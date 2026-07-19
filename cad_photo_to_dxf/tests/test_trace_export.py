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


def _page_with_small_text() -> np.ndarray:
    binary = np.full((1000, 1400), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "TEXT A1 9000",
        (80, 110),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        0,
        2,
        cv2.LINE_8,
    )
    return binary


def test_single_export_writes_compatible_exact_geometry(tmp_path: Path) -> None:
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
    hatches = list(modelspace.query("HATCH"))
    assert len(outlines) == len(paths)
    # On this deliberately tiny page the symbols are too large to qualify as
    # safe text fills.  Exact boundaries remain, without a risky broad HATCH.
    assert hatches == []
    assert {entity.dxf.layer for entity in outlines} <= {
        "TRACE_STRAIGHT",
        "TRACE_CURVE",
        "TRACE_TEXT_SYMBOL",
    }
    assert {entity.dxf.color for entity in outlines} <= {3, 5, 6}
    assert not document.audit().errors


def test_small_text_fill_uses_valid_polyline_boundary_flags(tmp_path: Path) -> None:
    binary = _page_with_small_text()
    paths = trace_binary(binary)
    calibration = ScaleCalibration((0.0, 0.0), (1399.0, 0.0), 1400.0)

    result = export_exact_trace_dxf(
        paths,
        tmp_path / "text-fill.dxf",
        binary.shape[0],
        calibration,
        image_width=binary.shape[1],
    )

    document = ezdxf.readfile(result.path)
    hatches = list(document.modelspace().query("HATCH"))
    assert hatches
    for hatch in hatches:
        boundary_paths = hatch.paths.paths
        assert boundary_paths
        # Every polyline boundary must contain bit 2.  The outer loop also has
        # bit 1; holes retain bit 2 without pretending to be external loops.
        assert boundary_paths[0].path_type_flags & 2
        assert boundary_paths[0].path_type_flags & 1
        for hole in boundary_paths[1:]:
            assert hole.path_type_flags & 2
            assert not hole.path_type_flags & 1
        assert hatch.dxf.hatch_style == 0
    assert not document.audit().errors


def test_page_spanning_regions_are_never_hatched(tmp_path: Path) -> None:
    binary = np.full((800, 1200), 255, dtype=np.uint8)
    polygon = np.array(((20, 20), (1180, 20), (850, 760), (20, 430)), dtype=np.int32)
    cv2.fillPoly(binary, [polygon], 0)
    cv2.rectangle(binary, (120, 120), (1080, 680), 255, 12)
    paths = trace_binary(binary)
    calibration = ScaleCalibration((0.0, 0.0), (1199.0, 0.0), 1200.0)

    result = export_exact_trace_dxf(
        paths,
        tmp_path / "large-region.dxf",
        binary.shape[0],
        calibration,
        image_width=binary.shape[1],
    )

    document = ezdxf.readfile(result.path)
    assert len(document.modelspace().query("LWPOLYLINE")) == len(paths)
    assert len(document.modelspace().query("HATCH")) == 0
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
    assert len(layout.query("LWPOLYLINE")) == 0
    assert len(layout.query("VIEWPORT")) >= 1
    assert len(document.modelspace().query("LWPOLYLINE")) == len(paths)
    assert len(document.modelspace().query("HATCH")) == 0
    assert len(document.modelspace().query("IMAGE")) == 0
    assert result.group_names == ("PAGE_001",)
    assert not document.audit().errors
