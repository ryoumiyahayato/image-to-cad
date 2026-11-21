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
    from . import connection_core_routes

    expected = {
        connection_core_routes.__name__: hashlib.sha256(
            Path(connection_core_routes.__file__).read_bytes()
        ).hexdigest()
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
        if obj["kind"] != "DOOR":
            continue
        for i, member in enumerate(native_members(obj)):
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


def complete_connections_without_unresolved_retirement(
    gray, roi, source_sha, objects, out, cache_dir=None, *, text_regions=None
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
            gray, roi, objects, out / "discovery", text_regions=text_regions
        )
    )
    raw_evidence = restore_connection_discovery_evidence(
        cache_dir if payload is not None or revision is not None else out.parent,
        out,
        gray,
        discovery=raw,
        binding=(payload or revision or {}).get("raw_discovery_evidence"),
    )
    members = _existing_line_members(objects)
    adopted = []
    decisions = []
    distance_fields = {}
    for proposal in raw["objects"]:
        reasons = []
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
                "revision_current_source_and_text_recheck": current_recheck,
            }
        )
        if not reasons:
            adopted.append(copy.deepcopy(proposal))
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
        "dashed_gaps_joined": False,
        "engineering_stroke_identity_proven": False,
        "status": "LOCAL_SOURCE_PATH_CANDIDATES_REQUIRE_SAVED_DXF_AUDIT",
        "raw_discovery_evidence": raw_evidence,
    }
    save_json(out / "completion_result.json", result)
    return result
