"""Cold, source-bound proof of intentional retraces inside one saved polyline.

An object ID is never an exemption.  A bounded local source cell, original
white pixels, the complete protected walk, its exact saved vertex positions,
and every repeated traversal must all agree.  The returned allowances refer
to two segment indices on one actual modelspace handle.  Other repetitions
remain ordinary duplicate-geometry failures.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np


EPS = 1e-7


def _point(value):
    if len(value) != 2 or any(not math.isfinite(float(v)) for v in value):
        raise ValueError("NONFINITE_SOURCE_POINT")
    return tuple(float(v) for v in value)


def _edge(a, b):
    return tuple(sorted((_point(a), _point(b))))


def _edges(points):
    return Counter(_edge(a, b) for a, b in zip(points, points[1:]))


def _same(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and bool(np.allclose(a, b, atol=EPS, rtol=0))


def _identity(entity):
    if not entity.has_xdata("I2CAD_NATIVE_V2"):
        return {}
    for tag in entity.get_xdata("I2CAD_NATIVE_V2"):
        if tag.code == 1000:
            try:
                return json.loads(tag.value)
            except (TypeError, ValueError):
                return {}
    return {}


def _neighbors(point, skeleton):
    x, y = point
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            q = (x + dx, y + dy)
            if not (dx or dy) or q not in skeleton:
                continue
            if dx and dy and ((x + dx, y) in skeleton or (x, y + dy) in skeleton):
                continue
            yield q


def _component(seed, allowed, connectivity):
    found, pending = {seed}, [seed]
    while pending:
        x, y = pending.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy) or (connectivity == 4 and dx and dy):
                    continue
                q = (x + dx, y + dy)
                if q in allowed and q not in found:
                    found.add(q)
                    pending.append(q)
    return found


def _distance(point, a, b):
    delta = np.asarray(b, float) - a
    offset = np.asarray(point, float) - a
    fraction = np.clip(offset @ delta / max(float(delta @ delta), 1e-12), 0, 1)
    return float(np.linalg.norm(offset - fraction * delta))


def _unique_rows(rows):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("DUPLICATE_EVIDENCE_ID")
    return result


def certify_saved_retraces(
    doc, dxf_sha256, metadata_path, graph_path, discovery_path, gray, roi, dpi
):
    """Return explicit allowances and failed proof rows, without changing files.

    The raw graph is hash-bound to the current decoded source crop.  Local
    cells are reconstructed from all of its real nodes/edges/ports; neither a
    candidate's claimed subgraph nor its flags substitute for this evidence.
    The original source image independently supplies every ink/white witness.
    This function does not claim to hash the original TIFF container from a
    decoded array.
    """
    report = {
        "schema": "saved_same_handle_source_cell_retrace_proof_v1",
        "actual_DXF_sha256": dxf_sha256,
        "allowances": [],
        "object_checks": [],
        "geometry_modified": False,
        "OID_only_exemptions": False,
        "source_image_or_graph_modified": False,
        "TIFF_container_hash_verified_by_this_function": False,
    }
    metadata_path, graph_path, discovery_path = map(
        Path, (metadata_path, graph_path, discovery_path)
    )
    if not metadata_path.is_file():
        report["evidence_status"] = "NO_SIDECAR_NO_RETRACE_ALLOWANCE"
        return report
    try:
        meta = json.loads(metadata_path.read_text())
        claimed = [
            o
            for o in meta["objects"]
            if any(
                c.get("local_cycle_cover_evidence")
                for c in o.get("source_evidence", {}).get("crossing_evidence", [])
            )
        ]
        if not claimed:
            report["evidence_status"] = "NO_DECLARED_LOCAL_CYCLE_RETRACES"
            return report
        objects = _unique_rows(meta["objects"])
        written = _unique_rows(meta["written"])
        if len({r["handle"] for r in meta["written"]}) != len(meta["written"]):
            raise ValueError("DUPLICATE_WRITTEN_HANDLE")
        if (
            meta["dxf_sha256"] != dxf_sha256
            or meta["roi_xyxy_px"] != list(roi)
            or float(meta["dpi"]) != dpi
        ):
            raise ValueError("SIDECAR_DXF_OR_COORDINATE_BINDING_MISMATCH")
        graph_bytes = graph_path.read_bytes()
        discovery = json.loads(discovery_path.read_text())
        if (
            hashlib.sha256(graph_bytes).hexdigest()
            != discovery["source_graph"]["sha256"]
        ):
            raise ValueError("RAW_SOURCE_GRAPH_HASH_MISMATCH")
        graph = json.loads(graph_bytes)
        bounds = graph["source_crop_xyxy_px"]
        if len(bounds) != 4 or any(not isinstance(v, int) for v in bounds):
            raise ValueError("RAW_GRAPH_SOURCE_CROP_INVALID")
        x0, y0, x1, y1 = bounds
        if not 0 <= x0 < x1 <= gray.shape[1] or not 0 <= y0 < y1 <= gray.shape[0]:
            raise ValueError("RAW_GRAPH_SOURCE_CROP_OUTSIDE_IMAGE")
        if (
            hashlib.sha256(gray[y0:y1, x0:x1].tobytes()).hexdigest()
            != graph["source_crop_array_sha256"]
        ):
            raise ValueError("RAW_SOURCE_GRAPH_CURRENT_IMAGE_BINDING_MISMATCH")
        if discovery["policy"]["source_threshold"] != 128:
            raise ValueError("RAW_SOURCE_GRAPH_THRESHOLD_CHANGED")
        expected_crop = [
            max(0, roi[0] - 32),
            max(0, roi[1] - 32),
            min(gray.shape[1], roi[2] + 32),
            min(gray.shape[0], roi[3] + 32),
        ]
        if discovery["policy"]["context_px"] != 32 or bounds != expected_crop:
            raise ValueError("RAW_SOURCE_GRAPH_CROP_IS_NOT_CURRENT_ROI_CONTEXT")
        nodes, edges = _unique_rows(graph["nodes"]), _unique_rows(graph["edges"])
        graph_ports = {nid: [] for nid in nodes}
        for eid, edge in edges.items():
            if len(edge["nodes"]) != 2:
                raise ValueError("RAW_GRAPH_EDGE_DOES_NOT_HAVE_TWO_ENDS")
            for end, nid in enumerate(edge["nodes"]):
                graph_ports[nid].append((eid, end))
        skeleton = set()
        for row in graph["nodes"] + graph["edges"]:
            skeleton.update(
                _point(p)
                for p in row.get("source_core_points", row.get("source_points", []))
            )
        actual_by_id = {}
        for entity in doc.modelspace():
            if entity.dxf.layer != "REVIEW":
                actual_by_id.setdefault(_identity(entity).get("id"), []).append(entity)
        all_path_edges = {
            oid: set(_edges(o["source_evidence"]["source_path_points"]))
            for oid, o in objects.items()
            if o["kind"] == "CONNECTION_PATH"
        }
        all_path_graph_edges = {
            oid: set(o["source_evidence"]["source_graph_edge_ids"])
            for oid, o in objects.items()
            if o["kind"] == "CONNECTION_PATH"
        }
        report["raw_graph_sha256"] = hashlib.sha256(graph_bytes).hexdigest()
        report["source_crop_array_sha256"] = graph["source_crop_array_sha256"]
        report["sidecar_sha256"] = hashlib.sha256(
            metadata_path.read_bytes()
        ).hexdigest()
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
    ) as exc:
        report["evidence_status"] = "RETRACE_EVIDENCE_BINDING_FAILED"
        report["object_checks"] = [
            {
                "id": "UNBOUND_LOCAL_RETRACE_EVIDENCE",
                "pass": False,
                "failures": [str(exc)],
            }
        ]
        return report

    mm = 25.4 / dpi

    def ink(p):
        x, y = p
        return (
            x == int(x)
            and y == int(y)
            and 0 <= x < gray.shape[1]
            and 0 <= y < gray.shape[0]
            and gray[int(y), int(x)] < 128
        )

    for obj in claimed:
        oid = obj["id"]
        result = {
            "id": oid,
            "handle": written.get(oid, {}).get("handle"),
            "pass": False,
            "failures": [],
            "cells": [],
        }

        def require(ok, reason):
            if not ok:
                raise ValueError(reason)

        try:
            require(
                obj["kind"] == "CONNECTION_PATH",
                "RETRACE_OWNER_IS_NOT_A_CONNECTION_PATH",
            )
            require(
                len(actual_by_id.get(oid, [])) == 1,
                "RETRACE_ID_DOES_NOT_LOCATE_EXACTLY_ONE_MODELSPACE_HANDLE",
            )
            entity = actual_by_id[oid][0]
            require(
                entity.dxf.handle == written[oid]["handle"]
                and written[oid]["kind"] == obj["kind"],
                "ACTUAL_HANDLE_WRITTEN_BINDING_MISMATCH",
            )
            require(
                entity.dxftype() == "LWPOLYLINE" and not entity.closed,
                "RETRACE_REQUIRES_ONE_OPEN_TOP_LEVEL_LWPOLYLINE",
            )
            require(
                float(entity.dxf.get("elevation", 0)) == 0
                and tuple(entity.dxf.extrusion) == (0, 0, 1),
                "RETRACE_POLYLINE_PLANE_IS_NOT_DEFAULT",
            )
            require(
                float(entity.dxf.get("thickness", 0)) == 0,
                "RETRACE_POLYLINE_HAS_THICKNESS",
            )
            linetype = str(entity.dxf.get("linetype", "BYLAYER")).upper()
            if linetype == "BYLAYER":
                require(
                    doc.layers.has_entry(entity.dxf.layer), "RETRACE_LAYER_IS_MISSING"
                )
                linetype = str(doc.layers.get(entity.dxf.layer).dxf.linetype).upper()
            require(
                linetype == "CONTINUOUS" and doc.linetypes.has_entry(linetype),
                "RETRACE_EFFECTIVE_LINETYPE_IS_NOT_CONTINUOUS",
            )
            pattern = doc.linetypes.get(linetype).pattern_tags.tags
            require(
                not any(tag.code == 49 for tag in pattern)
                and all(
                    float(tag.value) == 0 for tag in pattern if tag.code in (40, 73)
                ),
                "RETRACE_CONTINUOUS_LINETYPE_HAS_A_PATTERN",
            )
            vertices = np.asarray([list(p) for p in entity.get_points("xyseb")], float)
            require(
                len(vertices) >= 2 and np.isfinite(vertices).all(),
                "INVALID_NATIVE_RETRACE_VERTICES",
            )
            require(
                not np.any(vertices[:, 2:] != 0)
                and float(entity.dxf.get("const_width", 0)) == 0,
                "RETRACE_HAS_WIDTH_OR_BULGE",
            )
            native = np.column_stack(
                (vertices[:, 0] / mm + roi[0], roi[3] - vertices[:, 1] / mm)
            )
            geometry = obj["geometry"]
            require(
                not geometry.get("closed")
                and _same(native, geometry["points"])
                and all(abs(v) <= EPS for v in geometry["bulges"]),
                "WHOLE_NATIVE_GEOMETRY_DIFFERS_FROM_BOUND_SIDECAR",
            )
            ev = obj["source_evidence"]
            source_path = [_point(p) for p in ev["source_path_points"]]
            require(
                2 <= len(source_path) <= 10000
                and len(vertices) <= 48
                and len(vertices) == ev["control_vertex_count"],
                "RETRACE_PATH_OR_NATIVE_VERTEX_BUDGET_MISMATCH",
            )
            require(
                _same(native[[0, -1]], [source_path[0], source_path[-1]]),
                "NATIVE_ENDPOINTS_DIFFER_FROM_OBSERVED_SOURCE_ENDPOINTS",
            )
            require(
                all(p in skeleton and ink(p) for p in source_path),
                "SOURCE_PATH_IS_NOT_ORIGINAL_SOURCE_GRAPH_INK",
            )
            require(
                all(
                    b in set(_neighbors(a, skeleton))
                    for a, b in zip(source_path, source_path[1:])
                ),
                "SOURCE_PATH_BRIDGES_A_MISSING_SOURCE_ADJACENCY",
            )
            require(
                len(ev["source_graph_edge_ids"])
                == len(set(ev["source_graph_edge_ids"])),
                "SOURCE_GRAPH_EDGE_ID_IS_REPEATED_AS_AN_OWNER",
            )
            require(
                all(
                    not (set(ev["source_graph_edge_ids"]) & other)
                    for other_id, other in all_path_graph_edges.items()
                    if other_id != oid
                ),
                "SOURCE_GRAPH_EDGE_HAS_ANOTHER_FORMAL_PATH_OWNER",
            )
            for eid in ev["source_graph_edge_ids"]:
                chain = edges[eid]["source_points"]
                require(
                    any(
                        _same(source_path[i : i + len(chain)], chain)
                        or _same(source_path[i : i + len(chain)], chain[::-1])
                        for i in range(len(source_path) - len(chain) + 1)
                    ),
                    "CLAIMED_GRAPH_EDGE_NOT_FULLY_IN_SOURCE_PATH",
                )
            endpoints = ev["endpoint_evidence"]
            require(
                len(endpoints) == 2
                and all(
                    e and e.get("kind") == "OBSERVED_ROUND_BOUNDARY_CONTACT"
                    for e in endpoints
                ),
                "RETRACE_DOES_NOT_HAVE_TWO_OBSERVED_ROUND_TERMINALS",
            )
            require(
                endpoints[0]["round_id"] != endpoints[1]["round_id"],
                "RETRACE_TERMINALS_ARE_THE_SAME_ROUND",
            )
            for index, field in enumerate(("start_node", "end_node")):
                node = nodes[ev[field]]
                require(
                    node["terminal"] == endpoints[index]
                    and source_path[0 if index == 0 else -1]
                    in set(map(_point, node["source_core_points"])),
                    "RETRACE_TERMINAL_RAW_NODE_MISMATCH",
                )
            covered_indices = set()
            expected_repeats = {}
            object_allowances = []
            for crossing in ev["crossing_evidence"]:
                cert = crossing.get("local_cycle_cover_evidence")
                if not cert:
                    continue
                require(
                    cert.get("eligible") is True
                    and cert.get("single_owner_required") is True
                    and cert.get("source_pixels_modified") is False
                    and cert.get("source_short_branches_deleted") is False
                    and cert.get("selection_is_encoding_only_not_semantic_inference")
                    is True,
                    "CERTIFICATE_IS_NOT_AN_ELIGIBLE_UNMODIFIED_SINGLE_OWNER_ENCODING",
                )
                nids = cert["cell_node_ids"]
                require(
                    1 <= len(nids) <= 4
                    and len(nids) == len(set(nids))
                    and all(nid in nodes for nid in nids),
                    "INVALID_BOUNDED_CELL_NODE_SET",
                )
                require(
                    all(
                        not nodes[nid]["terminal"]
                        and nodes[nid].get("reason")
                        != "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT"
                        for nid in nids
                    ),
                    "CELL_CONTAINS_A_REAL_TERMINAL_OR_INPUT_BOUNDARY",
                )
                internal = sorted(
                    eid for eid, e in edges.items() if set(e["nodes"]) <= set(nids)
                )
                core = set().union(
                    *(set(map(_point, nodes[n]["source_core_points"])) for n in nids)
                )
                for eid in internal:
                    core.update(map(_point, edges[eid]["source_points"]))
                require(
                    all(
                        sorted(map(tuple, nodes[n]["all_ports"]))
                        == sorted(graph_ports[n])
                        for n in nids
                    ),
                    "RAW_CELL_PORTS_DO_NOT_INCLUDE_ALL_ACTUAL_GRAPH_EDGE_ENDS",
                )
                external = sorted(
                    p for n in nids for p in graph_ports[n] if p[0] not in internal
                )
                require(
                    len(external) == 2 and external[0][0] != external[1][0],
                    "CELL_HAS_OTHER_EXTERNAL_PORT_OR_SAME_EXTERNAL_EDGE",
                )
                require(
                    sorted(map(tuple, cert["external_ports"]))
                    == external
                    == sorted(map(tuple, cert["all_ports"])),
                    "CELL_EXTERNAL_PORTS_NOT_COMPLETE",
                )
                require(
                    internal == sorted(cert["internal_source_graph_edge_ids"])
                    and set(internal) <= set(ev["source_graph_edge_ids"]),
                    "CELL_INTERNAL_SOURCE_GRAPH_EDGES_NOT_FULLY_OWNED",
                )
                require(
                    all(edges[eid]["length_px"] <= 12 for eid in internal),
                    "CELL_INTERNAL_EDGE_EXCEEDS_FROZEN_LIMIT",
                )
                require(
                    0 < len(core) <= 24
                    and core == set(map(_point, cert["source_core_points"])),
                    "CELL_SOURCE_PIXELS_NOT_EXACT_OR_OVER_BUDGET",
                )
                require(
                    max(
                        max(p[i] for p in core) - min(p[i] for p in core)
                        for i in (0, 1)
                    )
                    <= 6,
                    "CELL_EXTENT_EXCEEDS_FROZEN_LIMIT",
                )
                require(all(ink(p) for p in core), "CELL_CORE_IS_NOT_ORIGINAL_INK")
                adj = {p: set(_neighbors(p, skeleton)) & core for p in core}
                actual_edges = {_edge(p, q) for p, qs in adj.items() for q in qs}
                require(
                    actual_edges == {_edge(*e) for e in cert["source_core_edges"]}
                    and len(actual_edges) == len(core),
                    "CELL_SOURCE_ADJACENCIES_OR_SINGLE_CYCLE_NOT_EXACT",
                )
                reached, todo = {next(iter(core))}, [next(iter(core))]
                while todo:
                    for q in adj[todo.pop()] - reached:
                        reached.add(q)
                        todo.append(q)
                require(reached == core, "CELL_GRAPH_NOT_CONNECTED")
                ports = {
                    tuple(edges[eid]["source_points"][0 if end == 0 else -1])
                    for eid, end in external
                }
                require(
                    {p for p in core if len(adj[p]) == 1} == ports
                    and sum(len(adj[p]) == 3 for p in core) == 2
                    and all(len(adj[p]) in (1, 2, 3) for p in core),
                    "CELL_HAS_REAL_EXTRA_BRANCH_OR_COMPOSITE_PORT",
                )
                require(
                    all(
                        not (actual_edges & other)
                        for other_id, other in all_path_edges.items()
                        if other_id != oid
                    ),
                    "ANOTHER_SOURCE_OWNER_USES_THIS_CELL_EDGE",
                )
                candidates = cert["finite_cover_walks"]
                require(
                    len(candidates) == 2 and len({c["id"] for c in candidates}) == 2,
                    "CELL_DOES_NOT_RETAIN_TWO_FINITE_ENCODINGS",
                )
                repeated_arcs = []
                for candidate in candidates:
                    walk = [_point(p) for p in candidate["source_walk_points"]]
                    counts = _edges(walk)
                    declared = {
                        _edge(*r["source_edge"]): r
                        for r in candidate["source_edge_traversals"]
                    }
                    require(
                        len(walk) - 1 <= 64
                        and set(walk) == core
                        and set(counts) == actual_edges
                        and len(declared) == len(candidate["source_edge_traversals"]),
                        "FINITE_WALK_DOES_NOT_COVER_EXACT_SOURCE_CELL",
                    )
                    require(
                        {walk[0], walk[-1]} == ports,
                        "FINITE_WALK_DOES_NOT_JOIN_EXACT_EXTERNAL_PORTS",
                    )
                    require(
                        set(declared) == actual_edges
                        and all(
                            n in (1, 2)
                            and declared[e]["traversal_count"] == n
                            and declared[e]["owner_count"] == 1
                            for e, n in counts.items()
                        ),
                        "FINITE_WALK_EDGE_TRAVERSALS_NOT_EXACT",
                    )
                    repeated_arcs.append(
                        {e for e, count in counts.items() if count == 2}
                    )
                cycle = set(core)
                while True:
                    leaves = {p for p in cycle if len(adj[p] & cycle) == 1}
                    if not leaves:
                        break
                    cycle -= leaves
                cycle_edges = {e for e in actual_edges if set(e) <= cycle}
                require(
                    not repeated_arcs[0] & repeated_arcs[1]
                    and repeated_arcs[0] | repeated_arcs[1] == cycle_edges,
                    "TWO_FINITE_WALKS_DO_NOT_RETRACE_COMPLEMENTARY_CYCLE_ARCS",
                )
                selected = [
                    c for c in candidates if c["id"] == cert["selected_encoding_id"]
                ]
                require(len(selected) == 1, "SELECTED_ENCODING_NOT_UNIQUE")
                interval = crossing["protected_source_path_interval"]
                require(
                    len(interval) == 2
                    and all(isinstance(v, int) for v in interval)
                    and 0 <= interval[0] < interval[1] <= len(source_path),
                    "INVALID_PROTECTED_SOURCE_INTERVAL",
                )
                protected = source_path[interval[0] : interval[1]]
                require(
                    _same(protected, selected[0]["source_walk_points"])
                    or _same(protected, selected[0]["source_walk_points"][::-1]),
                    "PROTECTED_SOURCE_INTERVAL_IS_NOT_SELECTED_FULL_WALK",
                )
                matches = [
                    i
                    for i in range(len(native) - len(protected) + 1)
                    if _same(native[i : i + len(protected)], protected)
                ]
                require(
                    len(matches) == 1,
                    "PROTECTED_WALK_NOT_ONE_CONTIGUOUS_ACTUAL_VERTEX_RUN",
                )
                start = matches[0]
                segment_indices = set(range(start, start + len(protected) - 1))
                require(
                    not segment_indices & covered_indices,
                    "LOCAL_CERTIFICATES_OVERLAP_NATIVE_SEGMENT_INDICES",
                )
                covered_indices.update(segment_indices)
                local_indices = {}
                for offset, (a, b) in enumerate(zip(protected, protected[1:])):
                    local_indices.setdefault(_edge(a, b), []).append(start + offset)
                for edge, indices in local_indices.items():
                    if len(indices) == 2:
                        require(
                            edge not in expected_repeats,
                            "SOURCE_EDGE_RETRACE_CLAIMED_BY_TWO_CELLS",
                        )
                        expected_repeats[edge] = indices
                        object_allowances.append(
                            {
                                "handle": entity.dxf.handle,
                                "id": oid,
                                "cell_node_ids": nids,
                                "segment_indices": indices,
                                "source_edge": [list(p) for p in edge],
                                "source_owner_count": 1,
                                "actual_traversal_count": 2,
                            }
                        )
                hole = cert["original_source_hole_evidence"]
                expected_bounds = [
                    int(min(p[0] for p in core)) - 1,
                    int(min(p[1] for p in core)) - 1,
                    int(max(p[0] for p in core)) + 2,
                    int(max(p[1] for p in core)) + 2,
                ]
                require(
                    hole["neighborhood_xyxy_px"] == expected_bounds,
                    "WHITE_SOURCE_NEIGHBORHOOD_NOT_BOUND_TO_CELL",
                )
                lx, ly, hx, hy = expected_bounds
                require(
                    0 <= lx < hx <= gray.shape[1] and 0 <= ly < hy <= gray.shape[0],
                    "WHITE_NEIGHBORHOOD_OUTSIDE_ORIGINAL_IMAGE",
                )
                neighborhood = {(x, y) for y in range(ly, hy) for x in range(lx, hx)}
                actual_ink = {p for p in neighborhood if ink(p)}
                actual_white = neighborhood - actual_ink
                require(
                    actual_ink == set(map(_point, hole["source_ink_points"])),
                    "SOURCE_NEIGHBORHOOD_INK_MISMATCH",
                )
                raw = bytes(
                    int((x, y) in actual_ink)
                    for y in range(ly, hy)
                    for x in range(lx, hx)
                )
                require(
                    hashlib.sha256(raw).hexdigest()
                    == hole["thresholded_source_neighborhood_sha256"],
                    "WHITE_NEIGHBORHOOD_HASH_MISMATCH",
                )

                def boundary(points):
                    return {
                        p
                        for p in points
                        if p[0] in (lx, hx - 1) or p[1] in (ly, hy - 1)
                    }

                remaining, holes = set(actual_white), []
                while remaining:
                    component = _component(next(iter(remaining)), remaining, 4)
                    remaining -= component
                    if not boundary(component):
                        holes.append(component)
                white = set(map(_point, hole["enclosed_white_hole_points"]))
                require(
                    hole["white_hole_connectivity"] == 4
                    and len(holes) == 1
                    and white == holes[0],
                    "ACTUAL_FOUR_CONNECTED_WHITE_REGION_MISMATCH",
                )
                eight = _component(next(iter(white)), actual_white, 8)
                contacts = boundary(eight)
                diagonals = {
                    (p, (p[0] + dx, p[1] + dy))
                    for p in white
                    for dx in (-1, 1)
                    for dy in (-1, 1)
                    if (p[0] + dx, p[1] + dy) in actual_white - white
                }
                require(
                    set(map(_point, hole["white_eight_reachable_points"])) == eight
                    and set(
                        map(_point, hole["white_eight_neighborhood_boundary_contacts"])
                    )
                    == contacts,
                    "ACTUAL_EIGHT_CONNECTED_WHITE_REGION_MISMATCH",
                )
                require(
                    hole["white_eight_connected_to_neighborhood_boundary"]
                    == bool(contacts)
                    and hole["eight_neighbor_enclosed_hole_claimed"]
                    == (not bool(contacts))
                    and hole["white_diagonal_contacts_removed"] is False
                    and {
                        (_point(r["inside"]), _point(r["outside"]))
                        for r in hole[
                            "white_diagonal_contacts_outside_four_neighbor_hole"
                        ]
                    }
                    == diagonals,
                    "ACTUAL_WHITE_DIAGONAL_CONTACT_EVIDENCE_MISMATCH",
                )
                clearance = min(
                    _distance(p, a, b)
                    for p in white
                    for a, b in zip(native, native[1:])
                )
                require(
                    clearance >= 0.5 - EPS,
                    "ACTUAL_NATIVE_GEOMETRY_CONSUMES_LOCAL_WHITE_REGION",
                )
                result["cells"].append(
                    {
                        "cell_node_ids": nids,
                        "actual_protected_vertex_interval": [
                            start,
                            start + len(protected),
                        ],
                        "source_edge_count": len(actual_edges),
                        "actual_white_minimum_clearance_px": clearance,
                        "white_eight_connected_to_exterior": bool(contacts),
                        "pass": True,
                    }
                )
            # Match all actual repetitions, not merely those inside a good
            # certificate.  Moving a repeat elsewhere or adding a third visit
            # invalidates the whole object's exemption.
            actual_indices = {}
            for index, (a, b) in enumerate(zip(native, native[1:])):
                key = _edge(np.round(a, 7), np.round(b, 7))
                actual_indices.setdefault(key, []).append(index)
            repeated = {
                edge: indices
                for edge, indices in actual_indices.items()
                if len(indices) > 1
            }
            require(
                repeated == expected_repeats,
                "ACTUAL_NATIVE_RETRACE_POSITIONS_OR_MULTIPLICITIES_NOT_EXACT",
            )
            result["pass"] = True
            report["allowances"].extend(object_allowances)
        except (
            KeyError,
            TypeError,
            ValueError,
            IndexError,
            ArithmeticError,
            AttributeError,
        ) as exc:
            result["failures"].append(str(exc))
        report["object_checks"].append(result)
    report["evidence_status"] = (
        "COMPLETE_COLD_PROOF"
        if all(r["pass"] for r in report["object_checks"])
        else "LOCAL_RETRACE_PROOF_FAILED"
    )
    return report
