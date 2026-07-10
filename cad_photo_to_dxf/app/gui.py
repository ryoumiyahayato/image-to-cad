from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dxf_exporter import export_dxf
from . import __version__
from .cancellation import CancellationToken, ProcessingCancelled
from .auxiliary_recognition import AuxiliaryRecognitionResult, recognize_auxiliary
from .geometry_cleaner import GeometryCleanParams, GeometryCleanReport, clean_geometry_with_report
from .image_loader import load_image
from .layer_classifier import ClassificationReport, classify_layers_with_report
from .line_detect import LineDetectionParams, LineSegment, detect_lines, render_line_preview
from .perspective import (
    auto_correct,
    resolve_paper_aspect_ratio,
    resolve_paper_dimensions_mm,
    rotate_image,
    warp_perspective,
)
from .preprocess import PreprocessParams, PreprocessResult, preprocess_image_with_stages
from .reporting import build_lineage, write_json_report
from .scale_calibrator import ScaleCalibration, create_calibration


def cv_to_qpixmap(image: np.ndarray) -> QPixmap:
    if image.ndim == 2:
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    height, width, channels = rgb.shape
    qimage = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class ProcessingWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, float)

    def __init__(
        self,
        operation: Callable[[CancellationToken, Callable[[str, float], None]], object],
        token: CancellationToken,
    ) -> None:
        super().__init__()
        self._operation = operation
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self._token, self._emit_progress)
            self._token.checkpoint()
        except ProcessingCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)

    def _emit_progress(self, stage: str, fraction: float) -> None:
        self.progress.emit(stage, max(0.0, min(1.0, float(fraction))))


class ImageCanvas(QGraphicsView):
    point_clicked = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._overlay_items: list[object] = []
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.darkGray)
        self._selection_enabled = False

    def set_image(self, image: np.ndarray | None) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._pixmap_item = None
        if image is None:
            return
        pixmap = cv_to_qpixmap(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self.resetTransform()
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def clear_overlays(self) -> None:
        for item in self._overlay_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._overlay_items.clear()

    def add_point(self, point: tuple[float, float], label: str = "", color: Qt.GlobalColor = Qt.red) -> None:
        x, y = point
        pen = QPen(color, 3)
        ellipse = self._scene.addEllipse(x - 5, y - 5, 10, 10, pen)
        self._overlay_items.append(ellipse)
        if label:
            text = self._scene.addSimpleText(label)
            text.setBrush(color)
            text.setPos(x + 7, y + 7)
            self._overlay_items.append(text)

    def add_line(self, start: tuple[float, float], end: tuple[float, float], color: Qt.GlobalColor = Qt.red) -> None:
        item = self._scene.addLine(start[0], start[1], end[0], end[1], QPen(color, 2))
        self._overlay_items.append(item)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.angleDelta().y() == 0:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._selection_enabled and event.button() == Qt.LeftButton and self._pixmap_item is not None:
            scene_point = self.mapToScene(event.position().toPoint())
            image_rect = self._pixmap_item.boundingRect()
            if image_rect.contains(scene_point):
                self.point_clicked.emit(scene_point.x(), scene_point.y())
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._pixmap_item is not None and self.transform().m11() == 1.0:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"纸质 CAD 图纸照片转可编辑 DXF — v{__version__}")
        self.resize(1450, 900)

        self.original_image: np.ndarray | None = None
        self.corrected_image: np.ndarray | None = None
        self.binary_image: np.ndarray | None = None
        self.raw_lines: list[LineSegment] = []
        self.lines: list[LineSegment] = []
        self.preprocess_stages: dict[str, np.ndarray] = {}
        self.geometry_report: GeometryCleanReport | None = None
        self.classification_report: ClassificationReport | None = None
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
        self.tabs.addTab(self.original_canvas, "原图")
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

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("导入图片", self)
        open_action.triggered.connect(self.import_image)
        export_action = QAction("导出 DXF", self)
        export_action.triggered.connect(self.export_file)
        file_menu.addAction(open_action)
        file_menu.addAction(export_action)

    def _button(self, text: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _build_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self._button("1. 导入图片", self.import_image))
        layout.addWidget(self._button("2. 自动识别纸张并校正", self.auto_perspective))
        layout.addWidget(self._button("手动点击四角并校正", self.start_manual_corners))

        paper_group = QGroupBox("纸张真实比例")
        paper_form = QFormLayout(paper_group)
        self.paper_size_combo = QComboBox()
        self.paper_size_combo.addItem("未知（仅结构模式）", (None, "auto"))
        for size in ("A0", "A1", "A2", "A3", "A4", "LETTER", "LEGAL"):
            self.paper_size_combo.addItem(f"{size} 横向", (size, "landscape"))
            self.paper_size_combo.addItem(f"{size} 纵向", (size, "portrait"))
        paper_form.addRow("纸张规格", self.paper_size_combo)
        layout.addWidget(paper_group)

        rotate_row = QHBoxLayout()
        rotate_row.addWidget(self._button("旋转 90°", lambda: self.rotate_corrected(90)))
        rotate_row.addWidget(self._button("180°", lambda: self.rotate_corrected(180)))
        rotate_row.addWidget(self._button("270°", lambda: self.rotate_corrected(270)))
        layout.addLayout(rotate_row)
        layout.addWidget(self._button("3. 图像预处理", self.preprocess))
        layout.addWidget(self._button("4. 识别并清理线条", self.detect_and_clean))
        layout.addWidget(self._button("5. 点击两点校准比例", self.start_scale_calibration))
        layout.addWidget(self._button("6. 导出可编辑 DXF", self.export_file))
        self.cancel_button = self._button("取消当前处理", self.cancel_processing)
        self.cancel_button.setEnabled(False)
        layout.addWidget(self.cancel_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("空闲")
        layout.addWidget(self.progress_bar)

        params_group = QGroupBox("参数")
        form = QFormLayout(params_group)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 40)
        self.threshold_spin.setValue(12)
        form.addRow("二值化强度", self.threshold_spin)

        self.min_length_spin = QSpinBox()
        self.min_length_spin.setRange(5, 1000)
        self.min_length_spin.setValue(35)
        form.addRow("最小线段长度(px)", self.min_length_spin)

        self.bridge_spin = QDoubleSpinBox()
        self.bridge_spin.setRange(0, 100)
        self.bridge_spin.setValue(12)
        form.addRow("最大断线连接距离", self.bridge_spin)

        self.snap_spin = QDoubleSpinBox()
        self.snap_spin.setRange(0, 100)
        self.snap_spin.setValue(6)
        form.addRow("端点吸附距离", self.snap_spin)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(0, 15)
        self.angle_spin.setDecimals(1)
        self.angle_spin.setValue(3)
        form.addRow("水平/垂直角度容差", self.angle_spin)

        self.keep_hatch = QCheckBox("保留填充线并放入 HATCH 层")
        self.keep_hatch.setChecked(True)
        form.addRow(self.keep_hatch)
        self.enable_auxiliary = QCheckBox("辅助识别圆和矩形符号（仅报告）")
        self.enable_auxiliary.setChecked(True)
        form.addRow(self.enable_auxiliary)
        self.enable_ocr = QCheckBox("启用可选 OCR（仅报告）")
        self.enable_ocr.setChecked(False)
        form.addRow(self.enable_ocr)
        layout.addWidget(params_group)

        self.info_label = QLabel("比例：未校准（导出时 1 px = 1 mm 图形单位）")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.paper_size_combo.currentIndexChanged.connect(self._paper_setting_changed)
        self.threshold_spin.valueChanged.connect(self._invalidate_preprocess_results)
        self.min_length_spin.valueChanged.connect(self._invalidate_line_results)
        self.bridge_spin.valueChanged.connect(self._invalidate_line_results)
        self.snap_spin.valueChanged.connect(self._invalidate_line_results)
        self.angle_spin.valueChanged.connect(self._invalidate_line_results)
        self.keep_hatch.toggled.connect(self._invalidate_line_results)
        self.enable_auxiliary.toggled.connect(self._invalidate_line_results)
        self.enable_ocr.toggled.connect(self._invalidate_line_results)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setMinimumWidth(300)
        return scroll

    def _target_aspect_ratio(self) -> float | None:
        paper_size, orientation = self.paper_size_combo.currentData()
        return resolve_paper_aspect_ratio(
            paper_size,
            orientation=orientation,
            observed_landscape=(
                self.original_image.shape[1] >= self.original_image.shape[0]
                if self.original_image is not None
                else None
            ),
        )

    def _apply_paper_calibration(self) -> None:
        if self.corrected_image is None:
            self.calibration = None
            return
        paper_size, orientation = self.paper_size_combo.currentData()
        dimensions = resolve_paper_dimensions_mm(
            paper_size,
            orientation=orientation,
            observed_landscape=self.corrected_image.shape[1] >= self.corrected_image.shape[0],
        )
        if dimensions is None:
            self.calibration = None
            self.info_label.setText("比例：未校准（导出时 1 px = 1 mm 图形单位）")
            return
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, self.corrected_image.shape[1] - 1)), 0.0),
            dimensions[0],
        )
        self.info_label.setText(
            f"比例：由纸张外边界推导 {self.calibration.mm_per_pixel:.6f} mm/px；"
            "请确保角点位于纸张外缘，并用已知尺寸复核"
        )

    def _clear_preprocess_tabs(self) -> None:
        self.preprocess_canvases.clear()
        while self.preprocess_tabs.count():
            widget = self.preprocess_tabs.widget(0)
            self.preprocess_tabs.removeTab(0)
            widget.deleteLater()

    def _show_preprocess_stages(self, stages: dict[str, np.ndarray]) -> None:
        self._clear_preprocess_tabs()
        for stage_name, stage_image in stages.items():
            canvas = ImageCanvas()
            canvas.set_image(stage_image)
            self.preprocess_canvases[stage_name] = canvas
            self.preprocess_tabs.addTab(canvas, stage_name)

    def _invalidate_line_results(self, *_args: object) -> None:
        self._state_revision += 1
        self.raw_lines = []
        self.lines = []
        self.geometry_report = None
        self.classification_report = None
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

    def _paper_setting_changed(self, *_args: object) -> None:
        if self.original_image is None:
            return
        self.corrected_image = None
        self.calibration = None
        self._invalidate_preprocess_results()
        self.corrected_canvas.set_image(None)
        self.info_label.setText("比例：纸张规格已变化，请重新执行透视校正")
        self.statusBar().showMessage("纸张规格已变化，请重新校正、预处理和识别")

    def _is_processing(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _start_processing(
        self,
        operation: Callable[[CancellationToken, Callable[[str, float], None]], object],
        on_success: Callable[[object], None],
        message: str,
    ) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成，或点击取消。")
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

    @Slot(str)
    def _on_processing_failed(self, message: str) -> None:
        self._task_success = None
        self._cancellation_token = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("失败")
        QMessageBox.critical(self, "处理失败", message)
        self.statusBar().showMessage(f"处理失败：{message}")

    @Slot()
    def _on_processing_cancelled(self) -> None:
        self._task_success = None
        self._cancellation_token = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("已取消")
        self.statusBar().showMessage("处理已取消；原生 OpenCV 调用会在返回后响应取消")

    @Slot(str, float)
    def _on_processing_progress(self, stage: str, fraction: float) -> None:
        self.progress_bar.setValue(int(round(fraction * 100)))
        self.progress_bar.setFormat(f"{stage} %p%")

    @Slot()
    def _on_worker_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None

    def cancel_processing(self) -> None:
        if self._cancellation_token is None:
            return
        self._cancellation_token.cancel()
        self.cancel_button.setEnabled(False)
        self.progress_bar.setFormat("正在取消…")
        self.statusBar().showMessage("已请求取消，将在当前 OpenCV/OCR 调用返回后停止")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._is_processing():
            self.cancel_processing()
            event.ignore()
            QMessageBox.information(
                self,
                "正在停止任务",
                "已请求取消。当前 OpenCV/OCR 调用返回后即可关闭窗口。",
            )
            return
        super().closeEvent(event)

    def _require_original(self) -> bool:
        if self.original_image is None:
            QMessageBox.warning(self, "缺少图片", "请先导入图纸照片。")
            return False
        return True

    def _require_corrected(self) -> bool:
        if self.corrected_image is None:
            if not self._require_original():
                return False
            self.corrected_image = self.original_image.copy()
            self.corrected_canvas.set_image(self.corrected_image)
        return True

    def import_image(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图纸照片",
            str(Path.home()),
            "Images (*.jpg *.jpeg *.png)",
        )
        if not path:
            return
        try:
            image = load_image(path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self.current_path = Path(path)
        self.original_image = image
        self.corrected_image = None
        self.binary_image = None
        self.raw_lines = []
        self.lines = []
        self.preprocess_stages = {}
        self.geometry_report = None
        self.classification_report = None
        self.auxiliary_result = None
        self.calibration = None
        self._state_revision += 1
        self._clear_preprocess_tabs()
        self.original_canvas.set_image(image)
        self.corrected_canvas.set_image(None)
        self.detected_canvas.set_image(None)
        self.info_label.setText("比例：未校准（导出时 1 px = 1 mm 图形单位）")
        self.tabs.setCurrentWidget(self.original_canvas)
        self.statusBar().showMessage(f"已导入：{self.current_path.name}")

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
            progress("纸张边界识别", 0.15)
            result = auto_correct(source, ratio)
            token.checkpoint()
            progress("透视校正", 1.0)
            return result

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的校正结果")
                return
            result = value
            if result is None:
                QMessageBox.information(
                    self,
                    "未识别纸张边界",
                    "自动识别失败。请使用“手动点击四角并校正”，四点顺序不限。",
                )
                return
            self.corrected_image = result.image
            self._invalidate_preprocess_results()
            self._apply_paper_calibration()
            self.original_canvas.clear_overlays()
            for index, point in enumerate(result.corners, start=1):
                self.original_canvas.add_point(tuple(point), str(index))
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            message = f"自动透视校正完成；置信度 {result.confidence:.2f}"
            if result.warnings:
                message += f"；警告 {len(result.warnings)} 项"
            self.statusBar().showMessage(message)

        self._start_processing(operation, completed, "正在识别纸张并校正…")

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

    def _on_original_point(self, x: float, y: float) -> None:
        if self.selection_mode != "corners":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.original_canvas.add_point(point, str(len(self.selected_points)))
        if len(self.selected_points) == 4:
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
                self.statusBar().showMessage("手动四角透视校正完成")

            self._start_processing(operation, completed, "正在执行手动透视校正…")

    def rotate_corrected(self, degrees: int) -> None:
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

    def preprocess(self) -> None:
        if not self._require_corrected():
            return
        params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        source = self.corrected_image.copy()
        revision = self._state_revision

        def operation(
            token: CancellationToken, progress: Callable[[str, float], None]
        ) -> object:
            return preprocess_image_with_stages(
                source,
                params,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的预处理结果")
                return
            result: PreprocessResult = value
            self.binary_image = result.image
            self.preprocess_stages = result.stages
            self._invalidate_line_results()
            self.corrected_canvas.set_image(self.binary_image)
            self._show_preprocess_stages(result.stages)
            self.tabs.setCurrentWidget(self.preprocess_tabs)
            self.statusBar().showMessage("逐算子预处理完成，可在“预处理阶段”页逐项检查")

        self._start_processing(operation, completed, "正在执行图像预处理…")

    def detect_and_clean(self) -> None:
        if not self._require_corrected():
            return
        detection = LineDetectionParams(
            min_line_length=self.min_length_spin.value(),
            max_line_gap=max(2, int(round(self.bridge_spin.value()))),
        )
        cleaning = GeometryCleanParams(
            snap_distance=self.snap_spin.value(),
            max_bridge_gap=self.bridge_spin.value(),
            angle_tolerance=self.angle_spin.value(),
            min_line_length=max(5.0, self.min_length_spin.value() * 0.45),
        )
        existing_binary = self.binary_image.copy() if self.binary_image is not None else None
        corrected = self.corrected_image.copy()
        preprocess_params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        preserve_hatch = self.keep_hatch.isChecked()
        enable_auxiliary = self.enable_auxiliary.isChecked() or self.enable_ocr.isChecked()
        enable_ocr = self.enable_ocr.isChecked()
        revision = self._state_revision

        def operation(
            token: CancellationToken, progress: Callable[[str, float], None]
        ) -> object:
            stages: dict[str, np.ndarray] = {}
            if existing_binary is None:
                preprocessing = preprocess_image_with_stages(
                    corrected,
                    preprocess_params,
                    cancellation_token=token,
                    progress_callback=lambda stage, fraction: progress(
                        f"预处理:{stage}", fraction * 0.28
                    ),
                )
                binary = preprocessing.image
                stages = preprocessing.stages
            else:
                binary = existing_binary
            raw = detect_lines(
                binary,
                detection,
                cancellation_token=token,
                progress_callback=lambda stage, fraction: progress(
                    f"检线:{stage}", 0.30 + fraction * 0.34
                ),
            )
            progress("几何清理", 0.68)
            geometry = clean_geometry_with_report(raw, cleaning, token)
            progress("图层分类", 0.86)
            classification = classify_layers_with_report(
                geometry.lines,
                binary.shape,
                preserve_hatch=preserve_hatch,
                cancellation_token=token,
            )
            auxiliary = None
            if enable_auxiliary:
                progress("辅助识别", 0.92)
                auxiliary = recognize_auxiliary(
                    binary,
                    enable_ocr=enable_ocr,
                    cancellation_token=token,
                )
            preview = render_line_preview(binary, classification.lines)
            progress("预览", 1.0)
            return {
                "binary": binary,
                "stages": stages,
                "raw": raw,
                "lines": classification.lines,
                "geometry_report": geometry.report,
                "classification_report": classification.report,
                "auxiliary": auxiliary,
                "preview": preview,
            }

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("参数已变化，已丢弃过期的识别结果")
                return
            result: dict[str, Any] = value
            self.binary_image = result["binary"]
            if result["stages"]:
                self.preprocess_stages = result["stages"]
                self._show_preprocess_stages(self.preprocess_stages)
            self.raw_lines = result["raw"]
            self.lines = result["lines"]
            self.geometry_report = result["geometry_report"]
            self.classification_report = result["classification_report"]
            self.auxiliary_result = result["auxiliary"]
            self.detected_canvas.set_image(result["preview"])
            self.tabs.setCurrentWidget(self.detected_canvas)
            counts = self.classification_report.layer_counts or {}
            details = ", ".join(f"{key}:{value}" for key, value in sorted(counts.items()))
            auxiliary_details = ""
            if self.auxiliary_result is not None:
                auxiliary_details = (
                    f"；辅助圆 {len(self.auxiliary_result.circles)}、"
                    f"文字 {len(self.auxiliary_result.texts)}、"
                    f"符号 {len(self.auxiliary_result.symbols)}"
                )
            self.statusBar().showMessage(
                f"识别并清理后共 {len(self.lines)} 条线；{details}{auxiliary_details}；"
                "已记录完整源线谱系"
            )

        self._start_processing(operation, completed, "正在识别和清理线条…")

    def start_scale_calibration(self) -> None:
        if not self._require_corrected():
            return
        # Display the corrected source for accurate endpoint selection.
        self.corrected_canvas.set_image(self.corrected_image)
        self.corrected_canvas.clear_overlays()
        self.selection_mode = "scale"
        self.selected_points = []
        self.corrected_canvas.set_selection_enabled(True)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        self.statusBar().showMessage("请在校正图上点击已知尺寸线段的两个端点")

    def _on_corrected_point(self, x: float, y: float) -> None:
        if self.selection_mode != "scale":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.corrected_canvas.add_point(point, str(len(self.selected_points)), Qt.blue)
        if len(self.selected_points) == 2:
            self.corrected_canvas.add_line(self.selected_points[0], self.selected_points[1], Qt.blue)
            self.corrected_canvas.set_selection_enabled(False)
            length, ok = QInputDialog.getDouble(
                self,
                "输入实际长度",
                "这两个点之间的实际长度（mm）：",
                12000.0,
                0.001,
                1_000_000_000.0,
                3,
            )
            self.selection_mode = None
            if not ok:
                self.statusBar().showMessage("已取消比例校准")
                return
            try:
                self.calibration = create_calibration(self.selected_points, length)
            except Exception as exc:
                QMessageBox.critical(self, "校准失败", str(exc))
                return
            self.info_label.setText(
                f"比例：{self.calibration.mm_per_pixel:.6f} mm/px；"
                f"{self.calibration.pixel_distance:.2f}px = {length:.3f}mm"
            )
            self.statusBar().showMessage("真实尺寸比例校准完成")

    def export_file(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成后再导出。")
            return
        if not self.lines:
            QMessageBox.warning(self, "尚未识别", "请先完成“识别并清理线条”，确认预览后再导出。")
            return
        if not self.lines or self.binary_image is None:
            return
        default_dir = Path.cwd() / "output"
        default_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 DXF",
            str(default_dir / "output.dxf"),
            "DXF files (*.dxf)",
        )
        if not path:
            return
        if not path.lower().endswith(".dxf"):
            path += ".dxf"
        if self.calibration is None:
            QMessageBox.information(
                self,
                "未校准真实尺寸",
                "当前未设置比例。DXF 将按 1 像素 = 1 毫米图形单位导出，结构可编辑，但真实尺寸不准确。",
            )
        try:
            result = export_dxf(
                self.lines,
                path,
                self.binary_image.shape[0],
                self.calibration,
            )
            report_path = Path(path).with_suffix(".report.json")
            report = {
                "schema_version": "1.1",
                "application_version": __version__,
                "input_path": str(self.current_path) if self.current_path else None,
                "paper_setting": self.paper_size_combo.currentText(),
                "image_shape": list(self.binary_image.shape),
                "geometry": asdict(self.geometry_report) if self.geometry_report else None,
                "classification": (
                    asdict(self.classification_report) if self.classification_report else None
                ),
                "auxiliary": asdict(self.auxiliary_result) if self.auxiliary_result else None,
                "lineage": build_lineage(self.raw_lines, self.lines),
                "export": {
                    "path": str(result.path),
                    "line_count": result.line_count,
                    "skipped_line_count": result.skipped_line_count,
                    "mm_per_pixel": result.mm_per_pixel,
                    "calibrated": result.calibrated,
                },
                "technical_limits": [
                    "严重折叠、局部波浪和复杂非刚性形变不能保证整页误差小于 2%。",
                    "取消在原生 OpenCV 或 OCR 单次调用返回后生效。",
                    "HATCH 封闭区域包含关系使用保守近似。",
                    "OCR、圆弧、尺寸文字和建筑符号仅作为辅助候选。",
                ],
            }
            write_json_report(report_path, report)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"已生成：{result.path}\n可编辑 LINE 数量：{result.line_count}\n"
            f"处理报告：{report_path}\n"
            f"比例：{result.mm_per_pixel:.6f} mm/px"
            + ("" if result.calibrated else "\n注意：真实尺寸尚未校准。"),
        )
        self.statusBar().showMessage(f"DXF 已导出：{result.path}")
