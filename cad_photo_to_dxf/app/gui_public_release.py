from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .gui_final_release import MainWindow as _OptimizedMainWindow
from .gui_page_export import (
    export_current_page_from_window,
    export_processed_pages_from_window,
)
from .raster_trace import RasterTraceResult, trace_binary
from .trace_paint import TracePaintDialog
from .trace_verification import TraceVerificationResult, verify_trace_paths
from .visual_acceptance import (
    VisualAcceptanceArtifacts,
    VisualAcceptanceWorkbench,
    write_visual_acceptance_artifacts,
    write_visual_acceptance_review,
)


_EXPORT_BUTTON_LABELS = {
    "导出同一 CAD（DWG / DXF）",
    "导出当前 PDF 全部页 CAD（DWG / DXF）",
    "导出 CAD（每页独立文件）",
}


class MainWindow(_OptimizedMainWindow):
    """Final user-facing terminology and human-visible CAD acceptance."""

    def __init__(self) -> None:
        self.visual_acceptance: VisualAcceptanceWorkbench | None = None
        self._last_visual_acceptance_artifacts: VisualAcceptanceArtifacts | None = None
        super().__init__()
        self.visual_acceptance = VisualAcceptanceWorkbench(self)
        self.visual_acceptance.review_changed.connect(
            self._on_visual_acceptance_review_changed
        )
        self.tabs.addTab(self.visual_acceptance, "视觉验收")
        self._refresh_visual_acceptance(open_tab=False)

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

        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is not None:
            visual_group = QGroupBox("肉眼验收", container)
            visual_layout = QVBoxLayout(visual_group)
            visual_note = QLabel(
                "处理完成后直接对比原图、最终 CAD 重建和同坐标叠加。"
                "这里看见的重建结果绑定当前 FinalStructure，不使用另一套漂亮预览。",
                visual_group,
            )
            visual_note.setWordWrap(True)
            visual_layout.addWidget(visual_note)
            visual_button = QPushButton("打开视觉验收", visual_group)
            visual_button.clicked.connect(self.open_visual_acceptance)
            visual_layout.addWidget(visual_button)
            layout.insertWidget(max(0, layout.count() - 1), visual_group)

        if hasattr(self, "page_summary_label"):
            self.page_summary_label.setText(
                "当前页处理完成后可立即肉眼对比并导出；也可批量导出所有已处理页面。"
            )
        return scroll

    def _visual_acceptance_source_label(self) -> str:
        source = (
            Path(self.current_path).name
            if self.current_path is not None
            else "未保存图像"
        )
        if bool(getattr(self, "_native_pdf_mode", False)):
            page_index = int(getattr(self, "_current_pdf_page_index", 0)) + 1
            return f"{source}-page-{page_index:03d}"
        return source

    @staticmethod
    def _visual_acceptance_root() -> Path:
        return Path.cwd() / "local-artifacts" / "draftsman" / "visual-acceptance"

    def _visual_acceptance_source(self):
        if self.corrected_image is not None:
            return self.corrected_image
        return self.original_image

    def _refresh_visual_acceptance(self, *, open_tab: bool) -> None:
        workbench = self.visual_acceptance
        structure = getattr(self, "_final_structure", None)
        source = self._visual_acceptance_source()
        if workbench is None:
            return
        if source is None or structure is None:
            workbench.clear()
            return
        try:
            structure.assert_valid()
            if getattr(self, "_preview_structure_id", None) != structure.structure_id:
                raise ValueError("视觉验收拒绝使用与当前导出结构不一致的预览状态")
            width, height = structure.source_size_px
            if source.shape[:2] != (height, width):
                if not bool(getattr(self, "_native_pdf_mode", False)):
                    raise ValueError("视觉验收原图与最终结构坐标尺寸不一致")
                source = self._load_trace_source_for_current_page()
                if source.shape[:2] != (height, width):
                    raise ValueError("PDF 处理原图与最终结构坐标尺寸仍不一致")
            label = self._visual_acceptance_source_label()
            workbench.set_result(source, structure, source_label=label)
            artifacts = write_visual_acceptance_artifacts(
                source,
                structure,
                root=self._visual_acceptance_root(),
                source_label=label,
                review=workbench.review_payload(),
            )
            self._last_visual_acceptance_artifacts = artifacts
            workbench.set_artifact_paths(artifacts)
            if open_tab:
                self.tabs.setCurrentWidget(workbench)
            self.statusBar().showMessage(
                f"视觉验收已更新；总览截图：{artifacts.overview_path}"
            )
        except (OSError, ValueError, AssertionError) as exc:
            self._last_visual_acceptance_artifacts = None
            self.statusBar().showMessage(f"视觉验收生成失败：{exc}")

    def open_visual_acceptance(self) -> None:
        workbench = self.visual_acceptance
        if workbench is None:
            return
        if getattr(self, "_final_structure", None) is None:
            QMessageBox.warning(self, "尚无处理结果", "请先处理当前页，再进行肉眼验收。")
            return
        self._refresh_visual_acceptance(open_tab=True)

    def _on_visual_acceptance_review_changed(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        artifacts = self._last_visual_acceptance_artifacts
        if artifacts is None:
            return
        current: dict[str, object] = {}
        try:
            if artifacts.review_path.exists():
                loaded = json.loads(artifacts.review_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            current = {}
        current["human_review"] = dict(payload)
        write_visual_acceptance_review(artifacts.review_path, current)
        if bool(getattr(self, "_native_pdf_mode", False)):
            state = self._pdf_page_states.setdefault(
                int(getattr(self, "_current_pdf_page_index", 0)),
                {},
            )
            state["visual_acceptance_review"] = dict(payload)

    def _clear_trace_state(self) -> None:
        super()._clear_trace_state()
        self._last_visual_acceptance_artifacts = None
        workbench = self.visual_acceptance
        if workbench is not None:
            workbench.clear()

    def _apply_trace_result(
        self,
        result: RasterTraceResult,
        *,
        started_at: datetime,
        duration: float,
        save_pdf_state: bool,
    ) -> None:
        super()._apply_trace_result(
            result,
            started_at=started_at,
            duration=duration,
            save_pdf_state=save_pdf_state,
        )
        self._refresh_visual_acceptance(open_tab=True)

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        super()._restore_cached_trace_for_page(page_index)
        self._refresh_visual_acceptance(open_tab=False)

    def _replace_final_structure_texts(self, texts):  # type: ignore[override]
        structure = super()._replace_final_structure_texts(texts)
        self._refresh_visual_acceptance(open_tab=False)
        return structure

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
