from __future__ import annotations

import cv2
from dataclasses import replace
import hashlib
import json
import numpy as np
import pytest
from unittest.mock import patch
from pathlib import Path

import app.geometry.source_stroke_reconciliation as reconciliation
from app.geometry.content_ownership import (
    arbitrate_content_candidates,
    finalize_content_ownership,
    graphic_source_mask,
    partition_content,
)
from app.geometry.line_detect import LineSegment
from app.ocr.logo_detection import LogoRegion
from app.geometry.optimized_trace import _preserve_ownership_continuity
from app.geometry.source_stroke_reconciliation import (
    LEGACY_ACCEPTED_HISTORY,
    LineageOperation,
    ReconciliationLedger,
    Relation,
    RouteOrigin,
    TerminalDisposition,
)
from app.geometry.straight_line_reconstruction import (
    _prepare_late_restorations,
    reconstruct_straight_lines,
    suppress_parallel_duplicate_detections,
)
from app.export.trace_dxf_entities import add_straight_line_entities


@pytest.mark.parametrize(
    "coords,piece,width",
    [
        ((18, 23, 62, 23), (29, 23, 48, 23), 1),
        ((5.5, 7.5, 85.5, 70.5), (22.5, 21.5, 60.5, 50.5), 4),
        ((-40, 16, 120, 83), (10, 37, 70, 62), 2),
        ((-40, -30, -20, -5), (-35, -28, -25, -10), 8),
        ((2, 3, 93, 79), (2, 3, 93, 79), 24),
        ((13.5, 20.5, 79.5, 20.5), (32.5, 20.5, 65.5, 20.5), 1),
    ],
)
def test_local_claim_measurements_match_full_page_pixel_contract(coords, piece, width):
    from app.geometry.reconciliation_geometry import _line_claim_mask

    shape = (84, 96)
    parent = LineSegment(*coords, width=width)
    child = LineSegment(*piece, width=width)
    yy, xx = np.indices(shape)
    binary = np.where((xx + 2 * yy) % 3, 0, 255).astype(np.uint8)
    masks = {
        name: np.where((xx + i * yy) % (i + 3) == 0, 255, 0).astype(np.uint8)
        for i, name in enumerate(
            ("line", "text", "graphic", "logo", "signature", "residual"), 1
        )
    }
    protected = np.where(xx % 5 == 0, 255, 0).astype(np.uint8)
    full_parent = _line_claim_mask(parent, shape=shape) > 0
    full_child = _line_claim_mask(child, shape=shape) > 0
    source = binary < 128
    owned = full_child & source
    conflicts = (
        masks["text"] | masks["graphic"] | masks["logo"] | masks["signature"]
    ) > 0
    expected = {
        "source_pixels": int(owned.sum()),
        "new_source_pixels": int((owned & (masks["line"] == 0)).sum()),
        "protected_source_pixels": int((owned & (protected > 0)).sum()),
        "semantic_conflict_source_pixels": int((owned & conflicts).sum()),
        "residual_source_pixels": int((owned & (masks["residual"] > 0)).sum()),
    }
    assert (
        reconciliation._claim_measurements(
            child, masks=masks, protected_mask=protected, source_binary=binary
        )
        == expected
    )
    delta = full_child & ~full_parent & source
    expected_delta = {
        "new_source_pixels": int(delta.sum()),
        "new_protected_source_pixels": int((delta & (protected > 0)).sum()),
        "inherited_protected_source_pixels": int(
            (owned & full_parent & (protected > 0)).sum()
        ),
    }
    assert (
        reconciliation._claim_delta_measurements(
            parent, child, protected_mask=protected, source_binary=binary
        )
        == expected_delta
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_real_tiny_house_white_edge_alias_keeps_source_window_boundaries(reverse):
    # Original PDF physical p9, 240 dpi, crop (700,830)-(850,995).
    gray = cv2.imread(
        str(
            Path(__file__).parent / "real_regression/assets/regions/"
            "tiny-house-window-p9-240dpi.png"
        ),
        cv2.IMREAD_GRAYSCALE,
    )
    assert gray is not None
    binary = np.where(gray < 254, 0, 255).astype(np.uint8)
    observations = [
        (21, 135, 124, 135, "HOUGH-000012"),
        (61, 150, 123, 150, "HOUGH-000033"),
        (35, 142, 79, 142, "HOUGH-000040"),
        (18, 17, 18, 135, "HOUGH-000078"),
        (21.875, 144.701782, 121.875, 144.701782, "LSD-000400"),
        (17.857422, 134.375, 17.869995, 16.874817, "LSD-000507"),
        (20.884155, 134.375, 20.896667, 19.374878, "LSD-000508"),
        (21.874939, 135.155151, 124.375122, 135.140930, "LSD-001004"),
        (21.875, 142.043640, 121.875, 142.043640, "LSD-001285"),
        (21.875, 150.150452, 121.875, 150.150391, "LSD-001330"),
        (21.875, 137.649109, 121.875, 137.650146, "LSD-001357"),
    ]
    lines = [
        LineSegment(
            *values[:4],
            width=1.909999966621399,
            confidence=1 if values[4].startswith("HOUGH") else 0.8,
            source_ids=(values[4],),
            history=(
                "detected:" + ("hough" if values[4].startswith("HOUGH") else "lsd"),
            ),
        )
        for values in observations
    ]
    if reverse:
        lines.reverse()
    ledger = ReconciliationLedger(
        source_gray=gray,
        source_binary=binary,
        protected_mask=np.zeros_like(binary),
        scale=1,
    )
    ledger.observe_route(
        lines, route=RouteOrigin.MAIN, producer="saved-real-observations"
    )
    out = ledger.consolidate_detector_aliases(lines)
    merged = [line for line in out if "HOUGH-000012" in line.source_ids]
    assert len(merged) == 1
    assert set(merged[0].source_ids) == {"HOUGH-000012", "LSD-001004"}
    assert (merged[0].x1, merged[0].y1, merged[0].x2, merged[0].y2) == (
        21,
        135,
        124,
        135,
    )
    # Different vertical window edges, horizontal panes and short nested
    # observations must retain their own geometry, even with overlapping claims.
    for sid in ("LSD-000508", "LSD-000400", "LSD-001285", "LSD-001357", "HOUGH-000040"):
        original = next(line for line in lines if line.source_ids == (sid,))
        assert original in out
    result = ledger.reconcile(
        main_candidates=out,
        accepted_main=out,
        restoration_candidates=[],
        ownership_masks={},
    )
    assert sum("LSD-001004" in line.source_ids for line in result.lines) == 1
    result.assert_complete()


@pytest.mark.parametrize(
    "condition",
    [
        "plain",
        "gap",
        "second_band",
        "faint_band",
        "protected",
        "new_endpoint",
        "junction",
    ],
)
def test_white_edge_alias_requires_complete_single_source_and_endpoint_coverage(
    condition,
):
    gray = _page((90, 110))
    cv2.line(gray, (15, 41), (90, 41), 0, 1)
    keeper = _line(15, 40, 90, 40, "first", width=2, history=("detected:hough",))
    candidate = _line(
        16.1, 40.15, 90.2, 40.15, "second", width=2, history=("detected:lsd",)
    )
    protection = np.zeros_like(gray)
    if condition == "gap":
        gray[:, 50] = 255
    if condition in {"second_band", "faint_band"}:
        cv2.line(gray, (15, 43), (90, 43), 0 if condition == "second_band" else 210, 1)
    if condition == "protected":
        protection[41, 50] = 255
    if condition == "new_endpoint":
        candidate = candidate.copy(x1=30)
    if condition == "junction":
        cv2.line(gray, (90, 40), (90, 20), 0, 1)
    binary = np.where(gray < 254, 0, 255).astype(np.uint8)
    ledger = ReconciliationLedger(
        source_gray=gray, source_binary=binary, protected_mask=protection, scale=1
    )
    lines = (keeper, candidate)
    if condition == "junction":
        lines += (
            _line(
                candidate.x2,
                candidate.y2,
                candidate.x2,
                20,
                "peer",
                history=("detected:hough",),
            ),
        )
    out = ledger.consolidate_detector_aliases(lines)
    assert len(out) == (1 if condition == "plain" else len(lines))
    assert (out[0].x1, out[0].y1, out[0].x2, out[0].y2) == (15, 40, 90, 40)


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source_id: str,
    *,
    width: float = 1.0,
    history: tuple[str, ...] = (),
) -> LineSegment:
    return LineSegment(
        x1,
        y1,
        x2,
        y2,
        width=width,
        source_ids=(source_id,),
        history=history,
    )


def _page(shape: tuple[int, int] = (220, 240)) -> np.ndarray:
    return np.full(shape, 255, dtype=np.uint8)


def _draw(page: np.ndarray, line: LineSegment, *, thickness: int = 1) -> None:
    cv2.line(
        page,
        (int(round(line.x1)), int(round(line.y1))),
        (int(round(line.x2)), int(round(line.y2))),
        0,
        thickness,
        cv2.LINE_8,
    )


def _ownership_line(page: np.ndarray, lines: list[LineSegment]) -> np.ndarray:
    mask = np.zeros_like(page)
    for line in lines:
        cv2.line(
            mask,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            max(1, int(round(line.width))),
            cv2.LINE_8,
        )
    return np.where((mask > 0) & (page < 128), 255, 0).astype(np.uint8)


def _reconcile(
    page: np.ndarray,
    *,
    main: list[LineSegment],
    accepted_main: list[LineSegment] | None = None,
    restorations: list[LineSegment] | None = None,
    protected: np.ndarray | None = None,
    ownership_overrides: dict[str, np.ndarray] | None = None,
    ledger: ReconciliationLedger | None = None,
):
    accepted = main if accepted_main is None else accepted_main
    protection = np.zeros_like(page) if protected is None else protected
    masks: dict[str, np.ndarray] = {
        "line": _ownership_line(page, accepted),
    }
    masks.update(ownership_overrides or {})
    if ledger is None:
        ledger = ReconciliationLedger(
            source_gray=page,
            source_binary=page,
            protected_mask=protection,
            scale=1.0,
        )
    return ledger.reconcile(
        main_candidates=main,
        accepted_main=accepted,
        restoration_candidates=restorations or [],
        ownership_masks=masks,
    )


def _source_ids(result) -> list[tuple[str, ...]]:
    return [line.source_ids for line in result.lines]


@pytest.mark.parametrize(
    ("case", "long", "first", "second"),
    [
        (
            "ENV-1",
            _line(20, 40, 190, 40, "LSD-000014", width=2),
            _line(80, 40, 120, 40, "HOUGH-000252", width=2),
            _line(121, 40, 180, 40, "HOUGH-000138", width=2),
        ),
        (
            "ENV-4",
            _line(20, 140, 190, 140, "LSD-000267", width=2),
            _line(80, 140, 120, 140, "HOUGH-000496", width=2),
            _line(121, 140, 180, 140, "HOUGH-000564", width=2),
        ),
    ],
)
def test_env_group_nonoverlap_cannot_veto_independent_same_cells(
    case: str,
    long: LineSegment,
    first: LineSegment,
    second: LineSegment,
) -> None:
    page = _page()
    _draw(page, long, thickness=2)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    ledger.observe_route(
        [long, first, second],
        route=RouteOrigin.MAIN,
        producer=f"{case}-before-suppression",
    )

    deferred = suppress_parallel_duplicate_detections(
        [long, first, second],
        gray=page,
        scale=1.0,
        reconciliation_ledger=ledger,
    )

    assert deferred == [long, first, second]
    result = ledger.reconcile(
        main_candidates=deferred,
        accepted_main=deferred,
        restoration_candidates=[],
        ownership_masks={"line": _ownership_line(page, deferred)},
    )
    payload = result.ledger_payload()
    same_pairs = {
        tuple(sorted(cell["members"]))
        for cell in payload["cells"]
        if cell["relation"] == Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
    }
    assert len(same_pairs) == 2
    assert any(
        item["kind"] == "ROUTE_DECISION"
        and item["measurements"]["state"] == "PROPOSED_ONLY"
        for item in payload["evidence"]
    )
    assert sum(line.length for line in result.lines) == pytest.approx(long.length)
    result.assert_complete()


def test_env2_partial_legacy_restoration_keeps_only_novel_parent_pieces() -> None:
    page = _page()
    main_left = _line(20, 80, 60, 80, "HOUGH-000098", width=2)
    main_right = _line(100, 80, 130, 80, "HOUGH-000654", width=2)
    restoration = _line(
        20,
        80,
        160,
        80,
        "LSD-002819",
        width=2,
        history=(LEGACY_ACCEPTED_HISTORY,),
    )
    _draw(page, restoration, thickness=2)

    result = _reconcile(
        page,
        main=[main_left, main_right],
        restorations=[restoration],
    )

    restored = [line for line in result.lines if line.source_ids == ("LSD-002819",)]
    assert [(line.x1, line.x2) for line in restored] == pytest.approx(
        [(60.0, 100.0), (130.0, 160.0)]
    )
    assert restoration.x2 == 160
    assert all(
        line.history[-1] == "source_stroke_reconciliation_piece" for line in restored
    )


def test_exact_long_medium_short_with_independent_attachments_stay_editable() -> None:
    page = _page()
    lines = [
        _line(20, 70, 200, 70, "LONG"),
        _line(60, 70, 160, 70, "MEDIUM"),
        _line(90, 70, 130, 70, "SHORT"),
    ]
    _draw(page, lines[0])
    for x in (60, 90, 130, 160):
        cv2.line(page, (x, 60), (x, 80), 0, 1, cv2.LINE_8)

    result = _reconcile(page, main=lines)

    assert len(result.lines) == 3
    assert set(_source_ids(result)) == {("LONG",), ("MEDIUM",), ("SHORT",)}


@pytest.mark.parametrize("offset", [1, 2, 3])
def test_near_coincident_tracks_with_endpoint_obligations_do_not_collapse(
    offset: int,
) -> None:
    page = _page()
    first = _line(20, 50, 190, 50, f"A-{offset}")
    second = _line(50, 50 + offset, 150, 50 + offset, f"B-{offset}")
    _draw(page, first)
    _draw(page, second)
    for x in (50, 150):
        cv2.line(
            page,
            (x, 45 + offset),
            (x, 55 + offset),
            0,
            1,
            cv2.LINE_8,
        )

    result = _reconcile(page, main=[first, second])

    assert len(result.lines) == 2


def test_nested_rectangle_shared_locus_preserves_boundary_identities() -> None:
    page = _page()
    shared = [
        _line(30, 20, 30, 190, "OUTER"),
        _line(30, 50, 30, 160, "MIDDLE"),
        _line(30, 80, 30, 130, "INNER"),
    ]
    _draw(page, shared[0])
    for y in (20, 50, 80, 130, 160, 190):
        cv2.line(page, (30, y), (80, y), 0, 1, cv2.LINE_8)

    result = _reconcile(page, main=shared)

    assert len(result.lines) == 3


def test_legitimate_double_rule_is_distinct_on_original_light_gap() -> None:
    page = _page()
    upper = _line(20, 60, 200, 60, "UPPER")
    lower = _line(20, 64, 200, 64, "LOWER")
    _draw(page, upper)
    _draw(page, lower)

    result = _reconcile(page, main=[upper, lower])

    assert len(result.lines) == 2
    assert any(
        cell["relation"] == Relation.DISTINCT_VISIBLE_STROKES_SUPPORTED.value
        for cell in result.ledger_payload()["cells"]
    )


def test_hollow_structure_keeps_both_boundaries_without_centerline() -> None:
    page = _page()
    left = _line(70, 30, 70, 190, "HOLLOW-LEFT")
    right = _line(74, 30, 74, 190, "HOLLOW-RIGHT")
    cv2.rectangle(page, (70, 30), (74, 190), 0, 1)

    result = _reconcile(page, main=[left, right])

    assert len(result.lines) == 2
    assert {line.x1 for line in result.lines} == {70, 74}


def test_filled_thick_band_can_keep_one_existing_representation() -> None:
    page = _page()
    cv2.line(page, (20, 100), (200, 100), 0, 7, cv2.LINE_8)
    first = _line(20, 98, 200, 98, "FILLED-A", width=4)
    second = _line(20, 102, 200, 102, "FILLED-B", width=4)

    result = _reconcile(page, main=[first, second])

    assert len(result.lines) == 1
    assert (result.lines[0].y1, result.lines[0].y2) in {(98, 98), (102, 102)}


def test_true_novel_damaged_continuation_preserves_hole_and_far_endpoint() -> None:
    page = _page()
    main = _line(20, 120, 100, 120, "MAIN")
    restoration = _line(
        80,
        120,
        180,
        120,
        "RESTORE",
        history=(LEGACY_ACCEPTED_HISTORY,),
    )
    cv2.line(page, (20, 120), (114, 120), 0, 1, cv2.LINE_8)
    cv2.line(page, (121, 120), (180, 120), 0, 1, cv2.LINE_8)

    result = _reconcile(page, main=[main], restorations=[restoration])
    restored = [line for line in result.lines if line.source_ids == ("RESTORE",)]

    assert len(restored) == 2
    assert restored[0].x1 >= 100
    assert restored[0].x2 < restored[1].x1
    assert restored[-1].x2 == pytest.approx(180)


def test_text_adjacent_fresh_restoration_is_blocked_not_promoted() -> None:
    page = _page()
    main = _line(20, 150, 100, 150, "MAIN")
    restoration = _line(80, 150, 180, 150, "RESTORE-FRESH")
    _draw(page, _line(20, 150, 180, 150, "SOURCE"))
    protected = np.zeros_like(page)
    protected[145:156, 130:181] = 255
    text = np.where((protected > 0) & (page < 128), 255, 0).astype(np.uint8)

    result = _reconcile(
        page,
        main=[main],
        restorations=[restoration],
        protected=protected,
        ownership_overrides={"text": text},
    )

    assert _source_ids(result) == [("MAIN",)]
    assert any(
        item["disposition"] == "BLOCKED"
        for item in result.ledger_payload()["supersession_ledger"]
    )


def test_fresh_partial_restoration_emits_safe_piece_and_blocks_disputed_tail() -> None:
    page = _page()
    main_left = _line(20, 170, 60, 170, "MAIN-LEFT")
    main_right = _line(100, 170, 130, 170, "MAIN-RIGHT")
    restoration = _line(20, 170, 180, 170, "PARTIAL-FRESH")
    _draw(page, restoration)
    protected = np.zeros_like(page)
    protected[165:176, 130:181] = 255

    result = _reconcile(
        page,
        main=[main_left, main_right],
        restorations=[restoration],
        protected=protected,
    )
    restored = [line for line in result.lines if line.source_ids == ("PARTIAL-FRESH",)]

    assert [(line.x1, line.x2) for line in restored] == pytest.approx([(60, 100)])
    parent = next(
        item
        for item in result.ledger_payload()["supersession_ledger"]
        if "PARTIAL-FRESH" in item["representation_id"]
    )
    assert parent["disposition"] == "SPLIT"


def test_unresolved_equal_geometry_preserves_accepted_representations() -> None:
    page = _page()
    first = _line(20, 30, 180, 30, "UNKNOWN-A")
    second = _line(20, 30, 180, 30, "UNKNOWN-B")

    result = _reconcile(page, main=[first, second])

    assert len(result.lines) == 2


def test_rejected_keeper_cannot_supply_coverage_for_restoration() -> None:
    page = _page()
    rejected = _line(20, 180, 120, 180, "REJECTED-MAIN")
    restoration = _line(20, 180, 180, 180, "RESTORE-AFTER-REJECT")
    _draw(page, restoration)

    result = _reconcile(
        page,
        main=[rejected],
        accepted_main=[],
        restorations=[restoration],
    )

    assert _source_ids(result) == [("RESTORE-AFTER-REJECT",)]
    assert result.lines[0].x1 == 20


def test_ownership_rejected_keeper_and_disputed_restoration_both_stay_out() -> None:
    page = _page()
    rejected = _line(20, 190, 120, 190, "REJECTED-MAIN")
    restoration = _line(20, 190, 180, 190, "DISPUTED-RESTORE")
    _draw(page, restoration)
    protected = np.where(page < 128, 255, 0).astype(np.uint8)

    result = _reconcile(
        page,
        main=[rejected],
        accepted_main=[],
        restorations=[restoration],
        protected=protected,
        ownership_overrides={"text": protected},
    )

    assert result.lines == ()


def test_empty_main_route_can_admit_safe_source_supported_restoration() -> None:
    page = _page()
    restoration = _line(30, 40, 180, 40, "EMPTY-MAIN-RESTORE")
    _draw(page, restoration)

    result = _reconcile(page, main=[], restorations=[restoration])

    assert _source_ids(result) == [("EMPTY-MAIN-RESTORE",)]


def test_no_late_output_legacy_helper_behavior_remains_available() -> None:
    page = _page()
    long = _line(20, 40, 180, 40, "LONG")
    short = _line(80, 40, 120, 40, "SHORT")
    _draw(page, long)

    legacy = suppress_parallel_duplicate_detections(
        [long, short],
        gray=page,
        scale=1.0,
    )
    late = _prepare_late_restorations(
        [short],
        [long],
        gray=page,
        scale=1.0,
    )

    assert len(legacy) == 1
    assert late == ()


def test_permutation_and_idempotence_preserve_geometry_and_digests() -> None:
    page = _page()
    long = _line(20, 100, 180, 100, "A-LONG")
    short = _line(80, 100, 120, 100, "B-SHORT")
    _draw(page, long)

    first = _reconcile(page, main=[long, short])
    permuted = _reconcile(page, main=[short, long])
    rerun = _reconcile(page, main=list(first.lines))

    def geometry(result):
        return [
            (line.x1, line.y1, line.x2, line.y2, line.source_ids)
            for line in result.lines
        ]

    assert geometry(first) == geometry(permuted)
    assert geometry(rerun) == geometry(first)
    assert first.final_set_digest == permuted.final_set_digest
    first.assert_complete()
    permuted.assert_complete()
    rerun.assert_complete()


def test_ledger_has_closed_v1_shape_and_resolvable_piece_references() -> None:
    page = _page()
    long = _line(20, 100, 180, 100, "SCHEMA-LONG")
    short = _line(80, 100, 120, 100, "SCHEMA-SHORT")
    _draw(page, long)

    payload = _reconcile(page, main=[long, short]).ledger_payload()

    assert set(payload) == {
        "schema_version",
        "record_id",
        "source_image_sha256",
        "producer_head",
        "policy_version",
        "input_set_digest",
        "final_main_set_digest",
        "route_ledger_digest",
        "physical_instance_assertion",
        "basis",
        "representations",
        "evidence",
        "cells",
        "endpoints",
        "pieces",
        "supersession_ledger",
        "transaction",
    }
    assert payload["schema_version"] == "source-visible-reconciliation-v1"
    assert payload["physical_instance_assertion"] is False
    endpoint_ids = {item["endpoint_id"] for item in payload["endpoints"]}
    evidence_ids = {item["evidence_id"] for item in payload["evidence"]}
    representation_ids = {
        item["representation_id"] for item in payload["representations"]
    }
    assert representation_ids == {
        item["representation_id"] for item in payload["supersession_ledger"]
    }
    for piece in payload["pieces"]:
        assert piece["start_endpoint_id"] in endpoint_ids
        assert piece["end_endpoint_id"] in endpoint_ids
        assert set(piece["support_evidence_refs"]) <= evidence_ids
        assert piece["new_protected_source_claim_pixels"] == 0


def test_stair_step_light_separator_is_not_dilated_into_same() -> None:
    page = _page()
    for x in range(10, 221):
        page[50 + x % 2, x] = 0
        page[52 + x % 2, x] = 0
    left = _line(20, 50.25, 210, 50.25, "STAIR-A")
    right = _line(20, 52.25, 210, 52.25, "STAIR-B")

    result = _reconcile(page, main=[left, right])

    assert len(result.lines) == 2
    assert all(
        cell["relation"] != Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
        for cell in result.ledger_payload()["cells"]
    )


def test_near_endpoints_with_independent_attachments_are_retained() -> None:
    page = _page()
    keeper = _line(10, 50, 200, 50, "END-A")
    candidate = _line(11, 50, 199, 50, "END-B")
    _draw(page, keeper)
    for x in (11, 199):
        cv2.line(page, (x, 50), (x, 75), 0, 1)

    result = _reconcile(page, main=[keeper, candidate])

    assert len(result.lines) == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_rejected_main_claim_cannot_reenter_through_restoration(legacy: bool) -> None:
    page = _page()
    rejected = _line(20, 50, 180, 50, "ANCESTOR")
    _draw(page, rejected)
    restored = rejected.copy(
        history=(LEGACY_ACCEPTED_HISTORY,) if legacy else ("text_mask_restoration",)
    )
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=None,
        scale=1.0,
    )
    ledger.observe_transformation(
        rejected,
        restored,
        parent_route=RouteOrigin.MAIN,
        child_route=RouteOrigin.RESTORATION,
        producer="test-explicit-route-diversion",
        operation=LineageOperation.ROUTE_DIVERSION,
    )

    result = _reconcile(
        page,
        main=[rejected],
        accepted_main=[],
        restorations=[restored],
        ownership_overrides={"graphic": np.where(page < 128, 255, 0).astype(np.uint8)},
        ledger=ledger,
    )

    assert not result.lines
    assert all(
        item["disposition"] == "OWNERSHIP_REJECTED"
        for item in result.ledger_payload()["supersession_ledger"]
    )


def test_sloped_parent_reduction_with_new_raster_claim_rolls_back() -> None:
    parent = LineSegment(
        21.074613966823737,
        36.975202884623805,
        190.79209210605188,
        40.22905163684617,
        width=1.0,
        source_ids=("PARENT",),
        history=(LEGACY_ACCEPTED_HISTORY,),
    )
    cut = 34.395969936063686
    piece = reconciliation._exact_subsegment(
        parent,
        reconciliation.ParameterInterval(cut, parent.length),
    )
    keeper = parent.copy(
        x2=piece.x1,
        y2=piece.y1,
        source_ids=("KEEPER",),
        history=(),
    )
    shape = (120, 240)
    parent_claim = reconciliation._line_claim_mask(parent, shape=shape)
    piece_claim = reconciliation._line_claim_mask(piece, shape=shape)
    new_claim = (piece_claim > 0) & (parent_claim == 0)
    page = np.where((parent_claim > 0) | new_claim, 0, 255).astype(np.uint8)
    protected = np.where(new_claim, 255, 0).astype(np.uint8)

    result = _reconcile(
        page,
        main=[keeper],
        restorations=[parent],
        protected=protected,
        ownership_overrides={"line": parent_claim},
    )
    restored = [line for line in result.lines if line.source_ids == ("PARENT",)]

    assert len(restored) == 1
    assert restored[0].p1.tolist() == parent.p1.tolist()
    assert restored[0].p2.tolist() == parent.p2.tolist()


def test_mixed_same_and_unknown_samples_are_separate_cells() -> None:
    page = _page()
    long = _line(10, 50, 220, 50, "CELL-A")
    short = _line(25, 50, 205, 50, "CELL-B")
    _draw(page, long)
    page[50, 100:106] = 255

    result = _reconcile(page, main=[long, short])
    relation_evidence = [
        item
        for item in result.ledger_payload()["evidence"]
        if item["kind"] in {"SOURCE_BAND_RUNS", "UNCERTAINTY"}
    ]

    assert len(result.lines) == 2
    assert any(
        item["measurements"].get("unknown_samples", 0) > 0 for item in relation_evidence
    )
    assert all(
        not (
            item["kind"] == "SOURCE_BAND_RUNS"
            and item["measurements"].get("unknown_samples", 0) > 0
        )
        for item in relation_evidence
    )


def test_actual_finalstructure_input_digest_rejects_late_append() -> None:
    page = _page()
    line = _line(20, 60, 150, 60, "COMMITTED")
    _draw(page, line)
    result = _reconcile(page, main=[line])
    late = _line(10, 95, 70, 95, "UNREVIEWED")

    with pytest.raises(AssertionError, match="Actual FinalStructure line set"):
        result.assert_complete((*result.lines, late))


def test_unrepresentable_novel_tail_preserves_accepted_parent() -> None:
    page = _page()
    keeper = _line(20, 60, 150, 60, "TAIL-A")
    candidate = _line(20, 60, 150.0000005, 60, "TAIL-B")
    _draw(page, keeper)

    result = _reconcile(page, main=[keeper, candidate])

    class Layout:
        def add_line(self, *args, **kwargs):
            return args, kwargs

    count, _entities, _bounds = add_straight_line_entities(
        Layout(),
        result.lines,
        transform=lambda x, y: (x, y),
    )
    assert len(result.lines) == 2
    assert count == 2


def test_ownership_continuity_preserves_residual_and_downgrades() -> None:
    page = _page((120, 240))
    line = _line(20, 60, 210, 60, "OWN")
    _draw(page, line)
    logo = LogoRegion(
        bbox=(100, 55, 20, 11),
        mask=np.full((11, 20), 255, np.uint8),
        structural_score=1.0,
        hole_count=0,
        contour_count=1,
    )
    initial_candidates = partition_content(
        page,
        lines=[line],
        texts=(),
        logos=[logo],
        signatures=(),
    )
    initial_arbitrated = arbitrate_content_candidates(
        page,
        lines=[line],
        texts=(),
        logos=[logo],
        signatures=(),
        ownership=initial_candidates,
    )
    initial = finalize_content_ownership(
        page,
        candidates=initial_candidates,
        arbitrated=initial_arbitrated,
    )
    updated_candidates = partition_content(
        page,
        lines=(),
        texts=(),
        logos=(),
        signatures=(),
        graphic_mask=graphic_source_mask(page, [logo]),
        forced_residual=initial.residual,
    )
    updated_arbitrated = arbitrate_content_candidates(
        page,
        lines=(),
        texts=(),
        logos=(),
        signatures=(),
        ownership=updated_candidates,
    )
    updated = finalize_content_ownership(
        page,
        candidates=updated_candidates,
        arbitrated=updated_arbitrated,
    )
    final = _preserve_ownership_continuity(
        initial,
        updated,
        initial_downgrades=initial_arbitrated.downgrades,
    )

    assert np.array_equal(final.residual, initial.residual)
    assert all(item in final.downgrades for item in initial_arbitrated.downgrades)
    assert all(item in final.conflicts for item in initial.conflicts)


def test_no_late_output_public_api_is_non_destructive() -> None:
    page = _page((120, 240))
    first = _line(10, 50, 220, 50, "API-A")
    second = _line(40, 52, 180, 52, "API-B")
    _draw(page, first)
    _draw(page, second)

    with patch(
        "app.geometry.straight_line_reconstruction.detect_lines",
        return_value=[first, second],
    ):
        output = reconstruct_straight_lines(
            page,
            late_restoration_output=None,
        )

    assert {line.source_ids for line in output} == {
        ("API-A",),
        ("API-B",),
    }


@pytest.mark.parametrize(
    ("left_y", "right_y"),
    [(50.4, 50.8), (50.35, 50.75), (50.45, 50.65)],
)
def test_fractional_trajectories_bind_their_actual_source_pixels(
    left_y: float,
    right_y: float,
) -> None:
    page = _page()
    page[50, 5:231] = 0
    page[51, 20:100] = 0
    left = _line(20, left_y, 210, left_y, "FRACTIONAL-A")
    right = _line(20, right_y, 210, right_y, "FRACTIONAL-B")

    result = _reconcile(page, main=[left, right])
    false_same = []
    for evidence in result.ledger_payload()["evidence"]:
        if evidence["kind"] != "SOURCE_BAND_RUNS":
            continue
        for cross_section in evidence["measurements"].get("cross_sections", ()):
            x, y = cross_section["right_trajectory_pixel"]
            if (
                cross_section["relation"]
                == Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
                and page[y, x] > 150
            ):
                false_same.append(cross_section)

    candidate_pieces = [
        line for line in result.lines if line.source_ids == right.source_ids
    ]
    assert candidate_pieces
    assert min(line.x1 for line in candidate_pieces) <= right.x1
    assert max(line.x2 for line in candidate_pieces) == right.x2
    assert not false_same


@pytest.mark.parametrize("height", [2, 3, 4])
def test_short_endpoint_attachments_preserve_obligation(height: int) -> None:
    page = _page()
    keeper = _line(10, 50, 220, 50, "SHORT-ATTACH-A")
    candidate = _line(25, 50, 200, 50, "SHORT-ATTACH-B")
    _draw(page, keeper)
    for x in (25, 200):
        cv2.line(page, (x, 50), (x, 50 + height), 0, 1)

    result = _reconcile(page, main=[keeper, candidate])

    candidate_pieces = [
        line for line in result.lines if line.source_ids == candidate.source_ids
    ]
    assert candidate_pieces
    assert any(np.array_equal(line.p1, candidate.p1) for line in candidate_pieces)
    assert any(np.array_equal(line.p2, candidate.p2) for line in candidate_pieces)


def test_fractional_sloped_short_attachment_preserves_obligation() -> None:
    page = _page()
    keeper = _line(10.2, 45.2, 220.2, 55.2, "SLOPED-ATTACH-A")
    candidate = _line(25.2, 45.9, 200.2, 54.2, "SLOPED-ATTACH-B")
    _draw(page, keeper)
    for point in (candidate.p1, candidate.p2):
        tangent = (candidate.p2 - candidate.p1) / candidate.length
        normal = np.array([-tangent[1], tangent[0]])
        end = point + normal * 3.0
        cv2.line(
            page,
            tuple(np.rint(point).astype(int)),
            tuple(np.rint(end).astype(int)),
            0,
            1,
        )

    result = _reconcile(page, main=[keeper, candidate])

    candidate_pieces = [
        line for line in result.lines if "SLOPED-ATTACH-B" in line.source_ids
    ]
    assert candidate_pieces
    endpoints = [point for line in candidate_pieces for point in (line.p1, line.p2)]
    assert any(np.array_equal(point, candidate.p1) for point in endpoints)
    assert any(np.array_equal(point, candidate.p2) for point in endpoints)


def test_fresh_restoration_cannot_borrow_widened_source_membership() -> None:
    page = _page()
    source = _line(10, 50, 220, 50, "SOURCE-ONLY")
    restoration = _line(20, 51.8, 210, 51.8, "OFFSET-RESTORATION")
    _draw(page, source)

    result = _reconcile(page, main=[], restorations=[restoration])

    assert not result.lines
    assert any(
        item["disposition"] == "BLOCKED"
        for item in result.ledger_payload()["supersession_ledger"]
    )


@pytest.mark.parametrize("generations", [2, 3])
def test_rejected_ancestor_tombstone_is_transitive(generations: int) -> None:
    page = _page()
    root = _line(10, 80, 220, 80, "TOMBSTONE", history=("root",))
    _draw(page, root)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=None,
        scale=1.0,
    )
    parent = root
    descendants: list[LineSegment] = []
    for generation in range(generations):
        child = parent.copy(
            x1=parent.x1 + 5,
            x2=parent.x2 - 5,
            history=(*parent.history, f"trim-{generation + 1}"),
        )
        ledger.observe_transformation(
            parent,
            child,
            parent_route=(
                RouteOrigin.MAIN if generation == 0 else RouteOrigin.RESTORATION
            ),
            child_route=RouteOrigin.RESTORATION,
            producer=f"test-transform-{generation + 1}",
            operation=LineageOperation.TRIM_TO_SOURCE_SUPPORT,
            parent_parameter_interval=(5.0, parent.length - 5.0),
        )
        descendants.append(child)
        parent = child

    result = _reconcile(
        page,
        main=[root],
        accepted_main=[],
        restorations=[descendants[-1]],
        ownership_overrides={"graphic": np.where(page < 128, 255, 0).astype(np.uint8)},
        ledger=ledger,
    )
    payload = result.ledger_payload()

    assert not result.lines
    rejected = [
        item
        for item in payload["supersession_ledger"]
        if item["disposition"] == "OWNERSHIP_REJECTED"
    ]
    assert len(rejected) >= 2
    snapshot = _route_snapshot(payload)
    assert len(snapshot["transformations"]) == generations
    observations = {item["observation_id"] for item in snapshot["observed"]}
    assert all(
        item["parent_observation_id"] in observations
        and item["child_observation_id"] in observations
        for item in snapshot["transformations"]
    )


def test_protection_rejection_tombstone_is_transitive() -> None:
    page = _page()
    root = _line(10, 85, 220, 85, "PROTECTION-TOMBSTONE")
    child = root.copy(x1=20, x2=210, history=("protected-trim",))
    grandchild = child.copy(x1=30, x2=200, history=(*child.history, "grandchild"))
    _draw(page, root)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=None,
        scale=1.0,
    )
    ledger.observe_transformation(
        root,
        child,
        parent_route=RouteOrigin.MAIN,
        child_route=RouteOrigin.RESTORATION,
        producer="protected-trim-one",
        operation=LineageOperation.TRIM_TO_SOURCE_SUPPORT,
        parent_parameter_interval=(10.0, 200.0),
    )
    ledger.observe_transformation(
        child,
        grandchild,
        parent_route=RouteOrigin.RESTORATION,
        child_route=RouteOrigin.RESTORATION,
        producer="protected-trim-two",
        operation=LineageOperation.TRIM_TO_SOURCE_SUPPORT,
        parent_parameter_interval=(10.0, 180.0),
    )
    ledger.record_prefilter_rejection(
        root,
        route=RouteOrigin.MAIN,
        reason="EXPLICIT_PROTECTION_REJECTION",
        disposition=TerminalDisposition.REJECTED_PROTECTION,
    )

    result = _reconcile(page, main=[], restorations=[grandchild], ledger=ledger)

    assert not result.lines
    record = reconciliation._gap_extent_extension(result.ledger_payload())
    assert any(
        cell["disposition"] == "REJECTED_PROTECTION"
        for parent in record["parents"]
        for cell in parent["partition"]
    )


@pytest.mark.parametrize("boundary", ["protected", "semantic_owner"])
def test_relation_cells_split_at_local_authority_boundaries(boundary: str) -> None:
    page = _page()
    keeper = _line(10, 60, 220, 60, "BOUNDARY-A")
    candidate = _line(20, 60, 210, 60, "BOUNDARY-B")
    _draw(page, keeper)
    mask = np.zeros_like(page)
    mask[59:62, 100:121] = 255
    protected = mask if boundary == "protected" else None
    ownership = {"text": mask} if boundary == "semantic_owner" else None

    result = _reconcile(
        page,
        main=[keeper, candidate],
        protected=protected,
        ownership_overrides=ownership,
    )
    cells = result.ledger_payload()["cells"]

    assert len(result.lines) == 2
    assert not [
        cell
        for cell in cells
        if cell["interval"]["start"] < 80 and cell["interval"]["end"] > 101
    ]
    assert all(isinstance(cell["endpoint_obligations_clear"], bool) for cell in cells)


def test_relation_cells_split_at_endpoint_transition() -> None:
    page = _page()
    first = _line(20, 65, 210, 65, "ENDPOINT-CELL-A")
    second = _line(20, 65, 210, 65, "ENDPOINT-CELL-B")
    _draw(page, first)

    result = _reconcile(page, main=[first, second])
    cells = result.ledger_payload()["cells"]

    assert len(cells) >= 3
    assert cells[0]["interval"]["end"] < cells[-1]["interval"]["start"]
    assert all("endpoint_obligations_clear" in cell for cell in cells)


def test_explicit_transform_lineage_preserves_original_observation() -> None:
    page = _page()
    root = _line(10, 90, 220, 90, "LINEAGE", history=("original",))
    child = root.copy(x1=20, x2=210, history=(*root.history, "trim"))
    _draw(page, root)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=None,
        scale=1.0,
    )
    ledger.observe_transformation(
        root,
        child,
        parent_route=RouteOrigin.MAIN,
        child_route=RouteOrigin.MAIN,
        producer="test-explicit-trim",
        operation=LineageOperation.TRIM_TO_SOURCE_SUPPORT,
        parent_parameter_interval=(10.0, 200.0),
    )

    result = _reconcile(page, main=[child], ledger=ledger)
    payload = result.ledger_payload()
    snapshot = _route_snapshot(payload)
    original = next(
        item for item in snapshot["observed"] if item["line"]["history"] == ["original"]
    )
    transformed = next(
        item for item in snapshot["observed"] if item["line"]["history"][-1] == "trim"
    )
    transform = snapshot["transformations"][0]
    assert transform["parent_observation_id"] == original["observation_id"]
    assert transform["child_observation_id"] == transformed["observation_id"]
    assert transform["parent_parameter_interval"] == [10.0, 200.0]
    assert transform["child_geometry_px"]["start"] == [20.0, 90.0]
    result.assert_complete(result.lines)


def _route_snapshot(payload):
    return next(
        item["measurements"]["route_ledger"]
        for item in payload["evidence"]
        if item["artifact"] == "runtime-route-ledger-snapshot"
    )


def _repack_result(result, payload, **changes):
    ledger_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return replace(
        result,
        ledger_json=ledger_json,
        ledger_digest=hashlib.sha256(ledger_json.encode("utf-8")).hexdigest(),
        **changes,
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate_terminal",
        "rejected_but_emitted",
        "unknown_parent",
        "missing_ancestry",
        "false_final_main_digest",
        "wrong_ownership_state",
        "piece_geometry_interval_mismatch",
        "wrong_keeper_coverage",
        "claim_counter_falsification",
    ],
)
def test_semantic_transaction_corruption_fails_closed(corruption: str) -> None:
    page = _page()
    keeper = _line(20, 110, 180, 110, "TX-KEEPER")
    candidate = _line(80, 110, 120, 110, "TX-CANDIDATE")
    _draw(page, keeper)
    result = _reconcile(page, main=[keeper, candidate])
    payload = result.ledger_payload()
    if corruption == "duplicate_terminal":
        payload["supersession_ledger"].append(dict(payload["supersession_ledger"][0]))
    elif corruption == "rejected_but_emitted":
        payload["supersession_ledger"][0]["disposition"] = "REJECTED_OWNERSHIP"
        payload["representations"][0]["ownership_state"] = "MAIN_REJECTED"
    elif corruption == "unknown_parent":
        payload["pieces"][0]["parent_id"] = "MISSING-PARENT"
    elif corruption == "missing_ancestry":
        payload["representations"][0]["parent_ids"] = ["MISSING-ANCESTOR"]
    elif corruption == "false_final_main_digest":
        payload["final_main_set_digest"] = "0" * 64
    elif corruption == "wrong_ownership_state":
        payload["representations"][0]["ownership_state"] = "MAIN_REJECTED"
    elif corruption == "piece_geometry_interval_mismatch":
        payload["pieces"][0]["geometry_px"]["start"][0] += 1.0
        endpoint_id = payload["pieces"][0]["start_endpoint_id"]
        next(
            item for item in payload["endpoints"] if item["endpoint_id"] == endpoint_id
        )["point_px"][0] += 1.0
    elif corruption == "wrong_keeper_coverage":
        target = next(item for item in payload["cells"] if item["retained_ids"])
        target["retained_ids"] = ["MISSING-KEEPER"]
    elif corruption == "claim_counter_falsification":
        payload["pieces"][0]["new_source_claim_pixels"] += 1

    corrupted = _repack_result(result, payload)
    with pytest.raises(AssertionError):
        corrupted.assert_complete(corrupted.lines)


def test_coherent_stale_ledger_with_new_final_lines_fails_closed() -> None:
    page = _page()
    line = _line(20, 120, 180, 120, "STALE")
    _draw(page, line)
    result = _reconcile(page, main=[line])
    changed = (result.lines[0].copy(y1=121.0, y2=121.0),)
    corrupted = replace(
        result,
        lines=changed,
        final_set_digest=reconciliation._lines_digest(changed),
    )

    with pytest.raises(AssertionError):
        corrupted.assert_complete(changed)


def test_positive_tail_5e_10_is_preserved_before_exportability_collapse() -> None:
    page = _page()
    keeper = _line(20, 130, 150, 130, "TAIL-5E10-A")
    candidate = _line(20, 130, 150.0000000005, 130, "TAIL-5E10-B")
    _draw(page, keeper)

    result = _reconcile(page, main=[keeper, candidate])

    assert len(result.lines) == 2
    assert any(line.x2 == candidate.x2 for line in result.lines)


def test_standalone_certificate_preserves_any_positive_uncovered_tail() -> None:
    page = _page()
    source = _line(5, 140, 230, 140, "STANDALONE-SOURCE")
    keeper = _line(10, 140, 180, 140, "STANDALONE-A")
    candidate = _line(30, 140, 180.0000005, 140, "STANDALONE-B")
    _draw(page, source)

    output = suppress_parallel_duplicate_detections(
        [keeper, candidate],
        gray=page,
        scale=1.0,
    )

    assert any(line.x2 == candidate.x2 for line in output)


def test_standalone_restoration_coverage_preserves_positive_tail() -> None:
    page = _page()
    base = _line(20, 150, 180, 150, "RESTORE-BASE")
    candidate = _line(20, 150, 180.0000005, 150, "RESTORE-TAIL")
    _draw(page, candidate)

    prepared = _prepare_late_restorations(
        [candidate],
        [base],
        gray=page,
        scale=1.0,
    )

    assert prepared == (candidate,)
