"""Source-bound enclosure relations; no symbol names or symbol library."""
from dataclasses import replace
from math import cos, sin, pi

import cv2
import numpy as np

from app.core.trace_types import TracePath
from app.ocr.logo_detection import LogoRegion
from app.ocr.text_output_contract import text_output_decisions


def _text_part(candidate, content, box):
    x, y, w, h = (int(v) for v in box)
    return replace(candidate, text=content, bbox=(x, y, w, h),
                   quad=((x, y), (x+w, y), (x+w, y+h), (x, y+h)),
                   character_boxes=(), source=candidate.source + ":enclosure-relation")


def resolve_enclosure_relations(binary, candidates, *, claimed_candidates=None):
    """Separate inside/outside characters only with a supported closed boundary.

    The returned TracePaths are committed native enclosure geometry; masks are
    source ownership footprints used to remove obsolete residual fragments.
    Uncertain bounded objects retain their original foreground as a graphic.
    """
    ink = np.where(binary < 128, 255, 0).astype(np.uint8)
    _, component_labels = cv2.connectedComponents(ink, connectivity=8)
    # Dense edge samples are needed for circularity: four square corners alone
    # have identical radii and must never be mistaken for a circular boundary.
    contours, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    proposals = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 12 or not .88 < w/h < 1.14 or max(w, h) > min(binary.shape)*.035:
            continue
        area = cv2.contourArea(contour)
        if area < w*h*.55:
            continue
        points = cv2.approxPolyDP(contour, .035*cv2.arcLength(contour, True), True)[:, 0]
        rectangle = len(points) == 4 and area/(w*h) > .80
        if rectangle:
            edges = np.roll(points, -1, axis=0)-points
            rectangle = all(min(abs(dx), abs(dy)) <= max(abs(dx), abs(dy))*.08 for dx, dy in edges)
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        radial = np.linalg.norm(contour[:, 0] - (cx, cy), axis=1)
        circle = not rectangle and np.std(radial) < max(.45, radius*.035) and .88 < w/h < 1.14
        matching = []
        for i, candidate in enumerate(candidates):
            content = candidate.text.strip()
            if not content or not content.isascii() or len(content) > 4:
                continue
            boxes = candidate.character_boxes
            if len(boxes) != len(content):
                boxes = (candidate.bbox,) if len(content) == 1 else ()
            inside = [j for j, (bx, by, bw, bh) in enumerate(boxes)
                      if x+2 < bx+bw*.5 < x+w-2 and y+2 < by+bh*.5 < y+h-2]
            if inside:
                matching.append((i, inside, boxes))
        if not matching:
            continue
        # Independent internal ink prevents treating an O/0 glyph as enclosure.
        interior = ink[y+3:y+h-3, x+3:x+w-3]
        boundary_components = np.unique(component_labels[contour[:,0,1],contour[:,0,0]])
        interior_components = component_labels[y+3:y+h-3,x+3:x+w-3]
        independent = (interior > 0) & ~np.isin(interior_components,boundary_components)
        if np.count_nonzero(independent) < 8:
            continue
        proposals.append((x, y, w, h, rectangle, circle, cx, cy, radius, matching))

    result = list(candidates)
    replacements = {}
    paths, records, graphics = [], [], []
    claimed = np.zeros_like(binary)
    taken = set()
    for x, y, w, h, rectangle, circle, cx, cy, radius, matching in sorted(
            proposals, key=lambda p: (0 if p[4] else 1 if p[5] else 2, p[2]*p[3])):
        # Nested ring boundaries describe one object, not two enclosures.
        if np.any(claimed[y+2:y+h-2, x+2:x+w-2]):
            continue
        if any(i in taken for i, _, _ in matching):
            continue
        local = ink[y:y+h, x:x+w]
        internal_text_safe = all(text_output_decisions((candidates[i],))[0].text_emit_eligible
                                 for i, _, _ in matching)
        if not (rectangle or circle) or not internal_text_safe:
            # RETR_LIST may propose the inner boundary of a thick ring. Include
            # the original surrounding ink rather than clipping that boundary.
            left, top = max(0,x-2), max(0,y-2)
            right, bottom = min(ink.shape[1],x+w+2), min(ink.shape[0],y+h+2)
            patch = ink[top:bottom,left:right].copy()
            graphics.append(LogoRegion((left, top, right-left, bottom-top), patch, .95, 0, 1,
                                       visual_kind="engineering_graphic"))
            for i, inside, boxes in matching:
                outside = [j for j in range(len(candidates[i].text.strip())) if j not in inside]
                groups = []
                for j in outside:
                    if not groups or j != groups[-1][-1]+1:
                        groups.append([j])
                    else:
                        groups[-1].append(j)
                parts = []
                for indices in groups:
                    selected = [boxes[j] for j in indices]
                    bx, by = min(b[0] for b in selected),min(b[1] for b in selected)
                    box = (bx,by,max(b[0]+b[2] for b in selected)-bx,max(b[1]+b[3] for b in selected)-by)
                    parts.append(_text_part(candidates[i], ''.join(candidates[i].text.strip()[j] for j in indices),box))
                replacements[i] = parts
                taken.add(i)
            claimed[top:bottom,left:right] = patch
            continue
        inside_ink = local.copy()
        inside_ink[:3] = inside_ink[-3:] = 0
        inside_ink[:, :3] = inside_ink[:, -3:] = 0
        if circle:
            yy, xx = np.indices(local.shape)
            inside_ink[(xx+x-cx)**2 + (yy+y-cy)**2 >= (radius-2)**2] = 0
        visible = cv2.findNonZero(inside_ink)
        if visible is None:
            continue
        ix, iy, iw, ih = cv2.boundingRect(visible)
        for i, inside, boxes in matching:
            candidate = candidates[i]
            content = candidate.text.strip()
            groups = []
            for j in range(len(content)):
                key = j in inside
                if not groups or groups[-1][0] != key:
                    groups.append((key, [j]))
                else:
                    groups[-1][1].append(j)
            parts = []
            for is_inside, indices in groups:
                text = "".join(content[j] for j in indices)
                if is_inside:
                    box = (x+ix, y+iy, iw, ih)
                else:
                    selected = [boxes[j] for j in indices]
                    left, top = min(b[0] for b in selected), min(b[1] for b in selected)
                    box = (left, top, max(b[0]+b[2] for b in selected)-left,
                           max(b[1]+b[3] for b in selected)-top)
                parts.append(_text_part(candidate, text, box))
            replacements[i] = parts
            taken.add(i)
        if rectangle:
            vertices = ((x-.5, y-.5), (x+w-.5, y-.5), (x+w-.5, y+h-.5), (x-.5, y+h-.5))
        else:
            radius += .5
            vertices = tuple((cx+radius*cos(2*pi*j/48), cy+radius*sin(2*pi*j/48)) for j in range(48))
        paths.append(TracePath(vertices, None, 0, len(paths)))
        records.append(dict(kind="rectangle" if rectangle else "circle", bbox=[x, y, w, h],
                            candidate_indices=[i for i, _, _ in matching]))
        claimed[y:y+h, x:x+w] = local
    result = tuple(part for i, candidate in enumerate(result)
                   for part in replacements.get(i, [candidate]))
    if claimed_candidates is not None:
        claimed_candidates.update(taken)
    return result, tuple(paths), tuple(records), tuple(graphics), claimed
