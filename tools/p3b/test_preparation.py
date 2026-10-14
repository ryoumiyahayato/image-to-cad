"""P3B contract tests, independent of the production regression suite."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from common import LABELS, read, validate_samples, write_rows
from benchmark import evaluate, score
from extract import render_channels
from label_ui import LabelApp, LabelStore
from synthetic import SCENES, WIDTHS, generate, truth
from active_learning import select
from features import feature_vector, image_tensor
from p3a_baseline import measure


def row(sid="a", drawing="a", label=None, partition="train"):
    return {
        "sample_id": sid,
        "source_drawing_id": drawing,
        "source_family_id": drawing,
        "source_page": 1,
        "source_bbox": [0, 0, 256, 256],
        "candidate_geometry_ids": [],
        "source_dpi": None,
        "current_p3a_measurement": [],
        "current_deterministic_decision": "NOT_CAPTURED",
        "label": label,
        "label_provenance": None,
        "split": partition,
        "source_sha256": drawing,
        "patch_sha256": sid,
        "patch_dir": sid,
        "domain": "real",
        "label_contract": "p3b-label-v2",
        "target_kind": "CONTROL",
        "target_roi": [100, 100, 20, 20],
        "candidate_geometry": [],
        "quality": {
            "HUMAN_QUEUE_ELIGIBLE": True,
            "metrics": {"TARGET_INK_PIXELS": 400},
        },
    }


class Contracts(unittest.TestCase):
    def test_frozen_p3a_baseline_recovers_clean_control_and_vetoes_parallels(self):
        gray = np.full((100, 180), 255, np.uint8)
        gray[47:54, 20:161] = 0
        candidates = [
            ("a", [20, 47, 160, 47], "synthetic"),
            ("b", [20, 53, 160, 53], "synthetic"),
        ]
        affine = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        profiles, decision, _ = measure(
            gray, candidates, {"primitives": []}, 1.0, affine, 300
        )
        self.assertEqual(decision, "MERGE_PROPOSED_OFFLINE")
        self.assertEqual(profiles[0]["profile"]["source_width_px"], 7)
        gray[48:53, 20:161] = 255
        _, decision, _ = measure(gray, candidates, {"primitives": []}, 1.0, affine, 300)
        self.assertEqual(decision, "PRESERVE_OFFLINE")

    def test_leakage_guards(self):
        for field in (
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
        ):
            a, b = row("a", "a"), row("b", "b", partition="validation")
            b[field] = a[field]
            with self.assertRaises(ValueError):
                validate_samples([a, b])

    def test_synthetic_blind_and_text_guards(self):
        r = row(partition="blind_test")
        r["domain"] = "synthetic"
        with self.assertRaises(ValueError):
            validate_samples([r])
        r = row(label=LABELS[0])
        r["content_role"] = "text"
        with self.assertRaises(ValueError):
            validate_samples([r])

    def test_safety_metrics_and_missing_support(self):
        rows = [
            row("a", "a", LABELS[1]),
            row("b", "b", LABELS[1]),
            row("c", "c", LABELS[0]),
            row("d", "d", LABELS[3]),
        ]
        probabilities = [
            [0.9, 0.05, 0.03, 0.02],
            [0.01, 0.98, 0.005, 0.005],
            [0.97, 0.01, 0.01, 0.01],
            [0.1, 0.1, 0.1, 0.7],
        ]
        predictions = [
            {"sample_id": r["sample_id"], "probabilities": dict(zip(LABELS, p))}
            for r, p in zip(rows, probabilities)
        ]
        result = evaluate(rows, predictions)
        self.assertEqual(result["overall"]["FALSE_MERGE_RATE"], 0.5)
        self.assertEqual(result["overall"]["per_class"][LABELS[0]]["precision"], 0.5)
        self.assertEqual(result["overall"]["AMBIGUOUS_truth_coverage"], 0.25)
        at95 = next(x for x in result["overall"]["selective"] if x["threshold"] == 0.95)
        self.assertEqual(at95["selective_accuracy"], 1)
        self.assertIsNone(score([], [])["FALSE_MERGE_RATE"])
        with self.assertRaises(ValueError):
            score(
                rows, [{"sample_id": "a", "probabilities": dict.fromkeys(LABELS, 0.7)}]
            )

    def test_channels_and_feature_contract(self):
        gray = np.full((512, 512), 255, np.uint8)
        lines = [
            ("one", [100, 140, 300, 140], "proposal"),
            ("two", [100, 144, 300, 144], "proposal"),
        ]
        channels = render_channels(
            gray, [100, 100, 256, 256], lines, [[150, 130, 10, 10]], [(150, 140)]
        )
        self.assertEqual(np.array(channels[1])[40, 0], 255)
        self.assertEqual(np.array(channels[2])[42, 0], 255)
        self.assertEqual(np.array(channels[3])[30, 50], 255)
        self.assertTrue(np.array(channels[4])[40, 50])
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            for name, channel in zip(("gray", "edges", "centerline"), channels):
                channel.save(folder / (name + ".png"))
            self.assertEqual(image_tensor(row(), folder).shape, (3, 256, 256))
            self.assertEqual(feature_vector(row(), folder).shape, (18,))
            self.assertTrue(np.isfinite(feature_vector(row(), folder)).all())

    def test_labels_atomic_undo_resume_and_manifest_binding(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            manifest, labels = path / "samples.jsonl", path / "labels.json"
            write_rows(manifest, [row()])
            store = LabelStore(labels, manifest, "tester")
            store.nominate(row(), "VALID_TARGET")
            store.assign(row(), LABELS[3])
            previous = labels.read_bytes()
            with patch("common.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    store.assign(row(), LABELS[0])
            self.assertEqual(labels.read_bytes(), previous)
            resumed = LabelStore(labels, manifest, "tester")
            self.assertEqual(resumed.state["labels"]["a"]["label"], LABELS[3])
            resumed.undo()
            self.assertEqual(read(labels)["labels"], {})
            write_rows(manifest, [row("changed")])
            with self.assertRaises(ValueError):
                LabelStore(labels, manifest, "tester")

    def test_synthetic_truth_repeatability_and_splits(self):
        self.assertEqual(WIDTHS, (0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00))
        for scene in SCENES:
            self.assertEqual(truth(scene, 0.25, 100), truth(scene, 0.25, 100))
        self.assertEqual(truth("isolated", 0.25, 100)["class"], LABELS[0])
        self.assertEqual(truth("parallel", 0.25, 100)["class"], LABELS[1])
        self.assertEqual(truth("text", 0.25, 100)["class"], LABELS[2])
        with tempfile.TemporaryDirectory() as td:
            rows = generate(Path(td), variants=1)
            validate_samples(rows)
            self.assertEqual(len(rows), 98)
            self.assertFalse(any(r["split"] == "blind_test" for r in rows))
            for r in rows:
                with Image.open(Path(td) / r["patch_dir"] / "gray.png") as image:
                    self.assertEqual(image.size, (256, 256))

    def test_active_source_caps_and_spatial_dedup(self):
        rows = [row(str(i), "drawing-" + str(i // 3)) for i in range(12)]
        for i, r in enumerate(rows):
            r["source_bbox"] = [i * 500, 0, 256, 256]
        scores = [
            {"sample_id": r["sample_id"], "probabilities": dict.fromkeys(LABELS, 0.25)}
            for r in rows
        ]
        chosen = select(rows, scores, count=8, per_drawing=1)
        self.assertEqual(len(chosen), 4)
        rows[0]["split"] = "validation"
        with self.assertRaises(ValueError):
            select(rows, scores)

    def test_tk_workflow_without_real_labels(self):
        import tkinter as tk

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            rows = [row("one", "a"), row("two", "b")]
            for r in rows:
                folder = base / r["patch_dir"]
                folder.mkdir()
                for name in ("gray", "overlay", "context", "support"):
                    image = Image.new("RGB", (256, 256), "white")
                    ImageDraw.Draw(image).rectangle((100, 100, 120, 120), fill="black")
                    image.save(folder / (name + ".png"))
            manifest = base / "samples.jsonl"
            write_rows(manifest, rows)
            window = tk.Tk()
            window.withdraw()
            try:
                app = LabelApp(window, manifest, base / "labels.json", "UI-test")
                window.update()
                app.toggle_context()
                app.choose(4)
                self.assertEqual(app.store.state["labels"], {})
                self.assertTrue(
                    all(str(b.cget("state")) == "disabled" for b in app.class_buttons)
                )
                app.nominate("VALID_TARGET")
                app.choose(4)
                app.skip()
                app.undo()
                app.undo()
                self.assertEqual(app.index, 0)
                self.assertEqual(app.store.state["labels"], {})
                self.assertTrue(window.bind("<BackSpace>"))
                self.assertTrue(window.bind("<space>"))
                for key in "1234vxud":
                    self.assertTrue(window.bind(key))
            finally:
                window.destroy()


if __name__ == "__main__":
    unittest.main()
