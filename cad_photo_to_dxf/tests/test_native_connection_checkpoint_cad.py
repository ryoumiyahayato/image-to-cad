"""Actual old entities survive a bounded native connection export unchanged.

These tests exercise saved CAD structure, not font rendering. The existing
explicit geometry-export fixture isolates only the new-path font packaging.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import ezdxf
import pytest

from app.native_objects import cad_io
from app.native_objects.connection_checkpoint_cad import write_checkpoint_dxf


ROI = [0, 0, 200, 120]
SOURCE_SHA = "9" * 64


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _baseline(tmp_path, mtext=None):
    path = tmp_path / "baseline.dxf"
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(cad_io.APPID)
    doc.appids.new("SECOND_SOURCE_APP")
    for name in ("GEOMETRY", "ROOM_LABELS", "ANNOTATION", "REVIEW"):
        doc.layers.new(name, dxfattribs={"color": 3, "lineweight": 25})
    doc.layers.get("REVIEW").off()
    doc.styles.new("OLD_STYLE", dxfattribs={"font": "txt", "width": 0.91})
    msp = doc.modelspace()
    objects = []

    def mark(entity, oid, kind):
        cad_io.mark(entity, {"id": oid, "kind": kind})
        if kind != "REVIEW":
            objects.append({
                "id": oid, "kind": kind, "layer": entity.dxf.layer,
                # Deliberately not sufficient to redraw these objects: the
                # actual old DXF must be retained, not reconstructed.
                "geometry": {"original_entity_is_authoritative": True},
                "source_evidence": {"method": "synthetic_structural_fixture"},
            })
        return entity

    line = mark(msp.add_line((1, 1), (15, 1), dxfattribs={"layer": "GEOMETRY", "color": 5}), "keep-line", "LINE")
    line.set_xdata("SECOND_SOURCE_APP", [(1000, "other application evidence"), (1070, 12)])
    mark(msp.add_line((1, 2), (15, 2), dxfattribs={"layer": "GEOMETRY"}), "remove-line", "LINE")
    block = doc.blocks.new("INDEPENDENT_OLD_NOTE", base_point=(2, 3))
    block.add_text("KEEP", dxfattribs={"insert": (2, 4), "height": 2, "width": 0.87, "rotation": 11, "style": "OLD_STYLE"})
    block.add_line((0, 0), (4, 4))
    mark(msp.add_blockref(block.name, (30, 20), dxfattribs={"layer": "ROOM_LABELS", "rotation": 7, "xscale": 1.2, "yscale": 0.9}), "keep-block", "ROOM_LABEL")
    mark(msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], dxfattribs={"layer": "REVIEW"}), "review-only", "REVIEW")
    if mtext is not None:
        attrs = {"layer": "ANNOTATION", "insert": (10, 15), "char_height": 2, "width": 20, "style": "OLD_STYLE", "line_spacing_factor": 0.85}
        if mtext == "explicit":
            attrs["flow_direction"] = 1
        mark(msp.add_mtext("FIRST\\PSECOND", dxfattribs=attrs), "keep-mtext", "MTEXT")
    if mtext == "explicit":
        cad_io.save_native_dxf(doc, path)
    else:
        doc.saveas(path)
    cold = ezdxf.readfile(path)
    written = []
    for entity in cold.modelspace():
        identity = cad_io.identity(entity)
        if identity["kind"] == "REVIEW":
            continue
        written.append({
            **identity, "type": entity.dxftype(), "handle": entity.dxf.handle,
            "block_members": [member.dxftype() for member in cold.blocks.get(entity.dxf.name)] if entity.dxftype() == "INSERT" else [],
        })
    return path, {
        "dxf_path": str(path), "dxf_sha256": _sha(path), "source_sha256": SOURCE_SHA,
        "roi_xyxy_px": ROI, "dpi": 200, "unit": "paper_mm",
        "objects": objects, "written": written,
    }


def _new_objects():
    return [{
        "id": "new-complete-path", "kind": "CONNECTION_PATH", "layer": "CONNECTIONS",
        "geometry": {"points": [[20, 20], [25, 15], [35, 10]], "bulges": [0.2, -0.1, 0.0], "closed": False},
        "source_evidence": {"method": "synthetic_complete_connection"},
    }]


def test_retains_actual_entities_blocks_tables_and_all_xdata(tmp_path, native_geometry_export_context):
    baseline, old_meta = _baseline(tmp_path)
    before_bytes = baseline.read_bytes()
    new_objects = _new_objects()
    output = tmp_path / "local" / "new.dxf"
    with native_geometry_export_context(new_objects):
        meta = write_checkpoint_dxf(baseline, old_meta, ["keep-line", "keep-block"], new_objects, output, ROI, 200, SOURCE_SHA)
    assert baseline.read_bytes() == before_bytes
    assert [row["id"] for row in meta["objects"]] == ["keep-line", "keep-block", "new-complete-path"]
    cold = ezdxf.readfile(output)
    entities = {cad_io.identity(entity)["id"]: entity for entity in cold.modelspace()}
    assert set(entities) == {"keep-line", "keep-block", "new-complete-path"}
    assert entities["new-complete-path"].dxftype() == "LWPOLYLINE"
    assert list(entities["new-complete-path"].get_points("b")) == [(-0.2,), (0.1,), (-0.0,)]
    assert [tag.value for tag in entities["keep-line"].get_xdata("SECOND_SOURCE_APP")] == ["other application evidence", 12]
    assert [entity.dxftype() for entity in cold.blocks.get("INDEPENDENT_OLD_NOTE")] == ["TEXT", "LINE"]
    assert cold.blocks.get("INDEPENDENT_OLD_NOTE").block.dxf.base_point == (2, 3, 0)
    assert cold.styles.get("OLD_STYLE").dxf.width == 0.91
    assert cold.layers.get("REVIEW").is_off()
    assert not list(cold.modelspace().query('*[layer=="REVIEW"]'))
    for record in meta["written"]:
        assert entities[record["id"]].dxf.handle == record["handle"]
    certificate = json.loads(Path(meta["preservation_certificate"]["path"]).read_text())
    assert certificate["status"] == "PASS"
    assert certificate["old_entities_reconstructed_from_ledger"] is False
    assert certificate["whole_neighbors_clipped_to_windows"] is False
    assert certificate["source_review_of_new_paths"] == "REQUIRED_SEPARATELY_NOT_INHERITED_FROM_BASELINE"
    assert certificate["removed_old_ids"] == ["remove-line"]


@pytest.mark.parametrize("mode", ["missing", "explicit"])
def test_mtext_direction_presence_and_layout_are_not_invented(tmp_path, native_geometry_export_context, mode):
    baseline, old_meta = _baseline(tmp_path, mtext=mode)
    old = ezdxf.readfile(baseline).modelspace().query("MTEXT").first
    old_data = cad_io.entity_data(old)
    assert old.dxf.hasattr("flow_direction") is (mode == "explicit")
    new_objects = _new_objects()
    output = tmp_path / "local.dxf"
    with native_geometry_export_context(new_objects):
        meta = write_checkpoint_dxf(baseline, old_meta, ["keep-mtext"], new_objects, output, ROI, 200, SOURCE_SHA)
    saved = ezdxf.readfile(output).modelspace().query("MTEXT").first
    assert saved.dxf.hasattr("flow_direction") is (mode == "explicit")
    assert cad_io.entity_data(saved) == old_data
    assert meta["preservation_certificate"]["status"] == "PASS"


@pytest.mark.parametrize("damage", ["unknown_retained", "duplicate_retained", "duplicate_new", "reuse_old_id", "new_block", "changed_roi"])
def test_writer_rejects_ambiguous_ids_new_blocks_and_coordinate_changes(tmp_path, damage):
    baseline, old_meta = _baseline(tmp_path)
    retained, new_objects, roi = ["keep-line"], _new_objects(), ROI
    if damage == "unknown_retained":
        retained = ["not-present"]
    elif damage == "duplicate_retained":
        retained *= 2
    elif damage == "duplicate_new":
        new_objects.append(deepcopy(new_objects[0]))
    elif damage == "reuse_old_id":
        new_objects[0]["id"] = "remove-line"
    elif damage == "new_block":
        new_objects[0]["kind"] = "ROOM_LABEL"
    else:
        roi = [1, 1, 200, 120]
    output = tmp_path / "must-not-exist.dxf"
    with pytest.raises(ValueError, match="CHECKPOINT_DXF_"):
        write_checkpoint_dxf(baseline, old_meta, retained, new_objects, output, roi, 200, SOURCE_SHA)
    assert not output.exists()
    assert _sha(baseline) == old_meta["dxf_sha256"]


def test_changed_retained_entity_fails_before_output_publication(tmp_path, monkeypatch, native_geometry_export_context):
    baseline, old_meta = _baseline(tmp_path)
    new_objects = _new_objects()
    original = cad_io.save_native_dxf

    def corrupted_save(doc, path):
        if Path(path).name == "merged_candidate.dxf":
            for entity in doc.modelspace().query("LINE"):
                entity.dxf.end = (999, 999)
        return original(doc, path)

    monkeypatch.setattr(cad_io, "save_native_dxf", corrupted_save)
    output = tmp_path / "must-not-exist.dxf"
    with native_geometry_export_context(new_objects), pytest.raises(ValueError, match="PRESERVATION_CHANGED"):
        write_checkpoint_dxf(baseline, old_meta, ["keep-line"], new_objects, output, ROI, 200, SOURCE_SHA)
    assert not output.exists()
    failures = list(tmp_path.glob("checkpoint-writer-*/failure.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())["status"] == "FAILED_NO_OUTPUT_PUBLICATION"
    assert _sha(baseline) == old_meta["dxf_sha256"]
