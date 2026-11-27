"""Falsification controls for exact finite-cell and source-width predicates.

Fixtures are analytical small geometries and authored integer raster strips.
No private image cells, source IDs, or target coordinates are embedded here.
"""
from fractions import Fraction
import json
import math

import numpy as np
import pytest

from app.native_objects import attached_stroke_width_exact as exact


def _strip():
    source = np.full((64, 64), 255, dtype=np.uint8)
    source[30:35, 8:57] = 0
    return source


def _section(source, x, **kwargs):
    return exact.measure_section(source, (x, 32), (8, 32), (56, 32), **kwargs)


def test_supplied_binary64_is_not_rounded_to_decimal_or_integer():
    assert exact.rational(0.1) == Fraction(3602879701896397, 36028797018963968)
    assert exact.rational(0.1) != Fraction(1, 10)
    value = math.nextafter(4.0, math.inf)
    assert exact.rational(value) > 4
    assert exact.rational(np.int64(9)) == 9
    assert exact.rational(np.float64(0.1)) == exact.rational(0.1)


@pytest.mark.parametrize("value", [True, np.bool_(False), float("nan"), float("inf"), "0.1"])
def test_invalid_numeric_types_cannot_enter_exact_geometry(value):
    with pytest.raises(ValueError):
        exact.rational(value)


def test_json_roundtrip_keeps_a_sub_ulp_nonempty_interval():
    lower = Fraction(1)
    upper = lower + Fraction(1, 2**180)
    assert float(lower) == float(upper)
    record = json.loads(json.dumps(exact.encode_interval(lower, upper)))
    assert exact.decode_interval(record) == (lower, upper)
    rows = [{"constraint_eligible": True, "half_width_squared_interval": record}] * 2
    result = exact.intersect_sections(rows)
    assert result["pass"]
    assert result["exact_interval_nonempty"]
    assert exact.decode_interval(result["half_width_squared_interval"])[0] < upper
    record["upper_closed"] = True
    with pytest.raises(ValueError, match="OPEN_UPPER"):
        exact.decode_interval(record)


@pytest.mark.parametrize("record", [
    {"numerator": 1, "denominator": 2},
    {"numerator": "2", "denominator": "4"},
    {"numerator": "01", "denominator": "2"},
    {"numerator": "1", "denominator": "0"},
])
def test_exact_record_does_not_accept_ambiguous_or_invalid_serializations(record):
    with pytest.raises(ValueError):
        exact.decode_rational(record)


def test_finite_projection_keeps_endpoint_cap_distance():
    distance, fraction, nearest = exact.project_point_segment((3, 4), (0, 0), (2, 0))
    assert (distance, fraction, nearest) == (17, 1, (2, 0))
    assert exact.point_segment_distance_squared((1, 3), (0, 0), (2, 0)) == 9
    # The cell-to-endpoint distance is 1.5² + .5², not the infinite-line .5².
    assert exact.cell_segment_distance_squared((3, 1), (0, 0), (1, 0)) == Fraction(5, 2)


def test_diagonal_cells_include_closed_corner_touch_but_keep_finite_end():
    assert exact.cell_segment_distance_squared((1, 0), (0, 0), (1, 1)) == 0
    assert exact.cell_segment_distance_squared((2, 1), (0, 0), (1, 1)) == Fraction(1, 4)
    assert exact.cell_segment_distance_squared((2, 2), (0, 0), (1, 1)) == Fraction(1, 2)


def test_segment_supercover_keeps_half_pixel_ownership_exact():
    tiny = Fraction(1, 2**180)
    assert exact.segment_cells((Fraction(1, 2) + tiny, 0), (Fraction(1, 2) + tiny, 2)) == [
        (1, 0), (1, 1), (1, 2)]
    assert exact.segment_cells((Fraction(1, 2), 0), (Fraction(1, 2), 2)) == [
        (0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    assert exact.segment_cells((Fraction(-1, 2), Fraction(-1, 2)),
                               (Fraction(1, 2), Fraction(1, 2))) == [
        (-1, -1), (-1, 0), (0, -1), (0, 0), (0, 1), (1, 0), (1, 1)]
    # A minuscule endpoint change can cross a real closed source-cell boundary.
    changed = exact.segment_cells((Fraction(1, 2) + tiny, 0), (Fraction(1, 2) - tiny, 2))
    assert (0, 2) in changed and (1, 0) in changed


def test_complete_polyline_minimum_uses_exact_projection_and_safe_box_pruning():
    points = [(0, 0), (3, 4), (20, 4), (20, 20)]
    prepared = exact.prepare_polyline(points)
    distance, index, fraction, nearest = exact.project_point_polyline((2, 2), prepared)
    assert (distance, index, fraction, nearest) == (
        Fraction(4, 25), 0, Fraction(14, 25), (Fraction(42, 25), Fraction(56, 25)))
    assert exact.cell_polyline_distance_squared((21, 10), prepared) == Fraction(1, 4)
    with pytest.raises(ValueError, match="ZERO_LENGTH"):
        exact.prepare_polyline([(0, 0), (0, 0)])


def test_exact_finite_normal_enumerates_boundary_touch_cells():
    assert exact.normal_section_cells((10, 10), (0, 10), (20, 10), Fraction(1, 2)) == [
        (10, 9), (10, 10), (10, 11)]
    assert exact.normal_section_cells((Fraction(1, 2), 0), (0, 0), (1, 0), Fraction(1, 2)) == [
        (0, -1), (0, 0), (0, 1), (1, -1), (1, 0), (1, 1)]
    assert exact.normal_section_cells((0, 0), (-1, -1), (1, 1), 1) == [
        (-1, 0), (-1, 1), (0, -1), (0, 0), (0, 1), (1, -1), (1, 0)]
    assert exact.normal_section_cells((0, 0), (-1, -1), (1, 1), Fraction(1, 2)) == [(0, 0)]


def test_rounded_projection_cannot_pose_as_a_point_on_the_exact_axis():
    _, _, q = exact.project_point_segment((1, 0), (0, 0), (2, 5))
    assert q == (Fraction(4, 29), Fraction(10, 29))
    rounded = tuple(float(value) for value in q)
    with pytest.raises(ValueError, match="EXACTLY_ON_NATIVE_AXIS"):
        exact.normal_section_cells(rounded, (0, 0), (2, 5))
    assert exact.normal_section_cells(q, (0, 0), (2, 5))


def test_closed_black_touch_and_strict_white_touch_are_different_predicates():
    path = [(8, 32), (56, 32)]
    black_limit = Fraction(9, 4)
    assert exact.cell_is_covered((20, 34), path, black_limit)
    assert not exact.cell_is_covered((20, 34), path, black_limit - Fraction(1, 2**180))
    white_limit = Fraction(49, 4)
    assert not exact.white_cell_has_exterior_witness((20, 35), [path], [white_limit])
    assert exact.white_cell_has_exterior_witness((20, 35), [path], [white_limit - Fraction(1, 2**180)])


def test_white_union_needs_one_common_exterior_point():
    left = [(Fraction(-1, 2), -3), (Fraction(-1, 2), 3)]
    right = [(Fraction(1, 2), -3), (Fraction(1, 2), 3)]
    radius = Fraction(1, 4)
    assert exact.white_cell_has_exterior_witness((0, 0), [left], [radius])
    assert exact.white_cell_has_exterior_witness((0, 0), [right], [radius])
    assert not exact.white_cell_has_exterior_witness((0, 0), [left, right], [radius, radius])


def test_finite_cap_true_tail_and_white_gap_are_not_infinite_axis_explanations():
    finite = [(4, 32), (20, 32)]
    radius = Fraction(9, 4)
    assert exact.cell_is_covered((22, 32), finite, radius)
    assert not exact.cell_is_covered((23, 32), finite, radius)
    paths = [[(8, 32), (19, 32)], [(21, 32), (56, 32)]]
    assert exact.white_cell_has_exterior_witness((20, 32), paths, [Fraction(1, 10)] * 2)
    assert not exact.white_cell_has_exterior_witness((20, 32), paths, [Fraction(5, 4)] * 2)
    assert not exact.white_cell_has_exterior_witness((16, 32), [finite], [1])


def test_clearance_at_a_rational_squared_boundary_has_no_epsilon():
    upper = Fraction(1, 2)
    touching = Fraction(9, 2)  # (2*sqrt(1/2) + sqrt(1/2))².
    assert not exact.strictly_clear_of_other_axis(touching, upper)
    assert exact.strictly_clear_of_other_axis(touching + Fraction(1, 2**180), upper)
    assert not exact.strictly_clear_of_other_axis(touching - Fraction(1, 2**180), upper)


def test_original_constant_strip_has_two_positive_exact_sections_and_keeps_pixels():
    source = _strip()
    original = source.tobytes()
    sections = [_section(source, x) for x in (20, 44)]
    assert all(row["pass"] and row["constraint_eligible"] for row in sections)
    assert all(exact.decode_interval(row["half_width_squared_interval"]) == (
        Fraction(9, 4), Fraction(49, 4)) for row in sections)
    result = exact.intersect_sections(sections)
    assert result["pass"]
    assert result["independent_section_count"] == 2
    assert source.tobytes() == original


def test_remote_same_chain_section_can_make_strict_common_interval_exactly_empty():
    source = np.full((64, 64), 255, dtype=np.uint8)
    source[29:36, 8:32] = 0
    source[31:34, 32:57] = 0
    sections = [_section(source, x) for x in (20, 44)]
    assert all(row["pass"] for row in sections)
    result = exact.intersect_sections(sections)
    assert result["reason"] == "CONSTANT_WIDTH_MODEL_INAPPLICABLE"
    assert not result["pass"] and not result["exact_interval_nonempty"]
    assert exact.decode_interval(result["half_width_squared_interval"]) == (Fraction(25, 4),) * 2
    assert result["lower_bound_section_indices"] == [0]
    assert result["upper_bound_section_indices"] == [1]
    assert result["contributing_section_indices"] == [0, 1]


def test_independent_internal_empty_section_is_retained_even_when_pass_is_false():
    valid = {"pass": True, "constraint_eligible": True,
             "half_width_squared_interval": exact.encode_interval(1, 9)}
    incompatible = {"pass": False, "constraint_eligible": True,
                    "half_width_squared_interval": exact.encode_interval(4, 4)}
    contaminated = {"pass": False, "constraint_eligible": False,
                    "half_width_squared_interval": exact.encode_interval(10, 1)}
    result = exact.intersect_sections([valid, incompatible, contaminated])
    assert result["reason"] == "CONSTANT_WIDTH_MODEL_INAPPLICABLE"
    assert result["contributing_section_indices"] == [0, 1]
    assert exact.decode_interval(result["half_width_squared_interval"]) == (4, 4)


def test_source_junction_foreign_axis_and_boundary_exclusions_are_preserved():
    source = _strip()
    core = _section(source, 20, forbidden_core_cells=[(20, 32)])
    foreign = _section(source, 20, other_paths=[[(18, 24), (18, 40)]])
    remote = _section(source, 44, other_paths=[[(18, 24), (18, 40)]])
    assert not core["constraint_eligible"] and core["interfering_core_cells"] == [[20, 32]]
    assert not foreign["constraint_eligible"] and foreign["reason"].startswith("SECTION_NOT_INDEPENDENT")
    assert remote["constraint_eligible"]
    assert exact.intersect_sections([core, foreign, remote])["reason"] == "INSUFFICIENT_INDEPENDENT_WIDTH_SECTIONS"
    boundary_source = np.full((20, 20), 255, dtype=np.uint8)
    boundary_source[3:6, 2:18] = 0
    boundary = exact.measure_section(boundary_source, (10, 4), (2, 4), (17, 4))
    assert not boundary["constraint_eligible"]
    assert boundary["reason"] == "SECTION_REACHES_SOURCE_BOUNDARY"
