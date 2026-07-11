from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import gui as _gui
from .auxiliary_recognition import CircleCandidate
from .dxf_exporter import ExportResult, export_dxf
from .quality import assess_image_quality
from .report_builder import ReportBuilder
from .reporting import write_json_report
from .resolution import image_resolution_scale


def export_from_window(
    window: Any,
    *,
    circles: list[CircleCandidate] | None = None,
) -> tuple[ExportResult, Path] | None:
    """Run the active GUI export and unified report path.

    ``circles`` must contain only candidates already approved by the explicit
    circle-review dialog. The exporter independently rechecks their validity.
    """
    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成后再导出。")
        return None
    if not window.lines:
        QMessageBox.warning(
            window,
            "尚未识别",
            "请先完成“识别并清理线条”，确认预览后再导出。",
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
    path, _ = QFileDialog.getSaveFileName(
        window,
        "导出 DXF",
        str(default_dir / "output.dxf"),
        "DXF files (*.dxf)",
    )
    if not path:
        return None
    if not path.lower().endswith(".dxf"):
        path += ".dxf"

    calibration_source, coordinate_space, semantic_warnings = (
        window._calibration_semantics()
    )
    if coordinate_space == "pixel":
        QMessageBox.information(
            window,
            "未校准尺寸",
            "当前未设置比例。DXF 将按像素图形单位导出，结构可编辑，但尺寸不准确。",
        )
    elif coordinate_space == "paper_mm":
        QMessageBox.information(
            window,
            "纸面坐标模式",
            "当前导出的是打印纸面毫米 paper_mm，不是工程模型尺寸 model_mm。",
        )

    approved_circles = list(circles or [])
    try:
        result = export_dxf(
            window.lines,
            path,
            window.binary_image.shape[0],
            window.calibration,
            circles=approved_circles,
        )
        report_path = Path(path).with_suffix(".report.json")
        quality = assess_image_quality(window.original_image)
        warnings = list(window._last_warnings)
        warnings.extend(quality.warnings)
        warnings.extend(semantic_warnings)
        if result.circle_count:
            warnings.append(
                f"已依据人工确认导出 {result.circle_count} 个 DXF CIRCLE 实体。"
            )
        if result.skipped_circle_count:
            warnings.append(
                "导出边界再次校验时跳过 "
                f"{result.skipped_circle_count} 个无效或低置信度圆形候选。"
            )
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
                "strict_perspective": True,
                "preserve_hatch": window.keep_hatch.isChecked(),
                "auxiliary_enabled": (
                    window.enable_auxiliary.isChecked()
                    or window.enable_ocr.isChecked()
                ),
                "ocr_enabled": window.enable_ocr.isChecked(),
                "circle_export_requires_confirmation": True,
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
            confirmed_circles=approved_circles,
            started_at_utc=window._run_started_at,
            duration_seconds=window._run_duration_seconds,
        )
        write_json_report(report_path, report)
    except Exception as exc:
        QMessageBox.critical(window, "导出失败", str(exc))
        return None

    QMessageBox.information(
        window,
        "导出完成",
        f"已生成：{result.path}\n"
        f"可编辑 LINE 数量：{result.line_count}\n"
        f"人工确认 CIRCLE 数量：{result.circle_count}\n"
        f"处理报告：{report_path}\n"
        f"坐标空间：{coordinate_space}\n"
        f"比例：{result.mm_per_pixel:.6f} mm/px",
    )
    window.statusBar().showMessage(f"DXF 已导出：{result.path}")
    return result, report_path
