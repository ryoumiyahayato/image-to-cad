"""One native job attempt, selected before any desktop imports.

Both source and PyInstaller programs dispatch --native-worker REQUEST here.
Only a fully saved, cold-read and current-review-bound directory is published.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback

from app.native_objects.offline_runtime import (
    prepare_onnx_privacy,
    runtime_privacy_status,
)
from app.native_objects.execution import (
    NativeCancelled,
    NativeResourceLimit,
    atomic_json,
    boundary,
    check_cancel,
    file_sha,
    read_json,
    use_context,
    utc_now,
)


def _watch_parent(request, directory, resource_start):
    """POSIX companion to Windows JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.

    Ordinary exits cancel cooperatively. If the desktop disappears during a
    blocking native call, record the last resource account and stop only this
    worker's dedicated session after a short grace period.
    """
    finished = threading.Event()
    if (
        os.name != "posix"
        or os.getpgrp() != os.getpid()
        or not request.get("parent_pid")
    ):
        return finished, None

    def watch():
        while not finished.wait(0.1):
            if os.getppid() == request["parent_pid"]:
                continue
            token = directory / "cancel.json"
            if not token.exists():
                atomic_json(
                    token,
                    {
                        "reason": "parent_application_exited",
                        "requested_utc": utc_now(),
                        "job_id": request["job_id"],
                    },
                )
            if finished.wait(2.0):
                return
            from app.native_objects.platform_stats import elapsed

            resources = elapsed(resource_start)
            try:
                import psutil

                live_cpu = 0.0
                for child in psutil.Process().children(recursive=True):
                    try:
                        usage = child.cpu_times()
                        live_cpu += usage.user + usage.system
                    except psutil.Error:
                        pass
                resources["unreaped_children_cpu_seconds_at_forced_stop"] = live_cpu
            except ImportError:
                resources["unreaped_children_cpu_seconds_at_forced_stop"] = None
            interruption = {
                "job_id": request["job_id"],
                "attempt": request["attempt"],
                "status": "INTERRUPTED",
                "stage": "PARENT_EXIT_FORCED_TREE_STOP",
                "progress": 0.0,
                "finished_utc": utc_now(),
                "wall_seconds": resources["wall_seconds"],
                "resources": resources,
                "production_GO": False,
                "error": {
                    "type": "PARENT_EXIT_FORCED_TREE_STOP",
                    "valid_checkpoints_retained": True,
                    "partial_files_retained_unpublished": True,
                    "automatic_retry": False,
                    "published_directory_if_committed_is_never_removed": True,
                },
            }
            atomic_json(directory / "parent_exit.json", interruption)
            if not (directory / "outcome.json").exists():
                atomic_json(directory / "outcome.json", interruption)
            os.killpg(os.getpgrp(), signal.SIGKILL)
            return

    thread = threading.Thread(target=watch, name="native-parent-watchdog", daemon=True)
    thread.start()
    return finished, thread


def _validate_request(path):
    from app.core.native_job_manager import algorithm_fingerprint

    path = Path(path).resolve()
    request = read_json(path)
    if request.get("schema") != "native-worker-request-v4":
        raise ValueError("Unsupported native worker request")
    directory = Path(request["attempt_directory"]).resolve()
    job = Path(request["job_directory"]).resolve()
    staging = Path(request["staging_directory"]).resolve()
    source = Path(request["input_path"]).resolve()
    if (
        path.parent != directory
        or directory.parent.parent != job
        or staging != directory / "staging"
    ):
        raise ValueError("Worker paths are not inside the declared task attempt")
    if (
        source.parent != job / "inputs"
        or not source.is_file()
        or file_sha(source) != request["source_sha256"]
    ):
        raise ValueError("Worker source is not the captured immutable task input")
    if request["algorithm"]["sha256"] != algorithm_fingerprint()["sha256"]:
        raise ValueError(
            "Worker code changed after task creation; start a newly reviewed task"
        )
    for key in ("cache_dir", "resume_evidence"):
        value = request.get(key)
        if value:
            candidate = Path(value).resolve()
            if (
                job not in candidate.parents
                or directory in candidate.parents
                or not candidate.is_dir()
            ):
                raise ValueError("Resume evidence must be a prior attempt in this task")
    if request.get("external_cache_or_review_list_supplied") is not False:
        raise ValueError(
            "This desktop worker does not accept developer cache or whitelist inputs"
        )
    if request.get("connection_checkpoint") is not None:
        from app.native_objects.connection_checkpoint import verify_captured_checkpoint

        verify_captured_checkpoint(
            request["connection_checkpoint"],
            job,
            request["source_sha256"],
            request["parameters"],
        )
    from app.native_objects.observation_cache import (
        ENVIRONMENT_VARIABLE,
        verify_binding,
    )

    raw_cache = request.get("raw_observation_cache")
    if raw_cache:
        verify_binding(raw_cache)
        if (
            Path(os.environ.get(ENVIRONMENT_VARIABLE, "")).resolve()
            != Path(raw_cache["root"]).resolve()
        ):
            raise ValueError("RAW_OBSERVATION_CACHE_ENVIRONMENT_NOT_BOUND_TO_REQUEST")
    elif os.environ.get(ENVIRONMENT_VARIABLE):
        raise ValueError("UNDECLARED_RAW_OBSERVATION_CACHE")
    imported = request.get("checkpoint_import")
    if imported:
        from app.native_objects.resume_checkpoint import verify_import_receipt

        receipt = Path(imported["receipt_path"]).resolve()
        if (
            job not in receipt.parents
            or file_sha(receipt) != imported["receipt_sha256"]
        ):
            raise ValueError("IMPORTED_CHECKPOINT_RECEIPT_CHANGED")
        verify_import_receipt(
            receipt,
            target_job=job,
            source_sha256=request["source_sha256"],
            current_parameters=request["parameters"],
        )
    compatible = request.get("compatible_resume")
    if compatible:
        from app.native_objects.compatible_resume import verify_compatible_receipt

        receipt = Path(compatible["receipt_path"]).resolve()
        if (
            job not in receipt.parents
            or file_sha(receipt) != compatible["receipt_sha256"]
        ):
            raise ValueError("COMPATIBLE_RESUME_RECEIPT_CHANGED")
        verify_compatible_receipt(
            receipt, job_directory=job, current_algorithm=request["algorithm"]
        )
    revision = request.get("revision_import")
    if revision:
        from app.native_objects.revision_resume import verify_revision_receipt

        receipt = Path(revision["receipt_path"]).resolve()
        if (
            job not in receipt.parents
            or file_sha(receipt) != revision["receipt_sha256"]
        ):
            raise ValueError("REVISION_RESUME_RECEIPT_CHANGED")
        verify_revision_receipt(
            receipt,
            target_job=job,
            source_sha256=request["source_sha256"],
            current_parameters=request["parameters"],
        )
    return request


def _saved_candidate_gates(staging, request):
    from app.native_objects.review_binding import verify_saved_review
    import ezdxf

    dxf = staging / "result.dxf"
    evidence = staging / "evidence"
    cold = read_json(evidence / "cold_audit.json")
    if (
        not cold.get("source_gate_pass")
        or cold.get("ezdxf_errors")
        or cold.get("ezdxf_in_memory_fixes")
        or cold.get("exact_duplicate_segments")
    ):
        raise ValueError("SAVED_SOURCE_OR_DXF_GATE_REJECTED; draft remains unpublished")
    if cold.get("dxf_sha256") != file_sha(dxf):
        raise ValueError("Saved DXF no longer matches its cold-read audit")
    doc = ezdxf.readfile(dxf)
    actual = doc.audit()
    if actual.errors or actual.fixes:
        raise ValueError("Final temporary DXF failed independent cold reading")
    meta = read_json(dxf.with_suffix(".objects.json"))
    imported = read_json(evidence / "import_manifest.json")
    review_path = evidence / "quality_review.json"
    review = read_json(review_path)
    binding = verify_saved_review(
        review_path, dxf, meta["objects"], imported, source_path=request["input_path"]
    )
    if not binding["valid"]:
        raise ValueError(
            "STALE_REVIEW_PENDING; candidate cannot inherit another input or code review"
        )
    if not review.get("summary", {}).get("safe_artifact_structure") or not review.get(
        "summary", {}
    ).get("source_geometry_gate_pass"):
        raise ValueError("FINAL_QUALITY_STRUCTURE_REJECTED; draft remains unpublished")
    return {
        "cold_DXF_sha256": file_sha(dxf),
        "review_binding": binding,
        "source_geometry_checks": len(cold["source_checks"]),
        "requires_manual_review": bool(
            review.get("summary", {}).get("requires_manual_review", True)
        ),
        "formal_entities": cold["formal_modelspace_types"],
    }


def _publish_staging(staging, published, *, context, wall_deadline):
    """Commit the audited directory, allowing only bounded Windows lock delays.

    A directory reader can briefly deny rename on Windows. The actual holder
    need not be known: persistent access failures still fail without publishing.
    The manager keeps enforcing CPU/RSS/disk limits through the cancel token;
    every attempt checks that token and the original remaining wall budget.
    Retry events live in the attempt directory, outside the frozen manifest.
    """
    started = time.monotonic()
    retry_deadline = started + 2.0
    attempts = 0
    last_error = None
    while True:
        check_cancel("BEFORE_ATOMIC_COMMIT")
        now = time.monotonic()
        if now >= wall_deadline:
            raise NativeResourceLimit("WALL_LIMIT before atomic publication")
        if published.exists() or published.is_symlink():
            raise FileExistsError(
                "A published result is immutable and will not be replaced"
            )
        if last_error is not None and now >= retry_deadline:
            context.event(
                "atomic_publication_retry_exhausted",
                rename_attempts=attempts,
                winerror=last_error.winerror,
                elapsed_seconds=now - started,
            )
            raise last_error
        attempts += 1
        try:
            # The sole commit point: never copy, replace or modify an existing
            # publication. Do not check cancellation after a successful rename.
            os.rename(staging, published)
        except OSError as exc:
            if sys.platform != "win32" or getattr(exc, "winerror", None) not in {
                5, 32, 33,
            }:
                raise
            last_error = exc
            now = time.monotonic()
            delay = min(0.05, retry_deadline - now, wall_deadline - now)
            if delay > 0:
                context.event(
                    "atomic_publication_retry",
                    rename_attempts=attempts,
                    winerror=exc.winerror,
                    elapsed_seconds=now - started,
                    delay_seconds=delay,
                )
                time.sleep(delay)
        else:
            return {
                "rename_attempts": attempts,
                "elapsed_seconds": time.monotonic() - started,
                "atomic_directory_rename": True,
            }


def worker_run(request_path):
    request_path = Path(request_path).resolve()
    directory = request_path.parent
    started = time.monotonic()
    request = None
    parent_guard = None
    parent_thread = None
    from app.native_objects.platform_stats import sample, elapsed

    resource_start = sample()
    outcome = {
        "status": "FAILED",
        "stage": "WORKER_STARTING",
        "progress": 0.0,
        "error": None,
        "production_GO": False,
    }
    try:
        prepare_onnx_privacy()
        request = _validate_request(request_path)
        parent_guard, parent_thread = _watch_parent(request, directory, resource_start)
        staging = Path(request["staging_directory"])
        evidence = staging / "evidence"
        identity = {
            "job_id": request["job_id"],
            "attempt": request["attempt"],
            "source_sha256": request["source_sha256"],
            "algorithm_sha256": request["algorithm"]["sha256"],
        }
        outcome.update(job_id=request["job_id"], attempt=request["attempt"])
        with use_context(
            cancel_file=directory / "cancel.json",
            event_file=directory / "events.jsonl",
            identity=identity,
            progress_file=directory / "progress.json",
            resume_evidence=request.get("resume_evidence"),
            parent_pid=request.get("parent_pid"),
            validation_controls=request.get("validation_controls") or {},
            resource_limits=request["limits"],
        ) as context:
            boundary("WORKER_INPUT_AND_VERSION_VERIFIED", 0.0)
            from app.core.processing import ProductionProcessingService

            params = request["parameters"]
            checkpoint_options = {}
            if request.get("connection_checkpoint") is not None:
                checkpoint_options["connection_checkpoint"] = request["connection_checkpoint"]
            result = ProductionProcessingService.process_native_objects(
                request["input_path"],
                staging / "result.dxf",
                params["roi"],
                dpi=params["dpi"],
                page_number=params.get("page_number"),
                frame_number=params.get("frame_number"),
                orientation=params.get("orientation", 0),
                job_id=request["job_id"],
                evidence_dir=evidence,
                temp_dir=staging / "temporary",
                resource_report_path=staging / "entry_resources.json",
                cache_dir=request.get("cache_dir"),
                progress_callback=boundary,
                entrypoint="main.py:--native-worker / NativeJobManager",
                **checkpoint_options,
            )
            check_cancel("BEFORE_FINAL_PUBLICATION_AUDIT")
            if context.failed_children:
                atomic_json(directory / "failed_children.json", context.failed_children)
                raise RuntimeError(
                    "CHILD_PROCESS_FAILURE: task contains a failed OCR child and is not published"
                )
            gates = _saved_candidate_gates(staging, request)
            boundary("FINAL_SAVED_DXF_AND_REVIEW_VERIFIED", 0.99)
            if file_sha(request["input_path"]) != request["source_sha256"]:
                raise ValueError("Task input changed during conversion")
            from app.native_objects.observation_cache import write_usage_report

            outcome["raw_observation_usage"] = write_usage_report(
                evidence / "raw_observation_usage.json",
                request.get("raw_observation_cache"),
            )
            atomic_json(evidence / "runtime_privacy.json", runtime_privacy_status())
            files = {
                p.relative_to(staging).as_posix(): {
                    "sha256": file_sha(p),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            }
            atomic_json(
                staging / "publication_manifest.json",
                {
                    "schema": "native-atomic-publication-v4",
                    "identity": identity,
                    "gates": gates,
                    "files": files,
                    "status": "COMPLETE_AUDITED_CANDIDATE_WITH_EXPLICIT_PENDING",
                    "not_a_production_GO": True,
                    "created_utc": utc_now(),
                    "historical_absolute_staging_paths_in_evidence_preserved": True,
                },
            )
            check_cancel("BEFORE_ATOMIC_COMMIT")
            published = (
                Path(request["job_directory"]) / "results" / f"{request['attempt']:04d}"
            )
            published.parent.mkdir(parents=True, exist_ok=True)
            # Same-volume directory rename is the sole commit point. All files
            # are already complete; a cancellation after this point cannot
            # turn a valid published result into a fake partially cancelled one.
            publication = _publish_staging(
                staging,
                published,
                context=context,
                wall_deadline=started + float(request["limits"]["wall_seconds"]),
            )
            outcome.update(
                status="COMPLETED_WITH_ISSUES",
                stage="PUBLISHED_AUDITED_CANDIDATE",
                progress=1.0,
                result_dxf=str(published / "result.dxf"),
                preview_path=str(published / "result.png"),
                source_roi_path=str(published / "evidence/quality_source_roi.png"),
                quality_path=str(published / "evidence/quality_review.json"),
                issues_path=str(published / "evidence/quality_issues.json"),
                evidence_dir=str(published / "evidence"),
                result_directory=str(published),
                publication_manifest=str(published / "publication_manifest.json"),
                result_sha256=gates["cold_DXF_sha256"],
                source_unchanged=True,
                remote_service_calls=0,
                remote_wait_seconds=0,
                requires_manual_review=gates["requires_manual_review"],
                formal_entities=gates["formal_entities"],
                atomic_publication=publication,
                error=None,
                cancellation_after_commit=(directory / "cancel.json").exists(),
            )
            context.event(
                "published",
                result_directory=str(published),
                dxf_sha256=gates["cold_DXF_sha256"],
                atomic_publication=publication,
            )
        exit_code = 0
    except NativeCancelled as exc:
        status = (
            "RESOURCE_STOP"
            if exc.reason.startswith("RESOURCE_STOP:")
            else "INTERRUPTED"
            if exc.reason == "parent_application_exited"
            else "CANCELLED"
        )
        outcome.update(
            status=status,
            stage=exc.stage or "CANCELLED",
            error={
                "type": "COOPERATIVE_CANCELLATION",
                "reason": exc.reason,
                "valid_checkpoints_retained": True,
                "successful_output_overwritten": False,
            },
        )
        exit_code = 2
    except NativeResourceLimit as exc:
        outcome.update(
            status="RESOURCE_STOP",
            stage="RESOURCE_STOP",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
                "valid_checkpoints_retained": True,
                "automatic_retry": False,
            },
        )
        exit_code = 2
    except Exception as exc:
        outcome.update(
            status="FAILED",
            error={
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "partial_files_retained_unpublished": True,
                "automatic_retry": False,
            },
        )
        exit_code = 1
    finally:
        if parent_guard is not None:
            parent_guard.set()
        if parent_thread is not None:
            parent_thread.join(timeout=0.2)
        if request is None:
            try:
                partial = read_json(request_path)
                outcome.update(
                    job_id=partial.get("job_id"), attempt=partial.get("attempt")
                )
            except (OSError, ValueError):
                pass
        outcome.update(
            finished_utc=utc_now(),
            wall_seconds=time.monotonic() - started,
            resources=elapsed(resource_start),
            worker_exit_code=locals().get("exit_code", 1),
            runtime_privacy=runtime_privacy_status(),
        )
        atomic_json(directory / "outcome.json", outcome)
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Pass exactly one managed worker request file")
    raise SystemExit(worker_run(sys.argv[1]))
