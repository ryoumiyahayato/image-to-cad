from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QSplitter

from app.ocr.auxiliary_recognition import TextCandidate
from app.gui import MainWindow
from app.gui.review_actions import LibreCadOcrReviewDialog
from app.gui import MainWindow as PublicMainWindow
from app.export.ocr_outline_export import accepted_ocr_texts


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_normal_exact_ui_hides_unused_panels_and_groups_generation() -> None:
    _application()
    window = MainWindow()
    try:
        assert window.tabs.indexOf(window.preprocess_tabs) == -1
        assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == ['SOURCE REFERENCE / 原图', 'FINAL OUTPUT PREVIEW / CAD 预览', '视觉验收']
        groups = {group.title(): group for group in window.findChildren(QGroupBox)}
        assert {'生成 CAD', '检查与修改', '文字识别', '输出设置'} <= groups.keys()
        assert not {'视图', '高级识别参数', '跨文件合并队列'} & groups.keys()
        buttons = {button.text(): button for button in window.findChildren(QPushButton)}
        assert {'处理当前页', '处理全部页面', '导出当前页 CAD', '导出已处理页面（每页独立文件）'} <= buttons.keys()
    finally:
        window.close()


def _pending_candidate() -> TextCandidate:
    return TextCandidate(
        text="A",
        bbox=(10, 10, 30, 20),
        confidence=0.80,
        kind="text_candidate",
        approved=True,
        reviewed=False,
    )


def test_recognizable_ocr_is_available_without_manual_save() -> None:
    _application()
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    dialog = LibreCadOcrReviewDialog(image, (_pending_candidate(),))
    try:
        assert accepted_ocr_texts(dialog.reviewed_texts()) == dialog.reviewed_texts()
        dialog.accept()
        saved = dialog.reviewed_texts()[0]
        assert not saved.reviewed
        assert accepted_ocr_texts((saved,)) == (saved,)
    finally:
        dialog.close()


def test_public_sidebar_opens_fully_without_deprecated_feature_copy() -> None:
    application = _application()
    window = PublicMainWindow()
    try:
        window.resize(1920, 1080)
        window.show()
        application.processEvents()
        splitter = window.centralWidget()
        assert isinstance(splitter, QSplitter)
        scroll = splitter.widget(0)
        assert scroll.width() >= 500
        assert scroll.horizontalScrollBar().maximum() == 0

        visible_text = []
        for widget_type in (QGroupBox, QPushButton, QLabel):
            for widget in window.findChildren(widget_type):
                if not widget.isVisible():
                    continue
                visible_text.append(
                    widget.title() if isinstance(widget, QGroupBox) else widget.text()
                )
        joined = "\n".join(visible_text)
        for deprecated in ("CAD 轮廓", "LibreCAD", "LFF", "逐字"):
            assert deprecated not in joined
    finally:
        window.close()


def test_editing_ocr_updates_final_cad_font_preview_and_confirms_export() -> None:
    _application()
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    dialog = LibreCadOcrReviewDialog(image, (_pending_candidate(),))
    try:
        dialog.text_edit.setText("B")
        reviewed = dialog.reviewed_texts()[0]
        assert reviewed.text == "B"
        assert reviewed.reviewed
        assert reviewed.approved
        assert reviewed.font_family
        assert reviewed.font_file
        assert accepted_ocr_texts((reviewed,)) == (reviewed,)

        preview = dialog._cad_preview_text_items[0]
        mask = dialog._cad_preview_mask_items[0]
        assert preview.text() == "B"
        assert preview.isVisible()
        assert mask.isVisible()
        assert dialog.preview_checkbox is not None
        assert dialog.preview_checkbox.isChecked()

        dialog.preview_checkbox.setChecked(False)
        assert not preview.isVisible()
        assert not mask.isVisible()
        dialog.preview_checkbox.setChecked(True)
        assert preview.isVisible()
        assert mask.isVisible()
    finally:
        dialog.close()
