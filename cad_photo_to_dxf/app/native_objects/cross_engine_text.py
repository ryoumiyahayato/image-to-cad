"""Finite, source-bound comparison with a deployed independent recognizer.

PP-OCR scores stay in their own units. Two crops are one engine's robustness
check, not two independent engines. Adoption needs an actual high-confidence
Tesseract whole-line witness, exact raw cross-engine text, unchanged source
checks, and no high-confidence or prefix/suffix conflict. Complete upstream
regions are control cases and are never changed by this stage.
"""

from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
from .evidence_paths import relative_evidence_path
import time

from . import text_regions as base, text_line_domains as domains
from . import independent_recognizer as independent
from .contracts import validate_text_regions
from .execution import check_cancel
from .performance import profiled


POLICY = {
    "version": "source-bound-cross-engine-whole-line-v1",
    "maximum_regions": 24,
    "maximum_model_calls": 48,
    "maximum_complete_controls": 6,
    "source_margins_px": [2, 4],
    "model_mean_confidence_minimum": 0.98,
    "model_emitted_character_confidence_minimum": 0.95,
    "model_confidence_is_not_calibrated_probability": True,
    "same_model_two_crops_are_not_two_independent_models": True,
    "required_independent_engine_families": ["Tesseract", "PP-OCR"],
    "Tesseract_word_confidence_unchanged": 85.0,
    "Tesseract_numeric_confidence_unchanged": 95.0,
    "raw_string_case_spaces_and_punctuation_must_match": True,
    "manual_expected_answers_or_case_ids": False,
    "complete_upstream_regions_immutable": True,
    "remote_inference": False,
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


def _raw_text(words):
    return " ".join(w["text"] for w in words)


def _confident(words):
    return bool(words) and all(
        w["confidence"]
        >= (
            base.POLICY["minimum_numeric_word_confidence"]
            if w["text"].isdigit()
            else base.POLICY["minimum_word_confidence"]
        )
        for w in words
    )


def _read_tesseract_evidence(region, text_data, upstream, output, image):
    """Use actual raw files; JSON strings or renamed IDs are not extra votes."""
    root = (
        upstream.parent
        / text_data.get("region_evidence_roots", {}).get(region["id"], ".")
    ).resolve()
    result, seen = [], set()
    for alternative in region.get("completeness_evidence", {}).get("alternatives", []):
        artifact = alternative.get("raw_artifact", {})
        raw = (
            (upstream.parent / artifact["path"]).resolve()
            if artifact.get("path")
            else (root / alternative["raw_tsv"]).resolve()
        )
        metadata = raw.with_suffix(".json")
        if not raw.is_file() or not metadata.is_file():
            raise FileNotFoundError(
                "CROSS_ENGINE_UPSTREAM_RAW_OBSERVATION_MISSING:" + str(raw)
            )
        meta = json.loads(metadata.read_text())
        if meta.get("status") != "COMPLETED" or meta.get("tsv_sha256") != base._sha(
            raw
        ):
            raise ValueError("CROSS_ENGINE_UPSTREAM_RAW_OBSERVATION_HASH_MISMATCH")
        spec = meta["specification"]
        box = list(spec["crop_xyxy_px"])
        if not base._inside(box, [0, 0, image.shape[1], image.shape[0]]):
            raise ValueError("CROSS_ENGINE_UPSTREAM_CROP_OUTSIDE_SOURCE")
        x0, y0, x1, y1 = box
        if spec["crop_array_sha256"] != base.source_array_sha256(image[y0:y1, x0:x1]):
            raise ValueError("CROSS_ENGINE_UPSTREAM_SOURCE_PIXELS_MISMATCH")
        key = base.raw_observation_key(meta)
        if key in seen:
            continue
        seen.add(key)
        padding = int(spec.get("external_white_padding_px", 0))
        origin = [
            box[0] - padding,
            box[1] - padding,
            box[2] + padding,
            box[3] + padding,
        ]
        words = base._parse_tsv(
            raw.read_text(), origin, alternative["context_id"], spec["psm"]
        )
        provenance = {
            **base.raw_observation_provenance(meta),
            "specification": spec,
            "raw_tsv": relative_evidence_path(raw, output),
            "raw_tsv_sha256": base._sha(raw),
            "metadata_sha256": base._sha(metadata),
            "engine_command": meta.get("command"),
            "engine_version": meta.get("engine_version"),
        }
        for number, word in enumerate(words):
            word.update(
                observation_key=key,
                observation_provenance=provenance,
                id="tess-" + key[:12] + "-" + str(number),
            )
        selected = base._select_line(words, region["bbox_xyxy_px"])
        result.append(
            {
                "context_id": alternative["context_id"],
                "psm": spec["psm"],
                "crop_xyxy_px": box,
                "status": "COMPLETED",
                "words": selected,
                "all_words": words,
                "raw_tsv": relative_evidence_path(raw, output),
                "observation_key": key,
                "raw_artifact": {
                    "path": relative_evidence_path(raw, output),
                    "sha256": base._sha(raw),
                    "status": "SAVED_RAW_TSV",
                },
                "observation_provenance": provenance,
                "evidence_role": "current_candidate",
                "upstream_evidence_role": alternative.get("evidence_role"),
                "raw_text": _raw_text(selected),
                "all_words_above_unchanged_threshold": _confident(selected),
            }
        )
    return result


def _source_contexts(region, glyphs, image_shape, roi):
    """Two finite contexts derived from all supported source components.

    Enclosures retain the complete measured interior as the maximum scope.
    Open regions retain any already measured ambiguous prefix/suffix domain.
    The model never receives an answer-selected character crop.
    """
    if region.get("enclosure"):
        limit = region["enclosure"]["bbox_xyxy_px"]
        components = [g for g in glyphs if base._inside(g["bbox_xyxy_px"], limit)]
        if not components:
            return [], "NO_COMPLETE_ENCLOSED_SOURCE_COMPONENT_SET"
        core = base._box_union([g["bbox_xyxy_px"] for g in components])
        method = "all_compact_source_components_inside_measured_enclosure"
    else:
        limit = roi
        measured = region.get("line_domain_refinement", {}).get("new_domain")
        if measured:
            core = list(measured["bbox_xyxy_px"])
            method = (
                "complete_previously_measured_source_line_domain_including_unknown_ink"
            )
        else:
            core = list(region["bbox_xyxy_px"])
            height = max(1, core[3] - core[1])
            components = [
                g
                for g in glyphs
                if 0.45 <= (g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1]) / height <= 1.7
                and abs(g["bbox_xyxy_px"][3] - core[3]) <= 0.35 * height
                and max(
                    g["bbox_xyxy_px"][0] - core[2], core[0] - g["bbox_xyxy_px"][2], 0
                )
                <= 1.25 * height
            ]
            if components:
                core = base._box_union([core] + [g["bbox_xyxy_px"] for g in components])
            method = (
                "existing_line_and_all_near_same_baseline_compact_source_components"
            )
    if not base._inside(core, roi) or not base._inside(core, limit):
        return [], "COMPLETE_SOURCE_DOMAIN_CROSSES_EFFECTIVE_INPUT"
    if not 7 <= core[3] - core[1] <= 130 or core[2] - core[0] > 750:
        return [], "SOURCE_DOMAIN_OUTSIDE_FINITE_RECOGNIZER_LINE_GEOMETRY"
    contexts = []
    for margin in POLICY["source_margins_px"]:
        crop = [
            max(limit[0], core[0] - margin),
            max(limit[1], core[1] - margin),
            min(limit[2], core[2] + margin),
            min(limit[3], core[3] + margin),
        ]
        if any(c["crop_xyxy_px"] == crop for c in contexts):
            continue
        contexts.append(
            {
                "crop_xyxy_px": crop,
                "source_domain_xyxy_px": core,
                "source_domain_method": method,
                "margin_px": margin,
                "source_pixels_modified": False,
                "external_white_padding_px": 0,
            }
        )
    return contexts, None if len(
        contexts
    ) == 2 else "TWO_DISTINCT_FINITE_SOURCE_CONTEXTS_UNAVAILABLE"


def _plan(text_data, glyphs, shape, roi):
    rows = []
    for region in text_data["regions"]:
        contexts, reason = _source_contexts(region, glyphs, shape, roi)
        rows.append(
            {
                "region_id": region["id"],
                "upstream_text": region["text"],
                "control_only": bool(region["complete"]),
                "enclosed": bool(region.get("enclosure")),
                "bbox_xyxy_px": region["bbox_xyxy_px"],
                "contexts": contexts,
                "eligible": reason is None,
                "not_attempted_reason": reason,
            }
        )

    def order(row):
        return (
            not row["enclosed"],
            row["bbox_xyxy_px"][1],
            row["bbox_xyxy_px"][0],
            row["region_id"],
        )

    controls = sorted(
        [r for r in rows if r["eligible"] and r["control_only"]], key=order
    )[: POLICY["maximum_complete_controls"]]
    pending = sorted(
        [r for r in rows if r["eligible"] and not r["control_only"]], key=order
    )
    selected = pending[: POLICY["maximum_regions"] - len(controls)] + controls
    ids = {r["region_id"] for r in selected}
    for row in rows:
        if row["eligible"] and row["region_id"] not in ids:
            row["not_attempted_reason"] = "FIXED_24_REGION_MODEL_BUDGET"
    return selected, rows


def _evaluate(region, tesseract, model_records, image, roi, glyphs, labels):
    reasons = []
    raw = [record["raw_model_output"]["raw_text"] for record in model_records]
    if (
        len(model_records) != 2
        or len(set(record["source_array_sha256"] for record in model_records)) != 2
    ):
        reasons.append("MODEL_ROBUSTNESS_REQUIRES_TWO_DISTINCT_SOURCE_CONTEXTS")
    if not raw or not raw[0] or len(set(raw)) != 1:
        reasons.append("RAW_MODEL_CONTEXT_TRANSCRIPTIONS_DISAGREE_OR_EMPTY")
    for record in model_records:
        output = record["raw_model_output"]
        mean, minimum = (
            output["model_mean_confidence"],
            output["minimum_emitted_character_confidence"],
        )
        tokens = output.get("raw_CTC_tokens", [])
        if not tokens or "".join(t["character"] for t in tokens) != output["raw_text"]:
            reasons.append("MODEL_RAW_CTC_TOKENS_DO_NOT_SUPPORT_RAW_STRING")
        if (
            mean is None
            or minimum is None
            or not math.isfinite(mean)
            or not math.isfinite(minimum)
            or mean < POLICY["model_mean_confidence_minimum"]
            or minimum < POLICY["model_emitted_character_confidence_minimum"]
        ):
            reasons.append("MODEL_CHARACTER_EVIDENCE_BELOW_FROZEN_OWN_SCALE_GATE")
        reasons.extend(record["source_domain_audit"]["unresolved_reasons"])
    text = raw[0] if raw and len(set(raw)) == 1 else None
    matching = [
        a
        for a in tesseract
        if a["raw_text"] == text and a["all_words_above_unchanged_threshold"]
    ]
    if not matching:
        reasons.append(
            "NO_SAME_RAW_WHOLE_LINE_TESSERACT_WITNESS_AT_UNCHANGED_THRESHOLDS"
        )
    # Exact strings and all high-confidence conflicts survive; no casefolding,
    # punctuation removal, numerical rewrite or majority over duplicated crops.
    conflicts = [
        {
            "raw_text": a["raw_text"],
            "context_id": a["context_id"],
            "observation_key": a["observation_key"],
            "words": a["words"],
        }
        for a in tesseract
        if a["words"]
        and a["raw_text"] != text
        and sum(w["confidence"] for w in a["words"]) / len(a["words"])
        >= base.POLICY["minimum_word_confidence"]
    ]
    if conflicts:
        reasons.append("HIGH_CONFIDENCE_TESSERACT_WHOLE_LINE_CONFLICT_RETAINED")
    candidate = None
    baseline_reasons = []
    if matching:
        best = max(matching, key=lambda a: min(w["confidence"] for w in a["words"]))
        originals = [w for a in tesseract for w in a["all_words"]]
        seed = {
            "id": region["id"],
            "bbox_xyxy_px": base._box_union([w["bbox_xyxy_px"] for w in best["words"]]),
            "enclosure": copy.deepcopy(region.get("enclosure")),
            "origin": "verified_cross_engine_whole_line",
            "seed_observation_ids": region.get("discovery_observation_ids", []),
            "glyph_labels": [],
            "discovery_strings": sorted(
                {a["raw_text"] for a in tesseract if a["raw_text"]}
            ),
        }
        candidate = base._complete_region(
            seed, [copy.deepcopy(best)], originals, image, roi, glyphs, labels
        )
        baseline_reasons = list(candidate["unresolved_reasons"])
        reasons.extend(
            reason
            for reason in baseline_reasons
            if reason != "word_missing_two_confident_contexts_with_current_local_OCR"
        )
    approved = bool(candidate and not reasons)
    assessment = {
        "policy": POLICY,
        "raw_model_strings": raw,
        "raw_whole_line_text": text,
        "Tesseract_matching_observation_keys": [a["observation_key"] for a in matching],
        "high_confidence_Tesseract_conflicts": conflicts,
        "baseline_candidate_reasons": baseline_reasons,
        "unresolved_reasons": sorted(set(reasons)),
        "independent_engine_family_count": 2 if matching and raw else 0,
        "PP_crop_count_is_only_same_engine_robustness": len(model_records),
        "numeric_or_word_Tesseract_gate_relaxed": False,
        "PP_score_converted_to_Tesseract_confidence": False,
        "model_model_confidence_calibration_proven": False,
        "approved_by_cross_engine_and_source_checks": approved,
        "previous_region_digest": _digest(region),
        "previous_unresolved_reasons": region["unresolved_reasons"],
        "previous_full_region_preserved_in_attempt_record": True,
    }
    if candidate:
        candidate["cross_engine_evidence"] = assessment
        candidate["completeness_evidence"]["historical_observations_preserved"] = (
            tesseract
        )
        if approved:
            candidate["complete"] = True
            candidate["unresolved_reasons"] = []
            candidate["status"] = "TEXT_PROPOSAL_PENDING_SOURCE_REVIEW"
            candidate["complete_claim_scope"] = (
                "one_actual_Tesseract_witness_plus_independent_PP_whole_line_and_source_checks_not_semantic_proof"
            )
            for word in candidate["words"]:
                word["Tesseract_only_agreement_pass"] = word["agreement_pass"]
                word["agreement_pass"] = True
                word["agreement_basis"] = (
                    "cross_engine_same_raw_whole_line_with_separate_confidence_scales"
                )
                word["independent_engine_witnesses"] = {
                    "Tesseract_observation_keys": [
                        a["observation_key"] for a in matching
                    ],
                    "PP_model_sha256": independent.MODEL_SHA256,
                    "PP_context_input_sha256": [
                        r["source_array_sha256"] for r in model_records
                    ],
                }
        candidate["retained_unassigned_old_context"] = copy.deepcopy(
            region.get("retained_unassigned_old_context")
            or {
                "bbox_xyxy_px": region.get(
                    "inspection_bbox_xyxy_px", region["bbox_xyxy_px"]
                ),
                "compact_source_ink_mask": region["compact_source_ink_mask"],
                "meaning": "unaltered upstream ambiguous source remains explicit evidence",
            }
        )
    return candidate, assessment


@profiled("cross_engine_text.refine_cross_engine")
def refine_cross_engine(
    image,
    text_data,
    output_dir,
    *,
    source_sha,
    upstream_path,
    dpi,
    progress_callback=None,
    model_path=None,
):
    """Pipeline-compatible current-source stage; no old cache/approval inputs."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import find_objects

    start, cpu = time.perf_counter(), time.process_time()
    image = np.asarray(image)
    roi = list(text_data["roi_xyxy_px"])
    validate_text_regions(text_data, image.shape, roi)
    source_hash = base.source_array_sha256(image)
    if source_hash != text_data["source_array_sha256"]:
        raise ValueError("CROSS_ENGINE_SOURCE_ARRAY_CHANGED")
    upstream = Path(upstream_path)
    if _digest(json.loads(upstream.read_text())) != _digest(text_data):
        raise ValueError("CROSS_ENGINE_UPSTREAM_NOT_SAVED_INPUT")
    upstream_hash = base._sha(upstream)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("CROSS_ENGINE_REQUIRES_FRESH_EVIDENCE_DIRECTORY")
    output.mkdir(parents=True, exist_ok=True)
    _, labels, glyphs = base._component_evidence(image, roi)
    slices = find_objects(labels)
    selected, decisions = _plan(text_data, glyphs, image.shape, roi)
    base._dump(
        output / "policy_and_selection.json",
        {
            "policy": POLICY,
            "all_region_decisions": decisions,
            "selected_region_ids": [p["region_id"] for p in selected],
            "planned_model_calls": len(selected) * 2,
            "source_array_sha256": source_hash,
            "source_sha256": source_sha,
            "producer_sha256": base._sha(__file__),
            "upstream_sha256": upstream_hash,
            "source_cases_or_expected_answers_read": False,
        },
    )
    result = copy.deepcopy(text_data)
    by_id = {r["id"]: r for r in result["regions"]}
    old_roots = {
        r["id"]: relative_evidence_path(
            (
                upstream.parent
                / text_data.get("region_evidence_roots", {}).get(r["id"], ".")
            ).resolve(),
            output,
        )
        for r in text_data["regions"]
    }
    result["region_evidence_roots"] = old_roots
    engine = independent.IndependentRecognizer(model_path)
    base._dump(output / "model_identity.json", engine.identity)
    records, model_observations, model_cache = [], [], {}
    for index, plan in enumerate(selected):
        check_cancel("CROSS_ENGINE_REGION:" + plan["region_id"])
        region = copy.deepcopy(by_id[plan["region_id"]])
        tess = _read_tesseract_evidence(region, text_data, upstream, output, image)
        currents = []
        for number, context in enumerate(plan["contexts"]):
            x0, y0, x1, y1 = context["crop_xyxy_px"]
            crop = image[y0:y1, x0:x1]
            key = _digest(
                {
                    "source_sha256": source_sha,
                    "crop": context["crop_xyxy_px"],
                    "crop_sha256": base.source_array_sha256(crop),
                    "model_sha256": independent.MODEL_SHA256,
                }
            )
            if key in model_cache:
                currents.append(copy.deepcopy(model_cache[key]))
                continue
            if len(model_observations) >= POLICY["maximum_model_calls"]:
                raise RuntimeError("CROSS_ENGINE_FIXED_MODEL_CALL_BUDGET")
            name = plan["region_id"] + "-context-" + str(number + 1)
            rawdir = output / "model_observations"
            rawdir.mkdir(exist_ok=True)
            image_path = rawdir / (name + ".png")
            Image.fromarray(crop).save(image_path)
            if progress_callback:
                progress_callback(
                    {
                        "stage": "cross_engine_recognition_start",
                        "region_id": region["id"],
                        "context": number + 1,
                        "total_selected": len(selected),
                    }
                )
            raw = engine.recognize(crop)
            if raw.get("input_array_sha256") != base.source_array_sha256(crop):
                raise ValueError("CROSS_ENGINE_RECOGNIZER_INPUT_HASH_MISMATCH")
            source_audit = domains.inspect_source_domain(
                labels, roi, context["crop_xyxy_px"], component_slices=slices
            )
            observation = copy.deepcopy(getattr(engine, "last_observation", {}))
            receipt = observation.get("raw_observation_cache") or {}
            record = {
                **observation,
                "observation_key": receipt.get("key", key),
                "source_context_key": key,
                "region_id": region["id"],
                "context": context,
                "source_array_sha256": base.source_array_sha256(crop),
                "source_png": relative_evidence_path(image_path, output),
                "source_png_sha256": base._sha(image_path),
                "source_domain_audit": source_audit,
                "raw_model_output": raw,
                "model_identity_sha256": _digest(engine.identity),
                "source_case_expected_text_read": False,
                "source_pixels_modified": False,
            }
            base._dump(rawdir / (name + ".json"), record)
            model_observations.append(record)
            model_cache[key] = record
            currents.append(record)
            base._dump(output / "partial_model_observations.json", model_observations)
        candidate, assessment = _evaluate(
            region, tess, currents, image, roi, glyphs, labels
        )
        adopt = bool(
            not region["complete"]
            and assessment["approved_by_cross_engine_and_source_checks"]
        )
        record = {
            "region_id": region["id"],
            "old": region,
            "plan": plan,
            "Tesseract_raw_observations": tess,
            "model_observations": currents,
            "assessment": assessment,
            "candidate": candidate,
            "control_only": region["complete"],
            "adopted_into_text_contract": adopt,
            "prior_complete_region_unchanged": bool(region["complete"]),
            "failure_preserves_previous_region": not adopt,
        }
        if adopt:
            by_id[region["id"]].clear()
            by_id[region["id"]].update(candidate)
            result["region_evidence_roots"][region["id"]] = "."
        records.append(record)
        base._dump(output / "region_attempts" / (region["id"] + ".json"), record)
        if progress_callback:
            progress_callback(
                {
                    "stage": "cross_engine_region_complete",
                    "region_id": region["id"],
                    "complete": bool(adopt or region["complete"]),
                    "model_calls": sum(
                        r.get("model_inference_executed_for_this_request", True)
                        for r in model_observations
                    ),
                    "observation_records": len(model_observations),
                }
            )
    for group in result["groups"]:
        rows = [by_id[rid] for rid in group["region_ids"]]
        group.update(
            text="\n".join(r["text"] for r in rows),
            complete=all(r["complete"] for r in rows),
            bbox_xyxy_px=base._box_union([r["bbox_xyxy_px"] for r in rows]),
            unresolved_reasons=sorted(
                {why for r in rows for why in r["unresolved_reasons"]}
            ),
            lines=[
                {
                    "region_id": r["id"],
                    "text": r["text"],
                    "bbox_xyxy_px": r["bbox_xyxy_px"],
                    "complete": r["complete"],
                    "word_ids": [w["id"] for w in r["words"]],
                }
                for r in rows
            ],
        )
    result["uncertainties"] = [
        {
            "region_id": r["id"],
            "text": r["text"],
            "bbox_xyxy_px": r["bbox_xyxy_px"],
            "reasons": r["unresolved_reasons"],
        }
        for r in result["regions"]
        if not r["complete"]
    ]
    unchanged = [
        {"region_id": r["id"], "same": _digest(r) == _digest(by_id[r["id"]])}
        for r in text_data["regions"]
        if r["complete"]
    ]
    if not all(r["same"] for r in unchanged):
        raise RuntimeError("CROSS_ENGINE_CHANGED_COMPLETE_UPSTREAM_REGION")
    if (
        base.source_array_sha256(image) != source_hash
        or base._sha(upstream) != upstream_hash
    ):
        raise RuntimeError("CROSS_ENGINE_MODIFIED_SOURCE_OR_UPSTREAM")
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
    dependencies = [
        {"module": m.__name__, "sha256": base._sha(m.__file__)}
        for m in (base, domains, independent)
    ]
    producer = {
        "module": __name__,
        "sha256": base._sha(__file__),
        "dependencies": dependencies,
        "source_array_sha256": source_hash,
        "source_sha256": source_sha,
        "upstream_path": str(upstream),
        "upstream_sha256": upstream_hash,
        "model_identity": engine.identity,
        "raw_source_pixels_modified": False,
        "manual_transcription_supplied": False,
    }
    summary = {
        "policy": POLICY,
        "selected_regions": len(selected),
        "actual_model_calls": sum(
            r.get("model_inference_executed_for_this_request", True)
            for r in model_observations
        ),
        "observation_records": len(model_observations),
        "model_families": 1,
        "robustness_contexts_not_independent_models": True,
        "new_automatic_complete_regions": [
            r["region_id"] for r in records if r["adopted_into_text_contract"]
        ],
        "new_automatic_texts": [
            r["candidate"]["text"] for r in records if r["adopted_into_text_contract"]
        ],
        "new_content_requires_more_than_model_confidence": True,
        "complete_controls_unchanged": unchanged,
        "CPU_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - start,
        "source_and_upstream_unchanged": True,
        "model_scores_not_mapped_to_Tesseract": True,
        "product_GO": False,
    }
    result.update(
        producer=producer,
        status="CROSS_ENGINE_SOURCE_TEXT_COMPLETED_WITH_EXPLICIT_PENDING",
        cross_engine_summary=summary,
    )
    validate_text_regions(result, image.shape, roi)
    base._dump(output / "text_regions.json", result)
    base._dump(output / "completed_text.json", result)
    base._dump(output / "summary.json", summary)
    base._dump(
        output / "completed_stages.json",
        {
            "source_sha256": source_sha,
            "source_array_sha256": source_hash,
            "roi_xyxy_px": roi,
            "source_size_px": result["source_size_px"],
            "coordinate_system": "source_pixels_top_left",
            "text": {
                "path": "completed_text.json",
                "sha256": base._sha(output / "completed_text.json"),
                "producer_module": __name__,
                "producer_sha256": base._sha(__file__),
                "dependency_producers": dependencies,
            },
        },
    )
    return result
