from __future__ import annotations

from hashlib import sha256
import inspect
from math import hypot
from pathlib import Path

import ezdxf
from PIL import Image
import pytest

from app.draftsman_family_audit import FamilyAuditReference
from app.draftsman_vs3_u1 import (
    SEMANTIC_IDENTITY_UNVERIFIED,
    TOPOLOGY_UNVERIFIED,
    U1FamilyAudit,
    U1GeometryDisposition,
    audit_draftsman_vs3_u1_family,
    preserve_draftsman_vs3_u1,
    write_draftsman_vs3_u1_artifacts,
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
FROZEN_HASHES = {
    "draftsman_raster_evidence.py": (
        "0bd224cd748ccb3f17a769d1a812be727069749ae27639363a5d14a6b384ec84"
    ),
    "draftsman_evidence_audit.py": (
        "b42fb696372b0700e08a542536785fb0785d284da694907d9f7e39d72a274b4d"
    ),
    "draftsman_vs3_t1.py": (
        "b17b0af0130566a0fc342ed70abd8ec5eb89ec1682c2e6c0ae077361863fda76"
    ),
}


@pytest.fixture(scope="module")
def family_replays() -> tuple[U1FamilyAudit, U1FamilyAudit]:
    reference = FamilyAuditReference.load(FAMILY_REFERENCE)
    return tuple(  # type: ignore[return-value]
        audit_draftsman_vs3_u1_family(GOLDEN_RASTER, reference=reference)
        for _ in range(2)
    )


def test_frozen_evidence_and_t1_implementation_are_unchanged() -> None:
    for filename, expected in FROZEN_HASHES.items():
        assert sha256((PROJECT_ROOT / "app" / filename).read_bytes()).hexdigest() == expected


def test_verified_t1_entities_remain_the_only_verified_path(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    audit = family_replays[0]
    assert len(audit.result.t1_result.logical_symbols) == 26
    assert audit.summary["verified_accepted_preserved"] == 26
    verified_ids = {item.candidate_id for item in audit.result.t1_result.logical_symbols}
    unverified_ids = {item.candidate_id for item in audit.result.unverified_symbols}
    assert verified_ids.isdisjoint(unverified_ids)
    assert len(audit.result.cad_ir["verified_symbols"]) == 26  # type: ignore[arg-type]


def test_unverified_semantics_do_not_block_editable_geometry(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    audit = family_replays[0]
    family_preserved = [
        item
        for item in audit.instances
        if item["u1_disposition"]
        == U1GeometryDisposition.EDITABLE_GEOMETRY_PRESERVED.value
    ]
    assert len(family_preserved) == 10
    entities = {item.logical_entity_id: item for item in audit.result.unverified_symbols}
    for item in family_preserved:
        logical_entity_id = item["unverified_logical_entity_id"]
        assert isinstance(logical_entity_id, str)
        entity = entities[logical_entity_id]
        assert entity.semantic_state == SEMANTIC_IDENTITY_UNVERIFIED
        assert entity.topology_state == TOPOLOGY_UNVERIFIED
        assert "SEMANTIC_REVIEW_REQUIRED" in entity.review_state
        assert "TOPOLOGY_REVIEW_REQUIRED" in entity.review_state
        assert len(entity.competing_semantic_hypotheses) == 2
        assert entity.competing_semantic_hypotheses[0]["state"] == (
            "CANDIDATE_ONLY_NOT_AUTHORITATIVE"
        )


def test_family_denominators_and_safety_metrics_are_separate(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    assert family_replays[0].summary == {
        "expected_family": 38,
        "verified_accepted": 26,
        "verified_accepted_preserved": 26,
        "previously_unaccepted_evaluated": 12,
        "semantic_unverified_candidates": 11,
        "editable_geometry_preserved": 10,
        "insufficient_geometry_evidence": 2,
        "geometry_conflict": 0,
        "other": 0,
        "unverified_editable_cad_entities": 10,
        "editable_cad_coverage": 36,
        "semantic_false_promotions": 0,
        "duplicate_final_representations": 0,
        "unsupported_geometry": 0,
        "invented_geometry": 0,
        "invented_ports": 0,
        "incorrect_line_through_symbol": 0,
        "unnecessary_fragments": 0,
        "source_wide_unverified_groups": 71,
    }


def test_unverified_cad_is_editable_traceable_and_has_no_invented_ports(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    audit = family_replays[0]
    groups = audit.result.cad_ir["unverified_groups"]
    assert isinstance(groups, list)
    by_logical = {item.logical_entity_id: item for item in audit.result.unverified_symbols}
    assert len(groups) == len(by_logical)
    for group in groups:
        entity = by_logical[group["logical_entity_id"]]
        assert group["semantic_state"] == SEMANTIC_IDENTITY_UNVERIFIED
        assert group["review_required"] is True
        assert len(group["entities"]) == 1
        body = group["entities"][0]
        assert body["entity_type"] == "EDITABLE_CIRCLE"
        assert body["source_evidence_id"] == entity.body_evidence_id
        assert body["source_evidence_id"] in entity.source_evidence_ids
        assert "ports" not in group
    relations = audit.result.cad_ir["provisional_relations"]
    assert isinstance(relations, list) and relations
    assert all("cad_entity_id" not in item for item in relations)
    assert all(item["topology_state"] == TOPOLOGY_UNVERIFIED for item in relations)


def test_verified_lines_stop_at_boundaries_and_unknown_groups_emit_no_lines(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    audit = family_replays[0]
    for symbol in audit.result.t1_result.logical_symbols:
        for connection in symbol.connections:
            distance = hypot(
                connection.start[0] - symbol.center[0],
                connection.start[1] - symbol.center[1],
            )
            assert distance == pytest.approx(symbol.radius, abs=1e-5)
    groups = audit.result.cad_ir["unverified_groups"]
    assert isinstance(groups, list)
    assert all(
        primitive["entity_type"] != "EDITABLE_LINE"
        for group in groups
        for primitive in group["entities"]
    )


def test_u1_runtime_has_no_reference_or_fixture_coordinate_path() -> None:
    runtime_source = inspect.getsource(preserve_draftsman_vs3_u1)
    forbidden = (
        "ELEC-150-S01",
        "environment-page",
        "FamilyAuditReference",
        "source_page ==",
        "source_center_px == (",
        "SMOKE_DETECTOR",
    )
    assert not any(item in runtime_source for item in forbidden)


def test_u1_replay_and_all_fallback_ids_are_deterministic(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit],
) -> None:
    first, second = family_replays
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.audit_id == second.audit_id
    assert [item.logical_entity_id for item in first.result.unverified_symbols] == [
        item.logical_entity_id for item in second.result.unverified_symbols
    ]


def test_artifacts_and_preview_are_valid_editable_outputs(
    family_replays: tuple[U1FamilyAudit, U1FamilyAudit], tmp_path: Path
) -> None:
    audit = family_replays[0]
    paths = write_draftsman_vs3_u1_artifacts(
        tmp_path,
        source=GOLDEN_RASTER,
        audit=audit,
        replay_audit_ids=(audit.audit_id, family_replays[1].audit_id),
    )
    assert {item.name for item in paths} == {
        "VS3_U1_REPORT.md",
        "u1-cad-ir.json",
        "u1-comparison.json",
        "u1-family-audit.json",
        "u1-family-overview.png",
        "u1-preview.dxf",
        "u1-review-items.json",
        "u1-review-overview.png",
        "u1-unverified-entities.json",
    }
    assert all(item.stat().st_size > 0 for item in paths)
    with Image.open(tmp_path / "u1-review-overview.png") as image:
        assert image.size == (2478, 1752)
    document = ezdxf.readfile(tmp_path / "u1-preview.dxf")
    assert len(document.modelspace().query("CIRCLE[layer=='U1_UNVERIFIED']")) == 71
    assert not document.modelspace().query("IMAGE")


def test_u1_is_not_imported_by_production_entrypoints() -> None:
    entrypoints = (
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "app" / "document_export.py",
        PROJECT_ROOT / "app" / "dxf_exporter.py",
    )
    assert all("draftsman_vs3_u1" not in path.read_text(encoding="utf-8") for path in entrypoints)
