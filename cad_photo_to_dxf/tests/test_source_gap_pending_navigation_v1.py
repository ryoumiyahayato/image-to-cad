from __future__ import annotations

import json
from pathlib import Path
import unittest

from cad_photo_to_dxf.app import targeted_source_gap_review_v1 as source_gap


REPO_ROOT = Path(__file__).resolve().parents[2]
V12_MANIFEST = (
    REPO_ROOT
    / "local-artifacts"
    / "draftsman"
    / "targeted-source-gap-review-v1-2"
    / "review-package"
    / "manifest.json"
)


class SourceGapPendingNavigationV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if V12_MANIFEST.is_file():
            package = json.loads(V12_MANIFEST.read_text(encoding="utf-8"))
        else:
            candidate_ids = [f"TEST-{index:02d}" for index in range(1, 17)]
            package = {
                "schema_version": 1,
                "package_id": "targeted-source-gap-review-v1-2",
                "review_protocol": source_gap.PROTOCOL,
                "candidate_set_id": "TEST-SOURCE-GAP-V1-2",
                "candidate_count": 16,
                "review_order": candidate_ids,
                "items": [
                    {
                        "review_index": index,
                        "candidate_id": candidate_id,
                        "local_clean_image": "assets/local/clean.png",
                        "local_overlay_image": "assets/local/overlay.png",
                        "context_clean_image": "assets/context/clean.png",
                        "context_overlay_image": "assets/context/overlay.png",
                        "marker": {},
                    }
                    for index, candidate_id in enumerate(candidate_ids, start=1)
                ],
            }
        cls.package = package
        cls.html = source_gap.render_review_html(package)

    def test_pending_filter_and_direct_jump_contract_present(self) -> None:
        for token in (
            'id="pending-only"',
            'id="pending-jumps"',
            "function pendingIndices()",
            "function visibleIndices()",
            "function jumpToIndex(index)",
            "renderPendingJumps(pending)",
            "state.pendingOnly",
            "function clearPrimary()",
            'id="clear-primary-button"',
            "已完成",
            "待审核：无（全部完成）",
        ):
            self.assertIn(token, self.html)

    def test_pending_navigation_does_not_change_export_schema(self) -> None:
        order = self.package["review_order"]
        rows = [
            {
                "protocol": source_gap.PROTOCOL,
                "candidate_set_id": self.package["candidate_set_id"],
                "candidate_id": candidate_id,
                "review_index": index,
                "primary_class": "CONTINUOUS_SOURCE_STROKE" if index <= 13 else None,
                "secondary_flags": [],
                "optional_note": "",
            }
            for index, candidate_id in enumerate(order, start=1)
        ]
        normalized = source_gap.validate_review_export(rows, self.package["candidate_set_id"], order)
        self.assertEqual(sum(row["primary_class"] is None for row in normalized), 3)
        self.assertTrue(all(set(row) == {"protocol", "candidate_set_id", "candidate_id", "review_index", "primary_class", "secondary_flags", "optional_note"} for row in normalized))
        self.assertNotIn("pendingOnly", json.dumps(normalized, ensure_ascii=False))

    def test_existing_v12_package_starts_with_thirteen_completed_and_three_pending(self) -> None:
        if not V12_MANIFEST.is_file():
            self.skipTest("runtime V1.2 package is not present")
        initial = self.package.get("initial_review_state", [])
        self.assertEqual(len(initial), 16)
        self.assertEqual(sum(bool(row.get("primary_class")) for row in initial), 13)
        self.assertEqual([row["review_index"] for row in initial if not row.get("primary_class")], [10, 15, 16])


if __name__ == "__main__":
    unittest.main()
