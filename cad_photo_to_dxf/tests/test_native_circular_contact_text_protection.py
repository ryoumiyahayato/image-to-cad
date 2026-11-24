"""A verified text box may include independent original ring/character ink.

Raw engine records are controlled; source partition, raw replay, circular
geometry and whole-object adoption are real. No OCR/model inference executes.
"""

from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
import pytest

from app.native_objects import circular_marker_adoption as adoption
from app.native_objects import single_line_labels as labels
from app.native_objects.circular_markers import _mask_from_runs, _protected_ring_conflicts
from app.native_objects.contracts import save_json
from tests.test_native_single_line_labels import _RawModel, _contract, _drawing, _engines


def _source(circle_x=124):
    gray = np.full((180, 360), 255, np.uint8)
    cv2.putText(gray, "AB     CD", (30, 105), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 1, cv2.LINE_8)
    yy, xx = np.nonzero(gray < 192)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    cv2.circle(gray, (circle_x, 65), 20, 0, 3)
    cv2.line(gray, (circle_x - 5, 55), (circle_x - 5, 80), 0, 1)
    cv2.line(gray, (circle_x - 5, 55), (circle_x + 5, 55), 0, 1)
    cv2.line(gray, (circle_x - 5, 65), (circle_x + 4, 65), 0, 1)
    cv2.line(gray, (circle_x + 20, 65), (245, 65), 0, 1)
    return gray, [0, 0, 360, 180], box


def _formal_text(tmp_path, monkeypatch, gray, roi, box, text):
    partition, reason = labels._partition(gray, roi, box)
    assert partition is not None and reason is None
    snapshot = _contract(gray, roi, box)
    upstream = tmp_path / "single_line_labels/upstream_completed_text.json"
    save_json(upstream, snapshot)
    plan = {
        "id": "synthetic-source-label", "region_ids": ["R1"],
        "source_partition": partition,
        "upstream_observations": {
            "snapshot": labels._file_record(upstream, tmp_path), "region_ids": ["R1"],
        },
    }
    _engines(monkeypatch, [(text, 96)])
    result = labels.recognize_single_line_label(
        gray, roi, plan, tmp_path / "single_line_labels/labels/proof",
        recognizer=_RawModel([(text, 0.999)]), evidence_root=tmp_path,
    )
    assert result["accepted"], result["reasons"]
    obj = {
        "id": "formal-whole-label", "kind": "TEXT", "layer": "ANNOTATION",
        "geometry": deepcopy(result["geometry"]),
        "source_evidence": {
            "bbox_xyxy_px": list(result["bbox_xyxy_px"]),
            "single_line_recovery": deepcopy(result["evidence"]),
        },
    }
    return obj, result


def _character(gray, roi, row, output_dir, *, dpi, evidence_root=None):
    a, b, c, d = row["glyph_bbox_xyxy_px"]
    return {
        "accepted": True,
        "text_geometry": {"text": "F", "x": a, "y": d, "height_px": d - b, "width_px": c - a},
        "evidence": {"scope": "synthetic character adoption stub; no OCR accuracy claim"},
        "reasons": [], "new_Tesseract_calls": 0, "new_model_calls": 0,
    }


def test_source_glyph_protection_retains_neighbor_ring_and_its_complete_character(
    tmp_path, monkeypatch
):
    gray, roi, box = _source()
    obj, observation = _formal_text(tmp_path, monkeypatch, gray, roi, box, "AB CD")
    before, source_before = deepcopy(obj), gray.copy()
    monkeypatch.setattr(adoption, "recognize_circle_character", _character)
    # A later responsibility mask can be broader. The accepted source row
    # must use its replayed complete glyph partition in both protection paths.
    region = {
        "id": "accepted-source-region", "accepted": True, "text": "AB CD",
        "bbox_xyxy_px": observation["bbox_xyxy_px"],
        "single_line_recovery": observation["evidence"],
        "compact_source_ink_mask": {"runs_y_x0_x1": [[80, 30, 221]]},
    }
    result = adoption.complete_circular_markers(
        gray, roi, hashlib.sha256(gray.tobytes()).hexdigest(), [obj],
        tmp_path / "circular_markers", dpi=200, text_regions={"regions": [region]},
    )
    assert len(result["objects"]) == 1
    marker = result["objects"][0]
    assert marker["kind"] == "CIRCULAR_MARKER"
    assert marker["geometry"]["text_geometry"]["text"] == "F"
    assert not result["retired_ids"] and obj == before
    assert np.array_equal(gray, source_before)
    # The font box overlaps both ring ink and the very bottom of the inner
    # character. The separate original glyph support decides both questions.
    assert box[1] < marker["source_evidence"]["glyph_bbox_xyxy_px"][3]
    assert any(
        row["reason"] == "OVERLAPPING_TEXT_BOX_HAS_SEPARATE_REPLAYED_ORIGINAL_GLYPH_SUPPORT"
        for row in marker["source_evidence"]["whole_object_retirement"]["unchanged_contacts"]
    )
    discovered = json.loads((tmp_path / "circular_markers/circular_marker_discovery.json").read_text())
    assert all(row["source_partition_replay_pass"] for row in discovered["formal_text_protection"])


@pytest.mark.parametrize("damage", ["missing_proof", "empty_runs", "native_content", "native_position", "raw_file"])
def test_missing_changed_or_unbound_text_support_keeps_conservative_box_protection(
    tmp_path, monkeypatch, damage
):
    gray, roi, box = _source()
    obj, _ = _formal_text(tmp_path, monkeypatch, gray, roi, box, "AB CD")
    if damage == "missing_proof":
        obj["source_evidence"].pop("single_line_recovery")
    elif damage == "empty_runs":
        obj["source_evidence"]["single_line_recovery"]["source_partition"]["source_support_runs_y_x0_x1"] = []
    elif damage == "native_content":
        obj["geometry"]["text"] = "AB CE"
    elif damage == "native_position":
        obj["geometry"]["x"] += 1
    else:
        record = obj["source_evidence"]["single_line_recovery"]["tesseract_views"][0]["raw_tsv"]
        (tmp_path / record["path"]).write_text("changed raw evidence")
    monkeypatch.setattr(
        adoption, "recognize_circle_character",
        lambda *_args, **_kwargs: pytest.fail("unproved formal glyph protection must reject before OCR"),
    )
    result = adoption.complete_circular_markers(
        gray, roi, hashlib.sha256(gray.tobytes()).hexdigest(), [obj],
        tmp_path / "circular_markers", dpi=200,
    )
    assert not result["objects"] and not result["retired_ids"]
    assert "RING_OVERLAPS_PROTECTED_FORMAL_GLYPH" in str(result["decisions"])


@pytest.mark.parametrize("text", ["OAB", "0AB"])
def test_replayed_ordinary_O_and_zero_source_still_owns_its_entire_outline(
    tmp_path, monkeypatch, text
):
    gray, roi, box, _ = _drawing(text)
    obj, observation = _formal_text(tmp_path, monkeypatch, gray, roi, box, text)
    protection = adoption._formal_text_protection(
        [obj], None, gray=gray, roi=roi, evidence_root=tmp_path,
    )
    assert protection[0]["source_partition_replay_pass"]
    component = observation["evidence"]["source_partition"]["components"][0]
    outline = _mask_from_runs(component["source_runs_y_x0_x1"], roi)
    assert outline.any()
    assert _protected_ring_conflicts(outline, roi[:2], protection) == [obj["id"]]
