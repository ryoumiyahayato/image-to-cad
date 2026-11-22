"""Bounded native connection reconstruction from captured source checkpoints.

The checkpoint is a source/observation and preservation contract, never an
adoption whitelist. Every new path is discovered from unchanged pixels and
passes the current native writer, cold source audit and saved review gates.
"""

from copy import deepcopy
from pathlib import Path
import time

from .connection_checkpoint_inputs import (
    capture_checkpoint,
    load_captured_checkpoint,
    verify_captured_checkpoint,
)
from .connections import extract_connections
from .contracts import save_json
from .connection_adoption import adopt_connection_paths as adopt_checkpoint_paths
from .execution import check_cancel, file_sha

__all__ = [
    "capture_checkpoint",
    "load_captured_checkpoint",
    "verify_captured_checkpoint",
    "adopt_checkpoint_paths",
    "run_connection_checkpoint",
]


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
