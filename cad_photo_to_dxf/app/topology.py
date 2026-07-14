from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

import numpy as np
from scipy.spatial import cKDTree

from .cancellation import CancellationToken, checkpoint
from .line_detect import LineSegment


@dataclass
class IntersectionSplitReport:
    input_lines: int = 0
    output_lines: int = 0
    intersections_found: int = 0
    lines_split: int = 0
    pair_checks: int = 0
    pair_limit_reached: bool = False


@dataclass
class TopologyValidationReport:
    line_count: int = 0
    nonfinite_lines: int = 0
    zero_length_lines: int = 0
    exact_duplicate_lines: int = 0
    near_duplicate_pairs: int = 0
    endpoint_nodes: int = 0
    dangling_endpoints: int = 0
    junction_nodes: int = 0
    small_gap_pairs: int = 0
    unresolved_interior_intersections: int = 0
    connected_components: int = 0
    closed_components: int = 0
    open_components: int = 0


@dataclass
class TopologyResult:
    lines: list[LineSegment]
    split_report: IntersectionSplitReport
    validation_report: TopologyValidationReport


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _angle_difference(left: LineSegment, right: LineSegment) -> float:
    delta = abs(left.angle - right.angle) % 180.0
    return min(delta, 180.0 - delta)


def _intersection_parameters(
    a: LineSegment,
    b: LineSegment,
    tolerance: float,
) -> tuple[float, float, np.ndarray] | None:
    p = a.p1
    r = a.p2 - a.p1
    q = b.p1
    s = b.p2 - b.p1
    denominator = _cross(r, s)
    scale = max(float(np.linalg.norm(r)), float(np.linalg.norm(s)), 1.0)
    if abs(denominator) <= max(1e-9, tolerance * scale * 1e-4):
        return None
    qmp = q - p
    t = _cross(qmp, s) / denominator
    u = _cross(qmp, r) / denominator
    parameter_tolerance = tolerance / max(float(np.linalg.norm(r)), 1.0)
    parameter_u_tolerance = tolerance / max(float(np.linalg.norm(s)), 1.0)
    if not (-parameter_tolerance <= t <= 1.0 + parameter_tolerance):
        return None
    if not (-parameter_u_tolerance <= u <= 1.0 + parameter_u_tolerance):
        return None
    return float(t), float(u), p + t * r


def _candidate_pairs(lines: list[LineSegment], tolerance: float) -> list[tuple[int, int]]:
    if len(lines) < 2:
        return []
    lengths = [line.length for line in lines if line.length > 1e-9]
    median_length = float(np.median(lengths)) if lengths else 64.0
    cell_size = max(32.0, min(512.0, median_length))
    buckets: dict[tuple[int, int], list[int]] = {}
    large: list[int] = []
    for index, line in enumerate(lines):
        min_x = min(line.x1, line.x2) - tolerance
        max_x = max(line.x1, line.x2) + tolerance
        min_y = min(line.y1, line.y2) - tolerance
        max_y = max(line.y1, line.y2) + tolerance
        x0 = math.floor(min_x / cell_size)
        x1 = math.floor(max_x / cell_size)
        y0 = math.floor(min_y / cell_size)
        y1 = math.floor(max_y / cell_size)
        cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if cell_count > 2048:
            large.append(index)
            continue
        for cell_x in range(x0, x1 + 1):
            for cell_y in range(y0, y1 + 1):
                buckets.setdefault((cell_x, cell_y), []).append(index)

    pairs: set[tuple[int, int]] = set()
    for indexes in buckets.values():
        unique = sorted(set(indexes))
        for position, left in enumerate(unique):
            for right in unique[position + 1 :]:
                pairs.add((left, right))
    for index in large:
        for other in range(len(lines)):
            if index != other:
                pairs.add((min(index, other), max(index, other)))
    return sorted(pairs)


def split_lines_at_intersections(
    lines: list[LineSegment],
    *,
    tolerance: float = 0.75,
    max_pair_checks: int = 1_000_000,
    cancellation_token: CancellationToken | None = None,
) -> tuple[list[LineSegment], IntersectionSplitReport]:
    report = IntersectionSplitReport(input_lines=len(lines))
    if not lines:
        return [], report
    split_parameters: list[list[float]] = [[0.0, 1.0] for _ in lines]
    pairs = _candidate_pairs(lines, tolerance)
    for pair_number, (left_index, right_index) in enumerate(pairs, start=1):
        if pair_number % 512 == 0:
            checkpoint(cancellation_token)
        report.pair_checks += 1
        if report.pair_checks > max_pair_checks:
            report.pair_limit_reached = True
            break
        left = lines[left_index]
        right = lines[right_index]
        result = _intersection_parameters(left, right, tolerance)
        if result is None:
            continue
        t, u, _point = result
        left_epsilon = tolerance / max(left.length, 1.0)
        right_epsilon = tolerance / max(right.length, 1.0)
        left_interior = left_epsilon < t < 1.0 - left_epsilon
        right_interior = right_epsilon < u < 1.0 - right_epsilon
        if not left_interior and not right_interior:
            continue
        report.intersections_found += 1
        if left_interior:
            split_parameters[left_index].append(min(1.0, max(0.0, t)))
        if right_interior:
            split_parameters[right_index].append(min(1.0, max(0.0, u)))

    output: list[LineSegment] = []
    for index, line in enumerate(lines):
        checkpoint(cancellation_token)
        parameters = sorted(split_parameters[index])
        unique: list[float] = []
        parameter_epsilon = tolerance / max(line.length, 1.0)
        for value in parameters:
            if not unique or abs(value - unique[-1]) > parameter_epsilon:
                unique.append(value)
        if len(unique) > 2:
            report.lines_split += 1
        vector = line.p2 - line.p1
        for start_t, end_t in zip(unique, unique[1:]):
            start = line.p1 + vector * start_t
            end = line.p1 + vector * end_t
            if float(np.linalg.norm(end - start)) <= tolerance:
                continue
            history = line.history
            if len(unique) > 2:
                history = tuple(dict.fromkeys(history + ("split_at_intersection",)))
            output.append(
                line.copy(
                    x1=float(start[0]),
                    y1=float(start[1]),
                    x2=float(end[0]),
                    y2=float(end[1]),
                    history=history,
                )
            )
    report.output_lines = len(output)
    return output, report


def _union_find(
    size: int,
) -> tuple[
    np.ndarray,
    Callable[[int], int],
    Callable[[int, int], None],
]:
    parent = np.arange(size)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    return parent, find, union


def validate_topology(
    lines: list[LineSegment],
    *,
    endpoint_tolerance: float = 0.5,
    gap_tolerance: float = 6.0,
    intersection_tolerance: float = 0.75,
    cancellation_token: CancellationToken | None = None,
) -> TopologyValidationReport:
    report = TopologyValidationReport(line_count=len(lines))
    if not lines:
        return report

    valid: list[LineSegment] = []
    exact_keys: dict[tuple[int, int, int, int], int] = {}
    exact_quantization = 1e-6
    for line in lines:
        coordinates = np.array([line.x1, line.y1, line.x2, line.y2], dtype=float)
        if not np.isfinite(coordinates).all():
            report.nonfinite_lines += 1
            continue
        if line.length <= 1e-9:
            report.zero_length_lines += 1
            continue
        first = (line.x1, line.y1)
        second = (line.x2, line.y2)
        start, end = sorted((first, second))
        key = tuple(
            int(round(value / exact_quantization)) for value in (*start, *end)
        )
        exact_keys[key] = exact_keys.get(key, 0) + 1
        valid.append(line)
    report.exact_duplicate_lines = sum(
        count - 1 for count in exact_keys.values() if count > 1
    )
    if not valid:
        return report

    points = np.array(
        [[line.x1, line.y1] for line in valid]
        + [[line.x2, line.y2] for line in valid],
        dtype=float,
    )
    line_count = len(valid)
    _parent, find, union = _union_find(len(points))
    tree = cKDTree(points)
    for pair_number, (left, right) in enumerate(tree.query_pairs(endpoint_tolerance)):
        if pair_number % 512 == 0:
            checkpoint(cancellation_token)
        if left % line_count == right % line_count:
            continue
        union(int(left), int(right))

    node_members: dict[int, list[int]] = {}
    for index in range(len(points)):
        node_members.setdefault(find(index), []).append(index)
    node_centers = {
        root: points[indexes].mean(axis=0) for root, indexes in node_members.items()
    }
    node_line_indexes = {
        root: {index % line_count for index in indexes}
        for root, indexes in node_members.items()
    }
    degree: dict[int, int] = {root: 0 for root in node_members}
    _graph_parent, graph_find, graph_union = _union_find(len(node_members))
    roots = list(node_members)
    root_position = {root: position for position, root in enumerate(roots)}
    for index in range(line_count):
        start_root = find(index)
        end_root = find(index + line_count)
        degree[start_root] += 1
        degree[end_root] += 1
        graph_union(root_position[start_root], root_position[end_root])

    report.endpoint_nodes = len(node_members)
    dangling_roots = [root for root, value in degree.items() if value == 1]
    report.dangling_endpoints = len(dangling_roots)
    report.junction_nodes = sum(1 for value in degree.values() if value > 2)

    components: dict[int, list[int]] = {}
    for position, root in enumerate(roots):
        components.setdefault(graph_find(position), []).append(root)
    report.connected_components = len(components)
    for component_roots in components.values():
        edge_degree_sum = sum(degree[root] for root in component_roots)
        edge_count = edge_degree_sum // 2
        if edge_count >= 3 and all(degree[root] == 2 for root in component_roots):
            report.closed_components += 1
        else:
            report.open_components += 1

    if len(dangling_roots) > 1 and gap_tolerance > endpoint_tolerance:
        dangling_points = np.array([node_centers[root] for root in dangling_roots])
        dangling_tree = cKDTree(dangling_points)
        for left_index, right_index in dangling_tree.query_pairs(gap_tolerance):
            left_root = dangling_roots[left_index]
            right_root = dangling_roots[right_index]
            if node_line_indexes[left_root] & node_line_indexes[right_root]:
                # The two endpoints belong to the same short open line; that is
                # an intentional segment, not a missing connection between lines.
                continue
            distance = float(
                np.linalg.norm(dangling_points[left_index] - dangling_points[right_index])
            )
            if distance > endpoint_tolerance:
                report.small_gap_pairs += 1

    pair_tolerance = max(intersection_tolerance, endpoint_tolerance * 2.0)
    pairs = _candidate_pairs(valid, pair_tolerance)
    for pair_number, (left_index, right_index) in enumerate(pairs):
        if pair_number % 512 == 0:
            checkpoint(cancellation_token)
        left = valid[left_index]
        right = valid[right_index]

        direct = float(
            np.linalg.norm(left.p1 - right.p1)
            + np.linalg.norm(left.p2 - right.p2)
        )
        reverse = float(
            np.linalg.norm(left.p1 - right.p2)
            + np.linalg.norm(left.p2 - right.p1)
        )
        endpoint_error = min(direct, reverse)
        same_direction = _angle_difference(left, right) <= 2.0
        similar_length = abs(left.length - right.length) <= endpoint_tolerance * 2.0
        if (
            exact_quantization * 4.0 < endpoint_error <= endpoint_tolerance * 4.0
            and same_direction
            and similar_length
        ):
            report.near_duplicate_pairs += 1

        result = _intersection_parameters(left, right, intersection_tolerance)
        if result is None:
            continue
        t, u, _point = result
        left_eps = intersection_tolerance / max(left.length, 1.0)
        right_eps = intersection_tolerance / max(right.length, 1.0)
        if left_eps < t < 1.0 - left_eps or right_eps < u < 1.0 - right_eps:
            report.unresolved_interior_intersections += 1

    return report


def build_topology(
    lines: list[LineSegment],
    *,
    intersection_tolerance: float = 0.75,
    endpoint_tolerance: float = 0.5,
    gap_tolerance: float = 6.0,
    max_pair_checks: int = 1_000_000,
    cancellation_token: CancellationToken | None = None,
) -> TopologyResult:
    split_lines, split_report = split_lines_at_intersections(
        lines,
        tolerance=intersection_tolerance,
        max_pair_checks=max_pair_checks,
        cancellation_token=cancellation_token,
    )
    validation = validate_topology(
        split_lines,
        endpoint_tolerance=endpoint_tolerance,
        gap_tolerance=gap_tolerance,
        intersection_tolerance=intersection_tolerance,
        cancellation_token=cancellation_token,
    )
    return TopologyResult(split_lines, split_report, validation)
