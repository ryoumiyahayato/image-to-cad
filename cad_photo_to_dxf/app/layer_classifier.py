from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .cancellation import CancellationToken, checkpoint
from .line_detect import LineSegment

LAYERS = (
    "OUTLINE",
    "WALL_OR_FRAME",
    "GRID_OR_AXIS",
    "HATCH",
    "HATCH_CANDIDATE",
    "DETAIL",
)


@dataclass
class ClassificationParams:
    hatch_angle_tolerance: float = 4.0
    hatch_neighbor_radius: float = 70.0
    hatch_min_neighbors: int = 4
    hatch_max_length_ratio: float = 0.35
    grid_min_length_ratio: float = 0.55
    outline_width_percentile: float = 82.0
    hatch_spacing_cv_max: float = 0.38
    hatch_min_enclosure_sides: int = 3
    hatch_high_confidence: float = 0.70
    hatch_candidate_confidence: float = 0.50


@dataclass
class ClassificationReport:
    input_lines: int = 0
    hatch_lines: int = 0
    hatch_candidate_lines: int = 0
    hatch_lines_dropped: int = 0
    dropped_source_ids: tuple[str, ...] = ()
    layer_counts: dict[str, int] | None = None


@dataclass
class ClassificationResult:
    lines: list[LineSegment]
    report: ClassificationReport


def _angle_difference(a: float, b: float) -> float:
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def _overlap_ratio(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    base = max(1.0, min(end_a - start_a, end_b - start_b))
    return overlap / base


def _enclosure_sides(
    family: list[LineSegment],
    all_lines: list[LineSegment],
    margin: float,
) -> int:
    """Approximate whether an axis-aligned closed region surrounds a hatch family."""
    endpoints = np.array(
        [[point.x1, point.y1] for point in family]
        + [[point.x2, point.y2] for point in family],
        dtype=float,
    )
    min_x, min_y = endpoints.min(axis=0)
    max_x, max_y = endpoints.max(axis=0)
    left = right = top = bottom = False
    family_ids = {id(item) for item in family}
    for boundary in all_lines:
        if id(boundary) in family_ids:
            continue
        angle = boundary.angle
        x_low, x_high = sorted((boundary.x1, boundary.x2))
        y_low, y_high = sorted((boundary.y1, boundary.y2))
        if abs(angle - 90.0) <= 8.0:
            x = (boundary.x1 + boundary.x2) / 2.0
            if _overlap_ratio(y_low, y_high, min_y, max_y) >= 0.55:
                left = left or (min_x - margin <= x <= min_x + margin * 0.35)
                right = right or (max_x - margin * 0.35 <= x <= max_x + margin)
        elif min(angle, 180.0 - angle) <= 8.0:
            y = (boundary.y1 + boundary.y2) / 2.0
            if _overlap_ratio(x_low, x_high, min_x, max_x) >= 0.55:
                top = top or (min_y - margin <= y <= min_y + margin * 0.35)
                bottom = bottom or (max_y - margin * 0.35 <= y <= max_y + margin)
    return sum((left, right, top, bottom))


def classify_layers_with_report(
    lines: list[LineSegment],
    image_shape: tuple[int, ...],
    preserve_hatch: bool = True,
    params: ClassificationParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> ClassificationResult:
    params = params or ClassificationParams()
    report = ClassificationReport(input_lines=len(lines), layer_counts={})
    if not lines:
        return ClassificationResult([], report)

    height, width = image_shape[:2]
    max_dimension = float(max(height, width))
    widths = np.array([line.width for line in lines], dtype=float)
    thick_threshold = max(2.2, float(np.percentile(widths, params.outline_width_percentile)))
    thin_limit = max(2.5, max_dimension * 0.0035)
    midpoints = np.array([line.midpoint for line in lines], dtype=float)
    tree = cKDTree(midpoints)
    neighbor_radius = max(float(params.hatch_neighbor_radius), max_dimension * 0.04)

    hatch_kind = np.full(len(lines), "", dtype=object)
    hatch_confidence = np.zeros(len(lines), dtype=float)
    hatch_reasons: list[tuple[str, ...]] = [() for _ in lines]
    for index, line in enumerate(lines):
        if index % 128 == 0:
            checkpoint(cancellation_token)
        if line.length > max_dimension * params.hatch_max_length_ratio:
            continue
        neighbor_indexes = tree.query_ball_point(line.midpoint, neighbor_radius)
        family_indexes: list[int] = [index]
        similarity_scores: list[float] = []
        for neighbor_index in neighbor_indexes:
            if neighbor_index == index:
                continue
            neighbor = lines[neighbor_index]
            if _angle_difference(line.angle, neighbor.angle) <= params.hatch_angle_tolerance:
                ratio = min(line.length, neighbor.length) / max(
                    line.length, neighbor.length, 1.0
                )
                width_ratio = min(line.width, neighbor.width) / max(
                    line.width, neighbor.width, 1.0
                )
                if ratio >= 0.45 and width_ratio >= 0.50:
                    family_indexes.append(neighbor_index)
                    similarity_scores.append(ratio)
        parallel_count = len(family_indexes) - 1
        if parallel_count < params.hatch_min_neighbors:
            continue

        direction = line.p2 - line.p1
        direction_norm = float(np.linalg.norm(direction))
        if direction_norm <= 1e-9:
            continue
        normal = np.array([-direction[1], direction[0]]) / direction_norm
        offsets = sorted(float(np.dot(lines[item].midpoint, normal)) for item in family_indexes)
        spacings = np.diff(offsets)
        spacings = spacings[spacings > 0.75]
        if len(spacings) < 3:
            continue
        spacing_cv = float(np.std(spacings) / max(np.mean(spacings), 1e-6))
        regular_spacing = spacing_cv <= params.hatch_spacing_cv_max
        family = [lines[item] for item in family_indexes]
        enclosure_sides = _enclosure_sides(family, lines, neighbor_radius)
        thin = line.width <= thin_limit
        density_score = min(1.0, parallel_count / max(params.hatch_min_neighbors + 2, 1))
        similarity_score = float(np.mean(similarity_scores)) if similarity_scores else 0.0
        spacing_score = max(0.0, 1.0 - spacing_cv / max(params.hatch_spacing_cv_max, 1e-6))
        confidence = (
            0.20 * density_score
            + 0.18 * similarity_score
            + 0.22 * spacing_score
            + 0.15 * float(thin)
            + 0.25 * (enclosure_sides / 4.0)
        )
        reasons = (
            f"parallel_neighbors={parallel_count}",
            f"spacing_cv={spacing_cv:.3f}",
            f"enclosure_sides={enclosure_sides}",
            f"thin={str(thin).lower()}",
        )
        hatch_confidence[index] = confidence
        hatch_reasons[index] = reasons
        if (
            regular_spacing
            and thin
            and enclosure_sides >= params.hatch_min_enclosure_sides
            and confidence >= params.hatch_high_confidence
        ):
            hatch_kind[index] = "HATCH"
        elif confidence >= params.hatch_candidate_confidence:
            hatch_kind[index] = "HATCH_CANDIDATE"

    classified: list[LineSegment] = []
    dropped_sources: list[str] = []
    for index, line in enumerate(lines):
        angle = line.angle
        orthogonal = min(angle, 180.0 - angle, abs(angle - 90.0)) <= 4.0
        clearly_thick = line.width >= max(thick_threshold, thin_limit * 1.15)
        if clearly_thick and line.length >= max_dimension * 0.08:
            layer = "OUTLINE"
            confidence = 0.85
            reasons = ("long_thick_stroke",)
        elif hatch_kind[index]:
            layer = str(hatch_kind[index])
            confidence = float(hatch_confidence[index])
            reasons = hatch_reasons[index]
        elif line.length >= max_dimension * params.grid_min_length_ratio and not clearly_thick:
            layer = "GRID_OR_AXIS"
            confidence = 0.75
            reasons = ("long_thin_stroke",)
        elif orthogonal and line.length >= max_dimension * 0.04:
            layer = "WALL_OR_FRAME"
            confidence = 0.65
            reasons = ("orthogonal_medium_or_long_stroke",)
        else:
            layer = "DETAIL"
            confidence = 0.5
            reasons = ("fallback_detail",)

        if layer == "HATCH":
            report.hatch_lines += 1
        elif layer == "HATCH_CANDIDATE":
            report.hatch_candidate_lines += 1
        if layer == "HATCH" and not preserve_hatch:
            report.hatch_lines_dropped += 1
            dropped_sources.extend(line.source_ids)
            continue
        classified_line = line.copy(
            layer=layer,
            classification_confidence=confidence,
            classification_reasons=reasons,
            history=line.history + (f"classify:{layer.lower()}",),
        )
        classified.append(classified_line)
        report.layer_counts[layer] = report.layer_counts.get(layer, 0) + 1

    report.dropped_source_ids = tuple(sorted(set(dropped_sources)))
    checkpoint(cancellation_token)
    return ClassificationResult(classified, report)


def classify_layers(
    lines: list[LineSegment],
    image_shape: tuple[int, ...],
    preserve_hatch: bool = True,
    params: ClassificationParams | None = None,
    cancellation_token: CancellationToken | None = None,
) -> list[LineSegment]:
    return classify_layers_with_report(
        lines,
        image_shape,
        preserve_hatch=preserve_hatch,
        params=params,
        cancellation_token=cancellation_token,
    ).lines
