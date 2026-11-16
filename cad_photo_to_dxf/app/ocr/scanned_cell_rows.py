"""Fit compact printed rows to their source ink inside a ruled cell."""
from __future__ import annotations

from dataclasses import replace
from itertools import pairwise, product
from math import isfinite
import re

import cv2
import numpy as np
from PySide6.QtGui import QPainterPath

from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import glyph_footprint
from app.geometry.text_residual_retirement import pixel_runs
from app.ocr.librecad_lff import librecad_text_metrics


def compact_printed_rows(rows):
    if not 2 <= len(rows) <= 6:
        return False
    for row in rows:
        _, _, width, height = row.bbox
        content = "".join(row.text.split())
        if (
            row.reviewed or row.display_quad is not None
            or not row.source.startswith("rapidocr") or row.confidence < .9
            or not isfinite(row.rotation_deg) or abs(row.rotation_deg) > 2
            or width < 5 * height or height <= 0
            or not content.isascii() or not any(c.isalnum() for c in content)
            or len(content) != len(row.character_boxes)
        ):
            return False
        if row.quad is not None and (
            len(row.quad) != 4 or row.quad[1][0] <= row.quad[0][0]
            or abs(row.quad[1][1] - row.quad[0][1]) > .04 * width
        ):
            return False
    # Overlapping detector boxes and similar starts nominate a compact cell.
    # Source components below still need to establish the separate rows.
    return all(
        0 < b.bbox[1] - a.bbox[1] < a.bbox[3]
        and abs(a.bbox[0] - b.bbox[0]) <= min(a.bbox[3], b.bbox[3]) / 2
        for a, b in pairwise(rows)
    )


def _path(mask, left, top, height):
    path = QPainterPath()
    for y, x0, x1 in pixel_runs(mask, left, top):
        path.addRect(x0, height - y - 1, x1 - x0, 1)
    return path


def _fit(row, box, scale, slope, intercept, shift=0.):
    left, _, right, _ = box
    left += shift
    right += shift
    metrics = librecad_text_metrics(row.text)
    if right <= left or metrics.width <= 0 or metrics.height <= 0 or metrics.fallback_glyph_count:
        return None
    tangent = np.array((1., slope))
    tangent /= np.linalg.norm(tangent)
    down = np.array((-tangent[1], tangent[0]))
    start = np.array((left, slope * left + intercept))
    end = np.array((right, slope * right + intercept))
    upper, lower = -metrics.max_y * scale * down, -metrics.min_y * scale * down
    quad = tuple(tuple(map(float, p)) for p in (start + upper, end + upper, end + lower, start + lower))
    return replace(row, display_quad=quad)


def _ink_box(ink, left, top):
    x, y, w, h = cv2.boundingRect(np.uint8(ink))
    return left + x + .5, top + y, left + x + w - .5, top + y + h


def _numeric_field(row, owned, left, top, contacts, cap_height):
    """Keep a contiguous numeric value editable when the full row cannot fit."""
    for gap in re.finditer(r"\s+", row.text):
        prefix = row.text[:gap.start()]
        value = row.text[gap.end():]
        if not any(c.isalpha() for c in prefix) or not any(c.isdigit() for c in value):
            continue
        if any(c.isalpha() for c in value):
            continue
        index = len("".join(prefix.split()))
        x, _, w, _ = row.character_boxes[index - 1]
        u, _, v, _ = row.character_boxes[index]
        a, b = max(0, round(x + w / 2) - left), min(owned.shape[1], round(u + v / 2) - left)
        empty = np.flatnonzero(~owned[:, a:b].any(axis=0)) + a
        if not empty.size:
            return ()
        gap_pixels = max(np.split(empty, np.flatnonzero(np.diff(empty) > 1) + 1), key=len)
        if len(gap_pixels) < max(2, cap_height / 4):
            return ()
        cut = int(gap_pixels[len(gap_pixels) // 2])
        if contacts[:, :cut].any() or not owned[:, :cut].any() or not owned[:, cut:].any():
            return ()
        output = []
        for content, boxes, ink, x0 in (
            (prefix, row.character_boxes[:index], owned[:, :cut], left),
            (value, row.character_boxes[index:], owned[:, cut:], left + cut),
        ):
            box = _ink_box(ink, x0, top)
            x, y, u, v = box
            x, u = int(x), int(u) + 1
            output.append((
                replace(row, text=content, bbox=(x, y, u - x, v - y),
                        quad=((x, y), (u, y), (u, v), (x, v)),
                        character_boxes=boxes, pre_cell_observation=None),
                box,
            ))
        return tuple(output)
    return ()


def measure_compact_cell(gray, binary, rows, cell, *, visible, line_mask, protected_masks):
    left, top, right, bottom = cell
    margin = max(2, round(float(np.median([t.bbox[3] for t in rows])) / 2))
    y0, y1 = max(0, top - margin), min(gray.shape[0], bottom + margin)
    if not 0 <= left < right <= gray.shape[1] or y1 <= y0 or (right - left) * (y1 - y0) > 65_536:
        return None
    window = np.s_[y0:y1, left:right]
    source = gray[window]
    strong = source < 128
    source_ink = binary[window] < 128
    width = right - left
    rule = cv2.morphologyEx(
        np.uint8(source < 192), cv2.MORPH_OPEN, np.ones((1, max(9, round(.4 * width))), np.uint8)
    ) > 0
    centers = np.array([t.bbox[1] + t.bbox[3] / 2 - y0 for t in rows])
    ruling = np.flatnonzero(rule.sum(axis=1) >= .65 * width)
    above, below = ruling[ruling < centers[0]], ruling[ruling > centers[-1]]
    if not above.size or not below.size or np.any((centers[0] <= ruling) & (ruling <= centers[-1])):
        return None
    start, end = above[-1] + 1, below[0]
    if start >= end:
        return None
    rule &= source_ink
    cores = strong & ~rule
    cores[:start] = False
    cores[end:] = False
    projection = cores.sum(axis=1)
    cuts = [int(start)]
    for a, b in pairwise(centers):
        middle = (a + b) / 2
        radius = (b - a) / 4
        probe = range(max(cuts[-1] + 1, int(np.ceil(middle - radius))),
                      min(end - 1, int(np.floor(middle + radius)) + 1))
        if not probe:
            return None
        valley = min(probe, key=lambda y: (projection[y], abs(y - middle)))
        if projection[valley] >= min(projection[cuts[-1]:valley].max(), projection[valley + 1:end].max()) / 2:
            return None
        cuts.append(valley + 1)
    cuts.append(int(end))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(cores), connectivity=8)
    protected = np.zeros_like(cores)
    for mask in protected_masks:
        protected |= mask[window] > 0
    line_ink = line_mask[window] > 0
    near_rule = cv2.dilate(np.uint8(rule), np.ones((3, 3), np.uint8)) > 0
    # Short islands rooted at the rule without a body in a row belong to the
    # existing edge evidence. A descending glyph must have ink above the edge.
    rule_stubs = [
        label for label in np.unique(labels[near_rule])
        if label and stats[label, cv2.CC_STAT_HEIGHT] <= 2
    ]
    stubs = np.isin(labels, rule_stubs)
    rule |= stubs
    transform = lambda x, y: (x, gray.shape[0] - y)
    rule_path = _path(rule, left, y0, gray.shape[0])
    protected_path = _path(protected & source_ink & ~rule, left, y0, gray.shape[0])
    measured = []
    prior_paths = []
    for row, a, b in zip(rows, cuts[:-1], cuts[1:], strict=True):
        x, _, w, h = row.bbox
        owners = []
        anchors = []
        for label, (gx, gy, gw, gh, area) in enumerate(stats[1:].tolist(), 1):
            if gy >= b or gy + gh <= a or gx + gw <= x - left - 1 or gx >= x + w - left + 1:
                continue
            if gy < a or gy + gh > b or gx + left < x - 1 or gx + gw + left > x + w + 1:
                return None
            if area >= 2 and label not in rule_stubs:
                owners.append(label)
            if gh >= .33 * h and gw <= h and area >= .4 * h:
                anchors.append((left + gx + gw / 2, y0 + gy + gh, gh))
        if len(anchors) < 4:
            return None
        ax, baseline, cap = np.array(anchors).T
        # Broken source components can shorten glyphs. The upper quartile
        # estimates the repeated cap body without using the tallest descender.
        cap_height = float(np.quantile(cap, .75, method="nearest"))
        ordinary = abs(cap - cap_height) <= 1
        if ordinary.sum() < 4:
            return None
        slope, intercept = map(float, np.polyfit(ax[ordinary], baseline[ordinary] - .5, 1))
        if abs(slope) > .035 or np.max(abs(baseline[ordinary] - .5 - slope * ax[ordinary] - intercept)) > 1.5:
            return None
        owned = np.isin(labels, owners)
        if not all(owned[:, max(0, bx - left - 1):bx + bw - left + 1].any()
                   for bx, _, bw, _ in row.character_boxes):
            return None
        box = _ink_box(owned, left, y0)
        contact = owned & near_rule
        count, contacts, _, centroids = cv2.connectedComponentsWithStats(
            np.uint8(contact), connectivity=8,
        )
        contact_paths = [
            _path((cv2.dilate(np.uint8(contacts == j), np.ones((5, 7), np.uint8)) > 0) & rule,
                  left, y0, gray.shape[0])
            for j in range(1, count)
        ]
        allowed_contact = QPainterPath()
        for path in contact_paths:
            allowed_contact.addPath(path)
        blocked_rule = rule_path.subtracted(allowed_contact)
        best = None
        scale = cap_height / librecad_text_metrics(row.text).em_height
        alternatives = [((row, box),)]
        if contact_paths:
            field = _numeric_field(row, owned, left, y0, contact, cap_height)
            if field:
                alternatives.append(field)
        for spans in alternatives:
            # Try the whole line first. Both spans of a split use one baseline.
            # Only the contact-bearing span may move across the measured
            # contact pixels. Detached spans retain their measured X anchor.
            shifts = (0., -.5, .5, -1., 1., -1.5, 1.5) if contact_paths else (0.,)
            for offset, shift in product((0., .5, -.5, .75, 1.), shifts):
                fits = tuple(
                    _fit(item, bounds, scale, slope, intercept + offset,
                         shift if i == len(spans) - 1 else 0.)
                    for i, (item, bounds) in enumerate(spans)
                )
                if any(fit is None for fit in fits):
                    break
                placements = tuple(native_text_placement(fit, transform=transform) for fit in fits)
                if any(placement is None for placement in placements):
                    continue
                paths = tuple(glyph_footprint(placement) for placement in placements)
                if (any(p.intersects(blocked_rule) or p.intersects(protected_path)
                        or any(p.intersects(q) for q in prior_paths) for p in paths)
                        or any(p.intersects(q) for i, p in enumerate(paths) for q in paths[i + 1:])):
                    continue
                combined = QPainterPath()
                for path in paths:
                    combined.addPath(path)
                hits = [combined.intersected(path) for path in contact_paths]
                if any(hit.isEmpty() for hit in hits):
                    continue
                errors = [
                    abs(hit.boundingRect().center().x() - (left + xy[0] + .5))
                    for hit, xy in zip(hits, centroids[1:], strict=True)
                ]
                quality = (max(errors, default=0.), sum(errors), len(spans), abs(offset), abs(shift))
                if best is None or quality < best[0]:
                    best = (quality, fits, paths, offset)
                if not contact_paths:
                    break
        if best is None:
            return None
        _, proposals, paths, offset = best
        # Keep exact rule pixels. Assign a one-pixel fringe only to the
        # measured row, and never transfer protected or competing ink.
        fringe = cv2.dilate(np.uint8(owned), np.ones((3, 3), np.uint8)) > 0
        fringe[:a] = False
        fringe[b:] = False
        exclusive = fringe & source_ink & ~rule
        if np.any(exclusive & protected) or np.any(exclusive & line_ink & visible[window] & ~near_rule):
            return None
        clear = exclusive & visible[window] & ~line_ink
        contact_rule = rule & (cv2.dilate(np.uint8(contact), np.ones((5, 3), np.uint8)) > 0)
        prior_paths.extend(paths)
        row_id = ",".join(map(str, row.bbox))
        proposals = tuple(
            replace(fit, logical_line=(row_id, i, len(proposals)))
            for i, fit in enumerate(proposals, 1)
        )
        measured.append((proposals, clear, {
            "text": row.text,
            "ocr_box": row.bbox,
            "baseline": (slope, intercept + offset),
            "cap_height_px": cap_height,
            "logical_line": row.text,
            "logical_line_id": row_id,
            "native_spans": [{"text": fit.text, "display_quad": fit.display_quad} for fit in proposals],
            "source_contact_runs": pixel_runs(contact, left, y0),
            "contact_rule_runs": pixel_runs(contact_rule, left, y0),
            "shared_line_runs": pixel_runs(exclusive & line_ink, left, y0),
            "rule_runs": pixel_runs(rule, left, y0),
            "retired_runs": pixel_runs(clear, left, y0),
        }))
    return window, rule, measured
