from __future__ import annotations

import json

import cv2
import numpy as np

from scripts import build_multiscale_structural_evidence_d7 as d7


def test_scale_windows_are_gap_stroke_and_processing_normalized() -> None:
    extents = d7._window_extents(gap_length=20.0, stroke_width=3.0, processing_scale=2.0)

    assert extents == {"LOCAL": 36, "MESO": 72, "WIDE": 144}


def test_axis_measurement_does_not_invent_support_across_blank() -> None:
    continuous = np.zeros((180, 180), dtype=np.uint8)
    blank = continuous.copy()
    cv2.line(continuous, (90, 10), (90, 170), 255, 5, cv2.LINE_8)
    cv2.line(blank, (90, 10), (90, 75), 255, 5, cv2.LINE_8)
    cv2.line(blank, (90, 105), (90, 170), 255, 5, cv2.LINE_8)
    gap = {
        "fragment_endpoints": {"first_inner": [90.0, 75.0], "second_inner": [90.0, 105.0]},
        "fragment_widths_px": [5.0, 5.0],
    }
    continuous_case = d7._case_measurement(
        "continuous", "structural", [90, 10, 90, 170], gap, continuous, continuous, 1.0
    )
    blank_case = d7._case_measurement(
        "blank", "safe_negative", [90, 10, 90, 170], gap, blank, blank, 1.0
    )

    continuous_support = continuous_case["binary"]["LOCAL"]["total_axis_support_fraction"]
    blank_support = blank_case["binary"]["LOCAL"]["total_axis_support_fraction"]
    assert continuous_support > blank_support
    assert blank_support < 1.0


def test_report_preserves_case_set_and_exposes_all_overlap() -> None:
    report = json.loads(d7.OUTPUT.read_text(encoding="utf-8"))

    assert report["production_semantic_delta"] == "NONE"
    assert report["case_set"]["structural_positives"] == list(d7.POSITIVE_IDS)
    assert report["case_set"]["hard_dimension_text_negatives"] == list(
        d7.HARD_NEGATIVE_IDS
    )
    assert len(report["diagnostic_matrix"]) == 15
    for family in report["evidence_family_analysis"].values():
        assert family["overlap_present"] is True
        assert family["non_overlapping_measurements"] == []
