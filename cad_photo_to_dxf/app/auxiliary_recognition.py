from __future__ import annotations

from dataclasses import dataclass
import re

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress


@dataclass(frozen=True)
class CircleCandidate:
    center: tuple[float, float]
    radius: float
    confidence: float


@dataclass(frozen=True)
class TextCandidate:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    kind: str


@dataclass(frozen=True)
class SymbolCandidate:
    kind: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass
class AuxiliaryRecognitionResult:
    circles: list[CircleCandidate]
    texts: list[TextCandidate]
    dimension_texts: list[TextCandidate]
    symbols: list[SymbolCandidate]
    warnings: list[str]


def _detect_circles(binary_image: np.ndarray) -> list[CircleCandidate]:
    foreground = 255 - binary_image
    contours, _ = cv2.findContours(foreground, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(binary_image.shape[0] * binary_image.shape[1])
    candidates: list[CircleCandidate] = []
    for contour in contours:
        area = float(abs(cv2.contourArea(contour)))
        perimeter = float(cv2.arcLength(contour, True))
        if area < 25.0 or area > image_area * 0.20 or perimeter <= 1e-6:
            continue
        circularity = float(4.0 * np.pi * area / (perimeter * perimeter))
        if circularity < 0.78:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) < 8:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        if radius < 3.0:
            continue
        bx, by, width, height = cv2.boundingRect(contour)
        aspect = min(width, height) / max(width, height, 1)
        if aspect < 0.82:
            continue
        confidence = min(0.95, 0.45 + 0.35 * circularity + 0.20 * aspect)
        candidate = CircleCandidate((float(x), float(y)), float(radius), confidence)
        duplicate = any(
            np.linalg.norm(np.array(candidate.center) - np.array(existing.center))
            <= max(2.0, min(candidate.radius, existing.radius) * 0.12)
            and abs(candidate.radius - existing.radius)
            <= max(2.0, min(candidate.radius, existing.radius) * 0.18)
            for existing in candidates
        )
        if not duplicate:
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)[:100]


def _detect_rectangular_symbols(binary_image: np.ndarray) -> list[SymbolCandidate]:
    foreground = 255 - binary_image
    contours, _ = cv2.findContours(foreground, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(binary_image.shape[0] * binary_image.shape[1])
    results: list[SymbolCandidate] = []
    for contour in contours:
        area = float(abs(cv2.contourArea(contour)))
        if area < 36.0 or area > image_area * 0.08:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, y, width, height = cv2.boundingRect(approx)
        if min(width, height) < 6:
            continue
        rectangularity = min(1.0, area / max(float(width * height), 1.0))
        aspect = width / max(height, 1)
        if 0.65 <= aspect <= 1.55:
            kind = "square_or_column_candidate"
        else:
            kind = "rectangular_symbol_candidate"
        results.append(
            SymbolCandidate(kind, (int(x), int(y), int(width), int(height)), 0.4 + 0.4 * rectangularity)
        )
    results.sort(key=lambda item: item.confidence, reverse=True)
    return results[:300]


def _run_optional_ocr(binary_image: np.ndarray) -> tuple[list[TextCandidate], str | None]:
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError:
        return [], "未安装可选依赖 pytesseract，已跳过 OCR。"
    try:
        data = pytesseract.image_to_data(
            binary_image,
            config="--psm 11",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        return [], f"OCR 调用失败：{exc}"

    results: list[TextCandidate] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index]) / 100.0
        except (KeyError, TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.25:
            continue
        bbox = (
            int(data["left"][index]),
            int(data["top"][index]),
            int(data["width"][index]),
            int(data["height"][index]),
        )
        kind = "dimension_text_candidate" if re.fullmatch(r"[ØRr]?\s*\d+(?:[.,]\d+)?", text) else "text_candidate"
        results.append(TextCandidate(text, bbox, confidence, kind))
    return results, None


def recognize_auxiliary(
    binary_image: np.ndarray,
    enable_ocr: bool = False,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AuxiliaryRecognitionResult:
    """Detect non-LINE information as review-only candidates.

    Candidates are deliberately excluded from the DXF geometry because circle,
    OCR, dimension and symbol semantics remain probabilistic in v1.1.
    """
    if binary_image.ndim == 3:
        binary_image = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    checkpoint(cancellation_token)
    circles = _detect_circles(binary_image)
    checkpoint(cancellation_token)
    report_progress(progress_callback, "auxiliary-circles", 0.35)
    symbols = _detect_rectangular_symbols(binary_image)
    checkpoint(cancellation_token)
    report_progress(progress_callback, "auxiliary-symbols", 0.65)

    warnings = [
        "圆弧、OCR、尺寸文字和建筑符号仅作为辅助候选，不自动写入 DXF 主体。"
    ]
    texts: list[TextCandidate] = []
    if enable_ocr:
        checkpoint(cancellation_token)
        texts, warning = _run_optional_ocr(binary_image)
        # A native OCR call cannot be interrupted until it returns.
        checkpoint(cancellation_token)
        if warning:
            warnings.append(warning)
    dimension_texts = [item for item in texts if item.kind == "dimension_text_candidate"]
    report_progress(progress_callback, "auxiliary", 1.0)
    return AuxiliaryRecognitionResult(circles, texts, dimension_texts, symbols, warnings)
