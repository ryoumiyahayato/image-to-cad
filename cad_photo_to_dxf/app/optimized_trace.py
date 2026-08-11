from __future__ import annotations

import cv2
import numpy as np

from .cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from .connectivity_safety import DEFAULT_CONNECTION_DPI
from .content_ownership import (
    arbitrate_content_candidates,
    binary_from_foreground,
    build_connection_protection,
    build_text_semantic_ownership,
    finalize_content_ownership,
    graphic_source_mask,
    partition_content,
    signature_source_mask,
    text_candidate_source_mask,
)
from .final_structure import build_final_structure
from .line_detect import LineSegment
from .logo_detection import detect_logo_regions
from .observability import (
    ObservationSink,
    observe,
    rasterize_lines,
    rasterize_text_boxes,
    texts_payload,
)
from .ocr_layout import constrain_texts_to_table_cells
from .ocr_overlap import collapse_overlapping_candidates
from .ocr_pipeline import recognize_text_candidates_optimized
from .performance_observability import (
    PerformanceCallback,
    emit_performance,
    performance_clock,
    record_performance,
)
from .raster_trace import RasterTraceResult, trace_binary
from .scan_artifact_filter import suppress_scan_artifact_traces
from .scan_cleanup import prepare_scan_page
from .signature_overlay import detect_signature_regions
from .straight_line_reconstruction import reconstruct_straight_lines
from .text_output_contract import (
    text_output_decisions,
    text_output_summary,
)


def trace_image_optimized(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
    enable_ocr: bool = False,
    source_dpi: float | None = DEFAULT_CONNECTION_DPI,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    observation_sink: ObservationSink | None = None,
    performance_callback: PerformanceCallback | None = None,
) -> RasterTraceResult:
    """Run OCR and tracing without constructing full-resolution UI overlays.

    Digital PDF pages keep literal non-white pixels. Real scans are normalized once
    and the same cleaned page is reused by OCR and tracing, avoiding duplicate work
    while suppressing folds, tape shadows, stains and damaged paper texture.
    """

    checkpoint(cancellation_token)
    if observation_sink is not None:
        observe(
            observation_sink,
            "original_page",
            image=image,
            payload={
                "shape": [int(value) for value in image.shape],
                "dtype": str(image.dtype),
            },
        )
    report_progress(progress_callback, "prepare-image", 0.02)
    prepared = prepare_scan_page(
        image,
        foreground_threshold=foreground_threshold,
        performance_callback=performance_callback,
    )
    if observation_sink is not None:
        observe(
            observation_sink,
            "original_gray",
            image=prepared.gray,
            payload={"clean_digital": bool(prepared.clean_digital)},
        )
        observe(
            observation_sink,
            "normalized_background",
            image=prepared.normalized,
            payload={"clean_digital": bool(prepared.clean_digital)},
        )
        observe(
            observation_sink,
            "binary_foreground",
            image=prepared.binary,
            payload={
                "threshold": int(prepared.threshold),
                "foreground_pixels": int(
                    np.count_nonzero(prepared.binary == 0)
                ),
            },
        )
        observe(
            observation_sink,
            "legacy_closing",
            payload={
                "executed": False,
                "reason": (
                    "Whole-page 2x1/1x2 morphological closing is removed from "
                    "the production path; this stage records its absence."
                ),
                "historical_introduction_commit": (
                    "d9fbda763e95c6dd7154934b801b59dbf034e711"
                ),
            },
            status="not_executed",
        )

    texts = ()
    warnings: list[str] = []
    if enable_ocr:
        ocr_started = performance_clock()
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
            observation_sink=observation_sink,
        )
        record_performance(performance_callback, "ocr", ocr_started)
        warnings.extend(ocr_warnings)
    else:
        emit_performance(performance_callback, "ocr", 0.0)
    if not enable_ocr and observation_sink is not None:
        for stage_key in (
            "ocr_raw_tiles",
            "ocr_rule_removed_tiles",
            "ocr_text_boxes",
        ):
            observe(
                observation_sink,
                stage_key,
                payload={"reason": "OCR is disabled for this trace."},
                status="not_executed",
            )

    signatures = detect_signature_regions(prepared.binary)
    logos = detect_logo_regions(prepared.binary)
    if texts:
        texts = constrain_texts_to_table_cells(prepared.binary, texts)
        texts = collapse_overlapping_candidates(texts)
    if enable_ocr and observation_sink is not None:
        observe(
            observation_sink,
            "ocr_text_boxes",
            image=rasterize_text_boxes(texts, prepared.binary.shape),
            payload={"texts": texts_payload(texts), "count": len(texts)},
        )

    # Classification happens once. Signatures and explicit logos exclude only
    # their actual source ink from structural detection. No OCR rectangle may
    # cut a title-block rule, wall, leader or symbol.
    signature_mask = signature_source_mask(prepared.binary, signatures)
    graphic_mask = graphic_source_mask(prepared.binary, logos)
    if observation_sink is not None:
        text_candidate_mask = text_candidate_source_mask(
            prepared.binary,
            texts,
        )
        observe(
            observation_sink,
            "text_candidate_mask",
            image=text_candidate_mask,
            payload={"role": "candidate", "count": len(texts)},
        )
        observe(
            observation_sink,
            "logo_candidate_mask",
            image=graphic_mask,
            payload={
                "role": "candidate",
                "count": len(logos),
                "regions": [item.payload() for item in logos],
            },
        )
        observe(
            observation_sink,
            "signature_candidate_mask",
            image=signature_mask,
            payload={
                "role": "candidate",
                "count": len(signatures),
                "regions": [item.payload() for item in signatures],
            },
        )
    connection_protection = build_connection_protection(
        prepared.binary,
        texts=texts,
        logos=logos,
        signatures=signatures,
    )
    protected_mask = connection_protection.mask
    report_progress(progress_callback, "line-reconstruction", 0.47 if enable_ocr else 0.08)
    late_restorations: list[LineSegment] = []
    line_candidates = reconstruct_straight_lines(
        prepared.binary,
        source_dpi=source_dpi,
        scan_support_gray=(
            None
            if prepared.clean_digital
            else prepared.gray
        ),
        protected_mask=protected_mask,
        protection_guards=dict(connection_protection.guards),
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage,
                (0.48 if enable_ocr else 0.09) + 0.22 * fraction,
            )
        ),
        observation_sink=observation_sink,
        performance_callback=performance_callback,
        late_restoration_output=late_restorations,
    )

    ownership_started = performance_clock()
    candidate_ownership = partition_content(
        prepared.binary,
        lines=line_candidates,
        texts=texts,
        signatures=signatures,
        logos=logos,
        graphic_mask=graphic_mask,
        signature_mask=signature_mask,
    )
    arbitrated = arbitrate_content_candidates(
        prepared.binary,
        lines=line_candidates,
        texts=texts,
        logos=logos,
        signatures=signatures,
        ownership=candidate_ownership,
    )
    ownership = finalize_content_ownership(
        prepared.binary,
        candidates=candidate_ownership,
        arbitrated=arbitrated,
    )
    record_performance(
        performance_callback,
        "ownership",
        ownership_started,
    )
    straight_lines = tuple(arbitrated.lines) + tuple(late_restorations)
    texts = arbitrated.texts
    logos = arbitrated.logos
    signatures = arbitrated.signatures
    text_decisions = text_output_decisions(texts)
    text_contract = text_output_summary(texts)
    text_semantics = build_text_semantic_ownership(
        prepared.binary,
        texts,
        ownership=ownership,
    )
    if observation_sink is not None:
        owner_map = np.zeros(prepared.binary.shape, dtype=np.uint8)
        for owner_code, mask in (
            (1, ownership.line),
            (2, ownership.text),
            (3, ownership.logo),
            (4, ownership.signature),
            (5, ownership.graphic),
            (6, ownership.residual),
        ):
            owner_map[mask > 0] = owner_code
        observe(
            observation_sink,
            "text_candidate_mask",
            image=ownership.text,
            payload={"role": "final-owned"},
        )
        observe(
            observation_sink,
            "logo_candidate_mask",
            image=ownership.logo,
            payload={
                "role": "final-owned",
                "count": len(logos),
                "regions": [item.payload() for item in logos],
            },
        )
        observe(
            observation_sink,
            "signature_candidate_mask",
            image=ownership.signature,
            payload={
                "role": "final-owned",
                "count": len(signatures),
                "regions": [item.payload() for item in signatures],
            },
        )
        observe(
            observation_sink,
            "structural_line_candidate_mask",
            image=ownership.line,
            payload={"role": "final-owned"},
        )
        observe(
            observation_sink,
            "conflict_mask",
            image=ownership.ambiguous,
            payload=ownership.payload(),
        )
        observe(
            observation_sink,
            "residual_mask",
            image=ownership.residual,
            payload={
                "role": "residual",
                "residual_pixels": int(cv2.countNonZero(ownership.residual)),
            },
        )
        observe(
            observation_sink,
            "residual_mask",
            image=owner_map,
            payload={
                "role": "pixel-lineage",
                "codebook": {
                    "0": "background",
                    "1": "structural_line",
                    "2": "text",
                    "3": "logo",
                    "4": "signature",
                    "5": "graphic",
                    "6": "residual",
                },
            },
        )
    outline_source = cv2.max(ownership.graphic, ownership.residual)
    primary_outline_source = np.where(
        (outline_source > 0)
        & (text_semantics.source_outline == 0)
        & (text_semantics.uncertain_outline == 0),
        255,
        0,
    ).astype(np.uint8)
    residual_binary = binary_from_foreground(primary_outline_source)
    artifact_removed = 0
    if not prepared.clean_digital and np.any(primary_outline_source):
        contour_started = performance_clock()
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
        record_performance(
            performance_callback,
            "contour_tracing",
            contour_started,
        )

    residual_foreground = np.where(residual_binary < 128, 255, 0).astype(np.uint8)
    contour_binary = binary_from_foreground(
        cv2.max(residual_foreground, ownership.logo)
    )
    if observation_sink is not None:
        final_line_mask = rasterize_lines(
            straight_lines,
            prepared.binary.shape,
        )
        observe(
            observation_sink,
            "final_structural_layer",
            image=final_line_mask,
            payload={
                "lines": len(straight_lines),
                "role": "exported-structural-lines",
            },
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.editable_source,
            payload={
                "texts": texts_payload(texts),
                "count": len(texts),
                "output_contract": text_contract.payload(),
                "semantic_ownership": text_semantics.payload(),
                "decisions": [
                    decision.payload()
                    for decision in text_decisions
                ],
            },
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.source_outline,
            payload={"role": "hidden-source-text-outline"},
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.uncertain_outline,
            payload={"role": "visible-uncertain-text-outline"},
        )
        observe(
            observation_sink,
            "final_outline_layer",
            image=contour_binary,
            payload={"role": "exported-contour-source"},
        )

    report_progress(progress_callback, "prepare-image", 0.71 if enable_ocr else 0.32)
    contour_started = performance_clock()
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
    record_performance(
        performance_callback,
        "contour_tracing",
        contour_started,
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
    if text_contract.ocr_candidate_count:
        warnings.append(
            f"识别到 {text_contract.ocr_candidate_count} 个文字候选，其中 "
            f"{text_contract.editable_text_count} 个导出为可编辑单行文字，"
            f"{text_contract.fallback_outline_count} 个进入 "
            "TEXT_FALLBACK_OUTLINE，"
            f"{text_contract.source_outline_backup_count} 个保留到默认关闭的 "
            "SOURCE_TEXT_OUTLINE，"
            f"{text_contract.residual_graphic_count} 个进入 "
            "RESIDUAL_GRAPHIC。"
        )
    if signatures:
        warnings.append(
            f"已提取 {len(signatures)} 个完整签名图像并置于前景图层。"
        )
    observations = (
        {
            "event": "ownership_partitioned",
            "ambiguous_pixels": int(cv2.countNonZero(ownership.ambiguous)),
            "residual_pixels": int(cv2.countNonZero(ownership.residual)),
            "graphic_fallback_pixels": int(
                cv2.countNonZero(ownership.graphic)
            ),
            "conflict_objects": len(ownership.conflicts),
            "downgrades": len(ownership.downgrades),
            "source_pixels": int(cv2.countNonZero(ownership.source)),
        },
        {
            "event": "text_output_contract",
            **text_contract.payload(),
            "semantic_ownership": text_semantics.payload(),
            "logo_count": len(logos),
            "signature_count": len(signatures),
        },
    )
    final_structure_started = performance_clock()
    final_structure = build_final_structure(
        source_size_px=(contour_binary.shape[1], contour_binary.shape[0]),
        contour_binary=contour_binary,
        contours=tuple(paths),
        straight_lines=tuple(straight_lines),
        texts=tuple(texts),
        logos=tuple(logos),
        signatures=tuple(signatures),
        editable_text_source_mask=text_semantics.editable_source,
        source_text_outline_mask=text_semantics.source_outline,
        uncertain_text_outline_mask=text_semantics.uncertain_outline,
        preview_binary=prepared.binary,
        threshold=prepared.threshold,
        warnings=tuple(warnings),
        provenance={
            "pipeline": "optimized_trace",
            "clean_digital": bool(prepared.clean_digital),
        },
        observations=observations,
    )
    record_performance(
        performance_callback,
        "final_structure_generation",
        final_structure_started,
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
