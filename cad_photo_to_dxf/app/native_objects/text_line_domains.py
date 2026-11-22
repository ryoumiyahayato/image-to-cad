"""Finite source-domain repair using this task's saved observations and ink.

Domain proposals use measured component positions and line layout, separately
from transcription acceptance. Initial discovery and current local OCR are
bound to their actual source/configuration; IDs cannot manufacture extra votes.
Raw source pixels, ambiguous suffixes and graphics are never erased/rescaled.
"""

from __future__ import annotations

from .performance import profiled
import copy
import hashlib
import json
import math
from pathlib import Path
from .evidence_paths import relative_evidence_path
import time

from . import text_regions as base
from .contracts import validate_text_regions


POLICY = {
    "version": "current_source_component_line_domains_v4_glyph_neighbor_partition",
    "maximum_regions": 24,
    "PSM": [7, 13],
    "enclosed_PSM": [6, 8],
    "word_confidence": 85.0,
    "numeric_confidence": 95.0,
    "minimum_repeated_contexts": 2,
    "minimum_source_components_for_domain": 2,
    "proposal_word_confidence": 20.0,
    "source_component_word_overlap": 0.5,
    "source_component_height_ratio": [0.45, 1.7],
    "source_component_baseline_ratio": 0.5,
    "source_row_join_gap_glyph_heights": 1.25,
    "source_row_baseline_glyph_heights": 0.35,
    "domain_confirmation_is_not_transcription_confirmation": True,
    "spatial_slot_overlap": 0.65,
    "source_margin_px": 2,
    "suffix_scan_maximum_glyph_heights": 3.0,
    "stopping_white_gap_glyph_heights": 0.5,
    "pollution_minimum_glyph_heights": 0.15,
    "paragraph_maximum_gap_glyph_heights": 0.75,
    "paragraph_alignment_glyph_heights": 0.35,
    "paragraph_height_ratio_maximum": 1.25,
    "maximum_paragraph_lines": 6,
    "source_threshold": 192,
    "source_pixels_modified": False,
    "automatic_formal_adoption": False,
    "confidence_or_content_gates_relaxed": False,
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _median(values):
    values = sorted(values)
    n = len(values)
    if not n:
        raise ValueError("EMPTY_GEOMETRICAL_MEDIAN")
    return (
        float(values[n // 2]) if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2.0
    )


def _qualifies(word):
    text = word["text"]
    alnum = "".join(c for c in text if c.isalnum())
    b = word["bbox_xyxy_px"]
    h, w = b[3] - b[1], b[2] - b[0]
    threshold = (
        POLICY["numeric_confidence"] if text.isdigit() else POLICY["word_confidence"]
    )
    # Single-character circuit/symbol observations remain in the old ledger,
    # but do not enlarge a neighbouring line's geometrical anchor domain.
    return (
        len(alnum) >= 2
        and word["confidence"] >= threshold
        and 7 <= h <= 90
        and 2 <= w <= 650
        and w / h <= max(5.0, 2.5 * len(text))
    )


def _context(word):
    # A context name is a locator, not independent evidence.
    return str(
        word.get("observation_key")
        or word.get("context_fingerprint")
        or ("unbound:" + str(word.get("context_id")) + ":" + str(word.get("psm")))
    )


def _collect_current_observations(image, text_data, cache_dir, provenance, output):
    """Load and verify actual raw passes from the current upstream stage.

    The cache may contain discovery only. It is not a prerequisite for repair:
    saved local TSV/meta and source geometry also belong to this task. Every
    equivalent source crop/configuration is counted once regardless of ID.
    """
    source_identity = {
        "source_array_sha256": base.source_array_sha256(image),
        "source_sha256": provenance["source_sha256"],
    }
    text_root = Path(
        provenance.get("text_evidence_dir", Path(provenance["text_path"]).parent)
    )
    policy_path = text_root / "policy_frozen_before_recognition.json"
    upstream_policy = (
        json.loads(policy_path.read_text()) if policy_path.exists() else {}
    )
    observations, pass_records, seen_passes, alias_records = [], [], {}, []

    def ingest(tsv_path, meta_path, context_id, origin, existing_ids=None):
        meta = json.loads(meta_path.read_text())
        spec = meta["specification"]
        if meta["status"] != "COMPLETED" or meta.get("tsv_sha256") != base._sha(
            tsv_path
        ):
            raise ValueError(
                "CURRENT_OBSERVATION_TSV_OR_STATUS_INVALID:" + str(tsv_path)
            )
        box = list(spec["crop_xyxy_px"])
        x0, y0, x1, y1 = box
        if not base._inside(box, [0, 0, image.shape[1], image.shape[0]]):
            raise ValueError("CURRENT_OBSERVATION_CROP_OUTSIDE_SOURCE")
        if base.source_array_sha256(image[y0:y1, x0:x1]) != spec["crop_array_sha256"]:
            raise ValueError("CURRENT_OBSERVATION_CROP_HASH_MISMATCH")
        if spec.get("source_pixels_modified") or spec.get("pixel_scale") != [1, 1]:
            raise ValueError("CURRENT_OBSERVATION_IS_NOT_UNMODIFIED_SOURCE")
        key = base.raw_observation_key(meta)
        artifact = {
            **base.raw_observation_provenance(meta),
            "raw_tsv": relative_evidence_path(tsv_path, output),
            "raw_tsv_sha256": base._sha(tsv_path),
            "metadata": relative_evidence_path(meta_path, output),
            "metadata_sha256": base._sha(meta_path),
            "source_identity": source_identity,
            "specification": spec,
            "engine": upstream_policy.get("engine"),
            "origin": origin,
        }
        if key in seen_passes:
            if seen_passes[key]["raw_tsv_sha256"] != artifact["raw_tsv_sha256"]:
                raise ValueError(
                    "DUPLICATE_SOURCE_CONFIGURATION_HAS_DIFFERENT_RAW_RESULT"
                )
            alias_records.append(
                {
                    "context_id": context_id,
                    "observation_key": key,
                    "canonical_context_id": seen_passes[key]["context_id"],
                    "reason": "SAME_SOURCE_PIXELS_CROP_AND_OCR_CONFIGURATION",
                }
            )
            return
        seen_passes[key] = {**artifact, "context_id": context_id}
        padding = int(spec.get("external_white_padding_px", 0))
        origin_box = [
            box[0] - padding,
            box[1] - padding,
            box[2] + padding,
            box[3] + padding,
        ]
        words = base._parse_tsv(
            tsv_path.read_text(), origin_box, context_id, spec["psm"]
        )
        included = []
        for number, word in enumerate(words):
            if not base._intersection(word["bbox_xyxy_px"], text_data["roi_xyxy_px"]):
                continue
            identifier = (existing_ids or {}).get(
                (word["text"], tuple(word["bbox_xyxy_px"])),
                "current-" + key[:12] + "-" + str(number),
            )
            entry = {
                **word,
                "id": identifier,
                "origin": origin,
                "observation_key": key,
                "context_fingerprint": key,
                "observation_provenance": artifact,
            }
            observations.append(entry)
            included.append(identifier)
        pass_records.append(
            {
                "context_id": context_id,
                "observation_key": key,
                "word_ids": included,
                **artifact,
            }
        )

    discovery_path = text_root / "discovery_observations.json"
    discovery = (
        json.loads(discovery_path.read_text()) if discovery_path.exists() else []
    )
    ids_by_context = {}
    for word in discovery:
        ctx = str(word.get("context_id", word.get("tile_id", "")))
        ids_by_context.setdefault(ctx, {})[
            (word["text"], tuple(word["bbox_xyxy_px"]))
        ] = word["id"]
    for meta_path in sorted((text_root / "discovery_ocr").glob("*.json")):
        tsv_path = meta_path.with_suffix(".tsv")
        if not tsv_path.exists():
            raise FileNotFoundError("CURRENT_DISCOVERY_TSV_MISSING:" + str(tsv_path))
        ingest(
            tsv_path,
            meta_path,
            meta_path.stem,
            "current_discovery",
            ids_by_context.get(meta_path.stem),
        )
    local_references = {}
    for region in text_data["regions"]:
        for alternative in region.get("completeness_evidence", {}).get(
            "alternatives", []
        ):
            raw = alternative.get("raw_tsv")
            if not raw:
                raise ValueError("CURRENT_LOCAL_OBSERVATION_HAS_NO_RAW_TSV")
            tsv = text_root / raw
            local_references.setdefault(str(tsv), (tsv, alternative["context_id"]))
    for tsv, context_id in sorted(
        local_references.values(), key=lambda item: str(item[0])
    ):
        ingest(tsv, tsv.with_suffix(".json"), context_id, "current_local_OCR")

    # A valid explicit cache remains optional discovery evidence. Fresh tasks
    # have the raw discovery pass above, so reading its generated cache must not
    # add a second vote for the same observation under the word 'seed'.
    cached, cache_info = base._cached_observations(
        cache_dir, image, text_data["roi_xyxy_px"]
    )
    known = {
        (w["context_id"], w["psm"], w["text"], tuple(w["bbox_xyxy_px"]))
        for w in observations
    }
    cache_only = []
    for word in cached or []:
        identity = (
            word["context_id"],
            word["psm"],
            word["text"],
            tuple(word["bbox_xyxy_px"]),
        )
        if identity in known:
            continue
        # Legacy cache lacks a crop/config identity. It may suggest a location,
        # but cannot supply a separate independent confirmation vote here.
        word = {
            **word,
            "observation_key": "unbound-cache:" + _digest(identity),
            "independent_confirmation_eligible": False,
            "observation_provenance": {
                "source_identity": source_identity,
                "cache_manifest_sha256": cache_info.get("manifest_sha256"),
                "missing_raw_crop_configuration": True,
            },
        }
        observations.append(word)
        cache_only.append(word["id"])
    return observations, {
        "schema": "current-source-observation-collection-v1",
        "passes": pass_records,
        "deduplicated_aliases": alias_records,
        "actual_independent_passes": len(pass_records),
        "current_local_passes": sum(
            p["origin"] == "current_local_OCR" for p in pass_records
        ),
        "cache": cache_info,
        "unbound_legacy_cache_word_ids": cache_only,
        "source_identity": source_identity,
        "transcription_gates_unchanged": True,
    }


def _proposal_word(word):
    """Position/scale hint only: never an accepted transcription."""
    box = word["bbox_xyxy_px"]
    height, width = box[3] - box[1], box[2] - box[0]
    return (
        len("".join(c for c in word["text"] if c.isalnum())) >= 2
        and word["confidence"] >= POLICY["proposal_word_confidence"]
        and 7 <= height <= 90
        and 2 <= width <= 650
    )


def _anchors(observations, glyphs=None):
    """Anchor source components by compatible positions, not identical boxes.

    At least two actual compact components must support a domain proposal.
    Whether their text is correct is deliberately left to _complete_region.
    """
    glyphs = glyphs or []
    slots = []
    for word in sorted(
        (w for w in observations if _proposal_word(w)),
        key=lambda w: (-w["confidence"], tuple(w["bbox_xyxy_px"]), w["id"]),
    ):
        box = word["bbox_xyxy_px"]
        h = box[3] - box[1]
        support = [
            g
            for g in glyphs
            if base._intersection(g["bbox_xyxy_px"], box)
            / max(1, base._area(g["bbox_xyxy_px"]))
            >= POLICY["source_component_word_overlap"]
            and POLICY["source_component_height_ratio"][0]
            <= (g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1]) / h
            <= POLICY["source_component_height_ratio"][1]
            and abs(g["bbox_xyxy_px"][3] - box[3])
            <= POLICY["source_component_baseline_ratio"]
            * max(h, g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1])
        ]
        if len(support) < POLICY["minimum_source_components_for_domain"]:
            continue
        source_box = base._box_union([g["bbox_xyxy_px"] for g in support])
        labels = {g["label"] for g in support}
        compatible = [
            slot
            for slot in slots
            if len(labels.intersection(slot["component_labels"])) >= 2
            and base._overlap(source_box, slot["first_box"])
            >= POLICY["spatial_slot_overlap"]
        ]
        if compatible:
            compatible[0]["observations"].append(word)
            compatible[0]["source_components"].extend(
                g
                for g in support
                if g["label"] not in compatible[0]["component_labels"]
            )
            compatible[0]["component_labels"].update(labels)
        else:
            slots.append(
                {
                    "first_box": source_box,
                    "observations": [word],
                    "source_components": list(support),
                    "component_labels": labels,
                }
            )
    result = []
    for slot in slots:
        modal_words = slot["observations"]
        modal_box = base._box_union(
            [g["bbox_xyxy_px"] for g in slot["source_components"]]
        )
        contexts = sorted({_context(w) for w in modal_words})
        result.append(
            {
                "id": "ANCHOR-" + _digest(list(modal_box))[:12],
                "bbox_xyxy_px": list(modal_box),
                "modal_contexts": contexts,
                "modal_support": len(contexts),
                "maximum_confidence": max(w["confidence"] for w in modal_words),
                "modal_observation_ids": [w["id"] for w in modal_words],
                "all_observation_ids": [w["id"] for w in slot["observations"]],
                "raw_text_alternatives": sorted(
                    {w["text"] for w in slot["observations"]}
                ),
                "observed_box_variants": [
                    {
                        "bbox_xyxy_px": w["bbox_xyxy_px"],
                        "observation_id": w["id"],
                        "observation_key": _context(w),
                    }
                    for w in modal_words
                ],
                "source_components": slot["source_components"],
                "source_component_labels": sorted(slot["component_labels"]),
                "domain_proposal_not_transcription_approval": True,
                "box_selected_by_geometry_and_support_not_desired_text": True,
            }
        )
    return sorted(
        result, key=lambda a: (a["bbox_xyxy_px"][1], a["bbox_xyxy_px"][0], a["id"])
    )


def _anchor_line(region, anchors, glyphs=None):
    seed_ids = set(region.get("discovery_observation_ids", []))
    old = region.get("discovery_bbox_xyxy_px", region["bbox_xyxy_px"])
    selected = [
        a
        for a in anchors
        if seed_ids.intersection(a["all_observation_ids"])
        or (
            base._overlap(old, a["bbox_xyxy_px"]) >= 0.75
            and base._intersection(old, a["bbox_xyxy_px"]) > 0
        )
    ]
    if not selected:
        # A source row already proposed by connected components must not need
        # an earlier correct string before it is allowed to obtain evidence.
        source = [g for g in (glyphs or []) if base._inside(g["bbox_xyxy_px"], old)]
        if len(source) < POLICY["minimum_source_components_for_domain"]:
            return None, "NO_SOURCE_COMPONENT_ROW_SUPPORT"
        box = base._box_union([g["bbox_xyxy_px"] for g in source])
        selected = [
            {
                "id": "SOURCE-" + _digest(box)[:12],
                "bbox_xyxy_px": box,
                "source_components": source,
                "source_component_labels": [g["label"] for g in source],
                "all_observation_ids": [],
                "raw_text_alternatives": [],
                "modal_support": 0,
                "domain_proposal_not_transcription_approval": True,
            }
        ]
    rows = []
    for anchor in sorted(
        selected, key=lambda a: (a["bbox_xyxy_px"][3], a["bbox_xyxy_px"][0])
    ):
        b = anchor["bbox_xyxy_px"]
        h = b[3] - b[1]
        match = None
        for row in rows:
            rh = _median([a["bbox_xyxy_px"][3] - a["bbox_xyxy_px"][1] for a in row])
            baseline = _median([a["bbox_xyxy_px"][3] for a in row])
            if 0.65 <= h / rh <= 1.5 and abs(b[3] - baseline) <= 0.25 * max(h, rh):
                match = row
                break
        if match is None:
            rows.append([anchor])
        else:
            match.append(anchor)
    if len(rows) != 1:
        return {
            "competing_anchor_rows": [[a["id"] for a in row] for row in rows]
        }, "MULTIPLE_COMPETING_ANCHOR_BASELINES"
    row = sorted(rows[0], key=lambda a: a["bbox_xyxy_px"][0])
    height = _median([a["bbox_xyxy_px"][3] - a["bbox_xyxy_px"][1] for a in row])
    box = base._box_union([a["bbox_xyxy_px"] for a in row])
    # Add compact same-baseline neighbours before the whitespace scan, so a
    # missed prefix/suffix separated by normal word spacing stays in the input.
    components = {g["label"]: g for a in row for g in a.get("source_components", [])}
    baseline = _median([a["bbox_xyxy_px"][3] for a in row])
    while True:
        added = [
            g
            for g in (glyphs or [])
            if g["label"] not in components
            and 0.45 <= (g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1]) / height <= 1.7
            and abs(g["bbox_xyxy_px"][3] - baseline)
            <= POLICY["source_row_baseline_glyph_heights"] * height
            and max(g["bbox_xyxy_px"][0] - box[2], box[0] - g["bbox_xyxy_px"][2], 0)
            <= POLICY["source_row_join_gap_glyph_heights"] * height
        ]
        if not added:
            break
        expanded = base._box_union([box] + [g["bbox_xyxy_px"] for g in added])
        if expanded[2] - expanded[0] > 750:
            return None, "SOURCE_ROW_EXCEEDS_FINITE_LINE_WIDTH"
        components.update((g["label"], g) for g in added)
        box = expanded
    return {
        "bbox_xyxy_px": box,
        "glyph_height_px": height,
        "baseline_y_px": baseline,
        "anchors": row,
        "anchor_ids": [a["id"] for a in row],
        "source_components": list(components.values()),
        "source_component_labels": sorted(components),
        "context_support": sum(a["modal_support"] for a in row),
        "proposal_is_source_layout_not_confirmed_string": True,
    }, None


def _enclosed_line(region, glyphs, roi):
    inner = region["enclosure"]["bbox_xyxy_px"]
    if not base._inside(inner, roi):
        return None, "ENCLOSED_INTERIOR_CROSSES_REQUESTED_ROI"
    source = [g for g in glyphs if base._inside(g["bbox_xyxy_px"], inner)]
    if len(source) < POLICY["minimum_source_components_for_domain"]:
        return None, "ENCLOSED_INTERIOR_HAS_NO_SUPPORTED_SOURCE_ROW"
    h = _median([g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1] for g in source])
    baseline = _median([g["bbox_xyxy_px"][3] for g in source])
    if any(abs(g["bbox_xyxy_px"][3] - baseline) > 0.35 * h for g in source):
        return None, "ENCLOSED_INTERIOR_HAS_MULTIPLE_SOURCE_ROWS"
    return {
        "bbox_xyxy_px": base._box_union([g["bbox_xyxy_px"] for g in source]),
        "glyph_height_px": h,
        "baseline_y_px": baseline,
        "anchors": [],
        "anchor_ids": [],
        "context_support": 0,
        "source_components": source,
        "source_component_labels": [g["label"] for g in source],
        "enclosed_source_interior": list(inner),
        "source_frame_kept_outside_text_input": True,
        "proposal_is_source_layout_not_confirmed_string": True,
    }, None


def _pollution(region, line):
    # A clean discovery box does not imply that later OCR kept a clean scope.
    # Rank repair by the actual current word/inspection domain as well.
    old = base._box_union(
        [
            region["bbox_xyxy_px"],
            region.get("inspection_bbox_xyxy_px", region["bbox_xyxy_px"]),
        ]
    )
    good = line["bbox_xyxy_px"]
    h = line["glyph_height_px"]
    excess = {
        "left": max(0, good[0] - old[0]),
        "top": max(0, good[1] - old[1]),
        "right": max(0, old[2] - good[2]),
        "bottom": max(0, old[3] - good[3]),
    }
    margin = max(2.0, POLICY["pollution_minimum_glyph_heights"] * h)
    reasons = []
    if (
        excess["top"] > margin
        or excess["bottom"] > margin
        or old[3] - old[1] > 1.25 * h
    ):
        reasons.append("DISCOVERY_BOX_INCLUDES_OTHER_HEIGHT_OR_ROW")
    if excess["left"] > margin:
        reasons.append("DISCOVERY_BOX_INCLUDES_UNSUPPORTED_LEFT_CONTEXT")
    if excess["right"] > margin:
        reasons.append("DISCOVERY_BOX_INCLUDES_UNSUPPORTED_RIGHT_CONTEXT")
    outside_tokens = []
    for alternative in region.get("completeness_evidence", {}).get("alternatives", []):
        for word in alternative.get("all_words", alternative.get("words", [])):
            b = word["bbox_xyxy_px"]
            if (
                not any(ch.isalnum() for ch in word["text"])
                and word["confidence"] < POLICY["word_confidence"]
                and (b[0] > good[2] + 0.5 * h or b[2] < good[0] - 0.5 * h)
            ):
                outside_tokens.append(
                    {
                        "text": word["text"],
                        "bbox_xyxy_px": b,
                        "context_id": alternative.get("context_id"),
                    }
                )
    if outside_tokens:
        reasons.append("LOCAL_CONTEXT_INCLUDES_DISTANT_UNCERTAIN_PUNCTUATION_OR_RULE")
    score = (
        2.0 * (excess["top"] + excess["bottom"]) + excess["left"] + excess["right"]
    ) / max(1.0, h)
    if outside_tokens:
        score += 0.25
    return {
        "eligible": bool(reasons),
        "reasons": reasons,
        "excess_px": excess,
        "minimum_domain_excess_px": margin,
        "score": score,
        "outside_uncertain_tokens": outside_tokens,
        "not_a_transcription_confidence_retry": True,
    }


def _separate_external_component_context(
    image, line, roi, domain, labels, component_slices
):
    """Use real white separation to keep long neighboring ink out of OCR.

    Compact unknown prefix/suffix components are never discarded. A neighboring
    component may leave the text input only when it does not touch any of the
    row's real support components, extends well beyond the row, and is separated
    by original white columns. Its source pixels remain in the drawing and in
    an explicit external-context ledger. This does not recognize any character.
    """
    import numpy as np

    core = list(line["bbox_xyxy_px"])
    box = list(domain["bbox_xyxy_px"])
    glyph_ids = set(line.get("source_component_labels", []))
    if len(glyph_ids) < POLICY["minimum_source_components_for_domain"]:
        return domain
    height = float(line["glyph_height_px"])
    margin = int(POLICY["source_margin_px"])
    x0, y0, x1, y1 = box
    local = labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]]
    core_labels = labels[
        core[1] - roi[1] : core[3] - roi[1], core[0] - roi[0] : core[2] - roi[0]
    ]
    crossing = []
    for label in np.unique(local):
        label = int(label)
        if not label or label in glyph_ids or np.any(core_labels == label):
            continue
        sl = component_slices[label - 1]
        if sl is None:
            raise ValueError("NEIGHBOR_SOURCE_COMPONENT_HAS_NO_GEOMETRY")
        sy, sx = sl
        source_box = [
            sx.start + roi[0],
            sy.start + roi[1],
            sx.stop + roi[0],
            sy.stop + roi[1],
        ]
        # A nearby punctuation mark/short suffix cannot satisfy this external
        # continuation test simply by being absent from a glyph heuristic.
        if not (
            source_box[3] - source_box[1]
            > max(base.POLICY["maximum_glyph_height"], 4 * height)
            and (source_box[1] < core[1] - height or source_box[3] > core[3] + height)
        ):
            continue
        ys, xs = np.nonzero(local == label)
        if not len(xs):
            continue
        left = int(xs.min() + x0)
        right = int(xs.max() + x0 + 1)
        crossing.append(
            {
                "label": label,
                "source_bbox_xyxy_px": source_box,
                "local_x0_x1": [left, right],
                "local_source_pixels": int(len(xs)),
                "independent_of_glyph_component_ids": True,
            }
        )
    if not crossing:
        return domain
    changed = []
    excluded_ids = {r["label"] for r in crossing}
    for side, start, end, cut in [
        ("left", x0, core[0], core[0] - margin),
        ("right", core[2], x1, core[2] + margin),
    ]:
        if end <= start:
            continue
        area = labels[y0 - roi[1] : y1 - roi[1], start - roi[0] : end - roi[0]]
        present = {int(v) for v in np.unique(area) if v}
        if not present or not present <= excluded_ids:
            continue
        yy, xx = np.nonzero(area)
        actual_x = xx + start
        white_columns = (
            core[0] - int(actual_x.max()) - 1
            if side == "left"
            else int(actual_x.min()) - core[2]
        )
        if white_columns < 2 * margin:
            continue
        if side == "left":
            box[0] = max(roi[0], cut)
        else:
            box[2] = min(roi[2], cut)
        changed.append(
            {
                "side": side,
                "external_component_ids": sorted(present),
                "original_white_separator_columns": white_columns,
                "crop_boundary_px": cut,
                "excluded_from_OCR_only": True,
                "source_or_neighbor_pixels_erased": False,
            }
        )
    if not changed:
        return domain
    result = {
        **domain,
        "bbox_xyxy_px": box,
        "kind": "complete_compact_glyph_row_separated_from_external_connected_graphics",
        "glyph_neighbor_separation": {
            "version": "unchanged_source_components_and_white_separation_v1",
            "previous_unmodified_context_box": domain["bbox_xyxy_px"],
            "glyph_core_box": core,
            "glyph_support_component_ids": sorted(glyph_ids),
            "external_continuations": crossing,
            "side_decisions": changed,
            "unknown_small_prefix_suffix_retained": True,
            "original_white_gap_search_threshold_unchanged": True,
            "transcription_decision": False,
        },
    }
    for row in changed:
        key = (
            "bounded_prefix_scan_has_no_white_stop"
            if row["side"] == "left"
            else "bounded_scan_has_no_white_stop"
        )
        result[key] = False
    return result


def _line_domain(image, line, roi, *, labels=None, component_slices=None):

    box = line["bbox_xyxy_px"]
    h = line["glyph_height_px"]
    margin = POLICY["source_margin_px"]
    if line.get("enclosed_source_interior"):
        return {
            "bbox_xyxy_px": list(line["enclosed_source_interior"]),
            "anchor_bbox_xyxy_px": list(box),
            "glyph_height_px": h,
            "baseline_y_px": line["baseline_y_px"],
            "kind": "complete_measured_enclosure_interior",
            "crop_crosses_roi": not base._inside(line["enclosed_source_interior"], roi),
            "bounded_scan_has_no_white_stop": False,
            "bounded_prefix_scan_has_no_white_stop": False,
            "source_pixels_modified": False,
            "external_white_padding_px": 0,
            "original_enclosing_frame_not_erased": True,
        }
    y0, y1 = max(roi[1], box[1] - margin), min(roi[3], box[3] + margin)
    left_cap = max(
        roi[0],
        int(math.floor(box[0] - POLICY["suffix_scan_maximum_glyph_heights"] * h)),
    )
    prefix_counts = (
        (image[y0:y1, left_cap : box[0]] < POLICY["source_threshold"])
        .sum(axis=0)
        .astype(int)
    )
    start = box[2]
    cap = min(
        roi[2], int(math.ceil(start + POLICY["suffix_scan_maximum_glyph_heights"] * h))
    )
    source_band = image[y0:y1, start:cap] < POLICY["source_threshold"]
    black_counts = source_band.sum(axis=0).astype(int)
    white_needed = max(
        2, int(math.ceil(POLICY["stopping_white_gap_glyph_heights"] * h))
    )
    left_stop, left_run = None, 0
    for offset, count in enumerate(prefix_counts[::-1].tolist()):
        left_run = left_run + 1 if count == 0 else 0
        if left_run >= white_needed:
            left_stop = box[0] - offset + left_run - 1
            break
    left = left_cap if left_stop is None else max(left_cap, left_stop - margin)
    left = min(max(roi[0], box[0] - margin), left)
    stop, run = None, 0
    for column, count in enumerate(black_counts.tolist()):
        run = run + 1 if count == 0 else 0
        if run >= white_needed:
            stop = start + column - run + 1
            break
    if stop is None:
        right = cap
    else:
        right = min(cap, stop + margin)
    # Always retain every chosen anchor sample and two original-paper pixels
    # where available.  No foreground mask is used to alter the crop.
    right = max(min(roi[2], start + margin), right)
    crop = [left, y0, right, y1]
    result = {
        "bbox_xyxy_px": crop,
        "anchor_bbox_xyxy_px": list(box),
        "glyph_height_px": h,
        "baseline_y_px": line["baseline_y_px"],
        "source_margin_px": margin,
        "suffix_scan_x0_x1": [start, cap],
        "kind": "source_component_row_with_bidirectional_unmodified_context",
        "prefix_scan_x0_x1": [left_cap, box[0]],
        "prefix_source_black_counts_by_column": prefix_counts.tolist(),
        "first_sufficient_prefix_white_gap_end_x": left_stop,
        "bounded_prefix_scan_has_no_white_stop": left_stop is None,
        "suffix_scan_y0_y1": [y0, y1],
        "suffix_source_black_counts_by_column": black_counts.tolist(),
        "required_actual_white_gap_columns": white_needed,
        "first_sufficient_white_gap_start_x": stop,
        "bounded_scan_has_no_white_stop": stop is None,
        "crop_crosses_roi": not base._inside(crop, roi),
        "source_pixels_modified": False,
        "external_white_padding_px": 0,
        "right_lookahead_can_include_connected_suffix_and_original_rules": True,
    }
    if labels is not None:
        if component_slices is None:
            from scipy.ndimage import find_objects

            component_slices = find_objects(labels)
        result = _separate_external_component_context(
            image, line, roi, result, labels, component_slices
        )
    return result


class ScopeObservationEvidence:
    """Keep full raw words once and use hash-bound references in scope decisions.

    Paths are relative to the task evidence root (the parent of a stage
    directory), not to a region's current stage. A later stage can therefore
    deepcopy a decision without rebasing or invalidating its evidence path.
    """

    def __init__(self, output):
        self.output = Path(output)
        self.references = {}

    def register(self, words, *, existing_path=None):
        digests = [_digest(word) for word in words]
        if all(digest in self.references for digest in digests):
            return
        if existing_path is None:
            path = (
                self.output / "scope_observation_ledgers" / (_digest(words) + ".json")
            )
            if not path.exists():
                base._dump(path, words)
        else:
            path = Path(existing_path)
        if _digest(json.loads(path.read_text())) != _digest(words):
            raise ValueError("SOURCE_SCOPE_OBSERVATION_LEDGER_CONTENT_MISMATCH")
        relative = path.resolve().relative_to(self.output.parent.resolve())
        ledger_hash = base._sha(path)
        for index, digest in enumerate(digests):
            self.references.setdefault(
                digest,
                {
                    "path": relative.as_posix(),
                    "relative_to": "task_evidence_root",
                    "sha256": ledger_hash,
                    "word_index_zero_based": index,
                    "word_sha256": digest,
                    "ledger_word_count": len(words),
                },
            )

    def reference(self, word):
        digest = _digest(word)
        if digest not in self.references:
            raise ValueError("SOURCE_SCOPE_RAW_WORD_HAS_NO_SAVED_LEDGER")
        return dict(self.references[digest])


def read_scope_observation(evidence_root, reference):
    """Cold-read an excluded raw word, verifying its ledger and value hashes."""
    if reference.get("relative_to") != "task_evidence_root":
        raise ValueError("SOURCE_SCOPE_OBSERVATION_REFERENCE_ROOT_INVALID")
    root = Path(evidence_root).resolve()
    path = (root / reference["path"]).resolve()
    path.relative_to(root)
    if base._sha(path) != reference["sha256"]:
        raise ValueError("SOURCE_SCOPE_OBSERVATION_LEDGER_HASH_MISMATCH")
    words = json.loads(path.read_text())
    if len(words) != reference["ledger_word_count"]:
        raise ValueError("SOURCE_SCOPE_OBSERVATION_LEDGER_COUNT_MISMATCH")
    index = reference["word_index_zero_based"]
    if type(index) is not int or not 0 <= index < len(words):
        raise ValueError("SOURCE_SCOPE_RAW_WORD_INDEX_INVALID")
    word = words[index]
    if _digest(word) != reference["word_sha256"]:
        raise ValueError("SOURCE_SCOPE_RAW_WORD_HASH_MISMATCH")
    return word


def scope_words_to_source_domain(words, domain, labels, roi, *, evidence=None):
    """Separate raw observations applicable to the selected source object.

    Raw words are not edited; a word whose box mixes the external component
    with glyphs remains an explicit incompatible observation. This cannot
    turn that word into a desired shorter string or discard an unknown suffix.
    """
    import numpy as np

    separation = domain.get("glyph_neighbor_separation")
    if not separation:
        return list(words), []
    external = {row["label"] for row in separation["external_continuations"]}
    kept = []
    rejected = []
    box = domain["bbox_xyxy_px"]
    for word in words:
        wb = word["bbox_xyxy_px"]
        xa, ya, xb, yb = (
            max(roi[0], wb[0]),
            max(roi[1], wb[1]),
            min(roi[2], wb[2]),
            min(roi[3], wb[3]),
        )
        inside = base._inside(wb, box)
        local = labels[
            max(0, ya - roi[1]) : max(0, yb - roi[1]),
            max(0, xa - roi[0]) : max(0, xb - roi[0]),
        ]
        ids = {int(v) for v in np.unique(local) if v}
        mixed = sorted(ids & external)
        if inside and ids and not mixed:
            kept.append(word)
        else:
            raw_word = (
                {
                    key: copy.deepcopy(word[key])
                    for key in (
                        "id",
                        "text",
                        "bbox_xyxy_px",
                        "confidence",
                        "context_id",
                        "psm",
                        "observation_key",
                    )
                    if key in word
                }
                if evidence is not None
                else copy.deepcopy(word)
            )
            rejection = {
                "raw_word": raw_word,
                "word_inside_current_source_domain": inside,
                "external_component_ids_in_word_box": mixed,
                "source_component_ids": sorted(ids),
                "reason": "OBSERVATION_REFERS_TO_DIFFERENT_OR_MIXED_SOURCE_SCOPE",
                "raw_word_or_original_source_modified": False,
            }
            if evidence is not None:
                rejection["raw_word_reference"] = evidence.reference(word)
            rejected.append(rejection)
    return kept, rejected


def _unread_boundary_ink(image, region, domain):
    import numpy as np

    x0, y0, x1, y1 = domain["bbox_xyxy_px"]
    if not region["words"]:
        return {
            "whole_domain_unread": True,
            "left_pixels": None,
            "right_pixels": None,
            "runs_y_x0_x1": [],
        }, ["NO_CURRENT_LOCAL_TRANSCRIPTION"]
    box = base._box_union([w["bbox_xyxy_px"] for w in region["words"]])
    mask = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    original = image[y0:y1, x0:x1] < POLICY["source_threshold"]
    left_end = min(x1, max(x0, box[0])) - x0
    right_start = min(x1, max(x0, box[2])) - x0
    if left_end:
        mask[:, :left_end] = original[:, :left_end]
    if right_start < x1 - x0:
        mask[:, right_start:] = original[:, right_start:]
    left_count = int(mask[:, :left_end].sum())
    right_count = int(mask[:, right_start:].sum())
    reasons = []
    if left_count:
        reasons.append("UNREAD_OR_SHARED_SOURCE_INK_BEFORE_RECOGNISED_LINE")
    if right_count:
        reasons.append("UNREAD_OR_SHARED_SOURCE_INK_AFTER_RECOGNISED_LINE")
    if domain["bounded_scan_has_no_white_stop"]:
        reasons.append("BOUNDED_SUFFIX_SCAN_REACHES_CAP_WITHOUT_SOURCE_WHITE_STOP")
    if domain.get("bounded_prefix_scan_has_no_white_stop"):
        reasons.append("BOUNDED_PREFIX_SCAN_REACHES_CAP_WITHOUT_SOURCE_WHITE_STOP")
    return {
        "whole_domain_unread": False,
        "left_pixels": left_count,
        "right_pixels": right_count,
        "runs_y_x0_x1": base._rle(mask, (x0, y0)),
        "connected_rule_or_suffix_not_semantically_assigned": True,
    }, reasons


def _domain_component_continuations(labels, slices, domain, roi):
    """Record source components crossing the actual proposed crop, not boxes.

    A crossing may be a character or a connected graphic. Neither is erased or
    semantically declared to belong to text to make recognition pass.
    """
    import numpy as np

    x0, y0, x1, y1 = domain["bbox_xyxy_px"]
    if not base._inside([x0, y0, x1, y1], roi):
        return {"crop_outside_ROI": True, "continuing_components": []}
    local = labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]]
    result = []
    for label in np.unique(local):
        if not label:
            continue
        source_slice = slices[int(label) - 1]
        if source_slice is None:
            raise ValueError("SOURCE_COMPONENT_LABEL_HAS_NO_GEOMETRY")
        sy, sx = source_slice
        box = [sx.start + roi[0], sy.start + roi[1], sx.stop + roi[0], sy.stop + roi[1]]
        if not base._inside(box, [x0, y0, x1, y1]):
            result.append(
                {
                    "label": int(label),
                    "source_bbox_xyxy_px": box,
                    "pixels_inside_proposed_crop": int((local == label).sum()),
                    "kind": "UNASSIGNED_CHARACTER_OR_GRAPHIC_CONTINUATION",
                }
            )
    return {
        "crop_outside_ROI": False,
        "continuing_components": result,
        "source_ink_erased_or_assigned_to_dust": False,
    }


def inspect_source_domain(labels, roi, crop_xyxy_px, *, component_slices=None):
    """Public current-domain check for subsequent OCR stages.

    Pass the *current actual input crop*, never an earlier failed crop. This
    returns source geometry diagnostics and cannot adopt a transcription.
    Component labels must be the unmodified ROI labels from _component_evidence.
    """
    if tuple(labels.shape) != (roi[3] - roi[1], roi[2] - roi[0]):
        raise ValueError("SOURCE_DOMAIN_LABEL_COORDINATE_MISMATCH")
    if component_slices is None:
        from scipy.ndimage import find_objects

        component_slices = find_objects(labels)
    evidence = _domain_component_continuations(
        labels, component_slices, {"bbox_xyxy_px": list(crop_xyxy_px)}, roi
    )
    reasons = []
    if evidence["crop_outside_ROI"]:
        reasons.append("REFINED_SOURCE_DOMAIN_CROSSES_REQUESTED_ROI")
    if evidence["continuing_components"]:
        reasons.append("SOURCE_COMPONENT_CONTINUES_OUTSIDE_TEXT_DOMAIN")
    return {
        **evidence,
        "current_crop_xyxy_px": list(crop_xyxy_px),
        "source_domain_complete": not reasons,
        "unresolved_reasons": reasons,
        "historical_failure_is_not_a_current_veto": True,
        "transcription_approval": False,
    }


def _previous_geometric_groups(regions, line_metrics, previous_groups):
    """Recheck existing row groups when no new modal geometry is available.

    Missing repeated OCR anchors do not contradict an existing geometric
    group. Replay its original grouping rules on the current regions; do not
    copy previous completeness, recognition or approval decisions.
    """
    by_id = {region["id"]: region for region in regions}
    if len(by_id) != len(regions):
        raise ValueError("GROUPING_REGION_IDENTITIES_NOT_UNIQUE")
    retained, rejected, previous_members = {}, {}, set()
    for previous in previous_groups or []:
        identifiers = previous.get("region_ids", [])
        if (
            not identifiers
            or len(set(identifiers)) != len(identifiers)
            or any(identifier not in by_id for identifier in identifiers)
        ):
            raise ValueError("PREVIOUS_GEOMETRIC_GROUP_MEMBERS_INVALID")
        if previous_members.intersection(identifiers):
            raise ValueError("PREVIOUS_GEOMETRIC_GROUP_MEMBERS_OVERLAP")
        previous_members.update(identifiers)
        # Any measured modal member leaves this group on the existing path.
        if any(line_metrics.get(identifier) for identifier in identifiers):
            continue
        rows = [by_id[identifier] for identifier in identifiers]
        replay = base._groups(rows)
        replay_ids = [group["region_ids"] for group in replay]
        valid = len(replay_ids) == 1 and set(replay_ids[0]) == set(identifiers)
        evidence = {
            "previous_group_id": previous.get("id"),
            "previous_region_ids": list(identifiers),
            "new_modal_member_metrics_available": False,
            "recheck_method": "text_regions._groups_on_current_regions_with_unchanged_original_geometric_rules",
            "replayed_region_groups": replay_ids,
            "revalidation_pass": valid,
            "current_region_geometry": [
                {
                    "region_id": row["id"],
                    "bbox_xyxy_px": list(row["bbox_xyxy_px"]),
                    "has_enclosure": bool(row.get("enclosure")),
                    "has_words": bool(row["words"]),
                }
                for row in rows
            ],
            "previous_completeness_or_approval_copied": False,
            "confidence_or_source_gates_changed": False,
        }
        destination = retained if valid else rejected
        for identifier in identifiers:
            destination[identifier] = evidence
    return retained, rejected


def _regroup(regions, line_metrics, previous_groups=None):
    """Use measured anchors, or revalidated existing geometry if none exist."""
    retained, rejected = _previous_geometric_groups(
        regions, line_metrics, previous_groups
    )
    by_id = {region["id"]: region for region in regions}
    used, groups = set(), []
    ordered = sorted(
        regions, key=lambda r: (r["bbox_xyxy_px"][1], r["bbox_xyxy_px"][0], r["id"])
    )
    for region in ordered:
        if region["id"] in used:
            continue
        chain = [region]
        first_metric = line_metrics.get(region["id"])
        prior_geometry = retained.get(region["id"])
        if prior_geometry:
            chain = [
                by_id[identifier]
                for identifier in prior_geometry["replayed_region_groups"][0]
            ]
        elif first_metric and not region.get("enclosure") and region["words"]:
            first_box = first_metric["bbox_xyxy_px"]
            height = first_metric["glyph_height_px"]
            current_metric = first_metric
            for _ in range(POLICY["maximum_paragraph_lines"] - 1):
                possible = []
                for nxt in ordered:
                    metric = line_metrics.get(nxt["id"])
                    if (
                        nxt["id"] in used
                        or nxt in chain
                        or not metric
                        or nxt.get("enclosure")
                        or not nxt["words"]
                    ):
                        continue
                    b = metric["bbox_xyxy_px"]
                    nh = metric["glyph_height_px"]
                    gap = b[1] - current_metric["bbox_xyxy_px"][3]
                    ratio = max(height, nh) / min(height, nh)
                    align = min(
                        abs(b[0] - first_box[0]),
                        abs((b[0] + b[2] - first_box[0] - first_box[2]) / 2),
                    )
                    if (
                        0
                        <= gap
                        <= POLICY["paragraph_maximum_gap_glyph_heights"]
                        * max(height, nh)
                        and ratio <= POLICY["paragraph_height_ratio_maximum"]
                        and align
                        <= POLICY["paragraph_alignment_glyph_heights"] * max(height, nh)
                    ):
                        possible.append((gap, align, nxt["id"], nxt, metric))
                if not possible:
                    break
                _, _, _, nxt, current_metric = min(possible, key=lambda item: item[:3])
                chain.append(nxt)
        used.update(r["id"] for r in chain)
        text = "\n".join(r["text"] for r in chain)
        region_ids = [r["id"] for r in chain]
        groups.append(
            {
                "id": "TGD-" + _digest(region_ids)[:12],
                "geometry_type": "MTEXT" if len(chain) > 1 else "TEXT",
                "kind": (
                    (
                        "multiline_preserved_geometric_group"
                        if prior_geometry
                        else "multiline_modal_anchor_group"
                    )
                    if len(chain) > 1
                    else "enclosed_label"
                    if region.get("enclosure")
                    else "single_line"
                ),
                "bbox_xyxy_px": base._box_union([r["bbox_xyxy_px"] for r in chain]),
                "region_ids": region_ids,
                "lines": [
                    {
                        "region_id": r["id"],
                        "text": r["text"],
                        "bbox_xyxy_px": r["bbox_xyxy_px"],
                        "complete": r["complete"],
                        "word_ids": [w["id"] for w in r["words"]],
                    }
                    for r in chain
                ],
                "text": text,
                "complete": all(r["complete"] for r in chain),
                "source_review_required": True,
                "unresolved_reasons": sorted(
                    {reason for r in chain for reason in r["unresolved_reasons"]}
                ),
                "enclosure": region.get("enclosure"),
                "numeric_label": len(chain) == 1 and bool(text) and text.isdigit(),
                "grouping_is_semantic_proof": False,
                "automatic_formal_adoption": False,
                "grouping_evidence": {
                    "method": "shared_repeated_anchor_height_baseline_and_column",
                    "region_anchor_metrics": {
                        r["id"]: line_metrics.get(r["id"]) for r in chain
                    },
                    "no_answer_or_test_case_coordinates_used": True,
                },
            }
        )
        if prior_geometry:
            groups[-1]["grouping_evidence"].update(
                method="revalidated_previous_geometric_group_without_new_modal_anchors",
                previous_geometric_group=prior_geometry,
            )
        elif any(row["id"] in rejected for row in chain):
            groups[-1]["grouping_evidence"]["previous_geometric_group_rejections"] = [
                rejected[row["id"]] for row in chain if row["id"] in rejected
            ]
    claimed = [identifier for group in groups for identifier in group["region_ids"]]
    if len(claimed) != len(regions) or set(claimed) != set(by_id):
        raise ValueError("GROUPING_REGION_ACCOUNTING_NOT_EXACTLY_ONCE")
    if len({group["id"] for group in groups}) != len(groups):
        raise ValueError("GROUPING_IDENTITIES_COLLIDE")
    return groups


def _verify_inputs(image, text_data, provenance):
    required = (
        "source_path",
        "source_sha256",
        "text_path",
        "text_sha256",
        "producer_sha256",
        "manifest_path",
        "manifest_sha256",
    )
    if not isinstance(provenance, dict) or any(
        key not in provenance for key in required
    ):
        raise ValueError("EXPLICIT_UPSTREAM_PROVENANCE_REQUIRED")
    for key, hash_key in (
        ("source_path", "source_sha256"),
        ("text_path", "text_sha256"),
        ("manifest_path", "manifest_sha256"),
    ):
        if base._sha(provenance[key]) != provenance[hash_key]:
            raise ValueError("UPSTREAM_FILE_HASH_MISMATCH:" + key)
    if base._sha(base.__file__) != provenance["producer_sha256"]:
        raise ValueError("UPSTREAM_TEXT_PRODUCER_CHANGED")
    original = json.loads(Path(provenance["text_path"]).read_text())
    if _digest(original) != _digest(text_data):
        raise ValueError("PASSED_TEXT_DATA_DIFFERS_FROM_SAVED_UPSTREAM")
    roi = list(text_data["roi_xyxy_px"])
    validate_text_regions(text_data, image.shape, roi)
    if text_data.get("source_array_sha256") != base.source_array_sha256(image):
        raise ValueError("TEXT_SOURCE_GRAY_SAMPLES_MISMATCH")
    manifest = json.loads(Path(provenance["manifest_path"]).read_text())
    if (
        manifest.get("source_sha256") != provenance["source_sha256"]
        or manifest.get("roi_xyxy_px") != roi
    ):
        raise ValueError("UPSTREAM_MANIFEST_SOURCE_OR_ROI_MISMATCH")
    if (
        manifest["text"]["sha256"] != provenance["text_sha256"]
        or manifest["text"]["producer_sha256"] != provenance["producer_sha256"]
    ):
        raise ValueError("UPSTREAM_MANIFEST_PRODUCER_OR_TEXT_MISMATCH")
    return roi


@profiled("text_line_domains.refine_text_line_domains")
def refine_text_line_domains(
    image_gray_native,
    text_data,
    output_dir,
    *,
    cache_dir,
    upstream_provenance,
    progress_callback=None,
    dpi=200,
):
    """Return a full new text contract; the old result remains immutable.

    upstream_provenance identifies the actual saved upstream JSON, producer,
    completion manifest, and encoded source file.  No implicit old path exists.
    The generated completed_stages.json declares this module's producer hash
    and the frozen text_regions dependency hash for a verified continuation.
    """
    import numpy as np
    import cv2
    from PIL import Image

    start, cpu_start = time.perf_counter(), time.process_time()
    image = np.asarray(image_gray_native)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise TypeError("FULL_NATIVE_UINT8_GRAY_IMAGE_REQUIRED")
    roi = _verify_inputs(image, text_data, upstream_provenance)
    source_hash = base.source_array_sha256(image)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            "REFINEMENT_REQUIRES_FRESH_EVIDENCE_DIRECTORY:" + str(output)
        )
    output.mkdir(parents=True, exist_ok=True)
    # Keep the fresh-directory guard intact. Only after it has passed may
    # the execution context restore hashed passes from this same task.
    from .execution import restore_partial_ocr

    restore_partial_ocr(output, source_subdir="text_domain_recovery")
    code_hash = base._sha(__file__)
    base._dump(
        output / "policy_frozen_before_recognition.json",
        {
            "policy": POLICY,
            "producer_module": __name__,
            "producer_sha256": code_hash,
            "source_array_sha256": source_hash,
            "upstream_provenance": upstream_provenance,
            "base_producer_sha256": base._sha(base.__file__),
            "source_cases_or_expected_answers_read": False,
        },
    )
    cv2.setNumThreads(1)
    _, labels, glyphs = base._component_evidence(image, roi)
    from scipy.ndimage import find_objects

    source_slices = find_objects(labels)
    observations, collection = _collect_current_observations(
        image, text_data, cache_dir, upstream_provenance, output
    )
    cache_evidence = collection["cache"]
    anchors = _anchors(observations, glyphs)
    base._dump(output / "current_observation_collection.json", collection)
    base._dump(output / "current_observations.json", observations)
    scope_evidence = ScopeObservationEvidence(output)
    scope_evidence.register(
        observations, existing_path=output / "current_observations.json"
    )
    line_metrics, decisions = {}, []
    for region in text_data["regions"]:
        if region.get("enclosure"):
            line, reason = _enclosed_line(region, glyphs, roi)
        else:
            line, reason = _anchor_line(region, anchors, glyphs)
        if line and reason is None:
            line_metrics[region["id"]] = line
        row = {
            "region_id": region["id"],
            "old_text": region["text"],
            "old_complete": region["complete"],
            "old_discovery_bbox_xyxy_px": region.get(
                "discovery_bbox_xyxy_px", region["bbox_xyxy_px"]
            ),
            "old_inspection_bbox_xyxy_px": region.get("inspection_bbox_xyxy_px"),
            "anchor_line": line,
            "eligible": False,
        }
        if region["complete"]:
            row["not_attempted_reason"] = "ALREADY_COMPLETE_NO_RECOGNITION_RETRY"
        elif not base._inside(row["old_discovery_bbox_xyxy_px"], roi):
            row["not_attempted_reason"] = "SOURCE_SEED_CROSSES_REQUESTED_ROI"
        elif reason:
            row["not_attempted_reason"] = reason
        else:
            pollution = _pollution(region, line)
            row["pollution"] = pollution
            row["domain"] = _line_domain(
                image, line, roi, labels=labels, component_slices=source_slices
            )
            row["fixed_psm"] = list(
                POLICY["enclosed_PSM"] if region.get("enclosure") else POLICY["PSM"]
            )
            row["proposal_evidence"] = {
                "method": "complete_source_enclosure_interior"
                if region.get("enclosure")
                else "current_observation_and_source_component_row",
                "source_component_labels": line["source_component_labels"],
                "current_context_support": line["context_support"],
                "domain_before_transcription_confirmation": True,
                "original_unresolved_reasons": region["unresolved_reasons"],
                "confidence_thresholds_not_relaxed": True,
            }
            row["eligible"] = True
            row["entry_reason"] = (
                "UNRESOLVED_MEASURED_ENCLOSURE_FULL_INTERIOR"
                if region.get("enclosure")
                else "UNRESOLVED_SOURCE_SUPPORTED_LINE_DOMAIN"
            )
            row["domain_source_continuations"] = inspect_source_domain(
                labels,
                roi,
                row["domain"]["bbox_xyxy_px"],
                component_slices=source_slices,
            )
        decisions.append(row)
    ranked = sorted(
        (row for row in decisions if row["eligible"]),
        key=lambda row: (
            -row["pollution"]["score"],
            -row["anchor_line"]["context_support"],
            row["region_id"],
        ),
    )
    selected, actual_domains = [], {}
    for row in ranked:
        identity = (tuple(row["domain"]["bbox_xyxy_px"]), tuple(row["fixed_psm"]))
        if identity in actual_domains:
            row["not_attempted_reason"] = (
                "SAME_SOURCE_DOMAIN_AND_CONFIGURATION_ALREADY_SELECTED"
            )
            row["shared_domain_primary_region"] = actual_domains[identity]
        elif len(selected) >= POLICY["maximum_regions"]:
            row["not_attempted_reason"] = "FIXED_24_REGION_BUDGET"
        else:
            actual_domains[identity] = row["region_id"]
            selected.append(row)
    selected_ids = {row["region_id"] for row in selected}
    base._dump(output / "anchor_box_modes.json", anchors)
    base._dump(
        output / "selection.json",
        {
            "selection_policy": POLICY,
            "all_region_decisions": decisions,
            "eligible_regions": len(ranked),
            "selected_region_ids": [r["region_id"] for r in selected],
            "planned_current_OCR_calls": len(selected) * 2,
        },
    )
    result = copy.deepcopy(text_data)
    by_id = {r["id"]: r for r in result["regions"]}
    passes, recoveries = [], []
    if progress_callback:
        progress_callback(
            {
                "stage": "modal_line_domain_selection",
                "eligible": len(ranked),
                "selected": len(selected),
                "planned_OCR_calls": len(selected) * 2,
            }
        )
    for number, decision in enumerate(selected, 1):
        rid = decision["region_id"]
        old = copy.deepcopy(by_id[rid])
        line, domain = decision["anchor_line"], decision["domain"]
        # Historical failures remain reviewable, but do not masquerade as a
        # current crop/source boundary witness. R1 owns the acceptance policy.
        alternatives = []
        original_root = Path(
            upstream_provenance.get(
                "text_evidence_dir", Path(upstream_provenance["text_path"]).parent
            )
        )
        for previous in old.get("completeness_evidence", {}).get("alternatives", []):
            historical = copy.deepcopy(previous)
            historical["evidence_role"] = "historical_diagnostic"
            raw = (original_root / previous["raw_tsv"]).resolve()
            historical["raw_tsv"] = relative_evidence_path(raw, output)
            historical["raw_artifact"] = {
                "path": relative_evidence_path(raw, output),
                "sha256": base._sha(raw),
                "status": "SAVED_RAW_TSV",
            }
            alternatives.append(historical)
        x0, y0, x1, y1 = domain["bbox_xyxy_px"]
        Image.fromarray(image[y0:y1, x0:x1]).save(output / (rid + "_new_domain.png"))
        old_box = old.get("inspection_bbox_xyxy_px", old["bbox_xyxy_px"])
        a, b, c, d = base._clip(old_box, image.shape)
        Image.fromarray(image[b:d, a:c]).save(output / (rid + "_old_domain.png"))
        for psm in decision["fixed_psm"]:
            name = rid + "-source-domain-p" + str(psm)
            words, meta = base._ocr(
                image,
                domain["bbox_xyxy_px"],
                psm,
                output / "local_ocr",
                name,
                progress_callback,
                padding_px=0,
                dpi=dpi,
            )
            passes.append({"region_id": rid, **meta})
            alternatives.append(
                {
                    "context_id": name,
                    "psm": psm,
                    "crop_xyxy_px": domain["bbox_xyxy_px"],
                    "status": meta["status"],
                    "raw_tsv": "local_ocr/" + name + ".tsv",
                    "external_white_padding_px": 0,
                    "evidence_role": "current_candidate",
                    "observation_key": base.raw_observation_key(meta),
                    "observation_provenance": {
                        **base.raw_observation_provenance(meta),
                        "source_identity": collection["source_identity"],
                        "specification": meta["specification"],
                        "raw_tsv": "local_ocr/" + name + ".tsv",
                        "raw_tsv_sha256": meta["tsv_sha256"],
                    },
                    "raw_artifact": {
                        "path": "local_ocr/" + name + ".tsv",
                        "sha256": meta["tsv_sha256"],
                        "status": "SAVED_RAW_TSV",
                    },
                    "all_words": words,
                    "words": base._select_line(words, line["bbox_xyxy_px"]),
                }
            )
        seed = {
            "id": rid,
            "bbox_xyxy_px": line["bbox_xyxy_px"],
            "origin": "current_source_component_line_domain",
            "seed_observation_ids": sorted(
                {
                    oid
                    for anchor in line["anchors"]
                    for oid in anchor["all_observation_ids"]
                }
            ),
            "glyph_labels": line["source_component_labels"],
            "enclosure": copy.deepcopy(old.get("enclosure")),
            "discovery_strings": sorted(
                {
                    s
                    for anchor in line["anchors"]
                    for s in anchor["raw_text_alternatives"]
                }
            ),
        }
        applicable_observations = observations
        scope_exclusions = []
        if domain.get("glyph_neighbor_separation"):
            applicable_observations, scope_exclusions = scope_words_to_source_domain(
                observations, domain, labels, roi, evidence=scope_evidence
            )
            for alternative in alternatives:
                scope_evidence.register(alternative["words"])
                applicable_words, excluded = scope_words_to_source_domain(
                    alternative["words"],
                    domain,
                    labels,
                    roi,
                    evidence=scope_evidence,
                )
                alternative["words"] = applicable_words
                alternative["source_scope_excluded_raw_words"] = excluded
            seed["discovery_strings"] = sorted(
                {
                    w["text"]
                    for w in applicable_observations
                    if base._intersection(w["bbox_xyxy_px"], line["bbox_xyxy_px"])
                }
            )
        new = base._complete_region(
            seed, alternatives, applicable_observations, image, roi, glyphs, labels
        )
        unread, reasons = _unread_boundary_ink(image, new, domain)
        if domain["crop_crosses_roi"]:
            reasons.append("REFINED_SOURCE_DOMAIN_CROSSES_REQUESTED_ROI")
        if decision["domain_source_continuations"]["continuing_components"]:
            reasons.append("SOURCE_COMPONENT_CONTINUES_OUTSIDE_TEXT_DOMAIN")
        if reasons:
            new["unresolved_reasons"] = sorted(set(new["unresolved_reasons"] + reasons))
            new["complete"] = False
            new["status"] = "UNRESOLVED_TEXT_REGION"
        new["line_domain_refinement"] = {
            "producer": __name__,
            "old_region_digest": _digest(old),
            "old_text_candidate": old["text"],
            "old_discovery_bbox_xyxy_px": old.get("discovery_bbox_xyxy_px"),
            "old_inspection_bbox_xyxy_px": old.get("inspection_bbox_xyxy_px"),
            "anchor_line": line,
            "new_domain": domain,
            "source_continuations": decision["domain_source_continuations"],
            "raw_observations_excluded_from_current_scope": scope_exclusions,
            "unread_or_shared_boundary_ink": unread,
            "discarded_crop_context_is_unassigned_source_not_dust": True,
        }
        # Preserve all old compact unknown-ink evidence in an explicit context
        # record, even when the narrower text domain no longer includes it.
        new["retained_unassigned_old_context"] = {
            "bbox_xyxy_px": old.get("inspection_bbox_xyxy_px", old["bbox_xyxy_px"]),
            "compact_source_ink_mask": old["compact_source_ink_mask"],
            "meaning": "prior ambiguous context remains source/repair evidence, not recognised text and not erased",
        }
        by_id[rid].clear()
        by_id[rid].update(new)
        recovery = {
            "region_id": rid,
            "old": old,
            "new": new,
            "domain_selection": decision,
            "source_transcription_hand_corrected": False,
            "old_complete": old["complete"],
            "new_complete": new["complete"],
            "old_text": old["text"],
            "new_text": new["text"],
        }
        recoveries.append(recovery)
        base._dump(output / "region_recoveries" / (rid + ".json"), recovery)
        if progress_callback:
            progress_callback(
                {
                    "stage": "modal_line_domain_complete",
                    "region_id": rid,
                    "completed": number,
                    "total": len(selected),
                    "text": new["text"],
                    "complete": new["complete"],
                }
            )

    result["groups"] = _regroup(result["regions"], line_metrics, text_data["groups"])
    result["uncertainties"] = [
        {
            "region_id": r["id"],
            "bbox_xyxy_px": r["bbox_xyxy_px"],
            "text": r["text"],
            "reasons": r["unresolved_reasons"],
        }
        for r in result["regions"]
        if not r["complete"]
    ]
    unchanged = [
        {"region_id": a["id"], "unchanged": _digest(a) == _digest(by_id[a["id"]])}
        for a in text_data["regions"]
        if a["id"] not in selected_ids
    ]
    if not all(row["unchanged"] for row in unchanged):
        raise RuntimeError("NONSELECTED_TEXT_REGION_CHANGED")
    if base.source_array_sha256(image) != source_hash:
        raise RuntimeError("SOURCE_GRAY_MODIFIED_DURING_REFINEMENT")
    if (
        base._sha(upstream_provenance["text_path"])
        != upstream_provenance["text_sha256"]
    ):
        raise RuntimeError("FROZEN_UPSTREAM_RESULT_CHANGED")
    combined = np.zeros((roi[3] - roi[1], roi[2] - roi[0]), dtype=np.uint8)
    for region in result["regions"]:
        masks = [region["compact_source_ink_mask"]]
        if region.get("retained_unassigned_old_context"):
            masks.append(
                region["retained_unassigned_old_context"]["compact_source_ink_mask"]
            )
        for mask in masks:
            for y, a, b in mask["runs_y_x0_x1"]:
                combined[y - roi[1], a - roi[0] : b - roi[0]] = 255
    Image.fromarray(combined).save(output / "compact_glyph_candidate_mask.png")
    result["bbox_overlay"] = base._overlay(image, roi, result["regions"], output)
    result["text_candidate_mask"] = {
        "path": "compact_glyph_candidate_mask.png",
        "origin_xy_px": roi[:2],
        "size_px": [roi[2] - roi[0], roi[3] - roi[1]],
        "coordinate_system": "source_pixels_top_left",
        "source_erasure_authorized": False,
        "old_unknown_context_mask_retained": True,
    }
    original_evidence = Path(
        upstream_provenance.get(
            "text_evidence_dir", Path(upstream_provenance["text_path"]).parent
        )
    )
    original_relative = relative_evidence_path(original_evidence, output)
    result["region_evidence_roots"] = {
        r["id"]: "." if r["id"] in selected_ids else original_relative
        for r in result["regions"]
    }
    resources = {
        "wall_seconds": time.perf_counter() - start,
        "process_cpu_seconds": time.process_time() - cpu_start,
        "new_local_OCR_calls": len(passes),
        "selected_regions": len(selected),
        "child_cpu_seconds": (
            sum(p["child_cpu_seconds"] for p in passes)
            if all(p["child_cpu_seconds"] is not None for p in passes)
            else None
        ),
        "passes": passes,
    }
    producer = {
        "module": __name__,
        "sha256": code_hash,
        "dependencies": [{"module": base.__name__, "sha256": base._sha(base.__file__)}],
        "upstream_provenance": upstream_provenance,
        "cache": cache_evidence,
        "source_array_sha256": source_hash,
        "source_sha256": upstream_provenance["source_sha256"],
        "source_pixels_modified": False,
        "expected_answers_or_source_cases_read": False,
    }
    result["producer"] = producer
    result["status"] = "MODAL_LINE_DOMAIN_REFINEMENT_COMPLETED_PENDING_SOURCE_REVIEW"
    result["resources"] = {
        "scope": "separately_recorded_stages_not_end_to_end_time",
        "upstream_text_stage": text_data.get("resources"),
        "modal_line_domain_stage": resources,
    }
    result["line_domain_recovery"] = {
        "policy": POLICY,
        "selected_region_ids": [row["region_id"] for row in selected],
        "all_nonselected_regions_unchanged": True,
        "groups_recomputed_from_modal_anchor_geometry": all(
            group["grouping_evidence"]["method"]
            == "shared_repeated_anchor_height_baseline_and_column"
            for group in result["groups"]
        ),
        "groups_preserved_after_original_geometry_recheck": [
            group["id"]
            for group in result["groups"]
            if group["grouping_evidence"].get("previous_geometric_group")
        ],
        "grouping_revision": "preserve_source_groups_without_new_modal_anchors_v2",
        "no_automatic_source_review_approval": True,
    }
    validate_text_regions(result, image.shape, roi)
    base._dump(output / "text_regions.json", result)
    base._dump(output / "completed_text.json", result)
    base._dump(
        output / "completed_stages.json",
        {
            "source_sha256": upstream_provenance["source_sha256"],
            "source_size_px": result["source_size_px"],
            "source_array_sha256": source_hash,
            "roi_xyxy_px": roi,
            "coordinate_system": "source_pixels_top_left",
            "text": {
                "path": "completed_text.json",
                "sha256": base._sha(output / "completed_text.json"),
                "producer_module": __name__,
                "producer_sha256": code_hash,
                "dependency_producers": producer["dependencies"],
                "upstream_text_sha256": upstream_provenance["text_sha256"],
            },
        },
    )
    summary = {
        "producer": producer,
        "policy": POLICY,
        "eligible_regions": len(ranked),
        "selected_regions": len(selected),
        "new_local_OCR_calls": len(passes),
        "recoveries": [
            {
                k: r[k]
                for k in (
                    "region_id",
                    "old_text",
                    "new_text",
                    "old_complete",
                    "new_complete",
                )
            }
            for r in recoveries
        ],
        "nonselected_region_checks": unchanged,
        "resources": resources,
        "automatic_complete_regions_before": sum(
            bool(r["complete"]) for r in text_data["regions"]
        ),
        "automatic_complete_regions_after": sum(
            bool(r["complete"]) for r in result["regions"]
        ),
        "source_and_old_text_files_unchanged": True,
        "source_review_required": True,
        "production_GO": False,
    }
    base._dump(output / "recovery_summary.json", summary)
    base._dump(
        output / "group_summary.json",
        [
            {
                k: g[k]
                for k in (
                    "id",
                    "geometry_type",
                    "region_ids",
                    "text",
                    "complete",
                    "unresolved_reasons",
                )
            }
            for g in result["groups"]
        ],
    )
    return result
