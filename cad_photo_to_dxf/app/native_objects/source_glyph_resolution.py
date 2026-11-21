"""Resolve a saved single-glyph conflict without recognizing or rewriting OCR.

The caller selects an existing group, not an answer.  Every proposed character
must occur in a bound raw model string; the other characters must agree with
the saved Tesseract observations.  Source morphology is a separate evidence
route, never an extra OCR vote or a lowered confidence threshold.  Updates are
atomic for the complete, original ordered group.  No file or model is opened.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np

from . import text_regions as base
from .text_glyph_adjudication import bitmap_sha256, propose_glyph_identity


POLICY = {
    "version": "source_glyph_resolution_v1",
    "source_threshold": base.POLICY["source_threshold"],
    "model_mean_confidence_minimum": 0.98,
    "model_character_confidence_minimum": 0.95,
    "model_distinct_source_contexts": 2,
    "confusion_family": ["1", "I", "i"],
    "raw_observations_may_be_rewritten": False,
    "recognition_calls": 0,
    "whole_original_group_is_atomic": True,
}
_RESOLVABLE_REASONS = {
    "high_confidence_seed_transcription_conflict_at_same_full_word_box",
    "word_missing_two_confident_contexts_with_current_local_OCR",
    "local_transcriptions_conflict",
    "HIGH_CONFIDENCE_TESSERACT_WHOLE_LINE_CONFLICT_RETAINED",
    "NO_SAME_RAW_WHOLE_LINE_TESSERACT_WITNESS_AT_UNCHANGED_THRESHOLDS",
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def receipt_digest(receipt):
    """Digest every receipt field except the self-referential digest field."""
    return _digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})


class _Rejected(ValueError):
    def __init__(self, reason, evidence=None):
        super().__init__(reason)
        self.evidence = evidence


def _require(condition, reason):
    if not condition:
        raise _Rejected(reason)


def _crop(image, box, roi):
    _require(len(box) == 4 and all(int(v) == v for v in box),
             "NON_INTEGER_SOURCE_BOX")
    b = list(map(int, box))
    _require(b[0] < b[2] and b[1] < b[3] and base._inside(b, roi),
             "SOURCE_BOX_OUTSIDE_FROZEN_INPUT")
    return image[b[1]:b[3], b[0]:b[2]]


def _provenance(observation):
    candidates = [observation.get("observation_provenance")]
    candidates += [w.get("observation_provenance")
                   for w in observation.get("words", [])]
    candidates.append(observation.get("raw_artifact"))
    return next((p for p in candidates if p and p.get("specification")), {})


def _observation_view(alternative):
    words = alternative.get("words", [])
    return {
        **alternative,
        "engine": "Tesseract",
        "raw_text": " ".join(w["text"] for w in words),
        "source_crop_xyxy_px": alternative["crop_xyxy_px"],
    }


def _threshold(word):
    return base.POLICY["minimum_numeric_word_confidence"] if word["text"].isdigit() else base.POLICY["minimum_word_confidence"]


def _bind_observation(image, row, observation, roi):
    """Recheck source hashes and actual current borders, including bad reads."""
    box = list(observation["source_crop_xyxy_px"])
    pixels = _crop(image, box, roi)
    actual_hash = base.source_array_sha256(pixels)
    engine = observation.get("engine")
    raw = observation.get("raw_text", "")
    _require(isinstance(raw, str) and raw, "EMPTY_RAW_OBSERVATION")
    if engine == "PP-OCR":
        _require(observation.get("original_crop_sha256") == actual_hash,
                 "MODEL_SOURCE_CROP_HASH_MISMATCH")
        tokens = observation.get("raw_CTC_tokens", [])
        _require("".join(t.get("character", "") for t in tokens) == raw,
                 "MODEL_RAW_TOKEN_STRING_MISMATCH")
        scores = [float(t.get("score", -1)) for t in tokens]
        _require(bool(scores)
                 and math.isclose(float(observation.get("model_mean_confidence", -1)),
                                  float(np.mean(scores)), abs_tol=1e-7)
                 and math.isclose(float(observation.get("minimum_emitted_character_confidence", -1)),
                                  min(scores), abs_tol=1e-7),
                 "MODEL_DECLARED_CONFIDENCE_DIFFERS_FROM_RAW_TOKENS")
        confidence_pass = bool(tokens) and (
            float(observation.get("model_mean_confidence", -1))
            >= POLICY["model_mean_confidence_minimum"]
            and float(observation.get("minimum_emitted_character_confidence", -1))
            >= POLICY["model_character_confidence_minimum"]
            and min(scores)
            >= POLICY["model_character_confidence_minimum"]
        )
        context_identity = {"engine": engine, "crop": box, "crop_sha256": actual_hash}
    else:
        _require(engine == "Tesseract", "UNSUPPORTED_SAVED_ENGINE")
        words = observation.get("words", [])
        _require(" ".join(w["text"] for w in words) == raw,
                 "TESSERACT_RAW_WORD_STRING_MISMATCH")
        provenance = _provenance(observation)
        spec = provenance.get("specification", {})
        _require(spec.get("crop_xyxy_px") == box
                 and spec.get("crop_array_sha256") == actual_hash,
                 "TESSERACT_SOURCE_CROP_HASH_MISMATCH")
        _require(spec.get("source_pixels_modified") is False
                 and spec.get("pixel_scale") == [1, 1],
                 "TESSERACT_SOURCE_WAS_MODIFIED_OR_UNBOUND")
        confidence_pass = bool(words) and all(
            float(w.get("confidence", -1)) >= _threshold(w) for w in words
        )
        context_identity = {
            "engine": engine, "crop": box, "crop_sha256": actual_hash,
            "psm": spec.get("psm"), "language": spec.get("language"),
            "engine_identity": provenance.get("engine_identity"),
        }
    mask = pixels < POLICY["source_threshold"]
    border_ink = int(mask[0].sum() + mask[-1].sum() + mask[:, 0].sum() + mask[:, -1].sum())
    rb = row["bbox_xyxy_px"]
    contains_line = base._inside(rb, box)
    # Check the current row, not the unrelated rows in a saved block context.
    strip_top, strip_bottom = max(box[1], rb[1] - 2), min(box[3], rb[3] + 2)
    if contains_line and strip_top < strip_bottom:
        prefix_ink = int((image[strip_top:strip_bottom, box[0]:rb[0]] < POLICY["source_threshold"]).sum())
        suffix_ink = int((image[strip_top:strip_bottom, rb[2]:box[2]] < POLICY["source_threshold"]).sum())
    else:
        prefix_ink = suffix_ink = -1
    try:
        _local_components(image, rb, roi)
        ownership_failure = None
    except _Rejected as exc:
        ownership_failure = str(exc)
    complete = (contains_line and border_ink == 0 and prefix_ink == 0
                and suffix_ink == 0 and ownership_failure is None)
    return {
        "engine": engine, "raw_text": raw,
        "observation_key": observation.get("observation_key") or observation.get("context_id"),
        "verified_context_key": _digest(context_identity),
        "source_crop_xyxy_px": box, "source_crop_array_sha256": actual_hash,
        "source_hash_verified": True, "confidence_thresholds_pass": confidence_pass,
        "source_domain_complete": bool(complete),
        "actual_crop_border_ink_pixels": border_ink,
        "unassigned_prefix_ink_pixels": prefix_ink,
        "unassigned_suffix_ink_pixels": suffix_ink,
        "source_component_ownership_failure": ownership_failure,
    }


def _complete_row(image, row, roi):
    _require(row.get("complete") is True and not row.get("unresolved_reasons"),
             "OTHER_PARAGRAPH_ROW_IS_NOT_COMPLETE")
    _require(" ".join(w["text"] for w in row.get("words", [])) == row.get("text"),
             "COMPLETE_ROW_RAW_WORDS_DO_NOT_MATCH")
    bound = [
        _bind_observation(image, row, _observation_view(a), roi)
        for a in row.get("completeness_evidence", {}).get("alternatives", [])
        if a.get("words")
    ]
    witnesses = {
        b["verified_context_key"] for b in bound
        if b["raw_text"] == row["text"] and b["confidence_thresholds_pass"]
        and b["source_domain_complete"]
    }
    _require(len(witnesses) >= 2, "COMPLETE_ROW_LACKS_TWO_BOUND_SOURCE_WITNESSES")
    return {"region_id": row["id"], "status": "PRESERVED_COMPLETE_SOURCE_ROW",
            "source_complete": True, "verified_context_keys": sorted(witnesses),
            "observations": bound}


def _local_components(image, box, roi):
    """Use only a word-sized source neighborhood; never label the full region."""
    height = box[3] - box[1]
    margin = max(2, int(math.ceil(height / 2)))
    context = [max(roi[0], box[0] - margin), max(roi[1], box[1] - margin),
               min(roi[2], box[2] + margin), min(roi[3], box[3] + margin)]
    _require(all(a > 0 for a in (box[0] - context[0], box[1] - context[1],
                               context[2] - box[2], context[3] - box[3])),
             "COMPONENT_ASSIGNMENT_TOUCHES_EFFECTIVE_INPUT")
    _, labels, glyphs = base._component_evidence(image, context)
    # Proposal filters deliberately omit thin rules and small fragments.  Such
    # source ink still participates in ownership: a long one-pixel neighbor may
    # not disappear from this check just because it is not a glyph candidate.
    from scipy.ndimage import find_objects

    slices = find_objects(labels)
    touched = np.unique(labels[box[1] - context[1]:box[3] - context[1],
                               box[0] - context[0]:box[2] - context[0]])
    raw_components = []
    for label in touched:
        if not label:
            continue
        ys, xs = slices[int(label) - 1]
        raw_box = [xs.start + context[0], ys.start + context[1],
                   xs.stop + context[0], ys.stop + context[1]]
        _require(base._inside(raw_box, box), "RAW_SOURCE_COMPONENT_SHARED_OUTSIDE_WORD")
        raw_components.append({"label": int(label), "bbox_xyxy_px": raw_box})
    # A surrounding frame can have a bounding box covering the word while no
    # frame pixel enters it.  Ownership follows the sampled raw labels above,
    # not bounding-box overlap (which would falsely reject enclosed labels).
    touched_labels = {int(label) for label in touched if label}
    intersecting = [g for g in glyphs if g["label"] in touched_labels]
    _require(all(base._inside(g["bbox_xyxy_px"], box) for g in intersecting),
             "COMPONENT_SHARED_WITH_OUTSIDE_WORD")
    compact_labels = {g["label"] for g in intersecting}
    for glyph in intersecting:
        glyph["retained_noncompact_word_components"] = [
            c for c in raw_components if c["label"] not in compact_labels
        ]
    return sorted(intersecting, key=lambda g: (g["bbox_xyxy_px"][0], g["bbox_xyxy_px"][1]))


def _reference_transcription_binding(image, row, word, roi):
    """Recheck a raw witness while retaining the checkpoint's approved route.

    Some approved references have two Tesseract contexts, others a saved
    independent-engine decision.  This stage does not invent a third approval
    route or silently require two new Tesseract observations of the latter.
    """
    witnesses, attempted = [], []
    for alternative in row.get("completeness_evidence", {}).get("alternatives", []):
        if not any(w["text"] == word["text"]
                   and float(w.get("confidence", -1)) >= _threshold(w)
                   and base._overlap(w["bbox_xyxy_px"], word["bbox_xyxy_px"]) >= .6
                   for w in alternative.get("words", [])):
            continue
        bound = _bind_observation(image, row, _observation_view(alternative), roi)
        attempted.append(bound)
        if bound["source_domain_complete"]:
            witnesses.append(bound)
    if not witnesses:
        raise _Rejected("REFERENCE_LACKS_A_REBOUND_CONFIDENT_RAW_WORD", {
            "region_id": row["id"], "word_id": word.get("id"),
            "raw_complete_word": word["text"], "bound_word_observations": attempted,
        })
    cross = row.get("cross_engine_evidence", {})
    if word.get("agreement_basis") == "cross_engine_same_raw_whole_line_with_separate_confidence_scales":
        engine_witnesses = word.get("independent_engine_witnesses", {})
        _require(cross.get("approved_by_cross_engine_and_source_checks") is True
                 and not cross.get("unresolved_reasons")
                 and cross.get("independent_engine_family_count") == 2
                 and set(cross.get("raw_model_strings", [])) == {row["text"]}
                 and bool(engine_witnesses.get("Tesseract_observation_keys"))
                 and len(set(engine_witnesses.get("PP_context_input_sha256", []))) >= 2,
                 "REFERENCE_CROSS_ENGINE_APPROVAL_LEDGER_INVALID")
        route = "checkpoint_approved_cross_engine_with_rebound_raw_Tesseract_word"
    else:
        _require(len(set(word.get("independent_agreement_observation_keys", []))) >= 2,
                 "REFERENCE_SAVED_INDEPENDENT_WORD_AGREEMENT_MISSING")
        route = "checkpoint_approved_independent_word_agreement_with_rebound_raw_word"
    return {"route": route, "verified_context_keys": sorted({w["verified_context_key"] for w in witnesses}),
            "saved_word_evidence_sha256": _digest(word),
            "saved_approval_is_checkpoint_evidence_not_new_recognition": True}


def _references(image, text_data, entry, roi, source_hash):
    """Rebind indexed exemplars and add eligible complete-word control classes."""
    records, arrays, seen, excluded = [], [], set(), []
    for row in text_data["regions"]:
        if not row.get("complete") or row.get("unresolved_reasons"):
            continue
        for word in row.get("words", []):
            raw = word.get("text", "")
            if (not word.get("agreement_pass") or not raw or " " in raw
                    or not set(raw).intersection(POLICY["confusion_family"])
                    or float(word.get("confidence", -1)) < _threshold(word)):
                continue
            try:
                transcription = _reference_transcription_binding(image, row, word, roi)
                components = _local_components(image, word["bbox_xyxy_px"], roi)
            except _Rejected as exc:
                excluded.append({"region_id": row["id"], "word_id": word.get("id"),
                                 "raw_complete_word": raw, "reason": str(exc),
                                 "evidence": exc.evidence})
                continue
            if len(components) != len(raw):
                excluded.append({"region_id": row["id"], "word_id": word.get("id"),
                                 "raw_complete_word": raw,
                                 "reason": "REFERENCE_COMPACT_COMPONENT_COUNT_DIFFERS_FROM_RAW_WORD",
                                 "source_component_count": len(components), "raw_character_count": len(raw)})
                continue
            for character, component in zip(raw, components):
                if character not in POLICY["confusion_family"]:
                    continue
                box = component["bbox_xyxy_px"]
                key = tuple(box)
                if key in seen:
                    continue
                seen.add(key)
                pixels = _crop(image, box, roi)
                record = {
                    "character": character, "complete_region_id": row["id"],
                    "word_id": word.get("id"), "raw_complete_word": raw,
                    "word_confidence": word["confidence"], "bbox_xyxy_px": box,
                    "original_crop_sha256": base.source_array_sha256(pixels),
                    "character_assignment": "left_to_right_complete_word_with_equal_component_count",
                    "reference_id": _digest([source_hash, box]),
                    "independence_key": _digest([source_hash, box]),
                    "reliable": True,
                    "transcription_binding": transcription,
                    "retained_noncompact_word_components": component["retained_noncompact_word_components"],
                    "reference_bitmap_scope": "indexed_compact_component_not_synthesized_whole_character",
                }
                records.append(record)
                arrays.append({**record, "bitmap": pixels < POLICY["source_threshold"]})
    by_identity = {(r["complete_region_id"], tuple(r["bbox_xyxy_px"])): r for r in records}
    for character, indexed in entry.get("same_page_reliable_character_references", {}).items():
        for old in indexed:
            new = by_identity.get((old["complete_region_id"], tuple(old["bbox_xyxy_px"])))
            if not (new is not None and new["character"] == character
                    and new["raw_complete_word"] == old["raw_complete_word"]
                    and new["original_crop_sha256"] == old["original_crop_sha256"]):
                raise _Rejected("INDEXED_REFERENCE_NO_LONGER_MATCHES_SOURCE_AND_COMPLETE_WORD", {
                    "reference_character": character, "indexed_reference": copy.deepcopy(old),
                    "recomputed_reference": new,
                    "word_exclusions": [e for e in excluded
                                        if e["region_id"] == old["complete_region_id"]
                                        and e["raw_complete_word"] == old["raw_complete_word"]],
                })
    return arrays, records, excluded


def _resolve_row(image, row, entry, text_data, roi, source_hash):
    _require(set(row.get("unresolved_reasons", [])) <= _RESOLVABLE_REASONS,
             "NON_CHARACTER_FAILURE_REMAINS")
    _require(not entry.get("observed_prefix_suffix_alternatives")
             and not entry.get("adjacent_unassigned_components"),
             "SUFFIX_OR_ADJACENT_SOURCE_IS_STILL_UNASSIGNED")
    conflicts = entry.get("character_conflicts", [])
    _require(len(conflicts) == 1, "REQUIRES_EXACTLY_ONE_SAVED_CHARACTER_CONFLICT")
    conflict = conflicts[0]
    index = int(conflict["character_index_zero_based"])
    raw_current = row["text"]
    _require(entry.get("current_unapproved_text") == raw_current
             and entry.get("source_bbox_xyxy_px") == row["bbox_xyxy_px"],
             "CONFIRMATION_ENTRY_DOES_NOT_MATCH_CURRENT_ROW")
    _require(0 <= index < len(raw_current) and not raw_current[index].isspace(),
             "CONFLICT_IS_NOT_A_CHARACTER_SLOT")
    _require(set(conflict["alternatives"]) <= set(POLICY["confusion_family"]),
             "UNSUPPORTED_CHARACTER_CONFLICT_FAMILY")
    raw_observations = entry.get("raw_observations", [])
    bound = [_bind_observation(image, row, o, roi) for o in raw_observations]
    remainder = raw_current[:index] + raw_current[index + 1:]
    _require(bool(bound) and all(
        len(o["raw_text"]) == len(raw_current)
        and o["raw_text"][:index] + o["raw_text"][index + 1:] == remainder
        for o in bound
    ), "NON_CONFLICT_CHARACTERS_OR_SUFFIX_DISAGREE")
    tess = [o for o in bound if o["engine"] == "Tesseract"
            and o["confidence_thresholds_pass"] and o["source_domain_complete"]]
    models = [o for o in bound if o["engine"] == "PP-OCR"
              and o["confidence_thresholds_pass"] and o["source_domain_complete"]]
    _require(bool(tess), "NO_BOUND_CONFIDENT_TESSERACT_REMAINDER_WITNESS")
    _require(len({o["verified_context_key"] for o in models})
             >= POLICY["model_distinct_source_contexts"],
             "INSUFFICIENT_BOUND_MODEL_SOURCE_CONTEXTS")
    _require(all(o["raw_text"][index] in conflict["alternatives"]
                 for o in tess + models), "ADDITIONAL_CONFIDENT_CHARACTER_CONFLICT")
    components = sorted(entry.get("source_components", []),
                        key=lambda g: (g["bbox_xyxy_px"][0], g["bbox_xyxy_px"][1]))
    character_slots = [n for n, c in enumerate(raw_current) if not c.isspace()]
    _require(len(components) == len(character_slots),
             "SOURCE_COMPONENT_COUNT_DOES_NOT_ASSIGN_CHARACTERS")
    actual_components = _local_components(image, row["bbox_xyxy_px"], roi)
    _require([g["bbox_xyxy_px"] for g in actual_components]
             == [g["bbox_xyxy_px"] for g in components],
             "SAVED_COMPONENT_ASSIGNMENT_CHANGED")
    _require(not any(g["retained_noncompact_word_components"] for g in actual_components),
             "UNASSIGNED_NONCOMPACT_SOURCE_IN_RESOLVED_ROW")
    for component in components:
        pixels = _crop(image, component["bbox_xyxy_px"], roi)
        _require(base.source_array_sha256(pixels) == component["original_crop_sha256"],
                 "SOURCE_COMPONENT_CROP_HASH_MISMATCH")
    target = components[character_slots.index(index)]
    box = target["bbox_xyxy_px"]
    top = int(math.ceil((box[3] - box[1]) / 3))
    context_box = [box[0] - 2, box[1] - top, box[2] + 2, box[3] + 2]
    context_pixels = _crop(image, context_box, roi)
    context_mask = context_pixels < POLICY["source_threshold"]
    target_mask = _crop(image, box, roi) < POLICY["source_threshold"]
    target_in_context = [2, top, 2 + target_mask.shape[1], top + target_mask.shape[0]]
    outside = context_mask.copy()
    outside[top:top + target_mask.shape[0], 2:2 + target_mask.shape[1]] = False
    _require(not outside.any(), "DOT_OR_NEIGHBOR_IN_TARGET_GLYPH_HALO")
    references, reference_records, reference_exclusions = _references(image, text_data, entry, roi, source_hash)
    proposal = propose_glyph_identity(
        target_mask, references, conflict["alternatives"], source_complete=True,
        context_bitmap=context_mask, target_bbox_in_context=target_in_context,
        source_evidence={
            "source_hash_verified": True, "ownership_verified": True,
            "no_shared_source": True, "source_sha256": source_hash,
            "context_sha256": bitmap_sha256(context_mask),
        },
    )
    if proposal.get("accepted") is not True:
        raise _Rejected("SOURCE_GLYPH_PROPOSAL_REMAINS_AMBIGUOUS", {
            "region_id": row["id"], "target_component": copy.deepcopy(target),
            "target_context_xyxy_px": context_box,
            "target_context_array_sha256": base.source_array_sha256(context_pixels),
            "same_page_references": reference_records, "glyph_proposal": proposal,
            "reference_exclusions": reference_exclusions,
        })
    character = proposal["character"]
    selected = {o["raw_text"] for o in models if o["raw_text"][index] == character}
    _require(len(selected) == 1, "GLYPH_IDENTITY_HAS_NO_UNIQUE_RAW_MODEL_STRING")
    resolved = next(iter(selected))
    _require(all(o["raw_text"] == resolved for o in models),
             "CONFIDENT_MODEL_STRINGS_STILL_CONFLICT")
    # Only the derived content changes.  The original word/confidence/provenance
    # ledger remains byte-for-byte equivalent in the caller's copied contract.
    words = row.get("words", [])
    tokens = resolved.split(" ")
    _require(len(tokens) == len(words), "RAW_MODEL_WORD_LAYOUT_DOES_NOT_MATCH_SOURCE")
    resolved_words = [
        {"id": w.get("id"), "text": token, "bbox_xyxy_px": list(w["bbox_xyxy_px"]),
         "raw_word_evidence_sha256": _digest(w), "raw_word_text": w["text"],
         "transcription_basis": "BOUND_RAW_MODEL_AND_SOURCE_GLYPH_ADJUDICATION"}
        for w, token in zip(words, tokens)
    ]
    record = {
        "region_id": row["id"], "status": "ACCEPTED_SOURCE_GLYPH_ADJUDICATION",
        "accepted": True, "source_complete": True, "resolved_text": resolved,
        "character_index_zero_based": index,
        "original_unresolved_reasons": list(row.get("unresolved_reasons", [])),
        "original_current_text": raw_current, "original_raw_observations_sha256": _digest(raw_observations),
        "raw_observations_changed": False, "observations": bound,
        "target_component": copy.deepcopy(target),
        "target_context_xyxy_px": context_box,
        "target_context_array_sha256": base.source_array_sha256(context_pixels),
        "target_context_bitmap_sha256": bitmap_sha256(context_mask),
        "source_sha256_in_morphology_means": "source_array_sha256_not_file_bytes",
        "target_halo_ink_pixels": int(outside.sum()),
        "same_page_references": reference_records, "glyph_proposal": proposal,
        "reference_exclusions": reference_exclusions,
        "model_contexts_are_one_engine_family": True,
        "non_conflict_content_exactly_matches_all_saved_raw_observations": True,
        "confidence_thresholds_unchanged": True,
    }
    updated = copy.deepcopy(row)
    updated.update(text=resolved, complete=True, status="TEXT_PROPOSAL_PENDING_SOURCE_REVIEW",
                   unresolved_reasons=[], resolved_words=resolved_words,
                   source_glyph_adjudication=record)
    return updated, record


def resolve_group_from_source(image, text_data, confirmation_index, group_id,
                              *, source_file_sha256=None):
    """Return ``(copy_of_text_data, receipt)``; never run OCR or partly adopt.

    ``source_file_sha256`` is an optional caller-verified TIFF/file digest.  It
    is recorded separately from the freshly computed uint8 source-array hash.
    An already complete ordinary group is checked and passed through unchanged.
    """
    result = copy.deepcopy(text_data)
    groups = {g["id"]: g for g in text_data["groups"]}
    if group_id not in groups:
        raise ValueError("SELECTED_GROUP_NOT_IN_CHECKPOINT")
    group = groups[group_id]
    rows = {r["id"]: r for r in text_data["regions"]}
    source_hash = base.source_array_sha256(image)
    ordered = list(group["region_ids"])
    receipt = {
        "schema": "source_glyph_resolution_v1", "policy": POLICY,
        "group_id": group_id, "ordered_region_ids": ordered,
        "source_array_sha256": source_hash, "source_file_sha256": source_file_sha256,
        "input_text_data_sha256": _digest(text_data),
        "confirmation_index_sha256": _digest(confirmation_index),
        "recognition_calls": 0, "raw_observations_changed": False,
        "source_pixels_modified": False, "accepted": False, "changed": False,
        "status": "PENDING_SOURCE_CONFIRMATION", "reasons": [], "row_checks": [],
    }
    try:
        _require(image.ndim == 2 and image.dtype == np.uint8,
                 "REQUIRES_UNMODIFIED_UINT8_GRAYSCALE_SOURCE")
        _require(text_data.get("source_array_sha256") == source_hash
                 and confirmation_index.get("source_array_sha256") == source_hash,
                 "FROZEN_SOURCE_ARRAY_HASH_MISMATCH")
        roi = list(text_data["roi_xyxy_px"])
        _require(confirmation_index.get("roi_xyxy_px") == roi,
                 "CONFIRMATION_INDEX_ROI_MISMATCH")
        _crop(image, roi, [0, 0, image.shape[1], image.shape[0]])
        _require(text_data.get("source_size_px") == [image.shape[1], image.shape[0]],
                 "FROZEN_SOURCE_DIMENSIONS_MISMATCH")
        _require(bool(ordered) and len(ordered) == len(set(ordered))
                 and all(rid in rows for rid in ordered), "GROUP_MEMBERSHIP_INVALID")
        _require(group.get("text") == "\n".join(rows[rid]["text"] for rid in ordered),
                 "GROUP_TEXT_ORDER_DOES_NOT_MATCH_ROWS")
        if group.get("lines"):
            _require([line["region_id"] for line in group["lines"]] == ordered
                     and [line["text"] for line in group["lines"]]
                     == [rows[rid]["text"] for rid in ordered],
                     "GROUP_LINE_LEDGER_DOES_NOT_MATCH_ROWS")
        pending = {p["region_id"]: p for p in confirmation_index.get("pending_regions", [])}
        replacements = {}
        for rid in ordered:
            row = rows[rid]
            if row.get("complete"):
                record = _complete_row(image, row, roi)
            else:
                _require(rid in pending, "INCOMPLETE_ROW_MISSING_CONFIRMATION_ENTRY")
                replacements[rid], record = _resolve_row(
                    image, row, pending[rid], text_data, roi, source_hash)
            receipt["row_checks"].append(record)
        receipt.update(
            accepted=True, changed=bool(replacements),
            status="ACCEPTED_SOURCE_GLYPH_ADJUDICATION" if replacements else "PASSTHROUGH_COMPLETE_GROUP",
            resolved_region_texts={rid: replacements.get(rid, rows[rid])["text"] for rid in ordered},
            source_region_bboxes={rid: list(rows[rid]["bbox_xyxy_px"]) for rid in ordered},
        )
        receipt["resolved_group_text"] = "\n".join(receipt["resolved_region_texts"][rid] for rid in ordered)
        for i, row in enumerate(result["regions"]):
            if row["id"] in replacements:
                result["regions"][i] = replacements[row["id"]]
        output_group = next(g for g in result["groups"] if g["id"] == group_id)
        if replacements:
            output_group.update(text=receipt["resolved_group_text"], complete=True,
                                unresolved_reasons=[])
            for line in output_group.get("lines", []):
                line.update(text=receipt["resolved_region_texts"][line["region_id"]], complete=True)
    except _Rejected as exc:
        receipt["reasons"].append(str(exc))
        if exc.evidence is not None:
            receipt["counterexample"] = exc.evidence
        # Reconstruct to guarantee that no earlier resolved row can leak into a
        # failed multirow transaction, even if a later row or binding fails.
        result = copy.deepcopy(text_data)
    receipt["receipt_sha256"] = receipt_digest(receipt)
    result["source_glyph_resolution_receipt"] = copy.deepcopy(receipt)
    if receipt["accepted"]:
        output_group = next(g for g in result["groups"] if g["id"] == group_id)
        output_group["source_glyph_adjudication"] = {
            "accepted": True, "status": receipt["status"],
            "receipt_sha256": receipt["receipt_sha256"],
        }
    return result, receipt
