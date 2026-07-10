from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .line_detect import LineSegment

LAYERS = ("OUTLINE", "WALL_OR_FRAME", "GRID_OR_AXIS", "HATCH", "DETAIL")


@dataclass
class ClassificationParams:
    hatch_angle_tolerance: float = 4.0
    hatch_neighbor_radius: float = 70.0
    hatch_min_neighbors: int = 4
    hatch_max_length_ratio: float = 0.35
    grid_min_length_ratio: float = 0.55
    outline_width_percentile: float = 82.0


def _angle_difference(a: float, b: float) -> float:
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def classify_layers(
    lines: list[LineSegment],
    image_shape: tuple[int, ...],
    preserve_hatch: bool = True,
    params: ClassificationParams | None = None,
) -> list[LineSegment]:
    params = params or ClassificationParams()
    if not lines:
        return []

    height, width = image_shape[:2]
    max_dimension = float(max(height, width))
    lengths = np.array([line.length for line in lines], dtype=float)
    widths = np.array([line.width for line in lines], dtype=float)
    thick_threshold = max(2.2, float(np.percentile(widths, params.outline_width_percentile)))
    midpoints = np.array([line.midpoint for line in lines], dtype=float)
    tree = cKDTree(midpoints)

    hatch_flags = np.zeros(len(lines), dtype=bool)
    for index, line in enumerate(lines):
        if line.length > max_dimension * params.hatch_max_length_ratio:
            continue
        neighbors = tree.query_ball_point(line.midpoint, params.hatch_neighbor_radius)
        parallel = 0
        for neighbor_index in neighbors:
            if neighbor_index == index:
                continue
            neighbor = lines[neighbor_index]
            if _angle_difference(line.angle, neighbor.angle) <= params.hatch_angle_tolerance:
                # Fill strokes are usually comparable in length and form a local parallel family.
                ratio = min(line.length, neighbor.length) / max(line.length, neighbor.length, 1.0)
                if ratio >= 0.45:
                    parallel += 1
        hatch_flags[index] = parallel >= params.hatch_min_neighbors

    classified: list[LineSegment] = []
    for index, line in enumerate(lines):
        angle = line.angle
        orthogonal = min(angle, 180.0 - angle, abs(angle - 90.0)) <= 4.0
        if hatch_flags[index]:
            layer = "HATCH"
        elif line.width >= thick_threshold and line.length >= max_dimension * 0.08:
            layer = "OUTLINE"
        elif line.length >= max_dimension * params.grid_min_length_ratio and line.width < thick_threshold:
            layer = "GRID_OR_AXIS"
        elif orthogonal and line.length >= max_dimension * 0.04:
            layer = "WALL_OR_FRAME"
        else:
            layer = "DETAIL"
        if layer == "HATCH" and not preserve_hatch:
            continue
        classified.append(line.copy(layer=layer))
    return classified
