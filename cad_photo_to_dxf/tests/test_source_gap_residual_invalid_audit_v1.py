from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = REPO_ROOT / "cad_photo_to_dxf" / "validation" / "source-gap-residual-invalid-audit-v1"
RESULTS = AUDIT_ROOT / "source-gap-residual-invalid-audit-results.json"
REPORT = AUDIT_ROOT / "SOURCE-GAP-RESIDUAL-INVALID-AUDIT-V1-FINAL.md"

RESIDUAL_IDS = {
    "FRESH1-6DA3382199DB993085B8",
    "FRESH1-EAF5141532787D12AFE2",
}


class SourceGapResidualInvalidAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = json.loads(RESULTS.read_text(encoding="utf-8"))
        cls.report = REPORT.read_text(encoding="utf-8")

    def test_exact_residual_ids_and_bounded_scope(self) -> None:
        self.assertEqual(self.results["scope"]["bounded_total"], 8)
        self.assertEqual(set(self.results["cases"]) & RESIDUAL_IDS, RESIDUAL_IDS)
        self.assertEqual(self.results["replay_checks"]["exact_residual_ids_recovered"], True)
        self.assertTrue(self.results["replay_checks"]["bounded_total_within_hard_cap"])

    def test_human_invalid_observations_and_primitive_pair_split_are_preserved(self) -> None:
        case15 = self.results["cases"]["FRESH1-6DA3382199DB993085B8"]
        case16 = self.results["cases"]["FRESH1-EAF5141532787D12AFE2"]
        self.assertEqual(case15["prior_human_observation"]["primary_class"], "INVALID_PRIMITIVE_FOR_GAP_REVIEW")
        self.assertEqual(case16["prior_human_observation"]["primary_class"], "INVALID_PRIMITIVE_FOR_GAP_REVIEW")
        self.assertEqual(case16["prior_human_observation"]["secondary_flags"], ["CROSSES_STRUCTURE"])
        for case in (case15, case16):
            self.assertEqual(case["straight_validity"]["status"], "STRAIGHT_UNCERTAIN")
            self.assertEqual(case["pair_validity_assessment"], "REJECTED")
            self.assertEqual(case["earliest_ideal_rejection_or_abstention_stage"], "PAIR_ADMISSION")
            self.assertTrue(case["current_eligibility"]["final_current_eligible"])

    def test_no_candidate_specific_fix_and_diagnostic_decision(self) -> None:
        self.assertEqual(self.results["shared_generic_failure"]["status"], "YES")
        self.assertEqual(self.results["shared_generic_failure"]["layer"], "PAIR_ADMISSION")
        self.assertFalse(self.results["pair_level_guard_implemented"])
        self.assertFalse(self.results["straight_validity_gate_changed"])
        self.assertFalse(self.results["governance"]["candidate_specific_exceptions"])
        self.assertIn("Primitive validity versus pair validity", self.report)
        self.assertIn("no pair-level guard is implemented", self.report)


if __name__ == "__main__":
    unittest.main()
