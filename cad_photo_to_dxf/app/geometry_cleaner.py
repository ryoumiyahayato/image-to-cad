from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.spatial import cKDTree

from .line_detect import LineSegment


@dataclass
class GeometryCleanParams:
    snap_distance: float = 6.0
    max_bridge_gap: float = 12.0
    angle_tolerance: float = 3.0
    collinear_distance: float = 3.0
    duplicate_distance: float = 3.0
    min_line_length: float = 12.0
    max_pair_checks: int = 2_000_000


def _angle_difference(a: float, b: float) -> float:
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def orthogonalize(line: LineSegment, tolerance: float) -> LineSegment:
    angle = line.angle
    if min(angle, 180.0 - angle) <= tolerance:
        y = (line.y1 + line.y2) / 2.0
        return line.copy(y1=y, y2=y)
    if abs(angle - 90.0) <= tolerance:
        x = (line.x1 + line.x2) / 2.0
        return line.copy(x1=x, x2=x)
    return line


def snap_endpoints(lines: list[LineSegment], distance: float) -> list[LineSegment]:
    if not lines or distance <= 0:
        return lines
    points = np.array(
        [[line.x1, line.y1] for line in lines] + [[line.x2, line.y2] for line in lines],
        dtype=float,
    )
    tree = cKDTree(points)
    parent = np.arange(len(points))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in tree.query_pairs(distance):
        union(int(a), int(b))

    groups: dict[int, list[int]] = {}
    for index in range(len(points)):
        groups.setdefault(find(index), []).append(index)
    centers = {root: points[indexes].mean(axis=0) for root, indexes in groups.items()}
    snapped = np.array([centers[find(index)] for index in range(len(points))])

    count = len(lines)
    return [
        line.copy(
            x1=float(snapped[index, 0]),
            y1=float(snapped[index, 1]),
            x2=float(snapped[index + count, 0]),
            y2=float(snapped[index + count, 1]),
        )
        for index, line in enumerate(lines)
    ]


def _line_basis(line: LineSegment) -> tuple[np.ndarray, np.ndarray]:
    vector = line.p2 - line.p1
    norm = np.linalg.norm(vector)
    if norm == 0:
        return np.array([1.0, 0.0]), np.array([0.0, 1.0])
    direction = vector / norm
    normal = np.array([-direction[1], direction[0]])
    return direction, normal


def _can_merge(a: LineSegment, b: LineSegment, params: GeometryCleanParams) -> bool:
    if _angle_difference(a.angle, b.angle) > params.angle_tolerance:
        return False
    direction, normal = _line_basis(a)
    offset = abs(float(np.dot(b.midpoint - a.midpoint, normal)))
    if offset > params.collinear_distance:
        return False

    origin = a.p1
    a_values = sorted([float(np.dot(a.p1 - origin, direction)), float(np.dot(a.p2 - origin, direction))])
    b_values = sorted([float(np.dot(b.p1 - origin, direction)), float(np.dot(b.p2 - origin, direction))])
    gap = max(a_values[0], b_values[0]) - min(a_values[1], b_values[1])
    return gap <= params.max_bridge_gap


def _merge_pair(a: LineSegment, b: LineSegment) -> LineSegment:
    direction, normal = _line_basis(a if a.length >= b.length else b)
    points = np.array([a.p1, a.p2, b.p1, b.p2])
    normal_coordinate = float(np.mean(points @ normal))
    projections = points @ direction
    start = direction * float(np.min(projections)) + normal * normal_coordinate
    end = direction * float(np.max(projections)) + normal * normal_coordinate
    return LineSegment(
        float(start[0]),
        float(start[1]),
        float(end[0]),
        float(end[1]),
        width=max(a.width, b.width),
        confidence=max(a.confidence, b.confidence),
        layer=a.layer,
    )


def merge_collinear(lines: list[LineSegment], params: GeometryCleanParams) -> list[LineSegment]:
    """Greedily merge overlapping or narrowly separated collinear segments."""
    work = sorted(lines, key=lambda line: line.length, reverse=True)
    changed = True
    pair_checks = 0
    while changed:
        changed = False
        result: list[LineSegment] = []
        consumed = [False] * len(work)
        for i, current in enumerate(work):
            if consumed[i]:
                continue
            merged = current
            for j in range(i + 1, len(work)):
                if consumed[j]:
                    continue
                pair_checks += 1
                if pair_checks > params.max_pair_checks:
                    result.extend(work[k] for k in range(i, len(work)) if not consumed[k])
                    return result
                candidate = work[j]
                # Midpoint proximity prefilter limits unnecessary geometric checks.
                max_distance = merged.length + candidate.length + params.max_bridge_gap
                if np.linalg.norm(candidate.midpoint - merged.midpoint) > max_distance:
                    continue
                if _can_merge(merged, candidate, params):
                    merged = _merge_pair(merged, candidate)
                    consumed[j] = True
                    changed = True
            result.append(merged)
        work = sorted(result, key=lambda line: line.length, reverse=True)
    return work


def remove_duplicates(lines: list[LineSegment], params: GeometryCleanParams) -> list[LineSegment]:
    # Duplicate candidates have almost identical endpoints, so their midpoints also
    # fall in the same small spatial bucket. This avoids an O(n²) full comparison.
    kept: list[LineSegment] = []
    cell_size = max(1.0, params.duplicate_distance * 3.0)
    buckets: dict[tuple[int, int], list[int]] = {}

    for line in sorted(lines, key=lambda item: (item.length, item.width), reverse=True):
        midpoint = line.midpoint
        cell = (int(math.floor(midpoint[0] / cell_size)), int(math.floor(midpoint[1] / cell_size)))
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(buckets.get((cell[0] + dx, cell[1] + dy), []))

        duplicate = False
        for index in candidates:
            existing = kept[index]
            if _angle_difference(line.angle, existing.angle) > params.angle_tolerance:
                continue
            direct = np.linalg.norm(line.p1 - existing.p1) + np.linalg.norm(line.p2 - existing.p2)
            reverse = np.linalg.norm(line.p1 - existing.p2) + np.linalg.norm(line.p2 - existing.p1)
            if min(direct, reverse) <= params.duplicate_distance * 4.0:
                duplicate = True
                break
        if not duplicate:
            kept.append(line)
            buckets.setdefault(cell, []).append(len(kept) - 1)
    return kept


def clean_geometry(
    lines: list[LineSegment], params: GeometryCleanParams | None = None
) -> list[LineSegment]:
    params = params or GeometryCleanParams()
    cleaned = [orthogonalize(line, params.angle_tolerance) for line in lines]
    cleaned = [line for line in cleaned if line.length >= params.min_line_length]
    cleaned = snap_endpoints(cleaned, params.snap_distance)
    cleaned = merge_collinear(cleaned, params)
    cleaned = snap_endpoints(cleaned, params.snap_distance)
    cleaned = remove_duplicates(cleaned, params)
    cleaned = [orthogonalize(line, params.angle_tolerance) for line in cleaned]
    return [line for line in cleaned if line.length >= params.min_line_length]
