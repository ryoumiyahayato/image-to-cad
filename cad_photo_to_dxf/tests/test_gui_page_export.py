from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app import gui_page_export


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
    page_one_cache = tmp_path / "page-001.npz"
    page_three_cache = tmp_path / "page-003.npz"
    page_one_cache.write_bytes(b"one")
    page_three_cache.write_bytes(b"three")
    exported: list[tuple[object, Path]] = []
    reports: list[dict[str, object]] = []

    def fake_export(pages, output_path, **_kwargs):
        page = tuple(pages)[0]
        exported.append((page, output_path))
        return SimpleNamespace(
            path=output_path,
            structure_ids=(f"structure-{page}",),
            trace_path_count=1,
            trace_vertex_count=2,
            text_count=3,
            signature_paths=(),
            ocr_candidate_count=3,
            fallback_text_count=0,
            source_text_outline_count=0,
            residual_graphic_count=0,
            logo_count=0,
            text_downgrade_reasons=(),
            underlay_paths=(),
        )

    class Token:
        @staticmethod
        def checkpoint() -> None:
            return None

    status_messages: list[str] = []
    window = SimpleNamespace(
        _pdf_page_count=4,
        _pdf_page_states={
            0: {"trace_cache_path": str(page_one_cache)},
            1: {},
            2: {"trace_cache_path": str(page_three_cache)},
            3: {},
        },
        _save_current_pdf_state=lambda: None,
        current_path=tmp_path / "source.pdf",
        document_pages_for_export=lambda: iter(
            ("page-one", "page-two", "page-three", "page-four")
        ),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda message: status_messages.append(message)
        ),
    )

    def start_processing(operation, completed, _label) -> None:
        completed(operation(Token(), lambda _stage, _fraction: None))

    window._start_processing = start_processing
    monkeypatch.setattr(
        gui_page_export,
        "_select_output_path",
        lambda *_args, **_kwargs: (tmp_path / "drawing.dxf", False),
    )
    monkeypatch.setattr(
        gui_page_export,
        "_resolve_converter_on_ui",
        lambda *_args, **_kwargs: (None, None),
    )
    monkeypatch.setattr(
        gui_page_export,
        "export_trace_document_streaming",
        fake_export,
    )
    monkeypatch.setattr(
        gui_page_export,
        "write_json_report",
        lambda _path, report: reports.append(report),
    )
    monkeypatch.setattr(
        gui_page_export.QMessageBox,
        "question",
        lambda *_args, **_kwargs: (
            gui_page_export.QMessageBox.StandardButton.Yes
        ),
    )
    monkeypatch.setattr(
        gui_page_export.QMessageBox,
        "information",
        lambda *_args, **_kwargs: None,
    )

    gui_page_export._start_processed_pages_export(window)

    assert [page for page, _path in exported] == ["page-one", "page-three"]
    assert [path.name for _page, path in exported] == [
        "page-001.dxf",
        "page-003.dxf",
    ]
    assert reports[0]["exported_pages"] == [1, 3]
    assert reports[0]["skipped_pages"] == [2, 4]
    assert status_messages
