"""Synthetic contracts for a bounded diagnostic, without CAD-pass assertions."""

import hashlib
import json
import math
from pathlib import Path
import sys

import ezdxf
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from app.native_objects import cad_io
from export_annotation_group_checkpoint import signature, snapshot
from probe_librecad_mtext_layout import build_parser, create_probes


def fixture_files(tmp_path, native_selector="standard"):
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(cad_io.APPID)
    doc.layers.new("ANNOTATION")
    doc.layers.new("CONNECTIONS")
    doc.styles.new("SourceFont", dxfattribs={"font": "unrendered-source.ttf"})
    lines = ["ROW A", "ROW B", "ROW C"]
    boxes = [[12, 20, 72, 32], [10, 38, 70, 50], [17, 56, 77, 68]]
    source_lines = [{"bbox_xyxy_px": box, "width_px": 60} for box in boxes]
    rich = r"\P".join(r"\pxi0,l0,r0,ql;{\W0.8;" + line + "}" for line in lines)
    note = doc.modelspace().add_mtext(rich, dxfattribs={
        "insert": (10, 80, 0), "char_height": 12, "width": 69,
        "rotation": 27, "attachment_point": 1, "flow_direction": 1,
        "line_spacing_style": 2, "line_spacing_factor": 0.9,
        "style": "SourceFont", "layer": "ANNOTATION",
    })
    cad_io.mark(note, {"id": "synthetic-note", "kind": "MTEXT"})
    neighbor = doc.modelspace().add_lwpolyline(
        [(2, 10, 0, 0, 0.25), (6, 14, 0, 0, 0), (8, 16, 0, 0, 0)],
        dxfattribs={"layer": "CONNECTIONS", "color": 3},
    )
    cad_io.mark(neighbor, {"id": "synthetic-neighbor", "kind": "CONNECTION"})
    source = tmp_path / "source.dxf"
    cad_io.save_native_dxf(doc, source)
    cold = ezdxf.readfile(source)
    geometry = {
        "text": "\n".join(lines), "lines": lines, "x": 10, "y": 20,
        "height_px": 12, "width_px": 67, "line_pitch_px": 18,
        "rotation_deg_image": -27, "source_line_geometries": source_lines,
    }
    receipt = {
        "schema": "local-annotation-group-checkpoint-v1",
        "status": "PASS_LOCAL_COMPLETE_MTEXT_MOVE_DELETE_AND_PROCESS_COLD_READ",
        "group_id": "synthetic-note", "unit": "paper_mm", "dpi": 25.4,
        "checks": {"all_rows_complete_and_source_bound": True},
        "outputs": {"restored": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()}},
        "assembled_geometry": geometry,
        "ordered_source_rows": [{"id": f"r{index}", "text": line, "bbox_xyxy_px": box}
                                for index, (line, box) in enumerate(zip(lines, boxes))],
        "saved_mtext_signature": signature(cold.modelspace().query("MTEXT")[0]),
    }
    receipt_path = tmp_path / "layout.json"
    receipt_path.write_text(json.dumps(receipt))
    template = ezdxf.new("R2007")
    if native_selector in template.styles:
        template.styles.get(native_selector).dxf.font = native_selector + ".lff"
    else:
        template.styles.new(native_selector, dxfattribs={"font": native_selector + ".lff"})
    template.modelspace().add_mtext(r"\P".join(lines), dxfattribs={
        "style": native_selector, "char_height": 55, "width": 555,
        "rotation": 71, "line_spacing_factor": 1.25,
    })
    template_path = tmp_path / "native.dxf"
    template.saveas(template_path)
    return source, receipt_path, template_path, receipt


def test_probe_keeps_source_and_neighbors_and_only_varies_reference_width(tmp_path):
    source, receipt, template, data = fixture_files(tmp_path)
    input_bytes = {p: p.read_bytes() for p in (source, receipt, template)}
    original = ezdxf.readfile(source)
    old_note = original.modelspace().query("MTEXT")[0]
    old_style = signature(original.styles.get("Standard"))
    out = tmp_path / "probes"
    manifest = create_probes(source, receipt, template, out)
    assert manifest["status"] == "DIAGNOSTIC_NOT_ADOPTED"
    assert manifest["candidate_count"] == 2
    assert set(p.name for p in out.iterdir()) == {
        "C_native_plain.dxf", "D_reference_width.dxf", "probe_manifest.json"}
    assert {p: p.read_bytes() for p in input_bytes} == input_bytes
    c = ezdxf.readfile(out / "C_native_plain.dxf")
    d = ezdxf.readfile(out / "D_reference_width.dxf")
    note = c.modelspace().query("MTEXT")[0]
    assert len(c.modelspace()) == 2
    assert note.text == r"ROW A\PROW B\PROW C"
    assert note.plain_text() == old_note.plain_text()
    assert note.dxf.style == "standard"
    # A case-insensitive existing record is reused without altering its font,
    # even though the native template's ignored STYLE font field is different.
    assert signature(c.styles.get("Standard")) == old_style
    assert manifest["outputs"]["C_native_plain"]["native_font"]["style_record_added"] is False
    assert manifest["common_left_approximation"]["source_left_offsets_px"] == [2, 0, 7]
    assert manifest["common_left_approximation"]["per_row_common_left_error_px"] == [0, 2, -5]
    angle = math.radians(27)
    assert tuple(note.dxf.insert) == pytest.approx((10 + 2 * math.cos(angle), 80 + 2 * math.sin(angle), 0))
    for name in ("char_height", "rotation", "line_spacing_factor", "line_spacing_style",
                 "attachment_point", "flow_direction", "layer"):
        assert note.dxf.get(name) == old_note.dxf.get(name)
    assert note.dxf.width == 69
    assert d.modelspace().query("MTEXT")[0].dxf.width == 67
    first = snapshot(c, "synthetic-note")
    second = snapshot(d, "synthetic-note")
    first["entities"]["synthetic-note"]["attributes"].pop("width")
    second["entities"]["synthetic-note"]["attributes"].pop("width")
    assert first == second
    old_neighbor = original.modelspace().query("LWPOLYLINE")[0]
    assert signature(c.modelspace().query("LWPOLYLINE")[0]) == signature(old_neighbor)
    assert manifest["actual_CAD_layout"] == "NOT_MEASURED_BY_THIS_SCRIPT"
    assert manifest["original_source_audit_inherited"] is False


def test_missing_native_style_is_added_without_changing_existing_records(tmp_path):
    source, receipt, template, _ = fixture_files(tmp_path, native_selector="iso")
    before = {e.dxf.name: signature(e) for e in ezdxf.readfile(source).styles}
    out = tmp_path / "probes"
    result = create_probes(source, receipt, template, out)
    doc = ezdxf.readfile(out / "C_native_plain.dxf")
    assert {name: signature(doc.styles.get(name)) for name in before} == before
    assert doc.modelspace().query("MTEXT")[0].dxf.style == "iso"
    assert result["outputs"]["C_native_plain"]["native_font"]["style_record_added"] is True


@pytest.mark.parametrize("change,reason", [
    ("hash", "SOURCE_RESTORED_HASH"),
    ("content", "SOURCE_CONTENT_OR_LINE_ORDER_MISMATCH"),
    ("nonfinite", "NON_FINITE_SOURCE_GEOMETRY"),
    ("group_id", "SOURCE_REQUIRES_ONE_TARGET_NATIVE_MTEXT"),
])
def test_unbound_or_nonfinite_source_cannot_create_candidates(tmp_path, change, reason):
    source, receipt, template, data = fixture_files(tmp_path)
    if change == "hash":
        data["outputs"]["restored"]["sha256"] = "0" * 64
    elif change == "content":
        data["assembled_geometry"]["text"] = "DIFFERENT"
    elif change == "nonfinite":
        data["assembled_geometry"]["source_line_geometries"][0]["bbox_xyxy_px"][0] = float("nan")
    else:
        data["group_id"] = "unknown-source-group"
    receipt.write_text(json.dumps(data))
    out = tmp_path / "probes"
    with pytest.raises(ValueError, match=reason):
        create_probes(source, receipt, template, out)
    assert not out.exists()


@pytest.mark.parametrize("change,reason", [
    ("second_mtext", "NATIVE_TEMPLATE_REQUIRES_ONE_MTEXT"),
    ("content", "NATIVE_TEMPLATE_CONTENT_DIFFERS_FROM_BOUND_SOURCE"),
])
def test_native_template_must_be_one_matching_ordinary_note(tmp_path, change, reason):
    source, receipt, template, _ = fixture_files(tmp_path)
    doc = ezdxf.readfile(template)
    if change == "second_mtext":
        doc.modelspace().add_mtext("SECOND")
    else:
        doc.modelspace().query("MTEXT")[0].text = "DIFFERENT"
    doc.saveas(template)
    with pytest.raises(ValueError, match=reason):
        create_probes(source, receipt, template, tmp_path / "probes")


def test_cli_has_no_expected_answer_argument(tmp_path, capsys):
    source, receipt, template, _ = fixture_files(tmp_path)
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args([
            "--source-restored", str(source), "--source-layout-receipt", str(receipt),
            "--native-template", str(template), "--out-dir", str(tmp_path / "probes"),
            "--expected-text", "FORCED ANSWER",
        ])
    assert error.value.code == 2
    assert "unrecognized arguments: --expected-text" in capsys.readouterr().err
