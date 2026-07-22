from __future__ import annotations

from datetime import datetime, timezone
import time

from PySide6.QtWidgets import QDialog, QMessageBox

from .gui_final_release import MainWindow as _OptimizedMainWindow
from .raster_trace import RasterTraceResult, trace_binary
from .trace_paint import TracePaintDialog
from .trace_verification import TraceVerificationResult, verify_trace_paths


class MainWindow(_OptimizedMainWindow):
    """Final user-facing terminology for editing and verification actions."""

    def review_layers(self) -> None:
        if self.binary_image is None:
            QMessageBox.warning(self, "尚无处理结果", "请先处理当前页。")
            return
        dialog = TracePaintDialog(self.binary_image, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.edited_binary()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        revision = self._state_revision

        def operation(token, progress) -> object:
            paths = trace_binary(
                edited,
                cancellation_token=token,
                progress_callback=progress,
            )
            return RasterTraceResult(
                binary=edited,
                stages={},
                paths=paths,
                threshold=self._trace_threshold or 128,
                foreground_pixels=int((edited == 0).sum()),
                vertex_count=sum(len(path.points) for path in paths),
                warnings=(),
                texts=tuple(self._ocr_texts),
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )
            self.statusBar().showMessage("已按修改内容重新生成当前页 CAD")

        self._start_processing(operation, completed, "正在应用修改并重新生成 CAD…")

    def verify_current_trace(self) -> None:
        if self.binary_image is None or not self._trace_paths:
            QMessageBox.warning(self, "尚无处理结果", "请先处理当前页。")
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        binary = self.binary_image.copy()
        paths = tuple(self._trace_paths)
        revision = self._state_revision

        def operation(token, progress) -> object:
            return verify_trace_paths(
                binary,
                paths,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            result: TraceVerificationResult = value  # type: ignore[assignment]
            self.detected_canvas.set_image(
                self._scaled_for_preview(
                    result.overlay,
                    target_shape=self._preview_shape(),
                )
            )
            self.tabs.setCurrentWidget(self.detected_canvas)
            if result.exact:
                QMessageBox.information(
                    self,
                    "核对完成",
                    "当前页生成内容与黑白来源一致，没有发现遗漏像素。",
                )
            else:
                QMessageBox.warning(
                    self,
                    "发现差异",
                    f"发现 {result.different_pixels} 个差异像素，请进入检查与修改。",
                )

        self._start_processing(operation, completed, "正在核对当前页…")
