"""Source-correspondence checks only; no real labels or ML training are written."""

import copy
import unittest

import numpy as np
from PIL import Image

from post_label_audit import correspondence


class CorrespondenceChecks(unittest.TestCase):
    def setUp(self):
        gray = np.full((256, 256), 255, np.uint8)
        gray[80, 35:186] = 0
        gray[120, 35:186] = 0
        self.patch = Image.fromarray(gray)
        self.row = {
            "source_bbox": [0, 0, 256, 256],
            "target_kind": "PAIR",
            "candidate_geometry": [
                ["a", [40, 80, 180, 80], "test"],
                ["b", [40, 120, 180, 120], "test"],
            ],
        }

    def test_quality_is_class_blind_and_preserves_input(self):
        original = copy.deepcopy(self.row)
        first = correspondence(self.row, self.patch)
        self.row["label"] = "TRUE_PARALLEL_STRUCTURE"
        second = correspondence(self.row, self.patch)
        self.row["label"] = "OTHER"
        third = correspondence(self.row, self.patch)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(first["nomination_quality"], "NOMINATION_STRONG")
        self.row.pop("label")
        self.assertEqual(original, self.row)

    def test_small_alignment_defect_is_review_not_exclusion(self):
        self.row["candidate_geometry"][0][1] = [40, 81.4, 180, 81.4]
        result = correspondence(self.row, self.patch)
        self.assertEqual(result["nomination_quality"], "NOMINATION_BORDERLINE")
        self.assertIn("A_IMPERFECT_INK_CORRESPONDENCE", result["reasons"])

    def test_floating_partner_is_poor(self):
        self.row["candidate_geometry"][1][1] = [40, 170, 180, 170]
        result = correspondence(self.row, self.patch)
        self.assertEqual(result["nomination_quality"], "NOMINATION_POOR")
        self.assertEqual(result["independent_metrics"]["B"]["SOURCE_SUPPORT_RATIO"], 0)

    def test_unequal_supported_pair_extents_are_borderline(self):
        self.row["candidate_geometry"][1][1] = [60, 120, 160, 120]
        result = correspondence(self.row, self.patch)
        self.assertEqual(result["nomination_quality"], "NOMINATION_BORDERLINE")
        self.assertIn("PAIR_UNEQUAL_EXTENT", result["reasons"])

    def test_control_has_explicit_roi_and_na_line_metrics(self):
        self.row.update(
            candidate_geometry=[], target_kind="CONTROL", target_roi=[40, 78, 40, 5]
        )
        result = correspondence(self.row, self.patch)
        self.assertEqual(result["nomination_quality"], "NOMINATION_STRONG")
        self.assertIn(
            "NOT_APPLICABLE", result["independent_metrics"]["CONTROL"]["LINE_METRICS"]
        )
        self.row["target_roi"] = [40, 160, 40, 5]
        self.assertEqual(
            correspondence(self.row, self.patch)["nomination_quality"],
            "NOMINATION_POOR",
        )


if __name__ == "__main__":
    unittest.main()
