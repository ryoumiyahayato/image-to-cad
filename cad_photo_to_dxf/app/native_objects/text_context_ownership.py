"""Source responsibility for a text row next to a through-going graphic.

This stage consumes already verified raw observations. It performs no OCR and
never edits a raw transcription, source pixel, existing word, or adoption bit.
A complete geometric row and two agreeing PP contexts can produce a precise
confirmation candidate. They cannot replace an independent Tesseract witness.
The original failures remain available beside the current missing evidence.
"""

from __future__ import annotations

import copy
import math
from collections import Counter

import numpy as np

from . import cross_engine_text as cross
from . import text_line_domains as domains
from . import text_regions as base


POLICY = {
    "version": "source-row-through-graphic-context-ownership-v1",
    "minimum_full_height_components": 2,
    "graphic_extension_each_side_glyph_heights": 1.0,
    "minimum_source_white_columns": 3,
    "punctuation_max_height_glyph_ratio": 0.35,
    "punctuation_min_aspect_ratio": 3.0,
    "minimum_distinct_model_contexts": 2,
    "raw_observations_must_already_be_bound": True,
    "model_crops_are_same_engine_robustness_not_independent_engines": True,
    "independent_transcription_gate_unchanged": True,
    "automatic_transcription_adoption": False,
    "source_pixels_modified": False,
    "expected_strings_or_case_ids": False,
}


def _component(label, labels, slices, roi):
    sy, sx = slices[label - 1]
    local = labels[sy, sx] == label
    box = [sx.start + roi[0], sy.start + roi[1], sx.stop + roi[0], sy.stop + roi[1]]
    runs = []
    for y in range(local.shape[0]):
        change = np.diff(np.r_[False, local[y], False].astype(np.int8))
        runs.extend(
            [
                [int(y + box[1]), int(a + box[0]), int(b + box[0])]
                for a, b in zip(
                    np.flatnonzero(change == 1), np.flatnonzero(change == -1)
                )
            ]
        )
    return {
        "source_component_label": int(label),
        "bbox_xyxy_px": box,
        "source_area_px": int(local.sum()),
        "source_runs_y_x0_x1": runs,
    }


def _ids_inside(labels, roi, box):
    x0, y0, x1, y1 = map(int, box)
    return set(
        map(
            int, np.unique(labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]])
        )
    ) - {0}


def _strictly_inside(box, outer):
    return (
        outer[0] < box[0] < box[2] < outer[2] and outer[1] < box[1] < box[3] < outer[3]
    )


def _punctuation_shape(component, row_box, glyph_height):
    b = component["bbox_xyxy_px"]
    width, height = b[2] - b[0], b[3] - b[1]
    center_ratio = ((b[1] + b[3]) / 2 - row_box[1]) / glyph_height
    return bool(
        height <= POLICY["punctuation_max_height_glyph_ratio"] * glyph_height
        and width >= POLICY["punctuation_min_aspect_ratio"] * height
        and width <= 1.25 * glyph_height
        and 0.2 <= center_ratio <= 0.8
    )


def _source_partition(region, image, roi, labels, slices, glyphs):
    """Separate source components, never crop through one to force a word."""
    box = region["bbox_xyxy_px"]
    height = box[3] - box[1]
    lo, hi = domains.POLICY["source_component_height_ratio"]
    full = [
        g
        for g in glyphs
        if base._intersection(g["bbox_xyxy_px"], box)
        and lo <= (g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1]) / height <= hi
        and abs(g["bbox_xyxy_px"][3] - box[3])
        <= domains.POLICY["source_row_baseline_glyph_heights"] * height
    ]
    if len(full) < POLICY["minimum_full_height_components"]:
        return None, "INSUFFICIENT_COMPLETE_SOURCE_GLYPH_ROW"
    full.sort(key=lambda g: g["bbox_xyxy_px"][0])
    core = base._box_union([g["bbox_xyxy_px"] for g in full])
    h = float(np.median([g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1] for g in full]))
    # A nearby unassigned glyph is a real possible suffix, not a graphic to trim.
    extended = [core[0] - 1.25 * h, core[1], core[2] + 1.25 * h, core[3]]
    for g in glyphs:
        b = g["bbox_xyxy_px"]
        if g in full or not base._intersection(b, extended):
            continue
        if lo <= (b[3] - b[1]) / h <= hi and abs(b[3] - core[3]) <= 0.35 * h:
            return None, "UNASSIGNED_NEIGHBOR_GLYPH_CAN_BE_A_REAL_SUFFIX_OR_PREFIX"
    components = [_component(g["label"], labels, slices, roi) for g in full]
    if any(not _strictly_inside(c["bbox_xyxy_px"], roi) for c in components):
        return None, "RETAINED_GLYPH_TOUCHES_EFFECTIVE_INPUT_BOUNDARY"
    ids = {c["source_component_label"] for c in components}
    punctuation = []
    for label in sorted(_ids_inside(labels, roi, core) - ids):
        c = _component(label, labels, slices, roi)
        b = c["bbox_xyxy_px"]
        # Interior punctuation has a complete full-height glyph on both sides.
        if (
            base._inside(b, core)
            and _punctuation_shape(c, core, h)
            and any(g["bbox_xyxy_px"][2] <= b[0] for g in full)
            and any(g["bbox_xyxy_px"][0] >= b[2] for g in full)
        ):
            c["source_role"] = "COMPLETE_INTERIOR_HORIZONTAL_PUNCTUATION"
            punctuation.append(c)
            ids.add(label)
        else:
            return None, "UNASSIGNED_OR_THROUGH_COMPONENT_INSIDE_RETAINED_ROW"
    for c in components:
        c["source_role"] = "COMPLETE_FULL_HEIGHT_GLYPH_COMPONENT"
    components += punctuation
    components.sort(key=lambda c: c["bbox_xyxy_px"][0])
    if any(
        a["bbox_xyxy_px"][2] > b["bbox_xyxy_px"][0]
        for a, b in zip(components, components[1:])
    ):
        return None, "NONUNIQUE_HORIZONTAL_SOURCE_COMPONENT_ORDER"
    outside = _ids_inside(labels, roi, box) - ids
    if not outside:
        return None, "NO_SEPARATE_THROUGH_GRAPHIC_AT_ROW_END"
    graphics = []
    for label in sorted(outside):
        c = _component(label, labels, slices, roi)
        # Use the actual ink in the row, not the possibly huge component bbox.
        row_runs = [
            r
            for r in c["source_runs_y_x0_x1"]
            if core[1] <= r[0] < core[3] and max(r[1], box[0]) < min(r[2], box[2])
        ]
        if not row_runs:
            return None, "UNASSIGNED_NONROW_SOURCE_COMPONENT_RETAINED"
        left = min(max(r[1], box[0]) for r in row_runs)
        right = max(min(r[2], box[2]) for r in row_runs)
        if left - core[2] < POLICY["minimum_source_white_columns"]:
            return None, "GRAPHIC_TOUCH_OR_OVERLAP_IS_NOT_A_SEPARATE_TERMINAL_CONTEXT"
        if np.any(
            image[int(core[1]) : int(core[3]), int(core[2]) : int(left)]
            < base.POLICY["source_threshold"]
        ):
            return None, "SOURCE_WHITE_STOP_IS_NOT_COMPLETE"
        extension = int(
            math.ceil(POLICY["graphic_extension_each_side_glyph_heights"] * h)
        )
        top, bottom = int(core[1] - extension), int(core[3] + extension)
        if top <= roi[1] or bottom >= roi[3]:
            return None, "GRAPHIC_CONTINUATION_CANNOT_BE_PROVEN_INSIDE_EFFECTIVE_INPUT"
        # Same original connected component must occupy every source row above,
        # through and below the glyph row in its local context corridor.
        strip = (
            labels[
                top - roi[1] : bottom - roi[1], int(left) - roi[0] : int(right) - roi[0]
            ]
            == label
        )
        continuous = strip.any(axis=1)
        if not continuous.all():
            return None, "NEIGHBOR_ONLY_TOUCHES_ROW_OR_LACKS_TWO_SIDED_CONTINUATION"
        all_runs = c.pop("source_runs_y_x0_x1")
        c["whole_connected_component_runs_digest"] = cross._digest(all_runs)
        c["source_runs_y_x0_x1"] = [
            [y, max(a, int(left)), min(b, int(right))]
            for y, a, b in all_runs
            if top <= y < bottom and max(a, left) < min(b, right)
        ]
        c["source_run_scope"] = (
            "local_continuation_proof_corridor_full_component_bbox_and_digest_retained"
        )
        c.update(
            source_role="SEPARATE_GRAPHIC_CONTINUES_ABOVE_AND_BELOW_COMPLETE_ROW",
            local_row_ink_bbox_xyxy_px=[left, core[1], right, core[3]],
            source_white_stop_xyxy_px=[core[2], core[1], left, core[3]],
            continuous_source_row_span_xyxy_px=[left, top, right, bottom],
            source_rows_above_glyphs=extension,
            source_rows_below_glyphs=extension,
        )
        graphics.append(c)
    graphics.sort(key=lambda c: c["local_row_ink_bbox_xyxy_px"][0])
    return {
        "retained_source_box_xyxy_px": core,
        "median_glyph_height_px": h,
        "ordered_retained_components": components,
        "separate_terminal_graphics": graphics,
        "all_source_ink_in_retained_domain_assigned": True,
        "original_source_components_cut": False,
    }, None


def _bind_model_prefix(record, partition, image):
    context = record["context"]["crop_xyxy_px"]
    x0, y0, x1, y1 = context
    raw = record["raw_model_output"]
    crop_hash = base.source_array_sha256(image[y0:y1, x0:x1])
    if crop_hash != record.get("source_array_sha256") or crop_hash != raw.get(
        "input_array_sha256"
    ):
        raise ValueError("TEXT_CONTEXT_BOUND_MODEL_SOURCE_HASH_MISMATCH")
    if (
        record.get("source_pixels_modified")
        or raw.get("source_geometry_modified")
        or raw.get("raw_transcription_rewritten")
    ):
        raise ValueError("TEXT_CONTEXT_RAW_SOURCE_OR_TRANSCRIPTION_MODIFIED")
    tokens = raw.get("raw_CTC_tokens", [])
    if not tokens or "".join(t["character"] for t in tokens) != raw.get("raw_text"):
        return None, "RAW_CTC_TOKENS_DO_NOT_EQUAL_SAVED_RAW_TEXT"
    if any(a["time_step"] >= b["time_step"] for a, b in zip(tokens, tokens[1:])):
        return None, "CTC_ORDER_NOT_STRICTLY_INCREASING"
    retained = partition["ordered_retained_components"]
    if any(not _strictly_inside(c["bbox_xyxy_px"], context) for c in retained):
        return None, "TRUE_RETAINED_GLYPH_TRUNCATION_IN_RECOGNITION_CONTEXT"
    nonspace = [(i, t) for i, t in enumerate(tokens) if not t["character"].isspace()]
    if len(nonspace) != len(retained) + len(partition["separate_terminal_graphics"]):
        return None, "SOURCE_COMPONENT_AND_CTC_ORDER_NOT_ONE_TO_ONE"
    bindings = []
    for c, (index, token) in zip(retained, nonspace):
        if len(token["character"]) != 1:
            return None, "MULTICHARACTER_CTC_TOKEN_HAS_NO_UNIQUE_COMPONENT_BINDING"
        if (
            c["source_role"] == "COMPLETE_INTERIOR_HORIZONTAL_PUNCTUATION"
            and token["character"] not in "-−–—"
        ):
            return None, "HORIZONTAL_PUNCTUATION_SOURCE_AND_CTC_TOKEN_DISAGREE"
        score = token.get("score")
        if (
            score is None
            or not math.isfinite(score)
            or score < cross.POLICY["model_emitted_character_confidence_minimum"]
        ):
            return None, "RETAINED_CHARACTER_BELOW_UNCHANGED_MODEL_GATE"
        bindings.append(
            {
                "source_component_label": c["source_component_label"],
                "source_bbox_xyxy_px": c["bbox_xyxy_px"],
                "raw_token_index": index,
                "raw_CTC_token": copy.deepcopy(token),
                "binding": "ordered_nonoverlapping_source_components_and_raw_CTC_tokens_candidate_only",
            }
        )
    kept_last = nonspace[len(retained) - 1][0]
    kept_tokens = tokens[: kept_last + 1]
    scores = [t["score"] for t in kept_tokens if not t["character"].isspace()]
    if sum(scores) / len(scores) < cross.POLICY["model_mean_confidence_minimum"]:
        return None, "RETAINED_PREFIX_BELOW_UNCHANGED_MODEL_MEAN_GATE"
    return {
        "observation_key": record["observation_key"],
        "context_xyxy_px": context,
        "source_crop_array_sha256": crop_hash,
        "model_identity_sha256": record.get("model_identity_sha256"),
        "original_raw_text": raw["raw_text"],
        "original_raw_CTC_tokens": copy.deepcopy(tokens),
        "candidate_text": "".join(t["character"] for t in kept_tokens),
        "retained_token_source_bindings": bindings,
        "graphic_context_tokens_retained_in_original_observation": copy.deepcopy(
            tokens[kept_last + 1 :]
        ),
        "prefix_mean_model_score": sum(scores) / len(scores),
        "prefix_minimum_model_score": min(scores),
        "raw_model_record_digest": cross._digest(record),
        "raw_transcription_rewritten": False,
    }, None


def _independent_witnesses(text, box, tesseract_rows):
    witnesses = []
    for row in tesseract_rows:
        words = [w for w in row["words"] if base._inside(w["bbox_xyxy_px"], box)]
        if (
            not words
            or " ".join(w["text"] for w in words) != text
            or not cross._confident(words)
        ):
            continue
        if base._box_union([w["bbox_xyxy_px"] for w in words]) != box:
            continue
        witnesses.append(
            {
                "observation_key": row["observation_key"],
                "source_raw_text": " ".join(w["text"] for w in words),
                "words": copy.deepcopy(words),
                "raw_original_bytes_already_verified": True,
            }
        )
    return witnesses


def derive_context_ownership(
    image, text_data, model_records, tesseract_rows, *, labels, slices, glyphs
):
    """Add review evidence only; both iterable inputs must come from BoundObservations.

    Confidence gates, raw words, accepted/complete bits and masks are immutable.
    Keeping the mask immutable also prevents withdrawing a punctuation LINE
    before a formal replacement TEXT has independently passed adoption.
    """
    source_hash = base.source_array_sha256(image)
    if source_hash != text_data["source_array_sha256"]:
        raise ValueError("TEXT_CONTEXT_SOURCE_ARRAY_BINDING_MISMATCH")
    result = copy.deepcopy(text_data)
    models, tess = list(model_records), list(tesseract_rows)
    events = []
    for region in result["regions"]:
        if region["complete"]:
            continue
        candidates = [
            m
            for m in models
            if m.get("region_id") == region["id"]
            or base._overlap(m["context"]["crop_xyxy_px"], region["bbox_xyxy_px"])
            >= 0.65
        ]
        if not candidates:
            continue
        partition, reason = _source_partition(
            region, image, result["roi_xyxy_px"], labels, slices, glyphs
        )
        event = {
            "region_id": region["id"],
            "prior_region_digest": cross._digest(region),
            "source_partition": partition,
            "blocked_reasons": [],
            "model_prefix_observations": [],
            "candidate_text": None,
            "automatic_content_adoption": False,
        }
        if reason:
            event["blocked_reasons"].append(reason)
        else:
            seen = set()
            for record in candidates:
                identity = (
                    tuple(record["context"]["crop_xyxy_px"]),
                    record["source_array_sha256"],
                )
                if identity in seen:
                    continue
                seen.add(identity)
                bound, failed = _bind_model_prefix(record, partition, image)
                if failed:
                    event["blocked_reasons"].append(failed)
                else:
                    event["model_prefix_observations"].append(bound)
            observations = event["model_prefix_observations"]
            if len(observations) < POLICY["minimum_distinct_model_contexts"]:
                event["blocked_reasons"].append(
                    "MISSING_TWO_DISTINCT_COMPLETE_SOURCE_CONTEXT_BINDINGS"
                )
            elif len({r["candidate_text"] for r in observations}) != 1:
                event["blocked_reasons"].append(
                    "SIMILAR_CHARACTER_OR_TRANSCRIPTION_CONFLICT_RETAINED"
                )
            elif not event["blocked_reasons"]:
                event["candidate_text"] = observations[0]["candidate_text"]
                witnesses = _independent_witnesses(
                    event["candidate_text"],
                    partition["retained_source_box_xyxy_px"],
                    tess,
                )
                event["independent_Tesseract_witnesses"] = witnesses
                event["independent_engine_family_count"] = 2 if witnesses else 1
                event["same_model_crop_count_is_not_engine_count"] = len(observations)
                event["current_missing_evidence"] = (
                    []
                    if witnesses
                    else [
                        "INDEPENDENT_WHOLE_ROW_TRANSCRIPTION_AT_UNCHANGED_TESSERACT_GATE"
                    ]
                )
                event["current_confirmation_scope"] = (
                    "COMPLETE_SOURCE_ROW_SUPPORTED_CANDIDATE_SEPARATE_GRAPHIC_CONTEXT_RETAINED"
                )
                event["prior_unresolved_reason_snapshot"] = list(
                    region["unresolved_reasons"]
                )
                event["raw_word_mask_and_formal_status_changed"] = False
                region["source_context_ownership"] = copy.deepcopy(event)
        event["blocked_reasons"] = sorted(set(event["blocked_reasons"]))
        events.append(event)
    audit = {
        "policy": POLICY,
        "source_array_sha256": source_hash,
        "producer_sha256": base._sha(__file__),
        "events": events,
        "source_supported_confirmation_candidates": sum(
            bool(e["candidate_text"]) for e in events
        ),
        "OCR_calls": 0,
        "model_calls": 0,
        "source_pixels_deleted": 0,
        "raw_observations_changed": False,
        "words_masks_completeness_adoption_unchanged": True,
        "blocked_reason_counts": dict(
            Counter(r for e in events for r in e["blocked_reasons"])
        ),
    }
    return result, audit


def attach_confirmation_context(confirmation, text_data):
    """Distinguish current missing proof from retained historical OCR failures."""
    by_id = {r["id"]: r for r in text_data["regions"]}
    for row in confirmation["pending_regions"]:
        context = by_id[row["region_id"]].get("source_context_ownership")
        if context:
            row["current_source_supported_confirmation"] = copy.deepcopy(context)
            row["historical_unresolved_reasons_retained_separately"] = True
    return confirmation
