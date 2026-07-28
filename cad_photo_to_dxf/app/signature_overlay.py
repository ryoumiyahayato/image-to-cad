from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import atan2, degrees, hypot
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .image_loader import save_image
from .structural_roi import verified_structural_rule_masks


@dataclass(frozen=True)
class SignatureRegion:
    """One structurally detected handwriting footprint.

    The mask contains source pixels only. It is never expanded by OCR boxes or
    morphology, so a signature cannot claim table rules or nearby text.
    """

    bbox: tuple[int, int, int, int]
    mask: np.ndarray


@dataclass(frozen=True)
class _InkComponent:
    label: int
    bbox: tuple[int, int, int, int]
    area: int


def _foreground(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Signature source must be a non-empty binary page")
    if binary.dtype != np.uint8:
        raise ValueError("Signature source must be an 8-bit binary page")
    return np.where(binary < 128, 255, 0).astype(np.uint8)


def _component_boxes(
    mask: np.ndarray,
) -> tuple[np.ndarray, tuple[_InkComponent, ...]]:
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    components: list[_InkComponent] = []
    for label in range(1, count):
        x, y, width, height, area = (
            int(value) for value in stats[label]
        )
        if area < 3 or width <= 0 or height <= 0:
            continue
        components.append(
            _InkComponent(
                label=label,
                bbox=(x, y, width, height),
                area=area,
            )
        )
    return labels, tuple(components)


def _components_belong_to_same_stroke_group(
    left: _InkComponent,
    right: _InkComponent,
) -> bool:
    lx, ly, lw, lh = left.bbox
    rx, ry, rw, rh = right.bbox
    horizontal_gap = max(0, max(lx, rx) - min(lx + lw, rx + rw))
    vertical_overlap = max(0, min(ly + lh, ry + rh) - max(ly, ry))
    center_distance = abs((ly + lh * 0.5) - (ry + rh * 0.5))
    local_height = max(1, lh, rh)
    return bool(
        horizontal_gap <= local_height * 0.45
        and (
            vertical_overlap >= min(lh, rh) * 0.20
            or center_distance <= local_height * 0.55
        )
    )


def _component_groups(
    components: tuple[_InkComponent, ...],
) -> tuple[tuple[_InkComponent, ...], ...]:
    parents = list(range(len(components)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    ordered = sorted(
        range(len(components)),
        key=lambda index: components[index].bbox[0],
    )
    observed_heights = np.asarray(
        [item.bbox[3] for item in components],
        dtype=np.float64,
    )
    search_height = max(
        1.0,
        float(np.quantile(observed_heights, 0.95)),
    )
    for order_index, left_index in enumerate(ordered):
        left = components[left_index]
        left_right = left.bbox[0] + left.bbox[2]
        for right_index in ordered[order_index + 1 :]:
            right = components[right_index]
            if right.bbox[0] - left_right > search_height * 0.45:
                break
            if _components_belong_to_same_stroke_group(
                left,
                right,
            ):
                union(left_index, right_index)

    grouped: dict[int, list[_InkComponent]] = {}
    for index, component in enumerate(components):
        grouped.setdefault(find(index), []).append(component)
    return tuple(tuple(group) for group in grouped.values())


def _group_bounds(
    group: tuple[_InkComponent, ...],
) -> tuple[int, int, int, int]:
    left = min(item.bbox[0] for item in group)
    top = min(item.bbox[1] for item in group)
    right = max(item.bbox[0] + item.bbox[2] for item in group)
    bottom = max(item.bbox[1] + item.bbox[3] for item in group)
    return left, top, right, bottom


def _directional_complexity(mask: np.ndarray) -> int:
    contours, _hierarchy = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    return sum(
        len(cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True))
        for contour in contours
        if len(contour) >= 3
    )


def _signature_like(
    group: tuple[_InkComponent, ...],
    labels: np.ndarray,
    *,
    minimum_height: float,
) -> SignatureRegion | None:
    left, top, right, bottom = _group_bounds(group)
    width = right - left
    height = bottom - top
    if (
        len(group) > 4
        or width < 20
        or height < max(5.0, minimum_height)
        or width < height * 2.8
    ):
        return None

    selected_labels = np.asarray([item.label for item in group], dtype=np.int32)
    local_labels = labels[top:bottom, left:right]
    mask = np.where(np.isin(local_labels, selected_labels), 255, 0).astype(np.uint8)
    area = int(cv2.countNonZero(mask))
    density = area / max(1.0, float(width * height))
    largest_component_width = max(item.bbox[2] for item in group)
    continuity = largest_component_width / max(1.0, float(width))
    complexity = _directional_complexity(mask)
    contours, _hierarchy = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    perimeter = sum(cv2.arcLength(contour, True) for contour in contours)
    foreground_points = cv2.findNonZero(mask)
    if foreground_points is None:
        return None
    convex_area = cv2.contourArea(cv2.convexHull(foreground_points))
    convex_solidity = area / max(1.0, float(convex_area))
    if (
        area < max(24, int(round(width * 0.45)))
        or density >= 0.38
        or continuity < 0.55
        or complexity < 8
        or perimeter / max(1.0, float(area)) > 1.15
        or convex_solidity > 0.58
    ):
        return None

    local_x, local_y, resolved_width, resolved_height = cv2.boundingRect(
        foreground_points
    )
    resolved = np.ascontiguousarray(
        mask[
            local_y : local_y + resolved_height,
            local_x : local_x + resolved_width,
        ],
        dtype=np.uint8,
    )
    return SignatureRegion(
        bbox=(
            left + local_x,
            top + local_y,
            resolved_width,
            resolved_height,
        ),
        mask=resolved,
    )


def detect_signature_regions(
    binary: np.ndarray,
    texts: Sequence[TextCandidate] = (),
) -> tuple[SignatureRegion, ...]:
    """Detect signature-shaped source strokes without reading OCR content.

    ``texts`` is retained only for API compatibility. It is deliberately ignored:
    text recognition, logo detection and signature detection are independent.
    """

    del texts
    foreground = _foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    non_rules = cv2.subtract(foreground, cv2.max(horizontal, vertical))
    labels, components = _component_boxes(non_rules)
    component_heights = np.asarray(
        [
            item.bbox[3]
            for item in components
            if item.bbox[2] > 1 and item.bbox[3] > 1
        ],
        dtype=np.float64,
    )
    minimum_height = (
        float(np.quantile(component_heights, 0.95))
        if len(component_heights) >= 8
        else 5.0
    )
    regions = [
        region
        for group in _component_groups(components)
        if (
            region := _signature_like(
                group,
                labels,
                minimum_height=minimum_height,
            )
        )
        is not None
    ]
    regions.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(regions)


def mark_signature_texts(
    texts: Sequence[TextCandidate],
    regions: Sequence[SignatureRegion],
) -> tuple[TextCandidate, ...]:
    """Compatibility shim that never changes a text object's type."""

    del regions
    return tuple(texts)


def mark_graphic_texts(
    texts: Sequence[TextCandidate],
    *,
    page_shape: tuple[int, int],
) -> tuple[TextCandidate, ...]:
    """Compatibility shim: OCR strings never classify Logo objects."""

    del page_shape
    return tuple(texts)


def suppress_signature_strokes(
    binary: np.ndarray,
    regions: Sequence[SignatureRegion],
) -> np.ndarray:
    """Remove only the exact source pixels assigned to signature regions."""

    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    for region in regions:
        x, y, width, height = region.bbox
        crop = result[y : y + height, x : x + width]
        if crop.shape == region.mask.shape:
            crop[region.mask > 0] = 255
    return result


def suppress_text_strokes(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
) -> np.ndarray:
    """Remove accepted OCR footprints while restoring source-supported rules."""

    if not texts:
        return np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    foreground = _foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    rules = cv2.max(horizontal, vertical)
    page_height, page_width = result.shape
    for item in texts:
        if item.kind not in {"text_candidate", "dimension_text_candidate"}:
            continue
        boxes = item.character_boxes or (item.bbox,)
        for x, y, width, height in boxes:
            left = max(0, int(x))
            top = max(0, int(y))
            right = min(page_width, int(x + width))
            bottom = min(page_height, int(y + height))
            if right <= left or bottom <= top:
                continue
            crop = result[top:bottom, left:right]
            crop[:] = 255
            crop[rules[top:bottom, left:right] > 0] = 0
    return result


def signature_rgba(region: SignatureRegion) -> np.ndarray:
    """Render the exact thresholded source footprint as transparent magenta."""

    alpha = np.where(region.mask > 0, 255, 0).astype(np.uint8)
    image = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    image[:, :, 0] = 255
    image[:, :, 2] = 255
    image[:, :, 3] = alpha
    return image


def add_signature_images(
    doc,
    layout,
    regions: Sequence[SignatureRegion],
    *,
    transform: Callable[[float, float], tuple[float, float]],
    output_path: str | Path,
    layer_name: str = "SIGNATURE_OVERLAY",
    name_prefix: str = "SIGNATURE",
) -> tuple[tuple[Path, ...], list[object], list[tuple[float, float]]]:
    """Write signature overlays beside the DXF and place them on the top layer."""

    dxf_path = Path(output_path).resolve()
    for stale_path in dxf_path.parent.glob(f"{dxf_path.stem}.signature-*.png"):
        stale_path.unlink(missing_ok=True)
    image_paths: list[Path] = []
    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    for index, region in enumerate(regions, start=1):
        x, y, width, height = region.bbox
        if width <= 0 or height <= 0 or region.mask.shape != (height, width):
            continue
        image_path = dxf_path.with_name(
            f"{dxf_path.stem}.signature-{index:03d}.png"
        )
        save_image(image_path, signature_rgba(region))
        image_paths.append(image_path)
        image_def = doc.add_image_def(
            filename=image_path.name,
            size_in_pixel=(width, height),
            name=f"{name_prefix}_{index:03d}",
        )
        bottom_left = transform(float(x), float(y + height))
        bottom_right = transform(float(x + width), float(y + height))
        top_left = transform(float(x), float(y))
        width_units = hypot(
            bottom_right[0] - bottom_left[0],
            bottom_right[1] - bottom_left[1],
        )
        height_units = hypot(
            top_left[0] - bottom_left[0],
            top_left[1] - bottom_left[1],
        )
        if width_units <= 0.0 or height_units <= 0.0:
            continue
        entity = layout.add_image(
            image_def=image_def,
            insert=bottom_left,
            size_in_units=(width_units, height_units),
            rotation=degrees(
                atan2(
                    bottom_right[1] - bottom_left[1],
                    bottom_right[0] - bottom_left[0],
                )
            ),
            dxfattribs={"layer": layer_name},
        )
        entity.dxf.flags = int(entity.dxf.flags) | 8
        entities.append(entity)
        bounds.extend((bottom_left, bottom_right, top_left))
    return tuple(image_paths), entities, bounds


def set_foreground_draw_order(layout, entities: Sequence[object]) -> None:
    handles = [
        str(entity.dxf.handle)
        for entity in entities
        if getattr(getattr(entity, "dxf", None), "handle", None)
    ]
    if handles:
        layout.set_redraw_order((handle, "0") for handle in handles)
