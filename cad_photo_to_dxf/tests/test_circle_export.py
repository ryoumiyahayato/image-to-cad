from __future__ import annotations

from pathlib import Path
import tempfile

import ezdxf
import pytest

from app.auxiliary_recognition import (
    MIN_CIRCLE_EXPORT_CONFIDENCE,
    CircleCandidate,
    confirmable_circles,
)
from app.circle_review import select_approved_circles
from app.dxf_exporter import export_dxf
from app.line_detect import LineSegment


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


def test_exporter_writes_only_confirmed_circle_entities() -> None:
    line = LineSegment(
        10,
        20,
        100,
        20,
        source_ids=("L1",),
        history=("test",),
    )
    circle = CircleCandidate((50.0, 60.0), 12.0, 0.95)

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "confirmed-circle.dxf"
        result = export_dxf(
            [line],
            output,
            image_height=200,
            circles=[circle],
        )
        document = ezdxf.readfile(output)
        circles = list(document.modelspace().query("CIRCLE"))
        lines = list(document.modelspace().query("LINE"))

    assert result.line_count == 1
    assert result.circle_count == 1
    assert result.skipped_circle_count == 0
    assert len(lines) == 1
    assert len(circles) == 1
    entity = circles[0]
    assert entity.dxf.layer == "CIRCLE_CONFIRMED"
    assert float(entity.dxf.center.x) == pytest.approx(50.0)
    assert float(entity.dxf.center.y) == pytest.approx(139.0)
    assert float(entity.dxf.radius) == pytest.approx(12.0)
