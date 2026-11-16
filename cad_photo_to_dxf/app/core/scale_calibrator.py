from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.ocr.auxiliary_recognition import TextCandidate


@dataclass
class ScaleCalibration:
    point1: tuple[float, float]
    point2: tuple[float, float]
    actual_length_mm: float
    paper_size_px: tuple[int, int] | None = None
    vertical_mm_per_pixel: float | None = None
    paper_corners_at_centers: bool = False
    known_length: bool = False

    @classmethod
    def for_paper(
        cls, size_px: tuple[int, int], size_mm: tuple[float, float], *,
        corners_at_centers: bool = False,
    ) -> ScaleCalibration:
        """Use outer edges for rendered pages and corner centers for a warp."""
        width, height = size_px
        width_span, height_span = width - corners_at_centers, height - corners_at_centers
        if min(width_span, height_span) <= 0:
            raise ValueError("Paper calibration has an empty pixel span")
        return cls(
            (0., 0.), (float(width_span), 0.), size_mm[0], (width, height),
            size_mm[1] / height_span, corners_at_centers,
        )

    @classmethod
    def for_raster_dpi(cls, size_px: tuple[int, int], dpi: float) -> ScaleCalibration:
        pitch = 25.4 / dpi
        return cls.for_paper(size_px, (size_px[0] * pitch, size_px[1] * pitch))

    @property
    def pixel_distance(self) -> float:
        coordinates = (*self.point1, *self.point2)
        if not all(math.isfinite(float(value)) for value in coordinates):
            raise ValueError("Calibration point coordinates must be finite")
        distance = math.dist(self.point1, self.point2)
        if not math.isfinite(distance):
            raise ValueError("Calibration pixel distance must be finite")
        return distance

    @property
    def mm_per_pixel(self) -> float:
        distance = self.pixel_distance
        if distance <= 1e-9:
            raise ValueError("Calibration points must not be identical")
        actual_length = float(self.actual_length_mm)
        if not math.isfinite(actual_length) or actual_length <= 0:
            raise ValueError("Actual length must be a positive finite number")
        scale = actual_length / distance
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Calibration scale must be a positive finite number")
        return scale


@dataclass(frozen=True)
class RasterToCad:
    """Map a raster window into a y-up CAD frame."""

    scale_x: float
    scale_y: float
    left: float
    top: float
    distinguish_pixel_centers: bool

    def edge(self, x: float, y: float) -> tuple[float, float]:
        return self.left + x * self.scale_x, self.top - y * self.scale_y

    def center(self, x: float, y: float) -> tuple[float, float]:
        offset = .5 if self.distinguish_pixel_centers else 0.
        return self.edge(x + offset, y + offset)


def raster_to_cad(
    size_px: tuple[int, int], calibration: ScaleCalibration | None,
    *, multiplier: float = 1., crop: tuple[int, int, int, int] | None = None,
    origin_y: float = 0.,
) -> RasterToCad:
    width, height = size_px
    sx = multiplier * (calibration.mm_per_pixel if calibration else 1.)
    if calibration is None or calibration.paper_size_px is None:
        # Existing callers and saved two-point calibrations retain their frame.
        return RasterToCad(sx, sx, 0., origin_y + height * sx, False)

    sy = multiplier * float(calibration.vertical_mm_per_pixel)
    if not math.isfinite(sy) or sy <= 0:
        raise ValueError("Invalid vertical paper calibration")
    page_width, page_height = calibration.paper_size_px
    left, top, right, bottom = crop or (0, 0, page_width, page_height)
    if not (0 <= left < right <= page_width and 0 <= top < bottom <= page_height
            and (right - left, bottom - top) == (width, height)):
        raise ValueError("Paper calibration and raster window use different grids")
    inset = .5 if calibration.paper_corners_at_centers else 0.
    return RasterToCad(sx, sy, (left - inset) * sx,
                       origin_y + (page_height - top - inset) * sy, True)


_NOT_TO_SCALE = re.compile(
    r"\b(?:N\s*\.\s*T\s*\.\s*S|NOT\s+TO\s+SCALE|SCALE(?:\s*[:=]\s*|\s+)NONE)\b",
    re.I,
)
_SHEET_SUBJECT = re.compile(r"(?:THIS|ENTIRE)\s+(?:SHEET|PAGE)|ALL\s+VIEWS", re.I)
_VIEW_SUBJECT = re.compile(r"^(?:DETAIL|SECTION|ELEVATION|VIEW|PLAN)\b", re.I)

CoordinateSpace = Literal["paper_mm", "model_mm", "pixel"]


@dataclass(frozen=True)
class ScaleNote:
    text: str
    bbox_px: tuple[int, int, int, int]
    scope: Literal["sheet", "view", "unknown"]


@dataclass(frozen=True)
class DrawingScaleDecision:
    multiplier: float
    coordinate_space: CoordinateSpace
    notes: tuple[ScaleNote, ...]
    warning: str | None = None


def _scale_notes(texts: Iterable[TextCandidate]) -> Iterable[ScaleNote]:
    for candidate in texts:
        match = _NOT_TO_SCALE.search(candidate.text)
        if match is None:
            continue
        subject = candidate.text[:match.start()].strip(" \t:–-")
        subject = re.sub(r"\s+(?:IS|ARE)$", "", subject, flags=re.I)
        suffix = candidate.text[match.end():].strip(" .")
        if _SHEET_SUBJECT.fullmatch(subject) and not suffix:
            scope = "sheet"
        elif _VIEW_SUBJECT.match(subject):
            scope = "view"
        else:
            scope = "unknown"
        yield ScaleNote(candidate.text, candidate.bbox, scope)


def resolve_drawing_scale(
    texts: Iterable[TextCandidate],
    requested_multiplier: float,
    *,
    coordinate_space: CoordinateSpace = "paper_mm",
) -> DrawingScaleDecision:
    notes = tuple(_scale_notes(texts))
    if coordinate_space != "paper_mm":
        return DrawingScaleDecision(1., coordinate_space, notes)
    if notes:
        # A text box locates an annotation. It does not delineate the view it describes.
        warning = (
            "整页注记标明 N.T.S. 或 SCALE NONE，导出保留纸面坐标。"
            if all(note.scope == "sheet" for note in notes)
            else "发现 N.T.S. 或 SCALE NONE 注记。缺少视图分区证据，导出保留纸面坐标。"
        )
        return DrawingScaleDecision(1., "paper_mm", notes, warning)
    space = "paper_mm" if requested_multiplier == 1. else "model_mm"
    return DrawingScaleDecision(requested_multiplier, space, notes)


def create_calibration(
    points: Iterable[Iterable[float]],
    actual_length_mm: float,
) -> ScaleCalibration:
    values: list[tuple[float, float]] = []
    for point in points:
        coordinates = tuple(map(float, point))
        if len(coordinates) != 2:
            raise ValueError("Each calibration point must contain exactly two coordinates")
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Calibration point coordinates must be finite")
        values.append((coordinates[0], coordinates[1]))
    if len(values) != 2:
        raise ValueError("Exactly two calibration points are required")
    calibration = ScaleCalibration(values[0], values[1], float(actual_length_mm), known_length=True)
    _ = calibration.mm_per_pixel
    return calibration
