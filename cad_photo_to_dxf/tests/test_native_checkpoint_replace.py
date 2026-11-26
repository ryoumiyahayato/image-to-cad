"""Required JSON checkpoints survive bounded Windows locks without lost evidence."""

import errno
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.native_objects import contracts
from app.native_objects.execution import NativeCancelled, use_context


class Clock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 0.05
        self.delays.append(seconds)
        self.now += seconds


def denied(winerror=5):
    error = PermissionError(errno.EACCES, "controlled required checkpoint denial")
    if winerror is not None:
        error.winerror = winerror
    return error


@pytest.fixture
def checkpoint(tmp_path):
    target = tmp_path / "evidence" / "pipeline_trace.json"
    contracts.save_json(target, {"old": "complete checkpoint"})
    with use_context(
        cancel_file=tmp_path / "cancel.json", event_file=tmp_path / "events.ndjson",
        identity={"job_id": "checkpoint-test", "attempt": 1},
    ) as context:
        yield SimpleNamespace(path=target, context=context, original=target.read_bytes())


def events(checkpoint):
    path = checkpoint.context.event_file
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_released_windows_lock_commits_whole_payload(checkpoint, monkeypatch, winerror):
    clock = Clock()
    monkeypatch.setattr(contracts, "time", clock)
    monkeypatch.setattr(contracts, "sys", SimpleNamespace(platform="win32"))
    replace = contracts.os.replace
    attempts = []

    def once(source, destination):
        attempts.append((source, destination))
        assert checkpoint.path.read_bytes() == checkpoint.original
        assert json.loads(Path(source).read_text()) == {"new": "完整证据"}
        if len(attempts) == 1:
            raise denied(winerror)
        return replace(source, destination)

    monkeypatch.setattr(contracts.os, "replace", once)
    contracts.save_json(checkpoint.path, {"new": "完整证据"})
    assert json.loads(checkpoint.path.read_text()) == {"new": "完整证据"}
    assert attempts[0] == attempts[1]
    assert clock.delays == [0.05]
    assert not list(checkpoint.path.parent.glob("*.pending-*"))
    assert [row["kind"] for row in events(checkpoint)] == [
        "checkpoint_replace_retry", "checkpoint_replace_recovered",
    ]
    assert events(checkpoint)[0]["winerror"] == winerror


@pytest.mark.parametrize("platform,winerror", [("linux", 5), ("win32", None), ("win32", 17), ("win32", 183)])
def test_other_failures_are_not_retried(checkpoint, monkeypatch, platform, winerror):
    clock = Clock()
    monkeypatch.setattr(contracts, "time", clock)
    monkeypatch.setattr(contracts, "sys", SimpleNamespace(platform=platform))
    failure = denied(winerror)
    calls = []

    def fail(source, destination):
        calls.append((source, destination))
        raise failure

    monkeypatch.setattr(contracts.os, "replace", fail)
    with pytest.raises(PermissionError) as caught:
        contracts.save_json(checkpoint.path, {"new": True})
    assert caught.value is failure and len(calls) == 1 and not clock.delays
    assert checkpoint.path.read_bytes() == checkpoint.original
    assert not list(checkpoint.path.parent.glob("*.pending-*"))
    assert not events(checkpoint)


def test_persistent_windows_denial_keeps_old_checkpoint_and_original_error(checkpoint, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(contracts, "time", clock)
    monkeypatch.setattr(contracts, "sys", SimpleNamespace(platform="win32"))
    failure = denied()
    calls = []

    def fail(source, destination):
        calls.append((source, destination))
        assert checkpoint.path.read_bytes() == checkpoint.original
        raise failure

    monkeypatch.setattr(contracts.os, "replace", fail)
    with pytest.raises(PermissionError) as caught:
        contracts.save_json(checkpoint.path, {"new": True})
    assert caught.value is failure
    assert len(calls) > 1 and clock.now == pytest.approx(2.0)
    assert checkpoint.path.read_bytes() == checkpoint.original
    assert not list(checkpoint.path.parent.glob("*.pending-*"))
    assert events(checkpoint)[-1]["kind"] == "checkpoint_replace_retry_exhausted"


def test_cancel_during_lock_prevents_replacement(checkpoint, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(contracts, "time", clock)
    monkeypatch.setattr(contracts, "sys", SimpleNamespace(platform="win32"))

    def cancel_then_fail(source, destination):
        checkpoint.context.cancel_file.write_text('{"reason":"user"}')
        raise denied()

    monkeypatch.setattr(contracts.os, "replace", cancel_then_fail)
    with pytest.raises(NativeCancelled):
        contracts.save_json(checkpoint.path, {"new": True})
    assert not clock.delays
    assert checkpoint.path.read_bytes() == checkpoint.original
    assert not list(checkpoint.path.parent.glob("*.pending-*"))


def test_cleanup_denial_preserves_original_failure_and_owned_temporary(checkpoint, monkeypatch):
    failure = denied()

    def fail_replace(source, destination):
        raise failure

    def fail_unlink(path):
        raise PermissionError(errno.EACCES, "temporary still locked")

    monkeypatch.setattr(contracts.os, "replace", fail_replace)
    monkeypatch.setattr(contracts.os, "unlink", fail_unlink)
    with pytest.raises(PermissionError) as caught:
        contracts.save_json(checkpoint.path, {"new": "unpublished evidence"})
    assert caught.value is failure
    assert checkpoint.path.read_bytes() == checkpoint.original
    remaining = list(checkpoint.path.parent.glob("*.pending-*"))
    assert len(remaining) == 1
    assert json.loads(remaining[0].read_text()) == {"new": "unpublished evidence"}
    assert any("temporary retained" in note for note in failure.__notes__)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires an actual Windows file handle")
def test_real_windows_file_handle_release_recovers(checkpoint, monkeypatch):
    """Exercise a real lock, without guessing the holder in the historical run."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    # Existing file, GENERIC_READ, SHARE_READ|SHARE_WRITE, deliberately no DELETE.
    handle = create_file(str(checkpoint.path), 0x80000000, 0x3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    denied_event = threading.Event()
    close_errors, errors = [], []
    replace = contracts.os.replace

    def observed_replace(source, destination):
        try:
            return replace(source, destination)
        except OSError as error:
            errors.append(error.winerror)
            denied_event.set()
            raise

    def release():
        try:
            if not denied_event.wait(3):
                close_errors.append("Expected actual Windows denial was not observed")
        finally:
            if not close_handle(handle):
                close_errors.append(str(ctypes.WinError(ctypes.get_last_error())))

    monkeypatch.setattr(contracts.os, "replace", observed_replace)
    thread = threading.Thread(target=release)
    thread.start()
    try:
        contracts.save_json(checkpoint.path, {"new": "actual Windows checkpoint"})
    finally:
        thread.join(4)
    assert not thread.is_alive() and not close_errors
    assert errors and set(errors) <= {5, 32, 33}
    assert json.loads(checkpoint.path.read_text()) == {"new": "actual Windows checkpoint"}
    assert not list(checkpoint.path.parent.glob("*.pending-*"))
    assert events(checkpoint)[-1]["kind"] == "checkpoint_replace_recovered"
