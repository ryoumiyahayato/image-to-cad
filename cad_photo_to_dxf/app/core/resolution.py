from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import floor, isfinite


REFERENCE_LONG_EDGE_PX = 2400.0
MIN_IMAGE_LONG_EDGE_FOR_SCALING = 800.0
MIN_RESOLUTION_SCALE = 0.5
MAX_RESOLUTION_SCALE = 3.0


def _positive_finite(value: float, name: str) -> float:
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return normalized


def _clamp_scale(value: float) -> float:
    normalized = _positive_finite(value, "Resolution scale")
    return max(MIN_RESOLUTION_SCALE, min(MAX_RESOLUTION_SCALE, normalized))


def image_resolution_scale(
    shape: Sequence[int],
    *,
    reference_long_edge_px: float = REFERENCE_LONG_EDGE_PX,
) -> float:
    """Return a bounded multiplier for pixel-domain parameters.

    Tiny synthetic images retain scale 1.0 so unit tests and small icons are not
    interpreted as photographed sheets. Real images scale all distance-based
    parameters against one reference long edge.
    """
    reference = _positive_finite(reference_long_edge_px, "Reference long edge")
    if len(shape) < 2:
        raise ValueError("Image shape must contain height and width")
    height = int(shape[0])
    width = int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("Image dimensions must be positive")
    long_edge = float(max(height, width))
    if long_edge < MIN_IMAGE_LONG_EDGE_FOR_SCALING:
        return 1.0
    return _clamp_scale(long_edge / reference)


def coordinate_resolution_scale(
    points: Iterable[tuple[float, float]],
    *,
    reference_long_edge_px: float = REFERENCE_LONG_EDGE_PX,
) -> float:
    """Infer the same multiplier from finite vector-coordinate extents."""
    reference = _positive_finite(reference_long_edge_px, "Reference long edge")
    values = list(points)
    if not values:
        return 1.0
    xs = [float(point[0]) for point in values]
    ys = [float(point[1]) for point in values]
    if not all(isfinite(value) for value in (*xs, *ys)):
        raise ValueError("Vector coordinates must be finite")
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < MIN_IMAGE_LONG_EDGE_FOR_SCALING:
        return 1.0
    return _clamp_scale(span / reference)


def scaled_int(value: float, scale: float, *, minimum: int = 0) -> int:
    normalized_value = float(value)
    normalized_scale = _positive_finite(scale, "Scale")
    if not isfinite(normalized_value) or normalized_value < 0:
        raise ValueError("Scaled value must be a non-negative finite number")
    if minimum < 0:
        raise ValueError("Minimum must be non-negative")
    return max(int(minimum), int(round(normalized_value * normalized_scale)))


def scaled_odd(value: float, scale: float, *, minimum: int = 1) -> int:
    result = scaled_int(value, scale, minimum=minimum)
    if result % 2 == 0:
        result += 1
    return result


def spatial_bucket(value: float, cell_size: float) -> int:
    """Centralize stable floor behavior for negative vector coordinates."""
    normalized_value = float(value)
    normalized_cell = _positive_finite(cell_size, "Cell size")
    if not isfinite(normalized_value):
        raise ValueError("Bucket coordinate must be finite")
    return int(floor(normalized_value / normalized_cell))
