"""Backward-compatible GUI imports.

The active application window is ``app.main_window.MainWindow``. This module
contains no image-processing, CAD-cleaning, export, or reporting implementation;
it only preserves older imports while callers migrate to the split UI modules.
"""

from __future__ import annotations

from .image_canvas import ImageCanvas, cv_to_qpixmap
from .ui_shell import MainWindow
from .worker import ProcessingWorker

__all__ = [
    "ImageCanvas",
    "MainWindow",
    "ProcessingWorker",
    "cv_to_qpixmap",
]
