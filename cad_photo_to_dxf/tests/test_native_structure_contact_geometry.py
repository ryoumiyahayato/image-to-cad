"""Whole independent paths through shared ink and a source-proved carrier."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.native_objects import structure_contact_geometry as structure
from app.native_objects import text_contact_geometry as contact
from app.native_objects.circular_markers import discover_circular_markers


ROI = [0, 0, 400, 280]


def _source():
    gray = np.full((280, 400), 255, np.uint8)
    cv2.circle(gray, (55, 90), 15, 0, 2)
    cv2.line(gray, (70, 90), (180, 70), 0, 2)
    cv2.line(gray, (180, 70), (260, 105), 0, 2)
    cv2.line(gray, (260, 105), (260, 225), 0, 2)
    cv2.putText(gray, "S", (242, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 2)
    cv2.line(gray, (180, 225), (370, 225), 0, 2)
    carrier = {
        "id": "observed-independent-line",
        "kind": "LINE",
        "layer": "GEOMETRY",
        "geometry": {"start": [180, 225], "end": [370, 225]},
    }
    circles = [
        {
            "id": row["id"],
            "kind": "CIRCLE",
            "layer": "CIRCULAR_MARKERS",
            "geometry": row["geometry"],
            "source_evidence": row["source_evidence"],
        }
        for row in discover_circular_markers(gray, ROI)["rows"]
        if row["geometry_accepted"]
    ]
    assert len(circles) == 1
    return gray, [carrier] + circles


def _targets(plan):
    return [row for row in plan["paths"] if row["path_role"] == "ROUND_TO_CARRIER"]


def test_shared_untranscribed_ink_is_crossed_as_one_reciprocal_round_to_carrier_path():
    gray, prior = _source()
    original = gray.copy()
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    rows = _targets(plan)
    assert len(rows) == 1
    row = rows[0]
    assert row["endpoint_source_points_px"] == [[71.0, 90.0], [260.0, 225.0]]
    assert row["endpoint_evidence"][-1]["kind"] == "OBSERVED_SUPPORTED_LINE_CONTACT"
    assert row["required_carrier_id"] == prior[0]["id"]
    assert row["required_start_circle_id"] == prior[1]["id"]
    assert row["starting_circle_evidence"]["formal_circle_original_source_reverified"]
    assert row["starting_circle_evidence"][
        "original_graph_prefix_matches_measured_circle_source_port"
    ]
    assert row["reverse_source_path_agreement"]["pass"]
    assert len(row["contact_continuations"]) == 3
    assert row["text_content_decision"] == "NOT_PERFORMED"
    assert any(
        c["reason"] == "RECIPROCAL_UNIQUE_SOURCE_PAIR"
        for c in row["contact_continuations"]
    )
    assert all(
        c["unselected_branch_source_paths"] for c in row["contact_continuations"]
    )
    raw = np.asarray(row["source_path_px"])
    assert np.array_equal(raw, np.rint(raw))
    assert np.max(np.linalg.norm(np.diff(raw, axis=0), axis=1)) <= np.sqrt(2) + 1e-12
    # Inside the shared character the connection stays on the vertical shaft;
    # its independent side loops remain available to the other source owner.
    inside = raw[(raw[:, 1] >= 155) & (raw[:, 1] <= 192)]
    assert np.ptp(inside[:, 0]) <= 2
    assert row["structural_terminal_evidence"]["closed_pixel_cells_all_original_ink"]
    assert np.array_equal(gray, original)


def test_ordinary_three_way_branch_without_independent_carrier_evidence_is_not_terminal():
    gray, prior = _source()
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior[1:])
    assert not _targets(plan)
    assert plan["carrier_candidate_count"] == 0


def test_real_white_strip_before_receiver_is_not_closed():
    gray, prior = _source()
    gray[215:220, 255:266] = 255
    original = gray.copy()
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    assert not _targets(plan)
    assert np.array_equal(gray, original)


def test_actual_continuation_across_receiver_is_not_mislabelled_as_a_t_terminal():
    gray, prior = _source()
    cv2.line(gray, (260, 225), (260, 265), 0, 2)
    assert not _targets(structure.plan_structure_contact_geometry(gray, ROI, prior))


def test_two_equal_outgoing_contacts_remain_pending_from_both_trace_directions():
    gray, prior = _source()
    gray[204:225, 257:264] = 255
    cv2.line(gray, (260, 202), (240, 225), 0, 2)
    cv2.line(gray, (260, 202), (280, 225), 0, 2)
    original = gray.copy()
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    assert not _targets(plan)
    assert any(
        p["reason"] == "CONTACT_PAIR_OR_COMPETITION_NOT_UNIQUE" for p in plan["pending"]
    )
    assert np.array_equal(gray, original)


def test_source_corners_and_parallel_edge_can_prove_a_new_separate_carrier():
    gray, prior = _source()
    cv2.line(gray, (180, 225), (180, 245), 0, 2)
    cv2.line(gray, (180, 245), (370, 245), 0, 2)
    cv2.line(gray, (370, 245), (370, 225), 0, 2)
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior[1:])
    rows = _targets(plan)
    carriers = [p for p in plan["paths"] if p["path_role"] == "SUPPORTING_CARRIER"]
    assert len(rows) == len(carriers) == 1
    carrier = carriers[0]
    assert len(carrier["representation"]["points"]) == 2
    assert carrier["carrier_id"] == rows[0]["required_carrier_id"]
    assert all(
        carrier["endpoint_representation_adjustments"][i]["all_original_ink"]
        for i in (0, 1)
    )
    assert carrier["structural_carrier_evidence"]["independent_parallel_source_witness"]
    assert plan["paths"].index(carrier) < plan["paths"].index(rows[0])


@pytest.mark.parametrize("mutation", ["missing", "unproved", "duplicate"])
def test_round_proposal_without_one_source_verified_formal_circle_remains_pending(
    mutation,
):
    gray, prior = _source()
    if mutation == "missing":
        prior = prior[:1]
    elif mutation == "unproved":
        prior[1]["source_evidence"]["crop_sha256"] = "0" * 64
    else:
        other = deepcopy(prior[1])
        other["id"] += "-second-native-owner"
        prior.append(other)
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    assert not _targets(plan)
    reason = (
        "START_CIRCLE_BINDING_AMBIGUOUS"
        if mutation == "duplicate"
        else "START_CIRCLE_NOT_SOURCE_VERIFIED"
    )
    rejected = [row for row in plan["pending"] if row["reason"] == reason]
    assert len(rejected) == 1
    observation = rejected[0]["path_observation"]
    assert observation["source_path_px"][0] == [71.0, 90.0]
    assert observation["source_path_px"][-1] == [260.0, 225.0]
    assert observation["contact_continuations"]
    assert rejected[0]["original_source_observation_retained"]
    assert not rejected[0]["formal_complete_path_adopted"]
    assert structure.verify_structure_contact_geometry_plan(gray, ROI, plan)["pass"]


def test_cold_replay_rechecks_carrier_ownership_competitors_and_actual_endpoint_adjustment():
    gray, prior = _source()
    graph = contact.build_text_contact_source_graph(gray, ROI)
    plan = structure.plan_structure_contact_geometry(
        gray, ROI, prior, source_graph=graph
    )
    result = structure.verify_structure_contact_geometry_plan(
        gray, ROI, plan, source_graph=graph
    )
    assert result["pass"] and result["replayed_paths"] == plan["paths"]
    mutations = [
        lambda p: p["paths"][0].update(required_carrier_id="another-carrier"),
        lambda p: p["paths"][0].update(required_start_circle_id="another-circle"),
        lambda p: p["paths"][0]["starting_circle_evidence"].update(
            observed_circle_contact_port_index=99
        ),
        lambda p: p["prior_circle_source_bindings"][0]["source_evidence"].update(
            crop_sha256="0" * 64
        ),
        lambda p: p["paths"][0]["contact_continuations"].clear(),
        lambda p: p["paths"][0]["native_endpoint_points_px"][-1].__setitem__(0, 261),
        lambda p: p["paths"][0]["endpoint_representation_adjustments"].clear(),
        lambda p: p.update(original_source_pixels_modified=True),
        lambda p: p["unchanged_connection_source_policy"].update(
            maximum_white_gap_px=99
        ),
        lambda p: p["prior_object_bindings"][0]["geometry"].update(end=[350, 225]),
    ]
    for mutate in mutations:
        forged = deepcopy(plan)
        mutate(forged)
        assert not structure.verify_structure_contact_geometry_plan(
            gray, ROI, forged, source_graph=graph
        )["pass"]
    forged = deepcopy(plan)
    forged["prior_circle_source_bindings"][0]["source_evidence"]["crop_sha256"] = (
        "0" * 64
    )
    forged["prior_circle_source_bindings_sha256"] = structure._digest(
        forged["prior_circle_source_bindings"]
    )
    assert not structure.verify_structure_contact_geometry_plan(
        gray, ROI, forged, source_graph=graph
    )["pass"]
