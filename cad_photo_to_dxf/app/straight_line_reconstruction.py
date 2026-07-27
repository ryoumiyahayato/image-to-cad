from __future__ import annotations

import math
from collections.abc import Sequence

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .geometry_cleaner import GeometryCleanParams, clean_geometry
from .line_detect import LineDetectionParams, LineSegment, detect_lines
from .resolution import image_resolution_scale


def _cross(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _angle_difference(left: LineSegment, right: LineSegment) -> float:
    delta = abs(left.angle - right.angle) % 180.0
    return min(delta, 180.0 - delta)


def _candidate_pairs(
    lines: Sequence[LineSegment],
    tolerance: float,
) -> list[tuple[int, int]]:
    """Return spatially nearby pairs without comparing every line to every line."""

    if len(lines) < 2:
        return []
    lengths = [line.length for line in lines if line.length > 1e-9]
    median_length = float(np.median(lengths)) if lengths else 64.0
    cell_size = max(32.0, min(384.0, median_length))
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


def _intersection_parameters(
    left: LineSegment,
    right: LineSegment,
) -> tuple[float, float, np.ndarray] | None:
    p = left.p1
    r = left.p2 - left.p1
    q = right.p1
    s = right.p2 - right.p1
    denominator = _cross(r, s)
    if abs(denominator) <= 1e-9:
        return None
    offset = q - p
    left_parameter = _cross(offset, s) / denominator
    right_parameter = _cross(offset, r) / denominator
    return (
        float(left_parameter),
        float(right_parameter),
        p + left_parameter * r,
    )


def _extension_endpoint(
    line: LineSegment,
    parameter: float,
    point: np.ndarray,
    maximum_extension: float,
) -> tuple[int, float] | None:
    """Identify an endpoint that can only move outwards to the intersection."""

    epsilon = 1e-7
    if parameter < -epsilon:
        distance = float(np.linalg.norm(point - line.p1))
        return (0, distance) if distance <= maximum_extension else None
    if parameter > 1.0 + epsilon:
        distance = float(np.linalg.norm(point - line.p2))
        return (1, distance) if distance <= maximum_extension else None
    return None


def _parameter_within_extended_segment(
    line: LineSegment,
    parameter: float,
    maximum_extension: float,
) -> bool:
    parameter_tolerance = maximum_extension / max(line.length, 1.0)
    return -parameter_tolerance <= parameter <= 1.0 + parameter_tolerance


def _axis_distance(angle: float) -> float:
    normalized = float(angle) % 90.0
    return min(normalized, 90.0 - normalized)


def _structural_intersection_pair(
    left: LineSegment,
    right: LineSegment,
    *,
    minimum_angle_degrees: float,
) -> bool:
    """Reject the shallow arbitrary crossings common in handwriting and damage."""

    difference = _angle_difference(left, right)
    if difference < minimum_angle_degrees:
        return False
    both_axis_aligned = _axis_distance(left.angle) <= 4.0 and _axis_distance(
        right.angle
    ) <= 4.0
    near_perpendicular = 72.0 <= difference <= 108.0
    return bool(both_axis_aligned or near_perpendicular)


def extend_lines_to_first_intersection(
    lines: Sequence[LineSegment],
    *,
    maximum_extension: float,
    minimum_angle_degrees: float = 7.5,
    max_pair_checks: int = 750_000,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    """Extend each open endpoint to its nearest valid theoretical intersection.

    An endpoint is changed at most once. Candidate intersections are ordered by
    extension distance, so the line stops at the first crossing and never grows
    through a nearer boundary to reach a farther one. Existing endpoints are
    never shortened.
    """

    resolved = [line.copy() for line in lines if line.length > 1e-9]
    if not resolved or maximum_extension <= 0.0:
        return resolved

    choices: dict[tuple[int, int], tuple[float, np.ndarray]] = {}
    pair_checks = 0
    for left_index, right_index in _candidate_pairs(resolved, maximum_extension):
        pair_checks += 1
        if pair_checks % 512 == 0:
            checkpoint(cancellation_token)
        if pair_checks > max_pair_checks:
            break
        left = resolved[left_index]
        right = resolved[right_index]
        if not _structural_intersection_pair(
            left,
            right,
            minimum_angle_degrees=minimum_angle_degrees,
        ):
            continue
        intersection = _intersection_parameters(left, right)
        if intersection is None:
            continue
        left_parameter, right_parameter, point = intersection
        if not _parameter_within_extended_segment(
            left, left_parameter, maximum_extension
        ):
            continue
        if not _parameter_within_extended_segment(
            right, right_parameter, maximum_extension
        ):
            continue

        left_endpoint = _extension_endpoint(
            left, left_parameter, point, maximum_extension
        )
        right_endpoint = _extension_endpoint(
            right, right_parameter, point, maximum_extension
        )
        if left_endpoint is None and right_endpoint is None:
            continue
        for line_index, endpoint in (
            (left_index, left_endpoint),
            (right_index, right_endpoint),
        ):
            if endpoint is None:
                continue
            endpoint_index, distance = endpoint
            source_line = resolved[line_index]
            relative_limit = max(2.0, source_line.length * 0.20)
            if distance > relative_limit:
                continue
            key = (line_index, endpoint_index)
            current = choices.get(key)
            if current is None or distance < current[0]:
                choices[key] = (distance, point.copy())

    output: list[LineSegment] = []
    for index, line in enumerate(resolved):
        start = choices.get((index, 0))
        end = choices.get((index, 1))
        changes: dict[str, float | tuple[str, ...]] = {}
        if start is not None:
            changes["x1"] = float(start[1][0])
            changes["y1"] = float(start[1][1])
        if end is not None:
            changes["x2"] = float(end[1][0])
            changes["y2"] = float(end[1][1])
        if changes:
            changes["history"] = tuple(
                dict.fromkeys(line.history + ("extend_to_first_intersection",))
            )
            output.append(line.copy(**changes))
        else:
            output.append(line)
    return output


def reconstruct_straight_lines(
    binary: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[LineSegment, ...]:
    """Detect long printed strokes and rebuild them as editable center lines."""

    if binary.ndim != 2 or binary.size == 0:
        return ()
    scale = image_resolution_scale(binary.shape)
    minimum_length = max(24.0 * scale, min(binary.shape[:2]) * 0.008)
    raw = detect_lines(
        binary,
        LineDetectionParams(
            min_line_length=24,
            max_line_gap=12,
            hough_threshold=28,
            use_lsd=True,
            max_segments=5000,
            center_thick_strokes=True,
        ),
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage, 0.55 * max(0.0, min(1.0, fraction))
            )
        ),
    )
    checkpoint(cancellation_token)
    candidates = [
        line
        for line in raw
        if line.length >= minimum_length
        and line.length >= max(10.0 * line.width, minimum_length)
        and (
            _axis_distance(line.angle) <= 4.0
            or line.length
            >= max(min(binary.shape[:2]) * 0.04, minimum_length * 3.0)
        )
    ]
    report_progress(progress_callback, "line-filtering", 0.58)
    if not candidates:
        return ()

    cleaned = clean_geometry(
        candidates,
        GeometryCleanParams(
            snap_distance=4.0 * scale,
            max_bridge_gap=12.0 * scale,
            angle_tolerance=2.5,
            collinear_distance=2.5 * scale,
            duplicate_distance=2.5 * scale,
            min_line_length=minimum_length,
            max_pair_checks=750_000,
        ),
        cancellation_token,
    )
    report_progress(progress_callback, "line-cleaning", 0.86)
    extended = extend_lines_to_first_intersection(
        cleaned,
        maximum_extension=max(6.0, 12.0 * scale),
        cancellation_token=cancellation_token,
    )
    checkpoint(cancellation_token)
    report_progress(progress_callback, "line-reconstruction", 1.0)
    return tuple(
        sorted(
            extended,
            key=lambda line: (
                round(min(line.y1, line.y2), 3),
                round(min(line.x1, line.x2), 3),
                -line.length,
            ),
        )
    )


def suppress_reconstructed_lines(
    binary: np.ndarray,
    lines: Sequence[LineSegment],
) -> np.ndarray:
    """Remove line stroke pixels before contour tracing; lines are exported separately."""

    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    if not lines:
        return result
    scale = image_resolution_scale(binary.shape)
    maximum_thickness = max(5, int(round(20.0 * scale)))
    for line in lines:
        thickness = max(
            2,
            min(
                maximum_thickness,
                int(math.ceil(max(1.0, line.width) * 1.35)) + 2,
            ),
        )
        cv2.line(
            result,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            thickness,
            cv2.LINE_8,
        )
    return result
