from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)


def cv_to_qpixmap(image: np.ndarray) -> QPixmap:
    """Convert an OpenCV image to an owned Qt pixmap."""
    if image.ndim == 2:
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    height, width, channels = rgb.shape
    qimage = QImage(
        rgb.data,
        width,
        height,
        channels * width,
        QImage.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(qimage)


class ImageCanvas(QGraphicsView):
    point_clicked = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._overlay_items: list[object] = []
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.darkGray)
        self._selection_enabled = False

    def set_image(self, image: np.ndarray | None) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None
        if image is None:
            return
        pixmap = cv_to_qpixmap(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self.resetTransform()
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        mode = QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag
        self.setDragMode(mode)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def clear_overlays(self) -> None:
        for item in self._overlay_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._overlay_items.clear()

    def add_point(
        self,
        point: tuple[float, float],
        label: str = "",
        color: Qt.GlobalColor = Qt.red,
    ) -> None:
        x, y = point
        pen = QPen(color, 3)
        ellipse = self._scene.addEllipse(x - 5, y - 5, 10, 10, pen)
        self._overlay_items.append(ellipse)
        if label:
            text = self._scene.addSimpleText(label)
            text.setBrush(color)
            text.setPos(x + 7, y + 7)
            self._overlay_items.append(text)

    def add_line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        color: Qt.GlobalColor = Qt.red,
    ) -> None:
        item = self._scene.addLine(
            start[0],
            start[1],
            end[0],
            end[1],
            QPen(color, 2),
        )
        self._overlay_items.append(item)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.angleDelta().y() == 0:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._selection_enabled
            and event.button() == Qt.LeftButton
            and self._pixmap_item is not None
        ):
            scene_point = self.mapToScene(event.position().toPoint())
            image_rect = self._pixmap_item.boundingRect()
            if image_rect.contains(scene_point):
                self.point_clicked.emit(scene_point.x(), scene_point.y())
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._pixmap_item is not None and self.transform().m11() == 1.0:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
