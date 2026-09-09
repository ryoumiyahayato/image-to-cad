from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import g0_corpus_v1_acquisition as acquisition

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "docs" / "draftsman" / "corpus"
REGISTRY_PATH = CORPUS_ROOT / "g0_candidate_registry.jsonl"
SPLIT_PATH = CORPUS_ROOT / "g0_corpus_v1_split.json"
SPLIT_DIGEST_PATH = CORPUS_ROOT / "g0_corpus_v1_digest.txt"
MANIFEST_PATH = CORPUS_ROOT / "g0_corpus_v1_acquisition_manifest.json"
SCHEMA_PATH = CORPUS_ROOT / "g0_corpus_v1_acquisition_manifest.schema.json"
REPORT_PATH = CORPUS_ROOT / "G0_ACQUISITION_REPORT.md"


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_authoritative_inputs_and_digest_binding() -> None:
    records, split = acquisition.validate_authoritative_inputs(
        REGISTRY_PATH, SPLIT_PATH, SPLIT_DIGEST_PATH
    )
    assert len(records) == 99
    assert split["authoritative"] is True
    assert hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest() == acquisition.REGISTRY_DIGEST
    assert hashlib.sha256(SPLIT_PATH.read_bytes()).hexdigest() == acquisition.SPLIT_DIGEST


def test_manifest_schema_counts_and_coverage() -> None:
    manifest = _manifest()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(manifest) == set(schema["required"])
    assert manifest["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert len(manifest["source_groups"]) == schema["properties"]["source_groups"]["minItems"]
    acquisition.validate_manifest(manifest)
    assert manifest["summary"]["source_groups"] == 30
    assert manifest["summary"]["acquisition_attempted"] == 30
    assert manifest["summary"]["provenance_coverage"] == 30
    assert manifest["summary"]["governance_coverage"] == 30


def test_manifest_membership_matches_frozen_split() -> None:
    manifest = _manifest()
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    expected = set(split["corpus_v1_source_group_ids"])
    actual = {entry["source_group_id"] for entry in manifest["source_groups"]}
    assert actual == expected
    assert manifest["authoritative_split_modified"] is False


def test_sha256_metadata_and_local_paths() -> None:
    manifest = _manifest()
    acquisition.verify_local_files(manifest, REPOSITORY_ROOT)
    paths: list[str] = []
    hashes: list[str] = []
    for entry in manifest["source_groups"]:
        for file in entry["files"]:
            paths.append(file["local_relative_path"])
            hashes.append(file["sha256"])
            assert len(file["sha256"]) == 64
            assert file["byte_size"] > 0
    assert len(paths) == len(set(paths))
    assert len(hashes) == len(set(hashes))
    assert len(paths) == manifest["summary"]["sha256_coverage"]


def test_locked_blind_default_check_does_not_read_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    original = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
        if "locked-blind" in path.as_posix():
            raise AssertionError("ordinary manifest validation read LOCKED_BLIND bytes")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    acquisition.validate_manifest(manifest)
    blind = [entry for entry in manifest["source_groups"] if entry["split"] == "LOCKED_BLIND"]
    assert len(blind) == 8
    assert all(entry["runtime_executed"] is False for entry in blind)
    assert all(entry["blind_exposure_status"] == "NEVER_EXECUTED" for entry in blind)


def test_duplicate_path_and_file_identity_rejected() -> None:
    manifest = _manifest()
    acquired = [entry for entry in manifest["source_groups"] if entry["files"]]
    if len(acquired) < 2:
        pytest.skip("requires two acquired source files")
    duplicate_path = copy.deepcopy(manifest)
    acquired_copy = [entry for entry in duplicate_path["source_groups"] if entry["files"]]
    acquired_copy[1]["files"][0]["local_relative_path"] = acquired_copy[0]["files"][0][
        "local_relative_path"
    ]
    with pytest.raises(acquisition.AcquisitionError, match="duplicate local"):
        acquisition.validate_manifest(duplicate_path)
    duplicate_identity = copy.deepcopy(manifest)
    acquired_copy = [entry for entry in duplicate_identity["source_groups"] if entry["files"]]
    acquired_copy[1]["files"][0]["sha256"] = acquired_copy[0]["files"][0]["sha256"]
    with pytest.raises(acquisition.AcquisitionError, match="duplicate file identity"):
        acquisition.validate_manifest(duplicate_identity)


def test_existing_file_hash_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "local-artifacts/draftsman/corpus-v1/dev/TEST-GROUP/TEST-GROUP.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"%PDF-1.4\nexisting\n%%EOF\n")
    record = {
        "source_group_id": "TEST-GROUP",
        "governance_status": "PUBLIC_DOWNLOAD_CLEAR",
        "canonical_source_url": "https://example.invalid/source.pdf",
        "retrieval_url": "https://example.invalid/source.pdf",
        "governance_or_access_notes": "test",
    }

    def fake_download(url: str, path: Path, timeout: int) -> tuple[str, int]:
        del url, timeout
        path.write_bytes(b"%PDF-1.4\nchanged\n%%EOF\n")
        return "SUCCESS", 200

    monkeypatch.setattr(acquisition, "_download", fake_download)
    monkeypatch.setattr(
        acquisition,
        "inspect_file",
        lambda path: {
            "detected_format": "PDF",
            "mime_type": "application/pdf",
            "integrity_check": "TEST_PASS",
            "page_count": 1,
            "encrypted": False,
        },
    )
    prior = {
        "attempted_at_utc": "2026-09-09T00:00:00Z",
        "files": [
            {
                "sha256": "0" * 64,
                "local_relative_path": existing.relative_to(tmp_path).as_posix(),
            }
        ],
    }
    entry = acquisition.acquire_entry(record, "DEV", tmp_path / acquisition.MATERIAL_ROOT, tmp_path, prior, 1)
    assert entry["acquisition_state"] == "SOURCE_BYTES_CHANGED"
    assert existing.read_bytes() == b"%PDF-1.4\nexisting\n%%EOF\n"


def test_registry_or_split_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    registry.write_bytes(REGISTRY_PATH.read_bytes() + b"\n")
    with pytest.raises(acquisition.AcquisitionError, match="registry digest"):
        acquisition.validate_authoritative_inputs(registry, SPLIT_PATH, SPLIT_DIGEST_PATH)
    digest = tmp_path / "digest.txt"
    digest.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(acquisition.AcquisitionError, match="split digest"):
        acquisition.validate_authoritative_inputs(REGISTRY_PATH, SPLIT_PATH, digest)


def test_deterministic_manifest_and_report_serialization() -> None:
    manifest = _manifest()
    assert MANIFEST_PATH.read_bytes() == acquisition.canonical_json_bytes(manifest)
    assert REPORT_PATH.read_text(encoding="utf-8") == acquisition.build_report(manifest)


def test_source_bytes_are_not_tracked_by_git() -> None:
    result = subprocess.run(
        ["git", "ls-files", "local-artifacts/draftsman/corpus-v1"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
