"""P19-A focused checks. All simulated confirmations are QA_TEST_ONLY."""

from copy import deepcopy
import os
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.core import manual_text_recovery as manual
from app.core.processing import (
    ProductionProcessingConfig,
    build_processing_cache_key,
    file_content_sha256,
)
from app.core.review_project import ConfirmationEvent, ReviewProject, ReviewProjectError
from app.core.structure_build import build_final_structure
from app.geometry.raster_trace import trace_binary
from app.geometry.line_detect import LineSegment
from app.ocr.auxiliary_recognition import TextCandidate
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming
from app.export.text_consistency import TextConsistencyError, TextConsistencyGuard


@pytest.fixture
def project(tmp_path):
    app = QApplication.instance() or QApplication([])
    binary = np.full((1000, 1000), 255, np.uint8)
    cv2.putText(binary, "1", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2, cv2.LINE_8)
    frame = binary.copy()
    cv2.putText(frame, "7", (130, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2, cv2.LINE_8)
    source = tmp_path / "QA_TEST_ONLY.png"
    cv2.imwrite(str(source), frame)
    structure = build_final_structure(
        source_size_px=(1000, 1000),
        contour_binary=binary,
        contours=tuple(trace_binary(binary)),
        straight_lines=(LineSegment(20, 150, 300, 150),),
        texts=(
            TextCandidate(
                "7",
                (130, 55, 20, 30),
                0.99,
                "text_candidate",
                source="QA_TEST_ONLY",
                replacement_safe=False,
            ),
        ),
        source_text_outline_mask=np.zeros_like(binary),
        uncertain_text_outline_mask=np.zeros_like(binary),
    )
    key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(source),
        page_index=None,
        config=ProductionProcessingConfig(),
    )
    p = ReviewProject.create(
        structure,
        source_path=source,
        cache_key=key.payload(),
        frame=frame,
        origin="QA_TEST_ONLY P19A",
    )
    yield p
    p.close()
    app.processEvents()


def confirm(p, content="1", selection=None, authorize=True, identity=None):
    selection = selection or [45, 50, 35, 40]
    proposal = manual.suggest(p, selection, content)
    record = manual.confirm(
        p,
        selection=selection,
        content=content,
        parameters=proposal["parameters"],
        manual_uuid=identity,
        source_hide_authorized=authorize,
        event=ConfirmationEvent.create(test_only=True),
    )
    return record


def layout(p, record):
    return manual.confirm(
        p,
        manual_uuid=record["manual_uuid"],
        action="CONFIRM_LAYOUT",
        event=ConfirmationEvent.create(test_only=True),
    )


def test_pending_layout_reopen_native_text_and_withdraw(project, tmp_path):
    p = project
    r = confirm(p)
    assert r["confirmation"]["kind"] == "QA_TEST_ONLY"
    assert r["content_transaction"]["state"] == "CONFIRMED"
    assert r["source_transaction"]["state"] == "VISIBLE_PENDING"
    p.export_dxf(tmp_path / "pending.dxf")
    assert [
        e.dxf.text
        for e in ezdxf.readfile(tmp_path / "pending.dxf").modelspace().query("TEXT")
    ] == ["7"]
    r = layout(p, r)
    assert r["source_transfer"] == "HIDDEN_FROZEN_BACKUP"
    p.save(tmp_path / "saved.icreview")
    p.export_dxf(tmp_path / "single.dxf")
    export_trace_document_streaming(
        [
            DocumentPage(
                1,
                None,
                (100.0, 100.0),
                final_structure=p.baseline,
                text_review=p.validated_review(),
            )
        ],
        tmp_path / "document.dxf",
    )
    for file in ("single.dxf", "document.dxf"):
        doc = ezdxf.readfile(tmp_path / file)
        texts = list(doc.modelspace().query("TEXT"))
        assert [e.dxf.text for e in texts] == ["7", "1"]
        assert not texts[0].has_xdata(manual.APPID)
        assert texts[1].get_xdata(manual.APPID)[5].value == "QA_TEST_ONLY"
        assert len(list(doc.modelspace().query("LINE"))) == 1
        backups = [
            e for e in doc.modelspace().query("LWPOLYLINE") if e.has_xdata(manual.APPID)
        ]
        assert len(backups) == 1
        assert doc.layers.get(backups[0].dxf.layer).is_frozen()
    opened = ReviewProject.open(tmp_path / "saved.icreview")
    try:
        assert opened.records == p.records
        assert (
            manual.confirm(
                opened,
                manual_uuid=r["manual_uuid"],
                action="CONFIRM_LAYOUT",
                event=ConfirmationEvent.create(test_only=True),
            )
            is None
        )
        count = len(opened.records)
        opened.add_records(opened.records)
        assert len(opened.records) == count
        manual.confirm(
            opened,
            manual_uuid=r["manual_uuid"],
            action="WITHDRAW",
            event=ConfirmationEvent.create(test_only=True),
        )
        opened.export_dxf(tmp_path / "withdrawn.dxf")
        doc = ezdxf.readfile(tmp_path / "withdrawn.dxf")
        assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["7"]
        assert all(
            not e.has_xdata(manual.APPID) for e in doc.modelspace().query("LWPOLYLINE")
        )
        opened.save(tmp_path / "withdrawn.icreview")
        code = "from app.core.review_project import ReviewProject;from app.core.manual_text_recovery import replay;p=ReviewProject.open(__import__('sys').argv[1]);assert all(r['source_transfer']=='RESTORED_VISIBLE' for r in replay(p).values());p.close()"
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path / "withdrawn.icreview")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    finally:
        opened.close()


@pytest.mark.parametrize(
    "content,authorize", [("17", True), ("1", False), ("版次 Rev.17", True)]
)
def test_multichar_or_no_authorization_keeps_source(
    project, tmp_path, content, authorize
):
    r = layout(project, confirm(project, content=content, authorize=authorize))
    assert r["source_transfer"] == "COEXISTING_OVERLAY"
    assert r["source_transaction"]["failure_reason"]
    project.export_dxf(tmp_path / "overlay.dxf")
    doc = ezdxf.readfile(tmp_path / "overlay.dxf")
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["7", content]
    assert all(
        not e.has_xdata(manual.APPID) for e in doc.modelspace().query("LWPOLYLINE")
    )


def test_partial_contact_duplicate_and_wrong_snapshot_are_refused_or_overlay(
    project, tmp_path
):
    p = project
    partial = manual.source_evidence(p, [58, 55, 7, 20])
    assert partial["state"] == "SAFE_OVERLAY_ONLY"
    r = confirm(p)
    with pytest.raises(ReviewProjectError, match="同一源区域"):
        confirm(p)
    assert len(p.records) == 1
    for key, value in [
        ("snapshot_uuid", str(uuid4())),
        ("snapshot_source", {**r["snapshot_source"], "physical_page": 2}),
        ("parameters", {**r["parameters"], "height": float("nan")}),
    ]:
        bad = deepcopy(r)
        bad[key] = value
        bad["event_uuid"] = str(uuid4())
        bad["manual_uuid"] = str(uuid4())
        with pytest.raises(ReviewProjectError):
            p.add_records([bad])
        assert len(p.records) == 1
    bad = deepcopy(r)
    bad["original_ocr_text"] = "fake"
    with pytest.raises(ReviewProjectError, match="OCR identity"):
        p.add_records([bad])


@pytest.mark.parametrize("tamper", ["content", "height", "identity", "backup"])
def test_atomic_manual_contract_rejects_bad_output(
    project, tmp_path, monkeypatch, tamper
):
    p = project
    layout(p, confirm(p))
    target = tmp_path / "good.dxf"
    p.export_dxf(target)
    before = target.read_bytes()
    original = TextConsistencyGuard.validate

    def broken(self, doc):
        e = next(e for e in doc.modelspace().query("TEXT") if e.has_xdata(manual.APPID))
        if tamper == "content":
            e.dxf.text = "wrong"
        elif tamper == "height":
            e.dxf.height *= 2
        elif tamper == "identity":
            e.set_xdata(manual.APPID, [(1000, "wrong")])
        else:
            b = next(
                e
                for e in doc.modelspace().query("LWPOLYLINE")
                if e.has_xdata(manual.APPID)
            )
            b.dxf.layer = "TRACE_CURVE"
        return original(self, doc)

    monkeypatch.setattr(TextConsistencyGuard, "validate", broken)
    with pytest.raises(TextConsistencyError):
        p.export_dxf(target)
    assert target.read_bytes() == before


def test_legacy_project_journal_and_new_journal_versions(project, tmp_path):
    path = tmp_path / "legacy-v1.icreview"
    project.save(path)
    with ZipFile(path) as z:
        assert (
            json.loads(z.read("project.json"))["format"] == "review-project-format-v1"
        )
        assert json.loads(z.read("corrections.json"))["format_version"] == 1
    confirm(project)
    project.save(tmp_path / "manual.icreview")
    with ZipFile(tmp_path / "manual.icreview") as z:
        assert (
            json.loads(z.read("project.json"))["format"] == "review-project-format-v1"
        )
        assert json.loads(z.read("corrections.json"))["format_version"] == 2
    opened = ReviewProject.open(path)
    opened.close()


def test_qa_gui_source_drag_and_separate_buttons(project, tmp_path):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from app.gui.manual_text_dialog import ManualTextDialog

    dialog = ManualTextDialog(project)
    dialog.show()
    QApplication.processEvents()
    dialog.nav_x.setValue(65)
    dialog.nav_y.setValue(70)
    dialog._locate()
    dialog.select_button.click()
    QApplication.processEvents()
    a = dialog.source_view.mapFromScene(QPointF(45, 50))
    b = dialog.source_view.mapFromScene(QPointF(80, 90))
    QTest.mousePress(dialog.source_view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(dialog.source_view.viewport(), b)
    QTest.mouseRelease(dialog.source_view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert dialog.selection is not None and abs(dialog.selection[0] - 45) <= 1
    dialog.text_edit.setText("1")
    dialog._suggest()
    dialog.hide_authorization.setChecked(True)
    dialog._confirm_content()
    assert len(dialog.project.records) == 1
    assert not dialog.layout_button.isEnabled()
    dialog._preview()
    from tests.test_review_async import wait_until, drain

    wait_until(lambda: dialog.layout_button.isEnabled())
    dialog._confirm_layout()
    assert len(dialog.project.records) == 2
    assert all(
        r["confirmation"]["kind"] == "QA_TEST_ONLY" for r in dialog.project.records
    )
    assert not project.records  # Dialog Cancel has no effect on the caller journal.
    dialog.reject()
    dialog.close()
    drain()


def test_same_cell_neighbor_table_and_touching_independent_structure(project, tmp_path):
    # A selection that also contains an existing 7 cannot transfer its source.
    evidence = manual.source_evidence(project, [45, 50, 115, 40])
    assert evidence["state"] == "SAFE_OVERLAY_ONLY"
    # A native table rule crosses this source selection even though its source
    # pixels are absent from contour_binary (the line already has its own owner).
    assert (
        manual.source_evidence(project, [45, 50, 35, 110])["state"]
        == "SAFE_OVERLAY_ONLY"
    )
    frame = project.frame.copy()
    cv2.line(frame, (60, 60), (180, 60), 0, 2)
    source = tmp_path / "QA_TEST_ONLY-connected.png"
    cv2.imwrite(str(source), frame)
    structure = build_final_structure(
        source_size_px=(1000, 1000),
        contour_binary=frame,
        contours=tuple(trace_binary(frame)),
        source_text_outline_mask=np.zeros_like(frame),
        uncertain_text_outline_mask=np.zeros_like(frame),
    )
    key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(source),
        page_index=None,
        config=ProductionProcessingConfig(),
    )
    p = ReviewProject.create(
        structure,
        source_path=source,
        cache_key=key.payload(),
        frame=frame,
        origin="QA_TEST_ONLY contact",
    )
    try:
        r = layout(p, confirm(p))
        assert r["source_transfer"] == "COEXISTING_OVERLAY"
        assert r["content_transaction"]["state"] == "CONFIRMED"
        p.export_dxf(tmp_path / "connected-overlay.dxf")
        d = ezdxf.readfile(tmp_path / "connected-overlay.dxf")
        assert [e.dxf.text for e in d.modelspace().query("TEXT")] == ["1"]
        assert all(
            not e.has_xdata(manual.APPID) for e in d.modelspace().query("LWPOLYLINE")
        )
    finally:
        p.close()


def test_reconfirm_existing_content_refreshes_pending_actual_cad(project):
    from app.core.preview import render_final_structure_preview
    from app.gui.manual_text_dialog import ManualTextDialog
    from app.gui.ocr_review import _image_pixmap

    original = layout(project, confirm(project))
    dialog = ManualTextDialog(project)
    dialog._load_record(0)
    assert dialog.manual_uuid == original["manual_uuid"]
    dialog.text_edit.setText("17")
    dialog._suggest()
    dialog._confirm_content()
    active = manual.replay(dialog.project)[original["manual_uuid"]]
    assert (
        active["action"] == "CONFIRM_CONTENT" and active["layout_confirmation"] is None
    )
    assert active["content"] == "17" and dialog.manual_uuid == original["manual_uuid"]
    from tests.test_review_async import wait_until, drain

    wait_until(lambda: dialog._preview_client.ready)
    # Pending content emits no manual TEXT: preserve the pre-confirmation baseline expectation.
    pending_expected = render_final_structure_preview(
        project.baseline,
        roi=dialog._displayed_roi,
        output_scale=dialog._displayed_density,
    )
    actual = (
        next(item for item in dialog.cad_scene.items() if hasattr(item, "pixmap"))
        .pixmap()
        .toImage()
    )
    assert actual == _image_pixmap(pending_expected).toImage()
    assert not dialog.layout_button.isEnabled()
    dialog.reject()
    dialog.close()
    drain()


def test_v2_manifest_accepts_manual_journal2_in_new_process(tmp_path):
    from tests.test_native_text_review import pdf_source, extract, make_project

    app = QApplication.instance() or QApplication([])
    source = pdf_source(tmp_path)
    frame, evidence = extract(source)
    p = make_project(source, frame, evidence)
    try:
        assert p.manifest["format"] == "review-project-format-v2"
        row = next(r for r in evidence["rows"] if r["layout_eligible"])
        x0, y0, x1, y1 = row["bounds"]
        selection = [int(x0) - 1, int(y0) - 1, int(x1 - x0) + 3, int(y1 - y0) + 3]
        r = layout(p, confirm(p, content="17", selection=selection))
        assert r["source_transfer"] == "COEXISTING_OVERLAY"
        path = tmp_path / "v2-manual.icreview"
        p.save(path)
        with ZipFile(path) as z:
            assert (
                json.loads(z.read("project.json"))["format"]
                == "review-project-format-v2"
            )
            assert json.loads(z.read("corrections.json"))["format_version"] == 2
        code = "from app.core.review_project import ReviewProject;from app.core.manual_text_recovery import replay;p=ReviewProject.open(__import__('sys').argv[1]);assert p.manifest['format']=='review-project-format-v2';assert list(replay(p).values())[0]['content']=='17';p.close()"
        result = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
    finally:
        p.close()
        app.processEvents()


def test_withdraw_unselected_warns_and_withdrawn_is_idempotent(project, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.gui.manual_text_dialog import ManualTextDialog

    r = layout(project, confirm(project))
    manual.confirm(
        project,
        manual_uuid=r["manual_uuid"],
        action="WITHDRAW",
        event=ConfirmationEvent.create(test_only=True),
    )
    dialog = ManualTextDialog(project)
    before = deepcopy(dialog.project.records)
    messages = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: messages.append(message)
    )
    dialog._withdraw()
    assert messages == ["请先选择一条已补录记录，再撤回。"]
    assert dialog.project.records == before
    assert "已撤回" not in dialog.state_label.text()
    dialog._load_record(0)
    dialog._withdraw()
    assert dialog.state_label.text() == "该记录已撤回；未增加修订。"
    assert dialog.project.records == before
    dialog.reject()
    dialog.close()


def test_withdraw_current_preview_reaches_ready_and_restores_source(project, tmp_path):
    from app.core.preview import render_final_structure_preview
    from app.gui.manual_text_dialog import ManualTextDialog
    from app.gui.ocr_review import _image_pixmap
    from tests.test_review_async import wait_until, drain

    original = layout(project, confirm(project))
    dialog = ManualTextDialog(project)
    dialog._load_record(0)
    dialog._withdraw()
    active = manual.replay(dialog.project)[original["manual_uuid"]]
    assert (
        active["action"] == "WITHDRAW"
        and active["source_transfer"] == "RESTORED_VISIBLE"
    )
    wait_until(lambda: dialog._preview_client.ready)
    # Withdrawal restores the source contour and removes the manual TEXT.
    expected = render_final_structure_preview(
        project.baseline,
        roi=dialog._displayed_roi,
        output_scale=dialog._displayed_density,
    )
    actual = (
        next(item for item in dialog.cad_scene.items() if hasattr(item, "pixmap"))
        .pixmap()
        .toImage()
    )
    assert actual == _image_pixmap(expected).toImage()
    assert "ROI" in dialog.preview_status.text()
    assert not dialog.layout_button.isEnabled()
    output = tmp_path / "QA_TEST_ONLY-withdraw-ready.dxf"
    dialog.project.export_dxf(output)
    document = ezdxf.readfile(output)
    assert [entity.dxf.text for entity in document.modelspace().query("TEXT")] == ["7"]
    assert not any(
        entity.has_xdata(manual.APPID) for entity in document.modelspace().query("TEXT")
    )
    dialog.reject()
    dialog.close()
    drain()


def test_linked_manual_views_preserve_center_zoom_and_actual_properties(project):
    from app.gui.manual_text_dialog import ManualTextDialog
    from tests.test_review_async import wait_until, drain
    from PySide6.QtCore import QPointF

    original = layout(project, confirm(project))
    dialog = ManualTextDialog(project)
    dialog.show()
    wait_until(lambda: dialog._preview_client.ready)
    actual = dialog._preview_client.entities[original["manual_uuid"]]
    assert actual["content"] == "1" and actual["entity"] == "TEXT"
    assert (
        actual["layer"].endswith("_MANUAL")
        and actual["source_transfer"] == "HIDDEN_FROZEN_BACKUP"
    )
    dialog.source_view.scale(1.22, 1.22)
    dialog.source_view.centerOn(QPointF(90, 85))
    dialog._sync_views(dialog.source_view, dialog.cad_view)
    wait_until(lambda: dialog._preview_client.ready)
    a = dialog.source_view.mapToScene(dialog.source_view.viewport().rect().center())
    b = dialog.cad_view.mapToScene(dialog.cad_view.viewport().rect().center())
    assert dialog.source_view.transform() == dialog.cad_view.transform()
    assert abs(a.x() - b.x()) < 1 and abs(a.y() - b.y()) < 1
    assert not dialog._viewport_timer.isActive()
    dialog.reject()
    drain()
