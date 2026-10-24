"""Local checks for the new pilot only; no CAD data or frozen answers loaded."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

from data import CLASSES, load, make_artificial, validate, validate_references
from evaluate import baseline, metrics
from pilot import run

HERE = Path(__file__).resolve().parent


class DataTest(unittest.TestCase):
    def test_small_artificial_package(self):
        summary = validate(make_artificial())
        self.assertEqual((summary["train"], summary["validation"], summary["real_samples"]), (12, 6, 0))

    def test_blind_and_reserve_rejected(self):
        for split in ("LOCKED_BLIND", "blind_test", "RESERVE"):
            data = make_artificial()
            data["samples"][0]["split"] = split
            with self.assertRaises(ValueError):
                validate(data)

    def test_related_sources_cannot_cross_split(self):
        for key in ("source_family_id", "source_document_id", "source_object_id"):
            data = make_artificial()
            data["samples"][-1][key] = data["samples"][0][key]
            with self.assertRaisesRegex(ValueError, "leakage"):
                validate(data)

    def test_unknown_label_is_not_a_hard_negative(self):
        data = make_artificial()
        data["samples"][0]["label"] = "AMBIGUOUS"
        with self.assertRaises(ValueError):
            validate(data)

    def test_real_input_and_nonfinite_features_rejected(self):
        data = make_artificial()
        data["domain"] = "real"
        with self.assertRaises(ValueError):
            validate(data)
        data = make_artificial()
        data["samples"][0]["features"][0] = float("nan")
        with self.assertRaises(ValueError):
            validate(data)

    def test_reference_catalogue_rejects_blind_and_leakage(self):
        rows = [{"sample_id": "r1", "split": "train", "label": CLASSES[0],
                 "human_review_record_present": True, "truth_reference": "truth#r1",
                 "record_reference": "record#r1", "source_family_id": "family1",
                 "source_drawing_id": "drawing1"}]
        self.assertEqual(validate_references(rows)["references"], 1)
        changed = copy.deepcopy(rows)
        changed[0]["split"] = "LOCKED_BLIND"
        with self.assertRaises(ValueError):
            validate_references(changed)
        changed = copy.deepcopy(rows[0])
        changed.update(sample_id="r2", split="validation", source_drawing_id="drawing2")
        with self.assertRaisesRegex(ValueError, "leakage"):
            validate_references(rows + [changed])

    def test_reference_ambiguous_stays_evaluation_only(self):
        row = {"sample_id": "r1", "split": "validation", "label": "AMBIGUOUS",
               "human_review_record_present": True, "truth_reference": "truth#r1",
               "record_reference": "record#r1", "source_family_id": "family1",
               "source_drawing_id": "drawing1"}
        self.assertEqual(validate_references([row])["references"], 1)
        row["split"] = "train"
        with self.assertRaises(ValueError):
            validate_references([row])


class MetricsTest(unittest.TestCase):
    def test_abstention_keeps_parallel_denominator_and_unknown_role(self):
        rows = [{"label": CLASSES[1]}, {"label": CLASSES[1]}, {"label": "AMBIGUOUS"}]
        value = metrics(rows, [[0.96, 0.03, 0.01], [0.4, 0.5, 0.1], [0.4, 0.3, 0.3]], 0.9)
        self.assertEqual(value["parallel_mislabeled_single_rate"], 0.5)
        self.assertEqual(value["known_support"], 2)
        self.assertEqual(value["ambiguous_abstained"], 1)
        self.assertEqual(value["cad_actions_authorized"], 0)

    def test_invalid_predictions_fail(self):
        with self.assertRaises(ValueError):
            metrics([{"label": CLASSES[0]}], [[0.1, 0.1, 0.1]])

    def test_train_only_prior_control(self):
        data = make_artificial()["samples"]
        train = [r for r in data if r["split"] == "train"]
        validation = [r for r in data if r["split"] == "validation"]
        value = baseline(train, validation)
        self.assertEqual(value["train_prior"], [1 / 3] * 3)
        self.assertEqual(value["uniform_abstain_at_0.9"]["coverage"], 0)


class RuntimeTest(unittest.TestCase):
    def test_restart_and_resume_matches_uninterrupted_cpu(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            config = HERE / "config.json"
            dataset = HERE / "artificial-data.json"
            common = [sys.executable, str(HERE / "pilot.py"), "--dataset", str(dataset),
                      "--config", str(config), "--device", "cpu"]
            for name, steps, resume in (("first", 2, None), ("resumed", 4, "first"), ("whole", 4, None)):
                command = common + ["--steps", str(steps), "--out", str(out / name)]
                if resume:
                    command += ["--resume", str(out / resume / "checkpoint.pt")]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            resumed = torch.load(out / "resumed/checkpoint.pt", weights_only=True, map_location="cpu")
            whole = torch.load(out / "whole/checkpoint.pt", weights_only=True, map_location="cpu")
            self.assertEqual(resumed["history"], whole["history"])
            for key in resumed["model_state"]:
                self.assertTrue(torch.equal(resumed["model_state"][key], whole["model_state"][key]))
            for key, value in resumed["optimizer_state"]["state"].items():
                self.assertTrue(torch.equal(value["momentum_buffer"],
                                            whole["optimizer_state"]["state"][key]["momentum_buffer"]))

    def test_resume_rejects_changed_data_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data = load(HERE / "artificial-data.json")
            config = json.loads((HERE / "config.json").read_text())
            run(data, config, path / "first", steps=1)
            changed = copy.deepcopy(data)
            changed["samples"][0]["features"][0] += 0.01
            with self.assertRaisesRegex(ValueError, "changed"):
                run(changed, config, path / "changed", steps=2, resume=path / "first/checkpoint.pt")
            with self.assertRaisesRegex(ValueError, "new run directory"):
                run(data, config, path / "first", steps=2)

    def test_real_training_configuration_rejected(self):
        config = json.loads((HERE / "config.json").read_text())
        config["real_training_enabled"] = True
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            run(make_artificial(), config, directory)


if __name__ == "__main__":
    unittest.main()
