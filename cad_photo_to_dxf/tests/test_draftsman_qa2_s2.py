from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.draftsman_qa1 import audit_draftsman_qa1
from app.draftsman_qa2_s1 import measure_independent_source_coverage
from app.draftsman_qa2_s2 import (
    ControlPopulation,
    RiskTier,
    calibrate_reference_free,
    triage_source_coverage_risk,
)
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1
from app.draftsman_vs3_u1 import preserve_draftsman_vs3_u1


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "tests/real_regression/assets/environment-page-003.png"
FROZEN_CONFIG_ID = (
    "draftsman-qa2-s2-frozen-config:"
    "61f2543291a526960250c09776a621ce457939bf6c74393ed3f4348a8b5a3360"
)


@pytest.fixture(scope="module")
def replays():  # type: ignore[no-untyped-def]
    outputs = []
    for _ in range(2):
        t1 = run_draftsman_vs3_t1(
            SOURCE,
            source_document_id="environment-plan-page-003-150dpi",
            source_page=3,
        )
        u1 = preserve_draftsman_vs3_u1(t1)
        qa1 = audit_draftsman_qa1(u1)
        s1 = measure_independent_source_coverage(
            SOURCE, u1_result=u1, qa1_audit=qa1
        )
        qa1_before = qa1.canonical_bytes()
        s2 = triage_source_coverage_risk(
            SOURCE, s1_result=s1, qa1_audit=qa1
        )
        outputs.append((qa1, s1, s2, qa1_before))
    return tuple(outputs)


def test_s1_residual_generation_is_frozen(replays) -> None:  # type: ignore[no-untyped-def]
    _, s1, s2, _ = replays[0]
    assert len(s1.residual_regions) == 220
    assert s2.summary["raw_s1_residuals"] == 220
    assert s2.to_dict()["runtime_contract"]["s1_generation_modified"] is False


def test_calibration_is_reference_free_and_has_no_target_leakage(replays) -> None:  # type: ignore[no-untyped-def]
    runtime = inspect.getsource(triage_source_coverage_risk)
    calibration = inspect.getsource(calibrate_reference_free)
    assert "reference" not in inspect.signature(triage_source_coverage_risk).parameters
    forbidden = (
        "FamilyAuditReference",
        "ELEC-150-S01",
        "SMOKE",
        "expected_family",
        "source_center_px ==",
    )
    assert not any(item in runtime + calibration for item in forbidden)
    assert replays[0][2].to_dict()["runtime_contract"]["electrical_identity_used"] is False


def test_positive_and_negative_controls_come_from_qa1(replays) -> None:  # type: ignore[no-untyped-def]
    features = replays[0][2].features
    assert sum(
        item.population is ControlPopulation.POSITIVE_STRUCTURE for item in features
    ) == 22
    assert sum(
        item.population is ControlPopulation.NEGATIVE_LOW_VALUE for item in features
    ) == 15
    assert sum(item.population is ControlPopulation.RESIDUAL for item in features) == 220


def test_features_clusters_and_tiers_are_deterministic(replays) -> None:  # type: ignore[no-untyped-def]
    first = replays[0][2]
    second = replays[1][2]
    assert first.result_id == second.result_id
    assert first.canonical_bytes() == second.canonical_bytes()
    assert len(first.clusters) == 190
    assert first.summary["tiers"] == {
        "TIER_A_ACTIONABLE_CANDIDATE": 104,
        "TIER_B_MEASUREMENT_ONLY": 25,
        "TIER_C_LIKELY_LOW_VALUE": 61,
    }
    assert all(item.measurement_only for item in first.clusters)
    assert all(item.tier in set(RiskTier) for item in first.clusters)


def test_frozen_config_digest_is_stable_and_has_no_fixture_rules(replays) -> None:  # type: ignore[no-untyped-def]
    config = replays[0][2].config
    assert config.config_id == FROZEN_CONFIG_ID
    payload = config.to_dict()
    assert payload["frozen_before_golden_evaluation"] is True
    assert payload["generic_triage_rule_count"] == 4
    assert payload["drawing_specific_rule_count"] == 0
    assert payload["fixture_specific_rule_count"] == 0
    assert payload["timestamp_used"] is False


def test_golden_is_loaded_only_after_config_persistence() -> None:
    script = (
        PROJECT_ROOT / "scripts/generate_draftsman_qa2_s2.py"
    ).read_text(encoding="utf-8")
    frozen_write = script.index("write_frozen_config(frozen_path, result.config)")
    golden_load = script.index("FamilyAuditReference.load(args.reference)")
    assert frozen_write < golden_load
    after_load = script[golden_load:]
    assert "triage_source_coverage_risk(" not in after_load
    assert "calibrate_reference_free(" not in after_load


def test_qa1_dispositions_are_unchanged(replays) -> None:  # type: ignore[no-untyped-def]
    qa1, _, s2, before = replays[0]
    assert qa1.canonical_bytes() == before
    assert s2.to_dict()["runtime_contract"]["qa1_dispositions_modified"] is False
    assert s2.summary["actionable_review_queue_entries"] == 0


def test_s2_is_not_imported_by_production_entrypoints() -> None:
    entrypoints = (
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "app/document_export.py",
        PROJECT_ROOT / "app/dxf_exporter.py",
    )
    assert all(
        "draftsman_qa2_s2" not in path.read_text(encoding="utf-8")
        for path in entrypoints
    )
