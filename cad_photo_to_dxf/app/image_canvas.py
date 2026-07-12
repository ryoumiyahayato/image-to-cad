from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)


def cv_to_qpixmap(image: np.ndarray) -> QPixmap:
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

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._selection_enabled = False
        self._overlay_items: list[object] = []
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.Antialiasing)

    def set_image(self, image: np.ndarray | None) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None
        if image is None:
            return
        pixmap = cv_to_qpixmap(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        self.setDragMode(
            QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag
        )

    def clear_overlays(self) -> None:
        for item in list(self._overlay_items):
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._overlay_items.clear()

    def add_point(
        self,
        point: tuple[float, float],
        label: str = "",
        color: Qt.GlobalColor = Qt.red,
    ) -> None:
        x, y = point
        pen = QPen(color, 2)
        radius = 5.0
        marker = self._scene.addEllipse(x - radius, y - radius, radius * 2, radius * 2, pen)
        self._overlay_items.append(marker)
        if label:
            text = self._scene.addText(label)
            text.setDefaultTextColor(color)
            text.setPos(x + radius + 2, y + radius + 2)
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

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._selection_enabled and event.button() == Qt.LeftButton:
            scene_point = self.mapToScene(event.position().toPoint())
            if self._scene.sceneRect().contains(scene_point):
                self.point_clicked.emit(scene_point.x(), scene_point.y())
                event.accept()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
