"""Review uncertain short printed labels against aligned original-scan glyphs."""

from dataclasses import replace
from math import ceil

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextObservation
from app.ocr.ocr_recognition import _candidate_kind, _get_rapidocr_engine


def _eligible(item):
    text = item.text
    return (
        item.kind == "text_candidate" and item.approved and not item.reviewed
        and 2 <= len(text) <= 4 and text.isascii() and text.isalnum()
        and 0 <= item.confidence < .85 and abs(item.rotation_deg) <= 5
        and len(item.character_boxes) == len(text)
    )


def _observed_glyphs(item, scan, crop_origin, input_shape):
    ratio = scan.ratio
    dx, dy = crop_origin
    height, width = input_shape
    x, y, w, h = item.bbox
    left, top = max(0, x - 1), max(0, y - 1)
    right, bottom = min(width, x + w + 1), min(height, y + h + 1)
    nx, ny = (dx + left) * ratio, (dy + top) * ratio
    native = scan.pixels[ny:(dy + bottom) * ratio, nx:(dx + right) * ratio]
    if native.shape != ((bottom - top) * ratio, (right - left) * ratio) or not native.size:
        return None
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.uint8(native < 128), connectivity=8,
    )
    # Components touching the window may be fragments of table rules or
    # neighboring text. They cannot provide a glyph, even when OCR reads them.
    ids = []
    for i, (gx, gy, gw, gh, count) in enumerate(stats[1:], 1):
        if count < max(3, ratio * ratio):
            continue
        if gx > 0 and gy > 0 and gx + gw < native.shape[1] and gy + gh < native.shape[0]:
            ids.append(i)
    ids.sort(key=lambda i: stats[i, cv2.CC_STAT_LEFT])
    if len(ids) != len(item.text):
        return None
    boxes, glyphs = [], []
    previous_right = 0
    for i, (cx, cy, cw, ch) in zip(ids, item.character_boxes, strict=True):
        gx, gy, gw, gh, count = map(int, stats[i])
        if gx < previous_right or gw < ratio or gh < 3 * ratio:
            return None
        x0, y0 = (cx - left) * ratio, (cy - top) * ratio
        x1, y1 = x0 + cw * ratio, y0 + ch * ratio
        if not (0 <= x0 < x1 <= native.shape[1] and 0 <= y0 < y1 <= native.shape[0]):
            return None
        hint = labels[y0:y1, x0:x1]
        if np.count_nonzero(hint == i) < .65 * count:
            return None
        # Reject a clipped component in the very area used to assign the glyph.
        for other in np.unique(hint):
            if other and other not in ids and stats[other, cv2.CC_STAT_AREA] >= max(3, ratio * ratio):
                return None
        glyphs.append(np.where(labels[gy:gy+gh, gx:gx+gw] == i, 0, 255).astype(np.uint8))
        boxes.append((nx + gx, ny + gy, nx + gx + gw, ny + gy + gh))
        previous_right = gx + gw
    x0, x1 = boxes[0][0] - nx, boxes[-1][2] - nx
    y0, y1 = min(b[1] for b in boxes) - ny, max(b[3] for b in boxes) - ny
    word = np.where(np.isin(labels[y0:y1, x0:x1], ids), 0, 255).astype(np.uint8)
    return word, glyphs, boxes


def _read_views(word, glyphs):
    inputs = []
    for image in (word, *glyphs):
        for fraction in (.15, .30):
            pad = ceil(fraction * image.shape[0])
            padded = np.pad(image, pad, constant_values=255)
            inputs.append(cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR))
    try:
        result = _get_rapidocr_engine().recognize_txt(inputs)
        return [(str(text).strip(), float(score)) for text, score
                in zip(result.txts, result.scores, strict=True)]
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError, cv2.error):
        return []


def _agreed_reading(readings, length):
    if len(readings) != 2 * (length + 1):
        return None
    for (a, sa), (b, sb) in zip(readings[::2], readings[1::2], strict=True):
        if a != b or not a.isascii() or not a.isalnum() or not (.90 <= sa <= 1 and .90 <= sb <= 1):
            return None
    chars = [text for text, _ in readings[2::2]]
    word = readings[0][0]
    if not all(len(char) == 1 for char in chars) or "".join(chars) != word:
        return None
    return word, min(score for _, score in readings)


def review_scanned_glyphs(texts, scan, *, source_crop, input_shape):
    """Correct a single disagreement only if isolated glyphs and token agree."""
    origin = source_crop[:2] if source_crop is not None else (0, 0)
    output, records = [], []
    for index, item in enumerate(texts):
        if not _eligible(item):
            output.append(item)
            continue
        record = dict(input_bbox=item.bbox, raw_text=item.text, raw_confidence=item.confidence)
        measured = _observed_glyphs(item, scan, origin, input_shape) if scan is not None else None
        agreed = None
        reason = "original_grid_unverified" if scan is None else "glyphs_not_isolated"
        if measured is not None:
            word, glyphs, boxes = measured
            readings = _read_views(word, glyphs)
            agreed = _agreed_reading(readings, len(item.text))
            record.update(original_dpi=scan.dpi, original_glyph_boxes_xyxy=boxes,
                          token_readings=readings[:2], glyph_readings=[
                              readings[i:i+2] for i in range(2, len(readings), 2)
                          ])
            reason = "original_readings_disagree"
        if agreed is not None and agreed[0] == item.text:
            records.append(dict(record, status="CONFIRMED", result=item.text))
            output.append(item)
            continue
        observation = item.pre_cell_observation or TextObservation.capture(item, index)
        if agreed is not None and sum(a != b for a, b in zip(item.text, agreed[0], strict=True)) == 1:
            content, confidence = agreed
            item = replace(item, text=content, confidence=confidence, kind=_candidate_kind(content),
                           source=f"{item.source}:original-glyph-review",
                           replacement_safe=False, pre_cell_observation=observation)
            records.append(dict(record, status="CORRECTED", result=content, confidence=confidence))
        else:
            item = replace(item, approved=False, replacement_safe=False,
                           pre_cell_observation=observation,
                           review_note=f"{item.review_note}；原扫字形复核未决".lstrip("；"))
            records.append(dict(record, status="UNRESOLVED",
                                reason="multiple_character_changes" if agreed is not None else reason))
        output.append(item)
    return tuple(output), tuple(records)
