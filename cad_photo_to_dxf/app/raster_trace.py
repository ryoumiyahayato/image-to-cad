from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress


@dataclass(frozen=True)
class TracePath:
    """One closed boundary in source-image pixel coordinates.

    The paths represent the printed regions themselves rather than an inferred
    wall/axis/structure model. ``parent`` and ``depth`` preserve the contour
    nesting needed for counters in text and holes in symbols.
    """

    points: tuple[tuple[float, float], ...]
    parent: int | None
    depth: int
    root: int


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


def make_black_white(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
) -> tuple[np.ndarray, int, dict[str, np.ndarray]]:
    """Create the literal foreground mask used to construct CAD boundaries.

    PDF renderings generally have a perfectly white background. When at least
    90% of the page is exactly white, every non-white anti-aliased pixel is
    treated as printed content by using threshold 254. Photographs and noisy
    scans instead use a conservative Otsu threshold. No opening, closing,
    skeletonization, Hough transform, snapping, merging, or semantic text
    suppression is performed.
    """

    gray = _to_gray(image)
    if foreground_threshold is None:
        exact_white_ratio = float(np.count_nonzero(gray == 255)) / float(gray.size)
        if exact_white_ratio >= 0.90:
            threshold = 254
        else:
            otsu_value, _ = cv2.threshold(
                gray,
                0,
                255,
                cv2.THRESH_BINARY | cv2.THRESH_OTSU,
            )
            threshold = int(min(245, max(200, round(float(otsu_value)))))
    else:
        threshold = int(max(1, min(254, foreground_threshold)))
    _unused, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    if int(np.count_nonzero(binary == 0)) > binary.size // 2:
        binary = 255 - binary

    stages = {
        "灰度原图": gray,
        "CAD 轮廓来源": binary,
    }
    return np.ascontiguousarray(binary), threshold, stages


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


def trace_image(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
    enable_ocr: bool = False,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RasterTraceResult:
    checkpoint(cancellation_token)
    texts: tuple[TextCandidate, ...] = ()
    warnings: list[str] = []
    stages: dict[str, np.ndarray] = {}

    if enable_ocr:
        from .ocr_recognition import recognize_text_candidates, render_ocr_overlay

        report_progress(progress_callback, "ocr-before-trace", 0.01)
        texts, ocr_warnings = recognize_text_candidates(
            image,
            cancellation_token=cancellation_token,
            progress_callback=(
                None
                if progress_callback is None
                else lambda stage, fraction: progress_callback(
                    stage,
                    0.02 + 0.28 * fraction,
                )
            ),
        )
        warnings.extend(ocr_warnings)
        if texts:
            stages["OCR 文字识别结果"] = render_ocr_overlay(image, texts)

    report_progress(progress_callback, "foreground-mask", 0.32 if enable_ocr else 0.02)
    binary, threshold, trace_stages = make_black_white(
        image,
        foreground_threshold=foreground_threshold,
    )
    stages = {**trace_stages, **stages}
    paths = trace_binary(
        binary,
        cancellation_token=cancellation_token,
        progress_callback=(
            progress_callback
            if not enable_ocr or progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage,
                0.34 + 0.66 * fraction,
            )
        ),
    )
    foreground_pixels = int(np.count_nonzero(binary == 0))
    vertex_count = sum(len(path.points) for path in paths)
    if not paths and foreground_pixels:
        warnings.append("前景内容存在，但未形成可导出的闭合 CAD 边界。")
    if vertex_count > 1_000_000:
        warnings.append(
            "CAD 边界超过 100 万个顶点；内容保持不变，但 DXF/DWG 文件会较大。"
        )
    if texts:
        warnings.append(
            f"已在轮廓生成前识别 {len(texts)} 个可编辑文字对象；"
            "原文字轮廓将保留在默认关闭的回退图层。"
        )
    return RasterTraceResult(
        binary=binary,
        stages=stages,
        paths=paths,
        threshold=threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=tuple(warnings),
        texts=texts,
    )
