from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.endpoint_topology_source_identity import (
    NegativeIdentityEvidence,
    PositiveIdentityEvidence,
    SourceIdentityStatus,
    assess_source_pair_identity,
    gap_ridge_evidence,
    profile_endpoint_topology,
)
from app.line_detect import LineSegment
from app.source_stroke_multiplicity import (
    SourceStrokeObservation,
    SourceStrokeRegistry,
    capture_line_hypotheses,
    group_coincident_or_near_coincident,
)


def _line(x1: float, y1: float, x2: float, y2: float, source: str) -> LineSegment:
    return LineSegment(x1, y1, x2, y2, source_ids=(source,))


def _stroke(
    stroke_id: str,
    geometry: LineSegment,
    *,
    confirmed: bool = True,
):
    if not confirmed:
        return capture_line_hypotheses([geometry]).strokes[0]
    observation = SourceStrokeObservation.from_line(
        geometry,
        observation_id=f"observation:{stroke_id}",
        source_instance_id=stroke_id,
    )
    return SourceStrokeRegistry.from_observations([observation]).strokes[0]


def _canvas() -> np.ndarray:
    return np.full((100, 140), 255, dtype=np.uint8)


def _profile_pair(
    image: np.ndarray,
    left,
    right,
    *,
    groups=(),
):
    profile_a = profile_endpoint_topology(image, left, 1, groups=groups)
    profile_b = profile_endpoint_topology(image, right, 0, groups=groups)
    support = gap_ridge_evidence(image, profile_a, profile_b)
    return profile_a, profile_b, support


def test_dropout_continuation_is_supported_by_shared_identity() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (58, 50), 0, 1)
    cv2.line(image, (64, 50), (120, 50), 0, 1)
    left = _stroke("CONTINUOUS", _line(10, 50, 58, 50, "left"))
    right = _stroke("CONTINUOUS", _line(64, 50, 120, 50, "right"))
    a, b, support = _profile_pair(image, left, right)

    result = assess_source_pair_identity(
        "dropout", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert result.identity_status is SourceIdentityStatus.SUPPORTED
    assert (
        PositiveIdentityEvidence.SHARED_CONFIRMED_SOURCE_STROKE.value
        in result.positive_evidence
    )


def test_two_independently_ending_collinear_segments_are_rejected() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (50, 50), 0, 1)
    cv2.line(image, (82, 50), (120, 50), 0, 1)
    left = _stroke("LEFT-SOURCE", _line(10, 50, 50, 50, "left"))
    right = _stroke("RIGHT-SOURCE", _line(82, 50, 120, 50, "right"))
    a, b, support = _profile_pair(image, left, right)

    result = assess_source_pair_identity(
        "independent", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert result.identity_status is SourceIdentityStatus.REJECTED
    assert (
        NegativeIdentityEvidence.DISTINCT_CONFIRMED_SOURCE_INSTANCES.value
        in result.negative_evidence
    )
    assert (
        NegativeIdentityEvidence.INDEPENDENT_ENDPOINT_TERMINATION.value
        in result.negative_evidence
    )


def test_crossing_with_axial_continuation_is_not_mistaken_for_termination() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (120, 50), 0, 1)
    cv2.line(image, (60, 25), (60, 75), 0, 1)
    left = _stroke("CROSSING-SOURCE", _line(10, 50, 60, 50, "left"))
    right = _stroke("CROSSING-SOURCE", _line(60, 50, 120, 50, "right"))
    a, b, support = _profile_pair(image, left, right)

    result = assess_source_pair_identity(
        "crossing", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert a.crossing_evidence >= 0.6
    assert a.termination_strength < 0.35
    assert result.identity_status is SourceIdentityStatus.SUPPORTED
    assert (
        PositiveIdentityEvidence.CROSSING_WITH_AXIAL_CONTINUATION.value
        in result.positive_evidence
    )


def test_t_junction_termination_is_rejected_without_semantic_labels() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (55, 50), 0, 1)
    cv2.line(image, (55, 25), (55, 75), 0, 1)
    cv2.line(image, (80, 50), (120, 50), 0, 1)
    left = _stroke("T-LEFT", _line(10, 50, 55, 50, "left"), confirmed=False)
    right = _stroke("T-RIGHT", _line(80, 50, 120, 50, "right"), confirmed=False)
    a, b, support = _profile_pair(image, left, right)

    result = assess_source_pair_identity(
        "t-junction", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert a.t_junction_evidence >= 0.6
    assert result.identity_status is SourceIdentityStatus.REJECTED
    assert (
        NegativeIdentityEvidence.JUNCTION_TERMINATION.value in result.negative_evidence
    )


def test_corner_termination_is_rejected_without_semantic_labels() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (55, 50), 0, 1)
    cv2.line(image, (55, 50), (55, 78), 0, 1)
    cv2.line(image, (82, 50), (120, 50), 0, 1)
    left = _stroke("CORNER-A", _line(10, 50, 55, 50, "left"), confirmed=False)
    right = _stroke("CORNER-B", _line(82, 50, 120, 50, "right"), confirmed=False)
    a, b, support = _profile_pair(image, left, right)

    result = assess_source_pair_identity(
        "corner", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert a.corner_evidence >= 0.6
    assert result.identity_status is SourceIdentityStatus.REJECTED
    assert NegativeIdentityEvidence.CORNER_TERMINATION.value in result.negative_evidence


def test_nested_coincident_endpoints_preserve_distinct_identity() -> None:
    observations = [
        SourceStrokeObservation.from_line(
            _line(40, 10, 40, 90, "long"),
            observation_id="long-observation",
            source_instance_id="LONG",
        ),
        SourceStrokeObservation.from_line(
            _line(40, 25, 40, 75, "medium"),
            observation_id="medium-observation",
            source_instance_id="MEDIUM",
        ),
        SourceStrokeObservation.from_line(
            _line(40, 40, 40, 60, "short"),
            observation_id="short-observation",
            source_instance_id="SHORT",
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)
    group = group_coincident_or_near_coincident(registry)[0]
    result = assess_source_pair_identity(
        "nested-cross-pair", registry.by_id("LONG"), registry.by_id("MEDIUM")
    )

    assert len(group.member_endpoint_ids) == 6
    assert result.identity_status is SourceIdentityStatus.REJECTED


@pytest.mark.parametrize("offset", [1, 2, 3])
def test_near_coincident_source_identities_are_not_merged(offset: int) -> None:
    observations = [
        SourceStrokeObservation.from_line(
            _line(40, 10, 40, 90, "a"),
            observation_id="a",
            source_instance_id="A",
        ),
        SourceStrokeObservation.from_line(
            _line(40 + offset, 20, 40 + offset, 80, "b"),
            observation_id="b",
            source_instance_id="B",
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)
    group = group_coincident_or_near_coincident(registry)[0]
    result = assess_source_pair_identity("near", *registry.strokes)

    assert len(group.member_stroke_ids) == 2
    assert result.identity_status is SourceIdentityStatus.REJECTED


def test_damaged_line_is_not_rejected_merely_for_weak_endpoint_ink() -> None:
    image = _canvas()
    cv2.line(image, (10, 50), (50, 50), 0, 1)
    cv2.line(image, (58, 50), (120, 50), 0, 1)
    left = _stroke("HYP-A", _line(10, 50, 50, 50, "left"), confirmed=False)
    right = _stroke("HYP-B", _line(58, 50, 120, 50, "right"), confirmed=False)
    a, b, support = _profile_pair(image, left, right)
    result = assess_source_pair_identity(
        "damage", left, right, endpoint_a=a, endpoint_b=b, gap_support=support
    )

    assert result.identity_status is SourceIdentityStatus.AMBIGUOUS
    assert result.pair_admission_action == "CONTINUE_EXISTING_POLICY"


def test_true_thick_stroke_does_not_create_multiple_source_identities() -> None:
    observations = [
        SourceStrokeObservation.from_line(
            _line(48, 10, 48, 90, "left-boundary"),
            observation_id="left-boundary",
            source_instance_id="THICK",
            equivalence_evidence=("filled_cross_band",),
        ),
        SourceStrokeObservation.from_line(
            _line(52, 10, 52, 90, "right-boundary"),
            observation_id="right-boundary",
            source_instance_id="THICK",
            equivalence_evidence=("filled_cross_band",),
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)

    assert len(registry.strokes) == 1
    assert len(registry.strokes[0].observations) == 2


def test_competing_identity_and_multiplicity_transition_are_negative_evidence() -> None:
    image = _canvas()
    cv2.line(image, (40, 10), (40, 90), 0, 1)
    observations = [
        SourceStrokeObservation.from_line(
            _line(40, 10, 40, 90, "long"),
            observation_id="long",
            source_instance_id="LONG",
        ),
        SourceStrokeObservation.from_line(
            _line(40, 25, 40, 50, "short"),
            observation_id="short",
            source_instance_id="SHORT",
        ),
        SourceStrokeObservation.from_line(
            _line(40, 55, 40, 80, "other"),
            observation_id="other",
            source_instance_id="OTHER",
        ),
        SourceStrokeObservation.from_line(
            _line(40, 30, 40, 52, "extra"),
            observation_id="extra",
            source_instance_id="EXTRA",
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)
    groups = group_coincident_or_near_coincident(registry, endpoint_gap_tolerance=5)
    short = registry.by_id("SHORT")
    other = registry.by_id("OTHER")
    a = profile_endpoint_topology(image, short, 1, groups=groups)
    b = profile_endpoint_topology(image, other, 0, groups=groups)
    result = assess_source_pair_identity(
        "competing", short, other, endpoint_a=a, endpoint_b=b
    )

    assert a.competing_stroke_ids
    assert result.identity_status is SourceIdentityStatus.REJECTED
    assert (
        NegativeIdentityEvidence.COMPETING_SOURCE_STROKE_IDENTITY.value
        in result.negative_evidence
    )
    assert (
        NegativeIdentityEvidence.MULTIPLICITY_CHANGE_ACROSS_GAP.value
        in result.negative_evidence
    )


def test_ambiguous_identity_is_not_blanket_rejected() -> None:
    left = _stroke("A", _line(10, 50, 50, 50, "left"), confirmed=False)
    right = _stroke("B", _line(58, 50, 120, 50, "right"), confirmed=False)
    result = assess_source_pair_identity("ambiguous", left, right)

    assert result.identity_status is SourceIdentityStatus.AMBIGUOUS
    assert result.pair_admission_action == "CONTINUE_EXISTING_POLICY"


def test_generic_module_has_no_candidate_or_semantic_exceptions() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "endpoint_topology_source_identity.py"
    ).read_text(encoding="utf-8")

    assert "FRESH1-" not in source
    assert "CASE15" not in source
    assert "CASE16" not in source
    for semantic_name in ("rectangle", "door", "cabinet", "table", "logo", "symbol"):
        assert semantic_name not in source.lower()
