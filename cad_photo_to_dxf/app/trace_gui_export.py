from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from . import __version__
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .document_export import DocumentExportResult
from .dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from .dxf_exporter import ExportResult
from .gui_export import _choose_oda_converter, _select_output_path
from .reporting import REPORT_SCHEMA_VERSION, write_json_report
from .trace_document_export import export_trace_document_streaming
from .trace_dxf_entities import MAX_EDITABLE_POLYLINE_VERTICES, TracePalette
from .trace_single_export import export_exact_trace_dxf


DEFAULT_PALETTE = TracePalette(straight=5, curve=3, text_symbol=6)


@dataclass(frozen=True)
class TraceExportCompletion:
    result: DocumentExportResult | ExportResult
    report_path: Path
    dwg_path: Path | None
    dwg_error: str | None
    document_mode: bool
    scale_description: str = "1:1"


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


def _document_missing_pages(window: Any) -> list[int]:
    missing: list[int] = []
    for page_index in range(int(window._pdf_page_count)):
        state = window._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if not cache_value or not Path(str(cache_value)).exists():
            missing.append(page_index + 1)
    return missing


def _start_document_export(window: Any) -> None:
    if not bool(getattr(window, "_native_pdf_mode", False)):
        return
    window._save_current_pdf_state()
    missing = _document_missing_pages(window)
    if missing:
        page_text = "、".join(map(str, missing[:12]))
        if len(missing) > 12:
            page_text += "……"
        QMessageBox.warning(
            window,
            "部分页面尚未生成 CAD 轮廓",
            f"尚未处理的页码：{page_text}\n\n"
            "请先点击“生成当前 PDF 全部页 CAD 轮廓”，再一次性导出。",
        )
        return

    selection = _select_output_path(window, default_name="drawing-all-pages.dwg")
    if selection is None:
        return
    requested_path, requested_dwg = selection
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
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
    pages = window.document_pages_for_export()
    total_pages = int(window._pdf_page_count)
    source_path = Path(window.current_path)
    page_scales = tuple(
        float(window._pdf_page_states.get(index, {}).get("drawing_scale", 1.0))
        for index in range(total_pages)
    )
    scale_description = (
        "1:1"
        if all(abs(value - 1.0) < 1e-9 for value in page_scales)
        else "per-page setting"
    )

    def operation(token: CancellationToken, progress: ProgressCallback) -> object:
        result = export_trace_document_streaming(
            pages,
            dxf_path,
            include_underlay=include_underlay,
            total_pages=total_pages,
            palette=DEFAULT_PALETTE,
            cancellation_token=token,
            progress_callback=lambda stage, fraction: progress(stage, 0.94 * fraction),
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
        checkpoint(token)
        report_progress(progress, "写入导出报告", 0.99)
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "ocr_complete_line_exact_cad_all_pdf_pages",
            "input": str(source_path),
            "page_count": result.page_count,
            "trace_path_count": result.trace_path_count,
            "trace_vertex_count": result.trace_vertex_count,
            "editable_text_count": result.text_count,
            "layouts": [],
            "page_groups": [],
            "scan_underlays": [str(path) for path in result.underlay_paths],
            "dxf": str(result.path),
            "dwg": str(dwg_path) if dwg_path is not None else None,
            "scale": scale_description,
            "editable_entity_strategy": {
                "page_block_wrappers": False,
                "groups": False,
                "hatches": False,
                "paper_space_layouts": False,
                "all_pages_spatially_separated_in_modelspace": True,
                "later_page_layers_default_off": True,
                "ocr_complete_lines_as_cad_text": True,
                "ocr_raster_outlines_exported": False,
                "max_vertices_per_polyline_piece": MAX_EDITABLE_POLYLINE_VERTICES,
            },
            "warnings": [
                "为避免 LibreCAD 叠加纸空间布局，全部页面采用模型空间分离排布。",
                "第一页图层默认开启；后续页面图层默认关闭，可按 PAGE_### 前缀切换。",
                "OCR 按完整文字行导出为可编辑 CAD TEXT；匹配到的扫描文字轮廓不再重复写入 DXF。",
                "颜色分类只用于检查；不会简化、吸附或合并非文字轮廓坐标。",
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
            document_mode=True,
            scale_description=report["scale"],
        )

    def completed(value: object) -> None:
        completion = value  # type: ignore[assignment]
        result: DocumentExportResult = completion.result
        summary = [
            *([f"DWG：{completion.dwg_path}"] if completion.dwg_path else []),
            f"DXF：{result.path}",
            f"PDF 页面：{result.page_count}",
            f"非文字 CAD 轮廓：{result.trace_path_count}",
            f"完整可编辑文字行：{result.text_count}",
            f"轮廓顶点：{result.trace_vertex_count}",
            f"输出比例：{completion.scale_description}",
            "页面方式：模型空间分离排布；第 2 页起图层默认关闭",
            "文字方式：每个 OCR 文字行是一个完整 TEXT，不再叠加扫描文字轮廓",
            f"处理报告：{completion.report_path}",
        ]
        if completion.dwg_error:
            summary.append(f"DWG 未生成：{completion.dwg_error}")
            QMessageBox.warning(window, "DXF 已完成，DWG 未生成", "\n".join(summary))
        else:
            QMessageBox.information(window, "CAD 导出完成", "\n".join(summary))
        window.statusBar().showMessage(
            f"全部 PDF 页面 CAD 已导出：{completion.dwg_path or result.path}"
        )

    window._start_processing(operation, completed, "正在后台导出全部 PDF 页面 CAD…")


def _start_single_export(window: Any) -> None:
    trace_paths = tuple(getattr(window, "_trace_paths", ()))
    if not trace_paths or window.binary_image is None or window.corrected_image is None:
        QMessageBox.warning(window, "尚无 CAD 轮廓", "请先生成当前页 CAD 轮廓。")
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
    drawing_multiplier = float(
        multiplier_getter() if callable(multiplier_getter) else window._drawing_scale()
    )
    selected_ratio = float(window._drawing_scale())
    explicit_model_calibration = bool(
        getattr(window, "_has_explicit_model_calibration", lambda: False)()
    )
    binary_shape = tuple(window.binary_image.shape[:2])
    calibration = window.calibration
    raster_image = window.corrected_image.copy() if include_underlay else None
    source_path = Path(window.current_path) if window.current_path is not None else None
    threshold = getattr(window, "_trace_threshold", None)
    foreground_pixels = int(getattr(window, "_trace_foreground_pixels", 0))
    texts = tuple(getattr(window, "_ocr_texts", ()))

    def operation(token: CancellationToken, progress: ProgressCallback) -> object:
        result = export_exact_trace_dxf(
            trace_paths,
            dxf_path,
            binary_shape[0],
            calibration,
            image_width=binary_shape[1],
            drawing_multiplier=drawing_multiplier,
            trace_color=7,
            palette=DEFAULT_PALETTE,
            texts=texts,
            raster_image=raster_image,
            raster_output_path=scan_path if include_underlay else None,
            cancellation_token=token,
            progress_callback=lambda stage, fraction: progress(stage, 0.94 * fraction),
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
            "mode": "ocr_complete_line_exact_cad_single_page",
            "input": str(source_path) if source_path is not None else None,
            "trace": {
                "path_count": result.trace_path_count,
                "vertex_count": result.trace_vertex_count,
                "threshold": threshold,
                "foreground_pixels": foreground_pixels,
                "editable_text_count": result.text_count,
            },
            "scale_source": scale_description,
            "drawing_multiplier": drawing_multiplier,
            "model_mm_per_pixel": result.mm_per_pixel,
            "editable_entity_strategy": {
                "block_wrappers": False,
                "groups": False,
                "hatches": False,
                "ocr_complete_lines_as_cad_text": True,
                "ocr_raster_outlines_exported": False,
                "max_vertices_per_polyline_piece": MAX_EDITABLE_POLYLINE_VERTICES,
            },
            "export": {
                **asdict(result),
                "path": str(result.path),
                "underlay_path": str(result.underlay_path) if result.underlay_path else None,
                "dwg_path": str(result.dwg_path) if result.dwg_path else None,
            },
            "warnings": [
                "OCR 按完整文字行导出为可编辑 CAD TEXT；匹配到的扫描文字轮廓不再重复写入 DXF。",
                f"超长连通轮廓按最多 {MAX_EDITABLE_POLYLINE_VERTICES} 个顶点拆为独立可编辑折线。",
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
        )

    def completed(value: object) -> None:
        completion = value  # type: ignore[assignment]
        result: ExportResult = completion.result
        summary = [
            *([f"DWG：{completion.dwg_path}"] if completion.dwg_path else []),
            f"DXF：{result.path}",
            f"非文字 CAD 轮廓：{result.trace_path_count}",
            f"完整可编辑文字行：{result.text_count}",
            f"轮廓顶点：{result.trace_vertex_count}",
            f"输出比例：{completion.scale_description}",
            "文字方式：每个 OCR 文字行是一个完整 TEXT，不再叠加扫描文字轮廓",
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


def export_trace_from_window(window: Any) -> None:
    """Start a responsive background export instead of blocking the Qt UI thread."""

    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成或取消。")
        return
    if bool(getattr(window, "_native_pdf_mode", False)):
        _start_document_export(window)
    else:
        _start_single_export(window)
