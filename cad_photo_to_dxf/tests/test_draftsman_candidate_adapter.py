from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import ezdxf
import numpy as np

from app.auxiliary_recognition import CircleCandidate, SymbolCandidate, TextCandidate
from app.draftsman_adapter import adapt_legacy_final_structure
from app.draftsman_candidate import (
    CandidateKind,
    CandidateRelationshipKind,
    LineCandidatePayload,
    StructuralRoiCandidatePayload,
    TextCandidatePayload,
    candidate_manifest_sha256,
)
from app.draftsman_candidate_adapter import (
    adapt_candidate_outputs,
    adapt_line_candidates,
    adapt_text_candidates,
    current_candidate_producers,
)
from app.draftsman_contract import EvidenceState, SourcePageRef, TransformRef
from app.final_structure import FinalStructure, build_final_structure
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.signature_overlay import SignatureRegion, SignatureVisualEvidence
from app.structural_roi import StructuralRoi
from app.text_protection import TEXT_MASK_RESTORATION
from app.trace_single_export import export_final_structure_dxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from v2_canonical_structure import canonical_json_bytes, canonical_payload  # noqa: E402


def _page() -> SourcePageRef:
    return SourcePageRef("candidate-document", 1, "c" * 64, (200, 100))


def _transform() -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload={
            "origin": [0.0, 100.0],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _producers(*, volatile: object | None = None):
    return current_candidate_producers(
        line_config={
            "min_line_length": 24,
            "max_line_gap": 0,
            "hough_threshold": 28,
            "use_lsd": True,
            "max_segments": 5000,
            "center_thick_strokes": True,
        },
        text_config={
            "pipeline": "optimized-native-tile",
            "bbox_role": "source-evidence-only",
        },
        structural_roi_config={
            "extension_budget": 3.0,
            "intersection_tolerance": 3.0,
        },
        include_legacy_auxiliary=True,
        diagnostic_metadata=volatile,
    )


def _structure(
    lines: tuple[LineSegment, ...],
    texts: tuple[TextCandidate, ...] = (),
) -> FinalStructure:
    binary = np.full((100, 200), 255, dtype=np.uint8)
    return build_final_structure(
        source_size_px=(200, 100),
        contour_binary=binary,
        contours=(),
        straight_lines=lines,
        texts=texts,
        preview_binary=binary,
    )


def test_overlapping_text_and_line_candidates_are_both_preserved() -> None:
    line = LineSegment(5.0, 15.0, 50.0, 15.0, source_ids=("HOUGH-000001",))
    text = TextCandidate(
        "A1",
        (10, 10, 20, 10),
        0.93,
        "text_candidate",
        quad=((10.0, 10.0), (30.0, 10.0), (30.0, 20.0), (10.0, 20.0)),
        source="rapidocr-tile",
    )
    manifest = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(line,),
        text_candidates=(text,),
        include_spatial_relationships=True,
    )
    assert manifest.candidate_count == 2
    assert {item.candidate_kind for item in manifest.candidates} == {
        CandidateKind.LINE_SEGMENT,
        CandidateKind.OCR_TEXT,
    }
    assert any(
        item.relationship_kind is CandidateRelationshipKind.OVERLAPS
        for item in manifest.relationships
    )


def test_ocr_adapter_preserves_source_bbox_quad_text_and_orientation() -> None:
    text = TextCandidate(
        "R25",
        (17, 23, 46, 12),
        0.87,
        "dimension_text_candidate",
        rotation_deg=12.5,
        quad=((17.0, 23.0), (63.0, 25.0), (62.0, 35.0), (16.0, 34.0)),
        source="rapidocr-overview",
        character_boxes=((17, 23, 10, 12), (28, 23, 10, 12), (39, 23, 10, 12)),
    )
    records = adapt_text_candidates(
        (text,),
        source_page=_page(),
        transform=_transform(),
        producer=_producers().text,
    )
    payload = records[0].payload
    assert isinstance(payload, TextCandidatePayload)
    assert payload.raw_recognized_text == "R25"
    assert payload.source_bbox == text.bbox
    assert payload.source_quad == text.quad
    assert payload.rotation_degrees == 12.5
    assert payload.orientation_evidence == "source-quad-and-rotation"
    assert "cad_insertion" not in payload.to_dict()
    assert "text_height" not in payload.to_dict()


def test_geometry_adapter_does_not_snap_extend_merge_or_reconstruct() -> None:
    line = LineSegment(
        10.125,
        20.25,
        79.875,
        21.5,
        width=1.75,
        confidence=0.82,
        source_ids=("LSD-000007",),
        history=("detected:lsd",),
    )
    before = replace(line)
    records = adapt_line_candidates(
        (line,),
        source_page=_page(),
        transform=_transform(),
        producer=_producers().line,
    )
    payload = records[0].payload
    assert isinstance(payload, LineCandidatePayload)
    assert payload.start == (line.x1, line.y1)
    assert payload.end == (line.x2, line.y2)
    assert payload.width == line.width
    assert line == before
    assert payload.detector_history == ("detected:lsd",)


def test_legacy_detector_ordinals_are_evidence_not_candidate_identity() -> None:
    first = LineSegment(
        10.0,
        20.0,
        80.0,
        20.0,
        source_ids=("HOUGH-000001",),
        history=("detected:hough",),
    )
    reordered = replace(first, source_ids=("HOUGH-000999",))
    first_record = adapt_line_candidates(
        (first,),
        source_page=_page(),
        transform=_transform(),
        producer=_producers().line,
    )[0]
    reordered_record = adapt_line_candidates(
        (reordered,),
        source_page=_page(),
        transform=_transform(),
        producer=_producers().line,
    )[0]
    assert first_record.stable_candidate_id == reordered_record.stable_candidate_id
    assert first_record.evidence_refs[0].identity_participates is False
    assert first_record.evidence_refs[0].evidence_id != (
        reordered_record.evidence_refs[0].evidence_id
    )


def test_candidate_manifest_replay_and_input_order_are_deterministic() -> None:
    horizontal = LineSegment(5.0, 10.0, 90.0, 10.0, source_ids=("line-h",))
    vertical = LineSegment(20.0, 2.0, 20.0, 80.0, source_ids=("line-v",))
    text = TextCandidate(
        "T1",
        (15, 8, 15, 10),
        0.91,
        "text_candidate",
        source="rapidocr-tile",
    )
    forward = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(horizontal, vertical),
        text_candidates=(text,),
    )
    reverse = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(vertical, horizontal),
        text_candidates=(text,),
    )
    replay = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(horizontal, vertical),
        text_candidates=(text,),
    )
    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert forward.canonical_bytes() == replay.canonical_bytes()
    assert candidate_manifest_sha256(forward) == candidate_manifest_sha256(replay)


def test_identical_candidates_get_deterministic_counted_ids() -> None:
    line = LineSegment(1.0, 2.0, 50.0, 2.0)
    manifest = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(line, line),
    )
    line_records = [
        item
        for item in manifest.candidates
        if item.candidate_kind is CandidateKind.LINE_SEGMENT
    ]
    assert len(line_records) == 2
    assert len({item.stable_candidate_id for item in line_records}) == 2
    assert sorted(item.occurrence for item in line_records) == [1, 2]


def test_structural_roi_and_table_region_keep_source_line_relationships() -> None:
    lines = (
        LineSegment(5.0, 10.0, 90.0, 10.0, source_ids=("h1",)),
        LineSegment(5.0, 40.0, 90.0, 40.0, source_ids=("h2",)),
        LineSegment(10.0, 5.0, 10.0, 50.0, source_ids=("v1",)),
        LineSegment(80.0, 5.0, 80.0, 50.0, source_ids=("v2",)),
    )
    roi = StructuralRoi(
        roi_id="table-001",
        purpose="table",
        bbox=(3, 3, 90, 50),
        line_indices=(0, 1, 2, 3),
        evidence_intersections=((10.0, 10.0), (80.0, 10.0), (10.0, 40.0), (80.0, 40.0)),
        confidence=1.0,
        expansion_distance=3.0,
        source_types=("orthogonal_intersection_network",),
    )
    manifest = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=lines,
        structural_rois=(roi,),
    )
    table = next(
        item
        for item in manifest.candidates
        if item.candidate_kind is CandidateKind.TABLE_REGION
    )
    assert isinstance(table.payload, StructuralRoiCandidatePayload)
    assert len(table.payload.related_line_candidate_ids) == 4
    belongs = [
        item
        for item in manifest.relationships
        if item.relationship_kind is CandidateRelationshipKind.BELONGS_TO_REGION
    ]
    assert len(belongs) == 4


def test_logo_signature_and_legacy_auxiliary_candidates_are_typed_and_read_only() -> None:
    logo_mask = np.array([[0, 255], [255, 255]], dtype=np.uint8)
    signature_mask = np.array([[255, 0, 255], [0, 255, 0]], dtype=np.uint8)
    logo = LogoRegion(
        bbox=(10, 20, 2, 2),
        mask=logo_mask,
        structural_score=0.88,
        hole_count=2,
        contour_count=3,
        density=0.75,
        closed_complexity=12,
        reflection_similarity=0.6,
    )
    visual = SignatureVisualEvidence(
        source_component_count=2,
        source_pixel_count=3,
        density=0.5,
        continuity=0.8,
        directional_complexity=10,
        positive_diagonal_span=5.0,
        negative_diagonal_span=4.0,
        bidirectional_diagonal_support=True,
        perimeter_per_pixel=0.8,
        convex_solidity=0.4,
        confidence=0.86,
    )
    signature = SignatureRegion((30, 40, 3, 2), signature_mask, visual)
    before_logo = logo_mask.tobytes()
    before_signature = signature_mask.tobytes()
    manifest = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        logo_candidates=(logo,),
        signature_candidates=(signature,),
        circle_candidates=(CircleCandidate((50.0, 50.0), 8.0, 0.9),),
        symbol_candidates=(SymbolCandidate("square_or_column_candidate", (60, 60, 10, 10), 0.8),),
    )
    assert {item.candidate_kind for item in manifest.candidates} == {
        CandidateKind.LOGO,
        CandidateKind.SIGNATURE,
        CandidateKind.CIRCLE,
        CandidateKind.SYMBOL,
    }
    assert logo_mask.tobytes() == before_logo
    assert signature_mask.tobytes() == before_signature


def test_m0_rc3_reconstructed_mapping_is_preserved() -> None:
    line = LineSegment(
        10.0,
        20.0,
        80.0,
        20.0,
        source_ids=("line-1",),
        history=("detected:lsd", TEXT_MASK_RESTORATION),
    )
    structure = _structure((line,))
    shadow = adapt_legacy_final_structure(
        structure,
        document_id=_page().source_document_id,
        page_number=1,
        source_sha256=_page().source_sha256,
        transform=_transform(),
    )
    assert shadow.entities[0].state is EvidenceState.RECONSTRUCTED
    candidate = adapt_line_candidates(
        (line,),
        source_page=_page(),
        transform=_transform(),
        producer=_producers().line,
    )[0]
    assert candidate.candidate_kind is CandidateKind.LINE_SEGMENT
    assert isinstance(candidate.payload, LineCandidatePayload)
    assert TEXT_MASK_RESTORATION in candidate.payload.detector_history


def _dxf_semantics(path: Path) -> list[dict[str, object]]:
    document = ezdxf.readfile(path)
    return sorted(
        (canonical_payload(entity) for entity in document.modelspace()),
        key=canonical_json_bytes,
    )


def test_candidate_adapter_has_zero_production_semantic_delta(tmp_path: Path) -> None:
    line = LineSegment(5.0, 6.0, 80.0, 6.0, source_ids=("line-1",))
    text = TextCandidate(
        "A-101",
        (20, 20, 40, 12),
        0.99,
        "text_candidate",
        source="unit-test",
        approved=True,
        replacement_safe=True,
    )
    structure = _structure((line,), (text,))
    before = tmp_path / "before.dxf"
    after = tmp_path / "after.dxf"
    before_result = export_final_structure_dxf(structure, before)
    manifest = adapt_candidate_outputs(
        source_page=_page(),
        transform=_transform(),
        producers=_producers(),
        line_candidates=(line,),
        text_candidates=(text,),
    )
    after_result = export_final_structure_dxf(structure, after)
    assert manifest.candidate_count == 2
    assert before_result.structure_id == after_result.structure_id
    assert _dxf_semantics(before) == _dxf_semantics(after)


def test_production_modules_do_not_import_candidate_shadow_layer() -> None:
    excluded = {"draftsman_candidate.py", "draftsman_candidate_adapter.py"}
    consumers = []
    for path in (PROJECT_ROOT / "app").glob("*.py"):
        if path.name in excluded:
            continue
        source = path.read_text(encoding="utf-8")
        if "draftsman_candidate" in source:
            consumers.append(path.name)
    assert consumers == []
