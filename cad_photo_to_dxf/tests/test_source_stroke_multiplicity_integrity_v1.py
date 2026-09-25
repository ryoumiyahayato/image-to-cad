from __future__ import annotations

from pathlib import Path

import pytest

from app.line_detect import LineSegment
from app.line_provenance_audit_v1 import normalize_hough_records
from app.source_stroke_multiplicity import (
    GroupRelationship,
    PairIdentityStatus,
    SourceStrokeObservation,
    SourceStrokeRegistry,
    assess_pair_identity,
    capture_line_hypotheses,
    derive_consolidated_hypothesis,
    group_coincident_or_near_coincident,
)


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source: str,
    *,
    width: float = 1.0,
) -> LineSegment:
    return LineSegment(
        x1,
        y1,
        x2,
        y2,
        width=width,
        source_ids=(source,),
        history=("synthetic-source-evidence",),
    )


def _observation(
    stroke_id: str,
    line: LineSegment,
    *,
    start_junctions: tuple[str, ...] = (),
    end_junctions: tuple[str, ...] = (),
) -> SourceStrokeObservation:
    return SourceStrokeObservation.from_line(
        line,
        observation_id=f"observation:{stroke_id}",
        source_instance_id=stroke_id,
        endpoint_confidence=(0.9, 0.85),
        start_junction_ids=start_junctions,
        end_junction_ids=end_junctions,
    )


def test_case_a_one_isolated_long_line_is_one_source_stroke() -> None:
    registry = SourceStrokeRegistry.from_observations(
        [_observation("LONG", _line(100, 20, 100, 500, "raw-long"))]
    )

    assert len(registry.strokes) == 1
    assert group_coincident_or_near_coincident(registry) == ()


def test_cases_b_c_exact_coincident_extents_and_endpoints_are_preserved() -> None:
    registry = SourceStrokeRegistry.from_observations(
        [
            _observation(
                "LONG",
                _line(100, 20, 100, 500, "raw-long"),
                start_junctions=("A",),
                end_junctions=("D",),
            ),
            _observation(
                "MEDIUM",
                _line(100, 140, 100, 380, "raw-medium"),
                start_junctions=("B",),
                end_junctions=("C",),
            ),
            _observation(
                "SHORT",
                _line(100, 220, 100, 300, "raw-short"),
                start_junctions=("E",),
                end_junctions=("F",),
            ),
        ]
    )
    groups = group_coincident_or_near_coincident(registry)

    assert len(registry.strokes) == 3
    assert len(groups) == 1
    assert groups[0].relationship is GroupRelationship.EXACT_COINCIDENT
    assert [item.multiplicity for item in groups[0].local_multiplicity_profile] == [
        1,
        2,
        3,
        2,
        1,
    ]
    assert {endpoint.point for stroke in registry.strokes for endpoint in stroke.endpoints} == {
        (100.0, 20.0),
        (100.0, 500.0),
        (100.0, 140.0),
        (100.0, 380.0),
        (100.0, 220.0),
        (100.0, 300.0),
    }
    assert set(groups[0].member_endpoint_ids) == {
        "LONG:START",
        "LONG:END",
        "MEDIUM:START",
        "MEDIUM:END",
        "SHORT:START",
        "SHORT:END",
    }


@pytest.mark.parametrize("offsets", [(0, 1, 2), (0, 1, 3), (0, 2, 3)])
def test_cases_d_e_f_near_coincident_1_to_3_px_preserve_trajectories(
    offsets: tuple[int, int, int],
) -> None:
    registry = SourceStrokeRegistry.from_observations(
        [
            _observation(
                f"STROKE-{offset}",
                _line(100 + offset, 20, 100 + offset, 500, f"raw-{offset}"),
            )
            for offset in offsets
        ]
    )
    groups = group_coincident_or_near_coincident(registry, distance_tolerance=3.0)

    assert len(registry.strokes) == 3
    assert len(groups) == 1
    assert groups[0].relationship is GroupRelationship.NEAR_COINCIDENT
    assert len(groups[0].member_geometry) == 3


def _rectangle_observations(
    rectangle_id: str,
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> list[SourceStrokeObservation]:
    edges = {
        "LEFT": _line(left, top, left, bottom, f"{rectangle_id}:raw-left"),
        "TOP": _line(left, top, right, top, f"{rectangle_id}:raw-top"),
        "RIGHT": _line(right, top, right, bottom, f"{rectangle_id}:raw-right"),
        "BOTTOM": _line(left, bottom, right, bottom, f"{rectangle_id}:raw-bottom"),
    }
    return [
        _observation(f"{rectangle_id}:{edge}", geometry)
        for edge, geometry in edges.items()
    ]


def test_case_g_three_nested_rectangles_with_one_exact_side_remain_recoverable() -> None:
    observations = []
    observations += _rectangle_observations(
        "OUTER", left=10, top=10, right=100, bottom=100
    )
    observations += _rectangle_observations(
        "MIDDLE", left=10, top=20, right=90, bottom=90
    )
    observations += _rectangle_observations(
        "INNER", left=10, top=30, right=80, bottom=80
    )
    registry = SourceStrokeRegistry.from_observations(observations)
    groups = group_coincident_or_near_coincident(registry)
    left_group = next(
        group
        for group in groups
        if set(group.member_stroke_ids)
        == {"OUTER:LEFT", "MIDDLE:LEFT", "INNER:LEFT"}
    )

    assert len(registry.strokes) == 12
    assert left_group.relationship is GroupRelationship.EXACT_COINCIDENT
    assert len(left_group.member_geometry) == 3


def test_case_h_nested_near_coincident_sides_do_not_become_one_source_instance() -> None:
    observations = []
    observations += _rectangle_observations(
        "OUTER", left=10, top=10, right=100, bottom=100
    )
    observations += _rectangle_observations(
        "MIDDLE", left=11, top=20, right=90, bottom=90
    )
    observations += _rectangle_observations(
        "INNER", left=13, top=30, right=80, bottom=80
    )
    registry = SourceStrokeRegistry.from_observations(observations)
    groups = group_coincident_or_near_coincident(registry)

    assert len(registry.strokes) == 12
    assert any(
        set(group.member_stroke_ids)
        == {"OUTER:LEFT", "MIDDLE:LEFT", "INNER:LEFT"}
        and group.relationship is GroupRelationship.NEAR_COINCIDENT
        for group in groups
    )


def test_case_i_thin_hollow_rectangle_keeps_two_edges_not_a_source_centerline() -> None:
    registry = SourceStrokeRegistry.from_observations(
        [
            _observation("LEFT-EDGE", _line(50, 20, 50, 220, "raw-left")),
            _observation("RIGHT-EDGE", _line(52, 20, 52, 220, "raw-right")),
        ]
    )
    group = group_coincident_or_near_coincident(registry)[0]
    derived = derive_consolidated_hypothesis(group)

    assert len(registry.strokes) == 2
    assert derived.member_stroke_ids == ("LEFT-EDGE", "RIGHT-EDGE")
    assert derived.to_dict()["replaces_members"] is False


def test_case_j_true_thick_stroke_does_not_hallucinate_two_source_instances() -> None:
    observations = [
        SourceStrokeObservation.from_line(
            _line(50, 20, 50, 220, "edge-left", width=6),
            observation_id="edge-left-detection",
            source_instance_id="THICK-STROKE",
            equivalence_evidence=("filled_cross_band",),
        ),
        SourceStrokeObservation.from_line(
            _line(54, 20, 54, 220, "edge-right", width=6),
            observation_id="edge-right-detection",
            source_instance_id="THICK-STROKE",
            equivalence_evidence=("filled_cross_band",),
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)

    assert len(registry.strokes) == 1
    assert len(registry.strokes[0].observations) == 2
    assert registry.strokes[0].geometry.x1 == pytest.approx(52.0)
    assert set(registry.strokes[0].geometry.source_ids) == {
        "edge-left",
        "edge-right",
    }


def test_case_k_partial_overlap_and_contained_short_line_keep_all_endpoints() -> None:
    registry = SourceStrokeRegistry.from_observations(
        [
            _observation("LONG", _line(0, 40, 200, 40, "raw-long")),
            _observation("PARTIAL", _line(120, 40, 260, 40, "raw-partial")),
            _observation("CONTAINED", _line(80, 40, 100, 40, "raw-contained")),
        ]
    )
    groups = group_coincident_or_near_coincident(registry)

    assert len(registry.strokes) == 3
    assert sum(len(stroke.endpoints) for stroke in registry.strokes) == 6
    assert any(
        set(group.member_stroke_ids) == {"LONG", "CONTAINED"}
        for group in groups
    )
    assert {stroke.stroke_id for stroke in registry.strokes} == {
        "LONG",
        "PARTIAL",
        "CONTAINED",
    }


def test_case_l_damage_fragments_join_only_with_independent_equivalence_evidence() -> None:
    observations = [
        SourceStrokeObservation.from_line(
            _line(0, 75, 95, 75, "damage-left"),
            observation_id="damage-left",
            source_instance_id="DAMAGED-LINE",
            equivalence_evidence=("independent_continuity_support",),
        ),
        SourceStrokeObservation.from_line(
            _line(101, 75, 200, 75, "damage-right"),
            observation_id="damage-right",
            source_instance_id="DAMAGED-LINE",
            equivalence_evidence=("independent_continuity_support",),
        ),
    ]
    registry = SourceStrokeRegistry.from_observations(observations)

    assert len(registry.strokes) == 1
    assert len(registry.strokes[0].observations) == 2
    assert registry.strokes[0].geometry.x1 == pytest.approx(0.0)
    assert registry.strokes[0].geometry.x2 == pytest.approx(200.0)


def test_shared_identity_admits_pair_and_distinct_or_ambiguous_identity_does_not() -> None:
    shared_left = SourceStrokeRegistry.from_observations(
        [_observation("SHARED", _line(0, 0, 40, 0, "left"))]
    ).strokes[0]
    shared_right = SourceStrokeRegistry.from_observations(
        [_observation("SHARED", _line(45, 0, 90, 0, "right"))]
    ).strokes[0]
    other = SourceStrokeRegistry.from_observations(
        [_observation("OTHER", _line(45, 0, 90, 0, "other"))]
    ).strokes[0]
    ambiguous = capture_line_hypotheses(
        [_line(45, 0, 90, 0, "raw-ambiguous")]
    ).strokes[0]

    assert assess_pair_identity([shared_left], [shared_right]).status is (
        PairIdentityStatus.SAME_SOURCE_SUPPORTED
    )
    assert assess_pair_identity([shared_left], [other]).status is (
        PairIdentityStatus.DISTINCT_SOURCE_REJECTED
    )
    ambiguous_decision = assess_pair_identity([shared_left], [ambiguous])
    assert ambiguous_decision.status is PairIdentityStatus.MULTIPLICITY_AMBIGUOUS
    assert ambiguous_decision.admitted is False


def test_aggregated_provenance_is_not_destructively_resurrected_as_fake_instances() -> None:
    already_merged = LineSegment(
        0,
        0,
        200,
        0,
        source_ids=("historic-a", "historic-b"),
        history=("merge_collinear",),
    )
    registry = capture_line_hypotheses([already_merged])

    assert len(registry.strokes) == 1
    assert len(registry.strokes[0].observations) == 1
    assert registry.strokes[0].observations[0].provenance_ids == (
        "historic-a",
        "historic-b",
    )


def test_quantized_hough_duplicate_group_preserves_member_geometry_and_endpoints() -> None:
    raw = [
        {
            "id": "raw-hough-000001",
            "detector": "HOUGH",
            "raw_geometry": {"start": [10, 20], "end": [110, 20]},
            "canonical_geometry": {
                "orientation": "horizontal",
                "axis": 20,
                "start": 10,
                "end": 110,
            },
        },
        {
            "id": "raw-hough-000002",
            "detector": "HOUGH",
            "raw_geometry": {"start": [10, 21], "end": [110, 21]},
            "canonical_geometry": {
                "orientation": "horizontal",
                "axis": 21,
                "start": 10,
                "end": 110,
            },
        },
    ]
    normalized = normalize_hough_records(raw)

    assert len(normalized) == 1
    group = normalized[0]["source_stroke_group"]
    assert group["member_count"] == 2
    assert group["members_preserved"] is True
    assert group["derived_geometry_replaces_members"] is False
    assert [
        member["raw_geometry"] for member in group["member_hypotheses"]
    ] == [record["raw_geometry"] for record in raw]


def test_no_candidate_specific_exceptions_in_generic_module() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "source_stroke_multiplicity.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "FRESH1-" not in source
    assert "CASE15" not in source
    assert "CASE16" not in source
