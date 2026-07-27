from __future__ import annotations

import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .ocr_outline_export import accepted_ocr_texts
from .ocr_layout import constrain_texts_to_table_cells
from .ocr_pipeline import recognize_text_candidates_optimized
from .raster_trace import RasterTraceResult, trace_binary
from .scan_cleanup import prepare_scan_page
from .signature_overlay import (
    detect_signature_regions,
    mark_graphic_texts,
    mark_signature_texts,
    suppress_signature_strokes,
    suppress_text_strokes,
)
from .straight_line_reconstruction import (
    reconstruct_straight_lines,
    suppress_reconstructed_lines,
)


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
        texts, ocr_warnings = recognize_text_candidates_optimized(
            prepared.gray,
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

    signatures = ()
    vector_binary = prepared.binary
    if texts:
        signatures = detect_signature_regions(prepared.binary, texts)
        texts = mark_signature_texts(texts, signatures)
        texts = mark_graphic_texts(texts, page_shape=prepared.binary.shape)
        texts = constrain_texts_to_table_cells(prepared.binary, texts)
        vector_binary = suppress_signature_strokes(vector_binary, signatures)
        vector_binary = suppress_text_strokes(
            vector_binary,
            accepted_ocr_texts(texts),
        )

    report_progress(progress_callback, "line-reconstruction", 0.47 if enable_ocr else 0.08)
    straight_lines = reconstruct_straight_lines(
        vector_binary,
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage,
                (0.48 if enable_ocr else 0.09) + 0.22 * fraction,
            )
        ),
    )
    contour_binary = suppress_reconstructed_lines(vector_binary, straight_lines)

    report_progress(progress_callback, "prepare-image", 0.71 if enable_ocr else 0.32)
    paths = trace_binary(
        contour_binary,
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else (
                (lambda stage, fraction: progress_callback(
                    stage,
                    0.72 + 0.28 * fraction,
                ))
                if enable_ocr
                else (lambda stage, fraction: progress_callback(
                    stage,
                    0.33 + 0.67 * fraction,
                ))
            )
        ),
    )
    foreground_pixels = int(np.count_nonzero(contour_binary == 0))
    vertex_count = sum(len(path.points) for path in paths)
    if not paths and foreground_pixels:
        warnings.append("页面中存在内容，但没有形成可导出的边界。")
    if vertex_count > 1_000_000:
        warnings.append("页面细节较多，生成的 CAD 文件可能较大。")
    if not prepared.clean_digital:
        warnings.append("已自动校正扫描底色并抑制纸张破损、阴影和污渍纹理。")
    if texts:
        editable_count = len(accepted_ocr_texts(texts))
        retained_count = max(0, len(texts) - editable_count)
        warnings.append(
            f"识别到 {len(texts)} 个文字候选，其中 {editable_count} 个导出为"
            f"可编辑单行文字，{retained_count} 个保留为图像。"
        )
    if signatures:
        warnings.append(
            f"已提取 {len(signatures)} 个完整签名图像并置于前景图层。"
        )
    return RasterTraceResult(
        binary=contour_binary,
        stages={},
        paths=paths,
        threshold=prepared.threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=tuple(warnings),
        texts=tuple(texts),
        signatures=tuple(signatures),
        straight_lines=tuple(straight_lines),
        preview_binary=np.ascontiguousarray(prepared.binary.copy()),
    )
