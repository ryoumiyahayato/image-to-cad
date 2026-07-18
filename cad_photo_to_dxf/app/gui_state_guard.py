from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

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
from .cancellation import CancellationToken
from .document_export import DocumentPage
from .geometry_cleaner import GeometryCleanParams
from .gui_review import MainWindow as _ReviewedMainWindow
from .image_canvas import ImageCanvas
from .image_loader import load_image, pdf_page_count, pdf_page_size_mm
from .line_detect import LineDetectionParams, render_line_preview
from .pipeline_service import PipelineService
from .preprocess import PreprocessParams
from .scale_calibrator import ScaleCalibration


UNSCALED_LABEL = "比例：未校准（1 px = 1 个无单位图形单位）"
PDF_RENDER_DPI = 200


class MainWindow(_ReviewedMainWindow):
    """Final GUI with scan-faithful PDF pages and a simplified workflow."""

    def __init__(self) -> None:
        # These fields are needed while the inherited constructor builds controls.
        self._native_pdf_mode = False
        self._pdf_page_count = 1
        self._current_pdf_page_index = 0
        self._page_states: dict[int, dict[str, Any]] = {}
        self._switching_pdf_page = False
        self._dwg_converter_path: Path | None = None
        self._current_pdf_page: int | None = None
        super().__init__()
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
            "2. 自动识别纸张并校正": "2A. 照片自动校正（PDF 无需）",
            "手动点击四角并校正": "2B. 照片手动校正",
            "3. 图像预处理": "高级：单独查看预处理",
            "4. 识别并清理线条": "3. 自动识别结构线（可选）",
            "5. 可视化修改识别结果": "4. 在图纸上可视化修改",
            "5. 点击两点校准模型尺寸": "5. 模型尺寸校准（可选）",
            "6. 导出可编辑 DXF": "6. 导出同一 CAD（DWG / DXF）",
        }
        preprocess_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            original = button.text()
            replacement = button_names.get(original)
            if replacement is not None:
                button.setText(replacement)
            if original == "3. 图像预处理":
                preprocess_button = button
        if preprocess_button is not None:
            preprocess_button.setVisible(False)

        self._paper_group: QGroupBox | None = None
        for group in scroll.findChildren(QGroupBox):
            if group.title() in {"纸张坐标", "2. 纸张规格与坐标"}:
                group.setTitle("纸张与坐标（照片可选）")
                self._paper_group = group
                break

        page_group = QGroupBox("PDF 页面与合并")
        page_layout = QVBoxLayout(page_group)
        page_row = QHBoxLayout()
        page_row.addWidget(self._button("上一页", self._previous_pdf_page))
        self.page_combo = QComboBox()
        self.page_combo.addItem("单页", 0)
        self.page_combo.setEnabled(False)
        self.page_combo.currentIndexChanged.connect(self._on_pdf_page_changed)
        page_row.addWidget(self.page_combo, 1)
        page_row.addWidget(self._button("下一页", self._next_pdf_page))
        page_layout.addLayout(page_row)
        self.page_summary_label = QLabel("图片输入或单页 PDF")
        self.page_summary_label.setWordWrap(True)
        page_layout.addWidget(self.page_summary_label)
        self.merge_all_pages_checkbox = QCheckBox(
            "导出时把全部 PDF 页面合并到同一 CAD，并建立独立页面布局"
        )
        self.merge_all_pages_checkbox.setChecked(True)
        self.merge_all_pages_checkbox.setEnabled(False)
        page_layout.addWidget(self.merge_all_pages_checkbox)
        batch_button = self._button(
            "批量自动识别全部 PDF 页面（可取消）",
            self.batch_vectorize_pdf,
        )
        page_layout.addWidget(batch_button)
        self.batch_pdf_button = batch_button
        self.batch_pdf_button.setEnabled(False)
        layout.insertWidget(1, page_group)

        self.enable_ocr.setText("启用 OCR 文字识别（高级，需要 Tesseract）")

        view_group = QGroupBox("视图")
        view_layout = QVBoxLayout(view_group)
        view_buttons = QHBoxLayout()
        view_buttons.addWidget(self._button("放大", self._zoom_in))
        view_buttons.addWidget(self._button("缩小", self._zoom_out))
        view_buttons.addWidget(self._button("适应窗口", self._fit_view))
        view_buttons.addWidget(self._button("100%", self._actual_size))
        view_layout.addLayout(view_buttons)
        hint = QLabel(
            "鼠标滚轮缩放；左键拖动平移；双击适应窗口。"
            "缩小时使用保线条预览，避免细线被直接采样丢失。"
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
            "将高置信度 OCR 结果另存为可编辑 TEXT（仍需人工校对）"
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
            "多页 PDF 会在一个模型空间中按页排列，并生成 PAGE_001、PAGE_002…布局。"
            "DWG 仍由本机 ODA File Converter 转换；所有 .scan.png 必须与 CAD 一起移动。"
        )
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)

        detect_button = next(
            (
                button
                for button in scroll.findChildren(QPushButton)
                if button.text().startswith("3. 自动识别结构线")
            ),
            None,
        )
        view_index = layout.indexOf(detect_button) if detect_button else -1
        layout.insertWidget(view_index if view_index >= 0 else 6, view_group)
        export_button = next(
            (
                button
                for button in scroll.findChildren(QPushButton)
                if button.text().startswith("6. 导出同一 CAD")
            ),
            None,
        )
        export_index = layout.indexOf(export_button) if export_button else -1
        layout.insertWidget(
            export_index if export_index >= 0 else max(0, layout.count() - 1),
            export_group,
        )
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
                self._page_states = {}
                self.page_combo.blockSignals(True)
                self.page_combo.clear()
                for index in range(count):
                    self.page_combo.addItem(f"第 {index + 1} / {count} 页", index)
                self.page_combo.setCurrentIndex(0)
                self.page_combo.blockSignals(False)
                self.page_combo.setEnabled(count > 1)
                self.merge_all_pages_checkbox.setEnabled(count > 1)
                self.batch_pdf_button.setEnabled(count > 1)
                if self._paper_group is not None:
                    self._paper_group.setEnabled(False)
                self._load_pdf_page(0)
                return
            image = load_image(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        self._native_pdf_mode = False
        self._pdf_page_count = 1
        self._current_pdf_page_index = 0
        self._current_pdf_page = None
        self._page_states = {}
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItem("单页图片", 0)
        self.page_combo.blockSignals(False)
        self.page_combo.setEnabled(False)
        self.merge_all_pages_checkbox.setEnabled(False)
        self.batch_pdf_button.setEnabled(False)
        if self._paper_group is not None:
            self._paper_group.setEnabled(True)
        self.current_path = file_path
        self._set_single_image_state(image)
        self.page_summary_label.setText("单页图片；如为照片，请先完成纸张校正。")
        self.statusBar().showMessage(f"已导入：{self.current_path.name}")

    def _set_single_image_state(self, image) -> None:
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
        self.info_label.setText(UNSCALED_LABEL)
        self.tabs.setCurrentWidget(self.original_canvas)

    def _save_current_pdf_state(self) -> None:
        if not self._native_pdf_mode:
            return
        self._page_states[self._current_pdf_page_index] = {
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
        }

    def _load_pdf_page(self, page_index: int) -> None:
        if self.current_path is None:
            return
        image = load_image(
            self.current_path,
            page_index=page_index,
            pdf_dpi=PDF_RENDER_DPI,
        )
        size_mm = pdf_page_size_mm(self.current_path, page_index)
        self._current_pdf_page_index = page_index
        self._current_pdf_page = page_index + 1
        self.original_image = image
        # A PDF page is already a rectified sheet.  Do not degrade it by running
        # photographed-paper boundary detection unless the user imports a photo.
        self.corrected_image = image
        self.binary_image = None
        self.preprocess_stages = {}
        self.selection_mode = None
        self.selected_points = []
        self._clear_preprocess_tabs()
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, image.shape[1] - 1)), 0.0),
            size_mm[0],
        )
        self._perspective_metadata = {
            "applied": False,
            "automatic": False,
            "source_pdf_native_page": True,
            "pdf_page": page_index + 1,
            "render_dpi": PDF_RENDER_DPI,
            "warnings": [],
        }
        state = self._page_states.get(page_index, {})
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
        self._state_revision += 1
        self.original_canvas.set_image(image)
        self.corrected_canvas.set_image(image)
        self.original_canvas.set_selection_enabled(False)
        self.corrected_canvas.set_selection_enabled(False)
        if self.lines:
            self.detected_canvas.set_image(render_line_preview(image, self.lines))
            self.tabs.setCurrentWidget(self.detected_canvas)
        else:
            self.detected_canvas.set_image(None)
            self.tabs.setCurrentWidget(self.original_canvas)
        self.info_label.setText(
            f"PDF 纸面坐标：{size_mm[0]:.2f} × {size_mm[1]:.2f} mm；"
            "扫描底图是视觉基准，不等于工程模型尺寸。"
        )
        self.page_combo.blockSignals(True)
        self.page_combo.setCurrentIndex(page_index)
        self.page_combo.blockSignals(False)
        processed = "已识别并可修改" if self.lines else "尚未识别；可直接保真导出"
        self.page_summary_label.setText(
            f"第 {page_index + 1} / {self._pdf_page_count} 页；{processed}。"
            "PDF 页面无需透视校正。"
        )
        self.statusBar().showMessage(
            f"已加载 {self.current_path.name} 第 {page_index + 1}/{self._pdf_page_count} 页"
        )

    def _on_pdf_page_changed(self, index: int) -> None:
        if self._switching_pdf_page or not self._native_pdf_mode:
            return
        target = self.page_combo.itemData(index)
        if not isinstance(target, int) or target == self._current_pdf_page_index:
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待处理完成后再切换页面。")
            self.page_combo.blockSignals(True)
            self.page_combo.setCurrentIndex(self._current_pdf_page_index)
            self.page_combo.blockSignals(False)
            return
        self._switching_pdf_page = True
        try:
            self._save_current_pdf_state()
            self._load_pdf_page(target)
        except Exception as exc:
            QMessageBox.critical(self, "页面切换失败", str(exc))
        finally:
            self._switching_pdf_page = False

    def _previous_pdf_page(self) -> None:
        if self._native_pdf_mode and self._current_pdf_page_index > 0:
            self.page_combo.setCurrentIndex(self._current_pdf_page_index - 1)

    def _next_pdf_page(self) -> None:
        if (
            self._native_pdf_mode
            and self._current_pdf_page_index + 1 < self._pdf_page_count
        ):
            self.page_combo.setCurrentIndex(self._current_pdf_page_index + 1)

    def batch_vectorize_pdf(self) -> None:
        if not self._native_pdf_mode or self.current_path is None:
            QMessageBox.information(self, "不是多页 PDF", "当前没有可批量处理的 PDF。")
            return
        self._save_current_pdf_state()
        source_path = self.current_path
        page_count = self._pdf_page_count
        preprocess_params = PreprocessParams(threshold_strength=self.threshold_spin.value())
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
        start_clock = time.perf_counter()

        def operation(token: CancellationToken, progress) -> object:
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
                    pdf_dpi=PDF_RENDER_DPI,
                )
                result = PipelineService.vectorize(
                    image,
                    preprocess_params=preprocess_params,
                    detection_params=detection_params,
                    clean_params=clean_params,
                    preserve_hatch=preserve_hatch,
                    enable_auxiliary=False,
                    enable_ocr=False,
                    protect_text=True,
                    cancellation_token=token,
                )
                results[page_index] = {
                    "raw_lines": list(result.raw_lines),
                    "lines": list(result.lines),
                    "geometry_report": result.geometry_report,
                    "classification_report": result.classification_report,
                    "auxiliary_result": None,
                    "last_warnings": tuple(result.warnings),
                    "run_started_at": run_started_at,
                    "run_duration_seconds": None,
                    "last_preprocess_scale": result.preprocess_resolution_scale,
                    "last_detection_scale": result.detection_resolution_scale,
                    "last_geometry_scale": result.geometry_resolution_scale,
                    "last_preprocess_params": preprocess_params,
                    "last_detection_params": detection_params,
                    "last_clean_params": clean_params,
                }
                del result
                del image
            progress("批量识别完成", 1.0)
            return results

        def completed(value: object) -> None:
            results = value  # type: ignore[assignment]
            duration = time.perf_counter() - start_clock
            for page_index, state in results.items():
                state["run_duration_seconds"] = duration
                self._page_states[page_index] = state
            self._load_pdf_page(self._current_pdf_page_index)
            QMessageBox.information(
                self,
                "批量识别完成",
                f"已处理 {page_count} 页。请逐页使用“在图纸上可视化修改”复核；"
                "扫描底图始终保留。",
            )

        self._start_processing(operation, completed, "正在批量识别 PDF 页面…")

    def document_pages_for_export(self) -> list[DocumentPage]:
        if not self._native_pdf_mode or self.current_path is None:
            return []
        self._save_current_pdf_state()
        pages: list[DocumentPage] = []
        for page_index in range(self._pdf_page_count):
            state = self._page_states.get(page_index, {})
            pages.append(
                DocumentPage(
                    page_number=page_index + 1,
                    source_path=self.current_path,
                    lines=tuple(state.get("lines", ())),
                    page_size_mm=pdf_page_size_mm(self.current_path, page_index),
                    label=f"{self.current_path.stem} - Page {page_index + 1}",
                )
            )
        return pages

    def _calibration_semantics(self) -> tuple[str, str, list[str]]:
        if self._native_pdf_mode:
            return (
                "pdf_page_dimensions",
                "paper_mm",
                [
                    "PDF 页面坐标来自页面纸面尺寸；不是原始工程模型尺寸。"
                ],
            )
        return super()._calibration_semantics()

    def _apply_paper_calibration(self) -> None:
        if self._native_pdf_mode and self.current_path is not None and self.corrected_image is not None:
            width_mm, _height_mm = pdf_page_size_mm(
                self.current_path, self._current_pdf_page_index
            )
            self.calibration = ScaleCalibration(
                (0.0, 0.0),
                (float(max(1, self.corrected_image.shape[1] - 1)), 0.0),
                width_mm,
            )
            return
        super()._apply_paper_calibration()
        if self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)

    def auto_perspective(self) -> None:
        if self._native_pdf_mode:
            QMessageBox.information(
                self,
                "PDF 无需纸张校正",
                "PDF 页面已经是矩形页面。为避免裁切和失真，程序直接使用原始页面渲染。",
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
        if self._native_pdf_mode:
            QMessageBox.information(
                self,
                "PDF 保持原方向",
                "多页 PDF 合并时按每页原始方向输出，避免页面与扫描底图错位。",
            )
            return
        revision_before = self._state_revision
        metadata_before = deepcopy(self._perspective_metadata)
        super().rotate_corrected(degrees)
        if self._state_revision == revision_before:
            self._perspective_metadata = metadata_before
        elif self.calibration is None:
            self.info_label.setText(UNSCALED_LABEL)
