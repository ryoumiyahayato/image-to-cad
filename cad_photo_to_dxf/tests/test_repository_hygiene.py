from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_repository_hygiene import (
    inspect_tracked_files,
    load_approved_runtime_assets,
    load_approved_source_fixtures,
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
            approved, manifest_findings = load_approved_runtime_assets(
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
            _approved, findings = load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("SHA256 mismatch" in item.reason for item in findings))

    def test_approved_runtime_asset_path_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["path"] = "resources/renamed.lff"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("not tracked" in item.reason for item in findings))

    def test_approved_runtime_asset_size_limit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["max_size_bytes"] = 1
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("exceeds max_size_bytes" in item.reason for item in findings))

    def test_missing_license_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["license_file"] = "licenses/missing.txt"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = load_approved_runtime_assets(root, tracked, manifest)

        self.assertTrue(any("license file is missing" in item.reason for item in findings))

    def test_wildcard_runtime_asset_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _asset, tracked, entry = _write_runtime_repo(root)
            entry["path"] = "resources/*.lff"
            manifest = _write_runtime_manifest(root, entry)
            _commit_tree(root)
            _approved, findings = load_approved_runtime_assets(root, tracked, manifest)

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
