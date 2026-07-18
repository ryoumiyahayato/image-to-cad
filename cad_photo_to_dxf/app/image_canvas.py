from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

from .auxiliary_recognition import CircleCandidate, TextCandidate
from .line_detect import LineSegment


LAYER_COLORS = {
    "OUTLINE": QColor(220, 30, 30),
    "WALL_OR_FRAME": QColor(0, 150, 0),
    "GRID_OR_AXIS": QColor(40, 90, 220),
    "HATCH": QColor(180, 0, 180),
    "HATCH_CANDIDATE": QColor(210, 130, 0),
    "DETAIL": QColor(0, 150, 190),
}


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
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(qimage)


class ImageCanvas(QGraphicsView):
    """Adaptive full-resolution scan viewer with independent vector overlays."""

    point_clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._source_image: np.ndarray | None = None
        self._selection_enabled = False
        self._overlay_items: list[QGraphicsItem] = []
        self._manual_zoom = False
        self._lod_key: tuple[int, int] | None = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

    def _reset_scene(self, image: np.ndarray | None) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None
        self._source_image = None
        self._lod_key = None
        self.resetTransform()
        self._manual_zoom = False
        if image is None:
            return
        self._source_image = np.ascontiguousarray(image.copy())
        height, width = self._source_image.shape[:2]
        self._pixmap_item = self._scene.addPixmap(cv_to_qpixmap(self._source_image))
        self._pixmap_item.setZValue(-10.0)
        self._scene.setSceneRect(0.0, 0.0, float(width), float(height))
        self.fit_image()

    def set_image(self, image: np.ndarray | None) -> None:
        self._reset_scene(image)

    def set_vector_result(
        self,
        image: np.ndarray,
        lines: Sequence[LineSegment],
        *,
        circles: Sequence[CircleCandidate] = (),
        texts: Sequence[TextCandidate] = (),
        underlay_opacity: float = 1.0,
    ) -> None:
        """Show the untouched scan and keep recognized entities independently editable."""

        self._reset_scene(image)
        if self._pixmap_item is None:
            return
        self._pixmap_item.setOpacity(max(0.0, min(1.0, float(underlay_opacity))))

        for line in lines:
            pen = QPen(LAYER_COLORS.get(line.layer, QColor(220, 30, 30)), 1.2)
            pen.setCosmetic(True)
            item = self._scene.addLine(line.x1, line.y1, line.x2, line.y2, pen)
            item.setZValue(2.0)
            self._overlay_items.append(item)

        circle_pen = QPen(QColor(0, 170, 255), 1.2)
        circle_pen.setCosmetic(True)
        for circle in circles:
            radius = max(1.0, float(circle.radius))
            item = self._scene.addEllipse(
                circle.center[0] - radius,
                circle.center[1] - radius,
                radius * 2.0,
                radius * 2.0,
                circle_pen,
                QBrush(Qt.BrushStyle.NoBrush),
            )
            item.setZValue(3.0)
            self._overlay_items.append(item)

        for text in texts:
            if not text.text.strip():
                continue
            x, y, _width, height = text.bbox
            item = self._scene.addSimpleText(text.text.strip())
            font = QFont()
            font.setPixelSize(max(6, int(round(height * 0.9))))
            item.setFont(font)
            item.setBrush(QBrush(QColor(210, 40, 180)))
            item.setPos(float(x), float(y))
            item.setZValue(4.0)
            self._overlay_items.append(item)

    def _refresh_lod_pixmap(self) -> None:
        if self._source_image is None or self._pixmap_item is None:
            return
        source_height, source_width = self._source_image.shape[:2]
        scale = abs(float(self.transform().m11()))
        if scale >= 0.72:
            target_width, target_height = source_width, source_height
        else:
            dpr = max(1.0, float(self.devicePixelRatioF()))
            target_width = max(
                320,
                min(source_width, int(round(source_width * scale * dpr * 1.8))),
            )
            target_height = max(
                320,
                min(source_height, int(round(source_height * scale * dpr * 1.8))),
            )
        target_width = min(
            source_width,
            max(1, int(round(target_width / 64.0) * 64)),
        )
        target_height = min(
            source_height,
            max(1, int(round(target_height / 64.0) * 64)),
        )
        key = (target_width, target_height)
        if key == self._lod_key:
            return
        if key == (source_width, source_height):
            preview = self._source_image
        else:
            preview = cv2.resize(
                self._source_image,
                key,
                interpolation=cv2.INTER_AREA,
            )
            lut = np.clip(
                (np.arange(256, dtype=np.float32) / 255.0) ** 1.22 * 255.0,
                0,
                255,
            ).astype(np.uint8)
            preview = cv2.LUT(preview, lut)
        self._pixmap_item.setPixmap(cv_to_qpixmap(preview))
        self._pixmap_item.setTransform(
            QTransform.fromScale(
                source_width / max(float(target_width), 1.0),
                source_height / max(float(target_height), 1.0),
            )
        )
        self._lod_key = key

    def fit_image(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self.fitInView(
            self._scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._manual_zoom = False
        self._refresh_lod_pixmap()

    def actual_size(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self._manual_zoom = True
        self._refresh_lod_pixmap()

    def zoom_by(self, factor: float) -> None:
        if self._pixmap_item is None or factor <= 0:
            return
        current_scale = abs(float(self.transform().m11()))
        target_scale = current_scale * factor
        if target_scale < 0.01 or target_scale > 100.0:
            return
        self.scale(factor, factor)
        self._manual_zoom = True
        self._refresh_lod_pixmap()

    def zoom_in(self) -> None:
        self.zoom_by(1.25)

    def zoom_out(self) -> None:
        self.zoom_by(0.8)

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag
            if enabled
            else QGraphicsView.DragMode.ScrollHandDrag
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
        color: Qt.GlobalColor = Qt.GlobalColor.red,
    ) -> None:
        x, y = point
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        radius = 5.0
        marker = self._scene.addEllipse(
            x - radius,
            y - radius,
            radius * 2,
            radius * 2,
            pen,
        )
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
        color: Qt.GlobalColor = Qt.GlobalColor.red,
    ) -> None:
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        item = self._scene.addLine(
            start[0],
            start[1],
            end[0],
            end[1],
            pen,
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
        if self._selection_enabled and event.button() == Qt.MouseButton.LeftButton:
            scene_point = self.mapToScene(event.position().toPoint())
            if self._scene.sceneRect().contains(scene_point):
                self.point_clicked.emit(scene_point.x(), scene_point.y())
                event.accept()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._pixmap_item is not None and not self._manual_zoom:
            self.fitInView(
                self._scene.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        self._refresh_lod_pixmap()
