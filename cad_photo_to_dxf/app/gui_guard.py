from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from . import gui as _gui
from .geometry_normalized import clean_geometry_with_report as _normalized_geometry_clean

# The active GUI still lives in the legacy module, but route its runtime global
# through the same resolution-normalized geometry service used by the CLI.
_gui.clean_geometry_with_report = _normalized_geometry_clean
_LegacyMainWindow = _gui.MainWindow


class MainWindow(_LegacyMainWindow):
    """GUI entry point with mandatory perspective confirmation.

    The legacy window silently copied the imported image into ``corrected_image``
    when preprocessing or vectorization was requested. That made the nominally
    strict GUI path process perspective-distorted photos without any warning.
    """

    def _require_corrected(self) -> bool:
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "需要确认纸张透视",
            "请先执行自动纸张校正，或手工确认四个纸张角点。\n\n"
            "当前版本不再把未经校正的原图静默视为已校正图。",
        )
        self.statusBar().showMessage("已阻止处理：尚未确认纸张透视")
        return False
