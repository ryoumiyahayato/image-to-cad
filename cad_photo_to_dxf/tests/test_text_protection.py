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


def test_masked_structural_continuation_survives_text_bbox() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:60, 80:105] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=4,
        text_region_count=1,
    )
    structural = LineSegment(60.0, 50.0, 125.0, 50.0)

    kept, result = filter_text_like_lines(
        [structural],
        protection,
        mask.shape,
    )

    assert structural in kept
    assert result.rejected_line_count == 0


def test_masked_structural_bridge_uses_collinearity_and_topology() -> None:
    mask = np.zeros((180, 240), dtype=np.uint8)
    mask[40:60, 80:130] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=5,
        text_region_count=1,
    )
    left_continuation = LineSegment(20.0, 50.0, 75.0, 50.0)
    masked_bridge = LineSegment(80.0, 50.0, 130.0, 50.0)
    crossing = LineSegment(100.0, 20.0, 100.0, 80.0)

    kept, _result = filter_text_like_lines(
        [left_continuation, masked_bridge, crossing],
        protection,
        mask.shape,
    )

    assert left_continuation in kept
    assert masked_bridge in kept


def test_text_glyph_stroke_inside_mask_is_not_restored() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:80, 60:140] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=8,
        text_region_count=1,
    )
    glyph_stroke = LineSegment(70.0, 55.0, 130.0, 55.0)

    kept, result = filter_text_like_lines(
        [glyph_stroke],
        protection,
        mask.shape,
    )

    assert glyph_stroke not in kept
    assert result.rejected_line_count == 1


def test_structural_continuation_threshold_is_resolution_normalized() -> None:
    cases = (
        ((800, 1200), LineSegment(100.0, 400.0, 130.0, 400.0), (400, 110, 400, 120)),
        ((1600, 2400), LineSegment(200.0, 800.0, 260.0, 800.0), (800, 220, 800, 240)),
    )

    for shape, structural, (top, left, bottom, right) in cases:
        mask = np.zeros(shape, dtype=np.uint8)
        mask[top:bottom, left:right] = 255
        protection = TextProtectionResult(
            mask=mask,
            candidate_component_count=3,
            text_region_count=1,
        )

        kept, _result = filter_text_like_lines(
            [structural],
            protection,
            mask.shape,
        )

        assert structural in kept


def test_text_region_filter_is_deterministic_for_same_geometry() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:100, 60:220] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=12,
        text_region_count=1,
    )
    lines = [
        LineSegment(80.0, 55.0, 145.0, 55.0),
        LineSegment(20.0, 70.0, 75.0, 70.0),
        LineSegment(250.0, 150.0, 330.0, 150.0),
    ]

    first, first_result = filter_text_like_lines(lines, protection, mask.shape)
    second, second_result = filter_text_like_lines(lines, protection, mask.shape)

    assert first == second
    assert first_result.rejected_line_count == second_result.rejected_line_count
    assert np.array_equal(first_result.mask, second_result.mask)


def test_restoration_candidates_are_reported_without_mutating_mask() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:60, 80:105] = 255
    original = mask.copy()
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=4,
        text_region_count=1,
    )
    structural = LineSegment(60.0, 50.0, 125.0, 50.0)

    kept, result = filter_text_like_lines(
        [structural],
        protection,
        mask.shape,
    )

    assert structural in kept
    assert result.restored_lines == (structural,)
    assert np.array_equal(mask, original)


def test_glyph_stroke_has_no_restoration_provenance() -> None:
    mask = np.zeros((200, 400), dtype=np.uint8)
    mask[40:80, 60:140] = 255
    protection = TextProtectionResult(
        mask=mask,
        candidate_component_count=8,
        text_region_count=1,
    )
    glyph_stroke = LineSegment(70.0, 55.0, 130.0, 55.0)

    kept, result = filter_text_like_lines(
        [glyph_stroke],
        protection,
        mask.shape,
    )

    assert glyph_stroke not in kept
    assert result.restored_lines == ()
