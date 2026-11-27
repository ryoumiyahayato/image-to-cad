"""Whole finite source responsibility under a falsifiable constant-width model.

The graph planner discovers routes; this module never changes their geometry.
New distance, width and union decisions use exact rational squared distances.
An incompatible model is not a claim that the source drawing is ambiguous.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import label

from . import attached_stroke_ink as legacy_ink
from . import attached_stroke_width_exact as exact
from .contracts import stable_id


SCHEMA = "source-finite-component-responsibility-v1"
POLICY = {
    "version": "whole-source-chain-constant-width-exact-finite-union-v1",
    "source_threshold": 128,
    "source_direction_spans_px": [6, 8, 12],
    "minimum_source_direction_chord_px": 4,
    "minimum_independent_sections": 2,
    "maximum_section_half_span_px": 12,
    "window_border_px": 13,
    "maximum_target_extent_px": 240,
    "maximum_window_cells": 131072,
    "maximum_model_search_states": 8192,
    "maximum_extension_events": 512,
    "maximum_extension_px": 240,
    "width_parameter_scope": "ONE_CONSTANT_SQUARED_HALF_WIDTH_PER_COMPLETE_FINITE_POLYLINE",
    "pixel_model": "CLOSED_BLACK_CELL_INTERSECTION_AND_COMMON_STRICT_WHITE_NINE_POINT_WITNESS",
    "endpoint_convention": "OBSERVABLE_FINITE_HOST_INTERSECTION",
    "geometry_generated_or_modified": False,
    "physical_pen_history_identifiable": False,
    "unknown_neighbor_can_explain_ink": False,
    "diagnostic_float_values_authorize_decisions": False,
}


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _points(row):
    geometry = row.get("representation", row)
    points = geometry["points"]
    if geometry.get("closed") or any(geometry.get("bulges", [])) or len(points) < 2:
        raise ValueError("FINITE_COMPONENT_REQUIRES_OPEN_STRAIGHT_POLYLINE")
    result = ([tuple(exact.decode_rational(v) for v in p) for p in row["representation_exact_points"]]
              if "representation_exact_points" in row else
              [tuple(exact.rational(v) for v in p) for p in points])
    if len(result) != len(points) or any(len(p) != 2 or any(float(p[k]) != float(points[i][k]) for k in (0, 1))
                                        for i, p in enumerate(result)):
        raise ValueError("EXACT_FINITE_POINTS_DO_NOT_MATCH_ACTUAL_GEOMETRY_DISPLAY")
    if any(len(p) != 2 for p in result) or any(a == b for a, b in zip(result, result[1:])):
        raise ValueError("FINITE_COMPONENT_INVALID_FINITE_SEGMENT")
    return result


def _encoded_point(point):
    return [exact.encode_rational(v) for v in point]


def _interval(width):
    bounds = width["half_width_squared_interval"]
    return exact.decode_rational(bounds["lower"]), exact.decode_rational(bounds["upper"])


def _source_edges(points):
    return {frozenset((tuple(map(int, a)), tuple(map(int, b))))
            for a, b in zip(points, points[1:]) if not np.array_equal(a, b)}


def exact_centerline_source_support(source, points):
    cells = sorted({cell for a, b in zip(points, points[1:]) for cell in exact.segment_cells(a, b)})
    invalid = [list(cell) for cell in cells if not (0 <= cell[0] < source.shape[1]
               and 0 <= cell[1] < source.shape[0]
               and source[cell[1], cell[0]] < POLICY["source_threshold"])]
    return {"pass": not invalid, "closed_source_pixel_cells": [list(cell) for cell in cells],
            "white_or_unobserved_cells": invalid, "decision_arithmetic": "EXACT_CLOSED_SEGMENT_CELL_CLIPPING"}


def materialize_shared_vertices(source, graph, rows, cores):
    """Keep already source-proved junction points as exact new-host vertices.

    This implements the separately frozen shared-vertex amendment. It never
    changes a prior object, removes an original vertex, or moves a guest point.
    Every downstream source and native gate must run on the returned geometry.
    """
    original, result = deepcopy(rows), deepcopy(rows)
    receipt = {"schema": "source-supported-new-candidate-shared-vertex-construction-v1",
               "pass": False, "prior_objects_modified": False, "guest_endpoints_modified": False,
               "preconstruction_geometry": [{"stroke_id": row["stroke_id"], "representation": row["representation"]}
                                            for row in original], "attempts": [], "insertions": [], "failure_reasons": []}
    pending = {}
    maximum_change2 = exact.rational(legacy_ink.POLICY["native_coordinate_precision_px"]) ** 2
    try:
        affected_segments = set()
        for row in original:
            native = _points(row)
            for end_index, terminal in enumerate(row["endpoint_evidence"]):
                if "host_path_index" in terminal:
                    host_index = terminal["host_path_index"]
                    distance2, segment, _, _ = exact.project_point_polyline(
                        native[0 if end_index == 0 else -1], _points(original[host_index]))
                    if distance2:
                        affected_segments.add((host_index, segment))
        for row in original:
            native = _points(row)
            for end_index, terminal in enumerate(row["endpoint_evidence"]):
                if "host_path_index" not in terminal:
                    continue
                host_index, nid = terminal["host_path_index"], terminal["node_id"]
                host = original[host_index]
                if host.get("body_role") == "NECESSARY_PRIOR_FINITE_NEIGHBOR" or "prior_source_binding" in host:
                    raise ValueError("SHARED_VERTEX_MUST_NOT_MODIFY_PRIOR_NATIVE_BODY")
                point = native[0 if end_index == 0 else -1]
                distance2, segment, fraction, _ = exact.project_point_polyline(point, _points(host))
                if distance2 == 0 and ((host_index, segment) not in affected_segments or fraction in (0, 1)):
                    continue
                if (not cores.get(nid, {}).get("pass") or nid not in host["source_node_ids"]
                        or nid not in row["source_node_ids"]):
                    raise ValueError("SHARED_VERTEX_HAS_NO_INDEPENDENT_SAME_SOURCE_CORE")
                core = graph.xy(graph.nodes[nid]["pixels"])
                inside_core = any(all(abs(point[k] - int(pixel[k])) <= Fraction(1, 2) for k in (0, 1)) for pixel in core)
                receipt["attempts"].append({"guest_id": row["stroke_id"], "host_id": host["stroke_id"],
                    "source_node_id": nid, "point_exact": _encoded_point(point),
                    "inside_actual_original_core_cells": inside_core,
                    "actual_original_core_cells": core.tolist(), "preconstruction_squared_distance": exact.encode_rational(distance2),
                    "projection_parameter_exact": exact.encode_rational(fraction)})
                if not inside_core:
                    raise ValueError("SHARED_VERTEX_OUTSIDE_ORIGINAL_SOURCE_CORE_CELLS")
                if not 0 < fraction < 1:
                    raise ValueError("SHARED_VERTEX_WOULD_EXTEND_FINITE_HOST")
                if distance2 > maximum_change2:
                    raise ValueError("SHARED_VERTEX_EXCEEDS_EXISTING_CONSTRUCTION_PRECISION")
                item = {"guest_id_before": row["stroke_id"], "host_id_before": host["stroke_id"],
                        "host_index": host_index, "host_segment_index_before": segment,
                        "source_node_id": nid, "point": list(row["representation"]["points"][0 if end_index == 0 else -1]),
                        "point_exact": _encoded_point(point),
                        "projection_parameter_exact": exact.encode_rational(fraction),
                        "preconstruction_squared_distance": exact.encode_rational(distance2)}
                pending.setdefault((host_index, segment), []).append((fraction, point, item))
        for (host_index, segment), values in pending.items():
            ordered = sorted(values, key=lambda value: (value[0], value[1]))
            unique = []
            for value in ordered:
                if unique and value[0] == unique[-1][0] and value[1] != unique[-1][1]:
                    raise ValueError("SHARED_VERTICES_HAVE_COMPETING_EQUAL_PROJECTIONS")
                if not unique or value[:2] != unique[-1][:2]:
                    unique.append(value)
            pending[(host_index, segment)] = unique
        for index, row in enumerate(result):
            geometry = deepcopy(row["representation"])
            vertices = []
            for segment, point in enumerate(geometry["points"][:-1]):
                vertices.append(point)
                for _, _, item in pending.get((index, segment), []):
                    vertices.append(item["point"])
                    receipt["insertions"].append(item)
            vertices.append(geometry["points"][-1])
            if any(a == b for a, b in zip(vertices, vertices[1:])) or len(vertices) > 256:
                raise ValueError("SHARED_VERTEX_ZERO_LENGTH_OR_VERTEX_RESOURCE_BOUND")
            geometry.update(points=vertices, bulges=[0.0] * len(vertices))
            row["representation"] = geometry
            points = _points(row)
            support = exact_centerline_source_support(source, points)
            if not support["pass"]:
                receipt["construction_white_cells"] = support["white_or_unobserved_cells"]
                raise ValueError("SHARED_VERTEX_GEOMETRY_TOUCHES_ORIGINAL_WHITE_OR_UNOBSERVED_CELL")
            samples = list(row["source_path_px"])
            core_samples = []
            for core in row.get("core_route_alternatives", []):
                core_samples += [point for path in core["all_simple_core_routes_px"] for point in path]
            for terminal in row["endpoint_evidence"]:
                core_samples += [point for path in terminal.get("terminal_core_route_alternatives_px", []) for point in path]
            samples += core_samples
            if any(exact.point_polyline_distance_squared(point, points) > Fraction(9, 4) for point in samples):
                raise ValueError("SHARED_VERTEX_COMPLETE_SOURCE_FIT_NOT_ESTABLISHED")
            row["stroke_id"] = stable_id("GRAPHSTROKE", geometry)
            row["maximum_core_encoding_native_residual_px"] = math.sqrt(float(max(
                (exact.point_polyline_distance_squared(point, points) for point in core_samples), default=Fraction(0))))
        for row in result:
            row["native_endpoint_points_px"] = [row["representation"]["points"][0], row["representation"]["points"][-1]]
            for end_index, terminal in enumerate(row["endpoint_evidence"]):
                terminal["native_endpoint_px"] = row["representation"]["points"][0 if end_index == 0 else -1]
                if "host_path_index" not in terminal:
                    continue
                host = result[terminal["host_path_index"]]
                terminal["host_path_id"] = host["stroke_id"]
                _, index, fraction, _ = exact.project_point_polyline(terminal["native_endpoint_px"], _points(host))
                terminal["preconstruction_host_segment_index"] = terminal.get("host_segment_index")
                terminal["host_segment_index"] = index
                terminal["finite_host_fraction"] = float(fraction)
        receipt.update(pass_=True, original_host_vertices_retained=True,
                       downstream_complete_component_checks_required=True,
                       resulting_geometry=[{"stroke_id": row["stroke_id"], "representation": row["representation"]}
                                           for row in result],
                       changed_candidate_count=sum(a["representation"] != b["representation"]
                                                   for a, b in zip(original, result)))
        receipt["pass"] = receipt.pop("pass_")
        return result, receipt
    except (ValueError, KeyError, IndexError) as exc:
        receipt["failure_reasons"] = [str(exc)]
        return original, receipt


def _length_reached(axial, diagonal, requested):
    """Compare axial + diagonal*sqrt(2) >= integer requested exactly."""
    remainder = requested - axial
    return remainder <= 0 or 2 * diagonal * diagonal >= remainder * remainder


def source_observations(graph, port):
    """All predeclared observations; an 8-connected pixel chain has exact steps."""
    pixels = np.asarray(graph.xy(graph.oriented(tuple(port))), int)
    if len(pixels) < 2:
        return []
    steps = np.abs(np.diff(pixels, axis=0))
    if np.any(steps.max(axis=1) != 1):
        raise ValueError("SOURCE_PORT_IS_NOT_AN_ORIGINAL_EIGHT_CONNECTED_CHAIN")
    diagonal = np.r_[0, np.cumsum(steps.sum(axis=1) == 2)]
    axial = np.arange(len(pixels)) - diagonal
    results = []
    for span in POLICY["source_direction_spans_px"]:
        index = next((i for i in range(1, len(pixels))
                      if _length_reached(int(axial[i]), int(diagonal[i]), span)), len(pixels) - 1)
        delta = pixels[index] - pixels[0]
        chord2 = int(delta @ delta)
        results.append({"requested_span_px": span, "source_points_px": pixels[:index + 1].tolist(),
                        "source_chord_squared_px": chord2,
                        "source_chord_px_diagnostic": math.sqrt(chord2),
                        "axial_steps": int(axial[index]), "diagonal_steps": int(diagonal[index]),
                        "stopped_at_observed_graph_node": index == len(pixels) - 1})
    return results


def _chain_binding(source, graph, row):
    ids = list(row.get("source_graph_edge_ids", []))
    raw = np.asarray(row.get("source_path_px", []))
    reasons = []
    if not ids or len(set(ids)) != len(ids):
        reasons.append("MISSING_OR_DUPLICATE_SOURCE_CHAIN_EDGE")
    if (raw.ndim != 2 or raw.shape[1:] != (2,) or len(raw) < 2
            or not np.array_equal(raw, np.rint(raw))):
        return {"pass": False, "reasons": ["SOURCE_CHAIN_IS_NOT_ORIGINAL_PIXEL_CENTERS"]}
    raw = raw.astype(int)
    if (np.any(raw < 0) or np.any(raw >= [source.shape[1], source.shape[0]])
            or not np.all(source[raw[:, 1], raw[:, 0]] < POLICY["source_threshold"])):
        reasons.append("SOURCE_CHAIN_HAS_WHITE_OR_OUT_OF_IMAGE_POINTS")
    observed = _source_edges(raw)
    missing = []
    for eid in ids:
        pixels = graph.xy(graph.edges[eid]["pixels"])
        if not _source_edges(pixels) <= observed:
            missing.append(eid)
    if missing:
        reasons.append("CLAIMED_GRAPH_EDGE_NOT_IN_THE_SAME_SOURCE_CHAIN")
    undeclared = [eid for eid, edge in enumerate(graph.edges) if eid not in ids
                  and bool(_source_edges(graph.xy(edge["pixels"])) & observed)]
    if undeclared:
        reasons.append("SOURCE_CHAIN_USES_UNDECLARED_EXTERNAL_GRAPH_EDGES")
    if np.any(np.max(np.abs(np.diff(raw, axis=0)), axis=1) > 1):
        reasons.append("SOURCE_CHAIN_IS_DISCONTINUOUS")
    return {"pass": not reasons, "reasons": reasons,
            "complete_source_chain_sha256": _digest(raw.tolist()),
            "source_graph_edge_ids": ids, "source_pixel_count": len(raw),
            "unbound_source_graph_edge_ids": missing,
            "undeclared_external_graph_edge_ids": undeclared,
            "source_chain_is_a_locator_not_a_width_certificate": True}


def measure_whole_chain_width(source, graph, row, all_rows, *, forbidden_core_cells=()):
    """Enumerate all chain ports before intersecting every independent constraint."""
    native = _points(row)
    others = [_points(other) for other in all_rows if other["stroke_id"] != row["stroke_id"]]
    ports = sorted({(eid, end) for eid in row["source_graph_edge_ids"] for end in (0, 1)})
    records, seen = [], set()
    for port in ports:
        for observation in source_observations(graph, port):
            _, index, fraction, q = exact.project_point_polyline(observation["source_points_px"][-1], native)
            item = {"port": list(port), "observation": observation,
                    "native_segment_index": index, "projection_fraction": exact.encode_rational(fraction)}
            if observation["source_chord_squared_px"] < POLICY["minimum_source_direction_chord_px"] ** 2:
                item.update(pass_=False, constraint_eligible=False, reason="SOURCE_DIRECTION_CHORD_TOO_SHORT")
            elif fraction <= 0 or fraction >= 1:
                item.update(pass_=False, constraint_eligible=False, reason="NO_INTERIOR_FINITE_NORMAL_SECTION")
            elif q in seen:
                item.update(pass_=False, constraint_eligible=False, reason="DUPLICATE_EXACT_SECTION_NOT_NEW_SUPPORT")
            else:
                seen.add(q)
                a, b = native[index], native[index + 1]
                direction = (b[0] - a[0], b[1] - a[1])
                # Another bend of this same polyline can contaminate a normal
                # section too. Collinear parts share the same axis/radius;
                # all noncollinear finite parts retain the ordinary exclusion.
                same_body_other_axes = [[c, d] for j, (c, d) in enumerate(zip(native, native[1:]))
                    if j != index and any(direction[0] * (p[1] - a[1]) != direction[1] * (p[0] - a[0])
                                          for p in (c, d))]
                item.update(exact.measure_section(
                    source, q, a, b, other_paths=others + same_body_other_axes,
                    forbidden_core_cells=forbidden_core_cells,
                    source_threshold=POLICY["source_threshold"], half_span=POLICY["maximum_section_half_span_px"]))
                item["same_body_noncollinear_finite_axes_excluded"] = len(same_body_other_axes)
            if "pass_" in item:
                item["pass"] = item.pop("pass_")
            records.append(item)
    result = exact.intersect_sections(records, min_sections=POLICY["minimum_independent_sections"])
    result.update(sections=records, source_ports_enumerated=[list(p) for p in ports],
                  every_complete_chain_port_enumerated=True,
                  selection_policy="ALL_FIXED_SOURCE_SPANS_BEFORE_EXCLUSIVITY_AND_EXACT_INTERSECTION",
                  native_geometry_sha256=_digest({"representation": row["representation"],
                      "exact_points": row.get("representation_exact_points")}),
                  same_chain_transfer_condition="UNIQUE_CONTINUOUS_ROUTE_AND_ALL_INDEPENDENT_CONSTRAINTS_AGREE")
    return result


def _owner_row(owner, graph):
    if owner is None:
        return None
    binding = owner.get("binding", owner)
    geometry = owner.get("native_geometry", binding.get("geometry"))
    evidence = binding.get("source_evidence", {})
    raw = evidence.get("source_path_points", [])
    observed = _source_edges(raw)
    ids = [eid for eid, edge in enumerate(graph.edges)
           if _source_edges(graph.xy(edge["pixels"])) and _source_edges(graph.xy(edge["pixels"])) <= observed]
    return {"stroke_id": binding["id"], "representation": deepcopy(geometry),
            "source_graph_edge_ids": ids,
            "source_node_ids": sorted({nid for eid in ids for nid in graph.edges[eid]["nodes"]}),
            "source_path_px": deepcopy(raw), "endpoint_evidence": [],
            "body_role": "NECESSARY_PRIOR_FINITE_NEIGHBOR", "prior_source_binding": deepcopy(evidence)}


def _window(source, graph, rows):
    points = [p for row in rows for p in _points(row)]
    low = [min(p[k] for p in points) for k in (0, 1)]
    high = [max(p[k] for p in points) for k in (0, 1)]
    if max(high[k] - low[k] for k in (0, 1)) > POLICY["maximum_target_extent_px"]:
        raise ValueError("TARGET_COMPONENT_EXTENT_RESOURCE_BOUND")
    border = POLICY["window_border_px"]
    requested = [math.floor(low[0]) - border, math.floor(low[1]) - border,
                 math.ceil(high[0]) + border + 1, math.ceil(high[1]) + border + 1]
    origin = list(map(int, graph.origin))
    box = [max(0, origin[0], requested[0]), max(0, origin[1], requested[1]),
           min(source.shape[1], origin[0] + graph.w, requested[2]),
           min(source.shape[0], origin[1] + graph.h, requested[3])]
    x0, y0, x1, y1 = box
    if (x1 - x0) * (y1 - y0) > POLICY["maximum_window_cells"]:
        raise ValueError("FINITE_COMPONENT_WINDOW_RESOURCE_BOUND")
    patch = source[y0:y1, x0:x1]
    ink = patch < POLICY["source_threshold"]
    labels, _ = label(ink, structure=np.ones((3, 3), int))
    seeds = {int(labels[int(p[1]) - y0, int(p[0]) - x0])
             for row in rows for p in row["source_path_px"]
             if x0 <= p[0] < x1 and y0 <= p[1] < y1}
    seeds.discard(0)
    owned = np.isin(labels, list(seeds)) & ink
    by, bx = np.nonzero(ink)
    wy, wx = np.nonzero(~ink)
    white_labels, count = label(~ink)
    border_labels = set(white_labels[0]) | set(white_labels[-1]) | set(white_labels[:, 0]) | set(white_labels[:, -1])
    holes = []
    for value in range(1, count + 1):
        if value not in border_labels:
            hy, hx = np.nonzero(white_labels == value)
            holes.append(np.column_stack((hx + x0, hy + y0)).tolist())
    return ({"raw_box_xyxy_px": box, "requested_box_xyxy_px": requested,
             "clipped_by_source_or_roi": box != requested,
             "raw_gray_array_sha256": hashlib.sha256(patch.tobytes()).hexdigest(),
             "raw_gray_values": patch.tolist(), "original_white_holes": holes,
             "source_window_shape": list(patch.shape)},
            np.column_stack((bx + x0, by + y0)).tolist(),
            owned[by, bx].tolist(), np.column_stack((wx + x0, wy + y0)).tolist())


def _white_points(cell):
    x, y = map(Fraction, cell)
    return [(x + dx, y + dy) for dx in (Fraction(-1, 2), Fraction(0), Fraction(1, 2))
            for dy in (Fraction(-1, 2), Fraction(0), Fraction(1, 2))]


def _bbox_point_distance2(point, native):
    # Exact AABB lower bound avoids expensive far-away finite-segment queries.
    return sum((max(min(p[k] for p in native) - point[k], 0,
                    point[k] - max(p[k] for p in native))) ** 2 for k in (0, 1))


def solve_finite_union(black_cells, white_cells, bodies, *, max_states=None):
    """Exact finite-event feasibility; a resource stop is never an infeasibility proof."""
    max_states = POLICY["maximum_model_search_states"] if max_states is None else max_states
    native = [_points(body) for body in bodies]
    prepared = [exact.prepare_polyline(points) for points in native]
    intervals = [_interval(body["width"]) for body in bodies]
    low = tuple(bounds[0] for bounds in intervals)
    upper = tuple(bounds[1] for bounds in intervals)
    if not bodies or any(lo >= hi for lo, hi in intervals):
        return {"pass": False, "status": "MODEL_NOT_APPLICABLE_INVALID_WIDTH", "search_complete": False,
                "resource_truncated": False, "visited_state_count": 0}
    distances = [tuple(exact.cell_polyline_distance_squared(cell, p) for p in prepared) for cell in black_cells]
    candidates = [tuple(i for i, value in enumerate(row) if value < upper[i]) for row in distances]
    impossible = [black_cells[i] for i, eligible in enumerate(candidates) if not eligible]
    if impossible:
        return {"pass": False, "status": "NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_ENVELOPES", "search_complete": True,
                "resource_truncated": False, "visited_state_count": 0, "unexplained_black_cells": impossible}
    # Most whites have a center outside even the strict upper envelopes. These
    # are certified for every possible model, not omitted from the evidence.
    white_constraints, universal = [], []
    for cell in white_cells:
        center = tuple(map(Fraction, cell))
        outside = []
        for i, points in enumerate(native):
            bound = _bbox_point_distance2(center, points)
            outside.append(bound >= upper[i] or exact.point_polyline_distance_squared(center, prepared[i]) >= upper[i])
        if all(outside):
            universal.append(cell)
        else:
            white_constraints.append((cell, [tuple(exact.point_polyline_distance_squared(p, poly)
                                                   for poly in prepared) for p in _white_points(cell)]))
    stack, seen, model = [low], set(), None
    rejected_white = 0
    while stack:
        radii = stack.pop()
        if radii in seen:
            continue
        if len(seen) >= max_states:
            return {"pass": False, "status": "PENDING_EXACT_MODEL_SEARCH_RESOURCE_BOUND", "search_complete": False,
                    "resource_truncated": True, "visited_state_count": len(seen),
                    "universal_white_center_count": len(universal)}
        seen.add(radii)
        if any(not any(all(distance > radius for distance, radius in zip(witness, radii))
                       for witness in witnesses) for _, witnesses in white_constraints):
            rejected_white += 1
            continue
        missing = [i for i, row in enumerate(distances) if not any(d <= r for d, r in zip(row, radii))]
        if not missing:
            model = radii
            break
        cell_index = min(missing, key=lambda i: (len(candidates[i]), i))
        for body_index in reversed(candidates[cell_index]):
            updated = list(radii)
            updated[body_index] = max(updated[body_index], distances[cell_index][body_index])
            stack.append(tuple(updated))
    result = {"pass": model is not None,
              "status": "COHERENT_FINITE_UNION_FOUND" if model is not None else "NO_COHERENT_FINITE_UNION",
              "search_complete": model is None and not stack, "existence_certificate_complete": model is not None,
              "resource_truncated": False, "visited_state_count": len(seen),
              "states_rejected_by_common_white_witness": rejected_white,
              "universal_white_center_count": len(universal),
              "body_ids": [body["stroke_id"] for body in bodies]}
    if model is not None:
        result["half_width_squared_vector"] = [exact.encode_rational(value) for value in model]
        result["black_witnesses"] = [{"source_cell": cell,
            "body_ids": [bodies[i]["stroke_id"] for i, distance in enumerate(row) if distance <= model[i]]}
            for cell, row in zip(black_cells, distances)]
        result["white_witnesses"] = [{"source_cell": cell, "point": list(cell), "valid_for_entire_width_box": True}
                                     for cell in universal]
        for cell, witnesses in white_constraints:
            index = next(i for i, witness in enumerate(witnesses)
                         if all(distance > radius for distance, radius in zip(witness, model)))
            result["white_witnesses"].append({"source_cell": cell,
                "point_exact": _encoded_point(_white_points(cell)[index]), "valid_for_entire_width_box": False})
    return result


def _endpoint_rows(graph, rows, cores, all_rows=None):
    all_rows = rows if all_rows is None else all_rows
    results = []
    for row in rows:
        native = _points(row)
        for index, terminal in enumerate(row.get("endpoint_evidence", [])):
            end = 0 if index == 0 else -1
            neighbor = 1 if end == 0 else -2
            delta = [native[end][k] - native[neighbor][k] for k in (0, 1)]
            observations = source_observations(graph, terminal["port"])
            source_direction = bool(observations) and all(
                observation["source_chord_squared_px"] >= POLICY["minimum_source_direction_chord_px"] ** 2
                for observation in observations)
            item = {"guest_id": row["stroke_id"], "end": 0 if end == 0 else 1,
                    "source_node_id": terminal["node_id"], "source_port": terminal["port"],
                    "actual_native_endpoint_exact": _encoded_point(native[end]),
                    "actual_native_terminal_segment_squared_length": exact.encode_rational(sum(v * v for v in delta)),
                    "actual_native_terminal_segment_length_px_diagnostic": math.sqrt(float(sum(v * v for v in delta))),
                    "source_direction_observations": observations, "source_direction_pass": source_direction,
                    "native_short_segment_preserved": True, "kind": terminal["kind"]}
            if "host_path_index" in terminal or "host_path_id" in terminal:
                host = (next(r for r in all_rows if r["stroke_id"] == terminal["host_path_id"])
                        if "host_path_id" in terminal else all_rows[terminal["host_path_index"]])
                distance2 = exact.point_polyline_distance_squared(native[end], _points(host))
                precision = exact.rational(legacy_ink.POLICY["native_coordinate_precision_px"])
                item.update(host_id=host["stroke_id"], finite_host_contact_squared_distance=exact.encode_rational(distance2),
                            exact_finite_host_contact=distance2 == 0,
                            within_existing_native_contact_precision=distance2 <= precision * precision,
                            existing_native_contact_precision_px=legacy_ink.POLICY["native_coordinate_precision_px"],
                            exact_contact_is_a_separate_saved_geometry_observation=True,
                            shared_core_independently_supported=bool(cores.get(terminal["node_id"], {}).get("pass")))
            else:
                node = graph.nodes[terminal["node_id"]]
                item["observed_free_end"] = ((node.get("terminal") or {}).get("kind") == "OBSERVED_FREE_SOURCE_ENDPOINT")
                item["fresh_free_cap_pass"] = bool(terminal.get("source_cap_evidence", {}).get("pass"))
            results.append(item)
    return results


def _exit_proof(cell, body, graph, box):
    """A boundary pixel is a shaft exit only with the same raw chain on both sides."""
    points = _points(body)
    distance2, segment, fraction, _ = exact.project_point_polyline(cell, points)
    if not 0 < fraction < 1:
        return None
    _, upper = _interval(body["width"])
    if exact.cell_polyline_distance_squared(cell, points) >= upper:
        return None
    x0, y0, x1, y1 = box
    sides = []
    if cell[0] == x0:
        sides.append((0, x0, -1))
    if cell[0] == x1 - 1:
        sides.append((0, x1 - 1, 1))
    if cell[1] == y0:
        sides.append((1, y0, -1))
    if cell[1] == y1 - 1:
        sides.append((1, y1 - 1, 1))
    for axis, boundary, sign in sides:
        for eid in body["source_graph_edge_ids"]:
            raw = np.asarray(graph.xy(graph.edges[eid]["pixels"]), int)
            signed = sign * (raw[:, axis] - boundary)
            near = np.sum((raw - np.asarray(cell)) ** 2, axis=1) <= (POLICY["maximum_section_half_span_px"] + 1) ** 2
            if np.any(near & (signed <= -4)) and np.any(near & (signed >= 4)):
                return {"body_id": body["stroke_id"], "source_edge_id": eid,
                        "native_segment_index": segment, "source_chord_on_both_sides_px": 4,
                        "point_to_native_squared_distance": exact.encode_rational(distance2)}
    return None


def _continuation_events(source, rows, bodies, endpoints, black, white, ledger, all_widths_valid):
    """Observable outward events are refusal witnesses, never adopted geometry."""
    residual = [item["source_cell"] for item in ledger
                if item["relevant_connected_ink"] and not item["compatible_body_ids"]]
    result = {"events": [], "distinct_observable_boundary_exists": False,
              "hidden_pen_travel": "SAME_DECLARED_EDITING_REPRESENTATION",
              "new_geometry_generated": False, "search_complete": False}
    if not all_widths_valid:
        result["status"] = "NOT_RUN_INAPPLICABLE_OR_UNSUPPORTED_BODY_WIDTH"
        return result
    if not residual:
        result.update(status="NO_CONNECTED_INK_OUTSIDE_SUPPORTED_FINITE_ENVELOPES", search_complete=True,
                      completeness_scope="OBSERVABLE_ORIGINAL_BLACK_CELL_EVENTS_OUTSIDE_FINITE_UNION")
        return result
    body_index = {body["stroke_id"]: i for i, body in enumerate(bodies)}
    attempted = 0
    for endpoint in endpoints:
        if "host_id" not in endpoint:
            continue
        row = next(row for row in rows if row["stroke_id"] == endpoint["guest_id"])
        points = _points(row)
        end, adjacent = (0, 1) if endpoint["end"] == 0 else (-1, -2)
        origin = points[end]
        direction = tuple(origin[k] - points[adjacent][k] for k in (0, 1))
        norm2 = sum(v * v for v in direction)
        if not norm2 or not endpoint["source_direction_pass"]:
            result["status"] = "PENDING_EXTENSION_DIRECTION_NOT_ESTABLISHED"
            return result
        values = set()
        for cell in residual:
            for point in _white_points(cell):
                scale = sum((point[k] - origin[k]) * direction[k] for k in (0, 1)) / norm2
                if scale > 0 and scale * scale * norm2 <= POLICY["maximum_extension_px"] ** 2:
                    values.add(scale)
        for scale in sorted(values):
            if attempted >= POLICY["maximum_extension_events"]:
                result["status"] = "PENDING_EXTENSION_EVENT_RESOURCE_BOUND"
                result["resource_truncated"] = True
                return result
            attempted += 1
            extended = deepcopy(bodies)
            replacement = list(points)
            replacement[end] = tuple(origin[k] + scale * direction[k] for k in (0, 1))
            # Exact fractions are kept internally; serialize the evaluated point
            # separately. This is a diagnostic hypothesis, never written as CAD.
            extended[body_index[row["stroke_id"]]]["representation"] = {"points": replacement, "closed": False}
            extended[body_index[row["stroke_id"]]]["representation_exact_points"] = [_encoded_point(p) for p in replacement]
            model = solve_finite_union(black, white, extended)
            event = {"guest_id": row["stroke_id"], "end": endpoint["end"],
                     "scale_exact": exact.encode_rational(scale), "endpoint_exact": _encoded_point(replacement[end]),
                     "coherent_with_original_black_and_white": model["pass"],
                     "model_status": model["status"], "adopted": False,
                     "search_resource_truncated": model.get("resource_truncated", False)}
            if model.get("half_width_squared_vector"):
                event["half_width_squared_vector"] = model["half_width_squared_vector"]
            result["events"].append(event)
            if model["pass"]:
                result.update(distinct_observable_boundary_exists=True,
                              status="OBSERVABLE_FINITE_CONTINUATION_COMPETITOR_FOUND")
                return result
            if model.get("resource_truncated"):
                result["status"] = "PENDING_EXTENSION_MODEL_RESOURCE_BOUND"
                return result
    result.update(status="NO_COMPATIBLE_ENUMERATED_OUTWARD_EVENT",
                  search_complete=False,
                  limitation="ARBITRARY_NEW_BENDS_AND_NONCONSTANT_WIDTH_CONTINUATIONS_NOT_EXCLUDED")
    return result


def audit_finite_bodies(source, graph, rows, *, owner=None, cores=None):
    """Low-level model seam for independently reconstructed source bindings.

    The caller must separately prove route uniqueness, exact native contacts,
    complete context and saved-file membership. This model never adopts objects.
    """
    source, cores = np.asarray(source), cores or {}
    report = {"schema": SCHEMA, "policy": deepcopy(POLICY), "producer_sha256": producer_sha256(),
              "exact_kernel_sha256": hashlib.sha256(Path(exact.__file__).read_bytes()).hexdigest(),
              "pass": False, "status": "PENDING", "failure_reasons": [],
              "new_geometry_generated": False, "bodies": [], "candidate_ids": [r["stroke_id"] for r in rows
                  if r.get("body_role") != "NECESSARY_PRIOR_FINITE_NEIGHBOR"]}
    try:
        targets = [row for row in rows if row.get("body_role") != "NECESSARY_PRIOR_FINITE_NEIGHBOR"]
        if any(len(row.get("endpoint_evidence", [])) != 2 for row in targets):
            raise ValueError("COMPLETE_TARGET_REQUIRES_TWO_INDEPENDENT_ENDPOINT_RECEIPTS")
        bodies = [{**deepcopy(row), "body_role": row.get("body_role", "COMPLETE_TARGET_STROKE")} for row in rows]
        prior = _owner_row(owner, graph)
        if prior is not None:
            bodies.append(prior)
        forbidden = {tuple(map(int, p)) for body in bodies for nid in body["source_node_ids"]
                     for p in graph.xy(graph.nodes[nid]["pixels"])}
        for body in bodies:
            body["chain_binding"] = _chain_binding(source, graph, body)
            body["width"] = measure_whole_chain_width(source, graph, body, bodies, forbidden_core_cells=forbidden)
            body["native_centerline_source_support"] = exact_centerline_source_support(source, _points(body))
            if "prior_source_binding" in body:
                evidence = body["prior_source_binding"]
                origin = list(map(int, graph.origin))
                box = [*origin, origin[0] + graph.w, origin[1] + graph.h]
                bound = (evidence.get("source_pixels_modified") is False
                         and evidence.get("original_source_crop_xyxy_px") == box
                         and evidence.get("original_source_crop_array_sha256") == hashlib.sha256(
                             source[box[1]:box[3], box[0]:box[2]].tobytes()).hexdigest())
                body["prior_source_identity_pass"] = bound
            else:
                body["prior_source_identity_pass"] = True
            body["independently_supported"] = bool(body["chain_binding"]["pass"] and body["width"]["pass"]
                and body["native_centerline_source_support"]["pass"] and body["prior_source_identity_pass"])
            report["bodies"].append({k: deepcopy(body[k]) for k in
                ("stroke_id", "body_role", "representation", "source_graph_edge_ids", "source_node_ids",
                 "chain_binding", "width", "native_centerline_source_support", "prior_source_identity_pass",
                 "independently_supported")})
        report["endpoints"] = _endpoint_rows(graph, targets, cores, all_rows=bodies)
        patch, black, relevant, white = _window(source, graph, targets)
        report["original_patch"] = patch
        supported = [body for body in bodies if body["independently_supported"]]
        prepared = [(body, exact.prepare_polyline(_points(body)), _interval(body["width"])[1]) for body in supported]
        core_map = {tuple(map(int, p)): nid for nid, core in cores.items() if core.get("pass")
                    for p in graph.xy(graph.nodes[nid]["pixels"])}
        ledger, exits = [], []
        x0, y0, x1, y1 = patch["raw_box_xyxy_px"]
        for cell, own in zip(black, relevant):
            ids = [body["stroke_id"] for body, native, upper in prepared
                   if exact.cell_polyline_distance_squared(cell, native) < upper] if own else []
            role = ("DISCONNECTED_NEIGHBOR" if not own else "UNKNOWN_CONNECTED_INK" if not ids
                    else "SUPPORTED_SHARED_JUNCTION" if tuple(cell) in core_map and len(ids) > 1
                    else "FINITE_BODY_COMPATIBLE_INK")
            item = {"source_cell": cell, "original_gray_value": int(source[cell[1], cell[0]]),
                    "relevant_connected_ink": bool(own), "classification": role,
                    "compatible_body_ids": ids, "assignment_is_joint_model_proved": False}
            roles = []
            for body in supported:
                if body["stroke_id"] not in ids:
                    continue
                native = _points(body)
                _, segment, fraction, _ = exact.project_point_polyline(cell, native)
                local = ("FINITE_END_CAP" if (segment == 0 and fraction == 0)
                         or (segment == len(native) - 2 and fraction == 1)
                         else "FINITE_INTERNAL_JOIN" if fraction in (0, 1) else "FINITE_SHAFT_BODY")
                roles.append({"body_id": body["stroke_id"], "body_role": body["body_role"],
                              "finite_role": local})
            item["compatible_responsibilities"] = roles
            if tuple(cell) in core_map:
                item["independently_supported_source_core_id"] = core_map[tuple(cell)]
            ledger.append(item)
            if own and (cell[0] in (x0, x1 - 1) or cell[1] in (y0, y1 - 1)):
                proofs = [proof for body in supported if (proof := _exit_proof(cell, body, graph, patch["raw_box_xyxy_px"]))]
                exits.append({"source_cell": cell, "classification": "PROVED_FINITE_SHAFT_EXIT" if proofs else "UNKNOWN_CONNECTED_EXIT",
                              "source_proofs": proofs})
        report["pixel_ledger"] = ledger
        report["white_ledger"] = [{"source_cell": cell, "original_gray_value": int(source[cell[1], cell[0]])} for cell in white]
        report["window_exits"] = exits
        report["observation_closed"] = not patch["clipped_by_source_or_roi"] and all(e["source_proofs"] for e in exits)
        all_supported = len(supported) == len(bodies)
        own_black = [cell for cell, own in zip(black, relevant) if own]
        if all_supported:
            model = solve_finite_union(own_black, white, bodies)
        else:
            model = {"pass": False, "status": "NOT_RUN_NECESSARY_BODY_MODEL_NOT_ESTABLISHED",
                     "unsupported_body_ids": [b["stroke_id"] for b in bodies if not b["independently_supported"]],
                     "search_complete": False, "resource_truncated": False}
        report["coherent_component_model"] = model
        if model["pass"]:
            witnesses = {tuple(r["source_cell"]): r["body_ids"] for r in model["black_witnesses"]}
            for item in ledger:
                if tuple(item["source_cell"]) in witnesses:
                    item["joint_model_body_ids"] = witnesses[tuple(item["source_cell"])]
                    item["assignment_is_joint_model_proved"] = True
        report["short_continuation_competition"] = _continuation_events(
            source, targets, bodies, report["endpoints"], own_black, white, ledger, all_supported)
        failures = report["failure_reasons"]
        for body in bodies:
            if not body["chain_binding"]["pass"] or not body["prior_source_identity_pass"]:
                failures.append("INDEPENDENT_COMPLETE_SOURCE_CHAIN_NOT_ESTABLISHED")
            if not body["width"]["pass"]:
                failures.append("COMPLETE_CHAIN_CONSTANT_WIDTH_NOT_ESTABLISHED")
            if not body["native_centerline_source_support"]["pass"]:
                failures.append("FINITE_NATIVE_CENTERLINE_SOURCE_CONTRADICTION")
        if not report["observation_closed"]:
            failures.append("PENDING_UNKNOWN_EXIT_OR_CLIPPED_TARGET_SCOPE")
        if not model["pass"]:
            failures.append("COHERENT_WHOLE_COMPONENT_MODEL_NOT_ESTABLISHED")
        for endpoint in report["endpoints"]:
            if not endpoint["source_direction_pass"]:
                failures.append("SOURCE_DIRECTION_CHORD_NOT_ESTABLISHED")
            if "host_id" in endpoint and (not endpoint["exact_finite_host_contact"]
                                           or not endpoint["shared_core_independently_supported"]):
                failures.append("FINITE_ATTACHMENT_OR_SHARED_SOURCE_CORE_NOT_ESTABLISHED")
            if "host_id" not in endpoint and not (endpoint["observed_free_end"] and endpoint["fresh_free_cap_pass"]):
                failures.append("COMPLETE_FREE_ENDPOINT_RESPONSIBILITY_NOT_ESTABLISHED")
        competition = report["short_continuation_competition"]
        if competition["distinct_observable_boundary_exists"]:
            failures.append("OBSERVABLE_FINITE_BOUNDARY_COMPETITOR")
        elif not competition["search_complete"]:
            failures.append("BOUNDARY_COMPETITION_NOT_COMPLETELY_RESOLVED")
        report["failure_reasons"] = sorted(set(failures))
        report["pass"] = not failures
        report["complete_pixel_accounting"] = len(ledger) + len(white) == np.prod(patch["source_window_shape"])
        report["status"] = ("COMPLETE_SOURCE_MODEL_PASS" if report["pass"] else
                            "MODEL_NOT_APPLICABLE_CONSTANT_WIDTH" if any(
                                body["width"].get("reason") == "CONSTANT_WIDTH_MODEL_INAPPLICABLE" for body in bodies)
                            else "PENDING_FINITE_COMPONENT_RESPONSIBILITY")
        report["constant_width_model_failures"] = [{"body_id": b["stroke_id"], "width_status": b["width"].get("status"),
                                                   "width_reason": b["width"].get("reason")}
                                                  for b in bodies if not b["width"]["pass"]]
        report["geometry_wrong_or_scan_ambiguous_asserted"] = False
    except (ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
        report.update(status="PENDING_INVALID_OR_RESOURCE_LIMITED_COMPONENT_INPUT",
                      failure_reasons=[str(exc)], pass_=False)
        report["pass"] = report.pop("pass_")
    return report


def prove_finite_component(source, graph, rows, *, owner, cores):
    """Planner seam; candidate retention and final adoption are caller-owned."""
    return audit_finite_bodies(source, graph, rows, owner=owner, cores=cores)
