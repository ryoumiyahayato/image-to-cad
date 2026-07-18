from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .auxiliary_recognition import (
    AuxiliaryRecognitionResult,
    confirmable_circles,
)
from .document_exporter import DocumentPage
from .document_gui_export import export_document_from_window
from .gui_export import export_from_window
from .gui_state_guard import MainWindow as _StateGuardMainWindow
from .image_loader import save_image
from .layer_review import layer_counts
from .pipeline_service import VectorizationResult
from .scale_calibrator import ScaleCalibration
from .visual_review import VectorReviewDialog


class MainWindow(_StateGuardMainWindow):
    """Final GUI with visual editing and an explicit multi-page document queue."""

    def __init__(self) -> None:
        self._document_pages: list[DocumentPage] = []
        self._document_tempdir = TemporaryDirectory(prefix="image-to-cad-pages-")
        super().__init__()
        self._refresh_document_status()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if layout is None:
            return scroll

        buttons = list(scroll.findChildren(QPushButton))
        review_button = next(
            (button for button in buttons if button.text() == "6. 人工复核图层"),
            None,
        )
        if review_button is not None:
            review_button.setText("6. 可视化编辑识别结果")

        circle_button = next(
            (button for button in buttons if button.text() == "7. 人工确认圆形"),
            None,
        )
        if circle_button is not None:
            layout.removeWidget(circle_button)
            circle_button.setParent(None)
            circle_button.deleteLater()

        document_group = QGroupBox("7. 多页合并（可选）", container)
        document_layout = QVBoxLayout(document_group)
        self.document_status_label = QLabel(document_group)
        self.document_status_label.setWordWrap(True)
        document_layout.addWidget(self.document_status_label)
        document_buttons = QHBoxLayout()
        add_page = QPushButton("加入当前页", document_group)
        add_page.clicked.connect(self.add_current_page_to_document)
        remove_page = QPushButton("移除最后一页", document_group)
        remove_page.clicked.connect(self.remove_last_document_page)
        clear_pages = QPushButton("清空", document_group)
        clear_pages.clicked.connect(self.clear_document_pages)
        document_buttons.addWidget(add_page)
        document_buttons.addWidget(remove_page)
        document_buttons.addWidget(clear_pages)
        document_layout.addLayout(document_buttons)
        document_note = QLabel(
            "逐页识别和可视化修改后加入队列；导出时所有页面横向排列在同一个 DXF/DWG 模型空间，并建立 PAGE_001 等页面组。",
            document_group,
        )
        document_note.setWordWrap(True)
        document_layout.addWidget(document_note)

        export_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "9. 导出选项"
            ),
            None,
        )
        export_index = layout.indexOf(export_group) if export_group is not None else -1
        layout.insertWidget(
            export_index if export_index >= 0 else max(0, layout.count() - 1),
            document_group,
        )

        params_group = next(
            (
                group
                for group in scroll.findChildren(QGroupBox)
                if group.title() == "参数"
            ),
            None,
        )
        preprocess_button = next(
            (button for button in buttons if button.text() == "4. 图像预处理"),
            None,
        )
        scale_button = next(
            (
                button
                for button in buttons
                if button.text() == "8. 点击两点校准模型尺寸"
            ),
            None,
        )
        advanced_group = QGroupBox("高级识别设置（默认无需调整）", container)
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(advanced_group)
        advanced_content = QWidget(advanced_group)
        advanced_content_layout = QVBoxLayout(advanced_content)
        advanced_content_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (preprocess_button, scale_button, params_group):
            if widget is None:
                continue
            layout.removeWidget(widget)
            advanced_content_layout.addWidget(widget)
        advanced_layout.addWidget(advanced_content)
        advanced_content.setVisible(False)
        advanced_group.toggled.connect(advanced_content.setVisible)
        document_index = layout.indexOf(document_group)
        layout.insertWidget(max(0, document_index), advanced_group)
        return scroll

    def _is_pdf_input(self) -> bool:
        return (
            self.current_path is not None and self.current_path.suffix.lower() == ".pdf"
        )

    def import_image(self) -> None:
        revision = self._state_revision
        super().import_image()
        if revision == self._state_revision or not self._is_pdf_input():
            return
        if self.original_image is None:
            return
        # A rendered PDF page is already planar. Re-running perspective
        # detection resamples it and reduces the fidelity of fine text/lines.
        self.corrected_image = self.original_image.copy()
        self.calibration = None
        self._perspective_metadata = {
            "applied": False,
            "automatic": False,
            "confidence": 1.0,
            "corners": None,
            "source_is_planar_pdf": True,
            "warnings": [],
        }
        self._invalidate_preprocess_results()
        self._apply_paper_calibration()
        self.corrected_canvas.set_image(self.corrected_image)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        page_note = (
            f"第 {self._current_pdf_page} 页"
            if self._current_pdf_page is not None
            else "PDF 页面"
        )
        self.statusBar().showMessage(
            f"已按原始像素导入{page_note}；已跳过不必要的透视重采样"
        )

    def _paper_setting_changed(self, *_args: object) -> None:
        if not self._is_pdf_input():
            super()._paper_setting_changed(*_args)
            return
        if self.original_image is None:
            return
        self.corrected_image = self.original_image.copy()
        self.calibration = None
        self._invalidate_preprocess_results()
        self._apply_paper_calibration()
        self.corrected_canvas.set_image(self.corrected_image)
        self.tabs.setCurrentWidget(self.corrected_canvas)
        self.statusBar().showMessage("PDF 页面纸张规格已更新；请重新识别线条")

    def auto_perspective(self) -> None:
        if self._is_pdf_input():
            if self.original_image is not None and self.corrected_image is None:
                self.corrected_image = self.original_image.copy()
                self._apply_paper_calibration()
                self.corrected_canvas.set_image(self.corrected_image)
            self.tabs.setCurrentWidget(self.corrected_canvas)
            self.statusBar().showMessage(
                "扫描 PDF 页面已保持原始像素；需要特殊裁切时可使用手动四角校正"
            )
            return
        super().auto_perspective()

    def _on_processing_succeeded(self, result: object) -> None:
        super()._on_processing_succeeded(result)
        if not isinstance(result, VectorizationResult):
            return
        if self.corrected_image is None:
            return
        circles = []
        texts = []
        if result.auxiliary is not None:
            circles = confirmable_circles(result.auxiliary.circles)
            texts = result.auxiliary.texts
        self._approved_circles = list(circles)
        self.detected_canvas.set_vector_result(
            self.corrected_image,
            self.lines,
            circles=circles,
            texts=texts,
        )
        self.tabs.setCurrentWidget(self.detected_canvas)

    def review_layers(self) -> None:
        if not self.lines or self.corrected_image is None:
            QMessageBox.warning(
                self,
                "尚无可编辑实体",
                "请先完成“识别线条”，再在扫描底图上直接修改结果。",
            )
            return
        circles = []
        texts = []
        if self.auxiliary_result is not None:
            circles = confirmable_circles(self.auxiliary_result.circles)
            texts = self.auxiliary_result.texts
        dialog = VectorReviewDialog(
            self.corrected_image,
            self.lines,
            circles=circles,
            texts=texts,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reviewed_lines, reviewed_circles, reviewed_texts = dialog.reviewed_entities()
        self.lines = reviewed_lines
        self._approved_circles = reviewed_circles
        if self.classification_report is not None:
            self.classification_report.layer_counts = layer_counts(reviewed_lines)
        if self.auxiliary_result is None:
            self.auxiliary_result = AuxiliaryRecognitionResult(
                circles=list(reviewed_circles),
                texts=list(reviewed_texts),
                dimension_texts=[
                    text
                    for text in reviewed_texts
                    if text.kind == "dimension_text_candidate"
                ],
                symbols=[],
                warnings=[],
            )
        else:
            self.auxiliary_result.circles = list(reviewed_circles)
            self.auxiliary_result.texts = list(reviewed_texts)
            self.auxiliary_result.dimension_texts = [
                text
                for text in reviewed_texts
                if text.kind == "dimension_text_candidate"
            ]
        self.detected_canvas.set_vector_result(
            self.corrected_image,
            reviewed_lines,
            circles=reviewed_circles,
            texts=reviewed_texts,
        )
        self.tabs.setCurrentWidget(self.detected_canvas)
        warning = (
            "已保存可视化修改："
            f"LINE {len(reviewed_lines)}、CIRCLE {len(reviewed_circles)}、"
            f"TEXT {len(reviewed_texts)}。"
        )
        self._last_warnings = tuple(dict.fromkeys((*self._last_warnings, warning)))
        self.statusBar().showMessage(warning)

    def _current_page_label(self) -> str:
        if self.current_path is None:
            return f"Page {len(self._document_pages) + 1}"
        if self._current_pdf_page is not None:
            return f"{self.current_path.stem} - 第 {self._current_pdf_page} 页"
        return self.current_path.stem

    def _current_page_key(self) -> tuple[str | None, int | None]:
        source = (
            str(self.current_path.resolve()) if self.current_path is not None else None
        )
        return source, self._current_pdf_page

    def add_current_page_to_document(self) -> None:
        if self.corrected_image is None:
            QMessageBox.warning(
                self,
                "当前页尚未完成",
                "请先导入并处理当前页。",
            )
            return
        temporary_path = Path(self._document_tempdir.name) / (
            f"page-{uuid4().hex}.scan.png"
        )
        save_image(temporary_path, self.corrected_image)
        calibration = None
        if self.calibration is not None:
            calibration = ScaleCalibration(
                tuple(self.calibration.point1),
                tuple(self.calibration.point2),
                float(self.calibration.actual_length_mm),
            )
        texts = (
            tuple(self.auxiliary_result.texts)
            if self.auxiliary_result is not None
            else ()
        )
        page = DocumentPage(
            lines=tuple(line.copy() for line in self.lines),
            image_width=int(self.corrected_image.shape[1]),
            image_height=int(self.corrected_image.shape[0]),
            calibration=calibration,
            circles=tuple(self._approved_circles),
            texts=texts,
            raster_path=temporary_path,
            label=self._current_page_label(),
            source_path=Path(self.current_path)
            if self.current_path is not None
            else None,
            source_page=self._current_pdf_page,
        )
        key = self._current_page_key()
        replacement_index = next(
            (
                index
                for index, existing in enumerate(self._document_pages)
                if (
                    str(existing.source_path.resolve())
                    if existing.source_path is not None
                    else None,
                    existing.source_page,
                )
                == key
            ),
            None,
        )
        if replacement_index is None:
            self._document_pages.append(page)
            action = "加入"
        else:
            old_path = self._document_pages[replacement_index].raster_path
            self._document_pages[replacement_index] = page
            if old_path is not None and old_path.exists():
                old_path.unlink()
            action = "更新"
        self._refresh_document_status()
        self.statusBar().showMessage(
            f"已{action}合并文档页面：{page.label}；当前共 {len(self._document_pages)} 页"
        )

    def remove_last_document_page(self) -> None:
        if not self._document_pages:
            return
        page = self._document_pages.pop()
        if page.raster_path is not None and page.raster_path.exists():
            page.raster_path.unlink()
        self._refresh_document_status()
        self.statusBar().showMessage(f"已移除：{page.label}")

    def clear_document_pages(self) -> None:
        for page in self._document_pages:
            if page.raster_path is not None and page.raster_path.exists():
                page.raster_path.unlink()
        self._document_pages.clear()
        self._refresh_document_status()
        self.statusBar().showMessage("已清空多页合并队列")

    def _refresh_document_status(self) -> None:
        label = getattr(self, "document_status_label", None)
        if label is None:
            return
        if not self._document_pages:
            label.setText("当前未加入页面；单页仍可直接导出。")
            return
        names = "、".join(page.label for page in self._document_pages[-3:])
        prefix = "…、" if len(self._document_pages) > 3 else ""
        label.setText(f"待合并 {len(self._document_pages)} 页：{prefix}{names}")

    def export_file(self) -> None:
        if self._document_pages:
            export_document_from_window(self)
            return
        export_from_window(self, circles=self._approved_circles)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        super().closeEvent(event)
        if event.isAccepted():
            self._document_tempdir.cleanup()
