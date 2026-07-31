from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from . import __version__
from .cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from .dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from .gui_export import _select_output_path
from .reporting import REPORT_SCHEMA_VERSION, write_json_report
from .trace_document_export import export_trace_document_streaming
from .trace_dxf_entities import MAX_EDITABLE_POLYLINE_VERTICES
from .trace_gui_export import (
    DEFAULT_PALETTE,
    TraceExportCompletion,
    _editable_text_strategy,
    _multi_page_output_directory,
    _resolve_converter_on_ui,
    _start_single_export,
)


def _processed_page_indices(window: Any) -> tuple[int, ...]:
    """Return zero-based PDF page indexes that have a valid trace cache."""

    processed: list[int] = []
    for page_index in range(int(window._pdf_page_count)):
        state = window._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if cache_value and Path(str(cache_value)).exists():
            processed.append(page_index)
    return tuple(processed)


def export_current_page_from_window(window: Any) -> None:
    """Export only the page currently shown, even for a multi-page PDF."""

    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成或取消。")
        return
    _start_single_export(window)


def export_processed_pages_from_window(window: Any) -> None:
    """Export every processed PDF page and skip pages that are not ready."""

    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成或取消。")
        return
    if not bool(getattr(window, "_native_pdf_mode", False)):
        _start_single_export(window)
        return
    _start_processed_pages_export(window)


def _start_processed_pages_export(window: Any) -> None:
    window._save_current_pdf_state()
    processed_indices = _processed_page_indices(window)
    total_source_pages = int(window._pdf_page_count)
    if not processed_indices:
        QMessageBox.warning(
            window,
            "没有可导出的页面",
            "当前 PDF 还没有处理完成的页面。请先处理至少一页。",
        )
        return

    skipped_pages = tuple(
        page_index + 1
        for page_index in range(total_source_pages)
        if page_index not in processed_indices
    )
    if skipped_pages:
        skipped_text = "、".join(map(str, skipped_pages[:12]))
        if len(skipped_pages) > 12:
            skipped_text += "……"
        answer = QMessageBox.question(
            window,
            "导出已处理页面",
            f"将导出 {len(processed_indices)} 个已处理页面，"
            f"跳过 {len(skipped_pages)} 个未处理页面。\n\n"
            f"跳过页码：{skipped_text}\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

    selection = _select_output_path(
        window,
        default_name="drawing-processed-pages.dwg",
    )
    if selection is None:
        return
    requested_path, requested_dwg = selection
    output_directory = _multi_page_output_directory(requested_path)
    report_path = output_directory / "export.report.json"
    converter_path, converter_error = _resolve_converter_on_ui(
        window,
        requested_dwg,
    )
    target_version = str(
        window.dwg_version_combo.currentData()
        if getattr(window, "dwg_version_combo", None) is not None
        else "R2018"
    )
    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    all_pages = tuple(window.document_pages_for_export())
    selected_pages = tuple(
        (page_index, all_pages[page_index])
        for page_index in processed_indices
    )
    source_path = Path(window.current_path)
    page_scales = tuple(
        float(
            window._pdf_page_states.get(page_index, {}).get(
                "drawing_scale",
                1.0,
            )
        )
        for page_index in processed_indices
    )
    scale_description = (
        "1:1"
        if all(abs(value - 1.0) < 1e-9 for value in page_scales)
        else "per-page setting"
    )

    def operation(
        token: CancellationToken,
        progress: ProgressCallback,
    ) -> object:
        output_directory.mkdir(parents=True, exist_ok=True)
        dxf_paths: list[Path] = []
        dwg_paths: list[Path] = []
        page_records: list[dict[str, Any]] = []
        conversion_errors: list[str] = []
        total_trace_paths = 0
        total_trace_vertices = 0
        total_text_lines = 0
        total_signature_images = 0
        total_ocr_candidates = 0
        total_fallback_texts = 0
        total_source_text_outlines = 0
        total_residual_graphics = 0
        total_logos = 0
        downgrade_reasons: Counter[str] = Counter()
        selected_count = len(selected_pages)

        for position, (source_index, page) in enumerate(
            selected_pages,
            start=1,
        ):
            token.checkpoint()
            source_page_number = source_index + 1
            page_dxf = output_directory / f"page-{source_page_number:03d}.dxf"
            page_base = (position - 1) / max(selected_count, 1)
            page_span = 0.88 / max(selected_count, 1)

            def page_progress(stage: str, fraction: float) -> None:
                progress(
                    f"第 {source_page_number} 页：{stage}",
                    page_base + page_span * fraction,
                )

            result = export_trace_document_streaming(
                [page],
                page_dxf,
                include_underlay=include_underlay,
                total_pages=1,
                palette=DEFAULT_PALETTE,
                cancellation_token=token,
                progress_callback=page_progress,
            )
            dxf_paths.append(result.path)
            total_trace_paths += result.trace_path_count
            total_trace_vertices += result.trace_vertex_count
            total_text_lines += result.text_count
            total_signature_images += len(result.signature_paths)
            total_ocr_candidates += result.ocr_candidate_count
            total_fallback_texts += result.fallback_text_count
            total_source_text_outlines += result.source_text_outline_count
            total_residual_graphics += result.residual_graphic_count
            total_logos += result.logo_count
            downgrade_reasons.update(dict(result.text_downgrade_reasons))

            page_dwg: Path | None = None
            page_error: str | None = None
            if requested_dwg and converter_path is not None:
                try:
                    page_dwg = convert_dxf_to_dwg(
                        result.path,
                        output_directory / f"page-{source_page_number:03d}.dwg",
                        version=target_version,
                        converter_executable=(
                            converter_path
                            if converter_path.name.lower()
                            != "odafileconverter.exe"
                            else None
                        ),
                    )
                    dwg_paths.append(page_dwg)
                except DwgConversionUnavailable as exc:
                    page_error = str(exc)
                    conversion_errors.append(
                        f"第 {source_page_number} 页：{exc}"
                    )
            elif requested_dwg and converter_error:
                page_error = converter_error

            page_records.append(
                {
                    "page": source_page_number,
                    "structure_id": (
                        result.structure_ids[0]
                        if result.structure_ids
                        else None
                    ),
                    "dxf": str(result.path),
                    "dwg": str(page_dwg) if page_dwg is not None else None,
                    "trace_path_count": result.trace_path_count,
                    "trace_vertex_count": result.trace_vertex_count,
                    "ocr_text_line_count": result.text_count,
                    "ocr_candidate_count": result.ocr_candidate_count,
                    "text_fallback_outline_count": result.fallback_text_count,
                    "source_text_outline_count": (
                        result.source_text_outline_count
                    ),
                    "residual_graphic_count": result.residual_graphic_count,
                    "logo_count": result.logo_count,
                    "text_downgrade_reasons": dict(
                        result.text_downgrade_reasons
                    ),
                    "signature_overlays": [
                        str(signature_path)
                        for signature_path in result.signature_paths
                    ],
                    "scan_underlays": [
                        str(path) for path in result.underlay_paths
                    ],
                    "dwg_error": page_error,
                }
            )

        checkpoint(token)
        report_progress(progress, "写入已处理页面导出清单", 0.97)
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "editable_line_text_processed_pdf_pages",
            "input": str(source_path),
            "output_directory": str(output_directory),
            "source_page_count": total_source_pages,
            "exported_page_count": len(page_records),
            "exported_pages": [item["page"] for item in page_records],
            "skipped_pages": list(skipped_pages),
            "pages": page_records,
            "scale": scale_description,
            "text_output_contract": {
                "ocr_candidate_count": total_ocr_candidates,
                "text_count": total_text_lines,
                "fallback_count": total_fallback_texts,
                "source_text_outline_count": total_source_text_outlines,
                "residual_count": total_residual_graphics,
                "logo_count": total_logos,
                "signature_count": total_signature_images,
                "downgrade_reasons": dict(
                    sorted(downgrade_reasons.items())
                ),
            },
            "editable_entity_strategy": {
                "one_dxf_per_pdf_page": True,
                "combined_modelspace_file": False,
                "paper_space_layouts": False,
                "page_block_wrappers": False,
                **_editable_text_strategy(),
                "max_vertices_per_non_text_polyline_piece": (
                    MAX_EDITABLE_POLYLINE_VERTICES
                ),
            },
            "warnings": [
                "只导出本次选择时已经完成处理的页面。",
                "未处理页面被跳过，不会阻止其他页面独立导出。",
                "每个 PDF 页面生成一个独立 DXF；页面之间不存在坐标或图层叠加。",
                "达到现有 OCR 内容合同的文字行均导出为原生 TEXT。",
                "无法安全抑制的源字形保留在默认关闭的 SOURCE_TEXT_OUTLINE。",
                *(
                    [converter_error]
                    if requested_dwg and converter_error
                    else []
                ),
                *conversion_errors,
            ],
        }
        write_json_report(report_path, report)
        report_progress(progress, "导出完成", 1.0)
        return TraceExportCompletion(
            result=None,
            report_path=report_path,
            dwg_path=None,
            dwg_error="\n".join(conversion_errors) or converter_error,
            document_mode=True,
            scale_description=scale_description,
            output_directory=output_directory,
            dxf_paths=tuple(dxf_paths),
            dwg_paths=tuple(dwg_paths),
            page_count=len(page_records),
            trace_path_count=total_trace_paths,
            trace_vertex_count=total_trace_vertices,
            text_count=total_text_lines,
            signature_count=total_signature_images,
            ocr_candidate_count=total_ocr_candidates,
            fallback_text_count=total_fallback_texts,
            source_text_outline_count=total_source_text_outlines,
            residual_graphic_count=total_residual_graphics,
            logo_count=total_logos,
            text_downgrade_reasons=tuple(
                sorted(downgrade_reasons.items())
            ),
        )

    def completed(value: object) -> None:
        completion: TraceExportCompletion = value  # type: ignore[assignment]
        summary = [
            f"输出目录：{completion.output_directory}",
            f"已导出页面：{completion.page_count}",
            f"跳过未处理页面：{len(skipped_pages)}",
            f"DXF 文件：{len(completion.dxf_paths)}",
            f"DWG 文件：{len(completion.dwg_paths)}",
            f"非文字图形：{completion.trace_path_count}",
            f"可编辑文字行：{completion.text_count}",
            f"不可编辑文字轮廓：{completion.fallback_text_count}",
            f"隐藏源字形备份：{completion.source_text_outline_count}",
            f"处理报告：{completion.report_path}",
        ]
        if completion.dwg_error:
            summary.append(f"部分或全部 DWG 未生成：{completion.dwg_error}")
            QMessageBox.warning(
                window,
                "已处理页面 DXF 已完成",
                "\n".join(summary),
            )
        else:
            QMessageBox.information(
                window,
                "已处理页面导出完成",
                "\n".join(summary),
            )
        window.statusBar().showMessage(
            f"已处理页面已独立导出：{completion.output_directory}"
        )

    window._start_processing(
        operation,
        completed,
        "正在导出已处理页面…",
    )
