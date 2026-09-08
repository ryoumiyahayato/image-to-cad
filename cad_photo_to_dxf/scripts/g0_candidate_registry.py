"""Recover and validate the durable Draftsman G0 candidate registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "draftsman-g0-candidate-registry-v1"
LEGACY_SELECTED_MEMBER = (
    "cad_photo_to_dxf/tests/generalization/corpus_v1_manifest.json"
)
LEGACY_RESERVE_MEMBER = (
    "cad_photo_to_dxf/tests/generalization/corpus_v1_reserve.json"
)
ALLOWED_PHASES = {"G0-A", "G0-A2", "RECOVERED_LEGACY", "FUTURE_REDISCOVERY"}
ALLOWED_QUALITY_TIERS = {"STRONG", "SECONDARY", "UNKNOWN"}
ALLOWED_DEDUP = {"DISTINCT", "UNRESOLVED"}
ALLOWED_IDENTITY_SCOPES = {"SOURCE_GROUP", "UNRESOLVED"}
ALLOWED_LEGACY_ROLES = {"SELECTED", "RESERVE"}
REQUIRED_FIELDS = {
    "schema_version",
    "source_group_id",
    "candidate_ids",
    "canonical_source_url",
    "landing_page_url",
    "retrieval_url",
    "organization",
    "project_or_package",
    "region",
    "country_or_area",
    "source_type",
    "file_format",
    "vector_raster_status",
    "historical_archival",
    "degraded_scan",
    "native_image",
    "era",
    "discipline",
    "drawing_type",
    "discovery_phase",
    "quality_tier",
    "quality_flags",
    "governance_status",
    "governance_or_access_notes",
    "source_family_id",
    "source_group_independence_notes",
    "recovery_provenance",
    "record_status",
    "split_eligibility",
    "identity_scope",
    "dedup_status",
    "legacy_proposal_role",
    "legacy_planned_split",
    "legacy_proposal_authoritative",
}


class RegistryValidationError(ValueError):
    """Raised when a registry record violates the recovery contract."""


def canonical_record_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_registry_bytes(records: Iterable[dict[str, Any]]) -> bytes:
    ordered = sorted(records, key=lambda record: record["source_group_id"])
    return ("\n".join(canonical_record_line(record) for record in ordered) + "\n").encode(
        "utf-8"
    )


def registry_sha256(records: Iterable[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_registry_bytes(records)).hexdigest()


def validate_record(record: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - record.keys())
    if missing:
        raise RegistryValidationError(f"missing required fields: {', '.join(missing)}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise RegistryValidationError("unsupported schema_version")
    source_group_id = record["source_group_id"]
    if not isinstance(source_group_id, str) or not source_group_id.strip():
        raise RegistryValidationError("source_group_id must be a non-empty string")
    if record["identity_scope"] not in ALLOWED_IDENTITY_SCOPES:
        raise RegistryValidationError("a page cannot be an independent SOURCE_GROUP")
    if re.search(r"(?:^|[-_])PAGE(?:[-_]|$)", source_group_id, re.IGNORECASE):
        raise RegistryValidationError("page-derived source_group_id is forbidden")
    candidate_ids = record["candidate_ids"]
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise RegistryValidationError("candidate_ids must be a non-empty list")
    url = record["canonical_source_url"]
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise RegistryValidationError("canonical_source_url must be an HTTP(S) URL")
    if record["discovery_phase"] not in ALLOWED_PHASES:
        raise RegistryValidationError("invalid discovery_phase")
    if record["quality_tier"] not in ALLOWED_QUALITY_TIERS:
        raise RegistryValidationError("invalid quality_tier")
    if record["dedup_status"] not in ALLOWED_DEDUP:
        raise RegistryValidationError("invalid dedup_status")
    if record["legacy_proposal_role"] not in ALLOWED_LEGACY_ROLES:
        raise RegistryValidationError("invalid legacy_proposal_role")
    if record["legacy_proposal_authoritative"] is not False:
        raise RegistryValidationError("legacy proposal must remain non-authoritative")
    provenance = record["recovery_provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise RegistryValidationError("recovery_provenance is required")
    for item in provenance:
        if not isinstance(item, dict) or not item.get("artifact_sha256") or not item.get(
            "member_path"
        ):
            raise RegistryValidationError("recovery_provenance entry is incomplete")


def validate_registry(records: list[dict[str, Any]]) -> None:
    if not records:
        raise RegistryValidationError("registry is empty")
    seen: set[str] = set()
    for record in records:
        validate_record(record)
        source_group_id = record["source_group_id"]
        if source_group_id in seen:
            raise RegistryValidationError(f"duplicate source_group_id: {source_group_id}")
        seen.add(source_group_id)


def load_registry(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise RegistryValidationError(f"invalid JSON on line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise RegistryValidationError(f"line {line_number} is not a JSON object")
        records.append(value)
    validate_registry(records)
    return records


def _is_confirmed_degraded(quality_flags: list[str]) -> bool | None:
    confirmed = {
        "LOW_DPI_RELATIVE_TO_MODERN_SCAN",
        "MONOCHROME_1BIT",
        "WATER_DAMAGE",
        "LOW_DPI_METADATA",
        "UNEQUAL_ILLUMINATION_OR_PHOTO_CAPTURE",
    }
    if confirmed.intersection(quality_flags):
        return True
    return None


def _normalize_legacy_record(
    source: dict[str, Any],
    *,
    role: str,
    artifact_name: str,
    artifact_sha256: str,
    member_path: str,
    unresolved_families: set[str],
) -> dict[str, Any]:
    candidate_id = str(source["candidate_id"])
    discovery_phase = "G0-A2" if candidate_id.startswith("G0A2-") else "G0-A"
    family_id = str(source.get("source_family_id") or source["source_group_id"])
    quality_flags = [str(value) for value in source.get("quality_flags", [])]
    independence = str(source.get("independence", "UNKNOWN"))
    authenticity = str(source.get("authenticity", "UNKNOWN"))
    relation_note = (
        f"Recovered legacy classification: authenticity={authenticity}; "
        f"independence={independence}; source_family_id={family_id}."
    )
    if family_id in unresolved_families:
        relation_note += " Multiple recovered records share this source family; relation review is unresolved."
    return {
        "schema_version": SCHEMA_VERSION,
        "source_group_id": str(source["source_group_id"]),
        "candidate_ids": [candidate_id],
        "canonical_source_url": str(source["canonical_url"]).strip(),
        "landing_page_url": None,
        "retrieval_url": None,
        "organization": source.get("organization") or "UNKNOWN",
        "project_or_package": source.get("project_name") or "UNKNOWN",
        "region": source.get("country_region") or "UNKNOWN",
        "country_or_area": source.get("country_region") or "UNKNOWN",
        "source_type": source.get("document_type") or "UNKNOWN",
        "file_format": source.get("file_format") or "UNKNOWN",
        "vector_raster_status": source.get("structural_class") or "UNKNOWN",
        "historical_archival": source.get("historical_archival"),
        "degraded_scan": _is_confirmed_degraded(quality_flags),
        "native_image": source.get("native_image"),
        "era": source.get("year_era") or "UNKNOWN",
        "discipline": source.get("electrical_discipline_type") or "UNKNOWN",
        "drawing_type": source.get("document_type") or "UNKNOWN",
        "discovery_phase": discovery_phase,
        "quality_tier": "UNKNOWN",
        "quality_flags": quality_flags,
        "governance_status": source.get("governance_status") or "UNKNOWN",
        "governance_or_access_notes": source.get("governance_note") or "UNKNOWN",
        "source_family_id": family_id,
        "source_group_independence_notes": relation_note,
        "recovery_provenance": [
            {
                "kind": "RECOVERED_LEGACY_G0B_RECORD",
                "artifact_name": artifact_name,
                "artifact_sha256": artifact_sha256,
                "member_path": member_path,
                "candidate_id": candidate_id,
            }
        ],
        "record_status": "RECOVERED_REAL_CANDIDATE",
        "split_eligibility": "PROVISIONAL_PENDING_ACQUISITION",
        "identity_scope": "SOURCE_GROUP",
        "dedup_status": "UNRESOLVED" if family_id in unresolved_families else "DISTINCT",
        "legacy_proposal_role": role,
        "legacy_planned_split": source.get("planned_split"),
        "legacy_proposal_authoritative": False,
    }


def recover_legacy_archive(archive_path: Path) -> list[dict[str, Any]]:
    artifact_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        selected = json.loads(archive.read(LEGACY_SELECTED_MEMBER))["sources"]
        reserve = json.loads(archive.read(LEGACY_RESERVE_MEMBER))["sources"]
    combined = selected + reserve
    family_counts = Counter(
        str(source.get("source_family_id") or source["source_group_id"])
        for source in combined
    )
    unresolved_families = {family for family, count in family_counts.items() if count > 1}
    records = [
        _normalize_legacy_record(
            source,
            role=role,
            artifact_name=archive_path.name,
            artifact_sha256=artifact_sha256,
            member_path=member,
            unresolved_families=unresolved_families,
        )
        for role, member, sources in (
            ("SELECTED", LEGACY_SELECTED_MEMBER, selected),
            ("RESERVE", LEGACY_RESERVE_MEMBER, reserve),
        )
        for source in sources
    ]
    validate_registry(records)
    return records


def preserve_legacy_split(archive_path: Path, output_path: Path) -> str:
    """Preserve the exact old split proposal bytes without making them authoritative."""
    with zipfile.ZipFile(archive_path) as archive:
        payload = archive.read("cad_photo_to_dxf/tests/generalization/corpus_v1_split.json")
    parsed = json.loads(payload)
    if parsed.get("freeze_status") == "FROZEN" or parsed.get("authoritative_frozen_digest"):
        raise RegistryValidationError("legacy proposal unexpectedly claims authoritative freeze")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def write_registry(path: Path, records: list[dict[str, Any]]) -> str:
    validate_registry(records)
    payload = canonical_registry_bytes(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    recover = subparsers.add_parser("recover", help="recover the legacy 30+15 archive")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--output", type=Path, required=True)
    recover.add_argument("--legacy-split-output", type=Path)
    validate = subparsers.add_parser("validate", help="validate an existing registry")
    validate.add_argument("registry", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "recover":
        records = recover_legacy_archive(args.archive)
        digest = write_registry(args.output, records)
        if args.legacy_split_output:
            legacy_digest = preserve_legacy_split(args.archive, args.legacy_split_output)
            print(f"legacy_split_raw_sha256={legacy_digest}")
    else:
        records = load_registry(args.registry)
        digest = registry_sha256(records)
        if args.registry.read_bytes() != canonical_registry_bytes(records):
            raise RegistryValidationError("registry bytes are not canonical")
    print(f"records={len(records)}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
