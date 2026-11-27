"""Common acceptance from actual source and saved DXF, with separate verdicts.

This entry point imports neither candidate discovery nor production PASS flags.
The numerical replay receipt is attached as a separately identified result;
it never overrides the saved-file or original-pixel observations.
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
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    _write(output, {"argv": command, "returncode": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise RuntimeError("COMMON_AUDIT_SUBPROCESS_FAILED: " + script)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-roi", nargs=4, type=int, required=True)
    parser.add_argument("--audit-roi", nargs=4, type=int, required=True)
    parser.add_argument("--dpi", type=float, required=True)
    parser.add_argument("--numerical-replay-receipt", type=Path)
    parser.add_argument("--edit-copies", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    saved_dir = args.out / "saved"
    arguments = ["--source", args.source, "--baseline", args.baseline,
                 "--dxf", args.dxf, "--metadata", args.metadata,
                 "--roi", *args.source_roi, "--dpi", args.dpi,
                 "--output-dir", saved_dir]
    if args.edit_copies:
        arguments.append("--edit-copies")
    _run("run_saved_audit.py", arguments, args.out / "saved_process.json")
    saved = _read(saved_dir / "SAVED_GEOMETRY_AND_EDITS.json")
    raw_path = args.out / "RAW_SOURCE_RESPONSIBILITY.json"
    targets = saved["target_object_ids"]
    if targets:
        _run("run_raw_source_audit.py", ["--source", args.source,
             "--geometry-json", saved_dir / "ACTUAL_SAVED_SOURCE_GEOMETRIES.json",
             "--roi", *args.audit_roi, "--out", raw_path], args.out / "raw_process.json")
        raw = _read(raw_path)
        raw_summary = raw["summary"]
    else:
        raw_summary = {"status": "NO_NEW_TARGET_GEOMETRY", "independent_source_ownership_proved": False,
                       "may_adopt_objects_from_this_report_alone": False}
    numerical = {"status": "NOT_SUPPLIED", "independently_rerun_by_this_entry_point": False}
    if args.numerical_replay_receipt:
        receipt = _read(args.numerical_replay_receipt)
        numerical = {"path": str(args.numerical_replay_receipt),
                     "sha256": sha256(args.numerical_replay_receipt),
                     "independently_rerun_by_this_entry_point": False,
                     "external_receipt": receipt,
                     "scope": "Separate replay evidence; cannot override either independent layer"}
    result = {
        "schema": "issue60-common-independent-acceptance-v1",
        "actual_source_sha256": sha256(args.source), "actual_dxf_sha256": sha256(args.dxf),
        "externally_bound_source_frame": {"roi": args.source_roi, "dpi": args.dpi},
        "independent_raw_evaluation_window": args.audit_roi,
        "identity_and_numerical_replay": numerical,
        "actual_saved_geometry_and_edit_isolation": {
            "protection": saved["baseline_protection_status"],
            "target_binding": saved["actual_target_bindings_status"],
            "edit_isolation": saved["edit_isolation_status"],
            "input_files_unchanged": saved["inputs_unchanged"],
            "receipt_sha256": sha256(saved_dir / "SAVED_GEOMETRY_AND_EDITS.json")},
        "original_pixel_source_responsibility": raw_summary,
        "target_object_ids": targets,
        "combined_adoption_authorized": False,
        "source_complete_ownership": "NOT_ESTABLISHED_BY_LIMITED_RAW_MODEL",
        "producer_PASS_consumed_by_independent_geometry_or_pixel_decisions": False,
        "GUI": "NOT_RUN", "ordinary_new_full_region_conversion": "NOT_RUN",
    }
    _write(args.out / "COMMON_ACCEPTANCE.json", result)
    print(json.dumps({"saved": result["actual_saved_geometry_and_edit_isolation"],
                      "raw_source": raw_summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
