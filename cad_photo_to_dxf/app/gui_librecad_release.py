from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from .gui_exact_release import MainWindow as _ExactMainWindow
from .librecad_lff import install_librecad_font
from .librecad_ocr_review import LibreCadLffOcrReviewDialog as _BaseOcrReviewDialog
from .ocr_outline_export import accepted_ocr_texts
from .ocr_recognition import render_ocr_overlay


class LibreCadOcrReviewDialog(_BaseOcrReviewDialog):
    """Preserve pending OCR decisions when the dialog is saved unchanged."""

    def accept(self) -> None:  # type: ignore[override]
        QDialog.accept(self)

    def _refresh_selected_state(self) -> None:
        super()._refresh_selected_state()
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None or not candidate.review_note:
            return
        note = f"原笔画检查：{candidate.review_note}"
        current = self.confidence_label.text()
        if note not in current:
            self.confidence_label.setText(f"{current}\n{note}")


class MainWindow(_ExactMainWindow):
    """LibreCAD shell with native LFF preview and editable Unicode characters."""

    def __init__(self) -> None:
        self._librecad_font_install_report = install_librecad_font(
            request_elevation=False
        )
        super().__init__()
        self.statusBar().showMessage(self._librecad_font_install_report.summary())

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        for group in scroll.findChildren(QGroupBox):
            if group.title() == "文字 OCR 与可编辑文字":
                group.setTitle(
                    "文字 OCR、内置字体匹配（LibreCAD LFF）与单字可编辑文字"
                )
        for checkbox in scroll.findChildren(QCheckBox):
            if checkbox.text().startswith("先识别完整文字行"):
                checkbox.setText("分块识别小字，再逐字确认（签名默认保留原轮廓）")
                checkbox.setToolTip(
                    "大图会按原分辨率分块识别小字。普通印刷文字按原笔画间隔"
                    "生成逐字定位框；签名、手写体和跨字符连笔默认不替换原轮廓，"
                    "只有人工确认后才导出为独立 CAD TEXT。"
                )
        for label in scroll.findChildren(QLabel):
            text = label.text()
            if text.startswith("OCR 结果按完整文字行导出为一个可编辑 TEXT"):
                label.setText(
                    "大幅工程图会使用重叠分块恢复小字，并根据原图笔画间隔为每个字"
                    "建立独立位置框。橙色候选表示签名、手写体、图形或覆盖不足，"
                    "默认保留完整原轮廓；紫色和绿色候选才替换为可编辑 TEXT。"
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
                button.setText("检查逐字位置、签名保留与 LibreCAD 字形")
        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "可处理当前页或全部页面；大页 OCR 会增加分块识别时间。"
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
        pending_layout = sum(
            1
            for item in self._ocr_texts
            if not item.reviewed and not item.replacement_safe
        )
        self.statusBar().showMessage(
            f"已保存 OCR 复核：确认 {len(exportable)} 行 / {character_count} 个独立字符；"
            f"保留原轮廓待确认 {pending_layout} 行"
        )
