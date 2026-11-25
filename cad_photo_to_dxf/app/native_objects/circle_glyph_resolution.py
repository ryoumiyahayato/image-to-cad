"""Resolve a circle's literal raw readings against frozen same-source glyphs.

The first pass keeps the unchanged two-engine character gate. Only its strict
successes, and independently replayed undisputed whole-line characters, may be
references. The second pass never feeds its own results back into that bank.
Every raw competing character needs a real reference; every available other
class is compared. Original OCR decisions, confidences and pixels are retained.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from . import source_glyph_equivalence as twins
from . import text_regions as base
from .contracts import save_json


POLICY = {
    "version": "same-source-circle-glyph-reference-resolution-v1",
    "minimum_distinct_original_positive_positions": 2,
    "references_frozen_before_any_resolution": True,
    "resolved_characters_may_be_references": False,
    "reference_routes": ["STRICT_TWO_ENGINE_CIRCLE", "REPLAYED_UNDISPUTED_SINGLE_LINE_CHARACTER"],
    "single_line_reference_eligibility": "STRICT_WHOLE_LINE_REPLAY_THEN_INDIVIDUAL_COMPLETE_SOURCE_COMPONENTS",
    "candidate_must_be_complete_original_raw_single_character": True,
    "every_raw_competing_single_character_requires_reference": True,
    "all_available_reference_classes_compared": True,
    "high_confidence_non_single_character_conflict_blocks_resolution": True,
    "any_nonempty_raw_reading_without_a_single_character_comparison_blocks_resolution": True,
    "competing_exclusion": "ALL_FINITE_QUANTIZATION_REGISTRATIONS_FAIL_OR_KNOWN_STABLE_TOPOLOGY_DIFFERS",
    "positive_equivalence_policy": deepcopy(twins.POLICY),
    "reference_source_domains_must_not_overlap": True,
    "source_pixels_modified": False,
    "OCR_confidence_thresholds_changed": False,
    "case_or_expected_answer_input": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _producer():
    return {"module": __name__, "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "glyph_comparison_sha256": hashlib.sha256(Path(twins.__file__).read_bytes()).hexdigest()}


def _overlap(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _circle_component(source):
    runs = source["interior_support_runs_y_x0_x1"]
    return {"source_role": "FULL_HEIGHT_GLYPH", "bbox_xyxy_px": list(source["glyph_bbox_xyxy_px"]),
            "source_runs_y_x0_x1": deepcopy(runs), "source_area_px": sum(b - a for _, a, b in runs),
            "source_white_gaps_not_filled": True,
            "source_threshold": int(source.get("policy", {}).get("source_threshold", 128))}


def _bind_component(gray, component):
    mask, _ = twins.component_samples(component)
    x0, y0, x1, y1 = component["bbox_xyxy_px"]
    threshold = component.get("source_threshold", base.POLICY["source_threshold"])
    if not np.array_equal(mask.astype(bool), gray[y0:y1, x0:x1] < threshold):
        raise ValueError("REFERENCE_COMPONENT_DIFFERS_FROM_COMPLETE_ORIGINAL_SOURCE")


def _circle_references(gray, roi, obj, evidence_root):
    from .circle_character_recognition import verify_circle_character_evidence, _single_character

    evidence = obj["source_evidence"]["character_evidence"]
    if not evidence.get("decision", {}).get("accepted") or evidence.get("source_reference_resolution") is not None:
        raise ValueError("REFERENCE_CIRCLE_IS_NOT_AN_ORIGINAL_STRICT_TWO_ENGINE_SUCCESS")
    checked = verify_circle_character_evidence(gray, roi, obj, evidence_root)
    if not checked["pass"] or checked.get("adoption_basis") != "STRICT_TWO_ENGINE_COMPLETE_SOURCE_CHARACTER":
        raise ValueError("REFERENCE_CIRCLE_RAW_AND_SOURCE_REPLAY_FAILED:" + checked.get("reason", ""))
    if not _single_character(checked["text"]):
        raise ValueError("REFERENCE_CIRCLE_IS_NOT_A_SINGLE_LITERAL_CHARACTER")
    component = _circle_component(obj["source_evidence"])
    _bind_component(gray, component)
    return [{"reference_key": "circle:" + obj["id"], "character": checked["text"],
             "route": "STRICT_TWO_ENGINE_CIRCLE", "source_component": component,
             "bound_original_evidence_sha256": _digest(evidence)}]


def _line_references(gray, roi, evidence, evidence_root, *, component_exclusions=None):
    from .circle_character_recognition import _single_character
    from .single_line_labels import verify_single_line_label_evidence

    checked = verify_single_line_label_evidence(gray, roi, evidence, evidence_root)
    if not checked.get("pass"):
        raise ValueError("REFERENCE_SINGLE_LINE_RAW_AND_SOURCE_REPLAY_FAILED:" + checked.get("reason", ""))
    components = evidence["source_partition"]["components"]
    labels = checked["source_text_normalization"]["component_characters"]
    anchors = evidence["decision"]["raw_character_conflict_evidence"]["anchors"]
    digest = _digest(evidence)
    refs = []
    for anchor in anchors:
        index = anchor["component_index"]
        letter = anchor["literal_character"]
        if not _single_character(letter) or components[index].get("source_role") != "FULL_HEIGHT_GLYPH":
            continue
        if (letter != labels[index] or not anchor.get("Tesseract_view_indices")
                or not anchor.get("strict_PP_view_indices")):
            raise ValueError("REFERENCE_LINE_CHARACTER_IS_NOT_UNDISPUTED_BEFORE_ANY_RESOLUTION")
        component = deepcopy(components[index])
        try:
            _bind_component(gray, component)
        except ValueError as exc:
            # The replayed row can contain an independently owned graphic
            # inside one glyph's bbox. It does not make another complete,
            # disjoint original glyph of that same verified row disappear.
            if component_exclusions is not None:
                component_exclusions.append({
                    "source_id": digest, "component_index": index,
                    "literal_character": letter,
                    "bbox_xyxy_px": component["bbox_xyxy_px"],
                    "whole_line_raw_and_source_replay_passed": True,
                    "reason": str(exc), "other_independent_row_components_discarded": False,
                })
            continue
        refs.append({"reference_key": "line:" + digest[:20] + ":" + str(index), "character": letter,
                     "route": "REPLAYED_UNDISPUTED_SINGLE_LINE_CHARACTER", "source_component": component,
                     "bound_original_evidence_sha256": digest})
    return refs


def _canonical_references(records):
    """One original source domain is one witness, regardless of view or route."""
    result, seen = [], {}
    for row in sorted(records, key=lambda r: r["reference_key"]):
        box = row["source_component"]["bbox_xyxy_px"]
        aliases = [old for old in result if _overlap(box, old["source_component"]["bbox_xyxy_px"])]
        if aliases:
            if any(old["character"] != row["character"] for old in aliases):
                raise ValueError("OVERLAPPING_REFERENCE_SOURCE_HAS_CONTRADICTORY_LITERAL_LABELS")
            continue
        key = tuple(box)
        if key in seen:
            continue
        seen[key] = row["character"]
        result.append(row)
    return result


def create_reference_pool(gray, roi, source_sha, objects, text_regions, output, evidence_root):
    """Freeze authenticated first-pass source witnesses before any upgrades."""
    circles, lines, records, exclusions = [], [], [], []
    for obj in objects:
        evidence = obj.get("source_evidence", {}).get("character_evidence") or {}
        if obj.get("kind") != "CIRCULAR_MARKER" or not evidence.get("decision", {}).get("accepted"):
            continue
        try:
            refs = _circle_references(gray, roi, obj, evidence_root)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            exclusions.append({"source_id": obj.get("id"), "reason": str(exc)})
            continue
        circles.append(deepcopy(obj))
        records.extend(refs)
    line_proofs = {}
    for obj in objects:
        proof = obj.get("source_evidence", {}).get("single_line_recovery")
        if isinstance(proof, dict):
            line_proofs[_digest(proof)] = proof
    for row in (text_regions or {}).get("regions", []):
        proof = row.get("single_line_recovery")
        if isinstance(proof, dict) and proof.get("decision", {}).get("accepted"):
            line_proofs[_digest(proof)] = proof
    for key, proof in sorted(line_proofs.items()):
        try:
            if proof.get("source_sha256") not in (None, source_sha):
                raise ValueError("REFERENCE_SINGLE_LINE_ORIGINAL_SOURCE_FILE_DIFFERS")
            refs = _line_references(gray, roi, proof, evidence_root, component_exclusions=exclusions)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            exclusions.append({"source_id": key, "reason": str(exc)})
            continue
        if refs:
            lines.append(deepcopy(proof))
            records.extend(refs)
    pool = {"schema": "native-circle-source-glyph-reference-pool-v1", "policy": deepcopy(POLICY),
            "producer": _producer(), "source_sha256": source_sha,
            "source_array_sha256": base.source_array_sha256(gray), "roi_xyxy_px": list(roi),
            "frozen_before_any_resolution": True, "upgraded_characters_used_as_references": False,
            "circle_sources": circles, "single_line_sources": lines,
            "references": _canonical_references(records), "excluded_source_witnesses": exclusions}
    save_json(output, pool)
    from .circle_character_recognition import _file_record
    return pool, _file_record(output, evidence_root)


def replay_reference_pool(gray, roi, pool, evidence_root):
    if (pool.get("schema") != "native-circle-source-glyph-reference-pool-v1"
            or pool.get("policy") != POLICY or pool.get("producer") != _producer()
            or pool.get("roi_xyxy_px") != list(roi)
            or pool.get("source_array_sha256") != base.source_array_sha256(gray)
            or pool.get("frozen_before_any_resolution") is not True
            or pool.get("upgraded_characters_used_as_references") is not False):
        raise ValueError("CIRCLE_REFERENCE_POOL_SOURCE_POLICY_OR_FROZEN_IDENTITY_CHANGED")
    records = []
    for obj in pool["circle_sources"]:
        if obj["source_evidence"].get("source_sha256") != pool["source_sha256"]:
            raise ValueError("CIRCLE_REFERENCE_ORIGINAL_SOURCE_FILE_DIFFERS")
        records.extend(_circle_references(gray, roi, obj, evidence_root))
    for proof in pool["single_line_sources"]:
        if proof.get("source_sha256") not in (None, pool["source_sha256"]):
            raise ValueError("REFERENCE_SINGLE_LINE_ORIGINAL_SOURCE_FILE_DIFFERS")
        if proof.get("source_array_sha256") != pool["source_array_sha256"]:
            raise ValueError("REFERENCE_SINGLE_LINE_COMPLETE_SOURCE_PIXELS_DIFFER")
        records.extend(_line_references(gray, roi, proof, evidence_root))
    expected = _canonical_references(records)
    if expected != pool.get("references"):
        raise ValueError("CIRCLE_REFERENCE_POOL_LABELS_OR_ORIGINAL_COMPONENTS_CHANGED")
    return expected


def _finite_geometric_exclusion(comparison):
    """Missing dimensions/references are never evidence against a character."""
    sampling = comparison.get("sampling_uncertainty_comparison", {})
    trials = sampling.get("registrations", [])
    left, right = sampling.get("left_stable_topology", {}), sampling.get("right_stable_topology", {})
    topology = bool(left.get("known") and right.get("known") and any(
        left.get(key) != right.get(key) for key in ("foreground_components", "background_holes")
    ))
    return bool(trials) and (not any(trial["pass"] for trial in trials) or topology)


def decide_source_reference_character(target, raw_replay, references):
    """Pure decision over authenticated original source components, never names."""
    from .circle_character_recognition import _single_character

    original = raw_replay["decision"]
    strings = original["Tesseract_raw_texts"] + original["PP_OCR_raw_texts"]
    raw_characters = sorted({s for s in strings if _single_character(s)})
    complete_raw = raw_replay["complete_source_raw_characters"]
    reasons = []
    if original.get("accepted"):
        reasons.append("ORIGINAL_STRICT_CHARACTER_ALREADY_ACCEPTED")
    strong_other = [s for s in original["high_confidence_raw_strings"] if not _single_character(s)]
    if strong_other:
        reasons.append("HIGH_CONFIDENCE_NON_SINGLE_CHARACTER_RAW_CONFLICT_RETAINED")
    if any(s and not _single_character(s) for s in strings):
        reasons.append("NON_SINGLE_CHARACTER_RAW_READING_HAS_NO_SOURCE_REFERENCE_COMPARISON")
    grouped = {}
    comparisons = []
    for ref in _canonical_references(references):
        component = ref["source_component"]
        if _overlap(target["bbox_xyxy_px"], component["bbox_xyxy_px"]):
            continue
        comparison = twins.compare_original_glyphs(target, component, require_distinct_row_positions=False)
        row = {"reference_key": ref["reference_key"], "character": ref["character"],
               "source_bbox_xyxy_px": component["bbox_xyxy_px"],
               "original_reference_evidence_sha256": ref["bound_original_evidence_sha256"],
               "comparison": comparison,
               "geometric_competing_reading_excluded": _finite_geometric_exclusion(comparison)}
        comparisons.append(row)
        grouped.setdefault(ref["character"], []).append(row)
    missing = [letter for letter in raw_characters if letter not in grouped]
    if missing:
        reasons.append("RAW_COMPETING_CHARACTER_HAS_NO_AUTHENTICATED_ORIGINAL_REFERENCE")
    positives = {
        letter: [r["reference_key"] for r in rows if r["comparison"]["pass"]]
        for letter, rows in grouped.items()
    }
    eligible = [letter for letter in complete_raw
                if len(positives.get(letter, [])) >= POLICY["minimum_distinct_original_positive_positions"]]
    if len(eligible) != 1:
        reasons.append("NO_UNIQUE_LITERAL_CHARACTER_WITH_TWO_INDEPENDENT_SOURCE_TWINS")
    chosen = eligible[0] if len(eligible) == 1 else None
    unresolved = []
    if chosen is not None:
        unresolved = [letter for letter, rows in grouped.items() if letter != chosen
                      and (any(r["comparison"]["pass"] for r in rows)
                           or not all(r["geometric_competing_reading_excluded"] for r in rows))]
        if unresolved:
            reasons.append("AVAILABLE_COMPETING_CHARACTER_NOT_GEOMETRICALLY_EXCLUDED")
    return {"accepted": not reasons, "text": chosen if not reasons else None, "reasons": reasons,
            "raw_single_character_readings": raw_characters,
            "complete_source_raw_character_readings": complete_raw,
            "original_raw_strings": strings,
            "original_high_confidence_strings": original["high_confidence_raw_strings"],
            "weak_non_single_raw_readings_retained": [s for s in strings if s and not _single_character(s)],
            "missing_raw_competing_reference_classes": missing,
            "all_available_reference_classes": sorted(grouped),
            "positive_reference_keys_by_character": positives,
            "eligible_raw_characters": eligible,
            "unexcluded_competing_reference_classes": unresolved,
            "comparisons": comparisons,
            "raw_observations_rewritten": False, "confidence_thresholds_changed": False}


def resolve_circle_from_source_references(gray, roi, obj, pool, pool_record, evidence_root):
    from .circle_character_recognition import replay_circle_character_observations

    raw = replay_circle_character_observations(gray, roi, obj, evidence_root)
    if not raw.get("pass"):
        return {"accepted": False, "reasons": ["TARGET_ORIGINAL_RAW_REPLAY_FAILED:" + raw.get("reason", "")]}
    target = _circle_component(obj["source_evidence"])
    decision = decide_source_reference_character(target, raw, pool["references"])
    box = target["bbox_xyxy_px"]
    geometry = {"text": decision["text"], "x": box[0], "y": box[3],
                "height_px": box[3] - box[1], "width_px": box[2] - box[0],
                "rotation_deg_image": 0.0} if decision["accepted"] else None
    evidence = {"schema": "native-circle-source-reference-resolution-v1", "policy": deepcopy(POLICY),
                "producer": _producer(), "adoption_basis": "SAME_SOURCE_FROZEN_GLYPH_REFERENCES",
                "reference_pool": deepcopy(pool_record), "source_component_sha256": _digest(target),
                "original_two_engine_decision_sha256": _digest(raw["decision"]),
                "decision": decision, "text_geometry": geometry,
                "original_raw_decision_and_conflicts_retained": True,
                "new_OCR_calls": 0, "new_model_calls": 0}
    return {"accepted": decision["accepted"], "reasons": decision["reasons"],
            "text_geometry": geometry, "evidence": evidence}


def verify_source_reference_resolution(gray, roi, obj, evidence_root, raw_replay):
    from .circle_character_recognition import _read_record

    result = {"pass": False, "new_OCR_calls": 0, "new_model_calls": 0}
    try:
        evidence = obj["source_evidence"]["character_evidence"]["source_reference_resolution"]
        if (evidence.get("schema") != "native-circle-source-reference-resolution-v1"
                or evidence.get("policy") != POLICY or evidence.get("producer") != _producer()
                or evidence.get("adoption_basis") != "SAME_SOURCE_FROZEN_GLYPH_REFERENCES"
                or evidence.get("original_raw_decision_and_conflicts_retained") is not True
                or evidence.get("new_OCR_calls") != 0 or evidence.get("new_model_calls") != 0):
            raise ValueError("CIRCLE_SOURCE_REFERENCE_RESOLUTION_POLICY_OR_IDENTITY_CHANGED")
        pool = json.loads(_read_record(evidence_root, evidence["reference_pool"]))
        if pool.get("source_sha256") != obj["source_evidence"].get("source_sha256"):
            raise ValueError("CIRCLE_SOURCE_REFERENCE_TARGET_AND_POOL_SOURCE_FILE_DIFFERS")
        references = replay_reference_pool(gray, roi, pool, evidence_root)
        target = _circle_component(obj["source_evidence"])
        decision = decide_source_reference_character(target, raw_replay, references)
        if (not decision["accepted"] or decision != evidence.get("decision")
                or evidence.get("source_component_sha256") != _digest(target)
                or evidence.get("original_two_engine_decision_sha256") != _digest(raw_replay["decision"])):
            raise ValueError("CIRCLE_SOURCE_REFERENCES_DO_NOT_RECONFIRM_SAVED_CHARACTER")
        box = target["bbox_xyxy_px"]
        geometry = {"text": decision["text"], "x": box[0], "y": box[3],
                    "height_px": box[3] - box[1], "width_px": box[2] - box[0], "rotation_deg_image": 0.0}
        if evidence.get("text_geometry") != geometry:
            raise ValueError("CIRCLE_SOURCE_REFERENCE_TEXT_GEOMETRY_CHANGED")
        result.update(pass_=True, text_geometry=geometry,
                      source_reference_count=len(references),
                      verified_positive_reference_keys=decision["positive_reference_keys_by_character"][decision["text"]],
                      compared_reference_classes=decision["all_available_reference_classes"],
                      every_raw_conflict_retained_and_compared=True,
                      reference_raw_sources_and_original_pixels_replayed=True,
                      comparison_and_adoption_recomputed=True)
        result["pass"] = result.pop("pass_")
    except (KeyError, ValueError, TypeError, OSError, UnicodeError) as exc:
        result["reason"] = str(exc)
    return result
