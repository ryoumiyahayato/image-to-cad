from __future__ import annotations

from copy import deepcopy
import inspect

import cv2
import numpy as np

from cad_photo_to_dxf.app.direct_continuation_admissibility import (
    DirectContinuationReason,
    DirectContinuationStatus,
    assess_direct_continuation,
)
from cad_photo_to_dxf.scripts.run_direct_continuation_admissibility_v1 import (
    _summary,
    evaluate_frozen_24,
)


def _candidate(
    *,
    gap_start: int = 40,
    gap_end: int = 60,
    a_axis: int = 50,
    b_axis: int = 50,
    candidate_id: str | None = None,
    semantic_class: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "orientation": "horizontal",
        "fragment_a_geometry": {
            "start": [10, a_axis],
            "end": [gap_start, a_axis],
        },
        "fragment_b_geometry": {
            "start": [gap_end, b_axis],
            "end": [90, b_axis],
        },
        "gap_endpoint_a": [gap_start, int(round((a_axis + b_axis) / 2))],
        "gap_endpoint_b": [gap_end, int(round((a_axis + b_axis) / 2))],
    }
    if candidate_id is not None:
        item["candidate_id"] = candidate_id
    if semantic_class is not None:
        item["semantic_class"] = semantic_class
    return item


def _image(candidate: dict[str, object]) -> np.ndarray:
    image = np.full((100, 110), 255, dtype=np.uint8)
    first = candidate["fragment_a_geometry"]
    second = candidate["fragment_b_geometry"]
    assert isinstance(first, dict) and isinstance(second, dict)
    cv2.line(image, tuple(first["start"]), tuple(first["end"]), 0, 2)
    cv2.line(image, tuple(second["start"]), tuple(second["end"]), 0, 2)
    return image


def test_admissibility_decision_and_reason_are_deterministic() -> None:
    candidate = _candidate()
    image = _image(candidate)
    first = assess_direct_continuation(image, candidate)
    second = assess_direct_continuation(image.copy(), deepcopy(candidate))
    assert first == second
    assert first.status is DirectContinuationStatus.ADMISSIBLE
    assert first.reason is DirectContinuationReason.CLEAR_DIRECT_TRAJECTORY


def test_node_or_component_in_gap_suppresses_direct_continuation() -> None:
    candidate = _candidate()
    image = _image(candidate)
    cv2.rectangle(image, (45, 42), (55, 58), 0, 2)
    decision = assess_direct_continuation(image, candidate)
    assert decision.status is DirectContinuationStatus.REJECTED
    assert decision.reason is DirectContinuationReason.NODE_OR_COMPONENT_MEDIATED


def test_competing_parallel_edge_is_not_accepted_from_collinearity_alone() -> None:
    candidate = _candidate(a_axis=47, b_axis=53)
    image = _image(candidate)
    cv2.line(image, (39, 43), (61, 43), 0, 2)
    decision = assess_direct_continuation(image, candidate)
    assert decision.status is not DirectContinuationStatus.ADMISSIBLE
    assert decision.reason in {
        DirectContinuationReason.PARALLEL_COMPETING_EDGE,
        DirectContinuationReason.PAIR_OFFSET_INCONSISTENT,
        DirectContinuationReason.NODE_OR_COMPONENT_MEDIATED,
    }


def test_bounded_intentional_opening_evidence_prevents_continuation() -> None:
    candidate = _candidate(gap_start=30, gap_end=75)
    image = _image(candidate)
    cv2.line(image, (30, 39), (30, 61), 0, 2)
    cv2.line(image, (75, 39), (75, 61), 0, 2)
    decision = assess_direct_continuation(image, candidate)
    assert decision.status is DirectContinuationStatus.REJECTED
    assert decision.reason is DirectContinuationReason.INTENTIONAL_OPENING_EVIDENCE


def test_valid_object_and_continuous_annotation_are_not_semantically_filtered() -> None:
    object_candidate = _candidate(
        gap_start=40,
        gap_end=46,
        a_axis=48,
        b_axis=52,
        semantic_class="OBJECT",
    )
    object_image = _image(object_candidate)
    object_decision = assess_direct_continuation(object_image, object_candidate)
    annotation_candidate = _candidate(semantic_class="ANNOTATION")
    annotation_image = _image(annotation_candidate)
    annotation_decision = assess_direct_continuation(annotation_image, annotation_candidate)
    assert object_decision.status is DirectContinuationStatus.ADMISSIBLE
    assert annotation_decision.status is DirectContinuationStatus.ADMISSIBLE
    assert not object_decision.semantic_or_model_evidence_used
    assert not annotation_decision.semantic_or_model_evidence_used


def test_candidate_identity_does_not_change_decision_and_geometry_is_untouched() -> None:
    first = _candidate(candidate_id="alpha")
    second = _candidate(candidate_id="completely-different")
    image = _image(first)
    original = deepcopy(first)
    first_decision = assess_direct_continuation(image, first)
    second_decision = assess_direct_continuation(image, second)
    assert first_decision == second_decision
    assert first == original
    assert not first_decision.geometry_mutated


def test_reason_and_source_evidence_are_retained_without_model_calls() -> None:
    candidate = _candidate()
    image = _image(candidate)
    decision = assess_direct_continuation(image, candidate)
    payload = decision.to_dict()
    assert payload["reason"] == DirectContinuationReason.CLEAR_DIRECT_TRAJECTORY.value
    assert payload["evidence"]["gap_length_px"] == 20
    source = inspect.getsource(assess_direct_continuation)
    assert "candidate_id" not in source
    assert "mobilenet" not in source.lower()
    assert "embedding" not in source.lower()
    assert ".predict(" not in source.lower()


def test_frozen_24_safety_and_reduction_gates() -> None:
    results = evaluate_frozen_24()
    summary = _summary(results)
    assert len(results) == 24
    assert summary["before_admissible"] == 24
    assert summary["valid_direct_object_continuation_preserved"] == 1
    assert summary["valid_annotation_hard_negatives_preserved"] == 6
    assert summary["component_or_node_mediated_rejected"] == 8
    assert summary["candidate_pairing_failures_rejected"] == 13
    assert summary["candidate_admissibility_fix"] == "SAFE"
    assert summary["raw_hough_overspan_root_cause_fixed"] == 0
