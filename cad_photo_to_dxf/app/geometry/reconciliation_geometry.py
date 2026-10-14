"""Exact interval, pixel-footprint and serialization math for reconciliation.

No merge policy, ownership decisions or transaction authority lives here.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import json
from typing import Mapping, Sequence
import cv2
import numpy as np
from app.geometry.line_detect import LineSegment
from app.core.resolution import image_resolution_scale

@dataclass(frozen=True)
class ParameterInterval:
    """Half-open line-local interval, measured in source pixels."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("Reconciliation intervals must be finite")
        if self.end <= self.start:
            raise ValueError("Reconciliation intervals must have positive length")

    @property
    def length(self) -> float:
        return self.end - self.start

    def payload(self, evidence_refs: Sequence[str] = ()) -> dict[str, object]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "endpoint_convention": (
                "HALF_OPEN_INTERIOR_WITH_SEPARATE_ENDPOINT_OBLIGATIONS"
            ),
            "evidence_refs": list(evidence_refs),
        }


def _parameter_at_axis_coordinate(
    line: LineSegment,
    axis: int,
    coordinate: float,
) -> float:
    start = float(line.p1[axis])
    delta = float(line.p2[axis] - line.p1[axis])
    if abs(delta) <= 1e-9:
        return 0.0
    fraction = min(1.0, max(0.0, (coordinate - start) / delta))
    return fraction * line.length


def _child_interval_on_parent(
    parent: LineSegment,
    child: LineSegment,
) -> tuple[float, float]:
    if parent.length <= 0.0:
        return (0.0, 0.0)
    tangent = (parent.p2 - parent.p1) / parent.length
    parameters = sorted(
        (
            float(np.dot(child.p1 - parent.p1, tangent)),
            float(np.dot(child.p2 - parent.p1, tangent)),
        )
    )
    return (parameters[0], parameters[1])


def _clipped_child_interval_on_parent(
    parent: LineSegment,
    child: LineSegment,
) -> tuple[float, float]:
    start, end = _child_interval_on_parent(parent, child)
    return (
        min(parent.length, max(0.0, start)),
        min(parent.length, max(0.0, end)),
    )


def _trajectory_basis_payload(line: LineSegment) -> dict[str, object]:
    if line.length <= 0.0:
        tangent = np.array([1.0, 0.0], dtype=float)
    else:
        tangent = (line.p2 - line.p1) / line.length
    normal = np.array([-tangent[1], tangent[0]], dtype=float)
    return {
        "origin_px": [float(line.x1), float(line.y1)],
        "unit_tangent": [float(tangent[0]), float(tangent[1])],
        "unit_normal": [float(normal[0]), float(normal[1])],
    }


def _pixel_is_source(
    x: int,
    y: int,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> bool:
    return bool(
        0 <= y < gray.shape[0]
        and 0 <= x < gray.shape[1]
        and int(gray[y, x]) <= 150
        and int(binary[y, x]) < 128
    )


def _bresenham_pixels(
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    output: list[tuple[int, int]] = []
    while True:
        output.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return output
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def _local_mask_state(
    mask: np.ndarray | None,
    pixels: Sequence[object],
    *,
    active: str,
    inactive: str,
) -> str:
    if mask is None:
        return inactive
    for value in pixels:
        if not isinstance(value, Sequence) or len(value) != 2:
            continue
        x, y = int(value[0]), int(value[1])
        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x] > 0:
            return active
    return inactive


def _production_claim_thickness(
    line: LineSegment,
    *,
    shape: tuple[int, int],
) -> int:
    scale = image_resolution_scale(shape)
    maximum_thickness = max(5, int(round(16.0 * scale)))
    return max(
        2,
        min(
            maximum_thickness,
            int(round(max(1.0, float(line.width)) * 1.20)) + 2,
        ),
    )


def _local_claim_footprint_pixels(
    samples: Sequence[tuple[LineSegment, np.ndarray, np.ndarray]],
    *,
    shape: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    """Return a station cut through the exact production claim footprint."""

    output: set[tuple[int, int]] = set()
    for line, point, claim in samples:
        if line.length <= 1e-12:
            continue
        tangent = (line.p2 - line.p1) / line.length
        normal = np.array([-tangent[1], tangent[0]], dtype=float)
        radius = _production_claim_thickness(line, shape=shape) + 1
        start = tuple(
            int(round(float(value))) for value in point - normal * float(radius)
        )
        end = tuple(
            int(round(float(value))) for value in point + normal * float(radius)
        )
        for x, y in _bresenham_pixels(start, end):
            if 0 <= y < shape[0] and 0 <= x < shape[1] and claim[y, x] > 0:
                output.add((x, y))
    return tuple(sorted(output, key=lambda value: (value[0], value[1])))


def _subtract_intervals(
    source: Sequence[ParameterInterval],
    removed: Sequence[ParameterInterval],
) -> list[ParameterInterval]:
    normalized_removed = _merge_intervals(removed)
    output: list[ParameterInterval] = []
    for interval in source:
        cursor = interval.start
        for cut in normalized_removed:
            if cut.end <= cursor or cut.start >= interval.end:
                continue
            if cut.start > cursor:
                output.append(ParameterInterval(cursor, min(cut.start, interval.end)))
            cursor = max(cursor, cut.end)
            if cursor >= interval.end:
                break
        if cursor < interval.end:
            output.append(ParameterInterval(cursor, interval.end))
    return output


def _intersect_interval_sets(
    left: Sequence[ParameterInterval],
    right: Sequence[ParameterInterval],
) -> list[ParameterInterval]:
    output: list[ParameterInterval] = []
    for first in left:
        for second in right:
            start = max(first.start, second.start)
            end = min(first.end, second.end)
            if end > start:
                output.append(ParameterInterval(start, end))
    return _merge_intervals(output)


def _merge_intervals(intervals: Sequence[ParameterInterval]) -> list[ParameterInterval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    output: list[ParameterInterval] = []
    start = ordered[0].start
    end = ordered[0].end
    for interval in ordered[1:]:
        if interval.start <= end:
            end = max(end, interval.end)
            continue
        output.append(ParameterInterval(start, end))
        start, end = interval.start, interval.end
    output.append(ParameterInterval(start, end))
    return output


def _exact_subsegment(line: LineSegment, interval: ParameterInterval) -> LineSegment:
    if interval.start <= 0.0 and interval.end >= line.length:
        return line
    tangent = (line.p2 - line.p1) / line.length
    start = line.p1 + tangent * interval.start
    end = line.p1 + tangent * interval.end
    return line.copy(
        x1=float(start[0]),
        y1=float(start[1]),
        x2=float(end[0]),
        y2=float(end[1]),
    )


def _line_claim_mask(
    line: LineSegment,
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize exactly the production ownership footprint for one line."""

    claim = np.zeros(shape, dtype=np.uint8)
    thickness = _production_claim_thickness(line, shape=shape)
    cv2.line(
        claim,
        (int(round(line.x1)), int(round(line.y1))),
        (int(round(line.x2)), int(round(line.y2))),
        255,
        thickness,
        cv2.LINE_8,
    )
    return claim


def _line_identity_key(line: LineSegment) -> str:
    return json.dumps(
        _line_payload(line),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _trajectory_evidence_key(line: LineSegment) -> tuple[str, ...]:
    """Exact binary64 trajectory/width identity for snapshot-bound evidence."""

    return tuple(
        float(value).hex()
        for value in (line.x1, line.y1, line.x2, line.y2, line.width)
    )


def _geometry_key(line: LineSegment) -> str:
    values = (
        float(line.x1),
        float(line.y1),
        float(line.x2),
        float(line.y2),
        float(line.width),
        *line.source_ids,
    )
    return "|".join(str(value) for value in values)


def _geometry_key_from_payload(
    payload: object,
    *,
    source_ids: Sequence[str] = (),
) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("Invalid geometry payload")
    start = payload["start"]
    end = payload["end"]
    if not isinstance(start, Sequence) or not isinstance(end, Sequence):
        raise TypeError("Invalid geometry endpoint payload")
    return "|".join(
        str(value)
        for value in (
            start[0],
            start[1],
            end[0],
            end[1],
            payload["width"],
            *source_ids,
        )
    )


def _geometry_payload(line: LineSegment) -> dict[str, object]:
    return {
        "start": [float(line.x1), float(line.y1)],
        "end": [float(line.x2), float(line.y2)],
        "width": float(line.width),
    }


def _geometry_payload_matches_line(
    payload: object,
    line: LineSegment,
) -> bool:
    """Compare serialized geometry without rejecting float reconstruction noise."""

    if not isinstance(payload, Mapping):
        return False
    start = payload.get("start")
    end = payload.get("end")
    if (
        not isinstance(start, Sequence)
        or isinstance(start, (str, bytes))
        or len(start) != 2
        or not isinstance(end, Sequence)
        or isinstance(end, (str, bytes))
        or len(end) != 2
    ):
        return False
    try:
        actual = (
            float(start[0]),
            float(start[1]),
            float(end[0]),
            float(end[1]),
            float(payload["width"]),
        )
    except (KeyError, TypeError, ValueError):
        return False
    expected = (
        float(line.x1),
        float(line.y1),
        float(line.x2),
        float(line.y2),
        float(line.width),
    )
    return all(
        math.isclose(value, target, rel_tol=0.0, abs_tol=1e-9)
        for value, target in zip(actual, expected, strict=True)
    )


def _line_payload(line: LineSegment) -> dict[str, object]:
    return {
        "x1": float(line.x1),
        "y1": float(line.y1),
        "x2": float(line.x2),
        "y2": float(line.y2),
        "width": float(line.width),
        "confidence": float(line.confidence),
        "layer": line.layer,
        "source_ids": list(line.source_ids),
        "history": list(line.history),
        "classification_confidence": float(line.classification_confidence),
        "classification_reasons": list(line.classification_reasons),
    }


def _line_from_payload(payload: Mapping[str, object]) -> LineSegment:
    return LineSegment(
        x1=float(payload["x1"]),
        y1=float(payload["y1"]),
        x2=float(payload["x2"]),
        y2=float(payload["y2"]),
        width=float(payload["width"]),
        confidence=float(payload["confidence"]),
        layer=str(payload["layer"]),
        source_ids=tuple(str(value) for value in payload.get("source_ids", ())),
        history=tuple(str(value) for value in payload.get("history", ())),
        classification_confidence=float(payload["classification_confidence"]),
        classification_reasons=tuple(
            str(value) for value in payload.get("classification_reasons", ())
        ),
    )


def _line_from_geometry_payload(
    payload: object,
    *,
    source_ids: tuple[str, ...],
    history: tuple[str, ...],
) -> LineSegment:
    if not isinstance(payload, Mapping):
        raise TypeError("Invalid geometry payload")
    start = payload["start"]
    end = payload["end"]
    if not isinstance(start, Sequence) or not isinstance(end, Sequence):
        raise TypeError("Invalid geometry endpoint payload")
    return LineSegment(
        float(start[0]),
        float(start[1]),
        float(end[0]),
        float(end[1]),
        width=float(payload["width"]),
        source_ids=source_ids,
        history=history,
    )

