"""Bounded independent review and exact freeze safety; temporary states only."""

import copy
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_acceptance import audit_state
from common import LABELS, read, read_rows, sha, write_rows
from label_ui import LabelApp, LabelStore
import validation_suspects as review


class ValidationSuspects(unittest.TestCase):
    def setUp(self):
        self.rows = read_rows(review.MANIFEST)
        self.originals = read(review.ORIGINALS)

    def state_in_temp(self, folder, revisions=None):
        manifest, state = folder / "review.jsonl", folder / "review.json"
        write_rows(manifest, self.rows)
        store = LabelStore(state, manifest, "test", review.PURPOSE)
        old = {r["sample_id"]: r for r in self.originals["samples"]}
        for i, row in enumerate(self.rows):
            store.present(row, i)
            choice = (revisions or {}).get(
                row["original_rank"], old[row["sample_id"]]["original_stage1"]["label"]
            )
            if choice in ("INVALID_NOMINATION", "UNCLEAR_TARGET"):
                store.nominate(row, choice)
            else:
                store.nominate(row, "VALID_TARGET")
                store.assign(row, choice)
        return store, manifest

    def test_only_eight_in_requested_order_with_originals_hidden(self):
        self.assertEqual([r["original_rank"] for r in review.verify()], review.ORDER)
        self.assertTrue(
            all(
                r["label"] is None
                and r["label_provenance"] is None
                and r["nomination_status"] is None
                for r in self.rows
            )
        )
        self.assertTrue(
            all(
                "original_stage1" not in r
                and "review_reasons" not in r
                and "human_class" not in r
                for r in self.rows
            )
        )
        with self.assertRaises(ValueError):
            review.verify(labels=review.ORIGINAL_STATE)
        changed = copy.deepcopy(self.rows)
        changed[0]["candidate_geometry"][0][1][0] += 1
        original_reader = read_rows
        with patch(
            "validation_suspects.read_rows",
            side_effect=lambda p: changed
            if Path(p) == review.MANIFEST
            else original_reader(p),
        ):
            with self.assertRaises(ValueError):
                review.verify()

    def test_exact_agreement_preserves_three_ambiguities(self):
        with tempfile.TemporaryDirectory() as td:
            store, manifest = self.state_in_temp(Path(td))
            history = audit_state(
                store.state, self.rows, sha(manifest), presentation_order=self.rows
            )
            self.assertTrue(history["FINAL_STATE_INTERNALLY_CONSISTENT"])
            result = review.compare(self.rows, self.originals, store.state)
            self.assertEqual(result["EXACT_AGREEMENT"], 8)
            self.assertEqual(result["CONFIRMED_AMBIGUOUS"], 3)
            self.assertEqual(result["CONFIRMED_TRUE_PARALLEL"], 2)
            self.assertEqual(result["CONFIRMED_SINGLE"], 3)
            effective = review.adjudicate(
                read_rows(review.ORIGINAL_MANIFEST),
                read(review.ORIGINAL_STATE),
                self.rows,
                store.state,
            )
            self.assertEqual(
                sum(r["current_class"] == "AMBIGUOUS" for r in effective), 3
            )

    def test_disagreements_reported_and_current_view_exclusion_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            store, _ = self.state_in_temp(
                Path(td), {16: "INVALID_NOMINATION", 41: LABELS[0], 6: LABELS[2]}
            )
            result = review.compare(self.rows, self.originals, store.state)
            self.assertEqual(result["EXACT_AGREEMENT"], 5)
            self.assertEqual(result["STAGE0_DISAGREEMENT"], 1)
            self.assertEqual(result["STAGE1_DISAGREEMENT"], 2)
            self.assertEqual(result["REVISED_TO_X_OR_U"], 1)
            self.assertEqual(result["REVISED_TO_SINGLE"], 1)
            self.assertEqual(result["REVISED_TO_OTHER"], 1)
            self.assertEqual(len(result["DISAGREEMENTS"]), 3)
            original = read(review.ORIGINAL_STATE)
            before = copy.deepcopy(original)
            effective = review.adjudicate(
                read_rows(review.ORIGINAL_MANIFEST), original, self.rows, store.state
            )
            excluded = [
                r for r in effective if r["current_review_status"] == "EXCLUDED"
            ]
            self.assertEqual(len(excluded), 1)
            self.assertEqual(excluded[0]["original_stage1"]["label"], LABELS[1])
            self.assertEqual(excluded[0]["current_stage0"], "INVALID_NOMINATION")
            self.assertEqual(original, before)

    def test_v_alone_and_skip_do_not_finalize(self):
        with tempfile.TemporaryDirectory() as td:
            store, _ = self.state_in_temp(Path(td))
            sid = self.rows[-1]["sample_id"]
            store.state["labels"].pop(sid)
            with self.assertRaises(ValueError):
                review.compare(self.rows, self.originals, store.state)
            store, _ = self.state_in_temp(Path(td) / "skipped")
            store.skip(self.rows[-1])
            with self.assertRaises(ValueError):
                review.compare(self.rows, self.originals, store.state)

    def test_ui_mode_order_direct_class4_and_no_skip(self):
        original_hash = sha(review.ORIGINAL_STATE)
        with tempfile.TemporaryDirectory() as td:
            root = tk.Tk()
            root.withdraw()
            try:
                with patch("validation_suspects.verify", return_value=self.rows):
                    app = LabelApp(
                        root,
                        review.MANIFEST,
                        Path(td) / "labels.json",
                        "test",
                        review.OUT,
                        "validation-suspect",
                    )
                self.assertEqual([r["original_rank"] for r in app.rows], review.ORDER)
                self.assertTrue(
                    all(b.cget("state") == "normal" for b in app.class_buttons)
                )
                app.skip()
                self.assertEqual(app.store.state["skipped"], {})
                app.choose(4)
                sid = self.rows[0]["sample_id"]
                self.assertEqual(app.store.state["labels"][sid]["label"], LABELS[3])
                self.assertEqual(app.rows[app.index]["original_rank"], 41)
                self.assertEqual(
                    app.store.state["review_log"][1]["action"], "nomination"
                )
                app.undo()
                self.assertEqual(app.index, 0)
                self.assertNotIn(sid, app.store.state["labels"])
            finally:
                root.destroy()
        self.assertEqual(sha(review.ORIGINAL_STATE), original_hash)

    def test_freeze_retains_ambiguous_truth_and_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            store, _ = self.state_in_temp(folder / "states")
            effective = review.adjudicate(
                read_rows(review.ORIGINAL_MANIFEST),
                read(review.ORIGINAL_STATE),
                self.rows,
                store.state,
            )
            fake = folder / "docs"
            fake.mkdir()
            for name in (
                "formal-seed-v2-001.jsonl",
                "formal-seed-adjudicated-decisions.jsonl",
                "FORMAL-SEED-FINAL-STATUS.json",
                "split-manifest.json",
            ):
                shutil.copyfile(review.DOCS / name, fake / name)
            for name in ("formal-seed-v2-001.json", "suspect-review-v2-001.json"):
                (fake / "labels").mkdir(exist_ok=True)
                shutil.copyfile(review.DOCS / "labels" / name, fake / "labels" / name)
            derived = fake / "validation-adjudicated-decisions.jsonl"
            write_rows(derived, effective)
            with patch.multiple(
                review,
                DOCS=fake,
                ADJUDICATED=derived,
                STATE=store.path,
                FREEZE=fake / "freeze.json",
            ):
                result = review.freeze_data(effective)
                self.assertEqual(result["train"]["included_count"], 94)
                self.assertEqual(result["validation"]["included_count"], 50)
                self.assertEqual(len(result["validation"]["ambiguous_sample_ids"]), 3)
                self.assertEqual(result["AMBIGUOUS_POLICY"]["recommended_route"], "A")
                self.assertFalse(result["training_authorized"])
                self.assertTrue(all(not x for x in result["leakage_checks"].values()))
                self.assertEqual(review.freeze_data(effective), result)
                altered = copy.deepcopy(effective)
                altered[0]["current_class"] = LABELS[0]
                write_rows(derived, altered)
                with self.assertRaises(ValueError):
                    review.freeze_data(altered)


if __name__ == "__main__":
    unittest.main()
