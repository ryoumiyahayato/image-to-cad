from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.document_export import DocumentPage, export_scan_document
from app.dxf_exporter import export_dxf
from app.raster_trace import trace_binary
from app.scale_calibrator import ScaleCalibration


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


def test_single_export_writes_every_trace_boundary_and_model_scale(tmp_path: Path) -> None:
    binary = _binary_symbol()
    paths = trace_binary(binary)
    calibration = ScaleCalibration((0.0, 0.0), (139.0, 0.0), 140.0)

    result = export_dxf(
        [],
        tmp_path / "trace.dxf",
        binary.shape[0],
        calibration,
        trace_paths=paths,
        drawing_scale=100.0,
        trace_color=1,
    )

    assert result.trace_path_count == len(paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in paths)
    assert result.mm_per_pixel == calibration.mm_per_pixel * 100.0
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    assert len(modelspace.query("LWPOLYLINE[layer=='TRACE_OUTLINE']")) == len(paths)
    assert len(modelspace.query("HATCH[layer=='TRACE_FILL']")) >= 1
    assert all(entity.dxf.color == 1 for entity in modelspace.query("LWPOLYLINE"))


def test_document_export_keeps_paper_layout_and_scaled_modelspace(tmp_path: Path) -> None:
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
        drawing_scale=50.0,
        trace_color=5,
    )

    result = export_scan_document([page], tmp_path / "document.dxf")

    assert result.trace_path_count == len(paths)
    assert result.trace_vertex_count == sum(len(path.points) for path in paths)
    document = ezdxf.readfile(result.path)
    layout = document.layouts.get("PAGE-001")
    assert len(layout.query("LWPOLYLINE[layer=='TRACE_OUTLINE']")) == len(paths)
    assert len(document.modelspace().query("LWPOLYLINE[layer=='TRACE_OUTLINE']")) == len(paths)
    model_image = document.modelspace().query("IMAGE").first
    layout_image = layout.query("IMAGE").first
    assert model_image is not None and layout_image is not None
    assert model_image.dxf.u_pixel[0] > layout_image.dxf.u_pixel[0]
    assert result.group_names == ("PAGE_001",)
