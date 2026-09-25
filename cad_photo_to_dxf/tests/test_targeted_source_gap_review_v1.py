from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from cad_photo_to_dxf.app.targeted_source_gap_review_v1 import (
    BASE_CHECKPOINT,
    FRESH_POOL_COUNT,
    MAX_PRIOR_REVIEWED_ANCHORS,
    PRIMARY_CLASSES,
    PROTOCOL,
    SECONDARY_FLAGS,
    STRATUM_TARGETS,
    TARGET_REVIEW_SIZE,
    _load_prior_reviewed_ids,
    _select_target,
    _selection_digest,
    build_review_package,
    replay_selection,
    validate_review_export,
    validate_review_package,
)
from cad_photo_to_dxf.app import targeted_source_gap_review_v1 as source_gap


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_ROOT = REPO_ROOT / "cad_photo_to_dxf" / "validation" / "targeted-source-gap-review-v1"


class TargetedSourceGapReviewV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = source_gap.primitive._load_frozen_inputs(REPO_ROOT)
        pool_ids = {str(item["candidate_id"]) for item in cls.frozen["pool"]}
        cls.prior_ids, _ = _load_prior_reviewed_ids(REPO_ROOT, pool_ids)
        cls.diagnostics = source_gap.primitive._load_diagnostics(REPO_ROOT, pool_ids)
        cls.records = _select_target(REPO_ROOT, cls.frozen["pool"], cls.prior_ids, cls.diagnostics)
        cls.digest = _selection_digest(cls.records, str(cls.frozen["runtime"]["candidate_set_id"]))
        cls.candidate_set_id = f"{cls.frozen['runtime']['candidate_set_id']}-SOURCE-GAP-{cls.digest[:12].upper()}"
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="source-gap-review-v1-test-", dir=str(REPO_ROOT / "local-artifacts"))
        temp_root = Path(cls.temp_dir.name)
        cls.package_dir = temp_root / "review-package"
        cls.package_zip = temp_root / "review-package.zip"
        cls.package_manifest, cls.package_validation = build_review_package(
            REPO_ROOT, cls.records, cls.candidate_set_id,
            {"source_frozen_pool_count": FRESH_POOL_COUNT, "selection_digest": cls.digest},
            output_dir=cls.package_dir, zip_path=cls.package_zip, replace=True,
        )
        cls.html = (cls.package_dir / "review.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_frozen_pool_selection_uniqueness_and_replay(self) -> None:
        self.assertEqual(len(self.frozen["pool"]), FRESH_POOL_COUNT)
        self.assertEqual(len(self.records), TARGET_REVIEW_SIZE)
        self.assertEqual(len({row["candidate_id"] for row in self.records}), TARGET_REVIEW_SIZE)
        self.assertEqual(len({source_gap.primitive._exact_primitive_key(row) for row in self.records}), TARGET_REVIEW_SIZE)
        new_count = sum(row["new_or_prior_reviewed"] == "NEW_UNREVIEWED" for row in self.records)
        anchor_count = TARGET_REVIEW_SIZE - new_count
        self.assertGreaterEqual(new_count, 12)
        self.assertLessEqual(anchor_count, MAX_PRIOR_REVIEWED_ANCHORS)
        manifest = json.loads((TRACKED_ROOT / "source-gap-selection-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(replay_selection(REPO_ROOT, manifest)["status"], "PASS")

    def test_balanced_strata_and_source_orientation_diversity(self) -> None:
        counts = dict(sorted(source_gap.Counter(row["selection_stratum"] for row in self.records).items()))
        self.assertEqual(counts, dict(sorted(STRATUM_TARGETS.items())))
        self.assertGreaterEqual(len({row["source_family"] for row in self.records}), 8)
        self.assertGreaterEqual(len({row["source_unit"] for row in self.records}), 8)
        self.assertGreater(sum(row["orientation"] == "horizontal" for row in self.records), 0)
        self.assertGreater(sum(row["orientation"] == "vertical" for row in self.records), 0)

    def test_chinese_blind_v2_ui_and_empty_state(self) -> None:
        for label in ("连续实线", "原图本来就分段", "规律分段 / 虚线", "被结构打断", "像是破损或扫描缺失", "看不清", "局部原图", "局部红线", "整体原图", "整体红线", "点击图片可放大", "备注（可选）"):
            self.assertIn(label, self.html)
        for value in PRIMARY_CLASSES + SECONDARY_FLAGS:
            self.assertIn(value, self.html)
            self.assertNotIn(f">{value}<", self.html)
        for token in ("primary_class:null", "secondary_flags:[]", 'optional_note:""', ".evidence-grid", ".data-menu", "function setModalScale", "pointerdown", "wheel"):
            self.assertIn(token, self.html)
        for forbidden in ("selection_stratum", "periodicity_score", "degradation_score", "diagnostic_hypothesis", "machine_verdict", "previous_human_label", "expected_answer", "support_fraction", "position:sticky", ".review-controls"):
            self.assertNotIn(forbidden, self.html)

    def test_four_views_gap_markers_and_translucent_overlay(self) -> None:
        self.assertEqual(validate_review_package(self.package_dir)["four_view_assets"], "PASS")
        self.assertEqual(len(self.package_manifest["items"]), TARGET_REVIEW_SIZE)
        for item in self.package_manifest["items"]:
            for kind in ("local", "context"):
                marker = item["marker"][kind]
                self.assertIn("gap_start", marker)
                self.assertIn("gap_end", marker)
                clean_path = self.package_dir / Path(*item[f"{kind}_clean_image"].split("/"))
                overlay_path = self.package_dir / Path(*item[f"{kind}_overlay_image"].split("/"))
                with Image.open(clean_path) as clean, Image.open(overlay_path) as overlay:
                    self.assertEqual(clean.size, overlay.size)
        source = (REPO_ROOT / "cad_photo_to_dxf/app/targeted_source_gap_review_v1.py").read_text(encoding="utf-8")
        self.assertIn("(224, 28, 45, 150)", source)

    def test_import_export_is_deterministic_and_notes_verbatim(self) -> None:
        note = "  断口附近有褪色\n保留空格  "
        rows = [{"protocol": PROTOCOL, "candidate_set_id": self.candidate_set_id, "candidate_id": row["candidate_id"], "review_index": row["review_index"], "primary_class": PRIMARY_CLASSES[index % len(PRIMARY_CLASSES)], "secondary_flags": [SECONDARY_FLAGS[index % len(SECONDARY_FLAGS)]], "optional_note": note if index == 0 else ""} for index, row in enumerate(self.records)]
        first = validate_review_export(rows, self.candidate_set_id, [row["candidate_id"] for row in self.records])
        second = validate_review_export(first, self.candidate_set_id, [row["candidate_id"] for row in self.records])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["optional_note"], note)

    def test_package_contains_no_source_documents_or_internal_diagnostics(self) -> None:
        with zipfile.ZipFile(self.package_zip) as archive:
            names = archive.namelist()
        self.assertFalse(any(name.lower().endswith((".pdf", ".dwg", ".dxf")) for name in names))
        self.assertFalse(any("selection-runtime" in name or "selection-diagnostics" in name for name in names))

    def test_outdated_test_audit_and_governance_are_explicit(self) -> None:
        audit = json.loads((TRACKED_ROOT / "outdated-patterned-test-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["affected_test_count"], 6)
        self.assertEqual(audit["summary"], {"KEEP": 3, "RENAME": 1, "REWRITE": 2, "DEPRECATE": 0})
        self.assertFalse(audit["patterned_stroke_reinterpretation"]["equivalent"])
        self.assertFalse(audit["scan_degradation_safety_weakened"])
        source = (REPO_ROOT / "cad_photo_to_dxf/app/targeted_source_gap_review_v1.py").read_text(encoding="utf-8")
        for forbidden in ("run_fresh_remine(", "MobileNet", "cosine_classifier", "ocr_semantic("):
            self.assertNotIn(forbidden, source)
        self.assertEqual(BASE_CHECKPOINT, "9b11815940e37fef2f6bc63b95ad7c4432c5ef98")


if __name__ == "__main__":
    unittest.main()
