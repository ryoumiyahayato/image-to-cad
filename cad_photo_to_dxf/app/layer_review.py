from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .layer_classifier import LAYERS
from .line_detect import LineSegment


class LayerReviewDialog(QDialog):
    """Allow explicit per-entity confirmation or correction of heuristic layers."""

    def __init__(self, lines: list[LineSegment], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("人工复核图层")
        self.resize(1050, 700)
        self._lines = list(lines)
        self._selectors: list[QComboBox] = []

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "自动图层属于启发式分类。请逐条确认或修改；应用后会在实体历史中记录 "
            "manual_layer_review，报告仍保留自动分类理由。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(len(lines), 6, self)
        self.table.setHorizontalHeaderLabels(
            ["实体", "图层", "置信度", "长度(px)", "来源", "分类理由"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)

        for row, line in enumerate(lines):
            self._set_read_only(row, 0, f"LINE-{row + 1:06d}")
            selector = QComboBox(self.table)
            selector.addItems(LAYERS)
            index = selector.findText(line.layer)
            selector.setCurrentIndex(index if index >= 0 else selector.findText("DETAIL"))
            self.table.setCellWidget(row, 1, selector)
            self._selectors.append(selector)
            self._set_read_only(row, 2, f"{line.classification_confidence:.3f}")
            self._set_read_only(row, 3, f"{line.length:.2f}")
            self._set_read_only(row, 4, ", ".join(line.source_ids) or "—")
            self._set_read_only(
                row,
                5,
                "; ".join(line.classification_reasons) or "未记录",
            )

        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.Save).setText("应用人工图层")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_read_only(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, column, item)

    def reviewed_lines(self) -> tuple[list[LineSegment], int]:
        reviewed: list[LineSegment] = []
        changed = 0
        for line, selector in zip(self._lines, self._selectors):
            layer = selector.currentText()
            if layer == line.layer:
                reviewed.append(line)
                continue
            changed += 1
            reviewed.append(
                line.copy(
                    layer=layer,
                    history=tuple(
                        dict.fromkeys(line.history + ("manual_layer_review",))
                    ),
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


def layer_counts(lines: list[LineSegment]) -> dict[str, int]:
    return dict(sorted(Counter(line.layer for line in lines).items()))
