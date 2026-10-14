from __future__ import annotations

import cv2
import numpy as np

from app.geometry.connectivity_safety import evaluate_structural_bridge
from app.geometry.line_detect import LineSegment
from app.geometry.optimized_trace import trace_image_optimized
from app.geometry.straight_line_reconstruction import extend_lines_to_first_intersection
from app.geometry.structural_roi import StructuralRoi, detect_structural_rois


def test_optimized_trace_never_runs_closing_or_hough_gap(
    monkeypatch,
) -> None:
    image = np.full((320, 480, 3), 255, np.uint8)
    cv2.rectangle(image, (30, 30), (450, 290), (0, 0, 0), 3)
    cv2.line(image, (100, 160), (210, 160), (0, 0, 0), 3)
    cv2.line(image, (220, 160), (380, 160), (0, 0, 0), 3)
    morphology_operations: list[int] = []
    hough_gaps: list[int] = []
    original_morphology = cv2.morphologyEx
    original_hough = cv2.HoughLinesP

    def observe_morphology(source, operation, kernel, *args, **kwargs):
        morphology_operations.append(int(operation))
        return original_morphology(source, operation, kernel, *args, **kwargs)

    def observe_hough(*args, **kwargs):
        hough_gaps.append(int(kwargs["maxLineGap"]))
        return original_hough(*args, **kwargs)

    monkeypatch.setattr(cv2, "morphologyEx", observe_morphology)
    monkeypatch.setattr(cv2, "HoughLinesP", observe_hough)

    result = trace_image_optimized(image)

    assert result.final_structure is not None
    assert cv2.MORPH_CLOSE not in morphology_operations
    assert hough_gaps
    assert set(hough_gaps) == {0}
    assert not any(
        operation in line.history
        for line in result.straight_lines
        for operation in (
            "snap_endpoints",
            "merge_collinear",
            "collapse_scan_parallel_duplicate",
        )
    )




def test_connectivity_judgment_runs_on_the_roi_crop(monkeypatch) -> None:
    page = np.zeros((1000, 1200), dtype=np.uint8)
    lines = [
        LineSegment(110.0, 150.0, 150.0, 150.0),
        LineSegment(170.0, 150.0, 200.0, 150.0),
    ]
    for line in lines:
        cv2.line(
            page,
            (int(line.x1), int(line.y1)),
            (int(line.x2), int(line.y2)),
            255,
            1,
            cv2.LINE_8,
        )
    roi = StructuralRoi(
        roi_id="table-001",
        purpose="table",
        bbox=(100, 100, 120, 100),
        line_indices=(0, 1),
        evidence_intersections=(),
        confidence=1.0,
        expansion_distance=20.0,
        source_types=("local_endpoint_corridor",),
    )
    observed_shapes: list[tuple[int, int]] = []
    original = cv2.connectedComponents

    def observe_components(mask, *args, **kwargs):
        observed_shapes.append(tuple(mask.shape))
        return original(mask, *args, **kwargs)

    monkeypatch.setattr(
        "app.geometry.connectivity_safety.cv2.connectedComponents",
        observe_components,
    )

    decision = evaluate_structural_bridge(
        roi=roi,
        lines=lines,
        source_line_index=0,
        target_line_index=1,
        start=(150.0, 150.0),
        end=(170.0, 150.0),
        maximum_gap=20.0,
        source_dpi=300.0,
        source_foreground=page,
        protected_mask=None,
    )

    assert decision.allowed
    assert decision.component_count_before == 2
    assert decision.component_count_after == 1
    assert observed_shapes
    assert set(observed_shapes) == {(100, 120)}


def test_connection_context_is_built_once_per_structural_roi(
    monkeypatch,
) -> None:
    lines = [
        LineSegment(14.0, 10.0, 86.0, 10.0),
        LineSegment(14.0, 50.0, 86.0, 50.0),
        LineSegment(10.0, 14.0, 10.0, 46.0),
        LineSegment(90.0, 14.0, 90.0, 46.0),
    ]
    foreground = np.zeros((80, 110), dtype=np.uint8)
    for line in lines:
        cv2.line(
            foreground,
            (int(line.x1), int(line.y1)),
            (int(line.x2), int(line.y2)),
            255,
            1,
        )
    rois = detect_structural_rois(
        lines,
        image_shape=foreground.shape,
        extension_budget=8.0,
    )
    calls: list[str] = []
    from app.geometry import straight_line_reconstruction as reconstruction

    original = reconstruction.build_structural_connectivity_context

    def observe_context(*, roi, **kwargs):
        calls.append(roi.roi_id)
        return original(roi=roi, **kwargs)

    monkeypatch.setattr(
        reconstruction,
        "build_structural_connectivity_context",
        observe_context,
    )

    resolved = extend_lines_to_first_intersection(
        lines,
        maximum_extension=8.0,
        structural_rois=rois,
        source_foreground=foreground,
    )

    assert len(resolved) == len(lines)
    assert calls == ["frame-001"]
