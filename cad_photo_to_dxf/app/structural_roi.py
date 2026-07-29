from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Sequence

import cv2
import numpy as np

from .line_detect import LineSegment


@dataclass(frozen=True)
class StructuralRoi:
    """A source-derived region where rule reconnection may be considered."""

    roi_id: str
    purpose: str
    bbox: tuple[int, int, int, int]
    line_indices: tuple[int, ...]
    evidence_intersections: tuple[tuple[float, float], ...]
    confidence: float
    expansion_distance: float = 0.0
    source_types: tuple[str, ...] = ()

    def contains(self, point: tuple[float, float]) -> bool:
        x, y, width, height = self.bbox
        return bool(
            x <= point[0] < x + width
            and y <= point[1] < y + height
        )


@dataclass(frozen=True)
class StructuralRoiSet:
    rois: tuple[StructuralRoi, ...]

    def common_roi(
        self,
        left_index: int,
        right_index: int,
        point: tuple[float, float],
    ) -> StructuralRoi | None:
        for roi in self.rois:
            if (
                left_index in roi.line_indices
                and right_index in roi.line_indices
                and roi.contains(point)
            ):
                return roi
        return None


def _run_lengths(values: np.ndarray) -> list[int]:
    positions = np.flatnonzero(values)
    if not positions.size:
        return []
    lengths: list[int] = []
    start = int(positions[0])
    previous = start
    for raw_value in positions[1:]:
        value = int(raw_value)
        if value > previous + 1:
            lengths.append(previous - start + 1)
            start = value
        previous = value
    lengths.append(previous - start + 1)
    return lengths


def _kernel_from_source_runs(foreground: np.ndarray, *, horizontal: bool) -> int:
    runs: list[int] = []
    iterable = foreground if horizontal else foreground.T
    for values in iterable:
        runs.extend(_run_lengths(values > 0))
    if not runs:
        return 9
    observed = np.asarray(runs, dtype=np.float64)
    typical = float(np.median(observed))
    long_runs = observed[observed >= max(5.0, typical * 3.0)]
    if not long_runs.size:
        return max(9, int(round(typical * 4.0)))
    return max(9, int(round(float(np.quantile(long_runs, 0.90)))))


def structural_rule_masks(
    foreground: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract source-supported rules without connecting separate ink."""

    horizontal_length = _kernel_from_source_runs(foreground, horizontal=True)
    vertical_length = _kernel_from_source_runs(foreground, horizontal=False)
    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_length, 1)),
    )
    vertical = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_length)),
    )
    return horizontal, vertical


def verified_structural_rule_masks(
    foreground: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return rules only when they form a table/frame intersection network."""

    horizontal, vertical = structural_rule_masks(foreground)
    intersections = cv2.bitwise_and(horizontal, vertical)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        intersections,
        connectivity=8,
    )
    supported_intersections = sum(
        1
        for label in range(1, count)
        if int(stats[label, cv2.CC_STAT_AREA]) > 0
    )
    if supported_intersections < 4:
        return np.zeros_like(foreground), np.zeros_like(foreground)
    return horizontal, vertical


def _axis_orientation(line: LineSegment) -> str | None:
    dx = abs(float(line.x2) - float(line.x1))
    dy = abs(float(line.y2) - float(line.y1))
    if dy <= max(1.0, dx * 0.12):
        return "horizontal"
    if dx <= max(1.0, dy * 0.12):
        return "vertical"
    return None


def _intersection(
    horizontal: LineSegment,
    vertical: LineSegment,
    *,
    tolerance: float,
) -> tuple[float, float] | None:
    left, right = sorted((float(horizontal.x1), float(horizontal.x2)))
    top, bottom = sorted((float(vertical.y1), float(vertical.y2)))
    y = (float(horizontal.y1) + float(horizontal.y2)) * 0.5
    x = (float(vertical.x1) + float(vertical.x2)) * 0.5
    if (
        left - tolerance <= x <= right + tolerance
        and top - tolerance <= y <= bottom + tolerance
    ):
        return x, y
    return None


def detect_structural_rois(
    lines: Sequence[LineSegment],
    *,
    image_shape: tuple[int, int],
    extension_budget: float,
) -> StructuralRoiSet:
    """Build table/frame ROIs from orthogonal rule networks only."""

    if not lines:
        return StructuralRoiSet(())
    horizontal = [
        index for index, line in enumerate(lines)
        if _axis_orientation(line) == "horizontal"
    ]
    vertical = [
        index for index, line in enumerate(lines)
        if _axis_orientation(line) == "vertical"
    ]
    adjacency: dict[int, set[int]] = {index: set() for index in horizontal + vertical}
    intersections: dict[tuple[int, int], tuple[float, float]] = {}
    median_width = float(np.median([max(1.0, float(line.width)) for line in lines]))
    tolerance = max(2.0, median_width * 1.5, float(extension_budget))
    for horizontal_index in horizontal:
        for vertical_index in vertical:
            point = _intersection(
                lines[horizontal_index],
                lines[vertical_index],
                tolerance=tolerance,
            )
            if point is None:
                continue
            adjacency[horizontal_index].add(vertical_index)
            adjacency[vertical_index].add(horizontal_index)
            intersections[(horizontal_index, vertical_index)] = point

    visited: set[int] = set()
    rois: list[StructuralRoi] = []
    page_height, page_width = image_shape
    for seed in adjacency:
        if seed in visited or not adjacency[seed]:
            continue
        stack = [seed]
        component: set[int] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        visited.update(component)
        component_horizontal = sorted(set(horizontal) & component)
        component_vertical = sorted(set(vertical) & component)
        if len(component_horizontal) < 2 or len(component_vertical) < 2:
            continue
        component_intersections = tuple(
            point
            for (left, right), point in intersections.items()
            if left in component and right in component
        )
        if len(component_intersections) < 4:
            continue
        xs = [
            value
            for index in component
            for value in (float(lines[index].x1), float(lines[index].x2))
        ]
        ys = [
            value
            for index in component
            for value in (float(lines[index].y1), float(lines[index].y2))
        ]
        component_widths = [
            max(1.0, float(lines[index].width))
            for index in component
        ]
        component_median_width = float(np.median(component_widths))
        pad = max(
            2,
            int(round(component_median_width + extension_budget)),
        )
        left = max(0, int(np.floor(min(xs))) - pad)
        top = max(0, int(np.floor(min(ys))) - pad)
        right = min(page_width - 1, int(np.ceil(max(xs))) + pad)
        bottom = min(page_height - 1, int(np.ceil(max(ys))) + pad)
        if right <= left or bottom <= top:
            continue
        crossing_capacity = len(component_horizontal) * len(component_vertical)
        confidence = min(
            1.0,
            len(component_intersections) / max(4.0, float(crossing_capacity)),
        )
        purpose = (
            "frame"
            if len(component_horizontal) == 2 and len(component_vertical) == 2
            else "table"
        )
        source_types = (
            "source_supported_axis_lines",
            (
                "closed_frame_network"
                if purpose == "frame"
                else "table_line_network"
            ),
            "orthogonal_intersection_network",
            "measured_line_width_and_direction",
            "local_endpoint_corridor",
        )
        rois.append(
            StructuralRoi(
                roi_id=f"{purpose}-{len(rois) + 1:03d}",
                purpose=purpose,
                bbox=(left, top, right - left + 1, bottom - top + 1),
                line_indices=tuple(sorted(component)),
                evidence_intersections=component_intersections,
                confidence=confidence,
                expansion_distance=float(extension_budget),
                source_types=source_types,
            )
        )
    return StructuralRoiSet(tuple(rois))


def _structural_roi_bounds(
    roi: StructuralRoi,
    *,
    image_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    page_height, page_width = image_shape
    x, y, width, height = roi.bbox
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(page_width, int(x + width))
    bottom = min(page_height, int(y + height))
    if right <= left or bottom <= top:
        raise ValueError(f"Structural ROI {roi.roi_id} is outside the page")
    return left, top, right, bottom


def rasterize_structural_roi_corridor_crop(
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    *,
    image_shape: tuple[int, int],
) -> tuple[int, int, np.ndarray]:
    """Return one bounded corridor in ROI-local coordinates."""

    left, top, right, bottom = _structural_roi_bounds(
        roi,
        image_shape=image_shape,
    )
    local = np.zeros((bottom - top, right - left), dtype=np.uint8)
    extension = max(0.0, float(roi.expansion_distance))
    for raw_index in roi.line_indices:
        index = int(raw_index)
        if index < 0 or index >= len(lines):
            raise IndexError(
                f"Structural ROI {roi.roi_id} references missing line {index}"
            )
        line = lines[index]
        dx = float(line.x2) - float(line.x1)
        dy = float(line.y2) - float(line.y1)
        length = hypot(dx, dy)
        if length <= 1e-9:
            continue
        unit_x = dx / length
        unit_y = dy / length
        start = (
            int(round(float(line.x1) - unit_x * extension)) - left,
            int(round(float(line.y1) - unit_y * extension)) - top,
        )
        end = (
            int(round(float(line.x2) + unit_x * extension)) - left,
            int(round(float(line.y2) + unit_y * extension)) - top,
        )
        corridor_thickness = max(
            3,
            int(np.ceil(max(1.0, float(line.width)))) + 2,
        )
        cv2.line(
            local,
            start,
            end,
            255,
            corridor_thickness,
            cv2.LINE_8,
        )
    return left, top, local


def rasterize_structural_roi_corridor(
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    *,
    image_shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize only source-line bands and their bounded endpoint extensions."""

    left, top, local = rasterize_structural_roi_corridor_crop(
        roi,
        lines,
        image_shape=image_shape,
    )
    mask = np.zeros(image_shape, dtype=np.uint8)
    bottom = top + local.shape[0]
    right = left + local.shape[1]
    mask[top:bottom, left:right] = local
    return mask


def rasterize_structural_roi_corridors(
    rois: Sequence[StructuralRoi],
    lines: Sequence[LineSegment],
    *,
    image_shape: tuple[int, int],
) -> np.ndarray:
    """Return the union of bounded local repair corridors."""

    mask = np.zeros(image_shape, dtype=np.uint8)
    for roi in rois:
        mask = cv2.max(
            mask,
            rasterize_structural_roi_corridor(
                roi,
                lines,
                image_shape=image_shape,
            ),
        )
    return mask


def rasterize_structural_lines(
    lines: Sequence[LineSegment],
    line_indices: Sequence[int],
    *,
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    for index in line_indices:
        line = lines[int(index)]
        cv2.line(
            mask,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            max(1, int(round(float(line.width)))),
            cv2.LINE_8,
        )
    return mask


def segment_length(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    return hypot(end[0] - start[0], end[1] - start[1])
