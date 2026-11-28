"""General finite centerline and basic-shape extraction for scanned drawings."""
from __future__ import annotations

from math import degrees

import cv2
import numpy as np

from app.core.cancellation import checkpoint


def thin_ink(mask, cancellation_token=None):
    """Zhang-Suen thinning; no closing or interpolation across source white gaps."""
    ink = np.pad(np.asarray(mask > 0, np.uint8), 1)
    for iteration in range(512):
        checkpoint(cancellation_token)
        changed = False
        for phase in (0, 1):
            p = ink[1:-1, 1:-1]
            n = [ink[:-2, 1:-1], ink[:-2, 2:], ink[1:-1, 2:], ink[2:, 2:],
                 ink[2:, 1:-1], ink[2:, :-2], ink[1:-1, :-2], ink[:-2, :-2]]
            count = sum(n)
            transitions = sum((n[i] == 0) & (n[(i+1) % 8] == 1) for i in range(8))
            if phase == 0:
                gate = (n[0]*n[2]*n[4] == 0) & (n[2]*n[4]*n[6] == 0)
            else:
                gate = (n[0]*n[2]*n[6] == 0) & (n[0]*n[4]*n[6] == 0)
            remove = (p == 1) & (count >= 2) & (count <= 6) & (transitions == 1) & gate
            if remove.any():
                p[remove] = 0
                changed = True
        if not changed:
            break
    return ink[1:-1, 1:-1]


def _paths(skeleton):
    """Stream source paths and endpoint degrees, including short junction edges.

    Two byte maps bound graph storage by page size even on dense pages.
    """
    # Opposite directions are four slots apart.
    directions = ((0, 1), (1, 1), (1, 0), (1, -1),
                  (0, -1), (-1, -1), (-1, 0), (-1, 1))
    ink = np.pad(skeleton, 1)
    h, w = skeleton.shape
    links = np.zeros_like(skeleton)
    degree = np.zeros_like(skeleton)
    for i, (dy, dx) in enumerate(directions):
        adjacent = skeleton & ink[1+dy:1+dy+h, 1+dx:1+dx+w]
        if dx and dy:
            adjacent &= 1 - (ink[1+dy:1+dy+h, 1:1+w] | ink[1:1+h, 1+dx:1+dx+w])
        links |= adjacent << i
        degree += adjacent

    def walk(y, x):
        start_degree = int(degree[y, x])
        points = [(x, y)]
        while links[y, x]:
            edges = int(links[y, x])
            i = (edges & -edges).bit_length() - 1
            dy, dx = directions[i]
            links[y, x] ^= 1 << i
            y, x = y + dy, x + dx
            links[y, x] ^= 1 << ((i+4) % 8)
            points.append((x, y))
            if degree[y, x] != 2:
                break
        return np.asarray(points, dtype=float), (start_degree, int(degree[y, x]))

    for junctions in (True, False):
        starts = (links > 0) & (degree != 2) if junctions else links > 0
        for y, x in zip(*np.nonzero(starts)):
            while links[y, x]:
                yield walk(int(y), int(x))


def _circle(points, closed, width):
    if len(points) < 12:
        return None
    origin = points.mean(axis=0)
    centered = points-origin
    a = np.column_stack((2*centered[:,0], 2*centered[:,1], np.ones(len(points))))
    solution, _, rank, _ = np.linalg.lstsq(a, (centered**2).sum(axis=1), rcond=None)
    if rank < 3:
        return None
    center = solution[:2]+origin
    radius = float(np.sqrt(max(0, solution[2]+(solution[:2]**2).sum())))
    residual = np.abs(np.linalg.norm(points-center, axis=1)-radius)
    if radius < 4 or np.max(residual) > max(0.85, min(1.5, width*0.25)):
        return None
    angles = np.unwrap(np.arctan2(-(points[:,1]-center[1]), points[:,0]-center[0]))
    span = degrees(float(angles[-1]-angles[0]))
    if closed:
        if abs(span) < 330:
            return None
        return {"type":"CIRCLE", "center":center.tolist(), "radius":radius}
    if abs(span) < 25 or abs(span) > 350:
        return None
    direction = np.sign(span)
    if np.count_nonzero(np.diff(angles)*direction < -0.03) > len(points)*0.03:
        return None
    start, end = (angles[0],angles[-1]) if span > 0 else (angles[-1],angles[0])
    return {"type":"ARC", "center":center.tolist(), "radius":radius,
            "start_angle":degrees(float(start)) % 360, "end_angle":degrees(float(end)) % 360}


def _line(points):
    if len(points) < 2:
        return None
    center = points.mean(axis=0)
    _, _, directions = np.linalg.svd(points-center, full_matrices=False)
    axis = directions[0]
    normal = np.asarray([-axis[1], axis[0]])
    if np.max(np.abs((points-center) @ normal)) > 0.8:
        return None
    extent = (points-center) @ axis
    return [list(center+axis*extent.min()), list(center+axis*extent.max())]


def extract_scan_geometry(binary, *, cancellation_token=None):
    """Return editable finite geometry plus a source-pixel coverage mask.

    Coverage describes fitted source paths only. Delivery checks rasterize the DXF.
    """
    ink = np.uint8(binary < 128)
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    skeleton = thin_ink(ink, cancellation_token)
    records = []
    coverage = np.zeros(ink.shape, dtype=np.uint8)
    warnings = []
    for index, (points, degrees_at_ends) in enumerate(_paths(skeleton)):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        length = np.linalg.norm(np.diff(points, axis=0), axis=1).sum()
        coords = points.astype(np.int32)
        width = float(max(1.0, 2*np.median(distance[coords[:,1],coords[:,0]])-1))
        attached = max(degrees_at_ends) > 2
        # A link at a junction has topological support even below one pen width.
        # An isolated mark needs an elongated trace to distinguish it from dust.
        if width > 30 or (not attached and length < 1.5 * width):
            continue
        closed = bool(np.array_equal(points[0],points[-1]))
        shape = _circle(points, closed, width)
        if shape is None and not closed:
            line = _line(points)
            if line is not None:
                shape = {"type":"LINE", "points":line}
        if shape is None:
            simplified = cv2.approxPolyDP(points.astype(np.float32), 0.65, closed).reshape(-1,2)
            if len(simplified) < 2:
                continue
            shape = {"type":"LWPOLYLINE", "points":simplified.tolist(), "closed":closed}
        shape["stroke_width"] = width
        records.append(shape)
        cv2.polylines(coverage,[coords],closed,255,max(1,int(np.ceil(width+2))))
    return records, coverage, warnings
