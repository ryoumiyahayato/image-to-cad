"""Rebuild a real source stage and save explicitly non-ordinary local geometry.

The prior plan contributes its prior bindings and source scope only. No earlier
candidate, adopted path or PASS is supplied to the new component producer.
Private paths are command arguments, never recognizer selection rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def source_files(repo):
    files = sorted((repo / "cad_photo_to_dxf/app").rglob("*.py"))
    files += sorted((repo / "docs/native").glob("ISSUE62_*.md"))
    files.append(Path(__file__).resolve())
    return {str(path.relative_to(repo)): sha(path) for path in files}


def save_local_drawings(out, plan, source_sha, baseline_dxf=None):
    import ezdxf
    from app.native_objects.cad_io import APPID, save_native_dxf

    rows, neighbors = {}, {}
    for component in plan["components"]:
        for row in component.get("candidate_paths", []):
            rows[row["stroke_id"]] = row
        for body in component.get("finite_component_responsibility", {}).get("bodies", []):
            if body["body_role"] == "NECESSARY_PRIOR_FINITE_NEIGHBOR":
                neighbors[body["stroke_id"]] = body
    adopted = {row["stroke_id"] for row in plan["paths"]}
    files = []
    for include_context in (False, True):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = 0
        doc.appids.new(APPID)
        for name, color in (("NOT_ADOPTED", 1), ("LOCAL_STAGE_SELECTED", 3), ("CONTEXT_PRIOR", 8)):
            doc.layers.new(name, dxfattribs={"color": color})
        mappings = []
        for identity, row in [*rows.items(), *(neighbors.items() if include_context else [])]:
            geometry = row["representation"]
            context = identity in neighbors
            status = "PRIOR_CONTEXT_ONLY" if context else "STAGE_SELECTED" if identity in adopted else "NOT_ADOPTED"
            layer = "CONTEXT_PRIOR" if context else "LOCAL_STAGE_SELECTED" if identity in adopted else "NOT_ADOPTED"
            entity = doc.modelspace().add_lwpolyline(geometry["points"], close=False, dxfattribs={"layer": layer})
            entity.set_xdata(APPID, [(1000, json.dumps({"id": identity, "kind": "CONNECTION_PATH"}))])
            mappings.append({"object_id": identity, "handle": entity.dxf.handle, "status": status,
                             "layer": layer, "points": geometry["points"], "bulges": geometry.get("bulges", [])})
        name = "LOCAL_CANDIDATES_WITH_CONTEXT.dxf" if include_context else "LOCAL_CANDIDATES_ONLY.dxf"
        path = out / name
        save_native_dxf(doc, path)
        files.append({"file": name, "sha256": sha(path), "size_bytes": path.stat().st_size,
                      "target_ids": sorted(rows), "context_ids": sorted(neighbors) if include_context else [],
                      "source_sha256": source_sha, "entities": mappings,
                      "coordinate_frame": "UNCHANGED_SOURCE_PIXEL_COORDINATES_Y_DOWN",
                      "units": "PIXELS_NOT_PAPER_MM", "ordinary_whole_region_result": False,
                      "formal_new_objects_claimed_from_this_local_file": False})
    if baseline_dxf is not None:
        baseline_sha = sha(baseline_dxf)
        doc = ezdxf.readfile(baseline_dxf)
        if doc.units != 4:
            raise ValueError("BASELINE_CONTEXT_MUST_BE_ACTUAL_PAPER_MM")
        if "NOT_ADOPTED_ISSUE62" not in doc.layers:
            doc.layers.new("NOT_ADOPTED_ISSUE62", dxfattribs={"color": 1})
        x0, _, _, y1 = plan["roi_xyxy_px"]
        mm = 25.4 / 200
        mappings = []
        for identity, row in rows.items():
            points = [[(x - x0) * mm, (y1 - y) * mm] for x, y in row["representation"]["points"]]
            entity = doc.modelspace().add_lwpolyline(points, close=False, dxfattribs={"layer": "NOT_ADOPTED_ISSUE62"})
            entity.set_xdata(APPID, [(1000, json.dumps({"id": identity, "kind": "CONNECTION_PATH",
                                                       "diagnostic_status": "NOT_ADOPTED"}))])
            mappings.append({"object_id": identity, "handle": entity.dxf.handle, "status": "NOT_ADOPTED",
                             "layer": "NOT_ADOPTED_ISSUE62", "points": points, "bulges": [0.0] * len(points)})
        path = out / "NOT_ADOPTED_BASELINE_CONTEXT_REVIEW.dxf"
        save_native_dxf(doc, path)
        if sha(baseline_dxf) != baseline_sha:
            raise ValueError("ORIGINAL_BASELINE_BYTES_CHANGED")
        files.append({"file": path.name, "sha256": sha(path), "size_bytes": path.stat().st_size,
                      "target_ids": sorted(rows), "context_source_dxf_sha256": baseline_sha,
                      "source_sha256": source_sha, "entities": mappings,
                      "all_modelspace_entity_count": len(doc.modelspace()),
                      "coordinate_frame": "PAPER_MM_AT_DECLARED_ROI", "dpi": 200,
                      "units": "paper_mm", "engineering_scale": "UNVERIFIED",
                      "ordinary_whole_region_result": False,
                      "formal_new_objects_claimed_from_this_local_file": False,
                      "purpose": "UNADOPTED_CANDIDATES_OVER_ACTUAL_BASELINE_FOR_INDEPENDENT_SOURCE_REVIEW"})
    write(out / "LOCAL_DRAWINGS.json", {"files": files})


def cold_drawings(out):
    import ezdxf

    records = json.loads((out / "LOCAL_DRAWINGS.json").read_text(encoding="utf-8"))
    checks = []
    for record in records["files"]:
        doc = ezdxf.readfile(out / record["file"])
        rows = []
        for expected in record["entities"]:
            entity = doc.entitydb.get(expected["handle"])
            actual = ([[float(x), float(y)] for x, y in entity.get_points("xy")]
                      if entity is not None and entity.dxftype() == "LWPOLYLINE" else None)
            rows.append({"object_id": expected["object_id"], "pass": actual == expected["points"]
                         and not entity.closed and entity.dxf.layer == expected["layer"]})
        checks.append({"file": record["file"], "sha256_matches": sha(out / record["file"]) == record["sha256"],
                       "entity_count_exact": len(doc.modelspace()) == record.get("all_modelspace_entity_count", len(record["entities"])),
                       "every_finite_vertex_and_layer_exact": all(row["pass"] for row in rows), "rows": rows})
    report = {"schema": "issue62-local-candidate-save-cold-read-v1", "fresh_process": True,
              "checks": checks, "pass": all(row["sha256_matches"] and row["entity_count_exact"]
                                             and row["every_finite_vertex_and_layer_exact"] for row in checks),
              "source_complete_responsibility": "SEPARATE_INDEPENDENT_AUDIT_REQUIRED",
              "new_real_adopted_object_edits": "NOT_CLAIMED_BY_LOCAL_CANDIDATE_DRAWINGS"}
    write(out / "LOCAL_SAVED_GEOMETRY_COLD_READ.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--prior-plan", type=Path)
    parser.add_argument("--baseline-dxf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cold-drawings", action="store_true")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.repo.resolve() / "cad_photo_to_dxf"))
    if args.cold_drawings:
        print(json.dumps(cold_drawings(args.output), ensure_ascii=False))
        return
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects import text_contact_geometry as contact
    from PIL import Image

    cv2.setNumThreads(1)
    args.output.mkdir(parents=True, exist_ok=False)
    before = source_files(args.repo)
    started = time.perf_counter()
    old = json.loads(args.prior_plan.read_text(encoding="utf-8"))
    with Image.open(args.source) as image:
        gray = np.asarray(image.convert("L"))
    source_sha = sha(args.source)
    print("Rebuilding the unchanged source graph", flush=True)
    context = contact.build_text_contact_source_graph(gray, old["roi_xyxy_px"])
    if (context.crop_bbox != old["original_source_crop_xyxy_px"]
            or context.source_crop_hash != old["original_source_crop_array_sha256"]):
        raise ValueError("ORIGINAL_SOURCE_SCOPE_DOES_NOT_MATCH_PRIOR_BINDINGS")
    graph_seconds = time.perf_counter() - started
    print("Running the complete finite-component source stage", flush=True)
    adoption = attached.complete_attached_strokes(gray, old["roi_xyxy_px"], source_sha,
        old["prior_object_bindings"], args.output / "attached", source_graph=context)
    plan = adoption["plan"]
    save_local_drawings(args.output, plan, source_sha, args.baseline_dxf)
    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
        "--output", str(args.output), "--cold-drawings"], text=True, capture_output=True, check=False)
    (args.output / "cold_drawings.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    summaries = []
    for component in plan["components"]:
        proof = component.get("finite_component_responsibility")
        if proof is None:
            continue
        summaries.append({"component_id": component["component_id"], "status": proof["status"],
            "pass": proof["pass"], "failure_reasons": proof["failure_reasons"],
            "candidate_ids": proof["candidate_ids"], "bodies": [{
                "object_id": body["stroke_id"], "role": body["body_role"],
                "chain_binding": body["chain_binding"], "width_pass": body["width"]["pass"],
                "width_reason": body["width"].get("reason"),
                "independent_sections": body["width"]["independent_section_count"],
                "half_width_squared_interval": body["width"].get("half_width_squared_interval"),
                "half_width_interval_px_approx": body["width"].get("half_width_interval_px_approx"),
                "finite_centerline_original_source_pass": body["native_centerline_source_support"]["pass"]}
                for body in proof["bodies"]],
            "endpoints": proof.get("endpoints", []),
            "model_status": proof.get("coherent_component_model", {}).get("status"),
            "black_ledger_count": len(proof.get("pixel_ledger", [])),
            "white_ledger_count": len(proof.get("white_ledger", [])),
            "observation_closed": proof.get("observation_closed"),
            "unknown_exit_count": sum(e["classification"] == "UNKNOWN_CONNECTED_EXIT" for e in proof.get("window_exits", [])),
            "shared_vertex_construction": component.get("shared_finite_vertex_construction"),
            "prior_native_contact_pass": component.get("prior_native_contact_check", {}).get("pass"),
            "failed_adoption_gates": component.get("failed_adoption_gates", [])})
    identity = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip(),
                "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=args.repo, text=True).strip(),
                "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=args.repo, text=True).strip())}
    report = {"schema": "issue62-complete-finite-source-stage-v1", "scope": "LOCAL_STAGE_NOT_ORDINARY_WHOLE_REGION",
              "source_sha256": source_sha, "prior_plan_sha256": sha(args.prior_plan),
              "original_source_crop_array_sha256": context.source_crop_hash,
              "roi_xyxy_px": old["roi_xyxy_px"], "prior_binding_count": len(old["prior_object_bindings"]),
              "old_proposed_paths_imported": False, "fresh_source_graph": True,
              "new_stage_adopted_count": len(adoption["objects"]), "components": summaries,
              "new_OCR_calls": 0, "new_model_inferences": 0, "graph_seconds": graph_seconds,
              "total_seconds": time.perf_counter() - started, "execution_identity": identity,
              "source_files_sha256": before, "source_files_unchanged_during_run": before == source_files(args.repo),
              "producer_sha256": plan["producer_sha256"], "additional_producer_sha256": plan["additional_producer_sha256"],
              "local_dxf_cold_process_exit_code": completed.returncode,
              "new_real_object_delete_move": "NOT_APPLICABLE" if not adoption["objects"] else "REQUIRES_ORDINARY_INTEGRATION",
              "valid_baseline_replaced": False, "ordinary_joint_run": "NOT_RUN_IN_THIS_LOCAL_STAGE"}
    write(args.output / "STAGE_SUMMARY.json", report)
    write(args.output / "FILE_MANIFEST.json", {str(path.relative_to(args.output)):
        {"size_bytes": path.stat().st_size, "sha256": sha(path)} for path in sorted(args.output.rglob("*")) if path.is_file()})
    print(json.dumps({"adopted": len(adoption["objects"]), "seconds": report["total_seconds"],
                      "components": [{"status": row["status"], "failures": row["failure_reasons"]} for row in summaries]}, indent=2))


if __name__ == "__main__":
    main()
