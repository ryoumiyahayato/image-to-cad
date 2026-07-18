from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .auxiliary_recognition import confirmable_circles
from .document_export import DocumentPage
from .geometry_cleaner import GeometryCleanParams
from .gui_export import _export_pdf_document, export_from_window
from .gui_state_guard import (
    PDF_VIEW_DPI,
    MainWindow as _DocumentMainWindow,
)
from .line_detect import LineDetectionParams
from .pipeline_service import PipelineService, VectorizationResult
from .preprocess import PreprocessParams


class MainWindow(_DocumentMainWindow):
    """PR20 document workflow plus PR21 cross-file queue and full entity review."""

    def __init__(self) -> None:
        self._document_queue: list[DocumentPage] = []
        self._reviewed_circles = []
        super().__init__()
        self._refresh_document_queue_status()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        queue_group = QGroupBox("跨文件合并队列", container)
        queue_layout = QVBoxLayout(queue_group)
        self.document_queue_status = QLabel(
            "尚未加入跨文件页面；当前多页 PDF 仍可直接整体导出。",
            queue_group,
        )
        self.document_queue_status.setWordWrap(True)
        queue_layout.addWidget(self.document_queue_status)

        first_row = QHBoxLayout()
        add_page = QPushButton("加入当前页 / 图片", queue_group)
        add_page.clicked.connect(self.add_current_page_to_queue)
        add_document = QPushButton("加入当前 PDF 全部页面", queue_group)
        add_document.clicked.connect(self.add_current_document_to_queue)
        first_row.addWidget(add_page)
        first_row.addWidget(add_document)
        queue_layout.addLayout(first_row)

        second_row = QHBoxLayout()
        remove_last = QPushButton("移除最后一页", queue_group)
        remove_last.clicked.connect(self.remove_last_queued_page)
        clear_queue = QPushButton("清空队列", queue_group)
        clear_queue.clicked.connect(self.clear_document_queue)
        second_row.addWidget(remove_last)
        second_row.addWidget(clear_queue)
        queue_layout.addLayout(second_row)

        note = QLabel(
            "可依次导入不同 PDF 或图片并加入队列。导出时仍保留 PR20 的 PAGE-### "
            "布局和模型空间纵向排列，同时增加 PAGE_### 整页选择组。",
            queue_group,
        )
        note.setWordWrap(True)
        queue_layout.addWidget(note)

        page_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "PDF 页面与合并"
            ),
            None,
        )
        page_index = layout.indexOf(page_group) if page_group is not None else -1
        layout.insertWidget(page_index + 1 if page_index >= 0 else 2, queue_group)
        return scroll

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        super()._set_single_image_state(image, corrected=corrected)
        self._reviewed_circles = []

    def _save_current_pdf_state(self) -> None:
        super()._save_current_pdf_state()
        if not self._native_pdf_mode:
            return
        state = self._pdf_page_states.get(self._current_pdf_page_index)
        if state is not None:
            state["reviewed_circles"] = list(self._reviewed_circles)

    def _load_pdf_page(self, page_index: int, *, save_current: bool = True) -> None:
        super()._load_pdf_page(page_index, save_current=save_current)
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

    def detect_and_clean(self) -> None:
        if self.corrected_image is None:
            if not self._require_corrected():
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
        if self._native_pdf_mode:
            work_image, scale_x, scale_y = self._pdf_working_image(source)
            existing_binary = None
            enable_auxiliary = False
            enable_ocr = False
        else:
            work_image = source
            scale_x = scale_y = 1.0
            existing_binary = (
                self.binary_image.copy() if self.binary_image is not None else None
            )
            enable_auxiliary = (
                self.enable_auxiliary.isChecked() or self.enable_ocr.isChecked()
            )
            enable_ocr = self.enable_ocr.isChecked()
        preserve_hatch = self.keep_hatch.isChecked()
        revision = self._state_revision
        run_started_at = datetime.now(timezone.utc)
        started = time.perf_counter()

        def operation(token, progress) -> object:
            return PipelineService.vectorize(
                work_image,
                existing_binary=existing_binary,
                preprocess_params=preprocess_params,
                detection_params=detection,
                clean_params=cleaning,
                preserve_hatch=preserve_hatch,
                enable_auxiliary=enable_auxiliary,
                enable_ocr=enable_ocr,
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
            if result.preprocess_stages:
                self.preprocess_stages = result.preprocess_stages
                self._show_preprocess_stages(self.preprocess_stages)
            self.raw_lines = self._rescale_lines(result.raw_lines, scale_x, scale_y)
            self.lines = self._rescale_lines(result.lines, scale_x, scale_y)
            self.geometry_report = result.geometry_report
            self.classification_report = result.classification_report
            self.auxiliary_result = result.auxiliary
            self._reviewed_circles = (
                confirmable_circles(result.auxiliary.circles)
                if result.auxiliary is not None
                else []
            )
            texts = list(result.auxiliary.texts) if result.auxiliary is not None else []
            self.detected_canvas.set_vector_result(
                source,
                self.lines,
                circles=self._reviewed_circles,
                texts=texts,
            )
            self.tabs.setCurrentWidget(self.detected_canvas)
            self._run_started_at = run_started_at
            self._run_duration_seconds = time.perf_counter() - started
            self._last_preprocess_scale = result.preprocess_resolution_scale
            self._last_detection_scale = result.detection_resolution_scale
            self._last_geometry_scale = result.geometry_resolution_scale
            self._last_preprocess_params = preprocess_params
            self._last_detection_params = detection
            self._last_clean_params = cleaning
            warnings = list(result.warnings)
            if self._native_pdf_mode:
                warnings.append(
                    f"PDF 矢量识别使用最长边 {max(work_image.shape[:2])} px 工作图；"
                    "原始扫描底图未降质。"
                )
            self._last_warnings = tuple(dict.fromkeys(warnings))
            if self._native_pdf_mode:
                self._save_current_pdf_state()
            self.statusBar().showMessage(
                f"识别完成：LINE {len(self.lines)}、"
                f"CIRCLE {len(self._reviewed_circles)}、TEXT {len(texts)}；"
                "可进入可视化编辑继续修改。"
            )

        self._start_processing(operation, completed, "正在识别和清理图纸…")

    @staticmethod
    def _page_key(page: DocumentPage) -> tuple[str, int | None]:
        source = (
            str(page.source_path.resolve())
            if page.source_path is not None
            else page.label
        )
        return source, page.source_page_index

    def _document_page_from_pdf_state(
        self,
        page_index: int,
        state: dict[str, Any],
    ) -> DocumentPage:
        if self.current_path is None:
            raise ValueError("PDF source path is missing")
        auxiliary = state.get("auxiliary_result")
        circles = state.get("reviewed_circles")
        if circles is None and auxiliary is not None:
            circles = confirmable_circles(auxiliary.circles)
        texts = list(auxiliary.texts) if auxiliary is not None else []
        vector_shape = state.get("vector_shape")
        return DocumentPage(
            page_number=page_index + 1,
            raster=None,
            page_size_mm=self._pdf_page_sizes_mm[page_index],
            lines=tuple(state.get("lines", ())),
            vector_size_px=(
                (int(vector_shape[1]), int(vector_shape[0]))
                if vector_shape is not None
                else None
            ),
            label=f"{self.current_path.stem} - Page {page_index + 1}",
            circles=tuple(circles or ()),
            texts=tuple(texts),
            source_path=Path(self.current_path),
            source_page_index=page_index,
            raster_dpi=PDF_VIEW_DPI,
        )

    def _current_document_page(self) -> DocumentPage | None:
        if self.corrected_image is None or self.current_path is None:
            QMessageBox.warning(self, "当前页不可加入", "请先导入并校正当前图纸。")
            return None
        if self._native_pdf_mode:
            self._save_current_pdf_state()
            state = self._pdf_page_states.get(self._current_pdf_page_index, {})
            return self._document_page_from_pdf_state(
                self._current_pdf_page_index,
                state,
            )
        if self.calibration is None:
            QMessageBox.warning(
                self,
                "图片尚未校准",
                "跨文件合并要求图片具有纸面或模型尺寸。请先完成纸张校正或两点尺寸校准。",
            )
            return None
        height, width = self.corrected_image.shape[:2]
        auxiliary = self.auxiliary_result
        texts = list(auxiliary.texts) if auxiliary is not None else []
        return DocumentPage(
            page_number=1,
            raster=self.corrected_image.copy(),
            page_size_mm=(
                max(1, width - 1) * self.calibration.mm_per_pixel,
                max(1, height - 1) * self.calibration.mm_per_pixel,
            ),
            lines=tuple(self.lines),
            vector_size_px=(width, height),
            label=self.current_path.stem,
            circles=tuple(self._reviewed_circles),
            texts=tuple(texts),
            source_path=Path(self.current_path),
            source_page_index=None,
            raster_dpi=PDF_VIEW_DPI,
        )

    def _enqueue_page(self, page: DocumentPage) -> str:
        key = self._page_key(page)
        replacement = next(
            (
                index
                for index, existing in enumerate(self._document_queue)
                if self._page_key(existing) == key
            ),
            None,
        )
        if replacement is None:
            self._document_queue.append(page)
            action = "加入"
        else:
            self._document_queue[replacement] = page
            action = "更新"
        return action

    def add_current_page_to_queue(self) -> None:
        page = self._current_document_page()
        if page is None:
            return
        action = self._enqueue_page(page)
        self._refresh_document_queue_status()
        self.statusBar().showMessage(
            f"已{action}跨文件队列：{page.label}；共 {len(self._document_queue)} 页"
        )

    def add_current_document_to_queue(self) -> None:
        if not self._native_pdf_mode:
            self.add_current_page_to_queue()
            return
        self._save_current_pdf_state()
        for page_index in range(self._pdf_page_count):
            state = self._pdf_page_states.get(page_index, {})
            self._enqueue_page(self._document_page_from_pdf_state(page_index, state))
        self._refresh_document_queue_status()
        self.statusBar().showMessage(
            f"已将当前 PDF 的 {self._pdf_page_count} 页加入跨文件队列；"
            f"队列共 {len(self._document_queue)} 页"
        )

    def remove_last_queued_page(self) -> None:
        if not self._document_queue:
            return
        page = self._document_queue.pop()
        self._refresh_document_queue_status()
        self.statusBar().showMessage(f"已移除队列页面：{page.label}")

    def clear_document_queue(self) -> None:
        self._document_queue.clear()
        self._refresh_document_queue_status()
        self.statusBar().showMessage("已清空跨文件合并队列")

    def _refresh_document_queue_status(self) -> None:
        label = getattr(self, "document_queue_status", None)
        if label is None:
            return
        if not self._document_queue:
            label.setText("尚未加入跨文件页面；当前多页 PDF 仍可直接整体导出。")
            return
        names = "、".join(page.label for page in self._document_queue[-3:])
        prefix = "…、" if len(self._document_queue) > 3 else ""
        label.setText(
            f"待合并 {len(self._document_queue)} 页：{prefix}{names}。"
            "继续导入其他文件不会清空该队列。"
        )

    def document_pages_for_export(self):
        if self._document_queue:
            return iter(tuple(self._document_queue))
        return super().document_pages_for_export()

    def export_file(self) -> None:
        if self._document_queue:
            _export_pdf_document(self)
            return
        export_from_window(self, circles=list(self._reviewed_circles))
