from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox

from .cancellation import CancellationToken
from .geometry_cleaner import GeometryCleanParams
from .gui import MainWindow as _LegacyMainWindow
from .line_detect import LineDetectionParams
from .pipeline_service import PipelineService, VectorizationResult
from .preprocess import PreprocessParams, PreprocessResult


class MainWindow(_LegacyMainWindow):
    """Active GUI with guarded state and the shared processing service."""

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
