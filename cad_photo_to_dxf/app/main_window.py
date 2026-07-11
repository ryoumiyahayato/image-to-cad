from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .gui import MainWindow as _LegacyMainWindow
from .safe_gui import MainWindow as _AuditedMainWindow
from .workflow_state import WorkflowState, WorkflowStateError


class MainWindow(_AuditedMainWindow):
    """Active application window built on the audited compatibility layer.

    New behaviour belongs here while the remaining legacy widget construction is
    split into smaller modules. In particular, starting a second scale selection
    must not discard a valid existing calibration before the user completes the
    replacement measurement.
    """

    def start_scale_calibration(self) -> None:
        try:
            self._workflow.require(WorkflowState.VECTORIZED, "尺寸校准")
        except WorkflowStateError:
            QMessageBox.warning(
                self,
                "尚未完成矢量化",
                "请先完成透视校正、预处理和识别，再进行模型尺寸校准。",
            )
            return

        # Call the legacy UI selection implementation directly. The audited
        # completion handler in safe_gui._on_corrected_point replaces the scale
        # and workflow state only after two points and a valid length are accepted.
        _LegacyMainWindow.start_scale_calibration(self)
