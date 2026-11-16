"""Recover compact round bodies and their observed geometric contact sites."""

from math import ceil

import cv2
import numpy as np


_NEIGHBORS = np.ones((3, 3), np.uint8)
_RAY_COUNT = 96
_RAY_STEP = 0.25
# Allow native-pixel sampling and a small antialiasing margin.
_MAX_P95_ERROR = 0.85
_MAX_ERROR = 1.35


def _cell_boundary(mask, left, top):
    """Return one exact pixel-cell boundary, or decline an ambiguous ring."""
    edges = set()
    for y, x in np.argwhere(mask):
        x, y = int(x) + left, int(y) + top
        corners = ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1))
        for start, end in zip(corners, (*corners[1:], corners[0])):
            if (end, start) in edges:
                edges.remove((end, start))
            else:
                edges.add((start, end))
    following = dict(edges)
    if not following or len(following) != len(edges):
        return ()
    start = point = min(following)
    ring = []
    while point in following:
        ring.append(point)
        point = following.pop(point)
    if point != start or following:
        return ()
    return tuple(
        point for i, point in enumerate(ring)
        if (ring[i - 1][0] != ring[(i + 1) % len(ring)][0]
            and ring[i - 1][1] != ring[(i + 1) % len(ring)][1])
    )


def _fit_boundary(gray, x, y, seed_radius, directions):
    steps = np.arange(0, max(seed_radius * 1.85, seed_radius + 6) + _RAY_STEP, _RAY_STEP)
    samples = directions[:, None, :] * steps[None, :, None] + (x, y)
    gray_values = cv2.remap(
        gray, samples[:, :, 0].astype(np.float32), samples[:, :, 1].astype(np.float32),
        cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255,
    )
    exits = gray_values >= 128
    measured = exits.any(axis=1)
    if np.count_nonzero(measured) < _RAY_COUNT * 0.75:
        return None
    radii = steps[np.argmax(exits, axis=1)] - _RAY_STEP / 2
    middle = np.median(radii[measured])
    # Rays that travel along a lead do not measure the boundary of the body.
    used = measured & (np.abs(radii - middle) <= max(1.2, middle * 0.18))
    quadrants = np.count_nonzero(used.reshape(4, -1), axis=1)
    if np.count_nonzero(used) < _RAY_COUNT * 0.75 or min(quadrants) < _RAY_COUNT / 8:
        return None
    edge = directions[used] * radii[used, None]
    matrix = np.column_stack((2 * edge, np.ones(len(edge))))
    dx, dy, intercept = np.linalg.lstsq(matrix, np.sum(edge * edge, axis=1), rcond=None)[0]
    offset = np.array((dx, dy))
    radius_squared = intercept + offset @ offset
    if radius_squared <= 0 or np.linalg.norm(offset) > 1.5:
        return None
    radius = float(np.sqrt(radius_squared))
    error = np.abs(np.linalg.norm(edge - offset, axis=1) - radius)
    p95, maximum = float(np.percentile(error, 95)), float(error.max())
    if p95 > _MAX_P95_ERROR or maximum > _MAX_ERROR:
        return None
    return (float(x + dx), float(y + dy)), radius, {
        "sampled_rays": _RAY_COUNT, "boundary_rays": int(len(edge)),
        "quadrant_rays": quadrants.tolist(), "sample_step_px": _RAY_STEP,
        "p95_radial_error_px": p95, "max_radial_error_px": maximum,
        "p95_limit_px": _MAX_P95_ERROR, "max_limit_px": _MAX_ERROR,
    }


def _contact_sites(source, dark, body, distance, radius, left, top):
    """Witness each body-to-exterior path with connected source ink."""
    reach = radius + max(3, radius * 0.5)
    band = source & ~body & (distance <= reach)
    adjacent = cv2.dilate(np.uint8(body), _NEIGHBORS) > 0
    count, labels = cv2.connectedComponents(np.uint8(band), connectivity=8)
    contacts = []
    leads = np.zeros_like(body)
    for label in range(1, count):
        ink = labels == label
        inner = np.argwhere(ink & adjacent)
        outer = np.argwhere(ink & (distance >= reach - 1))
        if not len(inner) or not len(outer) or not np.any(ink & dark):
            continue
        # A narrow lead may occupy part of the annulus; a broad surrounding
        # mass is insufficient evidence for an individual access position.
        pixels = int(np.count_nonzero(ink))
        if pixels > 0.3 * np.pi * (reach ** 2 - radius ** 2):
            continue
        iy, ix = inner[np.argmin(np.linalg.norm(inner - inner.mean(axis=0), axis=1))]
        oy, ox = outer[np.argmin(np.linalg.norm(outer - outer.mean(axis=0), axis=1))]
        contacts.append({
            "entry_px": [left + int(ix), top + int(iy)],
            "outer_witness_px": [left + int(ox), top + int(oy)],
            "connected_source_pixels": pixels,
        })
        leads |= ink
    return contacts, leads


def _fill_paths(mask, left, top):
    boundary = _cell_boundary(mask, left, top)
    if boundary:
        return (boundary,)
    # A diagonal contact can give the union a shared corner. Each fallback
    # loop fills one measured row run with no extra ink at that corner.
    paths = []
    for y, row in enumerate(mask, start=top):
        edges = np.flatnonzero(np.diff(np.r_[False, row, False]))
        for start, stop in edges.reshape(-1, 2):
            x0, x1 = left + int(start), left + int(stop)
            paths.append(((x0, y), (x1, y), (x1, y+1), (x0, y+1)))
    return tuple(paths)


def retain_filled_source_marks(gray, binary, contours, *, dpi, protected):
    """Return source-only filled objects and residual pixels outside their bodies."""
    dark = gray < 128
    distance = cv2.distanceTransform(np.uint8(dark), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    minimum, maximum = max(3.0, 0.95 * dpi / 25.4), 3.6 * dpi / 25.4
    peaks = (
        (distance >= minimum) & (distance <= maximum) & ~protected
        & (distance == cv2.dilate(distance, _NEIGHBORS))
    )
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(peaks), connectivity=8)
    angles = np.linspace(0, 2 * np.pi, _RAY_COUNT, endpoint=False)
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    records = []
    height, width = gray.shape
    owned = np.zeros_like(dark)
    for i, (left, top, w, h, _) in enumerate(stats[1:], start=1):
        local = np.where(labels[top:top+h, left:left+w] == i, distance[top:top+h, left:left+w], 0)
        sy, sx = np.unravel_index(int(local.argmax()), local.shape)
        x, y = int(left + sx), int(top + sy)
        seed_radius = float(distance[y, x])
        padding = ceil(max(seed_radius * 1.85, seed_radius + 6)) + 3
        a, b, c, d = x - padding, y - padding, x + padding + 1, y + padding + 1
        if a < 0 or b < 0 or c > width or d > height or owned[y, x]:
            continue
        region = np.s_[b:d, a:c]
        fitted = _fit_boundary(gray[region], x-a, y-b, seed_radius, directions)
        if fitted is None:
            continue
        (cx, cy), radius, metrics = fitted
        if not minimum <= radius <= maximum + 1:
            continue
        yy, xx = np.mgrid[:d-b, :c-a]
        radial = np.hypot(xx - cx, yy - cy)
        if np.any((radial <= radius - 1.0) & ~dark[region]):
            continue
        source = binary[region] < 128
        _, components = cv2.connectedComponents(
            np.uint8(source & (radial <= radius + 0.6)), connectivity=4
        )
        body_id = components[y-b, x-a]
        if body_id == 0:
            continue
        body = components == body_id
        if np.any(body & (protected[region] | owned[region])):
            continue
        contacts, leads = _contact_sites(
            source & ~protected[region] & ~owned[region], dark[region],
            body, radial, radius, a, b,
        )
        boundary = _cell_boundary(body, a, b)
        if not contacts or len(boundary) < 4:
            continue
        footprint = body | leads
        owned[region] |= footprint
        records.append({
            "center_px": [a + cx, b + cy], "radius_px": radius, "fit": metrics,
            "boundary_px": boundary, "source_pixels": int(np.count_nonzero(body)),
            "fill_paths_px": _fill_paths(footprint, a, b),
            "lead_source_pixels": int(np.count_nonzero(leads)),
            "contact_sites": contacts, "electrical_connectivity": "UNRESOLVED",
        })
    if not records:
        return contours, ()
    return np.where(owned, 255, contours).astype(np.uint8), tuple(records)
