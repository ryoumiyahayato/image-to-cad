"""Prepare bundled fonts and open an existing result through one CAD service.

This is a normal desktop entry, including for a DXF obtained from a previous
run. It never starts recognition, changes the drawing, or assumes that copying
font files proves that an already running LibreCAD has loaded them.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QSettings, QThread, Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


# The service configures this parent's rotating file handler for windowed
# builds. UI worker diagnostics must follow it rather than a silent stderr.
LOGGER = logging.getLogger("app.cad_delivery.gui")
_STATE_LABELS = {
    "NOT_PREPARED": "未准备",
    "PREPARED": "已准备，可打开 CAD",
    "REOPEN_REQUIRED": "需要重新打开 CAD",
    "FAILED": "准备失败",
}
_BUSY_LABELS = {
    "inspect_result_fonts": "正在检查图纸所需字体和 LibreCAD…",
    "prepare_result_fonts": "正在准备 CAD 字体…",
    "launch_result_in_cad": "正在检查并打开图纸…",
}


class _CadDeliveryThread(QThread):
    """Keep font inspection/generation and process discovery off the UI thread."""

    def __init__(self, operation, dxf_path, cad_executable, parent):
        super().__init__(parent)
        self.operation = operation
        self.dxf_path = dxf_path
        self.cad_executable = cad_executable
        self.report = None

    def run(self):
        try:
            self.report = dict(
                self.operation(
                    self.dxf_path, cad_executable=self.cad_executable
                )
            )
            LOGGER.info("CAD delivery report: %r", self.report)
        except Exception:
            # Raw paths, resource hashes and tracebacks belong in the log. The
            # service supplies specific, safe reasons for expected failures.
            LOGGER.exception("CAD delivery operation failed")
            self.report = {
                "status": "FAILED",
                "message": "操作未能完成。请确认图纸和 LibreCAD 可以访问；详细原因已记录在应用日志中。",
                "can_prepare": False,
                "can_launch": False,
                "launch_requested": False,
            }


class CadFontPreparationDialog(QDialog):
    """Inspect, prepare, then explicitly open the user's saved DXF."""

    def __init__(self, parent=None, *, dxf_path=None, service=None, settings=None):
        super().__init__(parent)
        if service is None:
            from app import cad_delivery

            service = cad_delivery
        self.service = service
        self.settings = (
            settings
            if settings is not None
            else QSettings("ImageToCAD", "CadDeliveryV1")
        )
        self._thread = None
        self._close_result = None
        self._cad_executable = self.settings.value("librecad_executable", "", str) or None
        self.last_report = {}
        self.launch_requested = False
        self.last_launch = None
        self.setWindowTitle("打开已有 DXF / 准备 CAD 字体")
        self.resize(700, 340)
        self._build()
        if dxf_path is None:
            previous = self.settings.value("last_dxf", "", str)
            if previous and Path(previous).is_file():
                dxf_path = previous
        self.dxf_path = Path(dxf_path) if dxf_path else None
        self.dxf_edit.setText(str(self.dxf_path) if self.dxf_path else "")
        self.cad_edit.setText(self._cad_executable or "")
        self._apply_report({
            "status": "NOT_PREPARED",
            "message": "请选择已有 DXF；软件会检查所需字体和 LibreCAD。",
            "can_prepare": False,
            "can_launch": False,
        })
        if self.dxf_path is not None:
            self.inspect_fonts()

    @property
    def busy(self):
        # Count the queued finished signal as busy, too. Otherwise a new path
        # could be inspected before the prior result is applied.
        return self._thread is not None

    def _build(self):
        outer = QVBoxLayout(self)
        explanation = QLabel(
            "选择已有图纸，准备所需字体后在 LibreCAD 中打开。已有 DXF 可以直接使用，无需再次转换。"
        )
        explanation.setWordWrap(True)
        outer.addWidget(explanation)
        files = QGridLayout()
        self.dxf_edit = QLineEdit()
        self.dxf_edit.setReadOnly(True)
        self.dxf_edit.setPlaceholderText("选择要打开的 DXF")
        self.choose_dxf_button = QPushButton("选择 DXF…")
        self.choose_dxf_button.clicked.connect(self.choose_dxf)
        files.addWidget(QLabel("图纸"), 0, 0)
        files.addWidget(self.dxf_edit, 0, 1)
        files.addWidget(self.choose_dxf_button, 0, 2)
        self.cad_edit = QLineEdit()
        self.cad_edit.setReadOnly(True)
        self.cad_edit.setPlaceholderText("自动查找 LibreCAD；未找到时请选择程序")
        self.choose_cad_button = QPushButton("选择 LibreCAD…")
        self.choose_cad_button.clicked.connect(self.choose_cad)
        files.addWidget(QLabel("CAD 程序"), 1, 0)
        files.addWidget(self.cad_edit, 1, 1)
        files.addWidget(self.choose_cad_button, 1, 2)
        outer.addLayout(files)
        self.state_label = QLabel()
        self.state_label.setTextFormat(Qt.TextFormat.PlainText)
        self.state_label.setStyleSheet("font-weight: 600; font-size: 16px;")
        outer.addWidget(self.state_label)
        self.reason_label = QLabel()
        self.reason_label.setTextFormat(Qt.TextFormat.PlainText)
        self.reason_label.setWordWrap(True)
        outer.addWidget(self.reason_label)
        self.reopen_label = QLabel(
            "请先保存正在编辑的图纸，完全退出 LibreCAD，再点击“重新检查”。软件不会替您关闭 CAD。"
        )
        self.reopen_label.setWordWrap(True)
        outer.addWidget(self.reopen_label)
        self.operation_label = QLabel()
        self.operation_label.setTextFormat(Qt.TextFormat.PlainText)
        self.operation_label.setWordWrap(True)
        outer.addWidget(self.operation_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        outer.addStretch(1)
        buttons = QHBoxLayout()
        self.prepare_button = QPushButton("准备 CAD 字体")
        self.prepare_button.clicked.connect(self.prepare_fonts)
        self.recheck_button = QPushButton("重新检查")
        self.recheck_button.clicked.connect(self.inspect_fonts)
        self.open_button = QPushButton("在 LibreCAD 中打开")
        self.open_button.clicked.connect(self.open_in_cad)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        for button in (
            self.prepare_button, self.recheck_button, self.open_button, self.close_button
        ):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        outer.addLayout(buttons)

    def choose_dxf(self):
        if self.busy:
            return
        start = str(self.dxf_path.parent) if self.dxf_path else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择已有 DXF", start, "DXF 图纸 (*.dxf *.DXF)"
        )
        if not filename:
            return
        self.dxf_path = Path(filename)
        self.dxf_edit.setText(filename)
        self.settings.setValue("last_dxf", filename)
        self.inspect_fonts()

    def choose_cad(self):
        if self.busy:
            return
        start = (
            str(Path(self._cad_executable).parent)
            if self._cad_executable else str(Path.home())
        )
        program_filter = "LibreCAD 程序 (*.exe)" if sys.platform == "win32" else "LibreCAD 程序 (*)"
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择 LibreCAD 程序", start, program_filter
        )
        if not filename:
            return
        self._cad_executable = filename
        self.cad_edit.setText(filename)
        self.settings.setValue("librecad_executable", filename)
        if self.dxf_path is not None:
            self.inspect_fonts()

    def inspect_fonts(self):
        self._start_operation("inspect_result_fonts")

    def prepare_fonts(self):
        if self.last_report.get("can_prepare"):
            self._start_operation("prepare_result_fonts")

    def open_in_cad(self):
        if (
            self.last_report.get("status") == "PREPARED"
            and self.last_report.get("can_launch")
        ):
            self._start_operation("launch_result_in_cad")

    def _start_operation(self, name):
        if self.busy or self.dxf_path is None:
            return
        if name == "inspect_result_fonts":
            # A previous drawing/CAD pair's readiness cannot describe a newly
            # selected one, even during the asynchronous inspection interval.
            self._apply_report({
                "status": "NOT_PREPARED",
                "message": "正在核对所选图纸和 LibreCAD 的字体准备状态。",
                "can_prepare": False,
                "can_launch": False,
            })
        self._thread = _CadDeliveryThread(
            getattr(self.service, name), self.dxf_path, self._cad_executable, self
        )
        self._thread.finished.connect(self._operation_finished)
        self.operation_label.setText(_BUSY_LABELS[name])
        self._update_controls()
        self._thread.start()

    @Slot()
    def _operation_finished(self):
        thread = self._thread
        if thread is None:
            return
        report = thread.report or {
            "status": "FAILED", "message": "检查未返回结果，请重新检查。"
        }
        if report.get("launch_requested"):
            self.last_launch = {
                "dxf": thread.dxf_path,
                "cad_executable": report.get("cad_executable"),
            }
        self._thread = None
        thread.deleteLater()
        self._apply_report(report)
        if self._close_result is not None:
            result, self._close_result = self._close_result, None
            super().done(result)

    def _apply_report(self, report):
        self.last_report = dict(report)
        status = report.get("status", "FAILED")
        if status not in _STATE_LABELS:
            LOGGER.error("Unknown CAD delivery state: %r", report)
            status = "FAILED"
            self.last_report.update(status=status, can_prepare=False, can_launch=False)
            self.reason_label.setText("检查返回了无法识别的状态，请重新检查。")
        else:
            self.reason_label.setText(str(report.get("message", "")))
        self.state_label.setText(_STATE_LABELS[status])
        self.reopen_label.setVisible(status == "REOPEN_REQUIRED")
        executable = report.get("cad_executable")
        if executable:
            self._cad_executable = str(executable)
            self.cad_edit.setText(self._cad_executable)
        if report.get("launch_requested"):
            self.launch_requested = True
            self.operation_label.setText("已请求 LibreCAD 打开此图纸。请在 CAD 中查看并编辑。")
        else:
            self.operation_label.clear()
        self._update_controls()

    def _update_controls(self):
        idle = not self.busy
        has_dxf = self.dxf_path is not None
        self.choose_dxf_button.setEnabled(idle)
        self.choose_cad_button.setEnabled(idle)
        self.recheck_button.setEnabled(idle and has_dxf)
        self.prepare_button.setEnabled(
            idle and has_dxf and bool(self.last_report.get("can_prepare"))
        )
        self.open_button.setEnabled(
            idle and has_dxf
            and self.last_report.get("status") == "PREPARED"
            and bool(self.last_report.get("can_launch"))
        )
        self.progress.setVisible(not idle)
        self.close_button.setText("完成后关闭" if self._close_result is not None else "关闭")

    def done(self, result):
        # Let an in-flight preparation finish without destroying its QThread
        # or leaving an interrupted font copy. Closing never kills LibreCAD.
        if self.busy:
            self._close_result = result
            self.operation_label.setText("正在完成当前操作，随后关闭窗口。")
            self._update_controls()
            return
        super().done(result)

    def closeEvent(self, event):
        if self.busy:
            self.done(QDialog.DialogCode.Rejected)
            event.ignore()
        else:
            super().closeEvent(event)
