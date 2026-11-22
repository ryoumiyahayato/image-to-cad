"""Job-scoped cancellation and observed child-process execution.

The desktop starts one worker process. OCR belongs to that process tree; no
module starts a detached recognizer. Without a context the same helpers retain
ordinary synchronous CLI behavior, with no hidden drawing or cache defaults.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from app.core.cancellation import ProcessingCancelled


class NativeCancelled(ProcessingCancelled):
    def __init__(self, reason="user", stage=None):
        self.reason, self.stage = reason, stage
        super().__init__(
            f"NATIVE_CANCELLED: {reason}" + (f" at {stage}" if stage else "")
        )


class NativeResourceLimit(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


@dataclass
class ExecutionContext:
    cancel_file: Path
    event_file: Path
    identity: dict
    progress_file: Path | None = None
    resume_evidence: Path | None = None
    parent_pid: int | None = None
    validation_controls: dict = field(default_factory=dict)
    resource_limits: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    active_children: dict = field(default_factory=dict)
    failed_children: list = field(default_factory=list)
    stage: str = "WORKER_STARTING"
    fraction: float = 0.0
    sequence: int = 0
    _progress_write_failures: int = field(default=0, init=False, repr=False)
    _progress_recovery_pending: bool = field(default=False, init=False, repr=False)

    def event(self, kind, **values):
        self.sequence += 1
        row = {
            "sequence": self.sequence,
            "utc": utc_now(),
            "elapsed_wall_seconds": time.monotonic() - self.started,
            "kind": kind,
            "job_id": self.identity.get("job_id"),
            "attempt": self.identity.get("attempt"),
            **values,
        }
        self.event_file.parent.mkdir(parents=True, exist_ok=True)
        with self.event_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
        return row

    def write_progress(self, data):
        """Publish optional telemetry without weakening required atomic writes.

        Only a denied replacement of this context's progress file is deferred.
        Creating, serializing, writing and syncing the owned temporary file,
        and recording the failure, retain their ordinary failure behavior.
        """
        if self.progress_file is None:
            return False
        path = Path(self.progress_file)
        payload = (
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=path.name + ".",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, path)
        except PermissionError as exc:
            # This file is unique to this call and was never published. A
            # cleanup or event-write failure is not an optional replace race.
            temporary.unlink()
            self._progress_write_failures += 1
            self._progress_recovery_pending = True
            self.event(
                "optional_progress_write_deferred",
                stage=self.stage,
                progress=self.fraction,
                path=str(path),
                failure_count=self._progress_write_failures,
                failure_step="os.replace",
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "errno": exc.errno,
                    "winerror": getattr(exc, "winerror", None),
                },
                unpublished_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
                unpublished_snapshot_bytes=len(payload),
                owned_temporary_removed=str(temporary),
                previous_snapshot_preserved=True,
                terminal_result_inferred=False,
            )
            return False
        if self._progress_recovery_pending:
            self.event(
                "optional_progress_write_recovered",
                stage=self.stage,
                progress=self.fraction,
                path=str(path),
                prior_failure_count=self._progress_write_failures,
                published_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
            )
            self._progress_recovery_pending = False
        return True

    def check(self, stage=None):
        if stage is not None:
            self.stage = str(stage)
        if self.cancel_file.is_file():
            try:
                reason = read_json(self.cancel_file).get("reason", "user")
            except (ValueError, OSError):
                reason = "cancel_file_present"
            raise NativeCancelled(reason, self.stage)
        if (
            self.parent_pid is not None
            and os.name == "posix"
            and os.getppid() != self.parent_pid
        ):
            raise NativeCancelled("parent_application_exited", self.stage)


_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "native_execution_context", default=None
)


def set_context(context=None, **kwargs):
    if context is None:
        for key in ("cancel_file", "event_file", "progress_file", "resume_evidence"):
            if kwargs.get(key) is not None:
                kwargs[key] = Path(kwargs[key])
        context = ExecutionContext(**kwargs)
    _CONTEXT.set(context)
    return context


@contextmanager
def use_context(context=None, **kwargs):
    prior = _CONTEXT.get()
    current = set_context(context, **kwargs)
    try:
        yield current
    finally:
        _CONTEXT.set(prior)


def current_context():
    return _CONTEXT.get()


def active_resource_limits(defaults):
    """Use the explicit task contract; retain standalone experiment defaults.

    The manager enforces cumulative CPU, elapsed wall time and simultaneous
    worker/OCR tree RSS. Local loops share that contract instead of silently
    applying an unrelated historical per-experiment limit.
    """
    context = _CONTEXT.get()
    if context is not None and context.resource_limits:
        return dict(context.resource_limits), "explicit_task_resource_contract"
    return dict(defaults), "historical_standalone_experiment_defaults"


def check_cancel(stage=None):
    context = _CONTEXT.get()
    if context is not None:
        context.check(stage)


def boundary(stage, fraction=None):
    """Report an actual stage boundary; an explicit test barrier is recorded."""
    context = _CONTEXT.get()
    if context is None:
        return
    context.check(stage)
    if fraction is not None:
        value = float(fraction)
        if not 0 <= value <= 1:
            raise ValueError("Progress must be in [0, 1]")
        context.fraction = value
    row = context.event("stage", stage=stage, progress=context.fraction)
    if context.progress_file is not None:
        context.write_progress(
            row | {"active_children": list(context.active_children.values())},
        )
    controls = context.validation_controls
    if controls.get("hold_stage") == stage:
        duration = float(controls.get("hold_seconds", 0))
        if not 0 <= duration <= 10:
            raise ValueError("Validation barrier is limited to 10 seconds")
        context.event("explicit_validation_barrier", stage=stage, seconds=duration)
        stop = time.monotonic() + duration
        while time.monotonic() < stop:
            context.check(stage)
            time.sleep(0.025)
    context.check(stage)


def checkpoint_artifact(name, path):
    context = _CONTEXT.get()
    if context is None:
        return
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    context.event(
        "checkpoint_artifact",
        name=name,
        path=str(path),
        sha256=file_sha(path),
        bytes=path.stat().st_size,
    )
    context.check()


def _terminate_child(process, grace=0.5):
    if process.poll() is not None:
        return
    children = []
    try:
        import psutil

        children = psutil.Process(process.pid).children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.Error:
                pass
    except Exception:
        pass
    process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    for child in children:
        try:
            if child.is_running():
                child.kill()
        except Exception:
            pass


def run_subprocess(
    args, *, input=None, capture_output=False, timeout=None, check=False, **kwargs
):
    """A subprocess.run-compatible narrow wrapper with real OCR cancellation.

    The child remains in the worker's process group. The parent's forced tree
    stop therefore reaches OCR even if the worker is blocked in a native call.
    """
    context = _CONTEXT.get()
    if context is None:
        return subprocess.run(
            args,
            input=input,
            capture_output=capture_output,
            timeout=timeout,
            check=check,
            **kwargs,
        )
    context.check()
    if kwargs.get("shell"):
        raise ValueError("Native worker subprocesses must use an argument vector")
    if capture_output:
        if "stdout" in kwargs or "stderr" in kwargs:
            raise ValueError("capture_output cannot be combined with stdout/stderr")
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        if "stdin" in kwargs:
            raise ValueError("input cannot be combined with stdin")
        kwargs["stdin"] = subprocess.PIPE
    kwargs.setdefault("start_new_session", False)
    if kwargs["start_new_session"]:
        raise ValueError("OCR must remain in its managed worker process tree")
    environment = kwargs.get("env")
    if getattr(__import__("sys"), "frozen", False):
        environment = dict(os.environ if environment is None else environment)
        for key in ("LD_LIBRARY_PATH", "LIBPATH"):
            original = environment.get(key + "_ORIG")
            if original is None:
                environment.pop(key, None)
            else:
                environment[key] = original
        kwargs["env"] = environment
    started = time.monotonic()
    process = subprocess.Popen(args, **kwargs)
    command = [os.fspath(a) for a in args] if not isinstance(args, str) else args
    child_row = {"pid": process.pid, "command": command, "started_utc": utc_now()}
    context.active_children[process.pid] = child_row
    context.event("subprocess_started", **child_row)
    first = True
    try:
        if context.progress_file:
            context.write_progress(
                {
                    "stage": context.stage,
                    "progress": context.fraction,
                    "utc": utc_now(),
                    "active_children": list(context.active_children.values()),
                },
            )
        while True:
            context.check()
            elapsed = time.monotonic() - started
            if timeout is not None and elapsed >= timeout:
                _terminate_child(process)
                out, err = process.communicate()
                raise subprocess.TimeoutExpired(args, timeout, output=out, stderr=err)
            try:
                out, err = process.communicate(
                    input=input if first else None,
                    timeout=min(0.05, max(0.001, timeout - elapsed))
                    if timeout is not None
                    else 0.05,
                )
                break
            except subprocess.TimeoutExpired:
                first = False
        result = subprocess.CompletedProcess(args, process.returncode, out, err)
        context.check()
        if check:
            result.check_returncode()
        return result
    except BaseException:
        _terminate_child(process)
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        context.active_children.pop(process.pid, None)
        if process.poll() not in (None, 0):
            context.failed_children.append(
                {"pid": process.pid, "command": command, "returncode": process.poll()}
            )
        context.event(
            "subprocess_finished",
            pid=process.pid,
            command=command,
            returncode=process.poll(),
            wall_seconds=time.monotonic() - started,
            live_child_remaining=process.poll() is None,
        )


def restore_partial_ocr(destination, *, source_subdir="text"):
    """Reuse only successful, hashed passes from this job's earlier attempt."""
    context = _CONTEXT.get()
    if context is None or context.resume_evidence is None:
        return {"restored_passes": 0, "reason": "NO_THIS_JOB_PARTIAL_CHECKPOINT"}
    relative = Path(source_subdir)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            "OCR checkpoint subdirectory must stay inside this task's prior evidence"
        )
    source = context.resume_evidence / relative
    destination = Path(destination)
    restored, rejected = [], []
    for folder in ("discovery_ocr", "local_ocr"):
        for meta_path in (
            sorted((source / folder).glob("*.json"))
            if (source / folder).is_dir()
            else []
        ):
            meta = read_json(meta_path)
            tsv = meta_path.with_suffix(".tsv")
            image = meta_path.with_suffix(".png")
            if (
                meta.get("status") != "COMPLETED"
                or not tsv.is_file()
                or not image.is_file()
                or file_sha(tsv) != meta.get("tsv_sha256")
                or file_sha(image) != meta.get("image_sha256")
            ):
                rejected.append(str(meta_path))
                continue
            target_dir = destination / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            copied = []
            for old in (meta_path, tsv, image, meta_path.with_suffix(".stderr.txt")):
                if old.is_file():
                    target = target_dir / old.name
                    if target.exists():
                        raise FileExistsError(
                            "Never overwrite a current OCR pass during restore: "
                            + str(target)
                        )
                    shutil.copy2(old, target)
                    copied.append({"path": str(target), "sha256": file_sha(target)})
            restored.append({"original_meta": str(meta_path), "files": copied})
    record = {
        "restored_passes": len(restored),
        "rejected_or_incomplete": rejected,
        "passes": restored,
        "identity": context.identity,
        "source_subdir": relative.as_posix(),
        "old_files_changed": False,
        "source_specification_rechecked_by_OCR_before_reuse": True,
    }
    context.event(
        "partial_OCR_restored",
        restored_passes=len(restored),
        rejected_passes=len(rejected),
    )
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination / "partial_ocr_resume.json", record)
    return record
