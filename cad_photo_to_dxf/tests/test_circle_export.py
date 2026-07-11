from __future__ import annotations

from pathlib import Path
import tempfile

import ezdxf
from ezdxf import units
import pytest

from app.auxiliary_recognition import (
    MIN_CIRCLE_EXPORT_CONFIDENCE,
    CircleCandidate,
    confirmable_circles,
)
from app.circle_review import select_approved_circles
from app.dxf_exporter import export_dxf
from app.line_detect import LineSegment
from app.scale_calibrator import ScaleCalibration


def test_circle_confirmation_requires_threshold_and_explicit_selection() -> None:
    high = CircleCandidate((50.0, 60.0), 12.0, MIN_CIRCLE_EXPORT_CONFIDENCE)
    low = CircleCandidate((70.0, 80.0), 10.0, MIN_CIRCLE_EXPORT_CONFIDENCE - 0.01)

    assert confirmable_circles([low, high]) == [high]
    assert select_approved_circles([high, low], [False, True]) == []
    assert select_approved_circles([high, low], [True, True]) == [high]


def test_circle_confirmation_rejects_mismatched_review_rows() -> None:
    circle = CircleCandidate((50.0, 60.0), 12.0, 0.95)
    with pytest.raises(ValueError, match="exactly one review selection"):
        select_approved_circles([circle], [])


def test_exporter_rechecks_circle_confidence_and_keeps_pixels_unitless() -> None:
    line = LineSegment(
        10,
        20,
        100,
        20,
        source_ids=("L1",),
        history=("test",),
    )
    high = CircleCandidate((50.0, 60.0), 12.0, 0.95)
    low = CircleCandidate(
        (80.0, 90.0),
        8.0,
        MIN_CIRCLE_EXPORT_CONFIDENCE - 0.01,
    )

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "confirmed-circle.dxf"
        result = export_dxf(
            [line],
            output,
            image_height=200,
            circles=[high, low],
        )
        document = ezdxf.readfile(output)
        circles = list(document.modelspace().query("CIRCLE"))
        lines = list(document.modelspace().query("LINE"))

    assert result.line_count == 1
    assert result.circle_count == 1
    assert result.skipped_circle_count == 1
    assert result.calibrated is False
    assert int(document.header["$INSUNITS"]) == 0
    assert len(lines) == 1
    assert len(circles) == 1
    entity = circles[0]
    assert entity.dxf.layer == "CIRCLE_CONFIRMED"
    assert float(entity.dxf.center.x) == pytest.approx(50.0)
    assert float(entity.dxf.center.y) == pytest.approx(139.0)
    assert float(entity.dxf.radius) == pytest.approx(12.0)


def test_calibrated_export_declares_millimetres() -> None:
    line = LineSegment(0, 0, 100, 0, source_ids=("L1",))
    calibration = ScaleCalibration((0.0, 0.0), (100.0, 0.0), 200.0)

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "calibrated.dxf"
        result = export_dxf(
            [line],
            output,
            image_height=200,
            calibration=calibration,
        )
        document = ezdxf.readfile(output)

    assert result.calibrated is True
    assert result.mm_per_pixel == pytest.approx(2.0)
    assert int(document.header["$INSUNITS"]) == units.MM
