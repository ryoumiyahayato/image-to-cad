from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from math import hypot

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_layout import (
    candidate_touches_internal_tile_edge,
    prepare_candidate_layout,
    tile_regions,
)
from .ocr_recognition import _recognize_rapidocr_pass


OVERVIEW_MAX_SIDE = 4096
TILE_SIZE = 4096
TILE_OVERLAP = 512
MAX_CANDIDATES = 3000


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise ValueError("Unsupported OCR image")


def _bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3 and image.shape[2] == 3:
        return np.ascontiguousarray(image)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    raise ValueError("Unsupported OCR image")


def _scaled_candidate(
    candidate: TextCandidate,
    *,
    scale_x: float,
    scale_y: float,
    source: str,
) -> TextCandidate:
    x, y, width, height = candidate.bbox
    quad = None
    if candidate.quad:
        quad = tuple(
            (float(px) * scale_x, float(py) * scale_y)
            for px, py in candidate.quad
        )
    boxes = tuple(
        (
            int(round(cx * scale_x)),
            int(round(cy * scale_y)),
            max(1, int(round(cw * scale_x))),
            max(1, int(round(ch * scale_y))),
        )
        for cx, cy, cw, ch in candidate.character_boxes
    )
    return replace(
        candidate,
        bbox=(
            int(round(x * scale_x)),
            int(round(y * scale_y)),
            max(1, int(round(width * scale_x))),
            max(1, int(round(height * scale_y))),
        ),
        quad=quad,
        character_boxes=boxes,
        source=source,
    )


def _offset_candidate(
    candidate: TextCandidate,
    *,
    offset_x: int,
    offset_y: int,
    source: str,
) -> TextCandidate:
    x, y, width, height = candidate.bbox
    quad = None
    if candidate.quad:
        quad = tuple(
            (float(px) + float(offset_x), float(py) + float(offset_y))
            for px, py in candidate.quad
        )
    boxes = tuple(
        (cx + offset_x, cy + offset_y, cw, ch)
        for cx, cy, cw, ch in candidate.character_boxes
    )
    return replace(
        candidate,
        bbox=(x + offset_x, y + offset_y, width, height),
        quad=quad,
        character_boxes=boxes,
        source=source,
    )


def _recognize_overview(image: np.ndarray) -> list[TextCandidate]:
    gray = _gray(image)
    height, width = gray.shape
    maximum = max(height, width)
    if maximum <= OVERVIEW_MAX_SIDE:
        working = gray
        scale_x = scale_y = 1.0
    else:
        ratio = OVERVIEW_MAX_SIDE / float(maximum)
        working = cv2.resize(
            gray,
            (max(1, int(round(width * ratio))), max(1, int(round(height * ratio)))),
            interpolation=cv2.INTER_AREA,
        )
        scale_x = width / float(working.shape[1])
        scale_y = height / float(working.shape[0])
    results = _recognize_rapidocr_pass(_bgr(working), rotation=0)
    return [
        _scaled_candidate(
            item,
            scale_x=scale_x,
            scale_y=scale_y,
            source="rapidocr-overview",
        )
        for item in results
    ]


def _remove_long_rules(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    horizontal = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(15, int(round(width * 0.18))), 1),
        ),
    )
    vertical = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(15, int(round(height * 0.18)))),
        ),
    )
    cleaned = cv2.subtract(mask, cv2.max(horizontal, vertical))
    return cleaned if cv2.countNonZero(cleaned) else mask


def tile_has_probable_text(tile: np.ndarray) -> bool:
    """Cheap conservative filter that skips blank and rule-only OCR tiles."""

    gray = _gray(tile)
    maximum = max(gray.shape)
    if maximum > 1024:
        ratio = 1024.0 / float(maximum)
        gray = cv2.resize(
            gray,
            (
                max(1, int(round(gray.shape[1] * ratio))),
                max(1, int(round(gray.shape[0] * ratio))),
            ),
            interpolation=cv2.INTER_AREA,
        )
    _threshold, mask = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    mask = _remove_long_rules(mask)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    likely = 0
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if area < 3 or width < 1 or height < 2:
            continue
        if height > max(160, int(mask.shape[0] * 0.25)):
            continue
        if width > max(900, int(mask.shape[1] * 0.92)) and height <= 3:
            continue
        likely += 1
        if likely >= 2:
            return True
    return False


def _recognize_tiles(
    image: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[TextCandidate]:
    gray = _gray(image)
    page_shape = tuple(int(value) for value in gray.shape[:2])
    regions = tile_regions(
        page_shape,
        tile_size=TILE_SIZE,
        overlap=TILE_OVERLAP,
    )
    if not regions:
        return []
    results: list[TextCandidate] = []
    for index, region in enumerate(regions):
        checkpoint(cancellation_token)
        left, top, right, bottom = region
        tile = np.ascontiguousarray(gray[top:bottom, left:right])
        if tile_has_probable_text(tile):
            for candidate in _recognize_rapidocr_pass(_bgr(tile), rotation=0):
                if candidate_touches_internal_tile_edge(
                    candidate,
                    tile_region=region,
                    page_shape=page_shape,
                    margin=24,
                ):
                    continue
                results.append(
                    _offset_candidate(
                        candidate,
                        offset_x=left,
                        offset_y=top,
                        source="rapidocr-tile",
                    )
                )
        report_progress(
            progress_callback,
            "ocr-tiles",
            (index + 1) / max(len(regions), 1),
        )
    return results


def _intersection(first: TextCandidate, second: TextCandidate) -> tuple[float, float, float]:
    ax, ay, aw, ah = first.bbox
    bx, by, bw, bh = second.bbox
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    width = max(0, right - left)
    height = max(0, bottom - top)
    area = float(width * height)
    minimum_area = max(1.0, float(min(aw * ah, bw * bh)))
    vertical = float(height) / max(1.0, float(min(ah, bh)))
    horizontal = float(width) / max(1.0, float(min(aw, bw)))
    return area / minimum_area, vertical, horizontal


def _compact(text: str) -> str:
    return "".join(text.split()).casefold()


def _same_region(first: TextCandidate, second: TextCandidate) -> bool:
    coverage, vertical, horizontal = _intersection(first, second)
    if coverage >= 0.72:
        return True
    ax, ay, aw, ah = first.bbox
    bx, by, bw, bh = second.bbox
    center_distance = hypot(
        (ax + aw * 0.5) - (bx + bw * 0.5),
        (ay + ah * 0.5) - (by + bh * 0.5),
    )
    scale = max(1.0, min(aw, bw) * 0.25 + min(ah, bh) * 0.75)
    first_text = _compact(first.text)
    second_text = _compact(second.text)
    texts_related = (
        first_text == second_text
        or first_text in second_text
        or second_text in first_text
    )
    return bool(
        vertical >= 0.78
        and horizontal >= 0.52
        and center_distance <= scale
        and (texts_related or coverage >= 0.55)
    )


def _candidate_rank(candidate: TextCandidate) -> tuple[float, int, int]:
    source_bonus = 2 if candidate.source == "rapidocr-tile" else 1
    compact = _compact(candidate.text)
    return float(candidate.confidence), len(compact), source_bonus


def deduplicate_candidates(
    candidates: Iterable[TextCandidate],
) -> tuple[TextCandidate, ...]:
    """Collapse overview/tile duplicates even when their boxes are not identical."""

    ordered = sorted(candidates, key=_candidate_rank, reverse=True)
    kept: list[TextCandidate] = []
    for candidate in ordered:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if _same_region(candidate, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(candidate)
        elif _candidate_rank(candidate) > _candidate_rank(kept[duplicate_index]):
            kept[duplicate_index] = candidate
        if len(kept) >= MAX_CANDIDATES:
            break
    kept.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(kept)


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


def _nearby_unboxed_ink(image: np.ndarray, candidate: TextCandidate) -> bool:
    x, y, width, height = candidate.bbox
    image_height, image_width = image.shape[:2]
    margin_x = max(8, int(round(max(width * 0.12, height * 0.55))))
    margin_y = max(8, int(round(height * 0.70)))
    left = max(0, x - margin_x)
    top = max(0, y - margin_y)
    right = min(image_width, x + width + margin_x)
    bottom = min(image_height, y + height + margin_y)
    if right <= left or bottom <= top:
        return False
    mask = _binary_crop(image, (left, top, right, bottom))
    inner_left = max(0, x - left)
    inner_top = max(0, y - top)
    inner_right = min(mask.shape[1], x + width - left)
    inner_bottom = min(mask.shape[0], y + height - top)
    if inner_right <= inner_left or inner_bottom <= inner_top:
        return False
    inside = int(cv2.countNonZero(mask[inner_top:inner_bottom, inner_left:inner_right]))
    if inside <= 0:
        return False
    outside_mask = mask.copy()
    outside_mask[inner_top:inner_bottom, inner_left:inner_right] = 0
    band_top = max(0, inner_top - max(3, int(round(height * 0.40))))
    band_bottom = min(mask.shape[0], inner_bottom + max(3, int(round(height * 0.40))))
    outside = int(cv2.countNonZero(outside_mask[band_top:band_bottom]))
    return outside >= max(16, int(round(inside * 0.16)))


def _connected_handwriting_like(image: np.ndarray, candidate: TextCandidate) -> bool:
    compact = _compact(candidate.text)
    if len(compact) < 2 or len(compact) > 8:
        return False
    x, y, width, height = candidate.bbox
    if width <= 0 or height <= 0:
        return False
    mask = _binary_crop(image, (x, y, x + width, y + height))
    if mask.size == 0:
        return False
    kernel_width = max(1, int(round(height * 0.025)))
    connected = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(connected > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    if count <= 1:
        return False
    largest_width = int(stats[1:, cv2.CC_STAT_WIDTH].max())
    expected_cell = width / max(len(compact), 1)
    return bool(
        largest_width >= width * 0.52
        or largest_width >= expected_cell * 1.85
    )


def prepare_safe_candidate(image: np.ndarray, candidate: TextCandidate) -> TextCandidate:
    prepared = prepare_candidate_layout(image, candidate)
    if not prepared.replacement_safe:
        return prepared
    if _nearby_unboxed_ink(image, prepared):
        return replace(
            prepared,
            replacement_safe=False,
            review_note="识别框附近仍有未覆盖笔画，疑似局部文字或签名，保留原图形等待确认",
        )
    if _connected_handwriting_like(image, prepared):
        return replace(
            prepared,
            replacement_safe=False,
            review_note="笔画跨越多个字符位置，疑似签名或连笔文字，保留原图形等待确认",
        )
    return prepared


def recognize_text_candidates_fast(
    image: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[TextCandidate, ...], tuple[str, ...]]:
    if image is None or image.size == 0:
        return (), ("文字识别输入为空，已跳过。",)

    candidates: list[TextCandidate] = []
    warnings: list[str] = []
    try:
        checkpoint(cancellation_token)
        report_progress(progress_callback, "ocr-overview", 0.03)
        candidates.extend(_recognize_overview(image))
        checkpoint(cancellation_token)
        candidates.extend(
            _recognize_tiles(
                image,
                cancellation_token=cancellation_token,
                progress_callback=(
                    None
                    if progress_callback is None
                    else lambda stage, fraction: progress_callback(
                        stage,
                        0.12 + 0.72 * fraction,
                    )
                ),
            )
        )
        checkpoint(cancellation_token)
    except ImportError:
        warnings.append("缺少文字识别组件，已继续处理非文字内容。")
    except Exception as exc:
        warnings.append(f"文字识别失败：{exc}；已继续处理非文字内容。")

    deduplicated = deduplicate_candidates(candidates)
    resolved: list[TextCandidate] = []
    for index, item in enumerate(deduplicated):
        checkpoint(cancellation_token)
        resolved.append(prepare_safe_candidate(image, item))
        if index % 64 == 0:
            report_progress(
                progress_callback,
                "ocr-safety",
                0.86 + 0.13 * index / max(len(deduplicated), 1),
            )
    if not resolved and not warnings:
        warnings.append("未找到可确认的文字。")
    report_progress(progress_callback, "ocr-complete", 1.0)
    return tuple(resolved), tuple(warnings)
