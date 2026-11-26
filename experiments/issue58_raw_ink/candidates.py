"""Experimental finite ink-band candidates, independently of the native source graph.

This is a candidate-discovery experiment, not a source-ownership or adoption gate.
All coordinates and scales derive from the supplied image/ROI. No original pixel
is created, removed or recoloured. Hough votes only nominate axes; actual paths
use adjacent original black pixel centres. Raw branch alternatives are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import platform
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

SCHEMA = "raw-ink-finite-band-candidates-v1"
POLICY = {
    "version": "raw-ink-hough-section-dag-v1",
    "source_threshold": 128,
    "ridge_width_estimator": "twice_median_positive_3x3_edt_maximum",
    "minimum_estimated_width_px": 1.0,
    "hough_rho_px": 1.0,
    "hough_theta_degrees": 1.0,
    "hough_vote_widths": 2.0,
    "hough_minimum_length_widths": 4.0,
    "hough_maximum_line_gap_px": 0,
    "minimum_candidate_length_widths": 4.0,
    "band_half_widths": 1.25,
    "section_width_px": math.sqrt(2.0),
    "axis_rho_quantum_px": 0.5,
    "axis_angle_quantum_degrees": 1.0,
    "minimum_seed_interval_overlap_fraction": 0.5,
    "maximum_seed_axes": 512,
    "maximum_section_paths_per_axis": 256,
    "maximum_candidate_paths": 4096,
    "minimum_seed_length_px": 6,
    "minimum_votes": 4,
    "seed_rng": 0,
    "geodesic_cost": "length * (1 + 1 / (1 + original_ink_edt))",
    "geodesic_represents_section_path_not_all_pixel_walks": True,
    "every_section_alternative_retained_unless_explicit_resource_stop": True,
    "source_graph_is_used": False,
    "original_source_pixels_modified": False,
    "candidate_is_not_an_adoption_approval": True,
    "complete_recovery_claims_allowed": False,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def retain_axis_evidence(rows, row):
    """Deduplicate geometry while retaining every distinct axis explanation.

    The historical top-level evidence fields remain a representative witness.
    They must not be mistaken for a union or consensus of the axis witnesses.
    Copies are necessary: merging seed provenance may not mutate the first
    axis's independently replayable explanation.
    """
    fields = (
        "seed_axes", "finite_projected_interval_local_px", "section_sequence",
        "section_sequence_competitors_in_same_axis",
        "original_ink_support_pixels_px", "unassigned_adjacent_source_pixels_px",
        "original_white_holes_touching_band", "endpoint_evidence", "rejection_reasons",
    )
    variant = {name: deepcopy(row[name]) for name in fields}
    variant["source_path_sha256"] = digest(row["source_path_px"])
    ident = row["candidate_id"]
    if ident in rows:
        if rows[ident]["source_path_px"] != row["source_path_px"]:
            raise ValueError("CANDIDATE_ID_COLLISION_WITH_DIFFERENT_SOURCE_PATH")
        rows[ident]["seed_axes"].extend(deepcopy(row["seed_axes"]))
        rows[ident]["axis_evidence_variants"].append(variant)
    else:
        row["axis_evidence_variants"] = [variant]
        row["primary_evidence_fields_are_representative_only"] = True
        row["axis_evidence_schema"] = "all-axis-explanations-for-identical-source-path-v1"
        rows[ident] = row


def _neighbors(point):
    x, y = point
    return [(x + dx, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if dx or dy]


def _components(points):
    remaining = set(points)
    groups = []
    while remaining:
        root = min(remaining, key=lambda p: (p[1], p[0]))
        remaining.remove(root)
        group, stack = {root}, [root]
        while stack:
            p = stack.pop()
            for q in _neighbors(p):
                if q in remaining:
                    remaining.remove(q)
                    group.add(q)
                    stack.append(q)
        groups.append(group)
    return groups


def _holes(ink, origin):
    # Four-connected white regions distinguish true enclosed white pixels from
    # diagonal background access. They remain evidence, never get filled.
    labels, count = ndimage.label(~ink)
    border = set(np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    rows = []
    for ident in range(1, count + 1):
        if ident in border:
            continue
        yy, xx = np.nonzero(labels == ident)
        points = np.column_stack((xx + origin[0], yy + origin[1])).tolist()
        rows.append({"white_pixels_px": points, "pixel_count": len(points),
                     "bbox_xyxy_px": [int(xx.min() + origin[0]), int(yy.min() + origin[1]),
                                      int(xx.max() + origin[0] + 1), int(yy.max() + origin[1] + 1)],
                     "interpretation": "ENCLOSED_ORIGINAL_WHITE_REGION_NOT_FILLED"})
    return rows


def _seeds(ink, points, width):
    cv2.setRNGSeed(POLICY["seed_rng"])
    minimum = max(POLICY["minimum_seed_length_px"],
                  math.ceil(POLICY["hough_minimum_length_widths"] * width))
    raw = cv2.HoughLinesP(
        ink.astype(np.uint8) * 255,
        POLICY["hough_rho_px"], math.radians(POLICY["hough_theta_degrees"]),
        threshold=max(POLICY["minimum_votes"], math.ceil(POLICY["hough_vote_widths"] * width)),
        minLineLength=minimum, maxLineGap=POLICY["hough_maximum_line_gap_px"],
    )
    groups = defaultdict(list)
    if raw is None:
        return [], False
    for line in sorted(raw[:, 0].tolist()):
        start, end = np.asarray(line[:2], float), np.asarray(line[2:], float)
        direction = end - start
        length = float(np.linalg.norm(direction))
        if not length:
            continue
        angle = math.degrees(math.atan2(direction[1], direction[0])) % 180.0
        angle = round(angle / POLICY["axis_angle_quantum_degrees"]) * POLICY["axis_angle_quantum_degrees"]
        angle %= 180.0
        axis = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
        normal = np.array([-axis[1], axis[0]])
        along, across = points @ axis, points @ normal
        lo, hi = sorted([float(start @ axis), float(end @ axis)])
        center = float((start + end) @ normal / 2)
        # Centre the proposed band using only finite raw support near the seed.
        supporting = (along >= lo) & (along <= hi) & (abs(across - center) <= width)
        if np.any(supporting):
            center = float(np.median(across[supporting]))
        rho = round(center / POLICY["axis_rho_quantum_px"]) * POLICY["axis_rho_quantum_px"]
        groups[(angle, rho)].append({"hough_endpoints_local_px": [start.tolist(), end.tolist()],
                                     "finite_seed_interval_px": [lo, hi]})
    overflow = len(groups) > POLICY["maximum_seed_axes"]
    # On overflow, expose all nominated axes in metadata, but do not analyze a
    # silently privileged prefix. The caller gets an explicit resource result.
    rows = [{"angle_deg": angle, "normal_offset_px": rho, "seeds": seeds}
            for (angle, rho), seeds in sorted(groups.items())]
    return rows, overflow


def _dag_paths(nodes, links):
    predecessors = defaultdict(set)
    for a, children in links.items():
        for b in children:
            predecessors[b].add(a)
    roots = [n for n in sorted(nodes) if not predecessors[n]]
    paths = []
    stack = [(n, [n]) for n in reversed(roots)]
    cap = POLICY["maximum_section_paths_per_axis"]
    while stack:
        n, path = stack.pop()
        children = sorted(links[n])
        if not children:
            paths.append(path)
            if len(paths) > cap:
                return [], True, len(paths)
        else:
            stack.extend((child, path + [child]) for child in reversed(children))
    return paths, False, len(paths)


def _representative_path(allowed, start, end, distance):
    queue = [(0.0, start)]
    costs, previous = {start: 0.0}, {}
    while queue:
        cost, p = heapq.heappop(queue)
        if cost > costs[p]:
            continue
        if p == end:
            trail = [p]
            while p != start:
                p = previous[p]
                trail.append(p)
            return trail[::-1]
        for q in _neighbors(p):
            if q not in allowed:
                continue
            step = math.hypot(q[0] - p[0], q[1] - p[1])
            clearance = float(distance[q[1], q[0]])
            next_cost = cost + step * (1.0 + 1.0 / (1.0 + clearance))
            if next_cost < costs.get(q, float("inf")) - 1e-12:
                costs[q] = next_cost
                previous[q] = p
                heapq.heappush(queue, (next_cost, q))
    raise ValueError("ORIGINAL_INK_SECTION_SEQUENCE_DISCONNECTED")


def _endpoint(node_points, axis, rho, distance, first):
    sign = -1 if first else 1
    pts = np.asarray(sorted(node_points), float)
    projection = sign * (pts @ axis)
    outer = pts[projection >= projection.max() - 0.5]
    normal = np.array([-axis[1], axis[0]])
    return min((tuple(map(int, p)) for p in outer),
               key=lambda p: (-distance[p[1], p[0]], abs(np.asarray(p) @ normal - rho), p))


def _endpoint_evidence(endpoint, support, whole_ink, axis, first, origin, box, width):
    sign = -1 if first else 1
    outgoing = axis * sign
    nearby = set()
    radius = max(2, math.ceil(width))
    x, y = endpoint
    for yy in range(max(0, y - radius), min(whole_ink.shape[0], y + radius + 1)):
        for xx in range(max(0, x - radius), min(whole_ink.shape[1], x + radius + 1)):
            if whole_ink[yy, xx] and (xx, yy) not in support:
                nearby.add((xx, yy))
    connected_outside = {q for p in support for q in _neighbors(p)
                         if q in nearby}
    forward_outside = [q for q in connected_outside
                       if (np.asarray(q) - endpoint) @ outgoing > 0.0]
    crop_censored = (x <= 0 or y <= 0 or x >= whole_ink.shape[1] - 1 or y >= whole_ink.shape[0] - 1)
    if crop_censored:
        interpretation = "ROI_CENSORED_NOT_A_TRUE_ENDPOINT"
    elif forward_outside:
        interpretation = "BAND_EXIT_OR_ATTACHMENT_UNRESOLVED"
    elif connected_outside:
        interpretation = "LATERAL_CONTACT_OR_TURN_UNRESOLVED"
    else:
        interpretation = "FINITE_RAW_CAP_CANDIDATE_NOT_PROOF_OF_OBJECT_COMPLETENESS"
    return {
        "source_point_px": [int(endpoint[0] + origin[0]), int(endpoint[1] + origin[1])],
        "interpretation": interpretation,
        "crop_censored": crop_censored,
        "outward_axis": outgoing.tolist(),
        "nearby_connected_source_outside_candidate_band_px":
            [[int(p[0] + origin[0]), int(p[1] + origin[1])] for p in sorted(connected_outside)],
        "boundary_is_ownership_approved": False,
    }


def _one_axis(ink, points, edt, width, seed, origin, roi, holes):
    angle = math.radians(seed["angle_deg"])
    axis = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-axis[1], axis[0]])
    rho = seed["normal_offset_px"]
    across, along = points @ normal, points @ axis
    in_band = abs(across - rho) <= POLICY["band_half_widths"] * width
    selected = points[in_band].astype(int)
    stations = np.floor(along[in_band] / POLICY["section_width_px"]).astype(int)
    bins = defaultdict(set)
    for p, station in zip(selected, stations):
        bins[int(station)].add(tuple(p))
    nodes, membership = {}, {}
    for station, pixels in sorted(bins.items()):
        for component in _components(pixels):
            nid = len(nodes)
            nodes[nid] = {"station": station, "pixels": component}
            for p in component:
                membership[p] = nid
    links = defaultdict(set)
    for p, nid in membership.items():
        for q in _neighbors(p):
            other = membership.get(q)
            if other is not None and nodes[other]["station"] == nodes[nid]["station"] + 1:
                links[nid].add(other)
    alternatives, overflow, observed_count = _dag_paths(nodes, links)
    axis_summary = {
        **seed, "band_half_width_px": POLICY["band_half_widths"] * width,
        "section_nodes": len(nodes),
        "section_splits": [{"node": n, "station": nodes[n]["station"], "children": sorted(links[n])}
                           for n in sorted(nodes) if len(links[n]) > 1],
        "status": "RESOURCE_LIMIT_ALL_AXIS_CANDIDATES_WITHHELD" if overflow else "ALL_SECTION_BRANCH_SEQUENCES_ENUMERATED",
        "maximal_section_sequences": observed_count,
        "within_section_pixel_walks_exhaustively_enumerated": False,
    }
    if overflow:
        return [], axis_summary
    result = []
    for seq in alternatives:
        support = set().union(*(nodes[n]["pixels"] for n in seq))
        if len(support) < 2:
            continue
        ps = np.asarray(list(support), float)
        lo, hi = float((ps @ axis).min()), float((ps @ axis).max())
        if hi - lo < POLICY["minimum_candidate_length_widths"] * width:
            continue
        matching = [s for s in seed["seeds"]
                    if max(0, min(hi, s["finite_seed_interval_px"][1]) - max(lo, s["finite_seed_interval_px"][0]))
                    >= POLICY["minimum_seed_interval_overlap_fraction"] *
                    (s["finite_seed_interval_px"][1] - s["finite_seed_interval_px"][0])]
        if not matching:
            continue
        start = _endpoint(nodes[seq[0]]["pixels"], axis, rho, edt, True)
        end = _endpoint(nodes[seq[-1]]["pixels"], axis, rho, edt, False)
        path = _representative_path(support, start, end, edt)
        absolute = [[int(x + origin[0]), int(y + origin[1])] for x, y in path]
        support_absolute = [[int(x + origin[0]), int(y + origin[1])] for x, y in sorted(support)]
        near_holes = []
        for h in holes:
            hole_pts = np.asarray(h["white_pixels_px"]) - origin
            projections, offsets = hole_pts @ axis, hole_pts @ normal
            if (np.any((projections >= lo) & (projections <= hi) &
                       (abs(offsets - rho) <= POLICY["band_half_widths"] * width))):
                near_holes.append(h)
        contacts = sorted({q for p in support for q in _neighbors(p)
                           if q not in support and 0 <= q[0] < ink.shape[1]
                           and 0 <= q[1] < ink.shape[0] and ink[q[1], q[0]]})
        reasons = ["INDEPENDENT_SOURCE_OWNERSHIP_NOT_PROVED"]
        if contacts:
            reasons.append("UNASSIGNED_OR_COMPETING_SIDE_SOURCE")
        if near_holes:
            reasons.append("LOCAL_WHITE_HOLE_OR_LOOP_RESPONSIBILITY_UNRESOLVED")
        ends = [_endpoint_evidence(p, support, ink, axis, first, origin, roi, width)
                for p, first in [(start, True), (end, False)]]
        if any(e["crop_censored"] for e in ends):
            reasons.append("CROP_CENSORED_ENDPOINT")
        result.append({
            "candidate_id": "RAWBAND-" + digest(absolute)[:16],
            "status": "PARTIAL_CANDIDATE_SOURCE_OWNERSHIP_UNPROVED",
            "source_path_px": absolute,
            "path_length_px": float(np.linalg.norm(np.diff(np.asarray(path), axis=0), axis=1).sum()),
            "representation": {"kind": "OPEN_LWPOLYLINE_CANDIDATE", "points": absolute,
                               "closed": False, "bulges": [0.0] * len(absolute)},
            "seed_axes": [{"angle_deg": seed["angle_deg"], "normal_offset_local_px": rho,
                           "hough_seeds": matching}],
            "finite_projected_interval_local_px": [lo, hi],
            "section_sequence": seq,
            "section_sequence_competitors_in_same_axis": len(alternatives) - 1,
            "original_ink_support_pixels_px": support_absolute,
            "unassigned_adjacent_source_pixels_px": [[int(x + origin[0]), int(y + origin[1])] for x, y in contacts],
            "original_white_holes_touching_band": near_holes,
            "endpoint_evidence": ends,
            "rejection_reasons": reasons,
            "path_points_all_original_ink": bool(all(ink[y, x] for x, y in path)),
            "path_steps_max_chebyshev_px": int(np.max(np.abs(np.diff(np.asarray(path), axis=0)))),
            "source_path_is_geometry_approval": False,
        })
    return result, axis_summary


def discover(gray, roi):
    began = time.perf_counter()
    source = np.asarray(gray)
    if source.ndim != 2 or source.dtype != np.uint8:
        raise ValueError("SOURCE_MUST_BE_UNMODIFIED_UINT8_GRAYSCALE")
    if len(roi) != 4 or any(int(v) != v for v in roi):
        raise ValueError("ROI_MUST_BE_INTEGER_XYXY")
    x0, y0, x1, y1 = map(int, roi)
    if not (0 <= x0 < x1 <= source.shape[1] and 0 <= y0 < y1 <= source.shape[0]):
        raise ValueError("ROI_OUTSIDE_SOURCE")
    crop = source[y0:y1, x0:x1]
    ink = crop < POLICY["source_threshold"]
    origin = np.array([x0, y0])
    edt = ndimage.distance_transform_edt(ink)
    maxima = (edt == ndimage.maximum_filter(edt, size=3, mode="constant")) & ink
    widths = 2.0 * edt[maxima]
    width = max(POLICY["minimum_estimated_width_px"],
                float(np.median(widths)) if len(widths) else 1.0)
    yy, xx = np.nonzero(ink)
    points = np.column_stack((xx, yy)).astype(float)
    seeds, seed_overflow = _seeds(ink, points, width)
    holes = _holes(ink, origin)
    rows, axes = {}, []
    global_overflow = False
    if not seed_overflow:
        for seed in seeds:
            candidates, summary = _one_axis(ink, points, edt, width, seed, origin, roi, holes)
            axes.append(summary)
            for row in candidates:
                retain_axis_evidence(rows, row)
                if len(rows) > POLICY["maximum_candidate_paths"]:
                    global_overflow = True
                    break
            if global_overflow:
                break
    status = "RESOURCE_LIMIT_CANDIDATES_WITHHELD" if (seed_overflow or global_overflow) else "CANDIDATE_DISCOVERY_ONLY_NO_ADOPTED_OBJECTS"
    if global_overflow:
        rows = {}
    covered = {tuple(p) for row in rows.values() for p in row["source_path_px"]}
    total_ink = {(int(x + x0), int(y + y0)) for x, y in zip(xx, yy)}
    return {
        "schema": SCHEMA, "status": status, "policy": POLICY,
        "policy_sha256": digest(POLICY),
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_shape_yx": list(source.shape), "roi_xyxy_px": list(map(int, roi)),
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "original_crop_array_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
        "estimated_ink_width_px": width, "width_maxima_count": int(maxima.sum()),
        "seed_axes": seeds, "axis_branch_reports": axes,
        "candidates": list(rows.values()), "adopted_objects": [],
        "complete_recovered_objects": 0,
        "unexplained_original_ink_pixels_px": [list(p) for p in sorted(total_ink - covered)],
        "unexplained_ink_note": "Raw pixels outside candidate centre traces; includes stroke thickness and neighbors. This is not an object-ownership residual metric.",
        "original_white_holes": holes,
        "original_source_pixels_modified": False, "old_source_graph_used": False,
        "expensive_OCR_calls": 0, "model_calls": 0,
        "resources": {"seed_axis_overflow": seed_overflow, "candidate_overflow": global_overflow,
                      "axis_branch_overflows": sum(r["status"].startswith("RESOURCE") for r in axes)},
        "environment": {"python": platform.python_version(), "opencv": cv2.__version__,
                        "numpy": np.__version__},
        "wall_seconds": time.perf_counter() - began,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--roi", nargs=4, type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with Image.open(args.input) as im:
        gray = np.array(im.convert("L"))
    result = discover(gray, args.roi)
    result["input_file_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "candidate_count": len(result["candidates"]),
                      "seed_axis_count": len(result["seed_axes"]), "complete_recovered_objects": 0,
                      "wall_seconds": result["wall_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
