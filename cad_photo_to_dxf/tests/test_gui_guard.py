from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.gui_guard import MainWindow


class _StatusBar:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, message: str) -> None:
        self.message = message


class _WindowStub:
    def __init__(self, corrected: bool) -> None:
        self.original_image = np.zeros((10, 10, 3), dtype=np.uint8)
        self.corrected_image = self.original_image.copy() if corrected else None
        self._status_bar = _StatusBar()

    def _require_original(self) -> bool:
        return self.original_image is not None

    def statusBar(self) -> _StatusBar:
        return self._status_bar


def test_gui_blocks_processing_before_perspective_confirmation() -> None:
    window = _WindowStub(corrected=False)
    with patch("app.gui_guard.QMessageBox.warning") as warning:
        allowed = MainWindow._require_corrected(window)
    assert allowed is False
    warning.assert_called_once()
    assert "尚未确认纸张透视" in window._status_bar.message
    assert window.corrected_image is None


def test_gui_allows_processing_after_perspective_confirmation() -> None:
    window = _WindowStub(corrected=True)
    with patch("app.gui_guard.QMessageBox.warning") as warning:
        allowed = MainWindow._require_corrected(window)
    assert allowed is True
    warning.assert_not_called()
