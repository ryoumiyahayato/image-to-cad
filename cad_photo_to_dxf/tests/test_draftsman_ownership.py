from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import ezdxf
import numpy as np

from app.auxiliary_recognition import SymbolCandidate, TextCandidate
from app.draftsman_adapter import (
    adapt_legacy_final_structure,
    load_v2_restoration_records,
)
from app.draftsman_candidate import DraftsmanCandidateManifest
from app.draftsman_candidate_adapter import (
    adapt_candidate_outputs,
    current_candidate_producers,
)
from app.draftsman_contract import EvidenceState, SourcePageRef, TransformRef
from app.draftsman_ownership import (
    DRAFTSMAN_OWNERSHIP_VERSION,
    DiscrepancyCategory,
    DraftsmanOwnershipManifest,
    OwnershipDecisionState,
    OwnershipKind,
    arbitrate_candidate_ownership,
    build_ownership_discrepancy_report,
    ownership_manifest_sha256,
)
from app.final_structure import build_final_structure
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.signature_overlay import SignatureRegion, SignatureVisualEvidence
from app.structural_roi import StructuralRoi
from app.text_protection import TEXT_MASK_RESTORATION
from app.trace_single_export import export_final_structure_dxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from v2_canonical_structure import canonical_json_bytes, canonical_payload  # noqa: E402


def _page() -> SourcePageRef:
    return SourcePageRef("ownership-document", 1, "d" * 64, (240, 120))


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


def _producers(*, volatile: object | None = None):
    return current_candidate_producers(
        line_config={"configuration": "test"},
        text_config={"configuration": "test", "bbox_role": "source-evidence-only"},
        structural_roi_config={"configuration": "test"},
        include_legacy_auxiliary=True,
        diagnostic_metadata=volatile,
    )


def _manifest(
    *,
    lines: tuple[LineSegment, ...] = (),
    texts: tuple[TextCandidate, ...] = (),
    logos: tuple[LogoRegion, ...] = (),
    signatures: tuple[SignatureRegion, ...] = (),
    rois: tuple[StructuralRoi, ...] = (),
    symbols: tuple[SymbolCandidate, ...] = (),
    volatile: object | None = None,
) -> DraftsmanCandidateManifest:
    return adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(volatile=volatile),
        line_candidates=lines,
        text_candidates=texts,
        logo_candidates=logos,
        signature_candidates=signatures,
        structural_rois=rois,
        symbol_candidates=symbols,
    )


def _selected_owner(group) -> OwnershipKind | None:
    return next(
        (
            hypothesis.ownership_kind
            for hypothesis in group.hypotheses
            if hypothesis.hypothesis_id == group.selected_hypothesis_id
        ),
        None,
    )


def _visual(confidence: float) -> SignatureVisualEvidence:
    return SignatureVisualEvidence(
        source_component_count=2,
        source_pixel_count=40,
        density=0.5,
        continuity=0.8,
        directional_complexity=10,
        positive_diagonal_span=8.0,
        negative_diagonal_span=7.0,
        bidirectional_diagonal_support=True,
        perimeter_per_pixel=0.8,
        convex_solidity=0.4,
        confidence=confidence,
    )


def test_contract_version_and_clear_ownership_resolve() -> None:
    manifest = _manifest(
        lines=(LineSegment(5.0, 10.0, 100.0, 10.0),),
        texts=(
            TextCandidate(
                "A-101",
                (150, 70, 30, 12),
                0.96,
                "text_candidate",
                quad=((150.0, 70.0), (180.0, 70.0), (180.0, 82.0), (150.0, 82.0)),
                source="unit-test",
            ),
        ),
    )
    ownership = arbitrate_candidate_ownership(manifest)
    assert DRAFTSMAN_OWNERSHIP_VERSION == "draftsman-ownership-v1"
    assert isinstance(ownership, DraftsmanOwnershipManifest)
    assert len(ownership.groups) == 2
    assert ownership.resolved_count == 2
    assert {_selected_owner(group) for group in ownership.groups} == {
        OwnershipKind.STRUCTURE,
        OwnershipKind.TEXT,
    }
    assert all(not group.review_required for group in ownership.groups)


def test_overlapping_line_and_text_remain_provisional_without_deletion() -> None:
    line = LineSegment(10.0, 30.0, 100.0, 30.0)
    text = TextCandidate(
        "LEVEL",
        (20, 24, 50, 14),
        0.94,
        "text_candidate",
        quad=((20.0, 24.0), (70.0, 24.0), (70.0, 38.0), (20.0, 38.0)),
        source="unit-test",
    )
    manifest = _manifest(lines=(line,), texts=(text,))
    before = manifest.canonical_bytes()
    ownership = arbitrate_candidate_ownership(manifest)
    assert manifest.canonical_bytes() == before
    assert len(ownership.groups) == 1
    group = ownership.groups[0]
    assert group.decision_state is OwnershipDecisionState.PROVISIONAL
    assert group.review_required
    assert group.review_reason == "OWNERSHIP_COMPETITION"
    assert group.review_item_id is not None
    assert len(group.candidate_ids) == 2
    assert ownership.considered_candidate_ids == tuple(
        sorted(item.stable_candidate_id for item in manifest.candidates)
    )
    assert "COMPETING_OWNER_CLAIMS" in group.reasons


def test_low_confidence_candidate_remains_unresolved() -> None:
    manifest = _manifest(
        symbols=(SymbolCandidate("unknown_mark", (20, 20, 8, 8), 0.12),),
    )
    group = arbitrate_candidate_ownership(manifest).groups[0]
    assert group.decision_state is OwnershipDecisionState.UNRESOLVED
    assert group.selected_hypothesis_id is None
    assert group.review_required
    assert group.review_reason == "OWNERSHIP_UNRESOLVED"
    assert group.review_item_id is not None


def test_equal_logo_signature_claims_do_not_use_arbitrary_tie_break() -> None:
    mask = np.full((10, 20), 255, dtype=np.uint8)
    logo = LogoRegion(
        bbox=(30, 30, 20, 10),
        mask=mask,
        structural_score=0.85,
        hole_count=1,
        contour_count=2,
    )
    signature = SignatureRegion((30, 30, 20, 10), mask.copy(), _visual(0.85))
    group = arbitrate_candidate_ownership(
        _manifest(logos=(logo,), signatures=(signature,))
    ).groups[0]
    assert group.decision_state is OwnershipDecisionState.PROVISIONAL
    assert group.selected_hypothesis_id is None
    assert {item.score for item in group.hypotheses} == {0.85}


def test_ambiguous_short_stroke_creates_explicit_competing_hypothesis() -> None:
    line = LineSegment(
        10.0,
        10.0,
        14.0,
        10.0,
        width=2.0,
        confidence=0.55,
        classification_confidence=0.55,
    )
    group = arbitrate_candidate_ownership(_manifest(lines=(line,))).groups[0]
    assert group.decision_state is OwnershipDecisionState.PROVISIONAL
    assert {item.ownership_kind for item in group.hypotheses} == {
        OwnershipKind.STRUCTURE,
        OwnershipKind.GRAPHIC,
    }
    assert "AMBIGUOUS_SHORT_STROKE" in group.reasons


def test_structural_and_table_regions_support_claims_without_owning_them() -> None:
    lines = (
        LineSegment(10.0, 20.0, 110.0, 20.0),
        LineSegment(10.0, 50.0, 110.0, 50.0),
    )
    rois = (
        StructuralRoi(
            "frame-1",
            "frame",
            (5, 10, 115, 50),
            (0,),
            ((10.0, 20.0),),
            0.95,
        ),
        StructuralRoi(
            "table-1",
            "table",
            (5, 10, 115, 50),
            (1,),
            ((10.0, 50.0),),
            0.95,
        ),
    )
    text = TextCandidate("C1", (30, 42, 20, 12), 0.9, "text_candidate")
    ownership = arbitrate_candidate_ownership(
        _manifest(lines=lines, texts=(text,), rois=rois)
    )
    assert len(ownership.considered_candidate_ids) == 5
    context_groups = [
        group
        for group in ownership.groups
        if _selected_owner(group) is OwnershipKind.LAYOUT_CONTEXT
    ]
    assert len(context_groups) == 2
    assert all(len(group.candidate_ids) == 1 for group in context_groups)
    assert any(
        "STRUCTURAL_ROI_SUPPORT" in group.reasons
        for group in ownership.groups
    )
    assert any(
        "TABLE_REGION_TEXT_SUPPORT" in group.reasons
        for group in ownership.groups
    )


def test_duplicate_competing_candidates_are_preserved() -> None:
    first = TextCandidate("O", (20, 20, 12, 12), 0.8, "text_candidate")
    second = TextCandidate("0", (20, 20, 12, 12), 0.78, "text_candidate")
    manifest = _manifest(texts=(first, second))
    ownership = arbitrate_candidate_ownership(manifest)
    assert len(manifest.candidates) == 2
    assert len(ownership.considered_candidate_ids) == 2
    assert len(ownership.groups) == 1
    assert len(ownership.groups[0].candidate_ids) == 2
    assert "DUPLICATE_OR_COMPETING_CANDIDATES" in ownership.groups[0].reasons


def test_arbitration_is_deterministic_and_order_independent() -> None:
    line = LineSegment(10.0, 30.0, 100.0, 30.0)
    text = TextCandidate("LEVEL", (20, 24, 50, 14), 0.94, "text_candidate")
    forward_manifest = _manifest(lines=(line,), texts=(text,))
    reverse_manifest = replace(
        forward_manifest,
        candidates=tuple(reversed(forward_manifest.candidates)),
        relationships=tuple(reversed(forward_manifest.relationships)),
    )
    forward = arbitrate_candidate_ownership(forward_manifest)
    reverse = arbitrate_candidate_ownership(reverse_manifest)
    replay = arbitrate_candidate_ownership(forward_manifest)
    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert forward.canonical_bytes() == replay.canonical_bytes()
    assert ownership_manifest_sha256(forward) == ownership_manifest_sha256(replay)
    assert [item.ownership_group_id for item in forward.groups] == [
        item.ownership_group_id for item in reverse.groups
    ]


def test_relevant_evidence_mutation_changes_decision() -> None:
    text = TextCandidate("LEVEL", (20, 24, 50, 14), 0.65, "text_candidate")
    weak = LineSegment(
        10.0,
        30.0,
        100.0,
        30.0,
        confidence=0.3,
        classification_confidence=0.3,
    )
    strong = replace(weak, confidence=1.0, classification_confidence=1.0)
    weak_group = arbitrate_candidate_ownership(
        _manifest(lines=(weak,), texts=(text,))
    ).groups[0]
    strong_group = arbitrate_candidate_ownership(
        _manifest(lines=(strong,), texts=(text,))
    ).groups[0]
    assert weak_group.decision_state is OwnershipDecisionState.PROVISIONAL
    assert strong_group.decision_state is OwnershipDecisionState.RESOLVED
    assert _selected_owner(strong_group) is OwnershipKind.STRUCTURE


def test_volatile_metadata_does_not_change_identity_or_decision() -> None:
    line = LineSegment(10.0, 20.0, 100.0, 20.0)
    first_manifest = _manifest(lines=(line,), volatile={"timestamp": "first", "guid": "A"})
    replay_manifest = _manifest(lines=(line,), volatile={"timestamp": "later", "guid": "B"})
    first = arbitrate_candidate_ownership(
        first_manifest,
        diagnostic_metadata={"run_timestamp": "first"},
    )
    replay = arbitrate_candidate_ownership(
        replay_manifest,
        diagnostic_metadata={"run_timestamp": "later"},
    )
    assert first.manifest_id == replay.manifest_id
    assert [item.ownership_group_id for item in first.groups] == [
        item.ownership_group_id for item in replay.groups
    ]
    assert [item.decision_identity_payload() for item in first.groups] == [
        item.decision_identity_payload() for item in replay.groups
    ]


def test_discrepancy_report_is_deterministic_and_does_not_treat_production_as_truth() -> None:
    manifest = _manifest(
        lines=(LineSegment(5.0, 10.0, 100.0, 10.0),),
        texts=(TextCandidate("A", (150, 70, 20, 12), 0.95, "text_candidate"),),
    )
    ownership = arbitrate_candidate_ownership(manifest)
    route_by_kind = {
        item.stable_candidate_id: (
            "STRUCTURE" if item.candidate_kind.value == "LINE_SEGMENT" else "REMOVED"
        )
        for item in manifest.candidates
    }
    report = build_ownership_discrepancy_report(ownership, route_by_kind)
    replay = build_ownership_discrepancy_report(ownership, dict(reversed(tuple(route_by_kind.items()))))
    assert report.canonical_bytes() == replay.canonical_bytes()
    assert report.discrepancy_count == 1
    assert report.category_counts[DiscrepancyCategory.SAME.value] == 1
    assert (
        report.category_counts[
            DiscrepancyCategory.PRODUCTION_DESTRUCTIVE_CONFLICT.value
        ]
        == 1
    )


def test_provisional_discrepancy_is_reported_explicitly() -> None:
    manifest = _manifest(
        lines=(LineSegment(10.0, 30.0, 100.0, 30.0),),
        texts=(TextCandidate("LEVEL", (20, 24, 50, 14), 0.94, "text_candidate"),),
    )
    ownership = arbitrate_candidate_ownership(manifest)
    report = build_ownership_discrepancy_report(
        ownership,
        {item.stable_candidate_id: "TEXT" for item in manifest.candidates},
    )
    assert report.records[0].category is DiscrepancyCategory.SHADOW_PROVISIONAL


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


def test_rc3_reconstructed_entities_are_unchanged_by_ownership_shadow() -> None:
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
    arbitrate_candidate_ownership(candidate_manifest)
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
    assert sum(
        TEXT_MASK_RESTORATION in item.payload.detector_history
        for item in candidate_manifest.candidates
        if hasattr(item.payload, "detector_history")
    ) == 91


def _dxf_semantics(path: Path) -> list[dict[str, object]]:
    document = ezdxf.readfile(path)
    return sorted(
        (canonical_payload(entity) for entity in document.modelspace()),
        key=canonical_json_bytes,
    )


def test_ownership_shadow_has_zero_production_semantic_delta(tmp_path: Path) -> None:
    line = LineSegment(5.0, 6.0, 80.0, 6.0)
    text = TextCandidate(
        "A-101",
        (20, 20, 40, 12),
        0.99,
        "text_candidate",
        source="unit-test",
    )
    binary = np.full((120, 240), 255, dtype=np.uint8)
    structure = build_final_structure(
        source_size_px=(240, 120),
        contour_binary=binary,
        contours=(),
        straight_lines=(line,),
        texts=(text,),
        preview_binary=binary,
    )
    before = tmp_path / "before.dxf"
    after = tmp_path / "after.dxf"
    before_result = export_final_structure_dxf(structure, before)
    ownership = arbitrate_candidate_ownership(
        _manifest(lines=(line,), texts=(text,))
    )
    after_result = export_final_structure_dxf(structure, after)
    assert len(ownership.considered_candidate_ids) == 2
    assert before_result.structure_id == after_result.structure_id
    assert _dxf_semantics(before) == _dxf_semantics(after)


def test_production_modules_do_not_import_ownership_shadow_layer() -> None:
    consumers = []
    for path in (PROJECT_ROOT / "app").glob("*.py"):
        if path.name.startswith("draftsman_"):
            continue
        source = path.read_text(encoding="utf-8")
        if "draftsman_ownership" in source:
            consumers.append(path.name)
    assert consumers == []
