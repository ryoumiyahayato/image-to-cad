from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import cv2
from jsonschema import Draft202012Validator
import numpy as np
import pytest

import app.geometry.source_stroke_reconciliation as reconciliation
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION, FinalStructure
from app.geometry.line_detect import LineSegment
from app.geometry.source_stroke_reconciliation import GAP_EXTENT_MEASUREMENT_SLOT, LEGACY_ACCEPTED_HISTORY, ReconciliationLedger, RouteOrigin, TerminalDisposition
from app.core.cache import TRACE_CACHE_VERSION


def _line(
    start: tuple[float, float],
    end: tuple[float, float],
    source_id: str = "RESTORE",
    *,
    width: float = 1.0,
    legacy: bool = False,
) -> LineSegment:
    return LineSegment(
        *start,
        *end,
        width=width,
        source_ids=(source_id,),
        history=(LEGACY_ACCEPTED_HISTORY,) if legacy else (),
    )


def _point(line: LineSegment, distance: float) -> tuple[int, int]:
    tangent = (line.p2 - line.p1) / line.length
    point = line.p1 + tangent * distance
    return int(round(float(point[0]))), int(round(float(point[1])))


def _masks(
    page: np.ndarray,
    **overrides: np.ndarray,
) -> dict[str, np.ndarray]:
    empty = np.zeros_like(page)
    result = {
        "line": np.where(page < 128, 255, 0).astype(np.uint8),
        "text": empty.copy(),
        "logo": empty.copy(),
        "signature": empty.copy(),
        "graphic": empty.copy(),
        "residual": empty.copy(),
    }
    result.update(overrides)
    return result


def _extension(payload: dict[str, object]) -> dict[str, object]:
    snapshot = next(
        item
        for item in payload["evidence"]
        if item.get("artifact") == "runtime-route-ledger-snapshot"
    )
    return snapshot["measurements"][GAP_EXTENT_MEASUREMENT_SLOT]


def _route_snapshot(payload: dict[str, object]) -> dict[str, object]:
    snapshot = next(
        item
        for item in payload["evidence"]
        if item.get("artifact") == "runtime-route-ledger-snapshot"
    )
    return snapshot["measurements"]["route_ledger"]


def _gapped_result(
    line: LineSegment,
    *,
    left_end: float,
    right_start: float,
    main: tuple[LineSegment, ...] = (),
):
    page = np.full((260, 300), 255, dtype=np.uint8)
    cv2.line(page, _point(line, 0.0), _point(line, left_end), 0, 1, cv2.LINE_8)
    cv2.line(
        page,
        _point(line, right_start),
        _point(line, line.length),
        0,
        1,
        cv2.LINE_8,
    )
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=main,
        accepted_main=main,
        restoration_candidates=(line,),
        accepted_restorations=(line,),
        ownership_masks=_masks(page),
    )
    return page, result


class _MutableLines(list):
    pass


class _LineProxy:
    def __init__(self, values):
        self._values = list(values)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


@pytest.mark.parametrize(
    "line",
    (
        _line((22.17, 61.29), (230.31, 70.19), width=4.0),
        _line((31.63, 42.41), (212.77, 91.83), width=3.2),
        _line((47.25, 202.75), (239.4, 122.6), width=5.0),
        _line((63.8, 24.2), (71.3, 229.7), width=2.4),
        _line((19.125, 181.875), (252.625, 185.375), width=4.6),
    ),
    ids=("reviewed", "rotated", "reverse-slope", "near-vertical", "fractional"),
)
def test_f01_complete_claim_footprint_accounts_for_every_production_pixel(
    line: LineSegment,
) -> None:
    shape = (280, 300)
    page = np.full(shape, 255, dtype=np.uint8)
    protected = np.zeros(shape, dtype=np.uint8)
    masks = _masks(page)
    records = reconciliation._complete_claim_footprint_records(
        line,
        gray=page,
        binary=page,
        protected_mask=protected,
        ownership_masks=masks,
    )
    recorded = {tuple(item["pixel"]) for item in records}
    claim = reconciliation._line_claim_mask(line, shape=shape)
    expected = {
        (int(x), int(y))
        for y, x in np.argwhere(claim > 0)
    }

    assert recorded == expected
    assert all(item["end"] > item["start"] for item in records)


def test_f01_reviewed_missed_source_pixel_cannot_be_certified_as_gap() -> None:
    line = _line(
        (22.17, 61.29),
        (230.31, 70.19),
        width=4.0,
        legacy=True,
    )
    shape = (150, 280)
    page = np.full(shape, 255, dtype=np.uint8)
    page[65, 120] = 0
    cv2.line(page, _point(line, 0.0), _point(line, 45.0), 0, 1, cv2.LINE_8)
    cv2.line(
        page,
        _point(line, 160.0),
        _point(line, line.length),
        0,
        1,
        cv2.LINE_8,
    )
    records = reconciliation._complete_claim_footprint_records(
        line,
        gray=page,
        binary=page,
        protected_mask=np.zeros_like(page),
        ownership_masks=_masks(page),
    )
    target = next(item for item in records if item["pixel"] == [120, 65])
    segments = reconciliation._continuous_footprint_segments(line, records)

    assert target["source"] is True
    assert not any(
        item["observation"] == "SOURCE_VISIBLE_GAP"
        and item["start"] < target["end"]
        and item["end"] > target["start"]
        for item in segments
    )


@pytest.mark.parametrize("owner", ("protected", "text"))
def test_f01_reviewed_authority_pixel_creates_unknown_boundary(owner: str) -> None:
    line = _line((22.17, 61.29), (230.31, 70.19), width=4.0)
    shape = (150, 280)
    page = np.full(shape, 255, dtype=np.uint8)
    protected = np.zeros(shape, dtype=np.uint8)
    masks = _masks(page)
    if owner == "protected":
        protected[65, 120] = 255
    else:
        masks["text"][65, 120] = 255
    records = reconciliation._complete_claim_footprint_records(
        line,
        gray=page,
        binary=page,
        protected_mask=protected,
        ownership_masks=masks,
    )
    target = next(item for item in records if item["pixel"] == [120, 65])
    segments = reconciliation._continuous_footprint_segments(line, records)

    assert any(
        item["observation"] == "UNKNOWN"
        and item["start"] < target["end"]
        and item["end"] > target["start"]
        for item in segments
    )


@pytest.mark.parametrize("rise", (2.1, 7.3, -6.7, 13.4, -11.2))
def test_f02_every_gap_only_reduction_runs_exact_claim_delta_gate(
    rise: float,
) -> None:
    line = _line((30.2, 100.4), (250.2, 100.4 + rise), legacy=True)
    page = np.full((240, 300), 255, dtype=np.uint8)
    cv2.line(page, _point(line, 0.0), _point(line, 82.0), 0, 1, cv2.LINE_8)
    cv2.line(
        page,
        _point(line, 104.0),
        _point(line, line.length),
        0,
        1,
        cv2.LINE_8,
    )
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    original = reconciliation._claim_delta_measurements

    def unauthorized_delta(parent, piece, **kwargs):
        measurement = original(parent, piece, **kwargs)
        measurement["new_protected_source_pixels"] = 1
        return measurement

    with patch.object(
        reconciliation,
        "_claim_delta_measurements",
        unauthorized_delta,
    ), pytest.raises(AssertionError, match="BLOCK_AND_REVIEW"):
        ledger.reconcile(
            main_candidates=(),
            accepted_main=(),
            restoration_candidates=(line,),
            accepted_restorations=(line,),
            ownership_masks=_masks(page),
        )


@pytest.mark.parametrize(
    ("branch", "gray_value", "binary_branch", "fractional"),
    (
        (((11, 50), (13, 48)), 200, False, False),
        (((11, 50), (14, 47)), 200, False, False),
        (((11, 50), (11, 53)), 200, False, False),
        (((199, 50), (202, 48)), 200, False, False),
        (((11, 50), (14, 47)), 0, True, False),
        (((11, 50), (14, 48)), 200, False, True),
    ),
    ids=(
        "two-pixel-faint-slanted",
        "three-pixel-faint-slanted",
        "faint-perpendicular",
        "gray-binary-disagreement",
        "dark-historical-control",
        "fractional-endpoint",
    ),
)
def test_f03_plausible_short_attachment_is_not_positive_absence(
    branch: tuple[tuple[int, int], tuple[int, int]],
    gray_value: int,
    binary_branch: bool,
    fractional: bool,
) -> None:
    gray = np.full((120, 240), 255, dtype=np.uint8)
    binary = gray.copy()
    keeper = _line((5, 50), (205, 50), "KEEPER")
    candidate = _line(
        (11.25 if fractional else 11.0, 50.0),
        (199.25 if fractional else 199.0, 50.0),
        "CANDIDATE",
    )
    cv2.line(gray, (5, 50), (205, 50), 0, 1, cv2.LINE_8)
    cv2.line(binary, (5, 50), (205, 50), 0, 1, cv2.LINE_8)
    cv2.line(gray, branch[0], branch[1], gray_value, 1, cv2.LINE_8)
    if binary_branch:
        cv2.line(binary, branch[0], branch[1], 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=gray,
        source_binary=binary,
        protected_mask=np.zeros_like(gray),
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(keeper, candidate),
        accepted_main=(keeper, candidate),
        restoration_candidates=(),
        ownership_masks=_masks(binary),
    )
    tangent = (candidate.p2 - candidate.p1) / candidate.length
    normal = np.array([-tangent[1], tangent[0]], dtype=float)
    endpoint = candidate.p1 if branch[0][0] < 100 else candidate.p2
    inward_sign = 1.0 if branch[0][0] < 100 else -1.0
    status = reconciliation._endpoint_attachment_status(
        endpoint,
        tangent=tangent,
        normal=normal,
        inward_sign=inward_sign,
        gray=gray,
        binary=binary,
    )

    assert status != "NO_ATTACHMENT_WITH_EVIDENCE"
    assert any(line.source_ids == ("CANDIDATE",) for line in result.lines)


def test_f03_clean_observable_frontier_can_clear_endpoint_obligation() -> None:
    page = np.full((120, 240), 255, dtype=np.uint8)
    keeper = _line((5, 50), (205, 50), "KEEPER")
    candidate = _line((11, 50), (199, 50), "CANDIDATE")
    cv2.line(page, (5, 50), (205, 50), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(keeper, candidate),
        accepted_main=(keeper, candidate),
        restoration_candidates=(),
        ownership_masks=_masks(page),
    )
    tangent = (candidate.p2 - candidate.p1) / candidate.length
    status = reconciliation._endpoint_attachment_status(
        candidate.p1,
        tangent=tangent,
        normal=np.array([-tangent[1], tangent[0]], dtype=float),
        inward_sign=1.0,
        gray=page,
        binary=page,
    )

    assert status == "NO_ATTACHMENT_WITH_EVIDENCE"
    assert result.lines


def test_f04_consolidation_rejection_is_interval_mapped_and_audited() -> None:
    page = np.full((390, 220), 255, dtype=np.uint8)
    raw_a = _line((100, 18), (100, 146), "RAW-A")
    raw_b = _line((100, 146), (100, 260), "RAW-B")
    raw_c = _line((100, 260), (100, 354), "RAW-C")
    consolidated = LineSegment(
        100,
        18,
        100,
        354,
        source_ids=("RAW-A", "RAW-B", "RAW-C"),
    )
    cv2.line(page, (100, 18), (100, 354), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    ledger.observe_consolidation(
        (raw_a, raw_b, raw_c),
        consolidated,
        route=RouteOrigin.MAIN,
        producer="r4-v2-many-to-one-control",
    )
    ledger.record_prefilter_rejection(
        raw_a,
        route=RouteOrigin.MAIN,
        reason="Scoped protected RAW-A extent",
        disposition=TerminalDisposition.REJECTED_PROTECTION,
    )
    result = ledger.reconcile(
        main_candidates=(consolidated,),
        accepted_main=(consolidated,),
        restoration_candidates=(),
        ownership_masks=_masks(page),
    )
    extension = _extension(result.ledger_payload())
    parent = extension["parents"][0]

    assert [(line.y1, line.y2) for line in result.lines] == [(146.0, 354.0)]
    assert parent["lineage"]["primitive_member_ids"] == [
        "RAW-A",
        "RAW-B",
        "RAW-C",
    ]
    assert len(parent["lineage"]["parent_ids"]) == 3
    assert parent["lineage"]["transform_records"][0]["role"] == (
        "EXPLICIT_MANY_TO_ONE_INTERVAL_MAPPED_ANCESTRY"
    )
    assert {cell["disposition"] for cell in parent["partition"]} == {
        "REJECTED_PROTECTION",
        "RETAINED_SOURCE_SUPPORTED_EXTENT",
    }
    assert result.commit() is result.lines


@pytest.mark.parametrize(
    "attack",
    (
        "fabricated_ownership_rejection",
        "duplicate_direct_output",
        "missing_filtered_original",
        "wrong_source_identity",
        "missing_same_evidence",
        "contradictory_same_evidence",
        "fabricated_keeper",
        "fabricated_gap",
        "fabricated_acceptance",
        "fake_rejection_authority",
    ),
)
def test_f05_coherent_ledger_attacks_fail_against_sealed_inputs(
    attack: str,
) -> None:
    restoration = _line((50, 110), (230, 110), legacy=True)
    keeper = _line((20, 110), (105, 110), "KEEPER")
    _page, result = _gapped_result(
        restoration,
        left_end=100.0,
        right_start=116.0,
        main=(keeper,),
    )
    payload = result.ledger_payload()
    extension = _extension(payload)
    route = _route_snapshot(payload)
    if attack == "fabricated_ownership_rejection":
        payload["representations"][0]["ownership_state"] = "MAIN_REJECTED"
    elif attack == "duplicate_direct_output":
        payload["pieces"].append(deepcopy(payload["pieces"][0]))
    elif attack == "missing_filtered_original":
        route["observed"].pop(0)
    elif attack == "wrong_source_identity":
        payload["source_image_sha256"] = "f" * 64
        extension["source"]["source_sha256"] = "f" * 64
    elif attack == "missing_same_evidence":
        cell = next(
            item
            for item in payload["cells"]
            if item["relation"] == "SAME_VISIBLE_STROKE_SUPPORTED"
        )
        cell["positive_evidence_refs"] = []
    elif attack == "contradictory_same_evidence":
        cell = next(
            item
            for item in payload["cells"]
            if item["relation"] == "SAME_VISIBLE_STROKE_SUPPORTED"
        )
        evidence = next(
            item
            for item in payload["evidence"]
            if item["evidence_id"] == cell["positive_evidence_refs"][0]
        )
        evidence["result"] = "CONTRADICTED"
    elif attack == "fabricated_keeper":
        cover = next(
            cover
            for parent in extension["parents"]
            for cell in parent["partition"]
            for cover in cell["equivalent_cover"]
        )
        cover["keeper_piece_id"] = "fabricated-keeper"
    elif attack == "fabricated_gap":
        extension["gap_observations"][0]["certified_absent_interval"][
            "start"
        ] -= 3.0
    elif attack == "fabricated_acceptance":
        fresh_parent = next(
            parent
            for parent in extension["parents"]
            if parent["acceptance_status"] == "ALREADY_ACCEPTED"
        )
        fresh_parent["acceptance_authorization_ref"] = "fabricated-acceptance"
    else:
        extension["authorizations"].append(
            deepcopy(extension["authorizations"][0])
        )
        extension["authorizations"][-1]["authorization_id"] = "fake-rejection"

    ledger_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    attacked = replace(
        result,
        ledger_json=ledger_json,
        ledger_digest=hashlib.sha256(ledger_json.encode("utf-8")).hexdigest(),
    )
    with pytest.raises(AssertionError, match="independently sealed"):
        attacked.assert_complete()


@pytest.mark.parametrize(
    "substitution",
    (
        lambda values: list(values),
        lambda values: _MutableLines(values),
        lambda values: _LineProxy(values),
    ),
    ids=("list", "mutable-subclass", "proxy"),
)
def test_f06_runtime_collection_substitution_fails_before_consumer(
    substitution,
) -> None:
    line = _line((40, 100), (200, 100), legacy=True)
    _page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    attacked = replace(result, lines=substitution(result.lines))

    with pytest.raises(TypeError, match="exact immutable tuple"):
        attacked.commit()


def test_f06_exact_committed_tuple_and_members_are_immutable() -> None:
    line = _line((40, 100), (200, 100), legacy=True)
    _page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    committed = result.commit()

    assert type(committed) is tuple
    assert committed is result.lines
    with pytest.raises(AttributeError):
        committed.append(line)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        committed.remove(committed[0])  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        committed[0] = line  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        committed[0].x1 = 9.0  # type: ignore[misc]


def test_f07_production_gap_validates_against_authoritative_v1_and_v2() -> None:
    line = _line((40, 100), (200, 100), legacy=True)
    _page, result = _gapped_result(line, left_end=70.0, right_start=84.0)
    payload = result.ledger_payload()
    extension = _extension(payload)
    fixtures = Path(__file__).parent / "fixtures"
    v1_schema = json.loads(
        (fixtures / "reconciliation-schema-v1.json").read_text(encoding="utf-8")
    )
    v2_schema = json.loads(
        (fixtures / "source-stroke-gap-extent-schema-v2.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(v1_schema)
    Draft202012Validator.check_schema(v2_schema)

    assert list(Draft202012Validator(v1_schema).iter_errors(payload)) == []
    assert list(Draft202012Validator(v2_schema).iter_errors(extension)) == []
    assert all(
        item["kind"] != "SOURCE_VISIBLE_GAP_OBSERVATION"
        for item in payload["evidence"]
    )
    assert extension["gap_observations"]


def test_f08_magic_history_cannot_override_text_ownership() -> None:
    page = np.full((180, 240), 255, dtype=np.uint8)
    line = _line((30, 80), (210, 80), legacy=True)
    cv2.line(page, (30, 80), (210, 80), 0, 1, cv2.LINE_8)
    text = np.where(page < 128, 255, 0).astype(np.uint8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=text,
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        ownership_masks=_masks(page, text=text),
    )
    parent = _extension(result.ledger_payload())["parents"][0]

    assert result.lines == ()
    assert parent["acceptance_status"] == "FRESH_PROPOSAL"


def test_f08_explicit_restoration_acceptance_is_sealed_and_audited() -> None:
    page = np.full((180, 240), 255, dtype=np.uint8)
    line = _line((30, 80), (210, 80))
    cv2.line(page, (30, 80), (210, 80), 0, 1, cv2.LINE_8)
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
        ownership_masks=_masks(page),
    )
    extension = _extension(result.ledger_payload())

    assert result.lines
    assert extension["parents"][0]["acceptance_status"] == "ALREADY_ACCEPTED"
    assert extension["accepted_set_digest"]
    assert extension["parents"][0]["acceptance_authorization_ref"]


def test_f09_missing_accepted_main_member_fails_closed() -> None:
    page = np.full((160, 240), 255, dtype=np.uint8)
    first = _line((20, 60), (100, 60), "A")
    omitted = _line((120, 60), (210, 60), "B")
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )

    with pytest.raises(AssertionError, match="one-to-one"):
        ledger.reconcile(
            main_candidates=(first,),
            accepted_main=(first, omitted),
            restoration_candidates=(),
            ownership_masks=_masks(page),
        )


def test_f09_duplicate_candidate_identity_fails_closed() -> None:
    page = np.full((160, 240), 255, dtype=np.uint8)
    line = _line((20, 60), (210, 60), "DUPLICATE")
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )

    with pytest.raises(AssertionError, match="one-to-one"):
        ledger.reconcile(
            main_candidates=(line, line),
            accepted_main=(line,),
            restoration_candidates=(),
            ownership_masks=_masks(page),
        )


def test_f10_fresh_graphic_owned_claim_is_blocked() -> None:
    page = np.full((180, 240), 255, dtype=np.uint8)
    line = _line((30, 80), (210, 80))
    cv2.line(page, (30, 80), (210, 80), 0, 1, cv2.LINE_8)
    graphic = np.where(page < 128, 255, 0).astype(np.uint8)
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
        ownership_masks=_masks(page, graphic=graphic),
    )

    assert result.lines == ()
    assert _extension(result.ledger_payload())["parents"][0][
        "acceptance_status"
    ] == "FRESH_PROPOSAL"


def _structure(line: LineSegment) -> FinalStructure:
    binary = np.full((64, 256), 255, dtype=np.uint8)
    structure = FinalStructure(
        source_size_px=(256, 64),
        contour_binary=binary,
        contours=(),
        straight_lines=(line,),
        preview_binary=binary,
    )
    structure.assert_valid()
    return structure


@pytest.mark.parametrize("delta", (5e-7, 8e-7, 2e-7, 5e-10, 7e-11))
def test_f11_every_positive_binary64_geometry_delta_changes_identity(
    delta: float,
) -> None:
    base = _line((0.1, 10.0), (200.0, 10.0), "IDENTITY")
    changed = base.copy(x2=base.x2 + delta)

    assert changed.x2 != base.x2
    assert _structure(changed).structure_id != _structure(base).structure_id


def test_f11_signed_zero_is_normalized_and_ids_are_deterministic() -> None:
    positive = _line((0.0, 10.0), (200.1, 10.0), "IDENTITY")
    negative = positive.copy(x1=-0.0)

    assert _structure(positive).structure_id == _structure(negative).structure_id
    assert _structure(positive).structure_id == _structure(positive).structure_id
    assert FINAL_STRUCTURE_SCHEMA_VERSION == 3
    assert TRACE_CACHE_VERSION == 10


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_f11_nonfinite_committed_geometry_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _line((10.0, 10.0), (200.0, 10.0), "NONFINITE").copy(x2=value)
