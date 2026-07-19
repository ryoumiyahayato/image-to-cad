from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from .cancellation import CancellationToken
from .document_export import DocumentPage
from .gui_consolidated import MainWindow as _ConsolidatedMainWindow
from .gui_export import _export_pdf_document, export_from_window
from .gui_state_guard import PDF_VIEW_DPI
from .image_loader import load_image
from .perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE
from .raster_trace import RasterTraceResult, TracePath, trace_binary, trace_image
from .trace_paint import TracePaintDialog
from . import gui as _gui


TRACE_COLORS = (
    ("黑/白（CAD 颜色 7）", 7),
    ("红色", 1),
    ("黄色", 2),
    ("绿色", 3),
    ("青色", 4),
    ("蓝色", 5),
    ("品红", 6),
    ("灰色", 8),
)


class MainWindow(_ConsolidatedMainWindow):
    """Full-fidelity trace workflow.

    The default operation is deliberately not structural recognition. It
    thresholds the corrected page at full render resolution and traces every
    black connected region, including text, symbols, curves, hatching and
    irregular strokes. The old semantic LINE workflow remains in the source for
    compatibility but is no longer the normal button path.
    """

    def __init__(self) -> None:
        self._trace_paths: tuple[TracePath, ...] = ()
        self._trace_threshold: int | None = None
        self._trace_foreground_pixels = 0
        self._trace_vertex_count = 0
        super().__init__()
        self._update_scale_label()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        rename_prefixes = {
            "1. 导入图片 / 扫描 PDF": "导入图片 / 扫描 PDF",
            "2A. 照片自动校正": "图片校正",
            "2B. 照片手动四角校正": "手动四角校正",
            "3. 自动识别结构线": "完整拓印全部黑白线条",
            "4. 在图纸上可视化修改": "在黑白拓印图上修补",
            "5. 模型尺寸校准（可选）": "按已知尺寸校准（照片补充）",
            "6. 导出同一 CAD（DWG / DXF）": "导出同一 CAD（DWG / DXF）",
        }
        correction_button: QPushButton | None = None
        manual_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            replacement = rename_prefixes.get(button.text())
            if replacement is not None:
                button.setText(replacement)
            if button.text() == "图片校正":
                correction_button = button
            elif button.text() == "手动四角校正":
                manual_button = button

        if correction_button is not None:
            try:
                correction_button.clicked.disconnect()
            except RuntimeError:
                pass
            correction_button.clicked.connect(self.correct_image)
        if manual_button is not None:
            manual_button.setVisible(False)

        self.batch_pdf_button.setText("批量拓印全部 PDF 页面（可取消）")
        self.tabs.setTabText(self.tabs.indexOf(self.corrected_canvas), "校正 / 黑白图")
        self.tabs.setTabText(self.tabs.indexOf(self.preprocess_tabs), "黑白拓印过程")
        self.tabs.setTabText(self.tabs.indexOf(self.detected_canvas), "拓印结果")

        scale_group = QGroupBox("拓印输出与比例尺", container)
        form = QFormLayout(scale_group)
        self.drawing_scale_spin = QSpinBox(scale_group)
        self.drawing_scale_spin.setRange(1, 10000)
        self.drawing_scale_spin.setValue(100)
        self.drawing_scale_spin.setSuffix("")
        self.drawing_scale_spin.setToolTip(
            "例如 100 表示图纸比例 1:100。PDF 纸面毫米将按该比例换算为模型毫米。"
        )
        form.addRow("图纸比例 1:", self.drawing_scale_spin)
        self.trace_color_combo = QComboBox(scale_group)
        for label, value in TRACE_COLORS:
            self.trace_color_combo.addItem(label, value)
        form.addRow("CAD 拓印颜色", self.trace_color_combo)
        self.scale_result_label = QLabel(scale_group)
        self.scale_result_label.setWordWrap(True)
        form.addRow("模型坐标", self.scale_result_label)
        self.drawing_scale_spin.valueChanged.connect(self._scale_changed)
        self.trace_color_combo.currentIndexChanged.connect(self._trace_color_changed)

        export_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "导出选项"
            ),
            None,
        )
        export_index = layout.indexOf(export_group) if export_group is not None else -1
        layout.insertWidget(export_index if export_index >= 0 else 4, scale_group)

        self.show_advanced_checkbox.setText("显示旧结构线参数（仅兼容，不用于完整拓印）")
        self.include_underlay_checkbox.setText(
            "同时保留扫描底图（用于对照；矢量拓印本身包含全部黑白笔画）"
        )
        return scroll

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        super()._set_single_image_state(image, corrected=corrected)
        self._clear_trace_state()

    def _clear_trace_state(self) -> None:
        self._trace_paths = ()
        self._trace_threshold = None
        self._trace_foreground_pixels = 0
        self._trace_vertex_count = 0

    def _drawing_scale(self) -> float:
        spin = getattr(self, "drawing_scale_spin", None)
        return float(spin.value()) if spin is not None else 100.0

    def _trace_color(self) -> int:
        combo = getattr(self, "trace_color_combo", None)
        return int(combo.currentData()) if combo is not None else 7

    def _scale_changed(self, _value: int) -> None:
        self._update_scale_label()
        if self._native_pdf_mode:
            self._save_current_pdf_state()

    def _trace_color_changed(self, _index: int) -> None:
        if self._native_pdf_mode:
            self._save_current_pdf_state()

    def _update_scale_label(self) -> None:
        label = getattr(self, "scale_result_label", None)
        if label is None:
            return
        ratio = self._drawing_scale()
        if self.calibration is None:
            label.setText(f"1:{int(ratio)}；尚无纸面毫米标定")
            return
        model_mm_per_pixel = self.calibration.mm_per_pixel * ratio
        label.setText(
            f"1:{int(ratio)}；{model_mm_per_pixel:.6f} 模型 mm/px "
            f"（纸面 {self.calibration.mm_per_pixel:.6f} mm/px）"
        )
        self.info_label.setText(
            f"图纸比例 1:{int(ratio)}；模型坐标 {model_mm_per_pixel:.6f} mm/px"
        )

    def correct_image(self) -> None:
        if self._native_pdf_mode:
            self.corrected_image = self.original_image.copy() if self.original_image is not None else None
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self.statusBar().showMessage("PDF 页面无需透视校正，可直接完整拓印")
            return
        self.auto_perspective()

    def auto_perspective(self) -> None:
        if not self._require_original():
            return
        source = self.original_image.copy()
        ratio = self._target_aspect_ratio()
        revision = self._state_revision

        def operation(
            token: CancellationToken,
            progress: Callable[[str, float], None],
        ) -> object:
            token.checkpoint()
            progress("自动寻找纸张边界", 0.15)
            result = _gui.auto_correct(source, ratio)
            token.checkpoint()
            progress("透视校正", 1.0)
            return result

        def use_manual(message: str) -> None:
            answer = QMessageBox.question(
                self,
                "改用手动校正",
                message + "\n\n是否立即点击四个纸张角点进行手动校正？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                QTimer.singleShot(0, self.start_manual_corners)

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("页面已变化，已丢弃过期校正结果")
                return
            result = value
            if result is None:
                use_manual("自动校正没有找到可靠的纸张边界。")
                return
            if result.confidence < MIN_AUTOMATIC_PAPER_CONFIDENCE:
                use_manual(
                    f"自动候选置信度 {result.confidence:.2f}，低于可靠阈值 "
                    f"{MIN_AUTOMATIC_PAPER_CONFIDENCE:.2f}。"
                )
                return
            self.corrected_image = result.image
            self._invalidate_preprocess_results()
            self._clear_trace_state()
            self._apply_paper_calibration()
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": True,
                "confidence": result.confidence,
                "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
                "corners": result.corners,
                "target_aspect_ratio": ratio,
                "warnings": list(result.warnings),
            }
            self._update_scale_label()
            answer = QMessageBox.question(
                self,
                "确认校正结果",
                "自动校正已完成。当前校正结果是否满意？\n\n"
                "选择“否”将立即进入手动四角校正。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.No:
                QTimer.singleShot(0, self.start_manual_corners)
            else:
                self.statusBar().showMessage(
                    f"自动校正完成；置信度 {result.confidence:.2f}"
                )

        self._start_processing(operation, completed, "正在自动校正图片…")

    def _apply_trace_result(
        self,
        result: RasterTraceResult,
        *,
        started_at: datetime,
        duration: float,
        save_pdf_state: bool,
    ) -> None:
        self.binary_image = result.binary
        self.preprocess_stages = dict(result.stages)
        self._show_preprocess_stages(self.preprocess_stages)
        self._trace_paths = tuple(result.paths)
        self._trace_threshold = int(result.threshold)
        self._trace_foreground_pixels = int(result.foreground_pixels)
        self._trace_vertex_count = int(result.vertex_count)
        self.raw_lines = []
        self.lines = []
        self.geometry_report = None
        self.classification_report = None
        self.auxiliary_result = None
        self._reviewed_circles = []
        self.corrected_canvas.set_image(result.binary)
        self.detected_canvas.set_image(result.binary)
        self.tabs.setCurrentWidget(self.detected_canvas)
        self._run_started_at = started_at
        self._run_duration_seconds = duration
        self._last_warnings = tuple(result.warnings)
        if save_pdf_state:
            self._save_current_pdf_state()
        self._update_scale_label()
        self.statusBar().showMessage(
            f"完整拓印完成：{len(result.paths)} 个闭合边界，"
            f"{result.vertex_count} 个顶点，黑色像素 {result.foreground_pixels}"
        )

    def detect_and_clean(self) -> None:
        if self.corrected_image is None and not self._require_corrected():
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        source = self.corrected_image.copy()
        revision = self._state_revision
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()

        def operation(token, progress) -> object:
            return trace_image(
                source,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("页面已变化，已丢弃过期拓印结果")
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )

        self._start_processing(operation, completed, "正在完整拓印黑白图…")

    def review_layers(self) -> None:
        if self.binary_image is None:
            QMessageBox.warning(self, "尚无拓印图", "请先执行“完整拓印全部黑白线条”。")
            return
        dialog = TracePaintDialog(self.binary_image, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.edited_binary()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        revision = self._state_revision

        def operation(token, progress) -> object:
            paths = trace_binary(
                edited,
                cancellation_token=token,
                progress_callback=progress,
            )
            return RasterTraceResult(
                binary=edited,
                stages={
                    "灰度原样": edited.copy(),
                    "黑白拓印图": edited.copy(),
                },
                paths=paths,
                threshold=self._trace_threshold or 128,
                foreground_pixels=int((edited == 0).sum()),
                vertex_count=sum(len(path.points) for path in paths),
                warnings=(),
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )

        self._start_processing(operation, completed, "正在按修补结果重新拓印…")

    def _save_current_pdf_state(self) -> None:
        super()._save_current_pdf_state()
        if not self._native_pdf_mode:
            return
        state = self._pdf_page_states.get(self._current_pdf_page_index)
        if state is None:
            return
        state.update(
            {
                "binary_image": self.binary_image.copy()
                if self.binary_image is not None
                else None,
                "preprocess_stages": {
                    name: image.copy() for name, image in self.preprocess_stages.items()
                },
                "trace_paths": tuple(self._trace_paths),
                "trace_threshold": self._trace_threshold,
                "trace_foreground_pixels": self._trace_foreground_pixels,
                "trace_vertex_count": self._trace_vertex_count,
                "drawing_scale": self._drawing_scale(),
                "trace_color": self._trace_color(),
            }
        )

    def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
        super()._load_pdf_page(page_index, save_current=save_current)
        if not self._native_pdf_mode:
            return
        state = self._pdf_page_states.get(page_index, {})
        binary = state.get("binary_image")
        self.binary_image = binary.copy() if binary is not None else None
        self.preprocess_stages = {
            name: image.copy()
            for name, image in state.get("preprocess_stages", {}).items()
        }
        self._trace_paths = tuple(state.get("trace_paths", ()))
        self._trace_threshold = state.get("trace_threshold")
        self._trace_foreground_pixels = int(state.get("trace_foreground_pixels", 0))
        self._trace_vertex_count = int(state.get("trace_vertex_count", 0))
        if hasattr(self, "drawing_scale_spin"):
            self.drawing_scale_spin.blockSignals(True)
            self.drawing_scale_spin.setValue(int(round(state.get("drawing_scale", self._drawing_scale()))))
            self.drawing_scale_spin.blockSignals(False)
        if hasattr(self, "trace_color_combo"):
            color = int(state.get("trace_color", self._trace_color()))
            index = self.trace_color_combo.findData(color)
            if index >= 0:
                self.trace_color_combo.blockSignals(True)
                self.trace_color_combo.setCurrentIndex(index)
                self.trace_color_combo.blockSignals(False)
        if self.preprocess_stages:
            self._show_preprocess_stages(self.preprocess_stages)
        if self.binary_image is not None:
            self.corrected_canvas.set_image(self.binary_image)
            self.detected_canvas.set_image(self.binary_image)
            self.tabs.setCurrentWidget(self.detected_canvas)
        self._update_scale_label()

    def batch_vectorize_pdf(self) -> None:
        if not self._native_pdf_mode or self.current_path is None:
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        self._save_current_pdf_state()
        source_path = Path(self.current_path)
        page_count = self._pdf_page_count
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        drawing_scale = self._drawing_scale()
        trace_color = self._trace_color()

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                progress(
                    f"完整拓印第 {page_index + 1}/{page_count} 页",
                    page_index / max(page_count, 1),
                )
                image = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=PDF_VIEW_DPI,
                )
                result = trace_image(image, cancellation_token=token)
                results[page_index] = {
                    "raw_lines": [],
                    "lines": [],
                    "geometry_report": None,
                    "classification_report": None,
                    "auxiliary_result": None,
                    "last_warnings": tuple(result.warnings),
                    "run_started_at": started_at,
                    "run_duration_seconds": None,
                    "vector_shape": tuple(image.shape[:2]),
                    "binary_image": result.binary,
                    "preprocess_stages": result.stages,
                    "trace_paths": result.paths,
                    "trace_threshold": result.threshold,
                    "trace_foreground_pixels": result.foreground_pixels,
                    "trace_vertex_count": result.vertex_count,
                    "drawing_scale": drawing_scale,
                    "trace_color": trace_color,
                }
            progress("批量完整拓印完成", 1.0)
            return results

        def completed(value: object) -> None:
            results = value  # type: ignore[assignment]
            duration = time.perf_counter() - started
            for state in results.values():
                state["run_duration_seconds"] = duration
            self._pdf_page_states.update(results)
            self._load_pdf_page(self._current_pdf_page_index, save_current=False)
            QMessageBox.information(
                self,
                "批量拓印完成",
                f"已按与单页完全相同的 {PDF_VIEW_DPI} DPI 全分辨率流程处理 "
                f"{page_count} 页。没有降采样，也没有结构线抽象。",
            )

        self._start_processing(operation, completed, "正在批量完整拓印 PDF…")

    def _document_page_from_pdf_state(
        self,
        page_index: int,
        state: dict[str, Any],
    ) -> DocumentPage:
        page = super()._document_page_from_pdf_state(page_index, state)
        return replace(
            page,
            trace_paths=tuple(state.get("trace_paths", ())),
            drawing_scale=float(state.get("drawing_scale", self._drawing_scale())),
            trace_color=int(state.get("trace_color", self._trace_color())),
        )

    def _current_document_page(self) -> DocumentPage | None:
        page = super()._current_document_page()
        if page is None:
            return None
        return replace(
            page,
            trace_paths=tuple(self._trace_paths),
            drawing_scale=self._drawing_scale(),
            trace_color=self._trace_color(),
        )

    def document_pages_for_export(self):
        if self._document_queue:
            return iter(tuple(self._document_queue))
        if not self._native_pdf_mode or self.current_path is None:
            return iter(())
        self._save_current_pdf_state()
        source_path = Path(self.current_path)
        states = dict(self._pdf_page_states)
        sizes = dict(self._pdf_page_sizes_mm)
        count = self._pdf_page_count

        def pages():
            for page_index in range(count):
                state = states.get(page_index, {})
                yield DocumentPage(
                    page_number=page_index + 1,
                    raster=None,
                    page_size_mm=sizes[page_index],
                    lines=(),
                    vector_size_px=(
                        (int(state["vector_shape"][1]), int(state["vector_shape"][0]))
                        if state.get("vector_shape") is not None
                        else None
                    ),
                    label=f"{source_path.stem} - Page {page_index + 1}",
                    source_path=source_path,
                    source_page_index=page_index,
                    raster_dpi=PDF_VIEW_DPI,
                    trace_paths=tuple(state.get("trace_paths", ())),
                    drawing_scale=float(state.get("drawing_scale", self._drawing_scale())),
                    trace_color=int(state.get("trace_color", self._trace_color())),
                )

        return pages()

    def export_file(self) -> None:
        if self._document_queue or self._native_pdf_mode:
            _export_pdf_document(self)
            return
        export_from_window(self, circles=[])
