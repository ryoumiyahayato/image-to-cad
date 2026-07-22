from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import atan2, degrees
from typing import Any

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_layout import (
    candidate_touches_internal_tile_edge,
    offset_candidate,
    prepare_candidate_layout,
    tile_regions,
)


# Keep lower-confidence detections available for manual correction. Automatic
# export still requires the stricter thresholds in ``accepted_ocr_texts``.
MIN_OCR_CONFIDENCE = 0.50
MAX_OCR_CANDIDATES = 3000
_RAPID_OCR_ENGINE: Any | None = None


def _candidate_kind(text: str) -> str:
    compact = "".join(text.split())
    if compact and all(char in "0123456789.,+-×xXØøRr:%/()[]" for char in compact):
        return "dimension_text_candidate"
    return "text_candidate"


def _quad_from_value(value: Any) -> tuple[tuple[float, float], ...] | None:
    try:
        array = np.asarray(value, dtype=float).reshape(-1, 2)
    except (TypeError, ValueError):
        return None
    if len(array) != 4 or not np.isfinite(array).all():
        return None
    return tuple((float(point[0]), float(point[1])) for point in array)


def _bbox_from_quad(quad: tuple[tuple[float, float], ...]) -> tuple[int, int, int, int]:
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    left = int(np.floor(min(xs)))
    top = int(np.floor(min(ys)))
    right = int(np.ceil(max(xs)))
    bottom = int(np.ceil(max(ys)))
    return left, top, max(1, right - left), max(1, bottom - top)


def _rotation_from_quad(quad: tuple[tuple[float, float], ...]) -> float:
    top_left, top_right = quad[0], quad[1]
    return float(degrees(atan2(top_right[1] - top_left[1], top_right[0] - top_left[0])))


def _map_rotated_quad(
    quad: tuple[tuple[float, float], ...],
    *,
    rotation: int,
    original_shape: tuple[int, int],
) -> tuple[tuple[float, float], ...]:
    if rotation == 0:
        return quad
    height, width = original_shape
    if rotation == 90:
        return tuple((float(y), float(height - 1 - x)) for x, y in quad)
    if rotation == 270:
        return tuple((float(width - 1 - y), float(x)) for x, y in quad)
    raise ValueError(f"Unsupported OCR rotation: {rotation}")


def _iter_word_results(value: Any) -> Iterable[tuple[str, float, Any]]:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        if (
            len(value) >= 3
            and isinstance(value[0], str)
            and isinstance(value[1], (int, float, np.integer, np.floating))
            and _quad_from_value(value[2]) is not None
        ):
            yield str(value[0]), float(value[1]), value[2]
            return
        for item in value:
            yield from _iter_word_results(item)


def _as_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _get_rapidocr_engine() -> Any:
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is not None:
        return _RAPID_OCR_ENGINE
    from rapidocr import RapidOCR  # type: ignore[import-not-found]

    params = {
        "Global.text_score": MIN_OCR_CONFIDENCE,
        "Global.max_side_len": 4096,
        "Global.log_level": "warning",
    }
    try:
        _RAPID_OCR_ENGINE = RapidOCR(params=params)
    except (TypeError, ValueError):
        _RAPID_OCR_ENGINE = RapidOCR()
    return _RAPID_OCR_ENGINE


def _candidate_is_reasonable(
    bbox: tuple[int, int, int, int],
    *,
    rotation: int,
    original_shape: tuple[int, int],
    text: str,
) -> bool:
    image_height, image_width = original_shape
    x, y, width, height = bbox
    if x < -2 or y < -2 or x + width > image_width + 2 or y + height > image_height + 2:
        return False
    if width <= 1 or height <= 1 or width * height <= 4:
        return False
    if len(text) > 180:
        return False
    image_area = max(float(image_width * image_height), 1.0)
    if width * height > image_area * 0.06:
        return False
    if rotation == 0:
        if height > max(48, int(image_height * 0.10)):
            return False
        if width > int(image_width * 0.95):
            return False
    else:
        if width > max(48, int(image_width * 0.10)):
            return False
        if height > int(image_height * 0.32):
            return False
        if len(text) > 24:
            return False
    return True


def _candidate_from_quad(
    text: str,
    confidence: float,
    quad_value: Any,
    *,
    rotation: int,
    original_shape: tuple[int, int],
    source: str,
) -> TextCandidate | None:
    cleaned = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if not cleaned or not np.isfinite(float(confidence)):
        return None
    if float(confidence) < MIN_OCR_CONFIDENCE:
        return None
    quad = _quad_from_value(quad_value)
    if quad is None:
        return None
    mapped = _map_rotated_quad(
        quad,
        rotation=rotation,
        original_shape=original_shape,
    )
    bbox = _bbox_from_quad(mapped)
    if not _candidate_is_reasonable(
        bbox,
        rotation=rotation,
        original_shape=original_shape,
        text=cleaned,
    ):
        return None
    return TextCandidate(
        cleaned,
        bbox,
        float(confidence),
        _candidate_kind(cleaned),
        rotation_deg=_rotation_from_quad(mapped),
        quad=mapped,
        source=source,
    )


def _line_candidates(
    result: Any,
    *,
    rotation: int,
    original_shape: tuple[int, int],
) -> list[TextCandidate]:
    boxes = _as_sequence(getattr(result, "boxes", None))
    texts = _as_sequence(getattr(result, "txts", None))
    scores = _as_sequence(getattr(result, "scores", None))
    candidates: list[TextCandidate] = []
    for quad, text, confidence in zip(boxes, texts, scores, strict=False):
        candidate = _candidate_from_quad(
            str(text),
            float(confidence),
            quad,
            rotation=rotation,
            original_shape=original_shape,
            source="rapidocr-line",
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _word_candidates(
    result: Any,
    *,
    rotation: int,
    original_shape: tuple[int, int],
) -> list[TextCandidate]:
    candidates: list[TextCandidate] = []
    for text, confidence, quad in _iter_word_results(
        getattr(result, "word_results", None)
    ):
        candidate = _candidate_from_quad(
            text,
            confidence,
            quad,
            rotation=rotation,
            original_shape=original_shape,
            source="rapidocr-word-fallback",
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _recognize_rapidocr_pass(
    image: np.ndarray,
    *,
    rotation: int,
) -> list[TextCandidate]:
    if rotation == 90:
        working = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 270:
        working = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        working = image
    engine = _get_rapidocr_engine()
    result = engine(
        working,
        use_det=True,
        use_cls=True,
        use_rec=True,
    )
    if result is None:
        return []

    original_shape = tuple(int(value) for value in image.shape[:2])
    lines = _line_candidates(
        result,
        rotation=rotation,
        original_shape=original_shape,
    )
    if lines:
        return lines
    return _word_candidates(
        result,
        rotation=rotation,
        original_shape=original_shape,
    )


def _recognize_tiled_horizontal(
    image: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[TextCandidate]:
    page_shape = tuple(int(value) for value in image.shape[:2])
    regions = tile_regions(page_shape)
    if not regions:
        return []
    candidates: list[TextCandidate] = []
    for index, region in enumerate(regions):
        checkpoint(cancellation_token)
        left, top, right, bottom = region
        tile = np.ascontiguousarray(image[top:bottom, left:right])
        for candidate in _recognize_rapidocr_pass(tile, rotation=0):
            if candidate_touches_internal_tile_edge(
                candidate,
                tile_region=region,
                page_shape=page_shape,
            ):
                continue
            candidates.append(
                offset_candidate(
                    candidate,
                    offset_x=left,
                    offset_y=top,
                    source="rapidocr-tile",
                )
            )
        report_progress(
            progress_callback,
            "ocr-native-tiles",
            (index + 1) / max(len(regions), 1),
        )
    return candidates


def _intersection_over_union(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    ax1, ay1, aw, ah = first
    bx1, by1, bw, bh = second
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    width = max(0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = float(width * height)
    if intersection <= 0:
        return 0.0
    union = float(aw * ah + bw * bh) - intersection
    return intersection / max(union, 1.0)


def _deduplicate(candidates: Iterable[TextCandidate]) -> tuple[TextCandidate, ...]:
    ordered = sorted(candidates, key=lambda item: item.confidence, reverse=True)
    kept: list[TextCandidate] = []
    for candidate in ordered:
        duplicate = any(
            _intersection_over_union(candidate.bbox, existing.bbox) >= 0.55
            and (
                candidate.text == existing.text
                or candidate.bbox[2] * candidate.bbox[3]
                <= existing.bbox[2] * existing.bbox[3] * 1.25
            )
            for existing in kept
        )
        if not duplicate:
            kept.append(candidate)
        if len(kept) >= MAX_OCR_CANDIDATES:
            break
    kept.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(kept)


def recognize_text_candidates(
    image: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[TextCandidate, ...], tuple[str, ...]]:
    """Recognize small horizontal text without partially replacing signatures.

    A full-page pass retains large headings. Large 300-DPI pages are also scanned
    in overlapping native-resolution tiles so table notes and small labels are
    not lost by the OCR engine's 4096-pixel internal resize. Every candidate is
    then checked against the original ink. Candidates whose strokes cross several
    character cells, as commonly happens with signatures and handwriting, remain
    review-only and do not suppress the original contour automatically.
    """

    if image is None or image.size == 0:
        return (), ("OCR 输入图像为空，已跳过文字识别。",)
    if image.ndim == 2:
        source = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        source = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim == 3 and image.shape[2] == 3:
        source = np.ascontiguousarray(image)
    else:
        return (), ("OCR 输入图像格式不受支持，已跳过文字识别。",)

    warnings: list[str] = []
    candidates: list[TextCandidate] = []
    try:
        checkpoint(cancellation_token)
        report_progress(progress_callback, "ocr-horizontal", 0.05)
        candidates.extend(_recognize_rapidocr_pass(source, rotation=0))
        checkpoint(cancellation_token)
        candidates.extend(
            _recognize_tiled_horizontal(
                source,
                cancellation_token=cancellation_token,
                progress_callback=(
                    None
                    if progress_callback is None
                    else lambda stage, fraction: progress_callback(
                        stage,
                        0.12 + 0.70 * fraction,
                    )
                ),
            )
        )
        checkpoint(cancellation_token)
    except ImportError:
        warnings.append("未找到内置 RapidOCR 组件；已继续生成非文字 CAD 轮廓。")
    except Exception as exc:
        warnings.append(f"RapidOCR 文字识别失败：{exc}；已继续生成非文字 CAD 轮廓。")

    deduplicated = _deduplicate(candidates)
    resolved = tuple(prepare_candidate_layout(source, item) for item in deduplicated)
    if not resolved and not warnings:
        warnings.append("OCR 未找到达到置信度阈值的完整横排文字行。")
    report_progress(progress_callback, "ocr-complete", 1.0)
    return resolved, tuple(warnings)


def render_ocr_overlay(
    image: np.ndarray,
    candidates: Iterable[TextCandidate],
) -> np.ndarray:
    if image.ndim == 2:
        overlay = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        overlay = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    else:
        overlay = image.copy()
    for candidate in candidates:
        color = (0, 180, 0) if candidate.replacement_safe else (0, 120, 230)
        quad = candidate.quad
        if quad:
            polygon = np.asarray(quad, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(overlay, [polygon], True, color, 2, cv2.LINE_AA)
        else:
            x, y, width, height = candidate.bbox
            cv2.rectangle(overlay, (x, y), (x + width, y + height), color, 2)
        for x, y, width, height in candidate.character_boxes:
            cv2.rectangle(
                overlay,
                (int(x), int(y)),
                (int(x + width), int(y + height)),
                (180, 0, 180),
                1,
            )
    return overlay
