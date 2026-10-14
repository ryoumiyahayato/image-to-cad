"""Source-component proposals for isolated thin scan strokes missed at an edge.

This precedes ownership/reconciliation. It never edits an accepted LINE or
deletes a contour. Only ordinary downstream ownership can consume the ink.
"""

from collections import Counter
from math import ceil

import cv2
import numpy as np

from app.geometry.line_detect import LineSegment
from app.geometry.reconciliation_geometry import _production_claim_thickness


MAX_COMPONENT_CHECKS = 512
MAX_CHECKS = 64
MAX_LOCAL_PIXELS = 65536
MAX_TOTAL_PIXELS = 1_000_000
MAX_NEIGHBOURS = 32


def isolated_scan_stroke_proposals(
    rejected, *, all_lines, binary, gray, protected_mask, scale=1.0
):
    """Review rejected LSD white-edge seeds; return fresh source proposals.

    A seed is only a locator. Fit every station of a complete isolated source
    component, never a crop-clipped piece of a wall, glyph, fill or curve. The
    0.5 px center residual is one raster cell's localization uncertainty, not
    a direction snap. Original source gaps and all other candidates remain.
    """
    bounds = np.array(
        [
            [min(line.x1, line.x2), min(line.y1, line.y2), max(line.x1, line.x2), max(line.y1, line.y2)]
            for line in all_lines
        ],
        dtype=float,
    ).reshape(-1, 4)
    claim_radii = np.array(
        [_production_claim_thickness(line, shape=binary.shape) / 2 + 1 for line in all_lines]
    )
    endpoints = Counter(p for line in all_lines for p in ((line.x1, line.y1), (line.x2, line.y2)))
    order = sorted(
        rejected, key=lambda line: (tuple(line.source_ids), line.x1, line.y1, line.x2, line.y2)
    )
    rejected_ids = {id(line) for line in order}
    proposals, decisions, seen = [], [], set()
    pixels_used, checks, component_checks = 0, 0, 0
    h, w = binary.shape
    for seed in order:
        if (
            "detected:lsd" not in seed.history
            or seed.width > 3 * scale
            or seed.length < max(40.0, 20 * seed.width)
            or min(seed.angle, abs(seed.angle - 90), 180 - seed.angle) > 4
        ):
            continue
        detail = dict(
            seed_source_ids=list(seed.source_ids),
            seed_geometry=[seed.x1, seed.y1, seed.x2, seed.y2],
        )

        def reject(reason):
            decisions.append(dict(detail, decision="REJECTED", reason=reason))

        if component_checks >= MAX_COMPONENT_CHECKS:
            decisions.append(
                dict(
                    detail,
                    decision="NOT_EVALUATED",
                    reason="SCAN_STROKE_COMPONENT_BUDGET",
                )
            )
            continue
        component_checks += 1
        margin = max(4, ceil(seed.width * 2))
        a = np.floor(np.minimum(seed.p1, seed.p2)).astype(int) - margin
        b = np.ceil(np.maximum(seed.p1, seed.p2)).astype(int) + margin + 1
        x0, y0 = a
        x1, y1 = b
        area = int((x1 - x0) * (y1 - y0))
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            reject("SOURCE_COMPONENT_AT_PAGE_EDGE")
            continue
        if area > MAX_LOCAL_PIXELS or pixels_used + area > MAX_TOTAL_PIXELS:
            decisions.append(
                dict(
                    detail, decision="NOT_EVALUATED", reason="SCAN_STROKE_PIXEL_BUDGET"
                )
            )
            continue
        pixels_used += area
        ink = (binary[y0:y1, x0:x1] < 128).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
        midpoint = seed.midpoint - a
        yy, xx = np.nonzero(ink)
        near = (xx - midpoint[0]) ** 2 + (yy - midpoint[1]) ** 2 <= max(
            2.0, seed.width
        ) ** 2
        choices = np.unique(labels[yy[near], xx[near]])
        if len(choices) != 1:
            reject("SOURCE_COMPONENT_AMBIGUOUS")
            continue
        label = int(choices[0])
        bx, by, bw, bh, source_pixels = map(int, stats[label])
        if bx == 0 or by == 0 or bx + bw == x1 - x0 or by + bh == y1 - y0:
            reject("INCOMPLETE_SOURCE_COMPONENT")
            continue
        detail["component_box"] = [
            int(x0 + bx),
            int(y0 + by),
            int(x0 + bx + bw),
            int(y0 + by + bh),
        ]
        key = tuple(detail["component_box"])
        if key in seen:
            reject("SOURCE_COMPONENT_ALREADY_PROPOSED")
            continue
        component = labels == label
        if protected_mask is not None and np.any(
            component & (protected_mask[y0:y1, x0:x1] > 0)
        ):
            reject("PROTECTED_SOURCE_COMPONENT")
            continue
        if any(endpoints[p] > 1 for p in ((seed.x1, seed.y1), (seed.x2, seed.y2))):
            reject("SHARED_DETECTOR_ENDPOINT")
            continue
        if checks >= MAX_CHECKS:
            decisions.append(
                dict(
                    detail, decision="NOT_EVALUATED", reason="SCAN_STROKE_CHECK_BUDGET"
                )
            )
            continue
        checks += 1
        paper = gray[y0:y1, x0:x1][ink == 0]
        if len(paper) < 40:
            reject("LOCAL_PAPER_UNRESOLVED")
            continue
        background = float(np.median(paper))
        # The full production claim must fit in this crop; neighbouring paths
        # remain in ink and are checked below, including at both source caps.
        vertical = bh > bw
        core = component[by : by + bh, bx : bx + bw]
        profiles = core if vertical else core.T
        centers, widths = [], []
        contrasts = []
        valid = True
        source_tones = gray[y0 + by : y0 + by + bh, x0 + bx : x0 + bx + bw]
        source_tones = source_tones if vertical else source_tones.T
        for profile, tones in zip(profiles, source_tones):
            indices = np.flatnonzero(profile)
            if not len(indices) or indices[-1] - indices[0] + 1 != len(indices):
                valid = False
                break
            widths.append(len(indices))
            centers.append((indices[0] + indices[-1]) / 2)
            contrasts.append(background - float(np.median(tones[indices])))
        width_limit = max(2, int(round(2 * scale)))
        if (
            not valid
            or len(centers) < 40
            or max(widths) > width_limit
            or max(widths) - min(widths) > 1
        ):
            reject("NOT_A_COMPLETE_THIN_STROKE")
            continue
        # The page-wide deep-ink mask can miss real thin ink on grey paper.
        # Require contrast against nearby paper at EVERY complete station;
        # weak fold/shading evidence is not promoted by straightness alone.
        if min(contrasts) < 40:
            reject("INSUFFICIENT_LOCAL_INK_CONTRAST")
            continue
        stations = np.arange(len(centers), dtype=float)
        slope, intercept = np.polyfit(stations, np.asarray(centers), 1)
        residual = np.asarray(centers) - (intercept + slope * stations)
        # Balance the extreme station errors for this measured direction.
        # Least squares alone can bias an end cap beyond half a raster cell.
        # This changes the fitted intercept, never the acceptance tolerance.
        intercept += (float(residual.min()) + float(residual.max())) / 2
        residual = np.asarray(centers) - (intercept + slope * stations)
        if abs(slope) > np.tan(np.radians(4)) or abs(residual).max() > 0.5:
            reject("NONLINEAR_SOURCE_TRAJECTORY")
            continue
        width = float(np.median(widths))
        # Centers of the first/last visible cap cells. Width accounts for cap
        # extent; no extrapolation or snapping to neighbouring geometry occurs.
        start, end = (width - 1) / 2, len(centers) - 1 - (width - 1) / 2
        local_points = np.array(
            [
                [intercept + slope * t + bx, t + by]
                if vertical
                else [t + bx, intercept + slope * t + by]
                for t in (start, end)
            ]
        )
        p, q = local_points + a
        source_id = "SCAN-STROKE:" + ":".join(str(v) for v in key)
        line = LineSegment(
            *p,
            *q,
            width=width,
            confidence=seed.confidence,
            layer=seed.layer,
            source_ids=(source_id,),
            history=(
                "detected:isolated_scan_component",
                "scan_component_centerline_v1",
                *("seed:" + sid for sid in seed.source_ids),
            ),
        )
        samples = np.linspace(seed.p1 - a, seed.p2 - a, max(2, ceil(seed.length) + 1))
        xi, yi = np.rint(samples).astype(int).T
        original_support = float(np.mean(component[yi, xi]))
        if original_support >= 0.8:
            reject("SEED_ALREADY_ON_SOURCE_TRAJECTORY")
            continue
        claim = np.zeros_like(ink)
        thickness = _production_claim_thickness(line, shape=binary.shape)
        cv2.line(
            claim,
            tuple(np.rint(local_points[0]).astype(int)),
            tuple(np.rint(local_points[1]).astype(int)),
            1,
            thickness,
            cv2.LINE_8,
        )
        if np.any(component & (claim == 0)) or np.any(
            (claim > 0) & (ink > 0) & ~component
        ):
            reject("INCOMPLETE_OR_SHARED_SOURCE_CLAIM")
            continue
        # Nearby source and candidate endpoint obligations are separate checks.
        cap = np.zeros_like(component)
        gy, gx = np.ogrid[: ink.shape[0], : ink.shape[1]]
        for point in (local_points[0], local_points[1]):
            cap |= (gx - point[0]) ** 2 + (gy - point[1]) ** 2 <= (width / 2 + 1.5) ** 2
        if np.any(cap & (ink > 0) & ~component):
            reject("SHARED_SOURCE_CAP")
            continue
        nearby = np.flatnonzero(
            (bounds[:, 0] - claim_radii <= x1)
            & (bounds[:, 2] + claim_radii >= x0)
            & (bounds[:, 1] - claim_radii <= y1)
            & (bounds[:, 3] + claim_radii >= y0)
        )
        if len(nearby) > MAX_NEIGHBOURS:
            reject("CROWDED_CANDIDATE_CONTEXT")
            continue
        # Raw detector footprints are not ownership claims: reconciliation
        # pads them to search for support. A neighbouring independent stroke
        # must not acquire this component merely through that search margin.
        # Check its measured footprint and actual endpoint obligations here;
        # the authoritative padded claims are arbitrated downstream.
        shared = False
        rejected_locators = []
        for j in nearby:
            other = all_lines[j]
            if other is seed:
                continue
            mask = np.zeros_like(ink)
            cv2.line(
                mask,
                tuple(np.rint(other.p1 - a).astype(int)),
                tuple(np.rint(other.p2 - a).astype(int)),
                1,
                max(1, ceil(other.width)),
                cv2.LINE_8,
            )
            endpoint_contact = any(
                np.linalg.norm(endpoint - point) <= width / 2 + 1.5
                for endpoint in (other.p1 - a, other.p2 - a)
                for point in local_points
            )
            if np.any(component & (mask > 0)) or endpoint_contact:
                # Two discarded white-edge observations may locate one complete
                # isolated component. Neither has accepted CAD obligations. Do
                # not extend this exception to retained/accepted candidates, a
                # source-centred line, another ink component or shared endpoint.
                other_samples = np.linspace(
                    other.p1 - a, other.p2 - a, max(2, ceil(other.length) + 1)
                )
                ox, oy = np.rint(other_samples).astype(int).T
                inside = (
                    (ox >= 0) & (oy >= 0) & (ox < ink.shape[1]) & (oy < ink.shape[0])
                )
                direct = (
                    float(np.mean(component[oy[inside], ox[inside]]))
                    if np.all(inside)
                    else 1.0
                )
                major = other_samples[:, 1] if vertical else other_samples[:, 0]
                major0, major1 = (by, by + bh - 1) if vertical else (bx, bx + bw - 1)
                own_ink = np.any(component & (mask > 0))
                foreign_ink = np.any((mask > 0) & (ink > 0) & ~component)
                if (
                    id(other) in rejected_ids
                    and "detected:lsd" in other.history
                    and direct < 0.2
                    and own_ink
                    and not foreign_ink
                    and major.min() >= major0
                    and major.max() <= major1
                    and all(
                        endpoints[p] == 1
                        for p in ((other.x1, other.y1), (other.x2, other.y2))
                    )
                ):
                    rejected_locators.extend(other.source_ids)
                    continue
                detail["conflicting_detector"] = dict(
                    source_ids=list(other.source_ids),
                    geometry=[other.x1, other.y1, other.x2, other.y2],
                    width=other.width,
                    endpoint_contact=endpoint_contact,
                )
                shared = True
                break
        if shared:
            reject("OTHER_DETECTOR_CLAIM_OR_ENDPOINT")
            continue
        line = line.copy(
            history=(
                *line.history,
                *("rejected-locator:" + sid for sid in sorted(rejected_locators)),
            )
        )
        seen.add(key)
        proposals.append(line)
        decisions.append(
            dict(
                detail,
                decision="PROPOSED",
                source_id=source_id,
                source_pixels=source_pixels,
                rejected_locator_source_ids=sorted(rejected_locators),
                profile_count=len(centers),
                width_range=[min(widths), max(widths)],
                width_px=width,
                center_residual_max_px=float(abs(residual).max()),
                center_residual_rms_px=float(np.sqrt(np.mean(residual**2))),
                seed_direct_source_fraction=original_support,
                geometry=[line.x1, line.y1, line.x2, line.y2],
                paper_gray=background,
                minimum_station_contrast=float(min(contrasts)),
                complete_source_claim=True,
                isolated_caps=True,
                authority="fresh source component proposal; not a transformed or merged accepted CAD member",
            )
        )
    return tuple(proposals), dict(
        policy="isolated-thin-scan-component-v1",
        checks=checks,
        component_checks=component_checks,
        local_pixels=pixels_used,
        decisions=decisions,
    )


def scan_stroke_line_record(line, source_dpi):
    """Present a committed, fully measured scan component using existing weights.

    Raw-grey dark-core profiles can be absent on grey paper. The new route has
    already measured every prepared foreground station and local contrast, so
    its width must not silently fall back to an unweighted one-pixel LINE.
    """
    if "scan_component_centerline_v1" not in line.history:
        return None
    from app.geometry.source_presentation import LINEWEIGHTS

    source_width_mm = line.width * 25.4 / source_dpi
    category, weight = min(
        LINEWEIGHTS.items(), key=lambda item: abs(item[1] / 100 - source_width_mm)
    )
    return dict(
        category=category,
        cad_lineweight=weight,
        source_width_px=line.width,
        source_width_mm=source_width_mm,
        source_dpi=source_dpi,
        source_support="complete isolated prepared source component; every station locally contrasted",
        ownership_class="STRUCTURAL GEOMETRY",
        width_quantization_error_px=abs(weight / 100 - source_width_mm)
        * source_dpi
        / 25.4,
    )
