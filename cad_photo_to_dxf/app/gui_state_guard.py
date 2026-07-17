from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import __version__
from .gui_review import MainWindow as _ReviewedMainWindow
from .image_canvas import ImageCanvas
from .image_loader import load_image, pdf_page_count


UNSCALED_LABEL = "比例：未校准（1 px = 1 个无单位图形单位）"


class MainWindow(_ReviewedMainWindow):
    """Final GUI entry point with transactional state and a complete 1–9 workflow."""

    def __init__(self) -> None:
        super().__init__()
        self._dwg_converter_path: Path | None = None
        self._current_pdf_page: int | None = None
        self.setWindowTitle(f"扫描图片 / PDF 转可编辑 CAD — v{__version__}")
        self.statusBar().showMessage("请先导入 JPG、PNG 或扫描 PDF")
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        button_names = {
            "1. 导入图片": "1. 导入图片 / 扫描 PDF",
            "2. 自动识别纸张并校正": "3. 自动识别纸张并校正",
            "手动点击四角并校正": "3B. 手动点击四角并校正",
            "3. 图像预处理": "4. 图像预处理",
            "4. 识别并清理线条": "5. 识别线条（自动保护文字）",
            "5. 人工复核图层": "6. 人工复核图层",
            "6. 人工确认圆形": "7. 人工确认圆形",
            "5. 点击两点校准模型尺寸": "8. 点击两点校准模型尺寸",
            "6. 导出可编辑 DXF": "9. 导出 CAD（DWG / DXF）",
        }
        for button in scroll.findChildren(QPushButton):
            replacement = button_names.get(button.text())
            if replacement is not None:
                button.setText(replacement)

        for group in scroll.findChildren(QGroupBox):
            if group.title() == "纸张坐标":
                group.setTitle("2. 纸张规格与坐标")
                break

        self.enable_ocr.setText("启用 OCR 文字识别（需安装 Tesseract）")

        view_group = QGroupBox("视图")
        view_layout = QVBoxLayout(view_group)
        view_buttons = QHBoxLayout()
        view_buttons.addWidget(self._button("放大", self._zoom_in))
        view_buttons.addWidget(self._button("缩小", self._zoom_out))
        view_buttons.addWidget(self._button("适应窗口", self._fit_view))
        view_buttons.addWidget(self._button("100%", self._actual_size))
        view_layout.addLayout(view_buttons)
        hint = QLabel("鼠标滚轮缩放；左键拖动平移；双击适应窗口")
        hint.setWordWrap(True)
        view_layout.addWidget(hint)

        export_group = QGroupBox("9. 导出选项")
        export_layout = QVBoxLayout(export_group)
        self.include_underlay_checkbox = QCheckBox(
            "附带校正扫描底图（保留原始文字与细节）"
        )
        self.include_underlay_checkbox.setChecked(True)
        export_layout.addWidget(self.include_underlay_checkbox)
        self.export_ocr_text_checkbox = QCheckBox(
            "将高置信度 OCR 结果导出为可编辑 TEXT"
        )
        self.export_ocr_text_checkbox.setChecked(False)
        self.export_ocr_text_checkbox.setEnabled(self.enable_ocr.isChecked())
        self.enable_ocr.toggled.connect(self.export_ocr_text_checkbox.setEnabled)
        export_layout.addWidget(self.export_ocr_text_checkbox)
        version_row = QHBoxLayout()
        version_row.addWidget(QLabel("DWG 目标版本"))
        self.dwg_version_combo = QComboBox()
        for label, value in (
            ("AutoCAD 2018", "R2018"),
            ("AutoCAD 2013", "R2013"),
            ("AutoCAD 2010", "R2010"),
        ):
            self.dwg_version_combo.addItem(label, value)
        version_row.addWidget(self.dwg_version_combo)
        export_layout.addLayout(version_row)
        export_note = QLabel(
            "DWG 由本机 ODA File Converter 转换；DXF 与 .scan.png 会一并保留。"
        )
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)

        insert_index = max(0, layout.count() - 1)
        layout.insertWidget(insert_index, view_group)
        layout.insertWidget(insert_index + 1, export_group)
        return scroll

    def _build_menu(self) -> None:
        super()._build_menu()
        for menu_action in self.menuBar().actions():
            menu = menu_action.menu()
            if menu is None or menu.title() != "文件":
                continue
            for action in menu.actions():
                if action.text() == "导入图片":
                    action.setText("导入图片 / 扫描 PDF")
                    action.setShortcut("Ctrl+O")
                elif action.text() == "导出 DXF":
                    action.setText("导出 CAD（DWG / DXF）")
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

    def _active_canvas(self) -> ImageCanvas | None:
        current = self.tabs.currentWidget()
        if isinstance(current, ImageCanvas):
            return current
        if current is self.preprocess_tabs:
            preprocess_current = self.preprocess_tabs.currentWidget()
            if isinstance(preprocess_current, ImageCanvas):
                return preprocess_current
        return None

    def _zoom_in(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.zoom_in()

    def _zoom_out(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.zoom_out()

    def _fit_view(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.fit_image()

    def _actual_size(self) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            canvas.actual_size()

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
            "选择图纸图片或扫描 PDF",
            str(Path.home()),
            "Drawing scans (*.jpg *.jpeg *.png *.pdf)",
        )
        if not path:
            return

        page_index = 0
        selected_page: int | None = None
        try:
            if Path(path).suffix.lower() == ".pdf":
                pages = pdf_page_count(path)
                if pages > 1:
                    selected_page, accepted = QInputDialog.getInt(
                        self,
                        "选择 PDF 页面",
                        f"此 PDF 共 {pages} 页，请输入要处理的页码：",
                        1,
                        1,
                        pages,
                        1,
                    )
                    if not accepted:
                        return
                    page_index = selected_page - 1
                else:
                    selected_page = 1
                image = load_image(path, page_index=page_index, pdf_dpi=300)
            else:
                image = load_image(path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        self.current_path = Path(path)
        self._current_pdf_page = selected_page
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
        self._approved_circles = []
        self._state_revision += 1
        self._clear_preprocess_tabs()
        self.original_canvas.set_image(image)
        self.original_canvas.set_selection_enabled(False)
        self.corrected_canvas.set_image(None)
        self.corrected_canvas.set_selection_enabled(False)
        self.detected_canvas.set_image(None)
        self.info_label.setText(UNSCALED_LABEL)
        self.tabs.setCurrentWidget(self.original_canvas)
        page_note = f"；第 {selected_page} 页" if selected_page is not None else ""
        self.statusBar().showMessage(f"已导入：{self.current_path.name}{page_note}")

    def _apply_paper_calibration(self) -> None:
        super()._apply_paper_calibration()
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def auto_perspective(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        if not self._require_original():
            return

        self.corrected_image = None
        self.calibration = None
        self._perspective_metadata = None
        self._invalidate_preprocess_results()
        self.corrected_canvas.set_image(None)
        self.info_label.setText("比例：未校准（旧校正结果已失效）")
        super().auto_perspective()

    def rotate_corrected(self, degrees: int) -> None:
        revision_before = self._state_revision
        metadata_before = deepcopy(self._perspective_metadata)
        super().rotate_corrected(degrees)
        if self._state_revision == revision_before:
            self._perspective_metadata = metadata_before
        elif self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)
