"""Ordinary cleanup removes scanner artifacts while preserving useful ink."""
import cv2
import numpy as np
import pytest

from app.geometry.scan_cleanup import paper_ink_alpha, prepare_scan_page


def test_dense_dust_is_removed_by_default_but_rules_and_punctuation_remain():
    source = np.full((320, 420), 255, np.uint8)
    dust = [(y, x) for y in range(80, 232, 8) for x in range(190, 358, 8)]
    for y, x in dust:
        source[y, x] = 0
    source[120:134, 240:244] = 0
    source[134, 246] = 0  # punctuation beside a larger printed glyph
    source[270, 70] = 0  # isolated punctuation, away from dense dust
    source[285, 20:360] = 180  # one-pixel, light engineering rule
    before = source.copy()
    result = prepare_scan_page(source)
    assert sum(result.binary[y, x] == 255 for y, x in dust) > len(dust)*.85
    assert result.binary[134, 246] == 0
    assert result.binary[270, 70] == 0
    assert np.all(result.binary[285, 20:360] == 0)
    assert np.array_equal(source, before)


def _gray_sheet():
    image = np.tile(np.linspace(220, 245, 400, dtype=np.uint8), (320, 1))
    image[30:290, 190:202] = 145  # broad, pale fold/tape trace
    image[30:290, 70] = 145  # a thin rule of the same tone must remain
    image[100, 20:370] = 20
    image[250:252, 40:42] = 20
    return image


def test_pale_broad_artifact_is_removed_without_erasing_thin_rule_or_dark_crossing():
    result = prepare_scan_page(_gray_sheet())
    assert result.binary[80, 195] == 255
    assert np.all(result.binary[100, 20:370] == 0)
    assert np.all(result.binary[40:280, 70] == 0)
    assert np.all(result.binary[250:252, 40:42] == 0)


def test_manual_protection_keeps_selected_ink_while_cleanup_runs_elsewhere():
    source = _gray_sheet()
    protected = np.zeros(source.shape, np.uint8)
    protected[60:90, 190:202] = 255
    result = prepare_scan_page(source, protected_mask=protected)
    assert np.all(result.binary[60:90, 190:202] == 0)
    assert result.binary[180, 195] == 255
    assert np.count_nonzero(protected) == 30*12


def test_clean_digital_and_explicit_threshold_keep_their_ink():
    digital = np.full((96, 128), 255, np.uint8)
    digital[20:65, 50] = 0
    digital[80, 110] = 192
    digital[8, 8] = 0
    actual = prepare_scan_page(digital)
    assert actual.clean_digital
    assert np.array_equal(actual.binary, np.where(digital < 255, 0, 255))
    scan = _gray_sheet()
    explicit = prepare_scan_page(scan, foreground_threshold=200)
    assert np.array_equal(explicit.binary, np.where(scan <= 200, 0, 255))


def test_gray_paper_alpha_removes_background_but_keeps_hairline_and_filled_logo():
    image = np.full((240, 300, 3), 220, np.uint8)
    cv2.line(image, (50, 75), (90, 120), (25, 25, 25), 1)
    cv2.rectangle(image, (105, 80), (155, 125), (30, 30, 30), -1)
    alpha = paper_ink_alpha(image, (40, 60, 170, 150))
    assert alpha[5, 5] == 0
    assert alpha[15, 10] > 200
    assert alpha[40, 90] > 200
    assert np.count_nonzero(alpha == 0) > alpha.size*.65


def test_faint_colored_stamp_and_thin_ink_keep_soft_opacity_on_gray_paper():
    image = np.full((180, 240, 3), 235, np.uint8)
    cv2.circle(image, (120, 90), 32, (210, 210, 240), 1)
    cv2.line(image, (100, 90), (140, 90), (220, 220, 220), 1)
    alpha = paper_ink_alpha(image, (75, 45, 165, 135))
    assert alpha[5, 5] == 0
    assert 0 < alpha[45, 13] < 100
    assert 0 < alpha[45, 45] < 100
    assert np.count_nonzero(alpha == 0) > alpha.size*.90


@pytest.mark.parametrize("mask", [np.ones((2, 2), bool), np.ones((20, 30), float)])
def test_invalid_protected_mask_is_rejected(mask):
    with pytest.raises(ValueError, match="source-sized"):
        prepare_scan_page(np.full((20, 30), 255, np.uint8), protected_mask=mask)
