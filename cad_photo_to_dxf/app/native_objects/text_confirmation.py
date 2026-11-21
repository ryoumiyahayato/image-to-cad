"""Source-bound pending text entries and reliable same-page glyph references.

This index never chooses an answer or blocks another region. Raw strings,
missing suffix evidence and similar-character alternatives stay distinguishable.
"""

from __future__ import annotations

from collections import Counter
import itertools
from . import text_regions as base


def _glyph_record(image, glyph):
    x0, y0, x1, y1 = glyph["bbox_xyxy_px"]
    return {
        "source_component_label": glyph["label"],
        "bbox_xyxy_px": [x0, y0, x1, y1],
        "original_crop_sha256": base.source_array_sha256(image[y0:y1, x0:x1]),
        "original_source_area_px": glyph["source_area_px"],
    }


def similar_character_conflicts(strings):
    """Find exact-position alternatives; never normalize i/I/1 into one."""
    found = {}
    for first, second in itertools.combinations(sorted(set(strings)), 2):
        if len(first) != len(second):
            continue
        differing = [i for i, (a, b) in enumerate(zip(first, second)) if a != b]
        if not differing or any(
            {first[i], second[i]} - {"i", "I", "1"} for i in differing
        ):
            continue
        for i in differing:
            key = (i, first[:i], first[i + 1 :])
            row = found.setdefault(
                key,
                {
                    "character_index_zero_based": i,
                    "prefix": first[:i],
                    "suffix": first[i + 1 :],
                    "alternatives": set(),
                    "raw_strings": set(),
                },
            )
            row["alternatives"].update((first[i], second[i]))
            row["raw_strings"].update((first, second))
    return [
        {
            **row,
            "alternatives": sorted(row["alternatives"]),
            "raw_strings": sorted(row["raw_strings"]),
        }
        for row in found.values()
    ]


def build_confirmation_index(image, text_data, model_records=(), *, glyphs=None):
    roi = text_data["roi_xyxy_px"]
    if glyphs is None:
        _, _, glyphs = base._component_evidence(image, roi)
    references = {}
    for region in text_data["regions"]:
        if not region["complete"]:
            continue
        for word in region.get("words", []):
            raw = word["text"]
            threshold = (
                base.POLICY["minimum_numeric_word_confidence"]
                if raw.isdigit()
                else base.POLICY["minimum_word_confidence"]
            )
            if (
                not word.get("agreement_pass")
                or word["confidence"] < threshold
                or not raw
                or " " in raw
            ):
                continue
            components = sorted(
                [
                    g
                    for g in glyphs
                    if base._inside(g["bbox_xyxy_px"], word["bbox_xyxy_px"])
                ],
                key=lambda g: g["bbox_xyxy_px"][0],
            )
            if len(components) != len(raw):
                continue
            for character, glyph in zip(raw, components):
                references.setdefault(character, []).append(
                    {
                        "character": character,
                        "complete_region_id": region["id"],
                        "word_id": word.get("id"),
                        "raw_complete_word": raw,
                        "word_confidence": word["confidence"],
                        "agreement_basis": word.get(
                            "agreement_basis", "two_verified_Tesseract_contexts"
                        ),
                        "independent_observation_keys": word.get(
                            "independent_agreement_observation_keys", []
                        ),
                        "character_assignment": "left_to_right_complete_word_with_equal_component_count",
                        **_glyph_record(image, glyph),
                    }
                )
    pending = []
    for region in text_data["regions"]:
        if region["complete"]:
            continue
        observations = []
        seen = set()
        for alternative in region.get("completeness_evidence", {}).get(
            "alternatives", []
        ):
            key = alternative.get("observation_key") or alternative.get("context_id")
            if key in seen:
                continue
            seen.add(key)
            words = alternative.get("words", [])
            observations.append(
                {
                    "engine": "Tesseract",
                    "observation_key": key,
                    "raw_text": " ".join(w["text"] for w in words),
                    "words": words,
                    "source_crop_xyxy_px": alternative["crop_xyxy_px"],
                    "raw_artifact": alternative.get(
                        "raw_artifact", {"path": alternative.get("raw_tsv")}
                    ),
                }
            )
        for model in model_records:
            context = model["context"]["crop_xyxy_px"]
            if (
                model.get("region_id") != region["id"]
                and base._overlap(context, region["bbox_xyxy_px"]) < 0.65
            ):
                continue
            key = model.get("observation_key")
            if key in seen:
                continue
            seen.add(key)
            raw = model["raw_model_output"]
            observations.append(
                {
                    "engine": "PP-OCR",
                    "observation_key": key,
                    "raw_text": raw["raw_text"],
                    "source_crop_xyxy_px": context,
                    "original_crop_sha256": model["source_array_sha256"],
                    "raw_CTC_tokens": raw.get("raw_CTC_tokens", []),
                    "model_mean_confidence": raw.get("model_mean_confidence"),
                    "minimum_emitted_character_confidence": raw.get(
                        "minimum_emitted_character_confidence"
                    ),
                }
            )
        strings = sorted({o["raw_text"] for o in observations if o["raw_text"]})
        conflicts = similar_character_conflicts(strings)
        extensions = [
            {
                "raw_prefix": short,
                "raw_longer_alternative": long,
                "unconfirmed_suffix": long[len(short) :],
            }
            for short, long in itertools.permutations(strings, 2)
            if long.startswith(short) and len(long) > len(short)
        ]
        evidence = region.get("completeness_evidence", {})
        reasons = list(region.get("unresolved_reasons", []))
        types = []
        if conflicts:
            types.append("SIMILAR_CHARACTER_EVIDENCE_CONFLICT")
        if extensions:
            types.append("OBSERVED_PREFIX_OR_SUFFIX_INCOMPLETENESS")
        if evidence.get("adjacent_unread_components"):
            types.append("UNASSIGNED_END_GLYPH_COMPONENTS")
        if any(
            "boundary" in reason.lower()
            or "domain" in reason.lower()
            or "ownership" in reason.lower()
            for reason in reasons
        ):
            types.append("NEIGHBOR_OR_INPUT_BOUNDARY_OWNERSHIP")
        if not types:
            types.append("INSUFFICIENT_TRANSCRIPTION_EVIDENCE")
        wanted = {c for conflict in conflicts for c in conflict["alternatives"]}
        source_components = [
            _glyph_record(image, g)
            for g in glyphs
            if base._intersection(g["bbox_xyxy_px"], region["bbox_xyxy_px"])
        ]
        pending.append(
            {
                "region_id": region["id"],
                "status": "NEEDS_SOURCE_CONFIRMATION",
                "source_bbox_xyxy_px": region["bbox_xyxy_px"],
                "current_unapproved_text": region["text"],
                "failure_types": types,
                "character_conflicts": conflicts,
                "observed_prefix_suffix_alternatives": extensions,
                "raw_observations": observations,
                "source_components": source_components,
                "adjacent_unassigned_components": evidence.get(
                    "adjacent_unread_components", []
                ),
                "same_page_reliable_character_references": {
                    c: references.get(c, []) for c in sorted(wanted)
                },
                "unchanged_unresolved_reasons": reasons,
                "automatic_content_adoption": False,
                "other_regions_may_continue": True,
            }
        )
    return {
        "schema": "source_text_confirmation_index_v1",
        "source_array_sha256": base.source_array_sha256(image),
        "roi_xyxy_px": roi,
        "pending_regions": pending,
        "failure_type_counts": dict(
            Counter(t for row in pending for t in row["failure_types"])
        ),
        "same_page_reference_counts": {c: len(rows) for c, rows in references.items()},
        "recognition_calls": 0,
        "raw_texts_changed": False,
        "missing_characters_invented": False,
        "conflict_resolution_rule": "Keep all exact raw alternatives until actual source glyph evidence resolves them; references are comparison evidence, not an answer dictionary.",
    }
