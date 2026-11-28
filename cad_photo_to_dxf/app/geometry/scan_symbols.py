"""Associate editable character labels with observed engineering symbol frames.

This operator only returns associations. It never removes geometry, changes OCR
content, or includes a neighbouring leader in the selectable symbol itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import cv2
import numpy as np

from app.core.cancellation import checkpoint


@dataclass(frozen=True)
class _Frame:
    kind: str
    indices: tuple[int, ...]
    center: np.ndarray
    axes: np.ndarray
    half: np.ndarray
    pen: float

    def contains(self, points, margin=0.0):
        local = (np.asarray(points) - self.center) @ self.axes.T
        if self.kind == "circle":
            return np.linalg.norm(local, axis=-1) <= self.half[0] + margin
        return np.all(np.abs(local) <= self.half + margin, axis=-1)

    def on_border(self, points, tolerance):
        local = (np.asarray(points) - self.center) @ self.axes.T
        if self.kind == "circle":
            return np.abs(np.linalg.norm(local, axis=-1) - self.half[0]) <= tolerance
        return (np.all(np.abs(local) <= self.half + tolerance, axis=-1)
                & np.any(np.abs(np.abs(local) - self.half) <= tolerance, axis=-1))


def _points(record):
    kind = record.get("type")
    if kind in {"LINE", "LWPOLYLINE"}:
        points = np.asarray(record.get("points", ()), dtype=float)
    elif kind in {"CIRCLE", "ARC"}:
        center = np.asarray(record.get("center", ()), dtype=float)
        radius = float(record.get("radius", 0))
        if center.shape != (2,) or radius <= 0:
            return np.empty((0, 2))
        start = 0 if kind == "CIRCLE" else float(record["start_angle"])
        span = 360 if kind == "CIRCLE" else (float(record["end_angle"]) - start) % 360
        angles = np.deg2rad(np.linspace(start, start + span, max(8, int(span/10) + 1)))
        points = center + radius * np.column_stack((np.cos(angles), -np.sin(angles)))
    else:
        return np.empty((0, 2))
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        return np.empty((0, 2))
    if record.get("closed") and len(points) > 2 and not np.allclose(points[0], points[-1]):
        points = np.vstack((points, points[0]))
    return points


def _polygon_frame(index, record, points):
    if record.get("type") != "LWPOLYLINE" or len(points) < 4:
        return None
    if not record.get("closed") and not np.allclose(points[0], points[-1]):
        return None
    pen = max(1.0, float(record.get("stroke_width", 1)))
    corners = cv2.approxPolyDP(points.astype(np.float32), max(1.0, pen*0.65), True).reshape(-1, 2)
    if len(corners) != 4 or not cv2.isContourConvex(corners):
        return None
    edges = np.roll(corners, -1, axis=0) - corners
    lengths = np.linalg.norm(edges, axis=1)
    if min(lengths) <= 2*pen:
        return None
    axis = edges[np.argmax(lengths)] / max(lengths)
    axes = np.array([axis, [-axis[1], axis[0]]])
    local = corners @ axes.T
    low, high = local.min(axis=0), local.max(axis=0)
    tolerance = max(1.0, pen*0.6)
    if np.any(np.min(np.minimum(abs(local-low), abs(local-high)), axis=1) > tolerance):
        return None
    # Every side must follow one box edge; a concave or sloping quadrilateral
    # must not acquire rectangular containment just from its bounding box.
    vectors = edges @ axes.T
    if np.any(np.min(abs(vectors), axis=1) > tolerance):
        return None
    return _Frame("rectangle", (index,), ((low+high)/2) @ axes,
                  axes, (high-low)/2, pen)


def _circle_frames(geometry):
    arcs = []
    for index, record in enumerate(geometry):
        if record.get("type") not in {"CIRCLE", "ARC"}:
            continue
        center = np.asarray(record.get("center", ()), dtype=float)
        radius = float(record.get("radius", 0))
        pen = max(1.0, float(record.get("stroke_width", 1)))
        if center.shape != (2,) or not np.isfinite(center).all() or not np.isfinite(radius) or radius <= pen:
            continue
        if record["type"] == "CIRCLE":
            yield _Frame("circle", (index,), center, np.eye(2), np.repeat(radius, 2), pen)
        else:
            arcs.append((index, center, radius, pen))
    used = set()
    for index, center, radius, pen in arcs:
        if index in used:
            continue
        tolerance = max(1.0, pen*0.5)
        members = [item for item in arcs if item[0] not in used
                   and np.linalg.norm(item[1]-center) <= tolerance
                   and abs(item[2]-radius) <= tolerance]
        if len(members) < 2:
            continue
        intervals = []
        for member, _, _, _ in members:
            record = geometry[member]
            start = float(record["start_angle"]) % 360
            span = (float(record["end_angle"]) - start) % 360
            end = start + span
            intervals.append((start, min(360, end)))
            if end > 360:
                intervals.append((0, end-360))
        end = 0.0
        gap = 0.0
        for start, stop in sorted(intervals):
            gap += max(0, start-end)
            end = max(end, stop)
        gap += 360-end
        if np.deg2rad(gap)*radius <= 2*tolerance:
            indices = tuple(item[0] for item in members)
            used.update(indices)
            yield _Frame("circle", indices, center, np.eye(2), np.repeat(radius, 2), pen)


def _line_frames(geometry, paths, quad, *, line_search=None):
    """Find a compact four-edge enclosure; long table rules cannot be its sides."""
    axis = quad[1] - quad[0]
    extent = np.linalg.norm(axis)
    if extent <= 0:
        return
    axis /= extent
    axes = np.array([axis, [-axis[1], axis[0]]])
    local_text = quad @ axes.T
    low, high = local_text.min(axis=0), local_text.max(axis=0)
    height = high[1]-low[1]
    if height <= 0:
        return
    middle = (low+high)/2
    candidates = range(len(geometry))
    if line_search is not None:
        indices, lows, highs, max_tolerance = line_search
        # A possible side spans the label in one direction and its midpoint
        # lies within four label heights in the other. The maximum line pen
        # tolerance also covers the allowed endpoint/axis deviation. Project
        # that enclosing window back to page coordinates before testing the
        # cached bounds; no side satisfying the rules below can be excluded.
        margin = 4*height + max_tolerance
        window_low, window_high = low-margin, high+margin
        corners = np.array([[window_low[0], window_low[1]],
                            [window_high[0], window_low[1]],
                            [window_high[0], window_high[1]],
                            [window_low[0], window_high[1]]]) @ axes
        candidates = indices[np.all(highs >= corners.min(axis=0), axis=1)
                             & np.all(lows <= corners.max(axis=0), axis=1)]
    sides = [[], [], [], []]
    for index in candidates:
        index = int(index)
        record, points = geometry[index], paths[index]
        if record.get("type") != "LINE" or len(points) != 2:
            continue
        local = points @ axes.T
        delta = abs(local[1]-local[0])
        pen = max(1.0, float(record.get("stroke_width", 1)))
        tolerance = max(1.0, pen*0.6)
        major = int(np.argmax(delta))
        minor = 1-major
        if delta[minor] > tolerance or delta[major] < height or delta[major] > 8*height:
            continue
        pos = float(local[:, minor].mean())
        start, stop = sorted(local[:, major])
        if start > low[major]+tolerance or stop < high[major]-tolerance:
            continue
        if low[minor] < pos < high[minor] or abs(pos-middle[minor]) > 4*height:
            continue
        side = 2*major + int(pos > middle[minor])
        sides[side].append((abs(pos-middle[minor]), index, pos, start, stop, pen))
    # major=0 gives top/bottom, major=1 gives left/right.
    choices = [sorted(items)[:4] for items in sides]
    for top, bottom, left, right in product(*choices):
        x0, x1, y0, y1 = left[2], right[2], top[2], bottom[2]
        pen = float(np.median([item[5] for item in (top, bottom, left, right)]))
        tolerance = max(1.25, pen*0.8)
        if min(x1-x0, y1-y0) <= 2*pen:
            continue
        expected = ((x0, x1), (x0, x1), (y0, y1), (y0, y1))
        if any(max(abs(item[3]-a), abs(item[4]-b)) > tolerance
               for item, (a, b) in zip((top, bottom, left, right), expected)):
            continue
        indices = tuple(sorted(item[1] for item in (top, bottom, left, right)))
        yield _Frame("rectangle", indices, np.array([(x0+x1)/2, (y0+y1)/2]) @ axes,
                     axes, np.array([(x1-x0)/2, (y1-y0)/2]), pen)


def _enters_interior(points, frame, inset):
    if len(points) < 2:
        return False
    local = (points-frame.center) @ frame.axes.T
    a, direction = local[:-1], np.diff(local, axis=0)
    if frame.kind == "circle":
        length = (direction**2).sum(axis=1)
        t = np.clip(-(a*direction).sum(axis=1)/np.maximum(length, 1e-12), 0, 1)
        return bool(np.any(np.linalg.norm(a+t[:, None]*direction, axis=1) < frame.half[0]-inset))
    half = frame.half - inset
    if min(half) <= 0:
        return False
    enter, leave = np.zeros(len(a)), np.ones(len(a))
    for axis in range(2):
        moving = abs(direction[:, axis]) > 1e-12
        valid = moving | (abs(a[:, axis]) < half[axis])
        divisor = np.where(moving, direction[:, axis], 1)
        t0 = (-half[axis]-a[:, axis])/divisor
        t1 = (half[axis]-a[:, axis])/divisor
        enter = np.maximum(enter, np.where(moving, np.minimum(t0, t1), 0))
        leave = np.minimum(leave, np.where(moving, np.maximum(t0, t1), 1))
        leave[~valid] = -1
    return bool(np.any(leave-enter > 1e-9))


def _label_fits(frame, quad):
    height = float(np.linalg.norm(quad[3]-quad[0]))
    if height <= 0 or not np.all(frame.contains(quad, margin=frame.pen*0.5)):
        return False
    if not 1.15*height <= 2*min(frame.half) <= 5*height or max(frame.half) > 4*height:
        return False
    if frame.kind == "rectangle" and max(frame.half) > 3*min(frame.half):
        return False
    offset = (quad.mean(axis=0)-frame.center) @ frame.axes.T
    return bool(np.all(abs(offset) <= 0.45*frame.half))


def assemble_symbols(geometry, texts, *, cancellation_token=None):
    """Return source-index associations for compact observed frames and labels.

    ``geometry_indices`` are selectable frame members, ``text_indices`` refer
    to whole OCR strings, and ``leader_indices`` are external relationships.
    All indices address the supplied lists, without replacing any entity.
    """
    if not geometry or not texts:
        return []
    paths = [_points(record) for record in geometry]
    lows = np.array([points.min(axis=0) if len(points) else [np.inf, np.inf] for points in paths])
    highs = np.array([points.max(axis=0) if len(points) else [-np.inf, -np.inf] for points in paths])
    line_indices = np.array([index for index, (record, points) in enumerate(zip(geometry, paths))
                             if record.get("type") == "LINE" and len(points) == 2], dtype=np.intp)
    max_tolerance = max([1.0, *(0.6*max(1.0, float(geometry[index].get("stroke_width", 1)))
                                for index in line_indices)])
    line_search = (line_indices, lows[line_indices], highs[line_indices], max_tolerance)
    quads = [np.asarray(line.quad, dtype=float) for line in texts]
    valid = [q.shape == (4, 2) and np.isfinite(q).all() for q in quads]
    frames = list(_circle_frames(geometry))
    for index, (record, points) in enumerate(zip(geometry, paths)):
        frame = _polygon_frame(index, record, points)
        if frame is not None:
            frames.append(frame)
    for index, quad in enumerate(quads):
        checkpoint(cancellation_token)
        if valid[index]:
            frames.extend(_line_frames(geometry, paths, quad, line_search=line_search))
    unique = {frame.indices: frame for frame in frames}
    selected = []
    used_geometry, used_text = set(), set()
    for frame in sorted(unique.values(), key=lambda item: float(np.prod(item.half))):
        checkpoint(cancellation_token)
        if used_geometry.intersection(frame.indices):
            continue
        labels = [index for index, quad in enumerate(quads)
                  if valid[index] and frame.contains(quad.mean(axis=0))]
        if len(labels) != 1 or labels[0] in used_text or not _label_fits(frame, quads[labels[0]]):
            continue
        corners = frame.center + np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * frame.half @ frame.axes
        bounds = (corners.min(axis=0), corners.max(axis=0))
        nearby = np.flatnonzero(np.all(highs >= bounds[0]-frame.pen, axis=1)
                                & np.all(lows <= bounds[1]+frame.pen, axis=1))
        leaders, grid_extensions = [], 0
        divided = False
        for raw_index in nearby:
            index = int(raw_index)
            record, points = geometry[index], paths[index]
            if index in frame.indices or len(points) < 2:
                continue
            if _enters_interior(points, frame, max(1.0, frame.pen)):
                divided = True
                break
            if record.get("type") not in {"LINE", "LWPOLYLINE"} or record.get("closed"):
                continue
            endpoints = points[[0, -1]]
            near = frame.on_border(endpoints, max(1.25, frame.pen))
            if near.any() and not frame.contains(endpoints, margin=frame.pen).all():
                leaders.append(index)
                if frame.kind == "rectangle":
                    local = (points-frame.center) @ frame.axes.T
                    # Collinear continuations at corners indicate shared grid
                    # boundaries, while a radial lead meets the middle of a side.
                    if any(np.all(abs(local[:, axis]-sign*frame.half[axis]) <= max(1.0, frame.pen))
                           for axis in (0, 1) for sign in (-1, 1)):
                        grid_extensions += 1
        if divided or grid_extensions:
            continue
        # Closed neighbouring cells can have no individual side continuations.
        # A shared side still identifies the candidate as part of a table grid.
        if frame.kind == "rectangle":
            if any(other.indices != frame.indices and other.kind == "rectangle"
                   and np.count_nonzero(other.on_border(corners, max(1.0, frame.pen))) >= 2
                   for other in unique.values()):
                continue
        selected.append({"kind": frame.kind, "geometry_indices": list(frame.indices),
                         "text_indices": labels, "leader_indices": leaders,
                         "bounds": np.concatenate(bounds).tolist()})
        used_geometry.update(frame.indices)
        used_text.update(labels)
    return selected
