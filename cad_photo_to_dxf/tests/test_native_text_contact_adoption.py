"""Public synthetic contacts exercise adoption, actual saved geometry and edits."""

from copy import deepcopy
import hashlib
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects.cad_io import export_objects, mark, save_native_dxf
from app.native_objects.contracts import save_json
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.text_contact_audit import (
    cold_text_contact_bindings,
    _primitive_matches,
)
from app.native_objects.text_contact_geometry import plan_text_contact_geometry


def _scene(*, curve=False, parallel=False):
    gray = np.full((200, 300), 255, np.uint8)
    if curve:
        cv2.polylines(
            gray,
            [np.asarray([[20, 100], [85, 100], [135, 140], [280, 140]], np.int32)],
            False,
            0,
            1,
        )
        cv2.line(gray, (200, 120), (200, 140), 0, 1)
        seed = [175, 115, 225, 145]
    else:
        cv2.line(gray, (20, 100), (280, 100), 0, 1)
        cv2.line(gray, (140, 80), (140, 100), 0, 1)
        seed = [115, 75, 165, 105]
        if parallel:
            cv2.line(gray, (20, 102), (280, 102), 0, 1)
    return gray, [0, 0, 300, 200], seed


def _line(a, b, oid="old-line"):
    return {
        "id": oid,
        "kind": "LINE",
        "layer": "GEOMETRY",
        "geometry": {"start": list(a), "end": list(b)},
    }


def _adopt(tmp_path, gray, roi, seed, prior=()):
    original, existing = gray.copy(), deepcopy(prior)
    plan = plan_text_contact_geometry(gray, roi, seed)
    assert plan["paths"]
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    result = complete_text_contact_paths(
        gray, roi, source_sha, list(prior), [plan], tmp_path / "evidence/text_contact"
    )
    assert np.array_equal(gray, original)
    assert prior == existing
    return result


def _save(tmp_path, gray, roi, result, prior=()):
    path = tmp_path / "result.dxf"
    objects = [obj for obj in prior if obj["id"] not in result["retired_ids"]] + result[
        "objects"
    ]
    export_objects(objects, path, roi, 200, result["source_sha256"])
    report = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    return path, report


def _resave(path, doc):
    save_native_dxf(doc, path)
    metadata_path = path.with_suffix(".objects.json")
    metadata = json.loads(metadata_path.read_text())
    # Rebind the serialization receipt, so the negative test must inspect
    # actual entity geometry rather than stop at the file's changed checksum.
    metadata["dxf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    save_json(metadata_path, metadata)


@pytest.mark.parametrize("curve", [False, True])
def test_complete_original_geometry_is_saved_when_text_is_still_pending(
    tmp_path, curve
):
    gray, roi, seed = _scene(curve=curve)
    result = _adopt(tmp_path, gray, roi, seed)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    assert obj["kind"] == ("CONNECTION_PATH" if curve else "LINE")
    assert "source_graph_edge_ids" not in obj["source_evidence"]
    assert obj["source_evidence"]["text_contact_path"]["path"]["source_graph_edge_ids"]
    assert not result["retired_ids"]
    assert result["new_complete_text_labels"] == 0
    path, report = _save(tmp_path, gray, roi, result)
    assert report["pass"], report
    actual = [
        entity
        for entity in ezdxf.readfile(path).modelspace()
        if entity.dxf.layer != "REVIEW"
    ]
    assert len(actual) == 1
    assert actual[0].dxftype() == ("LWPOLYLINE" if curve else "LINE")
    assert any(
        row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE" and row["pass"]
        for row in report["checks"]
    )


def test_existing_complete_line_is_retained_and_not_counted_twice(tmp_path):
    gray, roi, seed = _scene()
    old = _line((20, 100), (280, 100))
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert not result["objects"] and not result["retired_ids"]
    assert result["decisions"][0]["existing_adequate_ids"] == [old["id"]]
    _, report = _save(tmp_path, gray, roi, result, [old])
    assert report["pass"], report


def test_whole_supported_old_fragment_is_retired_with_one_explicit_destination(
    tmp_path,
):
    gray, roi, seed = _scene()
    old = _line((30, 100), (70, 100))
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert result["retired_ids"] == [old["id"]]
    assert len(result["objects"]) == 1
    assert result["decisions"][0]["whole_line_certificates"][0]["pass"]
    _, report = _save(tmp_path, gray, roi, result, [old])
    assert report["pass"], report


def test_unproved_old_remainder_prevents_retirement_and_duplicate_output(tmp_path):
    gray, roi, seed = _scene(curve=True)
    old = _line((30, 100), (290, 100))
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert not result["objects"] and not result["retired_ids"]
    assert (
        "WHOLE_OLD_LINE_RESPONSIBILITY_NOT_CERTIFIED"
        in result["decisions"][0]["reasons"]
    )


def test_parallel_line_across_real_white_gap_is_not_an_adequate_old_owner(tmp_path):
    gray, roi, seed = _scene(parallel=True)
    old = _line((20, 102), (280, 102))
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert len(result["objects"]) == 1
    assert not result["retired_ids"]
    assert np.all(gray[101, 20:281] == 255)
    assert all(
        point[1] == 100
        for point in result["objects"][0]["source_evidence"]["source_path_points"]
    )
    _, report = _save(tmp_path, gray, roi, result, [old])
    assert report["pass"], report


def test_crossing_neighbor_remains_an_independent_saved_line(tmp_path):
    gray, roi, seed = _scene()
    old = _line((140, 80), (140, 100), "protected-crossing")
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert len(result["objects"]) == 1 and not result["retired_ids"]
    path, report = _save(tmp_path, gray, roi, result, [old])
    assert report["pass"], report
    doc = ezdxf.readfile(path)
    new = next(
        entity
        for entity in doc.modelspace()
        if json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"]
        == result["objects"][0]["id"]
    )
    doc.modelspace().delete_entity(new)
    remaining = [entity for entity in doc.modelspace() if entity.dxf.layer != "REVIEW"]
    assert len(remaining) == 1
    assert all(
        _primitive_matches(remaining[0], "LINE", old["geometry"], roi, 200).values()
    )


@pytest.mark.parametrize("curve", [False, True])
def test_cold_read_rejects_changed_actual_vertex_even_when_file_receipt_is_rebound(
    tmp_path, curve
):
    gray, roi, seed = _scene(curve=curve)
    result = _adopt(tmp_path, gray, roi, seed)
    path, report = _save(tmp_path, gray, roi, result)
    assert report["pass"], report
    doc = ezdxf.readfile(path)
    entity = next(iter(doc.modelspace()))
    if curve:
        points = list(entity.get_points("xyb"))
        points[1] = (points[1][0], points[1][1] + 0.01, points[1][2])
        entity.set_points(points, format="xyb")
    else:
        entity.dxf.start = (entity.dxf.start.x + 0.01, entity.dxf.start.y, 0)
    _resave(path, doc)
    changed = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    assert not changed["pass"]
    row = next(
        row
        for row in changed["checks"]
        if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE"
    )
    assert row["checks"]["original_source_plan_replayed"]
    assert not row["checks"]["actual_vertices" if curve else "actual_start"]


@pytest.mark.parametrize(
    "remove", ["flag", "entity", "evidence", "null_evidence", "manifest"]
)
def test_union_of_receipts_finds_missing_contact_records(tmp_path, remove):
    gray, roi, seed = _scene()
    result = _adopt(tmp_path, gray, roi, seed)
    path, report = _save(tmp_path, gray, roi, result)
    assert report["pass"], report
    doc = ezdxf.readfile(path)
    entity = next(iter(doc.modelspace()))
    if remove == "flag":
        identity = json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)
        del identity["text_contact_path"]
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps(identity))])
        _resave(path, doc)
    elif remove == "entity":
        doc.modelspace().delete_entity(entity)
        _resave(path, doc)
    elif remove == "manifest":
        (tmp_path / "evidence/text_contact/adoption.json").unlink()
    else:
        metadata_path = path.with_suffix(".objects.json")
        metadata = json.loads(metadata_path.read_text())
        if remove == "null_evidence":
            metadata["objects"][0]["source_evidence"] = None
        else:
            del metadata["objects"][0]["source_evidence"]["text_contact_path"]
        save_json(metadata_path, metadata)
    changed = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    assert not changed["pass"]
    assert result["objects"][0]["id"] in changed["target_ids"]


def test_an_extra_native_redrawing_is_not_hidden_by_a_valid_source_plan(tmp_path):
    gray, roi, seed = _scene()
    result = _adopt(tmp_path, gray, roi, seed)
    path, report = _save(tmp_path, gray, roi, result)
    assert report["pass"], report
    doc = ezdxf.readfile(path)
    copy = next(iter(doc.modelspace())).copy()
    doc.modelspace().add_entity(copy)
    mark(copy, _line((20, 100), (280, 100), "unauthorized-independent-duplicate"))
    _resave(path, doc)
    changed = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    assert not changed["pass"] and changed["duplicate_conflicts"]


def test_saved_neighbor_geometry_is_checked_independently_of_the_candidate(tmp_path):
    gray, roi, seed = _scene()
    old = _line((140, 80), (140, 100), "protected-crossing")
    result = _adopt(tmp_path, gray, roi, seed, [old])
    path, report = _save(tmp_path, gray, roi, result, [old])
    assert report["pass"], report
    doc = ezdxf.readfile(path)
    entity = next(
        e
        for e in doc.modelspace()
        if json.loads(e.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"] == old["id"]
    )
    entity.dxf.start = (entity.dxf.start.x, entity.dxf.start.y - 0.01, 0)
    _resave(path, doc)
    changed = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    protected = next(
        row
        for row in changed["checks"]
        if row["type"] == "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION"
    )
    assert not changed["pass"] and not protected["pass"]


def test_actual_saved_arc_parameters_are_checked_without_a_path_id_prefix(tmp_path):
    obj = {
        "id": "ordinary-restored-curve",
        "kind": "ARC",
        "layer": "CONNECTIONS",
        "geometry": {
            "center": [80, 80],
            "radius_px": 35,
            "start_deg_image": 10,
            "end_deg_image": 120,
            "sweep_deg_image": 110,
        },
    }
    path = tmp_path / "arc.dxf"
    export_objects([obj], path, [0, 0, 180, 180], 200, "synthetic")
    entity = next(iter(ezdxf.readfile(path).modelspace()))
    assert all(
        _primitive_matches(
            entity, obj["kind"], obj["geometry"], [0, 0, 180, 180], 200
        ).values()
    )
    entity.dxf.end_angle += 0.5
    assert not all(
        _primitive_matches(
            entity, obj["kind"], obj["geometry"], [0, 0, 180, 180], 200
        ).values()
    )


@pytest.mark.parametrize("exact_native_overlap", [False, True])
def test_bounded_original_four_port_contact_keeps_the_whole_old_line(
    tmp_path, exact_native_overlap
):
    gray = np.full((220, 300), 255, np.uint8)
    points = [
        [120, 30],
        [130, 85],
        [133, 95],
        [135, 100],
        [137, 100],
        [137, 103],
        [144, 116],
        [160, 190],
    ]
    cv2.polylines(gray, [np.asarray(points, np.int32)], False, 0, 1)
    cv2.line(gray, (20, 100), (280, 100), 0, 1)
    roi, seed = [0, 0, 300, 220], [115, 85, 155, 115]
    old = _line(
        (20, 100 if exact_native_overlap else 99.7),
        (280, 100 if exact_native_overlap else 100.2),
        "complete-crossing-line",
    )
    result = _adopt(tmp_path, gray, roi, seed, [old])
    assert not result["retired_ids"]
    decisions = [
        row for row in result["decisions"] if row.get("shared_existing_line_contacts")
    ]
    assert len(decisions) == 1
    proof = decisions[0]["shared_existing_line_contacts"][0]
    assert proof["pass"] and not proof["old_object_retirement_authorized"]
    assert not proof["native_duplicates_authorized"]
    if exact_native_overlap:
        assert not result["objects"]
        assert (
            "SHARED_SOURCE_CORE_DOES_NOT_AUTHORIZE_NATIVE_DUPLICATES"
            in decisions[0]["reasons"]
        )
    else:
        assert len(result["objects"]) == 1
        _, report = _save(tmp_path, gray, roi, result, [old])
        assert report["pass"], report
        checked = next(
            row
            for row in report["checks"]
            if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE"
        )
        assert checked["shared_neighbor_source_checks"] == [
            {"prior_object_id": old["id"], "pass": True}
        ]


def test_original_core_retrace_allowance_cannot_exempt_an_extra_object(tmp_path):
    gray = np.full((240, 420), 255, np.uint8)
    cv2.circle(gray, (60, 100), 13, 0, 2)
    cv2.circle(gray, (360, 100), 13, 0, 2)
    cv2.line(gray, (74, 100), (346, 100), 0, 1)
    gray[99:102, 199:206] = 0
    gray[100, 200] = gray[100, 203] = 255
    roi, seed = [0, 0, 420, 240], [175, 85, 230, 115]
    result = _adopt(tmp_path, gray, roi, seed)
    path, report = _save(tmp_path, gray, roi, result)
    assert report["pass"], report
    assert report["allowances"], (
        "fixture must exercise actual same-owner repeated native edges"
    )
    allowance = report["allowances"][0]
    doc = ezdxf.readfile(path)
    original = next(iter(doc.modelspace()))
    source_a, source_b = allowance["source_edge"]
    mm = 25.4 / 200
    points = [(p[0] * mm, (roi[3] - p[1]) * mm) for p in (source_a, source_b)]
    extra = doc.modelspace().add_line(*points, dxfattribs={"layer": "CONNECTIONS"})
    mark(extra, _line(source_a, source_b, "independent-core-copy"))
    _resave(path, doc)
    changed = cold_text_contact_bindings(
        path, ezdxf.readfile(path), gray, roi, 200, tmp_path / "evidence"
    )
    assert not changed["pass"] and changed["duplicate_conflicts"]
    assert all(item["handle"] == original.dxf.handle for item in changed["allowances"])
