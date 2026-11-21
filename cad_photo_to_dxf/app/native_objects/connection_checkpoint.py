"""Bounded native connection reconstruction from captured source checkpoints.

The checkpoint is a source/observation and preservation contract, never an
adoption whitelist. Every new path is discovered from unchanged pixels and
passes the current native writer, cold source audit and saved review gates.
"""

from copy import deepcopy
import hashlib
from pathlib import Path
import time

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

from .connection_checkpoint_inputs import (
    capture_checkpoint,
    load_captured_checkpoint,
    verify_captured_checkpoint,
)
from .connections import (
    POLICY,
    _dense_geometry,
    _retirement_proposals,
    _support,
    extract_connections,
)
from .contracts import TOLERANCES, save_json
from .completion_stages import (
    _connection_path_responsibility, _existing_arc_overlap, _existing_line_members,
)
from .execution import check_cancel, file_sha

__all__ = [
    "capture_checkpoint",
    "load_captured_checkpoint",
    "verify_captured_checkpoint",
    "adopt_checkpoint_paths",
    "run_connection_checkpoint",
]


def _line_source_coverage(proposal, line):
    points = np.asarray(proposal["source_evidence"]["source_path_points"], float)
    a, b = (np.asarray(line["geometry"][key], float) for key in ("start", "end"))
    delta = b - a
    fraction = np.clip((points - a) @ delta / max(float(delta @ delta), 1e-12), 0, 1)
    distance = np.linalg.norm(points - (a + fraction[:, None] * delta), axis=1)
    return {
        "source_to_old_finite_line_max_px": float(distance.max()),
        "source_to_old_finite_line_p95_px": float(np.percentile(distance, 95)),
        "observed_endpoint_distances_px": distance[[0, -1]].tolist(),
        "already_complete_within_existing_line_tolerances": bool(
            distance.max() <= TOLERANCES["line_perpendicular_px"]
            and max(distance[0], distance[-1]) <= TOLERANCES["line_endpoint_px"]
        ),
    }


def _simple_component_line_contacts(gray, proposal, members):
    """Find old ownership on an isolated chain even off its exact centreline.

    A narrow parallel-geometry test is only a candidate interval finder. An
    older source-supported approximation can be a pixel away and still own
    the same ink. This broader responsibility search applies only when the
    complete original component is a proven simple chain; shared junctions
    continue to use their port-specific ownership rules.
    """
    source = proposal["source_evidence"]
    if not source.get("whole_simple_source_chain", {}).get("pass"):
        return []
    x0, y0, x1, y1 = source["original_source_crop_xyxy_px"]
    crop = gray[y0:y1, x0:x1]
    if hashlib.sha256(crop.tobytes()).hexdigest() != source["original_source_crop_array_sha256"]:
        raise ValueError("CONNECTION_REPLACEMENT_SOURCE_CHANGED")
    ink = crop < POLICY["source_threshold"]
    _, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    origin = np.array([x0, y0])
    raw = np.asarray(source["source_path_points"], float)
    samples = np.rint(raw - origin).astype(int)
    owner_labels = set(labels[samples[:, 1], samples[:, 0]].tolist())
    if len(owner_labels) != 1 or 0 in owner_labels:
        return []
    label = owner_labels.pop()
    distance, nearest = distance_transform_edt(~ink, return_indices=True)
    radius = POLICY["source_perpendicular_px"]
    lo, hi = raw.min(axis=0) - radius, raw.max(axis=0) + radius
    contacts = []
    for member in members:
        g = member["geometry"]
        endpoints = np.asarray([g["start"], g["end"]], float)
        if np.any(endpoints.max(axis=0) < lo) or np.any(endpoints.min(axis=0) > hi):
            continue
        line = _dense_geometry({"points": endpoints.tolist(), "bulges": [0, 0]})
        index = np.rint(line - origin).astype(int)
        inside = ((index[:, 0] >= 0) & (index[:, 0] < ink.shape[1])
                  & (index[:, 1] >= 0) & (index[:, 1] < ink.shape[0]))
        index = index[inside]
        if not len(index):
            continue
        owners = labels[nearest[0, index[:, 1], index[:, 0]],
                        nearest[1, index[:, 1], index[:, 0]]]
        supported = distance[index[:, 1], index[:, 0]] <= radius
        if np.any((owners == label) & supported):
            contacts.append(member["id"])
    return contacts


def _whole_line_responsibility(gray, proposal, line):
    """Certify an entire old LINE on one fully accounted simple ink chain.

    Parallel intervals alone cannot authorize retirement. Original ink labels
    must assign every old line sample to this same isolated source component;
    the current chain certificate owns every source adjacency and both ends.
    No partial block member, extra component, branch or outside remainder is
    silently removed. The normal old-line source tolerances stay unchanged.
    """
    source = proposal["source_evidence"]
    certificate = source.get("whole_simple_source_chain", {})
    result = {"old_object_id": line["id"], "pass": False}
    if line["kind"] != "LINE" or not certificate.get("pass"):
        result["reason"] = "WHOLE_SIMPLE_COMPONENT_RESPONSIBILITY_NOT_PROVEN"
        return result
    x0, y0, x1, y1 = source["original_source_crop_xyxy_px"]
    crop = gray[y0:y1, x0:x1]
    if hashlib.sha256(crop.tobytes()).hexdigest() != source["original_source_crop_array_sha256"]:
        raise ValueError("CONNECTION_REPLACEMENT_SOURCE_CHANGED")
    ink = crop < POLICY["source_threshold"]
    _, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    origin = np.array([x0, y0])
    raw = np.asarray(source["source_path_points"], float)
    q = np.rint(raw - origin).astype(int)
    if not np.array_equal(q + origin, raw):
        raise ValueError("CONNECTION_REPLACEMENT_NONPIXEL_SOURCE_CHAIN")
    expected = set(labels[q[:, 1], q[:, 0]].tolist())
    if len(expected) != 1 or 0 in expected:
        result["reason"] = "SOURCE_CHAIN_NOT_ON_ONE_ORIGINAL_INK_COMPONENT"
        return result
    component = expected.pop()
    g = line["geometry"]
    dense = _dense_geometry({"points": [g["start"], g["end"]], "bulges": [0, 0]})
    local = dense - origin
    index = np.rint(local).astype(int)
    if (np.any(index < 0) or np.any(index[:, 0] >= ink.shape[1])
            or np.any(index[:, 1] >= ink.shape[0])):
        result["reason"] = "OLD_LINE_EXTENDS_OUTSIDE_CURRENT_SOURCE_EVIDENCE"
        return result
    distance, nearest = distance_transform_edt(~ink, return_indices=True)
    owners = labels[nearest[0, index[:, 1], index[:, 0]],
                    nearest[1, index[:, 1], index[:, 0]]]
    support = _support(dense, distance, origin)
    coverage = _line_source_coverage(proposal, line)
    checks = {
        "complete_simple_source_chain": bool(certificate["pass"]),
        "whole_old_LINE_on_same_original_ink_component": bool(np.all(owners == component)),
        "whole_old_LINE_passes_unchanged_source_gate": support["pass"],
        "not_a_block_member": line["kind"] == "LINE",
    }
    result.update(
        checks=checks, source_component_label=int(component),
        original_source_crop_array_sha256=source["original_source_crop_array_sha256"],
        old_line_source_support=support, old_line_coverage=coverage,
        pass_=all(checks.values()),
        source_pixels_modified=False, old_line_remaining_intervals=[],
        basis="whole original ink component responsibility; not parallel-overlap intervals",
    )
    result["pass"] = result.pop("pass_")
    return result


def adopt_checkpoint_paths(gray, proposals, prior_objects):
    """Apply whole-object ownership and duplicate gates to live discoveries.

    This also protects already adequate old lines: a more complex polyline is
    not a new recovery when the old editable line already covers the source.
    """
    prior = {obj["id"]: obj for obj in prior_objects}
    if len(prior) != len(prior_objects):
        raise ValueError("CONNECTION_CHECKPOINT_DUPLICATE_PRIOR_ID")
    adopted, decisions, retired = [], [], set()
    for candidate in proposals:
        if candidate["kind"] != "CONNECTION_PATH":
            raise ValueError("CONNECTION_CHECKPOINT_NONPATH_PROPOSAL")
        obj = deepcopy(candidate)
        row = {"id": obj["id"], "adopted": False, "reasons": [],
               "retired_ids": [], "existing_adequate_ids": [], "whole_line_certificates": [],
               "shared_source_core_checks": []}
        active = [p for p in prior_objects if p["id"] not in retired] + adopted
        row.update(_connection_path_responsibility(gray, obj, active))
        if row["existing_adequate_ids"]:
            row["decision"] = "RETAIN_EXISTING_COMPLETE_PATH_NO_DUPLICATE"
            decisions.append(row)
            continue
        members = _existing_line_members(active)
        overlap, neighbors = _retirement_proposals(obj["geometry"], members)
        row["parallel_overlap_records"] = overlap
        row["unchanged_crossing_neighbors"] = neighbors
        component_contacts = _simple_component_line_contacts(gray, obj, members)
        row["same_simple_source_component_line_contacts"] = component_contacts
        proposed_retirements = []
        ownership_ids = sorted(set(component_contacts)
                               | {conflict["prior_object_id"] for conflict in overlap})
        for oid in ownership_ids:
            old = prior.get(oid)
            if old is None or old["kind"] != "LINE":
                row["reasons"].append("EXISTING_BLOCK_MEMBER_OR_NONLINE_RESPONSIBILITY_PENDING")
                continue
            proof = _whole_line_responsibility(gray, obj, old)
            row["whole_line_certificates"].append(proof)
            if not proof["pass"]:
                row["reasons"].append("WHOLE_OLD_LINE_RESPONSIBILITY_NOT_CERTIFIED")
            elif proof["old_line_coverage"]["already_complete_within_existing_line_tolerances"]:
                row["existing_adequate_ids"].append(oid)
            else:
                proposed_retirements.append(oid)
        arc_overlap = _existing_arc_overlap(obj, active)
        row["arc_overlap_records"] = arc_overlap
        if arc_overlap:
            row["reasons"].append("EXISTING_NATIVE_ARC_RESPONSIBILITY_PENDING")
        if row["existing_adequate_ids"]:
            row["decision"] = "RETAIN_EXISTING_ADEQUATE_LINE_NO_DUPLICATE"
        elif row["reasons"]:
            row["decision"] = "PENDING_WHOLE_OBJECT_RESPONSIBILITY"
        else:
            row.update(adopted=True, retired_ids=sorted(set(proposed_retirements)),
                       decision="REPLACE_WHOLE_INCOMPLETE_LINES" if proposed_retirements else "ADD_COMPLETE_PATH")
            retired.update(proposed_retirements)
            obj["source_evidence"]["checkpoint_responsibility_resolution"] = deepcopy(row)
            adopted.append(obj)
        decisions.append(row)
    return {
        "objects": adopted, "retired_ids": sorted(retired), "decisions": decisions,
        "uncertainties": [{"reason": "CONNECTION_EDIT_RESPONSIBILITY_PENDING", **row}
                          for row in decisions if row.get("decision") == "PENDING_WHOLE_OBJECT_RESPONSIBILITY"],
        "source_pixels_modified": False,
        "partial_old_entity_retirement_permitted": False,
    }


def _relative_evidence_path(path, evidence_root):
    """Use the portable evidence protocol, independent of host separators."""
    return path.relative_to(evidence_root).as_posix()


def run_connection_checkpoint(job, prepared, binding, *, progress_callback=None):
    """Formal native pipeline branch: captured observations, local fresh fits.

    The full decoded source stays available for context and audit; recognition
    is restricted to the declared bounded windows. No OCR or general object
    reconstruction stage is invoked, and no old audit authorizes new output.
    """
    from .cad_io import cold_audit, render_saved
    from .connection_checkpoint_cad import write_checkpoint_dxf
    from .quality_review import _box, _intersects, run_quality_review

    started = time.perf_counter()
    manifest, baseline, texts, baseline_path = load_captured_checkpoint(binding)
    if (prepared.source_sha256 != manifest["source_sha256"]
            or list(prepared.working_roi) != manifest["roi_xyxy_px"]
            or job.dpi != manifest["dpi"]
            or prepared.manifest["working_array_sha256"] != binding["source"]["source_array_sha256"]
            or job.input_path.resolve() != Path(binding["source"]["path"]).resolve()):
        raise ValueError("CONNECTION_CHECKPOINT_PREPARED_SOURCE_MISMATCH")
    if job.output_path.exists():
        raise FileExistsError("CONNECTION_CHECKPOINT_DXF_EXISTS")
    gray, roi, out = prepared.gray, prepared.working_roi, job.evidence_dir
    out.mkdir(parents=True, exist_ok=True)
    trace = []
    protected_ids, baseline_scopes, source_assets = set(), [], []
    verified_text_observations = None
    if binding.get("baseline_evidence") is not None:
        from .checkpoint_baseline import (
            capture_baseline_evidence,
            materialize_baseline_graphs,
            verify_baseline_evidence,
        )

        copied = capture_baseline_evidence(binding["baseline_evidence"], out / "baseline_preservation")
        current = verify_baseline_evidence(
            copied, baseline_path, baseline, job.input_path,
            prepared.source_sha256, binding["parameters"], gray=gray,
        )
        protected_ids = set(current["protected_object_ids"])
        baseline_scopes = materialize_baseline_graphs(copied, out, baseline, protected_ids)
        save_json(out / "baseline_preservation_checks.json", {
            key: value for key, value in current.items() if key not in ("manifest", "root")
        })
        source_assets.extend((out / "baseline_preservation").rglob("*"))
        source_assets.extend((out / "baseline_observations").rglob("*"))
        source_assets.append(out / "baseline_preservation_checks.json")
    if binding.get("source_observations") is not None:
        from .checkpoint_text_observations import capture_source_observations, verify_source_observations

        copied = capture_source_observations(
            binding["source_observations"]["path"], out / "source_observations",
            job.input_path, prepared.source_sha256, binding["parameters"],
        )
        verified_text_observations = verify_source_observations(
            copied, job.input_path, prepared.source_sha256,
            binding["parameters"], gray=gray,
        )
        save_json(out / "source_observations_verified.json", verified_text_observations)
        source_assets.extend((out / "source_observations").rglob("*"))
        source_assets.append(out / "source_observations_verified.json")

    def progress(stage, fraction):
        check_cancel(stage)
        trace.append({"stage": stage, "fraction": fraction,
                      "elapsed_wall_seconds": time.perf_counter() - started,
                      "job_id": job.job_id})
        save_json(out / "pipeline_trace.json", trace)
        if progress_callback:
            progress_callback(stage, fraction)

    scopes = [window["context_roi"] for window in manifest["windows"]]
    imported = deepcopy(prepared.manifest)
    imported["connection_checkpoint"] = {
        "manifest_sha256": binding["manifest"]["sha256"],
        "baseline_dxf_sha256": binding["baseline_dxf"]["sha256"],
        "context_rois": scopes,
    }
    save_json(out / "import_manifest.json", imported)
    save_json(out / "connection_checkpoint_binding.json", binding)
    selected = [obj for obj in baseline["objects"]
                if obj["id"] in protected_ids or any(_intersects(_box(obj), scope) for scope in scopes)]
    progress("CAPTURED_SOURCE_AND_EXISTING_OBSERVATIONS_VERIFIED_NO_OCR", 0.05)
    candidates, uncertainties, scope_rows, discovery_scopes = [], [], [], []
    first_scope = {}
    for index, window in enumerate(manifest["windows"]):
        progress("BOUNDED_ORIGINAL_SOURCE_CONNECTION_GRAPH", 0.08 + 0.48 * index / len(scopes))
        scope_dir = out / "connections" / "scopes" / f"{index:03d}"
        local_texts = deepcopy(texts)
        local_texts["roi_xyxy_px"] = window["context_roi"]
        save_json(scope_dir / "text_scope_derivation.json", {
            "original_text_file_sha256": binding["text_observations"]["sha256"],
            "parent_roi_xyxy_px": manifest["roi_xyxy_px"],
            "derived_roi_xyxy_px": window["context_roi"],
            "all_region_rows_unchanged": True, "new_OCR_calls": 0,
        })
        observation_options = {}
        if verified_text_observations is not None:
            observation_options["verified_text_observations"] = verified_text_observations
        raw = extract_connections(gray, window["context_roi"], baseline["objects"],
                                  scope_dir / "discovery", text_regions=local_texts,
                                  **observation_options)
        for obj in raw["objects"]:
            candidates.append(obj)
            first_scope.setdefault(obj["id"], index)
        for issue in raw["uncertainties"]:
            uncertainties.append({**issue, "checkpoint_window_index": index})
        scope_rows.append({"window_index": index, "reporting_label": window["id"],
                           "target_roi": window["target_roi"], "context_roi": window["context_roi"],
                           "proposal_ids": [obj["id"] for obj in raw["objects"]],
                           "uncertainty_count": len(raw["uncertainties"]),
                           "new_OCR_calls": 0})
        graph = scope_dir / "discovery/source_graph.json"
        discovery = scope_dir / "discovery/connections.json"
        discovery_scopes.append({
            "roi_xyxy_px": window["context_roi"],
            "graph_path": _relative_evidence_path(graph, out), "graph_sha256": file_sha(graph),
            "discovery_path": _relative_evidence_path(discovery, out), "discovery_sha256": file_sha(discovery),
            "object_ids": [],
        })
    progress("WHOLE_OBJECT_OWNERSHIP_AND_PRIOR_ENTITY_PROTECTION", 0.60)
    adoption = adopt_checkpoint_paths(gray, candidates, baseline["objects"])
    save_json(out / "connections/completion_result.json", adoption)
    retained = {obj["id"] for obj in selected} - set(adoption["retired_ids"])
    for obj in adoption["objects"]:
        discovery_scopes[first_scope[obj["id"]]]["object_ids"].append(obj["id"])
    # A retained old retrace also needs a current observed graph; it cannot
    # inherit its old cold-audit allowance just because its entity is unchanged.
    for obj in selected:
        if obj["id"] not in retained:
            continue
        if any(row.get("local_cycle_cover_evidence") for row in obj.get("source_evidence", {}).get("crossing_evidence", [])):
            if obj["id"] in protected_ids:
                continue  # Captured original graph is re-proved by the cold audit below.
            if obj["id"] not in first_scope:
                raise ValueError("RETAINED_RETRACE_NEEDS_CURRENT_BOUNDED_GRAPH")
            discovery_scopes[first_scope[obj["id"]]]["object_ids"].append(obj["id"])
    discovery_scopes.extend(baseline_scopes)
    if len(discovery_scopes) > 8:
        raise ValueError("BOUNDED_NEW_AND_PRESERVED_GRAPH_SCOPE_BUDGET_EXCEEDED")
    progress("ACTUAL_NATIVE_CHECKPOINT_DXF_SAVE", 0.72)
    meta = write_checkpoint_dxf(baseline_path, baseline, retained, adoption["objects"],
                                job.output_path, roi, job.dpi, prepared.source_sha256,
                                evidence_directory=out)
    meta["connection_discovery_scopes"] = discovery_scopes
    save_json(job.output_path.with_suffix(".objects.json"), meta)
    objects = meta["objects"]
    progress("SAVED_DXF_COLD_READ_AND_SOURCE_AUDIT", 0.81)
    audit = cold_audit(job.output_path, gray, roi, job.dpi, out / "cold_audit.json")
    progress("INDEPENDENT_SAVED_DXF_RENDER", 0.88)
    preview = job.output_path.with_suffix(".png")
    render = render_saved(job.output_path, preview, roi, job.dpi)
    issues = uncertainties + adoption["uncertainties"]
    save_json(out / "assembly.json", {"objects": objects, "uncertainties": issues,
                                     "bounded_windows": scope_rows})
    progress("CURRENT_SAVED_LOCAL_SOURCE_REVIEW", 0.94)
    quality = run_quality_review(job.output_path, gray, roi, job.dpi, objects, texts,
                                 issues, imported, out, cold_audit=audit, render=render)
    if source_assets:
        from .review_binding import verify_saved_review

        quality["evidence_assets"].extend({
            "relative_path": path.relative_to(out).as_posix(), "sha256": file_sha(path)
        } for path in sorted(set(source_assets)) if path.is_file())
        save_json(out / "quality_review.json", quality)
        if not verify_saved_review(out / "quality_review.json", job.output_path, objects,
                                    imported, source_path=job.input_path)["valid"]:
            raise ValueError("CURRENT_CAPTURED_SOURCE_PROOF_BINDING_REJECTED")
    report = {
        "status": "LOCAL_NO_GO", "formal_entry_called_new_pipeline": True,
        "pipeline_module": __name__, "job_id": job.job_id, "job_config": job.payload(),
        "source_sha256": prepared.source_sha256, "dxf_path": str(job.output_path),
        "preview_path": str(preview), "evidence_dir": str(out),
        "source_gate_pass": audit["source_gate_pass"],
        "native_modelspace_types": audit["formal_modelspace_types"],
        "expanded_native_types": audit["expanded_formal_types"],
        "bounded_windows": scope_rows,
        "new_complete_path_ids": [obj["id"] for obj in adoption["objects"]],
        "retired_whole_line_ids": adoption["retired_ids"],
        "preserved_old_object_ids": sorted(retained),
        "preserved_prior_delta_path_ids": sorted(protected_ids),
        "verified_raw_text_observations": len(verified_text_observations["observations"])
        if verified_text_observations is not None else 0,
        "old_objects_outside_selected_contexts_not_exported": len(baseline["objects"]) - len(selected),
        "existing_entities_partially_erased": False, "new_OCR_calls": 0,
        "full_region_conversion_runs": 0, "engineering_semantics_required": False,
        "source_pixels_modified": False, "existing_tolerances_not_relaxed": True,
        "old_adoption_or_review_used_to_authorize_new_paths": False,
        "source_to_working_to_CAD": imported["coordinates"],
        "source_import_manifest": str(out / "import_manifest.json"),
        "original_source_unchanged": file_sha(job.input_path) == prepared.source_sha256,
        "quality_path": str(out / "quality_review.json"), "quality_summary": quality["summary"],
        "issue_path": str(out / "quality_issues.json"),
        "source_roi_path": str(out / "quality_source_roi.png"),
        "review_binding_sha256": quality["binding"]["binding_sha256"],
        "render": render, "CAD_GUI": "NOT_RUN_BY_PIPELINE", "engineer_UAT": "NOT_RUN",
        "full_page_or_production_GO": False, "unit": "paper_mm",
        "machine_wall_seconds": time.perf_counter() - started,
    }
    report_path = job.output_path.with_suffix(".report.json")
    save_json(report_path, report)
    progress("COMPLETE_BOUNDED_NATIVE_CANDIDATE_WITH_EXPLICIT_UNCERTAINTIES", 1.0)
    return {**report, "report_path": str(report_path), "objects": objects}
