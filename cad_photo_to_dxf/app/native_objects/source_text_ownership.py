"""Separate compact candidate ink from evidenced character ownership.

A low OCR confidence alone never releases source ink. Only an entire isolated
component already proposed by the source-geometry component path is eligible.
Its original pixels must still pass the same line-shape/source gates, it must
have no reliable current word support, and it must fail every applicable text
row layout while having no neighboring source-glyph row witness. All old masks
and every decision remain evidence; this does not erase or relabel the raster.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image

from .contracts import validate_text_regions
from .text_line_domains import POLICY as ROW_POLICY
from .text_regions import POLICY as TEXT_POLICY
from .text_regions import _rle, source_array_sha256

VERSION = "isolated_source_component_text_ownership_v2"


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def _component_points(labels, stats, label, roi):
    x, y, width, height, _ = map(int, stats[label])
    yy, xx = np.nonzero(labels[y : y + height, x : x + width] == label)
    return np.column_stack((xx + x + roi[0], yy + y + roi[1])).astype(float)


def _source_line_evidence(candidate, points, box, roi):
    if len(points) != candidate["source_component_area"]:
        return {
            "checks": {"source_component_area_matches_cached_geometry": False},
            "qualified": False,
            "source_area_px": len(points),
            "cached_area_px": candidate["source_component_area"],
        }
    first = np.asarray(candidate["geometry"]["start"], dtype=float)
    last = np.asarray(candidate["geometry"]["end"], dtype=float)
    length = float(np.linalg.norm(last - first))
    if length <= 0:
        return {"checks": {"positive_length": False}, "qualified": False}
    direction = (last - first) / length
    normal = np.array([-direction[1], direction[0]])
    centered = points - points.mean(axis=0)
    t = (points - first) @ direction
    offsets = centered @ normal
    thickness_span = float(np.ptp(offsets))
    samples = np.linspace(first, last, max(2, int(length) + 1))
    # Distances to this complete source component, not to unrelated nearby ink.
    distance = np.sqrt(
        np.min(np.sum((samples[:, None, :] - points[None, :, :]) ** 2, axis=2), axis=1)
    )
    outside = distance > 2.0
    edges = np.diff(np.r_[False, outside, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    white_gap = int(max(ends - starts, default=0))
    arithmetic_bound = (
        256 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(points))))
    )
    endpoint_error = max(abs(float(t.min())), abs(float(t.max()) - length))
    width, height = box[2] - box[0], box[3] - box[1]
    checks = {
        "source_component_area_matches_cached_geometry": len(points)
        == candidate["source_component_area"],
        "complete_component_is_interior_to_requested_source": bool(
            box[0] > roi[0] and box[1] > roi[1] and box[2] < roi[2] and box[3] < roi[3]
        ),
        "same_source_short_component_size_gate": 10 <= max(width, height) <= 100
        and len(points) >= 10,
        "same_source_length_gate": length >= 12,
        "same_source_cross_section_span_gate": thickness_span <= 5,
        "same_source_aspect_gate": length / max(1.0, thickness_span) >= 5,
        "same_source_normal_residual_gate": float(np.quantile(np.abs(offsets), 0.95))
        <= 2,
        "cached_axis_endpoints_are_actual_component_extrema": endpoint_error
        <= arithmetic_bound,
        "same_source_coverage_gate": float(np.mean(distance <= 2)) >= 0.98,
        "same_source_white_gap_gate": white_gap <= 5,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    return {
        "checks": checks,
        "qualified": all(checks.values()),
        "length_px": length,
        "normal_span_px": thickness_span,
        "p95_normal_residual_px": float(np.quantile(np.abs(offsets), 0.95)),
        "component_supported_fraction": float(np.mean(distance <= 2)),
        "maximum_white_gap_px": white_gap,
        "axis_endpoint_error_px": endpoint_error,
        "arithmetic_error_bound_px": arithmetic_bound,
        "new_fit_executed": False,
        "source_localization_tolerances_changed": False,
    }


def _word_support(region, points, box):
    evidence = []
    for word in region.get("words", []):
        b = word["bbox_xyxy_px"]
        inside = (
            (points[:, 0] >= b[0])
            & (points[:, 0] < b[2])
            & (points[:, 1] >= b[1])
            & (points[:, 1] < b[3])
        )
        if not np.any(inside):
            continue
        height = float(b[3] - b[1])
        component_height = float(box[3] - box[1])
        ratio = component_height / height
        baseline_ratio = abs(box[3] - b[3]) / max(height, component_height)
        layout = (
            ROW_POLICY["source_component_height_ratio"][0]
            <= ratio
            <= ROW_POLICY["source_component_height_ratio"][1]
            and baseline_ratio <= ROW_POLICY["source_component_baseline_ratio"]
        )
        numeric = str(word.get("text", "")).isdigit()
        required = float(
            word.get(
                "required_confidence",
                TEXT_POLICY["minimum_numeric_word_confidence"]
                if numeric
                else TEXT_POLICY["minimum_word_confidence"],
            )
        )
        reliable = (
            word.get("agreement_pass") is True
            and float(word.get("confidence", -1)) >= required
        )
        # Approved manual/source-review content is retained, never silently
        # converted back to geometry by this automatic adapter.
        reviewed = bool(
            region.get("accepted") or region.get("explicit_source_review_accepted")
        )
        evidence.append(
            {
                "region_id": region["id"],
                "word_id": word.get("id"),
                "text": word.get("text"),
                "bbox_xyxy_px": list(b),
                "source_pixels_in_word_box": int(np.count_nonzero(inside)),
                "confidence": word.get("confidence"),
                "required_confidence": required,
                "independent_agreement_pass": word.get("agreement_pass") is True,
                "reliable_word_support": reliable or reviewed,
                "source_component_height_ratio": ratio,
                "source_component_baseline_ratio": baseline_ratio,
                "matches_existing_source_row_policy": bool(layout),
                "source_review_accepted": reviewed,
            }
        )
    return evidence


def _fragmented_character_witnesses(
    label, points, box, word_records, labels, stats, roi
):
    """Veto release when a nearby source fragment completes a text-sized shape.

    A disconnected parenthesis, I, or other character can have an individually
    line-like fragment. This is a conservative ownership veto, not character
    recognition. It reuses the existing two-pixel source localization distance
    and the existing row-height/baseline policy. No pixels are joined or erased.
    """
    witnesses = []
    for other_label, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if other_label == label or area < 3:
            continue
        other_box = [
            int(x + roi[0]),
            int(y + roi[1]),
            int(x + roi[0] + width),
            int(y + roi[1] + height),
        ]
        # A vertical fragment continuation must overlap horizontally and have
        # no more than the already used source localization distance between it.
        if max(box[0], other_box[0]) >= min(box[2], other_box[2]):
            continue
        vertical_gap = max(other_box[1] - box[3], box[1] - other_box[3], 0)
        if vertical_gap > 2:
            continue
        union_box = [
            min(box[0], other_box[0]),
            min(box[1], other_box[1]),
            max(box[2], other_box[2]),
            max(box[3], other_box[3]),
        ]
        matching_words = []
        for word in word_records:
            b = word["bbox_xyxy_px"]
            if not (
                b[0] <= union_box[0]
                and b[1] <= union_box[1]
                and union_box[2] <= b[2]
                and union_box[3] <= b[3]
            ):
                continue
            word_height = b[3] - b[1]
            combined_height = union_box[3] - union_box[1]
            ratio = combined_height / word_height
            baseline = abs(union_box[3] - b[3]) / max(word_height, combined_height)
            if (
                ROW_POLICY["source_component_height_ratio"][0]
                <= ratio
                <= ROW_POLICY["source_component_height_ratio"][1]
                and baseline <= ROW_POLICY["source_component_baseline_ratio"]
            ):
                matching_words.append(
                    {
                        "region_id": word["region_id"],
                        "word_id": word["word_id"],
                        "bbox_xyxy_px": b,
                        "combined_height_ratio": ratio,
                        "combined_baseline_ratio": baseline,
                    }
                )
        if not matching_words:
            continue
        other_points = _component_points(labels, stats, other_label, roi)
        distance = float(
            np.sqrt(
                np.min(
                    np.sum((points[:, None, :] - other_points[None, :, :]) ** 2, axis=2)
                )
            )
        )
        if distance <= 2:
            witnesses.append(
                {
                    "other_source_component_label": other_label,
                    "other_bbox_xyxy_px": other_box,
                    "other_source_area_px": int(area),
                    "source_pixel_minimum_distance_px": distance,
                    "combined_bbox_xyxy_px": union_box,
                    "word_layout_support": matching_words,
                    "source_pixels_joined": False,
                    "recognized_character_identity_claimed": False,
                }
            )
    return witnesses


def reconcile_source_text_ownership(
    text_data, image, roi, geometry_candidates, output_dir=None
):
    """Return a deep-copied text result and a complete source-ownership audit.

    ``geometry_candidates`` must be the already source-bound geometry checkpoint;
    the adapter validates each proposed component against the unchanged raster.
    Text, groups, completeness and adoption decisions are deliberately immutable.
    """
    started = time.perf_counter()
    cv2.setNumThreads(1)
    roi = list(map(int, roi))
    validate_text_regions(text_data, image.shape, roi)
    source_hash = source_array_sha256(image)
    if text_data.get("source_array_sha256") != source_hash:
        raise ValueError("SOURCE_TEXT_OWNERSHIP_ARRAY_BINDING_MISMATCH")
    if text_data.get("source_text_ownership", {}).get("version") == VERSION:
        prior = text_data["source_text_ownership"]
        if prior.get("source_array_sha256") != source_hash:
            raise ValueError("SOURCE_TEXT_OWNERSHIP_EXISTING_BINDING_MISMATCH")
        return copy.deepcopy(text_data), {
            **copy.deepcopy(prior),
            "already_reconciled_no_second_release": True,
        }
    x0, y0, x1, y1 = roi
    raw = image[y0:y1, x0:x1]
    ink = np.ascontiguousarray((raw < TEXT_POLICY["source_threshold"]).astype(np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # Source-only compact neighbor witnesses use the existing text proposal
    # heuristic. Their presence vetoes release even when OCR itself is poor.
    glyphs = []
    for label, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if (
            TEXT_POLICY["minimum_glyph_height"]
            <= height
            <= TEXT_POLICY["maximum_glyph_height"]
            and 2 <= width <= 120
            and area >= 8
            and 0.035 <= area / (width * height) <= 0.88
            and 0.04 <= width / height <= 5.0
        ):
            glyphs.append(
                (
                    label,
                    [
                        int(x + x0),
                        int(y + y0),
                        int(x + x0 + width),
                        int(y + y0 + height),
                    ],
                )
            )
    result = copy.deepcopy(text_data)
    source_geometry_rows = geometry_candidates.get("short_source_components")
    if not isinstance(source_geometry_rows, list):
        raise ValueError("SOURCE_TEXT_OWNERSHIP_REQUIRES_SAVED_COMPONENT_PROPOSALS")
    candidates_by_label = {}
    for candidate in source_geometry_rows:
        if candidate.get("decision") != "DEFER_TEXT_OWNERSHIP":
            continue
        endpoints = np.asarray(
            [candidate["geometry"]["start"], candidate["geometry"]["end"]], dtype=float
        )
        center = endpoints.mean(axis=0) - np.asarray(roi[:2])
        cx, cy = map(int, np.rint(center))
        left, right = max(0, cx - 3), min(labels.shape[1], cx + 4)
        top, bottom = max(0, cy - 3), min(labels.shape[0], cy + 4)
        yy, xx = np.nonzero(labels[top:bottom, left:right])
        if not len(xx):
            continue
        nearest = int(
            np.argmin((xx + left - center[0]) ** 2 + (yy + top - center[1]) ** 2)
        )
        label = int(labels[yy[nearest] + top, xx[nearest] + left])
        candidates_by_label.setdefault(label, []).append(candidate)
    events, released = [], set()
    original_masks = {
        r["id"]: copy.deepcopy(r.get("compact_source_ink_mask", {}))
        for r in result["regions"]
    }
    for label, candidates in sorted(candidates_by_label.items()):
        x, y, width, height, area = map(int, stats[label])
        box = [x + x0, y + y0, x + x0 + width, y + y0 + height]
        points = _component_points(labels, stats, label, roi)
        # A grey source can have different 128/192 components. Do not quietly
        # trim a connected component or treat its partial binary core as whole.
        same_binary_component = bool(
            np.all(image[points[:, 1].astype(int), points[:, 0].astype(int)] < 128)
        )
        mask_regions = []
        for region in result["regions"]:
            runs = region.get("compact_source_ink_mask", {}).get("runs_y_x0_x1", [])
            owns_any = any(
                box[1] <= gy < box[3]
                and max(lo, box[0]) < min(hi, box[2])
                and np.any(
                    labels[gy - y0, max(lo, box[0]) - x0 : min(hi, box[2]) - x0]
                    == label
                )
                for gy, lo, hi in runs
            )
            if owns_any:
                mask_regions.append(region["id"])
        if not mask_regions:
            continue
        independent = [_source_line_evidence(c, points, box, roi) for c in candidates]
        word_records = [
            record
            for region in result["regions"]
            for record in _word_support(region, points, box)
        ]
        fragmented_character_witnesses = _fragmented_character_witnesses(
            label, points, box, word_records, labels, stats, roi
        )
        neighbor_witnesses = []
        for other_label, b in glyphs:
            if other_label == label:
                continue
            other_height = b[3] - b[1]
            ratio = other_height / height
            gap = max(b[0] - box[2], box[0] - b[2], 0)
            if (
                ROW_POLICY["source_component_height_ratio"][0]
                <= ratio
                <= ROW_POLICY["source_component_height_ratio"][1]
                and abs(b[3] - box[3])
                <= ROW_POLICY["source_row_baseline_glyph_heights"] * height
                and gap <= ROW_POLICY["source_row_join_gap_glyph_heights"] * height
            ):
                neighbor_witnesses.append(
                    {
                        "component_label": other_label,
                        "bbox_xyxy_px": b,
                        "height_ratio": ratio,
                        "baseline_delta_px": abs(b[3] - box[3]),
                        "horizontal_gap_px": gap,
                    }
                )
        checks = {
            "whole_source_component_matches_geometry_threshold": same_binary_component,
            "independent_cached_source_line_geometry_passes": any(
                e["qualified"] for e in independent
            ),
            "no_reliable_current_word_or_review_ownership": not any(
                w["reliable_word_support"] for w in word_records
            ),
            "no_source_layout_character_witness": not any(
                w["matches_existing_source_row_policy"] for w in word_records
            ),
            "no_neighboring_source_glyph_row_witness": not neighbor_witnesses,
            "no_fragmented_character_source_witness": not fragmented_character_witnesses,
            "component_is_in_existing_text_candidate_mask": bool(mask_regions),
        }
        release = all(checks.values())
        if release:
            released.add(label)
        local = labels[y : y + height, x : x + width] == label
        events.append(
            {
                "source_component_label": label,
                "bbox_xyxy_px": box,
                "source_area_px": area,
                "cached_source_candidate_ids": [c["id"] for c in candidates],
                "candidate_geometries": [c["geometry"] for c in candidates],
                "source_component_runs_y_x0_x1": _rle(local, box[:2]),
                "original_mask_region_ids": mask_regions,
                "word_evidence": word_records,
                "neighboring_source_glyph_row_witnesses": neighbor_witnesses,
                "independent_geometry_evidence": independent,
                "fragmented_character_source_witnesses": fragmented_character_witnesses,
                "checks": checks,
                "decision": "RELEASE_TO_SOURCE_GEOMETRY_CLASSIFICATION"
                if release
                else "RETAIN_TEXT_OR_UNKNOWN_OWNERSHIP",
                "geometry_adoption_not_authorized_by_this_decision": True,
                "source_pixels_deleted": 0,
                "engineering_stroke_identity_claimed": False,
            }
        )
    mask_changes = []
    for region in result["regions"]:
        prior = original_masks[region["id"]]
        if not prior:
            continue
        kept = []
        removed = 0
        for gy, lo, hi in prior["runs_y_x0_x1"]:
            lab = labels[gy - y0, lo - x0 : hi - x0]
            remove = np.isin(lab, list(released))
            removed += int(np.count_nonzero(remove))
            padded = np.r_[False, ~remove, False].astype(np.int8)
            delta = np.diff(padded)
            kept.extend(
                [
                    [int(gy), int(lo + a), int(lo + b)]
                    for a, b in zip(
                        np.flatnonzero(delta == 1), np.flatnonzero(delta == -1)
                    )
                ]
            )
        if removed:
            region["source_text_ownership_prior_compact_mask"] = prior
            region["compact_source_ink_mask"] = {
                **prior,
                "runs_y_x0_x1": kept,
                "component_labels": [
                    lab
                    for lab in prior.get("component_labels", [])
                    if lab not in released
                ],
                "source_erasure_authorized": False,
                "ownership_reconciliation_version": VERSION,
            }
            mask_changes.append(
                {
                    "region_id": region["id"],
                    "removed_from_text_candidate_mask_pixels": removed,
                    "original_mask_sha256": _digest(prior),
                    "new_mask_sha256": _digest(region["compact_source_ink_mask"]),
                    "removed_pixels_still_in_original_source_and_geometry_candidate_evidence": True,
                }
            )
    for old, new in zip(text_data["regions"], result["regions"]):
        keys = set(old) - {"compact_source_ink_mask"}
        if any(_digest(old[k]) != _digest(new[k]) for k in keys):
            raise RuntimeError("SOURCE_TEXT_OWNERSHIP_MODIFIED_RECOGNITION_OR_ADOPTION")
    if (
        result["groups"] != text_data["groups"]
        or source_array_sha256(image) != source_hash
    ):
        raise RuntimeError("SOURCE_TEXT_OWNERSHIP_MODIFIED_TEXT_GROUPS_OR_SOURCE")
    audit = {
        "version": VERSION,
        "source_array_sha256": source_hash,
        "roi_xyxy_px": roi,
        "upstream_text_sha256": _digest(text_data),
        "saved_geometry_proposals_sha256": _digest(geometry_candidates),
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "existing_source_row_policy": {
            k: copy.deepcopy(ROW_POLICY[k])
            for k in (
                "source_component_height_ratio",
                "source_component_baseline_ratio",
                "source_row_baseline_glyph_heights",
                "source_row_join_gap_glyph_heights",
            )
        },
        "events": events,
        "mask_changes": mask_changes,
        "released_component_labels": sorted(released),
        "released_unique_source_pixels": sum(
            int(stats[label, 4]) for label in released
        ),
        "source_pixels_removed": 0,
        "OCR_calls": 0,
        "source_fits": 0,
        "text_groups_content_completeness_and_adoption_unchanged": True,
        "classification_only_not_native_acceptance": True,
        "wall_seconds": time.perf_counter() - started,
    }
    result["source_text_ownership"] = audit
    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        before = np.zeros_like(raw, dtype=np.uint8)
        after = np.zeros_like(raw, dtype=np.uint8)
        for masks, target in (
            (original_masks.values(), before),
            ([r["compact_source_ink_mask"] for r in result["regions"]], after),
        ):
            for mask in masks:
                for gy, lo, hi in mask.get("runs_y_x0_x1", []):
                    target[gy - y0, lo - x0 : hi - x0] = 255
        Image.fromarray(before).save(output / "original_compact_candidate_mask.png")
        Image.fromarray(after).save(output / "compact_glyph_candidate_mask.png")
        Image.fromarray(np.isin(labels, list(released)).astype(np.uint8) * 255).save(
            output / "released_source_components.png"
        )
        _write(output / "original_region_masks.json", original_masks)
        _write(output / "source_text_ownership_audit.json", audit)
        result["text_candidate_mask"] = {
            **result.get("text_candidate_mask", {}),
            "path": "compact_glyph_candidate_mask.png",
            "origin_xy_px": roi[:2],
            "size_px": [x1 - x0, y1 - y0],
            "source_erasure_authorized": False,
            "ownership_reconciliation_version": VERSION,
        }
    return result, audit
