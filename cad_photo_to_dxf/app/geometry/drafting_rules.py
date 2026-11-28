"""Executable drafting rules for source-supported scan geometry.

The extractor keeps observations; this module resolves their drawing relations.
Every changed segment must still lie on observed ink. A nearby endpoint alone is
not permission to join across white paper. Input records remain unmodified and
``source_indices`` refers to that immutable input, including after a merge.
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil

import cv2
import numpy as np
from scipy.spatial import cKDTree

from app.core.cancellation import checkpoint


PACK_NAME = "scan-drafting"
PACK_VERSION = "1"


def _width(record):
    return max(1.0, float(record.get("stroke_width", 1.0)))


def _length(points):
    return float(np.linalg.norm(points[1] - points[0]))


def _normal_tolerance(width):
    # This is a raster-centre tolerance, not permission to move by a whole pen.
    return max(0.6, min(1.25, width * 0.25))


class _InkSupport:
    def __init__(self, binary, dpi=300.0, source_binary=None):
        self.ink = np.asarray(binary) < 128
        self.height, self.width = self.ink.shape
        self.source_ink = self.ink if source_binary is None else np.asarray(source_binary) < 128
        if self.source_ink.shape != self.ink.shape:
            raise ValueError("Source and geometry witnesses must use the same page coordinates")
        self.dpi = float(dpi)
        if not np.isfinite(self.dpi) or self.dpi <= 0:
            raise ValueError("DPI must be positive")
        self.kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        self.allowed = cv2.dilate(self.ink.astype(np.uint8), self.kernel) > 0
        self.rejected_stroke_changes = 0
        self.mixed_pen_joins_kept = 0
        self.corner_pen_normalizations = 0

    def lineweight(self, record):
        if "lineweight" in record:
            return int(record["lineweight"])
        measured = 2540.0 * _width(record) / self.dpi
        return min((13, 25, 50, 100), key=lambda weight: abs(weight - measured))

    def _thickness(self, record):
        return max(1, round(self.lineweight(record) * self.dpi / 2540))

    def _regions(self, records):
        """Keep every endpoint inside one local raster, preserving line phase.

        Clipping a long line into tiles before drawing can restart OpenCV's
        raster stepping at a different phase. The complete before/after bounds
        avoid that error without repainting the entire page on every proposal.
        """
        lower = np.array([self.width, self.height])
        upper = np.zeros(2, int)
        for record in records:
            points = np.asarray(record["points"], float)
            margin = self._thickness(record) + 2
            lower = np.minimum(lower, np.floor(points.min(axis=0) - margin).astype(int))
            upper = np.maximum(upper, np.ceil(points.max(axis=0) + margin).astype(int) + 1)
        lower = np.maximum(0, lower)
        upper = np.minimum((self.width, self.height), upper)
        if np.all(upper > lower):
            yield lower, upper

    def _paint(self, records, lower, upper):
        mask = np.zeros((upper[1] - lower[1], upper[0] - lower[0]), np.uint8)
        for record in records:
            points = np.asarray(record["points"], float) - lower
            cv2.polylines(mask, [np.rint(points * 16).astype(np.int32)],
                          bool(record.get("closed", False)), 255,
                          self._thickness(record), shift=4)
        return mask

    def accepts_change(self, before, after, *, corner_centers=()):
        """Check the delivered pen, including its round ends, against the page.

        New paper marks may not appear outside geometry ink (with one raster
        pixel of tolerance). Previously represented ink in the pre-OCR source
        must remain represented. Only a separately proved orthogonal corner can
        occupy its standard pen's local disk; that cost remains visible to the
        independent saved-file check. Source-ink coverage is never exempted.
        """
        normalized_corner = False
        for lo, hi in self._regions([*before, *after]):
            # A halo keeps source coverage dilation inside the rendered bounds.
            lower = np.maximum(0, lo - 1)
            upper = np.minimum((self.width, self.height), hi + 1)
            inside = (slice(lo[1] - lower[1], hi[1] - lower[1]),
                      slice(lo[0] - lower[0], hi[0] - lower[0]))
            old = self._paint(before, lower, upper)
            new = self._paint(after, lower, upper)
            allowed = self.allowed[lower[1]:upper[1], lower[0]:upper[0]]
            added = (new > 0) & (old == 0) & ~allowed
            source = self.source_ink[lower[1]:upper[1], lower[0]:upper[0]]
            lost = (source & (cv2.dilate(old, self.kernel) > 0)
                    & (cv2.dilate(new, self.kernel) == 0))
            if lost[inside].any():
                self.rejected_stroke_changes += 1
                return False
            locations = np.argwhere(added[inside])
            if len(locations):
                radius = ceil(max(self._thickness(record) for record in after) / 2)
                pixels = np.column_stack((locations[:, 1] + lo[0], locations[:, 0] + lo[1]))
                outside = np.ones(len(pixels), bool)
                for center in corner_centers:
                    outside &= np.sum((pixels - center) ** 2, axis=1) > radius ** 2
                if outside.any():
                    self.rejected_stroke_changes += 1
                    return False
                normalized_corner = True
        if normalized_corner:
            self.corner_pen_normalizations += 1
        return True

    def supports(self, points):
        """Test every half-pixel section along the proposed centre line.

        Search only across the normal, never along the line: dilation in the
        travel direction would conceal a real white gap between two strokes.
        """
        start, end = np.asarray(points, dtype=float)
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length < 0.5 or not np.isfinite(length):
            return False
        count = max(2, ceil(length * 2) + 1)
        samples = start + np.linspace(0, 1, count)[:, None] * vector
        normal = np.array([-vector[1], vector[0]]) / length
        occupied = np.zeros(count, bool)
        for offset in (-0.75, 0.0, 0.75):
            coords = np.rint(samples + offset * normal).astype(np.int64)
            valid = ((coords[:, 0] >= 0) & (coords[:, 0] < self.width)
                     & (coords[:, 1] >= 0) & (coords[:, 1] < self.height))
            occupied[valid] |= self.ink[coords[valid, 1], coords[valid, 0]]
        return bool(occupied.all())


def _with_rule(record, name):
    rules = list(record.get("rules", ()))
    if name not in rules:
        rules.append(name)
    return rules


def _axis_segment(points, width):
    points = np.asarray(points, dtype=float).copy()
    length = _length(points)
    if length < 3:
        return None
    delta = abs(points[1] - points[0])
    minor = int(np.argmin(delta))
    if delta[minor] > min(_normal_tolerance(width) * 2, length * 0.04):
        return None
    points[:, minor] = float(points[:, minor].mean())
    return points


def _axis_run_coordinate(points, width, observations):
    """Prove a straight interior from the observed path, independent of its chord."""
    points = np.asarray(points, dtype=float)
    delta = abs(points[1] - points[0])
    major = int(np.argmax(delta))
    minor = 1 - major
    tolerance = _normal_tolerance(width)
    if delta[major] < max(6.0, 4 * width) or delta[minor] > 2 * tolerance:
        return None
    lower, upper = sorted(points[:, major])
    trim = min(width, (upper - lower) / 4)
    nearby = ((observations[:, major] >= lower + trim)
              & (observations[:, major] <= upper - trim)
              & (abs(observations[:, minor] - points[:, minor].mean()) <= 2 * tolerance))
    values = observations[nearby, minor]
    if len(values) < max(4, (upper - lower - 2 * trim) * 0.5):
        return None
    center = float(np.median(values))
    # A shallow diagonal has a progression of raster steps; a ruled edge has
    # one dominant interior axis despite displaced corner endpoints.
    if np.mean(abs(values - center) <= 0.25) < 0.8:
        return None
    order = np.argsort(observations[nearby, major], kind="stable")
    steps = np.diff(values[order])
    steps = steps[abs(steps) > 0.25]
    if len(steps) and (np.all(steps > 0) or np.all(steps < 0)):
        # Even a single sustained step carries a real slope. Local excursions
        # around a common axis return to it; monotonic staircases do not.
        return None
    third = max(1, len(order) // 3)
    if abs(np.median(values[order[:third]]) - np.median(values[order[-third:]])) >= 0.5:
        return None
    return center


def _observed_axis_segment(points, width, observations):
    """Use the straight interior of a run when rounded corners tilt its chord."""
    points = np.asarray(points, dtype=float)
    aligned = _axis_segment(points, width)
    if aligned is not None and np.allclose(points, aligned, atol=1e-7, rtol=0):
        return aligned
    center = _axis_run_coordinate(points, width, observations)
    if center is None:
        return None
    minor = int(np.argmin(abs(points[1] - points[0])))
    aligned = points.copy()
    aligned[:, minor] = center
    return aligned


def _orthogonal_path(record, support):
    """Resolve raster stair-steps at ruled corners without changing curves."""
    # A closed frame is already one editable object. Only open edge chains
    # need decomposition before continuation across their branch junctions.
    if record.get("closed", False):
        return None
    original = np.asarray(record["points"], dtype=np.float64)
    width = _width(record)
    # A second simplification removes at most the corner's raster stair-step.
    points = cv2.approxPolyDP(original.astype(np.float32),
                             max(0.75, min(3.0, width * 0.60)), False).reshape(-1, 2)
    if len(points) < 2:
        return None
    pairs = list(zip(points[:-1], points[1:]))
    observations = np.asarray(record.get("source_path", original), float)
    edges = [_observed_axis_segment(pair, width, observations) for pair in pairs]
    if any(edge is None for edge in edges):
        return None
    for edge in edges:
        major = int(np.argmax(abs(edge[1] - edge[0])))
        minor = 1 - major
        lower, upper = sorted(edge[:, major])
        nearby = ((observations[:, major] >= lower) & (observations[:, major] <= upper)
                  & (abs(observations[:, minor] - edge[0, minor]) <= 2 * _normal_tolerance(width)))
        if nearby.any():
            # Interior run observations dominate the rounded corner endpoints.
            edge[:, minor] = float(np.median(observations[nearby, minor]))
    # An axis interpretation must account for the entire observed path, not
    # merely approximate its endpoints while cutting an internal bend.
    for point in original:
        if min(_distance_to_segment(point, edge) for edge in edges) > _normal_tolerance(width):
            return None
    # Adjacent orthogonal lines meet at their analytic intersection. Long
    # collinear edges are handled by the same merge rule as all other records.
    for i in range(len(edges) - 1):
        j = i + 1
        intersection = _intersection(edges[i], edges[j])
        if intersection is not None:
            edges[i][1] = intersection
            edges[j][0] = intersection
    if not all(support.supports(edge) for edge in edges):
        return None
    corner_centers = []
    if "source_path" in record:
        axes = [int(np.argmax(abs(edge[1] - edge[0]))) for edge in edges]
        runs = [_axis_run_coordinate(edge, width, observations) for edge in edges]
        for i in range(len(edges) - 1):
            if axes[i] == axes[i + 1] or runs[i] is None or runs[i + 1] is None:
                continue
            if (abs(runs[i] - edges[i][0, 1 - axes[i]]) > 0.25
                    or abs(runs[i + 1] - edges[i + 1][0, 1 - axes[i + 1]]) > 0.25):
                continue
            center = edges[i][1]
            x, y = np.rint(center).astype(int)
            # Normal-neighbour support must not borrow ink across a white
            # corner: the proved analytic intersection itself needs source ink.
            if 0 <= x < support.width and 0 <= y < support.height and support.ink[y, x]:
                corner_centers.append(center)
    result = []
    for edge in edges:
        changed = dict(record)
        changed.pop("closed", None)
        changed.pop("endpoint_degrees", None)
        changed["type"] = "LINE"
        changed["points"] = edge.tolist()
        changed["rules"] = _with_rule(record, "orthogonal_frame")
        result.append(changed)
    previous_normalizations = support.corner_pen_normalizations
    if not support.accepts_change([record], result, corner_centers=corner_centers):
        return None
    if support.corner_pen_normalizations > previous_normalizations:
        for changed in result:
            changed["rules"] = _with_rule(changed, "orthogonal_corner_pen")
    return result


def _distance_to_segment(point, segment):
    a, b = np.asarray(segment, dtype=float)
    delta = b - a
    denominator = float(delta @ delta)
    if not denominator:
        return float(np.linalg.norm(point - a))
    t = float(np.clip((point - a) @ delta / denominator, 0, 1))
    return float(np.linalg.norm(point - (a + t * delta)))


def _intersection(first, second):
    p, q = first
    r, s = second
    a, b = q - p, s - r
    cross = a[0] * b[1] - a[1] * b[0]
    if abs(cross) < 1e-8 * max(1.0, np.linalg.norm(a) * np.linalg.norm(b)):
        return None
    offset = r - p
    t = (offset[0] * b[1] - offset[1] * b[0]) / cross
    return p + t * a


def _endpoint_pairs(lines, radius=4.0):
    if len(lines) < 2:
        return
    endpoints = np.asarray([point for line in lines for point in line["points"]], float)
    tree = cKDTree(endpoints)
    for i, point in enumerate(endpoints):
        for j in sorted(tree.query_ball_point(point, radius)):
            if j > i and j // 2 != i // 2:
                yield i // 2, i % 2, j // 2, j % 2


def _snap_intersections(lines, support, stats, cancellation_token):
    """Move only neighbouring endpoints onto an ink-supported T/L/X joint."""
    for count, (i, a, j, b) in enumerate(_endpoint_pairs(lines)):
        if count % 256 == 0:
            checkpoint(cancellation_token)
        first = np.asarray(lines[i]["points"], float)
        second = np.asarray(lines[j]["points"], float)
        length_a, length_b = _length(first), _length(second)
        if min(length_a, length_b) < 2:
            continue
        direction_a = (first[1] - first[0]) / length_a
        direction_b = (second[1] - second[0]) / length_b
        # Near-parallel continuations are resolved by the collinearity rule.
        if abs(direction_a @ direction_b) > 0.95:
            continue
        intersection = _intersection(first, second)
        if intersection is None:
            continue
        tolerance = max(1.0, min(4.0, min(_width(lines[i]), _width(lines[j])) * 0.6))
        if max(np.linalg.norm(intersection - first[a]),
               np.linalg.norm(intersection - second[b])) > tolerance:
            continue
        moved_a, moved_b = first.copy(), second.copy()
        moved_a[a], moved_b[b] = intersection, intersection
        if np.allclose(first, moved_a, atol=1e-7, rtol=0):
            moved_a = first
        if np.allclose(second, moved_b, atol=1e-7, rtol=0):
            moved_b = second
        if moved_a is first and moved_b is second:
            continue
        if _length(moved_a) < length_a * 0.5 or _length(moved_b) < length_b * 0.5:
            continue
        if not support.supports(moved_a) or not support.supports(moved_b):
            continue
        proposed = [dict(lines[i], points=moved_a.tolist()), dict(lines[j], points=moved_b.tolist())]
        if not support.accepts_change([lines[i], lines[j]], proposed):
            continue
        for index, old, new in ((i, first, moved_a), (j, second, moved_b)):
            if not np.allclose(old, new, atol=1e-7, rtol=0):
                lines[index]["points"] = new.tolist()
                lines[index]["rules"] = _with_rule(lines[index], "junction_snap")
                stats["snapped_endpoints"] += 1


def _fit_union(first, second, support):
    """Use both observations to select a single complete collinear segment."""
    a, b = np.asarray(first["points"], float), np.asarray(second["points"], float)
    lengths = _length(a), _length(b)
    if min(lengths) < 0.5:
        return None
    if support.lineweight(first) != support.lineweight(second):
        # A single LINE cannot carry a change of standard pen along its length.
        # Keep the connected observations with their respective formal pens.
        support.mixed_pen_joins_kept += 1
        return None
    widths = _width(first), _width(second)
    if max(widths) > min(widths) * 1.65:
        return None
    directions = [(points[1] - points[0]) / length for points, length in zip((a, b), lengths)]
    # Bound angular drift independently of segment length and pen thickness.
    if abs(directions[0] @ directions[1]) < np.cos(np.deg2rad(3.0)):
        return None
    points = np.concatenate((a, b))
    center = np.average(points, axis=0, weights=np.repeat(lengths, 2))
    _, _, axes = np.linalg.svd((points - center) * np.sqrt(np.repeat(lengths, 2))[:, None], full_matrices=False)
    axis = axes[0]
    normal = np.array([-axis[1], axis[0]])
    tolerance = _normal_tolerance(min(widths))
    if np.max(abs((points - center) @ normal)) > tolerance:
        return None
    projections = (points - center) @ axis
    proposed = np.array([center + axis * projections.min(), center + axis * projections.max()])
    # Test the delivered geometry, not a coverage mask painted from old paths.
    if not support.supports(proposed):
        return None
    result = dict(first)
    result.pop("source_path", None)
    result.pop("endpoint_degrees", None)
    result["points"] = proposed.tolist()
    result["source_indices"] = sorted(set(first["source_indices"]) | set(second["source_indices"]))
    result["rules"] = list(dict.fromkeys([*first["rules"], *second["rules"], "collinear_continuation"]))
    # Length weighting prevents a thick junction pixel from changing a long pen.
    result["stroke_width"] = float(np.average(widths, weights=lengths))
    return result if support.accepts_change([first, second], [result]) else None


def _merge_collinear(lines, support, stats, cancellation_token):
    parents = list(range(len(lines)))
    resolved = [dict(line) for line in lines]

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for count, (i, _, j, _) in enumerate(_endpoint_pairs(lines)):
        if count % 256 == 0:
            checkpoint(cancellation_token)
        a, b = root(i), root(j)
        if a == b:
            continue
        combined = _fit_union(resolved[a], resolved[b], support)
        if combined is not None:
            parents[b] = a
            resolved[a] = combined
            stats["merged_segments"] += 1
    return [resolved[i] for i in range(len(lines)) if root(i) == i]


def _assemble_junction_links(lines, support, stats, cancellation_token):
    """Account for raster junction links already carried by crossing main lines.

    Both ends must be branch nodes and every observed point must lie on the
    crossing lines. An isolated dash or a bridge between parallel lines cannot
    satisfy this rule. Ownership moves to those lines instead of being dropped.
    """
    absorbed = set()
    lengths = [_length(np.asarray(line["points"], float)) for line in lines]
    samples, owners = [], []
    for index, (line, length) in enumerate(zip(lines, lengths)):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        if length >= 8:
            segment = np.asarray(line["points"], float)
            count = ceil(length / 32) + 1
            samples.extend(np.linspace(segment[0], segment[1], count))
            owners.extend([index] * count)
    if not samples:
        return lines
    tree = cKDTree(np.asarray(samples))
    for i, line in enumerate(lines):
        if i % 256 == 0:
            checkpoint(cancellation_token)
        degrees = line.get("endpoint_degrees", ())
        if len(degrees) != 2 or min(degrees) < 3 or lengths[i] > max(2.0, _width(line) * 1.5):
            continue
        observations = np.asarray(line.get("source_path", line["points"]), float)
        middle = observations.mean(axis=0)
        carriers = []
        neighbours = sorted({owners[k] for k in tree.query_ball_point(middle, 18)})
        for j in neighbours:
            other = lines[j]
            if i == j or lengths[j] < max(8.0, 4 * _width(line)):
                continue
            segment = np.asarray(other["points"], float)
            if _distance_to_segment(middle, segment) > 2:
                continue
            direction = (segment[1] - segment[0]) / lengths[j]
            normal = np.array([-direction[1], direction[0]])
            along = (observations - segment[0]) @ direction
            inside = (along >= -0.75) & (along <= lengths[j] + 0.75)
            covered = inside & (abs((observations - segment[0]) @ normal) <= 0.75)
            if covered.any():
                carriers.append((j, direction, covered))
        for a in range(len(carriers)):
            for b in range(a + 1, len(carriers)):
                first, second = carriers[a], carriers[b]
                if abs(first[1] @ second[1]) > 0.8 or not np.all(first[2] | second[2]):
                    continue
                carriers_pair = [lines[first[0]], lines[second[0]]]
                if not support.accepts_change([line, *carriers_pair], carriers_pair):
                    continue
                for j in (first[0], second[0]):
                    lines[j]["source_indices"] = sorted(set(lines[j]["source_indices"])
                                                         | set(line["source_indices"]))
                    lines[j]["rules"] = _with_rule(lines[j], "junction_assembly")
                absorbed.add(i)
                break
            if i in absorbed:
                break
    stats["assembled_junction_links"] = len(absorbed)
    return [line for i, line in enumerate(lines) if i not in absorbed]


def resolve_geometry(records, binary, *, dpi=300.0, source_binary=None, cancellation_token=None):
    """Apply the executable pack to an entire page's extracted observations.

    Records outside these rules' shape families are carried through unchanged.
    A failed simplification keeps its observed editable geometry, never a blank
    area or a repair-layer substitute. The caller retains the source candidates.
    """
    support = _InkSupport(binary, dpi, source_binary)
    stats = defaultdict(int)
    lines, others = [], []
    for index, original in enumerate(records):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        record = dict(original)
        record["lineweight"] = support.lineweight(record)
        record["source_indices"] = [index]
        record["rules"] = []
        kind = record["type"]
        if kind == "LINE":
            points = np.asarray(record["points"], float)
            observations = np.asarray(record.get("source_path", points), float)
            aligned = _observed_axis_segment(points, _width(record), observations)
            if (aligned is not None and not np.allclose(points, aligned, atol=1e-7, rtol=0)
                    and support.supports(aligned)):
                proposed = dict(record, points=aligned.tolist(), rules=["orthogonal_alignment"])
                if support.accepts_change([record], [proposed]):
                    record = proposed
                    stats["aligned_segments"] += 1
            lines.append(record)
        elif kind == "LWPOLYLINE" and "const_width_px" not in record:
            frame = _orthogonal_path(record, support)
            if frame is None:
                others.append(record)
            else:
                lines.extend(frame)
                stats["resolved_frames"] += 1
        else:
            others.append(record)
    _snap_intersections(lines, support, stats, cancellation_token)
    resolved = _merge_collinear(lines, support, stats, cancellation_token)
    resolved = _assemble_junction_links(resolved, support, stats, cancellation_token) + others
    resolved.sort(key=lambda record: (min(record["source_indices"]), record["type"]))
    return resolved, {"pack": PACK_NAME, "version": PACK_VERSION,
                      "input_candidates": len(records), "output_entities": len(resolved),
                      "aligned_segments": stats["aligned_segments"],
                      "resolved_frames": stats["resolved_frames"],
                      "snapped_endpoints": stats["snapped_endpoints"],
                      "merged_segments": stats["merged_segments"],
                      "assembled_junction_links": stats["assembled_junction_links"],
                      "rejected_stroke_changes": support.rejected_stroke_changes,
                      "mixed_pen_joins_kept": support.mixed_pen_joins_kept,
                      "corner_pen_normalizations": support.corner_pen_normalizations}
