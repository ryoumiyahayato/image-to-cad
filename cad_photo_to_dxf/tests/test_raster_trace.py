from __future__ import annotations

import cv2
import numpy as np

from app.raster_trace import make_black_white, trace_binary, trace_image
from app.trace_verification import verify_trace_paths


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

    assert set(result.stages) == {"灰度原图", "CAD 轮廓来源"}
    assert result.foreground_pixels > 0
    assert result.paths
    assert result.vertex_count >= sum(3 for _path in result.paths)
    assert result.binary[20, 100] == 0
    assert result.binary[211, 321] == 0
    assert verify_trace_paths(result.binary, result.paths).exact


def test_trace_binary_does_not_drop_nested_holes() -> None:
    binary = np.full((120, 120), 255, dtype=np.uint8)
    cv2.rectangle(binary, (15, 15), (105, 105), 0, -1)
    cv2.rectangle(binary, (40, 40), (80, 80), 255, -1)

    paths = trace_binary(binary)

    assert len(paths) >= 2
    assert any(path.depth == 0 for path in paths)
    assert any(path.depth == 1 for path in paths)
    assert any(path.parent is not None for path in paths)
    assert verify_trace_paths(binary, paths).exact


def test_collinear_compression_reduces_vertices_without_pixel_difference() -> None:
    binary = np.full((220, 420), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 10), (410, 210), 0, 3)
    cv2.line(binary, (20, 60), (400, 60), 0, 5)
    cv2.putText(
        binary,
        "A11 9000",
        (50, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        2,
        cv2.LINE_8,
    )

    foreground = np.where(binary < 128, 255, 0).astype(np.uint8)
    padded = cv2.copyMakeBorder(
        foreground,
        1,
        1,
        1,
        1,
        cv2.BORDER_CONSTANT,
        value=0,
    )
    none_contours, _ = cv2.findContours(
        padded,
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_NONE,
    )
    paths = trace_binary(binary)

    assert sum(len(path.points) for path in paths) < sum(
        len(contour) for contour in none_contours
    )
    assert verify_trace_paths(binary, paths).exact


def test_foreground_conversion_has_no_morphological_detail_loss() -> None:
    gray = np.full((40, 80), 255, dtype=np.uint8)
    gray[10, 10:70] = 190
    gray[20:22, 20:22] = 50

    binary, threshold, stages = make_black_white(gray)

    assert 1 <= threshold <= 254
    assert binary[10, 30] == 0
    assert binary[20, 20] == 0
    assert np.array_equal(stages["CAD 轮廓来源"], binary)
