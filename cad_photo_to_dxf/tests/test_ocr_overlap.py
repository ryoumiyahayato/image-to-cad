from __future__ import annotations

from app.auxiliary_recognition import TextCandidate
from app.ocr_overlap import collapse_overlapping_candidates


def _candidate(
    text: str,
    bbox: tuple[int, int, int, int],
    confidence: float,
    source: str,
) -> TextCandidate:
    return TextCandidate(
        text=text,
        bbox=bbox,
        confidence=confidence,
        kind="text_candidate",
        source=source,
    )


def test_shifted_overview_and_tile_results_are_exported_once() -> None:
    overview = _candidate("消防平面图", (100, 200, 240, 44), 0.91, "rapidocr-overview")
    tiled = _candidate("消防平面图", (104, 202, 236, 42), 0.96, "rapidocr-tile")

    result = collapse_overlapping_candidates((overview, tiled))

    assert result == (tiled,)


def test_partial_duplicate_prefers_more_complete_high_rank_candidate() -> None:
    short = _candidate("控制", (300, 500, 90, 38), 0.92, "rapidocr-overview")
    complete = _candidate("控制模块", (296, 498, 180, 42), 0.95, "rapidocr-tile")

    result = collapse_overlapping_candidates((short, complete))

    assert result == (complete,)


def test_adjacent_labels_on_same_row_remain_separate() -> None:
    first = _candidate("感烟", (100, 300, 80, 36), 0.96, "rapidocr-tile")
    second = _candidate("手报", (205, 300, 80, 36), 0.95, "rapidocr-tile")

    result = collapse_overlapping_candidates((first, second))

    assert result == (first, second)
