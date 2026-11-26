"""Independent diagnostics for finite raw-ink candidate files.

This reader does not call the candidate producer, trust its `pass` fields, or
approve native adoption. Human-reviewed reference points are optional evaluation
inputs only. They never feed the candidate discovery module. Pixel coverage and
endpoint proximity are explicitly descriptive, not proof of independent objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


SCHEMA = "raw-ink-independent-diagnostic-audit-v1"


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def closed_segment_cells(a, b):
    """Independent slab intersection with *closed* original pixel squares.

    A white square touched at a corner remains a white contact. There is no
    distance-field allowance, opening, closing, or interpolation of source ink.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    delta = b - a
    low = np.ceil(np.minimum(a, b) - 0.5).astype(int)
    high = np.floor(np.maximum(a, b) + 0.5).astype(int)
    result = []
    for y in range(low[1], high[1] + 1):
        for x in range(low[0], high[0] + 1):
            enter, leave = 0.0, 1.0
            for k, center in enumerate((x, y)):
                if abs(delta[k]) <= 1e-14:
                    if not center - 0.5 <= a[k] <= center + 0.5:
                        leave = -1.0
                        break
                else:
                    t0, t1 = sorted(((center - 0.5 - a[k]) / delta[k],
                                     (center + 0.5 - a[k]) / delta[k]))
                    enter, leave = max(enter, t0), min(leave, t1)
            if enter <= leave + 1e-12:
                result.append((x, y))
    return result


def point_path_distances(points, path):
    points, path = np.asarray(points, float), np.asarray(path, float)
    if len(points) == 0:
        return np.empty(0)
    if len(path) < 2:
        return np.full(len(points), np.inf)
    a, v = path[:-1], np.diff(path, axis=0)
    lengths2 = (v * v).sum(axis=1)
    q = points[:, None, :] - a[None, :, :]
    t = np.clip((q * v[None, :, :]).sum(axis=2) /
                np.maximum(lengths2, 1e-20), 0.0, 1.0)
    return np.linalg.norm(q - t[:, :, None] * v[None, :, :], axis=2).min(axis=1)


def _edge_set(points):
    return {tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(points, points[1:])}


def positive_collinear_overlap_length(first, second):
    """Union collinear finite overlaps per first segment, excluding point contacts."""
    first, second = np.asarray(first, float), np.asarray(second, float)
    total = 0.0
    for a, b in zip(first, first[1:]):
        v = b - a
        length = float(np.linalg.norm(v))
        if length <= 1e-10:
            continue
        unit = v / length
        normal = np.array([-unit[1], unit[0]])
        intervals = []
        for c, d in zip(second, second[1:]):
            if max(abs(float((c - a) @ normal)), abs(float((d - a) @ normal))) > 1e-8:
                continue
            low, high = sorted((float((c - a) @ unit), float((d - a) @ unit)))
            low, high = max(0.0, low), min(length, high)
            if high - low > 1e-8:
                intervals.append((low, high))
        end = -np.inf
        for low, high in sorted(intervals):
            total += max(0.0, high - max(low, end))
            end = max(end, high)
    return total


def audit_saved_protected_path(baseline_dxf, baseline_objects, plan, reference):
    """Read actual saved geometry rather than the candidate's ownership receipt.

    This is a read-only baseline check, not integration-preservation acceptance.
    It measures the conflict if candidate polylines were exported unchanged.
    """
    import ezdxf

    doc = ezdxf.readfile(baseline_dxf)
    baseline = json.loads(Path(baseline_objects).read_text(encoding="utf-8"))
    formal = [entity for entity in doc.modelspace() if entity.dxf.layer != "REVIEW"]
    identities = {}
    for entity in formal:
        if entity.has_xdata("I2CAD_NATIVE_V2"):
            chunks = [tag.value for tag in entity.get_xdata("I2CAD_NATIVE_V2") if tag.code == 1000]
            identity = json.loads("".join(chunks))
            identities.setdefault(identity["id"], []).append(entity)
    expected_ids = {row["id"] for row in baseline["objects"]}
    checks = {
        "saved_baseline_dxf_hash_matches_sidecar": file_sha(baseline_dxf) == baseline["dxf_sha256"],
        "all_formal_ids_match_baseline_sidecar": set(identities) == expected_ids,
        "every_formal_identity_is_unique": all(len(rows) == 1 for rows in identities.values()),
        "every_formal_entity_has_one_identity": len(identities) == len(formal),
    }
    target_id = reference["protected_main_path"]["id"]
    entity = identities[target_id][0]
    if entity.dxftype() != "LWPOLYLINE" or entity.closed:
        raise ValueError("PROTECTED_MAIN_PATH_NOT_SAVED_OPEN_LWPOLYLINE")
    if any(abs(row[2]) > 1e-12 for row in entity.get_points("xyb")):
        raise ValueError("THIS_LINEAR_CONFLICT_AUDIT_REQUIRES_ZERO_BULGES")
    mm = 25.4 / baseline["dpi"]
    roi = baseline["roi_xyxy_px"]
    saved = [[row[0] / mm + roi[0], roi[3] - row[1] / mm]
             for row in entity.get_points("xy")]
    expected_geometry = reference["protected_main_path"]["geometry"]["points"]
    checks["saved_main_vertices_match_bound_reference"] = bool(
        np.asarray(saved).shape == np.asarray(expected_geometry).shape
        and np.allclose(saved, expected_geometry, atol=1e-8, rtol=0))
    return {
        "scope": "READ_ONLY_BASELINE_AND_HYPOTHETICAL_UNCHANGED_CANDIDATE_EXPORT",
        "baseline_dxf_sha256": file_sha(baseline_dxf),
        "checks": checks, "formal_count": len(formal),
        "review_count": sum(e.dxf.layer == "REVIEW" for e in doc.modelspace()),
        "named_block_count": sum(not b.name.startswith("*") for b in doc.blocks),
        "protected_path_vertex_count": len(saved),
        "candidate_conflicts_with_saved_protected_path": [
            {"candidate_id": c["candidate_id"], "positive_duplicate_length_px": overlap,
             "positive_duplicate_length_paper_mm": overlap * mm}
            for c in plan["candidates"]
            for overlap in [positive_collinear_overlap_length(c["source_path_px"], saved)]
            if overlap > 1e-8],
        "integrated_new_dxf_preservation_test": "NOT_RUN_NO_NEW_FORMAL_DXF",
    }


def _endpoint_ring(gray, point, radius):
    """Count raw-ink arcs on a bounded square ring, without declaring terminals."""
    x, y = map(int, point)
    left, right = max(0, x - radius), min(gray.shape[1], x + radius + 1)
    top, bottom = max(0, y - radius), min(gray.shape[0], y + radius + 1)
    ink = gray[top:bottom, left:right] < 128
    ring = np.zeros_like(ink)
    ring[0] = ink[0]
    ring[-1] = ink[-1]
    ring[:, 0] = ink[:, 0]
    ring[:, -1] = ink[:, -1]
    _, count = ndimage.label(ring, structure=np.ones((3, 3), dtype=np.uint8))
    return {"radius_px": radius, "boundary_ink_arc_count_8_connected": int(count),
            "window_xyxy_px": [left, top, right, bottom],
            "is_endpoint_proof": False}


def audit_candidate(gray, candidate, roi, width):
    """Recalculate raw support and exact geometry independently of assertions."""
    path = np.asarray(candidate.get("source_path_px", []), float)
    representation = candidate.get("representation", {})
    vertices = np.asarray(representation.get("points", []), float)
    checks = {}
    checks["finite_ordered_pixel_centers"] = bool(
        path.ndim == 2 and path.shape[1:] == (2,) and len(path) >= 2
        and np.isfinite(path).all() and np.array_equal(path, np.rint(path)))
    if not checks["finite_ordered_pixel_centers"]:
        return {"candidate_id": candidate.get("candidate_id"), "checks": checks,
                "status": "INVALID_CANDIDATE_DATA"}
    integer = path.astype(int)
    checks["source_points_inside_image"] = bool(
        np.all(integer >= 0) and np.all(integer[:, 0] < gray.shape[1])
        and np.all(integer[:, 1] < gray.shape[0]))
    if not checks["source_points_inside_image"]:
        return {"candidate_id": candidate.get("candidate_id"), "checks": checks,
                "status": "SOURCE_OUTSIDE_IMAGE"}
    steps = np.abs(np.diff(integer, axis=0))
    checks["all_source_points_are_original_black_pixels"] = bool(
        np.all(gray[integer[:, 1], integer[:, 0]] < 128))
    checks["all_steps_use_distinct_8_neighbor_pixels"] = bool(
        np.all(steps.max(axis=1) == 1))
    checks["declared_geometry_matches_actual_candidate_trace"] = bool(
        np.array_equal(vertices, path) and representation.get("closed") is False
        and representation.get("bulges") == [0.0] * len(path))
    cells = set()
    for a, b in zip(path, path[1:]):
        cells.update(closed_segment_cells(a, b))
    outside = sorted((x, y) for x, y in cells
                     if not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]))
    white = sorted((x, y) for x, y in cells
                   if 0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]
                   and gray[y, x] >= 128)
    checks["closed_native_segment_cells_all_original_ink"] = not white and not outside
    edges = _edge_set(integer.tolist())
    checks["no_exact_retraced_native_segment"] = len(edges) == len(path) - 1
    x0, y0, x1, y1 = roi
    ends = path[[0, -1]]
    checks["endpoints_not_on_crop_boundary"] = bool(
        np.all(ends[:, 0] > x0) and np.all(ends[:, 0] < x1 - 1)
        and np.all(ends[:, 1] > y0) and np.all(ends[:, 1] < y1 - 1))
    return {
        "candidate_id": candidate["candidate_id"], "checks": checks,
        "status": "GEOMETRIC_DIAGNOSTICS_ONLY_NOT_ADOPTION",
        "source_point_count": len(path),
        "endpoint_points_px": ends.tolist(),
        "closed_cell_count": len(cells), "white_closed_cells_px": white,
        "outside_image_closed_cells_px": outside,
        "endpoint_raw_ring_observations": [
            {"point_px": p.tolist(), "rings": [
                _endpoint_ring(gray, p, max(2, int(np.ceil(k * width)))) for k in (1, 2, 3)]}
            for p in ends],
        "independent_object_ownership_proved": False,
        "source_support_alone_is_not_completeness": True,
    }


def _boundary_sets(reference):
    result = []
    for i, free in enumerate(reference["known_free_endpoints"]):
        if free is not None:
            result.append(np.asarray([free], float))
        else:
            core = reference["shared_core_records"][0 if i == 0 else -1]
            result.append(np.asarray(core["original_core_points"], float))
    return result


def evaluate_references(plan, reference):
    """Describe all candidate matches; ranking is for illustrations, never adoption."""
    target_rows = reference["target_rows"]
    main_path = reference["protected_main_path"]["source_path_points"]
    main_edges = _edge_set(main_path)
    targets = []
    for target in target_rows:
        samples = target["known_exclusive_source_samples"]
        envelope = target["source_sample_envelope"]
        boundaries = _boundary_sets(target)
        comparisons = []
        for candidate in plan["candidates"]:
            path = np.asarray(candidate["source_path_px"], float)
            distances = point_path_distances(samples, path)
            count_1 = int(np.count_nonzero(distances <= 1.0))
            count_2 = int(np.count_nonzero(distances <= 2.0))
            if count_2 == 0:
                continue
            ends = path[[0, -1]]
            boundary_distance = np.asarray([
                [float(np.linalg.norm(region - e, axis=1).min()) for e in ends]
                for region in boundaries])
            ordering = (0, 1) if boundary_distance[0, 0] + boundary_distance[1, 1] <= (
                boundary_distance[0, 1] + boundary_distance[1, 0]) else (1, 0)
            end_errors = [float(boundary_distance[i, ordering[i]]) for i in (0, 1)]
            other_contacts = []
            for other in target_rows:
                if other["target"] == target["target"]:
                    continue
                other_distances = point_path_distances(other["known_exclusive_source_samples"], path)
                other_contacts.append({"target": other["target"],
                                       "exclusive_samples_within_1px": int((other_distances <= 1.0).sum()),
                                       "exclusive_samples_within_2px": int((other_distances <= 2.0).sum())})
            # Distances to a set, not to its arbitrarily sorted polygon.
            set_distance = np.linalg.norm(path[:, None, :] - np.asarray(envelope)[None, :, :], axis=2).min(axis=1)
            shared_edges = sorted(_edge_set(candidate["source_path_px"]) & main_edges)
            comparisons.append({
                "candidate_id": candidate["candidate_id"],
                "exclusive_reference_samples": len(samples),
                "exclusive_samples_within_1px": count_1,
                "exclusive_samples_within_2px": count_2,
                "maximum_exclusive_reference_distance_px": float(distances.max()),
                "uncovered_exclusive_samples_at_2px": [p for p, distance in zip(samples, distances) if distance > 2.0],
                "nearest_reference_boundary_errors_px": end_errors,
                "candidate_endpoint_order_for_reference": list(ordering),
                "candidate_samples_outside_reference_envelope_2px": path[set_distance > 2.0].tolist(),
                "other_target_reference_contacts": other_contacts,
                "shared_raw_source_adjacencies_with_protected_main_path": shared_edges,
                "all_reference_exclusive_samples_within_2px": count_2 == len(samples),
                "both_boundaries_within_2px": max(end_errors) <= 2.0,
                "geometry_approval": False,
            })
        comparisons.sort(key=lambda row: (-row["exclusive_samples_within_2px"],
                                         max(row["nearest_reference_boundary_errors_px"]),
                                         -row["exclusive_samples_within_1px"], row["candidate_id"]))
        targets.append({
            "target": target["target"], "label": target["label"],
            "status": "PARTIAL_CANDIDATES_OWNERSHIP_UNRESOLVED" if comparisons else "NO_CANDIDATE_NEAR_REFERENCE",
            "illustration_candidate_id": comparisons[0]["candidate_id"] if comparisons else None,
            "all_candidate_comparisons": comparisons,
            "complete_recovered_objects": 0,
            "criterion_note": "1px and 2px distances describe source sampling. They are not completeness/adoption tolerances.",
        })
    return targets


def audit_plan(gray, plan, reference=None):
    source_hash = hashlib.sha256(gray.tobytes()).hexdigest()
    x0, y0, x1, y1 = plan["roi_xyxy_px"]
    resources = dict(plan.get("resources", {}))
    resource_stop = bool(resources.get("seed_axis_overflow")
                         or resources.get("candidate_overflow")
                         or resources.get("axis_branch_overflows"))
    bindings = {
        "full_source_pixels_match": source_hash == plan["source_array_sha256"],
        "source_crop_pixels_match": hashlib.sha256(gray[y0:y1, x0:x1].tobytes()).hexdigest()
        == plan["original_crop_array_sha256"],
        "no_duplicate_candidate_id": len({c["candidate_id"] for c in plan["candidates"]}) == len(plan["candidates"]),
    }
    candidates = [audit_candidate(gray, c, plan["roi_xyxy_px"], plan["estimated_ink_width_px"])
                  for c in plan["candidates"]]
    target_results = evaluate_references(plan, reference) if reference else []
    if resource_stop:
        for row in target_results:
            row["status"] = ("NOT_EVALUATED_RESOURCE_LIMIT" if not candidates
                             else "PARTIAL_EVALUATION_RESOURCE_LIMIT")
    audit_status = ("PROVIDED_CANDIDATES_RECHECKED" if candidates else
                    "NOT_EVALUATED_RESOURCE_LIMIT" if resource_stop else
                    "EMPTY_DISCOVERY_OUTPUT_NO_CANDIDATE_VALIDATION")
    pairwise = []
    sets = {c["candidate_id"]: _edge_set(c["source_path_px"]) for c in plan["candidates"]}
    ids = list(sets)
    for i, first in enumerate(ids):
        for second in ids[i + 1:]:
            overlap = sets[first] & sets[second]
            if overlap:
                pairwise.append({"first": first, "second": second,
                                 "same_geometric_pixel_segments": len(overlap),
                                 "simultaneous_output_not_approved": True})
    return {
        "schema": SCHEMA, "source_binding_checks": bindings,
        "producer_discovery_status": plan.get("status"),
        "producer_resources": resources,
        "declared_discovery_budget_completed": not resource_stop,
        "candidate_audit_status": audit_status,
        "within_section_pixel_walks_or_ownerships_exhaustively_enumerated": False,
        "candidate_checks": candidates,
        "all_candidates_rechecked_from_original_pixels": bool(candidates) and all(bindings.values()),
        "candidates_failing_closed_cell_support": [r["candidate_id"] for r in candidates
                                                  if not r["checks"].get("closed_native_segment_cells_all_original_ink")],
        "competing_candidates_with_duplicate_geometric_segments": pairwise,
        "reference_comparison_is_evaluation_only": True,
        "target_results": target_results,
        "no_production_adoption_certificate_was_issued": True,
        "complete_recovered_objects": 0,
        "normal_full_roi_conversion": "NOT_RUN_NO_PROVED_ADOPTABLE_OBJECT",
        "saved_formal_experiment_dxf": "NOT_PRODUCED_NO_PROVED_ADOPTABLE_OBJECT",
        "candidate_delete_move_save_reopen": "NOT_RUN_NO_FORMAL_ADOPTION_CLAIM",
        "new_OCR_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--baseline-dxf", type=Path)
    parser.add_argument("--baseline-objects", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gray = np.array(Image.open(args.input).convert("L"))
    plan = json.loads(args.candidates.read_text(encoding="utf-8"))
    reference = json.loads(args.reference.read_text(encoding="utf-8")) if args.reference else None
    result = audit_plan(gray, plan, reference)
    if bool(args.baseline_dxf) != bool(args.baseline_objects):
        parser.error("--baseline-dxf and --baseline-objects must be provided together")
    if args.baseline_dxf:
        if reference is None:
            parser.error("saved baseline check requires the evaluation-only --reference")
        result["saved_baseline_check"] = audit_saved_protected_path(
            args.baseline_dxf, args.baseline_objects, plan, reference)
    result["input_file_sha256"] = file_sha(args.input)
    result["candidate_file_sha256"] = file_sha(args.candidates)
    result["reference_file_sha256"] = file_sha(args.reference) if args.reference else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"candidates_audited": len(result["candidate_checks"]),
                      "closed_cell_failures": len(result["candidates_failing_closed_cell_support"]),
                      "complete_recovered_objects": 0}))


if __name__ == "__main__":
    main()
