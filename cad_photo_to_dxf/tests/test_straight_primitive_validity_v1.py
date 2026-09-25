from __future__ import annotations

import cv2
import numpy as np
import pytest
from cad_photo_to_dxf.app.primitive_text_support_integrity import (
    TextSupportStatus,
    assess_primitive_text_support,
)
from cad_photo_to_dxf.app.straight_primitive_validity import (
    StraightValidityReason,
    StraightValidityStatus,
    assess_straight_primitive_validity,
    qualify_dev_straight_primitives,
)
from cad_photo_to_dxf.app.text_protection import TextProtectionResult

HORIZONTAL = {"start": [20, 90], "end": [260, 90]}
VERTICAL = {"start": [90, 20], "end": [90, 200]}


def _canvas(width: int = 280, height: int = 220) -> np.ndarray:
    return np.full((height, width), 255, np.uint8)


@pytest.mark.parametrize("geometry", [HORIZONTAL, VERTICAL])
def test_straight_horizontal_and_vertical_strokes_are_supported(geometry) -> None:
    image = _canvas()
    cv2.line(image, tuple(geometry["start"]), tuple(geometry["end"]), 0, 2)
    decision = assess_straight_primitive_validity(image, geometry)
    assert decision.status is StraightValidityStatus.SUPPORTED
    assert decision.reason is StraightValidityReason.CONFIRMED


def test_shallow_curved_contour_is_not_declared_straight() -> None:
    image = _canvas()
    points = np.asarray(
        [[x, 88 + round(3.0 * ((x - 140) / 120) ** 2)] for x in range(20, 261)],
        np.int32,
    )
    cv2.polylines(image, [points], False, 0, 3, cv2.LINE_AA)
    decision = assess_straight_primitive_validity(image, HORIZONTAL)
    assert decision.status is not StraightValidityStatus.SUPPORTED


def test_stronger_curved_contour_is_rejected() -> None:
    image = _canvas()
    geometry = {"start": [80, 90], "end": [200, 90]}
    points = np.asarray(
        [[x, 84 + round(10.0 * ((x - 140) / 60) ** 2)] for x in range(80, 201)],
        np.int32,
    )
    cv2.polylines(image, [points], False, 0, 5, cv2.LINE_AA)
    decision = assess_straight_primitive_validity(image, geometry)
    assert decision.status is StraightValidityStatus.REJECTED
    assert decision.reason is StraightValidityReason.CURVED


def test_piecewise_offset_line_is_rejected() -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (135, 90), 0, 2)
    cv2.line(image, (140, 96), (260, 96), 0, 2)
    cv2.line(image, (135, 90), (140, 96), 0, 1)
    decision = assess_straight_primitive_validity(image, HORIZONTAL)
    assert decision.status is StraightValidityStatus.REJECTED


def test_two_nearby_boundaries_switching_support_are_rejected() -> None:
    image = _canvas()
    cv2.line(image, (20, 87), (145, 87), 0, 2)
    cv2.line(image, (120, 94), (260, 94), 0, 2)
    decision = assess_straight_primitive_validity(image, HORIZONTAL)
    assert decision.status is StraightValidityStatus.REJECTED


def test_line_crossing_another_line_remains_supported() -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (260, 90), 0, 2)
    cv2.line(image, (140, 35), (140, 150), 0, 3)
    assert (
        assess_straight_primitive_validity(image, HORIZONTAL).status
        is StraightValidityStatus.SUPPORTED
    )


def test_line_crossing_oblique_stroke_remains_supported() -> None:
    image = _canvas()
    cv2.line(image, (20, 110), (260, 110), 0, 2)
    cv2.line(image, (90, 35), (190, 185), 0, 2)
    decision = assess_straight_primitive_validity(
        image, {"start": [20, 110], "end": [260, 110]}
    )
    assert decision.status is StraightValidityStatus.SUPPORTED


def test_line_crossing_hatch_remains_supported() -> None:
    image = _canvas()
    cv2.line(image, (20, 110), (260, 110), 0, 2)
    for x in range(55, 240, 28):
        cv2.line(image, (x - 10, 90), (x + 10, 130), 0, 1)
    decision = assess_straight_primitive_validity(
        image, {"start": [20, 110], "end": [260, 110]}
    )
    assert decision.status is StraightValidityStatus.SUPPORTED


def test_two_nearby_crossings_remain_supported() -> None:
    image = _canvas()
    cv2.line(image, (20, 110), (260, 110), 0, 2)
    cv2.line(image, (125, 55), (125, 165), 0, 2)
    cv2.line(image, (145, 55), (145, 165), 0, 2)
    decision = assess_straight_primitive_validity(
        image, {"start": [20, 110], "end": [260, 110]}
    )
    assert decision.status is StraightValidityStatus.SUPPORTED


def test_line_through_filled_node_remains_supported() -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (260, 90), 0, 2)
    cv2.rectangle(image, (134, 84), (146, 96), 0, -1)
    assert (
        assess_straight_primitive_validity(image, HORIZONTAL).status
        is StraightValidityStatus.SUPPORTED
    )


@pytest.mark.parametrize("kind", ["table", "title-block", "dimension-grid"])
def test_structural_borders_and_dimension_grid_lines_survive(kind: str) -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (260, 90), 0, 2)
    if kind == "table":
        for x in (50, 110, 170, 230):
            cv2.line(image, (x, 55), (x, 130), 0, 1)
    elif kind == "title-block":
        cv2.rectangle(image, (20, 55), (260, 130), 0, 2)
    else:
        for x in (70, 140, 210):
            cv2.line(image, (x, 78), (x, 102), 0, 1)
            cv2.circle(image, (x, 90), 3, 0, 1)
    assert (
        assess_straight_primitive_validity(image, HORIZONTAL).status
        is StraightValidityStatus.SUPPORTED
    )


def test_actual_straight_edge_inside_symbol_survives() -> None:
    image = _canvas()
    cv2.rectangle(image, (20, 90), (260, 155), 0, -1)
    geometry = {"start": [20, 90], "end": [260, 90]}
    assert (
        assess_straight_primitive_validity(image, geometry).status
        is StraightValidityStatus.SUPPORTED
    )


def test_noisy_but_straight_scan_line_survives() -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (260, 90), 25, 2, cv2.LINE_AA)
    noise = np.random.default_rng(9102).normal(0.0, 8.0, image.shape)
    image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    assert (
        assess_straight_primitive_validity(image, HORIZONTAL).status
        is StraightValidityStatus.SUPPORTED
    )


def test_text_rejected_primitive_never_reaches_straight_gate() -> None:
    image = _canvas()
    mask = np.zeros_like(image)
    for left in (40, 90, 140, 190):
        cv2.line(image, (left, 90), (left + 24, 90), 0, 2)
        mask[78:103, left - 4 : left + 29] = 255
    geometry = {"start": [40, 90], "end": [214, 90]}
    text = assess_primitive_text_support(
        image,
        geometry,
        protection=TextProtectionResult(mask, 4, 4),
    )
    assert text.status is TextSupportStatus.REJECTED
    text_eligible: list[dict[str, object]] = []
    straight = qualify_dev_straight_primitives(image, text_eligible)
    assert all(not values for values in straight.values())


def test_bucket_preserves_upstream_metadata_and_never_mutates_geometry() -> None:
    image = _canvas()
    cv2.line(image, (20, 90), (260, 90), 0, 2)
    record = {
        "id": "raw-hough-synthetic",
        "raw_geometry": {"start": [20, 90], "end": [260, 90]},
        "span_integrity": {"status": "SPAN_INTEGRITY_SUPPORTED"},
        "axis_support_integrity": {"status": "PRIMITIVE_AXIS_SUPPORTED"},
        "text_support_integrity": {"status": "TEXT_INDEPENDENT"},
    }
    before = {key: value.copy() if isinstance(value, dict) else value for key, value in record.items()}
    buckets = qualify_dev_straight_primitives(image, [record])
    assert buckets["supported"][0]["id"] == record["id"]
    assert buckets["supported"][0]["text_support_integrity"] == record["text_support_integrity"]
    assert record == before
