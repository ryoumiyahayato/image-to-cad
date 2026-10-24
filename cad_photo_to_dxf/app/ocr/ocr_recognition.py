from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from math import atan2, degrees
from typing import Any

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate


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
    from app.ocr.long_line_orientation import LongLineOrientationClassifier

    classifier = getattr(_RAPID_OCR_ENGINE, "text_cls", None)
    if callable(classifier):
        _RAPID_OCR_ENGINE.text_cls = LongLineOrientationClassifier(classifier)
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
    if rotation != 0 and len(text) > 24:
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


def _review_single_digit_orientation(
    image: np.ndarray,
    candidates: list[TextCandidate],
    engine: Any,
) -> list[TextCandidate]:
    """Recheck small digits that RapidOCR treats as vertical text.

    RapidOCR rotates crops with height/width >= 1.5 by 90 degrees. A narrow
    upright digit can then become another digit, even at high confidence.
    Require agreement between the source-oriented crop and a padded version;
    neither the previous answer nor a confidence comparison decides the digit.
    """
    recognize = getattr(engine, "recognize_txt", None)
    if not callable(recognize):
        return candidates

    indices: list[int] = []
    crops: list[np.ndarray] = []
    for index, candidate in enumerate(candidates):
        if candidate.text not in "0123456789" or len(candidate.text) != 1:
            continue
        if candidate.quad is None or abs(candidate.rotation_deg) > 10.0:
            continue
        points = np.asarray(candidate.quad, dtype=np.float32)
        width = int(
            max(
                np.linalg.norm(points[0] - points[1]),
                np.linalg.norm(points[2] - points[3]),
            )
        )
        height = int(
            max(
                np.linalg.norm(points[0] - points[3]),
                np.linalg.norm(points[1] - points[2]),
            )
        )
        if width < 2 or not 8 <= height <= 96 or height / width < 1.5:
            continue
        target = np.asarray(
            ((0, 0), (width, 0), (width, height), (0, height)), dtype=np.float32
        )
        crop = cv2.warpPerspective(
            image,
            cv2.getPerspectiveTransform(points, target),
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        padding = max(2, int(round(height * 0.08)))
        padded = cv2.copyMakeBorder(
            crop,
            padding,
            padding,
            padding,
            padding,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        indices.append(index)
        crops.extend((crop, padded))
    if not crops:
        return candidates

    # This optional local review must not discard successful page detections.
    try:
        result = recognize(crops)
        texts = _as_sequence(getattr(result, "txts", None))
        scores = _as_sequence(getattr(result, "scores", None))
        if len(texts) != len(crops) or len(scores) != len(crops):
            return candidates
        resolved = list(candidates)
        for pair, index in enumerate(indices):
            first, second = (str(texts[2 * pair + offset]).strip() for offset in (0, 1))
            confidence = float(
                np.minimum(float(scores[2 * pair]), float(scores[2 * pair + 1]))
            )
            if (
                len(first) != 1
                or first not in "0123456789"
                or first != second
                or not np.isfinite(confidence)
                or confidence < 0.90
            ):
                continue
            if first != candidates[index].text:
                resolved[index] = replace(
                    candidates[index],
                    text=first,
                    confidence=confidence,
                    source="rapidocr-line-upright-digit",
                )
        return resolved
    except Exception:
        return candidates


def _review_rotated_line_orientation(
    image: np.ndarray,
    candidates: list[TextCandidate],
    engine: Any,
) -> list[TextCandidate]:
    """Recover a portrait crop's reading basis lost by RapidOCR's output.

    The detector returns its original corners after crop auto-rotation and
    classification. Aspect ratio only selects a local review; a confident
    classifier and unchanged recognition must agree on the reading direction.
    Upright digits, vertical CJK typesetting and ambiguous readings stay intact.
    """
    recognize = getattr(engine, "recognize_txt", None)
    classify = getattr(engine, "text_cls", None)
    if not callable(recognize) or not callable(classify):
        return candidates

    indices: list[int] = []
    crops: list[np.ndarray] = []
    for index, candidate in enumerate(candidates):
        compact = "".join(candidate.text.split())
        if (
            candidate.reviewed
            or candidate.quad is None
            or not compact.isascii()
            or sum(character.isalnum() for character in compact) < 2
        ):
            continue
        points = np.asarray(candidate.quad, dtype=np.float32)
        width = int(
            max(
                np.linalg.norm(points[0] - points[1]),
                np.linalg.norm(points[2] - points[3]),
            )
        )
        height = int(
            max(
                np.linalg.norm(points[0] - points[3]),
                np.linalg.norm(points[1] - points[2]),
            )
        )
        if width < 2 or height / width < 1.5:
            continue
        target = np.asarray(
            ((0, 0), (width, 0), (width, height), (0, height)), dtype=np.float32
        )
        crop = cv2.warpPerspective(
            image,
            cv2.getPerspectiveTransform(points, target),
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        indices.append(index)
        crops.extend(
            (
                crop,
                np.ascontiguousarray(np.rot90(crop)),
                np.ascontiguousarray(np.rot90(crop, 3)),
            )
        )
    if not crops:
        return candidates

    try:
        classification = classify([crops[3 * pair + 1] for pair in range(len(indices))])
        labels = _as_sequence(getattr(classification, "cls_res", None))
        recognition = recognize(crops)
        texts = _as_sequence(getattr(recognition, "txts", None))
        scores = _as_sequence(getattr(recognition, "scores", None))
        if (
            len(labels) != len(indices)
            or len(texts) != len(crops)
            or len(scores) != len(crops)
        ):
            return candidates
        resolved = list(candidates)
        for pair, index in enumerate(indices):
            label, direction_confidence = labels[pair]
            if str(label) not in {"0", "180"} or not np.isfinite(
                float(direction_confidence)
            ):
                continue
            if float(direction_confidence) < 0.95:
                continue
            selected = 1 if str(label) == "0" else 2
            expected = "".join(candidates[index].text.split())
            readings = [
                "".join(str(texts[3 * pair + offset]).split()) for offset in range(3)
            ]
            confidences = [float(scores[3 * pair + offset]) for offset in range(3)]
            if (
                not all(np.isfinite(confidence) for confidence in confidences)
                or readings[selected] != expected
                or confidences[selected] < 0.90
            ):
                continue
            if any(
                readings[offset] == expected and confidences[offset] >= 0.90
                for offset in range(3)
                if offset != selected
            ):
                continue
            # Cyclic ordering changes the reading basis, never the source
            # polygon, bbox, string, confidence or source replacement authority.
            quad = candidates[index].quad
            assert quad is not None
            start = 1 if selected == 1 else 3
            oriented = tuple(quad[(start + offset) % 4] for offset in range(4))
            resolved[index] = replace(
                candidates[index],
                quad=oriented,
                rotation_deg=_rotation_from_quad(oriented),
            )
        return resolved
    except Exception:
        # Local orientation review cannot discard a successful page detection.
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
        lines = _review_rotated_line_orientation(image, lines, engine)
        if rotation == 0:
            return _review_single_digit_orientation(working, lines, engine)
        return lines
    return _word_candidates(
        result,
        rotation=rotation,
        original_shape=original_shape,
    )
