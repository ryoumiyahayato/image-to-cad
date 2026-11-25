"""Whole source paths through shared ink to independently supported straight edges.

The graph and all source branches are retained.  This planner has no character,
case, coordinate or engineering-semantic answer.  It licenses one reciprocal
continuation at a time and a port-specific terminal with a separate carrier.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from . import connections as paths
from . import text_contact_geometry as contact
from .contracts import stable_id
from .circle_endpoint_contacts import (
    POLICY as CIRCLE_CONTACT_POLICY,
    _port_indices,
    _segment_cells,
)
from .circular_markers import verify_circle_source_evidence


SCHEMA = "source-structure-contact-path-plan-v1"
POLICY = {
    "version": "reciprocal-source-contact-to-independent-carrier-v1",
    "minimum_direction_span_px": 4.0,
    "direction_span_px": 14.0,
    "maximum_direction_depth": 8,
    "maximum_direction_states": 64,
    "maximum_pair_deviation_deg": 20.0,
    "minimum_pair_margin_deg": 18.0,
    "minimum_carrier_arm_px": 24.0,
    "maximum_carrier_pair_deviation_deg": 8.0,
    "minimum_arrival_carrier_angle_deg": 60.0,
    "maximum_carrier_normal_px": 1.5,
    "maximum_carrier_owner_normal_px": 2.0,
    "maximum_carrier_owner_angle_deg": 3.0,
    "carrier_owner_source_normal_px": 1.0,
    "carrier_owner_source_fraction_min": 0.98,
    "parallel_witness_offset_px": [8, 40],
    "parallel_witness_minimum_span_px": 40.0,
    "parallel_witness_minimum_fraction": 0.60,
    "maximum_corner_turn_deviation_deg": 25.0,
    "minimum_corner_return_span_px": 6.0,
    "maximum_route_edges": 100,
    "minimum_path_length_px": 50.0,
    "maximum_path_length_px": 2400.0,
    "maximum_control_vertices": 256,
    "minimum_shared_contact_count": 1,
    "original_source_pixels_modified": False,
    "terminal_requires_independent_carrier": True,
    "start_requires_unique_formal_source_verified_circle": True,
    "reverse_trace_must_agree": True,
}

# These are the original geometry observations consumed by the existing circle
# verifier.  Character approvals and later endpoint reviews confer no authority
# on a boundary, and are deliberately outside this geometry replay input.
CIRCLE_SOURCE_FIELDS = (
    "kind",
    "coordinate_system",
    "policy",
    "crop_bbox_xyxy_px",
    "crop_sha256",
    "source_size_px",
    "roi_xyxy_px",
    "source_pixels_modified",
    "ring_geometry",
    "ring_support_runs_y_x0_x1",
    "interior_support_runs_y_x0_x1",
    "ring_source_pixels",
    "interior_source_pixels",
    "glyph_bbox_xyxy_px",
    "interior_component_count",
    "interior_connected_to_boundary",
    "interior_is_complete_separate_components",
    "contact_ports",
)


def _angle(a, b):
    return math.degrees(math.acos(float(np.clip(np.asarray(a) @ np.asarray(b), -1, 1))))


def _unit(v):
    return np.asarray(v, float) / max(float(np.linalg.norm(v)), 1e-12)


def _bindings(prior_objects):
    return [
        {k: obj[k] for k in ("id", "kind", "layer", "geometry")}
        for obj in sorted(prior_objects, key=lambda obj: obj["id"])
    ]


def circle_source_bindings(prior_objects):
    """Freeze minimal source certificates, separately from native ownership."""
    return [
        {
            "id": obj["id"],
            "source_evidence": {
                key: deepcopy(obj.get("source_evidence", {}).get(key))
                for key in CIRCLE_SOURCE_FIELDS
            },
        }
        for obj in sorted(prior_objects, key=lambda obj: obj["id"])
        if obj["kind"] in ("CIRCLE", "CIRCULAR_MARKER")
    ]


def _verified_start_circles(gray, roi, bindings, certificates):
    prior = {obj["id"]: obj for obj in bindings}
    verified = []
    for certificate in certificates:
        obj = {
            **prior[certificate["id"]],
            "source_evidence": certificate["source_evidence"],
        }
        if (
            obj["source_evidence"].get("source_pixels_modified") is False
            and verify_circle_source_evidence(gray, roi, obj)["pass"]
        ):
            verified.append(obj)
    return verified


def _starting_circle(context, node_id, port, verified_circles, certificates):
    """Bind an observed graph arrival to one actually owned source-proved ring.

    A round proposal alone cannot complete a path: it may have failed the
    stricter circular boundary fit.  Matching also requires the original
    external graph prefix to overlap one measured source contact port, rather
    than selecting whichever native circle is nearest.
    """
    graph = context.graph
    round_id = graph.nodes[node_id]["terminal"]["round_id"]
    observed = next(row for row in context.rounds if row["id"] == round_id)
    prefix = graph.xy(graph.oriented(port)).tolist()
    native_prefix = {
        "kind": "CONNECTION_PATH",
        "geometry": {"points": prefix, "bulges": [0.0] * len(prefix), "closed": False},
    }
    matches = []
    for obj in verified_circles:
        geometry = obj["geometry"].get("circle_geometry", obj["geometry"])
        evidence = obj["source_evidence"]
        width = float(evidence["ring_geometry"]["stroke_width_px"])
        allowance = (
            width / 2 + CIRCLE_CONTACT_POLICY["existing_native_fit_allowance_px"]
        )
        center_distance = float(
            np.linalg.norm(np.asarray(observed["center"]) - geometry["center"])
        )
        radial_offset = float(
            geometry["radius_px"] - observed["inner_boundary_radius_px"]
        )
        if center_distance > allowance or not 0 < radial_offset <= width + allowance:
            continue
        source_ports = _port_indices(native_prefix, 0, obj)
        if len(source_ports) != 1:
            continue
        certificate = next(row for row in certificates if row["id"] == obj["id"])
        matches.append(
            {
                "circle_id": obj["id"],
                "source_graph_round_id": round_id,
                "source_graph_node_id": node_id,
                "incoming_source_graph_port": list(port),
                "observed_circle_contact_port_index": source_ports[0],
                "circle_source_binding_sha256": _digest(certificate),
                "circle_object_binding_sha256": _digest(_bindings([obj])[0]),
                "observed_round_center_distance_px": center_distance,
                "measured_radius_minus_observed_inner_radius_px": radial_offset,
                "measured_ring_stroke_width_px": width,
                "formal_circle_original_source_reverified": True,
                "original_graph_prefix_matches_measured_circle_source_port": True,
            }
        )
    if len(matches) != 1:
        return {
            "pass": False,
            "reason": "START_CIRCLE_BINDING_AMBIGUOUS"
            if matches
            else "START_CIRCLE_NOT_SOURCE_VERIFIED",
            "source_graph_round_id": round_id,
            "source_graph_node_id": node_id,
            "incoming_source_graph_port": list(port),
            "matching_verified_circle_ids": [row["circle_id"] for row in matches],
        }
    return {"pass": True, **matches[0]}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _members(objects):
    for obj in objects:
        if obj["kind"] == "LINE":
            yield obj["id"], None, obj["geometry"]
        for index, member in enumerate(obj["geometry"].get("members", [])):
            if member["kind"] == "LINE":
                yield obj["id"], index, member["geometry"]


def _arm(graph, port):
    """Observe the finite first straight run, including its actual return bend."""
    raw = graph.xy(graph.oriented(port))
    if len(raw) < 10:
        return None
    span = np.r_[0.0, np.linalg.norm(np.diff(raw, axis=0), axis=1).cumsum()]
    k = min(len(raw) - 1, int(np.searchsorted(span, POLICY["minimum_carrier_arm_px"])))
    if span[k] < POLICY["minimum_carrier_arm_px"]:
        return None
    direction = _unit(raw[k] - raw[0])
    normal = np.array([-direction[1], direction[0]])
    residual = np.abs((raw - raw[0]) @ normal)
    if residual[: k + 1].max() > POLICY["maximum_carrier_normal_px"]:
        return None
    end = k
    for j in range(k + 1, len(raw)):
        if residual[j] > POLICY["maximum_carrier_normal_px"]:
            break
        end = j
    prefix = raw[: end + 1]
    after = raw[end:]
    corner = None
    returns = [after]
    if (
        len(after) > 1
        and paths._length(after) < POLICY["minimum_corner_return_span_px"]
    ):
        # A real corner can lie just before a second source junction.  Observe
        # every continuing branch there instead of treating graph segmentation
        # as the end of the original stroke.
        end_nid = graph.edges[port[0]]["nodes"][1 - port[1]]
        for following in graph.nodes[end_nid]["edges"]:
            if following[0] == port[0]:
                continue
            tail = graph.oriented(following)
            try:
                bridge = contact._core_route(
                    graph, end_nid, graph.oriented(port)[-1], tail[0]
                )
            except ValueError:
                continue
            returns.append(np.vstack((after, graph.xy(bridge[1:] + tail[1:]))))
    proofs = []
    observed_return_count = 0
    for after in returns:
        if len(after) <= 1:
            continue
        tail_span = np.r_[0.0, np.linalg.norm(np.diff(after, axis=0), axis=1).cumsum()]
        q = min(
            len(after) - 1,
            int(np.searchsorted(tail_span, POLICY["minimum_corner_return_span_px"])),
        )
        if tail_span[q] >= POLICY["minimum_corner_return_span_px"]:
            observed_return_count += 1
            turn = _angle(direction, _unit(after[q] - after[0]))
            if abs(turn - 90.0) <= POLICY["maximum_corner_turn_deviation_deg"]:
                proofs.append(
                    {
                        "source_points_px": after[: q + 1].tolist(),
                        "turn_deg": turn,
                        "return_span_px": float(tail_span[q]),
                    }
                )
    if proofs and len(proofs) == observed_return_count:
        corner = {
            **proofs[0],
            "source_return_alternatives": proofs,
            "all_observed_returns_turn_away_from_carrier": True,
        }
    return {
        "port": list(port),
        "pixels": graph.oriented(port)[: end + 1],
        "points": prefix,
        "direction": direction,
        "length_px": float(span[end]),
        "corner": corner,
    }


def _source_parallel_witness(graph, a, b):
    vector = np.asarray(b) - a
    length = float(np.linalg.norm(vector))
    direction = vector / length
    normal = np.array([-direction[1], direction[0]])
    steps = np.arange(0, length + 0.01, 1.0)
    best = None
    lo, hi = POLICY["parallel_witness_offset_px"]
    for signed_offset in list(range(-hi, -lo + 1)) + list(range(lo, hi + 1)):
        points = a + steps[:, None] * direction + signed_offset * normal
        hits = np.zeros(len(points), bool)
        for delta in (-1, 0, 1):
            q = np.rint(points + delta * normal - graph.origin).astype(int)
            valid = (
                (q[:, 0] >= 0)
                & (q[:, 0] < graph.w)
                & (q[:, 1] >= 0)
                & (q[:, 1] < graph.h)
            )
            hits[valid] |= graph.source_ink[q[valid, 1], q[valid, 0]]
        starts = np.flatnonzero(hits & ~np.r_[False, hits[:-1]])
        ends = np.flatnonzero(hits & ~np.r_[hits[1:], False])
        if not len(starts):
            continue
        i = int(np.argmax(ends - starts))
        left, right = int(starts[i]), int(ends[i])
        run = float(right - left)
        if (
            run < POLICY["parallel_witness_minimum_span_px"]
            or run / length < POLICY["parallel_witness_minimum_fraction"]
        ):
            continue
        row = {
            "signed_normal_offset_px": signed_offset,
            "continuous_span_px": run,
            "carrier_fraction": run / length,
            "source_start_px": points[left].tolist(),
            "source_end_px": points[right].tolist(),
            "normal_search_px": 1,
            "original_ink_continuous_at_every_station": True,
        }
        if best is None or (run, -abs(signed_offset)) > (
            best[0],
            -abs(best[1]["signed_normal_offset_px"]),
        ):
            best = (run, row)
    return None if best is None else best[1]


def _carrier_candidates(graph, prior_objects):
    carriers, pending = {}, []
    prior_lines = list(_members(prior_objects))
    for nid, node in graph.nodes.items():
        ports = node["edges"]
        if node["terminal"] or len(ports) != 3 or node["core_topology"]["cycle_rank"]:
            continue
        arms = {port: _arm(graph, port) for port in ports}
        candidates = []
        for i, a in enumerate(ports):
            for b in ports[i + 1 :]:
                if arms[a] is None or arms[b] is None:
                    continue
                deviation = _angle(arms[a]["direction"], -arms[b]["direction"])
                if deviation <= POLICY["maximum_carrier_pair_deviation_deg"]:
                    candidates.append((deviation, a, b))
        if len(candidates) != 1:
            continue
        deviation, a, b = candidates[0]
        arriving = next(p for p in ports if p not in (a, b))
        arrival_points = graph.xy(graph.oriented(arriving))
        if len(arrival_points) < 3:
            continue
        arrival_direction = _unit(
            arrival_points[min(len(arrival_points) - 1, 8)] - arrival_points[0]
        )
        axis_angle = min(
            _angle(arrival_direction, arms[a]["direction"]),
            _angle(arrival_direction, arms[b]["direction"]),
        )
        if axis_angle < POLICY["minimum_arrival_carrier_angle_deg"]:
            continue
        try:
            core = contact._core_route(
                graph, nid, arms[a]["pixels"][0], arms[b]["pixels"][0]
            )
        except ValueError:
            continue
        pixels = arms[a]["pixels"][::-1] + core[1:] + arms[b]["pixels"][1:]
        points = graph.xy(pixels)
        center = points.mean(axis=0)
        _, _, vh = np.linalg.svd(points - center, full_matrices=False)
        direction = vh[0]
        if (points[-1] - points[0]) @ direction < 0:
            direction = -direction
        projections = (points - center) @ direction
        aa, bb = (
            center + projections[0] * direction,
            center + projections[-1] * direction,
        )
        normal = np.array([-direction[1], direction[0]])
        maximum_normal = float(np.abs((points - center) @ normal).max())
        if maximum_normal > POLICY["maximum_carrier_normal_px"]:
            continue
        owners = []
        touch = np.asarray(node["center"])
        for oid, member, geometry in prior_lines:
            pa, pb = np.asarray(geometry["start"]), np.asarray(geometry["end"])
            vec = pb - pa
            length = float(np.linalg.norm(vec))
            if length < 2 * POLICY["minimum_carrier_arm_px"]:
                continue
            unit = vec / length
            t = float((touch - pa) @ unit)
            residual = float(np.linalg.norm(touch - (pa + t * unit)))
            angle = min(_angle(unit, direction), _angle(-unit, direction))
            if (
                POLICY["minimum_carrier_arm_px"]
                <= t
                <= length - POLICY["minimum_carrier_arm_px"]
                and residual <= POLICY["maximum_carrier_owner_normal_px"]
                and angle <= POLICY["maximum_carrier_owner_angle_deg"]
            ):
                samples = pa + np.arange(0.0, length + 0.01, 0.25)[:, None] * unit
                normals = np.array([-unit[1], unit[0]])
                hit = np.zeros(len(samples), bool)
                for offset in np.arange(
                    -POLICY["carrier_owner_source_normal_px"],
                    POLICY["carrier_owner_source_normal_px"] + 0.01,
                    0.25,
                ):
                    q = np.rint(samples + offset * normals - graph.origin).astype(int)
                    valid = (
                        (q[:, 0] >= 0)
                        & (q[:, 0] < graph.w)
                        & (q[:, 1] >= 0)
                        & (q[:, 1] < graph.h)
                    )
                    hit[valid] |= graph.source_ink[q[valid, 1], q[valid, 0]]
                source_fraction = float(hit.mean())
                if source_fraction >= POLICY["carrier_owner_source_fraction_min"]:
                    owners.append(
                        {
                            "id": oid,
                            "member_index": member,
                            "geometry": geometry,
                            "normal_px": residual,
                            "angle_deg": angle,
                            "complete_owner_source_fraction": source_fraction,
                            "complete_owner_source_normal_px": POLICY[
                                "carrier_owner_source_normal_px"
                            ],
                        }
                    )
        witness = None
        if len(owners) > 1:
            pending.append(
                {
                    "node_id": nid,
                    "reason": "COMPETING_EXISTING_CARRIER_OWNERS",
                    "owners": owners,
                }
            )
            continue
        if not owners:
            if not all(arms[p]["corner"] for p in (a, b)):
                continue
            witness = _source_parallel_witness(graph, aa, bb)
            if witness is None:
                continue
        geometry = {
            "points": [aa.tolist(), bb.tolist()],
            "bulges": [0.0, 0.0],
            "closed": False,
        }
        if owners:
            owner = owners[0]
            line_geometry = owner["geometry"]
            carrier_id = owner["id"]
        else:
            line_geometry = {"start": aa.tolist(), "end": bb.tolist()}
            carrier_id = stable_id("CONTACT", geometry)
        pa, pb = np.asarray(line_geometry["start"]), np.asarray(line_geometry["end"])
        axis = _unit(pb - pa)
        # Intersect the observed arriving direction with the independent carrier;
        # do not select a nearest endpoint or bridge a source gap.
        incoming = arrival_points[0]
        matrix = np.column_stack((arrival_direction, -axis))
        try:
            travel, along = np.linalg.solve(matrix, pa - incoming)
        except np.linalg.LinAlgError:
            continue
        intersection = incoming + travel * arrival_direction
        if np.linalg.norm(intersection - touch) > 4.0:
            continue
        source_cells = _segment_cells(incoming, intersection)
        cells = (np.asarray(source_cells) - graph.origin).astype(int)
        if not np.all(graph.source_ink[cells[:, 1], cells[:, 0]]):
            continue
        terminal = {
            "kind": "OBSERVED_SUPPORTED_LINE_CONTACT",
            "carrier_id": carrier_id,
            "carrier_member_index": owners[0]["member_index"] if owners else None,
            "source_node_id": nid,
            "arriving_port": list(arriving),
            "source_contact_point_px": intersection.tolist(),
            "source_core_points_px": graph.xy(node["pixels"]).tolist(),
            "carrier_source_ports": [list(a), list(b)],
            "carrier_source_arm_lengths_px": [
                arms[a]["length_px"],
                arms[b]["length_px"],
            ],
            "carrier_pair_deviation_deg": deviation,
            "arrival_carrier_angle_deg": axis_angle,
            "carrier_geometry": line_geometry,
            "carrier_source_path_px": points.tolist(),
            "carrier_source_maximum_normal_px": maximum_normal,
            "existing_carrier_binding": owners[0] if owners else None,
            "carrier_corner_evidence": [arms[a]["corner"], arms[b]["corner"]],
            "independent_parallel_source_witness": witness,
            "arrival_to_intersection_original_black_cells": source_cells,
            "closed_pixel_cells_all_original_ink": True,
            "all_source_ports_accounted": True,
            "equally_aligned_forward_port_count": 0,
            "semantics_inferred": False,
        }
        carriers[(nid, arriving)] = {
            "terminal": terminal,
            "geometry": geometry,
            "source_pixels": pixels,
            "source_points": points,
            "existing": bool(owners),
            "id": carrier_id,
        }
    return carriers, pending


def _port_directions(graph, port, carriers):
    """Local tangent hypotheses independent of the chosen trace origin."""
    queue = [(port, [], [], 0)]
    result = []
    complete = True
    while queue and len(result) < POLICY["maximum_direction_states"]:
        current, pixels, used, depth = queue.pop()
        if current[0] in used:
            complete = False
            continue
        part = graph.oriented(current)
        if pixels:
            nid = graph.edges[current[0]]["nodes"][current[1]]
            try:
                core = contact._core_route(graph, nid, pixels[-1], part[0])
            except ValueError:
                complete = False
                continue
            pixels = pixels + core[1:] + part[1:]
        else:
            pixels = list(part)
        used = used + [current[0]]
        points = graph.xy(pixels)
        spans = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
        nid = graph.edges[current[0]]["nodes"][1 - current[1]]
        incoming = (current[0], 1 - current[1])
        node = graph.nodes[nid]
        finished = (
            spans[-1] >= POLICY["direction_span_px"]
            or node["terminal"]
            or (nid, incoming) in carriers
        )
        if not finished and depth >= POLICY["maximum_direction_depth"]:
            complete = False
            continue
        if finished:
            k = min(
                len(points) - 1,
                int(np.searchsorted(spans, POLICY["direction_span_px"])),
            )
            vector = points[k] - points[0]
            if np.linalg.norm(vector) >= POLICY["minimum_direction_span_px"]:
                result.append(
                    {
                        "vector": _unit(vector),
                        "edge_ids": used,
                        "span_px": float(spans[k]),
                        "source_start_px": points[0].tolist(),
                        "source_end_px": points[k].tolist(),
                    }
                )
            else:
                complete = False
            continue
        choices = (
            [node["pairing"][incoming]]
            if incoming in node["pairing"]
            else [p for p in node["edges"] if p != incoming]
        )
        for candidate in choices:
            queue.append((candidate, pixels, used, depth + 1))
    return result, complete and not queue


def _reciprocal_pair(graph, nid, incoming, carriers, cache):
    if nid not in cache:
        node = graph.nodes[nid]
        ports = node["edges"]
        observed = {p: _port_directions(graph, p, carriers) for p in ports}
        looks = {p: value[0] for p, value in observed.items()}
        incomplete_ports = [
            p for p, value in observed.items() if not value[1] or not value[0]
        ]
        scored = {}
        for p in ports:
            options = []
            for q in ports:
                if p == q or p[0] == q[0] or not looks[p] or not looks[q]:
                    continue
                values = [
                    _angle(a["vector"], -b["vector"])
                    for a in looks[p]
                    for b in looks[q]
                ]
                # Every possible local tangent is represented. Choosing a start
                # point cannot exclude an inconvenient competing route.
                options.append((min(values), max(values), q))
            scored[p] = sorted(options)
        cache[nid] = (looks, scored, incomplete_ports)
    looks, scored, incomplete_ports = cache[nid]
    if incomplete_ports:
        return None, {
            "reason": "CONTACT_DIRECTION_EXPLORATION_INCOMPLETE",
            "node_id": nid,
            "unresolved_ports": [list(p) for p in incomplete_ports],
            "unexplored_competition_not_dropped": True,
        }
    choices = scored[incoming]
    if not choices:
        return None, {"reason": "NO_RECIPROCAL_CONTACT_DIRECTION", "node_id": nid}
    best, worst, outgoing = choices[0]
    reverse = scored[outgoing]
    margin = choices[1][0] - best if len(choices) > 1 else 180.0
    reverse_margin = reverse[1][0] - reverse[0][0] if len(reverse) > 1 else 180.0
    passed = (
        reverse
        and reverse[0][2] == incoming
        and worst <= POLICY["maximum_pair_deviation_deg"]
        and reverse[0][1] <= POLICY["maximum_pair_deviation_deg"]
        and margin >= POLICY["minimum_pair_margin_deg"]
        and reverse_margin >= POLICY["minimum_pair_margin_deg"]
    )
    evidence = {
        "reason": "RECIPROCAL_UNIQUE_SOURCE_PAIR"
        if passed
        else "CONTACT_PAIR_OR_COMPETITION_NOT_UNIQUE",
        "node_id": nid,
        "source_node_center_px": graph.nodes[nid]["center"],
        "source_core_pixels": graph.xy(graph.nodes[nid]["pixels"]).tolist(),
        "incoming_edge_id": incoming[0],
        "selected_outgoing_ports": [list(outgoing)],
        "maximum_pair_deviation_deg": worst,
        "forward_margin_deg": margin,
        "reverse_margin_deg": reverse_margin,
        "all_port_candidates": [
            {
                "port": list(p),
                "alternatives": [
                    {
                        "port": list(q),
                        "minimum_deviation_deg": low,
                        "maximum_deviation_deg": high,
                    }
                    for low, high, q in values
                ],
            }
            for p, values in scored.items()
        ],
        "unselected_branch_edge_ids": [
            p[0] for p in graph.nodes[nid]["edges"] if p not in (incoming, outgoing)
        ],
        "unselected_branch_source_paths": [
            graph.xy(graph.oriented(p)).tolist()
            for p in graph.nodes[nid]["edges"]
            if p not in (incoming, outgoing)
        ],
        "source_branches_deleted": False,
        "trace_origin_excluded_from_decision": True,
        "line_and_other_ink_may_share_core": True,
    }
    return (outgoing if passed else None), evidence


def _trace(graph, first, carriers, pair_cache):
    pixels, edges, contacts, covers, protected = [], [], [], [], []
    port = first
    nid = graph.edges[port[0]]["nodes"][port[1]]
    for _ in range(POLICY["maximum_route_edges"]):
        if len(edges) >= POLICY["maximum_route_edges"]:
            return {"reason": "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT"}
        if port[0] in edges:
            return {"reason": "SOURCE_ROUTE_CYCLE"}
        part = graph.oriented(port)
        if pixels:
            try:
                core = contact._core_route(graph, nid, pixels[-1], part[0])
            except ValueError:
                return {"reason": "SOURCE_CORE_NOT_CONNECTED"}
            protected.append([len(pixels) - 1, len(pixels) + len(core) - 1])
            pixels += core[1:] + part[1:]
        else:
            pixels = list(part)
        edges.append(port[0])
        nid = graph.edges[port[0]]["nodes"][1 - port[1]]
        incoming = (port[0], 1 - port[1])
        node = graph.nodes[nid]
        carrier = carriers.get((nid, incoming))
        terminal = carrier["terminal"] if carrier else node["terminal"]
        if terminal:
            return {
                "reason": None,
                "pixels": pixels,
                "edge_ids": edges,
                "contacts": contacts,
                "cycle_covers": covers,
                "protected": protected,
                "terminal": terminal,
                "terminal_node_id": nid,
                "terminal_port": incoming,
                "carrier": carrier,
                "terminal_source_core": contact.round_terminal_source_core(
                    graph, nid, incoming
                )
                if not carrier
                else None,
            }
        if node.get("reason") == "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT":
            return {"reason": node["reason"]}
        cover = graph.cycle_cells_by_port.get(incoming)
        micro = (
            None if cover else contact._complete_microcore_cover(graph, nid, incoming)
        )
        if cover or micro:
            if cover:
                outgoing = next(
                    tuple(p) for p in cover["external_ports"] if tuple(p) != incoming
                )
                walk = graph._cycle_cover_route(
                    cover, pixels[-1], graph.oriented(outgoing)[0]
                )
                certificate = cover
            else:
                outgoing, walk, certificate = micro
            if set(certificate["internal_source_graph_edge_ids"]) & set(edges):
                return {"reason": "SOURCE_ROUTE_CYCLE"}
            protected.append([len(pixels) - 1, len(pixels) + len(walk) - 1])
            pixels.extend(walk[1:])
            edges.extend(certificate["internal_source_graph_edge_ids"])
            covers.append(certificate)
            nid = graph.edges[outgoing[0]]["nodes"][outgoing[1]]
            port = outgoing
            continue
        if incoming in node["pairing"]:
            port = node["pairing"][incoming]
            if len(node["edges"]) >= 4:
                contacts.append(
                    {
                        "reason": "EXISTING_UNIQUE_FOUR_PORT_SOURCE_PAIR",
                        "node_id": nid,
                        "source_core_pixels": graph.xy(node["pixels"]).tolist(),
                        "incoming_edge_id": incoming[0],
                        "selected_outgoing_ports": [list(port)],
                        "source_branches_deleted": False,
                        "unselected_branch_edge_ids": [
                            p[0] for p in node["edges"] if p not in (incoming, port)
                        ],
                        "unselected_branch_source_paths": [
                            graph.xy(graph.oriented(p)).tolist()
                            for p in node["edges"]
                            if p not in (incoming, port)
                        ],
                        "original_crossing_evidence": node.get("crossing_evidence"),
                    }
                )
            continue
        port, evidence = _reciprocal_pair(graph, nid, incoming, carriers, pair_cache)
        contacts.append(evidence)
        if port is None:
            return {
                "reason": evidence["reason"],
                "contact_continuations": contacts,
                "source_path_px": graph.xy(pixels).tolist(),
            }
    return {"reason": "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT"}


def _plan_row(points, geometry, fit, support, terminals, cores, contacts, covers, role):
    return {
        "path_role": role,
        "source_path_px": points.tolist(),
        "source_path_length_px": paths._length(points),
        "representation": geometry,
        "representation_evidence": fit,
        "source_support": support,
        "native_endpoint_points_px": [geometry["points"][0], geometry["points"][-1]],
        "endpoint_evidence": terminals,
        "endpoint_source_points_px": [points[0].tolist(), points[-1].tolist()],
        "endpoint_source_cores": cores,
        "contact_continuations": contacts,
        "bounded_original_cycle_covers": covers,
        "line_runs": [],
        "shared_contact_runs": [],
        "original_branches_retained": True,
        "line_and_text_may_share_source_pixels": True,
        "text_content_decision": "NOT_PERFORMED",
    }


def plan_structure_contact_geometry(gray, roi, prior_objects, *, source_graph=None):
    source = np.asarray(gray)
    context = source_graph or contact.build_text_contact_source_graph(source, roi)
    graph = context.graph
    ox, oy, rx, by = context.crop_bbox
    if (
        list(map(int, roi)) != list(graph.roi)
        or hashlib.sha256(source[oy:by, ox:rx].tobytes()).hexdigest()
        != context.source_crop_hash
    ):
        raise ValueError("STRUCTURE_CONTACT_REUSED_GRAPH_SOURCE_CHANGED")
    bindings = _bindings(prior_objects)
    circle_bindings = circle_source_bindings(prior_objects)
    verified_circles = _verified_start_circles(source, roi, bindings, circle_bindings)
    result = {
        "schema": SCHEMA,
        "policy": dict(POLICY),
        "roi_xyxy_px": list(map(int, roi)),
        "seed_bbox_xyxy_px": list(map(int, roi)),
        "contact_context_bbox_xyxy_px": list(map(int, roi)),
        "original_source_crop_xyxy_px": context.crop_bbox,
        "original_source_crop_array_sha256": context.source_crop_hash,
        "round_observations": context.rounds,
        "prior_object_bindings": bindings,
        "prior_object_bindings_sha256": _digest(bindings),
        "prior_circle_source_bindings": circle_bindings,
        "prior_circle_source_bindings_sha256": _digest(circle_bindings),
        "circle_endpoint_source_policy": dict(CIRCLE_CONTACT_POLICY),
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "unchanged_connection_source_policy": dict(paths.POLICY),
        "paths": [],
        "pending": [],
        "original_source_pixels_modified": False,
        "transcription_supplied": False,
    }
    # The replay input is this canonical immutable binding list.  Pending
    # competing-owner order must be just as reproducible as adopted geometry.
    carriers, pending = _carrier_candidates(graph, bindings)
    result["pending"].extend(pending)
    result["carrier_candidate_count"] = len(carriers)
    distance = cv2.distanceTransform(
        (~graph.source_ink).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    pair_cache, seen = {}, set()
    rows, carrier_rows = [], {}
    for nid, node in graph.nodes.items():
        if (node["terminal"] or {}).get("kind") != "OBSERVED_ROUND_BOUNDARY_CONTACT":
            continue
        for first in node["edges"]:
            forward = _trace(graph, first, carriers, pair_cache)
            if forward["reason"]:
                result["pending"].append(
                    {"start_node_id": nid, "start_port": list(first), **forward}
                )
                continue
            if forward["terminal"].get("kind") != "OBSERVED_SUPPORTED_LINE_CONTACT":
                continue
            reverse = _trace(graph, forward["terminal_port"], carriers, pair_cache)
            if (
                reverse["reason"]
                or reverse.get("terminal_node_id") != nid
                or reverse.get("terminal_port") != first
                or set(reverse.get("edge_ids", [])) != set(forward["edge_ids"])
            ):
                result["pending"].append(
                    {
                        "start_node_id": nid,
                        "reason": "COMPLETE_REVERSE_TRACE_DOES_NOT_AGREE",
                        "forward_edge_ids": forward["edge_ids"],
                        "reverse": {
                            k: v
                            for k, v in reverse.items()
                            if k not in ("pixels", "carrier")
                        },
                    }
                )
                continue
            key = tuple(sorted(forward["edge_ids"]))
            if key in seen:
                continue
            seen.add(key)
            points = graph.xy(forward["pixels"])
            length = paths._length(points)
            if (
                not POLICY["minimum_path_length_px"]
                <= length
                <= POLICY["maximum_path_length_px"]
                or len(forward["contacts"]) < POLICY["minimum_shared_contact_count"]
            ):
                continue
            if paths._round_boundary_ownership(points, context.rounds):
                continue
            if not contact._inside(points, roi).all():
                continue
            endpoint = np.asarray(forward["terminal"]["source_contact_point_px"])
            end_node = graph.nodes[forward["terminal_node_id"]]
            source_end = min(
                end_node["pixels"],
                key=lambda p: (float(np.linalg.norm(graph.xy([p])[0] - endpoint)), p),
            )
            try:
                terminal_core = contact._core_route(
                    graph, end_node["id"], forward["pixels"][-1], source_end
                )
            except ValueError:
                continue
            original_pixels = forward["pixels"] + terminal_core[1:]
            points = graph.xy(original_pixels)
            geometry, fit = paths._representation(
                points, protected_intervals=forward["protected"]
            )
            # The source walk stays integral. The single representation end is
            # the source-proved intersection with the separately owned carrier.
            geometry["points"][-1] = endpoint.tolist()
            dense = paths._dense_geometry(geometry, paths.POLICY["dense_step_px"])
            support = paths._support(dense, distance, graph.origin)
            cycle_checks = paths._local_cycle_white_space_checks(
                geometry,
                [{"local_cycle_cover_evidence": c} for c in forward["cycle_covers"]],
            )
            if (
                not support["pass"]
                or (cycle_checks and not cycle_checks["pass"])
                or len(geometry["points"]) > POLICY["maximum_control_vertices"]
            ):
                result["pending"].append(
                    {
                        "start_node_id": nid,
                        "reason": "STRUCTURE_CONTACT_FINAL_SOURCE_OR_WHITE_SPACE_GATE_FAILED",
                        "support": support,
                        "cycle_checks": cycle_checks,
                    }
                )
                continue
            terminal = forward["terminal"]
            start_circle = _starting_circle(
                context, nid, first, verified_circles, circle_bindings
            )
            row = _plan_row(
                points,
                geometry,
                fit,
                support,
                [node["terminal"], terminal],
                [contact.round_terminal_source_core(graph, nid, first), None],
                forward["contacts"],
                forward["cycle_covers"],
                "ROUND_TO_CARRIER",
            )
            row.update(
                {
                    "source_graph_edge_ids": list(key),
                    "structural_terminal_evidence": terminal,
                    "required_carrier_id": terminal["carrier_id"],
                    "required_start_circle_id": start_circle.get("circle_id"),
                    "starting_circle_evidence": start_circle,
                    "reverse_source_path_agreement": {
                        "pass": True,
                        "forward_edge_ids": forward["edge_ids"],
                        "reverse_edge_ids": reverse["edge_ids"],
                        "same_round_node": nid,
                    },
                    "local_cycle_white_space_checks": cycle_checks,
                    "endpoint_representation_adjustments": [
                        {
                            "end": 1,
                            "original_source_endpoint_px": points[-1].tolist(),
                            "native_endpoint_px": endpoint.tolist(),
                            "basis": "ORIGINAL_ARRIVAL_INTERSECTS_INDEPENDENT_FINITE_CARRIER_IN_SAME_SOURCE_CORE",
                            "source_core_points_px": terminal["source_core_points_px"],
                            "closed_source_pixel_cells": terminal[
                                "arrival_to_intersection_original_black_cells"
                            ],
                            "all_original_ink": True,
                        }
                    ],
                }
            )
            if not start_circle["pass"]:
                result["pending"].append(
                    {
                        "reason": start_circle["reason"],
                        "start_node_id": nid,
                        "start_port": list(first),
                        "path_observation": deepcopy(row),
                        "original_source_observation_retained": True,
                        "formal_complete_path_adopted": False,
                    }
                )
            rows.append(row)
            carrier = forward["carrier"]
            if not carrier["existing"]:
                cg = carrier["geometry"]
                cp = carrier["source_points"]
                cs = paths._support(paths._dense_geometry(cg), distance, graph.origin)
                cr = _plan_row(
                    cp,
                    cg,
                    {
                        "representation": "ONE_NATIVE_LINE",
                        "maximum_normal_px": terminal[
                            "carrier_source_maximum_normal_px"
                        ],
                    },
                    cs,
                    [
                        {"kind": "OBSERVED_SOURCE_CARRIER_CORNER", "evidence": c}
                        for c in terminal["carrier_corner_evidence"]
                    ],
                    [None, None],
                    [],
                    [],
                    "SUPPORTING_CARRIER",
                )
                cr.update(
                    {
                        "structural_carrier_evidence": terminal,
                        "carrier_id": carrier["id"],
                        "source_graph_edge_ids": [
                            p[0] for p in terminal["carrier_source_ports"]
                        ],
                    }
                )
                adjustments = []
                for end in (0, 1):
                    raw_end, native_end = (
                        cp[0 if end == 0 else -1],
                        np.asarray(cg["points"][0 if end == 0 else -1]),
                    )
                    cells = _segment_cells(raw_end, native_end)
                    q = (np.asarray(cells) - graph.origin).astype(int)
                    adjustments.append(
                        {
                            "end": end,
                            "original_source_endpoint_px": raw_end.tolist(),
                            "native_endpoint_px": native_end.tolist(),
                            "basis": "TWO_SIDED_ORIGINAL_CARRIER_LINE_FIT_AT_OBSERVED_CORNER",
                            "closed_source_pixel_cells": cells,
                            "all_original_ink": bool(
                                np.all(graph.source_ink[q[:, 1], q[:, 0]])
                            ),
                        }
                    )
                cr["endpoint_representation_adjustments"] = adjustments
                if not all(a["all_original_ink"] for a in adjustments):
                    result["pending"].append(
                        {
                            "reason": "CARRIER_ENDPOINT_FIT_HAS_ORIGINAL_WHITE_CELL",
                            "carrier_id": carrier["id"],
                        }
                    )
                    rows.pop()
                    continue
                carrier_rows[carrier["id"]] = cr
    rows, competitions = contact._quarantine_competing_whole_routes(rows)
    result["pending"].extend(competitions)
    # An unowned round observation remains a competitor and a recorded source
    # path, but cannot become a formally complete round-to-carrier object.
    rows = [row for row in rows if row["starting_circle_evidence"]["pass"]]
    required = {r["required_carrier_id"] for r in rows}
    result["paths"] = [
        carrier_rows[k] for k in sorted(required & set(carrier_rows))
    ] + rows
    result["reason"] = (
        "COMPLETE_STRUCTURE_CONTACT_PATHS_PLANNED"
        if rows
        else "NO_COMPLETE_STRUCTURE_CONTACT_PATH_PROVEN"
    )
    return result


def verify_structure_contact_geometry_plan(gray, roi, plan, *, source_graph=None):
    """Cold replay the complete discovery, competitors, carrier and source walk."""
    bindings = plan.get("prior_object_bindings", [])
    if plan.get("schema") != SCHEMA or plan.get(
        "prior_object_bindings_sha256"
    ) != _digest(bindings):
        return {"pass": False, "checks": {"prior_bindings_integrity": False}}
    certificates = plan.get("prior_circle_source_bindings", [])
    try:
        circle_ids = [
            obj["id"]
            for obj in bindings
            if obj["kind"] in ("CIRCLE", "CIRCULAR_MARKER")
        ]
        if (
            plan.get("prior_circle_source_bindings_sha256") != _digest(certificates)
            or [row["id"] for row in certificates] != circle_ids
            or len(set(circle_ids)) != len(circle_ids)
        ):
            raise ValueError("START_CIRCLE_SOURCE_BINDINGS_CHANGED")
        by_id = {row["id"]: row["source_evidence"] for row in certificates}
        prior = [
            {**obj, "source_evidence": by_id.get(obj["id"], {})} for obj in bindings
        ]
    except (KeyError, TypeError, ValueError):
        return {
            "pass": False,
            "checks": {"prior_circle_source_bindings_integrity": False},
        }
    replay = plan_structure_contact_geometry(
        gray, roi, prior, source_graph=source_graph
    )
    keys = (
        "schema",
        "policy",
        "roi_xyxy_px",
        "original_source_crop_xyxy_px",
        "original_source_crop_array_sha256",
        "round_observations",
        "prior_object_bindings",
        "prior_object_bindings_sha256",
        "prior_circle_source_bindings",
        "prior_circle_source_bindings_sha256",
        "circle_endpoint_source_policy",
        "paths",
        "pending",
        "carrier_candidate_count",
        "reason",
        "producer_sha256",
        "unchanged_connection_source_policy",
        "original_source_pixels_modified",
        "transcription_supplied",
    )
    checks = {key + "_replayed": plan.get(key) == replay.get(key) for key in keys}
    passed = all(checks.values())
    return {
        "pass": passed,
        "checks": checks,
        "reason": "EXACT_STRUCTURE_CONTACT_SOURCE_REPLAY"
        if passed
        else "STRUCTURE_CONTACT_SOURCE_REPLAY_MISMATCH",
        "path_count": len(replay["paths"]),
        "replayed_paths": replay["paths"],
        "source_pixels_modified": False,
    }
