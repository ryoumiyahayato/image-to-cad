from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .document_export import DocumentExportResult, DocumentPage, _resolve_raster
from .dxf_exporter import LAYER_STYLES
from .image_loader import save_image
from .ocr_outline_export import accepted_ocr_texts, add_ocr_outline_blocks
from .signature_overlay import add_signature_images, set_foreground_draw_order
from .text_output_contract import (
    TextOutputState,
    suppressible_ocr_texts,
    text_output_decisions,
    text_output_summary,
)
from .trace_dxf_entities import (
    TRACE_LAYER_STYLES,
    TracePalette,
    add_exact_trace_entities,
    add_straight_line_entities,
)


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
        "TEXT_FALLBACK_OUTLINE": (
            f"{prefix}_TEXT_FALLBACK_OUTLINE"
        ),
        "RESIDUAL_GRAPHIC": f"{prefix}_RESIDUAL_GRAPHIC",
        "OCR_TEXT": f"{prefix}_OCR_TEXT",
        "SIGNATURE_OVERLAY": f"{prefix}_SIGNATURE_OVERLAY",
    }


def _ensure_page_layers(doc, index: int) -> dict[str, str]:
    names = _page_layer_names(index)
    styles = {"SCAN_UNDERLAY": LAYER_STYLES["SCAN_UNDERLAY"], **TRACE_LAYER_STYLES}
    for base_name, layer_name in names.items():
        style = styles[base_name]
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)
        if index > 1:
            doc.layers.get(layer_name).off()
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
    line_count = 0
    trace_path_count = 0
    trace_vertex_count = 0
    text_count = 0
    ocr_candidate_count = 0
    fallback_text_count = 0
    residual_graphic_count = 0
    logo_count = 0
    signature_count = 0
    downgrade_reasons: Counter[str] = Counter()
    page_count = 0
    structure_ids: list[str] = []
    expected_pages = max(int(total_pages or 0), 1)
    origin_y = 0.0
    first_page_view: tuple[float, float] | None = None

    for index, page in enumerate(page_stream(), start=1):
        checkpoint(cancellation_token)
        page_count = index
        if page.page_number <= 0:
            raise ValueError("Page numbers must be positive")
        structure = page.final_structure
        if structure is not None:
            structure.assert_valid()
            trace_paths = structure.contours
            lines = structure.straight_lines
            texts = structure.texts
            signatures = structure.signatures
            vector_size = structure.source_size_px
            structure_ids.append(structure.structure_id)
        else:
            trace_paths = page.trace_paths
            lines = page.lines
            texts = page.texts
            signatures = page.signatures
            vector_size = page.vector_size_px
        if not trace_paths and not lines and not texts and not signatures:
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

        text_decisions = text_output_decisions(texts)
        text_summary = text_output_summary(texts)
        exportable_texts = accepted_ocr_texts(texts)
        suppressible_texts = suppressible_ocr_texts(texts)
        fallback_texts = tuple(
            decision.candidate
            for decision in text_decisions
            if decision.state is TextOutputState.TEXT_FALLBACK_OUTLINE
        )
        residual_texts = tuple(
            decision.candidate
            for decision in text_decisions
            if decision.state is TextOutputState.RESIDUAL_GRAPHIC
        )
        selected_palette = palette or TracePalette()
        if int(page.trace_color) != 7:
            selected_palette = TracePalette(
                int(page.trace_color),
                int(page.trace_color),
                int(page.trace_color),
            )
        current_line_count, _line_entities, _line_bounds = add_straight_line_entities(
            modelspace,
            lines,
            transform=transform,
            layer_name=layer_names["TRACE_STRAIGHT"],
            color=selected_palette.straight,
        )
        current_path_count, current_vertex_count, _entities, _bounds = add_exact_trace_entities(
            modelspace,
            trace_paths,
            transform=transform,
            color=page.trace_color,
            source_size=(vector_width, vector_height),
            palette=palette,
            ocr_texts=suppressible_texts,
            fallback_ocr_texts=fallback_texts,
            residual_ocr_texts=residual_texts,
            layer_names=layer_names,
            cancellation_token=cancellation_token,
            progress_callback=page_progress,
        )
        current_text_count, text_entities, _text_bounds = add_ocr_outline_blocks(
            doc,
            modelspace,
            exportable_texts,
            transform=transform,
            layer_name=layer_names["OCR_TEXT"],
            block_prefix=f"PAGE_{index:03d}_OCR_LINE",
        )
        current_signature_paths, signature_entities, _signature_bounds = (
            add_signature_images(
                doc,
                modelspace,
                signatures,
                transform=transform,
                output_path=(
                    path
                    if expected_pages == 1
                    else path.with_name(f"{path.stem}.page-{index:03d}.dxf")
                ),
                layer_name=layer_names["SIGNATURE_OVERLAY"],
                name_prefix=f"PAGE_{index:03d}_SIGNATURE",
            )
        )
        signature_paths.extend(current_signature_paths)
        set_foreground_draw_order(
            modelspace,
            [*text_entities, *signature_entities],
        )
        line_count += current_line_count
        trace_path_count += current_path_count
        trace_vertex_count += current_vertex_count
        text_count += current_text_count
        ocr_candidate_count += text_summary.ocr_candidate_count
        fallback_text_count += text_summary.fallback_outline_count
        residual_graphic_count += text_summary.residual_graphic_count
        logo_count += (
            len(structure.logos)
            if structure is not None
            else 0
        )
        signature_count += len(signatures)
        downgrade_reasons.update(dict(text_summary.downgrade_reasons))

        gap_units = max(1.0, float(modelspace_gap_mm) * page.drawing_scale)
        origin_y -= height_units + gap_units
        del raster

    doc.set_raster_variables(frame=0, quality=1, units="mm")
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
        circle_count=0,
        text_count=text_count,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        underlay_paths=tuple(underlays),
        layout_names=(),
        group_names=(),
        signature_paths=tuple(signature_paths),
        structure_ids=tuple(structure_ids),
        ocr_candidate_count=ocr_candidate_count,
        fallback_text_count=fallback_text_count,
        residual_graphic_count=residual_graphic_count,
        logo_count=logo_count,
        signature_count=signature_count,
        text_downgrade_reasons=tuple(
            sorted(downgrade_reasons.items())
        ),
    )
