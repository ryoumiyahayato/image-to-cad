"""Independent saved inspection with explicit stage targets and durable failures.

Historical drawings keep historical execution identity. ID differences never
select targets. Old complete objects and unexpected changes are always checked.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from app.native_objects import independent_saved_geometry_audit as audit
from app.native_objects import independent_stage_binding as stage_audit
from app.native_objects.independent_stage_binding import (
    audit_stage_binding,
    resolve_stage_inputs,
)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _inputs(args):
    paths = [args.baseline, args.dxf, args.metadata, args.source]
    resolved = resolve_stage_inputs(args.dxf, plan=args.stage_plan, adoption=args.stage_adoption,
                                    publication=args.publication, execution_request=args.execution_request)
    paths.extend(path for path in resolved.values() if path is not None)
    continuation = getattr(args, "source_stage_continuation", None)
    manifest = getattr(args, "source_stage_manifest", None)
    try:
        request_path = resolved["execution_request"]
        request = json.loads(request_path.read_text()) if request_path and request_path.is_file() else {}
        captured = request.get("source_stage_checkpoint")
        if captured:
            manifest = Path(manifest or captured["manifest_path"])
            continuation = continuation or args.dxf.with_suffix(".native") / "evidence/source_stage_continuation.json"
    except (OSError, ValueError, TypeError, KeyError):
        # The stage checker records the invalid request; protection still runs.
        pass
    if manifest:
        paths.append(manifest)
        if manifest.is_file():
            paths.extend(path for path in manifest.parent.rglob("*") if path.is_file())
    if continuation:
        paths.append(continuation)
    return {str(path): audit.sha256(path) if path.is_file() else None for path in paths}


def inspect(args, summary):
    summary["inputs_before"] = _inputs(args)
    protection = audit.compare_saved_dxf(args.baseline, args.dxf)
    # Save protection before touching any declared target type or geometry.
    write_json(args.output_dir / "BASELINE_PROTECTION.json", protection)
    summary["baseline_protection_status"] = protection["status"]
    summary["unchanged_complete_old_objects"] = protection["unchanged_old_object_count"]
    summary["unchanged_top_level_old_entities"] = protection["unchanged_top_level_object_count"]
    stage = audit_stage_binding(dxf_path=args.dxf, metadata_path=args.metadata, source_path=args.source,
        roi=args.roi, dpi=args.dpi, plan_path=args.stage_plan, adoption_path=args.stage_adoption,
        publication_path=args.publication, execution_request_path=args.execution_request,
        source_stage_manifest_path=getattr(args, "source_stage_manifest", None),
        source_stage_continuation_path=getattr(args, "source_stage_continuation", None))
    write_json(args.output_dir / "STAGE_SCOPE_BINDING.json", stage)
    summary["stage_binding_status"] = stage["status"]
    summary["stage_execution_status"] = stage["stage_execution_status"]
    summary["stage_contract_scope"] = stage["contract_scope"]
    summary["source_stage_checkpoint_binding"] = stage.get("source_stage_checkpoint_binding", {"status": "NOT_RUN"})
    targets = stage["declared_adopted_target_ids"]
    summary["target_object_ids"] = targets
    summary["unadopted_candidate_path_ids"] = stage["unadopted_candidate_path_ids"]
    summary["complete_candidate_path_ids"] = stage["complete_candidate_path_ids"]
    bindings = audit.audit_saved_target_bindings(args.dxf, args.metadata, targets,
        expected_roi=args.roi, expected_dpi=args.dpi, expected_source_sha256=audit.sha256(args.source))
    write_json(args.output_dir / "ACTUAL_TARGET_BINDINGS.json", bindings)
    bound = {row["object_id"] for row in bindings["target_checks"] if row["pass"]}
    bound &= set(stage["bound_declared_target_ids"])
    if stage["status"] != "PASS" or not all(bindings["file_checks"].values()):
        bound.clear()
    before_snapshot = audit.snapshot_dxf(args.baseline)
    after_snapshot = audit.snapshot_dxf(args.dxf)
    write_json(args.output_dir / "BASELINE_SNAPSHOT.json", before_snapshot)
    write_json(args.output_dir / "ACTUAL_DXF_SNAPSHOT.json", after_snapshot)
    old_ids, actual_ids = set(before_snapshot["formal"]), set(after_snapshot["formal"])
    new_ids = actual_ids - old_ids
    verified_targets = bound - old_ids
    deltas = {
        "declared_adopted_target_ids": targets,
        "saved_and_stage_bound_target_ids": sorted(verified_targets),
        "declared_target_ids_that_are_old_objects": sorted(set(targets) & old_ids),
        "missing_declared_target_ids": sorted(set(targets) - actual_ids),
        "all_file_new_ids": sorted(new_ids), "unexpected_new_ids": sorted(new_ids - verified_targets),
        "missing_old_ids": protection["missing_old_ids"],
        "changed_complete_old_ids": protection["changed_complete_old_ids"],
        "changed_top_level_old_ids": protection["changed_top_level_old_ids"],
        "changed_block_dependency_parent_ids": protection["changed_block_dependency_parent_ids"],
        "unadopted_candidates_present_as_new_formal_ids": sorted(set(stage["unadopted_candidate_path_ids"]) & new_ids),
        "empty_target_set_does_not_suppress_file_deltas": True,
    }
    write_json(args.output_dir / "STAGE_TARGETS_AND_FILE_DELTAS.json", deltas)
    summary["target_and_file_sets"] = deltas
    scope_ok = (stage["status"] == "PASS" and not deltas["declared_target_ids_that_are_old_objects"]
                and not deltas["missing_declared_target_ids"] and not deltas["unexpected_new_ids"]
                and not deltas["unadopted_candidates_present_as_new_formal_ids"])
    summary["declared_target_scope_status"] = "PASS" if scope_ok else "FAIL"
    summary["actual_metadata_file_binding_status"] = "PASS" if all(bindings["file_checks"].values()) else "FAIL"
    summary["actual_target_bindings_status"] = (
        "NOT_RUN" if stage["status"] == "NOT_RUN" else
        "NOT_APPLICABLE_ZERO_ADOPTED" if not targets and stage["status"] == "PASS" else bindings["status"])
    geometries = audit.saved_source_geometries(args.dxf, args.roi, args.dpi)
    geometries["external_source_sha256"] = audit.sha256(args.source)
    geometries["target_object_ids"] = sorted(verified_targets)
    geometries["declared_target_ids"] = targets
    geometries["unadopted_candidate_ids"] = stage["unadopted_candidate_path_ids"]
    geometries["attachment_declarations"] = []
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    for row in metadata["objects"]:
        if row["id"] not in verified_targets:
            continue
        source_path = row.get("source_evidence", {}).get("attached_stroke_graph", {}).get("path", {})
        for index, terminal in enumerate(source_path.get("endpoint_evidence", [])):
            if terminal.get("host_path_id"):
                geometries["attachment_declarations"].append({"guest": row["id"], "end": index,
                    "host": terminal["host_path_id"], "declaration_origin": "producer claim requiring independent source review"})
    write_json(args.output_dir / "ACTUAL_SAVED_SOURCE_GEOMETRIES.json", geometries)
    summary["verified_saved_target_ids"] = sorted(verified_targets)
    summary["saved_geometry_identity_errors"] = geometries["identity_errors"]
    edits = []
    safe_for_edits = scope_ok and protection["status"] == "PASS" and bindings["status"] == "PASS"
    if args.edit_copies and safe_for_edits and targets:
        edit_dir = args.output_dir / "edits"
        edit_dir.mkdir()
        for index, target in enumerate(targets):
            for operation in ("delete", "move"):
                stem = f"target_{index + 1}_{operation}"
                edited = edit_dir / (stem + ".dxf")
                phases = []
                for action in ("write", "cold-read"):
                    report = edit_dir / (stem + "_" + action + ".json")
                    command = [sys.executable, str(Path(__file__).resolve()), "--child-action", action,
                               "--dxf", str(args.dxf), "--edited", str(edited), "--target-id", target,
                               "--operation", operation, "--report", str(report)]
                    process = subprocess.run(command, capture_output=True, text=True, check=False)
                    write_json(edit_dir / (stem + "_" + action + "_process.json"), {
                        "argv": command, "returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
                    if not report.is_file():
                        phases.append({"status": "FAIL", "reason": "CHILD_DID_NOT_WRITE_RECEIPT", "process_role": action})
                        break
                    phases.append(json.loads(report.read_text(encoding="utf-8")))
                    if process.returncode:
                        break
                edits.append({"target_id": target, "operation": operation, "phases": phases,
                              "pass": len(phases) == 2 and phases[0].get("process_id") != phases[1].get("process_id")
                                      and phases[1].get("status") == "PASS"})
    summary["edits"] = edits
    summary["edit_isolation_status"] = (
        "NOT_APPLICABLE_ZERO_ADOPTED" if stage["status"] == "PASS" and not targets else
        "NOT_RUN_PRECONDITION_FAILED" if not safe_for_edits else
        "NOT_RUN" if not args.edit_copies else "PASS" if edits and all(row["pass"] for row in edits) else "FAIL")
    summary["inputs_after"] = _inputs(args)
    summary["inputs_unchanged"] = summary["inputs_before"] == summary["inputs_after"]
    good = (protection["status"] == "PASS" and scope_ok and bindings["status"] == "PASS"
            and summary["inputs_unchanged"] and not geometries["identity_errors"]
            and summary["edit_isolation_status"] != "FAIL")
    summary["status"] = "PASS" if good else "NOT_RUN" if stage["status"] == "NOT_RUN" else "FAIL"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--roi", nargs=4, type=int)
    parser.add_argument("--dpi", type=float)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--stage-plan", type=Path)
    parser.add_argument("--stage-adoption", type=Path)
    parser.add_argument("--publication", type=Path)
    parser.add_argument("--execution-request", type=Path)
    parser.add_argument("--source-stage-manifest", type=Path,
                        help="Optional relocated captured manifest; its SHA must match the request")
    parser.add_argument("--source-stage-continuation", type=Path,
                        help="Optional relocated published continuation receipt; its SHA must match the export")
    parser.add_argument("--edit-copies", action="store_true")
    parser.add_argument("--child-action", choices=["write", "cold-read"])
    parser.add_argument("--edited", type=Path)
    parser.add_argument("--target-id")
    parser.add_argument("--operation", choices=["delete", "move"])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.child_action:
        if not all([args.edited, args.target_id, args.operation, args.report]):
            parser.error("child edit action requires edited, target-id, operation, report")
        try:
            result = (audit.make_edit_copy(args.dxf, args.edited, args.target_id, args.operation)
                      if args.child_action == "write" else audit.audit_edit_copy(args.dxf, args.edited, args.target_id, args.operation))
            result.setdefault("status", "PASS")
        except (OSError, ValueError, TypeError, KeyError, audit.ezdxf.DXFError) as exc:
            result = {"status": "FAIL", "reason": "EDIT_OPERATION_FAILED", "exception_type": type(exc).__name__, "detail": str(exc)}
        result.update(process_id=os.getpid(), process_role=args.child_action)
        write_json(args.report, result)
        return 0 if result["status"] == "PASS" else 1
    if not all([args.baseline, args.metadata, args.output_dir, args.source, args.roi, args.dpi]):
        parser.error("baseline, metadata, source, externally specified roi/dpi and output-dir are required")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    summary = {"schema": "joint-independent-saved-acceptance-execution-v3", "status": "NOT_RUN",
        "executed_at_utc": datetime.datetime.now(datetime.UTC).isoformat(), "errors": [],
        "checker_sha256": audit.sha256(Path(audit.__file__)), "runner_sha256": audit.sha256(Path(__file__)),
        "stage_checker_sha256": audit.sha256(Path(stage_audit.__file__)),
        "baseline_protection_status": "NOT_RUN", "stage_binding_status": "NOT_RUN",
        "actual_target_bindings_status": "NOT_RUN", "edit_isolation_status": "NOT_RUN",
        "target_object_ids": [], "verified_saved_target_ids": [], "inputs_unchanged": False,
        "drawing_provenance": "Actual supplied saved drawing; execution contract retained separately",
        "ordinary_full_region_conversions": 0, "new_OCR_calls": 0, "new_model_calls": 0,
        "CAD_GUI": "NOT_RUN", "source_complete_responsibility": "SEPARATE_REVIEW_REQUIRED"}
    try:
        inspect(args, summary)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must persist an explicit failed receipt.
        summary["status"] = "FAIL"
        summary["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        try:
            summary["inputs_after"] = _inputs(args)
            summary["inputs_unchanged"] = summary.get("inputs_before") == summary["inputs_after"]
        except (OSError, ValueError, TypeError, KeyError):
            summary["inputs_after"] = None
    write_json(args.output_dir / "SAVED_GEOMETRY_AND_EDITS.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "baseline_protection_status", "stage_binding_status", "actual_target_bindings_status", "edit_isolation_status", "target_object_ids")}, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
