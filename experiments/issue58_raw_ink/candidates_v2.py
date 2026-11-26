"""One seed-discovery alternative: non-consuming raw-ink direction voting.

The v1 candidate representation, source-band branching and refusal behavior are
unchanged. Only the axis nomination mechanism changes. Private source locations
and expected shape counts are never used by this module.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import time

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

_spec = importlib.util.spec_from_file_location("raw_ink_band_engine_v1", Path(__file__).with_name("candidates.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
SCHEMA = "raw-ink-finite-band-candidates-v2"
POLICY = deepcopy(base.POLICY)
POLICY.update({
    "version": "non-consuming-raw-ink-votes-section-dag-v2",
    "seed_model": "all_original_pixels_vote_without_removal_then_finite_raw_component_support",
    "accumulator_peak_neighborhood": [3, 3],
    "accumulator_ties": "all_equal_local_maxima_retained",
    "finite_seed_band_half_widths": 0.5,
    "accumulator_minimum_votes": "ceil(minimum_seed_length / sqrt(2))",
    "candidate_band_engine": base.POLICY["version"],
    "unchanged_candidate_geometry_and_ownership_refusals": True,
})


def non_consuming_seeds(ink, points, width):
    """No greedy pixel consumption; all quantized directional peaks compete."""
    if not len(points):
        return [], False
    rho_max = int(math.ceil(math.hypot(ink.shape[1], ink.shape[0]))) + 1
    theta = np.arange(0.0, 180.0, POLICY["hough_theta_degrees"])
    accumulator = np.zeros((len(theta), 2 * rho_max + 1), np.int32)
    for index, angle in enumerate(theta):
        normal = np.array([-math.sin(math.radians(angle)), math.cos(math.radians(angle))])
        rho_bins = np.rint(points @ normal / POLICY["hough_rho_px"]).astype(int) + rho_max
        accumulator[index] = np.bincount(rho_bins, minlength=2 * rho_max + 1)
    # Do not wrap angle boundaries while keeping rho unchanged: an axis angle
    # wrap reverses its normal. A constant border is conservative and may retain
    # equivalent endpoint directions, which are explicitly represented.
    maxima = accumulator == ndimage.maximum_filter(accumulator, size=tuple(POLICY["accumulator_peak_neighborhood"]), mode="constant")
    minimum_length = max(POLICY["minimum_seed_length_px"],
                         math.ceil(POLICY["hough_minimum_length_widths"] * width))
    vote_floor = math.ceil(minimum_length / math.sqrt(2.0))
    peaks = np.argwhere(maxima & (accumulator >= vote_floor))
    groups = defaultdict(list)
    for theta_index, rho_index in peaks:
        angle = float(theta[theta_index])
        axis = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
        normal = np.array([-axis[1], axis[0]])
        rho = float((rho_index - rho_max) * POLICY["hough_rho_px"])
        in_seed_band = abs(points @ normal - rho) <= POLICY["finite_seed_band_half_widths"] * width
        for component in base._components(map(tuple, points[in_seed_band].astype(int))):
            pixels = np.asarray(sorted(component), float)
            projected = pixels @ axis
            lo, hi = float(projected.min()), float(projected.max())
            if hi - lo < minimum_length:
                continue
            centered_rho = float(np.median(pixels @ normal))
            centered_rho = round(centered_rho / POLICY["axis_rho_quantum_px"]) * POLICY["axis_rho_quantum_px"]
            endpoints = [pixels[int(np.argmin(projected))].tolist(), pixels[int(np.argmax(projected))].tolist()]
            groups[(angle, centered_rho)].append({
                "raw_interval_endpoints_local_px": endpoints,
                "finite_seed_interval_px": [lo, hi],
                "finite_seed_original_component_pixels": len(component),
                "accumulator_peak": {"angle_deg": angle, "normal_offset_px": rho,
                                     "raw_pixel_votes": int(accumulator[theta_index, rho_index])},
                "seed_source_components_are_original_8_connected": True,
                "seed_is_not_a_native_line_approval": True,
            })
    rows = [{"angle_deg": angle, "normal_offset_px": rho, "seeds": seeds}
            for (angle, rho), seeds in sorted(groups.items())]
    return rows, len(rows) > POLICY["maximum_seed_axes"]


def discover(gray, roi):
    began = time.perf_counter()
    source = np.asarray(gray)
    if source.ndim != 2 or source.dtype != np.uint8:
        raise ValueError("SOURCE_MUST_BE_UNMODIFIED_UINT8_GRAYSCALE")
    if len(roi) != 4 or any(int(v) != v for v in roi):
        raise ValueError("ROI_MUST_BE_INTEGER_XYXY")
    x0, y0, x1, y1 = map(int, roi)
    if not (0 <= x0 < x1 <= source.shape[1] and 0 <= y0 < y1 <= source.shape[0]):
        raise ValueError("ROI_OUTSIDE_SOURCE")
    crop = source[y0:y1, x0:x1]
    ink = crop < POLICY["source_threshold"]
    origin = np.array([x0, y0])
    edt = ndimage.distance_transform_edt(ink)
    maxima = (edt == ndimage.maximum_filter(edt, size=3, mode="constant")) & ink
    widths = 2.0 * edt[maxima]
    width = max(POLICY["minimum_estimated_width_px"], float(np.median(widths)) if len(widths) else 1.0)
    yy, xx = np.nonzero(ink)
    points = np.column_stack((xx, yy)).astype(float)
    seeds, seed_overflow = non_consuming_seeds(ink, points, width)
    holes = base._holes(ink, origin)
    rows, axes = {}, []
    global_overflow = False
    if not seed_overflow:
        for seed in seeds:
            candidates, summary = base._one_axis(ink, points, edt, width, seed, origin, roi, holes)
            axes.append(summary)
            for row in candidates:
                ident = row["candidate_id"]
                if ident in rows:
                    rows[ident]["seed_axes"].extend(row["seed_axes"])
                else:
                    rows[ident] = row
                if len(rows) > POLICY["maximum_candidate_paths"]:
                    global_overflow = True
                    break
            if global_overflow:
                break
    status = "RESOURCE_LIMIT_CANDIDATES_WITHHELD" if (seed_overflow or global_overflow) else "CANDIDATE_DISCOVERY_ONLY_NO_ADOPTED_OBJECTS"
    if global_overflow:
        rows = {}
    covered = {tuple(p) for row in rows.values() for p in row["source_path_px"]}
    total_ink = {(int(x + x0), int(y + y0)) for x, y in zip(xx, yy)}
    return {
        "schema": SCHEMA, "status": status, "policy": POLICY,
        "policy_sha256": base.digest(POLICY),
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidate_engine_sha256": hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),
        "source_shape_yx": list(source.shape), "roi_xyxy_px": list(map(int, roi)),
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "original_crop_array_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
        "estimated_ink_width_px": width, "width_maxima_count": int(maxima.sum()),
        "seed_axes": seeds, "axis_branch_reports": axes,
        "candidates": list(rows.values()), "adopted_objects": [], "complete_recovered_objects": 0,
        "unexplained_original_ink_pixels_px": [list(p) for p in sorted(total_ink - covered)],
        "unexplained_ink_note": "Raw pixels outside candidate centre traces; includes stroke thickness and neighbors. This is not an object-ownership residual metric.",
        "original_white_holes": holes, "original_source_pixels_modified": False,
        "old_source_graph_used": False, "expensive_OCR_calls": 0, "model_calls": 0,
        "resources": {"seed_axis_overflow": seed_overflow, "candidate_overflow": global_overflow,
                      "axis_branch_overflows": sum(r["status"].startswith("RESOURCE") for r in axes)},
        "environment": {"python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__},
        "wall_seconds": time.perf_counter() - began,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--roi", nargs=4, type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with Image.open(args.input) as im:
        gray = np.array(im.convert("L"))
    result = discover(gray, args.roi)
    result["input_file_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "candidate_count": len(result["candidates"]),
                      "seed_axis_count": len(result["seed_axes"]), "resources": result["resources"],
                      "complete_recovered_objects": 0, "wall_seconds": result["wall_seconds"]}))


if __name__ == "__main__":
    main()
