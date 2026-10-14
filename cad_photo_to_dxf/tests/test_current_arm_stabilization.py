from __future__ import annotations

import numpy as np

import app.geometry.source_stroke_reconciliation as reconciliation
from app.geometry.line_detect import LineSegment


def test_parent_child_geometry_accepts_only_roundoff_scale_difference() -> None:
    expected = LineSegment(
        754.2218629419685,
        585.6249423879286,
        754.479797512281,
        113.12505682884658,
        width=3.5,
    )
    roundoff_payload = reconciliation._geometry_payload(expected)
    roundoff_payload["end"][1] = 113.1250568288466

    assert reconciliation._geometry_payload_matches_line(
        roundoff_payload,
        expected,
    )

    displaced_payload = reconciliation._geometry_payload(expected)
    displaced_payload["end"][1] += 1e-6
    assert not reconciliation._geometry_payload_matches_line(
        displaced_payload,
        expected,
    )


def test_continuous_footprint_pixel_union_is_complete_and_sorted() -> None:
    line = LineSegment(10.25, 20.5, 180.75, 37.25, width=4.0)
    page = np.full((80, 220), 255, dtype=np.uint8)
    empty = np.zeros_like(page)
    ownership = {
        "line": empty.copy(),
        "text": empty.copy(),
        "logo": empty.copy(),
        "signature": empty.copy(),
        "graphic": empty.copy(),
        "residual": empty.copy(),
    }
    records = reconciliation._complete_claim_footprint_records(
        line,
        gray=page,
        binary=page,
        protected_mask=empty,
        ownership_masks=ownership,
    )

    segments = reconciliation._continuous_footprint_segments(line, records)
    covered = {
        tuple(pixel)
        for segment in segments
        for pixel in segment["claim_footprint_pixels"]
    }
    expected = {tuple(record["pixel"]) for record in records}

    assert len(segments) == 1
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == line.length
    assert segments[0]["claim_footprint_pixels"] == [
        list(pixel) for pixel in sorted(expected)
    ]
    assert covered == expected
    assert all(
        segment["claim_footprint_pixels"]
        == sorted(segment["claim_footprint_pixels"])
        for segment in segments
    )
    assert all(
        segment["observation"] == "SOURCE_VISIBLE_GAP"
        for segment in segments
    )
