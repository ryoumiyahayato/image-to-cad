"""Qt interaction checks; these do not claim Windows LibreCAD GUI coverage."""

from collections import deque
import logging
from pathlib import Path
from threading import Event, get_ident
import time

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel

from app.gui.cad_font_dialog import CadFontPreparationDialog


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def preferences(tmp_path):
    return QSettings(str(tmp_path / "cad-dialog.ini"), QSettings.Format.IniFormat)


def wait_for(qt_app, condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition():
        qt_app.processEvents()
        if time.monotonic() >= deadline:
            pytest.fail("Qt operation did not complete")
        time.sleep(0.002)
    qt_app.processEvents()


def report(status, **overrides):
    result = {
        "status": status,
        "message": {
            "NOT_PREPARED": "图纸所需字体尚未准备。",
            "PREPARED": "所需资源已准备，可打开 CAD。",
            "REOPEN_REQUIRED": "LibreCAD 正在运行，需要完全退出后重新打开。",
            "FAILED": "未找到 LibreCAD，请选择已安装的 LibreCAD 程序。",
        }[status],
        "cad_executable": "/cad/LibreCAD.exe",
        "can_prepare": status == "NOT_PREPARED",
        "can_launch": status == "PREPARED",
        "launch_requested": False,
    }
    result.update(overrides)
    return result


class Service:
    def __init__(self, *, inspect=(), prepare=(), launch=()):
        self.responses = {
            "inspect": deque(inspect), "prepare": deque(prepare), "launch": deque(launch)
        }
        self.calls = []

    def _call(self, action, path, cad_executable):
        self.calls.append((action, Path(path), cad_executable, get_ident()))
        value = self.responses[action].popleft()
        if callable(value):
            return value()
        if isinstance(value, Exception):
            raise value
        return value

    def inspect_result_fonts(self, path, cad_executable=None):
        return self._call("inspect", path, cad_executable)

    def prepare_result_fonts(self, path, cad_executable=None):
        return self._call("prepare", path, cad_executable)

    def launch_result_in_cad(self, path, cad_executable=None):
        return self._call("launch", path, cad_executable)


def test_existing_dxf_prepare_reopen_and_explicit_launch(qt_app, preferences, tmp_path, monkeypatch):
    dxf = tmp_path / "actual-saved-result.dxf"
    dxf.write_text("existing result", encoding="utf-8")
    service = Service(
        inspect=[report("NOT_PREPARED"), report("PREPARED")],
        prepare=[report("REOPEN_REQUIRED")],
        launch=[report("PREPARED", launch_requested=True)],
    )
    dialog = CadFontPreparationDialog(service=service, settings=preferences)
    try:
        assert not dialog.prepare_button.isEnabled()
        assert not dialog.open_button.isEnabled()
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(dxf), "DXF"))
        dialog.choose_dxf_button.click()
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.prepare_button.isEnabled()
        assert not dialog.open_button.isEnabled()
        dialog.prepare_button.click()
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.last_report["status"] == "REOPEN_REQUIRED"
        assert "完全退出" in dialog.reopen_label.text()
        assert not dialog.open_button.isEnabled()
        assert not dialog.launch_requested
        # Copying/preparing while CAD was running must not open another CAD or
        # pretend that a font has already been loaded by the existing process.
        dialog.open_in_cad()
        assert [call[0] for call in service.calls] == ["inspect", "prepare"]
        dialog.recheck_button.click()
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.open_button.isEnabled()
        assert dialog.state_label.text() == "已准备，可打开 CAD"
        dialog.open_button.click()
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.launch_requested
        assert dialog.last_launch["dxf"] == dxf
        assert "已请求" in dialog.operation_label.text()
        assert [call[0] for call in service.calls] == ["inspect", "prepare", "inspect", "launch"]
        assert all(call[1] == dxf for call in service.calls)
        assert all(call[3] != get_ident() for call in service.calls)
        assert service.calls[0][2] is None
        assert all(call[2] == "/cad/LibreCAD.exe" for call in service.calls[1:])
        assert preferences.value("last_dxf") == str(dxf)
    finally:
        dialog.close()


def test_changed_dxf_and_cad_are_rechecked_before_launch(qt_app, preferences, tmp_path, monkeypatch):
    first, second = tmp_path / "one.dxf", tmp_path / "two.dxf"
    first.touch()
    second.touch()
    release = Event()

    def pending_inspection():
        assert release.wait(5)
        return report("NOT_PREPARED")

    service = Service(inspect=[report("PREPARED"), pending_inspection, report("PREPARED")])
    dialog = CadFontPreparationDialog(dxf_path=first, service=service, settings=preferences)
    try:
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.open_button.isEnabled()
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(second), "DXF"))
        dialog.choose_dxf_button.click()
        assert dialog.busy
        assert dialog.last_report["status"] == "NOT_PREPARED"
        assert not dialog.open_button.isEnabled()
        dialog.open_in_cad()
        release.set()
        wait_for(qt_app, lambda: not dialog.busy)
        assert dialog.last_report["status"] == "NOT_PREPARED"
        assert not dialog.open_button.isEnabled()
        assert [call[0] for call in service.calls] == ["inspect", "inspect"]
        chosen = str(tmp_path / "chosen" / "LibreCAD.exe")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (chosen, "application"))
        dialog.choose_cad_button.click()
        wait_for(qt_app, lambda: not dialog.busy)
        assert service.calls[-1][1:3] == (second, chosen)
        assert preferences.value("librecad_executable") == chosen
        assert dialog.open_button.isEnabled()
    finally:
        release.set()
        wait_for(qt_app, lambda: not dialog.busy)
        dialog.close()


def test_failures_show_safe_reason_and_keep_internal_diagnostics_in_log(
    qt_app, preferences, tmp_path, caplog
):
    private_path = "C:/internal-resource-store/font/private-font.lff"
    digest = "ab" * 32
    service = Service(inspect=[report(
        "FAILED", cad_executable=None,
        font_directory=private_path, sha256=digest,
    ), PermissionError(private_path)])
    diagnostic_log = tmp_path / "cad-fonts.log"
    handler = logging.FileHandler(diagnostic_log, encoding="utf-8")
    service_logger = logging.getLogger("app.cad_delivery")
    service_logger.addHandler(handler)
    with caplog.at_level(logging.INFO, logger="app.cad_delivery.gui"):
        dialog = CadFontPreparationDialog(
            dxf_path=tmp_path / "one.dxf", service=service, settings=preferences
        )
        try:
            wait_for(qt_app, lambda: not dialog.busy)
            labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            assert "未找到 LibreCAD" in labels
            assert private_path not in labels
            assert digest not in labels
            assert private_path in caplog.text
            assert digest in caplog.text
            assert not dialog.open_button.isEnabled()
            dialog.recheck_button.click()
            wait_for(qt_app, lambda: not dialog.busy)
            assert dialog.last_report["status"] == "FAILED"
            assert private_path not in dialog.reason_label.text()
            assert "应用日志" in dialog.reason_label.text()
            handler.flush()
            assert "CAD delivery operation failed" in diagnostic_log.read_text(encoding="utf-8")
            assert private_path in diagnostic_log.read_text(encoding="utf-8")
        finally:
            dialog.close()
            service_logger.removeHandler(handler)
            handler.close()


def test_close_waits_without_blocking_qt_or_interrupting_prepare(qt_app, preferences, tmp_path):
    entered, release = Event(), Event()

    def preparing():
        entered.set()
        assert release.wait(5)
        return report("PREPARED")

    service = Service(inspect=[report("NOT_PREPARED")], prepare=[preparing])
    dialog = CadFontPreparationDialog(
        dxf_path=tmp_path / "one.dxf", service=service, settings=preferences
    )
    dialog.show()
    try:
        wait_for(qt_app, lambda: not dialog.busy)
        dialog.prepare_button.click()
        wait_for(qt_app, entered.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        dialog.close_button.click()
        wait_for(qt_app, lambda: bool(heartbeat))
        assert dialog.isVisible()
        assert dialog.busy
        assert dialog._close_result is not None
        release.set()
        wait_for(qt_app, lambda: not dialog.busy)
        assert not dialog.isVisible()
        assert service.calls[-1][0] == "prepare"
    finally:
        release.set()
        wait_for(qt_app, lambda: not dialog.busy)
        dialog.close()


def test_menu_and_native_workspace_share_existing_dxf_entry_and_publish_guard(
    qt_app, tmp_path, monkeypatch
):
    from app.gui import MainWindow
    from app.gui import cad_font_dialog
    from app.gui.native_task_viewmodel import PUBLISHED_STATUSES

    monkeypatch.setenv("I2CAD_JOBS_ROOT", str(tmp_path / "jobs"))
    opened = []

    class Dialog:
        def __init__(self, parent=None, *, dxf_path=None):
            self.dxf_path = dxf_path
            self.last_launch = None

        def exec(self):
            opened.append(self.dxf_path)

    monkeypatch.setattr(cad_font_dialog, "CadFontPreparationDialog", Dialog)
    window = MainWindow()
    try:
        panel = window.native_task_panel
        panel.poll_timer.stop()
        assert panel.state is None
        assert panel.existing_dxf_button.isEnabled()
        panel.existing_dxf_button.click()
        window._cad_delivery_action.trigger()
        assert opened == [None, None]
        assert panel.input_path is None
        assert panel.job_id is None
        # Preparing an obtained file does not bypass the review gate for the
        # current job's result button or invoke an association/Popen shortcut.
        published_dxf = tmp_path / "published.dxf"
        panel.state = {"status": next(iter(PUBLISHED_STATUSES)), "result_dxf": str(published_dxf)}
        panel._result_domain = True
        monkeypatch.setattr(panel, "_review_is_current", lambda: False)
        panel.open_in_cad()
        assert opened == [None, None]
        monkeypatch.setattr(panel, "_review_is_current", lambda: True)
        panel.open_in_cad()
        assert opened[-1] == published_dxf
        panel._result_domain = False
        panel.open_in_cad()
        assert opened == [None, None, published_dxf]
    finally:
        panel.state = None
        window.close()
        qt_app.processEvents()
