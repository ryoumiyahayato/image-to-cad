"""Focused invariants for the targeted Primitive Integrity Review V1 package."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from app.primitive_integrity_review_v1 import (
    BASE_CHECKPOINT,
    FRESH_POOL_COUNT,
    MAX_PRIOR_REVIEWED_CONTROLS,
    PRIMARY_CLASSES,
    PROTOCOL,
    SECONDARY_FLAGS,
    TARGET_REVIEW_SIZE,
    _exact_primitive_key,
    _load_diagnostics,
    _load_frozen_inputs,
    _load_prior_reviewed_ids,
    _select_target,
    _selection_digest,
    build_review_package,
    replay_selection,
    validate_review_export,
    validate_review_package,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_ROOT = REPO_ROOT / "cad_photo_to_dxf" / "validation" / "primitive-integrity-review-v1"


class PrimitiveIntegrityReviewV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = _load_frozen_inputs(REPO_ROOT)
        pool_ids = {str(item["candidate_id"]) for item in cls.frozen["pool"]}
        cls.prior_ids, _prior_metadata = _load_prior_reviewed_ids(REPO_ROOT, pool_ids)
        cls.diagnostics = _load_diagnostics(REPO_ROOT, pool_ids)
        cls.records = _select_target(REPO_ROOT, cls.frozen["pool"], cls.prior_ids, cls.diagnostics)
        cls.selection_digest = _selection_digest(
            cls.records, str(cls.frozen["runtime"]["candidate_set_id"])
        )
        cls.candidate_set_id = (
            f"{cls.frozen['runtime']['candidate_set_id']}-PRIMITIVE-INTEGRITY-"
            f"{cls.selection_digest[:12].upper()}"
        )
        cls.temp_dir = tempfile.TemporaryDirectory(
            prefix="primitive-integrity-review-v1-test-",
            dir=str(REPO_ROOT / "local-artifacts"),
        )
        temp_root = Path(cls.temp_dir.name)
        cls.package_dir = temp_root / "review-package"
        cls.package_zip = temp_root / "review-package.zip"
        cls.package_manifest, cls.package_validation = build_review_package(
            REPO_ROOT,
            cls.records,
            cls.candidate_set_id,
            {
                "source_fresh_candidate_set_id": cls.frozen["runtime"]["candidate_set_id"],
                "source_frozen_pool_count": FRESH_POOL_COUNT,
                "source_pool_runtime_sha256": cls.frozen["runtime_sha256"],
                "selection_digest": cls.selection_digest,
            },
            output_dir=cls.package_dir,
            zip_path=cls.package_zip,
            replace=True,
        )
        cls.html = (cls.package_dir / "review.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_frozen_pool_size_selection_size_and_replay(self) -> None:
        self.assertEqual(len(self.frozen["pool"]), FRESH_POOL_COUNT)
        self.assertEqual(len({item["candidate_id"] for item in self.frozen["pool"]}), FRESH_POOL_COUNT)
        self.assertEqual(len(self.records), TARGET_REVIEW_SIZE)
        self.assertEqual(
            sum(record["new_or_prior_reviewed"] == "NEW_UNREVIEWED" for record in self.records),
            12,
        )
        self.assertEqual(
            sum(record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in self.records),
            4,
        )
        self.assertLessEqual(
            sum(record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in self.records),
            MAX_PRIOR_REVIEWED_CONTROLS,
        )
        self.assertEqual(len({record["candidate_id"] for record in self.records}), TARGET_REVIEW_SIZE)
        self.assertEqual(len({_exact_primitive_key(record) for record in self.records}), TARGET_REVIEW_SIZE)
        tracked_manifest = json.loads(
            (TRACKED_ROOT / "primitive-integrity-selection-manifest.json").read_text(encoding="utf-8")
        )
        replay = replay_selection(REPO_ROOT, tracked_manifest)
        self.assertEqual(replay["status"], "PASS")
        self.assertEqual(replay["selection_deterministic_replay"], "PASS")

    def test_expected_strata_and_source_diversity_are_frozen(self) -> None:
        strata = {}
        for record in self.records:
            strata[record["selection_stratum"]] = strata.get(record["selection_stratum"], 0) + 1
        self.assertEqual(
            strata,
            {
                "AXIS_SPAN_EDGE_CASES": 1,
                "CLEAN_LONG_PRIMITIVE_CONTROLS": 3,
                "CLEAN_SHORT_MEDIUM_CONTROLS": 3,
                "SUSPECTED_COHERENCE_CASES": 5,
                "SUSPECTED_ENDPOINT_CASES": 4,
            },
        )
        self.assertEqual(len({record["source_family"] for record in self.records}), 10)
        self.assertEqual(len({record["source_unit"] for record in self.records}), 13)
        self.assertEqual(sum(record["orientation"] == "horizontal" for record in self.records), 6)
        self.assertEqual(sum(record["orientation"] == "vertical" for record in self.records), 10)
        self.assertEqual(
            json.loads(
                (TRACKED_ROOT / "primitive-integrity-selection-replay.json").read_text(
                    encoding="utf-8"
                )
            )["status"],
            "PASS",
        )

    def test_four_view_assets_are_mapped_and_red_overlay_is_present(self) -> None:
        self.assertEqual(self.package_manifest["candidate_count"], TARGET_REVIEW_SIZE)
        self.assertEqual(self.package_validation["candidate_count"], TARGET_REVIEW_SIZE)
        for item in self.package_manifest["items"]:
            for key in (
                "local_clean_image",
                "local_overlay_image",
                "context_clean_image",
                "context_overlay_image",
            ):
                path = self.package_dir / Path(*item[key].split("/"))
                self.assertTrue(path.is_file(), path)
            for kind in ("local", "context"):
                marker = item["marker"][kind]
                clean_key = f"{kind}_clean_image"
                overlay_key = f"{kind}_overlay_image"
                with Image.open(self.package_dir / Path(*item[clean_key].split("/"))) as clean:
                    with Image.open(self.package_dir / Path(*item[overlay_key].split("/"))) as overlay:
                        self.assertEqual(clean.size, overlay.size)
                        self.assertEqual(tuple(clean.size), (marker["width"], marker["height"]))
                        red_pixels = sum(
                            1
                            for red, green, blue in overlay.convert("RGB").getdata()
                            if red > 180 and green < 100 and blue < 130
                        )
                        self.assertGreater(red_pixels, 0)

    def test_reviewer_ui_is_fresh_blind_and_compact_normal_flow(self) -> None:
        for value in PRIMARY_CLASSES + SECONDARY_FLAGS:
            self.assertIn(value, self.html)
        for token in (
            "primary_class:null",
            "secondary_flags:[]",
            'optional_note:""',
            ".review-section",
            ".data-menu",
            "padding:20px 22px 28px",
            "function setModalScale",
            "function endpointMarkerSvg",
            "pointerdown",
            "pointermove",
            "wheel",
            "适合窗口",
            "局部原图",
            "局部红线",
            "整体原图",
            "整体红线",
            "补充标记（可选）",
            "备注（可选）",
            "点击图片可放大",
            "上一张",
            "下一张",
        ):
            self.assertIn(token, self.html)
        for forbidden in (
            "position:sticky",
            ".review-controls",
            "marker-toggle",
            "data-view-mode",
            "data-focus",
            'class="label-code"',
            ">VALID_SINGLE_STRAIGHT_PRIMITIVE<",
            ">MULTIPLE_OR_OFFSET_SEGMENTS<",
            ">ENDPOINT_OVERSHOOT<",
            ">FOREIGN_STROKE_CAPTURE<",
            ">OTHER_PRIMITIVE_MISMATCH<",
            ">INSUFFICIENT_EVIDENCE<",
            "primitive overlay",
            "selection_stratum",
            "diagnostic_measurements_used",
            "machine_verdict",
            "support_fraction",
            "coherence_status",
            "endpoint_status",
            "human_stage1",
            "human_stage2",
            "prediction",
            "cosine",
            "MobileNet",
            "VALIDATION",
            "LOCKED_BLIND",
            "H1/H2",
            "Batch-03",
        ):
            self.assertNotIn(forbidden, self.html)
        self.assertNotIn("<script src=", self.html)
        self.assertNotIn("fetch(", self.html)

    def test_export_schema_preserves_primary_flags_and_note_verbatim(self) -> None:
        note = "  red line enters text\nkeep this spacing  "
        rows = [
            {
                "protocol": PROTOCOL,
                "candidate_set_id": self.candidate_set_id,
                "candidate_id": record["candidate_id"],
                "review_index": record["review_index"],
                "primary_class": PRIMARY_CLASSES[index % len(PRIMARY_CLASSES)],
                "secondary_flags": [SECONDARY_FLAGS[index % len(SECONDARY_FLAGS)]],
                "optional_note": note if index == 0 else "",
            }
            for index, record in enumerate(self.records)
        ]
        normalized = validate_review_export(rows, self.candidate_set_id, [r["candidate_id"] for r in self.records])
        self.assertEqual(normalized[0]["optional_note"], note)
        self.assertEqual(normalized[0]["primary_class"], PRIMARY_CLASSES[0])
        self.assertEqual(normalized[0]["secondary_flags"], [SECONDARY_FLAGS[0]])
        self.assertEqual(
            set(normalized[0]),
            {
                "protocol",
                "candidate_set_id",
                "candidate_id",
                "review_index",
                "primary_class",
                "secondary_flags",
                "optional_note",
            },
        )

    def test_package_validation_and_zip_do_not_include_source_documents(self) -> None:
        self.assertEqual(validate_review_package(self.package_dir)["bottom_control_overlap_guard"], "PASS")
        with zipfile.ZipFile(self.package_zip) as archive:
            names = archive.namelist()
        self.assertEqual(len([name for name in names if name.startswith("assets/local/")]), 32)
        self.assertEqual(len([name for name in names if name.startswith("assets/context/")]), 32)
        self.assertFalse(any(name.lower().endswith((".pdf", ".dwg", ".dxf")) for name in names))
        self.assertFalse(any("selection-runtime" in name or "diagnostic" in name for name in names))

    def test_no_mining_or_model_call_is_added_to_targeted_module(self) -> None:
        source = (REPO_ROOT / "cad_photo_to_dxf/app/primitive_integrity_review_v1.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("run_fresh_remine(", source)
        self.assertNotIn("MobileNet", source)
        self.assertNotIn("cosine_classifier", source)
        self.assertNotIn("ocr_semantic", source)
        self.assertEqual(BASE_CHECKPOINT, "e3a3c81fa2783352bc8655b28d564471b441ceec")


if __name__ == "__main__":
    unittest.main()
