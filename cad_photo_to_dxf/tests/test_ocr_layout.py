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


def test_connected_high_confidence_text_stays_as_image_until_reviewed() -> None:
    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    points = np.asarray(
        [[25, 55], [65, 28], [105, 62], [150, 25], [205, 63], [255, 35]],
        dtype=np.int32,
    )
    cv2.polylines(image, [points], False, (0, 0, 0), 5, cv2.LINE_AA)

    prepared = prepare_candidate_layout(image, _candidate("唐忠荣"))

    assert not prepared.replacement_safe
    assert "跨越多个字符格" in prepared.review_note
    assert accepted_ocr_texts((prepared,)) == ()
    reviewed = replace(prepared, reviewed=True)
    assert accepted_ocr_texts((reviewed,)) == (reviewed,)

    non_text_object = replace(
        prepared,
        kind="unclassified_candidate",
        approved=False,
    )
    assert accepted_ocr_texts((non_text_object,)) == ()


def test_review_cannot_turn_a_non_text_object_into_ocr_text() -> None:
    non_text_object = replace(
        _candidate("唐忠荣"),
        kind="unclassified_candidate",
        approved=True,
        reviewed=True,
    )

    assert accepted_ocr_texts((non_text_object,)) == ()


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


def test_grossly_wide_text_box_is_still_clipped_to_its_cell() -> None:
    binary = np.full((220, 420), 255, dtype=np.uint8)
    for x_value in (40, 160, 280, 400):
        cv2.line(binary, (x_value, 30), (x_value, 190), 0, 2)
    for y_value in (30, 100, 190):
        cv2.line(binary, (40, y_value), (400, y_value), 0, 2)
    candidate = TextCandidate(
        text="项目名称",
        bbox=(70, 45, 245, 40),
        confidence=0.99,
        kind="text_candidate",
        source="test",
    )

    constrained = constrain_texts_to_table_cells(binary, (candidate,))[0]

    assert constrained.bbox[0] > 160
    assert constrained.bbox[0] + constrained.bbox[2] < 280


def test_text_policy_does_not_depend_on_page_margin_position() -> None:
    binary = np.full((1000, 1000), 255, dtype=np.uint8)
    for x_value in (880, 925, 970, 995):
        cv2.line(binary, (x_value, 600), (x_value, 900), 0, 2)
    for y_value in range(600, 901, 40):
        cv2.line(binary, (880, y_value), (995, y_value), 0, 2)
    title_candidate = TextCandidate(
        text="梅晚虹",
        bbox=(930, 650, 38, 22),
        confidence=0.99,
        kind="text_candidate",
        source="test",
    )
    drawing_candidate = replace(
        title_candidate,
        bbox=(430, 650, 38, 22),
    )

    title, drawing = constrain_texts_to_table_cells(
        binary,
        (title_candidate, drawing_candidate),
    )

    assert title.approved == drawing.approved
    assert title.replacement_safe == drawing.replacement_safe
    assert title.text == drawing.text


def test_ocr_content_is_not_corrected_from_a_fixed_field_dictionary() -> None:
    binary = np.full((1000, 1000), 255, dtype=np.uint8)
    for x_value in (880, 925, 970, 995):
        cv2.line(binary, (x_value, 600), (x_value, 900), 0, 2)
    for y_value in range(600, 901, 40):
        cv2.line(binary, (880, y_value), (995, y_value), 0, 2)
    wrong_label = TextCandidate(
        text="会格",
        bbox=(885, 610, 35, 22),
        confidence=0.70,
        kind="text_candidate",
        source="rapidocr-tile",
    )
    drawing_code = replace(
        wrong_label,
        text="T08028-ZL",
        bbox=(930, 650, 60, 22),
        confidence=0.999,
    )

    label, code = constrain_texts_to_table_cells(
        binary,
        (wrong_label, drawing_code),
    )

    assert label.text == "会格"
    assert label.replacement_safe
    assert label.source == "rapidocr-tile"
    assert accepted_ocr_texts((label,)) == (label,)
    assert code.text == "T08028-ZL"
    assert code.replacement_safe
    assert accepted_ocr_texts((code,)) == (code,)


def test_source_tags_do_not_trigger_template_inference_or_deduplication() -> None:
    binary = np.full((1000, 1000), 255, dtype=np.uint8)
    for x_value in (880, 925, 970, 995):
        cv2.line(binary, (x_value, 600), (x_value, 900), 0, 2)
    for y_value in range(600, 901, 40):
        cv2.line(binary, (880, y_value), (995, y_value), 0, 2)
    template = TextCandidate(
        text="建设单位",
        bbox=(885, 645, 70, 30),
        confidence=0.99,
        kind="text_candidate",
        source="rapidocr-title-block-template",
        replacement_safe=False,
    )
    shifted_ocr = replace(
        template,
        bbox=(887, 660, 65, 18),
        confidence=0.995,
        source="rapidocr-title-block",
        replacement_safe=True,
    )
    drawing_number = replace(
        template,
        text="图号",
        bbox=(930, 730, 38, 22),
    )

    constrained = constrain_texts_to_table_cells(
        binary,
        (template, shifted_ocr, drawing_number),
    )

    assert [item.text for item in constrained].count("建设单位") == 2
    assert constrained[0].source == "rapidocr-title-block-template"
    assert not constrained[0].replacement_safe
    assert constrained[1].source == "rapidocr-title-block"
    assert constrained[1].replacement_safe
    assert constrained[2].text == "图号"
    assert not constrained[2].replacement_safe
