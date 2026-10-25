"""Saved synthetic DXF integration tests; distinct from the real-PDF study."""
import json
import subprocess
import sys

import ezdxf
import pytest

from tools.drafting_rules.cli import load_pack, validate_files
from tools.drafting_rules.dxf_adapter import sha256, snapshot


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def fixture(tmp_path):
    before, after = tmp_path / "before.dxf", tmp_path / "after.dxf"
    source, evidence_path = tmp_path / "source.txt", tmp_path / "evidence.json"
    source.write_text("Synthetic drawing, no real drawing claims.")
    doc = ezdxf.new("R2010")
    doc.units = 0  # Coordinates in this synthetic source are explicitly unitless.
    doc.layers.new("TABLE")
    doc.layers.new("OLD")
    doc.styles.new("wqy-unicode", dxfattribs={"font": "wqy-unicode.lff"})
    msp = doc.modelspace()
    text = msp.add_text("电气", dxfattribs={"height": 3, "insert": (10, 10), "style": "wqy-unicode"})
    outline = msp.add_lwpolyline([(10, 10), (12, 12)], dxfattribs={"layer": "OLD"})
    logo = msp.add_circle((40, 10), 2)
    line = msp.add_line((0, 0), (60, 0), dxfattribs={"layer": "TABLE"})
    doc.saveas(before)
    text.dxf.text = "水电"
    doc.layers.get("OLD").off()
    doc.layers.get("OLD").freeze()
    doc.saveas(after)
    evidence = dict(schema_version=1,
                    source=dict(sha256=sha256(source), page=1, region=[0, 0, 60, 20],
                                authority="synthetic integration fixture", units="unitless"),
                    before_sha256=sha256(before), after_sha256=sha256(after),
                    texts=[dict(id="row", handle=text.dxf.handle, expected_text="水电",
                                cell=[0, 1, 30, 19], source_outline_handles=[outline.dxf.handle],
                                outline_mapping_complete=True, ownership_ref="synthetic outline mapping")],
                    protected=[dict(id="logo", role="logo", handles=[logo.dxf.handle], authority="synthetic")],
                    table=dict(id="table", layer="TABLE", mapping_complete=True,
                               source_ref="synthetic segment", source_segments=[[0, 0, 60, 0]]),
                    edit=dict(allowed_handles=[text.dxf.handle, outline.dxf.handle]))
    write_json(evidence_path, evidence)
    return before, after, source, evidence_path, evidence, line.dxf.handle


def test_saved_edit_roundtrip_uses_actual_font_metrics(tmp_path):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    report = validate_files(before, after, source, path)
    assert report["summary"] == {"PASS": 6}
    h = evidence["texts"][0]["handle"]
    assert snapshot(after)[h]["bounds"] is not None
    assert ezdxf.readfile(after).entitydb[h].dxf.text == "水电"


@pytest.mark.parametrize("mutation,rule", [
    ("hidden", "editable-text"), ("wrong-content", "editable-text"),
    ("overflow", "cell-fit"), ("residual", "source-glyph-exit"),
    ("logo", "background-protection"), ("duplicate", "table-line-parity"),
    ("bridge", "table-line-parity"), ("missing", "table-line-parity"),
    ("unrelated", "edit-isolation"), ("shared-style", "edit-isolation"),
])
def test_real_file_mutations_fail(tmp_path, mutation, rule):
    before, after, source, path, evidence, line = fixture(tmp_path)
    doc = ezdxf.readfile(after)
    text = doc.entitydb[evidence["texts"][0]["handle"]]
    if mutation == "hidden":
        text.dxf.invisible = 1
    elif mutation == "wrong-content":
        text.dxf.text = "错误"
    elif mutation == "overflow":
        text.dxf.insert = (200, 200)
    elif mutation == "residual":
        doc.layers.get("OLD").on()
        doc.layers.get("OLD").thaw()
    elif mutation == "logo":
        doc.entitydb[evidence["protected"][0]["handles"][0]].dxf.radius = 3
    elif mutation == "duplicate":
        doc.modelspace().add_line((60, 0), (0, 0), dxfattribs={"layer": "TABLE"})
    elif mutation == "bridge":
        doc.entitydb[line].dxf.end = (80, 0)
    elif mutation == "missing":
        doc.modelspace().delete_entity(doc.entitydb[line])
    elif mutation == "shared-style":
        # Shared resources change appearance without changing entity tags.
        doc.layers.get("0").dxf.color = 1
    else:
        doc.entitydb[line].translate(1, 0, 0)
    doc.saveas(after)
    evidence["after_sha256"] = sha256(after)
    write_json(path, evidence)
    report = validate_files(before, after, source, path)
    assert next(r for r in report["results"] if r["rule"] == rule)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["font", "mtext", "alignment", "missing-glyph", "oblique", "rotation"])
def test_unsupported_layout_abstains(tmp_path, mutation):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    doc = ezdxf.readfile(after)
    text = doc.entitydb[evidence["texts"][0]["handle"]]
    if mutation == "font":
        text.dxf.style = "Standard"
    elif mutation == "mtext":
        doc.modelspace().delete_entity(text)
        replacement = doc.modelspace().add_mtext("水电")
        evidence["texts"][0]["handle"] = replacement.dxf.handle
    elif mutation == "alignment":
        text.dxf.halign = 1
    elif mutation == "missing-glyph":
        text.dxf.text = "\U0010ffff"
    elif mutation == "rotation":
        text.dxf.rotation = 13
    else:
        text.dxf.oblique = 12
    doc.saveas(after)
    evidence["after_sha256"] = sha256(after)
    write_json(path, evidence)
    report = validate_files(before, after, source, path)
    assert next(r for r in report["results"] if r["rule"] == "cell-fit")["status"] == "ABSTAIN"


def test_stale_hash_bad_schema_and_nan_rejected(tmp_path):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    evidence["after_sha256"] = "0" * 64
    write_json(path, evidence)
    with pytest.raises(ValueError, match="Stale"):
        validate_files(before, after, source, path)
    path.write_text('{"value": NaN}')
    with pytest.raises(ValueError, match="Non-finite"):
        validate_files(before, after, source, path)


def test_official_executable_requires_full_text_and_clause(tmp_path):
    pack = load_pack()
    pack["rules"][0].update(classification="OFFICIAL_STANDARD", sources=["title-block"])
    path = tmp_path / "pack.json"
    write_json(path, pack)
    with pytest.raises(ValueError, match="verified edition and clause"):
        load_pack(path)


def test_cli_strict_abstain_exit_and_no_overwrite(tmp_path):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    evidence["texts"][0].pop("cell")
    write_json(path, evidence)
    output = tmp_path / "report.json"
    args = [sys.executable, "-m", "tools.drafting_rules.cli", "validate", "--before", str(before),
            "--after", str(after), "--source", str(source), "--evidence", str(path), "--output", str(output), "--strict"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    saved = output.read_bytes()
    assert subprocess.run(args, capture_output=True).returncode == 2
    assert output.read_bytes() == saved


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_orthogonal_rotation_measures_current_entity_not_cached_export_bbox(tmp_path, angle):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    doc = ezdxf.readfile(after)
    text = doc.entitydb[evidence["texts"][0]["handle"]]
    old = snapshot(after)[text.dxf.handle]["bounds"]
    text.dxf.rotation = angle
    doc.saveas(after)
    evidence["after_sha256"] = sha256(after)
    evidence["texts"][0]["cell"] = [-50, -50, 50, 50]
    write_json(path, evidence)
    report = validate_files(before, after, source, path)
    assert next(r for r in report["results"] if r["rule"] == "cell-fit")["status"] == "PASS"
    assert snapshot(after)[text.dxf.handle]["bounds"] != old


def test_block_contents_cannot_hide_behind_unchanged_outer_handle(tmp_path):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    doc = ezdxf.readfile(before)
    block = doc.blocks.new("BACKGROUND")
    inner = block.add_circle((0, 0), 1)
    outer = doc.modelspace().add_blockref("BACKGROUND", (30, 20))
    doc.saveas(before)
    inner.dxf.radius = 2
    doc.saveas(after)
    evidence.update(before_sha256=sha256(before), after_sha256=sha256(after))
    evidence["protected"] = [dict(id="block", role="logo", handles=[outer.dxf.handle], authority="synthetic")]
    write_json(path, evidence)
    report = validate_files(before, after, source, path)
    assert next(r for r in report["results"] if r["rule"] == "background-protection")["status"] == "ABSTAIN"
    assert next(r for r in report["results"] if r["rule"] == "edit-isolation")["status"] == "ABSTAIN"


@pytest.mark.parametrize("invalid", ["schema", "region", "units"])
def test_cli_input_errors_are_persisted_and_never_reported_as_pass(tmp_path, invalid):
    before, after, source, path, evidence, _ = fixture(tmp_path)
    if invalid == "schema":
        evidence["texts"][0]["unexpected_field"] = True
    elif invalid == "region":
        evidence["source"]["region"] = [2, 0, 1, 20]
    else:
        evidence["source"]["units"] = "mm"
    write_json(path, evidence)
    output = tmp_path / "error.json"
    args = [sys.executable, "-m", "tools.drafting_rules.cli", "validate", "--before", str(before),
            "--after", str(after), "--source", str(source), "--evidence", str(path), "--output", str(output)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert json.loads(output.read_text())["status"] == "INPUT_ERROR"
