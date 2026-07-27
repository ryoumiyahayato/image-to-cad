from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import atan2, degrees, hypot
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .image_loader import save_image


@dataclass(frozen=True)
class SignatureRegion:
    """One handwritten signature retained as a transparent raster overlay."""

    bbox: tuple[int, int, int, int]
    mask: np.ndarray


def _foreground(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Signature source must be a non-empty binary page")
    return np.where(binary < 128, 255, 0).astype(np.uint8)


def _rule_masks(foreground: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = foreground.shape
    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(25, int(round(width * 0.015))), 1),
        ),
    )
    vertical = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(25, int(round(height * 0.015)))),
        ),
    )
    return horizontal, vertical


def _run_centers(values: np.ndarray) -> list[int]:
    positions = np.flatnonzero(values)
    if not positions.size:
        return []
    runs: list[list[int]] = [[int(positions[0])]]
    for position in positions[1:]:
        value = int(position)
        if value <= runs[-1][-1] + 1:
            runs[-1].append(value)
        else:
            runs.append([value])
    return [int(round(sum(run) / len(run))) for run in runs]


def _signature_header(text: str) -> bool:
    compact = "".join(str(text or "").split()).casefold()
    if not compact or len(compact) > 28 or compact.startswith("手写"):
        return False
    return bool(
        compact == "signature"
        or any(term in compact for term in ("签字", "签名", "签署", "盖章"))
    )


_FALLBACK_LABELS = {
    "建筑",
    "结构",
    "给排水",
    "暖通",
    "电气",
    "设计",
    "绘图",
    "审核",
    "审定",
    "校对",
    "日期",
    "图号",
    "阶段",
    "专业",
    "姓名",
    "职责",
    "建设单位",
    "工程名称",
    "项目名称",
    "专业负责人",
    "设计负责人",
}


def _fallback_signature_candidate(
    item: TextCandidate,
    *,
    page_width: int,
    page_height: int,
) -> bool:
    compact = "".join(str(item.text or "").split())
    x, y, width, height = item.bbox
    cjk_count = sum("\u4e00" <= character <= "\u9fff" for character in compact)
    warning = str(item.review_note or "")
    return bool(
        item.kind != "dimension_text_candidate"
        and x + width * 0.5 >= page_width * 0.52
        and y + height * 0.5 >= page_height * 0.72
        and width >= max(page_width * 0.045, height * 1.8)
        and height >= page_height * 0.018
        and 1 <= len(compact) <= 20
        and cjk_count >= 1
        and compact not in _FALLBACK_LABELS
        and float(item.confidence) <= 0.96
        and any(term in warning for term in ("签名", "手写", "连笔", "只覆盖", "图形"))
    )


def _region_from_handwriting_candidate(
    foreground: np.ndarray,
    rules: np.ndarray,
    item: TextCandidate,
) -> SignatureRegion | None:
    page_height, page_width = foreground.shape
    x, y, width, height = item.bbox
    margin_x = max(8, int(round(height * 0.45)))
    margin_y = max(5, int(round(height * 0.20)))
    left = max(0, x - margin_x)
    top = max(0, y - margin_y)
    right = min(page_width, x + width + margin_x)
    bottom = min(page_height, y + height + margin_y)
    if right <= left or bottom <= top:
        return None
    crop = foreground[top:bottom, left:right]
    non_rules = cv2.subtract(crop, rules[top:bottom, left:right])
    connected = cv2.morphologyEx(
        non_rules,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    seed = np.zeros_like(connected)
    seed_top = max(0, y - top)
    seed_left = max(0, x - left)
    seed_bottom = min(seed.shape[0], y + height - top)
    seed_right = min(seed.shape[1], x + width - left)
    seed[seed_top:seed_bottom, seed_left:seed_right] = 255
    selected = np.zeros_like(connected)
    for label_value in range(1, count):
        if int(stats[label_value, cv2.CC_STAT_AREA]) < 3:
            continue
        component = labels == label_value
        if np.any(component & (seed > 0)):
            selected[component] = 255
    if not cv2.countNonZero(selected):
        return None
    support = cv2.dilate(
        selected,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 9)),
        iterations=1,
    )
    recovered = cv2.bitwise_and(non_rules, support)
    recovered = cv2.max(recovered, selected)
    points = cv2.findNonZero(recovered)
    if points is None or len(points) < 20:
        return None
    local_x, local_y, resolved_width, resolved_height = cv2.boundingRect(points)
    pad = 2
    local_left = max(0, local_x - pad)
    local_top = max(0, local_y - pad)
    local_right = min(recovered.shape[1], local_x + resolved_width + pad)
    local_bottom = min(recovered.shape[0], local_y + resolved_height + pad)
    mask = np.ascontiguousarray(
        recovered[local_top:local_bottom, local_left:local_right],
        dtype=np.uint8,
    )
    return SignatureRegion(
        bbox=(
            left + local_left,
            top + local_top,
            mask.shape[1],
            mask.shape[0],
        ),
        mask=mask,
    )


def _fallback_signature_regions(
    foreground: np.ndarray,
    rules: np.ndarray,
    texts: Sequence[TextCandidate],
) -> tuple[SignatureRegion, ...]:
    page_height, page_width = foreground.shape
    results: list[SignatureRegion] = []
    for item in texts:
        if not _fallback_signature_candidate(
            item,
            page_width=page_width,
            page_height=page_height,
        ):
            continue
        region = _region_from_handwriting_candidate(
            foreground,
            rules,
            item,
        )
        if region is None:
            continue
        rx, ry, rw, rh = region.bbox
        overlaps_existing = any(
            max(0, min(rx + rw, ex + ew) - max(rx, ex))
            * max(0, min(ry + rh, ey + eh) - max(ry, ey))
            >= 0.35 * min(rw * rh, ew * eh)
            for ex, ey, ew, eh in (existing.bbox for existing in results)
        )
        if not overlaps_existing:
            results.append(region)
    return tuple(results)


def _nearest_column(
    vertical: np.ndarray,
    header: TextCandidate,
) -> tuple[int, int, list[int]] | None:
    page_height, _page_width = vertical.shape
    x, y, width, height = header.bbox
    center_x = x + width * 0.5
    top = max(0, int(y - height * 4))
    bottom = min(page_height, int(y + height * 22))
    span = vertical[top:bottom]
    minimum = max(8, int(round(max(1, bottom - top) * 0.10)))
    projection = np.count_nonzero(span > 0, axis=0)
    centers = _run_centers(projection >= minimum)
    lefts = [value for value in centers if value < center_x - 2]
    rights = [value for value in centers if value > center_x + 2]
    if not lefts or not rights:
        return None
    left = max(lefts)
    right = min(rights)
    if right - left < max(12, int(round(width * 0.75))):
        return None
    return left, right, centers


def _horizontal_centers(
    horizontal: np.ndarray,
    *,
    left: int,
    right: int,
) -> list[int]:
    if right <= left:
        return []
    span = horizontal[:, left : right + 1]
    minimum = max(5, int(round((right - left + 1) * 0.35)))
    projection = np.count_nonzero(span > 0, axis=1)
    return _run_centers(projection >= minimum)


def _expanded_row_mask(
    foreground: np.ndarray,
    rules: np.ndarray,
    *,
    row_top: int,
    row_bottom: int,
    column_left: int,
    column_right: int,
    vertical_centers: Sequence[int],
) -> SignatureRegion | None:
    left_index = max(
        (index for index, value in enumerate(vertical_centers) if value == column_left),
        default=-1,
    )
    right_index = max(
        (index for index, value in enumerate(vertical_centers) if value == column_right),
        default=-1,
    )
    expanded_left = (
        vertical_centers[left_index - 1]
        if left_index > 0
        else max(0, column_left - (column_right - column_left))
    )
    expanded_right = (
        vertical_centers[right_index + 1]
        if 0 <= right_index < len(vertical_centers) - 1
        else min(foreground.shape[1] - 1, column_right + (column_right - column_left))
    )
    top = max(0, row_top + 1)
    bottom = min(foreground.shape[0], row_bottom)
    left = max(0, expanded_left + 1)
    right = min(foreground.shape[1], expanded_right)
    if bottom <= top or right <= left:
        return None

    crop = foreground[top:bottom, left:right]
    non_rules = cv2.subtract(crop, rules[top:bottom, left:right])
    if not cv2.countNonZero(non_rules):
        return None
    connected = cv2.morphologyEx(
        non_rules,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    seed_left = max(0, column_left - left + 2)
    seed_right = min(connected.shape[1], column_right - left - 1)
    if seed_right <= seed_left:
        return None
    seed = np.zeros_like(connected)
    seed[:, seed_left:seed_right] = 255

    selected = np.zeros_like(connected)
    for label_value in range(1, count):
        area = int(stats[label_value, cv2.CC_STAT_AREA])
        if area < 3:
            continue
        component = labels == label_value
        if np.any(component & (seed > 0)):
            selected[component] = 255
    if not cv2.countNonZero(selected):
        return None

    for _iteration in range(2):
        support = cv2.dilate(
            selected,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 7)),
            iterations=1,
        )
        for label_value in range(1, count):
            component = labels == label_value
            if np.any(component & (support > 0)):
                selected[component] = 255

    support = cv2.dilate(
        selected,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 9)),
        iterations=1,
    )
    recovered = cv2.bitwise_and(crop, support)
    recovered = cv2.max(recovered, selected)
    points = cv2.findNonZero(recovered)
    if points is None or len(points) < 12:
        return None
    local_x, local_y, width, height = cv2.boundingRect(points)
    pad = 2
    local_left = max(0, local_x - pad)
    local_top = max(0, local_y - pad)
    local_right = min(recovered.shape[1], local_x + width + pad)
    local_bottom = min(recovered.shape[0], local_y + height + pad)
    mask = np.ascontiguousarray(
        recovered[local_top:local_bottom, local_left:local_right],
        dtype=np.uint8,
    )
    return SignatureRegion(
        bbox=(
            left + local_left,
            top + local_top,
            mask.shape[1],
            mask.shape[0],
        ),
        mask=mask,
    )


def _freeform_signature_region(
    foreground: np.ndarray,
    rules: np.ndarray,
    header: TextCandidate,
) -> SignatureRegion | None:
    """Recover a signature beside a free-form label without inventing strokes.

    OCR commonly returns ``委托人签名或盖章：`` and the adjacent handwriting as
    one wide box.  Table-column logic cannot resolve that layout, and erasing the
    complete OCR box removes the signature.  This path keeps only source pixels
    to the right of the estimated printed label and never skeletonizes or
    extrapolates them.
    """

    compact = "".join(str(header.text or "").split())
    x, y, width, height = header.bbox
    if (
        len(compact) < 3
        or width < max(24, int(round(height * 2.8)))
        or not _signature_header(compact)
    ):
        return None

    page_height, page_width = foreground.shape
    estimated_label_width = min(
        width * 0.62,
        max(height * 1.5, len(compact) * height * 0.20),
    )
    left = max(0, int(round(x + estimated_label_width)))
    top = max(0, int(round(y - height * 0.12)))
    right = min(
        page_width,
        int(round(x + width + max(height * 0.35, width * 0.08))),
    )
    bottom = min(
        page_height,
        int(round(y + height + max(8.0, height * 0.25))),
    )
    if right <= left or bottom <= top:
        return None

    crop = foreground[top:bottom, left:right]
    non_rules = cv2.subtract(crop, rules[top:bottom, left:right])
    connected = cv2.morphologyEx(
        non_rules,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    selected = np.zeros_like(connected)
    for label_value in range(1, count):
        area = int(stats[label_value, cv2.CC_STAT_AREA])
        component_width = int(stats[label_value, cv2.CC_STAT_WIDTH])
        component_height = int(stats[label_value, cv2.CC_STAT_HEIGHT])
        if area < 4 or max(component_width, component_height) < 3:
            continue
        selected[labels == label_value] = 255
    if cv2.countNonZero(selected) < 16:
        return None

    support = cv2.dilate(
        selected,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 5)),
        iterations=1,
    )
    recovered = cv2.bitwise_and(non_rules, support)
    points = cv2.findNonZero(recovered)
    if points is None or len(points) < 16:
        return None
    local_x, local_y, resolved_width, resolved_height = cv2.boundingRect(points)
    if resolved_width < max(8, int(round(resolved_height * 1.15))):
        return None
    pad = 2
    local_left = max(0, local_x - pad)
    local_top = max(0, local_y - pad)
    local_right = min(recovered.shape[1], local_x + resolved_width + pad)
    local_bottom = min(recovered.shape[0], local_y + resolved_height + pad)
    mask = np.ascontiguousarray(
        recovered[local_top:local_bottom, local_left:local_right],
        dtype=np.uint8,
    )
    return SignatureRegion(
        bbox=(
            left + local_left,
            top + local_top,
            mask.shape[1],
            mask.shape[0],
        ),
        mask=mask,
    )


def detect_signature_regions(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
) -> tuple[SignatureRegion, ...]:
    """Find handwritten rows below a detected title-block signature header."""

    headers = [item for item in texts if _signature_header(item.text)]
    foreground = _foreground(binary)
    horizontal, vertical = _rule_masks(foreground)
    rules = cv2.max(horizontal, vertical)
    results: list[SignatureRegion] = []
    visited_columns: set[tuple[int, int]] = set()

    for header in sorted(headers, key=lambda item: (item.bbox[1], item.bbox[0])):
        result_count_before_header = len(results)
        column = _nearest_column(vertical, header)
        if column is not None:
            left, right, vertical_centers = column
            key = (left, right)
            if key not in visited_columns:
                visited_columns.add(key)
                horizontal_centers = _horizontal_centers(
                    horizontal,
                    left=left,
                    right=right,
                )
                _x, y, _width, height = header.bbox
                header_bottom = y + height
                later_lines = [
                    value
                    for value in horizontal_centers
                    if value > header_bottom - 2
                ]
                if len(later_lines) >= 2:
                    first_boundary = later_lines[0]
                    typical_gap = max(12.0, float(height) * 1.7)
                    previous_gap: float | None = None
                    for row_index in range(min(12, len(later_lines) - 1)):
                        row_top = later_lines[row_index]
                        row_bottom = later_lines[row_index + 1]
                        gap = float(row_bottom - row_top)
                        if row_top < first_boundary or gap <= 4:
                            continue
                        if previous_gap is not None and gap > max(
                            typical_gap * 2.4,
                            previous_gap * 2.4,
                        ):
                            break
                        previous_gap = (
                            gap if previous_gap is None else min(previous_gap, gap)
                        )
                        interior = cv2.subtract(
                            foreground[row_top + 1 : row_bottom, left + 1 : right],
                            rules[row_top + 1 : row_bottom, left + 1 : right],
                        )
                        minimum_ink = max(12, int(round(interior.size * 0.002)))
                        if int(cv2.countNonZero(interior)) < minimum_ink:
                            continue
                        region = _expanded_row_mask(
                            foreground,
                            rules,
                            row_top=row_top,
                            row_bottom=row_bottom,
                            column_left=left,
                            column_right=right,
                            vertical_centers=vertical_centers,
                        )
                        if region is not None:
                            results.append(region)

        if len(results) == result_count_before_header:
            freeform = _freeform_signature_region(
                foreground,
                rules,
                header,
            )
            if freeform is not None:
                results.append(freeform)

    if results:
        return tuple(results)
    return _fallback_signature_regions(
        foreground,
        rules,
        texts,
    )


def mark_signature_texts(
    texts: Sequence[TextCandidate],
    regions: Sequence[SignatureRegion],
) -> tuple[TextCandidate, ...]:
    if not regions:
        return tuple(texts)
    marked: list[TextCandidate] = []
    for item in texts:
        x, y, width, height = item.bbox
        item_area = max(1, width * height)
        overlaps_signature = False
        for region in regions:
            rx, ry, rw, rh = region.bbox
            overlap_width = max(0, min(x + width, rx + rw) - max(x, rx))
            overlap_height = max(0, min(y + height, ry + rh) - max(y, ry))
            if overlap_width * overlap_height / item_area >= 0.20:
                overlaps_signature = True
                break
        if overlaps_signature:
            marked.append(
                replace(
                    item,
                    kind="signature_candidate",
                    approved=False,
                    replacement_safe=False,
                    review_note="已作为完整签名图像保留，不转换为文字",
                )
            )
        else:
            marked.append(item)
    return tuple(marked)


def mark_graphic_texts(
    texts: Sequence[TextCandidate],
    *,
    page_shape: tuple[int, int],
) -> tuple[TextCandidate, ...]:
    """Keep compact connected logo-like OCR boxes as source graphics."""

    page_height, page_width = (int(page_shape[0]), int(page_shape[1]))
    page_area = max(1, page_height * page_width)
    marked: list[TextCandidate] = []
    for item in texts:
        if item.kind == "signature_candidate" or item.replacement_safe:
            marked.append(item)
            continue
        x, y, width, height = item.bbox
        compact = "".join(str(item.text or "").split())
        aspect = width / max(float(height), 1.0)
        sentence_like = any(
            character in compact
            for character in "。！？；，,.!?;"
        )
        suspicious_graphic = bool(
            "图形" in str(item.review_note or "")
            and 1 <= len(compact) <= 24
            and not sentence_like
            and 0.55 <= aspect <= 6.5
            and width * height >= max(36, int(round(page_area * 0.00008)))
            and 0 <= x < page_width
            and 0 <= y < page_height
        )
        if suspicious_graphic:
            marked.append(
                replace(
                    item,
                    kind="graphic_candidate",
                    approved=False,
                    replacement_safe=False,
                    review_note="疑似 Logo、手写或连接图形，保留原始图形轮廓",
                )
            )
        else:
            marked.append(item)
    return tuple(marked)


def suppress_signature_strokes(
    binary: np.ndarray,
    regions: Sequence[SignatureRegion],
) -> np.ndarray:
    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    for region in regions:
        x, y, width, height = region.bbox
        crop = result[y : y + height, x : x + width]
        if crop.shape != region.mask.shape:
            continue
        removal = cv2.dilate(
            np.where(region.mask > 0, 255, 0).astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=1,
        )
        crop[removal > 0] = 255
    return result


def suppress_text_strokes(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
) -> np.ndarray:
    """Remove accepted glyph pixels while restoring table and frame rules."""

    if not texts:
        return np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    foreground = _foreground(binary)
    horizontal, vertical = _rule_masks(foreground)
    rules = cv2.max(horizontal, vertical)
    page_height, page_width = result.shape
    for item in texts:
        if item.kind in {"signature_candidate", "graphic_candidate"}:
            continue
        x, y, width, height = item.bbox
        source_boxes = (
            item.character_boxes
            if item.character_boxes and not item.replacement_safe
            else ((x, y, width, height),)
        )
        for box_x, box_y, box_width, box_height in source_boxes:
            margin_x = max(2, int(round(box_height * 0.08)))
            margin_y = max(2, int(round(box_height * 0.10)))
            left = max(0, box_x - margin_x)
            top = max(0, box_y - margin_y)
            right = min(page_width, box_x + box_width + margin_x)
            bottom = min(page_height, box_y + box_height + margin_y)
            if right <= left or bottom <= top:
                continue
            crop = result[top:bottom, left:right]
            crop[:] = 255
            crop[rules[top:bottom, left:right] > 0] = 0
    return result


def signature_rgba(region: SignatureRegion) -> np.ndarray:
    """Keep the thresholded source footprint instead of reducing it to roots."""

    alpha = np.where(region.mask > 0, 255, 0).astype(np.uint8)
    image = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    image[:, :, 0] = 255
    image[:, :, 2] = 255
    image[:, :, 3] = alpha
    return image


def add_signature_images(
    doc,
    layout,
    regions: Sequence[SignatureRegion],
    *,
    transform: Callable[[float, float], tuple[float, float]],
    output_path: str | Path,
    layer_name: str = "SIGNATURE_OVERLAY",
    name_prefix: str = "SIGNATURE",
) -> tuple[tuple[Path, ...], list[object], list[tuple[float, float]]]:
    """Write signatures beside the DXF and place each as a transparent top image."""

    dxf_path = Path(output_path).resolve()
    for stale_path in dxf_path.parent.glob(
        f"{dxf_path.stem}.signature-*.png"
    ):
        stale_path.unlink(missing_ok=True)
    image_paths: list[Path] = []
    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    for index, region in enumerate(regions, start=1):
        x, y, width, height = region.bbox
        if width <= 0 or height <= 0 or region.mask.shape != (height, width):
            continue
        image_path = dxf_path.with_name(
            f"{dxf_path.stem}.signature-{index:03d}.png"
        )
        save_image(image_path, signature_rgba(region))
        image_paths.append(image_path)
        image_def = doc.add_image_def(
            filename=image_path.name,
            size_in_pixel=(width, height),
            name=f"{name_prefix}_{index:03d}",
        )
        bottom_left = transform(float(x), float(y + height))
        bottom_right = transform(float(x + width), float(y + height))
        top_left = transform(float(x), float(y))
        width_units = hypot(
            bottom_right[0] - bottom_left[0],
            bottom_right[1] - bottom_left[1],
        )
        height_units = hypot(
            top_left[0] - bottom_left[0],
            top_left[1] - bottom_left[1],
        )
        if width_units <= 0.0 or height_units <= 0.0:
            continue
        entity = layout.add_image(
            image_def=image_def,
            insert=bottom_left,
            size_in_units=(width_units, height_units),
            rotation=degrees(
                atan2(
                    bottom_right[1] - bottom_left[1],
                    bottom_right[0] - bottom_left[0],
                )
            ),
            dxfattribs={"layer": layer_name},
        )
        entity.dxf.flags = int(entity.dxf.flags) | 8
        entities.append(entity)
        bounds.extend((bottom_left, bottom_right, top_left))
    return tuple(image_paths), entities, bounds


def set_foreground_draw_order(layout, entities: Sequence[object]) -> None:
    handles = [
        str(entity.dxf.handle)
        for entity in entities
        if getattr(getattr(entity, "dxf", None), "handle", None)
    ]
    if handles:
        layout.set_redraw_order((handle, "0") for handle in handles)
