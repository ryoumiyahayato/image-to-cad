"""Independent saved-file inspection and fresh-process whole-entity edits."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from app.native_objects import independent_saved_geometry_audit as audit


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--roi", nargs=4, type=int)
    parser.add_argument("--dpi", type=float)
    parser.add_argument("--output-dir", type=Path)
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
        if args.child_action == "write":
            result = audit.make_edit_copy(args.dxf, args.edited, args.target_id, args.operation)
        else:
            result = audit.audit_edit_copy(args.dxf, args.edited, args.target_id, args.operation)
        result["process_id"] = os.getpid()
        result["process_role"] = args.child_action
        write_json(args.report, result)
        return 0
    if not all([args.baseline, args.metadata, args.output_dir, args.source, args.roi, args.dpi]):
        parser.error("baseline, metadata, source, externally specified roi/dpi and output-dir are required for inspection")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    before = {str(p): audit.sha256(p) for p in [args.baseline, args.dxf, args.metadata, args.source]}
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    protection = audit.compare_saved_dxf(args.baseline, args.dxf)
    targets = protection["new_object_ids"]
    bindings = audit.audit_saved_target_bindings(args.dxf, args.metadata, targets,
        expected_roi=args.roi, expected_dpi=args.dpi, expected_source_sha256=audit.sha256(args.source))
    geometries = audit.saved_source_geometries(args.dxf, args.roi, args.dpi)
    geometries["external_source_sha256"] = audit.sha256(args.source)
    geometries["target_object_ids"] = targets
    geometries["attachment_declarations"] = []
    for row in metadata["objects"]:
        if row["id"] not in targets:
            continue
        # Optional producer declarations are exported as claims only. They do
        # not change actual saved geometry or decide raw-pixel responsibility.
        source_path = row.get("source_evidence", {}).get("attached_stroke_graph", {}).get("path", {})
        for index, terminal in enumerate(source_path.get("endpoint_evidence", [])):
            if terminal.get("host_path_id"):
                geometries["attachment_declarations"].append({
                    "guest": row["id"], "end": index, "host": terminal["host_path_id"],
                    "declaration_origin": "producer declaration requiring independent source review"})
    write_json(args.output_dir / "BASELINE_PROTECTION.json", protection)
    write_json(args.output_dir / "ACTUAL_TARGET_BINDINGS.json", bindings)
    write_json(args.output_dir / "ACTUAL_SAVED_SOURCE_GEOMETRIES.json", geometries)
    write_json(args.output_dir / "BASELINE_SNAPSHOT.json", audit.snapshot_dxf(args.baseline))
    write_json(args.output_dir / "ACTUAL_DXF_SNAPSHOT.json", audit.snapshot_dxf(args.dxf))
    edits = []
    if args.edit_copies:
        edit_dir = args.output_dir / "edits"
        edit_dir.mkdir()
        for index, target in enumerate(targets):
            for operation in ("delete", "move"):
                stem = f"target_{index + 1}_{operation}"
                edited = edit_dir / (stem + ".dxf")
                phases = []
                for action in ("write", "cold-read"):
                    report = edit_dir / (stem + "_" + action + ".json")
                    command = [sys.executable, str(Path(__file__).resolve()),
                               "--child-action", action, "--dxf", str(args.dxf),
                               "--edited", str(edited), "--target-id", target,
                               "--operation", operation, "--report", str(report)]
                    process = subprocess.run(command, capture_output=True, text=True, check=False)
                    log = {"argv": command, "returncode": process.returncode,
                           "stdout": process.stdout, "stderr": process.stderr}
                    write_json(edit_dir / (stem + "_" + action + "_process.json"), log)
                    if process.returncode:
                        raise RuntimeError("EDIT_SUBPROCESS_FAILED: " + stem + " " + action)
                    phases.append(json.loads(report.read_text(encoding="utf-8")))
                assert phases[0]["process_id"] != phases[1]["process_id"]
                edits.append({"target_id": target, "operation": operation,
                              "write_receipt": phases[0], "independent_cold_read": phases[1]})
    after = {str(p): audit.sha256(p) for p in [args.baseline, args.dxf, args.metadata, args.source]}
    summary = {
        "schema": "issue60-independent-saved-acceptance-execution-v1",
        "executed_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "inputs_before": before, "inputs_after": after, "inputs_unchanged": before == after,
        "checker_sha256": audit.sha256(Path(audit.__file__)), "runner_sha256": audit.sha256(Path(__file__)),
        "baseline_protection_status": protection["status"], "actual_target_bindings_status": bindings["status"],
        "target_object_ids": targets, "edits": edits,
        "edit_isolation_status": ("PASS" if edits and all(e["independent_cold_read"]["status"] == "PASS" for e in edits)
                                  else "NOT_RUN" if not edits else "FAIL"),
        "drawing_provenance": "Input frozen drawing; no new production conversion claimed",
        "ordinary_full_region_conversions": 0, "new_OCR_calls": 0, "new_model_calls": 0,
        "CAD_GUI": "NOT_RUN", "source_complete_responsibility": "SEPARATE_REVIEW_REQUIRED",
    }
    write_json(args.output_dir / "SAVED_GEOMETRY_AND_EDITS.json", summary)
    print(json.dumps({k: summary[k] for k in ("baseline_protection_status", "actual_target_bindings_status", "edit_isolation_status", "target_object_ids")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
