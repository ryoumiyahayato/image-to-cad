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


def _ocr_text() -> TextCandidate:
    return TextCandidate(
        "A1",
        (66, 36, 48, 32),
        0.96,
        "text_candidate",
        quad=((66.0, 36.0), (114.0, 36.0), (114.0, 68.0), (66.0, 68.0)),
        source="test",
    )


def test_single_export_writes_editable_text_and_independent_outlines(
    tmp_path: Path,
) -> None:
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
        texts=(_ocr_text(),),
    )

    assert result.trace_path_count == len(paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in paths)
    assert result.text_count == 1
    assert result.mm_per_pixel == calibration.mm_per_pixel
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    outlines = list(modelspace.query("LWPOLYLINE"))
    texts = list(modelspace.query("TEXT"))
    assert outlines
    assert len(texts) == 1
    assert texts[0].dxf.text == "A1"
    assert texts[0].dxf.layer == "OCR_TEXT"
    assert len(modelspace.query("INSERT")) == 0
    assert len(modelspace.query("HATCH")) == 0
    assert all(len(entity) <= MAX_EDITABLE_POLYLINE_VERTICES for entity in outlines)
    assert document.layers.get("TRACE_TEXT_OUTLINE").is_off()
    assert {entity.dxf.layer for entity in outlines} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
        "TRACE_TEXT_OUTLINE",
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
        page_size_mm=(140.0, 100.0),
        vector_size_px=(140, 100),
        label=f"trace page {number}",
        trace_paths=paths,
        drawing_scale=1.0,
        trace_color=7,
        texts=(_ocr_text(),) if with_text else (),
    )


def test_document_export_uses_modelspace_page_layers_without_layout_overlap(
    tmp_path: Path,
) -> None:
    page = _document_page(1, with_text=True)
    result = export_trace_document_streaming(
        [page],
        tmp_path / "document.dxf",
        total_pages=1,
    )

    assert result.trace_path_count == len(page.trace_paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in page.trace_paths)
    assert result.text_count == 1
    assert result.underlay_paths == ()
    assert result.layout_names == ()
    assert result.group_names == ()
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    outlines = list(modelspace.query("LWPOLYLINE"))
    texts = list(modelspace.query("TEXT"))

    assert outlines
    assert len(texts) == 1
    assert all(entity.dxf.layer.startswith("PAGE_001_") for entity in outlines)
    assert texts[0].dxf.layer == "PAGE_001_OCR_TEXT"
    assert document.layers.get("PAGE_001_TRACE_TEXT_OUTLINE").is_off()
    assert len(modelspace.query("INSERT")) == 0
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
