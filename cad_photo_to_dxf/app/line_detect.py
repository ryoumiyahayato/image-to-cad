from __future__ import annotations

from dataclasses import dataclass, replace
import math

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress


@dataclass
class LineSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 1.0
    confidence: float = 1.0
    layer: str = "DETAIL"
    source_ids: tuple[str, ...] = ()
    history: tuple[str, ...] = ()
    classification_confidence: float = 1.0
    classification_reasons: tuple[str, ...] = ()

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

    def copy(self, **changes: object) -> "LineSegment":
        values = {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "width": self.width,
            "confidence": self.confidence,
            "layer": self.layer,
            "source_ids": self.source_ids,
            "history": self.history,
            "classification_confidence": self.classification_confidence,
            "classification_reasons": self.classification_reasons,
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
    scale_with_resolution: bool = True
    reference_long_edge: float = 2000.0


def effective_line_detection_params(
    params: LineDetectionParams,
    image_shape: tuple[int, ...],
) -> tuple[LineDetectionParams, float]:
    """Scale pixel thresholds from a reference long edge to the current image."""
    if not params.scale_with_resolution:
        return params, 1.0
    if params.reference_long_edge <= 0:
        raise ValueError("reference_long_edge must be greater than zero")
    long_edge = float(max(image_shape[:2]))
    factor = float(np.clip(long_edge / params.reference_long_edge, 0.25, 4.0))
    effective = replace(
        params,
        min_line_length=max(5, int(round(params.min_line_length * factor))),
        max_line_gap=max(0, int(round(params.max_line_gap * factor))),
        hough_threshold=max(10, int(round(params.hough_threshold * math.sqrt(factor)))),
        scale_with_resolution=False,
    )
    return effective, factor


def _estimate_width(distance_map: np.ndarray, segment: LineSegment) -> float:
    vector = segment.p2 - segment.p1
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return 1.0
    normal = np.array([-vector[1], vector[0]], dtype=float) / norm
    search_radius = max(4, min(20, int(round(segment.length * 0.025))))
    samples = []
    for t in np.linspace(0.1, 0.9, 7):
        point = segment.p1 + vector * t
        profile = []
        for offset in range(-search_radius, search_radius + 1):
            sample = point + normal * offset
            x, y = int(round(sample[0])), int(round(sample[1]))
            if 0 <= y < distance_map.shape[0] and 0 <= x < distance_map.shape[1]:
                profile.append(float(distance_map[y, x]) * 2.0)
        if profile:
            samples.append(max(profile))
    return max(1.0, float(np.median(samples))) if samples else 1.0


def _normalize_endpoint_order(segment: LineSegment) -> LineSegment:
    if (segment.x2, segment.y2) < (segment.x1, segment.y1):
        return segment.copy(x1=segment.x2, y1=segment.y2, x2=segment.x1, y2=segment.y1)
    return segment


def detect_lines(
    binary_image: np.ndarray,
    params: LineDetectionParams | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[LineSegment]:
    """Detect candidate line segments from a binary image."""
    requested_params = params or LineDetectionParams()
    params, resolution_factor = effective_line_detection_params(
        requested_params, binary_image.shape
    )
    checkpoint(cancellation_token)
    if binary_image.ndim == 3:
        binary_image = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)

    foreground = 255 - binary_image
    # Scale the close kernel with image resolution while keeping it odd.
    close_size = max(3, int(round(3.0 * resolution_factor)))
    if close_size % 2 == 0:
        close_size += 1
    foreground = cv2.morphologyEx(
        foreground,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size)),
    )
    edges = cv2.Canny(foreground, 40, 140, apertureSize=3)
    distance_map = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)
    report_progress(progress_callback, "line-preparation", 0.15)

    segments: list[LineSegment] = []
    checkpoint(cancellation_token)
    hough = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 720.0,
        threshold=max(10, int(params.hough_threshold)),
        minLineLength=max(5, int(params.min_line_length)),
        maxLineGap=max(0, int(params.max_line_gap)),
    )
    checkpoint(cancellation_token)
    if hough is not None:
        for index, (x1, y1, x2, y2) in enumerate(hough[:, 0, :], start=1):
            if index % 128 == 0:
                checkpoint(cancellation_token)
            source_id = f"HOUGH-{index:06d}"
            segment = LineSegment(
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                source_ids=(source_id,),
                history=("detected:hough",),
            )
            if segment.length >= params.min_line_length:
                segment.width = _estimate_width(distance_map, segment)
                segments.append(_normalize_endpoint_order(segment))
    report_progress(progress_callback, "hough", 0.55)

    if params.use_lsd:
        checkpoint(cancellation_token)
        detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        detected = detector.detect(foreground)[0]
        checkpoint(cancellation_token)
        if detected is not None:
            for index, item in enumerate(detected[:, 0, :], start=1):
                if index % 128 == 0:
                    checkpoint(cancellation_token)
                x1, y1, x2, y2 = map(float, item)
                source_id = f"LSD-{index:06d}"
                segment = LineSegment(
                    x1,
                    y1,
                    x2,
                    y2,
                    confidence=0.8,
                    source_ids=(source_id,),
                    history=("detected:lsd",),
                )
                if segment.length >= params.min_line_length:
                    segment.width = _estimate_width(distance_map, segment)
                    segments.append(_normalize_endpoint_order(segment))
    report_progress(progress_callback, "lsd", 0.9)

    # Prefer longer and stronger lines if a noisy image creates an excessive number.
    segments.sort(key=lambda line: (line.length * line.confidence, line.width), reverse=True)
    checkpoint(cancellation_token)
    report_progress(progress_callback, "line-detection", 1.0)
    return segments[: max(0, int(params.max_segments))]


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
        "HATCH_CANDIDATE": (180, 120, 0),
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
