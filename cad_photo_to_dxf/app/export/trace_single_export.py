from __future__ import annotations

from dataclasses import replace
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.core.cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from app.export.document_export import ExportResult
from app.core.structure import FinalStructure
from app.core.image_loader import save_image
from app.geometry.line_detect import LineSegment
from app.core.arc_types import ArcSegment
from app.core.trace_types import TracePath
from app.export.trace_entity_writer import write_page_entities, semantic_paths
from app.core.scale_calibrator import ScaleCalibration
from app.ocr.signature_overlay import SignatureRegion
from app.export.trace_dxf_entities import TRACE_LAYER_STYLES, TracePalette
from app.core.member_binding import ResolvedDraftsmanOutput, resolve_draftsman_output


def export_exact_trace_dxf(
    trace_paths: tuple[TracePath, ...],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    image_width: int | None = None,
    drawing_multiplier: float = 1.0,
    trace_color: int = 7,
    palette: TracePalette | None = None,
    straight_lines: tuple[LineSegment, ...] = (),
    arcs: tuple[ArcSegment, ...] = (),
    texts: tuple[TextCandidate, ...] = (),
    source_text_outline_paths: tuple[TracePath, ...] = (),
    uncertain_text_outline_paths: tuple[TracePath, ...] = (),
    semantic_outlines_prepartitioned: bool = False,
    signatures: tuple[SignatureRegion, ...] = (),
    logos=(),
    enclosure_records=(),
    stroke_presentation=None,
    raster_image: np.ndarray | None = None,
    raster_output_path: str | Path | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    resolved_output: ResolvedDraftsmanOutput | None = None,
    allow_empty: bool = False,
) -> ExportResult:
    if image_height <= 0:
        raise ValueError("Image height must be greater than zero")
    if not allow_empty and not trace_paths and not straight_lines and not arcs and not texts and not signatures and not logos:
        raise ValueError("At least one CAD entity is required")
    multiplier = float(drawing_multiplier)
    if not isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Drawing multiplier must be positive and finite")
    paper_scale = calibration.mm_per_pixel if calibration is not None else 1.0
    scale = float(paper_scale) * multiplier
    if not isfinite(scale) or scale <= 0:
        raise ValueError("Trace export scale must be positive and finite")

    checkpoint(cancellation_token)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010", setup=True)
    if calibration is not None:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
    else:
        doc.units = 0
        doc.header["$INSUNITS"] = 0
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1
    styles = {"SCAN_UNDERLAY": {"color": 8, "lineweight": 0}, **TRACE_LAYER_STYLES}
    for layer_name, style in styles.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)
    source_outline_layer = doc.layers.get("SOURCE_TEXT_OUTLINE")
    source_outline_layer.off()
    source_outline_layer.freeze()
    modelspace = doc.modelspace()
    coordinates: list[tuple[float, float]] = []
    underlay_path: Path | None = None
    resolved_width = int(image_width or 0)
    if resolved_width <= 0 and trace_paths:
        resolved_width = max(
            1,
            int(round(max(float(x) for trace in trace_paths for x, _y in trace.points))) + 1,
        )
    if resolved_width <= 0 and straight_lines:
        resolved_width = max(
            1,
            int(
                round(
                    max(
                        max(float(line.x1), float(line.x2))
                        for line in straight_lines
                    )
                )
            )
            + 1,
        )
    resolved_width = max(1, resolved_width)

    if raster_image is not None:
        if raster_image.size == 0 or raster_image.ndim not in (2, 3):
            raise ValueError("Raster underlay must be a non-empty image")
        raster_height, raster_width = raster_image.shape[:2]
        if raster_height != image_height:
            raise ValueError("Raster underlay height does not match trace coordinates")
        underlay_path = (
            Path(raster_output_path)
            if raster_output_path is not None
            else path.with_name(f"{path.stem}.scan.png")
        ).resolve()
        if underlay_path.parent != path.resolve().parent:
            raise ValueError("Raster underlay must be saved beside the DXF")
        save_image(underlay_path, raster_image)
        image_def = doc.add_image_def(
            filename=underlay_path.name,
            size_in_pixel=(int(raster_width), int(raster_height)),
        )
        doc.set_raster_variables(
            frame=0,
            quality=1,
            units="mm" if calibration is not None else "none",
        )
        modelspace.add_image(
            image_def=image_def,
            insert=(0.0, 0.0),
            size_in_units=(raster_width * scale, raster_height * scale),
            rotation=0.0,
            dxfattribs={"layer": "SCAN_UNDERLAY"},
        )
        coordinates.extend(((0.0, 0.0), (raster_width * scale, raster_height * scale)))

    def entity_progress(stage: str, fraction: float) -> None:
        report_progress(progress_callback, stage, 0.05 + 0.80 * fraction)

    def transform(x: float, y: float) -> tuple[float, float]:
        return (x * scale, (image_height - y) * scale)

    (line_count, trace_path_count, trace_vertex_count, text_count,
     signature_paths, entity_bounds, text_summary, signature_count, graphic_paths) = write_page_entities(
        doc, modelspace, trace_paths=trace_paths, straight_lines=straight_lines,
        arcs=arcs,
        stroke_presentation=stroke_presentation,
        texts=texts, signatures=signatures, transform=transform, output_path=path,
        logos=logos, enclosure_records=enclosure_records,
        source_size=(resolved_width, image_height), trace_color=trace_color, palette=palette,
        source_text_outline_paths=source_text_outline_paths,
        uncertain_text_outline_paths=uncertain_text_outline_paths,
        semantic_outlines_prepartitioned=semantic_outlines_prepartitioned,
        resolved_output=resolved_output, cancellation_token=cancellation_token,
        progress_callback=entity_progress)
    coordinates.extend(entity_bounds)
    if signature_count or graphic_paths:
        doc.set_raster_variables(
            frame=0,
            quality=1,
            units="mm" if calibration is not None else "none",
        )

    if coordinates:
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        doc.header["$EXTMIN"] = (min(xs), min(ys), 0.0)
        doc.header["$EXTMAX"] = (max(xs), max(ys), 0.0)
        if arcs:
            # ezdxf saves these layout extents back into the header.
            modelspace.dxf.extmin = doc.header['$EXTMIN']
            modelspace.dxf.extmax = doc.header['$EXTMAX']
        try:
            zoom.extents(modelspace, factor=1.03)
        except Exception:
            pass

    checkpoint(cancellation_token)
    report_progress(progress_callback, "cad-save", 0.92)
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
    report_progress(progress_callback, "cad-save", 1.0)

    return ExportResult(
        path=path,
        line_count=line_count,
        arc_count=len(arcs),
        mm_per_pixel=scale,
        calibrated=calibration is not None,
        text_count=text_count,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        drawing_scale=multiplier,
        underlay_path=underlay_path,
        signature_paths=signature_paths,
        graphic_paths=graphic_paths,
        ocr_candidate_count=text_summary.ocr_candidate_count,
        fallback_text_count=text_summary.fallback_outline_count,
        source_text_outline_count=(
            text_summary.source_outline_backup_count
        ),
        residual_graphic_count=text_summary.residual_graphic_count,
        signature_count=len(signature_paths),
        text_downgrade_reasons=text_summary.downgrade_reasons,
    )


def export_final_structure_dxf(
    structure: FinalStructure,
    output_path: str | Path,
    calibration: ScaleCalibration | None = None,
    *,
    drawing_multiplier: float = 1.0,
    trace_color: int = 7,
    palette: TracePalette | None = None,
    raster_image: np.ndarray | None = None,
    raster_output_path: str | Path | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    allow_empty: bool = False,
) -> ExportResult:
    """Export the same immutable structure instance used by the GUI preview."""

    resolved_output = resolve_draftsman_output(structure)
    structure.assert_valid()
    width, height = structure.source_size_px

    semantic_outlines_prepartitioned = any(
        mask is not None
        for mask in (
            structure.source_text_outline_mask,
            structure.uncertain_text_outline_mask,
        )
    )
    result = export_exact_trace_dxf(
        structure.contours,
        output_path,
        height,
        calibration,
        image_width=width,
        drawing_multiplier=drawing_multiplier,
        trace_color=trace_color,
        palette=palette,
        straight_lines=structure.straight_lines,
        arcs=structure.arcs,
        texts=structure.texts,
        source_text_outline_paths=semantic_paths(
            structure.source_text_outline_mask
        ),
        uncertain_text_outline_paths=semantic_paths(
            structure.uncertain_text_outline_mask
        ),
        semantic_outlines_prepartitioned=(
            semantic_outlines_prepartitioned
        ),
        signatures=structure.signatures,
        logos=structure.logos,
        enclosure_records=structure.provenance.get('engineering_enclosures', ()),
        stroke_presentation=structure.provenance.get('stroke_presentation'),
        raster_image=raster_image,
        raster_output_path=raster_output_path,
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
        resolved_output=resolved_output,
        allow_empty=allow_empty,
    )
    return replace(
        result,
        structure_id=structure.structure_id,
        logo_count=len(structure.logos),
        signature_count=len(structure.signatures),
    )
