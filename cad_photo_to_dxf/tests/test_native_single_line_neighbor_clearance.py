"""Original source white gaps and actual saved-font relations; no OCR inference."""

from copy import deepcopy
import hashlib
import json

import ezdxf
import numpy as np
import pytest

from app.native_objects import cad_io, revision_resume
from app.native_objects import single_line_labels as labels
from app.native_objects import single_line_neighbor_clearance as clearance
from app.native_objects.circular_markers import _observe_seed
from app.native_objects.contracts import save_json
from app.native_objects.single_line_text_audit import cold_native_text_bindings
from tests.test_native_circular_contact_text_protection import _formal_text, _source
from tests.test_native_single_line_labels import _RawModel, _contract, _drawing, _engines


def _observe(tmp_path, monkeypatch, circle_x=130):
    gray, roi, box = _source(circle_x)
    partition, reason = labels._partition(gray, roi, box)
    assert reason is None
    upstream = tmp_path / "single_line_labels/upstream_completed_text.json"
    save_json(upstream, _contract(gray, roi, box))
    plan = {
        "id": "synthetic-white-gap", "region_ids": ["R1"], "source_partition": partition,
        "upstream_observations": {"snapshot": labels._file_record(upstream, tmp_path), "region_ids": ["R1"]},
    }
    _engines(monkeypatch, [("AB CD", 96)])
    observation = labels.recognize_single_line_label(
        gray, roi, plan, tmp_path / "single_line_labels/labels/proof",
        recognizer=_RawModel([("AB CD", 0.999)]), evidence_root=tmp_path,
    )
    return gray, roi, box, observation


def test_exact_previous_circle_130_fixture_retains_transcription_but_rejects_layout(tmp_path, monkeypatch):
    # This is the precise former positive fixture; it is retained as a negative,
    # not silently moved to evade its newly measured glyph/ring collision.
    gray, roi, _, observation = _observe(tmp_path, monkeypatch, circle_x=130)
    assert observation["transcription_accepted"] is True
    assert observation["evidence"]["decision"]["accepted"] is True
    assert observation["text"] == "AB CD"
    assert observation["accepted"] is False
    assert observation["reasons"] == ["NATIVE_TEXT_CLOSES_PROVED_SOURCE_ROUND_WHITE_GAP"]
    relation = observation["evidence"]["layout_adoption"]["relations"][0]
    assert relation["original_white_gap_proved"]
    assert relation["actual_font_touches_original_ring_ink"]
    replay = labels.verify_single_line_label_evidence(gray, roi, observation["evidence"], tmp_path)
    assert not replay["pass"] and replay["transcription_source_pass"]
    assert replay["reason"] == "SINGLE_LINE_SOURCE_WHITE_GAP_LAYOUT_REJECTED"
    resumed = revision_resume._replay_single_line_result(observation, gray, roi, tmp_path)
    assert resumed["transcription_accepted"] and not resumed["accepted"]
    assert resumed["pending_observation_not_adopted"]
    damaged = deepcopy(observation)
    damaged["evidence"].pop("layout_adoption")
    with pytest.raises(ValueError, match="LAYOUT_PROOF_MISSING"):
        revision_resume._replay_single_line_result(damaged, gray, roi, tmp_path)


def test_ordinary_refinement_does_not_create_text_or_transfer_source_for_rejected_layout(tmp_path, monkeypatch):
    gray, roi, box = _source(circle_x=130)
    original, pixels = _contract(gray, roi, box), gray.copy()
    before = deepcopy(original)
    _engines(monkeypatch, [("AB CD", 96)])
    result = labels.refine_single_line_labels(
        gray, original, tmp_path / "single_line_labels", roi=roi,
        recognizer=_RawModel([("AB CD", 0.999)]), evidence_root=tmp_path,
    )
    assert result["single_line_label_recovery"]["accepted_labels"] == 0
    assert result["single_line_label_recovery"]["pending_labels"] == 1
    assert result["regions"] == before["regions"] and result["groups"] == before["groups"]
    assert not any("single_line_recovery" in row for row in result["regions"])
    assert result["single_line_label_recovery"]["attempts"][0]["text"] == "AB CD"
    assert original == before and np.array_equal(gray, pixels)
    # Full source-circle and external line evidence remains unchanged. No
    # glyph ownership was transferred to a nonexistent adopted TEXT.
    part, reason = labels._partition(gray, roi, box)
    assert reason is None
    seed = part["text_contact_separation"]["independent_round_observations"][0]
    ring = _observe_seed(gray, roi, seed, ())
    assert ring["geometry_accepted"]
    assert np.all(gray[65, 152:245] == 0)


@pytest.mark.parametrize("field", ["insert", "height", "width", "rotation"])
def test_saved_clearance_inspects_actual_text_transform_after_mutation(tmp_path, monkeypatch, field):
    gray, roi, box = _source(circle_x=124)
    obj, _ = _formal_text(tmp_path, monkeypatch, gray, roi, box, "AB CD")
    path = tmp_path / "saved.dxf"
    cad_io.export_objects([obj], path, roi, 200, hashlib.sha256(gray.tobytes()).hexdigest())
    doc = ezdxf.readfile(path)
    good, source = cold_native_text_bindings(path, doc, gray, roi, 200, tmp_path)
    assert good[0]["pass"] and source[0]["pass"]
    entity = next(e for e in doc.modelspace() if e.dxftype() == "TEXT")
    if field == "insert":
        entity.dxf.insert = (entity.dxf.insert.x - 6 * 25.4 / 200, entity.dxf.insert.y, 0)
    elif field in ("height", "width"):
        setattr(entity.dxf, field, getattr(entity.dxf, field) * 1.25)
    else:
        entity.dxf.rotation = 10
    doc.saveas(path)
    metadata = json.loads(path.with_suffix(".objects.json").read_text())
    metadata["dxf_sha256"] = cad_io.sha(path)
    path.with_suffix(".objects.json").write_text(json.dumps(metadata))
    # The candidate and expected-layout receipts are deliberately unchanged.
    # The independent relation must inspect the actual saved transform anyway.
    candidates, source = cold_native_text_bindings(path, ezdxf.readfile(path), gray, roi, 200, tmp_path)
    assert not candidates[0]["pass"] and not source[0]["pass"]
    assert source[0]["source_replay"]["pass"]
    checked = source[0]["actual_saved_text_round_clearance"]
    assert not checked["pass"] and checked["relations"][0]["original_white_gap_proved"]


def test_unverified_partition_cannot_reach_saved_geometry_clearance(tmp_path, monkeypatch):
    gray, roi, box = _source(circle_x=124)
    obj, _ = _formal_text(tmp_path, monkeypatch, gray, roi, box, "AB CD")
    obj["source_evidence"]["single_line_recovery"]["source_partition"]["source_support_runs_y_x0_x1"] = []
    path = tmp_path / "invalid.dxf"
    cad_io.export_objects([obj], path, roi, 200, "synthetic")
    monkeypatch.setattr(clearance, "check_text_round_white_gaps", lambda *_: pytest.fail("unreplayed source reached contour inspection"))
    _, source = cold_native_text_bindings(path, ezdxf.readfile(path), gray, roi, 200, tmp_path)
    assert not source[0]["pass"]
    assert source[0]["actual_saved_text_round_clearance"]["reason"] == "SINGLE_LINE_CLEARANCE_SOURCE_NOT_REPLAYED"


@pytest.mark.parametrize("text", ["OAB", "0AB"])
def test_normal_O_or_zero_remains_glyph_not_independent_neighbor(tmp_path, monkeypatch, text):
    gray, roi, box, _ = _drawing(text)
    _, observation = _formal_text(tmp_path, monkeypatch, gray, roi, box, text)
    assert observation["accepted"]
    assert observation["evidence"]["layout_adoption"]["pass"]


def test_source_contact_and_self_owned_ring_do_not_require_a_white_gap():
    gray, roi, box = _source(circle_x=130)
    part, reason = labels._partition(gray, roi, box)
    assert reason is None
    seed = part["text_contact_separation"]["independent_round_observations"][0]
    ring = _observe_seed(gray, roi, seed, ())["source_evidence"]
    # Isolate this relation predicate with genuine existing source black ink.
    # Full recognition replay is separately required before any adoption.
    shared = deepcopy(part)
    shared["source_support_runs_y_x0_x1"] = ring["ring_support_runs_y_x0_x1"]
    shared["bbox_xyxy_px"] = ring["crop_bbox_xyxy_px"]
    rows = clearance._source_rounds(gray, roi, shared)
    assert rows and all(row["original_glyph_and_ring_touch"] for row in rows)
    checked = clearance.check_text_round_white_gaps(
        gray, roi, shared, {"text": "O", "insert": [0, 0, 0], "height": 3, "width": 1, "rotation": 0},
        clearance.native_font_path(), 200,
    )
    assert checked["pass"]
    assert checked["relations"][0]["relation"] == "ORIGINAL_SOURCE_CONTACT_OR_OWN_GLYPH_ALLOWED"


def test_missing_white_gap_producer_cannot_restore_completed_adoption():
    from tests.test_native_single_line_revision_resume import _producers

    producers = _producers()
    producers.pop("app.native_objects.single_line_neighbor_clearance")
    with pytest.raises(ValueError, match="SINGLE_LINE_PRODUCER_SET_INCOMPLETE"):
        revision_resume._producer_checks(producers)
