from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import __version__
from .document_exporter import DocumentPage, export_document_dxf
from .dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from .gui_export import _choose_oda_converter
from .reporting import write_json_report


def export_document_from_window(window: Any):
    """Export the pages captured by the GUI into one DXF and optional DWG."""

    pages: list[DocumentPage] = list(getattr(window, "_document_pages", []))
    if not pages:
        QMessageBox.warning(
            window, "尚无合并页面", "请先将至少一个已识别页面加入合并文档。"
        )
        return None
    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成后再导出。")
        return None

    default_dir = Path.cwd() / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    selected_path, selected_filter = QFileDialog.getSaveFileName(
        window,
        "导出多页 CAD",
        str(default_dir / "combined-pages.dwg"),
        "AutoCAD DWG (*.dwg);;Drawing Exchange Format (*.dxf)",
    )
    if not selected_path:
        return None

    requested_path = Path(selected_path)
    if requested_path.suffix.lower() not in {".dwg", ".dxf"}:
        requested_path = requested_path.with_suffix(
            ".dwg" if selected_filter.startswith("AutoCAD DWG") else ".dxf"
        )
    requested_dwg = requested_path.suffix.lower() == ".dwg"
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
    include_underlays = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    export_ocr_text = bool(
        getattr(window, "export_ocr_text_checkbox", None)
        and window.export_ocr_text_checkbox.isChecked()
    )
    export_pages = pages
    if not export_ocr_text:
        export_pages = [replace(page, texts=()) for page in pages]

    dwg_error: str | None = None
    try:
        result = export_document_dxf(
            export_pages,
            dxf_path,
            include_underlays=include_underlays,
        )
        if requested_dwg:
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
                        converter
                        if converter.name.lower() != "odafileconverter.exe"
                        else None
                    ),
                )
                result = replace(result, dwg_path=dwg_path, output_format="DWG")
            except DwgConversionUnavailable as exc:
                dwg_error = str(exc)

        report = {
            "schema_version": "combined-document-1",
            "application_version": __version__,
            "input_pages": [
                {
                    "label": page.label,
                    "source_path": (
                        str(page.source_path) if page.source_path is not None else None
                    ),
                    "source_page": page.source_page,
                    "image_width": page.image_width,
                    "image_height": page.image_height,
                    "calibrated": page.calibration is not None,
                    "line_count": len(page.lines),
                    "circle_count": len(page.circles),
                    "text_count": len(page.texts) if export_ocr_text else 0,
                }
                for page in export_pages
            ],
            "export": {
                **asdict(result),
                "path": str(result.path),
                "dwg_path": str(result.dwg_path) if result.dwg_path else None,
                "underlay_path": (
                    str(result.underlay_path) if result.underlay_path else None
                ),
                "underlay_paths": [str(path) for path in result.underlay_paths],
            },
            "options": {
                "include_underlays": include_underlays,
                "export_ocr_text": export_ocr_text,
                "page_layout": "horizontal-modelspace",
                "page_groups": True,
            },
            "warnings": [
                "扫描底图是外部 PNG 引用，交付时必须与 CAD 文件一起移动。",
                "底图保持 PDF 渲染结果的像素细节；自动矢量实体不等同于原始 CAD 语义恢复。",
                *([f"DWG 转换未完成：{dwg_error}"] if dwg_error else []),
            ],
        }
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "多页导出失败", str(exc))
        return None

    output_lines = [
        f"合并页面：{result.page_count}",
        f"DXF：{result.path}",
        f"可编辑 LINE：{result.line_count}",
        f"可编辑 CIRCLE：{result.circle_count}",
        f"可编辑 OCR TEXT：{result.text_count}",
        f"扫描底图：{len(result.underlay_paths)} 个",
        f"处理报告：{report_path}",
    ]
    if result.dwg_path is not None:
        output_lines.insert(1, f"DWG：{result.dwg_path}")
    if dwg_error:
        output_lines.append(f"DWG 未生成：{dwg_error}")
        QMessageBox.warning(window, "DXF 已导出，DWG 未生成", "\n".join(output_lines))
    else:
        QMessageBox.information(window, "多页导出完成", "\n".join(output_lines))
    window.statusBar().showMessage(
        f"已导出 {result.page_count} 页合并 CAD：{result.dwg_path or result.path}"
    )
    return result, report_path
