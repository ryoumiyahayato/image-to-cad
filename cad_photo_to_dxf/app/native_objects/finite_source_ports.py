"""Source-bound finite portions of unchanged prior native objects.

The whole object and its historical source identity remain in every receipt.
Only a finite, independently reconstructed source arm is admitted to a local
component.  This module neither changes CAD nor renews a whole-object verdict.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import itertools
import json
import math

import numpy as np

from . import attached_stroke_component as component
from . import attached_stroke_width_exact as exact
from .finite_component_saved_reader import exact_points

SCHEMA = "independent-necessary-prior-finite-port-v1"
DOMAIN_SCHEMA = "target-and-complete-read-influence-domain-v1"
ROLE = "NECESSARY_PRIOR_FINITE_PORT"
F = Fraction
POLICY = {"maximum_continuation_px": 240, "maximum_normal_half_span_px": 12,
          "same_arm_exit_chord_px": 4, "source_distance_squared_px": 4,
          "maximum_port_pieces": 64, "maximum_domain_cells": 262144,
          "source_threshold": 128, "source_geometry_mutated": False}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _enc(point):
    return [exact.encode_rational(v) for v in point]


def _dec(point):
    return tuple(exact.decode_rational(v) for v in point)


def _points(row):
    return exact_points(row) if "points_exact" in row else component._points(row)


def _geometry_record(row):
    points = _points(row)
    oid = row.get("object_id", row.get("stroke_id"))
    return {"stroke_id": oid, "representation": {"points": [[float(v) for v in p] for p in points],
            "bulges": [0.] * len(points), "closed": False}, "representation_exact_points": [_enc(p) for p in points]}


def prior_source_points(prior_object):
    """Read known native schemas without rewriting the complete old binding."""
    geometry = prior_object["geometry"]
    if "points" in geometry:
        values = geometry["points"]
    elif (prior_object.get("kind") in ("LINE", "WALL_SEGMENT") and
          "start" in geometry and "end" in geometry and not geometry.get("members")):
        values = [geometry["start"], geometry["end"]]
    else:
        raise ValueError("PRIOR_HAS_NO_SUPPORTED_COMPLETE_NATIVE_ENDPOINT_OR_POLYLINE_SCHEMA")
    points = [tuple(exact.rational(v) for v in p) for p in values]
    if (geometry.get("closed") or any(geometry.get("bulges", [])) or len(points) < 2
            or any(len(p) != 2 for p in points) or any(a == b for a, b in itertools.pairwise(points))):
        raise ValueError("PRIOR_PORT_REQUIRES_OPEN_STRAIGHT_NATIVE_POLYLINE")
    return points


def prior_source_geometry_row(prior_object):
    """Source-stage geometry only; it never claims that a DXF was cold-read."""
    geometry = prior_object["geometry"]
    points = prior_source_points(prior_object)
    xs, ys = zip(*points)
    return {"object_id": prior_object["id"], "parent_object_id": prior_object["id"],
        "kind": prior_object["kind"], "points": [[float(v) for v in p] for p in points],
        "points_exact": [[[v.numerator, v.denominator] for v in p] for p in points],
        "bulges": list(geometry.get("bulges", [0.] * len(points))), "closed": False,
        "bbox_xyxy": list(map(float, (min(xs), min(ys), max(xs), max(ys)))),
        "geometry_supported": True, "actual_saved_geometry": False, "geometry_origin": "SOURCE_STAGE"}


def _runs(cells):
    result = []
    for y, rows in itertools.groupby(sorted(set((int(y), int(x)) for x, y in cells)), key=lambda p: p[0]):
        xs = [p[1] for p in rows]
        start = end = xs[0]
        for x in xs[1:]:
            if x != end + 1:
                result.append([y, start, end + 1])
                start = x
            end = x
        result.append([y, start, end + 1])
    return result


def cells_from_runs(runs):
    return {(x, y) for y, x0, x1 in runs for x in range(x0, x1)}


def _canonical_window(source, targets):
    points = [p for row in targets for p in _points(row)]
    if not points:
        raise ValueError("INFLUENCE_DOMAIN_REQUIRES_COMPLETE_TARGET_GEOMETRY")
    border = component.POLICY["window_border_px"]
    return [max(0, math.floor(min(p[0] for p in points)) - border),
            max(0, math.floor(min(p[1] for p in points)) - border),
            min(source.shape[1], math.ceil(max(p[0] for p in points)) + border + 1),
            min(source.shape[0], math.ceil(max(p[1] for p in points)) + border + 1)]


def build_influence_domain(source, graph, target_rows, model_window):
    """Freeze geometry, every endpoint direction, and every proof read branch.

    Corridor cells conservatively intersect the finite rotated rectangle. The
    integer cell footprint affects scope only, never an ink/geometry tolerance.
    """
    from .finite_component_source_audit import _direction_table_v2
    targets = [_geometry_record(row) for row in target_rows]
    required, window = _canonical_window(source, targets), list(map(int, model_window))
    if (len(window) != 4 or window[0] > required[0] or window[1] > required[1] or
            window[2] < required[2] or window[3] < required[3]):
        raise ValueError("INFLUENCE_WINDOW_OMITS_TARGET_LENGTH_CAP_OR_NORMAL_DOMAIN")
    if not (0 <= window[0] < window[2] <= source.shape[1] and 0 <= window[1] < window[3] <= source.shape[0]):
        raise ValueError("INFLUENCE_WINDOW_OUTSIDE_ORIGINAL_SOURCE")
    if (window[2] - window[0]) * (window[3] - window[1]) > POLICY["maximum_domain_cells"]:
        raise ValueError("INFLUENCE_WINDOW_RESOURCE_BOUND")
    rays, nodes, tables = [], set(), {}
    for row in targets:
        for endpoint in (_points(row)[0], _points(row)[-1]):
            for nid, node in sorted(graph.nodes.items()):
                points = np.asarray(graph.xy(node["pixels"]), int)
                if (points[:, 0].min() > endpoint[0] + 2 or points[:, 0].max() < endpoint[0] - 2 or
                        points[:, 1].min() > endpoint[1] + 2 or points[:, 1].max() < endpoint[1] - 2):
                    continue
                if not any(exact.squared_distance(endpoint, tuple(map(int, p))) <= 4 for p in points):
                    continue
                nodes.add(nid)
                if nid not in tables:
                    tables[nid] = _direction_table_v2(graph, nid)
                for port in sorted(node["edges"]):
                    for observation in component.source_observations(graph, port):
                        start, end = observation["source_points_px"][0], observation["source_points_px"][-1]
                        vector = tuple(int(b - a) for a, b in zip(start, end))
                        if not any(vector):
                            continue
                        # Both signs are predeclared: existing source arms and
                        # the observable continuation of an arriving target.
                        for sign in (-1, 1):
                            rays.append({"origin_exact": _enc(endpoint), "vector": [sign * v for v in vector],
                                "source_node_id": nid, "source_port": list(port),
                                "requested_span_px": observation["requested_span_px"]})
    unique = {_digest(ray): ray for ray in rays}
    read_pixels = {tuple(p) for table in tables.values() for p in table["evidence_read_pixels_px"]}
    if len(read_pixels) > POLICY["maximum_domain_cells"]:
        raise ValueError("COMPLETE_DIRECTION_READ_DOMAIN_RESOURCE_BOUND")
    domain = {"schema": DOMAIN_SCHEMA, "policy": dict(POLICY), "model_window": window,
        "required_target_window": required, "target_geometry": targets,
        "target_geometry_sha256": _digest(targets), "source_shape": list(source.shape),
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "continuation_corridors": [unique[k] for k in sorted(unique)],
        "endpoint_source_node_ids": sorted(nodes),
        "direction_read_cells_y_x0_x1": _runs(read_pixels),
        "direction_receipts": [tables[n] for n in sorted(tables)],
        "failure_based_domain_shrink": False,
        "all_failed_short_truncated_direction_reads_retained": True}
    domain["domain_sha256"] = _digest(domain)
    return domain


def _domain_contains_cell(domain, cell, read_cells=None):
    x, y = cell
    x0, y0, x1, y1 = domain["model_window"]
    if x0 <= x < x1 and y0 <= y < y1:
        return True
    if read_cells is None:
        read_cells = cells_from_runs(domain["direction_read_cells_y_x0_x1"])
    if cell in read_cells:
        return True
    for ray in domain["continuation_corridors"]:
        origin, vector = _dec(ray["origin_exact"]), ray["vector"]
        dx, dy = F(x) - origin[0], F(y) - origin[1]
        dot, cross = dx * vector[0] + dy * vector[1], dx * vector[1] - dy * vector[0]
        half_projection, norm2 = F(abs(vector[0]) + abs(vector[1]), 2), sum(v * v for v in vector)
        if (dot + half_projection >= 0 and max(F(0), dot - half_projection) ** 2 <= 240 ** 2 * norm2
                and max(F(0), abs(cross) - half_projection) ** 2 <= 12 ** 2 * norm2):
            return True
    return False


def _clip_geometry(points, domain):
    from .finite_component_source_audit import _raster_intervals
    groups, current, ranges, reads = [], [], [], cells_from_runs(domain["direction_read_cells_y_x0_x1"])
    for index, (a, b) in enumerate(itertools.pairwise(points)):
        intervals, _ = _raster_intervals(a, b)
        accepted = []
        for lo, hi, cells in intervals:
            if any(_domain_contains_cell(domain, tuple(c), reads) for c in cells):
                if accepted and accepted[-1][1] == lo:
                    accepted[-1] = accepted[-1][0], hi
                else:
                    accepted.append((lo, hi))
        for lo, hi in accepted:
            start = tuple(u + lo * (v - u) for u, v in zip(a, b))
            end = tuple(u + hi * (v - u) for u, v in zip(a, b))
            if current and current[-1] != start:
                groups.append((current, ranges))
                current, ranges = [], []
            if not current:
                current.append(start)
            current.append(end)
            ranges.append({"native_segment_index": index, "parameter_start": exact.encode_rational(lo),
                           "parameter_end": exact.encode_rational(hi)})
        if not accepted or accepted[-1][1] != 1:
            if current:
                groups.append((current, ranges))
                current, ranges = [], []
    if current:
        groups.append((current, ranges))
    return groups


def _prior_binding(source, saved_row, prior_object, roi, dpi):
    failures = []
    if saved_row.get("parent_object_id", saved_row.get("object_id")) != prior_object.get("id"):
        failures.append("COMPLETE_PRIOR_OBJECT_ID_MISMATCH")
    source_points = prior_source_points(prior_object)
    if saved_row.get("actual_saved_geometry"):
        expected_kind = "LWPOLYLINE" if "points" in prior_object["geometry"] else "LINE"
        if (saved_row.get("kind") != expected_kind or saved_row.get("closed") or any(saved_row.get("bulges", []))
                or saved_row.get("constant_width") or any(any(w) for w in saved_row.get("widths", []))):
            failures.append("COMPLETE_PRIOR_NATIVE_TYPE_OR_FINITE_SEGMENT_REPRESENTATION_CHANGED")
        scale = 25.4 / float(dpi)
        expected = [(F((float(x) - roi[0]) * scale), F((roi[3] - float(y)) * scale)) for x, y in source_points]
        actual = [tuple(F(*v) for v in p) for p in saved_row.get("native_mm_points_exact", [])]
        if expected != actual:
            failures.append("COMPLETE_SAVED_PRIOR_NATIVE_MM_GEOMETRY_CHANGED")
        transformed = [(x / F(scale) + roi[0], roi[3] - y / F(scale)) for x, y in actual]
        if _points(saved_row) != transformed:
            failures.append("SAVED_PRIOR_SOURCE_COORDINATES_DO_NOT_MATCH_ACTUAL_MM_TRANSFORM")
    elif saved_row.get("geometry_origin") != "SOURCE_STAGE" or _points(saved_row) != source_points:
        failures.append("COMPLETE_PRIOR_SOURCE_STAGE_GEOMETRY_CHANGED")
    evidence = prior_object.get("source_evidence", {})
    box = evidence.get("original_source_crop_xyxy_px", [])
    if evidence.get("source_pixels_modified") is not False or len(box) != 4:
        failures.append("COMPLETE_PRIOR_SOURCE_IDENTITY_MISSING")
    else:
        x0, y0, x1, y1 = map(int, box)
        if not (0 <= x0 < x1 <= source.shape[1] and 0 <= y0 < y1 <= source.shape[0]):
            failures.append("PRIOR_SOURCE_CROP_OUTSIDE_IMAGE")
        elif hashlib.sha256(source[y0:y1, x0:x1].tobytes()).hexdigest() != evidence.get("original_source_crop_array_sha256"):
            failures.append("PRIOR_SOURCE_CROP_HASH_MISMATCH")
    raw = evidence.get("source_path_points", [])
    if len(raw) < 2 or any(any(F(v).denominator != 1 for v in p) for p in raw):
        failures.append("PRIOR_ORIGINAL_SOURCE_ARM_IDENTITY_MISSING")
    return {"pass": not failures, "reasons": failures, "prior_binding_sha256": _digest(prior_object),
            "complete_geometry_sha256": _digest(saved_row), "source_path_locator_sha256": _digest(raw)}


def _source_route(source, graph, native, prior_object, domain, full_native=None, read_receipt=None):
    from .finite_component_source_audit import _core_walks, _direction_table_v2, _core_evidence_v2
    original = {tuple(map(int, p)) for p in prior_object["source_evidence"]["source_path_points"]}
    full_native = full_native or prior_source_points(prior_object)
    prepared = exact.prepare_polyline(native)
    x, y = zip(*native)
    box = min(x) - 2, min(y) - 2, max(x) + 2, max(y) + 2
    pieces, read_cells = [], set()
    read_receipt = {} if read_receipt is None else read_receipt
    read_receipt.update(core_direction_attempts=[], candidate_subranges=[])
    domain_reads = cells_from_runs(domain["direction_read_cells_y_x0_x1"])
    for eid, edge in enumerate(graph.edges):
        points = [tuple(map(int, p)) for p in graph.xy(edge["pixels"])]
        if not any(box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3] for p in points):
            continue
        active = [i for i, p in enumerate(points) if p in original and
                  _domain_contains_cell(domain, p, domain_reads) and
                  exact.point_polyline_distance_squared(p, prepared) <= 4]
        for _, values in itertools.groupby(enumerate(active), key=lambda item: item[1] - item[0]):
            indices = [v for _, v in values]
            if len(indices) < 2:
                continue
            lo, hi = indices[0], indices[-1]
            keys = [edge["nodes"][0] if lo == 0 else (eid, lo),
                    edge["nodes"][1] if hi == len(points) - 1 else (eid, hi)]
            pieces.append({"edge_id": eid, "start_index": lo, "end_index": hi, "keys": keys,
                           "source_points_px": [list(p) for p in points[lo:hi + 1]]})
    read_receipt["candidate_subranges"] = [{k: p[k] for k in ("edge_id", "start_index", "end_index", "source_points_px")} for p in pieces]
    if not pieces or len(pieces) > POLICY["maximum_port_pieces"]:
        raise ValueError("FINITE_PRIOR_ROUTE_MISSING_OR_RESOURCE_BOUND")
    incidence = {}
    for i, piece in enumerate(pieces):
        for end, key in enumerate(piece["keys"]):
            incidence.setdefault(key, []).append((i, end))
    ends = [k for k, ports in incidence.items() if len(ports) == 1]
    if len(ends) != 2 or any(len(ports) > 2 for ports in incidence.values()):
        raise ValueError("FINITE_PRIOR_ROUTE_BRANCHES_OR_CLOSES")
    def key_point(key):
        i, end = incidence[key][0]
        return pieces[i]["source_points_px"][0 if end == 0 else -1]
    current = min(ends, key=lambda key: exact.squared_distance(native[0], key_point(key)))
    start, remaining, raw, subranges, nodes, cores = current, set(range(len(pieces))), [], [], [current], []
    while remaining:
        choices = [(i, end) for i, end in incidence[current] if i in remaining]
        if len(choices) != 1:
            raise ValueError("FINITE_PRIOR_ROUTE_DISCONNECTED")
        i, orientation = choices[0]
        remaining.remove(i)
        piece = pieces[i]
        part = list(graph.edges[piece["edge_id"]]["pixels"][piece["start_index"]:piece["end_index"] + 1])
        if orientation:
            part.reverse()
        if raw:
            if not isinstance(current, int):
                raise ValueError("FINITE_PRIOR_ROUTE_UNEXPECTED_PARTIAL_EDGE_JOIN")
            walks = _core_walks(graph, current, raw[-1], part[0])
            if any(exact.point_polyline_distance_squared(tuple(map(int, p)), prepared) > 4
                   for walk in walks for p in graph.xy(walk)):
                raise ValueError("FINITE_PRIOR_CORE_ENCODINGS_DISAGREE_WITH_ACTUAL_GEOMETRY")
            table = _direction_table_v2(graph, current)
            involved = {pieces[j]["edge_id"] for j, _ in incidence[current]}
            pair = next((p for p in table["pairs"] if {q[0] for q in p["ports"]} == involved), None)
            core = _core_evidence_v2(source, graph, current, table)
            read_cells.update(tuple(p) for p in table["evidence_read_pixels_px"])
            x0, y0, x1, y1 = core["raw_box_xyxy_px"]
            read_cells.update((x, y) for y in range(y0, y1) for x in range(x0, x1))
            read_receipt["core_direction_attempts"].append({"node_id": current, "core": core,
                "selected_pair": pair, "all_walks_px": [np.asarray(graph.xy(walk), int).tolist() for walk in walks]})
            read_receipt["all_route_read_cells_y_x0_x1"] = _runs(read_cells)
            if not pair or not pair["pass"] or not core["pass"]:
                raise ValueError("FINITE_PRIOR_CORE_OR_COMPLETE_DIRECTION_COMPETITION_PENDING")
            cores.append({"node_id": current, "core": core, "all_walks_px":
                          [np.asarray(graph.xy(walk), int).tolist() for walk in walks]})
            raw.extend(walks[0][1:])
            raw.extend(part[1:])
        else:
            raw = part
        subranges.append({k: piece[k] for k in ("edge_id", "start_index", "end_index")})
        subranges[-1]["orientation"] = orientation
        current = piece["keys"][1 - orientation]
        nodes.append(current)
    endpoint_evidence = []
    for end, key in enumerate((start, current)):
        point = native[0 if end == 0 else -1]
        i, _ = incidence[key][0]
        piece, guard = pieces[i], []
        if isinstance(key, tuple):
            eid, index = key
            points = [tuple(map(int, p)) for p in graph.xy(graph.edges[eid]["pixels"])]
            distances = [[j for j in range(index - 1, -1, -1)
                          if exact.squared_distance(points[j], points[index]) >= 16],
                         [j for j in range(index + 1, len(points))
                          if exact.squared_distance(points[j], points[index]) >= 16]]
            if not all(distances):
                raise ValueError("FINITE_PRIOR_SCOPE_EXIT_LACKS_BOTH_FOUR_PIXEL_SOURCE_ARMS")
            lo, hi = distances[0][0], distances[1][0]
            guard = points[lo:hi + 1]
            if any(p not in original or source[p[1], p[0]] >= 128 or
                   exact.point_polyline_distance_squared(p, full_native) > 4 for p in guard):
                raise ValueError("FINITE_PRIOR_SCOPE_EXIT_IS_NOT_THE_SAME_BOUND_SOURCE_ARM")
            read_cells.update(guard)
            endpoint_evidence.append({"node_id": None, "kind": "FINITE_PRIOR_SCOPE_EXIT",
                "source_edge_id": eid, "source_index": index,
                "entry_or_exit": "ENTRY" if end == 0 else "EXIT",
                "both_sides_source_points_px": [list(p) for p in guard],
                "guard_start_index": lo, "guard_end_index": hi, "actual_finite_endpoint_exact": _enc(point)})
        else:
            true_terminal = point == full_native[0] or point == full_native[-1]
            if not true_terminal:
                raise ValueError("FINITE_PRIOR_SCOPE_EXIT_AT_CORE_NEEDS_TWO_SIDED_SOURCE_CONTINUATION")
            endpoint_evidence.append({"node_id": key, "kind": "BOUND_ORIGINAL_PRIOR_OBJECT_TERMINAL",
                "port": [piece["edge_id"], 0 if piece["keys"][0] == key else 1],
                "new_free_cap_claimed": False, "actual_finite_endpoint_exact": _enc(point)})
    source_path = np.asarray(graph.xy(raw), int).tolist()
    read_cells.update(tuple(p) for p in source_path)
    return {"source_graph_edge_ids": list(dict.fromkeys(p["edge_id"] for p in subranges)),
        "source_edge_subranges": subranges, "source_node_ids": [n if isinstance(n, int) else None for n in nodes],
        "source_path_px": source_path, "endpoint_evidence": endpoint_evidence,
        "independent_core_walks": cores, "route_read_cells_y_x0_x1": _runs(read_cells)}


def _subrange_observations(graph, subrange, end):
    edge = graph.edges[subrange["edge_id"]]
    pixels = np.asarray(graph.xy(edge["pixels"][subrange["start_index"]:subrange["end_index"] + 1]), int)
    if end:
        pixels = pixels[::-1]
    steps = np.abs(np.diff(pixels, axis=0))
    if len(pixels) < 2 or np.any(steps.max(axis=1) != 1):
        raise ValueError("FINITE_PORT_SUBRANGE_IS_NOT_ORIGINAL_EIGHT_CONNECTED_SOURCE")
    diagonal = np.r_[0, np.cumsum(steps.sum(axis=1) == 2)]
    axial = np.arange(len(pixels)) - diagonal
    for span in component.POLICY["source_direction_spans_px"]:
        index = next((i for i in range(1, len(pixels)) if component._length_reached(
            int(axial[i]), int(diagonal[i]), span)), len(pixels) - 1)
        delta = pixels[index] - pixels[0]
        yield {"requested_span_px": span, "source_points_px": pixels[:index + 1].tolist(),
               "source_chord_squared_px": int(delta @ delta), "stopped_at_finite_source_subrange": index == len(pixels) - 1}


def measure_finite_port_sections(source, graph, row, all_rows, *, forbidden_core_cells=()):
    native, records, seen = component._points(row), [], set()
    context = [other for other in all_rows if other["stroke_id"] != row["stroke_id"]]
    curves = [other for other in context if other.get("curve_type", other.get("kind")) == "CIRCLE"]
    others = [component._points(other) for other in context if other not in curves]
    for subrange in row["source_edge_subranges"]:
        for end in (0, 1):
            for observation in _subrange_observations(graph, subrange, end):
                _, index, fraction, q = exact.project_point_polyline(observation["source_points_px"][-1], native)
                item = {"source_edge_subrange": subrange, "port": [subrange["edge_id"], end],
                    "observation": observation, "native_segment_index": index,
                    "projection_fraction": exact.encode_rational(fraction)}
                if observation["source_chord_squared_px"] < 16:
                    item.update({"pass": False, "constraint_eligible": False, "reason": "SOURCE_DIRECTION_CHORD_TOO_SHORT"})
                elif not 0 < fraction < 1:
                    item.update({"pass": False, "constraint_eligible": False, "reason": "NO_INTERIOR_FINITE_NORMAL_SECTION"})
                elif q in seen:
                    item.update({"pass": False, "constraint_eligible": False, "reason": "DUPLICATE_EXACT_SECTION_NOT_NEW_SUPPORT"})
                else:
                    seen.add(q)
                    a, b = native[index], native[index + 1]
                    d = b[0] - a[0], b[1] - a[1]
                    self_axes = [[c, e] for j, (c, e) in enumerate(itertools.pairwise(native)) if j != index and
                        any(d[0] * (p[1] - a[1]) != d[1] * (p[0] - a[0]) for p in (c, e))]
                    item.update(exact.measure_section(source, q, a, b, other_paths=others + self_axes,
                        forbidden_core_cells=forbidden_core_cells, source_threshold=128, half_span=12))
                    if item.get("constraint_eligible") and curves:
                        from .finite_circle_source import circle_point_strictly_outside
                        upper = exact.decode_rational(item["half_width_squared_interval"]["upper"])
                        # This rational clearance is conservative for the old
                        # 2*sqrt(upper)+sqrt(1/2) independent-axis condition.
                        near = [curve["stroke_id"] for curve in curves if not
                                circle_point_strictly_outside(curve, q, 8 * upper + 1)]
                        item["interfering_actual_circle_ids"] = near
                        if near:
                            item.update({"pass": False, "constraint_eligible": False, "independent": False,
                                         "reason": "SECTION_NOT_INDEPENDENT_OF_ACTUAL_CIRCLE_AXIS"})
                records.append(item)
    result = exact.intersect_sections(records, min_sections=2)
    result.update(sections=records, every_finite_subrange_port_enumerated=True,
        selection_policy="ALL_FIXED_SOURCE_SPANS_BEFORE_INDEPENDENCE_AND_INTERVAL_INTERSECTION",
        native_geometry_sha256=_digest(_geometry_record(row)), complete_prior_width_reproved=False,
        evidence_read_cells_y_x0_x1=_runs(p for r in records for p in
            r.get("section_source_cells", r["observation"]["source_points_px"])))
    return result


def certify_finite_prior_port(source, graph, saved_row, prior_object, influence_domain, *, roi, dpi):
    from .finite_component_source_audit import _finite_support
    receipt = {"schema": SCHEMA, "policy": dict(POLICY), "pass": False, "rows": [], "failures": [],
        "whole_prior_object_reauthorized": False, "complete_saved_object_changed": False}
    try:
        binding = _prior_binding(source, saved_row, prior_object, roi, dpi)
        receipt["complete_identity_binding"] = binding
        if not binding["pass"]:
            receipt["failures"].extend(binding["reasons"])
            return receipt
        domain_hash = influence_domain["domain_sha256"]
        if _digest({k: v for k, v in influence_domain.items() if k != "domain_sha256"}) != domain_hash:
            raise ValueError("INFLUENCE_DOMAIN_HASH_MISMATCH")
        if influence_domain["source_array_sha256"] != hashlib.sha256(source.tobytes()).hexdigest():
            raise ValueError("INFLUENCE_DOMAIN_SOURCE_IDENTITY_CHANGED")
        full_support = _finite_support(source, saved_row)
        receipt["original_whole_prior_support"] = full_support
        receipt["finite_route_read_attempts"] = []
        groups = _clip_geometry(_points(saved_row), influence_domain)
        if not groups:
            raise ValueError("PRIOR_HAS_NO_FINITE_GEOMETRY_IN_DECLARED_INFLUENCE_DOMAIN")
        for index, (points, native_ranges) in enumerate(groups):
            oid = saved_row["object_id"] + "/finite-port:" + str(index)
            row = {"stroke_id": oid, "parent_object_id": saved_row["parent_object_id"], "body_role": ROLE,
                "representation": {"points": [[float(v) for v in p] for p in points], "bulges": [0.] * len(points), "closed": False},
                "representation_exact_points": [_enc(p) for p in points], "native_segment_subranges": native_ranges,
                "full_saved_geometry": deepcopy(saved_row), "full_saved_geometry_sha256": binding["complete_geometry_sha256"],
                "prior_binding": deepcopy(prior_object), "prior_binding_sha256": binding["prior_binding_sha256"],
                "influence_domain": influence_domain, "influence_domain_sha256": domain_hash,
                "coordinate_frame": {"roi": list(roi), "dpi": dpi}}
            read_attempt = {"stroke_id": oid}
            receipt["finite_route_read_attempts"].append(read_attempt)
            row.update(_source_route(source, graph, points, prior_object, influence_domain,
                                     _points(saved_row), read_attempt))
            finite_saved = {"object_id": oid, "points_exact":
                [[[v.numerator, v.denominator] for v in p] for p in points]}
            support = _finite_support(source, finite_saved)
            row["finite_positive_length_source_support"] = support
            if not support["pass"]:
                receipt["failures"].append("FINITE_PRIOR_HAS_POSITIVE_WHITE_OR_OUTSIDE_INTERVAL")
            # Width is measured again with the caller's complete body inventory;
            # this preliminary receipt never authorizes omitted neighbor axes.
            preliminary = measure_finite_port_sections(source, graph, row,
                [row] + influence_domain["target_geometry"])
            row["independent_sections"] = preliminary["sections"]
            row["width_requires_complete_context_remeasurement"] = True
            reads = cells_from_runs(row["route_read_cells_y_x0_x1"]) | cells_from_runs(preliminary["evidence_read_cells_y_x0_x1"])
            reads |= cells_from_runs(influence_domain["direction_read_cells_y_x0_x1"])
            row["complete_evidence_read_cells_y_x0_x1"] = _runs(reads)
            row["finite_port_certificate"] = {"schema": SCHEMA, "full_saved_geometry_sha256": binding["complete_geometry_sha256"],
                "prior_binding_sha256": binding["prior_binding_sha256"], "influence_domain_sha256": domain_hash,
                "source_array_sha256": influence_domain["source_array_sha256"],
                "source_arm_sha256": _digest({k: row[k] for k in ("source_edge_subranges", "source_path_px", "endpoint_evidence")})}
            receipt["rows"].append(row)
        active_reads = set().union(*(cells_from_runs(r["complete_evidence_read_cells_y_x0_x1"]) for r in receipt["rows"]))
        excluded = []
        for finding in full_support["uncovered_positive_intervals"]:
            cells = [tuple(p) for p in finding["white_cells"]]
            affected = any(p in active_reads or _domain_contains_cell(influence_domain, p) for p in cells)
            if affected:
                receipt["failures"].append("PRIOR_FAILURE_INTERSECTS_ACTUALLY_USED_EVIDENCE_DOMAIN")
            else:
                excluded.append({**finding, "exclusion": "OUTSIDE_TARGET_CONTINUATION_AND_ALL_ACTUAL_EVIDENCE_READS"})
        receipt.update(excluded_remote_findings=excluded, original_whole_prior_support=full_support,
            finite_port_count=len(receipt["rows"]), pass_=not receipt["failures"])
        receipt["pass"] = receipt.pop("pass_")
        for row in receipt["rows"]:
            row["excluded_remote_findings"] = excluded
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        receipt["failures"].append(str(exc))
    receipt["status"] = "FINITE_PRIOR_SOURCE_PORTS_ESTABLISHED" if receipt["pass"] else "PENDING_FINITE_PRIOR_SOURCE_PORT"
    return receipt


def validate_finite_port_certificate(source, graph, row, *, prior_object=None, expected_influence_domain=None):
    """Recompute from source and full geometry; supplied PASS is never read."""
    try:
        if row.get("body_role") != ROLE:
            raise ValueError("WRONG_FINITE_PRIOR_BODY_TYPE")
        original = prior_object if prior_object is not None else row["prior_binding"]
        domain = row["influence_domain"]
        rebuilt = build_influence_domain(source, graph, domain["target_geometry"], domain["model_window"])
        if rebuilt != domain or (expected_influence_domain is not None and rebuilt != expected_influence_domain):
            raise ValueError("FINITE_PRIOR_INFLUENCE_DOMAIN_NOT_INDEPENDENTLY_REPRODUCED")
        frame = row["coordinate_frame"]
        result = certify_finite_prior_port(source, graph, row["full_saved_geometry"], original, rebuilt,
                                          roi=frame["roi"], dpi=frame["dpi"])
        fresh = next((r for r in result["rows"] if r["stroke_id"] == row["stroke_id"]), None)
        fields = ("representation", "representation_exact_points", "native_segment_subranges", "source_graph_edge_ids",
                  "source_edge_subranges", "source_path_px", "source_node_ids", "endpoint_evidence",
                  "full_saved_geometry_sha256", "prior_binding_sha256", "influence_domain_sha256",
                  "finite_port_certificate", "complete_evidence_read_cells_y_x0_x1")
        differences = [key for key in fields if fresh is None or fresh.get(key) != row.get(key)]
        return {"schema": SCHEMA, "pass": result["pass"] and not differences, "differences": differences,
                "fresh_failures": result["failures"], "producer_approval_consumed": False,
                "whole_prior_object_reauthorized": False}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return {"schema": SCHEMA, "pass": False, "reasons": [str(exc)], "producer_approval_consumed": False}
