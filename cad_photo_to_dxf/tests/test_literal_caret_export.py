"""Literal caret is logical OCR text; DXF TEXT encodes it with caret-space."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ezdxf
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from ezdxf.tools.text import caret_decode
from app.core.structure_build import build_final_structure
from app.ocr.auxiliary_recognition import TextCandidate
from app.export.trace_single_export import export_final_structure_dxf


@pytest.mark.parametrize("content", ["^", "3MT-1^", "A^I", "A^ B", "1/4 mm 中文"])
def test_literal_content_survives_text_file_roundtrip(tmp_path, content):
    _application = QApplication.instance() or QApplication([])
    frame = np.full((150, 320), 255, np.uint8)
    structure = build_final_structure(
        source_size_px=(320, 150),
        contour_binary=frame,
        contours=(),
        straight_lines=(),
        texts=(
            TextCandidate(
                content,
                (20, 30, 100, 20),
                0.99,
                "text_candidate",
                source="TEST_ONLY",
                approved=True,
            ),
        ),
        editable_text_source_mask=np.zeros_like(frame),
        source_text_outline_mask=np.zeros_like(frame),
        uncertain_text_outline_mask=np.zeros_like(frame),
    )
    path = tmp_path / "literal.dxf"
    export_final_structure_dxf(structure, path)
    entities = list(ezdxf.readfile(path).modelspace().query("TEXT"))
    assert len(entities) == 1
    entity = entities[0]
    assert caret_decode(entity.dxf.text) == content
    assert entity.get_xdata("OCR_TEXT_LINE")[1].value == content
    if "^" not in content:
        assert entity.dxf.text == content
