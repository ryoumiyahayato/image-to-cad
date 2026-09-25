from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.line_provenance_audit_v1 import (
    AuditPaths,
    CONFIDENCES,
    NOT_AVAILABLE,
    ROOT_CAUSES,
    _raw_hough,
    _summary,
    _validate_cases,
    build_audit,
    load_frozen_candidates,
    sample_span_support,
)


REPO = Path(__file__).resolve().parents[2]
TRACKED = REPO / "cad_photo_to_dxf" / "validation" / "line-provenance-audit-v1"


def _built_cases() -> list[dict[str, object]]:
    payload = json.loads(
        (TRACKED / "line-provenance-audit-cases.json").read_text(encoding="utf-8")
    )
    return payload["cases"]


def test_loads_exact_frozen_24_in_preserved_review_order() -> None:
    cases = load_frozen_candidates(AuditPaths(REPO))
    assert len(cases) == 24
    assert len({item["candidate_id"] for item in cases}) == 24
    assert [item["review_index"] for item in cases] == list(range(1, 25))


def test_hough_and_absent_lsd_provenance_remain_distinguishable() -> None:
    gray = np.full((120, 180), 255, dtype=np.uint8)
    cv2.line(gray, (10, 60), (170, 60), 0, 2)
    _binary, records = _raw_hough(gray)
    assert records
    assert {item["detector"] for item in records} == {"HOUGH"}
    cases = _built_cases()
    assert all(item["raw_lsd_ancestors"] == NOT_AVAILABLE for item in cases)
    assert all(item["raw_hough_ancestors"] != NOT_AVAILABLE for item in cases)


def test_absent_provenance_is_explicit() -> None:
    cases = _built_cases()
    assert all(item["post_consolidation_ids"] == NOT_AVAILABLE for item in cases)
    assert all(item["ownership_fallback_artifact_path"] == NOT_AVAILABLE for item in cases)


def test_span_support_sampling_is_deterministic_ordered_and_non_mutating() -> None:
    gray = np.full((40, 100), 255, dtype=np.uint8)
    cv2.line(gray, (5, 20), (94, 20), 0, 1)
    geometry = {"start": [5, 20], "end": [94, 20], "length_px": 89}
    before = deepcopy(geometry)
    first = sample_span_support(gray, geometry, sample_count=21)
    second = sample_span_support(gray, geometry, sample_count=21)
    assert first == second
    assert geometry == before
    fractions = [item["sample_position_fraction"] for item in first["samples"]]
    assert fractions == sorted(fractions)
    assert fractions[0] == 0.0
    assert fractions[-1] == 1.0


def test_diagnostic_mode_is_disabled_by_default() -> None:
    result = build_audit(REPO)
    assert result == {
        "diagnostic_enabled": False,
        "production_geometry_mutated": False,
    }


def test_governance_forbids_model_validation_locked_blind_and_holdouts() -> None:
    summary = json.loads(
        (TRACKED / "line-provenance-audit-summary.json").read_text(encoding="utf-8")
    )
    assert summary["model_run"] == "NO"
    assert summary["model_assisted_labeling"] == "NO"
    assert summary["validation"] == "NO"
    assert summary["locked_blind"] == "0 / 8"
    assert summary["h1_h2_opened"] == "NO"
    assert summary["production_geometry_mutated"] is False


def test_root_cause_confidence_and_single_primary_are_validated() -> None:
    cases = _built_cases()
    assert all(item["primary_root_cause"] in ROOT_CAUSES for item in cases)
    assert all(item["confidence"] in CONFIDENCES for item in cases)
    assert all(isinstance(item["secondary_failures"], list) for item in cases)
    broken = deepcopy(cases)
    broken[0]["primary_root_cause"] = "GENERIC_WRONG_PAIRING"
    with pytest.raises(ValueError, match="invalid primary root cause"):
        _validate_cases(broken)


def test_summary_primary_counts_sum_to_24() -> None:
    cases = _built_cases()
    summary = _summary(cases)
    assert len(cases) == 24
    assert summary["primary_counts_sum"] == 24
    assert sum(summary["primary_root_cause_counts"].values()) == 24

