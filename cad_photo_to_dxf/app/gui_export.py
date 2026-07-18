from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import gui as _gui
from .auxiliary_recognition import CircleCandidate
from .document_export import export_scan_document
from .dwg_converter import (
    DwgConversionUnavailable,
    configure_oda_converter,
    convert_dxf_to_dwg,
)
from .dxf_exporter import ExportResult, export_dxf
from .quality import assess_image_quality
from .report_builder import ReportBuilder
from .reporting import write_json_report
from .resolution import image_resolution_scale


def _choose_oda_converter(window: Any) -> Path:
    configured = getattr(window, "_dwg_converter_path", None)
    if configure_oda_converter(configured):
        return Path(configured) if configured is not None else Path("ODAFileConverter.exe")

    default_location = Path("C:/Program Files/ODA")
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "选择 ODA File Converter",
        str(default_location if default_location.exists() else Path.home()),
        "ODA File Converter (ODAFileConverter.exe)",
    )
    if not selected:
        raise DwgConversionUnavailable(
            "未选择 ODAFileConverter.exe；已保留可直接打开的 DXF。"
        )
    converter_path = Path(selected)
    configure_oda_converter(converter_path)
    window._dwg_converter_path = converter_path
    return converter_path


def export_from_window(
    window: Any,
    *,
    circles: list[CircleCandidate] | None = None,
) -> tuple[ExportResult, Path] | None:
    """Export one or many scan-backed sheets and optionally convert to DWG."""
    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成后再导出。")
        return None
    if window.original_image is None or window.corrected_image is None:
        QMessageBox.warning(window, "状态不完整", "请先导入图纸。")
        return None

    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    is_pdf_document = bool(
        getattr(window, "_native_pdf_mode", False)
        and getattr(window, "merge_all_pages_checkbox", None)
        and window.merge_all_pages_checkbox.isChecked()
        and getattr(window, "_pdf_page_count", 1) > 1
    )
    if not include_underlay and not window.lines and not is_pdf_document:
        QMessageBox.warning(
            window,
            "没有可导出内容",
            "当前既没有扫描底图，也没有人工复核后的结构线。",
        )
        return None

    default_dir = Path.cwd() / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    default_name = (
        f"{window.current_path.stem}.dwg"
        if getattr(window, "current_path", None) is not None
        else "output.dwg"
    )
    selected_path, selected_filter = QFileDialog.getSaveFileName(
        window,
        "导出 CAD",
        str(default_dir / default_name),
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
    scan_path = dxf_path.with_name(f"{dxf_path.stem}.scan.png")

    calibration_source, coordinate_space, semantic_warnings = window._calibration_semantics()
    if is_pdf_document:
        calibration_source = "pdf_page_dimensions"
        coordinate_space = "paper_mm"
        semantic_warnings = [
            "多页 PDF 按每页纸面毫米排列；这不是工程模型尺寸。",
        ]
    elif coordinate_space == "pixel":
        QMessageBox.information(
            window,
            "未校准尺寸",
            "当前未设置比例。CAD 将按无单位图形坐标导出，结构可编辑，但尺寸不准确。",
        )
    elif coordinate_space == "paper_mm":
        QMessageBox.information(
            window,
            "纸面坐标模式",
            "当前导出的是打印纸面毫米 paper_mm，不是工程模型尺寸 model_mm。",
        )

    export_ocr_text = bool(
        getattr(window, "export_ocr_text_checkbox", None)
        and window.export_ocr_text_checkbox.isChecked()
    )
    requested_texts = (
        list(window.auxiliary_result.texts)
        if export_ocr_text and window.auxiliary_result is not None
        else []
    )
    dwg_error: str | None = None

    try:
        if is_pdf_document:
            pages = window.document_pages_for_export()
            result = export_scan_document(
                pages,
                dxf_path,
                pdf_dpi=200,
            )
        else:
            image_height = (
                window.binary_image.shape[0]
                if window.binary_image is not None
                else window.corrected_image.shape[0]
            )
            result = export_dxf(
                window.lines,
                dxf_path,
                image_height,
                window.calibration,
                circles=[],
                texts=requested_texts,
                raster_image=window.corrected_image if include_underlay else None,
                raster_output_path=scan_path if include_underlay else None,
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
                        converter if converter.name.lower() != "odafileconverter.exe" else None
                    ),
                )
                result = replace(result, dwg_path=dwg_path, output_format="DWG")
            except DwgConversionUnavailable as exc:
                dwg_error = str(exc)
                result = replace(result, output_format="DXF")

        quality = assess_image_quality(window.original_image)
        warnings = list(window._last_warnings)
        warnings.extend(quality.warnings)
        warnings.extend(semantic_warnings)
        if result.text_count:
            warnings.append(
                f"已将 {result.text_count} 个高置信度 OCR 结果导出为可编辑 TEXT；"
                "文字内容仍需人工校对。"
            )
        if result.underlay_paths:
            warnings.append(
                f"已为 {len(result.underlay_paths)} 页保存无损 PNG 扫描底图；"
                "CAD 文件与所有 page-xxx.scan.png 必须一起移动。"
            )
        elif include_underlay and result.underlay_path is not None:
            warnings.append(
                "已链接扫描底图以保留原始文字和细节；"
                "CAD 文件与 .scan.png 必须放在同一目录并一起移动。"
            )
        if requested_dwg and result.dwg_path is not None:
            warnings.append("已通过本机 ODA File Converter 将生成的 DXF 转换为 DWG。")
        if dwg_error:
            warnings.append(f"DWG 转换未完成：{dwg_error}")
        if window._perspective_metadata is not None:
            warnings.extend(window._perspective_metadata.get("warnings", []))

        paper_size, orientation = window.paper_size_combo.currentData()
        paper_dimensions = _gui.resolve_paper_dimensions_mm(
            paper_size,
            orientation=orientation,
            observed_landscape=(
                window.corrected_image.shape[1] >= window.corrected_image.shape[0]
            ),
        )
        binary_shape = (
            window.binary_image.shape
            if window.binary_image is not None
            else window.corrected_image.shape
        )
        report = ReportBuilder.build(
            input_path=window.current_path,
            original_shape=window.original_image.shape,
            corrected_shape=window.corrected_image.shape,
            perspective=window._perspective_metadata,
            quality=quality,
            parameters={
                "preprocess": asdict(window._last_preprocess_params),
                "line_detection": asdict(window._last_detection_params),
                "geometry_cleaning": asdict(window._last_clean_params),
                "paper_size": paper_size,
                "paper_orientation": orientation,
                "paper_dimensions_mm": paper_dimensions,
                "pdf_page": getattr(window, "_current_pdf_page", None),
                "pdf_page_count": getattr(window, "_pdf_page_count", 1),
                "multi_page_document": is_pdf_document,
                "scan_faithful_mode": include_underlay or is_pdf_document,
                "protect_text_regions": True,
                "preserve_hatch": window.keep_hatch.isChecked(),
                "ocr_enabled": window.enable_ocr.isChecked(),
                "ocr_text_export_requested": export_ocr_text,
                "circle_confirmation_workflow": False,
                "requested_output_format": "DWG" if requested_dwg else "DXF",
            },
            preprocess_stages=window.preprocess_stages,
            preprocess_resolution_scale=window._last_preprocess_scale,
            detection_resolution_scale=(
                window._last_detection_scale
                if window._last_detection_scale
                else image_resolution_scale(binary_shape)
            ),
            thick_stroke_centering=window._last_detection_params.center_thick_strokes,
            raw_lines=window.raw_lines,
            lines=window.lines,
            geometry_report=window.geometry_report,
            geometry_resolution_scale=window._last_geometry_scale,
            classification_report=window.classification_report,
            auxiliary=window.auxiliary_result,
            export_result=result,
            calibration_source=calibration_source,
            coordinate_space=coordinate_space,
            warnings=warnings,
            confirmed_circles=[],
            started_at_utc=window._run_started_at,
            duration_seconds=window._run_duration_seconds,
        )
        report["document"] = {
            "page_count": result.page_count,
            "layout_strategy": "modelspace_vertical_stack_and_paperspace_per_page",
            "underlay_files": [str(path.name) for path in result.underlay_paths],
        }
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "导出失败", str(exc))
        return None

    output_lines = [f"DXF：{result.path}"]
    if result.dwg_path is not None:
        output_lines.insert(0, f"DWG：{result.dwg_path}")
    if result.page_count > 1:
        output_lines.append(f"合并页面：{result.page_count} 页")
        output_lines.append(f"扫描底图：{len(result.underlay_paths)} 个无损 PNG")
    elif result.underlay_path is not None:
        output_lines.append(f"扫描底图：{result.underlay_path}")
    output_lines.extend(
        (
            f"可编辑 LINE：{result.line_count}",
            f"可编辑 OCR TEXT：{result.text_count}",
            f"处理报告：{report_path}",
            f"坐标空间：{coordinate_space}",
        )
    )
    if dwg_error:
        output_lines.append(f"\nDWG 未生成：{dwg_error}")
        QMessageBox.warning(window, "DXF 已导出，DWG 未生成", "\n".join(output_lines))
    else:
        QMessageBox.information(window, "导出完成", "\n".join(output_lines))
    final_output = result.dwg_path or result.path
    window.statusBar().showMessage(f"CAD 已导出：{final_output}")
    return result, report_path
