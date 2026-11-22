"""Source-measured circular boundaries, separate from characters and leads.

The existing connection graph observes *inner* round boundaries as terminals.
Those observations are seeds only.  This module remeasures both sides of the
actual ring, verifies a closed source enclosure, and retains exact source runs
for the ring, interior ink, and exterior contacts.  It does not recognize text,
retire another object, or turn an incomplete arc into a complete circle.
"""

from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np

from app.geometry.source_filled_marks import _fit_boundary

from .connections import _round_boundaries
from .contracts import COORDINATES, stable_id


POLICY = {
    "version": "native-circular-boundary-v1",
    "source_threshold": 128,
    "radial_sample_count": 96,
    "radial_sample_step_px": 0.25,
    "dense_centerline_step_px": 0.25,
    "inner_boundary_p95_px": 0.85,
    "inner_boundary_max_px": 1.35,
    "minimum_clean_outer_fraction": 0.70,
    "maximum_centerline_source_distance_px": 0.85,
    "minimum_interior_pixels": 8,
    "source_ring_annulus_fringe_px": 1.0,
    "interior_clearance_px": 1.0,
    "minimum_exterior_extension_px": 3.0,
    "minimum_enclosed_white_area_fraction": 0.30,
    "ordinary_text_or_empty_loop_is_not_a_marker": True,
    "source_modification": "NONE",
    "exterior_connection_geometry_owned": False,
}
_ANGLES = np.arange(POLICY["radial_sample_count"]) * (
    2 * math.pi / POLICY["radial_sample_count"]
)
_RAYS = np.column_stack((np.cos(_ANGLES), np.sin(_ANGLES)))


def _validate_input(gray, roi):
    gray = np.asarray(gray)
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("CIRCULAR_SOURCE_REQUIRES_NATIVE_UINT8_GRAY")
    if len(roi) != 4 or any(int(value) != value for value in roi):
        raise ValueError("CIRCULAR_ROI_REQUIRES_INTEGER_SOURCE_COORDINATES")
    left, top, right, bottom = map(int, roi)
    if not (0 <= left < right <= gray.shape[1] and 0 <= top < bottom <= gray.shape[0]):
        raise ValueError("CIRCULAR_ROI_OUTSIDE_FULL_WORKING_RASTER")
    return gray, (left, top, right, bottom)


def _sample(mask, points):
    points = np.asarray(points, np.float32)
    return cv2.remap(
        mask.astype(np.float32), points[:, 0, None], points[:, 1, None],
        cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    ).ravel()


def _runs(mask, origin):
    runs = []
    ox, oy = map(int, origin)
    for y in np.flatnonzero(np.any(mask, axis=1)):
        edges = np.flatnonzero(np.diff(np.r_[False, mask[y], False]))
        runs.extend([int(y) + oy, int(a) + ox, int(b) + ox] for a, b in edges.reshape(-1, 2))
    return runs


def _mask_from_runs(runs, bbox):
    left, top, right, bottom = map(int, bbox)
    mask = np.zeros((bottom - top, right - left), bool)
    if not isinstance(runs, list):
        raise ValueError("CIRCULAR_SOURCE_RUNS_MISSING")
    for run in runs:
        if len(run) != 3 or any(int(v) != v for v in run):
            raise ValueError("CIRCULAR_SOURCE_RUN_INVALID")
        y, a, b = map(int, run)
        if not (top <= y < bottom and left <= a < b <= right):
            raise ValueError("CIRCULAR_SOURCE_RUN_OUTSIDE_BOUND_CROP")
        if mask[y - top, a - left:b - left].any():
            raise ValueError("CIRCULAR_SOURCE_RUNS_OVERLAP")
        mask[y - top, a - left:b - left] = True
    return mask


def _hash_gray(gray):
    return hashlib.sha256(np.ascontiguousarray(gray).tobytes()).hexdigest()


def _dense_circle(center, radius):
    count = max(96, math.ceil(2 * math.pi * radius / POLICY["dense_centerline_step_px"]))
    angle = np.arange(count) * (2 * math.pi / count)
    return np.asarray(center) + radius * np.column_stack((np.cos(angle), np.sin(angle)))


def _measure_ring(component, seed, seed_radius):
    """Reuse the established native radial fit without its legacy exporter."""
    fitted = _fit_boundary(np.uint8(component) * 255, *seed, seed_radius, _RAYS)
    if fitted is None:
        return None, "INNER_BOUNDARY_NOT_CIRCULAR_WITHIN_NATIVE_FIT_LIMITS"
    center, inner_radius, inner_metrics = fitted
    center = np.asarray(center)
    step = POLICY["radial_sample_step_px"]
    distances = np.arange(max(0, inner_radius - 2), inner_radius * 1.6 + 3, step)
    samples = (center + _RAYS[:, None] * distances[None, :, None]).reshape(-1, 2)
    ink = _sample(component, samples).reshape(len(_RAYS), -1) >= 0.5
    enters = np.argmax(ink, axis=1)
    exits = ~ink & (np.arange(len(distances))[None, :] > enters[:, None])
    measured = ink.any(axis=1) & exits.any(axis=1)
    outer_radius = distances[np.argmax(exits, axis=1)] - step / 2
    if measured.sum() < 0.75 * len(_RAYS):
        return None, "OUTER_RING_BOUNDARY_HAS_TOO_FEW_OBSERVED_RAYS"
    median_outer = np.median(outer_radius[measured])
    clean = measured & (np.abs(outer_radius - median_outer) <= max(1.2, 0.08 * inner_radius))
    if (clean.mean() < POLICY["minimum_clean_outer_fraction"]
            or min(clean.reshape(4, -1).sum(axis=1)) < len(_RAYS) / 8):
        return None, "OUTER_RING_BOUNDARY_OBSCURED_BY_NEIGHBORS"
    width = float(np.median(outer_radius[clean]) - inner_radius)
    radius = float(inner_radius + width / 2)
    if not 1 <= width < inner_radius / 2:
        return None, "RING_STROKE_WIDTH_NOT_SEPARABLE_FROM_FILLED_BODY"
    dense = _dense_circle(center, radius)
    center_ink = _sample(component, dense)
    source_distance = _sample(cv2.distanceTransform(
        np.uint8(~component), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    ), dense)
    # A subpixel ideal centre can lie beside a stair-stepped source stroke.
    # Bound that distance using the established native fitting tolerance; a
    # separate exact white-connectivity test below forbids closing any gap.
    if source_distance.max() > POLICY["maximum_centerline_source_distance_px"]:
        return None, "FULL_CIRCLE_CENTERLINE_HAS_UNSUPPORTED_SOURCE_GAP"
    metrics = dict(inner_metrics)
    metrics.update({
        "clean_outer_rays": int(clean.sum()),
        "outer_p95_radial_error_px": float(np.percentile(np.abs(outer_radius[clean] - inner_radius - width), 95)),
        "dense_centerline_samples": len(dense),
        "minimum_center_ink": float(center_ink.min()),
        "maximum_centerline_source_distance_px": float(source_distance.max()),
        "full_circle_source_fraction": float(np.mean(source_distance <= POLICY["maximum_centerline_source_distance_px"])),
    })
    return (center, radius, width, metrics), None


def _closed_source_enclosure(ring, center, radius, width):
    """Eight-connected white paths remain open; never morphologically close."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.uint8(~ring), connectivity=8
    )
    exterior = set(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]].tolist())
    yy, xx = np.indices(ring.shape)
    inside = np.hypot(xx - center[0], yy - center[1]) < radius - width / 2 - 1
    white_ids = set(np.unique(labels[inside & ~ring]).tolist()) - {0}
    enclosed_ids = sorted(white_ids - exterior)
    open_ids = sorted(white_ids & exterior)
    enclosed = sum(int(stats[i, cv2.CC_STAT_AREA]) for i in enclosed_ids)
    threshold = POLICY["minimum_enclosed_white_area_fraction"] * math.pi * max(0, radius - width / 2) ** 2
    return {
        "pass": bool(count > 1 and enclosed >= threshold and not open_ids),
        "white_connectivity": 8,
        "closed_white_component_count": len(enclosed_ids),
        "interior_white_components_connected_to_exterior": open_ids,
        "enclosed_white_pixels": enclosed,
        "minimum_enclosed_white_pixels": float(threshold),
        "source_morphology_applied": False,
    }


def _contact_ports(ink, ring, distance, radius, width, origin):
    outer = radius + width / 2 + POLICY["source_ring_annulus_fringe_px"]
    reach = outer + max(8.0, radius * 0.75)
    band = ink & (distance > outer) & (distance <= reach)
    count, labels = cv2.connectedComponents(np.uint8(band), connectivity=8)
    adjacent = cv2.dilate(np.uint8(ring), np.ones((3, 3), np.uint8)) > 0
    ports = []
    for label in range(1, count):
        pixels = labels == label
        contacts = np.argwhere(pixels & adjacent)
        if not len(contacts):
            continue
        radial = distance[pixels]
        if radial.max() - outer < POLICY["minimum_exterior_extension_px"]:
            continue
        contact = contacts[np.argmin(np.linalg.norm(contacts - contacts.mean(axis=0), axis=1))]
        all_points = np.argwhere(pixels)
        far = all_points[np.argmax(distance[pixels])]
        ports.append({
            "contact_px": [int(contact[1] + origin[0]), int(contact[0] + origin[1])],
            "outer_witness_px": [int(far[1] + origin[0]), int(far[0] + origin[1])],
            "source_runs_y_x0_x1": _runs(pixels, origin),
            "source_pixels": int(pixels.sum()),
            "ring_contact_is_geometric_only": True,
            "external_connection_owned": False,
            "electrical_connectivity": "UNRESOLVED",
        })
    return ports


def _protected_ring_conflicts(ring, origin, protected_text_boxes):
    left, top = map(int, origin)
    height, width = ring.shape
    conflicts = []
    for index, value in enumerate(protected_text_boxes):
        if isinstance(value, dict):
            if not (value.get("confirmed") or value.get("accepted")):
                continue
            box = value.get("bbox_xyxy_px")
            runs = value.get("glyph_source_runs")
            identity = value.get("id", value.get("region_id", str(index)))
        else:
            box, runs, identity = value, None, str(index)
        if not box or len(box) != 4:
            continue
        a, b, c, d = box
        if c <= left or a >= left + width or d <= top or b >= top + height:
            continue
        if runs is not None:
            intersects = any(
                top <= int(y) < top + height
                and max(left, int(x0)) < min(left + width, int(x1))
                and ring[int(y) - top, max(left, int(x0)) - left:min(left + width, int(x1)) - left].any()
                for y, x0, x1 in runs
            )
        else:
            window = np.s_[max(0, math.floor(b) - top):min(height, math.ceil(d) - top),
                           max(0, math.floor(a) - left):min(width, math.ceil(c) - left)]
            intersects = bool(ring[window].any())
        if intersects:
            conflicts.append(str(identity))
    return conflicts


def _observe_seed(gray, roi, seed, protected_text_boxes):
    initial_center = np.asarray(seed["center"], float)
    initial_radius = float(seed["inner_boundary_radius_px"])
    pad = math.ceil(initial_radius * 2.2 + 8)
    cx, cy = initial_center
    left, top = max(0, math.floor(cx) - pad), max(0, math.floor(cy) - pad)
    right, bottom = min(gray.shape[1], math.ceil(cx) + pad + 1), min(gray.shape[0], math.ceil(cy) + pad + 1)
    bbox = [left, top, right, bottom]
    crop = gray[top:bottom, left:right]
    ink = crop < POLICY["source_threshold"]
    _, labels = cv2.connectedComponents(np.uint8(ink), connectivity=8)
    center = initial_center - (left, top)
    sample = np.rint(center + (initial_radius + 1) * _RAYS).astype(int)
    valid = (sample[:, 0] >= 0) & (sample[:, 0] < crop.shape[1]) & (sample[:, 1] >= 0) & (sample[:, 1] < crop.shape[0])
    ids = labels[sample[valid, 1], sample[valid, 0]]
    ids = ids[ids > 0]
    component_id = int(np.bincount(ids).argmax()) if len(ids) else 0
    row = {
        "id": stable_id("CIRCULAR", {"seed_center": np.round(initial_center, 6).tolist(), "seed_radius": round(initial_radius, 6)}),
        "seed_observation": seed,
        "geometry_accepted": False,
        "reasons": [],
        "source_evidence": {
            "kind": "CIRCULAR_BOUNDARY_SOURCE_V1",
            "coordinate_system": COORDINATES,
            "policy": dict(POLICY),
            "crop_bbox_xyxy_px": bbox,
            "crop_sha256": _hash_gray(crop),
            "source_size_px": [gray.shape[1], gray.shape[0]],
            "roi_xyxy_px": list(roi),
            "source_pixels_modified": False,
            "external_connections_owned": False,
            "recognition_performed": False,
        },
    }
    if not component_id:
        row["reasons"].append("OBSERVED_RING_HAS_NO_SOURCE_COMPONENT")
        return row
    component = labels == component_id
    fitted, failure = _measure_ring(component, center, initial_radius)
    if fitted is None:
        row["reasons"].append(failure)
        return row
    center, radius, width, metrics = fitted
    full_center = center + (left, top)
    yy, xx = np.indices(ink.shape)
    distance = np.hypot(xx - center[0], yy - center[1])
    ring = component & (np.abs(distance - radius) <= width / 2 + POLICY["source_ring_annulus_fringe_px"])
    interior = ink & (distance < radius - width / 2 - POLICY["interior_clearance_px"])
    closed = _closed_source_enclosure(ring, center, radius, width)
    ports = _contact_ports(ink, ring, distance, radius, width, (left, top))
    conflicts = _protected_ring_conflicts(ring, (left, top), protected_text_boxes)
    interior_ids = [int(v) for v in np.unique(labels[interior]) if v > 0]
    connected_interior = component_id in interior_ids
    disconnected_complete = bool(interior_ids and not connected_interior)
    for identity in interior_ids:
        all_component = labels == identity
        if np.any(all_component & ~interior):
            disconnected_complete = False
    glyph_bbox = None
    if interior.any():
        gy, gx = np.nonzero(interior)
        glyph_bbox = [int(gx.min()) + left, int(gy.min()) + top,
                      int(gx.max()) + left + 1, int(gy.max()) + top + 1]
    row.update({
        "geometry": {"center": full_center.tolist(), "radius_px": radius},
        "stroke_width_px": width,
        "bbox_xyxy_px": [float(full_center[0] - radius - width / 2), float(full_center[1] - radius - width / 2),
                          float(full_center[0] + radius + width / 2), float(full_center[1] + radius + width / 2)],
        "glyph_bbox_xyxy_px": glyph_bbox,
    })
    row["source_evidence"].update({
        "ring_geometry": {"center": full_center.tolist(), "radius_px": radius, "stroke_width_px": width},
        "ring_support_runs_y_x0_x1": _runs(ring, (left, top)),
        "interior_support_runs_y_x0_x1": _runs(interior, (left, top)),
        "ring_source_pixels": int(ring.sum()),
        "interior_source_pixels": int(interior.sum()),
        "glyph_bbox_xyxy_px": glyph_bbox,
        "interior_component_count": len(interior_ids),
        "interior_connected_to_boundary": connected_interior,
        "interior_is_complete_separate_components": disconnected_complete,
        "contact_ports": ports,
        "closed_source_enclosure": closed,
        "radial_fit": metrics,
        "protected_text_conflicts": conflicts,
        "text_content": None,
    })
    if not closed["pass"]:
        row["reasons"].append("SOURCE_RING_HAS_OPEN_WHITE_ROUTE")
    if conflicts:
        row["reasons"].append("RING_OVERLAPS_PROTECTED_FORMAL_GLYPH")
    if interior.sum() < POLICY["minimum_interior_pixels"] and not ports:
        row["reasons"].append("EMPTY_UNCONNECTED_LOOP_COULD_BE_ORDINARY_O_OR_ZERO")
    a, b, c, d = row["bbox_xyxy_px"]
    if not (roi[0] <= a < c <= roi[2] and roi[1] <= b < d <= roi[3]):
        row["reasons"].append("COMPLETE_CIRCLE_EXTENDS_OUTSIDE_REQUESTED_ROI")
    row["geometry_accepted"] = not row["reasons"]
    row["composition_status"] = "BOUNDARY_ONLY_CHARACTER_NOT_YET_RECOGNIZED" if row["geometry_accepted"] else "PENDING_REPAIR"
    return row


def discover_circular_markers(gray, roi, *, protected_text_boxes=(), observed_rounds=None):
    """Observe the whole requested ROI; accept no case IDs or expected strings."""
    gray, roi = _validate_input(gray, roi)
    left, top, right, bottom = roi
    seeds = _round_boundaries(gray[top:bottom, left:right] < POLICY["source_threshold"], np.asarray((left, top)))
    # Optional previous observations are only additional proposal seeds.  Every
    # acceptance below is remeasured on the current unmodified source image.
    for seed in observed_rounds or ():
        center = np.asarray(seed.get("center", []), float)
        if center.shape != (2,) or not np.isfinite(center).all():
            continue
        radius = float(seed.get("inner_boundary_radius_px", 0))
        if not math.isfinite(radius) or not 8 <= radius <= 32:
            continue
        if not (left <= center[0] < right and top <= center[1] < bottom):
            continue
        if any(np.linalg.norm(center - np.asarray(s["center"])) < 1 and abs(radius - s["inner_boundary_radius_px"]) < 1 for s in seeds):
            continue
        seeds.append({"center": center.tolist(), "inner_boundary_radius_px": radius,
                      "class": "PREVIOUS_OBSERVATION_REQUIRES_CURRENT_SOURCE_REMEASUREMENT"})
    rows = [_observe_seed(gray, roi, seed, protected_text_boxes) for seed in seeds]
    # Reconcile only fully measured, source-closed boundaries.  Different seed
    # observations must not create duplicate CIRCLE objects for the same ring.
    represented = []
    for row in rows:
        if not row["geometry_accepted"]:
            continue
        geometry = row["geometry"]
        duplicate = next((prior for prior in represented
                          if np.linalg.norm(np.asarray(geometry["center"]) - prior["geometry"]["center"]) <= 0.25
                          and abs(geometry["radius_px"] - prior["geometry"]["radius_px"]) <= 0.25), None)
        if duplicate is None:
            represented.append(row)
        else:
            row["geometry_accepted"] = False
            row["duplicate_of"] = duplicate["id"]
            row["reasons"].append("SAME_MEASURED_SOURCE_BOUNDARY_ALREADY_REPRESENTED")
            row["composition_status"] = "DUPLICATE_OBSERVATION_NOT_A_SECOND_OBJECT"
    return {
        "schema": "native-circular-boundary-observations-v1",
        "coordinate_system": COORDINATES,
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "roi_xyxy_px": list(roi),
        "policy": dict(POLICY),
        "rows": rows,
        "summary": {"observed_round_seeds": len(seeds),
                    "accepted_complete_boundaries": sum(row["geometry_accepted"] for row in rows),
                    "recognized_characters": 0,
                    "retired_old_objects": 0},
    }


def verify_circle_source_evidence(gray, roi, obj, evidence_root=None):
    """Recompute the saved circle's source contract; no cached PASS authority."""
    del evidence_root  # All necessary evidence is source-bound, not path-based.
    result = {"object_id": obj.get("id"), "pass": False, "reasons": []}
    try:
        gray, roi = _validate_input(gray, roi)
        evidence = obj.get("source_evidence", {})
        if evidence.get("kind") != "CIRCULAR_BOUNDARY_SOURCE_V1":
            raise ValueError("CIRCULAR_BOUNDARY_SOURCE_EVIDENCE_MISSING")
        if evidence.get("policy") != POLICY or evidence.get("coordinate_system") != COORDINATES:
            raise ValueError("CIRCULAR_BOUNDARY_POLICY_OR_COORDINATE_MISMATCH")
        if evidence.get("source_size_px") != [gray.shape[1], gray.shape[0]] or evidence.get("roi_xyxy_px") != list(roi):
            raise ValueError("CIRCULAR_BOUNDARY_INPUT_IDENTITY_MISMATCH")
        bbox = evidence.get("crop_bbox_xyxy_px")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(int(v) != v for v in bbox):
            raise ValueError("CIRCULAR_SOURCE_CROP_BOUNDS_INVALID")
        a, b, c, d = map(int, bbox)
        if not (0 <= a < c <= gray.shape[1] and 0 <= b < d <= gray.shape[0]):
            raise ValueError("CIRCULAR_SOURCE_CROP_OUTSIDE_RASTER")
        crop = gray[b:d, a:c]
        if _hash_gray(crop) != evidence.get("crop_sha256"):
            raise ValueError("CIRCULAR_SOURCE_CROP_HASH_MISMATCH")
        geometry = obj.get("geometry", {})
        if "circle_geometry" in geometry:
            geometry = geometry["circle_geometry"]
        stored = evidence.get("ring_geometry", {})
        center = np.asarray(geometry.get("center", []), float)
        radius = float(geometry.get("radius_px", 0))
        width = float(stored.get("stroke_width_px", 0))
        if center.shape != (2,) or not np.isfinite(center).all() or not all(math.isfinite(v) and v > 0 for v in (radius, width)):
            raise ValueError("CIRCULAR_GEOMETRY_INVALID")
        if not np.allclose(center, stored.get("center", []), rtol=0, atol=1e-8) or abs(radius - float(stored.get("radius_px", -1))) > 1e-8:
            raise ValueError("CIRCULAR_GEOMETRY_DIFFERS_FROM_SOURCE_MEASUREMENT")
        ring = _mask_from_runs(evidence.get("ring_support_runs_y_x0_x1"), bbox)
        interior = _mask_from_runs(evidence.get("interior_support_runs_y_x0_x1"), bbox)
        ink = crop < POLICY["source_threshold"]
        if not ring.any() or np.any((ring | interior) & ~ink):
            raise ValueError("CIRCULAR_SOURCE_RUNS_NOT_SUPPORTED_BY_ORIGINAL_INK")
        local_center = center - (a, b)
        yy, xx = np.indices(crop.shape)
        distance = np.hypot(xx - local_center[0], yy - local_center[1])
        _, labels = cv2.connectedComponents(np.uint8(ink), connectivity=8)
        ids = np.unique(labels[ring])
        if len(ids) != 1 or ids[0] == 0:
            raise ValueError("CIRCULAR_RING_RUNS_SPAN_INCOMPATIBLE_SOURCE_COMPONENTS")
        expected_ring = (labels == ids[0]) & (np.abs(distance - radius) <= width / 2 + POLICY["source_ring_annulus_fringe_px"])
        expected_interior = ink & (distance < radius - width / 2 - POLICY["interior_clearance_px"])
        if not np.array_equal(ring, expected_ring) or not np.array_equal(interior, expected_interior):
            raise ValueError("CIRCULAR_SOURCE_RUNS_INCOMPLETE_OR_REASSIGNED")
        interior_ids = [int(value) for value in np.unique(labels[interior]) if value > 0]
        connected_interior = int(ids[0]) in interior_ids
        complete_separate = bool(interior_ids and not connected_interior)
        for identity in interior_ids:
            if np.any((labels == identity) & ~interior):
                complete_separate = False
        glyph_box = None
        if interior.any():
            gy, gx = np.nonzero(interior)
            glyph_box = [int(gx.min()) + a, int(gy.min()) + b,
                         int(gx.max()) + a + 1, int(gy.max()) + b + 1]
        interior_facts = {
            "interior_component_count": len(interior_ids),
            "interior_connected_to_boundary": connected_interior,
            "interior_is_complete_separate_components": complete_separate,
            "glyph_bbox_xyxy_px": glyph_box,
            "ring_source_pixels": int(ring.sum()),
            "interior_source_pixels": int(interior.sum()),
        }
        if any(evidence.get(key) != value for key, value in interior_facts.items()):
            raise ValueError("CIRCULAR_INTERIOR_COMPONENT_OR_GLYPH_BOUNDING_EVIDENCE_CHANGED")
        if not (roi[0] <= center[0] - radius - width / 2
                and center[0] + radius + width / 2 <= roi[2]
                and roi[1] <= center[1] - radius - width / 2
                and center[1] + radius + width / 2 <= roi[3]):
            raise ValueError("CIRCULAR_COMPLETE_GEOMETRY_OUTSIDE_REQUESTED_ROI")
        enclosed = _closed_source_enclosure(ring, local_center, radius, width)
        dense = _dense_circle(local_center, radius)
        sampled = _sample(ink, dense)
        source_distance = _sample(cv2.distanceTransform(
            np.uint8(~ink), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
        ), dense)
        if not enclosed["pass"] or source_distance.max() > POLICY["maximum_centerline_source_distance_px"]:
            raise ValueError("SAVED_FULL_CIRCLE_NOT_CLOSED_AND_SOURCE_SUPPORTED")
        remeasured, reason = _measure_ring(labels == ids[0], local_center, radius - width / 2)
        if remeasured is None:
            raise ValueError(reason)
        measured_center, measured_radius, _, _ = remeasured
        if np.linalg.norm(measured_center - local_center) > 0.15 or abs(measured_radius - radius) > 0.15:
            raise ValueError("CIRCULAR_REMEASUREMENT_CHANGED_BEYOND_SAMPLING_STEP")
        ports = _contact_ports(ink, ring, distance, radius, width, (a, b))
        if ports != evidence.get("contact_ports"):
            raise ValueError("CIRCULAR_EXTERNAL_CONTACT_SOURCE_CHANGED")
        if interior.sum() < POLICY["minimum_interior_pixels"] and not ports:
            raise ValueError("EMPTY_UNCONNECTED_LOOP_HAS_NO_MARKER_EVIDENCE")
        result.update({"crop_hash_matches": True, "all_source_runs_replayed": True,
                       "full_circle_samples": len(sampled), "minimum_center_ink": float(sampled.min()),
                       "maximum_centerline_source_distance_px": float(source_distance.max()),
                       "interior_component_evidence_recomputed": interior_facts,
                       "closed_source_enclosure": enclosed, "contact_port_count": len(ports),
                       "external_connection_geometry_owned": False, "pass": True})
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        result["reasons"].append(str(error))
    return result
