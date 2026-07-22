from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any

from PySide6.QtWidgets import QGroupBox, QLabel, QMessageBox, QPushButton

from .document_export import DocumentPage
from .gui_trace_mode import MainWindow as _TraceMainWindow
from .image_loader import load_image
from .raster_trace import RasterTraceResult, trace_image
from .scale_calibrator import ScaleCalibration
from .trace_gui_export import export_trace_from_window
from .trace_storage import load_trace_cache, save_trace_cache
from .trace_verification import TraceVerificationResult, verify_trace_paths


TRACE_PDF_DPI = 300


class MainWindow(_TraceMainWindow):
    """Exact CAD-contour workflow with responsive export and visual verification."""

    def __init__(self) -> None:
        self._trace_cache_tempdir = TemporaryDirectory(prefix="image-to-cad-trace-")
        self._trace_cache_by_key: dict[tuple[str, int | None], Path] = {}
        super().__init__()
        self._update_scale_label()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        for group in scroll.findChildren(QGroupBox):
            if group.title() == "跨文件合并队列":
                group.setVisible(False)
            elif group.title() == "PDF 页面与合并":
                group.setTitle("当前 PDF 页面")
            elif group.title() == "拓印输出与比例尺":
                group.setTitle("CAD 输出设置")

        rename = {
            "完整拓印全部黑白线条": "生成当前页 CAD 轮廓",
            "在黑白拓印图上修补": "检查并修正当前页 CAD 轮廓",
            "按已知尺寸校准（照片补充）": "按已知尺寸校准（可选）",
            "导出同一 CAD（DWG / DXF）": "导出当前 PDF 全部页 CAD（DWG / DXF）",
        }
        review_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            if button.text() in rename:
                button.setText(rename[button.text()])
            if button.text() == "检查并修正当前页 CAD 轮廓":
                review_button = button

        self.batch_pdf_button.setText("生成当前 PDF 的全部页 CAD 轮廓（可取消）")
        self.drawing_scale_spin.blockSignals(True)
        self.drawing_scale_spin.setValue(1)
        self.drawing_scale_spin.blockSignals(False)
        self.drawing_scale_spin.setToolTip(
            "默认按 1:1 输出。只有明确需要按图纸比例还原模型尺寸时才修改。"
        )

        self.trace_color_combo.setVisible(False)
        scale_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "CAD 输出设置"
            ),
            None,
        )
        if scale_group is not None:
            for label in scale_group.findChildren(QLabel):
                if label.text() == "CAD 拓印颜色":
                    label.setVisible(False)
            scale_layout = scale_group.layout()
            if scale_layout is not None and hasattr(scale_layout, "addRow"):
                palette_label = QLabel(
                    "直线：蓝色；曲线：绿色；文字/符号：品红色。"
                    "颜色分类只用于检查，不会改变轮廓坐标。",
                    scale_group,
                )
                palette_label.setWordWrap(True)
                scale_layout.addRow("自动分层颜色", palette_label)

        verify_button = QPushButton("验证当前页与原图是否一致", container)
        verify_button.clicked.connect(self.verify_current_trace)
        review_index = layout.indexOf(review_button) if review_button is not None else -1
        layout.insertWidget(review_index + 1 if review_index >= 0 else 5, verify_button)

        self.include_underlay_checkbox.setChecked(False)
        self.include_underlay_checkbox.setText(
            "附加原扫描底图（仅需在 CAD 中对照时开启；会增加文件和导出时间）"
        )
        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "同一个 PDF 的所有页将一次性生成并导出为一个 CAD 文件。"
            )
        return scroll

    def _drawing_scale(self) -> float:
        spin = getattr(self, "drawing_scale_spin", None)
        return float(spin.value()) if spin is not None else 1.0

    def _trace_color(self) -> int:
        return 7

    def _has_explicit_model_calibration(self) -> bool:
        if self._native_pdf_mode or self.calibration is None:
            return False
        try:
            _source, coordinate_space, _warnings = self._calibration_semantics()
        except Exception:
            return False
        return coordinate_space == "model_mm"

    def _export_drawing_multiplier(self) -> float:
        if self._has_explicit_model_calibration():
            return 1.0
        if self.calibration is None:
            return 1.0
        return self._drawing_scale()

    def _update_scale_label(self) -> None:
        label = getattr(self, "scale_result_label", None)
        if label is None:
            return
        if self.calibration is None:
            label.setText("输出比例 1:1；尚未标定纸面或模型尺寸")
            return
        if self._has_explicit_model_calibration():
            label.setText(
                f"已知尺寸标定：{self.calibration.mm_per_pixel:.6f} 模型 mm/px；"
                "不会再叠加图纸比例"
            )
            self.info_label.setText(
                f"工程模型坐标：{self.calibration.mm_per_pixel:.6f} mm/px；"
                f"{self.calibration.pixel_distance:.2f} px = "
                f"{self.calibration.actual_length_mm:.3f} mm"
            )
            return
        ratio = self._drawing_scale()
        model_mm_per_pixel = self.calibration.mm_per_pixel * ratio
        label.setText(
            f"输出比例 1:{int(ratio)}；{model_mm_per_pixel:.6f} 模型 mm/px "
            f"（纸面 {self.calibration.mm_per_pixel:.6f} mm/px）"
        )
        self.info_label.setText(
            f"输出比例 1:{int(ratio)}；模型坐标 {model_mm_per_pixel:.6f} mm/px"
        )

    def _on_corrected_point(self, x: float, y: float) -> None:
        super()._on_corrected_point(x, y)
        self._update_scale_label()

    @staticmethod
    def _source_key(
        source_path: Path | None,
        page_index: int | None,
        fallback: str = "unsaved",
    ) -> tuple[str, int | None]:
        source = str(source_path.resolve()) if source_path is not None else fallback
        return source, page_index

    def _current_trace_key(self) -> tuple[str, int | None]:
        page_index = self._current_pdf_page_index if self._native_pdf_mode else None
        return self._source_key(self.current_path, page_index)

    def _cache_path_for_key(self, key: tuple[str, int | None]) -> Path:
        digest = sha256(f"{key[0]}|{key[1]}".encode("utf-8")).hexdigest()[:24]
        return Path(self._trace_cache_tempdir.name) / f"trace-{digest}.npz"

    def _store_current_trace(self) -> Path | None:
        if self.binary_image is None or not self._trace_paths:
            return None
        key = self._current_trace_key()
        target = self._trace_cache_by_key.get(key, self._cache_path_for_key(key))
        result = RasterTraceResult(
            binary=self.binary_image,
            stages=dict(self.preprocess_stages),
            paths=tuple(self._trace_paths),
            threshold=int(self._trace_threshold or 128),
            foreground_pixels=int(self._trace_foreground_pixels),
            vertex_count=int(self._trace_vertex_count),
            warnings=tuple(self._last_warnings),
        )
        save_trace_cache(target, result)
        self._trace_cache_by_key[key] = target
        return target

    def _save_current_pdf_state(self) -> None:
        super()._save_current_pdf_state()
        if not self._native_pdf_mode:
            return
        state = self._pdf_page_states.get(self._current_pdf_page_index)
        if state is None:
            return
        cache_path = self._store_current_trace()
        if cache_path is not None:
            state["trace_cache_path"] = str(cache_path)
        state["drawing_scale"] = self._drawing_scale()
        state["trace_color"] = 7
        state.pop("binary_image", None)
        state.pop("preprocess_stages", None)
        state.pop("trace_paths", None)

    def _load_trace_source_for_current_page(self):
        if not self._native_pdf_mode or self.current_path is None:
            return self.corrected_image.copy()
        image = load_image(
            self.current_path,
            page_index=self._current_pdf_page_index,
            pdf_dpi=TRACE_PDF_DPI,
        )
        self.original_image = image
        self.corrected_image = image.copy()
        width_mm, _height_mm = self._pdf_page_sizes_mm[self._current_pdf_page_index]
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, image.shape[1] - 1)), 0.0),
            width_mm,
        )
        self.original_canvas.set_image(image)
        self.corrected_canvas.set_image(image)
        self._update_scale_label()
        return image.copy()

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        state = self._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if not cache_value:
            self._clear_trace_state()
            self.binary_image = None
            self.preprocess_stages = {}
            self._clear_preprocess_tabs()
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

        source = load_image(
            self.current_path,
            page_index=page_index,
            pdf_dpi=TRACE_PDF_DPI,
        )
        self.original_image = source
        self.corrected_image = source.copy()
        width_mm, _height_mm = self._pdf_page_sizes_mm[page_index]
        self.calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, source.shape[1] - 1)), 0.0),
            width_mm,
        )
        self.preprocess_stages = {
            "原图": source,
            "CAD 轮廓来源": stored.binary,
        }
        self._show_preprocess_stages(self.preprocess_stages)
        self.original_canvas.set_image(source)
        self.corrected_canvas.set_image(stored.binary)
        self.detected_canvas.set_image(stored.binary)
        self.tabs.setCurrentWidget(self.detected_canvas)
        self._update_scale_label()

    def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
        super()._load_pdf_page(page_index, save_current=save_current)
        if self._native_pdf_mode:
            try:
                self._restore_cached_trace_for_page(page_index)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "读取 CAD 轮廓缓存失败",
                    f"第 {page_index + 1} 页需要重新生成。\n{exc}",
                )

    def detect_and_clean(self) -> None:
        if self.corrected_image is None and not self._require_corrected():
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        try:
            source = self._load_trace_source_for_current_page()
        except Exception as exc:
            QMessageBox.critical(self, "读取高精度页面失败", str(exc))
            return
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
                self.statusBar().showMessage("页面已变化，已丢弃过期结果")
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )
            self.statusBar().showMessage(
                f"当前页 CAD 轮廓已生成：{len(self._trace_paths)} 个边界，"
                f"{self._trace_vertex_count} 个顶点"
            )

        self._start_processing(
            operation,
            completed,
            f"正在以 {TRACE_PDF_DPI} DPI 生成当前页 CAD 轮廓…",
        )

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

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                progress(
                    f"生成第 {page_index + 1}/{page_count} 页 CAD 轮廓",
                    page_index / max(page_count, 1),
                )
                image = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=TRACE_PDF_DPI,
                )
                result = trace_image(image, cancellation_token=token)
                key = self._source_key(source_path, page_index)
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
                    "drawing_scale": drawing_scale,
                    "trace_color": 7,
                }
                del image
                del result
            progress("全部页面 CAD 轮廓生成完成", 1.0)
            return results

        def completed(value: object) -> None:
            results = value  # type: ignore[assignment]
            duration = time.perf_counter() - started
            for page_index, state in results.items():
                state["run_duration_seconds"] = duration
                key = self._source_key(source_path, page_index)
                self._trace_cache_by_key[key] = Path(state["trace_cache_path"])
            self._pdf_page_states.update(results)
            self._load_pdf_page(self._current_pdf_page_index, save_current=False)
            QMessageBox.information(
                self,
                "全部页面处理完成",
                f"已用相同的 {TRACE_PDF_DPI} DPI 流程处理 {page_count} 页。\n"
                "现在可一次性导出当前 PDF 的全部页面。",
            )

        self._start_processing(operation, completed, "正在生成当前 PDF 的全部页 CAD 轮廓…")

    def verify_current_trace(self) -> None:
        if self.binary_image is None or not self._trace_paths:
            QMessageBox.warning(self, "尚无 CAD 轮廓", "请先生成当前页 CAD 轮廓。")
            return
        if self._is_processing():
            QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
            return
        binary = self.binary_image.copy()
        paths = tuple(self._trace_paths)
        revision = self._state_revision

        def operation(token, progress) -> object:
            return verify_trace_paths(
                binary,
                paths,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            result: TraceVerificationResult = value  # type: ignore[assignment]
            self.preprocess_stages["CAD 一致性验证"] = result.overlay
            self._show_preprocess_stages(self.preprocess_stages)
            canvas = self.preprocess_canvases.get("CAD 一致性验证")
            if canvas is not None:
                self.preprocess_tabs.setCurrentWidget(canvas)
            self.tabs.setCurrentWidget(self.preprocess_tabs)
            message = (
                "蓝色：原图与将导出的 CAD 轮廓一致；红色：原图有但 CAD 缺失；"
                "品红色：CAD 多出。\n\n"
                f"一致像素：{result.matched_pixels}\n"
                f"缺失像素：{result.missing_pixels}\n"
                f"多余像素：{result.extra_pixels}"
            )
            if result.exact:
                QMessageBox.information(self, "一致性验证通过", message)
            else:
                QMessageBox.warning(self, "一致性验证发现差异", message)

        self._start_processing(operation, completed, "正在验证 CAD 轮廓与原图…")

    @staticmethod
    def _page_with_stored_trace(page: DocumentPage, cache_path: Path) -> DocumentPage:
        stored = load_trace_cache(cache_path)
        height, width = stored.binary.shape[:2]
        return replace(
            page,
            trace_paths=stored.paths,
            vector_size_px=(width, height),
        )

    def document_pages_for_export(self):
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
                page = DocumentPage(
                    page_number=page_index + 1,
                    raster=None,
                    page_size_mm=sizes[page_index],
                    vector_size_px=(
                        (int(state["vector_shape"][1]), int(state["vector_shape"][0]))
                        if state.get("vector_shape") is not None
                        else None
                    ),
                    label=f"{source_path.stem} - Page {page_index + 1}",
                    source_path=source_path,
                    source_page_index=page_index,
                    raster_dpi=TRACE_PDF_DPI,
                    drawing_scale=float(state.get("drawing_scale", 1.0)),
                    trace_color=7,
                )
                cache_value = state.get("trace_cache_path")
                if cache_value and Path(str(cache_value)).exists():
                    yield self._page_with_stored_trace(page, Path(str(cache_value)))
                else:
                    yield page

        return pages()

    def export_file(self) -> None:
        export_trace_from_window(self)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        super().closeEvent(event)
        if event.isAccepted():
            self._trace_cache_tempdir.cleanup()
