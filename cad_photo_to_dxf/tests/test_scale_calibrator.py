from __future__ import annotations

import pytest

from app.scale_calibrator import ScaleCalibration, create_calibration


def test_finite_calibration_scale() -> None:
    calibration = create_calibration([(0, 0), (100, 0)], 250)
    assert calibration.pixel_distance == pytest.approx(100.0)
    assert calibration.mm_per_pixel == pytest.approx(2.5)


@pytest.mark.parametrize(
    "calibration, message",
    [
        (ScaleCalibration((0, 0), (0, 0), 10), "must not be identical"),
        (ScaleCalibration((0, 0), (100, 0), 0), "positive finite"),
        (ScaleCalibration((0, 0), (100, 0), float("inf")), "positive finite"),
        (ScaleCalibration((float("nan"), 0), (100, 0), 10), "coordinates"),
    ],
)
def test_invalid_calibrations_are_rejected(
    calibration: ScaleCalibration,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = calibration.mm_per_pixel


def test_create_calibration_rejects_nonfinite_points() -> None:
    with pytest.raises(ValueError, match="coordinates"):
        create_calibration([(0, 0), (float("inf"), 0)], 10)
