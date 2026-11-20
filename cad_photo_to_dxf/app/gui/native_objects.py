"""Native-object mode within the existing desktop window and worker lifecycle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog

from app.core.image_loader import load_image
from app.core.native_objects_entry import validate_native_request
from app.core.processing import ProductionProcessingService, file_content_sha256


def native_objects_selected(self) -> bool:
    combo = getattr(self, "processing_mode_combo", None)
    return combo is not None and combo.currentData() == "native-objects"


def native_objects_mode_changed(self, *_args) -> None:
    selected = native_objects_selected(self)
    self.native_region_group.setVisible(selected)
    self.process_current_button.setText(
        "生成并保存原生 CAD" if selected else "处理当前页"
    )
    self.export_current_button.setText(
        "打开原生 CAD 输出目录" if selected else "导出当前页 CAD"
    )
    previous = getattr(self, "_native_legacy_enabled_states", {})
    for name in (
        "batch_pdf_button",
        "export_processed_pages_button",
        "include_underlay_checkbox",
        "dwg_version_combo",
        "drawing_scale_spin",
        "ocr_before_trace_checkbox",
        "page_combo",
        "previous_page_button",
        "next_page_button",
    ):
        widget = getattr(self, name, None)
        if widget is not None:
            if selected:
                previous[name] = widget.isEnabled()
                widget.setEnabled(False)
            else:
                widget.setEnabled(previous.get(name, True))
    self._native_legacy_enabled_states = previous
    if selected:
        self.statusBar().showMessage(
            "原生对象模式：明确页/帧、DPI、方向和原始 ROI；预览不供识别"
        )
    elif getattr(self, "_native_preview_only", False):
        # A downsampled native import preview must not become a legacy input.
        self.original_image = None
        self.corrected_image = None
        self.original_canvas.set_image(None)
        self._native_preview_only = False
        self._native_preview_binding = None
        self.statusBar().showMessage("已离开原生预览；兼容模式请重新导入原始来源")


def _selection(self):
    return {
        "page_number": self.native_page_spin.value() or None,
        "frame_number": self.native_frame_spin.value() or None,
        "orientation": int(self.native_orientation_combo.currentData()),
        "dpi": float(self.native_dpi_spin.value()),
    }


def import_native_source(self) -> None:
    """Existing Import action's selectable native route, not a second app."""
    from app.native_objects.source_import import inspect_container

    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择原生任务扫描来源",
        str(Path.home()),
        "Scanned drawings (*.png *.jpg *.jpeg *.tif *.tiff *.pdf)",
    )
    if not filename:
        return
    source = Path(filename).resolve()
    try:
        info = inspect_container(source)
        self.native_page_spin.setValue(0)
        self.native_frame_spin.setValue(0)
        self.native_orientation_combo.setCurrentIndex(0)
        self.native_job_id_edit.clear()
        count = info["page_count"] if info["format"] == "PDF" else info["frame_count"]
        selected = 1
        if count > 1:
            selected, okay = QInputDialog.getInt(
                self,
                "明确选择来源",
                f"来源含 {count} 页/帧，选择编号（从 1 起）：",
                1,
                1,
                count,
            )
            if not okay:
                return
        widget = (
            self.native_page_spin if info["format"] == "PDF" else self.native_frame_spin
        )
        widget.setValue(selected)
        self.current_path = source
        if not reload_native_source_preview(self):
            return
        size = self._native_preview_binding["source_size_px"]
        for spin, value in zip(self.native_roi_spins, (0, 0, *size)):
            spin.setValue(value)
        self.statusBar().showMessage(
            f"已导入所选来源：{source.name}；可修改原始 ROI 后生成"
        )
    except (ValueError, OSError) as exc:
        QMessageBox.critical(self, "原生来源导入失败", str(exc))


def reload_native_source_preview(self) -> bool:
    if self._is_processing():
        QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
        return False
    if self.current_path is None:
        QMessageBox.warning(self, "缺少来源", "请先导入图片或扫描 PDF。")
        return False
    from app.native_objects.source_import import read_preview

    selection = _selection(self)
    if not selection["dpi"].is_integer():
        QMessageBox.warning(
            self, "DPI 无效", "识别 DPI 必须为整数，不从预览分辨率推断。"
        )
        return False
    try:
        preview, info = read_preview(self.current_path, **selection)
    except (ValueError, OSError) as exc:
        QMessageBox.critical(self, "来源选页/帧失败", str(exc))
        return False
    from app.gui.review_project_actions import detach_review_project

    detach_review_project(self)
    self._native_pdf_mode = False
    self._pdf_page_count = 1
    self._current_pdf_page = None
    self._current_pdf_page_index = 0
    self._pdf_page_states = {}
    self._pdf_page_sizes_mm = {}
    self._set_pdf_controls_enabled(False)
    self._set_single_image_state(preview, corrected=False)
    self._native_preview_only = True
    self._native_preview_binding = {
        "input_path": str(Path(self.current_path).resolve()),
        **selection,
        "source_size_px": info["source_size_px"],
        "source_sha256": info["source_sha256"],
    }
    self._native_objects_result = None
    self.page_summary_label.setText(
        f"原生页/帧：{info['page_number_1based'] or info['frame_number_1based']}；原始 {info['source_size_px']} px；"
        f"预览 {info['preview_size_px']} px（不供识别）"
    )
    self.info_label.setText(
        "ROI 请输入旋转前原始选页/帧坐标；生成时重新读取原文件，保存全部变换。"
    )
    return True


def invalidate_native_objects_result(self, *_args) -> None:
    self._native_objects_result = None
    if native_objects_selected(self):
        self.detected_canvas.set_image(None)


def native_objects_processing_state(self, running: bool) -> None:
    """Do not let a running worker publish under a different selected mode/ROI."""
    for name in ("processing_mode_combo", "native_region_group"):
        widget = getattr(self, name, None)
        if widget is not None:
            widget.setEnabled(not running)


def start_native_objects(self) -> None:
    panel = getattr(self, "native_task_panel", None)
    if panel is not None:
        # The old compatibility-page button navigates to the same managed
        # native task UI. It must not retain an unkillable QThread OCR route.
        self.workspace_tabs.setCurrentWidget(panel)
        if (
            self.current_path is not None
            and not panel.running
            and not panel.preview_running
        ):
            panel.load_source(str(self.current_path))
        panel.status_label.setText(
            "请在原生任务页确认页码和区域后开始；转换由可取消、可恢复的独立工作进程执行。"
        )
        return
    if self._is_processing():
        QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
        return
    if self.current_path is None or self.original_image is None:
        QMessageBox.warning(
            self, "缺少原扫描", "请先导入并选择原始扫描页/帧，再填写原始 ROI。"
        )
        return
    from app.gui.review_project_actions import can_leave_review_project

    if not can_leave_review_project(self):
        return
    source = Path(self.current_path).resolve()
    roi = tuple(spin.value() for spin in self.native_roi_spins)
    selection = _selection(self)
    dpi = selection["dpi"]
    binding = getattr(self, "_native_preview_binding", None)
    if (
        binding is None
        or binding.get("input_path") != str(source)
        or any(binding.get(k) != v for k, v in selection.items())
        or binding.get("source_sha256") != file_content_sha256(source)
    ):
        if not reload_native_source_preview(self):
            return
    # Validate original coordinates before asking for an output filename. The
    # corrected/downsampled preview is deliberately not an input to this route.
    try:
        validate_native_request(
            source, source.with_name(source.stem + "-native.dxf"), roi, **selection
        )
    except (ValueError, OSError) as exc:
        QMessageBox.warning(self, "原生对象范围无效", str(exc))
        return
    filename, _ = QFileDialog.getSaveFileName(
        self,
        "生成并保存原生对象 DXF",
        str(source.with_name(source.stem + "-native.dxf")),
        "DXF (*.dxf)",
    )
    if not filename:
        return
    output = Path(filename)
    if not output.suffix:
        output = output.with_suffix(".dxf")
    evidence = output.with_name(output.stem + ".evidence")
    requested_job_id = self.native_job_id_edit.text().strip() or None
    self._native_objects_result = None
    self._clear_trace_state()
    self._invalidate_line_results()

    def operation(token, progress):
        return ProductionProcessingService.process_native_objects(
            source,
            output,
            roi,
            **selection,
            job_id=requested_job_id,
            progress_callback=progress,
            evidence_dir=evidence,
            cancellation_token=token,
            entrypoint="GUI.MainWindow.detect_and_clean(native-objects)",
        )

    def completed(value):
        result = dict(value)
        result["GUI_request_binding"] = {
            "input_path": str(source),
            "roi": list(roi),
            **selection,
            "requested_job_id": requested_job_id,
            "source_sha256": result["source_sha256"],
        }
        self._native_objects_result = result
        self.detected_canvas.set_image(load_image(result["preview_path"]))
        self.tabs.setCurrentWidget(self.detected_canvas)
        self.info_label.setText(
            f"原生选区 {roi}；{dpi:g} DPI，{25.4 / dpi:.6f} 纸面 mm/px；工程比例未标定"
        )
        self.statusBar().showMessage(
            f"已保存原生候选：{result['dxf_path']}；待修内容与验收状态见报告"
        )
        QMessageBox.information(
            self,
            "原生 CAD 已保存",
            f"{result['dxf_path']}\n对象记录：{len(result['objects'])}\n"
            f"待修与来源报告：{result['report_path']}\n\n目标 CAD 显示、编辑和工程师验收状态另行记录。",
        )

    self._start_processing(operation, completed, "正在生成原生对象…")


def open_native_objects_output(self) -> None:
    if self._is_processing():
        QMessageBox.information(self, "正在处理", "请等待当前任务完成或取消。")
        return
    result = getattr(self, "_native_objects_result", None)
    if not result:
        QMessageBox.information(self, "尚未生成", "请先点击“生成并保存原生 CAD”。")
        return
    binding = result["GUI_request_binding"]
    current = (
        Path(self.current_path).resolve() if self.current_path is not None else None
    )
    if (
        current is None
        or str(current) != binding["input_path"]
        or not current.is_file()
        or file_content_sha256(current) != binding["source_sha256"]
        or [spin.value() for spin in self.native_roi_spins] != binding["roi"]
        or any(binding.get(k) != v for k, v in _selection(self).items())
        or (self.native_job_id_edit.text().strip() or None)
        != binding["requested_job_id"]
    ):
        self._native_objects_result = None
        QMessageBox.warning(
            self, "来源或范围已变化", "当前设置与保存结果不同，请重新生成到新路径。"
        )
        return
    output = Path(result["dxf_path"])
    if not output.is_file():
        QMessageBox.warning(self, "输出文件不存在", str(output))
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent)))
