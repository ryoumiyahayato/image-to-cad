"""Source-bound completion stages with optional, explicitly attested replay.

Cache replay is only for already completed local experiments. Fresh user jobs
run the algorithms. Neither path can read fixed source-case answers.
"""

from pathlib import Path
import copy
import hashlib
import importlib
import json
import math
import numpy as np
from .contracts import plain, save_json


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=plain, allow_nan=False
        ).encode()
    ).hexdigest()


def text_context_sha(objects):
    rows = []
    for obj in objects:
        kind = obj["kind"]
        g = obj["geometry"]
        if kind == "ROOM_LABEL":
            kind = "TEXT"
            g = g["text_geometry"]
        if kind in ("TEXT", "MTEXT"):
            rows.append({"id": obj["id"], "kind": kind, "geometry": g})
    return canonical_sha(sorted(rows, key=lambda r: r["id"]))


def _check_completion_dependencies(stage, payload):
    """A source proposal also depends on its finite local route implementation.

    The job fingerprint covers every native module. An explicitly imported
    stage has its own identity too; checking only connections.py would allow a
    changed helper to reuse an old route selection. Missing attestations fail
    closed, including historical payloads that predate the helper.
    """
    if stage != "connections":
        return
    from . import (
        connection_core_routes, text_graph_support, checkpoint_text_observations,
        source_endpoint_caps,
    )

    expected = {
        module.__name__: hashlib.sha256(
            Path(module.__file__).read_bytes()
        ).hexdigest()
        for module in (
            connection_core_routes, text_graph_support, checkpoint_text_observations,
            source_endpoint_caps,
        )
    }
    discovery = payload.get("discovery", {})
    if discovery.get("dependency_producers") != expected:
        raise ValueError("CONNECTION_ROUTE_DEPENDENCY_CHANGED_OR_MISSING")


def restore_connection_discovery_evidence(
    cache_dir, out, gray, *, discovery=None, binding=None, objects=()
):
    """Restore the immutable raw graph needed by a new cold retrace audit.

    Completed assembly checkpoints bind both files explicitly. Proposal
    replay instead supplies its already hash-verified discovery payload.
    Neither imports a prior cold audit or approves a traversal. ``out=None``
    verifies the published evidence without changing the original job.
    """
    candidates = discovery.get("objects", []) if discovery is not None else objects
    required = any(
        crossing.get("local_cycle_cover_evidence")
        for obj in candidates
        for crossing in obj.get("source_evidence", {}).get("crossing_evidence", [])
    )
    if not required and binding is None:
        return None
    if cache_dir is None or (discovery is None and binding is None):
        raise ValueError("CONNECTION_RETRACE_RAW_EVIDENCE_BINDING_MISSING")
    root = Path(cache_dir).resolve()
    relative_names = (
        "connections/discovery/connections.json",
        "connections/discovery/source_graph.json",
    )
    contents = {}
    for name in relative_names:
        path = root / name
        if (
            path.is_symlink()
            or root not in path.resolve().parents
            or not path.is_file()
        ):
            raise ValueError(
                "CONNECTION_RETRACE_RAW_EVIDENCE_MISSING_OR_OUTSIDE:" + name
            )
        contents[name] = path.read_bytes()
    recorded = json.loads(contents[relative_names[0]])
    if discovery is not None and canonical_sha(recorded) != canonical_sha(discovery):
        raise ValueError("CONNECTION_RETRACE_DISCOVERY_PAYLOAD_CHANGED")
    _check_completion_dependencies("connections", {"discovery": recorded})
    graph_bytes = contents[relative_names[1]]
    graph_ref = recorded.get("source_graph", {})
    if (
        graph_ref.get("path") != "source_graph.json"
        or graph_ref.get("sha256") != hashlib.sha256(graph_bytes).hexdigest()
    ):
        raise ValueError("CONNECTION_RETRACE_RAW_GRAPH_HASH_CHANGED")
    graph = json.loads(graph_bytes)
    bounds = graph.get("source_crop_xyxy_px", [])
    if (
        graph.get("schema") != "unmodified_source_graph_v2"
        or len(bounds) != 4
        or any(not isinstance(v, int) or isinstance(v, bool) for v in bounds)
    ):
        raise ValueError("CONNECTION_RETRACE_RAW_GRAPH_SOURCE_CROP_INVALID")
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0]):
        raise ValueError("CONNECTION_RETRACE_RAW_GRAPH_SOURCE_CROP_INVALID")
    crop_sha = hashlib.sha256(
        np.ascontiguousarray(gray[y0:y1, x0:x1]).tobytes()
    ).hexdigest()
    if crop_sha != graph.get("source_crop_array_sha256"):
        raise ValueError("CONNECTION_RETRACE_RAW_GRAPH_CURRENT_SOURCE_CHANGED")
    actual = {
        "schema": "connection-discovery-evidence-v1",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in contents.items()
        },
        "source_crop_xyxy_px": bounds,
        "source_crop_array_sha256": crop_sha,
        "prior_cold_audit_imported": False,
        "current_saved_retrace_certification_required": True,
    }
    if binding is not None and binding != actual:
        raise ValueError("CONNECTION_RETRACE_RAW_EVIDENCE_BINDING_CHANGED")
    if out is not None:
        destination = Path(out).resolve()
        for name, data in contents.items():
            target = destination / "discovery" / Path(name).name
            if target.is_symlink() or destination not in target.resolve().parents:
                raise ValueError("CONNECTION_RETRACE_RESTORED_PATH_OUTSIDE_EVIDENCE")
            if target.exists() and target.read_bytes() != data:
                raise ValueError("CONNECTION_RETRACE_RESTORED_EVIDENCE_ALREADY_DIFFERS")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    return actual


def _load(cache_dir, stage, gray, roi, source_sha, out, *, text_sha=None):
    manifest = Path(cache_dir) / "native_completion_stages.json" if cache_dir else None
    if manifest is None or not manifest.is_file():
        return None, None
    data = json.loads(manifest.read_text())
    row = data.get("stages", {}).get(stage)
    if row is None:
        return None, None
    actual = {
        "source_sha256": source_sha,
        "source_array_sha256": hashlib.sha256(
            np.ascontiguousarray(gray).tobytes()
        ).hexdigest(),
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "roi_xyxy_px": list(roi),
    }
    if any(data.get(k) != v for k, v in actual.items()):
        raise ValueError("NATIVE_COMPLETION_CACHE_SOURCE_MISMATCH:" + stage)
    if text_sha is not None and row.get("text_context_sha256") != text_sha:
        raise ValueError("NATIVE_COMPLETION_CACHE_TEXT_CONTEXT_MISMATCH:" + stage)
    base = manifest.parent.resolve()
    path = (base / row["path"]).resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError("NATIVE_COMPLETION_CACHE_PATH_INVALID")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError("NATIVE_COMPLETION_CACHE_PAYLOAD_CHANGED:" + stage)
    expected = {
        "connections": "app.native_objects.connections",
        "doors": "app.native_objects.door_completion",
    }[stage]
    if row.get("producer_module") != expected:
        raise ValueError("NATIVE_COMPLETION_CACHE_PRODUCER_NOT_ALLOWED")
    module = importlib.import_module(expected)
    if (
        hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        != row["producer_sha256"]
    ):
        raise ValueError("NATIVE_COMPLETION_CACHE_PRODUCER_CHANGED:" + stage)
    payload = json.loads(path.read_text())
    _check_completion_dependencies(stage, payload)
    evidence = {
        "cache_hit": True,
        "path": str(path),
        "sha256": row["sha256"],
        "producer_module": expected,
        "producer_sha256": row["producer_sha256"],
        "provenance": row.get("provenance"),
        "source_checks": actual,
        "old_fitting_repeated": False,
    }
    save_json(Path(out) / (stage + "_cache_replay.json"), evidence)
    return payload, evidence


def _revision_proposals(cache_dir, stage, gray, roi, source_sha, out):
    """Import verified proposals, never a previous text or edit decision."""
    filename = {
        "doors": "revision_door_completion_proposals.json",
        "connections": "revision_connection_proposals.json",
    }[stage]
    path = Path(cache_dir) / filename if cache_dir else None
    if path is None or not path.is_file():
        return None, None
    row = json.loads(path.read_text())
    expected_module = {
        "doors": "app.native_objects.door_completion",
        "connections": "app.native_objects.connections",
    }[stage]
    module = importlib.import_module(expected_module)
    expected = {
        "source_sha256": source_sha,
        "roi_xyxy_px": list(roi),
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "producer_module": expected_module,
        "producer_sha256": hashlib.sha256(
            Path(module.__file__).read_bytes()
        ).hexdigest(),
    }
    if any(row.get(k) != v for k, v in expected.items()):
        raise ValueError("REVISION_PROPOSAL_SOURCE_OR_PRODUCER_MISMATCH:" + stage)
    _check_completion_dependencies(stage, row)
    if (
        row.get("source_array_sha256")
        != hashlib.sha256(np.ascontiguousarray(gray).tobytes()).hexdigest()
    ):
        raise ValueError("REVISION_PROPOSAL_WORKING_BYTES_CHANGED:" + stage)
    evidence = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_and_unchanged_producer_rechecked": True,
        "old_fitting_repeated": False,
        "old_adoption_or_responsibility_reused": False,
        "old_text_context_sha256": row.get("old_text_context_sha256"),
        "current_responsibility_must_be_rechecked": True,
    }
    retained = Path(out) / filename
    retained.write_bytes(path.read_bytes())
    evidence["retained_proposal_evidence"] = filename
    evidence["retained_proposal_sha256"] = hashlib.sha256(
        retained.read_bytes()
    ).hexdigest()
    save_json(Path(out) / (stage + "_revision_proposals_replay.json"), evidence)
    return row, evidence


def complete_doors_with_responsibility(
    gray, roi, source_path, source_sha, line_data, retained, out, cache_dir=None
):
    from .door_completion import (
        complete_doors,
        retire_door_fragments,
        append_leaf_end_responsibility,
    )

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    revision, replay = _revision_proposals(
        cache_dir, "doors", gray, roi, source_sha, out
    )
    if revision is not None:
        payload = revision
    else:
        payload, replay = _load(cache_dir, "doors", gray, roi, source_sha, out)
    if payload is not None:
        raw = payload["raw_generation"]

        def retained_without_old_export_handles(rows):
            return [
                {k: v for k, v in o.items() if k not in ("handle_at_write", "export")}
                for o in rows
            ]

        if canonical_sha(
            retained_without_old_export_handles(raw["retained_objects"])
        ) != canonical_sha(retained_without_old_export_handles(retained)):
            raise ValueError("NATIVE_DOOR_REPLAY_RETAINED_OBJECTS_CHANGED")
        responsibility = payload.get("responsibility") if revision is None else None
    else:
        raw = complete_doors(
            gray, roi, line_data, retained, out / "generation", source_path=source_path
        )
        if raw.get("resource_stop"):
            from .execution import NativeResourceLimit

            raise NativeResourceLimit("NATIVE_DOOR_COMPLETION_RESOURCE_STOP")
        responsibility = None
    if responsibility is None:
        original_partition = retire_door_fragments(line_data["objects"], raw["objects"])
        save_json(out / "initial_responsibility_partition.json", original_partition)
        responsibility = append_leaf_end_responsibility(
            gray, roi, raw, line_data, original_partition, out / "responsibility"
        )
    save_json(
        out / "completion_result.json",
        {"raw_generation": raw, "responsibility": responsibility, "replay": replay},
    )
    return {
        "objects": copy.deepcopy(responsibility["adopted_objects"]),
        "uncertainties": [
            {"reason": "DOOR_EDIT_RESPONSIBILITY_PENDING", "object": o}
            for o in responsibility["pending_new_objects"]
        ],
        "raw_candidate_count": len(raw["new_objects"]),
        "new_adopted_count": len(responsibility["adopted_objects"]) - len(retained),
        "replay": replay,
        "responsibility_decisions": responsibility["responsibility_decisions"],
    }


def _existing_line_members(objects):
    from .door_completion import native_members

    rows = []
    for obj in objects:
        kind = obj["kind"]
        g = obj["geometry"]
        members = []
        if kind == "LINE":
            rows.append(obj)
            continue
        if kind == "WALL_SEGMENT":
            members = g["members"]
        elif kind == "DOOR":
            members = native_members(obj)
        elif kind == "ROOM_LABEL":
            pts = g["frame_points"]
            members = [
                {"kind": "LINE", "geometry": {"start": a, "end": b}}
                for a, b in zip(pts, pts[1:] + pts[:1])
            ]
            members += g.get("frame_source_remainders", [])
        for i, m in enumerate(members):
            if m["kind"] == "LINE":
                rows.append(
                    {
                        "id": obj["id"] + ":MEMBER:" + str(i),
                        "kind": "LINE",
                        "geometry": m["geometry"],
                    }
                )
    return rows


def _existing_arc_overlap(proposal, objects):
    """Conservatively reject coincidence with an already owned finite arc.

    Pure crossings have a different tangent and are not reassigned. This adds
    a refusal gate; it never authorizes a source erasure or changes geometry.
    """
    from .connections import _dense_geometry, POLICY
    from .door_completion import native_members
    from .contracts import TOLERANCES

    p = _dense_geometry(proposal["geometry"], 0.25)
    v = np.diff(p, axis=0)
    length = np.linalg.norm(v, axis=1)
    q = (p[:-1] + p[1:]) * 0.5
    direction = v / np.maximum(length[:, None], 1e-300)
    rows = []
    for obj in objects:
        if obj["kind"] == "ARC":
            arc_members = [obj]
        elif obj["kind"] == "DOOR":
            arc_members = native_members(obj)
        else:
            continue
        for i, member in enumerate(arc_members):
            if member["kind"] != "ARC":
                continue
            g = member["geometry"]
            c = np.asarray(g["center"], float)
            radius = float(g["radius_px"])
            start = math.radians(g["start_deg_image"])
            sweep = math.radians(g["sweep_deg_image"])
            radial = q - c
            norm = np.linalg.norm(radial, axis=1)
            tangent = np.column_stack((-radial[:, 1], radial[:, 0])) / np.maximum(
                norm[:, None], 1e-300
            )
            phase = (
                (np.arctan2(radial[:, 1], radial[:, 0]) - start)
                * math.copysign(1, sweep)
            ) % (2 * math.pi)
            mask = (np.abs(norm - radius) <= TOLERANCES["arc_radial_px"]) & (
                phase <= abs(sweep)
            )
            mask &= np.abs(np.sum(direction * tangent, axis=1)) >= math.cos(
                math.radians(POLICY["prior_fragment_angle_deg"])
            )
            coincident = float(length[mask].sum())
            if coincident >= POLICY["minimum_retired_interval_px"]:
                rows.append(
                    {
                        "existing_object_id": obj["id"],
                        "member_index": i,
                        "parallel_near_arc_length_px": coincident,
                        "decision": "PENDING_EXISTING_ARC_RESPONSIBILITY_NOT_REASSIGNED",
                    }
                )
    return rows



def _source_edges(obj):
    points = obj.get("source_evidence", {}).get("source_path_points", [])
    return {
        tuple(sorted((tuple(a), tuple(b))))
        for a, b in zip(points, points[1:])
        if a != b
    }



def _quarantine_native_duplicate_groups(proposals, prior_objects=()):
    """Reject an entire observed source group before any old entity retirement.

    This is a refusal gate for distinct paths with positive collinear finite
    overlap, including different segmentations and partial coincident spans.
    The tolerance is the existing seven-decimal source-coordinate precision.
    Equal whole-path rediscoveries remain the ordinary duplicate suppressor's
    responsibility. Same-owner source-certified local-cycle walks are untouched.
    """
    from scipy.spatial import cKDTree

    from .connections import POLICY, _dense_geometry

    paths = list(proposals)
    old_paths = [obj for obj in prior_objects if obj.get("kind") == "CONNECTION_PATH"]
    dense = {}

    def equivalent(a, b):
        if a["id"] == b["id"]:
            if a["kind"] != b["kind"] or a["geometry"] != b["geometry"]:
                raise ValueError("CONNECTION_PATH_ID_GEOMETRY_COLLISION")
            return True
        for obj in (a, b):
            if id(obj) not in dense:
                dense[id(obj)] = _dense_geometry(obj["geometry"])
        left, right = dense[id(a)], dense[id(b)]
        return max(float(cKDTree(left).query(right)[0].max()),
                   float(cKDTree(right).query(left)[0].max())) <= POLICY["polyline_approximation_px"]

    groups, membership = {}, {}
    for obj in paths:
        if obj.get("kind") != "CONNECTION_PATH":
            raise ValueError("CONNECTION_PATH_RESPONSIBILITY_REQUIRES_PATH")
        source = obj.get("source_evidence", {})
        scope = source.get("original_source_crop_xyxy_px")
        source_group = source.get("source_connected_group_id")
        key = ("source_graph", tuple(scope), source.get("original_source_crop_array_sha256"), source_group) \
            if scope is not None and source_group else ("one_path", obj["id"])
        groups.setdefault(key, set()).add(obj["id"])
        membership.setdefault(obj["id"], set()).add(key)
    adequate = {obj["id"] for obj in paths if any(equivalent(obj, old) for old in old_paths)}
    active = [(obj, True) for obj in paths if obj["id"] not in adequate]
    active += [(obj, False) for obj in old_paths]
    segments, conflicts, bad_groups = [], [], set()
    for obj, proposed in active:
        points = obj["geometry"]["points"]
        bulges = obj["geometry"]["bulges"]
        spans = list(zip(points, points[1:] + (points[:1] if obj["geometry"].get("closed") else [])))
        for index, (a, b) in enumerate(spans):
            if float(bulges[index]) != 0:
                continue  # Circular arcs retain their independent existing gates.
            a, b = np.asarray(a, float), np.asarray(b, float)
            if not np.all(np.isfinite([a, b])):
                raise ValueError("CONNECTION_NATIVE_SEGMENT_NONFINITE")
            if float(np.linalg.norm(b - a)) <= 1e-7:
                continue
            segments.append((float(min(a[0], b[0])), float(max(a[0], b[0])),
                             float(min(a[1], b[1])), float(max(a[1], b[1])),
                             obj, proposed, index, a, b))
    nearby = []
    for span in sorted(segments, key=lambda item: (item[0], item[2], item[4]["id"], item[6])):
        left, right, bottom, top, obj, proposed, index, a, b = span
        nearby = [old for old in nearby if old[1] >= left - 1e-7]
        for other_span in nearby:
            _, _, other_bottom, other_top, other, other_proposed, other_index, c, d = other_span
            if top < other_bottom - 1e-7 or other_top < bottom - 1e-7:
                continue
            if not (proposed or other_proposed):
                continue
            vector = b - a
            length = float(np.linalg.norm(vector))
            axis = vector / length
            delta = np.asarray([c - a, d - a])
            perpendicular = np.abs(delta[:, 0] * axis[1] - delta[:, 1] * axis[0])
            if float(perpendicular.max()) > 1e-7:
                continue  # A true point crossing is not coincident native length.
            low, high = sorted(float(point @ axis) for point in delta)
            start, end = max(0.0, low), min(length, high)
            if end - start > 1e-7:
                if equivalent(obj, other):
                    continue
                affected = [row["id"] for row, fresh in ((obj, proposed), (other, other_proposed)) if fresh]
                for oid in affected:
                    bad_groups.update(membership[oid])
                conflicts.append({"object_ids": [other["id"], obj["id"]],
                                  "native_segment_indices": [other_index, index],
                                  "source_pixel_endpoints": [(a + start * axis).tolist(),
                                                             (a + end * axis).tolist()],
                                  "positive_overlap_length_source_px": end - start,
                                  "finite_segment_intersection": True})
        nearby.append(span)
    # One object may have been discovered in overlapping graph namespaces.
    # Propagate only those exact identity links, not nearby source bounding boxes.
    while True:
        quarantined = set().union(*(groups[key] for key in bad_groups)) if bad_groups else set()
        linked = set().union(*(membership[oid] for oid in quarantined)) if quarantined else set()
        if linked <= bad_groups:
            break
        bad_groups.update(linked)
    return {"quarantined_ids": sorted(quarantined - adequate),
            "source_group_members": [sorted(groups[key]) for key in sorted(bad_groups, key=repr)],
            "native_duplicate_conflicts": conflicts,
            "before_old_entity_retirement": True,
            "existing_entities_modified": 0,
            "whole_path_duplicate_suppression_unchanged": True,
            "same_owner_retrace_permission_changed": False}


def _connection_path_responsibility(gray, proposal, existing):
    """One conservative path-ownership rule for ordinary and bounded entry."""
    from scipy.spatial import cKDTree

    from .connections import POLICY, _dense_geometry
    from .text_graph_support import prove_shared_core_overlap

    if proposal["kind"] != "CONNECTION_PATH":
        raise ValueError("CONNECTION_PATH_RESPONSIBILITY_REQUIRES_PATH")
    row = {"existing_adequate_ids": [], "shared_source_core_checks": [], "reasons": []}
    path = _dense_geometry(proposal["geometry"])
    edges = _source_edges(proposal)
    for old in existing:
        if old["id"] == proposal["id"]:
            if old["geometry"] != proposal["geometry"] or old["kind"] != proposal["kind"]:
                raise ValueError("CONNECTION_PATH_ID_GEOMETRY_COLLISION")
            row["existing_adequate_ids"].append(old["id"])
            continue
        if old["kind"] != "CONNECTION_PATH":
            continue
        other = _dense_geometry(old["geometry"])
        same = max(float(cKDTree(path).query(other)[0].max()),
                   float(cKDTree(other).query(path)[0].max())) <= POLICY["polyline_approximation_px"]
        if same:
            row["existing_adequate_ids"].append(old["id"])
        elif edges & _source_edges(old):
            shared = prove_shared_core_overlap(gray, proposal, old)
            row["shared_source_core_checks"].append(shared)
            if not shared["pass"]:
                row["reasons"].append("ANOTHER_WHOLE_PATH_OWNS_OBSERVED_SOURCE_ADJACENCIES")
    return row


def _finalize_complete_connection_groups(proposals, prior_objects, adopted, decisions, retired_ids=()):
    """Reconcile complete-group claims with the entities that will be written.

    A rejected member cannot leave its peers claiming the complete discovery
    group. Adequate retained old entities may represent members, but every
    route needs a distinct actual representative. Withdrawal also cancels the
    withdrawn paths' old-entity retirement plans, before the writer runs.
    """
    groups = {}
    known_paths = {}
    for obj in [*prior_objects, *proposals]:
        known_paths.setdefault(obj["id"], []).append(obj)
    for obj in proposals:
        evidence = obj.get("source_evidence", {})
        certificate = evidence.get("text_graphic_support", {}).get("complete_graphic_group")
        if certificate is None:
            continue
        signature = certificate.get("certificate_sha256") if isinstance(certificate, dict) else None
        key = (signature or canonical_sha(certificate),
               tuple(evidence.get("original_source_crop_xyxy_px", [])))
        members = evidence.get("graphic_group_path_responsibility", [])
        declared = {row.get("path_id"): tuple(sorted(row.get("source_graph_edge_ids", [])))
                    for row in members if isinstance(row, dict)}
        routes = {tuple(sorted(row.get("source_graph_edge_ids", [])))
                  for row in certificate.get("complete_routes", [])} if isinstance(certificate, dict) else set()
        own_route = tuple(sorted(evidence.get("source_graph_edge_ids", [])))
        # Duplicate suppression can observe an exact whole-path alias. It is
        # not a new route or member: bind it to a present canonical member's
        # actual geometry and source traversal, not its self-declared edge IDs.
        alias_bound = obj["id"] not in declared and any(
            own_route == route
            and original.get("kind") == obj.get("kind")
            and original.get("geometry") == obj.get("geometry")
            and all(original.get("source_evidence", {}).get(field) == evidence.get(field)
                    for field in ("source_path_points", "source_graph_edge_ids",
                                  "original_source_crop_xyxy_px", "original_source_crop_array_sha256",
                                  "source_connected_group_id"))
            for oid, route in declared.items() for original in known_paths.get(oid, [])
        )
        valid = (isinstance(signature, str) and bool(routes) and len(declared) == len(members)
                 and all(isinstance(oid, str) and oid for oid in declared)
                 and len(declared) == len(routes) and set(declared.values()) == routes
                 and own_route in routes
                 and (declared.get(obj["id"]) == own_route or alias_bound))
        group = groups.setdefault(key, {"certificate_sha256": signature,
                                       "members": declared, "declaring_ids": set(),
                                       "valid_declaration": valid})
        group["valid_declaration"] &= valid and group["members"] == declared
        group["declaring_ids"].add(obj["id"])
    decisions = copy.deepcopy(decisions)
    adopted = copy.deepcopy(adopted)
    adopted_ids = {obj["id"] for obj in adopted}
    prior_ids = {obj["id"] for obj in prior_objects}
    rows_by_id = {}
    for row in decisions:
        rows_by_id.setdefault(row["id"], []).append(row)
    all_planned = {oid for row in decisions for oid in row.get("retired_ids", [])}
    unassigned_retirements = set(retired_ids) - all_planned
    blocked, failed = set(), {}

    def remaining_retirements():
        return unassigned_retirements | {
            oid for row in decisions if row.get("adopted") and row["id"] not in blocked
            for oid in row.get("retired_ids", [])
        }

    def actual_representatives(member_ids, available):
        options = {}
        for oid in member_ids:
            adequate = {actual for row in rows_by_id.get(oid, [])
                        for actual in row.get("existing_adequate_ids", [])}
            choices = ({oid} | adequate) & available
            options[oid] = sorted(choices, key=lambda actual: (actual != oid, actual))
        assigned = {}

        def match(oid, seen):
            for actual in options[oid]:
                if actual in seen:
                    continue
                seen.add(actual)
                if actual not in assigned or match(assigned[actual], seen):
                    assigned[actual] = oid
                    return True
            return False

        for oid in sorted(member_ids, key=lambda identity: (len(options[identity]), identity)):
            if not match(oid, set()):
                return None, {key: values for key, values in options.items() if not values}
        return {oid: actual for actual, oid in assigned.items()}, {}

    # Withdrawal can remove a representative used by another declaration.
    # Iterate only removals; never invent a replacement or re-adopt a failure.
    while True:
        available = (prior_ids - remaining_retirements()) | (adopted_ids - blocked)
        newly_blocked = set()
        for key, group in groups.items():
            if key in failed:
                continue
            representatives, missing = actual_representatives(group["members"], available)
            if not group["valid_declaration"] or representatives is None:
                failed[key] = {
                    "reason": "FINAL_COMPLETE_GROUP_MEMBER_SET_NOT_REPRESENTED"
                    if group["valid_declaration"] else "COMPLETE_GROUP_DECLARATION_INCONSISTENT",
                    "member_ids_without_actual_representative": sorted(missing),
                }
                newly_blocked.update(set(group["members"]) | group["declaring_ids"])
        if newly_blocked <= blocked:
            break
        blocked.update(newly_blocked)
    final_retired = remaining_retirements()
    available = (prior_ids - final_retired) | (adopted_ids - blocked)
    group_rows = []
    for key, group in groups.items():
        representatives, _ = actual_representatives(group["members"], available)
        group_rows.append({
            "certificate_sha256": group["certificate_sha256"],
            "expected_proposed_member_ids": sorted(group["members"]),
            "pass": key not in failed,
            "actual_member_representatives": representatives if key not in failed else {},
            "source_scope_xyxy_px": list(key[1]),
            **failed.get(key, {}),
        })
    for row in decisions:
        if row["id"] not in blocked:
            continue
        if row.get("adopted"):
            row["decision_before_final_group_gate"] = row.get("decision", "ADOPTED_COMPLETE_PATH")
            row["decision"] = "PENDING_INCOMPLETE_FINAL_SOURCE_GROUP"
        row["adopted"] = False
        row["retired_ids"] = []
        row["reasons"] = sorted(set(row.get("reasons", [])) | {"FINAL_COMPLETE_GROUP_MEMBER_SET_NOT_REPRESENTED"})
        row["final_complete_group_gate_pass"] = False
    result = [obj for obj in adopted if obj["id"] not in blocked]
    for obj in result:
        declarations = [row for row in group_rows if row["pass"]
                        and obj["id"] in row["expected_proposed_member_ids"]]
        if declarations:
            obj["source_evidence"]["final_graphic_group_responsibility"] = declarations
    return {"objects": result, "decisions": decisions, "retired_ids": sorted(final_retired),
            "groups": group_rows, "quarantined_ids": sorted(blocked),
            "rolled_back_retired_ids": sorted(set(retired_ids) - final_retired),
            "distinct_actual_entity_required_per_member": True,
            "existing_entities_modified": 0, "before_old_entity_retirement": True,
            "recognition_or_source_graph_modified": False}


def complete_connections_without_unresolved_retirement(
    gray, roi, source_sha, objects, out, cache_dir=None, *, text_regions=None,
    verified_text_observations=None,
):
    from .connections import (
        extract_connections,
        _retirement_proposals,
        _text_boxes,
        _dense_geometry,
        _support,
        POLICY,
    )

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    revision, replay = _revision_proposals(
        cache_dir, "connections", gray, roi, source_sha, out
    )
    payload = None
    if revision is None:
        payload, replay = _load(
            cache_dir,
            "connections",
            gray,
            roi,
            source_sha,
            out,
            text_sha=text_context_sha(objects),
        )
    raw = (
        payload["discovery"]
        if payload is not None
        else revision["discovery"]
        if revision is not None
        else extract_connections(
            gray, roi, objects, out / "discovery", text_regions=text_regions,
            verified_text_observations=verified_text_observations,
        )
    )
    raw_evidence = restore_connection_discovery_evidence(
        cache_dir if payload is not None or revision is not None else out.parent,
        out,
        gray,
        discovery=raw,
        binding=(payload or revision or {}).get("raw_discovery_evidence"),
    )
    quarantine = _quarantine_native_duplicate_groups(raw["objects"], objects)
    quarantined_ids = set(quarantine["quarantined_ids"])
    members = _existing_line_members(objects)
    adopted = []
    decisions = []
    distance_fields = {}
    for proposal in raw["objects"]:
        if proposal["id"] in quarantined_ids:
            responsibility = _connection_path_responsibility(gray, proposal, objects)
            decisions.append({"id": proposal["id"], "adopted": False, **responsibility,
                              "decision": "PENDING_NATIVE_DUPLICATE_SOURCE_GROUP",
                              "reasons": [*responsibility["reasons"], "SOURCE_GROUP_HAS_DUPLICATE_NATIVE_SEGMENTS"],
                              "existing_entities_modified": 0})
            continue
        responsibility = _connection_path_responsibility(gray, proposal, [*objects, *adopted])
        reasons = list(responsibility["reasons"])
        if responsibility["existing_adequate_ids"]:
            reasons.append("EXISTING_COMPLETE_PATH_ALREADY_PRESENT_NO_DUPLICATE")
        current_recheck = None
        if revision is not None:
            import cv2

            source = proposal["source_evidence"]
            ox, oy, rx, by = source["original_source_crop_xyxy_px"]
            crop = gray[oy:by, ox:rx]
            if (
                hashlib.sha256(crop.tobytes()).hexdigest()
                != source["original_source_crop_array_sha256"]
            ):
                raise ValueError(
                    "REVISION_CONNECTION_SOURCE_CROP_CHANGED:" + proposal["id"]
                )
            points = np.asarray(source["source_path_points"], dtype=float)
            contacts = []
            for text_id, box in _text_boxes(objects):
                inside = (
                    (points[:, 0] >= box[0] - 1)
                    & (points[:, 0] <= box[2] + 1)
                    & (points[:, 1] >= box[1] - 1)
                    & (points[:, 1] <= box[3] + 1)
                )
                if int(inside.sum()) >= 6:
                    contacts.append(text_id)
            if contacts:
                reasons.append("EXISTING_NATIVE_TEXT_NEIGHBOR_CONTACT")
            crop_key = (ox, oy, rx, by)
            if crop_key not in distance_fields:
                distance_fields[crop_key] = cv2.distanceTransform(
                    (crop >= POLICY["source_threshold"]).astype("uint8"),
                    cv2.DIST_L2,
                    cv2.DIST_MASK_PRECISE,
                )
            distance = distance_fields[crop_key]
            dense = _dense_geometry(proposal["geometry"], POLICY["dense_step_px"])
            support = _support(dense, distance, np.array([ox, oy]))
            if not support["pass"]:
                reasons.append("WHOLE_NATIVE_PATH_SOURCE_GATE_FAILED")
            current_recheck = {
                "source_crop_sha256_unchanged": True,
                "source_support": support,
                "current_text_context_sha256": text_context_sha(objects),
                "current_text_neighbor_ids": contacts,
                "source_graph_and_geometry_not_refitted": True,
                "unchanged_source_graph_endpoint_evidence_retained": source[
                    "endpoint_evidence"
                ],
                "old_text_context_not_relabelled_as_current": True,
            }
        if proposal["source_evidence"].get("retirement_proposals"):
            reasons.append("EXISTING_SOURCE_LINE_RETIREMENT_NOT_CERTIFIED_COMPLETE")
        overlap, _ = _retirement_proposals(proposal["geometry"], members)
        if overlap:
            reasons.append("EXISTING_NATIVE_LINE_OR_BLOCK_MEMBER_OVERLAP")
        arc_overlap = _existing_arc_overlap(proposal, objects)
        if arc_overlap:
            reasons.append("EXISTING_NATIVE_ARC_OVERLAP")
        # This is an additional whole-object responsibility gate, not a
        # relaxation of source tolerances. All existing entities are retained.
        decisions.append(
            {
                "id": proposal["id"],
                "adopted": not reasons,
                "reasons": reasons,
                "existing_entities_modified": 0,
                "overlap_records": overlap,
                "arc_overlap_records": arc_overlap,
                "existing_adequate_ids": responsibility["existing_adequate_ids"],
                "shared_source_core_checks": responsibility["shared_source_core_checks"],
                "revision_current_source_and_text_recheck": current_recheck,
            }
        )
        if not reasons:
            adopted.append(copy.deepcopy(proposal))
    final_groups = _finalize_complete_connection_groups(raw["objects"], objects, adopted, decisions)
    adopted, decisions = final_groups["objects"], final_groups["decisions"]
    result = {
        "objects": adopted,
        "raw_candidate_count": len(raw["objects"]),
        "uncertainties": list(raw["uncertainties"])
        + [
            {"reason": "CONNECTION_EDIT_RESPONSIBILITY_PENDING", **d}
            for d in decisions
            if not d["adopted"]
        ],
        "decisions": decisions,
        "replay": replay,
        "all_existing_native_entities_retained": True,
        "native_duplicate_group_quarantine": quarantine,
        "final_complete_group_gate": {key: value for key, value in final_groups.items()
                                      if key not in ("objects", "decisions")},
        "dashed_gaps_joined": False,
        "engineering_stroke_identity_proven": False,
        "status": "LOCAL_SOURCE_PATH_CANDIDATES_REQUIRE_SAVED_DXF_AUDIT",
        "raw_discovery_evidence": raw_evidence,
    }
    save_json(out / "completion_result.json", result)
    return result
