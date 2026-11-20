"""Opt-in observational spans for native conversion, with no geometry changes.

Set I2CAD_PROFILE_DIR for the current run. Each process appends to its own JSONL
file. CPU values are process-wide snapshots, not per-thread attribution; reaped
child CPU is cumulative RUSAGE_CHILDREN and must not be added twice to a process
tree total. Missing platform counters are null, never fabricated as zero.

Recorder overhead has not been measured. Profile I/O is best-effort and cannot
replace the conversion's existing cancellation, exception or publication rules.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import itertools
import json
import os
from pathlib import Path
import sys
import threading
import time

try:
    import resource as _resource
except ImportError:  # Windows has no Unix resource module.
    _resource = None


SCHEMA = "native-performance-span-v1"
_lock = threading.RLock()
_local = threading.local()
_ids = itertools.count(1)
_created = set()
_warned = set()


def _child_cpu():
    if _resource is None:
        return None
    try:
        usage = _resource.getrusage(_resource.RUSAGE_CHILDREN)
        return float(usage.ru_utime + usage.ru_stime)
    except (AttributeError, OSError, ValueError):
        return None


def _exception_detail(error):
    try:
        message = str(error)[:500]
    except Exception:
        message = "<exception message unavailable>"
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": message,
    }


def _emit(directory, record):
    """Serialize writes between threads; logging failure cannot fail a job."""
    try:
        with _lock:
            key = (os.getpid(), directory)
            if key not in _created:
                Path(directory).mkdir(parents=True, exist_ok=True)
                _created.add(key)
            target = Path(directory) / f"spans-{os.getpid()}.jsonl"
            with target.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=True,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    except Exception as error:
        # Bound diagnostic output to one warning per process/directory.
        with _lock:
            key = (os.getpid(), directory)
            if key not in _warned:
                _warned.add(key)
                try:
                    print(
                        f"I2CAD_PROFILE_WRITE_FAILED: {type(error).__name__}: {str(error)[:240]}",
                        file=sys.stderr,
                    )
                except Exception:
                    pass


@contextmanager
def span(name, *, _directory=None):
    """Record an inclusive span, preserving the exact original exception."""
    directory = (
        os.environ.get("I2CAD_PROFILE_DIR") if _directory is None else _directory
    )
    if not directory:
        yield
        return
    directory = os.path.abspath(os.path.expanduser(directory))
    stack = getattr(_local, "stack", None)
    if stack is None:
        stack = _local.stack = []
    pid = os.getpid()
    with _lock:
        span_id = f"{pid}:{next(_ids)}"
    parent = stack[-1][0] if stack and stack[-1][1] == directory else None
    stack.append((span_id, directory))
    started_ns = time.monotonic_ns()
    started_cpu = time.process_time()
    started_child_cpu = _child_cpu()
    identity = {
        "schema": SCHEMA,
        "pid": pid,
        "ppid": os.getppid(),
        "thread_id": threading.get_ident(),
        "thread_name": threading.current_thread().name,
        "span_id": span_id,
        "parent_span_id": parent,
        "name": str(name),
    }
    _emit(
        directory,
        {
            **identity,
            "event": "begin",
            "monotonic_ns": started_ns,
            "process_cpu_seconds": started_cpu,
            "reaped_child_cpu_seconds": started_child_cpu,
            "wall_seconds": None,
            "success": None,
            "exception": None,
        },
    )
    failure = None
    try:
        yield
    except BaseException as error:
        failure = _exception_detail(error)
        raise
    finally:
        ended_ns = time.monotonic_ns()
        ended_cpu = time.process_time()
        ended_child_cpu = _child_cpu()
        stack.pop()
        _emit(
            directory,
            {
                **identity,
                "event": "end",
                "monotonic_ns": ended_ns,
                "process_cpu_seconds": ended_cpu,
                "reaped_child_cpu_seconds": ended_child_cpu,
                "wall_seconds": (ended_ns - started_ns) / 1e9,
                "process_cpu_elapsed_seconds": ended_cpu - started_cpu,
                "reaped_child_cpu_elapsed_seconds": (
                    None
                    if started_child_cpu is None or ended_child_cpu is None
                    else ended_child_cpu - started_child_cpu
                ),
                "success": failure is None,
                "exception": failure,
            },
        )


def profiled(name=None):
    """Decorate selected synchronous functions without capturing their data."""

    def decorate(function):
        label = name or f"{function.__module__}.{function.__qualname__}"

        @wraps(function)
        def measured(*args, **kwargs):
            directory = os.environ.get("I2CAD_PROFILE_DIR")
            if not directory:
                return function(*args, **kwargs)
            with span(label, _directory=directory):
                return function(*args, **kwargs)

        return measured

    return decorate
