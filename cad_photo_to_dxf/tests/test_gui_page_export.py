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
