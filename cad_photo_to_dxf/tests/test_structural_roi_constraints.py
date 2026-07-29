from __future__ import annotations

import cv2
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.connectivity_safety import evaluate_structural_bridge
from app.content_ownership import build_connection_protection
from app.line_detect import LineSegment
from app.logo_detection import LogoRegion
from app.observability import roi_payload
from app.signature_overlay import SignatureRegion
from app.straight_line_reconstruction import (
    extend_lines_to_first_intersection,
)
from app.structural_roi import (
    StructuralRoi,
    detect_structural_rois,
    rasterize_structural_roi_corridor,
)


def _frame_lines() -> list[LineSegment]:
    return [
        LineSegment(14.0, 10.0, 86.0, 10.0, width=2.0),
        LineSegment(14.0, 50.0, 86.0, 50.0, width=2.0),
        LineSegment(10.0, 14.0, 10.0, 46.0, width=2.0),
        LineSegment(90.0, 14.0, 90.0, 46.0, width=2.0),
    ]


def _foreground(lines: list[LineSegment]) -> np.ndarray:
    foreground = np.zeros((80, 110), dtype=np.uint8)
    for line in lines:
        cv2.line(
            foreground,
            (int(line.x1), int(line.y1)),
            (int(line.x2), int(line.y2)),
            255,
            max(1, int(round(line.width))),
            cv2.LINE_8,
        )
    return foreground


def test_roi_payload_exposes_source_evidence_and_endpoint_corridors() -> None:
    lines = _frame_lines()
    detected = detect_structural_rois(
        lines,
        image_shape=(80, 110),
        extension_budget=8.0,
    )

    assert len(detected.rois) == 1
    payload = roi_payload(detected.rois[0], lines)

    assert payload["source_types"] == [
        "source_supported_axis_lines",
        "closed_frame_network",
        "orthogonal_intersection_network",
        "measured_line_width_and_direction",
        "local_endpoint_corridor",
    ]
    assert payload["expansion_distance"] == 8.0
    assert payload["confidence"] == 1.0
    assert payload["line_width_evidence"]["median"] == 2.0
    assert payload["orientation_evidence"]["horizontal"] == 2
    assert payload["orientation_evidence"]["vertical"] == 2
    assert len(payload["endpoint_corridors"]) == 8


def test_roi_mask_is_local_corridors_not_the_network_bbox() -> None:
    lines = _frame_lines()
    roi = detect_structural_rois(
        lines,
        image_shape=(80, 110),
        extension_budget=8.0,
    ).rois[0]

    mask = rasterize_structural_roi_corridor(
        roi,
        lines,
        image_shape=(80, 110),
    )
    x, y, width, height = roi.bbox

    assert cv2.countNonZero(mask) < width * height
    assert mask[y + height // 2, x + width // 2] == 0
    assert mask[10, 10] == 255


def test_bridge_inside_bbox_but_outside_corridor_is_rejected() -> None:
    lines = [
        LineSegment(10.0, 20.0, 40.0, 20.0),
        LineSegment(60.0, 20.0, 90.0, 20.0),
    ]
    roi = StructuralRoi(
        roi_id="table-001",
        purpose="table",
        bbox=(0, 0, 100, 100),
        line_indices=(0, 1),
        evidence_intersections=(),
        confidence=1.0,
        expansion_distance=10.0,
        source_types=("local_endpoint_corridor",),
    )
    page = _foreground(lines)

    decision = evaluate_structural_bridge(
        roi=roi,
        lines=lines,
        start=(45.0, 45.0),
        end=(55.0, 45.0),
        source_foreground=page,
        protected_mask=None,
    )

    assert not decision.allowed
    assert decision.reason_code == "outside_structural_corridor"


def test_roi_bbox_uses_exclusive_right_and_bottom_edges() -> None:
    roi = StructuralRoi(
        roi_id="frame-001",
        purpose="frame",
        bbox=(10, 20, 30, 40),
        line_indices=(),
        evidence_intersections=(),
        confidence=1.0,
    )

    assert roi.contains((10.0, 20.0))
    assert roi.contains((39.999, 59.999))
    assert not roi.contains((40.0, 30.0))
    assert not roi.contains((20.0, 60.0))


def test_connection_protection_declares_all_required_guard_categories() -> None:
    binary = np.full((100, 140), 255, dtype=np.uint8)
    binary[20:30, 15:45] = 0
    text = TextCandidate(
        "25",
        (15, 20, 30, 10),
        0.99,
        "dimension_text_candidate",
        source="test",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )
    logo = LogoRegion(
        bbox=(60, 15, 20, 20),
        mask=np.full((20, 20), 255, dtype=np.uint8),
        structural_score=1.0,
        hole_count=2,
        contour_count=3,
    )
    signature = SignatureRegion(
        (90, 15, 30, 20),
        np.full((20, 30), 255, dtype=np.uint8),
    )

    protection = build_connection_protection(
        binary,
        texts=(text,),
        logos=(logo,),
        signatures=(signature,),
    )
    payload = protection.payload()

    assert set(payload["protected_categories"]) == {
        "high_confidence_text",
        "logo",
        "signature",
        "engineering_symbol",
        "arrow",
        "dimension_number",
        "leader_annotation",
    }
    assert payload["protection_guards"]["engineering_symbol"] == (
        "non_structural_source_ink_inside_structural_roi"
    )
    assert payload["category_pixels"]["dimension_number"] > 0
    assert cv2.countNonZero(protection.mask) > 0


def test_connection_observation_uses_each_rois_local_protection_mask() -> None:
    class Collector:
        def __init__(self) -> None:
            self.records: list[tuple[str, np.ndarray | None, dict]] = []

        def record(
            self,
            stage_key,
            *,
            image=None,
            payload=None,
            status="captured",
        ) -> None:
            del status
            self.records.append(
                (
                    stage_key,
                    None if image is None else image.copy(),
                    dict(payload or {}),
                )
            )

    lines = _frame_lines()
    foreground = _foreground(lines)
    rois = detect_structural_rois(
        lines,
        image_shape=foreground.shape,
        extension_budget=8.0,
    )
    collector = Collector()

    extend_lines_to_first_intersection(
        lines,
        maximum_extension=8.0,
        structural_rois=rois,
        source_foreground=foreground,
        protected_mask=np.zeros_like(foreground),
        protection_guards={
            "engineering_symbol": "non_structural_source_ink",
        },
        observation_sink=collector,
    )

    local_records = [
        (image, payload)
        for stage, image, payload in collector.records
        if stage == "conflict_mask"
        and payload.get("role") == "connection-protection-roi"
    ]
    global_records = [
        (image, payload)
        for stage, image, payload in collector.records
        if stage == "conflict_mask"
        and payload.get("role") == "connection-protection"
    ]
    assert len(local_records) == 1
    assert len(global_records) == 1
    local_image, local_payload = local_records[0]
    assert local_payload["roi_id"] == "frame-001"
    assert local_payload["origin"] == [
        rois.rois[0].bbox[0],
        rois.rois[0].bbox[1],
    ]
    assert local_payload["protected_categories"] == [
        "engineering_symbol"
    ]
    assert local_image is not None
    approved_payloads = [
        payload
        for stage, _image, payload in collector.records
        if stage == "approved_connections"
    ]
    assert approved_payloads
    assert all(
        int(connection["bridge_thickness"]) > 0
        for payload in approved_payloads
        for connection in payload["connections"]
    )
