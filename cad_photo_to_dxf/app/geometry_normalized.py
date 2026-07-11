from __future__ import annotations

from dataclasses import replace

from .cancellation import CancellationToken
from .geometry_cleaner import (
    GeometryCleanParams,
    GeometryCleanResult,
    clean_geometry_with_report as _clean_geometry_with_report,
)
from .line_detect import LineSegment
from .resolution import coordinate_resolution_scale


def geometry_resolution_scale(lines: list[LineSegment]) -> float:
    points = [
        point
        for line in lines
        for point in ((float(line.x1), float(line.y1)), (float(line.x2), float(line.y2)))
    ]
    return coordinate_resolution_scale(points)


def effective_geometry_params(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
) -> tuple[GeometryCleanParams, float]:
    """Scale all pixel-distance cleaning thresholds as one coherent unit."""
    base = params or GeometryCleanParams()
    scale = geometry_resolution_scale(lines)
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
) -> GeometryCleanResult:
    effective, scale = effective_geometry_params(lines, params)
    result = _clean_geometry_with_report(lines, effective, cancellation_token)
    # Keep the existing report schema compatible while making the effective
    # scale available to callers that need to record it.
    setattr(result.report, "resolution_scale", scale)
    return result


def clean_geometry(
    lines: list[LineSegment],
    params: GeometryCleanParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return clean_geometry_with_report(lines, params, cancellation_token).lines
