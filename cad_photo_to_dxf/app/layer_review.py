from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .image_canvas import cv_to_qpixmap
from .layer_classifier import LAYERS
from .line_detect import LineSegment


_LAYER_COLORS = {
    "OUTLINE": QColor(220, 45, 45),
    "WALL_OR_FRAME": QColor(25, 150, 75),
    "GRID_OR_AXIS": QColor(40, 105, 220),
    "HATCH": QColor(180, 65, 190),
    "HATCH_CANDIDATE": QColor(225, 145, 30),
    "DETAIL": QColor(30, 30, 30),
}


def apply_layer_overrides(
    lines: Sequence[LineSegment],
    selected_layers: Sequence[str],
) -> tuple[list[LineSegment], int]:
    """Apply reviewed layers while preserving automatic classification evidence."""
    if len(lines) != len(selected_layers):
        raise ValueError("Each line must have exactly one reviewed layer")

    reviewed: list[LineSegment] = []
    changed = 0
    for line, layer in zip(lines, selected_layers):
        if layer not in LAYERS:
            raise ValueError(f"Unknown layer: {layer}")
        if layer == line.layer:
            reviewed.append(line)
            continue
        changed += 1
        reviewed.append(
            line.copy(
                layer=layer,
                history=tuple(dict.fromkeys(line.history + ("manual_layer_review",))),
                classification_confidence=1.0,
                classification_reasons=tuple(
                    dict.fromkeys(
                        line.classification_reasons
                        + (f"manual_override:{line.layer}->{layer}",)
                    )
                ),
            )
        )
    return reviewed, changed


class _ReviewView(QGraphicsView):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.angleDelta().y() == 0:
            return super().wheelEvent(event)
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        current = abs(float(self.transform().m11()))
        if 0.03 <= current * factor <= 60.0:
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LayerReviewDialog(QDialog):
    """Direct visual selection, re-layering and deletion over the source scan."""

    def __init__(
        self,
        lines: list[LineSegment],
        parent: QWidget | None = None,
        *,
        background: np.ndarray | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("在图纸上可视化修改识别结果")
        self.resize(1350, 850)
        self._lines = list(lines)
        self._layers = [line.layer if line.layer in LAYERS else "DETAIL" for line in lines]
        self._deleted: set[int] = set()
        self._line_items: list[QGraphicsLineItem] = []

        root = QHBoxLayout(self)
        scene = QGraphicsScene(self)
        self.view = _ReviewView(scene, self)
        self.view.setRenderHints(self.view.renderHints())
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.view.setBackgroundBrush(QBrush(QColor(245, 245, 245)))

        if background is not None and background.size:
            pixmap_item = QGraphicsPixmapItem(cv_to_qpixmap(background))
            pixmap_item.setZValue(-10.0)
            scene.addItem(pixmap_item)
            scene.setSceneRect(pixmap_item.boundingRect())

        for index, line in enumerate(lines):
            item = QGraphicsLineItem(line.x1, line.y1, line.x2, line.y2)
            item.setData(0, index)
            item.setFlag(QGraphicsItem.ItemIsSelectable, True)
            item.setZValue(10.0)
            item.setPen(self._pen_for(index, selected=False))
            scene.addItem(item)
            self._line_items.append(item)
        if background is None and lines:
            scene.setSceneRect(scene.itemsBoundingRect())
        scene.selectionChanged.connect(self._selection_changed)
        root.addWidget(self.view, 1)

        side = QWidget(self)
        side.setMaximumWidth(330)
        side_layout = QVBoxLayout(side)
        explanation = QLabel(
            "直接在图纸上点击或框选线段。滚轮缩放，双击适应窗口。"
            "可把所选线段改到指定图层，或删除明显属于文字、噪点的错误线。"
        )
        explanation.setWordWrap(True)
        side_layout.addWidget(explanation)
        self.selection_label = QLabel("未选择线段")
        self.selection_label.setWordWrap(True)
        side_layout.addWidget(self.selection_label)

        self.layer_combo = QComboBox(self)
        self.layer_combo.addItems(LAYERS)
        side_layout.addWidget(self.layer_combo)
        apply_button = QPushButton("将所选线段设为该图层", self)
        apply_button.clicked.connect(self._apply_selected_layer)
        side_layout.addWidget(apply_button)
        delete_button = QPushButton("删除所选错误线段", self)
        delete_button.clicked.connect(self._delete_selected)
        side_layout.addWidget(delete_button)
        restore_button = QPushButton("恢复全部已删除线段", self)
        restore_button.clicked.connect(self._restore_all)
        side_layout.addWidget(restore_button)
        select_all_button = QPushButton("全选当前可见线段", self)
        select_all_button.clicked.connect(self._select_all)
        side_layout.addWidget(select_all_button)
        clear_button = QPushButton("清除选择", self)
        clear_button.clicked.connect(scene.clearSelection)
        side_layout.addWidget(clear_button)
        side_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.Save).setText("应用可视化修改")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        side_layout.addWidget(buttons)
        root.addWidget(side)

        if not scene.sceneRect().isEmpty():
            self.view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    @property
    def deleted_count(self) -> int:
        return len(self._deleted)

    def _pen_for(self, index: int, *, selected: bool) -> QPen:
        color = QColor(255, 35, 35) if selected else _LAYER_COLORS.get(
            self._layers[index], QColor(30, 30, 30)
        )
        pen = QPen(color, 3.0 if selected else 1.7)
        pen.setCosmetic(True)
        return pen

    def _selected_indexes(self) -> list[int]:
        indexes: list[int] = []
        for item in self.view.scene().selectedItems():
            value = item.data(0)
            if isinstance(value, int) and value not in self._deleted:
                indexes.append(value)
        return sorted(set(indexes))

    def _selection_changed(self) -> None:
        selected = set(self._selected_indexes())
        for index, item in enumerate(self._line_items):
            if index in self._deleted:
                continue
            item.setPen(self._pen_for(index, selected=index in selected))
        if not selected:
            self.selection_label.setText(
                f"未选择线段；当前保留 {len(self._lines) - len(self._deleted)} 条，"
                f"已删除 {len(self._deleted)} 条"
            )
            return
        layers = sorted({self._layers[index] for index in selected})
        self.selection_label.setText(
            f"已选择 {len(selected)} 条；当前图层：{', '.join(layers)}"
        )
        if len(layers) == 1:
            combo_index = self.layer_combo.findText(layers[0])
            if combo_index >= 0:
                self.layer_combo.setCurrentIndex(combo_index)

    def _apply_selected_layer(self) -> None:
        selected = self._selected_indexes()
        if not selected:
            return
        layer = self.layer_combo.currentText()
        for index in selected:
            self._layers[index] = layer
            self._line_items[index].setPen(self._pen_for(index, selected=True))
        self._selection_changed()

    def _delete_selected(self) -> None:
        for index in self._selected_indexes():
            self._deleted.add(index)
            item = self._line_items[index]
            item.setSelected(False)
            item.setVisible(False)
        self._selection_changed()

    def _restore_all(self) -> None:
        for index in list(self._deleted):
            self._line_items[index].setVisible(True)
            self._line_items[index].setPen(self._pen_for(index, selected=False))
        self._deleted.clear()
        self._selection_changed()

    def _select_all(self) -> None:
        for index, item in enumerate(self._line_items):
            if index not in self._deleted and item.isVisible():
                item.setSelected(True)

    def reviewed_lines(self) -> tuple[list[LineSegment], int]:
        active_lines: list[LineSegment] = []
        active_layers: list[str] = []
        for index, line in enumerate(self._lines):
            if index in self._deleted:
                continue
            active_lines.append(line)
            active_layers.append(self._layers[index])
        reviewed, layer_changed = apply_layer_overrides(active_lines, active_layers)
        return reviewed, layer_changed + len(self._deleted)


def layer_counts(lines: Sequence[LineSegment]) -> dict[str, int]:
    return dict(sorted(Counter(line.layer for line in lines).items()))
