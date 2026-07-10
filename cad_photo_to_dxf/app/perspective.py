from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class PerspectiveResult:
    image: np.ndarray
    corners: np.ndarray
    automatic: bool


def order_points(points: Iterable[Iterable[float]]) -> np.ndarray:
    """Return four points ordered as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(list(points), dtype=np.float32)
    if pts.shape != (4, 2):
        raise ValueError("Exactly four 2D points are required")

    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = pts.sum(axis=1)
    differences = np.diff(pts, axis=1).reshape(-1)
    ordered[0] = pts[np.argmin(sums)]
    ordered[2] = pts[np.argmax(sums)]
    ordered[1] = pts[np.argmin(differences)]
    ordered[3] = pts[np.argmax(differences)]
    return ordered


def detect_paper_corners(image: np.ndarray) -> np.ndarray | None:
    """Detect the largest plausible quadrilateral representing the paper boundary."""
    if image is None or image.size == 0:
        return None

    height, width = image.shape[:2]
    scale = min(1.0, 1400.0 / max(height, width))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)

    # Combine edge and brightness segmentation so a white sheet can be found on a dark desk.
    edges = cv2.Canny(gray, 40, 140)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates = [edges, bright]

    image_area = float(small.shape[0] * small.shape[1])
    quadrilaterals: list[tuple[float, np.ndarray]] = []
    for mask in candidates:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < image_area * 0.18:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                quadrilaterals.append((area, approx.reshape(4, 2).astype(np.float32)))

    if quadrilaterals:
        _, best = max(quadrilaterals, key=lambda item: item[0])
        return order_points(best / scale)

    # Conservative fallback: use a minimum-area rectangle only for a very large contour.
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(contour) >= image_area * 0.25:
            box = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
            return order_points(box / scale)
    return None


def warp_perspective(image: np.ndarray, corners: Iterable[Iterable[float]]) -> np.ndarray:
    """Rectify a sheet using four corner points."""
    rect = order_points(corners)
    tl, tr, br, bl = rect
    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    height_right = np.linalg.norm(br - tr)
    height_left = np.linalg.norm(bl - tl)
    output_width = max(2, int(round(max(width_top, width_bottom))))
    output_height = max(2, int(round(max(height_right, height_left))))

    destination = np.array(
        [
            [0, 0],
            [output_width - 1, 0],
            [output_width - 1, output_height - 1],
            [0, output_height - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(
        image,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def auto_correct(image: np.ndarray) -> PerspectiveResult | None:
    corners = detect_paper_corners(image)
    if corners is None:
        return None
    return PerspectiveResult(warp_perspective(image, corners), corners, automatic=True)


def rotate_image(image: np.ndarray, degrees: int) -> np.ndarray:
    normalized = degrees % 360
    if normalized == 0:
        return image.copy()
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("Rotation must be 0, 90, 180, or 270 degrees")
