from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton

from .gui_exact_release import MainWindow as _ExactMainWindow


class MainWindow(_ExactMainWindow):
    """LibreCAD-stable wording layered on the exact review workflow."""

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()

        for group in scroll.findChildren(QGroupBox):
            if group.title() == "文字 OCR 与可编辑文字":
                group.setTitle("文字 OCR 与整行矢量")

        for checkbox in scroll.findChildren(QCheckBox):
            if checkbox.text().startswith("先识别完整文字行"):
                checkbox.setText(
                    "先识别完整横排文字行，再生成非文字 CAD 轮廓（推荐）"
                )
                checkbox.setToolTip(
                    "每个识别文字行在 DXF 中生成一个字体无关的矢量块；"
                    "不会再依赖 LibreCAD 的 TTF/SHX 中文字体解析。"
                )

        for label in scroll.findChildren(QLabel):
            text = label.text()
            if text.startswith("OCR 结果按完整文字行导出为一个可编辑 TEXT"):
                label.setText(
                    "OCR 结果在导出时按整行生成一个矢量块。"
                    "识别错误请在导出前修改；LibreCAD 中不会再出现菱形乱码、"
                    "单字 TEXT 或纵向文字塔。"
                )
            elif text.startswith("多页 PDF 默认合并到一个 DXF/DWG"):
                label.setText(
                    "多页 PDF 导出时每页生成一个独立 DXF/DWG 文件，"
                    "保存在同一输出文件夹中；不再把多页塞进同一个模型空间。"
                )

        for button in scroll.findChildren(QPushButton):
            if button.text().startswith("6. 导出同一 CAD"):
                button.setText("6. 导出 CAD（PDF 每页独立文件）")

        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "可处理当前页或全部页面；导出时多页会分别生成独立 CAD 文件。"
            )
        return scroll
