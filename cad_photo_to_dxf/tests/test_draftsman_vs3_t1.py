from __future__ import annotations

from hashlib import sha256
from math import hypot
from pathlib import Path

import pytest

from app.draftsman_family_audit import FamilyAuditReference
from app.draftsman_raster_evidence import RasterElectricalCandidateEvidence
from app.draftsman_vs3_t1 import (
    BOUNDARY_RULE_ID,
    T1FamilyAudit,
    T1HypothesisState,
    T1TopologyHypothesis,
    T1TopologyRole,
    _LineObservation,
    _boundary_rays,
    audit_draftsman_vs3_t1_family,
    write_draftsman_vs3_t1_artifacts,
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
FROZEN_EVIDENCE_HASHES = {
    "draftsman_raster_evidence.py": (
        "0bd224cd748ccb3f17a769d1a812be727069749ae27639363a5d14a6b384ec84"
    ),
    "draftsman_evidence_audit.py": (
        "b42fb696372b0700e08a542536785fb0785d284da694907d9f7e39d72a274b4d"
    ),
}


@pytest.fixture(scope="module")
def family_replays() -> tuple[T1FamilyAudit, T1FamilyAudit]:
    reference = FamilyAuditReference.load(FAMILY_REFERENCE)
    return tuple(  # type: ignore[return-value]
        audit_draftsman_vs3_t1_family(GOLDEN_RASTER, reference=reference)
        for _ in range(2)
    )


def _candidate() -> RasterElectricalCandidateEvidence:
    return RasterElectricalCandidateEvidence(
        stable_candidate_id="candidate:test",
        glyph_evidence_id="glyph:test",
        tag_evidence_id="tag:test",
        nearby_line_evidence_ids=(),
        source_center_px=(100, 100),
        radius_px=12,
        left_line_support=0.0,
        right_line_support=0.0,
        normalized_frame_bounds=(88.0, 88.0, 112.0, 112.0),
    )


def test_evidence_implementation_is_frozen() -> None:
    for filename, expected in FROZEN_EVIDENCE_HASHES.items():
        content = (PROJECT_ROOT / "app" / filename).read_bytes()
        assert sha256(content).hexdigest() == expected


def test_boundary_incidence_excludes_nearby_crossing_and_gap_lines() -> None:
    observations = (
        _LineObservation("connected", (112.0, 100.0), (150.0, 110.0)),
        _LineObservation("nearby", (116.0, 90.0), (145.0, 90.0)),
        _LineObservation("crossing", (70.0, 100.0), (130.0, 100.0)),
        _LineObservation("gap", (119.0, 100.0), (150.0, 100.0)),
    )
    rays = _boundary_rays(_candidate(), observations)
    assert [item.evidence_id for item in rays] == ["connected"]
    assert rays[0].outward_point == (150.0, 110.0)


def test_domain_identity_is_retained_before_topology(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit],
) -> None:
    result = family_replays[0].result
    assert len(result.domain_hypotheses) == len(result.evidence.candidates) == 154
    no_port_candidates = {
        item.candidate_id for item in result.topology_hypotheses if not item.ports
    }
    domains = {item.candidate_id: item for item in result.domain_hypotheses}
    assert no_port_candidates
    assert no_port_candidates <= domains.keys()
    assert any(
        domains[item].domain_identity == "ELECTRICAL.FIRE_ALARM.SMOKE_DETECTOR"
        for item in no_port_candidates
    )


def test_orientation_neutral_ports_preserve_angle_degree_and_provenance(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit],
) -> None:
    result = family_replays[0].result
    assert {len(item.connections) for item in result.logical_symbols} == {1, 2, 3}
    assert {item.topology_role for item in result.logical_symbols} == {
        T1TopologyRole.TERMINAL,
        T1TopologyRole.SERIES,
        T1TopologyRole.BRANCH,
    }
    accepted = [
        item
        for item in result.topology_hypotheses
        if item.state is T1HypothesisState.ACCEPTED
    ]
    ports = [port for item in accepted for port in item.ports]
    assert ports
    assert all(port.rule_id == BOUNDARY_RULE_ID for port in ports)
    assert all(port.connected_line_evidence_ids for port in ports)
    assert all(hypot(*port.observed_direction_vector) == pytest.approx(1.0) for port in ports)
    assert any(
        abs(port.observed_direction_vector[0]) > 0.05
        and abs(port.observed_direction_vector[1]) > 0.05
        for port in ports
    )


def test_logical_and_cad_connections_stop_at_symbol_boundaries(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit],
) -> None:
    result = family_replays[0].result
    for symbol in result.logical_symbols:
        for connection in symbol.connections:
            distance = hypot(
                connection.start[0] - symbol.center[0],
                connection.start[1] - symbol.center[1],
            )
            assert distance == pytest.approx(symbol.radius, abs=1e-5)
            assert connection.end != symbol.center
    assert len(result.cad_ir.lines) == sum(
        len(item.connections) for item in result.logical_symbols
    )


def test_competing_topologies_remain_reversible(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit],
) -> None:
    hypotheses = family_replays[0].result.topology_hypotheses
    grouped: dict[str, list[T1TopologyHypothesis]] = {}
    for hypothesis in hypotheses:
        grouped.setdefault(hypothesis.candidate_id, []).append(hypothesis)
    alternatives = [items for items in grouped.values() if len(items) > 1]
    assert alternatives
    assert any(
        {item.state for item in items}
        >= {T1HypothesisState.PROVISIONAL, T1HypothesisState.UNRESOLVED}
        for items in alternatives
    )


def test_family_replay_is_deterministic_and_reduces_review_without_false_accepts(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit],
) -> None:
    first, second = family_replays
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.audit_id == second.audit_id
    assert first.summary == {
        "expected_family": 38,
        "evidence_candidates": 154,
        "domain_hypotheses": 154,
        "topology_hypotheses": 162,
        "accepted_logical_instances": 26,
        "auto_accepted": 26,
        "review_required": 11,
        "missed": 1,
        "invalid_output": 0,
        "final_false_positives": 0,
        "t0_predicted_resolvable": 28,
        "actually_newly_resolved": 23,
        "logical_evaluated": 26,
        "logical_failures": 0,
        "assembly_evaluated": 26,
        "assembly_failures": 0,
        "incorrect_line_through_symbol": 0,
        "unnecessary_fragments": 0,
        "duplicate_logical_entities": 0,
        "duplicate_cad_ir_entities": 0,
        "unsupported_geometry": 0,
        "real_topology_families_supported": 3,
        "semantic_unverified_editable_fallback_implemented": False,
        "silent_omission_auditor_implemented": False,
    }


def test_runtime_has_no_fixture_or_absolute_side_semantics() -> None:
    source = (PROJECT_ROOT / "app" / "draftsman_vs3_t1.py").read_text(encoding="utf-8")
    runtime_source = source.split("def _match_reference_candidates", maxsplit=1)[0]
    forbidden = (
        "ELEC-150-S01",
        "environment-page",
        "ElectricalPortSide",
        "LEFT_ALARM_BUS",
        "RIGHT_ALARM_BUS",
        "source_page ==",
    )
    assert not any(item in runtime_source for item in forbidden)


def test_required_artifacts_are_self_contained(
    family_replays: tuple[T1FamilyAudit, T1FamilyAudit], tmp_path: Path
) -> None:
    audit = family_replays[0]
    paths = write_draftsman_vs3_t1_artifacts(
        tmp_path,
        audit=audit,
        replay_audit_ids=(audit.audit_id, family_replays[1].audit_id),
    )
    assert {item.name for item in paths} == {
        "VS3_T1_REPORT.md",
        "t1-cad-ir.json",
        "t1-comparison.json",
        "t1-family-audit.json",
        "t1-hypotheses.json",
        "t1-logical-entities.json",
        "t1-topology-decisions.json",
    }
    assert all(item.stat().st_size > 0 for item in paths)
