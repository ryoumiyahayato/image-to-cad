from __future__ import annotations

import ezdxf
from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import TextCandidate
from app.font_library import find_font_face, safe_style_name
from app.ocr_outline_export import add_ocr_outline_blocks


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_selected_cjk_font_is_used_for_each_editable_character() -> None:
    _application()
    document = ezdxf.new("R2010", setup=True)
    modelspace = document.modelspace()
    candidate = TextCandidate(
        text="火灾",
        bbox=(10, 10, 80, 32),
        confidence=1.0,
        kind="text_candidate",
        quad=((10.0, 10.0), (90.0, 10.0), (90.0, 42.0), (10.0, 42.0)),
        source="manual-test",
        approved=True,
        reviewed=True,
        font_family="SimHei",
        font_file="simhei.ttf",
        font_match_score=0.88,
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
    assert all(entity.dxf.style == "OCR_SIMHEI" for entity in entities)
    assert all(float(entity.dxf.width) == 1.0 for entity in entities)
    assert all(float(entity.dxf.oblique) == 0.0 for entity in entities)
    style = document.styles.get("OCR_SIMHEI")
    assert style.dxf.font == "simhei.ttf"
    family, italic, bold = style.get_extended_font_data()
    assert family == "SimHei"
    assert not italic
    assert not bold
    assert document.header["$DWGCODEPAGE"] == "ANSI_936"
    assert len(modelspace.query("INSERT")) == 0
    assert len(modelspace.query("LWPOLYLINE")) == 0
    for entity in entities:
        xdata = entity.get_xdata("OCR_CHARACTER")
        text_values = [tag.value for tag in xdata if tag.code == 1000]
        assert "火灾" in text_values
        assert "SimHei" in text_values
        assert "simhei.ttf" in text_values
    assert not document.audit().errors


def test_explicit_font_selection_survives_missing_local_catalog_entry() -> None:
    face = find_font_face("Example CJK", "example-cjk.ttf", "中文")

    assert face.family == "Example CJK"
    assert face.filename == "example-cjk.ttf"
    assert safe_style_name(face) == "OCR_EXAMPLE_CJK"
