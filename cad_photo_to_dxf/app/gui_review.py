from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from .auxiliary_recognition import (
    AuxiliaryRecognitionResult,
    confirmable_circles,
)
from .gui_export import export_from_window
from .gui_guard import MainWindow as _GuardedMainWindow
from .layer_review import layer_counts
from .visual_review import VectorReviewDialog


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

    def _current_review_circles(self):
        reviewed = getattr(self, "_reviewed_circles", None)
        if reviewed is not None:
            return list(reviewed)
        if self.auxiliary_result is None:
            return []
        return confirmable_circles(self.auxiliary_result.circles)

    def review_layers(self) -> None:
        background = (
            self.corrected_image
            if self.corrected_image is not None
            else self.binary_image
        )
        if background is None:
            QMessageBox.warning(
                self,
                "尚无可修改图纸",
                "请先导入图纸并完成照片校正；可在没有自动识别结果时手工新增实体。",
            )
            return
        circles = self._current_review_circles()
        texts = (
            list(self.auxiliary_result.texts)
            if self.auxiliary_result is not None
            else []
        )
        before_counts = (len(self.lines), len(circles), len(texts))
        dialog = VectorReviewDialog(
            background,
            self.lines,
            circles=circles,
            texts=texts,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reviewed_lines, reviewed_circles, reviewed_texts = dialog.reviewed_entities()
        self.lines = reviewed_lines
        self._reviewed_circles = list(reviewed_circles)
        if self.classification_report is not None:
            self.classification_report.layer_counts = layer_counts(reviewed_lines)
        if self.auxiliary_result is None:
            self.auxiliary_result = AuxiliaryRecognitionResult(
                circles=list(reviewed_circles),
                texts=list(reviewed_texts),
                dimension_texts=[
                    text
                    for text in reviewed_texts
                    if text.kind == "dimension_text_candidate"
                ],
                symbols=[],
                warnings=[],
            )
        else:
            self.auxiliary_result.circles = list(reviewed_circles)
            self.auxiliary_result.texts = list(reviewed_texts)
            self.auxiliary_result.dimension_texts = [
                text
                for text in reviewed_texts
                if text.kind == "dimension_text_candidate"
            ]
        self.detected_canvas.set_vector_result(
            background,
            reviewed_lines,
            circles=reviewed_circles,
            texts=reviewed_texts,
        )
        self.tabs.setCurrentWidget(self.detected_canvas)
        after_counts = (
            len(reviewed_lines),
            len(reviewed_circles),
            len(reviewed_texts),
        )
        warning = (
            "可视化修改已保存："
            f"LINE {before_counts[0]}→{after_counts[0]}，"
            f"CIRCLE {before_counts[1]}→{after_counts[1]}，"
            f"TEXT {before_counts[2]}→{after_counts[2]}。"
        )
        self._last_warnings = tuple(dict.fromkeys((*self._last_warnings, warning)))
        save_state = getattr(self, "_save_current_pdf_state", None)
        if callable(save_state):
            save_state()
        self.statusBar().showMessage(warning)

    def export_file(self) -> None:
        export_from_window(self, circles=self._current_review_circles())
