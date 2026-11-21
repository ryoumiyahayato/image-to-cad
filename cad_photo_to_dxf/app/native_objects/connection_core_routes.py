"""Finite, source-complete encodings of a small two-port internal cycle.

This module never selects an electrical connection.  A tiny source cycle with
two tails has four odd-degree vertices, so an open walk covering every source
edge must retrace one cycle arc.  The two possible arc retraces have the same
visible source-edge union.  Choosing the shorter encoding is not a topology or
semantic inference.  A caller may use it only within a complete path between
two different observed round boundaries.
"""

from __future__ import annotations

from collections import Counter, deque
import hashlib
import math


def _edge(a, b):
    return tuple(sorted((a, b)))


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _point_segment_distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


def finite_two_port_cycle_cover(
    core_points,
    adjacency,
    port_points,
    port_ids,
    source_ink_at,
    *,
    maximum_core_pixels=24,
    maximum_core_extent_px=6,
    maximum_walk_steps=64,
):
    """Return a bounded cover certificate or an explicit pending reason.

    Coordinates are integer source pixels. ``adjacency`` must come from the
    unchanged source skeleton graph, including its diagonal-contact rule.
    ``source_ink_at`` reads the original thresholded source, not the skeleton.
    No source pixel or graph edge is created, removed, or reassigned here.
    """
    points = {tuple(map(int, p)) for p in core_points}
    ports = [tuple(map(int, p)) for p in port_points]
    report = {
        "eligible": False,
        "all_ports": [list(p) for p in port_ids],
        "source_core_points": [list(p) for p in sorted(points)],
        "semantic_connection": "UNKNOWN_NOT_INFERRED",
        "single_owner_required": True,
        "round_to_different_round_endpoints_required": True,
        "source_pixels_modified": False,
        "source_short_branches_deleted": False,
    }

    def pending(reason):
        report["reason"] = reason
        report["decision"] = "PENDING_EXPLICIT_CORE_DECOMPOSITION"
        return report

    if len(ports) != 2 or len(port_ids) != 2 or port_ids[0][0] == port_ids[1][0]:
        return pending("LOCAL_CYCLE_REQUIRES_TWO_DISTINCT_EXTERNAL_EDGES")
    if ports[0] == ports[1] or not all(p in points for p in ports):
        return pending("LOCAL_CYCLE_COMPOSITE_OR_COINCIDENT_PORTS")
    if not points or len(points) > maximum_core_pixels:
        return pending("LOCAL_CYCLE_CORE_PIXEL_BUDGET_EXCEEDED")
    xmin = min(p[0] for p in points)
    xmax = max(p[0] for p in points)
    ymin = min(p[1] for p in points)
    ymax = max(p[1] for p in points)
    if max(xmax - xmin, ymax - ymin) > maximum_core_extent_px:
        return pending("LOCAL_CYCLE_CORE_EXTENT_BUDGET_EXCEEDED")
    adj = {p: {tuple(q) for q in adjacency[p] if tuple(q) in points} for p in points}
    if any(p not in adj[q] for p, qs in adj.items() for q in qs):
        return pending("LOCAL_CYCLE_SOURCE_ADJACENCY_NOT_SYMMETRIC")
    seen = {ports[0]}
    todo = [ports[0]]
    while todo:
        for q in adj[todo.pop()]:
            if q not in seen:
                seen.add(q)
                todo.append(q)
    all_edges = {_edge(p, q) for p, qs in adj.items() for q in qs}
    report["core_topology"] = {
        "pixels": len(points),
        "edges": len(all_edges),
        "components": 1 if seen == points else None,
        "cycle_rank": len(all_edges) - len(points) + 1 if seen == points else None,
    }
    report["source_core_edges"] = [[list(a), list(b)] for a, b in sorted(all_edges)]
    report["source_vertex_degrees"] = [
        {"point": list(p), "degree": len(adj[p])} for p in sorted(points)
    ]
    if seen != points:
        return pending("LOCAL_CYCLE_CORE_NOT_CONNECTED")
    if len(all_edges) != len(points):
        return pending("LOCAL_CYCLE_REQUIRES_EXACTLY_ONE_INTERNAL_CYCLE")
    leaves = {p for p in points if len(adj[p]) == 1}
    forks = {p for p in points if len(adj[p]) == 3}
    if (
        leaves != set(ports)
        or len(forks) != 2
        or any(len(adj[p]) not in (1, 2, 3) for p in points)
    ):
        return pending("LOCAL_CYCLE_HAS_EXTRA_BRANCH_OR_COMPOSITE_PORT")

    # Strip the two tails; the remainder must be a simple cycle with the two
    # attachment vertices distinct.  This enumerates exactly two cycle arcs.
    cycle = set(points)
    degrees = {p: len(adj[p]) for p in points}
    queue = deque(sorted(leaves))
    while queue:
        p = queue.popleft()
        if p not in cycle:
            continue
        cycle.remove(p)
        for q in adj[p] & cycle:
            degrees[q] -= 1
            if degrees[q] == 1:
                queue.append(q)
    if len(cycle) < 4 or any(len(adj[p] & cycle) != 2 for p in cycle):
        return pending("LOCAL_CYCLE_REMAINDER_NOT_A_SIMPLE_CYCLE")

    tails = []
    for port in ports:
        tail = [port]
        while tail[-1] not in cycle:
            next_points = adj[tail[-1]] - set(tail)
            if len(next_points) != 1:
                return pending("LOCAL_CYCLE_TAIL_IS_NOT_UNIQUE")
            tail.append(next_points.pop())
        tails.append(tail)
    a, b = tails[0][-1], tails[1][-1]
    if a == b or {a, b} != forks or set(tails[0][:-1]) & set(tails[1][:-1]):
        return pending("LOCAL_CYCLE_PORT_ATTACHMENTS_NOT_INDEPENDENT")

    arcs = []
    for first in sorted(adj[a] & cycle):
        arc = [a, first]
        while arc[-1] != b:
            next_points = (adj[arc[-1]] & cycle) - {arc[-2]}
            if len(next_points) != 1:
                return pending("LOCAL_CYCLE_ARC_NOT_UNIQUE")
            q = next_points.pop()
            if q in arc or len(arc) > maximum_walk_steps:
                return pending("LOCAL_CYCLE_ARC_BUDGET_OR_TOPOLOGY_FAILED")
            arc.append(q)
        arcs.append(arc)
    if set(arcs[0][1:-1]) & set(arcs[1][1:-1]):
        return pending("LOCAL_CYCLE_ARCS_SHARE_UNEXPLAINED_SOURCE")
    if set(tails[0]) | set(tails[1]) | set(arcs[0]) | set(arcs[1]) != points:
        return pending("LOCAL_CYCLE_HAS_UNACCOUNTED_SOURCE_POINTS")

    # Preserve a witnessed white hole in the original image.  A cycle created
    # by skeleton geometry alone is insufficient to authorize this encoding.
    if source_ink_at is None:
        return pending("LOCAL_CYCLE_REQUIRES_ORIGINAL_SOURCE_HOLE_EVIDENCE")
    bounds = [xmin - 1, ymin - 1, xmax + 2, ymax + 2]
    source_ink = {
        (x, y)
        for y in range(bounds[1], bounds[3])
        for x in range(bounds[0], bounds[2])
        if source_ink_at(x, y)
    }
    if not points <= source_ink:
        return pending("LOCAL_CYCLE_CORE_NOT_SUPPORTED_BY_ORIGINAL_SOURCE")
    white = {
        (x, y)
        for y in range(bounds[1], bounds[3])
        for x in range(bounds[0], bounds[2])
        if (x, y) not in source_ink
    }
    holes = []
    remaining = set(white)
    while remaining:
        connected = {remaining.pop()}
        queue = list(connected)
        while queue:
            x, y = queue.pop()
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                q = (x + dx, y + dy)
                if q in remaining:
                    remaining.remove(q)
                    connected.add(q)
                    queue.append(q)
        if not any(
            p[0] in (bounds[0], bounds[2] - 1) or p[1] in (bounds[1], bounds[3] - 1)
            for p in connected
        ):
            holes.append(connected)
    if len(holes) != 1:
        return pending("LOCAL_CYCLE_REQUIRES_ONE_ORIGINAL_ENCLOSED_WHITE_HOLE")
    hole = holes[0]
    # Black diagonal contacts and four-neighbor white regions are a
    # complementary digital-topology convention.  Also retain every white
    # diagonal contact: a four-neighbor pocket can be eight-connected to the
    # exterior and must never be described as an eight-neighbor closed hole.
    white_eight_reachable = set(hole)
    queue = list(hole)
    while queue:
        x, y = queue.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (x + dx, y + dy)
                if (dx or dy) and q in white and q not in white_eight_reachable:
                    white_eight_reachable.add(q)
                    queue.append(q)
    exterior_contacts = sorted(
        p
        for p in white_eight_reachable
        if p[0] in (bounds[0], bounds[2] - 1) or p[1] in (bounds[1], bounds[3] - 1)
    )
    diagonal_contacts = sorted(
        (p, (p[0] + dx, p[1] + dy))
        for p in hole
        for dx in (-1, 1)
        for dy in (-1, 1)
        if (p[0] + dx, p[1] + dy) in white - hole
    )
    source_bytes = bytes(
        1 if (x, y) in source_ink else 0
        for y in range(bounds[1], bounds[3])
        for x in range(bounds[0], bounds[2])
    )
    report["original_source_hole_evidence"] = {
        "neighborhood_xyxy_px": bounds,
        "thresholded_source_neighborhood_sha256": hashlib.sha256(
            source_bytes
        ).hexdigest(),
        "source_ink_points": [list(p) for p in sorted(source_ink)],
        "enclosed_white_hole_points": [list(p) for p in sorted(hole)],
        "white_hole_connectivity": 4,
        "white_eight_connected_to_neighborhood_boundary": bool(exterior_contacts),
        "white_eight_reachable_points": [
            list(p) for p in sorted(white_eight_reachable)
        ],
        "white_eight_neighborhood_boundary_contacts": [
            list(p) for p in exterior_contacts
        ],
        "white_diagonal_contacts_outside_four_neighbor_hole": [
            {"inside": list(p), "outside": list(q)} for p, q in diagonal_contacts
        ],
        "white_diagonal_contacts_removed": False,
        "eight_neighbor_enclosed_hole_claimed": not bool(exterior_contacts),
        "hole_pixels_filled": False,
    }
    candidates = []
    for index in range(2):
        repeated, other = arcs[index], arcs[1 - index]
        walk = (
            tails[0]
            + repeated[1:]
            + other[::-1][1:]
            + repeated[1:]
            + tails[1][::-1][1:]
        )
        if len(walk) - 1 > maximum_walk_steps:
            return pending("LOCAL_CYCLE_COVER_WALK_BUDGET_EXCEEDED")
        counts = Counter(_edge(p, q) for p, q in zip(walk, walk[1:]))
        if set(counts) != all_edges or any(v not in (1, 2) for v in counts.values()):
            return pending("LOCAL_CYCLE_COVER_FAILED_EXACT_EDGE_ACCOUNTING")
        clearance = min(
            _point_segment_distance(p, u, v)
            for p in hole
            for u, v in zip(walk, walk[1:])
        )
        if clearance < 0.5:
            return pending("LOCAL_CYCLE_COVER_WOULD_CONSUME_ORIGINAL_WHITE_HOLE")
        candidates.append(
            {
                "id": f"RETRACE_CYCLE_ARC_{index}",
                "source_walk_points": [list(p) for p in walk],
                "source_walk_length_px": _length(walk),
                "repeated_arc_points": [list(p) for p in repeated],
                "repeated_arc_length_px": _length(repeated),
                "source_edge_traversals": [
                    {
                        "source_edge": [list(u), list(v)],
                        "traversal_count": counts[(u, v)],
                        "owner_count": 1,
                    }
                    for u, v in sorted(all_edges)
                ],
                "all_core_source_edges_covered": True,
                "all_core_source_pixels_covered": set(walk) == points,
                "white_hole_minimum_route_clearance_px": clearance,
                "white_hole_points_on_route": [],
                "same_visible_source_edge_union": True,
            }
        )
    selected = min(
        candidates, key=lambda c: (c["repeated_arc_length_px"], c["source_walk_points"])
    )
    report.update(
        {
            "eligible": True,
            "reason": None,
            "decision": "FINITE_COVER_REQUIRES_DISTINCT_ROUND_TERMINALS",
            "cycle_arcs": [[list(p) for p in arc] for arc in arcs],
            "finite_cover_walks": candidates,
            "selected_encoding_id": selected["id"],
            "selection_rule": "MINIMUM_REPEATED_ARC_LENGTH_THEN_LEXICAL_SOURCE_WALK",
            "selection_is_encoding_only_not_semantic_inference": True,
            "source_edge_ownership_is_a_set_not_traversal_multiplicity": True,
            "all_core_walk_control_points_must_be_preserved": True,
        }
    )
    return report


def enumerate_bounded_cycle_cells(
    nodes,
    edges,
    neighbors,
    xy,
    source_ink_at,
    *,
    maximum_core_nodes=4,
    maximum_internal_edge_length_px=12.0,
    maximum_states_per_seed=128,
    maximum_core_pixels=24,
    maximum_core_extent_px=6,
    maximum_walk_steps=64,
):
    """Describe complete local cells without cutting off a real external port.

    The same enumeration includes a single contracted core, a core plus its
    self-loop, and a few cores joined by short source edges.  Every edge whose
    endpoints lie in the cell is included.  All remaining ports are external;
    cells with a real third port cannot pass the two-port cover certificate.
    Overlapping eligible cells and exhausted enumeration components stay
    pending, so iteration order cannot silently select an owner.
    """
    nonterminals = {
        nid
        for nid, node in nodes.items()
        if not node["terminal"]
        and node.get("reason") != "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT"
    }
    near = {nid: set() for nid in nonterminals}
    for edge in edges:
        a, b = edge["nodes"]
        if (
            a != b
            and a in near
            and b in near
            and edge["length"] <= maximum_internal_edge_length_px
        ):
            near[a].add(b)
            near[b].add(a)
    visited = set()
    rows = []
    budget_nodes = set()
    states = 0
    for seed in sorted(nonterminals):
        pending_sets = [frozenset([seed])]
        seed_states = 0
        while pending_sets:
            nids = pending_sets.pop()
            if nids in visited:
                continue
            visited.add(nids)
            seed_states += 1
            states += 1
            if seed_states > maximum_states_per_seed:
                component = {seed}
                queue = [seed]
                while queue:
                    for other in near[queue.pop()]:
                        if other not in component:
                            component.add(other)
                            queue.append(other)
                budget_nodes.update(component)
                break
            internal = sorted(
                {
                    eid
                    for nid in nids
                    for eid, _ in nodes[nid]["edges"]
                    if all(v in nids for v in edges[eid]["nodes"])
                }
            )
            external = [
                port
                for nid in sorted(nids)
                for port in nodes[nid]["edges"]
                if port[0] not in internal
            ]
            pixels = {p for nid in nids for p in nodes[nid]["pixels"]}
            for eid in internal:
                pixels.update(edges[eid]["pixels"])
            if len(pixels) > maximum_core_pixels:
                continue
            positions = {p: tuple(map(int, xy([p])[0])) for p in pixels}
            if (
                max(
                    max(p[axis] for p in positions.values())
                    - min(p[axis] for p in positions.values())
                    for axis in (0, 1)
                )
                > maximum_core_extent_px
            ):
                continue
            if (
                len(external) == 2
                and all(
                    edges[eid]["length"] <= maximum_internal_edge_length_px
                    for eid in internal
                )
                and not any(
                    nodes[nid].get("internal_source_endpoint_count") for nid in nids
                )
            ):
                adjacency = {
                    point: [positions[q] for q in neighbors(pixel) if q in pixels]
                    for pixel, point in positions.items()
                }
                port_points = [
                    positions[edges[eid]["pixels"][0 if end == 0 else -1]]
                    for eid, end in external
                ]
                certificate = finite_two_port_cycle_cover(
                    positions.values(),
                    adjacency,
                    port_points,
                    external,
                    source_ink_at,
                    maximum_core_pixels=maximum_core_pixels,
                    maximum_core_extent_px=maximum_core_extent_px,
                    maximum_walk_steps=maximum_walk_steps,
                )
                certificate.update(
                    {
                        "cell_node_ids": sorted(nids),
                        "internal_source_graph_edge_ids": internal,
                        "external_ports": [list(p) for p in external],
                        "all_internal_source_graph_edges_included": True,
                    }
                )
                rows.append(certificate)
            if len(nids) < maximum_core_nodes:
                choices = set().union(*(near[nid] for nid in nids)) - nids
                for other in sorted(choices, reverse=True):
                    if other > min(nids):
                        pending_sets.append(nids | {other})
    eligible = [row for row in rows if row["eligible"]]
    node_owners = {}
    for index, row in enumerate(eligible):
        for nid in row["cell_node_ids"]:
            node_owners.setdefault(nid, []).append(index)
    for index, row in enumerate(rows):
        row["cell_id"] = f"SOURCE-CYCLE-CELL-{index:05d}"
        if not row["eligible"]:
            continue
        if set(row["cell_node_ids"]) & budget_nodes:
            row.update(
                {
                    "eligible": False,
                    "reason": "LOCAL_CYCLE_CELL_ENUMERATION_BUDGET_EXCEEDED",
                    "decision": "PENDING_EXPLICIT_CORE_DECOMPOSITION",
                }
            )
        elif any(len(node_owners[nid]) > 1 for nid in row["cell_node_ids"]):
            row.update(
                {
                    "eligible": False,
                    "reason": "LOCAL_CYCLE_CELLS_HAVE_OVERLAPPING_SOURCE_OWNERSHIP",
                    "decision": "PENDING_EXPLICIT_CORE_DECOMPOSITION",
                }
            )
    return {
        "cells": rows,
        "enumerated_node_sets": states,
        "eligible_cells": sum(row["eligible"] for row in rows),
        "enumeration_budget_pending_node_ids": sorted(budget_nodes),
        "all_source_ports_preserved": True,
        "multiple_cycles_and_true_external_branches_remain_pending": True,
    }
