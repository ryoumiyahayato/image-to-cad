from __future__ import annotations

import cv2
import numpy as np

from app.line_detect import LineSegment
from app.optimized_trace import trace_image_optimized
from app.raster_trace import trace_binary
from app.scan_artifact_filter import suppress_scan_artifact_traces
from app.source_support_lifecycle import SourceSupportLifecycle


def _horizontal_support(shape: tuple[int, int], y: int, x1: int, x2: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.line(mask, (x1, y), (x2, y), 255, 3, cv2.LINE_8)
    return mask


def test_lifecycle_traces_rerouted_support_to_artifact_terminal_reason() -> None:
    shape = (120, 180)
    support = _horizontal_support(shape, 50, 20, 150)
    binary = np.where(support > 0, 0, 255).astype(np.uint8)
    line = LineSegment(20, 50, 150, 50, width=3, source_ids=("LSD-000001",))
    paths = trace_binary(binary)
    lifecycle = SourceSupportLifecycle(shape)
    lifecycle.register(
        "SS-D2-002",
        support,
        evidence_types=("native_LINE_evidence", "TEXT-adjacent_structural_evidence"),
    )
    lifecycle.observe_detection("RAW", (line,))
    lifecycle.observe_detection("ELIGIBLE", (line,), eligible=True)
    lifecycle.observe_detection("POST_FILTER_CANDIDATE", (line,), eligible=True)
    lifecycle.observe_ownership(
        owner_masks={
            "LINE": np.zeros(shape, dtype=np.uint8),
            "GRAPHIC_FALLBACK": support,
        },
        downgrades=({"downgrade_reason": "weak_or_conflicting_line_candidate"},),
    )
    lifecycle.observe_fallback_start(binary, paths)
    lifecycle.observe_artifact_root(
        root_id="artifact-root-000000",
        root_mask=support,
        decision="REJECTED_DAMAGE_CLUSTER_PROPAGATION",
        reason="damage_root_proximity_propagation",
    )
    lifecycle.observe_fallback_result(np.full(shape, 255, dtype=np.uint8))
    lifecycle.observe_final(
        contours=(),
        straight_lines=(),
        contour_binary=np.full(shape, 255, dtype=np.uint8),
        final_structure_id="final-absent",
    )

    item = lifecycle.payload()["supports"][0]
    assert item["source_support_id"] == "SS-D2-002"
    assert item["ever_had_candidate_id"] is True
    assert item["final_owner"] == "GRAPHIC_FALLBACK"
    assert item["fallback_execution"] == "EXECUTED"
    assert item["terminal_reason"] == "DAMAGE_CLUSTER_PROPAGATION_REJECTED"
    assert item["coverage_gaps"] == []


def test_artifact_suppressor_emits_root_provenance_without_changing_result() -> None:
    shape = (160, 220)
    binary = np.full(shape, 255, dtype=np.uint8)
    cv2.rectangle(binary, (30, 50), (190, 55), 0, -1)
    gray = binary.copy()
    paths = trace_binary(binary)
    support = np.where(binary < 128, 255, 0).astype(np.uint8)
    lifecycle = SourceSupportLifecycle(shape)
    lifecycle.register("SS-LOWER-RESCUED", support)
    lifecycle.observe_fallback_start(binary, paths)

    baseline = suppress_scan_artifact_traces(gray, binary, paths)
    observed = suppress_scan_artifact_traces(
        gray,
        binary,
        paths,
        source_support_lifecycle=lifecycle,
    )
    lifecycle.observe_fallback_result(observed.binary)
    lifecycle.observe_final(
        contours=trace_binary(observed.binary),
        straight_lines=(),
        contour_binary=observed.binary,
        final_structure_id="final-preserved",
    )

    assert np.array_equal(observed.binary, baseline.binary)
    assert observed.removed_root_count == baseline.removed_root_count
    item = lifecycle.payload()["supports"][0]
    assert item["artifact_suppression_decisions"]
    assert item["artifact_suppression_decisions"][0]["decision"] == "ACCEPTED"
    assert item["terminal_reason"] == "PRESERVED"




def test_pipeline_instrumentation_has_zero_final_structure_semantic_delta() -> None:
    image = np.full((180, 260, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 90), (235, 90), (0, 0, 0), 3, cv2.LINE_8)
    baseline = trace_image_optimized(image, enable_ocr=False)
    lifecycle = SourceSupportLifecycle(image.shape[:2])
    lifecycle.register(
        "SS-P1-D2-005",
        _horizontal_support(image.shape[:2], 90, 20, 235),
        evidence_types=("native_LINE_evidence",),
        observation_metadata={"case_id": "D2-005"},
    )
    instrumented = trace_image_optimized(
        image,
        enable_ocr=False,
        source_support_lifecycle=lifecycle,
    )

    assert baseline.final_structure is not None
    assert instrumented.final_structure is not None
    assert instrumented.final_structure.structure_id == baseline.final_structure.structure_id
    assert len(instrumented.paths) == len(baseline.paths)
    assert len(instrumented.straight_lines) == len(baseline.straight_lines)
    item = lifecycle.payload()["supports"][0]
    assert item["terminal_reason"] == "PRESERVED"
    assert lifecycle.census()["supports_with_instrumentation_gap"] == 0


def test_partial_raw_detection_is_explicit_detection_fragmentation() -> None:
    shape = (100, 220)
    support = _horizontal_support(shape, 45, 10, 205)
    partial = LineSegment(10, 45, 100, 45, width=3, source_ids=("LSD-FRAGMENT",))
    lifecycle = SourceSupportLifecycle(shape)
    lifecycle.register("SS-D2-001", support)
    lifecycle.observe_detection("RAW", (partial,))
    lifecycle.observe_detection("ELIGIBLE", (partial,), eligible=True)
    lifecycle.observe_fallback_start(np.full(shape, 255, dtype=np.uint8), (), executed=False)
    lifecycle.observe_final(
        contours=(),
        straight_lines=(),
        contour_binary=np.full(shape, 255, dtype=np.uint8),
        final_structure_id="final-absent",
    )

    item = lifecycle.payload()["supports"][0]
    assert item["terminal_reason"] == "DETECTION_FRAGMENTED"
    assert item["coverage_gaps"] == []
