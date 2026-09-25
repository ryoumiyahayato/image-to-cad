"""Deterministic PDF-native path evidence for Draftsman shadow pipelines.

This module deliberately stops at source evidence.  It does not infer tables,
logical entities, reconstruction, ownership, or CAD output.
"""

from __future__ import annotations

from collections import defaultdict
import ctypes
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from math import hypot, isfinite
from pathlib import Path
from typing import Any, Iterable, Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id


DRAFTSMAN_PDF_EVIDENCE_VERSION = "draftsman-pdf-path-evidence-v1"
DRAFTSMAN_PDF_LINE_FRAGMENT_VERSION = "draftsman-pdf-line-fragment-v1"


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _sha256(value: str, name: str) -> str:
    normalized = _required(value, name).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    if not isfinite(normalized):
        raise ValueError("PDF evidence coordinates must be finite")
    return 0.0 if normalized == 0.0 else normalized


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("A PDF point must contain exactly two coordinates")
    return _number(value[0]), _number(value[1])


class PdfPathSegmentKind(str, Enum):
    MOVE_TO = "MOVE_TO"
    LINE_TO = "LINE_TO"
    BEZIER_TO = "BEZIER_TO"


@dataclass(frozen=True)
class PdfPathSegment:
    kind: PdfPathSegmentKind
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
class PdfPathPaint:
    stroke: bool
    fill_mode: int
    stroke_width_pt: float
    stroke_rgba: tuple[int, int, int, int]
    fill_rgba: tuple[int, int, int, int]
    dash_array_pt: tuple[float, ...] = ()
    dash_phase_pt: float = 0.0

    def __post_init__(self) -> None:
        if int(self.fill_mode) < 0:
            raise ValueError("fill_mode must not be negative")
        object.__setattr__(self, "stroke_width_pt", _number(self.stroke_width_pt))
        object.__setattr__(
            self,
            "dash_array_pt",
            tuple(_number(value) for value in self.dash_array_pt),
        )
        object.__setattr__(self, "dash_phase_pt", _number(self.dash_phase_pt))
        for name, color in (
            ("stroke_rgba", self.stroke_rgba),
            ("fill_rgba", self.fill_rgba),
        ):
            if len(color) != 4 or any(not 0 <= int(value) <= 255 for value in color):
                raise ValueError(f"{name} must contain four 8-bit channels")

    @property
    def has_fill(self) -> bool:
        return int(self.fill_mode) != 0

    def to_dict(self) -> dict[str, object]:
        return {
            "stroke": bool(self.stroke),
            "fill_mode": int(self.fill_mode),
            "stroke_width_pt": self.stroke_width_pt,
            "stroke_rgba": list(self.stroke_rgba),
            "fill_rgba": list(self.fill_rgba),
            "dash_array_pt": list(self.dash_array_pt),
            "dash_phase_pt": self.dash_phase_pt,
        }


@dataclass(frozen=True)
class PdfPathEvidenceSeed:
    """Order-free semantic seed produced by a PDF object reader."""

    object_transform: tuple[float, float, float, float, float, float]
    segments: tuple[PdfPathSegment, ...]
    paint: PdfPathPaint

    def __post_init__(self) -> None:
        if len(self.object_transform) != 6:
            raise ValueError("PDF object transform must contain six values")
        object.__setattr__(
            self,
            "object_transform",
            tuple(_number(value) for value in self.object_transform),
        )
        if not self.segments:
            raise ValueError("PDF path evidence requires at least one segment")

    def identity_payload(self) -> dict[str, object]:
        return {
            "object_transform": list(self.object_transform),
            "segments": [segment.to_dict() for segment in self.segments],
            "paint": self.paint.to_dict(),
        }


@dataclass(frozen=True)
class PdfPathEvidence:
    stable_evidence_id: str
    source_document_id: str
    source_page: int
    source_sha256: str
    page_size_pt: tuple[float, float]
    page_transform_id: str
    object_transform: tuple[float, float, float, float, float, float]
    segments: tuple[PdfPathSegment, ...]
    paint: PdfPathPaint
    occurrence: int
    bounds_pt: tuple[float, float, float, float]
    schema_version: str = DRAFTSMAN_PDF_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _required(self.source_document_id, "source_document_id")
        if int(self.source_page) <= 0:
            raise ValueError("source_page must be positive")
        _sha256(self.source_sha256, "source_sha256")
        if len(self.page_size_pt) != 2 or any(float(value) <= 0 for value in self.page_size_pt):
            raise ValueError("page_size_pt must contain two positive values")
        if int(self.occurrence) <= 0:
            raise ValueError("occurrence must be positive")
        expected = semantic_id(
            "draftsman-pdf-path-evidence",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_evidence_id != expected:
            raise ValueError("stable_evidence_id does not match PDF path semantics")

    @classmethod
    def create(
        cls,
        *,
        source_document_id: str,
        source_page: int,
        source_sha256: str,
        page_size_pt: Sequence[float],
        page_transform_id: str,
        seed: PdfPathEvidenceSeed,
        occurrence: int = 1,
        schema_version: str = DRAFTSMAN_PDF_EVIDENCE_VERSION,
    ) -> PdfPathEvidence:
        page_size = _point(page_size_pt)
        points = tuple(segment.point for segment in seed.segments)
        x_values = tuple(point[0] for point in points)
        y_values = tuple(point[1] for point in points)
        bounds = (
            min(x_values),
            min(y_values),
            max(x_values),
            max(y_values),
        )
        identity = {
            "source_document_id": source_document_id,
            "source_page": int(source_page),
            "source_sha256": source_sha256.lower(),
            "page_size_pt": list(page_size),
            "page_transform_id": page_transform_id,
            **seed.identity_payload(),
            "occurrence": int(occurrence),
        }
        return cls(
            stable_evidence_id=semantic_id(
                "draftsman-pdf-path-evidence",
                schema_version,
                identity,
            ),
            source_document_id=source_document_id,
            source_page=int(source_page),
            source_sha256=source_sha256.lower(),
            page_size_pt=page_size,
            page_transform_id=page_transform_id,
            object_transform=seed.object_transform,
            segments=seed.segments,
            paint=seed.paint,
            occurrence=int(occurrence),
            bounds_pt=(
                _number(bounds[0]),
                _number(bounds[1]),
                _number(bounds[2]),
                _number(bounds[3]),
            ),
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "source_sha256": self.source_sha256.lower(),
            "page_size_pt": list(self.page_size_pt),
            "page_transform_id": self.page_transform_id,
            "object_transform": list(self.object_transform),
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
        }


@dataclass(frozen=True)
class PdfLineFragmentEvidence:
    stable_fragment_id: str
    parent_path_evidence_id: str
    source_document_id: str
    source_page: int
    page_transform_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    stroke_width_pt: float
    occurrence: int
    schema_version: str = DRAFTSMAN_PDF_LINE_FRAGMENT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _point(self.start))
        object.__setattr__(self, "end", _point(self.end))
        object.__setattr__(self, "stroke_width_pt", _number(self.stroke_width_pt))
        if self.length <= 0.0:
            raise ValueError("PDF line fragment must have positive length")
        expected = semantic_id(
            "draftsman-pdf-line-fragment",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_fragment_id != expected:
            raise ValueError("stable_fragment_id does not match line semantics")

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @classmethod
    def create(
        cls,
        *,
        parent: PdfPathEvidence,
        start: Sequence[float],
        end: Sequence[float],
        occurrence: int,
    ) -> PdfLineFragmentEvidence:
        normalized_start = _point(start)
        normalized_end = _point(end)
        if normalized_end < normalized_start:
            normalized_start, normalized_end = normalized_end, normalized_start
        identity = {
            "parent_path_evidence_id": parent.stable_evidence_id,
            "source_document_id": parent.source_document_id,
            "source_page": parent.source_page,
            "page_transform_id": parent.page_transform_id,
            "start": list(normalized_start),
            "end": list(normalized_end),
            "stroke_width_pt": parent.paint.stroke_width_pt,
            "occurrence": int(occurrence),
        }
        return cls(
            stable_fragment_id=semantic_id(
                "draftsman-pdf-line-fragment",
                DRAFTSMAN_PDF_LINE_FRAGMENT_VERSION,
                identity,
            ),
            parent_path_evidence_id=parent.stable_evidence_id,
            source_document_id=parent.source_document_id,
            source_page=parent.source_page,
            page_transform_id=parent.page_transform_id,
            start=normalized_start,
            end=normalized_end,
            stroke_width_pt=parent.paint.stroke_width_pt,
            occurrence=int(occurrence),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "parent_path_evidence_id": self.parent_path_evidence_id,
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "page_transform_id": self.page_transform_id,
            "start": list(self.start),
            "end": list(self.end),
            "stroke_width_pt": self.stroke_width_pt,
            "occurrence": int(self.occurrence),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_fragment_id": self.stable_fragment_id,
            **self.identity_payload(),
            "length": _number(self.length),
        }


@dataclass(frozen=True)
class PdfPathEvidenceManifest:
    source_document_id: str
    source_page: int
    source_sha256: str
    page_size_pt: tuple[float, float]
    page_transform_id: str
    paths: tuple[PdfPathEvidence, ...]
    schema_version: str = DRAFTSMAN_PDF_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.paths, key=lambda item: item.stable_evidence_id))
        if self.paths != ordered:
            raise ValueError("PDF path evidence must use canonical ID order")
        if len({item.stable_evidence_id for item in self.paths}) != len(self.paths):
            raise ValueError("PDF path evidence IDs must be unique")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-pdf-path-evidence-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": int(self.source_page),
                "source_sha256": self.source_sha256,
                "page_size_pt": list(self.page_size_pt),
                "page_transform_id": self.page_transform_id,
                "path_ids": [item.stable_evidence_id for item in self.paths],
            },
        )

    @property
    def native_path_count(self) -> int:
        return len(self.paths)

    def line_fragments(self) -> tuple[PdfLineFragmentEvidence, ...]:
        fragments: list[PdfLineFragmentEvidence] = []
        for path in self.paths:
            if not path.paint.stroke:
                continue
            raw_fragments: list[tuple[tuple[float, float], tuple[float, float]]] = []
            previous: tuple[float, float] | None = None
            subpath_start: tuple[float, float] | None = None
            for segment in path.segments:
                if segment.kind is PdfPathSegmentKind.MOVE_TO:
                    previous = segment.point
                    subpath_start = segment.point
                    continue
                if segment.kind is PdfPathSegmentKind.LINE_TO and previous is not None:
                    if segment.point != previous:
                        raw_fragments.append((previous, segment.point))
                    previous = segment.point
                    if (
                        segment.closes_subpath
                        and subpath_start is not None
                        and previous != subpath_start
                    ):
                        raw_fragments.append((previous, subpath_start))
                        previous = subpath_start
                    continue
                previous = segment.point

            keyed = sorted(
                raw_fragments,
                key=lambda item: canonical_json_bytes(
                    {
                        "start": list(min(item)),
                        "end": list(max(item)),
                    }
                ),
            )
            occurrences: dict[bytes, int] = defaultdict(int)
            for start, end in keyed:
                key = canonical_json_bytes(
                    {"start": list(min(start, end)), "end": list(max(start, end))}
                )
                occurrences[key] += 1
                fragments.append(
                    PdfLineFragmentEvidence.create(
                        parent=path,
                        start=start,
                        end=end,
                        occurrence=occurrences[key],
                    )
                )
        return tuple(sorted(fragments, key=lambda item: item.stable_fragment_id))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "source_sha256": self.source_sha256,
            "page_size_pt": list(self.page_size_pt),
            "page_transform_id": self.page_transform_id,
            "native_path_count": self.native_path_count,
            "paths": [item.to_dict() for item in self.paths],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def materialize_pdf_path_evidence(
    *,
    source_document_id: str,
    source_page: int,
    source_sha256: str,
    page_size_pt: Sequence[float],
    seeds: Iterable[PdfPathEvidenceSeed],
) -> PdfPathEvidenceManifest:
    """Materialize order-independent evidence IDs from source path semantics."""

    page_size = _point(page_size_pt)
    page_transform_id = semantic_id(
        "pdf-page-transform",
        DRAFTSMAN_PDF_EVIDENCE_VERSION,
        {
            "source_document_id": source_document_id,
            "source_page": int(source_page),
            "source_sha256": source_sha256.lower(),
            "source_space": "pdf-user-space",
            "target_space": "normalized-page-point",
            "matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "page_size_pt": list(page_size),
        },
    )
    ordered_seeds = sorted(
        tuple(seeds),
        key=lambda item: canonical_json_bytes(item.identity_payload()),
    )
    occurrences: dict[bytes, int] = defaultdict(int)
    paths: list[PdfPathEvidence] = []
    for seed in ordered_seeds:
        key = canonical_json_bytes(seed.identity_payload())
        occurrences[key] += 1
        paths.append(
            PdfPathEvidence.create(
                source_document_id=source_document_id,
                source_page=source_page,
                source_sha256=source_sha256,
                page_size_pt=page_size,
                page_transform_id=page_transform_id,
                seed=seed,
                occurrence=occurrences[key],
            )
        )
    return PdfPathEvidenceManifest(
        source_document_id=source_document_id,
        source_page=int(source_page),
        source_sha256=source_sha256.lower(),
        page_size_pt=page_size,
        page_transform_id=page_transform_id,
        paths=tuple(sorted(paths, key=lambda item: item.stable_evidence_id)),
    )


def _color(function: Any, raw_object: object) -> tuple[int, int, int, int]:
    channels = [ctypes.c_uint() for _ in range(4)]
    success = function(  # type: ignore[operator]
        raw_object,
        *(ctypes.byref(channel) for channel in channels),
    )
    if not success:
        return (0, 0, 0, 0)
    return tuple(int(channel.value) for channel in channels)  # type: ignore[return-value]


def _paint(raw: Any, raw_object: object) -> PdfPathPaint:
    width = ctypes.c_float()
    if not raw.FPDFPageObj_GetStrokeWidth(raw_object, ctypes.byref(width)):
        width.value = 0.0
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not raw.FPDFPath_GetDrawMode(
        raw_object,
        ctypes.byref(fill_mode),
        ctypes.byref(stroke),
    ):
        fill_mode.value = 0
        stroke.value = 0
    dash_count = int(raw.FPDFPageObj_GetDashCount(raw_object))
    dash_array: tuple[float, ...] = ()
    if dash_count > 0:
        values = (ctypes.c_float * dash_count)()
        if raw.FPDFPageObj_GetDashArray(raw_object, values, dash_count):
            dash_array = tuple(_number(values[index]) for index in range(dash_count))
    dash_phase = ctypes.c_float()
    if not raw.FPDFPageObj_GetDashPhase(raw_object, ctypes.byref(dash_phase)):
        dash_phase.value = 0.0
    return PdfPathPaint(
        stroke=bool(stroke.value),
        fill_mode=int(fill_mode.value),
        stroke_width_pt=float(width.value),
        stroke_rgba=_color(raw.FPDFPageObj_GetStrokeColor, raw_object),
        fill_rgba=_color(raw.FPDFPageObj_GetFillColor, raw_object),
        dash_array_pt=dash_array,
        dash_phase_pt=float(dash_phase.value),
    )


def extract_pdf_path_evidence(
    path: str | Path,
    *,
    source_document_id: str,
    page_number: int,
) -> PdfPathEvidenceManifest:
    """Extract normalized native PATH evidence without rendering the PDF."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() != ".pdf":
        raise ValueError("PDF-native evidence requires a PDF source")
    if int(page_number) <= 0:
        raise ValueError("page_number must be positive")

    try:
        import pypdfium2 as pdfium
        from pypdfium2 import raw
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise RuntimeError("pypdfium2 is required for PDF-native evidence") from exc

    source_sha = sha256(source.read_bytes()).hexdigest()
    document = pdfium.PdfDocument(str(source))
    try:
        if page_number > len(document):
            raise IndexError(f"PDF page is outside document: {page_number}/{len(document)}")
        page = document[page_number - 1]
        try:
            page_size = tuple(float(value) for value in page.get_size())
            seeds: list[PdfPathEvidenceSeed] = []
            for pdf_object in page.get_objects():
                if int(pdf_object.type) != int(raw.FPDF_PAGEOBJ_PATH):
                    continue
                matrix = pdf_object.get_matrix()
                segments: list[PdfPathSegment] = []
                segment_count = int(raw.FPDFPath_CountSegments(pdf_object.raw))
                for segment_index in range(segment_count):
                    raw_segment = raw.FPDFPath_GetPathSegment(
                        pdf_object.raw,
                        segment_index,
                    )
                    x_value = ctypes.c_float()
                    y_value = ctypes.c_float()
                    if not raw.FPDFPathSegment_GetPoint(
                        raw_segment,
                        ctypes.byref(x_value),
                        ctypes.byref(y_value),
                    ):
                        raise ValueError("PDFium could not read a path segment point")
                    point = matrix.on_point(float(x_value.value), float(y_value.value))
                    raw_kind = int(raw.FPDFPathSegment_GetType(raw_segment))
                    kind = {
                        int(raw.FPDF_SEGMENT_MOVETO): PdfPathSegmentKind.MOVE_TO,
                        int(raw.FPDF_SEGMENT_LINETO): PdfPathSegmentKind.LINE_TO,
                        int(raw.FPDF_SEGMENT_BEZIERTO): PdfPathSegmentKind.BEZIER_TO,
                    }.get(raw_kind)
                    if kind is None:
                        raise ValueError(f"Unsupported PDF path segment type: {raw_kind}")
                    segments.append(
                        PdfPathSegment(
                            kind=kind,
                            point=_point(point),
                            closes_subpath=bool(
                                raw.FPDFPathSegment_GetClose(raw_segment)
                            ),
                        )
                    )
                if segments:
                    seeds.append(
                        PdfPathEvidenceSeed(
                            object_transform=(
                                matrix.a,
                                matrix.b,
                                matrix.c,
                                matrix.d,
                                matrix.e,
                                matrix.f,
                            ),
                            segments=tuple(segments),
                            paint=_paint(raw, pdf_object.raw),
                        )
                    )
        finally:
            page.close()
    finally:
        document.close()

    return materialize_pdf_path_evidence(
        source_document_id=source_document_id,
        source_page=page_number,
        source_sha256=source_sha,
        page_size_pt=page_size,
        seeds=seeds,
    )
