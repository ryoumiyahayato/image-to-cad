"""Isolated current-CAD project window; no production baseline regeneration."""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QTransform
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QComboBox, QLabel, QLineEdit, QPushButton, QGraphicsScene,
    QGraphicsView, QFileDialog, QMessageBox, QSplitter, QDialog, QDialogButtonBox,
    QPlainTextEdit)

from reconnect import ReconnectProject, write_files
from local_repair import current_texts, preview_repair, accept_repair, source_evidence
from relation_review import resolve_confirmation
import cad_delta as delta
from cad_preview import draw_current_cad


class ProjectWindow(QMainWindow):
    def __init__(self, path=None, *, actor="HUMAN_REVIEWED"):
        super().__init__()
        self.actor, self.project, self.preview, self.preview_files = actor, None, None, None
        self.setWindowTitle("Image to CAD · 当前 CAD 工程 · 局部文字修复")
        self.resize(1250, 850)
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.status = QLabel("打开已回接的 .icreview 工程")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        actions = QHBoxLayout(); layout.addLayout(actions)
        for title, fn in (("打开工程", self.open_dialog), ("另存工程", self.save_as), ("外部保存回接", self.import_external), ("查看来源候选及失效", self.relation_history), ("撤销并保存", self.undo), ("导出当前 CAD", self.export)):
            button = QPushButton(title); button.clicked.connect(lambda _checked=False, f=fn: self.run(f)); actions.addWidget(button)
        self.member = QComboBox(); self.source = QComboBox()
        for combo in (self.member, self.source):
            combo.setEditable(True); combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setMinimumWidth(300)
        layout.addWidget(QLabel("当前 CAD 文字成员（只表示当前状态，不是历史身份）")); layout.addWidget(self.member)
        layout.addWidget(QLabel("来源区域（须由本次明确确认建立关系）")); layout.addWidget(self.source)
        self.member.currentIndexChanged.connect(lambda: self.run(self.select_member))
        self.source.currentIndexChanged.connect(lambda: self.run(self.show_source))
        views = QSplitter(); layout.addWidget(views, 1)
        self.before_view, self.after_view = self.cad_panel(views, "当前 CAD"), self.cad_panel(views, "修复预览")
        source_panel = QWidget(); source_layout = QVBoxLayout(source_panel)
        self.crop_title = QLabel("重新读取来源邻域"); self.crop_title.setWordWrap(True)
        source_layout.addWidget(self.crop_title)
        self.crop = QLabel(); self.crop.setAlignment(Qt.AlignmentFlag.AlignCenter); self.crop.setMinimumSize(260, 260)
        source_layout.addWidget(self.crop, 1); views.addWidget(source_panel)
        self.change = QLabel("选择成员和来源区域。修改只作用于一个 TEXT 字符串，保持当前布局。")
        self.change.setWordWrap(True); layout.addWidget(self.change)
        self.text = QLineEdit(); self.text.setPlaceholderText("修订后的单行文字")
        self.text.textChanged.connect(self.invalidate); layout.addWidget(self.text)
        commands = QHBoxLayout(); layout.addLayout(commands)
        button = QPushButton("预览局部修复"); button.clicked.connect(lambda: self.run(self.make_preview)); commands.addWidget(button)
        self.confirm = QPushButton("直接文字确认已停用")
        self.confirm.clicked.connect(lambda: self.run(self.accept)); commands.addWidget(self.confirm)
        self.confirm.setEnabled(False)
        layout.addWidget(QLabel("wqy-unicode使用项目LFF；未支持字体/布局拒绝预览。屏幕细线约1.4像素起，不代表出图线宽。"))
        if path:
            self.run(lambda: self.open_path(path))

    def cad_panel(self, splitter, title):
        widget = QWidget(); layout = QVBoxLayout(widget); layout.addWidget(QLabel(title))
        view = QGraphicsView(); view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setTransform(QTransform.fromScale(1, -1))
        view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        layout.addWidget(view); splitter.addWidget(widget)
        return view

    def run(self, fn):
        try:
            fn()
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            QMessageBox.warning(self, "操作未应用", str(exc))

    def invalidate(self, *_):
        self.preview = self.preview_files = None
        self.confirm.setEnabled(False)

    def draft(self):
        if self.project is None:
            raise ValueError("先打开工程")
        project = ReconnectProject(self.project.core, deepcopy(self.project.state), dict(self.project.payloads), self.project.path)
        project.disk_revision = self.project.disk_revision
        return project

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开当前 CAD 工程", "", "Image to CAD (*.icreview)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        project = ReconnectProject.open(path)
        project.disk_revision = project.state["revision"]
        self.project = project; self.populate()

    def populate(self, selected=None):
        self.invalidate()
        self.member.blockSignals(True); self.source.blockSignals(True)
        self.member.clear(); self.source.clear()
        for row in current_texts(self.project):
            c = row["content"]
            self.member.addItem(f'{row["handle"]} | {c["text"]} | ({c["insert"][0]:.3f}, {c["insert"][1]:.3f})', row["handle"])
        manifest = json.loads(self.project.core["project.json"])
        for binding in manifest["text_bindings"]:
            self.source.addItem(f'{binding["index"]+1} | {binding["original_candidate"]["text"]} | 第{binding["physical_page"]}页', binding["text_source_uuid"])
        self.source.setCurrentIndex(-1)
        if selected:
            self.member.setCurrentIndex(self.member.findData(selected))
        self.member.blockSignals(False); self.source.blockSignals(False)
        state = self.project.state["states"][self.project.state["current"]]
        pending = sum(bool(r.get("prior_confirmations")) for r in state["relations"].values())
        missing = len(state.get("unresolved_relation_refs", []))
        self.status.setText(f'{self.project.path}\n修订 {self.project.state["revision"]} · 确认操作人 {self.actor} · 来源候选成员 {pending} · 无当前对应 {missing} · 隔离工程入口')
        self.select_member(); self.show_source()

    def render(self, view, files, member):
        with TemporaryDirectory(prefix="g28-window-") as tmp:
            doc = delta.ezdxf.readfile(write_files(tmp, files))
            scene = QGraphicsScene(view)
            draw_current_cad(doc, scene)
            old_scene = view.scene(); view.setScene(scene)
            if old_scene:
                old_scene.deleteLater()
            e = doc.entitydb.get(member)
            if e is not None:
                x, y, _ = e.dxf.insert
                span = max(8., e.dxf.height*5.)
                view.fitInView(QRectF(x-span, y-span, span*2, span*2), Qt.AspectRatioMode.KeepAspectRatio)
            else:
                view.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def select_member(self):
        self.invalidate()
        if self.project is None or self.member.currentIndex() < 0:
            return
        member = self.member.currentData()
        row = next(r for r in current_texts(self.project) if r["handle"] == member)
        self.text.setText(row["content"]["text"])
        files = self.project.payloads[self.project.state["current"]]
        self.render(self.before_view, files, member)
        self.render(self.after_view, files, member)
        relation = self.project.state["states"][self.project.state["current"]]["relations"].get(member, {})
        self.change.setText(f'当前 {row["content"]["text"]} · 关系 {relation.get("status", "未确认")}。只改文字，布局保持。')

    def show_source(self):
        self.invalidate(); self.crop.clear()
        if self.project is None or self.source.currentIndex() < 0:
            self.crop_title.setText("请选择来源区域；当前成员不会自动认领来源。")
            return
        proof = source_evidence(self.project, self.source.currentData())
        self.display_source(proof)

    def display_source(self, proof):
        pixmap = QPixmap(); pixmap.loadFromData(base64.b64decode(proof["png_base64"]))
        self.crop.setPixmap(pixmap.scaled(330, 390, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        self.crop_title.setText(f'重新读取第{proof["physical_page"]}页 · {proof["dpi"]} DPI\n邻域 {proof["observed_box_xyxy"]}\n历史 OCR：{proof["original_ocr_text"]}')

    def make_preview(self):
        if self.project is None or self.source.currentIndex() < 0:
            raise ValueError("先选择当前文字和来源区域")
        self.preview, self.preview_files = preview_repair(self.project, self.member.currentData(), self.source.currentData(), self.text.text())
        self.display_source(self.preview["source_evidence"])
        self.render(self.after_view, self.preview_files, self.member.currentData())
        self.change.setText(f'文字建议：{self.preview["before"]["text"]} → {self.preview["after"]["text"]}。本版邻字遮挡判断未通过，直接确认已停用。须在实际CAD修改/核验后，经外部保存回接接受。')
        self.confirm.setEnabled(False)

    def accept(self):
        raise ValueError("直接文字确认已停用；须在实际CAD核验后外部回接")

    def import_external(self):
        if self.project is None:
            raise ValueError("先打开工程")
        directory = str(self.project.path.parent)
        before, _ = QFileDialog.getOpenFileName(self, "选择外部编辑前实际导出 D0", directory, "DXF (*.dxf)")
        if not before:
            return
        after, _ = QFileDialog.getOpenFileName(self, "选择外部编辑器保存 D1", directory, "DXF (*.dxf)")
        if not after:
            return
        preview = self.project.preview(before, after)
        dialog = QDialog(self); dialog.setWindowTitle("外部保存回接预览"); dialog.resize(850, 620)
        layout = QVBoxLayout(dialog)
        status = {"READY_FOR_REVIEW": "可复核接受", "ALREADY_ACCEPTED": "已接受，无需重复", "OBJECT_CONFLICT": "修改冲突", "STALE_BASE_REQUIRES_MERGE": "导出基线已过期"}.get(preview["status"], preview["status"])
        layout.addWidget(QLabel(f'{status} · 内容复核 {preview.get("content_confirmation_items", 0)} · 来源关系复核 {preview.get("relation_confirmation_items", 0)} · 合计 {preview["confirmation_items"]}'))
        note = QLabel("接受外部结果会保留先前确认作为待复核候选；不能据此认定跨保存身份。无当前对应的确认仍可追查。")
        note.setWordWrap(True); layout.addWidget(note)
        report = preview.get("delta", {})
        summary = report.get("summary", {})
        lines = [f'内容相同 {summary.get("content_equal", 0)}；功能等价 {summary.get("functional_equal", 0)}；对应歧义 {summary.get("ambiguous_groups", 0)}。']
        for change in report.get("changes", []):
            lines.append(f'\n成员 {change["before"]} → 候选 {change["after"]}：')
            lines.extend(f'  {field["field"]}: {field["before"]} → {field["after"]}' for field in change["fields"])
        for label, key in (("旧未匹配成员", "removed_or_unmatched"), ("新未匹配成员", "added_or_unmatched")):
            if report.get(key):
                lines.append(f'{label}：' + ", ".join(report[key]))
        for change in report.get("document_changes", []):
            lines.append(f'文档 {change["field"]}: {change["before"]} → {change["after"]}')
        for change in preview.get("relation_changes", []):
            current = ", ".join(change["after_candidates"]) or "无当前对应；保留失效记录"
            proof = resolve_confirmation(self.project, change["reference"])["source_evidence"]
            lines.extend([f'\n先前确认成员：{", ".join(change["before_members"])}', f'当前待复核候选：{current}', f'先前确认者：{change["prior_actor"]}；来源第 {proof.get("physical_page", "未知")} 页。', "先前确认及裁片保留，可在“查看来源候选及失效”追查。", "此次接受不证明跨保存身份，也不开放自动来源操作。"])
        text = QPlainTextEdit("\n".join(lines)); text.setReadOnly(True); layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("接受外部结果及关系变更并保存")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(preview["status"] == "READY_FOR_REVIEW")
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            project = self.draft()
            if project.accept(preview, actor=self.actor):
                project.save(); self.project = project; self.populate()

    def relation_history(self):
        if self.project is None:
            raise ValueError("先打开工程")
        state = self.project.state["states"][self.project.state["current"]]
        entries = [(member, ref) for member, relation in state["relations"].items() for ref in relation.get("prior_confirmations", [])]
        entries += [(None, lost["reference"]) for lost in state.get("unresolved_relation_refs", [])]
        if not entries:
            QMessageBox.information(self, "来源候选", "当前没有先前确认的候选或失效记录。")
            return
        dialog = QDialog(self); dialog.setWindowTitle("先前确认：候选及失效记录"); dialog.resize(720, 650)
        layout = QVBoxLayout(dialog); choice = QComboBox(); layout.addWidget(choice)
        for member, reference in entries:
            choice.addItem(f'{"候选当前成员 " + member if member else "无当前对应"} ← {reference["state"][:8]}/{reference["member"]}')
        label = QLabel(); label.setWordWrap(True); layout.addWidget(label)
        crop = QLabel(); crop.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(crop, 1)
        reread = QPushButton("在主窗口重新读取该来源区域"); layout.addWidget(reread)

        def show():
            member, reference = entries[choice.currentIndex()]
            previous = resolve_confirmation(self.project, reference)
            proof = previous["source_evidence"]
            label.setText(f'历史确认：{previous["confirmation"].get("actor")} · {previous["confirmation"].get("at", "")}\n源页 {proof.get("physical_page")} · 来源区域 {proof.get("source_uuid")}\n下方为已保存的历史裁片，不是本次重新读取。跨保存历史身份未证明，自动来源操作关闭。')
            pixmap = QPixmap(); pixmap.loadFromData(base64.b64decode(proof.get("png_base64", "")))
            crop.setPixmap(pixmap.scaled(430, 410, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            reread.setEnabled(member is not None and self.member.findData(member) >= 0 and self.source.findData(proof.get("source_uuid")) >= 0)

        def use_region():
            member, reference = entries[choice.currentIndex()]
            proof = resolve_confirmation(self.project, reference)["source_evidence"]
            self.member.setCurrentIndex(self.member.findData(member))
            self.source.blockSignals(True)
            self.source.setCurrentIndex(self.source.findData(proof["source_uuid"]))
            self.source.blockSignals(False)
            self.show_source()
            # This explicit navigation is still only a new evidence preview.
            dialog.accept()

        choice.currentIndexChanged.connect(lambda: self.run(show))
        reread.clicked.connect(lambda: self.run(use_region))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        show(); dialog.exec()

    def save_as(self):
        project = self.draft()
        path, _ = QFileDialog.getSaveFileName(self, "另存当前工程", "", "Image to CAD (*.icreview)")
        if path:
            if Path(path).exists():
                raise ValueError("请选未使用的文件名")
            project.save(path); self.project = project; self.populate()

    def undo(self):
        project = self.draft(); project.undo(); project.save()
        self.project = project; self.populate()

    def export(self):
        project = self.draft()
        directory = QFileDialog.getExistingDirectory(self, "选择空的导出目录")
        if directory:
            path = project.export(directory); project.save()
            self.project = project; self.populate()
            self.status.setText(self.status.text() + f"\n已导出 {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?")
    parser.add_argument("--actor", choices=["HUMAN_REVIEWED", "AGENT_REVIEWED"], default="HUMAN_REVIEWED")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    window = ProjectWindow(args.project, actor=args.actor); window.show()
    app.exec()


if __name__ == "__main__":
    main()
