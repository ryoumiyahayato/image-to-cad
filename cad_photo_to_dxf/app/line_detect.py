from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass
class LineSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 1.0
    confidence: float = 1.0
    layer: str = "DETAIL"

    @property
    def p1(self) -> np.ndarray:
        return np.array([self.x1, self.y1], dtype=float)

    @property
    def p2(self) -> np.ndarray:
        return np.array([self.x2, self.y2], dtype=float)

    @property
    def length(self) -> float:
        return float(math.hypot(self.x2 - self.x1, self.y2 - self.y1))

    @property
    def angle(self) -> float:
        angle = math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1)) % 180.0
        return angle

    @property
    def midpoint(self) -> np.ndarray:
        return (self.p1 + self.p2) / 2.0

    def copy(self, **changes: float | str) -> "LineSegment":
        values = {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "width": self.width,
            "confidence": self.confidence,
            "layer": self.layer,
        }
        values.update(changes)
        return LineSegment(**values)


@dataclass
class LineDetectionParams:
    min_line_length: int = 35
    max_line_gap: int = 10
    hough_threshold: int = 35
    use_lsd: bool = True
    max_segments: int = 6000


def _estimate_width(distance_map: np.ndarray, segment: LineSegment) -> float:
    samples = []
    for t in np.linspace(0.1, 0.9, 7):
        x = int(round(segment.x1 + (segment.x2 - segment.x1) * t))
        y = int(round(segment.y1 + (segment.y2 - segment.y1) * t))
        if 0 <= y < distance_map.shape[0] and 0 <= x < distance_map.shape[1]:
            samples.append(float(distance_map[y, x]) * 2.0)
    return max(1.0, float(np.median(samples))) if samples else 1.0


def _normalize_endpoint_order(segment: LineSegment) -> LineSegment:
    if (segment.x2, segment.y2) < (segment.x1, segment.y1):
        return segment.copy(x1=segment.x2, y1=segment.y2, x2=segment.x1, y2=segment.y1)
    return segment


def detect_lines(
    binary_image: np.ndarray, params: LineDetectionParams | None = None
) -> list[LineSegment]:
    """Detect candidate line segments from a binary image."""
    params = params or LineDetectionParams()
    if binary_image.ndim == 3:
        binary_image = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)

    foreground = 255 - binary_image
    # A slight close repairs tiny breaks before line detection.
    foreground = cv2.morphologyEx(
        foreground,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    edges = cv2.Canny(foreground, 40, 140, apertureSize=3)
    distance_map = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)

    segments: list[LineSegment] = []
    hough = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 720.0,
        threshold=max(10, int(params.hough_threshold)),
        minLineLength=max(5, int(params.min_line_length)),
        maxLineGap=max(0, int(params.max_line_gap)),
    )
    if hough is not None:
        for x1, y1, x2, y2 in hough[:, 0, :]:
            segment = LineSegment(float(x1), float(y1), float(x2), float(y2))
            if segment.length >= params.min_line_length:
                segment.width = _estimate_width(distance_map, segment)
                segments.append(_normalize_endpoint_order(segment))

    if params.use_lsd:
        detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        detected = detector.detect(foreground)[0]
        if detected is not None:
            for item in detected[:, 0, :]:
                x1, y1, x2, y2 = map(float, item)
                segment = LineSegment(x1, y1, x2, y2, confidence=0.8)
                if segment.length >= params.min_line_length:
                    segment.width = _estimate_width(distance_map, segment)
                    segments.append(_normalize_endpoint_order(segment))

    # Prefer longer and stronger lines if a noisy image creates an excessive number.
    segments.sort(key=lambda line: (line.length * line.confidence, line.width), reverse=True)
    return segments[: params.max_segments]


def render_line_preview(
    base_image: np.ndarray,
    lines: list[LineSegment],
    show_layers: bool = True,
) -> np.ndarray:
    if base_image.ndim == 2:
        canvas = cv2.cvtColor(base_image, cv2.COLOR_GRAY2BGR)
    else:
        canvas = base_image.copy()

    colors = {
        "OUTLINE": (0, 0, 220),
        "WALL_OR_FRAME": (0, 150, 0),
        "GRID_OR_AXIS": (220, 80, 0),
        "HATCH": (180, 0, 180),
        "DETAIL": (0, 160, 220),
    }
    for line in lines:
        color = colors.get(line.layer, (0, 0, 255)) if show_layers else (0, 0, 255)
        cv2.line(
            canvas,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas
