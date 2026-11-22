"""Protect a proved local white separation beside a newly measured circle.

The legacy long-LINE fitter permits small distances to ink.  That tolerance
must not turn a separate source line and a circle into a joined finite LINE.
This bounded correction leaves the long-line detector unchanged: only a short
terminal overrun into a verified circle can be removed, and only when every
removed ink sample belongs to that circle rather than to the exterior lead.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .circular_markers import _runs, verify_circle_source_evidence
from .circle_endpoint_contacts import _circle, _digest, verified_original_geometry


FIELD = "circle_white_gap_protection"
POLICY = {
    "version": "native-circle-terminal-white-gap-protection-v1",
    "source_threshold": 128,
    "source_connectivity": 8,
    "eligible_source_method": "native_tiled_source_centered_complete_lines_v2",
    "legacy_line_source_distance_px": 2.0,
    "maximum_terminal_extent_stroke_widths": 2.0,
    "maximum_terminal_extent_px": 12.0,
    "minimum_corridor_halfwidth_px": 2.5,
    "maximum_corridor_halfwidth_px": 4.0,
    "minimum_complete_white_strip_px": 0.5,
    "minimum_retained_line_length_px": 8.0,
    "circle_and_exterior_source_must_be_separate_in_local_corridor": True,
    "removed_ink_must_belong_only_to_verified_ring": True,
    "source_pixels_modified": False,
    "block_members_or_polylines_trimmed": False,
}


def _ring_mask(circle, bounds):
    x0, y0, x1, y1 = bounds
    mask = np.zeros((y1 - y0, x1 - x0), bool)
    for y, a, b in circle["source_evidence"]["ring_support_runs_y_x0_x1"]:
        if y0 <= y < y1 and max(a, x0) < min(b, x1):
            mask[y - y0, max(a, x0) - x0:min(b, x1) - x0] = True
    return mask


def _candidate(gray, roi, line, end, circle):
    """Prove an exterior line cap, a full local white strip and separate ring."""
    if (line.get("kind") != "LINE" or line.get("source_evidence", {}).get("method")
            != POLICY["eligible_source_method"]):
        return None
    geometry = line["geometry"]
    endpoint = np.asarray(geometry["start" if end == 0 else "end"], float)
    other = np.asarray(geometry["end" if end == 0 else "start"], float)
    cg = _circle(circle)
    center, radius = np.asarray(cg["center"], float), float(cg["radius_px"])
    width = float(circle["source_evidence"]["ring_geometry"]["stroke_width_px"])
    radial = float(np.linalg.norm(endpoint - center))
    # This correction is solely for a finite LINE already overrun into a
    # circle's terminal band. Nearby, tangent, through-going and block-member
    # geometry retain their existing responsibilities and tolerances.
    if not radius - width / 2 - POLICY["legacy_line_source_distance_px"] <= radial < radius - 1e-6:
        return None
    vector = other - endpoint
    length = float(np.linalg.norm(vector))
    if length <= 0 or not np.isfinite(vector).all():
        return None
    u = vector / length
    if float((endpoint - center) @ u) <= 0:
        return None
    extent = min(POLICY["maximum_terminal_extent_px"],
                 POLICY["maximum_terminal_extent_stroke_widths"] * width
                 + 2 * POLICY["legacy_line_source_distance_px"])
    if length <= extent + POLICY["minimum_retained_line_length_px"]:
        return None
    source_width = float(line["source_evidence"].get("source_width_px", width))
    halfwidth = max(POLICY["minimum_corridor_halfwidth_px"],
                    min(POLICY["maximum_corridor_halfwidth_px"], source_width / 2 + 0.5))
    n = np.array([-u[1], u[0]])
    corners = np.asarray([endpoint + t * u + v * n
                          for t in (0.0, extent) for v in (-halfwidth, halfwidth)])
    low = np.maximum(np.floor(corners.min(axis=0) - 1).astype(int), (0, 0))
    high = np.minimum(np.ceil(corners.max(axis=0) + 1).astype(int) + 1,
                      (gray.shape[1], gray.shape[0]))
    x0, y0 = low
    x1, y1 = high
    yy, xx = np.mgrid[y0:y1, x0:x1]
    points = np.stack((xx, yy), axis=-1).astype(float)
    projection = (points - endpoint) @ u
    normal = (points - endpoint) @ n
    corridor = (projection >= 0) & (projection <= extent) & (np.abs(normal) <= halfwidth)
    ink = (gray[y0:y1, x0:x1] < POLICY["source_threshold"]) & corridor
    ring = _ring_mask(circle, [x0, y0, x1, y1]) & corridor
    _, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    circle_labels = set(labels[ring & ink].tolist()) - {0}
    exterior_labels = set(labels[ink & (projection >= extent - 1.5)].tolist()) - {0}
    if len(circle_labels) != 1 or len(exterior_labels) != 1:
        return None
    def pending(reason):
        return {"object_id": line["id"], "circle_id": circle["id"], "endpoint_number": end,
                "accepted": False, "requires_repair": True, "reason": reason,
                "original_endpoint_px": endpoint.tolist(),
                "source_crop_xyxy_px": [int(x0), int(y0), int(x1), int(y1)],
                "original_geometry_retained": True,
                "status": "NEARBY_EXTERNAL_ENDPOINT_RELATION_PENDING"}
    if circle_labels == exterior_labels:
        _, four = cv2.connectedComponents(ink.astype(np.uint8), connectivity=4)
        ring_four = set(four[ring & ink].tolist()) - {0}
        exterior_four = set(four[ink & (projection >= extent - 1.5)].tolist()) - {0}
        if ring_four.isdisjoint(exterior_four):
            return pending("LOCAL_CONTACT_IS_DIAGONAL_ONLY_NO_WHITE_STRIP_TRIM_AUTHORITY")
        return None
    ring_label, exterior_label = next(iter(circle_labels)), next(iter(exterior_labels))
    observed = set(labels[ink].tolist())
    if observed != {ring_label, exterior_label}:
        return pending("LOCAL_SOURCE_HAS_ANOTHER_COMPONENT_OR_SHORT_BRANCH")
    exterior = labels == exterior_label
    ring_component = labels == ring_label
    exterior_front = float(projection[exterior].min())
    ring_back = float(projection[ring_component].max())
    # A pixel is a unit square, not merely its centre. These projection
    # bounds prove an actually white strip across the complete local band.
    pixel_half_projection = float(np.abs(u).sum() / 2)
    strip = [ring_back + pixel_half_projection, exterior_front - pixel_half_projection]
    if strip[1] - strip[0] < POLICY["minimum_complete_white_strip_px"]:
        return pending("SEPARATE_LOCAL_SOURCE_DOES_NOT_PROVE_A_COMPLETE_WHITE_STRIP")
    removed_ink = ink & (projection < exterior_front - 1e-9)
    if not removed_ink.any() or np.any(removed_ink & ~ring):
        return pending("TERMINAL_TAIL_HAS_SOURCE_NOT_OWNED_BY_THE_CIRCLE")
    retained = endpoint + exterior_front * u
    if (not (roi[0] <= retained[0] < roi[2] and roi[1] <= retained[1] < roi[3])
            or np.linalg.norm(retained - center) <= radius
            or length - exterior_front < POLICY["minimum_retained_line_length_px"]):
        return None
    bounds = [int(x0), int(y0), int(x1), int(y1)]
    return {
        "object_id": line["id"], "circle_id": circle["id"], "endpoint_number": end,
        "accepted": True, "requires_repair": False,
        "original_endpoint_px": endpoint.tolist(), "retained_source_endpoint_px": retained.tolist(),
        "removed_terminal_length_px": exterior_front, "maximum_terminal_extent_px": extent,
        "circle_geometry": deepcopy(cg), "circle_source_crop_sha256": circle["source_evidence"]["crop_sha256"],
        "corridor_halfwidth_px": halfwidth, "corridor_axis": u.tolist(),
        "source_crop_xyxy_px": bounds,
        "source_crop_sha256": hashlib.sha256(np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()).hexdigest(),
        "exterior_source_runs_y_x0_x1": _runs(exterior, (x0, y0)),
        "removed_ring_source_runs_y_x0_x1": _runs(removed_ink, (x0, y0)),
        "white_strip_projection_px": strip,
        "complete_white_strip_width_px": float(strip[1] - strip[0]),
        "exterior_and_ring_are_different_local_eight_connected_components": True,
        "all_removed_ink_is_verified_circle_boundary": True,
        "retained_exterior_source_not_removed": True,
        "source_pixels_modified": False,
        "status": "PROTECTED_SOURCE_WHITE_GAP_NO_CONNECTION_REQUIRED",
    }


def _original(line):
    original = deepcopy(line)
    certificate = original.get("source_evidence", {}).pop(FIELD, None)
    if certificate:
        original["geometry"] = deepcopy(certificate["original_geometry"])
    return original


def _retained_geometry(original, ends):
    geometry = deepcopy(original["geometry"])
    for row in ends:
        geometry["start" if row["endpoint_number"] == 0 else "end"] = list(row["retained_source_endpoint_px"])
    return geometry


def protect_circle_white_gaps(gray, roi, objects):
    """Keep the independently editable source line; remove only a proved overrun."""
    circles = [obj for obj in objects if obj.get("kind") in ("CIRCLE", "CIRCULAR_MARKER")
               and verify_circle_source_evidence(gray, roi, obj).get("pass") is True]
    replacements, changes, unresolved = [], [], []
    for obj in objects:
        if obj.get("kind") != "LINE":
            continue
        if obj.get("source_evidence", {}).get("circle_endpoint_contacts"):
            # Ordinary assembly applies this protection before extensions.
            # A completed, separately proved extension must never be peeled
            # away by running the earlier stage again; cold audit still checks
            # both certificates and any remaining actual white-gap overrun.
            continue
        original = _original(obj)
        ends = []
        for end in (0, 1):
            offers = [proof for circle in circles
                      if (proof := _candidate(gray, roi, original, end, circle))]
            if len(offers) == 1 and offers[0]["accepted"]:
                ends.extend(offers)
            elif offers:
                unresolved.extend({**row, "accepted": False, "requires_repair": True,
                                   "reason": row.get("reason", "TERMINAL_HAS_MORE_THAN_ONE_CIRCLE_OWNER")}
                                  for row in offers)
        if not ends:
            continue
        replacement = deepcopy(original)
        replacement["geometry"] = _retained_geometry(original, ends)
        certificate = {
            "schema": POLICY["version"], "policy": dict(POLICY),
            "original_geometry": deepcopy(original["geometry"]),
            "original_geometry_sha256": _digest(original["geometry"]),
            "original_source_evidence_sha256": _digest(original.get("source_evidence", {})),
            "retained_geometry_sha256": _digest(replacement["geometry"]), "ends": ends,
            "same_independent_object_id_retained": True,
            "original_source_records_modified": False,
            "source_supported_exterior_line_deleted": False,
        }
        replacement.setdefault("source_evidence", {})[FIELD] = certificate
        replacements.append(replacement)
        changes.append({"old_object_id": obj["id"], "result_object_id": obj["id"],
                        "action": "REMOVE_ONLY_CIRCLE_OWNED_TERMINAL_OVERRUN_ACROSS_PROVED_WHITE_GAP",
                        "old_geometry_sha256": certificate["original_geometry_sha256"],
                        "retained_geometry_sha256": certificate["retained_geometry_sha256"],
                        "protected_white_gaps": len(ends), "retired": False,
                        "source_supported_exterior_line_deleted": False})
    return {"schema": POLICY["version"], "policy": dict(POLICY),
            "replacements": replacements, "changes": changes, "pending_relations": unresolved,
            "summary": {"corrected_independent_lines": len(replacements),
                        "protected_source_white_gaps": sum(len(obj["source_evidence"][FIELD]["ends"]) for obj in replacements),
                        "pending_terminal_relations": len(unresolved),
                        "new_formal_objects": 0, "retired_objects": 0,
                        "new_OCR_calls": 0, "source_pixels_modified": False}}


def verify_white_gap_protection(gray, roi, obj, objects, actual_geometry):
    """Rebuild the source separation and require the actual saved finite LINE."""
    current = deepcopy(obj)
    if current.get("source_evidence", {}).get("circle_endpoint_contacts"):
        current["geometry"] = verified_original_geometry(gray, roi, current, objects, actual_geometry)
        current["source_evidence"].pop("circle_endpoint_contacts")
        # The full saved LINE has just been checked against its separate
        # extension proof; white-gap protection applies to the preserved base.
        actual_geometry = current["geometry"]
    certificate = current["source_evidence"][FIELD]
    if certificate.get("schema") != POLICY["version"] or certificate.get("policy") != POLICY:
        raise ValueError("CIRCLE_WHITE_GAP_POLICY_CHANGED")
    original = _original(current)
    if (_digest(original["geometry"]) != certificate["original_geometry_sha256"]
            or _digest(original.get("source_evidence", {})) != certificate["original_source_evidence_sha256"]
            or certificate.get("same_independent_object_id_retained") is not True
            or certificate.get("original_source_records_modified") is not False
            or certificate.get("source_supported_exterior_line_deleted") is not False):
        raise ValueError("CIRCLE_WHITE_GAP_ORIGINAL_OBJECT_OR_SOURCE_RECORD_CHANGED")
    by_id = {item["id"]: item for item in objects}
    if len(by_id) != len(objects) or obj["kind"] != "LINE":
        raise ValueError("CIRCLE_WHITE_GAP_REQUIRES_ONE_INDEPENDENT_LINE")
    ends = certificate["ends"]
    if not 1 <= len(ends) <= 2 or len({row["endpoint_number"] for row in ends}) != len(ends):
        raise ValueError("CIRCLE_WHITE_GAP_ENDPOINT_SET_INVALID")
    for row in ends:
        circle = by_id[row["circle_id"]]
        if verify_circle_source_evidence(gray, roi, circle).get("pass") is not True:
            raise ValueError("CIRCLE_WHITE_GAP_RING_SOURCE_NOT_VERIFIED")
        replay = _candidate(gray, roi, original, row["endpoint_number"], circle)
        if replay is None or not replay["accepted"] or _digest(replay) != _digest(row):
            raise ValueError("CIRCLE_WHITE_GAP_ORIGINAL_PIXEL_PROOF_DOES_NOT_REPLAY")
        alternatives = [item for item in objects if item.get("kind") in ("CIRCLE", "CIRCULAR_MARKER")
                        and item["id"] != circle["id"]
                        and _candidate(gray, roi, original, row["endpoint_number"], item)
                        and verify_circle_source_evidence(gray, roi, item).get("pass") is True]
        if alternatives:
            raise ValueError("CIRCLE_WHITE_GAP_HAS_AMBIGUOUS_RING_OWNERSHIP")
    expected = _retained_geometry(original, ends)
    if _digest(expected) != certificate["retained_geometry_sha256"] or _digest(expected) != _digest(current["geometry"]):
        raise ValueError("CIRCLE_WHITE_GAP_RETAINED_LINE_CHANGED")
    for key in ("start", "end"):
        value = np.asarray(actual_geometry[key], float)
        if value.shape != (2,) or not np.isfinite(value).all() or not np.allclose(value, expected[key], rtol=0, atol=1e-7):
            raise ValueError("SAVED_LINE_DOES_NOT_PRESERVE_PROVED_SOURCE_WHITE_GAP")
    return {"pass": True, "protected_source_white_gaps": len(ends),
            "actual_saved_line_checked": True, "original_source_records_preserved": True,
            "source_supported_exterior_line_preserved": True}


def cold_circle_white_gaps(path, doc, gray, roi, dpi):
    """Also reject an uncorrected overrun: absence of a certificate is no pass."""
    from .cad_io import identity, sha, circular_candidate_contract

    actual, flags, targets = {}, set(), set()
    for entity in doc.modelspace():
        if entity.dxf.layer == "REVIEW":
            continue
        ident = identity(entity)
        actual.setdefault(ident["id"], []).append(entity)
        if ident.get(FIELD):
            flags.add(ident["id"])
    targets.update(flags)
    try:
        meta = json.loads(Path(path).with_suffix(".objects.json").read_text(encoding="utf-8"))
        objects = meta["objects"]
        claims = {obj["id"] for obj in objects if obj.get("source_evidence", {}).get(FIELD)}
        targets.update(claims)
        circles = [obj for obj in objects if obj.get("kind") in ("CIRCLE", "CIRCULAR_MARKER")]
        if not circles and not targets:
            return []
        if (meta["dxf_sha256"] != sha(path) or meta["roi_xyxy_px"] != list(roi)
                or meta["dpi"] != dpi or flags != claims):
            raise ValueError("CIRCLE_WHITE_GAP_SAVED_SOURCE_BINDING_CHANGED")
        by_id = {obj["id"]: obj for obj in objects}
        written = {obj["id"]: obj for obj in meta["written"]}
        if len(by_id) != len(objects):
            raise ValueError("CIRCLE_WHITE_GAP_DUPLICATE_CANDIDATE_ID")
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return [{"id": oid, "type": "CIRCLE_WHITE_GAP_PROTECTION", "pass": False, "failure": str(exc)}
                for oid in sorted(targets)]
    mm = 25.4 / dpi

    def px(point):
        return np.array([point[0] / mm + roi[0], roi[3] - point[1] / mm])

    rows, saved_lines = [], []
    for obj in objects:
        if obj.get("kind") != "LINE":
            continue
        entities = actual.get(obj["id"], [])
        if len(entities) != 1 or entities[0].dxftype() != "LINE":
            if obj["id"] in targets:
                rows.append({"id": obj["id"], "type": "CIRCLE_WHITE_GAP_PROTECTION", "pass": False,
                             "failure": "CIRCLE_WHITE_GAP_ACTUAL_LINE_MISSING_OR_DUPLICATED"})
            continue
        entity = entities[0]
        geometry = {"start": px(entity.dxf.start).tolist(), "end": px(entity.dxf.end).tolist()}
        saved_lines.append({**obj, "geometry": geometry})
        if obj["id"] not in targets:
            continue
        row = {"id": obj["id"], "type": "CIRCLE_WHITE_GAP_PROTECTION", "pass": False}
        try:
            if (entity.dxf.start.z != 0 or entity.dxf.end.z != 0
                    or entity.dxf.get("thickness", 0) != 0 or tuple(entity.dxf.extrusion) != (0, 0, 1)
                    or entity.dxf.handle != written[obj["id"]]["handle"]):
                raise ValueError("CIRCLE_WHITE_GAP_ACTUAL_LINE_TRANSFORM_OR_BINDING_CHANGED")
            row.update(verify_white_gap_protection(gray, roi, obj, objects, geometry))
            for end in obj["source_evidence"][FIELD]["ends"]:
                oid = end["circle_id"]
                if len(actual.get(oid, [])) != 1 or not all(
                        value is True for value in circular_candidate_contract(actual[oid][0], by_id[oid], px, mm).values()):
                    raise ValueError("CIRCLE_WHITE_GAP_ACTUAL_RING_CHANGED")
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, ArithmeticError) as exc:
            row.update(pass_=False, failure=str(exc))
            row["pass"] = row.pop("pass_")
        rows.append(row)
    verified_circles = [obj for obj in circles if verify_circle_source_evidence(gray, roi, obj).get("pass") is True]
    for line in saved_lines:
        for circle in verified_circles:
            for end in (0, 1):
                proof = _candidate(gray, roi, line, end, circle)
                if proof:
                    rows.append({"id": line["id"], "type": "CIRCLE_WHITE_GAP_PROTECTION", "pass": False,
                                 "failure": ("SAVED_LINE_STILL_BRIDGES_PROVED_ORIGINAL_WHITE_GAP" if proof["accepted"]
                                             else "SAVED_CIRCLE_TERMINAL_SOURCE_RELATION_PENDING"),
                                 "circle_id": circle["id"], "endpoint_number": end,
                                 "source_relation": proof})
    return rows
