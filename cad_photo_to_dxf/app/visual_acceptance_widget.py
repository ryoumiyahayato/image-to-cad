from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .final_structure import FinalStructure
from .image_canvas import ImageCanvas
from .visual_acceptance import (
    VisualAcceptanceImages,
    VisualAcceptanceRun,
    VisualLayerSelection,
    create_visual_acceptance_run,
    render_visual_acceptance,
    update_human_review,
)


ISSUE_TAGS = {
    "漏内容": "MISSING_CONTENT",
    "多画": "EXTRA_CONTENT",
    "乱连接": "WRONG_CONNECTION",
    "位置错误": "POSITION_OR_SCALE_ERROR",
    "文字错误": "TEXT_ERROR",
    "符号错误": "SYMBOL_ERROR",
    "整体错误": "SEVERE_OVERALL_ERROR",
    "其他": "OTHER",
}


class AcceptanceCanvas(ImageCanvas):
    view_changed = Signal(object)
    coordinate_changed = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        super().wheelEvent(event)
        self.view_changed.emit(self)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        self.view_changed.emit(self)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        point = self.mapToScene(event.position().toPoint())
        rect = self.scene().sceneRect()
        if rect.width() > 0 and rect.height() > 0 and rect.contains(point):
            self.coordinate_changed.emit(
                100.0 * point.x() / rect.width(),
                100.0 * point.y() / rect.height(),
            )
        super().mouseMoveEvent(event)


class VisualAcceptanceWidget(QWidget):
    """Human-facing source/final/overlay view backed by one FinalStructure."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("visualAcceptanceWorkbench")
        self._source: np.ndarray | None = None
        self._structure: FinalStructure | None = None
        self._images: VisualAcceptanceImages | None = None
        self._run: VisualAcceptanceRun | None = None
        self._source_label = ""
        self._page_label = ""
        self._commit = "UNKNOWN"
        self._syncing = False

        layout = QVBoxLayout(self)
        self.info_label = QLabel("处理一张图纸后，这里会显示原图、最终重建和叠加比较。")
        self.info_label.setObjectName("visualAcceptanceInfo")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        views = QHBoxLayout()
        self.original_canvas = self._view_column(views, "原始图")
        self.reconstructed_canvas = self._view_column(views, "最终重建")
        self.overlay_canvas = self._view_column(views, "叠加比较")
        layout.addLayout(views, 1)
        self._canvases = (
            self.original_canvas,
            self.reconstructed_canvas,
            self.overlay_canvas,
        )
        for canvas in self._canvases:
            canvas.view_changed.connect(self._synchronize_views)
            canvas.coordinate_changed.connect(self._show_coordinate)

        controls = QHBoxLayout()
        self.layer_checkboxes: dict[str, QCheckBox] = {}
        for key, label in (
            ("structure_lines", "结构线"),
            ("texts", "文字"),
            ("symbols", "符号"),
            ("unverified_geometry", "未确认几何"),
            ("review_warnings", "警告 / Review 区域"),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._refresh_images)
            self.layer_checkboxes[key] = checkbox
            controls.addWidget(checkbox)
        controls.addStretch(1)
        controls.addWidget(QLabel("原图透明度"))
        self.source_opacity = QSlider(Qt.Orientation.Horizontal)
        self.source_opacity.setRange(0, 100)
        self.source_opacity.setValue(72)
        self.source_opacity.setMaximumWidth(120)
        self.source_opacity.valueChanged.connect(self._refresh_images)
        controls.addWidget(self.source_opacity)
        controls.addWidget(QLabel("CAD 透明度"))
        self.cad_opacity = QSlider(Qt.Orientation.Horizontal)
        self.cad_opacity.setRange(0, 100)
        self.cad_opacity.setValue(82)
        self.cad_opacity.setMaximumWidth(120)
        self.cad_opacity.valueChanged.connect(self._refresh_images)
        controls.addWidget(self.cad_opacity)
        layout.addLayout(controls)

        review_group = QGroupBox("人工验收")
        review_layout = QVBoxLayout(review_group)
        verdict_row = QHBoxLayout()
        self.verdict_group = QButtonGroup(self)
        self.verdict_group.setExclusive(True)
        for label, verdict in (
            ("通过", "PASS"),
            ("部分通过", "PARTIAL"),
            ("不通过", "FAIL"),
        ):
            button = QPushButton(label)
            button.setObjectName(f"visualVerdict{verdict.title()}")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, value=verdict: self._save_review(value)
            )
            self.verdict_group.addButton(button)
            verdict_row.addWidget(button)
        verdict_row.addStretch(1)
        self.coordinate_label = QLabel("位置：—")
        verdict_row.addWidget(self.coordinate_label)
        review_layout.addLayout(verdict_row)

        issue_row = QHBoxLayout()
        issue_row.addWidget(QLabel("问题类型："))
        self.issue_checkboxes: dict[str, QCheckBox] = {}
        for label, key in ISSUE_TAGS.items():
            checkbox = QCheckBox(label)
            self.issue_checkboxes[key] = checkbox
            issue_row.addWidget(checkbox)
        issue_row.addStretch(1)
        review_layout.addLayout(issue_row)
        layout.addWidget(review_group)

        self.details_group = QGroupBox("开发详情")
        self.details_group.setCheckable(True)
        self.details_group.setChecked(False)
        details_layout = QVBoxLayout(self.details_group)
        self.details_label = QLabel("尚无最终结构。")
        self.details_label.setWordWrap(True)
        details_layout.addWidget(self.details_label)
        self.details_group.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_group)
        self._toggle_details(False)

    def _view_column(self, parent: QHBoxLayout, title: str) -> AcceptanceCanvas:
        column = QVBoxLayout()
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(label)
        canvas = AcceptanceCanvas()
        canvas.setMinimumSize(240, 280)
        column.addWidget(canvas, 1)
        parent.addLayout(column, 1)
        return canvas

    def _toggle_details(self, visible: bool) -> None:
        self.details_label.setVisible(bool(visible))

    def clear_result(self) -> None:
        self._source = None
        self._structure = None
        self._images = None
        self._run = None
        for canvas in getattr(self, "_canvases", ()):
            canvas.set_image(None)
        self.info_label.setText("处理一张图纸后，这里会显示原图、最终重建和叠加比较。")
        self.details_label.setText("尚无最终结构。")

    def set_result(
        self,
        source: np.ndarray,
        structure: FinalStructure,
        *,
        source_label: str,
        page_label: str,
        commit: str,
        output_root: Path,
        corpus_split: str | None = None,
    ) -> VisualAcceptanceRun:
        self._source = np.ascontiguousarray(source.copy())
        self._structure = structure
        self._source_label = source_label
        self._page_label = page_label
        self._commit = commit
        self._run, self._images = create_visual_acceptance_run(
            self._source,
            structure,
            output_root=output_root,
            source_label=source_label,
            page_label=page_label,
            commit=commit,
            corpus_split=corpus_split,
        )
        self._show_images(self._images)
        self.info_label.setText(
            f"{source_label} · {page_label} · 最终实体 {self._run.entity_count} 个 · "
            "三个视图已按同一像素坐标对齐并联动"
        )
        warning_text = "；".join(structure.warnings) if structure.warnings else "无"
        self.details_label.setText(
            f"FinalStructure：{structure.structure_id}\n"
            f"总览截图：{self._run.overview_path}\n"
            f"语义提示：语义未确认时仍保留几何。\n"
            f"警告：{warning_text}"
        )
        return self._run

    def _selection(self) -> VisualLayerSelection:
        return VisualLayerSelection(
            **{
                key: checkbox.isChecked()
                for key, checkbox in self.layer_checkboxes.items()
            }
        )

    def _refresh_images(self, _value: object = None) -> None:
        if self._source is None or self._structure is None:
            return
        self._images = render_visual_acceptance(
            self._source,
            self._structure,
            layers=self._selection(),
            source_opacity=self.source_opacity.value() / 100.0,
            cad_opacity=self.cad_opacity.value() / 100.0,
        )
        self._show_images(self._images)

    def _show_images(self, images: VisualAcceptanceImages) -> None:
        self.original_canvas.set_image(images.original)
        self.reconstructed_canvas.set_image(images.reconstructed)
        self.overlay_canvas.set_image(images.overlay)

    def _synchronize_views(self, source: object) -> None:
        if self._syncing or not isinstance(source, AcceptanceCanvas):
            return
        self._syncing = True
        try:
            center = source.mapToScene(source.viewport().rect().center())
            transform = source.transform()
            for canvas in self._canvases:
                if canvas is source:
                    continue
                canvas.setTransform(transform)
                canvas.centerOn(center)
        finally:
            self._syncing = False

    def _show_coordinate(self, x_percent: float, y_percent: float) -> None:
        self.coordinate_label.setText(f"位置：x={x_percent:.1f}%, y={y_percent:.1f}%")

    def _save_review(self, verdict: str) -> None:
        if self._run is None:
            return
        issue_tags = [
            key for key, checkbox in self.issue_checkboxes.items() if checkbox.isChecked()
        ]
        update_human_review(
            self._run,
            verdict=verdict,
            issue_tags=issue_tags,
            source_label=self._source_label,
            page_label=self._page_label,
            commit=self._commit,
        )
        self.info_label.setText(
            f"{self._source_label} · {self._page_label} · 人工结论已保存：{verdict}"
        )
