from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Callable

import numpy as np
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import __version__
from .cancellation import CancellationToken
from .dxf_exporter import export_dxf
from .geometry_cleaner import GeometryCleanParams
from .gui import MainWindow as _LegacyMainWindow
from .line_detect import LineDetectionParams
from .perspective import (
    PerspectiveResult,
    auto_correct,
    resolve_paper_dimensions_mm,
    warp_perspective,
)
from .preprocess import (
    PreprocessParams,
    PreprocessResult,
    preprocess_image_with_stages,
)
from .processing_service import (
    ProcessingConfig,
    ProcessingResult,
    process_corrected_image,
)
from .quality import assess_image_quality
from .reporting import build_processing_report, write_json_report
from .workflow_state import (
    WorkflowState,
    WorkflowStateError,
    WorkflowStateMachine,
)


class MainWindow(_LegacyMainWindow):
    """GUI entrypoint with strict workflow state and one shared pipeline."""

    def __init__(self) -> None:
        self._workflow = WorkflowStateMachine()
        self._coordinate_mode = "pixel_units"
        self._calibration_source = "uncalibrated"
        self._imported_at = datetime.now(timezone.utc)
        self._session_started_clock = time.perf_counter()
        self._perspective_metadata: dict[str, object] = {
            "applied": False,
            "automatic": None,
            "confidence": None,
            "corners": None,
            "target_aspect_ratio": None,
            "corrected_shape": None,
        }
        self._last_processing_config: ProcessingConfig | None = None
        self._last_processing_result: ProcessingResult | None = None
        super().__init__()
        self.info_label.setText("坐标：未校准的无单位像素坐标")

    def _reset_session_metadata(self) -> None:
        self._coordinate_mode = "pixel_units"
        self._calibration_source = "uncalibrated"
        self._imported_at = datetime.now(timezone.utc)
        self._session_started_clock = time.perf_counter()
        self._perspective_metadata = {
            "applied": False,
            "automatic": None,
            "confidence": None,
            "corners": None,
            "target_aspect_ratio": None,
            "corrected_shape": None,
        }
        self._last_processing_config = None
        self._last_processing_result = None
        self.info_label.setText("坐标：未校准的无单位像素坐标")

    def import_image(self) -> None:
        previous_revision = self._state_revision
        super().import_image()
        if self._state_revision == previous_revision or self.original_image is None:
            return
        self._workflow.import_image()
        self._reset_session_metadata()
        self.statusBar().showMessage(
            f"已导入：{self.current_path.name}；状态 {self._workflow.state.name}"
        )

    def _invalidate_line_results(self, *_args: object) -> None:
        previous_state = self._workflow.state
        super()._invalidate_line_results(*_args)
        self._last_processing_config = None
        self._last_processing_result = None
        if previous_state >= WorkflowState.VECTORIZED:
            target = (
                WorkflowState.PREPROCESSED
                if self.binary_image is not None
                else WorkflowState.PERSPECTIVE_CONFIRMED
            )
            self._workflow.invalidate_to(target)

    def _invalidate_preprocess_results(self, *_args: object) -> None:
        previous_state = self._workflow.state
        super()._invalidate_preprocess_results(*_args)
        if self.corrected_image is not None:
            if previous_state >= WorkflowState.PERSPECTIVE_CONFIRMED:
                self._workflow.invalidate_to(WorkflowState.PERSPECTIVE_CONFIRMED)
        elif self.original_image is not None:
            if previous_state >= WorkflowState.IMPORTED:
                self._workflow.invalidate_to(WorkflowState.IMPORTED)
        else:
            self._workflow.clear()

    def _require_corrected(self) -> bool:
        if (
            self.corrected_image is not None
            and self._workflow.perspective_confirmed
        ):
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "尚未确认透视校正",
            "请先执行“自动透视校正”，或使用“手动点击四角并校正”。\n"
            "系统不会再把原始照片静默当作已校正图像。",
        )
        self.statusBar().showMessage(
            "处理已阻止：必须先进入 PERSPECTIVE_CONFIRMED 状态"
        )
        return False

    def _apply_paper_calibration(self) -> None:
        super()._apply_paper_calibration()
        if self.calibration is None:
            self._coordinate_mode = "pixel_units"
            self._calibration_source = "uncalibrated"
            self.info_label.setText("坐标：未校准的无单位像素坐标")
            return
        self._coordinate_mode = "paper_mm"
        self._calibration_source = "paper_dimensions"
        self.info_label.setText(
            f"坐标：纸面毫米 {self.calibration.mm_per_pixel:.6f} mm/px；"
            "不是工程模型尺寸"
        )

    def _paper_setting_changed(self, *_args: object) -> None:
        super()._paper_setting_changed(*_args)
        self._coordinate_mode = "pixel_units"
        self._calibration_source = "uncalibrated"
        self._perspective_metadata = {
            "applied": False,
            "automatic": None,
            "confidence": None,
            "corners": None,
            "target_aspect_ratio": None,
            "corrected_shape": None,
        }
        if self.original_image is not None:
            self._workflow.import_image()
        else:
            self._workflow.clear()

    def rotate_corrected(self, degrees: int) -> None:
        if not self._require_corrected():
            return
        super().rotate_corrected(degrees)
        if self.corrected_image is not None:
            self._coordinate_mode = "pixel_units"
            self._calibration_source = "uncalibrated"
            self._perspective_metadata["corrected_shape"] = list(
                self.corrected_image.shape
            )
            self.info_label.setText("旋转后比例已失效；当前为无单位像素坐标")
            self.statusBar().showMessage(
                f"已旋转 {degrees}°；状态 {self._workflow.state.name}"
            )

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
            result = auto_correct(source, ratio)
            token.checkpoint()
            progress("透视校正", 1.0)
            return result

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            if value is None:
                QMessageBox.information(
                    self,
                    "未识别纸张边界",
                    "自动识别失败或置信度不足。请使用手动四角校正。",
                )
                return
            if not isinstance(value, PerspectiveResult):
                raise TypeError("Perspective service returned an invalid result")
            if self._workflow.state > WorkflowState.IMPORTED:
                self._workflow.invalidate_to(WorkflowState.IMPORTED)
            self._workflow.confirm_perspective()
            self.corrected_image = value.image
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.original_canvas.clear_overlays()
            for index, point in enumerate(value.corners, start=1):
                self.original_canvas.add_point(tuple(point), str(index))
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": True,
                "confidence": float(value.confidence),
                "corners": value.corners.copy(),
                "target_aspect_ratio": ratio,
                "corrected_shape": list(self.corrected_image.shape),
            }
            message = (
                f"自动透视校正完成；置信度 {value.confidence:.2f}；"
                f"状态 {self._workflow.state.name}"
            )
            if value.warnings:
                message += f"；警告 {len(value.warnings)} 项"
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
            image = warp_perspective(source, points, ratio)
            token.checkpoint()
            progress("手动透视校正", 1.0)
            return image

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            if not isinstance(value, np.ndarray):
                raise TypeError("Manual perspective service returned an invalid image")
            if self._workflow.state > WorkflowState.IMPORTED:
                self._workflow.invalidate_to(WorkflowState.IMPORTED)
            self._workflow.confirm_perspective()
            self.corrected_image = value
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": False,
                "confidence": 1.0,
                "corners": points,
                "target_aspect_ratio": ratio,
                "corrected_shape": list(self.corrected_image.shape),
            }
            self.statusBar().showMessage(
                f"手动四角透视校正完成；状态 {self._workflow.state.name}"
            )

        self._start_processing(operation, completed, "正在执行手动透视校正…")

    def preprocess(self) -> None:
        if not self._require_corrected():
            return
        if self._workflow.state > WorkflowState.PERSPECTIVE_CONFIRMED:
            self._workflow.invalidate_to(WorkflowState.PERSPECTIVE_CONFIRMED)
        params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        source = self.corrected_image.copy()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            return preprocess_image_with_stages(
                source,
                params,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的预处理结果")
                return
            if not isinstance(value, PreprocessResult):
                raise TypeError("Preprocess service returned an invalid result")
            self.binary_image = value.image
            self.preprocess_stages = value.stages
            self._invalidate_line_results()
            self.corrected_canvas.set_image(self.binary_image)
            self._show_preprocess_stages(value.stages)
            self.tabs.setCurrentWidget(self.preprocess_tabs)
            self._workflow.mark_preprocessed()
            self.statusBar().showMessage(
                f"逐算子预处理完成；状态 {self._workflow.state.name}"
            )

        self._start_processing(operation, completed, "正在执行图像预处理…")

    def detect_and_clean(self) -> None:
        if not self._require_corrected():
            return

        config = ProcessingConfig(
            preprocess=PreprocessParams(
                threshold_strength=self.threshold_spin.value()
            ),
            detection=LineDetectionParams(
                min_line_length=self.min_length_spin.value(),
                max_line_gap=max(2, int(round(self.bridge_spin.value()))),
            ),
            cleaning=GeometryCleanParams(
                snap_distance=self.snap_spin.value(),
                max_bridge_gap=self.bridge_spin.value(),
                angle_tolerance=self.angle_spin.value(),
                min_line_length=max(
                    5.0,
                    self.min_length_spin.value() * 0.45,
                ),
            ),
            preserve_hatch=self.keep_hatch.isChecked(),
            enable_auxiliary=(
                self.enable_auxiliary.isChecked() or self.enable_ocr.isChecked()
            ),
            enable_ocr=self.enable_ocr.isChecked(),
        )
        existing_binary = (
            self.binary_image.copy() if self.binary_image is not None else None
        )
        if self._workflow.state > WorkflowState.PREPROCESSED:
            self._workflow.invalidate_to(
                WorkflowState.PREPROCESSED
                if existing_binary is not None
                else WorkflowState.PERSPECTIVE_CONFIRMED
            )
        corrected = self.corrected_image.copy()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            return process_corrected_image(
                corrected,
                config,
                existing_binary=existing_binary,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的识别结果")
                return
            if not isinstance(value, ProcessingResult):
                raise TypeError("Shared processing service returned an invalid result")

            self.binary_image = value.binary
            if value.preprocess_stages:
                self.preprocess_stages = value.preprocess_stages
                self._show_preprocess_stages(self.preprocess_stages)
            self.raw_lines = value.raw_lines
            self.lines = value.lines
            self.geometry_report = value.geometry_report
            self.classification_report = value.classification_report
            self.auxiliary_result = value.auxiliary
            self.detected_canvas.set_image(value.preview)
            self.tabs.setCurrentWidget(self.detected_canvas)
            self._last_processing_config = config
            self._last_processing_result = value

            if self._workflow.state < WorkflowState.PREPROCESSED:
                self._workflow.mark_preprocessed()
            self._workflow.mark_vectorized()
            if self.calibration is not None:
                self._workflow.mark_calibrated()

            counts = self.classification_report.layer_counts or {}
            details = ", ".join(
                f"{key}:{count}" for key, count in sorted(counts.items())
            )
            auxiliary_details = ""
            if self.auxiliary_result is not None:
                auxiliary_details = (
                    f"；辅助圆 {len(self.auxiliary_result.circles)}、"
                    f"文字 {len(self.auxiliary_result.texts)}、"
                    f"符号 {len(self.auxiliary_result.symbols)}"
                )
            self.statusBar().showMessage(
                f"共享管线识别后共 {len(self.lines)} 条线；"
                f"{details}{auxiliary_details}；"
                f"分辨率系数 {value.detection_resolution_factor:.3f}；"
                f"状态 {self._workflow.state.name}"
            )

        self._start_processing(operation, completed, "正在通过共享管线识别和清理…")

    def start_scale_calibration(self) -> None:
        try:
            self._workflow.require(WorkflowState.VECTORIZED, "尺寸校准")
        except WorkflowStateError:
            QMessageBox.warning(
                self,
                "尚未完成矢量化",
                "请先完成透视校正、预处理和识别，再进行模型尺寸校准。",
            )
            return
        if self._workflow.state > WorkflowState.VECTORIZED:
            self._workflow.invalidate_to(WorkflowState.VECTORIZED)
        super().start_scale_calibration()

    def _on_corrected_point(self, x: float, y: float) -> None:
        previous_calibration = self.calibration
        was_scale_selection = self.selection_mode == "scale"
        super()._on_corrected_point(x, y)
        if (
            was_scale_selection
            and self.calibration is not None
            and self.calibration is not previous_calibration
        ):
            self._coordinate_mode = "model_mm"
            self._calibration_source = "known_dimension"
            self._workflow.mark_calibrated()
            self.info_label.setText(
                f"坐标：工程模型毫米 {self.calibration.mm_per_pixel:.6f} mm/px；"
                "请用第二个独立尺寸复核"
            )
            self.statusBar().showMessage(
                f"模型尺寸校准完成；状态 {self._workflow.state.name}"
            )

    def export_file(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成后再导出。")
            return
        try:
            self._workflow.require(WorkflowState.VECTORIZED, "DXF 导出")
        except WorkflowStateError:
            QMessageBox.warning(
                self,
                "尚未完成矢量化",
                "请先完成透视校正、预处理和识别，再导出 DXF。",
            )
            return
        if not self.lines or self.binary_image is None:
            QMessageBox.warning(self, "尚未识别", "请先完成识别并确认预览。")
            return
        if self._last_processing_config is None or self._last_processing_result is None:
            QMessageBox.warning(self, "状态不完整", "请重新执行识别后再导出。")
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

        warnings: list[str] = []
        if self._coordinate_mode == "pixel_units":
            warnings.append("当前导出为无单位像素坐标，不是毫米或工程真实尺寸。")
            QMessageBox.information(
                self,
                "无单位坐标",
                "当前没有比例校准。DXF 将使用无单位像素坐标，不会声明毫米。",
            )
        elif self._coordinate_mode == "paper_mm":
            warnings.append("当前导出为纸面毫米，不是原始工程模型尺寸。")
        else:
            warnings.append("工程尺寸来自单个已知长度，请使用第二个独立尺寸复核。")

        try:
            result = export_dxf(
                self.lines,
                path,
                self.binary_image.shape[0],
                self.calibration,
                coordinate_mode=self._coordinate_mode,
            )
            quality = assess_image_quality(self.original_image)
            warnings.extend(quality.warnings)
            if self.auxiliary_result is not None:
                warnings.extend(self.auxiliary_result.warnings)

            paper_size, orientation = self.paper_size_combo.currentData()
            paper_dimensions = resolve_paper_dimensions_mm(
                paper_size,
                orientation=orientation,
                observed_landscape=(
                    self.corrected_image.shape[1] >= self.corrected_image.shape[0]
                ),
            )
            processing = self._last_processing_result
            config = self._last_processing_config
            report = build_processing_report(
                application_version=__version__,
                started_at_utc=self._imported_at.isoformat(),
                duration_seconds=time.perf_counter() - self._session_started_clock,
                input_path=self.current_path,
                input_shape=self.original_image.shape,
                perspective={
                    **self._perspective_metadata,
                    "corrected_shape": list(self.corrected_image.shape),
                },
                quality=quality,
                parameters={
                    "preprocess": asdict(config.preprocess),
                    "line_detection_requested": asdict(config.detection),
                    "line_detection_effective": asdict(
                        processing.effective_detection_params
                    ),
                    "line_detection_resolution_factor": (
                        processing.detection_resolution_factor
                    ),
                    "geometry_cleaning": asdict(config.cleaning),
                    "paper_size": paper_size,
                    "paper_orientation": orientation,
                    "paper_dimensions_mm": paper_dimensions,
                    "preserve_hatch": config.preserve_hatch,
                    "auxiliary_enabled": config.enable_auxiliary,
                    "ocr_enabled": config.enable_ocr,
                    "workflow_state_before_export": self._workflow.state.name,
                },
                preprocess_stages=self.preprocess_stages,
                debug_directory=None,
                raw_lines=self.raw_lines,
                final_lines=self.lines,
                geometry_report=self.geometry_report,
                classification_report=self.classification_report,
                auxiliary=self.auxiliary_result,
                export_result=result,
                calibration_source=self._calibration_source,
                warnings=warnings,
            )
            report_path = Path(path).with_suffix(".report.json")
            write_json_report(report_path, report)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        validation_passed = bool(
            result.validation and result.validation.get("passed")
        )
        if validation_passed:
            self._workflow.mark_exported()
        else:
            QMessageBox.critical(
                self,
                "DXF 验证失败",
                f"文件已生成，但结构验证未通过。请查看报告：{report_path}",
            )
            self.statusBar().showMessage("DXF 已生成但验证失败；未进入 EXPORTED 状态")
            return

        if result.coordinate_mode == "model_mm":
            scale_text = f"工程模型毫米，{result.mm_per_pixel:.6f} mm/px"
        elif result.coordinate_mode == "paper_mm":
            scale_text = f"纸面毫米，{result.mm_per_pixel:.6f} mm/px"
        else:
            scale_text = "无单位像素坐标"
        QMessageBox.information(
            self,
            "导出完成",
            f"已生成：{result.path}\n"
            f"可编辑 LINE 数量：{result.line_count}\n"
            f"处理报告：{report_path}\n"
            f"坐标模式：{scale_text}\n"
            f"状态：{self._workflow.state.name}",
        )
        self.statusBar().showMessage(
            f"DXF 已导出并验证：{result.path}；状态 {self._workflow.state.name}"
        )
