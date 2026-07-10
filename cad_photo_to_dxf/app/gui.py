from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QAction, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dxf_exporter import export_dxf
from .geometry_cleaner import GeometryCleanParams, clean_geometry
from .image_loader import load_image
from .layer_classifier import classify_layers
from .line_detect import LineDetectionParams, LineSegment, detect_lines, render_line_preview
from .perspective import auto_correct, rotate_image, warp_perspective
from .preprocess import PreprocessParams, preprocess_image
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
        self.setWindowTitle("纸质 CAD 图纸照片转可编辑 DXF — MVP")
        self.resize(1450, 900)

        self.original_image: np.ndarray | None = None
        self.corrected_image: np.ndarray | None = None
        self.binary_image: np.ndarray | None = None
        self.lines: list[LineSegment] = []
        self.calibration: ScaleCalibration | None = None
        self.current_path: Path | None = None
        self.selection_mode: str | None = None
        self.selected_points: list[tuple[float, float]] = []

        self.tabs = QTabWidget()
        self.original_canvas = ImageCanvas()
        self.corrected_canvas = ImageCanvas()
        self.detected_canvas = ImageCanvas()
        self.tabs.addTab(self.original_canvas, "原图")
        self.tabs.addTab(self.corrected_canvas, "校正 / 黑白图")
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

        rotate_row = QHBoxLayout()
        rotate_row.addWidget(self._button("旋转 90°", lambda: self.rotate_corrected(90)))
        rotate_row.addWidget(self._button("180°", lambda: self.rotate_corrected(180)))
        rotate_row.addWidget(self._button("270°", lambda: self.rotate_corrected(270)))
        layout.addLayout(rotate_row)
        layout.addWidget(self._button("3. 图像预处理", self.preprocess))
        layout.addWidget(self._button("4. 识别并清理线条", self.detect_and_clean))
        layout.addWidget(self._button("5. 点击两点校准比例", self.start_scale_calibration))
        layout.addWidget(self._button("6. 导出可编辑 DXF", self.export_file))

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
        layout.addWidget(params_group)

        self.info_label = QLabel("比例：未校准（导出时 1 px = 1 mm 图形单位）")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setMinimumWidth(300)
        return scroll

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
        self.lines = []
        self.calibration = None
        self.original_canvas.set_image(image)
        self.corrected_canvas.set_image(None)
        self.detected_canvas.set_image(None)
        self.info_label.setText("比例：未校准（导出时 1 px = 1 mm 图形单位）")
        self.tabs.setCurrentWidget(self.original_canvas)
        self.statusBar().showMessage(f"已导入：{self.current_path.name}")

    def auto_perspective(self) -> None:
        if not self._require_original():
            return
        result = auto_correct(self.original_image)
        if result is None:
            QMessageBox.information(
                self,
                "未识别纸张边界",
                "自动识别失败。请使用“手动点击四角并校正”，四点顺序不限。",
            )
            return
        self.corrected_image = result.image
        self.binary_image = None
        self.lines = []
        self.calibration = None
        self.original_canvas.clear_overlays()
        for index, point in enumerate(result.corners, start=1):
            self.original_canvas.add_point(tuple(point), str(index))
        self.corrected_canvas.set_image(self.corrected_image)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        self.statusBar().showMessage("自动透视校正完成")

    def start_manual_corners(self) -> None:
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
            try:
                self.corrected_image = warp_perspective(self.original_image, self.selected_points)
            except Exception as exc:
                QMessageBox.critical(self, "校正失败", str(exc))
                self.selection_mode = None
                return
            self.selection_mode = None
            self.binary_image = None
            self.lines = []
            self.calibration = None
            self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self.statusBar().showMessage("手动四角透视校正完成")

    def rotate_corrected(self, degrees: int) -> None:
        if not self._require_corrected():
            return
        self.corrected_image = rotate_image(self.corrected_image, degrees)
        self.binary_image = None
        self.lines = []
        self.calibration = None
        self.corrected_canvas.set_image(self.corrected_image)
        self.detected_canvas.set_image(None)
        self.statusBar().showMessage(f"已旋转 {degrees}°，请重新预处理和识别")

    def preprocess(self) -> None:
        if not self._require_corrected():
            return
        params = PreprocessParams(threshold_strength=self.threshold_spin.value())
        try:
            self.binary_image = preprocess_image(self.corrected_image, params)
        except Exception as exc:
            QMessageBox.critical(self, "预处理失败", str(exc))
            return
        self.corrected_canvas.set_image(self.binary_image)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        self.statusBar().showMessage("去阴影和自适应二值化完成")

    def detect_and_clean(self) -> None:
        if self.binary_image is None:
            self.preprocess()
        if self.binary_image is None:
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
        try:
            raw = detect_lines(self.binary_image, detection)
            cleaned = clean_geometry(raw, cleaning)
            self.lines = classify_layers(
                cleaned,
                self.binary_image.shape,
                preserve_hatch=self.keep_hatch.isChecked(),
            )
            preview = render_line_preview(self.binary_image, self.lines)
        except Exception as exc:
            QMessageBox.critical(self, "线条识别失败", str(exc))
            return
        self.detected_canvas.set_image(preview)
        self.tabs.setCurrentWidget(self.detected_canvas)
        counts: dict[str, int] = {}
        for line in self.lines:
            counts[line.layer] = counts.get(line.layer, 0) + 1
        details = ", ".join(f"{key}:{value}" for key, value in sorted(counts.items()))
        self.statusBar().showMessage(f"识别并清理后共 {len(self.lines)} 条线；{details}")

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
        if not self.lines:
            self.detect_and_clean()
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
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"已生成：{result.path}\n可编辑 LINE 数量：{result.line_count}\n"
            f"比例：{result.mm_per_pixel:.6f} mm/px"
            + ("" if result.calibrated else "\n注意：真实尺寸尚未校准。"),
        )
        self.statusBar().showMessage(f"DXF 已导出：{result.path}")
