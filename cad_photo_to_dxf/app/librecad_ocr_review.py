from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsPathItem,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from .librecad_lff import (
    LIBRECAD_FONT_FAMILY,
    LIBRECAD_FONT_FILENAME,
    install_librecad_font,
    preview_text_path,
)
from .ocr_outline_export import accepted_ocr_texts
from .ocr_review import OcrReviewDialog


class _TextPathPreviewItem(QGraphicsPathItem):
    """QGraphicsPathItem with the old text-item inspection interface."""

    def __init__(self) -> None:
        super().__init__(QPainterPath())
        self._content = ""

    def setText(self, text: str) -> None:
        self._content = str(text)
        self.setPath(preview_text_path(self._content))

    def text(self) -> str:
        return self._content


class LibreCadLffOcrReviewDialog(OcrReviewDialog):
    """Show the same native LFF strokes that LibreCAD uses after DXF export."""

    def __init__(self, image: np.ndarray, candidates, parent=None) -> None:
        self._source_image = np.ascontiguousarray(image.copy())
        self._preview_paths: dict[int, _TextPathPreviewItem] = {}
        self._preview_masks: dict[int, object] = {}
        # Compatibility names retained for UI regression tests and extensions.
        self._cad_preview_text_items = self._preview_paths
        self._cad_preview_mask_items = self._preview_masks
        self._show_all_previews = True
        self._install_report = install_librecad_font(request_elevation=False)
        self.preview_checkbox: QCheckBox | None = None
        self.font_status_label: QLabel | None = None
        super().__init__(image, candidates, parent)
        self.setWindowTitle("检查、预览并确认 LibreCAD 中文 OCR 文字")
        self.preview_item.setVisible(False)

        for index in range(len(self._candidates)):
            self._force_lff(index)

        panel = self.text_edit.parentWidget()
        layout = panel.layout() if panel is not None else None
        if layout is not None:
            title = QLabel(
                "LibreCAD 中文字体：wqy-unicode.lff（预览与 DXF 完全同源）",
                panel,
            )
            title.setWordWrap(True)
            row = QHBoxLayout()
            repair = QPushButton("安装/修复 LibreCAD 中文 LFF 字体", panel)
            use_font = QPushButton("对当前候选使用 LibreCAD 字体", panel)
            row.addWidget(repair)
            row.addWidget(use_font)

            self.preview_checkbox = QCheckBox(
                "在原图上显示全部已确认文字的最终 LibreCAD 字形",
                panel,
            )
            self.preview_checkbox.setChecked(True)
            self.font_status_label = QLabel(self._install_report.summary(), panel)
            self.font_status_label.setWordWrap(True)
            note = QLabel(
                "LibreCAD 的文字引擎读取 LFF，而不是 Windows 的 TTF/OTF。"
                "上一版在本程序里显示 Noto 字体，但 LibreCAD 无法使用，因此出现菱形。"
                "本窗口的紫色笔画直接由 wqy-unicode.lff 解析，导出后的 TEXT 也引用同一字体。",
                panel,
            )
            note.setWordWrap(True)

            insert_at = max(0, layout.indexOf(self.approval_checkbox))
            layout.insertWidget(insert_at, title)
            layout.insertLayout(insert_at + 1, row)
            layout.insertWidget(insert_at + 2, self.preview_checkbox)
            layout.insertWidget(insert_at + 3, self.font_status_label)
            layout.insertWidget(insert_at + 4, note)

            repair.clicked.connect(self._repair_font)
            use_font.clicked.connect(self._apply_lff_to_current)
            self.preview_checkbox.toggled.connect(self._toggle_previews)

        self._update_all_previews()
        if self._selected_index is not None:
            self._refresh_selected_state()

    def _force_lff(self, index: int) -> None:
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        if (
            candidate.font_family == LIBRECAD_FONT_FAMILY
            and candidate.font_file.casefold() == LIBRECAD_FONT_FILENAME.casefold()
        ):
            return
        self._candidates[index] = replace(
            candidate,
            font_family=LIBRECAD_FONT_FAMILY,
            font_file=LIBRECAD_FONT_FILENAME,
            font_match_score=1.0,
        )

    def _is_exported(self, candidate) -> bool:
        return bool(accepted_ocr_texts((candidate,)))

    def _items(self, index: int):
        mask = self._preview_masks.get(index)
        path_item = self._preview_paths.get(index)
        if mask is None:
            mask = self.scene_object.addRect(0.0, 0.0, 1.0, 1.0)
            mask.setPen(QPen(Qt.PenStyle.NoPen))
            mask.setBrush(QBrush(QColor(255, 255, 255, 235)))
            mask.setZValue(14.0)
            self._preview_masks[index] = mask
        if path_item is None:
            path_item = _TextPathPreviewItem()
            self.scene_object.addItem(path_item)
            path_item.setPen(QPen(QColor(210, 0, 190), 0.8))
            path_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            path_item.setOpacity(0.96)
            path_item.setZValue(15.0)
            self._preview_paths[index] = path_item
        return mask, path_item

    def _update_preview(self, index: int) -> None:
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        old_mask = self._preview_masks.get(index)
        old_path = self._preview_paths.get(index)
        visible = bool(
            candidate is not None
            and self._show_all_previews
            and self._is_exported(candidate)
            and candidate.text.strip()
        )
        if not visible:
            if old_mask is not None:
                old_mask.setVisible(False)
            if old_path is not None:
                old_path.setVisible(False)
            return

        assert candidate is not None
        self._force_lff(index)
        candidate = self._candidates[index]
        assert candidate is not None
        mask, path_item = self._items(index)
        x, y, width, height = candidate.bbox
        mask.setRect(float(x), float(y), float(width), float(height))
        mask.setVisible(True)

        content = " ".join(
            candidate.text.replace("\r", " ").replace("\n", " ").split()
        )
        path_item.setText(content)
        path_item.setScale(1.0)
        path_item.setRotation(float(candidate.rotation_deg))
        bounds = path_item.boundingRect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            path_item.setVisible(False)
            return
        scale = max(
            0.01,
            min(
                float(width) * 0.94 / bounds.width(),
                float(height) * 0.90 / bounds.height(),
            ),
        )
        path_item.setScale(scale)
        path_item.setPos(
            float(x) + (float(width) - bounds.width() * scale) * 0.5
            - bounds.left() * scale,
            float(y) + (float(height) - bounds.height() * scale) * 0.5
            - bounds.top() * scale,
        )
        path_item.setVisible(True)

    def _update_all_previews(self) -> None:
        for index in range(len(self._candidates)):
            self._update_preview(index)

    def _refresh_candidate_style(self, index: int) -> None:
        super()._refresh_candidate_style(index)
        if hasattr(self, "scene_object"):
            self._update_preview(index)

    def _select_index(self, index: int | None, *, center: bool) -> None:
        if index is not None:
            self._force_lff(index)
        super()._select_index(index, center=center)
        self.preview_item.setVisible(False)

    def _refresh_selected_state(self) -> None:
        super()._refresh_selected_state()
        self.preview_item.setVisible(False)
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        self._force_lff(index)
        self.confidence_label.setText(
            f"{self.confidence_label.text()}\n"
            f"LibreCAD 字体：{LIBRECAD_FONT_FAMILY}（{LIBRECAD_FONT_FILENAME}）\n"
            "字形来源：LibreCAD 原生 LFF 笔画\n"
            "可编辑性：每个非空字符仍是独立 DXF TEXT\n"
            "紫色预览与 LibreCAD 打开 DXF 后使用同一字体文件。"
        )
        self._update_preview(index)

    def _apply_lff_to_current(self) -> None:
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        self._candidates[index] = replace(
            candidate,
            font_family=LIBRECAD_FONT_FAMILY,
            font_file=LIBRECAD_FONT_FILENAME,
            font_match_score=1.0,
            reviewed=True,
        )
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _repair_font(self) -> None:
        self._install_report = install_librecad_font(request_elevation=True)
        if self.font_status_label is not None:
            self.font_status_label.setText(self._install_report.summary())

    def _toggle_previews(self, checked: bool) -> None:
        self._show_all_previews = bool(checked)
        self._update_all_previews()

    def _apply_current_text(self) -> None:
        index = self._selected_index
        if index is not None:
            self._force_lff(index)
        super()._apply_current_text()
        if index is not None:
            self._force_lff(index)
            self._update_preview(index)

    def _delete_current(self) -> None:
        index = self._selected_index
        super()._delete_current()
        if index is not None:
            self._update_preview(index)
