"""Failure-oriented checks for actual persisted geometry and edit isolation."""
import json

import ezdxf
from ezdxf.xclip import XClip

from app.native_objects.independent_saved_geometry_audit import (
    APPID,
    audit_edit_copy,
    audit_saved_target_bindings,
    compare_saved_dxf,
    entity_identity,
    make_edit_copy,
    saved_source_geometries,
    sha256,
)


def _identity(entity, oid, kind=None):
    entity.set_xdata(APPID, [(1000, json.dumps({"id": oid, "kind": kind or entity.dxftype()}))])


def _fixture(tmp_path):
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    doc.layers.new("NATIVE")
    doc.layers.new("REVIEW")
    doc.styles.new("test-font", dxfattribs={"font": "example.ttf"})
    _identity(doc.modelspace().add_line((1, 1), (10, 1), dxfattribs={"layer": "NATIVE"}), "old")
    block = doc.blocks.new("test-block")
    block.add_line((0, 0), (3, 0))
    _identity(doc.modelspace().add_blockref("test-block", (20, 20)), "old-block")
    doc.modelspace().add_line((50, 50), (60, 50), dxfattribs={"layer": "REVIEW"})
    baseline = tmp_path / "baseline.dxf"
    doc.saveas(baseline)
    current = ezdxf.readfile(baseline)
    _identity(current.modelspace().add_line((2, 3), (9, 9), dxfattribs={"layer": "NATIVE"}), "new")
    candidate = tmp_path / "candidate.dxf"
    current.saveas(candidate)
    return baseline, candidate


def _entity(doc, oid):
    return next(e for e in doc.modelspace() if e.has_xdata(APPID) and entity_identity(e)["id"] == oid)


def test_saved_old_content_preserved_and_subpixel_mutation_rejected(tmp_path):
    before, after = _fixture(tmp_path)
    report = compare_saved_dxf(before, after)
    assert report["status"] == "PASS"
    assert report["new_object_ids"] == ["new"]
    doc = ezdxf.readfile(after)
    old = _entity(doc, "old")
    old.dxf.end = (10.000000000000002, 1, 0)
    doc.saveas(after)
    report = compare_saved_dxf(before, after)
    assert report["status"] == "FAIL"
    assert report["changed_old_ids"] == ["old"]


def test_review_block_style_and_layer_changes_are_not_count_only_checks(tmp_path):
    before, after = _fixture(tmp_path)
    doc = ezdxf.readfile(after)
    next(e for e in doc.modelspace() if e.dxf.layer == "REVIEW").dxf.end = (61, 50, 0)
    doc.blocks["test-block"][0].dxf.end = (4, 0, 0)
    doc.styles.get("test-font").dxf.width = 1.1
    doc.layers.get("NATIVE").dxf.color = 3
    doc.saveas(after)
    report = compare_saved_dxf(before, after)
    assert report["status"] == "FAIL"
    assert not any(report["context_exact"][k] for k in ("review", "blocks", "styles", "layers"))


def test_xclip_dictionary_content_cannot_inherit_complete_protection_or_edit_pass(tmp_path):
    before, after = _fixture(tmp_path)
    doc = ezdxf.readfile(before)
    XClip(_entity(doc, "old-block")).set_block_clipping_path([(-1, -1), (4, 1)])
    doc.saveas(before)
    _identity(doc.modelspace().add_line((2, 3), (9, 9), dxfattribs={"layer": "NATIVE"}), "new")
    XClip(_entity(doc, "old-block")).set_block_clipping_path([(-1, -1), (1, 1)])
    doc.saveas(after)
    report = compare_saved_dxf(before, after)
    # The spatial filter lives behind the unchanged INSERT dictionary handle.
    # Matching top-level and block tags cannot certify it.
    assert report["changed_top_level_old_ids"] == []
    assert report["context_exact"]["blocks"]
    assert report["status"] == "FAIL"
    assert report["unverified_complete_old_ids"] == ["old-block"]
    assert report["complete_object_status"]["old-block"] == "UNVERIFIED_DEPENDENCY"
    assert report["unchanged_old_object_count"] == 1
    assert any(row.get("object_id") == "old-block" and row["reason"] == "UNVERIFIED_EXTENSION_DICTIONARY"
               for row in report["candidate_dependency_errors"])
    edited = tmp_path / "delete.dxf"
    make_edit_copy(after, edited, "new", "delete")
    result = audit_edit_copy(after, edited, "new", "delete")
    assert result["status"] == "FAIL"
    assert result["checks"]["complete_target_operation"]
    assert not result["checks"]["edited_complete_dependencies_verified"]


def test_duplicate_or_missing_actual_stable_id_rejected(tmp_path):
    before, after = _fixture(tmp_path)
    doc = ezdxf.readfile(after)
    _identity(_entity(doc, "new"), "old")
    doc.saveas(after)
    assert compare_saved_dxf(before, after)["status"] == "FAIL"


def test_whole_delete_and_move_are_checked_after_save(tmp_path):
    _, source = _fixture(tmp_path)
    for operation in ("delete", "move"):
        edited = tmp_path / (operation + ".dxf")
        make_edit_copy(source, edited, "new", operation)
        result = audit_edit_copy(source, edited, "new", operation)
        assert result["status"] == "PASS"
        assert result["non_target_object_count"] == 2
    doc = ezdxf.readfile(tmp_path / "move.dxf")
    _entity(doc, "new").dxf.end = (9, 9, 0)
    doc.saveas(tmp_path / "move.dxf")
    assert audit_edit_copy(source, tmp_path / "move.dxf", "new", "move")["status"] == "FAIL"


def test_editing_neighbor_or_table_cannot_inherit_target_edit_pass(tmp_path):
    _, source = _fixture(tmp_path)
    edited = tmp_path / "edited.dxf"
    make_edit_copy(source, edited, "new", "delete")
    doc = ezdxf.readfile(edited)
    _entity(doc, "old").dxf.start = (3, 1, 0)
    doc.saveas(edited)
    result = audit_edit_copy(source, edited, "new", "delete")
    assert result["status"] == "FAIL"
    assert result["changed_non_target_ids"] == ["old"]


def test_whole_polyline_move_handles_serialized_defaults_but_rejects_missing_tail(tmp_path):
    _, source = _fixture(tmp_path)
    doc = ezdxf.readfile(source)
    doc.modelspace().delete_entity(_entity(doc, "new"))
    _identity(doc.modelspace().add_lwpolyline([(2, 3), (4, 4), (9, 9)]), "new", "CONNECTION_PATH")
    doc.saveas(source)
    edited = tmp_path / "polyline-move.dxf"
    make_edit_copy(source, edited, "new", "move")
    assert audit_edit_copy(source, edited, "new", "move")["status"] == "PASS"
    doc = ezdxf.readfile(edited)
    _entity(doc, "new").set_points([(13, -4), (15, -3)])
    doc.saveas(edited)
    assert audit_edit_copy(source, edited, "new", "move")["status"] == "FAIL"


def test_source_coordinate_geometry_comes_from_actual_file_and_blocks(tmp_path):
    _, path = _fixture(tmp_path)
    result = saved_source_geometries(path, [0, 0, 100, 100], 25.4)
    rows = {r["object_id"]: r for r in result["geometries"]}
    assert rows["new"]["points"] == [[2., 97.], [9., 91.]]
    assert rows["old-block/member:0"]["points"] == [[20., 80.], [23., 80.]]
    doc = ezdxf.readfile(path)
    _identity(doc.modelspace().add_circle((30, 30), 5), "circle")
    doc.saveas(path)
    rows = {r["object_id"]: r for r in saved_source_geometries(path, [0, 0, 100, 100], 25.4)["geometries"]}
    assert rows["circle"]["points"] == []
    assert rows["circle"]["bbox_xyxy"] == [25., 65., 35., 75.]
    assert rows["circle"]["unsupported_reason"] == "NON_LINEAR_NATIVE_MEMBER"


def test_actual_target_vertex_and_width_changes_reject_even_with_updated_file_hash(tmp_path):
    _, path = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    doc.modelspace().delete_entity(_entity(doc, "new"))
    _identity(doc.modelspace().add_lwpolyline([(2, 3), (4, 4), (9, 9)], dxfattribs={"layer": "NATIVE"}), "new", "CONNECTION_PATH")
    doc.saveas(path)
    ids = [entity_identity(e)["id"] for e in doc.modelspace() if e.has_xdata(APPID)]
    objects = [{"id": oid} for oid in ids if oid != "new"] + [{
        "id": "new", "kind": "CONNECTION_PATH", "layer": "NATIVE",
        "geometry": {"points": [[2, 97], [4, 96], [9, 91]], "bulges": [0., 0., 0.], "closed": False}}]
    metadata = {"dxf_sha256": sha256(path), "objects": objects, "written": [{"id": x} for x in ids],
                "roi_xyxy_px": [0, 0, 100, 100], "dpi": 25.4, "unit": "paper_mm", "source_sha256": "fixture-source"}
    meta = tmp_path / "objects.json"
    meta.write_text(json.dumps(metadata))
    frame = {"expected_roi": [0, 0, 100, 100], "expected_dpi": 25.4, "expected_source_sha256": "fixture-source"}
    assert audit_saved_target_bindings(path, meta, ["new"], **frame)["status"] == "PASS"
    metadata["roi_xyxy_px"] = [100, 0, 200, 100]
    objects[-1]["geometry"]["points"] = [[x + 100, y] for x, y in objects[-1]["geometry"]["points"]]
    meta.write_text(json.dumps(metadata))
    assert audit_saved_target_bindings(path, meta, ["new"], **frame)["status"] == "FAIL"
    metadata["roi_xyxy_px"] = [0, 0, 100, 100]
    objects[-1]["geometry"]["points"] = [[x - 100, y] for x, y in objects[-1]["geometry"]["points"]]
    _entity(doc, "new").dxf.const_width = .1
    doc.saveas(path)
    metadata["dxf_sha256"] = sha256(path)
    meta.write_text(json.dumps(metadata))
    assert audit_saved_target_bindings(path, meta, ["new"], **frame)["status"] == "FAIL"


def test_saved_identity_kind_is_not_trusted_from_matching_id(tmp_path):
    from app.native_objects.independent_saved_geometry_audit import check_target_binding
    _, path = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    entity = _entity(doc, "new")
    declaration = {"id": "new", "kind": "LINE", "layer": "NATIVE",
                   "geometry": {"start": [2, 97], "end": [9, 91]}}
    assert check_target_binding(entity, declaration, [0, 0, 100, 100], 25.4)["pass"]
    _identity(entity, "new", "WRONG_KIND")
    report = check_target_binding(entity, declaration, [0, 0, 100, 100], 25.4)
    assert not report["pass"]
    assert not report["checks"]["identity_kind"]


def test_matching_degenerate_geometry_is_not_a_valid_target(tmp_path):
    from app.native_objects.independent_saved_geometry_audit import check_target_binding
    _, path = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    entity = _entity(doc, "new")
    entity.dxf.end = entity.dxf.start
    declaration = {"id": "new", "kind": "LINE", "layer": "NATIVE",
                   "geometry": {"start": [2, 97], "end": [2, 97]}}
    report = check_target_binding(entity, declaration, [0, 0, 100, 100], 25.4)
    assert report["checks"]["complete_finite_geometry"]
    assert not report["checks"]["nondegenerate_native_geometry"]
    assert not report["pass"]


def test_minserts_and_skipped_members_are_explicitly_unresolved(tmp_path, monkeypatch):
    _, path = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    _entity(doc, "old-block").dxf.column_count = 2
    _entity(doc, "old-block").dxf.column_spacing = 100
    doc.saveas(path)
    rows = saved_source_geometries(path, [0, 0, 100, 100], 25.4)["geometries"]
    assert any(r.get("unsupported_reason") == "MULTIPLE_INSERT_REQUIRES_COMPLETE_INSTANCE_AUDIT" for r in rows)
    _entity(doc, "old-block").dxf.column_count = 1
    doc.saveas(path)
    from ezdxf.entities import Insert
    def skipped(self, *, skipped_entity_callback, **kwargs):
        skipped_entity_callback(next(iter(self.block())), "unsupported transform")
        return iter(())
    monkeypatch.setattr(Insert, "virtual_entities", skipped)
    rows = saved_source_geometries(path, [0, 0, 100, 100], 25.4)["geometries"]
    assert any(r.get("unsupported_reason") == "UNTRANSFORMED_BLOCK_MEMBERS" for r in rows)


def test_width_thickness_and_unknown_bounds_never_certify_exclusion(tmp_path):
    _, path = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    _entity(doc, "old").dxf.thickness = 10
    wide = doc.modelspace().add_lwpolyline([(0, 0), (3, 0)])
    wide.dxf.const_width = 10
    _identity(wide, "wide", "CONNECTION_PATH")
    varying = doc.modelspace().add_lwpolyline([(0, 0, 1, 10, 0), (3, 0, 10, 2, 0)], format="xyseb")
    _identity(varying, "varying", "CONNECTION_PATH")
    doc.saveas(path)
    rows = {r["object_id"]: r for r in saved_source_geometries(path, [0, 0, 100, 100], 25.4)["geometries"]}
    assert rows["old"]["unsupported_reason"] == "LINE_THICKNESS_REQUIRES_AREA_AUDIT"
    for oid in ("old", "wide", "varying"):
        assert not rows[oid]["coverage_valid"]
        assert rows[oid]["unsupported_reason"]
    assert rows["wide"]["width_unit"] == "saved_dxf_mm"
