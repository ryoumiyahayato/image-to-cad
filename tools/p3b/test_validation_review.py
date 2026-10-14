"""Ownership, independent split and crash/resume safeguards; no real human answers edited."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pypdfium2 as pdfium

from audit_acceptance import audit_state
from common import LABELS, read, read_rows, sha, write_rows
from label_ui import LabelApp, LabelStore
from validation_review import (
    MANIFEST,
    OUT,
    PLAN,
    PURPOSE,
    STATE,
    summarize,
    verify_batch,
)
from validation_v2 import explicit_text_mask, owned_by_text


def fixture_pdf(path):
    """Known native glyph plus real boundary crossing its ink; no dependencies."""
    content = b"0 g BT /F1 90 Tf 30 100 Td (I) Tj ET 0 G 1 w 45 0 m 45 256 l S 160 0 m 160 256 l S"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 256 256] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
    ]
    document = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(document))
        document += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(document)
    document += b"xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        document += f"{offset:010d} 00000 n \n".encode()
    document += (
        f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(document)


class ValidationSafeguards(unittest.TestCase):
    def test_native_glyph_ownership_does_not_own_crossing_structure(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "truth.pdf"
            fixture_pdf(path)
            before = sha(path)
            with pdfium.PdfDocument(path) as doc:
                page = doc[0]
                bitmap = page.render(scale=1, grayscale=True)
                gray = np.array(bitmap.to_pil().convert("L"))
                bitmap.close()
                page.close()
            mask, proof = explicit_text_mask({"path": str(path)}, 1, 72, gray)
            self.assertTrue(proof["available"])
            self.assertFalse(proof["bbox_proximity_used"])
            self.assertEqual(sha(path), before)
            # A known source boundary inside the native glyph's bounding region
            # survives the no-text render and must never be text-owned.
            self.assertFalse(mask[:, 45].any())
            self.assertFalse(mask[:, 160].any())
            x = int(mask.sum(0).argmax())
            ys = np.flatnonzero(mask[:, x])
            # Pick a contiguous interior stem run, avoiding glyph serifs.
            runs = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
            stem = max(runs, key=len)
            target = {
                "source_bbox": [0, 0, 256, 256],
                "candidate_geometry": [
                    ["glyph", [x, int(stem[0]) + 2, x, int(stem[-1]) - 2], "test"]
                ],
            }
            self.assertTrue(owned_by_text(target, gray, mask))
            target["candidate_geometry"][0][1] = [45, 80, 45, 170]
            self.assertFalse(owned_by_text(target, gray, mask))

    def test_batch_is_frozen_fresh_and_whole_family_independent(self):
        rows = verify_batch()
        self.assertEqual(len(rows), 50)
        self.assertEqual(sum(r["target_kind"] == "CONTROL" for r in rows), 5)
        self.assertEqual(len({r["source_family_id"] for r in rows}), 5)
        self.assertTrue(all(r["label"] is None for r in rows))
        train = read_rows(MANIFEST.parent / "formal-seed-v2-001.jsonl")
        for key in (
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
        ):
            self.assertFalse({r[key] for r in rows} & {r[key] for r in train})

    def test_split_or_plan_corruption_cannot_launch(self):
        rows = read_rows(MANIFEST)
        modified = copy.deepcopy(rows)
        modified[0]["split"] = "blind_test"
        original_read_rows = read_rows
        with patch(
            "validation_review.read_rows",
            side_effect=lambda p: modified
            if Path(p).resolve() == MANIFEST.resolve()
            else original_read_rows(p),
        ):
            with self.assertRaises(ValueError):
                verify_batch()
        plan = read(PLAN)
        plan["final_train_status_sha256"] = "0" * 64
        original_read = read
        with patch(
            "validation_review.read",
            side_effect=lambda p: plan
            if Path(p).resolve() == PLAN.resolve()
            else original_read(p),
        ):
            with self.assertRaises(ValueError):
                verify_batch()
        with self.assertRaises(ValueError):
            verify_batch(labels=STATE.parent / "formal-seed-v2-001.json")
        with self.assertRaises(ValueError):
            verify_batch(patch_root=OUT.parent)

    def test_simplified_keys_persist_v_before_class_and_resume_undo(self):
        row = read_rows(MANIFEST)[5]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "samples.jsonl"
            write_rows(manifest, [row])
            store = LabelStore(
                base / "labels.json", manifest, "test-validation", PURPOSE
            )
            store.present(row, 0)
            app = LabelApp.__new__(LabelApp)
            app.mode, app.rows, app.index, app.store = "validation", [row], 0, store
            app.advance = lambda: None
            LabelApp.choose(app, 3)
            state = read(store.path)
            self.assertEqual(
                [r["action"] for r in state["review_log"]],
                ["present", "nomination", "physical_class"],
            )
            self.assertTrue(
                audit_state(state, [row], sha(manifest))[
                    "FINAL_STATE_INTERNALLY_CONSISTENT"
                ]
            )
            reopened = LabelStore(store.path, manifest, "test-validation", PURPOSE)
            reopened.undo()
            self.assertEqual(reopened.state["labels"], {})
            self.assertEqual(
                reopened.state["nomination_statuses"][row["sample_id"]]["status"],
                "VALID_TARGET",
            )
            self.assertEqual(summarize([row], reopened.state)["VALIDATION_REVIEWED"], 0)
            reopened.assign(row, LABELS[0])
            self.assertTrue(
                audit_state(reopened.state, [row], sha(manifest))[
                    "FINAL_STATE_INTERNALLY_CONSISTENT"
                ]
            )

    def test_crash_between_v_and_class_remains_incomplete(self):
        row = read_rows(MANIFEST)[5]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "samples.jsonl"
            write_rows(manifest, [row])
            store = LabelStore(
                base / "labels.json", manifest, "test-validation", PURPOSE
            )
            store.present(row, 0)
            store.nominate(row, "VALID_TARGET")
            restored = LabelStore(store.path, manifest, "test-validation", PURPOSE)
            self.assertEqual(summarize([row], restored.state)["VALIDATION_REVIEWED"], 0)
            self.assertEqual(restored.state["cursor_sample_id"], row["sample_id"])
            restored.nominate(row, "UNCLEAR_TARGET")
            self.assertEqual(summarize([row], restored.state)["VALIDATION_EXCLUDED"], 1)
            with self.assertRaises(ValueError):
                restored.assign(row, LABELS[0])
            self.assertTrue(
                audit_state(restored.state, [row], sha(manifest))[
                    "FINAL_STATE_INTERNALLY_CONSISTENT"
                ]
            )


if __name__ == "__main__":
    unittest.main()
