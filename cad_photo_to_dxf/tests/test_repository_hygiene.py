from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.check_repository_hygiene import inspect_tracked_files


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

    def test_ground_truth_fixture_dxf_is_allowed_within_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "tests/fixtures/ground_truth/example.dxf"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")

            findings = inspect_tracked_files(
                root,
                [relative],
                maximum_file_size_bytes=1024,
            )

        self.assertEqual(findings, [])

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
