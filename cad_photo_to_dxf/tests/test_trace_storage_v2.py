from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.raster_trace import trace_image
from app.trace_storage import load_trace_cache, save_trace_cache


def test_packed_cache_preserves_character_layout_and_signature_safety(tmp_path: Path) -> None:
    image = np.full((120, 180), 255, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (170, 110), 0, 2)
    result = trace_image(image)
    candidate = TextCandidate(
        text="签名",
        bbox=(40, 40, 80, 30),
        confidence=0.97,
        kind="text_candidate",
        source="rapidocr-tile",
        character_boxes=((42, 42, 30, 26), (78, 42, 34, 26)),
        replacement_safe=False,
        review_note="疑似签名，保留原图形等待确认",
    )
    result = replace(result, texts=(candidate,))

    path = save_trace_cache(tmp_path / "packed.npz", result)
    with np.load(path, allow_pickle=False) as archive:
        assert "binary_packed" in archive.files
        assert "binary" not in archive.files

    stored = load_trace_cache(path)

    assert np.array_equal(stored.binary, result.binary)
    assert stored.texts == (candidate,)
    assert not stored.texts[0].replacement_safe
    assert stored.texts[0].character_boxes == candidate.character_boxes
