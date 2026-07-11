from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMessageBox

from .cancellation import CancellationToken
from .geometry_cleaner import GeometryCleanParams
from .gui import MainWindow as _LegacyMainWindow
from .line_detect import LineDetectionParams
from .preprocess import PreprocessParams
from .processing_service import (
    ProcessingConfig,
    ProcessingResult,
    process_corrected_image,
)


class MainWindow(_LegacyMainWindow):
    """GUI entrypoint with strict perspective state and one shared pipeline."""

    def _require_corrected(self) -> bool:
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "尚未确认透视校正",
            "请先执行“自动透视校正”，或使用“手动点击四角并校正”。\n"
            "系统不会再把原始照片静默当作已校正图像。",
        )
        self.statusBar().showMessage("处理已阻止：必须先确认纸张四角和透视校正")
        return False

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
            result = value
            if not isinstance(result, ProcessingResult):
                raise TypeError("Shared processing service returned an invalid result")

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
            details = ", ".join(
                f"{key}:{value}" for key, value in sorted(counts.items())
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
                f"分辨率系数 {result.detection_resolution_factor:.3f}"
            )

        self._start_processing(operation, completed, "正在通过共享管线识别和清理…")
