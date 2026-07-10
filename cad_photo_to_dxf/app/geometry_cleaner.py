from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.spatial import cKDTree

from .cancellation import CancellationToken, checkpoint
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


@dataclass
class GeometryCleanReport:
    input_lines: int = 0
    initial_orthogonalized: int = 0
    initial_short_removed: int = 0
    first_snap_moved_endpoints: int = 0
    collinear_merges: int = 0
    merge_pair_limit_reached: bool = False
    duplicate_merges: int = 0
    final_orthogonalized: int = 0
    final_snap_moved_endpoints: int = 0
    final_short_removed: int = 0
    output_lines: int = 0


@dataclass
class GeometryCleanResult:
    lines: list[LineSegment]
    report: GeometryCleanReport


def _angle_difference(a: float, b: float) -> float:
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def orthogonalize(line: LineSegment, tolerance: float) -> LineSegment:
    angle = line.angle
    if min(angle, 180.0 - angle) <= tolerance:
        y = (line.y1 + line.y2) / 2.0
        if abs(line.y1 - y) > 1e-9 or abs(line.y2 - y) > 1e-9:
            return line.copy(y1=y, y2=y, history=line.history + ("orthogonalize",))
    if abs(angle - 90.0) <= tolerance:
        x = (line.x1 + line.x2) / 2.0
        if abs(line.x1 - x) > 1e-9 or abs(line.x2 - x) > 1e-9:
            return line.copy(x1=x, x2=x, history=line.history + ("orthogonalize",))
    return line


def _line_intersection(a: LineSegment, b: LineSegment) -> np.ndarray | None:
    p, r = a.p1, a.p2 - a.p1
    q, s = b.p1, b.p2 - b.p1
    cross = float(r[0] * s[1] - r[1] * s[0])
    if abs(cross) <= 1e-9:
        return None
    qmp = q - p
    t = float((qmp[0] * s[1] - qmp[1] * s[0]) / cross)
    return p + t * r


def _snap_endpoints_with_count(
    lines: list[LineSegment],
    distance: float,
    cancellation_token: CancellationToken | None = None,
) -> tuple[list[LineSegment], int]:
    if not lines or distance <= 0:
        return lines, 0
    points = np.array(
        [[line.x1, line.y1] for line in lines] + [[line.x2, line.y2] for line in lines],
        dtype=float,
    )
    tree = cKDTree(points)
    parent = np.arange(len(points))
    members: dict[int, list[int]] = {index: [index] for index in range(len(points))}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            members[ra] = members.pop(ra, [ra]) + members.pop(rb, [rb])

    pairs = sorted(
        ((int(a), int(b)) for a, b in tree.query_pairs(distance)),
        key=lambda pair: float(np.linalg.norm(points[pair[0]] - points[pair[1]])),
    )
    count = len(lines)
    for pair_index, (a, b) in enumerate(pairs):
        if pair_index % 256 == 0:
            checkpoint(cancellation_token)
        # Never collapse both endpoints of the same source segment.
        if a % count == b % count:
            continue
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        candidate_members = members[ra] + members[rb]
        candidate_points = points[candidate_members]
        deltas = candidate_points[:, None, :] - candidate_points[None, :, :]
        diameter = float(np.max(np.linalg.norm(deltas, axis=2)))
        # Complete-linkage bound prevents a 0-5-10 chain from exceeding a
        # 6-pixel snap threshold through transitive union.
        if diameter <= distance + 1e-9:
            union(ra, rb)

    groups: dict[int, list[int]] = {}
    for index in range(len(points)):
        groups.setdefault(find(index), []).append(index)
    centers: dict[int, np.ndarray] = {}
    for root, indexes in groups.items():
        center = points[indexes].mean(axis=0)
        line_indexes = sorted(set(index % count for index in indexes))
        best_intersection: np.ndarray | None = None
        best_cost = float("inf")
        for left_index, left in enumerate(line_indexes):
            for right in line_indexes[left_index + 1 :]:
                intersection = _line_intersection(lines[left], lines[right])
                if intersection is None:
                    continue
                distances = np.linalg.norm(points[indexes] - intersection, axis=1)
                if float(np.max(distances)) <= distance + 1e-9:
                    cost = float(np.sum(distances))
                    if cost < best_cost:
                        best_cost = cost
                        best_intersection = intersection
        centers[root] = best_intersection if best_intersection is not None else center
    snapped = np.array([centers[find(index)] for index in range(len(points))])

    result: list[LineSegment] = []
    moved_endpoints = 0
    for index, line in enumerate(lines):
        start = snapped[index]
        end = snapped[index + count]
        moved = int(np.linalg.norm(start - line.p1) > 1e-9) + int(
            np.linalg.norm(end - line.p2) > 1e-9
        )
        moved_endpoints += moved
        history = line.history + (("snap_endpoints",) if moved else ())
        result.append(
            line.copy(
                x1=float(start[0]),
                y1=float(start[1]),
                x2=float(end[0]),
                y2=float(end[1]),
                history=history,
            )
        )
    return result, moved_endpoints


def snap_endpoints(
    lines: list[LineSegment],
    distance: float,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return _snap_endpoints_with_count(lines, distance, cancellation_token)[0]


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
        source_ids=tuple(sorted(set(a.source_ids + b.source_ids))),
        history=tuple(dict.fromkeys(a.history + b.history + ("merge_collinear",))),
        classification_confidence=max(
            a.classification_confidence, b.classification_confidence
        ),
        classification_reasons=tuple(
            dict.fromkeys(a.classification_reasons + b.classification_reasons)
        ),
    )


def _merge_collinear_with_report(
    lines: list[LineSegment],
    params: GeometryCleanParams,
    cancellation_token: CancellationToken | None = None,
) -> tuple[list[LineSegment], int, bool]:
    """Greedily merge overlapping or narrowly separated collinear segments."""
    work = sorted(lines, key=lambda line: line.length, reverse=True)
    changed = True
    pair_checks = 0
    merge_count = 0
    while changed:
        checkpoint(cancellation_token)
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
                    result.append(merged)
                    result.extend(
                        work[k] for k in range(i + 1, len(work)) if not consumed[k]
                    )
                    return result, merge_count, True
                if pair_checks % 2048 == 0:
                    checkpoint(cancellation_token)
                candidate = work[j]
                # Midpoint proximity prefilter limits unnecessary geometric checks.
                max_distance = merged.length + candidate.length + params.max_bridge_gap
                if np.linalg.norm(candidate.midpoint - merged.midpoint) > max_distance:
                    continue
                if _can_merge(merged, candidate, params):
                    merged = _merge_pair(merged, candidate)
                    consumed[j] = True
                    changed = True
                    merge_count += 1
            result.append(merged)
        work = sorted(result, key=lambda line: line.length, reverse=True)
    return work, merge_count, False


def merge_collinear(
    lines: list[LineSegment],
    params: GeometryCleanParams,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return _merge_collinear_with_report(lines, params, cancellation_token)[0]


def _remove_duplicates_with_count(
    lines: list[LineSegment],
    params: GeometryCleanParams,
    cancellation_token: CancellationToken | None = None,
) -> tuple[list[LineSegment], int]:
    # Duplicate candidates have almost identical endpoints, so their midpoints also
    # fall in the same small spatial bucket. This avoids an O(n²) full comparison.
    kept: list[LineSegment] = []
    cell_size = max(1.0, params.duplicate_distance * 3.0)
    buckets: dict[tuple[int, int], list[int]] = {}

    duplicate_count = 0
    for line_number, line in enumerate(
        sorted(lines, key=lambda item: (item.length, item.width), reverse=True)
    ):
        if line_number % 256 == 0:
            checkpoint(cancellation_token)
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
                existing_sources = tuple(sorted(set(existing.source_ids + line.source_ids)))
                kept[index] = existing.copy(
                    source_ids=existing_sources,
                    history=tuple(
                        dict.fromkeys(existing.history + line.history + ("merge_duplicate",))
                    ),
                    width=max(existing.width, line.width),
                    confidence=max(existing.confidence, line.confidence),
                )
                duplicate_count += 1
                break
        if not duplicate:
            kept.append(line)
            buckets.setdefault(cell, []).append(len(kept) - 1)
    return kept, duplicate_count


def remove_duplicates(
    lines: list[LineSegment],
    params: GeometryCleanParams,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return _remove_duplicates_with_count(lines, params, cancellation_token)[0]


def clean_geometry(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return clean_geometry_with_report(lines, params, cancellation_token).lines


def clean_geometry_with_report(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> GeometryCleanResult:
    params = params or GeometryCleanParams()
    report = GeometryCleanReport(input_lines=len(lines))
    prepared = [
        line
        if line.source_ids
        else line.copy(source_ids=(f"INPUT-{index:06d}",), history=("input",))
        for index, line in enumerate(lines, start=1)
    ]
    checkpoint(cancellation_token)

    cleaned = [orthogonalize(line, params.angle_tolerance) for line in prepared]
    report.initial_orthogonalized = sum(
        1 for before, after in zip(prepared, cleaned) if before is not after
    )
    before_count = len(cleaned)
    cleaned = [line for line in cleaned if line.length >= params.min_line_length]
    report.initial_short_removed = before_count - len(cleaned)

    cleaned, report.first_snap_moved_endpoints = _snap_endpoints_with_count(
        cleaned, params.snap_distance, cancellation_token
    )
    cleaned, report.collinear_merges, report.merge_pair_limit_reached = (
        _merge_collinear_with_report(cleaned, params, cancellation_token)
    )
    cleaned, report.duplicate_merges = _remove_duplicates_with_count(
        cleaned, params, cancellation_token
    )

    before_orthogonal = cleaned
    cleaned = [orthogonalize(line, params.angle_tolerance) for line in cleaned]
    report.final_orthogonalized = sum(
        1 for before, after in zip(before_orthogonal, cleaned) if before is not after
    )
    # Snapping is deliberately the final coordinate-changing operation so a
    # shared endpoint cannot be pulled apart by a later orthogonalization pass.
    cleaned, report.final_snap_moved_endpoints = _snap_endpoints_with_count(
        cleaned, params.snap_distance, cancellation_token
    )
    before_count = len(cleaned)
    cleaned = [line for line in cleaned if line.length >= params.min_line_length]
    report.final_short_removed = before_count - len(cleaned)
    report.output_lines = len(cleaned)
    checkpoint(cancellation_token)
    return GeometryCleanResult(cleaned, report)
