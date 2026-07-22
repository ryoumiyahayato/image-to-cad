from __future__ import annotations

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_fast import (
    TILE_OVERLAP,
    TILE_SIZE,
    _offset_candidate,
    _recognize_overview,
    deduplicate_candidates,
    prepare_safe_candidate,
)
from .ocr_layout import candidate_touches_internal_tile_edge, tile_regions
from .ocr_overlap import collapse_overlapping_candidates
from .ocr_recognition import _recognize_rapidocr_pass
from .ocr_tile_filter import tile_has_probable_text


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise ValueError("Unsupported OCR image")


def remove_table_rules_for_ocr(tile: np.ndarray) -> np.ndarray:
    """Whiten only long table rules before OCR while retaining printed glyphs."""

    gray = _gray(tile)
    _threshold, foreground = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    height, width = foreground.shape
    horizontal = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(25, int(round(width * 0.20))), 1),
        ),
    )
    vertical = cv2.morphologyEx(
        foreground,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(25, int(round(height * 0.20)))),
        ),
    )
    rules = cv2.max(horizontal, vertical)
    if not cv2.countNonZero(rules):
        return gray
    cleaned = gray.copy()
    cleaned[rules > 0] = 255
    return cleaned


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
    candidates: list[TextCandidate] = []
    for index, region in enumerate(regions):
        checkpoint(cancellation_token)
        left, top, right, bottom = region
        tile = np.ascontiguousarray(gray[top:bottom, left:right])
        if tile_has_probable_text(tile):
            cleaned = remove_table_rules_for_ocr(tile)
            working = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)
            for candidate in _recognize_rapidocr_pass(working, rotation=0):
                if candidate_touches_internal_tile_edge(
                    candidate,
                    tile_region=region,
                    page_shape=page_shape,
                    margin=24,
                ):
                    continue
                candidates.append(
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
    return candidates


def recognize_text_candidates_optimized(
    image: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[TextCandidate, ...], tuple[str, ...]]:
    """Recognize large headings and table text once, then remove duplicates."""

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

    deduplicated = collapse_overlapping_candidates(deduplicate_candidates(candidates))
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
