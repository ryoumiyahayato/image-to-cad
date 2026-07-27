from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.ocr_layout import (
    constrain_texts_to_table_cells,
    prepare_candidate_layout,
    tile_regions,
)
from app.ocr_outline_export import accepted_ocr_texts


def _candidate(text: str) -> TextCandidate:
    return TextCandidate(
        text=text,
        bbox=(20, 20, 240, 50),
        confidence=0.99,
        kind="text_candidate",
        quad=((20.0, 20.0), (260.0, 20.0), (260.0, 70.0), (20.0, 70.0)),
        source="rapidocr-consensus",
    )


def test_large_page_uses_overlapping_native_resolution_tiles() -> None:
    regions = tile_regions((10513, 7442))

    assert len(regions) > 1
    assert regions[0][0:2] == (0, 0)
    assert max(right for _left, _top, right, _bottom in regions) == 7442
    assert max(bottom for _left, _top, _right, bottom in regions) == 10513

    scan_regions = tile_regions(
        (3964, 2803),
        tile_size=2560,
        overlap=320,
    )
    assert len(scan_regions) > 1


def test_regular_separated_printed_text_gets_character_boxes_and_auto_export() -> None:
    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    for left in (30, 75, 120, 165, 210):
        cv2.rectangle(image, (left, 30), (left + 20, 60), (0, 0, 0), 2)

    prepared = prepare_candidate_layout(image, _candidate("火灾ABC"))

    assert prepared.replacement_safe
    assert len(prepared.character_boxes) == 5
    assert accepted_ocr_texts((prepared,)) == (prepared,)


def test_connected_high_confidence_text_is_editable_without_manual_confirmation() -> None:
    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    points = np.asarray(
        [[25, 55], [65, 28], [105, 62], [150, 25], [205, 63], [255, 35]],
        dtype=np.int32,
    )
    cv2.polylines(image, [points], False, (0, 0, 0), 5, cv2.LINE_AA)

    prepared = prepare_candidate_layout(image, _candidate("唐忠荣"))

    assert not prepared.replacement_safe
    assert "签名" in prepared.review_note or "手写" in prepared.review_note
    assert accepted_ocr_texts((prepared,)) == (prepared,)

    detected_signature = replace(
        prepared,
        kind="signature_candidate",
        approved=False,
    )
    assert accepted_ocr_texts((detected_signature,)) == ()


def test_reviewed_signature_candidate_still_remains_an_image() -> None:
    detected_signature = replace(
        _candidate("唐忠荣"),
        kind="signature_candidate",
        approved=True,
        reviewed=True,
    )

    assert accepted_ocr_texts((detected_signature,)) == ()


def test_text_box_is_constrained_to_enclosing_table_cell() -> None:
    binary = np.full((220, 320), 255, dtype=np.uint8)
    for x_value in (40, 160, 280):
        cv2.line(binary, (x_value, 30), (x_value, 190), 0, 2)
    for y_value in (30, 100, 190):
        cv2.line(binary, (40, y_value), (280, y_value), 0, 2)
    candidate = TextCandidate(
        text="说明文字",
        bbox=(55, 45, 125, 40),
        confidence=0.99,
        kind="text_candidate",
        source="test",
    )

    constrained = constrain_texts_to_table_cells(binary, (candidate,))[0]

    assert constrained.bbox[0] == 55
    assert constrained.bbox[0] + constrained.bbox[2] < 160
    assert constrained.quad is not None
    assert max(point[0] for point in constrained.quad) < 160
