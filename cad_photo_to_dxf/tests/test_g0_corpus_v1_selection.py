from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.g0_candidate_registry import load_registry
from scripts.g0_corpus_v1_selection import (
    REGISTRY_DIGEST,
    SCHEMA_VERSION,
    SelectionError,
    build_artifacts,
    canonical_json_bytes,
    load_locked_blind_ids,
    validate_split,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "docs" / "draftsman" / "corpus"
REGISTRY_PATH = CORPUS_ROOT / "g0_candidate_registry.jsonl"
SPLIT_PATH = CORPUS_ROOT / "g0_corpus_v1_split.json"
SCHEMA_PATH = CORPUS_ROOT / "g0_corpus_v1_split.schema.json"
REPORT_PATH = CORPUS_ROOT / "g0_selection_report.json"
DIGEST_PATH = CORPUS_ROOT / "g0_corpus_v1_digest.txt"


def _artifact() -> dict[str, object]:
    return json.loads(SPLIT_PATH.read_text(encoding="utf-8"))


def test_split_schema_and_authoritative_state() -> None:
    artifact = _artifact()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["authoritative"] is True
    assert artifact["freeze_status"] == "FROZEN"
    assert set(artifact) == set(schema["required"])
    assert artifact["counts"] == {
        "CORPUS_V1": 30,
        "DEV": 15,
        "LOCKED_BLIND": 8,
        "RESERVE": 15,
        "VALIDATION": 7,
    }


def test_exact_counts_no_overlap_and_all_ids_exist() -> None:
    artifact = _artifact()
    splits = artifact["splits"]
    assert {name: len(entries) for name, entries in splits.items()} == {
        "DEV": 15,
        "LOCKED_BLIND": 8,
        "RESERVE": 15,
        "VALIDATION": 7,
    }
    ids = [entry["source_group_id"] for entries in splits.values() for entry in entries]
    assert len(ids) == len(set(ids)) == 45
    registry_ids = {record["source_group_id"] for record in load_registry(REGISTRY_PATH)}
    assert set(ids) <= registry_ids
    corpus_ids = {
        entry["source_group_id"]
        for name in ("DEV", "VALIDATION", "LOCKED_BLIND")
        for entry in splits[name]
    }
    assert corpus_ids == set(artifact["corpus_v1_source_group_ids"])


def test_eligibility_and_source_family_leakage_gates() -> None:
    artifact = _artifact()
    entries = [entry for values in artifact["splits"].values() for entry in values]
    assert all(entry["eligibility"] in {"ELIGIBLE", "ELIGIBLE_WITH_ADVISORY"} for entry in entries)
    family_splits: dict[str, set[str]] = {}
    for split, values in artifact["splits"].items():
        for entry in values:
            family_splits.setdefault(entry["source_family_id"], set()).add(split)
    assert len(family_splits) == 45
    assert all(len(splits) == 1 for splits in family_splits.values())
    assert artifact["gates"]["source_family_leakage"] == []
    assert artifact["gates"]["ineligible_selected"] == []


def test_locked_blind_is_never_executed_and_requires_opt_in() -> None:
    artifact = _artifact()
    blind = artifact["splits"]["LOCKED_BLIND"]
    assert len(blind) == 8
    assert all(entry["blind_exposure_status"] == "NEVER_EXECUTED" for entry in blind)
    assert all(entry["source_group_id"].startswith("G0R2-") for entry in blind)
    legacy = json.loads(
        (CORPUS_ROOT / "legacy_g0b_provisional_split.json").read_text(encoding="utf-8")
    )
    legacy_ids = {entry["source_group_id"] for entry in legacy["entries"]}
    assert not legacy_ids.intersection(entry["source_group_id"] for entry in blind)
    with pytest.raises(SelectionError, match="explicit opt-in"):
        load_locked_blind_ids(SPLIT_PATH)
    assert load_locked_blind_ids(SPLIT_PATH, explicit_opt_in=True) == [
        entry["source_group_id"] for entry in blind
    ]


def test_selection_policy_and_digest_replay() -> None:
    records = load_registry(REGISTRY_PATH)
    artifact = _artifact()
    replay, report = build_artifacts(records, artifact["candidate_registry"]["path"])
    validate_split(artifact, records)
    assert canonical_json_bytes(replay) == SPLIT_PATH.read_bytes()
    assert canonical_json_bytes(report) == REPORT_PATH.read_bytes()
    assert hashlib.sha256(SPLIT_PATH.read_bytes()).hexdigest() == DIGEST_PATH.read_text(
        encoding="ascii"
    ).strip()


def test_registry_digest_mismatch_fails_closed() -> None:
    records = copy.deepcopy(load_registry(REGISTRY_PATH))
    assert records[0]["canonical_source_url"]
    records[0]["organization"] = "tampered"
    with pytest.raises(SelectionError, match="digest mismatch"):
        build_artifacts(records, REGISTRY_PATH.as_posix())
    assert _artifact()["candidate_registry"]["sha256"] == REGISTRY_DIGEST


def test_legacy_proposal_remains_non_authoritative() -> None:
    legacy = json.loads(
        (CORPUS_ROOT / "legacy_g0b_provisional_split.json").read_text(encoding="utf-8")
    )
    assert legacy["freeze_status"] == "NOT_FROZEN_ACQUISITION_PENDING"
    assert legacy["authoritative_frozen_digest"] is None
    assert legacy["provisional_manifest_sha256"] != DIGEST_PATH.read_text(
        encoding="ascii"
    ).strip()
