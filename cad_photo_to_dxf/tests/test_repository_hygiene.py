from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_repository_hygiene import (
    CANONICAL_RUNTIME_ASSET_PATH,
    CANONICAL_RUNTIME_ASSET_SHA256,
    CANONICAL_RUNTIME_ASSET_SIZE_BYTES,
    GLOBAL_MAXIMUM_FILE_SIZE_BYTES,
    ApprovedRuntimeAsset,
    ApprovedSourceFixture,
    _load_approved_runtime_assets,
    inspect_tracked_files,
    load_approved_runtime_assets,
    load_approved_source_fixtures,
    validate_approved_runtime_asset_contract,
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _commit_tree(root: Path) -> None:
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Repository Hygiene Test")
    _git(root, "config", "user.email", "hygiene@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "test repository hygiene asset")


def _write_runtime_repo(root: Path) -> tuple[Path, list[str], dict[str, object]]:
    asset = root / "resources" / "font.lff"
    license_file = root / "licenses" / "FONT.txt"
    required_by = root / "app" / "export.py"
    asset.parent.mkdir(parents=True, exist_ok=True)
    license_file.parent.mkdir(parents=True, exist_ok=True)
    required_by.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"font-data\n")
    license_file.write_text("License\n", encoding="utf-8")
    required_by.write_text("font\n", encoding="utf-8")
    tracked = [
        "resources/font.lff",
        "licenses/FONT.txt",
        "app/export.py",
    ]
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    entry: dict[str, object] = {
        "path": "resources/font.lff",
        "sha256": digest,
        "max_size_bytes": len(asset.read_bytes()),
        "purpose": "test runtime font",
        "license_file": "licenses/FONT.txt",
        "license": "Apache-2.0",
        "required_by": ["app/export.py"],
    }
    return asset, tracked, entry


def _write_runtime_manifest(root: Path, entry: dict[str, object]) -> Path:
    manifest = root / "approved-runtime.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "assets": [entry]}, indent=2),
        encoding="utf-8",
    )
    return manifest


def _write_source_fixture_manifest(
    root: Path,
    relative: str,
    *,
    max_size_bytes: int | None = None,
) -> Path:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"source-fixture\n")
    size_bytes = path.stat().st_size
    entry = {
        "path": relative,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": size_bytes,
        "max_size_bytes": max_size_bytes if max_size_bytes is not None else size_bytes,
        "test_owner": "test",
        "non_generable_reason": "source fixture is externally supplied",
        "source_or_license": "source fixture",
        "fixture_kind": "source",
        "generated_by_test": False,
    }
    manifest = root / "approved-fixtures.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "fixtures": [entry]}, indent=2),
        encoding="utf-8",
    )
    return manifest


def _canonical_runtime_asset(
    *,
    path: str = CANONICAL_RUNTIME_ASSET_PATH,
    sha256: str = CANONICAL_RUNTIME_ASSET_SHA256,
    max_size_bytes: int = CANONICAL_RUNTIME_ASSET_SIZE_BYTES,
) -> ApprovedRuntimeAsset:
    return ApprovedRuntimeAsset(
        path=path,
        sha256=sha256,
        max_size_bytes=max_size_bytes,
        purpose="canonical test runtime font",
        license_file="licenses/FONT.txt",
        license_name="Apache-2.0",
        required_by=("app/export.py",),
    )


class RepositoryHygieneTests(unittest.TestCase):
    def test_generated_and_large_files_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "app/source.py": b"print('ok')\n",
                "dist/application.exe": b"binary",
                "app/__pycache__/source.pyc": b"cache",
                "output/result.dxf": b"dxf",
                "large.bin": b"x" * 32,
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            findings = inspect_tracked_files(
                root,
                files,
                maximum_file_size_bytes=16,
            )

        paths = {finding.path for finding in findings}
        self.assertNotIn("app/source.py", paths)
        self.assertIn("dist/application.exe", paths)
        self.assertIn("app/__pycache__/source.pyc", paths)
        self.assertIn("output/result.dxf", paths)
        self.assertIn("large.bin", paths)

    def test_unapproved_dxf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "tests/fixtures/ground_truth/example.dxf"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")

            findings = inspect_tracked_files(root, [relative])

        self.assertEqual(len(findings), 1)
        self.assertIn("generated output file", findings[0].reason)

    def test_unapproved_font_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "resources/unapproved.lff"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"font")

            findings = inspect_tracked_files(root, [relative])

        self.assertEqual(len(findings), 1)
        self.assertIn("unapproved runtime font", findings[0].reason)

    def test_approved_runtime_asset_with_exact_hash_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset, tracked, entry = _write_runtime_repo(root)
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            approved, manifest_findings = _load_approved_runtime_assets(
                root,
                tracked,
                manifest,
            )
            findings = inspect_tracked_files(
                root,
                tracked,
                approved_runtime_assets=approved,
            )
            self.assertTrue(asset.is_file())
            self.assertEqual(manifest_findings, [])
            self.assertEqual(findings, [])

    def test_approved_runtime_asset_sha_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset, tracked, entry = _write_runtime_repo(root)
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            asset.write_bytes(b"changed\n")
            _approved, findings = _load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("SHA256 mismatch" in item.reason for item in findings))

    def test_approved_runtime_asset_path_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["path"] = "resources/renamed.lff"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = _load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("not tracked" in item.reason for item in findings))

    def test_approved_runtime_asset_size_limit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["max_size_bytes"] = 1
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = _load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("exceeds max_size_bytes" in item.reason for item in findings))

    def test_fixed_runtime_asset_set_accepts_only_canonical_wqy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            findings = validate_approved_runtime_asset_contract(
                root,
                root / "approved-runtime.json",
                {CANONICAL_RUNTIME_ASSET_PATH: _canonical_runtime_asset()},
            )

        self.assertEqual(findings, [])

    def test_public_runtime_loader_rejects_noncanonical_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            approved, findings = load_approved_runtime_assets(root, tracked, manifest)

        self.assertEqual(approved, {})
        self.assertTrue(any("fixed approved asset set" in item.reason for item in findings))

    def test_fixed_runtime_asset_set_rejects_additional_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extra = _canonical_runtime_asset(path="resources/second.lff")
            findings = validate_approved_runtime_asset_contract(
                root,
                root / "approved-runtime.json",
                {
                    CANONICAL_RUNTIME_ASSET_PATH: _canonical_runtime_asset(),
                    extra.path: extra,
                },
            )

        self.assertTrue(any("not in the fixed approved asset set" in item.reason for item in findings))

    def test_fixed_runtime_asset_set_rejects_path_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replacement = _canonical_runtime_asset(path="resources/replacement.lff")
            findings = validate_approved_runtime_asset_contract(
                root,
                root / "approved-runtime.json",
                {replacement.path: replacement},
            )

        self.assertTrue(any("canonical runtime asset is missing" in item.reason for item in findings))
        self.assertTrue(any("not in the fixed approved asset set" in item.reason for item in findings))

    def test_fixed_runtime_asset_set_rejects_sha_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changed = _canonical_runtime_asset(sha256="0" * 64)
            findings = validate_approved_runtime_asset_contract(
                root,
                root / "approved-runtime.json",
                {CANONICAL_RUNTIME_ASSET_PATH: changed},
            )

        self.assertTrue(any("SHA256 contract mismatch" in item.reason for item in findings))

    def test_fixed_runtime_asset_set_rejects_size_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changed = _canonical_runtime_asset(max_size_bytes=GLOBAL_MAXIMUM_FILE_SIZE_BYTES)
            findings = validate_approved_runtime_asset_contract(
                root,
                root / "approved-runtime.json",
                {CANONICAL_RUNTIME_ASSET_PATH: changed},
            )

        self.assertTrue(any("size contract mismatch" in item.reason for item in findings))

    def test_missing_license_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["license_file"] = "licenses/missing.txt"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = _load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("license file is missing" in item.reason for item in findings))

    def test_wildcard_runtime_asset_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["path"] = "resources/*.lff"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = _load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("without wildcards" in item.reason for item in findings))

    def test_test_output_cannot_be_approved_source_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "tests/fixtures/expected/generated.dxf"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"generated")
            tracked = [relative]
            manifest = root / "approved-fixtures.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "fixtures": [
                            {
                                "path": relative,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "size_bytes": path.stat().st_size,
                                "max_size_bytes": path.stat().st_size,
                                "test_owner": "test",
                                "non_generable_reason": "not applicable",
                                "source_or_license": "not applicable",
                                "fixture_kind": "generated",
                                "generated_by_test": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            _git(root, "init", "--initial-branch=main")
            _git(root, "config", "user.name", "Repository Hygiene Test")
            _git(root, "config", "user.email", "hygiene@example.invalid")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "test generated fixture rejection")
            _approved, findings = load_approved_source_fixtures(root, tracked, manifest)

        self.assertTrue(any("cannot be an approved source fixture" in item.reason for item in findings))

    def test_generated_ground_truth_dxf_cannot_be_approved_source_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "tests/fixtures/ground_truth/generated.dxf"
            manifest = _write_source_fixture_manifest(root, relative)
            tracked = [relative]
            _commit_tree(root)
            _approved, findings = load_approved_source_fixtures(root, tracked, manifest)

        self.assertTrue(any("generated/test/output/diagnostic/export path" in item.reason for item in findings))

    def test_generated_test_output_cannot_be_approved_source_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "cad_photo_to_dxf/test-output/generated.bin"
            manifest = _write_source_fixture_manifest(root, relative)
            tracked = [relative]
            _commit_tree(root)
            _approved, findings = load_approved_source_fixtures(root, tracked, manifest)

        self.assertTrue(any("generated/test/output/diagnostic/export path" in item.reason for item in findings))

    def test_legal_source_fixture_remains_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "cad_photo_to_dxf/tests/fixtures/ground_truth/source.png"
            manifest = _write_source_fixture_manifest(root, relative)
            tracked = [relative]
            _commit_tree(root)
            approved, manifest_findings = load_approved_source_fixtures(root, tracked, manifest)
            findings = inspect_tracked_files(root, tracked, approved_source_fixtures=approved)

        self.assertEqual(manifest_findings, [])
        self.assertEqual(findings, [])

    def test_source_fixture_manifest_cannot_raise_global_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "cad_photo_to_dxf/tests/fixtures/ground_truth/large-source.bin"
            path = root.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                handle.truncate(GLOBAL_MAXIMUM_FILE_SIZE_BYTES + 1)
            manifest = _write_source_fixture_manifest(
                root,
                relative,
                max_size_bytes=GLOBAL_MAXIMUM_FILE_SIZE_BYTES + 1,
            )
            _commit_tree(root)
            _approved, findings = load_approved_source_fixtures(root, [relative], manifest)

        self.assertTrue(any("global repository limit" in item.reason for item in findings))

    def test_approved_source_fixture_cannot_skip_global_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "source/large.bin"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 32)
            fixture = ApprovedSourceFixture(
                path=relative,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=32,
                max_size_bytes=32,
                test_owner="test",
                non_generable_reason="source fixture",
                source_or_license="source fixture",
            )
            findings = inspect_tracked_files(
                root,
                [relative],
                maximum_file_size_bytes=16,
                approved_source_fixtures={relative: fixture},
            )

        self.assertTrue(any("repository size limit" in item.reason for item in findings))

    def test_nested_project_generated_directories_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated_paths = [
                "cad_photo_to_dxf/output/generated.bin",
                "cad_photo_to_dxf/installer/output/generated.bin",
                "cad_photo_to_dxf/packaging/output/generated.bin",
                "cad_photo_to_dxf/test-output/generated.bin",
                "cad_photo_to_dxf/validation-diagnostics/report.json",
            ]
            legal_path = "cad_photo_to_dxf/tests/fixtures/ground_truth/source.png"
            for relative in [*generated_paths, legal_path]:
                path = root.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"data")
            findings = inspect_tracked_files(root, [*generated_paths, legal_path])

        finding_paths = {finding.path for finding in findings}
        self.assertEqual(finding_paths, set(generated_paths))

    def test_new_generated_artifact_cannot_enter_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "validation/new-output.dxf"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"new")

            findings = inspect_tracked_files(root, [relative])

        self.assertEqual(len(findings), 1)
        self.assertIn("generated output file", findings[0].reason)

    def test_generated_report_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "drawing.report.json"
            (root / relative).write_text("{}", encoding="utf-8")

            findings = inspect_tracked_files(root, [relative])

        self.assertEqual(len(findings), 1)
        self.assertIn("processing report", findings[0].reason)


if __name__ == "__main__":
    unittest.main()
