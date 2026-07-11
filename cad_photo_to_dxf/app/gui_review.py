from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from .auxiliary_recognition import CircleCandidate, confirmable_circles
from .circle_review import CircleReviewDialog
from .gui_export import export_from_window
from .gui_guard import MainWindow as _GuardedMainWindow
from .layer_review import LayerReviewDialog, layer_counts
from .line_detect import render_line_preview


class MainWindow(_GuardedMainWindow):
    """Guarded GUI with explicit semantic and circle review."""

    def __init__(self) -> None:
        self._approved_circles: list[CircleCandidate] = []
        super().__init__()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is not None:
            layer_button = self._button("5. 人工复核图层", self.review_layers)
            circle_button = self._button("6. 人工确认圆形", self.review_circles)
            # Insert after line detection and before scale calibration/export.
            layout.insertWidget(7, layer_button)
            layout.insertWidget(8, circle_button)
        return scroll

    def _invalidate_line_results(self) -> None:
        super()._invalidate_line_results()
        self._approved_circles = []

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

    def review_circles(self) -> None:
        if self.auxiliary_result is None:
            QMessageBox.warning(
                self,
                "尚无圆形候选",
                "请启用辅助识别并重新执行“识别并清理线条”。",
            )
            return
        eligible = confirmable_circles(self.auxiliary_result.circles)
        if not eligible:
            QMessageBox.information(
                self,
                "没有可确认圆形",
                "当前没有达到保守置信度阈值的圆形候选。不会导出 CIRCLE。",
            )
            self._approved_circles = []
            return
        dialog = CircleReviewDialog(self.auxiliary_result.circles, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._approved_circles = dialog.approved_circles()
        warning = (
            f"人工确认 {len(self._approved_circles)} 个圆形候选可导出为 DXF CIRCLE。"
        )
        self._last_warnings = tuple(
            dict.fromkeys((*self._last_warnings, warning))
        )
        self.statusBar().showMessage(warning)

    def export_file(self) -> None:
        export_from_window(self, circles=self._approved_circles)
