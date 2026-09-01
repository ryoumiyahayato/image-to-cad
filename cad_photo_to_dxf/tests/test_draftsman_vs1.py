from __future__ import annotations

from pathlib import Path

import ezdxf
from PIL import Image
import pytest

from app.draftsman_cad_ir import assemble_editable_cad_ir, audit_vs1_cad_ir
from app.draftsman_domain_pack import ElectricalDomainPackV0
from app.draftsman_logical import assemble_logical_table_rules
from app.draftsman_pdf_evidence import (
    DRAFTSMAN_PDF_EVIDENCE_VERSION,
    PdfPathEvidenceSeed,
    PdfPathPaint,
    PdfPathSegment,
    PdfPathSegmentKind,
    materialize_pdf_path_evidence,
)
from app.draftsman_vs1 import (
    DraftsmanVs1Result,
    run_draftsman_vs1,
    write_vs1_preview_dxf,
    write_vs1_preview_png,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
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
EXPECTED_RULES = 19


def _paint() -> PdfPathPaint:
    return PdfPathPaint(
        stroke=True,
        fill_mode=0,
        stroke_width_pt=0.24,
        stroke_rgba=(0, 0, 0, 255),
        fill_rgba=(0, 0, 0, 255),
    )


def _line_seed(
    start: tuple[float, float],
    end: tuple[float, float],
) -> PdfPathEvidenceSeed:
    return PdfPathEvidenceSeed(
        object_transform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        segments=(
            PdfPathSegment(PdfPathSegmentKind.MOVE_TO, start),
            PdfPathSegment(PdfPathSegmentKind.LINE_TO, end),
        ),
        paint=_paint(),
    )


def _synthetic_manifest(*, reverse: bool = False, mutated: bool = False):
    seeds = []
    for index in range(5):
        y_value = 10.0 + index * 10.0
        seeds.extend(
            (
                _line_seed((10.0, y_value), (50.0, y_value)),
                _line_seed(
                    (50.0, y_value),
                    (90.0 + (1.0 if mutated and index == 2 else 0.0), y_value),
                ),
            )
        )
    if reverse:
        seeds.reverse()
    return materialize_pdf_path_evidence(
        source_document_id="synthetic-directory",
        source_page=1,
        source_sha256="a" * 64,
        page_size_pt=(100.0, 100.0),
        seeds=seeds,
    )


@pytest.fixture(scope="module")
def golden_replays() -> tuple[DraftsmanVs1Result, DraftsmanVs1Result]:
    return tuple(  # type: ignore[return-value]
        run_draftsman_vs1(
            GOLDEN_PDF,
            source_document_id=SOURCE_DOCUMENT_ID,
            page_number=1,
            expected_logical_entity_count=EXPECTED_RULES,
        )
        for _ in range(2)
    )


def test_native_pdf_path_extraction_uses_authoritative_vector_source(
    golden_replays: tuple[DraftsmanVs1Result, DraftsmanVs1Result],
) -> None:
    evidence = golden_replays[0].evidence
    assert evidence.schema_version == DRAFTSMAN_PDF_EVIDENCE_VERSION
    assert evidence.source_sha256 == GOLDEN_SHA256
    assert evidence.source_page == 1
    assert evidence.page_size_pt == (652.0, 907.0)
    assert evidence.native_path_count == 2481


def test_evidence_identity_is_order_independent_and_replay_stable() -> None:
    forward = _synthetic_manifest()
    reverse = _synthetic_manifest(reverse=True)
    assert forward.manifest_id == reverse.manifest_id
    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert [item.stable_evidence_id for item in forward.paths] == [
        item.stable_evidence_id for item in reverse.paths
    ]


def test_real_source_or_geometry_mutation_changes_evidence_identity() -> None:
    original = _synthetic_manifest()
    geometry_changed = _synthetic_manifest(mutated=True)
    source_changed = materialize_pdf_path_evidence(
        source_document_id=original.source_document_id,
        source_page=original.source_page,
        source_sha256="b" * 64,
        page_size_pt=original.page_size_pt,
        seeds=(_line_seed((10.0, 10.0), (90.0, 10.0)),),
    )
    assert original.manifest_id != geometry_changed.manifest_id
    assert original.paths[0].stable_evidence_id != source_changed.paths[0].stable_evidence_id


def test_multiple_pdf_evidence_fragments_form_one_logical_rule() -> None:
    evidence = _synthetic_manifest()
    logical = assemble_logical_table_rules(evidence, ElectricalDomainPackV0.create())
    assert len(logical.table_rules) == 5
    assert logical.target_evidence_fragment_count == 10
    assert all(len(rule.source_fragment_ids) == 2 for rule in logical.table_rules)
    assert all(rule.unsupported_length == 0.0 for rule in logical.table_rules)
    assert all(rule.start[0] == 10.0 and rule.end[0] == 90.0 for rule in logical.table_rules)


def test_one_logical_table_rule_becomes_one_editable_cad_ir_line() -> None:
    evidence = _synthetic_manifest()
    logical = assemble_logical_table_rules(evidence, ElectricalDomainPackV0.create())
    cad_ir = assemble_editable_cad_ir(logical)
    assert len(cad_ir.lines) == len(logical.table_rules)
    assert {line.logical_entity_id for line in cad_ir.lines} == {
        rule.logical_entity_id for rule in logical.table_rules
    }
    by_logical = {rule.logical_entity_id: rule for rule in logical.table_rules}
    for line in cad_ir.lines:
        rule = by_logical[line.logical_entity_id]
        assert line.start == rule.start
        assert line.end == rule.end
        assert line.provenance_ref == rule.provenance_id


def test_golden_produces_exact_logical_and_editable_counts(
    golden_replays: tuple[DraftsmanVs1Result, DraftsmanVs1Result],
) -> None:
    result = golden_replays[0]
    assert result.logical.target_evidence_fragment_count == EXPECTED_RULES
    assert len(result.logical.table_rules) == EXPECTED_RULES
    assert len(result.cad_ir.lines) == EXPECTED_RULES
    assert result.quality.logical_entity_count == EXPECTED_RULES
    assert result.quality.cad_ir_line_count == EXPECTED_RULES
    assert result.quality.final_entities_per_logical_rule == 1.0


def test_golden_has_no_unsupported_or_unnecessary_output(
    golden_replays: tuple[DraftsmanVs1Result, DraftsmanVs1Result],
) -> None:
    quality = golden_replays[0].quality
    assert quality.unnecessary_fragments == 0
    assert quality.unsupported_geometry == 0
    assert quality.missing_logical_entities == 0
    assert quality.extra_logical_entities == 0
    assert quality.passed


def test_quality_audit_detects_missing_expected_logical_rules() -> None:
    evidence = _synthetic_manifest()
    logical = assemble_logical_table_rules(evidence, ElectricalDomainPackV0.create())
    cad_ir = assemble_editable_cad_ir(logical)
    quality = audit_vs1_cad_ir(
        logical,
        cad_ir,
        expected_logical_entity_count=6,
    )
    assert quality.missing_logical_entities == 1
    assert not quality.passed


def test_golden_replay_is_deterministic(
    golden_replays: tuple[DraftsmanVs1Result, DraftsmanVs1Result],
) -> None:
    first, replay = golden_replays
    assert first.replay_identity() == replay.replay_identity()
    assert first.evidence.canonical_bytes() == replay.evidence.canonical_bytes()
    assert first.logical.canonical_bytes() == replay.logical.canonical_bytes()
    assert first.cad_ir.canonical_bytes() == replay.cad_ir.canonical_bytes()


def test_core_logic_contains_no_golden_fixture_or_expected_geometry() -> None:
    paths = (
        PROJECT_ROOT / "app" / "draftsman_pdf_evidence.py",
        PROJECT_ROOT / "app" / "draftsman_domain_pack.py",
        PROJECT_ROOT / "app" / "draftsman_logical.py",
        PROJECT_ROOT / "app" / "draftsman_cad_ir.py",
        PROJECT_ROOT / "app" / "draftsman_vs1.py",
    )
    forbidden = (
        "warehouse-electrical-vector.pdf",
        "warehouse-index-page-001-600dpi",
        GOLDEN_SHA256,
        "622.32",
        "594.96",
        "214.20",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert all(value not in source for value in forbidden)


def test_preview_contains_only_one_line_per_cad_ir_entity(
    tmp_path: Path,
    golden_replays: tuple[DraftsmanVs1Result, DraftsmanVs1Result],
) -> None:
    result = golden_replays[0]
    dxf_path = write_vs1_preview_dxf(tmp_path / "preview.dxf", result.cad_ir)
    png_path = write_vs1_preview_png(tmp_path / "preview.png", result.cad_ir)
    document = ezdxf.readfile(dxf_path)
    assert len(document.modelspace()) == EXPECTED_RULES
    assert {entity.dxftype() for entity in document.modelspace()} == {"LINE"}
    assert {entity.dxf.layer for entity in document.modelspace()} == {"TABLE_RULE"}
    with Image.open(png_path) as preview:
        assert preview.width > 0
        assert preview.height > 0
        assert preview.getbbox() is not None


def test_vs1_is_shadow_only_and_production_does_not_consume_it() -> None:
    production_modules = (
        PROJECT_ROOT / "app" / "optimized_trace.py",
        PROJECT_ROOT / "app" / "image_loader.py",
        PROJECT_ROOT / "app" / "trace_dxf_entities.py",
        PROJECT_ROOT / "app" / "document_export.py",
    )
    forbidden_imports = (
        "draftsman_pdf_evidence",
        "draftsman_domain_pack",
        "draftsman_logical",
        "draftsman_cad_ir",
        "draftsman_vs1",
    )
    production_source = "\n".join(
        path.read_text(encoding="utf-8") for path in production_modules
    )
    assert all(name not in production_source for name in forbidden_imports)
