"""Ordinary conversion retains the bounded route's proven whole-line repair."""

from copy import deepcopy
import hashlib

import ezdxf
import numpy as np
import pytest

from app.native_objects.cad_io import cold_audit, export_objects
from app.native_objects.completion_stages import complete_connections_without_unresolved_retirement
from tests.test_native_connection_checkpoint_adoption import ROI, _curve, _line, _source


def _complete(gray, old, out):
    pixels, prior = gray.copy(), deepcopy(old)
    result = complete_connections_without_unresolved_retirement(
        gray, ROI, hashlib.sha256(gray.tobytes()).hexdigest(), old, out,
    )
    assert np.array_equal(gray, pixels) and old == prior
    assert result["source_pixels_modified"] is False
    assert result["partial_old_entity_retirement_permitted"] is False
    return result


@pytest.mark.parametrize("offset", [0.0, 1.0])
def test_ordinary_route_replaces_incomplete_line_and_preserves_independent_neighbor(tmp_path, offset):
    gray = _curve()
    gray[140, 20:161] = 0
    old = _line((30, 70 + offset), (60, 70 + offset))
    neighbor = _line((20, 140), (160, 140), oid="independent-neighbor")
    result = _complete(gray, [old, neighbor], tmp_path / "connections")
    assert len(result["objects"]) == 1
    assert result["retired_ids"] == [old["id"]]
    assert result["retained_existing_ids"] == [neighbor["id"]]
    assert result["all_existing_native_entities_retained"] is False
    row = result["decisions"][0]
    assert row["decision"] == "REPLACE_WHOLE_INCOMPLETE_LINES"
    assert row["whole_line_certificates"][0]["pass"]
    assert row["existing_entities_modified"] == 1


def test_ordinary_route_preserves_already_adequate_whole_line(tmp_path):
    gray = _source([[20, 70], [80, 72], [160, 70]])
    old = _line((20, 71), (160, 71))
    result = _complete(gray, [old], tmp_path / "connections")
    assert result["objects"] == [] and result["retired_ids"] == []
    assert result["retained_existing_ids"] == [old["id"]]
    assert result["all_existing_native_entities_retained"]
    assert result["decisions"][0]["existing_adequate_ids"] == [old["id"]]


@pytest.mark.parametrize("ownership", ["outside-remainder", "wall-member"])
def test_ordinary_route_cannot_delete_unproved_remainder_or_block_member(tmp_path, ownership):
    gray = _curve()
    old = (_line((30, 70), (175, 70)) if ownership == "outside-remainder" else {
        "id": "independent-wall", "kind": "WALL_SEGMENT", "layer": "WALLS",
        "geometry": {"members": [_line((30, 70), (60, 70))]},
    })
    result = _complete(gray, [old], tmp_path / "connections")
    assert result["objects"] == [] and result["retired_ids"] == []
    assert result["all_existing_native_entities_retained"]
    assert result["uncertainties"]


def test_ordinary_replacement_saved_dxf_contains_one_whole_path_and_no_old_fragment(tmp_path):
    gray = _curve()
    gray[140, 20:161] = 0
    old = _line((30, 70), (60, 70))
    neighbor = _line((20, 140), (160, 140), oid="independent-neighbor")
    prior = [old, neighbor]
    result = _complete(gray, prior, tmp_path / "connections")
    retained = [obj for obj in prior if obj["id"] not in result["retired_ids"]]
    final = retained + result["objects"]
    dxf = tmp_path / "ordinary-replacement.dxf"
    export_objects(final, dxf, ROI, 200, hashlib.sha256(gray.tobytes()).hexdigest())
    saved = ezdxf.readfile(dxf)
    formal = [entity for entity in saved.modelspace() if entity.dxf.layer != "REVIEW"]
    assert [entity.dxftype() for entity in formal] == ["LINE", "LWPOLYLINE"]
    assert saved.layers.get("REVIEW").is_frozen()
    audit = cold_audit(dxf, gray, ROI, 200, tmp_path / "cold_audit.json")
    assert audit["source_gate_pass"]
    assert not audit["exact_duplicate_segments"]
    assert not audit["ezdxf_errors"] and not audit["ezdxf_in_memory_fixes"]
