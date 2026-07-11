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
    confidence: float = 1.0
    warnings: tuple[str, ...] = ()
    target_aspect_ratio: float | None = None


PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
}

# Automatic perspective correction must be conservative. Candidates below this
# threshold require manual corner confirmation instead of being stretched into a
# known paper aspect ratio.
MIN_AUTOMATIC_PAPER_CONFIDENCE = 0.60


def resolve_paper_dimensions_mm(
    paper_size: str | None = None,
    custom_width_mm: float | None = None,
    custom_height_mm: float | None = None,
    orientation: str = "auto",
    observed_landscape: bool | None = None,
) -> tuple[float, float] | None:
    """Resolve oriented paper dimensions as output width and height."""
    if custom_width_mm is not None or custom_height_mm is not None:
        if not custom_width_mm or not custom_height_mm:
            raise ValueError("Both custom paper width and height are required")
        if custom_width_mm <= 0 or custom_height_mm <= 0:
            raise ValueError("Paper dimensions must be greater than zero")
        width, height = float(custom_width_mm), float(custom_height_mm)
    elif paper_size and paper_size.upper() not in {"UNKNOWN", "AUTO"}:
        try:
            width, height = PAPER_SIZES_MM[paper_size.upper()]
        except KeyError as exc:
            raise ValueError(f"Unknown paper size: {paper_size}") from exc
    else:
        return None

    normalized_orientation = orientation.lower()
    if normalized_orientation not in {"auto", "portrait", "landscape"}:
        raise ValueError("Orientation must be auto, portrait, or landscape")
    if normalized_orientation == "auto":
        landscape = bool(observed_landscape) if observed_landscape is not None else width >= height
    else:
        landscape = normalized_orientation == "landscape"
    long_side, short_side = max(width, height), min(width, height)
    return (long_side, short_side) if landscape else (short_side, long_side)


def resolve_paper_aspect_ratio(
    paper_size: str | None = None,
    custom_width_mm: float | None = None,
    custom_height_mm: float | None = None,
    orientation: str = "auto",
    observed_landscape: bool | None = None,
) -> float | None:
    """Resolve the target width/height ratio for a known sheet."""
    dimensions = resolve_paper_dimensions_mm(
        paper_size,
        custom_width_mm,
        custom_height_mm,
        orientation,
        observed_landscape,
    )
    return dimensions[0] / dimensions[1] if dimensions is not None else None


def order_points(points: Iterable[Iterable[float]]) -> np.ndarray:
    """Return four points ordered as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(list(points), dtype=np.float32)
    if pts.shape != (4, 2):
        raise ValueError("Exactly four 2D points are required")
    if not np.isfinite(pts).all():
        raise ValueError("Corner coordinates must be finite")
    if len(np.unique(np.round(pts, decimals=4), axis=0)) != 4:
        raise ValueError("Corner points must be unique")
    hull = cv2.convexHull(pts).reshape(-1, 2)
    if len(hull) != 4 or abs(float(cv2.contourArea(hull))) < 1e-3:
        raise ValueError("Corner points must form a non-degenerate convex quadrilateral")

    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    # Start at the top-left-like vertex. The tie breakers keep a 45-degree
    # diamond deterministic without assigning the same point twice.
    start = min(
        range(4),
        key=lambda index: (
            float(ordered[index, 0] + ordered[index, 1]),
            float(ordered[index, 1]),
            float(ordered[index, 0]),
        ),
    )
    ordered = np.roll(ordered, -start, axis=0).astype(np.float32)
    # Ascending image-space angles normally produce TL, TR, BR, BL. Reverse
    # the traversal if the second vertex is on the left-hand side instead.
    if ordered[1, 0] < ordered[-1, 0]:
        ordered = ordered[[0, 3, 2, 1]]
    return ordered


def _appearance_score(gray: np.ndarray, ordered: np.ndarray) -> float | None:
    """Score a bright sheet against the background outside the candidate."""
    polygon = np.round(ordered).astype(np.int32)
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, polygon, 255)

    characteristic = max(3, int(round(min(gray.shape[:2]) * 0.012)))
    if characteristic % 2 == 0:
        characteristic += 1
    inner_kernel = np.ones((characteristic, characteristic), np.uint8)
    guard_size = characteristic * 3
    if guard_size % 2 == 0:
        guard_size += 1
    guard_kernel = np.ones((guard_size, guard_size), np.uint8)

    inner = cv2.erode(mask, inner_kernel, iterations=1)
    outside_guard = cv2.dilate(mask, guard_kernel, iterations=1)
    interior = gray[inner > 0]
    exterior = gray[outside_guard == 0]
    if interior.size < 64 or exterior.size < 64:
        return None

    interior_mean = float(np.mean(interior))
    # The median prevents a narrow black frame line from masquerading as the
    # background. A true sheet normally remains brighter than the broad area
    # outside its boundary; an internal frame on a white page does not.
    exterior_level = float(np.median(exterior))
    contrast = interior_mean - exterior_level
    if contrast < 8.0:
        return None

    contrast_score = float(np.clip(contrast / 80.0, 0.0, 1.0))
    brightness_score = float(np.clip(interior_mean / 235.0, 0.0, 1.0))
    return 0.75 * contrast_score + 0.25 * brightness_score


def _aspect_score(ordered: np.ndarray, target_aspect_ratio: float | None) -> float:
    if target_aspect_ratio is None:
        return 1.0
    tl, tr, br, bl = ordered
    width = max(float(np.linalg.norm(tr - tl)), float(np.linalg.norm(br - bl)))
    height = max(float(np.linalg.norm(bl - tl)), float(np.linalg.norm(br - tr)))
    if width <= 1e-6 or height <= 1e-6:
        return 0.0
    observed = width / height
    error = abs(float(np.log(observed / target_aspect_ratio)))
    return float(np.exp(-3.0 * error))


def _detect_paper_candidate(
    image: np.ndarray,
    target_aspect_ratio: float | None = None,
) -> tuple[np.ndarray, float] | None:
    """Return the best validated quadrilateral and a conservative confidence score."""
    if image is None or image.size == 0:
        return None

    height, width = image.shape[:2]
    scale = min(1.0, 1400.0 / max(height, width))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    if float(np.std(gray)) < 3.0:
        return None
    gray = cv2.GaussianBlur(gray, (7, 7), 0)

    edges = cv2.Canny(gray, 40, 140)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    image_area = float(small.shape[0] * small.shape[1])
    margin = max(2.0, min(small.shape[:2]) * 0.008)
    candidates: list[tuple[float, float, np.ndarray]] = []

    for mask in (edges, bright):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / max(image_area, 1.0)
            if area_ratio < 0.18 or area_ratio > 0.95:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            quad = approx.reshape(4, 2).astype(np.float32)
            try:
                ordered = order_points(quad)
            except ValueError:
                continue
            touches = sum(
                1
                for x, y in ordered
                if x <= margin
                or y <= margin
                or x >= small.shape[1] - 1 - margin
                or y >= small.shape[0] - 1 - margin
            )
            if touches >= 3:
                continue

            appearance = _appearance_score(gray, ordered)
            if appearance is None:
                continue
            rectangle = cv2.minAreaRect(contour)
            rectangle_area = float(rectangle[1][0] * rectangle[1][1])
            if rectangle_area <= 1e-6:
                continue
            rectangularity = float(np.clip(area / rectangle_area, 0.0, 1.0))
            if rectangularity < 0.72:
                continue

            area_score = float(np.clip(area_ratio / 0.72, 0.0, 1.0))
            border_score = 1.0 - touches / 4.0
            aspect_score = _aspect_score(ordered, target_aspect_ratio)
            confidence = (
                area_score * 0.25
                + border_score * 0.10
                + appearance * 0.40
                + rectangularity * 0.15
                + aspect_score * 0.10
            )
            candidates.append((confidence, area, ordered))

    if not candidates:
        return None
    confidence, _, best = max(candidates, key=lambda item: (item[0], item[1]))
    return best / scale, float(confidence)


def detect_paper_corners(image: np.ndarray) -> np.ndarray | None:
    """Detect a validated quadrilateral representing the paper boundary."""
    candidate = _detect_paper_candidate(image)
    if candidate is None or candidate[1] < MIN_AUTOMATIC_PAPER_CONFIDENCE:
        return None
    return candidate[0]


def warp_perspective(
    image: np.ndarray,
    corners: Iterable[Iterable[float]],
    target_aspect_ratio: float | None = None,
) -> np.ndarray:
    """Rectify a sheet using four corner points."""
    rect = order_points(corners)
    tl, tr, br, bl = rect
    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    height_right = np.linalg.norm(br - tr)
    height_left = np.linalg.norm(bl - tl)
    observed_width = max(width_top, width_bottom)
    observed_height = max(height_right, height_left)
    if target_aspect_ratio is not None:
        if not np.isfinite(target_aspect_ratio) or target_aspect_ratio <= 0:
            raise ValueError("Target paper aspect ratio must be greater than zero")
        approximate_area = max(4.0, observed_width * observed_height)
        output_width = max(2, int(round(np.sqrt(approximate_area * target_aspect_ratio))))
        output_height = max(2, int(round(output_width / target_aspect_ratio)))
    else:
        output_width = max(2, int(round(observed_width)))
        output_height = max(2, int(round(observed_height)))

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


def auto_correct(
    image: np.ndarray,
    target_aspect_ratio: float | None = None,
    minimum_confidence: float = MIN_AUTOMATIC_PAPER_CONFIDENCE,
) -> PerspectiveResult | None:
    candidate = _detect_paper_candidate(image, target_aspect_ratio)
    if candidate is None:
        return None
    corners, confidence = candidate
    if confidence < minimum_confidence:
        return None
    ratio = target_aspect_ratio
    warnings: list[str] = []
    if ratio is None:
        warnings.append("未指定纸张真实长宽比，横纵尺寸可能存在非等比例误差。")
    if confidence < 0.75:
        warnings.append("纸张边界识别置信度一般，请检查四个角点；必要时改用手动校正。")
    return PerspectiveResult(
        warp_perspective(image, corners, ratio),
        corners,
        automatic=True,
        confidence=confidence,
        warnings=tuple(warnings),
        target_aspect_ratio=ratio,
    )


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
