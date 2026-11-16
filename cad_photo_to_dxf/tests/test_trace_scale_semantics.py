from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.cancellation import CancellationToken
from app.core.scale_calibrator import ScaleCalibration, create_calibration, resolve_drawing_scale
from app.core.structure_build import build_final_structure
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming
from app.geometry.line_detect import LineSegment
from app.gui import MainWindow
from app.gui import document as gui_document
from app.gui import export_worker
from app.ocr.auxiliary_recognition import TextCandidate


_APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("native_pdf", [False, True])
def test_known_length_calibration_is_not_overridden_by_local_note(native_pdf) -> None:
    window = MainWindow()
    window._native_pdf_mode = native_pdf
    window.original_image = np.full((100, 200, 3), 255, dtype=np.uint8)
    window.corrected_image = window.original_image.copy()
    window.paper_size_combo.setCurrentIndex(0)
    window.calibration = create_calibration([(10, 10), (110, 10)], 5000.0)
    window._final_structure = SimpleNamespace(
        texts=(TextCandidate("DETAIL A N.T.S.", (120, 12, 60, 8), 0.99, "text_candidate"),)
    )
    window.drawing_scale_spin.setValue(100)

    assert window._has_explicit_model_calibration()
    assert window._export_drawing_multiplier() == 1.0
    assert window._export_scale_decision().coordinate_space == "model_mm"
    window._update_scale_label()
    assert "不会再叠加图纸比例" in window.scale_result_label.text()
    window.close()


def test_pdf_paper_coordinates_use_selected_drawing_ratio() -> None:
    window = MainWindow()
    window._native_pdf_mode = True
    window.original_image = np.full((100, 200, 3), 255, dtype=np.uint8)
    window.corrected_image = window.original_image.copy()
    window.calibration = ScaleCalibration((0.0, 0.0), (199.0, 0.0), 420.0)
    window.drawing_scale_spin.setValue(50)

    assert not window._has_explicit_model_calibration()
    assert window._export_drawing_multiplier() == 50.0
    window._update_scale_label()
    assert "输出比例 1:50" in window.scale_result_label.text()
    window.close()


@pytest.mark.parametrize("notation", ["N.T.S.", "SCALE: NONE"])
def test_local_scale_note_keeps_paper_coordinates_and_reports_scope(tmp_path, monkeypatch, notation):
    size_px = (200, 100)
    size_mm = (100., 50.)
    binary = np.full(size_px[::-1], 255, dtype=np.uint8)
    lines = (LineSegment(10, 30, 30, 30), LineSegment(130, 30, 150, 30))
    plan = TextCandidate("FLOOR PLAN SCALE 1:50", (10, 12, 70, 8), 0.99, "text_candidate")
    detail = TextCandidate(f"DETAIL A {notation}", (120, 12, 60, 8), 0.99, "text_candidate")
    structure = build_final_structure(
        source_size_px=size_px, contour_binary=binary, contours=(),
        straight_lines=lines, texts=(plan, detail),
    )
    window = MainWindow()
    window._native_pdf_mode = True
    window.corrected_image = binary
    window.calibration = ScaleCalibration.for_paper(size_px, size_mm)
    window._final_structure = structure
    window._preview_structure_id = structure.structure_id
    window.drawing_scale_spin.setValue(50)
    single_path = tmp_path / "single.dxf"
    dialogs = []
    monkeypatch.setattr(export_worker, "_select_output_path", lambda *a, **kw: (single_path, False))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: dialogs.append(args[-1]))
    window._start_processing = lambda operation, completed, label: completed(
        operation(CancellationToken(), lambda *_: None)
    )
    try:
        assert window.drawing_scale_spin.value() == 50
        assert "缺少视图分区证据" in window.scale_result_label.text()
        export_worker._start_single_export(window)
    finally:
        window.close()
    assert "缺少视图分区证据" in dialogs[0]
    report = json.loads(single_path.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["coordinate_space"] == "paper_mm"
    assert report["drawing_multiplier"] == 1.
    assert report["scale_notes"] == [
        {"text": detail.text, "bbox_px": list(detail.bbox), "scope": "view"}
    ]

    multi_path = tmp_path / "multiple.dxf"
    pages = [
        DocumentPage(1, None, size_mm, final_structure=structure, drawing_scale=50.),
        DocumentPage(2, None, size_mm, lines=lines[:1], texts=(plan,),
                     vector_size_px=size_px, drawing_scale=50.),
        DocumentPage(3, None, (2000., 1000.), lines=lines[:1], texts=(detail,),
                     vector_size_px=size_px, model_calibrated=True),
    ]
    result = export_trace_document_streaming(pages, multi_path)
    mixed, uniform, calibrated = result.page_scales
    assert (mixed.multiplier, mixed.coordinate_space) == (1., "paper_mm")
    assert mixed.notes[0].bbox_px == detail.bbox
    assert mixed.notes[0].scope == "view"
    assert "缺少视图分区证据" in mixed.warning
    assert (uniform.multiplier, uniform.coordinate_space, uniform.warning) == (50., "model_mm", None)
    assert (calibrated.multiplier, calibrated.coordinate_space) == (1., "model_mm")
    for path, expected_lengths in [(single_path, [10., 10.]), (multi_path, [10., 10., 500., 200.])]:
        exported_lines = ezdxf.readfile(path).modelspace().query("LINE")
        assert [(line.dxf.end - line.dxf.start).magnitude for line in exported_lines] == pytest.approx(
            expected_lengths
        )


@pytest.mark.parametrize(("text", "scope"), [("ALL VIEWS N.T.S.", "sheet"), ("SCALE NONE", "unknown")])
def test_scale_scope_requires_a_subject(text, scope):
    note = TextCandidate(text, (10, 10, 60, 8), 0.99, "text_candidate")
    decision = resolve_drawing_scale((note,), 50.)
    assert decision.notes[0].scope == scope
    assert decision.coordinate_space == "paper_mm"
    assert ("缺少视图分区证据" in decision.warning) == (scope == "unknown")


def test_page_switch_clears_scale_notes_from_previous_page(tmp_path, monkeypatch):
    window = MainWindow()
    window.current_path = tmp_path / "unused.pdf"
    window._native_pdf_mode = True
    window._pdf_page_count = 2
    window._pdf_page_sizes_mm = {0: (100., 50.), 1: (100., 50.)}
    window.calibration = ScaleCalibration.for_paper((20, 10), (100., 50.))
    window._final_structure = SimpleNamespace(
        texts=(TextCandidate("DETAIL A N.T.S.", (1, 1, 10, 2), 0.99, "text_candidate"),)
    )
    window._pdf_page_states = {1: {"drawing_scale": 50.}}
    monkeypatch.setattr(gui_document, "load_image", lambda *a, **kw: np.zeros((10, 20, 3), np.uint8))
    try:
        window._update_scale_label()
        assert "缺少视图分区证据" in window.scale_result_label.text()
        window._load_pdf_page(1, save_current=False)
        assert "输出比例 1:50" in window.scale_result_label.text()
    finally:
        window.close()
