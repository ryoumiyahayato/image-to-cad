from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from .line_detect import LineSegment
from .resolution import image_resolution_scale, scaled_int


@dataclass(frozen=True)
class TextProtectionResult:
    mask: np.ndarray
    candidate_component_count: int
    text_region_count: int
    rejected_line_count: int = 0


def _as_binary_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim != 2 or image.size == 0:
        raise ValueError("Text protection requires a non-empty grayscale image")
    if image.dtype != np.uint8:
        raise ValueError("Text protection requires an 8-bit image")
    return image


def detect_text_region_mask(binary_image: np.ndarray) -> TextProtectionResult:
    """Find conservative rows or columns of glyph-like connected components.

    The mask does not claim to understand the text. It only marks compact groups
    of small printed components so their horizontal and vertical strokes are not
    exported as independent CAD LINE entities.
    """
    image = _as_binary_gray(binary_image)
    scale = image_resolution_scale(image.shape)
    foreground = np.where(image < 128, 255, 0).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        foreground,
        connectivity=8,
    )

    min_height = scaled_int(4, scale, minimum=3)
    max_height = scaled_int(120, scale, minimum=24)
    max_width = scaled_int(180, scale, minimum=32)
    min_area = max(4, int(round(5.0 * scale * scale)))
    max_area = max(320, int(round(12000.0 * scale * scale)))

    candidate_mask = np.zeros_like(image)
    candidate_boxes: list[tuple[int, int, int, int]] = []
    for label in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label])
        if not (min_height <= height <= max_height):
            continue
        if not (1 <= width <= max_width):
            continue
        if not (min_area <= area <= max_area):
            continue
        fill_ratio = area / max(float(width * height), 1.0)
        aspect = width / max(float(height), 1.0)
        if not (0.025 <= fill_ratio <= 0.96):
            continue
        if not (0.06 <= aspect <= 10.0):
            continue
        candidate_mask[labels == label] = 255
        candidate_boxes.append((x, y, width, height))

    if not candidate_boxes:
        return TextProtectionResult(np.zeros_like(image), 0, 0)

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            scaled_int(28, scale, minimum=8),
            scaled_int(7, scale, minimum=2),
        ),
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            scaled_int(7, scale, minimum=2),
            scaled_int(28, scale, minimum=8),
        ),
    )
    grouped = cv2.max(
        cv2.dilate(candidate_mask, horizontal_kernel, iterations=1),
        cv2.dilate(candidate_mask, vertical_kernel, iterations=1),
    )
    group_count, _group_labels, group_stats, _ = cv2.connectedComponentsWithStats(
        grouped,
        connectivity=8,
    )

    mask = np.zeros_like(image)
    margin = scaled_int(4, scale, minimum=2)
    accepted_regions = 0
    for group_label in range(1, group_count):
        x, y, width, height, area = (
            int(value) for value in group_stats[group_label]
        )
        if width < min_height and height < min_height:
            continue
        components_in_group = 0
        for bx, by, bw, bh in candidate_boxes:
            center_x = bx + bw * 0.5
            center_y = by + bh * 0.5
            if x <= center_x <= x + width and y <= center_y <= y + height:
                components_in_group += 1
        horizontal_text = width >= height * 1.2
        vertical_text = height >= width * 1.2
        compact_word = components_in_group >= 2 and (
            horizontal_text or vertical_text or components_in_group >= 4
        )
        dense_single = (
            components_in_group == 1
            and area >= min_area * 6
            and max(width, height) <= max_height * 1.25
        )
        if not (compact_word or dense_single):
            continue
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(image.shape[1] - 1, x + width + margin)
        y2 = min(image.shape[0] - 1, y + height + margin)
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)
        accepted_regions += 1

    return TextProtectionResult(
        mask,
        len(candidate_boxes),
        accepted_regions,
    )


def _line_mask_coverage(line: LineSegment, mask: np.ndarray) -> float:
    sample_count = max(8, min(256, int(math.ceil(line.length / 2.0))))
    xs = np.linspace(line.x1, line.x2, sample_count)
    ys = np.linspace(line.y1, line.y2, sample_count)
    xi = np.clip(np.rint(xs).astype(int), 0, mask.shape[1] - 1)
    yi = np.clip(np.rint(ys).astype(int), 0, mask.shape[0] - 1)
    return float(np.mean(mask[yi, xi] > 0))


def _axis_orientation(line: LineSegment) -> str | None:
    if abs(line.y2 - line.y1) <= abs(line.x2 - line.x1) * 0.08:
        return "horizontal"
    if abs(line.x2 - line.x1) <= abs(line.y2 - line.y1) * 0.08:
        return "vertical"
    return None


def _structural_connection_counts(
    lines: list[LineSegment],
    *,
    tolerance: float,
) -> list[int]:
    """Count supported horizontal/vertical crossings in a rule network."""

    counts = [0] * len(lines)
    horizontal = [
        index
        for index, line in enumerate(lines)
        if _axis_orientation(line) == "horizontal"
    ]
    vertical = [
        index
        for index, line in enumerate(lines)
        if _axis_orientation(line) == "vertical"
    ]
    for horizontal_index in horizontal:
        h_line = lines[horizontal_index]
        h_left, h_right = sorted((h_line.x1, h_line.x2))
        h_y = (h_line.y1 + h_line.y2) * 0.5
        for vertical_index in vertical:
            v_line = lines[vertical_index]
            v_top, v_bottom = sorted((v_line.y1, v_line.y2))
            v_x = (v_line.x1 + v_line.x2) * 0.5
            if (
                h_left - tolerance <= v_x <= h_right + tolerance
                and v_top - tolerance <= h_y <= v_bottom + tolerance
            ):
                counts[horizontal_index] += 1
                counts[vertical_index] += 1
    return counts


def filter_text_like_lines(
    lines: list[LineSegment],
    protection: TextProtectionResult,
    image_shape: tuple[int, ...],
) -> tuple[list[LineSegment], TextProtectionResult]:
    """Reject short line candidates substantially contained by text regions."""
    if protection.text_region_count == 0 or not lines:
        return list(lines), protection

    scale = image_resolution_scale(image_shape)
    diagonal = math.hypot(float(image_shape[0]), float(image_shape[1]))
    local_line_limit = max(72.0 * scale, diagonal * 0.08)
    connection_counts = _structural_connection_counts(
        lines,
        tolerance=max(3.0, 3.0 * scale),
    )
    network_minimum = max(42.0 * scale, diagonal * 0.012)
    kept: list[LineSegment] = []
    rejected = 0
    for index, line in enumerate(lines):
        coverage = _line_mask_coverage(line, protection.mask)
        structural_network = bool(
            line.length >= network_minimum
            and connection_counts[index] >= 2
        )
        reject = (
            coverage >= 0.28 and line.length <= local_line_limit
        ) or coverage >= 0.72
        if reject and not structural_network:
            rejected += 1
            continue
        kept.append(line)

    return kept, TextProtectionResult(
        protection.mask,
        protection.candidate_component_count,
        protection.text_region_count,
        rejected_line_count=rejected,
    )
