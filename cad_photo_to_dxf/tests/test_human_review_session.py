from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from app.human_review_server import create_review_server
from app.human_review_session import (
    ALLOWED_HUMAN_LABELS,
    ReviewItem,
    ReviewSession,
    ReviewSessionError,
    create_session_from_manifest,
    load_review_manifest,
    verify_review_assets,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
E1_ROOT = REPO_ROOT / "cad_photo_to_dxf" / "validation" / "user-supplied-human-review-v2-local-e1"
E1_MANIFEST = E1_ROOT / "human-review-manifest.json"
E1_ORDER = E1_ROOT / "review-order.json"


def _items() -> tuple[ReviewItem, ...]:
    return tuple(
        ReviewItem(
            item_id=f"item-{index}",
            review_index=index,
            local_image_path=f"assets/local-{index}.png",
            context_image_path=f"assets/context-{index}.png",
        )
        for index in range(1, 4)
    )


class HumanReviewSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.mkdtemp(prefix="human-review-test-")
        self.tmp_path = Path(self._temporary_directory)

    def tearDown(self) -> None:
        shutil.rmtree(self._temporary_directory, ignore_errors=True)

    def _session(self) -> ReviewSession:
        return ReviewSession(
            items=_items(),
            state_path=self.tmp_path / "review-state.json",
            manifest_sha256="a" * 64,
            ordering_method="fixed test order",
            manifest_name="manifest.json",
            order_name="order.json",
            export_path=self.tmp_path / "review-export.json",
        )

    def test_allowed_labels_are_exact_and_initial_state_has_no_labels(self) -> None:
        session = self._session()
        self.assertEqual(
            ALLOWED_HUMAN_LABELS,
            (
                "STRUCTURAL_CONTINUATION",
                "ANNOTATION_OR_GLYPH",
                "AMBIGUOUS",
                "INVALID_FOR_TASK",
            ),
        )
        self.assertEqual(
            session.counts(),
            {
                "total": 3,
                "completed": 0,
                "pending": 3,
                "by_label": {label: 0 for label in ALLOWED_HUMAN_LABELS},
            },
        )
        self.assertTrue(
            all(item["human_label"] is None for item in session.snapshot()["items"])
        )

    def test_invalid_label_is_rejected_without_mutating_state(self) -> None:
        session = self._session()
        with self.assertRaisesRegex(ReviewSessionError, "not allowed"):
            session.set_label("item-1", "POSITIVE")
        self.assertIsNone(session.item_state("item-1")["human_label"])

    def test_save_reload_resume_and_note_persistence(self) -> None:
        session = self._session()
        session_id = session.snapshot()["session_id"]
        session.set_label("item-1", "STRUCTURAL_CONTINUATION")
        session.set_note("item-1", "保留供后续复核")

        resumed = self._session()
        self.assertEqual(resumed.snapshot()["session_id"], session_id)
        self.assertEqual(
            resumed.item_state("item-1")["human_label"], "STRUCTURAL_CONTINUATION"
        )
        self.assertEqual(
            resumed.item_state("item-1")["reviewer_note"], "保留供后续复核"
        )
        self.assertEqual(resumed.item_state("item-1")["review_status"], "REVIEWED")

    def test_changing_label_persists_small_history_and_counts(self) -> None:
        session = self._session()
        session.set_label("item-1", "AMBIGUOUS")
        session.set_label("item-1", "ANNOTATION_OR_GLYPH")
        state = session.item_state("item-1")
        self.assertEqual(state["human_label"], "ANNOTATION_OR_GLYPH")
        self.assertIsNone(state["label_history"][0]["old_label"])
        self.assertEqual(state["label_history"][0]["new_label"], "AMBIGUOUS")
        self.assertEqual(state["label_history"][1]["old_label"], "AMBIGUOUS")
        self.assertEqual(
            state["label_history"][1]["new_label"], "ANNOTATION_OR_GLYPH"
        )
        self.assertEqual(session.counts()["completed"], 1)
        self.assertEqual(session.counts()["pending"], 2)
        self.assertEqual(session.counts()["by_label"]["ANNOTATION_OR_GLYPH"], 1)

    def test_item_identity_and_export_are_preserved_without_model_fields(self) -> None:
        session = self._session()
        session.set_label("item-2", "INVALID_FOR_TASK")
        payload = session.export()
        self.assertEqual(payload["review_order"], ["item-1", "item-2", "item-3"])
        self.assertEqual(
            [item["candidate_id"] for item in payload["items"]],
            payload["review_order"],
        )
        self.assertEqual(payload["items"][1]["human_label"], "INVALID_FOR_TASK")
        self.assertEqual(payload["manifest_identity"]["manifest_sha256"], "a" * 64)
        self.assertNotIn('"model"', json.dumps(payload).lower())

    def test_e1_manifest_has_24_items_and_all_assets_are_available(self) -> None:
        manifest = load_review_manifest(E1_MANIFEST, E1_ORDER)
        self.assertEqual(len(manifest.items), 24)
        self.assertEqual(
            [item.review_index for item in manifest.items], list(range(1, 25))
        )
        self.assertEqual(len(verify_review_assets(manifest.items, REPO_ROOT)), 48)

        session, _ = create_session_from_manifest(
            manifest_path=E1_MANIFEST,
            order_path=E1_ORDER,
            state_path=self.tmp_path / "review-state.json",
            repo_root=REPO_ROOT,
        )
        self.assertEqual(len(session.items), 24)
        self.assertEqual(session.counts()["completed"], 0)
        self.assertTrue(
            all(item["human_label"] is None for item in session.snapshot()["items"])
        )

    def test_local_http_adapter_serves_pair_and_persists_label(self) -> None:
        session, _ = create_session_from_manifest(
            manifest_path=E1_MANIFEST,
            order_path=E1_ORDER,
            state_path=self.tmp_path / "review-state.json",
            repo_root=REPO_ROOT,
            export_path=self.tmp_path / "review-export.json",
        )
        server = create_review_server(
            session=session,
            repo_root=REPO_ROOT,
            export_path=self.tmp_path / "review-export.json",
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(f"{base_url}/api/session") as response:
                snapshot = json.load(response)["session"]
            first = snapshot["items"][0]
            self.assertTrue(first["local_image_url"].startswith("/assets/"))
            self.assertTrue(first["context_image_url"].startswith("/assets/"))
            self.assertNotIn("source_family_id", first)
            self.assertFalse(
                {"model", "model_score", "prediction", "uncertainty"}.intersection(
                    first
                )
            )

            request = Request(
                f"{base_url}/api/items/{first['item_id']}/label",
                data=json.dumps({"label": "AMBIGUOUS"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                mutation = json.load(response)
            self.assertEqual(mutation["item"]["human_label"], "AMBIGUOUS")
            self.assertEqual(mutation["session"]["counts"]["completed"], 1)
            self.assertEqual(
                session.item_state(first["item_id"])["human_label"], "AMBIGUOUS"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
