from __future__ import annotations

import inspect

import cv2
import numpy as np

from cad_photo_to_dxf.app.primitive_span_integrity import (
    SpanIntegrityReason,
    SpanIntegrityStatus,
    assess_primitive_span,
    build_span_support_profile,
    qualify_dev_hough_primitives,
)
from cad_photo_to_dxf.scripts.run_primitive_span_support_integrity_v1 import (
    _summary,
    evaluate_frozen_24,
    threshold_sensitivity,
)


GEOMETRY = {"start": [20, 50], "end": [180, 50]}


def _solid() -> np.ndarray:
    image = np.full((100, 200), 255, np.uint8)
    cv2.line(image, (20, 50), (180, 50), 0, 3)
    return image


def test_span_samples_are_ordered_deterministic_and_cover_full_span() -> None:
    image = _solid()
    first = build_span_support_profile(image, GEOMETRY)
    second = build_span_support_profile(image, GEOMETRY)
    assert first == second
    positions = [sample.t for sample in first.samples]
    assert positions == sorted(positions)
    assert positions[0] == 0.0
    assert positions[-1] == 1.0
    assert len(positions) > 2


def test_endpoints_alone_do_not_make_full_span_supported() -> None:
    image = np.full((100, 200), 255, np.uint8)
    cv2.circle(image, (20, 50), 4, 0, -1)
    cv2.circle(image, (180, 50), 4, 0, -1)
    decision = assess_primitive_span(image, GEOMETRY)
    assert decision.status is not SpanIntegrityStatus.SUPPORTED
    assert decision.evidence.longest_internal_gap_fraction > 0.5


def test_short_isolated_dropout_does_not_automatically_reject() -> None:
    image = _solid()
    image[48:53, 100:102] = 255
    decision = assess_primitive_span(image, GEOMETRY)
    assert decision.status is SpanIntegrityStatus.SUPPORTED
    assert decision.reason is SpanIntegrityReason.CONTINUOUS_SOURCE_SUPPORT


def test_material_internal_support_collapse_is_detectable() -> None:
    image = _solid()
    image[45:56, 86:116] = 255
    decision = assess_primitive_span(image, GEOMETRY)
    assert decision.status is SpanIntegrityStatus.REJECTED
    assert decision.reason is SpanIntegrityReason.MATERIAL_INTERNAL_SUPPORT_COLLAPSE
    assert decision.evidence.material_internal_gap_count >= 1


def test_competing_structure_strengthens_material_collapse() -> None:
    image = _solid()
    image[35:66, 84:118] = 255
    cv2.line(image, (101, 25), (101, 75), 0, 2)
    decision = assess_primitive_span(image, GEOMETRY)
    assert decision.status is SpanIntegrityStatus.REJECTED
    assert decision.reason is SpanIntegrityReason.COMPETING_STRUCTURE_IN_SPAN
    assert decision.evidence.competing_structure_samples > 0


def test_periodic_pattern_is_uncertain_not_rejected() -> None:
    image = np.full((100, 200), 255, np.uint8)
    for start in range(20, 181, 20):
        cv2.line(image, (start, 50), (min(start + 10, 180), 50), 0, 2)
    decision = assess_primitive_span(image, GEOMETRY)
    assert decision.status is SpanIntegrityStatus.UNCERTAIN
    assert decision.reason in {
        SpanIntegrityReason.POSSIBLE_PATTERNED_STROKE,
        SpanIntegrityReason.NOISY_OR_DEGRADED_SUPPORT,
    }


def test_qualification_keeps_uncertain_separate_and_manufactures_nothing() -> None:
    image = np.full((100, 200), 255, np.uint8)
    for start in range(20, 181, 20):
        cv2.line(image, (start, 50), (min(start + 10, 180), 50), 0, 2)
    record = {"id": "raw-hough-000001", "raw_geometry": GEOMETRY}
    buckets = qualify_dev_hough_primitives(image, [record])
    assert not buckets["supported"]
    assert len(buckets["uncertain"]) == 1
    qualified = buckets["uncertain"][0]
    assert qualified["raw_geometry"] == GEOMETRY
    assert qualified["span_integrity"]["geometry_mutated"] is False
    assert qualified["span_integrity"]["split_points_created"] is False


def test_no_identity_source_family_filename_or_model_inputs_exist() -> None:
    signature = inspect.signature(assess_primitive_span)
    assert set(signature.parameters) == {"gray", "geometry", "thresholds"}
    source = inspect.getsource(assess_primitive_span)
    for forbidden in (
        "candidate_id",
        "filename",
        "source_family",
        "mobilenet",
        "embedding",
        "ocr",
    ):
        assert forbidden not in source.lower()


def test_frozen_24_controls_and_previous_admissibility_are_preserved() -> None:
    first = evaluate_frozen_24()
    second = evaluate_frozen_24()
    assert first == second
    sensitivity = threshold_sensitivity()
    summary = _summary(first, sensitivity)
    assert summary["span_integrity_fix"] == "SAFE"
    assert summary["raw_hough_overspan_detected"] == 3
    assert summary["raw_hough_overspan_root_cause_remediated"] == 3
    assert summary["valid_direct_object_continuation_preserved"] == 1
    assert summary["valid_annotation_hard_negatives_preserved"] == 6
    assert summary["previous_pairing_family_rejections_preserved"] == 13
    assert summary["insufficient_case_preserved_uncertain"] is True
    assert summary["threshold_sensitivity_stable"] is True
    assert summary["model_run"] == "NO"
    assert summary["new_candidate_mining"] == "NO"
