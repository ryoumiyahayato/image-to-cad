"""Whole-object adoption of original paths passing through text source ink.

Text and line evidence may overlap.  That permission does not assign a whole
connected ink component to either owner, nor permit deleting an old entity's
unproved remainder.  This stage never chooses a transcription.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

from .connection_adoption import _line_source_coverage
from .completion_stages import (
    _connection_path_responsibility,
    _existing_arc_overlap,
    _existing_line_members,
    _quarantine_native_duplicate_groups,
    _source_edges,
)
from .connections import (
    POLICY as PATH_POLICY,
    _dense_geometry,
    _retirement_proposals,
    _support,
)
from .contracts import TOLERANCES, save_json, stable_id


FIELD = "text_contact_path"
SCHEMA = "source-text-contact-adoption-v1"
EVIDENCE_SCHEMA = "source-text-contact-native-path-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def object_binding(obj):
    """The edit contract of an existing object, independent of report prose."""
    return {key: deepcopy(obj[key]) for key in ("id", "kind", "layer", "geometry")}


def path_geometry(obj):
    """Represent native LINE/ARC/path without changing any native geometry."""
    geometry, kind = obj["geometry"], obj["kind"]
    if kind == "CONNECTION_PATH":
        return deepcopy(geometry)
    if kind == "LINE":
        return {
            "points": [geometry["start"], geometry["end"]],
            "bulges": [0.0, 0.0],
            "closed": False,
        }
    if kind == "ARC":
        start = float(geometry["start_deg_image"])
        sweep = float(
            geometry.get("sweep_deg_image", geometry["end_deg_image"] - start)
        )
        angles = np.deg2rad([start, start + sweep])
        points = np.asarray(geometry["center"], float) + float(
            geometry["radius_px"]
        ) * np.column_stack((np.cos(angles), np.sin(angles)))
        return {
            "points": points.tolist(),
            "bulges": [math.tan(math.radians(sweep) / 4), 0.0],
            "closed": False,
        }
    raise ValueError("CONTACT_PATH_REQUIRES_LINE_ARC_OR_CONNECTION_PATH")


def _native_object(representation):
    points, bulges = representation["points"], representation["bulges"]
    if len(points) != 2:
        return "CONNECTION_PATH", deepcopy(representation)
    a, b = np.asarray(points[0], float), np.asarray(points[1], float)
    bulge = float(bulges[0])
    if bulge == 0:
        return "LINE", {"start": a.tolist(), "end": b.tolist()}
    chord = float(np.linalg.norm(b - a))
    normal = np.array([-(b - a)[1], (b - a)[0]]) / chord
    centre = (a + b) / 2 + normal * chord * (1 - bulge * bulge) / (4 * bulge)
    start = math.degrees(math.atan2(*(a - centre)[::-1]))
    sweep = math.degrees(4 * math.atan(bulge))
    return "ARC", {
        "center": centre.tolist(),
        "radius_px": float(np.linalg.norm(a - centre)),
        "start_deg_image": start,
        "end_deg_image": start + sweep,
        "sweep_deg_image": sweep,
    }


def _as_path(obj):
    result = deepcopy(obj)
    result.update(kind="CONNECTION_PATH", geometry=path_geometry(obj))
    return result


def _plan_source_checks(gray, roi, plan, prior_objects=None):
    from . import text_contact_geometry
    from .text_contact_geometry import POLICY, SCHEMA as PLAN_SCHEMA

    producer = text_contact_geometry
    structural = plan.get("schema") == "source-structure-contact-path-plan-v1"
    if structural:
        from . import structure_contact_geometry

        producer = structure_contact_geometry
        POLICY, PLAN_SCHEMA = producer.POLICY, producer.SCHEMA
    checks = {
        "schema_matches": plan.get("schema") == PLAN_SCHEMA,
        "current_geometry_policy": plan.get("policy") == POLICY,
        "same_geometry_producer": plan.get("producer_sha256")
        == hashlib.sha256(
            Path(producer.__file__).read_bytes()
        ).hexdigest(),
        "unchanged_connection_source_policy": plan.get(
            "unchanged_connection_source_policy"
        )
        == PATH_POLICY,
        "same_roi": plan.get("roi_xyxy_px") == list(roi),
        "source_not_modified": plan.get("original_source_pixels_modified") is False,
        "no_transcription_supplied": plan.get("transcription_supplied") is False,
    }
    if structural:
        bindings = plan.get("prior_object_bindings")
        try:
            checks["receiving_context_bound_to_existing_objects"] = (
                isinstance(bindings, list)
                and prior_objects is not None
                and sorted(bindings, key=lambda row: row["id"])
                == sorted(
                    (object_binding(obj) for obj in prior_objects),
                    key=lambda row: row["id"],
                )
            )
        except (KeyError, TypeError):
            checks["receiving_context_bound_to_existing_objects"] = False
        checks["starting_circle_sources_bound_to_existing_objects"] = (
            prior_objects is not None
            and plan.get("prior_circle_source_bindings")
            == producer.circle_source_bindings(prior_objects)
        )
    try:
        x0, y0, x1, y1 = plan["original_source_crop_xyxy_px"]
        checks["source_crop_bounds_valid"] = (
            all(isinstance(v, int) for v in (x0, y0, x1, y1))
            and 0 <= x0 < x1 <= gray.shape[1]
            and 0 <= y0 < y1 <= gray.shape[0]
        )
        checks["original_source_array_sha256_matches"] = (
            checks["source_crop_bounds_valid"]
            and hashlib.sha256(
                np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()
            ).hexdigest()
            == plan["original_source_crop_array_sha256"]
        )
    except (KeyError, TypeError, ValueError):
        checks["original_source_array_sha256_matches"] = False
    return {"pass": all(checks.values()), "checks": checks}


def _path_source_checks(gray, plan, path):
    from .text_contact_geometry import POLICY as CONTACT_POLICY

    checks = {}
    try:
        points = np.asarray(path["source_path_px"], float)
        checks["ordered_original_pixel_path"] = bool(
            points.ndim == 2
            and points.shape[1] == 2
            and len(points) >= 2
            and np.isfinite(points).all()
            and np.array_equal(points, np.rint(points))
        )
        if not checks["ordered_original_pixel_path"]:
            raise ValueError("SOURCE_PATH_MUST_USE_ORIGINAL_PIXEL_CENTRES")
        integer = points.astype(int)
        checks["source_points_in_original_image"] = bool(
            np.all(integer >= 0)
            and np.all(integer[:, 0] < gray.shape[1])
            and np.all(integer[:, 1] < gray.shape[0])
        )
        if not checks["source_points_in_original_image"]:
            raise ValueError("SOURCE_PATH_OUTSIDE_ORIGINAL_IMAGE")
        checks["every_source_point_is_original_ink"] = bool(
            np.all(gray[integer[:, 1], integer[:, 0]] < PATH_POLICY["source_threshold"])
        )
        steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
        checks["no_source_gap_bridged"] = bool(
            np.all(steps > 0) and np.max(steps) <= math.sqrt(2) + 1e-9
        )
        terminal_kinds = {
            "OBSERVED_FREE_SOURCE_ENDPOINT", "OBSERVED_ROUND_BOUNDARY_CONTACT"
        }
        structural = (
            plan.get("schema") == "source-structure-contact-path-plan-v1"
            or plan.get(FIELD, {}).get("geometry_plan_schema")
            == "source-structure-contact-path-plan-v1"
        )
        if structural:
            terminal_kinds |= {
                "OBSERVED_SUPPORTED_LINE_CONTACT", "OBSERVED_SOURCE_CARRIER_CORNER"
            }
        checks["two_real_source_terminals"] = len(
            path["endpoint_evidence"]
        ) == 2 and all(
            terminal.get("kind") in terminal_kinds
            for terminal in path["endpoint_evidence"]
        )
        if structural:
            kinds = [item.get("kind") for item in path["endpoint_evidence"]]
            role = path.get("path_role")
            checks["structural_path_has_explicit_independent_role"] = (
                role == "ROUND_TO_CARRIER"
                and sorted(kinds) == sorted([
                    "OBSERVED_ROUND_BOUNDARY_CONTACT", "OBSERVED_SUPPORTED_LINE_CONTACT"
                ])
                and isinstance(path.get("required_carrier_id"), str)
                and isinstance(path.get("required_start_circle_id"), str)
                and bool(path.get("starting_circle_evidence"))
                and bool(path.get("structural_terminal_evidence"))
            ) or (
                role == "SUPPORTING_CARRIER"
                and kinds == ["OBSERVED_SOURCE_CARRIER_CORNER"] * 2
                and bool(path.get("structural_carrier_evidence"))
            )
        checks["terminal_coordinates_match_complete_path"] = path[
            "endpoint_source_points_px"
        ] == [points[0].tolist(), points[-1].tolist()]
        checks["source_branches_retained"] = (
            path.get("original_branches_retained") is True
        )
        checks["text_decision_not_claimed"] = (
            path.get("text_content_decision") == "NOT_PERFORMED"
        )
        geometry = path["representation"]
        vertices, bulges = (
            np.asarray(geometry["points"], float),
            np.asarray(geometry["bulges"], float),
        )
        checks["valid_open_native_path"] = bool(
            geometry.get("closed") is False
            and vertices.ndim == 2
            and vertices.shape[1] == 2
            and 2 <= len(vertices) <= CONTACT_POLICY["maximum_control_vertices"]
            and bulges.shape == (len(vertices),)
            and np.isfinite(vertices).all()
            and np.isfinite(bulges).all()
            and bulges[-1] == 0
        )
        if not checks["valid_open_native_path"]:
            raise ValueError("INVALID_CONTACT_NATIVE_PATH")
        if structural:
            # Original walks keep integer source pixels.  A fitted receiving
            # LINE can meet that walk at a subpixel intersection inside the
            # same observed terminal core.  This separate representation is
            # licensed only by the replayed structural plan and black cells.
            from .circle_endpoint_contacts import _segment_cells

            endpoints = np.asarray(path["native_endpoint_points_px"], float)
            checks["native_endpoints_match_proved_terminal_representations"] = bool(
                endpoints.shape == (2, 2)
                and np.isfinite(endpoints).all()
                and np.allclose(vertices[[0, -1]], endpoints, atol=1e-7, rtol=0)
            )
            adjustments = path.get("endpoint_representation_adjustments", [])
            by_end = {item["end"]: item for item in adjustments}
            adjusted = {
                end for end in (0, 1)
                if not np.array_equal(points[[0, -1]][end], endpoints[end])
            }
            certificates_pass = (
                len(by_end) == len(adjustments)
                and adjusted <= set(by_end) <= {0, 1}
                and checks["native_endpoints_match_proved_terminal_representations"]
            )
            for end, declaration in by_end.items():
                old, new = points[[0, -1]][end], endpoints[end]
                cells = np.asarray(declaration["closed_source_pixel_cells"])
                cells_valid = bool(
                    cells.ndim == 2 and cells.shape[1] == 2 and len(cells)
                    and np.isfinite(cells).all()
                    and np.array_equal(cells, np.rint(cells))
                    and np.all(cells >= 0)
                    and np.all(cells[:, 0] < gray.shape[1])
                    and np.all(cells[:, 1] < gray.shape[0])
                )
                certificates_pass &= (
                    declaration["original_source_endpoint_px"] == old.tolist()
                    and declaration["native_endpoint_px"] == new.tolist()
                    and declaration.get("all_original_ink") is True
                    and cells_valid
                )
                if cells_valid:
                    integer_cells = cells.astype(int)
                    certificates_pass &= bool(
                        np.all(gray[integer_cells[:, 1], integer_cells[:, 0]]
                               < PATH_POLICY["source_threshold"])
                        and set(map(tuple, _segment_cells(old, new)))
                        <= set(map(tuple, integer_cells))
                    )
            checks["terminal_representation_adjustments_have_original_ink"] = bool(
                certificates_pass
            )
        else:
            checks["native_endpoints_are_original_terminals"] = bool(
                np.allclose(vertices[[0, -1]], points[[0, -1]], atol=1e-7, rtol=0)
            )
        x0, y0, x1, y1 = plan["original_source_crop_xyxy_px"]
        distance = distance_transform_edt(
            gray[y0:y1, x0:x1] >= PATH_POLICY["source_threshold"]
        )
        support = _support(_dense_geometry(geometry), distance, (x0, y0))
        checks["actual_native_path_has_original_source_support"] = support["pass"]
        return {
            "pass": all(checks.values()),
            "checks": checks,
            "actual_source_support": support,
        }
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        return {
            "pass": False,
            "checks": checks,
            "failure": type(exc).__name__ + ": " + str(exc),
        }


def _existing_line_covers(gray, proposal, old):
    """A retained old long line may cover a discovered source subpath fully."""
    points = np.asarray(proposal["source_evidence"]["source_path_points"], float)
    a, b = (
        np.asarray(old["geometry"]["start"], float),
        np.asarray(old["geometry"]["end"], float),
    )
    axis, length = b - a, float(np.linalg.norm(b - a))
    if length <= 0:
        return False
    axis /= length
    projection = (points - a) @ axis
    normal = np.abs((points[:, 0] - a[0]) * axis[1] - (points[:, 1] - a[1]) * axis[0])
    # The old line is not shortened to the graph endpoint.  Retaining it also
    # preserves source-supported portions outside the localized text context.
    geometrically_covered = bool(
        normal.max() <= TOLERANCES["line_perpendicular_px"]
        and projection.min() >= -TOLERANCES["line_endpoint_px"]
        and projection.max() <= length + TOLERANCES["line_endpoint_px"]
    )
    if not geometrically_covered:
        return False
    projected = a + np.clip(projection, 0, length)[:, None] * axis
    x0, y0 = np.maximum(
        0,
        np.floor(np.minimum(points.min(axis=0), projected.min(axis=0)) - 4).astype(int),
    )
    x1, y1 = np.minimum(
        [gray.shape[1], gray.shape[0]],
        np.ceil(np.maximum(points.max(axis=0), projected.max(axis=0)) + 5).astype(int),
    )
    ink = gray[y0:y1, x0:x1] < PATH_POLICY["source_threshold"]
    _, indices = distance_transform_edt(~ink, return_indices=True)
    rounded = np.rint(projected - [x0, y0]).astype(int)
    if (
        np.any(rounded < 0)
        or np.any(rounded[:, 0] >= ink.shape[1])
        or np.any(rounded[:, 1] >= ink.shape[0])
    ):
        return False
    closest = np.column_stack(
        (
            indices[1, rounded[:, 1], rounded[:, 0]] + x0,
            indices[0, rounded[:, 1], rounded[:, 0]] + y0,
        )
    )
    # Geometric tolerance must not suppress a second thin line across a real
    # white gap.  Retain only if the old line addresses this source stroke.
    return bool(cKDTree(points).query(closest)[0].max() <= 1.0)


def whole_old_line_responsibility(gray, proposal, old):
    """Prove an entire old LINE on this route, without component ownership."""
    result = {
        "prior_object_id": old["id"],
        "pass": False,
        "checks": {},
        "source_component_exclusivity_required": False,
        "partial_entity_retirement_permitted": False,
    }
    if old.get("kind") != "LINE":
        result["failure"] = "ONLY_WHOLE_TOP_LEVEL_LINE_RETIREMENT_IS_SUPPORTED"
        return result
    geometry = path_geometry(proposal)
    dense = _dense_geometry(geometry)
    a, b = (
        np.asarray(old["geometry"]["start"], float),
        np.asarray(old["geometry"]["end"], float),
    )
    length = float(np.linalg.norm(b - a))
    if length <= 0:
        result["failure"] = "OLD_LINE_HAS_NO_FINITE_LENGTH"
        return result
    samples = np.linspace(a, b, max(2, int(math.ceil(length / 0.25)) + 1))
    distances, nearest = cKDTree(dense).query(samples)
    tangent = np.gradient(dense, axis=0)
    norms = np.linalg.norm(tangent, axis=1)
    alignment = np.abs(
        (tangent[nearest] / np.maximum(norms[nearest, None], 1e-12))
        @ ((b - a) / length)
    )
    checks = result["checks"]
    checks["entire_old_line_within_route"] = bool(
        distances.max() <= PATH_POLICY["prior_fragment_normal_px"]
    )
    checks["entire_old_line_has_same_direction"] = bool(
        np.all(
            alignment >= math.cos(math.radians(PATH_POLICY["prior_fragment_angle_deg"]))
        )
    )
    x0, y0 = np.maximum(0, np.floor(samples.min(axis=0) - 4).astype(int))
    x1, y1 = np.minimum(
        [gray.shape[1], gray.shape[0]], np.ceil(samples.max(axis=0) + 5).astype(int)
    )
    ink = gray[y0:y1, x0:x1] < PATH_POLICY["source_threshold"]
    distance, indices = distance_transform_edt(~ink, return_indices=True)
    checks["old_line_original_source_support"] = _support(samples, distance, (x0, y0))[
        "pass"
    ]
    # A nearby parallel stroke separated by real white pixels is not the same
    # source.  Each nearest original ink pixel must also lie on this route's
    # source stroke; no ink-component label grants deletion authority.
    rounded = np.rint(samples - [x0, y0]).astype(int)
    valid = (
        (rounded[:, 0] >= 0)
        & (rounded[:, 0] < ink.shape[1])
        & (rounded[:, 1] >= 0)
        & (rounded[:, 1] < ink.shape[0])
    )
    if valid.all():
        closest = np.column_stack(
            (
                indices[1, rounded[:, 1], rounded[:, 0]] + x0,
                indices[0, rounded[:, 1], rounded[:, 0]] + y0,
            )
        )
        source = np.asarray(proposal["source_evidence"]["source_path_points"], float)
        source_distances = cKDTree(source).query(closest)[0]
        checks["nearest_original_ink_belongs_to_route"] = bool(
            source_distances.max() <= 1.0
        )
    else:
        checks["nearest_original_ink_belongs_to_route"] = False
    result.update(
        maximum_old_to_route_distance_px=float(distances.max()),
        minimum_direction_alignment=float(alignment.min()),
        old_line_coverage=_line_source_coverage(proposal, old),
        old_line_remaining_intervals=[]
        if all(checks.values())
        else "UNPROVED_REMAINDER_RETAINED",
    )
    result["pass"] = all(checks.values())
    return result


def shared_existing_line_contact(gray, proposal, old, overlap):
    """Rebuild a bounded four-port source core without reassigning either line.

    Two real paths may use the same small raster core while their native
    curves intersect normally.  Positive coincident native spans still have
    to pass the independent duplicate gate: this proof grants no exemption.
    """
    from .connections import _SourceGraph, _thinning
    from .text_graph_support import four_port_source_core_proof

    result = {
        "schema": "text-contact-existing-line-shared-core-v1",
        "pass": False,
        "prior_object_id": old["id"],
        "old_geometry_sha256": digest(old["geometry"]),
        "overlap": deepcopy(overlap),
        "native_duplicates_authorized": False,
        "old_object_retirement_authorized": False,
        "source_pixels_modified": False,
        "cores": [],
    }
    if old.get("kind") != "LINE":
        return result
    a, b = (
        np.asarray(old["geometry"]["start"], float),
        np.asarray(old["geometry"]["end"], float),
    )
    axis = (b - a) / max(float(np.linalg.norm(b - a)), 1e-12)
    route_edges = _source_edges(proposal)
    intervals = overlap.get("retire_intervals_px", [])
    if not intervals:
        return result
    for low, high in intervals:
        ends = a + np.asarray([low, high])[:, None] * axis
        margin = PATH_POLICY["context_px"]
        lower = np.maximum(0, np.floor(ends.min(axis=0)).astype(int) - margin)
        upper = np.minimum(
            [gray.shape[1], gray.shape[0]],
            np.ceil(ends.max(axis=0)).astype(int) + margin + 1,
        )
        x0, y0 = map(int, lower)
        x1, y1 = map(int, upper)
        # A long same-direction overlap is an ownership conflict, not a local
        # source intersection, and must never become a large search crop.
        if max(x1 - x0, y1 - y0) > 2 * margin + 16:
            return result
        ink = gray[y0:y1, x0:x1] < PATH_POLICY["source_threshold"]
        started = time.process_time()
        skeleton, _ = _thinning(ink, started)
        graph = _SourceGraph(
            skeleton, [x0, y0], [], [x0, y0, x1, y1], started, source_ink=ink
        )
        found = []
        for node in graph.nodes.values():
            if len(node.get("pairing", {})) != 4:
                continue
            core = four_port_source_core_proof(graph, node)
            if core is None:
                continue
            core_points = np.asarray(core["source_core_points"], float)
            samples = np.linspace(
                ends[0], ends[1], max(2, int(math.ceil(high - low) / 0.25) + 1)
            )
            if (
                float(cKDTree(core_points).query(samples)[0].max())
                > TOLERANCES["line_perpendicular_px"]
            ):
                continue
            selected = [
                port
                for port in node["edges"]
                if tuple(
                    sorted(map(tuple, graph.xy(graph.oriented(port)[:2]).tolist()))
                )
                in route_edges
            ]
            if len(selected) != 2 or node["pairing"].get(selected[0]) != selected[1]:
                continue
            other = [port for port in node["edges"] if port not in selected]
            if len(other) != 2 or node["pairing"].get(other[0]) != other[1]:
                continue
            observed = [graph.xy(graph.oriented(port)[:14]).tolist() for port in other]
            if any(len(points) < 8 for points in observed):
                continue
            if not all(
                _existing_line_covers(
                    gray, {"source_evidence": {"source_path_points": points}}, old
                )
                for points in observed
            ):
                continue
            found.append(
                {
                    "source_core_proof": core,
                    "candidate_ports": [list(port) for port in selected],
                    "retained_old_line_ports": [list(port) for port in other],
                    "retained_old_line_original_tangents": observed,
                    "original_crop_xyxy_px": [x0, y0, x1, y1],
                    "original_crop_array_sha256": hashlib.sha256(
                        np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()
                    ).hexdigest(),
                    "covered_old_parameter_interval_px": [low, high],
                }
            )
        if len(found) != 1:
            return result
        result["cores"].append(found[0])
    result["pass"] = True
    return result


def _circle_overlaps(proposal, objects):
    arcs = []
    for old in objects:
        geometry = old["geometry"]
        circle = (
            geometry
            if old["kind"] == "CIRCLE"
            else geometry.get("circle_geometry")
            if old["kind"] == "CIRCULAR_MARKER"
            else None
        )
        if circle is not None:
            arcs.append(
                {
                    "id": old["id"],
                    "kind": "ARC",
                    "geometry": {
                        **circle,
                        "start_deg_image": 0.0,
                        "end_deg_image": 360.0,
                        "sweep_deg_image": 360.0,
                    },
                }
            )
    return _existing_arc_overlap(proposal, arcs)


def complete_text_contact_paths(gray, roi, source_sha, objects, plans, out):
    """Return new native objects and explicit whole-object retirement receipts.

    ``out`` is the ordinary evidence root's ``text_contact`` directory.  The
    inputs are never mutated.  Complete geometry is useful even if the nearby
    text remains pending, and never increments the complete-label count.
    """
    source = np.asarray(gray)
    if source.ndim != 2:
        raise ValueError("TEXT_CONTACT_ADOPTION_REQUIRES_GRAYSCALE_SOURCE")
    prior = {obj["id"]: obj for obj in objects}
    if len(prior) != len(objects):
        raise ValueError("TEXT_CONTACT_DUPLICATE_PRIOR_ID")
    stored_plans, proposals, rejected = {}, [], []
    for plan in plans:
        plan_key = digest(plan)
        if plan_key in stored_plans:
            continue
        stored_plans[plan_key] = deepcopy(plan)
        plan_check = _plan_source_checks(source, roi, plan, objects)
        if not plan_check["pass"]:
            rejected.append(
                {
                    "plan_sha256": plan_key,
                    "adopted": False,
                    "decision": "PENDING_INVALID_SOURCE_PLAN",
                    "source_check": plan_check,
                }
            )
            continue
        for index, path in enumerate(plan.get("paths", [])):
            source_check = _path_source_checks(source, plan, path)
            if not source_check["pass"]:
                rejected.append(
                    {
                        "plan_sha256": plan_key,
                        "path_index": index,
                        "adopted": False,
                        "decision": "PENDING_INVALID_SOURCE_PATH",
                        "source_check": source_check,
                    }
                )
                continue
            geometry = deepcopy(path["representation"])
            obj = {
                "id": stable_id("CONTACT", geometry),
                "kind": "CONNECTION_PATH",
                "layer": "CONNECTIONS",
                "geometry": geometry,
                "source_evidence": {
                    "source_path_points": deepcopy(path["source_path_px"]),
                    # Graph-local integers remain inside the independently
                    # replayed contact plan.  They are not IDs in the legacy
                    # connection discovery graph's namespace.
                    "original_source_crop_xyxy_px": plan[
                        "original_source_crop_xyxy_px"
                    ],
                    "original_source_crop_array_sha256": plan[
                        "original_source_crop_array_sha256"
                    ],
                    "source_pixels_modified": False,
                    FIELD: {
                        "schema": EVIDENCE_SCHEMA,
                        "source_sha256": source_sha,
                        "plan_sha256": plan_key,
                        "path_index": index,
                        "path_sha256": digest(path),
                        "path": deepcopy(path),
                    },
                },
                "editing_scope": "one complete independent observed line; text and endpoint symbols remain separate",
                "status": "SOURCE_SUPPORTED_COMPLETE_TEXT_CONTACT_PATH",
            }
            if plan.get("schema") == "source-structure-contact-path-plan-v1":
                obj["source_evidence"][FIELD]["geometry_plan_schema"] = plan["schema"]
            proposals.append(obj)
    # A newly proved receiving line remains a separate entity.  Adopt it
    # before its dependent round-to-line path; a rejected receiving object
    # cannot turn into a fictitious saved terminal merely by being proposed.
    proposals.sort(key=lambda obj: (
        obj["source_evidence"][FIELD]["path"].get("path_role") != "SUPPORTING_CARRIER"
    ))
    # This established finite-segment refusal gate also sees all old paths.
    # It grants no exemption merely because text-contact evidence exists.
    prior_members = _existing_line_members(objects)
    adequate_before_quarantine = {
        obj["id"]
        for obj in proposals
        if any(_existing_line_covers(source, obj, old) for old in prior_members)
    }
    # A candidate already represented by an unchanged LINE is never written;
    # it cannot quarantine another candidate merely by its unused encoding.
    # Old LINE overlap remains subject to whole retirement or a proved local
    # source contact below; the exact native gate is applied to retained ones.
    quarantine_prior = [
        _as_path(obj) if obj["kind"] == "ARC" else obj for obj in objects
    ]
    quarantine = _quarantine_native_duplicate_groups(
        [obj for obj in proposals if obj["id"] not in adequate_before_quarantine],
        quarantine_prior,
    )
    quarantined = set(quarantine["quarantined_ids"])
    adopted, internal_adopted, decisions, retired = [], [], list(rejected), set()
    for proposal in proposals:
        row = {
            "id": proposal["id"],
            "adopted": False,
            "reasons": [],
            "retired_ids": [],
            "plan_sha256": proposal["source_evidence"][FIELD]["plan_sha256"],
            "path_index": proposal["source_evidence"][FIELD]["path_index"],
            "existing_adequate_ids": [],
            "whole_line_certificates": [],
            "shared_existing_line_contacts": [],
        }
        active = [obj for obj in objects if obj["id"] not in retired] + internal_adopted
        selected_path = proposal["source_evidence"][FIELD]["path"]
        if selected_path.get("path_role") == "ROUND_TO_CARRIER":
            start_id = selected_path["required_start_circle_id"]
            start = next((old for old in active if old["id"] == start_id), None)
            row["required_source_verified_start_circle_id"] = start_id
            row["source_verified_start_circle_present"] = (
                start is not None and start["kind"] in ("CIRCLE", "CIRCULAR_MARKER")
            )
            if not row["source_verified_start_circle_present"]:
                row["reasons"].append("SOURCE_VERIFIED_START_CIRCLE_NOT_PRESENT")
                row["decision"] = "PENDING_SOURCE_VERIFIED_START_CIRCLE"
                decisions.append(row)
                continue
            carrier_id = selected_path["required_carrier_id"]
            carrier = next((old for old in active if old["id"] == carrier_id), None)
            row["required_independent_receiving_object_id"] = carrier_id
            row["independent_receiving_object_present"] = carrier is not None
            if carrier is None:
                row["reasons"].append("INDEPENDENT_RECEIVING_OBJECT_NOT_ADOPTED")
                row["decision"] = "PENDING_INDEPENDENT_RECEIVING_OBJECT"
                decisions.append(row)
                continue
        responsibility_active = []
        for old in active:
            if old["id"] == proposal["id"] and old["kind"] != "CONNECTION_PATH":
                kind, geometry = _native_object(proposal["geometry"])
                if old["kind"] != kind or old["geometry"] != geometry:
                    raise ValueError("CONTACT_PATH_ID_GEOMETRY_COLLISION")
                old = {
                    **old,
                    "kind": "CONNECTION_PATH",
                    "geometry": proposal["geometry"],
                }
            responsibility_active.append(old)
        row.update(
            _connection_path_responsibility(source, proposal, responsibility_active)
        )
        members = _existing_line_members(active)
        # Test adequacy before overlap/replacement.  A source-supported old
        # long LINE is not replaced by a noisy shorter graph subpath.
        row["existing_adequate_ids"].extend(
            old["id"] for old in members if _existing_line_covers(source, proposal, old)
        )
        dense = _dense_geometry(proposal["geometry"])
        for old in active:
            if old["kind"] == "ARC":
                other = _dense_geometry(path_geometry(old))
                if (
                    max(
                        float(cKDTree(dense).query(other)[0].max()),
                        float(cKDTree(other).query(dense)[0].max()),
                    )
                    <= PATH_POLICY["polyline_approximation_px"]
                ):
                    row["existing_adequate_ids"].append(old["id"])
        if row["existing_adequate_ids"]:
            row["existing_adequate_ids"] = sorted(set(row["existing_adequate_ids"]))
            if row["reasons"]:
                row["unused_proposal_responsibility_reasons"] = row["reasons"]
                row["reasons"] = []
            row["decision"] = "RETAIN_EXISTING_COMPLETE_GEOMETRY_NO_DUPLICATE"
            decisions.append(row)
            continue
        if proposal["id"] in quarantined:
            row["reasons"].append("SOURCE_GROUP_HAS_DUPLICATE_NATIVE_SEGMENTS")
        overlap, neighbors = _retirement_proposals(proposal["geometry"], members)
        row["parallel_overlap_records"], row["unchanged_crossing_neighbors"] = (
            overlap,
            neighbors,
        )
        replacing = []
        for conflict in overlap:
            oid = conflict["prior_object_id"]
            old = prior.get(oid)
            if old is None or old["kind"] != "LINE":
                row["reasons"].append(
                    "EXISTING_BLOCK_MEMBER_OR_NONLINE_RESPONSIBILITY_PENDING"
                )
                continue
            shared = shared_existing_line_contact(source, proposal, old, conflict)
            if shared["pass"]:
                row["shared_existing_line_contacts"].append(shared)
                exact = _quarantine_native_duplicate_groups([proposal], [_as_path(old)])
                if exact["quarantined_ids"]:
                    row["reasons"].append(
                        "SHARED_SOURCE_CORE_DOES_NOT_AUTHORIZE_NATIVE_DUPLICATES"
                    )
                continue
            proof = whole_old_line_responsibility(source, proposal, old)
            row["whole_line_certificates"].append(proof)
            if proof["pass"]:
                replacing.append(oid)
            else:
                row["reasons"].append("WHOLE_OLD_LINE_RESPONSIBILITY_NOT_CERTIFIED")
        arc_overlap = _existing_arc_overlap(proposal, active) + _circle_overlaps(
            proposal, active
        )
        row["arc_overlap_records"] = arc_overlap
        if arc_overlap:
            row["reasons"].append("EXISTING_NATIVE_CURVE_RESPONSIBILITY_PENDING")
        if row["reasons"]:
            row["decision"] = "PENDING_WHOLE_OBJECT_RESPONSIBILITY"
        else:
            obj = deepcopy(proposal)
            obj["kind"], obj["geometry"] = _native_object(proposal["geometry"])
            row.update(
                adopted=True,
                retired_ids=sorted(set(replacing)),
                native_kind=obj["kind"],
                decision="REPLACE_PROVED_WHOLE_LINES"
                if replacing
                else "ADD_COMPLETE_INDEPENDENT_GEOMETRY",
            )
            obj["source_evidence"]["text_contact_responsibility"] = deepcopy(row)
            adopted.append(obj)
            internal_adopted.append(proposal)
            retired.update(replacing)
        decisions.append(row)
    result = {
        "schema": SCHEMA,
        "source_sha256": source_sha,
        "roi_xyxy_px": list(roi),
        "objects": adopted,
        "retired_ids": sorted(retired),
        "decisions": decisions,
        "geometry_plans": stored_plans,
        "prior_object_bindings": [object_binding(obj) for obj in objects],
        "uncertainties": [
            deepcopy(row) for row in decisions if row["decision"].startswith("PENDING_")
        ],
        "native_duplicate_group_quarantine": quarantine,
        "source_pixels_modified": False,
        "partial_old_entity_retirement_permitted": False,
        "text_content_decisions_performed": False,
        "new_complete_text_labels": 0,
    }
    save_json(Path(out) / "adoption.json", result)
    return result
