from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom
import numpy as np

from .auxiliary_recognition import (
    MIN_CIRCLE_EXPORT_CONFIDENCE,
    CircleCandidate,
    TextCandidate,
)
from .image_loader import save_image
from .line_detect import LineSegment
from .scale_calibrator import ScaleCalibration


MIN_TEXT_EXPORT_CONFIDENCE = 0.60


@dataclass(frozen=True)
class ExportResult:
    path: Path
    line_count: int
    mm_per_pixel: float
    calibrated: bool
    skipped_line_count: int = 0
    circle_count: int = 0
    skipped_circle_count: int = 0
    text_count: int = 0
    skipped_text_count: int = 0
    underlay_path: Path | None = None
    dwg_path: Path | None = None
    output_format: str = "DXF"


LAYER_STYLES = {
    "SCAN_UNDERLAY": {"color": 8, "lineweight": 0},
    "OUTLINE": {"color": 1, "lineweight": 50},
    "WALL_OR_FRAME": {"color": 3, "lineweight": 25},
    "GRID_OR_AXIS": {"color": 5, "lineweight": 13},
    "HATCH": {"color": 6, "lineweight": 9},
    "HATCH_CANDIDATE": {"color": 4, "lineweight": 9},
    "DETAIL": {"color": 7, "lineweight": 9},
    "CIRCLE_CONFIRMED": {"color": 2, "lineweight": 18},
    "OCR_TEXT": {"color": 2, "lineweight": 9},
}


def filter_exportable_circles(
    circles: Sequence[CircleCandidate],
) -> list[CircleCandidate]:
    """Return the exact candidates eligible to become DXF CIRCLE entities."""
    valid: list[CircleCandidate] = []
    for circle in circles:
        values = (
            float(circle.center[0]),
            float(circle.center[1]),
            float(circle.radius),
            float(circle.confidence),
        )
        if (
            all(isfinite(value) for value in values)
            and circle.radius > 1e-9
            and circle.confidence >= MIN_CIRCLE_EXPORT_CONFIDENCE
        ):
            valid.append(circle)
    return valid


def filter_exportable_texts(
    texts: Sequence[TextCandidate],
) -> list[TextCandidate]:
    valid: list[TextCandidate] = []
    for text in texts:
        x, y, width, height = text.bbox
        values = (float(x), float(y), float(width), float(height), text.confidence)
        if (
            text.text.strip()
            and all(isfinite(float(value)) for value in values)
            and width > 0
            and height > 0
            and text.confidence >= MIN_TEXT_EXPORT_CONFIDENCE
        ):
            valid.append(text)
    return valid


def export_dxf(
    lines: list[LineSegment],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    circles: list[CircleCandidate] | None = None,
    texts: list[TextCandidate] | None = None,
    raster_image: np.ndarray | None = None,
    raster_output_path: str | Path | None = None,
) -> ExportResult:
    """Export editable vectors and an optional linked scan underlay.

    Uncalibrated coordinates remain unitless. The raster image is linked as an
    external IMAGE reference and is saved next to the DXF; it is not embedded.
    """
    if int(image_height) <= 0:
        raise ValueError("Image height must be greater than zero")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    calibrated = calibration is not None
    try:
        scale = calibration.mm_per_pixel if calibrated else 1.0
    except ValueError as exc:
        raise ValueError("Export scale must be a positive finite number") from exc
    if not isfinite(float(scale)) or scale <= 0:
        raise ValueError("Export scale must be a positive finite number")

    doc = ezdxf.new("R2010", setup=True)
    if calibrated:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
    else:
        doc.units = 0
        doc.header["$INSUNITS"] = 0
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1

    for layer_name, style in LAYER_STYLES.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    coordinates: list[tuple[float, float]] = []
    underlay_path: Path | None = None
    if raster_image is not None:
        if raster_image.size == 0 or raster_image.ndim not in (2, 3):
            raise ValueError("Raster underlay must be a non-empty image")
        raster_height, raster_width = raster_image.shape[:2]
        if raster_height != image_height:
            raise ValueError("Raster underlay height does not match vector coordinates")
        underlay_path = (
            Path(raster_output_path)
            if raster_output_path is not None
            else path.with_name(f"{path.stem}.scan.png")
        )
        save_image(underlay_path, raster_image)
        image_def = doc.add_image_def(
            filename=str(underlay_path.resolve()),
            size_in_pixel=(int(raster_width), int(raster_height)),
        )
        doc.set_raster_variables(
            frame=0,
            quality=1,
            units="mm" if calibrated else "none",
        )
        modelspace.add_image(
            image_def=image_def,
            insert=(0.0, 0.0),
            size_in_units=(raster_width * scale, raster_height * scale),
            rotation=0.0,
            dxfattribs={"layer": "SCAN_UNDERLAY"},
        )
        coordinates.extend(
            (
                (0.0, 0.0),
                (raster_width * scale, raster_height * scale),
            )
        )

    valid_lines: list[LineSegment] = []
    for line in lines:
        values = np.array([line.x1, line.y1, line.x2, line.y2], dtype=float)
        if not np.isfinite(values).all() or line.length <= 1e-9:
            continue
        start = (line.x1 * scale, (image_height - 1 - line.y1) * scale)
        end = (line.x2 * scale, (image_height - 1 - line.y2) * scale)
        layer = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        modelspace.add_line(start, end, dxfattribs={"layer": layer})
        valid_lines.append(line)
        coordinates.extend((start, end))

    requested_circles = list(circles or [])
    valid_circles = filter_exportable_circles(requested_circles)
    for circle in valid_circles:
        center = (
            circle.center[0] * scale,
            (image_height - 1 - circle.center[1]) * scale,
        )
        radius = circle.radius * scale
        modelspace.add_circle(
            center,
            radius,
            dxfattribs={"layer": "CIRCLE_CONFIRMED"},
        )
        coordinates.extend(
            (
                (center[0] - radius, center[1] - radius),
                (center[0] + radius, center[1] + radius),
            )
        )

    requested_texts = list(texts or [])
    valid_texts = filter_exportable_texts(requested_texts)
    for text in valid_texts:
        x, y, width, height = text.bbox
        insert = (
            x * scale,
            (image_height - 1 - (y + height)) * scale,
        )
        text_height = max(scale, height * scale * 0.85)
        entity = modelspace.add_text(
            text.text.strip(),
            height=text_height,
            dxfattribs={"layer": "OCR_TEXT"},
        )
        entity.set_placement(insert)
        coordinates.extend(
            (
                insert,
                (insert[0] + width * scale, insert[1] + height * scale),
            )
        )

    if coordinates:
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        doc.header["$EXTMIN"] = (min(xs), min(ys), 0.0)
        doc.header["$EXTMAX"] = (max(xs), max(ys), 0.0)
        try:
            zoom.extents(modelspace, factor=1.05)
        except Exception:
            center = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
            doc.set_modelspace_vport(
                height=max(1.0, (max(ys) - min(ys)) * 1.05),
                center=center,
            )
    else:
        doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
        doc.header["$EXTMAX"] = (0.0, 0.0, 0.0)

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp.dxf",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        doc.saveas(temporary_path)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return ExportResult(
        path,
        len(valid_lines),
        float(scale),
        calibrated,
        skipped_line_count=len(lines) - len(valid_lines),
        circle_count=len(valid_circles),
        skipped_circle_count=len(requested_circles) - len(valid_circles),
        text_count=len(valid_texts),
        skipped_text_count=len(requested_texts) - len(valid_texts),
        underlay_path=underlay_path,
    )
