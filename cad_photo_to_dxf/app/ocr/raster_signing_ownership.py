"""Source-only ownership for scanned, ruled signing fields."""
from dataclasses import dataclass, replace
from itertools import combinations

import cv2
import numpy as np

from app.geometry.structural_roi import verified_structural_rule_masks
from app.ocr.logo_detection import LogoRegion
from app.ocr.ocr_layout import _projection_centers
from app.ocr.signature_overlay import SignatureRegion, source_ink_region


@dataclass(frozen=True)
class SigningField:
    box: tuple[int, int, int, int]


def _window(box):
    x, y, w, h = box
    return np.s_[y:y+h, x:x+w]


def _bounds(mask, x=0, y=0):
    bx, by, w, h = cv2.boundingRect(np.uint8(mask))
    return int(x+bx), int(y+by), w, h


def _components(mask):
    return cv2.connectedComponentsWithStats(np.uint8(mask), connectivity=8)[1:3]


def _field(text, horizontal, vertical):
    x, y, w, h = text.bbox
    left = max(0, x-2*h)
    right = min(horizontal.shape[1], x+w+4*h)
    band = vertical[max(0, y-h):y+3*h, left:right]
    columns = [left+v for v in _projection_centers(np.count_nonzero(band, axis=0) >= 2*h)]
    before = [v for v in columns if x-h <= v < x]
    after = [v for v in columns if v >= x+w]
    if not before or not after:
        return None
    left, right = max(before), min(after)
    # The field starts after the ruled heading row, and ends at the next rule.
    ruled = np.count_nonzero(horizontal[y:y+7*h, left+2:right-1], axis=1)
    rows = [y+v for v in _projection_centers(ruled > (right-left)*.58)]
    rows = [v for v in rows if v >= y+h-3]
    if len(rows) < 2 or not h <= rows[1]-rows[0] <= 5*h:
        return None
    return SigningField((left, rows[0], right-left, rows[1]-rows[0]))


def _in_field(text, field):
    x, y, w, h = text.bbox
    left, top, width, height = field.box
    return left < x < left+width and top < y+h*.5 < top+height


def _native_piece(text, reading, mask, left, top, boxes=()):
    x, y, w, h = _bounds(mask, left, top)
    return replace(
        text, text=reading, bbox=(x, y, w, h), rotation_deg=0,
        quad=((x, y), (x+w, y), (x+w, y+h), (x, y+h)),
        source=text.source+":signing-source", display_quad=None,
        character_boxes=tuple(boxes), replacement_safe=True, review_note="",
    )


def _repeated_print(gray, fields, texts, rules):
    """Use a clean instance of a repeated printed token to bound both readings."""
    for merged_field, short_field in (fields, fields[::-1]):
        short = [t for t in texts if _in_field(t, short_field) and t.confidence >= .9
                 and 1 < len(t.text) <= 4 and t.text.isascii() and t.text.isalpha()
                 and t.text.isupper()]
        for clean_reading in short:
            merged = [t for t in texts if _in_field(t, merged_field)
                      and t.text.startswith(clean_reading.text)
                      and len(t.text) > len(clean_reading.text)
                      and abs(t.bbox[0]-clean_reading.bbox[0]) <= 3]
            if len(merged) != 1:
                continue
            old = merged[0]
            x, y, w, h = clean_reading.bbox
            left, top, _, height = merged_field.box
            start = max(x-1, left+3)
            end = x+w-2
            source = (gray[top+3:top+height-2, start:end] < 255)
            labels, stats = _components(source)
            glyphs = [i for i, (gx, gy, gw, gh, area) in enumerate(stats[1:], 1)
                      if gw >= 3 and .28*h <= gh <= .8*h and area >= 8]
            if len(glyphs) != len(clean_reading.text):
                continue
            glyphs.sort(key=lambda i: stats[i, 0])
            clean = np.isin(labels, glyphs)
            bx, by, bw, bh = _bounds(clean)
            if bx+bw >= source.shape[1] or bw < 2*bh*.55:
                continue
            template = clean[by:by+bh, bx:bx+bw]
            sy, sx = max(0, y-2), max(0, start+bx-2)
            endx = min(gray.shape[1], start+bx+bw+3)
            probe = (gray[sy:y+h+1, sx:endx] < 255)
            if probe.shape[0] < bh or probe.shape[1] < bw:
                continue
            scores = cv2.matchTemplate(np.uint8(probe), np.uint8(template), cv2.TM_CCORR)
            ry, rx = np.unravel_index(int(scores.argmax()), scores.shape)
            match = probe[ry:ry+bh, rx:rx+bw]
            if np.count_nonzero(match & template) < .78*np.count_nonzero(template):
                continue
            # Only retire observed source with support from the other impression.
            # The overprint outside that support stays as fixed crossing evidence.
            observed = (gray[sy+ry-1:sy+ry+bh+1, sx+rx-1:sx+rx+bw+1] < 255)
            if observed.shape != (bh+2, bw+2):
                continue
            border = cv2.dilate(np.uint8(np.pad(template, 1)), np.ones((3, 3), np.uint8)) > 0
            other = observed & border
            left0, top0 = start, top+3
            text0 = _native_piece(old, clean_reading.text, clean, left0, top0,
                                  (_bounds(labels == i, left0, top0) for i in glyphs))
            text1 = _native_piece(clean_reading, clean_reading.text, other, sx+rx-1, sy+ry-1)
            if np.any(rules[_window(text0.bbox)] & clean[by:by+bh, bx:bx+bw]):
                continue
            native = np.zeros_like(gray, dtype=bool)
            clean_window = np.s_[top0:top0+clean.shape[0], left0:left0+clean.shape[1]]
            other_window = np.s_[sy+ry-1:sy+ry+bh+1, sx+rx-1:sx+rx+bw+1]
            native[clean_window] = clean
            native[other_window] |= other
            members = ((text0, clean_window, clean), (text1, other_window, other))
            return {old.bbox, clean_reading.bbox}, members, native
    return None


def _stamp(gray, fields, forbidden):
    """Require a source-supported ring and interior marks next to signing cells."""
    left, top, _, _ = fields[0].box
    bottom = max(y+h for _, y, _, h in (f.box for f in fields))
    height = bottom-top
    x0, y0 = max(0, left-3*height), max(0, top-height//2)
    y1 = min(gray.shape[0], bottom+height)
    patch = gray[y0:y1, x0:left]
    if min(patch.shape) < height:
        return None
    low = max(5, int(.53*height))
    high = min(int(1.05*height), min(patch.shape)//2)
    if high <= low:
        return None
    candidates = cv2.HoughCircles(
        cv2.GaussianBlur(patch, (5, 5), 1), cv2.HOUGH_GRADIENT, 1,
        low/2, param1=75, param2=22, minRadius=low, maxRadius=high,
    )
    if candidates is None:
        return None
    yy, xx = np.ogrid[:patch.shape[0], :patch.shape[1]]
    angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
    for cx, cy, radius in candidates[0]:
        if min(cx, cy, patch.shape[1]-cx, patch.shape[0]-cy) < radius+2:
            continue
        radial = np.arange(.91*radius, 1.075*radius, .75)
        xs = np.rint(cx+np.cos(angles[:, None])*radial).astype(int)
        ys = np.rint(cy+np.sin(angles[:, None])*radial).astype(int)
        if (xs.min() < 0 or ys.min() < 0 or xs.max() >= patch.shape[1]
                or ys.max() >= patch.shape[0]):
            continue
        on_ring = (patch[ys, xs] < 192).any(axis=1)
        distance = np.hypot(xx-cx, yy-cy)
        core = distance < radius*.76
        quadrant_density = [
            np.mean(patch[region] < 192) for region in
            (core & (xx < cx) & (yy < cy), core & (xx >= cx) & (yy < cy),
             core & (xx < cx) & (yy >= cy), core & (xx >= cx) & (yy >= cy))
        ]
        if (on_ring.mean() < .86 or min(quadrant_density) < .015
                or not .04 <= np.mean(quadrant_density) <= .45):
            continue
        support = (patch < 255) & ~forbidden[y0:y1, x0:left]
        disk = distance <= radius*1.075
        labels, stats = _components(support)
        # Entire components with observed continuation well outside the ring
        # are fixed. Neither the seal nor a signature may take those pixels.
        outside = np.unique(labels[distance > radius*1.095])
        shared_labels = set(np.intersect1d(labels[disk & support], outside))
        anchors = []
        for label in shared_labels:
            py, px = np.nonzero((labels == label) & disk)
            if stats[label, 4] >= 8 and px.size:
                anchors.append(np.array([px.mean(), py.mean()]))
        # A second observed entry on the opposite side supports an overprint.
        # Keep long, non-rim source components in that band fixed as well. A
        # broken faint pen stroke may never form one binary component.
        for a, b in combinations(anchors, 2):
            delta = b-a
            length = np.linalg.norm(delta)
            if length < 1.55*radius:
                continue
            across = np.abs((xx-a[0])*delta[1] - (yy-a[1])*delta[0])/length
            local_ids = set(np.unique(labels[(across < .52*radius) & (distance < .74*radius)]))
            rim_ids = set(np.unique(labels[distance > .93*radius]))
            shared_labels.update(i for i in local_ids-rim_ids if max(stats[i, 2:4]) >= .19*radius)
        crossing = np.isin(labels, tuple(shared_labels))
        interior = disk & support & ~crossing
        if np.count_nonzero(interior) < .55*np.count_nonzero(disk & support):
            continue
        exclusive = np.zeros_like(gray, dtype=bool)
        shared = np.zeros_like(exclusive)
        exclusive[y0:y1, x0:left] = interior
        shared[y0:y1, x0:left] = crossing
        return exclusive, shared
    return None


def _approval(gray, texts, horizontal, excluded, rule_shape):
    """Separate pen-only components from a ruled approval caption."""
    page_h, page_w = gray.shape
    for heading in texts:
        if heading.text.casefold().strip(" :") != "approved" or heading.confidence < .9:
            continue
        x, y, w, h = heading.bbox
        for caption in texts:
            cx, cy, cw, ch = caption.bbox
            letters = "".join(caption.text.split())
            if not (cx > x+w and h*1.6 < cy-y < 5*h and cw > 4*h
                    and letters.isalpha() and letters.isupper() and caption.confidence >= .9):
                continue
            carriers = [t for t in texts if cx-h <= t.bbox[0] <= cx+h
                        and y-h <= t.bbox[1] < cy-h and t.bbox[2] >= cw*.8
                        and t.confidence < .9]
            if len(carriers) != 1:
                continue
            pen = carriers[0]
            px, py, pw, ph = pen.bbox
            x0, x1 = max(x+w+2, min(px, cx)-4*h), min(page_w, max(px+pw, cx+cw)+h)
            y0, y1 = max(0, min(y, py)-2*h), min(page_h, cy+ch+2*h)
            win = np.s_[y0:y1, x0:x1]
            projection = np.count_nonzero(horizontal[win], axis=1)
            rows = [y0+v for v in _projection_centers(projection >= (x1-x0)*.43)]
            above = [r for r in rows if y < r < cy]
            below = [r for r in rows if cy+ch-3 <= r < cy+ch+h]
            if not above or not below:
                continue
            middle, bottom = max(above), min(below)
            if not h <= bottom-middle <= h*2.6:
                continue
            support = (gray[win] < 255) & ~rule_shape[win] & ~excluded[win]
            labels, stats = _components(support)
            caption_zone = np.zeros_like(support)
            caption_zone[cy-y0:min(cy+ch, bottom)-y0, cx-x0:cx+cw-x0] = True
            # Connected source in the gap can carry both pen and caption ink.
            # Require a component that actually extends outside the text band.
            caption_ids = np.unique(labels[caption_zone & support])
            joined = [i for i in caption_ids if stats[i, 0]+x0 < cx-2
                      or stats[i, 1]+y0 < cy-1 and stats[i, 3] > ch+1]
            if not joined:
                continue
            seed = labels[max(py, y0)-y0:min(py+ph, middle)-y0, px-x0:min(px+pw, x1)-x0]
            ink_ids = [i for i in np.unique(seed) if i and stats[i, 4] >= 4
                       and (stats[i, 2] >= 3 or stats[i, 3] >= 3)]
            if sum(stats[i, 4] for i in ink_ids) < 35:
                continue
            # Preserve the measured pen continuations on both sides of the
            # rules. Their crossing pixel itself stays with the stationary rule.
            pen_ink = np.isin(labels, ink_ids)
            band = max(3, h//3)
            around = np.zeros_like(support)
            for row in (middle, bottom, *[r for r in rows if abs(r-y) <= h]):
                around[max(0, row-y0-band):row-y0+band+1] = True
            reach = np.ones((2*(band+max(2, h//5))+1, 2*max(2, h//4)+1), np.uint8)
            # Walk the observed fragments across the rules, including the
            # continuation below the caption. Keep the whole conflict fixed.
            crossing = set(joined)
            for _ in range(3):
                near = cv2.dilate(np.uint8(pen_ink | np.isin(labels, tuple(crossing))),
                                  reach) > 0
                more = set(np.unique(labels[near & around & support]))
                if more <= crossing:
                    break
                crossing.update(more)
            words, word_ids = _separable_caption_words(caption, labels, caption_zone, joined, x0, y0)
            words = tuple((word, win, ink) for word, ink in words)
            native_ink = np.isin(labels, word_ids) & support
            fixed = np.isin(labels, [*caption_ids, *crossing]) & support & ~native_ink
            moving = pen_ink & ~fixed & ~native_ink
            # A crossing may leave all candidate ink shared. Keep the fixed
            # source in that case as well.
            exclusive = np.zeros_like(gray, dtype=bool)
            shared = np.zeros_like(exclusive)
            printed = np.zeros_like(exclusive)
            exclusive[win], shared[win] = moving, fixed
            printed[win] = native_ink
            return {pen.bbox, caption.bbox}, exclusive, shared, caption, words, printed
    return None


def _separable_caption_words(caption, labels, zone, joined, left, top):
    words = caption.text.split()
    if len(words) != 2 or len(caption.character_boxes) != sum(map(len, words)):
        return (), ()
    _, y, _, h = caption.bbox
    first_right = caption.character_boxes[len(words[0])-1]
    second_left = caption.character_boxes[len(words[0])][0]
    boundary = (first_right[0]+first_right[2]+second_left)//2-left
    empty = ~np.any(zone & (labels > 0), axis=0)
    gaps = [v for v in _projection_centers(empty) if abs(v-boundary) < h*.65]
    if len(gaps) != 1:
        return (), ()
    cut = gaps[0]
    protected = set()
    native = []
    for reading, a, b in zip(words, (0, cut), (cut, labels.shape[1])):
        ids = set(np.unique(labels[:, a:b][zone[:, a:b]])) - {0}
        if not ids or ids.intersection(joined):
            continue
        source = np.isin(labels, tuple(ids))
        _, by, width, height = _bounds(source, left, top)
        if by < y-2 or by+height > y+h+2 or not 3*len(reading) <= width <= h*len(reading):
            continue
        if ids & protected:
            return (), ()
        native.append((_native_piece(caption, reading, source, left, top), source))
        protected.update(ids)
    return tuple(native), tuple(protected)


def resolve_raster_signing(gray, binary, texts, *, line_ink, excluded):
    """Return disjoint ownership, text retirement, and unresolved member boxes."""
    roles = [t for t in texts if t.confidence >= .9 and len(t.text.split()) >= 2
             and t.text.casefold().split()[-1] in {"engineer", "architect"}]
    if len(roles) < 2:
        return None
    foreground = (gray < 255)
    horizontal, vertical = verified_structural_rule_masks(np.uint8(gray < 128)*255)
    if not horizontal.any():
        return None
    # Follow long measured runs in the same ruled network, including rules
    # partly broken in the strong-ink mask by scan antialiasing.
    length = max(9, round(2.5*np.median([t.bbox[3] for t in roles])))
    horizontal |= cv2.morphologyEx(np.uint8(gray < 192)*255, cv2.MORPH_OPEN,
                                    np.ones((1, length), np.uint8))
    fields = [f for t in roles if (f := _field(t, horizontal, vertical)) is not None]
    # Retain the source edge tone of the measured rule with the fixed drawing.
    rule_shape = cv2.dilate(horizontal, np.ones((3, 1), np.uint8)) > 0
    rule_shape |= cv2.dilate(vertical, np.ones((1, 3), np.uint8)) > 0
    for first, second in combinations(sorted(fields, key=lambda f: f.box[1]), 2):
        x, y, w, h = first.box
        lx, ly, lw, _ = second.box
        if abs(x-lx) > 3 or abs(w-lw) > 4 or not h <= ly-y <= 3*h:
            continue
        repeated = _repeated_print(gray, (first, second), texts, rule_shape | excluded)
        if repeated is None:
            continue
        rejected, native, print_ink = repeated
        if np.any(print_ink & (excluded | (line_ink > 0))):
            continue
        break
    else:
        return None

    blocked = rule_shape | (line_ink > 0) | excluded
    other_text = np.zeros_like(foreground)
    for text in texts:
        if text.bbox not in rejected:
            other_text[_window(text.bbox)] = True
    handwriting = []
    fixed_members = []
    shared = np.zeros_like(foreground)
    stamp = _stamp(gray, (first, second), blocked)
    graphics = []
    stamp_edge = None
    if stamp is not None:
        stamp_ink, stamp_crossing = stamp
        stamp_region = _region(stamp_ink, gray, "stamp")
        graphics.append(stamp_region)
        if stamp_crossing.any():
            fixed_members.append(stamp_region.bbox)
        stamp_edge = stamp_region.bbox[0]+stamp_region.bbox[2]
        shared |= stamp_crossing
        blocked |= stamp_ink
    for field in (first, second):
        x, y, w, h = field.box
        # Start with the same rule-subtracted source components as labelled
        # signing fields. Use source layout to exclude neighbouring text rows.
        x0 = x if field is first else max(0, x-h, stamp_edge or 0)
        y0 = max(0, y-(h//4 if field is second else 0))
        win = np.s_[y0:y+h+2, x0:x+w]
        support = (foreground[win] & ~blocked[win] & ~print_ink[win]
                   & ~shared[win] & ~other_text[win])
        labels, stats = _components(support)
        ink_ids = [i for i, (ix, iy, iw, ih, area) in enumerate(stats[1:], 1)
                   if area >= 4 and (iw >= 3 or ih >= 3)]
        selected = np.isin(labels, ink_ids)
        boundary = cv2.dilate(np.uint8(rule_shape[win]), np.ones((3, 3), np.uint8)) > 0
        near_print = cv2.dilate(np.uint8(print_ink[win]), np.ones((3, 3), np.uint8)) > 0
        near_text = cv2.dilate(np.uint8(other_text[win]), np.ones((3, 3), np.uint8)) > 0
        fixed_ids = np.unique(labels[selected & (boundary | near_print | near_text)])
        fixed = np.isin(labels, fixed_ids)
        shared[win] |= fixed
        exclusive = np.zeros_like(foreground)
        exclusive[win] = selected & ~fixed
        if exclusive.any():
            region = _region(exclusive, gray, "signature")
            handwriting.append(region)
            # Nearby shared paint may be separated from the field by the
            # two sides of a one-pixel rule. Unrelated distant paint stays fixed
            # without restricting this member.
            if fixed.any() or np.any(
                shared[win] & (cv2.dilate(np.uint8(selected), np.ones((5, 5), np.uint8)) > 0)
            ):
                fixed_members.append(region.bbox)
    approval = _approval(gray, texts, horizontal, blocked | shared | print_ink, rule_shape)
    caption = None
    if approval is not None:
        retired, exclusive, conflict, caption, words, printed = approval
        rejected |= retired
        shared |= conflict
        native += words
        print_ink |= printed
        if exclusive.any():
            region = _region(exclusive, gray, "signature")
            handwriting.append(region)
            if conflict.any():
                fixed_members.append(region.bbox)
    # Raw gray locates complete printed members. Only prepared foreground can
    # be retired as editable text. Keep a rejected member's entire gray mask
    # on the visible fixed-source layer, including its faint pixels.
    retired_print = np.zeros_like(print_ink)
    printed, unresolved = [], []
    for text, win, ink in native:
        if np.any(ink & (binary[win] >= 128)):
            shared[win] |= ink
            unresolved.append(replace(
                text, approved=False, replacement_safe=False,
                review_note="签署文字来源域未决",
            ))
        else:
            retired_print[win] |= ink
            printed.append(text)
    if shared.any():
        graphics.append(_region(shared, gray, "shared_signing_ink"))
    return (
        rejected, tuple(printed), retired_print, tuple(handwriting), tuple(graphics),
        caption, tuple(fixed_members), tuple(unresolved),
    )


def _region(mask, gray, kind):
    box = _bounds(mask)
    alpha = np.uint8(mask[_window(box)])*255
    region = (SignatureRegion(box, alpha) if kind == "signature" else
              LogoRegion(box, alpha, 1.0, 0, 0, visual_kind=kind))
    return source_ink_region(region, gray)
