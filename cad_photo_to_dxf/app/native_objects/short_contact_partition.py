"""Bounded short glyph groups beside independently adopted source paths.

The source skeleton is partitioned by editing responsibility, not by a proposed
transcription.  Complete adopted paths retain their source pixels.  Their
recorded junction cores may also belong to a compact, complete side glyph.
No sample is painted, no crop edge becomes an endpoint, and no target box or
expected character is an input to discovery.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree

from . import connections
from . import text_regions as base
from .text_contact_adoption import object_binding


POLICY = {
    "version": "adopted-path-complete-short-source-components-v2",
    "source_threshold": 128,
    "glyph_height_px": [8, 70],
    "glyph_width_height_ratio": [0.20, 2.0],
    "maximum_characters": 4,
    "maximum_groups": 24,
    "adjacent_component_gap_heights": 0.60,
    "adjacent_baseline_difference_heights": 0.25,
    "adjacent_height_ratio": [0.60, 1.45],
    "maximum_graphic_normal_px": 3.0,
    "glyph_ink_assignment": "nearest_original_skeleton_then_own_connected_ink_component",
    "shared_junction_core_samples_retained": True,
    "only_adopted_round_to_carrier_contacts": True,
    "new_path_discovery_or_adoption": False,
    "maximum_completion_passes": 1,
    "supported_layout": "horizontal_short_groups_crossed_by_near_vertical_paths",
    "maximum_graphic_horizontal_to_vertical_ratio": 0.25,
    "case_coordinates_or_transcripts": False,
    "original_pixels_added_or_rewritten": False,
    "carrier_shared_return_maximum_height_ratio": 0.60,
    "carrier_shared_span_within_side_glyph_horizontal_extent": True,
    "carrier_source_outside_glyph_minimum_px": 24.0,
    "carrier_attached_glyph_requires_unique_complete_return": True,
    "adjacent_primary_group_gap_uncertainty_px": 1.0,
    "complete_neighbor_component_assigned_to_one_source_group": True,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _inside(box, roi):
    return roi[0] < box[0] < box[2] < roi[2] and roi[1] < box[1] < box[3] < roi[3]


def _bbox(points, pad=0):
    p = np.asarray(points, dtype=float)
    return [int(math.floor(p[:, 0].min())) - pad, int(math.floor(p[:, 1].min())) - pad,
            int(math.ceil(p[:, 0].max())) + 1 + pad, int(math.ceil(p[:, 1].max())) + 1 + pad]


def _overlap(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _mask(runs, box):
    result = np.zeros((box[3] - box[1], box[2] - box[0]), bool)
    for y, a, b in runs:
        if box[1] <= y < box[3]:
            result[y - box[1], max(a, box[0]) - box[0]:min(b, box[2]) - box[0]] = True
    return result


def _component(mask, origin, *, basis, skeleton=None, shared=None, endpoints=None):
    yy, xx = np.nonzero(mask)
    box = [int(xx.min() + origin[0]), int(yy.min() + origin[1]),
           int(xx.max() + 1 + origin[0]), int(yy.max() + 1 + origin[1])]
    return {
        "bbox_xyxy_px": box, "source_role": "FULL_HEIGHT_GLYPH",
        "source_runs_y_x0_x1": base._rle(mask, origin),
        "source_area_px": int(mask.sum()), "source_threshold": POLICY["source_threshold"],
        "source_white_gaps_not_filled": True, "source_component_basis": basis,
        "source_skeleton_points_px": [] if skeleton is None else skeleton,
        "shared_core_points_px": [] if shared is None else shared,
        "original_free_endpoint_points_px": [] if endpoints is None else endpoints,
    }


def _covered_by_formal(component, objects, owning_ids):
    """Do not reclaim an already editable short stroke, text, or symbol."""
    box = component["bbox_xyxy_px"]
    points = np.asarray(component["source_skeleton_points_px"], float)
    if not len(points):
        points = np.asarray([[x,y] for y,a,b in component["source_runs_y_x0_x1"]
                             for x in range(a,b)], float)
    for obj in objects:
        if obj["id"] in owning_ids:
            continue
        kind, g = obj["kind"], obj["geometry"]
        if kind in {"TEXT", "MTEXT", "CIRCULAR_MARKER", "ROOM_LABEL", "TEXT_GROUP"}:
            other = obj.get("bbox_xyxy_px") or g.get("bbox_xyxy_px")
            if kind == "TEXT":
                other = [g["x"], g["y"] - g["height_px"], g["x"] + g["width_px"], g["y"]]
            if other and _overlap(box, other):
                return obj["id"]
        if kind == "LINE" and len(points):
            a, b = np.asarray(g["start"], float), np.asarray(g["end"], float)
            delta = b - a
            if np.dot(delta, delta) <= 0:
                continue
            t = np.clip((points - a) @ delta / np.dot(delta, delta), 0, 1)
            distance = np.linalg.norm(points - (a + t[:, None] * delta), axis=1)
            if np.mean(distance <= 2.0) >= 0.85:
                return obj["id"]
        if kind == "CIRCLE" and len(points):
            distance = np.abs(np.linalg.norm(points-np.asarray(g["center"]),axis=1)-g["radius_px"])
            if np.mean(distance <= 2.0) >= 0.85:
                return obj["id"]
        if kind == "CONNECTION_PATH" and len(points):
            dense = connections._dense_geometry({**g,"bulges":g.get("bulges",[0.0]*len(g["points"]))},0.25)
            if len(dense) and np.mean(cKDTree(dense).query(points)[0]<=2.0)>=0.85:
                return obj["id"]
        if kind == "ARC" and len(points):
            sweep = float(g.get("sweep_deg_image",g["end_deg_image"]-g["start_deg_image"]))
            angles = np.deg2rad(np.linspace(g["start_deg_image"],g["start_deg_image"]+sweep,
                                            max(3,int(math.ceil(abs(sweep)*math.pi/180*g["radius_px"]/.25))+1)))
            dense = np.asarray(g["center"])+g["radius_px"]*np.column_stack((np.cos(angles),np.sin(angles)))
            if np.mean(cKDTree(dense).query(points)[0]<=2.0)>=0.85:
                return obj["id"]
    return None


def _owned_ink(gray, graph, labels, label, box):
    # A context margin prevents another source skeleton outside the glyph's
    # finite box from losing responsibility for its own ink at the boundary.
    origin = graph.origin.astype(int)
    local_box = [max(int(origin[0]), box[0] - 5), max(int(origin[1]), box[1] - 5),
                 min(int(origin[0]) + graph.w, box[2] + 5),
                 min(int(origin[1]) + graph.h, box[3] + 5)]
    x0, y0, x1, y1 = local_box
    slices = (slice(y0 - origin[1], y1 - origin[1]), slice(x0 - origin[0], x1 - origin[0]))
    own = (labels[slices] == label).astype(np.uint8)
    other = (graph.skel[slices] & ~(labels[slices] == label)).astype(np.uint8)
    near_own = cv2.distanceTransform(1 - own, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    near_other = cv2.distanceTransform(1 - other, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    candidate = (gray[y0:y1, x0:x1] < POLICY["source_threshold"]) & (near_own <= near_other + 1e-7)
    _, ink_labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=8)
    own_labels = set(map(int, np.unique(ink_labels[own != 0]))) - {0}
    retained = np.isin(ink_labels, list(own_labels))
    if not np.all(retained[own != 0]):
        raise ValueError("SHORT_GLYPH_OWN_SKELETON_NOT_RETAINED")
    excluded = candidate & ~retained
    return retained, local_box, base._rle(excluded, local_box[:2])


def _carrier_glyph_neighbors(gray, graph, objects, owners, primary):
    """Recover a complete side glyph sharing a bounded span of its receiver.

    A long side body and its short return have original free endpoints. Both
    attach to the same source-proved, independently adopted receiving LINE.
    Their intervening source span and *all* attachment cores remain glyph ink.
    Cutting the whole receiver out of the recognition image is not evidence.
    Multiple possible returns remain unresolved; no transcription is an input.
    """
    by_id = {o["id"]: o for o in objects}
    primary_box = primary["bbox_xyxy_px"]
    primary_height = primary_box[3] - primary_box[1]
    origin = graph.origin.astype(int)
    original_degree = connections._degree(graph.skel)
    recovered, pending, seen = [], [], set()
    for owner in owners:
        if owner["id"] not in primary["independent_path_owner_ids"]:
            continue
        path = owner["source_evidence"]["text_contact_path"]["path"]
        terminal = path["structural_terminal_evidence"]
        carrier = by_id.get(path["required_carrier_id"])
        if (not carrier or carrier["kind"] != "LINE"
                or terminal["carrier_id"] != carrier["id"]
                or terminal["carrier_geometry"] != carrier["geometry"]
                or not terminal["closed_pixel_cells_all_original_ink"]):
            pending.append({"bbox_xyxy_px": primary_box,
                            "reason": "ACTUAL_FINITE_RECEIVER_BINDING_NOT_PROVEN"})
            continue
        points = np.asarray(terminal["carrier_source_path_px"], float)
        key = digest({"id": carrier["id"], "source": points.tolist()})
        if key in seen:
            continue
        seen.add(key)
        if (len(points) < 3 or not np.array_equal(points, np.rint(points))
                or np.max(np.linalg.norm(np.diff(points, axis=0), axis=1)) > math.sqrt(2)+1e-9):
            raise ValueError("SHORT_CONTACT_RECEIVER_SOURCE_IS_NOT_A_CONTINUOUS_ORIGINAL_WALK")
        a = np.asarray(carrier["geometry"]["start"], float)
        delta = np.asarray(carrier["geometry"]["end"], float) - a
        unit = delta / np.linalg.norm(delta)
        # This completion keeps the existing horizontal-group layout scope.
        if abs(unit[1]) > POLICY["maximum_graphic_horizontal_to_vertical_ratio"]*abs(unit[0]):
            continue
        normal = np.array([-unit[1], unit[0]])
        carrier_mask = np.zeros_like(graph.skel, np.uint8)
        local = points.astype(int)-origin
        carrier_mask[local[:, 1], local[:, 0]] = 1
        residual = graph.skel.astype(np.uint8) & ~carrier_mask
        _, labels, stats, _ = cv2.connectedComponentsWithStats(residual, connectivity=8)
        near = cv2.dilate(carrier_mask, np.ones((3, 3), np.uint8)) != 0
        branches = []
        for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
            if h > POLICY["glyph_height_px"][1] or w > 2*POLICY["glyph_height_px"][1]:
                continue
            own = labels[y:y+h, x:x+w] == label
            if not np.any(own & near[y:y+h, x:x+w]):
                continue
            yy, xx = np.nonzero(own)
            skeleton = np.column_stack((xx+x+origin[0], yy+y+origin[1]))
            box = _bbox(skeleton)
            gap = max(primary_box[0]-box[2], box[0]-primary_box[2], 0)
            if gap > POLICY["adjacent_component_gap_heights"]*primary_height:
                continue
            free = own & (original_degree[y:y+h, x:x+w] <= 1)
            fy, fx = np.nonzero(free)
            ends = np.column_stack((fx+x+origin[0], fy+y+origin[1])).tolist()
            if not 1 <= len(ends) <= 8:
                continue
            displacement = (skeleton-a)@normal
            substantial = displacement[np.abs(displacement) > 1.5]
            if not len(substantial) or np.any(substantial > 0) and np.any(substantial < 0):
                continue
            touch = np.flatnonzero(cv2.dilate((labels == label).astype(np.uint8),
                                              np.ones((3, 3), np.uint8))[local[:,1],local[:,0]])
            if not len(touch):
                continue
            branches.append({"label":label,"box":box,"height":h,
                             "points":skeleton,"ends":ends,"touch":touch,
                             "side":int(np.sign(substantial[0]))})
        for body in branches:
            h = body["height"]
            if not (POLICY["adjacent_height_ratio"][0] <= h/primary_height <= POLICY["adjacent_height_ratio"][1]
                    and h >= POLICY["glyph_height_px"][0]):
                continue
            if _overlap(body["box"], primary_box):
                continue
            possible = []
            for tail in branches:
                if (tail is body or tail["side"] != body["side"]
                        or tail["height"] > POLICY["carrier_shared_return_maximum_height_ratio"]*h):
                    continue
                lo = int(min(body["touch"].min(), tail["touch"].min()))
                hi = int(max(body["touch"].max(), tail["touch"].max()))
                span = points[lo:hi+1]
                length = float(np.linalg.norm(np.diff(span,axis=0),axis=1).sum())
                branch_points = np.vstack((body["points"],tail["points"]))
                glyph_projection = (branch_points-a)@unit
                span_projection = (span-a)@unit
                # Attachments above use an eight-neighbor 3x3 footprint. Its
                # exact projection on a tilted carrier is |ux|+|uy|, not one
                # axial pixel. This follows the observed neighborhood itself.
                attachment_projection = float(np.abs(unit).sum())
                if (span_projection.min()<glyph_projection.min()-attachment_projection-1e-9
                        or span_projection.max()>glyph_projection.max()+attachment_projection+1e-9):
                    continue
                intervening = [other["box"] for other in branches if other is not body and other is not tail
                               and np.any((other["touch"] >= lo) & (other["touch"] <= hi))]
                outside = [np.linalg.norm(np.diff(points[:lo+1],axis=0),axis=1).sum(),
                           np.linalg.norm(np.diff(points[hi:],axis=0),axis=1).sum()]
                if min(outside) < POLICY["carrier_source_outside_glyph_minimum_px"]:
                    continue
                branch_labels = {body["label"], tail["label"]}
                existing_branch_owner = False
                for branch in (body,tail):
                    branch_probe = {"bbox_xyxy_px":branch["box"],
                                    "source_skeleton_points_px":branch["points"].tolist()}
                    if _covered_by_formal(branch_probe,objects,{owner["id"],carrier["id"]}):
                        existing_branch_owner = True
                        break
                if existing_branch_owner:
                    continue
                cores = []
                for node in graph.nodes.values():
                    xy = np.rint(graph.xy(node["pixels"])-origin).astype(int)
                    if (np.any(carrier_mask[xy[:,1],xy[:,0]]) and
                            branch_labels.intersection(map(int,labels[xy[:,1],xy[:,0]]))):
                        cores.extend(graph.xy(node["pixels"]).tolist())
                if not cores:
                    continue
                skeleton = np.unique(np.vstack((body["points"],tail["points"],span,cores)).astype(int),axis=0)
                box = _bbox(skeleton)
                width, height = box[2]-box[0], box[3]-box[1]
                if not _inside(box,[int(origin[0]),int(origin[1]),
                                   int(origin[0])+graph.w,int(origin[1])+graph.h]):
                    continue
                if (not POLICY["glyph_width_height_ratio"][0] <= width/height <= POLICY["glyph_width_height_ratio"][1]
                        or abs(box[3]-primary_box[3]) > POLICY["adjacent_baseline_difference_heights"]*primary_height):
                    continue
                glyph_label = len(stats)
                glyph_labels = labels.copy()
                xy = skeleton-origin
                glyph_labels[xy[:,1],xy[:,0]] = glyph_label
                mask, local_box, excluded = _owned_ink(gray,graph,glyph_labels,glyph_label,box)
                c = _component(mask,local_box[:2],basis="complete_carrier_side_body_return_and_shared_source_span",
                               skeleton=skeleton.tolist(),shared=[list(p) for p in sorted(set(map(tuple,cores)))],
                               endpoints=body["ends"]+tail["ends"])
                if _covered_by_formal(c,objects,{owner["id"],carrier["id"]}):
                    continue
                c["nearby_ink_of_other_components_not_claimed"] = excluded
                c["carrier_shared_span_points_px"] = span.tolist()
                c["carrier_contact_evidence"] = {
                    "owner_path_id":owner["id"],"carrier_binding":object_binding(carrier),
                    "carrier_source_path_sha256":digest(points.tolist()),
                    "shared_span_index_range":[lo,hi],"shared_span_length_px":length,
                    "eight_neighbor_attachment_projection_px":attachment_projection,
                    "source_continuation_outside_glyph_px":list(map(float,outside)),
                    "complete_side_body_skeleton_px":body["points"].tolist(),
                    "complete_short_return_skeleton_px":tail["points"].tolist(),
                    "original_free_endpoints_px":body["ends"]+tail["ends"],
                    "all_attachment_core_and_intervening_source_samples_retained":True,
                    "both_branches_on_same_carrier_side":True,
                    "competing_complete_return_count":0,
                    "unassigned_intervening_source_branches":intervening,
                }
                possible.append(c)
            if len(possible) == 1 and not possible[0]["carrier_contact_evidence"]["unassigned_intervening_source_branches"]:
                recovered.append(possible[0])
            else:
                pending.append({"bbox_xyxy_px":body["box"],
                                "reason":"CARRIER_ATTACHED_NEIGHBOR_HAS_NO_UNIQUE_COMPLETE_SOURCE_RETURN",
                                "complete_return_candidates":len(possible)})
    return recovered, pending


def _graphic_crossings(component, owners):
    box = component["bbox_xyxy_px"]
    required = component.get("required_owner_ids")
    glyph_cores = {tuple(p) for p in component.get("shared_core_points_px", [])}
    result = []
    for owner in owners:
        if required is not None and owner["id"] not in required:
            continue
        path = owner["source_evidence"]["text_contact_path"]["path"]
        owner_cores = {tuple(p) for contact in path.get("contact_continuations", [])
                       for p in contact.get("source_core_pixels", [])}
        shared_cores = sorted(glyph_cores & owner_cores)
        if glyph_cores and not shared_cores:
            continue
        points = np.asarray(path["source_path_px"], float)
        inside = ((points[:, 0] >= box[0]) & (points[:, 0] < box[2])
                  & (points[:, 1] >= box[1]) & (points[:, 1] < box[3]))
        indexes = np.flatnonzero(inside)
        if not len(indexes):
            continue
        first, last = int(indexes[0]), int(indexes[-1])
        if first == 0 or last == len(points) - 1:
            continue
        if not np.array_equal(indexes, np.arange(first, last + 1)):
            continue
        before, after = points[first - 1], points[last + 1]
        if before[1] < box[1] and after[1] >= box[3]:
            crossed_sides = ["TOP", "BOTTOM"]
        elif before[1] >= box[3] and after[1] < box[1]:
            crossed_sides = ["BOTTOM", "TOP"]
        else:
            continue
        direction = points[last+1]-points[first-1]
        if abs(direction[0]) > POLICY["maximum_graphic_horizontal_to_vertical_ratio"]*abs(direction[1]):
            continue
        # Genuine independent source terminals inside a glyph cannot be
        # reclassified as an unbounded graphic stroke by changing the crop.
        if any(box[0] <= p[0] < box[2] and box[1] <= p[1] < box[3]
               for p in (points[0], points[-1])):
            continue
        result.append({
            "owner_id": owner["id"], "owner_geometry_sha256": digest(owner["geometry"]),
            "first_inside_index": first, "last_inside_index": last,
            "original_point_before_glyph": points[first - 1].tolist(),
            "original_point_after_glyph": points[last + 1].tolist(),
            "first_original_point_inside": points[first].tolist(),
            "last_original_point_inside": points[last].tolist(),
            "original_complete_path_endpoints": [points[0].tolist(), points[-1].tolist()],
            "source_box_crossed_sides": crossed_sides,
            "single_contiguous_source_visit": True,
            "shared_core_points_used": [list(p) for p in shared_cores],
            "glyph_box_is_not_path_terminal": True,
            "source_continuity_both_sides": True,
            "path_and_glyph_share_only_recorded_source_core": True,
        })
    return result


def _finite_receiver_contacts(raw_box, primary, owners, objects):
    """A continuing glyph-crossing stroke may finish on a proved receiver.

    This is distinct from continuing beyond both raw crop edges. The complete
    glyph is crossed first; the finite receiver lies outside it, has independent
    source on both sides of this raw crop, and is an actual adopted LINE.
    """
    by_id = {o["id"]:o for o in objects}
    result = []
    for crossing in _graphic_crossings(primary,owners):
        owner = by_id[crossing["owner_id"]]
        path = owner["source_evidence"]["text_contact_path"]["path"]
        terminal = path["structural_terminal_evidence"]
        carrier = by_id.get(path["required_carrier_id"])
        if (not carrier or carrier["kind"]!="LINE"
                or carrier["geometry"]!=terminal["carrier_geometry"]
                or carrier["id"]!=terminal["carrier_id"]
                or not terminal["closed_pixel_cells_all_original_ink"]
                or not terminal["all_source_ports_accounted"]
                or terminal["equally_aligned_forward_port_count"]!=0):
            continue
        points = np.asarray(path["source_path_px"],float)
        inside = ((points[:,0]>=raw_box[0]) & (points[:,0]<raw_box[2]) &
                  (points[:,1]>=raw_box[1]) & (points[:,1]<raw_box[3]))
        indexes = np.flatnonzero(inside)
        if (not len(indexes) or indexes[0]==0 or indexes[-1]!=len(points)-1
                or not np.array_equal(indexes,np.arange(indexes[0],len(points)))
                or points[indexes[0]-1,1]>=raw_box[1]):
            continue
        end = np.asarray(terminal["source_contact_point_px"],float)
        glyph_box = primary["bbox_xyxy_px"]
        carrier_points = np.asarray(terminal["carrier_source_path_px"],float)
        if (end[1]<glyph_box[3] or np.linalg.norm(points[-1]-end)>2.0
                or carrier_points[:,0].min()>=raw_box[0]
                or carrier_points[:,0].max()<raw_box[2]
                or min(terminal["carrier_source_arm_lengths_px"])<POLICY["carrier_source_outside_glyph_minimum_px"]):
            continue
        result.append({
            "owner_id":owner["id"],"owner_geometry_sha256":digest(owner["geometry"]),
            "carrier_binding":object_binding(carrier),
            "carrier_source_path_sha256":digest(carrier_points.tolist()),
            "carrier_source_extents_px":_bbox(carrier_points),
            "source_contact_point_px":end.tolist(),
            "first_original_point_inside":points[indexes[0]].tolist(),
            "last_original_point_inside":points[-1].tolist(),
            "original_point_before_crop":points[indexes[0]-1].tolist(),
            "complete_glyph_crossing":crossing,
            "same_word_requires_top_edge_and_actual_receiver_coverage":True,
            "single_contiguous_source_visit":True,
            "path_ends_outside_complete_glyph_on_independent_receiver":True,
            "receiver_source_continues_past_both_horizontal_crop_edges":True,
        })
    return result


def _adjacent_source_group_claims(box, candidates):
    """A complete intervening glyph cannot be copied into two nearby groups.

    Compare original ink gaps to every source-proved crossing glyph on the same
    baseline. This partitions geometry before recognition; no candidate text
    supplies another candidate's answer. Indistinguishable gaps remain pending.
    """
    width,height = box[2]-box[0],box[3]-box[1]
    claims=[]
    for index,candidate in enumerate(candidates):
        other=candidate["component"]["bbox_xyxy_px"]
        other_height=other[3]-other[1]
        if (_overlap(box,other)
                or abs(box[3]-other[3])>POLICY["adjacent_baseline_difference_heights"]*other_height
                or not POLICY["adjacent_height_ratio"][0]<=height/other_height<=POLICY["adjacent_height_ratio"][1]
                or width/height>POLICY["glyph_width_height_ratio"][1]):
            continue
        gap=max(other[0]-box[2],box[0]-other[2],0)
        claims.append((gap,index))
    if not claims:
        return []
    nearest=min(gap for gap,_ in claims)
    return [index for gap,index in claims
            if gap<=nearest+POLICY["adjacent_primary_group_gap_uncertainty_px"]]


def plan_short_contact_text(gray, roi, objects, contact_completion, *, source_graph=None,
                            verify_geometry=True):
    """One finite discovery pass over already adopted paths, without OCR."""
    from .text_contact_audit import verify_contact_plan_source_replay
    from .text_contact_partition import _source_graph

    source = np.asarray(gray)
    plans = contact_completion.get("geometry_plans", {})
    owners, plan_checks, pending = [], {}, []
    for obj in objects:
        proof = obj.get("source_evidence", {}).get("text_contact_path", {})
        path = proof.get("path", {})
        if obj["kind"] != "CONNECTION_PATH" or path.get("path_role") != "ROUND_TO_CARRIER":
            continue
        key = proof.get("plan_sha256")
        plan = plans.get(key)
        if (not isinstance(plan, dict) or digest(plan) != key
                or proof.get("path_sha256") != digest(path)
                or not isinstance(proof.get("path_index"), int)
                or proof["path_index"] >= len(plan["paths"])
                or plan["paths"][proof["path_index"]] != path):
            pending.append({"owner_id": obj["id"], "reason": "ADOPTED_CONTACT_PLAN_OR_PATH_NOT_BOUND"})
            continue
        owners.append(obj)
    result = {"schema": "native-short-contact-source-plan-v1", "policy": deepcopy(POLICY),
              "source_array_sha256": base.source_array_sha256(source), "roi_xyxy_px": list(roi),
              "plans": [], "pending": pending, "adopted_path_bindings": [],
              "geometry_plan_checks": plan_checks, "completion_passes": 1,
              "original_source_pixels_modified": False, "transcription_supplied": False}
    if not owners:
        return result
    context = source_graph or _source_graph(source, roi)
    graph, origin = context.graph, context.graph.origin.astype(int)
    for key in sorted({o["source_evidence"]["text_contact_path"]["plan_sha256"] for o in owners}):
        check = verify_contact_plan_source_replay(source, roi, plans[key], source_graph=context) if verify_geometry else {"pass": True, "diagnostic_only": True}
        plan_checks[key] = check
        if not check.get("pass"):
            raise ValueError("SHORT_CONTACT_OWNER_SOURCE_REPLAY_FAILED:" + str(check.get("reason")))
    result["adopted_path_bindings"] = [object_binding(o) for o in owners]
    removed = np.zeros_like(graph.skel, dtype=np.uint8)
    shared = np.zeros_like(removed)
    for obj in owners:
        path = obj["source_evidence"]["text_contact_path"]["path"]
        points = np.asarray(path["source_path_px"], float)
        if not np.array_equal(points, np.rint(points)):
            raise ValueError("SHORT_CONTACT_REQUIRES_ORIGINAL_INTEGER_PATH_SAMPLES")
        xy = points.astype(int) - origin
        removed[xy[:, 1], xy[:, 0]] = 1
        for contact in path.get("contact_continuations", []):
            p = np.asarray(contact.get("source_core_pixels", []), float)
            if len(p):
                xy = p.astype(int) - origin
                shared[xy[:, 1], xy[:, 0]] = 1
    residual = graph.skel.astype(np.uint8) & ~(removed & ~shared)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(residual, connectivity=8)
    candidates = []
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if not (POLICY["glyph_height_px"][0] <= h <= POLICY["glyph_height_px"][1]
                and POLICY["glyph_width_height_ratio"][0] <= w / h <= POLICY["glyph_width_height_ratio"][1]):
            continue
        own = labels[y:y+h, x:x+w] == label
        if not np.any(own & shared[y:y+h, x:x+w]):
            continue
        box = [int(x + origin[0]), int(y + origin[1]), int(x + w + origin[0]), int(y + h + origin[1])]
        if not _inside(box, roi):
            continue
        yy, xx = np.nonzero(own)
        skeleton = np.column_stack((xx + box[0], yy + box[1])).tolist()
        local_shared = own & (shared[y:y+h, x:x+w] != 0)
        yy, xx = np.nonzero(local_shared)
        cores = np.column_stack((xx + box[0], yy + box[1])).tolist()
        degree = connections._degree(own)
        yy, xx = np.nonzero(own & (degree <= 1) & ~local_shared)
        ends = np.column_stack((xx + box[0], yy + box[1])).tolist()
        if not 1 <= len(ends) <= 8:
            pending.append({"bbox_xyxy_px": box, "reason": "SHORT_GLYPH_HAS_NO_BOUNDED_ORIGINAL_FREE_ENDPOINTS"})
            continue
        mask, local, excluded = _owned_ink(source, graph, labels, label, box)
        component = _component(mask, local[:2], basis="complete_residual_source_skeleton_with_retained_shared_cores",
                               skeleton=skeleton, shared=cores, endpoints=ends)
        component["nearby_ink_of_other_components_not_claimed"] = excluded
        crossings = _graphic_crossings(component, owners)
        if not crossings:
            pending.append({"bbox_xyxy_px": box, "reason": "GRAPHIC_STROKE_HAS_NO_INDEPENDENT_CONTINUATION_BOTH_SIDES"})
            continue
        component["independent_path_owner_ids"] = [c["owner_id"] for c in crossings]
        already = _covered_by_formal(component, objects, {o["id"] for o in owners})
        if already:
            pending.append({"bbox_xyxy_px": box, "reason": "SOURCE_COMPONENT_ALREADY_HAS_FORMAL_EDITOR", "owner_id": already})
            continue
        candidates.append({"component": component, "crossings": crossings})
    # Adjacent complete original components, such as a smaller digit, can
    # join the group without borrowing any of the new target transcriptions.
    x0, y0, x1, y1 = map(int, roi)
    _, original_labels, original_stats, _ = cv2.connectedComponentsWithStats(
        (source[y0:y1, x0:x1] < POLICY["source_threshold"]).astype(np.uint8), connectivity=8)
    for candidate_index,candidate in enumerate(candidates[:POLICY["maximum_groups"]]):
        primary = candidate["component"]
        members = [primary]
        box = primary["bbox_xyxy_px"]
        height = box[3] - box[1]
        carrier_neighbors, carrier_pending = _carrier_glyph_neighbors(source,graph,objects,owners,primary)
        if carrier_pending:
            pending.extend(carrier_pending)
            pending.append({"bbox_xyxy_px":box,
                            "reason":"COMPLETE_ADJACENT_CARRIER_GLYPH_UNRESOLVED_NO_PREFIX_ADOPTED"})
            continue
        ambiguous_neighbor = False
        for _ in range(POLICY["maximum_characters"]):
            group = base._box_union([c["bbox_xyxy_px"] for c in members])
            neighbors = []
            for label, (x, y, w, h, area) in enumerate(original_stats[1:], 1):
                b = [int(x+x0), int(y+y0), int(x+w+x0), int(y+h+y0)]
                if not _inside(b, roi) or any(_overlap(b, c["bbox_xyxy_px"]) for c in members):
                    continue
                gap = max(group[0]-b[2], b[0]-group[2], 0)
                if (gap > POLICY["adjacent_component_gap_heights"] * height
                        or abs(b[3]-box[3]) > POLICY["adjacent_baseline_difference_heights"] * height
                        or not POLICY["adjacent_height_ratio"][0] <= h/height <= POLICY["adjacent_height_ratio"][1]
                        or w/h > POLICY["glyph_width_height_ratio"][1]):
                    continue
                claims=_adjacent_source_group_claims(b,candidates)
                if candidate_index not in claims:
                    continue
                if len(claims)!=1:
                    ambiguous_neighbor=True
                    continue
                own = original_labels[y:y+h, x:x+w] == label
                c = _component(own, b[:2], basis="complete_disconnected_original_source_component")
                if _covered_by_formal(c, objects, set()):
                    continue
                neighbors.append((gap, b[0], c))
            for c in carrier_neighbors:
                b = c["bbox_xyxy_px"]
                if any(_overlap(b, member["bbox_xyxy_px"]) for member in members):
                    continue
                gap = max(group[0]-b[2],b[0]-group[2],0)
                if gap <= POLICY["adjacent_component_gap_heights"]*height:
                    claims=_adjacent_source_group_claims(b,candidates)
                    if candidate_index not in claims:
                        continue
                    if len(claims)!=1:
                        ambiguous_neighbor=True
                        continue
                    neighbors.append((gap,b[0],c))
            if not neighbors:
                break
            members.append(min(neighbors, key=lambda r:(r[0],r[1]))[2])
        if ambiguous_neighbor:
            pending.append({"bbox_xyxy_px":base._box_union([c["bbox_xyxy_px"] for c in members]),
                            "reason":"COMPLETE_NEIGHBOR_HAS_COMPETING_SOURCE_GROUPS_NO_PREFIX_ADOPTED"})
            continue
        if len(members) > POLICY["maximum_characters"]:
            pending.append({"bbox_xyxy_px":base._box_union([c["bbox_xyxy_px"] for c in members]),
                            "reason":"COMPLETE_SHORT_GROUP_EXCEEDS_CHARACTER_BUDGET_NO_PREFIX_ADOPTED"})
            continue
        members.sort(key=lambda c:c["bbox_xyxy_px"][0])
        box = base._box_union([c["bbox_xyxy_px"] for c in members])
        runs = [r for c in members for r in c["source_runs_y_x0_x1"]]
        support = _mask(runs, box)
        original = source[box[1]:box[3], box[0]:box[2]]
        excluded = (original < POLICY["source_threshold"]) & ~support
        core_mask = np.zeros_like(support,np.uint8)
        for member in members:
            for x,y in member["shared_core_points_px"] + member.get("carrier_shared_span_points_px",[]):
                if box[0]<=x<box[2] and box[1]<=y<box[3]:
                    core_mask[int(y)-box[1],int(x)-box[0]]=1
        shared_ink = support & (cv2.dilate(core_mask,np.ones((3,3),np.uint8)) != 0)
        path_mask = np.zeros_like(support, np.uint8)
        for owner in owners:
            p = np.asarray(owner["source_evidence"]["text_contact_path"]["path"]["source_path_px"])
            cv2.polylines(path_mask, [np.rint(p-box[:2]).astype(np.int32)], False, 1,
                          thickness=int(2*POLICY["maximum_graphic_normal_px"]+1))
        carrier_contacts = [c["carrier_contact_evidence"] for c in members if "carrier_contact_evidence" in c]
        for proof in carrier_contacts:
            owner = next(o for o in owners if o["id"]==proof["owner_path_id"])
            p = np.asarray(owner["source_evidence"]["text_contact_path"]["path"][
                "structural_terminal_evidence"]["carrier_source_path_px"])
            cv2.polylines(path_mask,[np.rint(p-box[:2]).astype(np.int32)],False,1,
                          thickness=int(2*POLICY["maximum_graphic_normal_px"]+1))
        if np.any(excluded & (path_mask == 0)):
            pending.append({"bbox_xyxy_px": box, "reason": "UNASSIGNED_ORIGINAL_INK_INSIDE_SHORT_GROUP"})
            continue
        pad = int(math.ceil(height))
        context_box = [max(roi[0],box[0]-pad),max(roi[1],box[1]-pad),
                       min(roi[2],box[2]+pad),min(roi[3],box[3]+pad)]
        crop_pad = max(2, int(math.ceil(0.08*height)))
        raw_box = [max(roi[0],box[0]-crop_pad),max(roi[1],box[1]-crop_pad),
                   min(roi[2],box[2]+crop_pad),min(roi[3],box[3]+crop_pad)]
        partition = {"schema": "complete-short-contact-group-partition-v1",
                     "bbox_xyxy_px": box, "components": members,
                     "source_support_runs_y_x0_x1": base._rle(support,box[:2]),
                     "shared_contact_runs_y_x0_x1": base._rle(shared_ink,box[:2]),
                     "shared_ink_basis":"original_glyph_ink_within_one_pixel_of_recorded_junction_core",
                     "excluded_independent_graphic_runs_y_x0_x1": base._rle(excluded,box[:2]),
                     "source_crop_array_sha256": base.source_array_sha256(original),
                     "context_bbox_xyxy_px": context_box,
                     "context_array_sha256": base.source_array_sha256(source[context_box[1]:context_box[3],context_box[0]:context_box[2]]),
                     "raw_original_bbox_xyxy_px": raw_box,
                     "graphic_crossings": candidate["crossings"],
                     "raw_context_graphic_continuations":_graphic_crossings({
                         "bbox_xyxy_px":raw_box,
                         "shared_core_points_px":primary["shared_core_points_px"],
                         "required_owner_ids":primary["independent_path_owner_ids"]},owners),
                     "all_side_glyph_skeleton_and_shared_core_samples_retained": True,
                     "original_source_pixels_modified": False,
                     "derived_view_alone_proves_transcription": False,
                     "independent_graphics_require_separate_adoption": True}
        if carrier_contacts:
            partition["carrier_contact_evidence"] = carrier_contacts
            partition["shared_ink_basis"] = "original_glyph_ink_at_recorded_cores_and_complete_bounded_shared_carrier_spans"
        finite_contacts = _finite_receiver_contacts(raw_box,primary,owners,objects)
        if finite_contacts:
            partition["raw_context_finite_receiver_contacts"] = finite_contacts
        result["plans"].append({"id":"SCT-"+digest({"source":result["source_array_sha256"],"bbox":box})[:12],
                                "source_partition":partition})
    result["plans"].sort(key=lambda p:(p["source_partition"]["bbox_xyxy_px"][1],p["source_partition"]["bbox_xyxy_px"][0]))
    return result


def recognition_view(gray, partition, component_index=None, *, original=False):
    """Keep original intensities; the ownership view only excludes other ink."""
    if original:
        box = partition["raw_original_bbox_xyxy_px"]
        return np.ascontiguousarray(gray[box[1]:box[3],box[0]:box[2]]), box
    if component_index is None:
        box, runs = partition["bbox_xyxy_px"], partition["source_support_runs_y_x0_x1"]
    else:
        component = partition["components"][component_index]
        box, runs = component["bbox_xyxy_px"], component["source_runs_y_x0_x1"]
    source = gray[box[1]:box[3],box[0]:box[2]]
    return np.where(_mask(runs,box),source,255).astype(np.uint8), box
