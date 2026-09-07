from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.draftsman_domain_pack import ElectricalDomainPackV0
from app.draftsman_family_audit import (
    DRAFTSMAN_EXCEPTION_AUDIT_VERSION,
    DRAFTSMAN_FAMILY_AUDIT_VERSION,
    ExceptionType,
    FailureLayer,
    FamilyAuditReference,
    FamilyAuditResult,
    FamilyInstanceState,
    audit_electrical_family,
    write_family_audit_artifacts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_RASTER = (
    PROJECT_ROOT / "tests" / "real_regression" / "assets" / "environment-page-003.png"
)
FAMILY_REFERENCE = (
    PROJECT_ROOT
    / "tests"
    / "real_regression"
    / "assets"
    / "references"
    / "environment-page-003-smoke-family-v1.json"
)
FROZEN_VS3_RULE_ID = (
    "draftsman-electrical-symbol-rule:"
    "e00681670dacb88eb870fe779e5c49360a479d1779dd64237f29e1b0cb17cb9b"
)


@pytest.fixture(scope="module")
def family_reference() -> FamilyAuditReference:
    return FamilyAuditReference.load(FAMILY_REFERENCE)


@pytest.fixture(scope="module")
def family_replays(
    family_reference: FamilyAuditReference,
) -> tuple[FamilyAuditResult, FamilyAuditResult]:
    return tuple(  # type: ignore[return-value]
        audit_electrical_family(GOLDEN_RASTER, reference=family_reference)
        for _ in range(2)
    )


def test_reference_is_audit_truth_not_runtime_detection_input(
    family_reference: FamilyAuditReference,
) -> None:
    assert len(family_reference.instances) == 38
    assert {item.drawing_tag for item in family_reference.instances} == {
        str(value) for value in range(140, 178)
    }
    assert family_reference.source_page == 3
    assert family_reference.image_size_px == (2478, 1752)
    assert family_reference.frozen_rule_id == FROZEN_VS3_RULE_ID
    assert len(family_reference.baseline_slice_reference_ids) == 5


def test_vs3_rule_is_frozen_and_unchanged_during_family_audit(
    family_reference: FamilyAuditReference,
) -> None:
    pack = ElectricalDomainPackV0.create()
    rule = next(
        item
        for item in pack.electrical_symbol_rules
        if item.inventory_canonical_identity == "感烟"
    )
    assert rule.rule_id == family_reference.frozen_rule_id == FROZEN_VS3_RULE_ID
    signature = rule.raster_recognition_signature
    assert signature is not None
    assert signature.minimum_template_score == 0.62
    assert signature.minimum_ring_coverage == 0.60
    assert signature.minimum_port_support == 0.85
    assert signature.minimum_aligned_repetition == 5
    assert signature.alignment_tolerance_px == 5.0


def test_source_wide_discovery_runs_once_on_the_full_page(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    result = family_replays[0]
    assert result.vs3.evidence.image_size_px == (2478, 1752)
    assert len(result.vs3.evidence.candidates) == 154
    assert result.to_dict()["runtime"]["mode"] == "SOURCE_WIDE_DISCOVERY"  # type: ignore[index]
    assert result.to_dict()["runtime"]["source_crop_count"] == 0  # type: ignore[index]


def test_frozen_rule_family_result_is_measured_not_forced(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    summary = family_replays[0].summary
    assert summary.expected_instances == 38
    assert summary.source_wide_detected_instances == 5
    assert summary.matched_instances == 5
    assert summary.auto_accepted == 5
    assert summary.review_required == 32
    assert summary.missed == 1
    assert summary.invalid_output == 0
    assert summary.false_positives == 0
    assert summary.automatic_acceptance_rate == pytest.approx(5 / 38)
    assert summary.auto_accepted_beyond_baseline == 0
    assert summary.manual_review_items == summary.review_items_per_page == 33


def test_every_expected_instance_has_complete_instance_audit(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    result = family_replays[0]
    assert len(result.instances) == 38
    assert {item.reference_instance_id for item in result.instances} == {
        item.reference_instance_id for item in result.reference.instances
    }
    assert all(item.source_bbox_px for item in result.instances)
    assert all(
        item.exception_state is FamilyInstanceState.AUTO_ACCEPTED
        or (item.exception_ids and item.exception_reasons and item.failure_layer)
        for item in result.instances
    )
    assert all(
        item.logical_entity_id and item.cad_ir_entity_ids
        for item in result.instances
        if item.exception_state is FamilyInstanceState.AUTO_ACCEPTED
    )


def test_exception_classification_has_concrete_factors_and_layer(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    result = family_replays[0]
    assert len(result.exceptions) == 33
    assert {item.exception_type for item in result.exceptions} == {
        ExceptionType.EVIDENCE_MISSED,
        ExceptionType.DOMAIN_NO_MATCH,
        ExceptionType.PORT_MISMATCH,
    }
    assert all(item.factors and item.reason for item in result.exceptions)
    assert all(
        item.exception_type is not ExceptionType.LOW_CONFIDENCE
        for item in result.exceptions
    )
    failure_distribution = dict(result.summary.failure_distribution)
    assert failure_distribution == {
        "ASSEMBLY": 0,
        "DOMAIN": 10,
        "EVIDENCE": 1,
        "LOGICAL_ENTITY": 0,
        "TOPOLOGY": 22,
    }


def test_false_positive_detection_reports_unmatched_emitted_entity(
    family_reference: FamilyAuditReference,
) -> None:
    without_one_auto_instance = replace(
        family_reference,
        instances=tuple(
            item for item in family_reference.instances if item.drawing_tag != "147"
        ),
        baseline_slice_reference_ids=tuple(
            item
            for item in family_reference.baseline_slice_reference_ids
            if item != "ELEC-150-S01-147"
        ),
    )
    result = audit_electrical_family(
        GOLDEN_RASTER,
        reference=without_one_auto_instance,
    )
    false_positives = tuple(
        item
        for item in result.exceptions
        if item.exception_type is ExceptionType.FALSE_POSITIVE
    )
    assert result.summary.false_positives == 1
    assert len(false_positives) == 1
    assert false_positives[0].expected_reference_id is None
    assert false_positives[0].failure_layer is FailureLayer.ASSEMBLY
    assert false_positives[0].evidence_ids


def test_editability_fragmentation_and_duplicate_audit_are_clean(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    result = family_replays[0]
    summary = result.summary
    assert summary.unnecessary_fragments == 0
    assert summary.duplicate_logical_entities == 0
    assert summary.duplicate_cad_ir_entities == 0
    assert summary.incorrect_line_through_symbol == 0
    assert summary.invalid_port_connections == 0
    auto = tuple(
        item
        for item in result.instances
        if item.exception_state is FamilyInstanceState.AUTO_ACCEPTED
    )
    assert all(item.port_count == 2 for item in auto)
    assert all(item.connected_line_count == 2 for item in auto)
    assert all("SYMBOL_BOUNDARY" in item.meaningful_gap_state for item in auto)


def test_systematic_variant_gaps_are_reported_without_rule_tuning(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    gaps = family_replays[0].summary.systematic_variant_gaps
    assert len(gaps) == 3
    assert all(item.startswith("SYSTEMATIC_VARIANT_GAP:") for item in gaps)
    assert any("tag" in item and "angled" in item for item in gaps)
    assert any("two-sided horizontal port" in item for item in gaps)
    assert any("scan-degraded glyph" in item for item in gaps)


def test_audit_contract_and_replay_are_deterministic(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
) -> None:
    first, second = family_replays
    assert first.schema_version == DRAFTSMAN_FAMILY_AUDIT_VERSION
    assert first.exceptions[0].schema_version == DRAFTSMAN_EXCEPTION_AUDIT_VERSION
    assert first.audit_id == second.audit_id
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.canonical_sha256 == second.canonical_sha256


def test_machine_readable_artifacts_support_headless_exception_review(
    family_replays: tuple[FamilyAuditResult, FamilyAuditResult],
    tmp_path: Path,
) -> None:
    result = family_replays[0]
    paths = write_family_audit_artifacts(
        tmp_path,
        source_path=GOLDEN_RASTER,
        result=result,
        replay_audit_ids=(result.audit_id, result.audit_id),
    )
    assert {item.name for item in paths} == {
        "family-audit.json",
        "exceptions.json",
        "logical-entities.json",
        "cad-ir.json",
        "VS3_FAMILY_AUDIT.md",
        "family-overview.png",
        "exceptions-overview.png",
    }
    family_payload = json.loads((tmp_path / "family-audit.json").read_text("utf-8"))
    exception_payload = json.loads((tmp_path / "exceptions.json").read_text("utf-8"))
    assert family_payload["summary"]["manual_review_items"] == 33
    assert family_payload["runtime"]["rules_modified_during_audit"] is False
    assert family_payload["runtime"]["source_crop_count"] == 0
    assert len(family_payload["instances"]) == 38
    assert exception_payload["exception_count"] == 33
    assert all(item["failure_layer"] for item in exception_payload["exceptions"])


def test_family_audit_is_shadow_only_and_production_unchanged() -> None:
    app_dir = PROJECT_ROOT / "app"
    production_entrypoints = (
        "pipeline.py",
        "pipeline_service.py",
        "trace_single_export.py",
        "dxf_exporter.py",
    )
    for filename in production_entrypoints:
        source = (app_dir / filename).read_text(encoding="utf-8")
        assert "draftsman_family_audit" not in source
    runtime_source = (app_dir / "draftsman_family_audit.py").read_text(
        encoding="utf-8"
    )
    assert "environment-page-003.png" not in runtime_source
    assert "source_page == 3" not in runtime_source
    assert "1802, 864" not in runtime_source
