from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom

from .document_export import (
    DocumentExportResult,
    DocumentPage,
    _add_page_entities,
    _resolve_raster,
    _safe_group_name,
    _safe_layout_name,
)
from .dxf_exporter import LAYER_STYLES
from .image_loader import save_image


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
) -> DocumentExportResult:
    """Export pages sequentially so cached 300 DPI traces stay bounded in RAM."""

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
    styles = {
        **LAYER_STYLES,
        "TRACE_OUTLINE": {"color": 7, "lineweight": 0},
        "TRACE_FILL": {"color": 7, "lineweight": 0},
    }
    for layer_name, style in styles.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    underlays: list[Path] = []
    layout_names: list[str] = []
    group_names: list[str] = []
    line_count = 0
    circle_count = 0
    text_count = 0
    trace_path_count = 0
    trace_vertex_count = 0
    page_count = 0
    model_y = 0.0

    for index, page in enumerate(page_stream(), start=1):
        page_count = index
        if page.page_number <= 0:
            raise ValueError("Page numbers must be positive")
        page_width_mm, page_height_mm = page.page_size_mm
        if page_width_mm <= 0 or page_height_mm <= 0:
            raise ValueError(f"Page {page.page_number} has invalid paper dimensions")
        raster = _resolve_raster(page)
        scan_path = path.with_name(f"{path.stem}.page-{index:03d}.scan.png")
        save_image(scan_path, raster)
        underlays.append(scan_path)
        raster_height, raster_width = raster.shape[:2]
        image_def = doc.add_image_def(
            filename=scan_path.name,
            size_in_pixel=(int(raster_width), int(raster_height)),
            name=f"SCAN_PAGE_{index:03d}",
        )

        layout_name = _safe_layout_name(index)
        layout = doc.layouts.new(layout_name)
        layout.page_setup(
            size=(page_width_mm, page_height_mm),
            margins=(0.0, 0.0, 0.0, 0.0),
            units="mm",
            rotation=0,
        )
        (
            layout_lines,
            layout_circles,
            layout_texts,
            layout_trace_paths,
            layout_trace_vertices,
            _layout_entities,
        ) = _add_page_entities(
            layout,
            image_def,
            page,
            raster.shape,
            origin=(0.0, 0.0),
            drawing_multiplier=1.0,
        )
        line_count += layout_lines
        circle_count += layout_circles
        text_count += layout_texts
        trace_path_count += layout_trace_paths
        trace_vertex_count += layout_trace_vertices
        layout_names.append(layout_name)

        (
            _model_lines,
            _model_circles,
            _model_texts,
            _model_trace_paths,
            _model_trace_vertices,
            model_entities,
        ) = _add_page_entities(
            modelspace,
            image_def,
            page,
            raster.shape,
            origin=(0.0, model_y),
            drawing_multiplier=page.drawing_scale,
        )
        group_name = _safe_group_name(index)
        try:
            group = doc.groups.new(group_name)
            group.extend(model_entities)
            group_names.append(group_name)
        except Exception:
            pass
        model_y += page_height_mm * page.drawing_scale + max(
            0.0,
            float(modelspace_gap_mm) * page.drawing_scale,
        )
        del raster

    doc.set_raster_variables(frame=0, quality=1, units="mm")
    try:
        zoom.extents(modelspace, factor=1.03)
    except Exception:
        pass

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

    return DocumentExportResult(
        path=path,
        page_count=page_count,
        line_count=line_count,
        circle_count=circle_count,
        text_count=text_count,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        underlay_paths=tuple(underlays),
        layout_names=tuple(layout_names),
        group_names=tuple(group_names),
    )
