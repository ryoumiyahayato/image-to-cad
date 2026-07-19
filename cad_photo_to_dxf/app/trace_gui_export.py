from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from . import __version__
from .document_export import DocumentExportResult
from .dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from .dxf_exporter import ExportResult, export_dxf
from .gui_export import _choose_oda_converter, _select_output_path
from .reporting import REPORT_SCHEMA_VERSION, write_json_report
from .trace_document_export import export_trace_document_streaming


def _convert_if_requested(
    window: Any,
    dxf_path: Path,
    requested_path: Path,
    requested_dwg: bool,
) -> tuple[Path | None, str | None]:
    if not requested_dwg:
        return None, None
    try:
        converter = _choose_oda_converter(window)
        target_version = (
            window.dwg_version_combo.currentData()
            if getattr(window, "dwg_version_combo", None) is not None
            else "R2018"
        )
        dwg_path = convert_dxf_to_dwg(
            dxf_path,
            requested_path,
            version=str(target_version or "R2018"),
            converter_executable=(
                converter if converter.name.lower() != "odafileconverter.exe" else None
            ),
        )
        return dwg_path, None
    except DwgConversionUnavailable as exc:
        return None, str(exc)


def export_trace_document(window: Any) -> tuple[DocumentExportResult, Path] | None:
    selection = _select_output_path(window, default_name="traced-document.dwg")
    if selection is None:
        return None
    requested_path, requested_dwg = selection
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
    try:
        result = export_trace_document_streaming(
            window.document_pages_for_export(),
            dxf_path,
        )
        dwg_path, dwg_error = _convert_if_requested(
            window,
            dxf_path,
            requested_path,
            requested_dwg,
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "full_fidelity_black_white_trace_document",
            "input": str(window.current_path),
            "page_count": result.page_count,
            "trace_path_count": result.trace_path_count,
            "trace_vertex_count": result.trace_vertex_count,
            "legacy_line_count": result.line_count,
            "layouts": list(result.layout_names),
            "page_groups": list(result.group_names),
            "scan_underlays": [str(path) for path in result.underlay_paths],
            "dxf": str(result.path),
            "dwg": str(dwg_path) if dwg_path is not None else None,
            "warnings": [
                "拓印实体是黑白像素区域的可编辑边界和 SOLID HATCH，不进行墙线、文字或符号语义推断。",
                "CAD 文件与 page-###.scan.png 应放在同一目录并一起移动。",
                *([f"DWG 转换未完成：{dwg_error}"] if dwg_error else []),
            ],
        }
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "拓印导出失败", str(exc))
        return None

    summary = [
        *([f"DWG：{dwg_path}"] if dwg_path is not None else []),
        f"DXF：{result.path}",
        f"页面：{result.page_count}",
        f"拓印边界：{result.trace_path_count}",
        f"拓印顶点：{result.trace_vertex_count}",
        f"PAGE 布局：{', '.join(result.layout_names)}",
        f"处理报告：{report_path}",
    ]
    if dwg_error:
        summary.append(f"DWG 未生成：{dwg_error}")
        QMessageBox.warning(window, "DXF 已导出，DWG 未生成", "\n".join(summary))
    else:
        QMessageBox.information(window, "完整拓印 CAD 导出完成", "\n".join(summary))
    window.statusBar().showMessage(f"完整拓印 CAD 已导出：{dwg_path or result.path}")
    return result, report_path


def export_trace_single(window: Any) -> tuple[ExportResult, Path] | None:
    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成后再导出。")
        return None
    trace_paths = tuple(getattr(window, "_trace_paths", ()))
    if not trace_paths or window.binary_image is None or window.corrected_image is None:
        QMessageBox.warning(window, "尚无拓印结果", "请先完成黑白拓印，再导出 CAD。")
        return None
    selection = _select_output_path(window, default_name="traced-page.dwg")
    if selection is None:
        return None
    requested_path, requested_dwg = selection
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
    scan_path = dxf_path.with_name(f"{dxf_path.stem}.scan.png")
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
    trace_color = int(window._trace_color())
    try:
        result = export_dxf(
            [],
            dxf_path,
            window.binary_image.shape[0],
            window.calibration,
            trace_paths=trace_paths,
            drawing_scale=drawing_multiplier,
            trace_color=trace_color,
            raster_image=window.corrected_image if include_underlay else None,
            raster_output_path=scan_path if include_underlay else None,
        )
        dwg_path, dwg_error = _convert_if_requested(
            window,
            dxf_path,
            requested_path,
            requested_dwg,
        )
        if dwg_path is not None:
            result = replace(result, dwg_path=dwg_path, output_format="DWG")
        scale_description = (
            "explicit_known_length"
            if explicit_model_calibration
            else f"1:{int(selected_ratio)}"
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "full_fidelity_black_white_trace_page",
            "input": str(window.current_path),
            "trace": {
                "path_count": result.trace_path_count,
                "vertex_count": result.trace_vertex_count,
                "threshold": getattr(window, "_trace_threshold", None),
                "foreground_pixels": getattr(window, "_trace_foreground_pixels", 0),
                "color_index": trace_color,
            },
            "scale_source": scale_description,
            "drawing_multiplier": drawing_multiplier,
            "model_mm_per_pixel": result.mm_per_pixel,
            "export": {
                **asdict(result),
                "path": str(result.path),
                "underlay_path": (
                    str(result.underlay_path) if result.underlay_path else None
                ),
                "dwg_path": str(result.dwg_path) if result.dwg_path else None,
            },
            "warnings": [
                "拓印保留黑白区域形状，不进行结构语义简化。",
                *([f"DWG 转换未完成：{dwg_error}"] if dwg_error else []),
            ],
        }
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "拓印导出失败", str(exc))
        return None

    scale_line = (
        "尺寸来源：已知长度两点标定（不再叠加图纸比例）"
        if explicit_model_calibration
        else f"图纸比例：1:{int(selected_ratio)}"
    )
    summary = [
        *([f"DWG：{result.dwg_path}"] if result.dwg_path is not None else []),
        f"DXF：{result.path}",
        f"拓印边界：{result.trace_path_count}",
        f"拓印顶点：{result.trace_vertex_count}",
        scale_line,
        f"模型坐标：{result.mm_per_pixel:.6f} mm/px",
        f"处理报告：{report_path}",
    ]
    if dwg_error:
        summary.append(f"DWG 未生成：{dwg_error}")
        QMessageBox.warning(window, "DXF 已导出，DWG 未生成", "\n".join(summary))
    else:
        QMessageBox.information(window, "完整拓印 CAD 导出完成", "\n".join(summary))
    return result, report_path


def export_trace_from_window(window: Any):
    if getattr(window, "_document_queue", None) or bool(
        getattr(window, "_native_pdf_mode", False)
    ):
        return export_trace_document(window)
    return export_trace_single(window)
