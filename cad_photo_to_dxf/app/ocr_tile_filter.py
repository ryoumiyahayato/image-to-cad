from __future__ import annotations

import cv2
import numpy as np


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise ValueError("Unsupported OCR tile")


def _without_long_rules(mask: np.ndarray) -> np.ndarray:
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
    """Skip empty and table-rule-only tiles before invoking the OCR engine."""

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
    mask = _without_long_rules(mask)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    likely = 0
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        # Rule intersections left after morphology are normally 1–4 px blobs.
        if area < 6 or width < 2 or height < 3:
            continue
        if width <= 4 and height <= 4 and area <= 16:
            continue
        if height > max(160, int(mask.shape[0] * 0.25)):
            continue
        if width > max(900, int(mask.shape[1] * 0.92)) and height <= 4:
            continue
        likely += 1
        if likely >= 2:
            return True
    return False
