"""Recover pen paint exposed by removing independently drawn PDF cell rules."""

import ctypes as ct
from dataclasses import replace
from math import ceil

import cv2
import numpy as np
import pypdfium2 as pdf

from app.diagnostics.observability import rasterize_lines
from app.geometry.native_pdf_paths import (
    OCCLUSION_GRAY_ALLOWANCE,
    _local_render,
    _segments,
    render_without_active_objects,
)


def _window(box):
    left, top, right, bottom = box
    return np.s_[top:bottom, left:right]


def _rule_objects(page, size, bounds, rules, scale):
    raw = pdf.raw
    left, top, right, bottom = bounds
    x, y, u, v = (ct.c_int() for _ in range(4))
    active = raw.FPDF_BOOL()
    mode, stroke = ct.c_int(), raw.FPDF_BOOL()
    for obj in page.get_objects(max_depth=1):
        if obj.type != raw.FPDF_PAGEOBJ_PATH or not 2 <= raw.FPDFPath_CountSegments(obj) <= 5:
            continue
        a, b, c, d = obj.get_bounds()
        if max(c-a, d-b)*scale < 64 or min(c-a, d-b)*scale > 8:
            continue
        if not (
            raw.FPDF_PageToDevice(page, 0, 0, *size, 0, a, b, ct.byref(x), ct.byref(y))
            and raw.FPDF_PageToDevice(page, 0, 0, *size, 0, c, d, ct.byref(u), ct.byref(v))
        ):
            continue
        l, r = sorted((x.value, u.value))
        t, z = sorted((y.value, v.value))
        box = (max(left, l-1), max(top, t-1), min(right, r+1), min(bottom, z+1))
        if box[2]-box[0] < 2 or box[3]-box[1] < 2:
            continue
        vertical = z-t > r-l
        support = (rules[_window(box)] > 0).any(axis=1 if vertical else 0)
        if support.size < 32 or support.mean() < .8:
            continue
        segments = _segments(obj)
        if (segments[0][0] != 2 or any(s[0] != 0 for s in segments[1:])
                or not raw.FPDFPageObj_GetIsActive(obj, ct.byref(active)) or not active.value):
            continue
        if not raw.FPDFPath_GetDrawMode(obj, ct.byref(mode), ct.byref(stroke)):
            continue
        if (mode.value and len(segments) < 4) or (not mode.value and (not stroke.value or len(segments) != 2)):
            continue
        matrix = obj.get_matrix()
        vertices = []
        for _, point, _ in segments:
            if not raw.FPDF_PageToDevice(page, 0, 0, *size, 0, *matrix.on_point(*point),
                                         ct.byref(x), ct.byref(y)):
                break
            vertices.append((y.value, x.value) if vertical else (x.value, y.value))
        length = z-t if vertical else r-l
        if len(vertices) != len(segments) or not any(
            a[1] == b[1] and abs(a[0]-b[0]) >= .9*length for a, b in zip(vertices, vertices[1:])
        ):
            continue
        yield obj, box, vertical


def _crossing_labels(labels, seed, local_box, band, vertical):
    l, t, r, b = local_box
    x, y, u, v = band
    if vertical:
        labels, seed = labels.T, seed.T
        l, t, r, b, x, y, u, v = t, l, b, r, y, x, v, u
    start, stop = y-t, v-t
    first, last = max(0, x-l), min(r-l, u-l)
    if not (1 <= start < stop < b-t and first < last):
        return set()
    near = labels[max(0, start-2):start, first:last]
    far = labels[stop:stop+2, first:last]
    return set(np.unique(near)).intersection(np.unique(far), np.unique(labels[seed])) - {0}


def restore_pdf_signature_crossings(gray, regions, rules, binding, *, protected_masks=(), structural_lines=()):
    """Use isolated pen pixels on both sides of a rule, including their gray edges."""
    if not regions or rules is None:
        return regions
    padding = 20
    size = gray.shape[::-1]
    left = max(0, min(r.bbox[0] for r in regions)-padding)
    top = max(0, min(r.bbox[1] for r in regions)-padding)
    right = min(size[0], max(r.bbox[0]+r.bbox[2] for r in regions)+padding)
    bottom = min(size[1], max(r.bbox[1]+r.bbox[3] for r in regions)+padding)
    bounds = (left, top, right, bottom)
    if (right-left)*(bottom-top) > 750_000 or not np.any(rules[_window(bounds)]):
        return regions
    try:
        with pdf.PdfDocument(binding["document"]) as doc:
            page = doc[int(binding["page_number"])-1]
            scale = float(binding["requested_dpi"])/72
            if (tuple(ceil(d*scale) for d in page.get_size()) != size
                    or pdf.raw.FPDFPage_CountObjects(page) > 200_000):
                return regions
            verified = list(_rule_objects(page, size, bounds, rules, scale))
            if not 1 <= len(verified) <= 32:
                return regions
            original = _local_render(page, bounds, size)
            exposed = render_without_active_objects(page, bounds, size, (o for o, _, _ in verified))
    except (IndexError, KeyError, OSError, ValueError, pdf.PdfiumError):
        return regions
    source = gray[_window(bounds)]
    bands = [(x-left, y-top, u-left, v-top, vertical) for _, (x, y, u, v), vertical in verified]
    in_band = np.zeros(source.shape, dtype=bool)
    for *box, _ in bands:
        in_band[_window(box)] = True
    # PDFium can quantize isolated source vertices differently in a clipped
    # render. Every rule strip must agree, and disagreeing pixels elsewhere
    # cannot supply pen paint or join two components.
    consistent = ((original < 128) == (source < 128)) & (
        np.abs(original.astype(np.int16)-source) <= OCCLUSION_GRAY_ALLOWANCE
    )
    if not np.all(consistent[in_band]):
        return regions
    changed = exposed.astype(np.int16)-original
    if np.any(changed < -OCCLUSION_GRAY_ALLOWANCE) or np.any((changed > OCCLUSION_GRAY_ALLOWANCE) & ~in_band):
        return regions

    usable = (rules[_window(bounds)] == 0) | in_band
    if structural_lines:
        # The ownership tolerance band may include pen ink beyond the actual
        # CAD stroke. Use its nominal footprint when testing the exposed pen.
        line_ink = rasterize_lines(structural_lines, source.shape, origin=(left, top))
        usable &= (line_ink == 0) | in_band
    for mask in protected_masks:
        if mask is not None:
            usable &= mask[_window(bounds)] == 0
    owner = np.zeros(source.shape, dtype=np.int16)
    for i, region in enumerate(regions, 1):
        x, y, w, h = region.bbox
        local = owner[y-top:y-top+h, x-left:x-left+w]
        local[region.mask > 0] = i

    proposals = []
    claims = np.zeros(source.shape, dtype=np.uint8)
    for i, region in enumerate(regions, 1):
        x, y, w, h = region.bbox
        x, y = x-left, y-top
        l, t = max(0, x-padding), max(0, y-padding)
        r, b = min(right-left, x+w+padding), min(bottom-top, y+h+padding)
        local_box = (l, t, r, b)
        win = _window(local_box)
        old = np.zeros((b-t, r-l), dtype=np.uint8)
        old[y-t:y-t+h, x-l:x-l+w] = region.mask
        other = (owner[win] != 0) & (owner[win] != i)
        allowed = (usable[win] | (old > 0)) & ~other & consistent[win]
        pen = exposed[win]
        _, labels = cv2.connectedComponents(np.uint8((pen < 128) & allowed), connectivity=8)
        crossing = set()
        for *band, vertical in bands:
            crossing.update(_crossing_labels(labels, old >= 128, local_box, band, vertical))
        # A component cut by the probe edge could continue into foreign ink.
        crossing.difference_update(np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        alpha = old.copy()
        rule_only = (pen == 255) & (changed[win] > OCCLUSION_GRAY_ALLOWANCE) & in_band[win]
        alpha[rule_only] = 0
        if crossing:
            core = np.isin(labels, tuple(crossing))
            fringe = cv2.dilate(np.uint8(core), np.ones((3, 3), np.uint8)) > 0
            near_rule = cv2.dilate(np.uint8(in_band[win]), np.ones((5, 5), np.uint8)) > 0
            outside = np.ones(old.shape, dtype=bool)
            outside[y-t:y-t+h, x-l:x-l+w] = False
            recovered = fringe & allowed & (pen < 255) & (
                in_band[win] | ((old == 0) & (near_rule | outside))
            )
            alpha[recovered] = 255-pen[recovered]
        claims[win][(alpha > 0) & (old == 0)] += 1
        proposals.append((region, local_box, alpha, old))
    output = []
    for region, box, alpha, old in proposals:
        l, t, _, _ = box
        alpha[(claims[_window(box)] != 1) & (old == 0)] = 0
        if np.array_equal(alpha, old) or not alpha.any():
            output.append(region)
            continue
        x, y, w, h = cv2.boundingRect(alpha)
        output.append(replace(region, bbox=(left+l+x, top+t+y, w, h),
                              mask=alpha[y:y+h, x:x+w].copy()))
    return tuple(output)
