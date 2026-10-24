"""Requested isolated fault controls, using the existing exporter/inspector.

All sources and damage here are TEST_ONLY. These are checks of the checks, not
newly discovered defects or permissions to change real engineering objects.
"""

import json
from zipfile import ZipFile, ZIP_DEFLATED

import cv2
import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.core.processing import (
    ProductionProcessingConfig,
    build_processing_cache_key,
    file_content_sha256,
)
from app.core.review_project import ConfirmationEvent, ReviewProject
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.ocr.auxiliary_recognition import TextCandidate
from app.quality import fidelity as f


@pytest.fixture
def exported(tmp_path):
    app = QApplication.instance() or QApplication([])
    gray = np.full((180, 400), 255, np.uint8)
    path = tmp_path / "QA_TEST_ONLY.png"
    assert cv2.imwrite(str(path), gray)
    texts = tuple(
        TextCandidate(t, b, 0.99, "text_candidate", source="TEST_ONLY")
        for t, b in [
            ("12.50", (20, 20, 80, 20)),
            ("ALPHA", (140, 20, 80, 20)),
            ("ALPHA", (270, 20, 80, 20)),
        ]
    )
    lines = tuple(
        LineSegment(*v)
        for v in [
            (20, 100, 180, 100),
            (20, 104, 180, 104),
            (220, 100, 250, 100),
            (270, 100, 300, 100),
            (100, 100, 100, 110),
        ]
    )
    structure = build_final_structure(
        source_size_px=(400, 180),
        contour_binary=gray,
        contours=(),
        straight_lines=lines,
        texts=texts,
        editable_text_source_mask=np.zeros_like(gray),
        source_text_outline_mask=np.zeros_like(gray),
        uncertain_text_outline_mask=np.zeros_like(gray),
    )
    key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(path),
        page_index=None,
        config=ProductionProcessingConfig(),
    )
    project = ReviewProject.create(
        structure,
        source_path=path,
        cache_key=key.payload(),
        frame=gray,
        origin="QA_TEST_ONLY faults",
    )
    result = project.export_dxf(tmp_path / "normal.dxf")
    project.close()
    yield result.path
    app.processEvents()


def observed(path):
    _, rows, audit, _ = f.read_dxf(path, 1, (400, 180), {}, f.Limits())
    assert audit == {"errors": 0, "fixes": 0}
    return [
        {
            k: r[k]
            for k in ("type", "layer", "visible", "geometry_source_CAD_axes", "xdata")
        }
        for r in rows
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "dimension_digit",
        "omitted_character",
        "same_name_uuid_swap",
        "merge_independent_lines",
        "close_opening",
        "delete_short_branch",
        "delete_source_xdata",
    ],
)
def test_normal_control_matches_and_damaged_control_exposes_exact_difference(
    exported, tmp_path, fault
):
    baseline = observed(exported)
    assert observed(exported) == baseline
    doc = ezdxf.readfile(exported)
    space = doc.modelspace()
    texts = list(space.query("TEXT"))
    lines = list(space.query("LINE"))
    if fault in {"dimension_digit", "omitted_character"}:
        target = next(e for e in texts if e.dxf.text == "12.50")
        target.dxf.text = "12.60" if fault == "dimension_digit" else "12.5"
    elif fault == "same_name_uuid_swap":
        a, b = [e for e in texts if e.dxf.text == "ALPHA"]
        ta, tb = list(a.get_xdata("TEXT_REVIEW")), list(b.get_xdata("TEXT_REVIEW"))
        a.set_xdata("TEXT_REVIEW", tb)
        b.set_xdata("TEXT_REVIEW", ta)
    elif fault == "merge_independent_lines":
        space.delete_entity(next(e for e in lines if e.dxf.start.y == 76))
    elif fault == "close_opening":
        space.add_line((250, 80), (270, 80))
    elif fault == "delete_short_branch":
        space.delete_entity(next(e for e in lines if e.dxf.start.x == e.dxf.end.x))
    else:
        texts[0].discard_xdata("TEXT_REVIEW")
    damaged = tmp_path / (fault + ".dxf")
    doc.saveas(damaged)
    actual = observed(damaged)
    assert actual != baseline
    # Equal object count, lengths, bbox or strings cannot conceal source swaps.
    if fault in {"same_name_uuid_swap", "delete_source_xdata"}:
        assert [r["geometry_source_CAD_axes"] for r in actual] == [
            r["geometry_source_CAD_axes"] for r in baseline
        ]
        assert [r["xdata"] for r in actual] != [r["xdata"] for r in baseline]
    elif fault in {"dimension_digit", "omitted_character"}:
        assert len(actual) == len(baseline)
        assert [r["geometry_source_CAD_axes"] for r in actual] != [
            r["geometry_source_CAD_axes"] for r in baseline
        ]
    else:
        assert len(actual) != len(baseline)


def test_omitted_saved_layout_fails_actual_project_consumer(tmp_path):
    from tests.test_native_text_review import pdf_source, extract, make_project

    app = QApplication.instance() or QApplication([])
    source = pdf_source(tmp_path)
    frame, evidence = extract(source)
    project = make_project(source, frame, evidence)
    uid = project.bindings[0]["text_source_uuid"]
    suggestion = project.suggestion(uid)["evidence"]["text"]
    project.confirm(uid, suggestion, event=ConfirmationEvent.create(test_only=True))
    record = project.confirm_source_layout(
        uid, event=ConfirmationEvent.create(test_only=True)
    )
    assert record["consumption"] == "APPLIED"
    normal = tmp_path / "normal.icreview"
    project.save(normal)
    project.close()
    checked = ReviewProject.open(normal)
    checked.validated_review()
    checked.close()
    with ZipFile(normal) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    journal = json.loads(entries["corrections.json"])
    journal["records"][-1]["layout_check"].pop("source_quad")
    entries["corrections.json"] = json.dumps(journal).encode()
    damaged = tmp_path / "missing-layout.icreview"
    with ZipFile(damaged, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises((ValueError, KeyError), match="source_quad|layout"):
        loaded = ReviewProject.open(damaged)
        try:
            loaded.validated_review()
        finally:
            loaded.close()
    app.processEvents()
