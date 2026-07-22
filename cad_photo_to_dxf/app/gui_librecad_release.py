from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
)

from .gui_exact_release import MainWindow as _ExactMainWindow
from .gui_trace_release import TRACE_PDF_DPI
from .image_loader import load_image
from .librecad_ocr_review import LibreCadLffOcrReviewDialog as _BaseOcrReviewDialog
from .ocr_outline_export import accepted_ocr_texts
from .optimized_trace import trace_image_optimized
from .raster_trace import RasterTraceResult
from .scale_calibrator import ScaleCalibration
from .trace_storage import load_trace_cache, save_trace_cache


PREVIEW_MAX_DIMENSION = 2400
SIDEBAR_WIDTH = 390


class LibreCadOcrReviewDialog(_BaseOcrReviewDialog):
    """Keep the proven LibreCAD glyph preview but present it as normal text review."""

    def __init__(self, image, candidates, parent=None) -> None:
        super().__init__(image, candidates, parent)
        self.setWindowTitle("检查文字识别结果")
        if self.preview_checkbox is not None:
            self.preview_checkbox.setText("在原图上显示已确认文字")
        for label in self.findChildren(QLabel):
            text = label.text()
            if (
                "LibreCAD 中文字体" in text
                or "LFF" in text
                or "Windows 的 TTF" in text
                or "字形来源：LibreCAD" in text
            ):
                label.setVisible(False)
        for button in self.findChildren(QPushButton):
            if "安装/修复 LibreCAD" in button.text() or "使用 LibreCAD 字体" in button.text():
                button.setVisible(False)

    def accept(self) -> None:  # type: ignore[override]
        # Saving unchanged review must not approve the selected pending candidate.
        QDialog.accept(self)


class MainWindow(_ExactMainWindow):
    """Optimized normal UI with exact content, OCR deduplication and safe caching."""

    def __init__(self) -> None:
        # Font discovery previously ran PowerShell, registry scans and a 43 MB copy
        # before the first window appeared. It is now delayed until text review.
        self._librecad_font_install_report = None
        super().__init__()
        splitter = self.centralWidget()
        if isinstance(splitter, QSplitter):
            splitter.setCollapsible(0, False)
            controls = splitter.widget(0)
            if controls is not None:
                controls.setMinimumWidth(360)
            splitter.setSizes([SIDEBAR_WIDTH, max(900, self.width() - SIDEBAR_WIDTH)])
        self.statusBar().showMessage("可处理当前页或全部页面")

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        if isinstance(scroll, QScrollArea):
            scroll.setMinimumWidth(360)

        self.tabs.setTabText(self.tabs.indexOf(self.original_canvas), "原图")
        self.tabs.setTabText(self.tabs.indexOf(self.corrected_canvas), "校正图")
        self.tabs.setTabText(self.tabs.indexOf(self.detected_canvas), "CAD 预览")

        title_map = {
            "CAD 轮廓生成": "生成 CAD",
            "检查与验证": "检查与修改",
            "文字 OCR 与可编辑文字": "文字识别",
            "CAD 输出设置": "输出设置",
        }
        for group in scroll.findChildren(QGroupBox):
            replacement = title_map.get(group.title())
            if replacement is not None:
                group.setTitle(replacement)

        button_map = {
            "生成当前页 CAD 轮廓": "处理当前页",
            "生成当前 PDF 全部页 CAD 轮廓": "处理全部页面",
            "检查并修正当前页 CAD 轮廓": "检查并修改当前页",
            "验证当前页": "核对当前页",
            "检查并修改 OCR 文字": "检查文字识别结果",
            "导出当前 PDF 全部页 CAD（DWG / DXF）": "导出 CAD（每页独立文件）",
        }
        for button in scroll.findChildren(QPushButton):
            replacement = button_map.get(button.text())
            if replacement is not None:
                button.setText(replacement)

        checkbox = getattr(self, "ocr_before_trace_checkbox", None)
        if isinstance(checkbox, QCheckBox):
            checkbox.setText("识别文字并生成可编辑文字")
            checkbox.setToolTip(
                "识别可靠的印刷文字；无法确认的签名、手写内容或局部文字保留原图形。"
            )

        for label in scroll.findChildren(QLabel):
            text = label.text()
            if text.startswith("OCR 结果按完整文字行"):
                label.setText(
                    "文字会逐字导出为可编辑内容；无法可靠识别的部分保留原图形。"
                )
            elif "直线：蓝色；曲线：绿色；文字/符号" in text:
                label.setText("不同内容使用不同颜色，便于检查。")
            elif "可生成当前页" in text or "已载入" in text:
                label.setText("可处理当前页，也可连续处理全部页面。")

        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "可处理当前页或全部页面；导出时每页生成一个独立文件。"
            )
        return scroll

    @staticmethod
    def _scaled_for_preview(
        image: np.ndarray,
        *,
        target_shape: tuple[int, int] | None = None,
    ) -> np.ndarray:
        height, width = image.shape[:2]
        if target_shape is not None:
            target_height, target_width = target_shape
            if target_height > 0 and target_width > 0 and (
                target_height != height or target_width != width
            ):
                return cv2.resize(
                    image,
                    (int(target_width), int(target_height)),
                    interpolation=cv2.INTER_AREA,
                )
        maximum = max(height, width)
        if maximum <= PREVIEW_MAX_DIMENSION:
            return image
        ratio = PREVIEW_MAX_DIMENSION / float(maximum)
        return cv2.resize(
            image,
            (
                max(1, int(round(width * ratio))),
                max(1, int(round(height * ratio))),
            ),
            interpolation=cv2.INTER_AREA,
        )

    def _preview_shape(self) -> tuple[int, int] | None:
        if self.original_image is None:
            return None
        return tuple(int(value) for value in self.original_image.shape[:2])

    def _load_trace_source_for_current_page(self):
        if not self._native_pdf_mode or self.current_path is None:
            if self.corrected_image is None:
                raise ValueError("当前页面尚未载入")
            return np.ascontiguousarray(self.corrected_image.copy())
        image = load_image(
            self.current_path,
            page_index=self._current_pdf_page_index,
            pdf_dpi=TRACE_PDF_DPI,
            grayscale=True,
        )
        width_mm, _height_mm = self._pdf_page_sizes_mm[self._current_pdf_page_index]
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, image.shape[1] - 1)), 0.0),
            width_mm,
        )
        self._update_scale_label()
        return image

    def _apply_trace_result(
        self,
        result: RasterTraceResult,
        *,
        started_at: datetime,
        duration: float,
        save_pdf_state: bool,
    ) -> None:
        self._ocr_texts = tuple(result.texts)
        self._dirty_trace_keys.add(self._current_trace_key())
        self.binary_image = result.binary
        self.preprocess_stages = {}
        self._clear_preprocess_tabs()
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
        preview = self._scaled_for_preview(
            result.binary,
            target_shape=self._preview_shape(),
        )
        self.corrected_canvas.set_image(preview)
        self.detected_canvas.set_image(preview)
        self.tabs.setCurrentWidget(self.detected_canvas)
        self._run_started_at = started_at
        self._run_duration_seconds = duration
        self._last_warnings = tuple(result.warnings)
        if save_pdf_state:
            self._save_current_pdf_state()
        self._update_scale_label()
        safe = sum(1 for item in result.texts if item.replacement_safe)
        pending = len(result.texts) - safe
        self.statusBar().showMessage(
            f"当前页处理完成：文字 {safe} 项，保留原图形待确认 {pending} 项"
        )

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        state = self._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if not cache_value:
            self._clear_trace_state()
            self.binary_image = None
            self.preprocess_stages = {}
            self._clear_preprocess_tabs()
            self._ocr_texts = ()
            return
        cache_path = Path(str(cache_value))
        stored = load_trace_cache(cache_path)
        self._trace_cache_by_key[self._current_trace_key()] = cache_path
        self.binary_image = stored.binary
        self._trace_paths = stored.paths
        self._trace_threshold = stored.threshold
        self._trace_foreground_pixels = stored.foreground_pixels
        self._trace_vertex_count = stored.vertex_count
        self._last_warnings = stored.warnings
        self._ocr_texts = stored.texts
        self._dirty_trace_keys.discard(self._current_trace_key())
        self.preprocess_stages = {}
        self._clear_preprocess_tabs()
        preview = self._scaled_for_preview(
            stored.binary,
            target_shape=self._preview_shape(),
        )
        self.corrected_canvas.set_image(preview)
        self.detected_canvas.set_image(preview)
        self.tabs.setCurrentWidget(self.detected_canvas)
        width_mm, _height_mm = self._pdf_page_sizes_mm[page_index]
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, stored.binary.shape[1] - 1)), 0.0),
            width_mm,
        )
        self._update_scale_label()

    @staticmethod
    def _stage_text(stage: str) -> str:
        if stage.startswith("ocr"):
            return "识别文字"
        if stage.startswith("trace") or stage == "prepare-image":
            return "生成 CAD 内容"
        return "处理页面"

    def detect_and_clean(self) -> None:
        if self.corrected_image is None and not self._require_corrected():
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        try:
            source = self._load_trace_source_for_current_page()
        except Exception as exc:
            QMessageBox.critical(self, "读取页面失败", str(exc))
            return
        revision = self._state_revision
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        enable_ocr = self._ocr_enabled()

        def operation(token, progress) -> object:
            return trace_image_optimized(
                source,
                enable_ocr=enable_ocr,
                cancellation_token=token,
                progress_callback=lambda stage, fraction: progress(
                    self._stage_text(stage), fraction
                ),
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("页面已变化，已丢弃过期结果")
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )

        self._start_processing(operation, completed, "正在处理当前页…")

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
        cache_root = Path(self._trace_cache_tempdir.name)
        enable_ocr = self._ocr_enabled()

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                key = self._source_key(source_path, page_index)
                old_state = self._pdf_page_states.get(page_index, {})
                old_cache = old_state.get("trace_cache_path")
                if (
                    key not in self._dirty_trace_keys
                    and old_cache
                    and Path(str(old_cache)).exists()
                ):
                    results[page_index] = dict(old_state)
                    progress(
                        f"第 {page_index + 1}/{page_count} 页：使用已有结果",
                        (page_index + 1) / max(page_count, 1),
                    )
                    continue

                image = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=TRACE_PDF_DPI,
                    grayscale=True,
                )

                def page_progress(stage: str, fraction: float) -> None:
                    progress(
                        f"第 {page_index + 1}/{page_count} 页：{self._stage_text(stage)}",
                        (page_index + max(0.0, min(1.0, fraction)))
                        / max(page_count, 1),
                    )

                result = trace_image_optimized(
                    image,
                    enable_ocr=enable_ocr,
                    cancellation_token=token,
                    progress_callback=page_progress,
                )
                digest = sha256(f"{key[0]}|{key[1]}".encode("utf-8")).hexdigest()[:24]
                cache_path = cache_root / f"trace-{digest}.npz"
                save_trace_cache(cache_path, result)
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
                    "trace_cache_path": str(cache_path),
                    "trace_threshold": result.threshold,
                    "trace_foreground_pixels": result.foreground_pixels,
                    "trace_vertex_count": result.vertex_count,
                    "ocr_text_count": len(result.texts),
                    "drawing_scale": drawing_scale,
                    "trace_color": 7,
                }
                del image
                del result
            progress("全部页面处理完成", 1.0)
            return results

        def completed(value: object) -> None:
            results = value  # type: ignore[assignment]
            duration = time.perf_counter() - started
            total_texts = 0
            for page_index, state in results.items():
                state["run_duration_seconds"] = duration
                total_texts += int(state.get("ocr_text_count", 0))
                key = self._source_key(source_path, page_index)
                cache_value = state.get("trace_cache_path")
                if cache_value:
                    self._trace_cache_by_key[key] = Path(str(cache_value))
            self._pdf_page_states.update(results)
            self._load_pdf_page(self._current_pdf_page_index, save_current=False)
            QMessageBox.information(
                self,
                "处理完成",
                f"已处理 {page_count} 页，找到 {total_texts} 个文字候选。\n"
                "现在可以导出 CAD。",
            )

        self._start_processing(operation, completed, "正在处理全部页面…")

    def review_ocr_texts(self) -> None:
        if not self._ocr_texts:
            QMessageBox.warning(self, "尚无文字结果", "请先处理当前页。")
            return
        try:
            if self._native_pdf_mode and self.current_path is not None:
                source = load_image(
                    self.current_path,
                    page_index=self._current_pdf_page_index,
                    pdf_dpi=TRACE_PDF_DPI,
                    grayscale=True,
                )
            else:
                source = (
                    self.corrected_image
                    if self.corrected_image is not None
                    else self.original_image
                )
        except Exception as exc:
            QMessageBox.critical(self, "读取页面失败", str(exc))
            return
        if source is None:
            return
        dialog = LibreCadOcrReviewDialog(source, tuple(self._ocr_texts), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._ocr_texts = dialog.reviewed_texts()
        self._dirty_trace_keys.add(self._current_trace_key())
        if self._native_pdf_mode:
            self._save_current_pdf_state()
        exportable = accepted_ocr_texts(self._ocr_texts)
        pending = sum(
            1
            for item in self._ocr_texts
            if item.approved and not item.reviewed and not item.replacement_safe
        )
        character_count = sum(
            1
            for item in exportable
            for character in item.text
            if not character.isspace()
        )
        self.statusBar().showMessage(
            f"文字检查已保存：{character_count} 个可编辑字符，{pending} 项保留原图形"
        )
