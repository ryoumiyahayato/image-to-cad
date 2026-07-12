from __future__ import annotations

from dataclasses import replace
from math import hypot, isfinite

from .cancellation import CancellationToken
from .geometry_cleaner import (
    GeometryCleanParams,
    GeometryCleanResult,
    clean_geometry_with_report as _clean_geometry_with_report,
)
from .line_detect import LineSegment
from .resolution import coordinate_resolution_scale


def _is_invalid_candidate(line: LineSegment) -> bool:
    coordinates = (float(line.x1), float(line.y1), float(line.x2), float(line.y2))
    if not all(isfinite(value) for value in coordinates):
        return True
    return hypot(coordinates[2] - coordinates[0], coordinates[3] - coordinates[1]) <= 1e-9


def geometry_resolution_scale(lines: list[LineSegment]) -> float:
    points: list[tuple[float, float]] = []
    for line in lines:
        coordinates = (float(line.x1), float(line.y1), float(line.x2), float(line.y2))
        if not all(isfinite(value) for value in coordinates):
            # Invalid geometry is deliberately left for the cleaner's filtering
            # report; it must not prevent scale estimation for valid candidates.
            continue
        points.extend(((coordinates[0], coordinates[1]), (coordinates[2], coordinates[3])))
    return coordinate_resolution_scale(points)


def effective_geometry_params(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    *,
    resolution_scale: float | None = None,
) -> tuple[GeometryCleanParams, float]:
    """Scale all pixel-distance cleaning thresholds as one coherent unit.

    The caller should pass the scale derived from the full corrected image when
    it is available. Falling back to vector extents is retained for standalone
    geometry utilities and tests, but can underestimate the scale of sparse
    drawings whose detected lines occupy only a small part of a high-resolution
    sheet.
    """
    base = params or GeometryCleanParams()
    scale = (
        geometry_resolution_scale(lines)
        if resolution_scale is None
        else float(resolution_scale)
    )
    if not isfinite(scale) or scale <= 0:
        raise ValueError("Resolution scale must be a positive finite number")
    return (
        replace(
            base,
            snap_distance=float(base.snap_distance) * scale,
            max_bridge_gap=float(base.max_bridge_gap) * scale,
            collinear_distance=float(base.collinear_distance) * scale,
            duplicate_distance=float(base.duplicate_distance) * scale,
            min_line_length=float(base.min_line_length) * scale,
        ),
        scale,
    )


def clean_geometry_with_report(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    cancellation_token: CancellationToken | None = None,
    *,
    resolution_scale: float | None = None,
) -> GeometryCleanResult:
    invalid_input_count = sum(1 for line in lines if _is_invalid_candidate(line))
    effective, scale = effective_geometry_params(
        lines,
        params,
        resolution_scale=resolution_scale,
    )
    result = _clean_geometry_with_report(lines, effective, cancellation_token)
    # The core cleaner historically grouped invalid or zero-length input with
    # short-line removal during its initial gate. Preserve its API while exposing
    # accurate report semantics to the shared normalized pipeline.
    result.report.final_invalid_removed += invalid_input_count
    result.report.initial_short_removed = max(
        0,
        result.report.initial_short_removed - invalid_input_count,
    )
    # Keep the existing report dataclass compatible while exposing the actual
    # scale selected by the shared pipeline.
    setattr(result.report, "resolution_scale", scale)
    return result


def clean_geometry(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    cancellation_token: CancellationToken | None = None,
    *,
    resolution_scale: float | None = None,
) -> list[LineSegment]:
    return clean_geometry_with_report(
        lines,
        params,
        cancellation_token,
        resolution_scale=resolution_scale,
    ).lines
