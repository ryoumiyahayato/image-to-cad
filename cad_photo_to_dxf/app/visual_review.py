from __future__ import annotations

from math import hypot

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .auxiliary_recognition import CircleCandidate, TextCandidate
from .layer_classifier import LAYERS
from .line_detect import LineSegment

COLORS = {
    "OUTLINE": QColor(220, 30, 30),
    "WALL_OR_FRAME": QColor(0, 150, 0),
    "GRID_OR_AXIS": QColor(40, 90, 220),
    "HATCH": QColor(180, 0, 180),
    "HATCH_CANDIDATE": QColor(210, 130, 0),
    "DETAIL": QColor(0, 150, 190),
}


def _pixmap(image: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(
        image, cv2.COLOR_GRAY2RGB if image.ndim == 2 else cv2.COLOR_BGR2RGB
    )
    rgb = np.ascontiguousarray(rgb)
    height, width, channels = rgb.shape
    qimage = QImage(
        rgb.data,
        width,
        height,
        channels * width,
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(qimage)


class _Handle(QGraphicsEllipseItem):
    def __init__(self, owner: QGraphicsItem, role: int) -> None:
        super().__init__(-4, -4, 8, 8, owner)
        self.owner = owner
        self.role = role
        self.setBrush(QBrush(Qt.GlobalColor.white))
        self.setPen(QPen(Qt.GlobalColor.black, 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(20)

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            callback = getattr(self.owner, "handle_moved", None)
            if callback is not None and not getattr(self.owner, "_syncing", False):
                callback(self.role, QPointF(value))
        return super().itemChange(change, value)


class EditableLine(QGraphicsLineItem):
    def __init__(self, source: LineSegment) -> None:
        super().__init__(source.x1, source.y1, source.x2, source.y2)
        self.source = source
        self.layer = source.layer if source.layer in LAYERS else "DETAIL"
        self._syncing = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setZValue(3)
        self.handles = (_Handle(self, 0), _Handle(self, 1))
        self._sync_handles()
        self._show_handles(False)
        self._update_pen()

    def _update_pen(self) -> None:
        pen = QPen(COLORS.get(self.layer, COLORS["DETAIL"]), 1.4)
        pen.setCosmetic(True)
        self.setPen(pen)

    def _sync_handles(self) -> None:
        self._syncing = True
        self.handles[0].setPos(self.line().p1())
        self.handles[1].setPos(self.line().p2())
        self._syncing = False

    def _show_handles(self, visible: bool) -> None:
        for handle in self.handles:
            handle.setVisible(visible)

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._show_handles(bool(value))
        return super().itemChange(change, value)

    def handle_moved(self, role: int, point: QPointF) -> None:
        line = self.line()
        line.setP1(point) if role == 0 else line.setP2(point)
        self.setLine(line)

    def set_layer(self, layer: str) -> None:
        if layer in LAYERS:
            self.layer = layer
            self._update_pen()

    def result(self) -> LineSegment:
        line, offset = self.line(), self.pos()
        values = (
            line.x1() + offset.x(),
            line.y1() + offset.y(),
            line.x2() + offset.x(),
            line.y2() + offset.y(),
        )
        changed = self.layer != self.source.layer or values != (
            self.source.x1,
            self.source.y1,
            self.source.x2,
            self.source.y2,
        )
        return self.source.copy(
            x1=float(values[0]),
            y1=float(values[1]),
            x2=float(values[2]),
            y2=float(values[3]),
            layer=self.layer,
            history=tuple(
                dict.fromkeys(
                    self.source.history
                    + (("visual_geometry_review",) if changed else ())
                )
            ),
            classification_confidence=(
                1.0 if changed else self.source.classification_confidence
            ),
            classification_reasons=tuple(
                dict.fromkeys(
                    self.source.classification_reasons
                    + (("manual_visual_edit",) if changed else ())
                )
            ),
        )


class EditableCircle(QGraphicsEllipseItem):
    def __init__(self, source: CircleCandidate) -> None:
        self.source = source
        self._syncing = False
        x, y = source.center
        radius = max(1.0, float(source.radius))
        super().__init__(x - radius, y - radius, radius * 2, radius * 2)
        pen = QPen(QColor(0, 170, 255), 1.4)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setZValue(4)
        self.handle = _Handle(self, 0)
        self._sync_handle()
        self.handle.setVisible(False)

    def _sync_handle(self) -> None:
        self._syncing = True
        rect = self.rect()
        self.handle.setPos(rect.right(), rect.center().y())
        self._syncing = False

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.handle.setVisible(bool(value))
        return super().itemChange(change, value)

    def handle_moved(self, _role: int, point: QPointF) -> None:
        center = self.rect().center()
        radius = max(1.0, hypot(point.x() - center.x(), point.y() - center.y()))
        self.setRect(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        self._sync_handle()

    def result(self) -> CircleCandidate:
        center = self.rect().center() + self.pos()
        return CircleCandidate(
            (float(center.x()), float(center.y())), self.rect().width() / 2, 1.0
        )


class EditableText(QGraphicsSimpleTextItem):
    def __init__(self, source: TextCandidate) -> None:
        super().__init__(source.text)
        self.source = source
        x, y, _width, height = source.bbox
        font = QFont()
        font.setPixelSize(max(6, int(height * 0.9)))
        self.setFont(font)
        self.setBrush(QBrush(QColor(210, 40, 180)))
        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setZValue(5)

    def result(self) -> TextCandidate:
        rect, point = self.boundingRect(), self.pos()
        return TextCandidate(
            self.text().strip(),
            (
                int(point.x()),
                int(point.y()),
                max(1, int(rect.width())),
                max(1, int(rect.height())),
            ),
            1.0,
            self.source.kind,
        )


class ReviewView(QGraphicsView):
    create_clicked = Signal(float, float)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.mode = "select"
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.22 if event.angleDelta().y() > 0 else 1 / 1.22
        target = abs(self.transform().m11()) * factor
        if 0.01 <= target <= 100:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.mode != "select" and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            self.create_clicked.emit(point.x(), point.y())
            event.accept()
            return
        super().mousePressEvent(event)


class VectorReviewDialog(QDialog):
    def __init__(
        self,
        image: np.ndarray,
        lines: list[LineSegment] | tuple[LineSegment, ...],
        circles: list[CircleCandidate] | tuple[CircleCandidate, ...] = (),
        texts: list[TextCandidate] | tuple[TextCandidate, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if image is None or image.size == 0:
            raise ValueError("Visual review requires a non-empty image")
        self.setWindowTitle("可视化编辑识别结果")
        self.resize(1400, 900)
        self.scene = QGraphicsScene(self)
        self.underlay = QGraphicsPixmapItem(_pixmap(image))
        self.underlay.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.underlay)
        self.scene.setSceneRect(self.underlay.boundingRect())
        self._line_items = [EditableLine(line) for line in lines]
        self._circle_items = [EditableCircle(circle) for circle in circles]
        self._text_items = [EditableText(text) for text in texts]
        for item in (*self._line_items, *self._circle_items, *self._text_items):
            self.scene.addItem(item)
        self.pending: QPointF | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("直接拖动实体、线端点和圆半径；框选后可批量删除。滚轮缩放。")
        )
        splitter = QSplitter(self)
        self.view = ReviewView(self.scene)
        self.view.create_clicked.connect(self._create)
        splitter.addWidget(self.view)
        splitter.addWidget(self._panel())
        splitter.setStretchFactor(0, 1)
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存可视化修改")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.scene.selectionChanged.connect(self._selection_changed)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        for label, mode in (
            ("选择", "select"),
            ("加线", "line"),
            ("加圆", "circle"),
            ("加文字", "text"),
        ):
            button = QPushButton(label, panel)
            button.clicked.connect(
                lambda _checked=False, value=mode: self._set_mode(value)
            )
            row.addWidget(button)
        layout.addLayout(row)
        delete = QPushButton("删除所选实体", panel)
        delete.clicked.connect(self._delete)
        layout.addWidget(delete)
        self.selection_label = QLabel("未选择实体", panel)
        layout.addWidget(self.selection_label)
        form = QFormLayout()
        self.layer_combo = QComboBox(panel)
        self.layer_combo.addItems(LAYERS)
        self.layer_combo.currentTextChanged.connect(self._layer_changed)
        form.addRow("线图层", self.layer_combo)
        self.text_edit = QLineEdit(panel)
        self.text_edit.editingFinished.connect(self._text_changed)
        form.addRow("文字内容", self.text_edit)
        layout.addLayout(form)
        opacity = QSlider(Qt.Orientation.Horizontal, panel)
        opacity.setRange(0, 100)
        opacity.setValue(100)
        opacity.valueChanged.connect(
            lambda value: self.underlay.setOpacity(value / 100)
        )
        layout.addWidget(QLabel("扫描底图透明度"))
        layout.addWidget(opacity)
        fit = QPushButton("适应窗口", panel)
        fit.clicked.connect(
            lambda: self.view.fitInView(
                self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        )
        layout.addWidget(fit)
        layout.addStretch(1)
        return panel

    def _set_mode(self, mode: str) -> None:
        self.pending = None
        self.view.mode = mode
        self.view.setDragMode(
            QGraphicsView.DragMode.RubberBandDrag
            if mode == "select"
            else QGraphicsView.DragMode.NoDrag
        )

    def _create(self, x: float, y: float) -> None:
        if self.view.mode == "text":
            value, accepted = QInputDialog.getText(self, "新增文字", "文字内容：")
            if accepted and value.strip():
                item = EditableText(
                    TextCandidate(
                        value.strip(),
                        (int(x), int(y), max(20, len(value) * 12), 18),
                        1.0,
                        "manual_text",
                    )
                )
                self.scene.addItem(item)
                self._text_items.append(item)
            return
        point = QPointF(x, y)
        if self.pending is None:
            self.pending = point
            return
        first, self.pending = self.pending, None
        distance = hypot(point.x() - first.x(), point.y() - first.y())
        if distance < 1:
            return
        if self.view.mode == "line":
            item = EditableLine(
                LineSegment(
                    first.x(),
                    first.y(),
                    point.x(),
                    point.y(),
                    layer="DETAIL",
                    history=("manual_visual_add",),
                    classification_reasons=("manual_visual_add",),
                )
            )
            self._line_items.append(item)
        else:
            item = EditableCircle(
                CircleCandidate((first.x(), first.y()), distance, 1.0)
            )
            self._circle_items.append(item)
        self.scene.addItem(item)

    def _selected(self):
        return [
            item
            for item in self.scene.selectedItems()
            if isinstance(item, (EditableLine, EditableCircle, EditableText))
        ]

    def _selection_changed(self) -> None:
        items = self._selected()
        self.layer_combo.setEnabled(
            len(items) == 1 and isinstance(items[0], EditableLine) if items else False
        )
        self.text_edit.setEnabled(
            len(items) == 1 and isinstance(items[0], EditableText) if items else False
        )
        self.selection_label.setText(
            f"已选择 {len(items)} 个实体" if items else "未选择实体"
        )
        if len(items) == 1 and isinstance(items[0], EditableLine):
            self.layer_combo.setCurrentText(items[0].layer)
        if len(items) == 1 and isinstance(items[0], EditableText):
            self.text_edit.setText(items[0].text())
        elif not items or not isinstance(items[0], EditableText):
            self.text_edit.clear()

    def _layer_changed(self, layer: str) -> None:
        for item in self._selected():
            if isinstance(item, EditableLine):
                item.set_layer(layer)

    def _text_changed(self) -> None:
        value = self.text_edit.text().strip()
        for item in self._selected():
            if value and isinstance(item, EditableText):
                item.setText(value)

    def _delete(self) -> None:
        for item in self._selected():
            self.scene.removeItem(item)
            collection = (
                self._line_items
                if isinstance(item, EditableLine)
                else self._circle_items
                if isinstance(item, EditableCircle)
                else self._text_items
            )
            collection.remove(item)

    def reviewed_entities(
        self,
    ) -> tuple[list[LineSegment], list[CircleCandidate], list[TextCandidate]]:
        lines: list[LineSegment] = []
        for item in self._line_items:
            line = item.result()
            if line.length > 1e-9:
                lines.append(line)
        circles = [item.result() for item in self._circle_items]
        texts = [item.result() for item in self._text_items if item.text().strip()]
        return lines, circles, texts
