from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .final_structure import FinalStructure
from .image_canvas import ImageCanvas
from .image_loader import save_image
from .preview_renderer import render_final_structure_preview


@dataclass(frozen=True)
class VisualAcceptanceArtifacts:
    root: Path
    original_path: Path
    reconstructed_path: Path
    overlay_path: Path
    overview_path: Path
    review_path: Path


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("Visual acceptance source image must not be empty")
    if image.ndim == 2:
        return cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 3:
        return np.ascontiguousarray(image.copy())
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_BGRA2BGR)
    raise ValueError("Visual acceptance source must be grayscale, BGR, or BGRA")


def _assert_same_coordinates(source: np.ndarray, structure: FinalStructure) -> None:
    structure.assert_valid()
    source_height, source_width = source.shape[:2]
    width, height = structure.source_size_px
    if (source_width, source_height) != (width, height):
        raise ValueError(
            "Visual acceptance source and FinalStructure must use identical page coordinates"
        )


def _canonical_reconstruction_bgr(structure: FinalStructure) -> np.ndarray:
    preview = render_final_structure_preview(structure)
    if preview.ndim == 2:
        return cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)
    return _to_bgr(preview)


def _draw_review_annotations(
    overlay: np.ndarray,
    structure: FinalStructure,
    *,
    show_text: bool,
    show_symbols: bool,
    show_unverified: bool,
) -> None:
    if show_text:
        for text in structure.texts:
            x, y, width, height = (int(value) for value in text.bbox)
            if width <= 0 or height <= 0:
                continue
            cv2.rectangle(
                overlay,
                (x, y),
                (x + width, y + height),
                (190, 40, 190),
                2,
                cv2.LINE_AA,
            )

    if show_symbols:
        for item in (*structure.logos, *structure.signatures):
            x, y, width, height = (int(value) for value in item.bbox)
            if width <= 0 or height <= 0:
                continue
            cv2.rectangle(
                overlay,
                (x, y),
                (x + width, y + height),
                (30, 150, 230),
                2,
                cv2.LINE_AA,
            )

    if show_unverified and structure.uncertain_text_outline_mask is not None:
        mask = np.ascontiguousarray(
            structure.uncertain_text_outline_mask > 0,
            dtype=np.uint8,
        )
        contours, _hierarchy = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        cv2.drawContours(overlay, contours, -1, (0, 140, 255), 2, cv2.LINE_AA)


def build_visual_acceptance_images(
    source: np.ndarray,
    structure: FinalStructure,
    *,
    show_structure: bool = True,
    show_text: bool = True,
    show_symbols: bool = True,
    show_unverified: bool = True,
    source_opacity: float = 0.72,
    cad_opacity: float = 0.88,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return original, canonical reconstruction, and same-coordinate overlay images.

    The center reconstruction comes directly from the existing FinalStructure
    preview path. The overlay never changes geometry; it only tints canonical
    output pixels and adds review-only bounding boxes for categories that are
    explicitly present in FinalStructure.
    """

    source_bgr = _to_bgr(source)
    _assert_same_coordinates(source_bgr, structure)
    reconstructed = _canonical_reconstruction_bgr(structure)
    if reconstructed.shape[:2] != source_bgr.shape[:2]:
        raise ValueError("Canonical preview does not match source coordinates")

    base_weight = max(0.0, min(1.0, float(source_opacity)))
    overlay = cv2.addWeighted(
        source_bgr,
        base_weight,
        np.full_like(source_bgr, 255),
        1.0 - base_weight,
        0.0,
    )
    if show_structure:
        gray = cv2.cvtColor(reconstructed, cv2.COLOR_BGR2GRAY)
        mask = gray < 245
        alpha = max(0.0, min(1.0, float(cad_opacity)))
        tint = np.zeros_like(overlay)
        tint[:, :] = (30, 40, 220)
        blended = cv2.addWeighted(overlay, 1.0 - alpha, tint, alpha, 0.0)
        overlay[mask] = blended[mask]

    _draw_review_annotations(
        overlay,
        structure,
        show_text=show_text,
        show_symbols=show_symbols,
        show_unverified=show_unverified,
    )
    return source_bgr, reconstructed, overlay


def _safe_label(value: str) -> str:
    result = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in value.strip()
    )
    result = "-".join(part for part in result.split("-") if part)
    return result[:80] or "source"


def _overview_image(
    original: np.ndarray,
    reconstructed: np.ndarray,
    overlay: np.ndarray,
) -> np.ndarray:
    height = max(original.shape[0], reconstructed.shape[0], overlay.shape[0])

    def sized(image: np.ndarray) -> np.ndarray:
        if image.shape[0] == height:
            return image
        ratio = height / max(float(image.shape[0]), 1.0)
        width = max(1, round(image.shape[1] * ratio))
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    images = [sized(original), sized(reconstructed), sized(overlay)]
    gutter = np.full((height, 12, 3), 245, dtype=np.uint8)
    return np.hstack((images[0], gutter, images[1], gutter, images[2]))


def write_visual_acceptance_review(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_visual_acceptance_artifacts(
    source: np.ndarray,
    structure: FinalStructure,
    *,
    root: Path,
    source_label: str,
    review: Mapping[str, object] | None = None,
) -> VisualAcceptanceArtifacts:
    original, reconstructed, overlay = build_visual_acceptance_images(source, structure)
    run_name = f"{_safe_label(source_label)}-{structure.structure_id[:12]}"
    target = root / run_name
    target.mkdir(parents=True, exist_ok=True)

    original_path = target / "original.png"
    reconstructed_path = target / "reconstructed.png"
    overlay_path = target / "overlay.png"
    overview_path = target / "visual_acceptance_overview.png"
    review_path = target / "human_review.json"
    save_image(original_path, original)
    save_image(reconstructed_path, reconstructed)
    save_image(overlay_path, overlay)
    save_image(overview_path, _overview_image(original, reconstructed, overlay))

    payload = {
        "schema_version": 1,
        "source": source_label,
        "structure_id": structure.structure_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "final_entity_summary": {
            "contours": len(structure.contours),
            "straight_lines": len(structure.straight_lines),
            "texts": len(structure.texts),
            "logos": len(structure.logos),
            "signatures": len(structure.signatures),
            "warnings": len(structure.warnings),
        },
        "human_review": dict(review or {}),
    }
    write_visual_acceptance_review(review_path, payload)
    return VisualAcceptanceArtifacts(
        root=target,
        original_path=original_path,
        reconstructed_path=reconstructed_path,
        overlay_path=overlay_path,
        overview_path=overview_path,
        review_path=review_path,
    )


class _LinkedImageCanvas(ImageCanvas):
    view_changed = Signal()
    cursor_moved = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        super().wheelEvent(event)
        self.view_changed.emit()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        self.view_changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        super().mouseDoubleClickEvent(event)
        self.view_changed.emit()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        point = self.mapToScene(event.position().toPoint())
        if self.sceneRect().contains(point):
            self.cursor_moved.emit(float(point.x()), float(point.y()))
        super().mouseMoveEvent(event)


class VisualAcceptanceWorkbench(QWidget):
    """Human-first three-pane review surface for one FinalStructure page."""

    review_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: np.ndarray | None = None
        self._structure: FinalStructure | None = None
        self._source_label = ""
        self._syncing = False
        self._artifact_paths: VisualAcceptanceArtifacts | None = None

        root = QVBoxLayout(self)
        title = QLabel(
            "肉眼验收：左边看原图，中间看最终 CAD 重建，右边看同坐标叠加。",
            self,
        )
        title.setWordWrap(True)
        root.addWidget(title)

        splitter = QSplitter(self)
        self.original_canvas = _LinkedImageCanvas()
        self.reconstructed_canvas = _LinkedImageCanvas()
        self.overlay_canvas = _LinkedImageCanvas()
        for caption, canvas in (
            ("原始图", self.original_canvas),
            ("最终重建", self.reconstructed_canvas),
            ("叠加比较", self.overlay_canvas),
        ):
            panel = QWidget(splitter)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(2, 2, 2, 2)
            label = QLabel(caption, panel)
            panel_layout.addWidget(label)
            panel_layout.addWidget(canvas, 1)
            splitter.addWidget(panel)
        splitter.setSizes([1, 1, 1])
        root.addWidget(splitter, 1)

        controls = QGroupBox("显示与人工验收", self)
        controls_layout = QVBoxLayout(controls)
        toggle_row = QHBoxLayout()
        self.show_structure = QCheckBox("结构（最终 CAD）", controls)
        self.show_text = QCheckBox("文字标记", controls)
        self.show_symbols = QCheckBox("符号/签名标记", controls)
        self.show_unverified = QCheckBox("未确认区域", controls)
        self.show_warnings = QCheckBox("警告（仅计数）", controls)
        self.show_warnings.setChecked(True)
        self.show_warnings.setEnabled(False)
        self.show_warnings.setToolTip(
            "当前 warning 没有可信的页面区域坐标，所以只显示数量，不伪造高亮框。"
        )
        for checkbox in (
            self.show_structure,
            self.show_text,
            self.show_symbols,
            self.show_unverified,
        ):
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._refresh_overlay)
            toggle_row.addWidget(checkbox)
        toggle_row.addWidget(self.show_warnings)
        controls_layout.addLayout(toggle_row)

        verdict_row = QHBoxLayout()
        verdict_row.addWidget(QLabel("整页判断：", controls))
        self.verdict_group = QButtonGroup(self)
        self.verdict_group.setExclusive(True)
        for label, value in (
            ("通过", "PASS"),
            ("部分通过", "PARTIAL"),
            ("不通过", "FAIL"),
        ):
            button = QPushButton(label, controls)
            button.setCheckable(True)
            button.setProperty("verdict", value)
            self.verdict_group.addButton(button)
            verdict_row.addWidget(button)
        self.verdict_group.buttonClicked.connect(self._emit_review_changed)
        verdict_row.addStretch(1)
        controls_layout.addLayout(verdict_row)

        problem_row = QHBoxLayout()
        self.problem_checks: dict[str, QCheckBox] = {}
        for label, value in (
            ("漏内容", "missing_content"),
            ("多画", "extra_content"),
            ("错误连接", "wrong_connection"),
            ("位置/比例", "position_or_scale"),
            ("文字", "text_error"),
            ("符号", "symbol_error"),
            ("整体严重错误", "severe_global_error"),
            ("其他", "other"),
        ):
            checkbox = QCheckBox(label, controls)
            checkbox.toggled.connect(self._emit_review_changed)
            checkbox.setProperty("problem", value)
            self.problem_checks[value] = checkbox
            problem_row.addWidget(checkbox)
        controls_layout.addLayout(problem_row)

        info_row = QHBoxLayout()
        self.coordinate_label = QLabel("坐标：—", controls)
        self.warning_label = QLabel("警告：—", controls)
        self.artifact_label = QLabel("总览截图：尚未生成", controls)
        self.artifact_label.setWordWrap(True)
        info_row.addWidget(self.coordinate_label)
        info_row.addWidget(self.warning_label)
        info_row.addWidget(self.artifact_label, 1)
        controls_layout.addLayout(info_row)
        root.addWidget(controls)

        for canvas in (
            self.original_canvas,
            self.reconstructed_canvas,
            self.overlay_canvas,
        ):
            canvas.view_changed.connect(lambda c=canvas: self._sync_views(c))
        self.overlay_canvas.cursor_moved.connect(self._update_coordinate_label)

    def clear(self) -> None:
        self._source = None
        self._structure = None
        self._source_label = ""
        self._artifact_paths = None
        self.original_canvas.set_image(None)
        self.reconstructed_canvas.set_image(None)
        self.overlay_canvas.set_image(None)
        self.coordinate_label.setText("坐标：—")
        self.warning_label.setText("警告：—")
        self.artifact_label.setText("总览截图：尚未生成")

    def set_result(
        self,
        source: np.ndarray,
        structure: FinalStructure,
        *,
        source_label: str,
    ) -> None:
        self._source = np.ascontiguousarray(source.copy())
        self._structure = structure
        self._source_label = source_label
        original, reconstructed, overlay = build_visual_acceptance_images(
            self._source,
            structure,
            show_structure=self.show_structure.isChecked(),
            show_text=self.show_text.isChecked(),
            show_symbols=self.show_symbols.isChecked(),
            show_unverified=self.show_unverified.isChecked(),
        )
        self.original_canvas.set_image(original)
        self.reconstructed_canvas.set_image(reconstructed)
        self.overlay_canvas.set_image(overlay)
        self.warning_label.setText(
            f"警告：{len(structure.warnings)} 条"
            if structure.warnings
            else "警告：无"
        )
        self._sync_views(self.original_canvas)

    def set_artifact_paths(self, artifacts: VisualAcceptanceArtifacts) -> None:
        self._artifact_paths = artifacts
        self.artifact_label.setText(f"总览截图：{artifacts.overview_path}")

    def review_payload(self) -> dict[str, object]:
        verdict = None
        checked = self.verdict_group.checkedButton()
        if checked is not None:
            verdict = checked.property("verdict")
        problems = [
            key for key, checkbox in self.problem_checks.items() if checkbox.isChecked()
        ]
        return {
            "source": self._source_label,
            "structure_id": (
                self._structure.structure_id if self._structure is not None else None
            ),
            "verdict": verdict,
            "problems": problems,
        }

    def _emit_review_changed(self, *_args: object) -> None:
        self.review_changed.emit(self.review_payload())

    def _refresh_overlay(self, *_args: object) -> None:
        if self._source is None or self._structure is None:
            return
        _original, _reconstructed, overlay = build_visual_acceptance_images(
            self._source,
            self._structure,
            show_structure=self.show_structure.isChecked(),
            show_text=self.show_text.isChecked(),
            show_symbols=self.show_symbols.isChecked(),
            show_unverified=self.show_unverified.isChecked(),
        )
        self.overlay_canvas.set_image(overlay)
        self._sync_views(self.original_canvas)

    def _sync_views(self, source: _LinkedImageCanvas) -> None:
        if self._syncing or source.scene() is None:
            return
        self._syncing = True
        try:
            center = source.mapToScene(source.viewport().rect().center())
            transform: QTransform = source.transform()
            for target in (
                self.original_canvas,
                self.reconstructed_canvas,
                self.overlay_canvas,
            ):
                if target is source or target.scene() is None:
                    continue
                target.setTransform(transform)
                target.centerOn(center)
        finally:
            self._syncing = False

    def _update_coordinate_label(self, x: float, y: float) -> None:
        if self._structure is None:
            self.coordinate_label.setText("坐标：—")
            return
        width, height = self._structure.source_size_px
        x_percent = 100.0 * x / max(float(width), 1.0)
        y_percent = 100.0 * y / max(float(height), 1.0)
        self.coordinate_label.setText(
            f"坐标：x={x_percent:.1f}%, y={y_percent:.1f}%"
        )
