from __future__ import annotations
from typing import TYPE_CHECKING, Mapping
import numpy as np
from app.core.structure import FinalStructure
from app.core.arc_types import ArcSegment
if TYPE_CHECKING:
    from app.ocr.auxiliary_recognition import TextCandidate
    from app.geometry.line_detect import LineSegment
    from app.ocr.logo_detection import LogoRegion
    from app.geometry.raster_trace import RasterTraceResult
    from app.core.trace_types import TracePath
    from app.ocr.signature_overlay import SignatureRegion

def build_final_structure(
    *,
    source_size_px: tuple[int, int],
    contour_binary: np.ndarray,
    contours: tuple[TracePath, ...],
    straight_lines: tuple[LineSegment, ...] = (),
    texts: tuple[TextCandidate, ...] = (),
    logos: tuple[LogoRegion, ...] = (),
    signatures: tuple[SignatureRegion, ...] = (),
    editable_text_source_mask: np.ndarray | None = None,
    source_text_outline_mask: np.ndarray | None = None,
    uncertain_text_outline_mask: np.ndarray | None = None,
    preview_binary: np.ndarray | None = None,
    threshold: int = 128,
    warnings: tuple[str, ...] = (),
    provenance: Mapping[str, object] | None = None,
    observations: tuple[Mapping[str, object], ...] = (),
    arcs: tuple[ArcSegment, ...] = (),
) -> FinalStructure:
    structure = FinalStructure(
        source_size_px=source_size_px,
        contour_binary=contour_binary,
        contours=contours,
        straight_lines=straight_lines,
        texts=texts,
        logos=logos,
        signatures=signatures,
        editable_text_source_mask=editable_text_source_mask,
        source_text_outline_mask=source_text_outline_mask,
        uncertain_text_outline_mask=uncertain_text_outline_mask,
        preview_binary=preview_binary,
        threshold=threshold,
        warnings=warnings,
        provenance=provenance or {},
        observations=observations,
        arcs=arcs,
    )
    if "draftsman_output_v1" in structure.provenance:
        # Import here: the resolver consumes FinalStructure and must not own a
        # second geometry model.
        from app.core.member_binding import resolve_draftsman_output

        resolve_draftsman_output(structure, required=True)
    return structure


def final_structure_from_trace_result(
    result: RasterTraceResult,
) -> FinalStructure:
    existing = getattr(result, "final_structure", None)
    if existing is not None:
        return existing
    height, width = result.binary.shape[:2]
    return build_final_structure(
        source_size_px=(width, height),
        contour_binary=result.binary,
        contours=tuple(result.paths),
        straight_lines=tuple(result.straight_lines),
        arcs=tuple(result.arcs),
        texts=tuple(result.texts),
        logos=tuple(getattr(result, "logos", ())),
        signatures=tuple(result.signatures),
        preview_binary=result.preview_binary,
        threshold=int(result.threshold),
        warnings=tuple(result.warnings),
        provenance={"adapter": "RasterTraceResult"},
    )
