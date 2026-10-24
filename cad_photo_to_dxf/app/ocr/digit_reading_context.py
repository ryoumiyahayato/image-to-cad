"""Bounded rule-row evidence for upright single-digit recognition input."""

import cv2
import numpy as np


def bounded_upright_context(image, target, candidates, directions):
    if image is None or target.quad is None or target.reviewed:
        return None
    x, y, w, h = target.bbox
    height, width = image.shape[:2]
    if min(x, y) <= 2 or x + w >= width - 2 or y + h >= height - 2:
        return None
    left, right = max(0, x - 24 * h), min(width, x + w + 24 * h)
    top, bottom = max(0, y - 4 * h), min(height, y + h + 4 * h)
    gray = image[top:bottom, left:right]
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    rules = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, 4 * h), 1)),
    )
    # A continuous observed rule must cross the full target width.
    rows = np.flatnonzero(np.all(rules[:, x - left : x - left + w] > 0, axis=1)) + top
    above, below = rows[rows < y - 1], rows[rows > y + h + 1]
    if not len(above) or not len(below):
        return None
    upper, lower = int(above[-1]), int(below[0])
    if lower - upper > 4 * h:
        return None
    spans = []
    for row in (upper, lower):
        values = rules[row - top] > 0
        a, b = x - left, x - left + w
        while a > 0 and values[a - 1]:
            a -= 1
        while b < len(values) and values[b]:
            b += 1
        spans.append((left + a, left + b))
    a, b = max(v[0] for v in spans), min(v[1] for v in spans)
    # A clipped rule does not establish a finite annotation row.
    if a <= left or b >= right or b - a > 32 * h:
        return None
    anchors = []
    for candidate in candidates:
        if (
            candidate is target
            or len("".join(candidate.text.split())) < 2
            or candidate.quad is None
        ):
            continue
        cx, cy, cw, ch = candidate.bbox
        if not (a < cx and cx + cw < b and upper < cy and cy + ch < lower):
            continue
        if cx < x + w and cx + cw > x and cy < y + h and cy + ch > y:
            return None
        # Every same-row multi-character detection must have a trusted actual
        # upright decision and horizontal long axis. Never vote by page majority.
        direction = directions.get(candidate.quad)
        if (
            cw < 1.2 * ch
            or abs(candidate.rotation_deg) > 10
            or direction is None
            or str(direction[0]) != "0"
            or not np.isfinite(float(direction[1]))
            or float(direction[1]) < 0.95
        ):
            return None
        if any(
            cx < ax + aw and cx + cw > ax and cy < ay + ah and cy + ch > ay
            for other in anchors
            for ax, ay, aw, ah in (other.bbox,)
        ):
            return None
        anchors.append(candidate)
    if not 2 <= len(anchors) <= 32:
        return None
    return {
        "direction": 0,
        "bounded_row": [a, upper, b, lower],
        "anchors": [
            {
                "text": c.text,
                "bbox": list(c.bbox),
                "direction": list(directions[c.quad]),
            }
            for c in anchors
        ],
    }
