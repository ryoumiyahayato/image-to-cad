"""Measure closely spaced printed rows in a ruled scan on the source grid."""
from dataclasses import replace
from itertools import pairwise

import cv2
import numpy as np
from PySide6.QtGui import QPainterPath

from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import glyph_footprint
from app.geometry.text_residual_retirement import pixel_runs
from app.ocr.librecad_lff import librecad_font_available, librecad_text_metrics
from app.ocr.scanned_cell_rows import compact_printed_rows, measure_compact_cell
from app.ocr.text_output_contract import accepted_ocr_texts


def _eligible(text):
    _, _, w, h = text.bbox
    letters = [c for c in text.text if c.isalpha()]
    return (
        text.source.startswith("rapidocr") and text.confidence >= .9
        and not text.reviewed and text.display_quad is None and abs(text.rotation_deg) <= 2
        and text.text.isascii() and len(letters) >= 12 and all(c.isupper() for c in letters)
        and w >= 5*h and len(text.character_boxes) == len("".join(text.text.split()))
        and text.quad is not None and text.quad[1][0] > text.quad[0][0]
        and abs(text.quad[1][1]-text.quad[0][1]) <= .04*w
    )


def _span(text, content, glyph_boxes, baseline, cap_scale):
    """Recover placement from measured left/right ink, reading axis and baseline."""
    left = glyph_boxes[0][0] + .5
    right = glyph_boxes[-1][2] - .5
    if right <= left:
        return None
    slope, intercept = baseline
    tangent = np.array((1.0, slope))
    tangent /= np.linalg.norm(tangent)
    down = np.array((-tangent[1], tangent[0]))
    start = np.array((left, slope*left+intercept))
    end = start + tangent*((right-left)/tangent[0])
    metrics = librecad_text_metrics(content)
    if metrics.fallback_glyph_count or metrics.width <= 0 or metrics.height <= 0:
        return None
    top, bottom = -metrics.max_y*cap_scale, -metrics.min_y*cap_scale
    quad = tuple(tuple(map(float, p)) for p in
                 (start+down*top, end+down*top, end+down*bottom, start+down*bottom))
    x, y = glyph_boxes[0][0], min(b[1] for b in glyph_boxes)
    u, v = glyph_boxes[-1][2], max(b[3] for b in glyph_boxes)
    return replace(text, text=content, bbox=(x,y,u-x,v-y),
                   quad=((x,y),(u,y),(u,v),(x,v)), display_quad=quad,
                   character_boxes=tuple((x,y,u-x,v-y) for x,y,u,v in glyph_boxes))


def _measure_row(gray, text):
    x, y, w, h = text.bbox
    left, top = max(0, x-3), max(0, y-3)
    right, bottom = min(gray.shape[1], x+w+3), min(gray.shape[0], y+h+3)
    win = np.s_[top:bottom, left:right]
    patch = gray[win]
    strong = patch < 128
    # Long observed runs in the lower part of the row. The source can have a
    # shallow slope, so multiple collinear horizontal runs can support a rule.
    rule = cv2.morphologyEx(np.uint8(patch < 192), cv2.MORPH_OPEN,
                            np.ones((1, max(9, round(.16*w))), np.uint8)) > 0
    rule[:max(0, y-top+round(.72*h))] = False
    if np.count_nonzero(rule.any(axis=0)) < .79*w:
        rule[:] = False
    labels, stats = cv2.connectedComponentsWithStats(
        np.uint8(strong & ~rule), connectivity=8)[1:3]
    char_indices = [i for i, c in enumerate(text.text) if not c.isspace()]
    chars = [text.text[i] for i in char_indices]
    glyphs = [i for i, (gx, gy, gw, gh, area) in enumerate(stats[1:], 1)
              if gh >= .39*h and area >= .30*h and gw < .85*h]
    short = [i for i, c in enumerate(chars) if librecad_text_metrics(c).height < 5]
    for i in short:
        bx, by, bw, bh = text.character_boxes[i]
        small = [j for j, (gx, gy, gw, gh, area) in enumerate(stats[1:], 1)
                 if 2 <= gh < .39*h and area >= 4 and gw <= .32*h
                 and bx-1 <= left+gx+gw/2 <= bx+bw+1 and by-2 <= top+gy+gh/2 <= by+bh+2]
        if len(small) != 1:
            return None
        glyphs += small
    glyphs.sort(key=lambda i: stats[i, 0])
    if len(glyphs) != len(chars) or len(set(glyphs)) != len(chars):
        return None

    boxes, contacts = [], set()
    glyph_ink = np.isin(labels, glyphs)
    for i, (label, char_box) in enumerate(zip(glyphs, text.character_boxes, strict=True)):
        gx, gy, gw, gh, _ = map(int, stats[label])
        bx, _, bw, _ = char_box
        # The detector's character height can describe just the underline.
        # The ordered, complete ink components establish vertical placement.
        if not bx-.35*h <= left+gx+gw/2 <= bx+bw+.35*h:
            return None
        owned = labels == label
        if rule.any() and np.any(cv2.dilate(np.uint8(owned), np.ones((3, 3), np.uint8)) & rule):
            contacts.add(i)
            # Follow a short fragment across the measured rule within this
            # glyph's own columns. The original rule itself stays fixed.
            band = rule[:, max(0,gx-1):gx+gw+1]
            hits = np.flatnonzero(band.any(axis=1))
            if hits.size:
                rest = labels[hits[-1]+1:, max(0,gx-1):gx+gw+1]
                for tail in np.unique(rest[:2]):
                    if tail == 0 or tail in glyphs:
                        continue
                    tx, ty, tw, th, _ = map(int, stats[tail])
                    if ty >= hits[-1] and th <= .24*h and gx-2 <= tx < tx+tw <= gx+gw+2:
                        owned |= labels == tail
                glyph_ink |= owned
        ax, ay, aw, ah = cv2.boundingRect(np.uint8(owned))
        boxes.append((left+ax, top+ay, left+ax+aw, top+ay+ah))
    ordinary = [i for i,c in enumerate(chars) if c.isalpha() and i not in contacts]
    if len(ordinary) < 12:
        return None
    metrics = [librecad_text_metrics(c) for c in chars]
    scale = float(np.median([(boxes[i][3]-boxes[i][1]-1)/metrics[i].height for i in ordinary]))
    anchors = np.array([(boxes[i][0], boxes[i][3]-.5+metrics[i].min_y*scale) for i in ordinary])
    slope, intercept = map(float, np.polyfit(anchors[:,0], anchors[:,1], 1))
    if abs(slope) > .035 or np.max(np.abs(anchors[:,1]-slope*anchors[:,0]-intercept)) > max(2, .10*h):
        return None

    spans = []
    cuts = sorted({0, len(chars), *contacts, *(i+1 for i in contacts)})
    for a, b in pairwise(cuts):
        content = text.text[char_indices[a]:char_indices[b-1]+1]
        if a in contacts:
            gx, gy, gu, gb = boxes[a]
            m = metrics[a]
            # Use the observed contact edge when a glyph ends at the rule.
            # A stroke that extends across it keeps its actual lower edge.
            stop = float(gb if gb < bottom and rule[gb-top,gx-left:gu-left].any() else gb-.5)
            local_scale = (stop-gy-.5)/m.height
            baseline = slope, stop+m.min_y*local_scale-slope*(gx+.5)
        else:
            local_scale = scale
            baseline = slope, intercept
        proposal = _span(text, content, boxes[a:b], baseline, local_scale)
        if proposal is None:
            return None
        spans.append(proposal)
    fringe = cv2.dilate(np.uint8(glyph_ink), np.ones((3, 3), np.uint8)) > 0
    fixed = cv2.dilate(np.uint8(rule), np.ones((3, 1), np.uint8)) > 0
    return spans, win, fringe & ~fixed, rule, boxes, contacts, (slope, intercept)



def _coalesce_cell_candidates(cells):
    """Join near-identical locator boxes; measured source rules still decide.

    Table detection can assign rows from one physical cell boxes differing by
    one or two input pixels. This is nomination only, not source authority.
    Keep disjoint/stacked cells separate and use complete-link bounds so small
    differences cannot chain across a real separator.
    """
    groups = []
    for cell, members in sorted(cells.items()):
        chosen = None
        for old_cells, old_members in groups:
            if all(cell[0] == old[0] and cell[2] == old[2]
                   and abs(cell[1]-old[1]) <= 2 and abs(cell[3]-old[3]) <= 2
                   for old in old_cells):
                chosen = (old_cells, old_members)
                break
        if chosen is None:
            groups.append(([cell], list(members)))
        else:
            chosen[0].append(cell)
            chosen[1].extend(key for key in members if key not in chosen[1])
    return {
        (min(c[0] for c in boxes), min(c[1] for c in boxes),
         max(c[2] for c in boxes), max(c[3] for c in boxes)): tuple(members)
        for boxes, members in groups
    }


def _measurement_row(text):
    """Use the unchanged pre-cell characters only as measurement proposals.

    Clipping can drop a punctuation character-box on a rule. It must not make
    complete source-row measurement unreachable. Source components, contacts,
    protection masks and exclusivity are still checked before any commitment.
    The committed text's bbox and quad remain the current values.
    """
    observation = text.pre_cell_observation
    count = len("".join(text.text.split()))
    if (len(text.character_boxes) != count and observation is not None
            and observation.text == text.text and observation.source == text.source
            and len(observation.character_boxes) == count):
        return replace(text, character_boxes=observation.character_boxes)
    return text

def refine_scanned_title_rows(gray, binary, texts, cells, *, visible, protected_masks, line_mask=None):
    """Commit only source-proven row spacing and exclusive replacement ink."""
    retired = np.zeros_like(binary)
    fixed = np.zeros_like(binary)
    if not cells or not librecad_font_available():
        return texts, retired, fixed, ()
    keys = {}
    for i, item in enumerate(texts):
        keys.setdefault((item.text, item.bbox), []).append(i)
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    columns = {}
    for (left, _, right, _), members in cells.items():
        for key in members:
            found = keys.get(key, ())
            if len(found) == 1 and id(texts[found[0]]) in accepted and _eligible(texts[found[0]]):
                columns.setdefault((left, right), set()).add(found[0])
    replacements, records = {}, []
    transform = lambda x, y: (x, gray.shape[0]-y)
    for indexes in columns.values():
        ordered = sorted(indexes, key=lambda i: texts[i].bbox[1])
        for triple in zip(ordered, ordered[1:], ordered[2:]):
            if any(i in replacements for i in triple):
                continue
            rows = [texts[i] for i in triple]
            if any(not .75*a.bbox[3] <= b.bbox[1]-a.bbox[1] <= 1.55*a.bbox[3]
                   or abs(a.bbox[0]+a.bbox[2]/2-b.bbox[0]-b.bbox[2]/2) > a.bbox[3]
                   for a,b in pairwise(rows)):
                continue
            measured = [_measure_row(gray, row) for row in rows]
            if any(m is None for m in measured) or not all(m[3].any() for m in measured[:2]):
                continue
            group_paths = []
            for spans, win, _ink, rule, boxes, contacts, _base in measured:
                top, left = win[0].start, win[1].start
                rules = QPainterPath()
                for y,x0,x1 in pixel_runs(rule, left, top):
                    rules.addRect(x0, gray.shape[0]-y-1, x1-x0, 1)
                overlap = QPainterPath()
                for k in contacts:
                    x,y,u,v = boxes[k]
                    overlap.addRect(x-1, gray.shape[0]-v-1, u-x+2, v-y+2)
                paths = []
                contacts_rendered = QPainterPath()
                for t in spans:
                    p = native_text_placement(t, transform=transform)
                    if p is None:
                        break
                    path = glyph_footprint(p)
                    paths.append(path)
                    contacts_rendered.addPath(path.intersected(rules))
                if (len(paths) != len(spans)
                        or any(p.intersects(rules.subtracted(overlap)) for p in paths)
                        or any(not contacts_rendered.intersects(rect.boundingRect())
                               for rect in overlap.toSubpathPolygons())):
                    break
                group_paths.extend(paths)
            if len(group_paths) != sum(len(m[0]) for m in measured) or any(
                a.intersects(b) for i,a in enumerate(group_paths) for b in group_paths[i+1:]
            ):
                continue
            for i, (spans, win, ink, rule, boxes, contacts, base) in zip(triple, measured, strict=True):
                measured_rule = (cv2.dilate(np.uint8(rule), np.ones((3, 1), np.uint8)) > 0)
                measured_rule &= binary[win] < 128
                fixed[win][measured_rule] = 255
                clear = ink & (binary[win] < 128) & visible[win]
                for mask in protected_masks:
                    clear &= mask[win] == 0
                retired[win][clear] = 255
                replacements[i] = spans
                records.append(dict(text=texts[i].text, ocr_box=texts[i].bbox,
                                    ocr_character_boxes=texts[i].character_boxes,
                                    source_glyph_boxes=boxes, baseline=base,
                                    shared_characters=sorted(contacts),
                                    native_spans=[dict(text=t.text, display_quad=t.display_quad)
                                                  for t in spans],
                                    rule_runs=pixel_runs(measured_rule, win[1].start, win[0].start),
                                    retired_runs=pixel_runs(clear, win[1].start, win[0].start)))
    for cell, members in _coalesce_cell_candidates(cells).items():
        if line_mask is None:
            break
        if any(len(keys.get(key, ())) != 1 for key in members):
            continue
        indexes = sorted((keys[key][0] for key in members), key=lambda i: texts[i].bbox[1])
        if any(i in replacements or id(texts[i]) not in accepted for i in indexes):
            continue
        rows = tuple(_measurement_row(texts[i]) for i in indexes)
        if not compact_printed_rows(rows):
            continue
        measured = measure_compact_cell(
            gray, binary, rows, cell, visible=visible, line_mask=line_mask,
            protected_masks=tuple(mask for mask in protected_masks if mask is not line_mask),
        )
        if measured is None:
            continue
        window, rule, fits = measured
        fixed[window][rule] = 255
        for i, (spans, clear, record) in zip(indexes, fits, strict=True):
            retired[window][clear] = 255
            replacements[i] = spans
            records.append(record)
    output = tuple(t for i, old in enumerate(texts) for t in replacements.get(i, (old,)))
    return output, retired, fixed, tuple(records)
