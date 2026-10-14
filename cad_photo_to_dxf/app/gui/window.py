from __future__ import annotations
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QWidget,
)
from app import __version__
from app.version import PRODUCT_NAME
from app.ocr.auxiliary_recognition import AuxiliaryRecognitionResult
from app.core.cancellation import CancellationToken
from app.core.structure import FinalStructure
from app.gui.image_canvas import ImageCanvas
from app.geometry.line_detect import LineSegment
from app.core.perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE, auto_correct, resolve_paper_aspect_ratio, resolve_paper_dimensions_mm, rotate_image, warp_perspective
from app.geometry.preprocess import PreprocessParams
from app.core.trace_types import TracePath
from app.core.scale_calibrator import ScaleCalibration, create_calibration
from app.gui.visual_acceptance_widget import VisualAcceptanceWidget
from app.gui.worker import ProcessingWorker

ProcessingOperation = Callable[
    [CancellationToken, Callable[[str, float], None]], object
]
UNSCALED_LABEL = "比例：未校准（1 px = 1 个无单位图形单位）"
SIDEBAR_MINIMUM_WIDTH = 500
SIDEBAR_WIDTH = 540


class MainWindow(QMainWindow):
    """Desktop window. Domain processing lives in ProductionProcessingService."""

    from app.gui.controls import build_controls as _build_controls
    from app.gui.document import _cache_file_matches, _cache_path_for_key, _current_trace_key, _load_pdf_page, _load_trace_source_for_current_page, _next_pdf_page, _on_pdf_page_changed, _previous_pdf_page, _processing_pdf_dpi, _restore_cached_trace_for_page, _save_current_pdf_state, _set_pdf_controls_enabled, _set_single_image_state, _source_key, _store_current_trace, import_image
    from app.gui.processing import _apply_trace_result, _processing_config, _stage_text, batch_vectorize_pdf, detect_and_clean
    from app.gui.review_actions import _preview_shape, _refresh_visual_acceptance, _replace_final_structure_texts, _scaled_for_preview, _visual_acceptance_source, review_layers, review_ocr_texts, verify_current_trace

    from app.gui.page_export import export_current_page_from_window as export_file, export_processed_pages_from_window as export_processed_pages

    def __init__(self) -> None:
        self._librecad_font_install_report = None
        self._dirty_trace_keys: set[object] = set()
        self._ocr_texts = ()
        self._signature_regions = ()
        self._cad_preview_binary = None
        self._final_structure: FinalStructure | None = None
        self._preview_structure_id: str | None = None
        self._trace_cache_tempdir = TemporaryDirectory(prefix="image-to-cad-trace-")
        self._trace_cache_by_key: dict[object, Path] = {}
        self._trace_paths: tuple[TracePath, ...] = ()
        self._trace_threshold: int | None = None
        self._trace_foreground_pixels = 0
        self._trace_vertex_count = 0
        self._reviewed_circles = []
        QMainWindow.__init__(self)
        self.setWindowTitle(f"{PRODUCT_NAME} {__version__}")
        self.resize(1450, 900)
        self.original_image: np.ndarray | None = None
        self.corrected_image: np.ndarray | None = None
        self.binary_image: np.ndarray | None = None
        self.raw_lines: list[LineSegment] = []
        self.lines: list[LineSegment] = []
        self.preprocess_stages: dict[str, np.ndarray] = {}
        self.auxiliary_result: AuxiliaryRecognitionResult | None = None
        self.calibration: ScaleCalibration | None = None
        self.current_path: Path | None = None
        self.selection_mode: str | None = None
        self.selected_points: list[tuple[float, float]] = []
        self._worker_thread: QThread | None = None
        self._worker: ProcessingWorker | None = None
        self._cancellation_token: CancellationToken | None = None
        self._task_success: Callable[[object], None] | None = None
        self._state_revision = 0
        self.tabs = QTabWidget()
        self.original_canvas = ImageCanvas()
        self.corrected_canvas = ImageCanvas()
        self.detected_canvas = ImageCanvas()
        self.preprocess_tabs = QTabWidget()
        self.preprocess_canvases: dict[str, ImageCanvas] = {}
        self.tabs.addTab(self.original_canvas, "SOURCE REFERENCE / 原图")
        self.tabs.addTab(self.corrected_canvas, "校正 / 黑白图")
        self.tabs.addTab(self.preprocess_tabs, "预处理阶段")
        self.tabs.addTab(self.detected_canvas, "识别线条")
        self.original_canvas.point_clicked.connect(self._on_original_point)
        self.corrected_canvas.point_clicked.connect(self._on_corrected_point)
        controls = self._build_controls()
        splitter = QSplitter()
        splitter.addWidget(controls)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 1100])
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("请先导入 JPG/PNG 图纸照片")
        self._build_menu()
        self._perspective_metadata: dict[str, object] | None = None
        self._run_started_at: datetime | None = None
        self._run_duration_seconds: float | None = None
        self._last_preprocess_scale = 1.0
        self._last_preprocess_params = PreprocessParams()
        self._last_warnings: tuple[str, ...] = ()
        self._dwg_converter_path: Path | None = None
        self._current_pdf_page: int | None = None
        self._native_pdf_mode = False
        self._pdf_page_count = 1
        self._current_pdf_page_index = 0
        self._pdf_page_states: dict[int, dict[str, Any]] = {}
        self._pdf_page_sizes_mm: dict[int, tuple[float, float]] = {}
        self.setWindowTitle(f"{PRODUCT_NAME} {__version__}")
        self.statusBar().showMessage("请先导入 JPG、PNG 或扫描 PDF")
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)
        self._set_pdf_controls_enabled(False)
        self._update_scale_label()
        self._update_scale_label()
        splitter = self.centralWidget()
        if isinstance(splitter, QSplitter):
            splitter.setCollapsible(0, False)
            controls = splitter.widget(0)
            if controls is not None:
                controls.setMinimumWidth(SIDEBAR_MINIMUM_WIDTH)
            splitter.setSizes([SIDEBAR_WIDTH, max(860, self.width() - SIDEBAR_WIDTH)])
        self.statusBar().showMessage(
            "可处理当前页或全部页面；扫描件会自动清理纸张底色和破损纹理"
        )
        self.visual_acceptance = VisualAcceptanceWidget(self)
        self.tabs.addTab(self.visual_acceptance, "视觉验收")
        self.tabs.currentChanged.connect(lambda _index: self._refresh_visual_acceptance())

    def _active_canvas(self) -> ImageCanvas | None:
        current = self.tabs.currentWidget()
        if isinstance(current, ImageCanvas):
            return current
        if current is self.preprocess_tabs:
            preprocess_current = self.preprocess_tabs.currentWidget()
            if isinstance(preprocess_current, ImageCanvas):
                return preprocess_current
        return None

    def _actual_size(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.actual_size()

    def _apply_paper_calibration(self) -> None:
        if self._native_pdf_mode:
            return
        if self.corrected_image is None:
            self.calibration = None
            return
        paper_size, orientation = self.paper_size_combo.currentData()
        dimensions = resolve_paper_dimensions_mm(
            paper_size,
            orientation=orientation,
            observed_landscape=self.corrected_image.shape[1]
            >= self.corrected_image.shape[0],
        )
        if dimensions is None:
            self.calibration = None
            self.info_label.setText("坐标：未校准的无单位像素坐标")
            return
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, self.corrected_image.shape[1] - 1)), 0.0),
            dimensions[0],
        )
        self.info_label.setText(
            f"坐标：纸面毫米 {self.calibration.mm_per_pixel:.6f} mm/px；不是工程模型尺寸"
        )
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("导入图片", self)
        open_action.triggered.connect(self.import_image)
        export_action = QAction("导出 DXF", self)
        export_action.triggered.connect(self.export_file)
        file_menu.addAction(open_action)
        file_menu.addAction(export_action)
        for menu_action in self.menuBar().actions():
            menu = menu_action.menu()
            if menu is None or menu.title() != "文件":
                continue
            for action in menu.actions():
                if action.text() == "导入图片":
                    action.setText("导入图片 / 扫描 PDF")
                    action.setShortcut("Ctrl+O")
                elif action.text() == "导出 DXF":
                    action.setText("导出同一 CAD（DWG / DXF）")
                    action.setShortcut("Ctrl+Shift+S")
        view_menu = self.menuBar().addMenu("视图")
        zoom_in = QAction("放大", self)
        zoom_in.setShortcut("Ctrl++")
        zoom_in.triggered.connect(self._zoom_in)
        zoom_out = QAction("缩小", self)
        zoom_out.setShortcut("Ctrl+-")
        zoom_out.triggered.connect(self._zoom_out)
        fit_action = QAction("适应窗口", self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.triggered.connect(self._fit_view)
        actual_action = QAction("100%", self)
        actual_action.setShortcut("Ctrl+1")
        actual_action.triggered.connect(self._actual_size)
        view_menu.addActions((zoom_in, zoom_out, fit_action, actual_action))

    def _button(self, text: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _clear_preprocess_tabs(self) -> None:
        self.preprocess_canvases.clear()
        while self.preprocess_tabs.count():
            widget = self.preprocess_tabs.widget(0)
            self.preprocess_tabs.removeTab(0)
            widget.deleteLater()

    def _clear_trace_state(self) -> None:
        self._trace_paths = ()
        self._trace_threshold = None
        self._trace_foreground_pixels = 0
        self._trace_vertex_count = 0
        self._ocr_texts = ()
        self._signature_regions = ()
        self._cad_preview_binary = None
        self._final_structure = None
        self._preview_structure_id = None
        widget = getattr(self, "visual_acceptance", None)
        if widget is not None:
            widget.clear_result()

    def _drawing_scale(self) -> float:
        spin = getattr(self, "drawing_scale_spin", None)
        return float(spin.value()) if spin is not None else 1.0

    def _export_drawing_multiplier(self) -> float:
        if self._has_explicit_model_calibration():
            return 1.0
        if self.calibration is None:
            return 1.0
        return self._drawing_scale()

    def _fit_view(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.fit_image()

    def _has_explicit_model_calibration(self) -> bool:
        if self._native_pdf_mode or self.calibration is None:
            return False
        try:
            _source, coordinate_space, _warnings = self._calibration_semantics()
        except Exception:
            return False
        return coordinate_space == "model_mm"

    def _invalidate_line_results(self, *_args: object) -> None:
        self._state_revision += 1
        self.raw_lines = []
        self.lines = []
        self.auxiliary_result = None
        self.detected_canvas.set_image(None)

    def _invalidate_preprocess_results(self, *_args: object) -> None:
        self._state_revision += 1
        self.binary_image = None
        self.preprocess_stages = {}
        self._clear_preprocess_tabs()
        self._invalidate_line_results()
        if self.corrected_image is not None:
            self.corrected_canvas.set_image(self.corrected_image)

    def _is_processing(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _ocr_enabled(self) -> bool:
        checkbox = getattr(self, "ocr_before_trace_checkbox", None)
        return bool(checkbox is None or checkbox.isChecked())

    def _on_corrected_point(self, x: float, y: float) -> None:
        if self.selection_mode != "scale":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.corrected_canvas.add_point(point, str(len(self.selected_points)), Qt.blue)
        if len(self.selected_points) != 2:
            return
        self.corrected_canvas.add_line(
            self.selected_points[0], self.selected_points[1], Qt.blue
        )
        self.corrected_canvas.set_selection_enabled(False)
        length, accepted = QInputDialog.getDouble(
            self,
            "输入实际长度",
            "这两个点之间的工程模型长度（mm）：",
            12000.0,
            0.001,
            1000000000.0,
            3,
        )
        self.selection_mode = None
        if not accepted:
            self.statusBar().showMessage("已取消模型尺寸校准")
            return
        try:
            calibration = create_calibration(self.selected_points, length)
        except Exception as exc:
            QMessageBox.critical(self, "校准失败", str(exc))
            return
        self.calibration = calibration
        self.info_label.setText(
            f"坐标：工程模型毫米 {calibration.mm_per_pixel:.6f} mm/px；{calibration.pixel_distance:.2f}px = {length:.3f}mm"
        )
        self.statusBar().showMessage("工程模型尺寸校准完成")
        self._update_scale_label()

    def _on_original_point(self, x: float, y: float) -> None:
        if self.selection_mode != "corners":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.original_canvas.add_point(point, str(len(self.selected_points)))
        if len(self.selected_points) != 4:
            return
        self.original_canvas.set_selection_enabled(False)
        self.selection_mode = None
        source = self.original_image.copy()
        points = list(self.selected_points)
        ratio = self._target_aspect_ratio()
        revision = self._state_revision

        def operation(
            token: CancellationToken, progress: Callable[[str, float], None]
        ) -> object:
            token.checkpoint()
            progress("四角验证", 0.2)
            image = warp_perspective(source, points, ratio)
            token.checkpoint()
            progress("手动透视校正", 1.0)
            return image

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            self.corrected_image = value
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self._perspective_metadata = {
                "applied": True,
                "automatic": False,
                "confidence": 1.0,
                "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
                "corners": points,
                "target_aspect_ratio": ratio,
                "warnings": [],
            }
            self.statusBar().showMessage("手动四角透视校正完成")

        self._start_processing(operation, completed, "正在执行手动透视校正…")

    @Slot()
    def _on_processing_cancelled(self) -> None:
        self._task_success = None
        self._cancellation_token = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("已取消")
        self.statusBar().showMessage("处理已取消；原生 OpenCV 调用会在返回后响应取消")

    @Slot(str)
    def _on_processing_failed(self, message: str) -> None:
        self._task_success = None
        self._cancellation_token = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("失败")
        QMessageBox.critical(self, "处理失败", message)
        self.statusBar().showMessage(f"处理失败：{message}")

    @Slot(str, float)
    def _on_processing_progress(self, stage: str, fraction: float) -> None:
        self.progress_bar.setValue(int(round(fraction * 100)))
        self.progress_bar.setFormat(f"{stage} %p%")

    @Slot(object)
    def _on_processing_succeeded(self, result: object) -> None:
        callback = self._task_success
        self._task_success = None
        self._cancellation_token = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("完成")
        if callback is not None:
            callback(result)

    @Slot()
    def _on_worker_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None

    def _paper_setting_changed(self, *_args: object) -> None:
        if self.original_image is None:
            return
        self.corrected_image = None
        self.calibration = None
        self._invalidate_preprocess_results()
        self.corrected_canvas.set_image(None)
        self.info_label.setText("纸张规格已变化，请重新执行透视校正")
        self.statusBar().showMessage("纸张规格已变化，请重新校正、预处理和识别")

    @staticmethod
    def _remove_from_layout(widget: QWidget | None) -> None:
        if widget is None:
            return
        parent = widget.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(widget)

    def _require_corrected(self) -> bool:
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "需要确认纸张透视",
            "请先执行自动纸张校正，或手工确认四个纸张角点。\n\n当前版本不再把未经校正的原图静默视为已校正图。",
        )
        self.statusBar().showMessage("已阻止处理：尚未确认纸张透视")
        return False

    def _require_original(self) -> bool:
        if self.original_image is None:
            QMessageBox.warning(self, "缺少图片", "请先导入图纸照片。")
            return False
        return True

    def _scale_changed(self, _value: int) -> None:
        self._update_scale_label()
        if self._native_pdf_mode:
            self._save_current_pdf_state()

    def _show_preprocess_stages(self, stages: dict[str, np.ndarray]) -> None:
        self._clear_preprocess_tabs()
        for stage_name, stage_image in stages.items():
            canvas = ImageCanvas()
            canvas.set_image(stage_image)
            self.preprocess_canvases[stage_name] = canvas
            self.preprocess_tabs.addTab(canvas, stage_name)

    def _start_processing(
        self,
        operation: ProcessingOperation,
        on_success: Callable[[object], None],
        message: str,
    ) -> None:
        if self._is_processing():
            QMessageBox.information(
                self, "正在处理", "请等待当前任务完成，或点击取消。"
            )
            return
        token = CancellationToken()
        thread = QThread(self)
        worker = ProcessingWorker(operation, token)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_processing_succeeded)
        worker.failed.connect(self._on_processing_failed)
        worker.cancelled.connect(self._on_processing_cancelled)
        worker.progress.connect(self._on_processing_progress)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._worker_thread = thread
        self._worker = worker
        self._cancellation_token = token
        self._task_success = on_success
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(message)
        self.statusBar().showMessage(message)
        thread.start()

    def _target_aspect_ratio(self) -> float | None:
        paper_size, orientation = self.paper_size_combo.currentData()
        return resolve_paper_aspect_ratio(
            paper_size,
            orientation=orientation,
            observed_landscape=self.original_image.shape[1]
            >= self.original_image.shape[0]
            if self.original_image is not None
            else None,
        )

    def _trace_color(self) -> int:
        return 7

    def _update_scale_label(self) -> None:
        label = getattr(self, "scale_result_label", None)
        if label is None:
            return
        if self.calibration is None:
            label.setText("输出比例 1:1；尚未标定纸面或模型尺寸")
            return
        if self._has_explicit_model_calibration():
            label.setText(
                f"已知尺寸标定：{self.calibration.mm_per_pixel:.6f} 模型 mm/px；不会再叠加图纸比例"
            )
            self.info_label.setText(
                f"工程模型坐标：{self.calibration.mm_per_pixel:.6f} mm/px；{self.calibration.pixel_distance:.2f} px = {self.calibration.actual_length_mm:.3f} mm"
            )
            return
        ratio = self._drawing_scale()
        model_mm_per_pixel = self.calibration.mm_per_pixel * ratio
        label.setText(
            f"输出比例 1:{int(ratio)}；{model_mm_per_pixel:.6f} 模型 mm/px （纸面 {self.calibration.mm_per_pixel:.6f} mm/px）"
        )
        self.info_label.setText(
            f"输出比例 1:{int(ratio)}；模型坐标 {model_mm_per_pixel:.6f} mm/px"
        )

    def _zoom_in(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.zoom_in()

    def _zoom_out(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.zoom_out()

    def auto_perspective(self) -> None:
        if not self._require_original():
            return
        source = self.original_image.copy()
        ratio = self._target_aspect_ratio()
        revision = self._state_revision

        def operation(
            token: CancellationToken, progress: Callable[[str, float], None]
        ) -> object:
            token.checkpoint()
            progress("自动寻找纸张边界", 0.15)
            result = auto_correct(source, ratio)
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
                    f"自动候选置信度 {result.confidence:.2f}，低于可靠阈值 {MIN_AUTOMATIC_PAPER_CONFIDENCE:.2f}。"
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
                "自动校正已完成。当前校正结果是否满意？\n\n选择“否”将立即进入手动四角校正。",
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

    def cancel_processing(self) -> None:
        if self._cancellation_token is None:
            return
        self._cancellation_token.cancel()
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("正在取消…")
        self.statusBar().showMessage("已请求取消，将在当前 OpenCV/OCR 调用返回后停止")

    def closeEvent(self, event) -> None:
        if self._is_processing():
            self.cancel_processing()
            event.ignore()
            QMessageBox.information(
                self,
                "正在停止任务",
                "已请求取消。当前 OpenCV/OCR 调用返回后即可关闭窗口。",
            )
            return
        QMainWindow.closeEvent(self, event)
        if event.isAccepted():
            self._trace_cache_tempdir.cleanup()

    def correct_image(self) -> None:
        if self._native_pdf_mode:
            self.corrected_image = (
                self.original_image.copy() if self.original_image is not None else None
            )
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self.statusBar().showMessage("PDF 页面无需透视校正，可直接完整拓印")
            return
        self.auto_perspective()

    def rotate_corrected(self, degrees: int) -> None:
        revision_before = self._state_revision
        metadata_before = deepcopy(self._perspective_metadata)
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        if not self._require_corrected():
            return
        self.corrected_image = rotate_image(self.corrected_image, degrees)
        self._invalidate_preprocess_results()
        self.calibration = None
        self.corrected_canvas.set_image(self.corrected_image)
        self.detected_canvas.set_image(None)
        self.statusBar().showMessage(f"已旋转 {degrees}°，请重新预处理和识别")
        if self.corrected_image is not None and self._perspective_metadata is not None:
            rotations = list(self._perspective_metadata.get("rotations", []))
            rotations.append(int(degrees))
            self._perspective_metadata["rotations"] = rotations
        if self._state_revision == revision_before:
            self._perspective_metadata = metadata_before
        elif self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def start_manual_corners(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        if not self._require_original():
            return
        self.selection_mode = "corners"
        self.selected_points = []
        self.original_canvas.clear_overlays()
        self.original_canvas.set_selection_enabled(True)
        self.tabs.setCurrentWidget(self.original_canvas)
        self.statusBar().showMessage("请在原图上点击纸张的四个角，顺序不限")

    def start_scale_calibration(self) -> None:
        if not self._require_corrected():
            return
        self.corrected_canvas.set_image(self.corrected_image)
        self.corrected_canvas.clear_overlays()
        self.selection_mode = "scale"
        self.selected_points = []
        self.corrected_canvas.set_selection_enabled(True)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        self.statusBar().showMessage("请在校正图上点击已知尺寸线段的两个端点")

    def _calibration_semantics(self) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        if self.calibration is None:
            warnings.append("未校准尺寸；导出坐标仍为像素图形单位。")
            return ("uncalibrated", "pixel", warnings)
        paper_size, orientation = self.paper_size_combo.currentData()
        dimensions = resolve_paper_dimensions_mm(
            paper_size,
            orientation=orientation,
            observed_landscape=self.corrected_image.shape[1]
            >= self.corrected_image.shape[0],
        )
        expected_end = float(max(1, self.corrected_image.shape[1] - 1))
        paper_derived = (
            dimensions is not None
            and abs(self.calibration.point1[0]) < 1e-06
            and (abs(self.calibration.point1[1]) < 1e-06)
            and (abs(self.calibration.point2[0] - expected_end) < 0.001)
            and (abs(self.calibration.point2[1]) < 1e-06)
        )
        if paper_derived:
            warnings.append(
                "导出坐标为纸面毫米（paper_mm），不是原始设计模型尺寸；恢复 model_mm 必须用图纸比例或已知实际尺寸重新校准。"
            )
            return ("paper_dimensions", "paper_mm", warnings)
        return ("explicit", "model_mm", warnings)
