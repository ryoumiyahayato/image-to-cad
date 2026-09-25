from __future__ import annotations

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.content_ownership import (
    arbitrate_content_candidates,
    binary_from_foreground,
    build_text_semantic_ownership,
    finalize_content_ownership,
    graphic_source_mask,
    partition_content,
)
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.signature_overlay import mark_graphic_texts
from app.text_output_contract import decide_text_output


def test_every_source_pixel_gets_exactly_one_owner() -> None:
    binary = np.full((180, 320), 255, dtype=np.uint8)
    cv2.rectangle(binary, (10, 20), (310, 160), 0, 3)
    cv2.line(binary, (10, 90), (310, 90), 0, 3)
    cv2.putText(
        binary,
        "TITLE",
        (70, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        0,
        2,
        cv2.LINE_8,
    )
    text = TextCandidate(
        text="TITLE",
        bbox=(65, 52, 100, 35),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=True,
    )
    lines = (
        LineSegment(10.0, 20.0, 310.0, 20.0, width=3.0),
        LineSegment(10.0, 90.0, 310.0, 90.0, width=3.0),
        LineSegment(10.0, 160.0, 310.0, 160.0, width=3.0),
        LineSegment(10.0, 20.0, 10.0, 160.0, width=3.0),
        LineSegment(310.0, 20.0, 310.0, 160.0, width=3.0),
    )

    ownership = partition_content(
        binary,
        lines=lines,
        texts=(text,),
        signatures=(),
    )

    ownership.assert_valid()
    assert ownership.line[90, 150] == 255
    assert cv2.countNonZero(ownership.text) > 0
    assert not np.any((ownership.line > 0) & (ownership.text > 0))
    assert np.count_nonzero(ownership.source) == sum(
        np.count_nonzero(mask)
        for mask in (
            ownership.line,
            ownership.text,
            ownership.logo,
            ownership.graphic,
            ownership.signature,
            ownership.residual,
        )
    )


def test_unsafe_text_stays_explicit_graphic_outline_not_default_residual() -> None:
    binary = np.full((120, 260), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "ABC",
        (30, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text="ABC",
        bbox=(25, 35, 100, 50),
        confidence=0.93,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=False,
        review_note="connected to nearby source strokes",
    )
    marked = mark_graphic_texts((candidate,), page_shape=binary.shape)

    ownership = partition_content(
        binary,
        lines=(),
        texts=marked,
        signatures=(),
    )

    assert marked[0].kind == "text_candidate"
    assert cv2.countNonZero(ownership.logo) == 0
    assert cv2.countNonZero(ownership.text) == 0
    assert cv2.countNonZero(ownership.residual) == 0
    assert cv2.countNonZero(ownership.graphic) == cv2.countNonZero(
        np.where(binary < 128, 255, 0).astype(np.uint8)
    )


def test_connected_component_spans_characters_keeps_editable_primary_semantic() -> None:
    binary = np.full((120, 280), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "ABC",
        (30, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text="ABC",
        bbox=(25, 35, 105, 50),
        confidence=0.93,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=False,
        review_note="connected_component_spans_characters",
    )
    ownership = partition_content(
        binary,
        lines=(),
        texts=(candidate,),
        signatures=(),
    )
    semantics = build_text_semantic_ownership(
        binary,
        (candidate,),
        ownership=ownership,
    )

    decision = decide_text_output(candidate)
    assert decision.text_emit_eligible
    assert decision.primary_semantic == "editable_text"
    assert cv2.countNonZero(semantics.source_outline) > 0
    assert semantics.candidates[0]["source_pixels_conserved"]
    assert semantics.candidates[0]["primary_semantic_unique"]


def test_uncovered_nearby_ink_remains_visible_outside_candidate_mask() -> None:
    binary = np.full((120, 280), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "ABC",
        (30, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_8,
    )
    cv2.circle(binary, (155, 62), 3, 0, -1)
    candidate = TextCandidate(
        text="ABC",
        bbox=(25, 35, 105, 50),
        confidence=0.93,
        kind="text_candidate",
        source="test",
        approved=True,
        character_boxes=((25, 35, 105, 50),),
        replacement_safe=False,
        review_note="uncovered_nearby_ink",
    )
    ownership = partition_content(
        binary,
        lines=(),
        texts=(candidate,),
        signatures=(),
    )
    semantics = build_text_semantic_ownership(
        binary,
        (candidate,),
        ownership=ownership,
    )

    assert semantics.source_outline[62, 155] == 0
    assert ownership.graphic[62, 155] == 255
    assert semantics.candidates[0]["source_pixels_conserved"]
    assert set(
        candidate.category for candidate in ownership.candidate_classes
    ) == {"structural_line", "text", "logo", "signature", "graphic"}


def test_logo_owns_source_strokes_but_not_surrounding_cell_rules() -> None:
    binary = np.full((260, 420), 255, dtype=np.uint8)
    cv2.rectangle(binary, (20, 20), (400, 240), 0, 3)
    cv2.line(binary, (20, 190), (400, 190), 0, 3)
    cv2.putText(
        binary,
        "DESIGN GROUP",
        (75, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        0,
        2,
        cv2.LINE_8,
    )
    logo_bbox = (70, 120, 220, 40)
    x, y, width, height = logo_bbox
    logo_mask = np.where(
        binary[y : y + height, x : x + width] < 128,
        255,
        0,
    ).astype(np.uint8)
    logo = LogoRegion(
        bbox=logo_bbox,
        mask=logo_mask,
        structural_score=0.9,
        hole_count=2,
        contour_count=4,
    )

    graphic = graphic_source_mask(binary, (logo,))

    assert cv2.countNonZero(graphic) > 0
    assert graphic[190, 200] == 0
    contour_binary = binary_from_foreground(graphic)
    assert np.count_nonzero(contour_binary[120:160, 70:290] == 0) > 40


def test_character_stroke_line_candidate_is_arbitrated_to_text() -> None:
    binary = np.full((100, 140), 255, dtype=np.uint8)
    cv2.line(binary, (40, 50), (90, 50), 0, 2, cv2.LINE_8)
    text = TextCandidate(
        text="一",
        bbox=(35, 42, 62, 18),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=True,
    )
    line = LineSegment(40.0, 50.0, 90.0, 50.0, width=2.0)

    candidates = partition_content(
        binary,
        lines=(line,),
        texts=(text,),
        logos=(),
        signatures=(),
    )
    arbitrated = arbitrate_content_candidates(
        binary,
        lines=(line,),
        texts=(text,),
        logos=(),
        signatures=(),
        ownership=candidates,
    )
    final = finalize_content_ownership(
        binary,
        candidates=candidates,
        arbitrated=arbitrated,
    )

    assert not arbitrated.lines
    assert arbitrated.texts[0].replacement_safe
    assert cv2.countNonZero(final.line) == 0
    assert cv2.countNonZero(final.text) > 0
    assert any(
        conflict.final_category == "text"
        and conflict.conflict_reason
        == "line_text_overlap_without_independent_line_endpoints"
        for conflict in final.conflicts
    )
    payload = final.payload()
    assert payload["conflict_pixels"] > 0
    assert sum(payload["final_owner_pixels"].values()) == cv2.countNonZero(
        final.source
    )
    assert payload["unresolved_conflict_pixels"] == 0


def test_true_structure_line_downgrades_overlapping_editable_text() -> None:
    binary = np.full((100, 220), 255, dtype=np.uint8)
    cv2.line(binary, (10, 50), (210, 50), 0, 3, cv2.LINE_8)
    cv2.putText(
        binary,
        "A",
        (92, 63),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        0,
        2,
        cv2.LINE_8,
    )
    text = TextCandidate(
        text="A",
        bbox=(88, 38, 32, 32),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=True,
    )
    line = LineSegment(10.0, 50.0, 210.0, 50.0, width=3.0)

    candidates = partition_content(
        binary,
        lines=(line,),
        texts=(text,),
        logos=(),
        signatures=(),
    )
    arbitrated = arbitrate_content_candidates(
        binary,
        lines=(line,),
        texts=(text,),
        logos=(),
        signatures=(),
        ownership=candidates,
    )
    final = finalize_content_ownership(
        binary,
        candidates=candidates,
        arbitrated=arbitrated,
    )

    assert arbitrated.lines == (line,)
    assert not arbitrated.texts[0].replacement_safe
    assert cv2.countNonZero(final.line) > 0
    assert cv2.countNonZero(final.text) == 0
    assert any(
        conflict.final_category == "structural_line"
        and conflict.conflict_reason
        == "line_text_overlap_with_independent_line_endpoints"
        for conflict in final.conflicts
    )
    semantics = build_text_semantic_ownership(
        binary,
        arbitrated.texts,
        ownership=final,
    )
    decision = decide_text_output(arbitrated.texts[0])
    assert decision.text_emit_eligible
    assert decision.primary_semantic == "editable_text"
    assert not np.any(
        (semantics.source_outline > 0) & (final.line > 0)
    )
    assert semantics.candidates[0]["source_pixels_conserved"]


def test_logo_text_conflict_preserves_only_exact_overlap_as_residual() -> None:
    binary = np.full((100, 220), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "AB",
        (30, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        0,
        2,
        cv2.LINE_8,
    )
    text = TextCandidate(
        text="AB",
        bbox=(25, 35, 75, 38),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        approved=True,
        replacement_safe=True,
    )
    logo_bbox = (30, 35, 24, 38)
    x, y, width, height = logo_bbox
    logo_mask = np.where(
        binary[y : y + height, x : x + width] < 128,
        255,
        0,
    ).astype(np.uint8)
    logo = LogoRegion(
        bbox=logo_bbox,
        mask=logo_mask,
        structural_score=0.9,
        hole_count=2,
        contour_count=3,
    )

    ownership = partition_content(
        binary,
        lines=(),
        texts=(text,),
        logos=(logo,),
        signatures=(),
    )

    assert cv2.countNonZero(ownership.residual) == cv2.countNonZero(
        logo_mask
    )
    assert cv2.countNonZero(ownership.text) > 0
    assert cv2.countNonZero(ownership.logo) == 0
    assert cv2.countNonZero(ownership.graphic) == 0
    assert all(
        conflict.final_category == "residual"
        and conflict.downgrade_reason == "semantic_evidence_conflict"
        for conflict in ownership.conflicts
    )


def test_line_crossing_unresolved_logo_conflict_is_not_exported() -> None:
    binary = np.full((100, 220), 255, dtype=np.uint8)
    cv2.line(binary, (10, 50), (210, 50), 0, 3, cv2.LINE_8)
    cv2.circle(binary, (110, 50), 14, 0, 2, cv2.LINE_8)
    logo_bbox = (94, 34, 33, 33)
    x, y, width, height = logo_bbox
    logo_mask = np.where(
        binary[y : y + height, x : x + width] < 128,
        255,
        0,
    ).astype(np.uint8)
    logo = LogoRegion(
        bbox=logo_bbox,
        mask=logo_mask,
        structural_score=0.9,
        hole_count=2,
        contour_count=3,
    )
    line = LineSegment(10.0, 50.0, 210.0, 50.0, width=3.0)
    candidates = partition_content(
        binary,
        lines=(line,),
        texts=(),
        logos=(logo,),
        signatures=(),
    )

    arbitrated = arbitrate_content_candidates(
        binary,
        lines=(line,),
        texts=(),
        logos=(logo,),
        signatures=(),
        ownership=candidates,
    )

    assert not arbitrated.lines
    assert any(
        item["candidate_category"] == "structural_line"
        and item["conflict_reason"] == "line_source_not_exclusively_owned"
        for item in arbitrated.downgrades
    )
