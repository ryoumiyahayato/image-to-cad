from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from .gui_export import export_from_window
from .gui_guard import MainWindow as _GuardedMainWindow
from .layer_review import LayerReviewDialog, layer_counts
from .line_detect import render_line_preview


class MainWindow(_GuardedMainWindow):
    """Guarded GUI with direct visual editing on top of the source scan."""

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is not None:
            review_button = self._button("5. 可视化修改识别结果", self.review_layers)
            layout.insertWidget(7, review_button)
        return scroll

    def review_layers(self) -> None:
        if not self.lines:
            QMessageBox.warning(
                self,
                "尚无可修改实体",
                "请先完成自动识别，再在图纸上选择、删除或修改线段。",
            )
            return
        background = (
            self.corrected_image
            if self.corrected_image is not None
            else self.binary_image
        )
        dialog = LayerReviewDialog(
            self.lines,
            self,
            background=background,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        reviewed, changed = dialog.reviewed_lines()
        self.lines = reviewed
        if self.classification_report is not None:
            self.classification_report.layer_counts = layer_counts(reviewed)
        preview_base = background if background is not None else self.binary_image
        if preview_base is not None:
            preview = render_line_preview(preview_base, reviewed)
            self.detected_canvas.set_image(preview)
            self.tabs.setCurrentWidget(self.detected_canvas)
        if changed:
            warning = (
                f"可视化修改影响 {changed} 条实体；"
                f"其中删除 {dialog.deleted_count} 条。"
            )
            self._last_warnings = tuple(
                dict.fromkeys((*self._last_warnings, warning))
            )
        self.statusBar().showMessage(
            f"可视化修改完成；保留 {len(reviewed)} 条实体，影响 {changed} 条"
        )

    def export_file(self) -> None:
        # Circle candidates remain report-only. The normal workflow no longer asks
        # users to approve a coordinate table they cannot judge visually.
        export_from_window(self, circles=[])
