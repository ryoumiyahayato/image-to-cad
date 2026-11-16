from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from app.geometry.structural_roi import verified_structural_rule_masks


LOGO_VISUAL_KINDS = ("graphic_mark", "wordmark")


@dataclass(frozen=True)
class LogoRegion:
    """A compact source-geometry cluster classified without OCR semantics."""

    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    structural_score: float
    hole_count: int
    contour_count: int
    visual_kind: str = "graphic_mark"
    density: float = 0.0
    closed_complexity: int = 0
    reflection_similarity: float = 0.0

    def payload(self) -> dict[str, object]:
        return {
            "bbox": [int(value) for value in self.bbox],
            "mask_pixels": int(cv2.countNonZero(self.mask)),
            "visual_kind": self.visual_kind,
            "structural_score": float(self.structural_score),
            "hole_count": int(self.hole_count),
            "contour_count": int(self.contour_count),
            "density": float(self.density),
            "closed_complexity": int(self.closed_complexity),
            "reflection_similarity": float(self.reflection_similarity),
            "evidence_source": "source_geometry_only",
        }


def _foreground(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Logo source must be a non-empty binary page")
    if binary.dtype != np.uint8:
        raise ValueError("Logo source must be an 8-bit binary page")
    return np.where(binary < 128, 255, 0).astype(np.uint8)


def _contour_holes(
    mask: np.ndarray,
) -> tuple[list[np.ndarray], int]:
    contours, hierarchy = cv2.findContours(
        mask,
        cv2.RETR_CCOMP,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if hierarchy is None:
        return contours, 0
    holes = sum(1 for entry in hierarchy[0] if int(entry[3]) >= 0)
    return contours, holes


def _reflection_similarity(mask: np.ndarray) -> float:
    source = mask > 0
    similarities: list[float] = []
    for reflected in (
        np.fliplr(source),
        np.flipud(source),
        np.flipud(np.fliplr(source)),
    ):
        union = int(np.count_nonzero(source | reflected))
        similarities.append(
            int(np.count_nonzero(source & reflected)) / max(1, union)
        )
    return max(similarities)


def _candidate_from_component(
    labels: np.ndarray,
    label: int,
    bbox: tuple[int, int, int, int],
    *,
    median_extent: float,
) -> LogoRegion | None:
    x, y, width, height = bbox
    if width < median_extent * 1.4 or height < median_extent * 1.4:
        return None
    aspect = width / max(1.0, float(height))
    if not 0.32 <= aspect <= 3.4:
        return None
    local = np.where(
        labels[y : y + height, x : x + width] == label,
        255,
        0,
    ).astype(np.uint8)
    area = int(cv2.countNonZero(local))
    density = area / max(1.0, float(width * height))
    contours, hole_count = _contour_holes(local)
    outer_count = max(0, len(contours) - hole_count)
    closed_complexity = sum(
        len(cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True))
        for contour in contours
        if len(contour) >= 3
    )
    reflection_similarity = _reflection_similarity(local)
    if (
        hole_count < 2
        or outer_count < 1
        or closed_complexity < 12
        or not 0.08 <= density <= 0.72
        or reflection_similarity < 0.32
    ):
        return None
    score = min(
        1.0,
        0.35
        + min(hole_count, 6) * 0.08
        + min(closed_complexity, 40) / 120.0
        + reflection_similarity * 0.2,
    )
    return LogoRegion(
        bbox=bbox,
        mask=local,
        structural_score=score,
        hole_count=hole_count,
        contour_count=len(contours),
        visual_kind="graphic_mark",
        density=density,
        closed_complexity=closed_complexity,
        reflection_similarity=reflection_similarity,
    )


def detect_logo_regions(binary: np.ndarray) -> tuple[LogoRegion, ...]:
    """Detect conservative logo geometry without reading OCR text or page position."""

    foreground = _foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    non_rules = cv2.subtract(foreground, cv2.max(horizontal, vertical))
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        non_rules,
        connectivity=8,
    )
    if count <= 1:
        return ()
    distance = cv2.distanceTransform(non_rules, cv2.DIST_L2, 3)
    stroke_samples = distance[non_rules > 0]
    if not stroke_samples.size:
        return ()
    component_extents = np.asarray(
        [
            max(
                int(stats[label, cv2.CC_STAT_WIDTH]),
                int(stats[label, cv2.CC_STAT_HEIGHT]),
            )
            for label in range(1, count)
            if int(stats[label, cv2.CC_STAT_AREA]) >= 3
        ],
        dtype=np.float64,
    )
    population_extent = (
        float(np.quantile(component_extents, 0.995))
        if len(component_extents) >= 8
        else 0.0
    )
    median_extent = max(
        2.0,
        float(np.median(stroke_samples)) * 4.0,
        population_extent,
    )
    regions: list[LogoRegion] = []
    for label in range(1, count):
        x, y, width, height, area = (
            int(value) for value in stats[label]
        )
        if area < 12:
            continue
        region = _candidate_from_component(
            labels,
            label,
            (x, y, width, height),
            median_extent=median_extent,
        )
        if region is not None:
            regions.append(region)
    regions.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(regions)


def _outlined_row(ink: np.ndarray) -> bool:
    """Require enclosed outline ink, not just rows of similarly sized glyphs."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink)
    outlined_pixels = 0
    outlined_components = 0
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < 8:
            continue
        component = np.uint8(labels[y:y+h, x:x+w] == index)
        _, holes = _contour_holes(component)
        if holes:
            outlined_components += 1
            outlined_pixels += area
    return outlined_components >= 4 and outlined_pixels >= .85 * np.count_nonzero(ink)


def source_logo_lockup(mark: LogoRegion, gray: np.ndarray, *, line_ink=None,
                       text_candidates=()) -> LogoRegion:
    """Extend a proved interleaved mark to its isolated stacked wordmark."""
    x, y, w, h = mark.bbox
    left, right = x - round(.7*h), x + w + round(.7*h)
    top, bottom = y - round(.16*h), y + h + round(1.1*h)
    if left < 0 or top < 0 or right > gray.shape[1] or bottom > gray.shape[0]:
        return mark
    window = gray[top:bottom, left:right]
    ink = window < 255
    edges = np.flatnonzero(np.diff(np.any(ink, axis=1), prepend=False, append=False))
    if len(edges) != 6:
        return mark
    mark_top, mark_bottom, upper_top, upper_bottom, lower_top, lower_bottom = edges
    if not (mark_top >= .07*h and len(ink)-lower_bottom >= .18*h
            and .12*h <= upper_top-mark_bottom <= .34*h
            and .035*h <= lower_top-upper_bottom <= .15*h
            and .20*h <= upper_bottom-upper_top <= .40*h
            and .08*h <= lower_bottom-lower_top <= .22*h):
        return mark

    strong = window < 128
    mark_crop = strong[y-top:y-top+h, x-left:x-left+w]
    if (not np.array_equal(mark_crop, mark.mask >= 128)
            or np.count_nonzero(strong[mark_top:mark_bottom]) != np.count_nonzero(mark_crop)):
        return mark

    widths = []
    for start, stop in ((upper_top, upper_bottom), (lower_top, lower_bottom)):
        row = strong[start:stop]
        columns = np.flatnonzero(np.any(row, axis=0))
        if not len(columns) or not _outlined_row(row.astype(np.uint8)):
            return mark
        first, last = columns[0]+left, columns[-1]+left+1
        if abs((first+last)/2 - (x+w/2)) > .08*w:
            return mark
        widths.append(last-first)
    upper_width, lower_width = widths
    if not (1.05*w <= upper_width <= 1.55*w and .7*upper_width <= lower_width <= upper_width):
        return mark

    columns = np.flatnonzero(np.any(ink, axis=0))
    start, stop = columns[0], columns[-1]+1
    if min(start, window.shape[1]-stop) < .07*h:
        return mark
    if line_ink is not None and np.any(ink & (line_ink[top:bottom, left:right] > 0)):
        return mark

    # The late ownership step must be able to retire a whole text candidate.
    # Keep the old representation when the candidate also covers foreign ink.
    for candidate in text_candidates:
        cx, cy, cw, ch = candidate.bbox
        left_coord, t = max(left, cx), max(top, cy)
        r, b = min(right, cx+cw), min(bottom, cy+ch)
        if left_coord >= r or t >= b:
            continue
        claimed = np.count_nonzero(strong[t-top:b-top, left_coord-left:r-left])
        if claimed and claimed != np.count_nonzero(gray[cy:cy+ch, cx:cx+cw] < 128):
            return mark

    local = np.uint8(ink[mark_top:lower_bottom, start:stop]) * 255
    contours, holes = _contour_holes(local)
    return replace(mark, bbox=(int(left+start), int(top+mark_top),
                               int(stop-start), int(lower_bottom-mark_top)),
                   mask=local, visual_kind="wordmark", hole_count=holes,
                   contour_count=len(contours), density=np.count_nonzero(local)/local.size)


def source_logo_objects(binary: np.ndarray, *, source_gray=None, line_ink=None,
                        text_candidates=()) -> tuple[LogoRegion, ...]:
    """Recover whole marks from source components, after LINE authority commits.

    A filled, patterned diamond or interleaved large outline components supply
    positive graphic evidence. No OCR strings or page coordinates classify logos.
    Unlike the detector used for line protection, this reads the original ink;
    cleanup must not be allowed to erase a mark before representation is chosen.
    """
    foreground = _foreground(binary)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
    heights = [r[3] for r in stats[1:] if r[4] >= 12 and r[2] > 2 and r[3] > 2]
    typical = max(6.0, float(np.quantile(heights, .90))) if heights else 6.0
    maximum = min(binary.shape) * .12
    regions = []

    def region_for(selected):
        boxes = stats[list(selected)]
        x, y = boxes[:, 0].min(), boxes[:, 1].min()
        right = (boxes[:, 0] + boxes[:, 2]).max()
        bottom = (boxes[:, 1] + boxes[:, 3]).max()
        mask = np.where(np.isin(labels[y:bottom, x:right], selected), 255, 0).astype(np.uint8)
        contours, holes = _contour_holes(mask)
        return LogoRegion((int(x), int(y), int(right-x), int(bottom-y)), mask,
                          .98, holes, len(contours), density=np.count_nonzero(mask)/mask.size)

    seeds = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if not typical * 1.7 <= h <= maximum or not .3 <= w/h <= 3.4:
            continue
        mask = np.where(labels[y:y+h, x:x+w] == label, 255, 0).astype(np.uint8)
        contours, holes = _contour_holes(mask)
        density = area / (w*h)
        outer = max(contours, key=cv2.contourArea, default=None)
        if outer is None:
            continue
        vertices = cv2.approxPolyDP(outer, .035*cv2.arcLength(outer, True), True)[:, 0]
        edges = np.roll(vertices, -1, axis=0) - vertices
        diagonal = len(vertices) == 4 and all(
            .45 < abs(float(dx))/max(abs(float(dy)), .001) < 2.2 for dx, dy in edges)
        if diagonal and .75 < w/h < 1.33 and .18 < density < .78 and holes >= 2:
            regions.append(region_for([label]))
        elif h >= typical * 2.1 and density < .18 and len(vertices) >= 6:
            seeds.append(label)

    # Interleaved pieces have overlapping bounding extents but distinct ink.
    # Ordinary letters separated by spaces do not satisfy this relation.
    groups = []
    for label in sorted(seeds, key=lambda i: stats[i, 0]):
        x, y, w, h, _ = stats[label]
        matches = []
        for group in groups:
            if any(min(x+w, stats[j, 0]+stats[j, 2])-max(x, stats[j, 0]) > min(w, stats[j, 2])*.08
                   and min(y+h, stats[j, 1]+stats[j, 3])-max(y, stats[j, 1]) > min(h, stats[j, 3])*.55
                   for j in group):
                matches.append(group)
        if matches:
            merged = [label, *(j for group in matches for j in group)]
            groups = [g for g in groups if g not in matches] + [merged]
        else:
            groups.append([label])
    for group in groups:
        if len(group) < 3:
            continue
        box = region_for(group).bbox
        x, y, w, h = box
        if not 1.8 < w/h < 5.5:
            continue
        selected = list(group)
        for label in range(1, count):
            lx, ly, lw, lh, area = stats[label]
            if area >= 8 and x-h*.25 <= lx <= x+w+h*.55 and y <= ly and ly+lh <= y+h+2:
                selected.append(label)
        mark = region_for(sorted(set(selected)))
        if source_gray is not None:
            mark = source_logo_lockup(mark, source_gray, line_ink=line_ink,
                                      text_candidates=text_candidates)
        regions.append(mark)
    return tuple(sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0])))
