from __future__ import annotations

from copy import deepcopy

import cv2
import numpy as np

import app.geometry.source_stroke_reconciliation as rec
from app.geometry.line_detect import LineSegment


def _line(x2: float, source_id: str) -> LineSegment:
    return LineSegment(10.0, 30.0, x2, 30.0, width=2.0, source_ids=(source_id,))


def _arguments():
    page = np.full((80, 100), 255, dtype=np.uint8)
    page[29:32, 8:82] = 0
    zero = np.zeros_like(page)
    masks = {key: zero for key in ("line", "text", "logo", "signature", "graphic", "residual")}
    return page, zero, masks


def test_exact_pair_result_is_reused_only_within_bound_snapshot() -> None:
    page, protected, masks = _arguments()
    cache = rec._ReconciliationEvidenceCache.create("source", "ownership", "protection", rec.POLICY_VERSION)
    kwargs = {
        "left_id": "left",
        "right_id": "right",
        "gray": page,
        "binary": page,
        "scale": 1.0,
        "protected_mask": protected,
        "ownership_masks": masks,
        "evidence_cache": cache,
    }
    first = rec._certify_pair_cells(_line(80.0, "A"), _line(70.0, "B"), **kwargs)
    second = rec._certify_pair_cells(_line(80.0, "A"), _line(70.0, "B"), **kwargs)

    assert second is first
    assert cache.counters["pair_misses"] == 1
    assert cache.counters["pair_hits"] == 1
    other_snapshot = rec._ReconciliationEvidenceCache.create("other-source", "ownership", "protection", rec.POLICY_VERSION)
    rec._certify_pair_cells(
        _line(80.0, "A"),
        _line(70.0, "B"),
        **{**kwargs, "evidence_cache": other_snapshot},
    )
    assert other_snapshot.counters == {
        "pair_misses": 1,
        "claim_mask_misses": 2,
        "footprint_misses": 2,
    }


def test_positive_binary64_geometry_delta_never_shares_pair_evidence() -> None:
    page, protected, masks = _arguments()
    cache = rec._ReconciliationEvidenceCache.create("source", "ownership", "protection", rec.POLICY_VERSION)
    common = {
        "left_id": "left",
        "right_id": "right",
        "gray": page,
        "binary": page,
        "scale": 1.0,
        "protected_mask": protected,
        "ownership_masks": masks,
        "evidence_cache": cache,
    }
    rec._certify_pair_cells(_line(80.0, "A"), _line(70.0, "B"), **common)
    rec._certify_pair_cells(_line(80.0, "A"), _line(70.0 + 1e-10, "B"), **common)

    assert cache.counters["pair_misses"] == 2
    assert cache.counters.get("pair_hits", 0) == 0


def test_ownership_state_is_part_of_pair_cache_key() -> None:
    page, protected, masks = _arguments()
    cache = rec._ReconciliationEvidenceCache.create("source", "ownership", "protection", rec.POLICY_VERSION)
    common = {
        "left_id": "left",
        "right_id": "right",
        "gray": page,
        "binary": page,
        "scale": 1.0,
        "protected_mask": protected,
        "ownership_masks": masks,
        "evidence_cache": cache,
    }
    rec._certify_pair_cells(_line(80.0, "A"), _line(70.0, "B"), right_ownership_state="MAIN_ACCEPTED", **common)
    rec._certify_pair_cells(_line(80.0, "A"), _line(70.0, "B"), right_ownership_state="MAIN_REJECTED", **common)

    assert cache.counters["pair_misses"] == 2
    assert cache.counters.get("pair_hits", 0) == 0


def test_complete_support_segments_reuse_exact_trajectory_across_candidate_ids() -> None:
    page, protected, masks = _arguments()
    cache = rec._ReconciliationEvidenceCache.create("source", "ownership", "protection", rec.POLICY_VERSION)
    common = {
        "gray": page,
        "binary": page,
        "protected_mask": protected,
        "ownership_masks": masks,
        "evidence_cache": cache,
    }
    first = rec._source_visible_gap_certificates(_line(80.0, "A"), representation_id="A", **common)
    second = rec._source_visible_gap_certificates(_line(80.0, "B"), representation_id="B", **common)

    assert [item["certified_absent_interval"] for item in first] == [
        item["certified_absent_interval"] for item in second
    ]
    assert cache.counters["footprint_misses"] == 1
    assert cache.counters["footprint_hits"] == 1
    assert cache.counters["support_segment_misses"] == 1
    assert cache.counters["support_segment_hits"] == 1


def test_support_segments_do_not_share_positive_geometry_delta() -> None:
    page, protected, masks = _arguments()
    cache = rec._ReconciliationEvidenceCache.create("source", "ownership", "protection", rec.POLICY_VERSION)
    common = {
        "gray": page,
        "binary": page,
        "protected_mask": protected,
        "ownership_masks": masks,
        "evidence_cache": cache,
    }
    rec._source_visible_gap_certificates(_line(80.0, "A"), representation_id="A", **common)
    rec._source_visible_gap_certificates(_line(80.0 + 1e-10, "A"), representation_id="A2", **common)

    assert cache.counters["footprint_misses"] == 2
    assert cache.counters.get("footprint_hits", 0) == 0
    assert cache.counters["support_segment_misses"] == 2
    assert cache.counters.get("support_segment_hits", 0) == 0


def _route_record_case(monkeypatch, *, offset=0, reverse=False):
    page = np.full((100, 120), 255, np.uint8)
    first = LineSegment(10, 25+offset, 95, 25+offset, width=1, source_ids=('first',))
    second = LineSegment(10, 60+offset, 95, 60+offset, width=1, source_ids=('second',))
    for line in (first, second):
        cv2.line(page, (int(line.x1), int(line.y1)), (int(line.x2), int(line.y2)), 0, 1)
    lines = (second, first) if reverse else (first, second)
    ledger = rec.ReconciliationLedger(source_gray=page, source_binary=page,
        protected_mask=np.zeros_like(page), scale=1)
    captured = []
    build = rec._build_gap_extent_v2_record

    def capture(payload, **kwargs):
        captured.append((deepcopy(payload), kwargs))
        return build(payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(rec, '_build_gap_extent_v2_record', capture)
        result = ledger.reconcile(main_candidates=lines, accepted_main=lines,
                                  restoration_candidates=(), ownership_masks={})
    return result, captured[0]


def test_route_snapshot_is_decoded_once_per_record_and_has_no_shared_mutable_state(monkeypatch):
    _result, (payload, kwargs) = _route_record_case(monkeypatch)
    route = kwargs['context'].route_ledger_json
    loads = rec.json.loads
    decoded = []

    def capture_load(value, *args, **options):
        result = loads(value, *args, **options)
        if value is route:
            decoded.append(result)
        return result

    original_payload = deepcopy(payload)
    with monkeypatch.context() as patch:
        patch.setattr(rec.json, 'loads', capture_load)
        record = rec._build_gap_extent_v2_record(payload, **kwargs)
    assert len(record['parents']) == 2 and len(decoded) == 1
    # A caller that modifies the output, or an observer that retains decoded
    # data, cannot affect the sealed input or a subsequent record build.
    baseline = deepcopy(record)
    record['parents'][0]['lineage']['parent_ids'].append('output-only')
    decoded[0]['observed'].clear()
    assert kwargs['context'].route_ledger_json == route
    assert rec._build_gap_extent_v2_record(original_payload, **kwargs) == baseline


def test_route_snapshot_reuse_does_not_cross_pages_or_change_input_order(monkeypatch):
    first, first_args = _route_record_case(monkeypatch)
    reverse, _reverse_args = _route_record_case(monkeypatch, reverse=True)
    other, other_args = _route_record_case(monkeypatch, offset=4)
    assert first.lines == reverse.lines
    assert [(line.y1, line.y2) for line in first.lines] == [(25,25), (60,60)]
    assert [(line.y1, line.y2) for line in other.lines] == [(29,29), (64,64)]
    for result, (payload, kwargs) in ((first, first_args), (other, other_args)):
        record = rec._build_gap_extent_v2_record(payload, **kwargs)
        starts = [parent['original_geometry']['start_px'][1] for parent in record['parents']]
        assert starts == [line.y1 for line in result.lines]
