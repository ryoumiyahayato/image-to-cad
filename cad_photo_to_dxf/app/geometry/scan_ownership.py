"""Source-ink ownership around OCR observations and protected graphics."""
from __future__ import annotations
from unicodedata import category, east_asian_width

import cv2
import numpy as np

from app.ocr.signature_overlay import detect_signature_regions


def _window(quad, shape, pad):
    low = np.maximum(0, np.floor(quad.min(axis=0)).astype(int) - pad)
    high = np.minimum(shape[::-1], np.ceil(quad.max(axis=0)).astype(int) + pad + 1)
    return np.s_[low[1]:high[1], low[0]:high[0]], quad - low


def _polygon(shape, points):
    region = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(region, np.rint(points).astype(np.int32), 255)
    return region


def _inclined_run(ink, region, endpoints, span):
    """Measure the pen on uncontested cross sections, then follow actual ink."""
    x0, y0, x1, y1 = endpoints
    if abs(y1-y0) > abs(x1-x0):
        return _inclined_run(ink.T, region.T, (y0, x0, y1, x1), span).T
    result = np.zeros_like(ink)
    x = np.arange(ink.shape[1])
    slope = (y1-y0) / (x1-x0)
    predicted = y0 + slope * (x-x0)
    radius = max(4, min(32, round(span / 4)))
    offset = np.arange(-radius, radius+1)[:, None]
    rows = np.rint(predicted).astype(int) + offset
    clipped = rows.clip(0, ink.shape[0]-1)
    samples = (ink[clipped, x] != 0) & (rows == clipped)
    seed = np.argmin(np.where(samples, abs(offset), 2*radius), axis=0) - radius
    valid = samples.any(axis=0) & (abs(seed) <= 2)
    # Find both edges of the contiguous source run containing the seed.
    top = np.max(np.where(~samples & (offset < seed), offset, -radius-1), axis=0) + 1
    bottom = np.min(np.where(~samples & (offset > seed), offset, radius+1), axis=0) - 1
    mid = np.rint(predicted) + (top + bottom) / 2
    measure = valid & (region[clipped[radius], x] == 0) & (top > -radius) & (bottom < radius)
    if measure.sum() < max(5, span / 3):
        return result
    widths = bottom - top + 1
    pen = np.median(widths[measure])
    measure &= abs(widths - pen) <= 1
    if measure.sum() < 4 or np.ptp(x[measure]) < span / 3:
        return result
    slope, intercept = np.polyfit(x[measure], mid[measure], 1)
    fitted = slope * x + intercept
    if np.quantile(abs(mid[measure] - fitted[measure]), 0.9) > 0.8:
        return result
    # Pixel centres fluctuate with raster phase. Keep measured narrow sections;
    # at a merged glyph use only the band supported on the exterior sections.
    measured_band = (offset >= top) & (offset <= bottom) & measure
    margin = np.quantile(abs(rows - fitted)[measured_band], 0.99)
    band = abs(rows - fitted) <= max(0.55, margin + 0.08)
    narrow = (widths <= pen+1) & (abs(mid-fitted) <= 0.8)
    band[:, narrow] = ((offset >= top) & (offset <= bottom))[:, narrow]
    selected = samples & band & valid
    # A collinear but disjoint mark supplies no continuation through white paper.
    occupied = selected.any(axis=0)
    for start, end in np.flatnonzero(np.diff(np.pad(occupied, 1))).reshape(-1, 2):
        if not np.any(measure[start:end]):
            selected[:, start:end] = False
    yy, xx = np.nonzero(selected)
    result[rows[yy, xx], xx] = 255
    return result


def _continuous_rules(ink, region, span, *, crossing_only=False):
    """Directional openings and exterior pen profiles never fill source gaps."""
    radius = max(3, int(np.ceil(span / 2)))
    rules = np.zeros_like(ink)
    for size in ((2*radius+1, 1), (1, 2*radius+1)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, size)
        runs = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel,
                                borderType=cv2.BORDER_CONSTANT, borderValue=0)
        if crossing_only and runs.any():
            n, labels = cv2.connectedComponents(runs)
            external = np.zeros(n, bool)
            external[labels[region == 0]] = True
            external[0] = False
            runs = np.uint8(external[labels]) * 255
        rules |= runs
    proposals = cv2.HoughLinesP(ink, 1, np.pi / 360, threshold=radius,
                                minLineLength=radius * 2, maxLineGap=2)
    if proposals is not None:
        for x0, y0, x1, y1 in proposals[:, 0]:
            # An axis-aligned proposal can also be a rule whose raster edge
            # steps at a glyph crossing. Use its measured exterior profile.
            rules |= _inclined_run(ink, region, (x0, y0, x1, y1), span)
    return rules


def _enclosures(ink):
    """Find a ring/frame containing separate ink; ordinary glyph counters are empty."""
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return
    for i, (_, _, child, parent) in enumerate(hierarchy[0]):
        if parent != -1 or child < 0:
            continue
        contour = contours[i]
        area = cv2.contourArea(contour)
        while child >= 0:
            hole = contours[child]
            if hierarchy[0, child, 2] >= 0 and cv2.contourArea(hole) > 0.35 * area:
                yield contour, hole
                break
            child = hierarchy[0, child, 0]


def _attached_frames(ink, is_frame):
    """Keep the perimeter when an internal character touches its circular/box frame."""
    borders = np.zeros_like(ink)
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 9 or not 0.6 < w / h < 1.6 or not is_frame(contour):
            continue
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.025*perimeter, True)
        rectangle = len(polygon) == 4 and cv2.isContourConvex(polygon) and area > 0.85*w*h
        if not rectangle and 4*np.pi*area < 0.85 * perimeter**2:
            continue
        filled = np.zeros((h+2, w+2), np.uint8)
        cv2.drawContours(filled, [contour - np.int32([x-1, y-1])], 0, 255, -1)
        depth = cv2.distanceTransform(filled, cv2.DIST_L2, 5)[1:-1, 1:-1]
        local = ink[y:y+h, x:x+w]
        interior = depth > 0.22 * min(w, h)
        if not np.any(local[interior]) or not np.any(local[interior] == 0):
            continue
        holes, _ = cv2.findContours(np.uint8((local == 0) & (depth > 0)), cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_NONE)
        if holes:
            edge = np.concatenate(holes)[:, 0]
            thickness = np.quantile(depth[edge[:, 1], edge[:, 0]], 0.30)
            if thickness < 0.22 * min(w, h):
                borders[y:y+h, x:x+w] |= np.where((depth > 0) & (depth <= thickness),
                                                  local, 0).astype(np.uint8)
    return borders


def glyph_ink(binary, lines):
    """Claim compact source components after separating rules within each neighbourhood."""
    result = np.zeros_like(binary)
    for line in lines:
        quad = np.asarray(line.quad, dtype=float)
        height = max(2, np.linalg.norm(quad[3] - quad[0]))
        window, local_quad = _window(quad, binary.shape, int(np.ceil(2 * height)))
        ink = cv2.bitwise_not(binary[window])
        if not ink.size:
            continue
        region = _polygon(ink.shape, local_quad)
        advance = sum(1 if east_asian_width(c) in ("W", "F") else 0.55 for c in line.text)
        em = np.linalg.norm(quad[1] - quad[0]) / max(1, advance)

        def is_frame(contour):
            # A full-width glyph may itself contain a rectangular enclosure.
            # Respect the line's character advance and the actual footprint.
            x, y, w, h = cv2.boundingRect(contour)
            single_narrow = len(line.text) == 1 and east_asian_width(line.text) not in ("W", "F")
            return (single_narrow or max(w, h) > 1.2*em or h > height
                    or not np.all(region[contour[:, 0, 1], contour[:, 0, 0]]))

        rules = _continuous_rules(ink, region, 1.6 * height) | _attached_frames(ink, is_frame)
        # Enclosing contours can be shorter than the line-opening kernel.
        for outer, hole in _enclosures(ink):
            if not is_frame(outer):
                continue
            frame = np.zeros_like(ink)
            cv2.drawContours(frame, [outer], 0, 255, -1)
            cv2.drawContours(frame, [hole], 0, 0, -1)
            cv2.drawContours(frame, [hole], 0, 255, 1)
            rules |= frame & ink
        remaining = cv2.subtract(ink, rules)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(remaining)
        inside = np.bincount(labels[region != 0], minlength=n)
        # Include antialiasing and clipped glyph tips just outside the OCR box.
        # An adjacent component merely grazing the box has no such ownership.
        claim = inside >= 0.65 * stats[:, cv2.CC_STAT_AREA]
        pad = max(1, int(np.ceil(0.2 * height)))
        nearby = cv2.dilate(region, np.ones((2*pad+1, 2*pad+1), np.uint8))
        claim[np.unique(labels[nearby == 0])] = False
        # A short rule can fit entirely inside a loose OCR box. Test its normal
        # position against the actual glyph bodies before giving it to the text.
        axis = quad[1] - quad[0]
        axis /= max(1, np.linalg.norm(axis))
        normal = np.array([-axis[1], axis[0]])
        coords = stats[:, :2]
        sizes = stats[:, 2:4]
        middle = (coords + 0.5*sizes) @ normal
        extent = sizes @ np.abs(normal)
        bodies = claim & (extent >= 0.3*height)
        bodies[0] = False
        if bodies.any() and not any(category(c) in ("Pc", "Pd") for c in line.text):
            top = np.min(middle[bodies] - extent[bodies]/2)
            bottom = np.max(middle[bodies] + extent[bodies]/2)
            flat = sizes @ np.abs(axis) >= 3*extent
            clear = (middle + extent/2 < top-1) | (middle - extent/2 > bottom+1)
            claim[flat & clear] = False
        claim[0] = False
        result[window] |= np.uint8(claim[labels]) * 255
    return result


def _outside_rules(binary, footprint):
    """Reserve ink continuing into a graphic from its surroundings."""
    result = np.zeros_like(binary)
    contours, _ = cv2.findContours(footprint, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        short = min(w, h)
        box = np.array([[x, y], [x+w-1, y], [x+w-1, y+h-1], [x, y+h-1]])
        window, quad = _window(box, binary.shape, max(8, short))
        ink = cv2.bitwise_not(binary[window])
        # Demand continuation beyond the bounding box, not just into its white holes.
        outside = cv2.dilate(_polygon(ink.shape, quad), np.ones((7, 7), np.uint8))
        if np.any(ink[outside == 0]):
            rules = _continuous_rules(ink, outside, max(12, short * 0.65), crossing_only=True)
            result[window] |= rules & footprint[window] & _polygon(ink.shape, quad)
    return result


def emblem_ink(image, binary, observed_text):
    """Recognize filled emblem shapes or adjacent fields of different pigment.

    Unframed marks compete with OCR first. Printed outlines, counters and
    isolated stems are insufficient evidence of an emblem.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    color = cv2.inRange(hsv, (0, 70, 35), (179, 255, 255))
    mask = np.zeros_like(color)
    contours, _ = cv2.findContours(color, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 8 or max(w, h) > 3 * min(w, h):
            continue
        local = np.zeros((h, w), np.uint8)
        cv2.drawContours(local, [contour - np.int32([x, y])], 0, 255, -1)
        pigment = color[y:y+h, x:x+w] & local
        if np.any(pigment & observed_text[y:y+h, x:x+w]):
            continue
        # Hull occupancy distinguishes solid artwork from skeletal glyphs.
        hull = cv2.convexHull(contour)
        solidity = cv2.countNonZero(pigment) / max(1, cv2.contourArea(hull))
        hues = hsv[y:y+h, x:x+w, 0][pigment != 0].astype(float) * (np.pi / 90)
        multiple_pigments = np.hypot(np.mean(np.cos(hues)), np.mean(np.sin(hues))) < 0.8
        vertices = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        if (solidity > 0.9 and len(vertices) in (3, 4)) or (solidity > 0.55 and multiple_pigments):
            mask[y:y+h, x:x+w] |= pigment
    return cv2.subtract(mask, _outside_rules(binary, mask)) if mask.any() else mask


def protected_ink(image, binary, manual):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    color = cv2.inRange(hsv, (0, 70, 35), (179, 255, 255))
    graphic = np.zeros_like(binary)
    # An enclosing coloured border with separate inner lettering is a stamp.
    # Fill only its actual pigment, leaving intersecting black rules available.
    for outer, _ in _enclosures(color):
        x, y, w, h = cv2.boundingRect(outer)
        local = np.zeros((h, w), np.uint8)
        cv2.drawContours(local, [outer - np.int32([x, y])], 0, 255, -1)
        # An ordinary square printed glyph can also have ink inside a counter.
        # For a rectangular seal require a row of distinct inner glyphs.
        area = cv2.contourArea(outer)
        if 4*np.pi*area < 0.84 * cv2.arcLength(outer, True)**2:
            _, _, pieces, _ = cv2.connectedComponentsWithStats(local & color[y:y+h, x:x+w])
            inner = [p for p in pieces[1:] if 0.15*h < p[3] < 0.8*h and p[4] >= 4]
            if not any(a[0]+a[2] <= b[0] and abs(a[1]-b[1]) < 0.3*h
                       for a in inner for b in inner):
                continue
        graphic[y:y+h, x:x+w] |= local & color[y:y+h, x:x+w]
    for region in detect_signature_regions(binary):
        x, y, w, h = region.bbox
        graphic[y:y+h, x:x+w] |= region.mask
    graphic[manual > 0] = 255
    return cv2.subtract(graphic, _outside_rules(binary, graphic)) if graphic.any() else graphic
