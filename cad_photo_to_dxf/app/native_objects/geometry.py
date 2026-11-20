"""Complete native lines using required text regions and source evidence.

Text glyphs, crossing geometry and enclosure sides are distinct decisions.
No raster erasure, blanket bbox deletion, angular snap or gap completion.
"""

from .performance import profiled
import math
import time
from pathlib import Path
import numpy as np
import cv2
from scipy.ndimage import map_coordinates
from PIL import Image, ImageDraw
from .contracts import validate_text_regions, save_json, stable_id


def samples(a, b, step=1):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.linspace(a, b, max(2, int(np.linalg.norm(b - a) / step) + 1))


def longest(v):
    e = np.diff(np.r_[False, v, False].astype(int))
    s = np.flatnonzero(e == 1)
    t = np.flatnonzero(e == -1)
    return int(max(t - s, default=0))


def source_support(a, b, dist, origin, step=1):
    p = samples(a, b, step)
    ds = map_coordinates(
        dist,
        [p[:, 1] - origin[1], p[:, 0] - origin[0]],
        order=1,
        mode="constant",
        cval=999,
    )
    return {
        "supported_fraction": float(np.mean(ds <= 2)),
        "maximum_white_gap_px": float(longest(ds > 2) * step),
        "max_distance_px": float(ds.max()),
        "p95_distance_px": float(np.quantile(ds, 0.95)),
    }


def fit_source(seg, gray, origin):
    a, b = np.asarray(seg[:2], float), np.asarray(seg[2:], float)
    v = b - a
    length = np.linalg.norm(v)
    if length < 8:
        return None, "below_detector_resolution"
    u = v / length
    n = np.array([-u[1], u[0]])
    pts = samples(a, b, 2)
    off = np.arange(-4, 4.01, 0.5)
    q = pts[:, None, :] + off[None, :, None] * n
    ink = (
        map_coordinates(
            gray,
            [q[:, :, 1] - origin[1], q[:, :, 0] - origin[0]],
            order=0,
            mode="constant",
            cval=255,
        )
        < 128
    )
    centers = []
    widths = []
    for p, row in zip(pts, ink):
        d = np.diff(np.r_[False, row, False].astype(int))
        s = np.flatnonzero(d == 1)
        e = np.flatnonzero(d == -1)
        runs = [(lo, hi) for lo, hi in zip(s, e) if 0 < hi - lo < 12]
        if not runs:
            continue
        lo, hi = min(runs, key=lambda r: abs((off[r[0]] + off[r[1] - 1]) / 2))
        shift = (off[lo] + off[hi - 1]) / 2
        if abs(shift) > 3.5:
            continue
        centers.append(p + shift * n)
        widths.append((hi - lo) * 0.5)
    if len(centers) < 0.8 * len(pts):
        return None, "ambiguous_cross_section"
    c = np.asarray(centers)
    t = (c - a) @ u
    z = (c - a) @ n
    if np.ptp(t) < 1:
        return None, "insufficient_span"
    slope, offset = np.polyfit(t, z, 1)
    res = np.abs(z - slope * t - offset)
    if abs(math.degrees(math.atan(slope))) > 0.5:
        return None, "direction_change_exceeds_bound"
    if np.quantile(res, 0.95) > 2:
        return None, "nonstraight_source"
    return (
        a + offset * n,
        b + (offset + slope * length) * n,
        float(np.median(widths)),
    ), "ok"


def text_relation(a, b, boxes):
    """Only contained glyph-like segments are withheld; crossings survive."""
    pts = samples(a, b, 1)
    length = float(np.linalg.norm(np.asarray(b) - a))
    events = []
    decision = "NO_TEXT_CONTACT"
    for box in boxes:
        x0, y0, x1, y1 = box["bbox_xyxy_px"]
        pad = 1.0
        inside = (
            (pts[:, 0] >= x0 - pad)
            & (pts[:, 0] <= x1 + pad)
            & (pts[:, 1] >= y0 - pad)
            & (pts[:, 1] <= y1 + pad)
        )
        if not inside.any():
            continue
        frac = float(inside.mean())
        idx = np.flatnonzero(inside)
        outside_before = int(idx[0])
        outside_after = len(pts) - 1 - int(idx[-1])
        h = y1 - y0
        cross = outside_before >= max(8, h * 0.5) and outside_after >= max(8, h * 0.5)
        runs = box.get("glyph_source_runs")
        glyph_fraction = None
        if runs is not None:
            # A text rectangle does not own connected wall/leader ink. Require
            # positive compact glyph-source support before deferring a line.
            # The 2px neighbourhood is the existing line localization bound;
            # it does not edit, grow or erase the source raster.
            glyph = np.zeros(len(pts), bool)
            for gy, gx0, gx1 in runs:
                if gy < min(a[1], b[1]) - 2 or gy > max(a[1], b[1]) + 2:
                    continue
                glyph |= (
                    (abs(pts[:, 1] - gy) <= 2)
                    & (pts[:, 0] >= gx0 - 2)
                    & (pts[:, 0] < gx1 + 2)
                )
            glyph_fraction = float(glyph.mean())
        if cross:
            status = "RETAIN_SOURCE_SUPPORTED_THROUGH_LINE"
        elif glyph_fraction is not None and glyph_fraction < 0.7:
            status = "RETAIN_LINE_WITHOUT_POSITIVE_GLYPH_SOURCE_OWNERSHIP"
        elif frac >= 0.7 and length <= max(3 * h, 1.2 * (x1 - x0)):
            status = "DEFER_TEXT_GLYPH_OR_INTERNAL_STROKE"
        elif frac < 0.25:
            status = "RETAIN_NEAR_TEXT_LINE_WITH_LOCAL_CONTACT"
        else:
            status = "DEFER_AMBIGUOUS_TEXT_LINE_OWNERSHIP"
        events.append(
            {
                "region_id": box["region_id"],
                "bbox_xyxy_px": box["bbox_xyxy_px"],
                "inside_fraction": frac,
                "positive_glyph_source_fraction": glyph_fraction,
                "outside_before_px": outside_before,
                "outside_after_px": outside_after,
                "decision": status,
            }
        )
    if any(e["decision"].startswith("DEFER") for e in events):
        decision = "DEFER_TEXT_OWNERSHIP"
    elif events:
        decision = "RETAIN_GEOMETRY_WITH_TEXT_CONTACT"
    return decision, events


def extend(p, u, dist, origin):
    d = np.arange(0, 1801, dtype=float)
    q = p + d[:, None] * u
    ds = map_coordinates(
        dist,
        [q[:, 1] - origin[1], q[:, 0] - origin[0]],
        order=1,
        mode="constant",
        cval=999,
    )
    good = ds <= 2
    gaps = np.flatnonzero(
        np.convolve((~good).astype(int), np.ones(6, dtype=int), "valid") == 6
    )
    stop = int(gaps[0]) if len(gaps) else len(good) - 1
    valid = np.flatnonzero(good[: max(1, stop)])
    end = int(valid[-1]) if len(valid) else 0
    return p + end * u


def outgoing(p, u, ink, origin):
    rad = np.arange(7.0, 25.0)
    ang = np.deg2rad(np.arange(-30.0, 30.1, 3.0))
    n = np.array([-u[1], u[0]])
    vec = np.cos(ang)[:, None] * u + np.sin(ang)[:, None] * n
    q = p + rad[:, None, None] * vec[None, :, :]
    val = (
        map_coordinates(
            ink,
            [q[:, :, 1] - origin[1], q[:, :, 0] - origin[0]],
            order=0,
            mode="constant",
            cval=0,
        )
        > 0
    )
    return longest(val.any(axis=1)) >= 10


def clip(a, b, roi):
    u = b - a
    length = np.linalg.norm(u)
    u /= length
    lo, hi = 0.0, length
    for k, mn, mx in ((0, roi[0], roi[2]), (1, roi[1], roi[3])):
        if abs(u[k]) < 1e-10:
            if not mn <= a[k] <= mx:
                return None
        else:
            lower, upper = sorted(((mn - a[k]) / u[k], (mx - a[k]) / u[k]))
            lo = max(lo, lower)
            hi = min(hi, upper)
    return (a + lo * u, a + hi * u) if hi > lo else None


@profiled("geometry.extract_lines")
def extract_lines(full, roi, text_data, out):
    started = time.perf_counter()
    cv2.setNumThreads(1)
    out = Path(out)
    boxes = validate_text_regions(text_data, full.shape, roi)
    x0, y0, x1, y1 = roi
    ox, oy = max(0, x0 - 160), max(0, y0 - 160)
    rx, by = min(full.shape[1], x1 + 160), min(full.shape[0], y1 + 160)
    origin = np.array([ox, oy])
    crop = full[oy:by, ox:rx]
    ink = (crop < 128).astype("uint8")
    dist = cv2.distanceTransform(1 - ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    proposals = []
    deferred = []
    tiles = []
    for y in range(oy, by, 1160):
        for x in range(ox, rx, 1160):
            tile = full[y : min(y + 1400, by), x : min(x + 1400, rx)]
            if min(tile.shape) < 30:
                continue
            detected = detector.detect(tile)[0]
            tiles.append([x, y, x + tile.shape[1], y + tile.shape[0]])
            for raw in [] if detected is None else detected.reshape(-1, 4):
                s = raw + np.array([x, y, x, y])
                length = np.linalg.norm(s[2:] - s[:2])
                if length < 30:
                    continue  # isolated real short strokes have a separate source-component path below
                if (
                    max(s[0], s[2]) < x0
                    or min(s[0], s[2]) > x1
                    or max(s[1], s[3]) < y0
                    or min(s[1], s[3]) > y1
                ):
                    continue
                fitted, reason = fit_source(s, crop, origin)
                if fitted is None:
                    continue
                a, b, w = fitted
                if tuple(a) > tuple(b):
                    a, b = b, a
                sup = source_support(a, b, dist, origin)
                if sup["supported_fraction"] < 0.98 or sup["maximum_white_gap_px"] > 5:
                    continue
                proposals.append({"a": a, "b": b, "width": w, "observations": 1})
    merged = []
    for p in sorted(proposals, key=lambda q: -np.linalg.norm(q["b"] - q["a"])):
        found = False
        for m in merged:
            a, b = m["a"], m["b"]
            length = np.linalg.norm(b - a)
            u = (b - a) / length
            n = np.array([-u[1], u[0]])
            v = p["b"] - p["a"]
            if abs(u @ (v / np.linalg.norm(v))) < math.cos(math.radians(0.5)):
                continue
            if max(abs((p["a"] - a) @ n), abs((p["b"] - a) @ n)) > 2:
                continue
            t = sorted([(p["a"] - a) @ u, (p["b"] - a) @ u])
            if max(0, t[0] - length, -t[1]) > 5:
                continue
            aa = a + min(0, t[0]) * u
            bb = a + max(length, t[1]) * u
            sup = source_support(aa, bb, dist, origin)
            if sup["supported_fraction"] < 0.98 or sup["maximum_white_gap_px"] > 5:
                continue
            m["a"], m["b"] = aa, bb
            m["observations"] += 1
            found = True
            break
        if not found:
            merged.append(p.copy())
    objects = []
    text_audit = []
    all_geom = []
    candidate_groups = {}
    for m in merged:
        a, b = m["a"], m["b"]
        length = np.linalg.norm(b - a)
        if length < 60:
            continue  # handled explicitly as real components / complete frames
        u = (b - a) / length
        aa, bb = extend(a, -u, dist, origin), extend(b, u, dist, origin)
        boundary = [
            not (x0 + 2 < p[0] < x1 - 2 and y0 + 2 < p[1] < y1 - 2) for p in (aa, bb)
        ]
        if any(
            outgoing(p, d, ink, origin) and not edge
            for p, d, edge in ((aa, -u, boundary[0]), (bb, u, boundary[1]))
        ):
            deferred.append(
                {
                    "geometry": {"start": a.tolist(), "end": b.tolist()},
                    "reason": "CURVED_OR_BRANCH_CONTINUATION_NOT_A_WHOLE_LINE",
                }
            )
            continue
        clipped = clip(aa, bb, roi)
        if clipped is None:
            continue
        a, b = clipped
        sup = source_support(a, b, dist, origin)
        if sup["supported_fraction"] < 0.98 or sup["maximum_white_gap_px"] > 5:
            continue
        geometry = {"start": a.tolist(), "end": b.tolist()}
        oid = stable_id("LINE", geometry)
        status, events = text_relation(a, b, boxes)
        text_audit.append(
            {
                "id": oid,
                "geometry": geometry,
                "legacy_bbox_bug_context_count": 0,
                "actual_word_boxes_read": len(boxes),
                "decision": status,
                "contacts": events,
            }
        )
        obj = {
            "id": oid,
            "kind": "LINE",
            "layer": "GEOMETRY",
            "geometry": geometry,
            "source_evidence": {
                "method": "native_tiled_source_centered_complete_lines_v2",
                "support": sup,
                "source_width_px": m["width"],
                "source_observations": m["observations"],
                "boundary_clipped": any(boundary),
                "text_relation": status,
                "text_contacts": events,
            },
        }
        if status.startswith("DEFER"):
            deferred.append(
                {"id": oid, "geometry": geometry, "reason": status, "contacts": events}
            )
            continue
        # A local approximate duplicate is still a source-supported proposal.
        # Complete-wall feasibility chooses the representative later.
        all_geom.append(obj)
        duplicate = False
        for q in objects:
            c, d = np.array(q["geometry"]["start"]), np.array(q["geometry"]["end"])
            v = d - c
            ql = np.linalg.norm(v)
            if abs(u @ (v / ql)) < math.cos(math.radians(0.5)):
                continue
            n = np.array([-u[1], u[0]])
            if max(abs((c - a) @ n), abs((d - a) @ n)) > 2:
                continue
            ts = sorted([(c - a) @ u, (d - a) @ u])
            ov = max(0, min(np.linalg.norm(b - a), ts[1]) - max(0, ts[0]))
            if ov > 0.85 * min(ql, np.linalg.norm(b - a)):
                duplicate = True
                candidate_groups[q["id"]]["candidate_ids"].append(oid)
                break
        if not duplicate:
            objects.append(obj)
            candidate_groups[oid] = {
                "representative_id": oid,
                "candidate_ids": [oid],
                "decision": "LOCAL_APPROXIMATION_ONLY_COMPLETE_WALL_MUST_SELECT",
            }
    # Source connected components are not removed by a length cutoff. A thin,
    # isolated, non-text component can be a whole short dash with natural ends.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (full[y0:y1, x0:x1] < 128).astype("uint8"), 8
    )
    short_log = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (10 <= max(w, h) <= 100 and area >= 10):
            continue
        ys, xs = np.nonzero(labels[y : y + h, x : x + w] == i)
        pts = np.column_stack((xs + x + x0, ys + y + y0)).astype(float)
        centre = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - centre, full_matrices=False)
        u = vt[0]
        n = np.array([-u[1], u[0]])
        t = (pts - centre) @ u
        normal = (pts - centre) @ n
        length = float(t.max() - t.min())
        if (
            length < 12
            or np.ptp(normal) > 5
            or length / max(1, np.ptp(normal)) < 5
            or np.quantile(abs(normal), 0.95) > 2
        ):
            continue
        a, b = centre + t.min() * u, centre + t.max() * u
        if tuple(a) > tuple(b):
            a, b = b, a
        status, events = text_relation(a, b, boxes)
        geometry = {"start": a.tolist(), "end": b.tolist()}
        oid = stable_id("SHORT", geometry)
        record = {
            "id": oid,
            "geometry": geometry,
            "source_component_area": int(area),
            "decision": status,
            "contacts": events,
        }
        short_log.append(record)
        if status.startswith("DEFER"):
            deferred.append(record)
            continue
        sup = source_support(a, b, dist, origin)
        if sup["supported_fraction"] < 0.98 or sup["maximum_white_gap_px"] > 5:
            continue
        if any(
            np.linalg.norm(
                (np.array(q["geometry"]["start"]) + q["geometry"]["end"]) / 2
                - (a + b) / 2
            )
            < length / 2
            for q in objects
        ):
            continue
        objects.append(
            {
                "id": oid,
                "kind": "LINE",
                "layer": "SHORT_STROKE",
                "geometry": geometry,
                "source_evidence": {
                    "method": "complete_isolated_ink_component_PCA",
                    "component_bbox_xyxy_px": [
                        int(x + x0),
                        int(y + y0),
                        int(x + x0 + w),
                        int(y + y0 + h),
                    ],
                    "component_area": int(area),
                    "support": sup,
                    "text_contacts": events,
                    "not_a_length_based_deletion": True,
                },
            }
        )
    result = {
        "objects": objects,
        "pre_dedup_line_candidates": all_geom,
        "line_candidate_groups": list(candidate_groups.values()),
        "uncertainties": deferred,
        "text_interface": {
            "coordinate_system": "source_pixels_top_left",
            "regions_received": len(text_data["regions"]),
            "word_boxes_consumed": len(boxes),
            "missing_field_policy": "RAISE_CONTRACT_ERROR",
            "contacts": text_audit,
        },
        "short_source_components": short_log,
        "tiles": tiles,
        "resources": {"wall_seconds": time.perf_counter() - started},
    }
    save_json(out / "lines.json", result)
    overlay = Image.fromarray(full[y0:y1, x0:x1]).convert("RGB")
    draw = ImageDraw.Draw(overlay)
    for box in boxes:
        x, y, r, b = box["bbox_xyxy_px"]
        draw.rectangle((x - x0, y - y0, r - x0, b - y0), outline=(220, 40, 40), width=1)
    for o in objects:
        a, b = o["geometry"]["start"], o["geometry"]["end"]
        draw.line(
            (a[0] - x0, a[1] - y0, b[0] - x0, b[1] - y0), fill=(0, 120, 230), width=2
        )
    overlay.save(out / "text_geometry_overlay.png")
    return result
