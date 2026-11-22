"""A transient progress read must not decide a managed worker's outcome."""

import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import native_job_manager as jobs


JOB_ID = "optional-progress"


@pytest.fixture
def active_task(tmp_path):
    manager = jobs.NativeJobManager(tmp_path / "jobs")
    directory = manager.jobs_root / JOB_ID / "attempts" / "0001"
    directory.mkdir(parents=True)
    state = {
        "job_id": JOB_ID,
        "attempt": 1,
        "attempt_directory": str(directory),
        "status": "RUNNING",
        "stage": "TEXT_ROWS",
        "progress": 0.2,
        "active_children": [{"pid": 1234}],
        "result_dxf": None,
        "error": None,
    }
    manager._save_state(state)
    manager._processes[JOB_ID] = {"process": SimpleNamespace(poll=lambda: None)}
    jobs.atomic_json(
        directory / "progress.json",
        {"stage": "CROSS_ENGINE_TEXT", "progress": 0.4, "active_children": []},
    )
    return manager, directory, state


def _fail_read(monkeypatch, path, exception, *, once=False):
    original = jobs.read_json
    calls = []

    def read(candidate):
        if Path(candidate) == path and (not once or not calls):
            calls.append(str(candidate))
            raise exception
        return original(candidate)

    monkeypatch.setattr(jobs, "read_json", read)
    return calls


@pytest.mark.parametrize("status", ["STARTING", "RUNNING"])
@pytest.mark.parametrize(
    "error_type,code",
    [(PermissionError, errno.EACCES), (FileNotFoundError, errno.ENOENT)],
)
def test_optional_read_preserves_progress_then_recovers(
    active_task, monkeypatch, status, error_type, code
):
    manager, directory, initial = active_task
    initial["status"] = status
    manager._save_state(initial)
    path = directory / "progress.json"
    calls = _fail_read(
        monkeypatch,
        path,
        error_type(code, "transient file race", str(path)),
        once=True,
    )

    first = manager.poll(JOB_ID)
    assert first["status"] == status
    for key in ("stage", "progress", "active_children", "result_dxf", "error"):
        assert first[key] == initial[key]
    note = first["optional_progress_read"]
    assert note["transient_failure_count"] == 1
    assert note["last_read_succeeded"] is False
    assert note["last_failure"]["type"] == error_type.__name__
    assert note["last_failure"]["errno"] == code
    assert note["last_failure"]["path"] == str(path)
    assert note["last_failure"]["previous_progress_preserved"]
    assert not note["last_failure"]["terminal_result_inferred"]
    assert manager._read_state(JOB_ID)["optional_progress_read"] == note

    second = manager.poll(JOB_ID)
    assert second["status"] == "RUNNING"
    assert second["stage"] == "CROSS_ENGINE_TEXT"
    assert second["progress"] == 0.4
    assert second["active_children"] == []
    assert second["result_dxf"] is None
    assert second["optional_progress_read"]["transient_failure_count"] == 1
    assert second["optional_progress_read"]["last_read_succeeded"] is True
    assert second["optional_progress_read"]["last_failure"] == note["last_failure"]
    assert second["optional_progress_read"]["last_successful_read_utc"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error_type,code",
    [(PermissionError, errno.EACCES), (FileNotFoundError, errno.ENOENT)],
)
def test_unreadable_progress_does_not_hide_dead_worker(
    active_task, monkeypatch, error_type, code
):
    manager, directory, initial = active_task
    path = directory / "progress.json"
    _fail_read(monkeypatch, path, error_type(code, "transient file race", str(path)))
    manager._processes.clear()
    monkeypatch.setattr(jobs, "_same_process", lambda identity: False)

    actual = manager.poll(JOB_ID)
    assert actual["status"] == "INTERRUPTED"
    assert actual["error"]["type"] == "WORKER_EXIT_WITHOUT_OUTCOME"
    assert actual["progress"] == initial["progress"]
    assert actual["result_dxf"] is None
    assert actual["optional_progress_read"]["transient_failure_count"] == 1
    assert not (directory / "outcome.json").exists()
    assert not (manager.jobs_root / JOB_ID / "results").exists()


def test_outcome_is_read_before_optional_progress(active_task, monkeypatch):
    manager, directory, _ = active_task
    calls = _fail_read(
        monkeypatch, directory / "progress.json", PermissionError("locked progress")
    )
    jobs.atomic_json(
        directory / "outcome.json",
        {
            "job_id": JOB_ID,
            "attempt": 1,
            "status": "FAILED",
            "stage": "SOURCE_GATE_REJECTED",
            "progress": 0.8,
            "error": {"type": "SOURCE_GATE_REJECTED"},
        },
    )
    manager._processes[JOB_ID]["process"] = SimpleNamespace(
        poll=lambda: pytest.fail("Valid outcome must take precedence over process poll")
    )

    actual = manager.poll(JOB_ID)
    assert actual["status"] == "FAILED"
    assert actual["stage"] == "SOURCE_GATE_REJECTED"
    assert actual["error"]["type"] == "SOURCE_GATE_REJECTED"
    assert "optional_progress_read" not in actual
    assert calls == []


@pytest.mark.parametrize(
    "error_type,code",
    [(PermissionError, errno.EACCES), (FileNotFoundError, errno.ENOENT)],
)
def test_required_outcome_read_errors_are_not_swallowed(
    active_task, monkeypatch, error_type, code
):
    manager, directory, _ = active_task
    outcome = directory / "outcome.json"
    jobs.atomic_json(outcome, {"job_id": JOB_ID, "attempt": 1, "status": "FAILED"})
    _fail_read(
        monkeypatch, outcome, error_type(code, "required outcome read", str(outcome))
    )
    with pytest.raises(error_type):
        manager.poll(JOB_ID)
    assert "optional_progress_read" not in manager._read_state(JOB_ID)


@pytest.mark.parametrize("changes", [{"job_id": "different-task"}, {"attempt": 2}])
def test_outcome_identity_mismatch_is_not_swallowed(active_task, changes):
    manager, directory, _ = active_task
    jobs.atomic_json(
        directory / "outcome.json",
        {
            "job_id": JOB_ID,
            "attempt": 1,
            "status": "FAILED",
            **changes,
        },
    )
    with pytest.raises(ValueError, match="Worker outcome identity mismatch"):
        manager.poll(JOB_ID)


@pytest.mark.parametrize("filename", ["progress.json", "outcome.json"])
def test_damaged_json_is_not_swallowed(active_task, filename):
    manager, directory, _ = active_task
    (directory / filename).write_text('{"stage": broken', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        manager.poll(JOB_ID)
    assert "optional_progress_read" not in manager._read_state(JOB_ID)


@pytest.mark.parametrize("content", ["null", "[]"])
def test_invalid_progress_record_is_not_treated_as_absent(active_task, content):
    manager, directory, _ = active_task
    (directory / "progress.json").write_text(content, encoding="utf-8")
    with pytest.raises(AttributeError):
        manager.poll(JOB_ID)
    assert "optional_progress_read" not in manager._read_state(JOB_ID)


def test_other_progress_io_error_is_not_swallowed(active_task, monkeypatch):
    manager, directory, _ = active_task
    _fail_read(
        monkeypatch,
        directory / "progress.json",
        OSError(errno.EIO, "unrelated IO error"),
    )
    with pytest.raises(OSError, match="unrelated IO error"):
        manager.poll(JOB_ID)


def test_stored_job_identity_mismatch_is_not_swallowed(active_task):
    manager, _, initial = active_task
    jobs.atomic_json(
        manager.jobs_root / JOB_ID / "state.json",
        {**initial, "job_id": "different-task"},
    )
    with pytest.raises(ValueError, match="Stored job identity mismatch"):
        manager.poll(JOB_ID)


def test_inactive_task_does_not_read_optional_progress(active_task, monkeypatch):
    manager, directory, initial = active_task
    initial["status"] = "INTERRUPTED"
    manager._save_state(initial)
    calls = _fail_read(
        monkeypatch, directory / "progress.json", PermissionError("locked progress")
    )
    actual = manager.poll(JOB_ID)
    assert actual["status"] == "INTERRUPTED"
    assert calls == []
    assert "optional_progress_read" not in actual
