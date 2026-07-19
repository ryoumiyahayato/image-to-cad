from __future__ import annotations

import cv2
import numpy as np

from app.raster_trace import trace_binary
from app.trace_verification import verify_trace_paths


def test_verification_rasterizes_the_same_geometry_used_for_cad() -> None:
    binary = np.full((180, 280), 255, dtype=np.uint8)
    cv2.line(binary, (10, 20), (260, 20), 0, 3)
    cv2.circle(binary, (70, 90), 30, 0, 4)
    cv2.putText(binary, "A11", (120, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    paths = trace_binary(binary)

    result = verify_trace_paths(binary, paths)

    assert result.exact
    assert result.missing_pixels == 0
    assert result.extra_pixels == 0
    assert result.matched_pixels == int(np.count_nonzero(binary == 0))
    matched_pixels = result.overlay[binary == 0]
    assert np.all(matched_pixels == np.array([255, 0, 0], dtype=np.uint8))
