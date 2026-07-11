from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from .gui_guard import MainWindow as _GuardedMainWindow
from .layer_review import LayerReviewDialog, layer_counts
from .line_detect import render_line_preview


class MainWindow(_GuardedMainWindow):
    """Guarded GUI with explicit per-entity layer review."""

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is not None:
            review_button = self._button("5. 人工复核图层", self.review_layers)
            # Insert after line detection and before scale calibration/export.
            layout.insertWidget(7, review_button)
        return scroll

    def review_layers(self) -> None:
        if not self.lines:
            QMessageBox.warning(
                self,
                "尚无可复核实体",
                "请先完成“识别并清理线条”，再进行逐实体图层复核。",
            )
            return
        if self.binary_image is None:
            return
        dialog = LayerReviewDialog(self.lines, self)
        if dialog.exec() != QDialog.Accepted:
            return
        reviewed, changed = dialog.reviewed_lines()
        self.lines = reviewed
        if self.classification_report is not None:
            self.classification_report.layer_counts = layer_counts(reviewed)
        preview = render_line_preview(self.binary_image, reviewed)
        self.detected_canvas.set_image(preview)
        self.tabs.setCurrentWidget(self.detected_canvas)
        if changed:
            warning = f"人工复核已修改 {changed} 条实体的图层。"
            self._last_warnings = tuple(
                dict.fromkeys((*self._last_warnings, warning))
            )
        self.statusBar().showMessage(
            f"图层复核完成；共 {len(reviewed)} 条实体，人工修改 {changed} 条"
        )
