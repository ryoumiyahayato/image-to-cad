from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import pytest

from app import line_integrity_audit
from app.line_integrity_audit import AuditCase, build_case_artifact, load_audit_registry


def _case_payload(index: int) -> dict[str, object]:
    return {
        "case_id": f"D2-{index:03d}",
        "source_group_id": "DEV-SG-001",
        "page": 1,
        "bundle_directory": "bundle",
        "vqa_run_directory": "vqa",
        "roi": [10, 20, 80, 60],
        "target": [20, 30, 70, 30],
        "orientation": "horizontal",
        "approximate_width_px": 2,
        "approximate_length_px": 51,
        "target_type": "solid line",
        "source_description": "Synthetic continuous DEV line.",
        "status": "QUALIFIED",
        "confidence": "HIGH",
        "qualification": {
            "source_continuous": "YES",
            "processing_input_continuous": "YES",
            "coordinate_mapping_verified": True,
            "same_source_structure_endpoints": "YES",
            "target_type": "solid line",
            "allowed_as_false_break_case": "QUALIFIED",
        },
        "result_type": "PRESERVED",
        "root_cause": "NO_END_TO_END_DEFECT",
        "first_true_divergence_stage": "NONE",
        "first_divergence_event": "NONE",
        "branch": "native LINE",
        "plain_conclusion": "Target remains continuous.",
        "success_control": True,
        "paired_case_id": None,
        "rejection_reason": None,
        "source_support_dropped": False,
        "fragment_first_risk": False,
        "evidence": {"binary": "continuous"},
    }


def _registry_payload() -> dict[str, object]:
    cases = [_case_payload(index) for index in range(1, 9)]
    return {
        "schema_version": "line-integrity-audit-d2-v1",
        "architecture_risk": {
            "LINE_INTEGRITY_IS_NOT_PRESERVED_END_TO_END": "INCONCLUSIVE"
        },
        "comparison_pairs": [
            {"label": "PAIR", "success": "D2-001", "failure": "D2-002"}
        ],
        "full_page_sanity": [
            {"source_group_id": "DEV-SG-001", "vqa_run_directory": "vqa"}
        ],
        "cases": cases,
    }


def _write_registry(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_accepts_eight_coordinate_verified_qualified_cases(
    tmp_path: Path,
) -> None:
    registry = load_audit_registry(
        _write_registry(tmp_path, _registry_payload()), tmp_path
    )

    assert len(registry.cases) == 8
    assert registry.cases[0].roi == (10, 20, 80, 60)
    assert registry.cases[0].target == (20, 30, 70, 30)


def test_registry_rejects_unverified_source_continuity(tmp_path: Path) -> None:
    payload = _registry_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    assert isinstance(first, dict)
    qualification = first["qualification"]
    assert isinstance(qualification, dict)
    qualification["source_continuous"] = "UNCERTAIN"

    with pytest.raises(ValueError, match="lacks required evidence"):
        load_audit_registry(_write_registry(tmp_path, payload), tmp_path)


def test_registry_rejects_target_outside_fixed_roi(tmp_path: Path) -> None:
    payload = _registry_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    first = cases[0]
    assert isinstance(first, dict)
    first["target"] = [5, 30, 70, 30]

    with pytest.raises(ValueError, match="target must stay inside ROI"):
        load_audit_registry(_write_registry(tmp_path, payload), tmp_path)


def test_protected_split_fails_closed_before_panels(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"input": {"path": "C:/corpus-v1/locked_blind/example.pdf"}}),
        encoding="utf-8",
    )
    item = _case_payload(1)
    values = {
        **item,
        "roi": (10, 20, 80, 60),
        "target": (20, 30, 70, 30),
        "bundle_directory": bundle,
        "vqa_run_directory": tmp_path / "vqa",
    }
    case = AuditCase(**cast(Any, values))

    with pytest.raises(ValueError, match="not DEV|protected split"):
        line_integrity_audit._case_panels(case)


def test_case_artifact_keeps_coordinates_and_is_diagnostic_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _case_payload(1)
    values = {
        **item,
        "roi": (10, 20, 80, 60),
        "target": (20, 30, 70, 30),
        "bundle_directory": tmp_path / "bundle",
        "vqa_run_directory": tmp_path / "vqa",
    }
    case = AuditCase(**cast(Any, values))
    panels = [
        (label, np.full((60, 80, 3), 255, np.uint8))
        for label in (
            "SOURCE",
            "PROCESSING INPUT",
            "BINARY",
            "RAW",
            "FILTERED",
            "GEOMETRY",
            "FINALSTRUCTURE",
            "VQA FINAL",
        )
    ]
    monkeypatch.setattr(line_integrity_audit, "_case_panels", lambda _case: panels)
    output = tmp_path / "case.png"

    build_case_artifact(case, output)

    rendered = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert rendered is not None
    assert rendered.shape == (816, 1440, 3)
    assert case.roi == (10, 20, 80, 60)
    assert case.target == (20, 30, 70, 30)
