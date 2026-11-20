"""Persistent native conversion jobs shared by the desktop and CLI.

The manager performs no OCR or reconstruction in the UI process. Attempts have
separate evidence and staging; only an audited worker result is published.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from app.native_objects.execution import atomic_json, file_sha, read_json, utc_now

try:
    import psutil
except ImportError:
    psutil = None


ACTIVE = frozenset({"STARTING", "RUNNING", "CANCEL_REQUESTED"})
TERMINAL = frozenset(
    {"COMPLETED_WITH_ISSUES", "CANCELLED", "FAILED", "INTERRUPTED", "RESOURCE_STOP"}
)
DEFAULT_LIMITS = {
    "CPU_seconds": 7200.0,
    "wall_seconds": 7200.0,
    "RSS_MiB": 3072.0,
    "temporary_MiB": 8192.0,
}


def remaining_budget(attempts, limits):
    """A resume spends the same task budget; cancellation never resets it.

    A final worker account includes reaped children. The manager also samples
    live children and the whole attempt. Keep the larger observation in each
    scope; never treat an unavailable CPU value as zero.
    """
    cpu_total = wall_total = 0.0
    accounts = []
    for attempt in attempts:
        directory = Path(attempt["directory"])
        outcome = (
            read_json(directory / "outcome.json")
            if (directory / "outcome.json").is_file()
            else {}
        )
        report = (
            read_json(directory / "manager_resources.json")
            if (directory / "manager_resources.json").is_file()
            else {}
        )
        resources = outcome.get("resources", {})
        cpu_values = [report.get("sampled_tree_CPU_seconds")]
        if (
            resources.get("process_cpu_seconds") is not None
            and resources.get("completed_children_cpu_seconds") is not None
            and resources.get("unreaped_children_cpu_seconds_at_forced_stop", 0.0)
            is not None
        ):
            cpu_values.append(
                resources["process_cpu_seconds"]
                + resources["completed_children_cpu_seconds"]
                + resources.get("unreaped_children_cpu_seconds_at_forced_stop", 0.0)
            )
        cpu_values = [float(v) for v in cpu_values if v is not None]
        wall_values = [
            float(v)
            for v in (report.get("elapsed_wall_seconds"), outcome.get("wall_seconds"))
            if v is not None
        ]
        if not cpu_values or not wall_values:
            raise RuntimeError(
                "RESOURCE_ACCOUNTING_INCOMPLETE: retained checkpoints cannot silently receive a fresh budget"
            )
        cpu, wall = max(cpu_values), max(wall_values)
        cpu_total += cpu
        wall_total += wall
        accounts.append(
            {
                "attempt": attempt["number"],
                "CPU_seconds_charged": cpu,
                "wall_seconds_charged": wall,
            }
        )
    remaining = {
        "CPU_seconds": float(limits["CPU_seconds"]) - cpu_total,
        "wall_seconds": float(limits["wall_seconds"]) - wall_total,
        "RSS_MiB": float(limits["RSS_MiB"]),
        "temporary_MiB": float(
            limits.get("temporary_MiB", DEFAULT_LIMITS["temporary_MiB"])
        ),
    }
    if remaining["CPU_seconds"] <= 0 or remaining["wall_seconds"] <= 0:
        raise RuntimeError(
            "TASK_CUMULATIVE_RESOURCE_BUDGET_EXHAUSTED: no automatic enlarged-budget retry"
        )
    return remaining, {
        "CPU_seconds_spent": cpu_total,
        "wall_seconds_spent": wall_total,
        "attempts": accounts,
    }


def git_source_provenance(app_root):
    """Record Git identity when available; source hashes remain authoritative."""
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(app_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        changes = subprocess.check_output(
            [
                "git",
                "-C",
                str(app_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).splitlines()
        return {
            "available": True,
            "commit": commit,
            "worktree_dirty": bool(changes),
            "changes": changes,
            "scope": "repository checkout; exact algorithm identity uses file hashes",
        }
    except (OSError, subprocess.SubprocessError):
        return {
            "available": False,
            "commit": None,
            "worktree_dirty": None,
            "scope": "source archive or packaged application; exact file/executable hashes retained",
        }


def algorithm_fingerprint():
    app_root = Path(__file__).resolve().parents[2]
    files = [
        *sorted((app_root / "app/native_objects").glob("*.py")),
        app_root / "app/core/native_objects_entry.py",
        Path(__file__).resolve(),
        app_root / "app/core/native_worker.py",
        app_root / "app/core/processing.py",
        app_root / "main.py",
    ]
    rows = {str(p.relative_to(app_root)): file_sha(p) for p in files if p.is_file()}
    if getattr(sys, "frozen", False):
        # A bundled program may carry Python in an archive instead of .py
        # files. Bind those tasks to the real executable, not an empty list.
        rows["frozen_application_executable"] = file_sha(sys.executable)
    if not rows:
        raise RuntimeError(
            "Cannot establish native algorithm identity from this installation"
        )
    content = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "files": rows,
        "git": git_source_provenance(app_root),
    }


def worker_command(
    request_path, *, main_path=None, python_executable=None, frozen=None
):
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    executable = str(python_executable or sys.executable)
    if frozen:
        return [executable, "--native-worker", str(Path(request_path).resolve())]
    main = (
        Path(main_path)
        if main_path
        else Path(__file__).resolve().parents[2] / "main.py"
    )
    return [
        executable,
        str(main.resolve()),
        "--native-worker",
        str(Path(request_path).resolve()),
    ]


def _process_identity(pid):
    if psutil is not None:
        try:
            process = psutil.Process(int(pid))
            if process.status() == psutil.STATUS_ZOMBIE:
                return None
            return {
                "pid": int(pid),
                "started": process.create_time(),
                "backend": "psutil",
            }
        except psutil.Error:
            return None
    if os.name == "posix":
        try:
            fields = (
                Path(f"/proc/{int(pid)}/stat").read_text().rsplit(") ", 1)[1].split()
            )
            if fields[0] == "Z":
                return None
            return {
                "pid": int(pid),
                "started": fields[19],
                "backend": "proc_start_ticks",
            }
        except (OSError, IndexError, ValueError):
            return None
    # A packaged Windows release includes psutil. Unknown is not a verified PID.
    return None


def _same_process(identity):
    return bool(identity) and _process_identity(identity["pid"]) == identity


class _WindowsKillJob:
    """Windows descendants die if the GUI exits or closes this job handle."""

    def __init__(self, process):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = (
            0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not handle or not kernel.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            if handle:
                kernel.CloseHandle(handle)
            raise OSError(ctypes.get_last_error(), "Windows job-object setup failed")
        if not kernel.AssignProcessToJobObject(
            handle, wintypes.HANDLE(int(process._handle))
        ):
            kernel.CloseHandle(handle)
            raise OSError(
                ctypes.get_last_error(), "Windows worker could not join its managed job"
            )
        self.handle, self.kernel = handle, kernel

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class NativeJobManager:
    def __init__(self, jobs_root, main_path=None, python_executable=None):
        self.jobs_root = Path(jobs_root).expanduser().resolve()
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.main_path, self.python_executable = main_path, python_executable
        self._lock = threading.RLock()
        self._processes = {}
        self._threads = {}

    def _directory(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", job_id
        ):
            raise ValueError("Invalid job identity")
        return self.jobs_root / job_id

    def _read_state(self, job_id):
        path = self._directory(job_id) / "state.json"
        if not path.is_file():
            raise FileNotFoundError(f"Unknown native task: {job_id}")
        state = read_json(path)
        if state.get("job_id") != job_id:
            raise ValueError("Stored job identity mismatch")
        return state

    def _save_state(self, state):
        state["updated_utc"] = utc_now()
        atomic_json(self._directory(state["job_id"]) / "state.json", state)
        return state

    def create(self, request=None, **kwargs):
        values = dict(request or {})
        values.update(kwargs)
        allowed = {
            "input_path",
            "roi",
            "dpi",
            "page_number",
            "frame_number",
            "orientation",
            "job_id",
            "language",
            "limits",
            "validation_controls",
        }
        extra = set(values) - allowed
        if extra:
            raise ValueError("Unknown task options: " + ", ".join(sorted(extra)))
        language = values.get("language", "eng")
        if language != "eng":
            raise ValueError(
                "This native route currently implements eng OCR; another language is not silently substituted"
            )
        source = Path(values["input_path"]).expanduser().resolve()
        from app.native_objects.job import make_job
        from app.native_objects.source_import import inspect_source, validate_roi

        jid = values.get("job_id") or "job-" + uuid.uuid4().hex
        directory = self._directory(jid)
        if directory.exists():
            raise FileExistsError(
                "Task directory already exists; prior evidence is never replaced"
            )
        job = make_job(
            source,
            directory / "placeholder.dxf",
            values["roi"],
            dpi=values.get("dpi", 200),
            page_number=values.get("page_number"),
            frame_number=values.get("frame_number"),
            orientation=values.get("orientation", 0),
            job_id=jid,
        )
        info = inspect_source(
            source,
            dpi=job.dpi,
            page_number=job.page_number,
            frame_number=job.frame_number,
        )
        validate_roi(job.roi, info["source_size_px"])
        limits = dict(DEFAULT_LIMITS)
        limits.update(values.get("limits") or {})
        if set(limits) != set(DEFAULT_LIMITS) or any(
            isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0
            for v in limits.values()
        ):
            raise ValueError(
                "Explicit CPU/wall/RSS limits must be positive finite values"
            )
        directory.mkdir()
        incoming = directory / "inputs"
        incoming.mkdir()
        saved_input = incoming / ("source" + source.suffix.lower())
        before = file_sha(source)
        temporary = saved_input.with_suffix(saved_input.suffix + ".tmp")
        shutil.copyfile(source, temporary)
        if file_sha(source) != before or file_sha(temporary) != before:
            raise ValueError(
                "Input changed while being captured; no conversion was started"
            )
        os.replace(temporary, saved_input)
        algorithm = algorithm_fingerprint()
        parameters = {
            "roi": list(job.roi),
            "dpi": job.dpi,
            "page_number": job.page_number,
            "frame_number": job.frame_number,
            "orientation": job.orientation_cw,
            "language": language,
        }
        from app.native_objects.observation_cache import (
            ENVIRONMENT_VARIABLE,
            cache_binding,
        )

        supplied_raw_cache = os.environ.get(ENVIRONMENT_VARIABLE)
        raw_cache = cache_binding(
            supplied_raw_cache or directory / "raw_observations",
            create=not bool(supplied_raw_cache),
        )
        raw_cache["selection"] = (
            "explicit_environment" if supplied_raw_cache else "new_task_local_cache"
        )
        state = {
            "schema": "native-persistent-job-v4",
            "job_id": jid,
            "created_utc": utc_now(),
            "status": "QUEUED",
            "stage": "QUEUED",
            "progress": 0.0,
            "attempt": 0,
            "original_input_path": str(source),
            "input_path": str(saved_input),
            "source_sha256": before,
            "parameters": parameters,
            "algorithm": algorithm,
            "limits": limits,
            "ocr_threads": 1,
            "raw_observation_cache": raw_cache,
            "processing_location": "computer_running_this_application",
            "remote_service_calls": 0,
            "remote_wait_seconds": 0,
            "review_capability": "local OCR, deterministic source rules, saved-DXF audit; no chat vision service",
            "validation_controls": values.get("validation_controls") or {},
            "result_dxf": None,
            "preview_path": None,
            "source_roi_path": None,
            "quality_path": None,
            "evidence_dir": None,
            "error": None,
            "attempts": [],
            "production_GO": False,
        }
        atomic_json(
            directory / "input_manifest.json",
            {
                "source_sha256": before,
                "original_path": str(source),
                "saved_input_path": str(saved_input),
                "source_size_bytes": saved_input.stat().st_size,
                "selection": info,
                "parameters": parameters,
                "external_cache_or_review_list_supplied": False,
            },
        )
        return dict(self._save_state(state))

    def import_completed_checkpoint(self, job_id, source_job, *, stop_record):
        """Bind a verified stopped task to a new, explicitly budgeted task.

        This is not a cache/approval-list option on fresh conversion. The
        importer verifies immutable source, stage producers and raw OCR, and
        copies only text checkpoint evidence into this new task. Old state and
        resource accounting are retained, never relabelled as successful.
        """
        with self._lock:
            state = self._read_state(job_id)
            if (
                state["status"] != "QUEUED"
                or state["attempt"]
                or state.get("checkpoint_import")
            ):
                raise RuntimeError("CHECKPOINT_IMPORT_REQUIRES_NEW_UNSTARTED_TASK")
            from app.native_objects.resume_checkpoint import prepare_checkpoint_import

            imported = prepare_checkpoint_import(
                source_job,
                self._directory(job_id),
                stop_record=stop_record,
                current_parameters=state["parameters"],
                captured_input_path=state["input_path"],
                expected_source_sha256=state["source_sha256"],
            )
            state["checkpoint_import"] = imported
            state["resume_mode"] = "VERIFIED_TEXT_CHECKPOINT_NEW_RESOURCE_CONTRACT"
            return dict(self._save_state(state))

    def import_revision_checkpoint(self, job_id, source_job, *, budget_adjustment):
        """Reuse validated raw evidence in a distinct task, never old adoption."""
        with self._lock:
            state = self._read_state(job_id)
            if (
                state["status"] != "QUEUED"
                or state["attempt"]
                or any(
                    state.get(k)
                    for k in (
                        "checkpoint_import",
                        "compatible_resume",
                        "revision_import",
                    )
                )
            ):
                raise RuntimeError("REVISION_IMPORT_REQUIRES_NEW_UNSTARTED_TASK")
            from app.native_objects.revision_resume import prepare_revision_resume

            imported = prepare_revision_resume(
                source_job,
                self._directory(job_id),
                current_parameters=state["parameters"],
                captured_input_path=state["input_path"],
                budget_adjustment=budget_adjustment,
            )
            state["revision_import"] = imported
            state["resume_mode"] = "PUBLISHED_RAW_EVIDENCE_CURRENT_ADOPTION_REQUIRED"
            return dict(self._save_state(state))

    def resume_compatible_checkpoint(self, job_id):
        """Explicit continuation after a verified execution-budget defect.

        Completed producers must remain byte-identical. The old request, failed
        attempt and source snapshot are immutable; the existing cumulative
        resource contract is not reset or enlarged by this operation.
        """
        with self._lock:
            state = self.poll(job_id)
            if state["status"] not in {"FAILED", "RESOURCE_STOP", "INTERRUPTED"}:
                raise RuntimeError("COMPATIBLE_RESUME_REQUIRES_STOPPED_TASK")
            from app.native_objects.compatible_resume import prepare_compatible_resume

            current = algorithm_fingerprint()
            prepared = prepare_compatible_resume(
                self._directory(job_id), current_algorithm=current
            )
            state.setdefault("algorithm_history", []).append(
                {
                    "algorithm": state["algorithm"],
                    "through_attempt": state["attempt"],
                    "reason": "legacy_internal_budget_contract_repair",
                    "compatibility_receipt": prepared["receipt_path"],
                    "receipt_sha256": prepared["receipt_sha256"],
                }
            )
            state["algorithm"] = current
            state["compatible_resume"] = prepared
            self._save_state(state)
        return self._launch(job_id, resume=True)

    def _launch(self, job_id, resume=False):
        with self._lock:
            state = self.poll(job_id)
            tracked = self._processes.get(job_id)
            if tracked and tracked["process"].poll() is None:
                raise RuntimeError(
                    "Previous worker is still finishing; wait for process cleanup before resume"
                )
            if state["status"] in ACTIVE:
                raise RuntimeError("This task is already running")
            if state["status"] == "COMPLETED_WITH_ISSUES":
                raise RuntimeError(
                    "Completed task is immutable; start a new task for changed input"
                )
            if not resume and state["attempt"]:
                raise RuntimeError(
                    "Use the explicit resume action for an interrupted task"
                )
            if file_sha(state["input_path"]) != state["source_sha256"]:
                raise ValueError("JOB_SOURCE_CHANGED_START_NEW_TASK")
            if algorithm_fingerprint()["sha256"] != state["algorithm"]["sha256"]:
                raise ValueError("ALGORITHM_CHANGED_START_NEW_TASK_AND_REVIEW")
            if any(
                s["status"] in ACTIVE for s in self.list_jobs() if s["job_id"] != job_id
            ):
                raise RuntimeError(
                    "Another native conversion is active; this manager runs one heavy task at a time"
                )
            if psutil is None:
                raise RuntimeError(
                    "RESOURCE_MONITOR_UNAVAILABLE: CPU and tree RSS enforcement are required before conversion"
                )
            limits, consumed = remaining_budget(state["attempts"], state["limits"])
            revision = state.get("revision_import")
            if revision:
                from app.native_objects.revision_resume import verify_revision_receipt

                if file_sha(revision["receipt_path"]) != revision["receipt_sha256"]:
                    raise ValueError("REVISION_IMPORT_RECEIPT_CHANGED")
                verified = verify_revision_receipt(
                    revision["receipt_path"],
                    target_job=self._directory(job_id),
                    source_sha256=state["source_sha256"],
                    current_parameters=state["parameters"],
                )
                ledger = verified["budget_ledger"]
                if (
                    ledger["original_contract"] != state["limits"]
                    or ledger != revision["budget_ledger"]
                ):
                    raise ValueError("REVISION_RESOURCE_CONTRACT_CHANGED")
                limits["CPU_seconds"] -= ledger["CPU_seconds_budget_charge"]
                limits["wall_seconds"] -= ledger["wall_seconds_budget_charge"]
                consumed["revision_prior_budget"] = ledger
                if limits["CPU_seconds"] <= 0 or limits["wall_seconds"] <= 0:
                    raise RuntimeError("REVISION_CUMULATIVE_RESOURCE_BUDGET_EXHAUSTED")
            previous = (
                Path(state["attempts"][-1]["directory"])
                if resume and state["attempts"]
                else None
            )
            attempt = state["attempt"] + 1
            directory = self._directory(job_id) / "attempts" / f"{attempt:04d}"
            directory.mkdir(parents=True, exist_ok=False)
            staging = directory / "staging"
            staging.mkdir()
            previous_evidence = previous / "staging/evidence" if previous else None
            if revision and not previous:
                previous_evidence = Path(revision["resume_evidence"])
            imported = state.get("checkpoint_import") if not previous else None
            if imported:
                from app.native_objects.resume_checkpoint import verify_import_receipt

                if file_sha(imported["receipt_path"]) != imported["receipt_sha256"]:
                    raise ValueError("IMPORTED_CHECKPOINT_RECEIPT_CHANGED")
                verify_import_receipt(
                    imported["receipt_path"],
                    target_job=self._directory(job_id),
                    source_sha256=state["source_sha256"],
                    current_parameters=state["parameters"],
                )
                previous_evidence = Path(imported["resume_evidence"])
            compatible = state.get("compatible_resume")
            if (
                compatible
                and compatible.get("prior_attempt_number") == state["attempt"]
            ):
                from app.native_objects.compatible_resume import (
                    verify_compatible_receipt,
                )

                if file_sha(compatible["receipt_path"]) != compatible["receipt_sha256"]:
                    raise ValueError("COMPATIBLE_RESUME_RECEIPT_CHANGED")
                verify_compatible_receipt(
                    compatible["receipt_path"],
                    job_directory=self._directory(job_id),
                    current_algorithm=state["algorithm"],
                )
                previous_evidence = Path(compatible["resume_evidence"])
            cache = (
                previous_evidence
                if previous_evidence
                and (previous_evidence / "completed_stages.json").is_file()
                else None
            )
            from app.native_objects.observation_cache import (
                ENVIRONMENT_VARIABLE,
                verify_binding,
            )

            raw_cache = state.get("raw_observation_cache")
            if raw_cache:
                raw_cache = {
                    **verify_binding(raw_cache, check_inventory=False),
                    "selection": raw_cache["selection"],
                }
            request = {
                "schema": "native-worker-request-v4",
                "job_id": job_id,
                "attempt": attempt,
                "job_directory": str(self._directory(job_id)),
                "attempt_directory": str(directory),
                "input_path": state["input_path"],
                "source_sha256": state["source_sha256"],
                "parameters": state["parameters"],
                "algorithm": state["algorithm"],
                "limits": limits,
                "task_limits": state["limits"],
                "prior_resource_consumption": consumed,
                "staging_directory": str(staging),
                "cache_dir": str(cache) if cache else None,
                "resume_evidence": str(previous_evidence)
                if previous_evidence
                else None,
                "parent_pid": os.getpid(),
                "validation_controls": state["validation_controls"],
                "external_cache_or_review_list_supplied": False,
                "raw_observation_cache": raw_cache,
            }
            request["checkpoint_import"] = state.get("checkpoint_import")
            request["compatible_resume"] = compatible
            request["revision_import"] = revision
            path = directory / "request.json"
            atomic_json(path, request)
            command = worker_command(
                path, main_path=self.main_path, python_executable=self.python_executable
            )
            env = dict(os.environ)
            if raw_cache:
                env[ENVIRONMENT_VARIABLE] = raw_cache["root"]
            else:
                env.pop(ENVIRONMENT_VARIABLE, None)
            env.update(
                OMP_NUM_THREADS="1",
                OMP_THREAD_LIMIT="1",
                OPENBLAS_NUM_THREADS="1",
                MKL_NUM_THREADS="1",
                PYTHONUNBUFFERED="1",
            )
            app_root = str(Path(__file__).resolve().parents[2])
            inherited = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = app_root + (os.pathsep + inherited if inherited else "")
            stdout = (directory / "worker.stdout.txt").open("x", encoding="utf-8")
            stderr = (directory / "worker.stderr.txt").open("x", encoding="utf-8")
            options = (
                {"start_new_session": True}
                if os.name == "posix"
                else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            )
            try:
                process = subprocess.Popen(
                    command,
                    cwd=directory,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    **options,
                )
                windows_job = _WindowsKillJob(process)
            except Exception as exc:
                if "process" in locals() and process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                state.update(
                    status="FAILED",
                    stage="WORKER_LAUNCH_FAILED",
                    attempt=attempt,
                    attempt_directory=str(directory),
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "automatic_retry": False,
                        "partial_files_retained_unpublished": True,
                    },
                )
                state["attempts"].append(
                    {
                        "number": attempt,
                        "directory": str(directory),
                        "request_sha256": file_sha(path),
                        "command": command,
                        "launch_failed": True,
                    }
                )
                atomic_json(
                    directory / "manager_resources.json",
                    {
                        "elapsed_wall_seconds": 0.0,
                        "sampled_tree_CPU_seconds": 0.0
                        if "process" not in locals()
                        else None,
                        "sampled_tree_peak_RSS_bytes": None,
                        "monitor_backend": "worker_launch_failed",
                        "no_worker_launched": "process" not in locals(),
                        "final_status": "FAILED",
                    },
                )
                self._save_state(state)
                raise
            finally:
                stdout.close()
                stderr.close()
            identity = _process_identity(process.pid)
            state.update(
                status="STARTING",
                stage="STARTING_WORKER",
                progress=0.0,
                attempt=attempt,
                attempt_directory=str(directory),
                process_identity=identity,
                pid=process.pid,
                started_utc=utc_now(),
                error=None,
                cancel_requested_monotonic=None,
                resume_mode="OWN_COMPLETED_STAGE"
                if cache
                else ("OWN_PARTIAL_OCR" if previous else "EMPTY_TASK_NO_CACHE"),
            )
            state["attempts"].append(
                {
                    "number": attempt,
                    "directory": str(directory),
                    "request_sha256": file_sha(path),
                    "command": command,
                    "resume_cache": str(cache) if cache else None,
                }
            )
            self._save_state(state)
            self._processes[job_id] = {
                "process": process,
                "windows_job": windows_job,
                "started": time.monotonic(),
                "peak_tree_RSS_bytes": 0,
                "peak_tree_CPU_seconds": 0.0,
                "peak_temporary_bytes": 0,
                "last_disk_sample": -1.0,
                "observed_process_CPU": {},
                "resource_samples": 0,
                "resource_monitor": "psutil" if psutil else "unavailable",
                "limits": limits,
                "prior_resource_consumption": consumed,
                "last_resource_checkpoint": 0.0,
            }
            thread = threading.Thread(
                target=self._monitor,
                args=(job_id,),
                name="native-job-" + job_id,
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
            return dict(state)

    def start(self, job_id):
        return self._launch(job_id, resume=False)

    def resume(self, job_id):
        state = self.poll(job_id)
        if state["status"] not in {
            "CANCELLED",
            "INTERRUPTED",
            "FAILED",
            "RESOURCE_STOP",
        }:
            raise RuntimeError("Only stopped tasks can be explicitly resumed")
        if state["status"] == "RESOURCE_STOP":
            raise RuntimeError(
                "Resource-limited task is retained; no automatic enlarged-budget retry"
            )
        return self._launch(job_id, resume=True)

    def _stop_tree(self, job_id, force=False):
        tracked = self._processes.get(job_id)
        state = self._read_state(job_id)
        pid = state.get("pid")
        if not pid:
            return
        process = tracked["process"] if tracked else None
        if not process and not _same_process(state.get("process_identity")):
            return
        if os.name == "posix":
            try:
                os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif tracked and tracked["windows_job"].handle:
            tracked["windows_job"].close()
        else:
            # Arguments identify only this recorded worker, never a name wildcard.
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
            )

    def cancel(self, job_id, reason="user"):
        with self._lock:
            state = self.poll(job_id)
            if state["status"] not in ACTIVE:
                return state
            directory = Path(state["attempt_directory"])
            if not (directory / "cancel.json").exists():
                atomic_json(
                    directory / "cancel.json",
                    {
                        "reason": str(reason),
                        "requested_utc": utc_now(),
                        "job_id": job_id,
                    },
                )
            state.update(
                status="CANCEL_REQUESTED",
                cancel_reason=str(reason),
                cancel_requested_monotonic=time.monotonic(),
            )
            return dict(self._save_state(state))

    def _monitor(self, job_id):
        tracked = self._processes[job_id]
        try:
            while tracked["process"].poll() is None:
                with self._lock:
                    state = self._read_state(job_id)
                    if psutil is not None:
                        try:
                            process = psutil.Process(tracked["process"].pid)
                            tree = [process] + process.children(recursive=True)
                            rss = 0
                            for item in tree:
                                try:
                                    key = (item.pid, item.create_time())
                                    times = item.cpu_times()
                                    tracked["observed_process_CPU"][key] = (
                                        times.user + times.system
                                    )
                                    rss += item.memory_info().rss
                                except psutil.Error:
                                    continue
                            cpu = sum(tracked["observed_process_CPU"].values())
                            tracked["peak_tree_RSS_bytes"] = max(
                                tracked["peak_tree_RSS_bytes"], rss
                            )
                            tracked["peak_tree_CPU_seconds"] = max(
                                tracked["peak_tree_CPU_seconds"], cpu
                            )
                            tracked["resource_samples"] += 1
                        except psutil.Error:
                            pass
                    elapsed = time.monotonic() - tracked["started"]
                    if elapsed - tracked["last_resource_checkpoint"] >= 0.5:
                        atomic_json(
                            Path(state["attempt_directory"])
                            / "resource_heartbeat.json",
                            {
                                "observed_utc": utc_now(),
                                "elapsed_wall_seconds": elapsed,
                                "sampled_tree_CPU_seconds": tracked[
                                    "peak_tree_CPU_seconds"
                                ],
                                "sampled_tree_peak_RSS_bytes": tracked[
                                    "peak_tree_RSS_bytes"
                                ],
                                "not_a_final_resource_account": True,
                            },
                        )
                        tracked["last_resource_checkpoint"] = elapsed
                    limits = tracked["limits"]
                    if elapsed - tracked["last_disk_sample"] >= 1.0:
                        size = 0
                        for artifact in self._directory(job_id).rglob("*"):
                            try:
                                if artifact.is_file() and not artifact.is_symlink():
                                    size += artifact.stat().st_size
                            except FileNotFoundError:
                                pass  # A just-published directory may have moved.
                        tracked["peak_temporary_bytes"] = max(
                            tracked["peak_temporary_bytes"], size
                        )
                        tracked["last_disk_sample"] = elapsed
                    cause = (
                        "WALL_LIMIT"
                        if elapsed > limits["wall_seconds"]
                        else "CPU_LIMIT"
                        if tracked["peak_tree_CPU_seconds"] > limits["CPU_seconds"]
                        else "RSS_LIMIT"
                        if tracked["peak_tree_RSS_bytes"]
                        > limits["RSS_MiB"] * 1024 * 1024
                        else "TEMPORARY_LIMIT"
                        if tracked["peak_temporary_bytes"]
                        > limits["temporary_MiB"] * 1024 * 1024
                        else None
                    )
                    if cause and state["status"] != "CANCEL_REQUESTED":
                        self.cancel(job_id, "RESOURCE_STOP:" + cause)
                        state = self._read_state(job_id)
                    cancelled_at = state.get("cancel_requested_monotonic")
                    if (
                        state["status"] == "CANCEL_REQUESTED"
                        and cancelled_at is not None
                    ):
                        age = time.monotonic() - cancelled_at
                        if age > 2:
                            self._stop_tree(job_id, force=age > 3)
                    self._refresh(job_id)
                time.sleep(0.1)
            tracked["process"].wait()
        finally:
            # A worker that crashes before its finally block must not leave
            # an OCR child alive. This group was created only for this worker.
            self._stop_tree(job_id, force=True)
            tracked["windows_job"].close()
            with self._lock:
                state = self._refresh(job_id)
                report = {
                    "elapsed_wall_seconds": time.monotonic() - tracked["started"],
                    "sampled_tree_peak_RSS_bytes": tracked["peak_tree_RSS_bytes"]
                    if tracked["resource_samples"]
                    else None,
                    "sampled_tree_CPU_seconds": tracked["peak_tree_CPU_seconds"]
                    if tracked["resource_samples"]
                    else None,
                    "samples": tracked["resource_samples"],
                    "monitor_backend": tracked["resource_monitor"],
                    "sampled_peak_temporary_bytes": tracked["peak_temporary_bytes"],
                    "temporary_scope": "all task files including captured input and retained attempts",
                    "CPU_scope": "sum of maximum observed own CPU per child PID/start identity; sampling can miss very short lived children",
                    "exit_code": tracked["process"].returncode,
                    "limits": tracked["limits"],
                    "prior_resource_consumption": tracked["prior_resource_consumption"],
                    "final_status": state["status"],
                    "automatic_retry": False,
                }
                atomic_json(
                    Path(state["attempt_directory"]) / "manager_resources.json", report
                )

    def _recover_committed_result(self, state):
        """Recover the rename/outcome crash window only from a verified commit.

        Directory existence, a preview, or the worker exit code alone cannot
        establish completion. This performs the same saved-candidate gates as
        the worker, plus every byte hash committed in its manifest.
        """
        published = (
            self._directory(state["job_id"]) / "results" / f"{state['attempt']:04d}"
        )
        if not published.exists():
            return None
        manifest = read_json(published / "publication_manifest.json")
        identity = {
            "job_id": state["job_id"],
            "attempt": state["attempt"],
            "source_sha256": state["source_sha256"],
            "algorithm_sha256": state["algorithm"]["sha256"],
        }
        if (
            manifest.get("schema") != "native-atomic-publication-v4"
            or manifest.get("identity") != identity
        ):
            raise ValueError("COMMIT_RECOVERY_IDENTITY_MISMATCH")
        if file_sha(state["input_path"]) != state["source_sha256"]:
            raise ValueError("COMMIT_RECOVERY_SOURCE_CHANGED")
        if algorithm_fingerprint()["sha256"] != state["algorithm"]["sha256"]:
            raise ValueError("COMMIT_RECOVERY_VERSION_CHANGED_REVIEW_PENDING")
        files = manifest.get("files", {})
        required = {
            "result.dxf",
            "result.objects.json",
            "evidence/quality_review.json",
            "evidence/cold_audit.json",
        }
        if not required.issubset(files):
            raise ValueError("COMMIT_RECOVERY_REQUIRED_ARTIFACT_MISSING")
        for name, expected in files.items():
            path = (published / name).resolve()
            if published not in path.parents or not path.is_file():
                raise ValueError(
                    "COMMIT_RECOVERY_ARTIFACT_MISSING_OR_OUTSIDE_RESULT:" + name
                )
            if (
                path.stat().st_size != expected["bytes"]
                or file_sha(path) != expected["sha256"]
            ):
                raise ValueError("COMMIT_RECOVERY_ARTIFACT_CHANGED:" + name)
        from app.core.native_worker import _saved_candidate_gates

        gates = _saved_candidate_gates(published, {"input_path": state["input_path"]})
        recovered = {
            "job_id": state["job_id"],
            "attempt": state["attempt"],
            "status": "COMPLETED_WITH_ISSUES",
            "stage": "RECOVERED_VERIFIED_COMMIT",
            "progress": 1.0,
            "finished_utc": utc_now(),
            "result_dxf": str(published / "result.dxf"),
            "preview_path": str(published / "result.png"),
            "source_roi_path": str(published / "evidence/quality_source_roi.png"),
            "quality_path": str(published / "evidence/quality_review.json"),
            "issues_path": str(published / "evidence/quality_issues.json"),
            "evidence_dir": str(published / "evidence"),
            "result_directory": str(published),
            "publication_manifest": str(published / "publication_manifest.json"),
            "result_sha256": gates["cold_DXF_sha256"],
            "source_unchanged": True,
            "requires_manual_review": gates["requires_manual_review"],
            "formal_entities": gates["formal_entities"],
            "production_GO": False,
            "error": None,
            "commit_recovery": {
                "directory_existence_alone_accepted": False,
                "manifest_files_hash_verified": len(files),
                "saved_DXF_and_current_review_gates": gates,
                "worker_final_outcome_was_missing": True,
                "recognition_or_render_reexecuted": False,
            },
        }
        directory = Path(state["attempt_directory"])
        atomic_json(directory / "commit_recovery.json", recovered["commit_recovery"])
        atomic_json(directory / "outcome.json", recovered)
        return recovered

    def _refresh(self, job_id):
        state = self._read_state(job_id)
        directory = (
            Path(state["attempt_directory"]) if state.get("attempt_directory") else None
        )
        if directory:
            outcome = directory / "outcome.json"
            progress = directory / "progress.json"
            if outcome.is_file():
                result = read_json(outcome)
                if (
                    result.get("job_id") != job_id
                    or result.get("attempt") != state["attempt"]
                ):
                    raise ValueError("Worker outcome identity mismatch")
                state.update(result)
            elif state["status"] in ACTIVE:
                if progress.is_file():
                    row = read_json(progress)
                    state.update(
                        stage=row.get("stage", state["stage"]),
                        progress=row.get("progress", state["progress"]),
                        active_children=row.get("active_children", []),
                    )
                    if state["status"] == "STARTING":
                        state["status"] = "RUNNING"
                tracked = self._processes.get(job_id)
                alive = (
                    tracked["process"].poll() is None
                    if tracked
                    else _same_process(state.get("process_identity"))
                )
                if not alive:
                    try:
                        recovered = self._recover_committed_result(state)
                    except Exception as exc:
                        recovered = None
                        recovery_error = {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "published_files_preserved": True,
                            "automatic_retry": False,
                        }
                        atomic_json(
                            directory / "commit_recovery_rejected.json", recovery_error
                        )
                    else:
                        recovery_error = None
                    if recovered:
                        state.update(recovered)
                        return self._save_state(state)
                    reason = state.get("cancel_reason")
                    if reason:
                        status = (
                            "RESOURCE_STOP"
                            if reason.startswith("RESOURCE_STOP:")
                            else "CANCELLED"
                        )
                        error = {
                            "type": "FORCED_TREE_STOP",
                            "message": reason,
                            "valid_checkpoints_retained": True,
                        }
                    else:
                        status, error = (
                            "INTERRUPTED",
                            {
                                "type": "WORKER_EXIT_WITHOUT_OUTCOME",
                                "message": "Worker stopped before an audited result; partial files are not published",
                            },
                        )
                    if recovery_error:
                        error["commit_recovery_rejection"] = recovery_error
                    state.update(status=status, error=error, finished_utc=utc_now())
        return self._save_state(state)

    def poll(self, job_id):
        with self._lock:
            return dict(self._refresh(job_id))

    def list_jobs(self):
        with self._lock:
            rows = []
            for path in sorted(self.jobs_root.glob("*/state.json")):
                rows.append(self._refresh(path.parent.name))
            return sorted(rows, key=lambda row: row["created_utc"], reverse=True)

    def list(self):
        return self.list_jobs()

    def shutdown(self, cancel_running=True, timeout=4.0):
        if cancel_running:
            for row in self.list_jobs():
                if row["status"] in ACTIVE:
                    self.cancel(row["job_id"], "application_exit")
        end = time.monotonic() + timeout
        for thread in self._threads.values():
            thread.join(max(0, end - time.monotonic()))
        return self.list_jobs()

    def export(self, job_id, destination):
        """Validate the published result, then publish a new DXF last."""
        state = self.poll(job_id)
        if state["status"] != "COMPLETED_WITH_ISSUES" or not state.get("result_dxf"):
            raise RuntimeError(
                "No completely saved and audited result is available to export"
            )
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.lower() != ".dxf":
            raise ValueError("Export destination must be a new DXF path")
        if destination.exists():
            raise FileExistsError("Existing successful output is never overwritten")
        if (
            self._directory(job_id) == destination
            or self._directory(job_id) in destination.parents
        ):
            raise ValueError("Export outside the immutable task directory")
        source = Path(state["result_dxf"])
        from app.native_objects.review_binding import verify_saved_review

        objects = read_json(source.with_suffix(".objects.json"))["objects"]
        imported = read_json(Path(state["evidence_dir"]) / "import_manifest.json")
        binding = verify_saved_review(
            state["quality_path"],
            source,
            objects,
            imported,
            source_path=state["input_path"],
        )
        if not binding["valid"]:
            raise ValueError(
                "STALE_REVIEW_PENDING: export requires this exact input, candidate and version"
            )
        import ezdxf

        doc = ezdxf.readfile(source)
        audit = doc.audit()
        if audit.errors or audit.fixes:
            raise ValueError("Published DXF no longer passes a cold-read audit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / (
            "." + destination.name + ".export-" + uuid.uuid4().hex
        )
        temporary.mkdir()
        companion_name = destination.stem + ".native"
        companion_target = destination.parent / companion_name
        companion = temporary / companion_name
        files = {
            destination.name: source,
            destination.stem + ".objects.json": source.with_suffix(".objects.json"),
            "DejaVuSans.ttf": source.parent / "DejaVuSans.ttf",
            "FONT_LICENSE_DejaVu.txt": source.parent / "FONT_LICENSE_DejaVu.txt",
        }
        created = []
        created_directories = []
        try:
            if companion_target.exists():
                raise FileExistsError("Export evidence directory already exists")
            # Review assets use paths relative to evidence/. Preserve the
            # complete layout and original bytes, including rendered output,
            # instead of exporting a review JSON with broken dependencies.
            shutil.copytree(source.parent, companion)
            captured_source = companion / "task_input" / Path(state["input_path"]).name
            captured_source.parent.mkdir()
            shutil.copyfile(state["input_path"], captured_source)
            copied_binding = verify_saved_review(
                companion / "evidence/quality_review.json",
                companion / "result.dxf",
                objects,
                imported,
                source_path=captured_source,
            )
            if not copied_binding["valid"]:
                raise ValueError(
                    "Export evidence copy failed current input and dependency binding"
                )
            for name, original in files.items():
                if not original.is_file():
                    raise FileNotFoundError(
                        "Required export dependency missing: " + str(original)
                    )
                target = destination.parent / name
                if target.exists() and (
                    name not in {"DejaVuSans.ttf", "FONT_LICENSE_DejaVu.txt"}
                    or file_sha(target) != file_sha(original)
                ):
                    raise FileExistsError(
                        "Export would overwrite another artifact: " + str(target)
                    )
                shutil.copyfile(original, temporary / name)
                if file_sha(temporary / name) != file_sha(original):
                    raise ValueError("Export copy hash mismatch")
            copied_doc = ezdxf.readfile(temporary / destination.name)
            copied_audit = copied_doc.audit()
            if copied_audit.errors or copied_audit.fixes:
                raise ValueError("Temporary export failed actual DXF cold read")
            manifest = {
                "job_id": job_id,
                "source_sha256": state["source_sha256"],
                "algorithm": state["algorithm"],
                "DXF_sha256": file_sha(source),
                "review_binding": binding,
                "files": {name: file_sha(temporary / name) for name in files},
                "evidence_package": companion_name,
                "evidence_files": {
                    p.relative_to(companion).as_posix(): file_sha(p)
                    for p in sorted(companion.rglob("*"))
                    if p.is_file()
                },
                "review_path": companion_name + "/evidence/quality_review.json",
                "issues_path": companion_name + "/evidence/quality_issues.json",
                "captured_source_path": companion_name
                + "/task_input/"
                + captured_source.name,
                "commit_marker": destination.name,
                "DXF_is_published_last": True,
                "status": "AUDITED_CANDIDATE_WITH_EXPLICIT_PENDING_NOT_PRODUCT_GO",
                "source_result_unchanged": True,
            }
            manifest_name = destination.stem + ".export.json"
            if (destination.parent / manifest_name).exists():
                raise FileExistsError("Export manifest already exists")
            atomic_json(temporary / manifest_name, manifest)
            # Reserve a new directory exclusively. All linked files were
            # completely copied and verified in temporary storage first.
            companion_target.mkdir(exist_ok=False)
            created_directories.append(companion_target)
            for original in sorted(companion.rglob("*")):
                target = companion_target / original.relative_to(companion)
                if original.is_dir():
                    target.mkdir(exist_ok=False)
                    created_directories.append(target)
                else:
                    os.link(original, target)
                    created.append(target)
            # Exclusive hard links publish complete same-volume files. The DXF
            # becomes visible last; no platform-dependent overwrite rename.
            for name in [n for n in files if n != destination.name] + [
                manifest_name,
                destination.name,
            ]:
                target = destination.parent / name
                if target.exists():
                    if name in {
                        "DejaVuSans.ttf",
                        "FONT_LICENSE_DejaVu.txt",
                    } and file_sha(target) == file_sha(temporary / name):
                        continue
                    raise FileExistsError(
                        "Export destination appeared during publication: " + str(target)
                    )
                os.link(temporary / name, target)
                created.append(target)
            return {
                "dxf_path": str(destination),
                "manifest_path": str(destination.parent / manifest_name),
                "evidence_dir": str(companion_target),
                "quality_path": str(companion_target / "evidence/quality_review.json"),
                "sha256": file_sha(destination),
                "status": "EXPORTED_WITH_EXPLICIT_PENDING",
            }
        except Exception:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            for path in reversed(created_directories):
                try:
                    path.rmdir()
                except OSError:
                    # Leave any independently added file alone.
                    pass
            raise
        finally:
            shutil.rmtree(temporary)
