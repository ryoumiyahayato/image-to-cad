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
        self._manual_zoom = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def set_image(self, image: np.ndarray | None) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None
        self.resetTransform()
        self._manual_zoom = False
        if image is None:
            return
        pixmap = cv_to_qpixmap(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self.fit_image()

    def fit_image(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._manual_zoom = False

    def actual_size(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self._manual_zoom = True

    def zoom_by(self, factor: float) -> None:
        if self._pixmap_item is None or factor <= 0:
            return
        current_scale = abs(float(self.transform().m11()))
        target_scale = current_scale * factor
        if target_scale < 0.02 or target_scale > 80.0:
            return
        self.scale(factor, factor)
        self._manual_zoom = True

    def zoom_in(self) -> None:
        self.zoom_by(1.25)

    def zoom_out(self) -> None:
        self.zoom_by(0.8)

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

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta == 0 or self._pixmap_item is None:
            super().wheelEvent(event)
            return
        self.zoom_by(1.25 if delta > 0 else 0.8)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if not self._selection_enabled and self._pixmap_item is not None:
            self.fit_image()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
        if self._pixmap_item is not None and not self._manual_zoom:
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
