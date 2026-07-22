from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.ocr_layout import prepare_candidate_layout, tile_regions
from app.ocr_outline_export import accepted_ocr_texts


def _candidate(text: str) -> TextCandidate:
    return TextCandidate(
        text=text,
        bbox=(20, 20, 240, 50),
        confidence=0.99,
        kind="text_candidate",
        quad=((20.0, 20.0), (260.0, 20.0), (260.0, 70.0), (20.0, 70.0)),
        source="synthetic",
    )


def test_large_page_uses_overlapping_native_resolution_tiles() -> None:
    regions = tile_regions((10513, 7442))

    assert len(regions) > 1
    assert regions[0][0:2] == (0, 0)
    assert max(right for _left, _top, right, _bottom in regions) == 7442
    assert max(bottom for _left, _top, _right, bottom in regions) == 10513


def test_regular_separated_printed_text_gets_character_boxes_and_auto_export() -> None:
    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    for left in (30, 75, 120, 165, 210):
        cv2.rectangle(image, (left, 30), (left + 20, 60), (0, 0, 0), 2)

    prepared = prepare_candidate_layout(image, _candidate("火灾ABC"))

    assert prepared.replacement_safe
    assert len(prepared.character_boxes) == 5
    assert accepted_ocr_texts((prepared,)) == (prepared,)


def test_connected_signature_stays_as_original_trace_until_manual_confirmation() -> None:
    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    points = np.asarray(
        [[25, 55], [65, 28], [105, 62], [150, 25], [205, 63], [255, 35]],
        dtype=np.int32,
    )
    cv2.polylines(image, [points], False, (0, 0, 0), 5, cv2.LINE_AA)

    prepared = prepare_candidate_layout(image, _candidate("唐忠荣"))

    assert not prepared.replacement_safe
    assert "签名" in prepared.review_note or "手写" in prepared.review_note
    assert accepted_ocr_texts((prepared,)) == ()

    confirmed = replace(prepared, reviewed=True, approved=True)
    assert accepted_ocr_texts((confirmed,)) == (confirmed,)
