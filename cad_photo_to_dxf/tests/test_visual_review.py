from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import CircleCandidate, TextCandidate
from app.image_canvas import ImageCanvas
from app.line_detect import LineSegment
from app.visual_review import VectorReviewDialog

_APP = QApplication.instance() or QApplication([])


def test_visual_editor_returns_direct_geometry_and_text_changes() -> None:
    image = np.full((120, 180, 3), 255, dtype=np.uint8)
    dialog = VectorReviewDialog(
        image,
        [LineSegment(10, 20, 100, 20, layer="DETAIL")],
        circles=[CircleCandidate((60, 60), 15, 0.95)],
        texts=[TextCandidate("old", (20, 80, 30, 14), 0.9, "text_candidate")],
    )
    line_item = dialog._line_items[0]
    line_item.set_layer("GRID_OR_AXIS")
    line_item.handle_moved(1, QPointF(120, 30))
    text_item = dialog._text_items[0]
    text_item.setText("new")
    text_item.setPos(30, 90)

    lines, circles, texts = dialog.reviewed_entities()

    assert len(lines) == len(circles) == len(texts) == 1
    assert lines[0].layer == "GRID_OR_AXIS"
    assert (lines[0].x2, lines[0].y2) == (120.0, 30.0)
    assert "visual_geometry_review" in lines[0].history
    assert texts[0].text == "new"
    assert texts[0].bbox[:2] == (30, 90)


def test_canvas_keeps_scan_and_vectors_as_separate_items() -> None:
    image = np.full((100, 160, 3), 255, dtype=np.uint8)
    canvas = ImageCanvas()
    canvas.set_vector_result(
        image,
        [LineSegment(5, 5, 150, 5, layer="OUTLINE")],
        circles=[CircleCandidate((50, 50), 10, 0.95)],
        texts=[TextCandidate("A", (70, 40, 10, 12), 1.0, "text_candidate")],
    )

    assert canvas._pixmap_item is not None
    assert len(canvas._overlay_items) == 3
    canvas.actual_size()
    canvas.zoom_out()
    assert canvas._pixmap_item.transformationMode().name == "SmoothTransformation"
