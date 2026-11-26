"""Cold proof of whole old receiving-line reconciliation and actual retirement."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from .text_contact_adoption import object_binding
from .text_contact_audit import (
    _before_circle_relation_edits,
    _actual_geometry,
    _identity,
    _neighbor_matches,
    _primitive_matches,
    _px,
    _source_evidence,
)


FIELD = "carrier_reconciliation"


def cold_carrier_reconciliation(path, doc, gray, roi, dpi, evidence_root):
    """Verify current pixels, finite saved LINEs, retired IDs and neighbours."""
    path, evidence_root = Path(path), Path(evidence_root)
    manifest_path = evidence_root / "carrier_reconciliation" / "adoption.json"
    actual, flagged = defaultdict(list), set()
    for entity in doc.modelspace():
        ident = _identity(entity)
        if ident.get("id"):
            actual[ident["id"]].append(entity)
        if ident.get(FIELD):
            flagged.add(ident.get("id") or "UNIDENTIFIED:" + entity.dxf.handle)
    metadata, manifest, errors = {}, {}, []
    try:
        metadata = json.loads(path.with_suffix(".objects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(type(exc).__name__)
    objects = {row["id"]: row for row in metadata.get("objects", [])}
    flagged.update(oid for oid, obj in objects.items() if FIELD in _source_evidence(obj))
    if not manifest_path.exists() and not flagged:
        return {"checks": [], "pass": True, "target_ids": [], "retired_ids": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(type(exc).__name__)
    from .carrier_reconciliation import verify_existing_carrier_reconciliation

    adopted = {row["id"]: row for row in manifest.get("objects", [])}
    targets = flagged | set(adopted)
    retired = set(manifest.get("retired_ids", []))
    prior = {row["id"]: row for row in manifest.get("prior_object_bindings", [])}
    checks = {
        "receipts_loaded": not errors,
        "sidecar_bound_to_saved_DXF": metadata.get("dxf_sha256")
        == hashlib.sha256(path.read_bytes()).hexdigest(),
        "same_roi_and_dpi": metadata.get("roi_xyxy_px") == list(roi)
        == manifest.get("roi_xyxy_px") and metadata.get("dpi") == dpi,
        "unique_prior_context": len(prior) == len(manifest.get("prior_object_bindings", [])),
        "unique_adopted_ids": len(adopted) == len(manifest.get("objects", [])),
        "new_carriers_flagged_in_actual_file": targets == flagged == set(adopted),
        "retirements_are_whole_prior_objects": retired <= set(prior),
        "retired_objects_absent_from_saved_file_and_ledger": not (retired & (set(actual) | set(objects))),
    }
    try:
        replay = verify_existing_carrier_reconciliation(gray, roi, manifest)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        replay = {"pass": False, "reason": type(exc).__name__ + ": " + str(exc)}
    checks["whole_source_ranges_and_terminals_replayed"] = replay.get("pass") is True
    # A rewritten identity is not a clean retirement.  Read all actual
    # LINE members (including block members and polyline spans), and reuse
    # the same complete-source proof for near-overlapping expressions.
    from .carrier_reconciliation import _candidate, prove_existing_carrier_pair

    actual_lines, _ = _actual_geometry(doc, roi, dpi)
    observed_lines = [{
        "id": f"SAVED:{row['handle']}:{row['member']}:{row['segment']}",
        "kind": "LINE", "layer": "ACTUAL_SAVED_GEOMETRY",
        "geometry": {"start": row["a"].tolist(), "end": row["b"].tolist()},
        "saved_handle": row["handle"], "saved_source_id": row["id"],
    } for row in actual_lines]
    residues = []
    for old_id in retired:
        binding = prior.get(old_id)
        if binding is None or binding.get("kind") != "LINE":
            continue
        old_points = np.asarray([binding["geometry"][key] for key in ("start", "end")])
        for observed in observed_lines:
            new_points = np.asarray([observed["geometry"][key] for key in ("start", "end")])
            if any(np.allclose(old_points, points, atol=1e-7, rtol=0) for points in (new_points, new_points[::-1])):
                residues.append({"retired_id": old_id, "actual_segment_id": observed["id"],
                                 "actual_source_id": observed["saved_source_id"],
                                 "reason": "RETIRED_WHOLE_GEOMETRY_REMAINS_UNDER_ANY_IDENTITY"})
    for oid in targets:
        handles = {entity.dxf.handle for entity in actual.get(oid, [])}
        receivers = [row for row in observed_lines if row["saved_handle"] in handles]
        for receiver in receivers:
            for other in observed_lines:
                if other["saved_handle"] in handles or _candidate(receiver, other) is None:
                    continue
                proof = prove_existing_carrier_pair(gray, receiver, other, prior_objects=observed_lines)
                if proof["pass"]:
                    residues.append({"carrier_id": oid, "actual_segment_id": other["id"],
                                     "actual_source_id": other["saved_source_id"],
                                     "reason": "ANOTHER_WHOLE_SAVED_EXPRESSION_HAS_THE_SAME_SOURCE_STROKE",
                                     "complete_source_proof": proof})
    checks["no_saved_same_source_old_geometry_residue"] = not residues
    rows = [{"id": "CARRIER_RECONCILIATION_SOURCE", "type": "SAVED_CARRIER_SOURCE_AND_RETIREMENT",
             "checks": checks, "pass": all(checks.values()), "source_replay": replay,
             "errors": errors, "actual_same_source_residues": residues}]
    receipts = {row["id"]: row for row in metadata.get("written", [])}
    for oid in sorted(targets):
        actual_checks = {}
        try:
            obj, claimed = objects[oid], adopted[oid]
            actual_checks["one_finite_native_LINE"] = (
                len(actual[oid]) == 1 and actual[oid][0].dxftype() == "LINE"
                and obj["kind"] == claimed["kind"] == "LINE"
            )
            entity = actual[oid][0]
            actual_checks["exact_adopted_geometry_and_source_receipt"] = (
                object_binding(obj) == object_binding(claimed)
                and _source_evidence(obj).get(FIELD) == _source_evidence(claimed).get(FIELD)
            )
            actual_checks["saved_identity_and_receipt"] = (
                _identity(entity).get(FIELD) is True
                and _identity(entity).get("kind") == obj["kind"]
                and receipts[oid]["handle"] == entity.dxf.handle
                and receipts[oid]["type"] == entity.dxftype()
                and entity.dxf.layer == obj["layer"]
            )
            actual_checks.update({"actual_" + key: value for key, value in
                                  _primitive_matches(entity, obj["kind"], obj["geometry"], roi, dpi).items()})
            decision = manifest["decisions"][_source_evidence(claimed)[FIELD]["decision_index"]]
            endpoints = [entity.dxf.start, entity.dxf.end]
            for index, terminal in enumerate(decision["proof"].get("native_endpoint_return_bindings", [])):
                for bound in terminal.get("matched_existing_returns", []):
                    rid = bound["object_binding"]["id"]
                    valid = len(actual.get(rid, [])) == 1 and actual[rid][0].dxftype() == "LINE"
                    if valid:
                        return_line = actual[rid][0]
                        point = np.asarray(_px(endpoints[index], roi, dpi))
                        a, b = (np.asarray(_px(p, roi, dpi)) for p in (return_line.dxf.start, return_line.dxf.end))
                        vector = b - a
                        projection = float((point - a) @ vector / (vector @ vector))
                        distance = float(np.linalg.norm(point - (a + np.clip(projection, 0, 1) * vector)))
                        valid = np.isfinite(distance) and distance <= 1e-7 and 0 <= projection <= 1
                    actual_checks[f"actual_endpoint_{index}_contacts_finite_return:{rid}"] = bool(valid)
        except (KeyError, TypeError, ValueError, IndexError):
            actual_checks["saved_carrier_binding_complete"] = False
        rows.append({"id": oid, "type": "SAVED_RECONCILED_CARRIER_LINE",
                     "pass": all(actual_checks.values()), "checks": actual_checks})
    protected = []
    for oid, binding in sorted(prior.items()):
        if oid in retired:
            continue
        neighbor_checks = {"one_actual_entity": len(actual.get(oid, [])) == 1,
                           "candidate_present": oid in objects}
        try:
            obj = objects[oid]
            unchanged = object_binding(binding) == object_binding(obj)
            if not unchanged:
                before_final_relations = _before_circle_relation_edits(
                    gray, roi, obj, list(objects.values())
                )
                unchanged = object_binding(binding) == object_binding(before_final_relations)
            neighbor_checks["protected_candidate_geometry"] = unchanged
            font = path.parent / "DejaVuSans.ttf"
            if obj["kind"] == "TEXT":
                from .single_line_text_audit import resolve_saved_text_font

                _, font, _ = resolve_saved_text_font(path, metadata, obj)
            neighbor_checks["actual_saved_neighbor_geometry"] = (
                neighbor_checks["one_actual_entity"]
                and _neighbor_matches(actual[oid][0], obj, roi, dpi, font)
            )
        except (KeyError, TypeError, ValueError, IndexError, OSError):
            neighbor_checks["actual_saved_neighbor_geometry"] = False
        protected.append({"id": oid, "pass": all(neighbor_checks.values()), "checks": neighbor_checks})
    rows.append({"id": "CARRIER_RECONCILIATION_NEIGHBORS", "type": "SAVED_CARRIER_NEIGHBOR_PROTECTION",
                 "pass": all(row["pass"] for row in protected), "objects": protected})
    return {"checks": rows, "pass": all(row["pass"] for row in rows),
            "target_ids": sorted(targets), "retired_ids": sorted(retired),
            "source_or_DXF_modified": False}
