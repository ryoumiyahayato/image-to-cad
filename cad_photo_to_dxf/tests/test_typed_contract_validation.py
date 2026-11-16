"""Incomplete boundary data must fail explicitly, never gain default geometry."""

import pytest

from app.core.scale_calibrator import ScaleCalibration, raster_to_cad
from app.ocr.auxiliary_recognition import TextObservation


def test_paper_calibration_without_vertical_pitch_has_no_invented_scale():
    calibration = ScaleCalibration((0.0, 0.0), (100.0, 0.0), 210.0, (100, 200))
    with pytest.raises(ValueError, match="Invalid vertical paper calibration"):
        raster_to_cad((100, 200), calibration)


def test_incomplete_cell_clip_cannot_serialize_an_observation_as_complete():
    observation = TextObservation(
        0, "Text", (1, 2, 3, 4), None, (), 0.0, "verified-test-source",
        cell_clip_bbox=(1, 2, 3, 4),
    )
    with pytest.raises(ValueError, match="Cell clip bbox requires a matching quad"):
        observation.payload()
