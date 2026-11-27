"""Replay the eight declared synthetic attachment probes through current code.

Example: python experiments/issue59_attached_ink/run_probes.py --output NEW_DIR

The public test fixtures require the repository's test dependencies. Every case
builds its own source graph and actually adopts its owner. Rejected candidate
receipts remain inspectable; zero adoption is not a substitute for a positive
control. No private input, B candidate generator, OCR or model is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

SCHEMA = "issue59-synthetic-attached-ink-probes-v1"
SCRIPT_VERSION = "fresh-owner-ledger-and-strict-replay-v2"
BASELINE_ARRAY_SHA256 = "087af325fd4c81b802efa4002eb121791405b78b02ed7a9ec05db4d91bac6a57"
EXPECTED_PLAN_SCHEMA = "source-attached-stroke-graph-plan-v2"
DEFAULT_REPO = Path(__file__).resolve().parents[2]


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, set):
        return [plain(item) for item in sorted(value, key=repr)]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    return value


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_sha(array):
    return hashlib.sha256(array.tobytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(plain(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def variants():
    """Exact original coordinator constructions, fixed before any new plan."""
    return [
        {"name": "baseline", "pixels": [], "role": "UNCHANGED_POSITIVE_CONTROL",
         "expectation": "FOUR_OBJECT_POSITIVE_CONTROL_WITH_THREE_PROVED_ATTACHMENTS"},
        {"name": "one_pixel_cap", "pixels": [(126, 127)],
         "role": "RAW_CAP_OR_SHORT_TAIL_COMPETITION", "expectation": "NEW_LEDGER_AND_EXPLICIT_MODEL_DECISION"},
        {"name": "three_pixel_cap_row", "pixels": [(x, 127) for x in range(125, 128)],
         "role": "RAW_CAP_OR_SHORT_TAIL_COMPETITION", "expectation": "NEW_LEDGER_AND_EXPLICIT_MODEL_DECISION"},
        {"name": "six_pixel_wedge", "pixels": [(x, 127) for x in range(125, 129)] + [(125, 128), (126, 128)],
         "role": "RAW_CAP_OR_SHORT_TAIL_COMPETITION", "expectation": "PENDING_WITH_RAW_RESIDUAL_OR_BOUNDARY_COMPETITION"},
        {"name": "six_pixel_block", "pixels": [(x, y) for y in (127, 128) for x in range(125, 128)],
         "role": "RAW_CAP_OR_SHORT_TAIL_COMPETITION", "expectation": "PENDING_WITH_RAW_RESIDUAL_OR_BOUNDARY_COMPETITION"},
        {"name": "three_pixel_thin_tail", "pixels": [(126, y) for y in range(127, 130)],
         "role": "SMALL_VISIBLE_ARM_CONTROL", "expectation": "INDEPENDENT_GRAPH_ARM_REFUSAL"},
        {"name": "fifteen_pixel_stub", "pixels": [(x, y) for y in range(127, 130) for x in range(124, 129)],
         "role": "BOUNDED_WIDE_STUB_CONTROL", "expectation": "PENDING_WITH_RAW_RESIDUAL_OR_BOUNDARY_COMPETITION"},
        {"name": "existing_long_tail_control", "pixels": [], "fixture_variant": "continues_below_attachment",
         "role": "EXISTING_CLEAR_FOURTH_ARM_CONTROL", "expectation": "INDEPENDENT_GRAPH_ARM_REFUSAL"},
    ]


def configure(repo, output):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo / "cad_photo_to_dxf"))
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", ORT_DISABLE_TELEMETRY="1",
                      OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1",
                      MKL_NUM_THREADS="1", XDG_CACHE_HOME=str(output / "runtime-cache"),
                      MPLCONFIGDIR=str(output / "matplotlib"))


def source_hashes(repo):
    files = list((repo / "cad_photo_to_dxf/app").rglob("*.py"))
    files += [repo / "cad_photo_to_dxf/tests/test_attached_stroke_graph.py",
              repo / "cad_photo_to_dxf/tests/test_native_transverse_stroke_geometry.py",
              repo / "docs/native/ATTACHED_INK_CONTRACT_20261127.md", Path(__file__).resolve()]
    return {(str(path.relative_to(repo)) if path.is_relative_to(repo) else "validation_entry/run_probes.py"):
            file_sha(path) for path in sorted(files)}


def git_identity(repo):
    def read(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=repo, text=True).strip()
    return {"head": read("rev-parse", "HEAD"), "head_tree": read("rev-parse", "HEAD^{tree}"),
            "worktree_dirty": bool(read("status", "--porcelain")),
            "uncommitted_execution_is_bound_by_exact_source_file_hashes": True}


def graph_snapshot(context):
    import numpy as np

    graph = context.graph
    yy, xx = np.nonzero(graph.skel)
    skeleton = np.column_stack((xx, yy)) + graph.origin.astype(int)
    nodes = []
    for node_id, node in sorted(graph.nodes.items()):
        nodes.append({"node_id": node_id, "source_pixel_centers_px": graph.xy(node["pixels"]),
                      "ports": sorted(node["edges"]), "terminal": node.get("terminal"),
                      "pairing": node.get("pairing"), "core_topology": node.get("core_topology"),
                      "internal_source_endpoint_count": node.get("internal_source_endpoint_count")})
    edges = [{"edge_id": edge_id, "nodes": edge["nodes"], "length_px": edge["length"],
              "ordered_source_pixel_centers_px": graph.xy(edge["pixels"])}
             for edge_id, edge in enumerate(graph.edges)]
    return plain({"schema": "issue59-fresh-synthetic-source-graph-v1", "roi": list(graph.roi),
                  "crop_bbox": context.crop_bbox, "crop_array_sha256": context.source_crop_hash,
                  "skeleton_sha256": array_sha(graph.skel), "skeleton_points_px": skeleton,
                  "nodes": nodes, "edges": edges})


def all_candidates(plan):
    found = {}
    for component in plan.get("components", []):
        for row in component.get("candidate_paths", []):
            found[row["stroke_id"]] = row
    for row in plan.get("paths", []):
        found[row["stroke_id"]] = row
    return list(found.values())


def summarize_receipt(guest, endpoint, gray, added):
    """Independently check the saved ledger against its original pixel patch."""
    import numpy as np

    proof = endpoint.get("attached_raw_ink_responsibility")
    summary = {"guest_id": guest["stroke_id"], "host_id": endpoint.get("host_path_id"),
               "source_node_id": endpoint["node_id"], "receipt_present": isinstance(proof, dict)}
    if not isinstance(proof, dict):
        return {**summary, "ledger_integrity_pass": False, "error": "RAW_ATTACHMENT_RECEIPT_MISSING"}
    summary.update(schema=proof.get("schema"), policy_version=proof.get("policy", {}).get("version"),
                   producer_sha256=proof.get("producer_sha256"), receipt_sha256=digest(proof),
                   status=proof.get("status"), passed=proof.get("pass"),
                   failure_reasons=proof.get("failure_reasons", []),
                   observation_closed=proof.get("observation_closed"),
                   observation_expansions=proof.get("observation_expansions", []),
                   unexplained_original_cells=proof.get("unexplained_original_cells", []))
    widths = proof.get("independent_width_evidence", {})
    summary["independent_widths"] = {
        role: {**{key: row.get(key) for key in ("pass", "half_width_interval_px", "reason")},
               "section_count": len(row.get("sections", [])),
               "valid_section_count": sum(section.get("pass", False) for section in row.get("sections", []))}
        for role, row in widths.items()}
    models = proof.get("coherent_terminal_models") or {}
    competition = proof.get("short_continuation_competition") or {}
    summary["model_receipt_summary"] = {
        "terminal_pass": models.get("pass"), "feasible_models": models.get("feasible_models", []),
        "rejected_models": models.get("rejected_models", []), "resource_truncated": models.get("resource_truncated"),
        "continuation_events": competition.get("events", []),
        "continuation_status": competition.get("status"),
        "continuation_search_complete": competition.get("search_complete"),
        "distinct_observable_boundary_exists": competition.get("distinct_observable_boundary_exists"),
        "continuation_resource_truncated": competition.get("resource_truncated"),
        "junction_normalization": proof.get("junction_normalization")}
    patch = proof.get("original_patch")
    ledger = proof.get("pixel_ledger")
    if not isinstance(patch, dict) or not isinstance(ledger, list):
        return {**summary, "ledger_integrity_pass": False, "error": "ORIGINAL_PATCH_OR_PIXEL_LEDGER_MISSING"}
    left, top, right, bottom = map(int, patch["raw_box_xyxy_px"])
    actual = gray[top:bottom, left:right]
    yy, xx = np.nonzero(actual < 128)
    expected_cells = set(zip((xx + left).tolist(), (yy + top).tolist()))
    by_cell = {tuple(row["source_cell"]): row for row in ledger}
    cells = set(by_cell)
    tests = {"raw_gray_values_match_source": np.array_equal(actual, np.asarray(patch["raw_gray_values"])),
             "raw_mask_matches_source": np.array_equal(actual < 128, np.asarray(patch["raw_ink_mask"], bool)),
             "ledger_is_exact_black_cell_set": cells == expected_cells,
             "ledger_contains_no_duplicate_cells": len(cells) == len(ledger),
             "ledger_gray_values_match_source": all(int(gray[y, x]) == row["original_gray_value"]
                                                      for (x, y), row in by_cell.items()),
             "ledger_responsibilities_are_explicit": all(bool(row.get("compatible_responsibilities")) for row in ledger)}
    contained = [cell for cell in added if left <= cell[0] < right and top <= cell[1] < bottom]
    matches = [by_cell[tuple(cell)] for cell in added if tuple(cell) in by_cell]
    tests["all_added_cells_in_patch_appear_in_ledger"] = all(tuple(cell) in cells for cell in contained)
    summary.update(raw_box_xyxy_px=[left, top, right, bottom], pixel_ledger_count=len(ledger),
                   ledger_checks=tests, ledger_integrity_pass=all(tests.values()),
                   added_pixels_in_patch=contained, added_pixel_ledger_rows=matches,
                   added_pixels_missing_from_ledger=[cell for cell in added if tuple(cell) not in cells],
                   all_added_pixels_in_this_ledger=all(tuple(cell) in cells for cell in added))
    return summary


def responsibility_summary(plan, gray, added):
    import numpy as np

    candidates = all_candidates(plan)
    receipts = [summarize_receipt(row, end, gray, added) for row in candidates
                for end in row.get("endpoint_evidence", []) if "host_path_index" in end]
    # This is the same public synthetic locator used by the original probes.
    middle = [row for row in candidates if any(np.linalg.norm(np.asarray(p) - [134, 50]) < 3
                                               for p in row["native_endpoint_points_px"])]
    middle_ids = {row["stroke_id"] for row in middle}
    target = [row for row in receipts if row["guest_id"] in middle_ids]
    return {"candidate_path_count": len(candidates), "endpoint_receipt_count": len(receipts),
            "endpoint_receipts": receipts, "middle_candidate_count": len(middle),
            "middle_receipts": target,
            "all_available_ledgers_integrity_pass": bool(receipts) and all(r["ledger_integrity_pass"] for r in receipts),
            "all_added_pixels_in_middle_ledger": (all(r.get("all_added_pixels_in_this_ledger", False) for r in target)
                                                   if target else None),
            "attachment_responsibility_checks": [c.get("attachment_responsibility_checks", []) for c in plan.get("components", [])],
            "prior_native_contact_checks": [c.get("prior_native_contact_check") for c in plan.get("components", [])],
            "component_failed_adoption_gates": [c.get("failed_adoption_gates", []) for c in plan.get("components", [])]}


def implementation_identity(attached, plan=None):
    return {"plan_schema": attached.SCHEMA, "policy_version": attached.POLICY["version"],
            "attached_stroke_graph_producer_sha256": file_sha(attached.__file__),
            "saved_plan_producer_sha256": None if plan is None else plan.get("producer_sha256"),
            "additional_producer_sha256": None if plan is None else plan.get("additional_producer_sha256")}


def strict_replay(repo, case):
    """A fresh process cold-reads source/plan and lets the strict gate rebuild."""
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from PIL import Image

    cv2.setNumThreads(1)
    identity = json.loads((case / "input_identity.json").read_text())
    plan_path, source_path = case / "attached/plan.json", case / "source.png"
    plan = json.loads(plan_path.read_text())
    with Image.open(source_path) as image:
        gray = np.asarray(image.convert("L"))
    before = source_hashes(repo)
    source_bound = array_sha(gray) == identity["source_array_sha256"]
    verification = attached.verify_attached_stroke_graph_plan(gray, identity["roi"], plan, source_graph=None)
    after = source_hashes(repo)
    report = {"schema": "issue59-fresh-process-strict-replay-v1", "source_array_matches": source_bound,
              "source_png_sha256": file_sha(source_path), "plan_file_sha256": file_sha(plan_path),
              "fresh_process": True, "fresh_source_graph_requested": True,
              "source_files_unchanged": before == after, "source_files_sha256": before,
              "implementation": implementation_identity(attached, plan), "verification": verification,
              "pass": source_bound and before == after and bool(verification.get("pass")),
              "new_OCR_calls": 0, "numeric_replay_tolerance_added": False}
    write_json(case / "strict_replay.json", report)
    return 0 if report["pass"] else 1


def expectation(variant, row, responsibility):
    kind = variant["expectation"]
    proofs = responsibility.get("endpoint_receipts", [])
    added_in_ledger = responsibility.get("all_added_pixels_in_middle_ledger")
    raw_pending = any("PENDING_UNEXPLAINED_INK" in p.get("failure_reasons", []) or
                      "PENDING_BOUNDARY_COMPETITION" in p.get("failure_reasons", []) for p in proofs)
    if kind == "FOUR_OBJECT_POSITIVE_CONTROL_WITH_THREE_PROVED_ATTACHMENTS":
        passed = row.get("adopted_count") == 4 and len(proofs) == 3 and all(p.get("passed") for p in proofs)
    elif kind == "PENDING_WITH_RAW_RESIDUAL_OR_BOUNDARY_COMPETITION":
        passed = row.get("adopted_count") == 0 and added_in_ledger is True and raw_pending
    elif kind == "INDEPENDENT_GRAPH_ARM_REFUSAL":
        passed = row.get("adopted_count") == 0 and bool(row.get("pending")) and not row.get("skeleton_identical_to_baseline")
    else:
        passed = added_in_ledger is True and bool(proofs) and all(p.get("status") for p in proofs)
        if row.get("adopted_count", 0):
            passed = passed and all(p.get("passed") for p in proofs)
    return {"expected": kind, "satisfied": bool(passed), "zero_adoption_is_not_a_positive_control": True}


def run_suite(args):
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects.text_contact_adoption import complete_text_contact_paths
    from PIL import Image
    from tests.test_attached_stroke_graph import _source
    from tests.test_native_transverse_stroke_geometry import ROI, _structure_stage

    cv2.setNumThreads(1)
    declared, before, baseline = variants(), source_hashes(args.repo), _source()
    prepared = []
    for variant in declared:
        gray = _source(variant=variant["fixture_variant"]) if "fixture_variant" in variant else baseline.copy()
        for x, y in variant["pixels"]:
            gray[y, x] = 0
        prepared.append((variant, gray))
    frozen = {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "variants": declared,
              "baseline_array_sha256": array_sha(baseline), "original_baseline_array_sha256": BASELINE_ARRAY_SHA256,
              "variant_array_sha256": {v["name"]: array_sha(g) for v, g in prepared},
              "source_files_sha256": before, "source_git": git_identity(args.repo),
              "implementation": implementation_identity(attached),
              "all_source_graphs_and_formal_owners_rebuilt": True, "strict_replay_in_fresh_process": True,
              "synthetic_coordinates_are_evaluation_only": True, "known_development_inputs_not_holdout": True,
              "private_inputs_used": False, "B_generator_imported": False, "new_OCR_calls": 0}
    write_json(args.output / "FROZEN_VARIANTS.json", frozen)
    if array_sha(baseline) != BASELINE_ARRAY_SHA256 or attached.SCHEMA != EXPECTED_PLAN_SCHEMA:
        raise ValueError("ORIGINAL_SYNTHETIC_FIXTURE_OR_NEW_PLAN_SCHEMA_MISMATCH")
    summaries, baseline_graph, baseline_geometry, baseline_receipts = [], None, None, None
    for index, (variant, gray) in enumerate(prepared):
        started = time.perf_counter()
        case = args.output / variant["name"]
        case.mkdir()
        add_y, add_x = np.nonzero((gray < 128) & (baseline >= 128))
        remove_y, remove_x = np.nonzero((gray >= 128) & (baseline < 128))
        added = np.column_stack((add_x, add_y)).tolist()
        removed = np.column_stack((remove_x, remove_y)).tolist()
        source_hash = array_sha(gray)
        Image.fromarray(gray).save(case / "source.png")
        write_json(case / "input_identity.json", {"name": variant["name"], "roi": ROI,
                   "source_array_sha256": source_hash, "source_png_sha256": file_sha(case / "source.png"),
                   "added_original_black_pixels_px": added, "removed_original_black_pixels_px": removed})
        row = {"name": variant["name"], "source_array_sha256": source_hash,
               "added_raw_pixels": len(added), "removed_raw_pixels": len(removed), "new_OCR_calls": 0}
        responsibility = {}
        try:
            context, initial, structure_plan = _structure_stage(gray)
            graph = graph_snapshot(context)
            write_json(case / "fresh_graph.json", graph)
            write_json(case / "structure_plan.json", structure_plan)
            left, top, right, bottom = context.crop_bbox
            row["fresh_graph_crop_matches_variant"] = context.source_crop_hash == array_sha(gray[top:bottom, left:right])
            skeleton = {tuple(p) for p in graph["skeleton_points_px"]}
            if index == 0:
                baseline_graph = skeleton
            row["skeleton_identical_to_baseline"] = skeleton == baseline_graph
            row["skeleton_added_samples_vs_baseline_px"] = sorted(skeleton - baseline_graph)
            row["skeleton_removed_samples_vs_baseline_px"] = sorted(baseline_graph - skeleton)
            targets = [p for p in structure_plan["paths"] if p["path_role"] == "ROUND_TO_CARRIER"]
            if len(targets) != 1:
                raise ValueError("UNIQUE_STRUCTURE_OWNER_PRECONDITION_NOT_ESTABLISHED")
            owner = complete_text_contact_paths(gray, ROI, source_hash, initial, [structure_plan], case / "owner")
            if owner.get("new_OCR_calls", 0) != 0:
                raise ValueError("UNEXPECTED_OCR_CALL_IN_GRAPH_OWNER_STAGE")
            if len(owner["objects"]) != 1 or owner["objects"][0]["kind"] != "CONNECTION_PATH":
                raise ValueError("ACTUAL_OWNER_ADOPTION_PRECONDITION_NOT_ESTABLISHED")
            prior = [obj for obj in initial if obj["id"] not in owner["retired_ids"]] + owner["objects"]
            prior_hash = digest(prior)
            write_json(case / "actual_prior_objects.json", prior)
            result = attached.complete_attached_strokes(gray, ROI, source_hash, prior, case / "attached", source_graph=context)
            if result.get("new_OCR_calls", 0) != 0:
                raise ValueError("UNEXPECTED_OCR_CALL_IN_ATTACHED_GRAPH_STAGE")
            plan = json.loads((case / "attached/plan.json").read_text())
            row.update(adopted_count=len(result["objects"]), pending=plan["pending"],
                       implementation=implementation_identity(attached, plan),
                       source_array_unchanged=source_hash == array_sha(gray), prior_objects_unchanged=prior_hash == digest(prior),
                       source_graph_unchanged=graph == graph_snapshot(context))
            responsibility = responsibility_summary(plan, gray, added)
            write_json(case / "responsibility_summary.json", responsibility)
            geometry = [p["representation"] for p in plan["paths"]]
            receipts = [p["receipt_sha256"] for p in responsibility["middle_receipts"] if p.get("receipt_sha256")]
            if index == 0:
                baseline_geometry, baseline_receipts = geometry, receipts
            row.update(native_geometry_identical_to_baseline=geometry == baseline_geometry,
                       middle_raw_receipt_identical_to_baseline=receipts == baseline_receipts,
                       all_added_pixels_in_middle_ledger=responsibility["all_added_pixels_in_middle_ledger"],
                       candidate_path_count=responsibility["candidate_path_count"],
                       endpoint_receipt_count=responsibility["endpoint_receipt_count"],
                       endpoint_status_counts=dict(Counter(p.get("status", "MISSING") for p in responsibility["endpoint_receipts"])),
                       ledger_integrity_pass=responsibility["all_available_ledgers_integrity_pass"] if responsibility["endpoint_receipts"] else None)
            with (case / "strict_replay.log").open("x", encoding="utf-8") as log:
                replay = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
                                         "--strict-replay-case", str(case)], stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.replay_timeout_seconds, check=False)
            row["strict_replay_exit_code"] = replay.returncode
            strict_path = case / "strict_replay.json"
            strict = json.loads(strict_path.read_text()) if strict_path.exists() else {}
            row["strict_source_bound_replay_pass"] = strict.get("pass", False)
            row["status"] = "ADOPTED_COMPONENT" if result["objects"] else "PENDING_NO_ADOPTION"
            row["expectation"] = expectation(variant, row, responsibility)
            row["evidence_integrity_pass"] = all(row.get(key) is True for key in (
                "fresh_graph_crop_matches_variant", "source_array_unchanged", "prior_objects_unchanged", "source_graph_unchanged")) and row["ledger_integrity_pass"] is not False
        except (AssertionError, AttributeError, KeyError, IndexError, TypeError, ValueError, RuntimeError, OSError) as exc:
            row.update(status="PROBE_EXECUTION_ERROR", evidence_integrity_pass=False,
                       expectation={"expected": variant["expectation"], "satisfied": False},
                       error={"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        row["wall_seconds"] = time.perf_counter() - started
        row["source_array_unchanged"] = source_hash == array_sha(gray)
        write_json(case / "result.json", row)
        compact = {key: row.get(key) for key in ("name", "status", "added_raw_pixels", "adopted_count", "candidate_path_count",
                   "skeleton_identical_to_baseline", "endpoint_receipt_count", "endpoint_status_counts", "ledger_integrity_pass",
                   "all_added_pixels_in_middle_ledger", "strict_source_bound_replay_pass", "evidence_integrity_pass",
                   "expectation", "wall_seconds", "error")}
        summaries.append(compact)
        print(json.dumps(plain(compact), ensure_ascii=False), flush=True)
        write_json(args.output / f"PROGRESS_{index + 1:02d}.json", {"results": summaries, "planned_variant_count": len(declared)})
    after = source_hashes(args.repo)
    summary = {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "run_completed": True,
               "planned_variant_count": len(declared), "results": summaries,
               "source_files_sha256_before": before, "source_files_sha256_after": after,
               "source_files_unchanged": before == after,
               "all_strict_replays_pass": all(row.get("strict_source_bound_replay_pass") is True for row in summaries),
               "all_input_and_graph_integrity_checks_pass": all(row.get("evidence_integrity_pass") is True for row in summaries),
               "all_predeclared_expectations_satisfied": all(row["expectation"]["satisfied"] for row in summaries),
               "all_available_ledger_checks_pass": all(row.get("ledger_integrity_pass") is not False for row in summaries),
               "new_OCR_calls": 0, "new_model_inferences": 0, "new_full_main_DXF": False,
               "physical_geometry_error_or_missed_true_tail_proved": False,
               "implementation": implementation_identity(attached), "script_sha256": file_sha(__file__)}
    summary["pass"] = (before == after and summary["all_strict_replays_pass"]
                       and summary["all_input_and_graph_integrity_checks_pass"]
                       and summary["all_predeclared_expectations_satisfied"] and summary["all_available_ledger_checks_pass"])
    write_json(args.output / "SUMMARY.json", summary)
    return 0 if summary["pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--strict-replay-case", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--replay-timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    if args.strict_replay_case is not None:
        case = args.strict_replay_case.resolve()
        configure(args.repo, case)
        try:
            return strict_replay(args.repo, case)
        except Exception as exc:
            report = case / "strict_replay.json"
            if not report.exists():
                write_json(report, {"schema": "issue59-fresh-process-strict-replay-v1", "pass": False,
                           "status": "STRICT_REPLAY_EXECUTION_ERROR", "type": type(exc).__name__,
                           "message": str(exc), "traceback": traceback.format_exc()})
            raise
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("Output must be a new directory; previous evidence is never overwritten.")
    if args.replay_timeout_seconds <= 0:
        parser.error("Replay timeout must be positive.")
    args.output.mkdir(parents=True)
    configure(args.repo, args.output)
    try:
        return run_suite(args)
    except Exception as exc:
        write_json(args.output / "PREPARATION_ERROR.json", {"status": "PROBE_PREPARATION_FAILED",
                   "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    sys.exit(main())
