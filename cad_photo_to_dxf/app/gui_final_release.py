from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QSplitter

from . import gui_librecad_release as _release


PROCESS_PDF_DPI = 240
PROCESS_PDF_MAX_SIDE = 4800
SIDEBAR_MINIMUM_WIDTH = 500
SIDEBAR_WIDTH = 540
_release.TRACE_PDF_DPI = PROCESS_PDF_DPI
_release.PROCESS_PDF_MAX_SIDE = PROCESS_PDF_MAX_SIDE


class MainWindow(_release.MainWindow):
    """Final desktop shell with a readable sidebar and bounded scan workload."""

    def __init__(self) -> None:
        super().__init__()
        splitter = self.centralWidget()
        if isinstance(splitter, QSplitter):
            splitter.setCollapsible(0, False)
            controls = splitter.widget(0)
            if controls is not None:
                controls.setMinimumWidth(SIDEBAR_MINIMUM_WIDTH)
            splitter.setSizes([SIDEBAR_WIDTH, max(860, self.width() - SIDEBAR_WIDTH)])
        self.statusBar().showMessage("可处理当前页或全部页面；扫描件会自动清理纸张底色和破损纹理")

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        if isinstance(scroll, QScrollArea):
            scroll.setMinimumWidth(SIDEBAR_MINIMUM_WIDTH)
        return scroll
