from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton

from .gui_final_release import MainWindow as _OptimizedMainWindow
from .gui_page_export import (
    export_current_page_from_window,
    export_processed_pages_from_window,
)
from .raster_trace import RasterTraceResult, trace_binary
from .trace_paint import TracePaintDialog
from .trace_verification import TraceVerificationResult, verify_trace_paths
from .visual_acceptance import current_git_commit, default_visual_acceptance_root
from .visual_acceptance_widget import VisualAcceptanceWidget


_EXPORT_BUTTON_LABELS = {
    "导出同一 CAD（DWG / DXF）",
    "导出当前 PDF 全部页 CAD（DWG / DXF）",
    "导出 CAD（每页独立文件）",
}


class MainWindow(_OptimizedMainWindow):
    """Final user-facing terminology for editing and verification actions."""

    def __init__(self) -> None:
        super().__init__()
        self.visual_acceptance = VisualAcceptanceWidget(self)
        self.tabs.addTab(self.visual_acceptance, "视觉验收")

    def _clear_trace_state(self) -> None:
        super()._clear_trace_state()
        widget = getattr(self, "visual_acceptance", None)
        if widget is not None:
            widget.clear_result()

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        super()._set_single_image_state(image, corrected=corrected)
        widget = getattr(self, "visual_acceptance", None)
        if widget is not None:
            widget.clear_result()

    def _visual_acceptance_source(self):
        structure = self._final_structure
        if structure is None:
            raise ValueError("当前页没有最终 CAD 结构")
        source = self._load_trace_source_for_current_page()
        if (source.shape[1], source.shape[0]) != structure.source_size_px:
            raise ValueError("原图与最终 CAD 结构不在同一坐标系")
        return source

    def _refresh_visual_acceptance(self) -> None:
        structure = self._final_structure
        if structure is None or self.current_path is None:
            return
        source = self._visual_acceptance_source()
        page_label = (
            f"第 {self._current_pdf_page_index + 1} 页"
            if self._native_pdf_mode
            else "单页"
        )
        repository_root = Path(__file__).resolve().parents[2]
        run = self.visual_acceptance.set_result(
            source,
            structure,
            source_label=Path(self.current_path).name,
            page_label=page_label,
            commit=current_git_commit(repository_root),
            output_root=default_visual_acceptance_root(repository_root),
        )
        self.tabs.setCurrentWidget(self.visual_acceptance)
        self.statusBar().showMessage(
            f"视觉验收总览已生成：{run.overview_path}"
        )

    def _apply_trace_result(self, result, **kwargs) -> None:
        super()._apply_trace_result(result, **kwargs)
        self._refresh_visual_acceptance()

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        super()._restore_cached_trace_for_page(page_index)
        if self._final_structure is not None:
            self._refresh_visual_acceptance()

    def _replace_final_structure_texts(self, texts):
        structure = super()._replace_final_structure_texts(texts)
        self._refresh_visual_acceptance()
        return structure

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        export_button: QPushButton | None = None
        for button in scroll.findChildren(QPushButton):
            if button.text() in _EXPORT_BUTTON_LABELS:
                export_button = button
                break

        if export_button is not None:
            export_button.setText("导出当前页 CAD")
            export_button.setToolTip(
                "只导出当前已经处理完成的页面，不检查其他 PDF 页面。"
            )
            parent = export_button.parentWidget()
            parent_layout = parent.layout() if parent is not None else None
            self.export_processed_pages_button = QPushButton(
                "导出已处理页面（每页独立文件）",
                parent,
            )
            self.export_processed_pages_button.setToolTip(
                "导出所有已经处理完成的页面；未处理页面会被跳过。"
            )
            self.export_processed_pages_button.clicked.connect(
                self.export_processed_pages
            )
            if parent_layout is not None:
                index = parent_layout.indexOf(export_button)
                if hasattr(parent_layout, "insertWidget"):
                    parent_layout.insertWidget(
                        index + 1,
                        self.export_processed_pages_button,
                    )
                elif hasattr(parent_layout, "addRow"):
                    parent_layout.addRow(self.export_processed_pages_button)
                else:
                    parent_layout.addWidget(self.export_processed_pages_button)

        for label in scroll.findChildren(QLabel):
            text = label.text()
            if "多页 PDF" in text and (
                "合并" in text or "PAGE-###" in text
            ):
                label.setText(
                    "“导出当前页 CAD”只导出当前处理结果；"
                    "“导出已处理页面”会为每个已处理页面生成独立文件，"
                    "未处理页面不会阻止导出。"
                )
                label.setWordWrap(True)

        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "当前页处理完成后可立即导出；也可批量导出所有已处理页面。"
            )
        return scroll

    def export_file(self) -> None:
        export_current_page_from_window(self)

    def export_processed_pages(self) -> None:
        export_processed_pages_from_window(self)

    def review_layers(self) -> None:
        if self.binary_image is None:
            QMessageBox.warning(self, "尚无处理结果", "请先处理当前页。")
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
                stages={},
                paths=paths,
                threshold=self._trace_threshold or 128,
                foreground_pixels=int((edited == 0).sum()),
                vertex_count=sum(len(path.points) for path in paths),
                warnings=(),
                texts=tuple(self._ocr_texts),
                signatures=tuple(self._signature_regions),
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
            self.statusBar().showMessage("已按修改内容重新生成当前页 CAD")

        self._start_processing(operation, completed, "正在应用修改并重新生成 CAD…")

    def verify_current_trace(self) -> None:
        if self.binary_image is None or not self._trace_paths:
            QMessageBox.warning(self, "尚无处理结果", "请先处理当前页。")
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
            self.detected_canvas.set_image(
                self._scaled_for_preview(
                    result.overlay,
                    target_shape=self._preview_shape(),
                )
            )
            self.tabs.setCurrentWidget(self.detected_canvas)
            if result.exact:
                QMessageBox.information(
                    self,
                    "核对完成",
                    "当前页生成内容与黑白来源一致，没有发现遗漏像素。",
                )
            else:
                QMessageBox.warning(
                    self,
                    "发现差异",
                    f"发现 {result.different_pixels} 个差异像素，请进入检查与修改。",
                )

        self._start_processing(operation, completed, "正在核对当前页…")
