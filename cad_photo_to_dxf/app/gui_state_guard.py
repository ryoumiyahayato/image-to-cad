from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

import cv2

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import __version__
from .document_export import DocumentPage
from .geometry_cleaner import GeometryCleanParams
from .gui_review import MainWindow as _ReviewedMainWindow
from .image_canvas import ImageCanvas
from .image_loader import (
    load_image,
    pdf_page_count,
    pdf_page_size_mm,
)
from .line_detect import LineDetectionParams, render_line_preview
from .pipeline_service import PipelineService, VectorizationResult
from .preprocess import PreprocessParams
from .scale_calibrator import ScaleCalibration


UNSCALED_LABEL = "比例：未校准（1 px = 1 个无单位图形单位）"
PDF_VIEW_DPI = 200
PDF_BATCH_DPI = 100
MAX_PDF_VECTOR_DIMENSION = 2400


class MainWindow(_ReviewedMainWindow):
    """Final GUI entry point with document-oriented PDF handling."""

    def __init__(self) -> None:
        super().__init__()
        self._dwg_converter_path: Path | None = None
        self._current_pdf_page: int | None = None
        self._native_pdf_mode = False
        self._pdf_page_count = 1
        self._current_pdf_page_index = 0
        self._pdf_page_states: dict[int, dict[str, Any]] = {}
        self._pdf_page_sizes_mm: dict[int, tuple[float, float]] = {}
        self.setWindowTitle(f"扫描图片 / PDF 转可编辑 CAD — v{__version__}")
        self.statusBar().showMessage("请先导入 JPG、PNG 或扫描 PDF")
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)
        self._set_pdf_controls_enabled(False)
        self._toggle_advanced(False)

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        button_names = {
            "1. 导入图片": "1. 导入图片 / 扫描 PDF",
            "2. 自动识别纸张并校正": "2A. 照片自动校正",
            "手动点击四角并校正": "2B. 照片手动四角校正",
            "3. 图像预处理": "高级：单独查看预处理",
            "4. 识别并清理线条": "3. 自动识别结构线",
            "5. 可视化修改识别结果": "4. 在图纸上可视化修改",
            "5. 点击两点校准模型尺寸": "5. 模型尺寸校准（可选）",
            "6. 导出可编辑 DXF": "6. 导出同一 CAD（DWG / DXF）",
        }
        self._preprocess_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            original = button.text()
            replacement = button_names.get(original)
            if replacement is not None:
                button.setText(replacement)
            if original == "3. 图像预处理":
                self._preprocess_button = button

        self._paper_group: QGroupBox | None = None
        self._params_group: QGroupBox | None = None
        for group in scroll.findChildren(QGroupBox):
            if group.title() == "纸张坐标":
                group.setTitle("纸张与坐标（照片可选）")
                self._paper_group = group
            elif group.title() == "参数":
                group.setTitle("高级识别参数")
                self._params_group = group

        page_group = QGroupBox("PDF 页面与合并")
        page_layout = QVBoxLayout(page_group)
        page_row = QHBoxLayout()
        self.previous_page_button = self._button("上一页", self._previous_pdf_page)
        page_row.addWidget(self.previous_page_button)
        self.page_combo = QComboBox()
        self.page_combo.addItem("单页图片", 0)
        self.page_combo.currentIndexChanged.connect(self._on_pdf_page_changed)
        page_row.addWidget(self.page_combo, 1)
        self.next_page_button = self._button("下一页", self._next_pdf_page)
        page_row.addWidget(self.next_page_button)
        page_layout.addLayout(page_row)
        self.page_summary_label = QLabel("导入多页 PDF 后，可逐页查看并合并导出。")
        self.page_summary_label.setWordWrap(True)
        page_layout.addWidget(self.page_summary_label)
        self.batch_pdf_button = self._button(
            "批量自动识别全部 PDF 页面（可取消）",
            self.batch_vectorize_pdf,
        )
        page_layout.addWidget(self.batch_pdf_button)
        layout.insertWidget(1, page_group)

        view_group = QGroupBox("视图")
        view_layout = QVBoxLayout(view_group)
        view_buttons = QHBoxLayout()
        view_buttons.addWidget(self._button("放大", self._zoom_in))
        view_buttons.addWidget(self._button("缩小", self._zoom_out))
        view_buttons.addWidget(self._button("适应窗口", self._fit_view))
        view_buttons.addWidget(self._button("100%", self._actual_size))
        view_layout.addLayout(view_buttons)
        hint = QLabel(
            "鼠标滚轮缩放；左键拖动平移；双击适应窗口。缩小时采用保线条预览。"
        )
        hint.setWordWrap(True)
        view_layout.addWidget(hint)

        export_group = QGroupBox("导出选项")
        export_layout = QVBoxLayout(export_group)
        self.include_underlay_checkbox = QCheckBox(
            "扫描保真底图（推荐；保留原始文字、符号和全部细节）"
        )
        self.include_underlay_checkbox.setChecked(True)
        export_layout.addWidget(self.include_underlay_checkbox)
        self.export_ocr_text_checkbox = QCheckBox(
            "高级：将高置信度 OCR 结果导出为可编辑 TEXT"
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
            "多页 PDF 默认合并到一个 DXF/DWG：模型空间纵向排列，"
            "并为每页建立 PAGE-### 布局。DWG 由本机 ODA File Converter 转换。"
        )
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)

        self.show_advanced_checkbox = QCheckBox("显示高级参数与单独预处理")
        self.show_advanced_checkbox.toggled.connect(self._toggle_advanced)

        detect_button = next(
            (
                button
                for button in scroll.findChildren(QPushButton)
                if button.text().startswith("3. 自动识别")
            ),
            None,
        )
        export_button = next(
            (
                button
                for button in scroll.findChildren(QPushButton)
                if button.text().startswith("6. 导出")
            ),
            None,
        )
        view_index = layout.indexOf(detect_button) if detect_button else -1
        layout.insertWidget(view_index if view_index >= 0 else 6, view_group)
        export_index = layout.indexOf(export_button) if export_button else -1
        layout.insertWidget(
            export_index if export_index >= 0 else max(0, layout.count() - 1),
            export_group,
        )
        layout.insertWidget(max(0, layout.count() - 1), self.show_advanced_checkbox)
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

    def _toggle_advanced(self, visible: bool) -> None:
        if getattr(self, "_params_group", None) is not None:
            self._params_group.setVisible(bool(visible))
        if getattr(self, "_preprocess_button", None) is not None:
            self._preprocess_button.setVisible(bool(visible))
        if hasattr(self, "export_ocr_text_checkbox"):
            self.export_ocr_text_checkbox.setVisible(bool(visible))
        self.enable_ocr.setVisible(bool(visible))
        self.enable_auxiliary.setVisible(bool(visible))

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

    def _set_pdf_controls_enabled(self, enabled: bool) -> None:
        for widget_name in (
            "previous_page_button",
            "next_page_button",
            "page_combo",
            "batch_pdf_button",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(enabled)

    def import_image(self) -> None:
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请先取消或等待当前任务完成。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图纸图片或扫描 PDF",
            str(Path.home()),
            "Drawing scans (*.jpg *.jpeg *.png *.pdf)",
        )
        if not path:
            return

        file_path = Path(path)
        try:
            if file_path.suffix.lower() == ".pdf":
                count = pdf_page_count(file_path)
                self.current_path = file_path
                self._native_pdf_mode = True
                self._pdf_page_count = count
                self._current_pdf_page_index = 0
                self._current_pdf_page = 1
                self._pdf_page_states = {}
                self._pdf_page_sizes_mm = {
                    index: pdf_page_size_mm(file_path, index)
                    for index in range(count)
                }
                self.page_combo.blockSignals(True)
                self.page_combo.clear()
                for index in range(count):
                    self.page_combo.addItem(f"第 {index + 1} / {count} 页", index)
                self.page_combo.setCurrentIndex(0)
                self.page_combo.blockSignals(False)
                self._set_pdf_controls_enabled(count > 1)
                if self._paper_group is not None:
                    self._paper_group.setEnabled(False)
                self._load_pdf_page(0, save_current=False)
                self.page_summary_label.setText(
                    f"已载入 {count} 页。未识别页面仍会以无损扫描底图合并导出；"
                    "批量识别只增加可编辑结构线，不替代原始扫描。"
                )
                return
            image = load_image(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        self.current_path = file_path
        self._native_pdf_mode = False
        self._pdf_page_count = 1
        self._current_pdf_page_index = 0
        self._current_pdf_page = None
        self._pdf_page_states = {}
        self._pdf_page_sizes_mm = {}
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItem("单页图片", 0)
        self.page_combo.blockSignals(False)
        self._set_pdf_controls_enabled(False)
        if self._paper_group is not None:
            self._paper_group.setEnabled(True)
        self.page_summary_label.setText("单页图片；如为照片，请先完成纸张校正。")
        self._set_single_image_state(image, corrected=False)
        self.statusBar().showMessage(f"已导入：{self.current_path.name}")

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        self.original_image = image
        self.corrected_image = image.copy() if corrected else None
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
        self.corrected_canvas.set_image(self.corrected_image)
        self.corrected_canvas.set_selection_enabled(False)
        self.detected_canvas.set_image(None)
        self.info_label.setText(UNSCALED_LABEL)
        self.tabs.setCurrentWidget(self.original_canvas)

    def _save_current_pdf_state(self) -> None:
        if not self._native_pdf_mode:
            return
        self._pdf_page_states[self._current_pdf_page_index] = {
            "raw_lines": list(self.raw_lines),
            "lines": list(self.lines),
            "geometry_report": self.geometry_report,
            "classification_report": self.classification_report,
            "auxiliary_result": self.auxiliary_result,
            "last_warnings": tuple(self._last_warnings),
            "run_started_at": self._run_started_at,
            "run_duration_seconds": self._run_duration_seconds,
            "last_preprocess_scale": self._last_preprocess_scale,
            "last_detection_scale": self._last_detection_scale,
            "last_geometry_scale": self._last_geometry_scale,
            "last_preprocess_params": self._last_preprocess_params,
            "last_detection_params": self._last_detection_params,
            "last_clean_params": self._last_clean_params,
            "vector_shape": (
                tuple(self.corrected_image.shape[:2])
                if self.corrected_image is not None
                else None
            ),
        }

    def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
        if not self._native_pdf_mode or self.current_path is None:
            return
        if not 0 <= page_index < self._pdf_page_count:
            return
        if save_current:
            self._save_current_pdf_state()
        image = load_image(
            self.current_path,
            page_index=page_index,
            pdf_dpi=PDF_VIEW_DPI,
        )
        self._current_pdf_page_index = page_index
        self._current_pdf_page = page_index + 1
        self.original_image = image
        self.corrected_image = image.copy()
        self.binary_image = None
        self.preprocess_stages = {}
        self._clear_preprocess_tabs()
        state = self._pdf_page_states.get(page_index, {})
        self.raw_lines = list(state.get("raw_lines", []))
        self.lines = list(state.get("lines", []))
        self.geometry_report = state.get("geometry_report")
        self.classification_report = state.get("classification_report")
        self.auxiliary_result = state.get("auxiliary_result")
        self._last_warnings = tuple(state.get("last_warnings", ()))
        self._run_started_at = state.get("run_started_at")
        self._run_duration_seconds = state.get("run_duration_seconds")
        self._last_preprocess_scale = float(state.get("last_preprocess_scale", 1.0))
        self._last_detection_scale = float(state.get("last_detection_scale", 1.0))
        self._last_geometry_scale = float(state.get("last_geometry_scale", 1.0))
        self._last_preprocess_params = state.get(
            "last_preprocess_params", PreprocessParams()
        )
        self._last_detection_params = state.get(
            "last_detection_params", LineDetectionParams()
        )
        self._last_clean_params = state.get(
            "last_clean_params", GeometryCleanParams()
        )
        width_mm, _height_mm = self._pdf_page_sizes_mm[page_index]
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, image.shape[1] - 1)), 0.0),
            width_mm,
        )
        self._perspective_metadata = {
            "applied": True,
            "automatic": True,
            "source": "native_pdf_page",
            "page": page_index + 1,
            "warnings": [],
        }
        self._state_revision += 1
        self.original_canvas.set_image(image)
        self.corrected_canvas.set_image(image)
        if self.lines:
            self.detected_canvas.set_image(render_line_preview(image, self.lines))
        else:
            self.detected_canvas.set_image(None)
        self.info_label.setText(
            f"PDF 纸面坐标：{self.calibration.mm_per_pixel:.6f} mm/px；"
            "不是工程模型尺寸"
        )
        self.page_combo.blockSignals(True)
        self.page_combo.setCurrentIndex(page_index)
        self.page_combo.blockSignals(False)
        self.tabs.setCurrentWidget(
            self.detected_canvas if self.lines else self.original_canvas
        )
        processed = len(self._pdf_page_states)
        self.statusBar().showMessage(
            f"{self.current_path.name}：第 {page_index + 1}/{self._pdf_page_count} 页；"
            f"已有识别结果 {processed} 页"
        )

    def _on_pdf_page_changed(self, index: int) -> None:
        if self._native_pdf_mode and index >= 0 and index != self._current_pdf_page_index:
            self._load_pdf_page(index)

    def _previous_pdf_page(self) -> None:
        if self._native_pdf_mode:
            self._load_pdf_page(max(0, self._current_pdf_page_index - 1))

    def _next_pdf_page(self) -> None:
        if self._native_pdf_mode:
            self._load_pdf_page(
                min(self._pdf_page_count - 1, self._current_pdf_page_index + 1)
            )

    @staticmethod
    def _pdf_working_image(image):
        height, width = image.shape[:2]
        scale = min(1.0, MAX_PDF_VECTOR_DIMENSION / max(float(width), float(height)))
        if scale >= 0.999:
            return image.copy(), 1.0, 1.0
        target_width = max(1, int(round(width * scale)))
        target_height = max(1, int(round(height * scale)))
        work = cv2.resize(
            image,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
        return work, width / float(target_width), height / float(target_height)

    @staticmethod
    def _rescale_lines(lines, scale_x: float, scale_y: float):
        if abs(scale_x - 1.0) < 1e-9 and abs(scale_y - 1.0) < 1e-9:
            return list(lines)
        width_scale = (scale_x + scale_y) * 0.5
        return [
            line.copy(
                x1=line.x1 * scale_x,
                y1=line.y1 * scale_y,
                x2=line.x2 * scale_x,
                y2=line.y2 * scale_y,
                width=line.width * width_scale,
                history=tuple(dict.fromkeys(line.history + ("pdf_working_scale",))),
            )
            for line in lines
        ]

    def batch_vectorize_pdf(self) -> None:
        if not self._native_pdf_mode or self.current_path is None:
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        self._save_current_pdf_state()
        source_path = self.current_path
        page_count = self._pdf_page_count
        preprocess_params = PreprocessParams(
            threshold_strength=self.threshold_spin.value()
        )
        detection_params = LineDetectionParams(
            min_line_length=self.min_length_spin.value(),
            max_line_gap=max(2, int(round(self.bridge_spin.value()))),
        )
        clean_params = GeometryCleanParams(
            snap_distance=self.snap_spin.value(),
            max_bridge_gap=self.bridge_spin.value(),
            angle_tolerance=self.angle_spin.value(),
            min_line_length=max(5.0, self.min_length_spin.value() * 0.45),
        )
        preserve_hatch = self.keep_hatch.isChecked()
        run_started_at = datetime.now(timezone.utc)
        started = time.perf_counter()

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                progress(
                    f"批量识别第 {page_index + 1}/{page_count} 页",
                    page_index / max(page_count, 1),
                )
                image = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=PDF_BATCH_DPI,
                )
                work_image, scale_x, scale_y = self._pdf_working_image(image)
                result = PipelineService.vectorize(
                    work_image,
                    preprocess_params=preprocess_params,
                    detection_params=detection_params,
                    clean_params=clean_params,
                    preserve_hatch=preserve_hatch,
                    enable_auxiliary=False,
                    enable_ocr=False,
                    protect_text=True,
                    cancellation_token=token,
                )
                result.raw_lines = self._rescale_lines(result.raw_lines, scale_x, scale_y)
                result.lines = self._rescale_lines(result.lines, scale_x, scale_y)
                results[page_index] = self._state_from_vector_result(
                    result,
                    run_started_at,
                    preprocess_params,
                    detection_params,
                    clean_params,
                    image.shape[:2],
                )
                del result
                del work_image
                del image
            progress("批量识别完成", 1.0)
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
                "批量识别完成",
                f"已处理 {page_count} 页。请逐页使用“在图纸上可视化修改”复核；"
                "扫描底图始终保留。",
            )

        self._start_processing(operation, completed, "正在批量识别 PDF 页面…")

    @staticmethod
    def _state_from_vector_result(
        result: VectorizationResult,
        run_started_at,
        preprocess_params,
        detection_params,
        clean_params,
        vector_shape,
    ) -> dict[str, Any]:
        return {
            "raw_lines": list(result.raw_lines),
            "lines": list(result.lines),
            "geometry_report": result.geometry_report,
            "classification_report": result.classification_report,
            "auxiliary_result": result.auxiliary,
            "last_warnings": tuple(result.warnings),
            "run_started_at": run_started_at,
            "run_duration_seconds": None,
            "last_preprocess_scale": result.preprocess_resolution_scale,
            "last_detection_scale": result.detection_resolution_scale,
            "last_geometry_scale": result.geometry_resolution_scale,
            "last_preprocess_params": preprocess_params,
            "last_detection_params": detection_params,
            "last_clean_params": clean_params,
            "vector_shape": tuple(vector_shape),
        }

    def document_pages_for_export(self):
        if not self._native_pdf_mode or self.current_path is None:
            return iter(())
        self._save_current_pdf_state()
        source_path = self.current_path
        states = dict(self._pdf_page_states)
        sizes = dict(self._pdf_page_sizes_mm)
        count = self._pdf_page_count

        def pages():
            for page_index in range(count):
                raster = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=PDF_VIEW_DPI,
                )
                state = states.get(page_index, {})
                yield DocumentPage(
                    page_number=page_index + 1,
                    raster=raster,
                    page_size_mm=sizes[page_index],
                    lines=tuple(state.get("lines", ())),
                    vector_size_px=(
                        (int(state["vector_shape"][1]), int(state["vector_shape"][0]))
                        if state.get("vector_shape") is not None
                        else None
                    ),
                    label=f"{source_path.stem} - Page {page_index + 1}",
                )

        return pages()

    def detect_and_clean(self) -> None:
        if not self._native_pdf_mode:
            super().detect_and_clean()
            return
        if self.corrected_image is None:
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
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
        preprocess_params = PreprocessParams(
            threshold_strength=self.threshold_spin.value()
        )
        source = self.corrected_image.copy()
        work_image, scale_x, scale_y = self._pdf_working_image(source)
        preserve_hatch = self.keep_hatch.isChecked()
        revision = self._state_revision
        run_started_at = datetime.now(timezone.utc)
        started = time.perf_counter()

        def operation(token, progress) -> object:
            return PipelineService.vectorize(
                work_image,
                preprocess_params=preprocess_params,
                detection_params=detection,
                clean_params=cleaning,
                preserve_hatch=preserve_hatch,
                enable_auxiliary=False,
                enable_ocr=False,
                protect_text=True,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("页面已变化，已丢弃过期识别结果")
                return
            result: VectorizationResult = value  # type: ignore[assignment]
            self.binary_image = result.binary
            self.preprocess_stages = result.preprocess_stages
            self.raw_lines = self._rescale_lines(result.raw_lines, scale_x, scale_y)
            self.lines = self._rescale_lines(result.lines, scale_x, scale_y)
            self.geometry_report = result.geometry_report
            self.classification_report = result.classification_report
            self.auxiliary_result = None
            self.detected_canvas.set_image(render_line_preview(source, self.lines))
            self.tabs.setCurrentWidget(self.detected_canvas)
            self._run_started_at = run_started_at
            self._run_duration_seconds = time.perf_counter() - started
            self._last_preprocess_scale = result.preprocess_resolution_scale
            self._last_detection_scale = result.detection_resolution_scale
            self._last_geometry_scale = result.geometry_resolution_scale
            self._last_preprocess_params = preprocess_params
            self._last_detection_params = detection
            self._last_clean_params = cleaning
            scale_warning = (
                f"PDF 矢量识别使用最长边 {max(work_image.shape[:2])} px 工作图；"
                "原始扫描底图未降质。"
            )
            self._last_warnings = tuple(
                dict.fromkeys((*result.warnings, scale_warning))
            )
            self._save_current_pdf_state()
            self.statusBar().showMessage(
                f"第 {self._current_pdf_page_index + 1} 页识别完成；"
                f"保留 {len(self.lines)} 条结构线，文字与细节由扫描底图保真。"
            )

        self._start_processing(operation, completed, "正在识别当前 PDF 页面…")

    def _apply_paper_calibration(self) -> None:
        if self._native_pdf_mode:
            return
        super()._apply_paper_calibration()
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def auto_perspective(self) -> None:
        if self._native_pdf_mode:
            QMessageBox.information(
                self,
                "PDF 页面无需照片校正",
                "PDF 页面已按原始矩形纸面直接载入，不再执行照片透视校正。",
            )
            return
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
