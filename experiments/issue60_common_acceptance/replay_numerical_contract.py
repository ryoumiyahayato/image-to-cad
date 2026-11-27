"""Explicit legacy diagnostic compatibility and new v2 source-plan replay.

This entry point never generates a DXF, changes a frozen plan or runs OCR.
Legacy compatibility consumes a separately reconstructed frozen-producer plan;
it must not be substituted for executing the old exact verifier first.
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
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        changes = subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=normal"], text=True,
        ).splitlines()
        return {"commit": commit, "worktree_dirty": bool(changes), "changes": changes}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "worktree_dirty": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="command", required=True)
    legacy = sub.add_parser("legacy-compatibility", help="Compare two original v1 plans; preserve STRICT_FAIL.")
    legacy.add_argument("--saved-plan", type=Path, required=True)
    legacy.add_argument("--replayed-plan", type=Path, required=True)
    legacy.add_argument("--strict-failure", type=Path, required=True)
    legacy.add_argument("--expected-producer-sha256", required=True)
    legacy.add_argument("--output", type=Path, required=True)
    generate = sub.add_parser("generate-plan", help="Rebuild a new v2 source plan using prior-stage bindings.")
    generate.add_argument("--prior-plan", type=Path, required=True)
    verify = sub.add_parser("verify-plan", help="Cold-rebuild a saved v2 plan in a new invocation.")
    verify.add_argument("--plan", type=Path, required=True)
    for command in (generate, verify):
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--expected-source-sha256", required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    repo, output = args.repo.resolve(), args.output.resolve()
    execution_output = output.with_suffix(output.suffix + ".execution.json")
    if output.exists() or execution_output.exists():
        parser.error("output or execution receipt already exists; choose new paths")
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(repo / "cad_photo_to_dxf"))
    from app.native_objects import attached_stroke_graph as graph
    from app.native_objects import attached_stroke_numeric as numeric

    watched = {"graph_module": Path(graph.__file__), "numeric_module": Path(numeric.__file__)}
    if args.command == "legacy-compatibility":
        watched.update(saved_plan=args.saved_plan, replayed_plan=args.replayed_plan, strict_failure=args.strict_failure)
    else:
        watched["source"] = args.input
        watched["prior_plan" if args.command == "generate-plan" else "saved_v2_plan"] = (
            args.prior_plan if args.command == "generate-plan" else args.plan)
        if _sha(args.input) != args.expected_source_sha256:
            raise ValueError("SOURCE_BYTES_DIFFER_FROM_EXPLICIT_SHA256_ANCHOR")
    before = {name: _sha(path) for name, path in watched.items()}
    execution = {"command": args.command, "checkout": _checkout(repo), "input_sha256_before": before,
                 "contract": numeric.contract_identity(), "new_OCR_calls": 0, "new_model_calls": 0,
                 "new_DXF_generated": False, "ordinary_conversion_run": False,
                 "existing_evidence_modified": False}
    started = time.perf_counter()
    if args.command == "legacy-compatibility":
        failure = _read(args.strict_failure)
        if failure.get("pass") is not False and failure.get("status") != "FAIL":
            raise ValueError("LEGACY_STRICT_FAILURE_RECEIPT_REQUIRED")
        report = numeric.compare_legacy_plans(
            _read(args.saved_plan), _read(args.replayed_plan),
            expected_producer_sha256=args.expected_producer_sha256,
        )
        okay = report["pass"]
        execution["status"] = report["status"]
        execution["legacy_original_strict_status"] = report["legacy_original_strict_status"]
        execution["legacy_original_failure_receipt_preserved"] = True
        execution["legacy_dxf_relabelled_as_new_execution"] = False
    else:
        import numpy as np
        from PIL import Image

        with Image.open(args.input) as image:
            gray = np.asarray(image.convert("L"))
        if args.command == "generate-plan":
            prior = _read(args.prior_plan)
            report = graph.plan_attached_stroke_graph(gray, prior["roi_xyxy_px"], prior["prior_object_bindings"])
            okay = True
            execution.update(status="GENERATED_NEW_V2_SOURCE_PLAN_ONLY", proposed_path_count=len(report["paths"]),
                             pending_component_count=len(report["pending"]),
                             prior_object_bindings_are_inputs_not_new_adoption_approval=True)
        else:
            plan = _read(args.plan)
            report = graph.verify_attached_stroke_graph_plan(gray, plan["roi_xyxy_px"], plan)
            okay = report["pass"]
            execution.update(status="PASS_V2_SOURCE_PLAN_REPLAY" if okay else "FAIL_V2_SOURCE_PLAN_REPLAY",
                             numeric_adoption_status=report.get("numeric_adoption_status"))
    execution["wall_seconds"] = time.perf_counter() - started
    execution["input_sha256_after"] = {name: _sha(path) for name, path in watched.items()}
    execution["original_inputs_and_source_modules_unchanged"] = before == execution["input_sha256_after"]
    if not execution["original_inputs_and_source_modules_unchanged"]:
        execution["status"] = "FAIL_INPUT_OR_IMPLEMENTATION_CHANGED_DURING_EXECUTION"
        okay = False
    _write_new(output, report)
    execution["output_sha256"] = _sha(output)
    _write_new(execution_output, execution)
    print(json.dumps({"status": execution["status"], "output": str(output),
                      "execution_receipt": str(execution_output), "wall_seconds": execution["wall_seconds"]}))
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
