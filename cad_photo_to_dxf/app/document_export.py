from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
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
from .dxf_exporter import LAYER_STYLES, MIN_TEXT_EXPORT_CONFIDENCE
from .image_loader import load_image, save_image
from .line_detect import LineSegment
from .raster_trace import TracePath


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


def _safe_layout_name(sequence_number: int) -> str:
    return f"PAGE-{sequence_number:03d}"


def _safe_group_name(sequence_number: int) -> str:
    return f"PAGE_{sequence_number:03d}"


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


def _valid_circle(circle: CircleCandidate) -> bool:
    values = (*circle.center, circle.radius, circle.confidence)
    return (
        all(isfinite(float(value)) for value in values)
        and circle.radius > 1e-9
        and circle.confidence >= MIN_CIRCLE_EXPORT_CONFIDENCE
    )


def _valid_text(text: TextCandidate) -> bool:
    x, y, width, height = text.bbox
    values = (x, y, width, height, text.confidence)
    return (
        bool(text.text.strip())
        and all(isfinite(float(value)) for value in values)
        and width > 0
        and height > 0
        and text.confidence >= MIN_TEXT_EXPORT_CONFIDENCE
    )


def _transform_trace_points(
    path: TracePath,
    *,
    vector_height: int,
    scale_x: float,
    scale_y: float,
    origin_x: float,
    origin_y: float,
) -> list[tuple[float, float]]:
    return [
        (
            origin_x + float(x) * scale_x,
            origin_y + (vector_height - float(y)) * scale_y,
        )
        for x, y in path.points
    ]


def _add_trace_entities(
    layout,
    page: DocumentPage,
    *,
    vector_height: int,
    scale_x: float,
    scale_y: float,
    origin_x: float,
    origin_y: float,
) -> tuple[int, int, list[object]]:
    """Add editable contour boundaries and solid hatches for literal black ink."""

    if not page.trace_paths:
        return 0, 0, []
    color = int(page.trace_color)
    if not 1 <= color <= 255:
        color = 7
    transformed: list[list[tuple[float, float]]] = []
    entities: list[object] = []
    for trace_path in page.trace_paths:
        points = _transform_trace_points(
            trace_path,
            vector_height=vector_height,
            scale_x=scale_x,
            scale_y=scale_y,
            origin_x=origin_x,
            origin_y=origin_y,
        )
        transformed.append(points)
        if len(points) < 3:
            continue
        entities.append(
            layout.add_lwpolyline(
                points,
                close=True,
                dxfattribs={"layer": "TRACE_OUTLINE", "color": color},
            )
        )

    by_root: dict[int, list[int]] = defaultdict(list)
    for index, trace_path in enumerate(page.trace_paths):
        by_root[int(trace_path.root)].append(index)
    for indices in by_root.values():
        usable = [index for index in indices if len(transformed[index]) >= 3]
        if not usable:
            continue
        hatch = layout.add_hatch(
            color=color,
            dxfattribs={"layer": "TRACE_FILL", "color": color},
        )
        hatch.set_solid_fill(color=color)
        for index in usable:
            trace_path = page.trace_paths[index]
            hatch.paths.add_polyline_path(
                transformed[index],
                is_closed=True,
                flags=1 if trace_path.depth == 0 else 0,
            )
        entities.append(hatch)

    return len(page.trace_paths), sum(len(path.points) for path in page.trace_paths), entities


def _add_page_entities(
    layout,
    image_def,
    page: DocumentPage,
    raster_shape: tuple[int, ...],
    *,
    origin: tuple[float, float],
    drawing_multiplier: float,
) -> tuple[int, int, int, int, int, list[object]]:
    raster_height, raster_width = raster_shape[:2]
    page_width_mm, page_height_mm = page.page_size_mm
    origin_x, origin_y = origin
    multiplier = float(drawing_multiplier)
    if not isfinite(multiplier) or multiplier <= 0:
        raise ValueError(f"Page {page.page_number} drawing scale must be positive")
    width_units = page_width_mm * multiplier
    height_units = page_height_mm * multiplier
    entities: list[object] = []
    entities.append(
        layout.add_image(
            image_def=image_def,
            insert=(origin_x, origin_y),
            size_in_units=(width_units, height_units),
            rotation=0.0,
            dxfattribs={"layer": "SCAN_UNDERLAY"},
        )
    )
    vector_width, vector_height = page.vector_size_px or (raster_width, raster_height)
    scale_x = width_units / max(float(vector_width), 1.0)
    scale_y = height_units / max(float(vector_height), 1.0)

    line_count = 0
    circle_count = 0
    text_count = 0
    for line in page.lines:
        values = np.array((line.x1, line.y1, line.x2, line.y2), dtype=float)
        if not np.isfinite(values).all() or line.length <= 1e-9:
            continue
        start = (
            origin_x + line.x1 * scale_x,
            origin_y + (vector_height - 1 - line.y1) * scale_y,
        )
        end = (
            origin_x + line.x2 * scale_x,
            origin_y + (vector_height - 1 - line.y2) * scale_y,
        )
        layer = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        entities.append(layout.add_line(start, end, dxfattribs={"layer": layer}))
        line_count += 1

    radius_scale = (scale_x + scale_y) * 0.5
    for circle in page.circles:
        if not _valid_circle(circle):
            continue
        center = (
            origin_x + circle.center[0] * scale_x,
            origin_y + (vector_height - 1 - circle.center[1]) * scale_y,
        )
        entities.append(
            layout.add_circle(
                center,
                circle.radius * radius_scale,
                dxfattribs={"layer": "CIRCLE_CONFIRMED"},
            )
        )
        circle_count += 1

    for text in page.texts:
        if not _valid_text(text):
            continue
        x, y, _width, height = text.bbox
        insert = (
            origin_x + x * scale_x,
            origin_y + (vector_height - 1 - (y + height)) * scale_y,
        )
        entity = layout.add_text(
            text.text.strip(),
            height=max(scale_y, height * scale_y * 0.85),
            dxfattribs={"layer": "OCR_TEXT"},
        )
        entity.set_placement(insert)
        entities.append(entity)
        text_count += 1

    trace_path_count, trace_vertex_count, trace_entities = _add_trace_entities(
        layout,
        page,
        vector_height=vector_height,
        scale_x=scale_x,
        scale_y=scale_y,
        origin_x=origin_x,
        origin_y=origin_y,
    )
    entities.extend(trace_entities)
    return (
        line_count,
        circle_count,
        text_count,
        trace_path_count,
        trace_vertex_count,
        entities,
    )


def export_scan_document(
    pages: Iterable[DocumentPage],
    output_path: str | Path,
    *,
    modelspace_gap_mm: float = 25.0,
) -> DocumentExportResult:
    """Export queued scans into one DXF with paper layouts and full-size model data."""

    document_pages = list(pages)
    if not document_pages:
        raise ValueError("At least one document page is required")

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
    model_y = 0.0

    for index, page in enumerate(document_pages, start=1):
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
        page_count=len(document_pages),
        line_count=line_count,
        circle_count=circle_count,
        text_count=text_count,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        underlay_paths=tuple(underlays),
        layout_names=tuple(layout_names),
        group_names=tuple(group_names),
    )
