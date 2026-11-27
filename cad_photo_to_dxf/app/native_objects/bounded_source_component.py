"""Complete finite source accounting for the independently bounded field model.

Geometry, source route ownership, independent width observations and one joint
black/white parameter vector are separate gates. A broader width family never
authorizes an unowned original branch or a changed prior object.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

import numpy as np

from . import attached_stroke_component as legacy
from . import attached_stroke_width_exact as exact
from . import bounded_stroke_field_v2 as field_model
from . import finite_circle_source as circles
from . import finite_source_ports as ports
from .finite_source_junction import prove_finite_junction_domain

SCHEMA = "source-finite-component-responsibility-v2-bounded-field"
POLICY = {**legacy.POLICY,
    "version": "complete-independent-bounded-field-finite-prior-and-actual-circle-v2",
    "width_parameter_scope": "FIXED_INDEPENDENT_SECTION_AND_FINITE_GEOMETRY_KNOTS",
    "constant_intersection_does_not_exclude_continuous_family": True,
    "prior_scope": "TARGET_CONTINUATION_AND_COMPLETE_ACTUAL_EVIDENCE_READ_DOMAIN",
    "circle_geometry": "ACTUAL_FINITE_CIRCLE_ALGEBRA_NO_CHORD_SUBSTITUTION",
    "unowned_source_edges_cannot_be_explained_by_width": True,
    "all_eligible_section_black_and_white_use_same_vector": True,
    "maximum_context_bodies": 32}


def producer_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _circle(row):
    return row.get("curve_type", row.get("kind")) == "CIRCLE"


def _needed_geometry(points, relevant_cells, window):
    """A broad box is only rejection; inclusion observes actual source cells."""
    x0, y0, x1, y1 = window
    reach = POLICY["maximum_section_half_span_px"]
    if (max(p[0] for p in points) < x0 - reach or min(p[0] for p in points) > x1 + reach or
            max(p[1] for p in points) < y0 - reach or min(p[1] for p in points) > y1 + reach):
        return False
    prepared = exact.prepare_polyline(points)
    return any(exact.cell_polyline_distance_squared(cell, prepared) < reach ** 2 for cell in relevant_cells)


def _circle_relevant(row, relevant_cells, window):
    center, radius = circles.circle_geometry(row)
    x0, y0, x1, y1 = window
    reach = POLICY["maximum_section_half_span_px"]
    if (center[0] + radius < x0 - reach or center[0] - radius > x1 + reach or
            center[1] + radius < y0 - reach or center[1] - radius > y1 + reach):
        return False
    # Discovery uses the predeclared observation cap only. Coverage requires
    # the separate independently measured strict interval and ring ownership.
    return any(circles.circle_cell_intersects(row, cell, F(reach ** 2)) for cell in relevant_cells)


def _actual_relevant(row, relevant_cells, window):
    if row is None:
        return False
    try:
        if _circle(row):
            return _circle_relevant(row, relevant_cells, window)
        if row.get("geometry_supported"):
            return _needed_geometry(ports._points(row), relevant_cells, window)
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    box = row.get("bbox_xyxy")
    if box is None:
        return True  # An unknown actual extent cannot prove disjointness.
    reach = POLICY["maximum_section_half_span_px"]
    return not (box[2] < window[0]-reach or box[0] > window[2]+reach or
                box[3] < window[1]-reach or box[1] > window[3]+reach)


def _context(source, graph, targets, domain, relevant_cells, prior_objects,
             circle_source_objects, actual_saved_prior_rows, roi, dpi):
    """Bind every necessary original body before admitting any finite part."""
    saved = None if actual_saved_prior_rows is None else {
        row["object_id"]: row for row in actual_saved_prior_rows}
    objects = {obj["id"]: obj for obj in prior_objects}
    circle_objects = {obj["id"]: obj for obj in circle_source_objects}
    candidates, circle_candidates, receipts, unresolved = [], [], [], []
    window = domain["model_window"]
    target_ids = {row["stroke_id"] for row in targets}
    for oid, obj in sorted(objects.items()):
        if oid in target_ids:
            continue
        geometry = obj.get("geometry", {})
        if ("points" in geometry or ("start" in geometry and "end" in geometry)) and not geometry.get("closed") and not any(geometry.get("bulges", [])):
            try:
                source_row = ports.prior_source_geometry_row(obj)
                actual = source_row if saved is None else saved.get(oid)
                source_points = ports._points(source_row)
                if not (_needed_geometry(source_points, relevant_cells, window) or
                        _actual_relevant(actual, relevant_cells, window)):
                    continue
                if actual is None:
                    unresolved.append({"object_id": oid, "reason": "NECESSARY_PRIOR_NOT_IN_ACTUAL_SAVED_MEMBERSHIP"})
                    continue
                receipt = ports.certify_finite_prior_port(source, graph, actual, obj, domain, roi=roi, dpi=dpi)
                receipts.append({"object_id": oid, "receipt": receipt})
                # Preserve failed bodies and their reads; do not model the
                # surviving subset as if the missing prior were unnecessary.
                candidates.extend(receipt.get("rows", []))
                if not receipt["pass"]:
                    unresolved.append({"object_id": oid, "reason": "NECESSARY_FINITE_PRIOR_CERTIFICATE_PENDING",
                                       "failures": receipt["failures"]})
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                unresolved.append({"object_id": oid, "reason": str(exc)})
        elif obj.get("kind") in ("CIRCLE", "CIRCULAR_MARKER"):
            try:
                source_row = circles.circle_source_geometry_row(obj)
                actual = source_row if saved is None else saved.get(oid)
                # Marker readers can give a stable child ID while retaining
                # the original parent identity.
                if saved is not None and actual is None:
                    matches = [row for row in saved.values() if row.get("parent_object_id") == oid and _circle(row)]
                    actual = matches[0] if len(matches) == 1 else None
                actual_members = [] if saved is None else [row for row in saved.values()
                    if row.get("parent_object_id", row["object_id"]) == oid]
                if not (_circle_relevant(source_row, relevant_cells, window) or
                        _actual_relevant(actual, relevant_cells, window) or
                        any(_actual_relevant(row, relevant_cells, window) for row in actual_members)):
                    continue
                complete = circle_objects.get(oid)
                if complete is None or actual is None:
                    unresolved.append({"object_id": oid, "reason": "NECESSARY_ACTUAL_CIRCLE_OR_COMPLETE_SOURCE_IDENTITY_MISSING"})
                    continue
                recovered_row = circles.circle_source_geometry_row(complete)
                if (circles.circle_geometry(recovered_row) != circles.circle_geometry(source_row)
                        or complete.get("kind") != obj.get("kind") or complete.get("layer") != obj.get("layer")):
                    unresolved.append({"object_id": oid, "reason": "RECOVERED_CIRCLE_AND_PRIOR_BINDING_IDENTITIES_DISAGREE"})
                    continue
                circle_candidates.append((actual, complete))
            except (ValueError, KeyError, TypeError) as exc:
                unresolved.append({"object_id": oid, "reason": str(exc)})
    # An explicitly recovered circle may be absent from an older pruned
    # binding list. Its full original identity is still required and checked.
    for oid, obj in sorted(circle_objects.items()):
        if oid in objects:
            continue
        source_row = circles.circle_source_geometry_row(obj)
        actual = source_row if saved is None else next((r for r in saved.values()
            if r.get("parent_object_id", r["object_id"]) == oid and _circle(r)), None)
        if _circle_relevant(source_row, relevant_cells, window) or _actual_relevant(actual, relevant_cells, window):
            if actual is None:
                unresolved.append({"object_id": oid, "reason": "RECOVERED_CIRCLE_NOT_IN_ACTUAL_SAVED_MEMBERSHIP"})
            else:
                circle_candidates.append((actual, obj))
    if saved is not None:
        known = set(objects) | set(circle_objects)
        for row in saved.values():
            parent = row.get("parent_object_id", row["object_id"])
            if parent not in known and row["object_id"] not in known and _actual_relevant(row, relevant_cells, window):
                unresolved.append({"object_id": row["object_id"], "parent_object_id": parent,
                    "reason": "RELEVANT_ACTUAL_PRIOR_HAS_NO_COMPLETE_SOURCE_IDENTITY"})
    if len(targets) + len(candidates) + len(circle_candidates) > POLICY["maximum_context_bodies"]:
        unresolved.append({"reason": "NECESSARY_BODY_RESOURCE_BOUND"})
    return candidates, circle_candidates, receipts, unresolved


def _measure_target(source, graph, body, all_rows, forbidden):
    curves = [row for row in all_rows if _circle(row)]
    width = legacy.measure_whole_chain_width(source, graph, body,
        [row for row in all_rows if not _circle(row)], forbidden_core_cells=forbidden)
    # Tangent chords never replace a circle. Conservative exact radial
    # clearance can only discard a contaminated normal section.
    for section in width["sections"]:
        if not section.get("constraint_eligible"):
            continue
        q = tuple(exact.decode_rational(v) for v in section["center_exact"])
        hi = exact.decode_rational(section["half_width_squared_interval"]["upper"])
        near = [row["stroke_id"] for row in curves if not circles.circle_point_strictly_outside(row, q, 8 * hi + 1)]
        section["interfering_actual_circle_ids"] = near
        if near:
            section.update({"pass": False, "constraint_eligible": False, "independent": False,
                            "reason": "SECTION_NOT_INDEPENDENT_OF_ACTUAL_CIRCLE_AXIS"})
    recomputed = exact.intersect_sections(width["sections"], min_sections=2)
    width.update(recomputed)
    width["all_actual_circle_axes_checked"] = True
    return width


def _junction_controls(source, graph, targets, prior):
    controls, receipts = {row["stroke_id"]: [] for row in targets}, []
    by_id = {row["stroke_id"]: row for row in targets + prior}
    for guest in targets:
        for end, terminal in enumerate(guest.get("endpoint_evidence", [])):
            if "host_path_id" not in terminal:
                continue
            host = by_id.get(terminal["host_path_id"])
            if host is None:
                receipts.append({"pass": False, "reason": "JUNCTION_HOST_ID_NOT_IN_ACTUAL_TARGET_MEMBERSHIP"})
                continue
            proof = prove_finite_junction_domain(source, graph, terminal["node_id"], guest, host, end)
            receipts.append(proof)
            if proof["pass"]:
                point = legacy._points(guest)[0 if end == 0 else -1]
                if exact.point_polyline_distance_squared(point, legacy._points(host)) == 0:
                    controls.setdefault(host["stroke_id"], []).append(point)
                else:
                    receipts.append({"pass": False, "reason": "ACTUAL_JUNCTION_POINT_IS_NOT_EXACT_FINITE_HOST_POINT"})
    return controls, receipts


def _bind_prior_hosts(targets, prior):
    """Resolve an old host locator to one certified, actual finite portion."""
    receipts = []
    for guest in targets:
        for end, terminal in enumerate(guest.get("endpoint_evidence", [])):
            if not terminal.get("host_requires_necessary_prior_proof"):
                continue
            parent = terminal.get("finite_prior_host_parent_id", terminal.get("host_path_id"))
            point = legacy._points(guest)[0 if end == 0 else -1]
            candidates = [row for row in prior if row.get("parent_object_id") == parent
                and terminal["node_id"] in row.get("source_node_ids", [])
                and exact.point_polyline_distance_squared(point, legacy._points(row)) == 0
                and point not in (legacy._points(row)[0], legacy._points(row)[-1])]
            receipt = {"guest_id": guest["stroke_id"], "end": end, "whole_prior_parent_id": parent,
                "eligible_actual_finite_host_ids": [row["stroke_id"] for row in candidates],
                "pass": len(candidates) == 1, "original_whole_host_locator": terminal.get("host_path_id")}
            receipts.append(receipt)
            if len(candidates) == 1:
                terminal["host_path_id"] = candidates[0]["stroke_id"]
                terminal["host_source_graph_edge_ids"] = candidates[0]["source_graph_edge_ids"]
    return receipts


def _source_edge_ledger(graph, bodies, relevant_cells):
    """Original branch ownership is independent of variable-width coverage."""
    assigned = {}
    for body in bodies:
        if _circle(body):
            cells = ports.cells_from_runs(body["authorized_original_ring_cells_y_x0_x1"])
            for p in cells:
                assigned.setdefault(p, set()).add(body["stroke_id"])
        else:
            for point in body.get("source_path_px", []):
                assigned.setdefault(tuple(map(int, point)), set()).add(body["stroke_id"])
    ledger, unexplained = [], []
    for eid, edge in enumerate(graph.edges):
        raw = [tuple(map(int, p)) for p in graph.xy(edge["pixels"])]
        observed = [p for p in raw if p in relevant_cells]
        if not observed:
            continue
        missing = [p for p in observed if not assigned.get(p)]
        record = {"original_edge_id": eid, "in_window_original_source_pixels": [list(p) for p in observed],
            "body_ids": sorted({oid for p in observed for oid in assigned.get(p, [])}),
            "unassigned_original_source_pixels": [list(p) for p in missing],
            "pass": not missing, "width_coverage_consumed_as_ownership": False}
        ledger.append(record)
        if missing:
            unexplained.append(eid)
    return {"pass": not unexplained, "all_original_edges_examined": len(graph.edges),
        "relevant_edges": ledger, "unassigned_original_edge_ids": unexplained,
        "short_failed_and_truncated_branches_are_not_erased": True}


def _exit(cell, body, graph, window):
    if _circle(body):
        authorized = ports.cells_from_runs(body["authorized_original_ring_cells_y_x0_x1"])
        if tuple(cell) in authorized:
            return {"body_id": body["stroke_id"], "kind": "EXACT_ACTUAL_CIRCLE_FINITE_ARC_EXIT",
                    "source_cell_in_independently_bound_original_ring": True}
        return None
    points = legacy._points(body)
    _, segment, fraction, _ = exact.project_point_polyline(cell, points)
    if not 0 < fraction < 1:
        return None
    field = field_model.prepare_field(body["bounded_width_field"])
    if not field_model.cell_compatible_with_strict_upper(field, cell):
        return None
    x0, y0, x1, y1 = window
    sides = ([(0, x0, -1)] if cell[0] == x0 else []) + ([(0, x1-1, 1)] if cell[0] == x1-1 else [])
    sides += ([(1, y0, -1)] if cell[1] == y0 else []) + ([(1, y1-1, 1)] if cell[1] == y1-1 else [])
    bound = {tuple(map(int, p)) for p in body.get("source_path_px", [])}
    for terminal in body.get("endpoint_evidence", []):
        bound.update(tuple(p) for p in terminal.get("both_sides_source_points_px", []))
    for axis, boundary, sign in sides:
        for eid in body["source_graph_edge_ids"]:
            raw = np.asarray(graph.xy(graph.edges[eid]["pixels"]), int)
            eligible = np.asarray([tuple(p) in bound for p in raw], bool)
            signed = sign * (raw[:, axis] - boundary)
            near = np.sum((raw - np.asarray(cell)) ** 2, axis=1) <= 13 ** 2
            if np.any(eligible & near & (signed <= -4)) and np.any(eligible & near & (signed >= 4)):
                return {"body_id": body["stroke_id"], "source_edge_id": eid,
                    "native_segment_index": segment, "same_bound_source_arm_on_both_sides_px": 4,
                    "kind": "FINITE_SOURCE_BOUND_SHAFT_EXIT"}
    return None


def _observations(source, bodies, black, white):
    own, first_white, measured_white, all_reads = [], [], [], set()
    for body in bodies:
        for index, section in enumerate(body["width"].get("sections", [])):
            all_reads.update(tuple(p) for p in section.get("section_source_cells", []))
            measured_white.extend(cell for cell, value in zip(section.get("section_source_cells", []),
                section.get("original_values", [])) if value is not None and value >= 128)
            observation = section.get("observation", {})
            all_reads.update(tuple(p) for p in observation.get("source_points_px", []))
            if section.get("constraint_eligible"):
                own.extend({"body_id": body["stroke_id"], "source_cell": cell,
                            "section_index": index} for cell in section["independent_black_cells"])
                first_white.extend(section["first_white_cells"])
    source_checks = all(0 <= x < source.shape[1] and 0 <= y < source.shape[0] for x, y in all_reads)
    source_checks &= all(int(source[row["source_cell"][1], row["source_cell"][0]]) < 128 for row in own)
    source_checks &= all(int(source[p[1], p[0]]) >= 128 for p in first_white + measured_white)
    return {"pass": source_checks, "black_cells": black, "white_cells": list(dict.fromkeys(
        tuple(p) for p in white + first_white + measured_white)), "owned_black_constraints": own,
        "all_eligible_first_white_cells": first_white, "all_section_reads_y_x0_x1": ports._runs(all_reads),
        "all_actually_measured_section_white_cells": measured_white,
        "failed_and_ineligible_section_white_observations_retained": True,
        "one_shared_complete_parameter_vector_required": True}


def _continuations(source, targets, bodies, endpoints, observed, ledger, supported, source_edges):
    result = {"events": [], "new_geometry_generated": False,
        "distinct_observable_boundary_exists": False, "search_complete": False,
        "hidden_pen_travel": "SAME_DECLARED_EDITING_REPRESENTATION",
        "unassigned_source_edges_checked_even_inside_width_envelope": source_edges}
    if not supported:
        result["status"] = "NOT_RUN_INDEPENDENT_BOUND_OR_CONTEXT_PENDING"
        return result
    if not source_edges["pass"]:
        result.update(status="PENDING_UNASSIGNED_ORIGINAL_SOURCE_BRANCH",
            original_unassigned_edge_ids=source_edges["unassigned_original_edge_ids"])
        return result
    residual = [row["source_cell"] for row in ledger if row["relevant_connected_ink"] and not row["compatible_body_ids"]]
    if not residual:
        result.update(status="ALL_ORIGINAL_BRANCHES_BOUND_AND_NO_OBSERVABLE_OUTWARD_RESIDUAL",
            search_complete=True, completeness_scope="ORIGINAL_SOURCE_BRANCHES_AND_BLACK_CELL_RESIDUAL_EVENTS")
        return result
    by_id = {row["stroke_id"]: i for i, row in enumerate(bodies)}
    if not hasattr(field_model, "extend_endpoint_field"):
        result["status"] = "NOT_RUN_CONTINUOUS_EXTENSION_SOLVER_UNAVAILABLE"
        return result
    count = 0
    for endpoint in endpoints:
        if "host_id" not in endpoint:
            continue
        row = next(row for row in targets if row["stroke_id"] == endpoint["guest_id"])
        points = legacy._points(row)
        end, adjacent = (0, 1) if endpoint["end"] == 0 else (-1, -2)
        origin, direction = points[end], tuple(points[end][k]-points[adjacent][k] for k in (0, 1))
        norm2 = sum(v*v for v in direction)
        if not norm2 or not endpoint["source_direction_pass"]:
            result["status"] = "PENDING_EXTENSION_SOURCE_DIRECTION"
            return result
        scales = {sum((p[k]-origin[k])*direction[k] for k in (0, 1))/norm2
                  for cell in residual for p in legacy._white_points(cell)}
        scales = [s for s in sorted(scales) if s > 0 and s*s*norm2 <= POLICY["maximum_extension_px"]**2]
        for scale in scales:
            if count >= POLICY["maximum_extension_events"]:
                result.update(status="PENDING_EXTENSION_EVENT_RESOURCE_BOUND", resource_truncated=True)
                return result
            count += 1
            point = tuple(origin[k]+scale*direction[k] for k in (0, 1))
            support = legacy.exact_centerline_source_support(source, [origin, point])
            event = {"guest_id": row["stroke_id"], "end": endpoint["end"],
                "endpoint_exact": legacy._encoded_point(point), "scale_exact": exact.encode_rational(scale),
                "finite_source_support": support, "adopted": False}
            if not support["pass"]:
                event["model_status"] = "NOT_RUN_EXACT_WHITE_CENTERLINE_REFUSAL"
                result["events"].append(event)
                continue
            extended = deepcopy(bodies)
            i = by_id[row["stroke_id"]]
            extended[i]["bounded_width_field"] = field_model.extend_endpoint_field(
                extended[i]["bounded_width_field"], 0 if endpoint["end"] == 0 else -1, point)
            model = field_model.solve_bounded_union(observed["black_cells"], observed["white_cells"], extended,
                owned_black_constraints=observed["owned_black_constraints"])
            event.update(model_status=model["status"], coherent_with_original_black_and_white=model["pass"],
                         same_all_independent_section_constraints=True, model=model)
            result["events"].append(event)
            if model["pass"]:
                result.update(status="OBSERVABLE_OUTWARD_FINITE_BOUNDARY_COMPETITOR",
                              distinct_observable_boundary_exists=True, search_complete=False)
                return result
            if not model.get("exact_family_infeasibility_proved"):
                result["status"] = "PENDING_EXTENSION_MODEL_PARAMETER_SEARCH"
                return result
    result.update(status="ALL_OBSERVABLE_OUTWARD_EVENTS_REFUSED", search_complete=True)
    return result


def audit_bounded_bodies(source, graph, rows, *, owner=None, cores=None, prior_objects=None,
                         circle_source_objects=None, actual_saved_prior_rows=None, roi=None, dpi=200):
    """Shared model seam, with independently reconstructed source/saved inputs."""
    source, cores = np.asarray(source), cores or {}
    roi = list(graph.roi) if roi is None else list(roi)
    prior_objects, circle_source_objects = list(prior_objects or []), list(circle_source_objects or [])
    if owner is not None:
        binding = owner.get("binding", owner)
        if binding["id"] not in {obj["id"] for obj in prior_objects}:
            prior_objects.append(binding)
    targets = [deepcopy(row) for row in rows if not row.get("body_role", "").startswith("NECESSARY_PRIOR")]
    report = {"schema": SCHEMA, "policy": deepcopy(POLICY), "producer_sha256": producer_sha256(),
        "field_producer_sha256": field_model.producer_sha256(), "pass": False, "status": "PENDING",
        "failure_reasons": [], "new_geometry_generated": False,
        "candidate_ids": [row["stroke_id"] for row in targets], "bodies": [],
        "prior_objects_modified": False, "geometry_wrong_or_scan_ambiguous_asserted": False}
    try:
        if not targets or any(len(row.get("endpoint_evidence", [])) != 2 for row in targets):
            raise ValueError("COMPLETE_TARGET_REQUIRES_TWO_FRESH_ENDPOINT_RECEIPTS")
        for row in targets:
            row["body_role"] = "COMPLETE_TARGET_STROKE"
        patch, black, relevant, white = legacy._window(source, graph, targets)
        report["original_patch"] = patch
        relevant_cells = {tuple(cell) for cell, own in zip(black, relevant) if own}
        domain = ports.build_influence_domain(source, graph, targets, patch["raw_box_xyxy_px"])
        report["influence_domain"] = domain
        prior, circle_candidates, receipts, unresolved = _context(source, graph, targets, domain,
            relevant_cells, prior_objects, circle_source_objects, actual_saved_prior_rows, roi, dpi)
        report["necessary_prior_certificates"] = receipts
        report["unresolved_necessary_context"] = unresolved
        straight = targets + prior
        circle_axes = [{**row, "stroke_id": row["object_id"]} for row, _ in circle_candidates]
        all_axes = straight + circle_axes
        forbidden = {tuple(map(int, p)) for node in graph.nodes.values()
            for p in graph.xy(node["pixels"])}
        report["finite_prior_host_resolution"] = _bind_prior_hosts(targets, prior)
        if any(not row["pass"] for row in report["finite_prior_host_resolution"]):
            raise ValueError("OLD_HOST_LOCATOR_HAS_NO_UNIQUE_ACTUAL_FINITE_SOURCE_PORT")
        controls, junction_receipts = _junction_controls(source, graph, targets, prior)
        report["fresh_finite_junction_domains"] = junction_receipts
        for body in straight:
            is_prior = body.get("body_role") == ports.ROLE
            body["chain_binding"] = (ports.validate_finite_port_certificate(source, graph, body,
                prior_object=body["prior_binding"], expected_influence_domain=domain) if is_prior else
                legacy._chain_binding(source, graph, body))
            body["width"] = (ports.measure_finite_port_sections(source, graph, body, all_axes,
                forbidden_core_cells=forbidden) if is_prior else _measure_target(source, graph, body, all_axes, forbidden))
            body["historical_constant_width_receipt"] = deepcopy(body["width"])
            body["bounded_width_field"] = field_model.build_width_field(legacy._points(body), body["width"],
                junction_points=controls.get(body["stroke_id"], []))
            body["native_centerline_source_support"] = (body["finite_positive_length_source_support"] if is_prior else
                legacy.exact_centerline_source_support(source, legacy._points(body)))
            body["independently_supported"] = bool(body["chain_binding"]["pass"] and
                body["bounded_width_field"]["pass"] and body["native_centerline_source_support"]["pass"])
        observation = _observations(source, straight, sorted(relevant_cells), white)
        read_cells = ports.cells_from_runs(observation["all_section_reads_y_x0_x1"])
        window = patch["raw_box_xyxy_px"]
        circle_scope = [min([window[0]]+[p[0] for p in read_cells]), min([window[1]]+[p[1] for p in read_cells]),
                        max([window[2]]+[p[0]+1 for p in read_cells]), max([window[3]]+[p[1]+1 for p in read_cells])]
        circle_receipts, circle_bodies = [], []
        for actual, obj in circle_candidates:
            receipt = circles.certify_finite_circle_source(source, actual, obj, circle_scope, roi=roi, dpi=dpi,
                other_rows=all_axes, forbidden_core_cells=forbidden)
            circle_receipts.append(receipt)
            if "row" in receipt:
                body = receipt["row"]
                body["independently_supported"] = receipt["pass"]
                body["source_circle_certificate"] = {k: v for k, v in receipt.items() if k != "row"}
                circle_bodies.append(body)
            if not receipt["pass"]:
                unresolved.append({"object_id": actual["object_id"], "reason": "FINITE_CIRCLE_SOURCE_PENDING",
                                   "failures": receipt["failures"]})
        report["necessary_actual_circle_certificates"] = circle_receipts
        bodies = straight + circle_bodies
        report["bodies"] = bodies
        observation = _observations(source, bodies, sorted(relevant_cells), white)
        report["all_model_observations"] = observation
        actual_reads = ports.cells_from_runs(observation["all_section_reads_y_x0_x1"])
        for row in prior:
            actual_reads |= ports.cells_from_runs(row.get("complete_evidence_read_cells_y_x0_x1", []))
        report["complete_model_evidence_read_cells_y_x0_x1"] = ports._runs(actual_reads)
        for entry in receipts:
            for finding in entry["receipt"].get("excluded_remote_findings", []):
                if any(tuple(p) in actual_reads for p in finding["white_cells"]):
                    unresolved.append({"object_id": entry["object_id"],
                        "reason": "PREVIOUSLY_REMOTE_PRIOR_FAILURE_INTERSECTS_COMPLETE_MODEL_EVIDENCE_READS",
                        "finding": finding})
        report["endpoints"] = legacy._endpoint_rows(graph, targets, cores, all_rows=straight)
        source_edges = _source_edge_ledger(graph, bodies, relevant_cells)
        report["independent_source_edge_accounting"] = source_edges
        supported = [body for body in bodies if body["independently_supported"]]
        prepared = {body["stroke_id"]: field_model.prepare_field(body["bounded_width_field"])
                    for body in supported if not _circle(body)}
        circle_ring = {b["stroke_id"]: ports.cells_from_runs(b["authorized_original_ring_cells_y_x0_x1"])
                       for b in supported if _circle(b)}
        ledger, exits = [], []
        x0, y0, x1, y1 = window
        for cell, own in zip(black, relevant):
            ids = []
            if own:
                for body in supported:
                    if _circle(body):
                        upper = exact.decode_rational(body["width"]["half_width_squared_interval"]["upper"])
                        compatible = tuple(cell) in circle_ring[body["stroke_id"]] and circles.circle_cell_intersects(body, cell, upper)
                    else:
                        compatible = field_model.cell_compatible_with_strict_upper(prepared[body["stroke_id"]], cell)
                    if compatible:
                        ids.append(body["stroke_id"])
            ledger.append({"source_cell": cell, "original_gray_value": int(source[cell[1], cell[0]]),
                "relevant_connected_ink": bool(own), "compatible_body_ids": ids,
                "classification": "DISCONNECTED_NEIGHBOR" if not own else "FINITE_BOUNDED_BODY_COMPATIBLE" if ids else "UNKNOWN_CONNECTED_INK",
                "assignment_is_joint_model_proved": False})
            if own and (cell[0] in (x0, x1-1) or cell[1] in (y0, y1-1)):
                proofs = [proof for body in supported if (proof := _exit(cell, body, graph, window))]
                exits.append({"source_cell": cell, "source_proofs": proofs,
                    "classification": "PROVED_FINITE_SOURCE_EXIT" if proofs else "UNKNOWN_CONNECTED_EXIT"})
        report["pixel_ledger"], report["window_exits"] = ledger, exits
        report["white_ledger"] = [{"source_cell": cell, "original_gray_value": int(source[cell[1], cell[0]])} for cell in white]
        report["observation_closed"] = not patch["clipped_by_source_or_roi"] and all(row["source_proofs"] for row in exits)
        all_supported = len(supported) == len(bodies) and not unresolved and observation["pass"]
        model = (field_model.solve_bounded_union(observation["black_cells"], observation["white_cells"], bodies,
            owned_black_constraints=observation["owned_black_constraints"]) if all_supported else
            {"pass": False, "status": "NOT_RUN_NECESSARY_BOUND_OR_CONTEXT_NOT_ESTABLISHED",
             "unsupported_body_ids": [row["stroke_id"] for row in bodies if not row["independently_supported"]],
             "search_complete": False, "exact_family_infeasibility_proved": False})
        report["coherent_component_model"] = model
        if model["pass"]:
            witnesses = {tuple(row["source_cell"]): row["body_ids"] for row in model["black_witnesses"]
                         if row.get("constraint_role") == "COMPONENT_BLACK_CELL"}
            for item in ledger:
                if tuple(item["source_cell"]) in witnesses:
                    item.update(joint_model_body_ids=witnesses[tuple(item["source_cell"])], assignment_is_joint_model_proved=True)
        report["short_continuation_competition"] = _continuations(source, targets, bodies, report["endpoints"],
            observation, ledger, all_supported, source_edges)
        failures = report["failure_reasons"]
        if unresolved:
            failures.append("NECESSARY_FINITE_PRIOR_OR_CIRCLE_CONTEXT_PENDING")
        if not all_supported:
            failures.append("INDEPENDENT_COMPLETE_BOUNDED_BODIES_NOT_ESTABLISHED")
        if not all(receipt["pass"] for receipt in junction_receipts):
            failures.append("FRESH_FINITE_JUNCTION_SOURCE_DOMAIN_NOT_ESTABLISHED")
        if not source_edges["pass"]:
            failures.append("UNASSIGNED_ORIGINAL_SOURCE_BRANCH_CANNOT_BE_ABSORBED_BY_WIDTH")
        if not report["observation_closed"]:
            failures.append("PENDING_UNKNOWN_EXIT_OR_CLIPPED_TARGET_SCOPE")
        if not model["pass"]:
            failures.append("COHERENT_COMPLETE_BLACK_WHITE_PARAMETER_VECTOR_NOT_ESTABLISHED")
        for endpoint in report["endpoints"]:
            if not endpoint["source_direction_pass"]:
                failures.append("SOURCE_DIRECTION_CHORD_NOT_ESTABLISHED")
            if "host_id" in endpoint and (not endpoint["exact_finite_host_contact"] or not endpoint["shared_core_independently_supported"]):
                failures.append("EXACT_FINITE_ATTACHMENT_OR_INDEPENDENT_CORE_NOT_ESTABLISHED")
            if "host_id" not in endpoint and not (endpoint["observed_free_end"] and endpoint["fresh_free_cap_pass"]):
                failures.append("COMPLETE_FREE_ENDPOINT_RESPONSIBILITY_NOT_ESTABLISHED")
        competition = report["short_continuation_competition"]
        if competition["distinct_observable_boundary_exists"]:
            failures.append("OBSERVABLE_FINITE_BOUNDARY_COMPETITOR")
        elif not competition["search_complete"]:
            failures.append("BOUNDARY_COMPETITION_NOT_COMPLETELY_RESOLVED")
        report["complete_pixel_accounting"] = len(ledger) + len(white) == int(np.prod(patch["source_window_shape"]))
        report["historical_constant_failures"] = [{"body_id": b["stroke_id"], "receipt": b["historical_constant_width_receipt"]}
            for b in straight if not b["historical_constant_width_receipt"]["pass"]]
        report["failure_reasons"] = sorted(set(failures))
        report["pass"] = not failures
        report["status"] = "COMPLETE_BOUNDED_SOURCE_MODEL_PASS" if report["pass"] else "PENDING_COMPLETE_BOUNDED_SOURCE_RESPONSIBILITY"
    except (ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
        report.update(status="PENDING_INVALID_OR_RESOURCE_LIMITED_BOUNDED_INPUT", failure_reasons=[str(exc)])
    return report


def prove_finite_component(source, graph, rows, *, owner=None, cores=None, **kwargs):
    return audit_bounded_bodies(source, graph, rows, owner=owner, cores=cores, **kwargs)
