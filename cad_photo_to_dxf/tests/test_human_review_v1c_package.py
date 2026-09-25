"""Focused invariants for the V1C compact corrected-review package."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from PIL import Image

from app.human_review_v1c_package import build_human_review_package_v1c


REPO_ROOT = Path(__file__).resolve().parents[2]


class HumanReviewV1CTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="human-review-v1c-test-")
        root = Path(cls.temp_dir.name)
        cls.package_dir = root / "human-review-package-v1c"
        cls.zip_path = root / "human-review-package-v1c.zip"
        cls.result = build_human_review_package_v1c(
            REPO_ROOT,
            output_dir=cls.package_dir,
            zip_path=cls.zip_path,
        )
        cls.manifest = json.loads((cls.package_dir / "manifest.json").read_text(encoding="utf-8"))
        cls.html = (cls.package_dir / "review.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_exactly_24_clean_pairs_and_fresh_state(self) -> None:
        self.assertEqual(self.result.candidate_count, 24)
        self.assertEqual(self.result.clean_local_count, 24)
        self.assertEqual(self.result.clean_context_count, 24)
        self.assertEqual(self.manifest["candidate_count"], 24)
        self.assertIn('markerToggle: false', self.html)
        self.assertIn('human_label: null', self.html)
        self.assertIn("已完成 0 / 24", self.html)
        for item in self.manifest["items"]:
            for key in ("local_image", "context_image"):
                path = self.package_dir / Path(*item[key].split("/"))
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    self.assertGreater(image.width, 0)
                    self.assertGreater(image.height, 0)

    def test_exactly_four_labels_and_no_metadata_workflow(self) -> None:
        for label in (
            "STRUCTURAL_CONTINUATION",
            "ANNOTATION_OR_GLYPH",
            "AMBIGUOUS",
            "INVALID_FOR_TASK",
        ):
            self.assertIn(label, self.html)
        self.assertNotIn("POSITIVE", self.html)
        self.assertNotIn("NEGATIVE", self.html)
        for removed in ("reviewer_id", "reviewer_role", "reviewer_identity"):
            self.assertNotIn(removed, self.html)
        self.assertIn("导出审核结果 JSON", self.html)
        self.assertIn("session_id:", self.html)

    def test_compact_controls_and_collapsible_help(self) -> None:
        self.assertIn("position:fixed", self.html)
        self.assertIn('class="review-bar"', self.html)
        self.assertEqual(self.html.count('class="label-button"'), 4)
        self.assertIn('class="help"', self.html)
        self.assertIn("查看详细说明", self.html)
        self.assertIn("添加备注（可选）", self.html)
        self.assertIn("开始新的更正审核", self.html)

    def test_explicit_marker_legend_and_yellow_is_not_an_answer(self) -> None:
        self.assertIn("红 = Fragment A", self.html)
        self.assertIn("蓝 = Fragment B", self.html)
        self.assertIn("黄 = Candidate gap only; NOT a suggested connection", self.html)
        self.assertIn("Gap endpoint A", self.html)
        self.assertIn("Gap endpoint B", self.html)
        self.assertIn("黄色只表示正在判断的候选 gap / region，不表示应该填充或连接", self.html)

    def test_enlarged_clean_marked_views_use_image_coordinates(self) -> None:
        for token in (
            "function openModal",
            "modal-marker-toggle",
            "state.modal.marked",
            "preserveAspectRatio",
            "zoom-content",
            "setModalScale",
            "pointerdown",
            "pointermove",
            "wheel",
        ):
            self.assertIn(token, self.html)
        self.assertIn("if (state.markerToggle) frame.appendChild(markerSvg", self.html)
        self.assertIn("if (state.modal.marked) content.appendChild(markerSvg", self.html)
        self.assertIn("state.modal = { item:item, kind:kind, marked:Boolean(marked) }", self.html)
        self.assertIn("openModal(item, kind, state.markerToggle)", self.html)

    def test_keyboard_shortcuts_and_export_have_no_model_fields(self) -> None:
        for token in (
            'event.key === "1"',
            'event.key === "2"',
            'event.key === "3"',
            'event.key === "4"',
            'event.key === "ArrowLeft"',
            'event.key === "ArrowRight"',
            "review_exported_at",
            "source_manifest_identity",
            "review_order",
            "label_history",
        ):
            self.assertIn(token, self.html)
        self.assertNotIn("review_session_id", self.html)
        self.assertNotIn("cosine", self.html.lower())
        self.assertNotIn("centroid", self.html.lower())
        self.assertNotIn("prediction", self.html.lower())

    def test_fresh_session_is_independent_and_old_state_is_not_packaged(self) -> None:
        self.assertIn("draftsman-human-review-v1c:", self.html)
        self.assertIn("HISTORY_PREFIX", self.html)
        self.assertIn("localStorage.setItem(HISTORY_PREFIX", self.html)
        self.assertNotIn("REVIEWER_A", self.html)
        self.assertNotIn("review-state.json", self.html)
        self.assertNotIn("review-export.json", self.html)
        self.assertFalse(any(self.package_dir.rglob("*.dwg")))
        self.assertFalse(any(self.package_dir.rglob("*.pdf")))
        self.assertFalse(any(self.package_dir.rglob("*.dxf")))

    def test_static_offline_package_and_zip_contents(self) -> None:
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<link[^>]+href=")
        self.assertNotIn("fetch(", self.html)
        self.assertNotIn("XMLHttpRequest", self.html)
        external = self.html.replace("http://www.w3.org/2000/svg", "")
        self.assertIsNone(re.search(r"https?://", external))
        with zipfile.ZipFile(self.zip_path) as archive:
            names = set(archive.namelist())
        self.assertEqual(len([name for name in names if name.startswith("assets/local/")]), 24)
        self.assertEqual(len([name for name in names if name.startswith("assets/context/")]), 24)
        self.assertFalse(any(name.lower().endswith((".dwg", ".pdf", ".dxf")) for name in names))
        self.assertFalse(any("review-state" in name or "review-export" in name for name in names))


if __name__ == "__main__":
    unittest.main()
