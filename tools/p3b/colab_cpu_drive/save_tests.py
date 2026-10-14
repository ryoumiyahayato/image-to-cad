"""Local filesystem fault tests. No Colab, Drive, models, fit or fabricated training data."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import drive_saver as saver


def run_tests(verified_metrics_bytes):
    tests = []
    actual_mkdtemp = tempfile.mkdtemp
    with tempfile.TemporaryDirectory(prefix="p3b-save-test-") as tmp, patch.object(
        saver.tempfile, "mkdtemp", side_effect=lambda **kwargs: actual_mkdtemp(dir=tmp, **kwargs)):
        mount = Path(tmp) / "simulated-mount"; mount.mkdir()
        outside = mount / "MyDrive/UNRELATED"; outside.mkdir(parents=True)
        (outside / "keep.txt").write_bytes(b"existing unrelated bytes")
        before = saver.save_hash(outside / "keep.txt")
        def expect_failure(name, operation):
            try:
                operation()
            except (ValueError, saver.SaveFailure, OSError):
                tests.append({"test": name, "status": "PASS", "scope": "LOCAL_SIMULATION_ONLY"})
            else:
                raise AssertionError("Failed to reject: " + name)
        expect_failure("unmounted initialization blocks", lambda: saver._initialize_store(mount, lambda: False, "unmounted"))
        session = saver._initialize_store(mount, lambda: True, "success")
        content = {"metrics.json": verified_metrics_bytes}
        local = saver.prepare_save_stage("C1", content, {"scope": "verified first-result JSON; no training"})
        completed = saver.save_stage(session, "C1", local)
        marker = json.loads(Path(completed["marker_path"]).read_text(encoding="utf-8"))
        assert marker["verification_scope"] == "LOCAL_SIMULATION_ONLY"
        for f in marker["files"]:
            p = Path(completed["marker_path"]).parent / f["name"]
            assert p.stat().st_size == f["size_bytes"] and saver.save_hash(p) == f["sha256"]
        tests.append({"test": "full local copy/readback/last completion", "status": "PASS", "scope": "LOCAL_SIMULATION_ONLY"})
        expect_failure("duplicate run_id cannot overwrite", lambda: saver._initialize_store(mount, lambda: True, "success"))
        expect_failure("repeat completed stage cannot overwrite", lambda: saver.save_stage(session, "C1", local))
        expect_failure("missing initialization blocks stage", lambda: saver.ensure_save_session(None))
        expect_failure("missing preceding stage blocks compute", lambda: saver.ensure_save_session(session, "B1"))
        expect_failure("path traversal run_id", lambda: saver._initialize_store(mount, lambda: True, "../escape"))
        fault = saver._initialize_store(mount, lambda: True, "copy-failure")
        fail_local = saver.prepare_save_stage("C1", content, {})
        with patch.object(saver, "_copy_new_checked", side_effect=OSError("simulated interrupted write")):
            expect_failure("write failure visible and blocks completion", lambda: saver.save_stage(fault, "C1", fail_local))
        assert fault.failed and fault.pending and Path(fault.pending["backup_zip"]).is_file()
        assert not list(Path(fault.run_dir).rglob("COMPLETE.json"))
        expect_failure("SAVE_FAILED blocks following computation", lambda: saver.ensure_save_session(fault))
        saver.retry_pending_save_only(fault, reason="local simulated write fault removed")
        assert fault.retry_used == 1 and "C1" in fault.completed
        tests.append({"test": "one save-only retry copies preserved bytes without computation", "status": "PASS", "scope": "LOCAL_SIMULATION_ONLY"})
        expect_failure("second retry prohibited", lambda: saver.retry_pending_save_only(fault, reason="again"))
        corrupt = saver._initialize_store(mount, lambda: True, "hash-mismatch")
        bad_local = saver.prepare_save_stage("C1", content, {})
        def copy_corrupt(source, destination):
            Path(destination).write_bytes(b"corrupted mounted readback bytes")
        with patch.object(saver, "_copy_new_checked", side_effect=copy_corrupt):
            expect_failure("hash mismatch stops without COMPLETE", lambda: saver.save_stage(corrupt, "C1", bad_local))
        assert not list(Path(corrupt.run_dir).rglob("COMPLETE.json"))
        Path(bad_local, "metrics.json").write_bytes(verified_metrics_bytes + b"\n")
        expect_failure("mutated local retry identity prohibited", lambda: saver.retry_pending_save_only(corrupt, reason="simulated fault removed"))
        gone = saver._initialize_store(mount, lambda: True, "lost-mount")
        gone.mount_probe = lambda: False
        expect_failure("lost mount after init blocks", lambda: saver.ensure_save_session(gone))
        changed = saver._initialize_store(mount, lambda: True, "changed-identity")
        Path(changed.run_dir, "run-identity.json").write_bytes(b"{}")
        expect_failure("altered run ownership blocks", lambda: saver.ensure_save_session(changed))
        forbidden = []
        def forbid(*args, **kwargs):
            forbidden.append(True)
            raise AssertionError("Training/evaluation must never run from saver")
        with patch.object(saver, "train_manual", forbid, create=True), patch.object(saver, "validate_manual", forbid, create=True):
            session2 = saver._initialize_store(mount, lambda: True, "no-compute")
            saver.save_stage(session2, "C1", saver.prepare_save_stage("C1", content, {}))
        assert not forbidden
        assert saver.save_hash(outside / "keep.txt") == before
        files = [p for p in mount.rglob("*") if p.is_file() and p != outside / "keep.txt"]
        assert all(p.is_relative_to(mount / saver.RUN_SUFFIX) for p in files)
        tests.append({"test": "simulation invokes no training/evaluation and writes no unrelated Drive directory", "status": "PASS", "scope": "LOCAL_SIMULATION_ONLY"})
    return tests
