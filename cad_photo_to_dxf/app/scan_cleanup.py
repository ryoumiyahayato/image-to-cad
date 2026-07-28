from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .resolution import image_resolution_scale


_DIGITAL_WHITE_RATIO = 0.90
_BACKGROUND_MAX_SIDE = 1200
_COMPONENT_TILE_SIZE = 2048
_COMPONENT_OVERLAP = 64
_SPECK_TILE_SIZE = 1024
_SPECK_OVERLAP = 64


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


def _retain_connected_ink(strong: np.ndarray, weak: np.ndarray) -> np.ndarray:
    """Retain weak edge pixels connected to dark ink using bounded-memory tiles."""

    height, width = weak.shape
    retained = np.zeros((height, width), dtype=bool)
    tile_size = _COMPONENT_TILE_SIZE
    overlap = _COMPONENT_OVERLAP

    for core_top in range(0, height, tile_size):
        core_bottom = min(height, core_top + tile_size)
        top = max(0, core_top - overlap)
        bottom = min(height, core_bottom + overlap)
        for core_left in range(0, width, tile_size):
            core_right = min(width, core_left + tile_size)
            left = max(0, core_left - overlap)
            right = min(width, core_right + overlap)

            weak_tile = np.ascontiguousarray(
                weak[top:bottom, left:right], dtype=np.uint8
            )
            if not np.any(weak_tile):
                continue
            strong_tile = strong[top:bottom, left:right]
            count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
                weak_tile,
                connectivity=8,
            )
            keep_label = np.zeros(count, dtype=bool)
            if np.any(strong_tile):
                keep_label[np.unique(labels[strong_tile])] = True
            keep_label[0] = False
            keep_label &= stats[:, cv2.CC_STAT_AREA] >= 2

            local_core = keep_label[
                labels[
                    core_top - top : core_bottom - top,
                    core_left - left : core_right - left,
                ]
            ]
            retained[core_top:core_bottom, core_left:core_right] = local_core
    return retained


def _clean_scanned_page(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Recover ink from stained, folded, taped, or unevenly exposed paper.

    Broad paper shading is divided out first. A two-level connected-component gate
    then retains weak antialiasing only when it belongs to a component containing
    genuinely dark ink. The component pass is tiled so large architectural sheets
    do not allocate a page-sized 32-bit labels array.
    """

    background = _background_estimate(gray)
    divided = cv2.divide(gray, background, scale=255)
    normalized = cv2.addWeighted(gray, 0.62, divided, 0.38, 0.0)
    local_delta = background.astype(np.int16) - gray.astype(np.int16)

    strong = (divided < 190) | (gray < 95)
    weak = ((divided < 236) & (local_delta > 4)) | (gray < 155)
    retained = _retain_connected_ink(strong, weak)
    retained |= strong
    # Do not close one-pixel horizontal or vertical gaps globally.  On a
    # low-resolution plan those gaps are also the only separation between a
    # glyph and a leader, between adjacent symbols, or between a symbol and a
    # cell rule.  A generic 2x1/1x2 close welded those independent objects
    # together and produced the dense "stuck image" clusters seen in CAD.
    # Connected weak ink recovery above already retains antialiased members of
    # each real source component; any further repair must be semantic and
    # local, not a page-wide morphological bridge.
    binary = np.where(retained, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(normalized), np.ascontiguousarray(binary)


def _suppress_dense_speckle(binary: np.ndarray) -> np.ndarray:
    """Remove clustered scanner dust while preserving isolated punctuation and ink."""

    height, width = binary.shape
    cleaned = binary.copy()
    tile_size = _SPECK_TILE_SIZE
    overlap = _SPECK_OVERLAP
    for core_top in range(0, height, tile_size):
        core_bottom = min(height, core_top + tile_size)
        top = max(0, core_top - overlap)
        bottom = min(height, core_bottom + overlap)
        for core_left in range(0, width, tile_size):
            core_right = min(width, core_left + tile_size)
            left = max(0, core_left - overlap)
            right = min(width, core_right + overlap)
            foreground = np.ascontiguousarray(
                binary[top:bottom, left:right] == 0,
                dtype=np.uint8,
            )
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(
                foreground,
                connectivity=8,
            )
            if count <= 1:
                continue
            tiny = (
                (stats[:, cv2.CC_STAT_AREA] <= 3)
                & (stats[:, cv2.CC_STAT_WIDTH] <= 2)
                & (stats[:, cv2.CC_STAT_HEIGHT] <= 2)
            )
            tiny[0] = False
            tiny_labels = np.flatnonzero(tiny)
            if tiny_labels.size < 32:
                continue

            centers = np.zeros(foreground.shape, dtype=np.uint8)
            for label_value in tiny_labels:
                center_x, center_y = centroids[int(label_value)]
                centers[
                    max(0, min(centers.shape[0] - 1, int(round(center_y)))),
                    max(0, min(centers.shape[1] - 1, int(round(center_x)))),
                ] = 1
            density = cv2.boxFilter(
                centers,
                cv2.CV_32F,
                (128, 128),
                normalize=False,
                borderType=cv2.BORDER_CONSTANT,
            )
            remove_label = np.zeros(count, dtype=bool)
            for label_value in tiny_labels:
                center_x, center_y = centroids[int(label_value)]
                cy = max(0, min(density.shape[0] - 1, int(round(center_y))))
                cx = max(0, min(density.shape[1] - 1, int(round(center_x))))
                if density[cy, cx] >= 40.0:
                    remove_label[int(label_value)] = True

            core_labels = labels[
                core_top - top : core_bottom - top,
                core_left - left : core_right - left,
            ]
            core = cleaned[core_top:core_bottom, core_left:core_right]
            core[remove_label[core_labels]] = 255
    return np.ascontiguousarray(cleaned)


def _suppress_long_low_contrast_artifacts(
    gray: np.ndarray,
    binary: np.ndarray,
) -> np.ndarray:
    """Remove broad fold/tape edges without erasing thin rules or punctuation."""

    scale = image_resolution_scale(binary.shape)
    low_contrast = np.where(
        (binary == 0) & (gray >= 120),
        255,
        0,
    ).astype(np.uint8)
    if not cv2.countNonZero(low_contrast):
        return np.ascontiguousarray(binary)

    minimum_run = max(
        int(round(48.0 * scale)),
        int(round(min(binary.shape[:2]) * 0.04)),
    )
    distance = cv2.distanceTransform(low_contrast, cv2.DIST_L2, 3)
    cleaned = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    minimum_diameter = max(3.0, 3.5 * scale)

    for kernel in (
        cv2.getStructuringElement(cv2.MORPH_RECT, (minimum_run, 1)),
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, minimum_run)),
    ):
        seeds = cv2.morphologyEx(low_contrast, cv2.MORPH_OPEN, kernel)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            np.where(seeds > 0, 255, 0).astype(np.uint8),
            connectivity=8,
        )
        for label_value in range(1, count):
            component = labels == label_value
            component_width = int(stats[label_value, cv2.CC_STAT_WIDTH])
            component_height = int(stats[label_value, cv2.CC_STAT_HEIGHT])
            if max(component_width, component_height) < minimum_run:
                continue
            diameters = distance[component] * 2.0
            if not diameters.size or float(np.median(diameters)) < minimum_diameter:
                continue
            tones = gray[component]
            if not tones.size or float(np.median(tones)) < 132.0:
                continue
            radius = max(2, int(np.ceil(float(np.percentile(diameters, 75)) * 0.5)))
            component_mask = np.where(component, 255, 0).astype(np.uint8)
            expanded = cv2.dilate(
                component_mask,
                cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE,
                    (radius * 2 + 1, radius * 2 + 1),
                ),
                iterations=1,
            )
            removal = (expanded > 0) & (low_contrast > 0)
            cleaned[removal] = 255
    return np.ascontiguousarray(cleaned)


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
    if not clean_digital and foreground_threshold is None:
        binary = _suppress_dense_speckle(binary)
        binary = _suppress_long_low_contrast_artifacts(gray, binary)

    return PreparedScanPage(
        gray=np.ascontiguousarray(gray),
        normalized=np.ascontiguousarray(normalized),
        binary=np.ascontiguousarray(binary),
        threshold=threshold,
        clean_digital=clean_digital,
    )
