from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication
import pytest

import app.gui_exact_release as exact_release
from app.auxiliary_recognition import TextCandidate
from app.final_structure import build_final_structure
from app.gui_exact_release import MainWindow
from app.gui_librecad_release import MainWindow as ActiveMainWindow
from app.processing_contract import (
    ProductionProcessingService,
)
from app.raster_trace import trace_binary
from app.trace_storage import save_trace_cache


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
    structure = build_final_structure(
        source_size_px=(binary.shape[1], binary.shape[0]),
        contour_binary=binary,
        contours=paths,
        preview_binary=binary,
        threshold=200,
    )
    window._final_structure = structure
    window._preview_structure_id = structure.structure_id
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

    def record_save(path, _result, **_kwargs):
        calls.append(Path(path))
        return Path(path)

    monkeypatch.setattr(exact_release, "save_trace_cache", record_save)
    assert window._store_current_trace() == cache_path
    assert calls == [cache_path]
    assert key not in window._dirty_trace_keys
    assert window._store_current_trace() == cache_path
    assert calls == [cache_path]
    window.close()


def test_reviewed_text_rebuilds_the_same_final_structure_used_by_export(
    tmp_path: Path,
) -> None:
    window, key, _cache_path = _prepared_window(tmp_path)
    previous_id = window._final_structure.structure_id
    reviewed = TextCandidate(
        text="ROOM",
        bbox=(20, 20, 60, 20),
        confidence=0.95,
        kind="text_candidate",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )

    updated = window._replace_final_structure_texts((reviewed,))

    assert updated.structure_id != previous_id
    assert window._final_structure is updated
    assert window._preview_structure_id == updated.structure_id
    assert window._ocr_texts == (reviewed,)
    assert key in window._dirty_trace_keys
    window.close()


def test_active_gui_rejects_cache_after_same_path_content_changes(
    tmp_path: Path,
) -> None:
    window = ActiveMainWindow()
    try:
        source = tmp_path / "source.pdf"
        source.write_bytes(b"first PDF content")
        window._native_pdf_mode = True
        window.current_path = source
        window._current_pdf_page_index = 0
        window._pdf_page_sizes_mm = [(210.0, 297.0)]
        window._ocr_enabled = lambda: False  # type: ignore[method-assign]
        key = window._source_key(source, 0)
        config = window._processing_config(0, enable_ocr=False)
        image = np.full((80, 120), 255, dtype=np.uint8)
        cv2.rectangle(image, (10, 10), (110, 70), 0, 2)
        result = ProductionProcessingService.process_page(image, config)
        cache_path = save_trace_cache(
            tmp_path / "active-page.npz",
            result,
            cache_key=key.payload(),
        )
        window._pdf_page_states[0] = {
            "trace_cache_path": str(cache_path),
            "trace_cache_key": key.payload(),
            "trace_cache_key_digest": key.digest,
        }

        window._restore_cached_trace_for_page(0)
        assert window._final_structure is not None
        assert (
            window._preview_structure_id
            == window._final_structure.structure_id
        )

        source.write_bytes(b"second PDF content")
        with pytest.raises(ValueError, match="cache key"):
            window._restore_cached_trace_for_page(0)
        assert window._final_structure is None
        assert window._preview_structure_id is None
    finally:
        window.close()
