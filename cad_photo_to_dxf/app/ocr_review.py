from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    """Visually review OCR boxes and edit the text exported to CAD."""

    def __init__(
        self,
        image: np.ndarray,
        candidates: tuple[TextCandidate, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if image is None or image.size == 0:
            raise ValueError("OCR review requires a non-empty image")
        self.setWindowTitle("检查并修改 OCR 文字")
        self.resize(1500, 900)
        self._candidates: list[TextCandidate | None] = list(candidates)
        self._graphics_items: dict[int, QGraphicsItem] = {}
        self._list_items: dict[int, QListWidgetItem] = {}
        self._selected_index: int | None = None

        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "绿色框是将导出为 CAD TEXT 的识别结果。"
                "点击图中的框或右侧文字即可修改；删除只取消该 OCR 文字，"
                "原扫描轮廓仍保存在默认关闭的回退图层中。"
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.scene_object = QGraphicsScene(splitter)
        pixmap_item = QGraphicsPixmapItem(_image_pixmap(image))
        self.scene_object.addItem(pixmap_item)
        self.scene_object.setSceneRect(pixmap_item.boundingRect())
        self.view = OcrGraphicsView(self.scene_object)
        splitter.addWidget(self.view)

        panel = QWidget(splitter)
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(QLabel("识别文字"))
        self.result_list = QListWidget(panel)
        self.result_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        panel_layout.addWidget(self.result_list, 1)
        panel_layout.addWidget(QLabel("当前内容"))
        self.text_edit = QLineEdit(panel)
        panel_layout.addWidget(self.text_edit)
        self.confidence_label = QLabel("尚未选择", panel)
        self.confidence_label.setWordWrap(True)
        panel_layout.addWidget(self.confidence_label)

        action_row = QHBoxLayout()
        apply_button = QPushButton("应用修改", panel)
        delete_button = QPushButton("删除该 OCR 文字", panel)
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
        self.text_edit.returnPressed.connect(self._apply_current_text)
        apply_button.clicked.connect(self._apply_current_text)
        delete_button.clicked.connect(self._delete_current)
        fit_button.clicked.connect(self.fit_image)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "保存 OCR 文字并返回"
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

    def _add_candidate(self, index: int, candidate: TextCandidate) -> None:
        graphics_item = self.scene_object.addPolygon(
            self._candidate_polygon(candidate),
            QPen(QColor(0, 190, 0), 2.0),
        )
        graphics_item.setBrush(QColor(0, 190, 0, 18))
        graphics_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        graphics_item.setData(0, index)
        graphics_item.setZValue(10.0)
        self._graphics_items[index] = graphics_item

        list_item = QListWidgetItem(candidate.text)
        list_item.setData(_INDEX_ROLE, index)
        list_item.setToolTip(
            f"置信度 {candidate.confidence:.1%}；来源 {candidate.source or 'unknown'}"
        )
        self.result_list.addItem(list_item)
        self._list_items[index] = list_item

    def _select_index(self, index: int | None, *, center: bool) -> None:
        if index is None or index >= len(self._candidates):
            self._selected_index = None
            self.text_edit.clear()
            self.confidence_label.setText("尚未选择")
            return
        candidate = self._candidates[index]
        if candidate is None:
            return
        self._selected_index = index
        self.text_edit.setText(candidate.text)
        self.confidence_label.setText(
            f"置信度：{candidate.confidence:.1%}\n"
            f"来源：{candidate.source or 'unknown'}\n"
            "此处修改的是可编辑 CAD 文字内容，不会改变扫描轮廓坐标。"
        )
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

    def _scene_selection_changed(self) -> None:
        selected = self.scene_object.selectedItems()
        if not selected:
            return
        value = selected[0].data(0)
        self._select_index(int(value), center=False)

    def _list_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        self._select_index(int(current.data(_INDEX_ROLE)), center=True)

    def _apply_current_text(self) -> None:
        index = self._selected_index
        if index is None or self._candidates[index] is None:
            return
        text = self.text_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "文字为空", "内容为空时请使用“删除该 OCR 文字”。")
            return
        updated = replace(self._candidates[index], text=text)
        self._candidates[index] = updated
        list_item = self._list_items.get(index)
        if list_item is not None:
            list_item.setText(text)
        self.statusTip()

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
        self.confidence_label.setText("该 OCR 文字已删除")

    def fit_image(self) -> None:
        self.view.fitInView(self.scene_object.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def accept(self) -> None:  # type: ignore[override]
        self._apply_current_text()
        super().accept()

    def reviewed_texts(self) -> tuple[TextCandidate, ...]:
        return tuple(item for item in self._candidates if item is not None)
