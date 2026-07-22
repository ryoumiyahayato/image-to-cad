from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QSplitter

from app.auxiliary_recognition import TextCandidate
from app.gui_exact_release import MainWindow
from app.gui_librecad_release import LibreCadOcrReviewDialog
from app.gui_public_release import MainWindow as PublicMainWindow
from app.ocr_outline_export import accepted_ocr_texts


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_normal_exact_ui_hides_unused_panels_and_groups_generation() -> None:
    _application()
    window = MainWindow()
    try:
        assert window.tabs.indexOf(window.preprocess_tabs) == -1
        assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
            "原图",
            "校正图",
            "CAD 轮廓预览",
        ]

        groups = {group.title(): group for group in window.findChildren(QGroupBox)}
        assert groups["视图"].isHidden()
        assert groups["纸张与坐标（照片可选）"].isHidden()
        assert groups["高级识别参数"].isHidden()
        assert not groups["CAD 轮廓生成"].isHidden()
        assert not groups["检查与验证"].isHidden()

        buttons = {
            button.text(): button for button in window.findChildren(QPushButton)
        }
        assert "生成当前 PDF 全部页 CAD 轮廓" in buttons
        assert "生成当前 PDF 全部页 CAD 轮廓（可取消）" not in buttons
        assert "按已知尺寸校准（可选）" in buttons
        assert buttons["按已知尺寸校准（可选）"].isHidden()
        assert buttons["生成当前页 CAD 轮廓"].parentWidget().title() == "CAD 轮廓生成"
        assert (
            buttons["生成当前 PDF 全部页 CAD 轮廓"].parentWidget().title()
            == "CAD 轮廓生成"
        )
        assert (
            buttons["检查并修正当前页 CAD 轮廓"].parentWidget().title()
            == "检查与验证"
        )
        assert buttons["验证当前页"].parentWidget().title() == "检查与验证"
        assert window.show_advanced_checkbox.isHidden()
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


def test_pending_ocr_is_not_approved_by_unchanged_save() -> None:
    _application()
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    dialog = LibreCadOcrReviewDialog(image, (_pending_candidate(),))
    try:
        assert accepted_ocr_texts(dialog.reviewed_texts()) == ()
        dialog.accept()
        saved = dialog.reviewed_texts()[0]
        assert not saved.reviewed
        assert accepted_ocr_texts((saved,)) == ()
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
