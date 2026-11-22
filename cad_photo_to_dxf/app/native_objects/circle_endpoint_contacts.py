"""Restore only a short, directly ink-supported external end to a native circle.

The original connection and all its source observations remain intact.  A
polyline receives an extra straight terminal segment, so an existing bulge,
local retrace, short branch or white cell cannot change.  This is geometric
contact evidence, not an electrical-connectivity inference.
"""

from copy import deepcopy
import hashlib
import json
import math

import numpy as np

from .circular_markers import verify_circle_source_evidence
from .connections import _dense_geometry
from .contracts import plain


FIELD = "circle_endpoint_contacts"
POLICY = {
    "version": "native-direct-circle-end-contact-v1",
    "source_threshold": 128,
    "maximum_extension_stroke_widths": 1.0,
    "existing_native_fit_allowance_px": 0.85,
    "absolute_extension_limit_px": 6.0,
    "candidate_search_stroke_widths": 2.0,
    "existing_terminal_witness_length_px": 3.0,
    "endpoint_precision_px": 1e-6,
    "source_contact_test": "EVERY_CLOSED_PIXEL_CELL_INTERSECTED_BY_THE_STRAIGHT_EXTENSION_IS_ORIGINAL_INK",
    "source_morphology": "NONE",
    "existing_interior_overlap": "RETAIN_UNCHANGED",
    "external_connection_owned_by_marker": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=plain).encode()).hexdigest()


def _circle(obj):
    return obj["geometry"]["circle_geometry"] if obj["kind"] == "CIRCULAR_MARKER" else obj["geometry"]


def _original(obj):
    result = deepcopy(obj)
    certificate = result.get("source_evidence", {}).pop(FIELD, None)
    if certificate:
        result["geometry"] = deepcopy(certificate["original_geometry"])
    return result


def _ends(obj):
    """Return each original end and its exact outward tangent, including bulges."""
    g = obj["geometry"]
    if obj["kind"] == "LINE":
        points, bulges = np.asarray([g["start"], g["end"]], float), [0.0, 0.0]
    elif obj["kind"] == "CONNECTION_PATH" and not g.get("closed"):
        points = np.asarray(g["points"], float)
        bulges = g.get("bulges", [0.0] * len(points))
    else:
        return []
    if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 2
            or len(bulges) != len(points) or not np.isfinite(points).all()
            or not np.isfinite(bulges).all()):
        return []
    result = []
    for end, a, b, bulge in ((0, points[0], points[1], bulges[0]),
                              (1, points[-2], points[-1], bulges[-2])):
        chord = b - a
        length = float(np.linalg.norm(chord))
        if length <= 1e-9:
            continue
        angle = (1 if end else -1) * 2 * math.atan(float(bulge))
        c, s = math.cos(angle), math.sin(angle)
        direction = np.array([[c, -s], [s, c]]) @ (chord / length)
        if end == 0:
            direction = -direction
        result.append((end, points[0 if end == 0 else -1], direction))
    return result


def _segment_cells(a, b):
    """Exact supercover: no distance-field allowance can bridge a white pixel.

    Source pixel (x,y) owns the closed square [x-.5,x+.5]×[y-.5,y+.5].
    Even a corner-only contact is included; this deliberately conservative
    test can leave a diagonal contact pending, never fill a real white gap.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    delta = b - a
    lo = np.ceil(np.minimum(a, b) - 0.5).astype(int)
    hi = np.floor(np.maximum(a, b) + 0.5).astype(int)
    cells = []
    for y in range(lo[1], hi[1] + 1):
        for x in range(lo[0], hi[0] + 1):
            enter, leave = 0.0, 1.0
            for axis, coordinate in enumerate((x, y)):
                low, high = coordinate - 0.5, coordinate + 0.5
                if abs(delta[axis]) <= 1e-14:
                    if not low <= a[axis] <= high:
                        leave = -1.0
                        break
                else:
                    t0, t1 = sorted(((low - a[axis]) / delta[axis],
                                     (high - a[axis]) / delta[axis]))
                    enter, leave = max(enter, t0), min(leave, t1)
            if enter <= leave + 1e-12:
                cells.append([x, y])
    return cells


def _port_indices(obj, end, marker):
    """Use only a bounded existing terminal run to locate one observed port."""
    g = obj["geometry"]
    if obj["kind"] == "LINE":
        g = {"points": [g["start"], g["end"]], "bulges": [0.0, 0.0]}
    points = _dense_geometry(g, step=0.25)
    if end:
        points = points[::-1]
    length = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    width = float(marker["source_evidence"]["ring_geometry"]["stroke_width_px"])
    pixels = np.unique(np.rint(points[length <= max(3.0, 2 * width + 2)]).astype(int), axis=0)
    matches = []
    for index, port in enumerate(marker["source_evidence"]["contact_ports"]):
        runs = port["source_runs_y_x0_x1"]
        count = sum(any(y == row and left <= x < right for row, left, right in runs) for x, y in pixels)
        if count >= 2:
            matches.append(index)
    return matches


def _terminal_cells(obj, end):
    """Keep an exterior witness separate from a possibly already-on-ring end.

    The source graph permits diagonal adjacencies.  A circle-side endpoint
    alone therefore cannot establish direct contact with the exterior lead;
    inspect the unchanged last three pixels of that actual lead as well.
    """
    g = obj["geometry"]
    if obj["kind"] == "LINE":
        g = {"points": [g["start"], g["end"]], "bulges": [0.0, 0.0]}
    points = _dense_geometry(g, step=0.125)
    if end:
        points = points[::-1]
    travelled, cells = 0.0, set()
    for a, b in zip(points, points[1:]):
        length = float(np.linalg.norm(b - a))
        if travelled + length > POLICY["existing_terminal_witness_length_px"]:
            b = a + (b - a) * ((POLICY["existing_terminal_witness_length_px"] - travelled) / length)
        cells.update(map(tuple, _segment_cells(a, b)))
        travelled += length
        if travelled >= POLICY["existing_terminal_witness_length_px"]:
            break
    return [list(point) for point in sorted(cells, key=lambda p: (p[1], p[0]))]


def _offer(gray, roi, obj, end, endpoint, direction, marker):
    # A separately certified source white gap is a proved non-connection,
    # not an unresolved contact to be repaired or snapped back onto the ring.
    gap_proof = obj.get("source_evidence", {}).get("circle_white_gap_protection", {})
    if any(row.get("endpoint_number") == end and row.get("circle_id") == marker["id"]
           for row in gap_proof.get("ends", [])):
        return None
    geometry = _circle(marker)
    center, radius = np.asarray(geometry["center"], float), float(geometry["radius_px"])
    radial = endpoint - center
    gap = float(np.linalg.norm(radial) - radius)
    width = float(marker["source_evidence"]["ring_geometry"]["stroke_width_px"])
    bound = min(POLICY["absolute_extension_limit_px"],
                width * POLICY["maximum_extension_stroke_widths"] + POLICY["existing_native_fit_allowance_px"])
    search = width * POLICY["candidate_search_stroke_widths"] + POLICY["existing_native_fit_allowance_px"]
    if gap <= POLICY["endpoint_precision_px"] or gap > search:
        return None
    row = {"object_id": obj["id"], "endpoint_number": end, "circle_id": marker["id"],
           "accepted": False, "original_endpoint_px": endpoint.tolist(),
           "original_radial_gap_px": gap, "maximum_extension_px": bound}
    if gap > bound:
        row["reason"] = "NEARBY_END_OUTSIDE_BOUNDED_CONTACT_RESTORATION_RANGE"
        return row
    projection = float(radial @ direction)
    discriminant = projection ** 2 - (float(radial @ radial) - radius ** 2)
    if projection >= 0 or discriminant <= 0:
        row["reason"] = "EXISTING_END_TANGENT_DOES_NOT_ENTER_THE_CIRCLE"
        return row
    length = -projection - math.sqrt(discriminant)
    if not 0 < length <= bound:
        row["reason"] = "TANGENT_EXTENSION_EXCEEDS_ONE_OBSERVED_STROKE_WIDTH_PLUS_EXISTING_FIT_ALLOWANCE"
        return row
    target = endpoint + length * direction
    if not (roi[0] <= target[0] < roi[2] and roi[1] <= target[1] < roi[3]):
        row["reason"] = "CONTACT_OUTSIDE_CURRENT_ROI"
        return row
    ports = _port_indices(obj, end, marker)
    if len(ports) != 1:
        row.update(reason="EXISTING_TERMINAL_DOES_NOT_HAVE_ONE_UNIQUE_OBSERVED_CIRCLE_PORT", matching_ports=ports)
        return row
    cells = _segment_cells(endpoint, target)
    witness_cells = _terminal_cells(obj, end)
    all_cells = sorted(set(map(tuple, cells + witness_cells)), key=lambda p: (p[1], p[0]))
    black = bool(cells) and bool(witness_cells) and all(
        0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]
        and gray[y, x] < POLICY["source_threshold"] for x, y in all_cells)
    if not black:
        row.update(reason="DIRECT_TERMINAL_TO_CIRCLE_CONTACT_CONTAINS_ORIGINAL_WHITE_PIXEL",
                   direct_segment_cells_xy=cells, existing_terminal_witness_cells_xy=witness_cells)
        return row
    pixels = np.asarray(all_cells, int)
    x0, y0 = pixels.min(axis=0)
    x1, y1 = pixels.max(axis=0) + 1
    row.update(
        accepted=True, reason="DIRECT_ORIGINAL_INK_CONTACT_TO_MEASURED_CIRCLE",
        restored_endpoint_px=target.tolist(), extension_length_px=float(length),
        endpoint_direction=direction.tolist(), circle_geometry=deepcopy(geometry),
        circle_source_crop_sha256=marker["source_evidence"]["crop_sha256"],
        observed_port_index=ports[0], direct_segment_cells_xy=cells,
        existing_terminal_witness_cells_xy=witness_cells,
        source_crop_xyxy_px=[int(x0), int(y0), int(x1), int(y1)],
        source_crop_sha256=hashlib.sha256(np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()).hexdigest(),
        every_intersected_source_pixel_is_black=True, source_pixels_modified=False,
        source_path_points_modified=False, external_connection_in_marker_block=False,
    )
    return row


def _apply_geometry(obj, ends):
    result = deepcopy(obj["geometry"])
    for row in sorted(ends, key=lambda r: r["endpoint_number"]):
        end, target = row["endpoint_number"], row["restored_endpoint_px"]
        if obj["kind"] == "LINE":
            result["start" if end == 0 else "end"] = list(target)
        elif end == 0:
            result["points"] = [list(target)] + result["points"]
            result["bulges"] = [0.0] + result.get("bulges", [0.0] * (len(result["points"]) - 1))
        else:
            result.setdefault("bulges", [0.0] * len(result["points"]))
            if result["bulges"][-1] != 0:
                raise ValueError("UNUSED_LAST_BULGE_NOT_ZERO")
            result["points"].append(list(target))
            result["bulges"].append(0.0)
    return result


def restore_circle_endpoint_contacts(gray, roi, objects):
    """Return independently edited replacements; never mutate caller objects."""
    originals = [_original(obj) for obj in objects]
    if len({obj["id"] for obj in originals}) != len(originals):
        raise ValueError("CIRCLE_CONTACT_OBJECT_IDS_NOT_UNIQUE")
    circles = [obj for obj in originals if obj.get("kind") in ("CIRCLE", "CIRCULAR_MARKER")
               and verify_circle_source_evidence(gray, roi, obj).get("pass") is True]
    decisions = []
    for obj in originals:
        for end, endpoint, direction in _ends(obj):
            for marker in circles:
                row = _offer(gray, roi, obj, end, endpoint, direction, marker)
                if row:
                    decisions.append(row)
    accepted = [row for row in decisions if row["accepted"]]
    for row in accepted:
        same_end = [r for r in accepted if (r["object_id"], r["endpoint_number"]) == (row["object_id"], row["endpoint_number"])]
        same_port = [r for r in accepted if (r["circle_id"], r["observed_port_index"]) == (row["circle_id"], row["observed_port_index"])]
        if len(same_end) != 1 or len(same_port) != 1:
            row.update(accepted=False, reason="CONTACT_HAS_AMBIGUOUS_EXISTING_END_OR_CIRCLE_PORT")
    replacements, changes = [], []
    for obj in originals:
        ends = [row for row in decisions if row["accepted"] and row["object_id"] == obj["id"]]
        if not ends:
            continue
        if obj["kind"] == "CONNECTION_PATH" and len(obj["geometry"]["points"]) + len(ends) > 48:
            for row in ends:
                row.update(accepted=False, reason="EXISTING_NATIVE_VERTEX_BUDGET_MUST_REMAIN_UNCHANGED")
            continue
        replacement = deepcopy(obj)
        replacement["geometry"] = _apply_geometry(obj, ends)
        certificate = {
            "schema": POLICY["version"], "policy": dict(POLICY),
            "original_geometry": deepcopy(obj["geometry"]),
            "original_geometry_sha256": _digest(obj["geometry"]),
            "original_source_evidence_sha256": _digest(obj.get("source_evidence", {})),
            "original_source_path_points_sha256": _digest(obj.get("source_evidence", {}).get("source_path_points")),
            "restored_geometry_sha256": _digest(replacement["geometry"]),
            "ends": deepcopy(ends),
            "same_independent_object_id_retained": True,
            "existing_geometry_removed": False, "original_source_records_modified": False,
            "polyline_old_vertices_and_bulges_retained": obj["kind"] == "CONNECTION_PATH",
        }
        replacement.setdefault("source_evidence", {})[FIELD] = certificate
        replacements.append(replacement)
        changes.append({"old_object_id": obj["id"], "result_object_id": obj["id"],
                        "action": "EXTEND_SAME_INDEPENDENT_OBJECT_WITH_DIRECT_SOURCE_CONTACT",
                        "original_geometry_sha256": certificate["original_geometry_sha256"],
                        "result_geometry_sha256": certificate["restored_geometry_sha256"],
                        "restored_endpoint_count": len(ends), "retired": False,
                        "original_source_records_modified": False})
    return {"schema": POLICY["version"], "policy": dict(POLICY), "replacements": replacements,
            "changes": changes, "decisions": decisions,
            "summary": {"modified_existing_independent_objects": len(replacements),
                        "restored_external_endpoints": sum(len(obj["source_evidence"][FIELD]["ends"]) for obj in replacements),
                        "pending_nearby_contacts": sum(not row["accepted"] for row in decisions),
                        "new_formal_objects": 0, "retired_objects": 0,
                        "new_OCR_calls": 0, "source_pixels_modified": False}}


def verified_original_geometry(gray, roi, obj, objects, actual_geometry=None):
    """Cold replay binds new ends to raw pixels and the unaltered old object."""
    certificate = obj["source_evidence"][FIELD]
    if certificate.get("schema") != POLICY["version"] or certificate.get("policy") != POLICY:
        raise ValueError("CIRCLE_CONTACT_POLICY_CHANGED")
    original = _original(obj)
    if (_digest(original["geometry"]) != certificate["original_geometry_sha256"]
            or _digest(original.get("source_evidence", {})) != certificate["original_source_evidence_sha256"]
            or _digest(original.get("source_evidence", {}).get("source_path_points")) != certificate["original_source_path_points_sha256"]):
        raise ValueError("CIRCLE_CONTACT_ORIGINAL_GEOMETRY_OR_SOURCE_RECORD_CHANGED")
    if not certificate.get("same_independent_object_id_retained") or certificate.get("existing_geometry_removed") is not False:
        raise ValueError("CIRCLE_CONTACT_CHANGED_OLD_OBJECT_OWNERSHIP")
    ends = certificate["ends"]
    if not 1 <= len(ends) <= 2 or len({r["endpoint_number"] for r in ends}) != len(ends):
        raise ValueError("CIRCLE_CONTACT_INVALID_ENDPOINT_SET")
    by_id = {item["id"]: _original(item) for item in objects}
    if len(by_id) != len(objects) or obj["id"] not in by_id:
        raise ValueError("CIRCLE_CONTACT_OBJECT_BINDING_NOT_UNIQUE")
    for claimed in ends:
        marker = by_id[claimed["circle_id"]]
        if marker["kind"] not in ("CIRCLE", "CIRCULAR_MARKER") or verify_circle_source_evidence(gray, roi, marker).get("pass") is not True:
            raise ValueError("CIRCLE_CONTACT_TARGET_SOURCE_NOT_VERIFIED")
        end = next((item for item in _ends(original) if item[0] == claimed["endpoint_number"]), None)
        replay = _offer(gray, roi, original, *end, marker) if end else None
        if not replay or not replay["accepted"] or _digest(replay) != _digest(claimed):
            raise ValueError("CIRCLE_CONTACT_RAW_ENDPOINT_PROOF_DOES_NOT_REPLAY")
        for other in by_id.values():
            for n, endpoint, direction in _ends(other):
                if (other["id"], n) == (obj["id"], claimed["endpoint_number"]):
                    continue
                offer = _offer(gray, roi, other, n, endpoint, direction, marker)
                if offer and offer["accepted"] and offer["observed_port_index"] == claimed["observed_port_index"]:
                    raise ValueError("CIRCLE_CONTACT_PORT_HAS_ANOTHER_ELIGIBLE_END")
        for other in by_id.values():
            if other["id"] == marker["id"] or other["kind"] not in ("CIRCLE", "CIRCULAR_MARKER"):
                continue
            offer = _offer(gray, roi, original, *end, other)
            if offer and offer["accepted"]:
                if verify_circle_source_evidence(gray, roi, other).get("pass") is True:
                    raise ValueError("CIRCLE_CONTACT_END_HAS_ANOTHER_ELIGIBLE_CIRCLE")
    expected = _apply_geometry(original, ends)
    if _digest(expected) != certificate["restored_geometry_sha256"] or _digest(expected) != _digest(obj["geometry"]):
        raise ValueError("CIRCLE_CONTACT_RESTORED_GEOMETRY_CHANGED")
    if actual_geometry is not None:
        keys = ("start", "end") if obj["kind"] == "LINE" else ("points", "bulges")
        for key in keys:
            actual, planned = np.asarray(actual_geometry[key], float), np.asarray(expected[key], float)
            if actual.shape != planned.shape or not np.isfinite(actual).all() or not np.allclose(actual, planned, atol=1e-7, rtol=0):
                raise ValueError("SAVED_CIRCLE_CONTACT_GEOMETRY_DIFFERS_FROM_BOUND_PROOF")
        if obj["kind"] == "CONNECTION_PATH" and actual_geometry.get("closed"):
            raise ValueError("SAVED_CIRCLE_CONTACT_PATH_IS_CLOSED")
        actual_ends = {n: endpoint for n, endpoint, _ in _ends({**obj, "geometry": actual_geometry})}
        for row in ends:
            circle = _circle(by_id[row["circle_id"]])
            if abs(np.linalg.norm(actual_ends[row["endpoint_number"]] - circle["center"]) - circle["radius_px"]) > POLICY["endpoint_precision_px"]:
                raise ValueError("SAVED_CONNECTION_END_DOES_NOT_TOUCH_ACTUAL_CIRCLE_CENTERLINE")
    return deepcopy(original["geometry"])


def cold_circle_endpoint_contacts(path, doc, gray, roi, dpi):
    """Read real saved native endpoints; a plan or a broad source gate is insufficient."""
    from pathlib import Path
    from .cad_io import identity, sha, circular_candidate_contract

    actual = {}
    flags = set()
    targets = set()
    for entity in doc.modelspace():
        if entity.dxf.layer == "REVIEW":
            continue
        ident = identity(entity)
        actual.setdefault(ident["id"], []).append(entity)
        if ident.get("circle_endpoint_contacts"):
            flags.add(ident["id"])
    targets.update(flags)
    try:
        meta = json.loads(Path(path).with_suffix(".objects.json").read_text(encoding="utf-8"))
        objects = meta["objects"]
        claims = {obj["id"] for obj in objects if obj.get("source_evidence", {}).get(FIELD)}
        targets = flags | claims
        if not targets:
            return []
        if meta["dxf_sha256"] != sha(path) or meta["roi_xyxy_px"] != list(roi) or meta["dpi"] != dpi:
            raise ValueError("CIRCLE_CONTACT_SIDECAR_NOT_BOUND_TO_SAVED_DXF")
        if flags != claims:
            raise ValueError("CIRCLE_CONTACT_SAVED_FLAG_AND_SOURCE_CLAIM_DIFFER")
        by_id = {obj["id"]: obj for obj in objects}
        written = {obj["id"]: obj for obj in meta["written"]}
        if len(by_id) != len(objects):
            raise ValueError("CIRCLE_CONTACT_DUPLICATE_CANDIDATE_ID")
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        if not targets:
            return []
        return [{"id": oid, "type": "CIRCLE_ENDPOINT_CONTACT", "pass": False, "failure": str(exc)} for oid in sorted(targets)]
    mm = 25.4 / dpi

    def px(p):
        return np.array([p[0] / mm + roi[0], roi[3] - p[1] / mm])

    rows = []
    for oid in sorted(targets):
        row = {"id": oid, "type": "CIRCLE_ENDPOINT_CONTACT", "pass": False}
        try:
            obj = by_id[oid]
            if len(actual.get(oid, [])) != 1:
                raise ValueError("CIRCLE_CONTACT_REQUIRES_ONE_INDEPENDENT_MODELSPACE_ENTITY")
            entity = actual[oid][0]
            if entity.dxf.handle != written[oid]["handle"] or identity(entity)["kind"] != obj["kind"]:
                raise ValueError("CIRCLE_CONTACT_SAVED_ENTITY_BINDING_CHANGED")
            if obj["kind"] == "LINE" and entity.dxftype() == "LINE":
                if (entity.dxf.start.z != 0 or entity.dxf.end.z != 0
                        or entity.dxf.get("thickness", 0) != 0
                        or tuple(entity.dxf.extrusion) != (0, 0, 1)):
                    raise ValueError("CIRCLE_CONTACT_LINE_IS_NOT_PLANAR")
                geometry = {"start": px(entity.dxf.start).tolist(), "end": px(entity.dxf.end).tolist()}
            elif obj["kind"] == "CONNECTION_PATH" and entity.dxftype() == "LWPOLYLINE":
                vertices = list(entity.get_points("xyseb"))
                if (any(p[2] != 0 or p[3] != 0 for p in vertices)
                        or entity.dxf.get("const_width", 0) != 0
                        or entity.dxf.get("elevation", 0) != 0
                        or entity.dxf.get("thickness", 0) != 0
                        or tuple(entity.dxf.extrusion) != (0, 0, 1)):
                    raise ValueError("CIRCLE_CONTACT_PATH_HAS_WIDTH_OR_NONPLANAR_TRANSFORM")
                geometry = {"points": [px(p).tolist() for p in vertices],
                            "bulges": [-float(p[4]) for p in vertices], "closed": entity.closed}
            else:
                raise ValueError("CIRCLE_CONTACT_EXTERNAL_ENTITY_TYPE_CHANGED")
            verified_original_geometry(gray, roi, obj, objects, geometry)
            for end in obj["source_evidence"][FIELD]["ends"]:
                circle_id = end["circle_id"]
                if len(actual.get(circle_id, [])) != 1:
                    raise ValueError("CIRCLE_CONTACT_ACTUAL_TARGET_MISSING_OR_DUPLICATED")
                checks = circular_candidate_contract(actual[circle_id][0], by_id[circle_id], px, mm)
                if not all(value is True for value in checks.values()):
                    raise ValueError("CIRCLE_CONTACT_SAVED_TARGET_GEOMETRY_DIFFERS_FROM_SOURCE")
            row.update(pass_=True, restored_endpoints=len(obj["source_evidence"][FIELD]["ends"]),
                       actual_saved_geometry_checked=True, original_source_records_preserved=True,
                       external_entity_is_independent=True)
            row["pass"] = row.pop("pass_")
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, ArithmeticError) as exc:
            row["failure"] = str(exc)
        rows.append(row)
    return rows
