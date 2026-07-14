from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.perspective import PerspectiveResult
from app.pipeline import run_pipeline


def test_permissive_pipeline_keeps_original_for_low_confidence_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "drawing.png"
    original = np.full((240, 360, 3), 255, np.uint8)
    cv2.line(original, (40, 120), (320, 120), (0, 0, 0), 4)
    cv2.imwrite(str(source), original)

    suspicious_warp = np.zeros_like(original)
    candidate = PerspectiveResult(
        image=suspicious_warp,
        corners=np.array(
            [[10, 10], [350, 10], [350, 230], [10, 230]],
            dtype=np.float32,
        ),
        automatic=True,
        confidence=0.40,
        warnings=("low confidence",),
        target_aspect_ratio=297.0 / 210.0,
    )

    with patch("app.pipeline.auto_correct", return_value=candidate):
        result = run_pipeline(
            source,
            tmp_path / "output.dxf",
            paper_size="A4",
            paper_orientation="landscape",
            strict_perspective=False,
            fail_on_empty=False,
        )

    assert np.array_equal(result.corrected, original)
    assert result.report["perspective"]["candidate_detected"] is True
    assert result.report["perspective"]["applied"] is False
    assert result.report["perspective"]["rejected_low_confidence"] is True
    assert result.report["export"]["coordinate_space"] == "pixel"
    assert result.export.calibrated is False
