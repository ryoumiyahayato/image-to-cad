from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from app.core.structure_build import final_structure_from_trace_result
from app.core.image_loader import load_image
from app.export.ocr_outline_export import accepted_ocr_texts
from app.core.preview import render_final_structure_preview
from app.core.processing import DEFAULT_IMAGE_DPI, ProcessingCacheKey, ProductionProcessingConfig, ProductionProcessingService, file_content_sha256
from app.geometry.raster_trace import RasterTraceResult
from app.core.cache import save_trace_cache

TRACE_PDF_DPI = 240


def _apply_trace_result(
    self,
    result: RasterTraceResult,
    *,
    started_at: datetime,
    duration: float,
    save_pdf_state: bool,
) -> None:
    structure = final_structure_from_trace_result(result)
    self._final_structure = structure
    self._preview_structure_id = structure.structure_id
    self._ocr_texts = structure.texts
    self._signature_regions = structure.signatures
    self._dirty_trace_keys.add(self._current_trace_key())
    self.binary_image = structure.contour_binary
    self.preprocess_stages = dict(result.stages)
    self._show_preprocess_stages(self.preprocess_stages)
    self._trace_paths = structure.contours
    self._trace_threshold = structure.threshold
    self._trace_foreground_pixels = result.foreground_pixels
    self._trace_vertex_count = result.vertex_count
    self.raw_lines = []
    self.lines = list(structure.straight_lines)
    self.auxiliary_result = None
    self._run_started_at = started_at
    self._run_duration_seconds = duration
    self._last_warnings = structure.warnings
    self._cad_preview_binary = render_final_structure_preview(structure)
    preview = self._scaled_for_preview(self._cad_preview_binary, target_shape=self._preview_shape())
    self.corrected_canvas.set_image(preview)
    self.detected_canvas.set_image(preview)
    self.tabs.setCurrentWidget(self.detected_canvas)
    self._update_scale_label()
    if save_pdf_state:
        self._save_current_pdf_state()
    safe = len(accepted_ocr_texts(result.texts))
    retained = max(0, len(result.texts) - safe)
    self.statusBar().showMessage(
        f"ARC {len(structure.arcs)}; "
        f"当前页处理完成：可编辑文字 {safe} 项；中心直线 {len(result.straight_lines)} 条；签名 {len(result.signatures)} 项；保留图像 {retained} 项"
    )
    self._refresh_visual_acceptance()


def _processing_config(
    self, page_index: int | None, *, enable_ocr: bool | None = None
) -> ProductionProcessingConfig:
    resolved_ocr = self._ocr_enabled() if enable_ocr is None else bool(enable_ocr)
    dpi = (
        self._processing_pdf_dpi(page_index)
        if self._native_pdf_mode and page_index is not None
        else DEFAULT_IMAGE_DPI
    )
    return ProductionProcessingConfig(source_dpi=float(dpi), enable_ocr=resolved_ocr)


@staticmethod
def _stage_text(stage: str) -> str:
    if stage.startswith("ocr"):
        return "识别文字"
    if stage.startswith("trace") or stage == "prepare-image":
        return "生成 CAD 内容"
    return "处理页面"


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
    enable_ocr = self._ocr_enabled()

    def operation(token, progress) -> object:
        results: dict[int, dict[str, Any]] = {}
        source_hash = file_content_sha256(source_path)
        for page_index in range(page_count):
            token.checkpoint()
            config = self._processing_config(page_index, enable_ocr=enable_ocr)
            key = self._source_key(
                source_path,
                page_index,
                input_content_sha256=source_hash,
                enable_ocr=enable_ocr,
            )
            old_state = self._pdf_page_states.get(page_index, {})
            old_cache = old_state.get("trace_cache_path")
            if (
                key not in self._dirty_trace_keys
                and old_cache
                and (old_state.get("trace_cache_key_digest") == key.digest)
                and self._cache_file_matches(Path(str(old_cache)), key)
            ):
                results[page_index] = dict(old_state)
                progress(
                    f"第 {page_index + 1}/{page_count} 页：使用已有结果",
                    (page_index + 1) / max(page_count, 1),
                )
                continue
            geometry = []
            image = load_image(
                source_path,
                page_index=page_index,
                pdf_dpi=self._processing_pdf_dpi(page_index),
                grayscale=True,
                pdf_geometry_sink=geometry,
            )

            def page_progress(stage: str, fraction: float) -> None:
                progress(
                    f"第 {page_index + 1}/{page_count} 页：{self._stage_text(stage)}",
                    (page_index + max(0.0, min(1.0, fraction))) / max(page_count, 1),
                )

            result = ProductionProcessingService.process_page(
                image, config, cancellation_token=token, progress_callback=page_progress,
                pdf_geometry=geometry[0] if geometry else None,
            )
            cache_path = self._cache_path_for_key(key)
            save_trace_cache(cache_path, result, cache_key=key.payload())
            structure = result.final_structure
            if structure is None:
                raise AssertionError("Production service returned no FinalStructure")
            results[page_index] = {
                "raw_lines": [],
                "lines": [],
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
                "processing_dpi": self._processing_pdf_dpi(page_index),
                "processing_config": config.payload(),
                "trace_cache_key": key.payload(),
                "trace_cache_key_digest": key.digest,
                "structure_id": structure.structure_id,
                "drawing_scale": drawing_scale,
                "trace_color": 7,
            }
            del image
            del result
        progress("全部页面处理完成", 1.0)
        return results

    def completed(value: object) -> None:
        results = value
        duration = time.perf_counter() - started
        total_texts = 0
        for page_index, state in results.items():
            state["run_duration_seconds"] = duration
            total_texts += int(state.get("ocr_text_count", 0))
            key = ProcessingCacheKey.from_payload(state["trace_cache_key"])
            cache_value = state.get("trace_cache_path")
            if cache_value:
                self._trace_cache_by_key[key] = Path(str(cache_value))
        self._pdf_page_states.update(results)
        self._load_pdf_page(self._current_pdf_page_index, save_current=False)
        QMessageBox.information(
            self,
            "处理完成",
            f"已处理 {page_count} 页，找到 {total_texts} 个文字候选。\n现在可以导出 CAD。",
        )

    self._start_processing(operation, completed, "正在处理全部页面…")


def detect_and_clean(self) -> None:
    if self.corrected_image is None and (not self._require_corrected()):
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
        config = self._processing_config(
            self._current_pdf_page_index if self._native_pdf_mode else None,
            enable_ocr=enable_ocr,
        )
        return ProductionProcessingService.process_page(
            source,
            config,
            pdf_geometry=getattr(self, '_current_pdf_geometry', None) if self._native_pdf_mode else None,
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
            value,
            started_at=started_at,
            duration=time.perf_counter() - started,
            save_pdf_state=self._native_pdf_mode,
        )

    self._start_processing(operation, completed, "正在处理当前页…")
