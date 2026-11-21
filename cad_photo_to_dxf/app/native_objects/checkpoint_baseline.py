"""Compose saved baseline deltas and reprove their original path observations.

This module never draws or discovers geometry. It retains actual DXF entities;
the old report identifies a proposed whole-entity replacement which must pass
the current source/ownership rules again. Captured graphs are raw observations,
not old PASS records or permission to adopt any new path.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath

import ezdxf
import numpy as np
from scipy.ndimage import distance_transform_edt

from . import cad_io
from .connection_checkpoint_cad import (
    _compare_preserved,
    _copy_resource,
    _entity,
    _formal,
    _resources,
    _serialize_preserving_old_defaults,
    _snapshot,
)
from .connection_retrace_audit import _neighbors, certify_saved_retraces
from .connections import POLICY, _dense_geometry, _support
from .contracts import save_json
from .execution import file_sha
from .quality_review import _candidate_geometry_checks


SCHEMA = "native-baseline-evidence-v1"
_PARENTS = ("primary_dxf", "primary_ownership", "delta_dxf", "delta_ownership", "delta_report")


def _fail(reason):
    raise ValueError("BASELINE_CONTINUATION_" + reason)


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("HASH_INVALID")
    return value


def _asset(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": file_sha(path)}


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative_asset(value, root):
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        _fail("ASSET_FIELDS_INVALID")
    name = value["path"]
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute() or any(p in ("", ".", "..") for p in name.split("/"))):
        _fail("PORTABLE_RELATIVE_ASSET_REQUIRED")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        _fail("ASSET_OUTSIDE_ROOT_OR_MISSING")
    if file_sha(path) != _sha(value["sha256"]):
        _fail("ASSET_HASH_MISMATCH")
    return path


def _bundle(asset):
    path = Path(asset["path"]).resolve()
    if file_sha(path) != _sha(asset["sha256"]):
        _fail("MANIFEST_HASH_MISMATCH")
    data = _json(path)
    required = {"schema", "source_sha256", "source_array_sha256", "roi_xyxy_px", "dpi",
                "baseline_dxf_sha256", "baseline_ownership_sha256", "composed_ownership", "parents",
                "protected_object_ids", "retired_object_ids", "discovery_scopes"}
    if not isinstance(data, dict) or set(data) != required or data["schema"] != SCHEMA:
        _fail("MANIFEST_FIELDS_INVALID")
    if not isinstance(data["parents"], dict) or set(data["parents"]) != set(_PARENTS):
        _fail("PARENT_ASSETS_REQUIRED")
    assets = [*data["parents"].values(), data["composed_ownership"]]
    if not isinstance(data["discovery_scopes"], list) or not 1 <= len(data["discovery_scopes"]) <= 8:
        _fail("BOUNDED_RAW_GRAPHS_REQUIRED")
    for scope in data["discovery_scopes"]:
        if not isinstance(scope, dict) or set(scope) != {"roi_xyxy_px", "graph", "discovery", "object_ids"}:
            _fail("DISCOVERY_SCOPE_FIELDS_INVALID")
        assets += [scope["graph"], scope["discovery"]]
    resolved = [_relative_asset(item, path.parent) for item in assets]
    if len(resolved) != len(set(resolved)):
        _fail("ASSET_PATHS_NOT_DISTINCT")
    for name in ("protected_object_ids", "retired_object_ids"):
        rows = data[name]
        if (not isinstance(rows, list) or not all(isinstance(v, str) and v for v in rows)
                or len(rows) != len(set(rows))):
            _fail("OBJECT_IDS_INVALID")
    return data, path.parent, assets


def capture_baseline_evidence(manifest_asset, directory):
    """Copy a relative evidence bundle; no author paths survive this boundary."""
    data, root, assets = _bundle(manifest_asset)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for asset in assets:
        source = _relative_asset(asset, root)
        target = directory / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_resource(source, target)
    target = directory / "manifest.json"
    _copy_resource(Path(manifest_asset["path"]), target)
    captured = _asset(target)
    _bundle(captured)
    if file_sha(manifest_asset["path"]) != manifest_asset["sha256"]:
        _fail("ORIGINAL_MANIFEST_CHANGED_DURING_CAPTURE")
    return captured


def _source(source_path, source_sha, parameters, gray=None):
    from .source_import import _decode, inspect_source

    if file_sha(source_path) != source_sha or parameters.get("orientation") != 0:
        _fail("CURRENT_SOURCE_OR_ORIENTATION_MISMATCH")
    if gray is None:
        info = inspect_source(source_path, dpi=parameters["dpi"],
                              page_number=parameters.get("page_number"),
                              frame_number=parameters.get("frame_number"))
        gray = _decode(source_path, info, parameters["dpi"])
    gray = np.ascontiguousarray(gray)
    if gray.ndim != 2 or gray.dtype != np.uint8:
        _fail("ORIGINAL_UINT8_SOURCE_REQUIRED")
    return gray


def _plan(primary, primary_path, delta, delta_path, report, gray, source_sha, roi, dpi):
    from .connection_checkpoint import adopt_checkpoint_paths
    from .connection_checkpoint_inputs import _baseline

    _baseline(primary, _asset(primary_path), source_sha, roi, dpi)
    _baseline(delta, _asset(delta_path), source_sha, roi, dpi)
    primary_doc, delta_doc = ezdxf.readfile(primary_path), ezdxf.readfile(delta_path)
    old, changed = _formal(primary_doc), _formal(delta_doc)
    old_rows = {row["id"]: row for row in primary["objects"]}
    delta_rows = {row["id"]: row for row in delta["objects"]}
    common = set(old) & set(changed)
    added = set(changed) - set(old)
    if not added:
        _fail("NO_SAVED_DELTA_OBJECTS")
    for oid in common:
        if _entity(old[oid]) != _entity(changed[oid]) or old_rows[oid] != delta_rows[oid]:
            _fail("COMMON_OLD_ENTITY_CHANGED:" + oid)
    if any(delta_rows[oid]["kind"] != "CONNECTION_PATH" or changed[oid].dxftype() != "LWPOLYLINE" for oid in added):
        _fail("ONLY_SAVED_PATH_DELTA_SUPPORTED")
    if (report.get("source_sha256") != source_sha
            or report.get("render", {}).get("DXF_sha256") != delta["dxf_sha256"]
            or set(report.get("new_complete_path_ids", [])) != added
            or set(report.get("preserved_old_object_ids", [])) != common):
        _fail("DELTA_REPORT_NOT_BOUND_TO_SAVED_FILES")
    claims = set()
    for oid in added:
        record = delta_rows[oid]["source_evidence"].get("checkpoint_responsibility_resolution")
        if not isinstance(record, dict) or record.get("id") != oid or record.get("adopted") is not True:
            _fail("WHOLE_REPLACEMENT_RECORD_MISSING")
        claims.update(record.get("retired_ids", []))
    if claims != set(report.get("retired_whole_line_ids", [])) or not claims <= set(old) - set(changed):
        _fail("RETIRED_IDS_LACK_WHOLE_ENTITY_BASIS")
    proposals = [delta_rows[oid] for oid in delta_rows if oid in added]
    current = adopt_checkpoint_paths(gray, proposals, primary["objects"])
    if set(current["retired_ids"]) != claims or {o["id"] for o in current["objects"]} != added:
        _fail("CURRENT_WHOLE_OBJECT_RESPONSIBILITY_REJECTED")
    if any(any(c.get("local_cycle_cover_evidence") for c in obj.get("source_evidence", {}).get("crossing_evidence", []))
           for obj in primary["objects"]):
        _fail("PRIMARY_RETRACE_COMPOSITION_REQUIRES_ITS_OWN_EVIDENCE")
    return primary_doc, delta_doc, old, changed, old_rows, delta_rows, common, added, claims, current


def _validate_graphs(data, root, gray, objects, actual, roi, dpi):
    assigned, scopes, checked = set(), [], []
    mm = 25.4 / dpi

    def pixel(point):
        return np.array([float(point[0]) / mm + roi[0], roi[3] - float(point[1]) / mm])

    for index, scope in enumerate(data["discovery_scopes"]):
        local = scope["roi_xyxy_px"]
        if (not isinstance(local, list) or len(local) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in local)
                or not (roi[0] <= local[0] < local[2] <= roi[2] and roi[1] <= local[1] < local[3] <= roi[3])):
            _fail("GRAPH_SCOPE_OUTSIDE_PARENT")
        graph_path, discovery_path = (_relative_asset(scope[k], root) for k in ("graph", "discovery"))
        graph, discovery = _json(graph_path), _json(discovery_path)
        if (discovery.get("source_graph", {}).get("sha256") != file_sha(graph_path)
                or discovery.get("policy", {}).get("source_threshold") != POLICY["source_threshold"]
                or discovery.get("policy", {}).get("context_px") != POLICY["context_px"]):
            _fail("RAW_GRAPH_POLICY_OR_HASH_MISMATCH")
        margin = POLICY["context_px"]
        x0, y0, x1, y1 = expected = [max(0, local[0] - margin), max(0, local[1] - margin),
                                    min(gray.shape[1], local[2] + margin), min(gray.shape[0], local[3] + margin)]
        crop = gray[y0:y1, x0:x1]
        if graph.get("source_crop_xyxy_px") != expected or graph.get("source_crop_array_sha256") != hashlib.sha256(crop.tobytes()).hexdigest():
            _fail("RAW_GRAPH_CURRENT_SOURCE_MISMATCH")
        ids = scope["object_ids"]
        if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                or assigned.intersection(ids) or not set(ids) <= set(data["protected_object_ids"])):
            _fail("RAW_GRAPH_OBJECT_ASSIGNMENT_INVALID")
        assigned.update(ids)
        observed = {obj["id"]: obj for obj in discovery["objects"]}
        skeleton = {tuple(p) for row in graph["nodes"] + graph["edges"]
                    for p in row.get("source_core_points", row.get("source_points", []))}
        edges = {row["id"] for row in graph["edges"]}
        distance = distance_transform_edt(crop >= POLICY["source_threshold"])
        for oid in ids:
            obj = objects[oid]
            raw = observed.get(oid)
            if raw is None or any(raw.get(k) != obj.get(k) for k in ("id", "kind", "layer", "geometry")):
                _fail("SAVED_PATH_DIFFERS_FROM_RAW_OBSERVATION:" + oid)
            source = {k: v for k, v in obj["source_evidence"].items() if k != "checkpoint_responsibility_resolution"}
            if source != raw["source_evidence"]:
                _fail("PATH_SOURCE_EVIDENCE_DIFFERS_FROM_RAW:" + oid)
            points = [tuple(p) for p in source["source_path_points"]]
            if (len(points) < 2 or not set(source["source_graph_edge_ids"]) <= edges
                    or any(p not in skeleton or not all(v == int(v) for v in p)
                           or not (0 <= p[0] < gray.shape[1] and 0 <= p[1] < gray.shape[0])
                           or gray[int(p[1]), int(p[0])] >= 128 for p in points)
                    or any(b not in set(_neighbors(a, skeleton)) for a, b in zip(points, points[1:]))):
                _fail("PATH_NOT_ON_CURRENT_ORIGINAL_GRAPH:" + oid)
            support = _support(_dense_geometry(obj["geometry"]), distance, np.array([x0, y0]))
            checks = _candidate_geometry_checks(actual[oid], obj, [actual[oid]], pixel, mm)
            if not support["pass"] or not all(value is True for key, value in checks.items() if key != "contract_error"):
                _fail("ACTUAL_PATH_SOURCE_OR_GEOMETRY_REJECTED:" + oid)
            checked.append({"id": oid, "scope_index": index, "source_support": support,
                            "actual_saved_geometry_matches": True})
        scopes.append({"roi_xyxy_px": local, "graph_path": scope["graph"]["path"],
                       "graph_sha256": scope["graph"]["sha256"],
                       "discovery_path": scope["discovery"]["path"],
                       "discovery_sha256": scope["discovery"]["sha256"], "object_ids": ids})
    if assigned != set(data["protected_object_ids"]):
        _fail("PROTECTED_PATH_HAS_NO_RAW_GRAPH")
    return scopes, checked


def verify_baseline_evidence(asset, baseline_dxf, baseline_meta, source_path, source_sha, parameters, *, gray=None):
    """Recheck parent entities, whole retirement and graph/source bytes now."""
    data, root, _ = _bundle(asset)
    roi, dpi = list(parameters["roi"]), parameters["dpi"]
    gray = _source(source_path, source_sha, parameters, gray)
    if (data["source_sha256"] != source_sha or data["roi_xyxy_px"] != roi or data["dpi"] != dpi
            or data["source_array_sha256"] != hashlib.sha256(gray.tobytes()).hexdigest()
            or data["baseline_dxf_sha256"] != file_sha(baseline_dxf)
            or baseline_meta["dxf_sha256"] != data["baseline_dxf_sha256"]):
        _fail("CURRENT_BASELINE_SOURCE_BINDING_MISMATCH")
    parents = {name: _relative_asset(value, root) for name, value in data["parents"].items()}
    primary, delta, report = (_json(parents[name]) for name in ("primary_ownership", "delta_ownership", "delta_report"))
    plan = _plan(primary, parents["primary_dxf"], delta, parents["delta_dxf"], report, gray, source_sha, roi, dpi)
    primary_doc, _, old, changed, old_rows, delta_rows, common, added, retired, decisions = plan
    if set(data["protected_object_ids"]) != added or set(data["retired_object_ids"]) != retired:
        _fail("DECLARED_COMPOSITION_SETS_CHANGED")
    doc = ezdxf.readfile(baseline_dxf)
    actual = _formal(doc)
    expected = (set(old) - retired) | added
    if set(actual) != expected or {row["id"] for row in baseline_meta["objects"]} != expected:
        _fail("COMPOSED_ENTITY_SET_CHANGED")
    before = _snapshot(primary_doc, {oid: entity for oid, entity in old.items() if oid not in retired})
    after = _snapshot(doc, {oid: actual[oid] for oid in old if oid not in retired})
    _compare_preserved(before, after)
    rows = {row["id"]: row for row in baseline_meta["objects"]}
    for oid in expected:
        if rows[oid] != (delta_rows[oid] if oid in added else old_rows[oid]):
            _fail("COMPOSED_SOURCE_LEDGER_CHANGED:" + oid)
    for oid in added:
        a, b = _entity(changed[oid]), _entity(actual[oid])
        a.pop("handle")
        b.pop("handle")
        if a != b:
            _fail("SAVED_DELTA_ENTITY_CHANGED:" + oid)
    scopes, checks = _validate_graphs(data, root, gray, rows, actual, roi, dpi)
    # The composed ledger stores paths relative to root/evidence. The caller
    # captures that same layout, so no historical author path is consulted.
    expected_scopes = [{**row,
                        "graph_path": str(PurePosixPath(row["graph_path"]).relative_to("evidence")),
                        "discovery_path": str(PurePosixPath(row["discovery_path"]).relative_to("evidence"))}
                       for row in scopes]
    if baseline_meta.get("connection_discovery_scopes") != expected_scopes:
        _fail("COMPOSED_GRAPH_ROUTING_CHANGED")
    # Verification is read-only: use the captured composed sidecar, whose hash
    # is explicitly included in this bundle, instead of creating audit inputs.
    meta_path = _relative_asset(data["composed_ownership"], root)
    if (file_sha(meta_path) != data["baseline_ownership_sha256"]
            or _json(meta_path) != baseline_meta):
        _fail("COMPOSED_LEDGER_BYTES_NOT_BOUND")
    proof = certify_saved_retraces(doc, file_sha(baseline_dxf), meta_path,
                                  root / "evidence/connections/discovery/source_graph.json",
                                  root / "evidence/connections/discovery/connections.json", gray, roi, dpi)
    if any(row.get("pass") is not True for row in proof["object_checks"]):
        _fail("CURRENT_COLD_RETRACE_PROOF_REJECTED")
    if file_sha(source_path) != source_sha:
        _fail("SOURCE_CHANGED_DURING_VERIFICATION")
    _bundle(asset)
    return {"protected_object_ids": sorted(added), "retired_object_ids": sorted(retired),
            "raw_scope_checks": checks, "cold_retrace_proof": proof,
            "current_whole_object_responsibility": decisions,
            "manifest": data, "root": root, "old_PASS_used_as_authorization": False}


def materialize_baseline_graphs(asset, evidence_dir, baseline_meta, protected_ids):
    """Copy only original graph proofs for already retained baseline paths."""
    data, root, _ = _bundle(asset)
    rows = {row["id"]: row for row in baseline_meta["objects"]}
    scopes = []
    for index, scope in enumerate(data["discovery_scopes"]):
        ids = [oid for oid in scope["object_ids"] if oid in protected_ids and any(
            c.get("local_cycle_cover_evidence") for c in rows[oid]["source_evidence"].get("crossing_evidence", []))]
        if not ids:
            continue
        directory = Path(evidence_dir) / "baseline_observations" / f"{index:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        copied = {}
        for key, filename in (("graph", "source_graph.json"), ("discovery", "connections.json")):
            source = _relative_asset(scope[key], root)
            target = directory / filename
            _copy_resource(source, target)
            copied[key] = target
        scopes.append({"roi_xyxy_px": scope["roi_xyxy_px"], "object_ids": ids,
                       "graph_path": copied["graph"].relative_to(evidence_dir).as_posix(),
                       "graph_sha256": scope["graph"]["sha256"],
                       "discovery_path": copied["discovery"].relative_to(evidence_dir).as_posix(),
                       "discovery_sha256": scope["discovery"]["sha256"]})
    return scopes


def compose_checkpoint_baseline(primary_dxf, primary_ownership, delta_dxf, delta_ownership,
                                delta_report, delta_evidence_directory, source_path, output_path):
    """Compose an actual saved path delta without rebuilding the old drawing."""
    output = Path(output_path).resolve()
    if output.parent.exists() and any(output.parent.iterdir()):
        _fail("COMPOSITION_REQUIRES_NEW_EMPTY_DIRECTORY")
    primary_path, delta_path = Path(primary_dxf).resolve(), Path(delta_dxf).resolve()
    primary, delta, report = _json(primary_ownership), _json(delta_ownership), _json(delta_report)
    roi, dpi, source_sha = primary["roi_xyxy_px"], primary["dpi"], primary["source_sha256"]
    parameters = {"roi": roi, "dpi": dpi, "orientation": 0, "page_number": None, "frame_number": None}
    gray = _source(source_path, source_sha, parameters)
    plan = _plan(primary, primary_path, delta, delta_path, report, gray, source_sha, roi, dpi)
    doc, _, old, changed, old_rows, delta_rows, common, added, retired, _ = plan
    output.parent.mkdir(parents=True, exist_ok=True)
    parents = {}
    for name, path in zip(_PARENTS, (primary_path, primary_ownership, delta_path, delta_ownership, delta_report)):
        target = output.parent / "parents" / (name + (".dxf" if name.endswith("dxf") else ".json"))
        target.parent.mkdir(exist_ok=True)
        _copy_resource(Path(path), target)
        parents[name] = {"path": target.relative_to(output.parent).as_posix(), "sha256": file_sha(target)}
    raw_scopes, scopes = [], []
    for index, scope in enumerate(delta.get("connection_discovery_scopes", [])):
        ids = [oid for oid in scope["object_ids"] if oid in added]
        if not ids:
            continue
        target_dir = output.parent / "evidence" / "baseline_scopes" / f"{index:03d}"
        target_dir.mkdir(parents=True)
        raw = {"roi_xyxy_px": scope["roi_xyxy_px"], "object_ids": ids}
        bound = {"roi_xyxy_px": scope["roi_xyxy_px"], "object_ids": ids}
        for key, filename in (("graph", "source_graph.json"), ("discovery", "connections.json")):
            source = _relative_asset({"path": scope[key + "_path"], "sha256": scope[key + "_sha256"]}, delta_evidence_directory)
            target = target_dir / filename
            _copy_resource(source, target)
            raw[key] = {"path": target.relative_to(output.parent).as_posix(), "sha256": file_sha(target)}
            bound[key + "_path"] = target.relative_to(output.parent / "evidence").as_posix()
            bound[key + "_sha256"] = file_sha(target)
        raw_scopes.append(raw)
        scopes.append(bound)
    before = _snapshot(doc, {oid: e for oid, e in old.items() if oid not in retired})
    for entity in list(doc.modelspace()):
        if entity.dxf.layer == "REVIEW" or cad_io.identity(entity)["id"] in retired:
            doc.modelspace().delete_entity(entity)
    for oid in delta_rows:
        if oid in added:
            if changed[oid].dxf.layer not in doc.layers:
                _fail("NEW_PATH_LAYER_NOT_IN_PRIMARY")
            doc.modelspace().add_entity(changed[oid].copy())
    serialization = _serialize_preserving_old_defaults(doc, output)
    cold = ezdxf.readfile(output)
    actual = _formal(cold)
    _compare_preserved(before, _snapshot(cold, {oid: actual[oid] for oid in old if oid not in retired}))
    audit = cold.audit()
    if audit.errors or audit.fixes:
        _fail("COMPOSED_DXF_REQUIRES_REPAIR")
    objects = [deepcopy(row) for row in primary["objects"] if row["id"] not in retired]
    objects += [deepcopy(row) for row in delta["objects"] if row["id"] in added]
    previous_written = {row["id"]: row for row in primary["written"] + delta["written"]}
    written = [{**deepcopy(previous_written[row["id"]]), "handle": actual[row["id"]].dxf.handle} for row in objects]
    resources = _resources(primary_path, primary.get("font"), delta.get("font"), delta_path.parent, output.parent)
    meta = {**deepcopy(primary), "dxf_path": str(output), "dxf_sha256": file_sha(output),
            "objects": objects, "written": written, "repair_regions": [],
            "serialization": serialization, "connection_discovery_scopes": scopes}
    if isinstance(meta.get("font"), dict):
        meta["font"]["source"] = str(output.parent / meta["font"]["font"])
    meta_path = output.with_suffix(".objects.json")
    save_json(meta_path, meta)
    _copy_resource(meta_path, output.parent / "composed.objects.json")
    evidence = {"schema": SCHEMA, "source_sha256": source_sha,
                "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                "roi_xyxy_px": roi, "dpi": dpi, "baseline_dxf_sha256": file_sha(output),
                "baseline_ownership_sha256": file_sha(meta_path),
                "composed_ownership": {"path": "composed.objects.json", "sha256": file_sha(meta_path)},
                "parents": parents,
                "protected_object_ids": sorted(added), "retired_object_ids": sorted(retired),
                "discovery_scopes": raw_scopes}
    manifest = output.parent / "baseline_evidence.json"
    save_json(manifest, evidence)
    verified = verify_baseline_evidence(_asset(manifest), output, meta, source_path, source_sha, parameters, gray=gray)
    receipt = {"schema": "native-baseline-composition-result-v1", "status": "PASS",
               "baseline_dxf": _asset(output), "baseline_ownership": _asset(meta_path),
               "baseline_evidence": _asset(manifest), "primary_objects": len(old),
               "delta_objects": len(changed), "shared_unchanged_objects": len(common),
               "composed_objects": len(actual), "protected_object_ids": sorted(added),
               "retired_object_ids": sorted(retired), "resources": resources,
               "raw_scope_checks": verified["raw_scope_checks"],
               "source_graphs_reproved_not_old_PASS": True,
               "old_entities_reconstructed_from_ledger": False, "OCR_calls": 0,
               "full_region_conversion_runs": 0}
    save_json(output.parent / "composition_result.json", receipt)
    return receipt
