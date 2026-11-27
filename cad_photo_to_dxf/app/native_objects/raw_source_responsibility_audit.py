"""Independent, bounded raw-ink observations for saved finite CAD geometry.

This module deliberately imports no planner, skeleton, adoption receipt, or
producer verdict.  A compatible cap is an observation under a measured-width
model, not a proof of exclusive ownership or of the original drawing order.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import itertools
import json
import math

import numpy as np
from scipy.ndimage import label


SCHEMA = "independent-raw-source-responsibility-v2"
POLICY = {
    "version": "finite-geometry-raw-sections-v2-context-bounds",
    "unsupported_context_requires_certified_bbox": True,
    "source_black_threshold": 128,
    "inward_section_distances_px": [4, 6, 8, 12, 16],
    "normal_section_half_span_px": 16,
    "minimum_isolated_sections": 2,
    "pixel_cell_half_diagonal_px": math.sqrt(0.5),
    "endpoint_window_minimum_radius_px": 8,
    "endpoint_window_radius_width_multiplier": 3,
    "endpoint_window_radius_margin_px": 4,
    "observable_unassigned_excess_px": 2,
    "minimum_observable_projection_bins": 3,
    "source_ink_connectivity": 4,
    "diagnostic_ink_connectivity": 8,
    "white_hole_connectivity": 4,
    "supported_geometry_kinds": ["LINE", "LWPOLYLINE", "CONNECTION_PATH"],
    "maximum_target_objects": 64,
    "maximum_context_objects": 1024,
    "maximum_vertices_per_geometry": 1024,
    "maximum_roi_pixels": 1000000,
}

LIMITATIONS = [
    "Observed section widths and circular finite-geometry envelopes are a local "
    "diagnostic family, not a validated general pen or scanner model.",
    "Fixed 4/6/8/12/16 px samples define applicability at native source scale; "
    "they do not establish scale invariance or five independent observations.",
    "CAP_OR_JUNCTION_COMPATIBLE does not prove a unique stroke boundary, "
    "exclusive source ownership, drawing order, or product acceptance.",
    "Unassigned connected ink may be a continuation, another stroke, or an "
    "unmodeled width change; no missing centerline is synthesized.",
    "Only finite straight segments are audited. Relevant arcs, nonzero bulges, "
    "and unsupported members remain explicitly unresolved.",
    "The audit concerns the supplied ROI and target IDs, not all objects or "
    "unrepresented source ink on the page.",
]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _fraction(value):
    return Fraction.from_float(float(value))


def _point_fraction(point):
    return tuple(_fraction(value) for value in point)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _cells_at(point):
    """Every closed unit pixel cell containing an exact rational point."""
    axes = []
    for value in point:
        shifted = value + Fraction(1, 2)
        upper = math.floor(shifted)
        axes.append([upper - 1, upper] if shifted.denominator == 1 else [upper])
    return list(itertools.product(*axes))


def _raster_intervals(a, b):
    """Exact cell-boundary partition of the *supplied binary floats*.

    No epsilon changes endpoints or turns a near intersection into a contact.
    Positive intervals, boundary-aligned intervals, and isolated corner hits
    can consequently be reported separately.
    """
    a, b = _point_fraction(a), _point_fraction(b)
    delta = tuple(y - x for x, y in zip(a, b))
    times = {Fraction(0), Fraction(1)}
    for origin, end, span in zip(a, b, delta):
        if not span:
            continue
        low, high = sorted((origin, end))
        for integer in range(math.ceil(low - Fraction(1, 2)),
                             math.floor(high - Fraction(1, 2)) + 1):
            time = (Fraction(integer) + Fraction(1, 2) - origin) / span
            if 0 <= time <= 1:
                times.add(time)
    times = sorted(times)
    intervals = []
    for low, high in itertools.pairwise(times):
        middle = (low + high) / 2
        point = tuple(x + middle * d for x, d in zip(a, delta))
        intervals.append((low, high, _cells_at(point)))
    events = []
    for time in times:
        point = tuple(x + time * d for x, d in zip(a, delta))
        events.append((time, _cells_at(point)))
    return intervals, events


class _Source:
    def __init__(self, gray, roi, origin):
        self.gray = gray
        self.roi = tuple(roi)
        self.origin = tuple(origin)
        x0, y0, x1, y1 = self.roi
        ox, oy = self.origin
        self.ink = gray[y0 - oy:y1 - oy, x0 - ox:x1 - ox] < POLICY["source_black_threshold"]
        self.labels4, _ = label(self.ink)
        self.labels8, _ = label(self.ink, structure=np.ones((3, 3), int))

    def state(self, cell):
        x, y = cell
        x0, y0, x1, y1 = self.roi
        if not (x0 <= x < x1 and y0 <= y < y1):
            return "OUTSIDE_EVALUATION_ROI"
        return "BLACK" if self.ink[y - y0, x - x0] else "WHITE"

    def component(self, cell, connectivity=4):
        if self.state(cell) != "BLACK":
            return 0
        x, y = cell
        labels = self.labels4 if connectivity == 4 else self.labels8
        return int(labels[y - self.roi[1], x - self.roi[0]])

    def point(self, point):
        cells = _cells_at(_point_fraction(point))
        black = [list(cell) for cell in cells if self.state(cell) == "BLACK"]
        return {"closed_cells": [list(cell) for cell in cells], "black_cells": black,
                "white_cells": [list(cell) for cell in cells if self.state(cell) == "WHITE"],
                "outside_cells": [list(cell) for cell in cells
                                  if self.state(cell) == "OUTSIDE_EVALUATION_ROI"]}


def _segments(geometry):
    points = geometry["points"]
    result = list(itertools.pairwise(points))
    if geometry.get("closed") and len(points) > 2 and points[0] != points[-1]:
        result.append((points[-1], points[0]))
    return result


def _normalise_geometry(row):
    result = dict(row)
    result["object_id"] = str(row["object_id"])
    points = row.get("points", [])
    valid = (isinstance(points, (list, tuple)) and len(points) >= 2
             and all(isinstance(p, (list, tuple)) and len(p) == 2
                     and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)
                     for p in points))
    result["points"] = [[float(v) for v in p] for p in points] if valid else []
    reasons = []
    if row.get("kind") not in POLICY["supported_geometry_kinds"]:
        reasons.append("UNSUPPORTED_GEOMETRY_KIND")
    if not valid:
        reasons.append("MISSING_FINITE_TWO_DIMENSIONAL_POINTS")
    if valid and len(points) > POLICY["maximum_vertices_per_geometry"]:
        reasons.append("VERTEX_RESOURCE_LIMIT")
    if any(float(value) != 0 for value in row.get("bulges", [])):
        reasons.append("NONZERO_BULGE_REQUIRES_CURVED_GEOMETRY_AUDIT")
    if row.get("unsupported_reason"):
        reasons.append(str(row["unsupported_reason"]))
    if valid and not any(a != b for a, b in itertools.pairwise(result["points"])):
        reasons.append("NO_POSITIVE_LENGTH_GEOMETRY")
    result["audit_supported"] = not reasons
    result["audit_unsupported_reasons"] = reasons
    if not row.get("bbox_xyxy") and valid:
        array = np.asarray(points, float)
        result["bbox_xyxy"] = [*array.min(axis=0).tolist(), *array.max(axis=0).tolist()]
    return result


def _support(source, geometry):
    segments, white_interior, boundary_white, corner_white, outside = [], set(), set(), set(), set()
    total_uncovered = 0.0
    for index, (a, b) in enumerate(_segments(geometry)):
        length = math.dist(a, b)
        if not length:
            continue
        intervals, events = _raster_intervals(a, b)
        unsupported, boundary, white_positive = [], [], set()
        for low, high, cells in intervals:
            black = [cell for cell in cells if source.state(cell) == "BLACK"]
            white = [cell for cell in cells if source.state(cell) == "WHITE"]
            out = [cell for cell in cells if source.state(cell) == "OUTSIDE_EVALUATION_ROI"]
            outside.update(out)
            white_positive.update(white)
            if len(cells) == 1:
                white_interior.update(white)
            elif white:
                boundary_white.update(white)
                boundary.append({"t_interval": [float(low), float(high)],
                                 "white_cells": [list(c) for c in white],
                                 "black_cells": [list(c) for c in black]})
            if not black and not out:
                span = length * float(high - low)
                total_uncovered += span
                unsupported.append({"t_interval": [float(low), float(high)],
                                    "length_px": span, "white_cells": [list(c) for c in white]})
        corners = {cell for _, cells in events for cell in cells
                   if source.state(cell) == "WHITE" and cell not in white_positive}
        corner_white.update(corners)
        segments.append({"segment_index": index, "points": [a, b],
                         "uncovered_positive_intervals": unsupported,
                         "boundary_aligned_white_intervals": boundary,
                         "zero_length_white_cells": [list(c) for c in sorted(corners)]})
    return {"object_id": geometry["object_id"], "segments": segments,
            "status": "HARD_REJECT_WHITE_GAP" if total_uncovered else (
                "SOURCE_UNRESOLVED_OUTSIDE_ROI" if outside else "SUPPORTED_BY_CLOSED_BLACK_PIXEL_UNION"),
            "uncovered_positive_length_px": total_uncovered,
            "white_interior_cells": [list(c) for c in sorted(white_interior)],
            "white_boundary_cells": [list(c) for c in sorted(boundary_white)],
            "zero_length_white_cells": [list(c) for c in sorted(corner_white)],
            "outside_evaluation_cells": [list(c) for c in sorted(outside)],
            "closed_cell_all_black": not (white_interior or boundary_white or corner_white or outside)}


def _exact_intersection(a, b, c, d):
    a, b, c, d = map(_point_fraction, (a, b, c, d))
    u = tuple(y - x for x, y in zip(a, b))
    v = tuple(y - x for x, y in zip(c, d))
    w = tuple(y - x for x, y in zip(a, c))
    if not any(u) or not any(v):
        return None
    determinant = _cross(u, v)
    if determinant:
        t, s = _cross(w, v) / determinant, _cross(w, u) / determinant
        if 0 <= t <= 1 and 0 <= s <= 1:
            return {"type": "POINT", "point": tuple(x + t * z for x, z in zip(a, u)),
                    "fractions": [t, s]}
        return None
    if _cross(w, u):
        return None
    axis = 0 if u[0] else 1
    low, high = sorted(((c[axis] - a[axis]) / u[axis], (d[axis] - a[axis]) / u[axis]))
    low, high = max(Fraction(0), low), min(Fraction(1), high)
    if high < low:
        return None
    point = tuple(x + low * z for x, z in zip(a, u))
    if high == low:
        return {"type": "POINT", "point": point, "fractions": [low, None]}
    end = tuple(x + high * z for x, z in zip(a, u))
    return {"type": "OVERLAP", "points": [point, end]}


def _pair_evidence(source, geometries, targets):
    contacts, overlaps = [], []
    for left, right in itertools.combinations(geometries, 2):
        if not ({left["object_id"], right["object_id"]} & targets):
            continue
        if not left["audit_supported"] or not right["audit_supported"]:
            continue
        seen = set()
        for i, (a, b) in enumerate(_segments(left)):
            for j, (c, d) in enumerate(_segments(right)):
                hit = _exact_intersection(a, b, c, d)
                if hit is None:
                    continue
                row = {"object_ids": [left["object_id"], right["object_id"]],
                       "segment_indices": [i, j]}
                if hit["type"] == "OVERLAP":
                    points = [[float(v) for v in p] for p in hit["points"]]
                    row.update(points=points, length_px=math.dist(*points),
                               status="HARD_REJECT_POSITIVE_LENGTH_DUPLICATE")
                    overlaps.append(row)
                    continue
                key = hit["point"]
                if key in seen:
                    continue
                seen.add(key)
                point = [float(v) for v in key]
                cells = _cells_at(key)
                black = [cell for cell in cells if source.state(cell) == "BLACK"]
                white = [cell for cell in cells if source.state(cell) == "WHITE"]
                outside = [cell for cell in cells if source.state(cell) == "OUTSIDE_EVALUATION_ROI"]
                components = sorted({source.component(cell) for cell in black})
                status = "ORIGINAL_INK_POINT_CONTACT"
                if not black:
                    status = "SOURCE_UNRESOLVED_CONTACT_OUTSIDE_ROI" if outside else "HARD_REJECT_UNSUPPORTED_POINT_CONTACT"
                elif len(components) > 1 or (len(cells) == 4 and len(black) < 3):
                    status = "SOURCE_UNRESOLVED_POINT_ONLY_PIXEL_CONNECTION"
                row.update(point_px=point, black_cells=[list(x) for x in black],
                           white_cells=[list(x) for x in white], original_4_connected_labels=components,
                           finite_segment_fractions=[float(v) if v is not None else None
                                                     for v in hit["fractions"]], status=status)
                contacts.append(row)
    return contacts, overlaps


def _white_holes(source):
    components, count = label(~source.ink)
    boundary = set(components[0]) | set(components[-1]) | set(components[:, 0]) | set(components[:, -1])
    result = []
    for index in range(1, count + 1):
        if index in boundary:
            continue
        ys, xs = np.nonzero(components == index)
        points = np.column_stack((xs + source.roi[0], ys + source.roi[1])).tolist()
        result.append({"white_component_id": index, "pixel_count": len(points), "pixels": points,
                       "bbox_xyxy": [int(xs.min()) + source.roi[0], int(ys.min()) + source.roi[1],
                                     int(xs.max()) + 1 + source.roi[0], int(ys.max()) + 1 + source.roi[1]],
                       "interpretation": "ENCLOSED_ORIGINAL_WHITE_REGION_NOT_A_SKELETON_CYCLE"})
    return result


def _distance_projection(points, geometry):
    points = np.asarray(points, float).reshape(-1, 2)
    distances = np.full(len(points), np.inf)
    arclengths = np.zeros(len(points))
    total = 0.0
    for a, b in _segments(geometry):
        a, b = np.asarray(a, float), np.asarray(b, float)
        vector = b - a
        length = float(np.linalg.norm(vector))
        if not length:
            continue
        fractions = np.clip((points - a) @ vector / (length * length), 0, 1)
        current = np.linalg.norm(points - a - fractions[:, None] * vector, axis=1)
        change = current < distances
        distances[change] = current[change]
        arclengths[change] = total + fractions[change] * length
        total += length
    return distances, arclengths, total


def _at_arclength(geometry, distance):
    total = 0.0
    for a, b in _segments(geometry):
        a, b = np.asarray(a, float), np.asarray(b, float)
        span = b - a
        length = float(np.linalg.norm(span))
        if not length:
            continue
        if total <= distance <= total + length:
            fraction = (distance - total) / length
            return a + fraction * span, span / length
        total += length
    return None


def _section(source, point, tangent):
    normal = np.array([-tangent[1], tangent[0]])
    span = POLICY["normal_section_half_span_px"]
    a, b = point - span * normal, point + span * normal
    intervals, _ = _raster_intervals(a, b)
    runs = []
    for low, high, cells in intervals:
        black = [cell for cell in cells if source.state(cell) == "BLACK"]
        if black:
            if runs and runs[-1][1] == low:
                runs[-1][1] = high
                runs[-1][2].update(black)
            else:
                runs.append([low, high, set(black)])
    own = [run for run in runs if run[0] <= Fraction(1, 2) <= run[1]]
    row = {"point_px": point.tolist(), "tangent": tangent.tolist(), "normal": normal.tolist()}
    if len(own) != 1:
        return {**row, "status": "SECTION_AXIS_HAS_NO_UNIQUE_ORIGINAL_INK_INTERVAL"}
    low, high, pixels = own[0]
    if low == 0 or high == 1 or any(source.state(cell) == "OUTSIDE_EVALUATION_ROI"
                                  for cell in _cells_at(_point_fraction(point))):
        return {**row, "status": "SECTION_NOT_BOUNDED_BY_OBSERVED_WHITE"}
    left, right = ((float(value) - 0.5) * 2 * span for value in (low, high))
    # A section touching the ROI can end at unobserved space, not white.
    first, last = _point_fraction(a), _point_fraction(b)
    for value in (low, high):
        probe = tuple(x + value * (y - x) for x, y in zip(first, last))
        if any(source.state(cell) == "OUTSIDE_EVALUATION_ROI"
               for cell in _cells_at(probe)):
            return {**row, "status": "SECTION_BOUNDARY_OUTSIDE_ROI"}
    return {**row, "status": "MEASURED", "signed_normal_interval_px": [left, right],
            "width_px": right - left, "axis_radius_px": max(abs(left), abs(right)),
            "original_ink_cells": [list(cell) for cell in sorted(pixels)]}


def _width_evidence(source, geometry, endpoint, at_own_end, others):
    _, nearest, total = _distance_projection([endpoint], geometry)
    reference = float(nearest[0])
    positions = []
    for offset in POLICY["inward_section_distances_px"]:
        if at_own_end is not None:
            values = [offset if at_own_end == 0 else total - offset]
        else:
            values = [reference - offset, reference + offset]
        positions.extend(v for v in values if 0 < v < total)
    samples = []
    for position in sorted(set(positions)):
        at = _at_arclength(geometry, position)
        if at is None:
            continue
        point, tangent = at
        sample = _section(source, point, tangent)
        sample["arclength_px"] = position
        sample["excluded_by_other_finite_geometries"] = []
        if sample["status"] == "MEASURED":
            radius = sample["axis_radius_px"] + POLICY["pixel_cell_half_diagonal_px"]
            for other in others:
                if other["object_id"] == geometry["object_id"] or not other["audit_supported"]:
                    continue
                distance, _, _ = _distance_projection([point], other)
                if float(distance[0]) <= radius:
                    sample["excluded_by_other_finite_geometries"].append(other["object_id"])
            if sample["excluded_by_other_finite_geometries"]:
                sample["status"] = "EXCLUDED_JUNCTION_CONTAMINATION"
        samples.append(sample)
    isolated = [sample for sample in samples if sample["status"] == "MEASURED"]
    result = {"object_id": geometry["object_id"], "reference_arclength_px": reference,
              "samples": samples, "isolated_section_count": len(isolated)}
    if len(isolated) < POLICY["minimum_isolated_sections"]:
        return {**result, "status": "SOURCE_UNRESOLVED_INSUFFICIENT_ISOLATED_WIDTH"}
    radii = [sample["axis_radius_px"] for sample in isolated]
    widths = [sample["width_px"] for sample in isolated]
    half_cell = POLICY["pixel_cell_half_diagonal_px"]
    return {**result, "status": "MEASURED_LOCAL_WIDTH_FAMILY",
            "observed_axis_radius_range_px": [min(radii), max(radii)],
            "observed_full_width_range_px": [min(widths), max(widths)],
            "pixel_center_envelope_radius_range_px": [max(0.0, min(radii) - half_cell),
                                                       max(radii) + half_cell]}


def _bbox_distance(point, bbox):
    if not bbox or len(bbox) != 4:
        return None
    x, y = point
    return math.hypot(max(bbox[0] - x, 0, x - bbox[2]), max(bbox[1] - y, 0, y - bbox[3]))


def _residual_groups(pixels, margins, point, outward):
    if not len(pixels):
        return []
    low = pixels.min(axis=0)
    high = pixels.max(axis=0)
    mask = np.zeros((high[1] - low[1] + 1, high[0] - low[0] + 1), bool)
    mask[pixels[:, 1] - low[1], pixels[:, 0] - low[0]] = True
    components, count = label(mask)
    result = []
    for index in range(1, count + 1):
        selected = components[pixels[:, 1] - low[1], pixels[:, 0] - low[0]] == index
        group, excess = pixels[selected], margins[selected]
        projections = (group - point) @ outward
        bins = len(set(np.floor(projections).astype(int)))
        observable = (float(excess.max()) > POLICY["observable_unassigned_excess_px"]
                      and bins >= POLICY["minimum_observable_projection_bins"])
        result.append({"pixels": group.tolist(), "pixel_count": len(group),
                       "maximum_distance_outside_all_measured_envelopes_px": float(excess.max()),
                       "forward_projection_range_px": [float(projections.min()), float(projections.max())],
                       "distinct_one_pixel_projection_bins": bins,
                       "observation": "OBSERVABLE_UNASSIGNED_CONTINUATION" if observable
                       else "SOURCE_BOUNDARY_COMPETITION"})
    return result


def _endpoint(source, geometry, end, geometries):
    point = np.asarray(geometry["points"][0 if end == 0 else -1], float)
    segments = _segments(geometry)
    a, b = segments[0 if end == 0 else -1]
    outward = np.asarray(a, float) - b if end == 0 else np.asarray(b, float) - a
    length = np.linalg.norm(outward)
    if length == 0:
        return {"object_id": geometry["object_id"], "end": end, "point_px": point.tolist(),
                "status": "SOURCE_UNRESOLVED_ZERO_LENGTH_TERMINAL_SEGMENT"}
    outward /= length
    maximum_radius = (POLICY["normal_section_half_span_px"]
                      * POLICY["endpoint_window_radius_width_multiplier"]
                      + POLICY["endpoint_window_radius_margin_px"])
    nearby = []
    for other in geometries:
        distance = _bbox_distance(point, other.get("bbox_xyxy"))
        unknown_extent = (not other["audit_supported"]
                          and (other.get("coverage_valid") is not True or distance is None))
        if unknown_extent or (distance is not None and distance <= maximum_radius):
            nearby.append(other)
    widths = [_width_evidence(source, other, point,
                             end if other["object_id"] == geometry["object_id"] else None, nearby)
              for other in nearby if other["audit_supported"]]
    own = next((row for row in widths if row["object_id"] == geometry["object_id"]), None)
    result = {"object_id": geometry["object_id"], "end": end, "point_px": point.tolist(),
              "outward_terminal_direction": outward.tolist(), "local_width_evidence": widths,
              "point_source": source.point(point)}
    if own is None or "pixel_center_envelope_radius_range_px" not in own:
        return {**result, "status": "SOURCE_UNRESOLVED_INSUFFICIENT_ISOLATED_WIDTH"}
    own_radius = own["pixel_center_envelope_radius_range_px"][1]
    radius = max(POLICY["endpoint_window_minimum_radius_px"],
                 POLICY["endpoint_window_radius_width_multiplier"] * own_radius
                 + POLICY["endpoint_window_radius_margin_px"])
    x0, y0, x1, y1 = source.roi
    low = np.floor(point - radius).astype(int)
    high = np.ceil(point + radius).astype(int) + 1
    clipped = bool(low[0] < x0 or low[1] < y0 or high[0] > x1 or high[1] > y1)
    low = np.maximum(low, [x0, y0])
    high = np.minimum(high, [x1, y1])
    result.update(window_radius_px=radius,
                  observed_window_xyxy=[int(low[0]), int(low[1]), int(high[0]), int(high[1])],
                  window_clipped=clipped)
    if np.any(high <= low):
        return {**result, "status": "SOURCE_UNRESOLVED_ENDPOINT_OUTSIDE_ROI"}
    # Seed from the actual finite approach, not a producer graph terminal.
    approach = _at_arclength(geometry, min(2.0, _distance_projection([point], geometry)[2] / 2)
                            if end == 0 else max(0.0, _distance_projection([point], geometry)[2] - 2.0))
    anchor = approach[0] if approach is not None else point
    local_ink = source.ink[low[1] - y0:high[1] - y0, low[0] - x0:high[0] - x0]
    local4, _ = label(local_ink)
    local8, _ = label(local_ink, structure=np.ones((3, 3), int))
    anchor_cells = [cell for cell in source.point(anchor)["black_cells"]
                    if low[0] <= cell[0] < high[0] and low[1] <= cell[1] < high[1]]
    components4 = {int(local4[cell[1] - low[1], cell[0] - low[0]]) for cell in anchor_cells} - {0}
    components8 = {int(local8[cell[1] - low[1], cell[0] - low[0]]) for cell in anchor_cells} - {0}
    result["approach_anchor_px"] = anchor.tolist()
    result["anchor_4_connected_labels"] = sorted(components4)
    ys, xs = np.nonzero(local_ink)
    pixels = np.column_stack((xs + low[0], ys + low[1]))
    relative = pixels - point
    relevant = ((relative @ outward >= -POLICY["pixel_cell_half_diagonal_px"])
                & (np.linalg.norm(relative, axis=1) <= radius))
    pixels = pixels[relevant]
    labels4 = local4[pixels[:, 1] - low[1], pixels[:, 0] - low[0]]
    labels8 = local8[pixels[:, 1] - low[1], pixels[:, 0] - low[0]]
    connected4 = np.isin(labels4, list(components4))
    connected8 = np.isin(labels8, list(components8))
    result["disconnected_nearby_ink_pixels"] = pixels[~connected8].tolist()
    result["only_8_connected_ink_pixels"] = pixels[connected8 & ~connected4].tolist()
    pixels = pixels[connected4]
    result["forward_4_connected_ink_pixels"] = pixels.tolist()
    result["maximum_forward_source_center_extent_px"] = (
        float(((pixels - point) @ outward).max()) if len(pixels) else None)
    explanations, margins = [], np.full(len(pixels), np.inf)
    relevant_widths, unknown_widths = [], []
    for width in widths:
        other = next(row for row in nearby if row["object_id"] == width["object_id"])
        distance, _, _ = _distance_projection([point], other)
        if float(distance[0]) > radius:
            continue
        relevant_widths.append(width["object_id"])
        if "pixel_center_envelope_radius_range_px" not in width:
            unknown_widths.append(width["object_id"])
            continue
        distances, _, _ = _distance_projection(pixels, other)
        lower_radius, upper_radius = width["pixel_center_envelope_radius_range_px"]
        margins = np.minimum(margins, distances - upper_radius)
        explanations.append({"object_id": other["object_id"],
                             "radius_interval_px": [lower_radius, upper_radius],
                             "pixels_inside_upper_envelope": pixels[distances <= upper_radius].tolist(),
                             "pixels_inside_lower_envelope": pixels[distances <= lower_radius].tolist()})
    unsupported_nearby = []
    for other in nearby:
        distance = _bbox_distance(point, other.get("bbox_xyxy"))
        unknown_extent = other.get("coverage_valid") is not True or distance is None
        if not other["audit_supported"] and (unknown_extent or distance <= radius):
            unsupported_nearby.append({"object_id": other["object_id"],
                                       "bbox_xyxy": other.get("bbox_xyxy"),
                                       "bbox_scope": other.get("bbox_scope"),
                                       "coverage_valid": other.get("coverage_valid") is True,
                                       "extent_status": "UNKNOWN_EXTENT_UNSUPPORTED_CONTEXT" if unknown_extent
                                       else "CERTIFIED_BBOX_INTERSECTS_LOCAL_WINDOW",
                                       "reasons": other["audit_unsupported_reasons"]})
    outside = margins > 0
    groups = _residual_groups(pixels[outside], margins[outside], point, outward)
    if not components4:
        status = "SOURCE_UNRESOLVED_APPROACH_HAS_NO_ORIGINAL_INK"
    elif any(row["observation"] == "OBSERVABLE_UNASSIGNED_CONTINUATION" for row in groups):
        status = "OBSERVABLE_UNASSIGNED_CONTINUATION"
    elif groups:
        status = "SOURCE_BOUNDARY_COMPETITION"
    else:
        status = "CAP_OR_JUNCTION_COMPATIBLE"
    reasons = []
    if clipped:
        reasons.append("LOCAL_SOURCE_WINDOW_CLIPPED")
    if result["only_8_connected_ink_pixels"]:
        reasons.append("RAW_CORNER_ONLY_CONNECTION")
    if unknown_widths:
        reasons.append("RELEVANT_CONTEXT_WIDTH_NOT_MEASURED")
    if unsupported_nearby:
        reasons.append("RELEVANT_UNSUPPORTED_GEOMETRY")
    result.update(observation=status, status=status if not reasons else "SOURCE_UNRESOLVED_LIMITED_CONTEXT",
                  unresolved_reasons=reasons, measured_finite_envelope_explanations=explanations,
                  relevant_context_width_ids=relevant_widths,
                  context_width_unresolved_ids=unknown_widths,
                  relevant_unsupported_geometries=unsupported_nearby, unassigned_source_groups=groups,
                  original_ink_pixel_ownership_proved=False)
    return result


def _declarations(source, declarations, geometries, contacts):
    by_id = {row["object_id"]: row for row in geometries}
    result = []
    for declaration in declarations:
        guest = declaration.get("guest", declaration.get("guest_id"))
        host = declaration.get("host", declaration.get("host_id"))
        end = declaration.get("end", declaration.get("end_index"))
        row = {"declaration": dict(declaration), "used_as_truth": False}
        geometry = by_id.get(str(guest))
        if geometry is None or end not in (0, 1, -1) or not geometry["points"]:
            result.append({**row, "status": "SOURCE_UNRESOLVED_INVALID_DECLARATION"})
            continue
        index = 0 if end == 0 else -1
        point = geometry["points"][index]
        hosts = {g["object_id"] for g in geometries
                 if g["object_id"] == str(host) or g.get("parent_object_id") == str(host)}
        matches = [hit for hit in contacts if str(guest) in hit["object_ids"]
                   and (set(hit["object_ids"]) - {str(guest)}) & hosts and hit["point_px"] == point]
        near = []
        for host_id in sorted(hosts):
            other = by_id[host_id]
            if other["audit_supported"]:
                distances, _, _ = _distance_projection([point], other)
                near.append({"host_id": host_id, "finite_distance_px": float(distances[0])})
        result.append({**row, "actual_guest_endpoint_px": point,
                       "actual_endpoint_source": source.point(point),
                       "independently_observed_endpoint_contacts": matches,
                       "finite_host_distance_diagnostics": near,
                       "status": "EXACT_ENDPOINT_CONTACT_OBSERVED" if matches
                       else "SOURCE_UNRESOLVED_DECLARED_CONTACT_NOT_EXACTLY_OBSERVED"})
    return result


def audit_raw_source_responsibility(gray, geometries, *, roi_xyxy,
                                    source_origin_xy=(0, 0), attachment_declarations=(),
                                    source_identity=None, target_object_ids=None):
    """Audit actual finite geometry against this invocation's original pixels.

    ``points`` are in source pixel-center coordinates. ``source_origin_xy`` is
    the global center coordinate of array element [0, 0]. ROI bounds are integer
    half-open pixel indices. Target selection is evaluation scope only.
    """
    gray = np.asarray(gray)
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("RAW_AUDIT_REQUIRES_ORIGINAL_UINT8_GRAY_ARRAY")
    roi = tuple(roi_xyxy)
    origin = tuple(source_origin_xy)
    if (len(roi) != 4 or len(origin) != 2
            or any(not isinstance(value, int) for value in (*roi, *origin))):
        raise ValueError("RAW_AUDIT_ROI_AND_ORIGIN_MUST_BE_INTEGER_SOURCE_PIXEL_INDICES")
    x0, y0, x1, y1 = roi
    if not (origin[0] <= x0 < x1 <= origin[0] + gray.shape[1]
            and origin[1] <= y0 < y1 <= origin[1] + gray.shape[0]):
        raise ValueError("RAW_AUDIT_ROI_OUTSIDE_SUPPLIED_SOURCE")
    if (x1 - x0) * (y1 - y0) > POLICY["maximum_roi_pixels"]:
        raise ValueError("RAW_AUDIT_ROI_RESOURCE_LIMIT_NO_PARTIAL_PASS")
    geometries = [_normalise_geometry(row) for row in geometries]
    if len({row["object_id"] for row in geometries}) != len(geometries):
        raise ValueError("RAW_AUDIT_DUPLICATE_OBJECT_ID")
    targets = ({row["object_id"] for row in geometries} if target_object_ids is None
               else set(map(str, target_object_ids)))
    if not targets <= {row["object_id"] for row in geometries}:
        raise ValueError("RAW_AUDIT_UNKNOWN_TARGET_OBJECT_ID")
    if (len(targets) > POLICY["maximum_target_objects"]
            or len(geometries) > POLICY["maximum_context_objects"]):
        raise ValueError("RAW_AUDIT_GEOMETRY_RESOURCE_LIMIT_NO_PARTIAL_PASS")
    geometries.sort(key=lambda row: row["object_id"])
    source = _Source(gray, roi, origin)
    support = [_support(source, row) if row["audit_supported"] else {
        "object_id": row["object_id"], "status": "SOURCE_UNRESOLVED_UNSUPPORTED_GEOMETRY",
        "reasons": row["audit_unsupported_reasons"]}
               for row in geometries if row["object_id"] in targets]
    contacts, overlaps = _pair_evidence(source, geometries, targets)
    endpoints = [_endpoint(source, row, end, geometries)
                 for row in geometries if row["object_id"] in targets and row["audit_supported"]
                 and not row.get("closed") for end in (0, 1)]
    declarations = _declarations(source, attachment_declarations, geometries, contacts)
    reject = [row["status"] for row in [*support, *contacts, *overlaps]
              if row["status"].startswith("HARD_REJECT")]
    unresolved = [row["status"] for row in [*support, *contacts, *endpoints, *declarations]
                  if row["status"].startswith("SOURCE_")
                  or row["status"] == "OBSERVABLE_UNASSIGNED_CONTINUATION"]
    status = "HARD_REJECT" if reject else ("SOURCE_UNRESOLVED" if unresolved
                                          else "COMPATIBLE_UNDER_LIMITED_RAW_MODEL")
    return {"schema": SCHEMA, "policy": POLICY.copy(), "policy_sha256": _digest(POLICY),
            "source_binding": {"array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                               "array_shape": list(gray.shape), "array_dtype": str(gray.dtype),
                               "source_origin_xy": list(origin), "roi_xyxy": list(roi),
                               "evaluation_ink_sha256": hashlib.sha256(source.ink.tobytes()).hexdigest(),
                               "provided_source_identity": source_identity},
            "geometry_input_sha256": _digest(geometries), "target_object_ids": sorted(targets),
            "geometry_support": support, "pair_contacts": contacts,
            "positive_length_overlaps": overlaps, "white_holes": _white_holes(source),
            "endpoints": endpoints, "attachment_declaration_checks": declarations,
            "summary": {"status": status, "hard_reject_reasons": dict(Counter(reject)),
                        "unresolved_reasons": dict(Counter(unresolved)),
                        "endpoint_observations": dict(Counter(row.get("observation", row["status"])
                                                              for row in endpoints)),
                        "independent_source_ownership_proved": False,
                        "may_adopt_objects_from_this_report_alone": False},
            "limitations": LIMITATIONS}
