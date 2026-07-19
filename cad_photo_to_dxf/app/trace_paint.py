from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)


@dataclass(frozen=True)
class PaintStroke:
    start: tuple[float, float]
    end: tuple[float, float]
    value: int
    width: int


def _binary_pixmap(binary: np.ndarray) -> QPixmap:
    image = np.ascontiguousarray(binary)
    height, width = image.shape
    qimage = QImage(
        image.data,
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    ).copy()
    return QPixmap.fromImage(qimage)


class PaintView(QGraphicsView):
    def __init__(self, binary: np.ndarray) -> None:
        self.scene_object = QGraphicsScene()
        super().__init__(self.scene_object)
        self.binary = np.ascontiguousarray(binary.copy())
        self.pixmap_item = QGraphicsPixmapItem(_binary_pixmap(self.binary))
        self.scene_object.addItem(self.pixmap_item)
        self.scene_object.setSceneRect(self.pixmap_item.boundingRect())
        self.strokes: list[tuple[PaintStroke, QGraphicsLineItem]] = []
        self.paint_value = 0
        self.brush_width = 3
        self.last_point: QPointF | None = None
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def set_paint_value(self, value: int) -> None:
        self.paint_value = 0 if value < 128 else 255

    def set_brush_width(self, width: int) -> None:
        self.brush_width = max(1, int(width))

    def _append_segment(self, start: QPointF, end: QPointF) -> None:
        color = QColor(0, 0, 0) if self.paint_value == 0 else QColor(255, 255, 255)
        pen = QPen(color, float(self.brush_width))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        item = self.scene_object.addLine(
            start.x(),
            start.y(),
            end.x(),
            end.y(),
            pen,
        )
        item.setZValue(5.0)
        stroke = PaintStroke(
            (float(start.x()), float(start.y())),
            (float(end.x()), float(end.y())),
            self.paint_value,
            self.brush_width,
        )
        self.strokes.append((stroke, item))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self.last_point = point
                self._append_segment(point, point)
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.last_point is not None and event.buttons() & Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self._append_segment(self.last_point, point)
                self.last_point = point
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_point = None
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.22 if event.angleDelta().y() > 0 else 1.0 / 1.22
        target = abs(float(self.transform().m11())) * factor
        if 0.02 <= target <= 100.0:
            self.scale(factor, factor)
        event.accept()

    def undo(self) -> None:
        if not self.strokes:
            return
        _stroke, item = self.strokes.pop()
        self.scene_object.removeItem(item)

    def clear_edits(self) -> None:
        for _stroke, item in self.strokes:
            self.scene_object.removeItem(item)
        self.strokes.clear()

    def fit_image(self) -> None:
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def edited_binary(self) -> np.ndarray:
        result = self.binary.copy()
        for stroke, _item in self.strokes:
            cv2.line(
                result,
                (int(round(stroke.start[0])), int(round(stroke.start[1]))),
                (int(round(stroke.end[0])), int(round(stroke.end[1]))),
                int(stroke.value),
                thickness=int(stroke.width),
                lineType=cv2.LINE_8,
            )
        return result


class TracePaintDialog(QDialog):
    """Repair the literal black/white source before vector boundaries are rebuilt."""

    def __init__(self, binary: np.ndarray, parent=None) -> None:
        super().__init__(parent)
        if binary is None or binary.size == 0 or binary.ndim != 2:
            raise ValueError("Trace repair requires a non-empty black/white image")
        self.setWindowTitle("修补黑白拓印图")
        self.resize(1400, 900)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "黑色画笔补线，白色画笔擦除。这里修改的是最终拓印源图，保存后会重新生成全部 CAD 边界。"
            )
        )

        tools = QHBoxLayout()
        tools.addWidget(QLabel("画笔"))
        self.color_combo = QComboBox()
        self.color_combo.addItem("黑色：补充线条", 0)
        self.color_combo.addItem("白色：擦除错误", 255)
        tools.addWidget(self.color_combo)
        tools.addWidget(QLabel("笔宽"))
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, 80)
        self.width_slider.setValue(3)
        tools.addWidget(self.width_slider, 1)
        self.width_label = QLabel("3 px")
        tools.addWidget(self.width_label)
        undo_button = QPushButton("撤销一笔")
        clear_button = QPushButton("清除全部修改")
        fit_button = QPushButton("适应窗口")
        tools.addWidget(undo_button)
        tools.addWidget(clear_button)
        tools.addWidget(fit_button)
        layout.addLayout(tools)

        self.view = PaintView(binary)
        layout.addWidget(self.view, 1)
        self.color_combo.currentIndexChanged.connect(
            lambda _index: self.view.set_paint_value(int(self.color_combo.currentData()))
        )
        self.width_slider.valueChanged.connect(self.view.set_brush_width)
        self.width_slider.valueChanged.connect(
            lambda value: self.width_label.setText(f"{value} px")
        )
        undo_button.clicked.connect(self.view.undo)
        clear_button.clicked.connect(self.view.clear_edits)
        fit_button.clicked.connect(self.view.fit_image)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并重新拓印")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.view.fit_image()

    def edited_binary(self) -> np.ndarray:
        return self.view.edited_binary()
