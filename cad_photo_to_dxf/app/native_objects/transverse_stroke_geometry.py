"""Complete free-ended strokes crossing a separately adopted source path.

The source graph already distinguishes the four ports of these crossings.  The
ordinary connection pass intentionally leaves nearly straight chains to LINE
discovery; that assumption need not hold for short strokes inside shared ink.
This planner closes that responsibility gap without relaxing the connection
pass, assigning the whole connected component to a stroke, or choosing a case.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import connections as paths
from . import text_contact_geometry as contact
from .circle_endpoint_contacts import _segment_cells
from .contracts import stable_id
from .text_graph_support import four_port_source_core_proof


SCHEMA = "source-transverse-stroke-plan-v1"
POLICY = {
    "version": "complete-free-ended-strokes-with-shared-four-port-source-v1",
    "minimum_path_length_px": 20.0,
    "maximum_path_length_px": 120.0,
    "minimum_free_arm_length_px": 8.0,
    "maximum_straight_source_deviation_px": 1.5,
    "maximum_endpoint_cap_extent_px": 3.0,
    "minimum_crossing_axis_separation_deg": 45.0,
    "minimum_other_port_source_span_px": 4.0,
    "other_port_source_span_px": 12.0,
    "minimum_crossing_owner_length_ratio": 2.0,
    "maximum_owner_native_source_distance_px": 2.0,
    "minimum_parallel_companions": 1,
    "maximum_companion_axis_angle_deg": 12.0,
    "minimum_companion_length_ratio": 0.65,
    "minimum_companion_projected_overlap_fraction": 0.65,
    "minimum_companion_normal_separation_px": 4.0,
    "maximum_companion_separation_length_ratio": 0.8,
    "source_graph_pairing_is_reused_without_relaxation": True,
    "source_endpoints_and_all_competitors_required": True,
    "native_line_closed_pixel_cells_must_all_be_original_ink": True,
    "source_branches_deleted": False,
    "original_source_pixels_modified": False,
    "existing_objects_retired_by_this_planner": False,
    "crossing_owner_requires_complete_source_contact_adoption_receipt": True,
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _binding(obj):
    """Keep native identity and its original path observation together."""
    evidence = obj.get("source_evidence", {})
    return {
        **{key: deepcopy(obj[key]) for key in ("id", "kind", "layer", "geometry")},
        "source_evidence": {
            key: deepcopy(evidence.get(key))
            for key in (
                "source_path_points",
                "original_source_crop_xyxy_px",
                "original_source_crop_array_sha256",
                "source_pixels_modified",
                "text_contact_path",
            )
        },
    }


def _geometry(obj):
    geometry = obj["geometry"]
    if obj["kind"] == "CONNECTION_PATH" and not geometry.get("closed"):
        return geometry
    if obj["kind"] == "LINE":
        return {
            "points": [geometry["start"], geometry["end"]],
            "bulges": [0.0, 0.0],
            "closed": False,
        }
    return None


def _edge_key(a, b):
    return tuple(sorted((tuple(a), tuple(b))))


def _owners(source, context, prior_objects):
    owners, refusals = [], []
    for obj in prior_objects:
        geometry = _geometry(obj)
        evidence = obj.get("source_evidence", {})
        receipt = evidence.get("text_contact_path") or {}
        observation = receipt.get("path") or {}
        raw = np.asarray(evidence.get("source_path_points") or [], float)
        if geometry is None or raw.ndim != 2 or raw.shape[1:] != (2,) or len(raw) < 3:
            continue
        if not receipt:
            refusals.append(
                {
                    "id": obj["id"],
                    "reason": "NO_COMPLETE_SHARED_CONTACT_ADOPTION_RECEIPT",
                    "existing_native_object_preserved": True,
                }
            )
            continue
        if (
            receipt.get("schema") != "source-text-contact-native-path-v1"
            or receipt.get("geometry_plan_schema")
            not in (
                "source-structure-contact-path-plan-v1",
                "source-text-contact-path-plan-v1",
            )
            or receipt.get("path_sha256") != _digest(observation)
            or observation.get("source_path_px") != raw.tolist()
            or not observation.get("contact_continuations")
        ):
            refusals.append(
                {
                    "id": obj["id"],
                    "reason": "COMPLETE_SHARED_CONTACT_ADOPTION_RECEIPT_INVALID",
                    "existing_native_object_preserved": True,
                }
            )
            continue
        if (
            evidence.get("source_pixels_modified") is not False
            or evidence.get("original_source_crop_xyxy_px") != context.crop_bbox
            or evidence.get("original_source_crop_array_sha256")
            != context.source_crop_hash
            or not np.isfinite(raw).all()
            or not np.array_equal(raw, np.rint(raw))
        ):
            refusals.append(
                {
                    "id": obj["id"],
                    "reason": "CROSSING_OWNER_ORIGINAL_SOURCE_BINDING_CHANGED",
                    "existing_native_object_preserved": True,
                }
            )
            continue
        pixels = raw.astype(int)
        if (
            np.any(pixels[:, 0] < 0)
            or np.any(pixels[:, 1] < 0)
            or np.any(pixels[:, 0] >= source.shape[1])
            or np.any(pixels[:, 1] >= source.shape[0])
            or not np.all(
                source[pixels[:, 1], pixels[:, 0]] < paths.POLICY["source_threshold"]
            )
            or np.any(np.max(np.abs(np.diff(raw, axis=0)), axis=1) > 1)
        ):
            refusals.append(
                {
                    "id": obj["id"],
                    "reason": "CROSSING_OWNER_ORIGINAL_SOURCE_PATH_INVALID",
                    "existing_native_object_preserved": True,
                }
            )
            continue
        dense = paths._dense_geometry(geometry)
        if (
            paths._maximum_point_to_polyline_distance(raw, dense)
            > POLICY["maximum_owner_native_source_distance_px"]
        ):
            refusals.append(
                {
                    "id": obj["id"],
                    "reason": "CROSSING_OWNER_NATIVE_GEOMETRY_NO_LONGER_FOLLOWS_SOURCE",
                    "existing_native_object_preserved": True,
                }
            )
            continue
        owners.append(
            {
                "id": obj["id"],
                "binding": _binding(obj),
                "source_adjacencies": {_edge_key(a, b) for a, b in zip(raw, raw[1:])},
                "source_path_length_px": paths._length(raw),
                "native_geometry": geometry,
                "contact_continuations": deepcopy(observation["contact_continuations"]),
                "source_contact_receipt_identity": {
                    key: receipt.get(key)
                    for key in (
                        "schema",
                        "source_sha256",
                        "plan_sha256",
                        "path_index",
                        "path_sha256",
                        "geometry_plan_schema",
                    )
                },
            }
        )
    return owners, refusals


def _angle(a, b):
    return math.degrees(math.acos(float(np.clip(np.asarray(a) @ np.asarray(b), -1, 1))))


def _unit(v):
    return np.asarray(v, float) / max(float(np.linalg.norm(v)), 1e-12)


def _endpoint_cap(source, endpoint, inward):
    """A real degree-one tip may end within its finite raster pen cap."""
    endpoint, outward = np.asarray(endpoint), -_unit(inward)
    radius = int(math.ceil(POLICY["maximum_endpoint_cap_extent_px"])) + 2
    x, y = np.rint(endpoint).astype(int)
    left, top = max(0, x - radius), max(0, y - radius)
    right, bottom = (
        min(source.shape[1], x + radius + 1),
        min(source.shape[0], y + radius + 1),
    )
    rows, cols = np.nonzero(
        source[top:bottom, left:right] < paths.POLICY["source_threshold"]
    )
    points = np.column_stack((cols + left, rows + top))
    normal = np.array([-outward[1], outward[0]])
    relative = points - endpoint
    aligned = abs(relative @ normal) <= 1.5
    extent = max(0.0, float(np.max(relative[aligned] @ outward, initial=0.0)))
    return {
        "source_endpoint_px": endpoint.tolist(),
        "outward_source_tangent": outward.tolist(),
        "source_cap_forward_extent_px": extent,
        "pass": extent <= POLICY["maximum_endpoint_cap_extent_px"],
    }


def _crossing_owner(graph, crossing, stroke_points, owners):
    nid = crossing["node_id"]
    node = graph.nodes[nid]
    incoming_id, outgoing_id = crossing["incoming_edge"], crossing["outgoing_edge"]
    selected = [p for p in node["edges"] if p[0] in (incoming_id, outgoing_id)]
    other = [p for p in node["edges"] if p not in selected]
    if (
        len(node["edges"]) != 4
        or len(node["pairing"]) != 4
        or len(selected) != 2
        or len(other) != 2
        or node["pairing"].get(selected[0]) != selected[1]
        or node["pairing"].get(other[0]) != other[1]
        or node["core_topology"]["cycle_rank"]
        or node["internal_source_endpoint_count"]
    ):
        return None, {
            "reason": "CROSSING_NOT_A_COMPLETE_UNIQUE_FOUR_PORT_DECOMPOSITION",
            "node_id": nid,
        }
    bounded_core = four_port_source_core_proof(graph, node)
    if bounded_core is None:
        return None, {
            "reason": "CROSSING_HAS_NO_BOUNDED_ORIGINAL_SHARED_CORE_PROOF",
            "node_id": nid,
        }
    source_ports, source_edges = [], set()
    for port in other:
        points = graph.xy(graph.oriented(port))
        spans = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
        k = min(
            len(points) - 1,
            int(np.searchsorted(spans, POLICY["other_port_source_span_px"])),
        )
        if spans[k] < POLICY["minimum_other_port_source_span_px"]:
            return None, {
                "reason": "CROSSING_OTHER_PORT_SOURCE_TOO_SHORT",
                "node_id": nid,
            }
        prefix = points[: k + 1]
        source_ports.append(
            {
                "port": list(port),
                "source_points_px": prefix.tolist(),
                "observed_span_px": float(spans[k]),
            }
        )
        source_edges.update(_edge_key(a, b) for a, b in zip(prefix, prefix[1:]))
    try:
        core = contact._core_route(
            graph, nid, graph.oriented(other[0])[0], graph.oriented(other[1])[0]
        )
    except ValueError:
        return None, {
            "reason": "CROSSING_OWNER_SOURCE_CORE_DISCONNECTED",
            "node_id": nid,
        }
    core_points = graph.xy(core)
    source_edges.update(_edge_key(a, b) for a, b in zip(core_points, core_points[1:]))
    a = np.asarray(source_ports[0]["source_points_px"])
    b = np.asarray(source_ports[1]["source_points_px"])
    owner_axis = _unit(b[-1] - a[-1])
    stroke_axis = _unit(stroke_points[-1] - stroke_points[0])
    separation = _angle(owner_axis, stroke_axis)
    separation = min(separation, 180.0 - separation)
    source_core = {tuple(p) for p in graph.xy(node["pixels"]).tolist()}

    def proved_owner_core(owner):
        for original in owner["contact_continuations"]:
            observed = original.get("source_core_pixels", [])
            other_ids = {p[0] for p in other}
            selected_ids = {p[0] for p in selected}
            if (
                set(map(tuple, observed)) == source_core
                and original.get("incoming_edge_id") in other_ids
                and {p[0] for p in original.get("selected_outgoing_ports", [])}
                <= other_ids
                and len(original.get("selected_outgoing_ports", [])) == 1
                and selected_ids <= set(original.get("unselected_branch_edge_ids", []))
                and original.get("source_branches_deleted") is False
            ):
                return True
        return False

    candidates = [
        owner
        for owner in owners
        if source_edges <= owner["source_adjacencies"]
        and owner["source_path_length_px"]
        >= POLICY["minimum_crossing_owner_length_ratio"] * paths._length(stroke_points)
        and proved_owner_core(owner)
    ]
    certificate = {
        "node_id": nid,
        "source_node_center_px": node["center"],
        "source_core_points_px": graph.xy(node["pixels"]).tolist(),
        "source_core_pixels": graph.xy(node["pixels"]).tolist(),
        "bounded_shared_source_core": bounded_core,
        "incoming_edge_id": incoming_id,
        "selected_outgoing_ports": [list(p) for p in selected if p[0] == outgoing_id],
        "unselected_branch_edge_ids": [p[0] for p in other],
        "original_crossing_evidence": deepcopy(node["crossing_evidence"]),
        "all_finite_pairing_competitors": deepcopy(node["finite_path_decompositions"]),
        "selected_stroke_ports": [list(p) for p in selected],
        "other_path_ports": source_ports,
        "other_path_core_source_px": core_points.tolist(),
        "matching_existing_path_ids": [owner["id"] for owner in candidates],
        "axis_separation_deg": separation,
        "source_branches_deleted": False,
        "line_and_other_path_may_share_core": True,
    }
    if (
        len(candidates) != 1
        or separation < POLICY["minimum_crossing_axis_separation_deg"]
    ):
        certificate["reason"] = "CROSSING_OWNER_NOT_UNIQUE_OR_TRANSVERSE"
        return None, certificate
    certificate.update(
        reason="EXACT_ORIGINAL_FOUR_PORT_PAIR_WITH_SEPARATE_NATIVE_OWNER",
        crossing_path_id=candidates[0]["id"],
        crossing_path_binding_sha256=_digest(candidates[0]["binding"]),
        complete_contact_owner_receipt=deepcopy(
            candidates[0]["source_contact_receipt_identity"]
        ),
        original_owner_contact_core_and_other_pair_reverified=True,
        original_other_path_adjacencies_all_retained=True,
    )
    return candidates[0], certificate


def _companions(a, b):
    if a["required_crossing_path_id"] != b["required_crossing_path_id"]:
        return None
    first, second = np.asarray(a["source_path_px"]), np.asarray(b["source_path_px"])
    u, v = _unit(first[-1] - first[0]), _unit(second[-1] - second[0])
    angle = _angle(u, v)
    angle = min(angle, 180.0 - angle)
    lengths = [float(np.linalg.norm(p[-1] - p[0])) for p in (first, second)]
    normal = np.array([-u[1], u[0]])
    separation = abs(float((second.mean(axis=0) - first.mean(axis=0)) @ normal))
    projected = [p @ u for p in (first, second)]
    overlap = max(
        0.0, min(p.max() for p in projected) - max(p.min() for p in projected)
    )
    overlap_fraction = overlap / min(lengths)
    passed = (
        angle <= POLICY["maximum_companion_axis_angle_deg"]
        and min(lengths) / max(lengths) >= POLICY["minimum_companion_length_ratio"]
        and POLICY["minimum_companion_normal_separation_px"]
        <= separation
        <= POLICY["maximum_companion_separation_length_ratio"] * min(lengths)
        and overlap_fraction >= POLICY["minimum_companion_projected_overlap_fraction"]
    )
    return (
        {
            "other_source_path_sha256": _digest(b["source_path_px"]),
            "other_complete_source_endpoints_px": [
                second[0].tolist(),
                second[-1].tolist(),
            ],
            "axis_angle_deg": angle,
            "normal_separation_px": separation,
            "projected_overlap_fraction": overlap_fraction,
        }
        if passed
        else None
    )


def plan_transverse_stroke_geometry(gray, roi, prior_objects, *, source_graph=None):
    """Plan full independent LINEs; never retire or modify an existing object."""
    source = np.asarray(gray)
    context = source_graph or contact.build_text_contact_source_graph(source, roi)
    graph = context.graph
    left, top, right, bottom = context.crop_bbox
    if (
        list(map(int, roi)) != list(graph.roi)
        or hashlib.sha256(source[top:bottom, left:right].tobytes()).hexdigest()
        != context.source_crop_hash
    ):
        raise ValueError("TRANSVERSE_STROKE_REUSED_GRAPH_SOURCE_CHANGED")
    bindings = [
        _binding(obj) for obj in sorted(prior_objects, key=lambda row: row["id"])
    ]
    result = {
        "schema": SCHEMA,
        "policy": dict(POLICY),
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "roi_xyxy_px": list(map(int, roi)),
        "seed_bbox_xyxy_px": list(map(int, roi)),
        "contact_context_bbox_xyxy_px": list(map(int, roi)),
        "original_source_crop_xyxy_px": context.crop_bbox,
        "original_source_crop_array_sha256": context.source_crop_hash,
        "prior_object_bindings": bindings,
        "prior_object_bindings_sha256": _digest(bindings),
        "unchanged_connection_source_policy": dict(paths.POLICY),
        "paths": [],
        "pending": [],
        "original_source_pixels_modified": False,
        "transcription_supplied": False,
    }
    owners, result["owner_witness_refusals"] = _owners(source, context, bindings)
    texts = paths._text_boxes(bindings)
    rows, seen = [], set()
    for nid, node in sorted(graph.nodes.items()):
        if (node.get("terminal") or {}).get("kind") != "OBSERVED_FREE_SOURCE_ENDPOINT":
            continue
        for first in node["edges"]:
            raw, edge_ids, crossings, end_id, reason = graph.trace(nid, first)
            key = tuple(sorted(edge_ids))
            if key in seen or not raw:
                continue
            seen.add(key)
            points = graph.xy(raw)
            length = paths._length(points)
            if (
                not POLICY["minimum_path_length_px"]
                <= length
                <= POLICY["maximum_path_length_px"]
                or not crossings
            ):
                continue
            diagnostic = {
                "source_graph_edge_ids": edge_ids,
                "source_path_px": points.tolist(),
                "endpoint_source_points_px": [points[0].tolist(), points[-1].tolist()],
            }
            if (
                reason
                or (graph.nodes[end_id].get("terminal") or {}).get("kind")
                != "OBSERVED_FREE_SOURCE_ENDPOINT"
            ):
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": reason or "SECOND_END_NOT_A_FREE_SOURCE_ENDPOINT",
                    }
                )
                continue
            # The end has one actual source port; derive its orientation from
            # that port, not by changing the start to suppress competitors.
            end_port = graph.nodes[end_id]["edges"][0]
            reverse, reverse_edges, _, reverse_end, reverse_reason = graph.trace(
                end_id, end_port
            )
            if (
                reverse_reason
                or reverse_end != nid
                or raw != reverse[::-1]
                or edge_ids != reverse_edges[::-1]
            ):
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": "COMPLETE_REVERSE_STROKE_TRACE_DOES_NOT_AGREE",
                    }
                )
                continue
            chord = float(np.linalg.norm(points[-1] - points[0]))
            axis = _unit(points[-1] - points[0])
            along = (points - points[0]) @ axis
            normal = np.array([-axis[1], axis[0]])
            maximum_deviation = float(np.max(abs((points - points[0]) @ normal)))
            if (
                chord <= 0
                or maximum_deviation > POLICY["maximum_straight_source_deviation_px"]
                or np.min(np.diff(along)) < -1e-9
            ):
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": "SOURCE_STROKE_NOT_MONOTONE_AND_NEAR_STRAIGHT",
                    }
                )
                continue
            text_hits = [
                identity
                for identity, box in texts
                if contact._inside(points, box).sum() >= 3
            ]
            if text_hits:
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": "EXISTING_NATIVE_TEXT_HAS_SOURCE_RESPONSIBILITY",
                        "text_ids": text_hits,
                    }
                )
                continue
            owners_for_row, proofs, failed = [], [], False
            for crossing in crossings:
                owner, proof = _crossing_owner(graph, crossing, points, owners)
                proofs.append(proof)
                if owner is None:
                    failed = True
                    break
                center = np.asarray(graph.nodes[crossing["node_id"]]["center"])
                spans = [
                    abs(float((center - endpoint) @ axis))
                    for endpoint in (points[0], points[-1])
                ]
                if min(spans) < POLICY["minimum_free_arm_length_px"]:
                    proof["reason"] = "FREE_STROKE_ARM_TOO_SHORT_TO_SEPARATE_FROM_CORE"
                    failed = True
                    break
                owners_for_row.append(owner)
            if failed or len({owner["id"] for owner in owners_for_row}) != 1:
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": "STROKE_CROSSING_RESPONSIBILITY_NOT_PROVED",
                        "contact_continuations": proofs,
                    }
                )
                continue
            caps = [
                _endpoint_cap(source, points[0], points[1] - points[0]),
                _endpoint_cap(source, points[-1], points[-2] - points[-1]),
            ]
            cells = np.asarray(_segment_cells(points[0], points[-1]), int)
            all_ink = bool(
                np.all(
                    source[cells[:, 1], cells[:, 0]] < paths.POLICY["source_threshold"]
                )
            )
            if not all_ink or not all(row["pass"] for row in caps):
                result["pending"].append(
                    {
                        **diagnostic,
                        "reason": "NATIVE_STROKE_LINE_OR_ENDPOINT_CAP_NOT_SOURCE_SUPPORTED",
                        "all_native_closed_cells_ink": all_ink,
                        "endpoint_cap_checks": caps,
                    }
                )
                continue
            geometry = {
                "points": [points[0].tolist(), points[-1].tolist()],
                "bulges": [0.0, 0.0],
                "closed": False,
            }
            owner = owners_for_row[0]
            rows.append(
                {
                    "path_role": "TRANSVERSE_STROKE",
                    **diagnostic,
                    "source_path_length_px": length,
                    "representation": geometry,
                    "representation_evidence": {
                        "representation": "ONE_NATIVE_COMPLETE_STRAIGHT_LINE",
                        "maximum_raw_centerline_deviation_px": maximum_deviation,
                        "closed_pixel_cells": cells.tolist(),
                        "closed_pixel_cells_all_original_ink": True,
                        "native_endpoints_are_original_free_source_endpoints": True,
                    },
                    "source_support": {
                        "pass": True,
                        "source_fraction": 1.0,
                        "maximum_white_gap_px": 0.0,
                    },
                    "native_endpoint_points_px": deepcopy(geometry["points"]),
                    "endpoint_evidence": [
                        deepcopy(node["terminal"]),
                        deepcopy(graph.nodes[end_id]["terminal"]),
                    ],
                    "endpoint_source_cores": [None, None],
                    "endpoint_cap_checks": caps,
                    "reverse_source_path_agreement": {
                        "pass": True,
                        "all_source_edges_reversed": True,
                        "all_source_pixels_reversed": True,
                    },
                    "contact_continuations": proofs,
                    "bounded_original_cycle_covers": [],
                    "required_crossing_path_id": owner["id"],
                    "required_crossing_path_binding": deepcopy(owner["binding"]),
                    "required_crossing_path_binding_sha256": _digest(owner["binding"]),
                    "line_runs": [],
                    "shared_contact_runs": [],
                    "original_branches_retained": True,
                    "line_and_text_may_share_source_pixels": True,
                    "text_content_decision": "NOT_PERFORMED",
                    "existing_objects_may_be_retired": False,
                }
            )
    for row in rows:
        companions = [
            proof
            for other in rows
            if other is not row
            for proof in [_companions(row, other)]
            if proof is not None
        ]
        if len(companions) < POLICY["minimum_parallel_companions"]:
            result["pending"].append(
                {
                    "source_graph_edge_ids": row["source_graph_edge_ids"],
                    "source_path_px": row["source_path_px"],
                    "reason": "NO_INDEPENDENT_PARALLEL_COMPLETE_STROKE_COMPANION",
                }
            )
            continue
        row["parallel_stroke_group_evidence"] = {
            "complete_companions": companions,
            "graphic_repetition_is_support_not_character_transcription": True,
            "all_members_require_independent_free_endpoints_and_crossing_proofs": True,
        }
        row["stroke_id"] = stable_id("TRANSVERSE", row["source_path_px"])
        result["paths"].append(row)
    return result


def verify_transverse_stroke_geometry_plan(gray, roi, plan, *, source_graph=None):
    """Replay endpoints, competitors, original shared source and native owner."""
    bindings = plan.get("prior_object_bindings", [])
    if plan.get("schema") != SCHEMA or plan.get(
        "prior_object_bindings_sha256"
    ) != _digest(bindings):
        return {"pass": False, "checks": {"prior_bindings_integrity": False}}
    try:
        replay = plan_transverse_stroke_geometry(
            gray, roi, bindings, source_graph=source_graph
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "pass": False,
            "reason": "TRANSVERSE_STROKE_SOURCE_REPLAY_ERROR",
            "detail": str(exc),
        }
    checks = {key + "_replayed": plan.get(key) == replay.get(key) for key in replay}
    passed = all(checks.values())
    return {
        "pass": passed,
        "checks": checks,
        "reason": "EXACT_TRANSVERSE_STROKE_SOURCE_REPLAY"
        if passed
        else "TRANSVERSE_STROKE_SOURCE_REPLAY_MISMATCH",
        "path_count": len(replay["paths"]),
        "replayed_paths": replay["paths"],
        "source_pixels_modified": False,
    }
