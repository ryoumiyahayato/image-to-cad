from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.primitive_text_support_integrity import (
    INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT,
    TextSupportStatus,
    assess_primitive_text_support,
    count_structural_connections,
    qualify_dev_text_support_primitives,
)
from app.text_protection import TextProtectionResult


def _canvas(shape: tuple[int, int] = (220, 420)) -> np.ndarray:
    return np.full(shape, 255, dtype=np.uint8)


def _protection(mask: np.ndarray) -> TextProtectionResult:
    count = 1 if np.any(mask) else 0
    return TextProtectionResult(mask, candidate_component_count=count, text_region_count=count)


def _decision(
    image: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    mask: np.ndarray,
):
    return assess_primitive_text_support(
        image,
        {"start": list(start), "end": list(end)},
        protection=_protection(mask),
    )


@pytest.mark.parametrize(
    ("orientation", "start", "end"),
    [
        ("vertical glyph", (80, 55), (80, 120)),
        ("horizontal glyph", (55, 80), (130, 80)),
        ("digit one", (160, 45), (160, 125)),
        ("Chinese vertical", (230, 50), (230, 125)),
        ("Chinese horizontal", (205, 92), (275, 92)),
    ],
)
def test_isolated_masked_strokes_fail_closed_as_uncertain(
    orientation: str,
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    del orientation
    image = _canvas()
    cv2.line(image, start, end, 0, 2, cv2.LINE_8)
    mask = np.zeros_like(image)
    x0, x1 = sorted((start[0], end[0]))
    y0, y1 = sorted((start[1], end[1]))
    mask[max(0, y0 - 8) : y1 + 9, max(0, x0 - 8) : x1 + 9] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.UNCERTAIN
    assert decision.post_text_removal_support_fraction == 0.0


def test_aligned_glyph_strokes_forming_false_line_are_rejected() -> None:
    image = _canvas()
    mask = np.zeros_like(image)
    for left in (50, 95, 140, 185):
        cv2.line(image, (left, 90), (left + 22, 90), 0, 2, cv2.LINE_8)
        mask[78:103, left - 4 : left + 27] = 255

    decision = _decision(image, (50, 90), (207, 90), mask)

    assert decision.status is TextSupportStatus.REJECTED
    assert decision.text_component_count >= 3


@pytest.mark.parametrize(
    ("start", "end", "mask_box"),
    [
        ((30, 70), (380, 70), (170, 55, 235, 86)),
        ((120, 20), (120, 200), (105, 82, 137, 135)),
    ],
)
def test_real_line_passing_behind_text_keeps_independent_support(
    start: tuple[int, int],
    end: tuple[int, int],
    mask_box: tuple[int, int, int, int],
) -> None:
    image = _canvas()
    cv2.line(image, start, end, 0, 3, cv2.LINE_8)
    mask = np.zeros_like(image)
    x0, y0, x1, y1 = mask_box
    mask[y0:y1, x0:x1] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.INDEPENDENT
    assert decision.reason == INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT
    assert decision.longest_non_text_supported_run_px >= 12


@pytest.mark.parametrize(
    ("name", "line", "text_box"),
    [
        ("table border", ((40, 45), (380, 45)), (120, 65, 280, 110)),
        ("title block border", ((40, 170), (380, 170)), (180, 125, 300, 160)),
        ("dimension line", ((40, 130), (380, 130)), (180, 90, 240, 120)),
        ("grid line", ((300, 20), (300, 200)), (245, 85, 285, 125)),
        ("independent nearby", ((30, 35), (390, 35)), (100, 70, 260, 110)),
    ],
)
def test_legitimate_text_adjacent_lines_are_not_rejected(
    name: str,
    line: tuple[tuple[int, int], tuple[int, int]],
    text_box: tuple[int, int, int, int],
) -> None:
    del name
    image = _canvas()
    cv2.line(image, line[0], line[1], 0, 3, cv2.LINE_8)
    mask = np.zeros_like(image)
    x0, y0, x1, y1 = text_box
    mask[y0:y1, x0:x1] = 255

    assert _decision(image, line[0], line[1], mask).status is TextSupportStatus.INDEPENDENT


def test_line_touching_one_glyph_at_endpoint_is_not_rejected() -> None:
    image = _canvas()
    start, end = (35, 100), (350, 100)
    cv2.line(image, start, end, 0, 2, cv2.LINE_8)
    mask = np.zeros_like(image)
    mask[86:116, 330:371] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.INDEPENDENT


def test_line_partly_overlapping_glyph_without_long_continuation_is_uncertain() -> None:
    image = _canvas()
    start, end = (80, 100), (205, 100)
    cv2.line(image, start, end, 0, 2, cv2.LINE_8)
    mask = np.zeros_like(image)
    mask[84:117, 110:196] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.UNCERTAIN


def test_noisy_scan_with_ocr_mask_error_fails_uncertain_not_rejected() -> None:
    image = _canvas()
    start, end = (80, 110), (260, 110)
    cv2.line(image, start, end, 0, 2, cv2.LINE_8)
    image[108:113, 145:190] = 255
    for x in range(80, 261, 17):
        image[109:112, x : x + 3] = 0
    mask = np.zeros_like(image)
    mask[92:128, 95:245] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.UNCERTAIN


def test_thick_real_line_under_text_is_preserved() -> None:
    image = _canvas()
    start, end = (20, 150), (400, 150)
    cv2.line(image, start, end, 0, 9, cv2.LINE_8)
    mask = np.zeros_like(image)
    mask[125:176, 170:250] = 255

    decision = _decision(image, start, end, mask)

    assert decision.status is TextSupportStatus.INDEPENDENT
    assert decision.reason == INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT


def test_two_parallel_lines_with_text_between_are_preserved() -> None:
    image = _canvas()
    upper = ((30, 65), (390, 65))
    lower = ((30, 145), (390, 145))
    cv2.line(image, *upper, 0, 3, cv2.LINE_8)
    cv2.line(image, *lower, 0, 3, cv2.LINE_8)
    mask = np.zeros_like(image)
    mask[85:125, 120:300] = 255

    assert _decision(image, *upper, mask).status is TextSupportStatus.INDEPENDENT
    assert _decision(image, *lower, mask).status is TextSupportStatus.INDEPENDENT


def test_fully_masked_table_border_is_preserved_by_structural_network() -> None:
    image = _canvas()
    border = {"start": [50, 100], "end": [370, 100]}
    peers = [
        {"start": [90, 30], "end": [90, 180]},
        {"start": [210, 30], "end": [210, 180]},
        {"start": [330, 30], "end": [330, 180]},
    ]
    cv2.line(image, tuple(border["start"]), tuple(border["end"]), 0, 2, cv2.LINE_8)
    for peer in peers:
        cv2.line(image, tuple(peer["start"]), tuple(peer["end"]), 0, 2, cv2.LINE_8)
    mask = np.full_like(image, 255)
    connections = count_structural_connections(image.shape, border, peers)

    decision = assess_primitive_text_support(
        image,
        border,
        protection=_protection(mask),
        structural_connection_count=connections,
    )

    assert connections == 3
    assert decision.status is TextSupportStatus.INDEPENDENT
    assert decision.reason == INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT


def test_dev_partition_preserves_prior_integrity_metadata_for_uncertain() -> None:
    image = _canvas()
    glyph = {"start": [70, 80], "end": [160, 80]}
    cv2.line(image, tuple(glyph["start"]), tuple(glyph["end"]), 0, 2, cv2.LINE_8)
    # Use the repository detector in this composition test by adding adjacent
    # glyph strokes so the deterministic text-region mask exists.
    for y in (64, 96):
        for x in (70, 100, 130, 160):
            cv2.line(image, (x, y), (x + 12, y), 0, 2, cv2.LINE_8)
    record = {
        "id": "raw-hough-synthetic",
        "raw_geometry": glyph,
        "span_integrity": {"status": "SPAN_INTEGRITY_SUPPORTED"},
        "axis_support_integrity": {"status": "PRIMITIVE_AXIS_SUPPORTED"},
    }

    mask = np.zeros_like(image)
    mask[55:106, 55:181] = 255
    buckets = qualify_dev_text_support_primitives(
        image,
        [record],
        protection=_protection(mask),
    )

    assert not buckets["independent"]
    assert buckets["uncertain"][0]["id"] == record["id"]
    assert not buckets["rejected"]
    assert buckets["uncertain"][0]["span_integrity"] == record["span_integrity"]
    assert buckets["uncertain"][0]["axis_support_integrity"] == record["axis_support_integrity"]
