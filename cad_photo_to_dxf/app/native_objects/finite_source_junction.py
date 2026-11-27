"""Pointwise original-ink junction domains and explicit saved shared vertices.

This is the issue 63 v2 construction, not a tolerance change to the historical
issue 62 constructor. See ``docs/native/ISSUE63_JUNCTION_CONTRACT.md``. A domain
receipt grants permission for one point only; it never assigns nearby ink to a
stroke or replaces complete-component and independently saved-file audits.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct

import numpy as np

from . import attached_stroke_component as component
from . import attached_stroke_width_exact as exact
from .contracts import stable_id


DOMAIN_SCHEMA = "source-finite-junction-domain-v1"
CONSTRUCTION_SCHEMA = "source-supported-new-candidate-shared-vertex-construction-v2"
HALF = Fraction(1, 2)
NEW_CANDIDATE_ROLES = {None, "COMPLETE_TARGET_STROKE", "COMPLETE_ATTACHED_GRAPH_STROKE"}
PRIOR_IDENTITY_FIELDS = {"prior_source_binding", "prior_binding", "full_saved_geometry", "parent_object_id"}


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _point_record(point):
    return [exact.encode_rational(value) for value in point]


def _point_cells(point):
    return [(x, y) for x in range(math.ceil(point[0] - HALF), math.floor(point[0] + HALF) + 1)
            for y in range(math.ceil(point[1] - HALF), math.floor(point[1] + HALF) + 1)]


def _black_cells(source, cells):
    return all(0 <= x < source.shape[1] and 0 <= y < source.shape[0]
               and source[y, x] < component.POLICY["source_threshold"] for x, y in cells)


def _spoke(source, point, neck):
    cells = _point_cells(point) if point == neck else exact.segment_cells(point, neck)
    return {"neck_px": _point_record(neck), "closed_source_cells": [list(cell) for cell in cells],
            "pass": bool(_black_cells(source, cells))}


def _finite_host_location(point, host_points):
    distance, segment, fraction, projected = exact.project_point_polyline(point, host_points)
    internal_vertices = [index for index, vertex in enumerate(host_points[1:-1], 1) if vertex == point]
    # Before construction this projection can have a representation-sized error;
    # the separate exact-intersection rounding proof must justify any insertion.
    # An independent saved auditor also checks exact incidence on the saved host.
    interior = bool(point not in (host_points[0], host_points[-1])
                    and (internal_vertices or 0 < fraction < 1))
    return {"pass": interior, "host_segment_index": segment,
            "projection_parameter_exact": exact.encode_rational(fraction),
            "squared_distance_exact": exact.encode_rational(distance),
            "projected_point_exact": _point_record(projected),
            "existing_internal_vertex_indices": internal_vertices,
            "host_endpoints_never_extended": True}


def prove_finite_junction_domain(source, graph, node_id, guest, host, end_index):
    """Rebuild a three-arm, finite, pointwise raw-source permission certificate.

    ``source`` is the original grayscale array and ``graph`` must be rebuilt
    from it by the caller. No producer PASS, stored core proof or constructed
    endpoint flag is consulted. Saved auditors may supply exact rational source
    coordinates in ``representation_exact_points``; they are not rounded here.
    The returned permission is not an exact host-incidence certificate.
    """
    # The planner imports the component module. Keep this import lazy so the
    # planner can call the new constructor without an import-time cycle.
    from . import attached_stroke_graph as planner

    report = {"schema": DOMAIN_SCHEMA, "pass": False, "failure_reasons": [],
              "node_id": node_id, "guest_id": guest.get("stroke_id"),
              "host_id": host.get("stroke_id"), "end_index": end_index,
              "permission_scope": "ONE_POINT_NOT_BBOX_OR_CONNECTED_INK_OWNERSHIP",
              "source_graph_rebuilt_by_caller_required": True,
              "producer_sha256": producer_sha256(),
              "core_observer_sha256": hashlib.sha256(Path(planner.__file__).read_bytes()).hexdigest(),
              "exact_kernel_sha256": hashlib.sha256(Path(exact.__file__).read_bytes()).hexdigest()}
    try:
        if source.ndim != 2 or source.dtype != np.uint8:
            raise ValueError("ORIGINAL_SOURCE_MUST_BE_UINT8_GRAYSCALE")
        if end_index not in (0, 1):
            raise ValueError("GUEST_ENDPOINT_INDEX_MUST_BE_ZERO_OR_ONE")
        points, host_points = component._points(guest), component._points(host)
        point = points[0 if end_index == 0 else -1]
        report["point_exact"] = _point_record(point)
        report["source_array_sha256"] = hashlib.sha256(source.tobytes()).hexdigest()
        report["source_shape"] = list(source.shape)
        node = graph.nodes[node_id]
        ports = sorted(tuple(port) for port in node["edges"])
        report["all_original_external_ports"] = [list(port) for port in ports]
        if len(ports) != 3 or len(set(ports)) != 3:
            raise ValueError("POINTWISE_T_DOMAIN_REQUIRES_ALL_THREE_ORIGINAL_EXTERNAL_ARMS")
        core = planner._core_proof(source, graph, node_id)
        report["fresh_original_core_observation"] = core
        report["source_core_pixels"] = core["source_core_pixels"]
        report["all_source_core_adjacencies"] = core["all_source_core_adjacencies"]
        report["original_adjacency_deleted"] = False
        if not core["pass"]:
            raise ValueError("ORIGINAL_CORE_HAS_UNPROVED_TOPOLOGY_WHITE_HOLE_OR_INTERNAL_END")
        if core["core_topology"]["cycle_rank"]:
            raise ValueError("THREE_ARM_DOMAIN_DOES_NOT_AUTHORIZE_A_CYCLIC_CORE")
        raw_box = core["raw_ink_box_xyxy_px"]
        report["original_source_patch_sha256"] = _digest({"box": raw_box, "mask": core["raw_ink_mask"]})
        core_points = [tuple(exact.rational(value) for value in pixel) for pixel in core["source_core_pixels"]]
        bounds = (min(p[0] for p in core_points) - HALF, min(p[1] for p in core_points) - HALF,
                  max(p[0] for p in core_points) + HALF, max(p[1] for p in core_points) + HALF)
        report["locator_bounds_exact"] = [exact.encode_rational(value) for value in bounds]
        report["locator_padding_px"] = 0
        report["inside_skeleton_core_closed_cells"] = any(
            all(abs(point[k] - pixel[k]) <= HALF for k in (0, 1)) for pixel in core_points)
        if not (bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]):
            raise ValueError("CONTACT_OUTSIDE_UNPADDED_FINITE_CORE_LOCATOR")
        cells = _point_cells(point)
        report["allowed_contact_cells"] = [list(cell) for cell in cells]
        if not _black_cells(source, cells):
            raise ValueError("CONTACT_TOUCHES_ORIGINAL_WHITE_OR_UNOBSERVED_CELL")
        terminal = guest.get("endpoint_evidence", [])[end_index]
        guest_port = tuple(terminal["port"])
        guest_edges, host_edges = set(guest["source_graph_edge_ids"]), set(host["source_graph_edge_ids"])
        guest_ports = [port for port in ports if port[0] in guest_edges]
        host_ports = [port for port in ports if port[0] in host_edges]
        report["guest_port"] = list(guest_port)
        report["host_ports"] = [list(port) for port in host_ports]
        if (terminal["node_id"] != node_id or node_id not in guest["source_node_ids"]
                or node_id not in host["source_node_ids"] or guest_ports != [guest_port]
                or len(host_ports) != 2 or set(guest_ports + host_ports) != set(ports)
                or guest_edges & host_edges):
            raise ValueError("GUEST_AND_HOST_DO_NOT_OWN_EXACTLY_THE_ORIGINAL_THREE_ARMS")
        directions = planner._node_directions(graph, node_id)
        report["complete_direction_competition"] = directions
        passing = [item for item in directions["all_pair_candidates"] if item["pass"]]
        if (not directions["all_directions_complete"] or len(passing) != 1
                or set(map(tuple, passing[0]["pair"])) != set(host_ports)):
            raise ValueError("HOST_PAIR_IS_NOT_THE_UNIQUE_COMPLETE_SOURCE_CONTINUATION")
        observed = {tuple(item["port"]): item["observations"]
                    for item in directions["all_observed_directions"]}
        separation = min(min(planner._angle(a["vector"], b["vector"]),
                             180 - planner._angle(a["vector"], b["vector"]))
                         for port in host_ports for a, b in zip(observed[guest_port], observed[port]))
        report["minimum_guest_host_axis_separation_deg"] = separation
        if separation < planner.POLICY["minimum_attachment_axis_separation_deg"]:
            raise ValueError("GUEST_SOURCE_ARM_HAS_INSUFFICIENT_HOST_SEPARATION")
        arm_observations, spokes = [], []
        for port in ports:
            observations = component.source_observations(graph, port)
            if (len(observations) != len(component.POLICY["source_direction_spans_px"])
                    or any(item["source_chord_squared_px"] < 16 for item in observations)):
                raise ValueError("ORIGINAL_SOURCE_ARM_HAS_NO_COMPLETE_FIXED_SPAN_DIRECTION")
            if any(a["source_points_px"] != b["source_points_px"]
                   for a, b in zip(observations, observed[port])):
                raise ValueError("FIXED_SOURCE_DIRECTION_OBSERVERS_DISAGREE")
            arm_observations.append({"port": list(port), "observations": observations})
            neck = tuple(exact.rational(v) for v in observations[-1]["source_points_px"][0])
            spoke = _spoke(source, point, neck)
            spoke["port"] = list(port)
            spokes.append(spoke)
        report["all_original_arm_observations"] = arm_observations
        report["all_original_arm_spokes"] = spokes
        if not all(item["pass"] for item in spokes):
            raise ValueError("CONTACT_HAS_NO_ORIGINAL_BLACK_CONNECTION_TO_EVERY_SOURCE_ARM")
        if host.get("body_role") == "NECESSARY_PRIOR_FINITE_PORT":
            from . import finite_source_ports

            host_binding = finite_source_ports.validate_finite_port_certificate(source, graph, host)
            report["host_chain_binding_scope"] = "RECOMPUTED_READ_ONLY_FINITE_PRIOR_PORT"
            report["whole_prior_object_reauthorized"] = False
            report["finite_prior_validator_sha256"] = hashlib.sha256(
                Path(finite_source_ports.__file__).read_bytes()).hexdigest()
        else:
            host_binding = component._chain_binding(source, graph, host)
            report["host_chain_binding_scope"] = "COMPLETE_NEW_TARGET_SOURCE_CHAIN"
        bindings = {"guest": component._chain_binding(source, graph, guest), "host": host_binding}
        report["complete_chain_bindings"] = bindings
        if not all(item["pass"] for item in bindings.values()):
            raise ValueError("JUNCTION_PARTICIPANT_HAS_NO_COMPLETE_SAME_SOURCE_CHAIN")
        location = _finite_host_location(point, host_points)
        report["finite_host_location"] = location
        if not location["pass"]:
            raise ValueError("CONTACT_WOULD_EXTEND_OR_END_THE_COMPLETE_FINITE_HOST")
        support = {"guest": component.exact_centerline_source_support(source, points),
                   "host": component.exact_centerline_source_support(source, host_points)}
        report["finite_native_source_support"] = support
        if not all(item["pass"] for item in support.values()):
            raise ValueError("FINITE_JUNCTION_PARTICIPANT_TOUCHES_ORIGINAL_WHITE_OR_UNOBSERVED_CELL")
        report["pass"] = True
        return planner._plain(report)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        report["failure_reasons"] = [str(error)]
        return planner._plain(report)


def nearest_binary64_certificate(value, exact_value):
    """Prove nearest/ties-to-even rounding with exact adjacent-float midpoints."""
    supplied = exact.rational(value)
    number = float(value)
    if Fraction.from_float(number) != supplied:
        raise ValueError("CONSTRUCTION_COORDINATE_IS_NOT_AN_ACTUAL_BINARY64_VALUE")
    target = exact.rational(exact_value)
    before, after = math.nextafter(number, -math.inf), math.nextafter(number, math.inf)
    if not math.isfinite(before) or not math.isfinite(after):
        raise ValueError("BINARY64_NEIGHBOR_INTERVAL_IS_UNBOUNDED")
    lower, upper = (Fraction.from_float(before) + supplied) / 2, (supplied + Fraction.from_float(after)) / 2
    even = struct.unpack(">Q", struct.pack(">d", number))[0] % 2 == 0
    passed = lower < target < upper or even and target in (lower, upper)
    return {"pass": bool(passed), "actual_binary64_hex": number.hex(),
            "actual_exact": exact.encode_rational(supplied), "intersection_exact": exact.encode_rational(target),
            "rounding_interval_lower": exact.encode_rational(lower),
            "rounding_interval_upper": exact.encode_rational(upper),
            "lower_inclusive": even, "upper_inclusive": even,
            "error_exact": exact.encode_rational(supplied - target),
            "arithmetic": "EXACT_ADJACENT_BINARY64_MIDPOINTS_ROUND_NEAREST_TIES_EVEN"}


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _intersection_certificate(source, point, host_points, domain):
    """Enumerate every source-supported finite ray/host intersection exactly."""
    guest_port = domain["guest_port"]
    arm = next(item for item in domain["all_original_arm_observations"] if item["port"] == guest_port)
    samples = arm["observations"][-1]["source_points_px"]
    origin = tuple(exact.rational(value) for value in samples[0])
    direction = tuple(exact.rational(samples[-1][k]) - origin[k] for k in (0, 1))
    bounds = [exact.decode_rational(value) for value in domain["locator_bounds_exact"]]
    candidates, rejected = [], []
    for index, (start, end) in enumerate(zip(host_points, host_points[1:])):
        delta = tuple(end[k] - start[k] for k in (0, 1))
        offset = tuple(start[k] - origin[k] for k in (0, 1))
        denominator = _cross(direction, delta)
        record = {"host_segment_index": index}
        if not denominator:
            record["reason"] = "PARALLEL_SOURCE_CHORD_AND_FINITE_HOST"
            rejected.append(record)
            continue
        ray, fraction = _cross(offset, delta) / denominator, _cross(offset, direction) / denominator
        intersection = tuple(origin[k] + ray * direction[k] for k in (0, 1))
        record.update(source_ray_parameter_exact=exact.encode_rational(ray),
                      finite_host_fraction_exact=exact.encode_rational(fraction),
                      intersection_exact=_point_record(intersection))
        if ray > 0 or not 0 < fraction < 1:
            record["reason"] = "INTERSECTION_IS_NOT_BACKWARD_SOURCE_RAY_AND_STRICT_FINITE_HOST_INTERIOR"
            rejected.append(record)
            continue
        if not (bounds[0] <= intersection[0] <= bounds[2] and bounds[1] <= intersection[1] <= bounds[3]):
            record["reason"] = "EXACT_INTERSECTION_OUTSIDE_UNPADDED_CORE_LOCATOR"
            rejected.append(record)
            continue
        if not _spoke(source, intersection, origin)["pass"]:
            record["reason"] = "EXACT_SOURCE_RAY_INTERSECTION_TOUCHES_WHITE"
            rejected.append(record)
            continue
        record["coordinate_rounding"] = [nearest_binary64_certificate(point[k], intersection[k]) for k in (0, 1)]
        record["pass"] = all(item["pass"] for item in record["coordinate_rounding"])
        candidates.append(record)
    passed = len(candidates) == 1 and candidates[0]["pass"]
    return {"pass": bool(passed), "source_chord_origin_exact": _point_record(origin),
            "source_chord_delta_exact": _point_record(direction),
            "source_chord_observation": arm["observations"][-1],
            "all_source_supported_finite_intersections": candidates,
            "all_rejected_host_segments": rejected,
            "reason": None if passed else "NO_UNIQUE_CORRECTLY_ROUNDED_ORIGINAL_SOURCE_INTERSECTION"}


def _host_index(terminal, rows, by_id, *, guest_index=None):
    """Resolve every supplied reference against this exact candidate sequence.

    Missing fields may be inferred from the other reference; explicitly invalid
    fields may not. The caller's map is checked against the actual rows rather
    than treated as an authority. The terminal must belong to the guest row.
    """
    identities = [row.get("stroke_id") for row in rows]
    if any(not isinstance(identity, str) or not identity for identity in identities):
        raise ValueError("CANDIDATE_IDENTITY_MUST_BE_A_NONEMPTY_STRING")
    actual = {identity: index for index, identity in enumerate(identities)}
    if (len(actual) != len(rows) or by_id != actual
            or any(type(value) is not int for value in by_id.values())):
        raise ValueError("HOST_LOOKUP_DOES_NOT_MATCH_UNIQUE_ACTUAL_CANDIDATE_IDENTITIES")
    has_name, has_index = "host_path_id" in terminal, "host_path_index" in terminal
    if not has_name and not has_index:
        raise ValueError("ATTACHMENT_HAS_NO_HOST_REFERENCE")
    named = None
    if has_name:
        name = terminal["host_path_id"]
        if not isinstance(name, str) or not name or name not in actual:
            raise ValueError("EXPLICIT_HOST_ID_IS_UNKNOWN_OR_INVALID")
        named = actual[name]
    index = terminal.get("host_path_index") if has_index else named
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError("EXPLICIT_HOST_INDEX_IS_INVALID")
    if has_name and (named != index or rows[index]["stroke_id"] != terminal["host_path_id"]):
        raise ValueError("EXPLICIT_HOST_NAME_INDEX_AND_OBJECT_IDENTITY_DISAGREE")
    owners = [i for i, row in enumerate(rows)
              if any(terminal is item for item in row.get("endpoint_evidence", []))]
    if len(owners) != 1:
        raise ValueError("HOST_REFERENCE_REQUIRES_ONE_ACTUAL_GUEST_IDENTITY")
    if guest_index is None:
        guest_index = owners[0]
    if (type(guest_index) is not int or not 0 <= guest_index < len(rows)
            or owners[0] != guest_index):
        raise ValueError("TERMINAL_DOES_NOT_BELONG_TO_THE_REFERENCED_GUEST_OBJECT")
    if guest_index == index or rows[guest_index] is rows[index]:
        raise ValueError("ATTACHMENT_CANNOT_USE_ITSELF_AS_HOST")
    if ("host_source_graph_edge_ids" in terminal
            and terminal["host_source_graph_edge_ids"] != rows[index].get("source_graph_edge_ids")):
        raise ValueError("HOST_SOURCE_BINDING_DOES_NOT_MATCH_REFERENCED_OBJECT")
    return index


def _all_fit_samples(row):
    core_samples = [point for item in row.get("core_route_alternatives", [])
                    for route in item["all_simple_core_routes_px"] for point in route]
    core_samples += [point for terminal in row.get("endpoint_evidence", [])
                     for route in terminal.get("terminal_core_route_alternatives_px", []) for point in route]
    core_samples += [point for item in row.get("independent_core_walks", [])
                     for route in item["all_walks_px"] for point in route]
    return list(row["source_path_px"]) + core_samples, core_samples


def materialize_shared_vertices_v2(source, graph, rows, cores=None):
    """Return a reversible new-candidate construction and its complete receipt.

    Only existing binary64 guest endpoints are inserted. ``cores`` is accepted
    for integration compatibility and never supplies approval. The source-domain
    proof is reconstructed for every attachment. Any refusal returns original
    rows unchanged, including their identities and host references.
    """
    original, result = deepcopy(rows), deepcopy(rows)
    receipt = {"schema": CONSTRUCTION_SCHEMA, "producer_sha256": producer_sha256(), "pass": False,
               "prior_objects_modified": False, "guest_endpoints_modified": False,
               "cached_core_pass_used": False,
               "preconstruction_geometry": [{"stroke_id": row["stroke_id"],
                                             "representation": deepcopy(row["representation"])} for row in original],
               "attempts": [], "insertions": [], "failure_reasons": []}
    pending, references = {}, []
    try:
        by_id = {row["stroke_id"]: index for index, row in enumerate(original)}
        if len(by_id) != len(original):
            raise ValueError("DUPLICATE_INPUT_CANDIDATE_ID")
        # Preflight the complete input before observing or queuing any contact.
        # All saved/prior identity markers forbid construction, even when a
        # caller supplies a target-looking role beside an old-object binding.
        for row in original:
            if (any(row.get(key) not in NEW_CANDIDATE_ROLES for key in ("body_role", "role", "path_role"))
                    or PRIOR_IDENTITY_FIELDS.intersection(row)):
                raise ValueError("SHARED_VERTEX_CONSTRUCTOR_ACCEPTS_NEW_CANDIDATES_ONLY")
        for index, row in enumerate(original):
            points = component._points(row)
            if any(Fraction.from_float(float(value)) != value for point in points for value in point):
                raise ValueError("CONSTRUCTION_REQUIRES_BINARY64_SOURCE_GEOMETRY_NOT_SAVED_INVERSE_GEOMETRY")
            for end_index, terminal in enumerate(row.get("endpoint_evidence", [])):
                if "host_path_index" not in terminal and "host_path_id" not in terminal:
                    continue
                host_index = _host_index(terminal, original, by_id, guest_index=index)
                host, point = original[host_index], points[0 if end_index == 0 else -1]
                host_points = component._points(host)
                domain = prove_finite_junction_domain(source, graph, terminal["node_id"], row, host, end_index)
                attempt = {"guest_id_before": row["stroke_id"], "host_id_before": host["stroke_id"],
                           "guest_index": index, "host_index": host_index, "end_index": end_index,
                           "source_node_id": terminal["node_id"], "point_exact": _point_record(point),
                           "source_domain": domain}
                receipt["attempts"].append(attempt)
                if not domain["pass"]:
                    raise ValueError("FINITE_ORIGINAL_INK_CONTACT_DOMAIN_NOT_ESTABLISHED:" +
                                     ";".join(domain["failure_reasons"]))
                location = domain["finite_host_location"]
                references.append((index, end_index, host_index))
                if location["existing_internal_vertex_indices"]:
                    attempt["status"] = "ALREADY_EXPLICIT_SHARED_INTERNAL_VERTEX"
                    continue
                rounding = _intersection_certificate(source, point, host_points, domain)
                attempt["exact_source_intersection_rounding"] = rounding
                if not rounding["pass"]:
                    raise ValueError(rounding["reason"])
                candidate = rounding["all_source_supported_finite_intersections"][0]
                segment = candidate["host_segment_index"]
                fraction = exact.decode_rational(candidate["finite_host_fraction_exact"])
                item = {"guest_id_before": row["stroke_id"], "host_id_before": host["stroke_id"],
                        "guest_index": index, "host_index": host_index, "end_index": end_index,
                        "host_segment_index_before": segment, "source_node_id": terminal["node_id"],
                        "point": list(row["representation"]["points"][0 if end_index == 0 else -1]),
                        "point_exact": _point_record(point),
                        "projection_parameter_exact": candidate["finite_host_fraction_exact"],
                        "preconstruction_squared_distance": location["squared_distance_exact"]}
                pending.setdefault((host_index, segment), []).append((fraction, point, item))
                attempt["status"] = "SUPPORTED_INSERTION_QUEUED"
        for key, values in pending.items():
            ordered, unique = sorted(values, key=lambda item: (item[0], item[1])), []
            for value in ordered:
                if unique and value[0] == unique[-1][0] and value[1] != unique[-1][1]:
                    raise ValueError("SHARED_VERTICES_HAVE_COMPETING_EQUAL_PROJECTIONS")
                if not unique or value[:2] != unique[-1][:2]:
                    unique.append(value)
            pending[key] = unique
        for index, row in enumerate(result):
            geometry = deepcopy(row["representation"])
            vertices, retained_indices = [], []
            for segment, point in enumerate(geometry["points"][:-1]):
                retained_indices.append(len(vertices))
                vertices.append(point)
                for _, _, item in pending.get((index, segment), []):
                    vertices.append(item["point"])
                    receipt["insertions"].append(item)
            retained_indices.append(len(vertices))
            vertices.append(geometry["points"][-1])
            if any(a == b for a, b in zip(vertices, vertices[1:])) or len(vertices) > 256:
                raise ValueError("SHARED_VERTEX_ZERO_LENGTH_OR_VERTEX_RESOURCE_BOUND")
            geometry.update(points=vertices, bulges=[0.0] * len(vertices))
            row["representation"] = geometry
            if "representation_exact_points" in row:
                row["representation_exact_points"] = [_point_record(point) for point in vertices]
            points = component._points(row)
            support = component.exact_centerline_source_support(source, points)
            if not support["pass"]:
                receipt["construction_white_cells"] = support["white_or_unobserved_cells"]
                raise ValueError("SHARED_VERTEX_GEOMETRY_TOUCHES_ORIGINAL_WHITE_OR_UNOBSERVED_CELL")
            samples, core_samples = _all_fit_samples(row)
            if any(exact.point_polyline_distance_squared(point, points) > Fraction(9, 4) for point in samples):
                raise ValueError("SHARED_VERTEX_COMPLETE_SOURCE_FIT_NOT_ESTABLISHED")
            row["stroke_id"] = stable_id("GRAPHSTROKE", geometry)
            row["maximum_core_encoding_native_residual_px"] = math.sqrt(float(max(
                (exact.point_polyline_distance_squared(point, points) for point in core_samples), default=Fraction(0))))
            receipt.setdefault("retained_original_vertex_indices", []).append(
                {"candidate_index": index, "indices_in_result": retained_indices})
        for row in result:
            row["native_endpoint_points_px"] = [row["representation"]["points"][0], row["representation"]["points"][-1]]
            for end_index, terminal in enumerate(row.get("endpoint_evidence", [])):
                terminal["native_endpoint_px"] = row["representation"]["points"][0 if end_index == 0 else -1]
        for index, end_index, host_index in references:
            row, host = result[index], result[host_index]
            terminal = row["endpoint_evidence"][end_index]
            terminal["host_path_index"], terminal["host_path_id"] = host_index, host["stroke_id"]
            point = component._points(row)[0 if end_index == 0 else -1]
            distance, segment, fraction, _ = exact.project_point_polyline(point, component._points(host))
            if distance or point not in component._points(host)[1:-1]:
                raise ValueError("CONSTRUCTED_CONTACT_IS_NOT_AN_EXACT_SHARED_INTERNAL_VERTEX")
            terminal["preconstruction_host_segment_index"] = terminal.get("host_segment_index")
            terminal["host_segment_index"], terminal["finite_host_fraction"] = segment, float(fraction)
        receipt["id_mapping"] = [{"candidate_index": index, "old_id": old["stroke_id"], "new_id": new["stroke_id"]}
                                 for index, (old, new) in enumerate(zip(original, result))]
        receipt["host_reference_mapping"] = [{"guest_index": index, "end_index": end_index,
                                             "host_index": host_index,
                                             "old_host_id": original[host_index]["stroke_id"],
                                             "new_host_id": result[host_index]["stroke_id"]}
                                            for index, end_index, host_index in references]
        receipt["reference_validation"] = "ALL_SUPPLIED_NAMES_INDICES_OBJECT_IDENTITIES_AND_GUEST_OWNERSHIP"
        receipt.update({"pass": True, "original_host_vertices_retained": True,
                        "downstream_complete_component_checks_required": True,
                        "actual_saved_exact_contact_check_required": True,
                        "resulting_geometry": [{"stroke_id": row["stroke_id"], "representation": row["representation"]}
                                               for row in result],
                        "changed_candidate_count": sum(a["representation"] != b["representation"]
                                                       for a, b in zip(original, result))})
        return result, receipt
    except (ValueError, KeyError, IndexError, TypeError) as error:
        receipt["failure_reasons"] = [str(error)]
        receipt["original_rows_returned_unchanged"] = True
        return original, receipt


class SharedCoordinateTransform:
    """Ordinary source-to-paper arithmetic, with one value for each source node.

    Use one mapper instance for all new objects in the finite component. Existing
    formal objects are copied under their ordinary strict protection contract.
    ``receipt()`` is bookkeeping, never a replacement for reopening the DXF.
    """

    def __init__(self, roi, dpi):
        if len(roi) != 4 or any(not math.isfinite(float(value)) for value in roi):
            raise ValueError("INVALID_FINITE_EXPORT_ROI")
        self.roi = tuple(float(value) for value in roi)
        if self.roi[0] >= self.roi[2] or self.roi[1] >= self.roi[3]:
            raise ValueError("INVALID_FINITE_EXPORT_ROI")
        self.dpi = float(dpi)
        if not math.isfinite(self.dpi) or self.dpi <= 0:
            raise ValueError("INVALID_FINITE_EXPORT_DPI")
        self.scale = 25.4 / self.dpi
        self._values, self._calls = {}, 0

    def __call__(self, point):
        if len(point) != 2:
            raise ValueError("SOURCE_POINT_MUST_HAVE_TWO_COORDINATES")
        values = tuple(float(value) for value in point)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("NONFINITE_SHARED_SOURCE_COORDINATE")
        if any(Fraction.from_float(value) != exact.rational(original) for value, original in zip(values, point)):
            raise ValueError("SHARED_SOURCE_COORDINATE_IS_NOT_AN_ACTUAL_BINARY64_VALUE")
        key = tuple(value.hex() for value in values)
        self._calls += 1
        if key not in self._values:
            x0, _, _, y1 = self.roi
            self._values[key] = ((values[0] - x0) * self.scale, (y1 - values[1]) * self.scale)
        return self._values[key]

    def receipt(self):
        mapping = [{"source_binary64_hex": list(key), "paper_binary64_hex": [value.hex() for value in result]}
                   for key, result in sorted(self._values.items())]
        return {"schema": "shared-source-node-ordinary-paper-transform-v1", "roi": list(self.roi),
                "dpi": self.dpi, "scale_binary64_hex": self.scale.hex(),
                "operation_sequence": "(x-x0)*(25.4/dpi); (y1-y)*(25.4/dpi)",
                "source_points_snapped": False, "calls": self._calls,
                "unique_source_points": len(self._values), "reused_source_points": self._calls - len(self._values),
                "mapping_sha256": _digest(mapping), "mapping": mapping,
                "actual_saved_exact_contact_check_required": True}
