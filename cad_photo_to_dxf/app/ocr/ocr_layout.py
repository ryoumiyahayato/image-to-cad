from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import ceil
from unicodedata import east_asian_width

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.structural_roi import verified_structural_rule_masks


_TILE_SIZE = 3072
_TILE_OVERLAP = 384


@dataclass(frozen=True)
class VerifiedCellTextSource:
    """Exact source cores in a bounded cell or independent row group."""

    bounds: tuple[int, int, int, int]
    mask: np.ndarray
    texts: tuple[TextCandidate, ...]
    row_masks: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class LayoutRuleSource:
    """Observed rule ink, including glyph contacts, outside TEXT authority.

    The mask is not a new LINE or an exclusive physical-stroke assignment.
    It keeps the original pixels for the existing visible contour fallback.
    """

    bounds: tuple[int, int, int, int]
    mask: np.ndarray
    text: TextCandidate
    body_free_columns: int
    layout_excluded_pixels: int


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
    if max(height, width) <= size:
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


def _remove_long_rules(mask: np.ndarray) -> np.ndarray:
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


def verified_layout_rule_sources(
    image: np.ndarray,
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
) -> tuple[LayoutRuleSource, ...]:
    """Retain a simple bottom rule excluded from the character-layout proof.

    A long opening is only a seed. Source cross-sections in columns with no
    glyph body must independently establish a thin rule band. Contacts in that
    band stay visible; the rest of each glyph remains native TEXT. No source
    pixel is added, extended, or attributed from a fitted line. Middle rules,
    vertical rules, truncated boxes and ambiguous profiles are not handled.
    Work is bounded to OCR crops, with no page scan per candidate.
    """
    if image.shape[:2] != binary.shape:
        raise ValueError("Layout and suppression must use the same source pixels")
    from app.ocr.text_output_contract import accepted_ocr_texts

    output = []
    remaining_pixels = 1_000_000
    # Native TEXT emission and glyph-outline replacement are separate contracts.
    # An unsafe glyph carrier can still have an independently proved rule that
    # must remain visible outside its hidden SOURCE_TEXT_OUTLINE backup.
    eligible = sorted(
        accepted_ocr_texts(texts),
        key=lambda t: (t.bbox, t.text, t.rotation_deg, t.character_boxes),
    )
    for text in eligible:
        x, y, w, h = text.bbox
        if (
            text.reviewed
            or abs(text.rotation_deg) > 8
            or len(text.character_boxes) < 3
            or x < 0
            or y < 0
            or x + w > binary.shape[1]
            or y + h > binary.shape[0]
            or min(w, h) <= 0
            or w * h > min(65_536, remaining_pixels)
        ):
            continue
        remaining_pixels -= w * h
        crop = _gray(image[y : y + h, x : x + w])
        _threshold, raw = cv2.threshold(
            crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
        )
        cleaned = _remove_long_rules(raw)
        excluded = cv2.subtract(raw, cleaned)
        if not np.any(excluded):
            continue
        # Use the actual layout exclusion, not arbitrary horizontal glyph bars.
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            excluded, connectivity=8
        )
        seeds = [
            i
            for i in range(1, count)
            if stats[i, cv2.CC_STAT_WIDTH] >= max(9, int(w * 0.55))
        ]
        if len(seeds) != 1:
            continue
        sx, sy, sw, sh, _ = (int(v) for v in stats[seeds[0]])
        source = binary[y : y + h, x : x + w] < 128
        seed = labels == seeds[0]
        if np.any(seed & ~source):
            continue
        # Local Otsu can break a rule's weak shoulder while prepared source
        # still supports it. Follow only the uninterrupted observed row, never
        # bridge paper or extrapolate a fitted line across the glyph carrier.
        for row in range(sy, sy + sh):
            columns = np.flatnonzero(seed[row])
            if not len(columns):
                continue
            left, right = int(columns[0]), int(columns[-1]) + 1
            while left > 0 and source[row, left - 1]:
                left -= 1
            while right < w and source[row, right]:
                right += 1
            seed[row, left:right] = True
        _seed_rows, seed_columns = np.nonzero(seed)
        sx, sw = int(seed_columns.min()), int(np.ptp(seed_columns)) + 1
        rows = np.flatnonzero(np.any(raw, axis=1))
        if not rows.size:
            continue
        ink_height = int(rows[-1] - rows[0] + 1)
        maximum_width = max(2, int(ceil(ink_height * 0.12)))
        if sh > maximum_width or sy < rows[0] + ink_height * 0.65:
            continue
        crossed = sum(
            cx < x + sx + sw and cx + cw > x + sx
            for cx, _cy, cw, _ch in text.character_boxes
        )
        if crossed < 3:
            continue
        top, bottom = max(0, sy - maximum_width), min(h, sy + sh + maximum_width)
        body = raw.copy()
        body[top:bottom] = 0
        free = np.flatnonzero(~np.any(body[:, sx : sx + sw], axis=0)) + sx
        if len(free) < max(3, int(ceil(sw * 0.03))) or np.ptp(free) < sw * 0.25:
            continue
        profiles = []
        for column in free:
            on_seed = np.flatnonzero(seed[:, column])
            if not len(on_seed):
                continue
            first, last = int(on_seed[0]), int(on_seed[-1]) + 1
            while first > top and source[first - 1, column]:
                first -= 1
            while last < bottom and source[last, column]:
                last += 1
            if first == top or last == bottom or last - first > maximum_width:
                profiles = []
                break
            profiles.append((first, last))
        if len(profiles) < max(3, int(ceil(sw * 0.03))):
            continue
        band_top = min(a for a, _b in profiles)
        band_bottom = max(b for _a, b in profiles)
        if band_bottom - band_top > maximum_width:
            continue
        retained = np.zeros_like(raw)
        # Only observed ink in the measured band survives. Short aligned end
        # pieces may be separated by real paper; that paper is never bridged.
        band = source[band_top:band_bottom].astype(np.uint8)
        n, band_labels, band_stats, _ = cv2.connectedComponentsWithStats(
            band, connectivity=8
        )
        for label in range(1, n):
            if band_stats[label, cv2.CC_STAT_WIDTH] >= max(
                3, int(ceil(ink_height * 0.2))
            ):
                retained[band_top:band_bottom][band_labels == label] = 255
        if not np.any(retained):
            continue
        output.append(
            LayoutRuleSource(
                (x, y, x + w, y + h),
                retained,
                text,
                len(profiles),
                int(cv2.countNonZero(excluded)),
            )
        )
    return tuple(output)


def _binary_crop(image: np.ndarray, bounds: tuple[int, int, int, int]) -> np.ndarray:
    left, top, right, bottom = bounds
    crop = _gray(image[top:bottom, left:right])
    _threshold, mask = cv2.threshold(
        crop,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    return _remove_long_rules(mask)


def _text_mask(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = bbox
    image_height, image_width = image.shape[:2]
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(image_width, int(x + width))
    bottom = min(image_height, int(y + height))
    if right <= left or bottom <= top:
        return np.zeros((1, 1), dtype=np.uint8)
    return _binary_crop(image, (left, top, right, bottom))


def _crosses_candidate_boundary(
    image: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> bool:
    """Detect a text box that captures only part of a larger connected stroke."""

    x, y, width, height = bbox
    image_height, image_width = image.shape[:2]
    margin_x = max(6, int(round(max(width * 0.08, height * 0.40))))
    margin_y = max(6, int(round(height * 0.45)))
    left = max(0, int(x) - margin_x)
    top = max(0, int(y) - margin_y)
    right = min(image_width, int(x + width) + margin_x)
    bottom = min(image_height, int(y + height) + margin_y)
    if right <= left or bottom <= top:
        return False

    expanded = _binary_crop(image, (left, top, right, bottom))
    inner_left = max(0, int(x) - left)
    inner_top = max(0, int(y) - top)
    inner_right = min(expanded.shape[1], int(x + width) - left)
    inner_bottom = min(expanded.shape[0], int(y + height) - top)
    if inner_right <= inner_left or inner_bottom <= inner_top:
        return False

    foreground = np.where(expanded > 0, 255, 0).astype(np.uint8)
    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        foreground,
        connectivity=8,
    )
    if component_count <= 1:
        return False

    inner_labels = labels[inner_top:inner_bottom, inner_left:inner_right]
    minimum_extension_x = max(3, int(round(height * 0.16)))
    minimum_extension_y = max(3, int(round(height * 0.14)))
    for label_value in np.unique(inner_labels):
        if label_value <= 0:
            continue
        inside_count = int(np.count_nonzero(inner_labels == label_value))
        if inside_count < max(5, int(height * 0.12)):
            continue
        component_left = int(stats[label_value, cv2.CC_STAT_LEFT])
        component_top = int(stats[label_value, cv2.CC_STAT_TOP])
        component_right = component_left + int(stats[label_value, cv2.CC_STAT_WIDTH])
        component_bottom = component_top + int(stats[label_value, cv2.CC_STAT_HEIGHT])
        extends = bool(
            component_left < inner_left - minimum_extension_x
            or component_right > inner_right + minimum_extension_x
            or component_top < inner_top - minimum_extension_y
            or component_bottom > inner_bottom + minimum_extension_y
        )
        if not extends:
            continue
        total_count = int(stats[label_value, cv2.CC_STAT_AREA])
        outside_count = max(0, total_count - inside_count)
        if outside_count >= max(5, int(round(inside_count * 0.12))):
            return True
    return False


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
    *,
    verified_line: bool = False,
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

    connected = np.ascontiguousarray(mask)
    component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    if component_count > 1:
        maximum_component_width = int(stats[1:, cv2.CC_STAT_WIDTH].max())
        suspicious_wide_component = bool(
            non_space_count >= 2 and maximum_component_width > average_cell * 2.25
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
        and (not suspicious_wide_component or verified_line)
    )
    if suspicious_wide_component and verified_line:
        note = "英文连笔已由完整文字行源归属验证，不要求逐字断开"
    elif suspicious_wide_component:
        note = "笔画跨越多个字符格或相邻图形，保留原轮廓等待人工确认"
    elif visible_ratio < 0.72:
        note = "逐字分割覆盖不足，保留原轮廓等待人工确认"
    else:
        note = "已按原始笔画间隔生成逐字定位框"
    return tuple(boxes), safe, note


def prepare_candidate_layout(
    image: np.ndarray, candidate: TextCandidate, *, verified_line: bool = False
) -> TextCandidate:
    """Attach per-character positions and prevent unsafe partial OCR replacement."""

    try:
        mask = _text_mask(image, candidate.bbox)
        character_boxes, safe, note = _horizontal_character_boxes(
            mask, candidate, verified_line=verified_line
        )
        if _crosses_candidate_boundary(image, candidate.bbox):
            safe = False
            note = "识别框只覆盖了更大连通笔画的一部分，保留完整原轮廓等待人工确认"
    except (ValueError, cv2.error):
        character_boxes, safe, note = (), False, "无法验证原始笔画覆盖，等待人工确认"
    quad = candidate.quad
    # Detection boxes include recognition padding. Fitting a Chinese line to
    # that padding stretches its height and compresses its glyphs horizontally.
    # Keep the OCR bbox for ownership; only tighten the display quad when the
    # existing source-coverage checks confirm a horizontal printed line.
    content = "".join(candidate.text.split())
    horizontal_quad = quad is None or (
        len(quad) == 4
        and all(
            abs(quad[a][axis] - quad[b][axis]) <= 0.5
            for a, b, axis in ((0, 1, 1), (2, 3, 1), (0, 3, 0), (1, 2, 0))
        )
    )
    if (
        safe
        and not candidate.reviewed
        and len(content) >= 2
        and any("\u4e00" <= char <= "\u9fff" for char in content)
        and abs(candidate.rotation_deg) <= 0.5
        and horizontal_quad
    ):
        rows, columns = np.nonzero(mask)
        x, y, width, height = candidate.bbox
        # One source pixel accommodates edge antialiasing; the resulting quad
        # stays inside the OCR box and any preceding table-cell constraint.
        left = x + max(0, int(columns.min()) - 1)
        right = x + min(width, int(columns.max()) + 2)
        top = y + max(0, int(rows.min()) - 1)
        bottom = y + min(height, int(rows.max()) + 2)
        quad = (
            (float(left), float(top)),
            (float(right), float(top)),
            (float(right), float(bottom)),
            (float(left), float(bottom)),
        )
        note += "；文字显示框已按源墨迹范围定位"
    return replace(
        candidate,
        quad=quad,
        character_boxes=character_boxes,
        replacement_safe=bool(safe),
        review_note=note,
    )


def _projection_centers(values: np.ndarray) -> tuple[int, ...]:
    positions = np.flatnonzero(values)
    if not positions.size:
        return ()
    runs: list[list[int]] = [[int(positions[0])]]
    for raw_value in positions[1:]:
        value = int(raw_value)
        if value <= runs[-1][-1] + 1:
            runs[-1].append(value)
        else:
            runs.append([value])
    return tuple(int(round(sum(run) / len(run))) for run in runs)


def _supporting_rule_centers(
    mask: np.ndarray,
    centers: Sequence[int],
    *,
    orientation: str,
    candidate_bbox: tuple[int, int, int, int],
) -> tuple[int, ...]:
    """Reject glyph strokes that survived morphology as apparent cell rules."""

    x, y, width, height = candidate_bbox
    anchor = y + height * 0.5 if orientation == "vertical" else x + width * 0.5
    candidate_start = y if orientation == "vertical" else x
    candidate_end = y + height if orientation == "vertical" else x + width
    ratio = 1.55 if orientation == "vertical" else 1.25
    minimum_span = max(
        25,
        int(round((height if orientation == "vertical" else width) * ratio)),
    )
    supported: list[int] = []
    for center in centers:
        if orientation == "vertical":
            left = max(0, int(center) - 2)
            right = min(mask.shape[1], int(center) + 3)
            values = np.flatnonzero(np.any(mask[:, left:right] > 0, axis=1))
        else:
            top = max(0, int(center) - 2)
            bottom = min(mask.shape[0], int(center) + 3)
            values = np.flatnonzero(np.any(mask[top:bottom, :] > 0, axis=0))
        if not values.size:
            continue
        runs: list[list[int]] = [[int(values[0])]]
        for raw_value in values[1:]:
            value = int(raw_value)
            if value <= runs[-1][-1] + 3:
                runs[-1].append(value)
            else:
                runs.append([value])
        relevant = [
            run
            for run in runs
            if run[-1] >= candidate_start and run[0] <= candidate_end
        ]
        if not relevant:
            relevant = [
                min(runs, key=lambda run: abs((run[0] + run[-1]) * 0.5 - anchor))
            ]
        span = max(run[-1] - run[0] + 1 for run in relevant)
        if span >= minimum_span:
            supported.append(int(center))
    return tuple(supported)


def constrain_texts_to_table_cells(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
    *,
    verified_sources: list[VerifiedCellTextSource] | None = None,
    display_cells: dict | None = None,
) -> tuple[TextCandidate, ...]:
    """Clip OCR placement boxes to enclosing ruled cells when all sides exist."""

    if binary.ndim != 2 or binary.size == 0 or not texts:
        return tuple(texts)
    page_height, page_width = binary.shape
    foreground = np.where(binary < 128, 255, 0).astype(np.uint8)
    horizontal, vertical = verified_structural_rule_masks(foreground)

    constrained: list[TextCandidate] = []
    cell_groups: dict[tuple[int, int, int, int], list[int]] = {}
    for item in texts:
        if item.kind not in {"text_candidate", "dimension_text_candidate"}:
            constrained.append(item)
            continue
        x, y, width, height = item.bbox
        center_x = x + width * 0.5
        center_y = y + height * 0.5
        band_top = max(0, int(round(y - height * 0.30)))
        band_bottom = min(page_height, int(round(y + height * 1.30)))
        band_left = max(0, int(round(x - height * 0.80)))
        band_right = min(page_width, int(round(x + width + height * 0.80)))
        if band_bottom <= band_top or band_right <= band_left:
            constrained.append(item)
            continue

        vertical_projection = np.count_nonzero(
            vertical[band_top:band_bottom] > 0,
            axis=0,
        )
        vertical_centers = _projection_centers(
            vertical_projection >= max(4, int(round((band_bottom - band_top) * 0.45)))
        )
        vertical_centers = _supporting_rule_centers(
            vertical,
            vertical_centers,
            orientation="vertical",
            candidate_bbox=item.bbox,
        )
        horizontal_projection = np.count_nonzero(
            horizontal[:, band_left:band_right] > 0,
            axis=1,
        )
        horizontal_centers = _projection_centers(
            horizontal_projection >= max(4, int(round((band_right - band_left) * 0.45)))
        )
        horizontal_centers = _supporting_rule_centers(
            horizontal,
            horizontal_centers,
            orientation="horizontal",
            candidate_bbox=item.bbox,
        )
        lefts = [value for value in vertical_centers if value < center_x]
        rights = [value for value in vertical_centers if value > center_x]
        tops = [value for value in horizontal_centers if value < center_y]
        bottoms = [value for value in horizontal_centers if value > center_y]
        if not lefts or not rights or not tops or not bottoms:
            constrained.append(item)
            continue

        cell_left = max(lefts) + 2
        cell_right = min(rights) - 1
        cell_top = max(tops) + 2
        cell_bottom = min(bottoms) - 1
        cell_groups.setdefault(
            (cell_left, cell_top, cell_right, cell_bottom), []
        ).append(len(constrained))
        new_left = max(x, cell_left)
        new_top = max(y, cell_top)
        new_right = min(x + width, cell_right)
        new_bottom = min(y + height, cell_bottom)
        new_width = new_right - new_left
        new_height = new_bottom - new_top
        if new_width <= 1 or new_height <= 1:
            constrained.append(item)
            continue
        if (new_left, new_top, new_width, new_height) == item.bbox:
            constrained.append(item)
            continue
        display_quad = (
            (float(new_left), float(new_top)),
            (float(new_right), float(new_top)),
            (float(new_right), float(new_bottom)),
            (float(new_left), float(new_bottom)),
        )
        if item.quad and all(
            abs(item.quad[a][axis] - item.quad[b][axis]) <= 0.5
            for a, b, axis in ((0, 1, 1), (2, 3, 1), (0, 3, 0), (1, 2, 0))
        ):
            left, top = max(new_left, item.quad[0][0]), max(new_top, item.quad[0][1])
            right, bottom = (
                min(new_right, item.quad[2][0]),
                min(new_bottom, item.quad[2][1]),
            )
            if right > left and bottom > top:
                display_quad = (
                    (float(left), float(top)),
                    (float(right), float(top)),
                    (float(right), float(bottom)),
                    (float(left), float(bottom)),
                )
        clipped_character_boxes: list[tuple[int, int, int, int]] = []
        for box_x, box_y, box_width, box_height in item.character_boxes:
            clipped_left = max(box_x, cell_left)
            clipped_top = max(box_y, cell_top)
            clipped_right = min(box_x + box_width, cell_right)
            clipped_bottom = min(box_y + box_height, cell_bottom)
            if clipped_right > clipped_left and clipped_bottom > clipped_top:
                clipped_character_boxes.append(
                    (
                        clipped_left,
                        clipped_top,
                        clipped_right - clipped_left,
                        clipped_bottom - clipped_top,
                    )
                )
        constrained.append(
            replace(
                item,
                bbox=(new_left, new_top, new_width, new_height),
                quad=display_quad,
                character_boxes=tuple(clipped_character_boxes),
                review_note=(f"{item.review_note}；" if item.review_note else "")
                + "文字位置已限制在检测到的表格单元格内",
            )
        )
    for cell, indexes in cell_groups.items():
        restored = _restore_cell_text_rows(
            binary,
            tuple(constrained[index] for index in indexes),
            cell,
            verified_sources=verified_sources,
        )
        for index, item in zip(indexes, restored, strict=True):
            constrained[index] = item
        if display_cells is not None and len(indexes) == 1:
            item = constrained[indexes[0]]
            display_cells[(item.text, item.bbox)] = cell
    return _restore_overlapping_printed_rows(
        binary, tuple(constrained), verified_sources=verified_sources
    )


def _restore_overlapping_printed_rows(
    gray: np.ndarray,
    texts: tuple[TextCandidate, ...],
    *,
    verified_sources: list[VerifiedCellTextSource] | None = None,
) -> tuple[TextCandidate, ...]:
    """Use the existing complete-component proof for overlapping ASCII rows.

    Boxes only locate small neighborhoods. Every source component must still
    have a unique row owner; shared rules, truncated strokes and connected rows
    leave the original candidates intact. No line spacing is manufactured.
    """
    eligible = sorted(
        (
            index
            for index, item in enumerate(texts)
            if not item.reviewed
            and abs(item.rotation_deg) <= 0.5
            and item.text.isascii()
            and sum(char.isalpha() for char in item.text) >= 2
        ),
        key=lambda index: (
            texts[index].bbox[1],
            texts[index].bbox[0],
            texts[index].text,
        ),
    )
    neighbors = {index: set() for index in eligible}
    for position, index in enumerate(eligible):
        x, y, width, height = texts[index].bbox
        for other in eligible[position + 1 :]:
            bx, by, bw, bh = texts[other].bbox
            if by >= y + height:
                break
            overlap = min(x + width, bx + bw) - max(x, bx)
            if (
                overlap >= min(width, bw) * 0.65
                and abs((y + height * 0.5) - (by + bh * 0.5)) >= min(height, bh) * 0.35
            ):
                neighbors[index].add(other)
                neighbors[other].add(index)
    result = list(texts)
    visited: set[int] = set()
    for index in eligible:
        if index in visited or not neighbors[index]:
            continue
        pending, group = [index], set()
        while pending:
            current = pending.pop()
            if current in group:
                continue
            group.add(current)
            pending.extend(neighbors[current] - group)
        visited.update(group)
        if not 2 <= len(group) <= 6:
            continue
        indexes = sorted(
            group, key=lambda value: (texts[value].bbox[1], texts[value].bbox[0])
        )
        rows = tuple(texts[value] for value in indexes)
        margin = max(4, int(round(max(item.bbox[3] for item in rows) * 0.3)))
        bounds = (
            max(0, min(item.bbox[0] for item in rows) - margin),
            max(0, min(item.bbox[1] for item in rows) - margin),
            min(
                gray.shape[1],
                max(item.bbox[0] + item.bbox[2] for item in rows) + margin,
            ),
            min(
                gray.shape[0],
                max(item.bbox[1] + item.bbox[3] for item in rows) + margin,
            ),
        )
        restored = _restore_cell_text_rows(
            gray, rows, bounds, verified_sources=verified_sources, source_group=True
        )
        for value, item in zip(indexes, restored, strict=True):
            result[value] = item
    return tuple(result)


def _restore_cell_text_rows(
    binary: np.ndarray,
    texts: tuple[TextCandidate, ...],
    cell: tuple[int, int, int, int],
    *,
    verified_sources: list[VerifiedCellTextSource] | None = None,
    source_group: bool = False,
) -> tuple[TextCandidate, ...]:
    """Recover overlapping detection boxes from disjoint source strokes.

    The bounds come from an enclosing cell or a local printed-row group. No
    line spacing is invented and connected strokes are never split between
    rows. Uncertain character coverage retains the source-outline protection.
    """
    if not 2 <= len(texts) <= 6 or any(
        item.reviewed
        or abs(item.rotation_deg) > 0.5
        or len(item.text.strip()) < 2
        or (
            not source_group
            and item.quad
            and not all(
                abs(item.quad[a][axis] - item.quad[b][axis]) <= 0.5
                for a, b, axis in ((0, 1, 1), (2, 3, 1), (0, 3, 0), (1, 2, 0))
            )
        )
        for item in texts
    ):
        return texts
    if not source_group and not (
        any(any("\u4e00" <= char <= "\u9fff" for char in item.text) for item in texts)
        and any(
            item.text.isascii() and any(char.isalpha() for char in item.text)
            for item in texts
        )
    ):
        return texts
    if source_group and any(
        item.quad
        and (
            item.quad[1][0] <= item.quad[0][0]
            or item.quad[2][0] <= item.quad[3][0]
            or item.quad[3][1] <= item.quad[0][1]
        )
        for item in texts
    ):
        return texts
    if not any(
        max(a.bbox[0], b.bbox[0]) < min(a.bbox[0] + a.bbox[2], b.bbox[0] + b.bbox[2])
        and max(a.bbox[1], b.bbox[1])
        < min(a.bbox[1] + a.bbox[3], b.bbox[1] + b.bbox[3])
        for i, a in enumerate(texts)
        for b in texts[i + 1 :]
    ):
        return texts
    left, top, right, bottom = cell
    if right <= left or bottom <= top or (right - left) * (bottom - top) > 65536:
        return texts
    crop = binary[top:bottom, left:right]
    foreground = np.where(crop < 128, 255, 0).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    centers = [item.bbox[1] + item.bbox[3] * 0.5 for item in texts]
    owners: list[list[int]] = [[] for _ in texts]
    for label in range(1, count):
        x, y, width, height, _area = (int(value) for value in stats[label])
        # A narrow boundary rule may survive the existing cell inset. Do not
        # treat it as text; attached interior strokes make the cell uncertain.
        at_side = x == 0 or x + width == foreground.shape[1]
        if (
            not source_group
            and at_side
            and width <= 3
            and height >= foreground.shape[0] * 0.8
        ):
            continue
        if (
            x == 0
            or y == 0
            or x + width == foreground.shape[1]
            or y + height == foreground.shape[0]
        ):
            return texts
        center_y = top + y + height * 0.5
        distances = sorted(
            (abs(center_y - center), index) for index, center in enumerate(centers)
        )
        distance, index = distances[0]
        item = texts[index]
        bx, by, bw, bh = item.bbox
        if (
            distances[1][0] - distance < max(1.0, bh * 0.1)
            or distance > bh * 0.75
            or left + x < bx - bh * 1.5
            or left + x + width > bx + bw + bh * 1.5
            or any(
                top + y <= center <= top + y + height
                for other, center in enumerate(centers)
                if other != index
            )
        ):
            return texts
        owners[index].append(label)
    if any(len(group) < 2 for group in owners):
        return texts

    # Validate each row against its own complete connected components. Other
    # rows are excluded only after every interior component has a unique owner.
    from app.ocr.ocr_fast import prepare_safe_candidate

    restored: list[TextCandidate] = []
    row_bounds: list[tuple[int, int, int, int]] = []
    row_masks: list[np.ndarray] = []
    for item, group in zip(texts, owners, strict=True):
        owned = np.isin(labels, group)
        row_masks.append(np.where(owned, 255, 0).astype(np.uint8))
        ys, xs = np.nonzero(owned)
        x, y = left + int(xs.min()), top + int(ys.min())
        width, height = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        row_bounds.append((x, y, x + width, y + height))
        # A cell-size crop keeps the existing safety checks local and retains
        # the original source pixels, without removing anything from the page.
        isolated = np.full(crop.shape, 255, dtype=np.uint8)
        isolated[owned] = crop[owned]
        local = replace(
            item,
            bbox=(x - left, y - top, width, height),
            quad=(
                (x - left, y - top),
                (x + width - left, y - top),
                (x + width - left, y + height - top),
                (x - left, y + height - top),
            ),
            character_boxes=(),
        )
        # Only this complete-cell component proof may relax the connected-word
        # test. Coverage, cross-boundary and handwriting checks remain active.
        joined_printed_line = (
            verified_sources is not None
            and item.text.isascii()
            and (
                all(char.isalpha() or char.isspace() for char in item.text)
                or (source_group and item.text.isprintable())
            )
        )
        checked = offset_candidate(
            prepare_safe_candidate(isolated, local, verified_line=joined_printed_line),
            offset_x=left,
            offset_y=top,
        )
        # Line placement can be known even when per-character replacement is
        # unsafe (e.g. touching English letters). Keep that protection intact.
        display_quad = checked.quad
        if source_group:
            # Preserve the ordered reading basis, including the scan's slight
            # slope. Fit actual source pixel footprints in that local basis.
            direction = (
                (
                    np.array(item.quad[1])
                    - item.quad[0]
                    + np.array(item.quad[2])
                    - item.quad[3]
                )
                if item.quad
                else np.array([1.0, 0.0])
            )
            along = direction / np.linalg.norm(direction)
            across = np.array([-along[1], along[0]])
            pixels = np.column_stack((xs + left + 0.5, ys + top + 0.5))
            u, v = pixels @ along, pixels @ across
            pad = (abs(along[0]) + abs(along[1])) * 0.5
            u0, u1, v0, v1 = u.min() - pad, u.max() + pad, v.min() - pad, v.max() + pad
            display_quad = tuple(
                tuple(map(float, along * a + across * b))
                for a, b in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
            )
        restored.append(
            replace(
                item,
                quad=display_quad,
                character_boxes=checked.character_boxes
                if checked.replacement_safe
                else item.character_boxes,
                replacement_safe=checked.replacement_safe,
                review_note=checked.review_note
                + (
                    "；已按独立源笔画恢复文字行显示范围"
                    if source_group
                    else "；已按同单元格独立源笔画恢复文字行显示范围"
                ),
            )
        )
    # Preserve source-supported ordering, including genuine ascender/descender
    # overlap. Never use a uniform gap or move a table rule.
    order = sorted(range(len(texts)), key=lambda index: centers[index])
    if any(
        row_bounds[a][1] >= row_bounds[b][1] or row_bounds[a][3] >= row_bounds[b][3]
        for a, b in zip(order, order[1:])
    ):
        return texts
    if verified_sources is not None and all(item.replacement_safe for item in restored):
        from app.ocr.text_output_contract import accepted_ocr_texts

        if len(accepted_ocr_texts(restored)) == len(restored):
            core = np.where(
                np.isin(labels, [label for group in owners for label in group]), 255, 0
            ).astype(np.uint8)
            verified_sources.append(
                VerifiedCellTextSource(cell, core, tuple(restored), tuple(row_masks))
            )
    return tuple(restored)
