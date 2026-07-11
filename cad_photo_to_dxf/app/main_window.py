from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .safe_gui import MainWindow as _AuditedMainWindow
from .ui_shell import MainWindow as _UiShellMainWindow
from .workflow_state import WorkflowState, WorkflowStateError


class MainWindow(_AuditedMainWindow):
    """Active GUI window with audited workflow and shared processing services."""

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

        # The UI shell only enters two-point selection mode. The audited
        # completion handler replaces the existing scale after the new
        # measurement has been accepted and validated.
        _UiShellMainWindow.start_scale_calibration(self)
