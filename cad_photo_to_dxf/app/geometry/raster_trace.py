from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.core.cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from app.geometry.line_detect import LineSegment
from app.core.trace_types import TracePath
from app.core.arc_types import ArcSegment
from app.core.native_fill import NativeFill
from app.ocr.signature_overlay import SignatureRegion

if TYPE_CHECKING:
    from app.core.structure import FinalStructure
    from app.ocr.logo_detection import LogoRegion




@dataclass(frozen=True)
class RasterTraceResult:
    binary: np.ndarray
    stages: dict[str, np.ndarray]
    paths: tuple[TracePath, ...]
    threshold: int
    foreground_pixels: int
    vertex_count: int
    warnings: tuple[str, ...] = ()
    texts: tuple[TextCandidate, ...] = ()
    signatures: tuple[SignatureRegion, ...] = ()
    straight_lines: tuple[LineSegment, ...] = ()
    preview_binary: np.ndarray | None = None
    logos: tuple[LogoRegion, ...] = ()
    final_structure: FinalStructure | None = None
    arcs: tuple[ArcSegment, ...] = ()
    native_fills: tuple[NativeFill, ...] = ()


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("Trace source image must not be empty")
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        code = cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        gray = cv2.cvtColor(image, code)
    else:
        raise ValueError("Trace source must be a grayscale, BGR, or BGRA image")
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return np.ascontiguousarray(gray)






def _deduplicate_points(
    points: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    result: list[tuple[float, float]] = []
    for point in points:
        normalized = (float(point[0]), float(point[1]))
        if not result or normalized != result[-1]:
            result.append(normalized)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return tuple(result)


def _fallback_box(contour: np.ndarray) -> tuple[tuple[float, float], ...]:
    x, y, width, height = cv2.boundingRect(contour)
    x -= 1
    y -= 1
    width = max(1, width)
    height = max(1, height)
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )


def trace_binary(
    binary: np.ndarray,
    *,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[TracePath, ...]:
    """Trace every connected foreground region at full image resolution.

    ``CHAIN_APPROX_SIMPLE`` removes only intermediate points that lie on the
    same horizontal, vertical, or diagonal run. It does not apply an epsilon,
    curve fit, Hough transform, or semantic simplification. Filling the retained
    contour tree reconstructs the same pixel mask while reducing CAD vertices
    and export memory substantially.
    """

    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Binary trace image must be a non-empty 2D image")
    if binary.dtype != np.uint8:
        raise ValueError("Binary trace image must use 8-bit pixels")

    checkpoint(cancellation_token)
    report_progress(progress_callback, "trace:prepare", 0.05)
    foreground = np.where(binary < 128, 255, 0).astype(np.uint8)
    padded = cv2.copyMakeBorder(
        foreground,
        1,
        1,
        1,
        1,
        cv2.BORDER_CONSTANT,
        value=0,
    )
    contours, hierarchy = cv2.findContours(
        padded,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if hierarchy is None or not contours:
        return ()

    raw_paths: list[tuple[tuple[float, float], ...] | None] = []
    total = len(contours)
    for index, contour in enumerate(contours):
        if index % 512 == 0:
            checkpoint(cancellation_token)
            report_progress(
                progress_callback,
                "trace:boundaries",
                0.08 + 0.78 * index / max(total, 1),
            )
        reshaped = contour.reshape(-1, 2)
        points = _deduplicate_points(
            (float(x - 1), float(y - 1)) for x, y in reshaped
        )
        if len(points) < 3:
            points = _fallback_box(contour)
        raw_paths.append(points if len(points) >= 3 else None)

    old_to_new: dict[int, int] = {}
    kept_old_indices: list[int] = []
    for old_index, points in enumerate(raw_paths):
        if points is not None:
            old_to_new[old_index] = len(kept_old_indices)
            kept_old_indices.append(old_index)

    def nearest_kept_parent(old_index: int) -> int | None:
        parent = int(hierarchy[0][old_index][3])
        while parent >= 0 and parent not in old_to_new:
            parent = int(hierarchy[0][parent][3])
        return old_to_new[parent] if parent >= 0 else None

    paths: list[TracePath] = []
    for old_index in kept_old_indices:
        new_parent = nearest_kept_parent(old_index)
        depth = 0
        ancestor = new_parent
        while ancestor is not None:
            depth += 1
            ancestor = paths[ancestor].parent
        root = new_parent if new_parent is not None else len(paths)
        while new_parent is not None and paths[root].parent is not None:
            root = paths[root].parent  # type: ignore[assignment]
        paths.append(
            TracePath(
                points=raw_paths[old_index] or (),
                parent=new_parent,
                depth=depth,
                root=root,
            )
        )

    report_progress(progress_callback, "trace:complete", 1.0)
    return tuple(paths)
