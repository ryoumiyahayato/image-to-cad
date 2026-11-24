"""Separate compact candidate ink from evidenced character ownership.

A low OCR confidence alone never releases source ink. Only an entire isolated
component already proposed by the source-geometry component path is eligible.
Its original pixels must still pass the same line-shape/source gates, it must
have no reliable current word support, and it must fail every applicable text
row layout while having no neighboring source-glyph row witness. All old masks
and every decision remain evidence; this does not erase or relabel the raster.

Conversely, a completed single-line transcription can establish responsibility
for a dense I that the compact-ink heuristic omitted. This requires an exact
ordered source-component/character correspondence, already owned neighboring
glyphs, and a whole unbranched source component matching a cached line proposal.
The adapter adds only that component's original ink, never a rectangular mask.
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

VERSION = "isolated_source_component_text_ownership_v4_verified_complete_rows"


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


def _candidate_component_labels(candidates, labels, roi):
    by_label = {}
    for candidate in candidates:
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
        by_label.setdefault(label, []).append(candidate)
    return by_label


def _component_is_owned(points, runs):
    by_row = {}
    for y, lo, hi in runs:
        by_row.setdefault(y, []).append((lo, hi))
    for y in np.unique(points[:, 1]):
        xx = points[points[:, 1] == y, 0]
        owned = np.zeros(len(xx), dtype=bool)
        for lo, hi in by_row.get(int(y), []):
            owned |= (xx >= lo) & (xx < hi)
        if not np.all(owned):
            return False
    return True


def _merge_runs(runs):
    """Union original pixel intervals; do not bridge a source-white gap."""
    merged = []
    for y, lo, hi in sorted(runs):
        if merged and merged[-1][0] == y and lo <= merged[-1][2]:
            merged[-1][2] = max(merged[-1][2], hi)
        else:
            merged.append([int(y), int(lo), int(hi)])
    return merged


def _word_component_witnesses(region, ordered, image, labels, stats, roi):
    """Do not borrow a word-gap stroke to compensate for a merged glyph.

    A selected OCR word box may overlap the next word. Reuse independently
    source-bound raw observations with exact full strings and unambiguous word
    boxes; one broad box or two aliases of the same input cannot establish this.
    """
    accepted_words = region["words"]
    witnesses = {}
    for observation in region.get("completeness_evidence", {}).get("alternatives", []):
        words = observation.get("words", [])
        key = observation.get("observation_key")
        provenance = observation.get("observation_provenance", {})
        spec = provenance.get("specification", {})
        crop = spec.get("crop_xyxy_px", [])
        if (
            observation.get("status") != "COMPLETED"
            or not key
            or [w.get("text") for w in words] != [w["text"] for w in accepted_words]
            or spec.get("source_pixels_modified") is not False
            or len(crop) != 4
            or not all(isinstance(v, int) for v in crop)
            or not (
                roi[0] <= crop[0] < crop[2] <= roi[2]
                and roi[1] <= crop[1] < crop[3] <= roi[3]
            )
            or spec.get("crop_array_sha256")
            != source_array_sha256(image[crop[1] : crop[3], crop[0] : crop[2]])
            or not provenance.get("raw_tsv_sha256")
            or not provenance.get("engine_identity")
            or not all(
                crop[0] <= c["bbox_xyxy_px"][0] < c["bbox_xyxy_px"][2] <= crop[2]
                and crop[1] <= c["bbox_xyxy_px"][1] < c["bbox_xyxy_px"][3] <= crop[3]
                for c in ordered
            )
        ):
            continue
        word_proofs = []
        offset = 0
        for accepted, word in zip(accepted_words, words):
            required = max(
                float(accepted.get("required_confidence", 0)),
                TEXT_POLICY[
                    "minimum_numeric_word_confidence"
                    if word["text"].isdigit()
                    else "minimum_word_confidence"
                ],
            )
            b = word.get("bbox_xyxy_px", [])
            if (
                key not in accepted.get("independent_agreement_observation_keys", [])
                or word.get("raw_text_unchanged") is not True
                or float(word.get("confidence", -1)) < required
                or len(b) != 4
            ):
                break
            assigned = ordered[offset : offset + len(word["text"])]
            offset += len(word["text"])
            domain = [b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2]
            touched = sorted(
                (
                    int(lab)
                    for lab in np.unique(
                        labels[
                            max(0, int(np.floor(domain[1])) - roi[1]) : min(
                                labels.shape[0], int(np.ceil(domain[3])) - roi[1]
                            ),
                            max(0, int(np.floor(domain[0])) - roi[0]) : min(
                                labels.shape[1], int(np.ceil(domain[2])) - roi[0]
                            ),
                        ]
                    )
                    if lab
                ),
                key=lambda lab: (stats[lab, 0], stats[lab, 1]),
            )
            assigned_ids = [c["source_component_label"] for c in assigned]
            complete = all(
                domain[0] <= c["bbox_xyxy_px"][0] < c["bbox_xyxy_px"][2] <= domain[2]
                and domain[1]
                <= c["bbox_xyxy_px"][1]
                < c["bbox_xyxy_px"][3]
                <= domain[3]
                for c in assigned
            )
            if (
                len(assigned) != len(word["text"])
                or touched != assigned_ids
                or not complete
            ):
                break
            word_proofs.append(
                {
                    "text": word["text"],
                    "raw_bbox_xyxy_px": b,
                    "source_component_labels_in_literal_order": assigned_ids,
                    "all_and_only_whole_word_components_supported": True,
                }
            )
        if len(word_proofs) != len(accepted_words) or offset != len(ordered):
            continue
        identity = _digest(
            {"specification": spec, "engine_identity": provenance["engine_identity"]}
        )
        witnesses.setdefault(
            identity,
            {
                "observation_key": key,
                "source_configuration_identity": identity,
                "source_crop_xyxy_px": crop,
                "source_crop_array_sha256": spec["crop_array_sha256"],
                "raw_tsv_sha256": provenance["raw_tsv_sha256"],
                "words": word_proofs,
            },
        )
    return list(witnesses.values())


def _complete_line_glyph_ownership(texts, image, roi, labels, stats, candidates):
    """Prove missing dense-I responsibility from confirmed text and raw ink.

    This is not recognition or adoption. Unsupported component splits, extra
    strokes, overlapping characters, and multi-component punctuation remain
    unchanged. Word boxes only locate the already completed line: every whole
    source component, including punctuation, must fit its literal character
    position, so a rectangle cannot consume an unrelated line or short stroke.
    """
    regions = {r["id"]: r for r in texts["regions"]}
    additions, events = {}, []
    for group in texts.get("groups", []):
        ids = group.get("region_ids", [])
        if (
            group.get("geometry_type") != "TEXT"
            or group.get("kind") != "single_line"
            or not group.get("complete")
            or len(ids) != 1
            or ids[0] not in regions
        ):
            continue
        region = regions[ids[0]]
        text = region.get("text", "")
        words = region.get("words", [])
        if (
            not region.get("complete")
            or region.get("unresolved_reasons")
            or group.get("text") != text
            or "I" not in text
            or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -,." for c in text)
            or not words
            or " ".join(w.get("text", "") for w in words) != text
        ):
            continue
        word_checks = []
        for word in words:
            minimum = TEXT_POLICY[
                "minimum_numeric_word_confidence"
                if str(word.get("text", "")).isdigit()
                else "minimum_word_confidence"
            ]
            required = max(minimum, float(word.get("required_confidence", minimum)))
            contexts = sorted(
                set(word.get("independent_agreement_observation_keys", []))
            )
            word_checks.append(
                {
                    "word_id": word.get("id"),
                    "text": word.get("text"),
                    "required_confidence": required,
                    "confidence": word.get("confidence"),
                    "independent_observation_keys": contexts,
                    "pass": word.get("agreement_pass") is True
                    and float(word.get("confidence", -1)) >= required
                    and len(contexts) >= ROW_POLICY["minimum_repeated_contexts"],
                }
            )
        if not all(w["pass"] for w in word_checks):
            continue
        box = region["bbox_xyxy_px"]
        # The existing two-pixel localization tolerance allows the whole comma
        # descender to be read, rather than trimming it at a chosen OCR word box.
        domain = [
            max(roi[0], int(np.floor(box[0])) - 2),
            max(roi[1], int(np.floor(box[1])) - 2),
            min(roi[2], int(np.ceil(box[2])) + 2),
            min(roi[3], int(np.ceil(box[3])) + 2),
        ]
        source_labels = np.unique(
            labels[
                domain[1] - roi[1] : domain[3] - roi[1],
                domain[0] - roi[0] : domain[2] - roi[0],
            ]
        )
        ordered = []
        for label in source_labels:
            if not label:
                continue
            x, y, width, height, area = map(int, stats[label])
            b = [x + roi[0], y + roi[1], x + roi[0] + width, y + roi[1] + height]
            ordered.append(
                {
                    "source_component_label": int(label),
                    "bbox_xyxy_px": b,
                    "source_area_px": area,
                }
            )
        ordered.sort(key=lambda c: (c["bbox_xyxy_px"][0], c["bbox_xyxy_px"][1]))
        characters = [(i, c) for i, c in enumerate(text) if c != " "]
        checks = {
            "complete_source_components_match_full_literal_character_count": len(
                ordered
            )
            == len(characters),
            "whole_source_components_within_line_localization": all(
                domain[0] <= c["bbox_xyxy_px"][0] < c["bbox_xyxy_px"][2] <= domain[2]
                and domain[1]
                <= c["bbox_xyxy_px"][1]
                < c["bbox_xyxy_px"][3]
                <= domain[3]
                for c in ordered
            ),
            "source_components_have_unambiguous_left_to_right_order": all(
                a["bbox_xyxy_px"][2] < b["bbox_xyxy_px"][0]
                for a, b in zip(ordered, ordered[1:])
            ),
        }
        event = {
            "region_id": region["id"],
            "group_id": group["id"],
            "text": text,
            "word_evidence": word_checks,
            "ordered_source_components": ordered,
            "checks": checks,
            "added_components": [],
            "decision": "KEEP_EXISTING_OWNERSHIP_WITHOUT_COMPLETE_GLYPH_PROOF",
        }
        events.append(event)
        if not all(checks.values()):
            continue
        word_witnesses = _word_component_witnesses(
            region, ordered, image, labels, stats, roi
        )
        event["independent_word_source_component_witnesses"] = word_witnesses
        checks["each_literal_word_has_independent_complete_component_order"] = (
            len(word_witnesses) >= ROW_POLICY["minimum_repeated_contexts"]
        )
        if not checks["each_literal_word_has_independent_complete_component_order"]:
            continue
        runs = region.get("compact_source_ink_mask", {}).get("runs_y_x0_x1", [])
        for (index, character), component in zip(characters, ordered):
            component.update(character_index=index, character=character)
            points = _component_points(
                labels, stats, component["source_component_label"], roi
            )
            component["whole_component_already_in_text_mask"] = _component_is_owned(
                points, runs
            )
        anchors = [
            c for c in ordered if c["character"].isalnum() and c["character"] != "I"
        ]
        checks["at_least_two_preexisting_complete_glyph_anchors"] = len(
            anchors
        ) >= 2 and all(c["whole_component_already_in_text_mask"] for c in anchors)
        if not checks["at_least_two_preexisting_complete_glyph_anchors"]:
            continue
        top = float(np.median([c["bbox_xyxy_px"][1] for c in anchors]))
        baseline = float(np.median([c["bbox_xyxy_px"][3] for c in anchors]))
        height = baseline - top
        checks["glyph_anchors_share_full_height_and_baseline"] = height >= 12 and all(
            abs(c["bbox_xyxy_px"][1] - top) <= 2
            and abs(c["bbox_xyxy_px"][3] - baseline) <= 2
            for c in anchors
        )
        for component in ordered:
            if component["character"] != "I":
                continue
            x0, y0, x1, y1 = component["bbox_xyxy_px"]
            local = (
                labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]]
                == component["source_component_label"]
            )
            component["full_height_vertical_stem_source"] = (
                abs(y0 - top) <= 2
                and abs(y1 - baseline) <= 2
                and x1 - x0 <= max(5, 0.65 * height)
                and bool(np.any(np.all(local, axis=0)))
            )
        checks["every_literal_I_has_full_height_source_including_preowned_I"] = all(
            c["full_height_vertical_stem_source"]
            for c in ordered
            if c["character"] == "I"
        )
        punctuation_checks = []
        for component in ordered:
            c = component["character"]
            if c.isalnum():
                continue
            x0, y0, x1, y1 = component["bbox_xyxy_px"]
            width, ph = x1 - x0, y1 - y0
            if c == "-":
                valid = (
                    width >= 2 * ph
                    and ph <= 0.3 * height
                    and top + 0.25 * height <= (y0 + y1) / 2 <= baseline - 0.15 * height
                )
            elif c == ",":
                valid = (
                    width <= 0.35 * height
                    and ph <= 0.5 * height
                    and y0 >= top + 0.6 * height
                    and baseline <= y1 <= baseline + 0.5 * height
                )
            else:
                valid = (
                    width <= 0.35 * height
                    and ph <= 0.3 * height
                    and abs(y1 - baseline) <= 2
                )
            punctuation_checks.append(bool(valid))
            component["source_punctuation_position_and_shape_match"] = bool(valid)
        checks["all_literal_punctuation_has_separate_source_shape"] = all(
            punctuation_checks
        )
        checks["adjacent_source_components_share_one_line"] = all(
            0
            < b["bbox_xyxy_px"][0] - a["bbox_xyxy_px"][2]
            <= ROW_POLICY["source_row_join_gap_glyph_heights"] * height
            for a, b in zip(ordered, ordered[1:])
        )
        if not all(checks.values()):
            continue
        additions_for_line = []
        for component in ordered:
            if (
                component["character"] != "I"
                or component["whole_component_already_in_text_mask"]
            ):
                continue
            label = component["source_component_label"]
            x0, y0, x1, y1 = component["bbox_xyxy_px"]
            local = (
                labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]] == label
            )
            core = local & (image[y0:y1, x0:x1] < 128)
            yy, xx = np.nonzero(core)
            if not len(xx):
                continue
            core_box = [
                int(xx.min() + x0),
                int(yy.min() + y0),
                int(xx.max() + x0 + 1),
                int(yy.max() + y0 + 1),
            ]
            core_points = np.column_stack((xx + x0, yy + y0)).astype(float)
            component_checks = {
                "complete_source_component_is_solid_narrow_vertical_stroke": bool(
                    np.all(local)
                )
                and 1 <= x1 - x0 <= 5
                and (y1 - y0) / (x1 - x0) >= 5,
                "no_source_extension_beyond_confirmed_glyph_row": abs(y0 - top) <= 2
                and abs(y1 - baseline) <= 2,
                "unique_solid_geometry_core_preserves_complete_source_height": len(xx)
                == (core_box[2] - core_box[0]) * (core_box[3] - core_box[1])
                and core_box[1] == y0
                and core_box[3] == y1,
            }
            evidence = [
                _source_line_evidence(c, core_points, core_box, roi)
                for c in candidates.get(label, [])
            ]
            component_checks["unchanged_cached_complete_source_line_matches_core"] = (
                any(e["qualified"] for e in evidence)
            )
            component["dense_stroke_checks"] = component_checks
            if not all(component_checks.values()):
                continue
            additions_for_line.append(
                {
                    **copy.deepcopy(component),
                    "checks": component_checks,
                    "cached_source_candidate_ids": [
                        c["id"]
                        for c, e in zip(candidates[label], evidence)
                        if e["qualified"]
                    ],
                    "cached_source_line_evidence": evidence,
                    "source_component_runs_y_x0_x1": _rle(local, [x0, y0]),
                    "geometry_core_runs_y_x0_x1": _rle(core, [x0, y0]),
                    "source_gray_fringe_preserved": True,
                    "source_pixels_modified": False,
                }
            )
        checks["all_missing_I_components_have_complete_source_proof"] = len(
            additions_for_line
        ) == sum(
            c["character"] == "I" and not c["whole_component_already_in_text_mask"]
            for c in ordered
        )
        if (
            additions_for_line
            and checks["all_missing_I_components_have_complete_source_proof"]
        ):
            additions.setdefault(region["id"], []).extend(additions_for_line)
            event["added_components"] = additions_for_line
            event["decision"] = "ADD_COMPLETE_SOURCE_GLYPH_OWNERSHIP"
    return additions, events


def _verified_complete_row_components(texts, image, roi, labels, stats, evidence_root):
    """Preserve proved whole glyph/mark components when a raw word score is low.

    A rectangle or a successful sidecar flag cannot establish this ownership.
    Replay the complete saved row, then match each component to its entire
    original ink. Shared contact/graphic ink never grants exclusive ownership.
    """
    from . import single_line_labels

    witnesses, replays = {}, []
    for region in texts["regions"]:
        proof = region.get("single_line_recovery")
        if not proof or not region.get("complete"):
            continue
        if evidence_root is None:
            replays.append({"region_id": region["id"], "pass": False,
                            "reason": "COMPLETE_ROW_EVIDENCE_ROOT_MISSING"})
            continue
        check = single_line_labels.verify_single_line_label_evidence(
            image, roi, proof, evidence_root
        )
        bound = (
            check.get("pass") is True
            and check.get("text") == region.get("text")
            and check.get("bbox_xyxy_px") == region.get("bbox_xyxy_px")
        )
        replays.append({"region_id": region["id"], "pass": bound,
                        "source_replay": check})
        if not bound:
            continue
        partition = proof["source_partition"]
        separation = partition.get("text_contact_separation", {})
        graphic_runs = [
            *partition.get("recognition_excluded_graphic_runs_y_x0_x1", []),
            *separation.get("recognition_excluded_source_runs", []),
        ]
        shared_runs = separation.get("shared_original_contact_runs", [])
        for index, component in enumerate(partition["components"]):
            runs = component["source_runs_y_x0_x1"]
            if not runs:
                continue
            ys = np.array([y for y, x0, x1 in runs for _ in range(x0, x1)], dtype=int)
            xs = np.array([x for _, x0, x1 in runs for x in range(x0, x1)], dtype=int)
            source_labels = np.unique(labels[ys - roi[1], xs - roi[0]])
            if len(source_labels) != 1 or not source_labels[0]:
                continue
            label = int(source_labels[0])
            x, y, width, height, area = map(int, stats[label])
            actual_runs = _rle(labels[y:y+height, x:x+width] == label,
                               [x + roi[0], y + roi[1]])
            if actual_runs != runs or len(xs) != area:
                continue
            if any(np.any((ys == gy) & (xs >= lo) & (xs < hi))
                   for gy, lo, hi in [*graphic_runs, *shared_runs]):
                continue
            witnesses.setdefault(label, []).append({
                "region_id": region["id"], "component_index": index,
                "source_role": component["source_role"],
                "whole_original_component_runs_y_x0_x1": actual_runs,
                "source_partition_sha256": _digest(partition),
                "complete_row_source_and_raw_recognition_replayed": True,
                "independent_graphic_or_shared_contact_pixels_claimed": False,
            })
    return witnesses, replays


def reconcile_source_text_ownership(
    text_data, image, roi, geometry_candidates, output_dir=None, *, evidence_root=None
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
    all_candidates_by_label = _candidate_component_labels(
        source_geometry_rows, labels, roi
    )
    candidates_by_label = {
        label: [c for c in candidates if c.get("decision") == "DEFER_TEXT_OWNERSHIP"]
        for label, candidates in all_candidates_by_label.items()
    }
    candidates_by_label = {label: cs for label, cs in candidates_by_label.items() if cs}
    events, released = [], set()
    original_masks = {
        r["id"]: copy.deepcopy(r.get("compact_source_ink_mask", {}))
        for r in result["regions"]
    }
    glyph_additions, glyph_events = _complete_line_glyph_ownership(
        result, image, roi, labels, stats, all_candidates_by_label
    )
    complete_row_witnesses, complete_row_replays = _verified_complete_row_components(
        result, image, roi, labels, stats, evidence_root
    )
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
            "no_verified_complete_row_component_ownership": not complete_row_witnesses.get(label),
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
                "verified_complete_row_component_witnesses": complete_row_witnesses.get(label, []),
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
    added_labels = {
        c["source_component_label"] for cs in glyph_additions.values() for c in cs
    }
    if added_labels & released:
        raise RuntimeError("SOURCE_TEXT_OWNERSHIP_CONFLICTING_COMPONENT_RESPONSIBILITY")
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
        additions = glyph_additions.get(region["id"], [])
        added_runs = [
            run for c in additions for run in c["source_component_runs_y_x0_x1"]
        ]
        before_added = sum(hi - lo for _, lo, hi in kept)
        kept = _merge_runs(kept + added_runs)
        added = sum(hi - lo for _, lo, hi in kept) - before_added
        if removed or added:
            region.setdefault("source_text_ownership_prior_compact_mask", prior)
            region["compact_source_ink_mask"] = {
                **prior,
                "runs_y_x0_x1": kept,
                "component_labels": sorted(
                    {
                        lab
                        for lab in prior.get("component_labels", [])
                        if lab not in released
                    }
                    | {c["source_component_label"] for c in additions}
                ),
                "source_erasure_authorized": False,
                "ownership_reconciliation_version": VERSION,
            }
            mask_changes.append(
                {
                    "region_id": region["id"],
                    "removed_from_text_candidate_mask_pixels": removed,
                    "added_complete_glyph_source_pixels": added,
                    "added_complete_glyph_source_component_labels": [
                        c["source_component_label"] for c in additions
                    ],
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
        "complete_line_glyph_events": glyph_events,
        "complete_row_source_replays": complete_row_replays,
        "mask_changes": mask_changes,
        "released_component_labels": sorted(released),
        "released_unique_source_pixels": sum(
            int(stats[label, 4]) for label in released
        ),
        "added_complete_glyph_component_labels": sorted(added_labels),
        "added_unique_complete_glyph_source_pixels": sum(
            int(stats[label, 4]) for label in added_labels
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
