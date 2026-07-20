from __future__ import annotations

import ezdxf
from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import TextCandidate
from app.gui_librecad_release import LibreCadOcrReviewDialog
from app.librecad_lff import (
    LIBRECAD_FONT_FAMILY,
    LIBRECAD_FONT_FILENAME,
    LIBRECAD_STYLE_NAME,
)
from app.ocr_outline_export import add_ocr_outline_blocks


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _candidate(**changes) -> TextCandidate:
    values = {
        "text": "火灾",
        "bbox": (10, 10, 80, 32),
        "confidence": 1.0,
        "kind": "text_candidate",
        "quad": ((10.0, 10.0), (90.0, 10.0), (90.0, 42.0), (10.0, 42.0)),
        "source": "lff-test",
        "approved": True,
        "reviewed": True,
    }
    values.update(changes)
    return TextCandidate(**values)


def test_librecad_review_forces_native_lff_font() -> None:
    _application()
    import numpy as np

    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    dialog = LibreCadOcrReviewDialog(image, (_candidate(font_family="SimHei", font_file="simhei.ttf"),))
    try:
        reviewed = dialog.reviewed_texts()[0]
        assert reviewed.font_family == LIBRECAD_FONT_FAMILY
        assert reviewed.font_file == LIBRECAD_FONT_FILENAME
    finally:
        dialog.close()


def test_lff_candidate_exports_one_native_text_per_character() -> None:
    document = ezdxf.new("R2010", setup=True)
    modelspace = document.modelspace()
    candidate = _candidate(
        font_family=LIBRECAD_FONT_FAMILY,
        font_file=LIBRECAD_FONT_FILENAME,
    )

    count, entities, _bounds = add_ocr_outline_blocks(
        document,
        modelspace,
        (candidate,),
        transform=lambda x, y: (x, 100.0 - y),
    )

    assert count == 2
    assert [entity.dxf.text for entity in entities] == ["火", "灾"]
    assert all(entity.dxftype() == "TEXT" for entity in entities)
    assert all(entity.dxf.style == LIBRECAD_STYLE_NAME for entity in entities)
    assert document.styles.get(LIBRECAD_STYLE_NAME).dxf.font == LIBRECAD_FONT_FILENAME
    assert len(modelspace.query("INSERT")) == 0
    assert len(modelspace.query("LWPOLYLINE")) == 0
    assert not document.audit().errors
