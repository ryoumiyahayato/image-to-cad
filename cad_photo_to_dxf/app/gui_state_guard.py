from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import QMessageBox

from .gui_review import MainWindow as _ReviewedMainWindow


class MainWindow(_ReviewedMainWindow):
    """Final GUI entry point with transactional image-state changes."""

    def auto_perspective(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        if not self._require_original():
            return

        # A new automatic-correction attempt supersedes every result derived
        # from the previous corrected image. If detection fails or is rejected,
        # the GUI must not silently retain and export the stale correction.
        self.corrected_image = None
        self.calibration = None
        self._perspective_metadata = None
        self._invalidate_preprocess_results()
        self.corrected_canvas.set_image(None)
        self.info_label.setText("比例：正在重新识别纸张，旧校正结果已失效")
        super().auto_perspective()

    def rotate_corrected(self, degrees: int) -> None:
        revision_before = self._state_revision
        metadata_before = deepcopy(self._perspective_metadata)
        super().rotate_corrected(degrees)
        if self._state_revision == revision_before:
            # The parent returns without rotating while another task is active.
            # Restore metadata because the guarded parent may otherwise append a
            # rotation record even though the pixels did not change.
            self._perspective_metadata = metadata_before
