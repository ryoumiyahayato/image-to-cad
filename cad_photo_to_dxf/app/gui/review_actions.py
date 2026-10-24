from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton

from app.core.structure import metadata_to_jsonable
from app.core.structure_build import (
    build_final_structure,
    final_structure_from_trace_result,
)
from app.ocr.font_library import default_font_face
from app.core.image_loader import load_image
from app.gui.librecad_ocr_review import (
    LibreCadLffOcrReviewDialog as _BaseOcrReviewDialog,
)
from app.export.ocr_outline_export import accepted_ocr_texts
from app.core.preview import render_final_structure_preview
from app.geometry.raster_trace import RasterTraceResult, trace_binary
from app.ocr.text_output_contract import text_output_summary
from app.gui.trace_paint import TracePaintDialog
from app.diagnostics.trace_verification import (
    TraceVerificationResult,
    verify_trace_paths,
)
from app.diagnostics.visual_acceptance import default_visual_acceptance_root


PREVIEW_MAX_DIMENSION = 2400


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
                or ("字形来源：LibreCAD" in text)
            ):
                label.setVisible(False)
        for button in self.findChildren(QPushButton):
            if (
                "安装/修复 LibreCAD" in button.text()
                or "使用 LibreCAD 字体" in button.text()
            ):
                button.setVisible(False)

    def accept(self) -> None:
        QDialog.accept(self)

    def _force_lff(self, index: int) -> None:
        """Keep or assign a normal Windows font; the bundled LFF is not required."""
        if not 0 <= index < len(self._candidates):
            return
        candidate = self._candidates[index]
        if candidate is None or (candidate.font_family and candidate.font_file):
            return
        face = default_font_face(candidate.text)
        self._candidates[index] = replace(
            candidate,
            font_family=face.family,
            font_file=face.filename,
            font_match_score=max(float(candidate.font_match_score), 0.5),
        )


def _preview_shape(self) -> tuple[int, int] | None:
    if self.original_image is None:
        return None
    return tuple((int(value) for value in self.original_image.shape[:2]))


def _refresh_visual_acceptance(self) -> None:
    if getattr(self, "_review_project", None) is not None:
        # Legacy VQA has no review overlay input; the emitted CAD preview above
        # is authoritative for this snapshot, never show a stale OCR VQA image.
        self.visual_acceptance.clear_result()
        return
    if self.tabs.currentWidget() is not self.visual_acceptance:
        return
    structure = self._final_structure
    if structure is None or self.current_path is None:
        return
    source = self._visual_acceptance_source()
    page_label = (
        f"第 {self._current_pdf_page_index + 1} 页" if self._native_pdf_mode else "单页"
    )
    repository_root = Path(__file__).resolve().parents[3]
    run = self.visual_acceptance.set_result(
        source,
        structure,
        source_label=Path(self.current_path).name,
        page_label=page_label,
        commit="UNKNOWN",
        output_root=default_visual_acceptance_root(repository_root),
    )
    self.tabs.setCurrentWidget(self.visual_acceptance)
    self.statusBar().showMessage(f"视觉验收总览已生成：{run.overview_path}")


def _replace_final_structure_texts(self, texts):
    if getattr(self, "_review_project", None) is not None:
        raise ValueError("Saved snapshots require explicit correction journal events")
    structure = self._final_structure
    if structure is None:
        raise ValueError("Current page has no FinalStructure")
    text_summary = text_output_summary(texts)
    observations = tuple(
        (
            {
                "event": "text_output_contract",
                **text_summary.payload(),
                "logo_count": len(structure.logos),
                "signature_count": len(structure.signatures),
            }
            if item.get("event") == "text_output_contract"
            else metadata_to_jsonable(item)
            for item in structure.observations
        )
    )
    if not any((item.get("event") == "text_output_contract" for item in observations)):
        observations = (
            *observations,
            {
                "event": "text_output_contract",
                **text_summary.payload(),
                "logo_count": len(structure.logos),
                "signature_count": len(structure.signatures),
            },
        )
    provenance = metadata_to_jsonable(structure.provenance)
    if not isinstance(provenance, dict):
        raise TypeError("FinalStructure provenance must serialize as an object")
    provenance["gui_text_reviewed"] = True
    updated = build_final_structure(
        source_size_px=structure.source_size_px,
        contour_binary=structure.contour_binary,
        contours=structure.contours,
        straight_lines=structure.straight_lines,
        arcs=structure.arcs,
        native_fills=structure.native_fills,
        texts=texts,
        logos=structure.logos,
        signatures=structure.signatures,
        editable_text_source_mask=structure.editable_text_source_mask,
        source_text_outline_mask=structure.source_text_outline_mask,
        uncertain_text_outline_mask=structure.uncertain_text_outline_mask,
        preview_binary=structure.preview_binary,
        threshold=structure.threshold,
        warnings=structure.warnings,
        provenance=provenance,
        observations=observations,
    )
    self._final_structure = updated
    self._preview_structure_id = updated.structure_id
    self._ocr_texts = updated.texts
    self._cad_preview_binary = render_final_structure_preview(updated)
    self.detected_canvas.set_image(self._cad_preview_binary)
    self._dirty_trace_keys.add(self._current_trace_key())
    structure = updated
    self._refresh_visual_acceptance()
    return structure


@staticmethod
def _scaled_for_preview(
    image: np.ndarray, *, target_shape: tuple[int, int] | None = None
) -> np.ndarray:
    height, width = image.shape[:2]
    if target_shape is not None:
        target_height, target_width = target_shape
        if (
            target_height > 0
            and target_width > 0
            and (target_height != height or target_width != width)
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
        (max(1, int(round(width * ratio))), max(1, int(round(height * ratio)))),
        interpolation=cv2.INTER_AREA,
    )


def _visual_acceptance_source(self):
    structure = self._final_structure
    if structure is None:
        raise ValueError("当前页没有最终 CAD 结构")
    source = self._load_trace_source_for_current_page()
    if (source.shape[1], source.shape[0]) != structure.source_size_px:
        raise ValueError("原图与最终 CAD 结构不在同一坐标系")
    return source


def review_layers(self) -> None:
    if getattr(self, "_review_project", None) is not None:
        QMessageBox.information(
            self,
            "保存快照",
            "校对项目只修改文字内容。几何修改需要重新转换，原校对不会自动套用。",
        )
        return
    if self.binary_image is None:
        QMessageBox.warning(self, "尚无处理结果", "请先处理当前页。")
        return
    dialog = TracePaintDialog(self.binary_image, self)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    edited = dialog.edited_binary()
    if np.array_equal(edited, self.binary_image):
        self.statusBar().showMessage("内容未修改，已保留当前 CAD 结构")
        return
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    revision = self._state_revision
    previous_structure = self._final_structure

    def operation(token, progress) -> object:
        paths = trace_binary(
            edited, cancellation_token=token, progress_callback=progress
        )
        result = RasterTraceResult(
            binary=edited,
            stages={},
            paths=paths,
            threshold=self._trace_threshold or 128,
            foreground_pixels=int((edited == 0).sum()),
            vertex_count=sum((len(path.points) for path in paths)),
            warnings=(),
            texts=tuple(self._ocr_texts),
            signatures=tuple(self._signature_regions),
            arcs=previous_structure.arcs if previous_structure is not None else (),
            native_fills=previous_structure.native_fills
            if previous_structure is not None
            else (),
        )
        if result.arcs:
            rebuilt = final_structure_from_trace_result(result)
            provenance = metadata_to_jsonable(rebuilt.provenance)
            provenance["native_arc_replacements"] = metadata_to_jsonable(
                previous_structure.provenance.get("native_arc_replacements", ())
            )
            result = replace(
                result, final_structure=replace(rebuilt, provenance=provenance)
            )
        return result

    def completed(value: object) -> None:
        if revision != self._state_revision:
            return
        self._apply_trace_result(
            value,
            started_at=started_at,
            duration=time.perf_counter() - started,
            save_pdf_state=self._native_pdf_mode,
        )
        self.statusBar().showMessage("已按修改内容重新生成当前页 CAD")

    self._start_processing(operation, completed, "正在应用修改并重新生成 CAD…")


def review_ocr_texts(self) -> None:
    if getattr(self, "_review_project", None) is not None or (
        getattr(self, "_final_structure", None) is not None
        and getattr(self, "current_path", None) is not None
    ):
        from app.gui.review_project_actions import review_snapshot_texts

        review_snapshot_texts(self)
        return
    if not self._ocr_texts:
        QMessageBox.warning(self, "尚无文字结果", "请先处理当前页。")
        return
    try:
        if self._native_pdf_mode and self.current_path is not None:
            source = load_image(
                self.current_path,
                page_index=self._current_pdf_page_index,
                pdf_dpi=self._processing_pdf_dpi(self._current_pdf_page_index),
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
    self._replace_final_structure_texts(tuple(dialog.reviewed_texts()))
    if self._native_pdf_mode:
        self._save_current_pdf_state()
    exportable = accepted_ocr_texts(self._ocr_texts)
    retained = max(0, len(self._ocr_texts) - len(exportable))
    self.statusBar().showMessage(
        f"文字检查已保存：{len(exportable)} 项可编辑文字，{retained} 项保留为图像"
    )


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
            binary, paths, cancellation_token=token, progress_callback=progress
        )

    def completed(value: object) -> None:
        if revision != self._state_revision:
            return
        result: TraceVerificationResult = value
        self.detected_canvas.set_image(
            self._scaled_for_preview(result.overlay, target_shape=self._preview_shape())
        )
        self.tabs.setCurrentWidget(self.detected_canvas)
        if result.exact:
            QMessageBox.information(
                self, "核对完成", "当前页生成内容与黑白来源一致，没有发现遗漏像素。"
            )
        else:
            QMessageBox.warning(
                self,
                "发现差异",
                f"发现 {result.different_pixels} 个差异像素，请进入检查与修改。",
            )

    self._start_processing(operation, completed, "正在核对当前页…")
