"""Frozen synthetic counterexample runner for shared-core track research.

Run only after reviewing the implementation. Each invocation creates a fresh
output directory and never overwrites a preceding failure or test report.
No real A2/HABS source is read or executed by this runner.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import resource
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from independent_fixtures import Fixture, fixtures, native_version
from independent_native_fixtures import direct_native_fixtures
from independent_native_pen import line_ink, run_mask
from independent_oracle import Observation, inspect


CLEAR_POSITIVES = ("T_long_arms", "cross_long_arms")
SEMANTIC_KEYS = ("geometric_contact", "historical_object_identity", "electrical_semantics")


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest_array(array):
    return digest_bytes(np.ascontiguousarray(array).tobytes())


def fingerprint_code(repo: Path, proposal: Path):
    paths = set((repo / "cad_photo_to_dxf" / "app").rglob("*.py"))
    # Other agents may write orchestration scripts next to the proposal. They
    # are not imported by this runner and are outside its executed method.
    paths.add(proposal)
    paths.add(Path(__file__).resolve())
    paths.update(Path(__file__).parent.glob("independent_*.py"))
    return {str(path.resolve()): digest_bytes(path.read_bytes()) for path in sorted(paths)}


def serializable(value, arrays, prefix="root"):
    if isinstance(value, np.ndarray):
        name = prefix.replace("/", "_")
        arrays[name] = value
        return {"array_key": name, "shape": value.shape, "dtype": str(value.dtype),
                "sha256": digest_array(value)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): serializable(child, arrays, f"{prefix}_{key}")
                for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(child, arrays, f"{prefix}_{index}")
                for index, child in enumerate(value)]
    return value


def source_cases():
    for fixture in fixtures():
        yield fixture.name, fixture, native_version(fixture), 2, fixture.dpi
    for native_case in direct_native_fixtures():
        gray = native_case.working_gray
        blank = np.zeros(gray.shape, bool)
        working = Fixture(native_case.name, native_case.native.family, gray,
                          blank.copy(), blank.copy(), blank.copy(),
                          np.where(gray < 254, 0, 255).astype(np.uint8),
                          native_case.native.expectation, native_case.native.notes,
                          native_case.dpi)
        yield native_case.name, working, native_case.native, native_case.scale, native_case.dpi


def expected_parent_source(native_source, working_component, scale):
    return native_source & np.repeat(np.repeat(working_component, scale, 0), scale, 1)


def recover_candidates(result):
    value = result.get("candidates", [])
    if not isinstance(value, (list, tuple)):
        raise ValueError("candidate list is not explicit")
    return list(value)


def inspect_case(name, fixture, native_fixture, scale, dpi, recover, output):
    gray = fixture.gray.copy()
    native_gray = native_fixture.gray.copy()
    binary = np.where(gray < 254, 0, 255).astype(np.uint8)
    visible = fixture.visible.copy()
    protected = fixture.protected.copy()
    count, labels = cv2.connectedComponents(np.uint8(gray < 254), connectivity=8)
    np.savez_compressed(output / f"{name}.inputs.npz", gray=gray, native_gray=native_gray,
                        binary=binary, visible=visible, protected=protected,
                        native_must_retain=native_fixture.must_retain,
                        native_white_fence=native_fixture.white_fence)
    parent_rows = []
    all_parts = []
    retired_masks = []
    all_residual = np.zeros(native_gray.shape, bool)
    failures = []
    method_exceptions = []
    for label in range(1, count):
        component = labels == label
        foreign = ((gray < 254) & ~component) | protected
        parent = expected_parent_source(native_fixture.source, component, scale)
        inputs = {"gray": gray, "component": component, "foreign": foreign,
                  "native_gray": native_gray, "binary": binary,
                  "visible_binary": visible, "protected": protected}
        before = {key: digest_array(array) for key, array in inputs.items()}
        start = time.monotonic()
        try:
            result = recover(gray, component, foreign, native_gray=native_gray,
                             native_scale=scale, dpi=dpi, binary=binary,
                             visible_binary=visible, protected_masks=(protected,))
        except Exception as error:
            result = {"status": "EXCEPTION", "exception_type": type(error).__name__,
                      "exception": str(error), "traceback": traceback.format_exc()}
            method_exceptions.append(result)
            failures.append(f"parent_{label}_method_exception")
        elapsed = time.monotonic() - start
        after = {key: digest_array(array) for key, array in inputs.items()}
        unchanged = before == after
        if not unchanged:
            failures.append(f"parent_{label}_input_mutation")
        arrays = {}
        serialized = serializable(result, arrays)
        (output / f"{name}.parent_{label}.result.json").write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2, allow_nan=False))
        if arrays:
            np.savez_compressed(output / f"{name}.parent_{label}.arrays.npz", **arrays)
        row = {"label": label, "working_source_pixels": int(component.sum()),
               "native_source_pixels": int(parent.sum()), "status": result.get("status"),
               "reason": result.get("reason"), "input_unchanged": unchanged,
               "input_sha256_before": before, "input_sha256_after": after,
               "wall_seconds": elapsed, "decision_reasons": dict(Counter(
                   decision.get("reason", "UNSPECIFIED") for decision in result.get("decisions", []))),
               "semantics": {key: result.get(key, "MISSING") for key in SEMANTIC_KEYS}}
        try:
            parts = recover_candidates(result)
            source_runs = result.get("native_source_runs_y_x0_x1")
            if source_runs is not None:
                if not np.array_equal(run_mask(parent.shape, source_runs), parent):
                    failures.append(f"parent_{label}_source_ledger_changed")
            residual_runs = result.get("native_residual_runs_y_x0_x1")
            if residual_runs is None:
                if parts:
                    raise ValueError("candidates with missing retained-source ledger")
                expected_guard = None
                if np.any(component & (foreign | protected)):
                    expected_guard = "WHOLE_PARENT_PROTECTED_OR_FOREIGN"
                elif np.any(component & (binary >= 128)):
                    expected_guard = "WHOLE_PARENT_SOURCE_NOT_CURRENT"
                elif np.any(component & (visible >= 128)):
                    expected_guard = "WHOLE_PARENT_ALREADY_CLAIMED"
                if (expected_guard is None or result.get("reason") != expected_guard
                        or result.get("status") != "REJECTED"
                        or result.get("native_retired_source_pixels", 0) != 0
                        or source_runs is not None):
                    failures.append(f"parent_{label}_unexpected_unbound_source_rejection")
                residual = parent.copy()
                row["no_result_ledger"] = (
                    "Expected whole-parent guard checked against original inputs; no native ledger was bound, "
                    "zero candidates and zero retirement, arrays unchanged; original source retained.")
                row["expected_whole_parent_guard"] = expected_guard
            else:
                residual = run_mask(parent.shape, residual_runs)
            row["candidate_count"] = len(parts)
            all_residual |= residual
            parent_retired = np.zeros(parent.shape, bool)
            for index, part in enumerate(parts):
                retired = run_mask(parent.shape, part["native_retired_source_runs_y_x0_x1"])
                if np.any(retired & ~parent):
                    failures.append(f"parent_{label}_part_{index}_claims_other_parent")
                if np.any(parent_retired & retired):
                    failures.append(f"parent_{label}_duplicate_retirement")
                parent_retired |= retired
                all_parts.append((label, part))
                retired_masks.append(retired)
            if np.any(residual & parent_retired) or not np.array_equal(residual | parent_retired, parent):
                failures.append(f"parent_{label}_source_accounting_not_exact")
            if parts:
                if result.get("electrical_semantics") != "NOT_INFERRED":
                    failures.append(f"parent_{label}_electrical_contract_missing_or_inferred")
                if result.get("historical_object_identity") != "NOT_PROVEN":
                    failures.append(f"parent_{label}_historical_identity_missing_or_inferred")
                if result.get("geometric_contact") != "OBSERVED_SOURCE_ONLY":
                    failures.append(f"parent_{label}_geometric_contact_contract_missing")
                if result.get("full_object_movable") is not False:
                    failures.append(f"parent_{label}_partial_edit_scope_not_declared")
                if result.get("production_retirement_authorized") is not False:
                    failures.append(f"parent_{label}_unregistered_research_authorized_production")
        except Exception as error:
            row["oracle_exception"] = f"{type(error).__name__}: {error}"
            failures.append(f"parent_{label}_malformed_recovery_evidence")
        parent_rows.append(row)
    cap_reports = []
    for cap in ("round", "flat", "square"):
        pens = []
        try:
            for _label, part in all_parts:
                endpoints = (np.asarray(part["points_px"], float) + .5) * scale - .5
                width = float(part["lineweight_hundredth_mm"]) * dpi * scale / 2540.0
                pens.append(line_ink(native_gray.shape, endpoints, width, cap))
            rendered = all_residual.copy()
            for pen in pens:
                rendered |= pen
            observed = Observation(all_residual, retired_masks, rendered, pens,
                                   geometric_contact="OBSERVED_SOURCE_ONLY",
                                   object_identity="NOT_PROVEN",
                                   electrical_connectivity="NOT_INFERRED")
            audit = inspect(native_fixture, observed)
            audit.update(cap=cap, joins=("round", "mitre", "bevel"),
                         join_note="No interior join in a LINE; three labels denote the same geometry.",
                         missing_black_centers=int(np.count_nonzero(native_fixture.source & ~rendered)),
                         covered_white_centers=int(np.count_nonzero(rendered & ~native_fixture.source)))
            if not audit["pass"]:
                failures.extend(f"{cap}:{item}" for item in audit["failures"])
            cap_reports.append(audit)
        except Exception as error:
            failures.append(f"{cap}:oracle_render_exception")
            cap_reports.append({"pass": False, "cap": cap,
                                "exception": f"{type(error).__name__}: {error}"})
    if name in CLEAR_POSITIVES and not all_parts:
        failures.append("new_method_clear_positive_not_recovered")
    return {"name": name, "family": fixture.family, "source_kind": "SYNTHETIC_CONTROL",
            "expected": fixture.expectation, "notes": fixture.notes,
            "pass": not failures, "failures": failures, "parents": parent_rows,
            "candidate_count": len(all_parts), "cap_audits": cap_reports,
            "method_exception_count": len(method_exceptions),
            "limitations": "Center/state and annotated ownership checks; not complete continuous export or product acceptance."}


def missing_state_controls(recover, fixture, native_fixture, scale, dpi):
    rows = []
    gray = fixture.gray.copy()
    component = gray < 254
    binary = np.where(component, 0, 255).astype(np.uint8)
    blank = np.zeros(gray.shape, bool)
    for missing in ("binary", "visible_binary"):
        values = {"binary": binary.copy(), "visible_binary": binary.copy()}
        values[missing] = None
        try:
            result = recover(gray.copy(), component.copy(), blank.copy(),
                             native_gray=native_fixture.gray.copy(), native_scale=scale,
                             dpi=dpi, protected_masks=(blank.copy(),), **values)
            passed = not recover_candidates(result) and result.get("status") in ("REJECTED", "SKIPPED_INPUT_CONTRACT")
            rows.append({"omitted_state": missing, "pass": passed, "result": serializable(result, {})})
        except Exception as error:
            rows.append({"omitted_state": missing, "pass": False,
                         "exception": f"{type(error).__name__}: {error}"})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    before = fingerprint_code(args.repo, args.proposal)
    specification = {"status": "PRE_RUN_FROZEN", "created_utc": datetime.now(timezone.utc).isoformat(),
                     "proposal": str(args.proposal.resolve()), "code_sha256": before,
                     "cases": [name for name, *_ in source_cases()],
                     "new_method_clear_positive_names": CLEAR_POSITIVES,
                     "explicit_missing_state_checks": ("binary", "visible_binary"),
                     "real_sources_run": 0,
                     "control_manifest_sha256": digest_bytes((Path(__file__).parent / "controls_frozen.json").read_bytes()),
                     "native_manifest_sha256": digest_bytes((Path(__file__).parent / "native_audit_frozen.json").read_bytes())}
    (args.output / "pre_run_freeze.json").write_text(json.dumps(specification, indent=2))
    sys.path.insert(0, str(args.repo / "cad_photo_to_dxf"))
    sys.path.insert(0, str(args.proposal.parent))
    spec = importlib.util.spec_from_file_location("shared_core_proposal_under_review", args.proposal)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    recover = module.recover_shared_core_tracks
    start = time.monotonic()
    usage_start = resource.getrusage(resource.RUSAGE_SELF)
    rows = []
    for case in source_cases():
        row = inspect_case(*case, recover, args.output)
        rows.append(row)
        (args.output / f"{row['name']}.audit.json").write_text(json.dumps(row, ensure_ascii=False, indent=2))
        print(json.dumps({"case": row["name"], "pass": row["pass"],
                          "candidates": row["candidate_count"], "failures": row["failures"]}), flush=True)
    t_case = next(case for case in source_cases() if case[0] == "T_long_arms")
    state_rows = missing_state_controls(recover, *t_case[1:])
    usage_end = resource.getrusage(resource.RUSAGE_SELF)
    after = fingerprint_code(args.repo, args.proposal)
    summary = {"status": "PASS" if all(row["pass"] for row in rows) and all(row["pass"] for row in state_rows) and before == after else "FAIL",
               "synthetic_source_count": len(rows), "passing_source_count": sum(row["pass"] for row in rows),
               "failing_source_names": [row["name"] for row in rows if not row["pass"]],
               "candidate_count": sum(row["candidate_count"] for row in rows),
               "real_sources_run": 0, "production_adoptions": 0,
               "input_mutation_cases": [row["name"] for row in rows if any(not p["input_unchanged"] for p in row["parents"])],
               "method_exceptions": sum(row["method_exception_count"] for row in rows),
               "code_unchanged": before == after, "code_sha256_after": after,
               "missing_state_controls": state_rows,
               "wall_seconds": time.monotonic() - start,
               "user_cpu_seconds": usage_end.ru_utime - usage_start.ru_utime,
               "system_cpu_seconds": usage_end.ru_stime - usage_start.ru_stime,
               "process_peak_rss_kib": usage_end.ru_maxrss,
               "cases": rows,
               "limitations": ["All cases synthetic; no real A2 or HABS run.",
                               "No production export registration, saved DXF, GUI, or human editing-time claim.",
                               "Complete center-state preservation supplements but does not replace continuous/source ownership tests."]}
    summary["all_passed"] = summary["status"] == "PASS"
    (args.output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    concise = {key: summary[key] for key in ("all_passed", "status", "synthetic_source_count", "passing_source_count", "failing_source_names", "candidate_count", "code_unchanged", "method_exceptions", "wall_seconds", "process_peak_rss_kib")}
    concise["report_sha256"] = digest_bytes((args.output / "report.json").read_bytes())
    concise["proposal_sha256"] = before[str(args.proposal.resolve())]
    (args.output / "summary.json").write_text(json.dumps(concise, ensure_ascii=False, indent=2))
    print(json.dumps({key: summary[key] for key in ("status", "synthetic_source_count", "passing_source_count", "failing_source_names", "candidate_count", "code_unchanged", "wall_seconds", "process_peak_rss_kib")}), flush=True)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
