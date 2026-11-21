"""Source-bound graphic evidence for unresolved text-localization candidates.

Candidate ink is an observation, not an exclusive glyph partition.  Nothing
here edits a raster, changes a transcription, joins a gap, or adopts geometry.
The caller supplies observations freshly verified from captured raw artifacts;
legacy payloads without that evidence retain their conservative text veto.
"""

from __future__ import annotations

import hashlib
import json
import math

import cv2
import numpy as np


POLICY = {
    "version": "bound-text-candidate-graphic-support-v1",
    "minimum_verified_contexts": 2,
    "source_threshold": 128,
    "minimum_word_confidence": 85.0,
    "minimum_numeric_confidence": 95.0,
    "text_component_height_ratio": [0.45, 1.7],
    "text_row_baseline_height_ratio": 0.35,
    "text_row_neighbor_gap_height_ratio": 1.25,
    "local_reference_distance_glyph_heights": 8.0,
    "tangent_span_px": 12.0,
    "maximum_continuation_angle_deg": 20.0,
    "maximum_gap_glyph_heights": 2.0,
    "minimum_original_white_gap_px": 2.0,
    "maximum_aggregate_core_extent_px": 12.0,
    "maximum_aggregate_core_stroke_widths": 3.0,
    "common_crossing_axis_residual_px": 0.85,
    "crossing_pair_max_deviation_deg": 20.0,
    "crossing_pair_cost_margin_deg": 30.0,
    "crossing_axis_separation_min_deg": 30.0,
    "minimum_graphic_crossings": 2,
    "minimum_whole_crossing_member_length_px": 12.0,
    "maximum_component_routes": 16,
    "source_pixels_modified": False,
    "pixel_roles_must_be_exclusive": False,
    "geometry_adoption_authorized": False,
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _array_sha(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _word_rows(words):
    return [
        {"text": str(w.get("text", "")), "confidence": float(w.get("confidence", -1)),
         "bbox_xyxy_px": list(w.get("bbox_xyxy_px", []))}
        for w in words
    ]


def _inside(box, point):
    return box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]


def _intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _box_distance(a, b):
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0), max(a[1] - b[3], b[1] - a[3], 0))


def _text_references(objects):
    result = []
    for obj in objects:
        kind, geometry = obj["kind"], obj["geometry"]
        if kind == "ROOM_LABEL":
            geometry, kind = geometry["text_geometry"], "TEXT"
        if kind == "TEXT":
            box = [geometry["x"], geometry["y"] - geometry["height_px"],
                   geometry["x"] + geometry["width_px"], geometry["y"]]
        elif kind == "MTEXT":
            box = geometry["bbox_xyxy_px"]
        else:
            continue
        result.append({"object_id": obj["id"], "bbox_xyxy_px": list(box),
                       "glyph_height_px": float(geometry["height_px"])})
    return result


def _verified_rows(gray, data, verified):
    """Bind a runtime verifier result to the actual current pixels and words.

    ``validated`` is only consumed from the caller's raw-file verifier result,
    never from a text-region JSON or a checkpoint's claimed permission flag.
    Historical and imported observation keys may differ, so raw specification,
    crop bytes and unchanged parsed words establish the association instead.
    """
    if not isinstance(verified, dict) or verified.get("validated") is not True:
        return {}, "RAW_OBSERVATIONS_NOT_CAPTURED_AND_VERIFIED"
    actual = _array_sha(gray)
    if actual != data.get("source_array_sha256") or actual != verified.get("source_array_sha256"):
        return {}, "CURRENT_TEXT_SUPPORT_SOURCE_ARRAY_MISMATCH"
    regions = {row["id"]: row for row in data["regions"]}
    result = {}
    for observed in verified.get("observations", []):
        region = regions.get(observed.get("region_id"))
        spec = observed.get("specification", {})
        crop = spec.get("crop_xyxy_px", [])
        if region is None or len(crop) != 4 or not all(isinstance(v, int) for v in crop):
            continue
        x0, y0, x1, y1 = crop
        if not (0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0]):
            continue
        if _array_sha(gray[y0:y1, x0:x1]) != spec.get("crop_array_sha256"):
            continue
        if not all(isinstance(observed.get(key), str) and len(observed[key]) == 64
                   for key in ("raw_tsv_sha256", "metadata_sha256", "input_png_sha256")):
            continue
        matches = [
            alt for alt in region.get("completeness_evidence", {}).get("alternatives", [])
            if alt.get("crop_xyxy_px") == crop
            and alt.get("psm") == spec.get("psm")
            and _word_rows(alt.get("all_words", alt.get("words", [])))
            == _word_rows(observed.get("words", []))
        ]
        if not matches:
            continue
        result.setdefault(region["id"], {})[_digest(spec)] = {
            "key": observed.get("key"), "specification": spec,
            "raw_tsv_sha256": observed["raw_tsv_sha256"],
            "metadata_sha256": observed["metadata_sha256"],
            "input_png_sha256": observed["input_png_sha256"],
            "words": _word_rows(observed.get("words", [])),
            "historical_model_byte_identity_proven": False,
        }
    return {rid: list(rows.values()) for rid, rows in result.items()}, None


def _length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _direction(points):
    points = np.asarray(points, float)
    if len(points) < 2:
        return None
    # A certified endpoint lobe may return to its start. Retain the lobe in the
    # path; use the subsequent witnessed stroke only for its external tangent.
    repeats = np.flatnonzero(np.all(points == points[0], axis=1))
    if len(repeats) > 1:
        points = points[int(repeats[-1]):]
    if len(points) < 2:
        return None
    distances = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    index = int(np.searchsorted(distances, POLICY["tangent_span_px"]))
    if index >= len(points):
        return None
    vector = points[index] - points[0]
    norm = float(np.linalg.norm(vector))
    if norm < POLICY["tangent_span_px"] / 2:
        return None
    return vector / norm, points[:index + 1]


def _angle(a, b):
    return math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))


def verified_candidate_core_boxes(gray, data, verified):
    """Only current raw-bound candidates can enable the additional graph rule."""
    if not data:
        return []
    rows, error = _verified_rows(gray, data, verified)
    if error:
        return []
    return [row["bbox_xyxy_px"] for row in data["regions"]
            if len(rows.get(row["id"], [])) >= POLICY["minimum_verified_contexts"]
            and not row.get("complete") and not row.get("accepted")]


def _port_axis(graph, port):
    points = graph.xy(graph.oriented(port))
    span = np.r_[0.0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    index = int(np.searchsorted(span, min(POLICY["tangent_span_px"], span[-1])))
    if span[index] < POLICY["tangent_span_px"] / 2:
        return None
    samples = points[:index + 1]
    center = samples.mean(axis=0)
    _, _, axes = np.linalg.svd(samples - center)
    direction = axes[0]
    if direction @ (samples[-1] - samples[0]) < 0:
        direction = -direction
    return center, direction, samples


def aggregate_close_crossing_cores(graph, permitted_boxes):
    """Contract a raster-split crossing, retaining its entire original core.

    Two real, separated T junctions do not become a crossing merely because
    they are close: all four witnessed external axes must share one original
    ink intersection within the unchanged 0.85 px geometric tolerance.
    No skeleton pixel or source edge is erased; the tiny internal bridge is
    recorded as core support and can be shared by independent crossing paths.
    """
    if graph.source_ink is None or not permitted_boxes:
        return []
    widths = 2 * cv2.distanceTransform(graph.source_ink.astype(np.uint8), cv2.DIST_L2,
                                       cv2.DIST_MASK_PRECISE)
    graph.source_stroke_widths = widths
    eligible = []
    for internal in graph.edges:
        a, b = internal["nodes"]
        if a == b or len(graph.nodes[a]["edges"]) != 3 or len(graph.nodes[b]["edges"]) != 3:
            continue
        if sum(set(edge["nodes"]) == {a, b} for edge in graph.edges) != 1:
            continue
        pixels = sorted(set(graph.nodes[a]["pixels"] + graph.nodes[b]["pixels"] + internal["pixels"]))
        points = graph.xy(pixels)
        if not any(all(_inside(box, point) for point in points) for box in permitted_boxes):
            continue
        ports = [port for nid in (a, b) for port in graph.nodes[nid]["edges"]
                 if port[0] != internal["id"]]
        if len(ports) != 4 or len({port[0] for port in ports}) != 4:
            continue
        axes = [_port_axis(graph, port) for port in ports]
        if any(axis is None for axis in axes):
            continue
        port_widths = []
        for port in ports:
            chain = graph.oriented(port)[1:13]
            port_widths.extend(float(widths.ravel()[p]) for p in chain)
        width = float(np.median(port_widths))
        extent = float(np.ptp(points, axis=0).max())
        if extent > min(POLICY["maximum_aggregate_core_extent_px"],
                        POLICY["maximum_aggregate_core_stroke_widths"] * width):
            continue
        pixel_set = set(pixels)
        adjacency = sorted({tuple(sorted((p, q))) for p in pixels for q in graph.neighbors(p)
                            if q in pixel_set})
        # One connected tree only; preserve every cycle and true short endpoint.
        if len(adjacency) != len(pixels) - 1 or any(graph.degree.ravel()[p] <= 1 for p in pixels):
            continue
        directions = [axis[1] for axis in axes]
        scored = []
        for pairs in (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))):
            deviations = [_angle(-directions[i], directions[j]) for i, j in pairs]
            scored.append((sum(deviations), max(deviations), pairs, deviations))
        scored.sort(key=lambda row: row[:2])
        best = scored[0]
        separation = math.degrees(math.acos(float(np.clip(abs(
            directions[best[2][0][0]] @ directions[best[2][1][0]]), -1, 1))))
        if (best[1] > POLICY["crossing_pair_max_deviation_deg"]
                or scored[1][0] - best[0] < POLICY["crossing_pair_cost_margin_deg"]
                or separation < POLICY["crossing_axis_separation_min_deg"]):
            continue
        normals = np.array([[-axis[1][1], axis[1][0]] for axis in axes])
        offsets = np.array([normal @ axis[0] for normal, axis in zip(normals, axes)])
        common, *_ = np.linalg.lstsq(normals, offsets, rcond=None)
        residuals = np.abs(normals @ common - offsets)
        if float(residuals.max()) > POLICY["common_crossing_axis_residual_px"]:
            continue
        local = np.rint(common - graph.origin).astype(int)
        if (not (0 <= local[0] < graph.w and 0 <= local[1] < graph.h)
                or not graph.source_ink[local[1], local[0]]
                or np.any(common < points.min(axis=0) - 0.85)
                or np.any(common > points.max(axis=0) + 0.85)):
            continue
        proof = {
            "kind": "BOUNDED_ORIGINAL_INK_FOUR_PORT_CORE",
            "original_node_ids": [a, b], "original_internal_edge_id": internal["id"],
            "original_internal_edge_points": graph.xy(internal["pixels"]).tolist(),
            "source_core_points": points.tolist(),
            "source_core_adjacencies": [graph.xy(pair).tolist() for pair in adjacency],
            "source_core_extent_px": extent, "measured_stroke_width_px": width,
            "external_port_source_tangents": [axis[2].tolist() for axis in axes],
            "selected_pairs": [list(pair) for pair in best[2]],
            "pair_deviations_deg": best[3], "axis_separation_deg": separation,
            "common_source_intersection_px": common.tolist(),
            "common_axis_residuals_px": residuals.tolist(),
            "source_crop_xyxy_px": [int(graph.origin[0]), int(graph.origin[1]),
                                    int(graph.origin[0]) + graph.w, int(graph.origin[1]) + graph.h],
            "graph_roi_xyxy_px": list(graph.roi),
            "source_binary_crop_sha256": _array_sha(graph.source_ink.astype(np.uint8)),
            "all_four_ports_retained": True, "internal_source_bridge_retained": True,
            "white_holes_filled": False, "source_short_branches_deleted": False,
        }
        proof["core_geometry_sha256"] = _digest(points.tolist())
        eligible.append((a, b, internal["id"], pixels, proof))
    counts = {}
    for a, b, *_ in eligible:
        counts[a], counts[b] = counts.get(a, 0) + 1, counts.get(b, 0) + 1
    accepted = [row for row in eligible if counts[row[0]] == counts[row[1]] == 1]
    aliases, internal_ids, proofs = {}, set(), []
    for a, b, eid, pixels, proof in accepted:
        aliases[b] = a
        internal_ids.add(eid)
        graph.nodes[a]["pixels"] = pixels
        graph.nodes[a]["bounded_aggregate_source_core"] = proof
        graph.node_map[pixels] = a
        del graph.nodes[b]
        proofs.append(proof)
    if accepted:
        graph.edges = [edge for edge in graph.edges if edge["id"] not in internal_ids]
        for node in graph.nodes.values():
            node["edges"] = []
        for eid, edge in enumerate(graph.edges):
            edge["id"] = eid
            edge["nodes"] = [aliases.get(nid, nid) for nid in edge["nodes"]]
            for end, nid in enumerate(edge["nodes"]):
                graph.nodes[nid]["edges"].append((eid, end))
    return proofs


def four_port_source_core_proof(graph, node):
    """Give an ordinary or aggregated four-port core the same bounded proof."""
    if node.get("bounded_aggregate_source_core"):
        return node["bounded_aggregate_source_core"]
    if graph.source_ink is None or len(node.get("pairing", {})) != 4:
        return None
    pixels, ports = node["pixels"], node["edges"]
    points = graph.xy(pixels)
    pixel_set = set(pixels)
    adjacency = sorted({tuple(sorted((p, q))) for p in pixels for q in graph.neighbors(p)
                        if q in pixel_set})
    if len(adjacency) != len(pixels) - 1:
        return None
    axes = [_port_axis(graph, port) for port in ports]
    if any(axis is None for axis in axes):
        return None
    widths = getattr(graph, "source_stroke_widths", None)
    if widths is None:
        widths = 2 * cv2.distanceTransform(graph.source_ink.astype(np.uint8), cv2.DIST_L2,
                                           cv2.DIST_MASK_PRECISE)
        graph.source_stroke_widths = widths
    width = float(np.median([float(widths.ravel()[p]) for port in ports
                             for p in graph.oriented(port)[1:13]]))
    extent = float(np.ptp(points, axis=0).max())
    if extent > min(POLICY["maximum_aggregate_core_extent_px"],
                    POLICY["maximum_aggregate_core_stroke_widths"] * width):
        return None
    normals = np.array([[-axis[1][1], axis[1][0]] for axis in axes])
    offsets = np.array([normal @ axis[0] for normal, axis in zip(normals, axes)])
    common, *_ = np.linalg.lstsq(normals, offsets, rcond=None)
    residuals = np.abs(normals @ common - offsets)
    local = np.rint(common - graph.origin).astype(int)
    if (float(residuals.max()) > POLICY["common_crossing_axis_residual_px"]
            or not (0 <= local[0] < graph.w and 0 <= local[1] < graph.h)
            or not graph.source_ink[local[1], local[0]]):
        return None
    return {
        "kind": "BOUNDED_ORIGINAL_INK_FOUR_PORT_CORE",
        "original_node_ids": [node["id"]], "source_core_points": points.tolist(),
        "source_core_adjacencies": [graph.xy(pair).tolist() for pair in adjacency],
        "source_core_extent_px": extent, "measured_stroke_width_px": width,
        "external_port_source_tangents": [axis[2].tolist() for axis in axes],
        "common_source_intersection_px": common.tolist(),
        "common_axis_residuals_px": residuals.tolist(),
        "source_crop_xyxy_px": [int(graph.origin[0]), int(graph.origin[1]),
                                int(graph.origin[0]) + graph.w, int(graph.origin[1]) + graph.h],
        "graph_roi_xyxy_px": list(graph.roi),
        "source_binary_crop_sha256": _array_sha(graph.source_ink.astype(np.uint8)),
        "all_four_ports_retained": True, "internal_source_bridge_retained": True,
        "white_holes_filled": False, "source_short_branches_deleted": False,
        "core_geometry_sha256": _digest(points.tolist()),
    }


def _component_routes(graph, labels):
    """Only already-proved four-port decompositions qualify as a whole group."""
    edges_by_label = {}
    for edge in graph.edges:
        label = int(labels.ravel()[edge["pixels"][0]])
        edges_by_label.setdefault(label, set()).add(edge["id"])
    route_groups = {}
    for label, expected_edges in edges_by_label.items():
        nodes = [node for node in graph.nodes.values()
                 if int(labels.ravel()[node["pixels"][0]]) == label]
        crossings = [node for node in nodes
                     if node.get("crossing_evidence", {}).get("port_count") == 4
                     and len(node.get("pairing", {})) == 4]
        if len(crossings) < POLICY["minimum_graphic_crossings"]:
            continue
        routes, failures = {}, []
        for node in nodes:
            if not node.get("terminal"):
                if not node.get("pairing"):
                    failures.append("UNRESOLVED_SOURCE_PORTS")
                continue
            if node["terminal"]["kind"] != "OBSERVED_FREE_SOURCE_ENDPOINT":
                failures.append("GROUP_HAS_NONFREE_OR_UNRESOLVED_ENDPOINT")
                continue
            for port in node["edges"]:
                pixels, edge_ids, evidence, end, reason = graph.trace(node["id"], port)
                if reason or not pixels or graph.nodes[end].get("terminal", {}).get("kind") != "OBSERVED_FREE_SOURCE_ENDPOINT":
                    failures.append(reason or "GROUP_ROUTE_NOT_TWO_COMPLETE_FREE_ENDS")
                    continue
                key = tuple(sorted(edge_ids))
                points = graph.xy(pixels)
                if _length(points) < POLICY["minimum_whole_crossing_member_length_px"]:
                    failures.append("COMPLETE_CROSSING_MEMBER_BELOW_SOURCE_LENGTH_GATE")
                routes.setdefault(key, {"source_graph_edge_ids": list(key),
                                        "source_path_points": points.tolist(),
                                        "endpoint_node_ids": [node["id"], end],
                                        "crossing_node_ids": [row["node_id"] for row in evidence]})
        owned = [eid for key in routes for eid in key]
        if (failures or not routes or len(routes) > POLICY["maximum_component_routes"]
                or set(owned) != expected_edges or len(owned) != len(set(owned))):
            continue
        certificate = {
            "kind": "COMPLETE_SOURCE_GRAPH_WITH_MULTIPLE_PROVEN_FOUR_PORT_CROSSINGS",
            "source_component_label": label,
            "crossing_nodes": [{"node_id": node["id"], "all_ports": [list(p) for p in node["edges"]],
                                "pairing_evidence": node["crossing_evidence"]} for node in crossings],
            "complete_routes": list(routes.values()),
            "every_source_graph_edge_has_one_complete_route": True,
            "junction_source_pixels_may_support_several_paths": True,
            "source_short_branches_removed": False,
        }
        certificate["certificate_sha256"] = _digest(certificate)
        route_groups.update({key: certificate for key in routes})
    return route_groups


def prepare_text_support(gray, roi, text_regions, prior_objects, graph, *, verified_observations=None):
    """Prepare source evidence, not a mask or an adoption whitelist."""
    rows, error = _verified_rows(gray, text_regions, verified_observations) if text_regions else ({}, "NO_TEXT_OBSERVATIONS")
    _, labels, stats, _ = cv2.connectedComponentsWithStats(graph.source_ink.astype(np.uint8), connectivity=8)
    groups = {}
    for group in (text_regions or {}).get("groups", []):
        for region_id in group.get("region_ids", []):
            groups.setdefault(region_id, []).append(group)
    return {
        "gray": gray, "roi": list(roi), "graph": graph, "labels": labels, "stats": stats,
        "regions": {row["id"]: row for row in (text_regions or {}).get("regions", [])},
        "groups": groups, "verified_rows": rows, "binding_error": error,
        "references": _text_references(prior_objects),
        "complete_crossing_routes": _component_routes(graph, labels) if rows else {},
        "source_array_sha256": (text_regions or {}).get("source_array_sha256"),
        "verified_observations_digest": _digest(verified_observations) if verified_observations else None,
    }


def complete_crossing_group(context, edge_ids):
    return context["complete_crossing_routes"].get(tuple(sorted(edge_ids)))


def _source_adjacencies(obj):
    points = obj.get("source_evidence", {}).get("source_path_points", [])
    return {tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(points, points[1:]) if a != b}


def prove_shared_core_overlap(gray, candidate, other):
    """Rebuild source cores before permitting two independent source owners.

    This is deliberately not permission obtained from a saved ``pass`` flag.
    Both actual source paths must use different pairs of the current four-port
    graph, and every shared adjacency must lie inside its small original core.
    The caller still applies native duplicate, support and saved-file gates.
    """
    import time

    from scipy.spatial import cKDTree

    from .connections import _dense_geometry, _SourceGraph, _thinning

    result = {"schema": "current-source-shared-crossing-core-v1", "pass": False,
              "candidate_id": candidate.get("id"), "other_id": other.get("id"),
              "source_pixels_modified": False, "native_duplicates_authorized": False}
    source_edges = [_source_adjacencies(obj) for obj in (candidate, other)]
    shared = source_edges[0] & source_edges[1]
    result["shared_source_adjacency_count"] = len(shared)
    if not shared:
        result["reason"] = "NO_SHARED_SOURCE_ADJACENCIES"
        return result
    maps = []
    for obj in (candidate, other):
        rows = obj.get("source_evidence", {}).get("crossing_evidence", [])
        maps.append({row["bounded_shared_source_core"].get("core_geometry_sha256"):
                     row["bounded_shared_source_core"] for row in rows
                     if row.get("bounded_shared_source_core")})
    common = set(maps[0]) & set(maps[1])
    covered, proofs, reconstructed = set(), [], {}
    for key in sorted(common):
        recorded = maps[0][key]
        crop = recorded.get("source_crop_xyxy_px", [])
        roi = recorded.get("graph_roi_xyxy_px", [])
        if len(crop) != 4 or len(roi) != 4 or not all(isinstance(v, int) for v in crop + roi):
            continue
        x0, y0, x1, y1 = crop
        if (not (0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0])
                or (x1 - x0) * (y1 - y0) > 2_000_000):
            continue
        source_ink = gray[y0:y1, x0:x1] < POLICY["source_threshold"]
        if _array_sha(source_ink.astype(np.uint8)) != recorded.get("source_binary_crop_sha256"):
            continue
        scope = tuple(crop + roi)
        if scope not in reconstructed:
            started = time.process_time()
            skeleton, _ = _thinning(source_ink, started)
            reconstructed[scope] = _SourceGraph(skeleton, [x0, y0], [], roi, started,
                source_ink=source_ink, aggregate_core_boxes=[crop])
        graph = reconstructed[scope]
        nodes = [node for node in graph.nodes.values()
                 if node.get("bounded_shared_source_core", {}).get("core_geometry_sha256") == key
                 and len(node.get("pairing", {})) == 4]
        if len(nodes) != 1:
            continue
        node = nodes[0]
        fresh = node["bounded_shared_source_core"]
        if any(_digest(record.get("source_core_points")) != key for record in (maps[0][key], maps[1][key])):
            continue
        path_ports = []
        for edges in source_edges:
            ports = [port for port in node["edges"] if tuple(sorted(
                map(tuple, graph.xy(graph.oriented(port)[:2]).tolist()))) in edges]
            if len(ports) != 2 or node["pairing"].get(ports[0]) != ports[1]:
                break
            path_ports.append(ports)
        if len(path_ports) != 2 or set(path_ports[0]) & set(path_ports[1]):
            continue
        core_edges = {tuple(sorted(map(tuple, pair))) for pair in fresh["source_core_adjacencies"]}
        covered |= shared & core_edges
        proofs.append({"core_geometry_sha256": key, "source_core_points": fresh["source_core_points"],
                       "source_core_extent_px": fresh["source_core_extent_px"],
                       "measured_stroke_width_px": fresh["measured_stroke_width_px"],
                       "current_source_binary_crop_sha256": fresh["source_binary_crop_sha256"],
                       "independent_four_port_pairings": [[list(port) for port in row] for row in path_ports],
                       "source_recomputed": True})
    if covered != shared:
        result["reason"] = "SHARED_SOURCE_ADJACENCY_OUTSIDE_CURRENT_PROVEN_CORE"
        result["unproven_shared_adjacencies"] = [[list(p) for p in edge] for edge in sorted(shared - covered)]
        return result
    try:
        native = [_dense_geometry(obj["geometry"]) for obj in (candidate, other)]
    except (KeyError, ValueError, TypeError):
        result["reason"] = "NATIVE_GEOMETRY_NOT_A_SUPPORTED_PATH"
        return result
    overlaps = []
    for points, other_points in (native, native[::-1]):
        # Project onto finite spans, rather than comparing sampled points:
        # identical lines sampled with different phases are still duplicates.
        _, nearest = cKDTree(other_points).query(points, k=min(2, len(other_points)))
        nearest = np.asarray(nearest).reshape(len(points), -1)
        span_indices = np.clip(np.concatenate((nearest - 1, nearest), axis=1),
                               0, len(other_points) - 2)
        starts, ends = other_points[span_indices], other_points[span_indices + 1]
        vectors = ends - starts
        denominator = np.maximum(np.sum(vectors * vectors, axis=2), 1e-12)
        fractions = np.clip(np.sum((points[:, None] - starts) * vectors, axis=2) / denominator, 0, 1)
        distances = np.linalg.norm(points[:, None] - (starts + fractions[..., None] * vectors), axis=2)
        near = distances.min(axis=1) < 0.05
        overlap = points[near]
        if len(overlap):
            contained = np.zeros(len(overlap), bool)
            for proof in proofs:
                core = np.asarray(proof["source_core_points"], float)
                contained |= np.all((overlap >= core.min(axis=0) - 0.85)
                                    & (overlap <= core.max(axis=0) + 0.85), axis=1)
            if not np.all(contained):
                result["reason"] = "NATIVE_OVERLAP_EXTENDS_OUTSIDE_PROVEN_SOURCE_CORE"
                return result
        overlaps.append(int(near.sum()))
    result.update({"pass": True, "reason": "CURRENT_FOUR_PORT_CORE_HAS_DISTINCT_COMPLETE_PATH_OWNERS",
                   "current_core_proofs": proofs, "native_overlap_sample_counts": overlaps,
                   "shared_source_adjacencies": [[list(p) for p in edge] for edge in sorted(shared)]})
    return result


def _candidate_protection(context, region, component_box, source_label, *, stronger_graphic_evidence=None):
    blocks, evidence = [], {}
    rows = context["verified_rows"].get(region["id"], [])
    if len(rows) < POLICY["minimum_verified_contexts"]:
        blocks.append("INSUFFICIENT_ACTUALLY_VERIFIED_SOURCE_CONTEXTS")
    if region.get("accepted") or region.get("complete") or region.get("source_review", {}).get("accepted"):
        blocks.append("ACCEPTED_OR_COMPLETE_SOURCE_TEXT_REGION")
    if any(group.get("complete") or group.get("source_review", {}).get("accepted")
           for group in context["groups"].get(region["id"], [])):
        blocks.append("COMPLETE_OR_REVIEWED_SOURCE_TEXT_GROUP")
    local_word_sets = []
    has_single_interpretation = False
    for row in rows:
        words = [word for word in row["words"] if _intersects(word["bbox_xyxy_px"], component_box)]
        local_word_sets.append(tuple(word["text"] for word in words))
        for word in words:
            threshold = POLICY["minimum_numeric_confidence"] if word["text"].isdigit() else POLICY["minimum_word_confidence"]
            if word["confidence"] >= threshold:
                blocks.append("RELIABLE_VERIFIED_WORD_SUPPORT_RETAINED")
            if sum(c.isalnum() for c in word["text"]) <= 1:
                has_single_interpretation = True
    conflicting_shape_claims = (len(set(local_word_sets)) >= 2
                               and any(sum(c.isalnum() for c in text) > 1
                                       for words in local_word_sets for text in words))
    if has_single_interpretation:
        if stronger_graphic_evidence and conflicting_shape_claims:
            evidence["single_character_counterevidence"] = stronger_graphic_evidence
            evidence["conflicting_raw_local_word_sets_preserved"] = [list(row) for row in local_word_sets]
        else:
            blocks.append("SINGLE_CHARACTER_OR_PUNCTUATION_INTERPRETATION_RETAINED")
    if any("effective_input_boundary" in reason for reason in region.get("unresolved_reasons", [])):
        # A large OCR crop may touch an unrelated stroke at its boundary. A
        # complete, separately witnessed graphic component inside every raw
        # crop does not inherit that unrelated text-fragment failure. The raw
        # region's truncation decision remains unchanged and is not accepted.
        local_inside = bool(rows) and all(
            row["specification"]["crop_xyxy_px"][0] < component_box[0]
            and row["specification"]["crop_xyxy_px"][1] < component_box[1]
            and component_box[2] < row["specification"]["crop_xyxy_px"][2]
            and component_box[3] < row["specification"]["crop_xyxy_px"][3]
            for row in rows)
        if stronger_graphic_evidence and local_inside:
            evidence["parent_crop_truncation_not_assigned_to_complete_interior_component"] = {
                "all_verified_crops_strictly_contain_complete_component": True,
                "parent_text_truncation_decision_preserved": True,
                "complete_graphic_evidence": stronger_graphic_evidence,
            }
        else:
            blocks.append("TRUE_SOURCE_INPUT_TRUNCATION_RETAINED")
    references = context["references"]
    formal = [row for row in references if _intersects(row["bbox_xyxy_px"], component_box)]
    if formal:
        blocks.append("FORMAL_TEXT_SOURCE_RELATION_REQUIRES_SHARED_CONTACT_PROOF")
    nearby = [row for row in references if _box_distance(row["bbox_xyxy_px"], component_box)
              <= POLICY["local_reference_distance_glyph_heights"] * row["glyph_height_px"]]
    height = float(np.median([row["glyph_height_px"] for row in nearby])) if nearby else None
    evidence["nearby_formal_text_references"] = nearby
    evidence["formal_text_contacts"] = formal
    evidence["reference_glyph_height_px"] = height
    if height is None:
        blocks.append("NO_BOUND_CURRENT_TEXT_SCALE_REFERENCE")
    elif component_box[3] - component_box[1] <= POLICY["text_component_height_ratio"][1] * height:
        blocks.append("SOURCE_COMPONENT_CAN_STILL_BE_CURRENT_SCALE_GLYPH_OR_PUNCTUATION")
    neighbors, fragmented = [], []
    x0, y0, x1, y1 = component_box
    h = y1 - y0
    origin = context["graph"].origin
    for label, (x, y, width, other_height, area) in enumerate(context["stats"][1:], 1):
        if label == source_label or area < 3:
            continue
        b = [x + origin[0], y + origin[1], x + origin[0] + width, y + origin[1] + other_height]
        horizontal_gap = max(b[0] - x1, x0 - b[2], 0)
        lo, hi = POLICY["text_component_height_ratio"]
        if (lo <= other_height / max(h, 1) <= hi
                and abs(b[3] - y1) <= POLICY["text_row_baseline_height_ratio"] * h
                and horizontal_gap <= POLICY["text_row_neighbor_gap_height_ratio"] * h):
            neighbors.append({"source_component_label": label, "bbox_xyxy_px": list(map(float, b))})
        if (max(x0, b[0]) < min(x1, b[2])
                and max(b[1] - y1, y0 - b[3], 0) <= 2):
            fragmented.append({"source_component_label": label, "bbox_xyxy_px": list(map(float, b))})
    if neighbors:
        blocks.append("POSSIBLE_SOURCE_CHARACTER_ROW_RETAINED")
    if fragmented:
        blocks.append("POSSIBLE_FRAGMENTED_CHARACTER_RETAINED")
    evidence.update(source_glyph_row_witnesses=neighbors, fragmented_character_witnesses=fragmented,
                    verified_observations=rows, blocking_reasons=sorted(set(blocks)))
    return evidence


def _separated_continuations(context, points, source_label, height):
    graph, labels = context["graph"], context["labels"]
    evidence = []
    for ordered in (points, points[::-1]):
        tangent = _direction(ordered)
        possibilities = []
        if tangent is not None:
            outward = -tangent[0]
            endpoint = ordered[0]
            for node in graph.nodes.values():
                terminal = node.get("terminal") or {}
                if terminal.get("kind") not in ("OBSERVED_FREE_SOURCE_ENDPOINT", "OBSERVED_CLOSED_TERMINAL_LOBE"):
                    continue
                other_label = int(labels.ravel()[node["pixels"][0]])
                if other_label == source_label:
                    continue
                _, _, width, other_height, _ = context["stats"][other_label]
                if max(width, other_height) <= POLICY["text_component_height_ratio"][1] * height:
                    continue
                for port in node["edges"]:
                    if port[0] == terminal.get("loop_edge_id"):
                        continue
                    neighbor_pixels = graph.oriented(port)
                    if terminal.get("loop_pixels"):
                        loop = terminal["loop_pixels"]
                        neighbor_pixels = (loop + graph.core_route(node["id"], loop[-1], neighbor_pixels[0])[1:]
                                           + neighbor_pixels[1:])
                    neighbor = graph.xy(neighbor_pixels)
                    inward = _direction(neighbor)
                    if inward is None:
                        continue
                    gap = neighbor[0] - endpoint
                    distance = float(np.linalg.norm(gap))
                    if not (POLICY["minimum_original_white_gap_px"] < distance
                            <= POLICY["maximum_gap_glyph_heights"] * height):
                        continue
                    gap_direction = gap / distance
                    angles = [_angle(outward, gap_direction), _angle(outward, inward[0]),
                              _angle(gap_direction, inward[0])]
                    if max(angles) > POLICY["maximum_continuation_angle_deg"]:
                        continue
                    # The actual terminal lobe may extend farther than a fixed
                    # cap. Locate each component's witnessed ink boundary;
                    # require an uninterrupted original white interval between
                    # them and reject every third component in that interval.
                    distances = np.linspace(0, distance, max(3, int(distance * 2) + 1))
                    sample = endpoint + distances[:, None] * gap_direction
                    indices = np.rint(sample - graph.origin).astype(int)
                    chord_labels = labels[indices[:, 1], indices[:, 0]]
                    if any(int(value) not in (0, source_label, other_label) for value in chord_labels):
                        continue
                    target_hits = np.flatnonzero(chord_labels == source_label)
                    neighbor_hits = np.flatnonzero(chord_labels == other_label)
                    if not len(target_hits) or not len(neighbor_hits):
                        continue
                    left, right = int(target_hits[-1]), int(neighbor_hits[0])
                    if (right <= left + 1 or np.any(chord_labels[left + 1:right] != 0)
                            or distances[right - 1] - distances[left + 1] < POLICY["minimum_original_white_gap_px"]):
                        continue
                    possibilities.append({"neighbor_node_id": node["id"], "neighbor_source_component_label": other_label,
                                          "target_endpoint_px": endpoint.tolist(), "neighbor_endpoint_px": neighbor[0].tolist(),
                                          "target_source_tangent_samples": tangent[1].tolist(),
                                          "neighbor_source_tangent_samples": inward[1].tolist(),
                                          "original_white_gap_distance_px": distance, "continuation_angles_deg": angles,
                                          "actual_white_interval_px": [sample[left + 1].tolist(), sample[right - 1].tolist()],
                                          "actual_white_interval_length_px": float(distances[right - 1] - distances[left + 1]),
                                          "source_gap_remains_unconnected": True})
        evidence.append({"unique_witness": len(possibilities) == 1, "witnesses": possibilities})
    valid = all(row["unique_witness"] for row in evidence)
    if valid:
        valid = len({row["witnesses"][0]["neighbor_source_component_label"] for row in evidence}) == 2
    return {"kind": "TWO_SIDED_SEPARATE_SOURCE_STROKE_CONTINUATION", "pass": valid,
            "endpoint_witnesses": evidence, "new_interpolated_gap_geometry": False}


def assess_path_text_contact(context, points, endpoint_evidence, crossing_evidence,
                             collision_region_ids, *, complete_source_path,
                             source_graph_edge_ids=()):
    """A proof-bearing relation; original candidate masks remain unchanged."""
    points = np.asarray(points, float)
    graph = context["graph"]
    p = np.rint(points[0] - graph.origin).astype(int)
    label = int(context["labels"][p[1], p[0]])
    x, y, width, height, _ = context["stats"][label]
    box = [float(x + graph.origin[0]), float(y + graph.origin[1]),
           float(x + graph.origin[0] + width), float(y + graph.origin[1] + height)]
    report = {"schema": "source-text-graphic-contact-certificate-v1", "policy": POLICY,
              "source_array_sha256": context["source_array_sha256"],
              "verified_observations_digest": context["verified_observations_digest"],
              "source_path_sha256": _digest(points.tolist()), "source_component_bbox_xyxy_px": box,
              "complete_source_path": bool(complete_source_path), "candidate_relations": [],
              "raw_candidate_masks_modified": False, "source_pixels_uniquely_partitioned": False,
              "decision": "KEEP_PENDING", "geometry_adoption_authorized": False}
    if context["binding_error"] or not complete_source_path or not collision_region_ids:
        report["reason"] = context["binding_error"] or "NO_COMPLETE_BOUND_CANDIDATE_CONTACT"
        return report
    group = complete_crossing_group(context, source_graph_edge_ids)
    stronger = None
    if group:
        main = max(group["complete_routes"], key=lambda route: _length(np.asarray(route["source_path_points"])))
        references = [row for row in context["references"]
                      if _box_distance(row["bbox_xyxy_px"], box)
                      <= POLICY["local_reference_distance_glyph_heights"] * row["glyph_height_px"]]
        if references:
            scale = float(np.median([row["glyph_height_px"] for row in references]))
            continuations = _separated_continuations(context, np.asarray(main["source_path_points"]), label, scale)
            if continuations["pass"]:
                stronger = {"kind": "COMPLETE_MULTI_CROSSING_GRAPH_AND_SEPARATE_TWO_SIDED_CONTINUATION",
                            "complete_group_certificate_sha256": group["certificate_sha256"],
                            "complete_independent_route_count": len(group["complete_routes"]),
                            "main_route_separate_source_continuations": continuations,
                            "raw_character_hypotheses_preserved": True}
    for region_id in sorted(set(collision_region_ids)):
        region = context["regions"].get(region_id)
        if region is None:
            report["reason"] = "UNKNOWN_SOURCE_REGION"
            return report
        protected = _candidate_protection(context, region, box, label, stronger_graphic_evidence=stronger)
        evidence = None
        if not protected["blocking_reasons"]:
            evidence = group or _separated_continuations(context, points, label, protected["reference_glyph_height_px"])
        passed = bool(evidence and not protected["blocking_reasons"] and evidence.get("pass", group is not None))
        report["candidate_relations"].append({"region_id": region_id,
            "original_role": "UNCONFIRMED_COMPACT_SOURCE_CANDIDATE", "text_protection_checks": protected,
            "graphic_positive_evidence": evidence, "pass": passed,
            "source_relation": "GEOMETRIC_PATH_SUPPORT_WITH_RAW_TEXT_CANDIDATE_RETAINED" if passed else "UNRESOLVED_SHARED_OR_TEXT_SUPPORT"})
    if all(row["pass"] for row in report["candidate_relations"]):
        report["decision"] = "SOURCE_SUPPORTED_GRAPHIC"
        report["positive_evidence_kind"] = group["kind"] if group else "TWO_SIDED_SEPARATE_SOURCE_STROKE_CONTINUATION"
        if group:
            report["complete_graphic_group"] = group
    report["certificate_sha256"] = _digest(report)
    return report
