from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import math
from typing import Any

import ezdxf
import numpy as np
from scipy.spatial import cKDTree


Point = tuple[float, float]
PointKey = tuple[int, int]
LineKey = tuple[PointKey, PointKey]


@dataclass(frozen=True)
class DxfValidationResult:
    path: Path
    audit_error_count: int
    audit_fix_count: int
    line_count: int
    invalid_coordinate_count: int
    zero_length_count: int
    duplicate_line_count: int
    dangling_endpoint_count: int
    unique_endpoint_count: int
    connected_component_count: int
    open_component_count: int
    closed_component_count: int
    near_gap_count: int
    unsplit_intersection_count: int
    intersection_pair_checks: int
    intersection_check_limit_reached: bool
    tolerance: float
    gap_tolerance: float
    passed: bool
    audit_errors: tuple[str, ...] = ()
    audit_fixes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


def _quantize(value: float, tolerance: float) -> int:
    return int(round(value / tolerance))


def _point_key(point: Point, tolerance: float) -> PointKey:
    return _quantize(point[0], tolerance), _quantize(point[1], tolerance)


def _line_key(start: Point, end: Point, tolerance: float) -> LineKey:
    first = _point_key(start, tolerance)
    second = _point_key(end, tolerance)
    return (first, second) if first <= second else (second, first)


def _cross(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _has_unsplit_intersection(
    first: tuple[Point, Point, LineKey],
    second: tuple[Point, Point, LineKey],
    tolerance: float,
) -> bool:
    start_a, end_a, key_a = first
    start_b, end_b, key_b = second
    if set(key_a) & set(key_b):
        return False

    min_ax, max_ax = sorted((start_a[0], end_a[0]))
    min_ay, max_ay = sorted((start_a[1], end_a[1]))
    min_bx, max_bx = sorted((start_b[0], end_b[0]))
    min_by, max_by = sorted((start_b[1], end_b[1]))
    if (
        max_ax + tolerance < min_bx
        or max_bx + tolerance < min_ax
        or max_ay + tolerance < min_by
        or max_by + tolerance < min_ay
    ):
        return False

    point_a = np.asarray(start_a, dtype=float)
    vector_a = np.asarray(end_a, dtype=float) - point_a
    point_b = np.asarray(start_b, dtype=float)
    vector_b = np.asarray(end_b, dtype=float) - point_b
    denominator = _cross(vector_a, vector_b)
    scale = max(
        float(np.linalg.norm(vector_a)),
        float(np.linalg.norm(vector_b)),
        1.0,
    )
    if abs(denominator) <= tolerance * scale:
        return False

    offset = point_b - point_a
    t = _cross(offset, vector_b) / denominator
    u = _cross(offset, vector_a) / denominator
    parameter_tolerance = min(0.25, tolerance / scale)
    return (
        -parameter_tolerance <= t <= 1.0 + parameter_tolerance
        and -parameter_tolerance <= u <= 1.0 + parameter_tolerance
    )


def _component_counts(
    adjacency: dict[PointKey, set[PointKey]],
) -> tuple[int, int, int]:
    visited: set[PointKey] = set()
    component_count = 0
    open_count = 0
    closed_count = 0
    for start in adjacency:
        if start in visited:
            continue
        component_count += 1
        stack = [start]
        nodes: list[PointKey] = []
        visited.add(start)
        while stack:
            current = stack.pop()
            nodes.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        if nodes and all(len(adjacency[node]) == 2 for node in nodes):
            closed_count += 1
        else:
            open_count += 1
    return component_count, open_count, closed_count


def validate_dxf(
    path: str | Path,
    *,
    tolerance: float = 1e-6,
    gap_tolerance: float = 0.5,
    max_intersection_checks: int = 2_000_000,
) -> DxfValidationResult:
    """Validate DXF invariants and report topology diagnostics.

    Topology metrics are deliberately informational: open lines, crossings and
    near endpoints may be intentional axes or details. They are not treated as
    proof of invalid CAD without a fixture-specific acceptance policy.
    """
    if tolerance <= 0 or not math.isfinite(tolerance):
        raise ValueError("Validation tolerance must be a finite positive number")
    if gap_tolerance < tolerance or not math.isfinite(gap_tolerance):
        raise ValueError("Gap tolerance must be finite and not below tolerance")
    if max_intersection_checks < 0:
        raise ValueError("Maximum intersection checks cannot be negative")

    input_path = Path(path)
    document = ezdxf.readfile(input_path)
    auditor = document.audit()
    audit_errors = tuple(str(item) for item in auditor.errors)
    audit_fixes = tuple(str(item) for item in auditor.fixes)

    line_count = 0
    invalid_coordinate_count = 0
    zero_length_count = 0
    duplicate_line_count = 0
    line_keys: set[LineKey] = set()
    endpoint_degrees: dict[PointKey, int] = {}
    endpoint_positions: dict[PointKey, list[Point]] = {}
    adjacency: dict[PointKey, set[PointKey]] = {}
    valid_lines: list[tuple[Point, Point, LineKey]] = []

    for entity in document.modelspace().query("LINE"):
        line_count += 1
        start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
        end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
        coordinates = (*start, *end)
        if not all(math.isfinite(value) for value in coordinates):
            invalid_coordinate_count += 1
            continue

        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= tolerance:
            zero_length_count += 1
            continue

        key = _line_key(start, end, tolerance)
        if key in line_keys:
            duplicate_line_count += 1
            continue
        line_keys.add(key)
        valid_lines.append((start, end, key))

        start_key, end_key = key
        endpoint_degrees[start_key] = endpoint_degrees.get(start_key, 0) + 1
        endpoint_degrees[end_key] = endpoint_degrees.get(end_key, 0) + 1
        endpoint_positions.setdefault(_point_key(start, tolerance), []).append(start)
        endpoint_positions.setdefault(_point_key(end, tolerance), []).append(end)
        adjacency.setdefault(start_key, set()).add(end_key)
        adjacency.setdefault(end_key, set()).add(start_key)

    dangling_endpoint_count = sum(
        1 for degree in endpoint_degrees.values() if degree == 1
    )
    component_count, open_component_count, closed_component_count = (
        _component_counts(adjacency)
    )

    near_gap_count = 0
    if len(endpoint_positions) >= 2 and gap_tolerance > tolerance:
        endpoint_keys = list(endpoint_positions)
        points = np.asarray(
            [
                np.mean(np.asarray(endpoint_positions[key], dtype=float), axis=0)
                for key in endpoint_keys
            ],
            dtype=float,
        )
        tree = cKDTree(points)
        for left, right in tree.query_pairs(gap_tolerance):
            distance = float(np.linalg.norm(points[left] - points[right]))
            if distance > tolerance:
                near_gap_count += 1

    unsplit_intersection_count = 0
    intersection_pair_checks = 0
    intersection_check_limit_reached = False
    for left in range(len(valid_lines)):
        for right in range(left + 1, len(valid_lines)):
            if intersection_pair_checks >= max_intersection_checks:
                intersection_check_limit_reached = True
                break
            intersection_pair_checks += 1
            if _has_unsplit_intersection(
                valid_lines[left],
                valid_lines[right],
                tolerance,
            ):
                unsplit_intersection_count += 1
        if intersection_check_limit_reached:
            break

    passed = (
        len(audit_errors) == 0
        and len(audit_fixes) == 0
        and invalid_coordinate_count == 0
        and zero_length_count == 0
        and duplicate_line_count == 0
    )
    return DxfValidationResult(
        path=input_path,
        audit_error_count=len(audit_errors),
        audit_fix_count=len(audit_fixes),
        line_count=line_count,
        invalid_coordinate_count=invalid_coordinate_count,
        zero_length_count=zero_length_count,
        duplicate_line_count=duplicate_line_count,
        dangling_endpoint_count=dangling_endpoint_count,
        unique_endpoint_count=len(endpoint_degrees),
        connected_component_count=component_count,
        open_component_count=open_component_count,
        closed_component_count=closed_component_count,
        near_gap_count=near_gap_count,
        unsplit_intersection_count=unsplit_intersection_count,
        intersection_pair_checks=intersection_pair_checks,
        intersection_check_limit_reached=intersection_check_limit_reached,
        tolerance=tolerance,
        gap_tolerance=gap_tolerance,
        passed=passed,
        audit_errors=audit_errors,
        audit_fixes=audit_fixes,
    )
