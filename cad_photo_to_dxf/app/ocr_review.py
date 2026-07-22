from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .auxiliary_recognition import TextCandidate
from .ocr_outline_export import accepted_ocr_texts


_INDEX_ROLE = int(Qt.ItemDataRole.UserRole)


def _image_pixmap(image: np.ndarray) -> QPixmap:
    if image.ndim == 2:
        source = np.ascontiguousarray(image)
        height, width = source.shape
        qimage = QImage(
            source.data,
            width,
            height,
            width,
            QImage.Format.Format_Grayscale8,
        ).copy()
    else:
        if image.shape[2] == 4:
            source = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
            format_value = QImage.Format.Format_RGBA8888
        else:
            source = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            format_value = QImage.Format.Format_RGB888
        source = np.ascontiguousarray(source)
        height, width = source.shape[:2]
        qimage = QImage(
            source.data,
            width,
            height,
            int(source.strides[0]),
            format_value,
        ).copy()
    return QPixmap.fromImage(qimage)


class OcrGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.22 if event.angleDelta().y() > 0 else 1.0 / 1.22
        target = abs(float(self.transform().m11())) * factor
        if 0.02 <= target <= 100.0:
            self.scale(factor, factor)
        event.accept()


class OcrReviewDialog(QDialog):
    """Review OCR lines on the source image before per-character CAD export."""

    def __init__(
        self,
        image: np.ndarray,
        candidates: tuple[TextCandidate, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if image is None or image.size == 0:
            raise ValueError("OCR review requires a non-empty image")
        self.setWindowTitle("检查、预览并确认 OCR 文字")
        self.resize(1500, 900)
        self._candidates: list[TextCandidate | None] = list(candidates)
        self._graphics_items: dict[int, QGraphicsItem] = {}
        self._list_items: dict[int, QListWidgetItem] = {}
        self._selected_index: int | None = None

        root = QVBoxLayout(self)
        explanation = QLabel(
            "每个框代表一个 OCR 文字候选行。右侧修改会立即覆盖预览在原图框内；"
            "确认后导出时，每个汉字、字母和数字分别生成一个可编辑 CAD TEXT。"
            "橙色表示尚未达到自动导出条件，绿色表示已人工确认，紫色表示高置信度自动接受。"
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.scene_object = QGraphicsScene(splitter)
        pixmap_item = QGraphicsPixmapItem(_image_pixmap(image))
        self.scene_object.addItem(pixmap_item)
        self.scene_object.setSceneRect(pixmap_item.boundingRect())
        self.preview_item = self.scene_object.addSimpleText("")
        self.preview_item.setZValue(20.0)
        self.preview_item.setOpacity(0.88)
        self.view = OcrGraphicsView(self.scene_object)
        splitter.addWidget(self.view)

        panel = QWidget(splitter)
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(QLabel("识别文字候选"))
        self.result_list = QListWidget(panel)
        self.result_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        panel_layout.addWidget(self.result_list, 1)
        panel_layout.addWidget(QLabel("当前内容"))
        self.text_edit = QLineEdit(panel)
        panel_layout.addWidget(self.text_edit)
        self.approval_checkbox = QCheckBox(
            "确认作为单字可编辑文字导出",
            panel,
        )
        self.approval_checkbox.setToolTip(
            "勾选后以人工决定覆盖 OCR 置信度；取消后保留原扫描轮廓，不导出该候选文字。"
        )
        panel_layout.addWidget(self.approval_checkbox)
        self.confidence_label = QLabel("尚未选择", panel)
        self.confidence_label.setWordWrap(True)
        panel_layout.addWidget(self.confidence_label)

        note = QLabel(
            "预览使用统一缩放，不会分别拉伸横向和纵向。DXF 不写入本机绝对字体路径；"
            "文字内容和编辑能力可跨机器保留，具体字形由打开文件的 CAD 软件及其可用 Unicode 字体决定。",
            panel,
        )
        note.setWordWrap(True)
        panel_layout.addWidget(note)

        action_row = QHBoxLayout()
        apply_button = QPushButton("应用修改并确认", panel)
        delete_button = QPushButton("删除该文字候选", panel)
        fit_button = QPushButton("适应窗口", panel)
        action_row.addWidget(apply_button)
        action_row.addWidget(delete_button)
        action_row.addWidget(fit_button)
        panel_layout.addLayout(action_row)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        for index, candidate in enumerate(candidates):
            self._add_candidate(index, candidate)

        self.scene_object.selectionChanged.connect(self._scene_selection_changed)
        self.result_list.currentItemChanged.connect(self._list_selection_changed)
        self.text_edit.textChanged.connect(self._text_changed)
        self.text_edit.returnPressed.connect(self._apply_current_text)
        self.approval_checkbox.toggled.connect(self._approval_changed)
        apply_button.clicked.connect(self._apply_current_text)
        delete_button.clicked.connect(self._delete_current)
        fit_button.clicked.connect(self.fit_image)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "保存 OCR 复核结果并返回"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.fit_image()
        if self.result_list.count():
            self.result_list.setCurrentRow(0)

    @staticmethod
    def _candidate_polygon(candidate: TextCandidate) -> QPolygonF:
        if candidate.quad and len(candidate.quad) == 4:
            points = candidate.quad
        else:
            x, y, width, height = candidate.bbox
            points = (
                (float(x), float(y)),
                (float(x + width), float(y)),
                (float(x + width), float(y + height)),
                (float(x), float(y + height)),
            )
        return QPolygonF([QPointF(float(x), float(y)) for x, y in points])

    @staticmethod
    def _status(candidate: TextCandidate) -> tuple[str, QColor, QColor]:
        exported = bool(accepted_ocr_texts((candidate,)))
        if candidate.reviewed and candidate.approved and exported:
            return "已人工确认导出", QColor(0, 160, 70), QColor(0, 160, 70, 24)
        if candidate.reviewed and not candidate.approved:
            return "已人工取消", QColor(120, 120, 120), QColor(120, 120, 120, 16)
        if exported:
            return "高置信度自动接受", QColor(155, 0, 190), QColor(155, 0, 190, 20)
        return "待人工确认，不会自动替换原轮廓", QColor(230, 105, 0), QColor(230, 105, 0, 20)

    def _refresh_candidate_style(self, index: int) -> None:
        if index >= len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        status, pen_color, brush_color = self._status(candidate)
        graphics_item = self._graphics_items.get(index)
        if graphics_item is not None:
            graphics_item.setPen(QPen(pen_color, 2.0))
            graphics_item.setBrush(brush_color)
        list_item = self._list_items.get(index)
        if list_item is not None:
            list_item.setText(candidate.text or "（空白）")
            list_item.setToolTip(
                f"{status}；置信度 {candidate.confidence:.1%}；"
                f"来源 {candidate.source or 'unknown'}"
            )

    def _add_candidate(self, index: int, candidate: TextCandidate) -> None:
        graphics_item = self.scene_object.addPolygon(
            self._candidate_polygon(candidate),
            QPen(QColor(230, 105, 0), 2.0),
        )
        graphics_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        graphics_item.setData(0, index)
        graphics_item.setZValue(10.0)
        self._graphics_items[index] = graphics_item

        list_item = QListWidgetItem(candidate.text)
        list_item.setData(_INDEX_ROLE, index)
        self.result_list.addItem(list_item)
        self._list_items[index] = list_item
        self._refresh_candidate_style(index)

    def _select_index(self, index: int | None, *, center: bool) -> None:
        if index is None or index >= len(self._candidates):
            self._selected_index = None
            self.text_edit.clear()
            self.confidence_label.setText("尚未选择")
            self.preview_item.setText("")
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        self._selected_index = index
        self.text_edit.blockSignals(True)
        self.text_edit.setText(candidate.text)
        self.text_edit.blockSignals(False)
        self._refresh_selected_state()

        graphics_item = self._graphics_items.get(index)
        if graphics_item is not None:
            for item in self.scene_object.selectedItems():
                if item is not graphics_item:
                    item.setSelected(False)
            graphics_item.setSelected(True)
            if center:
                self.view.centerOn(graphics_item)
        list_item = self._list_items.get(index)
        if list_item is not None and self.result_list.currentItem() is not list_item:
            self.result_list.blockSignals(True)
            self.result_list.setCurrentItem(list_item)
            self.result_list.blockSignals(False)

    def _refresh_selected_state(self) -> None:
        index = self._selected_index
        if index is None or index >= len(self._candidates):
            self.preview_item.setText("")
            return
        candidate = self._candidates[index]
        if candidate is None:
            self.preview_item.setText("")
            return

        exported = bool(accepted_ocr_texts((candidate,)))
        status, pen_color, _brush_color = self._status(candidate)
        self.approval_checkbox.blockSignals(True)
        self.approval_checkbox.setChecked(exported)
        self.approval_checkbox.blockSignals(False)
        self.confidence_label.setText(
            f"状态：{status}\n"
            f"置信度：{candidate.confidence:.1%}\n"
            f"来源：{candidate.source or 'unknown'}\n"
            "人工修改或勾选确认后，原始置信度不再阻止导出。"
        )

        content = self.text_edit.text()
        self.preview_item.setText(content)
        self.preview_item.setBrush(pen_color)
        x, y, width, height = candidate.bbox
        font = QFont("Sans Serif")
        font.setPixelSize(max(8, int(height * 0.82)))
        self.preview_item.setFont(font)
        self.preview_item.setScale(1.0)
        bounds = self.preview_item.boundingRect()
        if not content or bounds.width() <= 0 or bounds.height() <= 0:
            return
        scale = max(
            0.02,
            min(float(width) / bounds.width(), float(height) / bounds.height()),
        )
        self.preview_item.setScale(scale)
        self.preview_item.setPos(
            float(x) + (float(width) - bounds.width() * scale) * 0.5,
            float(y) + (float(height) - bounds.height() * scale) * 0.5,
        )

    def _scene_selection_changed(self) -> None:
        selected = self.scene_object.selectedItems()
        if not selected:
            return
        value = selected[0].data(0)
        if value is not None:
            self._select_index(int(value), center=False)

    def _list_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        self._select_index(int(current.data(_INDEX_ROLE)), center=True)

    def _text_changed(self, text: str) -> None:
        index = self._selected_index
        if index is None or self._candidates[index] is None:
            return
        candidate = self._candidates[index]
        assert candidate is not None
        self._candidates[index] = replace(
            candidate,
            text=text,
            approved=bool(text.strip()),
            reviewed=True,
        )
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _approval_changed(self, checked: bool) -> None:
        index = self._selected_index
        if index is None or self._candidates[index] is None:
            return
        candidate = self._candidates[index]
        assert candidate is not None
        self._candidates[index] = replace(
            candidate,
            approved=bool(checked),
            reviewed=True,
        )
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _apply_current_text(self) -> None:
        index = self._selected_index
        if index is None or self._candidates[index] is None:
            return
        text = self.text_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "文字为空", "内容为空时请使用“删除该文字候选”。")
            return
        candidate = self._candidates[index]
        assert candidate is not None
        self._candidates[index] = replace(
            candidate,
            text=text,
            approved=True,
            reviewed=True,
        )
        self.text_edit.blockSignals(True)
        self.text_edit.setText(text)
        self.text_edit.blockSignals(False)
        self._refresh_candidate_style(index)
        self._refresh_selected_state()

    def _delete_current(self) -> None:
        index = self._selected_index
        if index is None or self._candidates[index] is None:
            return
        self._candidates[index] = None
        graphics_item = self._graphics_items.pop(index, None)
        if graphics_item is not None:
            self.scene_object.removeItem(graphics_item)
        list_item = self._list_items.pop(index, None)
        if list_item is not None:
            row = self.result_list.row(list_item)
            self.result_list.takeItem(row)
        self._selected_index = None
        self.text_edit.clear()
        self.preview_item.setText("")
        self.confidence_label.setText(
            "该 OCR 候选已删除；导出时不会抑制其原始扫描轮廓。"
        )

    def fit_image(self) -> None:
        self.view.fitInView(self.scene_object.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def accept(self) -> None:  # type: ignore[override]
        if self._selected_index is not None and self.text_edit.text().strip():
            self._apply_current_text()
        super().accept()

    def reviewed_texts(self) -> tuple[TextCandidate, ...]:
        return tuple(item for item in self._candidates if item is not None)
