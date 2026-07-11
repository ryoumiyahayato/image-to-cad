from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass
class ScaleCalibration:
    point1: tuple[float, float]
    point2: tuple[float, float]
    actual_length_mm: float

    @property
    def pixel_distance(self) -> float:
        coordinates = (*self.point1, *self.point2)
        if not all(math.isfinite(float(value)) for value in coordinates):
            raise ValueError("Calibration point coordinates must be finite")
        distance = math.dist(self.point1, self.point2)
        if not math.isfinite(distance):
            raise ValueError("Calibration pixel distance must be finite")
        return distance

    @property
    def mm_per_pixel(self) -> float:
        distance = self.pixel_distance
        if distance <= 1e-9:
            raise ValueError("Calibration points must not be identical")
        actual_length = float(self.actual_length_mm)
        if not math.isfinite(actual_length) or actual_length <= 0:
            raise ValueError("Actual length must be a positive finite number")
        scale = actual_length / distance
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Calibration scale must be a positive finite number")
        return scale


def create_calibration(
    points: Iterable[Iterable[float]],
    actual_length_mm: float,
) -> ScaleCalibration:
    values: list[tuple[float, float]] = []
    for point in points:
        coordinates = tuple(map(float, point))
        if len(coordinates) != 2:
            raise ValueError("Each calibration point must contain exactly two coordinates")
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Calibration point coordinates must be finite")
        values.append((coordinates[0], coordinates[1]))
    if len(values) != 2:
        raise ValueError("Exactly two calibration points are required")
    calibration = ScaleCalibration(values[0], values[1], float(actual_length_mm))
    _ = calibration.mm_per_pixel
    return calibration
