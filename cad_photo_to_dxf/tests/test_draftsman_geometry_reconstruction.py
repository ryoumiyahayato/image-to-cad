from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.draftsman_candidate import DraftsmanCandidateManifest
from app.draftsman_candidate_adapter import (
    adapt_candidate_outputs,
    current_candidate_producers,
)
from app.draftsman_contract import SourcePageRef, TransformRef
from app.draftsman_geometry_reconstruction import (
    DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION,
    AcceptedLineReconstruction,
    LineGeometry,
    LineReconstructionConfig,
    ReconstructionKind,
    ReconstructionState,
    SourceRasterEvidence,
    build_line_reconstruction_manifest,
    reconstruction_manifest_sha256,
)
from app.draftsman_ownership import arbitrate_candidate_ownership
from app.draftsman_reconstruction_diagnostics import (
    DIAGNOSTIC_LAYERS,
    write_reconstruction_review_dxf,
)
from app.line_detect import LineSegment
from app.structural_roi import StructuralRoi


def _page() -> SourcePageRef:
    return SourcePageRef("m3-document", 1, "e" * 64, (300, 200))


def _transform() -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload={
            "origin": [0.0, 200.0],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _config(**changes: object) -> LineReconstructionConfig:
    return replace(
        LineReconstructionConfig(reference_long_edge_px=300.0),
        **changes,
    )


def _manifest(
    *,
    lines: tuple[LineSegment, ...],
    texts: tuple[TextCandidate, ...] = (),
    rois: tuple[StructuralRoi, ...] = (),
    volatile: object | None = None,
) -> DraftsmanCandidateManifest:
    producers = current_candidate_producers(
        line_config={"detector": "unit"},
        text_config={"detector": "unit", "bbox_role": "source-evidence-only"},
        structural_roi_config={"detector": "unit"},
        include_legacy_auxiliary=True,
        diagnostic_metadata=volatile,
    )
    return adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=producers,
        line_candidates=lines,
        text_candidates=texts,
        structural_rois=rois,
    )


def _run(
    manifest: DraftsmanCandidateManifest,
    *,
    config: LineReconstructionConfig | None = None,
    source: SourceRasterEvidence | None = None,
    accepted: tuple[AcceptedLineReconstruction, ...] = (),
):
    ownership = arbitrate_candidate_ownership(manifest)
    before_candidates = manifest.canonical_bytes()
    before_ownership = ownership.canonical_bytes()
    result = build_line_reconstruction_manifest(
        manifest,
        ownership,
        config=config or _config(),
        source_raster_evidence=source,
        accepted_reconstructions=accepted,
    )
    assert manifest.canonical_bytes() == before_candidates
    assert ownership.canonical_bytes() == before_ownership
    return result


def _clear_lines(gap: float = 8.0) -> tuple[LineSegment, LineSegment]:
    return (
        LineSegment(10.0, 50.0, 50.0, 50.0, confidence=0.96),
        LineSegment(50.0 + gap, 50.0, 100.0, 50.0, confidence=0.96),
    )


def test_contract_and_clear_collinear_gap_reconstruct() -> None:
    result = _run(_manifest(lines=_clear_lines()))
    assert DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION == (
        "draftsman-geometry-reconstruction-v1"
    )
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.reconstruction_kind is ReconstructionKind.COLLINEAR_GAP_BRIDGE
    assert proposal.state is ReconstructionState.RECONSTRUCTED
    assert proposal.proposed_geometry == LineGeometry.create((10, 50), (100, 50), 1)
    assert not proposal.review_required


def test_tiny_detector_break_reconstructs() -> None:
    result = _run(_manifest(lines=_clear_lines(1.0)))
    assert result.metrics.reconstructed == 1


def test_large_unsupported_gap_does_not_auto_reconstruct() -> None:
    lines = (
        LineSegment(10, 50, 30, 50),
        LineSegment(90, 50, 110, 50),
    )
    assert _run(_manifest(lines=lines)).proposals == ()


def test_parallel_offset_lines_are_not_bridged() -> None:
    lines = (
        LineSegment(10, 50, 50, 50),
        LineSegment(58, 62, 100, 62),
    )
    assert _run(_manifest(lines=lines)).proposals == ()


def test_perpendicular_crossing_prevents_automatic_bridge() -> None:
    lines = (*_clear_lines(), LineSegment(54, 35, 54, 65))
    result = _run(_manifest(lines=lines))
    assert result.metrics.crossing_conflict_rejected == 1
    assert result.metrics.reconstructed == 0
    assert result.proposals[0].state is ReconstructionState.PROVISIONAL
    assert {item.conflict_code for item in result.proposals[0].conflicts} == {
        "COMPETING_INTERSECTION"
    }


def test_text_occluded_continuous_line_is_allowed_with_strong_geometry() -> None:
    text = TextCandidate(
        "A",
        (49, 44, 12, 12),
        0.98,
        "text_candidate",
        quad=((49.0, 44.0), (61.0, 44.0), (61.0, 56.0), (49.0, 56.0)),
        source="unit",
    )
    result = _run(_manifest(lines=_clear_lines(), texts=(text,)))
    assert result.metrics.text_structure_overlap_cases == 1
    assert result.metrics.occluded_background_proposals == 1
    assert result.proposals[0].state is ReconstructionState.RECONSTRUCTED


def test_glyph_like_short_strokes_stay_provisional() -> None:
    lines = (
        LineSegment(30, 50, 40, 50),
        LineSegment(42, 50, 52, 50),
    )
    text = TextCandidate("H", (28, 43, 27, 14), 0.95, "text_candidate", source="unit")
    result = _run(_manifest(lines=lines, texts=(text,)))
    assert result.proposals[0].state is ReconstructionState.PROVISIONAL
    assert result.proposals[0].review_reason == "STRUCTURE_TEXT_OWNERSHIP_CONFLICT"


def test_table_border_gap_uses_table_support() -> None:
    lines = _clear_lines()
    roi = StructuralRoi(
        "table-1",
        "table-grid",
        (5, 40, 105, 20),
        (0, 1),
        ((10.0, 50.0), (100.0, 50.0)),
        0.98,
        source_types=("table",),
    )
    result = _run(_manifest(lines=lines, rois=(roi,)))
    assert result.proposals[0].reconstruction_kind is (
        ReconstructionKind.TABLE_OR_RECTILINEAR_EDGE_COMPLETION
    )
    assert result.proposals[0].state is ReconstructionState.RECONSTRUCTED


def test_competing_continuations_remain_provisional_without_tie_break() -> None:
    lines = (
        LineSegment(10, 50, 50, 50, confidence=0.95),
        LineSegment(58, 49, 100, 49, confidence=0.95),
        LineSegment(58, 51, 100, 51, confidence=0.95),
    )
    result = _run(_manifest(lines=lines))
    assert len(result.proposals) >= 2
    assert all(item.state is ReconstructionState.PROVISIONAL for item in result.proposals)
    assert all(
        "COMPETING_CONTINUATION" in {conflict.conflict_code for conflict in item.conflicts}
        for item in result.proposals
    )


def test_duplicate_detectors_collapse_to_one_proposal() -> None:
    first, second = _clear_lines()
    lines = (
        first,
        first.copy(history=("detected:hough",), confidence=0.91),
        second,
        second.copy(history=("detected:lsd",), confidence=0.92),
    )
    result = _run(_manifest(lines=lines))
    assert len(result.proposals) == 1
    assert result.metrics.duplicate_evidence_collapsed == 2
    assert len(result.proposals[0].source_candidate_ids) == 4


def test_candidate_ordering_permutation_has_identical_manifest() -> None:
    lines = (*_clear_lines(), LineSegment(10, 90, 100, 90))
    first = _run(_manifest(lines=lines))
    second = _run(_manifest(lines=tuple(reversed(lines))))
    assert reconstruction_manifest_sha256(first) == reconstruction_manifest_sha256(second)
    assert first.manifest_id == second.manifest_id


def test_geometry_mutation_changes_proposal_identity() -> None:
    first = _run(_manifest(lines=_clear_lines()))
    mutated = (
        _clear_lines()[0],
        LineSegment(59, 50, 100, 50, confidence=0.96),
    )
    second = _run(_manifest(lines=mutated))
    assert first.proposals[0].stable_proposal_id != second.proposals[0].stable_proposal_id


def test_volatile_metadata_does_not_change_reconstruction_identity() -> None:
    first = _run(_manifest(lines=_clear_lines(), volatile={"timestamp": "one", "guid": "a"}))
    second = _run(_manifest(lines=_clear_lines(), volatile={"timestamp": "two", "guid": "b"}))
    assert reconstruction_manifest_sha256(first) == reconstruction_manifest_sha256(second)


def test_source_raster_evidence_is_read_only_and_deterministic() -> None:
    image = np.full((200, 300), 255, dtype=np.uint8)
    image[50, 10:101] = 0
    source = SourceRasterEvidence.create(source_page=_page(), image=image)
    image_before = image.copy()
    first = _run(_manifest(lines=_clear_lines()), source=source)
    second = _run(_manifest(lines=_clear_lines()), source=source)
    assert np.array_equal(image, image_before)
    assert reconstruction_manifest_sha256(first) == reconstruction_manifest_sha256(second)


def test_existing_rc3_reconstruction_is_preserved_not_duplicated() -> None:
    manifest = _manifest(lines=_clear_lines())
    accepted = AcceptedLineReconstruction(
        stable_entity_id="rc3-entity-1",
        geometry=LineGeometry.create((10, 50), (100, 50), 1),
        provenance_id="v2-provenance-1",
        source_candidate_ids=(),
    )
    result = _run(manifest, accepted=(accepted,))
    assert result.metrics.rc3_preserved == 1
    assert result.metrics.rc3_hypothesis_coverage == 1
    assert result.proposals == ()


def test_candidate_and_ownership_inputs_are_read_only_zero_delta() -> None:
    manifest = _manifest(lines=_clear_lines())
    ownership = arbitrate_candidate_ownership(manifest)
    candidate_before = manifest.canonical_bytes()
    ownership_before = ownership.canonical_bytes()
    build_line_reconstruction_manifest(manifest, ownership, config=_config())
    assert manifest.canonical_bytes() == candidate_before
    assert ownership.canonical_bytes() == ownership_before


def test_review_items_are_stable_and_risk_sorted() -> None:
    lines = (
        LineSegment(10, 50, 40, 50),
        LineSegment(50, 50, 80, 50),
        LineSegment(44, 30, 44, 70),
    )
    result = _run(_manifest(lines=lines))
    assert result.review_items
    assert result.review_items == tuple(
        sorted(result.review_items, key=lambda item: (-item.risk_score, item.review_item_id))
    )
    assert result.review_items[0].suggested_actions == (
        "ACCEPT",
        "REJECT",
        "EDIT",
        "LEAVE_UNRESOLVED",
    )


def test_diagnostic_dxf_uses_only_isolated_review_layers(tmp_path: Path) -> None:
    manifest = _manifest(lines=_clear_lines())
    reconstruction = _run(manifest)
    target = write_reconstruction_review_dxf(
        tmp_path / "review.dxf",
        candidate_manifest=manifest,
        reconstruction_manifest=reconstruction,
    )
    document = ezdxf.readfile(target)
    assert set(DIAGNOSTIC_LAYERS).issubset(
        {layer.dxf.name for layer in document.layers}
    )
    assert sum(
        entity.dxf.layer == "M3_RECONSTRUCTION_PROPOSAL"
        for entity in document.modelspace()
    ) == 1
