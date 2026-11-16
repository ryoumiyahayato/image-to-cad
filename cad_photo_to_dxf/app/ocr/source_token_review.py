"""Conservative source-token/glyph agreement, not spelling or grammar repair.

Only source-separated short tokens within an existing horizontal ASCII line
are eligible. Geometry, ownership, and all source masks stay unchanged.
A token and its differing isolated glyph must agree across source-preserving
views. Insertions/deletions, punctuation changes, single-character tokens,
uncertain segmentation and conflicting readings leave the old candidate intact.
Same-model agreement cannot distinguish common identity-like glyphs such as
letter O versus digit 0: these substitutions are explicitly rejected, not
resolved from language, token syntax, or the model's confidence.
"""
from __future__ import annotations

from dataclasses import replace
import json
from math import ceil, isfinite
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate

TOKEN_SCORE = 0.90
GLYPH_SCORE = 0.90
MAX_LINE_PIXELS = 32768
MAX_TOTAL_PIXELS = 524288
MAX_TOKENS = 256
MAX_CHANGED_TOKENS = 2
# A confidence score is not identity evidence. These are rejection-only
# classes: some valid engineering fonts intentionally render these alike.
# Do not use this table to choose a replacement or to normalize user text.
_IDENTITY_AMBIGUITIES = (frozenset("0Oo"), frozenset("1Il"))


def _ambiguous_substitution(before: str, after: str) -> bool:
    return (
        before != after
        and (before.casefold() == after.casefold()
             or any(before in group and after in group
                    for group in _IDENTITY_AMBIGUITIES))
    )


def _compact(text: str) -> str:
    return "".join(str(text).split())


def _eligible(item: TextCandidate) -> bool:
    return (
        item.approved and not item.reviewed
        and item.source.startswith("rapidocr-")
        and isfinite(float(item.confidence))
        and 0.50 <= float(item.confidence) < 0.995
        and isfinite(float(item.rotation_deg))
        and abs(float(item.rotation_deg)) <= 3.0
        and 6 <= len(_compact(item.text)) <= 120
        and item.text.isascii() and "\n" not in item.text
        and item.kind in {"text_candidate", "dimension_text_candidate"}
    )


def _source_tokens(gray: np.ndarray, bbox: tuple[int, int, int, int]):
    x, y, w, h = map(int, bbox)
    ih, iw = gray.shape
    if (w < 3*h or not 6 <= h <= 96 or w*h > MAX_LINE_PIXELS
            or min(x, y) < 0 or x+w > iw or y+h > ih):
        return []
    line = gray[y:y+h, x:x+w]
    dark = line < 160
    # These observations cannot certify a character clipped by the line box.
    if (not np.any(dark) or np.any(dark[0]) or np.any(dark[-1])
            or np.any(dark[:, 0]) or np.any(dark[:, -1])):
        return []
    columns = np.flatnonzero(np.any(dark, axis=0))
    gap = max(3, int(round(h*0.28)))
    groups = []
    start = previous = int(columns[0])
    for value in columns[1:]:
        value = int(value)
        if value - previous - 1 >= gap:
            groups.append((start, previous+1))
            start = value
        previous = value
    groups.append((start, previous+1))
    if not 2 <= len(groups) <= 12:
        return []
    result = []
    for left, right in groups:
        rows = np.flatnonzero(np.any(dark[:, left:right], axis=1))
        a, b = max(0, left-1), min(w, right+1)
        c, d = max(0, int(rows[0])-1), min(h, int(rows[-1])+2)
        if min(b-a, d-c) < 3:
            return []
        result.append(((x+a, y+c, b-a, d-c), line[c:d, a:b].copy()))
    return result


def _white_views(gray: np.ndarray):
    result = []
    for fraction in (.15, .30):
        pad = max(2, ceil(gray.shape[0]*fraction))
        padded = np.pad(gray, pad, constant_values=255)
        result.append(cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR))
    return result


def _read_pairs(recognize: Callable, images: Sequence[np.ndarray]):
    """Batch inference; exceptions and malformed results provide no authority."""
    rows = []
    for start in range(0, len(images), 24):
        chunk = images[start:start+24]
        try:
            result = recognize(list(chunk))
            texts, scores = result.txts, result.scores
            if texts is None or scores is None or len(texts) != len(chunk) or len(scores) != len(chunk):
                return None
            for text, score in zip(texts, scores, strict=True):
                score = float(score)
                if not isfinite(score) or not 0 <= score <= 1:
                    return None
                rows.append((str(text).strip(), score))
        except (AttributeError, RuntimeError, TypeError, ValueError, ImportError, cv2.error):
            return None
    return rows


def _agreed(pair, minimum: float):
    if len(pair) != 2:
        return None
    (first, a), (second, b) = pair
    value = _compact(first)
    if (not value or not value.isascii() or value != _compact(second)
            or min(a, b) < minimum):
        return None
    return value


def _single_glyph(gray: np.ndarray, bbox, token: str, index: int):
    x, y, w, h = map(int, bbox)
    crop = gray[y:y+h, x:x+w]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(crop < 160), connectivity=8)
    components = list(range(1, count))
    # No dust removal, joining, gap-filling or discarding punctuation here.
    if len(components) != len(token):
        return None
    components.sort(key=lambda k: (stats[k, 0]+stats[k, 2]/2, stats[k, 1]))
    # Two parts occupying the same horizontal reading position are not a
    # demonstrated sequence of separate characters.
    centers = [stats[k, 0]+stats[k, 2]/2 for k in components]
    if any(b-a < 1 for a, b in zip(centers, centers[1:])):
        return None
    k = components[index]
    a, b, cw, ch, pixels = map(int, stats[k])
    if pixels < 2 or ch < 4 or min(a, b) <= 0 or a+cw >= w or b+ch >= h:
        return None
    left, top = max(0, a-1), max(0, b-1)
    right, bottom = min(w, a+cw+1), min(h, b+ch+1)
    # Preserve the original grayscale edges; binarization is geometry-only.
    # Do not read a neighboring dark component as part of this glyph.
    others = set(map(int, np.unique(labels[top:bottom, left:right]))) - {0, k}
    if others:
        return None
    return crop[top:bottom, left:right].copy(), (x+left, y+top, right-left, bottom-top)


def review_source_tokens(
    gray: np.ndarray,
    candidates: Sequence[TextCandidate],
    *,
    recognize: Callable | None = None,
    checkpoint: Callable[[], None] | None = None,
):
    """Return candidates and evidence; never mutate image or source ownership."""
    original = list(candidates)
    if gray is None or gray.ndim != 2 or gray.dtype != np.uint8:
        return original, []
    jobs, images = [], []
    used_pixels = used_tokens = 0
    for index, item in enumerate(candidates):
        if checkpoint is not None:
            checkpoint()
        if not _eligible(item):
            continue
        tokens = _source_tokens(gray, item.bbox)
        pixels = sum(im.size for _, im in tokens)
        if (not tokens or used_tokens+len(tokens) > MAX_TOKENS
                or used_pixels+pixels > MAX_TOTAL_PIXELS):
            continue
        used_pixels += pixels
        used_tokens += len(tokens)
        offset = len(images)
        for _, image in tokens:
            pad = max(2, ceil(image.shape[0]*0.15))
            images.append(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
            images.append(cv2.cvtColor(np.pad(image, pad, constant_values=255), cv2.COLOR_GRAY2BGR))
        jobs.append((index, tokens, offset))
    if not jobs:
        return original, []
    if recognize is None:
        try:
            from app.ocr.ocr_recognition import _get_rapidocr_engine
            recognize = _get_rapidocr_engine().recognize_txt
        except (AttributeError, RuntimeError, ImportError, ValueError):
            return original, []
    readings = _read_pairs(recognize, images)
    if readings is None:
        return original, []
    records = []
    for index, tokens, offset in jobs:
        if checkpoint is not None:
            checkpoint()
        item = candidates[index]
        local_pairs = [readings[offset+2*i:offset+2*i+2] for i in range(len(tokens))]
        words = [_agreed(pair, TOKEN_SCORE) for pair in local_pairs]
        if any(word is None for word in words):
            continue
        before = _compact(item.text)
        after = "".join(words)
        if len(after) != len(before) or after == before:
            continue
        changes = [(i, a, b) for i, (a, b) in enumerate(zip(before, after)) if a != b]
        if not 1 <= len(changes) <= MAX_CHANGED_TOKENS:
            continue
        if any(not a.isalnum() or not b.isalnum()
               or _ambiguous_substitution(a, b) for _, a, b in changes):
            continue
        checks, start = [], 0
        complete = True
        for i, (word, (box, _)) in enumerate(zip(words, tokens, strict=True)):
            old = before[start:start+len(word)]
            different = [j for j, (a, b) in enumerate(zip(old, word, strict=True)) if a != b]
            if different:
                if len(different) != 1 or not 2 <= len(word) <= 12:
                    complete = False
                    break
                position = different[0]
                measured = _single_glyph(gray, box, word, position)
                if measured is None:
                    complete = False
                    break
                image, glyph_box = measured
                pair = _read_pairs(recognize, _white_views(image))
                if pair is None or _agreed(pair, GLYPH_SCORE) != word[position]:
                    complete = False
                    break
                checks.append({
                    "token_before": old, "token_after": word, "token_bbox": list(box),
                    "token_readings": local_pairs[i], "glyph_bbox": list(glyph_box),
                    "glyph_readings": pair,
                })
            start += len(word)
        if not complete or not checks:
            continue
        # Preserve the original spacing and all geometry fields, changing only
        # the certified character positions in the existing native text line.
        positions = [i for i, ch in enumerate(item.text) if not ch.isspace()]
        content = list(item.text)
        for compact_index, _, new in changes:
            content[positions[compact_index]] = new
        content = "".join(content)
        confidence = min(
            [float(item.confidence)]
            + [float(s) for check in checks
               for _, s in check["token_readings"]+check["glyph_readings"]]
        )
        evidence = {
            "stage": "source-token-glyph-review-v1", "candidate_index": index,
            "status": "CORRECTED", "before": item.text, "after": content,
            "bbox": list(item.bbox), "checks": checks,
            "source_masks_modified": False, "independent_ground_truth": False,
        }
        note = json.dumps(evidence, ensure_ascii=True, separators=(",", ":"))
        from app.ocr.ocr_recognition import _candidate_kind
        original[index] = replace(
            item, text=content, confidence=confidence, kind=_candidate_kind(content),
            source=item.source+":source-token-glyph-review",
            review_note=(item.review_note+"\n"+note).strip(),
        )
        records.append(evidence)
    return original, records
