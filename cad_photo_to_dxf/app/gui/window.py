"""Desktop entry for the same ordinary conversion used by the command line."""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core.cancellation import CancellationToken, ProcessingCancelled
from app.core.conversion import (
    MAX_RENDER_PIXELS,
    SUPPORTED_EXTENSIONS,
    convert_document,
    inspect_document,
)


def protected_source_rect(rect, image_rect, source_size):
    """Map a preview selection to an inclusive/exclusive source-pixel rectangle."""
    rect = rect.normalized().intersected(image_rect)
    if rect.isEmpty() or image_rect.isEmpty():
        return None
    width, height = source_size
    x0 = max(0, math.floor((rect.left()-image_rect.left()) / image_rect.width() * width))
    y0 = max(0, math.floor((rect.top()-image_rect.top()) / image_rect.height() * height))
    x1 = min(width, math.ceil((rect.right()-image_rect.left()) / image_rect.width() * width))
    y1 = min(height, math.ceil((rect.bottom()-image_rect.top()) / image_rect.height() * height))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def pdf_raster_size(page_rect, dpi):
    """Match the actual scanned-PDF renderer, including its pixel cap and rounding."""
    import pymupdf
    scale = min(float(dpi) / 72, math.sqrt(MAX_RENDER_PIXELS / max(page_rect.width*page_rect.height, 1)))
    pixels = (page_rect * pymupdf.Matrix(scale, scale)).irect
    return pixels.width, pixels.height


class PreviewView(QGraphicsView):
    region_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.white)
        self._image_rect = QRectF()
        self._source_size = None
        self._selection_enabled = False
        self._selection_start = None
        self._selection_item = None
        self._region_items = []

    def set_pixmap(self, pixmap, source_size=None):
        self.scene().clear()
        item = self.scene().addPixmap(pixmap)
        self._image_rect = item.boundingRect()
        self._source_size = source_size
        self._selection_start = self._selection_item = None
        self._region_items = []
        self.scene().setSceneRect(self._image_rect)
        self.set_selection_enabled(False)
        self.fit_image()

    def set_selection_enabled(self, enabled):
        self._selection_enabled = bool(enabled and self._source_size)
        self.setDragMode(QGraphicsView.DragMode.NoDrag if self._selection_enabled
                         else QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if self._selection_enabled
                                  else Qt.CursorShape.OpenHandCursor)

    def clear_regions(self):
        for item in self._region_items:
            self.scene().removeItem(item)
        self._region_items = []
        self._selection_start = self._selection_item = None

    def _bounded_point(self, point):
        return QPointF(max(self._image_rect.left(), min(self._image_rect.right(), point.x())),
                       max(self._image_rect.top(), min(self._image_rect.bottom(), point.y())))

    def mousePressEvent(self, event):
        if self._selection_enabled and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self._image_rect.contains(point):
                self._selection_start = point
                pen = QPen(QColor("#d76a00"), 2)
                pen.setCosmetic(True)
                self._selection_item = self.scene().addRect(
                    QRectF(point, point), pen, QBrush(QColor(255, 170, 0, 45)))
                self._selection_item.setZValue(10)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._selection_start is not None:
            point = self._bounded_point(self.mapToScene(event.position().toPoint()))
            self._selection_item.setRect(QRectF(self._selection_start, point).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._selection_start is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._bounded_point(self.mapToScene(event.position().toPoint()))
            rect = QRectF(self._selection_start, point).normalized()
            self._selection_item.setRect(rect)
            region = protected_source_rect(rect, self._image_rect, self._source_size)
            if region and rect.width()*self.transform().m11() >= 3 and rect.height()*self.transform().m22() >= 3:
                self._region_items.append(self._selection_item)
                self.region_selected.emit(region)
            else:
                self.scene().removeItem(self._selection_item)
            self._selection_start = self._selection_item = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def fit_image(self):
        if self.scene().items():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_image()

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)
        event.accept()


class ConversionWorker(QThread):
    progress = Signal(str, float)
    completed = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source, output, options):
        super().__init__()
        self.source, self.output, self.options = source, output, options
        self.token = CancellationToken()

    def run(self):
        try:
            result = convert_document(
                self.source, self.output, **self.options, cancellation_token=self.token,
                progress_callback=lambda stage, value: self.progress.emit(stage, value),
            )
        except ProcessingCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.completed.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"图像转 CAD · {__version__}")
        self.resize(1220, 820)
        self.setAcceptDrops(True)
        self._worker = None
        self._close_pending = False
        self._results = []
        self._preserve_regions = []
        self._source_can_protect = False
        self._install_ui_font()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择 PDF 或扫描图，也可直接拖入窗口")
        self.input_edit.setReadOnly(True)
        self.import_button = QPushButton("选择文件")
        self.import_button.clicked.connect(self.choose_input)
        source_row = QHBoxLayout()
        source_row.addWidget(self.input_edit)
        source_row.addWidget(self.import_button)
        self.output_edit = QLineEdit()
        self.output_button = QPushButton("保存到")
        self.output_button.clicked.connect(self.choose_output)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.output_edit)
        destination_row.addWidget(self.output_button)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(self.show_source)
        self.all_pages = QCheckBox("转换全部页面")
        self.all_pages.setChecked(True)
        self.page_spin.setEnabled(False)
        self.dpi_spin = QDoubleSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setDecimals(0)
        self.dpi_spin.valueChanged.connect(self.show_source)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 10000)
        self.scale_spin.setDecimals(3)
        self.scale_spin.setValue(1)
        self.ocr_check = QCheckBox("中英文识别，保存可编辑文字")
        self.ocr_check.setChecked(True)
        self.perspective_check = QCheckBox("校正照片的纸张透视")
        self.overwrite_check = QCheckBox("覆盖同名输出")
        self.protect_button = QPushButton("框选保护签章/Logo")
        self.protect_button.setCheckable(True)
        self.protect_button.setEnabled(False)
        self.protect_button.toggled.connect(self._set_protect_mode)
        self.clear_regions_button = QPushButton("清除")
        self.clear_regions_button.setEnabled(False)
        self.clear_regions_button.clicked.connect(self.clear_protected_regions)
        self.region_count = QLabel("已选 0 处")
        protection_row = QHBoxLayout()
        protection_row.addWidget(self.protect_button)
        protection_row.addWidget(self.clear_regions_button)
        protection_row.addWidget(self.region_count)
        self.page_label = QLabel("尚未导入文件")
        self.page_label.setWordWrap(True)
        info = QLabel(
            "矢量 PDF 直接提取图线和文字；扫描页提取基础几何和中英文文字。\n"
            "签章与 Logo 保留为独立图像。请保留 DXF 旁的字体和图像目录。\n"
            "DPI 决定扫描纸面尺寸。比例 1:100 输入 100；未知时保留 1，后续按已知尺寸校准。"
        )
        info.setWordWrap(True)
        form = QFormLayout()
        form.addRow("输入", source_row)
        form.addRow("输出", destination_row)
        form.addRow("查看/指定页", self.page_spin)
        form.addRow("", self.all_pages)
        form.addRow("扫描 DPI", self.dpi_spin)
        form.addRow("图纸比例 1:", self.scale_spin)
        form.addRow("", self.ocr_check)
        form.addRow("", self.perspective_check)
        form.addRow(protection_row)
        form.addRow("", self.overwrite_check)
        form.addRow("", self.page_label)
        self.convert_button = QPushButton("转换并保存 DXF")
        self.convert_button.setMinimumHeight(42)
        self.convert_button.clicked.connect(self.start_conversion)
        self.cancel_button = QPushButton("停止")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        buttons = QHBoxLayout()
        buttons.addWidget(self.convert_button)
        buttons.addWidget(self.cancel_button)
        self.progress_bar = QProgressBar()
        self.result_log = QTextEdit()
        self.result_log.setReadOnly(True)
        self.open_output_button = QPushButton("打开输出文件夹")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output)
        self.font_button = QPushButton("准备 CAD 中文字体")
        self.font_button.clicked.connect(self.prepare_cad_fonts)
        self.result_pages = QComboBox()
        self.result_pages.setPlaceholderText("选择已转换页面")
        self.result_pages.currentIndexChanged.connect(self.show_result)
        panel = QWidget()
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(500)
        left = QVBoxLayout(panel)
        left.addLayout(form)
        left.addWidget(info)
        left.addLayout(buttons)
        left.addWidget(self.progress_bar)
        left.addWidget(self.result_pages)
        left.addWidget(self.result_log, 1)
        left.addWidget(self.open_output_button)
        left.addWidget(self.font_button)
        self.source_view, self.result_view = PreviewView(), PreviewView()
        self.source_view.region_selected.connect(self._region_selected)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.source_view, "原图")
        self.tabs.addTab(self.result_view, "已保存 DXF")
        splitter = QSplitter()
        splitter.addWidget(panel)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 820])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("选择文件后即可转换")
        action = QAction("打开文件", self)
        action.setShortcut("Ctrl+O")
        action.triggered.connect(self.choose_input)
        self.menuBar().addMenu("文件").addAction(action)
        fit = QAction("适合窗口", self)
        fit.triggered.connect(lambda: self.tabs.currentWidget().fit_image())
        self.menuBar().addMenu("视图").addAction(fit)

    def _install_ui_font(self):
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        font = root / "resources/fonts/NotoSansCJKsc-Regular.otf"
        if font.exists():
            identifier = QFontDatabase.addApplicationFont(str(font))
            families = QFontDatabase.applicationFontFamilies(identifier)
            if families:
                QApplication.instance().setFont(QFont(families[0], 10))

    def choose_input(self):
        if self._worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图纸", "", "图纸 (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
        )
        if path:
            self.load_input(path)

    def load_input(self, path):
        if self._worker is not None:
            return
        try:
            details = inspect_document(path)
        except Exception as error:
            QMessageBox.warning(self, "无法读取", str(error))
            return
        source = Path(details["input"])
        self._results = []
        self.result_pages.clear()
        self.result_view.scene().clear()
        self.result_log.clear()
        self.open_output_button.setEnabled(False)
        self.input_edit.setText(str(source))
        self.output_edit.setText(str(source.with_name(source.stem + "_cad.dxf")))
        self.page_spin.setMaximum(details["pages"])
        self.page_spin.setValue(1)
        self.all_pages.setEnabled(details["pages"] > 1)
        self.page_spin.setEnabled(details["pages"] > 1)
        self.page_label.setText(f"{details['pages']} 页 · {source.name}")
        self.perspective_check.setEnabled(details["kind"] != "pdf")
        self.show_source()

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 DXF", self.output_edit.text(), "DXF (*.dxf)"
        )
        if path:
            self.output_edit.setText(path)

    def show_source(self, *_args):
        self.clear_protected_regions()
        self._source_can_protect = False
        self.protect_button.setEnabled(False)
        source = Path(self.input_edit.text())
        if not source.is_file():
            return
        try:
            if source.suffix.lower() == ".pdf":
                import pymupdf
                with pymupdf.open(source) as document:
                    page = document[min(self.page_spin.value() - 1, len(document) - 1)]
                    source_size = pdf_raster_size(page.rect, self.dpi_spin.value())
                    zoom = min(2.0, 1800 / max(page.rect.width, page.rect.height))
                    image = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    pixmap = QPixmap()
                    pixmap.loadFromData(image.tobytes("png"))
                from app.core.pdf_conversion import inspect_pdf_page
                self._source_can_protect = inspect_pdf_page(source, self.page_spin.value())["route"] == "scan"
            else:
                from io import BytesIO

                from PIL import Image, ImageOps
                with Image.open(source) as image:
                    image.seek(min(self.page_spin.value() - 1, getattr(image, "n_frames", 1) - 1))
                    image = ImageOps.exif_transpose(image).convert("RGBA")
                    source_size = image.size
                    image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image).convert("RGB")
                    image.thumbnail((2000, 2000))
                    stream = BytesIO()
                    image.save(stream, format="PNG")
                    pixmap = QPixmap()
                    pixmap.loadFromData(stream.getvalue())
                self._source_can_protect = True
            self.source_view.set_pixmap(pixmap, source_size)
            self.protect_button.setEnabled(self._source_can_protect and self._worker is None)
            self.protect_button.setToolTip("在原图上拖动矩形，保护区域保持图像，不参加文字识别。"
                                          if self._source_can_protect else "原生矢量 PDF 的嵌入图像直接保留，无需框选。")
            self.tabs.setCurrentWidget(self.source_view)
        except Exception as error:
            self.statusBar().showMessage(f"原图预览失败：{error}")

    def _set_protect_mode(self, enabled):
        self.source_view.set_selection_enabled(enabled and self._worker is None)
        if enabled:
            self.tabs.setCurrentWidget(self.source_view)
            self.statusBar().showMessage("在原图拖动矩形保护签章或 Logo；可连续框选多处。")

    def _region_selected(self, region):
        self._preserve_regions.append(tuple(region))
        self.all_pages.setChecked(False)
        self.all_pages.setEnabled(False)
        self.region_count.setText(f"已选 {len(self._preserve_regions)} 处")
        self.clear_regions_button.setEnabled(True)
        self.statusBar().showMessage(f"已保护 {len(self._preserve_regions)} 处；将转换当前第 {self.page_spin.value()} 页。")

    def clear_protected_regions(self):
        self._preserve_regions = []
        self.protect_button.setChecked(False)
        self.region_count.setText("已选 0 处")
        self.clear_regions_button.setEnabled(False)
        self.source_view.clear_regions()
        self.all_pages.setEnabled(self._worker is None and self.page_spin.maximum() > 1)

    def start_conversion(self):
        if self._worker is not None:
            return
        if not self.input_edit.text() or not self.output_edit.text():
            QMessageBox.information(self, "选择文件", "请先选择输入文件和 DXF 输出位置。")
            return
        options = {
            "page_number": None if self.all_pages.isChecked() and not self._preserve_regions else self.page_spin.value(),
            "all_pages": self.all_pages.isChecked() and not self._preserve_regions, "dpi": self.dpi_spin.value(),
            "drawing_scale": self.scale_spin.value(),
            "enable_ocr": self.ocr_check.isChecked(),
            "perspective": self.perspective_check.isEnabled() and self.perspective_check.isChecked(),
            "overwrite": self.overwrite_check.isChecked(),
            "preserve_regions": list(self._preserve_regions),
        }
        self._worker = ConversionWorker(self.input_edit.text(), self.output_edit.text(), options)
        self._worker.progress.connect(self._progress)
        self._worker.completed.connect(self._completed)
        self._worker.failed.connect(self._failed)
        self._worker.cancelled.connect(lambda: self.result_log.append("转换已停止，已完成页面保留。"))
        self._worker.finished.connect(self._finished)
        self.result_log.clear()
        self._results = []
        self.result_pages.clear()
        self.result_view.scene().clear()
        self.open_output_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self._worker.start()

    def _set_busy(self, busy):
        for widget in (self.convert_button, self.import_button, self.output_button,
                       self.output_edit, self.dpi_spin, self.scale_spin, self.ocr_check, self.overwrite_check):
            widget.setEnabled(not busy)
        self.page_spin.setEnabled(not busy and self.page_spin.maximum() > 1)
        self.all_pages.setEnabled(not busy and self.page_spin.maximum() > 1 and not self._preserve_regions)
        self.perspective_check.setEnabled(not busy and Path(self.input_edit.text()).suffix.lower() != ".pdf")
        self.cancel_button.setEnabled(busy)
        self.protect_button.setEnabled(not busy and self._source_can_protect)
        self.clear_regions_button.setEnabled(not busy and bool(self._preserve_regions))
        if busy:
            self.protect_button.setChecked(False)
        self.source_view.setEnabled(not busy)

    def _progress(self, stage, value):
        self.statusBar().showMessage(stage)
        self.progress_bar.setValue(round(value * 100))

    def _completed(self, result):
        self._results = result["outputs"]
        for page in self._results:
            self.result_log.append(
                f"第 {page['page_number']} 页\n{page['output']}\n实体：{page.get('counts', {})}\n"
            )
        for warning in result["warnings"]:
            self.result_log.append(warning)
        self.result_log.append(f"耗时 {result['elapsed_seconds']:.1f} 秒\n报告：{result['report']}")
        self.result_pages.addItems([f"第 {page['page_number']} 页 · {page['route']}" for page in self._results])
        if self._results:
            self.result_pages.setCurrentIndex(0)
        self.open_output_button.setEnabled(True)
        self.statusBar().showMessage("转换完成；请检查文字和局部几何")

    def show_result(self, index):
        if 0 <= index < len(self._results) and self._results[index].get("preview"):
            self.result_view.set_pixmap(QPixmap(self._results[index]["preview"]))
            self.tabs.setCurrentWidget(self.result_view)

    def _failed(self, message):
        self.result_log.append(f"转换失败：{message}")
        self.statusBar().showMessage("转换失败")

    def _finished(self):
        worker, self._worker = self._worker, None
        self._set_busy(False)
        if worker is not None:
            worker.deleteLater()
        if self._close_pending:
            self.close()

    def cancel_conversion(self):
        if self._worker is not None:
            self._worker.token.cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("正在停止…")

    def open_output(self):
        if self._results:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._results[0]["output"]).parent)))

    def prepare_cad_fonts(self):
        from app.core.font_install import install_cad_fonts
        try:
            result = install_cad_fonts()
            QMessageBox.information(self, "中文字体", result)
        except Exception as error:
            QMessageBox.warning(self, "字体准备失败", str(error))

    def dragEnterEvent(self, event):
        if self._worker is None and event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
            if len(paths) == 1 and paths[0].suffix.lower() in SUPPORTED_EXTENSIONS:
                event.acceptProposedAction()

    def dropEvent(self, event):
        self.load_input(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._close_pending = True
            self.cancel_conversion()
            event.ignore()
        else:
            event.accept()
