"""Source-overlay review with separate content and source-layout confirmation."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPen, QTransform, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
    QScrollArea,
)

from app.core.review_project import ConfirmationEvent, ReviewProjectError
from app.gui.ocr_review import OcrReviewDialog
from app.ocr.librecad_lff import librecad_text_path
from app.ocr.font_library import default_font_face, qfont_for_face
from app.ocr.text_output_contract import accepted_ocr_texts


class SnapshotTextReviewDialog(OcrReviewDialog):
    def __init__(self, project, parent=None, *, test_only=False):
        self.project = project.draft()
        self.test_only = (
            test_only or "TEST_ONLY" in project.manifest.get("origin", "").upper()
        )
        self._uuid_by_index = {
            b["index"]: b["text_source_uuid"] for b in project.bindings
        }
        self._native_items = {}
        self._source_region_item = None
        self._layout_preview_item = None
        self._layout_preview_for = None
        super().__init__(project.frame, project.baseline.texts, parent)
        self.setFont(qfont_for_face(default_font_face("文字校对"), 14))
        self.setWindowTitle(
            "校对同一转换快照的文字" + (" · QA_TEST_ONLY" if self.test_only else "")
        )
        self.approval_checkbox.hide()
        # Replace legacy fit-to-box and deletion instructions; no new CAD editor.
        for label in self.findChildren(QLabel):
            if "每个框代表" in label.text():
                label.setText(
                    "输入或复制PDF建议不会修改TEXT。先确认文字修订；需要源区域布局时，再预览并单独确认显示区域。待布局建议不进入DXF。返回后仍需保存项目。"
                )
            elif "预览使用统一缩放" in label.text():
                label.setText(
                    "紫色字形使用正式LFF度量及原TEXT几何。待布局建议不进入正式输出。"
                )
        for button in self.findChildren(QPushButton):
            if button.text() == "应用修改并确认":
                button.setText("确认修订")
            elif button.text() == "删除该文字候选":
                button.setText("保留原文 / 撤回修订")
        panel = self.text_edit.parentWidget()
        cancel_input = QPushButton("取消当前输入", panel)
        cancel_input.clicked.connect(self._reset_input)
        panel.layout().addWidget(cancel_input)
        self.suggestion_label = QLabel(panel)
        self.suggestion_label.setWordWrap(True)
        panel.layout().addWidget(self.suggestion_label)
        self.use_suggestion_button = QPushButton(
            "使用PDF建议作为输入（尚未确认）", panel
        )
        self.use_suggestion_button.clicked.connect(self._use_suggestion)
        panel.layout().addWidget(self.use_suggestion_button)
        self.preview_layout_button = QPushButton("预览源显示区域", panel)
        self.preview_layout_button.clicked.connect(self._preview_source_layout)
        panel.layout().addWidget(self.preview_layout_button)
        self.confirm_layout_button = QPushButton("确认使用源显示区域", panel)
        self.confirm_layout_button.clicked.connect(self._confirm_source_layout)
        self.confirm_layout_button.setEnabled(False)
        panel.layout().addWidget(self.confirm_layout_button)
        self.layout_label = QLabel("", panel)
        self.layout_label.setWordWrap(True)
        panel.layout().addWidget(self.layout_label)
        # The existing source overlay stays visible while long evidence and
        # UUID labels scroll in the narrow review panel.
        splitter = panel.parentWidget()
        scroll = QScrollArea(splitter)
        splitter.replaceWidget(1, scroll)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(500)
        scroll.setWidget(panel)
        self.result_list.setMinimumHeight(150)
        self.result_list.setMaximumHeight(240)
        for box in self.findChildren(QDialogButtonBox):
            box.button(QDialogButtonBox.StandardButton.Save).setText(
                "应用到会话（随后保存项目）"
            )
        for index in range(len(self._candidates)):
            self._refresh_native(index)
        self._refresh_selected_state()

    def _text_changed(self, _text):
        # Typing is a proposal, never an implicit human confirmation event.
        self._clear_layout_preview()
        self._refresh_selected_state()

    def _clear_layout_preview(self):
        self._layout_preview_for = None
        if getattr(self, "_layout_preview_item", None) is not None:
            self._layout_preview_item.hide()
        if hasattr(self, "confirm_layout_button"):
            self.confirm_layout_button.setEnabled(False)
            self.layout_label.clear()

    def _use_suggestion(self):
        if self._selected_index is not None:
            suggestion = self.project.suggestion(
                self._uuid_by_index[self._selected_index]
            )
            if suggestion:
                self.text_edit.setText(suggestion["evidence"]["text"])

    def _preview_source_layout(self):
        if self._selected_index is None:
            return
        text_uuid = self._uuid_by_index[self._selected_index]
        record = self.project.latest(text_uuid)
        if not record or self.text_edit.text() != record["new_text"]:
            self.layout_label.setText("请先明确确认当前输入的文字内容。")
            return
        try:
            result = self.project.preview_source_layout(text_uuid)
        except ReviewProjectError as exc:
            self.layout_label.setText(str(exc))
            return
        safe = result["state"] == "PASS"
        self.layout_label.setText(
            (
                "布局检查通过。预览尚未应用；点击确认后才修改正式TEXT。"
                if safe
                else "需要布局复核，正式TEXT保持原状。"
            )
            + "\n"
            + result["reason"]
            + (
                f"\n保留同一源文字的 {result.get('preserved_source_footprints', 0)} 个已有轮廓；不删除源图。"
                if safe
                else ""
            )
        )
        self._layout_preview_for = (text_uuid, record["revision"]) if safe else None
        self.confirm_layout_button.setEnabled(
            safe and record["action"] == "CONFIRM_STRING"
        )
        if safe:
            from app.export.review_text import source_anchored_text_placement

            placement = source_anchored_text_placement(
                self.project.baseline.texts[self._selected_index],
                record["new_text"],
                result["source_quad"],
                transform=self.project.guard.transform,
            )
            path = self._placement_path(placement)
            if self._layout_preview_item is None:
                self._layout_preview_item = self.scene_object.addPath(
                    path, QPen(QColor(0, 150, 60), 0.6)
                )
                self._layout_preview_item.setZValue(18)
            else:
                self._layout_preview_item.setPath(path)
            self._layout_preview_item.show()

    def _confirm_source_layout(self):
        if self._selected_index is None:
            return
        text_uuid = self._uuid_by_index[self._selected_index]
        previous = self.project.latest(text_uuid)
        if (
            not previous
            or self._layout_preview_for != (text_uuid, previous["revision"])
            or self.text_edit.text() != previous["new_text"]
        ):
            return
        try:
            self.project.confirm_source_layout(
                text_uuid, event=ConfirmationEvent.create(test_only=self.test_only)
            )
        except ReviewProjectError as exc:
            QMessageBox.warning(self, "源区域布局未应用", str(exc))
            return
        self._clear_layout_preview()
        self._refresh_native(self._selected_index)
        self._refresh_selected_state()

    def _approval_changed(self, _checked):
        pass

    def _reset_input(self):
        if self._selected_index is not None:
            self.text_edit.setText(
                self.project.current_text(self._uuid_by_index[self._selected_index])
            )

    def _refresh_selected_state(self):
        index = self._selected_index
        if index is None:
            return
        candidate = self.project.baseline.texts[index]
        text_uuid = self._uuid_by_index[index]
        current = self.project.current_text(text_uuid)
        record = self.project.latest(text_uuid)
        editable = bool(accepted_ocr_texts((candidate,)))
        self.text_edit.setEnabled(editable)
        state = record["status"] if record else "OCR_UNVERIFIED"
        held = bool(record and record["consumption"] == "HELD")
        source_layout = self.project.current_source_layout(text_uuid)
        layout_state = (
            f"已确认源显示区域：{source_layout['source_quad']}"
            if source_layout
            else "显示区域：原TEXT几何；尚未批准源区域调整"
        )
        proposal = ""
        if held:
            reason = record["layout_check"]["reason"]
            if reason == "New glyph bounds exceed the original legal display quad":
                reason = "新文字超出原TEXT合法显示范围。"
            proposal = (
                "\n待布局建议（已确认，未应用）："
                + record["new_text"]
                + "\n原因："
                + reason
                + "\n当前TEXT保留上次安全结果；需要人工处理布局。"
            )
        input_state = ""
        if self.text_edit.text() != current:
            input_state = (
                "\n该建议已确认，尚未应用。"
                if held and self.text_edit.text() == record["new_text"]
                else "\n输入尚未确认"
            )
        self.confidence_label.setText(
            f"原始OCR：{candidate.text}\n当前TEXT：{current}\n状态：{state}"
            f"\nTEXT UUID：{text_uuid}\n物理页：{self.project.manifest['source']['physical_page']}"
            f"\n原OCR区域：{candidate.bbox}\n{layout_state}\n源替换资格：{candidate.replacement_safe}"
            f"\n项目：{'有未保存修订' if self.project.dirty else '未增加修订'}"
            + proposal
            + input_state
            + ("\n该候选不是已有原生TEXT，不能在本项目中校对。" if not editable else "")
        )
        self.preview_item.setVisible(False)
        if hasattr(self, "suggestion_label"):
            suggestion = self.project.suggestion(text_uuid)
            self.use_suggestion_button.setEnabled(bool(suggestion))
            self.preview_layout_button.setEnabled(
                bool(suggestion and record and record["action"] != "WITHDRAW")
            )
            self.suggestion_label.setText(
                "PDF提取建议（NATIVE_SUGGESTED）：\n"
                + suggestion["evidence"]["text"]
                + "\n该建议由PDF文字层提取，字符映射尚未独立验证，请对照原图确认。"
                + f"\n蓝框为PDF源范围：{suggestion['evidence']['bounds']}"
                if suggestion
                else "没有可唯一绑定且完成可见性检查的PDF建议。保留原OCR流程。"
            )
            if self._source_region_item is not None:
                self._source_region_item.hide()
            if suggestion:
                points = QPolygonF(
                    [QPointF(*p) for p in suggestion["evidence"]["quad"]]
                )
                if self._source_region_item is None:
                    self._source_region_item = self.scene_object.addPolygon(
                        points, QPen(QColor(0, 100, 240), 0.7)
                    )
                    self._source_region_item.setZValue(16)
                else:
                    self._source_region_item.setPolygon(points)
                self._source_region_item.show()

    def _select_index(self, index, *, center=True):
        self._clear_layout_preview()
        super()._select_index(index, center=center)
        if index in self._uuid_by_index:
            self._reset_input()

    def _apply_current_text(self):
        if self._selected_index is None:
            return
        try:
            record = self.project.confirm(
                self._uuid_by_index[self._selected_index],
                self.text_edit.text(),
                event=ConfirmationEvent.create(test_only=self.test_only),
            )
        except ReviewProjectError as exc:
            QMessageBox.warning(self, "校对未应用", str(exc))
            return
        if record is not None:
            self._refresh_native(self._selected_index)
        self._refresh_selected_state()

    def _delete_current(self):
        if self._selected_index is None:
            return
        try:
            self.project.confirm(
                self._uuid_by_index[self._selected_index],
                "",
                event=ConfirmationEvent.create(test_only=self.test_only),
                withdraw=True,
            )
        except ReviewProjectError as exc:
            QMessageBox.warning(self, "撤回未应用", str(exc))
            return
        self._reset_input()
        self._refresh_native(self._selected_index)
        self._refresh_selected_state()

    def _refresh_native(self, index):
        candidate = self.project.baseline.texts[index]
        if not accepted_ocr_texts((candidate,)):
            return

        def transform(x, y):
            return float(x), self.project.baseline.source_size_px[1] - float(y)

        placement = self.project.current_placement(
            self._uuid_by_index[index], transform=transform
        )
        if placement is None:
            return
        path = self._placement_path(placement)
        item = self._native_items.get(index)
        if item is None:
            item = self.scene_object.addPath(path, QPen(QColor(200, 0, 170), 0.6))
            item.setZValue(15)
            self._native_items[index] = item
        else:
            item.setPath(path)

    def _placement_path(self, placement):
        g, m = placement.geometry, placement.metrics
        matrix = QTransform()
        matrix.translate(
            g.insert[0], self.project.baseline.source_size_px[1] - g.insert[1]
        )
        matrix.rotate(-g.rotation)
        matrix.scale(
            g.character_height / m.em_height * g.width_factor,
            g.character_height / m.em_height,
        )
        return matrix.map(librecad_text_path(placement.content))

    def accept(self):
        # Accepting the dialog does not confirm unsubmitted input.
        QDialog.accept(self)
