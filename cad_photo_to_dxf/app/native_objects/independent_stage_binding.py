"""Read-only binding of attached-stage claims to published files.

Declarations select a verification scope; neither a producer PASS nor an ID
difference supplies source responsibility. Historical receipts keep their own
contract identity. This module does not import discovery or its decisions.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath

from PIL import Image

from .independent_saved_geometry_audit import _exact, sha256

SCHEMA = "independent-attached-stage-scope-binding-v3"
JOINT_PLAN = "source-attached-stroke-joint-plan-v3"
JOINT_ADOPTION = "source-attached-stroke-joint-adoption-v3"
JOINT_NATIVE = "source-attached-stroke-joint-native-v3"
JOINT_CONTRACT = "attached-stroke-joint-evidence-contract-v3"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _same(left, right):
    return _exact(left) == _exact(right)


def _record(path):
    return {"path": str(path), "sha256": sha256(path), "bytes": Path(path).stat().st_size}


def resolve_stage_inputs(dxf, *, plan=None, adoption=None, publication=None, execution_request=None):
    """Only discover receipts beside the selected actual drawing; record paths."""
    dxf = Path(dxf)
    native = dxf.with_suffix(".native")
    paths = {
        "plan": Path(plan) if plan else native / "evidence/attached_strokes/plan.json",
        "adoption": Path(adoption) if adoption else native / "evidence/attached_strokes/adoption.json",
        "publication": Path(publication) if publication else dxf.with_suffix(".export.json"),
        "execution_request": Path(execution_request) if execution_request else None,
    }
    if paths["execution_request"] is None and paths["publication"].is_file():
        try:
            job_id = _read(paths["publication"]).get("job_id")
            # job_id is an identifier, never a path supplied by the receipt.
            if isinstance(job_id, str) and Path(job_id).name == job_id and job_id not in (".", ".."):
                job = dxf.parent.parent / "jobs" / job_id
                state = _read(job / "state.json")
                attempt = state.get("attempt")
                if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0:
                    paths["execution_request"] = job / "attempts" / f"{attempt:04d}" / "request.json"
        except (OSError, ValueError, TypeError):
            pass
    return paths


def _contract_scope(plan, adoption):
    schema = plan.get("schema")
    if schema == JOINT_PLAN:
        if adoption.get("schema") != JOINT_ADOPTION:
            return None
        return "CURRENT_JOINT_V3"
    if schema == "source-attached-stroke-graph-plan-v1" and adoption.get("schema") == "source-attached-stroke-adoption-v1":
        return "HISTORICAL_A_V1"
    if schema == "source-attached-stroke-graph-plan-v2" and adoption.get("schema") == "source-attached-stroke-adoption-v2":
        raw = "attached_stroke_ink.py" in plan.get("additional_producer_sha256", {})
        numeric = "numerical_contract" in plan
        if raw and not numeric:
            return "HISTORICAL_INK_V2"
        if numeric and not raw:
            return "HISTORICAL_NUMERICAL_V2"
    return None


def _path_ids(rows, key):
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("INVALID_STAGE_ROWS")
    ids = [row.get(key) for row in rows]
    if not all(isinstance(value, str) and value for value in ids):
        raise ValueError("INVALID_STAGE_OBJECT_ID")
    return ids


def _geometry_from_path(path, kind):
    representation = path.get("representation", {})
    points = representation.get("points", [])
    if kind == "LINE" and len(points) == 2 and not any(representation.get("bulges", [])) and representation.get("closed") is False:
        return {"start": points[0], "end": points[1]}
    if kind == "CONNECTION_PATH":
        return representation
    return None


def _checkpoint_binding(*, dxf_path, request, publication, plan, adoption, scope,
                        source_root, manifest_path=None, continuation_path=None):
    """Bind captured upstream state to current files without executing producers.

    This is a provenance and integrity review. The numerical cold replay and
    original-pixel responsibility are separate, and no pipeline PASS is reused.
    """
    evidence = Path(dxf_path).with_suffix(".native") / "evidence"
    continuation = Path(continuation_path) if continuation_path else evidence / "source_stage_continuation.json"
    captured = request.get("source_stage_checkpoint")
    published = publication.get("evidence_files", {})
    if captured is None:
        unexpected = continuation.exists() or "evidence/source_stage_continuation.json" in published or manifest_path is not None
        return {"status": "FAIL" if unexpected else "NOT_APPLICABLE_FRESH_UPSTREAM_PATH",
                "reason": "CONTINUATION_WITHOUT_CAPTURED_REQUEST" if unexpected else "NO_SOURCE_STAGE_CHECKPOINT_REQUESTED",
                "scope": "Fresh upstream path is not represented as checkpoint continuation"}
    manifest = Path(manifest_path) if manifest_path else Path(captured["manifest_path"])
    before = {str(manifest): sha256(manifest), str(continuation): sha256(continuation)}
    value, receipt = _read(manifest), _read(continuation)
    checks = {
        "current_joint_execution": scope == "CURRENT_JOINT_V3",
        "captured_schema": captured.get("schema") == "captured-source-stage-checkpoint-v1",
        "captured_manifest_file_hash": captured.get("manifest_sha256") == before[str(manifest)],
        "manifest_schema": value.get("schema") == "source-stage-checkpoint-pre-attached-v1"
                           and value.get("boundary") == "AFTER_SHORT_CONTACT_BEFORE_ATTACHED",
        "continuation_schema": receipt.get("schema") == "source-stage-continuation-execution-v1",
        "continuation_manifest_file_hash": receipt.get("checkpoint_manifest_sha256") == before[str(manifest)],
        "published_continuation_hash": published.get("evidence/source_stage_continuation.json") == before[str(continuation)],
        "explicit_execution_mode": captured.get("execution_mode") == receipt.get("execution_mode")
                                   == "SOURCE_STAGE_CHECKPOINT_CONTINUATION",
        "captured_request_source": captured.get("source_sha256") == request.get("source_sha256")
                                   == value.get("source", {}).get("source_sha256"),
        "captured_request_parameters": _same(captured.get("parameters"), request.get("parameters"))
                                       and _same(value.get("source", {}).get("parameters"), request.get("parameters")),
        "paper_units": value.get("source", {}).get("unit") == "paper_mm",
        "receipt_exact_upstream_identity": all(_same(receipt.get(key), value.get(key)) for key in
            ("source", "producer_closure", "runtime_and_resources", "upstream_state_sha256", "reused_stages")),
        "captured_execution_boundary": _same(captured.get("reused_stages"), value.get("reused_stages"))
                                       and _same(captured.get("downstream_required"), value.get("downstream_required")),
        "no_old_dxf_or_attached_reuse": value.get("old_DXF_read") is False
                                      and receipt.get("old_DXF_read") is False
                                      and receipt.get("old_attached_result_reused") is False,
        "no_upstream_refit_or_recognition": all(receipt.get(key) == 0 for key in
                                               ("new_upstream_fits", "new_OCR_calls", "new_model_inferences")),
    }
    artifacts, names = [], []
    for row in value.get("artifacts", []):
        name = row.get("path")
        rel = PurePosixPath(name) if isinstance(name, str) else None
        safe = (rel is not None and bool(rel.parts) and not rel.is_absolute()
                and ".." not in rel.parts and "\\" not in name)
        path = manifest.parent.joinpath(*rel.parts) if safe else None
        safe = bool(safe and manifest.parent.resolve() in path.resolve().parents
                    and not any(p.is_symlink() for p in (path, *path.parents) if p != manifest.parent.parent))
        actual = _record(path) if safe and path.is_file() else None
        okay = actual is not None and actual["sha256"] == row.get("sha256") and actual["bytes"] == row.get("bytes")
        names.append(name)
        artifacts.append({"relative_path": name, "pass": okay, "actual": actual})
        if actual:
            before[actual["path"]] = actual["sha256"]
    checks["all_manifest_members_exact"] = bool(artifacts) and all(row["pass"] for row in artifacts)
    checks["manifest_member_set_exact"] = (len(names) == len(set(names))
        and {p.relative_to(manifest.parent).as_posix() for p in manifest.parent.rglob("*") if p.is_file()}
            == set(names) | {manifest.name})
    state = _read(manifest.parent / "upstream_state.json")
    state_digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    checks["complete_upstream_state_digest"] = state_digest == value.get("upstream_state_sha256")
    old_rows = state.get("objects", [])
    old_ids = _path_ids(old_rows, "id")
    prior = plan.get("prior_object_bindings", [])
    old_map = {row["id"]: row for row in old_rows}
    checks["complete_prior_count_and_ids"] = (len(set(old_ids)) == len(old_ids)
        and receipt.get("prior_object_count") == len(old_ids) == len(prior)
        and set(old_ids) == set(_path_ids(prior, "id")))
    checks["complete_prior_geometry_and_responsibility"] = all(
        row["id"] in old_map and all(_same(row.get(key), old_map[row["id"]].get(key))
                                    for key in ("id", "kind", "layer", "geometry"))
        and all(_same(val, old_map[row["id"]].get("source_evidence", {}).get(key))
                for key, val in row.get("source_evidence", {}).items()) for row in prior)
    closure = value.get("producer_closure", {})
    reused_files = {**closure.get("historical_worker_recorded_native_files", {}),
                    **closure.get("supplemental_frozen_source_snapshot_files", {})}
    checks["current_reused_producer_file_bytes"] = bool(reused_files) and all(
        (source_root / name).is_file() and sha256(source_root / name) == expected
        for name, expected in reused_files.items())
    checks["current_checkpoint_validator_bytes"] = value.get("checkpoint_validator_sha256") == sha256(
        source_root / "app/native_objects/source_stage_checkpoint.py")
    executors = value.get("continuation_executor_sha256", {})
    checks["current_continuation_executor_bytes"] = bool(executors) and all(
        (source_root / name).is_file() and sha256(source_root / name) == expected for name, expected in executors.items())
    downstream = receipt.get("downstream", {})
    checks["downstream_stage_set"] = set(downstream) == set(value.get("downstream_required", []))
    checks["fresh_source_graph"] = downstream.get("fresh_source_graph") == "EXECUTED_REBUILT_FROM_UNCHANGED_PIXELS"
    for key in ("attached_ink", "all_prior_contacts", "joint_numerical_contract"):
        row = downstream.get(key, {})
        checks[key + "_current_stage_binding"] = (
            row.get("status") == "EXECUTED_CURRENT_PLANNER"
            and row.get("plan_sha256") == published.get("evidence/attached_strokes/plan.json")
            and row.get("adoption_sha256") == published.get("evidence/attached_strokes/adoption.json")
            and row.get("adopted_object_count") == len(adoption.get("objects", []))
            and row.get("candidate_components") == len(plan.get("components", []))
            and _same(row.get("stage_execution"), adoption.get("stage_execution")))
    saved = downstream.get("native_save", {})
    checks["current_saved_dxf"] = saved.get("status") == "EXECUTED" and saved.get("dxf_sha256") == sha256(dxf_path)
    for key, name in (("saved_source_cold_read", "cold_audit.json"), ("current_input_quality_review", "quality_review.json")):
        row, path = downstream.get(key, {}), evidence / name
        actual = _record(path)
        before[str(path)] = actual["sha256"]
        checks[key + "_actual_receipt"] = (row.get("status") == "EXECUTED"
            and row.get("receipt_sha256") == actual["sha256"] == published.get("evidence/" + name))
        if key == "saved_source_cold_read":
            checks["cold_read_result_recorded_without_promotion"] = _read(path).get("source_gate_pass") == row.get("source_gate_pass")
    checks["current_render_executed"] = downstream.get("render") == "EXECUTED_CURRENT_SAVED_DXF"
    checks["upstream_independent_protection_not_claimed"] = downstream.get("independent_old_content_check") == "NOT_RUN"
    after = {path: sha256(path) for path in before}
    checks["checkpoint_inputs_unchanged_during_check"] = before == after
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "failed_checks": [key for key, okay in checks.items() if not okay],
            "manifest": _record(manifest), "continuation": _record(continuation),
            "checked_artifacts": artifacts, "inputs_before": before, "inputs_after": after,
            "prior_object_count": len(old_ids), "scope": "Source state / dependency / current execution binding only",
            "runtime_identity_bound_to_manifest": True,
            "runtime_environment_revalidated_by_this_checker": False,
            "source_ownership_authorized_by_this_check": False}


def audit_stage_binding(*, dxf_path, metadata_path, source_path, roi, dpi,
                        plan_path=None, adoption_path=None, publication_path=None,
                        execution_request_path=None, current_source_root=None,
                        source_stage_manifest_path=None, source_stage_continuation_path=None):
    paths = resolve_stage_inputs(dxf_path, plan=plan_path, adoption=adoption_path,
                                 publication=publication_path, execution_request=execution_request_path)
    result = {
        "schema": SCHEMA, "status": "NOT_RUN", "stage_execution_status": "NOT_ESTABLISHED",
        "contract_scope": None, "receipt_paths": {k: str(v) if v else None for k, v in paths.items()},
        "declared_adopted_target_ids": [], "bound_declared_target_ids": [],
        "complete_candidate_path_ids": [], "unadopted_candidate_path_ids": [],
        "complete_candidates": [], "checks": {}, "errors": [],
        "producer_adoption_PASS_is_source_proof": False,
        "source_complete_responsibility": "NOT_ESTABLISHED_BY_STAGE_DECLARATIONS",
    }
    missing = [key for key, value in paths.items() if value is None or not value.is_file()]
    if missing:
        result["missing_receipts"] = missing
        result["reason"] = "STAGE_OR_PUBLICATION_RECEIPT_NOT_AVAILABLE"
        return result
    try:
        plan, adoption, publication, request = (_read(paths[key]) for key in
                                                ("plan", "adoption", "publication", "execution_request"))
        metadata = _read(metadata_path)
        checks = result["checks"]
        result["plan_canonical_sha256"] = digest(plan)
        result["input_records"] = {key: _record(value) for key, value in paths.items()}
        result["input_records"].update(dxf=_record(dxf_path), metadata=_record(metadata_path), source=_record(source_path))
        scope = _contract_scope(plan, adoption)
        result["contract_scope"] = scope
        checks["known_unambiguous_contract"] = scope is not None
        checks["adoption_embedded_plan_exact"] = _same(adoption.get("plan"), plan)
        checks["plan_prior_bindings_digest"] = plan.get("prior_object_bindings_sha256") == digest(plan.get("prior_object_bindings"))
        checks["adoption_prior_bindings_exact"] = _same(adoption.get("prior_object_bindings"), plan.get("prior_object_bindings"))
        checks["source_unmodified"] = all(plan.get(k) is False for k in ("source_pixels_modified", "original_source_pixels_modified"))
        checks["no_retired_prior_objects"] = adoption.get("retired_ids") == []
        source_hash = sha256(source_path)
        checks["external_source_identity"] = all(value == source_hash for value in (
            adoption.get("source_sha256"), metadata.get("source_sha256"),
            publication.get("source_sha256"), request.get("source_sha256")))
        checks["external_roi"] = all(value == list(roi) for value in (
            plan.get("roi_xyxy_px"), adoption.get("roi_xyxy_px"), metadata.get("roi_xyxy_px"),
            request.get("parameters", {}).get("roi")))
        checks["external_dpi"] = metadata.get("dpi") == dpi == request.get("parameters", {}).get("dpi")
        checks["orientation_and_units"] = request.get("parameters", {}).get("orientation") == 0 and metadata.get("unit") == "paper_mm"
        crop = plan.get("original_source_crop_xyxy_px")
        with Image.open(source_path) as image:
            valid_crop = (isinstance(crop, list) and len(crop) == 4
                          and all(isinstance(v, int) and not isinstance(v, bool) for v in crop)
                          and 0 <= crop[0] < crop[2] <= image.width
                          and 0 <= crop[1] < crop[3] <= image.height)
            checks["original_crop_bounds"] = valid_crop
            checks["original_crop_pixels_exact"] = valid_crop and hashlib.sha256(
                image.convert("L").crop(crop).tobytes()).hexdigest() == plan.get("original_source_crop_array_sha256")
        algorithm = request.get("algorithm", {})
        file_map = algorithm.get("files", {})
        checks["algorithm_file_digest"] = bool(file_map) and algorithm.get("sha256") == digest(file_map)
        checks["published_algorithm_exact"] = _same(publication.get("algorithm"), algorithm)
        checks["published_dxf_hash"] = publication.get("DXF_sha256") == sha256(dxf_path)
        checks["published_metadata_hash"] = publication.get("files", {}).get(Path(metadata_path).name) == sha256(metadata_path)
        published_evidence = publication.get("evidence_files", {})
        checks["published_plan_hash"] = published_evidence.get("evidence/attached_strokes/plan.json") == sha256(paths["plan"])
        checks["published_adoption_hash"] = published_evidence.get("evidence/attached_strokes/adoption.json") == sha256(paths["adoption"])
        producer_map = {"attached_stroke_graph.py": plan.get("producer_sha256"),
                        **plan.get("additional_producer_sha256", {})}
        checks["producer_matches_execution"] = all(
            isinstance(value, str) and file_map.get("app/native_objects/" + name) == value
            for name, value in producer_map.items())
        result["producer_dependencies"] = producer_map
        result["algorithm_identity"] = algorithm.get("sha256")
        result["recorded_execution_git"] = algorithm.get("git")

        adopted_paths = plan.get("paths", [])
        path_ids = _path_ids(adopted_paths, "stroke_id")
        adopted_objects = adoption.get("objects", [])
        object_ids = _path_ids(adopted_objects, "id")
        decisions = adoption.get("decisions", [])
        decision_ids = _path_ids(decisions, "id")
        result["declared_adopted_target_ids"] = object_ids
        checks["adopted_ids_unique"] = len(set(path_ids)) == len(path_ids) and len(set(object_ids)) == len(object_ids)
        checks["adopted_path_object_decision_ids_exact"] = path_ids == object_ids == decision_ids
        checks["adopted_decisions_are_explicit"] = all(row.get("adopted") is True for row in decisions)
        candidates = []
        for component in plan.get("components", []):
            for path in component.get("candidate_paths", []):
                candidates.append({"component_id": component.get("component_id"), "path": path,
                                   "component_status": component.get("status"),
                                   "failed_adoption_gates": component.get("failed_adoption_gates", []),
                                   "reason": component.get("reason")})
        candidate_ids = _path_ids([row["path"] for row in candidates], "stroke_id")
        checks["candidate_ids_unique"] = len(set(candidate_ids)) == len(candidate_ids)
        result["complete_candidate_path_ids"] = candidate_ids
        result["unadopted_candidate_path_ids"] = [oid for oid in candidate_ids if oid not in object_ids]
        result["complete_candidates"] = [{"path_id": row["path"]["stroke_id"],
            "component_id": row["component_id"], "path_sha256": digest(row["path"]),
            "representation": row["path"].get("representation"),
            "scope": "DECLARED_COMPLETE_CANDIDATE_NOT_SAVED_TARGET" if row["path"]["stroke_id"] not in object_ids else "ADOPTED_PATH_CANDIDATE_COPY",
            "component_status": row["component_status"], "failed_adoption_gates": row["failed_adoption_gates"],
            "reason": row["reason"]} for row in candidates]
        sidecar_rows = metadata.get("objects", [])
        sidecar_ids = _path_ids(sidecar_rows, "id")
        checks["sidecar_ids_unique"] = all(count == 1 for count in Counter(sidecar_ids).values())
        sidecar = {row["id"]: row for row in sidecar_rows}
        path_map = {row["stroke_id"]: row for row in adopted_paths}
        native_schema = JOINT_NATIVE if scope == "CURRENT_JOINT_V3" else (
            "source-attached-stroke-native-v1" if scope == "HISTORICAL_A_V1" else "source-attached-stroke-native-v2")
        target_rows = []
        for index, obj in enumerate(adopted_objects):
            oid = obj["id"]
            path = path_map.get(oid)
            native = obj.get("source_evidence", {}).get("attached_stroke_graph", {})
            row_checks = {
                "saved_sidecar_object_exact": oid in sidecar and _same(sidecar[oid], obj),
                "path_present": path is not None,
                "path_index": native.get("path_index") == index,
                "native_contract_schema": native.get("schema") == native_schema,
                "plan_digest": native.get("plan_sha256") == result["plan_canonical_sha256"],
                "path_digest": path is not None and native.get("path_sha256") == digest(path),
                "embedded_path_exact": path is not None and _same(native.get("path"), path),
                "finite_geometry_declaration_exact": path is not None and _same(obj.get("geometry"), _geometry_from_path(path, obj.get("kind"))),
                "source_identity": native.get("source_sha256") == source_hash,
            }
            target_rows.append({"object_id": oid, "checks": row_checks, "pass": all(row_checks.values())})
        result["declared_target_stage_bindings"] = target_rows
        checks["declared_targets_bound_to_sidecar_and_stage"] = all(row["pass"] for row in target_rows)
        result["bound_declared_target_ids"] = [row["object_id"] for row in target_rows if row["pass"]]
        source_root = Path(current_source_root) if current_source_root else Path(__file__).resolve().parents[2]
        if scope == "CURRENT_JOINT_V3":
            execution = adoption.get("stage_execution", {})
            checks["joint_complete_producer_set"] = set(producer_map) == {
                "attached_stroke_graph.py", "attached_stroke_ink.py",
                "attached_stroke_contacts.py", "attached_stroke_numeric.py"}
            checks["joint_contract_version"] = plan.get("joint_contract", {}).get("version") == JOINT_CONTRACT
            checks["joint_execution_receipt"] = (execution.get("stage") == "complete_attached_strokes"
                and execution.get("status") == "EXECUTED"
                and execution.get("source_graph_input") in ("REBUILT_FROM_ORIGINAL", "CALLER_SUPPLIED_BOUND_ORIGINAL_GRAPH")
                and execution.get("adopted_path_count") == len(adopted_paths)
                and execution.get("candidate_path_count") == len(candidates)
                and execution.get("producer_sha256") == plan.get("producer_sha256")
                and _same(execution.get("additional_producer_sha256"), plan.get("additional_producer_sha256"))
                and _same(execution.get("joint_contract"), plan.get("joint_contract")))
            checks["current_joint_producer_dependencies"] = all(
                (source_root / "app/native_objects" / name).is_file()
                and sha256(source_root / "app/native_objects" / name) == value
                for name, value in producer_map.items())
            result["stage_execution_status"] = "EXECUTED" if checks["joint_execution_receipt"] else "NOT_ESTABLISHED"
        elif scope is not None:
            result["stage_execution_status"] = "HISTORICAL_PUBLISHED_STAGE_RECEIPT"
            result["historical_receipt_not_relabelled_current_execution"] = True
        result["source_stage_checkpoint_binding"] = _checkpoint_binding(
            dxf_path=dxf_path, request=request, publication=publication, plan=plan, adoption=adoption,
            scope=scope, source_root=source_root, manifest_path=source_stage_manifest_path,
            continuation_path=source_stage_continuation_path)
        checks["source_stage_checkpoint_binding"] = result["source_stage_checkpoint_binding"]["status"] in (
            "PASS", "NOT_APPLICABLE_FRESH_UPSTREAM_PATH")
        result["status"] = "PASS" if all(checks.values()) else "FAIL"
        result["reason"] = "STAGE_SCOPE_BOUND_NOT_SOURCE_APPROVAL" if result["status"] == "PASS" else "STAGE_INPUT_OR_DECLARATION_BINDING_FAILED"
        result["failed_checks"] = [name for name, passed in checks.items() if not passed]
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, Image.DecompressionBombError) as exc:
        result["status"] = "FAIL"
        result["reason"] = "INVALID_STAGE_INPUT"
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    return result
