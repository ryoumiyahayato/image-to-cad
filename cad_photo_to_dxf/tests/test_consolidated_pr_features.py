from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import ezdxf
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import CircleCandidate, TextCandidate
from app.document_export import DocumentPage, export_scan_document
from app.gui_consolidated import MainWindow as ConsolidatedMainWindow
from app.gui_state_guard import MainWindow as DocumentMainWindow
from app.image_canvas import ImageCanvas
from app.line_detect import LineSegment
from app.visual_review import VectorReviewDialog

_APP = QApplication.instance() or QApplication([])


def test_consolidated_window_preserves_pr20_document_chain() -> None:
    assert issubclass(ConsolidatedMainWindow, DocumentMainWindow)


def test_visual_editor_moves_and_adds_multiple_entity_types() -> None:
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


def test_canvas_keeps_adaptive_scan_and_vectors_separate() -> None:
    image = np.full((100, 160, 3), 255, dtype=np.uint8)
    canvas = ImageCanvas()
    canvas.set_vector_result(
        image,
        [LineSegment(5, 5, 150, 5, layer="OUTLINE")],
        circles=[CircleCandidate((50, 50), 10, 0.95)],
        texts=[TextCandidate("A", (70, 40, 10, 12), 1.0, "text_candidate")],
    )

    assert canvas._pixmap_item is not None
    assert canvas._source_image is not None
    assert len(canvas._overlay_items) == 3
    canvas.actual_size()
    canvas.zoom_out()
    assert canvas._lod_key is not None


def _write_scan(path: Path, width: int, height: int) -> None:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (width - 6, height - 6), (0, 0, 0), 2)
    assert cv2.imwrite(str(path), image)


def test_document_export_keeps_layouts_groups_circles_text_and_lazy_scan(
    tmp_path: Path,
) -> None:
    lazy_scan = tmp_path / "lazy.png"
    _write_scan(lazy_scan, 200, 100)
    direct_scan = np.full((120, 180, 3), 255, dtype=np.uint8)
    result = export_scan_document(
        [
            DocumentPage(
                1,
                None,
                (420.0, 297.0),
                (LineSegment(10, 10, 190, 10),),
                (200, 100),
                "lazy page",
                circles=(CircleCandidate((50, 50), 12, 1.0),),
                texts=(TextCandidate("P1", (80, 40, 25, 14), 1.0, "manual_text"),),
                source_path=lazy_scan,
            ),
            DocumentPage(1, direct_scan, (420.0, 297.0), label="second source"),
        ],
        tmp_path / "combined.dxf",
    )

    assert result.page_count == 2
    assert result.line_count == 1
    assert result.circle_count == 1
    assert result.text_count == 1
    assert result.layout_names == ("PAGE-001", "PAGE-002")
    assert result.group_names == ("PAGE_001", "PAGE_002")
    document = ezdxf.readfile(result.path)
    assert len(document.modelspace().query("IMAGE")) == 2
    assert len(document.modelspace().query("LINE")) == 1
    assert len(document.modelspace().query("CIRCLE")) == 1
    assert len(document.modelspace().query("TEXT")) == 1
    assert {name for name, _group in document.groups} >= {"PAGE_001", "PAGE_002"}
