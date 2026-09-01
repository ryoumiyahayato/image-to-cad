"""Rotation-aware native PDF vector evidence for boxed-symbol slices.

The frontend in this module is deliberately domain neutral.  It observes
filled frame-like paths, the native paths inside those frames, and nearby
paths that may later support topology.  It never assigns an electrical
identity and never emits CAD entities.
"""

from __future__ import annotations

from collections import defaultdict
import ctypes
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id


DRAFTSMAN_PDF_VECTOR_VERSION = "draftsman-pdf-vector-evidence-v1"
DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION = "draftsman-boxed-symbol-evidence-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    if not isfinite(normalized):
        raise ValueError("PDF vector evidence coordinates must be finite")
    return 0.0 if normalized == 0.0 else normalized


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("A vector point must contain two coordinates")
    return _number(value[0]), _number(value[1])


def _bounds(points: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    normalized = tuple(_point(point) for point in points)
    if not normalized:
        raise ValueError("Vector bounds require at least one point")
    xs = tuple(point[0] for point in normalized)
    ys = tuple(point[1] for point in normalized)
    return _number(min(xs)), _number(min(ys)), _number(max(xs)), _number(max(ys))


def _intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float = 0.0,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


class PdfVectorSegmentKind(str, Enum):
    MOVE_TO = "MOVE_TO"
    LINE_TO = "LINE_TO"
    BEZIER_TO = "BEZIER_TO"


@dataclass(frozen=True)
class PdfVectorSegment:
    kind: PdfVectorSegmentKind
    point: tuple[float, float]
    closes_subpath: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "point", _point(self.point))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "point": list(self.point),
            "closes_subpath": bool(self.closes_subpath),
        }


@dataclass(frozen=True)
class PdfVectorPaint:
    stroke: bool
    fill_mode: int
    stroke_width_pt: float
    dash_array_pt: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stroke_width_pt", _number(self.stroke_width_pt))
        object.__setattr__(
            self,
            "dash_array_pt",
            tuple(_number(value) for value in self.dash_array_pt),
        )

    @property
    def has_fill(self) -> bool:
        return int(self.fill_mode) != 0

    def to_dict(self) -> dict[str, object]:
        return {
            "stroke": bool(self.stroke),
            "fill_mode": int(self.fill_mode),
            "stroke_width_pt": self.stroke_width_pt,
            "dash_array_pt": list(self.dash_array_pt),
        }


@dataclass(frozen=True)
class PdfVectorPrimitiveSeed:
    segments: tuple[PdfVectorSegment, ...]
    paint: PdfVectorPaint

    @property
    def bounds_pt(self) -> tuple[float, float, float, float]:
        return _bounds(segment.point for segment in self.segments)

    def identity_payload(self) -> dict[str, object]:
        return {
            "segments": [segment.to_dict() for segment in self.segments],
            "paint": self.paint.to_dict(),
        }


@dataclass(frozen=True)
class PdfVectorPrimitiveEvidence:
    stable_evidence_id: str
    source_document_id: str
    source_page: int
    source_sha256: str
    page_transform_id: str
    segments: tuple[PdfVectorSegment, ...]
    paint: PdfVectorPaint
    occurrence: int
    bounds_pt: tuple[float, float, float, float]
    schema_version: str = DRAFTSMAN_PDF_VECTOR_VERSION

    @classmethod
    def create(
        cls,
        *,
        source_document_id: str,
        source_page: int,
        source_sha256: str,
        page_transform_id: str,
        seed: PdfVectorPrimitiveSeed,
        occurrence: int,
    ) -> PdfVectorPrimitiveEvidence:
        identity = {
            "source_document_id": source_document_id,
            "source_page": int(source_page),
            "source_sha256": source_sha256,
            "page_transform_id": page_transform_id,
            **seed.identity_payload(),
            "occurrence": int(occurrence),
        }
        return cls(
            stable_evidence_id=semantic_id(
                "draftsman-pdf-vector-primitive",
                DRAFTSMAN_PDF_VECTOR_VERSION,
                identity,
            ),
            source_document_id=source_document_id,
            source_page=int(source_page),
            source_sha256=source_sha256,
            page_transform_id=page_transform_id,
            segments=seed.segments,
            paint=seed.paint,
            occurrence=int(occurrence),
            bounds_pt=seed.bounds_pt,
        )

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "source_sha256": self.source_sha256,
            "page_transform_id": self.page_transform_id,
            "segments": [segment.to_dict() for segment in self.segments],
            "paint": self.paint.to_dict(),
            "occurrence": int(self.occurrence),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_evidence_id": self.stable_evidence_id,
            **self.identity_payload(),
            "bounds_pt": list(self.bounds_pt),
            "segment_count": self.segment_count,
        }


@dataclass(frozen=True)
class PdfBoxedSymbolEvidence:
    stable_candidate_id: str
    frame_bounds_pt: tuple[float, float, float, float]
    frame_primitive_ids: tuple[str, ...]
    interior_primitive_ids: tuple[str, ...]
    nearby_primitive_ids: tuple[str, ...]
    schema_version: str = DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION

    @classmethod
    def create(
        cls,
        *,
        frame_bounds_pt: Sequence[float],
        frame_primitive_ids: Iterable[str],
        interior_primitive_ids: Iterable[str],
        nearby_primitive_ids: Iterable[str],
    ) -> PdfBoxedSymbolEvidence:
        bounds = tuple(_number(value) for value in frame_bounds_pt)
        if len(bounds) != 4:
            raise ValueError("A frame requires four bounds values")
        frame_ids = tuple(sorted(set(frame_primitive_ids)))
        interior_ids = tuple(sorted(set(interior_primitive_ids)))
        nearby_ids = tuple(sorted(set(nearby_primitive_ids)))
        identity = {
            "frame_bounds_pt": list(bounds),
            "frame_primitive_ids": list(frame_ids),
            "interior_primitive_ids": list(interior_ids),
            "nearby_primitive_ids": list(nearby_ids),
        }
        return cls(
            stable_candidate_id=semantic_id(
                "draftsman-boxed-symbol-candidate",
                DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION,
                identity,
            ),
            frame_bounds_pt=bounds,  # type: ignore[arg-type]
            frame_primitive_ids=frame_ids,
            interior_primitive_ids=interior_ids,
            nearby_primitive_ids=nearby_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_candidate_id": self.stable_candidate_id,
            "frame_bounds_pt": list(self.frame_bounds_pt),
            "frame_primitive_ids": list(self.frame_primitive_ids),
            "interior_primitive_ids": list(self.interior_primitive_ids),
            "nearby_primitive_ids": list(self.nearby_primitive_ids),
        }


@dataclass(frozen=True)
class PdfBoxedSymbolEvidenceManifest:
    source_document_id: str
    source_page: int
    source_sha256: str
    source_native_path_count: int
    page_size_pt: tuple[float, float]
    page_rotation_degrees: int
    page_transform_id: str
    primitives: tuple[PdfVectorPrimitiveEvidence, ...]
    boxed_candidates: tuple[PdfBoxedSymbolEvidence, ...]
    schema_version: str = DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        if self.primitives != tuple(
            sorted(self.primitives, key=lambda item: item.stable_evidence_id)
        ):
            raise ValueError("PDF vector primitives must use canonical ID order")
        if self.boxed_candidates != tuple(
            sorted(self.boxed_candidates, key=lambda item: item.stable_candidate_id)
        ):
            raise ValueError("Boxed candidates must use canonical ID order")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-boxed-symbol-evidence-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": self.source_page,
                "source_sha256": self.source_sha256,
                "source_native_path_count": self.source_native_path_count,
                "page_size_pt": list(self.page_size_pt),
                "page_rotation_degrees": self.page_rotation_degrees,
                "page_transform_id": self.page_transform_id,
                "primitive_ids": [item.stable_evidence_id for item in self.primitives],
                "candidate_ids": [
                    item.stable_candidate_id for item in self.boxed_candidates
                ],
            },
        )

    def primitive_by_id(self) -> dict[str, PdfVectorPrimitiveEvidence]:
        return {item.stable_evidence_id: item for item in self.primitives}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_sha256": self.source_sha256,
            "source_native_path_count": self.source_native_path_count,
            "page_size_pt": list(self.page_size_pt),
            "page_rotation_degrees": self.page_rotation_degrees,
            "page_transform_id": self.page_transform_id,
            "primitive_count": len(self.primitives),
            "boxed_candidate_count": len(self.boxed_candidates),
            "primitives": [item.to_dict() for item in self.primitives],
            "boxed_candidates": [item.to_dict() for item in self.boxed_candidates],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class BoxedVectorEvidenceProfile:
    minimum_frame_size_pt: float = 9.0
    maximum_frame_size_pt: float = 17.0
    maximum_side_thickness_pt: float = 1.6
    side_alignment_tolerance_pt: float = 1.1
    frame_deduplication_tolerance_pt: float = 1.0
    nearby_margin_pt: float = 34.0


@dataclass(frozen=True)
class _Side:
    orientation: str
    bounds: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        return (
            _number((self.bounds[0] + self.bounds[2]) / 2.0),
            _number((self.bounds[1] + self.bounds[3]) / 2.0),
        )


def _normalize_point(
    point: Sequence[float],
    *,
    rotation_degrees: int,
    raw_page_size: tuple[float, float],
) -> tuple[float, float]:
    x_value, y_value = _point(point)
    width, height = raw_page_size
    rotation = int(rotation_degrees) % 360
    if rotation == 0:
        return x_value, y_value
    if rotation == 90:
        return y_value, _number(width - x_value)
    if rotation == 180:
        return _number(width - x_value), _number(height - y_value)
    if rotation == 270:
        return _number(height - y_value), x_value
    raise ValueError(f"Unsupported PDF page rotation: {rotation_degrees}")


def _normalize_object_bounds(
    raw_bounds: Sequence[float],
    *,
    rotation_degrees: int,
    raw_page_size: tuple[float, float],
) -> tuple[float, float, float, float]:
    left, bottom, right, top = raw_bounds
    return _bounds(
        _normalize_point(
            point,
            rotation_degrees=rotation_degrees,
            raw_page_size=raw_page_size,
        )
        for point in (
            (left, bottom),
            (left, top),
            (right, bottom),
            (right, top),
        )
    )


def _draw_mode(raw: Any, raw_object: object) -> tuple[int, bool]:
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not raw.FPDFPath_GetDrawMode(
        raw_object,
        ctypes.byref(fill_mode),
        ctypes.byref(stroke),
    ):
        return 0, False
    return int(fill_mode.value), bool(stroke.value)


def _path_paint(raw: Any, raw_object: object) -> PdfVectorPaint:
    fill_mode, stroke = _draw_mode(raw, raw_object)
    width = ctypes.c_float()
    if not raw.FPDFPageObj_GetStrokeWidth(raw_object, ctypes.byref(width)):
        width.value = 0.0
    dash_count = int(raw.FPDFPageObj_GetDashCount(raw_object))
    dash_array: tuple[float, ...] = ()
    if dash_count > 0:
        values = (ctypes.c_float * dash_count)()
        if raw.FPDFPageObj_GetDashArray(raw_object, values, dash_count):
            dash_array = tuple(_number(values[index]) for index in range(dash_count))
    return PdfVectorPaint(
        stroke=stroke,
        fill_mode=fill_mode,
        stroke_width_pt=float(width.value),
        dash_array_pt=dash_array,
    )


def _path_seed(
    raw: Any,
    pdf_object: Any,
    *,
    rotation_degrees: int,
    raw_page_size: tuple[float, float],
) -> PdfVectorPrimitiveSeed | None:
    matrix = pdf_object.get_matrix()
    segments: list[PdfVectorSegment] = []
    for segment_index in range(int(raw.FPDFPath_CountSegments(pdf_object.raw))):
        raw_segment = raw.FPDFPath_GetPathSegment(pdf_object.raw, segment_index)
        x_value = ctypes.c_float()
        y_value = ctypes.c_float()
        if not raw.FPDFPathSegment_GetPoint(
            raw_segment,
            ctypes.byref(x_value),
            ctypes.byref(y_value),
        ):
            continue
        transformed = matrix.on_point(float(x_value.value), float(y_value.value))
        point = _normalize_point(
            transformed,
            rotation_degrees=rotation_degrees,
            raw_page_size=raw_page_size,
        )
        kind = {
            int(raw.FPDF_SEGMENT_MOVETO): PdfVectorSegmentKind.MOVE_TO,
            int(raw.FPDF_SEGMENT_LINETO): PdfVectorSegmentKind.LINE_TO,
            int(raw.FPDF_SEGMENT_BEZIERTO): PdfVectorSegmentKind.BEZIER_TO,
        }.get(int(raw.FPDFPathSegment_GetType(raw_segment)))
        if kind is None:
            continue
        segments.append(
            PdfVectorSegment(
                kind=kind,
                point=point,
                closes_subpath=bool(raw.FPDFPathSegment_GetClose(raw_segment)),
            )
        )
    if not segments:
        return None
    return PdfVectorPrimitiveSeed(tuple(segments), _path_paint(raw, pdf_object.raw))


def _deduplicate_sides(
    sides: Iterable[_Side],
    *,
    tolerance: float,
) -> tuple[_Side, ...]:
    groups: list[list[_Side]] = []
    for side in sorted(
        sides,
        key=lambda item: (item.orientation, item.center, item.bounds),
    ):
        for group in groups:
            reference = group[0]
            if reference.orientation != side.orientation:
                continue
            if all(
                abs(first - second) <= tolerance
                for first, second in zip(reference.bounds, side.bounds, strict=True)
            ):
                group.append(side)
                break
        else:
            groups.append([side])
    result: list[_Side] = []
    for group in groups:
        result.append(
            _Side(
                group[0].orientation,
                tuple(
                    _number(sum(item.bounds[index] for item in group) / len(group))
                    for index in range(4)
                ),  # type: ignore[arg-type]
            )
        )
    return tuple(result)


def _find_frames(
    sides: Iterable[_Side],
    profile: BoxedVectorEvidenceProfile,
) -> tuple[tuple[float, float, float, float], ...]:
    deduplicated = _deduplicate_sides(
        sides,
        tolerance=profile.frame_deduplication_tolerance_pt,
    )
    vertical = tuple(side for side in deduplicated if side.orientation == "VERTICAL")
    horizontal = tuple(side for side in deduplicated if side.orientation == "HORIZONTAL")
    frames: list[tuple[float, float, float, float]] = []
    tolerance = profile.side_alignment_tolerance_pt
    for left in vertical:
        for right in vertical:
            x_left = left.center[0]
            x_right = right.center[0]
            width = x_right - x_left
            if not profile.minimum_frame_size_pt <= width <= profile.maximum_frame_size_pt:
                continue
            if (
                abs(left.bounds[1] - right.bounds[1]) > tolerance
                or abs(left.bounds[3] - right.bounds[3]) > tolerance
            ):
                continue
            y_bottom = (left.bounds[1] + right.bounds[1]) / 2.0
            y_top = (left.bounds[3] + right.bounds[3]) / 2.0
            height = y_top - y_bottom
            if not profile.minimum_frame_size_pt <= height <= profile.maximum_frame_size_pt:
                continue
            bottom = any(
                abs(side.center[1] - y_bottom) <= tolerance
                and abs(side.bounds[0] - x_left) <= tolerance
                and abs(side.bounds[2] - x_right) <= tolerance
                for side in horizontal
            )
            top = any(
                abs(side.center[1] - y_top) <= tolerance
                and abs(side.bounds[0] - x_left) <= tolerance
                and abs(side.bounds[2] - x_right) <= tolerance
                for side in horizontal
            )
            if bottom and top:
                frames.append(
                    (
                        _number(x_left),
                        _number(y_bottom),
                        _number(x_right),
                        _number(y_top),
                    )
                )
    ordered: list[tuple[float, float, float, float]] = []
    for frame in sorted(set(frames)):
        if any(
            all(
                abs(first - second) <= profile.frame_deduplication_tolerance_pt
                for first, second in zip(frame, existing, strict=True)
            )
            for existing in ordered
        ):
            continue
        ordered.append(frame)
    return tuple(ordered)


def _materialize_primitives(
    *,
    source_document_id: str,
    source_page: int,
    source_sha256: str,
    page_transform_id: str,
    seeds: Iterable[PdfVectorPrimitiveSeed],
) -> tuple[PdfVectorPrimitiveEvidence, ...]:
    ordered = sorted(
        seeds,
        key=lambda seed: canonical_json_bytes(seed.identity_payload()),
    )
    occurrences: dict[bytes, int] = defaultdict(int)
    result: list[PdfVectorPrimitiveEvidence] = []
    for seed in ordered:
        key = canonical_json_bytes(seed.identity_payload())
        occurrences[key] += 1
        result.append(
            PdfVectorPrimitiveEvidence.create(
                source_document_id=source_document_id,
                source_page=source_page,
                source_sha256=source_sha256,
                page_transform_id=page_transform_id,
                seed=seed,
                occurrence=occurrences[key],
            )
        )
    return tuple(sorted(result, key=lambda item: item.stable_evidence_id))


def extract_pdf_boxed_symbol_evidence(
    path: str | Path,
    *,
    source_document_id: str,
    page_number: int,
    profile: BoxedVectorEvidenceProfile | None = None,
) -> PdfBoxedSymbolEvidenceManifest:
    """Extract geometric boxed-symbol candidates without assigning identity."""

    selected_profile = profile or BoxedVectorEvidenceProfile()
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        import pypdfium2 as pdfium
        from pypdfium2 import raw
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pypdfium2 is required for PDF-native evidence") from exc

    source_sha = sha256(source.read_bytes()).hexdigest()
    document = pdfium.PdfDocument(str(source))
    try:
        if page_number <= 0 or page_number > len(document):
            raise IndexError(f"PDF page is outside document: {page_number}/{len(document)}")
        page = document[page_number - 1]
        try:
            rotation = int(page.get_rotation()) % 360
            page_size = tuple(_number(value) for value in page.get_size())
            raw_bbox = page.get_bbox()
            raw_page_size = (
                _number(raw_bbox[2] - raw_bbox[0]),
                _number(raw_bbox[3] - raw_bbox[1]),
            )
            native_path_count = 0
            sides: list[_Side] = []
            for pdf_object in page.get_objects():
                if int(pdf_object.type) != int(raw.FPDF_PAGEOBJ_PATH):
                    continue
                native_path_count += 1
                fill_mode, _ = _draw_mode(raw, pdf_object.raw)
                if fill_mode == 0:
                    continue
                bounds = _normalize_object_bounds(
                    pdf_object.get_bounds(),
                    rotation_degrees=rotation,
                    raw_page_size=raw_page_size,
                )
                width = bounds[2] - bounds[0]
                height = bounds[3] - bounds[1]
                if (
                    selected_profile.minimum_frame_size_pt <= height
                    <= selected_profile.maximum_frame_size_pt
                    and 0.0 < width <= selected_profile.maximum_side_thickness_pt
                ):
                    sides.append(_Side("VERTICAL", bounds))
                if (
                    selected_profile.minimum_frame_size_pt <= width
                    <= selected_profile.maximum_frame_size_pt
                    and 0.0 < height <= selected_profile.maximum_side_thickness_pt
                ):
                    sides.append(_Side("HORIZONTAL", bounds))
            frames = _find_frames(sides, selected_profile)
            expanded = tuple(
                (
                    frame[0] - selected_profile.nearby_margin_pt,
                    frame[1] - selected_profile.nearby_margin_pt,
                    frame[2] + selected_profile.nearby_margin_pt,
                    frame[3] + selected_profile.nearby_margin_pt,
                )
                for frame in frames
            )
            seeds: list[PdfVectorPrimitiveSeed] = []
            for pdf_object in page.get_objects():
                if int(pdf_object.type) != int(raw.FPDF_PAGEOBJ_PATH):
                    continue
                bounds = _normalize_object_bounds(
                    pdf_object.get_bounds(),
                    rotation_degrees=rotation,
                    raw_page_size=raw_page_size,
                )
                if not any(_intersects(bounds, region) for region in expanded):
                    continue
                seed = _path_seed(
                    raw,
                    pdf_object,
                    rotation_degrees=rotation,
                    raw_page_size=raw_page_size,
                )
                if seed is not None:
                    seeds.append(seed)
        finally:
            page.close()
    finally:
        document.close()

    page_transform_id = semantic_id(
        "pdf-page-transform",
        DRAFTSMAN_PDF_VECTOR_VERSION,
        {
            "source_document_id": source_document_id,
            "source_page": int(page_number),
            "source_sha256": source_sha,
            "source_space": "pdf-user-space",
            "target_space": "normalized-page-point",
            "page_rotation_degrees": rotation,
            "raw_page_size_pt": list(raw_page_size),
            "page_size_pt": list(page_size),
        },
    )
    primitives = _materialize_primitives(
        source_document_id=source_document_id,
        source_page=page_number,
        source_sha256=source_sha,
        page_transform_id=page_transform_id,
        seeds=seeds,
    )
    candidates: list[PdfBoxedSymbolEvidence] = []
    for frame in frames:
        frame_ids = []
        interior_ids = []
        nearby_ids = []
        expanded_frame = (
            frame[0] - selected_profile.nearby_margin_pt,
            frame[1] - selected_profile.nearby_margin_pt,
            frame[2] + selected_profile.nearby_margin_pt,
            frame[3] + selected_profile.nearby_margin_pt,
        )
        for primitive in primitives:
            bounds = primitive.bounds_pt
            if _intersects(bounds, expanded_frame):
                nearby_ids.append(primitive.stable_evidence_id)
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            near_vertical = (
                primitive.paint.has_fill
                and height >= selected_profile.minimum_frame_size_pt
                and width <= selected_profile.maximum_side_thickness_pt
                and (
                    abs((bounds[0] + bounds[2]) / 2.0 - frame[0])
                    <= selected_profile.side_alignment_tolerance_pt
                    or abs((bounds[0] + bounds[2]) / 2.0 - frame[2])
                    <= selected_profile.side_alignment_tolerance_pt
                )
            )
            near_horizontal = (
                primitive.paint.has_fill
                and width >= selected_profile.minimum_frame_size_pt
                and height <= selected_profile.maximum_side_thickness_pt
                and (
                    abs((bounds[1] + bounds[3]) / 2.0 - frame[1])
                    <= selected_profile.side_alignment_tolerance_pt
                    or abs((bounds[1] + bounds[3]) / 2.0 - frame[3])
                    <= selected_profile.side_alignment_tolerance_pt
                )
            )
            if near_vertical or near_horizontal:
                if _intersects(bounds, expanded_frame):
                    frame_ids.append(primitive.stable_evidence_id)
            if (
                primitive.paint.stroke
                and not primitive.paint.has_fill
                and _contains(frame, bounds, tolerance=0.5)
            ):
                interior_ids.append(primitive.stable_evidence_id)
        candidates.append(
            PdfBoxedSymbolEvidence.create(
                frame_bounds_pt=frame,
                frame_primitive_ids=frame_ids,
                interior_primitive_ids=interior_ids,
                nearby_primitive_ids=nearby_ids,
            )
        )
    return PdfBoxedSymbolEvidenceManifest(
        source_document_id=source_document_id,
        source_page=int(page_number),
        source_sha256=source_sha,
        source_native_path_count=native_path_count,
        page_size_pt=page_size,  # type: ignore[arg-type]
        page_rotation_degrees=rotation,
        page_transform_id=page_transform_id,
        primitives=primitives,
        boxed_candidates=tuple(
            sorted(candidates, key=lambda item: item.stable_candidate_id)
        ),
    )
