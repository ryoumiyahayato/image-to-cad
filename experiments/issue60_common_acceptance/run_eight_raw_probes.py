"""Rebuild declared probe sources, save new local DXFs, and cold-audit pixels.

The producer runs in its fixed repository. Each saved DXF is read in a separate
process. The audit module imports no producer result. For sources producing no
new target, a separate baseline-DXF counterfactual documents pixel sensitivity;
it is never represented as that variant's produced or accepted geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(_plain(value), stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return [_plain(item) for item in sorted(value)]
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    return value


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _produce(args):
    sys.path.insert(0, str(args.producer_repo / "cad_photo_to_dxf"))
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects.cad_io import export_objects
    from app.native_objects.text_contact_adoption import complete_text_contact_paths
    from PIL import Image
    from tests.test_native_transverse_stroke_geometry import ROI, _structure_stage

    cv2.setNumThreads(1)
    started = time.perf_counter()
    gray = np.asarray(Image.open(args.source).convert("L"))
    before = hashlib.sha256(gray.tobytes()).hexdigest()
    assert gray.shape == (ROI[3] - ROI[1], ROI[2] - ROI[0])
    context, initial, structure_plan = _structure_stage(gray)
    graph = context.graph
    ys, xs = np.nonzero(graph.skel)
    snapshot = {
        "source_array_sha256": before, "crop_bbox": context.crop_bbox,
        "crop_array_sha256": context.source_crop_hash,
        "skeleton_sha256": hashlib.sha256(graph.skel.tobytes()).hexdigest(),
        "skeleton_points_px": (np.column_stack((xs, ys)) + graph.origin.astype(int)).tolist(),
        "node_count": len(graph.nodes), "edge_count": len(graph.edges),
        "all_nodes": graph.nodes, "all_edges": graph.edges,
    }
    _json(args.out / "fresh_graph.json", snapshot)
    _json(args.out / "fresh_structure_plan.json", structure_plan)
    owner = complete_text_contact_paths(gray, ROI, before, initial, [structure_plan], args.out / "owner")
    prior = [row for row in initial if row["id"] not in owner["retired_ids"]] + owner["objects"]
    complete = attached.complete_attached_strokes(gray, ROI, before, prior,
                                                args.out / "attached", source_graph=context)
    _json(args.out / "producer_return.json", complete)
    objects = prior + complete["objects"]
    saved = args.out / "native" / "probe.dxf"
    export_objects(objects, saved, ROI, 200, before)
    declarations = []
    for row in complete["plan"]["paths"]:
        for index, endpoint in enumerate(row["endpoint_evidence"]):
            if endpoint.get("host_path_id"):
                declarations.append({"guest": row["stroke_id"], "end": index,
                                     "host": endpoint["host_path_id"],
                                     "producer_kind": endpoint.get("kind")})
    record = {
        "source_file_sha256": _sha(args.source), "source_array_sha256": before,
        "source_unchanged": hashlib.sha256(gray.tobytes()).hexdigest() == before,
        "producer_repo": str(args.producer_repo), "producer_module_sha256": _sha(attached.__file__),
        "fresh_graph_and_owner_rebuilt_from_this_source": True,
        "owner_objects_count": len(owner["objects"]),
        "produced_target_object_ids": [row["id"] for row in complete["objects"]],
        "produced_target_count": len(complete["objects"]),
        "producer_pending_unverified": complete["pending"],
        "dxf_path": str(saved), "dxf_sha256": _sha(saved), "roi_xyxy": ROI, "dpi": 200,
        "attachment_declarations": declarations,
        "wall_seconds": time.perf_counter() - started, "new_ocr_calls": 0, "new_model_calls": 0,
        "producer_decision_is_not_independent_acceptance": True,
    }
    _json(args.out / "PRODUCER_EXECUTION.json", record)
    print(json.dumps({"source": str(args.source), "produced_target_count": len(complete["objects"]),
                      "wall_seconds": record["wall_seconds"]}), flush=True)


def _read_and_audit(args):
    import numpy as np
    from PIL import Image

    reader = _load_module(args.saved_reader, "issue60_pinned_saved_reader")
    audit = _load_module(args.raw_auditor, "issue60_pinned_raw_auditor")
    execution = json.loads((args.out / "PRODUCER_EXECUTION.json").read_text())
    started = time.perf_counter()
    geometries = reader.saved_source_geometries(execution["dxf_path"], execution["roi_xyxy"], execution["dpi"])
    geometries["target_object_ids"] = execution["produced_target_object_ids"]
    geometries["attachment_declarations"] = execution["attachment_declarations"]
    geometries["independent_reader_sha256"] = _sha(args.saved_reader)
    geometries["external_transform_contract"] = {
        "roi_xyxy": [0, 0, 400, 280], "dpi": 200, "rotation": 0, "units": "paper_mm",
        "origin": "predeclared_synthetic_fixture_coordinate_system",
    }
    assert geometries["roi_xyxy"] == [0, 0, 400, 280] and geometries["dpi"] == 200
    _json(args.out / "ACTUAL_SAVED_GEOMETRIES.json", geometries)
    gray = np.asarray(Image.open(args.source).convert("L"))
    report = audit.audit_raw_source_responsibility(
        gray, geometries["geometries"], roi_xyxy=geometries["roi_xyxy"],
        attachment_declarations=geometries["attachment_declarations"],
        target_object_ids=geometries["target_object_ids"],
        source_identity={"source_file_sha256": _sha(args.source),
                         "actual_saved_dxf_sha256": geometries["dxf_sha256"]},
    )
    report["execution"] = {"raw_auditor_sha256": _sha(args.raw_auditor),
                           "saved_reader_sha256": _sha(args.saved_reader),
                           "fresh_process_after_producer_exit": True,
                           "wall_seconds": time.perf_counter() - started,
                           "new_ocr_calls": 0, "new_model_calls": 0}
    report["probe_scope"] = ("PRODUCED_LOCAL_SAVED_TARGETS" if geometries["target_object_ids"]
                             else "NO_PRODUCED_TARGET_GEOMETRY_NOT_AN_ACCEPTANCE_PASS")
    _json(args.out / "RAW_ACTUAL_SAVED_AUDIT.json", report)
    print(json.dumps({"out": str(args.out), "scope": report["probe_scope"], "summary": report["summary"]}))


def _counterfactual(args):
    import numpy as np
    from PIL import Image

    audit = _load_module(args.raw_auditor, "issue60_pinned_raw_auditor")
    baseline_path = args.out.parent / "baseline" / "ACTUAL_SAVED_GEOMETRIES.json"
    baseline = json.loads(baseline_path.read_text())
    gray = np.asarray(Image.open(args.source).convert("L"))
    report = audit.audit_raw_source_responsibility(
        gray, baseline["geometries"], roi_xyxy=baseline["roi_xyxy"],
        target_object_ids=baseline["target_object_ids"],
        attachment_declarations=baseline["attachment_declarations"],
        source_identity={"source_file_sha256": _sha(args.source),
                         "counterfactual_baseline_actual_dxf_sha256": baseline["dxf_sha256"]},
    )
    report["probe_scope"] = "COUNTERFACTUAL_BASELINE_SAVED_GEOMETRY_ON_VARIANT_SOURCE_NOT_VARIANT_ADOPTION"
    report["execution"] = {"raw_auditor_sha256": _sha(args.raw_auditor),
                           "baseline_saved_geometry_json_sha256": _sha(baseline_path),
                           "source_pixels_recomputed_from_this_variant": True,
                           "new_ocr_calls": 0, "new_model_calls": 0}
    _json(args.out / "RAW_BASELINE_GEOMETRY_COUNTERFACTUAL.json", report)


def _run_all(args):
    if args.out.exists():
        raise FileExistsError("New probe output directory required")
    args.out.mkdir(parents=True)
    declared_path = args.probe_root / "FROZEN_VARIANTS.json"
    declared = json.loads(declared_path.read_text())
    pinned = args.out / "pinned_auditors"
    pinned.mkdir()
    reader_copy = pinned / "independent_saved_geometry_audit.py"
    raw_copy = pinned / "raw_source_responsibility_audit.py"
    reader_copy.write_bytes(args.saved_reader.read_bytes())
    raw_copy.write_bytes(args.raw_auditor.read_bytes())
    paths = [args.producer_repo / name for name in declared["source_files_sha256"]]
    freeze = {"schema": "issue60-fresh-eight-source-probes-v1",
              "declared_variants_sha256": _sha(declared_path),
              "variants": declared["variants"],
              "input_source_sha256": {row["name"]: _sha(args.probe_root / row["name"] / "source.png")
                                      for row in declared["variants"]},
              "producer_source_sha256": {str(path.relative_to(args.producer_repo)): _sha(path) for path in paths},
              "expected_historical_producer_source_sha256": declared["source_files_sha256"],
              "raw_auditor_sha256": _sha(raw_copy), "saved_reader_sha256": _sha(reader_copy),
              "runner_sha256": _sha(__file__), "no_producer_PASS_used_as_raw_truth": True,
              "new_ocr_calls": 0, "new_model_calls": 0}
    if freeze["producer_source_sha256"] != declared["source_files_sha256"]:
        raise ValueError("PRODUCER_DIFFERS_FROM_PREDECLARED_FIXED_A_FILES")
    _json(args.out / "RUN_FREEZE.json", freeze)
    results = []
    for row in declared["variants"]:
        output = args.out / row["name"]
        output.mkdir()
        source = args.probe_root / row["name"] / "source.png"
        for mode in ("produce", "read_and_audit", "counterfactual"):
            command = [sys.executable, str(Path(__file__).resolve()), "--mode", mode,
                       "--producer-repo", str(args.producer_repo), "--source", str(source),
                       "--saved-reader", str(reader_copy), "--raw-auditor", str(raw_copy),
                       "--out", str(output)]
            completed = subprocess.run(command, check=False, text=True, capture_output=True, env=os.environ.copy())
            (output / (mode + ".log")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(f"{row['name']}/{mode} failed; preserved log at {output}")
        produced = json.loads((output / "PRODUCER_EXECUTION.json").read_text())
        actual = json.loads((output / "RAW_ACTUAL_SAVED_AUDIT.json").read_text())
        counterfactual = json.loads((output / "RAW_BASELINE_GEOMETRY_COUNTERFACTUAL.json").read_text())
        graph = json.loads((output / "fresh_graph.json").read_text())
        if not results:
            baseline_skeleton = graph["skeleton_points_px"]
            baseline_saved = json.loads((output / "ACTUAL_SAVED_GEOMETRIES.json").read_text())
        saved = json.loads((output / "ACTUAL_SAVED_GEOMETRIES.json").read_text())
        base_geometry = {g["object_id"]: {k: g.get(k) for k in ("kind", "points", "bulges", "closed")}
                         for g in baseline_saved["geometries"] if g["object_id"] in baseline_saved["target_object_ids"]}
        own_geometry = {g["object_id"]: {k: g.get(k) for k in ("kind", "points", "bulges", "closed")}
                        for g in saved["geometries"] if g["object_id"] in saved["target_object_ids"]}
        compact = {"name": row["name"], "role": row["role"],
                   "source_file_sha256": _sha(source), "produced_target_count": produced["produced_target_count"],
                   "skeleton_identical_to_baseline": graph["skeleton_points_px"] == baseline_skeleton,
                   "actual_target_geometry_identical_to_baseline": own_geometry == base_geometry,
                   "actual_saved_scope": actual["probe_scope"], "actual_saved_raw_summary": actual["summary"],
                   "counterfactual_scope": counterfactual["probe_scope"],
                   "counterfactual_raw_summary": counterfactual["summary"],
                   "producer_wall_seconds": produced["wall_seconds"]}
        results.append(compact)
        print(json.dumps(compact), flush=True)
    _json(args.out / "SUMMARY.json", {"results": results, "planned_variant_count": len(declared["variants"]),
                                      "all_variants_completed": True, "new_ocr_calls": 0, "new_model_calls": 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["all", "produce", "read_and_audit", "counterfactual"], default="all")
    parser.add_argument("--producer-repo", type=Path, required=True)
    parser.add_argument("--probe-root", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--saved-reader", type=Path, required=True)
    parser.add_argument("--raw-auditor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"all": _run_all, "produce": _produce, "read_and_audit": _read_and_audit,
     "counterfactual": _counterfactual}[args.mode](args)


if __name__ == "__main__":
    main()
