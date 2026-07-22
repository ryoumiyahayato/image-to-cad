from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton

from .font_library import (
    available_font_faces,
    default_font_face,
    find_font_face,
    install_bundled_fonts_for_cad,
    match_font_face,
    qfont_for_face,
)
from .ocr_outline_export import accepted_ocr_texts
from .ocr_review import OcrReviewDialog


class FontAwareOcrReviewDialog(OcrReviewDialog):
    """Preview the actual selected CAD font on top of the source drawing."""

    def __init__(self, image: np.ndarray, candidates, parent=None) -> None:
        self._font_source_image = np.ascontiguousarray(image.copy())
        self._font_faces = available_font_faces()
        self._cad_preview_text_items: dict[int, object] = {}
        self._cad_preview_mask_items: dict[int, object] = {}
        self._show_all_cad_previews = True
        self.font_combo: QComboBox | None = None
        self.match_font_button: QPushButton | None = None
        self.preview_checkbox: QCheckBox | None = None
        self.font_status_label: QLabel | None = None
        self.install_font_button: QPushButton | None = None
        self._font_install_report = install_bundled_fonts_for_cad()
        super().__init__(image, candidates, parent)
        self.setWindowTitle("检查、预览、匹配字体并确认 OCR 文字")
        self.preview_item.setVisible(False)

        for index, candidate in enumerate(self._candidates):
            if candidate is None:
                continue
            if candidate.reviewed or candidate.confidence >= 0.90:
                self._ensure_candidate_font(index)

        panel = self.text_edit.parentWidget()
        panel_layout = panel.layout() if panel is not None else None
        if panel_layout is not None:
            font_label = QLabel("CAD 字体库（预览和 DXF/DWG 使用同一字体）", panel)
            font_row = QHBoxLayout()
            self.font_combo = QComboBox(panel)
            for face in self._font_faces:
                suffix = "内置" if face.bundled else "本机"
                self.font_combo.addItem(f"{face.label}（{suffix}）", face.filename)
            self.match_font_button = QPushButton("自动匹配原字形", panel)
            font_row.addWidget(self.font_combo, 1)
            font_row.addWidget(self.match_font_button)

            self.preview_checkbox = QCheckBox(
                "在原图上显示全部已确认文字的最终 CAD 字体预览",
                panel,
            )
            self.preview_checkbox.setChecked(True)
            self.preview_checkbox.setToolTip(
                "白色遮罩表示导出时被 OCR 文字替换的原扫描字形；"
                "紫色文字使用实际选择的 CAD 字体和等比缩放。"
            )
            self.font_status_label = QLabel(self._font_install_report.summary(), panel)
            self.font_status_label.setWordWrap(True)
            self.install_font_button = QPushButton("安装/修复内置 CAD 字体", panel)

            insert_at = max(0, panel_layout.indexOf(self.approval_checkbox))
            panel_layout.insertWidget(insert_at, font_label)
            panel_layout.insertLayout(insert_at + 1, font_row)
            panel_layout.insertWidget(insert_at + 2, self.preview_checkbox)
            panel_layout.insertWidget(insert_at + 3, self.font_status_label)
            panel_layout.insertWidget(insert_at + 4, self.install_font_button)

            self.font_combo.currentIndexChanged.connect(self._font_changed)
            self.match_font_button.clicked.connect(self._match_current_font)
            self.preview_checkbox.toggled.connect(self._preview_visibility_changed)
            self.install_font_button.clicked.connect(self._install_fonts_again)

            note = QLabel(
                "内置字体随软件提供，并为当前 Windows 用户自动安装。"
                "复核窗口显示的是最终 CAD 字体预览，而不是普通界面字体。"
                "选择本机字体时，其他电脑仍需安装同名字体；选择内置字体可保持一致。",
                panel,
            )
            note.setWordWrap(True)
            panel_layout.insertWidget(insert_at + 5, note)

        self._update_all_cad_previews()
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

    def _candidate_is_exported(self, candidate) -> bool:
        return bool(accepted_ocr_texts((candidate,)))

    def _preview_items(self, index: int):
        mask = self._cad_preview_mask_items.get(index)
        text_item = self._cad_preview_text_items.get(index)
        if mask is None:
            mask = self.scene_object.addRect(0.0, 0.0, 1.0, 1.0)
            mask.setPen(QPen(Qt.PenStyle.NoPen))
            mask.setBrush(QBrush(QColor(255, 255, 255, 235)))
            mask.setZValue(14.0)
            self._cad_preview_mask_items[index] = mask
        if text_item is None:
            text_item = self.scene_object.addSimpleText("")
            text_item.setBrush(QBrush(QColor(210, 0, 190)))
            text_item.setOpacity(0.96)
            text_item.setZValue(15.0)
            self._cad_preview_text_items[index] = text_item
        return mask, text_item

    def _update_candidate_preview(self, index: int) -> None:
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        existing_mask = self._cad_preview_mask_items.get(index)
        existing_text = self._cad_preview_text_items.get(index)
        visible = bool(
            candidate is not None
            and self._show_all_cad_previews
            and self._candidate_is_exported(candidate)
            and candidate.text.strip()
        )
        if not visible:
            if existing_mask is not None:
                existing_mask.setVisible(False)
            if existing_text is not None:
                existing_text.setVisible(False)
            return

        assert candidate is not None
        self._ensure_candidate_font(index)
        candidate = self._candidates[index]
        assert candidate is not None
        mask, text_item = self._preview_items(index)
        x, y, width, height = candidate.bbox
        mask.setRect(float(x), float(y), float(width), float(height))
        mask.setVisible(True)

        content = " ".join(
            candidate.text.replace("\r", " ").replace("\n", " ").split()
        )
        face = self._face_for_candidate(candidate)
        text_item.setText(content)
        text_item.setFont(qfont_for_face(face, max(24, int(height * 1.8))))
        text_item.setScale(1.0)
        text_item.setRotation(float(candidate.rotation_deg))
        bounds = text_item.boundingRect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            text_item.setVisible(False)
            return
        scale = max(
            0.01,
            min(
                float(width) * 0.94 / bounds.width(),
                float(height) * 0.90 / bounds.height(),
            ),
        )
        text_item.setScale(scale)
        text_item.setPos(
            float(x) + (float(width) - bounds.width() * scale) * 0.5,
            float(y) + (float(height) - bounds.height() * scale) * 0.5,
        )
        text_item.setVisible(True)

    def _update_all_cad_previews(self) -> None:
        for index in range(len(self._candidates)):
            self._update_candidate_preview(index)

    def _refresh_candidate_style(self, index: int) -> None:
        super()._refresh_candidate_style(index)
        if hasattr(self, "scene_object"):
            self._update_candidate_preview(index)

    def _select_index(self, index: int | None, *, center: bool) -> None:
        if index is not None and 0 <= index < len(self._candidates):
            self._ensure_candidate_font(index)
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
        self._ensure_candidate_font(index)
        candidate = self._candidates[index]
        assert candidate is not None
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

        portability = "内置字体，可在安装本软件的电脑上保持一致" if face.bundled else "本机字体，其他电脑需要另行安装"
        self.confidence_label.setText(
            f"{self.confidence_label.text()}\n"
            f"字体：{face.label}（{face.filename or '系统默认'}）\n"
            f"字形匹配度：{candidate.font_match_score:.1%}\n"
            f"可移植性：{portability}\n"
            "原图上的紫色覆盖文字就是当前 DXF/DWG 字体预览。"
        )
        self._update_candidate_preview(index)

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

    def _preview_visibility_changed(self, checked: bool) -> None:
        self._show_all_cad_previews = bool(checked)
        self._update_all_cad_previews()

    def _install_fonts_again(self) -> None:
        install_bundled_fonts_for_cad.cache_clear()
        self._font_install_report = install_bundled_fonts_for_cad()
        if self.font_status_label is not None:
            self.font_status_label.setText(self._font_install_report.summary())

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
        if index is not None:
            self._update_candidate_preview(index)

    def _delete_current(self) -> None:
        index = self._selected_index
        super()._delete_current()
        if index is not None:
            self._update_candidate_preview(index)
