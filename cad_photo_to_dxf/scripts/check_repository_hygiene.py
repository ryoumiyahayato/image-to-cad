from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

GENERATED_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".agents",
    "build",
    "dist",
    "diagnostic",
    "diagnostics",
    "export",
    "exports",
    "generated",
    "test-output",
    "validation-diagnostics",
}
GENERATED_DIRECTORY_PREFIXES = {
    "output",
    "installer/output",
    "packaging/output",
    "test-output",
    "tests/fixtures/expected",
    "tests/fixtures/generated",
    "validation-diagnostics",
}
GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".dxf",
}
FONT_SUFFIXES = {
    ".lff",
    ".otf",
    ".ttf",
}
GENERATED_FILENAMES = {
    "preview.png",
    "repository-hygiene.json",
}
GENERATED_REPORT_FILENAMES = {
    "repository-hygiene.json",
}
PROJECT_ROOT = PurePosixPath("cad_photo_to_dxf")
GLOBAL_MAXIMUM_FILE_SIZE_BYTES = 20 * 1024 * 1024
CANONICAL_RUNTIME_ASSET_PATH = "cad_photo_to_dxf/resources/fonts/wqy-unicode.lff"
CANONICAL_RUNTIME_ASSET_SHA256 = "3c97e1dc9732578fe42fca6329bd2369d17b798405b14443b0b9d41e0bacc201"
CANONICAL_RUNTIME_ASSET_SIZE_BYTES = 43_436_980
RUNTIME_ASSET_MANIFEST = PurePosixPath(
    "cad_photo_to_dxf/validation/repository-hygiene/approved_runtime_assets.json"
)
SOURCE_FIXTURE_MANIFEST = PurePosixPath(
    "cad_photo_to_dxf/validation/repository-hygiene/approved_source_fixtures.json"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WILDCARD_CHARS = frozenset("*?[]{}")


@dataclass(frozen=True)
class HygieneFinding:
    path: str
    reason: str
    size_bytes: int


@dataclass(frozen=True)
class ApprovedRuntimeAsset:
    path: str
    sha256: str
    max_size_bytes: int
    purpose: str
    license_file: str
    license_name: str
    required_by: tuple[str, ...]


@dataclass(frozen=True)
class ApprovedSourceFixture:
    path: str
    sha256: str
    size_bytes: int
    max_size_bytes: int
    test_owner: str
    non_generable_reason: str
    source_or_license: str


def _tracked_files(repository_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def _is_under(path: PurePosixPath, prefix: str) -> bool:
    parts = PurePosixPath(prefix).parts
    return path.parts[: len(parts)] == parts


def _path_variants(path: PurePosixPath) -> tuple[PurePosixPath, ...]:
    variants = [path]
    if path.parts[: len(PROJECT_ROOT.parts)] == PROJECT_ROOT.parts:
        project_relative_parts = path.parts[len(PROJECT_ROOT.parts) :]
        if project_relative_parts:
            variants.append(PurePosixPath(*project_relative_parts))
    return tuple(variants)


def _normalize_manifest_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        normalized != value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(character in normalized for character in WILDCARD_CHARS)
        or ":" in path.parts[0]
    ):
        raise ValueError(f"{field} must be one exact relative path without wildcards")
    return normalized


def _relative_path(repository_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repository_root.resolve()).as_posix()


def _file_size(repository_root: Path, relative: str) -> int:
    path = repository_root.joinpath(*PurePosixPath(relative).parts)
    return path.stat().st_size if path.is_file() else 0


def _finding_for_manifest(
    repository_root: Path,
    manifest_path: Path,
    reason: str,
) -> HygieneFinding:
    try:
        relative = _relative_path(repository_root, manifest_path)
    except ValueError:
        relative = manifest_path.name
    return HygieneFinding(relative, reason, _file_size(repository_root, relative))


def _current_blob(repository_root: Path, relative: str) -> tuple[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="repository-hygiene-objects-") as object_root:
        object_directory = Path(object_root) / "objects"
        object_directory.mkdir()
        environment = os.environ.copy()
        environment["GIT_OBJECT_DIRECTORY"] = str(object_directory)
        completed = subprocess.run(
            [
                "git",
                "hash-object",
                "-w",
                f"--path={relative}",
                "--",
                relative,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        blob_sha = completed.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
            raise ValueError(f"Git did not return a blob SHA for {relative}")
        blob = subprocess.run(
            ["git", "cat-file", "blob", blob_sha],
            cwd=repository_root,
            check=True,
            capture_output=True,
            env=environment,
        ).stdout
        return blob_sha, blob


def _validate_common_entry(
    entry: object,
    *,
    index: int,
    required_fields: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(entry, dict):
        return None, f"entry {index} must be an object"
    missing = sorted(required_fields - set(entry))
    if missing:
        return None, f"entry {index} is missing required fields: {', '.join(missing)}"
    try:
        path = _normalize_manifest_path(entry["path"], field=f"entry {index}.path")
    except ValueError as exc:
        return None, str(exc)
    sha256 = entry["sha256"]
    if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
        return None, f"entry {index}.sha256 must be lowercase 64-character SHA256"
    return {**entry, "path": path}, None


def _load_manifest(
    repository_root: Path,
    manifest: Path,
    *,
    entries_key: str,
) -> tuple[dict[str, Any] | None, list[HygieneFinding]]:
    if not manifest.is_file():
        return None, [_finding_for_manifest(repository_root, manifest, "approved manifest is missing")]
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [_finding_for_manifest(repository_root, manifest, f"approved manifest is invalid: {exc}")]
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return None, [_finding_for_manifest(repository_root, manifest, "approved manifest schema_version must be 1")]
    if not isinstance(payload.get(entries_key), list):
        return None, [_finding_for_manifest(repository_root, manifest, f"approved manifest {entries_key} must be a list")]
    return payload, []


def _load_approved_runtime_assets(
    repository_root: Path,
    tracked_files: Iterable[str],
    manifest_path: Path | None = None,
) -> tuple[dict[str, ApprovedRuntimeAsset], list[HygieneFinding]]:
    manifest = manifest_path or repository_root.joinpath(*RUNTIME_ASSET_MANIFEST.parts)
    payload, findings = _load_manifest(repository_root, manifest, entries_key="assets")
    if payload is None:
        return {}, findings
    tracked = {item.replace("\\", "/") for item in tracked_files}
    assets: dict[str, ApprovedRuntimeAsset] = {}
    entries = payload.get("assets", [])
    required_fields = {
        "path",
        "sha256",
        "max_size_bytes",
        "purpose",
        "license_file",
        "license",
        "required_by",
    }
    for index, raw_entry in enumerate(entries):
        entry, error = _validate_common_entry(
            raw_entry,
            index=index,
            required_fields=required_fields,
        )
        if error is not None or entry is None:
            findings.append(_finding_for_manifest(repository_root, manifest, error or "invalid runtime asset"))
            continue
        path = str(entry["path"])
        if path in assets:
            findings.append(_finding_for_manifest(repository_root, manifest, f"duplicate approved runtime asset path: {path}"))
            continue
        max_size = entry["max_size_bytes"]
        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0:
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset max_size_bytes is invalid: {path}"))
            continue
        purpose = entry["purpose"]
        license_name = entry["license"]
        if not isinstance(purpose, str) or not purpose.strip() or not isinstance(license_name, str) or not license_name.strip():
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset purpose/license is missing: {path}"))
            continue
        try:
            license_file = _normalize_manifest_path(entry["license_file"], field=f"runtime asset {path}.license_file")
        except ValueError as exc:
            findings.append(_finding_for_manifest(repository_root, manifest, str(exc)))
            continue
        required_by = entry["required_by"]
        if not isinstance(required_by, list) or not required_by:
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset required_by is empty: {path}"))
            continue
        try:
            required_paths = tuple(
                _normalize_manifest_path(item, field=f"runtime asset {path}.required_by")
                for item in required_by
            )
        except ValueError as exc:
            findings.append(_finding_for_manifest(repository_root, manifest, str(exc)))
            continue
        if path.startswith(("tests/", "validation/")) or _is_generated_path(PurePosixPath(path)):
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset path is generated/test/validation output: {path}"))
            continue
        if path not in tracked:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved runtime asset is not tracked: {path}"))
            continue
        if license_file not in tracked or not _file_size(repository_root, license_file):
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset license file is missing or untracked: {license_file}"))
        missing_required = [item for item in required_paths if item not in tracked]
        if missing_required:
            findings.append(_finding_for_manifest(repository_root, manifest, f"runtime asset required_by path is missing: {missing_required[0]}"))
        try:
            _blob_sha, blob = _current_blob(repository_root, path)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            findings.append(_finding_for_manifest(repository_root, manifest, f"cannot read approved runtime asset {path}: {exc}"))
            continue
        observed_sha = hashlib.sha256(blob).hexdigest()
        if observed_sha != entry["sha256"]:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved runtime asset SHA256 mismatch: {path}"))
        if len(blob) > max_size:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved runtime asset exceeds max_size_bytes: {path}"))
        assets[path] = ApprovedRuntimeAsset(
            path=path,
            sha256=str(entry["sha256"]),
            max_size_bytes=max_size,
            purpose=purpose.strip(),
            license_file=license_file,
            license_name=license_name.strip(),
            required_by=required_paths,
        )
    return assets, findings


def validate_approved_runtime_asset_contract(
    repository_root: Path,
    manifest_path: Path,
    assets: Mapping[str, ApprovedRuntimeAsset],
) -> list[HygieneFinding]:
    expected_paths = {CANONICAL_RUNTIME_ASSET_PATH}
    findings: list[HygieneFinding] = []
    for path in sorted(set(assets) - expected_paths):
        findings.append(
            _finding_for_manifest(
                repository_root,
                manifest_path,
                f"runtime asset is not in the fixed approved asset set: {path}",
            )
        )
    canonical = assets.get(CANONICAL_RUNTIME_ASSET_PATH)
    if canonical is None:
        findings.append(
            _finding_for_manifest(
                repository_root,
                manifest_path,
                f"canonical runtime asset is missing from the approved asset set: {CANONICAL_RUNTIME_ASSET_PATH}",
            )
        )
        return findings
    if canonical.sha256 != CANONICAL_RUNTIME_ASSET_SHA256:
        findings.append(
            _finding_for_manifest(
                repository_root,
                manifest_path,
                f"canonical runtime asset SHA256 contract mismatch: {CANONICAL_RUNTIME_ASSET_PATH}",
            )
        )
    if canonical.max_size_bytes != CANONICAL_RUNTIME_ASSET_SIZE_BYTES:
        findings.append(
            _finding_for_manifest(
                repository_root,
                manifest_path,
                f"canonical runtime asset size contract mismatch: {CANONICAL_RUNTIME_ASSET_PATH}",
            )
        )
    return findings


def load_approved_runtime_assets(
    repository_root: Path,
    tracked_files: Iterable[str],
    manifest_path: Path | None = None,
) -> tuple[dict[str, ApprovedRuntimeAsset], list[HygieneFinding]]:
    manifest = manifest_path or repository_root.joinpath(*RUNTIME_ASSET_MANIFEST.parts)
    assets, findings = _load_approved_runtime_assets(repository_root, tracked_files, manifest)
    contract_findings = validate_approved_runtime_asset_contract(repository_root, manifest, assets)
    findings.extend(contract_findings)
    if contract_findings:
        canonical = assets.get(CANONICAL_RUNTIME_ASSET_PATH)
        if (
            canonical is not None
            and canonical.sha256 == CANONICAL_RUNTIME_ASSET_SHA256
            and canonical.max_size_bytes == CANONICAL_RUNTIME_ASSET_SIZE_BYTES
        ):
            assets = {CANONICAL_RUNTIME_ASSET_PATH: canonical}
        else:
            assets = {}
    return assets, findings


def load_approved_source_fixtures(
    repository_root: Path,
    tracked_files: Iterable[str],
    manifest_path: Path | None = None,
) -> tuple[dict[str, ApprovedSourceFixture], list[HygieneFinding]]:
    manifest = manifest_path or repository_root.joinpath(*SOURCE_FIXTURE_MANIFEST.parts)
    payload, findings = _load_manifest(repository_root, manifest, entries_key="fixtures")
    if payload is None:
        return {}, findings
    tracked = {item.replace("\\", "/") for item in tracked_files}
    fixtures: dict[str, ApprovedSourceFixture] = {}
    required_fields = {
        "path",
        "sha256",
        "size_bytes",
        "max_size_bytes",
        "test_owner",
        "non_generable_reason",
        "source_or_license",
        "fixture_kind",
        "generated_by_test",
    }
    for index, raw_entry in enumerate(payload.get("fixtures", [])):
        entry, error = _validate_common_entry(
            raw_entry,
            index=index,
            required_fields=required_fields,
        )
        if error is not None or entry is None:
            findings.append(_finding_for_manifest(repository_root, manifest, error or "invalid source fixture"))
            continue
        path = str(entry["path"])
        if path in fixtures:
            findings.append(_finding_for_manifest(repository_root, manifest, f"duplicate approved source fixture path: {path}"))
            continue
        if _is_generated_path(PurePosixPath(path)):
            findings.append(
                _finding_for_manifest(
                    repository_root,
                    manifest,
                    f"generated/test/output/diagnostic/export path cannot be an approved source fixture: {path}",
                )
            )
            continue
        if entry["fixture_kind"] != "source" or entry["generated_by_test"] is not False:
            findings.append(_finding_for_manifest(repository_root, manifest, f"test output cannot be an approved source fixture: {path}"))
            continue
        if not all(isinstance(entry[field], str) and str(entry[field]).strip() for field in ("test_owner", "non_generable_reason", "source_or_license")):
            findings.append(_finding_for_manifest(repository_root, manifest, f"source fixture provenance fields are missing: {path}"))
            continue
        sizes = (entry["size_bytes"], entry["max_size_bytes"])
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in sizes):
            findings.append(_finding_for_manifest(repository_root, manifest, f"source fixture size fields are invalid: {path}"))
            continue
        if entry["max_size_bytes"] > GLOBAL_MAXIMUM_FILE_SIZE_BYTES:
            findings.append(
                _finding_for_manifest(
                    repository_root,
                    manifest,
                    f"source fixture max_size_bytes cannot exceed the global repository limit: {path}",
                )
            )
            continue
        if entry["size_bytes"] > entry["max_size_bytes"]:
            findings.append(_finding_for_manifest(repository_root, manifest, f"source fixture exceeds its max_size_bytes: {path}"))
            continue
        if path not in tracked:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved source fixture is not tracked: {path}"))
            continue
        try:
            _blob_sha, blob = _current_blob(repository_root, path)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            findings.append(_finding_for_manifest(repository_root, manifest, f"cannot read approved source fixture {path}: {exc}"))
            continue
        observed_sha = hashlib.sha256(blob).hexdigest()
        if observed_sha != entry["sha256"]:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved source fixture SHA256 mismatch: {path}"))
        if len(blob) != entry["size_bytes"]:
            findings.append(_finding_for_manifest(repository_root, manifest, f"approved source fixture size mismatch: {path}"))
        fixtures[path] = ApprovedSourceFixture(
            path=path,
            sha256=str(entry["sha256"]),
            size_bytes=int(entry["size_bytes"]),
            max_size_bytes=int(entry["max_size_bytes"]),
            test_owner=str(entry["test_owner"]).strip(),
            non_generable_reason=str(entry["non_generable_reason"]).strip(),
            source_or_license=str(entry["source_or_license"]).strip(),
        )
    return fixtures, findings


def _is_generated_path(path: PurePosixPath) -> bool:
    for candidate in _path_variants(path):
        if (
            any(part in GENERATED_DIRECTORY_NAMES for part in candidate.parts)
            or any(_is_under(candidate, prefix) for prefix in GENERATED_DIRECTORY_PREFIXES)
            or candidate.suffix.lower() in GENERATED_SUFFIXES
            or candidate.name.lower() in GENERATED_FILENAMES
            or candidate.name.endswith(".report.json")
        ):
            return True
    return False


def inspect_tracked_files(
    repository_root: Path,
    tracked_files: Iterable[str],
    *,
    maximum_file_size_bytes: int = 20 * 1024 * 1024,
    approved_runtime_assets: Mapping[str, ApprovedRuntimeAsset] | None = None,
    approved_source_fixtures: Mapping[str, ApprovedSourceFixture] | None = None,
) -> list[HygieneFinding]:
    if maximum_file_size_bytes <= 0 or maximum_file_size_bytes > GLOBAL_MAXIMUM_FILE_SIZE_BYTES:
        raise ValueError("maximum_file_size_bytes must be between 1 byte and the fixed 20 MiB limit")
    findings: list[HygieneFinding] = []
    approved_runtime_paths = set(approved_runtime_assets or {})
    approved_fixture_paths = set(approved_source_fixtures or {})
    for raw_path in tracked_files:
        normalized = raw_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        absolute = repository_root / Path(*relative.parts)
        size = absolute.stat().st_size if absolute.is_file() else 0
        path_variants = _path_variants(relative)

        reason: str | None = None
        canonical_runtime_asset = normalized == CANONICAL_RUNTIME_ASSET_PATH and normalized in approved_runtime_paths
        if size > maximum_file_size_bytes and not canonical_runtime_asset:
            reason = "tracked file exceeds repository size limit"
        elif normalized in approved_runtime_paths or normalized in approved_fixture_paths:
            continue
        elif any(any(part in GENERATED_DIRECTORY_NAMES for part in candidate.parts) for candidate in path_variants):
            reason = "generated or local-only directory is tracked"
        elif any(
            _is_under(candidate, prefix)
            for candidate in path_variants
            for prefix in GENERATED_DIRECTORY_PREFIXES
        ):
            reason = "generated output directory is tracked"
        elif any(candidate.suffix.lower() in FONT_SUFFIXES for candidate in path_variants):
            reason = "unapproved runtime font asset is tracked"
        elif any(candidate.suffix.lower() in GENERATED_SUFFIXES for candidate in path_variants):
            reason = "generated output file is tracked"
        elif any(candidate.name.lower() in GENERATED_REPORT_FILENAMES for candidate in path_variants):
            reason = "generated repository hygiene report is tracked"
        elif any(candidate.name.lower() in GENERATED_FILENAMES for candidate in path_variants):
            reason = "generated preview file is tracked"
        elif any(candidate.name.endswith(".report.json") for candidate in path_variants):
            reason = "generated processing report is tracked"
        elif size > maximum_file_size_bytes:
            reason = "tracked file exceeds repository size limit"

        if reason is not None:
            findings.append(HygieneFinding(normalized, reason, size))

    return sorted(findings, key=lambda item: (item.reason, item.path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail when generated artifacts or unexpectedly large files are tracked."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--maximum-file-size-mib",
        type=float,
        default=20.0,
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--approved-runtime-assets", type=Path)
    parser.add_argument("--approved-source-fixtures", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repository_root.resolve()
    maximum = int(args.maximum_file_size_mib * 1024 * 1024)
    if maximum <= 0 or maximum > GLOBAL_MAXIMUM_FILE_SIZE_BYTES:
        raise SystemExit("Maximum file size must be between 1 byte and the fixed 20 MiB limit")

    tracked = _tracked_files(root)
    runtime_assets, runtime_manifest_findings = load_approved_runtime_assets(
        root,
        tracked,
        args.approved_runtime_assets.resolve() if args.approved_runtime_assets else None,
    )
    source_fixtures, fixture_manifest_findings = load_approved_source_fixtures(
        root,
        tracked,
        args.approved_source_fixtures.resolve() if args.approved_source_fixtures else None,
    )
    findings = [
        *runtime_manifest_findings,
        *fixture_manifest_findings,
        *inspect_tracked_files(
            root,
            tracked,
            maximum_file_size_bytes=maximum,
            approved_runtime_assets=runtime_assets,
            approved_source_fixtures=source_fixtures,
        ),
    ]
    findings = sorted(findings, key=lambda item: (item.reason, item.path))
    payload = {
        "repository_root": str(root),
        "maximum_file_size_bytes": maximum,
        "approved_runtime_assets_manifest": str(
            (args.approved_runtime_assets or root.joinpath(*RUNTIME_ASSET_MANIFEST.parts)).resolve()
        ),
        "approved_source_fixtures_manifest": str(
            (args.approved_source_fixtures or root.joinpath(*SOURCE_FIXTURE_MANIFEST.parts)).resolve()
        ),
        "approved_runtime_asset_count": len(runtime_assets),
        "approved_source_fixture_count": len(source_fixtures),
        "finding_count": len(findings),
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
