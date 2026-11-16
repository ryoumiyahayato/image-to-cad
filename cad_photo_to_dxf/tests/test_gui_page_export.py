from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.gui import page_export as gui_page_export


def test_processed_page_indices_skip_unprocessed_pages(tmp_path: Path) -> None:
    page_one = tmp_path / "page-001.npz"
    page_three = tmp_path / "page-003.npz"
    page_one.write_bytes(b"one")
    page_three.write_bytes(b"three")
    window = SimpleNamespace(
        _pdf_page_count=4,
        _pdf_page_states={
            0: {"trace_cache_path": str(page_one)},
            1: {},
            2: {"trace_cache_path": str(page_three)},
            3: {"trace_cache_path": str(tmp_path / "missing.npz")},
        },
    )

    assert gui_page_export._processed_page_indices(window) == (0, 2)


def test_current_page_export_ignores_unprocessed_sibling_pages(monkeypatch) -> None:
    called: list[object] = []
    window = SimpleNamespace(_is_processing=lambda: False)
    monkeypatch.setattr(
        gui_page_export,
        "_start_single_export",
        lambda value: called.append(value),
    )

    gui_page_export.export_current_page_from_window(window)

    assert called == [window]


def test_processed_pages_export_uses_partial_pdf_path(monkeypatch) -> None:
    called: list[object] = []
    window = SimpleNamespace(
        _is_processing=lambda: False,
        _native_pdf_mode=True,
    )
    monkeypatch.setattr(
        gui_page_export,
        "_start_processed_pages_export",
        lambda value: called.append(value),
    )

    gui_page_export.export_processed_pages_from_window(window)

    assert called == [window]


def test_non_pdf_processed_export_falls_back_to_current_page(monkeypatch) -> None:
    called: list[object] = []
    window = SimpleNamespace(
        _is_processing=lambda: False,
        _native_pdf_mode=False,
    )
    monkeypatch.setattr(
        gui_page_export,
        "_start_single_export",
        lambda value: called.append(value),
    )

    gui_page_export.export_processed_pages_from_window(window)

    assert called == [window]


def test_partial_pdf_export_skips_unprocessed_and_keeps_page_numbers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json

    import ezdxf
    import numpy as np
    import pypdfium2 as pdfium
    import pytest
    from PySide6.QtWidgets import QFileDialog

    from app.core.arc_types import ArcSegment
    from app.core.cancellation import CancellationToken
    from app.core.image_loader import pdf_page_size_mm
    from app.core.structure_build import build_final_structure
    from app.geometry.line_detect import LineSegment
    from app.gui import MainWindow
    from app.gui.worker import ProcessingWorker
    from app.ocr.auxiliary_recognition import TextCandidate

    source = tmp_path / "source.pdf"
    with pdfium.PdfDocument.new() as pdf:
        for width, height in ((144, 72), (72, 36), (72, 36), (72, 36)):
            pdf.new_page(width, height).close()
        pdf.save(source)

    size = (200, 100)
    binary = np.full(size[::-1], 255, dtype=np.uint8)
    detail = TextCandidate("DETAIL A N.T.S.", (120, 12, 60, 8), 0.99, "text_candidate")
    plan = TextCandidate("FLOOR PLAN SCALE 1:50", (10, 12, 70, 8), 0.99, "text_candidate")
    page_one = build_final_structure(
        source_size_px=size, contour_binary=binary, contours=(),
        straight_lines=(LineSegment(10, 30, 30, 30), LineSegment(130, 30, 150, 30)),
        texts=(plan, detail),
    )
    page_three = build_final_structure(
        source_size_px=size, contour_binary=binary, contours=(),
        straight_lines=(LineSegment(10, 30, 30, 30),),
        arcs=(ArcSegment("third-page-arc", (60, 40), 8, 0, 90),),
    )

    failures, dialogs, status = [], [], []

    class WindowState(SimpleNamespace):
        """Bind the product's Python window methods without creating widgets."""

        def __getattr__(self, name):
            return getattr(MainWindow, name).__get__(self, type(self))

        def _start_processing(self, operation, completed, _label):
            worker = ProcessingWorker(operation, CancellationToken())
            worker.failed.connect(failures.append)
            worker.succeeded.connect(completed)
            worker.run()

        def statusBar(self):
            return SimpleNamespace(showMessage=status.append)

    window = WindowState(
        current_path=source, _native_pdf_mode=True, _pdf_page_count=4,
        _pdf_page_states={}, _worker_thread=None,
        _pdf_page_sizes_mm={i: pdf_page_size_mm(source, i) for i in range(4)},
        _trace_cache_tempdir=SimpleNamespace(name=tmp_path),
        _trace_cache_by_key={}, _dirty_trace_keys=set(),
        corrected_image=binary, binary_image=binary,
        raw_lines=[], lines=[], auxiliary_result=None, preprocess_stages={},
        _last_warnings=(), _run_started_at=None, _run_duration_seconds=None,
        _last_preprocess_scale=1.0, _last_preprocess_params=None, _reviewed_circles=[],
        _trace_paths=(), _trace_threshold=128, _trace_foreground_pixels=0, _trace_vertex_count=0,
    )
    window._current_pdf_page_index = 2
    window._final_structure = page_three
    window.drawing_scale_spin = SimpleNamespace(value=lambda: 25)
    window._save_current_pdf_state()

    window._current_pdf_page_index = 0
    window._final_structure = page_one
    window.drawing_scale_spin = SimpleNamespace(value=lambda: 50)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *_args: (str(tmp_path / "drawing.dxf"), "Drawing Exchange Format (*.dxf)"),
    )
    monkeypatch.setattr(
        gui_page_export.QMessageBox, "question",
        lambda *_args: gui_page_export.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        gui_page_export.QMessageBox, "information", lambda *args: dialogs.append(args[-1]),
    )

    window.export_processed_pages()

    assert failures == []
    out = tmp_path / "drawing-pages"
    report = json.loads((out / "export.report.json").read_text(encoding="utf-8"))
    assert report["exported_pages"] == [1, 3]
    assert report["skipped_pages"] == [2, 4]
    first, third = report["pages"]
    assert [first["structure_id"], third["structure_id"]] == [
        page_one.structure_id, page_three.structure_id,
    ]
    assert (first["drawing_multiplier"], first["coordinate_space"]) == (1., "paper_mm")
    assert first["scale_notes"] == [{"text": detail.text, "bbox_px": list(detail.bbox), "scope": "view"}]
    assert "缺少视图分区证据" in first["scale_warning"]
    assert any(first["scale_warning"] in warning for warning in report["warnings"])
    assert (third["drawing_multiplier"], third["coordinate_space"]) == (25., "model_mm")
    assert third["scale_warning"] is None
    assert [first["arc_count"], third["arc_count"]] == [0, 1]
    assert sorted(path.name for path in out.glob("*.dxf")) == ["page-001.dxf", "page-003.dxf"]
    for number, lengths in ((1, [5.08, 5.08]), (3, [63.5])):
        doc = ezdxf.readfile(out / f"page-{number:03d}.dxf")
        model = doc.modelspace()
        assert not doc.audit().errors
        line_lengths = [(line.dxf.end - line.dxf.start).magnitude for line in model.query("LINE")]
        assert line_lengths == pytest.approx(lengths)
        if number == 1:
            assert {entity.dxf.text for entity in model.query("TEXT")} == {plan.text, detail.text}
        else:
            assert [arc.dxf.radius for arc in model.query("ARC")] == pytest.approx([25.4])
    assert "缺少视图分区证据" in dialogs[0]
    assert status
