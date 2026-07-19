from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
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
    binary = np.full((100, 220), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 10), (210, 90), 0, 3)
    cv2.circle(binary, (45, 50), 18, 0, 3)
    cv2.putText(
        binary,
        "FIRE ALARM",
        (70, 62),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        0,
        2,
        cv2.LINE_8,
    )
    return binary


def _ocr_text() -> TextCandidate:
    return TextCandidate(
        "FIRE ALARM A1",
        (66, 34, 142, 36),
        0.96,
        "text_candidate",
        quad=((66.0, 34.0), (208.0, 34.0), (208.0, 70.0), (66.0, 70.0)),
        source="test-line",
    )


def _xdata_text(insert) -> str:
    return "".join(value for code, value in insert.get_xdata("OCR_LINE_TEXT") if code == 1000)


def test_single_export_writes_one_vector_block_per_ocr_line(
    tmp_path: Path,
) -> None:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    calibration = ScaleCalibration((0.0, 0.0), (219.0, 0.0), 220.0)

    result = export_exact_trace_dxf(
        paths,
        tmp_path / "trace.dxf",
        binary.shape[0],
        calibration,
        image_width=binary.shape[1],
        drawing_multiplier=1.0,
        texts=(_ocr_text(),),
    )

    assert result.trace_path_count < len(paths)
    assert result.trace_vertex_count < sum(len(path.points) for path in paths)
    assert result.text_count == 1
    assert result.mm_per_pixel == calibration.mm_per_pixel
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    outlines = list(modelspace.query("LWPOLYLINE"))
    inserts = list(modelspace.query("INSERT"))
    assert outlines
    assert len(inserts) == 1
    assert inserts[0].dxf.layer == "OCR_TEXT"
    assert inserts[0].dxf.xscale > 0
    assert inserts[0].dxf.yscale > 0
    assert _xdata_text(inserts[0]) == "FIRE ALARM A1"
    text_block = document.blocks.get(inserts[0].dxf.name)
    assert len(text_block.query("LWPOLYLINE")) > 0
    assert len(modelspace.query("TEXT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert all(len(entity) <= MAX_EDITABLE_POLYLINE_VERTICES for entity in outlines)
    assert {entity.dxf.layer for entity in outlines} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
    }
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


def _document_page(number: int, *, with_text: bool = False) -> DocumentPage:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    raster = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    return DocumentPage(
        page_number=number,
        raster=raster,
        page_size_mm=(220.0, 100.0),
        vector_size_px=(220, 100),
        label=f"trace page {number}",
        trace_paths=paths,
        drawing_scale=1.0,
        trace_color=7,
        texts=(_ocr_text(),) if with_text else (),
    )


def test_document_export_uses_page_layer_and_one_ocr_line_block(
    tmp_path: Path,
) -> None:
    page = _document_page(1, with_text=True)
    result = export_trace_document_streaming(
        [page],
        tmp_path / "document.dxf",
        total_pages=1,
    )

    assert result.trace_path_count < len(page.trace_paths)
    assert result.trace_vertex_count < sum(len(path.points) for path in page.trace_paths)
    assert result.text_count == 1
    assert result.underlay_paths == ()
    assert result.layout_names == ()
    assert result.group_names == ()
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    outlines = list(modelspace.query("LWPOLYLINE"))
    inserts = list(modelspace.query("INSERT"))

    assert outlines
    assert len(inserts) == 1
    assert all(entity.dxf.layer.startswith("PAGE_001_") for entity in outlines)
    assert inserts[0].dxf.layer == "PAGE_001_OCR_TEXT"
    assert _xdata_text(inserts[0]) == "FIRE ALARM A1"
    assert len(modelspace.query("TEXT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert "PAGE_BLOCK_001" not in document.blocks
    assert "PAGE-001" not in document.layouts
    assert not document.audit().errors


def test_later_pages_are_spatially_separated_and_default_off(tmp_path: Path) -> None:
    pages = [_document_page(1), _document_page(2)]
    result = export_trace_document_streaming(
        pages,
        tmp_path / "two-pages.dxf",
        total_pages=2,
    )

    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    page1 = [
        entity
        for entity in modelspace.query("LWPOLYLINE")
        if entity.dxf.layer.startswith("PAGE_001_")
    ]
    page2 = [
        entity
        for entity in modelspace.query("LWPOLYLINE")
        if entity.dxf.layer.startswith("PAGE_002_")
    ]

    assert result.layout_names == ()
    assert page1 and page2
    page1_min_y = min(float(vertex[1]) for entity in page1 for vertex in entity)
    page2_max_y = max(float(vertex[1]) for entity in page2 for vertex in entity)
    assert page2_max_y < page1_min_y
    assert not document.layers.get("PAGE_001_TRACE_CURVE").is_off()
    assert document.layers.get("PAGE_002_TRACE_CURVE").is_off()
    assert document.layers.get("PAGE_002_TRACE_STRAIGHT").is_off()
    assert len(modelspace.query("INSERT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert all("PAGE_BLOCK_" not in block.name for block in document.blocks)
    assert not document.audit().errors
