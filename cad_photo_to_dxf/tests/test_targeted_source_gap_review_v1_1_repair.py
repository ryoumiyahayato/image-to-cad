from __future__ import annotations

import json
from pathlib import Path
import unittest

from cad_photo_to_dxf.app import primitive_integrity_review_v1 as primitive
from cad_photo_to_dxf.app import targeted_source_gap_review_v1 as source_gap
from cad_photo_to_dxf.app import targeted_source_gap_review_v1_1_repair as repair


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_ROOT = REPO_ROOT / repair.TRACKED_RELATIVE
RUNTIME_ROOT = REPO_ROOT / repair.RUNTIME_RELATIVE
OLD_ROOT = REPO_ROOT / source_gap.TRACKED_RELATIVE


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TargetedSourceGapReviewV11RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repair_manifest = read_json(
            TRACKED_ROOT / "source-gap-v1-1-repair-manifest.json"
        )
        cls.selection_manifest = read_json(
            TRACKED_ROOT / "source-gap-v1-1-selection-manifest.json"
        )
        cls.replay_manifest = read_json(
            TRACKED_ROOT / "source-gap-v1-1-selection-replay.json"
        )
        cls.migration = read_json(
            TRACKED_ROOT / "source-gap-v1-1-human-state-migration.json"
        )
        cls.removed = read_json(
            TRACKED_ROOT / "source-gap-v1-1-removed-candidates.json"
        )
        cls.replacements = read_json(
            TRACKED_ROOT / "source-gap-v1-1-replacement-candidates.json"
        )
        cls.package_manifest = read_json(RUNTIME_ROOT / "review-package" / "manifest.json")
        cls.html = (RUNTIME_ROOT / "review-package" / "review.html").read_text(
            encoding="utf-8"
        )

    def test_frozen_pool_and_repair_counts(self) -> None:
        frozen = primitive._load_frozen_inputs(REPO_ROOT)
        self.assertEqual(len(frozen["pool"]), repair.FRESH_POOL_COUNT)
        self.assertEqual(self.repair_manifest["frozen_fresh_pool"], 147)
        self.assertEqual(self.repair_manifest["old_review_size"], 16)
        self.assertEqual(self.repair_manifest["invalid_current_candidates_removed"], 1)
        self.assertEqual(self.repair_manifest["retained_current_candidates"], 15)
        self.assertEqual(self.repair_manifest["replacement_candidates"], 1)
        self.assertEqual(self.repair_manifest["final_review_size"], 16)

    def test_removed_and_replacement_are_deterministic_and_eligible(self) -> None:
        old = read_json(OLD_ROOT / "source-gap-selection-manifest.json")
        self.assertEqual(
            self.selection_manifest["final_review_order"][:15], old["review_order"][:15]
        )
        self.assertEqual(
            self.selection_manifest["removed_candidate_ids"],
            ["FRESH1-EDC71A4759AD64EDCE78"],
        )
        self.assertEqual(
            self.selection_manifest["replacement_candidate_ids"],
            ["FRESH1-91191386DC95E23BEDAC"],
        )
        replacement = self.replacements["replacement_candidates"][0]
        self.assertEqual(replacement["diagnostic_stratum"], "AMBIGUOUS_EDGE_CASES")
        self.assertEqual(replacement["selection_score"]["eligible_rank"], 1)
        self.assertEqual(replacement["text_glyph_status"], "TEXT_UNCERTAIN")
        self.assertEqual(replacement["text_eligibility"], "ELIGIBLE_UNCHANGED")
        self.assertEqual(replacement["span_status"], "SPAN_INTEGRITY_SUPPORTED")
        self.assertEqual(replacement["axis_status"], "AXIS_SUPPORT_SUPPORTED")
        self.assertEqual(replacement["admissibility_status"], "DIRECT_CONTINUATION_ADMISSIBLE")
        pool = {row["candidate_id"]: row for row in primitive._load_frozen_inputs(REPO_ROOT)["pool"]}
        self.assertIn(replacement["candidate_id"], pool)
        self.assertEqual(
            pool[replacement["candidate_id"]]["direct_continuation"]["status"],
            "DIRECT_CONTINUATION_ADMISSIBLE",
        )

    def test_selection_replay_passes_and_has_no_duplicates(self) -> None:
        self.assertEqual(self.replay_manifest["status"], "PASS")
        self.assertEqual(
            self.replay_manifest["selection_deterministic_replay"], "PASS"
        )
        records = self.selection_manifest["records"]
        self.assertEqual(len({row["candidate_id"] for row in records}), 16)
        self.assertEqual(
            len({source_gap.primitive._exact_primitive_key(row) for row in records}), 16
        )
        self.assertTrue(self.selection_manifest["retained_order_preserved"])

    def test_human_state_migration_preserves_retained_and_blanks_replacement(self) -> None:
        self.assertEqual(self.migration["status"], "PASS")
        self.assertEqual(self.migration["migrated_answer_count"], 15)
        self.assertEqual(self.migration["removed_human_answer_history_count"], 1)
        self.assertEqual(self.migration["replacement_answers_prefilled"], "NO")
        replacement_id = self.selection_manifest["replacement_candidate_ids"][0]
        replacement_state = next(
            row for row in self.migration["initial_review_state"]
            if row["candidate_id"] == replacement_id
        )
        self.assertIsNone(replacement_state["primary_class"])
        self.assertEqual(replacement_state["secondary_flags"], [])
        self.assertEqual(replacement_state["optional_note"], "")
        removed_answer = self.removed["removed_candidates"][0]["prior_human_answer"]
        self.assertEqual(removed_answer["primary_class"], "STRUCTURAL_INTERRUPTION")
        self.assertEqual(removed_answer["secondary_flags"], ["ENDPOINT_ANOMALY"])
        self.assertNotIn(replacement_id, {
            row["candidate_id"]
            for row in self.migration["removed_human_answers_retained_as_history"]
        })

    def test_migrated_retained_answers_match_verified_export_exactly(self) -> None:
        export_path = Path.home() / "Downloads" / self.migration["source"]["source_file_name"]
        if not export_path.is_file():
            self.skipTest("verified Downloads human export is not present")
        exported = read_json(export_path)
        exported_by_id = {row["candidate_id"]: row for row in exported}
        migrated_by_id = {
            row["candidate_id"]: row for row in self.migration["migrated_human_answers"]
        }
        self.assertEqual(len(migrated_by_id), 15)
        for candidate_id, migrated in migrated_by_id.items():
            original = exported_by_id[candidate_id]
            self.assertEqual(migrated["primary_class"], original["primary_class"])
            self.assertEqual(migrated["secondary_flags"], original["secondary_flags"])
            self.assertEqual(migrated["optional_note"], original["optional_note"])

    def test_repaired_package_revision_and_fail_closed_ui(self) -> None:
        self.assertEqual(self.package_manifest["package_id"], repair.PACKAGE_ID)
        self.assertEqual(self.package_manifest["package_revision"], repair.PACKAGE_REVISION)
        self.assertEqual(self.package_manifest["candidate_count"], 16)
        for label in (
            "连续实线",
            "原图本来就分段",
            "规律分段 / 虚线",
            "被结构打断",
            "像是破损或扫描缺失",
            "看不清",
            "候选本身无效",
            "红线本身就不是一根应当进行断开分析的有效直线。",
        ):
            self.assertIn(label, self.html)
        self.assertIn("INVALID_PRIMITIVE_FOR_GAP_REVIEW", self.html)
        self.assertIn('<span class="shortcut">7</span>', self.html)
        self.assertIn("newSession(withInitial)", self.html)
        self.assertIn("PACKAGE.legacy_import", self.html)
        self.assertNotIn("machine_verdict", self.html)
        self.assertNotIn("selection_stratum", self.html)
        self.assertNotIn("diagnostic_measurements_used", self.html)
        self.assertIn("primary_class:null", self.html)
        self.assertIn("secondary_flags:[]", self.html)
        self.assertIn('optional_note:""', self.html)

    def test_export_validation_accepts_new_safety_value_and_old_protocol(self) -> None:
        old = read_json(OLD_ROOT / "source-gap-selection-manifest.json")
        rows = [
            {
                "protocol": source_gap.PROTOCOL,
                "candidate_set_id": old["candidate_set_id"],
                "candidate_id": candidate_id,
                "review_index": index,
                "primary_class": "INVALID_PRIMITIVE_FOR_GAP_REVIEW" if index == 16 else None,
                "secondary_flags": [],
                "optional_note": "",
            }
            for index, candidate_id in enumerate(old["review_order"], start=1)
        ]
        normalized = source_gap.validate_review_export(
            rows, old["candidate_set_id"], old["review_order"]
        )
        self.assertEqual(normalized[15]["primary_class"], "INVALID_PRIMITIVE_FOR_GAP_REVIEW")
        self.assertEqual(normalized[0]["protocol"], "SOURCE_GAP_REVIEW_V1")

    def test_static_package_qa(self) -> None:
        validation = source_gap.validate_review_package(RUNTIME_ROOT / "review-package")
        self.assertEqual(validation["four_view_assets"], "PASS")
        self.assertEqual(validation["click_to_enlarge"], "PASS")
        self.assertEqual(validation["import_export"], "PASS")


if __name__ == "__main__":
    unittest.main()
