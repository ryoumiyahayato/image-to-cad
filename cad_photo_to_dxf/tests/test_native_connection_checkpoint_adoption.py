"""Whole-object adoption on real extracted public-safe source strokes."""

from copy import deepcopy

import cv2
import numpy as np
from PIL import Image
import pytest

from app.native_objects.connection_checkpoint import adopt_checkpoint_paths
from app.native_objects.connections import extract_connections


ROI = (0, 0, 180, 180)


def _source(points):
    gray = np.full((180, 180), 255, dtype=np.uint8)
    cv2.polylines(gray, [np.asarray(points, np.int32)], False, 0, 1)
    return gray


def _curve():
    return _source([[20, 70], [65, 70], [95, 50], [125, 50], [160, 70]])


def _line(start, end, *, oid="old-line"):
    return {"id": oid, "kind": "LINE", "layer": "GEOMETRY",
            "geometry": {"start": list(start), "end": list(end)}}


def _extract(gray, directory, prior=(), *, require_simple=True):
    directory.mkdir()
    Image.fromarray(gray).save(directory / "synthetic_source.png")
    result = extract_connections(gray, ROI, list(prior), directory)
    assert len(result["objects"]) == 1, result["uncertainties"]
    obj = result["objects"][0]
    if require_simple:
        assert obj["source_evidence"]["whole_simple_source_chain"]["pass"]
        assert obj["source_evidence"]["whole_simple_source_chain_fit"]["pass"]
    assert obj["source_evidence"]["source_support"]["pass"]
    return result["objects"]


def _adopt_unchanged(gray, proposals, prior):
    pixels, original_proposals, original_prior = gray.copy(), deepcopy(proposals), deepcopy(prior)
    result = adopt_checkpoint_paths(gray, proposals, prior)
    assert np.array_equal(gray, pixels)
    assert proposals == original_proposals
    assert prior == original_prior
    assert not result["source_pixels_modified"]
    assert not result["partial_old_entity_retirement_permitted"]
    return result


@pytest.mark.parametrize("line_y", [70, 71, 72])
def test_existing_adequate_line_is_not_counted_as_a_new_path(tmp_path, line_y):
    gray = _source([[20, 70], [80, 72], [160, 70]])
    old = _line((20, line_y), (160, line_y))
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert result["decisions"][0]["existing_adequate_ids"] == [old["id"]]


@pytest.mark.parametrize("normal_offset", [0.0, 0.5, 1.0])
def test_complete_source_path_replaces_whole_incomplete_line(tmp_path, normal_offset):
    gray = _curve()
    old = _line((30, 70 + normal_offset), (60, 70 + normal_offset))
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert len(result["objects"]) == 1
    assert result["retired_ids"] == [old["id"]]
    assert result["decisions"][0]["decision"] == "REPLACE_WHOLE_INCOMPLETE_LINES"
    proof = result["decisions"][0]["whole_line_certificates"][0]
    assert proof["pass"]
    assert proof["old_line_remaining_intervals"] == []
    assert proof["checks"]["whole_old_LINE_on_same_original_ink_component"]


@pytest.mark.parametrize("same_id", [True, False])
def test_existing_complete_path_is_not_duplicated(tmp_path, same_id):
    gray = _curve()
    proposals = _extract(gray, tmp_path / "discovery")
    old = deepcopy(proposals[0])
    if not same_id:
        old["id"] = "other-preserved-path"
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    assert result["decisions"][0]["decision"] == "RETAIN_EXISTING_COMPLETE_PATH_NO_DUPLICATE"


def test_same_id_cannot_hide_changed_saved_geometry(tmp_path):
    gray = _curve()
    proposals = _extract(gray, tmp_path / "discovery")
    old = deepcopy(proposals[0])
    old["geometry"]["points"][-1][0] += 4
    original = deepcopy(old)
    with pytest.raises(ValueError, match="ID_GEOMETRY_COLLISION"):
        adopt_checkpoint_paths(gray, proposals, [old])
    assert old == original


def test_a_different_path_already_owning_source_edges_remains_pending(tmp_path):
    gray = _curve()
    proposals = _extract(gray, tmp_path / "discovery")
    old = deepcopy(proposals[0])
    old["id"] = "different-existing-owner"
    old["geometry"]["points"][-1][0] += 4
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    assert "ANOTHER_WHOLE_PATH_OWNS_OBSERVED_SOURCE_ADJACENCIES" in result["decisions"][0]["reasons"]


@pytest.mark.parametrize("end", [(175, 70), (220, 70)])
def test_unproved_old_line_remainder_is_not_deleted(tmp_path, end):
    gray = _curve()
    old = _line((30, 70), end)
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    assert result["uncertainties"]
    assert not result["decisions"][0]["whole_line_certificates"][0]["pass"]


def test_line_with_other_original_component_responsibility_stays_pending(tmp_path):
    gray = _curve()
    gray[73, 75:91] = 0
    old = _line((30, 71), (90, 71))
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    proof = result["decisions"][0]["whole_line_certificates"][0]
    assert not proof["checks"]["whole_old_LINE_on_same_original_ink_component"]


def test_parallel_neighbor_on_separate_ink_is_preserved_without_blocking_path(tmp_path):
    gray = _curve()
    gray[72, 30:61] = 0
    old = _line((30, 72), (60, 72))
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert len(result["objects"]) == 1
    assert not result["retired_ids"]
    assert not result["uncertainties"]
    assert np.all(gray[71, 30:61] == 255)


def test_crossing_line_is_not_confused_with_same_direction_replacement(tmp_path):
    gray = _curve()
    cv2.line(gray, (40, 59), (40, 81), 0, 1)
    old = _line((40, 59), (40, 81))
    proposals = _extract(gray, tmp_path / "discovery", [old], require_simple=False)
    result = _adopt_unchanged(gray, proposals, [old])
    assert len(result["objects"]) == 1
    assert not result["retired_ids"]
    assert not result["uncertainties"]


def test_a_wall_block_member_is_never_retired_separately(tmp_path):
    gray = _curve()
    old = {"id": "preserved-wall", "kind": "WALL_SEGMENT", "layer": "WALLS",
           "geometry": {"members": [_line((30, 70), (60, 70))]}}
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    assert "EXISTING_BLOCK_MEMBER_OR_NONLINE_RESPONSIBILITY_PENDING" in result["decisions"][0]["reasons"]


@pytest.mark.parametrize("in_door", [True, False])
def test_existing_native_arc_responsibility_is_not_duplicated(tmp_path, in_door):
    gray = np.full((180, 180), 255, dtype=np.uint8)
    cv2.ellipse(gray, (90, 90), (55, 55), 0, 0, 120, 0, 1)
    arc = {"kind": "ARC", "geometry": {
        "center": [90, 90], "radius_px": 55,
        "start_deg_image": 0, "sweep_deg_image": 120, "end_deg_image": 120,
    }}
    old = ({"id": "preserved-door", "kind": "DOOR", "layer": "DOORS",
            "geometry": {"native_members": [arc]}}
           if in_door else {"id": "preserved-arc", "layer": "GEOMETRY", **arc})
    proposals = _extract(gray, tmp_path / "discovery", [old])
    result = _adopt_unchanged(gray, proposals, [old])
    assert not result["objects"]
    assert not result["retired_ids"]
    assert "EXISTING_NATIVE_ARC_RESPONSIBILITY_PENDING" in result["decisions"][0]["reasons"]
