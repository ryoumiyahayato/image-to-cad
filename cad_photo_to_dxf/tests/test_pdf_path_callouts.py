import numpy as np

from app.ocr.pdf_path_callouts import _clear_quad


def test_source_callout_uses_full_bounds_or_defers_layout():
    glyphs = np.full((32, 60), 255, dtype=np.uint8)
    glyphs[6:26, 10:48] = 0
    foreign = np.full_like(glyphs, 255)
    foreign[27, 8:50] = 0
    assert _clear_quad(glyphs, foreign, 100, 200) == (
        (110, 206), (148, 206), (148, 226), (110, 226)
    )

    # The adjacent line reaches the last glyph row's clearance margin.
    # A partial-height source fit would silently move the text upwards.
    foreign[26, 8:50] = 0
    assert _clear_quad(glyphs, foreign, 100, 200) is None
