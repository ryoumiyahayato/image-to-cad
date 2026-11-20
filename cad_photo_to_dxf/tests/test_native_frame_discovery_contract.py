"""A derived frame proposal never changes source pixels or closes source gaps."""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image
import pytest

from app.native_objects import text_regions


def _broken_frame(*, border_gap=2):
    image = np.full((120, 180), 255, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (150, 90), 0, 1)
    image[20, 80 : 80 + border_gap] = 255
    image[42:68, 60:63] = 0
    image[52:54, 60:63] = 255  # Real internal glyph separation, not just the border.
    cv2.rectangle(image, (100, 43), (112, 67), 0, 1)
    roi = [0, 0, image.shape[1], image.shape[0]]
    ink, labels, glyphs = text_regions._component_evidence(image, roi)
    for array in (image, ink, labels):
        array.setflags(write=False)
    return image, ink, labels, glyphs, roi


def test_small_gap_discovery_preserves_immutable_source_and_original_edge_evidence(
    monkeypatch,
):
    image, ink, labels, glyphs, roi = _broken_frame()
    before = [array.copy() for array in (image, ink, labels)]
    original_closing = cv2.morphologyEx
    discovery_maps = []

    def discover(source, operation, kernel):
        assert source is ink and not source.flags.writeable
        assert operation == cv2.MORPH_CLOSE
        assert np.array_equal(kernel, np.ones((3, 3), dtype=np.uint8))
        result = original_closing(source, operation, kernel)
        discovery_maps.append(result.copy())
        return result

    monkeypatch.setattr(cv2, "morphologyEx", discover)
    frames = text_regions._frames(ink, roi)
    assert len(discovery_maps) == 1
    assert discovery_maps[0][20, 80] == 1 and ink[20, 80] == 0
    assert discovery_maps[0][52, 61] == 1 and ink[52, 61] == 0
    assert labels[51, 61] != labels[54, 61] and labels[52, 61] == 0
    assert glyphs
    selected = [
        frame
        for frame in frames
        if frame["enclosure_bbox_xyxy_px"] == [20, 20, 151, 91]
    ]
    assert len(selected) == 1
    frame = selected[0]
    assert frame["contour_discovery_method"] == "3x3_close_for_discovery_only"
    assert frame["edge_support"][0] == pytest.approx(129 / 131)
    assert (
        frame["edge_support"][0] < 1.0
    )  # The two absent source cells remain absent evidence.
    assert frame["source_frame_continuity_proven"] is False
    assert frame["geometry_must_verify_original_four_sides"] is True
    assert frame["source_rule_not_removed"] is True
    for current, original in zip((image, ink, labels), before):
        assert not current.flags.writeable
        np.testing.assert_array_equal(current, original)


def test_even_a_closed_discovery_proposal_cannot_supply_missing_source_edge_support(
    monkeypatch,
):
    image, ink, labels, _, roi = _broken_frame(border_gap=65)
    before = [array.copy() for array in (image, ink, labels)]
    deliberately_closed_proposal = ink.copy()
    deliberately_closed_proposal[20, 20:151] = 1
    assert deliberately_closed_proposal[20, 80] == 1 and ink[20, 80] == 0
    # Make the discovery proposal maximally tempting. Acceptance still has to
    # measure the unmodified source edge, whose support is below the threshold.
    monkeypatch.setattr(
        cv2, "morphologyEx", lambda *args: deliberately_closed_proposal.copy()
    )
    assert text_regions._frames(ink, roi) == []
    for current, original in zip((image, ink, labels), before):
        np.testing.assert_array_equal(current, original)


def test_frame_ocr_receives_original_crop_and_padding_with_internal_white_gap(
    tmp_path, monkeypatch
):
    image, ink, labels, _, roi = _broken_frame()
    before = [array.copy() for array in (image, ink, labels)]
    frame = next(
        frame
        for frame in text_regions._frames(ink, roi)
        if frame["enclosure_bbox_xyxy_px"] == [20, 20, 151, 91]
    )
    x0, y0, x1, y1 = frame["bbox_xyxy_px"]
    crop = image[y0:y1, x0:x1]
    padding = 8
    expected = np.pad(crop, padding, constant_values=255)
    captured = []
    monkeypatch.delenv("I2CAD_RAW_OBSERVATION_CACHE", raising=False)
    monkeypatch.setattr(
        text_regions,
        "_resolve_tesseract",
        lambda *args: {
            "executable": "not-executed-test-recognizer",
            "version": "tesseract test",
        },
    )

    def capture_input(command, **kwargs):
        with Image.open(command[1]) as picture:
            captured.append(np.asarray(picture.convert("L")).copy())
        return SimpleNamespace(stdout="level\ttext\n", stderr="", returncode=0)

    monkeypatch.setattr(text_regions, "run_subprocess", capture_input)
    words, meta = text_regions._ocr(
        image,
        frame["bbox_xyxy_px"],
        7,
        tmp_path,
        "raw-frame-interior",
        None,
        padding_px=padding,
        dpi=200,
    )
    assert words == [] and len(captured) == 1
    np.testing.assert_array_equal(captured[0], expected)
    assert captured[0][52 - y0 + padding, 61 - x0 + padding] == 255
    assert captured[0][51 - y0 + padding, 61 - x0 + padding] == 0
    assert meta["specification"]["source_pixels_modified"] is False
    assert meta["specification"]["padding_replaces_source_pixels"] is False
    for current, original in zip((image, ink, labels), before):
        np.testing.assert_array_equal(current, original)
