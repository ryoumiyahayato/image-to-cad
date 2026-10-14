"""Nomination-quality and two-stage workflow tests; no model training."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from common import LABELS, ROOT, digest, read, read_rows, sha, write_rows
from benchmark import join_labels
from label_ui import LabelStore
from quality import inspect
from prepare_v2 import local_geometry
from queue_dedup import deduplicate
from target_view import target_overlay, annotated_zoom
from test_preparation import row


class V2Contract(unittest.TestCase):
    def test_floating_partner_rejected_and_geometry_unmodified(self):
        gray = np.full((256, 256), 255, np.uint8)
        gray[80, 40:181] = 0
        candidate = row()
        candidate.update(
            candidate_geometry=[
                ("a", [40, 80, 180, 80], "test"),
                ("b", [40, 120, 180, 120], "test"),
            ],
            candidate_geometry_ids=["a", "b"],
        )
        original = digest(candidate)
        q = inspect(candidate, gray)
        self.assertFalse(q["HUMAN_QUEUE_ELIGIBLE"])
        self.assertIn("PARTNER_EDGE_MISSING_OR_FLOATING", q["rejection_reasons"])
        self.assertEqual(q["metrics"]["B_SOURCE_SUPPORT_RATIO"], 0)
        self.assertGreater(q["metrics"]["B_MEDIAN_DISTANCE_TO_DARK_INK"], 30)
        self.assertEqual(digest(candidate), original)
        gray[120, 40:181] = 0
        self.assertTrue(inspect(candidate, gray)["HUMAN_QUEUE_ELIGIBLE"])

    def test_no_target_clipping_and_extent_rejection(self):
        gray = np.zeros((256, 256), np.uint8)
        candidate = row()
        candidate.pop("target_roi")
        candidate.pop("target_kind")
        self.assertIn(
            "NO_EXPLICIT_TARGET_OVERLAY", inspect(candidate, gray)["rejection_reasons"]
        )
        candidate["candidate_geometry"] = [
            ("a", [-30, 80, 300, 80], "test"),
            ("b", [70, 100, 150, 100], "test"),
        ]
        result = inspect(candidate, gray)
        self.assertIn("TARGET_CLIPPED", result["rejection_reasons"])
        self.assertIn("SEVERE_EXTENT_MISMATCH", result["rejection_reasons"])
        local = local_geometry(candidate["candidate_geometry"], [128, 90])
        self.assertEqual(len(local), 2)
        self.assertLessEqual(
            abs((local[0][1][2] - local[0][1][0]) - (local[1][1][2] - local[1][1][0])),
            1e-6,
        )

    def test_stage_0_required_invalid_and_unclear_cannot_have_class(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "samples.jsonl"
            write_rows(manifest, [row()])
            store = LabelStore(base / "labels.json", manifest, "test")
            for status in (None, "INVALID_NOMINATION", "UNCLEAR_TARGET"):
                if status:
                    store.nominate(row(), status)
                with self.assertRaises(ValueError):
                    store.assign(row(), LABELS[2])
            store.nominate(row(), "VALID_TARGET")
            store.assign(row(), LABELS[3])
            self.assertEqual(
                read(base / "labels.json")["labels"]["a"]["nomination_status"],
                "VALID_TARGET",
            )
            store.nominate(row(), "INVALID_NOMINATION")
            self.assertEqual(store.state["labels"], {})
            self.assertFalse(store.state["training_authorized"])
            self.assertTrue(store.state["review_log"])

    def test_zero_support_cannot_enter_stage_1(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "samples.jsonl"
            write_rows(manifest, [row()])
            store = LabelStore(base / "labels.json", manifest, "test")
            candidate = row()
            candidate["quality"]["metrics"]["TARGET_INK_PIXELS"] = 0
            with self.assertRaises(ValueError):
                store.nominate(candidate, "VALID_TARGET")

    def test_v1_labels_frozen_and_training_consumers_refuse(self):
        docs = ROOT / "docs/product-fix-p3b"
        before = sha(docs / "labels/local-labels.json")
        with self.assertRaises(ValueError):
            LabelStore(
                docs / "labels/local-labels.json",
                docs / "real-candidates.jsonl",
                "test",
            )
        with self.assertRaises(ValueError):
            join_labels(
                read_rows(docs / "real-candidates.jsonl"),
                read(docs / "labels/local-labels.json"),
            )
        from classical import run

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "not training-authorized"):
                run(
                    docs / "real-candidates.jsonl",
                    docs / "labels/local-labels.json",
                    Path(td),
                )
        self.assertEqual(sha(docs / "labels/local-labels.json"), before)

    def test_persistent_cursor_skip_undo(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "samples.jsonl"
            write_rows(manifest, [row("a"), row("b")])
            store = LabelStore(base / "labels.json", manifest, "test")
            store.present(row("a"), 0)
            store.skip(row("a"))
            store.present(row("b"), 1)
            resumed = LabelStore(base / "labels.json", manifest, "test")
            self.assertEqual(resumed.state["cursor_sample_id"], "b")
            self.assertIn("a", resumed.state["skipped"])
            self.assertEqual(resumed.undo(), "a")
            self.assertNotIn("a", resumed.state["skipped"])

    def test_overlay_members_colors_endpoints_and_pixel_zoom(self):
        image = Image.new("L", (256, 256), 255)
        candidate = row()
        candidate.update(
            candidate_geometry=[
                ("a", [40, 80, 180, 80], "test"),
                ("b", [40, 120, 180, 120], "test"),
            ]
        )
        overlay = np.array(target_overlay(image, candidate))
        self.assertTrue(np.any(np.all(overlay == [227, 41, 54], axis=2)))
        self.assertTrue(np.any(np.all(overlay == [0, 126, 174], axis=2)))
        self.assertEqual(annotated_zoom(image, candidate, 8).size, (512, 512))

    def test_dedup_preserves_source_and_distinct_pair_gap(self):
        a = row("a", "drawing-a")
        a.update(
            target_kind="PAIR",
            candidate_geometry=[
                ("g", [20, 40, 160, 40], "test"),
                ("h", [20, 60, 160, 60], "test"),
            ],
            candidate_geometry_ids=["g", "h"],
            features={"distance_px": 20},
        )
        b = {
            **a,
            "sample_id": "b",
            "patch_sha256": "b",
            "source_bbox": [10, 0, 256, 256],
        }
        c = {
            **a,
            "sample_id": "c",
            "source_drawing_id": "drawing-c",
            "source_family_id": "drawing-c",
            "source_sha256": "drawing-c",
        }
        d = {
            **b,
            "sample_id": "d",
            "patch_sha256": "d",
            "features": {"distance_px": 40},
        }
        _, _, counts = deduplicate(
            [a, b, c, d], None, load_gray=lambda r: Image.new("L", (256, 256), 255)
        )
        self.assertEqual(counts["SAME_STRUCTURE_REPETITIONS_REMOVED"], 1)
        self.assertEqual(counts["UNIQUE_CANDIDATES_REMAINING"], 3)

    def test_exact_30_pool_has_no_labels_or_nontrain_sources(self):
        docs = ROOT / "docs/product-fix-p3b"
        rows = read_rows(docs / "real-v2-acceptance.jsonl")
        self.assertEqual(len(rows), 30)
        self.assertTrue(
            all(
                r["split"] == "train"
                and r["label"] is None
                and r["nomination_status"] is None
                and not r["training_authorized"]
                for r in rows
            )
        )
        self.assertTrue(all(r["quality"]["HUMAN_QUEUE_ELIGIBLE"] for r in rows))


if __name__ == "__main__":
    unittest.main()
