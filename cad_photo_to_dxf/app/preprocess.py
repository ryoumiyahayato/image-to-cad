from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .resolution import image_resolution_scale, scaled_int, scaled_odd


@dataclass
class PreprocessParams:
    threshold_strength: int = 12
    adaptive_block_size: int = 41
    shadow_kernel_size: int = 35
    # Median filtering with a 3x3 kernel erases valid one-pixel CAD strokes.
    # It is therefore opt-in; connected-component cleanup is used by default.
    denoise_strength: int = 1
    remove_small_noise: bool = True
    noise_min_area: int = 4
    noise_min_extent: int = 5


@dataclass
class PreprocessResult:
    image: np.ndarray
    stages: dict[str, np.ndarray]
    resolution_scale: float = 1.0


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


def _remove_small_components(
    foreground: np.ndarray,
    min_area: int,
    min_extent: int,
) -> np.ndarray:
    """Remove compact specks while retaining long thin strokes in every direction."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    cleaned = np.zeros_like(foreground)
    for label in range(1, count):
        _x, _y, width, height, area = stats[label]
        if area >= min_area or max(width, height) >= min_extent:
            cleaned[labels == label] = 255
    return cleaned


def preprocess_image_with_stages(
    image: np.ndarray,
    params: PreprocessParams | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PreprocessResult:
    """Return a resolution-normalized binary image and diagnostic stages."""
    params = params or PreprocessParams()
    if image is None or image.size == 0:
        raise ValueError("Input image must not be empty")
    scale = image_resolution_scale(image.shape)
    checkpoint(cancellation_token)
    report_progress(progress_callback, "grayscale", 0.05)
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    stages: dict[str, np.ndarray] = {"01_grayscale": gray.copy()}

    checkpoint(cancellation_token)
    denoise = (
        1
        if params.denoise_strength <= 1
        else scaled_odd(params.denoise_strength, scale, minimum=3)
    )
    if denoise > 1:
        gray = cv2.medianBlur(gray, denoise)
    stages["02_denoised"] = gray.copy()
    report_progress(progress_callback, "denoise", 0.2)

    checkpoint(cancellation_token)
    shadow_kernel = scaled_odd(params.shadow_kernel_size, scale, minimum=9)
    flattened = remove_shadow(gray, shadow_kernel)
    stages["03_shadow_removed"] = flattened.copy()
    report_progress(progress_callback, "shadow-removal", 0.4)

    checkpoint(cancellation_token)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(flattened)
    stages["04_contrast_enhanced"] = enhanced.copy()
    report_progress(progress_callback, "contrast", 0.58)

    checkpoint(cancellation_token)
    block_size = scaled_odd(params.adaptive_block_size, scale, minimum=11)
    binary = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        int(params.threshold_strength),
    )
    stages["05_thresholded"] = binary.copy()
    report_progress(progress_callback, "threshold", 0.78)

    checkpoint(cancellation_token)
    if params.remove_small_noise:
        foreground = _remove_small_components(
            255 - binary,
            scaled_int(params.noise_min_area, scale * scale, minimum=1),
            scaled_int(params.noise_min_extent, scale, minimum=1),
        )
        binary = 255 - foreground
    stages["06_noise_cleaned"] = binary.copy()
    report_progress(progress_callback, "noise-cleanup", 1.0)
    checkpoint(cancellation_token)
    return PreprocessResult(binary, stages, resolution_scale=scale)


def preprocess_image(
    image: np.ndarray,
    params: PreprocessParams | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> np.ndarray:
    """Return a cleaned binary image with black drawing strokes on a white background."""
    return preprocess_image_with_stages(
        image,
        params,
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
    ).image
