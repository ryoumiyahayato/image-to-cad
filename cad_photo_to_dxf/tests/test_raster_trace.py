from __future__ import annotations

import cv2
import numpy as np

from app.raster_trace import make_black_white, trace_binary, trace_image


def test_trace_preserves_text_curves_and_small_marks_as_boundaries() -> None:
    image = np.full((240, 360, 3), 255, dtype=np.uint8)
    cv2.line(image, (10, 20), (350, 20), (0, 0, 0), 2)
    cv2.circle(image, (70, 100), 23, (0, 0, 0), 2)
    cv2.putText(
        image,
        "A11",
        (120, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    cv2.rectangle(image, (320, 210), (323, 213), (80, 80, 80), -1)

    result = trace_image(image)

    assert set(result.stages) == {"灰度原样", "黑白拓印图"}
    assert result.foreground_pixels > 0
    assert result.paths
    assert result.vertex_count >= sum(3 for _path in result.paths)
    assert result.binary[20, 100] == 0
    assert result.binary[211, 321] == 0


def test_trace_binary_does_not_drop_nested_holes() -> None:
    binary = np.full((120, 120), 255, dtype=np.uint8)
    cv2.rectangle(binary, (15, 15), (105, 105), 0, -1)
    cv2.rectangle(binary, (40, 40), (80, 80), 255, -1)

    paths = trace_binary(binary)

    assert len(paths) >= 2
    assert any(path.depth == 0 for path in paths)
    assert any(path.depth == 1 for path in paths)
    assert any(path.parent is not None for path in paths)


def test_black_white_conversion_has_no_morphological_detail_loss() -> None:
    gray = np.full((40, 80), 255, dtype=np.uint8)
    gray[10, 10:70] = 190
    gray[20:22, 20:22] = 50

    binary, threshold, stages = make_black_white(gray)

    assert 1 <= threshold <= 254
    assert binary[10, 30] == 0
    assert binary[20, 20] == 0
    assert np.array_equal(stages["黑白拓印图"], binary)
