from __future__ import annotations

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .content_ownership import (
    binary_from_foreground,
    graphic_source_mask,
    partition_content,
    protected_object_regions,
    signature_source_mask,
    without_owned_pixels,
)
from .final_structure import build_final_structure
from .logo_detection import detect_logo_regions
from .ocr_outline_export import accepted_ocr_texts
from .ocr_layout import constrain_texts_to_table_cells
from .ocr_overlap import collapse_overlapping_candidates
from .ocr_pipeline import recognize_text_candidates_optimized
from .raster_trace import RasterTraceResult, trace_binary
from .scan_artifact_filter import suppress_scan_artifact_traces
from .scan_cleanup import prepare_scan_page
from .signature_overlay import (
    detect_signature_regions,
)
from .straight_line_reconstruction import reconstruct_straight_lines


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

    signatures = detect_signature_regions(prepared.binary)
    logos = detect_logo_regions(prepared.binary)
    if texts:
        texts = constrain_texts_to_table_cells(prepared.binary, texts)
        texts = collapse_overlapping_candidates(texts)

    # Classification happens once. Signatures and explicit logos exclude only
    # their actual source ink from structural detection. No OCR rectangle may
    # cut a title-block rule, wall, leader or symbol.
    signature_mask = signature_source_mask(prepared.binary, signatures)
    graphic_mask = graphic_source_mask(prepared.binary, logos)
    protected_mask = protected_object_regions(
        prepared.binary,
        texts=texts,
        logos=logos,
        signatures=signatures,
    )
    line_binary = without_owned_pixels(
        prepared.binary,
        signature_mask,
        graphic_mask,
    )

    report_progress(progress_callback, "line-reconstruction", 0.47 if enable_ocr else 0.08)
    straight_lines = reconstruct_straight_lines(
        line_binary,
        scan_support_gray=(
            None
            if prepared.clean_digital
            else prepared.gray
        ),
        protected_mask=protected_mask,
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

    ownership = partition_content(
        prepared.binary,
        lines=straight_lines,
        texts=texts,
        signatures=signatures,
        logos=logos,
        graphic_mask=graphic_mask,
        signature_mask=signature_mask,
    )
    residual_binary = binary_from_foreground(ownership.residual)
    artifact_removed = 0
    if not prepared.clean_digital and np.any(ownership.residual):
        residual_paths = trace_binary(
            residual_binary,
            cancellation_token=cancellation_token,
        )
        artifact_result = suppress_scan_artifact_traces(
            prepared.gray,
            residual_binary,
            residual_paths,
        )
        if artifact_result.removed_root_count:
            residual_binary = artifact_result.binary
            artifact_removed = artifact_result.removed_root_count

    residual_foreground = np.where(residual_binary < 128, 255, 0).astype(np.uint8)
    contour_binary = binary_from_foreground(
        cv2.max(residual_foreground, ownership.graphic)
    )

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
    if artifact_removed:
        warnings.append(
            f"已从最终 CAD 残留轮廓中清除 {artifact_removed} "
            "组折痕、胶带、撕裂或跨空白飞线。"
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
            f"可编辑单行文字，{retained_count} 个保留为原始源轮廓且不改判为图像。"
        )
    if signatures:
        warnings.append(
            f"已提取 {len(signatures)} 个完整签名图像并置于前景图层。"
        )
    observations = (
        {
            "event": "ownership_partitioned",
            "ambiguous_pixels": int(cv2.countNonZero(ownership.ambiguous)),
            "source_pixels": int(cv2.countNonZero(ownership.source)),
        },
    )
    final_structure = build_final_structure(
        source_size_px=(contour_binary.shape[1], contour_binary.shape[0]),
        contour_binary=contour_binary,
        contours=tuple(paths),
        straight_lines=tuple(straight_lines),
        texts=tuple(texts),
        logos=tuple(logos),
        signatures=tuple(signatures),
        preview_binary=prepared.binary,
        threshold=prepared.threshold,
        warnings=tuple(warnings),
        provenance={
            "pipeline": "optimized_trace",
            "clean_digital": bool(prepared.clean_digital),
        },
        observations=observations,
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
        logos=tuple(logos),
        final_structure=final_structure,
    )
