"""Bounded source-backed presentation, downstream of structural authority.

No OCR semantics or symbol vocabulary. Ambiguous ink remains in its existing
representation; a dark bridge alone never authorizes merging wall boundaries.
"""

from dataclasses import replace
from collections import Counter
from math import hypot

import cv2
import numpy as np

from app.ocr.logo_detection import LogoRegion


LINEWEIGHTS = {"HAIRLINE": 13, "THIN": 25, "MEDIUM": 50, "THICK": 100}


def source_fill_records(gray, paths, texts=(), *, excluded_indices=()):
    """Retain compact, uniform source fills as native editable HATCH regions.

    Never infer a centerline through a filled region. Text, nested contours,
    enclosures and elongated frame/table rules retain their existing ownership.
    Patterned or uneven ink remains unclassified rather than inventing a fill.
    """
    parents = {p.parent for p in paths if p.parent is not None}
    output = {}
    for i, path in enumerate(paths):
        if (
            i in excluded_indices
            or i in parents
            or path.depth % 2
            or len(path.points) < 3
        ):
            continue
        points = np.asarray(path.points, np.float32)
        x, y, w, h = cv2.boundingRect(points)
        if (
            min(w, h) < 6
            or max(w, h) > min(gray.shape) * 0.04
            or max(w, h) / min(w, h) > 4
        ):
            continue
        if any(
            max(x, a) < min(x + w, a + c) and max(y, b) < min(y + h, b + d)
            for a, b, c, d in (text.bbox for text in texts)
        ):
            continue
        if x < 0 or y < 0 or x + w > gray.shape[1] or y + h > gray.shape[0]:
            continue
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.rint(points - [x, y]).astype(np.int32)], 255)
        core = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
        values = gray[y : y + h, x : x + w][core]
        if (
            len(values) < 16
            or np.mean(values < 128) < 0.95
            or np.percentile(values, 90) - np.percentile(values, 10) > 8
        ):
            continue
        output[str(i)] = {
            "kind": "SOURCE_FILL",
            "source_gray": int(np.median(values)),
            "source_support": "compact closed region; uniform source-supported dark interior; no text or nested hole",
            "ownership_class": "existing editable boundary; fill presentation only",
        }
    return output


def source_orientation_graphics(gray):
    """Isolated round emblem with a substantial asymmetric filled interior.

    A ring containing ordinary text has no broad filled core. A box, shaft or
    grid junction has no circular perimeter and isolated surrounding paper.
    Nearby detached ink is owned only inside the isolated object's scale-bound
    neighbourhood (e.g. the direction label); no character is recognized.
    """
    # Faint anti-aliased perimeter pixels may establish connectivity; the
    # substantial filled-core test still uses dark source ink below 128.
    ink = (gray < 240).astype(np.uint8)
    proposal = ink
    count, labels, stats, centers = cv2.connectedComponentsWithStats(proposal, 8)
    objects = []
    for i in range(1, count):
        x, y, w, h, area = map(int, stats[i])
        if (
            min(w, h) < 20
            or max(w, h) > min(gray.shape) * 0.45
            or not 0.85 < w / h < 1.18
        ):
            continue
        radius = (w + h) / 4
        internal = [
            int(j)
            for j in np.unique(labels[y : y + h, x : x + w])
            if j not in (0, i)
            and stats[j, 0] >= x
            and stats[j, 1] >= y
            and stats[j, 0] + stats[j, 2] <= x + w
            and stats[j, 1] + stats[j, 3] <= y + h
        ]
        proposal_mask = np.isin(labels[y : y + h, x : x + w], [i, *internal]).astype(
            np.uint8
        )
        mask = proposal_mask * ink[y : y + h, x : x + w]
        area = int(mask.sum())
        if not 0.08 < area / (np.pi * radius**2) < 0.55:
            continue
        contours, hierarchy = cv2.findContours(
            proposal_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
        )
        if hierarchy is None or not np.any(hierarchy[0, :, 3] >= 0):
            continue
        outer = max(contours, key=cv2.contourArea).reshape(-1, 2)
        center = np.array([(w - 1) / 2, (h - 1) / 2])
        distances = np.linalg.norm(outer - center, axis=1)
        if np.mean(np.abs(distances - radius) < radius * 0.10) < 0.88:
            continue
        if (
            cv2.distanceTransform(
                mask * (gray[y : y + h, x : x + w] < 128), cv2.DIST_L2, 3
            ).max()
            < radius * 0.12
        ):
            continue
        yy, xx = np.where(mask)
        inner = (
            np.linalg.norm(np.column_stack((xx, yy)) - center, axis=1) < radius * 0.75
        )
        if inner.sum() < np.pi * radius**2 * 0.045:
            continue
        eigenvalues = np.linalg.eigvalsh(
            np.cov(np.column_stack((xx[inner], yy[inner])).T)
        )
        if eigenvalues[-1] / max(eigenvalues[0], 1) < 2.5:
            continue
        cx, cy = x + center[0], y + center[1]
        # Exclude any long continuing component entering the object's halo.
        nearby = []
        veto = False
        halo = int(np.ceil(radius * 1.65))
        ax, ay = max(0, int(cx) - halo), max(0, int(cy) - halo)
        bx, by = (
            min(gray.shape[1], int(cx) + halo + 1),
            min(gray.shape[0], int(cy) + halo + 1),
        )
        hy, hx = np.indices((by - ay, bx - ax))
        neighbourhood = labels[ay:by, ax:bx][
            (hx + ax - cx) ** 2 + (hy + ay - cy) ** 2 < (radius * 1.65) ** 2
        ]
        for j in np.unique(neighbourhood):
            if j == 0:
                continue
            if j == i or j in internal:
                continue
            a, b, c, d, pixels = map(int, stats[j])
            dx = max(a - cx, cx - (a + c), 0)
            dy = max(b - cy, cy - (b + d), 0)
            if hypot(dx, dy) > radius * 1.65:
                continue
            if max(c, d) > radius * 0.9:
                veto = True
                break
            if pixels >= 4:
                nearby.append(j)
        if veto:
            continue
        members = [i, *internal, *nearby]
        left = min(int(stats[j, 0]) for j in members)
        top = min(int(stats[j, 1]) for j in members)
        right = max(int(stats[j, 0] + stats[j, 2]) for j in members)
        bottom = max(int(stats[j, 1] + stats[j, 3]) for j in members)
        owned = (
            np.isin(labels[top:bottom, left:right], members).astype(np.uint8)
            * ink[top:bottom, left:right]
            * 255
        )
        objects.append(
            LogoRegion(
                (left, top, right - left, bottom - top),
                owned,
                1.0,
                int(np.sum(hierarchy[0, :, 3] >= 0)),
                len(contours),
                visual_kind="engineering_graphic",
                density=float(owned.mean() / 255),
            )
        )
    return tuple(objects)


def stroke_profile(gray, line):
    """Sample the connected dark run normal to a line, avoiding end junctions.

    A paper/grey trough creates separate runs. Return width only for a stable
    supported run, so glyph crossings and hatching cannot thicken a CAD rule.
    """
    dx, dy = line.x2 - line.x1, line.y2 - line.y1
    length = hypot(dx, dy)
    if length < 8:
        return None
    normal = np.array([-dy, dx]) / length
    span = max(12, min(48, int(min(gray.shape) * 0.008)))
    offsets = np.arange(-span, span + 1)
    widths, dark, centers, contrasted = [], [], [], []
    for t in np.linspace(0.12, 0.88, 19):
        point = np.array([line.x1 + dx * t, line.y1 + dy * t])
        samples = point + offsets[:, None] * normal
        xs, ys = np.rint(samples[:, 0]).astype(int), np.rint(samples[:, 1]).astype(int)
        if (
            xs.min() < 0
            or ys.min() < 0
            or xs.max() >= gray.shape[1]
            or ys.max() >= gray.shape[0]
        ):
            continue
        values = gray[ys, xs]
        candidates = np.where(values < 128)[0]
        if not len(candidates):
            continue
        seed = int(candidates[np.argmin(abs(candidates - span))])
        if abs(seed - span) > 2:
            continue
        a = b = seed
        while a > 0 and values[a - 1] < 128:
            a -= 1
        while b + 1 < len(values) and values[b + 1] < 128:
            b += 1
        if a == 0 or b == len(values) - 1:
            continue
        # A dark grey fill can lie below the ordinary ink threshold. Two
        # darker flanks around a brighter interior are separate boundaries,
        # even when no white pixel separates them. Anti-aliased single strokes
        # instead have their darkest core inside, not two darker outer flanks.
        run = values[a : b + 1]
        band = max(1, len(run) // 3)
        middle = float(np.median(run[band : len(run) - band])) if len(run) >= 3 else 0.0
        flanks = max(float(run[:band].min()), float(run[-band:].min()))
        split_fill = len(run) >= 3 and middle - flanks > 8
        if split_fill:
            level = (middle + flanks) / 2
            candidates = np.where(values <= level)[0]
            seed = int(candidates[np.argmin(abs(candidates - span))])
            if abs(seed - span) > 2:
                continue
            a = b = seed
            while a > 0 and values[a - 1] <= level:
                a -= 1
            while b + 1 < len(values) and values[b + 1] <= level:
                b += 1
            if a == 0 or b == len(values) - 1:
                continue
        widths.append(b - a + 1)
        centers.append((a + b) / 2 - span)
        dark.append(float(np.mean(values[a : b + 1] < 64)))
        contrasted.append(bool(split_fill))
    if len(widths) < 12:
        return None
    median = float(np.median(widths))
    stable = float(np.mean(abs(np.asarray(widths) - median) <= max(1, median * 0.25)))
    if stable < 0.75:
        return None
    return {
        "source_width_px": median,
        "stable_fraction": stable,
        "dark_core_fraction": float(np.median(dark)),
        "center_offset_px": float(np.median(centers)),
        "samples": len(widths),
        "contrast_separated_fraction": float(np.mean(contrasted)),
    }


def lineweight_record(profile, dpi):
    physical = profile["source_width_px"] * 25.4 / dpi
    category = min(
        LINEWEIGHTS,
        key=lambda k: abs(np.log(max(physical, 0.01) / (LINEWEIGHTS[k] / 100))),
    )
    return {
        **profile,
        "source_width_mm": physical,
        "source_dpi": dpi,
        "category": category,
        "cad_lineweight": LINEWEIGHTS[category],
        "ownership_class": "STRUCTURAL GEOMETRY",
        "source_support": "stable normal dark runs; paper-separated runs measured independently",
    }


def stroke_presentation(
    gray, lines, dpi=110.0, *, allow_merge=True, protected_mask=None
):
    """Presentation metadata plus conservative duplicate-boundary decisions.

    Existing exact junctions are protected: lines incident to another endpoint
    cannot be merged here. Fully coincident extents, stable solid cross-sections
    and isolated endpoints are all required, beyond any distance criterion.
    """
    profiles = [stroke_profile(gray, line) for line in lines]
    removed, replacements, decisions = set(), {}, []
    endpoints = Counter(
        p for line in lines for p in ((line.x1, line.y1), (line.x2, line.y2))
    )
    for i, first in enumerate(lines):
        if not allow_merge:
            break
        if i in removed or profiles[i] is None or first.length < 40:
            continue
        if any(endpoints[p] > 1 for p in ((first.x1, first.y1), (first.x2, first.y2))):
            continue
        tangent = (first.p2 - first.p1) / first.length
        normal = np.array([-tangent[1], tangent[0]])
        for j in range(i + 1, len(lines)):
            second = lines[j]
            if j in removed or profiles[j] is None:
                continue
            if (
                abs(first.length - second.length) > 3
                or abs((first.angle - second.angle + 90) % 180 - 90) > 1
            ):
                continue
            if any(
                endpoints[p] > 1
                for p in ((second.x1, second.y1), (second.x2, second.y2))
            ):
                continue
            ends = (
                (second.p1, second.p2)
                if np.dot(second.p2 - second.p1, tangent) >= 0
                else (second.p2, second.p1)
            )
            if (
                max(
                    abs(np.dot(ends[k] - p, tangent))
                    for k, p in enumerate((first.p1, first.p2))
                )
                > 1.5
            ):
                continue
            separation = abs(float(np.dot(ends[0] - first.p1, normal)))
            if separation < 0.5 or separation >= min(
                profiles[i]["source_width_px"], profiles[j]["source_width_px"]
            ):
                continue
            # Both proposals must actually describe opposite edges of the same
            # run. Two already-centered detections must not move a P1 node.
            offsets = [profiles[k]["center_offset_px"] for k in (i, j)]
            direction = 1 if np.dot(second.p2 - second.p1, tangent) >= 0 else -1
            if (
                offsets[0] * offsets[1] * direction >= 0
                or min(abs(v) for v in offsets) < separation * 0.35
            ):
                continue
            center = (first.p1 + ends[0]) / 2
            end = (first.p2 + ends[1]) / 2
            candidate = replace(
                first,
                x1=float(center[0]),
                y1=float(center[1]),
                x2=float(end[0]),
                y2=float(end[1]),
            )
            if protected_mask is not None:
                sample = np.linspace(center, end, max(2, int(first.length) + 1))
                xs = np.clip(np.rint(sample[:, 0]).astype(int), 0, gray.shape[1] - 1)
                ys = np.clip(np.rint(sample[:, 1]).astype(int), 0, gray.shape[0] - 1)
                if np.any(protected_mask[ys, xs]):
                    continue
            profile = stroke_profile(gray, candidate)
            if (
                profile is None
                or profile["dark_core_fraction"] < 0.95
                or profile["source_width_px"] < separation + 1
                or profile["source_width_px"] * 25.4 / dpi > 1.2
            ):
                continue
            # Grey fill and intervening paper fail this gate; junction-bearing
            # boundaries were vetoed above. Coordinates change only to recover
            # an evidenced physical centerline, never to simulate visual width.
            replacements[i] = replace(
                candidate,
                source_ids=tuple(
                    dict.fromkeys((*first.source_ids, *second.source_ids))
                ),
                history=(*first.history, "source-solid-stroke-presentation"),
            )
            profiles[i] = profile
            removed.add(j)
            decisions.append(
                {
                    "kept_input": i,
                    "removed_input": j,
                    "reason": "same extents, isolated endpoints, stable continuous dark core",
                }
            )
            break
    output, records = [], []
    for i, line in enumerate(lines):
        if i in removed:
            continue
        output.append(replacements.get(i, line))
        records.append(lineweight_record(profiles[i], dpi) if profiles[i] else None)
    return tuple(output), {
        "schema_version": 1,
        "line_records": records,
        "false_parallel_decisions": decisions,
        "vocabulary": LINEWEIGHTS,
        "source_dpi": dpi,
    }
