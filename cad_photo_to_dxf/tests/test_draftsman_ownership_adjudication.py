from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.draftsman_adapter import (
    adapt_legacy_final_structure,
    load_v2_restoration_records,
)
from app.draftsman_candidate import CandidateKind, DraftsmanCandidateManifest
from app.draftsman_candidate_adapter import (
    adapt_candidate_outputs,
    current_candidate_producers,
)
from app.draftsman_contract import EvidenceState, SourcePageRef, TransformRef
from app.draftsman_ownership import arbitrate_candidate_ownership
from app.draftsman_ownership_adjudication import (
    DRAFTSMAN_OWNERSHIP_RELATION_VERSION,
    DiscrepancyAdjudicationCategory,
    OwnershipSemanticRelation,
    SourceEvidenceRelation,
    build_discrepancy_adjudication_ledger,
    discrepancy_ledger_sha256,
)
from app.final_structure import build_final_structure
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.signature_overlay import SignatureRegion, SignatureVisualEvidence
from app.structural_roi import StructuralRoi
from app.trace_single_export import export_final_structure_dxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from v2_canonical_structure import canonical_json_bytes, canonical_payload  # noqa: E402


def _page() -> SourcePageRef:
    return SourcePageRef("relation-document", 1, "e" * 64, (240, 120))


def _transform() -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload={
            "origin": [0.0, 120.0],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _producers():
    return current_candidate_producers(
        line_config={"configuration": "m2-s2-test"},
        text_config={
            "configuration": "m2-s2-test",
            "bbox_role": "source-evidence-only",
        },
        structural_roi_config={"configuration": "m2-s2-test"},
    )


def _manifest(
    *,
    lines: tuple[LineSegment, ...] = (),
    texts: tuple[TextCandidate, ...] = (),
    logos: tuple[LogoRegion, ...] = (),
    signatures: tuple[SignatureRegion, ...] = (),
    rois: tuple[StructuralRoi, ...] = (),
) -> DraftsmanCandidateManifest:
    return adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=lines,
        text_candidates=texts,
        logo_candidates=logos,
        signature_candidates=signatures,
        structural_rois=rois,
    )


def _route_by_kind(
    manifest: DraftsmanCandidateManifest,
    *,
    removed_kind: CandidateKind,
    removed_route: str = "REMOVED",
) -> dict[str, str]:
    owners = {
        CandidateKind.LINE_SEGMENT: "STRUCTURE",
        CandidateKind.OCR_TEXT: "TEXT",
        CandidateKind.LOGO: "LOGO",
        CandidateKind.SIGNATURE: "SIGNATURE",
        CandidateKind.STRUCTURAL_ROI: "LAYOUT_CONTEXT",
        CandidateKind.TABLE_REGION: "LAYOUT_CONTEXT",
        CandidateKind.CIRCLE: "SYMBOL",
        CandidateKind.SYMBOL: "SYMBOL",
    }
    return {
        item.stable_candidate_id: (
            removed_route
            if item.candidate_kind is removed_kind
            else owners[item.candidate_kind]
        )
        for item in manifest.candidates
    }


def _ledger(
    manifest: DraftsmanCandidateManifest,
    routes: dict[str, str],
):
    ownership = arbitrate_candidate_ownership(manifest)
    return build_discrepancy_adjudication_ledger(
        candidates=manifest,
        ownership=ownership,
        production_routes=routes,
    )


def test_contract_is_versioned_and_count_unit_is_group() -> None:
    manifest = _manifest(lines=(LineSegment(10.0, 20.0, 100.0, 20.0),))
    ledger = _ledger(
        manifest,
        {manifest.candidates[0].stable_candidate_id: "REMOVED"},
    )
    assert DRAFTSMAN_OWNERSHIP_RELATION_VERSION == (
        "draftsman-ownership-relation-v1"
    )
    assert ledger.count_unit == "ownership-group"
    assert ledger.original_discrepancy_count == 1
    assert len(ledger.entries) == 1
    assert ledger.to_dict()["count_unit"] == "ownership-group"


def test_mutually_exclusive_text_and_glyph_stroke_is_legitimate_exclusive() -> None:
    line = LineSegment(
        35.0,
        30.0,
        43.0,
        30.0,
        confidence=0.2,
        classification_confidence=0.2,
    )
    text = TextCandidate(
        "E",
        (30, 24, 20, 14),
        1.0,
        "text_candidate",
        quad=((30.0, 24.0), (50.0, 24.0), (50.0, 38.0), (30.0, 38.0)),
    )
    manifest = _manifest(lines=(line,), texts=(text,))
    ledger = _ledger(
        manifest,
        _route_by_kind(manifest, removed_kind=CandidateKind.LINE_SEGMENT),
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.EXCLUSIVE
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.LEGITIMATE_EXCLUSIVE
    )
    assert entry.source_evidence_relation is (
        SourceEvidenceRelation.OVERLAPPING_FOOTPRINTS
    )


def test_isolated_short_line_without_lineage_stays_provisional() -> None:
    line = LineSegment(30.0, 30.0, 34.0, 30.0, confidence=1.0)
    manifest = _manifest(lines=(line,))
    ledger = _ledger(
        manifest,
        {manifest.candidates[0].stable_candidate_id: "REMOVED"},
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.PROVISIONAL
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.PROVISIONAL
    )
    assert entry.review_required
    assert entry.review_item_id is not None


def test_continuous_structure_through_text_is_occluded_background() -> None:
    line = LineSegment(5.0, 30.0, 110.0, 30.0)
    text = TextCandidate(
        "LEVEL",
        (35, 24, 40, 14),
        0.5,
        "text_candidate",
    )
    manifest = _manifest(lines=(line,), texts=(text,))
    ledger = _ledger(
        manifest,
        _route_by_kind(manifest, removed_kind=CandidateKind.OCR_TEXT),
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is (
        OwnershipSemanticRelation.OCCLUDED_BACKGROUND
    )
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.OCCLUDED_BACKGROUND
    )
    assert "CONTINUOUS_LINE_EXTENDS_ACROSS_FOREGROUND_REGION" in entry.reasons


def test_table_border_and_cell_text_coexist() -> None:
    line = LineSegment(10.0, 30.0, 110.0, 30.0)
    text = TextCandidate("C1", (35, 24, 20, 14), 0.6, "text_candidate")
    table = StructuralRoi(
        "table-1",
        "table",
        (5, 10, 115, 50),
        (0,),
        ((10.0, 30.0),),
        0.95,
    )
    manifest = _manifest(lines=(line,), texts=(text,), rois=(table,))
    routes = _route_by_kind(manifest, removed_kind=CandidateKind.OCR_TEXT)
    ledger = _ledger(manifest, routes)
    entry = next(
        item
        for item in ledger.entries
        if "TEXT" in item.candidate_interpretations
    )
    assert entry.final_cad_relation is OwnershipSemanticRelation.COEXIST
    assert entry.adjudication_category is DiscrepancyAdjudicationCategory.COEXIST
    assert "TABLE_BORDER_AND_CELL_TEXT_HAVE_DISTINCT_CAD_ROLES" in entry.reasons


def test_logo_covering_continuous_line_is_occluded_background() -> None:
    line = LineSegment(5.0, 30.0, 110.0, 30.0)
    mask = np.full((14, 40), 255, dtype=np.uint8)
    logo = LogoRegion(
        bbox=(35, 24, 40, 14),
        mask=mask,
        structural_score=0.5,
        hole_count=1,
        contour_count=2,
    )
    manifest = _manifest(lines=(line,), logos=(logo,))
    ledger = _ledger(
        manifest,
        _route_by_kind(manifest, removed_kind=CandidateKind.LOGO),
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is (
        OwnershipSemanticRelation.OCCLUDED_BACKGROUND
    )
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.OCCLUDED_BACKGROUND
    )


def test_signature_covering_continuous_line_is_occluded_background() -> None:
    line = LineSegment(5.0, 30.0, 110.0, 30.0)
    mask = np.full((14, 40), 255, dtype=np.uint8)
    visual = SignatureVisualEvidence(
        source_component_count=2,
        source_pixel_count=560,
        density=1.0,
        continuity=0.8,
        directional_complexity=10,
        positive_diagonal_span=8.0,
        negative_diagonal_span=7.0,
        bidirectional_diagonal_support=True,
        perimeter_per_pixel=0.8,
        convex_solidity=0.4,
        confidence=0.5,
    )
    signature = SignatureRegion((35, 24, 40, 14), mask, visual)
    manifest = _manifest(lines=(line,), signatures=(signature,))
    ledger = _ledger(
        manifest,
        _route_by_kind(manifest, removed_kind=CandidateKind.SIGNATURE),
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is (
        OwnershipSemanticRelation.OCCLUDED_BACKGROUND
    )
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.OCCLUDED_BACKGROUND
    )


def test_identical_line_detector_outputs_are_same_entity_not_ownership_loss() -> None:
    line = LineSegment(10.0, 20.0, 100.0, 20.0)
    manifest = _manifest(lines=(line, line))
    line_ids = sorted(item.stable_candidate_id for item in manifest.candidates)
    ledger = _ledger(
        manifest,
        {line_ids[0]: "STRUCTURE", line_ids[1]: "REMOVED"},
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.SAME_ENTITY
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.DUPLICATE_HYPOTHESIS
    )
    assert entry.source_evidence_relation is SourceEvidenceRelation.SHARED_FOOTPRINT


def test_raw_line_fragment_matching_final_line_is_lineage_not_suppression() -> None:
    raw_manifest = _manifest(
        lines=(LineSegment(20.0, 20.0, 80.0, 20.0),),
    )
    final_manifest = _manifest(
        lines=(LineSegment(10.0, 20.0, 100.0, 20.0),),
    )
    ownership = arbitrate_candidate_ownership(raw_manifest)
    ledger = build_discrepancy_adjudication_ledger(
        candidates=raw_manifest,
        ownership=ownership,
        production_routes={
            raw_manifest.candidates[0].stable_candidate_id: "REMOVED"
        },
        final_candidates=final_manifest,
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.SAME_ENTITY
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.DUPLICATE_HYPOTHESIS
    )
    assert entry.related_final_candidate_ids == (
        final_manifest.candidates[0].stable_candidate_id,
    )
    assert ledger.final_candidate_manifest_id == final_manifest.manifest_id


def test_bbox_edge_overlap_coexists_without_forcing_a_winner() -> None:
    line = LineSegment(5.0, 24.0, 110.0, 24.0)
    text = TextCandidate("ROOM", (35, 24, 40, 14), 0.5, "text_candidate")
    manifest = _manifest(lines=(line,), texts=(text,))
    ledger = _ledger(
        manifest,
        _route_by_kind(manifest, removed_kind=CandidateKind.OCR_TEXT),
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.COEXIST
    assert entry.adjudication_category is DiscrepancyAdjudicationCategory.COEXIST
    assert entry.review_required is False


def test_explicit_high_confidence_suppression_is_true_destructive() -> None:
    line = LineSegment(5.0, 20.0, 110.0, 20.0)
    manifest = _manifest(lines=(line,))
    ledger = _ledger(
        manifest,
        {manifest.candidates[0].stable_candidate_id: "MASKED_OUT"},
    )
    entry = ledger.entries[0]
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.TRUE_DESTRUCTIVE_SUPPRESSION
    )
    assert entry.review_required
    assert entry.review_reason == "TRUE_DESTRUCTIVE_SUPPRESSION"


def test_unobserved_lineage_is_unresolved_not_guessed() -> None:
    line = LineSegment(5.0, 20.0, 110.0, 20.0)
    manifest = _manifest(lines=(line,))
    ledger = _ledger(
        manifest,
        {manifest.candidates[0].stable_candidate_id: "UNOBSERVED"},
    )
    entry = ledger.entries[0]
    assert entry.final_cad_relation is OwnershipSemanticRelation.UNRESOLVED
    assert entry.adjudication_category is (
        DiscrepancyAdjudicationCategory.UNRESOLVED
    )
    assert entry.review_required


def test_relation_ledger_is_deterministic_order_independent_and_read_only() -> None:
    line = LineSegment(5.0, 30.0, 110.0, 30.0)
    text = TextCandidate("LEVEL", (35, 24, 40, 14), 0.5, "text_candidate")
    manifest = _manifest(lines=(line,), texts=(text,))
    ownership = arbitrate_candidate_ownership(manifest)
    routes = _route_by_kind(manifest, removed_kind=CandidateKind.OCR_TEXT)
    candidate_before = manifest.canonical_bytes()
    ownership_before = ownership.canonical_bytes()
    first = build_discrepancy_adjudication_ledger(
        candidates=manifest,
        ownership=ownership,
        production_routes=routes,
    )
    reversed_manifest = replace(
        manifest,
        candidates=tuple(reversed(manifest.candidates)),
        relationships=tuple(reversed(manifest.relationships)),
    )
    reversed_ownership = arbitrate_candidate_ownership(reversed_manifest)
    replay = build_discrepancy_adjudication_ledger(
        candidates=reversed_manifest,
        ownership=reversed_ownership,
        production_routes=dict(reversed(tuple(routes.items()))),
    )
    assert first.canonical_bytes() == replay.canonical_bytes()
    assert discrepancy_ledger_sha256(first) == discrepancy_ledger_sha256(replay)
    assert manifest.canonical_bytes() == candidate_before
    assert ownership.canonical_bytes() == ownership_before
    assert sum(len(group.candidate_ids) for group in ownership.groups) == len(
        manifest.candidates
    )


def _structure(lines: tuple[LineSegment, ...], size: tuple[int, int]):
    width, height = size
    binary = np.full((height, width), 255, dtype=np.uint8)
    return build_final_structure(
        source_size_px=size,
        contour_binary=binary,
        contours=(),
        straight_lines=lines,
        texts=(),
        preview_binary=binary,
    )


def _current_v2_page() -> Path | None:
    candidates = (
        WORKSPACE_ROOT
        / "local-artifacts/review/p1-v2-implementation/v2-pages"
        / "environment-plan-page-003-150dpi.json",
        PROJECT_ROOT
        / "validation/baselines/non-destructive-editable-text-v2/pages"
        / "environment-plan-page-003-150dpi.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def test_rc3_91_reconstructed_entities_survive_relation_adjudication() -> None:
    page_path = _current_v2_page()
    if page_path is None:
        return
    page = json.loads(page_path.read_text(encoding="utf-8"))
    records = load_v2_restoration_records(page_path)
    assert len(records) == 91
    lines = []
    for record in records:
        geometry = record["source_geometry"]
        provenance = record["r2_restoration_provenance"]
        assert isinstance(geometry, dict)
        assert isinstance(provenance, dict)
        history = provenance["r2_history"]
        assert isinstance(history, list)
        lines.append(
            LineSegment(
                *[float(value) for value in geometry["coords"]],
                width=float(geometry["width"]),
                history=tuple(str(item) for item in history),
            )
        )
    source = page["source"]
    assert isinstance(source, dict)
    dimensions = source["dimensions"]
    assert isinstance(dimensions, list)
    size = (int(dimensions[0]), int(dimensions[1]))
    transform = TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload=page["transform"],
    )
    structure = _structure(tuple(lines), size)
    before = adapt_legacy_final_structure(
        structure,
        document_id=str(page["page_id"]),
        page_number=int(source["page_number"]),
        source_sha256=str(source["sha256"]),
        transform=transform,
        v2_restoration_records=records,
    )
    candidate_manifest = adapt_candidate_outputs(
        source_page=before.source_page,
        transform=transform,
        producers=_producers(),
        line_candidates=tuple(lines),
    )
    ownership = arbitrate_candidate_ownership(candidate_manifest)
    build_discrepancy_adjudication_ledger(
        candidates=candidate_manifest,
        ownership=ownership,
        production_routes={
            item.stable_candidate_id: "STRUCTURE"
            for item in candidate_manifest.candidates
        },
    )
    after = adapt_legacy_final_structure(
        structure,
        document_id=str(page["page_id"]),
        page_number=int(source["page_number"]),
        source_sha256=str(source["sha256"]),
        transform=transform,
        v2_restoration_records=tuple(reversed(records)),
    )
    assert before.canonical_bytes() == after.canonical_bytes()
    assert sum(
        entity.state is EvidenceState.RECONSTRUCTED for entity in after.entities
    ) == 91


def _dxf_semantics(path: Path) -> list[dict[str, object]]:
    document = ezdxf.readfile(path)
    return sorted(
        (canonical_payload(entity) for entity in document.modelspace()),
        key=canonical_json_bytes,
    )


def test_relation_adjudication_has_zero_production_semantic_delta(tmp_path: Path) -> None:
    line = LineSegment(5.0, 20.0, 110.0, 20.0)
    binary = np.full((120, 240), 255, dtype=np.uint8)
    structure = build_final_structure(
        source_size_px=(240, 120),
        contour_binary=binary,
        contours=(),
        straight_lines=(line,),
        texts=(),
        preview_binary=binary,
    )
    before = tmp_path / "before.dxf"
    after = tmp_path / "after.dxf"
    before_result = export_final_structure_dxf(structure, before)
    manifest = _manifest(lines=(line,))
    ownership = arbitrate_candidate_ownership(manifest)
    ledger = build_discrepancy_adjudication_ledger(
        candidates=manifest,
        ownership=ownership,
        production_routes={manifest.candidates[0].stable_candidate_id: "REMOVED"},
    )
    after_result = export_final_structure_dxf(structure, after)
    assert ledger.original_discrepancy_count == 1
    assert before_result.structure_id == after_result.structure_id
    assert _dxf_semantics(before) == _dxf_semantics(after)


def test_production_modules_do_not_import_relation_shadow_layer() -> None:
    consumers = []
    for path in (PROJECT_ROOT / "app").glob("*.py"):
        if path.name.startswith("draftsman_"):
            continue
        source = path.read_text(encoding="utf-8")
        if "draftsman_ownership_adjudication" in source:
            consumers.append(path.name)
    assert consumers == []
