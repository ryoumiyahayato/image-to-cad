from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import cv2
import numpy as np


def _read(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise OSError(path)
    return image


def _fit(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (
            max(1, int(round(image.shape[1] * scale))),
            max(1, int(round(image.shape[0] * scale))),
        ),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
    )
    canvas: np.ndarray = np.full((height, width, 3), 248, np.uint8)
    left = (width - resized.shape[1]) // 2
    top = (height - resized.shape[0]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas


def _crop(image: np.ndarray, roi: Sequence[int]) -> np.ndarray:
    if len(roi) != 4:
        raise ValueError("ROI must be x, y, width, height")
    x, y, width, height = (int(value) for value in roi)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("ROI must be positive and inside the source image")
    if x + width > image.shape[1] or y + height > image.shape[0]:
        raise ValueError("ROI lies outside source coordinates")
    return np.ascontiguousarray(image[y : y + height, x : x + width])


def build_roi_before_after(
    *,
    source_path: Path,
    before_path: Path,
    after_path: Path,
    roi: Sequence[int],
    title: str,
    output_path: Path,
) -> Path:
    images = [
        _crop(_read(source_path), roi),
        _crop(_read(before_path), roi),
        _crop(_read(after_path), roi),
    ]
    panel_width, panel_height = 700, 620
    header_height = 92
    canvas: np.ndarray = np.full(
        (header_height + panel_height, panel_width * 3, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        title[:180],
        (20, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (25, 25, 25),
        2,
        cv2.LINE_AA,
    )
    for index, (label, image) in enumerate(
        zip(("SOURCE", "BEFORE FINAL", "AFTER FINAL"), images, strict=True)
    ):
        left = index * panel_width
        cv2.putText(
            canvas,
            label,
            (left + 16, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (35, 35, 35),
            1,
            cv2.LINE_AA,
        )
        canvas[header_height:, left : left + panel_width] = _fit(
            image,
            panel_width,
            panel_height,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def build_baseline_before_after(
    entries: Sequence[Mapping[str, object]],
    output_path: Path,
) -> Path:
    if len(entries) != 5:
        raise ValueError("Pipeline fix comparison requires the frozen five DEV entries")
    panel_width, panel_height = 525, 360
    header_height = 76
    row_title_height = 54
    row_height = row_title_height + panel_height
    canvas: np.ndarray = np.full(
        (header_height + len(entries) * row_height, panel_width * 4, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        "PIPELINE-DESTRUCTION-FIX-P1  SOURCE | BEFORE FINAL | AFTER FINAL | AFTER OVERLAY",
        (20, 46),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    for row, entry in enumerate(entries):
        top = header_height + row * row_height
        source_group_id = str(entry["source_group_id"])
        status = str(entry.get("comparison", "PENDING"))
        cv2.putText(
            canvas,
            f"{source_group_id}  {status}",
            (18, top + 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
        paths = (
            Path(str(entry["source_image"])),
            Path(str(entry["before_reconstructed"])),
            Path(str(entry["after_reconstructed"])),
            Path(str(entry["after_overlay"])),
        )
        for column, path in enumerate(paths):
            panel = _fit(_read(path), panel_width, panel_height)
            left = column * panel_width
            canvas[
                top + row_title_height : top + row_height,
                left : left + panel_width,
            ] = panel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path
