from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton

from .font_library import (
    available_font_faces,
    default_font_face,
    find_font_face,
    match_font_face,
)
from .ocr_review import OcrReviewDialog


class FontAwareOcrReviewDialog(OcrReviewDialog):
    """Use the same selected font for source preview and DXF/DWG export."""

    def __init__(self, image: np.ndarray, candidates, parent=None) -> None:
        self._font_source_image = np.ascontiguousarray(image.copy())
        self._font_faces = available_font_faces()
        self.font_combo: QComboBox | None = None
        self.match_font_button: QPushButton | None = None
        super().__init__(image, candidates, parent)
        self.setWindowTitle("检查、预览、匹配字体并确认 OCR 文字")

        panel = self.text_edit.parentWidget()
        panel_layout = panel.layout() if panel is not None else None
        if panel_layout is not None:
            font_label = QLabel("CAD 字体库（预览与 DXF/DWG 使用同一字体）", panel)
            font_row = QHBoxLayout()
            self.font_combo = QComboBox(panel)
            for face in self._font_faces:
                self.font_combo.addItem(face.label, face.filename)
            self.match_font_button = QPushButton("自动匹配原字形", panel)
            font_row.addWidget(self.font_combo, 1)
            font_row.addWidget(self.match_font_button)
            insert_at = max(0, panel_layout.indexOf(self.approval_checkbox))
            panel_layout.insertWidget(insert_at, font_label)
            panel_layout.insertLayout(insert_at + 1, font_row)
            self.font_combo.currentIndexChanged.connect(self._font_changed)
            self.match_font_button.clicked.connect(self._match_current_font)

            note = QLabel(
                "自动匹配会比较原图笔画与本机已安装的常用中文/西文字体。"
                "所选字体文件名会写入 DXF 文字样式；应用内预览与 CAD 使用同一选择。"
                "DXF/DWG 不能嵌入字体，另一台电脑仍需安装同名字体。",
                panel,
            )
            note.setWordWrap(True)
            panel_layout.insertWidget(insert_at + 2, note)

        if self._selected_index is not None:
            self._ensure_candidate_font(self._selected_index)
            self._refresh_selected_state()

    def _face_for_candidate(self, candidate):
        return find_font_face(candidate.font_family, candidate.font_file, candidate.text)

    def _ensure_candidate_font(self, index: int) -> None:
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None or candidate.font_family:
            return
        face, score = match_font_face(
            self._font_source_image,
            candidate.bbox,
            candidate.text,
        )
        self._candidates[index] = replace(
            candidate,
            font_family=face.family,
            font_file=face.filename,
            font_match_score=score,
        )

    def _select_index(self, index: int | None, *, center: bool) -> None:
        if index is not None and 0 <= index < len(self._candidates):
            self._ensure_candidate_font(index)
        super()._select_index(index, center=center)

    def _refresh_selected_state(self) -> None:
        super()._refresh_selected_state()
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        face = self._face_for_candidate(candidate)

        if self.font_combo is not None:
            selected = next(
                (
                    position
                    for position, item in enumerate(self._font_faces)
                    if item.filename.casefold() == face.filename.casefold()
                    or item.family.casefold() == face.family.casefold()
                ),
                0,
            )
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(selected)
            self.font_combo.blockSignals(False)

        x, y, width, height = candidate.bbox
        content = self.text_edit.text()
        font = QFont(face.family)
        font.setPixelSize(max(8, int(height * 0.82)))
        self.preview_item.setFont(font)
        self.preview_item.setScale(1.0)
        bounds = self.preview_item.boundingRect()
        if content and bounds.width() > 0 and bounds.height() > 0:
            scale = max(
                0.02,
                min(float(width) / bounds.width(), float(height) / bounds.height()),
            )
            self.preview_item.setScale(scale)
            self.preview_item.setPos(
                float(x) + (float(width) - bounds.width() * scale) * 0.5,
                float(y) + (float(height) - bounds.height() * scale) * 0.5,
            )

        self.confidence_label.setText(
            f"{self.confidence_label.text()}\n"
            f"字体：{face.label}（{face.filename or '系统默认'}）\n"
            f"字形匹配度：{candidate.font_match_score:.1%}\n"
            "当前预览与 DXF/DWG 将引用同一字体选择。"
        )

    def _font_changed(self, combo_index: int) -> None:
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None or not 0 <= combo_index < len(self._font_faces):
            return
        face = self._font_faces[combo_index]
        self._candidates[index] = replace(
            candidate,
            font_family=face.family,
            font_file=face.filename,
            font_match_score=1.0,
            reviewed=True,
        )
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _match_current_font(self) -> None:
        index = self._selected_index
        if index is None or not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        face, score = match_font_face(
            self._font_source_image,
            candidate.bbox,
            self.text_edit.text(),
        )
        self._candidates[index] = replace(
            candidate,
            text=self.text_edit.text(),
            font_family=face.family,
            font_file=face.filename,
            font_match_score=score,
            reviewed=True,
        )
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _apply_current_text(self) -> None:
        index = self._selected_index
        if index is not None and 0 <= index < len(self._candidates):
            candidate = self._candidates[index]
            if candidate is not None and not candidate.font_family:
                face = default_font_face(self.text_edit.text())
                self._candidates[index] = replace(
                    candidate,
                    font_family=face.family,
                    font_file=face.filename,
                )
        super()._apply_current_text()
