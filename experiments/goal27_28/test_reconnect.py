"""Focused synthetic counterexamples; never counted as real CAD operations."""
from copy import deepcopy
import io
import json
from pathlib import Path
from zipfile import ZipFile

import ezdxf
from PIL import Image
import pytest

import cad_delta as d
from reconnect import ReconnectProject, collect


def drawing(path):
    doc = ezdxf.new("R2010")
    doc.units = 4
    return doc


def save(doc, path):
    doc.saveas(path)
    return path


def test_engineering_string_never_uses_geometry_tolerance(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    text = a.modelspace().add_text("10 mm", dxfattribs={"height": 2.})
    p0 = save(a, tmp_path / "a.dxf")
    text.dxf.text = "10 cm"
    text.dxf.height += .00001
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert result["summary"]["changed_suggestions"] == 1
    assert {x["field"] for x in result["changes"][0]["fields"]} >= {"text", "height"}
    assert result["changes"][0]["identity"] == "NOT_PROVEN"


def test_delete_rebuild_equal_content_does_not_prove_identity(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    entity = a.modelspace().add_line((0, 0), (10, 0))
    p0 = save(a, tmp_path / "a.dxf")
    a.modelspace().delete_entity(entity)
    a.modelspace().add_line((0, 0), (10, 0))
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert result["summary"]["content_equal"] == 1
    assert result["summary"]["confirmed_historical_identities"] == 0


def test_identical_copy_retains_multiplicity_ambiguity(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    a.modelspace().add_line((0, 0), (10, 0))
    p0 = save(a, tmp_path / "a.dxf")
    a.modelspace().add_line((0, 0), (10, 0))
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert len(result["added_or_unmatched"]) == 1
    assert result["duplicate_groups"][0]["count_changed"]
    assert result["summary"]["confirmed_historical_identities"] == 0


def test_small_hole_cannot_be_erased_by_tolerance(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    hatch = a.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    hatch.paths.add_polyline_path([(1, 1), (1.00001, 1), (1.00001, 1.00001)], is_closed=True)
    p0 = save(a, tmp_path / "a.dxf")
    hatch.paths.paths.pop()
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert result["summary"]["content_equal"] == 0
    assert result["summary"]["functional_equal"] == 0
    assert result["removed_or_unmatched"] and result["added_or_unmatched"]


def test_geometry_subresolution_is_recorded(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    e = a.modelspace().add_line((0, 0), (10, 0))
    p0 = save(a, tmp_path / "a.dxf")
    e.dxf.end = (10.0001, 0)
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert result["summary"]["functional_equal"] == 1
    assert result["serialization_or_subresolution"]


def test_visibility_is_exact_even_when_effectively_frozen(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    layer = a.layers.new("hidden")
    layer.off(); layer.freeze()
    a.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "hidden"})
    p0 = save(a, tmp_path / "a.dxf")
    layer.on()
    result = d.compare(p0, save(a, tmp_path / "b.dxf"))
    assert any(x["field"] == "layers.hidden.off" for x in result["document_changes"])


def test_source_trace_keeps_original_tags_without_assigning_duplicates(tmp_path):
    doc = drawing(tmp_path / "before.dxf")
    doc.appids.add("ORIGINAL_SOURCE")
    layer = doc.layers.new("backup")
    layer.off()
    layer.freeze()
    space = doc.modelspace()
    dup_a = space.add_line((0, 0), (10, 0))
    dup_b = space.add_line((0, 0), (10, 0))
    single = space.add_line((0, 2), (10, 2))
    lost = space.add_circle((50, 50), 3)
    block = doc.blocks.new("source-block")
    nested = block.add_line((0, 0), (3, 0))
    space.add_blockref(block.name, (0, 50))
    entities = (dup_a, dup_b, single, lost, nested)
    for index, entity in enumerate(entities):
        entity.set_xdata("ORIGINAL_SOURCE", [(1070, index)])
    duplicate_handles = [dup_a.dxf.handle, dup_b.dxf.handle]
    lost_handle = lost.dxf.handle
    before = d.read(save(doc, tmp_path / "before.dxf"))
    for entity in entities:
        entity.discard_xdata("ORIGINAL_SOURCE")
    space.delete_entity(lost)
    layer.on()
    after = d.read(save(doc, tmp_path / "after.dxf"))

    trace = d.retain_source_trace(before, after, d.compare(before, after))
    assert trace["baseline"]["layers"]["backup"]["off"]
    assert not trace["saved"]["layers"]["backup"]["off"]
    assert trace["saved"]["layers"]["backup"]["frozen"]
    assert trace["baseline"]["modelspace"][lost_handle]["xdata"]["ORIGINAL_SOURCE"][-1] == [1070, 3]
    assert nested.dxf.handle in trace["baseline"]["blocks"]["source-block"]
    assert not trace["saved"]["modelspace"] and not trace["saved"]["blocks"]
    assert trace["unmatched_baseline_handles"] == [lost_handle]
    assert [m["before"] for m in trace["candidates"]] == [single.dxf.handle]
    assert trace["ambiguous_groups"] == [{
        "before": duplicate_handles, "after_candidates": duplicate_handles, "reason": "DUPLICATE_CONTENT",
    }]
    assert trace["historical_identity"] == "NOT_PROVEN"
    assert not trace["source_automatic_operations"]


@pytest.mark.parametrize("restore", (False, True))
def test_portable_delivery_tracks_moved_images_layers_and_source_targets(tmp_path, restore):
    from app.export.portable_dxf import validate_directory

    folder = tmp_path / "original"
    folder.mkdir()
    png = folder / "asset.png"
    Image.new("RGBA", (3, 3), "red").save(png)
    doc = drawing(folder / "before.dxf")
    doc.appids.add("ORIGINAL_SOURCE")
    layer = doc.layers.new("backup", dxfattribs={"color": 2})
    layer.off()
    layer.freeze()
    doc.styles.new("delivery-font", dxfattribs={"font": "wqy-unicode.lff"})
    space = doc.modelspace()
    text = space.add_text("示例", dxfattribs={"style": "delivery-font"})
    text.set_xdata("ORIGINAL_SOURCE", [(1070, 1)])
    block = doc.blocks.new("points")
    member = block.add_circle((3, 3), 1)
    member.set_xdata("ORIGINAL_SOURCE", [(1070, 2)])
    duplicate = block.add_circle((7, 7), 1)
    duplicate.set_xdata("ORIGINAL_SOURCE", [(1070, 3)])
    block.add_circle((7, 7), 1)
    space.add_blockref(block.name, (0, 0))
    definition = doc.add_image_def(filename=png.name, size_in_pixel=(3, 3))
    space.add_image(definition, insert=(0, 0), size_in_units=(3, 3))
    before = save(doc, folder / "before.dxf")
    for entity in (text, member, duplicate):
        entity.discard_xdata("ORIGINAL_SOURCE")
    layer.dxf.color = 256
    definition.dxf.owner = "FFFFF"
    after = save(doc, folder / "saved.dxf")

    archive_path = tmp_path / "delivery.zip"
    manifest = d.package_delivery(before, after, archive_path, restore_layer_states=restore)
    unpacked = tmp_path / "unpacked"
    with ZipFile(archive_path) as archive:
        archive.extractall(unpacked)
    moved = unpacked.rename(tmp_path / "moved directory")
    png.unlink()
    target = moved / manifest["dxf"]
    assert len(validate_directory(target)) == 1
    delivered = ezdxf.readfile(target)
    assert delivered.layers.get("backup").is_off() is restore
    assert delivered.layers.get("backup").is_frozen()
    assert not delivered.entitydb[text.dxf.handle].has_xdata("ORIGINAL_SOURCE")
    assert "wqy-unicode.lff" in (moved / manifest["font_note"]).read_text(encoding="utf-8")
    record = json.loads((moved / manifest["source_record"]).read_text(encoding="utf-8"))
    assert record["after"] == target.name
    trace = record["source_trace"]
    assert trace["candidate_targets"][text.dxf.handle]["text"] == "示例"
    assert [c["after"] for c in trace["block_candidates"]] == [member.dxf.handle]
    assert trace["unresolved_block_handles"] == {"points": [duplicate.dxf.handle]}


def test_resource_contents_and_missing_dependency(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    for folder, color in ((first, "red"), (second, "blue")):
        Image.new("RGBA", (3, 3), color).save(folder / "asset.png")
        a = drawing(folder / "drawing.dxf")
        image = a.add_image_def(filename="asset.png", size_in_pixel=(3, 3))
        a.modelspace().add_image(image, insert=(0, 0), size_in_units=(3, 3))
        save(a, folder / "drawing.dxf")
    result = d.compare(first / "drawing.dxf", second / "drawing.dxf")
    assert any(x["field"] == "asset_content" for x in result["changes"][0]["fields"])
    assert result["summary"]["content_equal"] == 0
    assert result["mappings"][0]["status"] == "ASSET_CHANGE"
    (second / "asset.png").unlink()
    assert d.compare(first / "drawing.dxf", second / "drawing.dxf")["missing_dependencies"]
    with pytest.raises(ValueError, match="MISSING_DEPENDENCIES"):
        collect(second / "drawing.dxf")


def test_stale_preview_and_repeat_accept_are_safe(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    e = a.modelspace().add_text("A", dxfattribs={"height": 2.})
    p0 = save(a, tmp_path / "a.dxf")
    e.dxf.text = "B"
    p1 = save(a, tmp_path / "b.dxf")
    files, snapshot = collect(p0)
    state = {"format": "external-cad-extension-v1", "revision": 0, "current": "baseline", "project_uuid": "test", "states": {"baseline": {"parent": None, "relations": {}}}, "journal": [], "exports": {}, "accepted_external": []}
    project = ReconnectProject({}, state, {"baseline": files})
    preview = project.preview(p0, p1)
    before = deepcopy(project.state)
    e.dxf.text = "C"; save(a, p1)
    with pytest.raises(ValueError, match="INPUT_CHANGED_SINCE_PREVIEW"):
        project.accept(preview, actor="TEST_ONLY")
    assert project.state == before
    preview = project.preview(p0, p1)
    assert project.accept(preview, actor="TEST_ONLY")
    assert project.preview(p0, p1)["status"] == "ALREADY_ACCEPTED"
    assert project.preview(p0, p1)["confirmation_items"] == 0
    project.undo()
    assert project.state["current"] == "baseline"


def test_two_branches_changing_same_member_report_conflict(tmp_path):
    a = drawing(tmp_path / "a.dxf")
    e = a.modelspace().add_text("A", dxfattribs={"height": 2.})
    p0 = save(a, tmp_path / "a.dxf")
    e.dxf.text = "LOCAL"; p1 = save(a, tmp_path / "local.dxf")
    e.dxf.text = "EXTERNAL"; p2 = save(a, tmp_path / "external.dxf")
    files, _ = collect(p0)
    state = {"format": "external-cad-extension-v1", "revision": 0, "current": "baseline", "project_uuid": "test", "states": {"baseline": {"parent": None, "relations": {}}}, "journal": [], "exports": {}, "accepted_external": []}
    project = ReconnectProject({}, state, {"baseline": files})
    project.accept(project.preview(p0, p1), actor="TEST_ONLY")
    report = project.preview(p0, p2)
    assert report["status"] == "OBJECT_CONFLICT"
    before = deepcopy(project.state)
    with pytest.raises(ValueError, match="OBJECT_CONFLICT"):
        project.accept(report, actor="TEST_ONLY")
    assert project.state == before


def test_restore_history_is_new_transaction_but_old_delivery_is_not(tmp_path):
    doc = drawing(tmp_path / "original.dxf")
    e = doc.modelspace().add_text("ORIGINAL", dxfattribs={"height": 2.})
    p0 = save(doc, tmp_path / "original.dxf")
    e.dxf.text = "FIRST_EDIT"; p1 = save(doc, tmp_path / "first.dxf")
    e.dxf.text = "SECOND_EDIT"; p2 = save(doc, tmp_path / "second.dxf")
    files, _ = collect(p0)
    state = {"revision": 0, "current": "baseline", "project_uuid": "test", "states": {"baseline": {"parent": None, "relations": {}}}, "journal": [], "exports": {}, "accepted_external": []}
    project = ReconnectProject({}, state, {"baseline": files})
    project.accept(project.preview(p0, p1), actor="TEST_ONLY")
    project.accept(project.preview(p1, p2), actor="TEST_ONLY")
    assert project.preview(p0, p1)["status"] == "ALREADY_ACCEPTED"
    restore = project.preview(p2, p1)
    assert restore["status"] == "READY_FOR_REVIEW"
    assert restore["confirmation_items"] == 1
    assert project.accept(restore, actor="TEST_ONLY")
    assert project.payloads[project.state["current"]] == collect(p1)[0]
    assert project.preview(p2, p1)["status"] == "ALREADY_ACCEPTED"
    # A repeated byte state must resolve to the active state, including after undo.
    project.undo()
    assert project.find_base(collect(p2)[0]) == project.state["current"]
    assert project.preview(p2, p1)["status"] == "READY_FOR_REVIEW"


def test_transitive_block_geometry_and_style_are_visible_changes(tmp_path):
    doc = drawing(tmp_path / "a.dxf")
    doc.styles.new("inner.style", dxfattribs={"font": "one.ttf"})
    inner = doc.blocks.new("INNER.part")
    line = inner.add_line((0, 0), (10, 0))
    inner.add_text("nested", dxfattribs={"style": "inner.style"})
    doc.blocks.new("OUTER").add_blockref("inner.part", (0, 0))
    doc.modelspace().add_blockref("outer", (0, 0))
    doc.blocks.new("unused").add_line((0, 0), (1, 0))
    p0 = save(doc, tmp_path / "a.dxf")
    line.dxf.end = (20, 0)
    doc.styles.get("inner.style").dxf.font = "two.ttf"
    doc.blocks.get("unused")[0].dxf.end = (2, 0)
    result = d.compare(p0, save(doc, tmp_path / "b.dxf"))
    assert {v["field"] for v in result["document_changes"]} >= {"blocks.INNER.part.members", "styles.inner.style.font"}
    assert {v["field"] for v in result["serialization_or_subresolution"] if v.get("reason") == "UNREFERENCED_TABLE_RECORD"} == {"blocks.unused.members"}


def test_nested_unsupported_type_and_block_cycle_are_rejected(tmp_path):
    doc = drawing(tmp_path / "a.dxf")
    block = doc.blocks.new("inner")
    block.add_ray((0, 0), (1, 0))
    doc.modelspace().add_blockref("inner", (0, 0))
    with pytest.raises(ValueError, match="Unsupported entity"):
        collect(save(doc, tmp_path / "a.dxf"))
    block.add_blockref("inner", (0, 0))
    with pytest.raises(ValueError, match="BLOCK_CYCLE"):
        collect(save(doc, tmp_path / "cycle.dxf"))


def test_mtext_background_extent_is_exact_and_retains_raw_change(tmp_path):
    doc = drawing(tmp_path / "a.dxf")
    e = doc.modelspace().add_mtext("note", dxfattribs={"bg_fill": 1, "bg_fill_color": 3, "box_fill_scale": 1.1})
    p0 = save(doc, tmp_path / "a.dxf")
    e.dxf.box_fill_scale = 5.
    result = d.compare(p0, save(doc, tmp_path / "b.dxf"))
    assert result["summary"]["content_equal"] == 0
    assert result["summary"]["changed_suggestions"] == 1
    assert {v["field"] for v in result["changes"][0]["fields"]} == {"box_fill_scale"}
    assert result["changes"][0]["raw_delta"]


def test_missing_block_and_multicolumn_text_are_explicitly_rejected(tmp_path):
    doc = drawing(tmp_path / "a.dxf")
    doc.modelspace().add_blockref("missing", (0, 0))
    with pytest.raises(ValueError, match="MISSING_BLOCK"):
        collect(save(doc, tmp_path / "a.dxf"))
    doc = drawing(tmp_path / "columns.dxf")
    doc.modelspace().add_mtext_static_columns(["first", "second"], width=10, gutter_width=2, height=20)
    with pytest.raises(ValueError, match="UNSUPPORTED_MTEXT_COLUMNS"):
        collect(save(doc, tmp_path / "columns.dxf"))
