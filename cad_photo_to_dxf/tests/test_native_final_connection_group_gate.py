"""Final editable groups require distinct actual members and no coincident spans."""

from copy import deepcopy

import numpy as np
import pytest

from app.native_objects import (
    completion_stages, connection_adoption, connection_checkpoint, connections,
)
from app.native_objects.completion_stages import (
    _finalize_complete_connection_groups,
    _quarantine_native_duplicate_groups,
    canonical_sha,
)


def path(identity, points, *, group="group-a", edge=1):
    return {
        "id": identity, "kind": "CONNECTION_PATH", "layer": "CONNECTIONS",
        "geometry": {"points": points, "bulges": [0.0] * len(points), "closed": False},
        "source_evidence": {
            "source_path_points": deepcopy(points), "source_graph_edge_ids": [edge],
            "source_connected_group_id": group, "original_source_crop_xyxy_px": [0, 0, 200, 200],
            "original_source_crop_array_sha256": "a" * 64, "retirement_proposals": [],
        },
    }


def complete_group(prefix, y=20):
    members = [path(f"{prefix}-{i}", [[10, y + i * 10], [30, y + i * 10]],
                    group=prefix, edge=i + 1) for i in range(3)]
    certificate = {"kind": "complete_observed_graphic_group",
                   "complete_routes": [{"source_graph_edge_ids": [i + 1]} for i in range(3)],
                   "fixture_source_component": prefix}
    certificate["certificate_sha256"] = canonical_sha(certificate)
    responsibility = [{"path_id": obj["id"], "source_graph_edge_ids": [i + 1], "endpoint_evidence": []}
                      for i, obj in enumerate(members)]
    for obj in members:
        obj["source_evidence"]["text_graphic_support"] = {"complete_graphic_group": deepcopy(certificate)}
        obj["source_evidence"]["graphic_group_path_responsibility"] = deepcopy(responsibility)
    return members


def decision(obj, *, adopted=True, adequate=(), retired=()):
    return {"id": obj["id"], "adopted": adopted, "decision": "ADD_COMPLETE_PATH" if adopted else "PENDING",
            "existing_adequate_ids": list(adequate), "retired_ids": list(retired),
            "reasons": [] if adopted else ["PER_PATH_RESPONSIBILITY_FAILED"]}


@pytest.mark.parametrize("overlap_points", [
    [[5, 10], [5, 20], [12, 20], [12, 30]],
    [[5, 10], [5, 20], [8, 20], [12, 20], [12, 30]],
    [[12, 30], [12, 20], [8, 20], [5, 20], [5, 10]],
])
def test_partial_resegmented_finite_overlap_quarantines_whole_group_only(overlap_points):
    bad = [path("main", [[0, 20], [20, 20], [20, 40]]), path("bar", overlap_points, edge=2),
           path("peer", [[30, 10], [30, 30]], edge=3)]
    independent = complete_group("independent", y=80)
    before = deepcopy(bad + independent)
    result = _quarantine_native_duplicate_groups(bad + independent)
    assert result["quarantined_ids"] == ["bar", "main", "peer"]
    conflicts = result["native_duplicate_conflicts"]
    assert sum(row["positive_overlap_length_source_px"] for row in conflicts) == pytest.approx(7)
    assert all(row["finite_segment_intersection"] for row in conflicts)
    assert bad + independent == before


def test_point_crossings_endpoint_touches_white_gaps_and_parallel_strokes_are_not_overlap():
    proposals = [path("horizontal", [[0, 20], [10, 20]]),
                 path("vertical", [[5, 10], [5, 30]], edge=2),
                 path("touch", [[10, 20], [15, 25]], edge=3),
                 path("white-gap", [[11, 20], [20, 20]], edge=4),
                 path("parallel", [[0, 21], [10, 21]], edge=5)]
    result = _quarantine_native_duplicate_groups(proposals)
    assert result["quarantined_ids"] == result["native_duplicate_conflicts"] == []


def test_partial_overlap_with_existing_path_holds_new_group_without_changing_old():
    old = path("retained-path", [[0, 20], [20, 20], [20, 40]], group="old")
    proposals = [path("new-bar", [[5, 10], [5, 20], [12, 20], [12, 30]]),
                 path("new-peer", [[30, 10], [30, 30]], edge=2),
                 path("unrelated", [[50, 60], [70, 80]], group="other")]
    before = deepcopy([old, proposals])
    result = _quarantine_native_duplicate_groups(proposals, [old])
    assert result["quarantined_ids"] == ["new-bar", "new-peer"]
    assert [old, proposals] == before and result["existing_entities_modified"] == 0


def test_late_member_refusal_withdraws_group_and_retirements_but_preserves_an_independent_group():
    first, second = complete_group("first"), complete_group("second", 80)
    old = {"id": "old-line", "kind": "LINE", "geometry": {"start": [10, 20], "end": [20, 20]}}
    rows = [decision(first[0], retired=[old["id"]]), decision(first[1], adopted=False), decision(first[2]),
            *[decision(obj) for obj in second]]
    adopted = [first[0], first[2], *second]
    before = deepcopy([first, second, old, rows, adopted])
    result = _finalize_complete_connection_groups(first + second, [old], adopted, rows, [old["id"]])
    assert [obj["id"] for obj in result["objects"]] == [obj["id"] for obj in second]
    assert not result["retired_ids"] and result["rolled_back_retired_ids"] == [old["id"]]
    assert result["quarantined_ids"] == [obj["id"] for obj in first]
    assert [row["pass"] for row in result["groups"]] == [False, True]
    assert all(not row["adopted"] and not row["retired_ids"] for row in result["decisions"][:3])
    assert [first, second, old, rows, adopted] == before


def test_a_distinct_retained_adequate_old_object_can_represent_a_complete_group_member():
    members = complete_group("group")
    old = deepcopy(members[1])
    old["id"] = "existing-adequate-path"
    rows = [decision(members[0]), decision(members[1], adopted=False, adequate=[old["id"]]),
            decision(members[2])]
    result = _finalize_complete_connection_groups(members, [old], [members[0], members[2]], rows)
    assert len(result["objects"]) == 2 and not result["quarantined_ids"]
    proof = result["groups"][0]
    assert proof["pass"] and proof["actual_member_representatives"] == {
        members[0]["id"]: members[0]["id"], members[1]["id"]: old["id"], members[2]["id"]: members[2]["id"],
    }
    assert all(obj["source_evidence"]["final_graphic_group_responsibility"] == [proof] for obj in result["objects"])


def test_one_old_entity_cannot_claim_two_distinct_complete_group_routes():
    members = complete_group("group")
    old = deepcopy(members[0])
    old["id"] = "one-old-path"
    rows = [decision(members[0]), *[decision(obj, adopted=False, adequate=[old["id"]]) for obj in members[1:]]]
    result = _finalize_complete_connection_groups(members, [old], [members[0]], rows)
    assert result["objects"] == [] and len(result["quarantined_ids"]) == 3
    assert not result["groups"][0]["pass"]


@pytest.mark.parametrize("damage", ["own-route", "unbound-id", "alias-geometry", "alias-source"])
def test_inconsistent_route_identity_or_unbound_alias_cannot_claim_a_complete_group(damage):
    members = complete_group("group")
    if damage == "own-route":
        members[0]["source_evidence"]["source_graph_edge_ids"] = [2]
    elif damage == "unbound-id":
        members[0]["id"] = "unbound-id"
    else:
        alias = deepcopy(members[0])
        alias["id"] = "alias"
        if damage == "alias-geometry":
            alias["geometry"]["points"][0][0] += 1
        else:
            alias["source_evidence"]["source_path_points"][0][0] += 1
        members.append(alias)
    result = _finalize_complete_connection_groups(members, [], members, [decision(obj) for obj in members])
    assert result["objects"] == [] and not result["groups"][0]["pass"]
    assert result["groups"][0]["reason"] == "COMPLETE_GROUP_DECLARATION_INCONSISTENT"


@pytest.mark.parametrize("entry", ["ordinary", "checkpoint"])
def test_both_entries_reconcile_late_refusal_and_keep_old_entities(tmp_path, monkeypatch, entry):
    first, second = complete_group("first"), complete_group("second", 80)
    old = {"id": "old-line", "kind": "LINE", "layer": "GEOMETRY",
           "geometry": {"start": [10, 20], "end": [20, 20]}, "source_evidence": {}}
    proposals = first + second
    source = np.full((200, 200), 255, np.uint8)
    before = deepcopy([proposals, old])
    monkeypatch.setattr(connection_adoption, "_existing_arc_overlap",
                        lambda obj, _: [{"existing_id": "late-arc-conflict"}] if obj["id"] == first[1]["id"] else [])
    monkeypatch.setattr(connection_adoption, "_whole_line_responsibility",
                        lambda *args: {"pass": True, "old_line_coverage": {
                            "already_complete_within_existing_line_tolerances": False}})
    if entry == "ordinary":
        monkeypatch.setattr(connections, "extract_connections",
                            lambda *args, **kwargs: {"objects": proposals, "uncertainties": []})
        result = completion_stages.complete_connections_without_unresolved_retirement(
            source, [0, 0, 200, 200], "s" * 64, [old], tmp_path / "ordinary")
        assert result["all_existing_native_entities_retained"]
    else:
        result = connection_checkpoint.adopt_checkpoint_paths(source, proposals, [old])
    assert not result["retired_ids"]
    assert result["final_complete_group_gate"]["rolled_back_retired_ids"] == [old["id"]]
    assert [obj["id"] for obj in result["objects"]] == [obj["id"] for obj in second]
    assert [row["pass"] for row in result["final_complete_group_gate"]["groups"]] == [False, True]
    assert [proposals, old] == before
