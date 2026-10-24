"""P13-E string-only review contract. Every simulated event is TEST_ONLY."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.core.processing import (
    ProductionProcessingConfig,
    build_processing_cache_key,
    file_content_sha256,
)
from app.core.review_project import ConfirmationEvent, ReviewProject, ReviewProjectError
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.ocr.auxiliary_recognition import TextCandidate


@pytest.fixture
def project(tmp_path):
    app = QApplication.instance() or QApplication([])
    frame = np.full((150, 320), 255, np.uint8)
    source = tmp_path / "TEST_ONLY-source.png"
    cv2.imwrite(str(source), frame)
    texts = tuple(
        TextCandidate(
            "ALPHA",
            box,
            0.99,
            "text_candidate",
            source="TEST_ONLY",
            replacement_safe=False,
        )
        for box in ((20, 30, 80, 20), (200, 30, 80, 20))
    )
    structure = build_final_structure(
        source_size_px=(320, 150),
        contour_binary=frame,
        contours=(),
        straight_lines=(LineSegment(10, 100, 300, 100),),
        texts=texts,
        editable_text_source_mask=np.zeros_like(frame),
        source_text_outline_mask=np.zeros_like(frame),
        uncertain_text_outline_mask=np.zeros_like(frame),
    )
    key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(source),
        page_index=None,
        config=ProductionProcessingConfig(),
    )
    review = ReviewProject.create(
        structure,
        source_path=source,
        cache_key=key.payload(),
        frame=frame,
        origin="TEST_ONLY constructed conversion",
    )
    yield review
    review.close()
    app.processEvents()


def _confirm(project, content="ALP", index=0, **kwargs):
    return project.confirm(
        project.bindings[index]["text_source_uuid"],
        content,
        event=ConfirmationEvent.create(test_only=True),
        **kwargs,
    )


def _texts(path):
    return list(ezdxf.readfile(path).modelspace().query("TEXT"))


def _attributes(entity):
    return {
        k: entity.dxf.get(k)
        for k in (
            "insert",
            "height",
            "width",
            "rotation",
            "halign",
            "valign",
            "style",
            "layer",
        )
    }


def _rewrite(path, name, transform):
    with ZipFile(path) as archive:
        entries = {n: archive.read(n) for n in archive.namelist()}
    entries[name] = transform(entries[name])
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for n, value in entries.items():
            archive.writestr(n, value)


def test_snapshot_original_uuid_and_real_text_consumer(project, tmp_path):
    project.export_dxf(tmp_path / "before.dxf")
    original = project.baseline
    before = _texts(tmp_path / "before.dxf")
    record = _confirm(project)
    assert record["status"] == "TEST_ONLY" and record["consumption"] == "APPLIED"
    project.export_dxf(tmp_path / "after.dxf")
    after = _texts(tmp_path / "after.dxf")
    assert [e.dxf.text for e in after] == ["ALP", "ALPHA"]
    assert project.baseline is original
    assert [t.text for t in original.texts] == ["ALPHA", "ALPHA"]
    assert (
        project.bindings[0]["text_source_uuid"]
        != project.bindings[1]["text_source_uuid"]
    )
    for a, b in zip(before, after):
        assert _attributes(a) == _attributes(b)
    assert after[0].get_xdata("OCR_TEXT_LINE")[1].value == "ALP"
    assert (
        after[0].get_xdata("OCR_TEXT_LINE")[3].value == 0
    )  # TEST_ONLY is not a real human review.
    assert after[0].get_xdata("TEXT_OUTPUT_CONTRACT")[-1].value == 0
    tags = [t.value for t in after[0].get_xdata("TEXT_REVIEW")]
    assert "TEST_ONLY" in tags and "ALPHA" in tags and project.snapshot_uuid in tags
    geometry = [
        t.value for t in after[0].get_xdata("OCR_TEXT_GEOMETRY") if t.code == 1040
    ]
    old_geometry = [
        t.value for t in before[0].get_xdata("OCR_TEXT_GEOMETRY") if t.code == 1040
    ]
    assert geometry[4] < old_geometry[4]
    assert all(
        not np.any(m)
        for m in (
            original.editable_text_source_mask,
            original.source_text_outline_mask,
            original.uncertain_text_outline_mask,
        )
    )
    doc = ezdxf.readfile(tmp_path / "after.dxf")
    audit = doc.audit()
    assert not audit.errors and not audit.fixes
    assert len(doc.modelspace().query("LINE")) == 1


def test_repeat_record_export_idempotence_and_noop_save(project, tmp_path):
    record = _confirm(project)
    project.add_records([record, record])
    assert len(project.records) == 1
    assert _confirm(project) is None
    path = tmp_path / "saved.icreview"
    project.save(path)
    project.save(path)
    assert len(project.records) == 1 and not project.dirty
    for index in range(2):
        project.export_dxf(tmp_path / f"same-{index}.dxf")
    for a, b in zip(_texts(tmp_path / "same-0.dxf"), _texts(tmp_path / "same-1.dxf")):
        assert a.dxfattribs() == b.dxfattribs()
        assert list(a.get_xdata("TEXT_REVIEW")) == list(b.get_xdata("TEXT_REVIEW"))


def test_revision_conflict_is_atomic(project):
    record = _confirm(project)
    conflicting = deepcopy(record)
    conflicting["new_text"] = "OTHER"
    with pytest.raises(ReviewProjectError, match="Conflicting"):
        project.add_records([conflicting])
    assert project.records == [record]


@pytest.mark.parametrize(
    "field",
    [
        "snapshot_uuid",
        "text_source_uuid",
        "document",
        "page",
        "config",
        "ocr",
        "geometry",
        "ownership",
    ],
)
def test_wrong_identity_rejected(project, field):
    record = _confirm(project)
    bad = deepcopy(record)
    if field in {"snapshot_uuid", "text_source_uuid"}:
        bad[field] = str(uuid4())
    elif field == "document":
        bad["snapshot_source"]["document_uuid"] = str(uuid4())
    elif field == "page":
        bad["snapshot_source"]["physical_page"] = 2
    elif field == "config":
        bad["snapshot_source"]["cache_identity"]["dpi"] += 1
    elif field == "ocr":
        bad["binding"]["original_candidate"]["text"] = "OTHER"
    elif field == "geometry":
        bad["binding"]["original_candidate"]["bbox"][0] += 1
    else:
        bad["binding"]["original_candidate"]["replacement_safe"] = True
    draft = project.draft()
    draft._records = []
    with pytest.raises(ReviewProjectError, match="IDENTITY_MISMATCH"):
        draft.add_records([bad])
    assert draft.records == []


def test_new_conversion_rejects_old_record_even_identical_source(project):
    record = _confirm(project)
    baseline = replace(project.baseline, provenance={})
    other = ReviewProject.create(
        baseline,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
    )
    try:
        assert other.snapshot_uuid != project.snapshot_uuid
        with pytest.raises(ReviewProjectError, match="IDENTITY_MISMATCH"):
            other.add_records([record])
        from app.export.trace_single_export import export_final_structure_dxf

        with pytest.raises(ReviewProjectError, match="NEEDS_RECONFIRM"):
            export_final_structure_dxf(
                other.baseline,
                "must-not-exist.dxf",
                text_review=project.validated_review(),
            )
    finally:
        other.close()


def test_long_proposal_held_previous_output_preserved_and_withdrawal(project, tmp_path):
    first = _confirm(project)
    second = _confirm(project, "ALPHA VERY LONG TEST_ONLY STRING")
    assert second["status"] == "NEEDS_LAYOUT_REVIEW" and second["consumption"] == "HELD"
    u = project.bindings[0]["text_source_uuid"]
    assert (
        project.current_text(u) == "ALP"
    )  # A rejected proposal cannot undo the last safe edit.
    assert _confirm(project, second["new_text"]) is None
    project.export_dxf(tmp_path / "held.dxf")
    assert _texts(tmp_path / "held.dxf")[0].dxf.text == "ALP"
    withdrawn = _confirm(project, withdraw=True)
    assert withdrawn["revision"] == 3 and withdrawn["action"] == "WITHDRAW"
    project.export_dxf(tmp_path / "withdrawn.dxf")
    assert [e.dxf.text for e in _texts(tmp_path / "withdrawn.dxf")] == [
        "ALPHA",
        "ALPHA",
    ]
    assert "WITHDRAWN" in [
        t.value for t in _texts(tmp_path / "withdrawn.dxf")[0].get_xdata("TEXT_REVIEW")
    ]
    assert project.records[0] == first
    project.save(tmp_path / "withdrawn.icreview")
    reopened = ReviewProject.open(tmp_path / "withdrawn.icreview")
    try:
        assert len(reopened.records) == 3 and reopened.current_text(u) == "ALPHA"
    finally:
        reopened.close()


def test_layout_neighbor_and_missing_glyph_fail_closed(project, monkeypatch):
    from app.export.review_text import polygon

    guard = project.guard
    obstacle = polygon([(20, 100), (100, 100), (100, 120), (20, 120)])
    guard.obstacles.append((None, obstacle, obstacle.boundingRect()))
    assert _confirm(project)["status"] == "NEEDS_LAYOUT_REVIEW"
    guard.obstacles.pop()
    assert _confirm(project, "\U0010ffff")["status"] == "NEEDS_LAYOUT_REVIEW"
    assert _confirm(project, "A\nB")["status"] == "NEEDS_LAYOUT_REVIEW"


@pytest.mark.parametrize("angle", [90, 30, 270])
def test_rotated_text_keeps_geometry(project, tmp_path, angle):
    from tests.test_native_text_geometry import _source_quad

    quad = _source_quad(center=(160, 280), width=80, height=20, rotation=angle)
    candidate = replace(
        project.baseline.texts[0],
        bbox=(100, 20, 100, 110),
        quad=quad,
        rotation_deg=angle,
    )
    baseline = replace(
        project.baseline, texts=(candidate,), straight_lines=(), provenance={}
    )
    other = ReviewProject.create(
        baseline,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
    )
    try:
        other.export_dxf(tmp_path / "before.dxf")
        assert _confirm(other)["consumption"] == "APPLIED"
        other.export_dxf(tmp_path / "after.dxf")
        assert _attributes(_texts(tmp_path / "before.dxf")[0]) == _attributes(
            _texts(tmp_path / "after.dxf")[0]
        )
    finally:
        other.close()


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_source_unavailable_or_version_changed(project, tmp_path, mutation):
    path = tmp_path / "source-check.icreview"
    project.save(path)
    source = Path(project.manifest["source"]["path"])
    if mutation == "missing":
        source.unlink()
    else:
        data = source.read_bytes()
        source.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(ReviewProjectError):
        project.export_dxf(tmp_path / "blocked.dxf")
    assert not (tmp_path / "blocked.dxf").exists()
    with pytest.raises(ReviewProjectError):
        ReviewProject.open(path)


@pytest.mark.parametrize(
    "mutation", ["incomplete", "format", "page", "snapshot", "payload"]
)
def test_corrupt_project_rejected(project, tmp_path, mutation):
    path = tmp_path / "corrupt.icreview"
    project.save(path)
    if mutation == "incomplete":
        path.write_bytes(path.read_bytes()[:100])
    elif mutation == "payload":

        def change_cache(data):
            with np.load(BytesIO(data), allow_pickle=False) as archive:
                values = {k: archive[k] for k in archive.files}
            texts = json.loads(str(values["texts_json"].reshape(-1)[0]))
            texts[0]["text"] = "TAMPERED"
            values["texts_json"] = np.asarray([json.dumps(texts)], dtype=str)
            result = BytesIO()
            np.savez(result, **values)
            return result.getvalue()

        _rewrite(path, "snapshot.npz", change_cache)
    else:

        def change_manifest(data):
            value = json.loads(data)
            if mutation == "format":
                value["format"] = "future"
            elif mutation == "page":
                value["source"]["physical_page"] = 2
            else:
                value["snapshot_uuid"] = str(uuid4())
            return json.dumps(value).encode()

        _rewrite(path, "project.json", change_manifest)
    with pytest.raises(ReviewProjectError):
        ReviewProject.open(path)


def test_failed_atomic_save_preserves_previous(project, tmp_path, monkeypatch):
    path = tmp_path / "atomic.icreview"
    project.save(path)
    old_bytes = path.read_bytes()
    _confirm(project)
    monkeypatch.setattr(
        os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("TEST_ONLY save failure")),
    )
    with pytest.raises(OSError):
        project.save(path)
    assert path.read_bytes() == old_bytes and project.dirty
    assert not list(tmp_path.glob(".atomic.icreview.*.tmp"))


def test_close_new_process_formal_export_and_dxf_edit_readback(project, tmp_path):
    _confirm(project)
    path = tmp_path / "persistent.icreview"
    project.save(path)
    u = project.bindings[0]["text_source_uuid"]
    project.close()
    code = """
from pathlib import Path
import sys,ezdxf
from app.core.review_project import ReviewProject
p=ReviewProject.open(sys.argv[1]); p.export_dxf(sys.argv[2]); p.close()
d=ezdxf.readfile(sys.argv[2]); a=d.audit(); assert not a.errors and not a.fixes
t=list(d.modelspace().query('TEXT')); assert [e.dxf.text for e in t]==['ALP','ALPHA']
assert sys.argv[3] in [v.value for v in t[0].get_xdata('TEXT_REVIEW')]
t[0].dxf.text='AL'; d.saveas(sys.argv[4])
"""
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            code,
            str(path),
            str(tmp_path / "formal.dxf"),
            u,
            str(tmp_path / "external-edit-TEST_ONLY.dxf"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    code2 = """
import ezdxf,sys
d=ezdxf.readfile(sys.argv[1]); t=list(d.modelspace().query('TEXT'))
assert [e.dxf.text for e in t]==['AL','ALPHA']; assert len(d.modelspace().query('LINE'))==1
assert t[0].has_xdata('TEXT_REVIEW'); a=d.audit(); assert not a.errors and not a.fixes
"""
    result = subprocess.run(
        [sys.executable, "-c", code2, str(tmp_path / "external-edit-TEST_ONLY.dxf")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_gui_explicit_confirm_cancel_save_open_and_formal_worker(
    project, tmp_path, monkeypatch
):
    from app.gui import MainWindow
    from app.gui.review_project_dialog import SnapshotTextReviewDialog
    from app.gui.review_project_actions import (
        open_review_project_from_path,
        save_review_project_to,
        _refresh_review_project,
    )
    from app.gui import export_worker

    project.save(tmp_path / "gui.icreview")
    window = MainWindow()
    open_review_project_from_path(window, tmp_path / "gui.icreview")
    dialog = SnapshotTextReviewDialog(window._review_project, window, test_only=True)
    dialog.text_edit.setText("ALP")
    assert not dialog.project.records and not window._review_project.records
    dialog.reject()
    dialog = SnapshotTextReviewDialog(window._review_project, window, test_only=True)
    dialog.text_edit.setText("ALP")
    dialog._apply_current_text()
    assert dialog.project.records[0]["confirmation"]["kind"] == "TEST_ONLY"
    dialog.text_edit.setText("UNCONFIRMED")
    dialog.accept()
    window._review_project.add_records(dialog.project.records)
    _refresh_review_project(window)
    assert window._review_project.dirty and window.isWindowModified()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(
        export_worker,
        "_select_output_path",
        lambda *a, **k: (tmp_path / "gui-formal.dxf", False),
    )
    window._start_processing = lambda *args: pytest.fail(
        "Unsaved review must not export"
    )
    export_worker._start_single_export(window)
    save_review_project_to(window, tmp_path / "gui.icreview")
    assert not window.isWindowModified()
    from app.core.cancellation import CancellationToken

    def run(operation, completed, _message):
        completed(operation(CancellationToken(), lambda *a: None))

    window._start_processing = run
    export_worker._start_single_export(window)
    assert [e.dxf.text for e in _texts(tmp_path / "gui-formal.dxf")] == ["ALP", "ALPHA"]
    window.close()
    reopened = MainWindow()
    open_review_project_from_path(reopened, tmp_path / "gui.icreview")
    assert (
        reopened._review_project.current_text(
            reopened._review_project.bindings[0]["text_source_uuid"]
        )
        == "ALP"
    )
    reopened.close()


def test_unchanged_confirmation_does_not_forge_review(project):
    assert _confirm(project, "ALPHA") is None
    assert not project.records


def test_normal_gui_completion_review_entry_and_snapshot_save(
    project, tmp_path, monkeypatch
):
    from app.gui import MainWindow
    from app.gui import processing, review_project_actions
    from app.core.review_project import _trace_result
    from app.core.cancellation import CancellationToken

    baseline = replace(project.baseline, provenance={})
    window = MainWindow()
    window.current_path = Path(project.manifest["source"]["path"])
    window.original_image = project.frame.copy()
    window.corrected_image = project.frame.copy()
    # Test conversion result is constructed; no OCR quality claim is made.
    monkeypatch.setattr(
        processing.ProductionProcessingService,
        "process_page",
        lambda *a, **k: _trace_result(baseline),
    )
    window._start_processing = lambda operation, completed, _: completed(
        operation(CancellationToken(), lambda *a: None)
    )
    window.detect_and_clean()
    assert window._completed_trace_key == window._current_trace_key()
    from app.gui.review_project_dialog import SnapshotTextReviewDialog

    class TestDialog(SnapshotTextReviewDialog):
        def __init__(self, p, parent):
            super().__init__(p, parent, test_only=True)

        def exec(self):
            self.text_edit.setText("ALP")
            self._apply_current_text()
            self.accept()
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(review_project_actions, "SnapshotTextReviewDialog", TestDialog)
    window.review_ocr_texts()
    assert window._review_project.records[0]["status"] == "TEST_ONLY"
    review_project_actions.save_review_project_to(
        window, tmp_path / "normal-entry.icreview"
    )
    assert not window._review_project.dirty
    window._review_project.export_dxf(tmp_path / "normal-entry.dxf")
    assert _texts(tmp_path / "normal-entry.dxf")[0].dxf.text == "ALP"
    window.close()


def test_snapshot_save_rejects_changed_conversion_settings(
    project, tmp_path, monkeypatch
):
    from app.gui import MainWindow
    from app.gui.review_project_actions import save_review_project_to
    from app.core.processing import ProductionProcessingConfig

    window = MainWindow()
    window.current_path = Path(project.manifest["source"]["path"])
    window.corrected_image = project.frame.copy()
    window._final_structure = replace(project.baseline, provenance={})
    window._completed_trace_key = window._current_trace_key()
    monkeypatch.setattr(
        window,
        "_processing_config",
        lambda *a, **k: ProductionProcessingConfig(enable_ocr=False),
    )
    with pytest.raises(ReviewProjectError, match="NEEDS_RECONFIRM"):
        save_review_project_to(window, tmp_path / "changed-config.icreview")
    assert not (tmp_path / "changed-config.icreview").exists()
    window.close()


def test_review_guard_measures_image_and_native_arc_without_changing_them(
    project, tmp_path
):
    from app.ocr.logo_detection import LogoRegion
    from app.core.arc_types import ArcSegment

    logo = LogoRegion((240, 90, 20, 20), np.full((20, 20), 255, np.uint8), 0.9, 0, 1)
    arc = ArcSegment("TEST_ONLY_arc", (170, 110), 10, 0, 90)
    base = replace(project.baseline, provenance={}, logos=(logo,), arcs=(arc,))
    other = ReviewProject.create(
        base,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
    )
    try:
        assert _confirm(other)["consumption"] == "APPLIED"
        other.export_dxf(tmp_path / "images-arcs.dxf")
        doc = ezdxf.readfile(tmp_path / "images-arcs.dxf")
        assert len(doc.modelspace().query("IMAGE")) == 1
        assert len(doc.modelspace().query("ARC")) == 1
        assert other.baseline.arcs == (arc,)
        np.testing.assert_array_equal(other.baseline.logos[0].mask, logo.mask)
    finally:
        other.close()


def test_calibrated_snapshot_preserves_units_after_reopen(project, tmp_path):
    from app.core.scale_calibrator import ScaleCalibration

    base = replace(project.baseline, provenance={})
    other = ReviewProject.create(
        base,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
        calibration=ScaleCalibration((0.0, 0.0), (100.0, 0.0), 10.0),
    )
    try:
        _confirm(other)
        other.save(tmp_path / "paper-mm.icreview")
        reopened = ReviewProject.open(tmp_path / "paper-mm.icreview")
        try:
            reopened.export_dxf(tmp_path / "paper-mm.dxf")
            assert reopened.calibration.mm_per_pixel == 0.1
            assert ezdxf.readfile(tmp_path / "paper-mm.dxf").units == 4
            assert _texts(tmp_path / "paper-mm.dxf")[0].dxf.height == 2.0
        finally:
            reopened.close()
    finally:
        other.close()


def test_source_and_temporary_paths_cannot_be_overwritten(project):
    source = Path(project.manifest["source"]["path"])
    original = source.read_bytes()
    with pytest.raises(ReviewProjectError):
        project.save(source)
    with pytest.raises(ReviewProjectError):
        project.export_dxf(source)
    with pytest.raises(ReviewProjectError):
        project.save(project._cache_path.parent / "temporary.icreview")
    assert source.read_bytes() == original


def test_original_raw_ocr_and_current_normalized_string_are_separate(project, tmp_path):
    candidate = replace(project.baseline.texts[0], text=" ALPHA  ")
    base = replace(project.baseline, provenance={}, texts=(candidate,))
    other = ReviewProject.create(
        base,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
    )
    try:
        assert other.current_text(other.bindings[0]["text_source_uuid"]) == "ALPHA"
        assert _confirm(other, "ALPHA") is None
        record = _confirm(other)
        assert (
            record["original_ocr_text"] == " ALPHA  "
            and record["expected_before"] == "ALPHA"
        )
        _confirm(other, withdraw=True)
        other.export_dxf(tmp_path / "raw-ocr.dxf")
        assert _texts(tmp_path / "raw-ocr.dxf")[0].dxf.text == "ALPHA"
        assert other.baseline.texts[0].text == " ALPHA  "
    finally:
        other.close()


def test_candidate_order_is_not_emitted_text_order(project, tmp_path):
    base = replace(
        project.baseline, provenance={}, texts=tuple(reversed(project.baseline.texts))
    )
    other = ReviewProject.create(
        base,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
    )
    try:
        assert _confirm(other)["consumption"] == "APPLIED"
        other.export_dxf(tmp_path / "ordered.dxf")
        entities = _texts(tmp_path / "ordered.dxf")
        assert [e.dxf.text for e in entities] == ["ALPHA", "ALP"]
        assert other.bindings[0]["text_source_uuid"] in [
            v.value for v in entities[1].get_xdata("TEXT_REVIEW")
        ]
    finally:
        other.close()


def test_changed_font_placement_is_rejected_before_reopen(
    project, tmp_path, monkeypatch
):
    from app.core import review_project

    project.save(tmp_path / "font.icreview")
    original = review_project._native_fact

    def changed(candidate, height):
        value = original(candidate, height)
        value["geometry"]["width_factor"] += 0.1
        return value

    monkeypatch.setattr(review_project, "_native_fact", changed)
    with pytest.raises(ReviewProjectError, match="font metrics changed"):
        ReviewProject.open(tmp_path / "font.icreview")


def test_incomplete_journal_record_is_rejected(project, tmp_path):
    path = tmp_path / "incomplete-journal.icreview"
    project.save(path)

    def change(data):
        value = json.loads(data)
        value["records"] = ["not a versioned correction object"]
        return json.dumps(value).encode()

    _rewrite(path, "corrections.json", change)
    original_bytes = path.read_bytes()
    original_records = project.records
    with pytest.raises(ReviewProjectError, match="Invalid correction record"):
        ReviewProject.open(path)
    assert path.read_bytes() == original_bytes
    assert project.records == original_records


@pytest.mark.parametrize("journal", [[], {"records": "invalid"}, {"records": [None]}])
def test_invalid_journal_container_is_rejected_without_writing(
    project, tmp_path, journal
):
    path = tmp_path / "invalid-journal.icreview"
    project.save(path)
    _rewrite(path, "corrections.json", lambda data: json.dumps(journal).encode())
    original_bytes = path.read_bytes()
    original_records = project.records
    with pytest.raises(ReviewProjectError, match="Invalid correction record"):
        ReviewProject.open(path)
    assert path.read_bytes() == original_bytes
    assert project.records == original_records


def test_confirmed_held_proposal_is_not_presented_as_unconfirmed_input(
    project, tmp_path
):
    """P13-F native UAT: a confirmed suggestion must remain visibly distinct from typing."""
    from app.gui.review_project_dialog import SnapshotTextReviewDialog

    dialog = SnapshotTextReviewDialog(project, test_only=True)
    dialog.text_edit.setText("ALP")
    dialog._apply_current_text()
    proposal = "TEST ONLY LONG PROPOSAL THAT CANNOT FIT THE ORIGINAL DISPLAY REGION"
    dialog.text_edit.setText(proposal)
    dialog._apply_current_text()
    assert dialog.project.records[-1]["consumption"] == "HELD"
    assert "已确认，未应用" in dialog.confidence_label.text()
    assert "新文字超出原TEXT合法显示范围" in dialog.confidence_label.text()
    assert "输入尚未确认" not in dialog.confidence_label.text()
    assert dialog.project.current_text(project.bindings[0]["text_source_uuid"]) == "ALP"
    dialog.text_edit.setText("ANOTHER UNCONFIRMED PROPOSAL")
    assert "输入尚未确认" in dialog.confidence_label.text()
    assert len(dialog.project.records) == 2
    dialog._reset_input()
    assert dialog.text_edit.text() == "ALP"
    dialog.accept()
    project.add_records(dialog.project.records)
    project.save(tmp_path / "held-feedback.icreview")
    reopened = ReviewProject.open(tmp_path / "held-feedback.icreview")
    try:
        view = SnapshotTextReviewDialog(reopened, test_only=True)
        assert "已确认，未应用" in view.confidence_label.text()
        assert "输入尚未确认" not in view.confidence_label.text()
        assert view.text_edit.text() == "ALP"
        reopened.export_dxf(tmp_path / "held-feedback.dxf")
        assert [e.dxf.text for e in _texts(tmp_path / "held-feedback.dxf")] == [
            "ALP",
            "ALPHA",
        ]
        assert len(reopened.records) == 2
        view.reject()
    finally:
        reopened.close()
