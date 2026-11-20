"""Default product routing, worker dispatch and preserved compatibility controls."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from main import build_parser, run_headless


def test_default_headless_uses_managed_native_worker_and_exports(tmp_path, monkeypatch):
    from app.core import native_job_manager

    calls = []
    task = tmp_path / "jobs" / "entry-test"
    attempt = task / "attempts" / "0001"
    attempt.mkdir(parents=True)
    (attempt / "manager_resources.json").write_text("{}")
    state = {
        "job_id": "entry-test",
        "status": "QUEUED",
        "stage": "QUEUED",
        "progress": 0,
        "algorithm": {"git": {"commit": "test-commit", "worktree_dirty": False}},
        "attempt_directory": str(attempt),
    }

    class Manager:
        def __init__(self, jobs_root):
            self.jobs_root = Path(jobs_root)

        def create(self, request):
            calls.append(("create", request))
            return dict(state)

        def start(self, job_id):
            calls.append(("start", job_id))
            return {**state, "status": "COMPLETED_WITH_ISSUES"}

        def shutdown(self, *, cancel_running):
            assert not cancel_running

        def export(self, job_id, output):
            calls.append(("export", job_id))
            output.write_text("test-saved-result")
            companion = output.with_suffix(".native")
            companion.mkdir()
            (companion / "result.png").write_bytes(b"saved-preview")
            (companion / "result.objects.json").write_text(json.dumps({"objects": []}))
            return {
                "dxf_path": str(output),
                "evidence_dir": str(companion),
                "manifest_path": str(output.with_suffix(".export.json")),
            }

    monkeypatch.setattr(native_job_manager, "NativeJobManager", Manager)
    args = build_parser().parse_args(
        [
            "--headless",
            "--input",
            str(tmp_path / "source.png"),
            "--roi",
            "0",
            "0",
            "100",
            "80",
            "--dpi",
            "200",
            "--output",
            str(tmp_path / "result.dxf"),
            "--jobs-dir",
            str(tmp_path / "jobs"),
        ]
    )
    assert args.mode == "native-objects"
    assert run_headless(args) == 0
    request = calls[0][1]
    assert request["roi"] == [0, 0, 100, 80]
    assert request["limits"] == {
        "CPU_seconds": 7200,
        "wall_seconds": 7200,
        "RSS_MiB": 3072,
        "temporary_MiB": 8192,
    }
    assert "cache_dir" not in request and "validation_controls" not in request
    assert [row[0] for row in calls] == ["create", "start", "export"]


@pytest.mark.parametrize(
    "extra,message",
    [
        ([], "--roi"),
        (["--roi", "0", "0", "10", "10"], "--dpi"),
        (
            [
                "--roi",
                "0",
                "0",
                "10",
                "10",
                "--dpi",
                "200",
                "--crop",
                "0",
                "0",
                "10",
                "10",
            ],
            "--mode legacy",
        ),
        (
            [
                "--roi",
                "0",
                "0",
                "10",
                "10",
                "--dpi",
                "200",
                "--native-cache",
                "old-whitelist",
            ],
            "external caches",
        ),
    ],
)
def test_native_entry_rejects_missing_or_cross_mode_contracts(extra, message):
    args = build_parser().parse_args(
        ["--headless", "--input", "not-opened.png", *extra]
    )
    with pytest.raises(ValueError, match=message):
        run_headless(args)


def test_worker_dispatch_runs_before_gui_or_input_requirement(monkeypatch):
    import main
    from app.core import native_worker

    seen = []
    monkeypatch.setattr(
        native_worker, "worker_run", lambda path: seen.append(path) or 17
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--native-worker", "request.json"])
    monkeypatch.setattr(
        main, "run_gui", lambda *args: pytest.fail("Worker opened the GUI")
    )
    assert main.main() == 17
    assert seen == [Path("request.json")]


def test_worker_commands_cover_source_and_packaged_entry(tmp_path):
    from app.core.native_job_manager import worker_command

    request = tmp_path / "request.json"
    source = tmp_path / "main.py"
    assert worker_command(
        request, main_path=source, python_executable="python", frozen=False
    ) == ["python", str(source.resolve()), "--native-worker", str(request.resolve())]
    assert worker_command(
        request, python_executable="CADPhotoToDXF.exe", frozen=True
    ) == ["CADPhotoToDXF.exe", "--native-worker", str(request.resolve())]


def test_git_source_provenance_tracks_commit_and_dirty_without_hardcoding(tmp_path):
    from app.core.native_job_manager import git_source_provenance

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Native entry test")
    git("config", "user.email", "native-entry@example.invalid")
    (tmp_path / "code.py").write_text("print('first')\n")
    git("add", "code.py")
    git("commit", "-m", "source snapshot")
    record = git_source_provenance(tmp_path)
    assert record["commit"] == git("rev-parse", "HEAD")
    assert record["worktree_dirty"] is False
    (tmp_path / "code.py").write_text("print('changed')\n")
    assert git_source_provenance(tmp_path)["worktree_dirty"] is True


def test_gui_defaults_to_native_and_keeps_explicit_legacy(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.gui import MainWindow

    monkeypatch.setenv("I2CAD_JOBS_ROOT", str(tmp_path / "jobs"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window._native_task_panel_active()
        assert "native-objects" in window.windowTitle()
        assert "LOCAL_NO_GO" in window.windowTitle()
        assert all(not action.isEnabled() for action in window._legacy_only_actions)
        assert window.native_task_panel.budget_spins["wall_seconds"].value() == 7200
        window.workspace_tabs.setCurrentIndex(1)
        assert "preserved_main_baseline" in window.windowTitle()
        assert all(action.isEnabled() for action in window._legacy_only_actions)
        assert window.product_status_label.text().startswith("兼容工具")
    finally:
        window.close()
        app.processEvents()
