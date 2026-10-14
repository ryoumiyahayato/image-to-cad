from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
import numpy as np
from app.ocr.auxiliary_recognition import CircleCandidate, TextCandidate
from app.geometry.line_detect import LineSegment
from app.core.trace_types import TracePath
from app.ocr.signature_overlay import SignatureRegion
from app.core.image_loader import load_image
if TYPE_CHECKING:
    from app.core.structure import FinalStructure

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
    trace_path_count: int = 0
    trace_vertex_count: int = 0
    drawing_scale: float = 1.0
    underlay_path: Path | None = None
    dwg_path: Path | None = None
    output_format: str = "DXF"
    signature_paths: tuple[Path, ...] = ()
    graphic_paths: tuple[Path, ...] = ()
    structure_id: str | None = None
    ocr_candidate_count: int = 0
    fallback_text_count: int = 0
    source_text_outline_count: int = 0
    residual_graphic_count: int = 0
    logo_count: int = 0
    signature_count: int = 0
    text_downgrade_reasons: tuple[tuple[str, int], ...] = ()
    arc_count: int = 0


@dataclass(frozen=True)
class DocumentPage:
    """One scan page plus reviewed entities in page pixel coordinates.

    ``raster`` may be omitted for queued PDF pages. In that case the exporter
    reloads ``source_path`` and ``source_page_index`` only when export starts,
    which avoids keeping several large PDF pages in memory while the user adds
    other files to the same document queue.
    """

    page_number: int
    raster: np.ndarray | None
    page_size_mm: tuple[float, float]
    lines: tuple[LineSegment, ...] = ()
    vector_size_px: tuple[int, int] | None = None
    label: str = ""
    circles: tuple[CircleCandidate, ...] = field(default_factory=tuple)
    texts: tuple[TextCandidate, ...] = field(default_factory=tuple)
    source_path: Path | None = None
    source_page_index: int | None = None
    raster_dpi: int = 200
    trace_paths: tuple[TracePath, ...] = field(default_factory=tuple)
    drawing_scale: float = 1.0
    trace_color: int = 7
    signatures: tuple[SignatureRegion, ...] = field(default_factory=tuple)
    final_structure: FinalStructure | None = None


@dataclass(frozen=True)
class DocumentExportResult:
    path: Path
    page_count: int
    line_count: int
    underlay_paths: tuple[Path, ...]
    layout_names: tuple[str, ...]
    circle_count: int = 0
    text_count: int = 0
    trace_path_count: int = 0
    trace_vertex_count: int = 0
    group_names: tuple[str, ...] = field(default_factory=tuple)
    signature_paths: tuple[Path, ...] = field(default_factory=tuple)
    graphic_paths: tuple[Path, ...] = field(default_factory=tuple)
    structure_ids: tuple[str, ...] = field(default_factory=tuple)
    ocr_candidate_count: int = 0
    fallback_text_count: int = 0
    source_text_outline_count: int = 0
    residual_graphic_count: int = 0
    logo_count: int = 0
    signature_count: int = 0
    text_downgrade_reasons: tuple[tuple[str, int], ...] = ()
    arc_count: int = 0


def _resolve_raster(page: DocumentPage) -> np.ndarray:
    if page.raster is not None:
        raster = page.raster
    elif page.source_path is not None:
        raster = load_image(
            page.source_path,
            page_index=page.source_page_index,
            pdf_dpi=page.raster_dpi,
        )
    else:
        raise ValueError(f"Page {page.page_number} has no raster source")
    if raster.ndim not in (2, 3) or raster.size == 0:
        raise ValueError(f"Page {page.page_number} has no raster image")
    return raster

