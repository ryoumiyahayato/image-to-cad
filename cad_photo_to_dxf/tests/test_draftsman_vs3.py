from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from app.draftsman_cad_ir import (
    EditableCadElectricalLine,
    EditableCadElectricalSymbol,
)
from app.draftsman_domain_pack import (
    ElectricalDomainPackV0,
    ElectricalSymbolRule,
)
from app.draftsman_electrical import (
    LogicalElectricalConnection,
    LogicalElectricalSymbol,
)
from app.draftsman_raster_evidence import (
    DRAFTSMAN_RASTER_EVIDENCE_VERSION,
    RasterGlyphEvidence,
)
from app.draftsman_vs3 import (
    DraftsmanVs3Result,
    run_draftsman_vs3,
    write_vs3_preview_dxf,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_RASTER = (
    PROJECT_ROOT / "tests" / "real_regression" / "assets" / "environment-page-003.png"
)
GOLDEN_SHA256 = "47a7d9fc4062cfa556e2e4a1ea62124342416c9b2f27d0c42a691f76d8ad83cc"
SOURCE_DOCUMENT_ID = "environment-plan-page-003-150dpi"
EXPECTED_INLINE_CENTERS = ((1168, 514), (1278, 516), (1386, 512), (1498, 514), (1608, 514))


@pytest.fixture(scope="module")
def golden_replays() -> tuple[DraftsmanVs3Result, DraftsmanVs3Result]:
    return tuple(  # type: ignore[return-value]
        run_draftsman_vs3(
            GOLDEN_RASTER,
            source_document_id=SOURCE_DOCUMENT_ID,
            source_page=3,
        )
        for _ in range(2)
    )


def test_raster_frontend_uses_authoritative_150_dpi_source(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    evidence = golden_replays[0].evidence
    assert evidence.schema_version == DRAFTSMAN_RASTER_EVIDENCE_VERSION
    assert evidence.source_sha256 == GOLDEN_SHA256
    assert evidence.source_page == 3
    assert evidence.image_size_px == (2478, 1752)
    assert len(evidence.primitives) == 413
    assert len(evidence.candidates) == 55
    assert evidence.transform_id.startswith("raster-image-to-cad-transform:")


def test_evidence_is_high_recall_and_has_no_electrical_identity(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    result = golden_replays[0]
    assert len(result.evidence.candidates) > len(result.interpretation.decisions.accepted)
    primitives = result.evidence.primitive_by_id()
    assert all(
        isinstance(primitives[item.glyph_evidence_id], RasterGlyphEvidence)
        for item in result.evidence.candidates
    )
    assert all(
        not hasattr(item, "canonical_domain_identity")
        for item in result.evidence.candidates
    )


def test_verified_smoke_detector_recall_and_domain_interpretation(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    result = golden_replays[0]
    candidate_by_id = {
        item.stable_candidate_id: item for item in result.evidence.candidates
    }
    accepted = sorted(
        result.interpretation.decisions.accepted,
        key=lambda item: candidate_by_id[item.candidate_id].source_center_px[0],
    )
    assert tuple(
        candidate_by_id[item.candidate_id].source_center_px for item in accepted
    ) == EXPECTED_INLINE_CENTERS
    assert len(accepted) == 5
    assert {
        item.canonical_domain_identity for item in accepted
    } == {"ELECTRICAL.FIRE_ALARM.SMOKE_DETECTOR"}
    assert {item.inventory_canonical_identity for item in accepted} == {"感烟"}
    assert all(item.frontend_kind == "RASTER_IMAGE" for item in accepted)
    assert all(
        "REPEATED_ALIGNED_FAMILY_MATCH" in item.reasons for item in accepted
    )


def test_fixed_domain_pack_contract_is_shared_across_frontends() -> None:
    pack = ElectricalDomainPackV0.create()
    vector_rule = next(
        item for item in pack.electrical_symbol_rules if item.recognition_signature
    )
    raster_rule = next(
        item for item in pack.electrical_symbol_rules if item.raster_recognition_signature
    )
    assert isinstance(vector_rule, ElectricalSymbolRule)
    assert isinstance(raster_rule, ElectricalSymbolRule)
    assert vector_rule.rule_id != raster_rule.rule_id
    assert vector_rule.ports[0].__class__ is raster_rule.ports[0].__class__
    assert not raster_rule.body_crossing_permitted
    assert raster_rule.drawing_legend_identity == "tags 140-177: 感烟"


def test_ports_topology_and_meaningful_symbol_gaps_are_preserved(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    result = golden_replays[0]
    for hypothesis in result.interpretation.decisions.accepted:
        assert {item.port_key for item in hypothesis.ports} == {
            "LEFT_ALARM_BUS",
            "RIGHT_ALARM_BUS",
        }
    assert len(result.logical.connections) == 6
    assert all(
        "SYMBOL_BOUNDARY" in connection.gap_causes
        for connection in result.logical.connections
    )
    assert result.quality.missed_expected_ports == 0
    assert result.quality.invalid_port_connections == 0
    assert result.quality.incorrect_line_through_symbol == 0


def test_many_raster_fragments_form_logical_entities_not_fragment_soup(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    result = golden_replays[0]
    assert all(isinstance(item, LogicalElectricalSymbol) for item in result.logical.symbols)
    assert all(
        isinstance(item, LogicalElectricalConnection)
        for item in result.logical.connections
    )
    assert len(result.logical.symbols) == 5
    assert len(result.logical.connections) == 6
    assert len(result.cad_ir.symbols) == 5
    assert len(result.cad_ir.lines) == 6
    assert result.cad_ir.entity_count == 11
    assert all(
        isinstance(item, EditableCadElectricalSymbol) for item in result.cad_ir.symbols
    )
    assert all(isinstance(item, EditableCadElectricalLine) for item in result.cad_ir.lines)
    assert result.quality.unnecessary_fragments == 0


def test_detection_break_becomes_one_reconstructed_cad_ir_line(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    result = golden_replays[0]
    reconstructed = [
        item for item in result.logical.connections if item.state == "RECONSTRUCTED"
    ]
    assert len(reconstructed) == 1
    line = reconstructed[0]
    assert line.observed_evidence_coverage == pytest.approx(0.88172)
    assert line.inferred_length == pytest.approx(11.0)
    assert "DETECTION_BREAK" in line.gap_causes
    assert sum(
        item.logical_line_id == line.logical_line_id for item in result.cad_ir.lines
    ) == 1
    assert result.quality.reconstructed_final_entity_count == 1


def test_no_unsupported_geometry_or_domain_rule_violations(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    quality = golden_replays[0].quality
    assert quality.raster_evidence_primitives == 16
    assert quality.unsupported_geometry == 0
    assert quality.domain_rule_violations == 0
    assert quality.failure_layer == "NONE"
    assert quality.passed


def test_raster_evidence_and_full_slice_replay_are_deterministic(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
) -> None:
    first, second = golden_replays
    assert first.replay_identity() == second.replay_identity()
    assert first.evidence.canonical_bytes() == second.evidence.canonical_bytes()
    assert (
        first.interpretation.decisions.canonical_bytes()
        == second.interpretation.decisions.canonical_bytes()
    )
    assert first.logical.canonical_bytes() == second.logical.canonical_bytes()
    assert first.cad_ir.canonical_bytes() == second.cad_ir.canonical_bytes()


def test_no_golden_filename_page_or_coordinate_hardcoding_in_runtime() -> None:
    app_dir = PROJECT_ROOT / "app"
    sources = "\n".join(
        (app_dir / filename).read_text(encoding="utf-8")
        for filename in (
            "draftsman_raster_evidence.py",
            "draftsman_raster_electrical.py",
            "draftsman_vs3.py",
        )
    )
    assert "environment-page-003.png" not in sources
    assert GOLDEN_SHA256 not in sources
    assert "1168, 514" not in sources
    assert "source_page == 3" not in sources


def test_preview_contains_editable_symbols_and_one_line_per_logical_line(
    golden_replays: tuple[DraftsmanVs3Result, DraftsmanVs3Result],
    tmp_path: Path,
) -> None:
    target = write_vs3_preview_dxf(tmp_path / "vs3-preview.dxf", golden_replays[0].cad_ir)
    document = ezdxf.readfile(target)
    entities = list(document.modelspace())
    assert [item.dxftype() for item in entities].count("INSERT") == 5
    assert [item.dxftype() for item in entities].count("LINE") == 6
    assert len(entities) == 11


def test_shadow_raster_modules_are_not_imported_by_production() -> None:
    app_dir = PROJECT_ROOT / "app"
    production_entrypoints = (
        "pipeline.py",
        "pipeline_service.py",
        "trace_single_export.py",
        "dxf_exporter.py",
    )
    shadow_names = (
        "draftsman_raster_evidence",
        "draftsman_raster_electrical",
        "draftsman_vs3",
    )
    for filename in production_entrypoints:
        source = (app_dir / filename).read_text(encoding="utf-8")
        assert not any(name in source for name in shadow_names)
