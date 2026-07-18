from __future__ import annotations

import numpy as np

from app.line_detect import LineSegment
from app.text_protection import TextProtectionResult, filter_text_like_lines


def test_pdf_scale_text_strokes_are_removed_but_long_structure_is_kept() -> None:
    mask = np.zeros((4000, 6000), dtype=np.uint8)
    mask[300:650, 700:2100] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=40,
        text_region_count=1,
    )
    long_glyph_stroke = LineSegment(780, 420, 1550, 420)
    crossing_structure = LineSegment(100, 500, 5900, 500)
    outside_structure = LineSegment(200, 1500, 5600, 1500)

    kept, result = filter_text_like_lines(
        [long_glyph_stroke, crossing_structure, outside_structure],
        protection,
        mask.shape,
    )

    assert long_glyph_stroke not in kept
    assert crossing_structure in kept
    assert outside_structure in kept
    assert result.rejected_line_count == 1
