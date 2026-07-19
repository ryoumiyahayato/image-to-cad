from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .raster_trace import TracePath


@dataclass(frozen=True)
class TraceVerificationResult:
    reconstructed: np.ndarray
    overlay: np.ndarray
    matched_pixels: int
    missing_pixels: int
    extra_pixels: int

    @property
    def exact(self) -> bool:
        return self.missing_pixels == 0 and self.extra_pixels == 0


def reconstruct_trace_binary(
    shape: tuple[int, int],
    trace_paths: Sequence[TracePath],
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> np.ndarray:
    """Rasterize the exact contour tree used by CAD export back to black/white."""

    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("Verification image dimensions must be positive")
    reconstructed = np.full((height, width), 255, dtype=np.uint8)
    ordered = sorted(enumerate(trace_paths), key=lambda item: (item[1].depth, item[0]))
    total = max(len(ordered), 1)
    for position, (_index, path) in enumerate(ordered):
        if position % 256 == 0:
            checkpoint(cancellation_token)
            report_progress(progress_callback, "verify-rasterize", 0.85 * position / total)
        if len(path.points) < 3:
            continue
        contour = np.asarray(path.points, dtype=np.float64)
        contour = np.rint(contour).astype(np.int32).reshape(-1, 1, 2)
        fill_value = 0 if path.depth % 2 == 0 else 255
        cv2.fillPoly(reconstructed, [contour], fill_value, lineType=cv2.LINE_8)
    report_progress(progress_callback, "verify-rasterize", 0.85)
    return reconstructed


def verify_trace_paths(
    binary: np.ndarray,
    trace_paths: Sequence[TracePath],
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> TraceVerificationResult:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Verification source must be a non-empty binary image")
    source = np.where(binary < 128, 0, 255).astype(np.uint8)
    reconstructed = reconstruct_trace_binary(
        source.shape,
        trace_paths,
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
    )
    checkpoint(cancellation_token)
    source_black = source == 0
    reconstructed_black = reconstructed == 0
    matched = source_black & reconstructed_black
    missing = source_black & ~reconstructed_black
    extra = ~source_black & reconstructed_black

    overlay = np.full((*source.shape, 3), 255, dtype=np.uint8)
    # Blue means geometry exists in both the source mask and the CAD contour set.
    overlay[matched] = (255, 0, 0)
    # Red means the source contains ink that would be absent from CAD.
    overlay[missing] = (0, 0, 255)
    # Magenta means CAD would contain geometry absent from the source.
    overlay[extra] = (255, 0, 255)
    report_progress(progress_callback, "verify-compare", 1.0)
    return TraceVerificationResult(
        reconstructed=reconstructed,
        overlay=overlay,
        matched_pixels=int(np.count_nonzero(matched)),
        missing_pixels=int(np.count_nonzero(missing)),
        extra_pixels=int(np.count_nonzero(extra)),
    )
