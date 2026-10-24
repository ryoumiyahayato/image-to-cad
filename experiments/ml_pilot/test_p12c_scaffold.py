"""Preparation contract checks only. No learner, scaler, real data or Gate0 run."""

import copy
import unittest

from p12c_numeric_pilot import admitted, execute, validate_rows, validate_separation


def artificial_row(identity="ARTIFICIAL-A", split="train"):
    return {"sample_id": identity, "split": split, "label": "OTHER",
            "features": [0.0] * 18, "missing_features": [False] * 18,
            "profile_present": False, "source_family_id": identity,
            "source_drawing_id": identity, "target_kind": "CONTROL"}


class PreparationTests(unittest.TestCase):
    def test_disabled_entry_reads_nothing(self):
        result = execute("NONEXISTENT_INPUT", "NONEXISTENT_OUTPUT", {}, requested=False)
        self.assertEqual(result["status"], "NOT_RUN")

    def test_requested_closed_admission_blocks_before_input(self):
        with self.assertRaises(PermissionError):
            execute("NONEXISTENT_INPUT", "NONEXISTENT_OUTPUT", {"enabled": False}, requested=True)

    def test_local_rights_do_not_imply_colab_rights(self):
        config = {"enabled": True, "admission": {
            "gate_1a": "GO", "label_review_resolved": True,
            "numeric_only_missing_originals_accepted": True,
            "all_17_local_rights_confirmed": True, "specific_real_fit_authorized": True,
            "authorization_reference": "ARTIFICIAL_TEST_ONLY",
        }}
        admitted(config, "local")  # Authorization logic only, no execute/fit call.
        with self.assertRaises(PermissionError):
            admitted(config, "colab")

    def test_artificial_finite_feature_contract_and_mask(self):
        row = artificial_row()
        self.assertEqual(validate_rows([row], "train"), {"ARTIFICIAL-A"})
        bad = copy.deepcopy(row)
        bad["features"][0] = float("nan")
        with self.assertRaises(ValueError):
            validate_rows([bad], "train")

    def test_ambiguity_is_not_training_truth(self):
        row = artificial_row()
        row["label"] = "AMBIGUOUS"
        with self.assertRaises(ValueError):
            validate_rows([row], "train")

    def test_source_overlap_is_rejected(self):
        a = artificial_row()
        b = artificial_row("ARTIFICIAL-B", "validation")
        b["source_family_id"] = a["source_family_id"]
        with self.assertRaises(ValueError):
            validate_separation([a], [b])


if __name__ == "__main__":
    unittest.main()
