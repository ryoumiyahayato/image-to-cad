from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path

import pytest

from app.draftsman_qa1 import (
    CadRecord,
    CandidateDisposition,
    FindingFamily,
    LogicalRecord,
    audit_draftsman_qa1,
    audit_qa1_lineage,
    input_from_u1,
    measurement_only_omission_signals,
)
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1
from app.draftsman_vs3_u1 import preserve_draftsman_vs3_u1


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_RASTER = (
    PROJECT_ROOT / "tests" / "real_regression" / "assets" / "environment-page-003.png"
)


@pytest.fixture(scope="module")
def replays():  # type: ignore[no-untyped-def]
    results = []
    for _ in range(2):
        t1 = run_draftsman_vs3_t1(
            GOLDEN_RASTER, source_document_id="environment", source_page=3
        )
        u1 = preserve_draftsman_vs3_u1(t1)
        results.append((u1, input_from_u1(u1), audit_draftsman_qa1(u1)))
    return tuple(results)


def test_reference_free_auditor_and_denominators(replays) -> None:  # type: ignore[no-untyped-def]
    _, data, audit = replays[0]
    assert "reference" not in inspect.signature(audit_qa1_lineage).parameters
    runtime_source = inspect.getsource(audit_qa1_lineage)
    assert not any(
        value in runtime_source
        for value in ("FamilyAuditReference", "ELEC-150-S01", "expected_family", "38")
    )
    assert data.u1_result_id
    assert audit.summary["evidence_candidates"] == 154
    assert audit.summary["domain_hypotheses"] == 154
    assert audit.summary["topology_hypotheses"] == 162
    assert audit.summary["logical_entities"] == 97
    assert audit.summary["cad_ir_entities"] == 146
    assert audit.summary["review_items"] == 71


def test_every_candidate_has_one_deterministic_disposition(replays) -> None:  # type: ignore[no-untyped-def]
    first = replays[0][2]
    second = replays[1][2]
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.audit_id == second.audit_id
    assert len(first.ledger) == len({item.candidate_id for item in first.ledger}) == 154
    assert first.summary["candidate_dispositions"] == {
        "REPRESENTED_VERIFIED": 26,
        "REPRESENTED_UNVERIFIED": 71,
        "EXPLICIT_REVIEW": 0,
        "EXPLICIT_REJECTION": 31,
        "LIKELY_NOISE": 26,
        "UNEXPLAINED": 0,
    }


def test_logical_and_cad_lineage_are_complete(replays) -> None:  # type: ignore[no-untyped-def]
    audit = replays[0][2]
    assert audit.summary["logical_entities_without_provenance"] == 0
    assert audit.summary["cad_ir_without_logical_lineage"] == 0
    assert audit.summary["cad_ir_without_source_provenance"] == 0
    assert not audit.findings


def test_unverified_semantic_and_review_state_are_preserved(replays) -> None:  # type: ignore[no-untyped-def]
    u1, _, audit = replays[0]
    entries = {
        item.candidate_id: item
        for item in audit.ledger
        if item.final_disposition is CandidateDisposition.REPRESENTED_UNVERIFIED
    }
    assert len(entries) == len(u1.unverified_symbols) == 71
    for entity in u1.unverified_symbols:
        entry = entries[entity.candidate_id]
        assert entry.related_cad_ir_entity_ids
        assert entry.related_review_item_ids
        assert entity.semantic_state == "SEMANTIC_IDENTITY_UNVERIFIED"


def test_duplicate_verified_unverified_is_detected(replays) -> None:  # type: ignore[no-untyped-def]
    _, data, _ = replays[0]
    verified = next(item for item in data.logical_entities if item.semantic_state == "VERIFIED")
    duplicate = LogicalRecord(
        "logical:test-unverified-duplicate",
        verified.candidate_id,
        "SEMANTIC_IDENTITY_UNVERIFIED",
        verified.source_evidence_ids,
        verified.source_region,
    )
    finding_families = {
        item.family
        for item in audit_qa1_lineage(
            replace(data, logical_entities=(*data.logical_entities, duplicate))
        ).findings
    }
    assert FindingFamily.VERIFIED_AND_UNVERIFIED_DOUBLE_REPRESENTATION in finding_families


def test_orphan_cad_and_hypothesis_are_detected(replays) -> None:  # type: ignore[no-untyped-def]
    _, data, _ = replays[0]
    orphan_cad = CadRecord("cad:test-orphan", None, (), "VERIFIED")
    domain = dict(data.domain_hypotheses[0])
    domain["hypothesis_id"] = "hypothesis:test-orphan"
    domain["source_evidence_ids"] = ["evidence:missing"]
    audited = audit_qa1_lineage(
        replace(
            data,
            cad_entities=(*data.cad_entities, orphan_cad),
            domain_hypotheses=(*data.domain_hypotheses, domain),
        )
    )
    families = {item.family for item in audited.findings}
    assert FindingFamily.CAD_IR_WITHOUT_LOGICAL_ENTITY in families
    assert FindingFamily.CAD_IR_WITHOUT_SOURCE_PROVENANCE in families
    assert FindingFamily.HYPOTHESIS_WITHOUT_EVIDENCE in families


def test_explicit_rejection_and_likely_noise_are_success_dispositions(replays) -> None:  # type: ignore[no-untyped-def]
    audit = replays[0][2]
    rejected = [
        item
        for item in audit.ledger
        if item.final_disposition is CandidateDisposition.EXPLICIT_REJECTION
    ]
    noise = [
        item
        for item in audit.ledger
        if item.final_disposition is CandidateDisposition.LIKELY_NOISE
    ]
    assert len(rejected) == 31 and all(item.rejection_record for item in rejected)
    assert len(noise) == 26 and all(item.rejection_record for item in noise)
    assert all(not item.auditor_finding_ids for item in noise)


def test_measurement_only_signals_are_not_actionable(replays) -> None:  # type: ignore[no-untyped-def]
    u1, _, audit = replays[0]
    measurement = measurement_only_omission_signals(u1)
    assert measurement["total_alerts"] == 37
    assert measurement["actionable_review_alerts"] == 0
    assert audit.summary["actionable_findings"] == {"INFO": 0, "REVIEW": 0, "ERROR": 0}


def test_auditor_is_read_only_and_shadow_only(replays) -> None:  # type: ignore[no-untyped-def]
    u1, _, _ = replays[0]
    before = u1.canonical_bytes()
    audit_draftsman_qa1(u1)
    assert u1.canonical_bytes() == before
    entrypoints = (
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "app" / "document_export.py",
        PROJECT_ROOT / "app" / "dxf_exporter.py",
    )
    assert all("draftsman_qa1" not in path.read_text(encoding="utf-8") for path in entrypoints)
