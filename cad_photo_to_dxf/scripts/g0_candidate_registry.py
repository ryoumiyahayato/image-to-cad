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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA_VERSION = "draftsman-g0-candidate-registry-v1"
LEGACY_SELECTED_MEMBER = (
    "cad_photo_to_dxf/tests/generalization/corpus_v1_manifest.json"
)
LEGACY_RESERVE_MEMBER = (
    "cad_photo_to_dxf/tests/generalization/corpus_v1_reserve.json"
)
ALLOWED_PHASES = {
    "G0-A",
    "G0-A2",
    "G0-R2",
    "RECOVERED_LEGACY",
    "FUTURE_REDISCOVERY",
}
ALLOWED_QUALITY_TIERS = {"STRONG", "SECONDARY", "UNKNOWN"}
ALLOWED_DEDUP = {"DISTINCT", "UNRESOLVED"}
ALLOWED_IDENTITY_SCOPES = {"SOURCE_GROUP", "UNRESOLVED"}
ALLOWED_LEGACY_ROLES = {"SELECTED", "RESERVE", None}
ALLOWED_RECORD_STATUSES = {
    "RECOVERED_REAL_CANDIDATE",
    "REDISCOVERED_REAL_CANDIDATE",
}
ALLOWED_SPLIT_ELIGIBILITY = {
    "PROVISIONAL_PENDING_ACQUISITION",
    "INELIGIBLE",
    "UNRESOLVED",
    "RESTRICTED",
    "REVIEW_REQUIRED",
}
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


def normalize_canonical_url(url: str) -> str:
    """Normalize a public source URL for deterministic identity and deduplication."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def rediscovered_source_group_id(canonical_source_url: str) -> str:
    identity = normalize_canonical_url(canonical_source_url).encode("utf-8")
    return f"G0R2-{hashlib.sha256(identity).hexdigest()[:16].upper()}"


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
    if not isinstance(url, str) or not url.lower().startswith(("https://", "http://")):
        raise RegistryValidationError("canonical_source_url must be an HTTP(S) URL")
    if record["discovery_phase"] not in ALLOWED_PHASES:
        raise RegistryValidationError("invalid discovery_phase")
    if record["quality_tier"] not in ALLOWED_QUALITY_TIERS:
        raise RegistryValidationError("invalid quality_tier")
    if record["dedup_status"] not in ALLOWED_DEDUP:
        raise RegistryValidationError("invalid dedup_status")
    if record["legacy_proposal_role"] not in ALLOWED_LEGACY_ROLES:
        raise RegistryValidationError("invalid legacy_proposal_role")
    if record["record_status"] not in ALLOWED_RECORD_STATUSES:
        raise RegistryValidationError("invalid record_status")
    if record["split_eligibility"] not in ALLOWED_SPLIT_ELIGIBILITY:
        raise RegistryValidationError("invalid split_eligibility")
    if record["legacy_proposal_authoritative"] is not False:
        raise RegistryValidationError("legacy proposal must remain non-authoritative")
    provenance = record["recovery_provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise RegistryValidationError("recovery_provenance is required")
    for item in provenance:
        if not isinstance(item, dict) or not item.get("kind"):
            raise RegistryValidationError("recovery_provenance entry is incomplete")
        if item["kind"] == "PUBLIC_WEB_REDISCOVERY":
            if not item.get("source_url") or not item.get("observed_at"):
                raise RegistryValidationError("web discovery provenance is incomplete")
        elif not item.get("artifact_sha256") or not item.get("member_path"):
            raise RegistryValidationError("recovery_provenance entry is incomplete")
    if record["discovery_phase"] == "G0-R2":
        expected_id = rediscovered_source_group_id(url)
        if source_group_id != expected_id:
            raise RegistryValidationError(
                f"non-deterministic G0-R2 source_group_id: expected {expected_id}"
            )
        if record["record_status"] != "REDISCOVERED_REAL_CANDIDATE":
            raise RegistryValidationError("G0-R2 record_status must be rediscovered")
        if record["legacy_proposal_role"] is not None or record["legacy_planned_split"] is not None:
            raise RegistryValidationError("G0-R2 records cannot inherit legacy split metadata")


def validate_registry(records: list[dict[str, Any]]) -> None:
    if not records:
        raise RegistryValidationError("registry is empty")
    seen: set[str] = set()
    seen_urls: dict[str, str] = {}
    for record in records:
        validate_record(record)
        source_group_id = record["source_group_id"]
        if source_group_id in seen:
            raise RegistryValidationError(f"duplicate source_group_id: {source_group_id}")
        seen.add(source_group_id)
        normalized_url = normalize_canonical_url(record["canonical_source_url"])
        if normalized_url in seen_urls:
            raise RegistryValidationError(
                "duplicate canonical_source_url: "
                f"{source_group_id} and {seen_urls[normalized_url]}"
            )
        seen_urls[normalized_url] = source_group_id


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


def rediscovered_record(source: dict[str, Any]) -> dict[str, Any]:
    """Build one schema-complete G0-R2 record from inspected web metadata."""
    canonical_url = normalize_canonical_url(str(source["canonical_source_url"]))
    source_group_id = rediscovered_source_group_id(canonical_url)
    provenance: dict[str, Any] = {
        "kind": "PUBLIC_WEB_REDISCOVERY",
        "source_url": canonical_url,
        "observed_at": str(source["observed_at"]),
    }
    for key in ("search_query", "evidence_note"):
        if source.get(key):
            provenance[key] = str(source[key])
    record = {
        "schema_version": SCHEMA_VERSION,
        "source_group_id": source_group_id,
        "candidate_ids": [source_group_id],
        "canonical_source_url": canonical_url,
        "landing_page_url": source.get("landing_page_url"),
        "retrieval_url": source.get("retrieval_url") or canonical_url,
        "organization": str(source["organization"]),
        "project_or_package": str(source["project_or_package"]),
        "region": str(source["region"]),
        "country_or_area": str(source["country_or_area"]),
        "source_type": str(source["source_type"]),
        "file_format": str(source.get("file_format", "UNKNOWN")),
        "vector_raster_status": str(source.get("vector_raster_status", "UNKNOWN")),
        "historical_archival": source.get("historical_archival"),
        "degraded_scan": source.get("degraded_scan"),
        "native_image": source.get("native_image"),
        "era": str(source.get("era", "UNKNOWN")),
        "discipline": str(source.get("discipline", "electrical")),
        "drawing_type": str(source["drawing_type"]),
        "discovery_phase": "G0-R2",
        "quality_tier": str(source.get("quality_tier", "SECONDARY")),
        "quality_flags": list(source.get("quality_flags", [])),
        "governance_status": str(
            source.get("governance_status", "PUBLIC_ACCESS_REUSE_UNCLEAR")
        ),
        "governance_or_access_notes": str(source["governance_or_access_notes"]),
        "source_family_id": str(source["source_family_id"]),
        "source_group_independence_notes": str(
            source["source_group_independence_notes"]
        ),
        "recovery_provenance": [provenance],
        "record_status": "REDISCOVERED_REAL_CANDIDATE",
        "split_eligibility": str(
            source.get("split_eligibility", "PROVISIONAL_PENDING_ACQUISITION")
        ),
        "identity_scope": "SOURCE_GROUP",
        "dedup_status": str(source.get("dedup_status", "DISTINCT")),
        "legacy_proposal_role": None,
        "legacy_planned_split": None,
        "legacy_proposal_authoritative": False,
    }
    validate_record(record)
    return record


def append_discovery_batch(registry_path: Path, batch_path: Path) -> tuple[int, str]:
    records = load_registry(registry_path)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if not isinstance(batch, list) or not batch:
        raise RegistryValidationError("discovery batch must be a non-empty JSON array")
    additions = [rediscovered_record(item) for item in batch]
    digest = write_registry(registry_path, records + additions)
    return len(additions), digest


def registry_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    viable = [record for record in records if record["split_eligibility"] != "INELIGIBLE"]
    return {
        "total_real_source_groups": len(records),
        "new_g0_r2_source_groups": sum(
            record["discovery_phase"] == "G0-R2" for record in records
        ),
        "total_viable_source_groups": len(viable),
        "quality_tier": dict(sorted(Counter(r["quality_tier"] for r in viable).items())),
        "vector_raster_status": dict(
            sorted(Counter(r["vector_raster_status"] for r in viable).items())
        ),
        "historical_archival": sum(r["historical_archival"] is True for r in viable),
        "confirmed_degraded": sum(r["degraded_scan"] is True for r in viable),
        "native_image": sum(r["native_image"] is True for r in viable),
        "region_distribution": dict(sorted(Counter(r["region"] for r in viable).items())),
        "split_eligibility": dict(
            sorted(Counter(r["split_eligibility"] for r in records).items())
        ),
        "governance_status": dict(
            sorted(Counter(r["governance_status"] for r in records).items())
        ),
        "unresolved_dedup": sum(r["dedup_status"] == "UNRESOLVED" for r in records),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    recover = subparsers.add_parser("recover", help="recover the legacy 30+15 archive")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--output", type=Path, required=True)
    recover.add_argument("--legacy-split-output", type=Path)
    validate = subparsers.add_parser("validate", help="validate an existing registry")
    validate.add_argument("registry", type=Path)
    append = subparsers.add_parser("append", help="append an inspected G0-R2 web batch")
    append.add_argument("--registry", type=Path, required=True)
    append.add_argument("--batch", type=Path, required=True)
    append.add_argument("--digest-output", type=Path)
    stats = subparsers.add_parser("stats", help="derive candidate-pool statistics")
    stats.add_argument("registry", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "recover":
        records = recover_legacy_archive(args.archive)
        digest = write_registry(args.output, records)
        if args.legacy_split_output:
            legacy_digest = preserve_legacy_split(args.archive, args.legacy_split_output)
            print(f"legacy_split_raw_sha256={legacy_digest}")
    elif args.command in {"validate", "stats"}:
        records = load_registry(args.registry)
        digest = registry_sha256(records)
        if args.registry.read_bytes() != canonical_registry_bytes(records):
            raise RegistryValidationError("registry bytes are not canonical")
        if args.command == "stats":
            print(json.dumps(registry_stats(records), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        added, digest = append_discovery_batch(args.registry, args.batch)
        records = load_registry(args.registry)
        if args.digest_output:
            args.digest_output.write_bytes(f"{digest}\n".encode("ascii"))
        print(f"added={added}")
    print(f"records={len(records)}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
