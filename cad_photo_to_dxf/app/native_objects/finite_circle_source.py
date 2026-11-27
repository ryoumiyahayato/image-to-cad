"""Actual CIRCLE geometry, finite source arcs and independently bounded radii.

The historical sampled source contract is replayed separately. Exact circle
queries use radial algebra, never chords. A receipt authorizes only its stated
source cells and radial observations, not an unexamined whole drawing.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math

from . import attached_stroke_component as component
from . import attached_stroke_width_exact as exact
from .circular_markers import verify_circle_source_evidence
from .finite_source_ports import _runs, cells_from_runs

SCHEMA = "independent-actual-circle-finite-source-arc-v1"
POLICY = {"source_threshold": 128, "radial_half_angle_denominator": 16,
          "maximum_section_half_span_px": 12, "minimum_independent_sections": 2,
          "algebraic_enclosure_bits": 128, "maximum_query_cells": 131072,
          "radial_interval_role": "CONSERVATIVE_OUTER_BOUND_REQUIRING_EXACT_BLACK_WHITE_RECHECK",
          "circle_replaced_by_chords": False, "legacy_sampled_pass_is_exact_approval": False}
F = Fraction


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _q(value):
    if isinstance(value, dict):
        return exact.decode_rational(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return F(int(value[0]), int(value[1]))
    return exact.rational(value)


def _enc(point):
    return [exact.encode_rational(v) for v in point]


def circle_geometry(row):
    if row.get("curve_type", row.get("kind")) != "CIRCLE":
        raise ValueError("EXACT_CIRCLE_ENTRY_REQUIRES_ACTUAL_CIRCLE_TYPE")
    center = tuple(_q(v) for v in row["circle_center_exact"])
    radius = _q(row["circle_radius_exact"])
    if len(center) != 2 or radius <= 0:
        raise ValueError("INVALID_ACTUAL_CIRCLE_GEOMETRY")
    return center, radius


def circle_source_geometry_row(source_object):
    geometry = source_object["geometry"].get("circle_geometry", source_object["geometry"])
    center = tuple(exact.rational(v) for v in geometry["center"])
    radius = exact.rational(geometry["radius_px"])
    return {"object_id": source_object["id"], "parent_object_id": source_object["id"],
        "kind": "CIRCLE", "curve_type": "CIRCLE", "curve_geometry_supported": True,
        "circle_center_exact": _enc(center), "circle_radius_exact": exact.encode_rational(radius),
        "geometry_origin": "SOURCE_STAGE", "actual_saved_geometry": False,
        "curve_replaced_by_chords": False}


def _cell_radial_squared(center, cell):
    p = tuple(exact.rational(v) for v in cell)
    low = sum(max(F(0), abs(p[k] - center[k]) - F(1, 2)) ** 2 for k in (0, 1))
    high = sum((abs(p[k] - center[k]) + F(1, 2)) ** 2 for k in (0, 1))
    return low, high


def _radial_within(d2, radius, squared_half_width):
    s = exact.rational(squared_half_width)
    if s < 0:
        raise ValueError("NEGATIVE_CIRCLE_SQUARED_HALF_WIDTH")
    difference = d2 + radius * radius - s
    return difference <= 0 or difference * difference <= 4 * radius * radius * d2


def circle_cell_intersects(row, cell, squared_half_width):
    """Closed native annulus intersects a closed source pixel, exactly."""
    if exact.rational(squared_half_width) < 0:
        raise ValueError("NEGATIVE_CIRCLE_SQUARED_HALF_WIDTH")
    center, radius = circle_geometry(row)
    low, high = _cell_radial_squared(center, cell)
    if low <= radius * radius <= high:
        return True
    return _radial_within(low if low > radius * radius else high, radius, squared_half_width)


def circle_point_strictly_outside(row, point, squared_half_width):
    """Exact strict exclusion; algebraic roots are eliminated by sign tests."""
    center, radius = circle_geometry(row)
    p = tuple(exact.rational(v) for v in point)
    return not _radial_within(sum((v - c) ** 2 for v, c in zip(p, center)), radius, squared_half_width)


def _sqrt_bounds(value):
    value = exact.rational(value)
    if value < 0:
        raise ValueError("NEGATIVE_RADICAL")
    scale = 1 << POLICY["algebraic_enclosure_bits"]
    integer = math.isqrt(value.numerator * scale * scale // value.denominator)
    low = F(integer, scale)
    return low, low if low * low == value else F(integer + 1, scale)


def _radial_distance_bounds(d2, radius):
    low, high = _sqrt_bounds(d2)
    minimum = F(0) if low <= radius <= high else min(abs(low - radius), abs(high - radius))
    maximum = max(abs(low - radius), abs(high - radius))
    return minimum * minimum, maximum * maximum


def _cell_distance_bounds(row, cell, *, maximum):
    center, radius = circle_geometry(row)
    low, high = _cell_radial_squared(center, cell)
    if maximum:
        a, b = _radial_distance_bounds(low, radius), _radial_distance_bounds(high, radius)
        return max(a[0], b[0]), max(a[1], b[1])
    if low <= radius * radius <= high:
        return F(0), F(0)
    return _radial_distance_bounds(low if low > radius * radius else high, radius)


def _radial_directions():
    denominator = POLICY["radial_half_angle_denominator"]
    result = set()
    for k in range(-denominator, denominator + 1):
        t = F(k, denominator)
        x, y = (1 - t * t) / (1 + t * t), 2 * t / (1 + t * t)
        result.add((x, y))
        result.add((-x, y))
    return sorted(result)


def _in_scope(point, scope, pad=0):
    return scope[0] - pad <= point[0] <= scope[2] + pad and scope[1] - pad <= point[1] <= scope[3] + pad


def _radial_sections(source, row, scope, ring_cells, other_rows, forbidden_core_cells):
    center, radius = circle_geometry(row)
    curves = [other for other in other_rows if other.get("curve_type", other.get("kind")) == "CIRCLE"
              and other.get("object_id", other.get("stroke_id")) != row["object_id"]]
    others = [component._points(other) for other in other_rows
              if other.get("curve_type", other.get("kind")) != "CIRCLE"]
    forbidden = set(tuple(p) for p in forbidden_core_cells)
    records = []
    for direction in _radial_directions():
        q = tuple(center[k] + radius * direction[k] for k in (0, 1))
        # The fixed 12-pixel observation reach also bounds which finite arcs
        # may contribute an independent width to this component window.
        if not _in_scope(q, scope, 12):
            continue
        tangent = -direction[1], direction[0]
        a, b = tuple(q[k] - tangent[k] for k in (0, 1)), tuple(q[k] + tangent[k] for k in (0, 1))
        section = exact.measure_section(source, q, a, b, other_paths=others,
            forbidden_core_cells=forbidden, source_threshold=128, half_span=12)
        section.update(curve_type="ACTUAL_CIRCLE_RADIAL_SECTION", radial_unit_direction_exact=_enc(direction),
            circle_center_exact=_enc(center), circle_radius_exact=exact.encode_rational(radius),
            tangent_section_is_not_a_chord_approximation=True)
        if "independent_black_cells" not in section or "first_white_cells" not in section:
            records.append(section)
            continue
        own, white = section["independent_black_cells"], section["first_white_cells"]
        # Outer bounds contain every radius satisfying the algebraic original
        # observations. They may not certify a chosen radius by themselves:
        # final own-black intersection and common-white exclusion stay exact.
        black_bounds = [_cell_distance_bounds(row, cell, maximum=False) for cell in own]
        white_bounds = [_cell_distance_bounds(row, cell, maximum=True) for cell in white]
        lo, hi = max(v[0] for v in black_bounds), min(v[1] for v in white_bounds)
        section["historical_tangent_squared_interval_not_used"] = section["half_width_squared_interval"]
        section["half_width_squared_interval"] = exact.encode_interval(lo, hi)
        section["half_width_interval_px_approx"] = [math.sqrt(float(lo)), math.sqrt(float(hi))]
        section["radial_algebraic_cell_bounds"] = [
            {"cell": list(cell), "constraint": kind, "distance_squared_enclosure":
                [exact.encode_rational(low), exact.encode_rational(high)],
             "radial_squared_cell_interval": [exact.encode_rational(v) for v in _cell_radial_squared(center, cell)]}
            for cells, values, kind in ((own, black_bounds, "BLACK_MIN_DISTANCE"), (white, white_bounds, "WHITE_MAX_DISTANCE"))
            for cell, (low, high) in zip(cells, values)]
        section["algebraic_enclosure_bits"] = POLICY["algebraic_enclosure_bits"]
        section["pass"] = False
        section["independent"] = section["constraint_eligible"] = False
        nearest_other = min((exact.point_polyline_distance_squared(q, path) for path in others), default=None)
        source_cells = {tuple(p) for p in section["section_source_cells"]}
        if any(tuple(p) not in ring_cells for p in own):
            section["reason"] = "RADIAL_SECTION_CONTAINS_INK_OUTSIDE_REPLAYED_ORIGINAL_RING"
        elif (source_cells & forbidden or (nearest_other is not None and not exact.strictly_clear_of_other_axis(nearest_other, hi))
              or any(not circle_point_strictly_outside(curve, q, 8 * hi + 1) for curve in curves)):
            section["reason"] = "RADIAL_SECTION_NOT_INDEPENDENT_OF_CORE_OR_OTHER_FINITE_AXIS"
        elif hi >= 144:
            section["reason"] = "RADIAL_SECTION_OBSERVATION_TRUNCATED"
        else:
            section["independent"] = section["constraint_eligible"] = True
            section["pass"] = lo < hi
            section["reason"] = "INDEPENDENT_ACTUAL_CIRCLE_RADIAL_SECTION" if lo < hi else "INDIVIDUAL_RADIAL_SECTION_INTERVAL_EMPTY"
        records.append(section)
    result = exact.intersect_sections(records, min_sections=2)
    result.update(sections=records, fixed_radial_direction_count=len(_radial_directions()),
        finite_radial_sections_enumerated=len(records), all_eligible_sections_retained=True,
        straight_tangent_width_not_transferred_to_circle=True,
        radial_interval_role=POLICY["radial_interval_role"],
        selected_radius_requires_exact_section_black_and_white_recheck=True)
    return result


def _bind_actual_circle(source, row, obj, roi, dpi):
    center, radius = circle_geometry(row)
    geometry = obj["geometry"].get("circle_geometry", obj["geometry"])
    original_center = tuple(exact.rational(v) for v in geometry["center"])
    original_radius = exact.rational(geometry["radius_px"])
    failures = []
    if row.get("parent_object_id", row.get("object_id")) != obj.get("id"):
        failures.append("ACTUAL_CIRCLE_PRIOR_ID_MISMATCH")
    if row.get("actual_saved_geometry"):
        scale = 25.4 / float(dpi)
        expected_center = (F((float(original_center[0]) - roi[0]) * scale),
                           F((roi[3] - float(original_center[1])) * scale))
        expected_radius = F(float(original_radius) * scale)
        if (tuple(_q(v) for v in row.get("native_mm_circle_center_exact", [])) != expected_center or
                _q(row.get("native_mm_circle_radius_exact", 0)) != expected_radius):
            failures.append("ACTUAL_SAVED_CIRCLE_NATIVE_MM_GEOMETRY_DIFFERS_FROM_BOUND_PRIOR")
        transformed_center = (expected_center[0] / F(scale) + roi[0], roi[3] - expected_center[1] / F(scale))
        if center != transformed_center or radius != expected_radius / F(scale):
            failures.append("ACTUAL_CIRCLE_SOURCE_COORDINATES_DO_NOT_MATCH_MM_TRANSFORM")
        # An actual transformed circle is still a circle. Its resulting mm
        # geometry is the identity check; the complete transform is retained.
        if "actual_insert_transform_chain" not in row:
            failures.append("ACTUAL_CIRCLE_TRANSFORM_RECEIPT_MISSING")
    elif (row.get("geometry_origin") != "SOURCE_STAGE" or center != original_center or radius != original_radius):
        failures.append("SOURCE_STAGE_CIRCLE_GEOMETRY_DIFFERS_FROM_PRIOR")
    legacy = verify_circle_source_evidence(source, roi, obj)
    if not legacy["pass"]:
        failures.append("HISTORICAL_CIRCLE_SOURCE_IDENTITY_REPLAY_FAILED")
    return {"pass": not failures, "reasons": failures, "legacy_sampled_contract_replay": legacy,
            "legacy_sampled_pass_is_new_exact_approval": False, "complete_prior_source_object_sha256": _digest(obj),
            "actual_circle_geometry_sha256": _digest(row), "original_source_pixels_modified": False}


def certify_finite_circle_source(source, saved_circle_row, source_object, scope, *, roi, dpi,
                                 other_rows=(), forbidden_core_cells=()):
    """Return source arcs, radial bounds and exact geometry as separate claims."""
    receipt = {"schema": SCHEMA, "policy": dict(POLICY), "pass": False, "failures": [],
        "whole_circle_exact_source_approval": False, "circle_replaced_by_chords": False,
        "independent_union_model_required": True}
    try:
        center, radius = circle_geometry(saved_circle_row)
        scope = list(map(int, scope))
        if len(scope) != 4 or not (0 <= scope[0] < scope[2] <= source.shape[1] and 0 <= scope[1] < scope[3] <= source.shape[0]):
            raise ValueError("FINITE_CIRCLE_SCOPE_OUTSIDE_ORIGINAL_SOURCE")
        binding = _bind_actual_circle(source, saved_circle_row, source_object, roi, dpi)
        receipt["source_identity_binding"] = binding
        if not binding["pass"]:
            receipt["failures"].extend(binding["reasons"])
            return receipt
        ring = cells_from_runs(source_object["source_evidence"]["ring_support_runs_y_x0_x1"])
        width = _radial_sections(source, saved_circle_row, scope, ring, other_rows, forbidden_core_cells)
        query = {(x, y) for y in range(scope[1], scope[3]) for x in range(scope[0], scope[2])}
        query.update(tuple(p) for section in width["sections"] for p in section.get("section_source_cells", []))
        if len(query) > POLICY["maximum_query_cells"]:
            raise ValueError("FINITE_CIRCLE_SOURCE_QUERY_RESOURCE_BOUND")
        positive_white, boundary_white, original_black = [], [], []
        for cell in sorted(query):
            x, y = cell
            if not (0 <= x < source.shape[1] and 0 <= y < source.shape[0]):
                raise ValueError("FINITE_CIRCLE_RADIAL_READ_OUTSIDE_SOURCE")
            low, high = _cell_radial_squared(center, cell)
            if source[y, x] < 128:
                original_black.append(list(cell))
            elif low < radius * radius < high:
                positive_white.append(list(cell))
            elif low <= radius * radius <= high:
                boundary_white.append(list(cell))
        if positive_white:
            receipt["failures"].append("ACTUAL_FINITE_CIRCLE_ARC_HAS_POSITIVE_LENGTH_WHITE_INTERIOR")
        if not width["pass"]:
            receipt["failures"].append("INDEPENDENT_FINITE_CIRCLE_RADIAL_WIDTH_NOT_ESTABLISHED")
        body = {**deepcopy(saved_circle_row), "stroke_id": saved_circle_row["object_id"],
            "body_role": "NECESSARY_PRIOR_CIRCLE_ARC", "width": width,
            "finite_arc_domain": {"model_window": scope, "authorized_query_cells_y_x0_x1": _runs(query),
                                  "parameterization": "ACTUAL_CIRCLE_RESTRICTED_TO_DECLARED_SOURCE_CELLS"},
            "authorized_original_ring_cells_y_x0_x1": _runs(ring & query),
            "complete_prior_source_object_sha256": binding["complete_prior_source_object_sha256"],
            "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest()}
        receipt.update(row=body, width=width, actual_circle_center_exact=_enc(center),
            actual_circle_radius_exact=exact.encode_rational(radius),
            actual_insert_transform_chain=saved_circle_row.get("actual_insert_transform_chain", []),
            finite_arc_domain=body["finite_arc_domain"], original_black_cells=original_black,
            original_white_cells=[list(p) for p in sorted(query) if source[p[1], p[0]] >= 128],
            authorized_original_ring_cells_y_x0_x1=body["authorized_original_ring_cells_y_x0_x1"],
            positive_length_white_arc_cells=positive_white, zero_length_white_circle_contacts=boundary_white,
            original_contact_ports=deepcopy(source_object["source_evidence"]["contact_ports"]),
            exact_finite_arc_centerline_support_pass=not positive_white)
        receipt["pass"] = not receipt["failures"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        receipt["failures"].append(str(exc))
    receipt["status"] = "FINITE_ACTUAL_CIRCLE_ARC_AND_RADIAL_BOUNDS_ESTABLISHED" if receipt["pass"] else "PENDING_FINITE_ACTUAL_CIRCLE_SOURCE"
    return receipt


def circle_query_is_authorized(row, cell):
    """Scope check kept separate from the pure native-geometry predicates."""
    return tuple(cell) in cells_from_runs(row["finite_arc_domain"]["authorized_query_cells_y_x0_x1"])
