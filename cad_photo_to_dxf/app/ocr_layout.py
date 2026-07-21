from __future__ import annotations

from dataclasses import replace
from math import ceil
from unicodedata import east_asian_width

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate


_TILE_SIZE = 3072
_TILE_OVERLAP = 384


def tile_regions(
    image_shape: tuple[int, int],
    *,
    tile_size: int = _TILE_SIZE,
    overlap: int = _TILE_OVERLAP,
) -> tuple[tuple[int, int, int, int], ...]:
    """Return overlapping native-resolution OCR tiles for large engineering pages."""

    height, width = (int(image_shape[0]), int(image_shape[1]))
    size = max(512, int(tile_size))
    overlap_value = min(size // 3, max(0, int(overlap)))
    if max(height, width) <= 4096:
        return ()
    step = max(256, size - overlap_value)

    def starts(length: int) -> list[int]:
        if length <= size:
            return [0]
        values = list(range(0, max(1, length - size + 1), step))
        final = max(0, length - size)
        if not values or values[-1] != final:
            values.append(final)
        return values

    regions: list[tuple[int, int, int, int]] = []
    for top in starts(height):
        for left in starts(width):
            right = min(width, left + size)
            bottom = min(height, top + size)
            regions.append((left, top, right, bottom))
    return tuple(regions)


def candidate_touches_internal_tile_edge(
    candidate: TextCandidate,
    *,
    tile_region: tuple[int, int, int, int],
    page_shape: tuple[int, int],
    margin: int = 18,
) -> bool:
    """Reject partial lines cut by an internal tile edge before deduplication."""

    left, top, right, bottom = tile_region
    page_height, page_width = page_shape
    x, y, width, height = candidate.bbox
    local_right = x + width
    local_bottom = y + height
    tile_width = right - left
    tile_height = bottom - top
    return bool(
        (left > 0 and x <= margin)
        or (right < page_width and local_right >= tile_width - margin)
        or (top > 0 and y <= margin)
        or (bottom < page_height and local_bottom >= tile_height - margin)
    )


def offset_candidate(
    candidate: TextCandidate,
    *,
    offset_x: int,
    offset_y: int,
    source: str | None = None,
) -> TextCandidate:
    x, y, width, height = candidate.bbox
    quad = None
    if candidate.quad:
        quad = tuple(
            (float(px) + float(offset_x), float(py) + float(offset_y))
            for px, py in candidate.quad
        )
    character_boxes = tuple(
        (cx + int(offset_x), cy + int(offset_y), cw, ch)
        for cx, cy, cw, ch in candidate.character_boxes
    )
    return replace(
        candidate,
        bbox=(x + int(offset_x), y + int(offset_y), width, height),
        quad=quad,
        character_boxes=character_boxes,
        source=source or candidate.source,
    )


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise ValueError("Unsupported OCR layout image")


def _text_mask(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = bbox
    image_height, image_width = image.shape[:2]
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(image_width, int(x + width))
    bottom = min(image_height, int(y + height))
    if right <= left or bottom <= top:
        return np.zeros((1, 1), dtype=np.uint8)
    crop = _gray(image[top:bottom, left:right])
    _threshold, mask = cv2.threshold(
        crop,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    h, w = mask.shape
    horizontal = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, int(w * 0.55)), 1)),
    )
    vertical = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(9, int(h * 0.75)))),
    )
    cleaned = cv2.subtract(mask, cv2.max(horizontal, vertical))
    return cleaned if cv2.countNonZero(cleaned) else mask


def _character_units(character: str) -> float:
    if character.isspace():
        return 0.35
    if east_asian_width(character) in {"W", "F", "A"}:
        return 1.0
    if character in ".,;:'`|!ijlI1()[]{}":
        return 0.34
    return 0.60


def _valley_boundary(
    projection: np.ndarray,
    target: float,
    radius: int,
    minimum: int,
    maximum: int,
) -> int:
    if maximum <= minimum:
        return minimum
    center = int(round(target))
    left = max(minimum, center - radius)
    right = min(maximum, center + radius)
    if right <= left:
        return max(minimum, min(center, maximum))
    values = projection[left : right + 1]
    return int(left + int(np.argmin(values)))


def _horizontal_character_boxes(
    mask: np.ndarray,
    candidate: TextCandidate,
) -> tuple[tuple[tuple[int, int, int, int], ...], bool, str]:
    content = " ".join(candidate.text.replace("\r", " ").replace("\n", " ").split())
    characters = list(content)
    non_space_count = sum(1 for character in characters if not character.isspace())
    if not characters or non_space_count == 0:
        return (), False, "OCR 内容为空"
    if abs(float(candidate.rotation_deg)) > 8.0:
        return (), False, "倾斜或竖排候选需人工确认"

    ink_count = int(cv2.countNonZero(mask))
    if ink_count <= max(4, mask.size // 1000):
        return (), False, "识别框内没有足够原始笔画"

    rows = np.flatnonzero(np.count_nonzero(mask, axis=1))
    columns = np.flatnonzero(np.count_nonzero(mask, axis=0))
    if rows.size == 0 or columns.size == 0:
        return (), False, "识别框内没有可分割笔画"
    ink_top = int(rows[0])
    ink_bottom = int(rows[-1]) + 1
    ink_left = int(columns[0])
    ink_right = int(columns[-1]) + 1
    ink_width = max(1, ink_right - ink_left)

    units = [_character_units(character) for character in characters]
    total_units = max(sum(units), 0.01)
    average_cell = ink_width / max(total_units, 0.01)
    projection = np.count_nonzero(mask, axis=0).astype(np.int32)
    radius = max(2, int(round(average_cell * 0.28)))

    boundaries = [ink_left]
    cumulative = 0.0
    for unit in units[:-1]:
        cumulative += unit
        target = ink_left + ink_width * cumulative / total_units
        boundary = _valley_boundary(
            projection,
            target,
            radius,
            boundaries[-1] + 1,
            ink_right - 1,
        )
        boundaries.append(boundary)
    boundaries.append(ink_right)

    boxes: list[tuple[int, int, int, int]] = []
    visible_segments = 0
    suspicious_wide_component = False
    x0, y0, _bbox_width, _bbox_height = candidate.bbox

    component_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(1, int(round(mask.shape[0] * 0.035))), 1),
    )
    connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, component_kernel)
    component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    if component_count > 1:
        maximum_component_width = int(stats[1:, cv2.CC_STAT_WIDTH].max())
        suspicious_wide_component = bool(
            non_space_count >= 3 and maximum_component_width > average_cell * 2.25
        )

    for index, character in enumerate(characters):
        left = int(boundaries[index])
        right = int(boundaries[index + 1])
        if right <= left:
            right = left + 1
        if character.isspace():
            continue
        segment = mask[ink_top:ink_bottom, left:right]
        segment_columns = np.flatnonzero(np.count_nonzero(segment, axis=0))
        segment_rows = np.flatnonzero(np.count_nonzero(segment, axis=1))
        if segment_columns.size and segment_rows.size:
            visible_segments += 1
            local_left = left + int(segment_columns[0])
            local_right = left + int(segment_columns[-1]) + 1
            local_top = ink_top + int(segment_rows[0])
            local_bottom = ink_top + int(segment_rows[-1]) + 1
        else:
            local_left, local_right = left, right
            local_top, local_bottom = ink_top, ink_bottom
        pad_x = max(1, int(ceil((local_right - local_left) * 0.05)))
        pad_y = max(1, int(ceil((local_bottom - local_top) * 0.06)))
        local_left = max(0, local_left - pad_x)
        local_right = min(mask.shape[1], local_right + pad_x)
        local_top = max(0, local_top - pad_y)
        local_bottom = min(mask.shape[0], local_bottom + pad_y)
        boxes.append(
            (
                x0 + local_left,
                y0 + local_top,
                max(1, local_right - local_left),
                max(1, local_bottom - local_top),
            )
        )

    visible_ratio = visible_segments / max(non_space_count, 1)
    safe = bool(
        len(boxes) == non_space_count
        and visible_ratio >= 0.72
        and not suspicious_wide_component
    )
    if suspicious_wide_component:
        note = "笔画跨越多个字符格，疑似签名、手写体或图形，保留原轮廓等待人工确认"
    elif visible_ratio < 0.72:
        note = "逐字分割覆盖不足，保留原轮廓等待人工确认"
    else:
        note = "已按原始笔画间隔生成逐字定位框"
    return tuple(boxes), safe, note


def prepare_candidate_layout(image: np.ndarray, candidate: TextCandidate) -> TextCandidate:
    """Attach per-character positions and prevent unsafe partial OCR replacement."""

    try:
        mask = _text_mask(image, candidate.bbox)
        character_boxes, safe, note = _horizontal_character_boxes(mask, candidate)
    except (ValueError, cv2.error):
        character_boxes, safe, note = (), False, "无法验证原始笔画覆盖，等待人工确认"
    return replace(
        candidate,
        character_boxes=character_boxes,
        replacement_safe=bool(safe),
        review_note=note,
    )
