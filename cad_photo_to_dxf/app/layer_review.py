from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
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


LAYER_COLORS = {
    "OUTLINE": QColor(215, 35, 35),
    "WALL_OR_FRAME": QColor(20, 155, 55),
    "GRID_OR_AXIS": QColor(30, 90, 220),
    "HATCH": QColor(165, 40, 175),
    "HATCH_CANDIDATE": QColor(210, 130, 20),
    "DETAIL": QColor(35, 145, 180),
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
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setMinimumSize(760, 520)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = 1.2 if delta > 0 else 1 / 1.2
        current = abs(float(self.transform().m11()))
        target = current * factor
        if 0.02 <= target <= 80.0:
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LayerReviewDialog(QDialog):
    """Visual line editor for selecting, deleting and reclassifying vectors.

    The scan remains visible underneath the vectors.  Users work on the drawing
    itself instead of trying to infer geometry from entity numbers and heuristic
    explanations in a table.
    """

    def __init__(
        self,
        lines: list[LineSegment],
        parent: QWidget | None = None,
        *,
        background: np.ndarray | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("可视化修改识别结果")
        self.resize(1280, 820)
        self._lines = list(lines)
        self._layers = [line.layer if line.layer in LAYERS else "DETAIL" for line in lines]
        self._deleted: set[int] = set()
        self._line_items: list[QGraphicsLineItem] = []

        root = QHBoxLayout(self)
        self.view = _ReviewView(self)
        scene = self.view.scene()
        assert scene is not None
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
        self.view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        scene.selectionChanged.connect(self._selection_changed)
        root.addWidget(self.view, 1)

        side = QWidget(self)
        side.setMaximumWidth(310)
        side_layout = QVBoxLayout(side)
        explanation = QLabel(
            "直接在图上点击或框选线段。滚轮缩放，双击适应窗口。"
            "可修改所选线段图层，或删除明显属于文字、噪点的错误线。"
        )
        explanation.setWordWrap(True)
        side_layout.addWidget(explanation)

        self.selection_label = QLabel("未选择线段")
        self.selection_label.setWordWrap(True)
        side_layout.addWidget(self.selection_label)

        self.layer_combo = QComboBox(self)
        self.layer_combo.addItems(LAYERS)
        side_layout.addWidget(self.layer_combo)

        apply_layer = QPushButton("将所选线段设为该图层", self)
        apply_layer.clicked.connect(self._apply_selected_layer)
        side_layout.addWidget(apply_layer)

        delete_button = QPushButton("删除所选错误线段", self)
        delete_button.clicked.connect(self._delete_selected)
        side_layout.addWidget(delete_button)

        restore_button = QPushButton("恢复全部已删除线段", self)
        restore_button.clicked.connect(self._restore_all)
        side_layout.addWidget(restore_button)

        select_all = QPushButton("全选当前可见线段", self)
        select_all.clicked.connect(self._select_all)
        side_layout.addWidget(select_all)

        clear_selection = QPushButton("取消选择", self)
        clear_selection.clicked.connect(scene.clearSelection)
        side_layout.addWidget(clear_selection)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        side_layout.addWidget(self.summary_label)
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
        self._update_summary()

    def _pen_for(self, index: int, *, selected: bool) -> QPen:
        if selected:
            pen = QPen(QColor(255, 0, 255), 3.0)
        else:
            pen = QPen(LAYER_COLORS.get(self._layers[index], QColor(220, 30, 30)), 1.6)
        pen.setCosmetic(True)
        return pen

    def _selected_indices(self) -> list[int]:
        scene = self.view.scene()
        if scene is None:
            return []
        indices: list[int] = []
        for item in scene.selectedItems():
            value = item.data(0)
            if isinstance(value, int) and value not in self._deleted:
                indices.append(value)
        return sorted(set(indices))

    def _selection_changed(self) -> None:
        selected = set(self._selected_indices())
        for index, item in enumerate(self._line_items):
            if index in self._deleted:
                continue
            item.setPen(self._pen_for(index, selected=index in selected))
        if not selected:
            self.selection_label.setText("未选择线段")
        elif len(selected) == 1:
            line = self._lines[next(iter(selected))]
            self.selection_label.setText(
                f"已选择 1 条；长度 {line.length:.1f}px；当前图层 {self._layers[next(iter(selected))]}"
            )
            combo_index = self.layer_combo.findText(self._layers[next(iter(selected))])
            if combo_index >= 0:
                self.layer_combo.setCurrentIndex(combo_index)
        else:
            self.selection_label.setText(f"已选择 {len(selected)} 条线段")

    def _apply_selected_layer(self) -> None:
        selected = self._selected_indices()
        layer = self.layer_combo.currentText()
        if layer not in LAYERS:
            return
        for index in selected:
            self._layers[index] = layer
            self._line_items[index].setPen(self._pen_for(index, selected=True))
        self._update_summary()

    def _delete_selected(self) -> None:
        for index in self._selected_indices():
            self._deleted.add(index)
            self._line_items[index].setSelected(False)
            self._line_items[index].setVisible(False)
        self._update_summary()
        self._selection_changed()

    def _restore_all(self) -> None:
        for index in sorted(self._deleted):
            self._line_items[index].setVisible(True)
            self._line_items[index].setPen(self._pen_for(index, selected=False))
        self._deleted.clear()
        self._update_summary()

    def _select_all(self) -> None:
        for index, item in enumerate(self._line_items):
            if index not in self._deleted:
                item.setSelected(True)

    def _update_summary(self) -> None:
        visible_count = len(self._lines) - len(self._deleted)
        self.summary_label.setText(
            f"保留 {visible_count} 条；删除 {len(self._deleted)} 条。"
            "扫描底图不会被删除，文字和符号仍保留在底图中。"
        )

    @property
    def deleted_count(self) -> int:
        return len(self._deleted)

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
