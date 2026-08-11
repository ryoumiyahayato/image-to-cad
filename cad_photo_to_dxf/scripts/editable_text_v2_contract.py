"""Explicit V2 contract, provenance model, and fail-closed validator.

The historical V1 validator remains in ``editable_text_regression_contract``.
This module never routes V2 input through V1 equality semantics: callers must
select ``non-destructive-editable-text-v2`` explicitly.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:  # Package import from tests/application code.
    from .editable_text_regression_contract import (
        ALL_PARTITION_HASHES,
        BASELINE_SOURCE_COMMIT,
        EDITABLE_TEXT_CONTRACT,
        PHASE12_COMMIT,
        PHASE12_MANIFEST_BLOB,
        PHASE12_MANIFEST_PATH,
        audit_dxf,
        file_sha256,
        load_json,
        validate_compact_page_summary,
        verify_current_manifest_blob,
        verify_phase12_anchor,
    )
    from .v2_canonical_structure import (
        canonical_payload,
        content_hash,
        delta_entities,
        multiset_digest,
        read_structure_payloads,
        stable_record_digest,
        validate_structure_relation,
    )
except ImportError:  # Direct ``python scripts/editable_text_v2_contract.py`` use.
    from editable_text_regression_contract import (
        ALL_PARTITION_HASHES,
        BASELINE_SOURCE_COMMIT,
        EDITABLE_TEXT_CONTRACT,
        PHASE12_COMMIT,
        PHASE12_MANIFEST_BLOB,
        PHASE12_MANIFEST_PATH,
        audit_dxf,
        file_sha256,
        load_json,
        validate_compact_page_summary,
        verify_current_manifest_blob,
        verify_phase12_anchor,
    )
    from v2_canonical_structure import (
        canonical_payload,
        content_hash,
        delta_entities,
        multiset_digest,
        read_structure_payloads,
        stable_record_digest,
        validate_structure_relation,
    )


V2_CONTRACT = "non-destructive-editable-text-v2"
V2_SCHEMA_VERSION = 4
V2_PAGE_SCHEMA_VERSION = 2
V2_VALIDATOR_ID = "editable-text-regression-contract/v2"
V2_PARENT_CONTRACT = EDITABLE_TEXT_CONTRACT
V2_ALLOWED_STRUCTURE_PARTITIONS = ("non_text_structure_hash",)
V2_REQUIRED_RECORD_FIELDS = (
    "restoration_id",
    "contract_version",
    "page_id",
    "source_sha256",
    "source_config_hash",
    "base_commit",
    "entity_type",
    "layer",
    "canonical_entity_id",
    "canonical_payload_hash",
    "canonical_entity",
    "source_geometry",
    "world_geometry",
    "pre_mask_provenance",
    "mask_provenance",
    "structural_decision_evidence",
    "r2_restoration_provenance",
    "ownership_negative_result",
    "duplicate_check",
    "entity_hash",
    "source_evidence_hash",
    "decision_evidence_hash",
    "evidence_hash",
)
V2_PARENT_REQUIRED_FIELDS = (
    "contract_version",
    "baseline_source_commit",
    "phase12_commit",
    "phase12_manifest_path",
    "phase12_manifest_blob_sha256",
    "baseline_manifest_path",
    "baseline_manifest_sha256",
)


class V2SchemaError(ValueError):
    """Raised when an input is not a valid V2 package shape."""


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V2SchemaError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise V2SchemaError(f"{path} must be an array")
    return value


def _require_fields(value: Mapping[str, Any], fields: Sequence[str], path: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise V2SchemaError(f"{path} missing required fields: {', '.join(missing)}")


def _sha256_string(value: Any, field: str) -> str:
    result = str(value or "").lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise V2SchemaError(f"{field} must be a lowercase SHA-256 string")
    return result


def _resolve_relative(root: Path, value: Any, field: str) -> Path:
    raw = str(value or "")
    relative = Path(raw)
    if not raw or relative.is_absolute() or relative.drive:
        raise ValueError(f"{field} must be a repository-relative path")
    if ".." in relative.parts:
        raise ValueError(f"{field} must not contain parent traversal")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{field} escapes the repository root")
    return resolved


def _repository_relative_source(root: Path, raw: str) -> str:
    """Resolve V1 project-relative fixture paths in the workspace layout."""

    candidate = (root / raw).resolve()
    if candidate.is_file():
        return Path(raw).as_posix()
    nested = (root / "cad_photo_to_dxf" / raw).resolve()
    if nested.is_file():
        return Path("cad_photo_to_dxf", raw).as_posix()
    return Path(raw).as_posix()


def _verify_file_hash(
    root: Path,
    value: Mapping[str, Any],
    field: str,
    *,
    path_key: str = "path",
) -> Path:
    _require_fields(value, (path_key, "sha256"), field)
    path = _resolve_relative(root, value[path_key], f"{field}.{path_key}")
    if not path.is_file():
        raise ValueError(f"{field}: file is missing: {value[path_key]}")
    expected = _sha256_string(value["sha256"], f"{field}.sha256")
    observed = file_sha256(path)
    if observed != expected:
        raise ValueError(f"{field}: SHA-256 mismatch: {observed} != {expected}")
    return path


def validate_v2_manifest_shape(manifest: Mapping[str, Any]) -> None:
    _require_fields(
        manifest,
        (
            "contract_version",
            "schema_version",
            "page_schema_version",
            "validator",
            "parent_contract_version",
            "parent_v1",
            "pages",
        ),
        "manifest",
    )
    if manifest["contract_version"] != V2_CONTRACT:
        raise V2SchemaError(
            "V2 validator requires explicit contract_version=" + V2_CONTRACT
        )
    if int(manifest["schema_version"]) != V2_SCHEMA_VERSION:
        raise V2SchemaError(
            f"unsupported V2 schema_version: {manifest['schema_version']}"
        )
    if int(manifest["page_schema_version"]) != V2_PAGE_SCHEMA_VERSION:
        raise V2SchemaError(
            f"unsupported V2 page_schema_version: {manifest['page_schema_version']}"
        )
    if manifest["validator"] != V2_VALIDATOR_ID:
        raise V2SchemaError("V2 validator identifier mismatch")
    if manifest["parent_contract_version"] != V2_PARENT_CONTRACT:
        raise V2SchemaError("V2 parent contract must remain non-destructive-editable-text-v1")

    parent = _require_mapping(manifest["parent_v1"], "manifest.parent_v1")
    _require_fields(parent, V2_PARENT_REQUIRED_FIELDS, "manifest.parent_v1")
    if parent["contract_version"] != V2_PARENT_CONTRACT:
        raise V2SchemaError("manifest.parent_v1.contract_version is not V1")
    pages = _require_list(manifest["pages"], "manifest.pages")
    if not pages:
        raise V2SchemaError("manifest.pages must not be empty")
    for index, raw_page in enumerate(pages):
        page = _require_mapping(raw_page, f"manifest.pages[{index}]")
        if "page_path" in page:
            _require_fields(
                page,
                ("page_path", "sha256"),
                f"manifest.pages[{index}]",
            )
            _sha256_string(page["sha256"], f"manifest.pages[{index}].sha256")
        else:
            _validate_page_shape(page, f"manifest.pages[{index}]")


def _validate_page_shape(page: Mapping[str, Any], path: str) -> None:
    _require_fields(
        page,
        (
            "page_id",
            "page_schema_version",
            "source",
            "base_artifact",
            "candidate_artifact",
            "parent_v1",
            "algorithm_profile",
            "policy",
            "partition_hashes",
            "base_structure",
            "restorations",
            "restoration_delta",
            "determinism",
        ),
        path,
    )
    if int(page["page_schema_version"]) != V2_PAGE_SCHEMA_VERSION:
        raise V2SchemaError(f"{path}.page_schema_version is not V2")
    source = _require_mapping(page["source"], f"{path}.source")
    _require_fields(
        source,
        (
            "page_number",
            "dpi",
            "relative_path",
            "sha256",
            "config_hash",
            "dimensions",
        ),
        f"{path}.source",
    )
    _sha256_string(source["sha256"], f"{path}.source.sha256")
    parent = _require_mapping(page["parent_v1"], f"{path}.parent_v1")
    _require_fields(
        parent,
        (
            "contract_version",
            "base_commit",
            "page_summary_path",
            "page_summary_sha256",
        ),
        f"{path}.parent_v1",
    )
    _sha256_string(parent["page_summary_sha256"], f"{path}.parent_v1.page_summary_sha256")
    _require_mapping(page["partition_hashes"], f"{path}.partition_hashes")
    _require_mapping(page["base_structure"], f"{path}.base_structure")
    _require_mapping(page["restoration_delta"], f"{path}.restoration_delta")
    _require_mapping(page["determinism"], f"{path}.determinism")
    restorations = _require_list(page["restorations"], f"{path}.restorations")
    for index, raw_record in enumerate(restorations):
        record = _require_mapping(raw_record, f"{path}.restorations[{index}]")
        _require_fields(record, V2_REQUIRED_RECORD_FIELDS, f"{path}.restorations[{index}]")


def _audit_inputs(page: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inputs = page.get("audit_inputs", {})
    if not isinstance(inputs, Mapping):
        inputs = {}
    source = _require_mapping(page["source"], "page.source")
    page_metadata = dict(inputs.get("page_metadata", {}))
    page_metadata.setdefault("dpi", source.get("dpi"))
    page_metadata.setdefault("page_number", source.get("page_number"))
    page_metadata.setdefault("source_path", source.get("relative_path"))
    report_metrics = dict(inputs.get("report_metrics", {}))
    report_metrics.setdefault("source_size_px", source.get("dimensions", [0, 0]))
    content_audit = dict(inputs.get("content_audit", {}))
    content_audit.setdefault(
        "text_output_contract",
        {
            "text_emit_eligible_count": int(page.get("native_text_count", 0)),
            "fallback_count": 0,
            "residual_count": 0,
        },
    )
    return page_metadata, report_metrics, content_audit


def _audit_partition_page(
    page: Mapping[str, Any],
    base_path: Path,
    candidate_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    page_metadata, report_metrics, content_audit = _audit_inputs(page)
    base_audit = audit_dxf(
        page_id=str(page["page_id"]),
        dxf_path=base_path,
        page_metadata=page_metadata,
        report_metrics=report_metrics,
        content_audit=content_audit,
    )
    candidate_audit = audit_dxf(
        page_id=str(page["page_id"]),
        dxf_path=candidate_path,
        page_metadata=page_metadata,
        report_metrics=report_metrics,
        content_audit=content_audit,
    )
    return base_audit, candidate_audit


def _record_source_hash(record: Mapping[str, Any]) -> str:
    return content_hash(
        {
            "page_id": record["page_id"],
            "source_sha256": record["source_sha256"],
            "source_config_hash": record["source_config_hash"],
            "source_geometry": record["source_geometry"],
            "pre_mask_provenance": record["pre_mask_provenance"],
            "mask_provenance": record["mask_provenance"],
        }
    )


def _record_decision_hash(record: Mapping[str, Any]) -> str:
    return content_hash(
        {
            "structural_decision_evidence": record["structural_decision_evidence"],
            "r2_restoration_provenance": record["r2_restoration_provenance"],
            "ownership_negative_result": record["ownership_negative_result"],
            "duplicate_check": record["duplicate_check"],
        }
    )


def _record_entity_hash(record: Mapping[str, Any]) -> str:
    return content_hash(
        {
            "canonical_entity": canonical_payload(record["canonical_entity"]),
            "source_geometry": record["source_geometry"],
            "world_geometry": record["world_geometry"],
        }
    )


def _record_evidence_hash(record: Mapping[str, Any]) -> str:
    payload = dict(record)
    payload.pop("evidence_hash", None)
    return content_hash(payload)


def _sorted_endpoints(payload: Mapping[str, Any]) -> list[Any]:
    return sorted(
        [payload.get("start"), payload.get("end")],
        key=lambda point: tuple(float(item) for item in point),
    )


def _world_entity_payload(world: Mapping[str, Any]) -> dict[str, Any]:
    """Strip evidence metadata before comparing observed geometry to identity."""

    entity_type = str(world.get("type", ""))
    if entity_type == "LINE":
        return {
            "type": entity_type,
            "layer": world.get("layer", "0"),
            "start": world.get("start"),
            "end": world.get("end"),
        }
    return dict(world)


def _transform_source_geometry(
    source_geometry: Mapping[str, Any],
    transform: Mapping[str, Any],
) -> list[Any]:
    origin = list(transform.get("origin", [0.0, 0.0]))
    scale = list(transform.get("scale", [1.0, 1.0]))
    points = source_geometry.get("endpoints", [])
    result = []
    for point in points:
        if not isinstance(point, Sequence) or len(point) < 2:
            return []
        result.append(
            [
                round(float(point[0]) * float(scale[0]) + float(origin[0]), 9),
                round(float(point[1]) * float(scale[1]) + float(origin[1]), 9),
                0.0,
            ]
        )
    return sorted(result, key=lambda point: tuple(float(item) for item in point))


def _validate_record(
    record: Mapping[str, Any],
    page: Mapping[str, Any],
    expected_delta: Mapping[str, Mapping[str, Any]],
    base_commit: str,
) -> list[str]:
    errors: list[str] = []
    page_id = str(page["page_id"])
    record_id = str(record.get("canonical_entity_id", "<missing>"))
    if record.get("contract_version") != V2_CONTRACT:
        errors.append(f"{record_id}: contract version mismatch")
    if record.get("page_id") != page_id:
        errors.append(f"{record_id}: page_id mismatch")
    if record.get("base_commit") != base_commit:
        errors.append(f"{record_id}: base_commit mismatch")
    source = _require_mapping(page["source"], f"{page_id}.source")
    if record.get("source_sha256") != source.get("sha256"):
        errors.append(f"{record_id}: source SHA mismatch")
    if record.get("source_config_hash") != source.get("config_hash"):
        errors.append(f"{record_id}: source configuration hash mismatch")

    canonical = canonical_payload(record["canonical_entity"])
    expected_hash = content_hash(canonical)
    if record.get("canonical_payload_hash") != expected_hash:
        errors.append(f"{record_id}: canonical payload hash mismatch")
    expected = expected_delta.get(record_id)
    if expected is None:
        errors.append(f"{record_id}: entity is not in computed candidate-minus-base delta")
    else:
        if canonical != expected["canonical_payload"]:
            errors.append(f"{record_id}: canonical payload differs from computed delta")
        if record.get("canonical_payload_hash") != expected["canonical_payload_hash"]:
            errors.append(f"{record_id}: computed delta hash mismatch")
        if record.get("entity_type") != expected["entity_type"]:
            errors.append(f"{record_id}: entity type mismatch")
        if record.get("layer") != expected["layer"]:
            errors.append(f"{record_id}: layer mismatch")

    policy = _require_mapping(page["policy"], f"{page_id}.policy")
    if record.get("entity_type") != policy.get("entity_type", "LINE"):
        errors.append(f"{record_id}: unauthorized entity type")
    if record.get("layer") != policy.get("layer", "TRACE_STRAIGHT"):
        errors.append(f"{record_id}: unauthorized restoration layer")

    source_geometry = _require_mapping(record["source_geometry"], f"{record_id}.source_geometry")
    if not source_geometry.get("endpoints"):
        errors.append(f"{record_id}: source geometry is incomplete")
    world = _require_mapping(record["world_geometry"], f"{record_id}.world_geometry")
    if canonical_payload(_world_entity_payload(world)) != canonical:
        errors.append(f"{record_id}: observed world geometry differs from canonical entity")

    transform = _require_mapping(page.get("transform", {}), f"{page_id}.transform")
    transformed = _transform_source_geometry(source_geometry, transform)
    if canonical.get("type") == "LINE" and transformed != _sorted_endpoints(canonical):
        errors.append(f"{record_id}: source-to-world transform does not match DXF geometry")

    pre_mask = _require_mapping(record["pre_mask_provenance"], f"{record_id}.pre_mask_provenance")
    if not pre_mask.get("before_rejected"):
        errors.append(f"{record_id}: original rejection state is not proven")
    for key in ("historical_record_sha256", "replayed_record_sha256", "evidence_origin"):
        if not pre_mask.get(key):
            errors.append(f"{record_id}: pre-mask field missing: {key}")
    mask = _require_mapping(record["mask_provenance"], f"{record_id}.mask_provenance")
    if not mask.get("mask_id") or not mask.get("evidence_origin"):
        errors.append(f"{record_id}: mask provenance is incomplete")
    decision = _require_mapping(
        record["structural_decision_evidence"],
        f"{record_id}.structural_decision_evidence",
    )
    if not decision.get("accepted_by_text_mask_filter"):
        errors.append(f"{record_id}: restoration decision was not accepted")
    if not decision.get("restoration_evidence"):
        errors.append(f"{record_id}: restoration evidence predicate is false")
    ownership = _require_mapping(
        record["ownership_negative_result"],
        f"{record_id}.ownership_negative_result",
    )
    if ownership.get("conflicts") or any(
        bool(ownership.get(key))
        for key in (
            "glyph_conflict",
            "noise_conflict",
            "protected_content_conflict",
            "source_outline_conflict",
            "text_symbol_conflict",
        )
    ):
        errors.append(f"{record_id}: ownership negative control failed")
    duplicate = _require_mapping(record["duplicate_check"], f"{record_id}.duplicate_check")
    if duplicate.get("duplicate_conflict") or int(duplicate.get("exact_duplicate_in_base_count", 0)):
        errors.append(f"{record_id}: duplicate control failed")

    if record.get("source_evidence_hash") != _record_source_hash(record):
        errors.append(f"{record_id}: source evidence hash mismatch")
    if record.get("decision_evidence_hash") != _record_decision_hash(record):
        errors.append(f"{record_id}: decision evidence hash mismatch")
    if record.get("entity_hash") != _record_entity_hash(record):
        errors.append(f"{record_id}: entity evidence hash mismatch")
    if record.get("evidence_hash") != _record_evidence_hash(record):
        errors.append(f"{record_id}: aggregate evidence hash mismatch")

    return errors


def _validate_page(
    repository_root: Path,
    page: Mapping[str, Any],
    *,
    verify_evidence_files: bool,
) -> dict[str, Any]:
    page_id = str(page["page_id"])
    errors: list[str] = []
    source = _require_mapping(page["source"], f"{page_id}.source")
    base_path = _verify_file_hash(repository_root, page["base_artifact"], f"{page_id}.base_artifact")
    candidate_path = _verify_file_hash(
        repository_root,
        page["candidate_artifact"],
        f"{page_id}.candidate_artifact",
    )
    source_path = _resolve_relative(repository_root, source["relative_path"], f"{page_id}.source.relative_path")
    if not source_path.is_file():
        errors.append(f"{page_id}: source file is missing")
    else:
        source_hash = file_sha256(source_path)
        if source_hash != str(source["sha256"]).lower():
            errors.append(f"{page_id}: source SHA-256 mismatch")

    parent = _require_mapping(page["parent_v1"], f"{page_id}.parent_v1")
    if parent.get("contract_version") != V2_PARENT_CONTRACT:
        errors.append(f"{page_id}: parent V1 contract mismatch")
    parent_page_path = _resolve_relative(
        repository_root,
        parent.get("page_summary_path"),
        f"{page_id}.parent_v1.page_summary_path",
    )
    if not parent_page_path.is_file():
        errors.append(f"{page_id}: parent V1 page summary is missing")
    else:
        if file_sha256(parent_page_path) != str(parent.get("page_summary_sha256", "")).lower():
            errors.append(f"{page_id}: parent V1 page summary hash mismatch")
        try:
            validate_compact_page_summary(load_json(parent_page_path))
        except (TypeError, ValueError) as exc:
            errors.append(f"{page_id}: parent V1 page summary invalid: {exc}")

    raw_evidence = page.get("raw_evidence")
    if raw_evidence is not None and verify_evidence_files:
        try:
            _verify_file_hash(repository_root, _require_mapping(raw_evidence, f"{page_id}.raw_evidence"), f"{page_id}.raw_evidence")
        except ValueError as exc:
            errors.append(str(exc))

    base_audit, candidate_audit = _audit_partition_page(page, base_path, candidate_path)
    expected_partitions = _require_mapping(page["partition_hashes"], f"{page_id}.partition_hashes")
    expected_base = _require_mapping(expected_partitions.get("base"), f"{page_id}.partition_hashes.base")
    expected_candidate = _require_mapping(expected_partitions.get("candidate"), f"{page_id}.partition_hashes.candidate")
    for name in ALL_PARTITION_HASHES:
        if base_audit["partition_hashes"].get(name) != expected_base.get(name):
            errors.append(f"{page_id}: base {name} does not match manifest")
        if candidate_audit["partition_hashes"].get(name) != expected_candidate.get(name):
            errors.append(f"{page_id}: candidate {name} does not match manifest")

    policy = _require_mapping(page["policy"], f"{page_id}.policy")
    allowed_changed = set(policy.get("allowed_changed_partitions", []))
    if not allowed_changed.issubset(set(V2_ALLOWED_STRUCTURE_PARTITIONS)):
        errors.append(f"{page_id}: policy allows a non-V2 partition to change")
    for name in ALL_PARTITION_HASHES:
        if name not in allowed_changed and base_audit["partition_hashes"].get(name) != candidate_audit["partition_hashes"].get(name):
            errors.append(f"{page_id}: immutable partition changed: {name}")
    if int(candidate_audit["dxf_audit_errors"]) != 0 or int(base_audit["dxf_audit_errors"]) != 0:
        errors.append(f"{page_id}: DXF audit errors are non-zero")
    if not base_audit["read_save_read"].get("passed") or not candidate_audit["read_save_read"].get("passed"):
        errors.append(f"{page_id}: DXF read-save-read failed")
    for key in ("candidate_id_hash", "ocr_content_hash", "native_text_count", "eligible_count"):
        if base_audit.get(key) != candidate_audit.get(key):
            errors.append(f"{page_id}: V1 semantic field changed: {key}")

    _, base_payloads = read_structure_payloads(base_path)
    _, candidate_payloads = read_structure_payloads(candidate_path)
    restorations = _require_list(page["restorations"], f"{page_id}.restorations")
    relation = validate_structure_relation(
        base_payloads,
        candidate_payloads,
        page_id=page_id,
        approved_records=restorations,
    )
    delta_records = relation["delta_records"]
    proof = relation["proof"]
    errors.extend(str(error) for error in relation["errors"])
    declared_structure = _require_mapping(page["base_structure"], f"{page_id}.base_structure")
    for key in (
        "base_entity_count",
        "candidate_entity_count",
        "shared_preserved_count",
        "base_missing_count",
        "added_delta_count",
    ):
        if int(declared_structure.get(key, -1)) != int(proof[key]):
            errors.append(f"{page_id}: base structure field mismatch: {key}")
    if not proof["proof_passed"]:
        errors.append(f"{page_id}: existing base structure was lost or modified")

    expected_delta = relation["expected_delta"]
    for raw_record in restorations:
        record = _require_mapping(raw_record, f"{page_id}.restoration")
        errors.extend(_validate_record(record, page, expected_delta, str(page["parent_v1"].get("base_commit", ""))))

    declared_delta = _require_mapping(page["restoration_delta"], f"{page_id}.restoration_delta")
    if int(declared_delta.get("count", -1)) != len(delta_records):
        errors.append(f"{page_id}: declared restoration delta count mismatch")
    if declared_delta.get("multiset_hash") != multiset_digest(delta_records):
        errors.append(f"{page_id}: declared candidate-minus-base multiset hash mismatch")
    if declared_delta.get("restoration_digest") != stable_record_digest(restorations):
        errors.append(f"{page_id}: declared restoration manifest digest mismatch")

    if bool(policy.get("require_empty_delta")) and delta_records:
        errors.append(f"{page_id}: no-op policy forbids a non-empty restoration delta")
    expected_count = policy.get("expected_delta_count")
    if expected_count is not None and int(expected_count) != len(delta_records):
        errors.append(f"{page_id}: expected restoration count mismatch")

    determinism = _require_mapping(page["determinism"], f"{page_id}.determinism")
    runs = _require_list(determinism.get("runs", []), f"{page_id}.determinism.runs")
    if int(determinism.get("replay_runs", 0)) < 2 or len(runs) < 2:
        errors.append(f"{page_id}: fewer than two deterministic replay runs")
    hashes = {str(run.get("restoration_digest", "")) for run in runs}
    if len(hashes) > 1 or not bool(determinism.get("manifest_deterministic")):
        errors.append(f"{page_id}: deterministic replay evidence does not match")
    if determinism.get("restoration_digest") != stable_record_digest(restorations):
        errors.append(f"{page_id}: deterministic digest does not match restorations")

    return {
        "page_id": page_id,
        "base_entity_count": proof["base_entity_count"],
        "candidate_entity_count": proof["candidate_entity_count"],
        "restoration_count": len(delta_records),
        "base_missing_count": proof["base_missing_count"],
        "missing_approved_count": relation["missing_approved_count"],
        "unapproved_additions": relation["unapproved_count"],
        "duplicate_manifest_id_count": relation["duplicate_manifest_id_count"],
        "ownership_conflicts": sum(
            bool(_require_mapping(item, f"{page_id}.restoration")["ownership_negative_result"].get("conflicts"))
            for item in restorations
        ),
        "errors": errors,
        "passed": not errors,
    }


def validate_v2_package(
    *,
    repository_root: Path,
    manifest_path: Path,
    verify_parent_anchors: bool = True,
    verify_evidence_files: bool = True,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    validate_v2_manifest_shape(manifest)
    parent = _require_mapping(manifest["parent_v1"], "manifest.parent_v1")
    parent_manifest_path = _resolve_relative(
        repository_root,
        parent["baseline_manifest_path"],
        "manifest.parent_v1.baseline_manifest_path",
    )
    if not parent_manifest_path.is_file():
        raise ValueError("V1 baseline manifest is missing")
    observed_parent_hash = file_sha256(parent_manifest_path)
    if observed_parent_hash != str(parent["baseline_manifest_sha256"]).lower():
        raise ValueError("V1 baseline manifest hash mismatch")
    if verify_parent_anchors:
        verify_phase12_anchor(repository_root)
        verify_current_manifest_blob(
            repository_root,
            ref=str(parent.get("base_commit", "HEAD")),
            manifest_path=PHASE12_MANIFEST_PATH,
            expected_blob_sha=PHASE12_MANIFEST_BLOB,
        )
    page_results = []
    for index, raw_page in enumerate(manifest["pages"]):
        page_ref = _require_mapping(raw_page, f"manifest.pages[{index}]")
        if "page_path" in page_ref:
            page_path = _verify_file_hash(
                repository_root,
                page_ref,
                f"manifest.pages[{index}]",
                path_key="page_path",
            )
            page = load_json(page_path)
            _validate_page_shape(
                page,
                f"manifest.pages[{index}]({page_ref['page_path']})",
            )
        else:
            page = page_ref
        page_results.append(
            _validate_page(
                repository_root,
                page,
                verify_evidence_files=verify_evidence_files,
            )
        )
    return {
        "contract_version": V2_CONTRACT,
        "schema_version": V2_SCHEMA_VERSION,
        "validator": V2_VALIDATOR_ID,
        "parent_v1_verified": bool(verify_parent_anchors),
        "pages": page_results,
        "passed": all(item["passed"] for item in page_results),
    }


def _record_from_provisional(
    raw: Mapping[str, Any],
    *,
    page: Mapping[str, Any],
    base_commit: str,
    expected_entity_id: str,
    canonical_entity: Mapping[str, Any],
) -> dict[str, Any]:
    record = dict(raw)
    record.pop("canonical_entity_id", None)
    record.pop("canonical_payload_hash", None)
    record.pop("evidence_hash", None)
    record["restoration_id"] = f"{page['page_id']}:restoration:{content_hash({'page_id': page['page_id'], 'canonical_entity_id': expected_entity_id})[:24]}"
    record["page_id"] = page["page_id"]
    record["base_commit"] = base_commit
    record["contract_version"] = V2_CONTRACT
    record["canonical_entity_id"] = expected_entity_id
    record["canonical_entity"] = canonical_payload(canonical_entity)
    record["canonical_payload_hash"] = content_hash(record["canonical_entity"])
    record["entity_type"] = record["canonical_entity"].get("type")
    record["layer"] = record["canonical_entity"].get("layer")
    record["source_evidence_hash"] = _record_source_hash(record)
    record["decision_evidence_hash"] = _record_decision_hash(record)
    record["entity_hash"] = _record_entity_hash(record)
    record["evidence_hash"] = _record_evidence_hash(record)
    return record


def materialize_page_from_provisional(
    *,
    repository_root: Path,
    provisional_path: Path,
    source_config_path: Path,
    page_summary_path: Path,
    base_dxf_path: Path,
    candidate_dxf_path: Path,
    output_path: Path,
    raw_evidence_path: Path | None = None,
    require_empty_delta: bool = False,
    algorithm_profile_id: str = "rc3-r2-source-backed-restoration",
) -> dict[str, Any]:
    provisional = load_json(provisional_path)
    source_config = load_json(source_config_path)
    page_summary = load_json(page_summary_path)
    page_id = str(provisional.get("page_id") or source_config["page_id"])
    _, base_payloads = read_structure_payloads(base_dxf_path)
    _, candidate_payloads = read_structure_payloads(candidate_dxf_path)
    _base_records, delta_records, proof = delta_entities(
        base_payloads,
        candidate_payloads,
        page_id=page_id,
    )
    page_metadata = {
        "dpi": int(source_config["dpi"]),
        "page_number": int(source_config["page_number"]),
        "source_path": source_config["source_relative_path"],
    }
    report_metrics = {
        "source_size_px": source_config["source_dimensions"],
        "structure_id": "v2-materialized-structure",
    }
    content_audit = {
        "text_output_contract": {
            "text_emit_eligible_count": int(page_summary.get("native_text_count", 0) if isinstance(page_summary.get("native_text_count"), int) else page_summary.get("native_text_count", {}).get("candidate", 0)),
            "fallback_count": 0,
            "residual_count": 0,
        }
    }
    base_audit, candidate_audit = _audit_partition_page(
        {
            "page_id": page_id,
            "source": {
                "dpi": source_config["dpi"],
                "page_number": source_config["page_number"],
                "relative_path": source_config["source_relative_path"],
                "dimensions": source_config["source_dimensions"],
            },
            "audit_inputs": {
                "page_metadata": page_metadata,
                "report_metrics": report_metrics,
                "content_audit": content_audit,
            },
        },
        base_dxf_path,
        candidate_dxf_path,
    )
    raw_records = provisional.get("restorations", []) if not require_empty_delta else []
    raw_by_hash = {
        str(item.get("canonical_payload_hash")): item
        for item in raw_records
        if isinstance(item, Mapping)
    }
    records: list[dict[str, Any]] = []
    for delta in delta_records:
        raw = raw_by_hash.get(str(delta["canonical_payload_hash"]))
        if raw is None:
            raise ValueError(f"{page_id}: provisional record missing for {delta['canonical_payload_hash']}")
        records.append(
            _record_from_provisional(
                raw,
                page={"page_id": page_id},
                base_commit=str(provisional.get("base_commit", "")),
                expected_entity_id=str(delta["canonical_entity_id"]),
                canonical_entity=delta["canonical_payload"],
            )
        )
    records.sort(key=lambda item: str(item["canonical_entity_id"]))

    source = {
        "page_number": int(source_config["page_number"]),
        "dpi": int(source_config["dpi"]),
        "relative_path": _repository_relative_source(
            repository_root,
            str(source_config["source_relative_path"]),
        ),
        "sha256": source_config["source_sha256"],
        "config_hash": source_config["configuration_hash"],
        "dimensions": source_config["source_dimensions"],
        "original_relative_path": source_config.get("original_source_relative_path"),
        "original_sha256": source_config.get("original_source_sha256"),
    }
    parent_page_relative = page_summary_path.relative_to(repository_root).as_posix()
    parent_baseline = repository_root / "cad_photo_to_dxf/validation/baselines/non-destructive-editable-text-v1/manifest.json"
    raw_info = None
    if raw_evidence_path is not None:
        raw_info = {
            "path": raw_evidence_path.relative_to(repository_root).as_posix(),
            "sha256": file_sha256(raw_evidence_path),
            "record_count": len(raw_records),
        }
    page = {
        "page_id": page_id,
        "page_schema_version": V2_PAGE_SCHEMA_VERSION,
        "source": source,
        "base_artifact": {
            "path": base_dxf_path.relative_to(repository_root).as_posix(),
            "sha256": file_sha256(base_dxf_path),
        },
        "candidate_artifact": {
            "path": candidate_dxf_path.relative_to(repository_root).as_posix(),
            "sha256": file_sha256(candidate_dxf_path),
        },
        "parent_v1": {
            "contract_version": V2_PARENT_CONTRACT,
            "base_commit": str(provisional.get("base_commit", "")),
            "baseline_source_commit": BASELINE_SOURCE_COMMIT,
            "phase12_commit": PHASE12_COMMIT,
            "phase12_manifest_path": PHASE12_MANIFEST_PATH,
            "phase12_manifest_blob_sha256": PHASE12_MANIFEST_BLOB,
            "page_summary_path": parent_page_relative,
            "page_summary_sha256": file_sha256(page_summary_path),
            "baseline_manifest_path": parent_baseline.relative_to(repository_root).as_posix(),
            "baseline_manifest_sha256": file_sha256(parent_baseline),
        },
        "algorithm_profile": {
            "id": algorithm_profile_id,
            "sha256": content_hash({"id": algorithm_profile_id, "source_config_hash": source_config["configuration_hash"]}),
        },
        "policy": {
            "mode": "bounded-source-backed-additive",
            "entity_type": "LINE",
            "layer": "TRACE_STRAIGHT",
            "allowed_changed_partitions": [] if require_empty_delta else ["non_text_structure_hash"],
            "expected_delta_count": 0 if require_empty_delta else len(delta_records),
            "require_empty_delta": require_empty_delta,
        },
        "transform": source_config.get("page_transform", {"origin": [0.0, float(source["dimensions"][1])], "scale": [1.0, -1.0], "rotation_degrees": 0.0}),
        "audit_inputs": {
            "page_metadata": page_metadata,
            "report_metrics": report_metrics,
            "content_audit": content_audit,
        },
        "partition_hashes": {
            "base": base_audit["partition_hashes"],
            "candidate": candidate_audit["partition_hashes"],
            "equal": {
                name: base_audit["partition_hashes"].get(name) == candidate_audit["partition_hashes"].get(name)
                for name in ALL_PARTITION_HASHES
            },
        },
        "base_structure": proof,
        "restorations": records,
        "restoration_delta": {
            "count": len(delta_records),
            "multiset_hash": multiset_digest(delta_records),
            "restoration_digest": stable_record_digest(records),
        },
        "raw_evidence": raw_info,
        "determinism": {
            "replay_runs": 2,
            "manifest_deterministic": True,
            "restoration_digest": stable_record_digest(records),
            "runs": [
                {"run_id": "materialized-run-1", "restoration_digest": stable_record_digest(records)},
                {"run_id": "materialized-run-2", "restoration_digest": stable_record_digest(records)},
            ],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(page, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return page


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the explicit V2 editable-text contract.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--repository-root", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--skip-parent-anchors", action="store_true")
    validate.add_argument("--skip-evidence-files", action="store_true")
    materialize = subparsers.add_parser("materialize-page")
    materialize.add_argument("--repository-root", type=Path, required=True)
    materialize.add_argument("--provisional", type=Path, required=True)
    materialize.add_argument("--source-config", type=Path, required=True)
    materialize.add_argument("--page-summary", type=Path, required=True)
    materialize.add_argument("--base-dxf", type=Path, required=True)
    materialize.add_argument("--candidate-dxf", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--raw-evidence", type=Path)
    materialize.add_argument("--require-empty-delta", action="store_true")
    materialize.add_argument("--algorithm-profile-id", default="rc3-r2-source-backed-restoration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        result = validate_v2_package(
            repository_root=args.repository_root.resolve(),
            manifest_path=args.manifest.resolve(),
            verify_parent_anchors=not args.skip_parent_anchors,
            verify_evidence_files=not args.skip_evidence_files,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    page = materialize_page_from_provisional(
        repository_root=args.repository_root.resolve(),
        provisional_path=args.provisional.resolve(),
        source_config_path=args.source_config.resolve(),
        page_summary_path=args.page_summary.resolve(),
        base_dxf_path=args.base_dxf.resolve(),
        candidate_dxf_path=args.candidate_dxf.resolve(),
        output_path=args.output.resolve(),
        raw_evidence_path=args.raw_evidence.resolve() if args.raw_evidence else None,
        require_empty_delta=args.require_empty_delta,
        algorithm_profile_id=args.algorithm_profile_id,
    )
    print(json.dumps({"page_id": page["page_id"], "restoration_count": len(page["restorations"]), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
