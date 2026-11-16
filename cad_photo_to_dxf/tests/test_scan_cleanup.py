from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.geometry.scan_cleanup import prepare_scan_page


def test_damaged_scan_cleanup_removes_paper_shading_but_keeps_ink() -> None:
    height, width = 700, 1000
    x_gradient = np.linspace(218, 248, width, dtype=np.float32)
    gray = np.repeat(x_gradient[None, :], height, axis=0)

    yy, xx = np.mgrid[:height, :width]
    broad_stain = 34.0 * np.exp(
        -(((xx - 170.0) / 180.0) ** 2 + ((yy - 180.0) / 150.0) ** 2)
    )
    gray = np.clip(gray - broad_stain, 0, 255).astype(np.uint8)

    cv2.rectangle(gray, (260, 180), (820, 530), 35, 3)
    cv2.line(gray, (300, 350), (780, 350), 55, 2, cv2.LINE_AA)
    cv2.putText(
        gray,
        "A1 100",
        (360, 310),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        35,
        2,
        cv2.LINE_AA,
    )
    cv2.polylines(
        gray,
        [np.asarray([(620, 590), (650, 555), (675, 600), (710, 565)], np.int32)],
        False,
        45,
        2,
        cv2.LINE_AA,
    )

    prepared = prepare_scan_page(gray)

    assert not prepared.clean_digital
    assert prepared.binary[180, 400] == 0
    assert prepared.binary[350, 500] == 0
    assert prepared.binary[590, 620] == 0
    assert prepared.binary[170, 170] == 255
    assert np.count_nonzero(prepared.binary == 0) < prepared.binary.size * 0.08


def test_tiled_component_filter_keeps_strokes_across_tile_boundaries() -> None:
    gray = np.full((420, 4300), 235, dtype=np.uint8)
    cv2.line(gray, (100, 210), (4200, 210), 95, 3, cv2.LINE_AA)
    for x_value in range(100, 4201, 300):
        cv2.circle(gray, (x_value, 210), 3, 35, -1)

    prepared = prepare_scan_page(gray)

    assert prepared.binary[210, 2048] == 0
    assert prepared.binary[210, 4096] == 0
    assert prepared.binary[80, 2048] == 255


def test_clean_digital_page_still_keeps_every_non_white_pixel() -> None:
    image = np.full((120, 180), 255, dtype=np.uint8)
    image[40, 50] = 254
    image[60, 80] = 120

    prepared = prepare_scan_page(image)

    assert prepared.clean_digital
    assert prepared.threshold == 254
    assert prepared.binary[40, 50] == 0
    assert prepared.binary[60, 80] == 0


def test_sparse_bitonal_scan_uses_local_dust_to_override_white_background() -> None:
    gray = np.full((256, 256), 255, dtype=np.uint8)
    gray[24:145:10, 24:145:10] = 0
    gray[180, 15:230] = 0
    gray[220, 200] = 0

    prepared = prepare_scan_page(gray)

    assert prepared.classification_reason == "dense_isolated_specks"
    assert prepared.binary[84, 84] == 0
    assert (84, 84, 85) in prepared.unconfirmed_noise_runs
    assert np.all(prepared.binary[180, 15:230] == 0)
    assert prepared.binary[220, 200] == 0
    manual = prepare_scan_page(gray, foreground_threshold=254)
    assert np.array_equal(manual.binary, gray)


@pytest.mark.parametrize(
    ("pdf_content", "reason"),
    [
        (None, "dense_isolated_specks"),
        ("mixed", "dense_isolated_specks"),
        ("raster", "pdf_page_raster"),
    ],
)
def test_dust_cleanup_preserves_faint_source_ink_between_dark_strokes(
    pdf_content, reason
) -> None:
    gray = np.full((256, 256), 255, dtype=np.uint8)
    gray[24:145:10, 24:145:10] = 0
    gray[180, 15:230] = 20
    gray[180, 110:122] = 250

    prepared = prepare_scan_page(gray, pdf_content=pdf_content)

    assert not prepared.clean_digital
    assert prepared.classification_reason == reason
    assert np.all(prepared.binary[180, 15:230] == 0)
    assert prepared.binary[84, 84] == 0
    assert (84, 84, 85) in prepared.unconfirmed_noise_runs


@pytest.fixture
def dusty_crop():
    dust = np.zeros((256, 256), dtype=bool)
    dust[24:145:10, 24:145:10] = True
    dust[63:100, 66:118] = False
    gray = np.where(dust, 40, 255).astype(np.uint8)
    return gray, dust


def test_confirmed_dust_does_not_shorten_branch_or_thin_pale_strokes(dusty_crop) -> None:
    gray, dust = dusty_crop
    gray[72:75, 75:108] = 40
    gray[67:72, 91] = 225
    gray[85:87, 78:106] = 242

    prepared = prepare_scan_page(gray, confirmed_noise=dust)

    assert np.all(prepared.binary[67:75, 91] == 0)
    assert np.array_equal(prepared.binary[71:76, 102], [255, 0, 0, 0, 255])
    assert np.all(prepared.binary[85:87, 78:106] == 0)
    assert np.all(prepared.gray[85:87, 78:106] == 242)
    assert prepared.binary[84, 54] == 255
    assert np.array_equal(prepared.binary == 0, (gray < 255) & ~dust)


def test_confirmed_dust_does_not_open_a_faint_closed_loop(dusty_crop) -> None:
    gray, dust = dusty_crop
    cv2.rectangle(gray, (79, 69), (98, 87), 220, 1)
    gray[69, 88] = 250

    prepared = prepare_scan_page(gray, confirmed_noise=dust)

    background = np.uint8(prepared.binary[67:90, 77:101] == 255)
    _, regions = cv2.connectedComponents(background, connectivity=4)
    assert regions[8, 8] != 0
    assert regions[8, 8] != regions[0, 0]
    assert prepared.binary[84, 54] == 255
    assert np.array_equal(prepared.binary == 0, (gray < 255) & ~dust)


def test_dust_lookalikes_remain_marked_as_punctuation_and_small_nodes(dusty_crop) -> None:
    gray, dust = dusty_crop
    gray[80, 80] = 40
    gray[88, 102:104] = 192

    prepared = prepare_scan_page(gray, confirmed_noise=dust)

    assert (80, 80, 81) in prepared.unconfirmed_noise_runs
    assert (88, 102, 104) in prepared.unconfirmed_noise_runs
    assert prepared.binary[84, 54] == 255
    assert np.array_equal(prepared.binary == 0, (gray < 255) & ~dust)


def test_native_scan_dust_requires_low_component_and_blank_region_agreement(monkeypatch) -> None:
    from app.geometry import scan_dust

    monkeypatch.setattr(scan_dust, "ORIGINAL_TILE_SIZE", 16)
    original = np.full((64, 64), 255, dtype=np.uint8)
    original[20, [19, 20]] = 0  # A tiny source component crosses a tile seam.
    original[26, 19] = 0
    original[26:30, 21:23] = 0  # A separate original stroke shares the low component.
    original[45, 45] = 0       # An isolated mark outside reviewed blank paper.
    low = cv2.resize(original, (32, 32), interpolation=cv2.INTER_AREA)
    approved, status = scan_dust.confirm_scan_dust(
        low, original, 100, 200, [(2, 2, 25, 20)]
    )

    assert status == "VERIFIED_ORIGINAL_GRID"
    assert approved is not None
    assert np.argwhere(approved).tolist() == [[10, 9], [10, 10]]


def test_upsampled_100dpi_pixels_cannot_confirm_dust() -> None:
    from app.geometry.scan_dust import confirm_scan_dust

    low = np.full((32, 32), 255, dtype=np.uint8)
    low[10, 10] = 0
    enlarged = np.repeat(np.repeat(low, 2, axis=0), 2, axis=1)
    approved, _ = confirm_scan_dust(low, enlarged, 100, 200, [(2, 2, 25, 25)])

    assert approved is not None
    assert not np.any(approved)


def test_mixed_cleanup_retains_only_vector_pixels_still_visible_in_source() -> None:
    gray = np.full((128, 128), 235, dtype=np.uint8)
    proof = np.full_like(gray, 255)
    gray[40, 15:110] = 229
    proof[40:42, 15:110] = 229

    cleaned = prepare_scan_page(gray, pdf_content="mixed")
    protected = prepare_scan_page(gray, pdf_content="mixed", mixed_vector_gray=proof)

    assert np.all(cleaned.binary[40:42, 15:110] == 255)
    assert np.all(protected.binary[40, 15:110] == 0)
    assert np.all(protected.binary[41, 15:110] == 255)


def test_sparse_gray_paper_far_from_dark_ink_triggers_scan_cleanup() -> None:
    gray = np.full((256, 256), 255, dtype=np.uint8)
    gray[24:72, 32:96] = np.tile([239, 244, 249, 253], 16)
    gray[180, 15:230] = 35

    prepared = prepare_scan_page(gray)

    assert prepared.classification_reason == "gray_paper_background"
    assert np.all(prepared.binary[24:72, 32:96] == 255)
    assert np.all(prepared.binary[180, 15:230] == 0)


def test_scanned_objects_separated_by_one_pixel_are_not_welded_together() -> None:
    gray = np.full((120, 180), 235, dtype=np.uint8)
    gray[50:70, 50:60] = 35
    gray[50:70, 61:71] = 35

    prepared = prepare_scan_page(gray)

    assert not prepared.clean_digital
    assert prepared.binary[60, 59] == 0
    assert prepared.binary[60, 60] == 255
    assert prepared.binary[60, 61] == 0


def test_confirmed_scanner_speckle_is_removed_without_erasing_real_ink() -> None:
    gray = np.full((700, 1000), 238, dtype=np.uint8)
    for y_value in range(180, 421, 12):
        for x_value in range(140, 381, 12):
            gray[y_value, x_value] = 20
    cv2.line(gray, (520, 240), (900, 240), 35, 3, cv2.LINE_AA)
    cv2.putText(
        gray,
        "A1",
        (600, 390),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        30,
        3,
        cv2.LINE_AA,
    )

    known_speckle = np.zeros_like(gray, dtype=bool)
    known_speckle[180:421:12, 140:381:12] = True
    prepared = prepare_scan_page(gray, confirmed_noise=known_speckle)

    speckle_region = prepared.binary[150:450, 110:410]
    assert np.count_nonzero(speckle_region == 0) < 80
    assert prepared.binary[240, 700] == 0
    assert np.count_nonzero(prepared.binary[330:410, 580:700] == 0) > 50


def test_broad_low_contrast_tape_edges_are_not_exported_as_lines() -> None:
    height, width = 900, 1200
    gray = np.full((height, width), 235, dtype=np.float32)
    _yy, xx = np.mgrid[:height, :width]
    gray -= 26.0 * np.exp(-(((xx - 760.0) / 45.0) ** 2))
    cv2.line(gray, (710, 80), (710, 820), 150, 3, cv2.LINE_AA)
    cv2.line(gray, (810, 80), (810, 820), 150, 3, cv2.LINE_AA)
    cv2.rectangle(gray, (360, 170), (1050, 700), 55, 3)
    cv2.line(gray, (400, 430), (1000, 430), 75, 2, cv2.LINE_AA)
    cv2.putText(
        gray,
        "A1 . : ,",
        (450, 360),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        65,
        2,
        cv2.LINE_AA,
    )

    known_tape = np.zeros_like(gray, dtype=bool)
    known_tape[80:821, 707:714] = True
    known_tape[80:821, 807:814] = True
    for y_value in (170, 430, 700):
        known_tape[y_value - 3:y_value + 4] = False
    source = np.clip(gray, 0, 255).astype(np.uint8)
    unconfirmed = prepare_scan_page(source)
    prepared = prepare_scan_page(source, confirmed_noise=known_tape)

    assert np.any(unconfirmed.binary[known_tape] == 0)
    assert np.all(prepared.binary[known_tape] == 255)
    assert np.array_equal(prepared.binary[~known_tape], unconfirmed.binary[~known_tape])
    assert prepared.binary[430, 600] == 0
    assert np.count_nonzero(prepared.binary[320:375, 440:610] == 0) > 20
