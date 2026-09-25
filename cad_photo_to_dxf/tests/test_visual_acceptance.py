from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import TextCandidate
from app.final_structure import FinalStructure, build_final_structure
from app.gui_public_release import MainWindow
from app.human_visible_baseline import (
    BaselineEntry,
    build_baseline_contact_sheet,
    common_failure_families,
)
from app.line_detect import LineSegment
from app.raster_trace import TracePath
from app.visual_acceptance import (
    VisualLayerSelection,
    create_visual_acceptance_run,
    plain_language_status,
    render_visual_acceptance,
    update_human_review,
)
from app.visual_acceptance_widget import VisualAcceptanceWidget


_APP = QApplication.instance() or QApplication([])


def _structure() -> FinalStructure:
    binary = np.full((80, 120), 255, dtype=np.uint8)
    path = TracePath(
        points=((10.0, 10.0), (55.0, 10.0), (55.0, 45.0), (10.0, 45.0)),
        parent=None,
        depth=0,
        root=0,
    )
    uncertain = np.zeros_like(binary)
    uncertain[60:66, 70:90] = 255
    return build_final_structure(
        source_size_px=(120, 80),
        contour_binary=binary,
        contours=(path,),
        straight_lines=(
            LineSegment(5.0, 70.0, 110.0, 70.0, source_ids=("evidence-1",)),
        ),
        texts=(
            TextCandidate(
                text="E-101",
                bbox=(65, 10, 45, 15),
                confidence=0.97,
                kind="drawing_text",
            ),
        ),
        uncertain_text_outline_mask=uncertain,
        warnings=("Review upper-right connection",),
        provenance={"pipeline": "production", "candidate_ids": ["candidate-1"]},
    )


def test_renderer_uses_one_source_coordinate_system_and_canonical_entities() -> None:
    structure = _structure()
    source = np.full((80, 120, 3), 235, dtype=np.uint8)
    structure_id = structure.structure_id

    images = render_visual_acceptance(source, structure)

    assert images.original.shape == images.reconstructed.shape == images.overlay.shape
    assert images.original.shape == (80, 120, 3)
    assert np.any(images.reconstructed[10, 10] < 245)
    assert np.any(images.reconstructed[70, 50] < 245)
    assert structure.structure_id == structure_id


def test_renderer_uses_packaged_unicode_glyphs_without_changing_structure() -> None:
    base = _structure()
    unicode_structure = build_final_structure(
        source_size_px=(220, 90),
        contour_binary=np.full((90, 220), 255, dtype=np.uint8),
        contours=(),
        straight_lines=(),
        texts=(
            TextCandidate(
                text="臥室 日本 한국 Latin 123 .,!?",
                bbox=(5, 8, 210, 72),
                confidence=0.99,
                kind="drawing_text",
            ),
        ),
    )
    structure_id = unicode_structure.structure_id

    rendered = render_visual_acceptance(
        np.full((90, 220), 255, dtype=np.uint8),
        unicode_structure,
    ).reconstructed
    question_structure = build_final_structure(
        source_size_px=(220, 90),
        contour_binary=np.full((90, 220), 255, dtype=np.uint8),
        contours=(),
        straight_lines=(),
        texts=(
            TextCandidate(
                text="?? ?? ?? Latin 123 .,!?",
                bbox=(5, 8, 210, 72),
                confidence=0.99,
                kind="drawing_text",
            ),
        ),
    )
    question_render = render_visual_acceptance(
        np.full((90, 220), 255, dtype=np.uint8),
        question_structure,
    ).reconstructed

    assert np.any(rendered[10:78, 7:213] < 245)
    assert not np.array_equal(rendered, question_render)
    assert unicode_structure.structure_id == structure_id
    assert base.structure_id == _structure().structure_id


def test_renderer_rejects_coordinate_mismatch() -> None:
    with pytest.raises(ValueError, match="same pixel coordinate system"):
        render_visual_acceptance(np.zeros((40, 60), dtype=np.uint8), _structure())


def test_layer_switches_change_display_without_changing_final_structure() -> None:
    structure = _structure()
    source = np.full((80, 120), 255, dtype=np.uint8)
    hidden = render_visual_acceptance(
        source,
        structure,
        layers=VisualLayerSelection(
            structure_lines=False,
            texts=False,
            symbols=False,
            unverified_geometry=False,
            review_warnings=False,
        ),
    )
    assert np.all(hidden.reconstructed == 255)
    assert structure.structure_id == _structure().structure_id


def test_run_writes_overview_review_and_entity_provenance(tmp_path: Path) -> None:
    structure = _structure()
    run, _images = create_visual_acceptance_run(
        np.full((80, 120), 255, dtype=np.uint8),
        structure,
        output_root=tmp_path,
        source_label="dev-source.png",
        page_label="single page",
        commit="abcdef1234567890",
        corpus_split="DEV",
        timestamp=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    expected = {
        "original.png",
        "reconstructed.png",
        "overlay.png",
        "visual_acceptance_overview.png",
        "human_review.json",
        "developer_details.json",
    }
    assert {path.name for path in run.directory.iterdir()} == expected
    assert cv2.imread(str(run.overview_path), cv2.IMREAD_COLOR) is not None
    details = json.loads((run.directory / "developer_details.json").read_text())
    assert details["final_structure_id"] == structure.structure_id
    assert details["entity_count"] == 3
    assert details["entity_references"][1]["candidate_or_evidence_ids"] == [
        "evidence-1"
    ]

    update_human_review(
        run,
        verdict="FAIL",
        issue_tags=["MISSING_CONTENT", "WRONG_CONNECTION"],
        source_label="dev-source.png",
        page_label="single page",
        commit="abcdef1234567890",
    )
    review = json.loads((run.directory / "human_review.json").read_text())
    assert review["verdict"] == "FAIL"
    assert review["issue_tags"] == ["MISSING_CONTENT", "WRONG_CONNECTION"]


def test_locked_blind_is_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GOLDEN, DEV"):
        create_visual_acceptance_run(
            np.full((80, 120), 255, dtype=np.uint8),
            _structure(),
            output_root=tmp_path,
            source_label="forbidden.png",
            page_label="page 1",
            commit="test",
            corpus_split="LOCKED_BLIND",
        )
    assert not list(tmp_path.iterdir())


def test_plain_language_statuses_hide_internal_enums() -> None:
    assert plain_language_status("SEMANTIC_IDENTITY_UNVERIFIED") == (
        "语义未确认，但几何已保留"
    )


def test_workbench_and_product_window_expose_visual_acceptance(tmp_path: Path) -> None:
    widget = VisualAcceptanceWidget()
    run = widget.set_result(
        np.full((80, 120), 255, dtype=np.uint8),
        _structure(),
        source_label="dev-source.png",
        page_label="single page",
        commit="test",
        output_root=tmp_path,
        corpus_split="DEV",
    )
    assert widget.original_canvas.scene().sceneRect().width() == 120
    assert widget.reconstructed_canvas.scene().sceneRect().width() == 120
    assert widget.overlay_canvas.scene().sceneRect().width() == 120
    assert run.overview_path.exists()

    window = MainWindow()
    assert window.tabs.indexOf(window.visual_acceptance) >= 0
    assert (
        window.tabs.tabText(window.tabs.indexOf(window.visual_acceptance)) == "视觉验收"
    )
    window.close()


def test_dev_baseline_contact_sheet_and_common_failure_gate(tmp_path: Path) -> None:
    entries = []
    for index in range(5):
        run_directory = tmp_path / f"run-{index}"
        run_directory.mkdir()
        for filename in ("original.png", "reconstructed.png", "overlay.png"):
            assert cv2.imwrite(
                str(run_directory / filename),
                np.full((60, 90, 3), 220 - index, dtype=np.uint8),
            )
        entries.append(
            BaselineEntry(
                source_group_id=f"DEV-{index}",
                verdict="FAIL" if index < 3 else "PARTIAL",
                issue_tags=("MISSING_CONTENT",) if index < 3 else ("TEXT_ERROR",),
                primary_observation="visible baseline",
                run_directory=run_directory,
            )
        )
    output = build_baseline_contact_sheet(entries, tmp_path / "baseline.png")
    image = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.shape == (72 + (64 + 430) * 5, 720 * 3, 3)
    assert common_failure_families(
        entries,
        {"MISSING_CONTENT": "STRUCTURE_RECALL_FAILURE"},
    ) == {"STRUCTURE_RECALL_FAILURE": ("DEV-0", "DEV-1", "DEV-2")}
