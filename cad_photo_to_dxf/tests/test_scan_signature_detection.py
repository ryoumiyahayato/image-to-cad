"""General handwriting controls retained from the former signature suite."""
import cv2
import numpy as np

from app.ocr.signature_overlay import detect_signature_regions


def test_signatures_crossing_table_rules_remain_protected():
    binary = np.full((300, 400), 255, np.uint8)
    for x in (200, 260, 320, 380):
        cv2.line(binary, (x, 20), (x, 280), 0, 2)
    for y in (20, 60, 100, 140, 180, 220, 260, 280):
        cv2.line(binary, (200, y), (380, y), 0, 2)
    for y in (78, 118, 158):
        points = np.array([(245, y+4), (275, y-8), (300, y+6), (335, y-5)])
        cv2.polylines(binary, [points], False, 0, 3)
    regions = detect_signature_regions(binary)
    assert len(regions) >= 3
    assert regions[0].bbox[0] < 260
    assert regions[0].bbox[0] + regions[0].bbox[2] > 320


def test_freeform_signature_beside_printed_label_is_preserved():
    binary = np.full((260, 520), 255, np.uint8)
    cv2.putText(binary, "SIGNATURE:", (80, 150), cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 2)
    points = np.array([(270, 155), (305, 125), (330, 165), (365, 120), (430, 150)])
    cv2.polylines(binary, [points], False, 0, 7)
    regions = detect_signature_regions(binary)
    assert len(regions) == 1
    assert 260 < regions[0].bbox[0] < 285
    assert regions[0].bbox[0] + regions[0].bbox[2] > 420
    assert cv2.countNonZero(regions[0].mask) > 300


def test_single_direction_engineering_stroke_is_not_a_signature():
    binary = np.full((180, 420), 255, np.uint8)
    points = np.array([(35, 125), (125, 110), (220, 95), (330, 75)])
    cv2.polylines(binary, [points], False, 0, 4)
    assert detect_signature_regions(binary) == ()


def test_circled_engineering_symbol_is_not_a_signature():
    binary = np.full((220, 320), 255, np.uint8)
    cv2.circle(binary, (120, 110), 40, 0, 3)
    cv2.putText(binary, "A", (96, 132), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 3)
    assert detect_signature_regions(binary) == ()
