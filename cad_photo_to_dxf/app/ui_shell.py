from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QThread, Qt, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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

from . import __version__
from .auxiliary_recognition import AuxiliaryRecognitionResult
from .cancellation import CancellationToken
from .geometry_cleaner import GeometryCleanReport
from .image_canvas import ImageCanvas
from .image_loader import load_image
from .layer_classifier import ClassificationReport
from .line_detect import LineSegment
from .perspective import (
    resolve_paper_aspect_ratio,
    resolve_paper_dimensions_mm,
    rotate_image,
)
from .scale_calibrator import ScaleCalibration, create_calibration
from .worker import ProcessingWorker


ProcessingOperation = Callable[
    [CancellationToken, Callable[[str, float], None]],
    object,
]


class MainWindow(QMainWindow):
    """Widget shell and interaction plumbing with no CAD processing pipeline."""

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
        layout.addWidget(
            self._button("2. 自动识别纸张并校正", self.auto_perspective)
        )
        layout.addWidget(
            self._button("手动点击四角并校正", self.start_manual_corners)
        )

        paper_group = QGroupBox("纸张坐标")
        paper_form = QFormLayout(paper_group)
        self.paper_size_combo = QComboBox()
        self.paper_size_combo.addItem("未知（无单位像素）", (None, "auto"))
        for size in ("A0", "A1", "A2", "A3", "A4", "LETTER", "LEGAL"):
            self.paper_size_combo.addItem(f"{size} 横向", (size, "landscape"))
            self.paper_size_combo.addItem(f"{size} 纵向", (size, "portrait"))
        paper_form.addRow("纸张规格", self.paper_size_combo)
        layout.addWidget(paper_group)

        rotate_row = QHBoxLayout()
        rotate_row.addWidget(
            self._button("旋转 90°", lambda: self.rotate_corrected(90))
        )
        rotate_row.addWidget(
            self._button("180°", lambda: self.rotate_corrected(180))
        )
        rotate_row.addWidget(
            self._button("270°", lambda: self.rotate_corrected(270))
        )
        layout.addLayout(rotate_row)
        layout.addWidget(self._button("3. 图像预处理", self.preprocess))
        layout.addWidget(self._button("4. 识别并清理线条", self.detect_and_clean))
        layout.addWidget(
            self._button("5. 点击两点校准模型尺寸", self.start_scale_calibration)
        )
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
        form.addRow("最小线段长度（参考像素）", self.min_length_spin)

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
        self.keep_hatch.setChecked(False)
        form.addRow(self.keep_hatch)
        self.enable_auxiliary = QCheckBox("辅助识别圆和矩形符号（仅报告）")
        self.enable_auxiliary.setChecked(False)
        form.addRow(self.enable_auxiliary)
        self.enable_ocr = QCheckBox("启用可选 OCR（仅报告）")
        self.enable_ocr.setChecked(False)
        form.addRow(self.enable_ocr)
        params_group.setTitle("高级参数（通常无需修改）")
        params_group.setCheckable(True)
        params_group.setChecked(False)
        parameter_children = [
            child for child in params_group.findChildren(QWidget) if child is not params_group
        ]
        for child in parameter_children:
            child.setVisible(False)

        def set_parameter_visibility(checked: bool) -> None:
            for child in parameter_children:
                child.setVisible(checked)
            params_group.updateGeometry()

        params_group.toggled.connect(set_parameter_visibility)
        layout.addWidget(params_group)

        self.info_label = QLabel("坐标：未校准的无单位像素坐标")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.paper_size_combo.currentIndexChanged.connect(
            self._paper_setting_changed
        )
        self.threshold_spin.valueChanged.connect(
            self._invalidate_preprocess_results
        )
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
            observed_landscape=(
                self.corrected_image.shape[1] >= self.corrected_image.shape[0]
            ),
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
            f"坐标：纸面毫米 {self.calibration.mm_per_pixel:.6f} mm/px；"
            "不是工程模型尺寸"
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
        self.info_label.setText("纸张规格已变化，请重新执行透视校正")
        self.statusBar().showMessage("纸张规格已变化，请重新校正、预处理和识别")

    def _is_processing(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _start_processing(
        self,
        operation: ProcessingOperation,
        on_success: Callable[[object], None],
        message: str,
    ) -> None:
        if self._is_processing():
            QMessageBox.information(
                self,
                "正在处理",
                "请等待当前任务完成，或点击取消。",
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
        self.statusBar().showMessage(
            "处理已取消；原生 OpenCV 调用会在返回后响应取消"
        )

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
        self.statusBar().showMessage(
            "已请求取消，将在当前 OpenCV/OCR 调用返回后停止"
        )

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
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "尚未确认透视校正",
            "请先自动识别纸张，或手动点击四角完成校正。",
        )
        return False

    def import_image(self) -> None:
        if self._is_processing():
            QMessageBox.information(
                self,
                "正在处理",
                "请先取消或等待当前任务完成。",
            )
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
        self.selection_mode = None
        self.selected_points = []
        self._state_revision += 1
        self._clear_preprocess_tabs()
        self.original_canvas.set_image(image)
        self.original_canvas.set_selection_enabled(False)
        self.corrected_canvas.set_image(None)
        self.corrected_canvas.set_selection_enabled(False)
        self.detected_canvas.set_image(None)
        self.info_label.setText("坐标：未校准的无单位像素坐标")
        self.tabs.setCurrentWidget(self.original_canvas)
        self.statusBar().showMessage(f"已导入：{self.current_path.name}")

    def start_manual_corners(self) -> None:
        if self._is_processing():
            QMessageBox.information(
                self,
                "正在处理",
                "请先取消或等待当前任务完成。",
            )
            return
        if not self._require_original():
            return
        self.selection_mode = "corners"
        self.selected_points = []
        self.original_canvas.clear_overlays()
        self.original_canvas.set_selection_enabled(True)
        self.tabs.setCurrentWidget(self.original_canvas)
        self.statusBar().showMessage("请在原图上点击纸张的四个角，顺序不限")

    def rotate_corrected(self, degrees: int) -> None:
        if self._is_processing():
            QMessageBox.information(
                self,
                "正在处理",
                "请先取消或等待当前任务完成。",
            )
            return
        if not self._require_corrected():
            return
        self.corrected_image = rotate_image(self.corrected_image, degrees)
        self._invalidate_preprocess_results()
        self.calibration = None
        self.corrected_canvas.set_image(self.corrected_image)
        self.detected_canvas.set_image(None)
        self.statusBar().showMessage(
            f"已旋转 {degrees}°，请重新预处理和识别"
        )

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

    def _on_corrected_point(self, x: float, y: float) -> None:
        if self.selection_mode != "scale":
            return
        point = (x, y)
        self.selected_points.append(point)
        self.corrected_canvas.add_point(
            point,
            str(len(self.selected_points)),
            Qt.blue,
        )
        if len(self.selected_points) != 2:
            return
        self.corrected_canvas.add_line(
            self.selected_points[0],
            self.selected_points[1],
            Qt.blue,
        )
        self.corrected_canvas.set_selection_enabled(False)
        length, accepted = QInputDialog.getDouble(
            self,
            "输入实际长度",
            "这两个点之间的工程模型长度（mm）：",
            12000.0,
            0.001,
            1_000_000_000.0,
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
            f"坐标：工程模型毫米 {calibration.mm_per_pixel:.6f} mm/px；"
            f"{calibration.pixel_distance:.2f}px = {length:.3f}mm"
        )
        self.statusBar().showMessage("工程模型尺寸校准完成")
