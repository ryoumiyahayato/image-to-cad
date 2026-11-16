"""Review horizontal outline labels tied to an observed PDF leader."""

import ctypes as ct
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil

import cv2
import numpy as np
import pypdfium2 as pdf

from app.geometry.native_pdf_paths import (
    OCCLUSION_GRAY_ALLOWANCE,
    _local_render,
    _segments,
    render_without_active_objects,
)
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_recognition import _get_rapidocr_engine
from app.ocr.pdf_path_digits import _stroke_boxes
from app.ocr.text_output_contract import accepted_ocr_texts


_NUMERIC_BODY = r"[0-9]+(?:[.,][0-9]+)?(?:[@×x/-][0-9]+)?"
# A recognized suffix may anchor a retry. Only the isolated leader and
# complete glyph paint in _review can authorize adding a missing prefix.
_OCR_LABEL = re.compile(r"(?:[^\w\s]|[Φφ])?" + _NUMERIC_BODY + r"|@[0-9]+")


@dataclass(frozen=True)
class CalloutSource:
    bounds: tuple[int, int, int, int]
    mask: np.ndarray
    glyphs: np.ndarray
    original: TextCandidate
    candidate: TextCandidate | None
    leader_objects: tuple[int, ...]
    text_objects: tuple[int, ...]


def _vertices(page, obj, size):
    try:
        segments = _segments(obj)
    except ValueError:
        return ()
    if not segments or segments[0][0] != 2 or any(s[0] != 0 for s in segments[1:]):
        return ()
    matrix = obj.get_matrix()
    x, y = ct.c_int(), ct.c_int()
    points = []
    for _, point, _ in segments:
        if not pdf.raw.FPDF_PageToDevice(page, 0, 0, *size, 0,
                                        *matrix.on_point(*point), ct.byref(x), ct.byref(y)):
            return ()
        points.append((x.value, y.value))
    return tuple(points)


def _intersects(a, b, pad=0):
    return (a[0] - pad < b[2] and b[0] < a[2] + pad
            and a[1] - pad < b[3] and b[1] < a[3] + pad)


def _leader(strokes, vertices, box):
    x, y, w, h = box
    nearby = [i for i, _, b in strokes
              if _intersects(b, (x-h, y-h, x+w+h, y+h+4))]
    short_paths = {i: p for i in nearby if 2 <= len(p := vertices(i)) <= 3}
    diagonals = [(i, a, b) for i, p in short_paths.items()
                 for a, b in zip(p, p[1:]) if abs(a[0]-b[0]) >= .2*h]
    leaders = set()
    for i, points in short_paths.items():
        for start, end in zip(points, points[1:]):
            left, right = sorted((start, end))
            if (left[1] != right[1] or abs(y+h-left[1]) > max(4, .18*h)
                    or min(right[0], x+w)-max(left[0], x) < .7*w):
                continue
            for j, a, b in diagonals:
                if len(points) == 3 and j != i:
                    continue
                if len(short_paths[j]) != 2 and j != i:
                    continue
                for join, tip in ((a, b), (b, a)):
                    if (abs(tip[1]-left[1]) >= .45*h
                            and not left[0] <= tip[0] <= right[0]
                            and any(max(abs(c-d) for c, d in zip(join, e)) <= 1
                                    for e in (left, right))):
                        leaders.add((left[1], tuple(sorted({i, j}))))
    return next(iter(leaders)) if len(leaders) == 1 else None


def _diameter_prefix(glyphs, vertices):
    """A closed oval with two tall central strokes and a connected short foot."""
    left_edge = min(b[0] for _, _, b in glyphs)
    matches = []
    for i, _, box in glyphs:
        if box[0] > left_edge + 2:
            continue
        points = vertices(i)
        if not 9 <= len(points) <= 40 or points[0] != points[-1]:
            continue
        p = np.asarray(points)
        lo, hi = p.min(axis=0), p.max(axis=0)
        width, height = hi - lo
        if height < 6 or not .45*height <= width <= 1.25*height:
            continue
        radius = np.linalg.norm((2*p - lo - hi)/(hi - lo), axis=1)
        if np.max(np.abs(radius-1)) > .33 or cv2.contourArea(p.astype(np.float32)) < .6*width*height:
            continue
        stems = []
        for j, _, _ in glyphs:
            stem = vertices(j)
            if not 2 <= len(stem) <= 3:
                continue
            for a, b in zip(stem, stem[1:]):
                top, bottom = sorted((a, b), key=lambda q: q[1])
                if (top[0] == bottom[0] and lo[0]+.15*width < top[0] < hi[0]-.15*width
                        and top[1] < lo[1] and bottom[1] > hi[1]
                        and bottom[1]-hi[1] <= .45*height):
                    stems.append((j, top, bottom))
        if len(stems) != 2:
            continue
        (a, a_top, a_bottom), (b, b_top, b_bottom) = stems
        if (a == b or abs(a_top[1]-b_top[1]) > 1 or abs(a_bottom[1]-b_bottom[1]) > 1
                or not 0 < abs(a_top[0]-b_top[0]) <= .5*width):
            continue
        feet = []
        for j, _, _ in glyphs:
            foot = vertices(j)
            if (j not in (a, b) and len(foot) == 2
                    and foot[0][1] == foot[1][1]
                    and any(p in (a_bottom, b_bottom) for p in foot)
                    and 0 < abs(foot[0][0]-foot[1][0]) <= width):
                feet.append(j)
        if len(feet) == 1:
            matches.append({i, a, b, feet[0]})
    return matches[0] if len(matches) == 1 else set()


def _recognize(gray):
    points = cv2.findNonZero(np.uint8(gray < 128))
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    crop = cv2.copyMakeBorder(gray[y:y+h, x:x+w], 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=255)
    padded = cv2.copyMakeBorder(crop, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    try:
        result = _get_rapidocr_engine().recognize_txt(
            [cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR) for patch in (crop, padded)]
        )
        a, b = ("".join(text.split()) for text in result.txts)
        if a == b and len(result.scores) == 2 and all(.90 <= score <= 1 for score in result.scores):
            return a
    except Exception:
        # The optional retry has no authority if local OCR is unavailable.
        pass
    return None


def _clear_quad(glyphs, foreign, left, top):
    """Use the complete glyph bounds or abstain when adjacent paint conflicts."""
    points = cv2.findNonZero(np.uint8(glyphs < 128))
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    occupied = (foreign[:, max(x-1, 0):x+w+1] < 255).any(axis=1)
    occupied = cv2.dilate(np.uint8(occupied[:, None]), np.ones((3, 1), np.uint8))[:, 0]
    if np.any(occupied[y:y+h]):
        return None
    left_coord, r = left+x, left+x+w
    t, b = top+y, top+y+h
    return ((left_coord, t), (r, t), (r, b), (left_coord, b))


def _review(page, gray, strokes, vertices, text):
    x, y, w, h = text.bbox
    match = _leader(strokes, vertices, text.bbox)
    if match is None:
        return None
    baseline, leader_ids = match
    size = gray.shape[::-1]
    leaders = [b for i, _, b in strokes if i in leader_ids]
    bounds = (max(0, min(x-3, *(b[0]-3 for b in leaders))),
              max(0, min(y-3, *(b[1]-3 for b in leaders))),
              min(size[0], max(x+w+3, *(b[2]+3 for b in leaders))),
              min(size[1], max(y+h+3, *(b[3]+3 for b in leaders))))
    left, top, right, bottom = bounds
    if right-left > 4*w or bottom-top > 4*h:
        return None
    local = [(i, o, b) for i, o, b in strokes if _intersects(b, bounds, pad=2)]
    if len(local) > 128:
        return None
    source = gray[top:bottom, left:right]
    rendered = _local_render(page, bounds, size)
    source_values = source.astype(np.int16)
    if (not np.array_equal(rendered < 128, source < 128)
            or np.max(np.abs(rendered-source_values)) > OCCLUSION_GRAY_ALLOWANCE):
        return None
    background = render_without_active_objects(page, bounds, size, (o for _, o, _ in local))
    leader = render_without_active_objects(page, bounds, size, (o for i, o, _ in local if i not in leader_ids))
    without_leader = render_without_active_objects(page, bounds, size, (o for i, o, _ in local if i in leader_ids))
    leader_ink = (background == 255) & (leader < 255) & (source < 255)
    if (np.any(leader_ink & (source_values-leader > OCCLUSION_GRAY_ALLOWANCE))
            or not np.any(leader_ink & (leader < 128) & (without_leader >= 128))):
        return None
    glyphs = [(i, o, b) for i, o, b in local if i not in leader_ids
              and x-2 <= b[0] <= b[2] <= x+w+2 and y-2 <= b[1] <= b[3] <= baseline+1
              and b[2]-b[0] <= .85*h]
    candidate = None
    exclusive = np.zeros_like(source)
    glyph_ids = {i for i, _, _ in glyphs}
    if glyph_ids:
        ink = render_without_active_objects(page, bounds, size, (o for i, o, _ in local if i not in glyph_ids))
        foreign = render_without_active_objects(page, bounds, size, (o for i, o, _ in local if i in glyph_ids))
        ink = np.where(background == 255, ink, 255).astype(np.uint8)
        quad = _clear_quad(ink, foreign, left, top)
        if quad is not None and not np.any((ink < 255) & (source_values-ink > OCCLUSION_GRAY_ALLOWANCE)):
            prefix = _diameter_prefix(glyphs, vertices)
            body = (render_without_active_objects(page, bounds, size,
                                   (o for i, o, _ in local if i not in glyph_ids-prefix))
                    if prefix else ink)
            reading = _recognize(np.where(background == 255, body, 255).astype(np.uint8))
            old = "".join(text.text.split())
            old_body = old
            if old[0] in "Φφ" or (not old[0].isalnum() and old[0] != "@"):
                old_body = old[1:]
            if (prefix and reading and re.fullmatch(_NUMERIC_BODY, reading)
                    and old_body and reading.endswith(old_body) and len(reading)-len(old_body) <= 1):
                reading = "Φ" + reading
            elif reading != old:
                reading = None
            if reading and all(len(vertices(i)) > 3 for i in glyph_ids-prefix):
                candidate = replace(text, text=reading, display_quad=quad)
                agrees = (ink < 255) & (source < 255) & (np.abs(source_values-ink) <= OCCLUSION_GRAY_ALLOWANCE)
                exclusive = np.uint8(agrees & (foreign == 255)) * 255
    return CalloutSource(bounds, np.uint8(leader_ink)*255, exclusive, text, candidate,
                         leader_ids, tuple(sorted(glyph_ids)))


def review_pdf_path_callouts(gray, texts, binding, *, content_changes_only=False):
    """Return source-bound callout proofs, optionally only for changed readings."""
    candidates = [t for t in accepted_ocr_texts(texts) if not t.reviewed
                  and t.source.startswith("rapidocr-") and t.display_quad is None
                  and _OCR_LABEL.fullmatch("".join(t.text.split()))
                  and abs(t.rotation_deg) <= 5 and 20 <= t.bbox[2] <= 256 and 12 <= t.bbox[3] <= 64]
    if not candidates or len(candidates) > 256:
        return ()
    size = gray.shape[::-1]
    try:
        with pdf.PdfDocument(binding["document"]) as doc:
            page = doc[int(binding["page_number"])-1]
            scale = float(binding["requested_dpi"])/72
            if (tuple(ceil(d*scale) for d in page.get_size()) != size
                    or pdf.raw.FPDFPage_CountObjects(page) > 8192):
                return ()
            strokes = list(_stroke_boxes(page, pdf.raw, size))
            objects = {i: obj for i, obj, _ in strokes}

            @lru_cache(maxsize=2048)
            def vertices(i):
                return _vertices(page, objects[i], size)

            proofs = []
            for text in candidates:
                proof = _review(page, gray, strokes, vertices, text)
                if proof is None or (content_changes_only and
                                     (proof.candidate is None or proof.candidate.text == text.text)):
                    continue
                proofs.append(proof)
                if len(proofs) == 8:
                    break
            return tuple(proofs)
    except (IndexError, KeyError, OSError, ValueError, pdf.PdfiumError):
        return ()


def apply_callout_texts(texts, proofs, retired, contour_binary, protected_masks, line_ink):
    """Fit editable TEXT in the clear source band and back up only exclusive ink."""
    by_observation = {(p.original.bbox, p.original.text, p.original.source): p
                      for p in proofs if p.candidate is not None}
    accepted = {id(text) for text in accepted_ocr_texts(texts)}
    updated = list(texts)
    changes = {}
    for index, text in enumerate(texts):
        proof = by_observation.get((text.bbox, text.text, text.source))
        if proof is None or id(text) not in accepted or text.display_quad is not None:
            continue
        candidate = proof.candidate
        (x, y), (right, _), (_, bottom), _ = candidate.display_quad
        if np.any(line_ink[y:bottom, x:right]):
            continue
        updated[index] = replace(
            text, text=candidate.text, display_quad=candidate.display_quad,
            character_boxes=() if candidate.text != text.text else text.character_boxes,
        )
        changes[index] = proof
    if not changes:
        return texts, []
    final_accepted = {id(t) for t in accepted_ocr_texts(updated)}
    if final_accepted != {id(updated[i]) for i, t in enumerate(texts) if id(t) in accepted}:
        return texts, []

    records = []
    for index, proof in changes.items():
        text = texts[index]
        left_coord, t, r, b = proof.bounds
        window = np.s_[t:b, left_coord:r]
        owned = (proof.glyphs > 0) & (contour_binary[window] < 128)
        for mask in protected_masks:
            owned &= mask[window] == 0
        retired[window][owned] = 255
        records.append({
            "before": text.text, "text": updated[index].text, "bbox": list(text.bbox),
            "leader_objects": list(proof.leader_objects), "text_objects": list(proof.text_objects),
            "retired_pixels": int(np.count_nonzero(owned)),
        })
    return tuple(updated), records
