from __future__ import annotations

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.content_ownership import (
    binary_from_foreground,
    graphic_source_mask,
    partition_content,
)
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.signature_overlay import mark_graphic_texts


def test_every_source_pixel_gets_exactly_one_owner() -> None:
    binary = np.full((180, 320), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 20), (310, 160), 0, 3)
    cv2.line(binary, (10, 90), (310, 90), 0, 3)
    cv2.putText(
        binary,
        "TITLE",
        (70, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        0,
        2,
        cv2.LINE_8,
    )
    text = TextCandidate(
        text="TITLE",
        bbox=(65, 52, 100, 35),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=True,
    )
    lines = (
        LineSegment(10.0, 20.0, 310.0, 20.0, width=3.0),
        LineSegment(10.0, 90.0, 310.0, 90.0, width=3.0),
        LineSegment(10.0, 160.0, 310.0, 160.0, width=3.0),
        LineSegment(10.0, 20.0, 10.0, 160.0, width=3.0),
        LineSegment(310.0, 20.0, 310.0, 160.0, width=3.0),
    )

    ownership = partition_content(
        binary,
        lines=lines,
        texts=(text,),
        signatures=(),
    )

    ownership.assert_valid()
    assert ownership.line[90, 150] == 255
    assert cv2.countNonZero(ownership.text) > 0
    assert not np.any((ownership.line > 0) & (ownership.text > 0))
    assert np.count_nonzero(ownership.source) == sum(
        np.count_nonzero(mask)
        for mask in (
            ownership.line,
            ownership.text,
            ownership.graphic,
            ownership.signature,
            ownership.residual,
        )
    )


def test_unsafe_text_stays_residual_instead_of_becoming_an_image_class() -> None:
    binary = np.full((120, 260), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "ABC",
        (30, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text="ABC",
        bbox=(25, 35, 100, 50),
        confidence=0.93,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=False,
        review_note="connected to nearby source strokes",
    )
    marked = mark_graphic_texts((candidate,), page_shape=binary.shape)

    ownership = partition_content(
        binary,
        lines=(),
        texts=marked,
        signatures=(),
    )

    assert marked[0].kind == "text_candidate"
    assert cv2.countNonZero(ownership.graphic) == 0
    assert cv2.countNonZero(ownership.text) == 0
    assert cv2.countNonZero(ownership.residual) == cv2.countNonZero(
        np.where(binary < 128, 255, 0).astype(np.uint8)
    )


def test_logo_owns_source_strokes_but_not_surrounding_cell_rules() -> None:
    binary = np.full((260, 420), 255, dtype=np.uint8)
    cv2.rectangle(binary, (20, 20), (400, 240), 0, 3)
    cv2.line(binary, (20, 190), (400, 190), 0, 3)
    cv2.putText(
        binary,
        "DESIGN GROUP",
        (75, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        0,
        2,
        cv2.LINE_8,
    )
    logo_bbox = (70, 120, 220, 40)
    x, y, width, height = logo_bbox
    logo_mask = np.where(
        binary[y : y + height, x : x + width] < 128,
        255,
        0,
    ).astype(np.uint8)
    logo = LogoRegion(
        bbox=logo_bbox,
        mask=logo_mask,
        structural_score=0.9,
        hole_count=2,
        contour_count=4,
    )

    graphic = graphic_source_mask(binary, (logo,))

    assert cv2.countNonZero(graphic) > 0
    assert graphic[190, 200] == 0
    contour_binary = binary_from_foreground(graphic)
    assert np.count_nonzero(contour_binary[120:160, 70:290] == 0) > 40
