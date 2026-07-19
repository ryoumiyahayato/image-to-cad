from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .document_export import (
    DocumentExportResult,
    DocumentPage,
    _resolve_raster,
    _safe_group_name,
    _safe_layout_name,
)
from .dxf_exporter import LAYER_STYLES
from .image_loader import save_image
from .trace_dxf_entities import TRACE_LAYER_STYLES, TracePalette, add_exact_trace_entities


def _require_first_page(
    pages: Iterable[DocumentPage],
) -> tuple[DocumentPage, Iterator[DocumentPage]]:
    iterator = iter(pages)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("At least one document page is required") from exc
    return first, iterator


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
    """Write each page once in model space and show it through paper viewports.

    Exact contour boundaries are written once.  Solid HATCH is restricted to
    small text/symbol regions; large or complex page linework remains editable
    contour polylines because broad multi-loop HATCHes are rendered incorrectly
    by some CAD viewers.  PAGE layouts are lightweight viewports and do not
    duplicate the model geometry.
    """

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
    for layer_name, style in {**LAYER_STYLES, **TRACE_LAYER_STYLES}.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    underlays: list[Path] = []
    layout_names: list[str] = []
    group_names: list[str] = []
    trace_path_count = 0
    trace_vertex_count = 0
    page_count = 0
    model_y = 0.0
    expected_pages = max(int(total_pages or 0), 1)

    for index, page in enumerate(page_stream(), start=1):
        checkpoint(cancellation_token)
        page_count = index
        if page.page_number <= 0:
            raise ValueError("Page numbers must be positive")
        if not page.trace_paths:
            raise ValueError(
                f"第 {page.page_number} 页尚未生成 CAD 轮廓。"
                "请先执行当前 PDF 全部页处理后再导出。"
            )
        page_width_mm, page_height_mm = page.page_size_mm
        if page_width_mm <= 0 or page_height_mm <= 0:
            raise ValueError(f"Page {page.page_number} has invalid paper dimensions")
        if page.drawing_scale <= 0:
            raise ValueError(f"Page {page.page_number} drawing scale must be positive")

        raster = None
        vector_size = page.vector_size_px
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
        page_entities: list[object] = []

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
            page_entities.append(
                modelspace.add_image(
                    image_def=image_def,
                    insert=(0.0, model_y),
                    size_in_units=(width_units, height_units),
                    rotation=0.0,
                    dxfattribs={"layer": "SCAN_UNDERLAY"},
                )
            )

        scale_x = width_units / max(float(vector_width), 1.0)
        scale_y = height_units / max(float(vector_height), 1.0)
        page_base = (index - 1) / expected_pages
        page_span = 0.88 / expected_pages

        def page_progress(stage: str, fraction: float) -> None:
            report_progress(
                progress_callback,
                f"第 {index} 页：{stage}",
                page_base + page_span * fraction,
            )

        (
            current_path_count,
            current_vertex_count,
            trace_entities,
            _trace_bounds,
        ) = add_exact_trace_entities(
            modelspace,
            page.trace_paths,
            transform=lambda x, y, sy=model_y: (
                x * scale_x,
                sy + (vector_height - y) * scale_y,
            ),
            color=page.trace_color,
            source_size=(vector_width, vector_height),
            palette=palette,
            cancellation_token=cancellation_token,
            progress_callback=page_progress,
        )
        page_entities.extend(trace_entities)
        trace_path_count += current_path_count
        trace_vertex_count += current_vertex_count

        group_name = _safe_group_name(index)
        try:
            group = doc.groups.new(group_name)
            group.extend(page_entities)
            group_names.append(group_name)
        except Exception:
            pass

        layout_name = _safe_layout_name(index)
        layout = doc.layouts.new(layout_name)
        layout.page_setup(
            size=(page_width_mm, page_height_mm),
            margins=(0.0, 0.0, 0.0, 0.0),
            units="mm",
            rotation=0,
        )
        layout.add_viewport(
            center=(page_width_mm / 2.0, page_height_mm / 2.0),
            size=(page_width_mm, page_height_mm),
            view_center_point=(width_units / 2.0, model_y + height_units / 2.0),
            view_height=height_units,
            dxfattribs={"status": 2},
        )
        layout_names.append(layout_name)

        model_y += height_units + max(0.0, float(modelspace_gap_mm))
        del raster

    doc.set_raster_variables(frame=0, quality=1, units="mm")
    try:
        zoom.extents(modelspace, factor=1.03)
    except Exception:
        pass

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
        line_count=0,
        circle_count=0,
        text_count=0,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        underlay_paths=tuple(underlays),
        layout_names=tuple(layout_names),
        group_names=tuple(group_names),
    )
