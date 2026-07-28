from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .structural_roi import verified_structural_rule_masks


@dataclass(frozen=True)
class LogoRegion:
    """A compact source-geometry cluster classified without OCR semantics."""

    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    structural_score: float
    hole_count: int
    contour_count: int


def _foreground(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Logo source must be a non-empty binary page")
    if binary.dtype != np.uint8:
        raise ValueError("Logo source must be an 8-bit binary page")
    return np.where(binary < 128, 255, 0).astype(np.uint8)


def _contour_holes(
    mask: np.ndarray,
) -> tuple[list[np.ndarray], int]:
    contours, hierarchy = cv2.findContours(
        mask,
        cv2.RETR_CCOMP,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if hierarchy is None:
        return contours, 0
    holes = sum(1 for entry in hierarchy[0] if int(entry[3]) >= 0)
    return contours, holes


def _reflection_similarity(mask: np.ndarray) -> float:
    source = mask > 0
    similarities: list[float] = []
    for reflected in (
        np.fliplr(source),
        np.flipud(source),
        np.flipud(np.fliplr(source)),
    ):
        union = int(np.count_nonzero(source | reflected))
        similarities.append(
            int(np.count_nonzero(source & reflected)) / max(1, union)
        )
    return max(similarities)


def _candidate_from_component(
    labels: np.ndarray,
    label: int,
    bbox: tuple[int, int, int, int],
    *,
    median_extent: float,
) -> LogoRegion | None:
    x, y, width, height = bbox
    if width < median_extent * 1.4 or height < median_extent * 1.4:
        return None
    aspect = width / max(1.0, float(height))
    if not 0.32 <= aspect <= 3.4:
        return None
    local = np.where(
        labels[y : y + height, x : x + width] == label,
        255,
        0,
    ).astype(np.uint8)
    area = int(cv2.countNonZero(local))
    density = area / max(1.0, float(width * height))
    contours, hole_count = _contour_holes(local)
    outer_count = max(0, len(contours) - hole_count)
    closed_complexity = sum(
        len(cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True))
        for contour in contours
        if len(contour) >= 3
    )
    reflection_similarity = _reflection_similarity(local)
    if (
        hole_count < 2
        or outer_count < 1
        or closed_complexity < 12
        or not 0.08 <= density <= 0.72
        or reflection_similarity < 0.32
    ):
        return None
    score = min(
        1.0,
        0.35
        + min(hole_count, 6) * 0.08
        + min(closed_complexity, 40) / 120.0
        + reflection_similarity * 0.2,
    )
    return LogoRegion(
        bbox=bbox,
        mask=local,
        structural_score=score,
        hole_count=hole_count,
        contour_count=len(contours),
    )


def detect_logo_regions(binary: np.ndarray) -> tuple[LogoRegion, ...]:
    """Detect conservative logo geometry without reading OCR text or page position."""

    foreground = _foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    non_rules = cv2.subtract(foreground, cv2.max(horizontal, vertical))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        non_rules,
        connectivity=8,
    )
    if count <= 1:
        return ()
    distance = cv2.distanceTransform(non_rules, cv2.DIST_L2, 3)
    stroke_samples = distance[non_rules > 0]
    if not stroke_samples.size:
        return ()
    component_extents = np.asarray(
        [
            max(
                int(stats[label, cv2.CC_STAT_WIDTH]),
                int(stats[label, cv2.CC_STAT_HEIGHT]),
            )
            for label in range(1, count)
            if int(stats[label, cv2.CC_STAT_AREA]) >= 3
        ],
        dtype=np.float64,
    )
    population_extent = (
        float(np.quantile(component_extents, 0.995))
        if len(component_extents) >= 8
        else 0.0
    )
    median_extent = max(
        2.0,
        float(np.median(stroke_samples)) * 4.0,
        population_extent,
    )
    regions: list[LogoRegion] = []
    for label in range(1, count):
        x, y, width, height, area = (
            int(value) for value in stats[label]
        )
        if area < 12:
            continue
        region = _candidate_from_component(
            labels,
            label,
            (x, y, width, height),
            median_extent=median_extent,
        )
        if region is not None:
            regions.append(region)
    regions.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(regions)
