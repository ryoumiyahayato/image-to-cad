"""Complete numeric labels with independently measured native frame edges.

This module consumes the automatic text-region contract and original source
pixels.  It never reads fixed review cases, expected strings or drawing-specific
coordinates.  A ROOM_LABEL is one observed frame plus one unchanged numeric
TEXT.  Its exporter must use a distinct BLOCK definition for each instance so
editing a room number cannot alter another instance.

All positions are native source pixels (x right, y down).  ``frame_points`` has
four distinct cyclic vertices and ``frame_closed`` is True. ``text_geometry.y``
is the source-pixel bottom/baseline proxy, not the top of the OCR box.  This is a
geometric text-layout proposal; font metrics and CAD readback are downstream.
"""

from __future__ import annotations

import hashlib
import math
import copy
from pathlib import Path
import time

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from .contracts import (
    COORDINATES,
    TOLERANCES,
    save_json,
    stable_id,
    validate_text_regions,
)
from .geometry import samples, source_support


POLICY = {
    "version": "complete-numeric-frame-assembly-v2-bounded-source-direction",
    "source_threshold": 128,
    "source_line_perpendicular_px": TOLERANCES["line_perpendicular_px"],
    "source_corner_displacement_px": TOLERANCES["line_endpoint_px"],
    "direction_change_deg": TOLERANCES["max_direction_adjustment_deg"],
    "minimum_supported_fraction": 0.98,
    "maximum_white_gap_px": TOLERANCES["max_unexplained_line_gap_px"],
    "source_sampling_step_px": 0.5,
    "geometry_editing_scope": "complete frame and its unchanged numeric text only",
    "numeric_without_complete_frame": "DEFER_WHOLE_GROUP_NO_ORPHAN_TEXT",
    "block_policy": "ONE_UNIQUE_BLOCK_DEFINITION_PER_ROOM_LABEL_INSTANCE",
    "automatic_formal_adoption": False,
    "direction_seed": "original_source_LSD_edge_not_quantized_polygon_corner_chord",
    "source_direction_discovery_corridor_px": 4.0,
    "minimum_source_direction_span_fraction": 0.50,
    "source_profile_normal_shift_bound_px": 3.5,
    "profile_optimizer": "finite_exact_2D_bounded_least_squares",
    "frame_edit_responsibility_version": "whole-frame-with-retained-source-endpoints-v1",
}


def _box_valid(box, shape):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if not all(math.isfinite(float(v)) for v in box):
        return False
    x0, y0, x1, y1 = map(float, box)
    return 0 <= x0 < x1 <= shape[1] and 0 <= y0 < y1 <= shape[0]


def _inside(box, roi):
    return (
        box[0] >= roi[0] and box[1] >= roi[1] and box[2] <= roi[2] and box[3] <= roi[3]
    )


def _ordered_corners(raw):
    """Order the supplied source contour; no orthogonal snapping or boxing."""
    pts = np.asarray(raw, dtype=float)
    if pts.shape != (4, 2) or not np.isfinite(pts).all():
        return None
    if len({tuple(p) for p in pts}) != 4:
        return None
    centre = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    pts = pts[np.argsort(angles, kind="stable")]
    start = min(range(4), key=lambda i: (pts[i, 1], pts[i, 0]))
    pts = np.roll(pts, -start, axis=0)
    if not cv2.isContourConvex(pts.astype(np.float32)):
        return None
    return pts


def _intersection(first, second):
    a, b = first
    c, d = second
    u, v = b - a, d - c
    determinant = float(u[0] * v[1] - u[1] * v[0])
    if abs(determinant) <= 1e-10 * max(
        1.0, float(np.linalg.norm(u) * np.linalg.norm(v))
    ):
        return None
    w = c - a
    t = float((w[0] * v[1] - w[1] * v[0]) / determinant)
    return a + t * u


def _source_profile(a, b, crop, origin):
    """Unchanged original fitter's source-profile search and run conditions."""
    length = float(np.linalg.norm(b - a))
    u = (b - a) / length
    n = np.array([-u[1], u[0]])
    p = samples(a, b, 2)
    offsets = np.arange(-4.0, 4.01, 0.5)
    q = p[:, None, :] + offsets[None, :, None] * n
    ink = (
        map_coordinates(
            crop,
            [q[:, :, 1] - origin[1], q[:, :, 0] - origin[0]],
            order=0,
            mode="constant",
            cval=255,
        )
        < 128
    )
    centres, widths = [], []
    for point, row in zip(p, ink):
        diff = np.diff(np.r_[False, row, False].astype(int))
        starts, ends = np.flatnonzero(diff == 1), np.flatnonzero(diff == -1)
        runs = [(lo, hi) for lo, hi in zip(starts, ends) if 0 < hi - lo < 12]
        if not runs:
            continue
        lo, hi = min(runs, key=lambda r: abs((offsets[r[0]] + offsets[r[1] - 1]) / 2))
        shift = float((offsets[lo] + offsets[hi - 1]) / 2)
        if abs(shift) > POLICY["source_profile_normal_shift_bound_px"]:
            continue
        centres.append(point + shift * n)
        widths.append(float((hi - lo) * 0.5))
    evidence = {
        "sample_count": len(p),
        "supported_profile_count": len(centres),
        "minimum_supported_profile_fraction": 0.8,
        "normal_search_px": [-4.0, 4.0],
        "normal_step_px": 0.5,
        "accepted_normal_shift_bound_px": POLICY[
            "source_profile_normal_shift_bound_px"
        ],
        "source_centres_xy_px": [v.tolist() for v in centres],
        "source_width_samples_px": widths,
    }
    if len(centres) < 0.8 * len(p):
        return None, evidence, "ambiguous_cross_section"
    c = np.asarray(centres)
    t = (c - a) @ u
    z = (c - a) @ n
    if np.ptp(t) < 1:
        return None, evidence, "insufficient_span"
    return (t, z, widths, u, n, length), evidence, "ok"


def _bounded_regression(t, z, length):
    """Solve the two-parameter convex LS problem on its exact feasible polygon.

    Parameters are start normal offset b and accumulated normal change q.
    |atan(q/length)| <= 0.5 degrees, |b| <= 3.5 px, |b+q| <= 3.5 px.
    Each polygon edge has a closed-form one-dimensional least-squares minimum;
    there is no iterative solver, threshold retry or unconstrained PASS override.
    """
    design = np.column_stack((np.ones(len(t)), t / length))
    raw = np.linalg.lstsq(design, z, rcond=None)[0]
    shift = POLICY["source_profile_normal_shift_bound_px"]
    qbound = np.nextafter(
        length * math.tan(math.radians(POLICY["direction_change_deg"])), 0.0
    )
    normals = np.array(
        [[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0], [1.0, 1.0], [-1.0, -1.0]]
    )
    limits = np.array([shift, shift, qbound, qbound, shift, shift])
    arithmetic_eps = 64 * np.finfo(float).eps * max(1.0, shift, qbound)

    def feasible(v):
        return bool(np.all(normals @ v <= limits + arithmetic_eps))

    vertices = []
    for i in range(len(normals)):
        for j in range(i + 1, len(normals)):
            matrix = normals[[i, j]]
            if abs(float(np.linalg.det(matrix))) < 0.5:
                continue
            v = np.linalg.solve(matrix, limits[[i, j]])
            if feasible(v) and not any(
                np.linalg.norm(v - w) <= arithmetic_eps for w in vertices
            ):
                vertices.append(v)
    choices = [(v, "feasible_polygon_vertex") for v in vertices]
    if feasible(raw):
        choices.append((raw, "unconstrained_optimum_is_feasible"))
    for n, bound in zip(normals, limits):
        on = [v for v in vertices if abs(float(n @ v) - bound) <= arithmetic_eps]
        if len(on) < 2:
            continue
        direction = np.array([-n[1], n[0]])
        on.sort(key=lambda v: float(v @ direction))
        first, last = on[0], on[-1]
        delta = last - first
        dz = design @ delta
        denominator = float(dz @ dz)
        if denominator <= 0:
            continue
        fraction = float(np.clip(-((design @ first - z) @ dz) / denominator, 0.0, 1.0))
        choices.append((first + fraction * delta, "constrained_boundary_optimum"))
    if not choices:
        raise AssertionError("EMPTY_FRAME_PROFILE_FEASIBLE_DOMAIN")
    optimum, method = min(
        choices,
        key=lambda item: (
            float(np.sum((design @ item[0] - z) ** 2)),
            item[1],
            item[0].tolist(),
        ),
    )
    # Numerical arithmetic is reported separately; it never changes 0.5 deg.
    if not feasible(optimum):
        raise AssertionError("BOUNDED_FRAME_OPTIMUM_OUTSIDE_DOMAIN")

    def metrics(v):
        residual = np.abs(design @ v - z)
        return {
            "start_normal_offset_px": float(v[0]),
            "end_normal_offset_px": float(v[0] + v[1]),
            "slope": float(v[1] / length),
            "direction_correction_deg": math.degrees(math.atan(float(v[1] / length))),
            "sum_squared_residual_px2": float(np.sum(residual**2)),
            "rms_normal_residual_px": float(np.sqrt(np.mean(residual**2))),
            "p95_normal_residual_px": float(np.quantile(residual, 0.95)),
            "max_normal_residual_px": float(residual.max()),
        }

    report = {
        "method": method,
        "unconstrained": metrics(raw),
        "constrained": metrics(optimum),
        "unconstrained_within_same_domain": feasible(raw),
        "maximum_direction_correction_deg": POLICY["direction_change_deg"],
        "maximum_endpoint_normal_offset_px": shift,
        "feasible_polygon_vertices": [v.tolist() for v in vertices],
        "optimization_candidates_evaluated": len(choices),
        "arithmetic_epsilon": arithmetic_eps,
        "acceptance_tolerances_changed": False,
    }
    return optimum, report


def _fit_frame_source_bounded(a, b, crop, origin):
    if float(np.linalg.norm(b - a)) < 8:
        return (
            None,
            "below_detector_resolution",
            {"source_profile": {"minimum_existing_fitter_length_px": 8}},
        )
    profile, evidence, status = _source_profile(a, b, crop, origin)
    if profile is None:
        return None, status, {"source_profile": evidence}
    t, z, widths, u, n, length = profile
    optimum, regression = _bounded_regression(t, z, length)
    evidence = {"source_profile": evidence, "profile_regression": regression}
    constrained = regression["constrained"]
    if abs(constrained["direction_correction_deg"]) > POLICY["direction_change_deg"]:
        return None, "direction_change_exceeds_bound", evidence
    if constrained["p95_normal_residual_px"] > 2:
        return None, "nonstraight_source", evidence
    return (
        (
            a + optimum[0] * n,
            b + (optimum[0] + optimum[1]) * n,
            float(np.median(widths)),
        ),
        "ok",
        evidence,
    )


def _source_sideband_direction(raw_a, raw_b, crop, origin):
    """Robust direction from actual source-profile centres when LSD lacks span."""
    length = float(np.linalg.norm(raw_b - raw_a))
    u = (raw_b - raw_a) / length
    inset = min(4.0, length * 0.10)
    a = raw_a + inset * u
    b = raw_b - inset * u
    profile, evidence, status = _source_profile(a, b, crop, origin)
    report = {
        "method": "robust_pairwise_slope_of_original_source_sideband_centres",
        "source_profile": evidence,
        "profile_status": status,
        "source_pixels_modified": False,
    }
    if profile is None:
        return None, report
    t, z, widths, u, n, span = profile
    first, last = np.triu_indices(len(t), 1)
    delta = t[last] - t[first]
    valid = np.abs(delta) > 1e-12
    if not np.any(valid):
        return None, report
    slope = float(np.median((z[last[valid]] - z[first[valid]]) / delta[valid]))
    offset = float(np.median(z - slope * t))
    direction = u + slope * n
    direction /= np.linalg.norm(direction)
    seed_a = a + offset * n
    seed_b = b + (offset + slope * span) * n
    observed = np.asarray(evidence["source_centres_xy_px"])
    projections = (observed - seed_a) @ direction
    report.update(
        source_seed_points=[seed_a.tolist(), seed_b.tolist()],
        source_direction=direction.tolist(),
        contour_chord_to_source_direction_deg=math.degrees(math.atan(slope)),
        observed_source_projection_interval_px=[
            float(projections.min()),
            float(projections.max()),
        ],
        source_width_px=float(np.median(widths)),
        source_direction_is_initial_detection_not_angle_gate_override=True,
    )
    return (seed_a, seed_b), report


def _source_direction_seed(raw_a, raw_b, detected, origin, crop):
    """Select one source detector direction before profile fitting/gating.

    Polygon corners locate a side, but raster rounding and rounded corners do
    not measure its direction. This uses raw LSD on the unmodified local source
    crop, as the line detector does. Selection is deterministic by observed
    span, then discovery distance; it never selects according to a later PASS.
    The unchanged 0.5 degree correction gate applies to this source direction.
    """
    direction = raw_b - raw_a
    length = float(np.linalg.norm(direction))
    unit = direction / length
    normal = np.array([-unit[1], unit[0]])
    candidates = []
    for detector_index, row in enumerate(detected):
        a = np.asarray(row[:2], dtype=float) + origin
        b = np.asarray(row[2:], dtype=float) + origin
        detected_length = float(np.linalg.norm(b - a))
        if detected_length < 12:
            continue
        v = (b - a) / detected_length
        if float(v @ unit) < 0:
            a, b, v = b, a, -v
        # A corridor is only a discovery/association bound, not a source gate.
        deviation = max(
            abs(float((a - raw_a) @ normal)), abs(float((b - raw_a) @ normal))
        )
        if deviation > POLICY["source_direction_discovery_corridor_px"]:
            continue
        lo, hi = sorted((float((a - raw_a) @ unit), float((b - raw_a) @ unit)))
        overlap = max(0.0, min(length, hi) - max(0.0, lo))
        if overlap < POLICY["minimum_source_direction_span_fraction"] * length:
            continue
        # Side candidates may not run on through another part of the drawing.
        if max(0.0, -lo, hi - length) > POLICY["source_corner_displacement_px"]:
            continue
        delta = math.degrees(math.acos(float(np.clip(unit @ v, -1.0, 1.0))))
        candidates.append(
            {
                "detector_index": detector_index,
                "source_start": a.tolist(),
                "source_end": b.tolist(),
                "source_direction": v.tolist(),
                "observed_overlap_px": overlap,
                "discovery_normal_distance_px": deviation,
                "contour_chord_to_source_direction_deg": delta,
                "raw_detector_length_px": detected_length,
            }
        )
    candidates.sort(
        key=lambda c: (
            -c["observed_overlap_px"],
            c["discovery_normal_distance_px"],
            c["source_start"],
            c["source_end"],
        )
    )
    evidence = {
        "method": "LSD_REFINE_STD_on_original_local_source_crop",
        "matching_source_directions": candidates,
        "selection_uses_later_fit_result": False,
        "direction_correction_gate_reference": "selected_raw_source_LSD_direction",
    }
    if not candidates:
        fallback, fallback_evidence = _source_sideband_direction(
            raw_a, raw_b, crop, origin
        )
        evidence["source_sideband_fallback"] = fallback_evidence
        if fallback is not None:
            evidence["direction_correction_gate_reference"] = (
                "detected_original_source_sideband_direction"
            )
            evidence["profile_seed_points"] = [p.tolist() for p in fallback]
        return fallback, evidence
    selected = candidates[0]
    a, b = np.asarray(selected["source_start"]), np.asarray(selected["source_end"])
    v = np.asarray(selected["source_direction"])
    centre = (a + b) / 2
    inset = min(4.0, length * 0.10)
    first = raw_a + inset * unit
    last = raw_b - inset * unit
    seed_a = centre + float((first - centre) @ v) * v
    seed_b = centre + float((last - centre) @ v) * v
    evidence.update(
        selected=selected, profile_seed_points=[seed_a.tolist(), seed_b.tolist()]
    )
    return (seed_a, seed_b), evidence


def _measure_frame(gray, roi, enclosure, text_box):
    """Fit each observed edge in its own narrow source corridor and check all.

    The four contour points are discovery seeds, not a reference answer.
    Source-centre fitting uses the same frozen line fitting bounds as the line
    module. Corner joins are finite line intersections and must stay within
    the existing 3 px endpoint bound; all final edges also pass dense source
    support with maximum distance <= 2 px. No missing edge is inferred.
    """
    report = {"discovery_enclosure": enclosure, "edges": [], "rejection_reasons": []}
    box = enclosure.get("enclosure_bbox_xyxy_px")
    if not _box_valid(box, gray.shape) or not _inside(box, roi):
        report["rejection_reasons"].append("ENCLOSURE_INVALID_OR_CROSSES_ROI")
        return None, report
    raw = _ordered_corners(enclosure.get("contour_points_xy_px", []))
    if raw is None:
        report["rejection_reasons"].append(
            "FOUR_CONVEX_SOURCE_CONTOUR_CORNERS_REQUIRED"
        )
        return None, report
    if not all(
        box[0] - 1 <= p[0] < box[2] + 1 and box[1] - 1 <= p[1] < box[3] + 1 for p in raw
    ):
        report["rejection_reasons"].append("CONTOUR_OUTSIDE_ITS_SOURCE_ENCLOSURE")
        return None, report
    pad = 8
    x0 = max(0, int(math.floor(min(raw[:, 0]))) - pad)
    y0 = max(0, int(math.floor(min(raw[:, 1]))) - pad)
    x1 = min(gray.shape[1], int(math.ceil(max(raw[:, 0]))) + pad + 1)
    y1 = min(gray.shape[0], int(math.ceil(max(raw[:, 1]))) + pad + 1)
    crop = np.asarray(gray[y0:y1, x0:x1], dtype=np.uint8)
    origin = np.array([x0, y0], dtype=float)
    distance = cv2.distanceTransform(
        (crop >= POLICY["source_threshold"]).astype(np.uint8),
        cv2.DIST_L2,
        cv2.DIST_MASK_PRECISE,
    )
    raw_detected = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(crop)[0]
    detected = [] if raw_detected is None else raw_detected.reshape(-1, 4)
    report.update(
        source_crop_xyxy_px=[x0, y0, x1, y1],
        source_crop_array_sha256=hashlib.sha256(crop.tobytes()).hexdigest(),
        ordered_discovery_corners=raw.tolist(),
        source_pixels_modified=False,
        source_profile_policy="original grayscale cross-sections; no rule erasure",
        raw_local_source_LSD_segments=len(detected),
        direction_initialization="source_LSD_direction; contour_only_locates_side",
    )
    fitted = []
    for index in range(4):
        a, b = raw[index], raw[(index + 1) % 4]
        length = float(np.linalg.norm(b - a))
        if length < 12:
            report["rejection_reasons"].append(
                "FRAME_SIDE_TOO_SHORT_FOR_EXISTING_SOURCE_FITTER"
            )
            return None, report
        # Corners contain the perpendicular neighbour. They must not bias a
        # straight side's width or normal centre; final corners are rechecked.
        inset = min(4.0, length * 0.10)
        seed, seed_evidence = _source_direction_seed(a, b, detected, origin, crop)
        if seed is None:
            report["edges"].append(
                {
                    "index": index,
                    "discovery_start": a.tolist(),
                    "discovery_end": b.tolist(),
                    "direction_discovery": seed_evidence,
                    "fit_status": "no_source_detector_direction",
                }
            )
            report["rejection_reasons"].append(
                "NO_SOURCE_DETECTOR_DIRECTION_FOR_FRAME_SIDE"
            )
            return None, report
        aa, bb = seed
        fit, reason, fit_evidence = _fit_frame_source_bounded(aa, bb, crop, origin)
        edge = {
            "index": index,
            "discovery_start": a.tolist(),
            "discovery_end": b.tolist(),
            "profile_end_inset_px": inset,
            "fit_status": reason,
            "direction_discovery": seed_evidence,
            "bounded_source_profile_fit": fit_evidence,
        }
        report["edges"].append(edge)
        if fit is None:
            report["rejection_reasons"].append("SOURCE_FRAME_SIDE_FIT_FAILED:" + reason)
            return None, report
        fa, fb, width = fit
        fitted.append((np.asarray(fa), np.asarray(fb)))
        edge.update(
            fitted_support_line=[fa.tolist(), fb.tolist()], source_width_px=float(width)
        )
        su = (bb - aa) / np.linalg.norm(bb - aa)
        fu = (fb - fa) / np.linalg.norm(fb - fa)
        edge["source_detector_to_final_direction_deg"] = math.degrees(
            math.acos(float(np.clip(su @ fu, -1.0, 1.0)))
        )
    corners = []
    for index in range(4):
        p = _intersection(fitted[(index - 1) % 4], fitted[index])
        if p is None or not np.isfinite(p).all():
            report["rejection_reasons"].append(
                "FRAME_ADJACENT_EDGES_DO_NOT_FORM_FINITE_CORNER"
            )
            return None, report
        corners.append(p)
    corners = np.asarray(corners)
    displacements = np.linalg.norm(corners - raw, axis=1)
    report["corner_source_displacement_px"] = displacements.tolist()
    if float(displacements.max()) > POLICY["source_corner_displacement_px"]:
        report["rejection_reasons"].append(
            "FRAME_CORNER_EXCEEDS_EXISTING_ENDPOINT_BOUND"
        )
    if not cv2.isContourConvex(corners.astype(np.float32)):
        report["rejection_reasons"].append("FITTED_FRAME_NOT_CONVEX")
    if not all(roi[0] <= p[0] <= roi[2] and roi[1] <= p[1] <= roi[3] for p in corners):
        report["rejection_reasons"].append("FITTED_FRAME_CROSSES_ROI")
    for index in range(4):
        support = source_support(
            corners[index],
            corners[(index + 1) % 4],
            distance,
            origin,
            POLICY["source_sampling_step_px"],
        )
        report["edges"][index]["final_support"] = support
        if (
            support["supported_fraction"] < POLICY["minimum_supported_fraction"]
            or support["max_distance_px"] > POLICY["source_line_perpendicular_px"]
            or support["maximum_white_gap_px"] > POLICY["maximum_white_gap_px"]
        ):
            report["rejection_reasons"].append(
                "FRAME_EDGE_LACKS_CONTINUOUS_SOURCE_SUPPORT"
            )
    if not _box_valid(text_box, gray.shape):
        report["rejection_reasons"].append("TEXT_BOX_INVALID")
    else:
        tx0, ty0, tx1, ty1 = map(float, text_box)
        clearances = [
            float(cv2.pointPolygonTest(corners.astype(np.float32), p, True))
            for p in [(tx0, ty0), (tx1, ty0), (tx1, ty1), (tx0, ty1)]
        ]
        report["text_bbox_corner_clearance_px"] = clearances
        if min(clearances) < 1.0:
            report["rejection_reasons"].append(
                "TEXT_BOX_NOT_SAFELY_INSIDE_MEASURED_FRAME"
            )
    report["rejection_reasons"] = sorted(set(report["rejection_reasons"]))
    report["final_frame_points"] = corners.tolist()
    return (None if report["rejection_reasons"] else corners), report


def _match_frame_lines(corners, lines):
    """Consume only complete candidate segments contained in a frame side.

    A line crossing a corner and continuing farther than the frozen endpoint
    bound is retained in full and prevents adoption of this label. Splitting or
    erasing a possible neighbouring wall/leader is outside this module's scope.
    """
    consumed, contacts, conflicts = [], [], []
    direction_cos = math.cos(math.radians(POLICY["direction_change_deg"]))
    for candidate in lines:
        if candidate.get("kind") != "LINE":
            continue
        geometry = candidate.get("geometry", {})
        a = np.asarray(geometry.get("start", []), dtype=float)
        b = np.asarray(geometry.get("end", []), dtype=float)
        if a.shape != (2,) or b.shape != (2,) or not np.isfinite(np.r_[a, b]).all():
            raise ValueError(
                "ANNOTATION_LINE_GEOMETRY_CONTRACT_INVALID:" + str(candidate.get("id"))
            )
        length = float(np.linalg.norm(b - a))
        if length <= 0:
            raise ValueError("ANNOTATION_ZERO_LENGTH_LINE:" + str(candidate.get("id")))
        v = (b - a) / length
        matches = []
        for index in range(4):
            p, q = corners[index], corners[(index + 1) % 4]
            side_length = float(np.linalg.norm(q - p))
            unit = (q - p) / side_length
            if abs(float(unit @ v)) < direction_cos:
                continue
            normal = np.array([-unit[1], unit[0]])
            deviation = max(abs(float((a - p) @ normal)), abs(float((b - p) @ normal)))
            if deviation > POLICY["source_line_perpendicular_px"]:
                continue
            lo, hi = sorted([float((a - p) @ unit), float((b - p) @ unit)])
            overlap = max(0.0, min(side_length, hi) - max(0.0, lo))
            if overlap <= 0:
                continue
            overhang = max(0.0, -lo, hi - side_length)
            matches.append(
                {
                    "line_id": candidate["id"],
                    "frame_side_index": index,
                    "normal_deviation_px": deviation,
                    "projection_interval_px": [lo, hi],
                    "frame_side_length_px": side_length,
                    "overlap_px": overlap,
                    "maximum_endpoint_overhang_px": overhang,
                    "source_line_length_px": length,
                    "retired_source_line_interval_px": [
                        max(0.0, min(float((p - a) @ v), float((q - a) @ v))),
                        min(length, max(float((p - a) @ v), float((q - a) @ v))),
                    ],
                    "endpoint_tolerance_is_not_deletion_permission": True,
                }
            )
        if not matches:
            continue
        match = min(
            matches,
            key=lambda r: (
                r["normal_deviation_px"],
                -r["overlap_px"],
                r["frame_side_index"],
            ),
        )
        if (
            match["maximum_endpoint_overhang_px"]
            > POLICY["source_corner_displacement_px"]
        ):
            match["decision"] = "RETAIN_LINE_CONTINUING_BEYOND_FRAME_CORNERS"
            conflicts.append(candidate["id"])
        else:
            match["decision"] = "CONSUME_COMPLETE_FRAME_EDGE_DUPLICATE"
            consumed.append(candidate["id"])
        contacts.append(match)
    return consumed, contacts, conflicts


def _frame_line_remainders(lines, adopted_contacts):
    """Preserve all endpoint excess instead of using the 3 px gate to erase it."""
    claims = {}
    for contact in adopted_contacts:
        if contact["decision"] != "CONSUME_COMPLETE_FRAME_EDGE_DUPLICATE":
            continue
        claims.setdefault(contact["line_id"], []).append(
            contact["retired_source_line_interval_px"]
        )
    kept, ledger, fully_retired = [], [], []
    for line in lines:
        if line["id"] not in claims:
            kept.append(line)
            continue
        a = np.asarray(line["geometry"]["start"], dtype=float)
        b = np.asarray(line["geometry"]["end"], dtype=float)
        length = float(np.linalg.norm(b - a))
        unit = (b - a) / length
        eps = max(1e-12, 64 * math.ulp(max(1.0, length)))
        merged = []
        for lo, hi in sorted(claims[line["id"]]):
            if lo < -eps or hi > length + eps or hi < lo:
                raise ValueError("FRAME_INTERVAL_OUTSIDE_SOURCE_LINE")
            lo, hi = max(0.0, lo), min(length, hi)
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
            else:
                merged.append((lo, hi))
        spans, numerical, last = [], [], 0.0
        for lo, hi in merged:
            if lo > last:
                (spans if lo - last > eps else numerical).append((last, lo))
            last = max(last, hi)
        if length > last:
            (spans if length - last > eps else numerical).append((last, length))
        for lo, hi in spans:
            geometry = {
                "start": (a + lo * unit).tolist(),
                "end": (a + hi * unit).tolist(),
            }
            kept.append(
                {
                    **line,
                    "id": stable_id("ANNOTATION_REMAIN", geometry),
                    "geometry": geometry,
                    "source_evidence": {
                        **line.get("source_evidence", {}),
                        "parent_line_id": line["id"],
                        "outside_frame_owned_interval_px": [lo, hi],
                        "positive_endpoint_excess_preserved": True,
                    },
                }
            )
        retired = math.fsum(hi - lo for lo, hi in merged)
        remaining = math.fsum(hi - lo for lo, hi in spans)
        floating = math.fsum(hi - lo for lo, hi in numerical)
        error = length - math.fsum((retired, remaining, floating))
        if abs(error) > eps * (len(merged) + len(spans) + 2):
            raise AssertionError("FRAME_LINE_LENGTH_NOT_CONSERVED")
        ledger.append(
            {
                "source_line_id": line["id"],
                "original_length_px": length,
                "frame_owned_intervals_px": merged,
                "retained_endpoint_intervals_px": spans,
                "frame_owned_union_length_px": retired,
                "retained_length_px": remaining,
                "floating_point_only_intervals_px": numerical,
                "numerical_epsilon_px": eps,
                "length_conservation_error_px": error,
                "all_source_parameter_intervals_accounted": True,
                "line_has_positive_endpoint_excess": bool(spans),
            }
        )
        if not spans:
            fully_retired.append(line["id"])
    return kept, ledger, fully_retired


def resolve_frame_edit_ownership(result, source_lines):
    """Bind existing measured geometry to a complete label's edit scope.

    This is a pure responsibility transfer: no source image, OCR, detector,
    fitter or renderer is called. Already retained endpoint LINE geometries
    become child members of their uniquely matched ROOM_LABEL. Proven frames
    with unresolved text retain their matched original LINEs in uncertainties,
    not as isolated formal fragments. Unmatched lines and long continuations
    are untouched. Applying the same resolved result twice is idempotent.
    """
    resolved = copy.deepcopy(result)
    version = POLICY["frame_edit_responsibility_version"]
    if resolved.get("frame_edit_responsibility", {}).get("version") == version:
        return resolved
    source_by = {o["id"]: o for o in source_lines}
    if len(source_by) != len(source_lines):
        raise ValueError("DUPLICATE_FRAME_SOURCE_LINE_IDS")
    owners = {}
    original_ids = {}
    for obj in resolved["objects"]:
        if obj.get("kind") != "ROOM_LABEL":
            continue
        original_ids[id(obj)] = obj["id"]
        obj["geometry"]["frame_source_remainders"] = []
        evidence = obj["source_evidence"]
        evidence.setdefault(
            "automatic_text_complete", bool(evidence.get("text_complete", False))
        )
        evidence.setdefault("source_review", False)
        for parent in evidence.get("consumed_frame_line_ids", []):
            if parent not in source_by:
                raise ValueError("FRAME_PARENT_LINE_NOT_IN_FROZEN_INPUT:" + parent)
            if parent in owners:
                raise ValueError("FRAME_PARENT_CLAIMED_BY_MULTIPLE_LABELS:" + parent)
            owners[parent] = obj
    partition_by = {
        p["source_line_id"]: p
        for p in resolved.get("frame_line_interval_partition", [])
    }
    kept = []
    attached = []
    for line in resolved["remaining_lines"]:
        evidence = line.get("source_evidence", {})
        parent = evidence.get("parent_line_id")
        interval = evidence.get("outside_frame_owned_interval_px")
        if not (
            parent in owners
            and evidence.get("positive_endpoint_excess_preserved")
            and interval is not None
        ):
            kept.append(line)
            continue
        partition = partition_by.get(parent)
        if partition is None or list(interval) not in [
            list(i) for i in partition["retained_endpoint_intervals_px"]
        ]:
            raise ValueError(
                "FRAME_ENDPOINT_LINE_HAS_NO_EXACT_INTERVAL_LEDGER:" + line["id"]
            )
        child = {
            "id": line["id"],
            "kind": "LINE",
            "geometry": copy.deepcopy(line["geometry"]),
            "parent_line_id": parent,
            "source_interval_px": list(interval),
            "role": "retained_original_frame_endpoint",
            "source_evidence": copy.deepcopy(evidence),
        }
        owners[parent]["geometry"]["frame_source_remainders"].append(child)
        attached.append(
            {
                "line_id": line["id"],
                "parent_line_id": parent,
                "text_group_id": owners[parent]["source_evidence"]["text_group_id"],
                "source_interval_px": list(interval),
                "original_geometry_preserved_exactly": True,
            }
        )
    resolved["remaining_lines"] = kept
    old_to_new = {}
    for obj in resolved["objects"]:
        if obj.get("kind") != "ROOM_LABEL":
            continue
        children = obj["geometry"]["frame_source_remainders"]
        children.sort(
            key=lambda m: (m["parent_line_id"], m["source_interval_px"], m["id"])
        )
        old = original_ids[id(obj)]
        geometry_identity = {
            "frame_points": obj["geometry"]["frame_points"],
            "frame_closed": True,
            "text_geometry": obj["geometry"]["text_geometry"],
            "frame_source_remainders": [m["geometry"] for m in children],
        }
        obj["id"] = stable_id("ROOM_LABEL", geometry_identity)
        old_to_new[old] = obj["id"]
        obj["source_evidence"]["geometry_proposal_id_before_responsibility"] = old
        obj["source_evidence"]["retained_endpoint_child_ids"] = [
            m["id"] for m in children
        ]
        obj["source_evidence"]["frame_edit_responsibility_version"] = version
        obj["editing_scope"] = (
            "measured closed frame, unchanged numeric TEXT, and all retained endpoints of uniquely matched frame source lines"
        )
        obj["expected_native_block_member_counts"] = {
            "closed_LWPOLYLINE": 1,
            "TEXT": 1,
            "retained_LINE": len(children),
            "total": 2 + len(children),
        }
    for decision in resolved.get("decisions", []):
        if decision.get("object_id") in old_to_new:
            decision["object_id"] = old_to_new[decision["object_id"]]
    for partition in resolved.get("frame_line_interval_partition", []):
        parent = partition["source_line_id"]
        if parent in owners:
            expected = sorted(
                [list(i) for i in partition["retained_endpoint_intervals_px"]]
            )
            actual = sorted(
                [
                    m["source_interval_px"]
                    for m in owners[parent]["geometry"]["frame_source_remainders"]
                    if m["parent_line_id"] == parent
                ]
            )
            if expected != actual:
                raise ValueError(
                    "FRAME_ENDPOINT_INTERVAL_NOT_OWNED_EXACTLY_ONCE:" + parent
                )
            partition["owner_ROOM_LABEL_id"] = owners[parent]["id"]
            partition["retained_endpoint_child_ids"] = [
                m["id"]
                for m in owners[parent]["geometry"]["frame_source_remainders"]
                if m["parent_line_id"] == parent
            ]
            partition["retained_endpoints_in_same_edit_scope"] = True
    decisions = {d["text_group_id"]: d for d in resolved.get("decisions", [])}
    uncertainties = {
        d["text_group_id"]: d
        for d in resolved.get("uncertainties", [])
        if d.get("text_group_id")
    }
    adopted_groups = {
        o["source_evidence"]["text_group_id"]
        for o in resolved["objects"]
        if o.get("kind") == "ROOM_LABEL"
    }
    pending_claims = {}
    deferred_records = []
    for frame in resolved.get("geometry_only_frame_candidates", []):
        if frame.get("automatic_text_complete", False):
            continue
        gid = frame["text_group_id"]
        decision = decisions.get(gid, {})
        if gid in adopted_groups:
            continue
        candidates = []
        withheld_ids = []
        skipped = []
        for contact in decision.get("frame_line_contacts", []):
            if contact["decision"] != "CONSUME_COMPLETE_FRAME_EDGE_DUPLICATE":
                continue
            parent = contact["line_id"]
            if parent in owners:
                skipped.append(
                    {
                        "line_id": parent,
                        "reason": "ALREADY_OWNED_BY_ADOPTED_LABEL_NOT_REASSIGNED",
                    }
                )
                continue
            if parent not in source_by:
                raise ValueError("DEFERRED_FRAME_PARENT_NOT_IN_FROZEN_INPUT:" + parent)
            pending_claims.setdefault(parent, []).append(gid)
            candidates.append(copy.deepcopy(source_by[parent]))
            withheld_ids.append(parent)
        frame["withheld_source_frame_line_candidates"] = candidates
        frame["withheld_source_frame_line_ids"] = withheld_ids
        frame["whole_label_deferred_together"] = True
        if gid in uncertainties:
            uncertainties[gid].update(
                geometry={
                    "frame_points": copy.deepcopy(frame["frame_points"]),
                    "frame_closed": True,
                },
                withheld_source_frame_line_candidates=copy.deepcopy(candidates),
                withheld_source_frame_line_ids=withheld_ids,
                whole_label_deferred_together=True,
                source_geometry_deleted=False,
                source_pixels_modified=False,
                unmatched_or_long_continuation_lines_withheld=False,
            )
        deferred_records.append(
            {
                "text_group_id": gid,
                "withheld_source_line_ids": withheld_ids,
                "skipped_conflicting_claims": skipped,
                "reason": "TEXT_UNRESOLVED_WHOLE_FRAME_PENDING",
            }
        )
    withheld = []
    remaining = []
    for line in resolved["remaining_lines"]:
        if line["id"] in pending_claims:
            if line["geometry"] != source_by[line["id"]]["geometry"]:
                raise ValueError(
                    "DEFERRED_FRAME_LINE_DIFFERS_FROM_FROZEN_SOURCE_CANDIDATE"
                )
            withheld.append(
                {
                    "line_id": line["id"],
                    "text_group_ids": pending_claims[line["id"]],
                    "original_geometry_preserved_exactly_in_uncertainties": True,
                }
            )
        else:
            remaining.append(line)
    resolved["remaining_lines"] = remaining
    resolved["frame_edit_responsibility"] = {
        "version": version,
        "method": "interval-ledger-based edit ownership transfer only",
        "source_geometry_recomputed": False,
        "OCR_recomputed": False,
        "source_pixels_modified": False,
        "adopted_frame_endpoint_members": attached,
        "whole_label_deferred_records": deferred_records,
        "withheld_formal_line_records": withheld,
        "object_id_map": old_to_new,
        "unmatched_short_lines_or_continuations_reassigned": False,
        "CAD_child_count_is_not_two": True,
    }
    resolved["counts"].update(
        remaining_lines=len(remaining),
        retained_endpoint_LINE_members_in_ROOM_blocks=len(attached),
        whole_label_deferred_source_lines=len(withheld),
        expected_ROOM_native_member_count=sum(
            o.get("expected_native_block_member_counts", {}).get("total", 0)
            for o in resolved["objects"]
        ),
    )
    return resolved


def assemble_annotations(gray, roi, text_data, lines, out):
    """Return ROOM_LABEL proposals and exact line/text ownership decisions.

    ``consumed_text_group_ids`` contains only adopted composite proposals.
    ``deferred_text_group_ids`` must also be withheld by the caller from normal
    standalone TEXT export. They remain unresolved review objects. No string
    changes, drawing-coordinate rules, source deletion or CAD writes occur.
    """
    started = time.perf_counter()
    validate_text_regions(text_data, gray.shape, roi)
    if not isinstance(text_data.get("groups"), list):
        raise ValueError("ANNOTATION_TEXT_GROUPS_LIST_MISSING")
    if not isinstance(lines, list):
        raise ValueError("ANNOTATION_LINES_LIST_MISSING")
    if len({line.get("id") for line in lines}) != len(lines) or any(
        not line.get("id") for line in lines
    ):
        raise ValueError("ANNOTATION_LINE_ID_MISSING_OR_DUPLICATE")
    objects, uncertainties, decisions, geometry_only = [], [], [], []
    adopted_contacts = []
    consumed_groups, deferred_groups, consumed_lines = [], [], set()
    group_ids = set()
    for group in text_data["groups"]:
        gid = group.get("id")
        if not gid or gid in group_ids:
            raise ValueError("ANNOTATION_TEXT_GROUP_ID_MISSING_OR_DUPLICATE")
        group_ids.add(gid)
        text = group.get("text")
        if not isinstance(text, str):
            raise ValueError("ANNOTATION_GROUP_TEXT_MUST_BE_STRING:" + gid)
        if not group.get("numeric_label", False):
            continue
        review = group.get("source_review", {})
        reviewed_unchanged = bool(review.get("accepted") and review.get("text") == text)
        text_ready = bool(group.get("complete", False) or reviewed_unchanged)
        reasons = []
        if not text or not text.isdigit():
            reasons.append("NUMERIC_LABEL_FLAG_CONTRADICTS_UNCHANGED_TEXT")
        if not text_ready:
            reasons.append("NUMERIC_TEXT_GROUP_INCOMPLETE")
        if group.get("unresolved_reasons") and not reviewed_unchanged:
            reasons.append("NUMERIC_TEXT_HAS_UNRESOLVED_REASONS")
        if group.get("geometry_type") != "TEXT" or len(group.get("lines", [])) != 1:
            reasons.append("NUMERIC_LABEL_REQUIRES_ONE_COMPLETE_TEXT_LINE")
        enclosure = group.get("enclosure")
        if not isinstance(enclosure, dict):
            reasons.append("NUMERIC_LABEL_WITHOUT_AUTOMATIC_COMPLETE_ENCLOSURE")
        frame, evidence = None, None
        # Source frame geometry can be diagnosed independently of an incomplete
        # OCR string. Such a result never changes complete/confidence or emits
        # a ROOM_LABEL; it is saved separately for a later explicit review.
        if (
            isinstance(enclosure, dict)
            and text
            and text.isdigit()
            and group.get("geometry_type") == "TEXT"
            and len(group.get("lines", [])) == 1
        ):
            frame, evidence = _measure_frame(
                gray, roi, enclosure, group.get("bbox_xyxy_px")
            )
            if frame is None:
                reasons.extend(evidence["rejection_reasons"])
        matched, contacts, conflicts = [], [], []
        if frame is not None:
            matched, contacts, conflicts = _match_frame_lines(frame, lines)
            if conflicts:
                reasons.append(
                    "FRAME_EDGE_HAS_UNRESOLVED_CONTINUATION_OUTSIDE_COMPOSITE"
                )
            if consumed_lines.intersection(matched):
                reasons.append("FRAME_LINE_ALREADY_OWNED_BY_OTHER_ANNOTATION")
            for previous in objects:
                before = np.asarray(previous["geometry"]["frame_points"])
                if all(
                    float(np.min(np.linalg.norm(before - p, axis=1))) <= 2.0
                    for p in frame
                ):
                    reasons.append("FRAME_ALREADY_OWNED_BY_OTHER_TEXT_GROUP")
        decision = {
            "text_group_id": gid,
            "text": text,
            "text_acceptance_mode": "EXPLICIT_SOURCE_REVIEW"
            if reviewed_unchanged
            else "AUTOMATIC_CRITERIA",
            "automatic_complete_unchanged": bool(group.get("complete", False)),
            "bbox_xyxy_px": group.get("bbox_xyxy_px"),
            "numeric_text_unchanged": True,
            "frame_source_evidence": evidence,
            "frame_line_contacts": contacts,
            "rejection_reasons": sorted(set(reasons)),
        }
        if reasons:
            deferred_groups.append(gid)
            decision["decision"] = "DEFER_WHOLE_NUMERIC_LABEL"
            uncertainties.append(
                {
                    **decision,
                    "reason": "INCOMPLETE_OR_AMBIGUOUS_COMPOSITE_ANNOTATION",
                    "standalone_numeric_text_export_allowed": False,
                    "source_retained": True,
                }
            )
            if frame is not None:
                geometry_only.append(
                    {
                        "text_group_id": gid,
                        "unchanged_ocr_proposal": text,
                        "automatic_text_complete": bool(group.get("complete", False)),
                        "frame_points": frame.tolist(),
                        "frame_closed": True,
                        "source_evidence": evidence,
                        "formal_adoption_allowed": False,
                        "defer_reasons": sorted(set(reasons)),
                        "text_confidence_or_complete_overridden": False,
                    }
                )
        else:
            box = list(map(float, group["bbox_xyxy_px"]))
            geometry = {
                "frame_points": frame.tolist(),
                "frame_closed": True,
                "text_geometry": {
                    "text": text,
                    "x": box[0],
                    "y": box[3],
                    "height_px": box[3] - box[1],
                    "width_px": box[2] - box[0],
                    "rotation_deg": 0.0,
                    "bbox_xyxy_px": box,
                    "baseline_basis": "source_word_bbox_bottom_font_layout_unverified",
                },
            }
            oid = stable_id("ROOM_LABEL", geometry)
            objects.append(
                {
                    "id": oid,
                    "kind": "ROOM_LABEL",
                    "layer": "ROOM_LABELS",
                    "geometry": geometry,
                    "source_evidence": {
                        "method": POLICY["version"],
                        "text_group_id": gid,
                        "region_ids": group.get("region_ids", []),
                        "text_complete": bool(group.get("complete", False)),
                        "text_unchanged": True,
                        "automatic_text_complete": bool(group.get("complete", False)),
                        "explicit_source_review_accepted": reviewed_unchanged,
                        "source_review": review if reviewed_unchanged else None,
                        "automatic_unresolved_reasons": group.get(
                            "unresolved_reasons", []
                        ),
                        "frame": evidence,
                        "consumed_frame_line_ids": matched,
                        "frame_line_contacts": contacts,
                    },
                    "editing_scope": "whole frame with numeric TEXT; inner TEXT independently editable",
                    "block_definition_policy": POLICY["block_policy"],
                    "source_review_required": True,
                    "automatic_formal_adoption": False,
                }
            )
            consumed_groups.append(gid)
            consumed_lines.update(matched)
            adopted_contacts.extend(contacts)
            decision.update(
                decision="COMPLETE_ROOM_LABEL_PROPOSAL",
                object_id=oid,
                consumed_frame_line_ids=matched,
            )
        decisions.append(decision)
    remaining, frame_partition, fully_retired = _frame_line_remainders(
        lines, adopted_contacts
    )
    result = {
        "coordinate_system": COORDINATES,
        "roi_xyxy_px": list(roi),
        "policy": POLICY,
        "objects": objects,
        "remaining_lines": remaining,
        "consumed_text_group_ids": consumed_groups,
        "deferred_text_group_ids": deferred_groups,
        "consumed_line_ids": sorted(consumed_lines),
        "uncertainties": uncertainties,
        "fully_retired_line_ids": fully_retired,
        "frame_line_interval_partition": frame_partition,
        "geometry_only_frame_candidates": geometry_only,
        "decisions": decisions,
        "source_pixels_modified": False,
        "expected_review_cases_used_as_input": False,
        "counts": {
            "room_label_proposals": len(objects),
            "deferred_numeric_groups": len(deferred_groups),
            "consumed_duplicate_frame_lines": len(consumed_lines),
            "remaining_lines": len(remaining),
        },
        "resources": {"wall_seconds": time.perf_counter() - started},
        "limitations": [
            "room-label role is observed enclosed-number structure, not a room schedule proof",
            "candidate completeness does not replace independent source/CAD/GUI review",
            "continued frame-edge ownership is deferred rather than splitting neighbour lines",
        ],
    }
    result = resolve_frame_edit_ownership(result, lines)
    from .frame_endpoint_reconcile import reconcile_frame_endpoints

    result = reconcile_frame_endpoints(result, gray, roi)
    save_json(Path(out) / "annotations.json", result)
    return result
