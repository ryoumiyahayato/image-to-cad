"""Native desktop workflow backed by persisted, separate worker processes.

The panel consumes actual saved source and MuPDF rasters and actual issue
groups. It neither recognizes drawings nor turns manual review into a model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QUrl, QRectF, QSettings
from PySide6.QtGui import QColor, QDesktopServices, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QProgressBar,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QGroupBox,
    QTabWidget,
    QToolButton,
)

from app.gui.image_canvas import ImageCanvas
from app.gui.native_task_viewmodel import (
    ACTIVE_STATUSES,
    RECOVERABLE_STATUSES,
    PUBLISHED_STATUSES,
    STATUS_LABELS,
    default_jobs_root,
    source_roi_to_preview,
    preview_rect_to_source,
    issue_local_box,
    issue_label,
    issue_user_details,
    saved_review_notice,
    load_quality,
    request_from_controls,
)


class NativePreviewThread(QThread):
    ready = Signal(object, object)
    failed = Signal(str)

    def __init__(self, path, selection, parent=None):
        super().__init__(parent)
        self.path, self.selection = path, dict(selection)

    def run(self):
        try:
            from app.native_objects.source_import import read_preview

            image, info = read_preview(self.path, **self.selection)
            self.ready.emit(image, info)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class NativeTaskCanvas(ImageCanvas):
    rectangle_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.roi_mode = False
        self._roi_start = None

    def enable_roi(self, enabled):
        self.roi_mode = bool(enabled)
        self.set_selection_enabled(bool(enabled))

    def show_box(self, box, *, focus=False, color="#e88700"):
        self.clear_overlays()
        x0, y0, x1, y1 = map(float, box)
        rectangle = QRectF(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))
        pen = QPen(QColor(color), 2)
        pen.setCosmetic(True)
        item = self._scene.addRect(rectangle, pen)
        item.setZValue(20)
        self._overlay_items.append(item)
        if focus:
            visible = rectangle.adjusted(-24, -24, 24, 24).intersected(
                self._scene.sceneRect()
            )
            if not visible.isEmpty():
                self.fitInView(visible, Qt.AspectRatioMode.KeepAspectRatio)
                self._manual_zoom = True
                self._refresh_lod_pixmap()

    def mousePressEvent(self, event):
        if self.roi_mode and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self._scene.sceneRect().contains(point):
                self._roi_start = point
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.roi_mode and self._roi_start is not None:
            p = self.mapToScene(event.position().toPoint())
            box = self._scene.sceneRect()
            x, y = (
                min(max(p.x(), box.left()), box.right()),
                min(max(p.y(), box.top()), box.bottom()),
            )
            self.show_box(
                [
                    min(self._roi_start.x(), x),
                    min(self._roi_start.y(), y),
                    max(self._roi_start.x(), x),
                    max(self._roi_start.y(), y),
                ]
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self.roi_mode
            and self._roi_start is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            p = self.mapToScene(event.position().toPoint())
            box = self._scene.sceneRect()
            x, y = (
                min(max(p.x(), box.left()), box.right()),
                min(max(p.y(), box.top()), box.bottom()),
            )
            values = [
                min(self._roi_start.x(), x),
                min(self._roi_start.y(), y),
                max(self._roi_start.x(), x),
                max(self._roi_start.y(), y),
            ]
            self._roi_start = None
            if values[2] > values[0] and values[3] > values[1]:
                self.rectangle_selected.emit(values)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class NativeTaskPanel(QWidget):
    running_changed = Signal(bool)
    ready_to_close = Signal()

    def __init__(self, parent=None, *, jobs_root=None, manager=None):
        super().__init__(parent)
        from app.core.native_job_manager import NativeJobManager

        self.jobs_root = Path(jobs_root or default_jobs_root()).resolve()
        self.manager = manager or NativeJobManager(self.jobs_root)
        self.settings = QSettings("ImageToCAD", "NativeDesktopV4")
        self.job_id = None
        self.state = None
        self.input_path = None
        self.preview_info = None
        self.preview_rgb = None
        self.source_rgb = None
        self.result_rgb = None
        self.quality = None
        self.review_verification = None
        self._preview_thread = None
        self._result_domain = False
        self._loading_controls = False
        self._closing = False
        self._reported_terminal = None
        self._history_signature = None
        self._build()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start()
        self.refresh_history()
        self._event("desktop_opened", jobs_root=str(self.jobs_root))

    @property
    def running(self):
        return bool(self.state and self.state.get("status") in ACTIVE_STATUSES)

    @property
    def preview_running(self):
        # Count the queued/start/finished-signal interval as busy as well: a
        # page selection must not change between scheduling and read-back.
        return self._preview_thread is not None

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        title = QLabel("原生对象转换与来源核对 · native-objects")
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        outer.addWidget(title)
        self.capability = QLabel(
            "处理位置：此桌面环境。使用本地英语 OCR、来源规则及独立 DXF 渲染；图纸不上传外部服务。未部署通用视觉判断模型。"
        )
        self.capability.setWordWrap(True)
        outer.addWidget(self.capability)
        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("选择 PNG、JPEG、TIFF 或扫描 PDF")
        self.open_button = QPushButton("选择文件…")
        self.open_button.clicked.connect(self.open_source)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(self.open_button)
        outer.addLayout(file_row)

        self.input_group = QGroupBox("本次输入")
        form = QGridLayout(self.input_group)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(0, 100000)
        self.page_spin.setSpecialValueText("不适用")
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(0, 100000)
        self.frame_spin.setSpecialValueText("不适用")
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(1, 10000)
        self.dpi_spin.setValue(200)
        self.orientation_combo = QComboBox()
        for degrees in (0, 90, 180, 270):
            self.orientation_combo.addItem(f"{degrees}°", degrees)
        self.language_combo = QComboBox()
        self.language_combo.addItem("英语 · eng（已部署）", "eng")
        # Four input pairs fit the real 1364 px desktop without a 10-column
        # row establishing an unnecessarily large minimum width.
        for col, (label, widget) in enumerate(
            (
                ("PDF 页", self.page_spin),
                ("图像帧", self.frame_spin),
                ("识别 DPI", self.dpi_spin),
                ("顺时针方向", self.orientation_combo),
            )
        ):
            form.addWidget(QLabel(label), 0, col * 2)
            form.addWidget(widget, 0, col * 2 + 1)
        form.addWidget(QLabel("文字语言"), 1, 0)
        form.addWidget(self.language_combo, 1, 1, 1, 3)
        self.roi_spins = []
        for col, name in enumerate(("x0", "y0", "x1", "y1")):
            spin = QSpinBox()
            spin.setRange(0, 1000000)
            spin.valueChanged.connect(self._roi_changed)
            self.roi_spins.append(spin)
            form.addWidget(QLabel(name), 2, col * 2)
            form.addWidget(spin, 2, col * 2 + 1)
        self.reload_button = QPushButton("载入页 / 重新选区")
        self.reload_button.clicked.connect(self.reload_preview)
        form.addWidget(self.reload_button, 1, 4, 1, 4)
        self.scale_label = QLabel(
            "比例：未标定工程尺寸；输出使用纸面 mm。ROI 为旋转前所选页的原始像素范围。"
        )
        self.scale_label.setWordWrap(True)
        form.addWidget(self.scale_label, 3, 0, 1, 8)
        outer.addWidget(self.input_group)
        from app.core.native_job_manager import DEFAULT_LIMITS

        self.budget_group = QGroupBox("任务预算（恢复仍计入同一任务；OCR 单线程）")
        budget_form = QGridLayout(self.budget_group)
        self.budget_spins = {}
        for col, (key, label) in enumerate(
            (
                ("CPU_seconds", "CPU 秒"),
                ("wall_seconds", "最长秒"),
                ("RSS_MiB", "内存 MiB"),
                ("temporary_MiB", "任务文件 MiB"),
            )
        ):
            spin = QSpinBox(self.budget_group)
            spin.setRange(1, 1048576)
            spin.setValue(int(DEFAULT_LIMITS[key]))
            self.budget_spins[key] = spin
            budget_form.addWidget(QLabel(label), 0, col * 2)
            budget_form.addWidget(spin, 0, col * 2 + 1)
        outer.addWidget(self.budget_group)
        for widget in (self.page_spin, self.frame_spin, self.dpi_spin):
            widget.valueChanged.connect(self._selection_changed)
        self.orientation_combo.currentIndexChanged.connect(self._selection_changed)

        self.splitter = QSplitter()
        view = QWidget()
        view_layout = QVBoxLayout(view)
        view_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.view_combo = QComboBox()
        self.view_combo.addItem("原图", "source")
        self.view_combo.addItem("保存的 DXF 渲染", "result")
        self.view_combo.addItem("叠加对照", "overlay")
        self.view_combo.currentIndexChanged.connect(self.update_view)
        toolbar.addWidget(self.view_combo)
        self.roi_checkbox = QCheckBox("拖拽框选区域")
        self.roi_checkbox.toggled.connect(self._roi_mode)
        toolbar.addWidget(self.roi_checkbox)
        self.fit_button = QPushButton("显示全范围")
        self.fit_button.clicked.connect(lambda: self.canvas.fit_image())
        toolbar.addWidget(self.fit_button)
        self.actual_size_button = QPushButton("1:1")
        self.actual_size_button.clicked.connect(lambda: self.canvas.actual_size())
        toolbar.addWidget(self.actual_size_button)
        toolbar.addStretch(1)
        view_layout.addLayout(toolbar)
        self.canvas = NativeTaskCanvas()
        self.canvas.rectangle_selected.connect(self._rectangle_selected)
        view_layout.addWidget(self.canvas, 1)
        self.view_note = QLabel("预览仅供选区和核对；正式识别重新读取原文件。")
        self.view_note.setWordWrap(True)
        view_layout.addWidget(self.view_note)
        self.splitter.addWidget(view)

        right = QTabWidget()
        issues_page = QWidget()
        issues_layout = QVBoxLayout(issues_page)
        self.issue_summary = QLabel("尚未生成本次输入的质量检查。")
        self.issue_summary.setWordWrap(True)
        issues_layout.addWidget(self.issue_summary)
        self.review_notice = QLabel("尚无保存结果的版本审核。")
        self.review_notice.setWordWrap(True)
        issues_layout.addWidget(self.review_notice)
        self.issue_list = QListWidget()
        self.issue_list.setUniformItemSizes(True)
        self.issue_list.currentItemChanged.connect(self.select_issue)
        issues_layout.addWidget(self.issue_list, 2)
        self.issue_details = QTextEdit()
        self.issue_details.setReadOnly(True)
        issues_layout.addWidget(self.issue_details, 1)
        self.technical_toggle = QToolButton()
        self.technical_toggle.setText("技术记录（可展开）")
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.technical_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.technical_toggle.toggled.connect(self._toggle_technical_details)
        issues_layout.addWidget(self.technical_toggle)
        self.technical_details = QTextEdit()
        self.technical_details.setReadOnly(True)
        self.technical_details.setVisible(False)
        issues_layout.addWidget(self.technical_details, 1)
        right.addTab(issues_page, "待修对象 / 来源组")
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        self.history_list = QListWidget()
        self.history_list.setUniformItemSizes(True)
        self.history_list.itemDoubleClicked.connect(self.open_history)
        history_layout.addWidget(self.history_list, 1)
        history_hint = QLabel(
            "双击任务查看。中断任务可恢复；已完成结果不会被新任务覆盖。"
        )
        history_hint.setWordWrap(True)
        history_layout.addWidget(history_hint)
        self.refresh_button = QPushButton("刷新历史任务")
        self.refresh_button.clicked.connect(self.refresh_history)
        history_layout.addWidget(self.refresh_button)
        right.addTab(history_page, "历史任务")
        self.side_tabs = right
        self.splitter.addWidget(right)
        self.splitter.setSizes([820, 340])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        outer.addWidget(self.splitter, 1)

        self.status_label = QLabel(
            "选择来源和区域后开始。任何未确认内容均在实际问题清单中保留。"
        )
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        outer.addWidget(self.progress)
        buttons = QGridLayout()
        self.start_button = QPushButton("开始新任务")
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel)
        self.resume_button = QPushButton("恢复此任务")
        self.resume_button.clicked.connect(self.resume)
        self.export_button = QPushButton("导出 DXF…")
        self.export_button.clicked.connect(self.export_dxf)
        self.folder_button = QPushButton("打开任务目录")
        self.folder_button.clicked.connect(self.open_folder)
        self.cad_button = QPushButton("在 CAD 中打开")
        self.cad_button.clicked.connect(self.open_in_cad)
        self.cad_settings_button = QPushButton("选择 CAD…")
        self.cad_settings_button.clicked.connect(self.choose_cad)
        for index, widget in enumerate(
            (
                self.start_button,
                self.cancel_button,
                self.resume_button,
                self.export_button,
                self.folder_button,
                self.cad_button,
                self.cad_settings_button,
            )
        ):
            buttons.addWidget(widget, index // 4, index % 4)
        for column in range(4):
            buttons.setColumnStretch(column, 1)
        outer.addLayout(buttons)
        self._enable_controls()

    def _event(self, action, **details):
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        row = {
            "time_UTC": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "job_id": self.job_id,
            "details": details,
        }
        with (self.jobs_root / "desktop_events.jsonl").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    row, ensure_ascii=False, allow_nan=False, default=self._event_value
                )
                + "\n"
            )

    @staticmethod
    def _event_value(value):
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Unsupported desktop event value: {type(value).__name__}")

    def _error(self, title, exc):
        text = str(exc)
        self.status_label.setText(f"{title}：{text}")
        self._event("ui_error", title=title, message=text)
        QMessageBox.critical(self, title, text)

    def _selection(self):
        return {
            "page_number": self.page_spin.value() or None,
            "frame_number": self.frame_spin.value() or None,
            "dpi": self.dpi_spin.value(),
            "orientation": self.orientation_combo.currentData(),
        }

    def open_source(self):
        if self.running or self.preview_running:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择原始工程图",
            str(Path.home()),
            "扫描图纸 (*.png *.jpg *.jpeg *.tif *.tiff *.pdf)",
        )
        if not filename:
            return
        self.load_source(filename)

    def load_source(self, filename):
        """The file-picker action calls this; no recognition or fixture lookup."""
        if self.running or self.preview_running:
            raise RuntimeError(
                "Wait for the active task/preview before changing source"
            )
        try:
            from app.native_objects.source_import import inspect_container

            info = inspect_container(filename)
            self.input_path = str(Path(filename).resolve())
            self.path_edit.setText(self.input_path)
            self._loading_controls = True
            self.page_spin.setValue(1 if info["format"] == "PDF" else 0)
            self.frame_spin.setValue(0 if info["format"] == "PDF" else 1)
            self.page_spin.setMaximum(max(1, info["page_count"] or 1))
            self.frame_spin.setMaximum(max(1, info["frame_count"] or 1))
            self.page_spin.setEnabled(info["format"] == "PDF")
            self.frame_spin.setEnabled(info["format"] != "PDF")
            self.orientation_combo.setCurrentIndex(0)
            self._loading_controls = False
            self.job_id = None
            self.state = None
            self._reported_terminal = None
            self.preview_info = None
            self.preview_rgb = None
            self._clear_result()
            self._event("source_selected", input_path=self.input_path, container=info)
            self.reload_preview(reset_roi=True)
        except Exception as exc:
            self._loading_controls = False
            self._error("无法导入来源", exc)

    def reload_preview(self, *_args, reset_roi=False):
        if self.running or self.preview_running or not self.input_path:
            return
        self._detach_displayed_task()
        self._clear_result()
        self.roi_checkbox.setChecked(False)
        self._preview_reset_roi = reset_roi
        thread = NativePreviewThread(self.input_path, self._selection(), self)
        thread.ready.connect(self._preview_ready)
        thread.failed.connect(lambda message: self._error("页 / 帧预览失败", message))
        thread.finished.connect(self._preview_finished)
        self._preview_thread = thread
        self.status_label.setText("正在读取所选页 / 帧预览；没有开始识别。")
        self._enable_controls()
        thread.start()

    def _preview_ready(self, image, info):
        self.preview_rgb = image
        self.preview_info = {
            **info,
            "selection": self._selection(),
            "input_path": self.input_path,
        }
        self._loading_controls = True
        width, height = info["source_size_px"]
        for spin, maximum in zip(self.roi_spins, (width, height, width, height)):
            spin.setMaximum(maximum)
        if self._preview_reset_roi or not any(spin.value() for spin in self.roi_spins):
            for spin, value in zip(self.roi_spins, (0, 0, *info["source_size_px"])):
                spin.setValue(value)
        self._loading_controls = False
        self._result_domain = False
        self.view_combo.setCurrentIndex(0)
        self.update_view()
        self._draw_roi()
        self.scale_label.setText(
            f"工程比例未标定；{self.dpi_spin.value()} DPI = {25.4 / self.dpi_spin.value():.6f} 纸面 mm/像素。ROI 为旋转前原图坐标。"
        )
        self.status_label.setText(
            f"已读取 {info['source_size_px']} 像素；预览 {info['preview_size_px']}。请选择区域，然后开始新任务。"
        )
        self._event(
            "preview_loaded",
            source_sha256=info["source_sha256"],
            source_size=info["source_size_px"],
            preview_size=info["preview_size_px"],
            selection=self._selection(),
        )

    def _preview_finished(self):
        thread, self._preview_thread = self._preview_thread, None
        if thread is not None:
            thread.deleteLater()
        self._enable_controls()
        if self._closing and not self.running:
            self.ready_to_close.emit()

    def _selection_changed(self, *_args):
        if self._loading_controls:
            return
        self.preview_info = None
        self.preview_rgb = None
        self._detach_displayed_task()
        self._clear_result()
        self.roi_checkbox.setChecked(False)
        self.canvas.set_image(None)
        self.status_label.setText(
            "页面、帧、DPI或方向已变化，请重新载入预览；旧任务仍在历史中。"
        )
        self._enable_controls()

    def _roi_changed(self, *_args):
        if self._loading_controls:
            return
        if self.state:
            self._detach_displayed_task()
            self._clear_result()
            self.update_view()
        self._draw_roi()
        self._enable_controls()

    def _roi_mode(self, checked):
        if self._result_domain:
            self.roi_checkbox.setChecked(False)
            return
        self.canvas.enable_roi(checked)

    def _rectangle_selected(self, rect):
        if not self.preview_info or self._result_domain:
            return
        roi = preview_rect_to_source(
            rect,
            self.preview_info["source_size_px"],
            self.preview_info["preview_size_px"],
            self.orientation_combo.currentData(),
        )
        self._loading_controls = True
        for spin, value in zip(self.roi_spins, roi):
            spin.setValue(value)
        self._loading_controls = False
        self._detach_displayed_task()
        self.roi_checkbox.setChecked(False)
        self._draw_roi()
        self._event("ROI_selected_in_source_view", roi=roi)

    def _draw_roi(self):
        if self.preview_info and not self._result_domain:
            box = source_roi_to_preview(
                [s.value() for s in self.roi_spins],
                self.preview_info["source_size_px"],
                self.preview_info["preview_size_px"],
                self.orientation_combo.currentData(),
            )
            self.canvas.show_box(box)

    def _clear_result(self):
        self.source_rgb = self.result_rgb = self.quality = None
        self.review_verification = None
        self._result_domain = False
        self.issue_list.clear()
        self.issue_details.clear()
        self.technical_details.clear()
        self.technical_toggle.setChecked(False)
        self.review_notice.setText("尚无保存结果的版本审核。")
        self.review_notice.setStyleSheet("")
        self.issue_summary.setText("本次设置尚无实际保存结果的质量检查。")

    def _detach_displayed_task(self):
        # A changed input becomes a new draft. The old persisted task remains
        # in history, but cannot masquerade as the current settings' result.
        self.job_id = None
        self.state = None
        self._reported_terminal = None
        self.progress.setValue(0)
        self.progress.setFormat("%p%")

    def start(self):
        if self.running or self.preview_running:
            return
        try:
            if (
                not self.preview_info
                or self.preview_info["selection"] != self._selection()
            ):
                raise ValueError("请先载入当前选择的页 / 帧预览")
            from app.native_objects.source_import import file_sha

            if file_sha(self.input_path) != self.preview_info["source_sha256"]:
                raise ValueError("原文件在预览后发生变化，请重新载入本次输入")
            request = request_from_controls(
                self.input_path,
                [s.value() for s in self.roi_spins],
                self.dpi_spin.value(),
                self.page_spin.value(),
                self.frame_spin.value(),
                self.orientation_combo.currentData(),
                self.language_combo.currentData(),
            )
            request["limits"] = {
                key: float(spin.value()) for key, spin in self.budget_spins.items()
            }
            state = self.manager.create(request=request)
            self.job_id = state["job_id"]
            started_state = self.manager.start(self.job_id)
            self._reported_terminal = None
            self._clear_result()
            self.roi_checkbox.setChecked(False)
            self._event("start_clicked", request=request)
            self._update_state(started_state)
            self.poll_timer.start()
            self.refresh_history()
        except Exception as exc:
            self._error("任务未能开始", exc)

    def cancel(self):
        if self.job_id and self.running:
            state = self.manager.cancel(
                self.job_id, reason="application_exit" if self._closing else "user"
            )
            self._event(
                "cancel_requested",
                reason="application_exit" if self._closing else "user",
            )
            self._update_state(state)

    def resume(self):
        if not self.job_id or self.running or self.preview_running:
            return
        try:
            status = self.state.get("status") if self.state else None
            if status == "RESOURCE_STOP":
                raise ValueError(
                    "本任务已因资源预算停止；检查点保留，不自动扩大预算或无条件重跑。"
                )
            if status == "QUEUED":
                if int(self.state.get("attempt", 0)) != 0:
                    raise ValueError(
                        "待启动任务的执行次数异常；保留状态并停止，不能猜测恢复。"
                    )
                state = self.manager.start(self.job_id)
                action = "queued_task_start_clicked"
            else:
                state = self.manager.resume(self.job_id)
                action = "resume_clicked"
            self._reported_terminal = None
            self._clear_result()
            self._event(action)
            self._update_state(state)
            self.poll_timer.start()
        except Exception as exc:
            self._error("无法恢复任务", exc)

    def poll(self):
        if not self.job_id:
            return
        try:
            state = self.manager.poll(self.job_id)
            self._update_state(state)
        except Exception as exc:
            # Stop a repeating UI error storm; the persisted worker state is
            # left intact for explicit recovery, never changed to success.
            self.poll_timer.stop()
            self._error("任务状态读取失败", exc)

    def _update_state(self, state):
        if not isinstance(state, dict):
            raise TypeError("Task manager must return a persisted state dictionary")
        was_running = self.running
        self.state = state
        for key, value in state.get("limits", {}).items():
            if key in self.budget_spins:
                self.budget_spins[key].setValue(int(value))
        status = state["status"]
        stage = state.get("stage") or status
        fraction = min(1.0, max(0.0, float(state.get("progress") or 0.0)))
        self.progress.setValue(round(fraction * 1000))
        self.progress.setFormat(f"{fraction * 100:.1f}% · {stage}")
        status_text = f"{STATUS_LABELS.get(status, status)} · {stage} · 任务 {state['job_id']} · 第 {state.get('attempt', 1)} 次执行"
        if was_running != self.running:
            self.running_changed.emit(self.running)
        terminal = status not in ACTIVE_STATUSES and status != "QUEUED"
        key = (state["job_id"], state.get("attempt"), status)
        if terminal and key != self._reported_terminal:
            self._reported_terminal = key
            self._event("terminal_state_observed", state=state)
            if status in PUBLISHED_STATUSES:
                self._load_result(state)
            elif state.get("error"):
                self.issue_details.setPlainText(
                    "任务未能完成，已保存的检查点和失败证据保留。请展开“技术记录”查看具体错误。"
                )
                self.technical_details.setPlainText(
                    json.dumps(state["error"], ensure_ascii=False, indent=2)
                )
            self.refresh_history()
        if (
            status in PUBLISHED_STATUSES
            and self.review_verification is not None
            and not self._review_is_current()
        ):
            status_text += " · 审核已失效，待重新审核；禁止导出"
        self.status_label.setText(status_text)
        self._enable_controls()
        if self._closing and terminal and not self.preview_running:
            self.ready_to_close.emit()

    def _load_result(self, state):
        required = ("result_dxf", "preview_path", "source_roi_path", "quality_path")
        if any(not state.get(k) or not Path(state[k]).is_file() for k in required):
            raise ValueError(
                "Published task is missing a saved DXF, raster, source or actual quality file"
            )
        self.quality = load_quality(state["quality_path"])
        self._verify_result_review(state)
        self.source_rgb = np.asarray(
            Image.open(state["source_roi_path"]).convert("RGB")
        )
        self.result_rgb = np.asarray(Image.open(state["preview_path"]).convert("RGB"))
        if self.source_rgb.shape != self.result_rgb.shape:
            raise ValueError(
                "Source and saved DXF rasters differ in size; overlay is disabled rather than rescaled"
            )
        self._result_domain = True
        self.roi_checkbox.setChecked(False)
        self.issue_list.clear()
        for issue in self.quality["issues"]:
            item = QListWidgetItem(issue_label(issue))
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue_label(issue))
            self.issue_list.addItem(item)
        self.issue_summary.setText(
            f"实际保存结果：{len(self.quality['issues'])} 个待修 / 待核对项。点击按来源位置定位；网格不作为对象。"
        )
        self.issue_details.setPlainText(
            "请选择一项查看中文原因和位置；原始编号与审核字段可在“技术记录”中展开。"
        )
        self.view_combo.setCurrentIndex(2)
        self.update_view()
        self.side_tabs.setCurrentIndex(0)

    def _review_is_current(self):
        return bool(
            self.review_verification and self.review_verification.get("valid") is True
        )

    def _verify_result_review(self, state):
        """Read the current binding, without recognition, rendering or repair.

        A persisted COMPLETED state describes the old execution. It must not
        imply that an old result remains reviewed under the current code.
        Stale data remains viewable but cannot acquire an export permission.
        """
        from app.native_objects.review_binding import verify_saved_review

        try:
            dxf = Path(state["result_dxf"])
            objects = json.loads(
                dxf.with_suffix(".objects.json").read_text(encoding="utf-8")
            )["objects"]
            imported = json.loads(
                (Path(state["evidence_dir"]) / "import_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            verification = verify_saved_review(
                state["quality_path"],
                dxf,
                objects,
                imported,
                source_path=state["input_path"],
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            verification = {
                "valid": False,
                "status": "STALE_REVIEW_PENDING",
                "mismatches": [
                    {
                        "field": "saved_review_inputs",
                        "reason": type(exc).__name__,
                        "detail": str(exc),
                    }
                ],
                "new_render_or_OCR_calls": 0,
            }
        self.review_verification = verification
        self.review_notice.setText(saved_review_notice(verification))
        self.review_notice.setStyleSheet(
            "color: #8a3c0d; font-weight: 600;" if not self._review_is_current() else ""
        )
        self.technical_details.setPlainText(
            json.dumps(
                {"saved_review_verification": verification},
                ensure_ascii=False,
                indent=2,
            )
        )
        self._event(
            "saved_result_review_binding_checked",
            valid=self._review_is_current(),
            status=verification.get("status"),
            mismatches=verification.get("mismatches", []),
        )
        self._enable_controls()
        return self._review_is_current()

    def _toggle_technical_details(self, expanded):
        self.technical_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.technical_details.setVisible(expanded)

    def update_view(self, *_args):
        mode = self.view_combo.currentData()
        if (
            self._result_domain
            and self.source_rgb is not None
            and self.result_rgb is not None
        ):
            if mode == "source":
                image = self.source_rgb
                note = "本任务所选区域原图；没有因候选缺失而删除原始来源。"
            elif mode == "result":
                image = self.result_rgb
                note = "实际保存 DXF 的官方 ezdxf→MuPDF 渲染；不是来源底图或求解器自绘结果。"
            else:
                s = 1.0 - self.source_rgb.mean(axis=2) / 255.0
                c = 1.0 - self.result_rgb.mean(axis=2) / 255.0
                image = np.stack(
                    (
                        255 * (1 - 0.55 * s),
                        255 * (1 - 0.8 * np.maximum(s, c)),
                        255 * (1 - 0.65 * c),
                    ),
                    axis=2,
                ).astype(np.uint8)
                note = "叠加：蓝色偏来源，红色偏保存 DXF，重合为深色；显示着色不改变任何审核阈值。"
            if not self._review_is_current():
                note += " 这是历史对照，当前审核已失效，不能据此导出。"
            self.canvas.set_image(np.ascontiguousarray(image[:, :, ::-1]))
            self.view_note.setText(note)
        elif self.preview_rgb is not None:
            self.canvas.set_image(np.ascontiguousarray(self.preview_rgb[:, :, ::-1]))
            self.view_note.setText("全页预览只供选区；正式识别重新读取原文件。")
            self._draw_roi()
        else:
            self.canvas.set_image(None)
        current = self.issue_list.currentItem()
        if self._result_domain and self.quality and current is not None:
            box = issue_local_box(
                current.data(Qt.ItemDataRole.UserRole), self.quality["roi_xyxy_px"]
            )
            if box is not None:
                self.canvas.show_box(box, focus=True)
        self._event(
            "view_changed",
            view=mode,
            domain="working_ROI" if self._result_domain else "source_preview",
        )

    def select_issue(self, current, _previous=None):
        if current is None or not self.quality:
            return
        issue = current.data(Qt.ItemDataRole.UserRole)
        self.issue_details.setPlainText(issue_user_details(issue))
        self.technical_details.setPlainText(
            json.dumps(
                {"issue": issue, "saved_review_verification": self.review_verification},
                ensure_ascii=False,
                indent=2,
            )
        )
        box = issue_local_box(issue, self.quality["roi_xyxy_px"])
        if box is None:
            self.view_note.setText("此问题暂无可靠来源坐标，已明确列出，未静默隐藏。")
        else:
            self.canvas.show_box(box, focus=True)
        self._event(
            "issue_selected",
            issue_id=issue["id"],
            bbox_xyxy_px=issue.get("bbox_xyxy_px"),
        )

    def refresh_history(self):
        try:
            states = self.manager.list_jobs()
            selected = self.job_id
            self.history_list.clear()
            for state in states:
                name = Path(
                    state.get("original_input_path") or state.get("input_path") or ""
                ).name
                label = STATUS_LABELS.get(state["status"], state["status"])
                if state["status"] in PUBLISHED_STATUSES:
                    label = "已保存，打开时核对审核版本"
                    if (
                        state["job_id"] == self.job_id
                        and self.review_verification is not None
                    ):
                        label = (
                            "已保存，含待修项"
                            if self._review_is_current()
                            else "审核已失效，待重新审核"
                        )
                item = QListWidgetItem(f"{label} · {name}\n{state['job_id']}")
                item.setData(Qt.ItemDataRole.UserRole, state["job_id"])
                self.history_list.addItem(item)
                if selected == state["job_id"]:
                    self.history_list.setCurrentItem(item)
        except Exception as exc:
            self._error("历史任务读取失败", exc)

    def open_history(self, item):
        if self.running or self.preview_running:
            return
        try:
            self.job_id = item.data(Qt.ItemDataRole.UserRole)
            state = self.manager.poll(self.job_id)
            self._clear_result()
            self.preview_rgb = None
            params = state.get("parameters", {})
            self._loading_controls = True
            self.input_path = state.get("original_input_path") or state["input_path"]
            self.path_edit.setText(self.input_path)
            self.page_spin.setMaximum(100000)
            self.frame_spin.setMaximum(100000)
            self.page_spin.setValue(params.get("page_number") or 0)
            self.frame_spin.setValue(params.get("frame_number") or 0)
            self.page_spin.setEnabled(params.get("page_number") is not None)
            self.frame_spin.setEnabled(params.get("page_number") is None)
            self.dpi_spin.setValue(params.get("dpi", 200))
            self.orientation_combo.setCurrentIndex(
                self.orientation_combo.findData(params.get("orientation", 0))
            )
            for spin in self.roi_spins:
                spin.setMaximum(1000000)
            for spin, value in zip(self.roi_spins, params.get("roi", [0, 0, 0, 0])):
                spin.setValue(value)
            self._loading_controls = False
            self.preview_info = None
            self._reported_terminal = None
            self._update_state(state)
            self.poll_timer.start()
            self._event("history_opened")
        except Exception as exc:
            self._loading_controls = False
            self._error("历史任务打开失败", exc)

    def export_dxf(self):
        if (
            not self._result_domain
            or not self.state
            or self.state.get("status") not in PUBLISHED_STATUSES
        ):
            QMessageBox.information(
                self,
                "没有可导出的结果",
                "只有读回审核后已发布的候选可以导出；失败或半成品不可导出。",
            )
            return
        if not self._verify_result_review(self.state):
            QMessageBox.information(
                self, "待重新审核", saved_review_notice(self.review_verification)
            )
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "导出已审核的 DXF 候选",
            str(Path.home() / (Path(self.input_path).stem + "-native.dxf")),
            "DXF (*.dxf)",
        )
        if not destination:
            return
        if not Path(destination).suffix:
            destination += ".dxf"
        try:
            receipt = self.manager.export(self.job_id, destination)
            self._event("DXF_exported", destination=destination, receipt=receipt)
            self.status_label.setText(f"已导出 {destination}；待修内容随审核记录保留。")
            QMessageBox.information(
                self,
                "DXF 已导出",
                f"{destination}\n\n这是含明确待修项的原生 CAD 候选，原图和已有成功结果保持不变。",
            )
        except Exception as exc:
            self._error("导出失败，旧文件保持不变", exc)

    def open_folder(self):
        if self.state:
            directory = self.jobs_root / self.state["job_id"]
            if self.state.get("result_dxf"):
                directory = Path(self.state["result_dxf"]).parent
        else:
            directory = self.jobs_root
        self._event("output_folder_opened", path=str(directory))
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self._error("无法打开目录", str(directory))

    def choose_cad(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择日常 CAD 程序", str(Path.home()), "应用程序 (*)"
        )
        if filename:
            self.settings.setValue("cad_executable", filename)
            self._event("CAD_program_selected", executable=filename)
            self.status_label.setText(
                f"关联 CAD：{Path(filename).name}。实际兼容性仍须在该版本验证。"
            )

    def open_in_cad(self):
        if (
            not self._result_domain
            or not self.state
            or self.state.get("status") not in PUBLISHED_STATUSES
            or not self._review_is_current()
        ):
            return
        path = Path(self.state["result_dxf"])
        executable = self.settings.value("cad_executable", "", str)
        try:
            if executable:
                subprocess.Popen([executable, str(path)], close_fds=True)
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise RuntimeError(
                    "系统未找到 DXF 关联程序，请用“选择 CAD…”指定已安装的程序"
                )
            self._event(
                "actual_saved_DXF_open_requested",
                dxf=str(path),
                executable=executable or "system_association",
            )
        except Exception as exc:
            self._error("无法打开 CAD", exc)

    def _enable_controls(self):
        busy = self.running or self.preview_running
        self.open_button.setEnabled(not busy)
        self.input_group.setEnabled(not busy)
        self.budget_group.setEnabled(not busy and self.job_id is None)
        self.start_button.setEnabled(not busy and self.preview_info is not None)
        self.cancel_button.setEnabled(
            self.running and self.state.get("status") != "CANCEL_REQUESTED"
        )
        self.resume_button.setEnabled(
            not busy
            and bool(self.state and self.state.get("status") in RECOVERABLE_STATUSES)
        )
        self.resume_button.setText(
            "启动待运行任务"
            if self.state and self.state.get("status") == "QUEUED"
            else "恢复此任务"
        )
        published = bool(
            self.state
            and self.state.get("status") in PUBLISHED_STATUSES
            and self._result_domain
            and self._review_is_current()
        )
        self.export_button.setEnabled(not busy and published)
        self.cad_button.setEnabled(not busy and published)
        self.folder_button.setEnabled(self.jobs_root.is_dir())
        self.history_list.setEnabled(not busy)
        self.roi_checkbox.setEnabled(
            not busy and self.preview_info is not None and not self._result_domain
        )
        if busy:
            self.canvas.enable_roi(False)

    def request_close(self):
        """Nonblocking close: request cancellation, let poll observe terminal."""
        if self.running or self.preview_running:
            self._closing = True
            if self.running:
                self.cancel()
            self.status_label.setText(
                "正在保存检查点并停止本任务；随后关闭，重开可从历史任务恢复。"
            )
            return False
        self._event("desktop_closed")
        return True
