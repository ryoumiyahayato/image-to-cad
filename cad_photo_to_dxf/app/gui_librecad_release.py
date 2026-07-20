from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from .font_ocr_review import FontAwareOcrReviewDialog as _BaseOcrReviewDialog
from .gui_exact_release import MainWindow as _ExactMainWindow
from .ocr_outline_export import accepted_ocr_texts
from .ocr_recognition import render_ocr_overlay


class LibreCadOcrReviewDialog(_BaseOcrReviewDialog):
    """Preserve pending OCR decisions when the dialog is saved unchanged."""

    def accept(self) -> None:  # type: ignore[override]
        # Editing and the approval checkbox already persist decisions immediately.
        # Calling the base override here would approve the currently selected
        # candidate merely because the user pressed Save without changing it.
        QDialog.accept(self)


class MainWindow(_ExactMainWindow):
    """LibreCAD shell with live OCR review and editable character export."""

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        for group in scroll.findChildren(QGroupBox):
            if group.title() == "文字 OCR 与可编辑文字":
                group.setTitle("文字 OCR、字体匹配与单字可编辑文字")
        for checkbox in scroll.findChildren(QCheckBox):
            if checkbox.text().startswith("先识别完整文字行"):
                checkbox.setText("先识别横排文字候选，再人工确认字体与可编辑文字（推荐）")
                checkbox.setToolTip(
                    "不确定候选不会自动替换原轮廓；确认后每个汉字、字母和数字"
                    "分别导出为独立 CAD TEXT，并引用复核界面选择的字体。"
                )
        for label in scroll.findChildren(QLabel):
            text = label.text()
            if text.startswith("OCR 结果按完整文字行导出为一个可编辑 TEXT"):
                label.setText(
                    "OCR 候选可在原图上实时预览、自动匹配或人工选择字体。"
                    "导出后每个汉字、字母和数字分别成为独立 TEXT；"
                    "预览与 DXF/DWG 引用同一字体文件名。"
                )
            elif text.startswith("多页 PDF 默认合并到一个 DXF/DWG"):
                label.setText(
                    "多页 PDF 导出时每页生成一个独立 DXF/DWG 文件，"
                    "保存在同一输出文件夹中。"
                )
        for button in scroll.findChildren(QPushButton):
            if button.text().startswith("6. 导出同一 CAD"):
                button.setText("6. 导出 CAD（PDF 每页独立文件）")
            elif button.text() == "检查并修改 OCR 文字":
                button.setText("检查、预览、匹配字体并确认 OCR 文字")
        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "可处理当前页或全部页面；导出时多页会分别生成独立 CAD 文件。"
            )
        return scroll

    def review_ocr_texts(self) -> None:
        if not self._ocr_texts:
            QMessageBox.warning(self, "尚无 OCR 文字", "请先生成当前页 CAD 轮廓。")
            return
        source = (
            self.corrected_image
            if self.corrected_image is not None
            else self.original_image
        )
        if source is None:
            return
        dialog = LibreCadOcrReviewDialog(source, tuple(self._ocr_texts), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._ocr_texts = dialog.reviewed_texts()
        self._dirty_trace_keys.add(self._current_trace_key())
        self.preprocess_stages["OCR 文字识别结果"] = render_ocr_overlay(
            source,
            self._ocr_texts,
        )
        self._show_preprocess_stages(self.preprocess_stages)
        if self._native_pdf_mode:
            self._save_current_pdf_state()
        exportable = accepted_ocr_texts(self._ocr_texts)
        character_count = sum(
            1
            for item in exportable
            for character in item.text
            if not character.isspace()
        )
        font_count = len(
            {
                (item.font_family, item.font_file)
                for item in exportable
                if item.font_family or item.font_file
            }
        )
        self.statusBar().showMessage(
            f"已保存 OCR 与字体复核：候选 {len(self._ocr_texts)} 行，"
            f"确认 {len(exportable)} 行 / {character_count} 个独立字符 / {font_count} 种字体"
        )
