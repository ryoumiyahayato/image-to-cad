from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = (
    PACKAGE_ROOT
    / "validation"
    / "primitive-integrity-review-v1"
    / "final-review"
)
CONTRACT_ROOT = (
    PACKAGE_ROOT / "validation" / "source-fidelity-primitive-contract-v1"
)
SELECTION_PATH = (
    PACKAGE_ROOT
    / "validation"
    / "primitive-integrity-review-v1"
    / "primitive-integrity-selection-manifest.json"
)
REVIEW_PATH = REVIEW_ROOT / "primitive-integrity-human-review-final.json"
MANIFEST_PATH = REVIEW_ROOT / "primitive-integrity-human-review-manifest.json"
JOIN_PATH = CONTRACT_ROOT / "frozen-16-diagnostic-join.json"
REPORT_PATH = CONTRACT_ROOT / "SOURCE-FIDELITY-PRIMITIVE-CONTRACT-V1-FINAL.md"

PROTOCOL = "PRIMITIVE_INTEGRITY_REVIEW_V1"
CANDIDATE_SET_ID = (
    "FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504-"
    "PRIMITIVE-INTEGRITY-748C5A4B61CD"
)
SELECTION_DIGEST = (
    "748c5a4b61cde3fb0ce5c754d000498275e06cdb9ae87263d7af0f0d4a47f94a"
)
SOURCE_EXPORT_SHA256 = (
    "0e9597c5516c49113f37701f2441ba7a7befd39fdbd12e4bea3a73ae98b5b987"
)
EXPECTED_PRIMARY = [
    "MULTIPLE_OR_OFFSET_SEGMENTS",
    "MULTIPLE_OR_OFFSET_SEGMENTS",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "ENDPOINT_OVERSHOOT",
    "MULTIPLE_OR_OFFSET_SEGMENTS",
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "OTHER_PRIMITIVE_MISMATCH",
    "MULTIPLE_OR_OFFSET_SEGMENTS",
]
EXPECTED_PRIMARY_COUNTS = {
    "VALID_SINGLE_STRAIGHT_PRIMITIVE": 10,
    "MULTIPLE_OR_OFFSET_SEGMENTS": 4,
    "ENDPOINT_OVERSHOOT": 1,
    "OTHER_PRIMITIVE_MISMATCH": 1,
    "FOREIGN_STROKE_CAPTURE": 0,
    "INSUFFICIENT_EVIDENCE": 0,
}
EXPECTED_SECONDARY_COUNTS = {
    "MULTIPLE_OR_OFFSET_SEGMENTS": 3,
    "ENDPOINT_OVERSHOOT": 0,
    "FOREIGN_STROKE_CAPTURE": 1,
    "CROSSES_LOCAL_STRUCTURE": 7,
    "OTHER": 0,
}


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_final_human_review_freeze_is_complete_and_exact() -> None:
    review = _load(REVIEW_PATH)
    manifest = _load(MANIFEST_PATH)
    selection = _load(SELECTION_PATH)

    assert isinstance(review, list)
    assert len(review) == 16
    assert [row["review_index"] for row in review] == list(range(1, 17))
    candidate_ids = [row["candidate_id"] for row in review]
    assert len(set(candidate_ids)) == 16
    assert candidate_ids == selection["review_order"]
    assert candidate_ids == manifest["candidate_order"]
    assert all(row["protocol"] == PROTOCOL for row in review)
    assert all(row["candidate_set_id"] == CANDIDATE_SET_ID for row in review)
    assert [row["primary_class"] for row in review] == EXPECTED_PRIMARY
    assert review[12]["primary_class"] == "MULTIPLE_OR_OFFSET_SEGMENTS"

    primary_counts = Counter(row["primary_class"] for row in review)
    assert {
        key: primary_counts.get(key, 0) for key in EXPECTED_PRIMARY_COUNTS
    } == EXPECTED_PRIMARY_COUNTS
    secondary_counts = Counter(
        flag for row in review for flag in row["secondary_flags"]
    )
    assert {
        key: secondary_counts.get(key, 0) for key in EXPECTED_SECONDARY_COUNTS
    } == EXPECTED_SECONDARY_COUNTS
    assert sum(bool(row["optional_note"]) for row in review) == 1
    assert review[0]["optional_note"] == "几乎犯了所有能犯的问题。"

    digest = hashlib.sha256(REVIEW_PATH.read_bytes()).hexdigest()
    assert digest == SOURCE_EXPORT_SHA256
    assert manifest["source_export_sha256"] == SOURCE_EXPORT_SHA256
    assert manifest["tracked_review_sha256"] == SOURCE_EXPORT_SHA256
    assert manifest["source_export_preserved_byte_for_byte"] is True
    assert manifest["human_labels_modified"] == "NO"
    assert manifest["review_completeness"] == "16 / 16"
    assert manifest["primary_counts"] == EXPECTED_PRIMARY_COUNTS
    assert manifest["secondary_flag_counts"] == EXPECTED_SECONDARY_COUNTS
    assert manifest["note_count"] == 1
    assert selection["selection_digest"] == SELECTION_DIGEST
    assert manifest["selection_digest"] == SELECTION_DIGEST
    assert manifest["selection_digest_preserved"] == "YES"


def test_diagnostic_join_preserves_human_data_and_order() -> None:
    review = _load(REVIEW_PATH)
    joined = _load(JOIN_PATH)
    cases = joined["cases"]

    assert joined["diagnostic_only"] is True
    assert joined["human_labels_modified"] is False
    assert joined["eligibility_changed"] is False
    assert joined["case_count"] == 16
    assert [case["candidate_id"] for case in cases] == [
        row["candidate_id"] for row in review
    ]
    assert [case["review_index"] for case in cases] == list(range(1, 17))
    for row, case in zip(review, cases, strict=True):
        assert case["human_primary"] == row["primary_class"]
        assert case["human_secondary_flags"] == row["secondary_flags"]
        assert case["current_eligibility"] == "DIRECT_CONTINUATION_ADMISSIBLE"
        assert case["diagnostic_mismatch_summary"]

    review_8 = cases[7]
    assert review_8["coherence"]["status"] == "PRIMITIVE_COHERENCE_SUPPORTED"
    review_13 = cases[12]
    assert review_13["human_primary"] == "MULTIPLE_OR_OFFSET_SEGMENTS"
    assert review_13["span"]["status"] == "SPAN_INTEGRITY_SUPPORTED"
    assert review_13["axis"]["status"] == "PRIMITIVE_AXIS_SUPPORTED"
    assert review_13["coherence"]["status"] == "PRIMITIVE_COHERENCE_SUPPORTED"


def test_contract_and_governance_are_frozen_without_source_media() -> None:
    report = REPORT_PATH.read_text(encoding="utf-8")
    for required in (
        "Source-visible stroke extents are preserved as geometry.",
        "Periodicity alone does not authorize destructive merging.",
        "Collinearity does not prove primitive identity.",
        "Crossing local structure does not automatically terminate primitive identity.",
        "EXISTING PATTERNED-STROKE ASSUMPTION CONFLICT: `PARTIAL`",
        "SEMANTICALLY OUTDATED TESTS FOUND: `YES`",
        "GENERIC SOURCE-STROKE-CONTINUITY GUARD: `NO`",
        "GENERIC ENDPOINT GUARD: `NO`",
        "PRODUCTION SEMANTIC DELTA: `NONE`",
    ):
        assert required in report

    forbidden_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
        ".dwg",
    }
    tracked_artifact_roots = (REVIEW_ROOT, CONTRACT_ROOT)
    assert not [
        path
        for root in tracked_artifact_roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]

    manifest = _load(MANIFEST_PATH)
    assert manifest["production_semantic_delta"] == "NONE"
    assert manifest["new_candidate_mining"] == "NO"
    assert manifest["new_human_review_package"] == "NO"
    assert manifest["model_run"] == "NO"
    assert manifest["model_assisted_labeling"] == "NO"
    assert manifest["validation"] == "NO"
    assert manifest["locked_blind"] == "0 / 8"
    assert manifest["h1_h2_opened"] == "NO"
    assert manifest["source_images_committed"] == "NO"
