"""Narrow, source-derived diagnostic contract for attached-stroke replay.

Raw producer diagnostics are retained. Only enumerated diagnostic leaves may
differ, and each actual value must fit an independently evaluated interval.
The interval chain is a finite reference arithmetic model, not a universal
error promise for a particular BLAS, LAPACK, SVD or system libm implementation.
Pixel responsibility, saved geometry, endpoints, identities and hashes never
receive a numerical tolerance from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path


CONTRACT = "attached-stroke-derived-diagnostics-interval-v1"
CERTIFICATE_SCHEMA = "attached-stroke-numerical-certificate-v1"
LEGACY_SCHEMA = "source-attached-stroke-graph-plan-v1"
PLAN_SCHEMA = "source-attached-stroke-graph-plan-v2"
ADOPTION_SCHEMA = "source-attached-stroke-adoption-v2"
EVIDENCE_SCHEMA = "source-attached-stroke-native-v2"


class NumericalUnresolved(ValueError):
    """A numerical interval cannot certify the existing discrete decision."""

    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence


def _fraction(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise NumericalUnresolved("NUMERIC_NONFINITE_OR_NONNUMERIC_INPUT")
    return Fraction(value)


def _directed(value, upwards):
    """Enclose an exact rational by binary64, checking the conversion exactly."""
    rounded = float(value)
    if not math.isfinite(rounded):
        raise NumericalUnresolved("NUMERIC_BINARY64_OVERFLOW")
    actual = Fraction(rounded)
    if (upwards and actual < value) or (not upwards and actual > value):
        rounded = math.nextafter(rounded, math.inf if upwards else -math.inf)
    if not math.isfinite(rounded):
        raise NumericalUnresolved("NUMERIC_BINARY64_OVERFLOW")
    return rounded


@dataclass(frozen=True)
class Interval:
    low: float
    high: float

    def __post_init__(self):
        if not (math.isfinite(self.low) and math.isfinite(self.high) and self.low <= self.high):
            raise NumericalUnresolved("NUMERIC_INVALID_INTERVAL")

    @classmethod
    def point(cls, value):
        exact = _fraction(value)
        return cls(_directed(exact, False), _directed(exact, True))

    @classmethod
    def rational(cls, low, high=None):
        high = low if high is None else high
        return cls(_directed(low, False), _directed(high, True))

    def __add__(self, other):
        other = _interval(other)
        return Interval.rational(Fraction(self.low) + Fraction(other.low),
                                 Fraction(self.high) + Fraction(other.high))

    __radd__ = __add__

    def __neg__(self):
        return Interval(-self.high, -self.low)

    def __sub__(self, other):
        return self + -_interval(other)

    def __rsub__(self, other):
        return _interval(other) - self

    def __mul__(self, other):
        other = _interval(other)
        values = [Fraction(a) * Fraction(b)
                  for a in (self.low, self.high) for b in (other.low, other.high)]
        return Interval.rational(min(values), max(values))

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = _interval(other)
        if other.low <= 0 <= other.high:
            raise NumericalUnresolved("NUMERIC_DENOMINATOR_INTERVAL_CONTAINS_ZERO",
                                      {"denominator_interval": other.as_list()})
        values = [Fraction(a) / Fraction(b)
                  for a in (self.low, self.high) for b in (other.low, other.high)]
        return Interval.rational(min(values), max(values))

    def square(self):
        values = [Fraction(self.low) ** 2, Fraction(self.high) ** 2]
        return Interval.rational(0 if self.low <= 0 <= self.high else min(values), max(values))

    def sqrt(self):
        if self.low < 0:
            raise NumericalUnresolved("NUMERIC_NEGATIVE_SQRT_INTERVAL")
        low, _ = _rational_sqrt_bounds(Fraction(self.low))
        _, high = _rational_sqrt_bounds(Fraction(self.high))
        return Interval.rational(low, high)

    def absolute(self):
        if self.low <= 0 <= self.high:
            return Interval(0.0, max(-self.low, self.high))
        return Interval(min(abs(self.low), abs(self.high)), max(abs(self.low), abs(self.high)))

    def hull(self, other):
        return Interval(min(self.low, other.low), max(self.high, other.high))

    def contains(self, value):
        return type(value) in (int, float) and math.isfinite(value) and self.low <= value <= self.high

    def as_list(self):
        return [self.low, self.high]


def _interval(value):
    return value if isinstance(value, Interval) else Interval.point(value)


def _minimum(values):
    values = list(values)
    return Interval(min(v.low for v in values), min(v.high for v in values))


def _maximum(values):
    values = list(values)
    return Interval(max(v.low for v in values), max(v.high for v in values))


def _rational_sqrt_bounds(value):
    if value < 0:
        raise NumericalUnresolved("NUMERIC_NEGATIVE_SQRT")
    # Fixed 192-bit *mathematical series/enclosure* accuracy, not a replay
    # tolerance. The final reference operations are still outward binary64.
    scale = 1 << 192
    root = math.isqrt((value.numerator * scale * scale) // value.denominator)
    low = Fraction(root, scale)
    return low, low if low * low == value else Fraction(root + 1, scale)


@lru_cache(maxsize=4096)
def _atan_series(value):
    """Alternating rational series, including its actual next-term remainder."""
    if value < 0:
        low, high = _atan_series(-value)
        return -high, -low
    if value > Fraction(1, 2):
        raise ValueError("ARCTANGENT_ARGUMENT_REDUCTION_REQUIRED")
    total, power, square = Fraction(0), value, value * value
    for index in range(1024):
        term = power / (2 * index + 1)
        total += term if index % 2 == 0 else -term
        power *= square
        next_term = power / (2 * index + 3)
        if next_term < Fraction(1, 1 << 192):
            other = total + (-next_term if index % 2 == 0 else next_term)
            return min(total, other), max(total, other)
    raise NumericalUnresolved("NUMERIC_ARCTANGENT_SERIES_BOUND_EXCEEDED")


@lru_cache(maxsize=1)
def _pi_bounds():
    a, b = _atan_series(Fraction(1, 5)), _atan_series(Fraction(1, 239))
    return 16 * a[0] - 4 * b[1], 16 * a[1] - 4 * b[0]


@lru_cache(maxsize=4096)
def _atan_bounds(value):
    if value < 0:
        low, high = _atan_bounds(-value)
        return -high, -low
    pi_low, pi_high = _pi_bounds()
    if value > 1:
        low, high = _atan_bounds(1 / value)
        return pi_low / 2 - high, pi_high / 2 - low
    if value > Fraction(1, 2):
        low, high = _atan_series((value - 1) / (value + 1))
        return pi_low / 4 + low, pi_high / 4 + high
    return _atan_series(value)


@lru_cache(maxsize=4096)
def _acos_bounds(value):
    """Rational enclosure of acos at an exact binary64 argument."""
    x = Fraction(value)
    pi_low, pi_high = _pi_bounds()
    if x == 1:
        return Fraction(0), Fraction(0)
    if x == -1:
        return pi_low, pi_high
    if x == 0:
        return pi_low / 2, pi_high / 2
    low, high = _rational_sqrt_bounds(1 - x * x)
    a = _atan_bounds(low / abs(x))[0]
    b = _atan_bounds(high / abs(x))[1]
    return (a, b) if x > 0 else (pi_low - b, pi_high - a)


def _unit(vector):
    vector = [_interval(v) for v in vector]
    length = sum(v.square() for v in vector).sqrt()
    denominator = Interval(max(length.low, 1e-12), max(length.high, 1e-12))
    return [v / denominator for v in vector]


def angle_interval(first, second):
    a, b = _unit(first), _unit(second)
    dot = sum(x * y for x, y in zip(a, b))
    low, high = max(-1.0, dot.low), min(1.0, dot.high)
    if low > high:
        raise NumericalUnresolved("NUMERIC_DOT_PRODUCT_OUTSIDE_UNIT_RANGE")
    radians = Interval.rational(_acos_bounds(high)[0], _acos_bounds(low)[1])
    # The conversion constant is enclosed by the two binary64 neighbours of
    # true pi, covering the ordinary rounded pi constant without a libm claim.
    pi = Interval.rational(*_pi_bounds())
    return radians * (Interval.point(180.0) / pi)


def axis_separation_interval(first, second):
    return _minimum([angle_interval(first, second), angle_interval(first, [-v for v in second])])


def gate_status(value, threshold, operator):
    """Use exactly the existing binary64 threshold, including its endpoint."""
    bound = _fraction(threshold)
    low, high = Fraction(value.low), Fraction(value.high)
    if operator == "<=":
        return "PASS" if high <= bound else "FAIL" if low > bound else "AMBIGUOUS"
    if operator == ">=":
        return "PASS" if low >= bound else "FAIL" if high < bound else "AMBIGUOUS"
    if operator == "<":
        return "PASS" if high < bound else "FAIL" if low >= bound else "AMBIGUOUS"
    raise ValueError("UNKNOWN_NUMERIC_GATE")


def _chord(observation):
    points = observation["source_points_px"]
    return [Interval.point(points[-1][i]) - Interval.point(points[0][i]) for i in range(2)]


def direction_intervals(table):
    observed = {tuple(row["port"]): [_chord(o) for o in row["observations"]]
                for row in table["all_observed_directions"]}
    pairs = {}
    for row in table["all_pair_candidates"]:
        a, b = map(tuple, row["pair"])
        values, margins = [], []
        for index, (first, second) in enumerate(zip(observed[a], observed[b])):
            value = angle_interval(first, [-v for v in second])
            alternatives = [angle_interval(observed[p][index], [-v for v in observed[c][index]])
                            for p in (a, b) for c in observed if c not in (a, b)]
            values.append(value)
            margins.append((_minimum(alternatives) if alternatives else Interval.point(180.0)) - value)
        pairs[frozenset((a, b))] = {"deviation_by_fixed_span_deg": values,
                                  "competition_margin_by_fixed_span_deg": margins,
                                  "maximum_pair_deviation_deg": _maximum(values),
                                  "minimum_competition_margin_deg": _minimum(margins)}
    return observed, pairs


def core_axis_intervals(samples_by_port):
    projectors, centers, gaps = [], [], []
    for samples in samples_by_port:
        points = [[Interval.point(v) for v in point] for point in samples]
        center = [sum(point[k] for point in points) / len(points) for k in range(2)]
        relative = [[point[k] - center[k] for k in range(2)] for point in points]
        xx = sum(p[0].square() for p in relative)
        yy = sum(p[1].square() for p in relative)
        xy = sum(p[0] * p[1] for p in relative)
        gap = ((xx - yy).square() + 4 * xy.square()).sqrt()
        if gap.low <= 0:
            raise NumericalUnresolved("NUMERIC_CORE_PRINCIPAL_AXIS_NOT_SEPARATED",
                                      {"axis_index": len(projectors), "spectral_gap_interval_px2": gap.as_list()})
        ratio = (xx - yy) / gap
        cross = -xy / gap
        projectors.append([[(1 - ratio) / 2, cross], [cross, (1 + ratio) / 2]])
        centers.append(center)
        gaps.append(gap.as_list())
    if not projectors:
        raise NumericalUnresolved("NUMERIC_CORE_HAS_NO_FINITE_AXIS_OBSERVATIONS")
    h = [[sum(p[i][j] for p in projectors) for j in range(2)] for i in range(2)]
    rhs = [sum(p[i][0] * c[0] + p[i][1] * c[1]
               for p, c in zip(projectors, centers)) for i in range(2)]
    determinant = h[0][0] * h[1][1] - h[0][1] * h[1][0]
    if determinant.low <= 0:
        raise NumericalUnresolved("NUMERIC_COMMON_CORE_AXES_NOT_SEPARATED",
                                  {"normal_equation_determinant_interval": determinant.as_list(),
                                   "normal_equation_matrix": _serialize(h)})
    point = [(rhs[0] * h[1][1] - h[0][1] * rhs[1]) / determinant,
             (h[0][0] * rhs[1] - rhs[0] * h[1][0]) / determinant]
    residuals = []
    for projector, center in zip(projectors, centers):
        dx, dy = [point[k] - center[k] for k in range(2)]
        squared = (projector[0][0] * dx.square() + 2 * projector[0][1] * dx * dy
                   + projector[1][1] * dy.square())
        # The exact normal projector is positive semidefinite. Negative lower
        # interval endpoints are dependence overestimation, not negative ink.
        if squared.high < 0:
            raise NumericalUnresolved("NUMERIC_CORE_DISTANCE_ENCLOSURE_INVALID")
        residuals.append(Interval(max(0.0, squared.low), squared.high).sqrt())
    return {"point": point, "residual": _maximum(residuals),
            "scatter_spectral_gap_intervals_px2": gaps,
            "normal_equation_determinant_interval": determinant.as_list()}


def _det(a, b):
    return a[0] * b[1] - a[1] * b[0]


def finite_pair_intervals(a, b, c, d):
    a, b, c, d = [[Interval.point(v) for v in point] for point in (a, b, c, d)]
    first, second, rhs = ([b[k] - a[k] for k in range(2)],
                          [c[k] - d[k] for k in range(2)],
                          [c[k] - a[k] for k in range(2)])
    determinant = _det(first, second)
    parallel = gate_status(determinant.absolute(), 1e-9, "<")
    if parallel == "AMBIGUOUS":
        raise NumericalUnresolved("NUMERIC_FINITE_DETERMINANT_GATE_UNRESOLVED",
                                  {"determinant_interval_px2": determinant.as_list(),
                                   "existing_threshold_binary64_hex": float(1e-9).hex()})
    if parallel == "PASS":
        return {"status": "PARALLEL_BY_EXISTING_GATE", "determinant": determinant}
    u, v = _det(rhs, second) / determinant, _det(first, rhs) / determinant
    # Also enclose the ordinary pivoted 2x2 elimination chain. This is a
    # named finite reference model, not a guarantee about all LAPACK builds.
    rows = [[first[i], second[i], rhs[i]] for i in range(2)]
    magnitudes = [row[0].absolute() for row in rows]
    if magnitudes[0].low >= magnitudes[1].high:
        orders = [(0, 1)]
    elif magnitudes[1].low > magnitudes[0].high:
        orders = [(1, 0)]
    else:
        orders = [(0, 1), (1, 0)]
    for top, bottom in orders:
        pivot, lower = rows[top], rows[bottom]
        if pivot[0].low <= 0 <= pivot[0].high:
            continue
        factor = lower[0] / pivot[0]
        vv = (lower[2] - factor * pivot[2]) / (lower[1] - factor * pivot[1])
        uu = (pivot[2] - pivot[1] * vv) / pivot[0]
        u, v = u.hull(uu), v.hull(vv)
    gates = [gate_status(value, threshold, operator) for value in (u, v)
             for threshold, operator in ((-1e-9, ">="), (1 + 1e-9, "<="))]
    if "FAIL" in gates:
        status = "OUTSIDE_FINITE_SEGMENTS"
    elif "AMBIGUOUS" in gates:
        raise NumericalUnresolved("NUMERIC_FINITE_PARAMETER_GATE_UNRESOLVED",
                                  {"parameter_intervals": [u.as_list(), v.as_list()],
                                   "existing_bounds_binary64_hex": [float(-1e-9).hex(), float(1 + 1e-9).hex()]})
    else:
        status = "FINITE_INTERSECTION"
    return {"status": status, "determinant": determinant, "fractions": [u, v],
            "point": [a[k] + u * first[k] for k in range(2)]}


def contact_geometry_intervals(left, right):
    if any(float(b) for geometry in (left, right) for b in geometry["bulges"]):
        raise NumericalUnresolved("NUMERIC_CURVED_NATIVE_CONTACT_NOT_SUPPORTED")
    all_pairs, retained = [], []
    for i, (a, b) in enumerate(zip(left["points"], left["points"][1:])):
        for j, (c, d) in enumerate(zip(right["points"], right["points"][1:])):
            row = finite_pair_intervals(a, b, c, d)
            row["segment_indices"] = [i, j]
            if row["status"] == "FINITE_INTERSECTION":
                duplicate = False
                for previous in retained:
                    distance = sum((x - y).square() for x, y in zip(row["point"], previous["point"])).sqrt()
                    state = gate_status(distance, 1e-7, "<")
                    if state == "AMBIGUOUS":
                        raise NumericalUnresolved("NUMERIC_FINITE_CONTACT_DEDUPLICATION_UNRESOLVED",
                                                  {"segment_indices": [i, j],
                                                   "prior_segment_indices": previous["segment_indices"],
                                                   "distance_interval_px": distance.as_list(),
                                                   "existing_threshold_binary64_hex": float(1e-7).hex()})
                    duplicate |= state == "PASS"
                row["status"] = "DUPLICATE_POINT" if duplicate else "RETAINED_FINITE_INTERSECTION"
                if not duplicate:
                    retained.append(row)
            all_pairs.append(row)
    return all_pairs, retained


def _geometry(obj):
    if obj["kind"] == "LINE":
        return {"points": [obj["geometry"]["start"], obj["geometry"]["end"]],
                "bulges": [0.0, 0.0], "closed": False}
    return obj["geometry"]


def _json_path(path):
    return "$" + "".join(f"[{p}]" if type(p) is int else "." + p for p in path)


def _at(value, path):
    for part in path:
        value = value[part]
    return value


def _serialize(value):
    if isinstance(value, Interval):
        return value.as_list()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value


def contract_identity():
    return {"version": CONTRACT, "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "finite_reference_arithmetic_model_not_universal_math_library_error_promise": True,
            "raw_diagnostics_retained": True, "non_whitelisted_values_strict": True}


def build_certificate(plan):
    """Enumerate exact allowed paths; no arbitrary recursive float matching."""
    policy = plan["policy"]
    entries, gates, conditioning, contact_checks, companion_checks = [], [], [], [], []
    unresolved_components = []
    core_cache = {}
    geometries = {row["stroke_id"]: row["representation"] for row in plan["paths"]}
    geometries.update({obj["id"]: _geometry(obj) for obj in plan.get("prior_object_bindings", [])
                       if obj["kind"] in ("LINE", "CONNECTION_PATH")})

    def add(path, value, unit, formula):
        entries.append({"path": list(path), "unit": unit, "interval": value.as_list(), "formula": formula})

    def gate(path, value, threshold, operator, name):
        gates.append({"path": list(path), "gate": name, "interval": value.as_list(),
                      "threshold_binary64_hex": float(threshold).hex(), "operator": operator,
                      "status": gate_status(value, threshold, operator)})

    def add_pair(path, intervals, with_gates=True):
        for field, value in intervals.items():
            if isinstance(value, list):
                for i, item in enumerate(value):
                    add((*path, field, i), item, "degree", "source_chord_norm_dot_acos_interval")
            else:
                add((*path, field), value, "degree", "source_chord_norm_dot_acos_interval")
        if with_gates:
            gate((*path, "maximum_pair_deviation_deg"), intervals["maximum_pair_deviation_deg"],
                 policy["maximum_pair_deviation_deg"], "<=", "maximum_pair_deviation")
            gate((*path, "minimum_competition_margin_deg"), intervals["minimum_competition_margin_deg"],
                 policy["minimum_pair_margin_deg"], ">=", "minimum_pair_competition_margin")

    def add_core(path, core):
        nid = core["node_id"]
        if nid not in core_cache:
            raise NumericalUnresolved("NUMERIC_CORE_FINITE_DIRECTIONS_NOT_RECORDED")
        numeric = core_cache[nid]
        for i, value in enumerate(numeric["point"]):
            add((*path, "external_axis_common_point_px", i), value, "source_px", "principal_normal_projectors_2x2_solve")
        add((*path, "axis_intersection_residual_px"), numeric["residual"], "source_px", "normal_projector_distance_maximum")
        if core["core_topology"]["cycle_rank"]:
            gate((*path, "axis_intersection_residual_px"), numeric["residual"],
                 policy["maximum_cycle_axis_intersection_residual_px"], "<=", "cycle_axis_residual")
            left, top, right, bottom = core["raw_ink_box_xyxy_px"]
            mask = core["raw_ink_mask"]
            xs = range(math.ceil(numeric["point"][0].low - 0.5), math.floor(numeric["point"][0].high + 0.5) + 1)
            ys = range(math.ceil(numeric["point"][1].low - 0.5), math.floor(numeric["point"][1].high + 0.5) + 1)
            black = all(left <= x < right and top <= y < bottom and mask[y - top][x - left] == 1
                        for x in xs for y in ys)
            gates.append({"path": list(path), "gate": "cycle_common_point_entire_interval_original_ink",
                          "status": "PASS" if black else "AMBIGUOUS", "point_intervals_px": _serialize(numeric["point"])})

    for ci, component in enumerate(plan["components"]):
        base = ("components", ci)
        if plan.get("schema") == PLAN_SCHEMA and component.get("numerical_status") == "PENDING":
            if (component["status"] != "PENDING"
                    or any(row.get("component_id") == component["component_id"] for row in plan["paths"])
                    or "numerical_pending_candidate_paths" not in component):
                raise NumericalUnresolved("NUMERIC_UNRESOLVED_COMPONENT_MUST_NOT_HAVE_ADOPTED_PATHS")
            # This is a replayable *negative* result, not a numeric certificate.
            # Its entire raw candidate/evidence subtree remains strict; no
            # diagnostic whitelist is granted to an unresolved component.
            unresolved_components.append({"component_id": component["component_id"],
                                          "reason": component["reason"],
                                          "raw_candidate_replay": "STRICT_ONLY",
                                          "adoption_numeric_certified": False})
            continue
        tables = {}
        for ti, table in enumerate(component.get("node_direction_evidence", [])):
            observed, pairs = direction_intervals(table)
            tables[table["node_id"]] = (observed, pairs)
            core_cache[table["node_id"]] = core_axis_intervals(
                [row["observations"][-1]["source_points_px"] for row in table["all_observed_directions"]])
            conditioning.append({"component_index": ci, "node_id": table["node_id"],
                                 **{key: value for key, value in core_cache[table["node_id"]].items()
                                    if key not in ("point", "residual")}})
            for pi, pair in enumerate(table["all_pair_candidates"]):
                add_pair((*base, "node_direction_evidence", ti, "all_pair_candidates", pi),
                         pairs[frozenset(map(tuple, pair["pair"]))])
        for di, decomposition in enumerate(component.get("decompositions", [])):
            for ai, assignment in enumerate(decomposition["T_assignments"]):
                observed, pairs = tables[assignment["node_id"]]
                pair = list(map(tuple, assignment["continuous_pair"]))
                path = (*base, "decompositions", di, "T_assignments", ai)
                add_pair((*path, "direction_proof"), pairs[frozenset(pair)], with_gates=False)
                single = tuple(assignment["attached_port"])
                separation = _minimum(axis_separation_interval(x, y) for port in pair
                                      for x, y in zip(observed[single], observed[port]))
                add((*path, "minimum_attachment_axis_separation_deg"), separation, "degree", "source_chord_axis_separation")
                gate((*path, "minimum_attachment_axis_separation_deg"), separation,
                     policy["minimum_attachment_axis_separation_deg"], ">=", "minimum_attachment_axis_separation")
        for ki, core in enumerate(component.get("original_core_evidence", [])):
            add_core((*base, "original_core_evidence", ki), core)
        for pi, pair in enumerate(component.get("native_contact_check", {}).get("pair_checks", [])):
            a, b = pair["object_ids"]
            all_pairs, retained = contact_geometry_intervals(geometries[a], geometries[b])
            path = (*base, "native_contact_check", "pair_checks", pi)
            contact_checks.append({"path": list(path), "all_segment_pairs": _serialize(all_pairs)})
            actual_rows = []
            for ni, node in enumerate(pair["finite_native_contacts"]):
                for ii, hit in enumerate(node["contacts"]):
                    actual_rows.append(((*path, "finite_native_contacts", ni, "contacts", ii), hit))
            actual_rows += [((*path, "unexpected_contacts", ii), hit)
                            for ii, hit in enumerate(pair.get("unexpected_contacts", []))]
            expected = {tuple(row["segment_indices"]): row for row in retained}
            if {tuple(hit["segment_indices"]) for _, hit in actual_rows} != set(expected):
                raise NumericalUnresolved("NUMERIC_FINITE_CONTACT_SET_DIFFERS_FROM_REFERENCE_MODEL")
            for hit_path, hit in actual_rows:
                reference = expected[tuple(hit["segment_indices"])]
                if not all(value.contains(actual) for value, actual in zip(reference["point"], hit["point_px"])):
                    raise NumericalUnresolved("NUMERIC_ACTUAL_CONTACT_POINT_OUTSIDE_REFERENCE_ENCLOSURE")
                for ii, value in enumerate(reference["fractions"]):
                    add((*hit_path, "finite_segment_fractions", ii), value, "dimensionless", "2x2_determinant_and_pivoted_elimination")
        anchors = set(component["anchor_nodes"])
        crossed = [row for row in plan["paths"]
                   if row.get("component_id", component["component_id"]) == component["component_id"]
                   and set(row["source_node_ids"]) & anchors]
        for row in crossed:
            endpoints = row["native_endpoint_points_px"]
            axis = [Interval.point(endpoints[1][k]) - Interval.point(endpoints[0][k]) for k in range(2)]
            candidates, passing = [], []
            for other in crossed:
                if other is row:
                    continue
                other_points = other["native_endpoint_points_px"]
                other_axis = [Interval.point(other_points[1][k]) - Interval.point(other_points[0][k]) for k in range(2)]
                value = axis_separation_interval(axis, other_axis)
                status = gate_status(value, policy["maximum_companion_axis_angle_deg"], "<=")
                if status == "AMBIGUOUS":
                    raise NumericalUnresolved("NUMERIC_PARALLEL_COMPANION_GATE_UNRESOLVED",
                                              {"stroke_id": row["stroke_id"], "other_id": other["stroke_id"],
                                               "angle_interval_deg": value.as_list(),
                                               "existing_threshold_binary64_hex": float(policy["maximum_companion_axis_angle_deg"]).hex()})
                candidates.append({"other_id": other["stroke_id"], "interval_deg": value.as_list(), "status": status})
                if status == "PASS":
                    passing.append(other["stroke_id"])
            if passing != row.get("parallel_crossing_companion_ids", []):
                raise NumericalUnresolved("NUMERIC_COMPLETE_COMPANION_SET_DIFFERS_FROM_REFERENCE_MODEL")
            companion_checks.append({"stroke_id": row["stroke_id"], "all_other_crossing_candidates": candidates,
                                     "minimum_companion_count": policy["minimum_parallel_crossing_companions"]})
    for pi, row in enumerate(plan["paths"]):
        for ki, core in enumerate(row["contact_continuations"]):
            add_core(("paths", pi, "contact_continuations", ki), core)
    entries.sort(key=lambda row: _json_path(row["path"]))
    if len({tuple(row["path"]) for row in entries}) != len(entries):
        raise NumericalUnresolved("NUMERIC_DUPLICATE_WHITELIST_PATH")
    return {"schema": CERTIFICATE_SCHEMA, "contract": CONTRACT, "entries": entries,
            "gates": gates, "conditioning": conditioning, "complete_finite_segment_checks": contact_checks,
            "complete_companion_checks": companion_checks,
            "unresolved_components_strict_only": unresolved_components,
            "attachment_endpoint_construction_and_native_fitting_numeric_guards": "NOT_CHANGED_BY_THIS_CONTRACT"}


def validate_raw_diagnostics(plan, certificate):
    failures = []
    for row in certificate["entries"]:
        value = _at(plan, row["path"])
        if type(value) is not float or not Interval(*row["interval"]).contains(value):
            failures.append({"path": _json_path(row["path"]), "value": value,
                             "interval": row["interval"], "unit": row["unit"]})
    return failures


def guard_candidate_component(component, rows, policy):
    """Check every competitor before declaring a decomposition adoptable."""
    owners = {row["required_crossing_path_binding"]["id"]: row["required_crossing_path_binding"] for row in rows}
    temporary = {"policy": policy, "components": [component], "paths": rows,
                 "prior_object_bindings": list(owners.values())}
    certificate = build_certificate(temporary)
    failures = validate_raw_diagnostics(temporary, certificate)
    ambiguous = [gate for gate in certificate["gates"] if gate["status"] == "AMBIGUOUS"]
    if failures or ambiguous:
        raise NumericalUnresolved("NUMERIC_COMPONENT_DIAGNOSTICS_OR_DECISIONS_UNRESOLVED",
                                  {"raw_diagnostic_failures": failures, "ambiguous_gates": ambiguous,
                                   "certificate": certificate})


def _strict_differences(left, right, allowed, path=(), differences=None):
    differences = [] if differences is None else differences
    if type(left) is not type(right):
        differences.append({"path": _json_path(path), "kind": "TYPE_CHANGED", "left": left, "right": right})
    elif isinstance(left, dict):
        if any(type(key) is not str for key in [*left, *right]):
            differences.append({"path": _json_path(path), "kind": "NON_STRING_JSON_KEY"})
            return differences
        if left.keys() != right.keys():
            differences.append({"path": _json_path(path), "kind": "KEY_SET_CHANGED"})
        for key in left.keys() & right.keys():
            _strict_differences(left[key], right[key], allowed, (*path, key), differences)
    elif isinstance(left, list):
        if len(left) != len(right):
            differences.append({"path": _json_path(path), "kind": "LENGTH_CHANGED"})
        for index, (a, b) in enumerate(zip(left, right)):
            _strict_differences(a, b, allowed, (*path, index), differences)
    elif type(left) is float and (not math.isfinite(left) or not math.isfinite(right)):
        differences.append({"path": _json_path(path), "kind": "NONFINITE_VALUE"})
    elif type(left) not in (str, int, float, bool, type(None)):
        differences.append({"path": _json_path(path), "kind": "NON_JSON_SCALAR"})
    elif left != right or type(left) is float and left.hex() != right.hex():
        differences.append({"path": _json_path(path), "kind": "ALLOWED_DIAGNOSTIC" if path in allowed else "STRICT_VALUE_CHANGED",
                            "left": left, "right": right})
    return differences


def compare_plans(saved, replayed, *, expected_schema, expected_producer_sha256):
    """Diagnostic comparison only; actual saved-file bindings stay separate."""
    strict = _strict_differences(saved, replayed, set())
    base = {"contract": contract_identity(), "original_strict_equal": not strict,
            "pass": False, "scope": "NUMERICAL_REPLAY_ONLY_NOT_SAVED_GEOMETRY_OR_RAW_INK_ADOPTION"}
    try:
        base.update(saved_plan_sha256=_digest(saved), replayed_plan_sha256=_digest(replayed))
    except (ValueError, TypeError):
        return {**base, "reason": "NUMERIC_NONFINITE_OR_NON_JSON_PLAN", "strict_changes": strict}
    if (not isinstance(expected_producer_sha256, str) or len(expected_producer_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_producer_sha256)
            or saved.get("schema") != expected_schema or replayed.get("schema") != expected_schema
            or saved.get("producer_sha256") != expected_producer_sha256
            or replayed.get("producer_sha256") != expected_producer_sha256):
        return {**base, "reason": "NUMERIC_SCHEMA_OR_FROZEN_PRODUCER_IDENTITY_CHANGED"}
    try:
        first, second = build_certificate(saved), build_certificate(replayed)
        certificate_differences = _strict_differences(first, second, set())
        allowed = {tuple(row["path"]) for row in first["entries"]}
        differences = _strict_differences(saved, replayed, allowed)
        strict_changes = [row for row in differences if row["kind"] != "ALLOWED_DIAGNOSTIC"]
        raw_failures = {"saved": validate_raw_diagnostics(saved, first),
                        "replayed": validate_raw_diagnostics(replayed, second)}
        ambiguous = [row for row in first["gates"] + second["gates"] if row["status"] == "AMBIGUOUS"]
        okay = not (certificate_differences or strict_changes or any(raw_failures.values()) or ambiguous)
        unresolved = bool(first["unresolved_components_strict_only"])
        reason = ("MATCHED_STRICT_REPLAY_OF_NUMERICALLY_PENDING_PLAN" if unresolved
                  else "PASS_NARROW_NUMERICAL_CONTRACT") if okay else "NUMERIC_CONTRACT_REPLAY_REJECTED"
        return {**base, "pass": okay, "reason": reason,
                "numeric_adoption_status": "PENDING" if first["unresolved_components_strict_only"] else "CERTIFIED_DIAGNOSTICS_ONLY",
                "all_differences": differences, "strict_changes": strict_changes,
                "certificate_differences": certificate_differences,
                "raw_diagnostic_failures": raw_failures, "ambiguous_gates": ambiguous,
                "certificate": first}
    except (NumericalUnresolved, KeyError, TypeError, ValueError, IndexError) as exc:
        return {**base, "reason": "NUMERIC_CONTRACT_UNRESOLVED", "detail": str(exc),
                "numerical_failure_evidence": getattr(exc, "evidence", None)}


def compare_legacy_plans(saved, replayed, *, expected_producer_sha256):
    result = compare_plans(saved, replayed, expected_schema=LEGACY_SCHEMA,
                           expected_producer_sha256=expected_producer_sha256)
    result["legacy_original_strict_status"] = "PASS" if result["original_strict_equal"] else "FAIL"
    result["status"] = "LEGACY_DIAGNOSTIC_COMPATIBILITY_PASS" if result["pass"] else "LEGACY_DIAGNOSTIC_COMPATIBILITY_REJECTED"
    result["legacy_evidence_or_execution_relabelled"] = False
    return result


def compare_path_records(saved, replayed, certificate):
    """Repeat the cold audit's path check under its already verified certificate."""
    if not isinstance(saved, list) or not isinstance(replayed, list):
        return {"pass": False, "reason": "NUMERIC_REPLAY_PATH_LIST_INVALID"}
    allowed, intervals = set(), {}
    for row in certificate["entries"]:
        path = row["path"]
        # Explicit path grammar; a supplied certificate cannot authorize
        # geometry, endpoints or similarly named fields elsewhere.
        if (len(path) in (5, 6) and path[0] == "paths" and type(path[1]) is int
                and path[2] == "contact_continuations" and type(path[3]) is int
                and ((len(path) == 5 and path[4] == "axis_intersection_residual_px")
                     or (len(path) == 6 and path[4] == "external_axis_common_point_px"
                         and type(path[5]) is int and path[5] in (0, 1)))):
            local = tuple(path[1:])
            allowed.add(local)
            intervals[local] = Interval(*row["interval"])
    changes = _strict_differences(saved, replayed, allowed)
    invalid = [row for row in changes if row["kind"] != "ALLOWED_DIAGNOSTIC"]
    for path, interval in intervals.items():
        try:
            if not interval.contains(_at(saved, path)) or not interval.contains(_at(replayed, path)):
                invalid.append({"path": _json_path(path), "kind": "DIAGNOSTIC_OUTSIDE_ENCLOSURE"})
        except (KeyError, TypeError, IndexError):
            invalid.append({"path": _json_path(path), "kind": "MISSING_CERTIFIED_PATH"})
    return {"pass": not invalid, "contract": CONTRACT, "all_differences": changes,
            "strict_or_outside_interval_changes": invalid}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
