"""Exact, independently bounded finite stroke fields (Issue 63).

The family is frozen in ISSUE63_BOUNDED_SOURCE_CONTRACT_20261127.md.
Rational membership is separate from the finite-resolution parameter search.
No source observation is discarded because it disagrees with a candidate.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path

from . import attached_stroke_width_exact as exact


SCHEMA = "source-bounded-continuous-squared-width-field-v1"
ALPHA_BITS = 48
MAX_STATES = 8192
F = Fraction


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _enc(value):
    return exact.encode_rational(value)


def _dec(value):
    return exact.decode_rational(value)


def _point(values):
    return tuple(exact.rational(v) for v in values)


def _ep(point):
    return [_enc(v) for v in point]


def build_width_field(points, width):
    """Choose the predeclared family from *all* independent section intervals."""
    points = [_point(p) for p in points]
    result = {"schema": SCHEMA, "pass": False, "producer_sha256": producer_sha256(),
              "alpha_lower": _enc(F(0)), "alpha_upper": _enc(F(1)),
              "alpha_upper_open": True, "parameter_count": 1,
              "selection_uses_residual_pixels": False,
              "all_eligible_sections_retained": True, "knots": [], "pieces": []}
    try:
        if len(points) < 2 or any(a == b for a, b in zip(points, points[1:])):
            raise ValueError("INVALID_FINITE_NATIVE_POLYLINE")
        positions = [F(0)]
        for a, b in zip(points, points[1:]):
            positions.append(positions[-1] + sum(abs(b[k] - a[k]) for k in (0, 1)))
        selected = [(i, s) for i, s in enumerate(width.get("sections", []))
                    if s.get("constraint_eligible")]
        result["eligible_section_indices"] = [i for i, _ in selected]
        if len(selected) < 2:
            raise ValueError("INSUFFICIENT_INDEPENDENT_WIDTH_SECTIONS")
        knots = []
        for index, section in selected:
            bounds = section["half_width_squared_interval"]
            lo, hi = _dec(bounds["lower"]), _dec(bounds["upper"])
            if not 0 <= lo < hi:
                raise ValueError("INDIVIDUAL_INDEPENDENT_SECTION_INTERVAL_EMPTY")
            segment = section["native_segment_index"]
            if (isinstance(segment, bool) or not isinstance(segment, int)
                    or not 0 <= segment < len(points) - 1):
                raise ValueError("INVALID_INDEPENDENT_SECTION_NATIVE_SEGMENT_INDEX")
            q = tuple(_dec(v) for v in section["center_exact"])
            a, b = points[segment], points[segment + 1]
            axis = next(k for k in (0, 1) if b[k] != a[k])
            t = (q[axis] - a[axis]) / (b[axis] - a[axis])
            if not 0 < t < 1 or any(a[k] + t * (b[k] - a[k]) != q[k] for k in (0, 1)):
                raise ValueError("WIDTH_KNOT_NOT_ON_ACTUAL_INTERIOR_FINITE_SEGMENT")
            s = positions[segment] + t * (positions[segment + 1] - positions[segment])
            knots.append((s, lo, hi, index, q))
        knots.sort()
        if len({k[0] for k in knots}) != len(knots):
            raise ValueError("DUPLICATE_PATH_POSITION_WIDTH_CONSTRAINT")
        low, high = max(k[1] for k in knots), min(k[2] for k in knots)
        result["recomputed_constant_intersection"] = {
            "lower": _enc(low), "upper": _enc(high), "empty": low >= high}
        # Recompute the family from all section intervals. A supplied PASS or
        # reason is only checked for consistency; it never selects the family.
        if low < high:
            bounds = width["half_width_squared_interval"]
            if (width.get("pass") is not True
                    or (_dec(bounds["lower"]), _dec(bounds["upper"])) != (low, high)):
                raise ValueError("STALE_OR_INCONSISTENT_CONSTANT_WIDTH_RECEIPT")
            result["family"] = "CONSTANT_INDEPENDENT_SECTION_INTERSECTION"
            result["constant_interval"] = {"lower": _enc(low), "upper": _enc(high)}
            interpolation = [(F(0), low, high), (positions[-1], low, high)]
        else:
            if (width.get("pass") is not False
                    or width.get("reason") != "CONSTANT_WIDTH_MODEL_INAPPLICABLE"):
                raise ValueError("STALE_OR_INCONSISTENT_EMPTY_CONSTANT_INTERSECTION_RECEIPT")
            result["family"] = "CONTINUOUS_SECTION_KNOT_SQUARED_WIDTH_COMMON_ALPHA"
            interpolation = [(k[0], k[1], k[2]) for k in knots]
        result["knots"] = [{"path_position_l1_exact": _enc(s), "lower": _enc(lo),
                            "upper": _enc(hi), "section_index": index, "center_exact": _ep(q)}
                           for s, lo, hi, index, q in knots]

        def at(s):
            if s <= interpolation[0][0]:
                return interpolation[0][1:]
            if s >= interpolation[-1][0]:
                return interpolation[-1][1:]
            i = bisect_right([v[0] for v in interpolation], s) - 1
            a, b = interpolation[i], interpolation[i + 1]
            t = (s - a[0]) / (b[0] - a[0])
            return tuple(a[k] + t * (b[k] - a[k]) for k in (1, 2))

        def center(s):
            i = min(bisect_right(positions, s) - 1, len(points) - 2)
            t = (s - positions[i]) / (positions[i + 1] - positions[i])
            return tuple(points[i][k] + t * (points[i + 1][k] - points[i][k]) for k in (0, 1))

        breaks = sorted(set(positions + [v[0] for v in interpolation]))
        for a, b in zip(breaks, breaks[1:]):
            lo0, hi0 = at(a)
            lo1, hi1 = at(b)
            result["pieces"].append({"a": _ep(center(a)), "b": _ep(center(b)),
                "path_position_start_l1_exact": _enc(a), "path_position_end_l1_exact": _enc(b),
                "lower_start": _enc(lo0), "lower_end": _enc(lo1),
                "upper_start": _enc(hi0), "upper_end": _enc(hi1)})
        result.update({"pass": True, "status": "INDEPENDENT_BOUNDED_FIELD_ESTABLISHED",
                       "continuity": "AFFINE_SQUARED_RADIUS_AT_ALL_SECTION_KNOTS",
                       "end_cap": "FINITE_ROUND_CAP_WITH_ENDPOINT_FIELD_RADIUS",
                       "extra_junction_ink_radius": None,
                       "path_position": "CUMULATIVE_ACTUAL_FINITE_NATIVE_L1_LENGTH_IN_SOURCE_COORDINATES",
                       "geometry_changed": False})
    except (ValueError, KeyError, IndexError, TypeError, StopIteration) as exc:
        result.update(status="BOUNDED_FIELD_NOT_ESTABLISHED", reason=str(exc))
    return result


@dataclass(frozen=True)
class Piece:
    a: tuple
    b: tuple
    lo0: F
    lo1: F
    hi0: F
    hi1: F


@dataclass(frozen=True)
class PreparedField:
    pieces: tuple
    constant_interval: tuple | None
    box: tuple
    upper_max: F


def prepare_field(field):
    if not field.get("pass"):
        raise ValueError("UNSUPPORTED_BOUNDED_FIELD")
    pieces = tuple(Piece(tuple(_dec(v) for v in row["a"]), tuple(_dec(v) for v in row["b"]),
                         _dec(row["lower_start"]), _dec(row["lower_end"]),
                         _dec(row["upper_start"]), _dec(row["upper_end"])) for row in field["pieces"])
    if not pieces or any(p.a == p.b or p.lo0 < 0 or p.lo1 < 0 or p.lo0 >= p.hi0 or p.lo1 >= p.hi1
                         for p in pieces):
        raise ValueError("INVALID_BOUNDED_FIELD_PIECES")
    if any(a.b != b.a or a.lo1 != b.lo0 or a.hi1 != b.hi0 for a, b in zip(pieces, pieces[1:])):
        raise ValueError("DISCONTINUOUS_BOUNDED_FIELD")
    constant = field.get("constant_interval")
    constant = None if constant is None else (_dec(constant["lower"]), _dec(constant["upper"]))
    if constant and any((p.lo0, p.hi0) != constant or (p.lo1, p.hi1) != constant for p in pieces):
        raise ValueError("CONSTANT_FIELD_PIECE_MISMATCH")
    pts = [p.a for p in pieces] + [pieces[-1].b]
    box = tuple(min(p[k] for p in pts) for k in (0, 1)) + tuple(max(p[k] for p in pts) for k in (0, 1))
    return PreparedField(pieces, constant, box, max(max(p.hi0, p.hi1) for p in pieces))


def _quadratic_minimum(a, b, c, low, high):
    values = [a * low * low + b * low + c, a * high * high + b * high + c]
    if a:
        t = -b / (2 * a)
        if low < t < high:
            values.append(a * t * t + b * t + c)
    return min(values)


@dataclass(frozen=True)
class Cost:
    # a*t^2 + (b-alpha*db)*t + (c-alpha*dc), restricted to [low,high]
    parts: tuple
    constant_interval: tuple | None = None

    def value(self, alpha):
        alpha = exact.rational(alpha)
        if not 0 <= alpha <= 1:
            raise ValueError("ALPHA_OUTSIDE_DECLARED_CLOSED_DIAGNOSTIC_BOX")
        return min(_quadratic_minimum(a, b - alpha * db, c - alpha * dc, low, high)
                   for a, b, c, db, dc, low, high in self.parts)


def point_cost(field, point):
    p = _point(point)
    parts = []
    for piece in field.pieces:
        d = tuple(piece.b[k] - piece.a[k] for k in (0, 1))
        g = tuple(piece.a[k] - p[k] for k in (0, 1))
        a = sum(v * v for v in d)
        b = 2 * sum(d[k] * g[k] for k in (0, 1)) - (piece.lo1 - piece.lo0)
        c = sum(v * v for v in g) - piece.lo0
        dc = piece.hi0 - piece.lo0
        db = piece.hi1 - piece.lo1 - dc
        parts.append((a, b, c, db, dc, F(0), F(1)))
    return Cost(tuple(parts), field.constant_interval)


def cell_cost(field, cell):
    center = _point(cell)
    low = tuple(v - F(1, 2) for v in center)
    high = tuple(v + F(1, 2) for v in center)
    parts = []
    for piece in field.pieces:
        d = tuple(piece.b[k] - piece.a[k] for k in (0, 1))
        breaks = {F(0), F(1)}
        for k in (0, 1):
            if d[k]:
                for bound in (low[k], high[k]):
                    t = (bound - piece.a[k]) / d[k]
                    if 0 < t < 1:
                        breaks.add(t)
        breaks = sorted(breaks)
        for left, right in zip(breaks, breaks[1:]):
            midpoint = (left + right) / 2
            qa, qb, qc = F(0), -(piece.lo1 - piece.lo0), -piece.lo0
            for k in (0, 1):
                value = piece.a[k] + midpoint * d[k]
                bound = low[k] if value < low[k] else high[k] if value > high[k] else None
                if bound is None:
                    continue
                g = piece.a[k] - bound
                qa += d[k] * d[k]
                qb += 2 * g * d[k]
                qc += g * g
            dc = piece.hi0 - piece.lo0
            db = piece.hi1 - piece.lo1 - dc
            parts.append((qa, qb, qc, db, dc, left, right))
    return Cost(tuple(parts), field.constant_interval)


def box_lower_distance_squared(field, point, *, cell=False):
    p = _point(point)
    half = F(1, 2) if cell else F(0)
    return sum(max(field.box[k] - p[k] - half, F(0), p[k] - half - field.box[k + 2]) ** 2
               for k in (0, 1))


def cell_compatible_with_strict_upper(field, cell):
    if box_lower_distance_squared(field, cell, cell=True) >= field.upper_max:
        return False
    return cell_cost(field, cell).value(F(1)) < 0


def _required_alpha(cost):
    zero = cost.value(F(0))
    if zero <= 0:
        return F(0)
    if cost.value(F(1)) >= 0:
        return None
    if cost.constant_interval is not None:
        lo, hi = cost.constant_interval
        return zero / (hi - lo)
    low, high, scale = 0, 1 << ALPHA_BITS, 1 << ALPHA_BITS
    while high - low > 1:
        middle = (low + high) // 2
        if cost.value(F(middle, scale)) <= 0:
            high = middle
        else:
            low = middle
    return F(high, scale) if high < scale else None


def _white_points(cell):
    x, y = _point(cell)
    return [(x + dx, y + dy) for dx in (F(-1, 2), F(0), F(1, 2))
            for dy in (F(-1, 2), F(0), F(1, 2))]


def solve_bounded_union(black_cells, white_cells, bodies, *, owned_black_constraints=(), max_states=MAX_STATES):
    """Certify one simultaneous finite-field vector or return a precise boundary.

    `owned_black_constraints` consists of {source_cell, body_id} records from
    independent width sections. These cannot be assigned to a different body.
    """
    fields = [prepare_field(body["bounded_width_field"]) for body in bodies]
    ids = [body["stroke_id"] for body in bodies]
    if not fields or len(set(ids)) != len(ids):
        return {"pass": False, "status": "INVALID_OR_EMPTY_BOUNDED_BODIES", "search_complete": False}
    index = {body_id: i for i, body_id in enumerate(ids)}
    variable = any(field.constant_interval is None for field in fields)
    base = {"schema": "coherent-bounded-finite-union-v1", "body_ids": ids,
            "alpha_dyadic_search_bits": ALPHA_BITS, "membership_arithmetic": "EXACT_RATIONAL_QUADRATICS",
            "search_resolution_is_not_geometry_epsilon": True, "pass": False,
            "resource_truncated": False, "visited_state_count": 0,
            "parameter_family_contains_variable_fields": variable}
    all_indices = tuple(range(len(fields)))
    constraints = [(list(cell), all_indices, "COMPONENT_BLACK_CELL") for cell in black_cells]
    for item in owned_black_constraints:
        if item["body_id"] not in index:
            raise ValueError("INDEPENDENT_SECTION_HAS_UNKNOWN_BODY")
        constraints.append((list(item["source_cell"]), (index[item["body_id"]],), "OWN_BODY_SECTION_BLACK_CELL"))
    # Identical constraints are retained in caller receipts but need only one
    # identical exact calculation in the search.
    constraints = list(dict.fromkeys((tuple(cell), allowed, role) for cell, allowed, role in constraints))
    costs = [[cell_cost(fields[i], cell) if i in allowed else None for i in all_indices]
             for cell, allowed, _ in constraints]
    candidates = [tuple(i for i in allowed if row[i].value(F(1)) < 0)
                  for row, (_, allowed, _) in zip(costs, constraints)]
    impossible = [j for j, values in enumerate(candidates) if not values]
    if impossible:
        base.update(status="NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_BOUNDED_ENVELOPES", search_complete=True,
                    exact_family_infeasibility_proved=True,
                    unexplained_black_cells=[list(constraints[j][0]) for j in impossible],
                    strict_upper_counterexamples=[{"source_cell": list(constraints[j][0]),
                        "constraint_role": constraints[j][2], "upper_envelope_costs": [
                            {"body_id": ids[i], "exact_cost": _enc(costs[j][i].value(F(1)))}
                            for i in constraints[j][1]]} for j in impossible])
        return base
    universal, whites = [], []
    for cell in dict.fromkeys(tuple(cell) for cell in white_cells):
        # >= is sound here: every actual alpha is strictly smaller than 1,
        # and every piece has positive upper-minus-lower radius at every t.
        if all(box_lower_distance_squared(field, cell) >= field.upper_max or
               point_cost(field, cell).value(F(1)) >= 0 for field in fields):
            universal.append(cell)
        else:
            whites.append((cell, [[point_cost(field, p) for field in fields] for p in _white_points(cell)]))
    stack, seen, model = [tuple(F(0) for _ in fields)], set(), None
    threshold_cache, rejected_white, unresolved_grid = {}, 0, False
    while stack:
        values = stack.pop()
        if values in seen:
            continue
        if len(seen) >= max_states:
            base.update(status="PENDING_BOUNDED_MODEL_SEARCH_RESOURCE_BOUND", search_complete=False,
                        resource_truncated=True, visited_state_count=len(seen))
            return base
        seen.add(values)
        if any(not any(all(cost.value(alpha) > 0 for cost, alpha in zip(witness, values))
                       for witness in witnesses) for _, witnesses in whites):
            rejected_white += 1
            continue
        missing = [j for j, row in enumerate(costs)
                   if not any(row[i].value(values[i]) <= 0 for i in candidates[j])]
        if not missing:
            model = values
            break
        j = min(missing, key=lambda k: (len(candidates[k]), k))
        for i in reversed(candidates[j]):
            key = (j, i)
            if key not in threshold_cache:
                threshold_cache[key] = _required_alpha(costs[j][i])
            required = threshold_cache[key]
            if required is None:
                unresolved_grid = True
                continue
            updated = list(values)
            updated[i] = max(updated[i], required)
            stack.append(tuple(updated))
    base.update(pass_=model is not None, visited_state_count=len(seen),
                states_rejected_by_common_white_witness=rejected_white,
                universal_white_center_count=len(universal),
                own_body_section_constraint_count=len(owned_black_constraints),
                parameter_resolution_pending=unresolved_grid)
    base["pass"] = base.pop("pass_")
    if model is None:
        base.update(status="PENDING_FINITE_PARAMETER_GRID_EXHAUSTED" if variable or unresolved_grid
                    else "NO_COHERENT_FINITE_CONSTANT_UNION",
                    search_complete=not variable and not unresolved_grid,
                    exact_family_infeasibility_proved=not variable and not unresolved_grid)
        return base
    base.update(status="COHERENT_BOUNDED_FINITE_UNION_FOUND", existence_certificate_complete=True,
                search_complete=False, exact_family_infeasibility_proved=False,
                alpha_vector=[_enc(v) for v in model],
                black_witnesses=[{"source_cell": list(cell), "constraint_role": role,
                    "body_ids": [ids[i] for i in allowed if costs[j][i].value(model[i]) <= 0]}
                    for j, (cell, allowed, role) in enumerate(constraints)],
                white_witnesses=[{"source_cell": list(cell), "point": list(cell),
                                  "valid_for_entire_width_box": True} for cell in universal])
    for cell, witnesses in whites:
        i = next(i for i, witness in enumerate(witnesses)
                 if all(cost.value(alpha) > 0 for cost, alpha in zip(witness, model)))
        base["white_witnesses"].append({"source_cell": list(cell), "point_exact": _ep(_white_points(cell)[i]),
                                         "valid_for_entire_width_box": False})
    if not variable:
        base["half_width_squared_vector"] = [_enc(field.constant_interval[0] + a *
            (field.constant_interval[1] - field.constant_interval[0])) for field, a in zip(fields, model)]
    return base
