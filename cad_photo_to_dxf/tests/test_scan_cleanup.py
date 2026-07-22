from __future__ import annotations

import cv2
import numpy as np

from app.scan_cleanup import prepare_scan_page


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
