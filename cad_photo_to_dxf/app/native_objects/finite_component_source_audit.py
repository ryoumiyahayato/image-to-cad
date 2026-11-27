"""Independent saved-file source acceptance for the finite component subset.

Fresh original-image graph edges are matched against actual saved geometry.
The component kernel is reused only after this separate reconstruction.  No
producer plan, target chain, endpoint approval or adoption verdict is consumed.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json
import math

import numpy as np
from PIL import Image
from scipy.ndimage import label

from . import attached_stroke_component as component
from . import attached_stroke_width_exact as exact
from .finite_component_saved_reader import (
    context_for_scope,
    exact_points,
    saved_source_geometries,
    sha256,
)
from .text_contact_geometry import build_text_contact_source_graph

SCHEMA = "independent-saved-finite-component-source-acceptance-v1"
POLICY = {
    "source_threshold": 128,
    "candidate_source_distance_squared": [9, 4],
    "prior_source_distance_squared": [4, 1],
    "maximum_bodies": 32,
    "maximum_route_edges": 32,
    "maximum_core_pixels": 64,
    "maximum_core_extent_px": 12,
    "maximum_simple_core_walks": 64,
    "maximum_core_walk_states": 8192,
    "maximum_pair_deviation_deg": 20.,
    "minimum_pair_margin_deg": 18.,
    "minimum_attachment_axis_separation_deg": 45.,
    "free_cap_extent_px": 3,
    "accepted_core_subset": "TREE_WITHOUT_INTERNAL_FREE_ENDPOINT_OR_WHITE_HOLE",
    "producer_approval_consumed": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _encoded(point):
    return [exact.encode_rational(v) for v in point]


def _cells_at(point):
    axes = []
    for value in point:
        shifted = value + Fraction(1, 2)
        index = math.floor(shifted)
        axes.append([index - 1, index] if shifted.denominator == 1 else [index])
    return list(itertools.product(*axes))


def _raster_intervals(a, b):
    """Exact cell-boundary events; boundary/corner contacts stay distinct."""
    delta = tuple(y - x for x, y in zip(a, b))
    times = {Fraction(0), Fraction(1)}
    for origin, end, span in zip(a, b, delta):
        if not span:
            continue
        low, high = sorted((origin, end))
        for integer in range(math.ceil(low - Fraction(1, 2)), math.floor(high - Fraction(1, 2)) + 1):
            time = (Fraction(integer) + Fraction(1, 2) - origin) / span
            if 0 <= time <= 1:
                times.add(time)
    times = sorted(times)
    intervals = [(lo, hi, _cells_at(tuple(x + (lo + hi) / 2 * d for x, d in zip(a, delta))))
                 for lo, hi in itertools.pairwise(times)]
    events = [(time, _cells_at(tuple(x + time * d for x, d in zip(a, delta)))) for time in times]
    return intervals, events


def _state(source, cell):
    x, y = cell
    if x < 0 or y < 0 or y >= source.shape[0] or x >= source.shape[1]:
        return "OUTSIDE"
    return "BLACK" if source[y, x] < POLICY["source_threshold"] else "WHITE"


def _finite_support(source, row):
    points = exact_points(row)
    white_intervals, outside, zero_white, closed_cells = [], set(), set(), set()
    for index, (a, b) in enumerate(itertools.pairwise(points)):
        intervals, events = _raster_intervals(a, b)
        positive = set()
        for low, high, cells in intervals:
            positive.update(cells)
            closed_cells.update(cells)
            states = [_state(source, c) for c in cells]
            outside.update(c for c, state in zip(cells, states) if state == "OUTSIDE")
            if "BLACK" not in states and "OUTSIDE" not in states:
                white_intervals.append({"segment_index": index,
                    "parameter_interval": [exact.encode_rational(low), exact.encode_rational(high)],
                    "white_cells": [list(c) for c in cells]})
        for _, cells in events:
            closed_cells.update(cells)
            zero_white.update(c for c in cells if c not in positive and _state(source, c) == "WHITE")
            outside.update(c for c in cells if _state(source, c) == "OUTSIDE")
    return {"object_id": row["object_id"], "pass": not white_intervals and not outside,
            "status": "HARD_REJECT_POSITIVE_LENGTH_WHITE_GAP" if white_intervals else
                      "PENDING_FINITE_GEOMETRY_OUTSIDE_IMAGE" if outside else "POSITIVE_LENGTH_SOURCE_SUPPORT",
            "uncovered_positive_intervals": white_intervals,
            "outside_cells": [list(c) for c in sorted(outside)],
            "zero_length_white_cells": [list(c) for c in sorted(zero_white)],
            "closed_cells": [list(c) for c in sorted(closed_cells)]}


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _intersection(a, b, c, d):
    u, v = tuple(y - x for x, y in zip(a, b)), tuple(y - x for x, y in zip(c, d))
    w = tuple(y - x for x, y in zip(a, c))
    determinant = _cross(u, v)
    if determinant:
        t, s = _cross(w, v) / determinant, _cross(w, u) / determinant
        if 0 <= t <= 1 and 0 <= s <= 1:
            return "POINT", [tuple(x + t * z for x, z in zip(a, u))]
        return None
    if _cross(w, u):
        return None
    axis = 0 if u[0] else 1
    lo, hi = sorted(((c[axis] - a[axis]) / u[axis], (d[axis] - a[axis]) / u[axis]))
    lo, hi = max(Fraction(0), lo), min(Fraction(1), hi)
    if hi < lo:
        return None
    points = [tuple(x + time * z for x, z in zip(a, u)) for time in (lo, hi)]
    return ("POINT", points[:1]) if hi == lo else ("OVERLAP", points)


def _pair_checks(source, rows, target_ids):
    hits, overlaps = [], []
    labels4, _ = label(source < POLICY["source_threshold"])
    for row in rows:
        if row["object_id"] not in target_ids:
            continue
        segments = list(itertools.pairwise(exact_points(row)))
        for (i, (a, b)), (j, (c, d)) in itertools.combinations(enumerate(segments), 2):
            hit = _intersection(a, b, c, d)
            if hit and hit[0] == "OVERLAP":
                overlaps.append({"object_ids": [row["object_id"], row["object_id"]],
                    "segment_indices": [i, j], "points_exact": [_encoded(p) for p in hit[1]],
                    "status": "HARD_REJECT_POSITIVE_LENGTH_DUPLICATE"})
    for left, right in itertools.combinations(rows, 2):
        if not ({left["object_id"], right["object_id"]} & target_ids):
            continue
        for i, (a, b) in enumerate(itertools.pairwise(exact_points(left))):
            for j, (c, d) in enumerate(itertools.pairwise(exact_points(right))):
                hit = _intersection(a, b, c, d)
                if hit is None:
                    continue
                kind, points = hit
                record = {"object_ids": [left["object_id"], right["object_id"]],
                          "segment_indices": [i, j], "points_exact": [_encoded(p) for p in points]}
                if kind == "OVERLAP":
                    overlaps.append({**record, "status": "HARD_REJECT_POSITIVE_LENGTH_DUPLICATE"})
                    continue
                cells = _cells_at(points[0])
                black = [c for c in cells if _state(source, c) == "BLACK"]
                labels = sorted({int(labels4[y, x]) for x, y in black})
                state = "ORIGINAL_INK_POINT_CONTACT"
                if not black:
                    state = "HARD_REJECT_UNSUPPORTED_POINT_CONTACT"
                elif len(labels) != 1 or (len(cells) == 4 and len(black) < 3):
                    state = "PENDING_POINT_ONLY_SOURCE_CONNECTION"
                hits.append({**record, "status": state, "black_cells": [list(c) for c in black],
                             "source_4_connected_labels": labels})
    return {"contacts": hits, "positive_length_overlaps": overlaps,
            "pass": not overlaps and all(h["status"] == "ORIGINAL_INK_POINT_CONTACT" for h in hits)}


def _angle(a, b):
    norm = math.sqrt(float(sum(v * v for v in a) * sum(v * v for v in b)))
    if not norm:
        return 180.
    value = float(sum(x * y for x, y in zip(a, b))) / norm
    return math.degrees(math.acos(max(-1., min(1., value))))


def _direction_table(graph, nid):
    ports = sorted(graph.nodes[nid]["edges"])
    observations = {p: component.source_observations(graph, p) for p in ports}
    vectors = {p: [tuple(b - a for a, b in zip(o["source_points_px"][0], o["source_points_px"][-1]))
                   for o in observations[p]] for p in ports}
    complete = all(len(observations[p]) == 3 and all(o["source_chord_squared_px"] >= 16
                   for o in observations[p]) for p in ports)
    pairs = []
    for a, b in itertools.combinations(ports, 2):
        deviations = [_angle(x, tuple(-v for v in y)) for x, y in zip(vectors[a], vectors[b])]
        margins = []
        for index, deviation in enumerate(deviations):
            competitors = [_angle(vectors[p][index], tuple(-v for v in vectors[c][index]))
                           for p in (a, b) for c in ports if c not in (a, b)]
            margins.append(min(competitors, default=180.) - deviation)
        passed = bool(complete and deviations and max(deviations) <= POLICY["maximum_pair_deviation_deg"]
                      and min(margins) >= POLICY["minimum_pair_margin_deg"])
        pairs.append({"ports": [list(a), list(b)], "deviations_deg": deviations,
                      "competition_margins_deg": margins, "pass": passed})
    return {"node_id": nid, "all_directions_complete": complete, "pairs": pairs,
            "observations": [{"port": list(p), "observations": observations[p]} for p in ports]}


def _direction_table_v2(graph, nid):
    """Finite acyclic proofs with every original core route and read branch.

    The older helper is unchanged. This separate reader implementation extends
    its route enumeration: a representative core BFS is not an equivalence
    proof, and failed/short/truncated paths are part of the evidence read set.
    """
    from . import structure_contact_geometry as direction
    original = _direction_table(graph, nid)
    reads = {"edges": set(), "nodes": set(), "pixels": set(), "failed": [], "core_walks": {}}
    visited, queue, complete_closure = set(), [nid], True
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        if len(visited) >= direction.POLICY["maximum_direction_dependency_nodes"]:
            complete_closure = False
            reads["failed"].append({"reason": "DIRECTION_DEPENDENCY_NODE_BOUND", "queued_nodes": sorted(queue + [current])})
            break
        visited.add(current)
        for port in sorted(graph.nodes[current]["edges"]):
            _, _, dependencies = _all_core_port_directions(graph, port, {}, reads)
            queue.extend(sorted(dependencies - visited))
    resolved, proofs = {}, []
    for round_index in range(direction.POLICY["maximum_direction_depth"]):
        additions = []
        for current in sorted(visited):
            table = _all_core_direction_pairs(graph, current, resolved, reads)
            for pair in table["pairs"]:
                if not pair["pass"]:
                    continue
                for incoming, outgoing in (pair["ports"], list(reversed(pair["ports"]))):
                    key = current, tuple(incoming)
                    if key in resolved or tuple(incoming) in graph.nodes[current]["pairing"]:
                        continue
                    proof = {"round": round_index, "node_id": current, "incoming_port": incoming,
                        "outgoing_port": outgoing, "pair": pair, "all_port_candidates": table["pairs"],
                        "only_earlier_round_dependencies_used": True,
                        "earlier_proof_ids": sorted({p for rows in table["all_direction_alternatives"]
                            for look in rows["looks"] for p in look["verified_direction_dependencies"]})}
                    additions.append((key, tuple(outgoing), _digest(_plain(proof)), proof))
        if not additions:
            break
        for key, outgoing, proof_id, proof in additions:
            resolved[key] = {"outgoing": outgoing, "proof_id": proof_id}
            proofs.append({"proof_id": proof_id, **proof})
    table = _all_core_direction_pairs(graph, nid, resolved, reads)
    table["all_directions_complete"] &= complete_closure
    if not complete_closure:
        for pair in table["pairs"]:
            pair["pass"] = False
    return _plain({**table, "schema": "independent-bounded-acyclic-source-direction-v2", "node_id": nid,
        "observations": original["observations"], "historical_local_table": original,
        "direction_dependency_proofs": proofs, "dependency_source_node_ids": sorted(reads["nodes"]),
        "dependency_source_edge_ids": sorted(reads["edges"]),
        "evidence_read_pixels_px": np.asarray(graph.xy(sorted(reads["pixels"])), int).tolist(),
        "failed_short_and_truncated_branches": reads["failed"],
        "all_internal_core_walks": list(reads["core_walks"].values()),
        "dependency_closure_complete": complete_closure,
        "source_branches_deleted": False, "graph_pairings_modified": False,
        "producer_approval_consumed": False,
        "maximum_pair_deviation_deg": 20., "minimum_pair_margin_deg": 18.})


def _all_core_port_directions(graph, first, resolved, reads):
    from . import structure_contact_geometry as direction
    policy = direction.POLICY
    queue, looks, dependencies, complete, states = [(tuple(first), [], [], 0, [])], [], set(), True, 0

    def finite_edge_prefix(port):
        pixels = list(graph.oriented(port))
        points = np.asarray(graph.xy(pixels), int)
        axial = diagonal = 0
        for index in range(1, len(points)):
            step = np.abs(points[index] - points[index - 1])
            diagonal += int(step.sum() == 2)
            axial += int(step.sum() != 2)
            if component._length_reached(axial, diagonal, policy["direction_span_px"]):
                return pixels[:index + 1]
        return pixels

    def record_port(port):
        reads["edges"].add(port[0])
        prefix = finite_edge_prefix(port)
        reads["pixels"].update(prefix)
        node_ids = [graph.edges[port[0]]["nodes"][port[1]]]
        if len(prefix) == len(graph.edges[port[0]]["pixels"]):
            node_ids.append(graph.edges[port[0]]["nodes"][1 - port[1]])
        for node_id in node_ids:
            reads["nodes"].add(node_id)
            reads["pixels"].update(graph.nodes[node_id]["pixels"])

    record_port(tuple(first))
    while queue:
        if states >= POLICY["maximum_core_walk_states"] or len(looks) >= policy["maximum_direction_states"]:
            for port, _, used, _, _ in queue:
                record_port(port)
                reads["failed"].append({"port": list(first), "reason": "DIRECTION_STATE_BOUND",
                                        "pending_port": list(port), "edge_ids": used + [port[0]]})
            complete = False
            break
        port, raw, used, depth, proof_ids = queue.pop()
        states += 1
        record_port(port)
        if port[0] in used:
            complete = False
            reads["failed"].append({"port": list(first), "reason": "DIRECTION_REUSES_EDGE", "edge_ids": used + [port[0]]})
            continue
        part = finite_edge_prefix(port)
        variants = [part]
        if raw:
            node_id = graph.edges[port[0]]["nodes"][port[1]]
            try:
                walks = _core_walks(graph, node_id, raw[-1], part[0])
            except ValueError as exc:
                complete = False
                reads["failed"].append({"port": list(first), "reason": str(exc), "node_id": node_id})
                continue
            key = node_id, raw[-1], part[0]
            reads["core_walks"][key] = {"node_id": node_id, "all_walks_px":
                [np.asarray(graph.xy(walk), int).tolist() for walk in walks]}
            variants = [raw + walk[1:] + part[1:] for walk in walks]
        next_used = used + [port[0]]
        node_id = graph.edges[port[0]]["nodes"][1 - port[1]]
        incoming, node = (port[0], 1 - port[1]), graph.nodes[node_id]
        for pixels in variants:
            reads["pixels"].update(pixels)
            points = graph.xy(pixels)
            spans = np.r_[0., np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
            finished = spans[-1] >= policy["direction_span_px"] or bool(node["terminal"])
            if finished:
                k = min(len(points) - 1, int(np.searchsorted(spans, policy["direction_span_px"])))
                vector = points[k] - points[0]
                if np.linalg.norm(vector) < policy["minimum_direction_span_px"]:
                    complete = False
                    reads["failed"].append({"port": list(first), "reason": "DIRECTION_CHORD_TOO_SHORT",
                                            "edge_ids": next_used, "source_points_px": points.tolist()})
                else:
                    looks.append({"vector": vector.tolist(), "edge_ids": next_used,
                        "source_start_px": points[0].tolist(), "source_end_px": points[k].tolist(),
                        "verified_direction_dependencies": proof_ids, "span_px": float(spans[k])})
                continue
            if depth >= policy["maximum_direction_depth"]:
                complete = False
                reads["failed"].append({"port": list(first), "reason": "DIRECTION_DEPTH_BOUND", "edge_ids": next_used})
                continue
            known = resolved.get((node_id, incoming))
            if incoming in node["pairing"]:
                choices, next_proofs = [node["pairing"][incoming]], proof_ids
            elif known:
                choices, next_proofs = [known["outgoing"]], proof_ids + [known["proof_id"]]
            else:
                dependencies.add(node_id)
                choices, next_proofs = [p for p in node["edges"] if p != incoming], proof_ids
            for choice in choices:
                record_port(choice)
                queue.append((choice, pixels, next_used, depth + 1, next_proofs))
    if len(looks) > policy["maximum_direction_states"]:
        complete = False
        reads["failed"].append({"port": list(first), "reason": "DIRECTION_CORE_VARIANT_STATE_BOUND",
                                "observed_variant_count": len(looks)})
    return looks, complete and bool(looks), dependencies


def _all_core_direction_pairs(graph, nid, resolved, reads):
    ports = sorted(graph.nodes[nid]["edges"])
    observed = {p: _all_core_port_directions(graph, p, resolved, reads) for p in ports}
    complete = all(value[1] for value in observed.values())
    intervals = {}
    for a, b in itertools.combinations(ports, 2):
        values = [_angle(x["vector"], tuple(-v for v in y["vector"]))
                  for x in observed[a][0] for y in observed[b][0]]
        intervals[frozenset((a, b))] = (min(values), max(values)) if values else (180., 180.)
    pairs = []
    for a, b in itertools.combinations(ports, 2):
        low, high = intervals[frozenset((a, b))]
        margins = [min((intervals[frozenset((p, c))][0] for c in ports if c not in (a, b)),
                       default=180.) - high for p in (a, b)]
        pairs.append({"ports": [list(a), list(b)], "deviations_deg": [low, high],
            "competition_margins_deg": margins,
            "pass": complete and a[0] != b[0] and high <= POLICY["maximum_pair_deviation_deg"]
                    and min(margins) >= POLICY["minimum_pair_margin_deg"]})
    return {"node_id": nid, "all_directions_complete": complete, "pairs": pairs,
        "all_direction_alternatives": [{"port": list(p), "complete": observed[p][1],
                                         "looks": observed[p][0]} for p in ports]}


def _core_walks(graph, nid, start, end):
    allowed, stack, paths, states = set(graph.nodes[nid]["pixels"]), [(start, [start])], [], 0
    while stack:
        current, path = stack.pop()
        states += 1
        if states > POLICY["maximum_core_walk_states"]:
            raise ValueError("PENDING_CORE_WALK_RESOURCE_BOUNDARY")
        if current == end:
            paths.append(path)
            if len(paths) > POLICY["maximum_simple_core_walks"]:
                raise ValueError("PENDING_CORE_WALK_RESOURCE_BOUNDARY")
        else:
            stack.extend((other, path + [other]) for other in sorted(graph.neighbors(current), reverse=True)
                         if other in allowed and other not in path)
    if not paths:
        raise ValueError("PENDING_DISCONTINUOUS_ORIGINAL_CORE")
    return sorted(paths, key=lambda p: (len(p), p))


def _core_evidence(source, graph, nid, directions):
    node = graph.nodes[nid]
    pixels, points = node["pixels"], np.asarray(graph.xy(node["pixels"]), int)
    adjacencies = {tuple(sorted((a, b))) for a in pixels for b in graph.neighbors(a) if b in pixels}
    reasons = []
    if len(pixels) > POLICY["maximum_core_pixels"] or np.ptp(points, axis=0).max() > POLICY["maximum_core_extent_px"]:
        reasons.append("PENDING_SOURCE_CORE_RESOURCE_BOUNDARY")
    if len(adjacencies) != len(pixels) - 1:
        reasons.append("PENDING_CYCLIC_CORE_OUTSIDE_INDEPENDENT_SUBSET")
    if node["internal_source_endpoint_count"]:
        reasons.append("PENDING_INTERNAL_SOURCE_FREE_ENDPOINT")
    x0, y0 = np.maximum(points.min(axis=0) - 2, 0)
    x1, y1 = np.minimum(points.max(axis=0) + 3, [source.shape[1], source.shape[0]])
    ink = source[y0:y1, x0:x1] < POLICY["source_threshold"]
    whites, count = label(~ink)
    boundary = set(whites[0]) | set(whites[-1]) | set(whites[:, 0]) | set(whites[:, -1])
    holes = [i for i in range(1, count + 1) if i not in boundary]
    if holes:
        reasons.append("PENDING_ORIGINAL_WHITE_HOLE_IN_SOURCE_CORE")
    if not directions["all_directions_complete"]:
        reasons.append("PENDING_SOURCE_CORE_DIRECTION_CHORD")
    return {"pass": not reasons, "reasons": reasons, "source_core_pixels": points.tolist(),
            "all_original_adjacencies": [np.asarray(graph.xy(e), int).tolist() for e in sorted(adjacencies)],
            "raw_box_xyxy_px": [int(x0), int(y0), int(x1), int(y1)], "white_hole_count": len(holes),
            "direction_evidence": directions}


def _core_evidence_v2(source, graph, nid, directions=None):
    """Admit a bounded solid microcycle without deleting any source adjacency."""
    directions = directions or _direction_table_v2(graph, nid)
    result = _core_evidence(source, graph, nid, directions)
    cyclic = "PENDING_CYCLIC_CORE_OUTSIDE_INDEPENDENT_SUBSET"
    points = np.asarray(graph.xy(graph.nodes[nid]["pixels"]), int)
    low, high = points.min(axis=0), points.max(axis=0) + 1
    patch = np.asarray(source[low[1]:high[1], low[0]:high[0]])
    ports = {tuple(p) for p in graph.nodes[nid]["edges"]}
    pairs = [set(map(tuple, row["ports"])) for row in directions["pairs"] if row["pass"]]
    covered = set().union(*pairs) if pairs else set()
    unique = all(sum(p in pair for pair in pairs) == 1 for p in ports)
    if cyclic in result["reasons"]:
        result["reasons"].remove(cyclic)
        if not bool(np.all(patch < POLICY["source_threshold"])):
            result["reasons"].append("PENDING_CYCLIC_CORE_MINIMAL_RECTANGLE_IS_NOT_SOLID_ORIGINAL_INK")
        if not ports or covered != ports or not unique:
            result["reasons"].append("PENDING_CYCLIC_CORE_EXTERNAL_ARMS_LACK_COMPLETE_UNIQUE_PAIRING")
        result["accepted_core_subset"] = "SOLID_RAW_RECTANGLE_MICROCYCLE_WITH_UNIQUE_EXTERNAL_PAIRS"
    else:
        result["accepted_core_subset"] = "TREE_WITHOUT_INTERNAL_FREE_ENDPOINT_OR_WHITE_HOLE"
    result.update(pass_=not result["reasons"], schema="independent-raw-source-core-v2",
        minimal_raw_box_xyxy_px=[int(low[0]), int(low[1]), int(high[0]), int(high[1])],
        minimal_raw_box_all_black=bool(np.all(patch < POLICY["source_threshold"])),
        minimal_raw_box_sha256=hashlib.sha256(patch.tobytes()).hexdigest(),
        source_array_sha256=hashlib.sha256(source.tobytes()).hexdigest(),
        original_adjacencies_removed=[], source_pixels_modified=False,
        complete_external_unique_pairing=bool(ports and covered == ports and unique))
    result["pass"] = result.pop("pass_")
    return result


def _free_cap(source, graph, terminal, native_endpoint):
    nid, port = terminal["node_id"], tuple(terminal["port"])
    node = graph.nodes[nid]
    start = tuple(map(int, graph.xy(graph.oriented(port))[0]))
    x, y = start
    radius = POLICY["free_cap_extent_px"] + 2
    x0, y0, x1, y1 = max(0, x - radius), max(0, y - radius), min(source.shape[1], x + radius + 1), min(source.shape[0], y + radius + 1)
    ink = source[y0:y1, x0:x1] < POLICY["source_threshold"]
    labels, _ = label(ink, structure=np.ones((3, 3), int))
    ys, xs = np.nonzero(labels == labels[y - y0, x - x0])
    # Thinning can retract a skeleton tip into a genuine round cap.  Its node
    # supplies a source direction and free-end identity, not a CAD endpoint.
    # The actual saved endpoint must explain this same original cap in the
    # joint finite union; its source normal/forward bound is measured here.
    points = [(Fraction(int(px + x0)) - native_endpoint[0],
               Fraction(int(py + y0)) - native_endpoint[1]) for px, py in zip(xs, ys)]
    observations, failures = component.source_observations(graph, port), []
    if (len(node["edges"]) != 1 or node["internal_source_endpoint_count"] != 1 or
            (node.get("terminal") or {}).get("kind") != "OBSERVED_FREE_SOURCE_ENDPOINT"):
        failures.append("SOURCE_NODE_IS_NOT_A_PROVED_FREE_END")
    for observation in observations:
        a, b = observation["source_points_px"][0], observation["source_points_px"][-1]
        out = tuple(v - u for v, u in zip(a, b))
        norm2 = sum(v * v for v in out)
        if norm2 < 16:
            failures.append("SOURCE_FREE_END_DIRECTION_TOO_SHORT")
            continue
        for point in points:
            forward = sum(v * u for v, u in zip(out, point))
            normal = _cross(out, point)
            if (normal * normal <= Fraction(9, 4) * norm2 and forward > 0 and
                    forward * forward > POLICY["free_cap_extent_px"] ** 2 * norm2):
                failures.append("OBSERVABLE_INK_BEYOND_SOURCE_FREE_CAP")
                break
    return {"pass": not failures, "reasons": sorted(set(failures)), "source_endpoint_px": list(start),
            "observations": observations, "all_original_component_pixels_retained": True}


def _reconstruct_routes(source, graph, records, target_ids, scope, *, source_model="v1", actual_prior_rows=()):
    bodies, issues, ownership = [], [], []
    direction_table = _direction_table_v2 if source_model == "v2" else _direction_table
    core_evidence = _core_evidence_v2 if source_model == "v2" else _core_evidence
    prepared = {r["object_id"]: exact.prepare_polyline(exact_points(r)) for r in records}
    owned = {r["object_id"]: [] for r in records}
    for eid, edge in enumerate(graph.edges):
        pixels = np.asarray(graph.xy(edge["pixels"]), int)
        candidates = []
        for row in records:
            oid = row["object_id"]
            threshold = Fraction(9, 4) if oid in target_ids else Fraction(4)
            box = row["bbox_xyxy"]
            # Broad rejection only; every accepted edge is checked exactly.
            if (pixels[:, 0].max() < box[0] - 2 or pixels[:, 0].min() > box[2] + 2 or
                    pixels[:, 1].max() < box[1] - 2 or pixels[:, 1].min() > box[3] + 2):
                continue
            if all(exact.point_polyline_distance_squared(tuple(map(int, p)), prepared[oid]) <= threshold for p in pixels):
                candidates.append(oid)
        if candidates:
            ownership.append({"source_edge_id": eid, "eligible_actual_saved_body_ids": candidates})
        if len(candidates) == 1:
            owned[candidates[0]].append(eid)
        elif len(candidates) > 1:
            issues.append({"reason": "PENDING_SOURCE_EDGE_HAS_MULTIPLE_SAVED_OWNERS", "source_edge_id": eid,
                           "body_ids": candidates})
    core_cache, direction_cache = {}, {}
    for row in records:
        oid, ids = row["object_id"], owned[row["object_id"]]
        try:
            if not ids or len(ids) > POLICY["maximum_route_edges"]:
                raise ValueError("PENDING_COMPLETE_SOURCE_ROUTE_MISSING_OR_RESOURCE_BOUND")
            incidence = {}
            for eid in ids:
                for end, nid in enumerate(graph.edges[eid]["nodes"]):
                    incidence.setdefault(nid, []).append((eid, end))
            terminals = [nid for nid, ports in incidence.items() if len(ports) == 1]
            if len(terminals) != 2 or any(len(ports) > 2 for ports in incidence.values()):
                raise ValueError("PENDING_SOURCE_ROUTE_BRANCHES_OR_CLOSES")
            native = exact_points(row)
            threshold = Fraction(9, 4) if oid in target_ids else Fraction(4)
            start = min(terminals, key=lambda nid: min(exact.squared_distance(native[0], tuple(map(int, p)))
                        for p in graph.xy(graph.nodes[nid]["pixels"])))
            nid, remaining, raw, used, nodes, terminal_records, core_routes = start, set(ids), [], [], [start], [], []
            first_port = incidence[start][0]
            port = first_port
            while remaining:
                eid = port[0]
                if eid not in remaining:
                    raise ValueError("PENDING_SOURCE_ROUTE_REUSES_EDGE")
                remaining.remove(eid)
                part = list(graph.oriented(port))
                if raw:
                    alternatives = _core_walks(graph, nid, raw[-1], part[0])
                    if any(exact.point_polyline_distance_squared(tuple(map(int, p)), prepared[oid]) > threshold
                           for walk in alternatives for p in graph.xy(walk)):
                        raise ValueError("PENDING_CORE_ENCODINGS_DISAGREE_WITH_FINITE_GEOMETRY")
                    raw += alternatives[0][1:] + part[1:]
                    core_routes.append({"node_id": nid, "all_walks_px": [np.asarray(graph.xy(p), int).tolist() for p in alternatives]})
                    if nid not in direction_cache:
                        direction_cache[nid] = direction_table(graph, nid)
                    table = direction_cache[nid]
                    pair = next(p for p in table["pairs"] if set(map(tuple, p["ports"])) == set(incidence[nid]))
                    if not pair["pass"]:
                        issues.append({"reason": "PENDING_ROUTE_DIRECTION_OR_COMPETITOR", "body_id": oid, "node_id": nid})
                    core_cache[nid] = core_evidence(source, graph, nid, table)
                else:
                    raw = part
                used.append(eid)
                nid = graph.edges[eid]["nodes"][1 - port[1]]
                incoming = (eid, 1 - port[1])
                nodes.append(nid)
                if nid in terminals:
                    if remaining:
                        raise ValueError("PENDING_DISCONNECTED_SOURCE_ROUTE")
                    terminal_records = [{"node_id": start, "port": list(first_port)},
                                        {"node_id": nid, "port": list(incoming)}]
                    break
                port = next(p for p in incidence[nid] if p != incoming)
            for end, terminal in enumerate(terminal_records):
                nid = terminal["node_id"]
                native_endpoint = native[0 if end == 0 else -1]
                anchor = min(graph.nodes[nid]["pixels"], key=lambda pixel: exact.squared_distance(
                             native_endpoint, tuple(map(int, graph.xy([pixel])[0]))))
                if (len(graph.nodes[nid]["edges"]) > 1 and
                        exact.squared_distance(native_endpoint, tuple(map(int, graph.xy([anchor])[0]))) > threshold):
                    issues.append({"reason": "PENDING_SAVED_ENDPOINT_OUTSIDE_SOURCE_TERMINAL_CORE", "body_id": oid, "end": end})
                extra = _core_walks(graph, nid, anchor if end == 0 else raw[-1], raw[0] if end == 0 else anchor)
                raw = extra[0][:-1] + raw if end == 0 else raw + extra[0][1:]
            body = {"stroke_id": oid, "representation": {"points": row["points"], "bulges": row["bulges"], "closed": False},
                    "representation_exact_points": [_encoded(p) for p in native],
                    "source_graph_edge_ids": used, "source_node_ids": nodes,
                    "source_path_px": np.asarray(graph.xy(raw), int).tolist(),
                    "endpoint_evidence": terminal_records, "independent_core_walks": core_routes,
                    "body_role": "COMPLETE_TARGET_STROKE" if oid in target_ids else "NECESSARY_PRIOR_FINITE_NEIGHBOR"}
            bodies.append(body)
        except (ValueError, KeyError, StopIteration) as exc:
            issues.append({"body_id": oid, "reason": str(exc) or type(exc).__name__})
    for body in bodies:
        for end, terminal in enumerate(body["endpoint_evidence"]):
            nid = terminal["node_id"]
            node = graph.nodes[nid]
            native = [tuple(exact.decode_rational(v) for v in p) for p in body["representation_exact_points"]]
            endpoint = native[0 if end == 0 else -1]
            outside = not (scope[0] <= endpoint[0] < scope[2] and scope[1] <= endpoint[1] < scope[3])
            if body["body_role"] == "NECESSARY_PRIOR_FINITE_NEIGHBOR" and outside:
                terminal.update(kind="OUT_OF_COMPONENT_SCOPE_PRIOR_TERMINAL",
                                remote_endpoint_certified_by_this_local_audit=False,
                                local_shaft_exit_requires_independent_kernel_proof=True)
                continue
            if len(node["edges"]) == 1:
                terminal["kind"] = "OBSERVED_FREE_SOURCE_ENDPOINT"
                terminal["source_cap_evidence"] = _free_cap(source, graph, terminal, native[0 if end == 0 else -1])
                if not terminal["source_cap_evidence"]["pass"]:
                    issues.append({"reason": "PENDING_INDEPENDENT_FREE_CAP", "body_id": body["stroke_id"],
                                   "end": end, "details": terminal["source_cap_evidence"]["reasons"]})
            else:
                terminal["kind"] = "OBSERVED_COMPLETE_STROKE_ATTACHMENT"
                hosts = [other for other in bodies if other is not body and nid in other["source_node_ids"][1:-1]]
                if source_model == "v2":
                    # A prior host is a locator here, never a renewed complete
                    # path. The shared component must independently certify its
                    # finite port and historical whole-object identity later.
                    for prior in actual_prior_rows:
                        if not prior.get("geometry_supported"):
                            continue
                        prior_points = exact_points(prior)
                        if exact.point_polyline_distance_squared(endpoint, prior_points):
                            continue
                        local_edges = []
                        for port in node["edges"]:
                            if port[0] in body["source_graph_edge_ids"]:
                                continue
                            observations = component.source_observations(graph, port)
                            if observations and all(exact.point_polyline_distance_squared(tuple(p), prior_points) <= 4
                                                    for o in observations for p in o["source_points_px"]):
                                local_edges.append(port[0])
                        if len(set(local_edges)) == 2:
                            hosts.append({"stroke_id": prior["object_id"],
                                "representation": {"points": prior["points"], "bulges": prior["bulges"], "closed": False},
                                "representation_exact_points": [_encoded(p) for p in prior_points],
                                "source_graph_edge_ids": sorted(set(local_edges)), "source_node_ids": [None, nid, None],
                                "prior_parent_locator": prior["parent_object_id"]})
                if len(hosts) == 1:
                    terminal["host_path_id"] = hosts[0]["stroke_id"]
                    if "prior_parent_locator" in hosts[0]:
                        terminal["finite_prior_host_parent_id"] = hosts[0]["prior_parent_locator"]
                        terminal["host_requires_necessary_prior_proof"] = True
                    point = native[0 if end == 0 else -1]
                    host = [tuple(exact.decode_rational(v) for v in p) for p in hosts[0]["representation_exact_points"]]
                    distance = exact.point_polyline_distance_squared(point, host)
                    terminal["independent_exact_finite_contact_squared_distance"] = exact.encode_rational(distance)
                    if distance:
                        issues.append({"reason": "LIMITED_ACTUAL_FINITE_ATTACHMENT_HAS_NONZERO_GAP", "body_id": body["stroke_id"],
                                       "end": end, "distance_squared": exact.encode_rational(distance)})
                    if nid not in direction_cache:
                        direction_cache[nid] = direction_table(graph, nid)
                    directions = direction_cache[nid]
                    guest_port = tuple(terminal["port"])
                    host_ports = {tuple(p) for p in node["edges"] if p[0] in hosts[0]["source_graph_edge_ids"]}
                    observations = {tuple(r["port"]): r["observations"] for r in directions["observations"]}
                    angles = []
                    for host_port in host_ports:
                        for left, right in zip(observations[guest_port], observations[host_port]):
                            a = tuple(y - x for x, y in zip(left["source_points_px"][0], left["source_points_px"][-1]))
                            b = tuple(y - x for x, y in zip(right["source_points_px"][0], right["source_points_px"][-1]))
                            angle = _angle(a, b)
                            angles.append(min(angle, 180. - angle))
                    terminal["independent_attachment_axis_angles_deg"] = angles
                    if len(host_ports) != 2 or not angles or min(angles) < POLICY["minimum_attachment_axis_separation_deg"]:
                        issues.append({"reason": "PENDING_ATTACHMENT_DIRECTION_SEPARATION", "body_id": body["stroke_id"], "end": end})
                    core_cache[nid] = core_evidence(source, graph, nid, directions)
                    if source_model == "v2" and "prior_parent_locator" not in hosts[0]:
                        from .finite_source_junction import prove_finite_junction_domain
                        domain = prove_finite_junction_domain(source, graph, nid, body, hosts[0], end)
                        terminal["independent_raw_ink_junction_domain"] = domain
                        if not domain["pass"]:
                            issues.append({"reason": "PENDING_INDEPENDENT_FINITE_RAW_JUNCTION_DOMAIN",
                                           "body_id": body["stroke_id"], "end": end, "details": domain.get("failure_reasons", [])})
                    elif source_model == "v2":
                        terminal["junction_domain_requires_component_finite_prior_certificate"] = True
                else:
                    issues.append({"reason": "PENDING_ATTACHMENT_HAS_NO_UNIQUE_COMPLETE_SAVED_HOST", "body_id": body["stroke_id"], "end": end})
    for nid, proof in core_cache.items():
        if not proof["pass"]:
            issues.append({"reason": "PENDING_INDEPENDENT_SHARED_CORE", "node_id": nid, "details": proof["reasons"]})
    return bodies, core_cache, {"pass": not issues, "issues": issues, "all_graph_edges_examined": len(graph.edges),
                               "edge_ownership": ownership, "producer_chain_consumed": False,
                               "reconstructed_body_count": len(bodies), "requested_body_count": len(records)}


def audit_saved_source_component(dxf_path, source_path, roi, dpi, target_ids, *, font_bindings=None,
                                expected_dxf_sha256=None, expected_source_sha256=None, source_model="v1",
                                prior_source_bindings=None, circle_source_objects=None):
    """Accept only the actual saved finite component under the frozen subset.

    Target IDs are locators, not an expected object count or a source truth.
    Necessary finite neighbors are discovered from saved geometry and the raw
    connected source component inside the independently computed local window.
    """
    if source_model == "v2":
        return _audit_saved_source_component_v2(dxf_path, source_path, roi, dpi, target_ids,
            font_bindings=font_bindings, expected_dxf_sha256=expected_dxf_sha256,
            expected_source_sha256=expected_source_sha256, prior_source_bindings=prior_source_bindings,
            circle_source_objects=circle_source_objects)
    if source_model != "v1":
        raise ValueError("UNKNOWN_INDEPENDENT_FINITE_SOURCE_MODEL")
    reader = saved_source_geometries(dxf_path, roi, dpi, font_bindings=font_bindings,
        expected_dxf_sha256=expected_dxf_sha256, source_path=source_path,
        expected_source_sha256=expected_source_sha256)
    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    if sha256(source_path) != reader["source_sha256"]:
        raise ValueError("SOURCE_CHANGED_DURING_INDEPENDENT_COLD_READ")
    target_ids = set(target_ids)
    targets = [r for r in reader["geometries"] if r["object_id"] in target_ids or r["parent_object_id"] in target_ids]
    report = {"schema": SCHEMA, "policy": dict(POLICY), "audit_sha256": sha256(__file__),
              "reader_sha256": reader["reader_sha256"], "dxf_sha256": reader["dxf_sha256"],
              "source_sha256": reader["source_sha256"], "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
              "pass": False, "status": "PENDING_INDEPENDENT_SOURCE_EVIDENCE", "target_ids": sorted(target_ids),
              "saved_reader_counts": reader["counts"], "saved_identity_errors": reader["identity_errors"],
              "producer_approval_consumed": False, "geometry_modified": False,
              "formal_adoption_verdict": "NOT_ESTABLISHED_BY_LOCAL_SOURCE_ACCEPTANCE",
              "source_decode": "PIL_GRAYSCALE_WITHOUT_RESIZE_ROTATION_OR_PIXEL_REPAIR",
              "geometry_wrong_or_scan_ambiguous_asserted": False, "failure_reasons": []}
    represented = {r["object_id"] for r in targets} | {r["parent_object_id"] for r in targets}
    if not target_ids or not target_ids <= represented or any(not r["geometry_supported"] for r in targets):
        report["failure_reasons"] = ["PENDING_ACTUAL_SAVED_TARGET_MISSING_OR_UNSUPPORTED"]
        return report
    actual_targets = {r["object_id"] for r in targets}
    points = [p for r in targets for p in exact_points(r)]
    border = component.POLICY["window_border_px"]
    scope = [math.floor(min(p[0] for p in points)) - border, math.floor(min(p[1] for p in points)) - border,
             math.ceil(max(p[0] for p in points)) + border + 1, math.ceil(max(p[1] for p in points)) + border + 1]
    scope = [max(0, scope[0]), max(0, scope[1]), min(source.shape[1], scope[2]), min(source.shape[0], scope[3])]
    context = context_for_scope(reader, scope, exclude_object_ids=actual_targets)
    report["context_relevance"] = context
    x0, y0, x1, y1 = scope
    labels, _ = label(source[y0:y1, x0:x1] < POLICY["source_threshold"], structure=np.ones((3, 3), int))
    def source_labels(cells):
        return {int(labels[y - y0, x - x0]) for x, y in cells if x0 <= x < x1 and y0 <= y < y1} - {0}
    supports = {r["object_id"]: _finite_support(source, r) for r in targets}
    touched = set().union(*(source_labels(s["closed_cells"]) for s in supports.values()))
    selected, related, unresolved = list(targets), [], []
    members = {r["object_id"]: r for r in reader["geometries"]}
    for entry in context["members"]:
        if entry["relation"] in ("PROVED_DISJOINT", "PROVED_EMPTY"):
            continue
        row = members[entry["object_id"]]
        if not row["geometry_supported"]:
            unresolved.append({"object_id": row["object_id"], "relation": entry["relation"],
                               "reason": row.get("extent_unknown_reason", row.get("unsupported_reason"))})
            continue
        related.append(row)
        support = _finite_support(source, row)
        if source_labels(support["closed_cells"]) & touched:
            supports[row["object_id"]] = support
            selected.append(row)
    report["unresolved_relevant_context"] = unresolved
    for oid, support in supports.items():
        if not support["pass"]:
            failed_cells = [cell for item in support["uncovered_positive_intervals"] for cell in item["white_cells"]]
            failed_cells += support["outside_cells"]
            support["target_or_context_role"] = "TARGET" if oid in actual_targets else "NECESSARY_PRIOR_CONTEXT"
            support["all_failure_cells_outside_target_window"] = all(
                not (x0 <= x < x1 and y0 <= y < y1) for x, y in failed_cells)
    report["finite_support"] = list(supports.values())
    pairs = _pair_checks(source, targets + related, actual_targets)
    report["exact_saved_finite_contacts"] = pairs
    if len(selected) > POLICY["maximum_bodies"]:
        report["failure_reasons"] = ["PENDING_NECESSARY_BODY_RESOURCE_BOUNDARY"]
        return report
    source_graph = build_text_contact_source_graph(source, roi)
    report["fresh_graph"] = {"source_crop_sha256": source_graph.source_crop_hash,
        "skeleton_sha256": hashlib.sha256(source_graph.graph.skel.tobytes()).hexdigest(),
        "source_graph_rebuilt_from_unmodified_image": True,
        "graph_source_sha256": sha256(build_text_contact_source_graph.__code__.co_filename)}
    bodies, cores, routes = _reconstruct_routes(source, source_graph.graph, selected, actual_targets, scope)
    report["independent_routes"] = routes
    report["reconstructed_source_bindings"] = bodies
    # Source-model stopping conditions apply before an expensive competition
    # search.  Unsupported bodies cannot be silently dropped and the remaining
    # subset cannot establish complete component feasibility or uniqueness.
    all_geometry = [{"stroke_id": r["object_id"],
                     "representation": {"points": r["points"], "bulges": r["bulges"], "closed": False},
                     "representation_exact_points": [_encoded(p) for p in exact_points(r)]} for r in selected]
    boxes = [tuple(Fraction(*v) for v in r["bbox_xyxy_exact"]) for r in selected]
    reach = component.POLICY["maximum_section_half_span_px"] + 1
    forbidden = {tuple(map(int, point)) for node in source_graph.graph.nodes.values()
                 for point in source_graph.graph.xy(node["pixels"])
                 if any(box[0] - reach <= int(point[0]) <= box[2] + reach and
                        box[1] - reach <= int(point[1]) <= box[3] + reach for box in boxes)}
    widths = [{"stroke_id": body["stroke_id"], "body_role": body["body_role"],
               "width": component.measure_whole_chain_width(source, source_graph.graph, body,
                         all_geometry, forbidden_core_cells=forbidden)} for body in bodies]
    report["independent_whole_chain_widths"] = widths
    empty_width = any(row["width"].get("reason") == "CONSTANT_WIDTH_MODEL_INAPPLICABLE" for row in widths)
    prerequisites = (routes["pass"] and len(bodies) == len(selected) and not unresolved and
                     all(s["pass"] for s in supports.values()) and pairs["pass"] and
                     not reader["identity_errors"] and reader["enumeration_complete"])
    if bodies and prerequisites and not empty_width:
        model = component.audit_finite_bodies(source, source_graph.graph, bodies, cores=cores)
    else:
        model = {"pass": False, "status": "MODEL_NOT_APPLICABLE_CONSTANT_WIDTH" if empty_width else
                 "NOT_RUN_INDEPENDENT_SOURCE_PREREQUISITE_PENDING", "bodies": widths,
                 "failure_reasons": ["STOP_BEFORE_JOINT_MODEL_AND_COMPETITION"],
                 "skipped_joint_model_is_not_an_infeasibility_proof": not empty_width,
                 "component_model_code_sha256": component.producer_sha256()}
    report["finite_component_model"] = model
    failures = report["failure_reasons"]
    if reader["identity_errors"] or not reader["enumeration_complete"]:
        failures.append("SAVED_DXF_MEMBERSHIP_INCOMPLETE")
    if not expected_source_sha256:
        failures.append("EXTERNAL_ORIGINAL_SOURCE_HASH_REQUIRED")
    if not touched:
        failures.append("NO_ORIGINAL_CONNECTED_TARGET_SOURCE")
    if not all(s["pass"] for oid, s in supports.items() if oid in actual_targets):
        failures.append("ACTUAL_TARGET_FINITE_SOURCE_SUPPORT_FAILED")
    if not all(s["pass"] for oid, s in supports.items() if oid not in actual_targets):
        failures.append("NECESSARY_PRIOR_SOURCE_SUPPORT_NOT_ESTABLISHED")
    if not pairs["pass"]:
        failures.append("EXACT_FINITE_CONTACT_OR_DUPLICATE_FAILED")
    if unresolved:
        failures.append("RELEVANT_CONTEXT_NOT_INDEPENDENTLY_RESOLVED")
    if not routes["pass"] or len(bodies) != len(selected):
        failures.append("INDEPENDENT_COMPLETE_SOURCE_ROUTE_NOT_ESTABLISHED")
    if not model["pass"]:
        failures.append("COMPLETE_COMPONENT_MODEL_NOT_ESTABLISHED")
    report["pass"] = not failures
    width_statuses = [b["width"].get("status", b["width"].get("reason", "")) for b in model.get("bodies", [])]
    report["width_status_counts"] = dict(Counter(width_statuses))
    hard = any(s["status"].startswith("HARD_REJECT") for oid, s in supports.items()
               if oid in actual_targets) or bool(pairs["positive_length_overlaps"])
    hard |= any(h["status"].startswith("HARD_REJECT") for h in pairs["contacts"])
    if report["pass"]:
        report["status"] = "COMPLETE_SOURCE_PASS"
    elif hard:
        report["status"] = "HARD_REJECT_SAVED_FINITE_GEOMETRY"
    elif any(status == "CONSTANT_WIDTH_MODEL_INAPPLICABLE" or "MODEL_NOT_APPLICABLE" in status
             for status in width_statuses):
        report["status"] = "MODEL_NOT_APPLICABLE_CONSTANT_WIDTH"
    report["report_binding_sha256"] = _digest({"dxf": report["dxf_sha256"], "source": report["source_sha256"],
        "source_array": report["source_array_sha256"], "reader": report["reader_sha256"],
        "auditor": report["audit_sha256"], "graph": report["fresh_graph"], "target_ids": sorted(actual_targets)})
    return _plain(report)


def _audit_saved_source_component_v2(dxf_path, source_path, roi, dpi, target_ids, *, font_bindings=None,
                                    expected_dxf_sha256=None, expected_source_sha256=None,
                                    prior_source_bindings=None, circle_source_objects=None):
    """Cold-read targets, then ask the common model for finite prior context.

    A full historical prior support failure is retained as a diagnostic. Only
    the finite-port certificate may prove its exclusion from the complete read
    domain. Actual saved context is always supplied, without geometry fallback.
    """
    reader = saved_source_geometries(dxf_path, roi, dpi, font_bindings=font_bindings,
        expected_dxf_sha256=expected_dxf_sha256, source_path=source_path,
        expected_source_sha256=expected_source_sha256, source_model="v2")
    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    if sha256(source_path) != reader["source_sha256"]:
        raise ValueError("SOURCE_CHANGED_DURING_INDEPENDENT_COLD_READ")
    target_ids = set(target_ids)
    targets = [r for r in reader["geometries"] if r["object_id"] in target_ids or r["parent_object_id"] in target_ids]
    report = {"schema": "independent-saved-finite-component-source-acceptance-v2",
        "policy": {**POLICY, "accepted_core_subset": "ALL_ORIGINAL_CORE_ROUTES_AND_SOLID_UNIQUELY_PAIRED_MICROCYCLES",
            "prior_responsibility": "SOURCE_BOUND_FINITE_PORT_WITH_COMPLETE_ACTUAL_EVIDENCE_DOMAIN",
            "circle_responsibility": "ACTUAL_CIRCLE_FINITE_ARC_AND_INDEPENDENT_RADIAL_OBSERVATIONS"},
        "audit_sha256": sha256(__file__), "reader_sha256": reader["reader_sha256"],
        "dxf_sha256": reader["dxf_sha256"], "source_sha256": reader["source_sha256"],
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "target_ids": sorted(target_ids), "saved_reader_counts": reader["counts"],
        "saved_identity_errors": reader["identity_errors"], "producer_approval_consumed": False,
        "source_decode": "PIL_GRAYSCALE_WITHOUT_RESIZE_ROTATION_OR_PIXEL_REPAIR",
        "geometry_modified": False, "geometry_wrong_or_scan_ambiguous_asserted": False,
        "formal_adoption_verdict": "NOT_ESTABLISHED_BY_LOCAL_SOURCE_ACCEPTANCE",
        "pass": False, "status": "PENDING_INDEPENDENT_SOURCE_EVIDENCE", "failure_reasons": []}
    represented = {r["object_id"] for r in targets} | {r["parent_object_id"] for r in targets}
    if not target_ids or not target_ids <= represented or any(not r["geometry_supported"] for r in targets):
        report["failure_reasons"] = ["PENDING_ACTUAL_SAVED_TARGET_MISSING_OR_UNSUPPORTED"]
        return report
    actual_targets = {r["object_id"] for r in targets}
    from .finite_source_ports import _canonical_window
    scope = _canonical_window(source, targets)
    report["model_window"] = scope
    context = context_for_scope(reader, scope, exclude_object_ids=actual_targets)
    report["context_relevance"] = context
    members = {r["object_id"]: r for r in reader["geometries"]}
    actual_prior_rows = [r for r in reader["geometries"] if r["object_id"] not in actual_targets]
    linear_related, curve_related, unresolved = [], [], []
    for entry in context["members"]:
        if entry["relation"] in ("PROVED_DISJOINT", "PROVED_EMPTY"):
            continue
        row = members[entry["object_id"]]
        if row["geometry_supported"]:
            linear_related.append(row)
        elif row.get("curve_geometry_supported") and row.get("curve_type") == "CIRCLE":
            curve_related.append(row)
        else:
            unresolved.append({"object_id": row["object_id"], "relation": entry["relation"],
                "reason": row.get("extent_unknown_reason", row.get("unsupported_reason", "UNSUPPORTED_RELEVANT_CONTEXT"))})
    supports = [_finite_support(source, row) for row in targets]
    report["finite_support"] = supports
    report["unresolved_relevant_context"] = unresolved
    report["actual_related_circle_ids"] = [r["object_id"] for r in curve_related]
    report["historical_prior_whole_support_diagnostics"] = [_finite_support(source, row) for row in linear_related]
    report["whole_prior_failures_require_finite_read_domain_certificate"] = True
    pairs = _pair_checks(source, targets + linear_related, actual_targets)
    report["exact_saved_finite_contacts"] = pairs
    context_graph = build_text_contact_source_graph(source, roi)
    graph = context_graph.graph
    report["fresh_graph"] = {"source_crop_sha256": context_graph.source_crop_hash,
        "skeleton_sha256": hashlib.sha256(graph.skel.tobytes()).hexdigest(),
        "source_graph_rebuilt_from_unmodified_image": True,
        "graph_source_sha256": sha256(build_text_contact_source_graph.__code__.co_filename)}
    bodies, cores, routes = _reconstruct_routes(source, graph, targets, actual_targets, scope,
        source_model="v2", actual_prior_rows=linear_related)
    report["independent_routes"] = routes
    report["independent_shared_cores"] = [{"node_id": nid, **proof} for nid, proof in sorted(cores.items())]
    report["reconstructed_source_bindings"] = bodies
    report["prior_whole_routes_reconstructed_as_targets"] = False
    priors = list((prior_source_bindings or {}).values()) if isinstance(prior_source_bindings, dict) else list(prior_source_bindings or [])
    circles = list((circle_source_objects or {}).values()) if isinstance(circle_source_objects, dict) else list(circle_source_objects or [])
    prerequisites = (routes["pass"] and len(bodies) == len(targets) and all(s["pass"] for s in supports)
                     and pairs["pass"] and not unresolved and not reader["identity_errors"]
                     and reader["enumeration_complete"])
    if prerequisites:
        try:
            from . import bounded_source_component as bounded
        except ImportError as exc:
            model = {"pass": False, "status": "PENDING_BOUNDED_SOURCE_COMPONENT_NOT_READY",
                     "failure_reasons": [str(exc)], "stage_executed": False}
        else:
            model = bounded.audit_bounded_bodies(source, graph, bodies, cores=cores,
                prior_objects=priors, circle_source_objects=circles, roi=roi, dpi=dpi,
                actual_saved_prior_rows=actual_prior_rows)
    else:
        model = {"pass": False, "status": "NOT_RUN_INDEPENDENT_SOURCE_PREREQUISITE_PENDING",
            "failure_reasons": ["STOP_BEFORE_JOINT_MODEL_AND_COMPETITION"],
            "skipped_joint_model_is_not_an_infeasibility_proof": True, "stage_executed": False}
    report["finite_component_model"] = model
    failures = report["failure_reasons"]
    if reader["identity_errors"] or not reader["enumeration_complete"]:
        failures.append("SAVED_DXF_MEMBERSHIP_INCOMPLETE")
    if not expected_source_sha256:
        failures.append("EXTERNAL_ORIGINAL_SOURCE_HASH_REQUIRED")
    if not all(s["pass"] for s in supports):
        failures.append("ACTUAL_TARGET_FINITE_SOURCE_SUPPORT_FAILED")
    if not pairs["pass"]:
        failures.append("EXACT_FINITE_CONTACT_OR_DUPLICATE_FAILED")
    if unresolved:
        failures.append("RELEVANT_CONTEXT_NOT_INDEPENDENTLY_RESOLVED")
    if not routes["pass"] or len(bodies) != len(targets):
        failures.append("INDEPENDENT_COMPLETE_TARGET_SOURCE_ROUTE_NOT_ESTABLISHED")
    if not model["pass"]:
        failures.append("COMPLETE_BOUNDED_COMPONENT_MODEL_NOT_ESTABLISHED")
    report["pass"] = not failures
    hard = any(s["status"].startswith("HARD_REJECT") for s in supports) or bool(pairs["positive_length_overlaps"])
    hard |= any(h["status"].startswith("HARD_REJECT") for h in pairs["contacts"])
    report["status"] = "COMPLETE_SOURCE_PASS" if report["pass"] else "HARD_REJECT_SAVED_FINITE_GEOMETRY" if hard else (
        "PENDING_BOUNDED_SOURCE_COMPONENT_NOT_READY" if model["status"] == "PENDING_BOUNDED_SOURCE_COMPONENT_NOT_READY"
        else "PENDING_INDEPENDENT_BOUNDED_SOURCE_EVIDENCE")
    report["report_binding_sha256"] = _digest({"dxf": report["dxf_sha256"], "source": report["source_sha256"],
        "source_array": report["source_array_sha256"], "reader": report["reader_sha256"],
        "auditor": report["audit_sha256"], "graph": report["fresh_graph"], "target_ids": sorted(actual_targets),
        "full_prior_bindings_sha256": _digest(priors), "full_circle_source_objects_sha256": _digest(circles)})
    return _plain(report)
