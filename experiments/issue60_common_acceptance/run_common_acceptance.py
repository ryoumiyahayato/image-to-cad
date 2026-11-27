"""Layered joint acceptance with actual stage scopes and machine-readable failures.

Saved geometry, numerical identity/replay and original-pixel responsibility are
separate verdicts. A missing stage is never a successful zero-adoption stage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.native_objects.independent_saved_geometry_audit import sha256


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _run(script, arguments, output):
    command = [sys.executable, str(Path(__file__).with_name(script)), *map(str, arguments)]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    result = {"argv": command, "returncode": process.returncode,
              "stdout": process.stdout, "stderr": process.stderr}
    _write(output, result)
    return result


def _numerical_receipt(path, stage, source_sha, dxf_sha, result_path=None):
    if path is None:
        return {"status": "NOT_RUN", "reason": "INDEPENDENT_REPLAY_RECEIPT_NOT_SUPPLIED",
                "independently_rerun_by_this_entry_point": False}
    try:
        receipt = _read(path)
        output = Path(result_path) if result_path else Path(receipt.get("output_path", ""))
        cold = _read(output)
        records = stage.get("input_records", {})
        request = receipt.get("execution_request_binding", {})
        checks = {
            "execution_schema": receipt.get("schema") == "joint-numeric-execution-v3",
            "actual_verify_entry": receipt.get("command") == "verify-plan",
            "current_joint_scope": stage.get("contract_scope") == "CURRENT_JOINT_V3"
                                   and receipt.get("plan_schema") == "source-attached-stroke-joint-plan-v3",
            "source_identity": receipt.get("actual_source_sha256") == source_sha == receipt.get("expected_source_sha256"),
            "plan_file_identity": receipt.get("checked_plan_file_sha256") == records.get("plan", {}).get("sha256"),
            "plan_canonical_identity": receipt.get("checked_plan_canonical_sha256") == stage.get("plan_canonical_sha256")
                                       == cold.get("saved_plan_sha256"),
            "algorithm_identity": receipt.get("algorithm_identity", {}).get("sha256") == stage.get("algorithm_identity"),
            "producer_dependencies": receipt.get("current_joint_producer_sha256") == stage.get("producer_dependencies"),
            "execution_request_identity": request.get("sha256") == records.get("execution_request", {}).get("sha256"),
            "execution_request_checks": request.get("pass") is True and bool(request.get("checks"))
                                        and all(value is True for value in request["checks"].values()),
            "independent_source_graph_rebuilt": receipt.get("independently_rebuilt") is True
                                                and receipt.get("source_graph_argument", "NOT_RUN") is None
                                                and cold.get("source_graph_rebuilt_from_original") is True,
            "inputs_and_producers_unchanged": receipt.get("original_inputs_and_source_modules_unchanged") is True,
            "algorithm_unchanged": receipt.get("algorithm_identity_unchanged") is True
                                   and receipt.get("algorithm_identity_after", {}).get("sha256") == stage.get("algorithm_identity"),
            "actual_output_file_hash": sha256(output) == receipt.get("output_sha256"),
            "actual_cold_result_pass": receipt.get("status") == "PASS_JOINT_V3_SOURCE_PLAN_REPLAY"
                                       and receipt.get("pass") is True and cold.get("pass") is True
                                       and cold.get("reason") == "ATTACHED_GRAPH_JOINT_V3_SOURCE_REPLAY",
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "path": str(path), "sha256": sha256(path),
                "checks": checks, "external_execution_receipt": receipt,
                "actual_cold_result_path": str(output), "actual_cold_result_sha256": sha256(output),
                "bound_saved_dxf_sha256_via_published_plan": dxf_sha,
                "independently_rerun_by_this_entry_point": False,
                "scope": "Exact execution/result/source/plan/producer binding; cannot override saved geometry or raw ownership"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"status": "FAIL", "reason": "INVALID_NUMERICAL_EXECUTION_RECEIPT",
                "exception_type": type(exc).__name__, "detail": str(exc),
                "independently_rerun_by_this_entry_point": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-roi", nargs=4, type=int, required=True)
    parser.add_argument("--audit-roi", nargs=4, type=int, required=True)
    parser.add_argument("--dpi", type=float, required=True)
    parser.add_argument("--stage-plan", type=Path)
    parser.add_argument("--stage-adoption", type=Path)
    parser.add_argument("--publication", type=Path)
    parser.add_argument("--execution-request", type=Path)
    parser.add_argument("--source-stage-manifest", type=Path)
    parser.add_argument("--source-stage-continuation", type=Path)
    parser.add_argument("--numerical-replay-receipt", type=Path)
    parser.add_argument("--numerical-replay-result", type=Path,
                        help="Optional relocated original result file; its SHA must match the execution receipt")
    parser.add_argument("--edit-copies", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = {"schema": "joint-common-independent-acceptance-v3", "status": "NOT_RUN", "errors": [],
        "entry_sha256": sha256(Path(__file__)),
        "child_entry_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                               ("run_saved_audit.py", "run_raw_source_audit.py")},
        "stage_execution": {"status": "NOT_RUN"},
        "identity_and_numerical_replay": {"status": "NOT_RUN"},
        "actual_saved_geometry_and_edit_isolation": {"status": "NOT_RUN"},
        "original_pixel_source_responsibility": {"status": "NOT_RUN"},
        "candidate_source_responsibility": {"status": "NOT_RUN"},
        "target_object_ids": [], "combined_adoption_authorized": False,
        "producer_PASS_consumed_by_independent_geometry_or_pixel_decisions": False,
        "GUI": "NOT_RUN", "ordinary_conversion_performed_by_this_checker": False}
    try:
        result.update(actual_source_sha256=sha256(args.source), actual_dxf_sha256=sha256(args.dxf),
                      externally_bound_source_frame={"roi": args.source_roi, "dpi": args.dpi},
                      independent_raw_evaluation_window=args.audit_roi)
        saved_dir = args.out / "saved"
        arguments = ["--source", args.source, "--baseline", args.baseline, "--dxf", args.dxf,
                     "--metadata", args.metadata, "--roi", *args.source_roi, "--dpi", args.dpi,
                     "--output-dir", saved_dir]
        for flag, value in (("--stage-plan", args.stage_plan), ("--stage-adoption", args.stage_adoption),
                            ("--publication", args.publication), ("--execution-request", args.execution_request),
                            ("--source-stage-manifest", args.source_stage_manifest),
                            ("--source-stage-continuation", args.source_stage_continuation)):
            if value is not None:
                arguments.extend([flag, value])
        if args.edit_copies:
            arguments.append("--edit-copies")
        process = _run("run_saved_audit.py", arguments, args.out / "saved_process.json")
        summary_path = saved_dir / "SAVED_GEOMETRY_AND_EDITS.json"
        if not summary_path.is_file():
            raise ValueError("SAVED_CHECKER_DID_NOT_WRITE_RECEIPT")
        saved = _read(summary_path)
        stage_path = saved_dir / "STAGE_SCOPE_BINDING.json"
        stage = _read(stage_path) if stage_path.is_file() else {"status": "NOT_RUN"}
        result["stage_execution"] = {"status": stage.get("stage_execution_status", "NOT_RUN"),
            "binding_status": stage["status"], "contract_scope": stage.get("contract_scope"),
            "receipt_sha256": sha256(stage_path) if stage_path.is_file() else None}
        result["source_stage_checkpoint_binding"] = stage.get("source_stage_checkpoint_binding", {"status": "NOT_RUN"})
        result["actual_saved_geometry_and_edit_isolation"] = {
            "status": saved["status"], "protection": saved["baseline_protection_status"],
            "target_binding": saved["actual_target_bindings_status"],
            "metadata_file_binding": saved.get("actual_metadata_file_binding_status", "NOT_RUN"),
            "target_scope": saved.get("declared_target_scope_status", "NOT_RUN"),
            "edit_isolation": saved["edit_isolation_status"], "input_files_unchanged": saved["inputs_unchanged"],
            "complete_old_objects_preserved": saved.get("unchanged_complete_old_objects"),
            "top_level_old_entities_preserved": saved.get("unchanged_top_level_old_entities"),
            "receipt_sha256": sha256(summary_path), "checker_exit_code": process["returncode"]}
        result["target_and_file_sets"] = saved.get("target_and_file_sets", {})
        result["target_object_ids"] = saved["target_object_ids"]
        candidates = saved.get("unadopted_candidate_path_ids", [])
        result["candidate_source_responsibility"] = {
            "status": "NOT_RUN_STAGE_UNAVAILABLE" if stage.get("status") == "NOT_RUN" else
                      "NOT_RUN_STAGE_BINDING_FAILED" if stage.get("status") != "PASS" else
                      "SOURCE_UNRESOLVED" if candidates else "NOT_APPLICABLE_NO_UNADOPTED_CANDIDATES",
            "complete_candidate_path_ids": candidates, "declared_in_stage_receipt": stage.get("status") != "NOT_RUN",
            "not_saved_targets": True, "source_PASS_inferred_from_producer": False,
            "independent_complete_model_audit": "NOT_RUN_PENDING_PARTNER_CONTRACT"}
        actual_targets = saved.get("verified_saved_target_ids", [])
        if actual_targets:
            raw_path = args.out / "RAW_SOURCE_RESPONSIBILITY.json"
            _run("run_raw_source_audit.py", ["--source", args.source,
                "--geometry-json", saved_dir / "ACTUAL_SAVED_SOURCE_GEOMETRIES.json",
                "--roi", *args.audit_roi, "--out", raw_path], args.out / "raw_process.json")
            if not raw_path.is_file():
                raise ValueError("RAW_CHECKER_DID_NOT_WRITE_RECEIPT")
            raw = _read(raw_path)
            result["original_pixel_source_responsibility"] = raw["summary"]
            result["original_pixel_source_responsibility"]["receipt_sha256"] = sha256(raw_path)
        elif stage.get("status") == "PASS" and not saved["target_object_ids"]:
            result["original_pixel_source_responsibility"] = {
                "status": "NOT_APPLICABLE_ZERO_ADOPTED", "independent_source_ownership_proved": False,
                "may_adopt_objects_from_this_report_alone": False,
                "candidate_source_responsibility_is_separate": True}
        else:
            result["original_pixel_source_responsibility"] = {
                "status": "NOT_RUN_STAGE_OR_SAVED_BINDING_FAILED", "independent_source_ownership_proved": False}
        numerical = _numerical_receipt(args.numerical_replay_receipt, stage,
                                       result["actual_source_sha256"], result["actual_dxf_sha256"], args.numerical_replay_result)
        result["identity_and_numerical_replay"] = numerical
        if saved["baseline_protection_status"] == "FAIL":
            result["status"] = "FAIL_PROTECTED_BASELINE"
        elif stage.get("status") != "PASS":
            result["status"] = "NOT_RUN_STAGE" if stage.get("status") == "NOT_RUN" else "FAIL_STAGE_BINDING"
        elif saved["status"] != "PASS":
            result["status"] = "FAIL_SAVED_GEOMETRY_OR_TARGET_SCOPE"
        elif result["original_pixel_source_responsibility"].get("status") == "HARD_REJECT":
            result["status"] = "FAIL_SOURCE_RESPONSIBILITY"
        elif numerical["status"] != "PASS":
            result["status"] = "NOT_RUN_NUMERICAL_REPLAY" if numerical["status"] == "NOT_RUN" else "FAIL_NUMERICAL_REPLAY_BINDING"
        elif not actual_targets:
            result["status"] = "PASS_ZERO_ADOPTED_PRESERVED_BASELINE"
        else:
            result["status"] = "SOURCE_UNRESOLVED"
        result["source_complete_ownership"] = (
            "NOT_RUN_STAGE_BINDING_NOT_ESTABLISHED" if stage.get("status") != "PASS" else
            "HARD_REJECT" if result["original_pixel_source_responsibility"].get("status") == "HARD_REJECT" else
            "SOURCE_UNRESOLVED" if candidates or saved["target_object_ids"] else "NOT_APPLICABLE_ZERO_ADOPTED")
        result["execution_completed"] = True
    except Exception as exc:  # noqa: BLE001 - CLI boundary must persist an explicit failed receipt.
        result["status"] = "FAIL_INPUT_OR_CHECKER_EXECUTION"
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        result["execution_completed"] = False
    _write(args.out / "COMMON_ACCEPTANCE.json", result)
    print(json.dumps({"status": result["status"], "saved": result["actual_saved_geometry_and_edit_isolation"],
                      "raw_source": result["original_pixel_source_responsibility"],
                      "candidates": result["candidate_source_responsibility"]}, ensure_ascii=False))
    return 1 if result["status"].startswith("FAIL") or result["status"].startswith("NOT_RUN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
