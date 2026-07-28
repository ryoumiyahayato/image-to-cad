from __future__ import annotations

import cv2
import numpy as np

from app.raster_trace import trace_binary
from app.scan_artifact_filter import suppress_scan_artifact_traces


def _synthetic_damaged_scan() -> tuple[np.ndarray, np.ndarray]:
    gray = np.full((600, 900), 220, dtype=np.uint8)
    binary = np.full_like(gray, 255)

    # Real structural rules must remain. Small corner gaps mirror the pipeline
    # state after reconstructed LINE entities have been removed from this mask.
    for start, end in (
        ((200, 130), (740, 130)),
        ((180, 160), (180, 470)),
        ((760, 160), (760, 470)),
        ((200, 500), (740, 500)),
    ):
        cv2.line(gray, start, end, 45, 3)
        cv2.line(binary, start, end, 0, 3)

    # Raised tape in the top-left corner: bright paper with a weak irregular edge.
    tape = np.array(((8, 8), (145, 12), (120, 100), (15, 145)), dtype=np.int32)
    cv2.fillPoly(gray, [tape], 250)
    cv2.polylines(gray, [tape], True, 170, 5)
    cv2.polylines(binary, [tape], True, 0, 5)
    cv2.line(gray, (25, 130), (120, 35), 165, 4)
    cv2.line(binary, (25, 130), (120, 35), 0, 4)

    # A torn bright band with several weak, disconnected dark edges.
    tear = np.array(
        ((430, 310), (450, 315), (444, 440), (420, 430)),
        dtype=np.int32,
    )
    cv2.fillPoly(gray, [tear], 252)
    cv2.polylines(gray, [tear], False, 166, 4)
    cv2.polylines(binary, [tear], False, 0, 4)
    cv2.line(gray, (424, 275), (438, 320), 168, 4)
    cv2.line(binary, (424, 275), (438, 320), 0, 4)
    cv2.line(gray, (442, 440), (460, 470), 172, 4)
    cv2.line(binary, (442, 440), (460, 470), 0, 4)

    # A dark, very sparse diagonal flight across an otherwise empty region.
    flight = np.array(((230, 260), (350, 180), (700, 170)), dtype=np.int32)
    cv2.polylines(gray, [flight], False, 70, 1)
    cv2.polylines(binary, [flight], False, 0, 1)
    return gray, binary


def test_scan_artifact_filter_removes_tape_tear_and_sparse_flight() -> None:
    gray, binary = _synthetic_damaged_scan()
    paths = trace_binary(binary)

    result = suppress_scan_artifact_traces(gray, binary, paths)

    assert result.removed_root_count >= 3
    assert result.binary[45, 110] == 255
    assert result.binary[360, 432] == 255
    assert result.binary[180, 350] == 255


def test_scan_artifact_filter_keeps_dark_structural_frame() -> None:
    gray, binary = _synthetic_damaged_scan()
    paths = trace_binary(binary)

    result = suppress_scan_artifact_traces(gray, binary, paths)

    assert result.binary[130, 500] == 0
    assert result.binary[500, 500] == 0
    assert result.binary[300, 180] == 0
    assert result.binary[300, 760] == 0


def test_scan_artifact_filter_removes_corner_tape_joined_to_page_border() -> None:
    gray = np.full((600, 900), 220, dtype=np.uint8)
    binary = np.full_like(gray, 255)
    cv2.line(gray, (5, 5), (895, 5), 35, 3)
    cv2.line(binary, (5, 5), (895, 5), 0, 3)

    tape = np.array(((18, 6), (150, 8), (130, 105), (25, 145)), dtype=np.int32)
    cv2.fillPoly(gray, [tape], 250)
    cv2.polylines(gray, [tape], True, 165, 5)
    cv2.polylines(binary, [tape], True, 0, 5)
    cv2.line(gray, (30, 135), (125, 28), 160, 5)
    cv2.line(binary, (30, 135), (125, 28), 0, 5)

    paths = trace_binary(binary)
    result = suppress_scan_artifact_traces(gray, binary, paths)

    assert result.removed_root_count >= 1
    assert result.binary[70, 105] == 255
    assert result.binary[135, 30] == 255
    assert result.binary[5, 500] == 255
