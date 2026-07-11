from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .cancellation import CancellationToken, checkpoint
from .line_detect import LineSegment


@dataclass(frozen=True)
class TopologyParams:
    split_intersections: bool = True
    intersection_tolerance: float = 1e-6
    max_pair_checks: int = 2_000_000


@dataclass(frozen=True)
class TopologyReport:
    input_lines: int
    output_lines: int
    split_line_count: int
    generated_segment_count: int
    pair_checks: int
    pair_limit_reached: bool


@dataclass
class TopologyResult:
    lines: list[LineSegment]
    report: TopologyReport


def _cross(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _intersection_parameters(
    first: LineSegment,
    second: LineSegment,
    tolerance: float,
) -> tuple[float, float] | None:
    point_a = first.p1
    vector_a = first.p2 - first.p1
    point_b = second.p1
    vector_b = second.p2 - second.p1

    min_ax, max_ax = sorted((first.x1, first.x2))
    min_ay, max_ay = sorted((first.y1, first.y2))
    min_bx, max_bx = sorted((second.x1, second.x2))
    min_by, max_by = sorted((second.y1, second.y2))
    if (
        max_ax + tolerance < min_bx
        or max_bx + tolerance < min_ax
        or max_ay + tolerance < min_by
        or max_by + tolerance < min_ay
    ):
        return None

    denominator = _cross(vector_a, vector_b)
    scale = max(first.length, second.length, 1.0)
    if abs(denominator) <= tolerance * scale:
        return None

    offset = point_b - point_a
    first_parameter = _cross(offset, vector_b) / denominator
    second_parameter = _cross(offset, vector_a) / denominator
    parameter_tolerance = min(0.25, tolerance / scale)
    if not (
        -parameter_tolerance <= first_parameter <= 1.0 + parameter_tolerance
        and -parameter_tolerance <= second_parameter <= 1.0 + parameter_tolerance
    ):
        return None
    return first_parameter, second_parameter


def _append_interior_parameter(
    values: list[float],
    parameter: float,
    line_length: float,
    tolerance: float,
) -> None:
    epsilon = max(1e-9, tolerance / max(line_length, 1.0))
    if epsilon < parameter < 1.0 - epsilon:
        values.append(float(np.clip(parameter, 0.0, 1.0)))


def _deduplicate_parameters(values: list[float], tolerance: float) -> list[float]:
    ordered = sorted(values)
    result: list[float] = []
    for value in ordered:
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def split_lines_at_intersections(
    lines: list[LineSegment],
    params: TopologyParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TopologyResult:
    params = params or TopologyParams()
    if params.intersection_tolerance <= 0 or not math.isfinite(
        params.intersection_tolerance
    ):
        raise ValueError("Intersection tolerance must be finite and positive")
    if params.max_pair_checks < 0:
        raise ValueError("Maximum pair checks cannot be negative")
    if not params.split_intersections or len(lines) < 2:
        return TopologyResult(
            list(lines),
            TopologyReport(
                input_lines=len(lines),
                output_lines=len(lines),
                split_line_count=0,
                generated_segment_count=0,
                pair_checks=0,
                pair_limit_reached=False,
            ),
        )

    breakpoints: list[list[float]] = [[0.0, 1.0] for _ in lines]
    pair_checks = 0
    pair_limit_reached = False
    for left in range(len(lines)):
        checkpoint(cancellation_token)
        for right in range(left + 1, len(lines)):
            if pair_checks >= params.max_pair_checks:
                pair_limit_reached = True
                break
            pair_checks += 1
            if pair_checks % 2048 == 0:
                checkpoint(cancellation_token)
            parameters = _intersection_parameters(
                lines[left],
                lines[right],
                params.intersection_tolerance,
            )
            if parameters is None:
                continue
            left_parameter, right_parameter = parameters
            _append_interior_parameter(
                breakpoints[left],
                left_parameter,
                lines[left].length,
                params.intersection_tolerance,
            )
            _append_interior_parameter(
                breakpoints[right],
                right_parameter,
                lines[right].length,
                params.intersection_tolerance,
            )
        if pair_limit_reached:
            break

    output: list[LineSegment] = []
    split_line_count = 0
    for line, values in zip(lines, breakpoints):
        parameter_tolerance = max(
            1e-9,
            params.intersection_tolerance / max(line.length, 1.0),
        )
        points = _deduplicate_parameters(values, parameter_tolerance)
        if len(points) > 2:
            split_line_count += 1
        vector = line.p2 - line.p1
        for start_parameter, end_parameter in zip(points, points[1:]):
            start = line.p1 + vector * start_parameter
            end = line.p1 + vector * end_parameter
            if float(np.linalg.norm(end - start)) <= params.intersection_tolerance:
                continue
            history = line.history
            if len(points) > 2:
                history = tuple(
                    dict.fromkeys(line.history + ("split_intersection",))
                )
            output.append(
                line.copy(
                    x1=float(start[0]),
                    y1=float(start[1]),
                    x2=float(end[0]),
                    y2=float(end[1]),
                    history=history,
                )
            )

    return TopologyResult(
        output,
        TopologyReport(
            input_lines=len(lines),
            output_lines=len(output),
            split_line_count=split_line_count,
            generated_segment_count=max(0, len(output) - len(lines)),
            pair_checks=pair_checks,
            pair_limit_reached=pair_limit_reached,
        ),
    )
