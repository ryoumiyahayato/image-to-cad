"""Rebuild the original eight public sources under the bounded-source rule.

Each case creates a fresh graph and actually adopts its source-bound owner.
Actual adopted objects are exported and read in a separate process. Candidate
drawings are explicitly NOT_ADOPTED and use source-pixel units. These declared
development examples are not a holdout set or an ordinary whole-region result.

Example: python experiments/issue63_bounded_source/run_probes.py --output NEW_DIR
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

from run_source_stage import (
    append_native_object,
    bind_saved_sidecar,
    cold_edit_checks,
    cold_saved_sidecar,
    file_manifest,
    interface_status,
    memory_identity,
    model_receipts,
    read_saved_document,
    resource_snapshot,
    save_edits,
    snapshot_doc,
    snapshot_entrypoints,
    strict_preservation,
)
from run_source_stage import (
    configure as configure_runtime,
)

SCHEMA = "issue63-bounded-source-eight-original-probes-v1"
SCRIPT_VERSION = "fresh-source-shared-coordinate-saved-audit-v2-per-case-checkpoints"
EXPECTED_PLAN_SCHEMA = "source-attached-stroke-graph-plan-v4-bounded-source"
EXPECTED_COMPONENT_SCHEMA = "source-finite-component-responsibility-v2-bounded-field"
DEFAULT_REPO = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_HASHES = {
    "baseline": "087af325fd4c81b802efa4002eb121791405b78b02ed7a9ec05db4d91bac6a57",
    "one_pixel_cap": "41e74bab1647ad0057117d07cc5a31fa04387123b7f4bf23ec097e0c9412d896",
    "three_pixel_cap_row": "921abacb4073d438250fc91ad70d02dc16d490990e7975f20927f7598a8a6c71",
    "six_pixel_wedge": "9654d4870359f0b0356e75e0234c02359982f2444bdbc42d9a797330af9354fe",
    "six_pixel_block": "d9605c91dff833b129c80912a9abbfecc4bcf082aed72bd483c81b7d2671f423",
    "three_pixel_thin_tail": "950624705a8957c990c9b1d7d3005b91dd0698cf46449eab157cd673162a70ba",
    "fifteen_pixel_stub": "8dc96b38dcd0cf83b76e0f39f3bc06134f6a8f21f56b29dfac7e8ee0f7c7ae2e",
    "existing_long_tail_control": "4a1d23b02d611b366ce6b2a887fd88ffd7ed305a139da0ee52d6350d5991cb5d",
}
DPI = 200
EXPECTED_ADDITIONAL_PRODUCERS = (
    "attached_stroke_ink.py", "attached_stroke_component.py", "finite_component_source_audit.py",
    "finite_component_saved_reader.py", "circular_markers.py", "connections.py",
    "text_contact_geometry.py", "transverse_stroke_geometry.py", "bounded_source_component.py",
    "bounded_stroke_field_v2.py", "bounded_stroke_field.py", "finite_source_junction.py",
    "finite_source_ports.py", "finite_circle_source.py", "attached_stroke_width_exact.py",
    "attached_stroke_contacts.py",
)


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
    """Keep the original eight constructions and declared expectations intact."""
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
    configure_runtime(repo, output)


def source_hashes(repo):
    files = list((repo / "cad_photo_to_dxf/app").rglob("*.py"))
    files += [repo / "cad_photo_to_dxf/tests/test_attached_stroke_graph.py",
              repo / "cad_photo_to_dxf/tests/test_native_transverse_stroke_geometry.py",
              repo / "docs/native/ISSUE62_FINITE_COMPONENT_CONTRACT_20261127.md",
              repo / "docs/native/ISSUE62_EXACT_WIDTH_CONTRACT_20261127.md"]
    files += list((repo / "docs/native").glob("ISSUE63_*.md"))
    files += list(Path(__file__).resolve().parent.glob("*.py"))
    return {str(path.relative_to(repo)): file_sha(path) for path in sorted(set(files))}


def git_identity(repo):
    def read(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=repo, text=True).strip()
    return {"head": read("rev-parse", "HEAD"), "head_tree": read("rev-parse", "HEAD^{tree}"),
            "worktree_dirty": bool(read("status", "--porcelain")),
            "uncommitted_execution_is_bound_by_exact_source_file_hashes": True}


def select_prepared_variants(prepared, selected_case):
    """Verify all eight original arrays before selecting any execution scope."""
    names = [variant["name"] for variant, _ in prepared]
    actual = {variant["name"]: array_sha(gray) for variant, gray in prepared}
    if names != [row["name"] for row in variants()] or actual != EXPECTED_SOURCE_HASHES:
        raise ValueError("ALL_EIGHT_ORIGINAL_SOURCE_ARRAYS_MUST_MATCH_BEFORE_CASE_SELECTION")
    if selected_case is not None and selected_case not in EXPECTED_SOURCE_HASHES:
        raise ValueError("UNKNOWN_ORIGINAL_PROBE_CASE")
    return [(variant, gray) for variant, gray in prepared
            if selected_case is None or variant["name"] == selected_case]


def reference_inventory(directory):
    """Hash every reference byte, including manifests omitted by the root map."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("BASELINE_REFERENCE_MUST_BE_A_PLAIN_COMPLETED_DIRECTORY")
    paths = sorted(directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("BASELINE_REFERENCE_SYMLINKS_ARE_NOT_ACCEPTED")
    return {path.relative_to(directory).as_posix(): {
        "size_bytes": path.stat().st_size, "sha256": file_sha(path)}
        for path in paths if path.is_file()}


def validate_reference_manifests(directory, inventory):
    """The root map excludes named manifests; each case map includes its files."""
    manifests = [name for name in inventory if Path(name).name == "FILE_MANIFEST.json"]
    if "FILE_MANIFEST.json" not in manifests or "baseline/FILE_MANIFEST.json" not in manifests:
        raise ValueError("BASELINE_REFERENCE_COMPLETE_ROOT_AND_CASE_MANIFESTS_REQUIRED")
    for name in manifests:
        path = directory / name
        rows = json.loads(path.read_text(encoding="utf-8"))["files"]
        if isinstance(rows, list):
            recorded = {row["path"]: {key: row[key] for key in ("size_bytes", "sha256")} for row in rows}
            if len(recorded) != len(rows):
                raise ValueError("BASELINE_REFERENCE_DUPLICATE_MANIFEST_PATH")
        elif isinstance(rows, dict):
            recorded = rows
        else:
            raise ValueError("BASELINE_REFERENCE_INVALID_MANIFEST")
        prefix = path.parent.relative_to(directory)
        expected = {}
        for relative, identity in inventory.items():
            item = Path(relative)
            if not item.is_relative_to(prefix) or relative == name:
                continue
            if name == "FILE_MANIFEST.json" and item.name == "FILE_MANIFEST.json":
                continue
            expected[item.relative_to(prefix).as_posix()] = identity
        if recorded != expected:
            raise ValueError("BASELINE_REFERENCE_MANIFEST_FILE_SET_OR_BYTES_MISMATCH:" + name)
    return manifests


def load_baseline_reference(directory, repo, attached, source_files_now, source_git_now, baseline, roi):
    """Load comparison diagnostics only after a completed same-tree baseline gate.

    Nothing returned here is supplied to an owner, planner, source graph or
    adoption decision. The baseline is not an alternative source certificate.
    """
    import numpy as np
    from PIL import Image

    inventory = reference_inventory(directory)
    manifests = validate_reference_manifests(directory, inventory)

    def load(relative):
        return json.loads((directory / relative).read_text(encoding="utf-8"))

    frozen, summary, entry = (load(name) for name in ("FROZEN_VARIANTS.json", "SUMMARY.json", "EXECUTION_ENTRY.json"))
    result, strict, identity = (load("baseline/" + name) for name in ("result.json", "strict_replay.json", "input_identity.json"))
    plan = load("baseline/evidence/attached_strokes/plan.json")
    graph, responsibility = load("baseline/fresh_graph.json"), load("baseline/responsibility_summary.json")
    branches = load("baseline/FRESH_BRANCH_RESPONSIBILITY.json")
    saved = load("baseline/saved_files.json")
    input_hash_check = load("ORIGINAL_SOURCE_HASH_CHECK.json")
    expected_producers = {name: file_sha(repo / "cad_photo_to_dxf/app/native_objects" / name)
                          for name in EXPECTED_ADDITIONAL_PRODUCERS}
    expected_impl = implementation_identity(attached, plan)
    with Image.open(directory / "baseline/source.png") as image:
        saved_source = np.asarray(image.convert("L"))
    recomputed_responsibility = plain(responsibility_summary(plan, baseline, []))
    compact_results = summary.get("results", [])
    canonical_baseline = variants()[0]
    snapshots = entry.get("entries", [])
    expected_entrypoints = {name for name in source_files_now
                            if Path(name).parent == Path("experiments/issue63_bounded_source") and name.endswith(".py")}
    checks = {
        "same_current_clean_git_identity": source_git_now.get("worktree_dirty") is False
            and frozen.get("source_git") == entry.get("git") == source_git_now
            and summary.get("source_git_before") == summary.get("source_git_after") == source_git_now,
        "same_complete_source_file_hashes": bool(source_files_now)
            and frozen.get("source_files_sha256") == summary.get("source_files_sha256_before")
            == summary.get("source_files_sha256_after") == strict.get("source_files_sha256") == source_files_now,
        "same_script_version_and_schemas": frozen.get("schema") == summary.get("schema") == SCHEMA
            and frozen.get("script_version") == summary.get("script_version") == SCRIPT_VERSION
            and plan.get("schema") == EXPECTED_PLAN_SCHEMA,
        "all_eight_original_inputs_and_authored_variants_bound": frozen.get("variants") == plain(variants())
            and frozen.get("variant_array_sha256") == frozen.get("original_variant_array_sha256") == EXPECTED_SOURCE_HASHES
            and frozen.get("all_original_source_hashes_match") is True
            and input_hash_check.get("pass") is True
            and input_hash_check.get("all_original_sources_built_before_selection") is True
            and input_hash_check.get("original_variant_count") == len(EXPECTED_SOURCE_HASHES)
            and input_hash_check.get("actual_source_array_sha256") == input_hash_check.get("expected_source_array_sha256")
            == EXPECTED_SOURCE_HASHES,
        "single_baseline_execution_scope": frozen.get("execution_variants") == summary.get("execution_variants") == ["baseline"]
            and frozen.get("original_variant_count") == summary.get("original_variant_count") == len(EXPECTED_SOURCE_HASHES)
            and frozen.get("planned_variant_count") == summary.get("planned_variant_count") == 1
            and summary.get("execution_scope") == "SINGLE_ORIGINAL_CASE"
            and entry.get("arguments", {}).get("case") == "baseline"
            and entry.get("arguments", {}).get("baseline_reference") is None,
        "completed_successful_reference": summary.get("run_completed") is True and summary.get("pass") is True
            and summary.get("source_files_unchanged") is True and summary.get("source_git_unchanged") is True
            and summary.get("all_strict_source_and_saved_replays_pass") is True
            and summary.get("all_input_and_graph_integrity_checks_pass") is True
            and summary.get("all_current_control_gates_pass") is True,
        "one_complete_baseline_result": len(compact_results) == 1 and compact_results[0].get("name") == "baseline"
            and all(result.get(key) == value for key, value in compact_results[0].items())
            and result.get("name") == "baseline" and result.get("status") == "ADOPTED_COMPONENT"
            and result.get("adopted_count") == 4 and result.get("strict_replay_exit_code") == 0
            and result.get("strict_source_and_saved_replay_pass") is True and result.get("evidence_integrity_pass") is True,
        "complete_baseline_input_bytes": identity.get("name") == "baseline" and identity.get("roi") == list(roi)
            and identity.get("dpi") == DPI and identity.get("added_original_black_pixels_px") == []
            and identity.get("removed_original_black_pixels_px") == []
            and identity.get("source_png_sha256") == file_sha(directory / "baseline/source.png")
            and identity.get("source_array_sha256") == result.get("source_array_sha256") == EXPECTED_SOURCE_HASHES["baseline"]
            and array_sha(saved_source) == EXPECTED_SOURCE_HASHES["baseline"] and np.array_equal(saved_source, baseline),
        "current_exact_producer_maps": plan.get("producer_sha256") == file_sha(attached.__file__)
            and plan.get("additional_producer_sha256") == expected_producers
            and result.get("implementation") == strict.get("implementation") == expected_impl
            and frozen.get("implementation") == summary.get("implementation") == implementation_identity(attached)
            and summary.get("script_sha256") == file_sha(__file__),
        "strict_fresh_source_and_saved_acceptance": strict.get("pass") is True
            and strict.get("fresh_source_graph_requested") is True
            and bool(strict.get("checks")) and all(value is True for value in strict["checks"].values())
            and strict.get("plan_file_sha256") == file_sha(directory / "baseline/evidence/attached_strokes/plan.json")
            and strict.get("actual_saved_plan_fields") == strict.get("actually_compared_fields") == sorted(plan)
            and strict.get("verification", {}).get("pass") is True
            and set(strict.get("verification", {}).get("checks", {})) == set(plan)
            and all(value is True for value in strict["verification"]["checks"].values())
            and strict.get("saved_dxf", {}).get("pass") is True
            and strict.get("saved_dxf", {}).get("adopted_count") == 4
            and strict.get("saved_dxf", {}).get("actual_saved_source_audit", {}).get("acceptance_pass") is True,
        "four_objects_three_proved_attachments": responsibility == recomputed_responsibility
            and responsibility.get("endpoint_reference_count") == 3
            and len(plan.get("paths", [])) == saved.get("adopted_count") == 4
            and result.get("current_control_gate") == current_control_gate(canonical_baseline, result, responsibility, branches, strict)
            and result.get("current_control_gate", {}).get("pass") is True,
        "actual_saved_file_bytes_bound": saved.get("actual_adopted_dxf_sha256")
            == strict.get("saved_dxf", {}).get("actual_dxf_sha256") == file_sha(directory / "baseline/actual_adopted.dxf")
            and saved.get("prior_dxf_sha256") == file_sha(directory / "baseline/prior.dxf"),
        "entrypoint_snapshots_match_current_files": len(snapshots) == len(expected_entrypoints)
            and {row["source"] for row in snapshots} == expected_entrypoints and all(
            inventory.get(row["snapshot"], {}).get("sha256") == row["sha256"]
            == source_files_now.get(row["source"]) for row in snapshots),
        "baseline_source_graph_bound": graph.get("schema") == "issue63-fresh-synthetic-source-graph-v1"
            and graph.get("roi") == list(roi) and graph.get("crop_bbox") == plan.get("original_source_crop_xyxy_px")
            and graph.get("crop_array_sha256") == plan.get("original_source_crop_array_sha256"),
    }
    if not all(checks.values()):
        raise ValueError("BASELINE_REFERENCE_GATE_FAILED:" + json.dumps(checks, sort_keys=True))
    comparisons = {"graph": {tuple(point) for point in graph["skeleton_points_px"]}, "graph_record": graph,
        "geometry": [path["representation"] for path in all_candidates(plan)],
        "proofs": [component.get("proof_sha256") for component in responsibility["components"]]}
    receipt = {"schema": "issue63-completed-baseline-comparison-reference-v1", "directory": str(directory),
        "pass": True, "checks": checks, "files": inventory, "root_manifest_sha256": inventory["FILE_MANIFEST.json"]["sha256"],
        "validated_manifests": manifests, "source_git": source_git_now, "source_files_sha256": source_files_now,
        "original_baseline_source_array_sha256": EXPECTED_SOURCE_HASHES["baseline"],
        "comparison_only": True, "used_as_source_graph_owner_plan_or_adoption_input": False,
        "comparison_expressions": ["set(tuple(point) for point in fresh_graph['skeleton_points_px'])",
            "[path['representation'] for path in all_candidates(plan)]",
            "[component.get('proof_sha256') for component in responsibility['components']]"]}
    return comparisons, receipt


def graph_snapshot(context):
    import numpy as np

    graph = context.graph
    yy, xx = np.nonzero(graph.skel)
    nodes = [{"node_id": node_id, "source_pixel_centers_px": graph.xy(node["pixels"]),
              "ports": sorted(node["edges"]), "terminal": node.get("terminal"),
              "pairing": node.get("pairing"), "core_topology": node.get("core_topology"),
              "internal_source_endpoint_count": node.get("internal_source_endpoint_count")}
             for node_id, node in sorted(graph.nodes.items())]
    edges = [{"edge_id": edge_id, "nodes": edge["nodes"], "length_px": edge["length"],
              "ordered_source_pixel_centers_px": graph.xy(edge["pixels"])}
             for edge_id, edge in enumerate(graph.edges)]
    return plain({"schema": "issue63-fresh-synthetic-source-graph-v1", "roi": list(graph.roi),
                  "crop_bbox": context.crop_bbox, "crop_array_sha256": context.source_crop_hash,
                  "skeleton_sha256": array_sha(graph.skel),
                  "skeleton_points_px": np.column_stack((xx, yy)) + graph.origin.astype(int),
                  "nodes": nodes, "edges": edges})


def all_candidates(plan):
    found = {}
    for component in plan.get("components", []):
        for row in component.get("candidate_paths", []):
            found[row["stroke_id"]] = row
    for row in plan.get("paths", []):
        found[row["stroke_id"]] = row
    return list(found.values())


def _ledger_summary(proof, gray, added):
    """Check stored source values, not the producer's responsibility verdict."""
    import numpy as np

    patch = proof.get("original_patch")
    ledger = proof.get("pixel_ledger")
    if not isinstance(patch, dict) or not isinstance(ledger, list):
        return {"status": "SOURCE_LEDGER_NOT_PRESENT_AT_THIS_MODEL_STOP",
                "ledger_present": False, "integrity_pass": None,
                "all_added_pixels_in_ledger": None}
    box = patch.get("raw_box_xyxy_px")
    if not isinstance(box, list) or len(box) != 4:
        return {"status": "RAW_WINDOW_FIELD_MISSING", "ledger_present": True,
                "integrity_pass": False, "all_added_pixels_in_ledger": False}
    left, top, right, bottom = map(int, box)
    actual = gray[top:bottom, left:right]
    checks = {"box_within_source": 0 <= left < right <= gray.shape[1]
              and 0 <= top < bottom <= gray.shape[0]}
    if "raw_gray_values" in patch:
        checks["raw_gray_values_match"] = np.array_equal(actual, np.asarray(patch["raw_gray_values"]))
    if "raw_ink_mask" in patch:
        checks["raw_ink_mask_matches"] = np.array_equal(actual < 128, np.asarray(patch["raw_ink_mask"], bool))
    checks["raw_array_sha256_matches"] = array_sha(actual) == patch.get("raw_gray_array_sha256")
    yy, xx = np.nonzero(actual < 128)
    expected = set(zip((xx + left).tolist(), (yy + top).tolist()))
    by_cell = {tuple(row["source_cell"]): row for row in ledger}
    cells = set(by_cell)
    checks["no_duplicate_cells"] = len(by_cell) == len(ledger)
    checks["exact_original_black_cell_set"] = cells == expected
    checks["ledger_gray_values_match"] = all(
        0 <= y < gray.shape[0] and 0 <= x < gray.shape[1]
        and row.get("original_gray_value") == int(gray[y, x])
        for (x, y), row in by_cell.items())
    checks["black_responsibility_fields_explicit"] = all(
        isinstance(row.get("relevant_connected_ink"), bool)
        and isinstance(row.get("classification"), str)
        and bool(row["classification"])
        and isinstance(row.get("compatible_body_ids"), list)
        and isinstance(row.get("assignment_is_joint_model_proved"), bool)
        for row in ledger)
    white_ledger = proof.get("white_ledger")
    checks["white_ledger_present"] = isinstance(white_ledger, list)
    white_count = None
    if isinstance(white_ledger, list):
        yy, xx = np.nonzero(actual >= 128)
        expected_white = set(zip((xx + left).tolist(), (yy + top).tolist()))
        white_rows = {tuple(row["source_cell"]): row for row in white_ledger}
        white_cells, white_count = set(white_rows), len(white_ledger)
        checks["no_duplicate_white_cells"] = len(white_rows) == len(white_ledger)
        checks["exact_original_white_cell_set"] = white_cells == expected_white
        checks["white_gray_values_match"] = all(
            0 <= y < gray.shape[0] and 0 <= x < gray.shape[1]
            and row.get("original_gray_value") == int(gray[y, x])
            for (x, y), row in white_rows.items())
        checks["all_original_window_cells_recorded_once"] = (
            not cells.intersection(white_cells) and len(ledger) + len(white_ledger) == actual.size)
    contained = [cell for cell in added if left <= cell[0] < right and top <= cell[1] < bottom]
    checks["all_added_cells_inside_window_recorded"] = all(tuple(cell) in cells for cell in contained)
    return {"status": "SOURCE_LEDGER_CHECKED", "ledger_present": True, "raw_box_xyxy_px": box,
            "black_cell_count": len(ledger), "white_cell_count": white_count,
            "classification_counts": dict(Counter(row.get("classification") for row in ledger)),
            "checks": checks, "integrity_pass": all(checks.values()),
            "added_pixels_in_window": contained,
            "all_added_pixels_in_ledger": all(tuple(cell) in cells for cell in added),
            "added_pixel_rows": [by_cell[tuple(cell)] for cell in added if tuple(cell) in by_cell]}


def responsibility_summary(plan, gray, added):
    components = []
    for component in plan.get("components", []):
        candidates = component.get("candidate_paths", [])
        if not candidates:
            continue
        proof = component.get("finite_component_responsibility")
        row = {"component_id": component["component_id"], "candidate_count": len(candidates),
               "candidate_ids": [candidate["stroke_id"] for candidate in candidates],
               "component_status": component.get("status"),
               "failed_adoption_gates": component.get("failed_adoption_gates", []),
               "proof_present": isinstance(proof, dict)}
        if isinstance(proof, dict):
            row.update(schema=proof.get("schema"), schema_matches=proof.get("schema") == EXPECTED_COMPONENT_SCHEMA,
                       proof_sha256=digest(proof), status=proof.get("status"), passed=proof.get("pass"),
                       failure_reasons=proof.get("failure_reasons", []),
                       proof_fields=sorted(proof), source_ledger=_ledger_summary(proof, gray, added))
            row["body_widths"] = [{"body_id": body["stroke_id"], "body_role": body["body_role"],
                                   "independently_supported": body.get("independently_supported"),
                                   "chain_binding_pass": body.get("chain_binding", {}).get("pass"),
                                   "width": {key: body.get("width", {}).get(key) for key in (
                                       "pass", "reason", "independent_section_count", "half_width_squared_interval",
                                       "exact_interval_nonempty", "contributing_section_indices",
                                       "lower_bound_section_indices", "upper_bound_section_indices")},
                                   "section_outcome_counts": dict(Counter(section.get("reason") for section in
                                                                          body.get("width", {}).get("sections", []))),
                                   "constant_width_receipt": body.get("width"),
                                   "bounded_width_field": body.get("bounded_width_field")}
                                  for body in proof.get("bodies", [])]
            row["constant_width_diagnostic"] = proof.get("constant_width_diagnostic")
            model = proof.get("coherent_component_model", {})
            row["coherent_model"] = {key: model.get(key) for key in (
                "pass", "status", "search_complete", "resource_truncated", "half_width_squared_vector")}
            row["coherent_model"].update(black_witness_count=len(model.get("black_witnesses", [])),
                                         white_witness_count=len(model.get("white_witnesses", [])))
            row["observation_closed"] = proof.get("observation_closed")
            row["window_exit_classifications"] = dict(Counter(exit_row.get("classification") for exit_row in proof.get("window_exits", [])))
            row["source_direction_and_native_endpoints"] = proof.get("endpoints", [])
            competition = proof.get("short_continuation_competition", {})
            row["boundary_competition"] = {key: competition.get(key) for key in (
                "status", "search_complete", "distinct_observable_boundary_exists", "resource_truncated", "limitation")}
            row["boundary_competition"]["event_count"] = len(competition.get("events", []))
        row["endpoint_references"] = [{"stroke_id": candidate["stroke_id"],
                                       "endpoint_kind": endpoint.get("kind"),
                                       "node_id": endpoint.get("node_id"),
                                       "reference": endpoint.get("attached_raw_ink_responsibility")}
                                      for candidate in candidates
                                      for endpoint in candidate.get("endpoint_evidence", [])
                                      if "host_path_index" in endpoint]
        components.append(row)
    ledgers = [row["source_ledger"] for row in components if "source_ledger" in row]
    return {"candidate_path_count": len(all_candidates(plan)), "components": components,
            "component_proof_count": sum(row["proof_present"] for row in components),
            "endpoint_reference_count": sum(len(row["endpoint_references"]) for row in components),
            "all_present_ledgers_integrity_pass": all(row["integrity_pass"] is not False for row in ledgers),
            "all_added_pixels_in_a_component_ledger": any(
                row["all_added_pixels_in_ledger"] is True for row in ledgers) if added else True,
            "producer_status_is_not_independent_acceptance": True}


def implementation_identity(attached, plan=None):
    return {"plan_schema": attached.SCHEMA, "policy_version": attached.POLICY["version"],
            "attached_stroke_graph_producer_sha256": file_sha(attached.__file__),
            "saved_plan_producer_sha256": None if plan is None else plan.get("producer_sha256"),
            "additional_producer_sha256": None if plan is None else plan.get("additional_producer_sha256")}


def save_actual_dxf(case, prior, adopted, roi, source_hash, transform):
    from app.native_objects.cad_io import export_objects, save_native_dxf

    export_objects(prior, case / "prior.dxf", roi, DPI, source_hash)
    doc = read_saved_document(case / "prior.dxf")
    for obj in adopted:
        append_native_object(doc, obj, transform)
    path = case / "actual_adopted.dxf"
    serialization = save_native_dxf(doc, path)
    binding = bind_saved_sidecar(path, source_path=case / "source.png", source_array_sha256=source_hash,
        roi=roi, dpi=DPI, objects=prior + adopted, target_ids=[row["id"] for row in adopted],
        status="PRODUCER_ADOPTED_REQUIRES_INDEPENDENT_ACCEPTANCE", prior_source_bindings=prior,
        circle_source_objects=[], baseline_dxf=case / "prior.dxf", planner_source_sha256=source_hash,
        input_binding_files={"prior_objects": {"path": str((case / "actual_prior_objects.json").resolve()),
                                               "sha256": file_sha(case / "actual_prior_objects.json")}})
    edits = save_edits(path, case, [row["id"] for row in adopted], "SYNTHETIC_LOCAL_STAGE_ADOPTED_OBJECT")
    write_json(case / "saved_files.json", {"dpi": DPI, "prior_ids": [row["id"] for row in prior],
               "adopted_ids": [row["id"] for row in adopted], "adopted_count": len(adopted),
               "prior_dxf_sha256": file_sha(case / "prior.dxf"),
               "actual_adopted_dxf_sha256": file_sha(path), "sidecar": binding, "serialization": serialization,
               "edit_status": "SYNTHETIC_EDITS_SAVED" if edits else "NOT_APPLICABLE_NO_NEW_ADOPTED_OBJECTS",
               "edits": edits, "ordinary_whole_region_result": False, "gui": "NOT_RUN"})


def save_pending_candidates(case, plan, prior, roi, source_hash, transform):
    """Persist pending candidates and complete saved context; audit in the child."""
    import ezdxf
    from app.native_objects.cad_io import APPID, save_native_dxf
    from app.native_objects.text_contact_adoption import _native_object

    adopted = {row["stroke_id"] for row in plan["paths"]}
    rows = [row for row in all_candidates(plan) if row["stroke_id"] not in adopted]
    if not rows:
        report = {"status": "NO_PENDING_CANDIDATES", "count": 0, "target_ids": []}
        write_json(case / "NOT_ADOPTED_candidates.json", report)
        return report
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 0
    doc.appids.new(APPID)
    doc.layers.new("NOT_ADOPTED", dxfattribs={"color": 1})
    mapping, pixel_objects, proposals = [], [], []
    for row in rows:
        geometry = row["representation"]
        points, bulges = geometry["points"], geometry["bulges"]
        entity = doc.modelspace().add_lwpolyline(
            [(point[0], point[1], bulge) for point, bulge in zip(points, bulges)],
            format="xyb", close=bool(geometry["closed"]), dxfattribs={"layer": "NOT_ADOPTED"})
        entity.set_xdata(APPID, [(1000, json.dumps({"id": row["stroke_id"], "kind": "CONNECTION_PATH"}))])
        mapping.append({"stroke_id": row["stroke_id"], "entity_handle": entity.dxf.handle,
                        "status": "NOT_ADOPTED", "representation": geometry})
        pixel_objects.append({"id": row["stroke_id"], "kind": "CONNECTION_PATH", "geometry": geometry,
                              "layer": "NOT_ADOPTED", "status": "PIXEL_DIAGNOSTIC_ONLY"})
        kind, native = _native_object(geometry)
        proposals.append({"id": row["stroke_id"], "kind": kind, "layer": "NOT_ADOPTED", "geometry": native,
                          "status": "NOT_ADOPTED_DIAGNOSTIC_CANDIDATE",
                          "source_evidence": {"diagnostic_only": True, "source_pixels_modified": False,
                                              "source_path_points": row["source_path_px"]}})
    path = case / "NOT_ADOPTED_candidates_source_pixels.dxf"
    save_native_dxf(doc, path)
    pixel_binding = bind_saved_sidecar(path, source_path=case / "source.png", source_array_sha256=source_hash,
        roi=roi, dpi=DPI, objects=pixel_objects, target_ids=[obj["id"] for obj in proposals],
        status="PIXEL_DIAGNOSTIC_ONLY", prior_source_bindings=prior, planner_source_sha256=source_hash,
        coordinate_frame="UNCHANGED_SOURCE_PIXEL_COORDINATES_Y_DOWN")
    # Retain independently saved current adopted neighbors as context too; a
    # pending guest must not lose a new host merely because that host was adopted.
    context_baseline = case / "actual_adopted.dxf"
    current = json.loads(context_baseline.with_suffix(".objects.json").read_text(encoding="utf-8"))
    context_path = case / "NOT_ADOPTED_with_context.dxf"
    context_doc = read_saved_document(context_baseline)
    if "NOT_ADOPTED" not in context_doc.layers:
        context_doc.layers.new("NOT_ADOPTED", dxfattribs={"color": 1})
    for obj in proposals:
        append_native_object(context_doc, obj, transform)
    save_native_dxf(context_doc, context_path)
    context_binding = bind_saved_sidecar(context_path, source_path=case / "source.png", source_array_sha256=source_hash,
        roi=roi, dpi=DPI, objects=current["objects"] + proposals, target_ids=[obj["id"] for obj in proposals],
        status="NOT_ADOPTED_DIAGNOSTIC_ONLY", prior_source_bindings=current["objects"], circle_source_objects=[],
        baseline_dxf=context_baseline, allowed_added_layers=["NOT_ADOPTED"], planner_source_sha256=source_hash,
        input_binding_files={"prior_objects": {"path": str((case / "actual_prior_objects.json").resolve()),
                                               "sha256": file_sha(case / "actual_prior_objects.json")}})
    report = {"status": "NOT_ADOPTED_DIAGNOSTIC_ONLY", "count": len(rows), "sha256": file_sha(path),
              "file": path.name, "pixel_sidecar": pixel_binding, "candidate_geometry": mapping,
              "coordinate_frame": "UNCHANGED_SOURCE_PIXELS_Y_DOWN_NO_PAPER_MM_CLAIM",
              "paper_mm_context_file": context_path.name, "paper_mm_context_sha256": file_sha(context_path),
              "context_sidecar": context_binding, "cold_read_status": "WAITING_FOR_SEPARATE_PROCESS",
              "source_file": "source.png", "source_file_sha256": file_sha(case / "source.png"),
              "source_array_sha256": source_hash, "roi_xyxy_px": list(roi), "dpi": DPI,
              "prior_ids": [obj["id"] for obj in current["objects"]], "target_ids": [obj["id"] for obj in proposals],
              "adopted_ids": [], "new_adopted_object_count": 0,
              "proposal_sidecar_chains_are_not_independent_source_acceptance": True,
              "does_not_replace_formal_drawing": True}
    write_json(case / "NOT_ADOPTED_candidates.json", report)
    return {key: value for key, value in report.items() if key != "candidate_geometry"}


def cold_read_saved(case, gray, roi):
    import ezdxf

    files = json.loads((case / "saved_files.json").read_text(encoding="utf-8"))
    path = case / "actual_adopted.dxf"
    prior, actual = snapshot_doc(ezdxf.readfile(case / "prior.dxf")), snapshot_doc(ezdxf.readfile(path))
    bound = cold_saved_sidecar(path)
    checks = {"prior_file_sha256": file_sha(case / "prior.dxf") == files["prior_dxf_sha256"],
              "actual_file_sha256": file_sha(path) == files["actual_adopted_dxf_sha256"],
              "actual_sidecar_sha256": file_sha(path.with_suffix(".objects.json")) == files["sidecar"]["sha256"],
              "prior_saved_id_set_exact": set(prior["formal"]) == set(files["prior_ids"]),
              "all_actual_saved_bindings_valid": bound["pass"],
              "adopted_targets_independently_accepted": not files["adopted_ids"] or bound["acceptance_pass"]}
    prior_protection = strict_preservation(prior, actual, files["adopted_ids"])
    checks["all_prior_saved_tags_and_resources_protected"] = prior_protection["pass"]
    pending_record = json.loads((case / "NOT_ADOPTED_candidates.json").read_text(encoding="utf-8"))
    pending = {"status": "NOT_APPLICABLE_NO_PENDING_CANDIDATES", "pass": True}
    if pending_record["count"]:
        pixel = cold_saved_sidecar(case / pending_record["file"], run_source_audit=False)
        context = cold_saved_sidecar(case / pending_record["paper_mm_context_file"])
        sidecars_match = (file_sha(pending_record["pixel_sidecar"]["path"]) == pending_record["pixel_sidecar"]["sha256"]
                          and file_sha(pending_record["context_sidecar"]["path"]) == pending_record["context_sidecar"]["sha256"])
        pending = {"status": "PENDING_DRAWING_INDEPENDENTLY_REOPENED", "pixel_diagnostic": pixel,
                   "paper_context": context, "sidecars_match": sidecars_match,
                   "pass": pixel["pass"] and context["pass"] and sidecars_match,
                   "source_acceptance_pass": context["acceptance_pass"], "adoption_claimed": False}
    checks["pending_saved_drawings_and_context_independently_bound"] = pending["pass"]
    edits = cold_edit_checks(path, case, files["edits"])
    checks["all_saved_synthetic_edits_pass"] = all(edit["pass"] for edit in edits)
    return {"fresh_process": True, "pid": os.getpid(), "checks": checks, "pass": all(checks.values()),
            "actual_formal_entity_count": len(actual["formal"]), "adopted_count": files["adopted_count"],
            "actual_dxf_sha256": file_sha(path), "actual_saved_geometry_sha256": digest(actual),
            "actual_saved_source_audit": bound, "pending_saved_source_audit": pending,
            "source_audit_invocation_count": int(bound["independent_source_audit_completed"])
                + int(pending.get("paper_context", {}).get("independent_source_audit_completed", False)),
            "prior_strict_preservation": prior_protection, "edit_status": files["edit_status"], "edits": edits,
            "independent_physical_source_certificate": "ACTUAL_SAVED_PAPER_TARGETS_AUDITED_IN_V2"}


def strict_replay(repo, case):
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from PIL import Image

    cv2.setNumThreads(1)
    identity = json.loads((case / "input_identity.json").read_text(encoding="utf-8"))
    plan_path, source_path = case / "evidence/attached_strokes/plan.json", case / "source.png"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    with Image.open(source_path) as image:
        gray = np.asarray(image.convert("L"))
    before = source_hashes(repo)
    prior_path = case / "actual_prior_objects.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    prior_file_hash = file_sha(prior_path)
    memory_before = memory_identity(gray, prior, [])
    verification = attached.verify_attached_stroke_graph_plan(gray, identity["roi"], plan, source_graph=None)
    exact_checks = verification.get("checks", {})
    saved = cold_read_saved(case, gray, identity["roi"])
    after = source_hashes(repo)
    checks = {"source_array_matches": array_sha(gray) == identity["source_array_sha256"],
              "source_png_matches": file_sha(source_path) == identity["source_png_sha256"],
              "source_files_unchanged": before == after, "strict_source_replay_pass": verification.get("pass") is True,
              "all_saved_plan_fields_exactly_compared": bool(exact_checks) and set(exact_checks) == set(plan),
              "all_saved_plan_fields_equal": bool(exact_checks) and all(value is True for value in exact_checks.values()),
              "prior_binding_file_unchanged": prior_file_hash == file_sha(prior_path),
              "source_prior_and_circles_unchanged": memory_before == memory_identity(gray, prior, []),
              "actual_saved_cold_read_pass": saved["pass"]}
    report = {"schema": "issue63-fresh-process-source-and-saved-replay-v1", "checks": checks,
              "pass": all(checks.values()), "plan_file_sha256": file_sha(plan_path),
              "fresh_source_graph_requested": True, "implementation": implementation_identity(attached, plan),
              "verification": verification, "saved_dxf": saved, "source_files_sha256": before,
              "source_audit_invocation_count": saved["source_audit_invocation_count"],
              "producer_replay_invocation_count": 1,
              "verification_source": "fresh_verify_attached_stroke_graph_plan_plus_independent_saved_v2_source_audit",
              "actual_saved_plan_fields": sorted(plan), "actually_compared_fields": sorted(exact_checks),
              "input_memory_before": memory_before, "input_memory_after": memory_identity(gray, prior, []),
              "new_OCR_calls": 0, "numeric_replay_tolerance_added": False}
    write_json(case / "strict_replay.json", report)
    return 0 if report["pass"] else 1


def expectation(variant, row, responsibility):
    """Report old expectations honestly, including changed-model failures."""
    kind = variant["expectation"]
    components = responsibility.get("components", [])
    proofs = [proof for component in components for proof in component.get("endpoint_references", [])]
    added_recorded = responsibility.get("all_added_pixels_in_a_component_ledger") is True
    failures = [str(reason) for component in components for reason in component.get("failure_reasons", [])]
    raw_pending = any(any(marker in reason for marker in ("UNEXPLAINED", "COMPETITION", "COMPETITOR", "OBSERVATION"))
                      for reason in failures)
    if kind == "FOUR_OBJECT_POSITIVE_CONTROL_WITH_THREE_PROVED_ATTACHMENTS":
        passed = row.get("adopted_count") == 4 and len(proofs) == 3 and all(
            component.get("passed") is True for component in components)
    elif kind == "PENDING_WITH_RAW_RESIDUAL_OR_BOUNDARY_COMPETITION":
        passed = row.get("adopted_count") == 0 and added_recorded and raw_pending
    elif kind == "INDEPENDENT_GRAPH_ARM_REFUSAL":
        passed = row.get("adopted_count") == 0 and bool(row.get("pending")) and not row.get("skeleton_identical_to_baseline")
    else:
        passed = added_recorded and bool(components) and all(component.get("status") for component in components)
        if row.get("adopted_count", 0):
            passed = passed and all(component.get("passed") is True for component in components)
    return {"original_declared_expectation": kind, "satisfied": bool(passed),
            "role": "HISTORICAL_REGRESSION_COMPARISON_NOT_A_NEW_MODEL_ADOPTION_GATE",
            "zero_adoption_is_not_a_positive_control": True,
            "model_not_applicable_is_not_wrong_geometry_proof": True}


def branch_responsibility(graph, baseline_graph, added, plan):
    """Record actual added external arms and their saved-target ownership.

    An arm witness needs a new finite graph edge with original added source
    centers, a junction with at least four complete external ports, and a
    distinct free terminal. Names such as 'thin tail' are not that evidence.
    """
    added = {tuple(point) for point in added}
    nodes = {node["node_id"]: node for node in graph["nodes"]}

    def chain_key(edge):
        points = tuple(tuple(point) for point in edge["ordered_source_pixel_centers_px"])
        return min(points, tuple(reversed(points)))

    baseline_edges = {chain_key(edge) for edge in baseline_graph["edges"]}
    witnesses = []
    for edge in graph["edges"]:
        new_centers = sorted(added.intersection(tuple(point) for point in edge["ordered_source_pixel_centers_px"]))
        if not new_centers or chain_key(edge) in baseline_edges or len(set(edge["nodes"])) != 2:
            continue
        for junction_id, terminal_id in (edge["nodes"], list(reversed(edge["nodes"]))):
            junction, terminal = nodes[junction_id], nodes[terminal_id]
            if len(junction["ports"]) < 4 or len(terminal["ports"]) != 1:
                continue
            owners = [path["stroke_id"] for path in plan["paths"]
                      if edge["edge_id"] in path.get("source_graph_edge_ids", [])]
            witnesses.append({"edge_id": edge["edge_id"], "junction_node_id": junction_id,
                "junction_external_edge_ids": junction["ports"], "terminal_node_id": terminal_id,
                "terminal_external_edge_ids": terminal["ports"], "added_original_black_centers_on_arm": new_centers,
                "ordered_source_pixel_centers_px": edge["ordered_source_pixel_centers_px"],
                "saved_adopted_native_owner_ids": owners, "unique_saved_adopted_native_owner": len(owners) == 1})
    return {"schema": "issue63-fresh-external-branch-responsibility-v1", "arm_witnesses": witnesses,
            "witness_count": len(witnesses), "source_graph_is_the_fresh_input_graph": True,
            "actual_adopted_ids": [path["stroke_id"] for path in plan["paths"]],
            "all_witnessed_new_arms_have_unique_adopted_owner": bool(witnesses)
                and all(row["unique_saved_adopted_native_owner"] for row in witnesses),
            "producer_owner_mapping_requires_independent_saved_source_acceptance": True}


def current_control_gate(variant, row, responsibility, branches, strict):
    """Evaluate facts from this execution, keeping old labels as comparisons."""
    adopted = row.get("adopted_count", 0)
    explicit_pending = adopted == 0 and bool(row.get("pending"))
    actual_saved = strict.get("saved_dxf", {})
    independently_accepted = (adopted > 0 and actual_saved.get("actual_saved_source_audit", {}).get("acceptance_pass") is True)
    checks = {"actual_saved_source_and_replay_pass": strict.get("pass") is True,
              "every_witnessed_external_arm_retained_or_uniquely_adopted": branches["witness_count"] == 0
                or explicit_pending or (branches["all_witnessed_new_arms_have_unique_adopted_owner"] and independently_accepted)}
    if variant["expectation"] == "FOUR_OBJECT_POSITIVE_CONTROL_WITH_THREE_PROVED_ATTACHMENTS":
        checks["actual_four_object_three_attachment_positive_control"] = (
            adopted == 4 and responsibility.get("endpoint_reference_count") == 3 and independently_accepted)
    if variant["expectation"] == "INDEPENDENT_GRAPH_ARM_REFUSAL":
        checks["actual_new_independent_external_arm_witness_present"] = branches["witness_count"] > 0
    return {"schema": "issue63-actual-source-and-saved-control-gate-v1", "checks": checks, "pass": all(checks.values()),
            "historical_shape_label_is_not_an_adoption_decision": True,
            "zero_adoption_cannot_satisfy_positive_control": True,
            "unowned_fourth_arm_cannot_be_absorbed_by_width": True}


def case_files(case):
    return [{"path": path.relative_to(case).as_posix(), "size_bytes": path.stat().st_size,
             "sha256": file_sha(path)} for path in sorted(case.rglob("*")) if path.is_file()]


def run_suite(args):
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects.finite_source_junction import SharedCoordinateTransform
    from app.native_objects.text_contact_adoption import complete_text_contact_paths
    from PIL import Image
    from tests.test_attached_stroke_graph import _source
    from tests.test_native_transverse_stroke_geometry import ROI, _structure_stage

    cv2.setNumThreads(1)
    snapshot_entrypoints(args.repo, args.output, {key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()})
    readiness = interface_status()
    write_json(args.output / "INTERFACE_STATUS.json", readiness)
    if not readiness["ready"]:
        raise ValueError("V2_BOUND_SOURCE_INTERFACES_NOT_READY")
    declared, before, baseline = variants(), source_hashes(args.repo), _source()
    source_git_before = git_identity(args.repo)
    resources_before = resource_snapshot(args.output)
    prepared = []
    for variant in declared:
        gray = _source(variant=variant["fixture_variant"]) if "fixture_variant" in variant else baseline.copy()
        for x, y in variant["pixels"]:
            gray[y, x] = 0
        prepared.append((variant, gray))
    actual_hashes = {variant["name"]: array_sha(gray) for variant, gray in prepared}
    write_json(args.output / "ORIGINAL_SOURCE_HASH_CHECK.json", {
        "all_original_sources_built_before_selection": True, "original_variant_count": len(declared),
        "actual_source_array_sha256": actual_hashes, "expected_source_array_sha256": EXPECTED_SOURCE_HASHES,
        "pass": actual_hashes == EXPECTED_SOURCE_HASHES})
    execution = select_prepared_variants(prepared, args.case)
    execution_names = [variant["name"] for variant, _ in execution]
    execution_scope = "ALL_EIGHT_ORIGINAL_CASES" if args.case is None else "SINGLE_ORIGINAL_CASE"
    write_json(args.output / "FROZEN_VARIANTS.json", {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "variants": declared,
               "execution_variants": execution_names, "original_variant_count": len(declared),
               "planned_variant_count": len(execution), "execution_scope": execution_scope,
               "variant_array_sha256": actual_hashes, "original_variant_array_sha256": EXPECTED_SOURCE_HASHES,
               "all_original_source_hashes_match": actual_hashes == EXPECTED_SOURCE_HASHES,
               "source_files_sha256": before, "source_git": source_git_before,
               "implementation": implementation_identity(attached), "fresh_graph_and_owner_for_every_case": True,
               "saved_dxf_and_new_process_cold_read_for_every_case": True,
               "fresh_source_audits_per_case": "EACH_NONEMPTY_PAPER_TARGET_SET_RECORDED_PER_CASE",
               "producer_replays_per_case": 1,
               "development_controls_not_holdout": True, "private_inputs_used": False, "new_OCR_calls": 0})
    if actual_hashes != EXPECTED_SOURCE_HASHES or attached.SCHEMA != EXPECTED_PLAN_SCHEMA:
        raise ValueError("ORIGINAL_SYNTHETIC_SOURCES_OR_NEW_PLAN_SCHEMA_MISMATCH")
    summaries, baseline_graph, baseline_graph_record, baseline_geometry, baseline_proofs = [], None, None, None, None
    reference_before = None
    if args.baseline_reference is not None:
        comparisons, reference_before = load_baseline_reference(
            args.baseline_reference, args.repo, attached, before, source_git_before, baseline, ROI)
        write_json(args.output / "BASELINE_REFERENCE_BEFORE.json", reference_before)
        baseline_graph, baseline_graph_record = comparisons["graph"], comparisons["graph_record"]
        baseline_geometry, baseline_proofs = comparisons["geometry"], comparisons["proofs"]
    for index, (variant, gray) in enumerate(execution):
        started = time.perf_counter()
        case = args.output / variant["name"]
        case.mkdir()
        add_y, add_x = np.nonzero((gray < 128) & (baseline >= 128))
        remove_y, remove_x = np.nonzero((gray >= 128) & (baseline < 128))
        added, removed = np.column_stack((add_x, add_y)).tolist(), np.column_stack((remove_x, remove_y)).tolist()
        source_hash = array_sha(gray)
        Image.fromarray(gray).save(case / "source.png")
        write_json(case / "input_identity.json", {"name": variant["name"], "roi": ROI, "dpi": DPI,
                   "source_array_sha256": source_hash, "source_png_sha256": file_sha(case / "source.png"),
                   "added_original_black_pixels_px": added, "removed_original_black_pixels_px": removed})
        row = {"name": variant["name"], "source_array_sha256": source_hash,
               "added_raw_pixels": len(added), "removed_raw_pixels": len(removed), "new_OCR_calls": 0}
        responsibility = {}
        prior, circles, memory_before = None, [], None
        print(json.dumps({"case": variant["name"], "stage": "FRESH_GRAPH_AND_OWNER"}), flush=True)
        try:
            context, initial, structure_plan = _structure_stage(gray)
            graph = graph_snapshot(context)
            write_json(case / "fresh_graph.json", graph)
            write_json(case / "structure_plan.json", structure_plan)
            left, top, right, bottom = context.crop_bbox
            row["fresh_graph_crop_matches_variant"] = context.source_crop_hash == array_sha(gray[top:bottom, left:right])
            skeleton = {tuple(point) for point in graph["skeleton_points_px"]}
            if variant["name"] == "baseline":
                baseline_graph = skeleton
                baseline_graph_record = graph
            row["skeleton_identical_to_baseline"] = skeleton == baseline_graph
            row["skeleton_added_samples_vs_baseline_px"] = sorted(skeleton - baseline_graph)
            row["skeleton_removed_samples_vs_baseline_px"] = sorted(baseline_graph - skeleton)
            targets = [path for path in structure_plan["paths"] if path["path_role"] == "ROUND_TO_CARRIER"]
            if len(targets) != 1:
                raise ValueError("UNIQUE_STRUCTURE_OWNER_PRECONDITION_NOT_ESTABLISHED")
            owner = complete_text_contact_paths(gray, ROI, source_hash, initial, [structure_plan], case / "owner")
            if owner.get("new_OCR_calls", 0) != 0:
                raise ValueError("UNEXPECTED_OCR_CALL_IN_OWNER_STAGE")
            if len(owner["objects"]) != 1 or owner["objects"][0]["kind"] != "CONNECTION_PATH":
                raise ValueError("ACTUAL_OWNER_ADOPTION_PRECONDITION_NOT_ESTABLISHED")
            prior = [obj for obj in initial if obj["id"] not in owner["retired_ids"]] + owner["objects"]
            prior_hash = digest(prior)
            memory_before = memory_identity(gray, prior, circles)
            write_json(case / "INPUT_MEMORY_BEFORE.json", memory_before)
            write_json(case / "actual_prior_objects.json", prior)
            print(json.dumps({"case": variant["name"], "stage": "FRESH_FINITE_COMPONENT_PLAN"}), flush=True)
            result = attached.complete_attached_strokes(
                gray, ROI, source_hash, prior, case / "evidence/attached_strokes", source_graph=context,
                circle_source_objects=circles)
            if result.get("new_OCR_calls", 0) != 0:
                raise ValueError("UNEXPECTED_OCR_CALL_IN_ATTACHED_GRAPH_STAGE")
            plan = json.loads((case / "evidence/attached_strokes/plan.json").read_text(encoding="utf-8"))
            row.update(adopted_count=len(result["objects"]), pending=plan["pending"],
                       implementation=implementation_identity(attached, plan),
                       source_array_unchanged=source_hash == array_sha(gray), prior_objects_unchanged=prior_hash == digest(prior),
                       source_graph_unchanged=graph == graph_snapshot(context))
            responsibility = responsibility_summary(plan, gray, added)
            branches = branch_responsibility(graph, baseline_graph_record, added, plan)
            write_json(case / "FRESH_BRANCH_RESPONSIBILITY.json", branches)
            write_json(case / "responsibility_summary.json", responsibility)
            write_json(case / "MODEL_RECEIPTS.json", model_receipts(plan))
            geometry = [path["representation"] for path in all_candidates(plan)]
            proofs = [component.get("proof_sha256") for component in responsibility["components"]]
            if variant["name"] == "baseline":
                baseline_geometry, baseline_proofs = geometry, proofs
            row.update(candidate_geometry_identical_to_baseline=geometry == baseline_geometry,
                       component_proofs_identical_to_baseline=proofs == baseline_proofs,
                       candidate_path_count=responsibility["candidate_path_count"],
                       component_proof_count=responsibility["component_proof_count"],
                       component_status_counts=dict(Counter(component.get("status", "MISSING") for component in responsibility["components"])),
                       ledger_integrity_pass=responsibility["all_present_ledgers_integrity_pass"],
                       all_added_pixels_in_component_ledger=responsibility["all_added_pixels_in_a_component_ledger"])
            transform = SharedCoordinateTransform(ROI, DPI)
            save_actual_dxf(case, prior, result["objects"], ROI, source_hash, transform)
            row["pending_candidate_drawing"] = save_pending_candidates(case, plan, prior, ROI, source_hash, transform)
            write_json(case / "SHARED_COORDINATE_TRANSFORM.json", transform.receipt())
            print(json.dumps({"case": variant["name"], "stage": "NEW_PROCESS_SAVED_DXF_AND_SOURCE_REPLAY"}), flush=True)
            log_path = args.output.parent / (args.output.name + "-" + variant["name"] + "-strict_replay.log")
            with log_path.open("x", encoding="utf-8") as log:
                replay = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--repo", str(args.repo),
                                         "--strict-replay-case", str(case)], stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.replay_timeout_seconds, check=False)
            row["strict_replay_exit_code"] = replay.returncode
            row["strict_replay_log"] = {"path": str(log_path), "sha256": file_sha(log_path)}
            strict_path = case / "strict_replay.json"
            strict = json.loads(strict_path.read_text(encoding="utf-8")) if strict_path.exists() else {}
            row["strict_source_and_saved_replay_pass"] = strict.get("pass", False)
            row["saved_edit_status"] = strict.get("saved_dxf", {}).get("edit_status", "COLD_READ_NOT_COMPLETED")
            row["status"] = "ADOPTED_COMPONENT" if result["objects"] else "PENDING_NO_ADOPTION"
            row["expectation"] = expectation(variant, row, responsibility)
            row["current_control_gate"] = current_control_gate(variant, row, responsibility, branches, strict)
            row["evidence_integrity_pass"] = all(row.get(key) is True for key in (
                "fresh_graph_crop_matches_variant", "source_array_unchanged", "prior_objects_unchanged", "source_graph_unchanged", "ledger_integrity_pass"))
        except Exception as exc:  # noqa: BLE001 - Preserve every failed probe and continue the declared suite.
            row.update(status="PROBE_EXECUTION_ERROR", evidence_integrity_pass=False,
                       expectation={"original_declared_expectation": variant["expectation"], "satisfied": False},
                       current_control_gate={"pass": False, "status": "EXECUTION_ERROR"},
                       error={"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        row["wall_seconds"] = time.perf_counter() - started
        row["source_array_unchanged"] = source_hash == array_sha(gray)
        if prior is not None:
            memory_after = memory_identity(gray, prior, circles)
            write_json(case / "INPUT_MEMORY_AFTER.json", memory_after)
            row["source_prior_and_circle_memory_unchanged"] = memory_before == memory_after
            row["evidence_integrity_pass"] = row.get("evidence_integrity_pass", False) and memory_before == memory_after
        row["source_png_bytes_unchanged"] = file_sha(case / "source.png") == json.loads(
            (case / "input_identity.json").read_text(encoding="utf-8"))["source_png_sha256"]
        row["evidence_integrity_pass"] = row.get("evidence_integrity_pass", False) and row["source_png_bytes_unchanged"]
        write_json(case / "result.json", row)
        write_json(case / "FILE_MANIFEST.json", {"files": case_files(case), "includes_failed_stage_outputs": True})
        keys = ("name", "status", "added_raw_pixels", "adopted_count", "candidate_path_count", "skeleton_identical_to_baseline",
                "component_proof_count", "component_status_counts", "ledger_integrity_pass", "all_added_pixels_in_component_ledger",
                "strict_source_and_saved_replay_pass", "saved_edit_status", "evidence_integrity_pass", "expectation",
                "current_control_gate", "wall_seconds", "error")
        compact = {key: row.get(key) for key in keys}
        summaries.append(compact)
        print(json.dumps(plain(compact), ensure_ascii=False), flush=True)
        write_json(args.output / f"PROGRESS_{index + 1:02d}.json", {"results": summaries,
            "original_variant_count": len(declared), "planned_variant_count": len(execution),
            "execution_variants": execution_names, "execution_scope": execution_scope})
    after = source_hashes(args.repo)
    source_git_after = git_identity(args.repo)
    reference_result = {"required": args.baseline_reference is not None,
        "status": "IN_RUN_BASELINE_COMPARISON" if args.baseline_reference is None else "EXTERNAL_COMPLETED_BASELINE_COMPARISON",
        "pass": True, "comparison_only": True, "used_as_source_graph_owner_plan_or_adoption_input": False}
    if reference_before is not None:
        reference_after = {"directory": str(args.baseline_reference), "pass": False}
        try:
            reference_after["files"] = reference_inventory(args.baseline_reference)
            reference_after["validated_manifests"] = validate_reference_manifests(args.baseline_reference, reference_after["files"])
            reference_after["root_manifest_sha256"] = reference_after["files"]["FILE_MANIFEST.json"]["sha256"]
            reference_after["pass"] = reference_before["files"] == reference_after["files"]
        except Exception as exc:  # noqa: BLE001 - Keep changed or removed reference bytes as a failed gate.
            reference_after["error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(args.output / "BASELINE_REFERENCE_AFTER.json", reference_after)
        reference_result.update(directory=str(args.baseline_reference), pass_before=reference_before["pass"],
            pass_after=reference_after["pass"], source_files_sha256=reference_before["source_files_sha256"],
            before_receipt="BASELINE_REFERENCE_BEFORE.json", after_receipt="BASELINE_REFERENCE_AFTER.json",
            root_manifest_sha256_before=reference_before["root_manifest_sha256"],
            root_manifest_sha256_after=reference_after.get("root_manifest_sha256"))
        reference_result["pass"] = reference_before["pass"] and reference_after["pass"]
    summary = {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "run_completed": True,
               "original_variant_count": len(declared), "planned_variant_count": len(execution),
               "execution_variants": execution_names, "execution_scope": execution_scope, "results": summaries,
               "source_files_sha256_before": before, "source_files_sha256_after": after, "source_files_unchanged": before == after,
               "source_git_before": source_git_before, "source_git_after": source_git_after,
               "source_git_unchanged": source_git_before == source_git_after, "baseline_reference": reference_result,
               "all_strict_source_and_saved_replays_pass": all(row.get("strict_source_and_saved_replay_pass") is True for row in summaries),
               "all_input_and_graph_integrity_checks_pass": all(row.get("evidence_integrity_pass") is True for row in summaries),
               "all_original_expectations_satisfied": all(row["expectation"]["satisfied"] for row in summaries),
               "all_current_control_gates_pass": all(row["current_control_gate"]["pass"] for row in summaries),
               "original_expectations_role": "PRESERVED_HISTORICAL_COMPARISON_NOT_A_SHAPE_LABEL_VETO",
               "new_OCR_calls": 0, "new_model_inferences": 0, "ordinary_whole_region_DXF": False,
               "gui": "NOT_RUN", "windows": "NOT_RUN", "engineer_UAT": "NOT_RUN",
               "independent_physical_source_certificate": "SEPARATE_ACCEPTANCE_REQUIRED",
               "implementation": implementation_identity(attached), "script_sha256": file_sha(__file__)}
    summary.update(resources_before=resources_before, resources_after=resource_snapshot(args.output))
    summary["pass"] = (before == after and source_git_before == source_git_after and reference_result["pass"]
                       and [row["name"] for row in summaries] == execution_names
                       and summary["all_strict_source_and_saved_replays_pass"]
                       and summary["all_input_and_graph_integrity_checks_pass"] and summary["all_current_control_gates_pass"])
    write_json(args.output / "SUMMARY.json", summary)
    return 0 if summary["pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--strict-replay-case", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=list(EXPECTED_SOURCE_HASHES),
                        help="Execute one original case after verifying all eight original source arrays.")
    parser.add_argument("--baseline-reference", type=Path,
                        help="Completed same-tree single-baseline output; comparison diagnostics only.")
    parser.add_argument("--replay-timeout-seconds", type=float, default=300)
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    if args.strict_replay_case is not None:
        if args.case is not None or args.baseline_reference is not None:
            parser.error("Case selection and baseline references are not cold-replay arguments.")
        case = args.strict_replay_case.resolve()
        configure(args.repo, case)
        try:
            return strict_replay(args.repo, case)
        except Exception as exc:
            report = case / "strict_replay.json"
            if not report.exists():
                write_json(report, {"schema": "issue63-fresh-process-source-and-saved-replay-v1", "pass": False,
                           "status": "STRICT_REPLAY_EXECUTION_ERROR", "type": type(exc).__name__,
                           "message": str(exc), "traceback": traceback.format_exc()})
            raise
    args.output = args.output.resolve()
    needs_reference = args.case is not None and args.case != "baseline"
    if needs_reference != (args.baseline_reference is not None):
        parser.error("Exactly the non-baseline --case runs require --baseline-reference.")
    if args.baseline_reference is not None:
        args.baseline_reference = args.baseline_reference.resolve()
        if args.output.is_relative_to(args.baseline_reference) or args.baseline_reference.is_relative_to(args.output):
            parser.error("Output and baseline reference must be separate directories.")
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
    finally:
        write_json(args.output / "FILE_MANIFEST.json", {"files": file_manifest(args.output),
            "includes_failed_stage_outputs": True, "entrypoints": "EXECUTION_ENTRY.json",
            "runtime_caches_and_process_logs_are_outside_verified_output": True})


if __name__ == "__main__":
    sys.exit(main())
