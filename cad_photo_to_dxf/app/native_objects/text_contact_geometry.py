"""Original-source paths through a bounded text observation.

This module knows no transcription, page name, case identifier or target answer.
It only proposes complete, independently editable graphic paths.  Recognition
may use the returned local line mask, but that derived mask is never evidence
that any particular character exists in the original scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import hashlib
import heapq
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

from . import connections as paths


SCHEMA = "source-text-contact-path-plan-v1"
POLICY = {
    "version": "bounded-source-direction-contact-v2-outside-word-free-ends",
    "minimum_anchor_length_heights": 1.25,
    "minimum_anchor_length_px": 24.0,
    "maximum_contact_extension_heights": 0.7,
    "direction_span_px": 14.0,
    "lookahead_span_px": 48.0,
    "maximum_direction_deviation_deg": 20.0,
    "minimum_direction_margin_deg": 18.0,
    "maximum_lookahead_local_turn_deg": 28.0,
    "maximum_lookahead_edges": 8,
    "maximum_route_edges": 100,
    "maximum_seed_edges": 40,
    "minimum_complete_length_heights": 2.5,
    "maximum_mask_normal_px": 2.0,
    "maximum_contact_cluster_heights": 2.0,
    "maximum_contact_ink_normal_px": 2.0,
    "maximum_microcore_pixels": 48,
    "maximum_microcore_extent_px": 16,
    "maximum_control_vertices": 256,
    "maximum_round_contact_stub_px": 8.0,
    "maximum_round_stub_deviation_deg": 45.0,
    "minimum_round_stub_other_branch_deviation_deg": 75.0,
    "free_terminal_inside_text_seed_requires_independent_identity": True,
}


@dataclass
class ContactSourceGraph:
    graph: object
    rounds: list
    crop_bbox: list
    source_crop_hash: str
    thinning_counts: list


def build_text_contact_source_graph(gray, roi):
    """Build one reusable unmodified graph for the requested ordinary ROI."""
    source = np.asarray(gray)
    if source.ndim != 2:
        raise ValueError("CONTACT_SOURCE_MUST_BE_GRAYSCALE")
    x0, y0, x1, y1 = map(int, roi)
    margin = paths.POLICY["context_px"]
    ox, oy = max(0, x0 - margin), max(0, y0 - margin)
    rx, by = min(source.shape[1], x1 + margin), min(source.shape[0], y1 + margin)
    crop = source[oy:by, ox:rx]
    ink = crop < paths.POLICY["source_threshold"]
    origin = np.array([ox, oy])
    started = time.process_time()
    rounds = paths._round_boundaries(ink, origin)
    skel, counts = paths._thinning(ink, started)
    graph = paths._SourceGraph(skel, origin, rounds, roi, started, source_ink=ink)
    return ContactSourceGraph(
        graph,
        rounds,
        [ox, oy, rx, by],
        hashlib.sha256(crop.tobytes()).hexdigest(),
        counts,
    )


def _inside(points, box):
    p = np.asarray(points)
    return (
        (p[:, 0] >= box[0])
        & (p[:, 0] < box[2])
        & (p[:, 1] >= box[1])
        & (p[:, 1] < box[3])
    )


def _tail_direction(graph, pixels):
    p = graph.xy(pixels)
    lengths = np.linalg.norm(np.diff(p, axis=0), axis=1)
    index = (
        len(p)
        - 1
        - int(
            np.searchsorted(
                np.r_[0, lengths[::-1].cumsum()], POLICY["direction_span_px"]
            )
        )
    )
    index = max(0, index)
    vector = p[-1] - p[index]
    norm = np.linalg.norm(vector)
    return None if norm < 4 else vector / norm


def _core_route(graph, node_id, start, end):
    """Use only original local ink, including raster-split internal edges.

    A dilated junction component can contain disconnected axial subcores,
    linked by tiny original self-loop edges.  They are graph adjacencies, not
    missing white pixels.  Returning one shared contact route never erases the
    other branches and does not give the line exclusive ownership of the core.
    """
    allowed = set(graph.nodes[node_id]["pixels"])
    for eid, _ in graph.nodes[node_id]["edges"]:
        edge = graph.edges[eid]
        if edge["nodes"] == [node_id, node_id] and edge["length"] <= 6.0:
            allowed.update(edge["pixels"])
    if start not in allowed or end not in allowed:
        raise ValueError("CONTACT_CORE_PORT_OUTSIDE_ORIGINAL_NODE")
    pending, parents = deque([start]), {start: None}
    while pending:
        current = pending.popleft()
        if current == end:
            route = []
            while current is not None:
                route.append(current)
                current = parents[current]
            return route[::-1]
        for other in graph.neighbors(current):
            if other in allowed and other not in parents:
                parents[other] = current
                pending.append(other)
    raise ValueError("CONTACT_SOURCE_CORE_ROUTE_NOT_CONNECTED")


def _lookahead_routes(graph, node_id, port, excluded):
    """Retain every original branch while observing a bounded outgoing tangent."""
    pending = [(node_id, port, [], [], 0.0)]
    result = []
    while pending and len(result) < 64:
        nid, current, pixels, ports, length = pending.pop()
        if current[0] in excluded or current[0] in [p[0] for p in ports]:
            continue
        edge_pixels = graph.oriented(current)
        if pixels:
            try:
                core = _core_route(graph, nid, pixels[-1], edge_pixels[0])
            except ValueError:
                continue
            pixels = pixels + core[1:] + edge_pixels[1:]
        else:
            pixels = list(edge_pixels)
        ports = ports + [current]
        length = paths._length(graph.xy(pixels))
        end_id = graph.edges[current[0]]["nodes"][1 - current[1]]
        end_node = graph.nodes[end_id]
        if length >= POLICY["lookahead_span_px"] or end_node["terminal"]:
            p = graph.xy(pixels)
            cumulative = np.r_[0, np.linalg.norm(np.diff(p, axis=0), axis=1).cumsum()]
            index = min(
                len(p) - 1,
                int(np.searchsorted(cumulative, POLICY["direction_span_px"])),
            )
            vector = p[index] - p[0]
            norm = np.linalg.norm(vector)
            if norm >= 4:
                last_index = min(
                    len(p) - 1,
                    int(np.searchsorted(cumulative, POLICY["lookahead_span_px"])),
                )
                samples = np.arange(
                    0.0, cumulative[last_index] + 0.01, POLICY["direction_span_px"]
                )
                indices = np.minimum(len(p) - 1, np.searchsorted(cumulative, samples))
                sample_points = p[indices]
                vectors = np.diff(sample_points, axis=0)
                lengths = np.linalg.norm(vectors, axis=1)
                directions = vectors[lengths > 3] / lengths[lengths > 3, None]
                turns = [
                    math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))
                    for a, b in zip(directions, directions[1:])
                ]
                result.append(
                    {
                        "ports": ports,
                        "pixels": pixels,
                        "direction": vector / norm,
                        "observed_span_px": float(cumulative[index]),
                        "full_observed_span_px": length,
                        "maximum_local_turn_deg": max(turns, default=0.0),
                        "lookahead_terminal": end_node["terminal"],
                        "lookahead_end_px": p[-1].tolist(),
                    }
                )
            continue
        if len(ports) >= POLICY["maximum_lookahead_edges"]:
            continue
        incoming = (current[0], 1 - current[1])
        choices = (
            [end_node["pairing"][incoming]]
            if incoming in end_node["pairing"]
            else [p for p in end_node["edges"] if p != incoming]
        )
        for candidate in choices:
            pending.append((end_id, candidate, pixels, ports, length))
    return result


def _contact_choice(graph, node_id, incoming, route, edge_ids, contact_box):
    node = graph.nodes[node_id]
    if not _inside(np.asarray([node["center"]]), contact_box)[0]:
        return None, {"reason": "UNRESOLVED_BRANCH_OUTSIDE_TEXT_CONTACT_CONTEXT"}
    direction = _tail_direction(graph, route)
    if direction is None:
        return None, {"reason": "INSUFFICIENT_ORIGINAL_INCOMING_DIRECTION"}
    scored = []
    for port in node["edges"]:
        if port == incoming or port[0] in edge_ids:
            continue
        for look in _lookahead_routes(graph, node_id, port, set(edge_ids)):
            if (
                look["maximum_local_turn_deg"]
                > POLICY["maximum_lookahead_local_turn_deg"]
            ):
                continue
            if (
                look["full_observed_span_px"] < POLICY["lookahead_span_px"]
                and look["lookahead_terminal"]
                and look["lookahead_terminal"].get("kind")
                == "OBSERVED_FREE_SOURCE_ENDPOINT"
                and _inside(np.asarray([look["lookahead_end_px"]]), contact_box)[0]
            ):
                continue
            angle = math.degrees(
                math.acos(float(np.clip(direction @ look["direction"], -1, 1)))
            )
            scored.append((angle, tuple(look["ports"]), look))
    scored.sort(key=lambda item: (item[0], item[1]))
    unique = []
    seen = set()
    for item in scored:
        # Competing paths that share the first port are a later decision.
        # Only choose this next original edge, then prove the next node anew.
        if item[1][0] not in seen:
            unique.append(item)
            seen.add(item[1][0])
    if not unique:
        return None, {"reason": "NO_ORIGINAL_OUTGOING_PATH"}
    best = unique[0]
    margin = unique[1][0] - best[0] if len(unique) > 1 else 180.0
    evidence = {
        "node_id": node_id,
        "source_node_center_px": node["center"],
        "source_core_pixels": graph.xy(node["pixels"]).tolist(),
        "incoming_edge_id": incoming[0],
        "selected_outgoing_ports": [list(p) for p in best[2]["ports"]],
        "lookahead_maximum_local_turn_deg": best[2]["maximum_local_turn_deg"],
        "deviation_deg": float(best[0]),
        "alternative_margin_deg": float(margin),
        "alternative_deviations_deg": [float(v[0]) for v in unique[1:]],
        "unselected_branch_edge_ids": [
            p[0] for p in node["edges"] if p != incoming and p != best[2]["ports"][0]
        ],
        "unselected_branch_source_paths": [
            graph.xy(graph.oriented(p)).tolist()
            for p in node["edges"]
            if p != incoming and p != best[2]["ports"][0]
        ],
        "source_branches_deleted": False,
        "semantic_connection_inferred": False,
    }
    if (
        best[0] > POLICY["maximum_direction_deviation_deg"]
        or margin < POLICY["minimum_direction_margin_deg"]
    ):
        evidence["reason"] = "CONTACT_DIRECTION_NOT_UNIQUE"
        return None, evidence
    evidence["reason"] = "UNIQUE_ORIGINAL_DIRECTION_THROUGH_CONTACT"
    return [best[2]["ports"][0]], evidence


def _ink_contact_bridge(graph, node_id, incoming, route, edge_ids, contact_box):
    """Use two external direction anchors when a glyph distorts thinning.

    The bridge consists entirely of a connected walk in the original black
    pixels.  A narrow geometric corridor may share ink with a letter; it may
    not paint or bridge a real source gap.  Neither text content nor a guessed
    character is part of this test.
    """
    if not _inside(np.asarray([graph.nodes[node_id]["center"]]), contact_box)[0]:
        return None
    height = (contact_box[3] - contact_box[1]) / (
        1 + 2 * POLICY["maximum_contact_extension_heights"]
    )
    anchor_length = max(
        POLICY["minimum_anchor_length_px"],
        POLICY["minimum_anchor_length_heights"] * height,
    )
    cluster, pending = {node_id}, [node_id]
    while pending and len(cluster) <= 24:
        current = pending.pop()
        for port in graph.nodes[current]["edges"]:
            edge = graph.edges[port[0]]
            other = edge["nodes"][1 - port[1]]
            if (
                port[0] in edge_ids
                or edge["length"] >= anchor_length
                or other in cluster
            ):
                continue
            if not _inside(np.asarray([graph.nodes[other]["center"]]), contact_box)[0]:
                continue
            cluster.add(other)
            pending.append(other)
    if len(cluster) > 24:
        return None
    cluster_pixels = {p for nid in cluster for p in graph.nodes[nid]["pixels"]}
    cluster_xy = graph.xy(sorted(cluster_pixels))
    if (
        np.ptp(cluster_xy, axis=0).max()
        > POLICY["maximum_contact_cluster_heights"] * height
    ):
        return None
    incoming_direction = _tail_direction(graph, route)
    if incoming_direction is None:
        return None
    entry = graph.xy([route[-1]])[0]
    candidates = []
    for nid in sorted(cluster):
        for port in graph.nodes[nid]["edges"]:
            edge = graph.edges[port[0]]
            if port[0] in edge_ids or edge["length"] < anchor_length:
                continue
            pts = graph.xy(graph.oriented(port))
            span = np.r_[0.0, np.linalg.norm(np.diff(pts, axis=0), axis=1).cumsum()]
            k = min(
                len(pts) - 1, int(np.searchsorted(span, POLICY["direction_span_px"]))
            )
            outward = pts[k] - pts[0]
            outward /= max(np.linalg.norm(outward), 1e-12)
            chord = pts[0] - entry
            length = np.linalg.norm(chord)
            if length < 4:
                continue
            chord /= length
            angles = [
                math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))
                for a, b in (
                    (incoming_direction, outward),
                    (incoming_direction, chord),
                    (chord, outward),
                )
            ]
            candidates.append((max(angles), port, nid, angles))
    candidates.sort(key=lambda row: (row[0], row[1]))
    if not candidates or candidates[0][0] > POLICY["maximum_direction_deviation_deg"]:
        return None
    margin = candidates[1][0] - candidates[0][0] if len(candidates) > 1 else 180.0
    if margin < POLICY["minimum_direction_margin_deg"]:
        return None
    angle, outgoing, exit_node, angles = candidates[0]
    target = graph.oriented(outgoing)[0]
    end = graph.xy([target])[0]
    vector = end - entry
    length2 = float(vector @ vector)
    band = POLICY["maximum_contact_ink_normal_px"]
    lo = np.floor(np.minimum(entry, end) - band - 1).astype(int)
    hi = np.ceil(np.maximum(entry, end) + band + 1).astype(int)
    start = route[-1]
    costs, parents = {start: 0.0}, {start: None}
    queue = [(0.0, start)]
    flat = graph.source_ink.ravel()
    while queue:
        cost, p = heapq.heappop(queue)
        if cost != costs[p]:
            continue
        if p == target:
            found = []
            while p is not None:
                found.append(p)
                p = parents[p]
            found.reverse()
            unselected = sorted(
                {
                    eid
                    for nid in cluster
                    for eid, _ in graph.nodes[nid]["edges"]
                    if eid not in edge_ids and eid != outgoing[0]
                }
            )
            evidence = {
                "reason": "TWO_ORIGINAL_LONG_ANCHORS_AND_CONNECTED_INK_CORRIDOR",
                "node_id": node_id,
                "source_node_center_px": graph.nodes[node_id]["center"],
                "source_core_pixels": cluster_xy.tolist(),
                "source_ink_contact_path_px": graph.xy(found).tolist(),
                "contact_cluster_node_ids": sorted(cluster),
                "incoming_edge_id": incoming[0],
                "selected_outgoing_ports": [list(outgoing)],
                "external_anchor_deviations_deg": angles,
                "deviation_deg": angle,
                "alternative_margin_deg": margin,
                "maximum_source_corridor_normal_px": band,
                "unselected_branch_edge_ids": unselected,
                "unselected_branch_source_paths": [
                    graph.xy(graph.edges[eid]["pixels"]).tolist() for eid in unselected
                ],
                "source_branches_deleted": False,
                "semantic_connection_inferred": False,
                "original_black_pixel_walk_required": True,
            }
            return outgoing, exit_node, found, evidence
        y, x = divmod(p, graph.w)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == dy == 0 or not (
                    0 <= x + dx < graph.w and 0 <= y + dy < graph.h
                ):
                    continue
                q = p + dy * graph.w + dx
                if not flat[q]:
                    continue
                # A diagonal contact must exist in the original pixel cells;
                # do not skip an axial black route or bridge white cells.
                if dx and dy and (flat[p + dy * graph.w] or flat[p + dx]):
                    continue
                point = graph.xy([q])[0]
                if np.any(point < lo) or np.any(point > hi):
                    continue
                t = float((point - entry) @ vector / length2)
                normal = float(
                    np.linalg.norm(point - (entry + np.clip(t, 0, 1) * vector))
                )
                if normal > band:
                    continue
                new = cost + math.hypot(dx, dy) + 4 * normal * normal
                if new < costs.get(q, float("inf")):
                    costs[q] = new
                    parents[q] = p
                    heapq.heappush(queue, (new, q))
    return None


def _complete_microcore_cover(graph, node_id, incoming):
    """Cover every original edge of a bounded multi-hole two-port core."""
    node = graph.nodes[node_id]
    external = [
        p for p in node["edges"] if graph.edges[p[0]]["nodes"] != [node_id, node_id]
    ]
    if (
        len(external) != 2
        or incoming not in external
        or node["internal_source_endpoint_count"]
    ):
        return None
    outgoing = next(p for p in external if p != incoming)
    points = set(node["pixels"])
    internal = []
    for eid, _ in node["edges"]:
        edge = graph.edges[eid]
        if edge["nodes"] == [node_id, node_id]:
            points.update(edge["pixels"])
            internal.append(eid)
    xy = graph.xy(sorted(points))
    if (
        len(points) > POLICY["maximum_microcore_pixels"]
        or np.ptp(xy, axis=0).max() > POLICY["maximum_microcore_extent_px"]
    ):
        return None
    adjacency = {
        p: sorted(q for q in graph.neighbors(p) if q in points) for p in points
    }
    start = graph.oriented(incoming)[0]
    end = graph.oriented(outgoing)[0]
    if {p for p, qs in adjacency.items() if len(qs) == 1} != {start, end}:
        return None
    parents = {start: None}
    queue = deque([start])
    while queue:
        p = queue.popleft()
        for q in adjacency[p]:
            if q not in parents:
                parents[q] = p
                queue.append(q)
    if set(parents) != points:
        return None
    direct = []
    p = end
    while p is not None:
        direct.append(p)
        p = parents[p]
    direct.reverse()
    direct_edges = {tuple(sorted((a, b))) for a, b in zip(direct, direct[1:])}
    all_edges = {tuple(sorted((a, b))) for a, qs in adjacency.items() for b in qs}
    if len(all_edges) - len(points) + 1 < 2:
        return None
    remaining = {edge: 1 if edge in direct_edges else 2 for edge in all_edges}
    stack = [start]
    walk = []
    while stack:
        p = stack[-1]
        q = next((q for q in adjacency[p] if remaining[tuple(sorted((p, q)))]), None)
        if q is None:
            walk.append(stack.pop())
        else:
            remaining[tuple(sorted((p, q)))] -= 1
            stack.append(q)
    walk.reverse()
    if walk[0] != start or walk[-1] != end or any(remaining.values()):
        return None
    observed = {tuple(sorted((a, b))) for a, b in zip(walk, walk[1:])}
    if observed != all_edges:
        return None
    certificate = {
        "schema": "bounded-two-port-original-multicycle-cover-v1",
        "source_core_points": xy.tolist(),
        "source_core_edges": [graph.xy(e).tolist() for e in sorted(all_edges)],
        "source_walk_points": graph.xy(walk).tolist(),
        "external_ports": [list(incoming), list(outgoing)],
        "internal_source_graph_edge_ids": sorted(set(internal)),
        "cycle_rank": len(all_edges) - len(points) + 1,
        "all_core_source_edges_covered": True,
        "all_core_source_pixels_covered": True,
        "source_pixels_modified": False,
        "source_short_branches_deleted": False,
        "same_owner_retrace_only": True,
        "round_to_different_round_endpoints_required": True,
        "selection_rule": "ORIGINAL_SHORTEST_PORT_PATH_PLUS_DOUBLE_REMAINDER_EULER_COVER",
    }
    return outgoing, walk, certificate


def _round_contact_stub(graph, node_id, incoming, route):
    node = graph.nodes[node_id]
    direction = _tail_direction(graph, route)
    if direction is None:
        return None
    candidates = []
    alternatives = []
    for port in node["edges"]:
        if port == incoming:
            continue
        edge = graph.edges[port[0]]
        points = graph.xy(graph.oriented(port))
        vector = points[min(len(points) - 1, 14)] - points[0]
        norm = np.linalg.norm(vector)
        if norm < 2:
            return None
        angle = math.degrees(
            math.acos(float(np.clip(direction @ vector / norm, -1, 1)))
        )
        terminal = graph.nodes[edge["nodes"][1 - port[1]]]["terminal"] or {}
        if (
            edge["length"] <= POLICY["maximum_round_contact_stub_px"]
            and terminal.get("kind") == "OBSERVED_ROUND_BOUNDARY_CONTACT"
            and angle <= POLICY["maximum_round_stub_deviation_deg"]
        ):
            candidates.append((port, angle, terminal))
        else:
            alternatives.append((port, angle))
    if len(candidates) != 1 or any(
        a < POLICY["minimum_round_stub_other_branch_deviation_deg"]
        for _, a in alternatives
    ):
        return None
    outgoing, angle, terminal = candidates[0]
    certificate = {
        "reason": "SHORT_ORIGINAL_ROUND_CONTACT_STUB_WITH_DISTINCT_OTHER_BRANCH",
        "node_id": node_id,
        "source_node_center_px": node["center"],
        "source_core_pixels": graph.xy(node["pixels"]).tolist(),
        "incoming_edge_id": incoming[0],
        "selected_outgoing_ports": [list(outgoing)],
        "deviation_deg": angle,
        "observed_round_terminal": terminal,
        "stub_length_px": graph.edges[outgoing[0]]["length"],
        "other_branch_deviations_deg": [a for _, a in alternatives],
        "unselected_branch_edge_ids": [p[0] for p, _ in alternatives],
        "unselected_branch_source_paths": [
            graph.xy(graph.oriented(p)).tolist() for p, _ in alternatives
        ],
        "source_branches_deleted": False,
        "semantic_connection_inferred": False,
    }
    return outgoing, certificate


def _trace_direction(graph, first_port, contact_box):
    pixels, edge_ids, contacts, cycle_covers = [], [], [], []
    node_id = graph.edges[first_port[0]]["nodes"][first_port[1]]
    forced = [first_port]
    for _ in range(POLICY["maximum_route_edges"]):
        if not forced:
            return {
                "reason": "MISSING_SOURCE_CONTINUATION",
                "source_path_px": graph.xy(pixels).tolist(),
            }
        port = forced.pop(0)
        eid, end = port
        if eid in edge_ids:
            return {
                "reason": "SOURCE_ROUTE_CYCLE",
                "source_path_px": graph.xy(pixels).tolist(),
            }
        part = graph.oriented(port)
        if pixels:
            core = _core_route(graph, node_id, pixels[-1], part[0])
            pixels.extend(core[1:])
            pixels.extend(part[1:])
        else:
            pixels.extend(part)
        edge_ids.append(eid)
        node_id = graph.edges[eid]["nodes"][1 - end]
        node = graph.nodes[node_id]
        if node["terminal"]:
            return {
                "reason": None,
                "pixels": pixels,
                "edge_ids": edge_ids,
                "contact_choices": contacts,
                "terminal_node_id": node_id,
                "terminal": node["terminal"],
                "cycle_covers": cycle_covers,
            }
        if node.get("reason") == "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT":
            return {"reason": "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT"}
        if forced:
            continue
        incoming = (eid, 1 - end)
        cover = graph.cycle_cells_by_port.get(incoming)
        if cover:
            internal = cover["internal_source_graph_edge_ids"]
            if set(internal) & set(edge_ids):
                return {"reason": "SOURCE_ROUTE_CYCLE"}
            outgoing = next(
                tuple(p) for p in cover["external_ports"] if tuple(p) != incoming
            )
            route = graph._cycle_cover_route(
                cover, pixels[-1], graph.oriented(outgoing)[0]
            )
            pixels.extend(route[1:])
            edge_ids.extend(internal)
            cycle_covers.append(cover)
            node_id = graph.edges[outgoing[0]]["nodes"][outgoing[1]]
            forced = [outgoing]
            continue
        if incoming in node["pairing"]:
            forced = [node["pairing"][incoming]]
            continue
        microcover = _complete_microcore_cover(graph, node_id, incoming)
        if microcover:
            outgoing, walk, certificate = microcover
            pixels.extend(walk[1:])
            edge_ids.extend(certificate["internal_source_graph_edge_ids"])
            cycle_covers.append(certificate)
            forced = [outgoing]
            continue
        round_stub = _round_contact_stub(graph, node_id, incoming, pixels)
        if round_stub:
            outgoing, certificate = round_stub
            contacts.append(certificate)
            forced = [outgoing]
            continue
        forced, evidence = _contact_choice(
            graph, node_id, incoming, pixels, edge_ids, contact_box
        )
        contacts.append(evidence)
        if forced is None:
            bridge = _ink_contact_bridge(
                graph, node_id, incoming, pixels, edge_ids, contact_box
            )
            if bridge:
                outgoing, exit_node, walk, certificate = bridge
                contacts[-1] = certificate
                pixels.extend(walk[1:])
                node_id = exit_node
                forced = [outgoing]
                continue
            return {
                "reason": evidence["reason"],
                "contact_choices": contacts,
                "source_path_px": graph.xy(pixels).tolist(),
            }
    return {"reason": "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT"}


def _mask_runs(mask, origin):
    result = []
    for y in np.flatnonzero(mask.any(axis=1)):
        changes = np.diff(np.r_[False, mask[y], False].astype(np.int8))
        for start, end in zip(
            np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        ):
            result.append(
                [int(y + origin[1]), int(start + origin[0]), int(end + origin[0])]
            )
    return result


def _pending_trace(trace):
    points = trace.get("source_path_px") or []
    contacts = []
    for row in trace.get("contact_choices", [])[-8:]:
        contacts.append(
            {
                k: v
                for k, v in row.items()
                if k
                not in {
                    "source_core_pixels",
                    "source_ink_contact_path_px",
                    "unselected_branch_source_paths",
                }
            }
        )
    return {
        "reason": trace["reason"],
        "terminal": trace.get("terminal"),
        "observed_source_path_point_count": len(points) or len(trace.get("pixels", [])),
        "last_source_point_px": points[-1] if points else None,
        "contact_decisions": contacts,
    }


def _deduplicate_contact_encodings(rows, contact_box):
    grouped = {}
    for row in rows:
        points = np.asarray(row["source_path_px"])
        inside = _inside(points, contact_box)
        outside_edges = frozenset(
            tuple(sorted((tuple(a), tuple(b))))
            for i, (a, b) in enumerate(zip(points, points[1:]))
            if not inside[i] and not inside[i + 1]
        )
        endpoint_key = tuple(sorted(tuple(p) for p in row["endpoint_source_points_px"]))
        key = (endpoint_key, outside_edges)
        grouped.setdefault(key, []).append(row)
    result = []
    for variants in grouped.values():
        variants.sort(
            key=lambda r: (
                r["source_path_length_px"],
                json.dumps(r["representation"], sort_keys=True),
            )
        )
        chosen = variants[0]
        if len(variants) > 1:
            chosen["equivalent_contact_encodings"] = {
                "count": len(variants),
                "same_external_original_edge_union": True,
                "same_actual_endpoint_points": True,
                "selection_rule": "SHORTEST_ORIGINAL_CONTACT_WALK_THEN_CANONICAL_GEOMETRY",
                "all_variants_individually_source_supported": True,
                "glyph_contact_ink_not_exclusively_owned": True,
            }
        result.append(chosen)
    return result


def _quarantine_competing_whole_routes(rows):
    """A branch cannot become unique merely by starting the trace backwards."""
    edge_sets = []
    for row in rows:
        p = row["source_path_px"]
        edge_sets.append(
            {tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(p, p[1:])}
        )
    blocked = set()
    decisions = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            shared = edge_sets[i] & edge_sets[j]
            length = sum(math.dist(a, b) for a, b in shared)
            if length <= POLICY["maximum_round_contact_stub_px"]:
                continue
            blocked.update((i, j))
            decisions.append(
                {
                    "reason": "NONUNIQUE_WHOLE_PATH_CONTINUATION_COMPETITION",
                    "candidate_endpoint_pairs": [
                        rows[i]["endpoint_source_points_px"],
                        rows[j]["endpoint_source_points_px"],
                    ],
                    "shared_original_source_adjacency_length_px": length,
                    "all_competing_routes_retained_pending": True,
                }
            )
    return [row for i, row in enumerate(rows) if i not in blocked], decisions


def plan_text_contact_geometry(gray, roi, seed_bbox, *, source_graph=None):
    """Plan complete original paths; do not adopt text or modify the source."""
    source = np.asarray(gray)
    seed = list(map(int, seed_bbox))
    height = seed[3] - seed[1]
    result = {
        "schema": SCHEMA,
        "policy": dict(POLICY),
        "seed_bbox_xyxy_px": seed,
        "roi_xyxy_px": list(map(int, roi)),
        "paths": [],
        "pending": [],
        "original_source_pixels_modified": False,
        "transcription_supplied": False,
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "unchanged_connection_source_policy": dict(paths.POLICY),
    }
    if height < 7 or height > 90 or seed[2] <= seed[0]:
        result["reason"] = "CONTACT_SEED_GEOMETRY_OUTSIDE_SINGLE_LINE_CONTRACT"
        return result
    context = source_graph or build_text_contact_source_graph(source, roi)
    graph = context.graph
    ox, oy, rx, by = context.crop_bbox
    if (
        list(map(int, roi)) != list(graph.roi)
        or hashlib.sha256(source[oy:by, ox:rx].tobytes()).hexdigest()
        != context.source_crop_hash
    ):
        raise ValueError("CONTACT_REUSED_GRAPH_ORIGINAL_SOURCE_OR_ROI_CHANGED")
    pad = POLICY["maximum_contact_extension_heights"] * height
    contact_box = [seed[0] - pad, seed[1] - pad, seed[2] + pad, seed[3] + pad]
    result.update(
        {
            "original_source_crop_xyxy_px": context.crop_bbox,
            "original_source_crop_array_sha256": context.source_crop_hash,
            "contact_context_bbox_xyxy_px": contact_box,
            "round_observations": context.rounds,
        }
    )
    seeds = []
    for edge in graph.edges:
        if edge["length"] < max(
            POLICY["minimum_anchor_length_px"],
            POLICY["minimum_anchor_length_heights"] * height,
        ):
            continue
        points = graph.xy(edge["pixels"])
        if _inside(points, contact_box).any():
            seeds.append(edge["id"])
    if len(seeds) > POLICY["maximum_seed_edges"]:
        result["reason"] = "CONTACT_SEED_GRAPH_DENSITY_EXCEEDS_LIMIT"
        return result
    seen = set()
    distance = cv2.distanceTransform(
        (~graph.source_ink).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    for eid in seeds:
        forward = _trace_direction(graph, (eid, 0), contact_box)
        reverse = _trace_direction(graph, (eid, 1), contact_box)
        if forward["reason"] or reverse["reason"]:
            result["pending"].append(
                {
                    "seed_edge_id": eid,
                    "forward": _pending_trace(forward),
                    "reverse": _pending_trace(reverse),
                }
            )
            continue
        overlap = set(forward["edge_ids"]) & set(reverse["edge_ids"])
        if overlap != {eid}:
            result["pending"].append(
                {"seed_edge_id": eid, "reason": "SOURCE_ROUTE_DOUBLE_BACK"}
            )
            continue
        key = tuple(sorted(set(forward["edge_ids"] + reverse["edge_ids"])))
        if key in seen:
            continue
        seen.add(key)
        edge_size = len(graph.edges[eid]["pixels"])
        pixels = reverse["pixels"][::-1] + forward["pixels"][edge_size:]
        points = graph.xy(pixels)
        length = paths._length(points)
        terminals = [reverse["terminal"], forward["terminal"]]
        ambiguous_free_ends = [
            endpoint.tolist()
            for endpoint, terminal in zip((points[0], points[-1]), terminals)
            if terminal.get("kind") == "OBSERVED_FREE_SOURCE_ENDPOINT"
            and _inside(np.asarray([endpoint]), seed)[0]
        ]
        if ambiguous_free_ends:
            result["pending"].append(
                {
                    "seed_edge_id": eid,
                    "reason": "FREE_SOURCE_ENDPOINT_INSIDE_TEXT_REQUIRES_INDEPENDENT_GRAPHIC_IDENTITY",
                    "unresolved_endpoint_points_px": ambiguous_free_ends,
                    "source_short_branch_or_glyph_not_erased": True,
                }
            )
            continue
        if terminals[0].get("round_id") is not None and terminals[0].get(
            "round_id"
        ) == terminals[1].get("round_id"):
            continue
        if paths._round_boundary_ownership(points, context.rounds):
            continue
        if not _inside(points, seed).any():
            # Adjacent independent underlines are useful recognition context;
            # closed frames and symbols are not text-contact path discoveries.
            delta = points[-1] - points[0]
            if abs(delta[0]) < 3 * abs(delta[1]):
                continue
            normal = np.array([-delta[1], delta[0]]) / max(np.linalg.norm(delta), 1e-12)
            if np.max(np.abs((points - points[0]) @ normal)) > 2.0:
                continue
        if np.linalg.norm(points[-1] - points[0]) < 0.35 * length:
            continue
        if length < max(
            paths.POLICY["minimum_path_length_px"],
            POLICY["minimum_complete_length_heights"] * height,
        ):
            continue
        covers = reverse.get("cycle_covers", []) + forward.get("cycle_covers", [])
        if covers and not (
            all(t.get("kind") == "OBSERVED_ROUND_BOUNDARY_CONTACT" for t in terminals)
            and terminals[0].get("round_id") != terminals[1].get("round_id")
        ):
            result["pending"].append(
                {
                    "seed_edge_id": eid,
                    "reason": "LOCAL_CYCLE_COVER_REQUIRES_DISTINCT_ROUND_TERMINALS",
                }
            )
            continue
        protected = []
        for cover in covers:
            local_points = set(tuple(p) for p in cover["source_core_points"])
            indices = [i for i, p in enumerate(points) if tuple(p) in local_points]
            if indices:
                protected.append([min(indices), max(indices) + 1])
        geometry, fit = paths._representation(points, protected_intervals=protected)
        dense = paths._dense_geometry(geometry, paths.POLICY["dense_step_px"])
        support = paths._support(dense, distance, graph.origin)
        if (
            not support["pass"]
            or len(geometry["points"]) > POLICY["maximum_control_vertices"]
        ):
            result["pending"].append(
                {
                    "seed_edge_id": eid,
                    "reason": "WHOLE_CONTACT_PATH_SOURCE_GATE_FAILED",
                    "source_support": support,
                    "control_count": len(geometry["points"]),
                }
            )
            continue
        x0, y0 = max(0, int(contact_box[0])), max(0, int(contact_box[1]))
        x1, y1 = (
            min(source.shape[1], int(math.ceil(contact_box[2]))),
            min(source.shape[0], int(math.ceil(contact_box[3]))),
        )
        local = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.polylines(
            local,
            [np.rint(dense - [x0, y0]).astype(np.int32)],
            False,
            1,
            thickness=int(2 * POLICY["maximum_mask_normal_px"] + 1),
        )
        line_mask = local.astype(bool) & (
            source[y0:y1, x0:x1] < paths.POLICY["source_threshold"]
        )
        contacts = reverse["contact_choices"] + forward["contact_choices"]
        shared = np.zeros_like(local)
        for contact in contacts:
            core = np.rint(np.asarray(contact["source_core_pixels"]) - [x0, y0]).astype(
                int
            )
            valid = (
                (core[:, 0] >= 0)
                & (core[:, 0] < shared.shape[1])
                & (core[:, 1] >= 0)
                & (core[:, 1] < shared.shape[0])
            )
            core = core[valid]
            shared[core[:, 1], core[:, 0]] = 1
        shared = cv2.dilate(shared, np.ones((3, 3), np.uint8)).astype(bool) & line_mask
        result["paths"].append(
            {
                "source_path_px": points.tolist(),
                "source_graph_edge_ids": list(key),
                "source_path_length_px": length,
                "representation": geometry,
                "representation_evidence": fit,
                "source_support": support,
                "endpoint_evidence": terminals,
                "endpoint_source_points_px": [points[0].tolist(), points[-1].tolist()],
                "contact_continuations": contacts,
                "bounded_original_cycle_covers": covers,
                "line_runs": _mask_runs(line_mask, [x0, y0]),
                "shared_contact_runs": _mask_runs(shared, [x0, y0]),
                "original_branches_retained": True,
                "line_and_text_may_share_source_pixels": True,
                "text_content_decision": "NOT_PERFORMED",
            }
        )
    result["paths"] = _deduplicate_contact_encodings(result["paths"], contact_box)
    result["paths"], competition = _quarantine_competing_whole_routes(result["paths"])
    result["pending"].extend(competition)
    result["reason"] = (
        "COMPLETE_SOURCE_PATHS_PLANNED"
        if result["paths"]
        else "NO_COMPLETE_SOURCE_PATH_PROVEN"
    )
    return result


def verify_text_contact_geometry_plan(gray, roi, plan, *, source_graph=None):
    """Rebuild every claimed whole path from original pixels and fixed rules.

    The caller must additionally compare the saved CAD geometry with the
    corresponding replayed representation.  A source certificate alone is
    not a saved-file validation.
    """
    checks = {
        "schema": plan.get("schema") == SCHEMA,
        "policy": plan.get("policy") == POLICY,
        "roi": plan.get("roi_xyxy_px") == list(map(int, roi)),
        "producer": plan.get("producer_sha256")
        == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "connection_source_policy": plan.get("unchanged_connection_source_policy")
        == paths.POLICY,
        "original_not_modified": plan.get("original_source_pixels_modified") is False,
        "no_transcription_input": plan.get("transcription_supplied") is False,
    }
    if not all(checks.values()):
        return {
            "pass": False,
            "checks": checks,
            "reason": "CONTACT_PLAN_POLICY_OR_PRODUCER_CHANGED",
            "replayed_paths": [],
        }
    try:
        replay = plan_text_contact_geometry(
            gray, roi, plan["seed_bbox_xyxy_px"], source_graph=source_graph
        )
    except (KeyError, TypeError, ValueError) as error:
        return {
            "pass": False,
            "checks": checks,
            "reason": str(error),
            "replayed_paths": [],
        }
    checks["original_crop_hash"] = plan.get(
        "original_source_crop_array_sha256"
    ) == replay.get("original_source_crop_array_sha256")
    checks["original_crop_bounds"] = plan.get(
        "original_source_crop_xyxy_px"
    ) == replay.get("original_source_crop_xyxy_px")
    checks["all_complete_paths_replayed"] = plan.get("paths") == replay.get("paths")
    checks["round_observations_replayed"] = plan.get(
        "round_observations"
    ) == replay.get("round_observations")
    return {
        "pass": bool(all(checks.values())),
        "checks": checks,
        "reason": "ALL_ORIGINAL_CONTACT_PATHS_REPLAYED"
        if all(checks.values())
        else "CONTACT_PLAN_SOURCE_OR_PATH_CHANGED",
        "replayed_paths": replay.get("paths", []),
    }
