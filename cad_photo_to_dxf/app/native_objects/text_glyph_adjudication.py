"""Adjudicate a source-supported upper shoulder without invoking OCR.

This is a bounded glyph-shape rule, not a dictionary or a general recognizer.
Inputs are unmodified, binary ink masks (True/1 means ink). Reference labels
must already be reliable, independently sourced observations. No target word,
page, object ID or absolute coordinate is accepted by this API.

The caller verifies the original source hash and exclusive glyph ownership.
This module independently checks the supplied context's hash, exact target
pixels, original white margins, connected support and calibrated shape. It
does not infer clipping or ownership outside that verified context. An absent
reference class is reported, not silently treated as a negative example.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import math
from statistics import median

import numpy as np


POLICY_VERSION = "source_upper_shoulder_adjudication_v1"
MIN_INDEPENDENT_REFERENCES = 3


def _ink(bitmap):
    a = np.asarray(bitmap)
    if a.ndim != 2 or not a.size or a.size > 65536:
        raise ValueError("bitmap must be a nonempty bounded 2D ink mask")
    if not np.isin(a, [0, 1]).all():
        raise ValueError("bitmap must use bool/0-1 ink, not inferred image polarity")
    return a.astype(bool, copy=True)


def bitmap_sha256(bitmap):
    """Canonical hash of a bool/0-1 ink mask, including its dimensions."""
    a = _ink(bitmap)
    prefix = f"{a.shape[0]},{a.shape[1]}:".encode("ascii")
    return hashlib.sha256(prefix + a.astype(np.uint8).tobytes()).hexdigest()


def _components(a):
    remaining = {tuple(p) for p in np.argwhere(a).tolist()}
    sizes = []
    while remaining:
        stack = [remaining.pop()]
        size = 0
        while stack:
            y, x = stack.pop()
            size += 1
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    p = y + dy, x + dx
                    if p in remaining:
                        remaining.remove(p)
                        stack.append(p)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def _describe(a):
    yy, xx = np.where(a)
    if not len(xx):
        raise ValueError("empty glyph support")
    box = [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]
    x0, y0, x1, y1 = box
    a = a[y0:y1, x0:x1]
    h, w = a.shape
    if h < 6:
        raise ValueError("glyph is too small for a shoulder/body separation")
    split = math.ceil(h / 3)
    rows = [np.flatnonzero(row) for row in a]
    body = [row for row in rows[split:] if len(row)]
    if not body:
        raise ValueError("glyph has no lower-body support")
    body_left = int(median([int(row[0]) for row in body]))
    body_right = int(median([int(row[-1]) for row in body]))
    stem = int(np.argmax(a[split:].sum(axis=0)))
    upper_y, upper_x = np.where(a[:split])
    left = int(upper_x.min())
    extension = max(0, body_left - left)

    # Each step uses an existing pixel and advances one column, with no down
    # step. Horizontal top serifs cannot manufacture an ascending shoulder.
    best = []
    if extension:
        for sy in np.flatnonzero(a[:split, left]):
            paths = {int(sy): [[left, int(sy)]]}
            for x in range(left + 1, body_left + 1):
                following = {}
                for y, path in paths.items():
                    for next_y in (y, y - 1):
                        if 0 <= next_y < split and a[next_y, x]:
                            following.setdefault(next_y, path + [[x, next_y]])
                paths = following
            if paths:
                path = paths[min(paths)]
                if not best or path[0][1] - path[-1][1] > best[0][1] - best[-1][1]:
                    best = path
    rise = best[0][1] - best[-1][1] if best else 0
    component_sizes = _components(a)
    metrics = {
        "height_px": h,
        "width_px": w,
        "ink_pixels": int(a.sum()),
        "tight_bbox_in_bitmap": box,
        "component_sizes": component_sizes,
        "component_count": len(component_sizes),
        "body_start_row": split,
        "body_left_column": body_left,
        "body_right_column": body_right,
        "body_width_px": body_right - body_left + 1,
        "stem_column": stem,
        "stem_occupied_rows": int(a[:, stem].sum()),
        "occupied_rows": sum(bool(len(row)) for row in rows),
        "blank_rows": [i for i, row in enumerate(rows) if not len(row)],
        "upper_width_px": int(upper_x.max() - upper_x.min() + 1),
        "left_extension_px": extension,
        "left_extension_per_height": extension / h,
        "ascending_path": best,
        "ascending_path_rise_px": rise,
        "ascending_path_rise_per_height": rise / h,
        "row_ink_extents": [
            [int(row[0]), int(row[-1]), len(row)] if len(row) else None
            for row in rows
        ],
        "bitmap_sha256": bitmap_sha256(a),
    }
    yy, xx = np.where(a)
    points = set(zip((xx - stem).tolist(), yy.tolist()))
    return metrics, points


def _distance(first, second):
    """Raw-pixel Jaccard distance; registration only, never resampling ink."""
    return min(
        len(first ^ shifted) / len(first | shifted)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for shifted in [{(x + dx, y + dy) for x, y in second}]
    )


def _context_check(target, context, box, evidence):
    result = {"verified": False, "reasons": []}
    if context is None or box is None or not isinstance(evidence, dict):
        result["reasons"].append("verified_source_context_missing")
        return result
    try:
        context = _ink(context)
        if len(box) != 4 or any(int(v) != v for v in box):
            raise ValueError("invalid target context box")
        x0, y0, x1, y1 = map(int, box)
        if not (0 <= x0 < x1 <= context.shape[1] and 0 <= y0 < y1 <= context.shape[0]):
            raise ValueError("target context box out of bounds")
        if not np.array_equal(context[y0:y1, x0:x1], target):
            result["reasons"].append("context_target_pixels_differ")
        digest = bitmap_sha256(context)
        result["context_sha256"] = digest
        if evidence.get("context_sha256") != digest:
            result["reasons"].append("context_hash_not_verified")
        for flag in ("source_hash_verified", "ownership_verified", "no_shared_source"):
            if evidence.get(flag) is not True:
                result["reasons"].append(flag + "_missing")
        source_hash = evidence.get("source_sha256", "")
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(
            c not in "0123456789abcdefABCDEF" for c in source_hash
        ):
            result["reasons"].append("source_identity_missing")
        result["source_sha256"] = source_hash
        margins = [x0, y0, context.shape[1] - x1, context.shape[0] - y1]
        required = [2, math.ceil(target.shape[0] / 3), 2, 2]
        result["white_margin_px_left_top_right_bottom"] = margins
        result["required_margin_px_left_top_right_bottom"] = required
        if any(a < b for a, b in zip(margins, required)):
            result["reasons"].append("source_context_margin_insufficient")
        outside = context.copy()
        outside[y0:y1, x0:x1] = False
        result["outside_target_ink_pixels"] = int(outside.sum())
        if outside.any():
            result["reasons"].append("additional_source_ink_or_detached_dot")
    except (TypeError, ValueError, IndexError) as exc:
        result["reasons"].append("invalid_source_context:" + str(exc))
    result["verified"] = not result["reasons"]
    return result


def propose_glyph_identity(
    target_bitmap,
    references,
    alternatives,
    *,
    source_complete=True,
    context_bitmap=None,
    target_bbox_in_context=None,
    source_evidence=None,
):
    """Return a JSON-safe proposal and its calibration; never rewrite text.

    references is a list of {character, bitmap, reliable, reference_id,
    independence_key?}. Aliases with the same independence key or identical
    pixels count once. Three independent reliable samples per participating
    class are required. Known fragmented glyphs may remain negative controls;
    a positive shoulder reference and the target must each be one component.

    source_evidence attests source_hash_verified, ownership_verified and
    no_shared_source, supplies the original source_sha256 and binds the context
    using bitmap_sha256(context_bitmap). These are checked caller assertions,
    not claims that this function has opened or hashed the complete drawing.

    Missing alternative samples remain an explicit limitation. Positive source
    shape, a verified complete isolated context and observed class separation
    must supply the evidence; absence of a dot alone can never select a label.
    """
    report = {
        "policy_version": POLICY_VERSION,
        "accepted": False,
        "character": None,
        "preferred_character": None,
        "reason": None,
        "reasons": [],
        "metrics": {},
        "calibration": {},
        "context": {},
        "limitations": [
            "Reference similarity does not establish the original font identity.",
            "This finite shape rule does not certify arbitrary fonts or source degradation.",
        ],
        "source_pixels_modified": False,
        "ocr_called": False,
        "formal_text_contract_modified": False,
    }
    try:
        target = _ink(target_bitmap)
        metrics, points = _describe(target)
    except (TypeError, ValueError) as exc:
        report["reason"] = "invalid_target_bitmap"
        report["reasons"] = [str(exc)]
        return report
    report["metrics"] = metrics
    report["context"] = _context_check(
        target, context_bitmap, target_bbox_in_context, source_evidence
    )
    if source_complete is not True:
        report["reasons"].append("source_incomplete_or_clipped")
    if metrics["component_count"] != 1 or metrics["blank_rows"]:
        report["reasons"].append("target_support_fragmented_or_multiple_components")
    if metrics["tight_bbox_in_bitmap"] != [0, 0, target.shape[1], target.shape[0]]:
        report["reasons"].append("target_bitmap_not_tight_support")
    report["reasons"].extend(report["context"]["reasons"])
    allowed = {c for c in alternatives if isinstance(c, str) and len(c) == 1}
    grouped = defaultdict(list)
    exclusions, seen_keys, seen_pixels = [], {}, {}
    for index, ref in enumerate(references):
        if index >= 64:
            exclusions.append({"reason": "bounded_reference_budget_exceeded"})
            break
        identity = ref.get("independence_key") or ref.get("reference_id")
        label = ref.get("character")
        try:
            if ref.get("reliable") is not True or not identity or not isinstance(identity, str):
                raise ValueError("reliability_or_independent_source_missing")
            if not isinstance(label, str) or len(label) != 1:
                raise ValueError("invalid_reference_character")
            mask = _ink(ref["bitmap"])
            rm, rp = _describe(mask)
            fingerprint = rm["bitmap_sha256"]
            if (identity in seen_keys and seen_keys[identity] != (label, fingerprint)) or (
                fingerprint in seen_pixels and seen_pixels[fingerprint] != label
            ):
                report["reasons"].append("contradictory_reference_label_or_source_alias")
                raise ValueError("reference_label_or_source_alias_conflict")
            if identity in seen_keys or fingerprint in seen_pixels:
                raise ValueError("duplicate_reference_evidence")
            seen_keys[identity] = (label, fingerprint)
            seen_pixels[fingerprint] = label
            grouped[label].append({"id": identity, "metrics": rm, "points": rp})
        except (KeyError, TypeError, ValueError) as exc:
            exclusions.append({"reference_id": identity, "reason": str(exc)})
    # A known reliable counterexample is never discarded for having fewer
    # examples than the positive-class sample requirement.
    groups = dict(grouped)
    sufficiently_sampled = {c for c, rs in groups.items() if len(rs) >= MIN_INDEPENDENT_REFERENCES}
    missing = sorted(allowed - sufficiently_sampled)
    if missing:
        report["limitations"].append(
            "No sufficiently sampled reliable reference class for: " + ", ".join(missing)
        )
    calibration = {
        "minimum_independent_references": MIN_INDEPENDENT_REFERENCES,
        "missing_or_insufficient_alternative_classes": missing,
        "reference_exclusions": exclusions,
        "reference_counts": {c: len(rs) for c, rs in grouped.items()},
        "classes": {},
        "pixel_distance": "raw_pixel_jaccard_after_stem_alignment_and_at_most_one_pixel_translation",
        "pixel_resampling_or_filling": False,
    }
    report["calibration"] = calibration
    distances = {}
    for char, refs in groups.items():
        pairs = [[_distance(a["points"], b["points"]) for b in refs] for a in refs]
        leave_one_out = [
            min((v for j, v in enumerate(row) if i != j), default=None)
            for i, row in enumerate(pairs)
        ]
        radius = max((v for v in leave_one_out if v is not None), default=None)
        target_distances = [_distance(points, r["points"]) for r in refs]
        distances[char] = min(target_distances)
        other_refs = [r for other, rs in groups.items() if other != char for r in rs]
        trials = []
        for i, ref in enumerate(refs):
            other_distance = min((_distance(ref["points"], r["points"]) for r in other_refs), default=None)
            trials.append({
                "reference_id": ref["id"],
                "nearest_same_class_distance": leave_one_out[i],
                "nearest_other_class_distance": other_distance,
                "nearest_class_separated": other_distance is not None and leave_one_out[i] is not None and leave_one_out[i] < other_distance,
            })
        calibration["classes"][char] = {
            "reference_ids": [r["id"] for r in refs],
            "height_range_px": [min(r["metrics"]["height_px"] for r in refs), max(r["metrics"]["height_px"] for r in refs)],
            "body_width_range_px": [min(r["metrics"]["body_width_px"] for r in refs), max(r["metrics"]["body_width_px"] for r in refs)],
            "left_extension_per_height_range": [min(r["metrics"]["left_extension_per_height"] for r in refs), max(r["metrics"]["left_extension_per_height"] for r in refs)],
            "ascending_rise_per_height_range": [min(r["metrics"]["ascending_path_rise_per_height"] for r in refs), max(r["metrics"]["ascending_path_rise_per_height"] for r in refs)],
            "target_distances": target_distances,
            "nearest_target_distance": min(target_distances),
            "largest_pairwise_distance": max(max(row) for row in pairs),
            "nearest_neighbor_leave_one_out_radius": radius,
            "target_inside_nearest_neighbor_radius": radius is not None and min(target_distances) <= radius,
            "leave_one_out": trials,
            "reference_metrics": [r["metrics"] for r in refs],
        }

    candidates = []
    for char, refs in groups.items():
        if char not in allowed or char not in sufficiently_sampled:
            continue
        others = [r for c, rs in groups.items() if c != char for r in rs]
        if len(others) < MIN_INDEPENDENT_REFERENCES or any(r["metrics"]["component_count"] != 1 for r in refs):
            continue
        own = calibration["classes"][char]
        comparisons = {}
        for name in ("left_extension_per_height", "ascending_path_rise_per_height"):
            positive_min = min(r["metrics"][name] for r in refs)
            negative_max = max(r["metrics"][name] for r in others)
            comparisons[name] = {
                "positive_min": positive_min,
                "negative_max": negative_max,
                "threshold": (positive_min + negative_max) / 2,
                "reference_classes_separated": positive_min > negative_max,
                "target_passes": metrics[name] > (positive_min + negative_max) / 2,
            }
        own["shoulder_calibration"] = comparisons
        if not all(x["reference_classes_separated"] and x["target_passes"] for x in comparisons.values()):
            continue
        candidates.append(char)
    if len(candidates) != 1:
        report["reasons"].append("no_unique_reference_calibrated_continuous_shoulder")
    else:
        char = candidates[0]
        report["preferred_character"] = char
        own = calibration["classes"][char]
        for metric, bounds in (("height_px", "height_range_px"), ("body_width_px", "body_width_range_px")):
            low, high = own[bounds]
            if not low - 1 <= metrics[metric] <= high + 1:
                report["reasons"].append("target_" + metric + "_outside_reference_quantization_envelope")
        if not metrics["ascending_path"]:
            report["reasons"].append("ascending_source_path_missing")
        if metrics["stem_occupied_rows"] < metrics["height_px"] - 1:
            report["reasons"].append("continuous_main_stem_support_missing")
        if own["nearest_target_distance"] > own["largest_pairwise_distance"] + 1e-12:
            report["reasons"].append("target_pixels_outside_observed_class_diameter")
        if own["nearest_target_distance"] >= min(v for c, v in distances.items() if c != char):
            report["reasons"].append("pixel_nearest_class_conflicts_with_shoulder")
        if not all(row["nearest_class_separated"] for row in own["leave_one_out"]):
            report["reasons"].append("reference_leave_one_out_class_conflict")
        if not own["target_inside_nearest_neighbor_radius"]:
            report["limitations"].append(
                "Target is outside the nearest-neighbor leave-one-out radius; "
                "adoption also requires the positive shoulder, class diameter and complete source context."
            )
    report["accepted"] = bool(report["preferred_character"] and not report["reasons"])
    if report["accepted"]:
        report["character"] = report["preferred_character"]
        report["reason"] = "positive_continuous_shoulder_with_verified_source_context"
    else:
        report["reason"] = report["reasons"][0]
    return report
