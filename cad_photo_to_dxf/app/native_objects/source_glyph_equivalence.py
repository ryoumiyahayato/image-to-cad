"""Resolve a raw character conflict only through an independently read source twin.

This module does not recognize characters or construct strings.  A complete
literal candidate must already have been read by both engine families.  It
compares immutable source samples at two different positions of that same row.
"""

from __future__ import annotations

import hashlib
import json
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree


POLICY = {
    "version": "same-original-row-half-cell-stable-glyph-equivalence-v2",
    "maximum_bbox_dimension_difference_source_px": 2.0,
    "maximum_symmetric_mean_source_px": 0.5,
    "maximum_symmetric_p95_source_px": 1.0,
    "maximum_symmetric_distance_source_px": math.sqrt(2.0),
    "foreground_connectivity": 8,
    "background_connectivity": 4,
    "transform": "bbox_center_and_common_height_uniform_scale_only",
    "registration_offsets_per_axis_source_px": [-0.5, 0.0, 0.5],
    "registration_basis": "finite_symmetric_half_original_pixel_sampling_origin_uncertainty",
    "error_basis": "original_pixel_center_quantization_not_case_score_fitting",
    "topology_comparison": {
        "basis": "features_still_present_after_half_pixel_cell_uncertainty_offset",
        "original_pixel_cell_subdivision": 2,
        "outward_L_infinity_offset_source_px": 0.5,
        "only_original_holes_with_a_surviving_white_core_are_evidence": True,
        "hole_born_from_original_exterior_makes_conclusion_unknown": True,
        "original_topology_always_recorded": True,
        "original_source_or_recognition_mask_modified": False,
    },
    "require_identical_stable_component_and_hole_counts": True,
    "sampling_fallback_requires_unstable_original_topology": True,
    "sampling_fallback_requires_frozen_competing_character_anchor": True,
    "competing_anchor_requires_known_persistent_macro_topology_contradiction": True,
    "anchor_requires_Tesseract_and_strict_PP_literal_character": True,
    "anchor_must_be_undisputed_before_any_resolution": True,
    "raw_candidate_must_already_be_complete": True,
    "source_samples_added_or_removed": False,
    "recognition_or_expected_strings": False,
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def component_samples(component):
    """Validate and decode the recorded original RLE without closing real gaps."""
    bbox = component["bbox_xyxy_px"]
    if (
        len(bbox) != 4
        or any(isinstance(v, bool) or not isinstance(v, int) for v in bbox)
        or not (0 < bbox[2] - bbox[0] <= 160 and 0 < bbox[3] - bbox[1] <= 160)
    ):
        raise ValueError("SOURCE_GLYPH_RLE_BBOX_INVALID")
    x0, y0, x1, y1 = bbox
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    previous = None
    for run in component.get("source_runs_y_x0_x1", []):
        if (
            not isinstance(run, list)
            or len(run) != 3
            or any(isinstance(v, bool) or not isinstance(v, int) for v in run)
        ):
            raise ValueError("SOURCE_GLYPH_RLE_RUN_INVALID")
        y, a, b = run
        if not (y0 <= y < y1 and x0 <= a < b <= x1):
            raise ValueError("SOURCE_GLYPH_RLE_RUN_OUTSIDE_COMPONENT")
        if previous is not None and (
            y < previous[0] or (y == previous[0] and a <= previous[2])
        ):
            raise ValueError("SOURCE_GLYPH_RLE_NOT_CANONICAL")
        mask[y - y0, a - x0 : b - x0] = 1
        previous = run
    yy, xx = np.nonzero(mask)
    if (
        not len(xx)
        or int(mask.sum()) != component.get("source_area_px")
        or [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]
        != [0, 0, x1 - x0, y1 - y0]
        or component.get("source_white_gaps_not_filled") is not True
    ):
        raise ValueError("SOURCE_GLYPH_ORIGINAL_SAMPLES_INCOMPLETE")
    points = np.column_stack((xx + 0.5, yy + 0.5)).astype(float)
    return mask, points


def _topology(mask):
    foreground = cv2.connectedComponents(mask, connectivity=8)[0] - 1
    background = np.pad(1 - mask, 1, constant_values=1)
    # The padded exterior is one background component; the rest are real holes.
    holes = cv2.connectedComponents(background, connectivity=4)[0] - 2
    return {"foreground_components": int(foreground), "background_holes": int(holes)}


def _half_cell_stable_topology(mask):
    """Compare feature persistence; never substitute this mask for source ink.

    An original sample occupies a unit square. Subdivision into four equal
    squares permits its exact half-pixel L-infinity uncertainty offset. A
    one-pixel sampling hole or break can vanish at this resolution; a larger
    hole or gap persists and must agree. Every original point is still used by
    the bidirectional distance test, so an unmatched branch cannot be erased.
    """
    subdivided = np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1)
    padded = np.pad(subdivided, 2, constant_values=0)
    feature = cv2.dilate(padded, np.ones((3, 3), np.uint8))
    _, original_background = cv2.connectedComponents(
        np.pad(1 - mask, 1, constant_values=1), connectivity=4,
    )
    original_exterior = int(original_background[0, 0])
    original_holes = set(map(int, np.unique(original_background))) - {0, original_exterior}
    source_labels = np.repeat(np.repeat(original_background[1:-1, 1:-1], 2, axis=0), 2, axis=1)
    source_labels = np.pad(source_labels, 2, constant_values=original_exterior)
    _, offset_background = cv2.connectedComponents(1 - feature, connectivity=4)
    offset_exterior = int(offset_background[0, 0])
    offset_holes = set(map(int, np.unique(offset_background))) - {0, offset_exterior}
    persistent = [label for label in sorted(original_holes)
                  if np.any((source_labels == label) & (feature == 0))]
    births = [label for label in sorted(offset_holes)
              if np.any((offset_background == label) & (source_labels == original_exterior))]
    # Closing an original C-like slit can create a large apparent hole. It is
    # neither proof of an original hole nor proof of stable absence: unknown
    # prevents both candidate support and competing-character exclusion.
    return {
        "known": not births,
        "foreground_components": int(cv2.connectedComponents(feature, connectivity=8)[0] - 1),
        "background_holes": len(persistent) if not births else None,
        "persistent_original_hole_count": len(persistent),
        "disappeared_original_hole_count": len(original_holes) - len(persistent),
        "new_holes_from_original_exterior": len(births),
    }


def _stable_signature(record):
    if not record["known"]:
        return None
    return {key: record[key] for key in ("foreground_components", "background_holes")}


def _distance_metrics(left, right):
    distances = np.r_[cKDTree(right).query(left)[0], cKDTree(left).query(right)[0]]
    return {
        "symmetric_mean_source_px": float(distances.mean()),
        "symmetric_p95_source_px": float(np.quantile(distances, 0.95)),
        "symmetric_maximum_source_px": float(distances.max()),
    }


def _distance_failures(metrics):
    return [
        "SOURCE_TWIN_EXCEEDS_QUANTIZATION_BOUND:" + metric
        for metric, limit in [
            ("symmetric_mean_source_px", "maximum_symmetric_mean_source_px"),
            ("symmetric_p95_source_px", "maximum_symmetric_p95_source_px"),
            ("symmetric_maximum_source_px", "maximum_symmetric_distance_source_px"),
        ]
        if metrics[metric] > POLICY[limit] + 1e-12
    ]


def compare_original_glyphs(left, right):
    """Compare in source-pixel units under a fixed, symmetric quantization bound."""
    result = {"pass": False, "policy": POLICY, "reasons": []}
    if any(c.get("source_role") != "FULL_HEIGHT_GLYPH" for c in (left, right)):
        result["reasons"].append("EQUIVALENCE_REQUIRES_TWO_FULL_HEIGHT_SOURCE_GLYPHS")
        return result
    try:
        lm, lp = component_samples(left)
        rm, rp = component_samples(right)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        result["reasons"].append(str(error))
        return result
    lbox, rbox = left["bbox_xyxy_px"], right["bbox_xyxy_px"]
    if max(lbox[0], rbox[0]) < min(lbox[2], rbox[2]):
        result["reasons"].append("SOURCE_TWIN_GLYPHS_ARE_NOT_DISTINCT_ROW_POSITIONS")
    lh, lw = lm.shape
    rh, rw = rm.shape
    dimension_difference = [abs(lw - rw), abs(lh - rh)]
    if max(dimension_difference) > POLICY["maximum_bbox_dimension_difference_source_px"]:
        result["reasons"].append("SOURCE_TWIN_DIMENSIONS_DIFFER")
    lt, rt = _topology(lm), _topology(rm)
    stable_left, stable_right = _half_cell_stable_topology(lm), _half_cell_stable_topology(rm)
    ls, rs = _stable_signature(stable_left), _stable_signature(stable_right)
    height = (lh + rh) / 2.0
    lp = (lp - np.array([lw / 2.0, lh / 2.0])) * (height / lh)
    rp = (rp - np.array([rw / 2.0, rh / 2.0])) * (height / rh)
    metrics = _distance_metrics(lp, rp)
    base_reasons = list(result["reasons"])
    strict_reasons = base_reasons + (["SOURCE_TWIN_TOPOLOGY_DIFFERS"] if lt != rt else []) + _distance_failures(metrics)
    registrations = []
    for dx in POLICY["registration_offsets_per_axis_source_px"]:
        for dy in POLICY["registration_offsets_per_axis_source_px"]:
            measured = _distance_metrics(lp, rp + [dx, dy])
            registrations.append({
                "translation_source_px": [dx, dy], "metrics": measured,
                "pass": not _distance_failures(measured),
            })
    passing = [row for row in registrations if row["pass"]]
    selected = min(passing, key=lambda row: (
        row["metrics"]["symmetric_mean_source_px"],
        row["metrics"]["symmetric_p95_source_px"],
        row["metrics"]["symmetric_maximum_source_px"],
        sum(abs(v) for v in row["translation_source_px"]),
        row["translation_source_px"],
    )) if passing else None
    topology_unstable = ls is not None and rs is not None and (lt != ls or rt != rs)
    strict_pass = not strict_reasons
    fallback_pass = bool(not base_reasons and topology_unstable and ls == rs and selected is not None)
    if not strict_pass and not fallback_pass:
        result["reasons"] = base_reasons
        if ls is None or rs is None:
            result["reasons"].append("SOURCE_TWIN_STABLE_TOPOLOGY_UNKNOWN")
        elif ls != rs:
            result["reasons"].append("SOURCE_TWIN_TOPOLOGY_DIFFERS")
        elif not topology_unstable:
            result["reasons"].append("SOURCE_TWIN_FALLBACK_HAS_NO_SAMPLING_TOPOLOGY_UNCERTAINTY")
        if selected is None:
            result["reasons"].append("SOURCE_TWIN_NO_QUANTIZATION_BOUNDED_REGISTRATION")
    else:
        result["reasons"] = []
    result.update(
        pass_=not result["reasons"],
        left_source_component_sha256=_digest(left),
        right_source_component_sha256=_digest(right),
        source_bbox_dimension_difference_px=dimension_difference,
        left_topology=lt,
        right_topology=rt,
        common_height_source_px=height,
        metrics=metrics,
        strict_zero_registration_comparison={"pass": not strict_reasons,
                                             "reasons": strict_reasons,
                                             "metrics": metrics},
        comparison_path=("STRICT_ORIGINAL_PIXEL_TWIN" if strict_pass else
                         "SAMPLING_UNCERTAINTY_CANDIDATE_SUPPORT" if fallback_pass else "REJECTED"),
        sampling_uncertainty_comparison={
            "left_stable_topology": stable_left,
            "right_stable_topology": stable_right,
            "registrations": registrations,
            "selected_registration": selected,
            "original_topology_is_sampling_scale_unstable": topology_unstable,
            "original_points_used_in_every_distance_check": True,
            "feature_mask_written_to_source_or_geometry": False,
            "distance_limits_changed": False,
        },
    )
    result["pass"] = result.pop("pass_")
    return result


def verify_raw_character_conflicts(partition, candidate, tesseract, models):
    """Keep all raw conflicts; verify only characters in an existing full string.

    Each row carries a canonical string plus its already source-checked mapping
    to ordered components.  No engine's raw record is rewritten here.
    """
    parts = partition["components"]
    rows = [*tesseract, *models]
    result = {"pass": False, "policy": POLICY, "conflicts": [], "anchors": []}
    candidates = [r for r in rows if r["text"] == candidate]
    if (
        not any(r["text"] == candidate for r in tesseract)
        or not any(r["text"] == candidate for r in models)
        or any(len(r["component_characters"]) != len(parts) for r in rows)
        or not candidates
    ):
        result["reason"] = "NO_EXISTING_COMPLETE_TWO_ENGINE_LITERAL_CANDIDATE"
        return result
    wanted = candidates[0]["component_characters"]
    if any(r["component_characters"] != wanted for r in candidates):
        result["reason"] = "CANDIDATE_COMPONENT_BINDING_CONFLICT"
        return result
    # Freeze anchors before resolving anything. A corrected position can never
    # become evidence for another correction in this or a later loop iteration.
    for index, component in enumerate(parts):
        if (
            component["source_role"] == "FULL_HEIGHT_GLYPH"
            and all(r["component_characters"][index] == wanted[index] for r in rows)
        ):
            result["anchors"].append({
                "component_index": index,
                "literal_character": wanted[index],
                "Tesseract_view_indices": [r["view_index"] for r in tesseract],
                "strict_PP_view_indices": [r["view_index"] for r in models],
            })
    for row in tesseract:
        if row["text"] == candidate:
            continue
        conflict = {"Tesseract_view_index": row["view_index"], "raw_canonical_text": row["text"],
                    "pass": True, "characters": []}
        for index, (before, after) in enumerate(zip(row["component_characters"], wanted)):
            if before == after:
                continue
            proof = {"component_index": index, "raw_character": before, "candidate_character": after,
                     "pass": False, "matching_anchors": [], "other_character_equivalents": [],
                     "competing_character_macro_contradictions": []}
            if parts[index]["source_role"] == "FULL_HEIGHT_GLYPH":
                for anchor in result["anchors"]:
                    ai = anchor["component_index"]
                    if ai == index:
                        continue
                    comparison = compare_original_glyphs(parts[index], parts[ai])
                    if comparison["pass"]:
                        key = "matching_anchors" if anchor["literal_character"] == after else "other_character_equivalents"
                        proof[key].append({"anchor": anchor, "comparison": comparison})
                    if anchor["literal_character"] == before:
                        sampling = comparison.get("sampling_uncertainty_comparison", {})
                        left_stable = sampling.get("left_stable_topology")
                        right_stable = sampling.get("right_stable_topology")
                        if left_stable and right_stable:
                            left_signature = _stable_signature(left_stable)
                            right_signature = _stable_signature(right_stable)
                            if (left_signature is not None and right_signature is not None
                                    and left_signature != right_signature):
                                proof["competing_character_macro_contradictions"].append({
                                    "anchor": anchor, "comparison": comparison,
                                    "basis": "KNOWN_PERSISTENT_ORIGINAL_TOPOLOGY_CONTRADICTS_COMPETING_LITERAL",
                                    "distance_failure_alone_used_as_exclusion": False,
                                })
                strict_matches = [entry for entry in proof["matching_anchors"]
                                  if entry["comparison"]["comparison_path"] == "STRICT_ORIGINAL_PIXEL_TWIN"]
                proof["pass"] = (bool(proof["matching_anchors"])
                                 and not proof["other_character_equivalents"]
                                 and bool(strict_matches or proof["competing_character_macro_contradictions"]))
                proof["resolution_path"] = (
                    "STRICT_ORIGINAL_PIXEL_TWIN" if strict_matches else
                    "SAMPLING_UNCERTAINTY_AND_FROZEN_COMPETING_SOURCE_CONTRADICTION"
                    if proof["pass"] else None
                )
            if not proof["pass"]:
                proof["reason"] = "RAW_CHARACTER_CONFLICT_HAS_NO_UNIQUE_INDEPENDENT_SOURCE_TWIN"
                conflict["pass"] = False
            conflict["characters"].append(proof)
        result["conflicts"].append(conflict)
    result["pass"] = all(c["pass"] for c in result["conflicts"])
    return result
