"""Focused tests for the portable Reviewer-B expert package."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from PIL import Image

from app.expert_review_package import build_expert_review_package


REPO_ROOT = Path(__file__).resolve().parents[2]


class ExpertReviewPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="expert-review-package-test-")
        root = Path(cls.temp_dir.name)
        cls.package_dir = root / "expert-review-package-v1"
        cls.zip_path = root / "expert-review-package-v1.zip"
        cls.result = build_expert_review_package(
            REPO_ROOT,
            output_dir=cls.package_dir,
            zip_path=cls.zip_path,
        )
        cls.manifest = json.loads((cls.package_dir / "manifest.json").read_text(encoding="utf-8"))
        cls.html = (cls.package_dir / "review.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_exactly_24_clean_pairs_exist(self) -> None:
        self.assertEqual(self.result.candidate_count, 24)
        self.assertEqual(self.result.clean_local_count, 24)
        self.assertEqual(self.result.clean_context_count, 24)
        self.assertEqual(self.manifest["candidate_count"], 24)
        self.assertEqual(len(self.manifest["items"]), 24)
        for item in self.manifest["items"]:
            for key in ("local_image", "context_image"):
                path = self.package_dir / Path(*item[key].split("/"))
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    self.assertGreater(image.width, 0)
                    self.assertGreater(image.height, 0)
                    sample = image.convert("RGB").resize((64, 64))
                    self.assertFalse(
                        any(
                            max(pixel) - min(pixel) > 18
                            for pixel in sample.getdata()
                        ),
                        path,
                    )

    def test_clean_view_is_default_and_markers_are_optional(self) -> None:
        self.assertIn('viewMode:"CLEAN"', self.html)
        self.assertIn('markerToggle:false', self.html)
        self.assertIn("清洁视图 · 原图未加候选图形", self.html)
        self.assertIn("显示候选标记", self.html)
        self.assertIn("清洁证据（无标记）", self.html)
        self.assertIn("候选标记（可选）", self.html)

    def test_marker_legend_and_exact_four_labels_exist(self) -> None:
        for text in ("Fragment A", "Fragment B", "Gap endpoint A", "Gap endpoint B"):
            self.assertIn(text, self.html)
        for label in (
            "STRUCTURAL_CONTINUATION",
            "ANNOTATION_OR_GLYPH",
            "AMBIGUOUS",
            "INVALID_FOR_TASK",
        ):
            self.assertIn(label, self.html)
        self.assertNotIn("POSITIVE", self.html)
        self.assertNotIn("NEGATIVE", self.html)

    def test_expert_package_excludes_reviewer_a_and_full_sources(self) -> None:
        self.assertFalse(self.manifest["governance"]["reviewer_a_data_included"])
        self.assertFalse(self.manifest["governance"]["source_full_documents_included"])
        self.assertNotIn("REVIEWER_A", self.html)
        self.assertNotIn("review-state.json", self.html)
        self.assertNotIn("review-export.json", self.html)
        self.assertFalse(any(self.package_dir.rglob("*.dwg")))
        self.assertFalse(any(self.package_dir.rglob("*.pdf")))
        self.assertFalse(any(self.package_dir.rglob("*.dxf")))

    def test_package_is_static_and_offline(self) -> None:
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<link[^>]+href=")
        self.assertNotIn("fetch(", self.html)
        self.assertNotIn("XMLHttpRequest", self.html)
        self.assertNotRegex(self.html, r"(?:src|href)=[\"']https?://")
        self.assertIn("导出审核结果 JSON", self.html)
        self.assertIn("source_manifest_identity", self.html)
        self.assertIn("review_session_id", self.html)
        self.assertIn("review_exported_at", self.html)

    def test_fresh_reviewer_b_state_has_no_labels(self) -> None:
        self.assertIn("function newSession()", self.html)
        self.assertIn("human_label:null", self.html)
        self.assertIn("review_status:\"PENDING\"", self.html)
        self.assertNotIn('"human_label":"STRUCTURAL_CONTINUATION"', self.html)
        self.assertNotIn('"human_label":"ANNOTATION_OR_GLYPH"', self.html)
        self.assertNotIn('"human_label":"AMBIGUOUS"', self.html)
        self.assertNotIn('"human_label":"INVALID_FOR_TASK"', self.html)

    def test_manifest_has_neutral_order_and_marker_geometry(self) -> None:
        ids = [item["candidate_id"] for item in self.manifest["items"]]
        self.assertEqual(ids, self.manifest["review_order"])
        self.assertEqual([item["review_index"] for item in self.manifest["items"]], list(range(1, 25)))
        for item in self.manifest["items"]:
            marker = item["marker"]
            for view in ("local", "context"):
                self.assertGreater(marker[view]["width"], 0)
                self.assertGreater(marker[view]["height"], 0)
                self.assertIn("fragment_a", marker[view])
                self.assertIn("fragment_b", marker[view])
                self.assertIn("gap_endpoint_a", marker[view])
                self.assertIn("gap_endpoint_b", marker[view])

    def test_zip_contains_only_portable_package(self) -> None:
        with zipfile.ZipFile(self.zip_path) as archive:
            names = set(archive.namelist())
        self.assertIn("review.html", names)
        self.assertIn("manifest.json", names)
        self.assertIn("README.txt", names)
        self.assertEqual(len([name for name in names if name.startswith("assets/local/")]), 24)
        self.assertEqual(len([name for name in names if name.startswith("assets/context/")]), 24)
        self.assertFalse(any(name.lower().endswith((".dwg", ".pdf", ".dxf")) for name in names))
        self.assertFalse(any("review-state" in name or "review-export" in name for name in names))


if __name__ == "__main__":
    unittest.main()
