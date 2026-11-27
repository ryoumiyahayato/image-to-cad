"""Fixed independently bounded knots; numerical proposals require exact replay.

The module name is retained for callers, but the family has an explicit v3
identity. No optimizer result by itself certifies geometry or observations.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import attached_stroke_width_exact as exact
from . import bounded_stroke_field as kernel

SCHEMA = "source-bounded-continuous-squared-width-field-v3-independent-knots"
SOLVER_SCHEMA = "coherent-bounded-finite-union-v3-independent-knots"
F = Fraction
MAX_STATES = kernel.MAX_STATES
ALPHA_BITS = kernel.ALPHA_BITS
NUMERICAL_LIMITS = {"maximum_parameters": 512, "maximum_unique_queries": 100000,
    "maximum_quadratic_parts": 1000000, "maximum_dense_jacobian_entries": 4000000}
point_cost = kernel.point_cost
cell_cost = kernel.cell_cost
cell_compatible_with_strict_upper = kernel.cell_compatible_with_strict_upper
box_lower_distance_squared = kernel.box_lower_distance_squared


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _enc(value):
    return exact.encode_rational(value)


def _dec(value):
    return exact.decode_rational(value) if isinstance(value, dict) else exact.rational(value)


def _ep(point):
    return [_enc(v) for v in point]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _turn(a, b, c):
    u = tuple(b[k] - a[k] for k in (0, 1))
    v = tuple(c[k] - b[k] for k in (0, 1))
    return u[0] * v[1] != u[1] * v[0] or sum(u[k] * v[k] for k in (0, 1)) <= 0


def _cell(values):
    values = tuple(_dec(v) for v in values)
    if len(values) != 2 or any(v.denominator != 1 for v in values):
        raise ValueError("SOURCE_CELL_COORDINATES_MUST_BE_INTEGERS")
    return tuple(int(v) for v in values)


def _section_observations(width):
    result = []
    for index, section in enumerate(width.get("sections", [])):
        cells, values = section.get("section_source_cells", []), section.get("original_values", [])
        if len(cells) != len(values):
            raise ValueError("SECTION_SOURCE_OBSERVATION_LENGTH_MISMATCH")
        whites = [list(_cell(cell)) for cell, value in zip(cells, values) if value >= 128]
        whites.extend(list(_cell(cell)) for cell in section.get("first_white_cells", []))
        result.append({"section_index": index, "constraint_eligible": bool(section.get("constraint_eligible")),
            "owned_black_cells": [list(_cell(cell)) for cell in section.get("independent_black_cells", [])]
                if section.get("constraint_eligible") else [],
            "all_actually_measured_white_cells": [list(cell) for cell in dict.fromkeys(map(tuple, whites))],
            "original_section_observations_sha256": _digest({"cells": cells, "values": values})})
    return result


def build_width_field(points, width, *, junction_points=()):
    """Freeze source/geometry knots and bounds before fitting residual pixels."""
    result = {"schema": SCHEMA, "pass": False, "producer_sha256": producer_sha256(),
        "exact_kernel_sha256": kernel.producer_sha256(),
        "family": "CONTINUOUS_PRODUCT_OF_FIXED_INDEPENDENT_KNOT_INTERVALS",
        "selection_uses_residual_pixels": False, "all_eligible_sections_retained": True,
        "alpha_lower": _enc(F(0)), "alpha_upper": _enc(F(1)), "alpha_upper_open": True,
        "knots": [], "pieces": []}
    try:
        old = kernel.build_width_field(points, width)
        result["original_constant_and_v1_diagnostic"] = {
            key: old.get(key) for key in ("pass", "reason", "family", "recomputed_constant_intersection")}
        if not old["pass"]:
            raise ValueError("INDEPENDENT_SECTION_INPUT_NOT_ESTABLISHED:" + old.get("reason", "UNKNOWN"))
        points = [tuple(exact.rational(v) for v in point) for point in points]
        positions = [F(0)]
        for a, b in zip(points, points[1:]):
            positions.append(positions[-1] + sum(abs(b[k] - a[k]) for k in (0, 1)))
        observations = old["knots"]
        global_low = min(_dec(k["lower"]) for k in observations)
        global_high = max(_dec(k["upper"]) for k in observations)
        result["independent_global_squared_width_range"] = {
            "lower": _enc(global_low), "upper": _enc(global_high), "upper_open": True,
            "calibration": "ALL_OWN_INDEPENDENT_SECTIONS_BEFORE_RESIDUAL_MODEL_CHECK"}
        result["eligible_section_indices"] = list(old["eligible_section_indices"])
        result["section_observations"] = _section_observations(width)
        knots = {}

        def add(s, q, low, high, role, source_index=None):
            item = knots.setdefault(s, {"point": q, "low": low, "high": high,
                                        "roles": [], "section_indices": []})
            if item["point"] != q:
                raise ValueError("INCONSISTENT_FINITE_PATH_POSITION")
            item["low"], item["high"] = max(item["low"], low), min(item["high"], high)
            if not item["low"] < item["high"]:
                raise ValueError("EMPTY_COINCIDENT_WIDTH_KNOT_INTERVAL")
            if role not in item["roles"]:
                item["roles"].append(role)
            if source_index is not None:
                item["section_indices"].append(source_index)

        for item in observations:
            add(_dec(item["path_position_l1_exact"]), tuple(_dec(v) for v in item["center_exact"]),
                _dec(item["lower"]), _dec(item["upper"]), "INDEPENDENT_SECTION", item["section_index"])
        geometric_controls = []
        for i, point in enumerate(points):
            if i in (0, len(points) - 1) or _turn(points[i - 1], point, points[i + 1]):
                role = "FINITE_ENDPOINT" if i in (0, len(points) - 1) else "ACTUAL_FINITE_DIRECTION_CHANGE"
                add(positions[i], point, global_low, global_high, role)
                geometric_controls.append(i)
        for point in junction_points:
            q = tuple(exact.rational(v) for v in point)
            distance, segment, fraction, projection = exact.project_point_polyline(q, points)
            if distance or projection != q:
                raise ValueError("JUNCTION_WIDTH_CONTROL_NOT_ON_ACTUAL_FINITE_BODY")
            s = positions[segment] + fraction * (positions[segment + 1] - positions[segment])
            add(s, q, global_low, global_high, "CALLER_PROVED_FINITE_SOURCE_JUNCTION")
        ordered = sorted(knots)
        result["geometry_control_vertex_indices"] = geometric_controls
        result["pure_collinear_encoding_vertices_add_width_knots"] = False
        result["junction_control_requires_fresh_caller_proof"] = True
        result["parameter_count"] = len(ordered)
        result["knots"] = [{"parameter_index": i, "parameter_id": f"knot-{i:04d}",
            "path_position_l1_exact": _enc(s), "center_exact": _ep(knots[s]["point"]),
            "lower": _enc(knots[s]["low"]), "upper": _enc(knots[s]["high"]),
            "roles": knots[s]["roles"], "section_indices": knots[s]["section_indices"]}
            for i, s in enumerate(ordered)]

        def weights_at(s):
            if s in knots:
                return {ordered.index(s): F(1)}
            i = bisect_right(ordered, s) - 1
            t = (s - ordered[i]) / (ordered[i + 1] - ordered[i])
            return {i: 1 - t, i + 1: t}

        def center(s):
            i = min(bisect_right(positions, s) - 1, len(points) - 2)
            t = (s - positions[i]) / (positions[i + 1] - positions[i])
            return tuple(points[i][k] + t * (points[i + 1][k] - points[i][k]) for k in (0, 1))

        def encode_weights(weights):
            return [{"knot_index": i, "weight": _enc(w)} for i, w in weights.items()]

        def endpoint(weights, key):
            return sum((w * knots[ordered[i]][key] for i, w in weights.items()), F(0))

        breaks = sorted(set(positions + ordered))
        for a, b in zip(breaks, breaks[1:]):
            start, end = weights_at(a), weights_at(b)
            delta = {i: end.get(i, F(0)) - start.get(i, F(0)) for i in set(start) | set(end)}
            slope_low = sum((w * knots[ordered[i]]["low" if w >= 0 else "high"]
                             for i, w in delta.items()), F(0)) / (b - a)
            slope_high = sum((w * knots[ordered[i]]["high" if w >= 0 else "low"]
                              for i, w in delta.items()), F(0)) / (b - a)
            result["pieces"].append({"a": _ep(center(a)), "b": _ep(center(b)),
                "path_position_start_l1_exact": _enc(a), "path_position_end_l1_exact": _enc(b),
                "start_knot_weights": encode_weights(start), "end_knot_weights": encode_weights(end),
                "lower_start": _enc(endpoint(start, "low")), "lower_end": _enc(endpoint(end, "low")),
                "upper_start": _enc(endpoint(start, "high")), "upper_end": _enc(endpoint(end, "high")),
                "squared_width_slope_enclosure": {"lower": _enc(slope_low), "upper": _enc(slope_high),
                    "derived_from_fixed_knot_product_box": True}})
        result.update({"pass": True, "status": "INDEPENDENT_KNOT_CONTINUOUS_FINITE_FIELD_ESTABLISHED",
            "continuity": "AFFINE_SQUARED_RADIUS_AT_FIXED_OBSERVATION_AND_FINITE_GEOMETRY_KNOTS",
            "end_cap": "FINITE_ROUND_CAP_WITH_ENDPOINT_FIELD_RADIUS", "extra_junction_ink_radius": None,
            "path_position": "CUMULATIVE_ACTUAL_FINITE_NATIVE_L1_LENGTH_IN_SOURCE_COORDINATES",
            "geometry_changed": False, "source_completeness_separately_required": True})
        prepare_field(result)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        result.update({"pass": False, "status": "BOUNDED_FIELD_NOT_ESTABLISHED", "reason": str(exc)})
    return result


def _weights(rows, count):
    values = {}
    for row in rows:
        i, value = row["knot_index"], _dec(row["weight"])
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < count or value <= 0 or i in values:
            raise ValueError("INVALID_FIXED_KNOT_INTERPOLATION_WEIGHT")
        values[i] = value
    if sum(values.values(), F(0)) != 1:
        raise ValueError("FIXED_KNOT_WEIGHTS_DO_NOT_SUM_EXACTLY_TO_ONE")
    return tuple(sorted(values.items()))


@dataclass(frozen=True)
class Polyline:
    field: dict
    bounds: tuple
    pieces: tuple
    weights: tuple
    upper: kernel.PreparedField

    def selected(self, values):
        radii = tuple(lo + value * (hi - lo) for (lo, hi), value in zip(self.bounds, values))
        pieces = []
        for original, (start, end) in zip(self.pieces, self.weights):
            r0 = sum((weight * radii[i] for i, weight in start), F(0))
            r1 = sum((weight * radii[i] for i, weight in end), F(0))
            pieces.append(kernel.Piece(original.a, original.b, r0, r1, r0, r1))
        return kernel.PreparedField(tuple(pieces), None, self.upper.box, max(radii))


def _polyline(field):
    if field.get("schema") != SCHEMA or not field.get("pass"):
        raise ValueError("UNSUPPORTED_INDEPENDENT_KNOT_FIELD")
    count = field["parameter_count"]
    if count != len(field["knots"]) or count < 2:
        raise ValueError("INVALID_FIXED_KNOT_PARAMETER_COUNT")
    bounds = []
    for i, row in enumerate(field["knots"]):
        lo, hi = _dec(row["lower"]), _dec(row["upper"])
        if row["parameter_index"] != i or not 0 <= lo < hi:
            raise ValueError("INVALID_FIXED_KNOT_INTERVAL_OR_IDENTITY")
        bounds.append((lo, hi))
    pieces, weights = [], []
    for row in field["pieces"]:
        a, b = (tuple(_dec(v) for v in row[key]) for key in ("a", "b"))
        if len(a) != 2 or len(b) != 2 or a == b:
            raise ValueError("INVALID_FINITE_FIELD_PIECE")
        start, end = (_weights(row[key], count) for key in ("start_knot_weights", "end_knot_weights"))
        vals = [sum((w * bounds[i][j] for i, w in weight_set), F(0))
                for j in (0, 1) for weight_set in (start, end)]
        for key, value in zip(("lower_start", "lower_end", "upper_start", "upper_end"), vals):
            if _dec(row[key]) != value:
                raise ValueError("FIELD_ENVELOPE_DISAGREES_WITH_FIXED_KNOT_WEIGHTS")
        pieces.append(kernel.Piece(a, b, *vals))
        weights.append((start, end))
    native_count = field.get("diagnostic_extension", {}).get("native_piece_count", len(pieces))
    if not pieces or not 1 <= native_count <= len(pieces):
        raise ValueError("EMPTY_NATIVE_FINITE_FIELD")
    if any(a.b != b.a or wa[1] != wb[0] for a, b, wa, wb in
           zip(pieces[:native_count - 1], pieces[1:native_count], weights[:native_count - 1], weights[1:native_count])):
        raise ValueError("DISCONTINUOUS_FIXED_KNOT_FIELD")
    if native_count < len(pieces):
        extension = field["diagnostic_extension"]
        if len(pieces) != native_count + 1 or extension.get("status") != "DIAGNOSTIC_NOT_NATIVE":
            raise ValueError("UNSUPPORTED_DIAGNOSTIC_EXTENSION")
        start = extension["end"] == 0
        endpoint = pieces[0].a if start else pieces[native_count - 1].b
        endpoint_weights = weights[0][0] if start else weights[native_count - 1][1]
        if pieces[-1].a != endpoint or weights[-1] != (endpoint_weights, endpoint_weights):
            raise ValueError("EXTENSION_CHANGED_ENDPOINT_PARAMETER_IDENTITY")
    points = [point for piece in pieces for point in (piece.a, piece.b)]
    box = tuple(min(p[k] for p in points) for k in (0, 1)) + tuple(max(p[k] for p in points) for k in (0, 1))
    upper = kernel.PreparedField(tuple(pieces), None, box, max(hi for _, hi in bounds))
    return Polyline(field, tuple(bounds), tuple(pieces), tuple(weights), upper)


def prepare_field(field):
    """Return the whole product-box envelope, not a selected knot vector."""
    return _polyline(field).upper


def extend_endpoint_field(field, end, point):
    """Append one diagnostic piece with original endpoint radius parameters."""
    poly = _polyline(field)
    if "diagnostic_extension" in field:
        raise ValueError("NESTED_DIAGNOSTIC_EXTENSION_NOT_SUPPORTED")
    if end not in (0, -1, "start", "end") or isinstance(end, bool):
        raise ValueError("END_MUST_BE_START_OR_END")
    end = 0 if end in (0, "start") else -1
    native = field["pieces"][0 if end == 0 else -1]
    endpoint = native["a" if end == 0 else "b"]
    target = _ep(tuple(exact.rational(v) for v in point))
    if target == endpoint:
        raise ValueError("EMPTY_DIAGNOSTIC_EXTENSION")
    weights = deepcopy(native["start_knot_weights" if end == 0 else "end_knot_weights"])
    lo, hi = (native[("lower_" if lower else "upper_") + ("start" if end == 0 else "end")]
              for lower in (True, False))
    result = deepcopy(field)
    result["pieces"].append({"a": deepcopy(endpoint), "b": target,
        "start_knot_weights": weights, "end_knot_weights": deepcopy(weights),
        "lower_start": lo, "lower_end": deepcopy(lo), "upper_start": hi, "upper_end": deepcopy(hi),
        "diagnostic_not_native": True})
    result["diagnostic_extension"] = {"status": "DIAGNOSTIC_NOT_NATIVE", "end": end,
        "native_piece_count": len(poly.pieces), "original_field_sha256": _digest(field),
        "new_knot_count": 0, "parameter_identity_changed": False,
        "source_extension_independently_proved_by_caller": "REQUIRED"}
    prepare_field(result)
    return result


@dataclass
class Body:
    body_id: str
    offset: int
    bounds: tuple
    aliases: tuple
    poly: Polyline | None = None
    circle: dict | None = None
    queries: frozenset = frozenset()
    ownership: frozenset = frozenset()

    @property
    def count(self):
        return len(self.bounds)

    def radii(self, vector):
        return tuple(lo + vector[self.offset + i] * (hi - lo)
                     for i, (lo, hi) in enumerate(self.bounds))


def _circle_bounds(row):
    from .finite_circle_source import circle_geometry
    circle_geometry(row)
    width = row["width"]
    intervals = [(_dec(s["half_width_squared_interval"]["lower"]),
                  _dec(s["half_width_squared_interval"]["upper"]))
                 for s in width["sections"] if s.get("constraint_eligible")]
    if len(intervals) < 2 or any(not 0 <= lo < hi for lo, hi in intervals):
        raise ValueError("INDEPENDENT_CIRCLE_SECTION_INTERVALS_NOT_ESTABLISHED")
    bounds = max(lo for lo, _ in intervals), min(hi for _, hi in intervals)
    if not bounds[0] < bounds[1] or width.get("pass") is not True or bounds != (
            _dec(width["half_width_squared_interval"]["lower"]),
            _dec(width["half_width_squared_interval"]["upper"])):
        raise ValueError("INCONSISTENT_CIRCLE_CONSTANT_WIDTH_INTERSECTION")
    return (bounds,)


def _prepare_bodies(bodies):
    from .finite_source_ports import cells_from_runs
    result, observations, layout = [], [], []
    offset = 0
    for row in bodies:
        body_id = row.get("stroke_id", row.get("object_id"))
        if not isinstance(body_id, str) or not body_id:
            raise ValueError("MISSING_FINITE_BODY_ID")
        circle = row.get("body_role") == "NECESSARY_PRIOR_CIRCLE_ARC" or row.get("curve_type") == "CIRCLE"
        aliases = {body_id}
        if circle:
            aliases.update(row[key] for key in ("object_id", "parent_object_id", "source_object_id")
                           if isinstance(row.get(key), str))
        aliases.update(row.get("body_id_aliases", []))
        if circle:
            bounds = _circle_bounds(row)
            body = Body(body_id, offset, bounds, tuple(sorted(aliases)), circle=row,
                queries=frozenset(cells_from_runs(row["finite_arc_domain"]["authorized_query_cells_y_x0_x1"])),
                ownership=frozenset(cells_from_runs(row["authorized_original_ring_cells_y_x0_x1"])))
            sections = _section_observations(row["width"])
            kind, parameter_ids = "ACTUAL_CIRCLE_CONSTANT_RADIUS", ["circle-constant-radius"]
        else:
            poly = _polyline(row["bounded_width_field"])
            body = Body(body_id, offset, poly.bounds, tuple(sorted(aliases)), poly=poly)
            sections = poly.field.get("section_observations", [])
            kind = "FINITE_POLYLINE_FIXED_INDEPENDENT_KNOTS"
            parameter_ids = [knot["parameter_id"] for knot in poly.field["knots"]]
        result.append(body)
        observations.extend((body_id, item) for item in sections)
        layout.append({"body_id": body_id, "body_id_aliases": list(body.aliases), "kind": kind,
            "offset": offset, "count": body.count, "parameter_ids": parameter_ids,
            "squared_radius_bounds": [{"lower": _enc(lo), "upper": _enc(hi), "upper_open": True}
                                      for lo, hi in body.bounds]})
        offset += body.count
    if not result or len({b.body_id for b in result}) != len(result):
        raise ValueError("INVALID_OR_EMPTY_BOUNDED_BODIES")
    aliases = {}
    for i, body in enumerate(result):
        for alias in body.aliases:
            if alias in aliases and aliases[alias] != i:
                raise ValueError("AMBIGUOUS_FINITE_BODY_ID_ALIAS")
            aliases[alias] = i
    return result, observations, layout, aliases


class Context:
    def __init__(self, black_cells, white_cells, bodies, owned_black_constraints):
        self.bodies, sections, self.layout, aliases = _prepare_bodies(bodies)
        self.count = sum(body.count for body in self.bodies)
        self.ids = [body.body_id for body in self.bodies]
        black = list(dict.fromkeys(_cell(cell) for cell in black_cells))
        white = [_cell(cell) for cell in white_cells]
        own = list(owned_black_constraints)
        for body_id, section in sections:
            own.extend({"body_id": body_id, "source_cell": cell,
                        "section_index": section["section_index"]}
                       for cell in section["owned_black_cells"])
            white.extend(_cell(cell) for cell in section["all_actually_measured_white_cells"])
        self.white = list(dict.fromkeys(white))
        self.constraints = []
        for cell in black:
            allowed = tuple(i for i, body in enumerate(self.bodies)
                            if body.circle is None or cell in body.queries and cell in body.ownership)
            self.constraints.append((cell, allowed, "COMPONENT_BLACK_CELL"))
        for row in own:
            if row["body_id"] not in aliases:
                raise ValueError("INDEPENDENT_SECTION_HAS_UNKNOWN_BODY")
            i, cell = aliases[row["body_id"]], _cell(row["source_cell"])
            body = self.bodies[i]
            if body.circle is not None and (cell not in body.queries or cell not in body.ownership):
                raise ValueError("CIRCLE_OWN_SECTION_BLACK_OUTSIDE_AUTHORIZED_RING")
            self.constraints.append((cell, (i,), "OWN_BODY_SECTION_BLACK_CELL"))
        self.constraints = list(dict.fromkeys(self.constraints))
        if set(self.white) & {cell for cell, _, _ in self.constraints}:
            raise ValueError("CONTRADICTORY_ORIGINAL_BLACK_AND_WHITE_CELL_OBSERVATIONS")
        for body in self.bodies:
            if body.circle is not None and any(cell not in body.queries for cell in self.white):
                raise ValueError("CIRCLE_QUERY_DOMAIN_INCOMPLETE_FOR_ALL_ACTUALLY_OBSERVED_WHITE")
        self.candidates, self.upper_counterexamples = [], []
        from .finite_circle_source import circle_cell_intersects
        for cell, allowed, role in self.constraints:
            possible, evidence = [], []
            for i in allowed:
                body = self.bodies[i]
                if body.poly is not None:
                    cost = kernel.cell_cost(body.poly.upper, cell).value(F(1))
                    compatible = cost < 0
                    evidence.append({"body_id": body.body_id, "exact_upper_cost": _enc(cost)})
                else:
                    compatible = circle_cell_intersects(body.circle, cell, body.bounds[0][1])
                    evidence.append({"body_id": body.body_id,
                        "closed_upper_circle_cell_intersects": compatible, "exact_algebraic_predicate": True})
                if compatible:
                    possible.append(i)
            self.candidates.append(tuple(possible))
            if not possible:
                self.upper_counterexamples.append({"source_cell": list(cell), "constraint_role": role,
                    "allowed_body_ids": [self.ids[i] for i in allowed], "upper_envelope_costs": evidence})
        self.universal_white, self.active_white = [], []
        from .finite_circle_source import circle_point_strictly_outside
        for cell in self.white:
            outside = True
            for body in self.bodies:
                if body.poly is not None:
                    field = body.poly.upper
                    clear = (kernel.box_lower_distance_squared(field, cell) >= field.upper_max or
                             kernel.point_cost(field, cell).value(F(1)) >= 0)
                else:
                    clear = circle_point_strictly_outside(body.circle, cell, body.bounds[0][1])
                if not clear:
                    outside = False
                    break
            (self.universal_white if outside else self.active_white).append(cell)

    def base(self):
        return {"schema": SOLVER_SCHEMA, "field_schema": SCHEMA,
            "field_producer_sha256": producer_sha256(), "exact_kernel_sha256": kernel.producer_sha256(),
            "body_ids": self.ids, "parameter_layout": self.layout, "parameter_count": self.count,
            "membership_arithmetic": "EXACT_RATIONAL_QUADRATICS_AND_NATIVE_CIRCLE_ALGEBRA",
            "all_fixed_knots_independently_parameterized": True,
            "one_complete_vector_for_all_black_white_and_own_sections": True,
            "canonical_component_black_constraint_count": sum(role == "COMPONENT_BLACK_CELL" for _, _, role in self.constraints),
            "canonical_owned_black_constraint_count": sum(role == "OWN_BODY_SECTION_BLACK_CELL" for _, _, role in self.constraints),
            "canonical_white_cell_count": len(self.white), "universal_white_center_count": len(self.universal_white),
            "source_completeness_separately_required": True}


def _evaluate(context, vector):
    result = context.base()
    values = tuple(_dec(value) for value in vector)
    bounds_ok = len(values) == context.count and all(0 <= value < 1 for value in values)
    result.update({"pass": False, "parameter_vector": [_enc(value) for value in values],
        "checks": {"complete_parameter_vector": len(values) == context.count, "strict_parameter_bounds": bounds_ok}})
    if not bounds_ok:
        result["status"] = "INVALID_OR_NONSTRICT_PARAMETER_VECTOR"
        return result
    from .finite_circle_source import circle_cell_intersects, circle_point_strictly_outside
    prepared = [body.poly.selected(values[body.offset:body.offset + body.count])
                if body.poly is not None else None for body in context.bodies]
    radii = [body.radii(values) for body in context.bodies]
    witnesses, missing = [], []
    for cell, allowed, role in context.constraints:
        covered = []
        for i in allowed:
            body = context.bodies[i]
            if body.poly is not None:
                cost = kernel.cell_cost(prepared[i], cell).value(F(0))
                hit = cost <= 0
            else:
                cost = None
                hit = circle_cell_intersects(body.circle, cell, radii[i][0])
            if hit:
                covered.append({"body_id": body.body_id, "exact_cost": None if cost is None else _enc(cost),
                                "exact_circle_predicate": body.circle is not None})
        row = {"source_cell": list(cell), "constraint_role": role,
               "body_ids": [item["body_id"] for item in covered], "exact_coverage": covered}
        (witnesses if covered else missing).append(row)
    white_witnesses = [{"source_cell": list(cell), "point_exact": _ep(cell),
                        "valid_for_entire_width_box": True} for cell in context.universal_white]
    lost_white = []
    for cell in context.active_white:
        found = None
        for point in kernel._white_points(cell):
            if all(kernel.point_cost(prepared[i], point).value(F(0)) > 0 if body.poly is not None
                   else circle_point_strictly_outside(body.circle, point, radii[i][0])
                   for i, body in enumerate(context.bodies)):
                found = point
                break
        if found is None:
            lost_white.append(list(cell))
        else:
            white_witnesses.append({"source_cell": list(cell), "point_exact": _ep(found),
                                    "valid_for_entire_width_box": False})
    result["checks"].update({
        "all_component_black": not any(row["constraint_role"] == "COMPONENT_BLACK_CELL" for row in missing),
        "every_owned_section_black": not any(row["constraint_role"] == "OWN_BODY_SECTION_BLACK_CELL" for row in missing),
        "one_common_strict_white_witness_per_cell": not lost_white})
    result.update({"pass": all(result["checks"].values()), "black_witnesses": witnesses,
        "white_witnesses": white_witnesses, "unexplained_black_constraints": missing,
        "white_cells_without_common_strict_witness": lost_white,
        "selected_squared_half_widths": [{"body_id": body.body_id, "values": [_enc(value) for value in selected]}
                                         for body, selected in zip(context.bodies, radii)],
        "existence_certificate_complete": all(result["checks"].values()),
        "exact_family_infeasibility_proved": False, "search_complete": False})
    result["status"] = "COHERENT_BOUNDED_FINITE_UNION_FOUND" if result["pass"] else "PARAMETER_VECTOR_FAILS_EXACT_OBSERVATIONS"
    return result


def evaluate_vector(black_cells, white_cells, bodies, parameter_vector, *, owned_black_constraints=()):
    """Rebuild and exactly check a complete rational parameter vector."""
    try:
        return _evaluate(Context(black_cells, white_cells, bodies, owned_black_constraints), parameter_vector)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return {"schema": SOLVER_SCHEMA, "pass": False, "status": "PENDING_MODEL_INPUT_NOT_ESTABLISHED",
                "reason": str(exc), "exact_family_infeasibility_proved": False, "search_complete": False}


def _legacy_proposal(context, *, constant_only, max_states):
    """Embed a constant/old section-profile candidate, then require new replay."""
    if any(body.circle is not None or body.poly.field.get("diagnostic_extension") for body in context.bodies):
        return None, {"status": "NOT_APPLICABLE_TO_CIRCLE_OR_EXTENSION"}
    fields = []
    for body in context.bodies:
        field = body.poly.field
        sections = [row for row in field["knots"] if row["section_indices"]]
        low, high = max(_dec(row["lower"]) for row in sections), min(_dec(row["upper"]) for row in sections)
        if constant_only and low >= high:
            return None, {"status": "CONSTANT_SUBFAMILY_EMPTY", "body_id": body.body_id}
        constant = low < high
        intervals = [(_dec(row["path_position_l1_exact"]), _dec(row["lower"]), _dec(row["upper"])) for row in sections]

        def at(s, intervals=intervals, constant=constant, low=low, high=high):
            if constant:
                return low, high
            if s <= intervals[0][0]:
                return intervals[0][1:]
            if s >= intervals[-1][0]:
                return intervals[-1][1:]
            i = bisect_right([row[0] for row in intervals], s) - 1
            a, b = intervals[i], intervals[i + 1]
            t = (s - a[0]) / (b[0] - a[0])
            return tuple(a[k] + t * (b[k] - a[k]) for k in (1, 2))

        derived = {"pass": True, "pieces": []}
        if constant:
            derived["constant_interval"] = {"lower": _enc(low), "upper": _enc(high)}
        for row in field["pieces"]:
            lo0, hi0 = at(_dec(row["path_position_start_l1_exact"]))
            lo1, hi1 = at(_dec(row["path_position_end_l1_exact"]))
            derived["pieces"].append({"a": row["a"], "b": row["b"],
                "lower_start": _enc(lo0), "lower_end": _enc(lo1),
                "upper_start": _enc(hi0), "upper_end": _enc(hi1)})
        fields.append(({"stroke_id": body.body_id, "bounded_width_field": derived}, at))
    black = [cell for cell, _, role in context.constraints if role == "COMPONENT_BLACK_CELL"]
    own = [{"source_cell": cell, "body_id": context.ids[allowed[0]]}
           for cell, allowed, role in context.constraints if role == "OWN_BODY_SECTION_BLACK_CELL"]
    report = kernel.solve_bounded_union(black, context.white, [row for row, _ in fields],
                                       owned_black_constraints=own, max_states=max_states)
    diagnostic = {key: report.get(key) for key in ("pass", "status", "visited_state_count", "resource_truncated")}
    diagnostic["old_family_pass_is_new_family_acceptance"] = False
    if not report.get("pass"):
        return None, diagnostic
    vector = []
    for body, (_, at), encoded in zip(context.bodies, fields, report["alpha_vector"]):
        alpha = _dec(encoded)
        for knot, (lo, hi) in zip(body.poly.field["knots"], body.bounds):
            legacy_lo, legacy_hi = at(_dec(knot["path_position_l1_exact"]))
            radius = legacy_lo + alpha * (legacy_hi - legacy_lo)
            vector.append((radius - lo) / (hi - lo))
    return vector, diagnostic


class ProposalResourceBound(RuntimeError):
    """A numerical work bound, never a mathematical infeasibility result."""


class NumericalProposal:
    """Floating optimizer oracle. Its gradients and residuals prove nothing."""

    def __init__(self, context, max_evaluations):
        import numpy as np
        self.np, self.context = np, context
        self.max_evaluations = max_evaluations
        if context.count > NUMERICAL_LIMITS["maximum_parameters"]:
            raise ProposalResourceBound("NUMERICAL_PARAMETER_DIMENSION_BOUND")
        self.requests, indices = [], {}

        def request(body, kind, point):
            key = body, kind, tuple(point)
            if key not in indices:
                if len(self.requests) >= NUMERICAL_LIMITS["maximum_unique_queries"]:
                    raise ProposalResourceBound("NUMERICAL_QUERY_COUNT_BOUND")
                if (len(self.requests) + 1) * context.count > NUMERICAL_LIMITS["maximum_dense_jacobian_entries"]:
                    raise ProposalResourceBound("NUMERICAL_DENSE_JACOBIAN_MEMORY_BOUND")
                indices[key] = len(self.requests)
                self.requests.append(key)
            return indices[key]

        self.black = [tuple(request(i, "cell", cell) for i in possible)
                      for (cell, _, _), possible in zip(context.constraints, context.candidates)]
        self.white = np.asarray([[[request(i, "point", point) for i in range(len(context.bodies))]
                                  for point in kernel._white_points(cell)] for cell in context.active_white], dtype=int)
        if len(self.requests) > NUMERICAL_LIMITS["maximum_unique_queries"]:
            raise ProposalResourceBound("NUMERICAL_QUERY_COUNT_BOUND")
        if len(self.requests) * context.count > NUMERICAL_LIMITS["maximum_dense_jacobian_entries"]:
            raise ProposalResourceBound("NUMERICAL_DENSE_JACOBIAN_MEMORY_BOUND")
        estimated_parts = sum((5 if kind == "cell" else 1) * len(context.bodies[i].poly.pieces)
                              for i, kind, _ in self.requests if context.bodies[i].poly is not None)
        if estimated_parts > NUMERICAL_LIMITS["maximum_quadratic_parts"]:
            raise ProposalResourceBound("NUMERICAL_QUADRATIC_EXPANSION_MEMORY_BOUND")
        self.estimated_resources = {"unique_queries": len(self.requests),
            "dense_jacobian_entries": len(self.requests) * context.count,
            "quadratic_part_upper_bound": estimated_parts}
        self.parts, self.circles = [], []
        for i, body in enumerate(context.bodies):
            queries = [(j, kind, point) for j, (owner, kind, point) in enumerate(self.requests) if owner == i]
            if body.circle is not None:
                from .finite_circle_source import circle_geometry
                center, radius = circle_geometry(body.circle)
                center, radius = np.asarray(list(map(float, center))), float(radius)
                lows, highs, ids = [], [], []
                for j, kind, point in queries:
                    distance = np.abs(np.asarray(list(map(float, point))) - center)
                    if kind == "cell":
                        low = np.sum(np.maximum(distance - .5, 0) ** 2)
                        high = np.sum((distance + .5) ** 2)
                        square = 0.0 if low <= radius * radius <= high else min(
                            (np.sqrt(low) - radius) ** 2, (np.sqrt(high) - radius) ** 2)
                    else:
                        square = (np.sqrt(np.sum(distance ** 2)) - radius) ** 2
                    lo, hi = body.bounds[0]
                    ids.append(j)
                    lows.append(square - float(lo))
                    highs.append(float(hi - lo))
                self.circles.append((np.asarray(ids, dtype=int), np.asarray(lows), np.asarray(highs), body.offset))
                continue
            p0, p1, c0, c1 = [], [], [], []
            for start, end in body.poly.weights:
                for weights, base, coefficient in ((start, p0, c0), (end, p1, c1)):
                    base.append(sum(float(weight * body.bounds[k][0]) for k, weight in weights))
                    row = np.zeros(context.count)
                    for k, weight in weights:
                        row[body.offset + k] = float(weight * (body.bounds[k][1] - body.bounds[k][0]))
                    coefficient.append(row)
            aa, bb, cc, ll, hh, pp, qq = [], [], [], [], [], [], []
            for j, kind, point in queries:
                point = np.asarray(list(map(float, point)))
                for pindex, piece in enumerate(body.poly.pieces):
                    a, b = np.asarray(list(map(float, piece.a))), np.asarray(list(map(float, piece.b)))
                    delta = b - a
                    breaks = [0.0, 1.0]
                    if kind == "cell":
                        for axis in (0, 1):
                            if delta[axis] != 0:
                                for bound in (point[axis] - .5, point[axis] + .5):
                                    t = (bound - a[axis]) / delta[axis]
                                    if 0 < t < 1:
                                        breaks.append(t)
                    breaks = sorted(set(breaks))
                    for left, right in zip(breaks, breaks[1:]):
                        midpoint = a + ((left + right) / 2) * delta
                        if kind == "point":
                            mask, target = np.ones(2, dtype=bool), point
                        else:
                            mask = (midpoint < point - .5) | (midpoint > point + .5)
                            target = np.clip(midpoint, point - .5, point + .5)
                        d, g = delta[mask], (a - target)[mask]
                        aa.append(float(d @ d))
                        bb.append(float(2 * d @ g))
                        cc.append(float(g @ g))
                        ll.append(left)
                        hh.append(right)
                        pp.append(pindex)
                        qq.append(j)
            self.parts.append(tuple(np.asarray(values, dtype=int if index in (5, 6) else float)
                                    for index, values in enumerate((aa, bb, cc, ll, hh, pp, qq))) +
                              (np.asarray(p0), np.asarray(p1), np.asarray(c0), np.asarray(c1)))
        self.last_x, self.last_result = None, None
        self.best_x, self.best_minimum = None, float("-inf")
        self.evaluations = 0

    def evaluate(self, values, *, margin=1e-7):
        np = self.np
        values = np.asarray(values)
        if self.last_x is not None and np.array_equal(values, self.last_x):
            raw, jac = self.last_result
            return raw - margin, jac
        if self.evaluations >= self.max_evaluations:
            raise ProposalResourceBound("NUMERICAL_ORACLE_EVALUATION_HARD_BOUND")
        self.evaluations += 1
        costs = np.full(len(self.requests), np.inf)
        derivatives = np.zeros((len(self.requests), self.context.count))
        for aa, bb, cc, ll, hh, pp, qq, p0, p1, c0, c1 in self.parts:
            r0, r1 = p0 + c0 @ values, p1 + c1 @ values
            b, c = bb - (r1 - r0)[pp], cc - r0[pp]
            t = np.where(aa > 0, -b / np.where(aa > 0, 2 * aa, 1), np.where(b >= 0, ll, hh))
            t = np.clip(t, ll, hh)
            v = aa * t * t + b * t + c
            np.minimum.at(costs, qq, v)
            choices = np.full(len(self.requests), len(v), dtype=int)
            selected = np.flatnonzero(v == costs[qq])
            np.minimum.at(choices, qq[selected], selected)
            usable = np.flatnonzero(choices < len(v))
            chosen = choices[usable]
            derivatives[usable] = -(1-t[chosen, None]) * c0[pp[chosen]] - t[chosen, None] * c1[pp[chosen]]
        for ids, low, change, offset in self.circles:
            costs[ids] = low - change * values[offset]
            derivatives[ids, offset] = -change
        selected_black = [row[int(np.argmin(costs[list(row)]))] for row in self.black]
        raw = [-costs[i] for i in selected_black]
        jac = [-derivatives[i] for i in selected_black]
        if self.white.size:
            white_costs = costs[self.white]
            worst_body = np.argmin(white_costs, axis=2)
            worst_cost = np.take_along_axis(white_costs, worst_body[:, :, None], axis=2)[:, :, 0]
            best_point = np.argmax(worst_cost, axis=1)
            for j, point in enumerate(best_point):
                index = self.white[j, point, worst_body[j, point]]
                raw.append(costs[index])
                jac.append(derivatives[index])
        raw, jac = np.asarray(raw), np.asarray(jac).reshape((-1, self.context.count))
        self.last_x, self.last_result = values.copy(), (raw, jac)
        minimum = float(np.min(raw)) if len(raw) else float("inf")
        if minimum > self.best_minimum:
            self.best_x, self.best_minimum = values.copy(), minimum
        return raw - margin, jac


def solve_bounded_union(black_cells, white_cells, bodies, *, owned_black_constraints=(), max_states=MAX_STATES):
    """Find and exactly certify one vector; finite exhaustion remains PENDING."""
    numerical = None
    try:
        context = Context(black_cells, white_cells, bodies, owned_black_constraints)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return {"schema": SOLVER_SCHEMA, "pass": False, "status": "PENDING_MODEL_INPUT_NOT_ESTABLISHED",
                "reason": str(exc), "search_complete": False, "exact_family_infeasibility_proved": False}
    report = context.base()
    report.update({"pass": False, "search_complete": False, "exact_family_infeasibility_proved": False,
                   "numeric_proposals_are_acceptance_evidence": False, "proposal_attempts": []})
    if context.upper_counterexamples:
        report.update({"status": "NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_BOUNDED_ENVELOPES",
            "strict_upper_counterexamples": context.upper_counterexamples,
            "unexplained_black_cells": [row["source_cell"] for row in context.upper_counterexamples],
            "search_complete": True, "exact_family_infeasibility_proved": True,
            "infeasibility_scope": "ONLY_THE_DECLARED_FINITE_GEOMETRY_KNOT_BOX_AND_CIRCLE_OWNERSHIP"})
        return report
    attempted = set()

    def check(vector, origin):
        if vector is None:
            return None
        vector = tuple(_dec(value) for value in vector)
        if vector in attempted:
            return None
        attempted.add(vector)
        answer = _evaluate(context, vector)
        report["proposal_attempts"].append({"origin": origin, "exact_pass": answer["pass"],
            "status": answer["status"], "parameter_vector_sha256": _digest([_enc(value) for value in vector]),
            "missing_black_count": len(answer.get("unexplained_black_constraints", [])),
            "missing_common_white_count": len(answer.get("white_cells_without_common_strict_witness", []))})
        if answer["pass"]:
            answer.update({"proposal_attempts": report["proposal_attempts"], "accepted_proposal_origin": origin,
                "numeric_proposals_are_acceptance_evidence": False, "resource_truncated": False,
                "exact_vector_evaluation_count": len(attempted)})
            return answer
        return None

    for constant_only in (True, False):
        vector, diagnostic = _legacy_proposal(context, constant_only=constant_only, max_states=max_states)
        origin = "CONSTANT_SUBFAMILY_FIRST" if constant_only else "LEGACY_SECTION_PROFILE_EMBEDDED_AS_CANDIDATE"
        report["proposal_attempts"].append({"origin": origin, "legacy_proposal_diagnostic": diagnostic})
        answer = check(vector, origin)
        if answer:
            return answer
    constant_seed = []
    for body in context.bodies:
        low, high = max(lo for lo, _ in body.bounds), min(hi for _, hi in body.bounds)
        constant_seed.extend((low - lo) / (hi - lo) if low < high else F(1, 2) for lo, hi in body.bounds)
    answer = check(constant_seed, "JOINT_CONSTANT_LOWER_WHERE_AVAILABLE")
    if answer:
        return answer
    answer = check([F(0)] * context.count, "ALL_FIXED_KNOT_LOWER_BOUNDS")
    if answer:
        return answer
    try:
        import numpy as np
        from scipy.optimize import minimize
        numerical = NumericalProposal(context, max_states)
        upper = float(F(1) - F(1, 1 << 40))
        seeds = [np.asarray(list(map(float, constant_seed))), np.full(context.count, .5),
                 np.full(context.count, .2), np.full(context.count, .8)]
        for direction in (1, -1):
            values = []
            for body in context.bodies:
                values.extend(np.linspace(.15, .85, body.count)[::direction])
            seeds.append(np.asarray(values))
        report["numerical_search"] = {"engine": "SCIPY_SLSQP_ANALYTIC_PIECEWISE_PROPOSAL_GRADIENT",
            "proposal_only_margin_squared_pixels": 1e-7, "acceptance_uses_margin_or_epsilon": False,
            "maximum_oracle_evaluations": max_states, "limits": dict(NUMERICAL_LIMITS),
            "estimated_resources": numerical.estimated_resources, "attempts": []}
        for index, seed in enumerate(seeds):
            if numerical.evaluations >= max_states:
                break
            seed = np.clip(seed, 0, upper)
            remaining = max_states - numerical.evaluations
            result = minimize(lambda x: 1e-8 * np.sum((x - seed) ** 2), seed,
                jac=lambda x: 2e-8 * (x - seed), method="SLSQP", bounds=[(0, upper)] * context.count,
                constraints=[{"type": "ineq", "fun": lambda x: numerical.evaluate(x)[0],
                              "jac": lambda x: numerical.evaluate(x)[1]}],
                options={"maxiter": min(200, max(1, remaining)), "ftol": 1e-12, "disp": False})
            residual = numerical.evaluate(result.x)[0]
            attempt = {"seed_index": index, "optimizer_success": bool(result.success),
                "optimizer_status": int(result.status), "message": str(result.message),
                "iterations": int(result.nit), "minimum_proposal_constraint": float(np.min(residual)) if len(residual) else None,
                "oracle_evaluations_so_far": numerical.evaluations}
            report["numerical_search"]["attempts"].append(attempt)
            # Optimizer success and failure both merely propose a vector.
            if np.all(np.isfinite(result.x)):
                vector = [F.from_float(float(value)) for value in np.clip(result.x, 0, upper)]
                answer = check(vector, f"NUMERICAL_PROPOSAL_{index}_EXACT_RATIONAL_REPLAY")
                if answer:
                    answer["numerical_search"] = report["numerical_search"]
                    return answer
        report["numerical_search"]["oracle_evaluations"] = numerical.evaluations
        report["resource_truncated"] = numerical.evaluations >= max_states
    except ProposalResourceBound as exc:
        report["resource_truncated"] = True
        report["numerical_resource_bound"] = {"reason": str(exc), "limits": dict(NUMERICAL_LIMITS),
            "oracle_evaluations": None if numerical is None else numerical.evaluations,
            "changes_declared_parameter_family": False}
        if numerical is not None and numerical.best_x is not None:
            vector = [F.from_float(float(value)) for value in numerical.best_x]
            answer = check(vector, "BEST_NUMERICAL_CANDIDATE_AT_RESOURCE_BOUND_EXACT_REPLAY")
            if answer:
                answer["numerical_resource_bound"] = report["numerical_resource_bound"]
                return answer
    except (ImportError, ValueError, FloatingPointError, ArithmeticError) as exc:
        report["numerical_search_error"] = {"type": type(exc).__name__, "message": str(exc)}
    report.update({"status": "PENDING_FINITE_PARAMETER_PROPOSALS_EXHAUSTED",
        "exact_vector_evaluation_count": len(attempted), "exact_family_infeasibility_proved": False,
        "search_complete": False, "no_optimizer_or_search_failure_is_impossibility": True})
    return report
