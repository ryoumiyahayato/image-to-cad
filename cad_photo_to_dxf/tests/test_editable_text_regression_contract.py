from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from editable_text_regression_contract import (
    BASELINE_SOURCE_COMMIT,
    CANDIDATE_COMMIT,
    EDITABLE_TEXT_CONTRACT,
    PHASE12_CONTRACT,
    PHASE12_MANIFEST_BLOB,
    PHASE12_MANIFEST_PATH,
    REQUIRED_EQUAL_PARTITIONS,
    SUPERSEDED_CONTRACT_ERROR,
    Phase12ImmutableAnchor,
    _compact_page_summary,
    _materialize_commit,
    _parser,
    _write_evidence_bytes,
    compare_before_after,
    content_hash,
    file_sha256,
    load_json_from_commit,
    require_explicit_contract,
    select_baseline_manifest,
    validate_before_contract,
    validate_compact_baseline_integrity,
    validate_compact_page_summary,
    validate_fixture_hashes,
    verify_current_manifest_blob,
    verify_phase12_anchor,
)

BASELINE_DIR = PROJECT_ROOT / "validation" / "baselines" / EDITABLE_TEXT_CONTRACT


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _git(repository: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=check,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _anchor_repository(tmp_path: Path) -> tuple[Path, Phase12ImmutableAnchor]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Contract Test")
    _git(repository, "config", "user.email", "contract@example.invalid")
    manifest = repository / "cad_photo_to_dxf/tests/real_regression/manifest.json"
    _write_json(manifest, {"schema_version": 2, "documents": []})
    _git(repository, "add", manifest.relative_to(repository).as_posix())
    title = "phase-12 immutable test anchor"
    _git(repository, "commit", "-m", title)
    commit = _git(repository, "rev-parse", "HEAD")
    blob = _git(
        repository,
        "rev-parse",
        f"{commit}:cad_photo_to_dxf/tests/real_regression/manifest.json",
    )
    return repository, Phase12ImmutableAnchor(
        commit_sha=commit,
        manifest_blob_sha=blob,
        expected_commit_title=title,
        recorded_tag_name="baseline/phase12-test-anchor",
        tag_ref_status="absent",
        verification_timestamp="2026-07-31T00:00:00+00:00",
    )


def _editable_manifest() -> dict[str, object]:
    return {
        "schema_version": 2,
        "contract_version": EDITABLE_TEXT_CONTRACT,
        "baseline_source_commit": BASELINE_SOURCE_COMMIT,
        "documents": [],
    }


def _page() -> dict[str, object]:
    hashes = {
        key: content_hash({"partition": key})
        for key in (*REQUIRED_EQUAL_PARTITIONS, "text_geometry_hash")
    }
    protected_parts = {
        name: content_hash({"protected": name})
        for name in ("logo", "signature", "residual", "uncertain")
    }
    return {
        "page_id": "page-001",
        "eligible_count": 1,
        "native_text_count": 1,
        "replacement_unsafe_downgrade_count": 0,
        "source_outline_state": {
            "exists": True,
            "off": True,
            "frozen": True,
        },
        "dxf_audit_errors": 0,
        "read_save_read": {
            "passed": True,
            "audit_errors_after": 0,
        },
        "candidate_ids": ["page-001:000001"],
        "candidate_id_hash": content_hash(["page-001:000001"]),
        "ocr_content_hash": content_hash(["测试"]),
        "partition_hashes": hashes,
        "protected_content_part_hashes": protected_parts,
        "partition_payloads": {"text_geometry": [{"width_factor": 1.0}]},
        "full_structure_id": "before-full-id",
    }


def _compact_fixture_summary() -> dict[str, object]:
    before = _page()
    after = _page()
    for page in (before, after):
        page.update(
            {
                "fallback_count": 0,
                "source_outline_entity_count": 2,
                "text_symbol_entity_count": 1,
                "source_dimensions": [100, 200],
                "protected_content_part_hashes": {
                    name: content_hash({"protected": name})
                    for name in ("logo", "signature", "residual", "uncertain")
                },
            }
        )
    after["partition_hashes"] = dict(after["partition_hashes"])
    after["partition_hashes"]["text_geometry_hash"] = content_hash("changed")
    after["partition_payloads"] = {"text_geometry": [{"width_factor": 0.9}]}
    comparison = compare_before_after(before, after)
    return _compact_page_summary(
        page_id="page-001",
        phase12_document={
            "source_path": "tests/fixtures/page.png",
            "sha256": "a" * 64,
            "original_path": "tests/fixtures/source.pdf",
            "original_sha256": "b" * 64,
            "page": {"number": 1, "dpi": 600},
        },
        before=before,
        after=after,
        comparison=comparison,
        failure_reasons=[],
        raw_evidence_path="raw/pages/page-001.json",
        raw_evidence_sha256="c" * 64,
        raw_evidence_record_count=3,
    )


def test_phase12_commit_and_blob_anchor_pass(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    result = verify_phase12_anchor(repository, anchor)
    assert result["verified"] is True
    assert result["resolved_commit_sha"] == anchor.commit_sha
    assert result["observed_manifest_blob_sha"] == anchor.manifest_blob_sha


def test_modified_commit_sha_fails(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    with pytest.raises(ValueError, match="Git verification failed"):
        verify_phase12_anchor(repository, replace(anchor, commit_sha="0" * 40))


def test_modified_blob_sha_fails(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    with pytest.raises(ValueError, match="manifest blob mismatch"):
        verify_phase12_anchor(
            repository,
            replace(anchor, manifest_blob_sha="1" * 40),
        )


def test_missing_tag_still_verifies_commit_blob(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    assert _git(repository, "tag", "--list") == ""
    result = verify_phase12_anchor(repository, anchor)
    assert result["tag_ref_observed"] == "absent"


def test_local_legacy_tag_does_not_replace_remote_absent_status(
    tmp_path: Path,
) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    _git(repository, "tag", anchor.recorded_tag_name, anchor.commit_sha)
    result = verify_phase12_anchor(repository, anchor)
    assert result["tag_ref_observed"] == "absent"
    assert result["local_tag_ref_observed"] == "present"


def test_anchor_verification_never_creates_tag(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    before = _git(repository, "show-ref", "--tags", check=False)
    verify_phase12_anchor(repository, anchor)
    after = _git(repository, "show-ref", "--tags", check=False)
    assert before == after == ""


def test_anchor_is_immutable_and_not_auto_updated(tmp_path: Path) -> None:
    _repository, anchor = _anchor_repository(tmp_path)
    with pytest.raises(FrozenInstanceError):
        anchor.commit_sha = "2" * 40  # type: ignore[misc]


def test_current_manifest_must_match_immutable_blob(tmp_path: Path) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    assert verify_current_manifest_blob(
        repository,
        ref=anchor.commit_sha,
        expected_blob_sha=anchor.manifest_blob_sha,
    ) == anchor.manifest_blob_sha
    with pytest.raises(ValueError, match="Current manifest blob mismatch"):
        verify_current_manifest_blob(
            repository,
            ref=anchor.commit_sha,
            expected_blob_sha="3" * 40,
        )


def test_historical_manifest_is_read_from_commit_not_working_tree(
    tmp_path: Path,
) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    manifest = repository / anchor.manifest_path
    manifest.write_text('{"schema_version": 999}\n', encoding="utf-8")
    assert load_json_from_commit(
        repository,
        commit_sha=anchor.commit_sha,
        manifest_path=anchor.manifest_path,
    ) == {"schema_version": 2, "documents": []}


def test_historical_commit_materialization_is_git_directory_read_only(
    tmp_path: Path,
) -> None:
    repository, anchor = _anchor_repository(tmp_path)
    destination = tmp_path / "historical-tree"
    _materialize_commit(
        repository,
        commit_sha=anchor.commit_sha,
        destination=destination,
    )
    assert json.loads(
        (destination / anchor.manifest_path).read_text(encoding="utf-8")
    ) == {"schema_version": 2, "documents": []}
    assert not (repository / ".git" / "worktrees").exists()


def test_phase12_manifest_file_is_unchanged_on_candidate_commit() -> None:
    repository = PROJECT_ROOT.parent
    assert verify_current_manifest_blob(
        repository,
        ref=CANDIDATE_COMMIT,
        manifest_path=PHASE12_MANIFEST_PATH,
        expected_blob_sha=PHASE12_MANIFEST_BLOB,
    ) == PHASE12_MANIFEST_BLOB
    assert not subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff",
            "--quiet",
            "--",
            PHASE12_MANIFEST_PATH,
        ],
        check=False,
    ).returncode


def test_missing_contract_is_rejected() -> None:
    with pytest.raises(ValueError, match="contract version is required"):
        require_explicit_contract(None)


def test_cli_requires_explicit_contract() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "select",
                "--scope",
                "architecture-safety",
                "--architecture-manifest",
                "architecture.json",
                "--editable-text-manifest",
                "editable.json",
            ]
        )


def test_versioned_baseline_integrity_and_phase12_manifest_separation() -> None:
    manifest = json.loads(
        (BASELINE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["contract_version"] == EDITABLE_TEXT_CONTRACT
    assert manifest["baseline_source_commit"] == BASELINE_SOURCE_COMMIT
    assert manifest["candidate_commit"] == CANDIDATE_COMMIT
    assert manifest["document_configuration_count"] == 12
    assert manifest["unique_page_count"] == 10
    anchor = manifest["phase12_immutable_anchor"]
    assert anchor["commit_sha"] == "6f5f69329aabf0bd3a7eda84baf66eb1959bdcba"
    assert anchor["manifest_path"] == PHASE12_MANIFEST_PATH
    assert anchor["manifest_blob_sha"] == PHASE12_MANIFEST_BLOB
    assert anchor["expected_commit_title"] == (
        "perf: complete final acceptance baseline (phase 12)"
    )
    assert anchor["recorded_tag_name"] == (
        "baseline/phase12-final-acceptance-2026-07-30"
    )
    assert anchor["tag_ref_status"] == "absent"
    assert anchor["contract_identifier"] == PHASE12_CONTRACT
    assert not (
        BASELINE_DIR / "tests" / "real_regression" / "manifest.json"
    ).exists()
    comparison = json.loads(
        (BASELINE_DIR / "comparison-report.json").read_text(encoding="utf-8")
    )
    assert comparison["phase12_architecture_to_editable_before"]["passed"]
    assert comparison["editable_before_to_p1b_candidate"]["passed"]


def test_versioned_baseline_has_one_page_record_per_configuration() -> None:
    manifest = json.loads(
        (BASELINE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    page_files = {
        path.stem for path in (BASELINE_DIR / "pages").glob("*.json")
    }
    manifest_ids = {str(item["page_id"]) for item in manifest["documents"]}
    assert len(manifest_ids) == 12
    assert page_files == manifest_ids
    for page_id in sorted(manifest_ids):
        payload = json.loads(
            (BASELINE_DIR / "pages" / f"{page_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["page_id"] == page_id
        assert payload["evidence_mode"] == "compact"
        assert payload["baseline_source_commit"] == BASELINE_SOURCE_COMMIT
        assert payload["candidate_commit"] == CANDIDATE_COMMIT
        assert payload["changed_partitions"] == ["text_geometry_hash"]
        assert payload["passed"] is True
        assert "partition_payloads" not in payload
        assert "candidate_ids" not in payload
        assert set(REQUIRED_EQUAL_PARTITIONS).issubset(
            payload["partition_hashes"]["baseline"]
        )
        assert {"logo", "signature", "residual", "uncertain"}.issubset(
            payload["protected_content_part_hashes"]["baseline"]
        )


def test_compact_and_raw_representations_preserve_partition_hashes() -> None:
    summary = _compact_fixture_summary()
    raw_page = {
        "editable_text_baseline": {
            "partition_hashes": summary["partition_hashes"]["baseline"]
        },
        "p1b_candidate": {
            "partition_hashes": summary["partition_hashes"]["candidate"]
        },
    }
    assert summary["partition_hashes"]["baseline"] == raw_page[
        "editable_text_baseline"
    ]["partition_hashes"]
    assert summary["partition_hashes"]["candidate"] == raw_page["p1b_candidate"][
        "partition_hashes"
    ]
    assert summary["changed_partitions"] == ["text_geometry_hash"]


def test_compact_summary_has_no_full_vertices_or_repeated_entity_arrays() -> None:
    summary = _compact_fixture_summary()
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "partition_payloads" not in summary
    assert "candidate_ids" not in summary
    assert "ocr_contents" not in summary
    assert "text_geometry_before" not in summary
    assert "text_geometry_after" not in summary
    assert "points" not in rendered


def test_compact_summary_schema_is_complete() -> None:
    validate_compact_page_summary(_compact_fixture_summary())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text_semantic_hash", "changed-semantic"),
        ("non_text_structure_hash", "changed-non-text"),
        ("source_sha256", "changed-source"),
        ("full_raw_evidence_sha256", "changed-raw"),
    ],
    ids=("text-semantic", "non-text", "source", "raw-evidence"),
)
def test_compact_baseline_hash_tamper_fails(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    target = tmp_path / "baseline"
    shutil.copytree(BASELINE_DIR, target)
    page_path = target / "pages" / "environment-plan-page-003-150dpi.json"
    payload = json.loads(page_path.read_text(encoding="utf-8"))
    if field in {"text_semantic_hash", "non_text_structure_hash"}:
        payload[field]["baseline"] = value
    else:
        payload[field] = value
    _write_json(page_path, payload)
    with pytest.raises(ValueError, match="compact page summary SHA256 mismatch"):
        validate_compact_baseline_integrity(target / "manifest.json")


def test_compact_protected_subhash_tamper_fails(tmp_path: Path) -> None:
    target = tmp_path / "baseline"
    shutil.copytree(BASELINE_DIR, target)
    page_path = target / "pages" / "environment-plan-page-003-150dpi.json"
    payload = json.loads(page_path.read_text(encoding="utf-8"))
    payload["protected"]["signature"]["baseline"] = "changed-protected"
    _write_json(page_path, payload)
    with pytest.raises(ValueError, match="compact page summary SHA256 mismatch"):
        validate_compact_baseline_integrity(target / "manifest.json")


def test_raw_evidence_gzip_decompresses_to_original_sha(tmp_path: Path) -> None:
    entry = _write_evidence_bytes(tmp_path, "pages/page-001.json", b"full raw")
    raw_path = tmp_path / entry["logical_name"]
    compressed_path = tmp_path / entry["compressed_logical_name"]
    with gzip.open(compressed_path, "rb") as handle:
        restored = handle.read()
    assert restored == raw_path.read_bytes()
    assert hashlib.sha256(restored).hexdigest() == entry["sha256"]
    assert file_sha256(compressed_path) == entry["compressed_sha256"]


def test_missing_external_raw_evidence_does_not_block_integrity_validation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline"
    shutil.copytree(BASELINE_DIR, target)
    (target / "raw-evidence-manifest.json").unlink()
    result = validate_compact_baseline_integrity(target / "manifest.json")
    assert result["passed"] is True


def test_compact_summary_records_regeneration_command_and_tool_version() -> None:
    summary = _compact_fixture_summary()
    assert "--evidence-mode compact" in summary["regeneration_command"]
    assert "--raw-evidence-dir" in summary["regeneration_command"]
    assert summary["regeneration_tool_version"]


def test_compact_baseline_has_12_configurations_and_10_pages() -> None:
    manifest = json.loads(
        (BASELINE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["document_configuration_count"] == 12
    assert manifest["unique_page_count"] == 10
    assert len(manifest["documents"]) == 12


def test_compact_baseline_keeps_600dpi_page() -> None:
    page = BASELINE_DIR / "pages" / "warehouse-index-page-001-600dpi.json"
    payload = json.loads(page.read_text(encoding="utf-8"))
    assert payload["dpi"] == 600
    assert payload["passed"] is True


def test_compact_baseline_size_and_file_hygiene_limits() -> None:
    files = [path for path in BASELINE_DIR.rglob("*") if path.is_file()]
    assert sum(path.stat().st_size for path in files) < 20 * 1024 * 1024
    assert max(path.stat().st_size for path in files) <= 20 * 1024 * 1024


def test_phase12_contract_is_rejected_for_editable_text_geometry(
    tmp_path: Path,
) -> None:
    architecture = tmp_path / "architecture.json"
    editable = tmp_path / "editable.json"
    _write_json(architecture, {"schema_version": 2})
    _write_json(editable, _editable_manifest())
    with pytest.raises(ValueError, match="Phase-12 routing expectations"):
        select_baseline_manifest(
            contract=PHASE12_CONTRACT,
            architecture_manifest=architecture,
            editable_text_manifest=editable,
            validation_scope="editable-text-geometry",
        )


def test_legacy_phase12_baseline_paths_are_unchanged() -> None:
    repository = PROJECT_ROOT.parent
    changed = _git(
        repository,
        "diff",
        "--name-only",
        CANDIDATE_COMMIT,
        "--",
        "tests/real_regression/manifest.json",
        "validation/final-acceptance",
        "validation/system-refactor-baselines",
    )
    assert changed == ""


def test_editable_text_contract_selects_5f7846e_manifest(
    tmp_path: Path,
) -> None:
    architecture = tmp_path / "architecture.json"
    editable = tmp_path / "editable.json"
    _write_json(architecture, {"schema_version": 2})
    _write_json(editable, _editable_manifest())
    selected = select_baseline_manifest(
        contract=EDITABLE_TEXT_CONTRACT,
        architecture_manifest=architecture,
        editable_text_manifest=editable,
        validation_scope="editable-text-geometry",
    )
    assert selected == editable


def test_phase12_and_editable_text_contracts_coexist(tmp_path: Path) -> None:
    architecture = tmp_path / "tests" / "real_regression" / "manifest.json"
    editable = (
        tmp_path
        / "validation"
        / "baselines"
        / EDITABLE_TEXT_CONTRACT
        / "manifest.json"
    )
    _write_json(architecture, {"schema_version": 2})
    old_bytes = architecture.read_bytes()
    _write_json(editable, _editable_manifest())
    assert select_baseline_manifest(
        contract=PHASE12_CONTRACT,
        architecture_manifest=architecture,
        editable_text_manifest=editable,
        validation_scope="architecture-safety",
    ) == architecture
    assert architecture.read_bytes() == old_bytes
    assert architecture.resolve() != editable.resolve()


def test_baseline_source_commit_must_match_manifest(tmp_path: Path) -> None:
    architecture = tmp_path / "architecture.json"
    editable = tmp_path / "editable.json"
    _write_json(architecture, {"schema_version": 2})
    payload = _editable_manifest()
    payload["baseline_source_commit"] = "deadbeef"
    _write_json(editable, payload)
    with pytest.raises(ValueError, match="source commit mismatch"):
        select_baseline_manifest(
            contract=EDITABLE_TEXT_CONTRACT,
            architecture_manifest=architecture,
            editable_text_manifest=editable,
            validation_scope="editable-text-geometry",
        )


def test_input_fixture_hash_change_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "fixture.png"
    source.write_bytes(b"original")
    manifest = {
        "documents": [
            {
                "id": "page-001",
                "source_path": "fixture.png",
                "sha256": content_hash("not-the-file"),
                "original_path": "fixture.png",
                "original_sha256": content_hash("not-the-file"),
            }
        ]
    }
    with pytest.raises(ValueError, match="input fixture hash changed"):
        validate_fixture_hashes(manifest, tmp_path)


def test_text_semantic_hash_change_fails() -> None:
    before = _page()
    after = _page()
    after["partition_hashes"] = dict(after["partition_hashes"])
    after["partition_hashes"]["text_semantic_hash"] = content_hash("changed")
    result = compare_before_after(before, after)
    assert result["passed"] is False
    assert "text_semantic_hash changed" in result["errors"]


def test_non_text_structure_hash_change_fails() -> None:
    before = _page()
    after = _page()
    after["partition_hashes"] = dict(after["partition_hashes"])
    after["partition_hashes"]["non_text_structure_hash"] = content_hash(
        "changed"
    )
    result = compare_before_after(before, after)
    assert result["passed"] is False
    assert "non_text_structure_hash changed" in result["errors"]


def test_text_geometry_hash_change_enters_geometry_comparison() -> None:
    before = _page()
    after = _page()
    after["partition_hashes"] = dict(after["partition_hashes"])
    after["partition_hashes"]["text_geometry_hash"] = content_hash("changed")
    after["partition_payloads"] = {
        "text_geometry": [{"width_factor": 0.91}]
    }
    result = compare_before_after(before, after)
    assert result["passed"] is True
    assert result["text_geometry_changed"] is True
    assert result["text_geometry_before"] != result["text_geometry_after"]


def test_full_structure_id_change_is_not_an_equality_gate() -> None:
    before = _page()
    after = _page()
    after["full_structure_id"] = "after-full-id"
    result = compare_before_after(before, after)
    assert result["passed"] is True
    assert result["full_structure_id_changed"] is True


def test_source_outline_state_change_fails() -> None:
    before = _page()
    after = _page()
    after["partition_hashes"] = dict(after["partition_hashes"])
    after["partition_hashes"]["source_outline_hash"] = content_hash(
        {"off": False, "frozen": True}
    )
    result = compare_before_after(before, after)
    assert result["passed"] is False
    assert "source_outline_hash changed" in result["errors"]


def test_protected_content_subpart_change_fails() -> None:
    before = _page()
    after = _page()
    after["protected_content_part_hashes"] = dict(
        after["protected_content_part_hashes"]
    )
    after["protected_content_part_hashes"]["signature"] = content_hash(
        "changed"
    )
    result = compare_before_after(before, after)
    assert result["passed"] is False
    assert "protected_content.signature changed" in result["errors"]


def test_before_contract_rejects_replacement_safe_gate() -> None:
    page = _page()
    page["replacement_unsafe_downgrade_count"] = 1
    errors = validate_before_contract(page)
    assert "replacement_safe still gates native TEXT" in errors


def test_error_message_names_historical_phase12_contract() -> None:
    assert "Phase-12 routing expectations are historical" in (
        SUPERSEDED_CONTRACT_ERROR
    )
