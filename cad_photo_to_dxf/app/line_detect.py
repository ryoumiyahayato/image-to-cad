from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .resolution import image_resolution_scale, scaled_int, scaled_odd


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
    center_thick_strokes: bool = True
    min_center_width: float = 4.0


def _estimate_width(
    distance_map: np.ndarray,
    segment: LineSegment,
    resolution_scale: float = 1.0,
) -> float:
    vector = segment.p2 - segment.p1
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return 1.0
    normal = np.array([-vector[1], vector[0]], dtype=float) / norm
    minimum_radius = scaled_int(4, resolution_scale, minimum=2)
    maximum_radius = scaled_int(20, resolution_scale, minimum=minimum_radius)
    search_radius = max(
        minimum_radius,
        min(maximum_radius, int(round(segment.length * 0.025))),
    )
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


def _recenter_thick_stroke(
    distance_map: np.ndarray,
    segment: LineSegment,
    resolution_scale: float,
    minimum_width: float,
) -> LineSegment:
    """Move edge detections to a stable local stroke centerline.

    Both Canny/Hough edges of one thick printed stroke tend to converge on the
    same distance-transform ridge, after which the geometry duplicate pass can
    merge them. Thin independent CAD boundaries are left unchanged.
    """
    if segment.width < minimum_width * resolution_scale:
        return segment
    vector = segment.p2 - segment.p1
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return segment
    normal = np.array([-vector[1], vector[0]], dtype=float) / norm
    radius = max(
        scaled_int(3, resolution_scale, minimum=2),
        min(
            scaled_int(36, resolution_scale, minimum=6),
            int(round(segment.width * 1.25)),
        ),
    )
    offsets: list[float] = []
    ridge_values: list[float] = []
    for t in np.linspace(0.15, 0.85, 7):
        point = segment.p1 + vector * t
        best_offset = 0
        best_value = -1.0
        for offset in range(-radius, radius + 1):
            sample = point + normal * offset
            x, y = int(round(sample[0])), int(round(sample[1]))
            if 0 <= y < distance_map.shape[0] and 0 <= x < distance_map.shape[1]:
                value = float(distance_map[y, x])
                if value > best_value:
                    best_value = value
                    best_offset = offset
        if best_value >= max(1.25, minimum_width * resolution_scale * 0.35):
            offsets.append(float(best_offset))
            ridge_values.append(best_value)
    if len(offsets) < 4:
        return segment
    shift = float(np.median(offsets))
    spread = float(np.median(np.abs(np.asarray(offsets) - shift)))
    if abs(shift) < 0.5 or spread > max(1.5, segment.width * 0.35):
        return segment
    delta = normal * shift
    return segment.copy(
        x1=float(segment.x1 + delta[0]),
        y1=float(segment.y1 + delta[1]),
        x2=float(segment.x2 + delta[0]),
        y2=float(segment.y2 + delta[1]),
        history=tuple(dict.fromkeys(segment.history + ("recenter_thick_stroke",))),
    )


def _normalize_endpoint_order(segment: LineSegment) -> LineSegment:
    if (segment.x2, segment.y2) < (segment.x1, segment.y1):
        return segment.copy(x1=segment.x2, y1=segment.y2, x2=segment.x1, y2=segment.y1)
    return segment


def _prepare_segment(
    distance_map: np.ndarray,
    segment: LineSegment,
    params: LineDetectionParams,
    resolution_scale: float,
) -> LineSegment:
    width = _estimate_width(distance_map, segment, resolution_scale)
    prepared = segment.copy(width=width)
    if params.center_thick_strokes:
        prepared = _recenter_thick_stroke(
            distance_map,
            prepared,
            resolution_scale,
            params.min_center_width,
        )
        prepared = prepared.copy(
            width=_estimate_width(distance_map, prepared, resolution_scale)
        )
    return _normalize_endpoint_order(prepared)


def detect_lines(
    binary_image: np.ndarray,
    params: LineDetectionParams | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[LineSegment]:
    """Detect resolution-normalized candidate line segments from a binary image."""
    params = params or LineDetectionParams()
    checkpoint(cancellation_token)
    if binary_image.ndim == 3:
        binary_image = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    if binary_image.size == 0:
        return []

    resolution_scale = image_resolution_scale(binary_image.shape)
    effective_min_length = scaled_int(params.min_line_length, resolution_scale, minimum=5)
    effective_max_gap = scaled_int(params.max_line_gap, resolution_scale, minimum=0)
    effective_hough_threshold = scaled_int(
        params.hough_threshold,
        resolution_scale,
        minimum=10,
    )

    foreground = 255 - binary_image
    # A slight close repairs tiny breaks before line detection. Its physical
    # footprint scales with the photographed sheet resolution.
    morphology_size = scaled_odd(3, resolution_scale, minimum=1)
    foreground = cv2.morphologyEx(
        foreground,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (morphology_size, morphology_size)),
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
        threshold=effective_hough_threshold,
        minLineLength=effective_min_length,
        maxLineGap=effective_max_gap,
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
            if segment.length >= effective_min_length:
                segments.append(
                    _prepare_segment(distance_map, segment, params, resolution_scale)
                )
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
                if segment.length >= effective_min_length:
                    segments.append(
                        _prepare_segment(distance_map, segment, params, resolution_scale)
                    )
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
