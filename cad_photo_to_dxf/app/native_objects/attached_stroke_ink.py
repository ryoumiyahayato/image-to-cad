"""Finite raw-ink responsibility at a proposed complete stroke attachment.

This is a refusal/proof gate, not another stroke generator.  Its observable
endpoint convention, independent width sections and counterexamples are frozen
in docs/native/ATTACHED_INK_CONTRACT_20261127.md.  No local source is rewritten.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import label

from . import connections as paths
from .circle_endpoint_contacts import _segment_cells


SCHEMA = "source-attached-end-raw-ink-responsibility-v1"
POLICY = {
    "version": "independent-arm-finite-round-capsule-responsibility-v1",
    "endpoint_convention": "OBSERVABLE_FINITE_HOST_INTERSECTION",
    "hidden_physical_pen_travel": "NOT_IDENTIFIABLE",
    "finite_observation_spans_px": [6.0, 8.0, 12.0],
    "minimum_native_terminal_direction_chord_px": 4.0,
    "minimum_independent_width_sections": 2,
    "maximum_width_section_half_span_px": 12.0,
    "exclusive_section_other_axis_half_width_multiplier": 2.0,
    "maximum_observation_radius_px": 240,
    "maximum_radius_event_models": 512,
    "native_coordinate_precision_px": 1e-7,
    "cap_model": "CONSTANT_WIDTH_FINITE_ROUND_CAPSULE_UNION",
    "pixel_model": "CLOSED_UNIT_CELL_INTERSECTION_WITH_STRICT_WHITE_EXTERIOR_WITNESS",
    "white_cell_witnesses": "CORNERS_EDGE_MIDPOINTS_AND_CENTER",
    "width_upper_bounds_are_strict": True,
    "patch_ink_cannot_increase_independent_width": True,
    "different_widths_not_combined_per_pixel": True,
    "original_source_pixels_modified": False,
    "new_geometry_generated": False,
}

_CORNERS = np.array([[-.5, -.5], [-.5, .5], [.5, -.5], [.5, .5]])
_WHITE_POINTS = np.array([(x, y) for y in (-.5, 0., .5) for x in (-.5, 0., .5)])


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _unit(v):
    v = np.asarray(v, float)
    length = float(np.linalg.norm(v))
    if length <= 0:
        raise ValueError("ZERO_LENGTH_NATIVE_DIRECTION")
    return v / length


def _points(geometry):
    points = np.asarray(geometry["points"], float)
    if (points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 2
            or not np.isfinite(points).all() or geometry.get("closed")
            or any(geometry.get("bulges", []))
            or np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) == 0)):
        raise ValueError("RAW_ATTACHMENT_MODEL_REQUIRES_FINITE_OPEN_STRAIGHT_SEGMENTS")
    return points


def _point_distances(query, polyline):
    query = np.asarray(query, float).reshape(-1, 2)
    best = np.full(len(query), np.inf)
    segments = np.zeros(len(query), int)
    fractions = np.zeros(len(query))
    nearest = np.zeros_like(query)
    for index, (a, b) in enumerate(zip(polyline, polyline[1:])):
        delta = b - a
        t = np.clip((query - a) @ delta / (delta @ delta), 0, 1)
        at = a + t[:, None] * delta
        distance = np.linalg.norm(query - at, axis=1)
        take = distance < best
        best[take], segments[take], fractions[take], nearest[take] = (
            distance[take], index, t[take], at[take])
    return best, segments, fractions, nearest


def _cell_min_distances(cells, polyline):
    """Exact minimum distance from closed unit squares to finite segments."""
    cells = np.asarray(cells, float).reshape(-1, 2)
    result = np.full(len(cells), np.inf)
    corners = cells[:, None, :] + _CORNERS
    for a, b in zip(polyline, polyline[1:]):
        delta = b - a
        t = np.clip((corners - a) @ delta / (delta @ delta), 0, 1)
        corner_distance = np.linalg.norm(corners - a - t[:, :, None] * delta, axis=2).min(axis=1)
        endpoint_distance = np.minimum(
            np.linalg.norm(np.maximum(np.abs(cells - a) - .5, 0), axis=1),
            np.linalg.norm(np.maximum(np.abs(cells - b) - .5, 0), axis=1))
        enter, leave = np.zeros(len(cells)), np.ones(len(cells))
        for axis in range(2):
            if delta[axis] == 0:
                leave[np.abs(cells[:, axis] - a[axis]) > .5] = -1
            else:
                first = (cells[:, axis] - .5 - a[axis]) / delta[axis]
                last = (cells[:, axis] + .5 - a[axis]) / delta[axis]
                enter = np.maximum(enter, np.minimum(first, last))
                leave = np.minimum(leave, np.maximum(first, last))
        distance = np.minimum(corner_distance, endpoint_distance)
        distance[enter <= leave] = 0
        result = np.minimum(result, distance)
    return result


def _black_cells(source, cells):
    points = np.asarray(cells, int).reshape(-1, 2)
    inside = (np.all(points >= 0, axis=1) & (points[:, 0] < source.shape[1])
              & (points[:, 1] < source.shape[0]))
    ink = np.zeros(len(points), bool)
    ink[inside] = source[points[inside, 1], points[inside, 0]] < paths.POLICY["source_threshold"]
    return inside, ink


def _source_centerline_check(source, polyline):
    cells = sorted({tuple(p) for a, b in zip(polyline, polyline[1:]) for p in _segment_cells(a, b)})
    inside, ink = _black_cells(source, cells)
    return {"pass": bool(np.all(inside & ink)), "closed_source_pixel_cells": [list(p) for p in cells],
            "white_or_unobserved_cells": [list(p) for p, valid in zip(cells, inside & ink) if not valid]}


def _observations(graph, port):
    points = graph.xy(graph.oriented(tuple(port)))
    cumulative = np.r_[0., np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    result = []
    for span in POLICY["finite_observation_spans_px"]:
        index = min(len(points) - 1, int(np.searchsorted(cumulative, min(span, cumulative[-1]))))
        chord = float(np.linalg.norm(points[index] - points[0]))
        result.append({"requested_span_px": span, "actual_span_px": float(cumulative[index]),
                       "chord_px": chord, "source_points_px": points[:index + 1].tolist(),
                       "stopped_at_next_graph_node": index == len(points) - 1})
    return result


def _section(source, q, axis, other_paths, forbidden_core_cells):
    normal = np.array([-axis[1], axis[0]])
    half_span = POLICY["maximum_width_section_half_span_px"]
    cells = np.asarray(_segment_cells(q - half_span * normal, q + half_span * normal), int)
    inside, ink = _black_cells(source, cells)
    row = {"center_px": q.tolist(), "actual_native_axis": axis.tolist(), "normal": normal.tolist(),
           "section_source_cells": cells.tolist(), "section_ink": ink.astype(int).tolist(), "pass": False}
    if not np.all(inside):
        row["reason"] = "SECTION_REACHES_SOURCE_BOUNDARY"
        return row
    black = {tuple(p) for p in cells[ink]}
    seed = {p for p in black if np.all(np.abs(np.asarray(p) - q) <= .5)}
    own, queue = set(seed), list(sorted(seed))
    while queue:
        x, y = queue.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if p in black and p not in own:
                    own.add(p)
                    queue.append(p)
    if not own:
        row["reason"] = "SECTION_NATIVE_AXIS_HAS_NO_ORIGINAL_INK"
        return row
    own_points = np.asarray(sorted(own), float)
    whites = cells[~ink]
    positions = (whites - q) @ normal
    sides = []
    for sign in (-1, 1):
        candidates = np.flatnonzero(positions * sign > 0)
        if not len(candidates):
            row["reason"] = "SECTION_HAS_NO_WHITE_ON_BOTH_SIDES"
            return row
        first = candidates[np.argmin(positions[candidates] * sign)]
        sides.append(whites[first])
    whites = np.asarray(sides)
    cell_half_projection = .5 * float(np.abs(normal).sum())
    low = max(0., float(np.max(np.abs((own_points - q) @ normal) - cell_half_projection)))
    high = float(np.min(np.abs((whites - q) @ normal) + cell_half_projection))
    nearest_other = min((float(_point_distances([q], p)[0][0]) for p in other_paths), default=None)
    required_separation = (POLICY["exclusive_section_other_axis_half_width_multiplier"] * high
                           + math.sqrt(.5))
    core_pixels = [list(p) for p in sorted(set(map(tuple, cells)) & forbidden_core_cells)]
    row.update(independent_black_cells=own_points.astype(int).tolist(), first_white_cells=whites.tolist(),
               half_width_interval_px=[low, high], upper_bound_is_strict=True,
               nearest_other_finite_axis_distance_px=nearest_other,
               required_other_axis_separation_px=required_separation, interfering_core_cells=core_pixels,
               original_values=[int(source[y, x]) for x, y in cells])
    if high >= half_span or low >= high:
        row["reason"] = "SECTION_WIDTH_INTERVAL_EMPTY_OR_TRUNCATED"
    elif core_pixels or (nearest_other is not None and nearest_other <= required_separation):
        row["reason"] = "SECTION_NOT_INDEPENDENT_OF_JUNCTION_OR_OTHER_STROKE"
    else:
        row.update(pass_=True, reason="INDEPENDENT_ORIGINAL_ARM_SECTION")
        row["pass"] = row.pop("pass_")
    return row


def _width(source, graph, ports, row, component_rows, extra_exclusion_paths):
    native = _points(row["representation"])
    other = [_points(r["representation"]) for r in component_rows if r["stroke_id"] != row["stroke_id"]]
    other += [np.asarray(p, float) for p in extra_exclusion_paths]
    forbidden = {tuple(map(int, p)) for r in component_rows for nid in r["source_node_ids"]
                 for p in graph.xy(graph.nodes[nid]["pixels"])}
    samples, used = [], set()
    for port in sorted(set(tuple(p) for p in ports)):
        for observation in _observations(graph, port):
            point = np.asarray(observation["source_points_px"][-1])
            _, segments, fractions, nearest = _point_distances([point], native)
            index, q = int(segments[0]), nearest[0]
            identity = (float(q[0]), float(q[1]))
            record = {"port": list(port), "observation": observation, "native_segment_index": index}
            if (observation["chord_px"] < POLICY["minimum_native_terminal_direction_chord_px"]
                    or fractions[0] <= 0 or fractions[0] >= 1):
                record.update(pass_=False, reason="NO_FINITE_INDEPENDENT_ARM_SECTION")
                record["pass"] = record.pop("pass_")
            elif identity in used:
                record.update(pass_=False, reason="DUPLICATE_SECTION_NOT_ANOTHER_OBSERVATION")
                record["pass"] = record.pop("pass_")
            else:
                used.add(identity)
                record.update(_section(source, q, _unit(native[index + 1] - native[index]), other, forbidden))
            samples.append(record)
    valid = [s for s in samples if s["pass"]]
    interval = ([max(s["half_width_interval_px"][0] for s in valid),
                 min(s["half_width_interval_px"][1] for s in valid)] if valid else None)
    passed = (len(valid) >= POLICY["minimum_independent_width_sections"] and interval[0] < interval[1])
    return {"pass": passed, "stroke_id": row["stroke_id"], "sections": samples,
            "independent_section_count": len(valid), "half_width_interval_px": interval,
            "upper_bound_is_strict": True, "endpoint_patch_not_used_to_raise_width": True,
            "reason": "INDEPENDENT_ARM_WIDTH_ESTABLISHED" if passed else "INDEPENDENT_ARM_WIDTH_NOT_ESTABLISHED"}


def _coherent_models(black, white, guest, host, intervals):
    dg, dh = _cell_min_distances(black, guest), _cell_min_distances(black, host)
    (gl, gu), (hl, hu) = intervals
    # Each black constraint is rg >= dg OR rh >= dh. White exterior
    # witnesses only become easier when a radius decreases. Every feasible
    # pair therefore has a minimal pair at these events, including arm-only
    # calibration lo. For each rg, the smallest sufficient rh is complete.
    events = sorted({float(gl), *(float(v) for v in dg if gl <= v < gu)})
    report = {"candidate_event_count": len(events), "feasible_models": [], "rejected_models": [],
              "black_cell_min_guest_distance_px": dg.tolist(), "black_cell_min_host_distance_px": dh.tolist(),
              "width_intervals_px": intervals, "pass": False, "resource_truncated": False}
    if len(events) > POLICY["maximum_radius_event_models"]:
        report["resource_truncated"] = True
        return report
    query = (np.asarray(white, float).reshape(-1, 1, 2) + _WHITE_POINTS).reshape(-1, 2)
    wg = _point_distances(query, guest)[0].reshape(-1, 9)
    wh = _point_distances(query, host)[0].reshape(-1, 9)
    for rg in events:
        uncovered = dg > rg
        rh = max(float(hl), float(np.max(dh[uncovered], initial=hl)))
        model = {"guest_half_width_px": rg, "host_half_width_px": rh}
        if not (gl <= rg < gu and hl <= rh < hu):
            model["reason"] = "BLACK_CELL_NEEDS_WIDTH_OUTSIDE_INDEPENDENT_INTERVAL"
            report["rejected_models"].append(model)
            continue
        exterior = (wg > rg) & (wh > rh)
        white_ok = np.any(exterior, axis=1)
        if not np.all(white_ok):
            model.update(reason="WHITE_CELL_HAS_NO_PROVED_EXTERIOR_POINT",
                         unresolved_white_cells=np.asarray(white)[~white_ok].tolist())
            report["rejected_models"].append(model)
            continue
        model.update(reason="ONE_COHERENT_FINITE_CAPSULE_PAIR_EXPLAINS_ALL_CONNECTED_INK",
                     every_black_cell_supported=True, every_white_cell_has_exterior_witness=True,
                     white_exterior_witness_indices=np.argmax(exterior, axis=1).tolist())
        report["feasible_models"].append(model)
    report["pass"] = bool(report["feasible_models"])
    return report


def _white_components(mask, left, top):
    values, count = label(~mask)
    boundary = set(values[0]) | set(values[-1]) | set(values[:, 0]) | set(values[:, -1])
    result = []
    for value in range(1, count + 1):
        y, x = np.nonzero(values == value)
        result.append({"label": value, "source_cells": np.column_stack((x + left, y + top)).tolist(),
                       "reaches_observation_boundary": value in boundary,
                       "enclosed_original_white_hole": value not in boundary})
    return result


def _patch(source, graph, endpoint, radius):
    roi = graph.roi
    requested = [int(math.floor(endpoint[0] - radius)), int(math.floor(endpoint[1] - radius)),
                 int(math.ceil(endpoint[0] + radius)) + 1, int(math.ceil(endpoint[1] + radius)) + 1]
    box = [max(0, roi[0], requested[0]), max(0, roi[1], requested[1]),
           min(source.shape[1], roi[2], requested[2]), min(source.shape[0], roi[3], requested[3])]
    left, top, right, bottom = box
    pixels = source[top:bottom, left:right]
    ink = pixels < paths.POLICY["source_threshold"]
    components, count = label(ink, structure=np.ones((3, 3), int))
    y, x = np.nonzero(ink)
    black = np.column_stack((x + left, y + top))
    own_values = {int(components[y - top, x - left]) for x, y in _segment_cells(endpoint, endpoint)
                  if left <= x < right and top <= y < bottom}
    own_values.discard(0)
    own = np.isin(components[y, x], list(own_values))
    wy, wx = np.nonzero(~ink)
    white = np.column_stack((wx + left, wy + top))
    boundary = (np.isin(black[:, 0], [left, right - 1]) | np.isin(black[:, 1], [top, bottom - 1]))
    receipt = {"radius_px": radius, "requested_box_xyxy_px": requested, "raw_box_xyxy_px": box,
               "raw_array_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(), "raw_ink_mask": ink.astype(int).tolist(),
               "raw_gray_values": pixels.tolist(), "connected_component_count": count,
               "junction_component_labels": sorted(own_values), "source_or_roi_truncated": box != requested,
               "original_white_components": _white_components(ink, left, top),
               "all_black_pixels_enumerated": True, "all_white_pixels_retained": True}
    return receipt, black, own, boundary, white, components[y, x]


def _pixel_role(cell, polyline, role):
    _, indices, fractions, _ = _point_distances([cell], polyline)
    index, fraction = int(indices[0]), float(fractions[0])
    if (index == 0 and fraction == 0) or (index == len(polyline) - 2 and fraction == 1):
        return role + "_NORMAL_CAP"
    if fraction in (0., 1.):
        return role + "_INTERNAL_ROUND_JOIN"
    return role + "_BODY_THICKNESS"


def _extensions(source, black, white, guest, host, endpoint_index, outward, intervals, unexplained):
    endpoint = guest[endpoint_index]
    projection = (np.asarray(unexplained, float).reshape(-1, 2) - endpoint) @ outward
    half = .5 * float(np.abs(outward).sum())
    events = sorted({float(v) for p in projection for v in (p - half, p, p + half)
                     if 0 < v <= POLICY["maximum_observation_radius_px"]})
    if len(events) > POLICY["maximum_radius_event_models"]:
        return {"events": [], "candidate_extension_lengths_px": events, "resource_truncated": True,
                "status": "NOT_RUN_EXTENSION_EVENT_RESOURCE_LIMIT", "search_complete": False,
                "unobserved_extensions_ruled_out": False, "pass_to_adopt_new_geometry": False,
                "distinct_observable_boundary_exists": False}
    result = []
    for length in events[:POLICY["maximum_radius_event_models"]]:
        point = endpoint + length * outward
        cells = _segment_cells(endpoint, point)
        inside, ink = _black_cells(source, cells)
        row = {"extension_length_px": length, "alternative_native_endpoint_px": point.tolist(),
               "closed_source_cells": cells, "all_centerline_cells_original_ink": bool(np.all(inside & ink)),
               "adopted": False}
        if row["all_centerline_cells_original_ink"]:
            alternative = guest.copy()
            alternative[endpoint_index] = point
            models = _coherent_models(black, white, alternative, host, intervals)
            row.update(coherent_models=models["feasible_models"], resource_truncated=models["resource_truncated"],
                       observable_boundary_competitor=bool(models["pass"]))
        else:
            row.update(coherent_models=[], observable_boundary_competitor=False)
        result.append(row)
    return {"events": result, "resource_truncated": any(r.get("resource_truncated", False) for r in result),
            "status": "BOUNDED_SOURCE_PIXEL_EVENT_COUNTEREVIDENCE", "search_complete": False,
            "unobserved_extensions_ruled_out": False,
            "pass_to_adopt_new_geometry": False,
            "distinct_observable_boundary_exists": any(r["observable_boundary_competitor"] for r in result)}


def prove_attached_endpoint_raw_responsibility(source, graph, terminal, guest_row, host_row,
                                               component_rows, *, extra_exclusion_paths=()):
    """Return a complete refusal receipt as well as successful endpoint proofs."""
    source = np.asarray(source)
    receipt = {"schema": SCHEMA, "policy": deepcopy(POLICY), "producer_sha256": producer_sha256(),
               "guest_id": guest_row["stroke_id"], "host_id": host_row["stroke_id"],
               "guest_representation": deepcopy(guest_row["representation"]),
               "finite_host_representation": deepcopy(host_row["representation"]),
               "source_node_id": terminal["node_id"], "guest_source_port": list(terminal["port"]),
               "pass": False, "source_pixels_modified": False, "new_geometry_generated": False,
               "observation_expansions": [], "failure_reasons": []}
    try:
        guest, host = _points(guest_row["representation"]), _points(host_row["representation"])
        endpoint = np.asarray(terminal["native_endpoint_px"], float)
        end_index = min((0, len(guest) - 1), key=lambda i: float(np.linalg.norm(guest[i] - endpoint)))
        adjacent_index = 1 if end_index == 0 else end_index - 1
        terminal_length = float(np.linalg.norm(endpoint - guest[adjacent_index]))
        outward = _unit(endpoint - guest[adjacent_index])
        hd, hi, hf, _ = _point_distances([endpoint], host)
        precision = POLICY["native_coordinate_precision_px"]
        finite_contact = bool(np.linalg.norm(guest[end_index] - endpoint) <= precision and hd[0] <= precision)
        guest_check, host_check = _source_centerline_check(source, guest), _source_centerline_check(source, host)
        observations = _observations(graph, terminal["port"])
        for obs in observations:
            p = np.asarray(obs["source_points_px"])
            if obs["chord_px"] > 0:
                obs["outward_source_direction"] = _unit(p[0] - p[-1]).tolist()
                obs["native_direction_deviation_deg"] = math.degrees(math.acos(float(np.clip(
                    np.asarray(obs["outward_source_direction"]) @ outward, -1, 1))))
        receipt.update(actual_native_endpoint_px=endpoint.tolist(), actual_outward_tangent=outward.tolist(),
                       actual_native_terminal_segment_length_px=terminal_length,
                       finite_host_contact={"pass": finite_contact, "segment_index": int(hi[0]),
                                            "fraction": float(hf[0]), "distance_px": float(hd[0])},
                       guest_object_to_source=guest_check, host_object_to_source=host_check,
                       all_finite_source_direction_observations=observations)
        host_ports = [p for p in graph.nodes[terminal["node_id"]]["edges"]
                      if p[0] in host_row["source_graph_edge_ids"]]
        gw = _width(source, graph, [terminal["port"]], guest_row, component_rows, extra_exclusion_paths)
        hw = _width(source, graph, host_ports, host_row, component_rows, extra_exclusion_paths)
        receipt["independent_width_evidence"] = {"guest": gw, "host": hw}
        width_valid = gw["pass"] and hw["pass"]
        intervals = [gw["half_width_interval_px"], hw["half_width_interval_px"]] if width_valid else None
        host_axis = _unit(host[int(hi[0]) + 1] - host[int(hi[0])])
        separation = abs(float(outward[0] * host_axis[1] - outward[1] * host_axis[0]))
        if width_valid and separation > 0:
            radius = int(math.ceil(max(intervals[0][1] + math.sqrt(.5),
                                       (intervals[1][1] + math.sqrt(.5)) / separation))) + 1
        else:
            radius = int(POLICY["maximum_width_section_half_span_px"])
        radius = min(radius, POLICY["maximum_observation_radius_px"])
        while True:
            patch, black, own, boundary, white, labels = _patch(source, graph, endpoint, radius)
            dg, dh = _cell_min_distances(black, guest), _cell_min_distances(black, host)
            possible = ((dg < intervals[0][1]) | (dh < intervals[1][1])) if width_valid else np.zeros(len(black), bool)
            unknown_exit = own & boundary & ~possible
            expansion = {"radius_px": radius, "raw_box_xyxy_px": patch["raw_box_xyxy_px"],
                         "unknown_boundary_cells": black[unknown_exit].tolist(),
                         "explained_shaft_exit_cells": black[own & boundary & possible].tolist(),
                         "source_or_roi_truncated": patch["source_or_roi_truncated"]}
            receipt["observation_expansions"].append(expansion)
            if (not width_valid or not np.any(unknown_exit) or patch["source_or_roi_truncated"]
                    or radius >= POLICY["maximum_observation_radius_px"]):
                break
            radius = min(radius * 2, POLICY["maximum_observation_radius_px"])
        receipt["original_patch"] = patch
        receipt["observation_closed"] = bool(width_valid and not np.any(unknown_exit)
                                             and not patch["source_or_roi_truncated"])
        own_black = black[own]
        models = _coherent_models(own_black, white, guest, host, intervals) if width_valid else None
        receipt["coherent_terminal_models"] = models
        selected = models["feasible_models"][0] if models and models["pass"] else None
        core = graph.xy(graph.nodes[terminal["node_id"]]["pixels"])
        old_low, old_high = np.floor(core.min(axis=0) - 2), np.ceil(core.max(axis=0) + 3)
        ledger = []
        for index, cell in enumerate(black):
            compatible = []
            if not own[index]:
                compatible = ["DISCONNECTED_NEIGHBOR_ORIGINAL_INK"]
            elif selected:
                if dg[index] <= selected["guest_half_width_px"]:
                    compatible.append(_pixel_role(cell, guest, "GUEST"))
                if dh[index] <= selected["host_half_width_px"]:
                    compatible.append(_pixel_role(cell, host, "FINITE_HOST"))
            elif width_valid:
                if dg[index] < intervals[0][1]:
                    compatible.append("GUEST_INDIVIDUALLY_POSSIBLE_NOT_A_JOINT_PROOF")
                if dh[index] < intervals[1][1]:
                    compatible.append("FINITE_HOST_INDIVIDUALLY_POSSIBLE_NOT_A_JOINT_PROOF")
            if not compatible:
                compatible = ["UNEXPLAINED_INK" if width_valid else "WIDTH_NOT_ESTABLISHED"]
            ledger.append({"source_cell": cell.tolist(), "original_gray_value": int(source[cell[1], cell[0]]),
                           "component_label": int(labels[index]), "junction_connected": bool(own[index]),
                           "actual_guest_outward_axis_projection_px": float((cell - endpoint) @ outward),
                           "guest_cell_min_distance_px": float(dg[index]), "finite_host_cell_min_distance_px": float(dh[index]),
                           "finite_host_center_distance_px": float(_point_distances([cell], host)[0][0]),
                           "inside_legacy_core_check_box": bool(np.all(cell >= old_low) and np.all(cell < old_high)),
                           "compatible_responsibilities": compatible,
                           "shared_by_guest_and_host_in_selected_model": bool(selected and own[index]
                               and dg[index] <= selected["guest_half_width_px"] and dh[index] <= selected["host_half_width_px"])})
        receipt["pixel_ledger"] = ledger
        residual = black[own & ~possible] if width_valid else np.empty((0, 2), int)
        receipt["unexplained_original_cells"] = residual.tolist()
        receipt["junction_normalization"] = {
            "convention": POLICY["endpoint_convention"], "physical_hidden_pen_travel": "NOT_IDENTIFIABLE",
            "physical_subpixel_termination_identifiable": False,
            "outward_ink_inside_independent_finite_junction": black[own & possible & ((black - endpoint) @ outward > 0)].tolist(),
            "outside_junction_ink_never_normalized_away": True,
            "all_feasible_terminal_models_have_same_finite_CAD_endpoint": bool(models and models["pass"])}
        extensions = {"events": [], "resource_truncated": False, "search_complete": False,
                      "unobserved_extensions_ruled_out": False, "distinct_observable_boundary_exists": False,
                      "pass_to_adopt_new_geometry": False, "status": "NO_OBSERVABLE_OUTSIDE_JUNCTION_RESIDUAL"}
        if not width_valid:
            extensions["status"] = "NOT_RUN_INDEPENDENT_WIDTH_NOT_ESTABLISHED"
        elif not receipt["observation_closed"]:
            extensions["status"] = "NOT_RUN_OBSERVATION_NOT_CLOSED"
        elif models["resource_truncated"]:
            extensions.update(status="NOT_RUN_TERMINAL_MODEL_RESOURCE_LIMIT", resource_truncated=True)
        elif terminal_length < POLICY["minimum_native_terminal_direction_chord_px"]:
            extensions["status"] = "NOT_RUN_UNSUPPORTED_NATIVE_TERMINAL_DIRECTION"
        elif len(residual):
            extensions = _extensions(source, own_black, white, guest, host, end_index, outward, intervals, residual)
        receipt["short_continuation_competition"] = extensions
        failures = receipt["failure_reasons"]
        if not finite_contact or not guest_check["pass"] or not host_check["pass"]:
            failures.append("REJECTED_SOURCE_OR_FINITE_CONTACT_CONTRADICTION")
        if terminal_length < POLICY["minimum_native_terminal_direction_chord_px"]:
            failures.append("PENDING_NATIVE_TERMINAL_DIRECTION_OUTSIDE_FINITE_MODEL")
        if not width_valid:
            failures.append("PENDING_WIDTH_NOT_INDEPENDENTLY_ESTABLISHED")
        if width_valid and (not receipt["observation_closed"] or models["resource_truncated"] or extensions["resource_truncated"]):
            failures.append("PENDING_OBSERVATION_TRUNCATED")
        if extensions["distinct_observable_boundary_exists"]:
            failures.append("PENDING_BOUNDARY_COMPETITION")
        if width_valid and len(residual):
            failures.append("PENDING_UNEXPLAINED_INK")
        if width_valid and not models["pass"] and not len(residual):
            failures.append("PENDING_NO_COHERENT_ROUND_CAP_MODEL")
        receipt["pass"] = not failures
        receipt["junction_normalization"]["canonical_native_endpoint_proved"] = not failures
        receipt["status"] = failures[0] if failures else "PROVED_TERMINAL"
        receipt["reason"] = receipt["status"]
        receipt["complete_pixel_accounting"] = len(ledger) == int(np.asarray(patch["raw_ink_mask"]).sum())
    except (ValueError, KeyError, IndexError) as exc:
        receipt.update(status="PENDING_RAW_ATTACHMENT_MODEL_INPUT", reason=str(exc), pass_=False)
        receipt["pass"] = receipt.pop("pass_")
        receipt["failure_reasons"].append(str(exc))
    return receipt
