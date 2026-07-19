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


def test_single_export_writes_one_exact_region_representation(tmp_path: Path) -> None:
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
    assert len(modelspace.query("LWPOLYLINE")) == 0
    hatches = list(modelspace.query("HATCH"))
    assert len(hatches) == sum(path.depth % 2 == 0 for path in paths)
    assert {hatch.dxf.layer for hatch in hatches} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
    }
    assert {hatch.dxf.color for hatch in hatches} <= {3, 5, 6}
    assert not document.audit().errors


def test_document_export_writes_geometry_once_and_uses_layout_viewport(tmp_path: Path) -> None:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    raster = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    page = DocumentPage(
        page_number=1,
        raster=raster,
        page_size_mm=(140.0, 100.0),
        vector_size_px=(140, 100),
        label="trace page",
        trace_paths=paths,
        drawing_scale=1.0,
        trace_color=7,
    )

    result = export_trace_document_streaming(
        [page],
        tmp_path / "document.dxf",
        total_pages=1,
    )

    assert result.trace_path_count == len(paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in paths)
    assert result.underlay_paths == ()
    document = ezdxf.readfile(result.path)
    layout = document.layouts.get("PAGE-001")
    assert len(layout.query("HATCH")) == 0
    assert len(layout.query("VIEWPORT")) >= 1
    assert len(document.modelspace().query("HATCH")) == sum(
        path.depth % 2 == 0 for path in paths
    )
    assert len(document.modelspace().query("IMAGE")) == 0
    assert result.group_names == ("PAGE_001",)
    assert not document.audit().errors
