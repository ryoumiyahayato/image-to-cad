from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import cv2
import numpy as np

from .raster_trace import TracePath, trace_binary
from .resolution import image_resolution_scale, scaled_int, scaled_odd


@dataclass(frozen=True)
class ScanArtifactSuppressionResult:
    binary: np.ndarray
    removed_root_count: int


@dataclass(frozen=True)
class _RootMetrics:
    box: tuple[int, int, int, int]
    median_tone: float
    defect_overlap: float
    solidity: float
    occupancy: float
    aspect_ratio: float
    edge_damage: bool
    local_damage: bool
    long_sparse_flight: bool


def _bright_damage_mask(gray: np.ndarray, scale: float) -> np.ndarray:
    """Locate raised folds, tears and transparent tape on scanned paper."""

    median_size = scaled_odd(31.0, scale, minimum=15)
    local_median = cv2.medianBlur(gray, median_size)
    bright_residual = gray.astype(np.int16) - local_median.astype(np.int16)
    seed = np.where(
        (bright_residual >= 18) & (gray >= 190),
        255,
        0,
    ).astype(np.uint8)
    open_size = scaled_odd(3.0, scale, minimum=3)
    seed = cv2.morphologyEx(
        seed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (open_size, open_size),
        ),
    )

    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        seed,
        connectivity=8,
    )
    keep = np.zeros(count, dtype=bool)
    minimum_area = scaled_int(9.0, scale * scale, minimum=7)
    minimum_span = scaled_int(7.0, scale, minimum=6)
    for label_value in range(1, count):
        width = int(stats[label_value, cv2.CC_STAT_WIDTH])
        height = int(stats[label_value, cv2.CC_STAT_HEIGHT])
        area = int(stats[label_value, cv2.CC_STAT_AREA])
        keep[label_value] = area >= minimum_area and max(width, height) >= minimum_span

    retained = np.where(keep[labels], 255, 0).astype(np.uint8)
    influence_radius = scaled_int(8.0, scale, minimum=6)
    return cv2.dilate(
        retained,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (influence_radius * 2 + 1, influence_radius * 2 + 1),
        ),
    )


def _path_metrics(
    path: TracePath,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
    damage_mask: np.ndarray,
    scale: float,
) -> _RootMetrics | None:
    points = np.asarray(path.points, dtype=np.float32)
    if len(points) < 3:
        return None
    x, y, width, height = cv2.boundingRect(points.astype(np.int32))
    page_height, page_width = binary.shape
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > page_width
        or y + height > page_height
    ):
        return None

    contour_area = abs(float(cv2.contourArea(points)))
    hull_area = abs(float(cv2.contourArea(cv2.convexHull(points))))
    solidity = contour_area / max(hull_area, 1.0)
    occupancy = contour_area / max(float(width * height), 1.0)
    maximum_span = max(width, height)
    minimum_span = min(width, height)
    aspect_ratio = maximum_span / max(float(minimum_span), 1.0)

    local_points = np.rint(points - np.array([x, y], dtype=np.float32)).astype(
        np.int32
    )
    contour_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(contour_mask, [local_points], 255)
    foreground = (contour_mask > 0) & (binary[y : y + height, x : x + width] == 0)
    foreground_count = int(np.count_nonzero(foreground))
    if foreground_count <= 0:
        return None

    median_tone = float(np.median(gray[y : y + height, x : x + width][foreground]))
    defect_overlap = float(
        np.count_nonzero(
            (damage_mask[y : y + height, x : x + width] > 0) & foreground
        )
    ) / float(foreground_count)

    edge_band = scaled_int(12.0, scale, minimum=8)
    touched_edges = sum(
        (
            x <= edge_band,
            y <= edge_band,
            x + width >= page_width - edge_band,
            y + height >= page_height - edge_band,
        )
    )
    edge_damage = (
        touched_edges >= 2
        and maximum_span >= scaled_int(35.0, scale, minimum=24)
        and minimum_span >= scaled_int(18.0, scale, minimum=12)
        and median_tone >= 145.0
        and defect_overlap >= 0.12
    )
    local_damage = (
        maximum_span >= scaled_int(18.0, scale, minimum=12)
        and minimum_span >= scaled_int(8.0, scale, minimum=6)
        and median_tone >= 145.0
        and solidity <= 0.60
        and defect_overlap >= 0.18
    )
    long_sparse_flight = (
        maximum_span >= scaled_int(120.0, scale, minimum=80)
        and aspect_ratio >= 4.5
        and occupancy <= 0.035
        and solidity <= 0.10
    )
    return _RootMetrics(
        box=(x, y, width, height),
        median_tone=median_tone,
        defect_overlap=defect_overlap,
        solidity=solidity,
        occupancy=occupancy,
        aspect_ratio=aspect_ratio,
        edge_damage=edge_damage,
        local_damage=local_damage,
        long_sparse_flight=long_sparse_flight,
    )


def _remove_corner_damage_clusters(
    binary: np.ndarray,
    damage_mask: np.ndarray,
    scale: float,
) -> tuple[np.ndarray, int]:
    """Erase corner damage even when it is joined to a full-page border.

    Tape or a folded corner can merge with the page frame into one enormous
    contour.  Whole-contour rejection cannot remove that damage without also
    deleting the frame, so isolate the bright-damage cluster spatially.  The
    frame has already been reconstructed as LINE entities before this pass.
    """

    page_height, page_width = binary.shape
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(damage_mask > 0, 1, 0).astype(np.uint8),
        connectivity=8,
    )
    component_boxes: list[tuple[int, int, int, int, int]] = []
    for label_value in range(1, count):
        x = int(stats[label_value, cv2.CC_STAT_LEFT])
        y = int(stats[label_value, cv2.CC_STAT_TOP])
        width = int(stats[label_value, cv2.CC_STAT_WIDTH])
        height = int(stats[label_value, cv2.CC_STAT_HEIGHT])
        area = int(stats[label_value, cv2.CC_STAT_AREA])
        component_boxes.append((x, y, width, height, area))
    _foreground_count, foreground_labels = cv2.connectedComponents(
        np.where(binary == 0, 1, 0).astype(np.uint8),
        connectivity=8,
    )

    def source_labels(
        box: tuple[int, int, int, int, int],
    ) -> set[int]:
        x, y, width, height, _area = box
        return {
            int(value)
            for value in np.unique(
                foreground_labels[y : y + height, x : x + width]
            )
            if int(value) > 0
        }

    cleaned = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    padding = scaled_int(55.0, scale, minimum=40)
    minimum_area = scaled_int(45.0, scale * scale, minimum=25)
    removed_regions = 0
    for left_side, top_side in (
        (True, True),
        (False, True),
        (True, False),
        (False, False),
    ):
        selected: list[tuple[int, int, int, int, int]] = []
        for box in component_boxes:
            x, y, width, height, _area = box
            in_horizontal_corner = (
                x <= padding
                if left_side
                else x + width >= page_width - padding
            )
            in_vertical_corner = (
                y <= padding
                if top_side
                else y + height >= page_height - padding
            )
            if in_horizontal_corner and in_vertical_corner:
                selected.append(box)
        changed = True
        while selected and changed:
            changed = False
            selected_source_labels = set().union(
                *(source_labels(box) for box in selected)
            )
            for box in component_boxes:
                if box in selected:
                    continue
                same_damaged_root = bool(
                    source_labels(box) & selected_source_labels
                )
                nearby_damage = any(
                    _box_distance(box[:4], existing[:4]) <= padding
                    for existing in selected
                )
                if same_damaged_root or nearby_damage:
                    selected.append(box)
                    changed = True
        if not selected or sum(box[4] for box in selected) < minimum_area:
            continue

        x0 = (
            0
            if left_side
            else max(0, min(box[0] for box in selected) - padding)
        )
        y0 = (
            0
            if top_side
            else max(0, min(box[1] for box in selected) - padding)
        )
        x1 = (
            min(
                page_width,
                max(box[0] + box[2] for box in selected) + padding,
            )
            if left_side
            else page_width
        )
        y1 = (
            min(
                page_height,
                max(box[1] + box[3] for box in selected) + padding,
            )
            if top_side
            else page_height
        )
        minimum_span = scaled_int(18.0, scale, minimum=12)
        if x1 - x0 < minimum_span or y1 - y0 < minimum_span:
            continue
        cleaned[y0:y1, x0:x1] = 255
        removed_regions += 1
    return cleaned, removed_regions


def _remove_scan_edge_band(
    binary: np.ndarray,
    *,
    scale: float,
) -> tuple[np.ndarray, bool]:
    """Drop the ragged physical paper edge from the residual contour layer."""

    margin = scaled_int(12.0, scale, minimum=8)
    cleaned = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    before = (
        int(np.count_nonzero(cleaned[:margin] == 0))
        + int(np.count_nonzero(cleaned[-margin:] == 0))
        + int(np.count_nonzero(cleaned[:, :margin] == 0))
        + int(np.count_nonzero(cleaned[:, -margin:] == 0))
    )
    cleaned[:margin] = 255
    cleaned[-margin:] = 255
    cleaned[:, :margin] = 255
    cleaned[:, -margin:] = 255
    return cleaned, before > 0


def _box_distance(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    dx = max(
        0,
        max(first_x, second_x)
        - min(first_x + first_width, second_x + second_width),
    )
    dy = max(
        0,
        max(first_y, second_y)
        - min(first_y + first_height, second_y + second_height),
    )
    return hypot(float(dx), float(dy))


def _remove_roots_from_binary(
    binary: np.ndarray,
    paths: tuple[TracePath, ...],
    removed_roots: set[int],
) -> tuple[np.ndarray, np.ndarray]:
    cleaned = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    removed_mask = np.zeros_like(cleaned)
    for root_index in removed_roots:
        points = np.rint(np.asarray(paths[root_index].points, dtype=np.float32)).astype(
            np.int32
        )
        if len(points) >= 3:
            cv2.fillPoly(cleaned, [points], 255)
            cv2.fillPoly(removed_mask, [points], 255)
    return cleaned, removed_mask


def _remove_nearby_damage_fragments(
    gray: np.ndarray,
    binary: np.ndarray,
    damage_mask: np.ndarray,
    scale: float,
) -> np.ndarray:
    """Clear light crack fragments split from the main tear by drawing rules."""

    if not cv2.countNonZero(damage_mask):
        return np.ascontiguousarray(binary)
    corridor_radius = scaled_int(13.0, scale, minimum=10)
    corridor = cv2.dilate(
        damage_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (corridor_radius * 2 + 1, corridor_radius * 2 + 1),
        ),
    )
    foreground = np.where(binary == 0, 1, 0).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        foreground,
        connectivity=8,
    )
    remove_label = np.zeros(count, dtype=bool)
    for label_value in range(1, count):
        x = int(stats[label_value, cv2.CC_STAT_LEFT])
        y = int(stats[label_value, cv2.CC_STAT_TOP])
        width = int(stats[label_value, cv2.CC_STAT_WIDTH])
        height = int(stats[label_value, cv2.CC_STAT_HEIGHT])
        component = labels[y : y + height, x : x + width] == label_value
        area = int(np.count_nonzero(component))
        if area <= 0:
            continue
        overlap = float(
            np.count_nonzero(
                component & (corridor[y : y + height, x : x + width] > 0)
            )
        ) / float(area)
        if overlap < 0.15:
            continue
        median_tone = float(np.median(gray[y : y + height, x : x + width][component]))
        if median_tone >= 125.0:
            remove_label[label_value] = True

    cleaned = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    cleaned[remove_label[labels]] = 255
    return cleaned


def suppress_scan_artifact_traces(
    gray: np.ndarray,
    binary: np.ndarray,
    paths: tuple[TracePath, ...],
) -> ScanArtifactSuppressionResult:
    """Remove fold/tape/tear contours that survived scan normalization.

    This pass is intentionally limited to scanned pages. It removes both direct
    paper-damage roots and nearby high-tone fragments belonging to the same tear.
    Very long, sparse residual contours crossing otherwise empty regions are
    rejected independently because they are the characteristic CAD "flying line"
    left after structural rules have already been reconstructed.
    """

    if (
        gray is None
        or binary is None
        or gray.size == 0
        or binary.size == 0
        or gray.shape != binary.shape
        or not paths
    ):
        return ScanArtifactSuppressionResult(
            binary=np.ascontiguousarray(binary),
            removed_root_count=0,
        )

    scale = image_resolution_scale(binary.shape)
    damage_mask = _bright_damage_mask(gray, scale)
    edge_cleaned_binary, edge_band_removed = _remove_scan_edge_band(
        binary,
        scale=scale,
    )
    working_binary, corner_region_count = _remove_corner_damage_clusters(
        edge_cleaned_binary,
        damage_mask,
        scale,
    )
    prefiltered_region_count = corner_region_count + int(edge_band_removed)
    working_paths = (
        trace_binary(working_binary)
        if prefiltered_region_count
        else paths
    )
    metrics: dict[int, _RootMetrics] = {}
    damage_roots: set[int] = set()
    sparse_roots: set[int] = set()
    for index, path in enumerate(working_paths):
        if path.depth != 0:
            continue
        item = _path_metrics(
            path,
            gray=gray,
            binary=working_binary,
            damage_mask=damage_mask,
            scale=scale,
        )
        if item is None:
            continue
        metrics[index] = item
        if item.edge_damage or item.local_damage:
            damage_roots.add(index)
        if item.long_sparse_flight:
            sparse_roots.add(index)

    # A tear is commonly split at every surviving grid rule. Grow only from
    # direct paper-damage roots; a long sparse flight is removed but must not
    # cause nearby legitimate symbols to be swept into the same cluster.
    clustered_damage = set(damage_roots)
    maximum_gap = scaled_int(38.0, scale, minimum=28)
    minimum_span = scaled_int(8.0, scale, minimum=6)
    for _iteration in range(6):
        additions: set[int] = set()
        for index, item in metrics.items():
            if index in clustered_damage or index in sparse_roots:
                continue
            _x, _y, width, height = item.box
            if (
                max(width, height) < minimum_span
                or item.median_tone < 145.0
                or not (item.solidity <= 0.65 or item.aspect_ratio >= 3.0)
            ):
                continue
            if any(
                _box_distance(item.box, metrics[root_index].box) <= maximum_gap
                for root_index in clustered_damage
            ):
                additions.add(index)
        if not additions:
            break
        clustered_damage.update(additions)

    removed_roots = clustered_damage | sparse_roots
    if not removed_roots:
        return ScanArtifactSuppressionResult(
            binary=working_binary,
            removed_root_count=prefiltered_region_count,
        )
    cleaned, _all_removed_mask = _remove_roots_from_binary(
        working_binary,
        working_paths,
        removed_roots,
    )
    _unused, damage_removed_mask = _remove_roots_from_binary(
        np.full_like(working_binary, 255),
        working_paths,
        clustered_damage,
    )
    cleaned = _remove_nearby_damage_fragments(
        gray,
        cleaned,
        damage_removed_mask,
        scale,
    )
    return ScanArtifactSuppressionResult(
        binary=cleaned,
        removed_root_count=len(removed_roots) + prefiltered_region_count,
    )
