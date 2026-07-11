from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.geometry_cleaner import GeometryCleanParams
from app.geometry_normalized import effective_geometry_params
from app.line_detect import LineDetectionParams, LineSegment, detect_lines
from app.preprocess import preprocess_image_with_stages
from app.resolution import (
    coordinate_resolution_scale,
    image_resolution_scale,
    scaled_int,
    spatial_bucket,
)


def test_image_resolution_scale_is_bounded_and_reference_based() -> None:
    assert image_resolution_scale((400, 600)) == 1.0
    assert image_resolution_scale((800, 1200)) == pytest.approx(0.5)
    assert image_resolution_scale((3500, 5000)) == pytest.approx(5000 / 2400)
    assert image_resolution_scale((9000, 12000)) == 3.0


def test_resolution_helpers_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="Reference long edge"):
        image_resolution_scale((400, 600), reference_long_edge_px=0)
    with pytest.raises(ValueError, match="dimensions"):
        image_resolution_scale((0, 600))
    with pytest.raises(ValueError, match="finite"):
        coordinate_resolution_scale([(0.0, 0.0), (float("nan"), 1.0)])
    with pytest.raises(ValueError, match="non-negative"):
        scaled_int(-1, 1.0)
    with pytest.raises(ValueError, match="positive finite"):
        scaled_int(1, 0.0)
    with pytest.raises(ValueError, match="finite"):
        spatial_bucket(float("inf"), 10.0)


def test_preprocessing_records_effective_resolution_scale() -> None:
    image = np.full((800, 1200, 3), 255, np.uint8)
    cv2.line(image, (100, 400), (1100, 400), (0, 0, 0), 4)
    result = preprocess_image_with_stages(image)
    assert result.resolution_scale == pytest.approx(0.5)
    assert result.image.shape == image.shape[:2]


def test_geometry_distances_scale_together() -> None:
    lines = [
        LineSegment(0, 0, 5000, 0, source_ids=("A",)),
        LineSegment(5000, 0, 5000, 3000, source_ids=("B",)),
    ]
    effective, scale = effective_geometry_params(lines, GeometryCleanParams())
    assert scale == pytest.approx(5000 / 2400)
    assert effective.snap_distance == pytest.approx(6.0 * scale)
    assert effective.max_bridge_gap == pytest.approx(12.0 * scale)
    assert effective.collinear_distance == pytest.approx(3.0 * scale)
    assert effective.duplicate_distance == pytest.approx(3.0 * scale)
    assert effective.min_line_length == pytest.approx(12.0 * scale)


def test_sparse_drawing_uses_full_image_scale_when_supplied() -> None:
    sparse = [LineSegment(100, 100, 300, 100, source_ids=("A",))]
    image_scale = image_resolution_scale((3500, 5000))
    effective, scale = effective_geometry_params(
        sparse,
        GeometryCleanParams(),
        resolution_scale=image_scale,
    )
    assert scale == pytest.approx(5000 / 2400)
    assert effective.snap_distance == pytest.approx(6.0 * scale)
    assert effective.min_line_length == pytest.approx(12.0 * scale)


def test_thick_stroke_candidates_are_recentred() -> None:
    image = np.full((1000, 1600), 255, np.uint8)
    cv2.line(image, (150, 500), (1450, 500), 0, 36)
    detected = detect_lines(
        image,
        LineDetectionParams(
            min_line_length=120,
            use_lsd=False,
            center_thick_strokes=True,
        ),
    )
    assert detected
    centred = [item for item in detected if "recenter_thick_stroke" in item.history]
    assert centred
    assert min(abs(float(item.midpoint[1]) - 500.0) for item in centred) <= 3.0
