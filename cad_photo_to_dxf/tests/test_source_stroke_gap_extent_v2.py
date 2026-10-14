from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import cv2
import numpy as np
import pytest

import app.geometry.source_stroke_reconciliation as reconciliation
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.geometry.raster_trace import RasterTraceResult
from app.geometry.source_stroke_reconciliation import GAP_EXTENT_MEASUREMENT_SLOT, LEGACY_ACCEPTED_HISTORY, ReconciliationLedger
from app.export.trace_dxf_entities import add_straight_line_entities
from app.core.cache import TRACE_CACHE_VERSION, load_trace_cache, save_trace_cache


def _line(
    start: tuple[float, float],
    end: tuple[float, float],
    source_id: str = "RESTORE",
    *,
    legacy: bool = True,
) -> LineSegment:
    return LineSegment(
        *start,
        *end,
        source_ids=(source_id,),
        history=(LEGACY_ACCEPTED_HISTORY,) if legacy else (),
    )


def _point(line: LineSegment, distance: float) -> tuple[int, int]:
    tangent = (line.p2 - line.p1) / line.length
    point = line.p1 + tangent * distance
    return int(round(float(point[0]))), int(round(float(point[1])))


def _gapped_result(
    line: LineSegment,
    *,
    left_end: float,
    right_start: float,
    shape: tuple[int, int] = (240, 260),
    gray_override: int | None = None,
    protected_gap: bool = False,
    main: tuple[LineSegment, ...] = (),
):
    page = np.full(shape, 255, dtype=np.uint8)
    cv2.line(page, _point(line, 0.0), _point(line, left_end), 0, 1, cv2.LINE_8)
    cv2.line(
        page,
        _point(line, right_start),
        _point(line, line.length),
        0,
        1,
        cv2.LINE_8,
    )
    if gray_override is not None:
        cv2.line(
            page,
            _point(line, left_end + 1.0),
            _point(line, right_start - 1.0),
            int(gray_override),
            1,
            cv2.LINE_8,
        )
    protected = np.zeros_like(page)
    if protected_gap:
        cv2.line(
            protected,
            _point(line, left_end + 1.0),
            _point(line, right_start - 1.0),
            255,
            5,
            cv2.LINE_8,
        )
    ownership = np.where(page < 128, 255, 0).astype(np.uint8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=protected,
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=main,
        accepted_main=main,
        restoration_candidates=(line,),
        accepted_restorations=(line,),
        ownership_masks={"line": ownership},
    )
    return page, result


def _extension(payload: dict[str, object]) -> dict[str, object]:
    snapshot = next(
        item
        for item in payload["evidence"]
        if item["artifact"] == "runtime-route-ledger-snapshot"
    )
    return snapshot["measurements"][GAP_EXTENT_MEASUREMENT_SLOT]


def _semantic_errors(result, payload: dict[str, object]) -> list[str]:
    return reconciliation._semantic_transaction_errors(
        payload,
        final_lines=result.lines,
        final_piece_ids=result.final_piece_ids,
        expected_final_digest=result.final_set_digest,
        context=result._validation_context,
    )


@pytest.mark.parametrize(
    ("line", "left_end", "right_start", "shape"),
    [
        (_line((45, 90), (185, 90)), 55.0, 66.0, (220, 240)),
        (_line((35, 35), (175, 105)), 60.0, 75.0, (180, 220)),
        (_line((30, 150), (230, 150)), 80.0, 96.0, (220, 280)),
    ],
    ids=("translated", "rotated", "scaled"),
)
def test_visible_gap_variants_are_measured_on_actual_parent_trajectory(
    line: LineSegment,
    left_end: float,
    right_start: float,
    shape: tuple[int, int],
) -> None:
    _page, result = _gapped_result(
        line,
        left_end=left_end,
        right_start=right_start,
        shape=shape,
    )
    record = _extension(result.ledger_payload())
    gaps = record["gap_observations"]

    assert gaps
    assert all(gap["cause_hypothesis"] == "UNKNOWN_GAP" for gap in gaps)
    assert all(gap["continuation_repair_refs"] == [] for gap in gaps)
    retained = [item for item in result.lines if item.source_ids == line.source_ids]
    assert len(retained) == 2
    assert retained[-1].p2 == pytest.approx(line.p2)


@pytest.mark.parametrize("uncertainty", ("threshold", "covered"))
def test_uncertain_gap_boundary_is_unknown_and_accepted_extent_survives(
    uncertainty: str,
) -> None:
    line = _line((40, 80), (190, 80))
    _page, result = _gapped_result(
        line,
        left_end=65.0,
        right_start=78.0,
        gray_override=200 if uncertainty == "threshold" else None,
        protected_gap=uncertainty == "covered",
    )

    assert len(result.lines) == 1
    assert result.lines[0].p1 == pytest.approx(line.p1)
    assert result.lines[0].p2 == pytest.approx(line.p2)
    assert _extension(result.ledger_payload())["gap_observations"] == []


def test_accepted_unknown_exterior_tail_is_never_dropped() -> None:
    page = np.full((180, 240), 255, dtype=np.uint8)
    line = _line((30, 70), (210, 70))
    cv2.line(page, (30, 70), (120, 70), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        accepted_restorations=(line,),
        ownership_masks={"line": np.where(page < 128, 255, 0).astype(np.uint8)},
    )

    assert result.lines[-1].p2 == pytest.approx(line.p2)
    parent = next(
        item
        for item in _extension(result.ledger_payload())["parents"]
        if item["acceptance_status"] == "ALREADY_ACCEPTED"
    )
    assert any(
        cell["disposition"] == "RETAINED_ACCEPTED_UNRESOLVED_EXTENT"
        for cell in parent["partition"]
    )


def test_gap_outside_equivalence_retrieval_cell_is_still_accounted() -> None:
    restoration = _line((50, 110), (220, 110))
    keeper = _line((20, 110), (100, 110), "KEEPER", legacy=False)
    _page, result = _gapped_result(
        restoration,
        left_end=90.0,
        right_start=105.0,
        main=(keeper,),
    )

    record = _extension(result.ledger_payload())
    restoration_parent = next(
        parent for parent in record["parents"] if "RESTORE" in parent["parent_id"]
    )
    assert any(
        cell["disposition"] == "SUPERSEDED_EQUIVALENT_REPRESENTATION"
        for cell in restoration_parent["partition"]
    )
    assert any(
        cell["disposition"] == "SOURCE_VISIBLE_GAP"
        for cell in restoration_parent["partition"]
    )
    assert result.lines[-1].x2 == pytest.approx(220.0)


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate_cell",
        "missing_cell",
        "overlap_cell",
        "equal_length_wrong_location",
        "wrong_source_hash",
        "wrong_scope_hash",
        "stale_evidence",
        "missing_evidence",
    ),
)
def test_v2_accounting_and_digest_corruption_fails_closed(mutation: str) -> None:
    line = _line((40, 100), (200, 100))
    _page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    payload = result.ledger_payload()
    record = _extension(payload)
    parent = next(
        item for item in record["parents"] if item["acceptance_status"] == "ALREADY_ACCEPTED"
    )
    cells = parent["partition"]
    if mutation == "duplicate_cell":
        cells.append(deepcopy(cells[0]))
    elif mutation == "missing_cell":
        cells.pop(0)
    elif mutation == "overlap_cell":
        cells[1]["parent_interval"]["start"] = cells[0]["parent_interval"]["start"]
    elif mutation == "equal_length_wrong_location":
        interval = cells[0]["parent_interval"]
        interval["start"] += 1.0
        interval["end"] += 1.0
    elif mutation == "wrong_source_hash":
        record["source"]["source_sha256"] = "f" * 64
    elif mutation == "wrong_scope_hash":
        record["accepted_set_digest"] = "e" * 64
    elif mutation == "stale_evidence":
        record["gap_observations"][0][
            "actual_trajectory_and_footprint_measurement"
        ]["sha256"] = "d" * 64
    else:
        snapshot = next(
            item
            for item in payload["evidence"]
            if item["artifact"] == "runtime-route-ledger-snapshot"
        )
        del snapshot["measurements"][GAP_EXTENT_MEASUREMENT_SLOT]

    errors = _semantic_errors(result, payload)
    assert errors
    if mutation == "missing_evidence":
        assert any("AUDIT_UNAVAILABLE" in error for error in errors)


def test_keeper_rejected_after_certification_cannot_discharge_extent() -> None:
    page = np.full((180, 240), 255, dtype=np.uint8)
    keeper = _line((20, 60), (210, 60), "KEEPER", legacy=False)
    candidate = _line((60, 60), (170, 60), "CANDIDATE")
    cv2.line(page, (20, 60), (210, 60), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(keeper,),
        accepted_main=(keeper,),
        restoration_candidates=(candidate,),
        ownership_masks={"line": np.where(page < 128, 255, 0).astype(np.uint8)},
    )
    payload = result.ledger_payload()
    keeper_piece = next(
        piece for piece in payload["pieces"] if piece["parent_id"].startswith("MAIN:")
    )
    keeper_piece["action"] = "BLOCK_AND_REVIEW"

    assert _semantic_errors(result, payload)


def test_positive_piece_and_original_endpoint_adjacent_to_gap_survive() -> None:
    line = _line((50, 140), (90.5, 140))
    _page, result = _gapped_result(line, left_end=25.0, right_start=39.0)
    pieces = [item for item in result.lines if item.source_ids == line.source_ids]

    assert len(pieces) == 2
    assert 0.0 < pieces[-1].length < 3.0
    assert pieces[-1].p2 == pytest.approx(line.p2)


def test_post_validation_mutations_cannot_reach_consumer_unnoticed() -> None:
    line = _line((40, 100), (200, 100))
    _page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    committed = result.commit()

    assert isinstance(committed, tuple)
    with pytest.raises(AttributeError):
        committed.append(line)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        committed.remove(committed[0])  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        committed[0] = line  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        committed[0].x1 = 999.0  # type: ignore[misc]
    with pytest.raises(AssertionError):
        result.assert_complete(tuple(reversed(committed)))
    with pytest.raises(AssertionError):
        result.assert_complete((*committed, line))
    with pytest.raises(AssertionError):
        result.assert_complete(committed[1:])
    with pytest.raises(AssertionError):
        result.assert_complete((line, *committed[1:]))


def test_actual_optimized_trace_finalstructure_boundary_consumes_commit_directly() -> None:
    source = (
        Path(__file__).parents[1] / "app" / "geometry" / "optimized_trace.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_final_structure"
    ]
    assert len(calls) == 1
    straight_lines = next(
        keyword.value
        for keyword in calls[0].keywords
        if keyword.arg == "straight_lines"
    )
    assert isinstance(straight_lines, ast.Call)
    assert isinstance(straight_lines.func, ast.Attribute)
    assert straight_lines.func.attr == "commit"
    assert isinstance(straight_lines.func.value, ast.Name)
    assert straight_lines.func.value.id == "final_line_authority"


class _Layout:
    def __init__(self) -> None:
        self.lines: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def add_line(self, start, end, dxfattribs=None):
        self.lines.append((tuple(start), tuple(end)))
        return {"start": start, "end": end, "attrs": dxfattribs}


def test_cache11_preview_and_dxf_consume_exact_committed_payload(tmp_path) -> None:
    line = _line((40, 100), (200, 100))
    page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    committed = result.commit()
    structure = build_final_structure(
        source_size_px=(page.shape[1], page.shape[0]),
        contour_binary=page,
        contours=(),
        straight_lines=committed,
        preview_binary=page,
        observations=(
            {
                "event": "source_stroke_reconciliation",
                "ledger_digest": result.ledger_digest,
                "ledger": result.ledger_payload(),
            },
        ),
    )
    trace = RasterTraceResult(
        binary=page,
        stages={},
        paths=(),
        threshold=128,
        foreground_pixels=int(np.count_nonzero(page < 128)),
        vertex_count=0,
        straight_lines=committed,
        preview_binary=page,
        final_structure=structure,
    )
    stored = load_trace_cache(save_trace_cache(tmp_path / "v2-gap-cache.npz", trace))
    layout = _Layout()
    count, _entities, _bounds = add_straight_line_entities(
        layout,
        structure.straight_lines,
        transform=lambda x, y: (x, y),
    )

    # D-011 changed storage versions, not the committed source-gap payload.
    assert FINAL_STRUCTURE_SCHEMA_VERSION == 4
    assert TRACE_CACHE_VERSION == 11
    assert structure.arcs == ()
    assert structure.straight_lines == committed
    assert structure.preview_binary is not None
    assert stored.final_structure is not None
    assert stored.final_structure.straight_lines == committed
    assert count == len(committed) == len(layout.lines)
