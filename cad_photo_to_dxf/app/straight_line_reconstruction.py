from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np

from .cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from .connectivity_safety import (
    StructuralConnectivityContext,
    build_structural_connectivity_context,
    evaluate_structural_bridge,
)
from .line_detect import LineDetectionParams, LineSegment, detect_lines
from .observability import (
    ObservationSink,
    lines_payload,
    observe,
    rasterize_connections,
    rasterize_endpoints,
    rasterize_lines,
    rasterize_rois,
    rois_payload,
)
from .resolution import image_resolution_scale
from .structural_roi import StructuralRoiSet, detect_structural_rois
from .text_protection import detect_text_region_mask, filter_text_like_lines


def _cross(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _angle_difference(left: LineSegment, right: LineSegment) -> float:
    delta = abs(left.angle - right.angle) % 180.0
    return min(delta, 180.0 - delta)


def _candidate_pairs(
    lines: Sequence[LineSegment],
    tolerance: float,
) -> list[tuple[int, int]]:
    """Return spatially nearby pairs without comparing every line to every line."""

    if len(lines) < 2:
        return []
    lengths = [line.length for line in lines if line.length > 1e-9]
    median_length = float(np.median(lengths)) if lengths else 64.0
    cell_size = max(32.0, min(384.0, median_length))
    buckets: dict[tuple[int, int], list[int]] = {}
    large: list[int] = []

    for index, line in enumerate(lines):
        min_x = min(line.x1, line.x2) - tolerance
        max_x = max(line.x1, line.x2) + tolerance
        min_y = min(line.y1, line.y2) - tolerance
        max_y = max(line.y1, line.y2) + tolerance
        x0 = math.floor(min_x / cell_size)
        x1 = math.floor(max_x / cell_size)
        y0 = math.floor(min_y / cell_size)
        y1 = math.floor(max_y / cell_size)
        cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if cell_count > 2048:
            large.append(index)
            continue
        for cell_x in range(x0, x1 + 1):
            for cell_y in range(y0, y1 + 1):
                buckets.setdefault((cell_x, cell_y), []).append(index)

    pairs: set[tuple[int, int]] = set()
    for indexes in buckets.values():
        unique = sorted(set(indexes))
        for position, left in enumerate(unique):
            for right in unique[position + 1 :]:
                pairs.add((left, right))
    for index in large:
        for other in range(len(lines)):
            if index != other:
                pairs.add((min(index, other), max(index, other)))
    return sorted(pairs)


def _intersection_parameters(
    left: LineSegment,
    right: LineSegment,
) -> tuple[float, float, np.ndarray] | None:
    p = left.p1
    r = left.p2 - left.p1
    q = right.p1
    s = right.p2 - right.p1
    denominator = _cross(r, s)
    if abs(denominator) <= 1e-9:
        return None
    offset = q - p
    left_parameter = _cross(offset, s) / denominator
    right_parameter = _cross(offset, r) / denominator
    return (
        float(left_parameter),
        float(right_parameter),
        p + left_parameter * r,
    )


def _extension_endpoint(
    line: LineSegment,
    parameter: float,
    point: np.ndarray,
    maximum_extension: float,
) -> tuple[int, float] | None:
    """Identify an endpoint that can only move outwards to the intersection."""

    epsilon = 1e-7
    if parameter < -epsilon:
        distance = float(np.linalg.norm(point - line.p1))
        return (0, distance) if distance <= maximum_extension else None
    if parameter > 1.0 + epsilon:
        distance = float(np.linalg.norm(point - line.p2))
        return (1, distance) if distance <= maximum_extension else None
    return None


def _parameter_within_extended_segment(
    line: LineSegment,
    parameter: float,
    maximum_extension: float,
) -> bool:
    parameter_tolerance = maximum_extension / max(line.length, 1.0)
    return -parameter_tolerance <= parameter <= 1.0 + parameter_tolerance


def _axis_distance(angle: float) -> float:
    normalized = float(angle) % 90.0
    return min(normalized, 90.0 - normalized)


def _line_mask_coverage(line: LineSegment, mask: np.ndarray) -> float:
    sample_count = max(12, min(512, int(math.ceil(line.length))))
    xs = np.linspace(line.x1, line.x2, sample_count)
    ys = np.linspace(line.y1, line.y2, sample_count)
    xi = np.clip(np.rint(xs).astype(np.int32), 0, mask.shape[1] - 1)
    yi = np.clip(np.rint(ys).astype(np.int32), 0, mask.shape[0] - 1)
    return float(np.mean(mask[yi, xi] > 0))


def _scan_support_mask(
    gray: np.ndarray,
    binary: np.ndarray,
    *,
    scale: float,
) -> np.ndarray:
    """Return nearby deep ink, excluding weak fold and tape-edge shading."""

    if gray.shape != binary.shape:
        raise ValueError("Scan support image must match the binary page shape")
    if gray.dtype != np.uint8:
        raise ValueError("Scan support image must be an 8-bit grayscale image")
    foreground_tones = gray[binary < 128]
    if foreground_tones.size:
        dark_threshold = int(
            round(
                float(
                    np.clip(
                        np.percentile(foreground_tones, 50.0),
                        110.0,
                        135.0,
                    )
                )
            )
        )
    else:
        dark_threshold = 125
    deep_ink = np.where(gray <= dark_threshold, 255, 0).astype(np.uint8)
    radius = max(2, int(round(3.0 * scale)))
    return cv2.dilate(
        deep_ink,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (radius * 2 + 1, radius * 2 + 1),
        ),
        iterations=1,
    )


def _binary_support_mask(binary: np.ndarray, *, scale: float) -> np.ndarray:
    """Return a narrow corridor around source ink for all page types."""

    foreground = np.where(binary < 128, 255, 0).astype(np.uint8)
    radius = max(1, int(round(1.5 * scale)))
    return cv2.dilate(
        foreground,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (radius * 2 + 1, radius * 2 + 1),
        ),
        iterations=1,
    )


def _filter_source_supported_lines(
    lines: Sequence[LineSegment],
    *,
    support_mask: np.ndarray,
) -> list[LineSegment]:
    """Reject any centerline that mostly spans pixels absent from the source."""

    kept: list[LineSegment] = []
    for line in lines:
        support_fraction, longest_gap_fraction = _line_support_quality(
            line,
            support_mask,
        )
        if support_fraction < 0.68 or longest_gap_fraction > 0.22:
            continue
        kept.append(line)
    return kept


def _trim_endpoints_to_source_support(
    lines: Sequence[LineSegment],
    *,
    support_mask: np.ndarray,
) -> list[LineSegment]:
    """Prevent cleaning or snapping from moving endpoints across blank paper."""

    trimmed: list[LineSegment] = []
    for line in lines:
        sample_count = max(2, min(4096, int(math.ceil(line.length)) + 1))
        parameters = np.linspace(0.0, 1.0, sample_count)
        xs = line.x1 + (line.x2 - line.x1) * parameters
        ys = line.y1 + (line.y2 - line.y1) * parameters
        xi = np.clip(np.rint(xs).astype(np.int32), 0, support_mask.shape[1] - 1)
        yi = np.clip(np.rint(ys).astype(np.int32), 0, support_mask.shape[0] - 1)
        supported = np.flatnonzero(support_mask[yi, xi] > 0)
        if not supported.size:
            continue
        first = int(supported[0])
        last = int(supported[-1])
        if last <= first:
            continue
        start = float(parameters[first])
        end = float(parameters[last])
        trimmed.append(
            line.copy(
                x1=float(line.x1 + (line.x2 - line.x1) * start),
                y1=float(line.y1 + (line.y2 - line.y1) * start),
                x2=float(line.x1 + (line.x2 - line.x1) * end),
                y2=float(line.y1 + (line.y2 - line.y1) * end),
                history=tuple(
                    dict.fromkeys(line.history + ("trim_to_source_support",))
                ),
            )
        )
    return trimmed


def _line_support_quality(
    line: LineSegment,
    support_mask: np.ndarray,
) -> tuple[float, float]:
    """Return total ink support and the longest unsupported fraction."""

    sample_count = max(12, min(2048, int(math.ceil(line.length))))
    xs = np.linspace(line.x1, line.x2, sample_count)
    ys = np.linspace(line.y1, line.y2, sample_count)
    xi = np.clip(np.rint(xs).astype(np.int32), 0, support_mask.shape[1] - 1)
    yi = np.clip(np.rint(ys).astype(np.int32), 0, support_mask.shape[0] - 1)
    supported = support_mask[yi, xi] > 0
    longest_gap = 0
    current_gap = 0
    for value in supported:
        if value:
            current_gap = 0
        else:
            current_gap += 1
            longest_gap = max(longest_gap, current_gap)
    return (
        float(np.mean(supported)),
        float(longest_gap) / float(sample_count),
    )


def _line_lies_on_crop_edge(
    line: LineSegment,
    image_shape: tuple[int, ...],
    *,
    margin: float,
) -> bool:
    height, width = int(image_shape[0]), int(image_shape[1])
    return bool(
        max(line.x1, line.x2) <= margin
        or min(line.x1, line.x2) >= width - 1 - margin
        or max(line.y1, line.y2) <= margin
        or min(line.y1, line.y2) >= height - 1 - margin
    )


def _filter_scan_artifact_lines(
    lines: Sequence[LineSegment],
    *,
    support_mask: np.ndarray,
    image_shape: tuple[int, ...],
    scale: float,
) -> list[LineSegment]:
    """Reject unsupported crop, fold and tape edges from the blue line layer."""

    if not lines:
        return []
    border_margin = max(6.0 * scale, min(image_shape[:2]) * 0.006)
    kept: list[LineSegment] = []
    for line in lines:
        if _line_lies_on_crop_edge(
            line,
            image_shape,
            margin=border_margin,
        ):
            continue
        support_fraction, longest_gap_fraction = _line_support_quality(
            line,
            support_mask,
        )
        weak_and_broken = support_fraction < 0.55 and longest_gap_fraction > 0.35
        if support_fraction < 0.40 or longest_gap_fraction > 0.55 or weak_and_broken:
            continue
        kept.append(line)
    return kept


def _axis_orientation(line: LineSegment) -> str | None:
    if abs(line.y2 - line.y1) <= abs(line.x2 - line.x1) * 0.05:
        return "horizontal"
    if abs(line.x2 - line.x1) <= abs(line.y2 - line.y1) * 0.05:
        return "vertical"
    return None


def _axis_coordinate(line: LineSegment, orientation: str) -> float:
    if orientation == "horizontal":
        return float((line.y1 + line.y2) * 0.5)
    return float((line.x1 + line.x2) * 0.5)


def _axis_interval(line: LineSegment, orientation: str) -> tuple[float, float]:
    if orientation == "horizontal":
        return tuple(sorted((float(line.x1), float(line.x2))))
    return tuple(sorted((float(line.y1), float(line.y2))))


def _parallel_band_ink_support(
    left: LineSegment,
    right: LineSegment,
    *,
    orientation: str,
    gray: np.ndarray,
    scale: float,
) -> float:
    """Measure whether two nearby detections lie on one continuous ink stroke.

    A thick scanned rule often produces detections on both stroke edges.  Real
    double rules instead have a light gap between them.  Sampling the complete
    cross-band distinguishes those cases without relying on line count alone.
    """

    left_start, left_end = _axis_interval(left, orientation)
    right_start, right_end = _axis_interval(right, orientation)
    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    if overlap_end <= overlap_start:
        return 0.0

    first = _axis_coordinate(left, orientation)
    second = _axis_coordinate(right, orientation)
    low, high = sorted((first, second))
    # Sample only between the two detections. Padding with surrounding paper
    # made the decision unstable for anti-aliased coordinates (for example,
    # 2191.0 versus 2191.03 could add a complete white row).
    cross_start = int(math.ceil(low))
    cross_end = int(math.floor(high))
    along_samples = max(
        12,
        min(384, int(math.ceil((overlap_end - overlap_start) / max(1.0, scale)))),
    )
    along = np.linspace(overlap_start, overlap_end, along_samples)
    cross = np.arange(cross_start, cross_end + 1, dtype=np.int32)
    if cross.size == 0:
        return 0.0

    if orientation == "horizontal":
        xs = np.clip(np.rint(along).astype(np.int32), 0, gray.shape[1] - 1)
        ys = np.clip(cross, 0, gray.shape[0] - 1)
        samples = gray[ys[:, None], xs[None, :]]
    else:
        ys = np.clip(np.rint(along).astype(np.int32), 0, gray.shape[0] - 1)
        xs = np.clip(cross, 0, gray.shape[1] - 1)
        samples = gray[ys[:, None], xs[None, :]].T

    dark = samples <= 150
    cross_occupancy = np.mean(dark, axis=0)
    return float(np.mean(cross_occupancy >= 0.40))


def _parallel_scan_duplicates(
    left: LineSegment,
    right: LineSegment,
    *,
    orientation: str,
    gray: np.ndarray,
    scale: float,
    maximum_separation: float,
) -> bool:
    separation = abs(
        _axis_coordinate(left, orientation) - _axis_coordinate(right, orientation)
    )
    if separation > maximum_separation:
        return False

    left_start, left_end = _axis_interval(left, orientation)
    right_start, right_end = _axis_interval(right, orientation)
    overlap = min(left_end, right_end) - max(left_start, right_start)
    shorter = min(left_end - left_start, right_end - right_start)
    if overlap < max(8.0 * scale, shorter * 0.55):
        return False

    # The ordinary geometry cleaner already handles almost coincident lines.
    # Wider scan drift is only collapsed when the complete band is genuinely
    # ink-filled, which preserves adjacent walls and intentional double rules.
    if separation <= 2.5 * scale:
        return True
    return (
        _parallel_band_ink_support(
            left,
            right,
            orientation=orientation,
            gray=gray,
            scale=scale,
        )
        >= 0.58
    )


def _merge_parallel_scan_group(
    group: Sequence[LineSegment],
    *,
    orientation: str,
) -> LineSegment:
    longest = max(group, key=lambda line: line.length)
    coordinate = float(
        np.median([_axis_coordinate(line, orientation) for line in group])
    )
    intervals = [_axis_interval(line, orientation) for line in group]
    start = min(interval[0] for interval in intervals)
    end = max(interval[1] for interval in intervals)
    source_ids = tuple(sorted({source for line in group for source in line.source_ids}))
    history = tuple(dict.fromkeys(item for line in group for item in line.history)) + (
        "collapse_scan_parallel_duplicate",
    )
    reasons = tuple(
        dict.fromkeys(
            reason for line in group for reason in line.classification_reasons
        )
    )
    changes: dict[str, object] = {
        "width": max(line.width for line in group),
        "confidence": max(line.confidence for line in group),
        "source_ids": source_ids,
        "history": history,
        "classification_confidence": max(
            line.classification_confidence for line in group
        ),
        "classification_reasons": reasons,
    }
    if orientation == "horizontal":
        changes.update(x1=start, y1=coordinate, x2=end, y2=coordinate)
    else:
        changes.update(x1=coordinate, y1=start, x2=coordinate, y2=end)
    return longest.copy(**changes)


def collapse_scan_parallel_duplicates(
    lines: Sequence[LineSegment],
    *,
    gray: np.ndarray,
    scale: float,
) -> list[LineSegment]:
    """Collapse duplicate edges of one scanned rule to one centerline.

    Groups use complete-linkage compatibility, so a 0/7/14-pixel chain cannot
    transitively erase two legitimate neighboring rules.
    """

    if not lines:
        return []
    maximum_separation = max(4.5, 4.5 * scale)
    remaining = set(range(len(lines)))
    output: list[LineSegment] = []
    ordered = sorted(
        range(len(lines)), key=lambda index: lines[index].length, reverse=True
    )
    for index in ordered:
        if index not in remaining:
            continue
        base = lines[index]
        orientation = _axis_orientation(base)
        remaining.remove(index)
        if orientation is None:
            output.append(base)
            continue
        group = [base]
        candidates = sorted(
            (
                candidate
                for candidate in remaining
                if _axis_orientation(lines[candidate]) == orientation
                and abs(
                    _axis_coordinate(base, orientation)
                    - _axis_coordinate(lines[candidate], orientation)
                )
                <= maximum_separation
            ),
            key=lambda candidate: abs(
                _axis_coordinate(base, orientation)
                - _axis_coordinate(lines[candidate], orientation)
            ),
        )
        for candidate in candidates:
            candidate_line = lines[candidate]
            if all(
                _parallel_scan_duplicates(
                    member,
                    candidate_line,
                    orientation=orientation,
                    gray=gray,
                    scale=scale,
                    maximum_separation=maximum_separation,
                )
                for member in group
            ):
                group.append(candidate_line)
                remaining.remove(candidate)
        if len(group) == 1:
            output.append(base)
        else:
            output.append(_merge_parallel_scan_group(group, orientation=orientation))
    return output


def suppress_parallel_duplicate_detections(
    lines: Sequence[LineSegment],
    *,
    gray: np.ndarray,
    scale: float,
) -> list[LineSegment]:
    """Drop duplicate detections without moving or joining source endpoints."""

    if not lines:
        return []
    maximum_separation = max(4.5, 4.5 * scale)
    remaining = set(range(len(lines)))
    output: list[LineSegment] = []
    ordered = sorted(
        range(len(lines)),
        key=lambda index: lines[index].length,
        reverse=True,
    )
    for index in ordered:
        if index not in remaining:
            continue
        base = lines[index]
        orientation = _axis_orientation(base)
        remaining.remove(index)
        if orientation is None:
            output.append(base)
            continue
        group = [base]
        candidates = sorted(
            (
                candidate
                for candidate in remaining
                if _axis_orientation(lines[candidate]) == orientation
                and abs(
                    _axis_coordinate(base, orientation)
                    - _axis_coordinate(lines[candidate], orientation)
                )
                <= maximum_separation
            ),
            key=lambda candidate: abs(
                _axis_coordinate(base, orientation)
                - _axis_coordinate(lines[candidate], orientation)
            ),
        )
        for candidate in candidates:
            candidate_line = lines[candidate]
            if all(
                _parallel_scan_duplicates(
                    member,
                    candidate_line,
                    orientation=orientation,
                    gray=gray,
                    scale=scale,
                    maximum_separation=maximum_separation,
                )
                for member in group
            ):
                group.append(candidate_line)
                remaining.remove(candidate)
        if len(group) > 1:
            base = base.copy(
                history=tuple(
                    dict.fromkeys(
                        base.history
                        + ("suppress_parallel_duplicate_detection",)
                    )
                )
            )
        output.append(base)
    return output


def _structural_intersection_pair(
    left: LineSegment,
    right: LineSegment,
    *,
    minimum_angle_degrees: float,
) -> bool:
    """Reject the shallow arbitrary crossings common in handwriting and damage."""

    difference = _angle_difference(left, right)
    if difference < minimum_angle_degrees:
        return False
    both_axis_aligned = (
        _axis_distance(left.angle) <= 4.0 and _axis_distance(right.angle) <= 4.0
    )
    near_perpendicular = 72.0 <= difference <= 108.0
    return bool(both_axis_aligned or near_perpendicular)


def extend_lines_to_first_intersection(
    lines: Sequence[LineSegment],
    *,
    maximum_extension: float,
    structural_rois: StructuralRoiSet | None = None,
    source_foreground: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
    minimum_angle_degrees: float = 7.5,
    max_pair_checks: int = 750_000,
    cancellation_token: CancellationToken | None = None,
    observation_sink: ObservationSink | None = None,
) -> list[LineSegment]:
    """Extend each open endpoint to its nearest valid theoretical intersection.

    An endpoint is changed at most once. Candidate intersections are ordered by
    extension distance, so the line stops at the first crossing and never grows
    through a nearer boundary to reach a farther one. Existing endpoints are
    never shortened.
    """

    resolved = [line.copy() for line in lines if line.length > 1e-9]
    if (
        not resolved
        or maximum_extension <= 0.0
        or structural_rois is None
        or source_foreground is None
    ):
        if observation_sink is not None and source_foreground is not None:
            blank = np.zeros_like(source_foreground)
            observe(
                observation_sink,
                "approved_connections",
                image=blank,
                payload={"connections": [], "count": 0},
            )
            observe(
                observation_sink,
                "rejected_connections",
                image=blank,
                payload={"connections": [], "count": 0},
            )
            observe(
                observation_sink,
                "intersection_extension",
                image=rasterize_lines(resolved, source_foreground.shape),
                payload={
                    "role": "before",
                    "lines": lines_payload(resolved),
                    "maximum_extension": float(maximum_extension),
                },
            )
            observe(
                observation_sink,
                "intersection_extension",
                image=rasterize_lines(resolved, source_foreground.shape),
                payload={
                    "role": "after",
                    "lines": lines_payload(resolved),
                    "maximum_extension": float(maximum_extension),
                },
            )
        return resolved

    choices: dict[tuple[int, int], tuple[float, np.ndarray]] = {}
    choice_records: dict[tuple[int, int], dict[str, Any]] = {}
    connectivity_contexts: dict[str, StructuralConnectivityContext] = {}
    allowed_attempts: list[dict[str, Any]] = []
    rejected_connections: list[dict[str, Any]] = []
    attempt_id = 0
    pair_checks = 0
    for left_index, right_index in _candidate_pairs(resolved, maximum_extension):
        pair_checks += 1
        if pair_checks % 512 == 0:
            checkpoint(cancellation_token)
        if pair_checks > max_pair_checks:
            break
        left = resolved[left_index]
        right = resolved[right_index]
        if not _structural_intersection_pair(
            left,
            right,
            minimum_angle_degrees=minimum_angle_degrees,
        ):
            continue
        intersection = _intersection_parameters(left, right)
        if intersection is None:
            continue
        left_parameter, right_parameter, point = intersection
        if not _parameter_within_extended_segment(
            left, left_parameter, maximum_extension
        ):
            continue
        if not _parameter_within_extended_segment(
            right, right_parameter, maximum_extension
        ):
            continue

        left_endpoint = _extension_endpoint(
            left, left_parameter, point, maximum_extension
        )
        right_endpoint = _extension_endpoint(
            right, right_parameter, point, maximum_extension
        )
        if left_endpoint is None and right_endpoint is None:
            continue
        roi = structural_rois.common_roi(
            left_index,
            right_index,
            (float(point[0]), float(point[1])),
        )
        if roi is None:
            if observation_sink is not None:
                for line_index, endpoint in (
                    (left_index, left_endpoint),
                    (right_index, right_endpoint),
                ):
                    if endpoint is None:
                        continue
                    endpoint_index, distance = endpoint
                    source_line = resolved[line_index]
                    source_point = (
                        (float(source_line.x1), float(source_line.y1))
                        if endpoint_index == 0
                        else (float(source_line.x2), float(source_line.y2))
                    )
                    attempt_id += 1
                    rejected_connections.append(
                        {
                            "attempt_id": attempt_id,
                            "line_index": line_index,
                            "other_line_index": (
                                right_index
                                if line_index == left_index
                                else left_index
                            ),
                            "endpoint_index": endpoint_index,
                            "start": list(source_point),
                            "end": [float(point[0]), float(point[1])],
                            "distance": float(distance),
                            "allowed": False,
                            "reason_code": "outside_structural_roi",
                            "roi_id": "",
                            "bridge_pixels": 0,
                            "component_count_before": 0,
                            "component_count_after": 0,
                        }
                    )
            continue
        for line_index, endpoint in (
            (left_index, left_endpoint),
            (right_index, right_endpoint),
        ):
            if endpoint is None:
                continue
            endpoint_index, distance = endpoint
            source_line = resolved[line_index]
            relative_limit = max(2.0, source_line.length * 0.20)
            source_point = (
                (float(source_line.x1), float(source_line.y1))
                if endpoint_index == 0
                else (float(source_line.x2), float(source_line.y2))
            )
            if observation_sink is not None:
                attempt_id += 1
            if distance > relative_limit:
                if observation_sink is not None:
                    rejected_connections.append(
                        {
                            "attempt_id": attempt_id,
                            "line_index": line_index,
                            "other_line_index": (
                                right_index
                                if line_index == left_index
                                else left_index
                            ),
                            "endpoint_index": endpoint_index,
                            "start": list(source_point),
                            "end": [float(point[0]), float(point[1])],
                            "distance": float(distance),
                            "allowed": False,
                            "reason_code": "relative_extension_limit",
                            "roi_id": roi.roi_id,
                            "bridge_pixels": 0,
                            "component_count_before": 0,
                            "component_count_after": 0,
                        }
                    )
                continue
            context = connectivity_contexts.get(roi.roi_id)
            if context is None:
                context = build_structural_connectivity_context(
                    roi=roi,
                    lines=resolved,
                    source_foreground=source_foreground,
                    protected_mask=protected_mask,
                )
                connectivity_contexts[roi.roi_id] = context
            decision = evaluate_structural_bridge(
                roi=roi,
                lines=resolved,
                start=source_point,
                end=(float(point[0]), float(point[1])),
                source_foreground=source_foreground,
                protected_mask=protected_mask,
                context=context,
            )
            record = None
            if observation_sink is not None:
                record = {
                    "attempt_id": attempt_id,
                    "line_index": line_index,
                    "other_line_index": (
                        right_index
                        if line_index == left_index
                        else left_index
                    ),
                    "endpoint_index": endpoint_index,
                    "start": list(source_point),
                    "end": [float(point[0]), float(point[1])],
                    "distance": float(distance),
                    "allowed": bool(decision.allowed),
                    "reason_code": decision.reason_code,
                    "roi_id": decision.roi_id,
                    "bridge_pixels": int(decision.bridge_pixels),
                    "component_count_before": int(
                        decision.component_count_before
                    ),
                    "component_count_after": int(
                        decision.component_count_after
                    ),
                }
            if not decision.allowed:
                if observation_sink is not None and record is not None:
                    rejected_connections.append(record)
                continue
            if observation_sink is not None and record is not None:
                allowed_attempts.append(record)
            key = (line_index, endpoint_index)
            current = choices.get(key)
            if current is None or distance < current[0]:
                choices[key] = (distance, point.copy())
                if observation_sink is not None and record is not None:
                    choice_records[key] = record

    output: list[LineSegment] = []
    for index, line in enumerate(resolved):
        start = choices.get((index, 0))
        end = choices.get((index, 1))
        changes: dict[str, float | tuple[str, ...]] = {}
        if start is not None:
            changes["x1"] = float(start[1][0])
            changes["y1"] = float(start[1][1])
        if end is not None:
            changes["x2"] = float(end[1][0])
            changes["y2"] = float(end[1][1])
        if changes:
            changes["history"] = tuple(
                dict.fromkeys(line.history + ("extend_to_first_intersection",))
            )
            output.append(line.copy(**changes))
        else:
            output.append(line)
    if observation_sink is not None:
        approved_connections = list(choice_records.values())
        applied_attempt_ids = {
            int(record["attempt_id"]) for record in approved_connections
        }
        rejected_connections.extend(
            {
                **record,
                "allowed": False,
                "reason_code": "superseded_by_nearer_connection",
            }
            for record in allowed_attempts
            if int(record["attempt_id"]) not in applied_attempt_ids
        )
        observe(
            observation_sink,
            "approved_connections",
            image=rasterize_connections(
                approved_connections,
                source_foreground.shape,
            ),
            payload={
                "connections": approved_connections,
                "count": len(approved_connections),
            },
        )
        observe(
            observation_sink,
            "rejected_connections",
            image=rasterize_connections(
                rejected_connections,
                source_foreground.shape,
            ),
            payload={
                "connections": rejected_connections,
                "count": len(rejected_connections),
            },
        )
        observe(
            observation_sink,
            "intersection_extension",
            image=rasterize_lines(resolved, source_foreground.shape),
            payload={
                "role": "before",
                "lines": lines_payload(resolved),
                "maximum_extension": float(maximum_extension),
            },
        )
        observe(
            observation_sink,
            "intersection_extension",
            image=rasterize_lines(output, source_foreground.shape),
            payload={
                "role": "after",
                "lines": lines_payload(output),
                "maximum_extension": float(maximum_extension),
            },
        )
    return output


def reconstruct_straight_lines(
    binary: np.ndarray,
    *,
    scan_support_gray: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    observation_sink: ObservationSink | None = None,
) -> tuple[LineSegment, ...]:
    """Detect table/frame rules without turning text or logos into blue lines.

    Residual curves, glyph strokes and diagonal drawing content stay in the
    contour channel.  Only near-horizontal or near-vertical structural rules
    are eligible for native LINE reconstruction.
    """

    if binary.ndim != 2 or binary.size == 0:
        return ()
    scale = image_resolution_scale(binary.shape)
    source_support = _binary_support_mask(binary, scale=scale)
    support_mask = (
        None
        if scan_support_gray is None
        else _scan_support_mask(
            scan_support_gray,
            binary,
            scale=scale,
        )
    )
    minimum_length = max(28.0 * scale, min(binary.shape[:2]) * 0.012)
    raw = detect_lines(
        binary,
        LineDetectionParams(
            min_line_length=24,
            # A page-wide Hough gap joins unrelated glyph, symbol and rule
            # fragments before ownership is known. Any repair must instead be
            # proposed later inside a verified StructuralRoi.
            max_line_gap=0,
            hough_threshold=28,
            use_lsd=True,
            max_segments=5000,
            center_thick_strokes=True,
        ),
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage, 0.55 * max(0.0, min(1.0, fraction))
            )
        ),
    )
    if observation_sink is not None:
        observe(
            observation_sink,
            "raw_line_candidates",
            image=rasterize_lines(raw, binary.shape),
            payload={"lines": lines_payload(raw), "count": len(raw)},
        )
    checkpoint(cancellation_token)
    candidates = [
        line
        for line in raw
        if line.length >= minimum_length
        and line.length >= max(10.0 * line.width, minimum_length)
        and _axis_distance(line.angle) <= 4.0
    ]
    candidates = _filter_source_supported_lines(
        candidates,
        support_mask=source_support,
    )
    text_protection = detect_text_region_mask(binary)
    candidates, _text_protection = filter_text_like_lines(
        candidates,
        text_protection,
        binary.shape,
    )
    if support_mask is not None:
        candidates = _filter_scan_artifact_lines(
            candidates,
            support_mask=support_mask,
            image_shape=binary.shape,
            scale=scale,
        )
    if observation_sink is not None:
        observe(
            observation_sink,
            "line_candidates_text_filtered",
            image=rasterize_lines(candidates, binary.shape),
            payload={
                "lines": lines_payload(candidates),
                "count": len(candidates),
            },
        )
        observe(
            observation_sink,
            "candidate_endpoints",
            image=rasterize_endpoints(candidates, binary.shape),
            payload={
                "endpoints": [
                    [float(x), float(y)]
                    for line in candidates
                    for x, y in ((line.x1, line.y1), (line.x2, line.y2))
                ],
                "count": len(candidates) * 2,
            },
        )
        snap_payload = {
            "enabled": False,
            "snap_distance": 0.0,
            "lines": lines_payload(candidates),
            "reason": "Production structural reconstruction disables endpoint snapping.",
        }
        observe(
            observation_sink,
            "endpoint_snap",
            image=rasterize_lines(candidates, binary.shape),
            payload={"role": "before", **snap_payload},
        )
        observe(
            observation_sink,
            "endpoint_snap",
            image=rasterize_lines(candidates, binary.shape),
            payload={"role": "after", **snap_payload},
        )
    report_progress(progress_callback, "line-filtering", 0.58)
    if not candidates:
        if observation_sink is not None:
            blank = np.zeros_like(binary)
            observe(
                observation_sink,
                "structural_roi",
                image=blank,
                payload={"rois": [], "count": 0},
            )
            observe(
                observation_sink,
                "approved_connections",
                image=blank,
                payload={"connections": [], "count": 0},
            )
            observe(
                observation_sink,
                "rejected_connections",
                image=blank,
                payload={"connections": [], "count": 0},
            )
            for role in ("before", "after"):
                observe(
                    observation_sink,
                    "intersection_extension",
                    image=blank,
                    payload={
                        "role": role,
                        "lines": [],
                        "maximum_extension": 0.0,
                    },
                )
            observe(
                observation_sink,
                "structural_line_candidate_mask",
                image=blank,
                payload={"lines": [], "count": 0},
            )
        return ()

    # Do not run the generic whole-page geometry cleaner here. Even with a
    # zero bridge distance it still performs page-wide orthogonalization,
    # collinear grouping and endpoint passes. Candidate coordinates remain
    # source-derived until the ROI-constrained extension decision below.
    cleaned = _trim_endpoints_to_source_support(
        candidates,
        support_mask=source_support,
    )
    if support_mask is not None:
        cleaned = _filter_scan_artifact_lines(
            cleaned,
            support_mask=support_mask,
            image_shape=binary.shape,
            scale=scale,
        )
    cleaned = _filter_source_supported_lines(
        cleaned,
        support_mask=source_support,
    )
    cleaned = _trim_endpoints_to_source_support(
        cleaned,
        support_mask=source_support,
    )
    cleaned = suppress_parallel_duplicate_detections(
        cleaned,
        gray=(binary if scan_support_gray is None else scan_support_gray),
        scale=scale,
    )
    report_progress(progress_callback, "line-cleaning", 0.86)
    extension_budget = max(2.0, 3.0 * scale)
    structural_rois = detect_structural_rois(
        cleaned,
        image_shape=binary.shape,
        extension_budget=extension_budget,
    )
    if observation_sink is not None:
        observe(
            observation_sink,
            "structural_roi",
            image=rasterize_rois(structural_rois.rois, binary.shape),
            payload={
                "rois": rois_payload(structural_rois.rois),
                "count": len(structural_rois.rois),
                "extension_budget": float(extension_budget),
            },
        )
    extended = extend_lines_to_first_intersection(
        cleaned,
        maximum_extension=extension_budget,
        structural_rois=structural_rois,
        source_foreground=np.where(binary < 128, 255, 0).astype(np.uint8),
        protected_mask=protected_mask,
        cancellation_token=cancellation_token,
        observation_sink=observation_sink,
    )
    if support_mask is not None:
        extended = _filter_scan_artifact_lines(
            extended,
            support_mask=support_mask,
            image_shape=binary.shape,
            scale=scale,
        )
    extended = _filter_source_supported_lines(
        extended,
        support_mask=source_support,
    )
    extended = _trim_endpoints_to_source_support(
        extended,
        support_mask=source_support,
    )
    if observation_sink is not None:
        observe(
            observation_sink,
            "structural_line_candidate_mask",
            image=rasterize_lines(extended, binary.shape),
            payload={
                "role": "post-filter-candidates",
                "lines": lines_payload(extended),
                "count": len(extended),
            },
        )
    checkpoint(cancellation_token)
    report_progress(progress_callback, "line-reconstruction", 1.0)
    return tuple(
        sorted(
            extended,
            key=lambda line: (
                round(min(line.y1, line.y2), 3),
                round(min(line.x1, line.x2), 3),
                -line.length,
            ),
        )
    )


def suppress_reconstructed_lines(
    binary: np.ndarray,
    lines: Sequence[LineSegment],
) -> np.ndarray:
    """Remove line stroke pixels before contour tracing; lines are exported separately."""

    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    if not lines:
        return result
    scale = image_resolution_scale(binary.shape)
    maximum_thickness = max(5, int(round(20.0 * scale)))
    for line in lines:
        thickness = max(
            2,
            min(
                maximum_thickness,
                int(math.ceil(max(1.0, line.width) * 1.35)) + 2,
            ),
        )
        cv2.line(
            result,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            thickness,
            cv2.LINE_8,
        )
    return result
