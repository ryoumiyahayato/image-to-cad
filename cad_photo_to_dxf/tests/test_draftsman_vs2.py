from __future__ import annotations

import inspect
from pathlib import Path

import ezdxf
import pytest

from app.draftsman_cad_ir import DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION
from app.draftsman_domain_pack import ElectricalDomainPackV0
from app.draftsman_electrical import ElectricalDecisionState
from app.draftsman_pdf_vector import DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION
from app.draftsman_vs2 import (
    DraftsmanVs2Result,
    run_draftsman_vs2,
    write_vs2_preview_dxf,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PDF = (
    PROJECT_ROOT
    / "tests"
    / "real_regression"
    / "assets"
    / "sources"
    / "warehouse-electrical-vector.pdf"
)
GOLDEN_SHA256 = "8967fc042f4979f017ca4d27d25e66e7c9fbb2e46d840d0fd81e68268af31017"
SOURCE_DOCUMENT_ID = "warehouse-electrical-vector-pdf"


@pytest.fixture(scope="module")
def golden_replays() -> tuple[DraftsmanVs2Result, DraftsmanVs2Result]:
    return tuple(  # type: ignore[return-value]
        run_draftsman_vs2(
            GOLDEN_PDF,
            source_document_id=SOURCE_DOCUMENT_ID,
            page_number=2,
        )
        for _ in range(2)
    )


def test_native_pdf_path_extraction_uses_authoritative_vector_page(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    evidence = golden_replays[0].evidence
    assert evidence.schema_version == DRAFTSMAN_BOXED_SYMBOL_EVIDENCE_VERSION
    assert evidence.source_sha256 == GOLDEN_SHA256
    assert evidence.source_page == 2
    assert evidence.source_native_path_count == 168_335
    assert evidence.page_rotation_degrees == 270
    assert evidence.page_size_pt == (2523.0, 1786.0)
    assert len(evidence.primitives) > 1_000
    assert "render" not in inspect.getsource(type(evidence)).lower()


def test_evidence_layer_preserves_geometry_without_assigning_electrical_identity(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    result = golden_replays[0]
    accepted_candidate_id = result.decisions.accepted[0].candidate_id
    candidate = next(
        item
        for item in result.evidence.boxed_candidates
        if item.stable_candidate_id == accepted_candidate_id
    )
    assert not hasattr(candidate, "canonical_domain_identity")
    assert not hasattr(candidate, "ports")
    assert candidate.frame_primitive_ids
    assert candidate.interior_primitive_ids


def test_verified_symbol_domain_rule_matches_one_operational_instance(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    decisions = golden_replays[0].decisions
    assert len(decisions.accepted) == 1
    accepted = decisions.accepted[0]
    assert accepted.state is ElectricalDecisionState.ACCEPTED
    assert accepted.inventory_canonical_identity == "控制模块"
    assert (
        accepted.canonical_domain_identity
        == "ELECTRICAL.SINGLE_INPUT_OUTPUT_CONTROL_MODULE"
    )
    assert "DRAWING_LEGEND_GLYPH_SIGNATURE_MATCH" in accepted.reasons
    assert "PORT_TOPOLOGY_MATCH" in accepted.reasons


def test_port_topology_preserves_meaningful_symbol_boundaries(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    result = golden_replays[0]
    accepted = result.decisions.accepted[0]
    ports = {port.port_key: port for port in accepted.ports}
    assert set(ports) == {
        "TOP_SIGNAL_A",
        "TOP_SIGNAL_B",
        "BOTTOM_CONTROL_OUT",
        "BOTTOM_CONTROL_IN",
    }
    assert ports["BOTTOM_CONTROL_OUT"].direction == "OUT"
    assert ports["BOTTOM_CONTROL_IN"].direction == "IN"
    left, bottom, right, top = accepted.frame_bounds_pt
    for port in ports.values():
        x_value, y_value = port.location
        assert left <= x_value <= right
        assert y_value in {bottom, top}
        assert port.connection_start == port.location
        assert port.connection_end != port.location
    assert all(
        line.meaningful_boundary == "SYMBOL_BOUNDARY"
        for line in result.logical.connections
    )
    assert result.quality.incorrect_line_through_symbol == 0


def test_multiple_native_primitives_form_one_logical_symbol(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    result = golden_replays[0]
    assert result.quality.source_evidence_primitives == 61
    assert len(result.logical.symbols) == 1
    assert len(result.logical.connections) == 4
    assert len(result.logical.symbols[0].source_evidence_ids) == 61


def test_logical_entities_assemble_to_editable_cad_ir_without_fragments(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    result = golden_replays[0]
    assert result.cad_ir.schema_version == DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION
    assert len(result.cad_ir.symbols) == 1
    assert len(result.cad_ir.lines) == 4
    assert result.cad_ir.entity_count == 5
    assert result.cad_ir.symbols[0].block_definition_ref == "ELEC_CONTROL_MODULE_C1"
    assert {line.logical_line_id for line in result.cad_ir.lines} == {
        line.logical_line_id for line in result.logical.connections
    }
    assert result.quality.unsupported_geometry == 0
    assert result.quality.unnecessary_fragments == 0
    assert result.quality.invalid_port_connections == 0
    assert result.quality.domain_rule_violations == 0
    assert result.quality.passed


def test_symbol_and_complete_slice_replay_are_deterministic(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
) -> None:
    first, second = golden_replays
    assert first.replay_identity() == second.replay_identity()
    assert first.evidence.canonical_bytes() == second.evidence.canonical_bytes()
    assert first.decisions.canonical_bytes() == second.decisions.canonical_bytes()
    assert first.logical.canonical_bytes() == second.logical.canonical_bytes()
    assert first.cad_ir.canonical_bytes() == second.cad_ir.canonical_bytes()
    assert (
        first.decisions.accepted[0].stable_hypothesis_id
        == second.decisions.accepted[0].stable_hypothesis_id
    )


def test_domain_logic_contains_rules_not_golden_instance_answers() -> None:
    app_dir = PROJECT_ROOT / "app"
    sources = "\n".join(
        (app_dir / name).read_text(encoding="utf-8")
        for name in (
            "draftsman_pdf_vector.py",
            "draftsman_domain_pack.py",
            "draftsman_electrical.py",
            "draftsman_cad_ir.py",
        )
    )
    assert "warehouse-electrical-vector.pdf" not in sources
    assert GOLDEN_SHA256 not in sources
    assert "1001.040039" not in sources
    assert "1013.76001" not in sources
    assert "page_number == 2" not in sources


def test_preview_is_clean_editable_block_and_connections(
    golden_replays: tuple[DraftsmanVs2Result, DraftsmanVs2Result],
    tmp_path: Path,
) -> None:
    target = write_vs2_preview_dxf(tmp_path / "vs2-preview.dxf", golden_replays[0].cad_ir)
    document = ezdxf.readfile(target)
    entities = list(document.modelspace())
    assert [entity.dxftype() for entity in entities].count("INSERT") == 1
    assert [entity.dxftype() for entity in entities].count("LINE") == 4
    assert {entity.dxf.layer for entity in entities} == {
        "ELECTRICAL_SYMBOL",
        "ELECTRICAL_SIGNAL",
        "ELECTRICAL_CONTROL",
    }


def test_shadow_modules_are_not_imported_by_production_entrypoints() -> None:
    app_dir = PROJECT_ROOT / "app"
    production_entrypoints = (
        "pipeline.py",
        "pipeline_service.py",
        "trace_single_export.py",
        "dxf_exporter.py",
    )
    shadow_names = (
        "draftsman_pdf_vector",
        "draftsman_electrical",
        "draftsman_vs2",
    )
    for filename in production_entrypoints:
        source = (app_dir / filename).read_text(encoding="utf-8")
        assert not any(name in source for name in shadow_names)


def test_electrical_pack_rule_is_declarative_and_fixed_contract() -> None:
    pack = ElectricalDomainPackV0.create()
    assert len(pack.electrical_symbol_rules) == 1
    rule = pack.electrical_symbol_rules[0]
    assert rule.drawing_legend_identity == "单输入输出控制模块 (C1)"
    assert len(rule.ports) == 4
    assert not rule.body_crossing_permitted
    assert not rule.annotation_expected
