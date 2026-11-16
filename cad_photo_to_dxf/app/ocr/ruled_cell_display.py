"""Source-proven bilingual row display, with no source replacement authority."""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

import cv2
import numpy as np
from PySide6.QtGui import QPainterPath

from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import glyph_footprint
from app.ocr.librecad_lff import librecad_font_available
from app.ocr.ocr_layout import _restore_cell_text_rows
from app.ocr.text_output_contract import accepted_ocr_texts


def refine_ruled_cell_row_displays(
    gray, texts, cells, *, protected_source_masks=(), source_proof_sink=None,
):
    """Fit only complete, independently separated source rows in observed cells.

    The existing strict ownership proof is NOT relaxed. Temporary candidates
    only ask it to measure horizontal ink; its source/safety results are never
    returned. Detector skew is disregarded only for a complete CJK row whose
    independent glyph tops and bottoms align to source-pixel precision.
    """
    if not cells or not librecad_font_available():
        return tuple(texts), ()
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Row display requires prepared source gray")
    if any(mask.shape != gray.shape for mask in protected_source_masks):
        raise ValueError("Row display protection must share source coordinates")
    output, records = list(texts), []
    keys = {}
    for index, item in enumerate(texts):
        keys.setdefault((item.text, item.bbox), []).append(index)
    remaining = 262_144
    for cell, members in cells.items():
        if not 2 <= len(members) <= 6 or any(len(keys.get(k, ())) != 1 for k in members):
            continue
        indexes = [keys[k][0] for k in members]
        rows = tuple(texts[i] for i in indexes)
        if any(
            t.reviewed or t.display_quad is not None
            or t.kind != "text_candidate" or not t.source.startswith("rapidocr")
            or not t.text.strip() or not all(c.isalpha() or c.isspace() for c in t.text)
            or not isfinite(t.rotation_deg) or abs(t.rotation_deg) > 3.0
            or (abs(t.rotation_deg) > 0.5 and not _cjk(t.text))
            for t in rows
        ) or len(accepted_ocr_texts(rows)) != len(rows):
            continue
        left, top, right, bottom = cell
        area = (right - left) * (bottom - top)
        if (not 0 <= left < right <= gray.shape[1]
                or not 0 <= top < bottom <= gray.shape[0]
                or area > min(remaining, 65_536)):
            continue
        remaining -= area
        probes = []
        for t in rows:
            x, y, w, h = t.bbox
            # Preserve the ordered horizontal reading basis; never straighten
            # vertical, reversed or genuinely oblique detection quads.
            if t.quad and (len(t.quad) != 4
                    or not all(isfinite(v) for point in t.quad for v in point)
                    or t.quad[1][0] <= t.quad[0][0]
                    or t.quad[2][0] <= t.quad[3][0]
                    or abs(t.quad[1][1] - t.quad[0][1]) > w * 0.06):
                break
            probes.append(replace(t, rotation_deg=0.0,
                quad=((x, y), (x+w, y), (x+w, y+h), (x, y+h))))
        if len(probes) != len(rows):
            continue
        proofs = []
        fitted = _restore_cell_text_rows(gray, tuple(probes), cell, verified_sources=proofs)
        if len(proofs) != 1:
            continue
        proof = proofs[0]
        if any(np.any((proof.mask > 0) & (m[top:bottom, left:right] > 0))
               for m in protected_source_masks):
            continue
        if any(abs(t.rotation_deg) > 0.5 and not _horizontal_cjk(t, mask)
               for t, mask in zip(rows, proof.row_masks, strict=True)):
            continue
        proposals = []
        for original, fit in zip(rows, fitted, strict=True):
            x, y, w, h = original.bbox
            quad = fit.quad
            if not quad or not (x <= quad[0][0] < quad[2][0] <= x+w
                                and y <= quad[0][1] < quad[2][1] <= y+h):
                break
            proposals.append(replace(original, display_quad=quad))
        if len(proposals) != len(rows):
            continue
        if all(p.display_quad == t.quad for p, t in zip(proposals, rows, strict=True)):
            continue
        def transform(x, y):
            return (x, gray.shape[0] - y)
        placements = [native_text_placement(t, transform=transform) for t in proposals]
        if any(p is None or p.metrics.fallback_reason for p in placements):
            continue
        paths = [glyph_footprint(p) for p in placements]
        # Protect source pixels even when the substituted glyph occupies paper
        # between the proved source strokes. Source-core exclusion alone cannot
        # establish that a different font avoids these pixels.
        protected = QPainterPath()
        for y in range(top, bottom):
            occupied = np.zeros(right - left, dtype=bool)
            for mask in protected_source_masks:
                occupied |= mask[y, left:right] > 0
            columns = np.flatnonzero(occupied)
            if not columns.size:
                continue
            breaks = np.flatnonzero(np.diff(columns) > 1) + 1
            for run in np.split(columns, breaks):
                protected.addRect(float(left + run[0]), float(gray.shape[0] - y - 1),
                                  float(run[-1] - run[0] + 1), 1.0)
        if any(path.intersects(protected) for path in paths):
            continue
        if any(a.intersects(b) for i, a in enumerate(paths) for b in paths[i+1:]):
            continue
        # A tightened row must not create a new contact with unchanged TEXT.
        blocked = False
        for i, old in enumerate(texts):
            if i in indexes:
                continue
            x, y, w, h = old.bbox
            if x+w < left or x > right or y+h < top or y > bottom:
                continue
            if not accepted_ocr_texts((old,)):
                continue
            placement = native_text_placement(old, transform=transform)
            if placement is None or placement.metrics.fallback_reason:
                blocked = True
                break
            other = glyph_footprint(placement)
            if any(path.intersects(other) for path in paths):
                blocked = True
                break
        if blocked:
            continue
        if source_proof_sink is not None:
            # Measurement only, not retirement authority. A consumer must prove
            # exact source members and final protected ownership independently.
            source_proof_sink.append((tuple(indexes), proof))
        for index, proposal in zip(indexes, proposals, strict=True):
            output[index] = proposal
            records.append(dict(index=index, cell=cell, display_quad=proposal.display_quad,
                                authority="DISPLAY_ONLY", proof="complete-horizontal-cell-rows"))
    return tuple(output), tuple(records)


def _cjk(text):
    return all("\u4e00" <= c <= "\u9fff" for c in text if not c.isspace())


def _horizontal_cjk(text, mask):
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    glyphs = stats[1:]
    if len(glyphs) != len("".join(text.text.split())) or len(glyphs) < 2:
        return False
    tolerance = max(1, int(round(float(np.median(glyphs[:, 3])) * 0.06)))
    return bool(np.ptp(glyphs[:, 1]) <= tolerance
                and np.ptp(glyphs[:, 1] + glyphs[:, 3]) <= tolerance)


def _source_row_boxes(gray, rows, cell):
    """Measure complete printed components in the interior of a verified cell."""
    left, top, right, bottom = cell
    x = max(left + 3, min(t.bbox[0] for t in rows) - 5)
    y = max(top + 3, min(t.bbox[1] for t in rows) - 7)
    u = min(right - 3, max(t.bbox[0] + t.bbox[2] for t in rows) + 5)
    v = min(bottom - 3, max(t.bbox[1] + t.bbox[3] for t in rows) + 7)
    if not (0 <= x < u <= gray.shape[1] and 0 <= y < v <= gray.shape[0]) or (u-x)*(v-y) > 65_536:
        return ()
    ink = np.uint8(gray[y:v, x:u] < 128)
    if ink[0].any() or ink[-1].any() or ink[:, 0].any() or ink[:, -1].any():
        return ()
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    centers = np.array([t.bbox[1] + t.bbox[3]/2 for t in rows])
    groups = [[] for _ in rows]
    for px, py, w, h, _area in stats[1:]:
        px, py, w, h = int(px)+x, int(py)+y, int(w), int(h)
        distances = np.abs(centers - (py + h/2))
        first, second = np.argsort(distances)[:2]
        bx, by, bw, bh = rows[first].bbox
        if (distances[second]-distances[first] < max(2, bh*.08)
                or not (bx-2 <= px < px+w <= bx+bw+2 and by-2 <= py < py+h <= by+bh+2)
                or any(py <= center <= py+h for i, center in enumerate(centers) if i != first)):
            return ()
        groups[first].append((px, py, px+w, py+h))
    boxes = []
    for row, group in zip(rows, groups, strict=True):
        if len(group) < 2:
            return ()
        left_coord, t = np.min(group, axis=0)[:2]
        r, b = np.max(group, axis=0)[2:]
        if r-left_coord < row.bbox[2]*.60 or b-t < row.bbox[3]*.42:
            return ()
        boxes.append([float(left_coord), float(t), float(r), float(b)])
    # Different letters can occupy adjacent rows without sharing pixels. A
    # one-pixel descender overlap can be fitted to the measured common border.
    for upper, lower in zip(boxes, boxes[1:]):
        if upper[3] > lower[1] + 1:
            return ()
        if upper[3] >= lower[1]:
            middle = (upper[3] + lower[1])/2
            upper[3], lower[1] = middle-.5, middle+.5
    return tuple(((left_coord, t), (r, t), (r, b), (left_coord, b)) for left_coord, t, r, b in boxes)


def refine_bilingual_source_bands(gray, texts, cells, *, protected_source_masks=()):
    """Tighten colliding TEXT to its own row without changing source ownership."""
    if not cells or not librecad_font_available():
        return tuple(texts), ()
    keys = {}
    for i, text in enumerate(texts):
        keys.setdefault((text.text, text.bbox), []).append(i)
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    output, changed = list(texts), []
    def transform(x, y):
        return (x, gray.shape[0]-y)
    for cell, members in cells.items():
        if not 2 <= len(members) <= 3 or any(len(keys.get(k, ())) != 1 for k in members):
            continue
        indexes = sorted((keys[k][0] for k in members),
                         key=lambda i: texts[i].bbox[1] + texts[i].bbox[3]/2)
        rows = [texts[i] for i in indexes]
        if (not _cjk(rows[0].text) or any(not t.text.isascii() or not any(c.isalpha() for c in t.text)
                                        for t in rows[1:])
                or any(id(t) not in accepted or t.reviewed or output[i].display_quad is not None
                       or not t.source.startswith("rapidocr") or abs(t.rotation_deg) > 3.5
                       or (t.quad and (t.quad[1][0] <= t.quad[0][0] or t.quad[2][0] <= t.quad[3][0]))
                       for i, t in zip(indexes, rows, strict=True))):
            continue
        old_quads = [t.quad or ((0, t.bbox[1]), (0, t.bbox[1]+t.bbox[3])) for t in rows]
        if not any(max(p[1] for p in a) >= min(p[1] for p in b) for a, b in zip(old_quads, old_quads[1:])):
            continue
        quads = _source_row_boxes(gray, rows, cell)
        if not quads:
            continue
        if any(mask[int(t):int(np.ceil(b)), int(left_coord):int(np.ceil(r))].any()
               for ((left_coord, t), _, (r, b), _) in quads for mask in protected_source_masks):
            continue
        proposals = [replace(t, display_quad=q) for t, q in zip(rows, quads, strict=True)]
        placements = [native_text_placement(t, transform=transform) for t in proposals]
        if any(p is None or p.metrics.fallback_reason for p in placements):
            continue
        paths = [glyph_footprint(p) for p in placements]
        left, top, right, bottom = cell
        blocked = False
        for i, old in enumerate(output):
            x, y, w, h = old.bbox
            if i in indexes or id(texts[i]) not in accepted or x+w < left or x > right or y+h < top or y > bottom:
                continue
            placement = native_text_placement(old, transform=transform)
            if placement is None or placement.metrics.fallback_reason:
                blocked = True
                break
            footprint = glyph_footprint(placement)
            if any(path.intersects(footprint) for path in paths):
                blocked = True
                break
        if not blocked:
            for i, proposal in zip(indexes, proposals, strict=True):
                output[i] = proposal
                changed.append(i)
    return tuple(output), tuple(changed)
