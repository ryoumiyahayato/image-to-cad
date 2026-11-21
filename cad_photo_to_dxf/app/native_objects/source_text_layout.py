"""Derive source-supported TEXT placement without changing recognition.

Input must be the task's verified immutable text contract. Raw OCR integrity
belongs to the upstream recognition producer; this module rechecks its crop
bytes/configuration identities and uses only its clean full-line witnesses.
It never changes transcription, completeness, raw word boxes or source masks.
No source-specific coordinates, expected text, model or file path is used.
"""

from __future__ import annotations
from collections import defaultdict
import copy
import hashlib
import json
import numpy as np

from . import text_regions as base


POLICY = {
    "version": "verified-clean-context-exact-ink-layout-v1",
    "minimum_distinct_clean_contexts": 2,
    "bbox_consensus": "exact_original_integer_word_union",
    "source_gate": "all_ink_in_current_word_union_has_exact_proposed_tight_bbox",
    "confidence_source_or_boundary_tolerance_changed": False,
    "OCR_or_acceptance_decision_changed": False,
}


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


def choose_source_text_layout(region, image, *, roi_xyxy_px=None):
    """Return a separate layout recommendation; never mutate region or image.

    Without a unique, independently witnessed bbox and exact original-pixel
    support, return the existing placement with an explicit unresolved status.
    Measured enclosed labels stay with their existing annotation/frame path.
    """
    current = list(region["bbox_xyxy_px"])
    result = {
        "bbox_xyxy_px": current,
        "changed": False,
        "status": "LAYOUT_UNCHANGED_UNPROVEN",
        "policy": POLICY,
        "recognition_region_sha256": _digest(region),
        "recognition_text": region.get("text"),
        "recognition_complete": region.get("complete"),
        "recognition_bbox_xyxy_px_preserved": current,
        "transcription_complete_words_and_source_mask_modified": False,
        "source_pixels_modified": False,
        "observations": [],
    }
    if not region.get("complete") or not region.get("words"):
        result["status"] = "LAYOUT_INCOMPLETE_RECOGNITION_PRESERVED"
        return result
    if region.get("enclosure"):
        result["status"] = "LAYOUT_MEASURED_ENCLOSED_LABEL_PRESERVED"
        return result
    image = np.asarray(image)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise TypeError("TEXT_LAYOUT_REQUIRES_ORIGINAL_UINT8_GRAY")
    source_bounds = [0, 0, image.shape[1], image.shape[0]]
    roi = list(roi_xyxy_px) if roi_xyxy_px is not None else source_bounds
    result["effective_roi_xyxy_px"] = roi
    if any(int(value) != value for value in current):
        result["status"] = "LAYOUT_NONINTEGER_ORIGINAL_REGION_COORDINATES_PRESERVED"
        return result
    current = list(map(int, current))
    if not base._inside(current, source_bounds) or not base._inside(current, roi):
        result["status"] = "LAYOUT_RECOGNITION_BBOX_CROSSES_EFFECTIVE_INPUT"
        return result
    boundary = region.get("completeness_evidence", {}).get(
        "current_boundary_assessment", {}
    )
    if boundary.get("actual_source_component_contacts_effective_input") or boundary.get(
        "chosen_word_indices_without_source_ink"
    ):
        result["status"] = "LAYOUT_REAL_SOURCE_BOUNDARY_OR_MISSING_INK_VETO"
        return result
    clean_records = {
        r["observation_key"]: r
        for r in boundary.get("observations", [])
        if r.get("clean_current_full_line_witness")
    }
    modes, seen = defaultdict(list), set()
    for alternative in region.get("completeness_evidence", {}).get("alternatives", []):
        provenance = alternative.get("observation_provenance") or {}
        if not provenance and alternative.get("words"):
            provenance = alternative["words"][0].get("observation_provenance", {})
        spec = provenance.get("specification")
        record = {"context_id": alternative.get("context_id"), "eligible": False}
        result["observations"].append(record)
        if not spec:
            record["reason"] = "MISSING_ORIGINAL_CROP_CONFIGURATION"
            continue
        key = base._observation_context_key(spec)
        record["observation_key"] = key
        if key in seen:
            record["reason"] = "DUPLICATE_SOURCE_AND_CONFIGURATION_NO_EXTRA_VOTE"
            continue
        seen.add(key)
        if (
            alternative.get("observation_key") not in (None, key)
            or key not in clean_records
        ):
            record["reason"] = "NOT_A_VERIFIED_CLEAN_CURRENT_WHOLE_LINE_WITNESS"
            continue
        words = alternative.get("words", [])
        text = " ".join(w["text"] for w in words)
        crop = list(spec["crop_xyxy_px"])
        raw_hash = provenance.get("raw_tsv_sha256")
        artifact_hash = alternative.get("raw_artifact", {}).get("sha256", raw_hash)
        if (
            alternative.get("status") != "COMPLETED"
            or text != region["text"]
            or not raw_hash
            or raw_hash != artifact_hash
            or spec.get("pixel_scale") != [1, 1]
            or spec.get("source_pixels_modified")
            or spec.get("padding_replaces_source_pixels")
            or not base._inside(crop, source_bounds)
        ):
            record["reason"] = "CURRENT_RAW_TEXT_SOURCE_OR_CONFIGURATION_BINDING_FAILED"
            continue
        x0, y0, x1, y1 = crop
        if base.source_array_sha256(image[y0:y1, x0:x1]) != spec["crop_array_sha256"]:
            record["reason"] = "ORIGINAL_SOURCE_CROP_BYTES_CHANGED"
            continue
        box = base._box_union([w["bbox_xyxy_px"] for w in words])
        confident = all(
            w["confidence"]
            >= (
                base.POLICY["minimum_numeric_word_confidence"]
                if w["text"].isdigit()
                else base.POLICY["minimum_word_confidence"]
            )
            for w in words
        )
        crop_touch = (
            min(box[0] - crop[0], box[1] - crop[1], crop[2] - box[2], crop[3] - box[3])
            <= 0
        )
        old = clean_records[key]
        if (
            not confident
            or crop_touch
            or not base._inside(box, roi)
            or old.get("actual_source_component_contacts_crop")
            or not old.get("matches_current_whole_line")
        ):
            record["reason"] = "CURRENT_SOURCE_CONFIDENCE_OR_CROP_EDGE_VETO"
            continue
        record.update(
            eligible=True,
            bbox_xyxy_px=box,
            crop_xyxy_px=crop,
            raw_tsv_sha256=raw_hash,
            original_crop_array_sha256=spec["crop_array_sha256"],
            original_word_boxes=[w["bbox_xyxy_px"] for w in words],
        )
        modes[tuple(box)].append(key)
    result["clean_bbox_modes"] = [
        {"bbox_xyxy_px": list(box), "independent_observation_keys": keys}
        for box, keys in sorted(modes.items())
    ]
    agreed = [
        box
        for box, keys in modes.items()
        if len(keys) >= POLICY["minimum_distinct_clean_contexts"]
    ]
    if len(agreed) != 1 or len(modes) != 1:
        result["status"] = "LAYOUT_NO_UNIQUE_TWO_CONTEXT_EXACT_BBOX"
        return result
    proposed = list(agreed[0])
    if not base._inside(proposed, current):
        result["status"] = "LAYOUT_CONSENSUS_IS_NOT_ONLY_EXISTING_BBOX_INFLATION"
        return result
    x0, y0, x1, y1 = current
    crop = image[y0:y1, x0:x1]
    ys, xs = np.nonzero(crop < base.POLICY["source_threshold"])
    tight = (
        [
            int(xs.min() + x0),
            int(ys.min() + y0),
            int(xs.max() + x0 + 1),
            int(ys.max() + y0 + 1),
        ]
        if len(xs)
        else None
    )
    result["actual_source_ink_check"] = {
        "threshold_unchanged": base.POLICY["source_threshold"],
        "old_bbox_original_crop_array_sha256": base.source_array_sha256(crop),
        "black_pixel_count": len(xs),
        "tight_bbox_xyxy_px": tight,
        "proposed_bbox_xyxy_px": proposed,
        "contains_all_ink_inside_original_word_union": tight == proposed,
        "source_rescaled_smoothed_or_erased": False,
    }
    if tight != proposed:
        result["status"] = "LAYOUT_ACTUAL_SOURCE_INK_DISAGREES_WITH_CONSENSUS"
        return result
    result.update(
        bbox_xyxy_px=proposed,
        changed=proposed != current,
        status="LAYOUT_SOURCE_BOUND_BBOX_INFLATION_CORRECTED"
        if proposed != current
        else "LAYOUT_ALREADY_SOURCE_BOUND",
        baseline_basis="bottom_of_two_exact_clean_source_word_boxes_font_ink_metrics_separate",
        layout_claim_scope="source placement bbox only; substitute font glyph outlines are not scan-identical",
    )
    return copy.deepcopy(result)
