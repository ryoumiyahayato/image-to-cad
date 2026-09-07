from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.draftsman_evidence_audit import (
    DRAFTSMAN_EVIDENCE_FAMILY_AUDIT_VERSION,
    EvidenceAuditBaseline,
    EvidenceFamilyAuditResult,
    audit_raster_evidence_family,
    write_evidence_family_audit_artifacts,
)
from app.draftsman_family_audit import FamilyAuditReference
from app.draftsman_raster_evidence import (
    DRAFTSMAN_RASTER_EVIDENCE_VERSION,
    RasterGlyphEvidence,
    RasterLineSegmentEvidence,
    RasterRelativePosition,
    RasterSpatialRelationKind,
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
EVIDENCE_BASELINE = FAMILY_REFERENCE.with_name(
    "environment-page-003-smoke-evidence-baseline-v1.json"
)
FROZEN_DOWNSTREAM_SHA256 = {
    "draftsman_domain_pack.py": (
        "ccf8fc3f08777fbf3d7082615a131be51f7e3d2fb1d1a727fbf35de2fa265c10"
    ),
    "draftsman_raster_electrical.py": (
        "5ff535159c23fb7af95e910d957abcd77d7c0baced18d3662edda518d5c7fb61"
    ),
    "draftsman_electrical.py": (
        "2f90a4d7fc0f4bb20bda88830fee75ca867929da00ab43ce08d1a3f0649b0bfe"
    ),
    "draftsman_cad_ir.py": (
        "fda7c948e927bfacaa2b59dfb9c2c819a84426f7ba70b4fda1ed64124f1313b8"
    ),
}


@pytest.fixture(scope="module")
def reference() -> FamilyAuditReference:
    return FamilyAuditReference.load(FAMILY_REFERENCE)


@pytest.fixture(scope="module")
def baseline() -> EvidenceAuditBaseline:
    return EvidenceAuditBaseline.load(EVIDENCE_BASELINE)


@pytest.fixture(scope="module")
def evidence_replays(
    reference: FamilyAuditReference,
    baseline: EvidenceAuditBaseline,
) -> tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult]:
    return tuple(  # type: ignore[return-value]
        audit_raster_evidence_family(
            GOLDEN_RASTER,
            reference=reference,
            baseline=baseline,
        )
        for _ in range(2)
    )


def test_evidence_contract_is_fact_typed_and_domain_neutral(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    evidence = evidence_replays[0].evidence
    assert evidence.schema_version == DRAFTSMAN_RASTER_EVIDENCE_VERSION
    assert DRAFTSMAN_RASTER_EVIDENCE_VERSION == "draftsman-raster-evidence-v2"
    counts = Counter(item.kind.value for item in evidence.primitives)
    assert set(counts) == {
        "GLYPH_SHAPE",
        "TAG_REGION",
        "LINE_FRAGMENT",
        "LINE_SEGMENT",
        "ENDPOINT",
        "REGION",
    }
    serialized = evidence.canonical_bytes().decode("utf-8")
    assert "SMOKE_DETECTOR" not in serialized
    assert "TWO_PORT_DEVICE" not in serialized
    assert "BELOW_TAG_DEVICE" not in serialized
    assert all("confidence" in item.to_dict() for item in evidence.primitives)
    assert all("confidence" in item.to_dict() for item in evidence.candidates)


def test_tag_position_is_observed_not_semantically_filtered(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    positions = {
        item.relative_position
        for item in evidence_replays[0].evidence.spatial_relations
        if item.relation_kind is RasterSpatialRelationKind.NEAR
    }
    assert {
        RasterRelativePosition.ABOVE,
        RasterRelativePosition.BELOW,
        RasterRelativePosition.LEFT,
        RasterRelativePosition.RIGHT,
    }.issubset(positions)
    source = (PROJECT_ROOT / "app" / "draftsman_raster_evidence.py").read_text(
        encoding="utf-8"
    )
    assert "minimum_tag_dy_px" not in source
    assert "maximum_tag_dy_px" not in source


def test_port_direction_does_not_filter_raw_observations(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    evidence = evidence_replays[0].evidence
    line_angles = {
        round(item.orientation_degrees)
        for item in evidence.primitives
        if isinstance(item, RasterLineSegmentEvidence)
    }
    assert any(20 <= angle <= 70 for angle in line_angles)
    assert any(80 <= angle <= 100 for angle in line_angles)
    assert any(
        max(item.left_line_support, item.right_line_support) < 0.55
        for item in evidence.candidates
    )
    source = (PROJECT_ROOT / "app" / "draftsman_raster_evidence.py").read_text(
        encoding="utf-8"
    )
    assert "evidence_port_support_minimum" not in source


def test_partial_or_isolated_glyph_observations_survive_without_candidate(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    evidence = evidence_replays[0].evidence
    candidate_glyph_ids = {item.glyph_evidence_id for item in evidence.candidates}
    independent_glyphs = {
        item.stable_evidence_id
        for item in evidence.primitives
        if isinstance(item, RasterGlyphEvidence)
    }
    assert len(independent_glyphs) == 195
    assert independent_glyphs - candidate_glyph_ids


def test_source_wide_evidence_coverage_and_frozen_downstream_are_distinct(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    result = evidence_replays[0]
    summary = result.summary
    assert result.to_dict()["runtime"]["mode"] == "ONE_SOURCE_WIDE_DISCOVERY_RUN"  # type: ignore[index]
    assert result.to_dict()["runtime"]["source_crop_count"] == 0  # type: ignore[index]
    assert summary.expected_family == 38
    assert summary.evidence_coverage_before == 15
    assert summary.evidence_coverage_after == 37
    assert summary.original_evidence_failures_recovered == 22
    assert summary.remaining_evidence_failures == 1
    assert summary.auto_accepted == 5
    assert summary.review_required == 32
    assert summary.missed == 1
    assert summary.false_positives == 0
    assert dict(summary.failure_distribution) == {
        "ASSEMBLY": 0,
        "DOMAIN": 10,
        "EVIDENCE": 1,
        "LOGICAL_ENTITY": 0,
        "TOPOLOGY": 22,
    }


def test_remaining_evidence_failure_names_missing_observation(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    missing = [
        item for item in evidence_replays[0].instances if not item.evidence_covered
    ]
    assert len(missing) == 1
    assert missing[0].reference_instance_id == "ELEC-150-S01-165"
    assert missing[0].missing_evidence_types == ("GLYPH_SHAPE",)
    assert missing[0].nearby_line_evidence_ids
    assert missing[0].endpoint_evidence_ids
    assert missing[0].tag_evidence_ids
    assert missing[0].spatial_relation_ids


def test_candidate_growth_is_bounded_and_reported_by_kind(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    summary = evidence_replays[0].summary
    assert summary.evidence_candidates_before == 55
    assert summary.evidence_candidates_after == 154
    assert summary.candidate_growth_ratio == pytest.approx(2.8)
    assert summary.candidate_growth_percent == pytest.approx(180.0)
    assert summary.false_candidate_density_per_megapixel < 30.0
    assert dict(summary.primitive_counts_by_kind)["LINE_SEGMENT"] > 0
    assert summary.spatial_relation_count > 0


def test_full_source_candidate_and_audit_replay_are_deterministic(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
) -> None:
    first, second = evidence_replays
    assert first.schema_version == DRAFTSMAN_EVIDENCE_FAMILY_AUDIT_VERSION
    assert first.evidence.manifest_id == second.evidence.manifest_id
    assert first.evidence.canonical_bytes() == second.evidence.canonical_bytes()
    assert first.audit_id == second.audit_id
    assert first.canonical_bytes() == second.canonical_bytes()


def test_frozen_downstream_sources_are_byte_identical_to_base() -> None:
    app_dir = PROJECT_ROOT / "app"
    actual = {
        filename: sha256((app_dir / filename).read_bytes()).hexdigest()
        for filename in FROZEN_DOWNSTREAM_SHA256
    }
    assert actual == FROZEN_DOWNSTREAM_SHA256


def test_machine_readable_e1_artifacts_are_complete(
    evidence_replays: tuple[EvidenceFamilyAuditResult, EvidenceFamilyAuditResult],
    tmp_path: Path,
) -> None:
    first, second = evidence_replays
    paths = write_evidence_family_audit_artifacts(
        tmp_path,
        result=first,
        replay_audit_ids=(first.audit_id, second.audit_id),
        runtime_seconds=3.5,
    )
    assert {item.name for item in paths} == {
        "evidence-family-audit.json",
        "evidence-candidates.json",
        "downstream-comparison.json",
        "exceptions.json",
        "VS3_E1_REPORT.md",
    }
    audit = json.loads((tmp_path / "evidence-family-audit.json").read_text("utf-8"))
    comparison = json.loads(
        (tmp_path / "downstream-comparison.json").read_text("utf-8")
    )
    exceptions = json.loads((tmp_path / "exceptions.json").read_text("utf-8"))
    assert audit["deterministic_replay"] == {
        "audit_ids": [first.audit_id, second.audit_id],
        "passed": True,
        "runs": 2,
    }
    assert len(audit["instances"]) == 38
    assert comparison["frozen_downstream"] is True
    assert comparison["main_conclusion"] == "DOMAIN_TOPOLOGY_BOTTLENECK"
    assert len(exceptions["remaining_evidence_failures"]) == 1


def test_e1_shadow_modules_do_not_enter_production() -> None:
    app_dir = PROJECT_ROOT / "app"
    for filename in (
        "pipeline.py",
        "pipeline_service.py",
        "trace_single_export.py",
        "dxf_exporter.py",
    ):
        source = (app_dir / filename).read_text(encoding="utf-8")
        assert "draftsman_evidence_audit" not in source
        assert "draftsman_raster_evidence" not in source
