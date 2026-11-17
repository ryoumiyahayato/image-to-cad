"""Independent full-grid LINE sampler and exact native-center composition.

No proposal/exporter functions are imported. The unnormalized dot/cross
predicates test every native center in the declared tile; there is no cropped
pen bounding box, epsilon, morphological dilation, or drawing-library renderer.
"""
from __future__ import annotations

import numpy as np


def line_ink(shape, endpoints, width, cap):
    endpoints = np.asarray(endpoints, np.float64)
    if endpoints.shape != (2, 2) or not np.isfinite(endpoints).all():
        raise ValueError("finite two-endpoint LINE required")
    if not np.isfinite(width) or width <= 0:
        raise ValueError("finite positive native pen width required")
    first, last = endpoints
    vector = last - first
    norm2 = float(np.dot(vector, vector))
    if norm2 <= 0:
        raise ValueError("nonzero LINE required")
    yy, xx = np.indices(shape, dtype=np.float64)
    dx, dy = xx - first[0], yy - first[1]
    dot = dx * vector[0] + dy * vector[1]
    cross = dx * vector[1] - dy * vector[0]
    radius = float(width) / 2.0
    across = cross * cross <= radius * radius * norm2
    if cap == "flat":
        return across & (dot >= 0.0) & (dot <= norm2)
    if cap == "square":
        extension = radius * np.sqrt(norm2)
        return across & (dot >= -extension) & (dot <= norm2 + extension)
    if cap == "round":
        excess = np.maximum(np.maximum(-dot, dot - norm2), 0.0)
        return cross * cross + excess * excess <= radius * radius * norm2
    raise ValueError("unknown terminal cap")


def run_mask(shape, runs):
    mask = np.zeros(shape, bool)
    for y, x0, x1 in runs:
        if not (0 <= y < shape[0] and 0 <= x0 < x1 <= shape[1]):
            raise ValueError("native source run outside complete tile")
        if mask[y, x0:x1].any():
            raise ValueError("overlapping source runs")
        mask[y, x0:x1] = True
    return mask


def audit_candidate_centers(result, *, native_original, scale, working_dpi):
    """Read returned geometry/ledger, independently recompute all center states."""
    source = np.asarray(native_original, bool)
    shape = source.shape
    rows = []
    if "native_residual_runs_y_x0_x1" not in result:
        if result.get("candidates"):
            raise ValueError("candidates without complete native residual")
        return {"status": "NO_CANDIDATE_NO_RETIREMENT", "cap_audits": [],
                "passed": True, "zero_candidate_result_requires_parent_guard_review": True}
    residual = run_mask(shape, result["native_residual_runs_y_x0_x1"])
    union_retired = np.zeros(shape, bool)
    overlaps = 0
    parts = result.get("candidates", [])
    retired_masks = []
    for part in parts:
        retired = run_mask(shape, part["native_retired_source_runs_y_x0_x1"])
        overlaps += int(np.count_nonzero(union_retired & retired))
        union_retired |= retired
        retired_masks.append(retired)
    ledger_exact = (not overlaps and not np.any(union_retired & residual)
                    and np.array_equal(union_retired | residual, source))
    for cap in ("round", "flat", "square"):
        output = residual.copy()
        own_reports = []
        for part, retired in zip(parts, retired_masks):
            work_points = np.asarray(part["points_px"], float)
            points = (work_points + .5) * scale - .5
            width = part["lineweight_hundredth_mm"] * working_dpi * scale / 2540.0
            ink = line_ink(shape, points, width, cap)
            own_reports.append({"part_id": part["part_id"],
                                "retired_source_centers": int(retired.sum()),
                                "missing_own_centers": int(np.count_nonzero(retired & ~ink))})
            output |= ink
        rows.append({"cap": cap, "missing_black_centers": int(np.count_nonzero(source & ~output)),
                     "covered_white_centers": int(np.count_nonzero(output & ~source)),
                     "own_retirement": own_reports,
                     "join_styles": ["round", "mitre", "bevel"],
                     "join_note": "LINE has no interior join; these are the same geometry."})
    passed = bool(ledger_exact and all(row["missing_black_centers"] == row["covered_white_centers"] == 0
                  and all(item["missing_own_centers"] == 0 for item in row["own_retirement"])
                  for row in rows))
    return {"status": "INDEPENDENT_NATIVE_CENTER_AUDIT", "passed": passed,
            "ledger_exact": bool(ledger_exact), "duplicate_retired_centers": overlaps,
            "cap_audits": rows, "source_pixels": int(source.sum()),
            "retained_pixels": int(residual.sum()), "retired_pixels": int(union_retired.sum()),
            "candidate_count": len(parts)}
