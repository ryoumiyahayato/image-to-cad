"""Source responsibility for contacts with retained native graphic members.

This is a refusal gate for finite attached-stroke proposals, not a new discovery
or old-object repair stage.  It follows the ordinary writer's block members.
Curves are bounded from their actual parameters, never replaced by chords.
The older duplicate and complete-text source gates remain independently required.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import connections as paths
from .circle_endpoint_contacts import _segment_cells
from .door_completion import native_members


SCHEMA = "source-attached-prior-native-contacts-v1"
POLICY = {
    "version": "all-prior-finite-graphic-member-source-contacts-v1",
    "native_coordinate_precision_px": 1e-7,
    "minimum_independent_source_port_chord_px": 4.0,
    "maximum_prior_port_native_distance_px": 2.0,
    "maximum_guest_port_native_distance_px": 1.5,
    "port_support_native_scope": "CONTIGUOUS_FINITE_LINEAR_MEMBER_CHAIN_CONTAINING_ACTUAL_CONTACT_SEGMENT",
    "prior_member_requires_its_own_unchanged_source_path": True,
    "shared_core_never_licenses_positive_native_length": True,
    "unsupported_curve_contact": "PENDING_IF_TRUE_PARAMETER_BOUND_IS_NOT_DISJOINT",
    "text_source_conflicts": "DELEGATED_TO_EXISTING_COMPLETE_TEXT_INTERSECTION_GATE",
    "old_old_contacts_examined": False,
    "native_geometry_modified": False,
}


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _points(value):
    result = np.asarray(value, float)
    if result.ndim != 2 or result.shape[1:] != (2,) or not np.isfinite(result).all():
        raise ValueError("NATIVE_CONTACT_REQUIRES_FINITE_XY_POINTS")
    return result


def _writer_line_member(member):
    # Wall members and retained frame remainders are always written as LINE by
    # cad_io, even if their incidental stored kind label says something else.
    geometry = member["geometry"]
    return {"kind": "LINE", "geometry": {"start": geometry["start"], "end": geometry["end"]},
            "source_evidence": member.get("source_evidence") or {}}


def _members(obj):
    """Use source coordinates and the member order of cad_io.export_objects.

    Member source evidence is not inherited from an unrelated parent path.
    A missing member witness refuses a real point contact without changing it.
    """
    kind, geometry = obj["kind"], obj["geometry"]
    if kind == "WALL_SEGMENT":
        values = [(i, ["members", i], _writer_line_member(member))
                  for i, member in enumerate(geometry["members"])]
    elif kind == "DOOR":
        values = [(i, ["native_members", i], member) for i, member in enumerate(native_members(obj))]
    elif kind == "ROOM_LABEL":
        points = geometry["frame_points"]
        values = [(0, ["frame_points"], {"kind": "CONNECTION_PATH", "geometry": {
            "points": points, "bulges": [0.0] * len(points), "closed": True}}),
            (1, ["text_geometry"], {"kind": "TEXT", "geometry": geometry["text_geometry"]})]
        values += [(i + 2, ["frame_source_remainders", i], _writer_line_member(member))
                   for i, member in enumerate(geometry.get("frame_source_remainders", []))]
    elif kind == "CIRCULAR_MARKER":
        values = [(0, ["circle_geometry"], {"kind": "CIRCLE", "geometry": geometry["circle_geometry"]}),
                  (1, ["text_geometry"], {"kind": "TEXT", "geometry": geometry["text_geometry"]})]
    elif kind == "TEXT_GROUP":
        values = [(i, ["text_members", i], {"kind": "TEXT", "geometry": member})
                  for i, member in enumerate(geometry["text_members"])]
    else:
        values = [(None, [], obj)]
    for index, location, member in values:
        yield {"object_id": obj["id"], "member_index": index, "member_path": location,
               "kind": member["kind"], "geometry": member["geometry"],
               "source_evidence": member.get("source_evidence") or {}}


def _bbox(points):
    points = _points(points)
    low, high = points.min(axis=0), points.max(axis=0)
    return [float(low[0]), float(low[1]), float(high[0]), float(high[1])]


def _arc_bbox(center, radius, start, sweep, endpoints=()):
    center = _points([center])[0]
    radius, start, sweep = float(radius), float(start), float(sweep)
    if not math.isfinite(radius) or radius <= 0 or not math.isfinite(start + sweep):
        raise ValueError("NATIVE_CONTACT_CURVE_PARAMETERS_INVALID")
    if abs(sweep) >= 2 * math.pi:
        return _bbox([center - radius, center + radius])
    angles = [start, start + sweep]
    for angle in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
        progress = ((angle - start) * math.copysign(1.0, sweep)) % (2 * math.pi)
        if progress <= abs(sweep) + 1e-12:
            angles.append(angle)
    points = [center + radius * np.array([math.cos(a), math.sin(a)]) for a in angles]
    points.extend(endpoints)
    return _bbox(points)


def _parts(member):
    """Exact linear parts, or conservative bounds of actual finite curves."""
    kind, geometry = member["kind"], member["geometry"]
    if kind == "LINE":
        points = _points([geometry["start"], geometry["end"]])
        spans = [(points[0], points[1], 0.0)]
    elif kind == "CONNECTION_PATH":
        points = _points(geometry["points"])
        bulges = geometry.get("bulges", [0.0] * len(points))
        if len(points) < 2 or len(bulges) != len(points):
            raise ValueError("NATIVE_CONTACT_PATH_PARAMETERS_INVALID")
        following = np.vstack([points[1:], points[:1]]) if geometry.get("closed") else points[1:]
        spans = list(zip(points, following, bulges))
    elif kind in ("CIRCLE", "ARC"):
        center, radius = geometry["center"], geometry["radius_px"]
        if kind == "CIRCLE":
            bounds = _arc_bbox(center, radius, 0.0, 2 * math.pi)
        else:
            start, end = float(geometry["start_deg_image"]), float(geometry["end_deg_image"])
            sweep = float(geometry.get("sweep_deg_image", end - start))
            delta = (start + sweep - end + 180.0) % 360.0 - 180.0
            if not 0 < abs(sweep) < 360 or abs(delta) > 1e-7:
                raise ValueError("NATIVE_CONTACT_ARC_SWEEP_DIFFERS_FROM_EXPORTED_ENDPOINTS")
            bounds = _arc_bbox(center, radius, math.radians(start), math.radians(sweep))
        return [{"segment_index": 0, "kind": kind, "bbox_xyxy_px": bounds}]
    else:
        raise ValueError("NATIVE_CONTACT_MEMBER_KIND_NOT_SUPPORTED:" + str(kind))
    result = []
    for index, (a, b, bulge) in enumerate(spans):
        bulge = float(bulge)
        chord = float(np.linalg.norm(b - a))
        if not math.isfinite(bulge) or chord == 0.0:
            raise ValueError("NATIVE_CONTACT_SEGMENT_PARAMETERS_INVALID")
        if bulge == 0.0:
            result.append({"segment_index": index, "kind": "LINE", "a": a, "b": b,
                           "bbox_xyxy_px": _bbox([a, b])})
        else:
            normal = np.array([-(b - a)[1], (b - a)[0]]) / chord
            center = (a + b) / 2 + normal * chord * (1 - bulge * bulge) / (4 * bulge)
            radius = float(np.linalg.norm(a - center))
            start = math.atan2(*(a - center)[::-1])
            bounds = _arc_bbox(center, radius, start, 4 * math.atan(bulge), endpoints=[a, b])
            result.append({"segment_index": index, "kind": "BULGE_ARC", "bbox_xyxy_px": bounds})
    return result


def _disjoint(left, right):
    # The same source-coordinate precision as the retained duplicate-length gate.
    # Include float construction error in curve bounds; no geometry is changed.
    padding = max(POLICY["native_coordinate_precision_px"],
                  64 * max(math.ulp(float(v)) for v in [*left, *right]))
    return any(left[i + 2] < right[i] - padding or right[i + 2] < left[i] - padding for i in (0, 1))


def _segment_contact(a, b, c, d):
    epsilon = POLICY["native_coordinate_precision_px"]
    vector, other = b - a, d - c
    length, other_length = float(np.linalg.norm(vector)), float(np.linalg.norm(other))
    axis = vector / length
    perpendicular = np.abs((np.asarray([c, d]) - a) @ np.array([-axis[1], axis[0]]))
    if float(perpendicular.max()) <= epsilon:
        low, high = sorted(float((point - a) @ axis) for point in (c, d))
        start, end = max(0.0, low), min(length, high)
        if end < start - epsilon:
            return None
        if end - start > epsilon:
            return {"classification": "POSITIVE_NATIVE_LENGTH_OVERLAP",
                    "overlap_endpoints_px": [(a + start * axis).tolist(), (a + end * axis).tolist()],
                    "positive_overlap_length_px": end - start}
        point = a + (start + end) / 2 * axis
        fractions = [float((point - a) @ vector / (length * length)),
                     float((point - c) @ other / (other_length * other_length))]
    else:
        matrix = np.column_stack((vector, -other))
        determinant = float(np.linalg.det(matrix))
        if abs(determinant) <= 64 * np.finfo(float).eps * max(length * other_length, 1.0):
            return None
        u, v = np.linalg.solve(matrix, c - a)
        if not (-epsilon / length <= u <= 1 + epsilon / length
                and -epsilon / other_length <= v <= 1 + epsilon / other_length):
            return None
        point, fractions = a + u * vector, [float(u), float(v)]
    return {"classification": "FINITE_NATIVE_POINT_CONTACT", "point_px": point.tolist(),
            "finite_segment_fractions": fractions}


def _edges(points):
    return {tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(points, points[1:]) if list(a) != list(b)}


def _validate_old_source(source, graph, member):
    evidence = member["source_evidence"]
    origin = np.asarray(graph.origin, int)
    box = [int(origin[0]), int(origin[1]), int(origin[0] + graph.w), int(origin[1] + graph.h)]
    actual_hash = hashlib.sha256(source[box[1]:box[3], box[0]:box[2]].tobytes()).hexdigest()
    if (evidence.get("source_pixels_modified") is not False
            or evidence.get("original_source_crop_xyxy_px") != box
            or evidence.get("original_source_crop_array_sha256") != actual_hash):
        return {"pass": False, "reason": "PRIOR_MEMBER_ORIGINAL_SOURCE_BINDING_MISSING_OR_CHANGED"}, set()
    try:
        raw = _points(evidence.get("source_path_points") or [])
    except (ValueError, TypeError):
        return {"pass": False, "reason": "PRIOR_MEMBER_HAS_NO_INDEPENDENT_ORIGINAL_SOURCE_PATH"}, set()
    if (len(raw) < 2 or not np.array_equal(raw, np.rint(raw))
            or np.any(np.max(np.abs(np.diff(raw, axis=0)), axis=1) > 1)
            or np.any(raw < origin) or np.any(raw >= origin + [graph.w, graph.h])):
        return {"pass": False, "reason": "PRIOR_MEMBER_ORIGINAL_SOURCE_PATH_IS_NOT_A_FINITE_PIXEL_CHAIN"}, set()
    pixels = raw.astype(int)
    if not np.all(source[pixels[:, 1], pixels[:, 0]] < paths.POLICY["source_threshold"]):
        return {"pass": False, "reason": "PRIOR_MEMBER_ORIGINAL_SOURCE_PATH_CONTAINS_WHITE"}, set()
    return {"pass": True, "original_source_crop_xyxy_px": box,
            "original_source_crop_array_sha256": actual_hash,
            "original_source_path_sha256": _digest(raw.tolist()),
            "original_source_path_pixel_count": len(raw)}, _edges(raw)


def _linear_chain(parts, segment_index):
    """Preserve the result under harmless straight-segment subdivision.

    The actual contact's segment is still recorded. Port evidence may continue
    into neighboring linear segments of this same editable member, stopping at
    an unsupported curved segment. It cannot borrow another block member.
    """
    first = last = segment_index
    while first > 0 and parts[first - 1]["kind"] == "LINE":
        first -= 1
    while last + 1 < len(parts) and parts[last + 1]["kind"] == "LINE":
        last += 1
    chain = [parts[first]["a"], *(part["b"] for part in parts[first:last + 1])]
    return np.asarray(chain), [part["segment_index"] for part in parts[first:last + 1]]


def _port_support(graph, nid, source_edges, native_chain, limit, allowed_edge_ids=None):
    points, segment_indices = native_chain
    result = []
    for port in sorted(graph.nodes[nid]["edges"]):
        if allowed_edge_ids is not None and port[0] not in allowed_edge_ids:
            continue
        samples = graph.xy(graph.oriented(port))
        chords = np.linalg.norm(samples - samples[0], axis=1)
        adequate = np.flatnonzero(chords >= POLICY["minimum_independent_source_port_chord_px"])
        if not len(adequate):
            continue
        samples = samples[:int(adequate[0]) + 1]
        observed_edges = _edges(samples)
        if not observed_edges or not observed_edges <= source_edges:
            continue
        residual = paths._maximum_point_to_polyline_distance(samples, points)
        if residual > limit:
            continue
        result.append({"port": list(port), "source_points_px": samples.tolist(),
                       "source_chord_px": float(np.linalg.norm(samples[-1] - samples[0])),
                       "native_linear_segment_indices": segment_indices,
                       "maximum_distance_to_actual_finite_member_linework_px": float(residual)})
    return result


def _point_source_proof(source, graph, row, member, new_chain, old_chain, point,
                        cores, owner, anchors, source_cache):
    key = (member["object_id"], tuple(member["member_path"]))
    if key not in source_cache:
        source_cache[key] = _validate_old_source(source, graph, member)
    binding, old_edges = source_cache[key]
    if not binding["pass"]:
        return {"pass": False, "reason": binding["reason"], "prior_source_binding": binding}
    cells = np.asarray(_segment_cells(point, point), int)
    if (not len(cells) or np.any(cells < 0) or np.any(cells >= [source.shape[1], source.shape[0]])
            or not np.all(source[cells[:, 1], cells[:, 0]] < paths.POLICY["source_threshold"])):
        return {"pass": False, "reason": "FINITE_NATIVE_POINT_IS_NOT_ENTIRELY_ORIGINAL_INK"}
    new_edges = _edges(row["source_path_px"])
    accepted, attempts = [], []
    for nid in sorted(set(row["source_node_ids"]) & cores.keys()):
        core = cores[nid]
        pixels = np.asarray(core["source_core_pixels"], float)
        if not (core.get("pass") is True and nid in graph.nodes
                and np.any(np.all(np.abs(pixels - point) <= 0.5 + POLICY["native_coordinate_precision_px"], axis=1))):
            continue
        if sorted(map(tuple, pixels)) != sorted(map(tuple, graph.xy(graph.nodes[nid]["pixels"]))):
            attempts.append({"node_id": nid, "reason": "CONTACT_CORE_DIFFERS_FROM_CURRENT_SOURCE_GRAPH"})
            continue
        new_ports = _port_support(graph, nid, new_edges, new_chain,
                                  POLICY["maximum_guest_port_native_distance_px"],
                                  set(row["source_graph_edge_ids"]))
        old_ports = _port_support(graph, nid, old_edges, old_chain,
                                  POLICY["maximum_prior_port_native_distance_px"])
        new_ids, old_ids = ({tuple(p["port"]) for p in proof} for proof in (new_ports, old_ports))
        reason = None
        if not new_ids or not old_ids:
            reason = "POINT_HAS_NO_INDEPENDENT_FINITE_SOURCE_PORT_FOR_BOTH_MEMBERS"
        elif new_ids & old_ids:
            reason = "SHARED_EXTERNAL_SOURCE_PORT_IS_NOT_AN_INDEPENDENT_CONTACT"
        elif owner and owner["id"] == member["object_id"]:
            expected = {tuple(p) for p in anchors.get(nid, {}).get("ports", [])}
            # The caller's existing owner gate proves its expected full pair.
            # This additional gate also checks the old member's actual source.
            if not expected or not old_ids <= expected:
                reason = "CURRENT_OWNER_CONTACT_HAS_NO_INDEPENDENT_FROZEN_PORT_WITNESS"
        proof = {"node_id": nid, "source_core_pixels": pixels.tolist(),
                 "actual_contact_closed_source_cells": cells.tolist(),
                 "guest_original_ports": new_ports, "prior_member_original_ports": old_ports}
        if reason:
            attempts.append({**proof, "reason": reason})
        else:
            accepted.append(proof)
    if len(accepted) != 1:
        return {"pass": False, "reason": "POINT_HAS_NO_UNIQUE_INDEPENDENT_ORIGINAL_SOURCE_CONTACT",
                "prior_source_binding": binding, "eligible_source_contacts": accepted,
                "rejected_source_contacts": attempts}
    return {"pass": True, "classification": "ALLOWED_ORIGINAL_SOURCE_POINT_CONTACT",
            "prior_source_binding": binding, **accepted[0]}


def check_prior_native_contacts(source, rows, prior_objects, *, graph, cores, owner=None, anchors=None):
    """Return replayable all-prior contact evidence before any new adoption.

    ``cores`` and ``graph`` are rebuilt from the current unchanged source. Prior
    source observations are checked separately; a candidate core cannot confer
    ownership on a prior line. Caller must still apply its new/new and owner
    expected-contact, duplicate-length and complete-text source gates.
    """
    source, anchors = np.asarray(source), anchors or {}
    report = {"schema": SCHEMA, "policy": deepcopy(POLICY), "producer_sha256": producer_sha256(),
              "pass": True, "prior_object_count": len(prior_objects), "prior_member_inventory": [],
              "pair_checks": [], "unsupported_contacts": [], "positive_length_overlaps": [],
              "unexpected_point_contacts": [], "allowed_source_point_contacts": [],
              "linear_segment_pair_count": 0, "curve_segment_pair_count": 0,
              "pairs_excluded_by_disjoint_true_geometry_bounds": 0,
              "text_member_count_delegated_to_existing_source_gate": 0,
              "existing_positive_length_and_complete_equivalence_gates_still_required": True}
    members = []
    for obj in sorted(prior_objects, key=lambda value: value["id"]):
        for member in _members(obj):
            identity = {key: deepcopy(member[key]) for key in ("object_id", "member_index", "member_path", "kind")}
            identity["native_member_geometry_sha256"] = _digest(member["geometry"])
            member["identity"] = identity
            if member["kind"] in ("TEXT", "MTEXT"):
                report["text_member_count_delegated_to_existing_source_gate"] += 1
                report["prior_member_inventory"].append({**identity, "scope": "EXISTING_COMPLETE_TEXT_SOURCE_GATE"})
                continue
            try:
                member["parts"] = _parts(member)
                member["bounds_error"] = None
            except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
                member["parts"], member["bounds_error"] = [], str(exc)
            report["prior_member_inventory"].append({**identity, "scope": "FINITE_GRAPHIC_CONTACTS",
                "parts": [{key: deepcopy(part[key]) for key in ("segment_index", "kind", "bbox_xyxy_px")}
                          for part in member["parts"]], "bounds_error": member["bounds_error"]})
            members.append(member)
    source_cache = {}
    for row in sorted(rows, key=lambda value: value["stroke_id"]):
        new_parts = _parts({"kind": "CONNECTION_PATH", "geometry": row["representation"]})
        if any(part["kind"] != "LINE" for part in new_parts):
            raise ValueError("ATTACHED_PRIOR_CONTACT_GATE_REQUIRES_LINEAR_NEW_STROKES")
        for member in members:
            identity = {"new_object_id": row["stroke_id"], **member["identity"]}
            check = {**identity, "pass": True, "point_contacts": [], "positive_length_overlaps": [],
                     "unsupported_curve_bound_contacts": []}
            if member["bounds_error"]:
                problem = {**identity, "reason": member["bounds_error"],
                           "classification": "PENDING_NATIVE_MEMBER_HAS_NO_RELIABLE_GEOMETRY_BOUND"}
                report["unsupported_contacts"].append(problem)
                check["unsupported_curve_bound_contacts"].append(problem)
            for new_part in new_parts:
                for old_part in member["parts"]:
                    category = "linear_segment_pair_count" if old_part["kind"] == "LINE" else "curve_segment_pair_count"
                    report[category] += 1
                    if _disjoint(new_part["bbox_xyxy_px"], old_part["bbox_xyxy_px"]):
                        report["pairs_excluded_by_disjoint_true_geometry_bounds"] += 1
                        continue
                    pair = {"new_segment_index": new_part["segment_index"],
                            "prior_member_segment_index": old_part["segment_index"]}
                    if old_part["kind"] != "LINE":
                        problem = {**identity, **pair, "curve_kind": old_part["kind"],
                                   "new_segment_bbox_xyxy_px": new_part["bbox_xyxy_px"],
                                   "curve_parameter_bbox_xyxy_px": old_part["bbox_xyxy_px"],
                                   "classification": "PENDING_UNSUPPORTED_CURVE_CONTACT",
                                   "actual_curve_intersection_asserted": False}
                        report["unsupported_contacts"].append(problem)
                        check["unsupported_curve_bound_contacts"].append(problem)
                        continue
                    hit = _segment_contact(new_part["a"], new_part["b"], old_part["a"], old_part["b"])
                    if hit is None:
                        continue
                    hit = {**pair, **hit}
                    if hit["classification"] == "POSITIVE_NATIVE_LENGTH_OVERLAP":
                        check["positive_length_overlaps"].append(hit)
                        report["positive_length_overlaps"].append({**identity, **hit})
                    else:
                        proof = _point_source_proof(source, graph, row, member,
                                                    _linear_chain(new_parts, new_part["segment_index"]),
                                                    _linear_chain(member["parts"], old_part["segment_index"]),
                                                    np.asarray(hit["point_px"]), cores, owner, anchors, source_cache)
                        hit["source_contact_proof"] = proof
                        check["point_contacts"].append(hit)
                        category = "allowed_source_point_contacts" if proof["pass"] else "unexpected_point_contacts"
                        report[category].append({**identity, **hit})
            if (check["point_contacts"] or check["positive_length_overlaps"]
                    or check["unsupported_curve_bound_contacts"]):
                check["pass"] = (not check["positive_length_overlaps"]
                                 and not check["unsupported_curve_bound_contacts"]
                                 and all(hit["source_contact_proof"]["pass"] for hit in check["point_contacts"]))
                report["pair_checks"].append(check)
    report["pass"] = all(check["pass"] for check in report["pair_checks"])
    return report
