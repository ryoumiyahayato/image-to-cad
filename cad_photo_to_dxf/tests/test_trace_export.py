from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.document_export import DocumentPage
from app.raster_trace import trace_binary
from app.scale_calibrator import ScaleCalibration
from app.trace_document_export import export_trace_document_streaming
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


def test_single_export_writes_outline_only_geometry(tmp_path: Path) -> None:
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
    assert len(outlines) == len(paths)
    assert len(modelspace.query("HATCH")) == 0
    assert {entity.dxf.layer for entity in outlines} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
    }
    assert {entity.dxf.color for entity in outlines} <= {3, 5, 6}
    assert not document.audit().errors


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


def test_document_export_uses_page_blocks_without_viewports_or_hatches(
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
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    layout = document.layouts.get("PAGE-001")
    block = document.blocks.get("PAGE_BLOCK_001")

    assert len(modelspace.query("INSERT")) == 1
    assert len(modelspace.query("LWPOLYLINE")) == 0
    assert len(layout.query("INSERT")) == 1
    assert len(layout.query("VIEWPORT")) == 0
    assert len(block.query("LWPOLYLINE")) == len(page.trace_paths)
    assert len(block.query("HATCH")) == 0
    assert result.group_names == ("PAGE_001",)
    assert not document.audit().errors


def test_only_first_page_layer_is_visible_by_default(tmp_path: Path) -> None:
    pages = [_document_page(1), _document_page(2)]
    result = export_trace_document_streaming(
        pages,
        tmp_path / "two-pages.dxf",
        total_pages=2,
    )

    document = ezdxf.readfile(result.path)
    inserts = list(document.modelspace().query("INSERT"))
    assert len(inserts) == 2
    assert {insert.dxf.layer for insert in inserts} == {"PAGE_001", "PAGE_002"}
    assert document.layers.get("PAGE_001").is_off() is False
    assert document.layers.get("PAGE_002").is_off() is True
    assert len(document.layouts.get("PAGE-001").query("INSERT")) == 1
    assert len(document.layouts.get("PAGE-002").query("INSERT")) == 1
    assert not document.audit().errors
