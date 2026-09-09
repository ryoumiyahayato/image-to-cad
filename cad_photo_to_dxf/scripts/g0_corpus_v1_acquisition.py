"""Acquire frozen Draftsman Corpus V1 source bytes without evaluating them."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

candidate_registry = importlib.import_module(
    ".g0_candidate_registry" if __package__ else "g0_candidate_registry",
    package=__package__,
)
corpus_selection = importlib.import_module(
    ".g0_corpus_v1_selection" if __package__ else "g0_corpus_v1_selection",
    package=__package__,
)

SCHEMA_VERSION = "draftsman-corpus-v1-acquisition-manifest-v1"
REGISTRY_DIGEST = "07e25d6d876c0d0416556aefe01267d688da495111eec69e521bb2c70803e780"
SPLIT_DIGEST = "05283c960096941ecac34f73e109fe9d850e8d2354b144387c00370755d288cd"
CORPUS_VERSION = "DRAFTSMAN_GENERALIZATION_CORPUS_V1"
MATERIAL_ROOT = "local-artifacts/draftsman/corpus-v1"
SPLITS = ("DEV", "VALIDATION", "LOCKED_BLIND")
USER_AGENT = "image-to-cad-g0-b4/1.0 (+source acquisition; no evaluation)"
REMEDIATION_SOURCE_GROUP_IDS = frozenset(
    {
        "A2-SG-010",
        "G0R2-2E9BDFFDD8C89AE7",
        "G0R2-53C88494D6CE893C",
        "G0R2-AFE53C2A00EB7D8F",
        "SGC-007",
        "SGC-008",
        "SGC-024",
    }
)
MANUAL_IMPORTABLE_STATES = frozenset(
    {"MANUAL_ACCESS_REQUIRED", "MANUAL_DOWNLOAD_REQUIRED"}
)

# These byte URLs were resolved through the official Wikimedia Commons API.
# The canonical registry URL remains the provenance identity.
OFFICIAL_BYTE_URLS = {
    "A2-SG-008": (
        "https://upload.wikimedia.org/wikipedia/commons/b/be/"
        "Interior_Renovations_of_Building_9_Second_Floor_Electrical_Plan%2C_"
        "July_30%2C_1993_-_DPLA_-_b6b22ab93e5f886a37869fd90012e91d.tiff",
        "OFFICIAL_WIKIMEDIA_API_IMAGEINFO",
    ),
    "A2-SG-009": (
        "https://upload.wikimedia.org/wikipedia/commons/1/17/"
        "Electrical_plans_for_four_floors_%28CABHC_2024-014-13%29.jpg",
        "OFFICIAL_WIKIMEDIA_API_IMAGEINFO",
    ),
    "A2-SG-022": (
        "https://planningregister.cherwell.gov.uk/Document/Download?"
        "fileName=C13-+BANBURY+ELECTRICAL+AS+BUILT.pdf&imageId=61424&isPlan=True&"
        "module=PLA&planId=51424&recordNumber=146257",
        "OFFICIAL_LANDING_PAGE_DOCUMENT_LINK",
    ),
    "G0R2-7E30C7F445081F40": (
        "https://apps.planningportal.nsw.gov.au/prweb/PRRestService/DocMgmt/v1/"
        "PublicDocuments/DATA-WORKATTACH-FILE%20PEC-DPE-EP-WORK%20"
        "P5-2023-61%2120230531T082853.259%20GMT",
        "OFFICIAL_LANDING_PAGE_DOCUMENT_LINK",
    ),
    "G0R2-4DC97797ABE2CB18": (
        "https://integrations.goldcoast.qld.gov.au/pdonline/default.aspx?oid=A38094160",
        "OFFICIAL_APPLICATION_DOCUMENT_VIEWER_LINK",
    ),
    "G0R2-AEA044C8E75CB3AB": (
        "https://cdn.loc.gov/master/pnp/habshaer/hi/hi0800/hi0822/sheet/00039a.tif",
        "OFFICIAL_LOC_DOWNLOAD_LINK",
    ),
    "G0R2-C2D095E069663C17": (
        "https://apps.planningportal.nsw.gov.au/prweb/PRRestService/DocMgmt/v1/"
        "PublicDocuments/DATA-WORKATTACH-FILE%20PEC-DPE-EP-WORK%20"
        "P5-2024-93%2120240703T010051.420%20GMT",
        "OFFICIAL_LANDING_PAGE_DOCUMENT_LINK",
    ),
    "SGC-008": (
        "https://www.farmington-ct.org/home/showpublisheddocument/36556",
        "OFFICIAL_OWNER_DOCUMENT_LINK",
    ),
}


class AcquisitionError(ValueError):
    """Raised when acquisition metadata or local bytes fail closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _governance(record: dict[str, Any]) -> tuple[str, str]:
    status = record["governance_status"]
    if status == "PUBLIC_DOWNLOAD_CLEAR":
        return "DOWNLOAD_ALLOWED_FOR_LOCAL_EVALUATION", "REDISTRIBUTION_NOT_GRANTED"
    if status == "PUBLIC_ARCHIVE_RIGHTS_ADVISORY":
        return "ARCHIVE_ADVISORY", "REDISTRIBUTION_RESTRICTED"
    if status == "PUBLIC_ACCESS_REUSE_UNCLEAR":
        return "RIGHTS_UNCLEAR", "REDISTRIBUTION_RESTRICTED"
    return "ACQUISITION_BLOCKED", "REDISTRIBUTION_RESTRICTED"


def _detect_format(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        head = stream.read(16)
    if head.startswith(b"%PDF-"):
        return "PDF", "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG", "image/jpeg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF", "image/tiff"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG", "image/png"
    if head.startswith(b"PK\x03\x04"):
        return "ZIP", "application/zip"
    return "UNKNOWN", "application/octet-stream"


def _pdf_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "integrity_check": "PDF_MAGIC_VALID",
        "page_count": None,
        "encrypted": None,
    }
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return metadata
    result = subprocess.run(
        [pdfinfo, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise AcquisitionError("downloaded PDF is not parseable by pdfinfo")
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    metadata["integrity_check"] = "PDFINFO_PARSE_PASS"
    if values.get("Pages", "").isdigit():
        metadata["page_count"] = int(values["Pages"])
    if "Encrypted" in values:
        metadata["encrypted"] = values["Encrypted"].lower().startswith("yes")
    return metadata


def _image_metadata(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return {
                "integrity_check": "PIL_VERIFY_PASS",
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
            }
    except (ImportError, OSError) as exc:
        raise AcquisitionError(f"downloaded image is not parseable: {exc}") from exc


def inspect_file(path: Path) -> dict[str, Any]:
    detected_format, mime_type = _detect_format(path)
    if detected_format == "UNKNOWN":
        raise AcquisitionError("response is not a supported source-byte format")
    metadata: dict[str, Any] = {
        "detected_format": detected_format,
        "mime_type": mime_type,
    }
    if detected_format == "PDF":
        metadata.update(_pdf_metadata(path))
    elif detected_format in {"JPEG", "TIFF", "PNG"}:
        metadata.update(_image_metadata(path))
    else:
        metadata["integrity_check"] = "ZIP_MAGIC_VALID"
    return metadata


def validate_authoritative_inputs(
    registry_path: Path, split_path: Path, split_digest_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = candidate_registry.load_registry(registry_path)
    if len(records) != 99:
        raise AcquisitionError("BLOCKED_AUTHORITATIVE_INPUT_MISMATCH: registry count")
    registry_digest = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if registry_digest != REGISTRY_DIGEST:
        raise AcquisitionError("BLOCKED_AUTHORITATIVE_INPUT_MISMATCH: registry digest")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    actual_split_digest = hashlib.sha256(split_path.read_bytes()).hexdigest()
    recorded_split_digest = split_digest_path.read_text(encoding="ascii").strip()
    if actual_split_digest != SPLIT_DIGEST or recorded_split_digest != SPLIT_DIGEST:
        raise AcquisitionError("BLOCKED_AUTHORITATIVE_INPUT_MISMATCH: split digest")
    corpus_selection.validate_split(split, records)
    expected_counts = {"CORPUS_V1": 30, "DEV": 15, "VALIDATION": 7, "LOCKED_BLIND": 8}
    if any(split["counts"].get(key) != value for key, value in expected_counts.items()):
        raise AcquisitionError("BLOCKED_AUTHORITATIVE_INPUT_MISMATCH: split counts")
    if split["gates"] != {
        "candidate_registry_digest_matches": True,
        "exact_split_counts": True,
        "fabricated_records": 0,
        "ineligible_selected": [],
        "previously_exposed_locked_blind": 0,
        "source_family_leakage": [],
        "split_overlap_count": 0,
    }:
        raise AcquisitionError("BLOCKED_AUTHORITATIVE_INPUT_MISMATCH: split gates")
    return records, split


def _prior_by_id(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {entry["source_group_id"]: entry for entry in manifest["source_groups"]}


def _download(url: str, temporary_path: Path, timeout: int) -> tuple[str, int | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            status = response.status
            if content_type in {"text/html", "application/xhtml+xml"}:
                return "MANUAL_ACCESS_REQUIRED", status
            with temporary_path.open("xb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        return "SUCCESS", status
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return "HTTP_RESTRICTED", exc.code
        if exc.code == 404:
            return "SOURCE_NOT_FOUND", exc.code
        return "HTTP_FAILURE", exc.code
    except urllib.error.URLError as exc:
        reason = str(exc.reason).lower()
        if "timed out" in reason:
            return "TIMEOUT", None
        if "name or service" in reason or "getaddrinfo" in reason:
            return "DNS_FAILURE", None
        return _download_with_curl(url, temporary_path, timeout)
    except TimeoutError:
        return "TIMEOUT", None


def _download_with_curl(
    url: str, temporary_path: Path, timeout: int
) -> tuple[str, int | None]:
    """Retry transport failures with curl without changing the source URL."""
    curl = shutil.which("curl")
    if not curl:
        return "NETWORK_FAILURE", None
    result = subprocess.run(
        [
            curl,
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "--user-agent",
            USER_AGENT,
            "--output",
            str(temporary_path),
            "--write-out",
            "%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout + 10,
    )
    try:
        http_status = int(result.stdout[-3:])
    except ValueError:
        http_status = None
    if result.returncode == 0 and temporary_path.exists() and temporary_path.stat().st_size:
        return "SUCCESS", http_status
    temporary_path.unlink(missing_ok=True)
    if http_status in {401, 403, 429}:
        return "HTTP_RESTRICTED", http_status
    if http_status == 404:
        return "SOURCE_NOT_FOUND", http_status
    if result.returncode == 28:
        return "TIMEOUT", http_status
    return "NETWORK_FAILURE", http_status


def _failure_entry(
    base: dict[str, Any], state: str, attempted_at: str, http_status: int | None
) -> dict[str, Any]:
    manual = state in {"MANUAL_ACCESS_REQUIRED", "HTTP_RESTRICTED"}
    base.update(
        {
            "acquisition_state": "MANUAL_ACCESS_REQUIRED" if manual else "ACQUISITION_FAILED",
            "attempted_at_utc": attempted_at,
            "failure": {"code": state, "http_status": http_status},
            "files": [],
            "materialization_state": "NOT_MATERIALIZED",
            "evaluation_ready": False,
        }
    )
    return base


def _entry_base(record: dict[str, Any], split_name: str) -> dict[str, Any]:
    source_group_id = record["source_group_id"]
    governance_state, redistribution_state = _governance(record)
    byte_url, resolution = OFFICIAL_BYTE_URLS.get(
        source_group_id,
        (record.get("retrieval_url") or record["canonical_source_url"], "REGISTRY_URL"),
    )
    return {
        "source_group_id": source_group_id,
        "split": split_name,
        "canonical_source_url": record["canonical_source_url"],
        "resolved_acquisition_url": byte_url,
        "url_resolution_evidence": resolution,
        "acquisition_method": "HTTPS_DIRECT_SOURCE",
        "governance_state": governance_state,
        "redistribution_state": redistribution_state,
        "governance_or_access_notes": record["governance_or_access_notes"],
        "runtime_executed": False,
        "blind_exposure_status": (
            "NEVER_EXECUTED" if split_name == "LOCKED_BLIND" else "NOT_APPLICABLE"
        ),
        "visual_manual_development_inspection": False,
    }


def acquire_entry(
    record: dict[str, Any],
    split_name: str,
    material_root: Path,
    repository_root: Path,
    prior: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    entry = _entry_base(record, split_name)
    attempted_at = _utc_now()
    if entry["governance_state"] == "ACQUISITION_BLOCKED":
        return _failure_entry(entry, "RIGHTS_BLOCKED", attempted_at, None)
    source_group_id = record["source_group_id"]
    if prior and prior.get("files"):
        prior_file = prior["files"][0]
        existing = repository_root / prior_file["local_relative_path"]
        if existing.exists():
            actual_hash = sha256_file(existing)
            if actual_hash != prior_file["sha256"]:
                entry.update(
                    {
                        "acquisition_state": "SOURCE_BYTES_CHANGED",
                        "attempted_at_utc": attempted_at,
                        "failure": {
                            "code": "SOURCE_BYTES_CHANGED",
                            "http_status": None,
                            "existing_sha256": actual_hash,
                            "expected_sha256": prior_file["sha256"],
                        },
                        "files": prior["files"],
                        "materialization_state": "CONFLICT",
                        "evaluation_ready": False,
                    }
                )
                return entry
            inspect_file(existing)
            entry.update(
                {
                    "acquisition_state": "REUSED_VERIFIED",
                    "attempted_at_utc": prior["attempted_at_utc"],
                    "failure": None,
                    "files": prior["files"],
                    "materialization_state": "EVALUATION_READY",
                    "evaluation_ready": True,
                }
            )
            return entry
    group_root = material_root / split_name.lower().replace("_", "-") / source_group_id
    group_root.mkdir(parents=True, exist_ok=True)
    temporary_path = group_root / f"{source_group_id}.download.part"
    if temporary_path.exists():
        temporary_path.unlink()
    state, http_status = _download(entry["resolved_acquisition_url"], temporary_path, timeout)
    if state != "SUCCESS":
        if temporary_path.exists():
            temporary_path.unlink()
        return _failure_entry(entry, state, attempted_at, http_status)
    try:
        metadata = inspect_file(temporary_path)
    except AcquisitionError:
        temporary_path.unlink(missing_ok=True)
        return _failure_entry(entry, "CORRUPT_OR_UNSUPPORTED", attempted_at, http_status)
    extension = {"PDF": ".pdf", "JPEG": ".jpg", "TIFF": ".tiff", "PNG": ".png", "ZIP": ".zip"}[
        metadata["detected_format"]
    ]
    target = group_root / f"{source_group_id}{extension}"
    downloaded_hash = sha256_file(temporary_path)
    acquisition_state = "SUCCESS"
    if target.exists():
        existing_hash = sha256_file(target)
        expected_hash = None
        if prior and prior.get("files"):
            expected_hash = prior["files"][0]["sha256"]
        if existing_hash != downloaded_hash or (
            expected_hash is not None and existing_hash != expected_hash
        ):
            temporary_path.unlink()
            entry.update(
                {
                    "acquisition_state": "SOURCE_BYTES_CHANGED",
                    "attempted_at_utc": attempted_at,
                    "failure": {
                        "code": "SOURCE_BYTES_CHANGED",
                        "http_status": http_status,
                        "existing_sha256": existing_hash,
                        "downloaded_sha256": downloaded_hash,
                    },
                    "files": prior.get("files", []) if prior else [],
                    "materialization_state": "CONFLICT",
                    "evaluation_ready": False,
                }
            )
            return entry
        temporary_path.unlink()
        acquisition_state = "REUSED_VERIFIED"
        attempted_at = prior.get("attempted_at_utc", attempted_at) if prior else attempted_at
    else:
        temporary_path.replace(target)
    relative_path = target.relative_to(repository_root).as_posix()
    file_entry = {
        "local_relative_path": relative_path,
        "sha256": downloaded_hash,
        "byte_size": target.stat().st_size,
        **metadata,
    }
    entry.update(
        {
            "acquisition_state": acquisition_state,
            "attempted_at_utc": attempted_at,
            "failure": None,
            "files": [file_entry],
            "materialization_state": "EVALUATION_READY",
            "evaluation_ready": True,
        }
    )
    return entry


def build_manifest(
    records: list[dict[str, Any]],
    split: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {record["source_group_id"]: record for record in records}
    expected_ids = {
        item["source_group_id"]
        for name in SPLITS
        for item in split["splits"][name]
    }
    actual_ids = {entry["source_group_id"] for entry in entries}
    if actual_ids != expected_ids or len(entries) != 30 or not actual_ids <= by_id.keys():
        raise AcquisitionError("manifest membership does not match frozen Corpus V1")
    ready = sum(bool(entry["evaluation_ready"]) for entry in entries)
    files = [file for entry in entries for file in entry["files"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "authoritative_split_modified": False,
        "candidate_registry_sha256": REGISTRY_DIGEST,
        "authoritative_split_sha256": SPLIT_DIGEST,
        "material_root": MATERIAL_ROOT,
        "generated_at_utc": _utc_now(),
        "source_groups": sorted(entries, key=lambda item: item["source_group_id"]),
        "summary": {
            "source_groups": 30,
            "acquisition_attempted": 30,
            "successfully_acquired": ready,
            "evaluation_ready": ready,
            "acquisition_failed": sum(
                entry["acquisition_state"]
                in {
                    "ACQUISITION_FAILED",
                    "OFFICIAL_SOURCE_UNAVAILABLE",
                    "SOURCE_BYTES_CHANGED",
                }
                for entry in entries
            ),
            "manual_access_required": sum(
                entry["acquisition_state"] in MANUAL_IMPORTABLE_STATES for entry in entries
            ),
            "network_environment_failures": sum(
                entry.get("failure", {}).get("code")
                in {"DNS_FAILURE", "TIMEOUT", "NETWORK_FAILURE"}
                for entry in entries
                if entry.get("failure")
            ),
            "governance_blocked": sum(
                entry.get("failure", {}).get("code") == "RIGHTS_BLOCKED"
                for entry in entries
                if entry.get("failure")
            ),
            "source_files_materialized": len(files),
            "sha256_coverage": len(files),
            "provenance_coverage": len(entries),
            "governance_coverage": len(entries),
            "changed_source_byte_conflicts": sum(
                entry["acquisition_state"] == "SOURCE_BYTES_CHANGED" for entry in entries
            ),
            "corrupt_or_unsupported": sum(
                entry.get("failure", {}).get("code") == "CORRUPT_OR_UNSUPPORTED"
                for entry in entries
                if entry.get("failure")
            ),
            "by_split": {
                name: {
                    "source_groups": sum(entry["split"] == name for entry in entries),
                    "evaluation_ready": sum(
                        entry["split"] == name and entry["evaluation_ready"] for entry in entries
                    ),
                }
                for name in SPLITS
            },
        },
        "gates": {
            "registry_digest_bound": True,
            "split_digest_bound": True,
            "locked_blind_runtime_executed": 0,
            "locked_blind_visual_manual_development_inspection": False,
            "source_bytes_committed_to_git": 0,
        },
        "deterministic_serialization": "UTF-8 JSON, sorted keys, indent=2, LF, final LF",
    }


def validate_manifest(manifest: dict[str, Any], *, read_locked_blind: bool = False) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise AcquisitionError("unsupported acquisition manifest schema")
    if manifest.get("candidate_registry_sha256") != REGISTRY_DIGEST:
        raise AcquisitionError("registry digest binding mismatch")
    if manifest.get("authoritative_split_sha256") != SPLIT_DIGEST:
        raise AcquisitionError("split digest binding mismatch")
    entries = manifest.get("source_groups", [])
    if len(entries) != 30 or len({entry["source_group_id"] for entry in entries}) != 30:
        raise AcquisitionError("manifest requires 30 unique SOURCE_GROUP records")
    paths = [file["local_relative_path"] for entry in entries for file in entry["files"]]
    if len(paths) != len(set(paths)):
        raise AcquisitionError("duplicate local material path")
    file_hashes = [file["sha256"] for entry in entries for file in entry["files"]]
    if len(file_hashes) != len(set(file_hashes)):
        raise AcquisitionError("duplicate file identity across SOURCE_GROUP records")
    for entry in entries:
        resolved = urllib.parse.urlsplit(entry["resolved_acquisition_url"])
        if resolved.scheme != "https" or not resolved.netloc:
            raise AcquisitionError("resolved acquisition URL must be an absolute HTTPS URL")
        if (
            entry["source_group_id"] in REMEDIATION_SOURCE_GROUP_IDS
            and entry["resolved_acquisition_url"] != entry["canonical_source_url"]
            and entry["url_resolution_evidence"] == "REGISTRY_URL"
        ):
            raise AcquisitionError("resolved URL requires relocation provenance")
        ready = entry["evaluation_ready"]
        files = entry["files"]
        if ready != bool(files):
            raise AcquisitionError("evaluation-ready state must match materialized files")
        if ready and entry["materialization_state"] != "EVALUATION_READY":
            raise AcquisitionError("materialized entry has inconsistent state")
        if not ready and entry["materialization_state"] == "EVALUATION_READY":
            raise AcquisitionError("unmaterialized entry has inconsistent state")
        if entry["acquisition_state"] == "MANUAL_IMPORT_SUCCESS" and not entry.get(
            "manual_import"
        ):
            raise AcquisitionError("manual import requires identity evidence")
        if entry["split"] == "LOCKED_BLIND":
            if entry["runtime_executed"] or entry["blind_exposure_status"] != "NEVER_EXECUTED":
                raise AcquisitionError("LOCKED_BLIND execution/exposure guard failed")
            if not read_locked_blind:
                continue
        for file in entry["files"]:
            if not isinstance(file["sha256"], str) or len(file["sha256"]) != 64:
                raise AcquisitionError("invalid SHA256 metadata")


def verify_local_files(
    manifest: dict[str, Any], repository_root: Path, *, include_locked_blind: bool = False
) -> None:
    """Verify material bytes while keeping LOCKED_BLIND opt-in protected."""
    for entry in manifest["source_groups"]:
        if entry["split"] == "LOCKED_BLIND" and not include_locked_blind:
            continue
        for file in entry["files"]:
            path = repository_root / file["local_relative_path"]
            if not path.is_file():
                raise AcquisitionError(f"material file missing: {file['local_relative_path']}")
            if path.stat().st_size != file["byte_size"]:
                raise AcquisitionError(f"material byte size changed: {file['local_relative_path']}")
            if sha256_file(path) != file["sha256"]:
                raise AcquisitionError(f"material SHA256 changed: {file['local_relative_path']}")


def build_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    failures = [entry for entry in manifest["source_groups"] if not entry["evaluation_ready"]]
    lines = [
        "# G0-B4 Corpus V1 Acquisition Report",
        "",
        "This report covers source acquisition and byte-level integrity only. No Draftsman, OCR, rendering, QA, or evaluation runtime was executed.",
        "",
        f"- Corpus V1 SOURCE_GROUPS: {summary['source_groups']}",
        f"- Successfully acquired: {summary['successfully_acquired']}",
        f"- Evaluation-ready: {summary['evaluation_ready']}",
        f"- Manual download required: {summary['manual_access_required']}",
        f"- Acquisition failed: {summary['acquisition_failed']}",
        f"- Source files materialized: {summary['source_files_materialized']}",
        "- LOCKED_BLIND runtime executed: 0 / 8",
        "- Authoritative split modified: NO",
        "",
        "## Unmaterialized SOURCE_GROUPS",
        "",
    ]
    if not failures:
        lines.append("None.")
    else:
        for entry in failures:
            failure = entry.get("failure") or {}
            lines.append(
                f"- `{entry['source_group_id']}` ({entry['split']}): "
                f"{failure.get('code', entry['acquisition_state'])}"
            )
    lines.extend(
        [
            "",
            "Third-party source bytes remain under the ignored repo-local material root and are not distributable through Git.",
            "",
        ]
    )
    return "\n".join(lines)


def register_manual_acquisition(
    registry_path: Path,
    split_path: Path,
    split_digest_path: Path,
    manifest_path: Path,
    report_path: Path,
    material_root: Path,
    repository_root: Path,
    *,
    source_group_id: str,
    source_file: Path,
    identity_evidence: str,
) -> dict[str, Any]:
    """Validate and register a human-downloaded official source without overwriting bytes."""
    records, split = validate_authoritative_inputs(registry_path, split_path, split_digest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    expected_ids = {
        selected["source_group_id"]
        for split_name in SPLITS
        for selected in split["splits"][split_name]
    }
    if source_group_id not in expected_ids or source_group_id not in REMEDIATION_SOURCE_GROUP_IDS:
        raise AcquisitionError("manual import SOURCE_GROUP is not an approved remediation target")
    evidence = identity_evidence.strip()
    if len(evidence) < 20:
        raise AcquisitionError("manual import requires specific source identity evidence")
    entries = copy.deepcopy(manifest["source_groups"])
    entry = next(item for item in entries if item["source_group_id"] == source_group_id)
    if entry["split"] == "LOCKED_BLIND":
        raise AcquisitionError("manual import cannot inspect LOCKED_BLIND material")
    if entry["acquisition_state"] not in MANUAL_IMPORTABLE_STATES or entry["files"]:
        raise AcquisitionError("SOURCE_GROUP state does not allow manual import")
    source = source_file.resolve(strict=True)
    if not source.is_file():
        raise AcquisitionError("manual import path is not a file")
    metadata = inspect_file(source)
    source_hash = sha256_file(source)
    known_hashes = {
        file["sha256"] for item in manifest["source_groups"] for file in item["files"]
    }
    if source_hash in known_hashes:
        raise AcquisitionError("manual import duplicates an existing source identity")
    root = material_root.resolve()
    repository = repository_root.resolve()
    expected_root = (repository / MATERIAL_ROOT).resolve()
    if root != expected_root:
        raise AcquisitionError("material root does not match the ignored Corpus V1 root")
    try:
        root.relative_to(repository)
    except ValueError as exc:
        raise AcquisitionError("material root must remain inside the repository") from exc
    extension = {
        "PDF": ".pdf",
        "JPEG": ".jpg",
        "TIFF": ".tiff",
        "PNG": ".png",
        "ZIP": ".zip",
    }[metadata["detected_format"]]
    group_root = root / entry["split"].lower().replace("_", "-") / source_group_id
    group_root.mkdir(parents=True, exist_ok=True)
    if any(group_root.iterdir()):
        raise AcquisitionError("manual import target directory is not empty; refusing overwrite")
    target = group_root / f"{source_group_id}{extension}"
    if source == target:
        raise AcquisitionError("manual import target already exists; refusing overwrite")
    try:
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        if sha256_file(target) != source_hash:
            raise AcquisitionError("manual import copy hash mismatch")
        relative_path = target.relative_to(repository).as_posix()
        entry.update(
            {
                "acquisition_method": "MANUAL_OFFICIAL_SOURCE_IMPORT",
                "acquisition_state": "MANUAL_IMPORT_SUCCESS",
                "attempted_at_utc": _utc_now(),
                "failure": None,
                "files": [
                    {
                        "local_relative_path": relative_path,
                        "sha256": source_hash,
                        "byte_size": target.stat().st_size,
                        **metadata,
                    }
                ],
                "manual_import": {
                    "identity_evidence": evidence,
                    "source_path_recorded": False,
                },
                "materialization_state": "EVALUATION_READY",
                "evaluation_ready": True,
            }
        )
        updated = build_manifest(records, split, entries)
        validate_manifest(updated)
        manifest_path.write_bytes(canonical_json_bytes(updated))
        report_path.write_text(build_report(updated), encoding="utf-8", newline="\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return updated


def acquire(
    registry_path: Path,
    split_path: Path,
    split_digest_path: Path,
    manifest_path: Path,
    report_path: Path,
    material_root: Path,
    repository_root: Path,
    *,
    include_locked_blind: bool,
    timeout: int,
) -> dict[str, Any]:
    records, split = validate_authoritative_inputs(registry_path, split_path, split_digest_path)
    record_by_id = {record["source_group_id"]: record for record in records}
    prior = _prior_by_id(manifest_path)
    entries: list[dict[str, Any]] = []
    for split_name in SPLITS:
        if split_name == "LOCKED_BLIND" and not include_locked_blind:
            raise AcquisitionError("LOCKED_BLIND acquisition requires explicit opt-in")
        for selected in split["splits"][split_name]:
            source_group_id = selected["source_group_id"]
            entries.append(
                acquire_entry(
                    record_by_id[source_group_id],
                    split_name,
                    material_root,
                    repository_root,
                    prior.get(source_group_id),
                    timeout,
                )
            )
    manifest = build_manifest(records, split, entries)
    validate_manifest(manifest, read_locked_blind=include_locked_blind)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    report_path.write_text(build_report(manifest), encoding="utf-8", newline="\n")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--split-digest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--include-locked-blind", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--manual-source-group-id")
    parser.add_argument("--manual-file", type=Path)
    parser.add_argument("--manual-identity-evidence")
    return parser


def main() -> int:
    args = _parser().parse_args()
    records, split = validate_authoritative_inputs(args.registry, args.split, args.split_digest)
    manual_values = (
        args.manual_source_group_id,
        args.manual_file,
        args.manual_identity_evidence,
    )
    if any(value is not None for value in manual_values):
        if not all(value is not None for value in manual_values) or args.check:
            raise AcquisitionError("manual import requires all manual options and cannot use --check")
        manifest = register_manual_acquisition(
            args.registry,
            args.split,
            args.split_digest,
            args.manifest,
            args.report,
            args.material_root,
            args.repository_root,
            source_group_id=args.manual_source_group_id,
            source_file=args.manual_file,
            identity_evidence=args.manual_identity_evidence,
        )
        print(json.dumps(manifest["summary"], sort_keys=True))
        return 0
    if args.check:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_manifest(manifest, read_locked_blind=args.include_locked_blind)
        verify_local_files(
            manifest, args.repository_root, include_locked_blind=args.include_locked_blind
        )
        if args.manifest.read_bytes() != canonical_json_bytes(manifest):
            raise AcquisitionError("manifest serialization is not canonical")
        expected_ids = {
            entry["source_group_id"]
            for name in SPLITS
            for entry in split["splits"][name]
        }
        if expected_ids != {entry["source_group_id"] for entry in manifest["source_groups"]}:
            raise AcquisitionError("manifest membership does not match frozen split")
        if args.report.read_text(encoding="utf-8") != build_report(manifest):
            raise AcquisitionError("acquisition report replay mismatch")
        print(f"records={len(records)}")
        print(f"evaluation_ready={manifest['summary']['evaluation_ready']}")
        return 0
    manifest = acquire(
        args.registry,
        args.split,
        args.split_digest,
        args.manifest,
        args.report,
        args.material_root,
        args.repository_root,
        include_locked_blind=args.include_locked_blind,
        timeout=args.timeout,
    )
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
