"""T06 whole observed paths from an unmodified native source-pixel graph.

The module has no fixture, page-coordinate, text-string, CAD writer, or OCR
dependency. Round *boundary* observations terminate paths; their meaning is
unknown. A unique four-port geometric continuation is not an assertion of an
electrical connection. All other branches remain whole-group uncertainties.
"""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import math
from pathlib import Path
import time

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from .connection_core_routes import enumerate_bounded_cycle_cells
from .contracts import save_json, stable_id


POLICY = {
    "source_threshold": 128,
    "context_px": 32,
    "thinning_max_iterations": 64,
    "junction_core_dilation_px": 1,
    "round_hole_radius_px": [8.0, 32.0],
    "round_hole_axis_ratio_max": 1.25,
    "round_hole_radial_p95_px": 1.6,
    "round_hole_radial_max_px": 3.0,
    "round_boundary_tangent_max_deviation_deg": 30.0,
    "round_boundary_minimum_owned_run_px": 12.0,
    "port_direction_span_px": 12.0,
    "crossing_pair_max_deviation_deg": 20.0,
    "crossing_pair_cost_margin_deg": 30.0,
    "crossing_axis_separation_min_deg": 30.0,
    "minimum_path_length_px": 50.0,
    "minimum_curved_deviation_px": 1.5,
    "maximum_path_length_px": 2400.0,
    "polyline_approximation_px": 0.85,
    "maximum_control_vertices": 48,
    "single_arc_radial_error_px": 0.85,
    "source_perpendicular_px": 2.0,
    "source_fraction_min": 0.98,
    "maximum_white_gap_px": 5.0,
    "dense_step_px": 0.25,
    "endpoint_cap_extent_px": 3.0,
    "proposal_selection": "ALL_COMPLETE_SOURCE_PATHS_WITHIN_TASK_RESOURCE_CONTRACT",
    "maximum_graph_steps": 10000,
    "maximum_trace_edges": 100,
    "local_cycle_maximum_core_pixels": 24,
    "local_cycle_maximum_core_extent_px": 6,
    "local_cycle_maximum_walk_steps": 64,
    "local_cycle_maximum_core_nodes": 4,
    "local_cycle_maximum_internal_edge_length_px": 12.0,
    "local_cycle_maximum_states_per_seed": 128,
    "local_cycle_unprotected_window_points": 128,
    "local_cycle_white_pixel_minimum_clearance_px": 0.5,
    "prior_fragment_normal_px": 0.75,
    "prior_fragment_angle_deg": 5.0,
    "minimum_retired_interval_px": 1.0,
}


class ConnectionResourceStop(RuntimeError):
    pass


def _checkpoint(started, budget=42.0):
    from .execution import active_resource_limits, check_cancel

    check_cancel("CONNECTION_SOURCE_GRAPH_RESOURCE_CHECK")
    limits, _ = active_resource_limits({"CPU_seconds": budget})
    budget = limits["CPU_seconds"]
    if time.process_time() - started > budget:
        raise ConnectionResourceStop("T06_DISCOVERY_CPU_BUDGET_STOP")


def _length(points):
    return float(
        np.linalg.norm(np.diff(np.asarray(points, float), axis=0), axis=1).sum()
    )


def _thinning(ink, started):
    """Zhang--Suen two-subiteration thinning; no opening/closing or pruning."""
    luts = []
    for phase in (0, 1):
        lut = np.zeros(256, np.uint8)
        for code in range(256):
            p = [(code >> index) & 1 for index in range(8)]
            b = sum(p)
            transitions = sum(not p[i] and p[(i + 1) % 8] for i in range(8))
            triples = (
                (p[0] * p[2] * p[4], p[2] * p[4] * p[6])
                if phase == 0
                else (p[0] * p[2] * p[6], p[0] * p[4] * p[6])
            )
            lut[code] = int(2 <= b <= 6 and transitions == 1 and not any(triples))
        luts.append(lut)
    kernel = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], np.float32)
    skel = ink.astype(np.uint8).copy()
    iteration_counts = []
    for iteration in range(POLICY["thinning_max_iterations"]):
        count = 0
        for lut in luts:
            codes = cv2.filter2D(
                skel, cv2.CV_16U, kernel, borderType=cv2.BORDER_CONSTANT
            )
            remove = (lut[codes] != 0) & (skel != 0)
            count += int(np.count_nonzero(remove))
            skel[remove] = 0
        iteration_counts.append(count)
        _checkpoint(started)
        if count == 0:
            return skel.astype(bool), iteration_counts
    raise ConnectionResourceStop("SOURCE_THINNING_DID_NOT_CONVERGE_WITHIN_FROZEN_LIMIT")


def _round_boundaries(ink, origin):
    contours, hierarchy = cv2.findContours(
        ink.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
    )
    observations = []
    if hierarchy is None:
        return observations
    for index, contour in enumerate(contours):
        if hierarchy[0, index, 3] < 0 or len(contour) < 28:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if not (14 <= min(w, h) <= max(w, h) <= 68):
            continue
        if max(w, h) / min(w, h) > POLICY["round_hole_axis_ratio_max"]:
            continue
        points = contour[:, 0, :].astype(float)
        centre0 = points.mean(axis=0)
        q = points - centre0
        solution, *_ = np.linalg.lstsq(
            np.column_stack((2 * q, np.ones(len(q)))), (q * q).sum(axis=1), rcond=None
        )
        centre = centre0 + solution[:2]
        radius = math.sqrt(max(0.0, solution[2] + solution[0] ** 2 + solution[1] ** 2))
        residual = np.abs(np.linalg.norm(points - centre, axis=1) - radius)
        lo, hi = POLICY["round_hole_radius_px"]
        if not lo <= radius <= hi:
            continue
        if (
            np.quantile(residual, 0.95) > POLICY["round_hole_radial_p95_px"]
            or residual.max() > POLICY["round_hole_radial_max_px"]
        ):
            continue
        area_ratio = abs(cv2.contourArea(contour)) / (math.pi * radius * radius)
        if not 0.70 <= area_ratio <= 1.2:
            continue
        observations.append(
            {
                "id": f"ROUND-{len(observations):04d}",
                "center": (centre + origin).tolist(),
                "inner_boundary_radius_px": radius,
                "contour_index": index,
                "contour_point_count": len(points),
                "radial_p95_px": float(np.quantile(residual, 0.95)),
                "radial_max_px": float(residual.max()),
                "area_ratio": area_ratio,
                "class": "OBSERVED_ROUND_INNER_BOUNDARY_SEMANTICS_UNKNOWN",
            }
        )
    return observations


def _degree(skel):
    h, w = skel.shape
    pad = np.pad(skel, 1)
    degree = np.zeros(skel.shape, np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            neighbor = pad[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w].copy()
            if dx and dy:
                # Do not add a diagonal shortcut around an existing axial edge.
                neighbor &= ~(
                    pad[1 + dy : 1 + dy + h, 1 : 1 + w]
                    | pad[1 : 1 + h, 1 + dx : 1 + dx + w]
                )
            degree += neighbor
    return degree


class _SourceGraph:
    def __init__(self, skel, origin, rounds, roi, started, *, source_ink=None,
                 aggregate_core_boxes=None):
        self.skel = skel
        self.h, self.w = skel.shape
        self.flat = skel.ravel()
        self.origin = np.asarray(origin, float)
        self.roi = list(map(int, roi))
        self.source_ink = source_ink
        self.degree = _degree(skel)
        junction = skel & (self.degree >= 3)
        core = (
            (cv2.dilate(junction.astype(np.uint8), np.ones((3, 3), np.uint8)) != 0)
            & skel
            & (self.degree > 1)
        )
        count, labels = cv2.connectedComponents(core.astype(np.uint8), connectivity=8)
        self.node_map = labels.ravel()
        self.nodes = {i: {"id": i, "pixels": [], "edges": []} for i in range(1, count)}
        for pixel in np.flatnonzero(core):
            self.nodes[int(self.node_map[pixel])]["pixels"].append(int(pixel))
        for pixel in np.flatnonzero(skel & (self.degree <= 1) & ~core):
            self.node_map[pixel] = count
            self.nodes[count] = {"id": count, "pixels": [int(pixel)], "edges": []}
            count += 1
        self.edges = []
        visited_ports = set()
        for node_id in sorted(self.nodes):
            for pixel in self.nodes[node_id]["pixels"]:
                for neighbor in self.neighbors(pixel):
                    if (
                        self.node_map[neighbor] == node_id
                        or (pixel, neighbor) in visited_ports
                    ):
                        continue
                    path = [pixel, neighbor]
                    previous, current = pixel, neighbor
                    while not self.node_map[current]:
                        choices = [p for p in self.neighbors(current) if p != previous]
                        if len(choices) != 1:
                            raise ValueError(
                                "NONNODE_SOURCE_GRAPH_PIXEL_HAS_NONCHAIN_DEGREE"
                            )
                        previous, current = current, choices[0]
                        path.append(current)
                        if len(path) > POLICY["maximum_graph_steps"]:
                            raise ConnectionResourceStop(
                                "SOURCE_GRAPH_EDGE_EXCEEDS_FROZEN_LIMIT"
                            )
                    end = int(self.node_map[current])
                    visited_ports.add((path[0], path[1]))
                    visited_ports.add((path[-1], path[-2]))
                    eid = len(self.edges)
                    edge = {
                        "id": eid,
                        "nodes": [node_id, end],
                        "pixels": path,
                        "length": _length(self.xy(path)),
                    }
                    self.edges.append(edge)
                    self.nodes[node_id]["edges"].append((eid, 0))
                    self.nodes[end]["edges"].append((eid, 1))
            if node_id % 300 == 0:
                _checkpoint(started)
        self.bounded_aggregate_cores = []
        if aggregate_core_boxes:
            from .text_graph_support import aggregate_close_crossing_cores

            self.bounded_aggregate_cores = aggregate_close_crossing_cores(
                self, aggregate_core_boxes
            )
        for node in self.nodes.values():
            points = self.xy(node["pixels"])
            centre = points.mean(axis=0)
            node["center"] = centre.tolist()
            node["terminal"] = None
            node["pairing"] = {}
            node["finite_path_decompositions"] = []
            pixel_set = set(node["pixels"])
            internal_edges = (
                sum(sum(q in pixel_set for q in self.neighbors(p)) for p in pixel_set)
                // 2
            )
            unseen = set(pixel_set)
            core_components = 0
            while unseen:
                core_components += 1
                pending = [unseen.pop()]
                while pending:
                    p = pending.pop()
                    for q in self.neighbors(p):
                        if q in unseen:
                            unseen.remove(q)
                            pending.append(q)
            node["core_topology"] = {
                "pixels": len(pixel_set),
                "edges": internal_edges,
                "components": core_components,
                "cycle_rank": internal_edges - len(pixel_set) + core_components,
            }
            node["internal_source_endpoint_count"] = sum(
                self.degree.ravel()[p] == 1 for p in node["pixels"]
            )
            if (
                points[:, 0].min() <= roi[0] + 2
                or points[:, 0].max() >= roi[2] - 2
                or points[:, 1].min() <= roi[1] + 2
                or points[:, 1].max() >= roi[3] - 2
            ):
                node["reason"] = "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT"
                continue
            matching = []
            for ring in rounds:
                radial = np.linalg.norm(points - np.asarray(ring["center"]), axis=1)
                residual = float(
                    np.min(np.abs(radial - (ring["inner_boundary_radius_px"] + 1.0)))
                )
                if residual <= 3.0:
                    matching.append((residual, ring["id"]))
            if matching:
                matching.sort()
                node["terminal"] = {
                    "kind": "OBSERVED_ROUND_BOUNDARY_CONTACT",
                    "round_id": matching[0][1],
                    "radial_contact_residual_px": matching[0][0],
                }
            elif (
                len(node["edges"]) == 1 and node["internal_source_endpoint_count"] == 1
            ):
                node["terminal"] = {"kind": "OBSERVED_FREE_SOURCE_ENDPOINT"}
            elif self._terminal_lobe(node):
                pass
            elif node["internal_source_endpoint_count"]:
                node["reason"] = "JUNCTION_CORE_CONTAINS_SOURCE_SHORT_BRANCH_ENDPOINT"
            elif node["core_topology"]["cycle_rank"]:
                node["reason"] = "INTERNAL_SOURCE_CYCLE_REQUIRES_EXPLICIT_DECOMPOSITION"
                node["finite_path_decompositions"] = self._unresolved_pairings(node)
            elif len(node["edges"]) == 2:
                # A contracted junction core can have only two external ports.
                # Its internal pixels are retained, so continuation is unique
                # even when the raster has a tiny side contact inside the core.
                a, b = node["edges"]
                if a[0] == b[0]:
                    node["reason"] = "CLOSED_SOURCE_LOOP_REQUIRES_SEPARATE_OBJECT"
                    continue
                node["pairing"] = {a: b, b: a}
                node["crossing_evidence"] = {
                    "port_count": 2,
                    "selected_pairs": [[0, 1]],
                    "core_source_pixels": len(node["pixels"]),
                    "semantic_connection": "UNIQUE_GEOMETRIC_CONTINUATION_ONLY",
                    "short_branches_deleted": False,
                }
                node["finite_path_decompositions"] = [
                    {"pairs": [[0, 1]], "decision": "UNIQUE_TWO_PORT_CORE"}
                ]
            elif len(node["edges"]) == 4:
                self._pair_crossing(node)
            else:
                node["reason"] = "NONUNIQUE_SOURCE_BRANCH_OR_NONFOURWAY_JUNCTION"
                node["finite_path_decompositions"] = self._unresolved_pairings(node)
        self._assign_bounded_cycle_cells()
        _checkpoint(started)

    def _assign_bounded_cycle_cells(self):
        def source_ink_at(x, y):
            x -= int(self.origin[0])
            y -= int(self.origin[1])
            return 0 <= x < self.w and 0 <= y < self.h and bool(self.source_ink[y, x])

        self.cycle_cell_discovery = enumerate_bounded_cycle_cells(
            self.nodes,
            self.edges,
            self.neighbors,
            self.xy,
            source_ink_at if self.source_ink is not None else None,
            maximum_core_nodes=POLICY["local_cycle_maximum_core_nodes"],
            maximum_internal_edge_length_px=POLICY[
                "local_cycle_maximum_internal_edge_length_px"
            ],
            maximum_states_per_seed=POLICY["local_cycle_maximum_states_per_seed"],
            maximum_core_pixels=POLICY["local_cycle_maximum_core_pixels"],
            maximum_core_extent_px=POLICY["local_cycle_maximum_core_extent_px"],
            maximum_walk_steps=POLICY["local_cycle_maximum_walk_steps"],
        )
        self.cycle_cells_by_port = {}
        for cover in self.cycle_cell_discovery["cells"]:
            if not cover["eligible"]:
                continue
            for nid in cover["cell_node_ids"]:
                self.nodes[nid]["local_cycle_cover"] = cover
            for port in cover["external_ports"]:
                self.cycle_cells_by_port[tuple(port)] = cover

    def _cycle_cover_route(self, cover, start, end):
        selected = next(
            row
            for row in cover["finite_cover_walks"]
            if row["id"] == cover["selected_encoding_id"]
        )
        route = [
            (int(y) - int(self.origin[1])) * self.w + int(x) - int(self.origin[0])
            for x, y in selected["source_walk_points"]
        ]
        if (route[0], route[-1]) == (end, start):
            route.reverse()
        if (route[0], route[-1]) != (start, end):
            raise ValueError("LOCAL_CYCLE_COVER_PORTS_DO_NOT_MATCH_TRACE")
        return route

    def _terminal_lobe(self, node):
        """Recognize a small observed terminal cycle without deleting its hole.

        It has exactly one external port and one self-loop. The complete loop
        remains part of the same editable open path, including its revisit to
        the contact point. No source pixel or graph edge is removed.
        """
        # A separate loop edge does not explain an additional cycle hidden
        # inside its contracted core. The latter must remain pending rather
        # than being replaced by a shortest core route.
        if node["core_topology"]["cycle_rank"]:
            return False
        ports = node["edges"]
        if len(ports) != 3:
            return False
        loops = [
            e
            for e in {p[0] for p in ports}
            if self.edges[e]["nodes"] == [node["id"], node["id"]]
        ]
        if len(loops) != 1:
            return False
        loop = self.edges[loops[0]]
        points = self.xy(loop["pixels"])
        extent = np.ptp(points, axis=0)
        if (
            float(extent.max()) > 2 * POLICY["endpoint_cap_extent_px"]
            or loop["length"] > 4 * POLICY["endpoint_cap_extent_px"]
        ):
            return False
        cycle = (
            loop["pixels"]
            + self.core_route(node["id"], loop["pixels"][-1], loop["pixels"][0])[1:]
        )
        # Start the closed walk where its unique external stroke actually
        # joins it. An arbitrary loop-edge origin can walk the closing edge
        # again while travelling to the external port, creating an avoidable
        # duplicate CAD segment. Rotation preserves every source cycle edge.
        external = next(port for port in ports if port[0] != loop["id"])
        external_pixel = self.oriented(external)[0]
        ring = cycle[:-1]
        entry = min(range(len(ring)), key=lambda index: (
            len(self.core_route(node["id"], ring[index], external_pixel))
            if self.node_map[ring[index]] == node["id"] else float("inf"),
            ring[index],
        ))
        ring = ring[entry:] + ring[:entry]
        cycle = ring + ring[:1]
        node["terminal"] = {
            "kind": "OBSERVED_CLOSED_TERMINAL_LOBE",
            "loop_edge_id": loop["id"],
            "loop_length_px": loop["length"],
            "loop_bbox_xyxy_px": [
                *points.min(axis=0).tolist(),
                *points.max(axis=0).tolist(),
            ],
            "loop_pixels": cycle,
            "source_hole_retained": True,
            "external_port_count": 1,
            "cycle_anchor_chosen_from_actual_external_port": True,
        }
        return True

    def _unresolved_pairings(self, node):
        """Bounded hypotheses retain every port, including unmatched branches."""
        ports = node["edges"]
        if len(ports) > 6:
            return [
                {
                    "decision": "TOO_MANY_PORTS_FOR_BOUNDED_DECOMPOSITION",
                    "all_ports": [list(p) for p in ports],
                }
            ]

        def matchings(indices):
            if not indices:
                yield []
                return
            a = indices[0]
            for i in range(1, len(indices)):
                b = indices[i]
                for rest in matchings(indices[1:i] + indices[i + 1 :]):
                    yield [[a, b], *rest]

        proposals = []
        unpaired = range(len(ports)) if len(ports) % 2 else [None]
        for singleton in unpaired:
            indices = [i for i in range(len(ports)) if i != singleton]
            for pairs in matchings(indices):
                proposals.append(
                    {
                        "pairs": pairs,
                        "unmatched_ports": [] if singleton is None else [singleton],
                        "all_ports_retained": True,
                        "decision": "PENDING_DIRECTION_CURVATURE_ENDPOINT_AND_CONTEXT",
                    }
                )
        return proposals

    def xy(self, pixels):
        p = np.asarray(pixels, np.int64)
        return np.column_stack((p % self.w, p // self.w)).astype(float) + self.origin

    def neighbors(self, pixel):
        y, x = divmod(int(pixel), self.w)
        result = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == dy == 0 or not (0 <= x + dx < self.w and 0 <= y + dy < self.h):
                    continue
                q = pixel + dy * self.w + dx
                if not self.flat[q]:
                    continue
                if (
                    dx
                    and dy
                    and (self.flat[pixel + dy * self.w] or self.flat[pixel + dx])
                ):
                    continue
                result.append(int(q))
        return result

    def oriented(self, port):
        eid, end = port
        points = self.edges[eid]["pixels"]
        return points if end == 0 else points[::-1]

    def _pair_crossing(self, node):
        ports = node["edges"]
        pairings = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
        node["finite_path_decompositions"] = [
            {
                "pairs": [list(p) for p in pairs],
                "all_ports_retained": True,
                "decision": "AWAITING_SOURCE_DIRECTION_EVIDENCE",
            }
            for pairs in pairings
        ]
        directions = []
        for port in ports:
            points = self.xy(self.oriented(port))
            span = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
            index = int(
                np.searchsorted(span, min(POLICY["port_direction_span_px"], span[-1]))
            )
            if span[index] < 6.0:
                node["reason"] = "PORT_TOO_SHORT_TO_DISTINGUISH_CROSSING"
                return
            direction = points[index] - points[0]
            directions.append(direction / np.linalg.norm(direction))
        scored = []
        for pairs in pairings:
            deviations = [
                math.degrees(
                    math.acos(float(np.clip(-directions[a] @ directions[b], -1, 1)))
                )
                for a, b in pairs
            ]
            scored.append((sum(deviations), max(deviations), pairs, deviations))
        scored.sort(key=lambda item: item[:2])
        node["finite_path_decompositions"] = [
            {
                "pairs": [list(p) for p in item[2]],
                "sum_deviation_deg": item[0],
                "maximum_deviation_deg": item[1],
                "all_ports_retained": True,
            }
            for item in scored
        ]
        best = scored[0]
        axis_sep = math.degrees(
            math.acos(
                float(
                    np.clip(
                        abs(directions[best[2][0][0]] @ directions[best[2][1][0]]),
                        -1,
                        1,
                    )
                )
            )
        )
        evidence = {
            "port_count": 4,
            "direction_vectors": [v.tolist() for v in directions],
            "selected_pairs": [list(pair) for pair in best[2]],
            "pair_deviations_deg": best[3],
            "second_best_cost_margin_deg": scored[1][0] - best[0],
            "axis_separation_deg": axis_sep,
            "semantic_connection": "UNKNOWN_NOT_INFERRED",
            "separate_crossing_owners_retained": True,
        }
        node["crossing_evidence"] = evidence
        if node.get("bounded_aggregate_source_core"):
            evidence["bounded_aggregate_source_core"] = node["bounded_aggregate_source_core"]
        if (
            best[1] > POLICY["crossing_pair_max_deviation_deg"]
            or scored[1][0] - best[0] < POLICY["crossing_pair_cost_margin_deg"]
            or axis_sep < POLICY["crossing_axis_separation_min_deg"]
        ):
            node["reason"] = "AMBIGUOUS_CROSSING_CONTINUATION"
            return
        for a, b in best[2]:
            node["pairing"][ports[a]] = ports[b]
            node["pairing"][ports[b]] = ports[a]

    def core_route(self, node_id, start, end):
        pending = deque([start])
        parent = {start: None}
        while pending:
            current = pending.popleft()
            if current == end:
                route = []
                while current is not None:
                    route.append(current)
                    current = parent[current]
                return route[::-1]
            for other in self.neighbors(current):
                if self.node_map[other] == node_id and other not in parent:
                    parent[other] = current
                    pending.append(other)
        raise ValueError("JUNCTION_CORE_SOURCE_ROUTE_NOT_CONNECTED")

    def trace(self, start_id, first_port):
        path = []
        edge_ids = []
        crossings = []
        node_id = start_id
        port = first_port
        terminal = self.nodes[start_id]["terminal"] or {}
        if terminal.get("kind") == "OBSERVED_CLOSED_TERMINAL_LOBE":
            loop = terminal["loop_edge_id"]
            if first_port[0] == loop:
                return (
                    [],
                    [],
                    [],
                    start_id,
                    "TERMINAL_LOBE_IS_OWNED_WITH_ITS_WHOLE_PATH",
                )
            path.extend(terminal["loop_pixels"])
            edge_ids.append(loop)
        for _ in range(POLICY["maximum_trace_edges"]):
            if len(edge_ids) >= POLICY["maximum_trace_edges"]:
                return (
                    path,
                    edge_ids,
                    crossings,
                    node_id,
                    "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT",
                )
            eid, end = port
            if eid in edge_ids:
                return path, edge_ids, crossings, node_id, "SOURCE_ROUTE_CYCLE"
            edge_ids.append(eid)
            points = self.oriented(port)
            if path:
                # A covered local cell has already appended its entire walk;
                # its exit is exactly this port.  BFS only joins ordinary
                # acyclic cores, never selects one side of a certified cycle.
                core = (
                    [path[-1]]
                    if path[-1] == points[0]
                    else self.core_route(node_id, path[-1], points[0])
                )
                path.extend(core[1:])
                path.extend(points[1:])
            else:
                path.extend(points)
            node_id = self.edges[eid]["nodes"][1 - end]
            node = self.nodes[node_id]
            if node["terminal"]:
                terminal = node["terminal"]
                if terminal.get("kind") == "OBSERVED_CLOSED_TERMINAL_LOBE":
                    loop = terminal["loop_edge_id"]
                    loop_pixels = terminal["loop_pixels"]
                    path.extend(self.core_route(node_id, path[-1], loop_pixels[0])[1:])
                    path.extend(loop_pixels[1:])
                    edge_ids.append(loop)
                if any(row.get("local_cycle_cover_evidence") for row in crossings):
                    start_terminal = self.nodes[start_id]["terminal"] or {}
                    if (
                        start_terminal.get("kind") != "OBSERVED_ROUND_BOUNDARY_CONTACT"
                        or terminal.get("kind") != "OBSERVED_ROUND_BOUNDARY_CONTACT"
                        or start_terminal["round_id"] == terminal.get("round_id")
                    ):
                        return (
                            path,
                            edge_ids,
                            crossings,
                            node_id,
                            "LOCAL_CYCLE_COVER_REQUIRES_DISTINCT_ROUND_TERMINALS",
                        )
                return path, edge_ids, crossings, node_id, None
            incoming = (eid, 1 - end)
            cover = self.cycle_cells_by_port.get(incoming)
            if cover:
                if (self.nodes[start_id]["terminal"] or {}).get(
                    "kind"
                ) != "OBSERVED_ROUND_BOUNDARY_CONTACT":
                    return (
                        path,
                        edge_ids,
                        crossings,
                        node_id,
                        "LOCAL_CYCLE_COVER_REQUIRES_DISTINCT_ROUND_TERMINALS",
                    )
                internal = cover["internal_source_graph_edge_ids"]
                if set(internal) & set(edge_ids):
                    return path, edge_ids, crossings, node_id, "SOURCE_ROUTE_CYCLE"
                if len(edge_ids) + len(internal) >= POLICY["maximum_trace_edges"]:
                    return (
                        path,
                        edge_ids,
                        crossings,
                        node_id,
                        "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT",
                    )
                outgoing = next(
                    tuple(p) for p in cover["external_ports"] if tuple(p) != incoming
                )
                route = self._cycle_cover_route(
                    cover, path[-1], self.oriented(outgoing)[0]
                )
                interval = [len(path) - 1, len(path) + len(route) - 1]
                path.extend(route[1:])
                edge_ids.extend(internal)
                crossings.append(
                    {
                        "node_id": node_id,
                        "center": node["center"],
                        "incoming_edge": eid,
                        "outgoing_edge": outgoing[0],
                        "other_owner_edge_ids": [],
                        "port_count": 2,
                        "semantic_connection": "UNKNOWN_NOT_INFERRED",
                        "local_cycle_cover_evidence": cover,
                        "protected_source_path_interval": interval,
                        "same_owner_local_retrace_not_electrical_inference": True,
                    }
                )
                node_id = self.edges[outgoing[0]]["nodes"][outgoing[1]]
                port = outgoing
                continue
            if incoming not in node["pairing"]:
                return (
                    path,
                    edge_ids,
                    crossings,
                    node_id,
                    node.get("reason", "UNRESOLVED_CORE"),
                )
            outgoing = node["pairing"][incoming]
            crossings.append(
                {
                    "node_id": node_id,
                    "center": node["center"],
                    "incoming_edge": eid,
                    "outgoing_edge": outgoing[0],
                    "other_owner_edge_ids": [
                        p[0] for p in node["edges"] if p not in (incoming, outgoing)
                    ],
                    **node["crossing_evidence"],
                }
            )
            port = outgoing
        return path, edge_ids, crossings, node_id, "SOURCE_ROUTE_EXCEEDS_EDGE_LIMIT"


def _dense_geometry(geometry, step=0.25):
    points = np.asarray(geometry["points"], float)
    bulges = geometry["bulges"]
    result = []
    for a, b, bulge in zip(points[:-1], points[1:], bulges):
        chord = float(np.linalg.norm(b - a))
        if abs(bulge) < 1e-12:
            q = np.linspace(a, b, max(2, int(math.ceil(chord / step)) + 1))
        else:
            theta = 4 * math.atan(bulge)
            u = (b - a) / chord
            n = np.array([-u[1], u[0]])
            centre = (a + b) / 2 + n * chord * (1 - bulge * bulge) / (4 * bulge)
            radius = float(np.linalg.norm(a - centre))
            start = math.atan2(*(a - centre)[::-1])
            angle = start + np.linspace(
                0.0, theta, max(3, int(math.ceil(abs(theta) * radius / step)) + 1)
            )
            q = centre + radius * np.column_stack((np.cos(angle), np.sin(angle)))
        result.extend(q[:-1].tolist())
    result.append(points[-1].tolist())
    return np.asarray(result)


def _bounded_source_polyline(points):
    """Minimize vertices within a bounded, source-ordered straight-span graph.

    Each candidate segment uses the existing finite-segment error bound.
    Source projections must progress monotonically along that segment, so a
    narrow out-and-back stroke cannot disappear into its common short chord.
    Protected core walks are never passed to this function.
    """
    points = np.asarray(points, float)
    count = len(points)
    window = POLICY["local_cycle_unprotected_window_points"]
    tolerance = POLICY["polyline_approximation_px"]
    costs = np.full(count, count + 1, np.int64)
    previous = np.full(count, -1, np.int64)
    costs[0] = 0
    examined = 0
    for start in range(count - 1):
        delta = points[start + 1 : start + window] - points[start]
        size = len(delta)
        squared_lengths = np.sum(delta * delta, axis=1)
        dot = delta @ delta.T
        fraction = np.clip(dot / np.maximum(squared_lengths[None, :], 1e-12), 0, 1)
        distance2 = (
            squared_lengths[:, None]
            - 2 * fraction * dot
            + fraction * fraction * squared_lengths[None, :]
        )
        progression = dot - np.vstack((np.zeros((1, size)), dot[:-1]))
        outside_span = np.tril_indices(size, -1)
        distance2[outside_span] = 0
        progression[outside_span] = 0
        valid = (
            (distance2.max(axis=0) <= tolerance * tolerance + 1e-9)
            & (progression.min(axis=0) >= -1e-9)
            & (squared_lengths > 1e-12)
        )
        endpoints = np.arange(start + 1, start + size + 1)
        improve = valid & (costs[endpoints] > costs[start] + 1)
        costs[endpoints[improve]] = costs[start] + 1
        previous[endpoints[improve]] = start
        examined += size
    if count > 1 and previous[-1] < 0:
        # Repeated/degenerate samples are retained, never replaced by a new
        # segment whose direction cannot be defined.
        indices = list(range(count))
        mode = "DEGENERATE_SOURCE_SAMPLES_RETAINED"
    else:
        indices = [count - 1]
        while indices[-1] > 0:
            indices.append(int(previous[indices[-1]]))
        indices.reverse()
        mode = "MINIMUM_VERTICES_WITHIN_BOUNDED_MONOTONE_SOURCE_WINDOW"
    return points[indices], {
        "method": mode,
        "source_point_count": count,
        "selected_source_point_indices": indices,
        "maximum_window_source_points": window,
        "candidate_segments_examined": examined,
        "maximum_finite_segment_source_distance_px": tolerance,
        "source_index_order_preserved": True,
        "source_projection_order_monotone": mode
        != "DEGENERATE_SOURCE_SAMPLES_RETAINED",
        "source_tolerances_unchanged": True,
    }


def _local_cycle_white_space_checks(geometry, crossings):
    white = sorted(
        {
            tuple(p)
            for crossing in crossings
            if crossing.get("local_cycle_cover_evidence")
            for p in crossing["local_cycle_cover_evidence"][
                "original_source_hole_evidence"
            ]["enclosed_white_hole_points"]
        }
    )
    if not white:
        return None
    if any(abs(bulge) > 1e-12 for bulge in geometry["bulges"]):
        raise ValueError("PROTECTED_CYCLE_WALK_REQUIRES_EXPLICIT_FINITE_LINE_SEGMENTS")
    points = np.asarray(geometry["points"], float)
    starts = points[:-1]
    delta = points[1:] - starts
    length2 = np.sum(delta * delta, axis=1)
    rows = []
    for point in white:
        offset = np.asarray(point, float) - starts
        fraction = np.clip(
            np.sum(offset * delta, axis=1) / np.maximum(length2, 1e-12), 0, 1
        )
        distance = float(
            np.linalg.norm(offset - fraction[:, None] * delta, axis=1).min()
        )
        rows.append(
            {
                "original_white_point": list(point),
                "minimum_native_segment_distance_px": distance,
            }
        )
    threshold = POLICY["local_cycle_white_pixel_minimum_clearance_px"]
    return {
        "method": "EXACT_DISTANCE_TO_ALL_NATIVE_FINITE_LINE_SEGMENTS",
        "original_white_pixels": rows,
        "required_clearance_px": threshold,
        "diagonal_raster_contacts_not_relabelled_as_electrical_connectivity": True,
        "pass": all(
            row["minimum_native_segment_distance_px"] >= threshold for row in rows
        ),
    }


def _representation(
    raw, *, protected_prefix=0, protected_suffix=0, protected_intervals=()
):
    points = np.asarray(raw, float)
    a, b = points[0], points[-1]
    chord = b - a
    length = np.linalg.norm(chord)
    normal = np.array([-chord[1], chord[0]]) / max(length, 1e-12)
    deviation = (points - a) @ normal
    mid = points[int(np.argmax(np.abs(deviation)))]
    if (
        not (protected_prefix or protected_suffix or protected_intervals)
        and abs(deviation).max() >= POLICY["minimum_curved_deviation_px"]
    ):
        matrix = 2 * np.array([mid - a, b - a])
        if abs(np.linalg.det(matrix)) > 1e-8:
            centre = np.linalg.solve(
                matrix, np.array([mid @ mid - a @ a, b @ b - a @ a])
            )
            radius = np.linalg.norm(a - centre)
            residual = np.abs(np.linalg.norm(points - centre, axis=1) - radius)
            angles = np.unwrap(
                np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
            )
            sweep = float(angles[-1] - angles[0])
            if (
                0.01 < abs(sweep) < math.radians(170)
                and residual.max() <= POLICY["single_arc_radial_error_px"]
                and np.all(np.diff(angles) * math.copysign(1, sweep) >= -0.02)
            ):
                return {
                    "points": [a.tolist(), b.tolist()],
                    "bulges": [math.tan(sweep / 4), 0.0],
                    "closed": False,
                }, {
                    "representation": "ONE_NATIVE_BULGED_ARC_SEGMENT",
                    "raw_radial_error_max_px": float(residual.max()),
                }
    unprotected_span_encodings = []
    if protected_intervals:
        anchors = {0, len(points) - 1}
        anchors.update(range(protected_prefix))
        anchors.update(range(len(points) - protected_suffix, len(points)))
        for lo, hi in protected_intervals:
            if not 0 <= lo < hi <= len(points):
                raise ValueError("PROTECTED_SOURCE_CORE_INTERVAL_OUTSIDE_PATH")
            anchors.update(range(lo, hi))
        ordered = sorted(anchors)
        parts = []
        for lo, hi in zip(ordered, ordered[1:]):
            if hi - lo > 1:
                part, encoding = _bounded_source_polyline(points[lo : hi + 1])
                encoding["source_path_interval"] = [lo, hi + 1]
                unprotected_span_encodings.append(encoding)
            else:
                part = points[lo : hi + 1]
            parts.extend(part if not parts else part[1:])
        simplified = np.asarray(parts, float)
    else:
        lo = max(0, protected_prefix - 1)
        hi = len(points) - max(0, protected_suffix - 1)
        simplified = cv2.approxPolyDP(
            points[lo:hi].astype(np.float32).reshape(-1, 1, 2),
            POLICY["polyline_approximation_px"],
            False,
        )[:, 0, :].astype(float)
        simplified = np.concatenate((points[:lo], simplified, points[hi:]))
    simplified[0] = points[0]
    simplified[-1] = points[-1]
    return {
        "points": simplified.tolist(),
        "bulges": [0.0] * len(simplified),
        "closed": False,
    }, {
        "representation": "ONE_NATIVE_OPEN_POLYLINE",
        "maximum_source_chain_simplification_px": POLICY["polyline_approximation_px"],
        "terminal_cycle_control_points_retained": protected_prefix + protected_suffix,
        "internal_cycle_control_points_retained": sum(
            hi - lo for lo, hi in protected_intervals
        ),
        "protected_source_path_intervals": [list(v) for v in protected_intervals],
        "local_retrace_is_same_owner_only": bool(protected_intervals),
        "unprotected_source_span_encodings": unprotected_span_encodings,
    }


def _support(points, distance, origin):
    ds = map_coordinates(
        distance,
        [points[:, 1] - origin[1], points[:, 0] - origin[0]],
        order=1,
        mode="constant",
        cval=999.0,
    )
    unsupported = ds > POLICY["source_perpendicular_px"]
    changes = np.diff(np.r_[False, unsupported, False].astype(np.int8))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    gap = float(max(ends - starts, default=0) * POLICY["dense_step_px"])
    fraction = float(np.mean(~unsupported))
    return {
        "samples": len(points),
        "max_distance_px": float(ds.max()),
        "source_fraction": fraction,
        "maximum_white_gap_px": gap,
        "source_tolerances_unchanged": True,
        "pass": bool(
            fraction >= POLICY["source_fraction_min"]
            and gap <= POLICY["maximum_white_gap_px"]
        ),
    }


def _simple_source_chain_certificate(graph, pixels, label, labels, expected_count):
    """Certify a complete natural-end source chain without a curvature proxy.

    An eight-neighbor raster path has orientation-dependent length even when
    its visible centreline is straight.  Length divided by endpoint distance
    therefore cannot establish whether a source stroke is complete.  Inspect
    the unchanged graph instead: every component pixel and adjacency must be
    owned, with exactly two degree-one ends and degree-two interior pixels.
    """
    ordered = list(map(int, pixels))
    owned = set(ordered)
    source_edges = {
        tuple(sorted((p, q))) for p in owned for q in graph.neighbors(p)
    }
    path_edges = {tuple(sorted(pair)) for pair in zip(ordered, ordered[1:])}
    degrees = {p: len(graph.neighbors(p)) for p in owned}
    endpoints = {p for p, degree in degrees.items() if degree == 1}
    checks = {
        "all_samples_from_same_source_component": bool(ordered)
        and all(int(labels.ravel()[p]) == label for p in owned),
        "all_component_skeleton_pixels_accounted": len(owned) == expected_count,
        "source_path_has_no_repeated_pixels": len(owned) == len(ordered),
        "every_source_adjacency_accounted": source_edges == path_edges,
        "exactly_two_natural_source_endpoints": len(ordered) >= 2
        and endpoints == {ordered[0], ordered[-1]}
        and len(endpoints) == 2,
        "all_internal_source_degrees_are_two": all(
            degree == 2 for p, degree in degrees.items() if p not in endpoints
        ),
    }
    return {
        "schema": "complete-natural-end-source-chain-v1",
        "checks": checks,
        "pass": all(checks.values()),
        "source_skeleton_pixels": int(expected_count),
        "owned_source_pixels": len(owned),
        "source_graph_edge_count": len(source_edges),
        "source_short_branches_deleted": False,
        "source_holes_or_gaps_modified": False,
        "engineering_semantics_required": False,
        "raster_length_to_chord_used_as_completeness_gate": False,
    }


def _maximum_point_to_polyline_distance(points, chain):
    """Exact point-to-finite-segment distances, with bounded working memory."""
    points, chain = np.asarray(points, float), np.asarray(chain, float)
    starts, delta = chain[:-1], np.diff(chain, axis=0)
    size2 = np.sum(delta * delta, axis=1)
    maximum = 0.0
    for offset in range(0, len(points), 64):
        vectors = points[offset : offset + 64, None, :] - starts[None, :, :]
        fraction = np.clip(
            np.sum(vectors * delta[None, :, :], axis=2)
            / np.maximum(size2[None, :], 1e-12),
            0,
            1,
        )
        distances = np.linalg.norm(
            vectors - fraction[:, :, None] * delta[None, :, :], axis=2
        )
        maximum = max(maximum, float(distances.min(axis=1).max()))
    return maximum


def _mixed_observed_endpoint_chain_certificate(graph, pixels, source_label, labels):
    """Own one complete chain from a witnessed boundary to a natural end.

    The rest of the connected component may contain the round boundary and
    other strokes. They are not owned by this path. Only the round-contact
    endpoint may have source adjacencies outside this unique chain; any real
    interior branch or cycle keeps the path pending rather than being pruned.
    """
    ordered = list(map(int, pixels))
    owned = set(ordered)
    ends = [ordered[0], ordered[-1]]
    internal = owned - set(ends)
    internal_edges = {
        tuple(sorted((p, q)))
        for p in owned
        for q in graph.neighbors(p)
        if q in owned
    }
    outside = {
        p: [q for q in graph.neighbors(p) if q not in owned]
        for p in owned
        if any(q not in owned for q in graph.neighbors(p))
    }
    checks = {
        "single_unchanged_source_component": all(
            int(labels.ravel()[p]) == source_label for p in owned
        ),
        "unique_ordered_source_samples": len(owned) == len(ordered),
        "all_internal_source_degrees_are_two": all(
            len(graph.neighbors(p)) == 2 for p in internal
        ),
        "all_owned_source_adjacencies_accounted": internal_edges
        == {tuple(sorted(pair)) for pair in zip(ordered, ordered[1:])},
        "one_natural_degree_one_endpoint": sum(
            len(graph.neighbors(p)) == 1 for p in ends
        )
        == 1,
        "no_unowned_interior_branches": not (set(outside) & internal),
        "unowned_source_only_at_contact_endpoint": len(outside) <= 1
        and all(p in ends for p in outside),
    }
    return {
        "schema": "complete-mixed-observed-endpoint-chain-v1",
        "checks": checks,
        "pass": all(checks.values()),
        "owned_source_pixel_count": len(owned),
        "unowned_contact_adjacencies_retained": [
            {"contact_source_point": graph.xy([p])[0].tolist(),
             "neighbor_source_points": graph.xy(qs).tolist()}
            for p, qs in sorted(outside.items())
        ],
        "round_boundary_geometry_owned": False,
        "whole_connected_component_ownership_claimed": False,
        "source_pixels_removed_or_gaps_closed": False,
        "engineering_semantics_required": False,
    }


def _simple_chain_fit_certificate(raw, geometry):
    """Check source order and both directions of the actual native fit.

    Native-to-source coverage is sampled at the existing 0.25 px source gate
    step. Source-to-native distance is exact for the single arc or finite line
    spans used here. No supporting pixels are erased to improve either score.
    """
    raw = np.asarray(raw, float)
    vertices = np.asarray(geometry["points"], float)
    tolerance = POLICY["polyline_approximation_px"]
    endpoint_match = np.allclose(vertices[[0, -1]], raw[[0, -1]], atol=1e-9, rtol=0)
    bulges = geometry["bulges"]
    source_order = False
    source_distance = float("inf")
    if len(vertices) == 2 and abs(bulges[0]) > 1e-12:
        a, b = vertices
        bulge = float(bulges[0])
        chord = float(np.linalg.norm(b - a))
        unit = (b - a) / chord
        normal = np.array([-unit[1], unit[0]])
        centre = (a + b) / 2 + normal * chord * (1 - bulge * bulge) / (4 * bulge)
        radius = float(np.linalg.norm(a - centre))
        angles = np.unwrap(np.arctan2(raw[:, 1] - centre[1], raw[:, 0] - centre[0]))
        directed = (angles - angles[0]) * math.copysign(1, bulge)
        sweep = abs(4 * math.atan(bulge))
        source_order = bool(
            np.all(np.diff(directed) >= -1e-9)
            and directed.min() >= -1e-9
            and directed.max() <= sweep + 1e-9
        )
        radial = np.abs(np.linalg.norm(raw - centre, axis=1) - radius)
        end_distances = np.minimum(
            np.linalg.norm(raw - a, axis=1), np.linalg.norm(raw - b, axis=1)
        )
        within_sweep = (directed >= 0) & (directed <= sweep)
        source_distance = float(np.where(within_sweep, radial, end_distances).max())
    elif all(abs(value) <= 1e-12 for value in bulges):
        indices = []
        for vertex in vertices:
            matches = np.flatnonzero(np.all(np.abs(raw - vertex) <= 1e-9, axis=1))
            if len(matches) != 1:
                break
            indices.append(int(matches[0]))
        source_order = (
            len(indices) == len(vertices)
            and indices[0] == 0
            and indices[-1] == len(raw) - 1
            and all(a < b for a, b in zip(indices, indices[1:]))
        )
        if source_order:
            source_distance = 0.0
            for lo, hi in zip(indices, indices[1:]):
                a, b = raw[lo], raw[hi]
                delta = b - a
                projection = (raw[lo : hi + 1] - a) @ delta
                source_order = source_order and bool(np.all(np.diff(projection) >= -1e-9))
                source_distance = max(
                    source_distance,
                    _maximum_point_to_polyline_distance(raw[lo : hi + 1], [a, b]),
                )
    dense = _dense_geometry(geometry, POLICY["dense_step_px"])
    native_distance = _maximum_point_to_polyline_distance(dense, raw)
    checks = {
        "natural_source_endpoints_preserved": bool(endpoint_match),
        "source_traversal_order_preserved": bool(source_order),
        "source_to_native_within_existing_fit_tolerance": source_distance <= tolerance + 1e-9,
        "native_to_source_within_existing_fit_tolerance": native_distance <= tolerance + 1e-9,
    }
    return {
        "schema": "ordered-two-way-simple-chain-fit-v1",
        "checks": checks,
        "pass": all(checks.values()),
        "maximum_fit_error_px": tolerance,
        "source_to_native_maximum_distance_px": source_distance if math.isfinite(source_distance) else None,
        "native_to_source_maximum_distance_px": native_distance,
        "native_sampling_step_px": POLICY["dense_step_px"],
        "source_tolerances_unchanged": True,
    }


def _text_boxes(prior_objects):
    boxes = []
    for obj in prior_objects:
        kind = obj["kind"]
        g = obj["geometry"]
        if kind == "ROOM_LABEL":
            g = g["text_geometry"]
            kind = "TEXT"
        if kind == "TEXT":
            boxes.append(
                (
                    obj["id"],
                    [g["x"], g["y"] - g["height_px"], g["x"] + g["width_px"], g["y"]],
                )
            )
        elif kind == "MTEXT":
            boxes.append((obj["id"], g["bbox_xyxy_px"]))
    return boxes


def _retirement_proposals(geometry, prior_objects):
    dense = _dense_geometry(geometry, 0.75)
    path_lo, path_hi = dense.min(axis=0) - 2.0, dense.max(axis=0) + 2.0
    cs, ds = dense[:-1], dense[1:]
    vectors = ds - cs
    vector_lengths = np.linalg.norm(vectors, axis=1)
    units = vectors / np.maximum(vector_lengths[:, None], 1e-12)
    proposals = []
    crossings = []
    for obj in prior_objects:
        if obj["kind"] != "LINE":
            continue
        a = np.asarray(obj["geometry"]["start"], float)
        b = np.asarray(obj["geometry"]["end"], float)
        if np.any(np.maximum(a, b) < path_lo) or np.any(np.minimum(a, b) > path_hi):
            continue
        length = float(np.linalg.norm(b - a))
        u = (b - a) / length
        n = np.array([-u[1], u[0]])
        epsilon = 64 * max(math.ulp(abs(float(v))) for v in [length, *a, *b, 1.0])
        intervals = []
        numeric_zero_records = []
        valid = (
            (vector_lengths > epsilon)
            & (
                np.abs(units @ u)
                >= math.cos(math.radians(POLICY["prior_fragment_angle_deg"]))
            )
            & (
                np.maximum(np.abs((cs - a) @ n), np.abs((ds - a) @ n))
                <= POLICY["prior_fragment_normal_px"]
            )
        )
        starts, ends = (cs - a) @ u, (ds - a) @ u
        for index in np.flatnonzero(valid):
            lo, hi = sorted([float(starts[index]), float(ends[index])])
            lo, hi = max(0.0, lo), min(length, hi)
            if hi > lo:
                intervals.append([lo, hi])
        merged = []
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1] + epsilon:
                if lo > merged[-1][1]:
                    numeric_zero_records.append(
                        {
                            "kind": "merged_numeric_zero_gap",
                            "interval_px": [merged[-1][1], lo],
                        }
                    )
                merged[-1][1] = max(hi, merged[-1][1])
            else:
                merged.append([lo, hi])
        merged = [
            v for v in merged if v[1] - v[0] >= POLICY["minimum_retired_interval_px"]
        ]
        if merged:
            remainder = []
            last = 0.0
            for lo, hi in merged:
                if lo - last > epsilon:
                    remainder.append([last, lo])
                elif lo > last:
                    numeric_zero_records.append(
                        {"kind": "numeric_zero_remainder", "interval_px": [last, lo]}
                    )
                last = hi
            if length - last > epsilon:
                remainder.append([last, length])
            elif length > last:
                numeric_zero_records.append(
                    {"kind": "numeric_zero_remainder", "interval_px": [last, length]}
                )
            proposals.append(
                {
                    "prior_object_id": obj["id"],
                    "parent_geometry": obj["geometry"],
                    "parent_length_px": length,
                    "retire_intervals_px": merged,
                    "remaining_intervals_px": remainder,
                    "retired_length_px": sum(hi - lo for lo, hi in merged),
                    "remaining_length_px": sum(hi - lo for lo, hi in remainder),
                    "numeric_zero_epsilon_px": epsilon,
                    "numeric_zero_records": numeric_zero_records,
                    "length_balance_error_px": length
                    - sum(hi - lo for lo, hi in merged)
                    - sum(hi - lo for lo, hi in remainder),
                    "basis": "parallel source-supported path overlap; exact original-line parameter intervals",
                    "maximum_normal_distance_px": POLICY["prior_fragment_normal_px"],
                    "maximum_axis_angle_deg": POLICY["prior_fragment_angle_deg"],
                    "proposal_only_requires_independent_remainder_and_ownership_audit": True,
                }
            )
        else:
            projections = (dense - a) @ u
            closest = np.clip(projections, 0.0, length)
            distances = np.linalg.norm(dense - (a + closest[:, None] * u), axis=1)
            if distances.min() <= 2.0:
                crossings.append(
                    {
                        "prior_object_id": obj["id"],
                        "minimum_centerline_distance_px": float(distances.min()),
                        "decision": "RETAIN_NONPARALLEL_OR_NONOWNED_NEIGHBOR_UNCHANGED",
                    }
                )
    return proposals, crossings


def _round_boundary_ownership(points, rounds):
    """Locate sustained tangential runs on any observed symbol boundary.

    Different endpoint round IDs do not establish an independent connection:
    three touching symbols can produce a route along the middle symbol. Check
    all observed rounds against the original path, without erasing any source
    pixels or trimming the claimed path to make it pass.
    """
    points = np.asarray(points, float)
    if len(points) < 3:
        return []
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    span = np.r_[0.0, steps.cumsum()]
    # A short symmetric chord estimates the local raster tangent, avoiding
    # single stair-step directions. It does not change the path geometry.
    lo = np.searchsorted(span, np.maximum(0.0, span - 3.0))
    hi = np.minimum(len(points) - 1, np.searchsorted(span, span + 3.0))
    tangent = points[hi] - points[lo]
    tangent_norm = np.linalg.norm(tangent, axis=1)
    conflicts = []
    for ring in rounds:
        radial = points - np.asarray(ring["center"], float)
        radii = np.linalg.norm(radial, axis=1)
        residual = np.abs(radii - (ring["inner_boundary_radius_px"] + 1.0))
        radial_cosine = np.abs(np.sum(tangent * radial, axis=1)) / np.maximum(
            tangent_norm * radii, 1e-12
        )
        owned = (
            (residual <= POLICY["round_hole_radial_max_px"])
            & (tangent_norm > 0)
            & (
                radial_cosine
                <= math.sin(
                    math.radians(POLICY["round_boundary_tangent_max_deviation_deg"])
                )
            )
        )
        padded = np.r_[False, owned, False].astype(np.int8)
        starts = np.flatnonzero(np.diff(padded) == 1)
        stops = np.flatnonzero(np.diff(padded) == -1)
        for start, stop in zip(starts, stops):
            run_length = float(span[stop - 1] - span[start])
            if run_length < POLICY["round_boundary_minimum_owned_run_px"]:
                continue
            conflicts.append(
                {
                    "round_id": ring["id"],
                    "source_path_point_interval": [int(start), int(stop)],
                    "tangential_source_run_length_px": run_length,
                    "radial_residual_max_px": float(residual[start:stop].max()),
                    "decision": "OBSERVED_SYMBOL_BOUNDARY_REQUIRES_ITS_OWN_OWNER",
                }
            )
    return conflicts


def extract_connections(
    gray, roi, prior_objects, out, *, cpu_budget_seconds=42.0, text_regions=None,
    verified_text_observations=None,
):
    """Return native whole paths and explicit, unapplied prior-LINE intervals."""
    del (
        cpu_budget_seconds
    )  # Standalone default stays 42s; managed jobs use their explicit contract.
    started = time.process_time()
    wall = time.perf_counter()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(1)
    source = np.asarray(gray)
    x0, y0, x1, y1 = map(int, roi)
    margin = POLICY["context_px"]
    ox, oy = max(0, x0 - margin), max(0, y0 - margin)
    rx, by = min(source.shape[1], x1 + margin), min(source.shape[0], y1 + margin)
    origin = np.array([ox, oy])
    crop = source[oy:by, ox:rx]
    ink = crop < POLICY["source_threshold"]
    input_hash = hashlib.sha256(crop.tobytes()).hexdigest()
    rounds = _round_boundaries(ink, origin)
    skel, thinning_counts = _thinning(ink, started)
    from .text_graph_support import verified_candidate_core_boxes

    core_boxes = verified_candidate_core_boxes(gray, text_regions, verified_text_observations)
    graph = _SourceGraph(skel, origin, rounds, roi, started, source_ink=ink,
                         aggregate_core_boxes=core_boxes)
    distance = cv2.distanceTransform(
        (~ink).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    _, source_labels, source_stats, _ = cv2.connectedComponentsWithStats(
        ink.astype(np.uint8), connectivity=8
    )
    skel_counts = np.bincount(source_labels[skel].ravel(), minlength=len(source_stats))
    texts = _text_boxes(prior_objects)
    source_text_boxes = []
    if text_regions is not None:
        from .contracts import validate_text_regions

        source_text_boxes = validate_text_regions(text_regions, gray.shape, roi)
    from .text_graph_support import (
        assess_path_text_contact,
        complete_crossing_group,
        prepare_text_support,
    )

    text_support = prepare_text_support(
        gray, roi, text_regions, prior_objects, graph,
        verified_observations=verified_text_observations,
    )
    proposals = []
    uncertainties = []
    seen = set()
    for start_id in sorted(graph.nodes):
        start_node = graph.nodes[start_id]
        if not start_node["terminal"]:
            continue
        for first_port in start_node["edges"]:
            pixels, edge_ids, crossings, end_id, reason = graph.trace(
                start_id, first_port
            )
            if not pixels:
                continue
            key = tuple(sorted(edge_ids))
            if key in seen:
                continue
            seen.add(key)
            points = graph.xy(pixels)
            length = _length(points)
            graphic_group = complete_crossing_group(text_support, edge_ids)
            if length < POLICY["minimum_path_length_px"] and graphic_group is None:
                continue
            row = {
                "source_graph_edge_ids": edge_ids,
                "source_path_points": points.tolist(),
                "source_path_length_px": length,
                "start_node": start_id,
                "end_node": end_id,
                "endpoint_evidence": [
                    start_node["terminal"],
                    graph.nodes[end_id]["terminal"],
                ],
                "crossing_evidence": crossings,
            }
            label = int(source_labels.ravel()[pixels[0]])
            row["source_connected_group_id"] = f"SOURCE-COMPONENT-{label:06d}"
            row["source_component_bbox_xywh"] = (
                source_stats[label, :4] + np.array([ox, oy, 0, 0])
            ).tolist()
            end_node = graph.nodes[end_id]
            if reason:
                row["reason"] = reason
                uncertainties.append(row)
                continue
            if (
                points[:, 0].min() < x0
                or points[:, 0].max() > x1
                or points[:, 1].min() < y0
                or points[:, 1].max() > y1
            ):
                row["reason"] = "WHOLE_SOURCE_ROUTE_EXCEEDS_FROZEN_QUARTER"
                uncertainties.append(row)
                continue
            if start_id == end_id or (
                start_node["terminal"].get("round_id")
                and start_node["terminal"].get("round_id")
                == end_node["terminal"].get("round_id")
            ):
                row["reason"] = "SAME_BOUNDARY_LOOP_NOT_AN_INDEPENDENT_OPEN_CONNECTION"
                uncertainties.append(row)
                continue
            endpoints = [start_node["terminal"]["kind"], end_node["terminal"]["kind"]]
            ring_pair = all(v == "OBSERVED_ROUND_BOUNDARY_CONTACT" for v in endpoints)
            free_pair = all(
                v in ("OBSERVED_FREE_SOURCE_ENDPOINT", "OBSERVED_CLOSED_TERMINAL_LOBE")
                for v in endpoints
            )
            mixed_pair = sorted(endpoints) == sorted(
                ["OBSERVED_ROUND_BOUNDARY_CONTACT", "OBSERVED_FREE_SOURCE_ENDPOINT"]
            )
            terminal_lobes = [
                n["terminal"]
                for n in (start_node, end_node)
                if n["terminal"].get("kind") == "OBSERVED_CLOSED_TERMINAL_LOBE"
            ]
            chord = float(np.linalg.norm(points[-1] - points[0]))
            if not ring_pair and not free_pair and not mixed_pair:
                row["reason"] = "MIXED_ENDPOINT_ROLE_REQUIRES_WHOLE_GROUP_REVIEW"
                uncertainties.append(row)
                continue
            if length > POLICY["maximum_path_length_px"] or chord < 1:
                row["reason"] = "PATH_EXTENT_OUTSIDE_FROZEN_PROPOSAL_SCOPE"
                uncertainties.append(row)
                continue
            boundary_conflicts = _round_boundary_ownership(points, rounds)
            row["observed_round_boundary_ownership_checks"] = {
                "round_observations_checked": len(rounds),
                "conflicts": boundary_conflicts,
                "source_boundary_pixels_removed": False,
            }
            if boundary_conflicts:
                row["reason"] = (
                    "OBSERVED_ROUND_BOUNDARY_IS_NOT_AN_INDEPENDENT_CONNECTION"
                )
                uncertainties.append(row)
                continue
            if mixed_pair:
                mixed_chain = _mixed_observed_endpoint_chain_certificate(
                    graph, pixels, label, source_labels
                )
                row["complete_mixed_observed_endpoint_chain"] = mixed_chain
                if not mixed_chain["pass"]:
                    row["reason"] = "MIXED_ENDPOINT_PATH_SOURCE_OWNERSHIP_NOT_COMPLETE"
                    uncertainties.append(row)
                    continue
            if free_pair or mixed_pair:
                whole_component = len(set(pixels)) == int(skel_counts[label])
                row["whole_isolated_component_skeleton_accounted"] = whole_component
                row["raster_path_length_to_chord_ratio_diagnostic_only"] = length / chord
                row["connected_group_may_have_several_independent_paths"] = bool(
                    crossings
                )
                simple_chain = None
                if free_pair and not crossings and not terminal_lobes:
                    simple_chain = _simple_source_chain_certificate(
                        graph, pixels, label, source_labels, int(skel_counts[label])
                    )
                    row["whole_simple_source_chain"] = simple_chain
                if free_pair and (
                    (not crossings and not whole_component)
                    or (simple_chain is not None and not simple_chain["pass"])
                ):
                    row["reason"] = "NOT_A_WHOLE_THIN_ISOLATED_CURVED_STROKE"
                    uncertainties.append(row)
                    continue
                cap_checks = []
                for ordered, endpoint_node in zip(
                    (points, points[::-1]), (start_node, end_node)
                ):
                    if endpoint_node["terminal"]["kind"] == "OBSERVED_ROUND_BOUNDARY_CONTACT":
                        cap_checks.append(
                            {
                                "kind": "OBSERVED_ROUND_BOUNDARY_CONTACT_RETAINED",
                                "round_id": endpoint_node["terminal"]["round_id"],
                                "boundary_pixels_owned_or_removed": False,
                                "pass": not boundary_conflicts,
                            }
                        )
                        continue
                    if (
                        endpoint_node["terminal"]["kind"]
                        == "OBSERVED_CLOSED_TERMINAL_LOBE"
                    ):
                        cap_checks.append(
                            {
                                "kind": "EXPLICIT_TERMINAL_LOOP_RETAINED_IN_SAME_PATH",
                                "loop_edge_id": endpoint_node["terminal"][
                                    "loop_edge_id"
                                ],
                                "pass": True,
                                "hole_filled": False,
                                "external_port_count": 1,
                            }
                        )
                        continue
                    endpoint = ordered[0]
                    span = np.r_[
                        0.0, np.linalg.norm(np.diff(ordered, axis=0), axis=1).cumsum()
                    ]
                    tangent_index = min(
                        len(ordered) - 1, int(np.searchsorted(span, min(8.0, span[-1])))
                    )
                    outward = endpoint - ordered[tangent_index]
                    outward /= np.linalg.norm(outward)
                    ex, ey = np.round(endpoint - origin).astype(int)
                    lx, ly = max(0, ex - 6), max(0, ey - 6)
                    hx, hy = min(ink.shape[1], ex + 7), min(ink.shape[0], ey + 7)
                    yy, xx = np.nonzero(source_labels[ly:hy, lx:hx] == label)
                    source_points = np.column_stack((xx + lx, yy + ly)) + origin
                    forward = float(
                        max(0.0, ((source_points - endpoint) @ outward).max())
                    )
                    cap_checks.append(
                        {
                            "endpoint": endpoint.tolist(),
                            "outward_source_tangent": outward.tolist(),
                            "source_cap_forward_extent_px": forward,
                            "source_neighborhood_xyxy_px": [
                                lx + ox,
                                ly + oy,
                                hx + ox,
                                hy + oy,
                            ],
                            "pass": forward <= POLICY["endpoint_cap_extent_px"],
                        }
                    )
                row["original_source_endpoint_cap_checks"] = cap_checks
                if not all(item["pass"] for item in cap_checks):
                    row["reason"] = (
                        "SOURCE_TERMINAL_CAP_NOT_EXPLAINED_WITHIN_ENDPOINT_BOUND"
                    )
                    uncertainties.append(row)
                    continue
            normal = (
                np.array([-(points[-1] - points[0])[1], (points[-1] - points[0])[0]])
                / chord
            )
            curved_deviation = float(np.max(np.abs((points - points[0]) @ normal)))
            if (
                curved_deviation < POLICY["minimum_curved_deviation_px"]
                and not terminal_lobes
                and graphic_group is None
            ):
                continue  # Existing straight-LINE capability; no new recovery claim.
            contacts = []
            for text_id, box in texts:
                inside = (
                    (points[:, 0] >= box[0] - 1)
                    & (points[:, 0] <= box[2] + 1)
                    & (points[:, 1] >= box[1] - 1)
                    & (points[:, 1] <= box[3] + 1)
                )
                if inside.sum() >= 6:
                    contacts.append(text_id)
            if contacts:
                row["reason"] = "EXISTING_NATIVE_TEXT_NEIGHBOR_CONTACT"
                row["text_neighbor_ids"] = contacts
                uncertainties.append(row)
                continue
            glyph_contacts = []
            for box in source_text_boxes:
                runs = box.get("glyph_source_runs")
                if runs is None:
                    b = box["bbox_xyxy_px"]
                    hit = (
                        (points[:, 0] >= b[0])
                        & (points[:, 0] <= b[2])
                        & (points[:, 1] >= b[1])
                        & (points[:, 1] <= b[3])
                    )
                else:
                    hit = np.zeros(len(points), bool)
                    for y, left, right in runs:
                        hit |= (
                            (abs(points[:, 1] - y) <= 1)
                            & (points[:, 0] >= left)
                            & (points[:, 0] < right)
                        )
                if int(hit.sum()) >= 6:
                    glyph_contacts.append(box["region_id"])
            if glyph_contacts:
                role = assess_path_text_contact(
                    text_support, points, row["endpoint_evidence"], crossings,
                    glyph_contacts,
                    complete_source_path=(
                        row.get("whole_isolated_component_skeleton_accounted", False)
                        or row.get("complete_mixed_observed_endpoint_chain", {}).get("pass", False)
                        or graphic_group is not None
                    ),
                    source_graph_edge_ids=edge_ids,
                )
                row["text_graphic_support"] = role
                if role["decision"] != "SOURCE_SUPPORTED_GRAPHIC":
                    row["reason"] = "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT"
                    row["text_region_ids"] = sorted(set(glyph_contacts))
                    uncertainties.append(row)
                    continue
            elif graphic_group is not None and (
                length < POLICY["minimum_path_length_px"]
                or curved_deviation < POLICY["minimum_curved_deviation_px"]
            ):
                # The bounded straight/short-member route is licensed only by
                # a freshly proved graphic support relation for this group.
                continue
            protected = [
                len(n["terminal"].get("loop_pixels", []))
                for n in (start_node, end_node)
            ]
            geometry, representation = _representation(
                points,
                protected_prefix=protected[0],
                protected_suffix=protected[1],
                protected_intervals=[
                    row["protected_source_path_interval"]
                    for row in crossings
                    if row.get("local_cycle_cover_evidence")
                ],
            )
            if (row.get("whole_simple_source_chain", {}).get("pass") or mixed_pair
                    or graphic_group is not None):
                fit = _simple_chain_fit_certificate(points, geometry)
                if not fit["pass"]:
                    simplified, encoding = _bounded_source_polyline(points)
                    replacement = {
                        "points": simplified.tolist(),
                        "bulges": [0.0] * len(simplified),
                        "closed": False,
                    }
                    retry = _simple_chain_fit_certificate(points, replacement)
                    row["initial_simple_chain_fit"] = fit
                    geometry, fit = replacement, retry
                    representation = {
                        "representation": "ONE_NATIVE_OPEN_POLYLINE",
                        "source_ordered_span_encoding": encoding,
                        "single_bounded_fallback_from_initial_fit": True,
                    }
                row[
                    "mixed_observed_endpoint_chain_fit"
                    if mixed_pair
                    else "whole_simple_source_chain_fit"
                ] = fit
                if not fit["pass"]:
                    row["reason"] = "COMPLETE_SOURCE_CHAIN_NATIVE_FIT_NOT_BIDIRECTIONAL"
                    row["native_geometry"] = geometry
                    uncertainties.append(row)
                    continue
            if len(geometry["points"]) > POLICY["maximum_control_vertices"]:
                row["reason"] = "CONTROL_COMPLEXITY_EXCEEDS_FROZEN_LIMIT"
                row["native_geometry"] = geometry
                row["native_representation"] = representation
                row["control_vertex_count"] = len(geometry["points"])
                uncertainties.append(row)
                continue
            dense = _dense_geometry(geometry, POLICY["dense_step_px"])
            support = _support(dense, distance, origin)
            if not support["pass"]:
                row["reason"] = "WHOLE_NATIVE_PATH_SOURCE_GATE_FAILED"
                row["native_geometry"] = geometry
                row["support"] = support
                uncertainties.append(row)
                continue
            white_space = _local_cycle_white_space_checks(geometry, crossings)
            if white_space is not None:
                row["local_cycle_white_space_checks"] = white_space
                if not white_space["pass"]:
                    row["reason"] = (
                        "LOCAL_CYCLE_NATIVE_GEOMETRY_CONSUMES_ORIGINAL_WHITE_SPACE"
                    )
                    row["native_geometry"] = geometry
                    uncertainties.append(row)
                    continue
            retirement, retained = _retirement_proposals(geometry, prior_objects)
            row.update(
                {
                    "method": "original_source_graph_round_terminals_unique_four_port_continuation",
                    "whole_path_class": (
                        "ROUND_BOUNDARY_TO_ROUND_BOUNDARY"
                        if ring_pair
                        else "OBSERVED_ROUND_BOUNDARY_TO_NATURAL_ENDPOINT"
                        if mixed_pair
                        else "COMPLETE_STROKE_WITH_TERMINAL_LOOP"
                        if terminal_lobes
                        else "COMPLETE_PATH_IN_SHARED_SOURCE_COMPONENT"
                        if crossings
                        else "ISOLATED_NATURAL_END_CURVED_STROKE"
                    ),
                    "semantic_connection_type": "UNKNOWN_NOT_INFERRED",
                    "source_support": support,
                    "source_curved_deviation_px": curved_deviation,
                    "native_representation": representation,
                    "control_vertex_count": len(geometry["points"]),
                    "native_unconstrained_planar_parameters": 3
                    * len(geometry["points"])
                    - 1,
                    "original_source_crop_xyxy_px": [ox, oy, rx, by],
                    "original_source_crop_array_sha256": input_hash,
                    "source_pixels_modified": False,
                    "source_morphological_gap_closing": False,
                    "source_short_branches_deleted": False,
                    "fixture_or_expected_answer_used": False,
                    "symbol_boundary_geometry_not_consumed": True,
                    "retirement_proposals": retirement,
                    "retained_neighbor_contacts": retained,
                    "independent_CAD_readback_render_edit_gate": "PENDING",
                }
            )
            proposals.append(
                {
                    "id": stable_id("CONNECTION", geometry),
                    "kind": "CONNECTION_PATH",
                    "layer": "CONNECTIONS",
                    "geometry": geometry,
                    "source_evidence": row,
                    "editing_scope": "one whole observed path; endpoint symbols and crossing neighbors remain separate",
                    "status": "SOURCE_SUPPORTED_WHOLE_PATH_PENDING_INDEPENDENT_CAD_VALIDATION",
                }
            )
            _checkpoint(started)
    # One rule applies across the requested ROI; work is bounded by the task
    # resource contract, not an arbitrary cap on successfully rebuilt objects.
    proposals.sort(
        key=lambda p: (
            -len(p["source_evidence"]["crossing_evidence"]),
            -p["source_evidence"]["source_path_length_px"],
            p["id"],
        )
    )
    owners = defaultdict(list)
    for obj in proposals:
        for eid in set(obj["source_evidence"]["source_graph_edge_ids"]):
            owners[eid].append(obj["id"])
    selected = []
    for obj in proposals:
        conflicts = {
            eid: owners[eid]
            for eid in obj["source_evidence"]["source_graph_edge_ids"]
            if len(owners[eid]) > 1
        }
        if conflicts:
            uncertainties.append(
                {
                    **obj["source_evidence"],
                    "reason": "SOURCE_GRAPH_EDGE_HAS_MULTIPLE_PROPOSED_OWNERS",
                    "conflicting_proposed_owners": conflicts,
                }
            )
        else:
            selected.append(obj)
    # A compound graphic is not reported complete if one of its real crossing
    # strokes failed native fitting or source responsibility. Shared core
    # pixels remain evidence; each external graph edge still has a whole path.
    complete_groups = {}
    for obj in selected:
        certificate = obj["source_evidence"].get("text_graphic_support", {}).get("complete_graphic_group")
        if certificate:
            complete_groups.setdefault(certificate["certificate_sha256"], (certificate, []))[1].append(obj)
    incomplete_ids = set()
    for certificate, members in complete_groups.values():
        expected = {tuple(sorted(row["source_graph_edge_ids"])) for row in certificate["complete_routes"]}
        actual = {tuple(sorted(obj["source_evidence"]["source_graph_edge_ids"])) for obj in members}
        if actual != expected:
            incomplete_ids.update(obj["id"] for obj in members)
            uncertainties.append({
                "reason": "WHOLE_GRAPHIC_GROUP_NATIVE_MEMBERS_INCOMPLETE",
                "source_connected_group_id": members[0]["source_evidence"]["source_connected_group_id"],
                "group_certificate": certificate,
                "complete_member_path_ids_before_group_gate": [obj["id"] for obj in members],
                "missing_source_edge_paths": [list(key) for key in sorted(expected - actual)],
                "source_short_branches_removed": False,
            })
        else:
            responsibility = [
                {"path_id": obj["id"], "source_graph_edge_ids": obj["source_evidence"]["source_graph_edge_ids"],
                 "endpoint_evidence": obj["source_evidence"]["endpoint_evidence"]}
                for obj in members
            ]
            for obj in members:
                obj["source_evidence"]["graphic_group_path_responsibility"] = responsibility
    selected = [obj for obj in selected if obj["id"] not in incomplete_ids]
    groups = defaultdict(
        lambda: {
            "edge_ids": [],
            "node_ids": [],
            "proposed_path_ids": [],
            "uncertainty_indices": [],
        }
    )
    graph_edges = []
    graph_nodes = []
    for edge in graph.edges:
        label = int(source_labels.ravel()[edge["pixels"][0]])
        group_id = f"SOURCE-COMPONENT-{label:06d}"
        groups[label]["edge_ids"].append(edge["id"])
        graph_edges.append(
            {
                "id": edge["id"],
                "nodes": edge["nodes"],
                "length_px": edge["length"],
                "source_connected_group_id": group_id,
                "source_points": graph.xy(edge["pixels"]).tolist(),
                "short_branch_or_dash_preserved": edge["length"]
                < POLICY["minimum_path_length_px"],
            }
        )
    for node in graph.nodes.values():
        label = int(source_labels.ravel()[node["pixels"][0]])
        groups[label]["node_ids"].append(node["id"])
        graph_nodes.append(
            {
                "id": node["id"],
                "source_connected_group_id": f"SOURCE-COMPONENT-{label:06d}",
                "center": node["center"],
                "source_core_points": graph.xy(node["pixels"]).tolist(),
                "all_ports": [list(p) for p in node["edges"]],
                "pairings": [
                    {"incoming": list(k), "outgoing": list(v)}
                    for k, v in node["pairing"].items()
                ],
                "terminal": node["terminal"],
                "reason": node.get("reason"),
                "core_topology": node["core_topology"],
                "finite_path_decompositions": node["finite_path_decompositions"],
                "local_cycle_cover_evidence": node.get("local_cycle_cover"),
                "bounded_aggregate_source_core": node.get("bounded_aggregate_source_core"),
                "semantic_connectivity": "UNKNOWN_UNLESS_INDEPENDENT_SOURCE_CONTEXT_PROVES_IT",
            }
        )
    assigned_edges = set()
    for obj in selected:
        ev = obj["source_evidence"]
        label = int(ev["source_connected_group_id"].rsplit("-", 1)[1])
        groups[label]["proposed_path_ids"].append(obj["id"])
        assigned_edges.update(ev["source_graph_edge_ids"])
    for index, row in enumerate(uncertainties):
        if row.get("source_connected_group_id"):
            label = int(row["source_connected_group_id"].rsplit("-", 1)[1])
            groups[label]["uncertainty_indices"].append(index)
    group_rows = []
    for label, row in sorted(groups.items()):
        group_rows.append(
            {
                "id": f"SOURCE-COMPONENT-{label:06d}",
                **row,
                "bbox_xywh_px": (
                    source_stats[label, :4] + np.array([ox, oy, 0, 0])
                ).tolist(),
                "source_ink_pixel_count": int(source_stats[label, 4]),
                "skeleton_pixel_count": int(skel_counts[label]),
                "edges_pending_or_owned_by_existing_objects": [
                    e for e in row["edge_ids"] if e not in assigned_edges
                ],
                "independent_paths_per_group_permitted": True,
                "short_edges_erased": False,
                "white_gaps_closed": False,
                "semantic_connection_type": "UNKNOWN_NOT_INFERRED",
            }
        )
    graph_path = out / "source_graph.json"
    save_json(
        graph_path,
        {
            "schema": "unmodified_source_graph_v2",
            "source_crop_xyxy_px": [ox, oy, rx, by],
            "source_crop_array_sha256": input_hash,
            "nodes": graph_nodes,
            "edges": graph_edges,
            "groups": group_rows,
            "bounded_local_cycle_cell_discovery": graph.cycle_cell_discovery,
            "bounded_aggregate_source_cores": graph.bounded_aggregate_cores,
            "all_ports_and_short_edges_preserved": True,
            "nodes_without_unique_decomposition_remain_pending": True,
        },
    )
    result = {
        "schema": "whole_source_connections_v2",
        "dependency_producers": {
            "app.native_objects.connection_core_routes": hashlib.sha256(
                Path(__file__).with_name("connection_core_routes.py").read_bytes()
            ).hexdigest(),
            "app.native_objects.text_graph_support": hashlib.sha256(
                Path(__file__).with_name("text_graph_support.py").read_bytes()
            ).hexdigest(),
            "app.native_objects.checkpoint_text_observations": hashlib.sha256(
                Path(__file__).with_name("checkpoint_text_observations.py").read_bytes()
            ).hexdigest(),
        },
        "policy": POLICY,
        "objects": selected,
        "uncertainties": uncertainties,
        "round_boundary_observations": rounds,
        "source_connected_groups": group_rows,
        "source_graph": {
            "path": graph_path.name,
            "sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        },
        "graph_summary": {
            "source_ink_pixels": int(ink.sum()),
            "skeleton_pixels": int(skel.sum()),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "source_four_port_unique_continuations": sum(
                bool(n["pairing"]) and len(n["edges"]) == 4
                for n in graph.nodes.values()
            ),
            "source_two_port_unique_continuations": sum(
                bool(n["pairing"]) and len(n["edges"]) == 2
                for n in graph.nodes.values()
            ),
            "source_two_port_local_cycle_cover_candidates": sum(
                bool(row["eligible"]) for row in graph.cycle_cell_discovery["cells"]
            ),
            "source_round_to_round_paths_with_local_cycle_cover": sum(
                any(
                    c.get("local_cycle_cover_evidence")
                    for c in obj["source_evidence"]["crossing_evidence"]
                )
                for obj in selected
            ),
            "round_boundary_terminal_nodes": sum(
                n["terminal"] is not None
                and n["terminal"]["kind"] == "OBSERVED_ROUND_BOUNDARY_CONTACT"
                for n in graph.nodes.values()
            ),
            "thinning_removed_pixels_per_iteration": thinning_counts,
            "source_background_gaps_unchanged": True,
        },
        "complete_proposals_before_cap": len(proposals),
        "candidate_count": len(selected),
        "source_array_unchanged": input_hash
        == hashlib.sha256(crop.tobytes()).hexdigest(),
        "resources": {
            "cpu_seconds": time.process_time() - started,
            "wall_seconds": time.perf_counter() - wall,
        },
    }
    save_json(out / "connections.json", result)
    return result
