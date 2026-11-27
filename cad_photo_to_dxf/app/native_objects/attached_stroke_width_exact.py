"""Exact finite geometry and strict width intervals for attached source strokes.

The frozen contract is ``docs/native/ISSUE62_EXACT_WIDTH_CONTRACT_20261127.md``.
All decisions use rational squared distances. Display-only floating values never
participate in a predicate. Source-chain membership and the finite component
solver belong to the caller; this module cannot certify provenance by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Integral


SCHEMA = "source-chain-exact-squared-width-v1"
HALF = Fraction(1, 2)
ZERO = Fraction(0)
ONE = Fraction(1)


def rational(value):
    """Return the exact supplied integer/binary64/rational value, without snap."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise ValueError("BOOLEAN_IS_NOT_A_GEOMETRIC_COORDINATE")
    if isinstance(value, Integral):
        return Fraction(int(value))
    # NumPy scalars are accepted without importing NumPy in this exact core.
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        raise ValueError("BOOLEAN_IS_NOT_A_GEOMETRIC_COORDINATE")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NONFINITE_GEOMETRIC_COORDINATE")
        return Fraction.from_float(value)
    raise ValueError("GEOMETRIC_COORDINATE_MUST_BE_INTEGER_BINARY64_OR_RATIONAL")


def encode_rational(value):
    """JSON-safe exact representation; strings avoid JSON integer precision loss."""
    value = rational(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def decode_rational(value):
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise ValueError("INVALID_EXACT_RATIONAL_RECORD")
    numerator, denominator = value["numerator"], value["denominator"]
    if not isinstance(numerator, str) or not isinstance(denominator, str):
        raise ValueError("EXACT_RATIONAL_COMPONENTS_MUST_BE_DECIMAL_STRINGS")
    try:
        n, d = int(numerator), int(denominator)
    except ValueError as error:
        raise ValueError("INVALID_EXACT_RATIONAL_RECORD") from error
    if str(n) != numerator or str(d) != denominator or d <= 0:
        raise ValueError("NONCANONICAL_EXACT_RATIONAL_RECORD")
    result = Fraction(n, d)
    if result.numerator != n or result.denominator != d:
        raise ValueError("UNREDUCED_EXACT_RATIONAL_RECORD")
    return result


def encode_interval(lower, upper):
    lower, upper = rational(lower), rational(upper)
    if lower < 0 or upper < 0:
        raise ValueError("NEGATIVE_SQUARED_WIDTH_BOUND")
    return {"lower": encode_rational(lower), "upper": encode_rational(upper),
            "lower_closed": True, "upper_closed": False}


def decode_interval(record):
    if record.get("lower_closed") is not True or record.get("upper_closed") is not False:
        raise ValueError("WIDTH_INTERVAL_MUST_BE_CLOSED_LOWER_OPEN_UPPER")
    lower, upper = decode_rational(record["lower"]), decode_rational(record["upper"])
    if lower < 0 or upper < 0:
        raise ValueError("NEGATIVE_SQUARED_WIDTH_BOUND")
    return lower, upper


def _point(value):
    if len(value) != 2:
        raise ValueError("POINT_MUST_HAVE_TWO_COORDINATES")
    return rational(value[0]), rational(value[1])


def _cell(value):
    point = _point(value)
    if any(v.denominator != 1 for v in point):
        raise ValueError("SOURCE_CELL_CENTER_MUST_BE_INTEGER")
    return int(point[0]), int(point[1])


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def squared_distance(a, b):
    delta = _sub(_point(a), _point(b))
    return _dot(delta, delta)


def _point_box_distance_squared(point, bounds):
    x, y = point
    xmin, ymin, xmax, ymax = bounds
    dx = max(xmin - x, ZERO, x - xmax)
    dy = max(ymin - y, ZERO, y - ymax)
    return dx * dx + dy * dy


def _box_box_distance_squared(first, second):
    dx = max(first[0] - second[2], ZERO, second[0] - first[2])
    dy = max(first[1] - second[3], ZERO, second[1] - first[3])
    return dx * dx + dy * dy


@dataclass(frozen=True)
class ExactSegment:
    a: tuple
    b: tuple
    delta: tuple
    length_squared: Fraction
    bounds: tuple


@dataclass(frozen=True)
class ExactPolyline:
    points: tuple
    segments: tuple
    bounds: tuple


def _segment(a, b):
    a, b = _point(a), _point(b)
    delta = _sub(b, a)
    length_squared = _dot(delta, delta)
    if length_squared == 0:
        raise ValueError("ZERO_LENGTH_NATIVE_SEGMENT")
    bounds = (min(a[0], b[0]), min(a[1], b[1]),
              max(a[0], b[0]), max(a[1], b[1]))
    return ExactSegment(a, b, delta, length_squared, bounds)


def prepare_polyline(points):
    """Prepare immutable rational segments once for many exact distance queries."""
    if isinstance(points, ExactPolyline):
        return points
    points = tuple(_point(p) for p in points)
    if len(points) < 2:
        raise ValueError("FINITE_POLYLINE_REQUIRES_TWO_POINTS")
    segments = tuple(_segment(a, b) for a, b in zip(points, points[1:]))
    bounds = (min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points))
    return ExactPolyline(points, segments, bounds)


def _project(point, segment):
    offset = _sub(point, segment.a)
    fraction = min(ONE, max(ZERO, _dot(offset, segment.delta) / segment.length_squared))
    nearest = (segment.a[0] + fraction * segment.delta[0],
               segment.a[1] + fraction * segment.delta[1])
    difference = _sub(point, nearest)
    return _dot(difference, difference), fraction, nearest


def project_point_segment(point, a, b):
    """Return ``(distance_squared, clamped_fraction, exact_nearest_point)``."""
    return _project(_point(point), _segment(a, b))


def project_point_polyline(point, points):
    """Return ``(distance_squared, segment_index, fraction, exact_point)``.

    Exact equal-distance ties retain the first segment in the actual polyline.
    The caller must reject a non-interior or otherwise ambiguous width section.
    """
    point, path = _point(point), prepare_polyline(points)
    best = None
    for index, segment in enumerate(path.segments):
        if best is not None and _point_box_distance_squared(point, segment.bounds) >= best[0]:
            continue
        distance, fraction, nearest = _project(point, segment)
        if best is None or distance < best[0]:
            best = distance, index, fraction, nearest
        if distance == 0:
            break
    return best


def point_segment_distance_squared(point, a, b):
    return project_point_segment(point, a, b)[0]


def point_polyline_distance_squared(point, points):
    return project_point_polyline(point, points)[0]


def _segment_intersects_box(segment, bounds):
    enter, leave = ZERO, ONE
    for axis in range(2):
        if segment.delta[axis] == 0:
            if not bounds[axis] <= segment.a[axis] <= bounds[axis + 2]:
                return False
        else:
            first = (bounds[axis] - segment.a[axis]) / segment.delta[axis]
            last = (bounds[axis + 2] - segment.a[axis]) / segment.delta[axis]
            enter, leave = max(enter, min(first, last)), min(leave, max(first, last))
            if enter > leave:
                return False
    return enter <= leave


def _cell_bounds(cell):
    return cell[0] - HALF, cell[1] - HALF, cell[0] + HALF, cell[1] + HALF


def _cell_segment_distance_squared(bounds, segment):
    if segment.delta[0] == 0 or segment.delta[1] == 0:
        # Axis-aligned segments are degenerate rectangles, so this is exact.
        return _box_box_distance_squared(bounds, segment.bounds)
    if _segment_intersects_box(segment, bounds):
        return ZERO
    best = min(_point_box_distance_squared(segment.a, bounds),
               _point_box_distance_squared(segment.b, bounds))
    for x in (bounds[0], bounds[2]):
        for y in (bounds[1], bounds[3]):
            best = min(best, _project((x, y), segment)[0])
    return best


def cell_segment_distance_squared(cell, a, b):
    """Minimum squared distance between a closed unit cell and finite segment."""
    return _cell_segment_distance_squared(_cell_bounds(_cell(cell)), _segment(a, b))


def cell_polyline_distance_squared(cell, points):
    """Exact minimum distance to the complete finite polyline, with AABB pruning."""
    bounds, path = _cell_bounds(_cell(cell)), prepare_polyline(points)
    best = None
    for segment in path.segments:
        if best is not None and _box_box_distance_squared(bounds, segment.bounds) >= best:
            continue
        distance = _cell_segment_distance_squared(bounds, segment)
        if best is None or distance < best:
            best = distance
        if best == 0:
            break
    return best


def segment_cells(a, b):
    """Enumerate every closed unit cell touched by an actual finite segment.

    Exact rational crossings of half-integer grid lines partition the segment.
    Cells at every crossing and every open-interval midpoint give its complete
    supercover, including corner-only touches and grid-boundary-aligned runs.
    The work scales with traversed grid lines, not a diagonal segment's box area.
    """
    segment = _segment(a, b)
    events = {ZERO, ONE}
    for axis in range(2):
        if segment.delta[axis] == 0:
            continue
        first, last = sorted((segment.a[axis], segment.b[axis]))
        for integer in range(math.ceil(first - HALF), math.floor(last - HALF) + 1):
            events.add((integer + HALF - segment.a[axis]) / segment.delta[axis])
    events = sorted(events)
    samples = events + [(first + last) * HALF for first, last in zip(events, events[1:])]
    cells = set()
    for fraction in samples:
        point = (segment.a[0] + fraction * segment.delta[0],
                 segment.a[1] + fraction * segment.delta[1])
        for x in range(math.ceil(point[0] - HALF), math.floor(point[0] + HALF) + 1):
            for y in range(math.ceil(point[1] - HALF), math.floor(point[1] + HALF) + 1):
                cells.add((x, y))
    return sorted(cells)


def cell_is_covered(cell, points, radius_squared):
    radius_squared = rational(radius_squared)
    if radius_squared < 0:
        raise ValueError("NEGATIVE_SQUARED_RADIUS")
    bounds, path = _cell_bounds(_cell(cell)), prepare_polyline(points)
    for segment in path.segments:
        if _box_box_distance_squared(bounds, segment.bounds) > radius_squared:
            continue
        if _cell_segment_distance_squared(bounds, segment) <= radius_squared:
            return True
    return False


def point_is_strictly_outside(point, points, radius_squared):
    """Exact outside predicate with radius-specific finite-segment box pruning."""
    radius_squared = rational(radius_squared)
    if radius_squared < 0:
        raise ValueError("NEGATIVE_SQUARED_RADIUS")
    point, path = _point(point), prepare_polyline(points)
    if _point_box_distance_squared(point, path.bounds) > radius_squared:
        return True
    for segment in path.segments:
        lower = _point_box_distance_squared(point, segment.bounds)
        if lower > radius_squared:
            continue
        if segment.delta[0] == 0 or segment.delta[1] == 0:
            return False  # Here the box lower bound is the exact distance.
        if _project(point, segment)[0] <= radius_squared:
            return False
    return True


def white_cell_exterior_witness(cell, paths, radii_squared):
    """Return a common strictly exterior nine-point witness, or ``None``.

    A separate exterior point for each path does not establish a white witness
    for their union. The center is tried first as a cheap, exact sufficient test.
    """
    x, y = _cell(cell)
    paths = tuple(prepare_polyline(path) for path in paths)
    radii = tuple(rational(radius) for radius in radii_squared)
    if len(paths) != len(radii) or not paths or any(radius < 0 for radius in radii):
        raise ValueError("WHITE_WITNESS_REQUIRES_MATCHED_NONNEGATIVE_FINITE_MODELS")
    offsets = ((ZERO, ZERO),) + tuple((dx, dy) for dy in (-HALF, ZERO, HALF)
                                    for dx in (-HALF, ZERO, HALF) if dx or dy)
    for dx, dy in offsets:
        point = (x + dx, y + dy)
        if all(point_is_strictly_outside(point, path, radius)
               for path, radius in zip(paths, radii)):
            return point
    return None


def white_cell_has_exterior_witness(cell, paths, radii_squared):
    return white_cell_exterior_witness(cell, paths, radii_squared) is not None


def _normal_data(q, a, b):
    q, segment = _point(q), _segment(a, b)
    normal = (-segment.delta[1], segment.delta[0])
    if _dot(normal, _sub(q, segment.a)) != 0:
        raise ValueError("SECTION_CENTER_MUST_BE_EXACTLY_ON_NATIVE_AXIS")
    fraction = _dot(_sub(q, segment.a), segment.delta) / segment.length_squared
    return q, segment, normal, fraction


def normal_section_cells(q, a, b, half_span=12):
    """Closed cells intersecting an exact finite normal segment of fixed length.

    The irrational normal endpoints are never rounded: rational clipping gives
    the allowed line parameter, then ``t²*|b-a|² <= half_span²`` decides overlap.
    The center must be exactly on the supplied native axis.
    """
    q, segment, normal, _ = _normal_data(q, a, b)
    half_span = rational(half_span)
    if half_span < 0:
        raise ValueError("NEGATIVE_SECTION_HALF_SPAN")
    half_span_squared = half_span * half_span
    cells = []
    for x in range(math.ceil(q[0] - half_span - HALF), math.floor(q[0] + half_span + HALF) + 1):
        for y in range(math.ceil(q[1] - half_span - HALF), math.floor(q[1] + half_span + HALF) + 1):
            bounds = _cell_bounds((x, y))
            enter, leave = None, None
            for axis in range(2):
                if normal[axis] == 0:
                    if not bounds[axis] <= q[axis] <= bounds[axis + 2]:
                        break
                else:
                    first = (bounds[axis] - q[axis]) / normal[axis]
                    last = (bounds[axis + 2] - q[axis]) / normal[axis]
                    low, high = min(first, last), max(first, last)
                    enter = low if enter is None else max(enter, low)
                    leave = high if leave is None else min(leave, high)
                    if enter > leave:
                        break
            else:
                nearest_t = ZERO if enter <= 0 <= leave else min(abs(enter), abs(leave))
                if nearest_t * nearest_t * segment.length_squared <= half_span_squared:
                    cells.append((x, y))
    return cells


def section_width_bounds(q, a, b, black_cells, first_white_cells):
    """Return exact ``(lower_radius_squared, strict_upper_radius_squared)``.

    This low-level function computes the supplied constraints. It does not prove
    that the supplied cells belong to an independent source section.
    """
    q, segment, normal, _ = _normal_data(q, a, b)
    black = tuple(_cell(cell) for cell in black_cells)
    white = tuple(_cell(cell) for cell in first_white_cells)
    if not black or len(white) != 2:
        raise ValueError("SECTION_REQUIRES_BLACK_CELLS_AND_TWO_WHITE_SIDE_CELLS")
    positions = tuple(_dot(normal, _sub(cell, q)) for cell in white)
    if positions[0] * positions[1] >= 0:
        raise ValueError("SECTION_WHITE_CELLS_MUST_LIE_ON_OPPOSITE_NORMAL_SIDES")
    half_projection = (abs(normal[0]) + abs(normal[1])) * HALF
    lower = max(ZERO, max(abs(_dot(normal, _sub(cell, q))) - half_projection for cell in black))
    upper = min(abs(position) + half_projection for position in positions)
    return lower * lower / segment.length_squared, upper * upper / segment.length_squared


def strictly_clear_of_other_axis(distance_squared, upper_radius_squared, multiplier=2):
    """Exact ``distance > multiplier*upper_radius + sqrt(1/2)`` test."""
    distance_squared, upper_radius_squared = rational(distance_squared), rational(upper_radius_squared)
    multiplier = rational(multiplier)
    if min(distance_squared, upper_radius_squared, multiplier) < 0:
        raise ValueError("NEGATIVE_CLEARANCE_ARGUMENT")
    squared_multiplier = multiplier * multiplier
    difference = distance_squared - squared_multiplier * upper_radius_squared - HALF
    return difference > 0 and difference * difference > 2 * squared_multiplier * upper_radius_squared


def _radius_approx(value):
    try:
        return math.sqrt(float(value))
    except OverflowError:
        return None


def measure_section(source, q, a, b, other_paths=(), forbidden_core_cells=(),
                    source_threshold=128, half_span=12):
    """Measure and retain one exact original-source normal section.

    ``constraint_eligible`` is independent of interval nonemptiness. In particular
    an independent empty section stays eligible and must reject the constant
    width model; callers must not select only rows whose ``pass`` is true.
    Source-chain/observation uniqueness is the caller's responsibility.
    """
    q, segment, normal, fraction = _normal_data(q, a, b)
    half_span = rational(half_span)
    row = {"schema": SCHEMA, "center_exact": [encode_rational(v) for v in q],
           "center_px_approx": [float(v) for v in q],
           "actual_native_segment_exact": [[encode_rational(v) for v in p]
                                             for p in (segment.a, segment.b)],
           "normal_exact": [encode_rational(v) for v in normal],
           "normal_squared_length": encode_rational(segment.length_squared),
           "native_segment_fraction": encode_rational(fraction),
           "pass": False, "independent": False, "constraint_eligible": False,
           "upper_bound_is_strict": True, "original_source_pixels_modified": False}
    if not 0 < fraction < 1:
        row["reason"] = "NO_FINITE_INDEPENDENT_ARM_SECTION"
        return row
    cells = normal_section_cells(q, a, b, half_span)
    row["section_source_cells"] = [list(cell) for cell in cells]
    height, width = source.shape[:2]
    inside = [0 <= x < width and 0 <= y < height for x, y in cells]
    values = [int(source[y, x]) if good else None for (x, y), good in zip(cells, inside)]
    row["original_values"] = values
    row["section_ink"] = [int(value is not None and value < source_threshold) for value in values]
    if not all(inside):
        row["reason"] = "SECTION_REACHES_SOURCE_BOUNDARY"
        return row
    black = {cell for cell, value in zip(cells, values) if value < source_threshold}
    seeds = {cell for cell in black if abs(cell[0] - q[0]) <= HALF and abs(cell[1] - q[1]) <= HALF}
    own, queue = set(seeds), sorted(seeds)
    while queue:
        x, y = queue.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = x + dx, y + dy
                if cell in black and cell not in own:
                    own.add(cell)
                    queue.append(cell)
    if not own:
        row["reason"] = "SECTION_NATIVE_AXIS_HAS_NO_ORIGINAL_INK"
        return row
    whites = [cell for cell in cells if cell not in black]
    positions = {cell: _dot(normal, _sub(cell, q)) for cell in whites}
    first_white = []
    for sign in (-1, 1):
        candidates = [cell for cell in whites if positions[cell] * sign > 0]
        if not candidates:
            row["reason"] = "SECTION_HAS_NO_WHITE_ON_BOTH_SIDES"
            return row
        first_white.append(min(candidates, key=lambda cell: (positions[cell] * sign, cell)))
    lower, upper = section_width_bounds(q, a, b, own, first_white)
    others = [prepare_polyline(points) for points in other_paths]
    nearest_other = min((point_polyline_distance_squared(q, path) for path in others), default=None)
    cores = set(_cell(cell) for cell in forbidden_core_cells)
    core_cells = sorted(set(cells) & cores)
    row.update(independent_black_cells=[list(cell) for cell in sorted(own)],
               first_white_cells=[list(cell) for cell in first_white],
               half_width_squared_interval=encode_interval(lower, upper),
               half_width_interval_px_approx=[_radius_approx(lower), _radius_approx(upper)],
               nearest_other_axis_distance_squared=(None if nearest_other is None
                                                    else encode_rational(nearest_other)),
               interfering_core_cells=[list(cell) for cell in core_cells])
    if upper >= half_span * half_span:
        row["reason"] = "SECTION_WIDTH_OBSERVATION_TRUNCATED"
    elif core_cells or (nearest_other is not None and not strictly_clear_of_other_axis(nearest_other, upper)):
        row["reason"] = "SECTION_NOT_INDEPENDENT_OF_JUNCTION_OR_OTHER_STROKE"
    else:
        row.update(independent=True, constraint_eligible=True)
        if lower >= upper:
            row["reason"] = "SECTION_CONSTANT_WIDTH_INTERVAL_EMPTY"
        else:
            row.update({"pass": True, "reason": "INDEPENDENT_ORIGINAL_ARM_SECTION"})
    return row


def intersect_sections(records, min_sections=2):
    """Intersect every eligible section, including eligible incompatible ones."""
    if isinstance(min_sections, bool) or not isinstance(min_sections, Integral) or min_sections < 1:
        raise ValueError("INVALID_MINIMUM_INDEPENDENT_SECTION_COUNT")
    eligible = [(index, row) for index, row in enumerate(records)
                if row.get("constraint_eligible", row.get("independent", row.get("pass", False)))]
    result = {"schema": SCHEMA, "pass": False, "independent_section_count": len(eligible),
              "contributing_section_indices": [index for index, _ in eligible],
              "half_width_squared_interval": None, "upper_bound_is_strict": True,
              "endpoint_patch_not_used_to_raise_width": True}
    if not eligible:
        result["reason"] = "INSUFFICIENT_INDEPENDENT_WIDTH_SECTIONS"
        return result
    intervals = [(index, *decode_interval(row["half_width_squared_interval"])) for index, row in eligible]
    lower, upper = max(row[1] for row in intervals), min(row[2] for row in intervals)
    result.update(half_width_squared_interval=encode_interval(lower, upper),
                  half_width_interval_px_approx=[_radius_approx(lower), _radius_approx(upper)],
                  lower_bound_section_indices=[index for index, lo, _ in intervals if lo == lower],
                  upper_bound_section_indices=[index for index, _, hi in intervals if hi == upper],
                  exact_interval_nonempty=lower < upper)
    if lower >= upper:
        result["reason"] = "CONSTANT_WIDTH_MODEL_INAPPLICABLE"
    elif len(eligible) < min_sections:
        result["reason"] = "INSUFFICIENT_INDEPENDENT_WIDTH_SECTIONS"
    else:
        result.update({"pass": True, "reason": "COMPLETE_SOURCE_CHAIN_CONSTANT_WIDTH_ESTABLISHED"})
    return result
