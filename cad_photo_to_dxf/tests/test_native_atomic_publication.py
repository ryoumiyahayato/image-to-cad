"""Atomic publication tolerates a brief Windows lock, never a partial commit."""

from __future__ import annotations

import errno
import json
import os
import sys
import threading
from types import SimpleNamespace

import pytest

from app.core import native_worker as worker
from app.native_objects.execution import (
    NativeCancelled,
    NativeResourceLimit,
    atomic_json,
    use_context,
)


class Clock:
    def __init__(self):
        self.now = 100.0
        self.delays = []
        self.after_sleep = lambda: None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 0.05
        self.delays.append(seconds)
        self.now += seconds
        self.after_sleep()


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(worker, "time", value)
    return value


@pytest.fixture
def publication(tmp_path):
    attempt = tmp_path / "job" / "attempts" / "0001"
    staging = attempt / "staging"
    (staging / "evidence").mkdir(parents=True)
    payload = {
        "candidate.bin": b"immutable test payload, not a conversion fixture",
        "evidence/audit.json": b'{"test_payload": true}\n',
        "publication_manifest.json": b'{"test_manifest": true}\n',
    }
    for name, content in payload.items():
        (staging / name).write_bytes(content)
    published = tmp_path / "job" / "results" / "0001"
    published.parent.mkdir()
    with use_context(
        cancel_file=attempt / "cancel.json",
        event_file=attempt / "events.jsonl",
        identity={"job_id": "publication-contract", "attempt": 1},
    ) as context:
        yield SimpleNamespace(
            staging=staging,
            published=published,
            payload=payload,
            context=context,
        )


def _commit(publication, *, wall_seconds=10.0):
    return worker._publish_staging(
        publication.staging,
        publication.published,
        context=publication.context,
        wall_deadline=worker.time.monotonic() + wall_seconds,
    )


def _denied(winerror=5):
    error = PermissionError(errno.EACCES, "controlled publication conflict")
    if winerror is not None:
        error.winerror = winerror
    return error


def _events(publication):
    path = publication.context.event_file
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _assert_payload(publication, *, committed):
    root = publication.published if committed else publication.staging
    assert {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    } == publication.payload
    assert not (publication.staging if committed else publication.published).exists()


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_conflict_preserves_payload_and_atomic_commit(
    publication, monkeypatch, clock, winerror
):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform="win32"))
    real_rename = os.rename
    calls = []

    def rename(source, target):
        calls.append((source, target))
        if len(calls) == 1:
            raise _denied(winerror)
        return real_rename(source, target)

    monkeypatch.setattr(worker.os, "rename", rename)
    report = _commit(publication)
    assert report["rename_attempts"] == 2
    assert report["atomic_directory_rename"]
    assert clock.delays == [0.05]
    _assert_payload(publication, committed=True)
    events = _events(publication)
    assert len(events) == 1 and events[0]["kind"] == "atomic_publication_retry"
    assert events[0]["winerror"] == winerror
    assert publication.context.event_file.parent == publication.staging.parent


@pytest.mark.parametrize(
    "platform,winerror", [("linux", 5), ("win32", None), ("win32", 17), ("win32", 183)]
)
def test_other_platforms_or_error_categories_are_not_retried(
    publication, monkeypatch, clock, platform, winerror
):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform=platform))
    error = _denied(winerror)

    def denied(*_args):
        raise error

    monkeypatch.setattr(worker.os, "rename", denied)
    with pytest.raises(OSError) as caught:
        _commit(publication)
    assert caught.value is error
    assert clock.delays == [] and _events(publication) == []
    _assert_payload(publication, committed=False)


def test_persistent_access_failure_is_bounded_and_keeps_original_exception(
    publication, monkeypatch, clock
):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform="win32"))
    error = _denied()
    calls = []

    def denied(*_args):
        calls.append(clock.now)
        raise error

    monkeypatch.setattr(worker.os, "rename", denied)
    with pytest.raises(PermissionError) as caught:
        _commit(publication)
    assert caught.value is error
    assert 1 < len(calls) <= 42 and all(100 <= when < 102 for when in calls)
    assert sum(clock.delays) == pytest.approx(2.0)
    assert _events(publication)[-1]["kind"] == "atomic_publication_retry_exhausted"
    _assert_payload(publication, committed=False)


@pytest.mark.parametrize(
    "reason", ["user", "RESOURCE_STOP:CPU_LIMIT", "RESOURCE_STOP:RSS_LIMIT", "RESOURCE_STOP:TEMPORARY_LIMIT"]
)
def test_cancel_and_manager_resource_stop_during_delay_prevent_commit(
    publication, monkeypatch, clock, reason
):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform="win32"))
    calls = []

    def denied(*_args):
        calls.append(True)
        raise _denied()

    monkeypatch.setattr(worker.os, "rename", denied)
    clock.after_sleep = lambda: atomic_json(publication.context.cancel_file, {"reason": reason})
    with pytest.raises(NativeCancelled) as caught:
        _commit(publication)
    assert caught.value.reason == reason and len(calls) == 1
    _assert_payload(publication, committed=False)


def test_retry_does_not_extend_original_wall_budget(publication, monkeypatch, clock):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform="win32"))
    calls = []

    def denied(*_args):
        calls.append(clock.now)
        raise _denied()

    monkeypatch.setattr(worker.os, "rename", denied)
    with pytest.raises(NativeResourceLimit, match="WALL_LIMIT"):
        _commit(publication, wall_seconds=0.08)
    assert len(calls) == 2 and sum(clock.delays) == pytest.approx(0.08)
    _assert_payload(publication, committed=False)


@pytest.mark.parametrize("during_retry", [False, True])
def test_existing_publication_is_never_overwritten(
    publication, monkeypatch, clock, during_retry
):
    monkeypatch.setattr(worker, "sys", SimpleNamespace(platform="win32"))
    calls = []

    def occupied():
        publication.published.mkdir()
        (publication.published / "other-result.bin").write_bytes(b"do not overwrite")

    def denied(*_args):
        calls.append(True)
        raise _denied()

    monkeypatch.setattr(worker.os, "rename", denied)
    if during_retry:
        clock.after_sleep = occupied
    else:
        occupied()
    with pytest.raises(FileExistsError, match="immutable"):
        _commit(publication)
    assert len(calls) == int(during_retry)
    assert (publication.published / "other-result.bin").read_bytes() == b"do not overwrite"
    assert (publication.staging / "candidate.bin").read_bytes() == publication.payload["candidate.bin"]


def test_cancellation_after_successful_commit_does_not_undo_publication(
    publication, monkeypatch, clock
):
    real_rename = os.rename

    def commit_then_cancel(source, target):
        real_rename(source, target)
        atomic_json(publication.context.cancel_file, {"reason": "user"})

    monkeypatch.setattr(worker.os, "rename", commit_then_cancel)
    report = _commit(publication)
    assert report["rename_attempts"] == 1 and publication.context.cancel_file.is_file()
    _assert_payload(publication, committed=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires an actual Windows directory handle")
def test_real_windows_directory_handle_conflict_recovers_after_release(publication, monkeypatch):
    """A real OS lock proves recoverability, not the holder in the historical CI failure."""
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
    # GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE (no DELETE),
    # OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS for a real directory handle.
    handle = create_file(str(publication.staging), 0x80000000, 0x3, None, 3, 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    denied = threading.Event()
    released = threading.Event()
    close_errors = []
    actual_errors = []
    real_rename = os.rename

    def observed_rename(source, target):
        try:
            return real_rename(source, target)
        except OSError as error:
            actual_errors.append(error.winerror)
            denied.set()
            raise

    def release_after_actual_denial():
        try:
            if not denied.wait(3):
                close_errors.append("No actual rename failure observed while the handle was held")
        finally:
            if not close_handle(handle):
                close_errors.append(str(ctypes.WinError(ctypes.get_last_error())))
            released.set()

    release_thread = threading.Thread(target=release_after_actual_denial)
    release_thread.start()
    monkeypatch.setattr(worker.os, "rename", observed_rename)
    try:
        report = _commit(publication)
    finally:
        denied.set()
        release_thread.join(timeout=3)
    assert released.is_set() and not release_thread.is_alive() and not close_errors
    assert actual_errors and set(actual_errors) <= {5, 32, 33}
    assert report["rename_attempts"] > 1
    assert _events(publication)[0]["winerror"] == actual_errors[0]
    _assert_payload(publication, committed=True)
