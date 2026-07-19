from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.raster_trace import trace_image
from app.trace_storage import load_trace_cache, save_trace_cache


def test_trace_cache_roundtrip_preserves_binary_hierarchy_and_vertices(
    tmp_path: Path,
) -> None:
    image = np.full((160, 220, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (15, 15), (205, 145), (0, 0, 0), -1)
    cv2.rectangle(image, (50, 45), (170, 115), (255, 255, 255), -1)
    cv2.putText(
        image,
        "A1",
        (75, 95),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 0, 0),
        2,
        cv2.LINE_8,
    )
    result = trace_image(image)

    path = save_trace_cache(tmp_path / "page.npz", result)
    stored = load_trace_cache(path)

    assert np.array_equal(stored.binary, result.binary)
    assert stored.threshold == result.threshold
    assert stored.foreground_pixels == result.foreground_pixels
    assert stored.vertex_count == result.vertex_count
    assert stored.warnings == result.warnings
    assert len(stored.paths) == len(result.paths)
    for expected, actual in zip(result.paths, stored.paths):
        assert actual.parent == expected.parent
        assert actual.depth == expected.depth
        assert actual.root == expected.root
        assert actual.points == expected.points
