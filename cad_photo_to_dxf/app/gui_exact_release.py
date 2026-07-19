from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import time
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .document_export import DocumentPage
from .gui_trace_release import TRACE_PDF_DPI
from .gui_trace_release import MainWindow as _TraceReleaseMainWindow
from .image_loader import load_image
from .ocr_recognition import render_ocr_overlay
from .ocr_review import OcrReviewDialog
from .raster_trace import RasterTraceResult, trace_binary, trace_image
from .trace_paint import TracePaintDialog
from .trace_storage import load_trace_cache, save_trace_cache


class MainWindow(_TraceReleaseMainWindow):
    """Exact-CAD shell with OCR-first text export and a reduced normal UI."""

    def __init__(self) -> None:
        self._dirty_trace_keys: set[tuple[str, int | None]] = set()
        self._ocr_texts = ()
        super().__init__()

    @staticmethod
    def _remove_from_layout(widget: QWidget | None) -> None:
        if widget is None:
            return
        parent = widget.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(widget)

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()

        self.tabs.setTabText(self.tabs.indexOf(self.original_canvas), "原图")
        self.tabs.setTabText(self.tabs.indexOf(self.corrected_canvas), "校正图")
        self.tabs.setTabText(self.tabs.indexOf(self.detected_canvas), "CAD 轮廓预览")
        preprocess_index = self.tabs.indexOf(self.preprocess_tabs)
        if preprocess_index >= 0:
            self.tabs.removeTab(preprocess_index)
        self.preprocess_tabs.setVisible(False)

        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        for group in scroll.findChildren(QGroupBox):
            if group.title() == "视图":
                group.setVisible(False)
            elif group.title().startswith("纸张与坐标"):
                group.setVisible(False)
            elif group.title() in {"高级识别参数", "参数"}:
                group.setVisible(False)

        if hasattr(self, "show_advanced_checkbox"):
            self.show_advanced_checkbox.setVisible(False)
        if getattr(self, "_params_group", None) is not None:
            self._params_group.setVisible(False)
        if getattr(self, "_preprocess_button", None) is not None:
            self._preprocess_button.setVisible(False)
        self.enable_ocr.setVisible(False)
        self.enable_auxiliary.setVisible(False)

        single_button: QPushButton | None = None
        review_button: QPushButton | None = None
        verify_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            if button.text() == "生成当前页 CAD 轮廓":
                single_button = button
            elif button.text() == "检查并修正当前页 CAD 轮廓":
                review_button = button
            elif button.text() == "验证当前页与原图是否一致":
                verify_button = button
            elif button.text() == "按已知尺寸校准（可选）":
                button.setVisible(False)

        self.batch_pdf_button.setText("生成当前 PDF 全部页 CAD 轮廓")

        generation_group = QGroupBox("CAD 轮廓生成", container)
        generation_layout = QVBoxLayout(generation_group)
        if single_button is not None:
            self._remove_from_layout(single_button)
            single_button.setParent(generation_group)
            generation_layout.addWidget(single_button)
        self._remove_from_layout(self.batch_pdf_button)
        self.batch_pdf_button.setParent(generation_group)
        generation_layout.addWidget(self.batch_pdf_button)

        validation_group = QGroupBox("检查与验证", container)
        validation_layout = QVBoxLayout(validation_group)
        if review_button is not None:
            self._remove_from_layout(review_button)
            review_button.setParent(validation_group)
            validation_layout.addWidget(review_button)
        if verify_button is not None:
            self._remove_from_layout(verify_button)
            verify_button.setText("验证当前页")
            verify_button.setParent(validation_group)
            validation_layout.addWidget(verify_button)

        page_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "当前 PDF 页面"
            ),
            None,
        )
        page_index = layout.indexOf(page_group) if page_group is not None else -1
        insert_index = page_index + 1 if page_index >= 0 else 2
        layout.insertWidget(insert_index, generation_group)
        layout.insertWidget(insert_index + 1, validation_group)

        ocr_group = QGroupBox("文字 OCR 与可编辑文字", container)
        ocr_layout = QVBoxLayout(ocr_group)
        self.ocr_before_trace_checkbox = QCheckBox(
            "先识别完整文字行，再生成非文字 CAD 轮廓（推荐）",
            ocr_group,
        )
        self.ocr_before_trace_checkbox.setChecked(True)
        self.ocr_before_trace_checkbox.setToolTip(
            "中文、英文和数字会按完整文字行导出为可直接修改内容的 CAD TEXT；"
            "已识别文字的扫描轮廓不会在 DXF 中重复生成。"
        )
        ocr_layout.addWidget(self.ocr_before_trace_checkbox)
        note = QLabel(
            "OCR 结果按完整文字行导出为一个可编辑 TEXT。"
            "识别错误可在导出前直接修改；DXF 不再同时保留碎片化文字轮廓。",
            ocr_group,
        )
        note.setWordWrap(True)
        ocr_layout.addWidget(note)
        ocr_review_button = QPushButton("检查并修改 OCR 文字", ocr_group)
        ocr_review_button.clicked.connect(self.review_ocr_texts)
        ocr_layout.addWidget(ocr_review_button)

        export_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "导出选项"
            ),
            None,
        )
        export_index = layout.indexOf(export_group) if export_group is not None else -1
        layout.insertWidget(export_index if export_index >= 0 else insert_index + 2, ocr_group)

        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "可生成当前页，也可一次生成当前 PDF 的全部页面。"
            )
        return scroll

    def _ocr_enabled(self) -> bool:
        checkbox = getattr(self, "ocr_before_trace_checkbox", None)
        return bool(checkbox is None or checkbox.isChecked())

    def _clear_trace_state(self) -> None:
        super()._clear_trace_state()
        self._ocr_texts = ()

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        super()._set_single_image_state(image, corrected=corrected)
        self._dirty_trace_keys.clear()
        self._ocr_texts = ()

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
        super()._apply_trace_result(
            result,
            started_at=started_at,
            duration=duration,
            save_pdf_state=save_pdf_state,
        )
        if result.texts:
            self.statusBar().showMessage(
                f"当前页 CAD 轮廓已生成；OCR 完整文字行 {len(result.texts)} 个"
            )

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        super()._restore_cached_trace_for_page(page_index)
        state = self._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if cache_value and Path(str(cache_value)).exists():
            self._ocr_texts = load_trace_cache(Path(str(cache_value))).texts
        else:
            self._ocr_texts = ()
        self._dirty_trace_keys.discard(self._current_trace_key())

    def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
        super()._load_pdf_page(page_index, save_current=save_current)
        if self._native_pdf_mode and hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                f"已载入 {self._pdf_page_count} 页。"
                "可生成当前页，也可一次生成全部页面。"
            )

    def _store_current_trace(self) -> Path | None:
        """Reuse an unchanged page cache instead of recompressing it at export."""

        if self.binary_image is None or not self._trace_paths:
            return None
        key = self._current_trace_key()
        state = (
            self._pdf_page_states.get(self._current_pdf_page_index, {})
            if self._native_pdf_mode
            else {}
        )
        existing = self._trace_cache_by_key.get(key)
        if existing is None and state.get("trace_cache_path"):
            existing = Path(str(state["trace_cache_path"]))
        if (
            key not in self._dirty_trace_keys
            and existing is not None
            and existing.exists()
        ):
            self._trace_cache_by_key[key] = existing
            return existing

        target = existing or self._cache_path_for_key(key)
        result = RasterTraceResult(
            binary=self.binary_image,
            stages=dict(self.preprocess_stages),
            paths=tuple(self._trace_paths),
            threshold=int(self._trace_threshold or 128),
            foreground_pixels=int(self._trace_foreground_pixels),
            vertex_count=int(self._trace_vertex_count),
            warnings=tuple(self._last_warnings),
            texts=tuple(self._ocr_texts),
        )
        save_trace_cache(target, result)
        self._trace_cache_by_key[key] = target
        self._dirty_trace_keys.discard(key)
        return target

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
        enable_ocr = self._ocr_enabled()

        def operation(token, progress) -> object:
            return trace_image(
                source,
                enable_ocr=enable_ocr,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                self.statusBar().showMessage("页面已变化，已丢弃过期结果")
                return
            result: RasterTraceResult = value  # type: ignore[assignment]
            self._apply_trace_result(
                result,
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )
            self.statusBar().showMessage(
                f"当前页 CAD 轮廓已生成：{len(result.paths)} 个边界，"
                f"OCR 完整文字行 {len(result.texts)} 个"
            )

        label = "先识别文字，再生成 CAD 轮廓" if enable_ocr else "生成 CAD 轮廓"
        self._start_processing(
            operation,
            completed,
            f"正在以 {TRACE_PDF_DPI} DPI {label}…",
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
        enable_ocr = self._ocr_enabled()

        def operation(token, progress) -> object:
            results: dict[int, dict[str, Any]] = {}
            for page_index in range(page_count):
                token.checkpoint()
                progress(
                    f"处理第 {page_index + 1}/{page_count} 页：OCR 与 CAD 轮廓",
                    page_index / max(page_count, 1),
                )
                image = load_image(
                    source_path,
                    page_index=page_index,
                    pdf_dpi=TRACE_PDF_DPI,
                )
                result = trace_image(
                    image,
                    enable_ocr=enable_ocr,
                    cancellation_token=token,
                )
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
                    "ocr_text_count": len(result.texts),
                    "drawing_scale": drawing_scale,
                    "trace_color": 7,
                }
                del image
                del result
            progress("全部页面 OCR 与 CAD 轮廓处理完成", 1.0)
            return results

        def completed(value: object) -> None:
            results = value  # type: ignore[assignment]
            duration = time.perf_counter() - started
            total_texts = 0
            for page_index, state in results.items():
                state["run_duration_seconds"] = duration
                total_texts += int(state.get("ocr_text_count", 0))
                key = self._source_key(source_path, page_index)
                self._trace_cache_by_key[key] = Path(state["trace_cache_path"])
            self._pdf_page_states.update(results)
            self._load_pdf_page(self._current_pdf_page_index, save_current=False)
            QMessageBox.information(
                self,
                "全部页面处理完成",
                f"已处理 {page_count} 页。\n"
                f"识别出 {total_texts} 个可编辑完整文字行。\n"
                "现在可一次性导出当前 PDF 的全部页面。",
            )

        self._start_processing(operation, completed, "正在处理当前 PDF 的全部页面…")

    def review_ocr_texts(self) -> None:
        if not self._ocr_texts:
            QMessageBox.warning(
                self,
                "尚无 OCR 文字",
                "请先启用 OCR 并生成当前页 CAD 轮廓。",
            )
            return
        source = self.corrected_image if self.corrected_image is not None else self.original_image
        if source is None:
            return
        dialog = OcrReviewDialog(source, tuple(self._ocr_texts), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._ocr_texts = dialog.reviewed_texts()
        self._dirty_trace_keys.add(self._current_trace_key())
        self.preprocess_stages["OCR 文字识别结果"] = render_ocr_overlay(
            source,
            self._ocr_texts,
        )
        self._show_preprocess_stages(self.preprocess_stages)
        if self._native_pdf_mode:
            self._save_current_pdf_state()
        self.statusBar().showMessage(
            f"已保存当前页 OCR 文字修改：{len(self._ocr_texts)} 个完整文字行"
        )

    def review_layers(self) -> None:
        if self.binary_image is None:
            QMessageBox.warning(self, "尚无 CAD 轮廓", "请先生成当前页 CAD 轮廓。")
            return
        dialog = TracePaintDialog(self.binary_image, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.edited_binary()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        revision = self._state_revision

        def operation(token, progress) -> object:
            paths = trace_binary(
                edited,
                cancellation_token=token,
                progress_callback=progress,
            )
            return RasterTraceResult(
                binary=edited,
                stages={
                    "CAD 轮廓来源（修改后）": edited.copy(),
                    **(
                        {
                            "OCR 文字识别结果": render_ocr_overlay(
                                self.corrected_image,
                                self._ocr_texts,
                            )
                        }
                        if self.corrected_image is not None and self._ocr_texts
                        else {}
                    ),
                },
                paths=paths,
                threshold=self._trace_threshold or 128,
                foreground_pixels=int((edited == 0).sum()),
                vertex_count=sum(len(path.points) for path in paths),
                warnings=(),
                texts=tuple(self._ocr_texts),
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )
            self.statusBar().showMessage("已按修改内容重新生成当前页 CAD 轮廓")

        self._start_processing(
            operation,
            completed,
            "正在按修改内容重新生成 CAD 轮廓…",
        )

    @staticmethod
    def _page_with_stored_trace(page: DocumentPage, cache_path: Path) -> DocumentPage:
        stored = load_trace_cache(cache_path)
        height, width = stored.binary.shape[:2]
        return replace(
            page,
            trace_paths=stored.paths,
            vector_size_px=(width, height),
            texts=stored.texts,
        )
