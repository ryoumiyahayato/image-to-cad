"""Only replacement of optional progress may defer a denied atomic write."""

from contextlib import contextmanager
import errno
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.native_objects import execution as ex


@pytest.fixture
def context(tmp_path):
    progress = tmp_path / "progress.json"
    ex.atomic_json(progress, {"stage": "PRIOR_STAGE", "progress": 0.2})
    with ex.use_context(
        cancel_file=tmp_path / "cancel.json",
        event_file=tmp_path / "events.ndjson",
        progress_file=progress,
        identity={"job_id": "optional-write", "attempt": 1},
    ) as value:
        value.stage, value.fraction = "PRIOR_STAGE", 0.2
        yield value


def _events(context, kind):
    if not context.event_file.exists():
        return []
    return [
        json.loads(line)
        for line in context.event_file.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == kind
    ]


def _deny_progress_replace(context, monkeypatch, on_denial=None):
    real_replace = ex.os.replace
    control = SimpleNamespace(deny=True, payloads=[], paths=[])

    def replace(source, target):
        if Path(target) == context.progress_file and control.deny:
            control.payloads.append(Path(source).read_bytes())
            control.paths.append(Path(source))
            if on_denial is not None:
                on_denial()
            raise PermissionError(
                errno.EACCES, "denied progress replacement", str(target)
            )
        return real_replace(source, target)

    monkeypatch.setattr(ex.os, "replace", replace)
    return control


def _invoke(entry):
    if entry == "boundary":
        return ex.boundary("SOURCE_OBSERVE", 0.3)
    result = ex.run_subprocess(
        [sys.executable, "-c", "print('child-completed')"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0 and result.stdout.strip() == "child-completed"
    return result


@pytest.mark.parametrize("entry", ["boundary", "subprocess"])
def test_both_optional_write_paths_keep_old_snapshot_then_recover(
    context, monkeypatch, entry
):
    before = context.progress_file.read_bytes()
    control = _deny_progress_replace(context, monkeypatch)
    _invoke(entry)
    assert context.progress_file.read_bytes() == before
    assert not context.active_children
    assert len(control.payloads) == 1
    assert all(not path.exists() for path in control.paths)
    assert not list(context.progress_file.parent.glob("progress.json.*.tmp"))
    deferred = _events(context, "optional_progress_write_deferred")
    assert len(deferred) == 1
    row = deferred[0]
    assert row["failure_step"] == "os.replace"
    assert row["error"]["type"] == "PermissionError"
    assert row["error"]["errno"] == errno.EACCES
    assert row["failure_count"] == 1
    assert row["previous_snapshot_preserved"]
    assert not row["terminal_result_inferred"]
    assert (
        row["unpublished_snapshot_sha256"]
        == hashlib.sha256(control.payloads[0]).hexdigest()
    )
    assert row["unpublished_snapshot_bytes"] == len(control.payloads[0])
    assert Path(row["owned_temporary_removed"]) == control.paths[0]

    control.deny = False
    ex.boundary("NEXT_REAL_STAGE", 0.5)
    actual = ex.read_json(context.progress_file)
    assert actual["stage"] == "NEXT_REAL_STAGE" and actual["progress"] == 0.5
    assert actual["active_children"] == []
    assert len(_events(context, "optional_progress_write_deferred")) == 1
    recovered = _events(context, "optional_progress_write_recovered")
    assert len(recovered) == 1 and recovered[0]["prior_failure_count"] == 1
    assert recovered[0]["published_snapshot_sha256"] == ex.file_sha(
        context.progress_file
    )
    assert not (context.progress_file.parent / "outcome.json").exists()


@pytest.mark.parametrize("entry", ["boundary", "subprocess"])
def test_deferred_progress_does_not_skip_cancel_or_child_cleanup(
    context, monkeypatch, entry
):
    before = context.progress_file.read_bytes()
    processes = []
    real_popen = ex.subprocess.Popen

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(ex.subprocess, "Popen", popen)

    def cancel():
        context.cancel_file.write_text(
            '{"reason": "explicit-user-cancel"}', encoding="utf-8"
        )

    _deny_progress_replace(context, monkeypatch, on_denial=cancel)
    with pytest.raises(ex.NativeCancelled, match="explicit-user-cancel"):
        if entry == "subprocess":
            ex.run_subprocess(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                stdin=subprocess.PIPE,
            )
        else:
            _invoke(entry)
    assert context.progress_file.read_bytes() == before
    assert not context.active_children
    assert all(process.poll() is not None for process in processes)
    assert len(_events(context, "optional_progress_write_deferred")) == 1
    if entry == "subprocess":
        assert len(processes) == 1
        assert (
            _events(context, "subprocess_finished")[-1]["live_child_remaining"] is False
        )


@pytest.mark.parametrize(
    "filename", ["outcome.json", "state.json", "completed_text.json"]
)
def test_required_atomic_json_still_raises_replace_permission_error(
    context, monkeypatch, filename
):
    target = context.progress_file.parent / filename
    ex.atomic_json(target, {"old": "required-evidence"})
    before = target.read_bytes()
    real_replace = ex.os.replace

    def replace(source, destination):
        if Path(destination) == target:
            raise PermissionError(
                errno.EACCES, "required replacement denied", str(target)
            )
        return real_replace(source, destination)

    monkeypatch.setattr(ex.os, "replace", replace)
    with pytest.raises(PermissionError, match="required replacement denied"):
        ex.atomic_json(target, {"new": "must-not-be-inferred-published"})
    assert target.read_bytes() == before
    assert not _events(context, "optional_progress_write_deferred")


@pytest.mark.parametrize("phase", ["create", "write", "fsync"])
def test_permission_errors_before_replace_are_not_optional(context, monkeypatch, phase):
    before = context.progress_file.read_bytes()

    def denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "required temporary " + phase)

    if phase == "create":
        monkeypatch.setattr(ex.tempfile, "NamedTemporaryFile", denied)
    elif phase == "fsync":
        monkeypatch.setattr(ex.os, "fsync", denied)
    else:
        create = ex.tempfile.NamedTemporaryFile

        @contextmanager
        def broken_writer(*args, **kwargs):
            with create(*args, **kwargs) as stream:
                yield SimpleNamespace(
                    name=stream.name,
                    write=denied,
                    flush=stream.flush,
                    fileno=stream.fileno,
                )

        monkeypatch.setattr(ex.tempfile, "NamedTemporaryFile", broken_writer)
    with pytest.raises(PermissionError, match="required temporary " + phase):
        ex.boundary("SOURCE_OBSERVE", 0.3)
    assert context.progress_file.read_bytes() == before
    assert not _events(context, "optional_progress_write_deferred")


def test_required_temporary_failure_in_subprocess_still_cleans_child(
    context, monkeypatch
):
    real_popen = ex.subprocess.Popen
    processes = []

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def denied(fd):
        raise PermissionError(errno.EACCES, "required temporary fsync")

    monkeypatch.setattr(ex.subprocess, "Popen", popen)
    monkeypatch.setattr(ex.os, "fsync", denied)
    with pytest.raises(PermissionError, match="required temporary fsync"):
        ex.run_subprocess(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
            stdin=subprocess.PIPE,
        )
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not context.active_children
    assert not _events(context, "optional_progress_write_deferred")
    assert _events(context, "subprocess_finished")[-1]["live_child_remaining"] is False


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.EIO, "other I/O"),
        FileNotFoundError(errno.ENOENT, "missing owned temporary"),
    ],
)
def test_other_replace_errors_are_not_swallowed(context, monkeypatch, error):
    def replace(source, target):
        raise error

    monkeypatch.setattr(ex.os, "replace", replace)
    with pytest.raises(type(error)):
        ex.boundary("SOURCE_OBSERVE", 0.3)
    assert not _events(context, "optional_progress_write_deferred")


@pytest.mark.parametrize(
    "value,error", [(float("nan"), ValueError), (object(), TypeError)]
)
def test_invalid_json_payload_is_not_swallowed(context, value, error):
    before = context.progress_file.read_bytes()
    with pytest.raises(error):
        context.write_progress({"bad": value})
    assert context.progress_file.read_bytes() == before
    assert not list(context.progress_file.parent.glob("progress.json.*.tmp"))
    assert not _events(context, "optional_progress_write_deferred")


def test_failure_to_record_deferral_is_not_hidden(context, monkeypatch):
    _deny_progress_replace(context, monkeypatch)
    event = context.event

    def record(kind, **values):
        if kind == "optional_progress_write_deferred":
            raise PermissionError(errno.EACCES, "required failure event")
        return event(kind, **values)

    monkeypatch.setattr(context, "event", record)
    with pytest.raises(PermissionError, match="required failure event"):
        ex.boundary("SOURCE_OBSERVE", 0.3)


@pytest.mark.skipif(
    sys.platform != "win32", reason="Requires a real Windows file handle"
)
def test_real_windows_progress_handle_denies_replace_then_recovers(
    context, monkeypatch
):
    """Proves this OS conflict, without identifying the historical CI lock holder."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    # A real regular-file handle: READ, share READ|WRITE but not DELETE,
    # OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL. No timing-based release/retry.
    handle = create_file(
        str(context.progress_file), 0x80000000, 0x3, None, 3, 0x80, None
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    before = context.progress_file.read_bytes()
    errors = []
    replace = ex.os.replace

    def observed_replace(source, target):
        try:
            return replace(source, target)
        except PermissionError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(ex.os, "replace", observed_replace)
    try:
        ex.boundary("LOCKED_PROGRESS", 0.3)
        assert len(errors) == 1 and errors[0].winerror in {5, 32, 33}
        assert context.progress_file.read_bytes() == before
        assert not list(context.progress_file.parent.glob("progress.json.*.tmp"))
        deferred = _events(context, "optional_progress_write_deferred")
        assert len(deferred) == 1
        assert deferred[0]["error"]["winerror"] == errors[0].winerror
    finally:
        if not close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    ex.boundary("AFTER_ACTUAL_HANDLE_RELEASE", 0.6)
    assert len(errors) == 1
    assert ex.read_json(context.progress_file)["stage"] == "AFTER_ACTUAL_HANDLE_RELEASE"
    assert len(_events(context, "optional_progress_write_recovered")) == 1
