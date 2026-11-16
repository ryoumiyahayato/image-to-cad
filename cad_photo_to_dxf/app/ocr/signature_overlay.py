from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import atan2, degrees, hypot
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.core.image_loader import save_image
from app.geometry.structural_roi import verified_structural_rule_masks


@dataclass(frozen=True)
class SignatureVisualEvidence:
    source_component_count: int
    source_pixel_count: int
    density: float
    continuity: float
    directional_complexity: int
    positive_diagonal_span: float
    negative_diagonal_span: float
    bidirectional_diagonal_support: bool
    perimeter_per_pixel: float
    convex_solidity: float
    confidence: float

    def payload(self) -> dict[str, object]:
        return {
            "source_component_count": int(self.source_component_count),
            "source_pixel_count": int(self.source_pixel_count),
            "density": float(self.density),
            "continuity": float(self.continuity),
            "directional_complexity": int(self.directional_complexity),
            "positive_diagonal_span": float(self.positive_diagonal_span),
            "negative_diagonal_span": float(self.negative_diagonal_span),
            "bidirectional_diagonal_support": bool(
                self.bidirectional_diagonal_support
            ),
            "perimeter_per_pixel": float(self.perimeter_per_pixel),
            "convex_solidity": float(self.convex_solidity),
            "confidence": float(self.confidence),
            "evidence_source": "source_geometry_only",
        }


@dataclass(frozen=True)
class SignatureRegion:
    """One structurally detected handwriting footprint.

    The mask contains source pixels only. Source gray at an unambiguous ink
    edge can supplement the detected footprint for display.
    """

    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    visual_evidence: SignatureVisualEvidence | None = None

    def payload(self) -> dict[str, object]:
        return {
            "bbox": [int(value) for value in self.bbox],
            "mask_pixels": int(cv2.countNonZero(self.mask)),
            "visual_evidence": (
                None
                if self.visual_evidence is None
                else self.visual_evidence.payload()
            ),
        }


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
    if not components:
        return ()
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


def _bidirectional_diagonal_spans(mask: np.ndarray) -> tuple[float, float]:
    """Return the longest supported stroke in each diagonal direction.

    Long one-directional plan, leader and title-block strokes are not sufficient
    evidence for a signature IMAGE. A positive signature classification requires
    source-supported diagonals in both directions; otherwise its pixels remain in
    the ordinary outline pipeline.
    """

    height = int(mask.shape[0])
    lines = cv2.HoughLinesP(
        mask,
        1,
        np.pi / 180.0,
        threshold=max(8, height // 3),
        minLineLength=max(8, height // 2),
        maxLineGap=max(2, height // 6),
    )
    positive_span = 0.0
    negative_span = 0.0
    if lines is None:
        return positive_span, negative_span

    minimum_vertical_span = max(2.0, height * 0.20)
    for x1, y1, x2, y2 in lines[:, 0]:
        dx = int(x2) - int(x1)
        dy = int(y2) - int(y1)
        if abs(dy) < minimum_vertical_span:
            continue
        span = hypot(dx, dy)
        if dx * dy > 0:
            positive_span = max(positive_span, span)
        elif dx * dy < 0:
            negative_span = max(negative_span, span)
    return positive_span, negative_span


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
    perimeter_per_pixel = perimeter / max(1.0, float(area))
    positive_diagonal_span, negative_diagonal_span = (
        _bidirectional_diagonal_spans(mask)
    )
    bidirectional_diagonal_support = bool(
        positive_diagonal_span >= height
        and negative_diagonal_span >= height
    )
    if (
        area < max(24, int(round(width * 0.45)))
        or density >= 0.38
        or continuity < 0.55
        or complexity < 8
        or perimeter_per_pixel > 1.15
        or convex_solidity > 0.58
        or not bidirectional_diagonal_support
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
        visual_evidence=SignatureVisualEvidence(
            source_component_count=len(group),
            source_pixel_count=area,
            density=density,
            continuity=continuity,
            directional_complexity=complexity,
            positive_diagonal_span=positive_diagonal_span,
            negative_diagonal_span=negative_diagonal_span,
            bidirectional_diagonal_support=(
                bidirectional_diagonal_support
            ),
            perimeter_per_pixel=perimeter_per_pixel,
            convex_solidity=convex_solidity,
            confidence=float(
                np.mean(
                    (
                        min(1.0, continuity),
                        1.0 - density,
                        min(1.0, complexity / 16.0),
                        1.0 - convex_solidity,
                    )
                )
            ),
        ),
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


def signature_field_regions(binary: np.ndarray, texts: Sequence[TextCandidate]) -> tuple[SignatureRegion, ...]:
    return signature_field_sources(binary, texts)[0]


def signature_field_sources(
    binary: np.ndarray, texts: Sequence[TextCandidate],
) -> tuple[tuple[SignatureRegion, ...], np.ndarray]:
    """Preserve source ink in explicitly labelled, source-ruled signing fields.

    OCR locates the printed field heading; it never supplies signature content.
    Connected source components may extend outside their cell. Printed names in
    the adjacent column are independent components and remain ordinary TEXT.
    """
    from app.ocr.ocr_layout import _projection_centers

    headings = [t for t in texts if t.text.strip().casefold() in
                {"signature", "signed", "签字", "签名"}]
    protected_rules = np.zeros_like(binary)
    if not headings:
        return (), protected_rules
    foreground = _foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    regions, seen = [], set()
    assigned_ink = np.zeros_like(foreground)
    page_h, page_w = binary.shape
    for heading in headings:
        x, y, w, h = heading.bbox
        center_x, center_y = x+w*.5, y+h*.5
        top, bottom = max(0, y-h), min(page_h, y+2*h)
        ruled_columns = np.count_nonzero(vertical[top:bottom], axis=0) > (bottom-top)*.7
        xs = _projection_centers(ruled_columns)
        lefts, rights = [v for v in xs if v < center_x], [v for v in xs if v > center_x]
        if not lefts or not rights:
            continue
        left, right = max(lefts), min(rights)
        if right-left > w*4 or right-left < w*.8:
            continue
        ruled_rows = np.count_nonzero(horizontal[:, left+2:right-2], axis=1) > (right-left-4)*.8
        ys = _projection_centers(ruled_rows)
        # Only the field's complete row/column projections establish rules.
        # Other long strokes inside a signed cell remain source ink even when
        # handwriting happens to contain horizontal/vertical intersections.
        field_rules = np.zeros_like(foreground)
        field_rules[ruled_rows] = horizontal[ruled_rows]
        field_rules[:, ruled_columns] = cv2.max(
            field_rules[:, ruled_columns], vertical[:, ruled_columns]
        )
        labels, components = _component_boxes(cv2.subtract(foreground, field_rules))
        by_label = {c.label: c for c in components}
        below = [v for v in ys if v > center_y]
        for row_top, row_bottom in zip(below, below[1:]):
            if (left, right, row_top, row_bottom) in seen:
                continue
            row_height = row_bottom-row_top
            if row_height < h*.7 or row_height > h*4:
                break
            if any(np.count_nonzero(vertical[row_top:row_bottom, max(0, edge-2):edge+3]) < row_height*.6
                   for edge in (left, right)):
                break
            seen.add((left, right, row_top, row_bottom))
            seed = labels[row_top+2:row_bottom-1, left+3:right-2]
            selected = [by_label[int(v)] for v in np.unique(seed) if int(v) in by_label
                        and by_label[int(v)].area >= 4
                        and by_label[int(v)].bbox[2] < (right-left)*2
                        and by_label[int(v)].bbox[3] < row_height*2]
            if not selected:
                continue
            band = max(2, int(round(h * .25)))
            rule_widths = [
                np.count_nonzero(np.count_nonzero(
                    vertical[row_top:row_bottom, max(0, edge-band):min(page_w, edge+band+1)],
                    axis=0,
                ) >= row_height * .6)
                for edge in (left, right)
            ]
            radius = max(1, int(max(rule_widths)) + 1)
            bridge_kernel = np.ones((2*radius+1, 2*radius+1), np.uint8)
            # A table rule can split a real pen stroke into two components.
            # Follow source-supported neighbours across that narrow rule only;
            # do not claim an adjacent printed name from its bounding box.
            for _ in range(2):
                sx, sy, sr, sb = _group_bounds(tuple(selected))
                lx, ty = max(0, sx-radius), max(0, sy-radius)
                rx, by = min(page_w, sr+radius), min(page_h, sb+radius)
                local_labels = labels[ty:by, lx:rx]
                selected_labels = [c.label for c in selected]
                current = np.isin(local_labels, selected_labels).astype(np.uint8)
                nearby = cv2.dilate(current, bridge_kernel) > 0
                near_rule = cv2.dilate(
                    field_rules[ty:by, lx:rx],
                    bridge_kernel,
                ) > 0
                additions = [by_label[int(v)] for v in np.unique(local_labels[nearby & near_rule])
                             if int(v) in by_label and int(v) not in selected_labels
                             and by_label[int(v)].area >= 4
                             and by_label[int(v)].bbox[2] < (right-left)*2
                             and by_label[int(v)].bbox[3] < row_height*2]
                if not additions:
                    break
                selected.extend(additions)
            bx, by, br, bb = _group_bounds(tuple(selected))
            # These are independently measured cell rules, not the signature's
            # dilated replacement footprint. Keep adjacent rule ink out of that
            # footprint even when the pen touches or crosses a cell boundary.
            window = np.s_[max(0, row_top-h):min(page_h, row_bottom+h),
                           max(0, min(left, bx)-h):min(page_w, max(right, br)+h)]
            protected_rules[window] = cv2.max(protected_rules[window], field_rules[window])
            mask = np.where(np.isin(labels[by:bb, bx:br], [c.label for c in selected]), 255, 0).astype(np.uint8)
            # Restore only original intersection pixels next to signature ink.
            # Single-image crossings are ambiguous; never invent a stroke.
            crossing = cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0
            mask[crossing & (foreground[by:bb, bx:br] > 0)] = 255
            # A stroke spanning two rows can seed both cells. Retain its source
            # opacity once; overlapping transparent images must not darken it.
            assigned = assigned_ink[by:bb, bx:br]
            mask[assigned > 0] = 0
            if not np.any(mask):
                continue
            assigned[mask > 0] = 255
            regions.append(SignatureRegion((bx, by, br-bx, bb-by), mask))
    return tuple(regions), protected_rules


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


def source_ink_region(region, gray: np.ndarray):
    """Reuse the foreground mask as source ink opacity, preserving gray detail.

    On white paper, black RGB plus alpha=(255-source gray) reproduces the ink.
    Unclaimed background stays fully transparent, including scan gray paper.
    """
    x, y, width, height = region.bbox
    crop = gray[y:y+height, x:x+width]
    if crop.shape != region.mask.shape:
        raise ValueError('Graphic source crop does not match its mask')
    return replace(region, mask=np.where(region.mask > 0, 255-crop, 0).astype(np.uint8))


def restore_signature_edge_gray(
    region: SignatureRegion,
    gray: np.ndarray,
    *,
    contour_binary: np.ndarray,
    protected_masks: Sequence[np.ndarray | None] = (),
) -> SignatureRegion:
    """Keep source gray next to owned ink inside the existing signing crop."""
    x, y, width, height = region.bbox
    left, top = max(0, x - 1), max(0, y - 1)
    right = min(gray.shape[1], x + width + 1)
    bottom = min(gray.shape[0], y + height + 1)
    window = np.s_[top:bottom, left:right]
    interior = np.s_[y-top:y-top+height, x-left:x-left+width]
    patch = gray[window]
    owned = np.zeros(patch.shape, dtype=bool)
    owned[interior] = region.mask >= 128
    protected = (patch < 128) & ~owned
    for mask in protected_masks:
        if mask is not None:
            protected |= mask[window] > 0
    neighbors = np.ones((3, 3), dtype=np.uint8)
    near_ink = cv2.dilate(np.uint8(owned & ~protected), neighbors) > 0
    near_conflict = cv2.dilate(np.uint8(protected), neighbors) > 0
    crop = patch[interior]
    restore = (
        near_ink[interior] & ~near_conflict[interior]
        & (region.mask == 0) & (crop >= 128) & (crop < 255)
        & (contour_binary[window][interior] == 255)
    )
    if not np.any(restore):
        return region
    alpha = region.mask.copy()
    alpha[restore] = 255 - crop[restore]
    return replace(region, mask=alpha)


def signature_rgba(region: SignatureRegion) -> np.ndarray:
    """Render the exact source foreground with transparent paper background."""

    alpha = np.ascontiguousarray(region.mask, dtype=np.uint8).copy()
    image = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    image[:, :, 3] = alpha
    return image


def _signature_ink_hatch(layout, region, transform, layer_name):
    """Encode source pixel cells, including holes, without a paper rectangle.

    ACI 7 is CAD's background-aware black/white, not fixed white RGB. Keep the
    original alpha PNG separately; native ink preserves its nonzero footprint.
    """
    x, y, _width, _height = region.bbox
    hatch = layout.add_hatch(color=7, dxfattribs={"layer": layer_name})
    for row_index, row in enumerate(region.mask > 0):
        edges = np.diff(np.r_[False, row, False].astype(np.int8))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            corners = ((x+start, y+row_index), (x+end, y+row_index),
                       (x+end, y+row_index+1), (x+start, y+row_index+1))
            hatch.paths.add_polyline_path(
                [transform(float(a), float(b)) for a, b in corners],
                is_closed=True, flags=1,
            )
    return hatch


def _source_alpha_runs(layout, region, transform, layer_name):
    """Single-loop HATCH members retain source pixel cells and opacity.

    Unlike the legacy compound HATCH, neighbouring rectangles do not compete
    as external loops in one fill. Each region remains one movable CAD block.
    """
    x,y,_,_=region.bbox
    entities=[]
    active={}
    rectangles=[]
    for row_index,row in enumerate(np.vstack([region.mask,np.zeros((1,region.mask.shape[1]),np.uint8)])):
        changes=np.flatnonzero(np.diff(np.r_[0,row,0].astype(int)))
        runs={(int(a),int(b),int(row[a])) for a,b in zip(changes,changes[1:]) if a<len(row) and row[a]}
        for key,start in list(active.items()):
            if key not in runs:
                rectangles.append((*key,start,row_index))
                del active[key]
        for key in runs:
            active.setdefault(key,row_index)
    for start,end,alpha,top,bottom in rectangles:
        e=layout.add_hatch(color=7,dxfattribs={'layer':layer_name})
        e.paths.add_polyline_path([transform(a,b) for a,b in (
            (x+start,y+top),(x+end,y+top),(x+end,y+bottom),(x+start,y+bottom))],is_closed=True,flags=1)
        e.dxf.transparency=0x02000000 | alpha
        entities.append(e)
    return entities


def _adaptive_tone_rgba(alpha: np.ndarray) -> np.ndarray:
    """A neutral overlay blends either CAD foreground or paper toward gray.

    With an ACI 7 core at alpha >= 128, this recovers source contrast on both
    black and white canvas without relying on DXF vector transparency.
    """
    image = np.full((*alpha.shape, 4), 128, dtype=np.uint8)
    image[:, :, 3] = 2 * np.minimum(alpha, 255-alpha)
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
    asset_kind: str = "signature",
    presentation: str = "legacy",
    signing_boxes: Sequence[tuple[int, int, int, int]] = (),
    source_origin: tuple[int, int] = (0, 0),
    shared_caption: tuple[str, tuple[int, int, int, int]] | None = None,
    fixed_member_boxes: Sequence[tuple[int, int, int, int]] = (),
    fixed_layer_name: str | None = None,
) -> tuple[tuple[Path, ...], list[object], list[tuple[float, float]]]:
    """Write source PNGs; use native adaptive ink for signatures, IMAGE for logos."""

    dxf_path = Path(output_path).resolve()
    for stale_path in dxf_path.parent.glob(f"{dxf_path.stem}.{asset_kind}-*.png"):
        stale_path.unlink(missing_ok=True)
    image_paths: list[Path] = []
    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    for index, region in enumerate(regions, start=1):
        x, y, width, height = region.bbox
        if width <= 0 or height <= 0 or region.mask.shape != (height, width):
            continue
        fixed = fixed_layer_name is not None and region.bbox in fixed_member_boxes
        asset_layer = fixed_layer_name if fixed else layer_name
        image_path = dxf_path.with_name(
            f"{dxf_path.stem}.{asset_kind}-{index:03d}.png"
        )
        save_image(image_path, signature_rgba(region))
        image_paths.append(image_path)
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
        mode = "adaptive-source-image" if region.bbox in signing_boxes else presentation
        if getattr(region, "visual_kind", "") == "engineering_graphic":
            mode = "legacy"
        if mode == "native-alpha":
            from app.export.source_component import source_component
            members=_source_alpha_runs(layout,region,transform,asset_layer)
            if not members:
                continue
            entity=source_component(doc,layout,members,f'{name_prefix}_{index:03d}',
                [{'id':f'{asset_kind}/{index}','object_index':index,'role':'protected_source_ink'}])
        elif asset_kind == "signature" and mode == "legacy":
            entity = _signature_ink_hatch(layout, region, transform, asset_layer)
            doc.layers.get(asset_layer).lock()
        else:
            display_path = image_path
            core = []
            if mode == "adaptive-source-image":
                display_path = dxf_path.with_name(
                    f"{dxf_path.stem}.{asset_kind}-tone-{index:03d}.png"
                )
                save_image(display_path, _adaptive_tone_rgba(region.mask))
                image_paths.append(display_path)
                opaque = np.where(region.mask >= 128, 255, 0).astype(np.uint8)
                core = _source_alpha_runs(layout, replace(region, mask=opaque), transform, asset_layer)
            image_def = doc.add_image_def(
                filename=display_path.name, size_in_pixel=(width, height),
                name=f"{name_prefix}_{index:03d}",
            )
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
                dxfattribs={"layer": asset_layer},
            )
            entity.dxf.flags = int(entity.dxf.flags) | 8
            if mode == "adaptive-source-image":
                from app.export.source_component import source_component

                entity = source_component(
                    doc, layout, [*core, entity], f"{name_prefix}_{index:03d}",
                    [{"id": f"{asset_kind}/{index}", "object_index": index,
                      "role": "protected_source_ink"}],
                )
        if mode != "legacy":
            doc.layers.get(asset_layer).lock()
        if 'IMAGE_TO_CAD' not in doc.appids:
            doc.appids.add('IMAGE_TO_CAD')
        object_class = {
            "engineering": "GRAPHIC", "logo": "LOGO", "signature": "SIGNATURE",
            "stamp": "STAMP", "signing-shared": "SHARED_SIGNING_INK",
        }.get(asset_kind, "SIGNATURE")
        if getattr(region, "visual_kind", "") == "engineering_graphic":
            object_class = "GRAPHIC"
        entity.set_xdata('IMAGE_TO_CAD', [(1000, object_class),
                         (1000, ','.join(str(v) for v in region.bbox)),
                         (1000, image_path.name)])
        if region.bbox in signing_boxes or asset_kind in {"stamp", "signing-shared"}:
            appid = "SIGNING_SOURCE"
            if appid not in doc.appids:
                doc.appids.add(appid)
            dx, dy = source_origin
            state = (
                "UNRESOLVED_OVERLAP" if asset_kind == "signing-shared"
                else "UNRESOLVED_MEMBER_FIXED" if fixed else "EXCLUSIVE_INK"
            )
            tags = [
                (1000, state),
                (1000, ",".join(map(str, (x+dx, y+dy, width, height)))),
            ]
            if shared_caption is not None:
                reading, (cx, cy, cw, ch) = shared_caption
                tags.extend(((1000, reading), (1000, ",".join(map(str, (cx+dx, cy+dy, cw, ch))))))
            entity.set_xdata(appid, tags)
        entities.append(entity)
        bounds.extend((bottom_left, bottom_right, top_left))
    return tuple(image_paths), entities, bounds


def set_foreground_draw_order(layout, entities: Sequence[object]) -> None:
    background = [e for e in entities if e.dxftype() == "HATCH"]
    if background:
        selected = {e.dxf.handle for e in entities}
        ordered = [*background,
                   *(e for e in layout if e.dxf.handle not in selected),
                   *(e for e in entities if e not in background)]
        layout.set_redraw_order((e.dxf.handle, format(i+1, "X")) for i, e in enumerate(ordered))
        return
    handles = [
        str(entity.dxf.handle)
        for entity in entities
        if getattr(getattr(entity, "dxf", None), "handle", None)
    ]
    if handles:
        layout.set_redraw_order((handle, "0") for handle in handles)
