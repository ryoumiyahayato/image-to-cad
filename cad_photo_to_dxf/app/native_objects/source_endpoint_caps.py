"""Restore a thinned endpoint only inside one bounded original-ink tube.

The raster is never changed. Original skeleton vertices and adjacencies remain
unchanged; only a simple terminal extension on existing source ink is allowed.
A fork, hole, white gap, nearby skeleton, unstable width or missing white cap
keeps the original endpoint. This is an observation repair, not CAD adoption.
"""

from __future__ import annotations

import hashlib
import heapq
import math

import cv2
import numpy as np


POLICY = {
    "version": "bounded-original-ink-terminal-tube-v1",
    "maximum_extension_px": 12.0,
    "already_adequate_cap_px": 3.0,
    "tangent_source_span_px": 8.0,
    "maximum_lateral_stroke_radii": 1.6,
    "raster_lateral_allowance_px": 0.5,
    "maximum_cross_section_gap_px": 1.5,
    "white_cap_depth_px": 2.0,
    "source_pixels_modified": False,
    "original_skeleton_adjacencies_removed": False,
    "gap_closing_or_branch_pruning": False,
}


def _sha(array):
    return hashlib.sha256(np.ascontiguousarray(array, dtype=np.uint8).tobytes()).hexdigest()


def _neighbors(skeleton, point):
    y, x = point
    height, width = skeleton.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            yy, xx = y + dy, x + dx
            if not (0 <= yy < height and 0 <= xx < width) or not skeleton[yy, xx]:
                continue
            if dx and dy and (skeleton[y + dy, x] or skeleton[y, x + dx]):
                continue
            yield yy, xx


def _degree(skeleton):
    height, width = skeleton.shape
    padded = np.pad(skeleton, 1)
    degree = np.zeros(skeleton.shape, np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            adjacent = padded[1 + dy:1 + dy + height, 1 + dx:1 + dx + width].copy()
            if dx and dy:
                adjacent &= ~(padded[1 + dy:1 + dy + height, 1:1 + width]
                              | padded[1:1 + height, 1 + dx:1 + dx + width])
            degree += adjacent
    return degree


def _tail(skeleton, endpoint):
    points, length = [endpoint], 0.0
    while length < POLICY["tangent_source_span_px"]:
        choices = [point for point in _neighbors(skeleton, points[-1])
                   if len(points) == 1 or point != points[-2]]
        if len(choices) != 1 or choices[0] in points:
            return None
        length += math.dist(points[-1], choices[0])
        points.append(choices[0])
    xy = np.asarray([[x, y] for y, x in points], float)
    _, _, axes = np.linalg.svd(xy - xy.mean(axis=0))
    outward = axes[0]
    if outward @ (xy[0] - xy[-1]) < 0:
        outward = -outward
    return points, outward


def _topology_unchanged(current, path):
    refined = current.copy()
    for point in path:
        refined[point] = True
    endpoint = path[0]
    affected = {point for added in path[1:] for point in _neighbors(refined, added)
                if current[point]}
    for point in affected:
        before, after = set(_neighbors(current, point)), set(_neighbors(refined, point))
        if point == endpoint:
            if after != before | {path[1]}:
                return None
        elif after != before:
            return None
    for index, point in enumerate(path[1:], 1):
        expected = {path[index - 1]}
        if index + 1 < len(path):
            expected.add(path[index + 1])
        if set(_neighbors(refined, point)) != expected:
            return None
    return refined


def _extension(skeleton, ink, distance, endpoint):
    tail = _tail(skeleton, endpoint)
    if tail is None:
        return None, "NO_UNIQUE_EXISTING_TERMINAL_TANGENT", {}
    points, outward = tail
    y, x = endpoint
    radius = float(np.median([distance[point] for point in points[1:]]))
    if radius < 0.5:
        return None, "NO_STABLE_SOURCE_STROKE_RADIUS", {}
    extent = int(math.ceil(POLICY["maximum_extension_px"] + 6))
    y0, x0 = max(0, y - extent), max(0, x - extent)
    y1, x1 = min(ink.shape[0], y + extent + 1), min(ink.shape[1], x + extent + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    delta = np.stack((xx - x, yy - y), axis=-1)
    longitudinal = delta @ outward
    normal = np.array([-outward[1], outward[0]])
    lateral = delta @ normal
    forward = ink[y0:y1, x0:x1] & (longitudinal >= -0.5)
    _, labels = cv2.connectedComponents(forward.astype(np.uint8), connectivity=8)
    label = int(labels[y - y0, x - x0])
    if not label:
        return None, "ENDPOINT_NOT_ON_ORIGINAL_INK", {}
    component = labels == label
    maximum = float(longitudinal[component].max())
    proof = {"original_endpoint_xy_px": [x, y], "outward_source_tangent": outward.tolist(),
             "original_tail_xy_px": [[px, py] for py, px in points],
             "reference_source_stroke_radius_px": radius, "source_forward_extent_px": maximum}
    if maximum <= POLICY["already_adequate_cap_px"]:
        return None, "ORIGINAL_CAP_ALREADY_WITHIN_UNCHANGED_TOLERANCE", proof
    if maximum > POLICY["maximum_extension_px"] or any((component[0].any(), component[-1].any(), component[:, 0].any(), component[:, -1].any())):
        return None, "SOURCE_EXTENSION_NOT_BOUNDED_BY_LOCAL_CAP", proof
    if float(np.abs(lateral[component]).max()) > radius * POLICY["maximum_lateral_stroke_radii"] + POLICY["raster_lateral_allowance_px"]:
        return None, "SOURCE_TUBE_WIDENS_OR_DIVERGES", proof
    _, hierarchy = cv2.findContours(component.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is not None and any(parent >= 0 for parent in hierarchy[0, :, 3]):
        return None, "SOURCE_WHITE_HOLE_OR_LOOP_RETAINED", proof
    bins = np.floor(longitudinal + 0.5).astype(int)
    local_distance = distance[y0:y1, x0:x1]
    sections = []
    for index in range(max(1, int(math.floor(maximum + 0.5))) + 1):
        section = component & (bins == index)
        if not section.any():
            return None, "NO_CONTINUOUS_ORIGINAL_INK_CROSS_SECTION", proof
        values = np.sort(lateral[section])
        ridge = np.sort(lateral[section & (local_distance >= float(local_distance[section].max()) - 1e-6)])
        if (len(values) > 1 and float(np.diff(values).max()) > POLICY["maximum_cross_section_gap_px"]
                or len(ridge) > 1 and float(np.diff(ridge).max()) > POLICY["maximum_cross_section_gap_px"]):
            return None, "MULTIPLE_SOURCE_RIDGES_OR_BRANCHES", proof
        sections.append({"longitudinal_bin": index, "source_lateral_range_px": [float(values[0]), float(values[-1])],
                         "ridge_lateral_range_px": [float(ridge[0]), float(ridge[-1])]})
    band = ((longitudinal > maximum + 0.75)
            & (longitudinal <= maximum + 0.75 + POLICY["white_cap_depth_px"])
            & (np.abs(lateral) <= radius + 0.75))
    if not band.any() or np.any(ink[y0:y1, x0:x1][band]):
        return None, "NO_UNAMBIGUOUS_ORIGINAL_WHITE_TERMINAL_CAP", proof
    existing = skeleton[y0:y1, x0:x1] & component & (longitudinal > 0.1)
    if existing.any():
        return None, "FORWARD_INK_ALREADY_HAS_ANOTHER_SKELETON", proof
    tips = np.argwhere(component & (longitudinal >= maximum - 0.75))
    target_local = min((tuple(point) for point in tips),
                       key=lambda point: (-float(local_distance[point]), abs(float(lateral[point])),
                                          -float(longitudinal[point]), point))
    target = (int(target_local[0]) + y0, int(target_local[1]) + x0)
    allowed = {(int(py + y0), int(px + x0)) for py, px in np.argwhere(component & (longitudinal >= -1e-9))}
    queue = [(0.0, endpoint)]
    costs, previous = {endpoint: 0.0}, {}
    while queue:
        cost, point = heapq.heappop(queue)
        if cost != costs.get(point):
            continue
        if point == target:
            break
        py, px = point
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                neighbor = (py + dy, px + dx)
                if neighbor not in allowed or np.array([dx, dy]) @ outward <= 0.1:
                    continue
                penalty = max(0., radius - float(distance[neighbor])) / radius
                total = cost + math.hypot(dx, dy) * (1 + penalty * penalty)
                if total < costs.get(neighbor, float("inf")) - 1e-12:
                    costs[neighbor], previous[neighbor] = total, point
                    heapq.heappush(queue, (total, neighbor))
    if target not in costs:
        return None, "NO_MONOTONE_SOURCE_INK_RIDGE_PATH", proof
    path = [target]
    while path[-1] != endpoint:
        path.append(previous[path[-1]])
    path.reverse()
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    if length > POLICY["maximum_extension_px"]:
        return None, "SOURCE_RIDGE_EXTENSION_LENGTH_EXCEEDS_BOUND", proof
    if _topology_unchanged(skeleton, path) is None:
        return None, "EXTENSION_WOULD_CHANGE_OLD_ADJACENCY_OR_CREATE_BRANCH", proof
    proof.update(source_cross_sections=sections, white_cap_original_pixel_count=int(band.sum()),
                 source_ridge_xy_px=[[px, py] for py, px in path], extension_length_px=length,
                 all_added_points_on_original_ink=True, old_skeleton_vertices_and_adjacencies_preserved=True,
                 no_gap_filled=True, no_branch_pruned=True)
    return path, "BOUNDED_ORIGINAL_SOURCE_ENDPOINT_RESTORED", proof


def restore_source_endpoint_caps(skel, source_ink, origin, permitted_boxes):
    """Return a new skeleton and a replayable evidence record; never edit ink."""
    skel, ink = np.asarray(skel, bool), np.asarray(source_ink, bool)
    if skel.shape != ink.shape or skel.ndim != 2 or np.any(skel & ~ink):
        raise ValueError("SOURCE_ENDPOINT_CAP_INPUT_NOT_ON_ORIGINAL_INK")
    result = skel.copy()
    evidence = {"schema": "source-endpoint-cap-restoration-v1", "policy": dict(POLICY),
                "origin_xy_px": list(map(float, origin)), "original_skeleton_sha256": _sha(skel),
                "original_ink_sha256": _sha(ink), "restored": [], "rejected": [],
                "source_pixels_modified": False, "geometry_adoption_authorized": False}
    if not permitted_boxes:
        evidence["refined_skeleton_sha256"] = _sha(result)
        return result, evidence
    distance = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    endpoints = np.argwhere(skel & (_degree(skel) == 1))
    for y, x in endpoints:
        endpoint = (int(y), int(x))
        world = [float(x + origin[0]), float(y + origin[1])]
        applicable = [box for box in permitted_boxes if box[0] <= world[0] < box[2] and box[1] <= world[1] < box[3]]
        if not applicable:
            continue
        path, reason, proof = _extension(result, ink, distance, endpoint)
        proof.update(decision=reason, original_endpoint_source_xy_px=world)
        if path:
            source_points = [[float(px + origin[0]), float(py + origin[1])] for py, px in path]
            if not any(all(box[0] <= px < box[2] and box[1] <= py < box[3] for px, py in source_points) for box in applicable):
                proof["decision"] = "ORIGINAL_CAP_EXTENDS_OUTSIDE_BOUND_CANDIDATE"
                path = None
            else:
                result = _topology_unchanged(result, path)
                proof["restored_path_source_xy_px"] = source_points
                evidence["restored"].append(proof)
        if not path and reason != "ORIGINAL_CAP_ALREADY_WITHIN_UNCHANGED_TOLERANCE":
            evidence["rejected"].append(proof)
    assert np.all(result[skel]) and not np.any(result & ~ink)
    evidence["refined_skeleton_sha256"] = _sha(result)
    evidence["added_original_ink_skeleton_pixels"] = int((result & ~skel).sum())
    return result, evidence
