"""Whole-object circular marker integration using a stubbed recognition result.

These tests exercise adoption responsibility, not OCR accuracy.  Actual engine
evidence and the saved CIRCLE/TEXT audit have separate production regressions.
"""

from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
import pytest

from app.native_objects import circular_marker_adoption as adoption
from app.native_objects.circular_markers import discover_circular_markers


ROI = [0, 0, 180, 180]


def _source():
    image = np.full((180, 180), 255, np.uint8)
    cv2.circle(image, (80, 80), 20, 0, 3)
    cv2.line(image, (75, 72), (75, 88), 0, 2)
    cv2.line(image, (75, 72), (85, 72), 0, 2)
    cv2.line(image, (75, 80), (82, 80), 0, 2)
    cv2.line(image, (100, 80), (145, 80), 0, 2)
    return image


def _character(gray, roi, row, output_dir, *, dpi, evidence_root=None, recognizer=None):
    box = row["glyph_bbox_xyxy_px"]
    return {"accepted": True,
            "text_geometry": {"text": "F", "x": box[0], "y": box[3],
                              "width_px": box[2] - box[0], "height_px": box[3] - box[1],
                              "rotation_deg_image": 0.0},
            "evidence": {"schema": "artificial-approved-character-contract-stub"},
            "reasons": [], "new_Tesseract_calls": 0, "new_model_calls": 0}


@pytest.fixture(autouse=True)
def _stub_recognition(monkeypatch):
    monkeypatch.setattr(adoption, "recognize_circle_character", _character)


def _run(tmp_path, prior=(), *, gray=None, text_regions=None, callback=None):
    gray = _source() if gray is None else gray
    return adoption.complete_circular_markers(
        gray, ROI, hashlib.sha256(gray.tobytes()).hexdigest(), list(prior), tmp_path,
        dpi=200, text_regions=text_regions, progress_callback=callback,
    )


def _ring_geometry(gray=None):
    gray = _source() if gray is None else gray
    return next(row["geometry"] for row in discover_circular_markers(gray, ROI)["rows"] if row["geometry_accepted"])


def _ring_chord(*, kind="LINE", block=False):
    circle = _ring_geometry()
    center, radius = np.asarray(circle["center"]), circle["radius_px"]
    angles = np.deg2rad([210, 225])
    points = center + radius * np.column_stack((np.cos(angles), np.sin(angles)))
    line = {"start": points[0].tolist(), "end": points[1].tolist()}
    if block:
        return {"id": "existing-wall", "kind": "WALL_SEGMENT", "geometry": {"members": [{"kind": "LINE", "geometry": line}]}, "source_evidence": {}}
    if kind == "CONNECTION_PATH":
        return {"id": "old-ring-path", "kind": kind,
                "geometry": {"points": points.tolist(), "bulges": [0, 0]}, "source_evidence": {}}
    return {"id": "old-ring-line", "kind": "LINE", "geometry": line, "source_evidence": {}}


def test_complete_marker_is_one_object_with_independent_genuine_members(tmp_path):
    updates = []
    result = _run(tmp_path, callback=updates.append)
    (marker,) = result["objects"]
    assert marker["kind"] == "CIRCULAR_MARKER"
    assert marker["layer"] == "CIRCULAR_MARKERS"
    assert set(marker["geometry"]) == {"circle_geometry", "text_geometry"}
    assert marker["geometry"]["text_geometry"]["text"] == "F"
    assert marker["source_evidence"]["components_complete"]
    assert not marker["source_evidence"]["external_connections_owned"]
    assert result["summary"]["new_complete_markers"] == 1
    assert result["summary"]["new_formal_objects"] == 1
    assert result["retired_ids"] == []
    assert updates[-1]["complete"]
    saved = json.loads((tmp_path / "circular_markers.json").read_text())
    assert saved["objects"] == result["objects"]


def test_stage_manifest_binds_saved_evidence_with_portable_paths_and_no_self_hash(tmp_path):
    stage = tmp_path / "circles"
    stage.mkdir()
    raw = stage / "characters" / "raw-result.json"
    raw.parent.mkdir()
    raw.write_text('{"original":"frozen-source-evidence"}')
    result = _run(stage)
    records = result["raw_evidence_files"]
    assert {entry["path"] for entry in records} == {
        "circles/circular_marker_discovery.json",
        "circles/adoption_progress.json",
        "circles/characters/raw-result.json",
    }
    assert all("\\" not in record["path"] for record in records)
    for record in records:
        assert hashlib.sha256((tmp_path / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    assert "circles/circular_markers.json" not in {entry["path"] for entry in records}


def test_external_connection_is_preserved_separately_without_splitting_or_retirement(tmp_path):
    line = {"id": "independent-external-line", "kind": "LINE",
            "geometry": {"start": [100, 80], "end": [145, 80]}, "source_evidence": {}}
    before = deepcopy(line)
    result = _run(tmp_path, [line])
    assert result["summary"]["new_complete_markers"] == 1
    assert result["retired_ids"] == []
    assert line == before
    assert result["prior_objects_sha256_before"] == result["prior_objects_sha256_after"]
    assert "independent-external-line" not in str(result["objects"][0]["geometry"])


@pytest.mark.parametrize("kind", ["LINE", "CONNECTION_PATH"])
def test_complete_old_ring_fragment_is_retired_once_with_whole_member_certificate(tmp_path, kind):
    fragment = _ring_chord(kind=kind)
    result = _run(tmp_path, [fragment])
    assert result["summary"]["new_complete_markers"] == 1
    assert result["retired_ids"] == [fragment["id"]]
    (certificate,) = result["retirement_records"]
    assert certificate["pass"]
    assert certificate["replacement_member_role"] == "circle_boundary"
    assert certificate["old_entity_remaining_intervals"] == []
    assert not certificate["partial_old_retirement"]
    assert certificate["all_old_samples_in_same_member_source"]


def test_old_character_stroke_is_retired_only_after_complete_text_approval(tmp_path):
    fragment = {"id": "old-character-stroke", "kind": "LINE",
                "geometry": {"start": [75, 73], "end": [75, 87]}, "source_evidence": {}}
    result = _run(tmp_path, [fragment])
    assert result["retired_ids"] == [fragment["id"]]
    assert result["retirement_records"][0]["replacement_member_role"] == "interior_character"


def test_uncertain_character_keeps_old_inner_stroke_and_counts_only_partial_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(adoption, "recognize_circle_character", lambda *args, **kwargs: {
        "accepted": False, "text_geometry": None, "evidence": None,
        "reasons": ["INDEPENDENT_RAW_CHARACTER_CONFLICT"],
    })
    fragment = {"id": "old-character-stroke", "kind": "LINE",
                "geometry": {"start": [75, 73], "end": [75, 87]}, "source_evidence": {}}
    result = _run(tmp_path, [fragment])
    assert result["summary"]["new_complete_markers"] == 0
    assert result["summary"]["new_partial_boundaries"] == 1
    assert result["retired_ids"] == []
    assert result["objects"][0]["kind"] == "CIRCLE"
    assert result["objects"][0]["layer"] == "CIRCULAR_MARKERS"
    assert not result["objects"][0]["source_evidence"]["components_complete"]


def test_existing_block_member_is_never_partially_retired_for_new_circle(tmp_path):
    result = _run(tmp_path, [_ring_chord(block=True)])
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert result["uncertainties"][0]["status"] == "BOUNDARY_WHOLE_OBJECT_RESPONSIBILITY_PENDING"


def test_old_path_with_outside_source_responsibility_cannot_be_retired(tmp_path):
    old = _ring_chord(kind="CONNECTION_PATH")
    old["source_evidence"]["source_path_points"] = [[60, 70], [20, 20]]
    result = _run(tmp_path, [old])
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert "OLD_PATH_SOURCE_HAS_UNREPLACED_OUTSIDE_CONTENT" in str(result["uncertainties"])


def test_mixed_curve_cannot_be_split_to_remove_its_circle_part(tmp_path):
    circle = _ring_geometry()
    center, radius = np.asarray(circle["center"]), circle["radius_px"]
    angles = np.deg2rad(np.linspace(200, 250, 30))
    points = center + radius * np.column_stack((np.cos(angles), np.sin(angles)))
    points = np.vstack([points, [20, 20]])
    old = {"id": "mixed-old-path", "kind": "CONNECTION_PATH",
           "geometry": {"points": points.tolist(), "bulges": [0] * len(points)}, "source_evidence": {}}
    result = _run(tmp_path, [old])
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert "OLD_CURVE_MIXES_RING_AND_UNREPLACED_OUTSIDE_CONTENT" in str(result["uncertainties"])


def test_existing_formal_inner_text_is_kept_and_not_duplicated(tmp_path):
    text = {"id": "already-correct-text", "kind": "TEXT",
            "geometry": {"text": "F", "x": 73, "y": 90, "height_px": 20, "width_px": 14},
            "source_evidence": {}}
    result = _run(tmp_path, [text])
    assert result["retired_ids"] == []
    assert result["summary"]["new_complete_markers"] == 0
    assert result["summary"]["new_partial_boundaries"] == 1
    assert "EXISTING_FORMAL_TEXT_IS_NOT_RETIRED_OR_DUPLICATED" in str(result["objects"])


def test_formal_text_box_overlapping_ring_prevents_geometry_adoption_before_ocr(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No OCR needed for source-owned formal text")
    monkeypatch.setattr(adoption, "recognize_circle_character", forbidden)
    text = {"id": "existing-glyph", "kind": "TEXT",
            "geometry": {"text": "O", "x": 55, "y": 105, "height_px": 50, "width_px": 50},
            "source_evidence": {}}
    result = _run(tmp_path, [text])
    assert result["objects"] == []
    assert result["retired_ids"] == []


def test_already_present_marker_has_no_second_circle_or_extra_ocr_call(tmp_path, monkeypatch):
    original = _run(tmp_path / "first")["objects"][0]
    monkeypatch.setattr(adoption, "recognize_circle_character", lambda *args, **kwargs: pytest.fail("repeated existing marker OCR"))
    result = _run(tmp_path / "second", [original])
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert result["decisions"][0]["status"] == "EXISTING_COMPLETE_BOUNDARY_RETAINED_NO_DUPLICATE"


def test_duplicate_old_identifiers_fail_before_any_retirement(tmp_path):
    line = {"id": "duplicate", "kind": "LINE", "geometry": {"start": [1, 1], "end": [2, 2]}}
    with pytest.raises(ValueError, match="IDENTITIES_NOT_UNIQUE"):
        _run(tmp_path, [line, deepcopy(line)])


def test_stale_discovery_pass_cannot_bypass_current_source_replay(tmp_path, monkeypatch):
    gray = _source()
    observations = discover_circular_markers(gray, ROI)
    observations["rows"][0]["source_evidence"]["crop_sha256"] = "0" * 64
    monkeypatch.setattr(adoption, "discover_circular_markers", lambda *args, **kwargs: observations)
    monkeypatch.setattr(adoption, "recognize_circle_character", lambda *args, **kwargs: pytest.fail("stale source OCR"))
    result = _run(tmp_path, gray=gray)
    assert result["objects"] == []
    assert result["retired_ids"] == []
    assert result["decisions"][0]["status"] == "CURRENT_BOUNDARY_SOURCE_RECHECK_FAILED"
