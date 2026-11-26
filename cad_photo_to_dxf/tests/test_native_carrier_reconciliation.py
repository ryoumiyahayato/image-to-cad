"""Old receiving lines need full source and both finite ends before retirement."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.native_objects import carrier_reconciliation as carriers


ROI = [0, 0, 380, 190]


def _line(oid, start, end):
    return {
        "id": oid,
        "kind": "LINE",
        "layer": "GEOMETRY",
        "geometry": {"start": start, "end": end},
    }


def _source():
    gray = np.full((190, 380), 255, np.uint8)
    cv2.line(gray, (30, 90), (330, 90), 0, 2)
    cv2.line(gray, (30, 90), (30, 150), 0, 1)
    cv2.line(gray, (330, 90), (330, 150), 0, 1)
    old = [
        _line("first-approximation", [29.0, 90.0], [331.0, 90.0]),
        _line("second-approximation", [30.0, 89.3], [331.0, 91.2]),
    ]
    return gray, old


def _plan(gray, old, **kwargs):
    return carriers.plan_existing_carrier_reconciliation(gray, ROI, old, **kwargs)


def test_full_source_and_two_finite_returns_replace_whole_old_expressions_once():
    gray, old = _source()
    before = deepcopy(old)
    original = gray.copy()
    plan = _plan(gray, old, receiving_object_ids=[old[0]["id"]])
    assert plan["retired_ids"] == sorted(obj["id"] for obj in old)
    assert len(plan["objects"]) == 1
    obj = plan["objects"][0]
    assert obj["kind"] == "LINE"
    assert np.allclose(obj["geometry"]["start"], [30, 90], atol=0.6)
    assert np.allclose(obj["geometry"]["end"], [330, 90], atol=0.6)
    proof = plan["decisions"][0]["proof"]
    assert proof["full_extent_source_profiles"]["all_source_profiles_examined"]
    assert all(end["pass"] for end in proof["endpoint_return_proofs"])
    assert not proof["partial_old_line_retirement_permitted"]
    assert carriers.verify_existing_carrier_reconciliation(gray, ROI, plan)["pass"]
    assert old == before and np.array_equal(gray, original)


def test_shared_endpoint_ink_of_transverse_crossing_does_not_become_horizontal_tail():
    gray, old = _source()
    cv2.line(gray, (295, 72), (363, 107), 0, 4)
    old[0]["geometry"]["end"] = [337.0, 90.0]
    old[1]["geometry"]["end"] = [337.0, 91.2]
    plan = _plan(gray, old)
    assert len(plan["objects"]) == 1, plan["decisions"]
    proof = plan["decisions"][0]["proof"]
    end = proof["endpoint_return_proofs"][1]["candidate_returns"][0]
    assert end["maximum_old_endpoint_extrapolation_px"] > 5
    assert (
        end["exterior_departure_proof"]["kind"]
        == "NONPARALLEL_INDEPENDENT_END_CROSSING"
    )
    assert not end["exterior_departure_proof"][
        "departing_source_stroke_adopted_as_part_of_carrier"
    ]
    assert abs(plan["objects"][0]["geometry"]["end"][0] - 330) < 0.6


def test_two_near_parallel_source_lines_with_one_pixel_white_strip_are_preserved():
    gray = np.full((190, 380), 255, np.uint8)
    for y in (90, 92):
        cv2.line(gray, (30, y), (330, y), 0, 1)
    old = [_line("upper", [30, 90], [330, 90]), _line("lower", [30, 92], [330, 92])]
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    proof = plan["decisions"][0]["proof"]
    assert proof["full_extent_source_profiles"]["distinct_original_runs_at_stations_px"]
    assert np.all(gray[91, 30:331] == 255)


def test_short_independent_parallel_end_or_branch_is_not_a_transverse_competitor():
    gray, old = _source()
    gray[89:92, 30:331] = 255
    cv2.line(gray, (30, 90), (330, 90), 0, 1)
    cv2.line(gray, (150, 92), (162, 92), 0, 1)
    old[0]["geometry"] = {"start": [30, 90], "end": [330, 90]}
    old[1]["geometry"] = {"start": [30, 91.3], "end": [330, 91.3]}
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    proof = plan["decisions"][0]["proof"]
    assert proof["full_extent_source_profiles"]["distinct_original_runs_at_stations_px"]


def test_real_internal_white_gap_prevents_whole_line_replacement():
    gray, old = _source()
    gray[87:94, 170:177] = 255
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    assert not plan["decisions"][0]["proof"]["checks"][
        "no_missing_source_profile_inside_complete_endpoints"
    ]


def test_ordinary_t_before_real_straight_end_is_not_a_terminal_corner():
    gray, old = _source()
    gray[92:151, 330] = 255
    cv2.line(gray, (310, 90), (310, 150), 0, 1)
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    assert (
        plan["decisions"][0]["proof"]["reason"]
        == "FULL_ENDPOINT_RESPONSIBILITY_NOT_PROVED"
    )


def test_competing_return_sides_do_not_become_a_unique_terminal_by_nearest_choice():
    gray, old = _source()
    cv2.line(gray, (330, 35), (330, 90), 0, 1)
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    ends = plan["decisions"][0]["proof"]["endpoint_return_proofs"]
    assert len(ends[1]["candidate_returns"]) == 2


def test_no_receivers_means_no_reconciliation_not_whole_drawing_discovery():
    gray, old = _source()
    plan = _plan(gray, old, receiving_object_ids=[])
    assert plan["scope_mode"] == "DISCOVERED_RECEIVER_PAIRS"
    assert not plan["objects"] and not plan["retired_ids"] and not plan["decisions"]
    assert carriers.verify_existing_carrier_reconciliation(gray, ROI, plan)["pass"]
    assert len(_plan(gray, old)["objects"]) == 1


def test_unique_source_matched_existing_return_gets_exact_finite_native_intersection():
    gray, old = _source()
    return_line = _line("independent-return", [330.25, 90], [330.25, 150])
    plan = _plan(gray, old + [return_line], receiving_object_ids=[old[0]["id"]])
    assert len(plan["objects"]) == 1
    assert plan["objects"][0]["geometry"]["end"][0] == 330.25
    assert return_line["id"] not in plan["retired_ids"]
    binding = plan["decisions"][0]["proof"]["native_endpoint_return_bindings"][1]
    assert binding["reason"] == "UNIQUE_FINITE_SOURCE_MATCHED_NATIVE_RETURN"
    proof = binding["matched_existing_returns"][0]
    assert proof["object_binding"] == return_line
    assert proof["adjustment_cells_all_original_ink"]
    assert 0 <= proof["finite_return_projection_px"] <= proof["finite_return_length_px"]


def test_competing_existing_return_owners_are_not_resolved_by_nearest_distance():
    gray, old = _source()
    returns = [
        _line("return-a", [330.1, 90], [330.1, 150]),
        _line("return-b", [330.25, 90], [330.25, 150]),
    ]
    plan = _plan(gray, old + returns, receiving_object_ids=[old[0]["id"]])
    assert not plan["objects"] and not plan["retired_ids"]
    binding = plan["decisions"][0]["proof"]["native_endpoint_return_bindings"][1]
    assert not binding["pass"] and len(binding["matched_existing_returns"]) == 2


def test_existing_return_cannot_pull_source_endpoint_across_even_one_white_pixel():
    gray, old = _source()
    gray[89:92, 29:332] = 255
    cv2.line(gray, (30, 90), (330, 90), 0, 1)
    cv2.line(gray, (30, 90), (30, 150), 0, 1)
    cv2.line(gray, (330, 90), (330, 150), 0, 1)
    return_line = _line("offset-native-return", [331.1, 90], [331.1, 150])
    plan = _plan(gray, old + [return_line], receiving_object_ids=[old[0]["id"]])
    assert not plan["objects"] and not plan["retired_ids"]
    proof = plan["decisions"][0]["proof"]["native_endpoint_return_bindings"][1]
    assert not proof["pass"]
    rejected = proof["rejected_existing_returns"][0]
    assert not rejected["adjustment_cells_all_original_ink"]
    assert gray[90, 331] == 255


def test_source_return_separated_by_a_real_near_corner_gap_cannot_define_endpoint():
    gray, old = _source()
    gray[93:96, 330] = 255
    plan = _plan(gray, old)
    assert not plan["objects"] and not plan["retired_ids"]
    proof = plan["decisions"][0]["proof"]
    assert proof["reason"] == "FULL_ENDPOINT_RESPONSIBILITY_NOT_PROVED"


@pytest.mark.parametrize("mutation", ["source", "geometry", "prior", "policy", "scope"])
def test_cold_replay_checks_current_pixels_both_old_extents_and_adopted_geometry(
    mutation,
):
    gray, old = _source()
    plan = _plan(gray, old, receiving_object_ids=[old[0]["id"]])
    assert plan["objects"]
    if mutation == "source":
        gray[90, 100] = 255
    elif mutation == "geometry":
        plan["objects"][0]["geometry"]["end"][0] += 10
    elif mutation == "prior":
        plan["prior_object_bindings"][0]["geometry"]["end"][0] += 10
    elif mutation == "policy":
        plan["policy"]["maximum_endpoint_transition_px"] += 1
    else:
        plan["receiving_object_ids"] = []
    assert not carriers.verify_existing_carrier_reconciliation(gray, ROI, plan)["pass"]
