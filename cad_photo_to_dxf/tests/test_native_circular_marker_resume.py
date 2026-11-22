"""Completed assembly must carry the raw circular evidence to its new job."""

import hashlib
import json

import pytest

from app.native_objects.pipeline import _restore_circular_marker_evidence


def _case(tmp_path):
    source = tmp_path / "previous"
    output = tmp_path / "new"
    name = "circular_markers/characters/source-bound-id/glyph-p10.tsv"
    raw = source / name
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"immutable raw observation\n")
    completion = {"raw_evidence_files": [{
        "path": name, "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
    }], "objects": [], "summary": {"new_complete_markers": 0}}
    return source, output, raw, completion


def test_completed_circle_evidence_remains_portable_after_old_directory_removed(tmp_path):
    source, output, raw, completion = _case(tmp_path)
    expected = raw.read_bytes()
    _restore_circular_marker_evidence(source, output, completion)
    raw.unlink()
    assert (output / completion["raw_evidence_files"][0]["path"]).read_bytes() == expected
    assert json.loads((output / "circular_markers/circular_markers.json").read_text()) == completion


def test_changed_raw_character_evidence_is_not_promoted_by_prior_assembly(tmp_path):
    source, output, raw, completion = _case(tmp_path)
    raw.write_bytes(b"different transcription\n")
    with pytest.raises(ValueError, match="HASH_CHANGED"):
        _restore_circular_marker_evidence(source, output, completion)


@pytest.mark.parametrize("path", [
    "../outside.tsv", "/outside.tsv", "circular_markers/../../outside.tsv",
    "circular_markers\\outside.tsv", "text/previous-final-approval.json",
])
def test_circle_resume_rejects_outside_or_unrelated_evidence(tmp_path, path):
    source, output, _, completion = _case(tmp_path)
    completion["raw_evidence_files"][0]["path"] = path
    with pytest.raises(ValueError, match="PATH_INVALID"):
        _restore_circular_marker_evidence(source, output, completion)


def test_circle_resume_does_not_replace_a_different_current_observation(tmp_path):
    source, output, _, completion = _case(tmp_path)
    target = output / completion["raw_evidence_files"][0]["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"current evidence\n")
    with pytest.raises(ValueError, match="DESTINATION_ALREADY_DIFFERS"):
        _restore_circular_marker_evidence(source, output, completion)
    assert target.read_bytes() == b"current evidence\n"


@pytest.mark.parametrize("records", [None, []])
def test_missing_circle_raw_manifest_fails_closed(tmp_path, records):
    source, output, _, completion = _case(tmp_path)
    completion["raw_evidence_files"] = records
    with pytest.raises(ValueError, match="MANIFEST_MISSING"):
        _restore_circular_marker_evidence(source, output, completion)
