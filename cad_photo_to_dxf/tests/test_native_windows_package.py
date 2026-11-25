"""Protect portable OCR binding and actual saved-content smoke comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import ezdxf
import pytest

from app.core import packaged_runtime
from scripts import native_packaging
from scripts import prepare_windows_native_runtime as setup
from scripts.windows_native_smoke import (
    _checked_record,
    create_circular_fixture,
    create_curve_end_boundary_fixture,
    entity_geometry,
    inspect_circle_path_edit_isolation,
    inspect_circular_character_payloads,
    inspect_circular_fixture_source_gap,
    inspect_circular_members,
    inspect_curve_end_fixture_source_gap,
)


def make_resource_bundle(root: Path) -> Path:
    bundle = root / "resources/ocr/tesseract"
    files = {}
    for name in ("tesseract.exe", "tessdata/eng.traineddata", "LICENSE-Tesseract.txt", "LICENSE-tessdata.txt", "engine.dll"):
        data = ("synthetic transport fixture, never executed: " + name).encode()
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (bundle / "native-ocr.lock.json").write_text(json.dumps({
        "schema": "native-windows-ocr-resources-v1", "profile": "unit-test-nonexecutable",
        "files": files,
    }), encoding="utf-8")
    return bundle


def test_frozen_runtime_uses_verified_bundle_despite_author_environment(tmp_path, monkeypatch):
    bundle = make_resource_bundle(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "C:/author/private/tesseract.exe")
    monkeypatch.setenv("TESSDATA_PREFIX", "C:/author/private/models")
    result = packaged_runtime.configure_native_ocr()
    assert result["selection"] == "verified_application_bundle"
    assert Path(result["executable"]) == bundle / "tesseract.exe"
    assert Path(result["tessdata"]) == bundle / "tessdata"
    assert result["runtime_download"] is False


def test_frozen_missing_bundle_does_not_fall_back_to_host_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "host-tesseract")
    with pytest.raises(FileNotFoundError, match="NATIVE_BUNDLED_TESSERACT_MISSING"):
        packaged_runtime.configure_native_ocr()


def test_non_windows_frozen_runtime_keeps_existing_deployment_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "/opt/controlled/tesseract")
    assert packaged_runtime.configure_native_ocr()["selection"] == "source_deployment_configuration"


@pytest.mark.parametrize("name", ["tesseract.exe", "tessdata/eng.traineddata", "engine.dll", "LICENSE-tessdata.txt"])
def test_changed_bundled_runtime_data_or_license_is_rejected(tmp_path, name):
    bundle = make_resource_bundle(tmp_path)
    (bundle / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="RESOURCE_CHANGED"):
        packaged_runtime.verify_ocr_bundle(bundle)


def test_manifest_cannot_resolve_outside_bundle(tmp_path):
    bundle = make_resource_bundle(tmp_path)
    path = bundle / "native-ocr.lock.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["../../../outside"] = {"bytes": 0, "sha256": "0" * 64}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="RESOURCE_MISSING"):
        packaged_runtime.verify_ocr_bundle(bundle)


def test_unverified_installer_rejected_before_extraction_or_staging(tmp_path, monkeypatch):
    installer = tmp_path / "untrusted.exe"
    installer.write_bytes(b"not the pinned release")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: pytest.fail("unverified installer was extracted"))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="DOWNLOAD_IDENTITY_MISMATCH"):
        setup.prepare(output, installer=installer)
    assert not output.exists()


def test_packaged_provenance_includes_every_current_native_producer():
    root = Path(__file__).resolve().parents[1]
    files = set(native_packaging.source_evidence_files(root))
    assert set((root / "app/native_objects").glob("*.py")).issubset(files)
    assert root / "app/core/native_worker.py" in files
    assert root / "app/core/native_job_manager.py" in files
    assert root / "main.py" in files


def test_actual_geometry_comparison_detects_text_endpoint_and_block_member_change():
    document = ezdxf.new()
    line = document.modelspace().add_line((1, 2), (3, 4))
    text = document.modelspace().add_text("ROOM 17", dxfattribs={"height": 3})
    block = document.blocks.new("independent")
    member = block.add_line((0, 0), (4, 0))
    insert = document.modelspace().add_blockref("independent", (20, 20))
    line_before = entity_geometry(line, document)
    text_before = entity_geometry(text, document)
    block_before = entity_geometry(insert, document)
    line.dxf.end = (9, 4)
    text.dxf.text = "ROOM 19"
    member.dxf.end = (2, 0)
    assert entity_geometry(line, document) != line_before
    assert entity_geometry(text, document) != text_before
    assert entity_geometry(insert, document) != block_before


def _saved_circular_checker_fixture(tmp_path):
    """Checker-only synthetic evidence, never passed to recognition or adoption.

    Mutations below test the smoke's ability to reject wrong real DXF members.
    Only the separate ordinary CLI/EXE run can claim actual source recognition.
    """
    document = ezdxf.new("R2013")
    document.units = 4
    document.appids.new("I2CAD_NATIVE_V2")
    rows, checks, sweeps = [], [], []
    mm = 25.4 / 200

    def point(x, y):
        return x * mm, (480 - y) * mm

    def identify(entity, oid, kind):
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": oid, "kind": kind}))])

    for index, (cx, cy, character) in enumerate(((150, 150, "F"), (400, 150, "K"), (400, 330, None))):
        oid = "checker-circle-" + str(index)
        kind = "CIRCULAR_MARKER" if character else "CIRCLE"
        if character:
            block = document.blocks.new("independent-" + str(index))
            block.add_circle((0, 0), 25 * mm)
            block.add_text(character, dxfattribs={"height": 20 * mm})
            entity = document.modelspace().add_blockref(block.name, point(cx, cy))
        else:
            entity = document.modelspace().add_circle(point(cx, cy), 25 * mm)
        identify(entity, oid, kind)
        rows.append({"id": oid, "kind": kind, "source_evidence": {"components_complete": bool(character), "external_endpoint_contact_review": {"status": "NO_UNRESOLVED_OBSERVED_EXTERNAL_ENDPOINT", "pending_contacts": []}}, "geometry": {"text_geometry": {"text": character, "x": cx - 10, "y": cy + 11, "height_px": 22, "width_px": 20}} if character else {}})
        checks.append({"id": oid, "pass": True, "saved_candidate_checks": {"checker_test_only": True}, "ring_source": {"pass": True}, **({"character_source": {"pass": True}} if character else {})})
        sweeps.append({"id": oid, "type": "CIRCLE", "pass": True, "sampled_sweep_deg": 360.0, "samples": 4000, "tolerance_px": 2.5, "max_distance_px": 1.0})
        line = document.modelspace().add_line(point(cx + 25, cy), point(cx + 130, cy))
        identify(line, "checker-lead-" + str(index), "LINE")
        rows.append({"id": "checker-lead-" + str(index), "kind": "LINE"})
        sweeps.append({"id": "checker-lead-" + str(index), "type": "LINE", "pass": True, "source_fraction": 1.0, "maximum_gap_px": 0.0, "max_distance_px": 0.0})
    gap_line = document.modelspace().add_line(point(290, 330), point(371, 330))
    identify(gap_line, "checker-real-gap-line", "LINE")
    rows.append({"id": "checker-real-gap-line", "kind": "LINE"})
    sweeps.append({"id": "checker-real-gap-line", "type": "LINE", "pass": True, "source_fraction": 1.0, "maximum_gap_px": 0.0, "max_distance_px": 0.0})
    path = tmp_path / "checker-only.dxf"
    document.saveas(path)
    cold = {"circular_marker_source_checks": checks, "source_checks": sweeps, "circular_member_source_sampling": {"closed_circle_sweep_deg": 360.0, "maximum_sample_spacing_px": 0.05, "circle_and_character_evidence_replayed": True, "missing_or_unreadable_evidence_passes": False}}
    return ezdxf.readfile(path), {"objects": rows}, cold


def test_circular_smoke_requires_distinct_complete_blocks_and_separate_partial_boundary(tmp_path):
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    result = inspect_circular_members(document, objects, cold)
    assert result["complete_marker_count"] == 2
    assert result["partial_circle_boundary_count"] == 1
    assert result["complete_marker_characters"] == ["F", "K"]
    assert len(result["independent_external_line_ids"]) == 4
    assert result["all_attached_finite_geometry_contacts_circle"] is True
    assert result["all_attached_endpoints_exactly_on_circle"] is True
    assert len(result["protected_real_gap_line_checks"]) == 1
    assert result["protected_real_gap_line_checks"][0]["minimum_saved_geometry_gap_px"] == pytest.approx(4)
    blocks = [document.blocks.get(entity.dxf.name) for entity in document.modelspace().query("INSERT")]
    blocks[0].query("TEXT")[0].dxf.text = "Z"
    assert blocks[1].query("TEXT")[0].dxf.text == "K"
    with pytest.raises(AssertionError, match="character"):
        inspect_circular_members(document, objects, cold)


@pytest.mark.parametrize("damage", ["shared-block", "extra-block-line", "missing-text", "false-O-circle", "partial-as-complete", "external-relation-pending", "missing-ring-audit", "missing-character-audit", "partial-sweep", "duplicate-lead", "fragmented-lead", "unsupported-lead", "lead-beyond-shared-contact", "lead-enters-character-box", "gap-bridged", "gap-line-missing", "gap-line-duplicate", "extra-glyph-fragment", "extra-glyph-text", "radius"])
def test_circular_smoke_rejects_actual_saved_representation_and_evidence_regressions(tmp_path, damage):
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    inserts = list(document.modelspace().query("INSERT"))
    if damage == "shared-block":
        inserts[1].dxf.name = inserts[0].dxf.name
    elif damage == "extra-block-line":
        document.blocks.get(inserts[0].dxf.name).add_line((1, 0), (10, 0))
    elif damage == "missing-text":
        block = document.blocks.get(inserts[0].dxf.name)
        block.delete_entity(block.query("TEXT")[0])
    elif damage == "false-O-circle":
        entity = document.modelspace().add_circle((15, 20), 1)
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": "false-O", "kind": "CIRCLE"}))])
    elif damage == "partial-as-complete":
        next(row for row in objects["objects"] if row["kind"] == "CIRCLE")["source_evidence"]["components_complete"] = True
    elif damage == "external-relation-pending":
        objects["objects"][0]["source_evidence"]["external_endpoint_contact_review"] = {"status": "NEARBY_EXTERNAL_ENDPOINT_RELATION_PENDING", "pending_contacts": [{"reason": "unproved nearby relation"}]}
    elif damage == "missing-ring-audit":
        cold["circular_marker_source_checks"] = []
    elif damage == "missing-character-audit":
        cold["circular_marker_source_checks"][0].pop("character_source")
    elif damage == "partial-sweep":
        cold["source_checks"][0]["sampled_sweep_deg"] = 90
    elif damage == "duplicate-lead":
        document.modelspace().add_entity(document.modelspace().query("LINE")[0].copy())
    elif damage == "fragmented-lead":
        line = document.modelspace().query("LINE")[0]
        end = line.dxf.end
        middle = (line.dxf.start + end) / 2
        line.dxf.end = middle
        document.modelspace().add_line(middle, end)
    elif damage == "unsupported-lead":
        next(row for row in cold["source_checks"] if row["type"] == "LINE")["source_fraction"] = 0.9
    elif damage == "lead-beyond-shared-contact":
        line = document.modelspace().query("LINE")[0]
        line.dxf.start = (line.dxf.start.x - 8 * 25.4 / 200, line.dxf.start.y)
    elif damage == "lead-enters-character-box":
        objects["objects"][0]["geometry"]["text_geometry"].update(x=174, width_px=3)
    elif damage == "gap-bridged":
        line = document.modelspace().query("LINE")[-1]
        line.dxf.end = (375 * 25.4 / 200, line.dxf.end.y)
    elif damage == "gap-line-missing":
        document.modelspace().delete_entity(document.modelspace().query("LINE")[-1])
    elif damage == "gap-line-duplicate":
        document.modelspace().add_entity(document.modelspace().query("LINE")[-1].copy())
    elif damage == "extra-glyph-fragment":
        document.modelspace().add_line((18, 18), (18.5, 18.5))
    elif damage == "extra-glyph-text":
        document.modelspace().add_text("F", dxfattribs={"height": 2, "insert": (20, 40)})
    else:
        document.blocks.get(inserts[0].dxf.name).query("CIRCLE")[0].dxf.radius *= 1.25
    path = tmp_path / "mutated.dxf"
    document.saveas(path)
    with pytest.raises(AssertionError):
        inspect_circular_members(ezdxf.readfile(path), objects, cold)


def test_generated_circle_fixture_has_original_round_glyph_protection_and_no_hints(tmp_path):
    from PIL import Image

    font = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    create_circular_fixture(first, font)
    create_circular_fixture(second, font)
    assert first.read_bytes() == second.read_bytes()
    with Image.open(first) as image:
        assert image.size == (640, 480)
        assert image.crop((108, 310, 180, 348)).getextrema() == (0, 255)
        assert image.crop((390, 320, 410, 340)).getextrema() == (255, 255)
        assert image.getpixel((500, 330)) == 0
        assert image.getpixel((371, 330)) == image.getpixel((374, 330)) == 0
        assert all(image.getpixel((x, y)) == 255 for x in (372, 373) for y in (329, 330, 331))
    assert inspect_circular_fixture_source_gap(first)["source_gap_width_px"] == 2
    assert set(tmp_path.iterdir()) == {first, second}


def test_circular_lead_can_share_only_the_source_ring_contact_band(tmp_path):
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    line = document.modelspace().query("LINE")[0]
    line.dxf.start = (172.25 * 25.4 / 200, (480 - 150) * 25.4 / 200)
    check = next(row for row in cold["source_checks"] if row["type"] == "LINE")
    check["max_distance_px"] = 1.75
    result = inspect_circular_members(document, objects, cold)
    assert len(result["independent_external_line_ids"]) == 4
    report = result["independent_line_shared_contact_checks"][0]
    assert report["source_stroke_width_px"] == 3
    assert report["saved_source_budget_px"] == 2.5
    assert report["circle_radius_px"] == pytest.approx(25)
    assert report["saved_source_check"]["source_fraction"] == 1
    assert report["contact_kind"] == "existing_supported_ring_overlap"
    assert report["finite_geometry_intersections_px"]
    assert result["existing_supported_overlap_line_ids"] == ["checker-lead-0"]
    assert result["all_attached_endpoints_exactly_on_circle"] is False
    assert result["ordinary_O_and_zero_transcription_accuracy_claimed"] is False


@pytest.mark.parametrize("entity_type", ["LINE", "LWPOLYLINE"])
@pytest.mark.parametrize("positive_gap_px", [0.0001, 0.25, 1.5])
def test_circular_smoke_rejects_positive_finite_geometry_gap_inside_source_budget(
    tmp_path, entity_type, positive_gap_px
):
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    line = document.modelspace().query("LINE")[0]
    line.dxf.start = ((175 + positive_gap_px) * 25.4 / 200, line.dxf.start.y)
    if entity_type == "LWPOLYLINE":
        points = [line.dxf.start, (line.dxf.start + line.dxf.end) / 2, line.dxf.end]
        replacement = document.modelspace().add_lwpolyline([(point.x, point.y) for point in points])
        replacement.set_xdata("I2CAD_NATIVE_V2", line.get_xdata("I2CAD_NATIVE_V2"))
        document.modelspace().delete_entity(line)
        next(row for row in cold["source_checks"] if row["id"] == "checker-lead-0")["type"] = "LWPOLYLINE"
    path = tmp_path / "positive-gap.dxf"
    document.saveas(path)
    with pytest.raises(AssertionError, match="does not contact"):
        inspect_circular_members(ezdxf.readfile(path), objects, cold)


def test_circle_source_gap_checker_rejects_an_accidentally_filled_fixture(tmp_path):
    from PIL import Image

    font = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    source = tmp_path / "damaged-source.png"
    create_circular_fixture(source, font)
    with Image.open(source) as original:
        image = original.copy()
    image.putpixel((372, 330), 0)
    image.save(source)
    with pytest.raises(AssertionError, match="white source gap"):
        inspect_circular_fixture_source_gap(source)


@pytest.mark.parametrize("restored_gap_px", [-0.25, 0.0])
def test_new_certified_circle_endpoint_cannot_claim_preserved_old_overlap(
    tmp_path, restored_gap_px
):
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    line = document.modelspace().query("LINE")[0]
    line.dxf.start = ((175 + restored_gap_px) * 25.4 / 200, line.dxf.start.y)
    row = next(row for row in objects["objects"] if row["id"] == "checker-lead-0")
    row["source_evidence"] = {"circle_endpoint_contacts": {
        "schema": "native-direct-circle-end-contact-v2-observed-terminal-core",
        "ends": [{"circle_id": "checker-circle-0", "endpoint_number": 0, "restored_endpoint_px": [175 + restored_gap_px, 150], "circle_geometry": {"center": [150, 150], "radius_px": 25}}],
    }}
    path = tmp_path / "new-contact.dxf"
    document.saveas(path)
    if restored_gap_px:
        with pytest.raises(AssertionError, match="newly certified endpoint"):
            inspect_circular_members(ezdxf.readfile(path), objects, cold)
    else:
        report = inspect_circular_members(ezdxf.readfile(path), objects, cold)
        assert report["independent_line_shared_contact_checks"][0]["new_certified_endpoint_checked"] is True


@pytest.mark.parametrize("name", ["../outside.tsv", "/absolute.tsv", "C:/host/raw.tsv", "sub\\raw.tsv"])
def test_circular_raw_payload_reader_rejects_external_references(tmp_path, name):
    with pytest.raises(AssertionError, match="reference|outside"):
        _checked_record(tmp_path, {"path": name, "sha256": "0" * 64})


def test_circular_raw_payload_reader_requires_actual_file_bytes(tmp_path):
    path = tmp_path / "observation.tsv"
    path.write_bytes(b"original checker-only raw observation")
    record = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert _checked_record(tmp_path, record)[1] == path.read_bytes()
    path.write_bytes(b"changed checker-only raw observation")
    with pytest.raises(AssertionError, match="bytes differ"):
        _checked_record(tmp_path, record)


@pytest.mark.parametrize("tesseract,model,summary_model", [(0, 0, 0), (1, 0, 0), (0, 1, 1), (1, 1, 2)])
def test_circular_smoke_cannot_substitute_global_or_cached_recognition_calls(tmp_path, tesseract, model, summary_model):
    # A deliberately incomplete checker fixture: rejection must happen before
    # reading any image/model. This does not simulate a successful recognizer.
    source = tmp_path / "input.png"
    source.write_bytes(b"checker input, not an image")
    stage_root = tmp_path / "circular_markers"
    stage_root.mkdir()
    raw = stage_root / "character_result.json"
    raw.write_text(json.dumps({"new_Tesseract_calls": tesseract, "new_model_calls": model}))
    summary = {"new_Tesseract_calls": tesseract, "new_model_calls": summary_model}
    stage = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "summary": summary, "raw_evidence_files": [{"path": "circular_markers/character_result.json", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}]}
    (stage_root / "circular_markers.json").write_text(json.dumps(stage))
    pipeline = {"circular_marker_completion": summary, "cross_engine_text": {"actual_model_calls": 99}}
    with pytest.raises(AssertionError, match="real new Tesseract and model calls"):
        inspect_circular_character_payloads({}, {}, tmp_path, source, pipeline)


def _saved_curve_end_checker_fixture(tmp_path):
    """Artificial checker data only; ordinary CLI/EXE supplies real receipts."""
    document, objects, cold = _saved_circular_checker_fixture(tmp_path)
    mm = 25.4 / 200
    circle = document.modelspace().query("CIRCLE")[0]
    circle.dxf.radius = 22 * mm
    boundary = next(row for row in objects["objects"] if row["kind"] == "CIRCLE")
    boundary["source_evidence"].update(
        radial_fit={"measurement": "PAIRED_ORIGINAL_INK_STROKE_EDGES_V1",
                    "radial_error_measured_on": "PAIRED_STROKE_CENTERLINE",
                    "source_pixels_modified": False, "full_circle_source_fraction": 1.0,
                    "minimum_center_ink": 1.0, "clean_outer_rays": 90,
                    "p95_radial_error_px": 0.3, "max_radial_error_px": 0.4,
                    "checker_test_only": True},
        ring_geometry={"stroke_width_px": 5.0},
    )
    contact, gap = list(document.modelspace().query("LINE"))[2:]
    contact.dxf.start = (422 * mm, (480 - 330) * mm)
    contact.dxf.end = (536 * mm, (480 - 300) * mm)
    gap.dxf.end = (373 * mm, (480 - 330) * mm)
    path = tmp_path / "curve-end-checker-only.dxf"
    document.saveas(path)
    return path, ezdxf.readfile(path), objects, cold


def test_curve_end_fixture_really_triggers_paired_edges_and_keeps_source_gap(tmp_path):
    import numpy as np
    from PIL import Image
    from app.native_objects.circular_markers import discover_circular_markers, verify_circle_source_evidence

    font = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    old, source = tmp_path / "old.png", tmp_path / "curve-ends.png"
    create_circular_fixture(old, font)
    create_curve_end_boundary_fixture(source, font)
    original_bytes = source.read_bytes()
    create_curve_end_boundary_fixture(source, font)
    assert source.read_bytes() == original_bytes
    with Image.open(source) as image, Image.open(old) as previous:
        gray = np.asarray(image.convert("L"))
        assert image.crop((0, 0, 640, 280)).tobytes() == previous.crop((0, 0, 640, 280)).tobytes()
        assert image.crop((0, 280, 280, 480)).tobytes() == previous.crop((0, 280, 280, 480)).tobytes()
        assert image.getpixel((536, 300)) == 0
    assert inspect_curve_end_fixture_source_gap(source)["original_white_columns"] == [374, 375]
    report = discover_circular_markers(gray, [0, 0, 640, 480])
    boundaries = [row for row in report["rows"] if row["geometry_accepted"]
                  and row["source_evidence"]["radial_fit"].get("measurement") == "PAIRED_ORIGINAL_INK_STROKE_EDGES_V1"]
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert boundary["geometry"]["center"] == pytest.approx([400, 330], abs=0.2)
    assert boundary["geometry"]["radius_px"] == pytest.approx(22, abs=0.2)
    assert verify_circle_source_evidence(gray, [0, 0, 640, 480], boundary)["pass"]
    assert source.read_bytes() == original_bytes
    with Image.open(source) as image:
        damaged = image.copy()
    damaged.putpixel((374, 330), 0)
    damaged.save(source)
    with pytest.raises(AssertionError, match="white source gap"):
        inspect_curve_end_fixture_source_gap(source)


def test_curve_end_saved_checker_and_actual_edit_save_reopen_isolation(tmp_path):
    path, document, objects, cold = _saved_curve_end_checker_fixture(tmp_path)
    result = inspect_circular_members(document, objects, cold, curve_end_boundaries=True)
    assert result["paired_original_stroke_edge_fallback_executed"]
    assert result["uncertain_inner_character_not_counted_as_complete"]
    assert result["paired_edge_boundary_radius_px"] == pytest.approx(22)
    assert result["protected_real_gap_line_checks"][0]["minimum_saved_geometry_gap_px"] == pytest.approx(5)
    edits = inspect_circle_path_edit_isolation(
        path, tmp_path / "edits", result["independent_marker_for_edit_id"],
        result["independent_boundary_contact_path_id"],
    )
    assert edits["pass"] and edits["GUI_operations_claimed"] is False
    assert [row["action"] for row in edits["checks"]] == ["move-marker", "delete-marker", "change-marker-text", "delete-path"]
    assert all(row["unchanged_other_formal_objects"] == 6 for row in edits["checks"])


@pytest.mark.parametrize("damage", ["missing-fallback", "circle-shift", "missing-contact-path",
                                   "broken-contact", "bridged-gap", "duplicate-contact-path", "missing-saved-circle-sweep"])
def test_curve_end_saved_checker_rejects_missing_boundary_path_gap_or_actual_audit(tmp_path, damage):
    _, document, objects, cold = _saved_curve_end_checker_fixture(tmp_path)
    boundary = next(row for row in objects["objects"] if row["kind"] == "CIRCLE")
    lines = list(document.modelspace().query("LINE"))
    mm = 25.4 / 200
    if damage == "missing-fallback":
        boundary["source_evidence"]["radial_fit"]["measurement"] = "INNER_CONTOUR_ONLY"
    elif damage == "circle-shift":
        document.modelspace().query("CIRCLE")[0].translate(mm, 0, 0)
    elif damage == "missing-contact-path":
        document.modelspace().delete_entity(lines[2])
    elif damage == "broken-contact":
        lines[2].dxf.start = (423 * mm, (480 - 330) * mm)
    elif damage == "bridged-gap":
        lines[3].dxf.end = (378 * mm, (480 - 330) * mm)
    elif damage == "duplicate-contact-path":
        document.modelspace().add_entity(lines[2].copy())
    else:
        cold["source_checks"] = [row for row in cold["source_checks"] if row["id"] != boundary["id"]]
    path = tmp_path / "damaged-curve-end.dxf"
    document.saveas(path)
    with pytest.raises(AssertionError):
        inspect_circular_members(ezdxf.readfile(path), objects, cold, curve_end_boundaries=True)
