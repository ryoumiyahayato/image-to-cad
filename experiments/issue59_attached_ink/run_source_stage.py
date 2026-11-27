"""Rebuild source and re-evaluate A's *prior* objects with the new local gates.

This is a stage diagnostic, not a new ordinary DXF or an imported A adoption.
The old plan supplies retained prior bindings only; its proposed paths are not
passed to the producer.  All new component discovery and ink proofs run afresh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--prior-plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.repo.resolve() / "cad_photo_to_dxf"))
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects import text_contact_geometry as contact
    from app.native_objects.contracts import save_json
    from PIL import Image

    cv2.setNumThreads(1)
    old = json.loads(args.prior_plan.read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(args.source.read_bytes()).hexdigest()
    prior_sha = hashlib.sha256(args.prior_plan.read_bytes()).hexdigest()
    with Image.open(args.source) as image:
        gray = np.asarray(image.convert("L"))
    print("Rebuilding unchanged source graph", file=sys.stderr, flush=True)
    started = time.perf_counter()
    context = contact.build_text_contact_source_graph(gray, old["roi_xyxy_px"])
    if (context.crop_bbox != old["original_source_crop_xyxy_px"]
            or context.source_crop_hash != old["original_source_crop_array_sha256"]):
        raise ValueError("ACTUAL_SOURCE_CROP_DIFFERS_FROM_THE_PRIOR_BINDINGS")
    graph_seconds = time.perf_counter() - started
    print(f"Fresh source graph: {graph_seconds:.3f} seconds; evaluating prior bindings", file=sys.stderr, flush=True)
    completion = attached.complete_attached_strokes(
        gray, old["roi_xyxy_px"], source_sha, old["prior_object_bindings"],
        args.output / "attached", source_graph=context)
    plan = completion["plan"]
    endpoint_rows = []
    for component in plan["components"]:
        for row in component.get("candidate_paths", []):
            for terminal in row["endpoint_evidence"]:
                proof = terminal.get("attached_raw_ink_responsibility")
                if not proof:
                    continue
                endpoint_rows.append({
                    "component_id": component["component_id"], "guest_id": row["stroke_id"],
                    "host_id": proof["host_id"], "status": proof["status"], "pass": proof["pass"],
                    "failure_reasons": proof["failure_reasons"],
                    "widths": {key: {field: value[field] for field in
                        ("pass", "independent_section_count", "half_width_interval_px")}
                        for key, value in proof.get("independent_width_evidence", {}).items()},
                    "unexplained_original_cells": proof.get("unexplained_original_cells"),
                    "observable_boundary_competition": proof.get("short_continuation_competition", {}).get(
                        "distinct_observable_boundary_exists"),
                    "complete_pixel_accounting": proof.get("complete_pixel_accounting"),
                    "ledger_count": len(proof.get("pixel_ledger", [])),
                    "feasible_terminal_model_count": len((proof.get("coherent_terminal_models") or {}).get("feasible_models", [])),
                })
    summary = {
        "schema": "issue59-fresh-source-stage-diagnostic-v1",
        "status": "STAGE_ONLY_NO_ORDINARY_DXF_CLAIM",
        "source_sha256": source_sha, "prior_plan_file_sha256": prior_sha,
        "source_crop_sha256": context.source_crop_hash, "graph_rebuilt_from_current_source": True,
        "prior_binding_count": len(old["prior_object_bindings"]),
        "old_proposed_paths_imported": False, "new_stage_object_count": len(completion["objects"]),
        "producer_sha256": plan["producer_sha256"], "additional_producer_sha256": plan["additional_producer_sha256"],
        "new_plan_schema": plan["schema"], "graph_seconds": graph_seconds,
        "total_seconds": time.perf_counter() - started, "endpoints": endpoint_rows,
        "pending": plan["pending"], "new_OCR_calls": 0,
    }
    save_json(args.output / "STAGE_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
