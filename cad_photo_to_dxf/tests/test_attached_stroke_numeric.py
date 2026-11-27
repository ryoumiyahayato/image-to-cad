"""Numerical replay contract: narrow diagnostics, exact geometry and guards."""

from copy import deepcopy
from fractions import Fraction
import itertools
import math

import pytest

from app.native_objects import attached_stroke_numeric as numeric
from app.native_objects.attached_stroke_graph import POLICY


PRODUCER = "f" * 64


def _table(vectors):
    ports = [(i, 0) for i in range(len(vectors))]
    unit = {p: [v / math.hypot(*vectors[p[0]]) for v in vectors[p[0]]] for p in ports}

    def angle(a, b):
        return math.degrees(math.acos(max(-1.0, min(1.0, -sum(x * y for x, y in zip(unit[a], unit[b]))))))

    pairs = []
    for a, b in itertools.combinations(ports, 2):
        deviation = angle(a, b)
        margin = min([angle(p, c) for p in (a, b) for c in ports if c not in (a, b)], default=180.0) - deviation
        pairs.append({"pair": [list(a), list(b)], "deviation_by_fixed_span_deg": [deviation] * 3,
                      "competition_margin_by_fixed_span_deg": [margin] * 3,
                      "maximum_pair_deviation_deg": deviation, "minimum_competition_margin_deg": margin,
                      "pass": deviation <= 20.0 and margin >= 18.0})
    return {"node_id": 0, "all_ports": [list(p) for p in ports], "all_pair_candidates": pairs,
            "all_directions_complete": True, "directions_never_follow_a_different_branch": True,
            "all_observed_directions": [
                {"port": list(p), "observations": [
                    {"source_points_px": [[0.0, 0.0], list(map(float, vectors[p[0]]))],
                     "requested_span_px": span, "vector": unit[p]}
                    for span in [6.0, 8.0, 12.0]]} for p in ports]}


@pytest.fixture
def legacy_plan():
    table = _table([(7, 1), (-7, -1), (-1, 7), (1, -7)])
    return {"schema": numeric.LEGACY_SCHEMA, "producer_sha256": PRODUCER,
            "policy": deepcopy(POLICY), "prior_object_bindings": [], "paths": [],
            "source_crop_sha256": "a" * 64,
            "strict_geometry": {"points": [[1.0, 2.0], [3.0, 4.0]], "width": 0.0},
            "components": [{"component_id": "synthetic-component", "anchor_nodes": [],
                            "node_direction_evidence": [table], "decompositions": [],
                            "original_core_evidence": [], "status": "PENDING"}]}


def _replace(value, path, replacement):
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement


def test_interval_basic_operations_enclose_exact_binary64_rationals():
    a, b = numeric.Interval.point(0.1), numeric.Interval.point(0.2)
    summed = a + b
    exact = Fraction(0.1) + Fraction(0.2)
    assert Fraction(summed.low) <= exact <= Fraction(summed.high)
    divided = summed / numeric.Interval.point(3.0)
    assert Fraction(divided.low) <= exact / 3 <= Fraction(divided.high)
    squared = numeric.Interval(-0.2, 0.1).square()
    assert squared.low == 0.0 and Fraction(squared.high) >= Fraction(0.2) ** 2
    root = numeric.Interval.point(2.0).sqrt()
    assert Fraction(root.low) ** 2 <= 2 <= Fraction(root.high) ** 2


def test_rational_pi_and_angles_have_known_enclosures_without_libm_as_oracle():
    low, high = numeric._pi_bounds()
    known_low = Fraction(314159265358979323846264338327950288419716939937510, 10**50)
    known_high = known_low + Fraction(1, 10**50)
    assert known_low < low < high < known_high
    for first, second, angle in [([1, 0], [0, 1], 90.0), ([1, 0], [1, 1], 45.0),
                                 ([7, 1], [-7, -1], 180.0)]:
        assert numeric.angle_interval(first, second).contains(angle)


@pytest.mark.parametrize("threshold,operator", [(20.0, "<="), (18.0, ">="), (45.0, ">="),
                                               (12.0, "<="), (0.85, "<="), (1e-9, "<")])
def test_binary64_gate_equality_and_straddling_never_silently_pass(threshold, operator):
    equal = numeric.gate_status(numeric.Interval.point(threshold), threshold, operator)
    assert equal == ("FAIL" if operator == "<" else "PASS")
    around = numeric.Interval(math.nextafter(threshold, -math.inf), math.nextafter(threshold, math.inf))
    assert numeric.gate_status(around, threshold, operator) == "AMBIGUOUS"
    assert Fraction(threshold) == Fraction.from_float(threshold)


def test_core_projector_reference_handles_crossing_and_rejects_singular_axes():
    cross = [[[0.0, 0.0], [7.0, 1.0]], [[0.0, 0.0], [-1.0, 7.0]],
             [[0.0, 0.0], [-7.0, -1.0]], [[0.0, 0.0], [1.0, -7.0]]]
    proof = numeric.core_axis_intervals(cross)
    assert all(value.contains(0.0) for value in proof["point"])
    assert proof["residual"].contains(0.0)
    with pytest.raises(numeric.NumericalUnresolved, match="NOT_SEPARATED"):
        numeric.core_axis_intervals([[[0.0, 0.0], [5.0, 0.0]], [[0.0, 0.0], [-5.0, 0.0]]])
    with pytest.raises(numeric.NumericalUnresolved, match="PRINCIPAL_AXIS"):
        numeric.core_axis_intervals([[[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]])


def test_finite_contact_checks_outside_pairs_and_parameter_boundary():
    inside = numeric.finite_pair_intervals([0.0, 0.0], [7.0, 3.0], [3.5, -5.0], [3.5, 8.0])
    assert inside["status"] == "FINITE_INTERSECTION"
    assert inside["fractions"][0].contains(0.5)
    outside = numeric.finite_pair_intervals([0.0, 0.0], [7.0, 3.0], [8.0, -5.0], [8.0, 8.0])
    assert outside["status"] == "OUTSIDE_FINITE_SEGMENTS"
    at_boundary = [7.0 * (1 + 1e-9), 3.0 * (1 + 1e-9)]
    with pytest.raises(numeric.NumericalUnresolved, match="PARAMETER_GATE"):
        numeric.finite_pair_intervals([0.0, 0.0], [7.0, 3.0],
                                     [at_boundary[0] - 1.5, at_boundary[1] - 6.5],
                                     [at_boundary[0] + 1.5, at_boundary[1] + 6.5])


def test_contact_deduplication_boundary_is_not_a_boolean_only_check():
    left = {"points": [[0.0, 0.0], [7.0, 3.0]], "bulges": [0.0, 0.0]}
    second_x = 0.25 + 1e-7 * 7 / math.sqrt(58)
    right = {"points": [[0.25, -1.0], [0.25, 1.0], [second_x, 1.0], [second_x, -1.0]],
             "bulges": [0.0] * 4}
    with pytest.raises(numeric.NumericalUnresolved, match="DEDUPLICATION"):
        numeric.contact_geometry_intervals(left, right)


def test_legacy_compatibility_preserves_the_strict_fail_and_both_raw_values(legacy_plan):
    changed = deepcopy(legacy_plan)
    certificate = numeric.build_certificate(legacy_plan)
    chosen = None
    for row in certificate["entries"]:
        raw = numeric._at(legacy_plan, row["path"])
        other = math.nextafter(raw, math.inf)
        if row["interval"][0] <= other <= row["interval"][1]:
            chosen = row, other
            break
    assert chosen is not None
    row, other = chosen
    _replace(changed, row["path"], other)
    result = numeric.compare_legacy_plans(legacy_plan, changed, expected_producer_sha256=PRODUCER)
    assert result["pass"], result
    assert result["legacy_original_strict_status"] == "FAIL"
    assert result["status"] == "LEGACY_DIAGNOSTIC_COMPATIBILITY_PASS"
    assert not result["legacy_evidence_or_execution_relabelled"]
    assert len(result["all_differences"]) == 1
    assert result["all_differences"][0]["right"] == other


@pytest.mark.parametrize("change", ["geometry_ulp", "width_ulp", "hash", "identity", "similar_named_diagnostic",
                                    "bool_to_int", "float_to_int", "nan", "infinity", "producer"])
def test_only_exact_whitelist_can_drift_and_every_other_type_or_value_rejects(legacy_plan, change):
    changed = deepcopy(legacy_plan)
    if change == "geometry_ulp":
        changed["strict_geometry"]["points"][0][0] = math.nextafter(1.0, math.inf)
    elif change == "width_ulp":
        changed["strict_geometry"]["width"] = math.nextafter(0.0, math.inf)
    elif change == "hash":
        changed["source_crop_sha256"] = "b" * 64
    elif change == "identity":
        changed["components"][0]["component_id"] += "-other"
    elif change == "similar_named_diagnostic":
        legacy_plan["external_axis_common_point_px"] = [1.0, 2.0]
        changed["external_axis_common_point_px"] = [math.nextafter(1.0, math.inf), 2.0]
    elif change == "bool_to_int":
        changed["components"][0]["node_direction_evidence"][0]["all_directions_complete"] = 1
    elif change == "float_to_int":
        changed["strict_geometry"]["points"][0][0] = 1
    elif change == "nan":
        changed["strict_geometry"]["width"] = float("nan")
    elif change == "infinity":
        changed["strict_geometry"]["width"] = float("inf")
    elif change == "producer":
        changed["producer_sha256"] = "e" * 64
    result = numeric.compare_legacy_plans(legacy_plan, changed, expected_producer_sha256=PRODUCER)
    assert not result["pass"], result


def test_whitelisted_raw_value_still_must_fit_the_source_derived_bound(legacy_plan):
    changed = deepcopy(legacy_plan)
    changed["components"][0]["node_direction_evidence"][0]["all_pair_candidates"][0]["maximum_pair_deviation_deg"] += 0.01
    result = numeric.compare_legacy_plans(legacy_plan, changed, expected_producer_sha256=PRODUCER)
    assert not result["pass"]
    assert result["raw_diagnostic_failures"]["replayed"]


@pytest.mark.parametrize("expected", [None, "", "f" * 63, "g" * 64])
def test_legacy_expected_producer_is_an_explicit_valid_external_anchor(legacy_plan, expected):
    legacy_plan.pop("producer_sha256")
    result = numeric.compare_legacy_plans(legacy_plan, deepcopy(legacy_plan), expected_producer_sha256=expected)
    assert not result["pass"]
    assert result["reason"] == "NUMERIC_SCHEMA_OR_FROZEN_PRODUCER_IDENTITY_CHANGED"


def test_uncertain_T_attachment_keeps_the_entire_component_pending():
    table = _table([(6, 0), (-6, 0), (6, 6)])
    continuous = table["all_pair_candidates"][0]
    component = {"component_id": "synthetic-T", "anchor_nodes": [],
                 "node_direction_evidence": [table], "original_core_evidence": [],
                 "decompositions": [{"T_assignments": [{"node_id": 0,
                    "continuous_pair": [[0, 0], [1, 0]], "attached_port": [2, 0],
                    "direction_proof": continuous, "minimum_attachment_axis_separation_deg": 45.0}]}]}
    with pytest.raises(numeric.NumericalUnresolved, match="COMPONENT"):
        numeric.guard_candidate_component(component, [], POLICY)


def test_every_companion_is_checked_even_when_reported_ids_already_match():
    radians = math.radians(12.0)
    paths = [
        {"stroke_id": "a", "component_id": "c", "source_node_ids": [0], "contact_continuations": [],
         "representation": {"points": [[0.0, 0.0], [1.0, 0.0]], "bulges": [0.0, 0.0]},
         "native_endpoint_points_px": [[0.0, 0.0], [1.0, 0.0]], "parallel_crossing_companion_ids": ["b"]},
        {"stroke_id": "b", "component_id": "c", "source_node_ids": [0], "contact_continuations": [],
         "representation": {"points": [[0.0, 0.0], [math.cos(radians), math.sin(radians)]], "bulges": [0.0, 0.0]},
         "native_endpoint_points_px": [[0.0, 0.0], [math.cos(radians), math.sin(radians)]],
         "parallel_crossing_companion_ids": ["a"]},
    ]
    with pytest.raises(numeric.NumericalUnresolved, match="COMPANION_GATE"):
        numeric.build_certificate({"policy": POLICY, "paths": paths, "prior_object_bindings": [],
                                   "components": [{"component_id": "c", "anchor_nodes": [0]}]})
