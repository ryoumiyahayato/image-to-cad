"""Dataset nomination quality only. No class label or production decision gate."""

import math

import cv2
import numpy as np

POLICY = {
    "version": "human-queue-quality-v2",
    "dark_threshold": 180,
    "support_radius_px": 1.25,
    "min_support_ratio": 0.90,
    "max_mean_distance_px": 1.0,
    "max_p95_distance_px": 2.0,
    "min_endpoint_support": 0.75,
    "min_overlap_px": 32.0,
    "min_length_ratio": 0.70,
    "max_separation_range_px": 1.5,
    "min_local_alignment": 0.75,
    "display_margin_px": 12,
}

# Only the explicit-page repair path consumes this extension. Historical
# queues/frozen inputs keep their original policy and source geometry.
EDGE_POLICY = {"min_directional_edge_ratio": .75, "max_unsupported_run_px": 8.0}


def ink_distance(gray):
    return cv2.distanceTransform(
        (gray > POLICY["dark_threshold"]).astype(np.uint8),
        cv2.DIST_L2,
        cv2.DIST_MASK_PRECISE,
    )


def edge_attachment(gray, line, radius_px=1.25):
    """Check local gradient direction at an unmoved edge proposal.

    Nearby dark ink can be a crossing or hatch. These diagnostics do not
    identify a wall, establish edge identity, or relocate the proposal.
    """
    a, b = np.asarray(line, dtype=float).reshape(2, 2)
    length = float(np.linalg.norm(b-a))
    tangent = (b-a)/max(length, 1e-9)
    normal = np.array([-tangent[1], tangent[0]])
    points = a + np.linspace(.02, .98, min(181, max(19, math.ceil(length))))[:, None]*(b-a)
    # A small source window avoids a full-page gradient for each proposal.
    lo = np.maximum(0, np.floor(np.minimum(a,b)-radius_px-5).astype(int))
    hi = np.minimum([gray.shape[1], gray.shape[0]], np.ceil(np.maximum(a,b)+radius_px+6).astype(int))
    patch = gray[lo[1]:hi[1], lo[0]:hi[0]].astype(np.float32)
    if min(patch.shape, default=0)<3:
        return {"directional_edge_ratio":0., "dominant_polarity_ratio":0., "limit":"source window unavailable"}
    smooth = cv2.GaussianBlur(patch, (3,3), .6)
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)/8
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)/8
    offsets = np.linspace(-radius_px, radius_px, max(11, math.ceil(radius_px*8)+1))
    probes = points[:,None,:] + offsets[None,:,None]*normal - lo
    xx, yy = probes[:,:,0].astype(np.float32), probes[:,:,1].astype(np.float32)
    dx = cv2.remap(gx,xx,yy,cv2.INTER_LINEAR)
    dy = cv2.remap(gy,xx,yy,cv2.INTER_LINEAR)
    magnitude = np.hypot(dx,dy)
    index = magnitude.argmax(axis=1)
    ids = np.arange(len(points))
    peak = magnitude[ids,index]
    signed = dx[ids,index]*normal[0] + dy[ids,index]*normal[1]
    aligned = (peak>=20) & (np.abs(signed)/np.maximum(peak,1e-6)>=math.cos(math.radians(25)))
    positive = int(np.sum(aligned & (signed>0)))
    negative = int(np.sum(aligned & (signed<0)))
    return {"directional_edge_ratio":float(aligned.mean()),
            "dominant_polarity_ratio":max(positive,negative)/len(points),
            "probe_count":len(points), "radius_px":float(radius_px),
            "median_peak_offset_px":float(np.median(offsets[index][aligned])) if aligned.any() else None,
            "peak_offset_range_px":float(np.ptp(offsets[index][aligned])) if aligned.any() else None,
            "limit":"finite local gradient evidence, not source-object identity or semantic class"}


def sample_line(gray, distance, line, *, support_radius_px=None, tangent_probe_px=3.0, endpoint_extent_scale=1.0):
    start, end = np.array(line[:2]), np.array(line[2:])
    length = float(np.linalg.norm(end - start))
    points = np.linspace(start, end, max(9, min(8192, math.ceil(length) + 1)))
    x, y = points[:, 0], points[:, 1]
    valid = (x >= 0) & (y >= 0) & (x < gray.shape[1]) & (y < gray.shape[0])
    values = np.full(len(points), 1e6)
    values[valid] = cv2.remap(
        distance,
        x[valid].astype(np.float32).reshape(1, -1),
        y[valid].astype(np.float32).reshape(1, -1),
        cv2.INTER_LINEAR,
    ).ravel()
    radius = POLICY["support_radius_px"] if support_radius_px is None else support_radius_px
    supported = values <= radius
    longest, current = 0, 0
    for support in supported:
        current = 0 if support else current+1
        longest = max(longest, current)
    step=length/max(1,len(points)-1)
    endpoint_count=5 if endpoint_extent_scale==1 else max(2,round(4*endpoint_extent_scale/max(step,1e-9))+1)
    endpoint = min(float(supported[:endpoint_count].mean()), float(supported[-endpoint_count:].mean()))
    # Nearest observed local ink must have tangent-oriented continuation, not just an isolated crossing.
    tangent = (end - start) / max(length, 1e-9)
    aligned = []
    for point, support in zip(
        points[:: max(1, len(points) // 64)], supported[:: max(1, len(points) // 64)]
    ):
        if not support:
            aligned.append(False)
            continue
        probes = point + np.array([-tangent_probe_px, tangent_probe_px])[:, None] * tangent
        xx = np.clip(np.rint(probes[:, 0]).astype(int), 0, gray.shape[1] - 1)
        yy = np.clip(np.rint(probes[:, 1]).astype(int), 0, gray.shape[0] - 1)
        aligned.append(bool(np.all(distance[yy, xx] <= radius)))
    return {
        "SOURCE_SUPPORT_RATIO": float(supported.mean()),
        "UNSUPPORTED_FRACTION": float((~supported).mean()),
        "MEDIAN_DISTANCE_TO_DARK_INK": float(np.median(values)),
        "MEAN_DISTANCE_TO_DARK_INK": float(values.mean()),
        "P95_DISTANCE_TO_DARK_INK": float(np.percentile(values, 95)),
        "ENDPOINT_SUPPORT": endpoint,
        "LOCAL_INK_ALIGNMENT": float(np.mean(aligned)),
        "LENGTH_PX": length,
        "SOURCE_IN_BOUNDS_RATIO": float(valid.mean()),
        "MAX_UNSUPPORTED_RUN_PX": min(length,longest*length/max(1,len(points)-1)),
        "SUPPORT_RADIUS_PX": float(radius),
        "SAMPLING_STEP_PX":step,
        "UNSUPPORTED_RUN_FAILED_SAMPLES":longest,
        "ENDPOINT_PROBE_EXTENT_PX":(endpoint_count-1)*step,
    }


def pair_metrics(first, second):
    a, b = np.array(first).reshape(2, 2), np.array(second).reshape(2, 2)
    tangent = (a[1] - a[0]) / max(np.linalg.norm(a[1] - a[0]), 1e-9)
    normal = np.array([-tangent[1], tangent[0]])
    aa = (a - a[0]) @ tangent
    bb = (b - a[0]) @ tangent
    lo, hi = (
        max(float(aa.min()), float(bb.min())),
        min(float(aa.max()), float(bb.max())),
    )
    denom = float(bb[1] - bb[0])
    points = (
        b[0] + ((np.linspace(lo, hi, 19) - bb[0]) / denom)[:, None] * (b[1] - b[0])
        if abs(denom) > 1e-9
        else np.repeat(b[:1], 19, axis=0)
    )
    separation = (points - a[0]) @ normal
    lengths = [float(np.linalg.norm(p[1] - p[0])) for p in (a, b)]
    return {
        "PAIR_OVERLAP_LENGTH": max(0.0, hi - lo),
        "PAIR_LENGTH_RATIO": min(lengths) / max(max(lengths), 1e-9),
        "PAIR_SEPARATION_STABILITY": {
            "range_px": float(np.ptp(separation)),
            "std_px": float(np.std(separation)),
            "mean_px": float(np.mean(np.abs(separation))),
        },
    }


def inspect(row, gray, distance=None, require_explicit=True, *, require_directional_edge=False, pixel_scale=1.0,
            control_evidence=None):
    distance = ink_distance(gray) if distance is None else distance
    metrics, reasons = {}, []
    geometry = row.get("candidate_geometry", [])
    bbox = row["source_bbox"]
    x, y, w, h = bbox
    clipped = False
    for i, (_, line, _) in enumerate(geometry):
        m = sample_line(gray, distance, line,support_radius_px=POLICY['support_radius_px']*pixel_scale,
                        tangent_probe_px=3*pixel_scale,endpoint_extent_scale=pixel_scale)
        prefix = "A" if i == 0 else "B"
        metrics.update({prefix + "_" + k: v for k, v in m.items()})
        if require_directional_edge:
            attachment = edge_attachment(gray, line,radius_px=POLICY['support_radius_px']*pixel_scale)
            metrics[prefix+"_EDGE_ATTACHMENT"] = attachment
            if attachment["directional_edge_ratio"] < EDGE_POLICY["min_directional_edge_ratio"]:
                reasons.append("EDGE_DIRECTION_UNCONFIRMED")
            if m["MAX_UNSUPPORTED_RUN_PX"] > EDGE_POLICY["max_unsupported_run_px"]*pixel_scale:
                reasons.append("SOURCE_INK_GAP_IN_TARGET_EXTENT")
        if (
            m["SOURCE_SUPPORT_RATIO"] < POLICY["min_support_ratio"]
            or m["MEAN_DISTANCE_TO_DARK_INK"] > POLICY["max_mean_distance_px"]*pixel_scale
            or m["P95_DISTANCE_TO_DARK_INK"] > POLICY["max_p95_distance_px"]*pixel_scale
        ):
            reasons.append(
                "CANDIDATE_MISALIGNMENT"
                if i == 0
                else "PARTNER_EDGE_MISSING_OR_FLOATING"
            )
        if m["ENDPOINT_SUPPORT"] < POLICY["min_endpoint_support"]:
            reasons.append("UNSUPPORTED_ENDPOINT")
        if m["LOCAL_INK_ALIGNMENT"] < POLICY["min_local_alignment"]:
            reasons.append("LOCAL_INK_MISALIGNMENT")
        margin = POLICY["display_margin_px"]*pixel_scale
        clipped |= any(
            not (
                x + margin <= px <= x + w - margin
                and y + margin <= py <= y + h - margin
            )
            for px, py in np.array(line).reshape(2, 2)
        )
    if len(geometry) == 2:
        metrics.update(pair_metrics(geometry[0][1], geometry[1][1]))
        if (
            metrics["PAIR_LENGTH_RATIO"] < POLICY["min_length_ratio"]
            or metrics["PAIR_OVERLAP_LENGTH"] < POLICY["min_overlap_px"]*pixel_scale
        ):
            reasons.append("SEVERE_EXTENT_MISMATCH")
        if (
            metrics["PAIR_SEPARATION_STABILITY"]["range_px"]
            > POLICY["max_separation_range_px"]*pixel_scale
        ):
            reasons.append("PAIR_SEPARATION_UNSTABLE")
        metrics["ENDPOINT_SUPPORT"] = min(
            metrics["A_ENDPOINT_SUPPORT"], metrics["B_ENDPOINT_SUPPORT"]
        )
        metrics["LOCAL_INK_ALIGNMENT"] = min(
            metrics["A_LOCAL_INK_ALIGNMENT"], metrics["B_LOCAL_INK_ALIGNMENT"]
        )
    elif len(geometry) == 1:
        metrics["ENDPOINT_SUPPORT"] = metrics["A_ENDPOINT_SUPPORT"]
        metrics["LOCAL_INK_ALIGNMENT"] = metrics["A_LOCAL_INK_ALIGNMENT"]
    elif not geometry:
        target = row.get("target_roi")
        if not target:
            reasons.append("NO_EXPLICIT_TARGET_OVERLAY")
        else:
            tx, ty, tw, th = target
            clipped = not (
                x + 8 <= tx
                and y + 8 <= ty
                and tx + tw <= x + w - 8
                and ty + th <= y + h - 8
            )
            crop = gray[max(0, int(ty)) : int(ty + th), max(0, int(tx)) : int(tx + tw)]
            metrics["TARGET_INK_PIXELS"] = int((crop <= POLICY["dark_threshold"]).sum())
            if metrics["TARGET_INK_PIXELS"] < 4:
                reasons.append("NO_SOURCE_TARGET_INK")
            if require_directional_edge and row.get('target_kind')=='CONTROL':
                if control_evidence is None:
                    reasons.append('CONTROL_OBJECT_EXTENT_UNASSESSED')
                elif not control_evidence['queue_eligible']:
                    reasons.append('CONTROL_LINE_FRAGMENT' if control_evidence['status']=='line_fragment'
                                   else 'CONTROL_OBJECT_EXTENT_UNCERTAIN')
    if clipped:
        reasons.append("TARGET_CLIPPED")
    if len(geometry) > 2:
        reasons.append("UNCLEAR_CANDIDATE_CARDINALITY")
    if require_explicit and not row.get("target_kind") and not geometry:
        reasons.append("NO_EXPLICIT_TARGET_OVERLAY")
    return {
        "quality_policy": POLICY["version"] + ("+directional-extent-v1" if require_directional_edge else ""),
        "edge_policy": dict(EDGE_POLICY) if require_directional_edge else None,
        "actual_source_pixels_per_reference_pixel":float(pixel_scale),
        "continuity_limit":"unsupported extent is failed samples times actual spacing, capped at target length; a gap is not proof of wrong geometry when line style is unknown",
        "identity_limit": "ink, direction and continuity are finite evidence, not unique source-object identity",
        "metrics": metrics,
        "rejection_reasons": sorted(set(reasons)),
        "HUMAN_QUEUE_ELIGIBLE": not reasons,
        "control_object_evidence":control_evidence if not geometry else None,
    }
