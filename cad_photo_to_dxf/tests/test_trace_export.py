from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.document_export import DocumentPage
from app.raster_trace import TracePath, trace_binary
from app.scale_calibrator import ScaleCalibration
from app.trace_document_export import export_trace_document_streaming
from app.trace_dxf_entities import (
    MAX_EDITABLE_POLYLINE_VERTICES,
    add_exact_trace_entities,
)
from app.trace_single_export import export_exact_trace_dxf


def _binary_symbol() -> np.ndarray:
    binary = np.full((100, 140), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 10), (130, 90), 0, 3)
    cv2.circle(binary, (45, 50), 18, 0, 3)
    cv2.putText(
        binary,
        "A1",
        (70, 62),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        0,
        2,
        cv2.LINE_8,
    )
    return binary


def test_single_export_writes_independent_outline_only_geometry(tmp_path: Path) -> None:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    calibration = ScaleCalibration((0.0, 0.0), (139.0, 0.0), 140.0)

    result = export_exact_trace_dxf(
        paths,
        tmp_path / "trace.dxf",
        binary.shape[0],
        calibration,
        image_width=binary.shape[1],
        drawing_multiplier=1.0,
    )

    assert result.trace_path_count == len(paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in paths)
    assert result.mm_per_pixel == calibration.mm_per_pixel
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    outlines = list(modelspace.query("LWPOLYLINE"))
    assert len(outlines) >= len(paths)
    assert len(modelspace.query("INSERT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert all(len(entity) <= MAX_EDITABLE_POLYLINE_VERTICES for entity in outlines)
    assert {entity.dxf.layer for entity in outlines} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
    }
    assert {entity.dxf.color for entity in outlines} <= {3, 5, 6}
    assert not document.audit().errors


def test_long_connected_contour_is_split_without_losing_segments() -> None:
    points = tuple((float(index), float(index % 2)) for index in range(150))
    path = TracePath(points=points, parent=None, depth=0, root=0)
    document = ezdxf.new("R2010", setup=True)
    modelspace = document.modelspace()

    _path_count, _vertex_count, entities, _bounds = add_exact_trace_entities(
        modelspace,
        [path],
        transform=lambda x, y: (x, y),
        source_size=(150, 2),
    )

    polylines = list(modelspace.query("LWPOLYLINE"))
    assert entities == polylines
    assert len(polylines) > 1
    assert all(len(entity) <= MAX_EDITABLE_POLYLINE_VERTICES for entity in polylines)
    assert all(not entity.closed for entity in polylines)
    exported_segment_count = sum(max(0, len(entity) - 1) for entity in polylines)
    assert exported_segment_count == len(points)


def _document_page(number: int) -> DocumentPage:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    raster = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    return DocumentPage(
        page_number=number,
        raster=raster,
        page_size_mm=(140.0, 100.0),
        vector_size_px=(140, 100),
        label=f"trace page {number}",
        trace_paths=paths,
        drawing_scale=1.0,
        trace_color=7,
    )


def test_document_export_contains_direct_entities_not_blocks_or_groups(
    tmp_path: Path,
) -> None:
    page = _document_page(1)
    result = export_trace_document_streaming(
        [page],
        tmp_path / "document.dxf",
        total_pages=1,
    )

    assert result.trace_path_count == len(page.trace_paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in page.trace_paths)
    assert result.underlay_paths == ()
    assert result.group_names == ()
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    layout = document.layouts.get("PAGE-001")

    model_entities = list(modelspace.query("LWPOLYLINE"))
    layout_entities = list(layout.query("LWPOLYLINE"))
    assert model_entities
    assert len(model_entities) == len(layout_entities)
    assert len(modelspace.query("INSERT")) == 0
    assert len(layout.query("INSERT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert len(layout.query("HATCH")) == 0
    assert "PAGE_BLOCK_001" not in document.blocks
    assert not document.audit().errors


def test_only_first_page_is_duplicated_into_modelspace(tmp_path: Path) -> None:
    pages = [_document_page(1), _document_page(2)]
    result = export_trace_document_streaming(
        pages,
        tmp_path / "two-pages.dxf",
        total_pages=2,
    )

    document = ezdxf.readfile(result.path)
    model_entities = list(document.modelspace().query("LWPOLYLINE"))
    first_layout_entities = list(document.layouts.get("PAGE-001").query("LWPOLYLINE"))
    second_layout_entities = list(document.layouts.get("PAGE-002").query("LWPOLYLINE"))

    assert result.layout_names == ("PAGE-001", "PAGE-002")
    assert model_entities
    assert len(model_entities) == len(first_layout_entities)
    assert len(second_layout_entities) == len(first_layout_entities)
    assert len(document.modelspace().query("INSERT")) == 0
    assert all("PAGE_BLOCK_" not in block.name for block in document.blocks)
    assert not document.audit().errors
