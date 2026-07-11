from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import floor


REFERENCE_LONG_EDGE_PX = 2400.0
MIN_IMAGE_LONG_EDGE_FOR_SCALING = 800.0
MIN_RESOLUTION_SCALE = 0.5
MAX_RESOLUTION_SCALE = 3.0


def _clamp_scale(value: float) -> float:
    return max(MIN_RESOLUTION_SCALE, min(MAX_RESOLUTION_SCALE, float(value)))


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
    if len(shape) < 2:
        raise ValueError("Image shape must contain height and width")
    long_edge = float(max(int(shape[0]), int(shape[1])))
    if long_edge <= 0:
        raise ValueError("Image dimensions must be positive")
    if long_edge < MIN_IMAGE_LONG_EDGE_FOR_SCALING:
        return 1.0
    if reference_long_edge_px <= 0:
        raise ValueError("Reference long edge must be positive")
    return _clamp_scale(long_edge / float(reference_long_edge_px))


def coordinate_resolution_scale(
    points: Iterable[tuple[float, float]],
    *,
    reference_long_edge_px: float = REFERENCE_LONG_EDGE_PX,
) -> float:
    """Infer the same multiplier from vector-coordinate extents."""
    values = list(points)
    if not values:
        return 1.0
    xs = [float(point[0]) for point in values]
    ys = [float(point[1]) for point in values]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < MIN_IMAGE_LONG_EDGE_FOR_SCALING:
        return 1.0
    if reference_long_edge_px <= 0:
        raise ValueError("Reference long edge must be positive")
    return _clamp_scale(span / float(reference_long_edge_px))


def scaled_int(value: float, scale: float, *, minimum: int = 0) -> int:
    return max(int(minimum), int(round(float(value) * float(scale))))


def scaled_odd(value: float, scale: float, *, minimum: int = 1) -> int:
    result = scaled_int(value, scale, minimum=minimum)
    if result % 2 == 0:
        result += 1
    return result


def spatial_bucket(value: float, cell_size: float) -> int:
    """Centralize stable floor behavior for negative vector coordinates."""
    if cell_size <= 0:
        raise ValueError("Cell size must be positive")
    return int(floor(float(value) / float(cell_size)))
