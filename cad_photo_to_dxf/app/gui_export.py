from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import gui as _gui
from .auxiliary_recognition import CircleCandidate
from .dwg_converter import (
    DwgConversionUnavailable,
    configure_oda_converter,
    convert_dxf_to_dwg,
)
from .dxf_exporter import (
    ExportResult,
    export_dxf,
    filter_exportable_circles,
    filter_exportable_texts,
)
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
    """Export the reviewed result as DXF and optionally convert it to DWG."""
    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成后再导出。")
        return None
    if not window.lines:
        QMessageBox.warning(
            window,
            "尚未识别",
            "请先完成“识别线条”，确认预览后再导出。",
        )
        return None
    if (
        window.original_image is None
        or window.binary_image is None
        or window.corrected_image is None
    ):
        QMessageBox.warning(window, "状态不完整", "图像处理状态不完整，请重新导入并处理。")
        return None

    default_dir = Path.cwd() / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    selected_path, selected_filter = QFileDialog.getSaveFileName(
        window,
        "导出 CAD",
        str(default_dir / "output.dwg"),
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

    calibration_source, coordinate_space, semantic_warnings = (
        window._calibration_semantics()
    )
    if coordinate_space == "pixel":
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

    approved_circles = list(circles or [])
    exported_circles = filter_exportable_circles(approved_circles)
    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
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
    exported_texts = filter_exportable_texts(requested_texts)
    dwg_error: str | None = None

    try:
        result = export_dxf(
            window.lines,
            dxf_path,
            window.binary_image.shape[0],
            window.calibration,
            circles=approved_circles,
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
                result = replace(
                    result,
                    dwg_path=dwg_path,
                    output_format="DWG",
                )
            except DwgConversionUnavailable as exc:
                dwg_error = str(exc)
                result = replace(result, output_format="DXF")

        quality = assess_image_quality(window.original_image)
        warnings = list(window._last_warnings)
        warnings.extend(quality.warnings)
        warnings.extend(semantic_warnings)
        if result.circle_count:
            warnings.append(
                f"已依据人工确认导出 {result.circle_count} 个 CIRCLE 实体。"
            )
        if result.skipped_circle_count:
            warnings.append(
                "导出边界再次校验时跳过 "
                f"{result.skipped_circle_count} 个无效或低置信度圆形候选。"
            )
        if result.text_count:
            warnings.append(
                f"已将 {result.text_count} 个高置信度 OCR 结果导出为可编辑 TEXT；"
                "文字内容仍需人工校对。"
            )
        if include_underlay and result.underlay_path is not None:
            warnings.append(
                "已链接校正扫描底图以保留原始文字和细节；"
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
                "strict_perspective": True,
                "protect_text_regions": True,
                "preserve_hatch": window.keep_hatch.isChecked(),
                "auxiliary_enabled": (
                    window.enable_auxiliary.isChecked()
                    or window.enable_ocr.isChecked()
                ),
                "ocr_enabled": window.enable_ocr.isChecked(),
                "ocr_text_export_requested": export_ocr_text,
                "scan_underlay_requested": include_underlay,
                "circle_export_requires_confirmation": True,
                "requested_output_format": "DWG" if requested_dwg else "DXF",
            },
            preprocess_stages=window.preprocess_stages,
            preprocess_resolution_scale=window._last_preprocess_scale,
            detection_resolution_scale=(
                window._last_detection_scale
                if window._last_detection_scale
                else image_resolution_scale(window.binary_image.shape)
            ),
            thick_stroke_centering=(
                window._last_detection_params.center_thick_strokes
            ),
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
            confirmed_circles=exported_circles,
            started_at_utc=window._run_started_at,
            duration_seconds=window._run_duration_seconds,
        )
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "导出失败", str(exc))
        return None

    scale_text = (
        f"比例：{result.mm_per_pixel:.6f} mm/px"
        if result.calibrated
        else "比例：未校准（1 px = 1 个无单位图形单位）"
    )
    output_lines = [f"DXF：{result.path}"]
    if result.dwg_path is not None:
        output_lines.insert(0, f"DWG：{result.dwg_path}")
    if result.underlay_path is not None:
        output_lines.append(f"扫描底图：{result.underlay_path}")
    output_lines.extend(
        (
            f"可编辑 LINE：{result.line_count}",
            f"人工确认 CIRCLE：{result.circle_count}",
            f"可编辑 OCR TEXT：{result.text_count}",
            f"处理报告：{report_path}",
            f"坐标空间：{coordinate_space}",
            scale_text,
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
