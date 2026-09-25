from __future__ import annotations

import inspect

import cv2
import numpy as np
import pytest

from cad_photo_to_dxf.app.primitive_axis_support_integrity import (
    AxisSupportReason,
    AxisSupportStatus,
    assess_primitive_axis,
    build_axis_support_profile,
)
from cad_photo_to_dxf.app.primitive_span_integrity import (
    qualify_dev_hough_primitives,
)
from cad_photo_to_dxf.scripts.run_primitive_axis_support_integrity_v1 import (
    evaluate_frozen_controls,
)


HORIZONTAL = {"start": [20, 60], "end": [180, 60]}
VERTICAL = {"start": [60, 20], "end": [60, 180]}


def _blank(width: int = 200, height: int = 120) -> np.ndarray:
    return np.full((height, width), 255, np.uint8)


def _solid(*, vertical: bool = False, thickness: int = 3) -> np.ndarray:
    image = _blank(120, 200) if vertical else _blank()
    geometry = VERTICAL if vertical else HORIZONTAL
    cv2.line(
        image,
        tuple(geometry["start"]),
        tuple(geometry["end"]),
        0,
        thickness,
        cv2.LINE_AA,
    )
    return image


def test_true_single_solid_strokes_are_supported_in_both_orientations() -> None:
    for image, geometry in ((_solid(), HORIZONTAL), (_solid(vertical=True), VERTICAL)):
        decision = assess_primitive_axis(image, geometry)
        assert decision.status is AxisSupportStatus.SUPPORTED
        assert decision.reason is AxisSupportReason.DIRECT_AXIS_SUPPORT
        assert decision.evidence.on_axis_direct_support_fraction >= 0.95


def test_blurred_single_straight_stroke_is_supported() -> None:
    image = cv2.GaussianBlur(_solid(thickness=2), (7, 7), 1.4)
    assert assess_primitive_axis(image, HORIZONTAL).status is AxisSupportStatus.SUPPORTED


def test_noisy_scanned_single_stroke_is_supported() -> None:
    generator = np.random.default_rng(4812)
    image = np.clip(
        _solid(thickness=2).astype(np.int16)
        + generator.normal(0.0, 11.0, (120, 200)).astype(np.int16),
        0,
        255,
    ).astype(np.uint8)
    assert assess_primitive_axis(image, HORIZONTAL).status is AxisSupportStatus.SUPPORTED


@pytest.mark.parametrize(
    ("vertical", "closed_ends"),
    ((False, True), (True, True), (False, False)),
)
def test_hollow_band_and_parallel_centerlines_are_rejected(
    vertical: bool, closed_ends: bool
) -> None:
    image = _blank(120, 200) if vertical else _blank()
    if vertical:
        cv2.line(image, (58, 20), (58, 180), 0, 1)
        cv2.line(image, (62, 20), (62, 180), 0, 1)
        if closed_ends:
            cv2.line(image, (58, 20), (62, 20), 0, 1)
            cv2.line(image, (58, 180), (62, 180), 0, 1)
        geometry = VERTICAL
    else:
        cv2.line(image, (20, 58), (180, 58), 0, 1)
        cv2.line(image, (20, 62), (180, 62), 0, 1)
        if closed_ends:
            cv2.line(image, (20, 58), (20, 62), 0, 1)
            cv2.line(image, (180, 58), (180, 62), 0, 1)
        geometry = HORIZONTAL
    decision = assess_primitive_axis(image, geometry)
    assert decision.status is AxisSupportStatus.REJECTED
    assert decision.reason is AxisSupportReason.SYMMETRIC_FLANK_WITH_CENTER_VOID
    evidence = decision.evidence
    assert evidence.on_axis_direct_support_fraction <= 0.05
    assert evidence.symmetric_flank_center_void_fraction >= 0.90
    assert evidence.broad_corridor_support_fraction >= 0.95


def test_dashed_pattern_is_uncertain_not_center_void_rejected() -> None:
    image = _blank()
    for start in range(20, 181, 24):
        cv2.line(image, (start, 60), (min(start + 12, 180), 60), 0, 2)
    decision = assess_primitive_axis(image, HORIZONTAL)
    assert decision.status is AxisSupportStatus.UNCERTAIN
    assert decision.reason in {
        AxisSupportReason.POSSIBLE_PATTERNED_AXIS_SUPPORT,
        AxisSupportReason.NOISY_OR_DEGRADED_AXIS_SUPPORT,
    }


def test_valid_stroke_crossing_perpendicular_line_is_supported() -> None:
    image = _solid()
    cv2.line(image, (100, 25), (100, 95), 0, 2)
    assert assess_primitive_axis(image, HORIZONTAL).status is AxisSupportStatus.SUPPORTED


def test_valid_stroke_near_text_is_supported() -> None:
    image = _solid()
    cv2.putText(
        image,
        "A17",
        (75, 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        0,
        1,
        cv2.LINE_AA,
    )
    assert assess_primitive_axis(image, HORIZONTAL).status is AxisSupportStatus.SUPPORTED


def test_small_degradation_between_collinear_fragments_is_supported() -> None:
    image = _solid(thickness=2)
    image[56:65, 97:103] = 255
    decision = assess_primitive_axis(image, HORIZONTAL)
    assert decision.status is AxisSupportStatus.SUPPORTED
    assert decision.evidence.longest_unsupported_axis_interval_fraction < 0.08


def test_true_intentional_gap_is_not_supported() -> None:
    image = _solid(thickness=2)
    image[52:69, 84:117] = 255
    decision = assess_primitive_axis(image, HORIZONTAL)
    assert decision.status is not AxisSupportStatus.SUPPORTED
    assert decision.evidence.longest_unsupported_axis_interval_fraction > 0.15


def test_slight_skew_antialiased_stroke_is_supported() -> None:
    image = _blank()
    geometry = {"start": [20, 55], "end": [180, 64]}
    cv2.line(image, (20, 55), (180, 64), 0, 2, cv2.LINE_AA)
    assert assess_primitive_axis(image, geometry).status is AxisSupportStatus.SUPPORTED


def test_two_nearby_engineering_edges_preserve_axis_on_real_edge() -> None:
    image = _blank()
    cv2.line(image, (20, 57), (180, 57), 0, 1)
    cv2.line(image, (20, 63), (180, 63), 0, 1)
    geometry = {"start": [20, 57], "end": [180, 57]}
    decision = assess_primitive_axis(image, geometry)
    assert decision.status is AxisSupportStatus.SUPPORTED
    assert decision.evidence.on_axis_direct_support_fraction >= 0.95


def test_one_pixel_unilateral_hough_offset_is_immediate_axis_support() -> None:
    image = _blank()
    cv2.line(image, (20, 59), (180, 59), 0, 1)
    decision = assess_primitive_axis(image, HORIZONTAL)
    assert decision.status is AxisSupportStatus.SUPPORTED
    assert decision.evidence.exact_axis_support_fraction == 0.0
    assert decision.evidence.on_axis_direct_support_fraction >= 0.95
    assert decision.evidence.symmetric_flank_center_void_fraction == 0.0


def test_wide_thick_stroke_is_supported() -> None:
    image = _solid(thickness=11)
    assert assess_primitive_axis(image, HORIZONTAL).status is AxisSupportStatus.SUPPORTED


def test_profile_is_deterministic_and_distinguishes_three_support_types() -> None:
    image = _blank()
    cv2.line(image, (20, 58), (180, 58), 0, 1)
    cv2.line(image, (20, 62), (180, 62), 0, 1)
    first = build_axis_support_profile(image, HORIZONTAL)
    second = build_axis_support_profile(image.copy(), HORIZONTAL)
    assert first == second
    assert first.on_axis_direct_support_fraction == 0.0
    assert first.symmetric_flank_support_fraction >= 0.95
    assert first.broad_corridor_support_fraction >= 0.95


def test_dev_qualification_composes_axis_guard_after_span_guard() -> None:
    hollow = _blank()
    cv2.line(hollow, (20, 58), (180, 58), 0, 1)
    cv2.line(hollow, (20, 62), (180, 62), 0, 1)
    record = {"id": "raw-hough-test", "raw_geometry": HORIZONTAL}
    hollow_buckets = qualify_dev_hough_primitives(hollow, [record])
    assert len(hollow_buckets["rejected"]) == 1
    rejected = hollow_buckets["rejected"][0]
    assert rejected["span_integrity"]["status"] == "SPAN_INTEGRITY_SUPPORTED"
    assert (
        rejected["axis_support_integrity"]["reason"]
        == "SYMMETRIC_FLANK_WITH_CENTER_VOID"
    )

    solid_buckets = qualify_dev_hough_primitives(_solid(), [record])
    assert len(solid_buckets["supported"]) == 1


def test_no_identity_filename_semantics_ocr_or_model_inputs_exist() -> None:
    signature = inspect.signature(assess_primitive_axis)
    assert set(signature.parameters) == {"gray", "geometry", "thresholds"}
    source = inspect.getsource(assess_primitive_axis).lower()
    for forbidden in (
        "candidate_id",
        "filename",
        "source_family",
        "rectangle",
        "duct",
        "symbol",
        "ocr",
        "model",
    ):
        assert forbidden not in source


def test_frozen_span_admissibility_and_valid_axis_controls_are_preserved() -> None:
    _rows, summary = evaluate_frozen_controls()
    assert summary["previous_span_guard_safe"] is True
    assert summary["previous_raw_hough_overspan_detected"] == 3
    assert summary["previous_admissibility_pairing_rejections_preserved"] == 13
    assert summary["valid_direct_object_controls_supported"] == 1
    assert summary["valid_direct_object_controls_total"] == 1
    assert summary["valid_annotation_controls_supported"] == 6
    assert summary["valid_annotation_controls_total"] == 6
