from __future__ import annotations

import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_fast import recognize_text_candidates_fast
from .raster_trace import RasterTraceResult, make_black_white, trace_binary


def trace_image_optimized(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
    enable_ocr: bool = False,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RasterTraceResult:
    """Run OCR and exact tracing without constructing full-resolution UI overlays."""

    checkpoint(cancellation_token)
    texts = ()
    warnings: list[str] = []
    if enable_ocr:
        texts, ocr_warnings = recognize_text_candidates_fast(
            image,
            cancellation_token=cancellation_token,
            progress_callback=(
                None
                if progress_callback is None
                else lambda stage, fraction: progress_callback(
                    stage,
                    0.02 + 0.43 * fraction,
                )
            ),
        )
        warnings.extend(ocr_warnings)

    report_progress(progress_callback, "prepare-image", 0.47 if enable_ocr else 0.03)
    binary, threshold, _stages = make_black_white(
        image,
        foreground_threshold=foreground_threshold,
    )
    paths = trace_binary(
        binary,
        cancellation_token=cancellation_token,
        progress_callback=(
            progress_callback
            if not enable_ocr or progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage,
                0.49 + 0.51 * fraction,
            )
        ),
    )
    foreground_pixels = int(np.count_nonzero(binary == 0))
    vertex_count = sum(len(path.points) for path in paths)
    if not paths and foreground_pixels:
        warnings.append("页面中存在内容，但没有形成可导出的边界。")
    if vertex_count > 1_000_000:
        warnings.append("页面细节较多，生成的 CAD 文件可能较大。")
    if texts:
        safe_count = sum(1 for item in texts if item.replacement_safe)
        warnings.append(
            f"识别到 {len(texts)} 个文字候选，其中 {safe_count} 个通过自动替换检查。"
        )
    return RasterTraceResult(
        binary=binary,
        stages={},
        paths=paths,
        threshold=threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=tuple(warnings),
        texts=tuple(texts),
    )
