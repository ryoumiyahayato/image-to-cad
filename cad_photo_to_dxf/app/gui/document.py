from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.ocr.auxiliary_recognition import confirmable_circles
from app.core.image_loader import bounded_pdf_dpi, load_image, pdf_page_count, pdf_page_size_mm
from app.geometry.pdf_arc_evidence import pdf_geometry_binding
from app.geometry.line_detect import render_line_preview
from app.geometry.preprocess import PreprocessParams
from app.core.preview import render_final_structure_preview
from app.core.processing import ProcessingCacheKey, build_processing_cache_key, cache_key_matches, file_content_sha256, image_content_sha256
from app.geometry.raster_trace import RasterTraceResult
from app.core.scale_calibrator import ScaleCalibration
from app.core.cache import load_trace_cache, save_trace_cache

UNSCALED_LABEL = "比例：未校准（1 px = 1 个无单位图形单位）"
PDF_VIEW_DPI = 200
PROCESS_PDF_MAX_SIDE = 4800
TRACE_PDF_DPI = 240


@staticmethod
def _cache_file_matches(path: Path, key: ProcessingCacheKey) -> bool:
    if not path.exists():
        return False
    try:
        stored = load_trace_cache(path)
    except (OSError, ValueError):
        return False
    return cache_key_matches(stored.cache_key, key)


def _cache_path_for_key(self, key: object) -> Path:
    if isinstance(key, ProcessingCacheKey):
        digest = key.digest[:24]
    else:
        digest = sha256(repr(key).encode("utf-8")).hexdigest()[:24]
    return Path(self._trace_cache_tempdir.name) / f"trace-{digest}.npz"


def _current_trace_key(self) -> object:
    page_index = self._current_pdf_page_index if self._native_pdf_mode else None
    return self._source_key(self.current_path, page_index)


def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
    if not self._native_pdf_mode or self.current_path is None:
        return
    if not 0 <= page_index < self._pdf_page_count:
        return
    if save_current:
        self._save_current_pdf_state()
    image = load_image(self.current_path, page_index=page_index, pdf_dpi=PDF_VIEW_DPI)
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
    self.auxiliary_result = state.get("auxiliary_result")
    self._last_warnings = tuple(state.get("last_warnings", ()))
    self._run_started_at = state.get("run_started_at")
    self._run_duration_seconds = state.get("run_duration_seconds")
    self._last_preprocess_scale = float(state.get("last_preprocess_scale", 1.0))
    self._last_preprocess_params = state.get(
        "last_preprocess_params", PreprocessParams()
    )
    width_mm, _height_mm = self._pdf_page_sizes_mm[page_index]
    self.calibration = ScaleCalibration(
        (0.0, 0.0), (float(max(1, image.shape[1] - 1)), 0.0), width_mm
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
        f"PDF 纸面坐标：{self.calibration.mm_per_pixel:.6f} mm/px；不是工程模型尺寸"
    )
    self.page_combo.blockSignals(True)
    self.page_combo.setCurrentIndex(page_index)
    self.page_combo.blockSignals(False)
    self.tabs.setCurrentWidget(
        self.detected_canvas if self.lines else self.original_canvas
    )
    processed = len(self._pdf_page_states)
    self.statusBar().showMessage(
        f"{self.current_path.name}：第 {page_index + 1}/{self._pdf_page_count} 页；已有识别结果 {processed} 页"
    )
    if not self._native_pdf_mode or self.corrected_image is None:
        return
    state = self._pdf_page_states.get(page_index, {})
    auxiliary = state.get("auxiliary_result")
    reviewed = state.get("reviewed_circles")
    if reviewed is None and auxiliary is not None:
        reviewed = confirmable_circles(auxiliary.circles)
    self._reviewed_circles = list(reviewed or [])
    texts = list(auxiliary.texts) if auxiliary is not None else []
    if self.lines or self._reviewed_circles or texts:
        self.detected_canvas.set_vector_result(
            self.corrected_image,
            self.lines,
            circles=self._reviewed_circles,
            texts=texts,
        )
        self.tabs.setCurrentWidget(self.detected_canvas)
    if not self._native_pdf_mode:
        return
    state = self._pdf_page_states.get(page_index, {})
    binary = state.get("binary_image")
    self.binary_image = binary.copy() if binary is not None else None
    self.preprocess_stages = {
        name: image.copy() for name, image in state.get("preprocess_stages", {}).items()
    }
    self._trace_paths = tuple(state.get("trace_paths", ()))
    self._trace_threshold = state.get("trace_threshold")
    self._trace_foreground_pixels = int(state.get("trace_foreground_pixels", 0))
    self._trace_vertex_count = int(state.get("trace_vertex_count", 0))
    if hasattr(self, "drawing_scale_spin"):
        self.drawing_scale_spin.blockSignals(True)
        self.drawing_scale_spin.setValue(
            int(round(state.get("drawing_scale", self._drawing_scale())))
        )
        self.drawing_scale_spin.blockSignals(False)
    if hasattr(self, "trace_color_combo"):
        color = int(state.get("trace_color", self._trace_color()))
        index = self.trace_color_combo.findData(color)
        if index >= 0:
            self.trace_color_combo.blockSignals(True)
            self.trace_color_combo.setCurrentIndex(index)
            self.trace_color_combo.blockSignals(False)
    if self.preprocess_stages:
        self._show_preprocess_stages(self.preprocess_stages)
    if self.binary_image is not None:
        self.corrected_canvas.set_image(self.binary_image)
        self.detected_canvas.set_image(self.binary_image)
        self.tabs.setCurrentWidget(self.detected_canvas)
    self._update_scale_label()
    if self._native_pdf_mode:
        try:
            self._restore_cached_trace_for_page(page_index)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "读取 CAD 轮廓缓存失败",
                f"第 {page_index + 1} 页需要重新生成。\n{exc}",
            )
    if self._native_pdf_mode and hasattr(self, "page_summary_label"):
        self.page_summary_label.setText(
            f"已载入 {self._pdf_page_count} 页。可生成当前页，也可一次生成全部页面。"
        )


def _load_trace_source_for_current_page(self):
    self._current_pdf_geometry = None
    if not self._native_pdf_mode or self.current_path is None:
        if self.corrected_image is None:
            raise ValueError("当前页面尚未载入")
        return np.ascontiguousarray(self.corrected_image.copy())
    geometry = []
    image = load_image(
        self.current_path,
        page_index=self._current_pdf_page_index,
        pdf_dpi=self._processing_pdf_dpi(self._current_pdf_page_index),
        grayscale=True,
        pdf_geometry_sink=geometry,
    )
    self._current_pdf_geometry = geometry[0] if geometry else None
    width_mm, _height_mm = self._pdf_page_sizes_mm[self._current_pdf_page_index]
    self.calibration = ScaleCalibration(
        (0.0, 0.0), (float(max(1, image.shape[1] - 1)), 0.0), width_mm
    )
    self._update_scale_label()
    return image


def _next_pdf_page(self) -> None:
    if self._native_pdf_mode:
        self._load_pdf_page(
            min(self._pdf_page_count - 1, self._current_pdf_page_index + 1)
        )


def _on_pdf_page_changed(self, index: int) -> None:
    if self._native_pdf_mode and index >= 0 and (index != self._current_pdf_page_index):
        self._load_pdf_page(index)


def _previous_pdf_page(self) -> None:
    if self._native_pdf_mode:
        self._load_pdf_page(max(0, self._current_pdf_page_index - 1))


def _processing_pdf_dpi(self, page_index: int) -> int:
    return bounded_pdf_dpi(
        self._pdf_page_sizes_mm[page_index],
        preferred_dpi=TRACE_PDF_DPI,
        max_dimension_px=PROCESS_PDF_MAX_SIDE,
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
        self._signature_regions = ()
        self._final_structure = None
        self._preview_structure_id = None
        return
    cache_path = Path(str(cache_value))
    expected_key = self._source_key(self.current_path, page_index)
    stored = load_trace_cache(cache_path)
    if not cache_key_matches(stored.cache_key, expected_key):
        self._clear_trace_state()
        self.binary_image = None
        self._ocr_texts = ()
        self._signature_regions = ()
        self._final_structure = None
        self._preview_structure_id = None
        raise ValueError(
            "Trace cache key does not match current content or configuration"
        )
    structure = stored.final_structure
    if structure is None:
        raise ValueError("Trace cache has no FinalStructure")
    self._trace_cache_by_key[expected_key] = cache_path
    self.binary_image = structure.contour_binary
    self._trace_paths = structure.contours
    self._trace_threshold = structure.threshold
    self._trace_foreground_pixels = int(np.count_nonzero(structure.contour_binary == 0))
    self._trace_vertex_count = sum((len(path.points) for path in structure.contours))
    self._last_warnings = structure.warnings
    self._ocr_texts = structure.texts
    self._signature_regions = structure.signatures
    self.lines = list(structure.straight_lines)
    self._final_structure = structure
    self._preview_structure_id = structure.structure_id
    self._cad_preview_binary = render_final_structure_preview(structure)
    self._dirty_trace_keys.discard(expected_key)
    self.preprocess_stages = {}
    self._clear_preprocess_tabs()
    preview = self._scaled_for_preview(
        self._cad_preview_binary, target_shape=self._preview_shape()
    )
    self.corrected_canvas.set_image(preview)
    self.detected_canvas.set_image(preview)
    self.tabs.setCurrentWidget(self.detected_canvas)
    width_mm, _height_mm = self._pdf_page_sizes_mm[page_index]
    self.calibration = ScaleCalibration(
        (0.0, 0.0), (float(max(1, stored.binary.shape[1] - 1)), 0.0), width_mm
    )
    self._update_scale_label()
    if self._final_structure is not None:
        self._refresh_visual_acceptance()


def _save_current_pdf_state(self) -> None:
    if not self._native_pdf_mode:
        return
    self._pdf_page_states[self._current_pdf_page_index] = {
        "raw_lines": list(self.raw_lines),
        "lines": list(self.lines),
        "auxiliary_result": self.auxiliary_result,
        "last_warnings": tuple(self._last_warnings),
        "run_started_at": self._run_started_at,
        "run_duration_seconds": self._run_duration_seconds,
        "last_preprocess_scale": self._last_preprocess_scale,
        "last_preprocess_params": self._last_preprocess_params,
        "vector_shape": tuple(self.corrected_image.shape[:2])
        if self.corrected_image is not None
        else None,
    }
    if not self._native_pdf_mode:
        return
    state = self._pdf_page_states.get(self._current_pdf_page_index)
    if state is not None:
        state["reviewed_circles"] = list(self._reviewed_circles)
    if not self._native_pdf_mode:
        return
    state = self._pdf_page_states.get(self._current_pdf_page_index)
    if state is None:
        return
    state.update(
        {
            "binary_image": self.binary_image.copy()
            if self.binary_image is not None
            else None,
            "preprocess_stages": {
                name: image.copy() for name, image in self.preprocess_stages.items()
            },
            "trace_paths": tuple(self._trace_paths),
            "trace_threshold": self._trace_threshold,
            "trace_foreground_pixels": self._trace_foreground_pixels,
            "trace_vertex_count": self._trace_vertex_count,
            "drawing_scale": self._drawing_scale(),
            "trace_color": self._trace_color(),
        }
    )
    if not self._native_pdf_mode:
        return
    state = self._pdf_page_states.get(self._current_pdf_page_index)
    if state is None:
        return
    cache_path = self._store_current_trace()
    if cache_path is not None:
        state["trace_cache_path"] = str(cache_path)
        key = self._current_trace_key()
        if isinstance(key, ProcessingCacheKey):
            state["trace_cache_key"] = key.payload()
            state["trace_cache_key_digest"] = key.digest
    state["drawing_scale"] = self._drawing_scale()
    state["trace_color"] = 7
    state.pop("binary_image", None)
    state.pop("preprocess_stages", None)
    state.pop("trace_paths", None)


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


def _set_single_image_state(self, image, *, corrected: bool) -> None:
    self.original_image = image
    self.corrected_image = image.copy() if corrected else None
    self.binary_image = None
    self.raw_lines = []
    self.lines = []
    self.preprocess_stages = {}
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
    self._reviewed_circles = []
    self._clear_trace_state()
    self._dirty_trace_keys.clear()
    self._ocr_texts = ()
    self._signature_regions = ()
    self._cad_preview_binary = None
    self._final_structure = None
    self._preview_structure_id = None
    widget = getattr(self, "visual_acceptance", None)
    if widget is not None:
        widget.clear_result()


def _source_key(
    self,
    source_path: Path | None,
    page_index: int | None,
    fallback: str = "unsaved",
    *,
    input_content_sha256: str | None = None,
    enable_ocr: bool | None = None,
) -> ProcessingCacheKey:
    config = self._processing_config(page_index, enable_ocr=enable_ocr)
    if input_content_sha256 is not None:
        content_hash = input_content_sha256
    elif source_path is not None and source_path.exists():
        content_hash = file_content_sha256(source_path)
    elif self.corrected_image is not None:
        content_hash = image_content_sha256(self.corrected_image)
    else:
        content_hash = image_content_sha256(
            np.frombuffer(fallback.encode("utf-8"), dtype=np.uint8)
        )
    return build_processing_cache_key(
        input_content_sha256=content_hash, page_index=page_index, config=config,
        pdf_geometry_binding=(
            pdf_geometry_binding(source_path, page_index, config.source_dpi)
            if source_path is not None and source_path.suffix.lower() == '.pdf' and page_index is not None else None),
    )


def _store_current_trace(self) -> Path | None:
    """Reuse an unchanged page cache instead of recompressing it at export."""
    structure = self._final_structure
    if structure is None:
        return None
    key = self._current_trace_key()
    state = (
        self._pdf_page_states.get(self._current_pdf_page_index, {})
        if self._native_pdf_mode
        else {}
    )
    existing = self._trace_cache_by_key.get(key)
    if existing is None and state.get("trace_cache_path"):
        candidate = Path(str(state["trace_cache_path"]))
        if isinstance(key, ProcessingCacheKey) and candidate.exists():
            try:
                stored = load_trace_cache(candidate)
            except (OSError, ValueError):
                stored = None
            if stored is not None and cache_key_matches(stored.cache_key, key):
                existing = candidate
        elif not isinstance(key, ProcessingCacheKey):
            existing = candidate
    if key not in self._dirty_trace_keys and existing is not None and existing.exists():
        self._trace_cache_by_key[key] = existing
        return existing
    target = existing or self._cache_path_for_key(key)
    result = RasterTraceResult(
        binary=structure.contour_binary,
        stages=dict(self.preprocess_stages),
        paths=structure.contours,
        threshold=structure.threshold,
        foreground_pixels=int(np.count_nonzero(structure.contour_binary == 0)),
        vertex_count=sum((len(path.points) for path in structure.contours)),
        warnings=structure.warnings,
        texts=structure.texts,
        signatures=structure.signatures,
        straight_lines=structure.straight_lines,
        arcs=structure.arcs,
        preview_binary=structure.preview_binary,
        logos=structure.logos,
        final_structure=structure,
    )
    save_trace_cache(
        target,
        result,
        cache_key=key.payload() if isinstance(key, ProcessingCacheKey) else None,
    )
    self._trace_cache_by_key[key] = target
    self._dirty_trace_keys.discard(key)
    return target


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
                index: pdf_page_size_mm(file_path, index) for index in range(count)
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
                f"已载入 {count} 页。未识别页面仍会以无损扫描底图合并导出；批量识别只增加可编辑结构线，不替代原始扫描。"
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
