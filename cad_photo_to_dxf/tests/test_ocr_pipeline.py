from __future__ import annotations

import cv2
import numpy as np

from app.ocr_pipeline import remove_table_rules_for_ocr


def test_table_rules_are_whitened_without_erasing_nearby_text() -> None:
    image = np.full((320, 640), 255, dtype=np.uint8)
    cv2.line(image, (20, 80), (620, 80), 0, 3)
    cv2.line(image, (20, 240), (620, 240), 0, 3)
    cv2.line(image, (120, 20), (120, 300), 0, 3)
    cv2.putText(
        image,
        "A12 TEST",
        (180, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        0,
        3,
        cv2.LINE_AA,
    )

    cleaned = remove_table_rules_for_ocr(image)

    assert int(cleaned[80, 400]) == 255
    assert int(cleaned[240, 400]) == 255
    assert int(cleaned[150:190, 180:420].min()) < 128
