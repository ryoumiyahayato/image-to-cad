"""Historical recovery survives normal main advancement and feature changes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def recovery_repository(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    remote = tmp_path / "remote.git"

    def run(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    run("init", "-b", "main")
    run("config", "user.name", "Recovery contract test")
    run("config", "user.email", "recovery-test@example.invalid")
    (root / "baseline.txt").write_text("original baseline\n")
    (root / "duplicate.txt").write_text("recoverable historical file\n")
    run("add", ".")
    run("commit", "-m", "historical source")
    source = run("rev-parse", "HEAD")
    protected = [{"path": "baseline.txt", "mode": "100644",
                  "blob_sha": run("rev-parse", "HEAD:baseline.txt")}]
    removed = {"path": "duplicate.txt", "mode": "100644",
               "blob_sha": run("rev-parse", "HEAD:duplicate.txt")}
    run("rm", "duplicate.txt")
    run("commit", "-m", "reviewed duplicate cleanup")
    run("init", "--bare", str(remote))
    run("remote", "add", "origin", str(remote))
    run("push", "origin", "main")
    record = {"schema": "test-historical-recovery", "source_commit": source,
              "deleted_files": [removed], "deleted_file_bytes": 28,
              "protected_files": protected,
              "protected_manifest_sha256": hashlib.sha256(json.dumps(
                  protected, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "deleted_branches": [], "retained_original_tags": [],
              "after_snapshot": {"branches": [{"name": "main", "sha": source}]}}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(record))
    path = Path(__file__).resolve().parents[2] / "maintenance/verify_cleanup_20261120.py"
    spec = importlib.util.spec_from_file_location("cleanup_recovery_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.MANIFEST = root, manifest
    return module, run, root, remote, record


def test_normal_main_advance_keeps_historical_recovery(recovery_repository):
    module, run, root, _, _ = recovery_repository
    (root / "new_feature.txt").write_text("new legitimate work\n")
    run("add", "new_feature.txt")
    run("commit", "-m", "normal main advance")
    run("push", "origin", "main")
    result = module.verify(remote=True, strict_current=True)
    assert result["passed"], result["failures"]
    assert result["remote"]["historical_branch_recovery"][0]["currently_recoverable_from"] == ["refs/heads/main"]


def test_feature_edit_does_not_claim_historical_data_loss(recovery_repository):
    module, run, root, _, _ = recovery_repository
    (root / "baseline.txt").write_text("reviewed later implementation\n")
    run("add", "baseline.txt")
    run("commit", "-m", "future implementation")
    run("push", "origin", "main")
    result = module.verify(remote=True)
    assert result["passed"], result["failures"]
    assert result["current_tree_changes_not_historical_data_loss"]
    assert not module.verify(strict_current=True)["passed"]


def test_archive_ref_can_replace_retired_branch(recovery_repository):
    module, run, _, remote, record = recovery_repository
    run("tag", "archive/test", record["source_commit"])
    run("push", "origin", "refs/tags/archive/test")
    subprocess.check_call(["git", "--git-dir", str(remote), "update-ref", "-d", "refs/heads/main"])
    result = module.verify(remote=True)
    assert result["passed"], result["failures"]
    assert result["remote"]["historical_branch_recovery"][0]["currently_recoverable_from"] == ["refs/tags/archive/test"]


def test_no_advertised_recovery_ref_is_a_real_failure(recovery_repository):
    module, _, _, remote, _ = recovery_repository
    subprocess.check_call(["git", "--git-dir", str(remote), "update-ref", "-d", "refs/heads/main"])
    result = module.verify(remote=True)
    assert not result["passed"]
    assert any("not reachable" in value for value in result["failures"])
