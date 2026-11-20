"""Audited continuation after a recorded legacy module resource-limit defect.

Only completed source-bound text, fitted geometry and original door proposals
are reusable.  No old decision is converted into a final DXF approval.  The
manager retains and charges every prior attempt against the unchanged task
resource contract; this module does not mutate task state or prior evidence.
"""

from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile

from .execution import atomic_json, file_sha, read_json, utc_now
from .resume_checkpoint import _require, _verify_file, _within


_ALLOWED_CHANGED = {
    "app/native_objects/execution.py": "explicit task resource propagation only",
    "app/core/native_worker.py": "resource propagation and verified compatible-resume dispatch",
    "app/core/native_job_manager.py": "explicit continuation accounting and algorithm history",
    "app/native_objects/door_completion.py": "unexecuted search resource guard; geometry unchanged",
    "app/native_objects/connections.py": "unexecuted connection resource guard; geometry unchanged",
    "app/native_objects/completion_stages.py": "unexecuted completion-stage orchestration",
    "app/native_objects/pipeline.py": "stage orchestration; completed producer functions frozen",
    "app/native_objects/cad_io.py": "export had not executed",
    "app/native_objects/compatible_resume.py": "new explicit continuation verifier",
}


def _nodes(path):
    tree = ast.parse(Path(path).read_text())
    result = {}
    for index, node in enumerate(tree.body):
        name = getattr(node, "name", None)
        if name is None and isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(target, "id", None)
        key = name or f"{type(node).__name__}:{index}"
        result[key] = ast.dump(node, include_attributes=False)
    return result


def _classify_changes(prior, current, old_root, app_root):
    rows = []
    permitted_nodes = {
        "app/native_objects/door_completion.py": {"_guard"},
        "app/native_objects/connections.py": {"_checkpoint"},
        "app/native_objects/execution.py": {
            "ExecutionContext",
            "active_resource_limits",
        },
    }
    frozen_pipeline = {
        "_completed_text_checkpoint",
        "_discovery_for_resume",
        "_completed_geometry_checkpoint",
        "_dense_line_gate",
        "_doors",
    }
    for relative in sorted(set(prior["files"]) | set(current["files"])):
        old_sha, new_sha = prior["files"].get(relative), current["files"].get(relative)
        if old_sha == new_sha:
            rows.append(
                {
                    "path": relative,
                    "before_sha256": old_sha,
                    "after_sha256": new_sha,
                    "classification": "UNCHANGED_COMPLETED_OR_UNREACHED_CODE",
                }
            )
            continue
        _require(
            relative in _ALLOWED_CHANGED,
            "COMPATIBLE_RESUME_UNEXPECTED_CODE_CHANGE:" + relative,
        )
        _require(
            new_sha is not None,
            "COMPATIBLE_RESUME_SOURCE_DELETION_FORBIDDEN:" + relative,
        )
        path = _within(app_root, relative)
        _verify_file(path, new_sha, relative)
        changed_nodes = []
        if old_sha is not None:
            before = _within(old_root, relative)
            _verify_file(before, old_sha, "preserved prior code/" + relative)
            old_nodes, new_nodes = _nodes(before), _nodes(path)
            changed_nodes = [
                name
                for name in sorted(set(old_nodes) | set(new_nodes))
                if old_nodes.get(name) != new_nodes.get(name)
            ]
            if relative in permitted_nodes:
                # Compare named definitions and all constants/imports. A resource
                # change must not alter fitting, thresholds or source gates.
                _require(
                    set(changed_nodes) <= permitted_nodes[relative],
                    "COMPATIBLE_RESUME_NON_RESOURCE_ALGORITHM_CHANGE:" + relative,
                )
            if relative == "app/native_objects/pipeline.py":
                _require(
                    all(old_nodes.get(k) == new_nodes.get(k) for k in frozen_pipeline),
                    "COMPATIBLE_RESUME_COMPLETED_PIPELINE_PRODUCER_CHANGED",
                )
        else:
            _require(
                relative == "app/native_objects/compatible_resume.py",
                "COMPATIBLE_RESUME_UNEXPECTED_ADDED_PRODUCER",
            )
        rows.append(
            {
                "path": relative,
                "before_sha256": old_sha,
                "after_sha256": new_sha,
                "classification": "ALLOWED_STAGE_SCOPED_CHANGE",
                "reason": _ALLOWED_CHANGED[relative],
                "AST_changed_top_level_nodes": changed_nodes,
            }
        )
    return rows


def prepare_compatible_resume(
    job_directory,
    *,
    current_algorithm,
    previous_source_directory=None,
    expected_failure="NATIVE_DOOR_COMPLETION_RESOURCE_STOP",
):
    from .job import make_job
    from .source_import import prepare_source
    from .contracts import validate_text_regions

    job = Path(job_directory).resolve()
    state = read_json(job / "state.json")
    _require(
        state.get("status") == "FAILED", "COMPATIBLE_RESUME_REQUIRES_FAILED_ATTEMPT"
    )
    _require(
        state.get("error", {}).get("message") == expected_failure,
        "COMPATIBLE_RESUME_UNKNOWN_FAILURE",
    )
    number = int(state["attempt"])
    attempt = job / "attempts" / f"{number:04d}"
    request = read_json(attempt / "request.json")
    outcome = read_json(attempt / "outcome.json")
    _require(
        outcome.get("error", {}).get("message") == expected_failure,
        "COMPATIBLE_RESUME_OUTCOME_FAILURE_MISMATCH",
    )
    _require(
        request["algorithm"] == state["algorithm"],
        "COMPATIBLE_RESUME_PRIOR_ALGORITHM_STATE_MISMATCH",
    )
    _require(
        request["task_limits"] == state["limits"],
        "COMPATIBLE_RESUME_RESOURCE_CONTRACT_CHANGED",
    )
    evidence = attempt / "staging/evidence"
    stage_path = evidence / "completed_stages.json"
    stage = read_json(stage_path)
    _require(
        "text" in stage and "geometry" in stage and "assembly" not in stage,
        "COMPATIBLE_RESUME_WRONG_COMPLETED_STAGE",
    )
    events = [
        json.loads(line) for line in (attempt / "events.jsonl").read_text().splitlines()
    ]
    last_checkpoint = [x for x in events if x.get("kind") == "checkpoint_artifact"][-1]
    _require(
        last_checkpoint.get("name") == "completed_geometry"
        and last_checkpoint.get("sha256") == file_sha(stage_path),
        "COMPATIBLE_RESUME_LAST_STAGE_EVENT_MISMATCH",
    )
    _require(
        not any(
            x.get("stage") in ("COMPLETE_SOURCE_CONNECTIONS", "DXF_EXPORT")
            for x in events
        ),
        "COMPATIBLE_RESUME_LATER_STAGE_ALREADY_ENTERED",
    )
    generation_path = evidence / "door_completion/generation/door_completion.json"
    generation = read_json(generation_path)
    _require(
        generation.get("resource_stop") is True
        and generation.get("status") == "RESOURCE_STOP_PARTIAL_NO_GO",
        "COMPATIBLE_RESUME_NO_LEGACY_RESOURCE_EVIDENCE",
    )
    _require(
        not generation["new_objects"]
        and not generation["source_anchor_ledger"]
        and not generation["rejected"],
        "COMPATIBLE_RESUME_DOOR_SEARCH_PARTIALLY_EXECUTED",
    )
    _require(
        generation["retained_objects_hash_before"]
        == generation["retained_objects_hash_after"],
        "COMPATIBLE_RESUME_EXISTING_DOOR_CHANGED",
    )
    usage = read_json(attempt / "manager_resources.json")
    limits = request["limits"]
    _require(
        usage["sampled_tree_peak_RSS_bytes"] < limits["RSS_MiB"] * 1024 * 1024
        and usage["sampled_tree_CPU_seconds"] < limits["CPU_seconds"]
        and usage["elapsed_wall_seconds"] < limits["wall_seconds"],
        "COMPATIBLE_RESUME_ACTUAL_TASK_RESOURCE_EXHAUSTED",
    )
    _require(
        generation["resources"]["peak_RSS_MiB"]
        > generation["policy"]["process_RSS_limit_MiB"],
        "COMPATIBLE_RESUME_LEGACY_RSS_CAUSE_NOT_PROVEN",
    )
    app_root = Path(__file__).resolve().parents[2]
    old_root = (
        Path(previous_source_directory).resolve()
        if previous_source_directory
        else app_root.parents[1]
        / "audit/legacy_budget_repair/before/repository/cad_photo_to_dxf"
    )
    changes = _classify_changes(
        request["algorithm"], current_algorithm, old_root, app_root
    )
    params = request["parameters"]
    source = Path(state["input_path"])
    _verify_file(source, state["source_sha256"], "captured source")
    prepared = prepare_source(
        make_job(
            source,
            job / "unused_compatibility_output.dxf",
            params["roi"],
            dpi=params["dpi"],
            frame_number=params.get("frame_number"),
            page_number=params.get("page_number"),
            orientation=params.get("orientation", 0),
            job_id="compatible-readonly-check",
            cache_dir=evidence,
        ),
        persist=False,
    )
    _require(
        prepared.manifest["cache_identity"] == stage["job_source_identity"],
        "COMPATIBLE_RESUME_SOURCE_IDENTITY_CHANGED",
    )
    text_path = _within(evidence, stage["text"]["path"])
    _verify_file(text_path, stage["text"]["sha256"], "completed text")
    text = read_json(text_path)
    validate_text_regions(text, prepared.gray.shape, prepared.working_roi)
    _require(
        text["source_array_sha256"] == prepared.manifest["working_array_sha256"],
        "COMPATIBLE_RESUME_TEXT_ARRAY_CHANGED",
    )
    producer = stage["text"]
    producer_rows = [(producer["producer_module"], producer["producer_sha256"])]
    producer_rows += [
        (x["module"], x["sha256"]) for x in producer.get("dependency_producers", [])
    ]
    producer_rows.append(
        ("app.native_objects.geometry", stage["geometry"]["producer_sha256"])
    )
    for module, expected in producer_rows:
        _verify_file(
            _within(app_root, module.replace(".", "/") + ".py"), expected, module
        )
    model = text.get("producer", {}).get("model_identity", {})
    _require(
        model.get("model_path") and model.get("model_sha256"),
        "COMPATIBLE_RESUME_COMPLETED_MODEL_IDENTITY_MISSING",
    )
    _verify_file(
        model["model_path"], model["model_sha256"], "completed independent model"
    )
    geometry_path = _within(evidence, stage["geometry"]["path"])
    _verify_file(
        geometry_path, stage["geometry"]["sha256"], "completed fitted geometry"
    )
    doors_path, proposals_path = (
        evidence / "doors/doors.json",
        evidence / "doors/door_proposals.json",
    )
    doors, proposals = read_json(doors_path), read_json(proposals_path)
    prior_detector = request["algorithm"]["files"][
        "app/native_objects/door_detector.py"
    ]
    _verify_file(
        app_root / "app/native_objects/door_detector.py",
        prior_detector,
        "completed door detector",
    )
    source_checks = {row["id"]: row for row in doors["source_checks"]}
    accepted = {obj["id"]: obj for obj in doors["objects"]}
    rejected = {row["object"]["id"]: row["object"] for row in doors["uncertainties"]}
    _require(
        set(accepted).isdisjoint(rejected), "COMPATIBLE_RESUME_DOOR_ACCEPTANCE_CONFLICT"
    )
    _require(
        {obj["id"] for obj in proposals["objects"]}
        == set(source_checks)
        == set(accepted) | set(rejected),
        "COMPATIBLE_RESUME_DOOR_SOURCE_CHECK_SET_CHANGED",
    )
    for obj in proposals["objects"]:
        identifier = obj["id"]
        retained = accepted.get(identifier) or rejected.get(identifier)
        _require(
            obj["kind"] == "DOOR" and obj["geometry"] == retained["geometry"],
            "COMPATIBLE_RESUME_DOOR_GEOMETRY_CHANGED",
        )
        _require(
            obj["source_evidence"]["source_sha256"] == state["source_sha256"],
            "COMPATIBLE_RESUME_DOOR_SOURCE_CHANGED",
        )
        _require(
            source_checks[identifier]["pass"] == (identifier in accepted),
            "COMPATIBLE_RESUME_DOOR_ACCEPTANCE_CHECK_CHANGED",
        )
    destination = job / "imports" / f"compatible-{number:04d}"
    _require(not destination.exists(), "COMPATIBLE_RESUME_IMPORT_ALREADY_EXISTS")
    destination.parent.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".compatible-", dir=destination.parent))
    target = temporary / "evidence"
    files = {}
    roots = [
        "completed_stages.json",
        "completed_text.json",
        "completed_geometry.json",
        "text",
        "text_domain_recovery",
        "text_block_rescue",
        "cross_engine_text",
        "geometry",
        "annotations",
        "doors",
    ]
    for name in roots:
        original = evidence / name
        paths = (
            [original]
            if original.is_file()
            else sorted(p for p in original.rglob("*") if p.is_file())
        )
        for path in paths:
            relative = path.relative_to(evidence).as_posix()
            _require(
                not path.is_symlink() and path.suffix.lower() not in (".dxf", ".dwg"),
                "COMPATIBLE_RESUME_UNEXPECTED_FILE",
            )
            copy_to = _within(target, relative)
            copy_to.parent.mkdir(parents=True, exist_ok=True)
            digest = file_sha(path)
            shutil.copy2(path, copy_to)
            _verify_file(copy_to, digest, relative)
            files[relative] = {
                "sha256": digest,
                "bytes": path.stat().st_size,
                "origin": "prior_completed_stage",
            }
    cache = {
        "schema": "same-task-frozen-door-proposals-v8",
        "source_sha256": state["source_sha256"],
        "roi_xyxy_px": params["roi"],
        "job_source_identity": stage["job_source_identity"],
        "objects": copy.deepcopy(proposals["objects"]),
        "provenance": {
            "method": "prior_completed_same_task_detection_without_refit",
            "source_doors_json_sha256": file_sha(doors_path),
            "source_proposals_json_sha256": file_sha(proposals_path),
            "door_detector_producer_sha256": prior_detector,
            "actual_prior_source_checks": doors["source_checks"],
            "accepted_ids": sorted(accepted),
            "rejected_ids": sorted(rejected),
            "new_source_fits": 0,
            "all_proposals_rechecked_by_current_pipeline": True,
            "rejected_proposals_not_promoted": True,
        },
    }
    atomic_json(target / "native_verified_cache.json", cache)
    files["native_verified_cache.json"] = {
        "sha256": file_sha(target / "native_verified_cache.json"),
        "bytes": (target / "native_verified_cache.json").stat().st_size,
        "origin": "audited_wrapper_of_unchanged_raw_door_proposals",
    }
    receipt = {
        "schema": "same-task-compatible-stage-resume-v8",
        "created_utc": utc_now(),
        "job_directory": str(job),
        "source_sha256": state["source_sha256"],
        "parameters": params,
        "prior_attempt_number": number,
        "prior_attempt_directory": str(attempt),
        "prior_algorithm": request["algorithm"],
        "new_algorithm": current_algorithm,
        "compatibility_changes": changes,
        "previous_source_directory": str(old_root),
        "prior_request_sha256": file_sha(attempt / "request.json"),
        "prior_stage_manifest_sha256": file_sha(stage_path),
        "prior_outcome_sha256": file_sha(attempt / "outcome.json"),
        "legacy_module_limit_evidence": {
            "path": str(generation_path),
            "sha256": file_sha(generation_path),
            "legacy_RSS_limit_MiB": generation["policy"]["process_RSS_limit_MiB"],
            "measured_process_high_water_RSS_MiB": generation["resources"][
                "peak_RSS_MiB"
            ],
            "generation_resources": generation["resources"],
            "search_had_no_processed_source_anchor": True,
        },
        "task_resource_contract_unchanged": state["limits"],
        "prior_resource_consumption": usage,
        "actual_task_resource_contract_exhausted": False,
        "budget_reset": False,
        "cache_dir": str(destination / "evidence"),
        "resume_evidence": str(destination / "evidence"),
        "files": files,
        "historical_adoption_inherited": False,
        "final_review_reexecution_required": True,
        "new_OCR_calls": 0,
        "new_line_fits": 0,
        "new_door_fits": 0,
        "prior_evidence_modified": False,
    }
    atomic_json(temporary / "receipt.json", receipt)
    os.rename(temporary, destination)
    receipt_path = destination / "receipt.json"
    return {
        "cache_dir": str(destination / "evidence"),
        "resume_evidence": str(destination / "evidence"),
        "receipt_path": str(receipt_path),
        "receipt_sha256": file_sha(receipt_path),
        "new_algorithm": current_algorithm,
        "prior_algorithm": request["algorithm"],
        "compatibility_changes": changes,
        "prior_attempt_number": number,
        "prior_resource_consumption": usage,
        "budget_reset": False,
    }


def verify_compatible_receipt(receipt_path, *, job_directory, current_algorithm):
    job, path = Path(job_directory).resolve(), Path(receipt_path).resolve()
    receipt = read_json(path)
    number = int(receipt["prior_attempt_number"])
    _require(
        path == job / "imports" / f"compatible-{number:04d}" / "receipt.json",
        "COMPATIBLE_RECEIPT_OUTSIDE_TASK",
    )
    _require(
        receipt["schema"] == "same-task-compatible-stage-resume-v8"
        and receipt["job_directory"] == str(job),
        "COMPATIBLE_RECEIPT_IDENTITY_CHANGED",
    )
    _require(
        receipt["new_algorithm"] == current_algorithm,
        "COMPATIBLE_RECEIPT_ALGORITHM_CHANGED",
    )
    state = read_json(job / "state.json")
    _require(
        state["source_sha256"] == receipt["source_sha256"]
        and state["parameters"] == receipt["parameters"],
        "COMPATIBLE_RECEIPT_SOURCE_CHANGED",
    )
    _require(
        state["limits"] == receipt["task_resource_contract_unchanged"]
        and receipt["budget_reset"] is False,
        "COMPATIBLE_RECEIPT_BUDGET_CHANGED",
    )
    evidence = path.parent / "evidence"
    _require(
        {p.relative_to(evidence).as_posix() for p in evidence.rglob("*") if p.is_file()}
        == set(receipt["files"]),
        "COMPATIBLE_RECEIPT_FILE_SET_CHANGED",
    )
    for relative, row in receipt["files"].items():
        _verify_file(_within(evidence, relative), row["sha256"], relative)
    prior = Path(receipt["prior_attempt_directory"])
    _require(
        prior == job / "attempts" / f"{number:04d}",
        "COMPATIBLE_PRIOR_ATTEMPT_PATH_CHANGED",
    )
    _verify_file(
        prior / "request.json", receipt["prior_request_sha256"], "original request"
    )
    _verify_file(
        prior / "staging/evidence/completed_stages.json",
        receipt["prior_stage_manifest_sha256"],
        "original completed-stage manifest",
    )
    _verify_file(
        prior / "outcome.json",
        receipt["prior_outcome_sha256"],
        "original failed outcome",
    )
    return receipt
