from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units

from app.core.cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from app.export.document_export import DocumentExportResult, DocumentPage, _resolve_raster
from app.core.image_loader import save_image
from app.export.trace_entity_writer import write_page_entities, semantic_paths
from app.export.trace_dxf_entities import TRACE_LAYER_STYLES, TracePalette
from app.core.member_binding import resolve_draftsman_output


def _require_first_page(
    pages: Iterable[DocumentPage],
) -> tuple[DocumentPage, Iterator[DocumentPage]]:
    iterator = iter(pages)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("At least one document page is required") from exc
    return first, iterator


def _page_layer_names(index: int) -> dict[str, str]:
    prefix = f"PAGE_{index:03d}"
    return {
        "SCAN_UNDERLAY": f"{prefix}_SCAN_UNDERLAY",
        "TRACE_STRAIGHT": f"{prefix}_TRACE_STRAIGHT",
        "TRACE_CURVE": f"{prefix}_TRACE_CURVE",
        "TRACE_TEXT_SYMBOL": f"{prefix}_TRACE_TEXT_SYMBOL",
        "SOURCE_TEXT_OUTLINE": f"{prefix}_SOURCE_TEXT_OUTLINE",
        "TEXT_FALLBACK_OUTLINE": (
            f"{prefix}_TEXT_FALLBACK_OUTLINE"
        ),
        "RESIDUAL_GRAPHIC": f"{prefix}_RESIDUAL_GRAPHIC",
        "OCR_TEXT": f"{prefix}_OCR_TEXT",
        "SIGNATURE_OVERLAY": f"{prefix}_SIGNATURE_OVERLAY",
        "LOGO_GRAPHIC": f"{prefix}_LOGO_GRAPHIC",
        "ENGINEERING_SYMBOL": f"{prefix}_ENGINEERING_SYMBOL",
    }


def _ensure_page_layers(doc, index: int) -> dict[str, str]:
    names = _page_layer_names(index)
    styles = {"SCAN_UNDERLAY": {"color": 8, "lineweight": 0}, **TRACE_LAYER_STYLES}
    for base_name, layer_name in names.items():
        style = styles[base_name]
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)
        if index > 1 or base_name == "SOURCE_TEXT_OUTLINE":
            doc.layers.get(layer_name).off()
        if base_name == "SOURCE_TEXT_OUTLINE":
            doc.layers.get(layer_name).freeze()
    return names


def _add_page_underlay(
    layout,
    image_def,
    *,
    insert: tuple[float, float],
    width_units: float,
    height_units: float,
    layer_name: str,
) -> object:
    return layout.add_image(
        image_def=image_def,
        insert=insert,
        size_in_units=(width_units, height_units),
        rotation=0.0,
        dxfattribs={"layer": layer_name},
    )


def export_trace_document_streaming(
    pages: Iterable[DocumentPage],
    output_path: str | Path,
    *,
    modelspace_gap_mm: float = 25.0,
    include_underlay: bool = False,
    total_pages: int | None = None,
    palette: TracePalette | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DocumentExportResult:
    """Export pages as direct model-space geometry and editable OCR lines."""

    first_page, remaining_pages = _require_first_page(pages)

    def page_stream():
        yield first_page
        yield from remaining_pages

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = units.MM
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1

    modelspace = doc.modelspace()
    underlays: list[Path] = []
    signature_paths: list[Path] = []
    graphic_paths: list[Path] = []
    line_count = 0
    arc_count = 0
    trace_path_count = 0
    trace_vertex_count = 0
    text_count = 0
    ocr_candidate_count = 0
    fallback_text_count = 0
    source_text_outline_count = 0
    residual_graphic_count = 0
    logo_count = 0
    signature_count = 0
    downgrade_reasons: Counter[str] = Counter()
    page_count = 0
    structure_ids: list[str] = []
    expected_pages = max(int(total_pages or 0), 1)
    origin_y = 0.0
    first_page_view: tuple[float, float] | None = None
    entity_extents = None

    for index, page in enumerate(page_stream(), start=1):
        checkpoint(cancellation_token)
        page_count = index
        if page.page_number <= 0:
            raise ValueError("Page numbers must be positive")
        structure = page.final_structure
        if structure is not None:
            structure.assert_valid()
            resolved_output = resolve_draftsman_output(structure)
            trace_paths = structure.contours
            source_text_outline_paths = semantic_paths(
                structure.source_text_outline_mask
            )
            uncertain_text_outline_paths = semantic_paths(
                structure.uncertain_text_outline_mask
            )
            semantic_outlines_prepartitioned = any(
                mask is not None
                for mask in (
                    structure.source_text_outline_mask,
                    structure.uncertain_text_outline_mask,
                )
            )
            lines = structure.straight_lines
            arcs = structure.arcs
            texts = structure.texts
            signatures = structure.signatures
            logos = structure.logos
            enclosure_records = structure.provenance.get('engineering_enclosures', ())
            stroke_presentation = structure.provenance.get('stroke_presentation')
            vector_size = structure.source_size_px
            structure_ids.append(structure.structure_id)
        else:
            resolved_output = None
            trace_paths = page.trace_paths
            source_text_outline_paths = ()
            uncertain_text_outline_paths = ()
            semantic_outlines_prepartitioned = False
            lines = page.lines
            arcs = ()
            texts = page.texts
            signatures = page.signatures
            logos, enclosure_records = (), ()
            stroke_presentation = None
            vector_size = page.vector_size_px
        if not trace_paths and not lines and not arcs and not texts and not signatures and not logos:
            raise ValueError(
                f"第 {page.page_number} 页尚未生成 CAD 内容。"
                "请先执行当前 PDF 全部页处理后再导出。"
            )
        page_width_mm, page_height_mm = page.page_size_mm
        if page_width_mm <= 0 or page_height_mm <= 0:
            raise ValueError(f"Page {page.page_number} has invalid paper dimensions")
        if page.drawing_scale <= 0:
            raise ValueError(f"Page {page.page_number} drawing scale must be positive")

        raster = None
        if vector_size is None or include_underlay:
            raster = _resolve_raster(page)
            raster_height, raster_width = raster.shape[:2]
            if vector_size is None:
                vector_size = (raster_width, raster_height)
        if vector_size is None:
            raise ValueError(f"Page {page.page_number} has no trace coordinate size")
        vector_width, vector_height = vector_size

        width_units = page_width_mm * page.drawing_scale
        height_units = page_height_mm * page.drawing_scale
        scale_x = width_units / max(float(vector_width), 1.0)
        scale_y = height_units / max(float(vector_height), 1.0)
        layer_names = _ensure_page_layers(doc, index)
        if first_page_view is None:
            first_page_view = (width_units, height_units)

        if include_underlay:
            assert raster is not None
            raster_height, raster_width = raster.shape[:2]
            scan_path = path.with_name(f"{path.stem}.page-{index:03d}.scan.png")
            save_image(scan_path, raster)
            underlays.append(scan_path)
            image_def = doc.add_image_def(
                filename=scan_path.name,
                size_in_pixel=(int(raster_width), int(raster_height)),
                name=f"SCAN_PAGE_{index:03d}",
            )
            _add_page_underlay(
                modelspace,
                image_def,
                insert=(0.0, origin_y),
                width_units=width_units,
                height_units=height_units,
                layer_name=layer_names["SCAN_UNDERLAY"],
            )

        page_base = (index - 1) / expected_pages
        page_span = 0.88 / expected_pages

        def page_progress(stage: str, fraction: float) -> None:
            report_progress(
                progress_callback,
                f"第 {index} 页：{stage}",
                page_base + page_span * fraction,
            )

        page_origin = origin_y

        def transform(x: float, y: float) -> tuple[float, float]:
            return (
                x * scale_x,
                page_origin + (vector_height - y) * scale_y,
            )

        (current_line_count, current_path_count, current_vertex_count,
         current_text_count, current_signature_paths, _bounds, text_summary,
         current_signature_count, current_graphic_paths) = write_page_entities(
            doc, modelspace, trace_paths=trace_paths, straight_lines=lines,
            arcs=arcs,
            texts=texts, signatures=signatures, transform=transform,
            logos=logos, enclosure_records=enclosure_records,
            stroke_presentation=stroke_presentation,
            output_path=(path if expected_pages == 1 else path.with_name(f"{path.stem}.page-{index:03d}.dxf")),
            source_size=(vector_width, vector_height), trace_color=page.trace_color,
            palette=palette, layer_names=layer_names,
            block_prefix=f"PAGE_{index:03d}_OCR_LINE", signature_prefix=f"PAGE_{index:03d}_SIGNATURE",
            source_text_outline_paths=source_text_outline_paths,
            uncertain_text_outline_paths=uncertain_text_outline_paths,
            semantic_outlines_prepartitioned=semantic_outlines_prepartitioned,
            resolved_output=resolved_output, cancellation_token=cancellation_token,
            progress_callback=page_progress)
        signature_paths.extend(current_signature_paths)
        page_bounds = list(_bounds)
        if include_underlay:
            page_bounds.extend(((0.0, page_origin), (width_units, page_origin + height_units)))
        if page_bounds:
            xs, ys = zip(*page_bounds)
            current_extents = (min(xs), min(ys), max(xs), max(ys))
            entity_extents = current_extents if entity_extents is None else (
                min(entity_extents[0], current_extents[0]),
                min(entity_extents[1], current_extents[1]),
                max(entity_extents[2], current_extents[2]),
                max(entity_extents[3], current_extents[3]),
            )
        graphic_paths.extend(current_graphic_paths)
        line_count += current_line_count
        arc_count += len(arcs)
        trace_path_count += current_path_count
        trace_vertex_count += current_vertex_count
        text_count += current_text_count
        ocr_candidate_count += text_summary.ocr_candidate_count
        fallback_text_count += text_summary.fallback_outline_count
        source_text_outline_count += (
            text_summary.source_outline_backup_count
        )
        residual_graphic_count += text_summary.residual_graphic_count
        logo_count += (
            len(structure.logos)
            if structure is not None
            else 0
        )
        signature_count += current_signature_count
        downgrade_reasons.update(dict(text_summary.downgrade_reasons))

        gap_units = max(1.0, float(modelspace_gap_mm) * page.drawing_scale)
        origin_y -= height_units + gap_units
        del raster

    doc.set_raster_variables(frame=0, quality=1, units="mm")
    if arc_count and entity_extents is not None:
        modelspace.dxf.extmin = (entity_extents[0], entity_extents[1], 0.0)
        modelspace.dxf.extmax = (entity_extents[2], entity_extents[3], 0.0)
    if first_page_view is not None:
        first_width, first_height = first_page_view
        doc.set_modelspace_vport(
            height=max(1.0, first_height * 1.03),
            center=(first_width * 0.5, first_height * 0.5),
        )

    checkpoint(cancellation_token)
    report_progress(progress_callback, "写入 DXF 文件", 0.92)
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
    report_progress(progress_callback, "DXF 写入完成", 1.0)

    return DocumentExportResult(
        path=path,
        page_count=page_count,
        line_count=line_count,
        arc_count=arc_count,
        circle_count=0,
        text_count=text_count,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        underlay_paths=tuple(underlays),
        layout_names=(),
        group_names=(),
        signature_paths=tuple(signature_paths),
        graphic_paths=tuple(graphic_paths),
        structure_ids=tuple(structure_ids),
        ocr_candidate_count=ocr_candidate_count,
        fallback_text_count=fallback_text_count,
        source_text_outline_count=source_text_outline_count,
        residual_graphic_count=residual_graphic_count,
        logo_count=logo_count,
        signature_count=signature_count,
        text_downgrade_reasons=tuple(
            sorted(downgrade_reasons.items())
        ),
    )
