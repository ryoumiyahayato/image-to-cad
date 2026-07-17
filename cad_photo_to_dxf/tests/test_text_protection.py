from __future__ import annotations

import numpy as np

from app.line_detect import LineSegment
from app.text_protection import TextProtectionResult, filter_text_like_lines


def test_text_region_filter_rejects_local_strokes_but_keeps_structure() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:100, 60:220] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=12,
        text_region_count=1,
    )
    inside_text = LineSegment(80.0, 55.0, 145.0, 55.0)
    outside_text = LineSegment(250.0, 150.0, 330.0, 150.0)
    long_structure = LineSegment(0.0, 70.0, 399.0, 70.0)

    kept, result = filter_text_like_lines(
        [inside_text, outside_text, long_structure],
        protection,
        mask.shape,
    )

    assert inside_text not in kept
    assert outside_text in kept
    assert long_structure in kept
    assert result.rejected_line_count == 1
