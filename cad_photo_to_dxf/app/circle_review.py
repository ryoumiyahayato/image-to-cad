from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .auxiliary_recognition import (
    MIN_CIRCLE_EXPORT_CONFIDENCE,
    CircleCandidate,
    confirmable_circles,
)


def select_approved_circles(
    circles: Sequence[CircleCandidate],
    selections: Sequence[bool],
    *,
    minimum_confidence: float = MIN_CIRCLE_EXPORT_CONFIDENCE,
) -> list[CircleCandidate]:
    """Return explicitly selected circles that also satisfy the confidence gate."""
    if len(circles) != len(selections):
        raise ValueError("Each circle must have exactly one review selection")
    approved: list[CircleCandidate] = []
    for circle, selected in zip(circles, selections):
        if selected and circle.confidence >= minimum_confidence:
            approved.append(circle)
    return approved


class CircleReviewDialog(QDialog):
    """Require explicit opt-in before exporting eligible circle candidates."""

    def __init__(
        self,
        circles: list[CircleCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("人工确认圆形实体")
        self.resize(760, 560)
        self._circles = confirmable_circles(circles)
        self._selectors: list[QCheckBox] = []

        layout = QVBoxLayout(self)
        explanation = QLabel(
            f"只显示置信度不低于 {MIN_CIRCLE_EXPORT_CONFIDENCE:.2f} 的候选。"
            "所有候选默认不导出；只有人工勾选后才会写入 DXF CIRCLE。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(len(self._circles), 5, self)
        self.table.setHorizontalHeaderLabels(
            ["导出", "候选", "中心 X,Y (px)", "半径 (px)", "置信度"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )

        for row, circle in enumerate(self._circles):
            selector = QCheckBox(self.table)
            selector.setChecked(False)
            selector.setToolTip("默认不导出，必须由用户明确勾选")
            self.table.setCellWidget(row, 0, selector)
            self._selectors.append(selector)
            self._set_read_only(row, 1, f"CIRCLE-{row + 1:04d}")
            self._set_read_only(
                row,
                2,
                f"{circle.center[0]:.2f}, {circle.center[1]:.2f}",
            )
            self._set_read_only(row, 3, f"{circle.radius:.2f}")
            self._set_read_only(row, 4, f"{circle.confidence:.3f}")

        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.Save).setText("保存人工确认")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_read_only(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(row, column, item)

    def approved_circles(self) -> list[CircleCandidate]:
        return select_approved_circles(
            self._circles,
            [selector.isChecked() for selector in self._selectors],
        )
