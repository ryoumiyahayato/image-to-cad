"""Whole independent paths through shared ink and a source-proved carrier."""

from copy import deepcopy
import math

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


def test_short_graph_edge_at_adjacent_digit_carries_complete_owned_receiver_source():
    gray, prior = _source()
    cv2.putText(gray, "3", (270, 225), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 1)
    original, before = gray.copy(), deepcopy(prior)
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    rows = _targets(plan)
    assert len(rows) == 1
    row = rows[0]
    terminal = row["structural_terminal_evidence"]
    arms = terminal["carrier_arm_source_continuations"]
    assert len(arms) == 1 and len(arms[0]["source_continuations"]) >= 2
    arm = arms[0]
    assert arm["owner_id"] == prior[0]["id"]
    assert arm["owner_geometry"] == prior[0]["geometry"]
    assert arm["minimum_arm_span_preserved_px"] == 24.0
    assert arm["full_unique_supported_arm_carried"]
    # The complete bottom stroke, including its two distinct source contacts,
    # remains present after the 24-pixel minimum has already been reached.
    raw_carrier = np.asarray(arm["source_points_px"])
    assert raw_carrier[-1, 0] >= 360
    assert np.ptp(raw_carrier[:, 1]) <= 2
    assert all(len(c["all_port_candidates"]) >= 2 for c in arm["source_continuations"])
    assert all(not c["source_branches_deleted"] for c in arm["source_continuations"])
    raw_path = np.asarray(row["source_path_px"])
    inside = raw_path[raw_path[:, 1] >= 155]
    assert np.ptp(inside[:, 0]) <= 2
    assert terminal["source_contact_point_px"] == [260.0, 225.0]
    assert prior == before and np.array_equal(gray, original)
    assert structure.verify_structure_contact_geometry_plan(gray, ROI, plan)["pass"]
    forged = deepcopy(plan)
    target = _targets(forged)[0]
    target["structural_terminal_evidence"]["carrier_arm_source_continuations"][0][
        "source_continuations"
    ][0]["all_port_candidates"].pop()
    assert not structure.verify_structure_contact_geometry_plan(gray, ROI, forged)["pass"]


def test_owned_receiver_continuation_never_bridges_a_later_original_white_gap():
    gray, prior = _source()
    cv2.putText(gray, "3", (270, 225), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 1)
    gray[222:229, 315:321] = 255
    original = gray.copy()
    plan = structure.plan_structure_contact_geometry(gray, ROI, prior)
    assert not _targets(plan)
    assert np.array_equal(gray, original)


def _close_contact_source(*, competing=False):
    """Small public pen drawing shared with the Windows feature fixture."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (340, 360), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse((38, 128, 82, 172), outline=0, width=3)
    curve = []
    for index in range(181):
        t = index / 180
        curve.append((
            round((1 - t) ** 2 * 82 + 2 * (1 - t) * t * 140 + t * t * 235),
            round((1 - t) ** 2 * 150 + 2 * (1 - t) * t * 35 + t * t * 260),
        ))
    curve.append((235, 330))
    draw.line(curve, fill=0, width=3)
    for index in (95, 118, 123):
        point = np.asarray(curve[index], float)
        tangent = np.asarray(curve[index + 4], float) - np.asarray(curve[index - 4], float)
        normal = np.asarray([-tangent[1], tangent[0]]) / np.linalg.norm(tangent)
        if index == 123:
            angle = (-1 if competing else 1) * math.pi / 4
            normal = np.asarray([[math.cos(angle), -math.sin(angle)],
                                 [math.sin(angle), math.cos(angle)]]) @ normal
        distances = (-16, 16) if index == 95 else (
            (0, 16) if competing and index == 123 else (-16, 0)
        )
        draw.line([tuple(np.rint(point + normal * span).astype(int)) for span in distances],
                  fill=0, width=2)
    draw.line((155, 330, 315, 330), fill=0, width=3)
    gray, roi = np.asarray(image), [0, 0, 340, 360]
    prior = [{"id": r["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
              "geometry": r["geometry"], "source_evidence": r["source_evidence"]}
             for r in discover_circular_markers(gray, roi)["rows"] if r["geometry_accepted"]]
    prior.append({"id": "independent-receiver", "kind": "LINE", "layer": "GEOMETRY",
                  "geometry": {"start": [155, 330], "end": [315, 330]}})
    return gray, roi, prior


def test_nearby_crossing_direction_uses_independently_proved_acyclic_source_pairs():
    gray, roi, prior = _close_contact_source()
    graph = contact.build_text_contact_source_graph(gray, roi)
    before = {nid: dict(n["pairing"]) for nid, n in graph.graph.nodes.items()}
    plan = structure.plan_structure_contact_geometry(gray, roi, prior, source_graph=graph)
    assert len(_targets(plan)) == 1
    row = _targets(plan)[0]
    dependencies = [c["direction_dependency_proofs"] for c in row["contact_continuations"]
                    if c.get("direction_dependency_proofs")]
    assert len(dependencies) == 1
    proof = dependencies[0]
    assert proof["original_unresolved_direction_evidence"]["reason"] == "CONTACT_PAIR_OR_COMPETITION_NOT_UNIQUE"
    assert proof["unchanged_pair_deviation_limit_deg"] == 20.0
    assert proof["unchanged_competition_margin_deg"] == 18.0
    assert proof["proofs"]
    rounds = {p["proof_id"]: p["round"] for p in proof["proofs"]}
    for p in proof["proofs"]:
        assert min(p["worst_case_competition_margins_deg"]) >= 18
        assert all(rounds[d] < p["round"] for d in p["evidence"].get("verified_direction_dependencies", []))
    assert before == {nid: dict(n["pairing"]) for nid, n in graph.graph.nodes.items()}
    assert row["reverse_source_path_agreement"]["pass"]
    assert structure.verify_structure_contact_geometry_plan(gray, roi, plan, source_graph=graph)["pass"]
    forged = deepcopy(plan)
    c = next(c for c in _targets(forged)[0]["contact_continuations"] if c.get("direction_dependency_proofs"))
    c["direction_dependency_proofs"]["proofs"].clear()
    assert not structure.verify_structure_contact_geometry_plan(gray, roi, forged, source_graph=graph)["pass"]


def test_competing_contact_cannot_become_unique_by_tracing_from_the_receiver():
    gray, roi, prior = _close_contact_source(competing=True)
    graph = contact.build_text_contact_source_graph(gray, roi)
    plan = structure.plan_structure_contact_geometry(gray, roi, prior, source_graph=graph)
    assert not _targets(plan)
    assert any(p["reason"] == "CONTACT_PAIR_OR_COMPETITION_NOT_UNIQUE" for p in plan["pending"])
    carriers, _ = structure._carrier_candidates(graph.graph, structure._bindings(prior))
    assert len(carriers) == 1
    (_, incoming), _ = next(iter(carriers.items()))
    reverse = structure._trace(graph.graph, incoming, carriers, {})
    assert reverse["reason"] == "CONTACT_PAIR_OR_COMPETITION_NOT_UNIQUE"


def _short_owned_receiver_cap_source():
    gray, roi, prior = _close_contact_source()
    gray = gray.copy()
    cv2.putText(gray, "3", (245, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 1)
    # A normally fitted finite LINE can end beyond the centre skeleton, while
    # remaining within the existing 3-pixel limit of the complete original cap.
    prior[-1]["geometry"]["end"][0] += 1.4
    return gray, roi, prior


def test_complete_free_source_cap_is_carried_without_modifying_skeleton_or_owner():
    gray, roi, prior = _short_owned_receiver_cap_source()
    context = contact.build_text_contact_source_graph(gray, roi)
    original, skeleton, owners = gray.copy(), context.graph.skel.copy(), deepcopy(prior)
    plan = structure.plan_structure_contact_geometry(gray, roi, prior, source_graph=context)
    assert len(_targets(plan)) == 1
    arms = _targets(plan)[0]["structural_terminal_evidence"]["carrier_arm_source_continuations"]
    caps = [a["source_continuation_stop"]["complete_free_source_cap"] for a in arms
            if "complete_free_source_cap" in a["source_continuation_stop"]]
    assert len(caps) == 1
    cap = caps[0]
    assert cap["complete_source_cap_path_px"] == [[313.0, 330.0], [314.0, 330.0], [315.0, 330.0]]
    assert not cap["graph_skeleton_modified"] and not cap["source_pixels_modified"]
    assert cap["finite_owner_endpoint_tolerance_px"] == 3.0
    assert cap["local_cap_proof"]["white_cap_original_pixel_count"] > 0
    assert cap["local_cap_proof"]["no_gap_filled"] and cap["local_cap_proof"]["no_branch_pruned"]
    assert np.array_equal(gray, original) and np.array_equal(context.graph.skel, skeleton)
    assert prior == owners
    assert structure.verify_structure_contact_geometry_plan(gray, roi, plan, source_graph=context)["pass"]
    forged = deepcopy(plan)
    arm = _targets(forged)[0]["structural_terminal_evidence"]["carrier_arm_source_continuations"][0]
    arm["source_continuation_stop"]["complete_free_source_cap"]["complete_source_cap_path_px"].pop()
    assert not structure.verify_structure_contact_geometry_plan(gray, roi, forged, source_graph=context)["pass"]


@pytest.mark.parametrize("obstacle", ["white_gap", "owner_beyond_source_cap"])
def test_short_cap_observation_cannot_bridge_gap_branch_or_extend_finite_owner(obstacle):
    gray, roi, prior = _short_owned_receiver_cap_source()
    if obstacle == "white_gap":
        gray[328:333, 314] = 255
    else:
        prior[-1]["geometry"]["end"][0] += 3.1
    before, owners = gray.copy(), deepcopy(prior)
    assert not _targets(structure.plan_structure_contact_geometry(gray, roi, prior))
    assert np.array_equal(gray, before) and prior == owners


def test_turning_terminal_branch_is_not_claimed_as_a_straight_source_cap():
    gray, roi, prior = _short_owned_receiver_cap_source()
    cv2.line(gray, (313, 330), (318, 323), 0, 2)
    before = gray.copy()
    plan = structure.plan_structure_contact_geometry(gray, roi, prior)
    # Enough receiver source may still support the arrival, but its later bend
    # cannot be silently reclassified as a complete straight terminal cap.
    assert len(_targets(plan)) == 1
    arms = _targets(plan)[0]["structural_terminal_evidence"]["carrier_arm_source_continuations"]
    assert arms
    assert all("complete_free_source_cap" not in a["source_continuation_stop"] for a in arms)
    stops = [a["source_continuation_stop"] for a in arms]
    assert all(s["reason"] == "END_OF_UNIQUE_STRAIGHT_SOURCE_ARM_AT_OBSERVED_JUNCTION" for s in stops)
    assert any(any(not p["follows_finite_owner"] and p["maximum_owner_normal_px"] > 1.5
                   for p in s["all_port_candidates"]) for s in stops)
    assert np.array_equal(gray, before)
