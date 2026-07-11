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
        return math.dist(self.point1, self.point2)

    @property
    def mm_per_pixel(self) -> float:
        if self.pixel_distance <= 1e-9:
            raise ValueError("Calibration points must not be identical")
        if self.actual_length_mm <= 0:
            raise ValueError("Actual length must be greater than zero")
        return self.actual_length_mm / self.pixel_distance


def create_calibration(
    points: Iterable[Iterable[float]],
    actual_length_mm: float,
) -> ScaleCalibration:
    values: list[tuple[float, float]] = []
    for point in points:
        coordinates = tuple(map(float, point))
        if len(coordinates) != 2:
            raise ValueError("Each calibration point must contain exactly two coordinates")
        values.append((coordinates[0], coordinates[1]))
    if len(values) != 2:
        raise ValueError("Exactly two calibration points are required")
    calibration = ScaleCalibration(values[0], values[1], float(actual_length_mm))
    _ = calibration.mm_per_pixel
    return calibration
