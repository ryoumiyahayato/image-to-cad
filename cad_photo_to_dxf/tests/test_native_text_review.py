"""P13-I: all constructed sources and confirmation events are QA_TEST_ONLY."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.core.image_loader import load_image
from app.core.processing import (
    ProductionProcessingConfig,
    build_processing_cache_key,
    file_content_sha256,
)
from app.core.review_project import ConfirmationEvent, ReviewProject, ReviewProjectError
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.geometry.pdf_text_suggestions import SUGGESTION_KEY
from app.ocr.auxiliary_recognition import TextCandidate


def pdf_source(
    tmp_path,
    *,
    prefix="",
    suffix="",
    content="Long source sentence",
    duplicate=False,
    wrong_mapping=False,
):
    # Tiny test source, not a production parser or an engineering correction.
    draw = f"BT /F1 12 Tf 1 0 0 1 30 100 Tm ({content}) Tj ET"
    stream = prefix + draw + (draw if duplicate else "") + suffix
    cmap = " /ToUnicode 6 0 R" if wrong_mapping else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 150] /Resources << /Font << /F1 4 0 R >> /ExtGState << /GS << /Type /ExtGState /ca 0 /CA 0 >> >> >> /Contents 5 0 R >>",
        (
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding"
            + cmap
            + " >>"
        ).encode(),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode(),
    ]
    if wrong_mapping:
        mapping = "/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Test) /Ordering (Test) /Supplement 0 >> def /CMapName /Test def /CMapType 2 def 1 begincodespacerange <00> <FF> endcodespacerange 1 beginbfchar <4C> <0058> endbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
        objects.append(
            f"<< /Length {len(mapping)} >>\nstream\n{mapping}\nendstream".encode()
        )
    data = b"%PDF-1.7\n"
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{v:010d} 00000 n \n".encode() for v in offsets[1:])
    data += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path = tmp_path / "QA_TEST_ONLY.pdf"
    path.write_bytes(data)
    return path


def extract(path):
    sink = []
    frame = load_image(path, pdf_dpi=72, grayscale=True, pdf_text_sink=sink)
    return frame, sink[0]


def make_project(
    path,
    frame,
    evidence,
    *,
    collision=False,
    duplicate_ocr=False,
    competing=False,
    split_ocr=False,
    partial_span=False,
):
    eligible = [r for r in evidence["rows"] if r["layout_eligible"]]
    assert eligible
    x0, y0, x1, y1 = eligible[0]["bounds"]
    box = (x0 - 2, y0 - 2, x1 - x0 + 4, y1 - y0 + 4)
    texts = [
        TextCandidate(
            "bad",
            box,
            0.99,
            "text_candidate",
            source="QA_TEST_ONLY",
            replacement_safe=False,
        )
    ]
    if duplicate_ocr:
        texts.append(replace(texts[0]))
    else:
        texts.append(replace(texts[0], bbox=(200, 105, 70, 15)))
    if split_ocr:
        texts[0] = replace(texts[0], bbox=(x0 - 2, y0 - 2, (x1 - x0) / 2, y1 - y0 + 4))
        texts[1] = replace(
            texts[0], bbox=(x0 + (x1 - x0) / 2, y0 - 2, (x1 - x0) / 2, y1 - y0 + 4)
        )
    if competing:
        evidence = deepcopy(evidence)
        evidence["rows"].append(deepcopy(eligible[0]))
    if partial_span:
        evidence = deepcopy(evidence)
        fragment = deepcopy(eligible[0])
        fragment["bounds"] = [x0, y0, x0 + 3, y1]
        fragment["layout_eligible"] = False
        evidence["rows"].append(fragment)
    line = (
        LineSegment(x0 + 10, y0, x0 + 10, y1)
        if collision
        else LineSegment(10, 140, 290, 140)
    )
    structure = build_final_structure(
        source_size_px=(300, 150),
        contour_binary=np.full_like(frame, 255),
        contours=(),
        straight_lines=(line,),
        texts=tuple(texts),
        editable_text_source_mask=np.zeros_like(frame),
        source_text_outline_mask=np.zeros_like(frame),
        uncertain_text_outline_mask=np.zeros_like(frame),
    )
    structure = replace(
        structure, provenance={**structure.provenance, SUGGESTION_KEY: evidence}
    )
    key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(path),
        page_index=0,
        config=ProductionProcessingConfig(source_dpi=72),
    )
    return ReviewProject.create(
        structure,
        source_path=path,
        cache_key=key.payload(),
        frame=frame,
        origin="QA_TEST_ONLY native review",
    )


@pytest.fixture
def project(tmp_path):
    _application = QApplication.instance() or QApplication([])
    path = pdf_source(tmp_path)
    frame, evidence = extract(path)
    review = make_project(path, frame, evidence)
    yield review
    review.close()
    _application.processEvents()


def event():
    return ConfirmationEvent.create(test_only=True)


def confirmed(project):
    uuid = project.bindings[0]["text_source_uuid"]
    suggestion = project.suggestion(uuid)
    record = project.confirm(uuid, suggestion["evidence"]["text"], event=event())
    assert record["consumption"] == "HELD"
    return uuid, record


@pytest.mark.parametrize(
    "prefix,suffix,reason",
    [
        ("3 Tr ", "", "HIDDEN"),
        ("/GS gs ", "", "HIDDEN"),
        ("q 0 0 0 0 re W n ", " Q", "CLIPPING"),
        ("q 30 95 30 20 re W n ", " Q", "CLIPPING"),
        ("", " 1 1 1 rg 20 90 220 30 re f", "OCCLUDED"),
        ("0 1 -1 0 200 0 cm ", "", "ROTATED"),
    ],
)
def test_hidden_clipped_covered_rotated_are_not_complete_suggestions(
    tmp_path, prefix, suffix, reason
):
    _, evidence = extract(pdf_source(tmp_path, prefix=prefix, suffix=suffix))
    assert not any(r["layout_eligible"] for r in evidence["rows"])
    assert reason in str(evidence)


def test_duplicate_native_paint_is_not_admitted(tmp_path):
    _, evidence = extract(pdf_source(tmp_path, duplicate=True))
    assert not any(r["layout_eligible"] for r in evidence["rows"])


def test_empty_pdf_has_no_native_suggestion(tmp_path):
    path = pdf_source(tmp_path, content="")
    _, evidence = extract(path)
    assert evidence["status"] == "NO_ELIGIBLE_SUGGESTION"


@pytest.mark.parametrize(
    "option", ["duplicate_ocr", "competing", "split_ocr", "partial_span"]
)
def test_nonunique_or_split_row_binding_rejected(tmp_path, option):
    _application = QApplication.instance() or QApplication([])
    path = pdf_source(tmp_path)
    frame, evidence = extract(path)
    review = make_project(path, frame, evidence, **{option: True})
    try:
        assert not review.manifest.get("native_suggestions")
    finally:
        review.close()


def test_wrong_tounicode_cannot_change_unconfirmed_text(tmp_path):
    _application = QApplication.instance() or QApplication([])
    normal, _ = extract(pdf_source(tmp_path))
    path = pdf_source(tmp_path, wrong_mapping=True)
    frame, evidence = extract(path)
    assert np.array_equal(normal, frame)
    assert any("Xong" in r["text"] for r in evidence["rows"])
    review = make_project(path, frame, evidence)
    try:
        assert review.records == []
        review.export_dxf(tmp_path / "unconfirmed.dxf")
        assert [
            e.dxf.text
            for e in ezdxf.readfile(tmp_path / "unconfirmed.dxf")
            .modelspace()
            .query("TEXT")
        ] == ["bad", "bad"]
    finally:
        review.close()


def test_content_confirmation_does_not_authorize_layout(project, tmp_path):
    uuid, record = confirmed(project)
    assert project.current_text(uuid) == "bad"
    assert project.preview_source_layout(uuid)["state"] == "PASS"
    project.export_dxf(tmp_path / "content-only.dxf")
    assert [
        e.dxf.text
        for e in ezdxf.readfile(tmp_path / "content-only.dxf")
        .modelspace()
        .query("TEXT")
    ] == ["bad", "bad"]
    assert len(project.records) == 1


def test_layout_consumer_persistence_idempotence_revoke(project, tmp_path):
    uuid, content = confirmed(project)
    baseline = project.baseline
    geometry = project.confirm_source_layout(uuid, event=event())
    assert (
        geometry["consumption"] == "APPLIED"
        and geometry["action"] == "CONFIRM_SOURCE_LAYOUT"
    )
    project.add_records([geometry, geometry])
    assert project.confirm_source_layout(uuid, event=event()) is None
    assert len(project.records) == 2
    project.save(tmp_path / "QA_TEST_ONLY.icreview")
    project.save(tmp_path / "QA_TEST_ONLY.icreview")
    opened = ReviewProject.open(tmp_path / "QA_TEST_ONLY.icreview")
    try:
        assert opened.records == project.records
        assert opened.suggestion(uuid) == project.suggestion(uuid)
        assert opened.current_text(uuid) == "Long source sentence"
        opened.export_dxf(tmp_path / "after.dxf")
        opened.export_dxf(tmp_path / "repeat.dxf")
        doc = ezdxf.readfile(tmp_path / "after.dxf")
        audit = doc.audit()
        assert not audit.errors and not audit.fixes
        texts = list(doc.modelspace().query("TEXT"))
        assert [e.dxf.text for e in texts] == ["Long source sentence", "bad"]
        assert 0.5 <= texts[0].dxf.width <= 2
        assert texts[0].has_xdata("TEXT_SOURCE_LAYOUT")
        assert texts[0].get_xdata("OCR_TEXT_LINE")[1].value == "Long source sentence"
        assert texts[0].get_xdata("TEXT_OUTPUT_CONTRACT")[-1].value == 0
        assert "bad" in [t.value for t in texts[0].get_xdata("TEXT_REVIEW")]
        assert texts[0].get_xdata("OCR_TEXT_LINE")[3].value == 0
        for a, b in zip(
            doc.modelspace(), ezdxf.readfile(tmp_path / "repeat.dxf").modelspace()
        ):
            assert a.dxfattribs() == b.dxfattribs()
        opened.confirm(uuid, "", event=event(), withdraw=True)
        assert opened.current_text(uuid) == "bad" and len(opened.records) == 3
        opened.export_dxf(tmp_path / "withdrawn.dxf")
        assert [
            e.dxf.text
            for e in ezdxf.readfile(tmp_path / "withdrawn.dxf")
            .modelspace()
            .query("TEXT")
        ] == ["bad", "bad"]
    finally:
        opened.close()
    assert project.baseline is baseline and baseline.texts[0].text == "bad"
    assert not np.any(baseline.editable_text_source_mask)
    assert not baseline.texts[0].replacement_safe


def test_layout_collision_and_excessive_compression_rejected(tmp_path):
    _application = QApplication.instance() or QApplication([])
    path = pdf_source(tmp_path)
    frame, evidence = extract(path)
    review = make_project(path, frame, evidence, collision=True)
    try:
        uuid, _ = confirmed(review)
        assert review.preview_source_layout(uuid)["state"] == "NEEDS_LAYOUT_REVIEW"
        result = review.confirm_source_layout(uuid, event=event())
        assert result["consumption"] == "HELD" and review.current_text(uuid) == "bad"
    finally:
        review.close()
    review = make_project(path, frame, evidence)
    try:
        uuid = review.bindings[0]["text_source_uuid"]
        review.confirm(uuid, "Long source sentence " * 8, event=event())
        assert review.preview_source_layout(uuid)["state"] == "NEEDS_LAYOUT_REVIEW"
    finally:
        review.close()


def test_unknown_uuid_source_version_and_geometry_payload_rejected(project):
    with pytest.raises(ReviewProjectError, match="unknown TEXT UUID"):
        project.preview_source_layout(str(uuid4()))
    uuid, _ = confirmed(project)
    record = project.confirm_source_layout(uuid, event=event())
    record["layout_check"]["source_quad"][0][0] += 1
    project._records[-1] = record
    with pytest.raises(ReviewProjectError, match="layout payload"):
        project.validated_review()
    path = Path(project.manifest["source"]["path"])
    path.write_bytes(path.read_bytes() + b"\n% QA source version change\n")
    with pytest.raises(ReviewProjectError, match="source document version"):
        project.validated_review()


def test_new_process_save_open_formal_export_and_edit(project, tmp_path):
    uuid, _ = confirmed(project)
    project.confirm_source_layout(uuid, event=event())
    path = tmp_path / "QA_TEST_ONLY.icreview"
    project.save(path)
    script = "from app.core.review_project import ReviewProject; import sys; from PySide6.QtWidgets import QApplication; a=QApplication([]); p=ReviewProject.open(sys.argv[1]); p.export_dxf(sys.argv[2]); p.close()"
    run = subprocess.run(
        [sys.executable, "-c", script, str(path), str(tmp_path / "fresh.dxf")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    doc = ezdxf.readfile(tmp_path / "fresh.dxf")
    entity = list(doc.modelspace().query("TEXT"))[0]
    entity.dxf.text = "QA_EDIT"
    doc.saveas(tmp_path / "edited.dxf")
    script = "import ezdxf,sys; d=ezdxf.readfile(sys.argv[1]); t=list(d.modelspace().query('TEXT')); assert t[0].dxf.text=='QA_EDIT'; assert t[0].has_xdata('TEXT_SOURCE_LAYOUT'); a=d.audit(); assert not a.errors and not a.fixes"
    run = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "edited.dxf")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


def test_gui_copy_input_cancel_and_independent_confirmations(project):
    from app.gui.review_project_dialog import SnapshotTextReviewDialog

    dialog = SnapshotTextReviewDialog(project, test_only=True)
    dialog._select_index(0)
    dialog.use_suggestion_button.click()
    assert dialog.project.records == []
    assert "Long source sentence" in dialog.suggestion_label.text()
    assert not dialog.confirm_layout_button.isEnabled()
    dialog._apply_current_text()
    assert len(dialog.project.records) == 1
    assert dialog.project.current_text(project.bindings[0]["text_source_uuid"]) == "bad"
    dialog._preview_source_layout()
    assert dialog.confirm_layout_button.isEnabled()
    dialog.confirm_layout_button.click()
    assert len(dialog.project.records) == 2
    assert "已确认源显示区域" in dialog.confidence_label.text()
    dialog.reject()
    assert project.records == []  # Dialog cancel does not commit the draft.


def test_new_snapshot_never_reuses_suggestion_or_layout_uuid(project):
    uuid, _ = confirmed(project)
    record = project.confirm_source_layout(uuid, event=event())
    provenance = {
        k: v
        for k, v in project.baseline.provenance.items()
        if k != "review_snapshot_v1"
    }
    baseline = replace(project.baseline, provenance=provenance)
    other = ReviewProject.create(
        baseline,
        source_path=project.manifest["source"]["path"],
        cache_key=project.manifest["source"]["cache_identity"],
        frame=project.frame,
        origin="QA_TEST_ONLY new conversion",
    )
    try:
        assert other.snapshot_uuid != project.snapshot_uuid
        assert other.bindings[0]["text_source_uuid"] != uuid
        with pytest.raises(ReviewProjectError, match="NEEDS_RECONFIRM"):
            other.add_records([record])
    finally:
        other.close()


def test_layout_cannot_promote_qa_content_to_real_user_confirmation(project):
    uuid, _ = confirmed(project)
    with pytest.raises(ReviewProjectError, match="same QA/user domain"):
        project.confirm_source_layout(
            uuid, event=ConfirmationEvent.create(test_only=False)
        )


def test_later_content_edit_cannot_silently_restore_original_geometry(project):
    uuid, _ = confirmed(project)
    project.confirm_source_layout(uuid, event=event())
    before = project.current_placement(uuid, transform=project.guard.transform)
    with pytest.raises(ReviewProjectError, match="请先撤回"):
        project.confirm(uuid, "b", event=event())
    assert len(project.records) == 2
    assert project.current_text(uuid) == "Long source sentence"
    assert project.current_placement(uuid, transform=project.guard.transform) == before
    project.confirm(uuid, "", event=event(), withdraw=True)
    project.confirm(uuid, "b", event=event())
    assert project.current_text(uuid) == "b"
    assert project.current_source_layout(uuid) is None


def test_old_cache_is_not_silently_native_suggestion_ready():
    from app.core.processing import cache_key_matches

    current = ProductionProcessingConfig()
    previous = replace(
        current,
        algorithm_version=current.algorithm_version.replace(
            "-native-pdf-review-suggestions-v1", "", 1
        ),
    )
    args = dict(input_content_sha256="a" * 64, page_index=2)
    old = build_processing_cache_key(**args, config=previous)
    new = build_processing_cache_key(**args, config=current)
    assert not cache_key_matches(old.payload(), new)


def test_raster_review_binding_does_not_require_optional_pdf_parser():
    script = "import sys; sys.modules['pypdfium2']=None; from app.core.native_text_review import bind_native_suggestions; from types import SimpleNamespace; assert bind_native_suggestions(SimpleNamespace(provenance={}),{})==[]"
    run = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert run.returncode == 0, run.stderr


def test_oversize_native_line_does_not_create_unbounded_xdata(tmp_path):
    _, evidence = extract(
        pdf_source(tmp_path, prefix="0.1 0 0 1 0 0 cm ", content="A" * 270)
    )
    assert not any(r["layout_eligible"] for r in evidence["rows"])
    assert "NATIVE_LINE_PROVENANCE_BYTE_LIMIT" in str(evidence)


def test_only_whole_native_source_footprints_are_retained(project):
    from app.export.review_text import polygon
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath

    uuid = project.bindings[0]["text_source_uuid"]
    suggestion = project.suggestion(uuid)
    row = suggestion["evidence"]
    proof = row["proof"]
    import base64

    support = cv2.imdecode(
        np.frombuffer(base64.b64decode(proof["source_only_support_png"]), np.uint8), 0
    )
    y, x = np.argwhere(support != 0)[len(np.argwhere(support != 0)) // 2]
    px, py = x + proof["support_box"][0], y + proof["support_box"][1]
    footprint = QPainterPath()
    footprint.addEllipse(QPointF(px + 0.5, 150 - py - 0.5), 0.2, 0.2)
    assert project.guard._is_preserved_source(footprint, suggestion)
    # A line crossing the full source row/whitespace is not a glyph carrier.
    across = polygon(
        [
            (row["bounds"][0], 150 - row["bounds"][1]),
            (row["bounds"][2], 150 - row["bounds"][1]),
            (row["bounds"][2], 149 - row["bounds"][1]),
            (row["bounds"][0], 149 - row["bounds"][1]),
        ]
    )
    assert not project.guard._is_preserved_source(across, suggestion)
