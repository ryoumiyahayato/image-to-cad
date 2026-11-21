"""Finite junction ownership, independent strokes and candidate-group choice."""

from copy import deepcopy

import numpy as np
import pytest

from app.native_objects.wall_group_representatives import (
    refine_selected_wall_representatives,
)
from app.native_objects.wall_junction_ownership import resolve_junction_boundaries
from app.native_objects.wall_partition_gate import _check, enforce_partition_source_gate
from app.native_objects.wall_segments import (
    _deferred_edge_replacements,
    _partition_wall_lines,
    assemble_walls,
)


def line(identifier, start, end, layer="GEOMETRY"):
    return {
        "id": identifier,
        "kind": "LINE",
        "layer": layer,
        "geometry": {"start": list(start), "end": list(end)},
        "source_evidence": {"source_width_px": 1.0},
    }


def wall(identifier, first, second, cap=False):
    members = [
        {"kind": "LINE", "role": "wall_edge", "geometry": deepcopy(o["geometry"])}
        for o in (first, second)
    ]
    if cap:
        members.append(
            {
                "kind": "LINE",
                "role": "observed_end_cap",
                "geometry": {
                    "start": first["geometry"]["end"],
                    "end": second["geometry"]["end"],
                },
            }
        )
    return {
        "id": identifier,
        "kind": "WALL_SEGMENT",
        "layer": "WALL_SEGMENTS",
        "geometry": {"members": members},
        "source_evidence": {
            "source_line_ids": [first["id"], second["id"]],
            "observed_caps": [False, cap],
            "whole_wall_feasibility": {"member_checks": []},
        },
    }


def junction_fixture(neighbor_x=199.5, neighbor_start=20):
    gray = np.full((260, 350), 255, np.uint8)
    gray[100, 20:201] = 0
    gray[120, 20:201] = 0
    gray[100:121, 200] = 0
    gray[20:231, round(neighbor_x)] = 0
    gray[20:231, 230] = 0
    target = wall(
        "target",
        line("lower", (20, 120), (200, 120)),
        line("upper", (20, 100), (200, 100)),
        True,
    )
    neighbor = wall(
        "neighbor",
        line("through", (neighbor_x, neighbor_start), (neighbor_x, 230)),
        line("other", (230, 20), (230, 230)),
    )
    return gray, [target, neighbor]


def test_cap_becomes_explicit_neighbor_boundary_without_changing_neighbor():
    gray, walls = junction_fixture()
    before = deepcopy(walls)
    pixels = gray.copy()
    resolved, boundaries, _ = resolve_junction_boundaries(gray, walls, _check)
    assert resolved[0]["id"] == before[0]["id"]
    assert len(resolved[0]["geometry"]["members"]) == 2
    assert resolved[1]["geometry"] == before[1]["geometry"]
    assert walls == before
    assert boundaries[0]["original_member"] == before[0]["geometry"]["members"][2]
    assert boundaries[0]["represented_by_wall_ids"] == ["neighbor"]
    proof = boundaries[0]["representative_evidence"][0]["source_responsibility"]
    assert proof["common_source_witness_count"] == proof["sample_count"]
    assert len(proof["source_witness_samples"]) == proof["sample_count"]
    assert all(
        row["literal_source_gray"] == 0 for row in proof["source_witness_samples"]
    )
    assert (
        len(resolved[0]["source_evidence"]["whole_wall_feasibility"]["member_checks"])
        == 2
    )
    assert np.array_equal(gray, pixels)


def test_true_end_cap_without_a_through_neighbor_stays_owned():
    gray, walls = junction_fixture()
    resolved, boundaries, _ = resolve_junction_boundaries(gray, walls[:1], _check)
    assert resolved == walls[:1]
    assert not boundaries


@pytest.mark.parametrize("start", [100, 120])
def test_one_sided_or_partial_neighbor_does_not_take_a_cap(start):
    gray, walls = junction_fixture(neighbor_start=start)
    resolved, boundaries, _ = resolve_junction_boundaries(gray, walls, _check)
    assert resolved[0] == walls[0]
    assert not boundaries


def test_nearby_parallel_stroke_with_original_white_gap_is_not_a_cap_owner():
    gray, walls = junction_fixture(neighbor_x=203)
    before = gray.copy()
    resolved, boundaries, candidates = resolve_junction_boundaries(gray, walls, _check)
    assert resolved[0] == walls[0]
    assert not boundaries
    assert any(
        row.get("source_responsibility", {}).get(
            "actual_white_separator_sample_count", 0
        )
        > 0
        for row in candidates
    )
    assert np.array_equal(gray, before)


def test_geometric_extension_without_actual_source_does_not_take_a_cap():
    gray, walls = junction_fixture()
    gray[20:100, 198:202] = 255
    gray[121:231, 198:202] = 255
    resolved, boundaries, candidates = resolve_junction_boundaries(gray, walls, _check)
    assert resolved[0] == walls[0]
    assert not boundaries
    assert any(
        not all(check["pass"] for check in row.get("local_extension_source_checks", []))
        for row in candidates
        if "local_extension_source_checks" in row
    )


def group_fixture():
    gray = np.full((180, 340), 255, np.uint8)
    gray[40, 30:281] = 0
    gray[44, 30:281] = 0
    gray[70, 30:281] = 0
    gray[0:141, 280] = 0
    gray[0:141, 310] = 0
    lower = line("lower", (30, 70), (280, 70))
    representative = line("main-upper", (30, 44), (280, 44))
    alternate = line("alternate", (30, 42), (280, 42))
    independent = line("independent-upper", (30, 40), (280, 40))
    left = line("through", (279.5, 0), (279.5, 140))
    right = line("through-other", (310, 0), (310, 140))
    walls = [wall("target", lower, alternate, True), wall("neighbor", left, right)]
    sources = [lower, representative, independent, left, right]
    groups = [
        {
            "representative_id": representative["id"],
            "candidate_ids": [representative["id"], alternate["id"]],
        }
    ]
    return gray, walls, sources, sources + [alternate], groups


def test_existing_group_choice_is_order_independent_and_preserves_white_gap():
    gray, walls, sources, admitted, groups = group_fixture()
    before = gray.copy()
    _, boundary, _ = resolve_junction_boundaries(gray, walls, _check)
    eligible = {row["wall_id"] for row in boundary}
    first, audit = refine_selected_wall_representatives(
        gray, walls, sources, admitted, groups, _check, _partition_wall_lines, eligible
    )
    second, _ = refine_selected_wall_representatives(
        gray,
        walls,
        list(reversed(sources)),
        list(reversed(admitted)),
        [{**groups[0], "candidate_ids": list(reversed(groups[0]["candidate_ids"]))}],
        _check,
        _partition_wall_lines,
        eligible,
    )
    assert audit and audit[0]["selected"]
    assert first[0]["geometry"] == second[0]["geometry"]
    assert first[0]["geometry"]["members"][1]["geometry"] == sources[1]["geometry"]
    assert first[0]["geometry"]["members"][0] == walls[0]["geometry"]["members"][0]
    assert first[1]["geometry"] == walls[1]["geometry"]
    kept, *_ = _partition_wall_lines(gray, sources, first)
    assert next(o for o in kept if o["id"] == "independent-upper") == sources[2]
    assert np.array_equal(gray, before)


def test_group_choice_cannot_reach_an_independent_group_or_unproven_scope():
    gray, walls, sources, admitted, groups = group_fixture()
    unchanged, audit = refine_selected_wall_representatives(
        gray, walls, sources, admitted, groups, _check, _partition_wall_lines, set()
    )
    assert unchanged == walls
    assert not audit
    only_alternate = [
        {"representative_id": "alternate", "candidate_ids": ["alternate"]}
    ]
    unchanged, audit = refine_selected_wall_representatives(
        gray,
        walls,
        sources,
        admitted,
        only_alternate,
        _check,
        _partition_wall_lines,
        {"target"},
    )
    assert unchanged == walls
    assert not audit


def test_wide_partial_with_bad_actual_tail_stays_pending_after_group_choice(tmp_path):
    gray = np.full((110, 700), 255, np.uint8)
    gray[50, 20:500] = 0
    gray[51, 500:616] = 0
    gray[53, 616:621] = 0
    gray[75, 500:621] = 0
    gray[51:76, 500] = 0
    gray[53:76, 620] = 0
    original = line("long-neighbor", (20, 50), (620, 50))
    sources = [
        original,
        line("lower", (500, 53), (620, 53)),
        line("upper", (500, 75), (620, 75)),
    ]
    result = assemble_walls(gray, [0, 0, 700, 110], sources, tmp_path)
    assert len(result["objects"]) == 1
    result["objects"][0]["source_evidence"][
        "candidate_group_representative_selection"
    ] = [{"source_thresholds_changed": False}]
    cache = {}
    kept, *_ = _partition_wall_lines(gray, sources, result["objects"], cache)
    assert next(o for o in kept if o["id"] == original["id"]) == original
    rejected = [
        proof for proof in cache.values() if proof.get("pending_partition_rejection")
    ]
    assert rejected
    assert any(
        not check["pass"]
        for proof in rejected
        for check in proof["candidate_remainder_checks"]
    )


def dependency_fixture():
    gray = np.full((240, 350), 255, np.uint8)
    gray[100:102, 30:281] = 0
    gray[120, 30:281] = 0
    gray[20:221, 279:281] = 0
    gray[20:221, 310] = 0
    lower = line("lower", (30, 120), (280.5, 120))
    old_upper = line("old-upper", (30, 101.6), (281.9, 101.6))
    upper = line("chosen-upper", (30, 100), (280.5, 100))
    a0, a1 = line("a0", (277.6, 20), (277.6, 220)), line("a1", (310, 20), (310, 220))
    b0, b1 = line("b0", (279.5, 20), (279.5, 220)), line("b1", (310, 20), (310, 220))
    walls = [wall("target", lower, upper, True), wall("a", a0, a1), wall("b", b0, b1)]
    sources = [lower, old_upper, a0, a1, b0, b1]
    walls, boundaries, candidates = resolve_junction_boundaries(gray, walls, _check)
    assert len(boundaries) == 1
    cache = {}
    kept, partitions, withdrawals, cap_dup, cap_partition, cap_nearby = (
        _partition_wall_lines(gray, sources, walls, cache)
    )
    result = {
        "objects": walls,
        "remaining_lines": kept,
        "source_interval_partition": partitions,
        "supported_edge_replacements": withdrawals,
        "deferred_edge_replacements": _deferred_edge_replacements(cache, walls),
        "junction_boundary_responsibilities": boundaries,
        "junction_boundary_candidates": candidates,
        "duplicate_cap_lines_consumed": cap_dup,
        "cap_interval_partition": cap_partition,
        "near_cap_lines_retained": cap_nearby,
        "rejected_pairs": [],
        "corners": [],
        "openings": [],
        "counts": {},
    }
    upper_partition = next(
        row for row in partitions if row["source_line_id"] == "old-upper"
    )
    assert any(
        claim.get("junction_dependency_intervals")
        for claim in upper_partition["wall_claims"]
    )
    return gray, sources, result


def test_finite_outside_overlap_tail_records_only_the_source_supported_owner():
    gray, sources, result = dependency_fixture()
    partition = next(
        p
        for p in result["source_interval_partition"]
        if p["source_line_id"] == "old-upper"
    )
    claim = partition["wall_claims"][0]
    dependencies = claim["junction_dependency_intervals"]
    assert dependencies[0]["outside_primary_overlap"]
    assert dependencies[0]["represented_by_wall_ids"] == ["b"]
    assert not partition["remaining_intervals_px"]
    assert claim["virtual_cap_used_as_owned_support"] is False
    assert (
        next(
            c
            for c in claim["junction_dependency_candidate_checks"]
            if c["neighbor_wall_id"] == "a"
        )["accepted_as_interval_representative"]
        is False
    )
    assert gray[101, 282] == 255


def test_losing_only_the_tail_owner_restores_that_tail_and_new_pending(tmp_path):
    gray, sources, result = dependency_fixture()
    next(w for w in result["objects"] if w["id"] == "b")["geometry"]["members"][1][
        "geometry"
    ] = {"start": [330, 20], "end": [330, 220]}
    checked = enforce_partition_source_gate(gray, sources, result, tmp_path)
    assert "target" in {w["id"] for w in checked["objects"]}
    assert "a" in {w["id"] for w in checked["objects"]}
    assert "b" not in {w["id"] for w in checked["objects"]}
    assert any(
        o["source_evidence"].get("parent_line_id") == "old-upper"
        for o in checked["remaining_lines"]
    )
    pending = [
        row
        for row in checked["deferred_edge_replacements"]
        if row["source_line_id"] == "old-upper"
    ]
    assert pending[0]["source_responsibility"]["pending_junction_dependency_intervals"]
    assert any(
        row["reason"] == "WALL_JUNCTION_ENDPOINT_RESPONSIBILITY_PENDING"
        for row in checked["uncertainties"]
    )


def test_losing_all_boundary_owners_revokes_the_dependent_wall(tmp_path):
    gray, sources, result = dependency_fixture()
    for w in result["objects"]:
        if w["id"] in {"a", "b"}:
            w["geometry"]["members"][1]["geometry"] = {
                "start": [330, 20],
                "end": [330, 220],
            }
    checked = enforce_partition_source_gate(gray, sources, result, tmp_path)
    assert not checked["objects"]
    assert "target" in checked["partition_source_gate"]["revoked_wall_ids"]
    assert checked["partition_source_gate"]["unavailable_junction_dependencies"]
    assert (
        next(o for o in checked["remaining_lines"] if o["id"] == "old-upper")
        == sources[1]
    )


def test_new_bad_remainder_after_owner_withdrawal_is_checked_and_restored(tmp_path):
    gray, sources, result = dependency_fixture()
    next(w for w in result["objects"] if w["id"] == "b")["geometry"]["members"][1][
        "geometry"
    ] = {"start": [330, 20], "end": [330, 220]}
    # The long original still passes the original 98% gate, while its newly
    # exposed short tail would not. It must not inherit a stale gate PASS.
    gray[101:103, 280] = 255
    checked = enforce_partition_source_gate(gray, sources, result, tmp_path)
    assert {w["id"] for w in checked["objects"]} == {"a"}
    evidence = checked["partition_source_gate"]
    assert evidence["pass"]
    assert {"target", "b"} <= set(evidence["revoked_wall_ids"])
    assert any(
        not check["pass"]
        for previous in evidence["prior_revocation_passes"]
        for check in previous["recomputed_actual_fragment_checks"]
    )
    assert all(_check(gray, o["geometry"])["pass"] for o in checked["remaining_lines"])
    assert (
        next(o for o in checked["remaining_lines"] if o["id"] == "old-upper")
        == sources[1]
    )


def test_two_revocation_passes_do_not_reactivate_an_old_boundary_owner(tmp_path):
    gray, sources, result = dependency_fixture()
    gray[160, 40:281] = 0
    gray[180, 40:281] = 0
    lower = line("survivor-lower", (40, 180), (280.5, 180))
    upper = line("survivor-upper", (40, 160), (280.5, 160))
    sources += [lower, upper]
    walls, boundaries, candidates = resolve_junction_boundaries(
        gray, result["objects"] + [wall("survivor", lower, upper, True)], _check
    )
    cache = {}
    kept, partitions, withdrawals, cap_dup, cap_partition, cap_nearby = (
        _partition_wall_lines(gray, sources, walls, cache)
    )
    result.update(
        objects=walls,
        remaining_lines=kept,
        source_interval_partition=partitions,
        supported_edge_replacements=withdrawals,
        deferred_edge_replacements=_deferred_edge_replacements(cache, walls),
        duplicate_cap_lines_consumed=cap_dup,
        cap_interval_partition=cap_partition,
        near_cap_lines_retained=cap_nearby,
        junction_boundary_responsibilities=result["junction_boundary_responsibilities"]
        + boundaries,
        junction_boundary_candidates=result["junction_boundary_candidates"]
        + candidates,
    )
    next(w for w in walls if w["id"] == "b")["geometry"]["members"][1]["geometry"] = {
        "start": [330, 20],
        "end": [330, 220],
    }
    gray[101:103, 280] = 255
    checked = enforce_partition_source_gate(gray, sources, result, tmp_path)
    active = {w["id"] for w in checked["objects"]}
    assert active == {"a", "survivor"}
    assert checked["partition_source_gate"]["prior_revocation_passes"]
    assert checked["partition_source_gate"]["pass"]
    for boundary in checked["junction_boundary_responsibilities"]:
        assert boundary["represented_by_wall_ids"] == ["a"]
        assert boundary["revoked_representative_wall_ids"] == ["b"]
        assert set(boundary["represented_by_wall_ids"]) <= active
    survivor = next(w for w in checked["objects"] if w["id"] == "survivor")
    assert survivor["source_evidence"]["junction_boundary_responsibilities"][0][
        "represented_by_wall_ids"
    ] == ["a"]


def test_joint_interval_keeps_primary_white_veto_and_uses_real_neighbor_members():
    gray = np.full((190, 220), 255, np.uint8)
    gray[100:102, 20:163] = 0
    gray[80, 40:163] = 0
    gray[20:171, 160:162] = 0
    gray[20:171, 190] = 0
    gray[101, 160] = 255
    target = wall(
        "target",
        line("chosen-lower", (40, 102.1), (162.5, 102.1)),
        line("chosen-upper", (40, 80), (162.5, 80)),
        True,
    )
    neighbor = wall(
        "neighbor",
        line("through", (160, 20), (160, 170)),
        line("other", (190, 20), (190, 170)),
    )
    walls, boundaries, _ = resolve_junction_boundaries(gray, [target, neighbor], _check)
    assert boundaries
    old = line("old-lower", (20, 100), (162.5, 100))
    _, partitions, *_ = _partition_wall_lines(gray, [old], walls)
    claim = partitions[0]["wall_claims"][0]
    assert claim["primary_only_support"]["actual_white_separator_sample_count"] > 0
    assert any(
        row["white_separator_veto"] and row["nearest_support_midpoint_gray"] == 255
        for row in claim["primary_only_support"]["source_witness_samples"]
    )
    assert claim["junction_dependency_intervals"]
    assert claim["actual_white_separator_veto_removed"] is False
    assert claim["virtual_cap_used_as_owned_support"] is False
    assert gray[101, 160] == 255
