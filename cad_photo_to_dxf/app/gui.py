"""Backward-compatible GUI imports without a duplicate CAD pipeline.

The active application window is assembled by ``app.gui_state_guard``.  This
module keeps older imports working while exposing only the widget shell,
worker, image canvas, and the three perspective helpers used by the guarded
window.  It contains no preprocessing, line detection, geometry cleaning,
classification, DXF export, or reporting implementation.
"""

from __future__ import annotations

from .image_canvas import ImageCanvas, cv_to_qpixmap
from .perspective import auto_correct, resolve_paper_dimensions_mm, warp_perspective
from .ui_shell import MainWindow
from .worker import ProcessingWorker

__all__ = [
    "ImageCanvas",
    "MainWindow",
    "ProcessingWorker",
    "auto_correct",
    "cv_to_qpixmap",
    "resolve_paper_dimensions_mm",
    "warp_perspective",
]
