from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


_DIGITAL_WHITE_RATIO = 0.90
_BACKGROUND_MAX_SIDE = 1200


@dataclass(frozen=True)
class PreparedScanPage:
    gray: np.ndarray
    normalized: np.ndarray
    binary: np.ndarray
    threshold: int
    clean_digital: bool


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("Scan source image must not be empty")
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        code = cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        gray = cv2.cvtColor(image, code)
    else:
        raise ValueError("Scan source must be grayscale, BGR, or BGRA")
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return np.ascontiguousarray(gray)


def _background_estimate(gray: np.ndarray) -> np.ndarray:
    """Estimate slow paper shading without blurring the full-size page repeatedly."""

    height, width = gray.shape
    maximum = max(height, width)
    ratio = min(1.0, _BACKGROUND_MAX_SIDE / float(maximum))
    if ratio < 1.0:
        small = cv2.resize(
            gray,
            (max(1, int(round(width * ratio))), max(1, int(round(height * ratio)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = gray
    sigma = max(7.0, min(small.shape) / 55.0)
    background_small = cv2.GaussianBlur(
        small,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    if background_small.shape != gray.shape:
        background = cv2.resize(
            background_small,
            (width, height),
            interpolation=cv2.INTER_LINEAR,
        )
    else:
        background = background_small
    return np.maximum(background, 32).astype(np.uint8, copy=False)


def _clean_scanned_page(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Recover ink from stained, folded, taped, or unevenly exposed paper.

    Broad paper shading is divided out first. A two-level connected-component gate
    then retains weak antialiasing only when it belongs to a component containing
    genuinely dark ink. This removes most paper texture and damaged-corner clouds
    without opening/closing strokes or deleting handwriting and signatures.
    """

    background = _background_estimate(gray)
    normalized = cv2.divide(gray, background, scale=255)
    local_delta = background.astype(np.int16) - gray.astype(np.int16)

    strong = (normalized < 160) | (gray < 70)
    weak = ((normalized < 222) & (local_delta > 7)) | (gray < 105)

    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        weak.astype(np.uint8),
        connectivity=8,
    )
    keep_label = np.zeros(count, dtype=bool)
    if np.any(strong):
        keep_label[np.unique(labels[strong])] = True
    keep_label[0] = False

    areas = stats[:, cv2.CC_STAT_AREA]
    keep_label &= areas >= 2
    retained = keep_label[labels]
    retained |= strong & (gray < 65)
    binary = np.where(retained, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(normalized), np.ascontiguousarray(binary)


def prepare_scan_page(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
) -> PreparedScanPage:
    """Prepare either a clean digital page or a damaged scan for OCR and tracing."""

    gray = _to_gray(image)
    exact_white_ratio = float(np.count_nonzero(gray == 255)) / float(gray.size)
    clean_digital = exact_white_ratio >= _DIGITAL_WHITE_RATIO

    if foreground_threshold is not None:
        threshold = int(max(1, min(254, foreground_threshold)))
        _unused, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        normalized = gray
    elif clean_digital:
        threshold = 254
        _unused, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        normalized = gray
    else:
        threshold = 128
        normalized, binary = _clean_scanned_page(gray)

    if int(np.count_nonzero(binary == 0)) > binary.size // 2:
        binary = 255 - binary

    return PreparedScanPage(
        gray=np.ascontiguousarray(gray),
        normalized=np.ascontiguousarray(normalized),
        binary=np.ascontiguousarray(binary),
        threshold=threshold,
        clean_digital=clean_digital,
    )
