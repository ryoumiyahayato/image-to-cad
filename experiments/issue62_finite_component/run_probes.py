"""Rebuild the original eight public sources under the finite component rule.

Each case creates a fresh graph and actually adopts its source-bound owner.
Actual adopted objects are exported and read in a separate process. Candidate
drawings are explicitly NOT_ADOPTED and use source-pixel units. These declared
development examples are not a holdout set or an ordinary whole-region result.

Example: python experiments/issue62_finite_component/run_probes.py --output NEW_DIR
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

SCHEMA = "issue62-finite-component-eight-source-probes-v1"
SCRIPT_VERSION = "one-fresh-saved-audit-and-labelled-context-v2"
EXPECTED_PLAN_SCHEMA = "source-attached-stroke-graph-plan-v3-component-exact"
EXPECTED_COMPONENT_SCHEMA = "source-finite-component-responsibility-v1"
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
              repo / "docs/native/ISSUE62_FINITE_COMPONENT_CONTRACT_20261127.md",
              repo / "docs/native/ISSUE62_EXACT_WIDTH_CONTRACT_20261127.md",
              Path(__file__).resolve()]
    return {str(path.relative_to(repo)): file_sha(path) for path in sorted(set(files))}


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
    nodes = [{"node_id": node_id, "source_pixel_centers_px": graph.xy(node["pixels"]),
              "ports": sorted(node["edges"]), "terminal": node.get("terminal"),
              "pairing": node.get("pairing"), "core_topology": node.get("core_topology"),
              "internal_source_endpoint_count": node.get("internal_source_endpoint_count")}
             for node_id, node in sorted(graph.nodes.items())]
    edges = [{"edge_id": edge_id, "nodes": edge["nodes"], "length_px": edge["length"],
              "ordered_source_pixel_centers_px": graph.xy(edge["pixels"])}
             for edge_id, edge in enumerate(graph.edges)]
    return plain({"schema": "issue62-fresh-synthetic-source-graph-v1", "roi": list(graph.roi),
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
                                                                          body.get("width", {}).get("sections", [])))}
                                  for body in proof.get("bodies", [])]
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


def save_actual_dxf(case, prior, adopted, roi, source_hash):
    import ezdxf
    from app.native_objects.cad_io import export_objects, save_native_dxf
    from tests.test_attached_stroke_graph import _native_entities

    export_objects(prior, case / "prior.dxf", roi, DPI, source_hash)
    export_objects(prior + adopted, case / "actual_adopted.dxf", roi, DPI, source_hash)
    edits = []
    for row in adopted:
        for operation in ("delete", "move"):
            doc = ezdxf.readfile(case / "actual_adopted.dxf")
            entity = _native_entities(doc)[row["id"]]
            if operation == "delete":
                doc.modelspace().delete_entity(entity)
            else:
                entity.translate(7.0, -3.0, 0.0)
            destination = case / "edits" / (row["id"] + "-" + operation + ".dxf")
            destination.parent.mkdir(exist_ok=True)
            save_native_dxf(doc, destination)
            edits.append({"id": row["id"], "operation": operation,
                          "file": destination.relative_to(case).as_posix(),
                          "sha256": file_sha(destination), "translation_mm": [7.0, -3.0, 0.0] if operation == "move" else None})
    write_json(case / "saved_files.json", {"dpi": DPI, "prior_ids": [row["id"] for row in prior],
               "adopted_ids": [row["id"] for row in adopted], "adopted_count": len(adopted),
               "prior_dxf_sha256": file_sha(case / "prior.dxf"),
               "actual_adopted_dxf_sha256": file_sha(case / "actual_adopted.dxf"),
               "edit_status": "SYNTHETIC_EDITS_SAVED" if edits else "NOT_APPLICABLE_NO_NEW_ADOPTED_OBJECTS",
               "edits": edits, "ordinary_whole_region_result": False, "gui": "NOT_RUN"})


def save_pending_candidates(case, plan, prior, roi, source_hash):
    """Save unchanged rejected geometry in an explicitly diagnostic drawing."""
    import ezdxf
    from app.native_objects.cad_io import APPID, export_objects, save_native_dxf
    from app.native_objects.text_contact_adoption import _native_object

    adopted = {row["stroke_id"] for row in plan["paths"]}
    rows = [row for row in all_candidates(plan) if row["stroke_id"] not in adopted]
    if not rows:
        return {"status": "NO_PENDING_CANDIDATES", "count": 0}
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 0
    doc.layers.new("NOT_ADOPTED", dxfattribs={"color": 1})
    mapping = []
    for row in rows:
        geometry = row["representation"]
        points, bulges = geometry["points"], geometry["bulges"]
        entity = doc.modelspace().add_lwpolyline(
            [(point[0], point[1], bulge) for point, bulge in zip(points, bulges)],
            format="xyb", close=bool(geometry["closed"]), dxfattribs={"layer": "NOT_ADOPTED"})
        mapping.append({"stroke_id": row["stroke_id"], "entity_handle": entity.dxf.handle,
                        "status": "NOT_ADOPTED", "representation": geometry})
    path = case / "NOT_ADOPTED_candidates_source_pixels.dxf"
    save_native_dxf(doc, path)
    reopened = ezdxf.readfile(path)
    cold_checks = []
    for row in mapping:
        entity = reopened.entitydb[row["entity_handle"]]
        actual = [[float(x), float(y), float(b)] for x, y, b in entity.get_points("xyb")]
        expected = [[float(p[0]), float(p[1]), float(b)]
                    for p, b in zip(row["representation"]["points"], row["representation"]["bulges"])]
        cold_checks.append({"stroke_id": row["stroke_id"],
                            "pass": actual == expected and entity.dxf.layer == "NOT_ADOPTED"
                            and bool(entity.closed) == bool(row["representation"]["closed"])})
    proposals = []
    for row in rows:
        kind, geometry = _native_object(row["representation"])
        proposals.append({"id": row["stroke_id"], "kind": kind, "layer": "NOT_ADOPTED",
                          "geometry": geometry, "status": "NOT_ADOPTED_DIAGNOSTIC_CANDIDATE",
                          "source_evidence": {"diagnostic_only": True, "source_pixels_modified": False,
                                              "source_path_points": row["source_path_px"]},
                          "editing_scope": "Unadopted geometry for independent saved-source audit only"})
    context_path = case / "NOT_ADOPTED_with_context.dxf"
    export_objects(prior + proposals, context_path, roi, DPI, source_hash)
    context_doc = ezdxf.readfile(context_path)
    context_entities = {json.loads(entity.get_xdata(APPID)[0].value)["id"]: entity
                        for entity in context_doc.modelspace() if entity.dxf.layer != "REVIEW"}
    context_checks = {
        "actual_id_set_matches_prior_and_proposals": set(context_entities) == {
            obj["id"] for obj in prior + proposals},
        "all_proposals_are_labelled_not_adopted": all(
            context_entities[obj["id"]].dxf.layer == "NOT_ADOPTED" for obj in proposals),
        "paper_mm_units": context_doc.header.get("$INSUNITS") == 4,
    }
    report = {"status": "NOT_ADOPTED_DIAGNOSTIC_ONLY", "count": len(rows), "sha256": file_sha(path),
              "file": path.name, "coordinate_frame": "UNCHANGED_SOURCE_PIXELS_Y_DOWN_NO_PAPER_MM_CLAIM",
              "candidate_geometry": mapping, "cold_read_checks": cold_checks,
              "geometry_roundtrip_pass": all(row["pass"] for row in cold_checks),
              "paper_mm_context_file": context_path.name,
              "paper_mm_context_sha256": file_sha(context_path),
              "paper_mm_context_checks": context_checks,
              "paper_mm_context_checks_pass": all(context_checks.values()),
              "source_file": "source.png", "roi_xyxy_px": list(roi), "dpi": DPI,
              "prior_ids": [obj["id"] for obj in prior], "target_ids": [obj["id"] for obj in proposals],
              "adopted_ids": [], "new_adopted_object_count": 0,
              "proposal_sidecar_chains_are_not_independent_source_acceptance": True,
              "does_not_replace_formal_drawing": True}
    write_json(case / "NOT_ADOPTED_candidates.json", report)
    return {key: value for key, value in report.items() if key not in ("candidate_geometry", "cold_read_checks")}


def cold_read_saved(case, gray, roi):
    import ezdxf
    from app.native_objects.attached_stroke_audit import cold_attached_stroke_bindings
    from tests.test_attached_stroke_graph import _native_entities, _saved_geometry

    files = json.loads((case / "saved_files.json").read_text(encoding="utf-8"))
    path = case / "actual_adopted.dxf"
    prior = _native_entities(ezdxf.readfile(case / "prior.dxf"))
    doc = ezdxf.readfile(path)
    actual = _native_entities(doc)
    expected_ids = set(files["prior_ids"]) | set(files["adopted_ids"])
    checks = {"prior_file_sha256": file_sha(case / "prior.dxf") == files["prior_dxf_sha256"],
              "actual_file_sha256": file_sha(path) == files["actual_adopted_dxf_sha256"],
              "saved_id_set_exact": set(actual) == expected_ids,
              "unique_actual_formal_entities": len(actual) == len([e for e in doc.modelspace() if e.dxf.layer != "REVIEW"]),
              "prior_saved_id_set_exact": set(prior) == set(files["prior_ids"]),
              "all_saved_prior_geometry_unchanged": all(
                  oid in actual and _saved_geometry(entity) == _saved_geometry(actual[oid])
                  for oid, entity in prior.items())}
    audit = cold_attached_stroke_bindings(path, doc, gray, roi, DPI, case / "evidence")
    checks["nonempty_saved_plan_audit"] = any(row.get("id") == "ATTACHED_STROKE_SOURCE_PLAN"
                                                for row in audit.get("checks", []))
    source_replay = audit.get("plan_replay", {})
    exact_checks = source_replay.get("checks", {})
    saved_plan = json.loads((case / "evidence/attached_strokes/plan.json").read_text(encoding="utf-8"))
    checks["all_saved_plan_fields_exactly_compared"] = bool(exact_checks) and set(exact_checks) == set(saved_plan)
    checks["all_saved_plan_field_comparisons_pass"] = bool(exact_checks) and all(value is True for value in exact_checks.values())
    checks["fresh_exact_source_replay_pass"] = source_replay.get("pass") is True and source_replay.get("reason") == "EXACT_ATTACHED_GRAPH_SOURCE_REPLAY"
    checks["cold_attached_source_audit_pass"] = audit.get("pass") is True
    edits = []
    original_geometry = {oid: _saved_geometry(entity) for oid, entity in actual.items()}
    for edit in files["edits"]:
        reopened = _native_entities(ezdxf.readfile(case / edit["file"]))
        oid, operation = edit["id"], edit["operation"]
        edit_checks = {"file_sha256": file_sha(case / edit["file"]) == edit["sha256"],
                       "id_set": set(reopened) == (set(actual) - ({oid} if operation == "delete" else set())),
                       "all_other_entities_exact": {key: _saved_geometry(entity) for key, entity in reopened.items() if key != oid}
                       == {key: geometry for key, geometry in original_geometry.items() if key != oid}}
        if operation == "move":
            expected = actual[oid].copy()
            expected.translate(*edit["translation_mm"])
            edit_checks["whole_target_translation_exact"] = oid in reopened and _saved_geometry(reopened[oid]) == _saved_geometry(expected)
        edits.append({**edit, "checks": edit_checks, "pass": all(edit_checks.values())})
    checks["all_saved_synthetic_edits_pass"] = all(edit["pass"] for edit in edits)
    return {"fresh_process": True, "checks": checks, "pass": all(checks.values()),
            "actual_formal_entity_count": len(actual), "adopted_count": files["adopted_count"],
            "actual_dxf_sha256": file_sha(path), "actual_saved_geometry_sha256": digest(original_geometry),
            "cold_source_audit": audit, "source_audit_invocation_count": 1,
            "source_replay_location": "cold_source_audit.plan_replay",
            "edit_status": files["edit_status"], "edits": edits,
            "independent_physical_source_certificate": "NOT_CLAIMED_BY_THIS_PRODUCER_REPLAY"}


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
    saved = cold_read_saved(case, gray, identity["roi"])
    verification = saved["cold_source_audit"].get("plan_replay", {})
    after = source_hashes(repo)
    checks = {"source_array_matches": array_sha(gray) == identity["source_array_sha256"],
              "source_png_matches": file_sha(source_path) == identity["source_png_sha256"],
              "source_files_unchanged": before == after, "strict_source_replay_pass": verification.get("pass") is True,
              "actual_saved_cold_read_pass": saved["pass"]}
    report = {"schema": "issue62-fresh-process-source-and-saved-replay-v1", "checks": checks,
              "pass": all(checks.values()), "plan_file_sha256": file_sha(plan_path),
              "fresh_source_graph_requested": True, "implementation": implementation_identity(attached, plan),
              "verification": verification, "saved_dxf": saved, "source_files_sha256": before,
              "source_audit_invocation_count": 1,
              "verification_source": "cold_attached_stroke_bindings.plan_replay",
              "separate_redundant_verify_call": "NOT_RUN",
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
            "zero_adoption_is_not_a_positive_control": True,
            "model_not_applicable_is_not_wrong_geometry_proof": True}


def case_files(case):
    return [{"path": path.relative_to(case).as_posix(), "size_bytes": path.stat().st_size,
             "sha256": file_sha(path)} for path in sorted(case.rglob("*")) if path.is_file()]


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
    actual_hashes = {variant["name"]: array_sha(gray) for variant, gray in prepared}
    write_json(args.output / "FROZEN_VARIANTS.json", {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "variants": declared,
               "variant_array_sha256": actual_hashes, "original_variant_array_sha256": EXPECTED_SOURCE_HASHES,
               "all_original_source_hashes_match": actual_hashes == EXPECTED_SOURCE_HASHES,
               "source_files_sha256": before, "source_git": git_identity(args.repo),
               "implementation": implementation_identity(attached), "fresh_graph_and_owner_for_every_case": True,
               "saved_dxf_and_new_process_cold_read_for_every_case": True,
               "fresh_source_audits_per_case": 1, "redundant_separate_verify_call": "NOT_RUN",
               "development_controls_not_holdout": True, "private_inputs_used": False, "new_OCR_calls": 0})
    if actual_hashes != EXPECTED_SOURCE_HASHES or attached.SCHEMA != EXPECTED_PLAN_SCHEMA:
        raise ValueError("ORIGINAL_SYNTHETIC_SOURCES_OR_NEW_PLAN_SCHEMA_MISMATCH")
    summaries, baseline_graph, baseline_geometry, baseline_proofs = [], None, None, None
    for index, (variant, gray) in enumerate(prepared):
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
        print(json.dumps({"case": variant["name"], "stage": "FRESH_GRAPH_AND_OWNER"}), flush=True)
        try:
            context, initial, structure_plan = _structure_stage(gray)
            graph = graph_snapshot(context)
            write_json(case / "fresh_graph.json", graph)
            write_json(case / "structure_plan.json", structure_plan)
            left, top, right, bottom = context.crop_bbox
            row["fresh_graph_crop_matches_variant"] = context.source_crop_hash == array_sha(gray[top:bottom, left:right])
            skeleton = {tuple(point) for point in graph["skeleton_points_px"]}
            if index == 0:
                baseline_graph = skeleton
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
            write_json(case / "actual_prior_objects.json", prior)
            print(json.dumps({"case": variant["name"], "stage": "FRESH_FINITE_COMPONENT_PLAN"}), flush=True)
            result = attached.complete_attached_strokes(
                gray, ROI, source_hash, prior, case / "evidence/attached_strokes", source_graph=context)
            if result.get("new_OCR_calls", 0) != 0:
                raise ValueError("UNEXPECTED_OCR_CALL_IN_ATTACHED_GRAPH_STAGE")
            plan = json.loads((case / "evidence/attached_strokes/plan.json").read_text(encoding="utf-8"))
            row.update(adopted_count=len(result["objects"]), pending=plan["pending"],
                       implementation=implementation_identity(attached, plan),
                       source_array_unchanged=source_hash == array_sha(gray), prior_objects_unchanged=prior_hash == digest(prior),
                       source_graph_unchanged=graph == graph_snapshot(context))
            responsibility = responsibility_summary(plan, gray, added)
            write_json(case / "responsibility_summary.json", responsibility)
            geometry = [path["representation"] for path in all_candidates(plan)]
            proofs = [component.get("proof_sha256") for component in responsibility["components"]]
            if index == 0:
                baseline_geometry, baseline_proofs = geometry, proofs
            row.update(candidate_geometry_identical_to_baseline=geometry == baseline_geometry,
                       component_proofs_identical_to_baseline=proofs == baseline_proofs,
                       candidate_path_count=responsibility["candidate_path_count"],
                       component_proof_count=responsibility["component_proof_count"],
                       component_status_counts=dict(Counter(component.get("status", "MISSING") for component in responsibility["components"])),
                       ledger_integrity_pass=responsibility["all_present_ledgers_integrity_pass"],
                       all_added_pixels_in_component_ledger=responsibility["all_added_pixels_in_a_component_ledger"])
            save_actual_dxf(case, prior, result["objects"], ROI, source_hash)
            row["pending_candidate_drawing"] = save_pending_candidates(case, plan, prior, ROI, source_hash)
            print(json.dumps({"case": variant["name"], "stage": "NEW_PROCESS_SAVED_DXF_AND_SOURCE_REPLAY"}), flush=True)
            with (case / "strict_replay.log").open("x", encoding="utf-8") as log:
                replay = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
                                         "--strict-replay-case", str(case)], stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.replay_timeout_seconds, check=False)
            row["strict_replay_exit_code"] = replay.returncode
            strict_path = case / "strict_replay.json"
            strict = json.loads(strict_path.read_text(encoding="utf-8")) if strict_path.exists() else {}
            row["strict_source_and_saved_replay_pass"] = strict.get("pass", False)
            row["saved_edit_status"] = strict.get("saved_dxf", {}).get("edit_status", "COLD_READ_NOT_COMPLETED")
            row["status"] = "ADOPTED_COMPONENT" if result["objects"] else "PENDING_NO_ADOPTION"
            row["expectation"] = expectation(variant, row, responsibility)
            row["evidence_integrity_pass"] = all(row.get(key) is True for key in (
                "fresh_graph_crop_matches_variant", "source_array_unchanged", "prior_objects_unchanged", "source_graph_unchanged", "ledger_integrity_pass"))
        except Exception as exc:  # noqa: BLE001 - Preserve every failed probe and continue the declared suite.
            row.update(status="PROBE_EXECUTION_ERROR", evidence_integrity_pass=False,
                       expectation={"original_declared_expectation": variant["expectation"], "satisfied": False},
                       error={"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        row["wall_seconds"] = time.perf_counter() - started
        row["source_array_unchanged"] = source_hash == array_sha(gray)
        write_json(case / "result.json", row)
        write_json(case / "FILE_MANIFEST.json", {"files": case_files(case), "includes_failed_stage_outputs": True})
        keys = ("name", "status", "added_raw_pixels", "adopted_count", "candidate_path_count", "skeleton_identical_to_baseline",
                "component_proof_count", "component_status_counts", "ledger_integrity_pass", "all_added_pixels_in_component_ledger",
                "strict_source_and_saved_replay_pass", "saved_edit_status", "evidence_integrity_pass", "expectation", "wall_seconds", "error")
        compact = {key: row.get(key) for key in keys}
        summaries.append(compact)
        print(json.dumps(plain(compact), ensure_ascii=False), flush=True)
        write_json(args.output / f"PROGRESS_{index + 1:02d}.json", {"results": summaries, "planned_variant_count": len(declared)})
    after = source_hashes(args.repo)
    summary = {"schema": SCHEMA, "script_version": SCRIPT_VERSION, "run_completed": True, "planned_variant_count": len(declared), "results": summaries,
               "source_files_sha256_before": before, "source_files_sha256_after": after, "source_files_unchanged": before == after,
               "all_strict_source_and_saved_replays_pass": all(row.get("strict_source_and_saved_replay_pass") is True for row in summaries),
               "all_input_and_graph_integrity_checks_pass": all(row.get("evidence_integrity_pass") is True for row in summaries),
               "all_original_expectations_satisfied": all(row["expectation"]["satisfied"] for row in summaries),
               "new_OCR_calls": 0, "new_model_inferences": 0, "ordinary_whole_region_DXF": False,
               "gui": "NOT_RUN", "windows": "NOT_RUN", "engineer_UAT": "NOT_RUN",
               "independent_physical_source_certificate": "SEPARATE_ACCEPTANCE_REQUIRED",
               "implementation": implementation_identity(attached), "script_sha256": file_sha(__file__)}
    summary["pass"] = (before == after and summary["all_strict_source_and_saved_replays_pass"]
                       and summary["all_input_and_graph_integrity_checks_pass"] and summary["all_original_expectations_satisfied"])
    write_json(args.output / "SUMMARY.json", summary)
    return 0 if summary["pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--strict-replay-case", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--replay-timeout-seconds", type=float, default=300)
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
                write_json(report, {"schema": "issue62-fresh-process-source-and-saved-replay-v1", "pass": False,
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
