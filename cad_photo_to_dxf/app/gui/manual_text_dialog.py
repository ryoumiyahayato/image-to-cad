"""Manual recovery from a rectangle drawn on the actual source canvas."""

from __future__ import annotations
from copy import deepcopy

from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.review_project import ConfirmationEvent, ReviewProjectError
from app.core import manual_text_recovery as recovery
from app.gui.ocr_review import OcrGraphicsView, _image_pixmap
from app.gui.review_async import PreviewClient


class LinkedReviewView(OcrGraphicsView):
    viewport_changed = Signal()

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.viewport_changed.emit()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.viewport_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()


class SourceSelectionView(LinkedReviewView):
    selected = Signal(object)

    def __init__(self, scene):
        super().__init__(scene)
        self.selecting = False
        self.start = None
        self.rectangle = None

    def mousePressEvent(self, event):
        if self.selecting and event.button() == Qt.MouseButton.LeftButton:
            self.start = self.mapToScene(event.position().toPoint())
            if self.rectangle is not None:
                self.scene().removeItem(self.rectangle)
            pen = QPen(QColor("#d00080"), 1)
            pen.setCosmetic(True)
            self.rectangle = self.scene().addRect(QRectF(self.start, self.start), pen)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.rectangle.setRect(
                QRectF(
                    self.start, self.mapToScene(event.position().toPoint())
                ).normalized()
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is not None:
            rect = self.rectangle.rect().intersected(self.sceneRect())
            self.start = None
            x = max(0, int(rect.left()))
            y = max(0, int(rect.top()))
            w = min(int(self.sceneRect().width()) - x, int(rect.right() + 1) - x)
            h = min(int(self.sceneRect().height()) - y, int(rect.bottom() + 1) - y)
            if w > 1 and h > 1:
                self.selected.emit([x, y, w, h])
            return
        super().mouseReleaseEvent(event)


class ManualTextDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project.draft()
        self.test_only = "TEST_ONLY" in project.manifest.get("origin", "").upper()
        self.selection = None
        self.manual_uuid = None
        self._loaded = False
        self._preview_signature = None
        self._preview_records = None
        self._preview_covered = False
        self._preview_client = PreviewClient(self, parent or self)
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(300)
        self._edit_timer.timeout.connect(self._auto_preview)
        self.setWindowTitle(
            "补录未识别文字" + (" · QA_TEST_ONLY" if self.test_only else "")
        )
        self.resize(1550, 940)
        root = QVBoxLayout(self)
        note = QLabel(
            "在左侧源图框选原来没有TEXT的字形。滚轮放大；取消框选可拖动。输入后取实际墨迹建议，再预览正式CAD。内容和最终布局分别确认；返回后保存校对项目。"
        )
        note.setWordWrap(True)
        root.addWidget(note)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(split, 1)
        visual = QWidget()
        visual_layout = QVBoxLayout(visual)
        toolbar = QHBoxLayout()
        visual_layout.addLayout(toolbar)
        self.select_button = QPushButton("框选源字形")
        self.select_button.setCheckable(True)
        toolbar.addWidget(self.select_button)
        fit = QPushButton("源图全页")
        toolbar.addWidget(fit)
        selected_fit = QPushButton("放大选区与邻对象")
        toolbar.addWidget(selected_fit)
        # Navigation only changes the view. A source selection still requires dragging.
        self.nav_x = QDoubleSpinBox()
        self.nav_y = QDoubleSpinBox()
        for spin, maximum in (
            (self.nav_x, project.baseline.source_size_px[0]),
            (self.nav_y, project.baseline.source_size_px[1]),
        ):
            spin.setRange(0, maximum)
            spin.setDecimals(0)
            spin.setPrefix("X " if spin is self.nav_x else "Y ")
            toolbar.addWidget(spin)
        locate = QPushButton("定位源图")
        toolbar.addWidget(locate)
        panes = QSplitter(Qt.Orientation.Horizontal)
        visual_layout.addWidget(panes, 1)
        source_widget = QWidget()
        source_layout = QVBoxLayout(source_widget)
        source_layout.addWidget(QLabel("源参照（原像素；框选仅在此处）"))
        source_layout.addWidget(
            QLabel(
                f"物理第 {project.manifest['source']['physical_page']} 页 · 源像素坐标"
            )
        )
        source_scene = QGraphicsScene(self)
        source_scene.addPixmap(_image_pixmap(project.frame))
        source_scene.setSceneRect(0, 0, *project.baseline.source_size_px)
        self.source_view = SourceSelectionView(source_scene)
        source_layout.addWidget(self.source_view)
        panes.addWidget(source_widget)
        cad_widget = QWidget()
        cad_layout = QVBoxLayout(cad_widget)
        cad_layout.addWidget(QLabel("正式CAD可见结果（含邻对象；不叠加源图）"))
        self.preview_status = QLabel("CAD预览更新中")
        cad_layout.addWidget(self.preview_status)
        self.cad_scene = QGraphicsScene(self)
        self.cad_view = LinkedReviewView(self.cad_scene)
        cad_layout.addWidget(self.cad_view)
        panes.addWidget(cad_widget)
        self.cad_scene.setSceneRect(0, 0, *project.baseline.source_size_px)
        panes.setChildrenCollapsible(False)
        panes.setSizes([500, 500])
        self._syncing = False
        self._render_project = self.project
        self._render_ready = None
        self._render_key = None
        self._viewport_timer = QTimer(self)
        self._viewport_timer.setSingleShot(True)
        self._viewport_timer.setInterval(120)
        self._viewport_timer.timeout.connect(self._request_viewport)
        self.source_view.viewport_changed.connect(
            lambda: self._sync_views(self.source_view, self.cad_view)
        )
        self.cad_view.viewport_changed.connect(
            lambda: self._sync_views(self.cad_view, self.source_view)
        )
        split.addWidget(visual)
        panel = QWidget()
        form_root = QVBoxLayout(panel)
        split.addWidget(panel)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 2)
        form_root.addWidget(QLabel("已补录记录（选择可编辑或撤回）"))
        self.records_list = QListWidget()
        self.records_list.setMaximumHeight(120)
        form_root.addWidget(self.records_list)
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("用户确认的正确字符串")
        form_root.addWidget(self.text_edit)
        self.selection_label = QLabel("尚未框选源字形")
        self.selection_label.setWordWrap(True)
        form_root.addWidget(self.selection_label)
        suggest = QPushButton("从实际墨迹提出LFF布局建议")
        form_root.addWidget(suggest)
        form = QFormLayout()
        form_root.addLayout(form)
        self.parameters = {}
        for key, label in [
            ("x", "插入点 X（源像素）"),
            ("y", "基线 Y（源像素向下）"),
            ("height", "字高（源像素）"),
            ("width", "宽度因子"),
            ("rotation", "旋转角（CAD方向）"),
        ]:
            spin = QDoubleSpinBox()
            spin.setDecimals(5)
            spin.setRange(
                -360
                if key == "rotation"
                else 0.01
                if key in {"height", "width"}
                else 0,
                360
                if key == "rotation"
                else 100
                if key == "width"
                else max(project.baseline.source_size_px),
            )
            self.parameters[key] = spin
            form.addRow(label, spin)
            spin.valueChanged.connect(self._changed)
        self.hide_authorization = QCheckBox("仅本字形：授权把完整独立轮廓转入隐藏备份")
        self.hide_authorization.setToolTip(
            "来源不全、混合结构、多字符均保留原轮廓。内容确认本身不会隐藏结构。"
        )
        self.hide_authorization.setChecked(False)
        form_root.addWidget(self.hide_authorization)
        self.hide_authorization.toggled.connect(self._changed)
        preview = QPushButton("预览实际CAD效果")
        form_root.addWidget(preview)
        content = QPushButton("确认文字内容")
        form_root.addWidget(content)
        self.layout_button = QPushButton("确认最终布局")
        self.layout_button.setEnabled(False)
        form_root.addWidget(self.layout_button)
        withdraw = QPushButton("撤回本条补录并恢复原轮廓")
        form_root.addWidget(withdraw)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        form_root.addWidget(self.state_label)
        form_root.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "应用到会话（随后保存项目）"
        )
        root.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.select_button.toggled.connect(self._selection_mode)
        fit.clicked.connect(self.fit_source)
        selected_fit.clicked.connect(self.fit_selection)
        locate.clicked.connect(self._locate)
        self.source_view.selected.connect(self._selected)
        suggest.clicked.connect(self._suggest)
        preview.clicked.connect(self._preview)
        content.clicked.connect(self._confirm_content)
        self.layout_button.clicked.connect(self._confirm_layout)
        withdraw.clicked.connect(self._withdraw)
        self.text_edit.textChanged.connect(self._changed)
        self.records_list.currentRowChanged.connect(self._load_record)
        self._refresh_list()
        QTimer.singleShot(0, self._initial_view)

    def _initial_view(self):
        if self._manual_records:
            self.records_list.setCurrentRow(0)
        else:
            self.fit_source()
            self._render(self.project)

    def _sync_views(self, source, target):
        if self._syncing:
            return
        self._syncing = True
        try:
            center = source.mapToScene(source.viewport().rect().center())
            target.setTransform(source.transform())
            target.centerOn(center)
        finally:
            self._syncing = False
        if hasattr(self, "_viewport_timer"):
            self._preview_client.invalidate()
            self._preview_covered = False
            if hasattr(self, "layout_button"):
                self.layout_button.setEnabled(False)
            self.preview_status.setText("视口更新中；旧图待替换")
            self._viewport_timer.start()

    def _event(self, preview=False):
        return ConfirmationEvent.create(test_only=preview or self.test_only)

    def _selection_mode(self, enabled):
        self.source_view.selecting = enabled
        self.source_view.setDragMode(
            self.source_view.DragMode.NoDrag
            if enabled
            else self.source_view.DragMode.ScrollHandDrag
        )

    def fit_source(self):
        self.source_view.fitInView(
            self.source_view.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
        )
        self._sync_views(self.source_view, self.cad_view)

    def _locate(self):
        x, y = self.nav_x.value(), self.nav_y.value()
        self.source_view.fitInView(
            QRectF(x - 100, y - 100, 200, 200), Qt.AspectRatioMode.KeepAspectRatio
        )
        self._sync_views(self.source_view, self.cad_view)

    def fit_selection(self):
        if self.selection:
            x, y, w, h = self.selection
            context = QRectF(
                x - max(w, 30), y - max(h, 30), w + 2 * max(w, 30), h + 2 * max(h, 30)
            )
            self.source_view.fitInView(context, Qt.AspectRatioMode.KeepAspectRatio)
            self._sync_views(self.source_view, self.cad_view)

    def _selected(self, selection):
        self.manual_uuid = None
        self.selection = selection
        self.selection_label.setText(f"源选区 X/Y/W/H：{selection}")
        self.hide_authorization.setChecked(False)
        self._changed()
        self.fit_selection()
        self.select_button.setChecked(False)

    def _values(self):
        return {k: spin.value() for k, spin in self.parameters.items()}

    def _signature(self):
        return (
            self.manual_uuid,
            self.selection,
            self.text_edit.text(),
            self._values(),
            self.hide_authorization.isChecked(),
        )

    def _auto_preview(self):
        if (
            self.selection
            and self.text_edit.text().strip()
            and all(self.parameters[k].value() > 0 for k in ("height", "width"))
        ):
            self._preview(quiet=True)

    def _changed(self, *_):
        if not self._loaded:
            self._preview_client.invalidate()
            self._preview_signature = None
            self._preview_covered = False
            self.layout_button.setEnabled(False)
            self.preview_status.setText("当前输入尚未预览；已有图像可能为上一修订")
            self.state_label.setText(
                "当前输入尚未预览或确认。修改内容或参数后需重新确认内容和布局。"
            )
            self._edit_timer.start()

    def _suggest(self):
        try:
            result = recovery.suggest(
                self.project, self.selection, self.text_edit.text()
            )
            self._loaded = True
            for key, value in result["parameters"].items():
                self.parameters[key].setValue(value)
            self._loaded = False
            self._changed()
            self.state_label.setText(
                result["evidence"]["reason"] + "\n建议来自源墨迹，不是选择框字高。"
            )
        except (ValueError, TypeError) as exc:
            self._error(exc)

    def _preview(self, quiet=False):
        try:
            draft = self.project.draft()
            # PREVIEW uses an ephemeral QA journal. It never enters the project.
            if self.manual_uuid:
                draft._records = [
                    r
                    for r in draft._records
                    if r.get("manual_uuid") != self.manual_uuid
                ]
            r = recovery.confirm(
                draft,
                selection=self.selection,
                content=self.text_edit.text(),
                parameters=self._values(),
                source_hide_authorized=self.hide_authorization.isChecked(),
                event=self._event(preview=True),
                manual_uuid=self.manual_uuid,
            )
            recovery.confirm(
                draft,
                manual_uuid=r["manual_uuid"],
                action="CONFIRM_LAYOUT",
                event=self._event(preview=True),
            )
            signature = deepcopy(self._signature())
            records = self.project.records
            active = recovery.replay(self.project).get(self.manual_uuid)
            can_confirm = bool(
                active
                and active["action"] == "CONFIRM_CONTENT"
                and active["content"] == self.text_edit.text()
                and active["parameters"] == self._values()
                and active["source_hide_authorized"]
                == self.hide_authorization.isChecked()
            )

            def ready():
                if signature == self._signature() and records == self.project.records:
                    self._preview_signature = signature
                    self._preview_records = records
                    x, y, w, h = self.selection
                    context = QRectF(
                        x - max(w, 30),
                        y - max(h, 30),
                        w + 2 * max(w, 30),
                        h + 2 * max(h, 30),
                    )
                    context = context.intersected(self.cad_scene.sceneRect())
                    covered = QRectF(*self._displayed_roi).contains(context)
                    self._preview_covered = covered
                    self.layout_button.setEnabled(can_confirm and covered)
                    self.layout_button.setToolTip(
                        "" if covered else "请先显示完整选区与邻对象，再确认布局"
                    )

            self._render(
                draft,
                ready=ready,
                key=("manual-preview", self.project.snapshot_uuid, records, signature),
            )
            state = recovery.replay(draft)[r["manual_uuid"]]["source_transfer"]
            self.state_label.setText(
                "QA_TEST_ONLY临时预览；尚未成为最终布局。\n"
                + (
                    "完整字形轮廓将转入隐藏备份，可撤回。"
                    if state == "HIDDEN_FROZEN_BACKUP"
                    else "共存人工TEXT覆盖层：原轮廓保留，可能重叠；不计清洁替换。"
                )
            )
        except (ValueError, TypeError) as exc:
            if quiet:
                self.preview_status.setText("草稿尚不能预览：" + str(exc))
            else:
                self._error(exc)

    def _render(self, project, *, ready=None, key=None):
        self._edit_timer.stop()
        self._render_project = project
        self._render_ready = ready
        self._render_key = key
        self._viewport_timer.stop()
        self._request_viewport()

    def _request_viewport(self):
        project = self._render_project
        rect = self.cad_view.mapToScene(self.cad_view.viewport().rect()).boundingRect()
        rect = rect.intersected(self.cad_scene.sceneRect())
        if rect.isEmpty():
            return
        # Native source resolution is retained. Large views update a visibly
        # bounded central ROI; no downsampled page can authorize layout.
        rect = rect.adjusted(-4, -4, 4, 4).intersected(self.cad_scene.sceneRect())
        if rect.width() > 1600 or rect.height() > 1600:
            center = rect.center()
            rect = QRectF(
                center.x() - min(1600.0, rect.width()) / 2,
                center.y() - min(1600.0, rect.height()) / 2,
                min(1600.0, rect.width()),
                min(1600.0, rect.height()),
            )
        roi = (rect.left(), rect.top(), rect.width(), rect.height())
        density = min(4.0, max(1.0, abs(self.cad_view.transform().m11())))
        self.layout_button.setEnabled(False)
        self.preview_status.setText(f"CAD r{len(project.records)} 更新中；旧图待替换")
        ready = self._render_ready
        state = "草稿待保存" if project.dirty else "已保存项目"
        status = f"CAD r{len(project.records)} · {state} · ROI {int(roi[0])},{int(roi[1])} {int(roi[2])}×{int(roi[3])}"

        def apply(image):
            self._displayed_roi = roi
            self._displayed_density = density
            self.cad_scene.clear()
            item = self.cad_scene.addPixmap(_image_pixmap(image))
            item.setScale(1.0 / density)
            item.setPos(roi[0], roi[1])
            self.preview_status.setText(status)
            pen = QPen(QColor("#3076a8"))
            pen.setCosmetic(True)
            self.cad_scene.addRect(QRectF(*roi), pen)
            actual = self._preview_client.entities.get(self.manual_uuid)
            if actual:
                transfer = (
                    "完整轮廓已转隐藏/冻结备份"
                    if actual["source_transfer"] == "HIDDEN_FROZEN_BACKUP"
                    else "原轮廓保留，可能重叠，需进一步确认"
                    if actual["source_transfer"] == "COEXISTING_OVERLAY"
                    else actual["source_transfer"]
                )
                self.state_label.setText(
                    f"字符串：{actual['content']} · {actual['entity']} · {actual['layer']}\n"
                    f"来源：manual · 实际导出对象 · {'可见' if actual['visible'] else '层关闭或冻结'}\n"
                    f"layout：{'临时草稿' if project is not self.project else '已确认'}\n{transfer}"
                )
            elif self.manual_uuid:
                active = recovery.replay(project).get(self.manual_uuid)
                if active:
                    self.state_label.setText(
                        f"字符串：{active['content']} · manual · {active['action']}\n"
                        f"当前正式CAD没有本条TEXT · 轮廓：{active['source_transfer']}"
                    )
            if ready:
                ready()

        def failed(message):
            self.preview_status.setText("CAD预览失败；请重试：" + message)
            self.layout_button.setEnabled(False)

        self._preview_client.request(
            project,
            apply,
            failed,
            key=self._render_key,
            roi=roi,
            output_scale=density,
            zoom=abs(self.cad_view.transform().m11()),
        )
        if self._preview_client.ready:
            self.preview_status.setText(status)
            if ready:
                ready()

    def done(self, result):
        self._viewport_timer.stop()
        self._edit_timer.stop()
        self._preview_client.close()
        super().done(result)

    def _confirm_content(self):
        try:
            r = recovery.confirm(
                self.project,
                selection=self.selection,
                content=self.text_edit.text(),
                parameters=self._values(),
                manual_uuid=self.manual_uuid,
                source_hide_authorized=self.hide_authorization.isChecked(),
                event=self._event(),
            )
            if r:
                self.manual_uuid = r["manual_uuid"]
            self._refresh_list()
            self._render(self.project)
            self._preview_signature = None
            self.layout_button.setEnabled(False)
            self.state_label.setText(
                "内容已确认；源轮廓保持可见。请预览实际CAD，再单独确认最终布局。"
            )
        except (ValueError, TypeError) as exc:
            self._error(exc)

    def _confirm_layout(self):
        try:
            if (
                not self._preview_client.ready
                or not self._preview_covered
                or self._preview_signature != self._signature()
                or self._preview_records != self.project.records
            ):
                raise ReviewProjectError("请先预览当前参数")
            r = recovery.confirm(
                self.project,
                manual_uuid=self.manual_uuid,
                action="CONFIRM_LAYOUT",
                event=self._event(),
            )
            self._render(self.project)
            self._refresh_list()
            self.layout_button.setEnabled(False)
            self.state_label.setText(
                "最终布局已确认。返回后保存校对项目。\n" + r["source_transfer"]
            )
        except (ValueError, TypeError) as exc:
            self._error(exc)

    def _withdraw(self):
        try:
            if self.manual_uuid not in recovery.replay(self.project):
                raise ReviewProjectError("请先选择一条已补录记录，再撤回。")
            record = recovery.confirm(
                self.project,
                manual_uuid=self.manual_uuid,
                action="WITHDRAW",
                event=self._event(),
            )
            if record is None:
                self.state_label.setText("该记录已撤回；未增加修订。")
                return
            self._refresh_list()
            self._changed()
            self._render(self.project)
            self.state_label.setText(
                "本条补录已撤回；原始轮廓恢复可见。返回后保存项目并重新导出。"
            )
        except (ValueError, TypeError) as exc:
            self._error(exc)

    def _refresh_list(self):
        self.records_list.blockSignals(True)
        self.records_list.clear()
        self._manual_records = list(recovery.replay(self.project).values())
        for r in self._manual_records:
            self.records_list.addItem(
                r["content"] + " · " + r["action"] + " · " + r["source_transfer"]
            )
        self.records_list.blockSignals(False)

    def _load_record(self, row):
        if not 0 <= row < len(self._manual_records):
            return
        r = self._manual_records[row]
        self._loaded = True
        self.manual_uuid = r["manual_uuid"]
        self.selection = r["selection"]
        self.text_edit.setText(r["content"])
        for key, value in r["parameters"].items():
            self.parameters[key].setValue(value)
        self.hide_authorization.setChecked(r["source_hide_authorized"])
        self._loaded = False
        self.selection_label.setText(f"源选区 X/Y/W/H：{self.selection}")
        self._changed()
        self.fit_selection()
        self._render(self.project)
        self.state_label.setText(
            f"字符串：{r['content']} · manual · {r['action']}\n实际实体与图层待当前CAD预览更新\n备份资格：{r['source_transfer']}"
        )

    def _error(self, error):
        self._loaded = False
        QMessageBox.warning(self, "补录未应用", str(error))


def recover_manual_text(window):
    from app.gui.review_project_actions import (
        create_review_project_from_window,
        _refresh_review_project,
    )

    if window._is_processing():
        return
    try:
        if window._review_project is None:
            window._review_project = create_review_project_from_window(window)
        dialog = ManualTextDialog(window._review_project, window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            window._review_project.add_records(dialog.project.records)
            _refresh_review_project(window)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(window, "补录未应用", str(exc))


def export_review_document(window):
    """The existing document consumer, available for a saved one-page project."""
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    from app.core.image_loader import pdf_page_size_mm
    from app.export.document_export import DocumentPage
    from app.export.trace_document_export import export_trace_document_streaming

    project = window._review_project
    if window._is_processing():
        return
    if project is None or project.path is None or project.dirty:
        QMessageBox.warning(window, "校对尚未保存", "请先保存当前校对项目。")
        return
    try:
        review = project.validated_review()
        source = project.manifest["source"]
        if Path(source["path"]).suffix.lower() == ".pdf":
            size = pdf_page_size_mm(source["path"], source["physical_page"] - 1)
        elif project.calibration is not None:
            scale = project.calibration.mm_per_pixel
            size = tuple(v * scale for v in project.baseline.source_size_px)
        else:
            raise ReviewProjectError(
                "文档出口需要纸面毫米标定。当前项目可用当前页DXF出口。"
            )
        path, _ = QFileDialog.getSaveFileName(
            window,
            "导出校对项目文档DXF",
            str(project.path.with_suffix(".document.dxf")),
            "DXF (*.dxf)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".dxf"

        def operation(token, progress):
            return export_trace_document_streaming(
                [
                    DocumentPage(
                        source["physical_page"],
                        None,
                        size,
                        final_structure=project.baseline,
                        text_review=review,
                        drawing_scale=project.manifest["export_settings"][
                            "drawing_multiplier"
                        ],
                    )
                ],
                path,
                cancellation_token=token,
                progress_callback=progress,
            )

        def completed(result):
            QMessageBox.information(window, "文档DXF已导出", str(result.path))

        window._start_processing(operation, completed, "正在导出校对项目文档DXF…")
    except (OSError, ValueError) as exc:
        QMessageBox.warning(window, "文档导出未应用", str(exc))
