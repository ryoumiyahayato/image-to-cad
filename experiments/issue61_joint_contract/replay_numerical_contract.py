"""Explicit historical compatibility and independently rebuilt joint source replay.

This CLI never generates a DXF, changes frozen evidence or invokes OCR. Its
execution receipt binds the exact input file, canonical plan, live producers,
source frame and (when supplied) actual ordinary worker request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _checkout(repo):
    try:
        return {"commit": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
                "tree": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip(),
                "worktree_changes": subprocess.check_output(
                    ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=normal"], text=True).splitlines()}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "tree": None, "worktree_changes": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="command", required=True)
    legacy = sub.add_parser("legacy-compatibility")
    legacy.add_argument("--saved-plan", type=Path, required=True)
    legacy.add_argument("--replayed-plan", type=Path, required=True)
    legacy.add_argument("--strict-failure", type=Path, required=True)
    legacy.add_argument("--expected-producer-sha256", required=True)
    inspect = sub.add_parser("inspect-candidates", help="Read a candidate plan in its original scope, without reconstruction.")
    inspect.add_argument("--plan", type=Path, required=True)
    inspect.add_argument("--expected-plan-sha256", required=True)
    generate = sub.add_parser("generate-plan")
    generate.add_argument("--prior-plan", type=Path, required=True)
    verify = sub.add_parser("verify-plan")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--expected-plan-sha256", required=True)
    verify.add_argument("--execution-request", type=Path)
    for command in (legacy, inspect, generate, verify):
        command.add_argument("--repo", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--output", type=Path, required=True)
    for command in (generate, verify):
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--expected-source-sha256", required=True)
    args = parser.parse_args(argv)
    repo, output = args.repo.resolve(), args.output.resolve()
    execution_path = output.with_suffix(output.suffix + ".execution.json")
    if output.exists() or execution_path.exists():
        parser.error("output or execution receipt exists; choose new paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1",
                      OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", ORT_DISABLE_TELEMETRY="1",
                      XDG_CACHE_HOME=str(output.parent / "runtime-cache"),
                      MPLCONFIGDIR=str(output.parent / "matplotlib"))
    sys.path.insert(0, str(repo / "cad_photo_to_dxf"))
    from app.core.native_job_manager import algorithm_fingerprint
    from app.native_objects import attached_stroke_graph as graph
    from app.native_objects import attached_stroke_numeric as numeric

    watched = {"graph_module": Path(graph.__file__), "numeric_module": Path(numeric.__file__),
               "ink_module": Path(graph.attached_ink.__file__), "contacts_module": Path(graph.prior_contacts.__file__)}
    execution = {"schema": "joint-numeric-execution-v3", "command": args.command,
                 "checkout": _checkout(repo), "algorithm_identity": algorithm_fingerprint(),
                 "process_pid": os.getpid(), "independently_rebuilt": False,
                 "source_graph_argument": "NOT_RUN", "contract": numeric.contract_identity(),
                 "joint_contract": numeric.joint_contract_identity(),
                 "new_OCR_calls": 0, "new_model_calls": 0, "new_DXF_generated": False,
                 "ordinary_conversion_run": False, "existing_evidence_modified": False,
                 "combined_source_adoption_authorized": False}
    execution["current_joint_producer_sha256"] = {
        "attached_stroke_graph.py": _sha(watched["graph_module"]),
        "attached_stroke_numeric.py": _sha(watched["numeric_module"]),
        "attached_stroke_ink.py": _sha(watched["ink_module"]),
        "attached_stroke_contacts.py": _sha(watched["contacts_module"])}
    if args.command == "legacy-compatibility":
        watched.update(saved_plan=args.saved_plan, replayed_plan=args.replayed_plan, strict_failure=args.strict_failure)
    elif args.command in ("inspect-candidates", "verify-plan"):
        watched["saved_plan"] = args.plan
    else:
        watched["prior_plan"] = args.prior_plan
    if args.command in ("generate-plan", "verify-plan"):
        watched["source"] = args.input
    if getattr(args, "execution_request", None):
        watched["execution_request"] = args.execution_request
    before = {name: _sha(path) if path.is_file() else None for name, path in watched.items()}
    execution["input_sha256_before"] = before
    started = time.perf_counter()
    report, okay = {"pass": False}, False
    try:
        if any(value is None for value in before.values()):
            raise ValueError("REQUIRED_NUMERIC_INPUT_MISSING:" + ",".join(name for name, value in before.items() if value is None))
        if args.command == "legacy-compatibility":
            failure = _read(args.strict_failure)
            if failure.get("pass") is not False and failure.get("status") != "FAIL":
                raise ValueError("LEGACY_STRICT_FAILURE_RECEIPT_REQUIRED")
            report = numeric.compare_legacy_plans(_read(args.saved_plan), _read(args.replayed_plan),
                                                 expected_producer_sha256=args.expected_producer_sha256)
            okay = report["pass"]
            execution.update(status=report["status"], legacy_original_strict_status=report["legacy_original_strict_status"],
                             legacy_original_failure_receipt_preserved=True, legacy_evidence_relabelled=False)
        else:
            plan_path = args.prior_plan if args.command == "generate-plan" else args.plan
            plan = _read(plan_path)
            execution.update(input_plan_schema=plan.get("schema"), plan_schema=plan.get("schema"),
                             checked_plan_file_sha256=_sha(plan_path),
                             checked_plan_canonical_sha256=graph._digest(plan),
                             roi_xyxy_px=plan.get("roi_xyxy_px"))
            if args.command != "generate-plan" and _sha(plan_path) != args.expected_plan_sha256:
                raise ValueError("PLAN_BYTES_DIFFER_FROM_EXPLICIT_SHA256_ANCHOR")
            if args.command == "inspect-candidates":
                report = numeric.build_certificate(plan)
                okay = report.get("pass", True)
                execution.update(status="CANDIDATE_DIAGNOSTICS_COMPLETED" if okay else "CANDIDATE_DIAGNOSTICS_UNRESOLVED",
                                 historical_input_not_joint_execution=plan.get("schema") != numeric.PLAN_SCHEMA)
            else:
                execution.update(expected_source_sha256=args.expected_source_sha256,
                                 actual_source_sha256=_sha(args.input))
                if execution["actual_source_sha256"] != args.expected_source_sha256:
                    raise ValueError("SOURCE_BYTES_DIFFER_FROM_EXPLICIT_SHA256_ANCHOR")
                if args.command == "verify-plan" and args.execution_request:
                    request = _read(args.execution_request)
                    checks = {"algorithm": request.get("algorithm", {}).get("sha256") == execution["algorithm_identity"]["sha256"],
                              "source": request.get("source_sha256") == args.expected_source_sha256,
                              "roi": request.get("parameters", {}).get("roi") == plan.get("roi_xyxy_px")}
                    execution["execution_request_binding"] = {"path": str(args.execution_request.resolve()),
                        "sha256": _sha(args.execution_request), "checks": checks, "pass": all(checks.values())}
                    if not all(checks.values()):
                        raise ValueError("ORDINARY_EXECUTION_REQUEST_IDENTITY_DIFFERS")
                import numpy as np
                from PIL import Image

                with Image.open(args.input) as image:
                    gray = np.asarray(image.convert("L"))
                execution["source_graph_argument"] = None
                if args.command == "generate-plan":
                    report = graph.plan_attached_stroke_graph(gray, plan["roi_xyxy_px"], plan["prior_object_bindings"],
                                                             source_graph=None)
                    okay = True
                    execution.update(status="GENERATED_NEW_JOINT_V3_SOURCE_PLAN_ONLY", output_plan_schema=report["schema"],
                                     proposed_path_count=len(report["paths"]),
                                     complete_candidate_count=sum(len(c.get("candidate_paths", [])) for c in report["components"]),
                                     prior_bindings_are_inputs_not_new_adoption_approval=True)
                else:
                    report = graph.verify_attached_stroke_graph_plan(gray, plan["roi_xyxy_px"], plan, source_graph=None)
                    okay = report["pass"]
                    execution.update(status="PASS_JOINT_V3_SOURCE_PLAN_REPLAY" if okay else "FAIL_JOINT_V3_SOURCE_PLAN_REPLAY",
                                     independently_rebuilt=report.get("source_graph_rebuilt_from_original") is True,
                                     numeric_adoption_status=report.get("numeric_adoption_status"))
        execution["status"] = execution.get("status", "NUMERIC_EXECUTION_COMPLETED")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        report = {"pass": False, "reason": "JOINT_NUMERIC_INPUT_OR_EXECUTION_REJECTED", "detail": str(exc)}
        execution.update(status="JOINT_NUMERIC_INPUT_OR_EXECUTION_REJECTED", failure_detail=str(exc))
    execution["wall_seconds"] = time.perf_counter() - started
    execution["input_sha256_after"] = {name: _sha(path) if path.is_file() else None for name, path in watched.items()}
    execution["original_inputs_and_source_modules_unchanged"] = before == execution["input_sha256_after"]
    if not execution["original_inputs_and_source_modules_unchanged"]:
        execution["status"] = "FAIL_INPUT_OR_IMPLEMENTATION_CHANGED_DURING_EXECUTION"
        okay = False
    execution["algorithm_identity_after"] = algorithm_fingerprint()
    execution["algorithm_identity_unchanged"] = (
        execution["algorithm_identity"]["sha256"] == execution["algorithm_identity_after"]["sha256"])
    if getattr(args, "execution_request", None) and not execution["algorithm_identity_unchanged"]:
        execution["status"] = "FAIL_ORDINARY_ALGORITHM_CHANGED_DURING_COLD_REPLAY"
        okay = False
    execution["pass"] = bool(okay)
    _write_new(output, report)
    execution["output_path"] = str(output)
    execution["output_sha256"] = _sha(output)
    _write_new(execution_path, execution)
    print(json.dumps({"status": execution["status"], "output": str(output),
                      "execution_receipt": str(execution_path), "wall_seconds": execution["wall_seconds"]}))
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
