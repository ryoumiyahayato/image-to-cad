from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class PreprocessParams:
    threshold_strength: int = 12
    adaptive_block_size: int = 41
    shadow_kernel_size: int = 35
    denoise_strength: int = 3
    remove_small_noise: bool = True


def _odd(value: int, minimum: int = 3) -> int:
    value = max(minimum, int(value))
    return value if value % 2 == 1 else value + 1


def remove_shadow(gray: np.ndarray, kernel_size: int = 35) -> np.ndarray:
    """Estimate the paper background and divide it out to reduce shadows and folds."""
    size = _odd(kernel_size, 9)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    normalized = cv2.divide(gray, background, scale=255)
    return cv2.normalize(normalized, None, 0, 255, cv2.NORM_MINMAX)


def preprocess_image(
    image: np.ndarray, params: PreprocessParams | None = None
) -> np.ndarray:
    """Return a cleaned binary image with black drawing strokes on a white background."""
    params = params or PreprocessParams()
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    denoise = _odd(params.denoise_strength, 1)
    if denoise > 1:
        gray = cv2.medianBlur(gray, denoise)

    flattened = remove_shadow(gray, params.shadow_kernel_size)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(flattened)

    block_size = _odd(params.adaptive_block_size, 11)
    binary = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        int(params.threshold_strength),
    )

    if params.remove_small_noise:
        # Remove isolated black specks while preserving long one-pixel lines.
        foreground = 255 - binary
        opened = cv2.morphologyEx(
            foreground,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_CROSS, (2, 2)),
        )
        # Recombine with long horizontal/vertical structures that opening can weaken.
        horizontal = cv2.morphologyEx(
            foreground,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1)),
        )
        vertical = cv2.morphologyEx(
            foreground,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)),
        )
        foreground = cv2.max(opened, cv2.max(horizontal, vertical))
        binary = 255 - foreground

    return binary
