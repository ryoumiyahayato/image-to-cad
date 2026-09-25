from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.pipeline_fix_report import (
    build_baseline_before_after,
    build_roi_before_after,
)


def _image(path: Path, value: int = 220) -> Path:
    assert cv2.imwrite(str(path), np.full((80, 120, 3), value, np.uint8))
    return path


def test_roi_before_after_uses_same_source_coordinates(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png", 210)
    before = _image(tmp_path / "before.png", 230)
    after = _image(tmp_path / "after.png", 190)
    output = tmp_path / "comparison.png"

    build_roi_before_after(
        source_path=source,
        before_path=before,
        after_path=after,
        roi=(10, 20, 60, 40),
        title="fixed ROI",
        output_path=output,
    )

    rendered = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert rendered is not None
    assert rendered.shape == (712, 2100, 3)


def test_roi_before_after_rejects_coordinate_mismatch(tmp_path: Path) -> None:
    image = _image(tmp_path / "image.png")
    with pytest.raises(ValueError, match="outside"):
        build_roi_before_after(
            source_path=image,
            before_path=image,
            after_path=image,
            roi=(100, 70, 30, 30),
            title="invalid",
            output_path=tmp_path / "never.png",
        )


def test_frozen_baseline_comparison_requires_five_entries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="five DEV"):
        build_baseline_before_after([], tmp_path / "never.png")
