from __future__ import annotations

from pathlib import Path
from time import perf_counter
import numpy as np
from PySide6.QtWidgets import QFileDialog, QMessageBox, QDialog

from app.core.cache import load_trace_cache
from app.core.review_project import ReviewProject, ReviewProjectError
from app.gui.review_project_dialog import SnapshotTextReviewDialog
from app.gui.review_async import (
    PreviewClient,
    ReviewJob,
    detached_review,
    release_project,
    timing,
)


def _refresh_review_project(window, *, preview=None, render=True):
    project = window._review_project
    window._final_structure = project.baseline
    window._preview_structure_id = project._manifest["structure_id"]
    window._ocr_texts = project.baseline.texts  # Original facts are never overwritten.
    window.tabs.setCurrentWidget(window.detected_canvas)
    window.setWindowModified(project.dirty)
    window.drawing_scale_spin.setEnabled(False)
    if "[*]" not in window.windowTitle():
        window.setWindowTitle(window.windowTitle() + "[*]")
    window.statusBar().showMessage(
        f"校对项目：{project.path or '尚未保存'} · "
        + (
            "有未保存修订；保存后才可导出"
            if project.dirty
            else (
                "已保存；原OCR和几何保留"
                if project.path
                else "快照尚未保存；保存后才可导出"
            )
        )
    )
    if preview is not None:
        window._cad_preview_binary = preview
        window.detected_canvas.set_image(preview)
    elif render:
        client = getattr(window, "_review_preview", None)
        if client is None:
            client = window._review_preview = PreviewClient(window)

        def apply(image):
            if window._review_project is project:
                window._cad_preview_binary = image
                window.detected_canvas.set_image(image)
                _refresh_review_project(window, render=False)
                window.statusBar().showMessage(
                    window.statusBar().currentMessage() + " · CAD预览已更新"
                )

        def failed(message):
            window.statusBar().showMessage("CAD预览失败；原预览保留：" + message)

        client.request(project, apply, failed)
        if not client.ready:
            window.statusBar().showMessage(
                window.statusBar().currentMessage()
                + " · CAD预览更新中（当前图可能为上一修订）"
            )


def create_review_project_from_window(window):
    if window._is_processing():
        raise ReviewProjectError("请先等待当前任务结束")
    if window._final_structure is None or window.current_path is None:
        raise ReviewProjectError("请先完成当前页转换")
    completed_key = getattr(window, "_completed_trace_key", None)
    if completed_key is None or completed_key != window._current_trace_key():
        raise ReviewProjectError(
            "NEEDS_RECONFIRM: 源文件或处理配置已变化；请重新处理当前页"
        )
    cache_path = window._store_current_trace()
    stored = load_trace_cache(cache_path) if cache_path else None
    if (
        stored is None
        or stored.cache_key is None
        or stored.cache_key != completed_key.payload()
    ):
        raise ReviewProjectError("当前结果缺少正式转换配置；请重新转换当前页")
    source = window._load_trace_source_for_current_page()
    return ReviewProject.create(
        window._final_structure,
        source_path=window.current_path,
        cache_key=stored.cache_key,
        frame=source,
        calibration=window.calibration,
        drawing_multiplier=window._export_drawing_multiplier(),
    )


def save_review_project_to(window, path, *, asynchronous=False):
    if window._is_processing():
        raise ReviewProjectError("请先等待当前任务结束")
    if (
        Path(path)
        .resolve()
        .is_relative_to(Path(window._trace_cache_tempdir.name).resolve())
    ):
        raise ReviewProjectError("请选择应用临时目录以外的持久项目位置")
    project = getattr(window, "_review_project", None)
    if getattr(window, "_review_save_job", None) is not None:
        raise ReviewProjectError("当前校对项目正在保存；请等待保存完成")
    created = project is None
    if created:
        project = create_review_project_from_window(window)
    if asynchronous:
        window._review_project = project
        snapshot = detached_review(project)
        saved_records = snapshot.records
        begin = perf_counter()
        timing(
            "save_begin",
            snapshot=project.snapshot_uuid,
            journal_records=len(saved_records),
        )

        def operation(token, progress):
            # No cancellation between serialize/readback/fsync/atomic replace.
            snapshot.save(path)
            timing("save_disk_complete", seconds=perf_counter() - begin)
            return snapshot.path

        def completed(target):
            project.path = target
            project.dirty = project.records != saved_records
            if window._review_project is project:
                _refresh_review_project(window, render=False)
                if project.dirty:
                    window.statusBar().showMessage(
                        "所选修订已保存；之后的新修订仍未保存。"
                    )
            timing(
                "save_ui_complete", seconds=perf_counter() - begin, dirty=project.dirty
            )

        def failed(message):
            project.dirty = True
            if window._review_project is project:
                _refresh_review_project(window, render=False)
                QMessageBox.critical(window, "项目保存失败；上一份保存保持", message)
            timing("save_failed")

        def finished():
            job = window._review_save_job
            window._review_save_job = None
            if job.release_project:
                project.close()

        job = ReviewJob(operation, completed, failed, finished)
        job.project = project
        job.release_project = False
        window._review_save_job = job
        window.statusBar().showMessage("正在保存校对项目；可以继续导航或修订。")
        job.start()
        return
    try:
        project.save(path)
    except BaseException:
        if created:
            project.close()
        raise
    window._review_project = project
    _refresh_review_project(window, render=created)


def save_review_project(self):
    if self._is_processing():
        return
    project = getattr(self, "_review_project", None)
    path, _ = QFileDialog.getSaveFileName(
        self,
        "保存校对项目",
        str(
            project.path
            if project and project.path
            else Path.home() / "drawing.icreview"
        ),
        "Image to CAD review project (*.icreview)",
    )
    if not path:
        return
    if not Path(path).suffix:
        path += ".icreview"
    try:
        save_review_project_to(self, path, asynchronous=True)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(self, "项目保存失败；上一份保存保持", str(exc))


def open_review_project_from_path(window, path):
    project = ReviewProject.open(path)  # Validate before changing any visible state.
    _apply_opened_project(window, project)


def _apply_opened_project(window, project, page_sizes=None):
    try:
        source = project.manifest["source"]
        native_pdf = Path(source["path"]).suffix.lower() == ".pdf"
        if page_sizes is None:
            page_sizes = {}
        if native_pdf and not page_sizes:
            from app.core.image_loader import pdf_page_size_mm

            page_sizes = {
                source["physical_page"] - 1: pdf_page_size_mm(
                    source["path"], source["physical_page"] - 1
                )
            }
        if getattr(window, "_review_project", None) is not None:
            detach_review_project(window)
        window._review_project = project
        window.current_path = Path(source["path"])
        window._native_pdf_mode = native_pdf
        window._current_pdf_page_index = source["physical_page"] - 1
        window._current_pdf_page = (
            source["physical_page"] if window._native_pdf_mode else None
        )
        window._pdf_page_sizes_mm = page_sizes
        window._pdf_page_states = {}
        window._trace_cache_by_key = {}
        window._dirty_trace_keys.clear()
        from app.core.processing import ProcessingCacheKey

        window._completed_trace_key = ProcessingCacheKey.from_payload(
            source["cache_identity"]
        )
        window._set_pdf_controls_enabled(
            False
        )  # A saved project contains exactly one physical page.
        window.page_combo.blockSignals(True)
        window.page_combo.clear()
        window.page_combo.addItem(
            f"保存快照 · 物理第 {source['physical_page']} 页",
            source["physical_page"] - 1,
        )
        window.page_combo.blockSignals(False)
        window.original_image = project.frame.copy()
        window.corrected_image = project.frame.copy()
        window.original_canvas.set_image(project.frame)
        window.corrected_canvas.set_image(project.frame)
        structure = project.baseline
        window.binary_image = structure.contour_binary
        window._trace_paths = structure.contours
        window._trace_threshold = structure.threshold
        window._trace_foreground_pixels = int(
            np.count_nonzero(structure.contour_binary == 0)
        )
        window._trace_vertex_count = sum(len(p.points) for p in structure.contours)
        window._last_warnings = structure.warnings
        window._signature_regions = structure.signatures
        window.lines = list(structure.straight_lines)
        window.raw_lines = []
        window.preprocess_stages = {}
        window._clear_preprocess_tabs()
        window.calibration = project.calibration
        window.drawing_scale_spin.setValue(
            int(project.manifest["export_settings"]["drawing_multiplier"])
        )
        _refresh_review_project(window)
    except BaseException:
        if getattr(window, "_review_project", None) is not project:
            project.close()
        raise


def open_review_project(self):
    if self._is_processing() or not can_leave_review_project(self):
        return
    path, _ = QFileDialog.getOpenFileName(
        self,
        "打开校对项目",
        str(Path.home()),
        "Image to CAD review project (*.icreview)",
    )
    if path:
        try:

            def operation(token, progress):
                start = perf_counter()
                project = ReviewProject.open(path)
                try:
                    source = project._manifest["source"]
                    sizes = {}
                    if Path(source["path"]).suffix.lower() == ".pdf":
                        from app.core.image_loader import pdf_page_size_mm

                        sizes[source["physical_page"] - 1] = pdf_page_size_mm(
                            source["path"], source["physical_page"] - 1
                        )
                    token.checkpoint()
                    timing("open_loaded", seconds=perf_counter() - start)
                    return project, sizes
                except BaseException:
                    project.close()
                    raise

            def completed(result):
                project, sizes = result
                start = perf_counter()
                try:
                    _apply_opened_project(self, project, sizes)
                    timing("open_ui_apply", seconds=perf_counter() - start)
                except (OSError, ValueError) as exc:
                    QMessageBox.critical(self, "项目无法打开", str(exc))

            self._start_processing(operation, completed, "正在读取校对项目…")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "项目无法打开", str(exc))


def review_snapshot_texts(window):
    if window._is_processing():
        return
    created = getattr(window, "_review_project", None) is None
    try:
        if getattr(window, "_review_project", None) is None:
            window._review_project = create_review_project_from_window(window)
        project = window._review_project
        project.validate_source()
        dialog = SnapshotTextReviewDialog(project, window)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if created:
                detach_review_project(window)
            return
        project.add_records(dialog.project.records)
        _refresh_review_project(window)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(window, "校对未应用", str(exc))


def can_leave_review_project(window):
    project = getattr(window, "_review_project", None)
    if project is None or not project.dirty:
        return True
    answer = QMessageBox.question(
        window,
        "有未保存校对",
        "保存校对项目后再离开？",
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer == QMessageBox.StandardButton.Save:
        window.save_review_project()
        return not project.dirty
    return answer == QMessageBox.StandardButton.Discard


def detach_review_project(window):
    project = getattr(window, "_review_project", None)
    if project is not None:
        if getattr(window, "_review_preview", None):
            window._review_preview.close()
        release_project(window, project)
        window._review_project = None
        window.setWindowModified(False)
        window.drawing_scale_spin.setEnabled(True)
