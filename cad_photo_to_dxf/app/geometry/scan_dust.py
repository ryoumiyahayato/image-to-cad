"""Read aligned original-scan evidence and authorize dust only in reviewed blank paper."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

REFERENCE_DPI = 200
MAX_DUST_SPAN_MM = 2 * 25.4 / REFERENCE_DPI
MAX_DUST_AREA_MM2 = 3 * (25.4 / REFERENCE_DPI) ** 2
ORIGINAL_TILE_SIZE = 1024


@dataclass(frozen=True)
class RegisteredOriginalScan:
    pixels: np.ndarray
    dpi: float
    ratio: int


def load_original_scan(path: Path) -> tuple[np.ndarray | None, float | None, str]:
    from PIL import Image

    try:
        with Image.open(path) as original:
            dpi = tuple(float(value) for value in original.info.get("dpi", ()))
            if (
                original.format != "TIFF" or original.n_frames != 1 or len(dpi) != 2
                or not all(np.isfinite(value) and value > 0 for value in dpi)
                or abs(dpi[0] - dpi[1]) > 0.01
            ):
                return None, None, "ORIGINAL_METADATA_NOT_VERIFIED"
            return np.asarray(original.convert("L")), dpi[0], "LOADED"
    except (OSError, ValueError, TypeError, Image.DecompressionBombError):
        return None, None, "ORIGINAL_READ_FAILED"


def register_original_scan(
    source: np.ndarray,
    original: np.ndarray,
    source_dpi: float,
    original_dpi: float,
) -> tuple[RegisteredOriginalScan | None, str]:
    height, width = source.shape
    ratio = round(original_dpi / source_dpi)
    if (
        original_dpi < REFERENCE_DPI or ratio < 2
        or abs(original_dpi - ratio * source_dpi) > 0.01
        or original.shape != (height * ratio, width * ratio)
    ):
        return None, "ORIGINAL_GRID_NOT_VERIFIED"
    if np.any((original != 0) & (original != 255)):
        return None, "ORIGINAL_NOT_BITONAL"

    reduced = cv2.resize(original, (width, height), interpolation=cv2.INTER_AREA)
    if (
        not np.array_equal(reduced < 255, source < 255)
        or cv2.norm(reduced, source, cv2.NORM_INF) > 1
    ):
        return None, "SOURCE_REGISTRATION_NOT_VERIFIED"
    return RegisteredOriginalScan(original, original_dpi, ratio), "VERIFIED_ORIGINAL_GRID"


def extract_original_scan_features(
    scan: RegisteredOriginalScan,
    source_crop: tuple[int, int, int, int] | None,
) -> dict[str, object]:
    """Measure original-grid ink in the requested input window."""
    height, width = scan.pixels.shape
    ratio = scan.ratio
    source_bounds = source_crop or (0, 0, width // ratio, height // ratio)
    left, top, right, bottom = (coordinate * ratio for coordinate in source_bounds)
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("Crop must be a nonempty rectangle inside the source")
    components = []
    native_ink_pixels = 0
    for y0 in range(top, bottom, ORIGINAL_TILE_SIZE):
        y1 = min(y0 + ORIGINAL_TILE_SIZE, bottom)
        for x0 in range(left, right, ORIGINAL_TILE_SIZE):
            x1 = min(x0 + ORIGINAL_TILE_SIZE, right)
            ink = np.uint8(scan.pixels[y0:y1, x0:x1] == 0)
            _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
            for x, y, w, h, area in stats[1:].tolist():
                touches_boundary = x == 0 or y == 0 or x + w == x1 - x0 or y + h == y1 - y0
                components.append((x0 + x, y0 + y, x0 + x + w, y0 + y + h, area, touches_boundary))
                native_ink_pixels += area
    return {
        "sampling": "native_tiff_pixels",
        "input_bounds_px": source_bounds,
        "original_bounds_px": (left, top, right, bottom),
        "original_dpi": scan.dpi,
        "original_pixels_per_input_axis": ratio,
        "native_ink_pixels": native_ink_pixels,
        "component_fields": ("x0", "y0", "x1", "y1", "ink_pixels", "touches_tile_or_crop_boundary"),
        "components_xyxy_area_boundary": components,
    }


def authorize_scan_dust(
    source: np.ndarray,
    scan: RegisteredOriginalScan | None,
    blank_regions: Sequence[tuple[int, int, int, int]],
) -> np.ndarray | None:
    """Require reviewed paper and complete low-grid component coverage."""
    height, width = source.shape
    for left, top, right, bottom in blank_regions:
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError("Reviewed blank paper must lie inside the source")
    if not blank_regions or scan is None:
        return None
    return _select_native_dust(source, scan, blank_regions)


def _select_native_dust(
    source: np.ndarray,
    scan: RegisteredOriginalScan,
    regions: Sequence[tuple[int, int, int, int]],
) -> np.ndarray:
    height, width = source.shape
    original, original_dpi, ratio = scan.pixels, scan.dpi, scan.ratio
    span = floor(MAX_DUST_SPAN_MM * original_dpi / 25.4 + 1e-9)
    area = min(
        ratio ** 2 - 1,
        floor(MAX_DUST_AREA_MM2 * (original_dpi / 25.4) ** 2 + 1e-9),
    )
    halo = ceil(span / ratio) + 1
    tile = max(1, ORIGINAL_TILE_SIZE // ratio)
    candidates = np.zeros(source.shape, dtype=bool)
    for left, top, right, bottom in regions:
        for y in range(top, bottom, tile):
            end_y = min(y + tile, bottom)
            y0, y1 = max(0, y - halo), min(height, end_y + halo)
            for x in range(left, right, tile):
                end_x = min(x + tile, right)
                x0, x1 = max(0, x - halo), min(width, end_x + halo)
                ink = original[y0 * ratio:y1 * ratio, x0 * ratio:x1 * ratio] == 0
                _, labels, stats, _ = cv2.connectedComponentsWithStats(
                    np.uint8(ink), connectivity=8
                )
                lx, ly, w, h, size = stats.T
                dust = (
                    (size <= area) & (w <= span) & (h <= span)
                    & (lx >= max(1, (left - x0) * ratio))
                    & (ly >= max(1, (top - y0) * ratio))
                    & (lx + w <= min(ink.shape[1] - 1, (right - x0) * ratio))
                    & (ly + h <= min(ink.shape[0] - 1, (bottom - y0) * ratio))
                )
                dust[0] = False
                selected = dust[labels]
                footprint = (y1 - y0, ratio, x1 - x0, ratio)
                supported = selected.reshape(footprint).any(axis=(1, 3))
                unexplained = (ink & ~selected).reshape(footprint).any(axis=(1, 3))
                low_ink = source[y0:y1, x0:x1] < 255
                count, low_labels = cv2.connectedComponents(np.uint8(low_ink), connectivity=8)
                keep = np.ones(count, dtype=bool)
                keep[0] = False
                keep[low_labels[low_ink & (~supported | unexplained)]] = False
                for edge in (low_labels[0], low_labels[-1], low_labels[:, 0], low_labels[:, -1]):
                    keep[edge] = False
                local_core = low_labels[y - y0:end_y - y0, x - x0:end_x - x0]
                candidates[y:end_y, x:end_x] |= keep[local_core]
    return candidates


def confirm_scan_dust(
    source: np.ndarray,
    original: np.ndarray,
    source_dpi: float,
    original_dpi: float,
    blank_regions: Sequence[tuple[int, int, int, int]],
) -> tuple[np.ndarray | None, str]:
    scan, status = register_original_scan(source, original, source_dpi, original_dpi)
    mask = authorize_scan_dust(source, scan, blank_regions)
    if scan is not None and not blank_regions:
        return None, "NO_REVIEWED_BLANK_PAPER"
    return mask, status
