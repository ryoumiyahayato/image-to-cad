from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import time

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import gui as _gui
from .cancellation import CancellationToken
from .dxf_exporter import export_dxf
from .geometry_cleaner import GeometryCleanParams
from .line_detect import LineDetectionParams
from .perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE
from .pipeline_service import PipelineService, VectorizationResult
from .preprocess import PreprocessParams, PreprocessResult
from .quality import assess_image_quality
from .report_builder import ReportBuilder
from .reporting import write_json_report
from .resolution import image_resolution_scale


class MainWindow(_gui.MainWindow):
    """Active GUI with guarded state and shared processing/report services."""

    def __init__(self) -> None:
        super().__init__()
        self._perspective_metadata: dict[str, object] | None = None
        self._run_started_at: datetime | None = None
        self._run_duration_seconds: float | None = None
        self._last_preprocess_scale = 1.0
        self._last_detection_scale = 1.0
        self._last_geometry_scale = 1.0
        self._last_preprocess_params = PreprocessParams()
        self._last_detection_params = LineDetectionParams()
        self._last_clean_params = GeometryCleanParams()
        self._last_warnings: tuple[str, ...] = ()

    def import_image(self) -> None:
        revision = self._state_revision
        super().import_image()
        if self._state_revision != revision:
            self._perspective_metadata = None
            self._run_started_at = None
            self._run_duration_seconds = None
            self._last_warnings = ()

    def _require_corrected(self) -> bool:
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "需要确认纸张透视",
            "请先执行自动纸张校正，或手工确认四个纸张角点。\n\n"
            "当前版本不再把未经校正的原图静默视为已校正图。",
        )
        self.statusBar().showMessage("已阻止处理：尚未确认纸张透视")
        return False

    def auto_perspective(self) -> None:
        if not self._require_original():
            return
        source = self.original_image.copy()
        ratio = self._target_aspect_ratio()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            token.checkpoint()
            progress("纸张边界识别", 0.15)
            result = _gui.auto_correct(source, ratio)
            token.checkpoint()
            progress("透视校正", 1.0)
            return result

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            result = value
            if result is None:
                QMessageBox.information(
                    self,
                    "未识别纸张边界",
                    "自动识别失败。请使用“手动点击四角并校正”，四点顺序不限。",
                )
                return
            if result.confidence < MIN_AUTOMATIC_PAPER_CONFIDENCE:
                QMessageBox.warning(
                    self,
                    "纸张识别置信度不足",
                    f"自动候选置信度为 {result.confidence:.2f}，低于严格阈值 "
                    f"{MIN_AUTOMATIC_PAPER_CONFIDENCE:.2f}。请手工确认四个纸张角点。",
                )
                self._perspective_metadata = {
                    "applied": False,
                    "automatic": True,
                    "confidence": result.confidence,
                    "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
                    "corners": result.corners,
                    "target_aspect_ratio": ratio,
                    "rejected_low_confidence": True,
                    "warnings": list(result.warnings),
                }
                return
            self.corrected_image = result.image
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.original_canvas.clear_overlays()
            for index, point in enumerate(result.corners, start=1):
                self.original_canvas.add_point(tuple(point), str(index))
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": True,
                "confidence": result.confidence,
                "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
                "corners": result.corners,
                "target_aspect_ratio": ratio,
                "warnings": list(result.warnings),
            }
            message = f"自动透视校正完成；置信度 {result.confidence:.2f}"
            if result.warnings:
                message += f"；警告 {len(result.warnings)} 项"
            self.statusBar().showMessage(message)

        self._start_processing(operation, completed, "正在识别纸张并校正…")

    def _on_original_point(self, x: float, y: float) -> None:
        if self.selection_mode != "corners":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.original_canvas.add_point(point, str(len(self.selected_points)))
        if len(self.selected_points) != 4:
            return

        self.original_canvas.set_selection_enabled(False)
        self.selection_mode = None
        source = self.original_image.copy()
        points = list(self.selected_points)
        ratio = self._target_aspect_ratio()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            token.checkpoint()
            progress("四角验证", 0.2)
            image = _gui.warp_perspective(source, points, ratio)
            token.checkpoint()
            progress("手动透视校正", 1.0)
            return image

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            self.corrected_image = value
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": False,
                "confidence": 1.0,
                "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
                "corners": points,
                "target_aspect_ratio": ratio,
                "warnings": [],
            }
            self.statusBar().showMessage("手动四角透视校正完成")

        self._start_processing(operation, completed, "正在执行手动透视校正…")

    def rotate_corrected(self, degrees: int) -> None:
        super().rotate_corrected(degrees)
        if self.corrected_image is not None and self._perspective_metadata is not None:
            rotations = list(self._perspective_metadata.get("rotations", []))
            rotations.append(int(degrees))
            self._perspective_metadata["rotations"] = rotations

    def preprocess(self) -> None:
        if not self._require_corrected():
            return
        params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        source = self.corrected_image.copy()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            return PipelineService.preprocess(
                source,
                params,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的预处理结果")
                return
            result: PreprocessResult = value  # type: ignore[assignment]
            self.binary_image = result.image
            self.preprocess_stages = result.stages
            self._last_preprocess_scale = result.resolution_scale
            self._last_preprocess_params = params
            self._invalidate_line_results()
            self.corrected_canvas.set_image(self.binary_image)
            self._show_preprocess_stages(result.stages)
            self.tabs.setCurrentWidget(self.preprocess_tabs)
            self.statusBar().showMessage(
                f"逐算子预处理完成；分辨率参数倍率 {result.resolution_scale:.3f}"
            )

        self._start_processing(operation, completed, "正在执行图像预处理…")

    def detect_and_clean(self) -> None:
        if not self._require_corrected():
            return
        detection = LineDetectionParams(
            min_line_length=self.min_length_spin.value(),
            max_line_gap=max(2, int(round(self.bridge_spin.value()))),
        )
        cleaning = GeometryCleanParams(
            snap_distance=self.snap_spin.value(),
            max_bridge_gap=self.bridge_spin.value(),
            angle_tolerance=self.angle_spin.value(),
            min_line_length=max(5.0, self.min_length_spin.value() * 0.45),
        )
        existing_binary = self.binary_image.copy() if self.binary_image is not None else None
        corrected = self.corrected_image.copy()
        preprocess_params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        preserve_hatch = self.keep_hatch.isChecked()
        enable_auxiliary = self.enable_auxiliary.isChecked() or self.enable_ocr.isChecked()
        enable_ocr = self.enable_ocr.isChecked()
        revision = self._state_revision
        run_started_at = datetime.now(timezone.utc)
        run_started_clock = time.perf_counter()

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            return PipelineService.vectorize(
                corrected,
                existing_binary=existing_binary,
                preprocess_params=preprocess_params,
                detection_params=detection,
                clean_params=cleaning,
                preserve_hatch=preserve_hatch,
                enable_auxiliary=enable_auxiliary,
                enable_ocr=enable_ocr,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的识别结果")
                return
            result: VectorizationResult = value  # type: ignore[assignment]
            self.binary_image = result.binary
            if result.preprocess_stages:
                self.preprocess_stages = result.preprocess_stages
                self._show_preprocess_stages(self.preprocess_stages)
            self.raw_lines = result.raw_lines
            self.lines = result.lines
            self.geometry_report = result.geometry_report
            self.classification_report = result.classification_report
            self.auxiliary_result = result.auxiliary
            self.detected_canvas.set_image(result.preview)
            self.tabs.setCurrentWidget(self.detected_canvas)
            self._run_started_at = run_started_at
            self._run_duration_seconds = time.perf_counter() - run_started_clock
            self._last_preprocess_scale = result.preprocess_resolution_scale
            self._last_detection_scale = result.detection_resolution_scale
            self._last_geometry_scale = result.geometry_resolution_scale
            self._last_preprocess_params = preprocess_params
            self._last_detection_params = detection
            self._last_clean_params = cleaning
            self._last_warnings = result.warnings
            counts = self.classification_report.layer_counts or {}
            details = ", ".join(f"{key}:{count}" for key, count in sorted(counts.items()))
            auxiliary_details = ""
            if self.auxiliary_result is not None:
                auxiliary_details = (
                    f"；辅助圆 {len(self.auxiliary_result.circles)}、"
                    f"文字 {len(self.auxiliary_result.texts)}、"
                    f"符号 {len(self.auxiliary_result.symbols)}"
                )
            warning_details = f"；警告 {len(result.warnings)}" if result.warnings else ""
            self.statusBar().showMessage(
                f"识别并清理后共 {len(self.lines)} 条线；{details}{auxiliary_details}"
                f"{warning_details}；几何倍率 {result.geometry_resolution_scale:.3f}"
            )

        self._start_processing(operation, completed, "正在识别和清理线条…")

    def _calibration_semantics(self) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        if self.calibration is None:
            warnings.append("未校准尺寸；导出坐标仍为像素图形单位。")
            return "uncalibrated", "pixel", warnings
        paper_size, orientation = self.paper_size_combo.currentData()
        dimensions = _gui.resolve_paper_dimensions_mm(
            paper_size,
            orientation=orientation,
            observed_landscape=self.corrected_image.shape[1] >= self.corrected_image.shape[0],
        )
        expected_end = float(max(1, self.corrected_image.shape[1] - 1))
        paper_derived = (
            dimensions is not None
            and abs(self.calibration.point1[0]) < 1e-6
            and abs(self.calibration.point1[1]) < 1e-6
            and abs(self.calibration.point2[0] - expected_end) < 1e-3
            and abs(self.calibration.point2[1]) < 1e-6
        )
        if paper_derived:
            warnings.append(
                "导出坐标为纸面毫米（paper_mm），不是原始设计模型尺寸；"
                "恢复 model_mm 必须用图纸比例或已知实际尺寸重新校准。"
            )
            return "paper_dimensions", "paper_mm", warnings
        return "explicit", "model_mm", warnings

    def export_file(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成后再导出。")
            return
        if not self.lines:
            QMessageBox.warning(self, "尚未识别", "请先完成“识别并清理线条”，确认预览后再导出。")
            return
        if self.binary_image is None or self.corrected_image is None:
            return
        default_dir = Path.cwd() / "output"
        default_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 DXF",
            str(default_dir / "output.dxf"),
            "DXF files (*.dxf)",
        )
        if not path:
            return
        if not path.lower().endswith(".dxf"):
            path += ".dxf"

        calibration_source, coordinate_space, semantic_warnings = self._calibration_semantics()
        if coordinate_space == "pixel":
            QMessageBox.information(
                self,
                "未校准尺寸",
                "当前未设置比例。DXF 将按像素图形单位导出，结构可编辑，但尺寸不准确。",
            )
        elif coordinate_space == "paper_mm":
            QMessageBox.information(
                self,
                "纸面坐标模式",
                "当前导出的是打印纸面毫米 paper_mm，不是工程模型尺寸 model_mm。",
            )

        try:
            result = export_dxf(
                self.lines,
                path,
                self.binary_image.shape[0],
                self.calibration,
            )
            report_path = Path(path).with_suffix(".report.json")
            quality = assess_image_quality(self.original_image)
            warnings = list(self._last_warnings)
            warnings.extend(quality.warnings)
            warnings.extend(semantic_warnings)
            if self._perspective_metadata is not None:
                warnings.extend(self._perspective_metadata.get("warnings", []))
            paper_size, orientation = self.paper_size_combo.currentData()
            paper_dimensions = _gui.resolve_paper_dimensions_mm(
                paper_size,
                orientation=orientation,
                observed_landscape=(
                    self.corrected_image.shape[1] >= self.corrected_image.shape[0]
                ),
            )
            report = ReportBuilder.build(
                input_path=self.current_path,
                original_shape=self.original_image.shape,
                corrected_shape=self.corrected_image.shape,
                perspective=self._perspective_metadata,
                quality=quality,
                parameters={
                    "preprocess": asdict(self._last_preprocess_params),
                    "line_detection": asdict(self._last_detection_params),
                    "geometry_cleaning": asdict(self._last_clean_params),
                    "paper_size": paper_size,
                    "paper_orientation": orientation,
                    "paper_dimensions_mm": paper_dimensions,
                    "strict_perspective": True,
                    "preserve_hatch": self.keep_hatch.isChecked(),
                    "auxiliary_enabled": (
                        self.enable_auxiliary.isChecked() or self.enable_ocr.isChecked()
                    ),
                    "ocr_enabled": self.enable_ocr.isChecked(),
                },
                preprocess_stages=self.preprocess_stages,
                preprocess_resolution_scale=self._last_preprocess_scale,
                detection_resolution_scale=(
                    self._last_detection_scale
                    if self._last_detection_scale
                    else image_resolution_scale(self.binary_image.shape)
                ),
                thick_stroke_centering=self._last_detection_params.center_thick_strokes,
                raw_lines=self.raw_lines,
                lines=self.lines,
                geometry_report=self.geometry_report,
                geometry_resolution_scale=self._last_geometry_scale,
                classification_report=self.classification_report,
                auxiliary=self.auxiliary_result,
                export_result=result,
                calibration_source=calibration_source,
                coordinate_space=coordinate_space,
                warnings=warnings,
                started_at_utc=self._run_started_at,
                duration_seconds=self._run_duration_seconds,
            )
            write_json_report(report_path, report)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"已生成：{result.path}\n可编辑 LINE 数量：{result.line_count}\n"
            f"处理报告：{report_path}\n"
            f"坐标空间：{coordinate_space}\n"
            f"比例：{result.mm_per_pixel:.6f} mm/px",
        )
        self.statusBar().showMessage(f"DXF 已导出：{result.path}")
