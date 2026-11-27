"""Finite decompositions of attached strokes in the unchanged source graph.

An already proved complete path fixes only its own ports.  All remaining
ports, finite edges and T junction alternatives are accounted for together.
No selected trace origin, page locator or transcription enters this model.
This is an experimental graph method; it leaves the older transverse planner
and its free-ended, four-port policy unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import label

from . import connections as paths
from . import attached_stroke_contacts as prior_contacts
from . import attached_stroke_ink as attached_ink
from . import attached_stroke_component as attached_component
from . import attached_stroke_width_exact as attached_width
from . import text_contact_geometry as contact
from . import transverse_stroke_geometry as transverse
from .circle_endpoint_contacts import _segment_cells
from .contracts import save_json, stable_id


SCHEMA = "source-attached-stroke-graph-plan-v3-component-exact"
FIELD = "attached_stroke_graph"
POLICY = {
    "version": "finite-attached-source-tree-decompositions-v3-component-exact",
    "finite_direction_spans_px": [6.0, 8.0, 12.0],
    "minimum_observed_direction_chord_px": 4.0,
    "maximum_pair_deviation_deg": 20.0,
    "minimum_pair_margin_deg": 18.0,
    "minimum_attachment_axis_separation_deg": 45.0,
    "maximum_component_edges": 32,
    "maximum_component_nodes": 32,
    "maximum_component_extent_px": 240.0,
    "maximum_decompositions": 512,
    "minimum_stroke_length_px": 20.0,
    "maximum_stroke_length_px": 120.0,
    "maximum_native_source_distance_px": 1.5,
    "maximum_core_extent_px": 12.0,
    "maximum_core_extent_stroke_widths": 3.0,
    "maximum_core_pixels": 64,
    "maximum_solid_core_cycle_rank": 1,
    "maximum_cycle_axis_intersection_residual_px": 0.85,
    "maximum_simple_core_routes": 64,
    "maximum_control_vertices": 256,
    "minimum_parallel_crossing_companions": 1,
    "maximum_companion_axis_angle_deg": 12.0,
    "maximum_owner_native_source_distance_px": 2.0,
    "all_T_pair_and_attachment_choices_enumerated": True,
    "all_original_core_adjacencies_retained_as_evidence": True,
    "shared_core_does_not_authorize_native_length_overlap": True,
    "native_contact_replay_requires_straight_segments": True,
    "source_pixels_modified": False,
    "source_graph_pairings_modified": False,
    "existing_objects_retired": False,
    "attached_endpoint_raw_ink_policy": attached_component.POLICY["version"],
    "all_prior_native_contact_policy": prior_contacts.POLICY["version"],
    "failed_complete_candidates_and_receipts_retained": True,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _plain(value):
    """Freeze graph scalars and sequences as portable JSON proof values."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [_plain(item) for item in value]
    return value


def object_binding(obj):
    result = transverse._binding(obj)
    evidence = obj.get("source_evidence", {})
    for key in ("short_contact_text", "text_layout", "text_geometry"):
        if key in evidence:
            result["source_evidence"][key] = deepcopy(evidence[key])
    return result


def _unit(vector):
    vector = np.asarray(vector, float)
    return vector / max(float(np.linalg.norm(vector)), 1e-12)


def _angle(a, b):
    return math.degrees(math.acos(float(np.clip(np.asarray(a) @ np.asarray(b), -1, 1))))


def _black_segment(source, a, b):
    cells = np.asarray(_segment_cells(a, b), int)
    return bool(len(cells) and np.all(cells >= 0)
                and np.all(cells[:, 0] < source.shape[1])
                and np.all(cells[:, 1] < source.shape[0])
                and np.all(source[cells[:, 1], cells[:, 0]] < paths.POLICY["source_threshold"]))


def _directions(graph, port):
    points = graph.xy(graph.oriented(port))
    cumulative = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    result = []
    for requested in POLICY["finite_direction_spans_px"]:
        index = min(len(points) - 1, int(np.searchsorted(cumulative, min(requested, cumulative[-1]))))
        vector = points[index] - points[0]
        chord = float(np.linalg.norm(vector))
        result.append({"requested_span_px": requested, "actual_span_px": float(cumulative[index]),
                       "chord_px": chord, "vector": _unit(vector).tolist(),
                       "source_points_px": points[:index + 1].tolist(),
                       "stopped_at_observed_graph_node": bool(index == len(points) - 1)})
    return result


def _node_directions(graph, nid):
    ports = sorted(graph.nodes[nid]["edges"])
    observed = {port: _directions(graph, port) for port in ports}
    complete = all(row["chord_px"] >= POLICY["minimum_observed_direction_chord_px"]
                   for rows in observed.values() for row in rows)
    scores = []
    for a, b in itertools.combinations(ports, 2):
        values = [_angle(x["vector"], -np.asarray(y["vector"]))
                  for x, y in zip(observed[a], observed[b])]
        competitors = []
        for index in range(len(values)):
            other_a = [_angle(observed[a][index]["vector"], -np.asarray(observed[c][index]["vector"]))
                       for c in ports if c not in (a, b)]
            other_b = [_angle(observed[b][index]["vector"], -np.asarray(observed[c][index]["vector"]))
                       for c in ports if c not in (a, b)]
            competitors.append(min(other_a + other_b, default=180.0) - values[index])
        scores.append({"pair": [list(a), list(b)], "deviation_by_fixed_span_deg": values,
                       "competition_margin_by_fixed_span_deg": competitors,
                       "maximum_pair_deviation_deg": max(values),
                       "minimum_competition_margin_deg": min(competitors),
                       "pass": bool(complete and max(values) <= POLICY["maximum_pair_deviation_deg"]
                                    and min(competitors) >= POLICY["minimum_pair_margin_deg"])})
    return {"node_id": nid, "all_ports": [list(port) for port in ports],
            "all_observed_directions": [{"port": list(port), "observations": observed[port]}
                                        for port in ports],
            "all_pair_candidates": scores, "all_directions_complete": complete,
            "directions_never_follow_a_different_branch": True}


def _pair_proof(table, pair):
    key = set(map(tuple, pair))
    return next(row for row in table["all_pair_candidates"] if set(map(tuple, row["pair"])) == key)


def _all_core_routes(graph, nid, a, b):
    allowed = set(graph.nodes[nid]["pixels"])
    stack, result = [(a, [a])], []
    while stack:
        node, route = stack.pop()
        if node == b:
            result.append(route)
            if len(result) > POLICY["maximum_simple_core_routes"]:
                raise ValueError("TOO_MANY_CORE_ENCODINGS")
            continue
        for other in sorted(graph.neighbors(node), reverse=True):
            if other in allowed and other not in route:
                stack.append((other, route + [other]))
    if not result:
        raise ValueError("DISCONNECTED_ORIGINAL_CORE")
    return sorted(result, key=lambda route: (len(route), route))


def _core_proof(source, graph, nid):
    node = graph.nodes[nid]
    if len(node["pixels"]) > POLICY["maximum_core_pixels"]:
        raise ValueError("ORIGINAL_CORE_EXCEEDS_FINITE_PIXEL_BOUND")
    pixels = sorted(node["pixels"])
    points = graph.xy(pixels)
    extent = float(np.ptp(points, axis=0).max())
    if extent > POLICY["maximum_core_extent_px"]:
        raise ValueError("ORIGINAL_CORE_EXCEEDS_FINITE_SPATIAL_BOUND")
    left, top = np.floor(points.min(axis=0) - 2).astype(int)
    right, bottom = np.ceil(points.max(axis=0) + 3).astype(int)
    if min(left, top) < 0 or right > source.shape[1] or bottom > source.shape[0]:
        raise ValueError("CORE_OUTSIDE_OBSERVED_SOURCE")
    ink = source[top:bottom, left:right] < paths.POLICY["source_threshold"]
    white_labels, count = label(~ink)
    boundary = set(white_labels[0]) | set(white_labels[-1]) | set(white_labels[:, 0]) | set(white_labels[:, -1])
    holes = []
    for value in range(1, count + 1):
        if value not in boundary:
            y, x = np.nonzero(white_labels == value)
            holes.append(np.column_stack((x + left, y + top)).tolist())
    pixel_set = set(pixels)
    core_edges = {tuple(sorted((p, q))) for p in pixels for q in graph.neighbors(p) if q in pixel_set}
    axes, widths = [], []
    # Measure local pen width on the actual original ink; the padded array is
    # only a distance measurement and is never used to reconnect source pixels.
    pad = 16
    x0, y0 = max(0, left - pad), max(0, top - pad)
    x1, y1 = min(source.shape[1], right + pad), min(source.shape[0], bottom + pad)
    distance = cv2.distanceTransform((source[y0:y1, x0:x1] < 128).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    for port in sorted(node["edges"]):
        samples = np.asarray(_directions(graph, port)[-1]["source_points_px"])
        center = samples.mean(axis=0)
        _, _, basis = np.linalg.svd(samples - center)
        direction = basis[0]
        normal = np.array([-direction[1], direction[0]])
        axes.append((normal, float(normal @ center)))
        for x, y in samples[1:].astype(int):
            if x0 <= x < x1 and y0 <= y < y1:
                widths.append(float(2 * distance[y - y0, x - x0]))
    normals = np.array([a[0] for a in axes])
    constants = np.array([a[1] for a in axes])
    point = np.linalg.lstsq(normals, constants, rcond=None)[0]
    residual = float(np.max(abs(normals @ point - constants)))
    width = float(np.median(widths)) if widths else 0.0
    rank = int(node["core_topology"]["cycle_rank"])
    passed = (not holes and not node["internal_source_endpoint_count"]
              and len(pixels) <= POLICY["maximum_core_pixels"]
              and extent <= min(POLICY["maximum_core_extent_px"], POLICY["maximum_core_extent_stroke_widths"] * width)
              and rank <= POLICY["maximum_solid_core_cycle_rank"])
    if rank:
        passed &= bool(len(node["edges"]) == 4
                       and residual <= POLICY["maximum_cycle_axis_intersection_residual_px"]
                       and _black_segment(source, point, point))
    return {"node_id": nid, "pass": bool(passed), "core_topology": deepcopy(node["core_topology"]),
            "source_core_pixels": points.tolist(),
            "all_source_core_adjacencies": [graph.xy(edge).tolist() for edge in sorted(core_edges)],
            "raw_ink_box_xyxy_px": [int(left), int(top), int(right), int(bottom)],
            "raw_ink_mask": ink.astype(int).tolist(), "enclosed_original_white_components": holes,
            "internal_source_endpoint_count": node["internal_source_endpoint_count"],
            "extent_px": extent, "observed_median_pen_width_px": width,
            "external_axis_common_point_px": point.tolist(), "axis_intersection_residual_px": residual,
            "source_graph_cycle_not_deleted": True,
            "solid_core_edges_are_shared_support_not_native_segments": True}


def _owner_nodes(graph, owner):
    by_core = {tuple(sorted(node["pixels"])): nid for nid, node in graph.nodes.items()}
    anchors = {}
    for proof in owner["contact_continuations"]:
        points = proof.get("source_core_pixels", [])
        pixels = tuple(sorted(int(y - graph.origin[1]) * graph.w + int(x - graph.origin[0]) for x, y in points))
        nid = by_core.get(pixels)
        if nid is None or len(graph.nodes[nid]["edges"]) != 4:
            continue
        selected = proof.get("selected_outgoing_ports", [])
        if len(selected) != 1:
            continue
        ids = {proof.get("incoming_edge_id"), selected[0][0]}
        ports = [p for p in graph.nodes[nid]["edges"] if p[0] in ids]
        if len(ids) == 2 and len(ports) == 2 and proof.get("source_branches_deleted") is False:
            anchors[nid] = {"ports": ports, "proof": deepcopy(proof)}
    return anchors


def _residual_components(graph, owner, anchors):
    owned = set()
    for edge in graph.edges:
        raw = graph.xy(edge["pixels"])
        adj = {transverse._edge_key(a, b) for a, b in zip(raw, raw[1:])}
        if adj and adj <= owner["source_adjacencies"]:
            owned.add(edge["id"])
    seeds = sorted({p[0] for nid in anchors for p in graph.nodes[nid]["edges"] if p[0] not in owned})
    seen, components = set(), []
    for seed in seeds:
        if seed in seen:
            continue
        queue, edges, nodes, failed = [seed], set(), set(), None
        while queue:
            eid = queue.pop()
            if eid in edges or eid in owned:
                continue
            edges.add(eid)
            for nid in graph.edges[eid]["nodes"]:
                nodes.add(nid)
                queue.extend(p[0] for p in graph.nodes[nid]["edges"] if p[0] not in owned and p[0] not in edges)
            if len(edges) > POLICY["maximum_component_edges"] or len(nodes) > POLICY["maximum_component_nodes"]:
                failed = "RESIDUAL_COMPONENT_EXCEEDS_FINITE_RESOURCE_BOUND"
                break
        seen.update(edges)
        if not edges:
            continue
        points = graph.xy([p for eid in edges for p in graph.edges[eid]["pixels"]])
        if float(np.ptp(points, axis=0).max()) > POLICY["maximum_component_extent_px"]:
            failed = "RESIDUAL_COMPONENT_EXCEEDS_FINITE_SPATIAL_BOUND"
        if any(graph.edges[e]["nodes"][0] == graph.edges[e]["nodes"][1] for e in edges):
            failed = "EXTERNAL_SOURCE_LOOP_REQUIRES_A_DIFFERENT_DECOMPOSITION_MODEL"
        # This model permits pixel cycles inside a proved solid core, while
        # preserving genuine inter-node cycles as explicit pending geometry.
        if len(edges) - len(nodes) + 1 != 0:
            failed = "RESIDUAL_MACRO_GRAPH_IS_NOT_A_TREE"
        ts = [nid for nid in nodes if len(graph.nodes[nid]["edges"]) == 3 and nid not in anchors]
        if not ts:
            continue  # Existing complete-free-ended planner owns this class.
        components.append({"edges": sorted(edges), "nodes": sorted(nodes), "T_nodes": sorted(ts),
                           "anchor_nodes": sorted(nodes & anchors.keys()), "reason": failed})
    return components


def _walk_decomposition(graph, component, pairs, attachments):
    remaining = set(component["edges"])
    endpoints = []
    for nid in component["nodes"]:
        node = graph.nodes[nid]
        for port in node["edges"]:
            if port[0] not in remaining:
                continue
            if (nid, port) in attachments:
                endpoints.append((nid, port, "OBSERVED_COMPLETE_STROKE_ATTACHMENT"))
            elif (node.get("terminal") or {}).get("kind") == "OBSERVED_FREE_SOURCE_ENDPOINT":
                endpoints.append((nid, port, "OBSERVED_FREE_SOURCE_ENDPOINT"))
    endpoint_map = {(nid, port): kind for nid, port, kind in endpoints}
    routes = []
    for start, first, kind in sorted(endpoints):
        if first[0] not in remaining:
            continue
        nid, port, edge_ids, pixels, nodes, core_routes = start, first, [], [], [start], []
        for _ in range(POLICY["maximum_component_edges"] + 1):
            if port[0] not in remaining:
                raise ValueError("DECOMPOSITION_REUSES_OR_LOSES_EXTERNAL_EDGE")
            remaining.remove(port[0])
            part = list(graph.oriented(port))
            if pixels:
                alternatives = _all_core_routes(graph, nid, pixels[-1], part[0])
                core_routes.append({"node_id": nid, "all_simple_core_routes_px": [graph.xy(r).tolist() for r in alternatives],
                                    "canonical_encoding_only": True})
                pixels += alternatives[0][1:] + part[1:]
            else:
                pixels = part
            edge_ids.append(port[0])
            nid = graph.edges[port[0]]["nodes"][1 - port[1]]
            incoming = (port[0], 1 - port[1])
            nodes.append(nid)
            if (nid, incoming) in endpoint_map:
                routes.append({"source_graph_edge_ids": edge_ids, "source_node_ids": nodes,
                               "source_pixels": pixels, "core_route_alternatives": core_routes,
                               "terminals": [{"node_id": start, "port": list(first), "kind": kind},
                                             {"node_id": nid, "port": list(incoming), "kind": endpoint_map[(nid, incoming)]}]})
                break
            if (nid, incoming) not in pairs:
                raise ValueError("DECOMPOSITION_HAS_AN_UNEXPLAINED_PORT")
            port = pairs[(nid, incoming)]
        else:
            raise ValueError("DECOMPOSITION_ROUTE_EXCEEDS_BOUND")
    if remaining:
        raise ValueError("DECOMPOSITION_LEAVES_UNEXPLAINED_EDGES")
    return routes


def _fit_native(source, raw, endpoints):
    raw = np.asarray(raw, float)
    points = raw.copy()
    points[0], points[-1] = endpoints
    # Consecutive equal source centres carry no native segment.
    keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-10]
    points = points[keep]
    reverse = tuple(points[-1]) < tuple(points[0])
    if reverse:
        points = points[::-1]
    count = len(points)
    costs = [count + 1] * count
    previous = [-1] * count
    costs[0] = 0
    for end in range(1, count):
        for start in range(end):
            if costs[start] + 1 > costs[end]:
                continue
            a, b = points[start], points[end]
            span = b - a
            size = float(span @ span)
            if size <= 1e-12:
                continue
            samples = points[start:end + 1]
            fractions = (samples - a) @ span / size
            projected = a + np.clip(fractions, 0, 1)[:, None] * span
            if (float(np.linalg.norm(samples - projected, axis=1).max()) > POLICY["maximum_native_source_distance_px"]
                    or np.min(np.diff(fractions)) < -1e-9
                    or not _black_segment(source, a, b)):
                continue
            if costs[start] + 1 < costs[end]:
                costs[end], previous[end] = costs[start] + 1, start
    if previous[-1] < 0:
        raise ValueError("NO_MONOTONE_ALL_ORIGINAL_INK_NATIVE_ENCODING")
    indices = [count - 1]
    while indices[-1]:
        indices.append(previous[indices[-1]])
    indices.reverse()
    vertices = points[indices].tolist()
    if reverse:
        vertices.reverse()
    if len(vertices) > POLICY["maximum_control_vertices"]:
        raise ValueError("NATIVE_PATH_HAS_TOO_MANY_CONTROL_VERTICES")
    return {"points": vertices, "bulges": [0.0] * len(vertices), "closed": False}


def _attachment_endpoint(source, graph, terminal, host_geometry):
    nid, port = terminal["node_id"], tuple(terminal["port"])
    samples = np.asarray(_directions(graph, port)[-1]["source_points_px"])
    # Use the observed finite incoming arm; its outward ray may reach the
    # separately fitted host only inside this actual original junction core.
    a, u = samples[0], _unit(samples[-1] - samples[0])
    core = graph.xy(graph.nodes[nid]["pixels"])
    low, high = core.min(axis=0) - 0.5, core.max(axis=0) + 0.5
    candidates = []
    for index, (c, d) in enumerate(zip(host_geometry["points"], host_geometry["points"][1:])):
        c, d = np.asarray(c), np.asarray(d)
        matrix = np.column_stack((u, -(d - c)))
        if abs(float(np.linalg.det(matrix))) < 1e-9:
            continue
        t, fraction = np.linalg.solve(matrix, c - a)
        point = a + t * u
        if (-1e-9 <= fraction <= 1 + 1e-9 and t <= 0.5
                and np.all(point >= low) and np.all(point <= high)
                and _black_segment(source, a, point)):
            if not any(np.linalg.norm(point - np.asarray(p["native_endpoint_px"])) < 1e-7 for p in candidates):
                candidates.append({"native_endpoint_px": point.tolist(), "host_segment_index": index,
                                   "finite_host_fraction": float(fraction), "incoming_ray_parameter_px": float(t),
                                   "closed_source_pixel_cells": _segment_cells(a, point), "all_original_ink": True})
    if len(candidates) != 1:
        raise ValueError("ATTACHED_END_HAS_NO_UNIQUE_SOURCE_SUPPORTED_FINITE_HOST_INTERSECTION")
    return candidates[0]


def _free_cap(source, graph, terminal):
    """Measure only the original tip's local ink component, preserving gaps."""
    port = tuple(terminal["port"])
    endpoint = graph.xy(graph.oriented(port))[0]
    directions = _directions(graph, port)
    limit = transverse.POLICY["maximum_endpoint_cap_extent_px"]
    radius = int(math.ceil(limit)) + 2
    x, y = np.rint(endpoint).astype(int)
    left, top = max(0, x - radius), max(0, y - radius)
    right, bottom = min(source.shape[1], x + radius + 1), min(source.shape[0], y + radius + 1)
    ink = source[top:bottom, left:right] < paths.POLICY["source_threshold"]
    components, count = label(ink, structure=np.ones((3, 3), int))
    own_label = int(components[y - top, x - left])
    observed = []
    own_points = None
    for value in range(1, count + 1):
        rows, cols = np.nonzero(components == value)
        points = np.column_stack((cols + left, rows + top))
        observed.append({"component_label": value, "source_pixel_cells": points.tolist(),
                         "contains_actual_free_endpoint": value == own_label})
        if value == own_label:
            own_points = points
    if own_points is None:
        raise ValueError("FREE_ENDPOINT_HAS_NO_ORIGINAL_INK_COMPONENT")
    checks = []
    for direction in directions:
        outward = -np.asarray(direction["vector"])
        normal = np.array([-outward[1], outward[0]])
        relative = own_points - endpoint
        aligned = abs(relative @ normal) <= 1.5
        extent = max(0.0, float(np.max(relative[aligned] @ outward, initial=0.0)))
        checks.append({"outward_source_tangent": outward.tolist(), "source_cap_forward_extent_px": extent,
                       "pass": extent <= limit and direction["chord_px"] >= POLICY["minimum_observed_direction_chord_px"]})
    return {"method": "original_connected_tip_cap_along_all_finite_observed_terminal_tangents",
            "source_endpoint_px": endpoint.tolist(), "raw_ink_box_xyxy_px": [left, top, right, bottom],
            "raw_ink_mask": ink.astype(int).tolist(), "all_original_ink_components": observed,
            "finite_direction_evidence": directions, "cap_observations": checks,
            "white_gaps_not_filled_and_neighbor_components_not_erased": True,
            "pass": all(row["pass"] for row in checks)}


def _geometry_routes(source, graph, routes, owner, core_proofs):
    passing = {}
    for index, route in enumerate(routes):
        for nid in route["source_node_ids"][1:-1]:
            passing.setdefault(nid, []).append(index)
    dependencies = {}
    for index, route in enumerate(routes):
        refs = {}
        for end, terminal in enumerate(route["terminals"]):
            if terminal["kind"] == "OBSERVED_COMPLETE_STROKE_ATTACHMENT":
                hosts = passing.get(terminal["node_id"], [])
                if len(hosts) != 1 or hosts[0] == index:
                    raise ValueError("ATTACHED_END_HAS_NO_DISTINCT_COMPLETE_HOST_ROUTE")
                refs[end] = hosts[0]
        dependencies[index] = refs
    built, queue = {}, set(range(len(routes)))
    while queue:
        ready = [index for index in sorted(queue) if set(dependencies[index].values()) <= built.keys()]
        if not ready:
            raise ValueError("TERMINAL_GEOMETRY_DEPENDENCIES_REQUIRE_A_DIFFERENT_JOINT_MODEL")
        for index in ready:
            route = routes[index]
            raw_pixels = list(route["source_pixels"])
            endpoints = graph.xy([raw_pixels[0], raw_pixels[-1]]).tolist()
            terminal_proofs = deepcopy(route["terminals"])
            for end, host_index in dependencies[index].items():
                proof = _attachment_endpoint(source, graph, route["terminals"][end], built[host_index]["representation"])
                endpoints[end] = proof["native_endpoint_px"]
                nid = route["terminals"][end]["node_id"]
                pixel = min(graph.nodes[nid]["pixels"], key=lambda p: (float(np.linalg.norm(graph.xy([p])[0] - endpoints[end])), p))
                if end == 0:
                    alternatives = _all_core_routes(graph, nid, pixel, raw_pixels[0])
                    extra = alternatives[0]
                    raw_pixels = extra[:-1] + raw_pixels
                else:
                    alternatives = _all_core_routes(graph, nid, raw_pixels[-1], pixel)
                    extra = alternatives[0]
                    raw_pixels += extra[1:]
                terminal_proofs[end].update(proof, host_path_index=host_index,
                                           host_source_graph_edge_ids=routes[host_index]["source_graph_edge_ids"],
                                           terminal_core_route_alternatives_px=[graph.xy(r).tolist() for r in alternatives],
                                           complete_host_and_guest_proved_from_one_simultaneous_decomposition=True)
            raw = graph.xy(raw_pixels)
            length = paths._length(raw)
            if not POLICY["minimum_stroke_length_px"] <= length <= POLICY["maximum_stroke_length_px"]:
                raise ValueError("COMPLETE_STROKE_LENGTH_OUTSIDE_FINITE_MODEL")
            geometry = _fit_native(source, raw, endpoints)
            core_encodings = [points for row in route["core_route_alternatives"]
                              for points in row["all_simple_core_routes_px"]]
            core_encodings += [points for terminal in terminal_proofs
                               for points in terminal.get("terminal_core_route_alternatives_px", [])]
            maximum_core_encoding_residual = max((paths._maximum_point_to_polyline_distance(
                np.asarray(points), np.asarray(geometry["points"])) for points in core_encodings), default=0.0)
            if maximum_core_encoding_residual > POLICY["maximum_native_source_distance_px"]:
                raise ValueError("CORE_ENCODINGS_DO_NOT_ALL_SUPPORT_THE_SAME_FINITE_NATIVE_PATH")
            for end, terminal in enumerate(terminal_proofs):
                terminal["native_endpoint_px"] = endpoints[end]
                terminal["source_endpoint_px"] = raw[[0, -1]][end].tolist()
                if terminal["kind"] == "OBSERVED_FREE_SOURCE_ENDPOINT":
                    cap = _free_cap(source, graph, terminal)
                    terminal["source_cap_evidence"] = cap
                    if not cap["pass"]:
                        raise ValueError("FREE_ENDPOINT_HAS_UNEXPLAINED_ORIGINAL_CAP")
            row = {"path_role": "COMPLETE_ATTACHED_GRAPH_STROKE", "source_graph_edge_ids": route["source_graph_edge_ids"],
                   "source_node_ids": route["source_node_ids"], "source_path_px": raw.tolist(),
                   "source_path_length_px": length, "representation": geometry,
                   "endpoint_source_points_px": [raw[0].tolist(), raw[-1].tolist()],
                   "native_endpoint_points_px": endpoints, "endpoint_evidence": terminal_proofs,
                   "core_route_alternatives": route["core_route_alternatives"],
                   "contact_continuations": [core_proofs[n] for n in route["source_node_ids"] if n in core_proofs],
                   "required_crossing_path_id": owner["id"], "required_crossing_path_binding": deepcopy(owner["binding"]),
                   "original_branches_retained": True, "text_content_decision": "NOT_PERFORMED",
                   "all_native_closed_cells_original_ink": True,
                   "all_core_encodings_support_this_native_geometry": True,
                   "maximum_core_encoding_native_residual_px": maximum_core_encoding_residual,
                   "source_core_walk_is_an_encoding_not_exclusive_pixel_ownership": True}
            row["stroke_id"] = stable_id("GRAPHSTROKE", geometry)
            built[index] = row
            queue.remove(index)
    return [built[i] for i in range(len(routes))]


def _native_conflicts(rows, prior_objects, source):
    from scipy.spatial import cKDTree

    from .completion_stages import _existing_line_members, _quarantine_native_duplicate_groups
    from .text_contact_adoption import _as_path, _existing_line_covers

    proposals = [{"id": row["stroke_id"], "kind": "CONNECTION_PATH", "geometry": row["representation"],
                  "source_evidence": {"source_path_points": row["source_path_px"]}}
                 for row in rows]
    members = _existing_line_members(prior_objects)
    old = [_as_path(o) for o in members]
    old += [_as_path(o) if o["kind"] == "ARC" else o for o in prior_objects
            if o["kind"] in ("ARC", "CONNECTION_PATH")]
    result = _quarantine_native_duplicate_groups(proposals, old)
    # The general quarantine intentionally leaves whole-path equivalence to
    # ordinary adoption.  This all-or-pending stage must reject it explicitly,
    # including reversed endpoints, segmentation and lines inside old blocks.
    equivalent, dense = [], {}
    for obj in [*proposals, *old]:
        dense[id(obj)] = paths._dense_geometry(obj["geometry"])
    adequate = set()
    for i, proposed in enumerate(proposals):
        for other in [*old, *proposals[i + 1:]]:
            a, b = dense[id(proposed)], dense[id(other)]
            distance = max(float(cKDTree(a).query(b)[0].max()), float(cKDTree(b).query(a)[0].max()))
            if distance <= paths.POLICY["polyline_approximation_px"]:
                equivalent.append({"object_ids": [proposed["id"], other["id"]],
                                   "symmetric_native_distance_px": distance})
                adequate.add(proposed["id"])
        for member in members:
            if _existing_line_covers(source, proposed, member):
                adequate.add(proposed["id"])
                equivalent.append({"object_ids": [proposed["id"], member["id"]],
                                   "retained_line_member_covers_complete_original_stroke": True})
    result["equivalent_complete_native_paths_or_existing_line_members"] = equivalent
    return result, sorted(adequate)


def _source_responsibility(rows, prior_objects, cores):
    """External source adjacencies are exclusive; only proved cores may share."""
    allowed = {transverse._edge_key(a, b)
               for core in cores.values() for a, b in core["all_source_core_adjacencies"]}
    groups = [(row["stroke_id"], True, {transverse._edge_key(a, b)
               for a, b in zip(row["source_path_px"], row["source_path_px"][1:])}) for row in rows]
    for obj in prior_objects:
        raw = obj.get("source_evidence", {}).get("source_path_points") or []
        if raw:
            groups.append((obj["id"], False, {transverse._edge_key(a, b) for a, b in zip(raw, raw[1:])}))
    shared, conflicts = [], []
    for (a, fresh_a, edges_a), (b, fresh_b, edges_b) in itertools.combinations(groups, 2):
        if not (fresh_a or fresh_b):
            continue
        overlap = edges_a & edges_b
        if not overlap:
            continue
        row = {"object_ids": [a, b], "shared_adjacencies": [list(edge) for edge in sorted(overlap)],
               "all_shared_source_is_inside_proved_original_cores": overlap <= allowed}
        shared.append(row)
        if not row["all_shared_source_is_inside_proved_original_cores"]:
            conflicts.append(row)
    return {"pass": not conflicts, "shared_source_checks": shared, "conflicts": conflicts,
            "all_other_macro_source_edges_owned_once": True,
            "unselected_core_adjacencies_remain_classified_as_original_solid_junction_support": True}


def _finite_intersections(left, right):
    if any(float(b) for geometry in (left, right) for b in geometry["bulges"]):
        raise ValueError("EXACT_NATIVE_CONTACT_OF_CURVED_OWNER_REQUIRES_DIFFERENT_MODEL")
    result = []
    for i, (a, b) in enumerate(zip(left["points"], left["points"][1:])):
        a, b = np.asarray(a, float), np.asarray(b, float)
        for j, (c, d) in enumerate(zip(right["points"], right["points"][1:])):
            c, d = np.asarray(c, float), np.asarray(d, float)
            matrix = np.column_stack((b - a, -(d - c)))
            if abs(float(np.linalg.det(matrix))) < 1e-9:
                continue  # Positive coincident spans have a separate strict gate.
            u, v = np.linalg.solve(matrix, c - a)
            if -1e-9 <= u <= 1 + 1e-9 and -1e-9 <= v <= 1 + 1e-9:
                point = a + u * (b - a)
                if not any(np.linalg.norm(point - np.asarray(row["point_px"])) < 1e-7 for row in result):
                    result.append({"point_px": point.tolist(), "segment_indices": [i, j],
                                   "finite_segment_fractions": [float(u), float(v)]})
    return result


def _native_contacts(source, rows, owner, anchors, cores):
    geometries = [(row["stroke_id"], row["representation"], set(row["source_node_ids"])) for row in rows]
    geometries.append((owner["id"], owner["native_geometry"], set(anchors)))
    results = []
    for (aid, a, anodes), (bid, b, bnodes) in itertools.combinations(geometries, 2):
        expected = anodes & bnodes & cores.keys()
        intersections = _finite_intersections(a, b)
        classified = {nid: [] for nid in expected}
        unexpected = []
        for intersection in intersections:
            point = np.asarray(intersection["point_px"])
            supported = []
            for nid in expected:
                pixels = np.asarray(cores[nid]["source_core_pixels"])
                if (np.all(point >= pixels.min(axis=0) - 0.5)
                        and np.all(point <= pixels.max(axis=0) + 0.5)
                        and _black_segment(source, point, point)):
                    supported.append(nid)
            if len(supported) != 1:
                unexpected.append(intersection)
            else:
                classified[supported[0]].append(intersection)
        passed = not unexpected and all(len(hits) == 1 for hits in classified.values())
        results.append({"object_ids": [aid, bid], "expected_original_junction_ids": sorted(expected),
                        "finite_native_contacts": [{"node_id": nid, "contacts": hits}
                                                   for nid, hits in sorted(classified.items())],
                        "unexpected_contacts": unexpected, "pass": passed})
    return {"pass": all(row["pass"] for row in results), "pair_checks": results,
            "contacts_are_on_actual_finite_native_segments": True}


def _text_intersections(rows, prior_objects):
    boxes = paths._text_boxes(prior_objects)
    for obj in prior_objects:
        if obj["kind"] == "TEXT_GROUP":
            box = obj["geometry"].get("bbox_xyxy_px")
            if box:
                boxes.append((obj["id"], box))
    return [{"path_id": row["stroke_id"], "text_id": oid}
            for row in rows for oid, box in boxes
            if contact._inside(np.asarray(row["source_path_px"]), box).sum() >= 3]


def plan_attached_stroke_graph(gray, roi, prior_objects, *, source_graph=None):
    source = np.asarray(gray)
    context = source_graph or contact.build_text_contact_source_graph(source, roi)
    graph = context.graph
    x0, y0, x1, y1 = context.crop_bbox
    if list(map(int, roi)) != list(graph.roi) or hashlib.sha256(source[y0:y1, x0:x1].tobytes()).hexdigest() != context.source_crop_hash:
        raise ValueError("ATTACHED_STROKE_SOURCE_GRAPH_IDENTITY_CHANGED")
    bindings = [object_binding(o) for o in sorted(prior_objects, key=lambda o: o["id"])]
    if len({o["id"] for o in bindings}) != len(bindings):
        raise ValueError("DUPLICATE_PRIOR_OBJECT_ID")
    result = {"schema": SCHEMA, "policy": deepcopy(POLICY),
              "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "additional_producer_sha256": {"attached_stroke_ink.py": attached_ink.producer_sha256(),
                                              "attached_stroke_component.py": attached_component.producer_sha256(),
                                              "attached_stroke_width_exact.py": hashlib.sha256(Path(attached_width.__file__).read_bytes()).hexdigest(),
                                              "attached_stroke_contacts.py": prior_contacts.producer_sha256()},
              "roi_xyxy_px": list(map(int, roi)), "original_source_crop_xyxy_px": context.crop_bbox,
              "original_source_crop_array_sha256": context.source_crop_hash,
              "prior_object_bindings": bindings, "prior_object_bindings_sha256": _digest(bindings),
              "paths": [], "components": [], "pending": [], "source_pixels_modified": False,
              "original_source_pixels_modified": False, "transcription_supplied": False}
    owners, refusals = transverse._owners(source, context, bindings)
    result["owner_witness_refusals"] = refusals
    owner_anchors = {owner["id"]: _owner_nodes(graph, owner) for owner in owners}
    seen = set()
    for owner in owners:
        anchors = owner_anchors[owner["id"]]
        for component in _residual_components(graph, owner, anchors):
            key = tuple(component["edges"])
            if key in seen:
                continue
            seen.add(key)
            record = {"component_id": stable_id("GRAPHCOMP", [owner["id"], key]),
                      "required_crossing_path_id": owner["id"], "source_graph_edge_ids": component["edges"],
                      "source_node_ids": component["nodes"], "T_nodes": component["T_nodes"],
                      "anchor_nodes": component["anchor_nodes"], "decompositions": [],
                      "status": "PENDING", "source_pixels_modified": False}
            result["components"].append(record)
            try:
                competing_owners = sorted(other["id"] for other in owners if other["id"] != owner["id"]
                                          and any(nid in owner_anchors[other["id"]]
                                                  and set(owner_anchors[other["id"]][nid]["ports"]) == set(anchors[nid]["ports"])
                                                  for nid in component["anchor_nodes"]))
                record["competing_prior_owner_ids"] = competing_owners
                if competing_owners:
                    raise ValueError("MULTIPLE_FORMAL_OWNERS_CLAIM_THE_SAME_SOURCE_PORTS")
                if component["reason"]:
                    raise ValueError(component["reason"])
                if 3 ** len(component["T_nodes"]) > POLICY["maximum_decompositions"]:
                    raise ValueError("COMPLETE_ENUMERATION_EXCEEDS_RESOURCE_BOUND")
                tables, cores, fixed = {}, {}, {}
                for nid in component["nodes"]:
                    node = graph.nodes[nid]
                    ports = sorted(p for p in node["edges"] if p[0] in component["edges"])
                    if (node.get("terminal") or {}).get("kind") == "OBSERVED_FREE_SOURCE_ENDPOINT":
                        if len(ports) != 1:
                            raise ValueError("FREE_TERMINAL_HAS_MULTIPLE_SOURCE_PORTS")
                        continue
                    if node.get("terminal") or node.get("reason") == "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT":
                        raise ValueError("COMPONENT_REACHES_NONFREE_OR_UNOBSERVED_BOUNDARY")
                    cores[nid] = _core_proof(source, graph, nid)
                    if not cores[nid]["pass"]:
                        raise ValueError("CORE_HAS_UNEXPLAINED_HOLE_BRANCH_OR_EXTENT")
                    if nid in anchors:
                        if len(ports) != 2 or set(ports) & set(anchors[nid]["ports"]):
                            raise ValueError("FROZEN_OWNER_PORT_RESPONSIBILITY_MISMATCH")
                        tables[nid] = _node_directions(graph, nid)
                        proof = _pair_proof(tables[nid], ports)
                        if not proof["pass"]:
                            raise ValueError("RESIDUAL_CROSSING_PAIR_NOT_INDEPENDENTLY_PROVED")
                        fixed[(nid, ports[0])], fixed[(nid, ports[1])] = ports[1], ports[0]
                    elif len(ports) == 2 and len(node["edges"]) == 2:
                        fixed[(nid, ports[0])], fixed[(nid, ports[1])] = ports[1], ports[0]
                    elif len(ports) == 3 and len(node["edges"]) == 3:
                        tables[nid] = _node_directions(graph, nid)
                    else:
                        raise ValueError("UNSUPPORTED_SOURCE_PORT_OR_OWNER_CONFIGURATION")
                record["node_direction_evidence"] = [tables[n] for n in sorted(tables)]
                record["original_core_evidence"] = [cores[n] for n in sorted(cores)]
                choices = [[pair for pair in itertools.combinations(sorted(graph.nodes[nid]["edges"]), 2)]
                           for nid in component["T_nodes"]]
                eligible = []
                for index, combination in enumerate(itertools.product(*choices)):
                    pairs, attachments, rejected = dict(fixed), {}, []
                    descriptions = []
                    for nid, pair in zip(component["T_nodes"], combination):
                        a, b = pair
                        pairs[(nid, a)], pairs[(nid, b)] = b, a
                        single = next(p for p in graph.nodes[nid]["edges"] if p not in pair)
                        attachments[(nid, single)] = pair
                        proof = _pair_proof(tables[nid], pair)
                        observed = {tuple(row["port"]): row["observations"]
                                    for row in tables[nid]["all_observed_directions"]}
                        separation = min(min(_angle(x["vector"], y["vector"]),
                                             _angle(x["vector"], -np.asarray(y["vector"])))
                                         for paired in pair
                                         for x, y in zip(observed[single], observed[paired]))
                        descriptions.append({"node_id": nid, "continuous_pair": [list(a), list(b)],
                                             "attached_port": list(single), "direction_proof": proof,
                                             "minimum_attachment_axis_separation_deg": separation})
                        if not proof["pass"]:
                            rejected.append("FINITE_T_DIRECTION_OR_COMPETITION_NOT_UNIQUE")
                        if separation < POLICY["minimum_attachment_axis_separation_deg"]:
                            rejected.append("ATTACHMENT_NOT_SEPARATED_FROM_CONTINUOUS_SOURCE_AXIS")
                    routes = _walk_decomposition(graph, component, pairs, attachments)
                    candidate = {"index": index, "T_assignments": descriptions,
                                 "complete_route_edge_chains": [r["source_graph_edge_ids"] for r in routes],
                                 "complete_route_terminals": [r["terminals"] for r in routes],
                                 "all_external_edges_accounted_once": True,
                                 "route_count_derived_from_terminal_assignment": len(routes),
                                 "rejection_reasons": sorted(set(rejected)),
                                 "native_geometry_stage": "NOT_RUN_REJECTED_DIRECTION"}
                    record["decompositions"].append(candidate)
                    if not rejected:
                        eligible.append((candidate, routes))
                if len(eligible) != 1:
                    raise ValueError("COMPONENT_HAS_NO_UNIQUE_COMPLETE_DIRECTION_DECOMPOSITION")
                selected, routes = eligible[0]
                rows = _geometry_routes(source, graph, routes, owner, cores)
                # Evidence is retained before every new adoption gate.  A failed
                # endpoint never turns into a missing explanation or a silently
                # salvaged subset of the old joint component.
                record["selected_decomposition_index"] = selected["index"]
                record["candidate_paths"] = rows
                record["candidate_status"] = "GEOMETRY_CANDIDATES_NOT_FORMAL_OBJECTS"
                rows, shared_vertex_construction = attached_component.materialize_shared_vertices(
                    source, graph, rows, cores)
                record["shared_finite_vertex_construction"] = shared_vertex_construction
                record["candidate_paths"] = rows
                component_proof = attached_component.prove_finite_component(
                    source, graph, rows, owner=owner, cores=cores)
                component_proof["original_source_crop_xyxy_px"] = context.crop_bbox
                component_proof["original_source_crop_array_sha256"] = context.source_crop_hash
                record["finite_component_responsibility"] = component_proof
                component_proof_hash = _digest(_plain(component_proof))
                raw_checks = []
                for row in rows:
                    for end_index, terminal in enumerate(row["endpoint_evidence"]):
                        if "host_path_index" not in terminal:
                            continue
                        host = rows[terminal["host_path_index"]]
                        terminal["host_path_id"] = host["stroke_id"]
                        endpoint = next((item for item in component_proof.get("endpoints", [])
                                         if item["guest_id"] == row["stroke_id"] and item["end"] == end_index), {})
                        proof = {"schema": "source-finite-component-endpoint-reference-v1",
                                 "component_responsibility_sha256": component_proof_hash,
                                 "guest_id": row["stroke_id"], "host_id": host["stroke_id"],
                                 "pass": component_proof["pass"],
                                 "status": "PROVED_TERMINAL" if component_proof["pass"] else component_proof["status"],
                                 "failure_reasons": component_proof["failure_reasons"],
                                 "complete_pixel_accounting": component_proof.get("complete_pixel_accounting", False),
                                 "junction_normalization": {"canonical_native_endpoint_proved": component_proof["pass"],
                                                            "physical_subpixel_termination_identifiable": False},
                                 "endpoint_evidence": deepcopy(endpoint)}
                        terminal["attached_raw_ink_responsibility"] = proof
                        raw_checks.append({"guest_id": row["stroke_id"], "host_id": host["stroke_id"],
                                           "source_node_id": terminal["node_id"], "pass": proof["pass"],
                                           "status": proof["status"], "failure_reasons": proof["failure_reasons"]})
                record["attachment_responsibility_checks"] = raw_checks
                failed_gates = []
                if not shared_vertex_construction["pass"]:
                    failed_gates.append("EXACT_SHARED_FINITE_VERTEX_CONSTRUCTION_NOT_ESTABLISHED")
                if not all(check["pass"] for check in raw_checks):
                    failed_gates.append("ATTACHED_ENDPOINT_ORIGINAL_INK_RESPONSIBILITY_NOT_PROVED")
                hits = _text_intersections(rows, prior_objects)
                if hits:
                    record["existing_text_source_conflicts"] = hits
                    failed_gates.append("EXISTING_COMPLETE_TEXT_OWNS_SOURCE_IN_THIS_COMPONENT")
                conflicts, adequate = _native_conflicts(rows, prior_objects, source)
                record["native_duplicate_check"] = conflicts
                if conflicts["quarantined_ids"] or adequate:
                    failed_gates.append("COMPLETE_GRAPH_COMPONENT_HAS_EXISTING_OR_DUPLICATE_NATIVE_GEOMETRY")
                responsibility = _source_responsibility(rows, prior_objects, cores)
                record["source_responsibility"] = responsibility
                if not responsibility["pass"]:
                    failed_gates.append("ANOTHER_OBJECT_OWNS_SOURCE_OUTSIDE_PROVED_SHARED_CORES")
                contacts = _native_contacts(source, rows, owner, anchors, cores)
                record["native_contact_check"] = contacts
                if not contacts["pass"]:
                    failed_gates.append("ACTUAL_FINITE_NATIVE_CONTACTS_DO_NOT_MATCH_SOURCE_GRAPH")
                prior_check = prior_contacts.check_prior_native_contacts(
                    source, rows, prior_objects, graph=graph, cores=cores, owner=owner, anchors=anchors)
                record["prior_native_contact_check"] = prior_check
                if not prior_check["pass"]:
                    failed_gates.append("ACTUAL_FINITE_PRIOR_NATIVE_CONTACTS_NOT_SOURCE_PROVED")
                crossed = [r for r in rows if set(r["source_node_ids"]) & set(component["anchor_nodes"])]
                for row in crossed:
                    axis = _unit(np.asarray(row["native_endpoint_points_px"])[1] - row["native_endpoint_points_px"][0])
                    companions = [other for other in crossed if other is not row
                                  and min(_angle(axis, _unit(np.asarray(other["native_endpoint_points_px"])[1] - other["native_endpoint_points_px"][0])),
                                          _angle(-axis, _unit(np.asarray(other["native_endpoint_points_px"])[1] - other["native_endpoint_points_px"][0])))
                                  <= POLICY["maximum_companion_axis_angle_deg"]]
                    if len(companions) < POLICY["minimum_parallel_crossing_companions"]:
                        failed_gates.append("NO_INDEPENDENT_COMPLETE_PARALLEL_CROSSING_COMPANION")
                    row["parallel_crossing_companion_ids"] = [r["stroke_id"] for r in companions]
                record["failed_adoption_gates"] = sorted(set(failed_gates))
                if failed_gates:
                    selected["native_geometry_stage"] = "PENDING_COMPLETE_CANDIDATE_RESPONSIBILITY"
                    raise ValueError(failed_gates[0])
                selected["native_geometry_stage"] = "PASS_ALL_ORIGINAL_INK_COMPLETE_AND_INDEPENDENT"
                record["candidate_status"] = "COMPLETE_COMPONENT_ADOPTED_AFTER_ALL_GATES"
                record.update(status="UNIQUE_COMPLETE_GRAPH_DECOMPOSITION", selected_decomposition_index=selected["index"],
                              new_complete_path_ids=[row["stroke_id"] for row in rows],
                              all_shared_core_adjacencies_preserved=True, unexplained_external_source_edges=[])
                for row in rows:
                    row["component_id"] = record["component_id"]
                    row["component_path_ids"] = record["new_complete_path_ids"]
                    for terminal in row["endpoint_evidence"]:
                        if "host_path_index" in terminal:
                            terminal["host_path_id"] = rows[terminal["host_path_index"]]["stroke_id"]
                    result["paths"].append(row)
            except (ValueError, KeyError, IndexError, np.linalg.LinAlgError) as exc:
                record["reason"] = str(exc)
                result["pending"].append({"component_id": record["component_id"], "reason": str(exc),
                                          "source_graph_edge_ids": component["edges"]})
    return _plain(result)


def verify_attached_stroke_graph_plan(gray, roi, plan, *, source_graph=None):
    if plan.get("schema") != SCHEMA or plan.get("prior_object_bindings_sha256") != _digest(plan.get("prior_object_bindings")):
        return {"pass": False, "reason": "ATTACHED_GRAPH_PRIOR_BINDING_INTEGRITY_FAILED", "checks": {"prior_bindings": False}}
    try:
        replay = plan_attached_stroke_graph(gray, roi, plan["prior_object_bindings"], source_graph=source_graph)
        checks = {key: plan.get(key) == value for key, value in replay.items()}
        return {"pass": all(checks.values()), "checks": checks,
                "reason": "EXACT_ATTACHED_GRAPH_SOURCE_REPLAY" if all(checks.values()) else "ATTACHED_GRAPH_SOURCE_REPLAY_MISMATCH",
                "replayed_paths": replay["paths"], "new_OCR_calls": 0}
    except (ValueError, KeyError, TypeError) as exc:
        return {"pass": False, "checks": {}, "reason": "ATTACHED_GRAPH_SOURCE_REPLAY_ERROR", "detail": str(exc)}


def complete_attached_strokes(gray, roi, source_sha, objects, out, *, source_graph=None):
    from .text_contact_adoption import _native_object

    plan = plan_attached_stroke_graph(gray, roi, objects, source_graph=source_graph)
    key = _digest(plan)
    adopted, decisions = [], []
    for index, row in enumerate(plan["paths"]):
        kind, geometry = _native_object(row["representation"])
        obj = {"id": row["stroke_id"], "kind": kind, "layer": "SHORT_STROKE", "geometry": geometry,
               "source_evidence": {"source_path_points": deepcopy(row["source_path_px"]),
                                   "original_source_crop_xyxy_px": plan["original_source_crop_xyxy_px"],
                                   "original_source_crop_array_sha256": plan["original_source_crop_array_sha256"],
                                   "source_pixels_modified": False,
                                   FIELD: {"schema": "source-attached-stroke-native-v3-component-exact", "source_sha256": source_sha,
                                           "plan_sha256": key, "path_index": index, "path_sha256": _digest(row), "path": deepcopy(row)}},
               "editing_scope": "one complete independent source stroke; attached and crossing strokes remain separate",
               "status": "SOURCE_SUPPORTED_COMPLETE_ATTACHED_GRAPH_STROKE"}
        adopted.append(obj)
        decisions.append({"id": obj["id"], "adopted": True, "decision": "ADD_COMPLETE_INDEPENDENT_GRAPH_STROKE",
                          "component_id": row["component_id"], "native_kind": kind, "retired_ids": []})
    result = {"schema": "source-attached-stroke-adoption-v3-component-exact", "source_sha256": source_sha,
              "roi_xyxy_px": list(roi), "plan": plan, "objects": adopted,
              "prior_object_bindings": plan["prior_object_bindings"], "decisions": decisions,
              "retired_ids": [], "pending": deepcopy(plan["pending"]), "new_OCR_calls": 0}
    save_json(Path(out) / "plan.json", plan)
    save_json(Path(out) / "adoption.json", result)
    return result
