from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .gui import MainWindow as _LegacyMainWindow


class MainWindow(_LegacyMainWindow):
    """GUI entrypoint with a strict perspective-confirmation gate.

    The legacy window previously copied the original photograph into the corrected
    slot when the user skipped perspective correction. That silently allowed a
    distorted phone photo to reach vectorization. Until the GUI is fully migrated
    to the shared pipeline service, this subclass makes the required state explicit.
    """

    def _require_corrected(self) -> bool:
        if self.corrected_image is not None:
            return True
        if not self._require_original():
            return False
        QMessageBox.warning(
            self,
            "尚未确认透视校正",
            "请先执行“自动透视校正”，或使用“手动点击四角并校正”。\n"
            "系统不会再把原始照片静默当作已校正图像。",
        )
        self.statusBar().showMessage("处理已阻止：必须先确认纸张四角和透视校正")
        return False
