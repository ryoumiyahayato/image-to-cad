from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

import app.gui_exact_release as exact_release
from app.gui_exact_release import MainWindow
from app.raster_trace import trace_binary


_APP = QApplication.instance() or QApplication([])


def _prepared_window(tmp_path: Path) -> tuple[MainWindow, tuple[str, int | None], Path]:
    window = MainWindow()
    window._native_pdf_mode = True
    window.current_path = tmp_path / "source.pdf"
    window._current_pdf_page_index = 0
    binary = np.full((80, 120), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 10), (110, 70), 0, 3)
    paths = trace_binary(binary)
    window.binary_image = binary
    window._trace_paths = paths
    window._trace_threshold = 200
    window._trace_foreground_pixels = int(np.count_nonzero(binary == 0))
    window._trace_vertex_count = sum(len(path.points) for path in paths)
    cache_path = tmp_path / "page.npz"
    cache_path.write_bytes(b"existing-cache")
    key = window._current_trace_key()
    window._trace_cache_by_key[key] = cache_path
    window._pdf_page_states[0] = {"trace_cache_path": str(cache_path)}
    return window, key, cache_path


def test_export_reuses_unchanged_page_cache_without_recompression(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, _key, cache_path = _prepared_window(tmp_path)

    def unexpected_save(*_args, **_kwargs):
        raise AssertionError("unchanged cache must not be recompressed at export")

    monkeypatch.setattr(exact_release, "save_trace_cache", unexpected_save)
    assert window._store_current_trace() == cache_path
    window.close()


def test_modified_page_is_written_once_and_then_reused(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, key, cache_path = _prepared_window(tmp_path)
    window._dirty_trace_keys.add(key)
    calls: list[Path] = []

    def record_save(path, _result):
        calls.append(Path(path))
        return Path(path)

    monkeypatch.setattr(exact_release, "save_trace_cache", record_save)
    assert window._store_current_trace() == cache_path
    assert calls == [cache_path]
    assert key not in window._dirty_trace_keys
    assert window._store_current_trace() == cache_path
    assert calls == [cache_path]
    window.close()
