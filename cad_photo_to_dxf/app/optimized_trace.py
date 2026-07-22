from __future__ import annotations

import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_pipeline import recognize_text_candidates_optimized
from .raster_trace import RasterTraceResult, trace_binary
from .scan_cleanup import prepare_scan_page


def trace_image_optimized(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
    enable_ocr: bool = False,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RasterTraceResult:
    """Run OCR and tracing without constructing full-resolution UI overlays.

    Digital PDF pages keep literal non-white pixels. Real scans are normalized once
    and the same cleaned page is reused by OCR and tracing, avoiding duplicate work
    while suppressing folds, tape shadows, stains and damaged paper texture.
    """

    checkpoint(cancellation_token)
    report_progress(progress_callback, "prepare-image", 0.02)
    prepared = prepare_scan_page(
        image,
        foreground_threshold=foreground_threshold,
    )

    texts = ()
    warnings: list[str] = []
    if enable_ocr:
        ocr_source = image if prepared.clean_digital else prepared.normalized
        texts, ocr_warnings = recognize_text_candidates_optimized(
            ocr_source,
            cancellation_token=cancellation_token,
            progress_callback=(
                None
                if progress_callback is None
                else lambda stage, fraction: progress_callback(
                    stage,
                    0.04 + 0.41 * fraction,
                )
            ),
        )
        warnings.extend(ocr_warnings)

    report_progress(progress_callback, "prepare-image", 0.47 if enable_ocr else 0.08)
    paths = trace_binary(
        prepared.binary,
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
    foreground_pixels = int(np.count_nonzero(prepared.binary == 0))
    vertex_count = sum(len(path.points) for path in paths)
    if not paths and foreground_pixels:
        warnings.append("页面中存在内容，但没有形成可导出的边界。")
    if vertex_count > 1_000_000:
        warnings.append("页面细节较多，生成的 CAD 文件可能较大。")
    if not prepared.clean_digital:
        warnings.append("已自动校正扫描底色并抑制纸张破损、阴影和污渍纹理。")
    if texts:
        safe_count = sum(1 for item in texts if item.replacement_safe)
        warnings.append(
            f"识别到 {len(texts)} 个文字候选，其中 {safe_count} 个通过自动替换检查。"
        )
    return RasterTraceResult(
        binary=prepared.binary,
        stages={},
        paths=paths,
        threshold=prepared.threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=tuple(warnings),
        texts=tuple(texts),
    )
