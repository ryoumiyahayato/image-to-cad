from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.dxf_exporter import ExportResult
from app.geometry_cleaner import GeometryCleanParams, GeometryCleanReport
from app.layer_classifier import ClassificationReport
from app.line_detect import LineDetectionParams, LineSegment
from app.pipeline_service import PipelineService
from app.report_builder import ReportBuilder
from app.topology import IntersectionSplitReport, TopologyValidationReport


def test_shared_pipeline_service_vectorizes_existing_binary() -> None:
    binary = np.full((500, 700), 255, np.uint8)
    cv2.rectangle(binary, (80, 80), (620, 420), 0, 4)
    cv2.line(binary, (100, 250), (600, 250), 0, 5)
    result = PipelineService.vectorize(
        cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR),
        existing_binary=binary,
        detection_params=LineDetectionParams(min_line_length=40, use_lsd=False),
        clean_params=GeometryCleanParams(min_line_length=10),
    )
    assert result.raw_lines
    assert result.lines
    assert result.binary.shape == binary.shape
    assert result.preview.shape[:2] == binary.shape
    assert result.classification_report.input_lines >= len(result.lines)
    assert result.intersection_split_report.output_lines >= len(result.lines)
    assert result.topology_report.line_count == result.intersection_split_report.output_lines


def test_shared_pipeline_rejects_stale_binary_dimensions() -> None:
    corrected = np.full((500, 700, 3), 255, np.uint8)
    stale_binary = np.full((480, 700), 255, np.uint8)
    with pytest.raises(ValueError, match="dimensions do not match"):
        PipelineService.vectorize(corrected, existing_binary=stale_binary)


def test_report_builder_emits_same_complete_schema_for_any_frontend() -> None:
    raw = [
        LineSegment(0, 0, 100, 0, source_ids=("HOUGH-000001",), history=("input",))
    ]
    final = [raw[0].copy(layer="DETAIL")]
    export = ExportResult(
        path=Path("output.dxf"),
        line_count=1,
        mm_per_pixel=1.0,
        calibrated=False,
    )
    report = ReportBuilder.build(
        input_path="input.png",
        original_shape=(500, 700, 3),
        corrected_shape=(480, 680, 3),
        perspective={
            "applied": True,
            "automatic": True,
            "confidence": 0.9,
            "corners": [[1, 2], [3, 4], [5, 6], [7, 8]],
        },
        quality={"warnings": []},
        parameters={"strict_perspective": True},
        preprocess_stages={"01_grayscale": np.zeros((480, 680), np.uint8)},
        preprocess_resolution_scale=1.0,
        detection_resolution_scale=1.0,
        thick_stroke_centering=True,
        raw_lines=raw,
        lines=final,
        geometry_report=GeometryCleanReport(input_lines=1, output_lines=1),
        geometry_resolution_scale=1.0,
        intersection_split_report=IntersectionSplitReport(
            input_lines=1,
            output_lines=1,
        ),
        topology_report=TopologyValidationReport(
            line_count=1,
            endpoint_nodes=2,
            dangling_endpoints=2,
            connected_components=1,
            open_components=1,
        ),
        classification_report=ClassificationReport(
            input_lines=1,
            layer_counts={"DETAIL": 1},
        ),
        auxiliary=None,
        export_result=export,
        calibration_source="uncalibrated",
        coordinate_space="pixel",
        warnings=["review required"],
        duration_seconds=0.25,
    )
    assert report["perspective"]["corners"]
    assert report["perspective"]["confidence"] == 0.9
    assert report["duration_seconds"] == 0.25
    assert report["parameters"]["strict_perspective"] is True
    assert report["geometry"]["resolution_scale"] == 1.0
    assert report["topology"]["intersection_splitting"]["output_lines"] == 1
    assert report["topology"]["validation"]["dangling_endpoints"] == 2
    assert report["lineage"]["final_entity_count"] == 1
    assert report["export"]["coordinate_space"] == "pixel"
    assert report["warnings"] == ["review required"]
