"""General finite centerline and basic-shape extraction for scanned drawings."""
from __future__ import annotations

from math import degrees

import cv2
import numpy as np

from app.core.cancellation import checkpoint
from app.geometry.line_detect import LineDetectionParams, detect_lines


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
    pixels = set(map(tuple, np.argwhere(skeleton > 0).tolist()))
    neighbours = {}
    for y, x in pixels:
        adjacent = []
        for dy, dx in ((-1,0), (0,1), (1,0), (0,-1), (-1,-1), (-1,1), (1,1), (1,-1)):
            p = y+dy, x+dx
            if p not in pixels:
                continue
            # A diagonal next to an existing cardinal link is a raster corner,
            # not a third geometric arm.
            if dy and dx and ((y+dy, x) in pixels or (y, x+dx) in pixels):
                continue
            adjacent.append(p)
        neighbours[y, x] = adjacent
    visited = set()
    paths = []
    nodes = sorted(p for p in pixels if len(neighbours[p]) != 2)
    for start in nodes + sorted(pixels):
        for following in neighbours[start]:
            edge = tuple(sorted((start, following)))
            if edge in visited:
                continue
            points = [start]
            previous, current = start, following
            visited.add(edge)
            while True:
                points.append(current)
                if current == start or len(neighbours[current]) != 2:
                    break
                nxt = next(p for p in neighbours[current] if p != previous)
                edge = tuple(sorted((current, nxt)))
                if edge in visited:
                    break
                visited.add(edge)
                previous, current = current, nxt
            paths.append(np.asarray([(x,y) for y,x in points], dtype=np.float64))
    return paths


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

    Short or unresolved ink is left unclaimed, so the caller can retain it as
    transparent source imagery instead of deleting it or inventing a line.
    """
    ink = np.uint8(binary < 128)
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    skeleton = thin_ink(ink, cancellation_token)
    records = []
    coverage = np.zeros(ink.shape, dtype=np.uint8)
    warnings = []
    if np.count_nonzero(skeleton) > 500000:
        # Bound graph memory on very dense sheets. The preserved detector uses
        # Hough/LSD proposals and distance-transform centers; unresolved ink is
        # retained by the caller rather than producing an unbounded path graph.
        proposals = detect_lines(binary, LineDetectionParams(max_line_gap=0, min_center_width=2.0),
                                 cancellation_token=cancellation_token)
        for item in proposals:
            points = np.asarray([[item.x1,item.y1],[item.x2,item.y2]])
            records.append({"type":"LINE", "points":points.tolist(), "stroke_width":item.width})
            cv2.polylines(coverage,[np.rint(points).astype(np.int32)],False,255,max(1,round(item.width)))
        warnings.append("密集图纸达到中心线图上限，使用Hough/LSD有限直线；其余墨迹保留为图像。")
        return records, coverage, warnings
    for index, points in enumerate(_paths(skeleton)):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        if len(points) < 2:
            continue
        length = np.linalg.norm(np.diff(points,axis=0),axis=1).sum()
        if length < 8:
            continue
        coords = np.rint(points).astype(np.int32)
        width = float(max(1.0, 2*np.median(distance[coords[:,1],coords[:,0]])-1))
        # Filled marks and broad irregular graphics remain raster resources.
        if width > 30 or length < max(8, width*3):
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
