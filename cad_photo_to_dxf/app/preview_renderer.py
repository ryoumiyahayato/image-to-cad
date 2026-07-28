from __future__ import annotations

import cv2
import numpy as np

from .final_structure import FinalStructure


def render_final_structure_preview(structure: FinalStructure) -> np.ndarray:
    """Render only data owned by ``FinalStructure`` for the GUI."""

    structure.assert_valid()
    if structure.preview_binary is not None:
        return np.ascontiguousarray(structure.preview_binary.copy())
    preview = np.ascontiguousarray(structure.contour_binary.copy())
    for line in structure.straight_lines:
        cv2.line(
            preview,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            0,
            max(1, int(round(float(line.width)))),
            cv2.LINE_8,
        )
    for region in structure.signatures:
        x, y, width, height = region.bbox
        crop = preview[y : y + height, x : x + width]
        if crop.shape == region.mask.shape:
            crop[region.mask > 0] = 0
    return preview
