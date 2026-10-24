from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from app import __version__
from app.core.cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from app.export.document_export import DocumentExportResult
from app.export.dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from app.export.document_export import ExportResult
from app.gui.export_dialogs import _choose_oda_converter, _select_output_path
from app.core.reporting import REPORT_SCHEMA_VERSION, write_json_report
from app.export.trace_dxf_entities import MAX_EDITABLE_POLYLINE_VERTICES, TracePalette
from app.export.trace_single_export import export_final_structure_dxf


DEFAULT_PALETTE = TracePalette(straight=5, curve=6, text_symbol=6)


@dataclass(frozen=True)
class TraceExportCompletion:
    result: DocumentExportResult | ExportResult | None
    report_path: Path
    dwg_path: Path | None
    dwg_error: str | None
    document_mode: bool
    scale_description: str = "1:1"
    output_directory: Path | None = None
    dxf_paths: tuple[Path, ...] = ()
    dwg_paths: tuple[Path, ...] = ()
    page_count: int = 0
    trace_path_count: int = 0
    trace_vertex_count: int = 0
    text_count: int = 0
    signature_count: int = 0
    ocr_candidate_count: int = 0
    fallback_text_count: int = 0
    source_text_outline_count: int = 0
    residual_graphic_count: int = 0
    logo_count: int = 0
    text_downgrade_reasons: tuple[tuple[str, int], ...] = ()
    arc_count: int = 0


def _resolve_converter_on_ui(
    window: Any,
    requested_dwg: bool,
) -> tuple[Path | None, str | None]:
    if not requested_dwg:
        return None, None
    try:
        return _choose_oda_converter(window), None
    except DwgConversionUnavailable as exc:
        QMessageBox.information(
            window,
            "将先导出 DXF",
            f"{exc}\n\n本次仍会在后台生成可直接打开的 DXF。",
        )
        return None, str(exc)


def _convert_in_worker(
    dxf_path: Path,
    requested_path: Path,
    requested_dwg: bool,
    converter_path: Path | None,
    target_version: str,
    previous_error: str | None,
    *,
    cancellation_token: CancellationToken | None,
    progress_callback: ProgressCallback | None,
) -> tuple[Path | None, str | None]:
    if not requested_dwg or converter_path is None:
        return None, previous_error
    checkpoint(cancellation_token)
    report_progress(progress_callback, "转换 DWG", 0.97)
    try:
        dwg_path = convert_dxf_to_dwg(
            dxf_path,
            requested_path,
            version=target_version,
            converter_executable=(
                converter_path
                if converter_path.name.lower() != "odafileconverter.exe"
                else None
            ),
        )
        return dwg_path, None
    except DwgConversionUnavailable as exc:
        return None, str(exc)


def _multi_page_output_directory(requested_path: Path) -> Path:
    return requested_path.parent / f"{requested_path.stem}-pages"


def _editable_text_strategy() -> dict[str, object]:
    return {
        "ocr_per_character_text_entities": False,
        "one_text_entity_per_non_space_character": False,
        "one_text_entity_per_recognized_line": True,
        "ocr_line_as_single_vector_block": False,
        "ocr_insert_blocks": False,
        "native_unicode_text_entities": True,
        "editability_independent_from_font_choice": True,
        "unsafe_text_layer": "SOURCE_TEXT_OUTLINE",
        "unsafe_text_layer_default_visible": False,
        "unreliable_text_layer": "TEXT_FALLBACK_OUTLINE",
        "absolute_font_path_embedded": False,
        "non_uniform_text_scaling": False,
        "ocr_unicode_preserved_as_line_xdata": True,
    }


def _start_single_export(window: Any) -> None:
    project = getattr(window, "_review_project", None)
    from app.core.manual_text_recovery import replay as replay_manual

    manual_text_count = (
        sum(r["action"] == "CONFIRM_LAYOUT" for r in replay_manual(project).values())
        if project
        else 0
    )
    if project is not None and (project.dirty or project.path is None):
        QMessageBox.warning(window, "校对尚未保存", "请先保存校对项目，再导出正式CAD。")
        return
    try:
        text_review = project.validated_review() if project is not None else None
    except (OSError, ValueError) as exc:
        QMessageBox.critical(window, "校对项目不可导出", str(exc))
        return
    structure = getattr(window, "_final_structure", None)
    if structure is None or window.corrected_image is None:
        QMessageBox.warning(window, "尚无处理结果", "请先处理当前页。")
        return
    if getattr(window, "_preview_structure_id", None) != structure.structure_id:
        QMessageBox.critical(
            window,
            "预览状态已失效",
            "当前预览与最终结构数据不一致，请重新处理当前页后再导出。",
        )
        return
    selection = _select_output_path(window, default_name="drawing-page.dwg")
    if selection is None:
        return
    requested_path, requested_dwg = selection
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
    scan_path = dxf_path.with_name(f"{dxf_path.stem}.scan.png")
    converter_path, converter_error = _resolve_converter_on_ui(window, requested_dwg)
    target_version = str(
        window.dwg_version_combo.currentData()
        if getattr(window, "dwg_version_combo", None) is not None
        else "R2018"
    )
    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    multiplier_getter = getattr(window, "_export_drawing_multiplier", None)
    drawing_multiplier = (
        float(project.manifest["export_settings"]["drawing_multiplier"])
        if project is not None
        else float(
            multiplier_getter()
            if callable(multiplier_getter)
            else window._drawing_scale()
        )
    )
    selected_ratio = float(window._drawing_scale())
    explicit_model_calibration = bool(
        getattr(window, "_has_explicit_model_calibration", lambda: False)()
    )
    calibration = project.calibration if project is not None else window.calibration
    raster_image = window.corrected_image.copy() if include_underlay else None
    source_path = Path(window.current_path) if window.current_path is not None else None
    threshold = getattr(window, "_trace_threshold", None)
    foreground_pixels = int(getattr(window, "_trace_foreground_pixels", 0))

    def operation(token: CancellationToken, progress: ProgressCallback) -> object:
        result = export_final_structure_dxf(
            structure,
            dxf_path,
            calibration,
            drawing_multiplier=drawing_multiplier,
            trace_color=7,
            palette=DEFAULT_PALETTE,
            raster_image=raster_image,
            raster_output_path=scan_path if include_underlay else None,
            cancellation_token=token,
            progress_callback=lambda stage, fraction: progress(stage, 0.94 * fraction),
            text_review=text_review,
        )
        dwg_path, dwg_error = _convert_in_worker(
            dxf_path,
            requested_path,
            requested_dwg,
            converter_path,
            target_version,
            converter_error,
            cancellation_token=token,
            progress_callback=progress,
        )
        if dwg_path is not None:
            result = replace(result, dwg_path=dwg_path, output_format="DWG")
        scale_description = (
            "已知长度两点标定"
            if explicit_model_calibration
            else f"1:{int(selected_ratio)}"
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "editable_line_text_single_page",
            "input": str(source_path) if source_path is not None else None,
            "text_review": (
                {
                    "snapshot_uuid": project.snapshot_uuid,
                    "export_version": project.manifest["export_version"],
                    "project": str(project.path),
                    "records": len(project.records),
                }
                if project
                else None
            ),
            "trace": {
                "structure_id": result.structure_id,
                "path_count": result.trace_path_count,
                "vertex_count": result.trace_vertex_count,
                "arc_count": result.arc_count,
                "hatch_count": result.hatch_count,
                "threshold": threshold,
                "foreground_pixels": foreground_pixels,
                "ocr_text_line_count": result.text_count - manual_text_count,
                "manual_text_insertion_count": manual_text_count,
                "native_text_total": result.text_count,
                "ocr_candidate_count": result.ocr_candidate_count,
                "text_fallback_outline_count": (result.fallback_text_count),
                "source_text_outline_count": (result.source_text_outline_count),
                "residual_graphic_count": result.residual_graphic_count,
                "logo_count": result.logo_count,
                "signature_image_count": len(result.signature_paths),
                "text_downgrade_reasons": dict(result.text_downgrade_reasons),
            },
            "scale_source": scale_description,
            "drawing_multiplier": drawing_multiplier,
            "model_mm_per_pixel": result.mm_per_pixel,
            "editable_entity_strategy": {
                "page_block_wrappers": False,
                "groups": False,
                "hatches": bool(result.hatch_count),
                **_editable_text_strategy(),
                "max_vertices_per_non_text_polyline_piece": MAX_EDITABLE_POLYLINE_VERTICES,
            },
            "text_output_contract": {
                "ocr_candidate_count": result.ocr_candidate_count,
                "text_count": result.text_count,
                "fallback_count": result.fallback_text_count,
                "source_text_outline_count": (result.source_text_outline_count),
                "residual_count": result.residual_graphic_count,
                "logo_count": result.logo_count,
                "signature_count": result.signature_count,
                "downgrade_reasons": dict(result.text_downgrade_reasons),
            },
            "export": {
                **asdict(result),
                "path": str(result.path),
                "underlay_path": str(result.underlay_path)
                if result.underlay_path
                else None,
                "dwg_path": str(result.dwg_path) if result.dwg_path else None,
            },
            "warnings": [
                "达到现有 OCR 内容合同的文字均作为可编辑 TEXT 导出。",
                "无法安全抑制的源字形保留在默认关闭的 SOURCE_TEXT_OUTLINE，低可靠文字保留在 TEXT_FALLBACK_OUTLINE。",
                "标题栏签名作为透明顶层图像导出，并与边框分层。",
                "DXF 不写入导出电脑的绝对字体路径；不同 CAD 环境可能使用不同 Unicode 字体显示同一内容。",
                f"超长非文字图形按最多 {MAX_EDITABLE_POLYLINE_VERTICES} 个顶点拆分。",
                *([f"DWG 转换未完成：{dwg_error}"] if dwg_error else []),
            ],
        }
        write_json_report(report_path, report)
        report_progress(progress, "导出完成", 1.0)
        return TraceExportCompletion(
            result=result,
            report_path=report_path,
            dwg_path=dwg_path,
            dwg_error=dwg_error,
            document_mode=False,
            scale_description=scale_description,
            text_count=result.text_count,
            arc_count=result.arc_count,
            signature_count=len(result.signature_paths),
            ocr_candidate_count=result.ocr_candidate_count,
            fallback_text_count=result.fallback_text_count,
            source_text_outline_count=(result.source_text_outline_count),
            residual_graphic_count=result.residual_graphic_count,
            logo_count=result.logo_count,
            text_downgrade_reasons=result.text_downgrade_reasons,
        )

    def completed(value: object) -> None:
        completion: TraceExportCompletion = value  # type: ignore[assignment]
        result: ExportResult = completion.result  # type: ignore[assignment]
        summary = [
            *([f"DWG：{completion.dwg_path}"] if completion.dwg_path else []),
            f"DXF：{result.path}",
            f"非文字图形：{result.trace_path_count}",
            f"可编辑圆弧：{result.arc_count}",
            f"可编辑文字行：{result.text_count}",
            f"不可编辑文字轮廓：{result.fallback_text_count}",
            f"隐藏源字形备份：{result.source_text_outline_count}",
            f"不可靠图形残留：{result.residual_graphic_count}",
            f"Logo：{result.logo_count}",
            f"签名图像：{len(result.signature_paths)}",
            f"图形顶点：{result.trace_vertex_count}",
            f"输出比例：{completion.scale_description}",
            "文字方式：每个识别文字行一个可编辑 TEXT",
            f"处理报告：{completion.report_path}",
        ]
        if completion.dwg_error:
            summary.append(f"DWG 未生成：{completion.dwg_error}")
            QMessageBox.warning(window, "DXF 已完成，DWG 未生成", "\n".join(summary))
        else:
            QMessageBox.information(window, "CAD 导出完成", "\n".join(summary))
        window.statusBar().showMessage(
            f"当前页 CAD 已导出：{completion.dwg_path or result.path}"
        )

    window._start_processing(operation, completed, "正在后台导出当前页 CAD…")
