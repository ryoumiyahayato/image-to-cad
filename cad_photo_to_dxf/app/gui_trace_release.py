from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any

from PySide6.QtWidgets import QMessageBox

from .document_export import DocumentPage
from .gui_trace_mode import MainWindow as _TraceMainWindow
from .image_loader import load_image
from .raster_trace import RasterTraceResult, trace_image
from .scale_calibrator import ScaleCalibration
from .trace_gui_export import export_trace_from_window
from .trace_storage import load_trace_cache, save_trace_cache


TRACE_PDF_DPI = 300


class MainWindow(_TraceMainWindow):
    """Release candidate using the identical full-resolution trace path everywhere."""

    def __init__(self) -> None:
        self._trace_cache_tempdir = TemporaryDirectory(prefix="image-to-cad-trace-")
        self._trace_cache_by_key: dict[tuple[str, int | None], Path] = {}
        self._queued_trace_cache_by_key: dict[tuple[str, int | None], Path] = {}
        super().__init__()

    def _has_explicit_model_calibration(self) -> bool:
        if self._native_pdf_mode or self.calibration is None:
            return False
        try:
            _source, coordinate_space, _warnings = self._calibration_semantics()
        except Exception:
            return False
        return coordinate_space == "model_mm"

    def _export_drawing_multiplier(self) -> float:
        """Return the multiplier applied after pixel-to-mm calibration.

        A PDF or paper-size calibration describes printed paper millimetres, so
        a 1:n drawing ratio must expand it to model millimetres. A two-point
        calibration already uses a known engineering length and must not be
        multiplied a second time.
        """

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
            label.setText("尚未标定；请设置纸张比例或点击已知尺寸的两个端点")
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
            f"图纸比例 1:{int(ratio)}；{model_mm_per_pixel:.6f} 模型 mm/px "
            f"（纸面 {self.calibration.mm_per_pixel:.6f} mm/px）"
        )
        self.info_label.setText(
            f"图纸比例 1:{int(ratio)}；模型坐标 {model_mm_per_pixel:.6f} mm/px"
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
        # The full binary page and all contour vertices can be hundreds of MB.
        # Keep them only for the visible page and store all inactive pages on disk.
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
            "灰度原样": source,
            "黑白拓印图": stored.binary,
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
                    "读取拓印缓存失败",
                    f"第 {page_index + 1} 页将保留原始扫描图，但拓印结果需要重新生成。\n{exc}",
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
                self.statusBar().showMessage("页面已变化，已丢弃过期拓印结果")
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )

        self._start_processing(
            operation,
            completed,
            f"正在以 {TRACE_PDF_DPI} DPI 完整拓印黑白图…",
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
        trace_color = self._trace_color()
        cache_root = Path(self._trace_cache_tempdir.name)

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                progress(
                    f"完整拓印第 {page_index + 1}/{page_count} 页",
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
                    "trace_color": trace_color,
                }
                del image
                del result
            progress("批量完整拓印完成", 1.0)
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
                "批量拓印完成",
                f"已用与单页按钮完全相同的 {TRACE_PDF_DPI} DPI 流程处理 "
                f"{page_count} 页；未降采样、未做 Hough 结构抽象。\n"
                "非当前页面的高分辨率拓印结果已压缩到临时磁盘缓存，避免占满内存。",
            )

        self._start_processing(operation, completed, "正在批量完整拓印 PDF…")

    def _document_page_from_pdf_state(
        self,
        page_index: int,
        state: dict[str, Any],
    ) -> DocumentPage:
        return replace(
            super()._document_page_from_pdf_state(page_index, state),
            raster_dpi=TRACE_PDF_DPI,
            trace_paths=(),
        )

    def _current_document_page(self) -> DocumentPage | None:
        page = super()._current_document_page()
        if page is None:
            return None
        cache_path = self._store_current_trace()
        key = self._page_key(page)
        if cache_path is not None:
            self._queued_trace_cache_by_key[key] = cache_path
        return replace(
            page,
            raster_dpi=TRACE_PDF_DPI,
            trace_paths=(),
            drawing_scale=self._export_drawing_multiplier(),
        )

    def _enqueue_page(self, page: DocumentPage) -> str:
        key = self._page_key(page)
        if page.source_path is not None and page.source_page_index is not None:
            state = self._pdf_page_states.get(page.source_page_index, {})
            cache_value = state.get("trace_cache_path")
            if cache_value:
                self._queued_trace_cache_by_key[key] = Path(str(cache_value))
        return super()._enqueue_page(page)

    def remove_last_queued_page(self) -> None:
        if self._document_queue:
            self._queued_trace_cache_by_key.pop(
                self._page_key(self._document_queue[-1]),
                None,
            )
        super().remove_last_queued_page()

    def clear_document_queue(self) -> None:
        self._queued_trace_cache_by_key.clear()
        super().clear_document_queue()

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
        if self._document_queue:
            queued_pages = tuple(self._document_queue)
            cache_map = dict(self._queued_trace_cache_by_key)

            def queued():
                for page in queued_pages:
                    cache_path = cache_map.get(self._page_key(page))
                    if cache_path is not None and cache_path.exists():
                        yield self._page_with_stored_trace(page, cache_path)
                    else:
                        yield page

            return queued()
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
                    drawing_scale=float(state.get("drawing_scale", self._drawing_scale())),
                    trace_color=int(state.get("trace_color", self._trace_color())),
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
