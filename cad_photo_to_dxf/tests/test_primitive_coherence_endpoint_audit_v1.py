from __future__ import annotations

import inspect

import cv2
import numpy as np
import pytest

from cad_photo_to_dxf.app.primitive_coherence_endpoint_audit import (
    CoherenceReason,
    CoherenceStatus,
    EndpointReason,
    EndpointStatus,
    assess_primitive_coherence,
    assess_primitive_endpoints,
    build_coherence_profile,
)


HORIZONTAL = {"start": [20, 70], "end": [220, 70]}
VERTICAL = {"start": [70, 20], "end": [70, 220]}


def _blank(width: int = 240, height: int = 140) -> np.ndarray:
    return np.full((height, width), 255, np.uint8)


def _solid(
    *, vertical: bool = False, thickness: int = 2
) -> tuple[np.ndarray, dict[str, list[int]]]:
    image = _blank(140, 240) if vertical else _blank()
    geometry = VERTICAL if vertical else HORIZONTAL
    cv2.line(
        image,
        tuple(geometry["start"]),
        tuple(geometry["end"]),
        0,
        thickness,
        cv2.LINE_AA,
    )
    return image, geometry


@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("thickness", [1, 7])
def test_true_and_thick_straight_strokes_are_coherent(
    vertical: bool, thickness: int
) -> None:
    image, geometry = _solid(vertical=vertical, thickness=thickness)
    decision = assess_primitive_coherence(image, geometry)
    assert decision.status is CoherenceStatus.SUPPORTED
    assert decision.reason is CoherenceReason.COHERENT_LOCAL_TRAJECTORY


def test_noisy_straight_stroke_is_coherent() -> None:
    image, geometry = _solid()
    generator = np.random.default_rng(12091)
    noisy = np.clip(
        image.astype(np.int16)
        + generator.normal(0.0, 9.0, image.shape).astype(np.int16),
        0,
        255,
    ).astype(np.uint8)
    assert (
        assess_primitive_coherence(noisy, geometry).status is CoherenceStatus.SUPPORTED
    )


def test_slightly_wavering_scan_is_not_rejected() -> None:
    image = _blank()
    points = np.asarray(
        [[x, 70 + int(round(1.1 * np.sin(x / 24.0)))] for x in range(20, 221)],
        np.int32,
    )
    cv2.polylines(image, [points], False, 0, 2, cv2.LINE_AA)
    assert (
        assess_primitive_coherence(image, HORIZONTAL).status
        is not CoherenceStatus.REJECTED
    )


@pytest.mark.parametrize("vertical", [False, True])
def test_piecewise_offset_segments_are_rejected(vertical: bool) -> None:
    image = _blank(140, 240) if vertical else _blank()
    geometry = VERTICAL if vertical else HORIZONTAL
    if vertical:
        cv2.line(image, (70, 20), (70, 112), 0, 2)
        cv2.line(image, (75, 112), (75, 220), 0, 2)
        cv2.line(image, (70, 112), (75, 112), 0, 1)
    else:
        cv2.line(image, (20, 70), (112, 70), 0, 2)
        cv2.line(image, (112, 75), (220, 75), 0, 2)
        cv2.line(image, (112, 70), (112, 75), 0, 1)
    decision = assess_primitive_coherence(image, geometry)
    assert decision.status is CoherenceStatus.REJECTED
    assert decision.reason is CoherenceReason.PIECEWISE_LATERAL_SHIFT


def test_staircase_offset_sequence_is_not_supported() -> None:
    image = _blank()
    cv2.line(image, (20, 68), (70, 68), 0, 2)
    cv2.line(image, (70, 70), (120, 70), 0, 2)
    cv2.line(image, (120, 73), (170, 73), 0, 2)
    cv2.line(image, (170, 76), (220, 76), 0, 2)
    assert (
        assess_primitive_coherence(image, HORIZONTAL).status
        is not CoherenceStatus.SUPPORTED
    )


def test_two_separate_lines_on_global_axis_are_disjoint() -> None:
    image = _blank()
    cv2.line(image, (20, 70), (92, 70), 0, 2)
    cv2.line(image, (118, 70), (220, 70), 0, 2)
    decision = assess_primitive_coherence(image, HORIZONTAL)
    assert decision.status is CoherenceStatus.REJECTED
    assert decision.reason is CoherenceReason.DISJOINT_LOCAL_TRAJECTORY


def test_true_line_crossing_perpendicular_line_remains_coherent() -> None:
    image, geometry = _solid()
    cv2.line(image, (120, 30), (120, 110), 0, 2)
    assert (
        assess_primitive_coherence(image, geometry).status is CoherenceStatus.SUPPORTED
    )
    assert (
        assess_primitive_endpoints(image, geometry).status is EndpointStatus.SUPPORTED
    )


def test_true_line_crossing_junction_remains_coherent() -> None:
    image, geometry = _solid()
    cv2.line(image, (120, 70), (150, 40), 0, 2)
    cv2.line(image, (120, 70), (150, 100), 0, 2)
    assert (
        assess_primitive_coherence(image, geometry).status is CoherenceStatus.SUPPORTED
    )


def test_curved_structure_near_line_does_not_force_rejection() -> None:
    image, geometry = _solid()
    cv2.ellipse(image, (120, 54), (28, 14), 0, 180, 360, 0, 2)
    assert (
        assess_primitive_coherence(image, geometry).status
        is not CoherenceStatus.REJECTED
    )


def test_long_line_crossing_symbol_while_continuous_is_supported() -> None:
    image, geometry = _solid()
    cv2.circle(image, (120, 70), 13, 0, 2)
    cv2.line(image, (112, 62), (128, 78), 0, 2)
    assert (
        assess_primitive_coherence(image, geometry).status is CoherenceStatus.SUPPORTED
    )


@pytest.mark.parametrize("vertical", [False, True])
def test_valid_line_ending_cleanly_has_supported_endpoints(vertical: bool) -> None:
    image, geometry = _solid(vertical=vertical)
    decision = assess_primitive_endpoints(image, geometry)
    assert decision.status is EndpointStatus.SUPPORTED
    assert decision.reason is EndpointReason.SOURCE_TERMINATION_ALIGNED


def test_endpoint_overshoot_into_offset_straight_stroke_is_flagged() -> None:
    image = _blank()
    cv2.line(image, (20, 70), (185, 70), 0, 2)
    cv2.line(image, (185, 75), (220, 75), 0, 5)
    cv2.line(image, (185, 70), (185, 75), 0, 1)
    decision = assess_primitive_endpoints(image, HORIZONTAL)
    assert decision.status is not EndpointStatus.SUPPORTED
    assert decision.reason in {
        EndpointReason.FOREIGN_STROKE_CAPTURE,
        EndpointReason.ENDPOINT_IDENTITY_CHANGE,
        EndpointReason.OVERSHOOT_BEYOND_SOURCE_TERMINATION,
    }


def test_endpoint_overshoot_into_glyph_like_vertical_stroke_is_flagged() -> None:
    image = _blank()
    cv2.line(image, (20, 70), (190, 70), 0, 2)
    cv2.line(image, (190, 54), (190, 88), 0, 5)
    cv2.line(image, (185, 57), (190, 54), 0, 3)
    geometry = {"start": [20, 70], "end": [190, 70]}
    decision = assess_primitive_endpoints(image, geometry)
    assert decision.status is EndpointStatus.UNCERTAIN
    assert decision.reason is EndpointReason.ENDPOINT_IDENTITY_CHANGE


def test_valid_line_near_text_but_not_touching_is_preserved() -> None:
    image, geometry = _solid()
    cv2.putText(image, "A17", (150, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1)
    assert (
        assess_primitive_coherence(image, geometry).status is CoherenceStatus.SUPPORTED
    )


def test_independent_short_lines_distributed_on_axis_are_disjoint() -> None:
    image = _blank()
    for start in (20, 62, 104, 146, 188):
        cv2.line(image, (start, 70), (start + 18, 70), 0, 2)
    assert (
        assess_primitive_coherence(image, HORIZONTAL).status is CoherenceStatus.REJECTED
    )


def test_profiles_are_deterministic_and_do_not_mutate_geometry() -> None:
    image, geometry = _solid()
    original = {key: list(value) for key, value in geometry.items()}
    assert build_coherence_profile(image, geometry) == build_coherence_profile(
        image.copy(), geometry
    )
    coherence = assess_primitive_coherence(image, geometry)
    endpoint = assess_primitive_endpoints(image, geometry, coherence=coherence.evidence)
    assert geometry == original
    assert not coherence.geometry_mutated and not coherence.split_points_created
    assert not endpoint.geometry_mutated and not endpoint.split_points_created


def test_runtime_api_has_no_identity_semantic_ocr_or_model_inputs() -> None:
    for function in (assess_primitive_coherence, assess_primitive_endpoints):
        signature = inspect.signature(function)
        assert "candidate_id" not in signature.parameters
        source = inspect.getsource(function).lower()
        for forbidden in ("filename", "source_family", "ocr", "model", "human"):
            assert forbidden not in source
