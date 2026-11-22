"""Finite block-context OCR of source-derived enclosures and paragraph rows.

No answer dictionary, transcription edits, glyph whitening or resizing. Existing
word-confidence, agreement, conflict, crop-edge and source-completeness gates
remain authoritative. Incomplete proposals stay pending with all old evidence.
"""

from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .evidence_paths import relative_evidence_path
import shutil
import time

from . import text_regions as base
from . import text_line_domains as domains
from .contracts import validate_text_regions
from .execution import check_cancel
from .performance import profiled


POLICY = {
    "version": "source_enclosure_and_paragraph_context_v1",
    "maximum_groups": 24,
    "maximum_OCR_calls": 48,
    "paragraph_PSM": [6, 11],
    "enclosure_PSM": [6, 8],
    "single_line_PSM": [6, 8],
    "paragraph_original_paper_margins_px": [2, 4],
    "single_line_original_paper_margins_px": [2, 4],
    "maximum_paragraph_lines": 6,
    "existing_confidence_or_content_gates_changed": False,
    "raw_source_pixels_modified": False,
    "source_rescaled": False,
    "answer_or_case_specific_dictionary": False,
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _expand(box, margin, roi):
    return [
        max(roi[0], box[0] - margin),
        max(roi[1], box[1] - margin),
        min(roi[2], box[2] + margin),
        min(roi[3], box[3] + margin),
    ]


def _plans(text_data, glyphs, shape):
    regions = {r["id"]: r for r in text_data["regions"]}
    roi = text_data["roi_xyxy_px"]
    proposed = []
    for group in text_data["groups"]:
        rows = [regions[rid] for rid in group["region_ids"]]
        if all(r["complete"] for r in rows):
            continue
        if any(r.get("source_review") for r in rows) or group.get("source_review"):
            raise ValueError("AUTOMATIC_BLOCK_RESCUE_CANNOT_CONSUME_MANUAL_REVIEW")
        if len(rows) > POLICY["maximum_paragraph_lines"]:
            continue
        box = base._box_union([r["bbox_xyxy_px"] for r in rows])
        if not base._inside(box, roi) or box[2] <= box[0] or box[3] <= box[1]:
            continue
        if len(rows) == 1 and rows[0].get("enclosure"):
            enclosure = rows[0]["enclosure"]
            inner = enclosure["bbox_xyxy_px"]
            compact = [
                g["bbox_xyxy_px"]
                for g in glyphs
                if base._inside(g["bbox_xyxy_px"], inner)
            ]
            if not compact:
                continue
            envelope = _expand(base._box_union(compact), 2, inner)
            plans = [
                {
                    "psm": 6,
                    "crop_xyxy_px": list(inner),
                    "domain": "complete_measured_frame_interior",
                },
                {
                    "psm": 8,
                    "crop_xyxy_px": envelope,
                    "domain": "all_compact_source_components_inside_frame",
                },
            ]
            kind, priority = "enclosed_label", 0
        elif len(rows) > 1:
            # The upstream geometric group supplies all rows, not desired text.
            if any(r.get("enclosure") for r in rows):
                continue
            plans = [
                {
                    "psm": psm,
                    "crop_xyxy_px": _expand(box, margin, roi),
                    "domain": "complete_geometric_paragraph",
                }
                for psm, margin in zip(
                    POLICY["paragraph_PSM"],
                    POLICY["paragraph_original_paper_margins_px"],
                )
            ]
            kind, priority = "paragraph", 1
        else:
            row = rows[0]
            if (
                not row.get("words")
                or sum(ch.isalnum() for ch in row.get("text", "")) < 2
            ):
                continue
            h = box[3] - box[1]
            if not (7 <= h <= 90) or box[2] - box[0] > 750:
                continue
            # Preserve the full automatically measured domain, including any
            # connected suffix/rule. Failure to separate them remains failure.
            region_domain = (
                row.get("line_domain_refinement", {})
                .get("new_domain", {})
                .get("bbox_xyxy_px", box)
            )
            plans = [
                {
                    "psm": psm,
                    "crop_xyxy_px": _expand(region_domain, margin, roi),
                    "domain": "complete_existing_source_line_domain",
                }
                for psm, margin in zip(
                    POLICY["single_line_PSM"],
                    POLICY["single_line_original_paper_margins_px"],
                )
            ]
            kind, priority = "single_line", 2
        if any(not base._inside(p["crop_xyxy_px"], roi) for p in plans):
            continue
        proposed.append(
            {
                "group_id": group["id"],
                "kind": kind,
                "priority": priority,
                "region_ids": [r["id"] for r in rows],
                "bbox_xyxy_px": box,
                "passes": plans,
            }
        )
    proposed.sort(
        key=lambda x: (
            x["priority"],
            x["bbox_xyxy_px"][1],
            x["bbox_xyxy_px"][0],
            x["group_id"],
        )
    )
    return proposed[: POLICY["maximum_groups"]], proposed[POLICY["maximum_groups"] :]


@profiled("text_block_rescue.refine_text_blocks")
def refine_text_blocks(
    image,
    text_data,
    output_dir,
    *,
    source_sha,
    upstream_path,
    observation_path,
    dpi,
    progress_callback=None,
    completed_ocr_checkpoint=None,
):
    start = time.perf_counter()
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("BLOCK_RESCUE_REQUIRES_NEW_EVIDENCE_DIRECTORY")
    output.mkdir(parents=True, exist_ok=True)
    roi = list(text_data["roi_xyxy_px"])
    validate_text_regions(text_data, image.shape, roi)
    source_hash = base.source_array_sha256(image)
    if source_hash != text_data["source_array_sha256"]:
        raise ValueError("BLOCK_RESCUE_SOURCE_ARRAY_CHANGED")
    upstream_path, observation_path = Path(upstream_path), Path(observation_path)
    if _digest(json.loads(upstream_path.read_text(encoding="utf-8"))) != _digest(text_data):
        raise ValueError("BLOCK_RESCUE_UPSTREAM_NOT_SAVED_INPUT")
    upstream_hash = base._sha(upstream_path)
    observations = json.loads(observation_path.read_text(encoding="utf-8"))
    if isinstance(observations, dict):
        observations = observations["observations"]
    # Legacy discovery uses tile_id; current discovery uses context_id. This is
    # an identifier adapter only: never alter raw text, confidence or geometry.
    observation_adaptations = []
    for word in observations:
        if "context_id" not in word:
            if "tile_id" not in word:
                raise ValueError("DISCOVERY_OBSERVATION_HAS_NO_CONTEXT_IDENTITY")
            word["context_id"] = str(word["tile_id"])
            observation_adaptations.append(
                {
                    "id": word["id"],
                    "tile_id": word["tile_id"],
                    "context_id": word["context_id"],
                }
            )
    _, labels, glyphs = base._component_evidence(image, roi)
    plans, omitted = _plans(text_data, glyphs, image.shape)
    plan_record = {
        "policy": POLICY,
        "selected": plans,
        "omitted": omitted,
        "source_sha256": source_sha,
        "source_array_sha256": source_hash,
        "producer_sha256": base._sha(__file__),
        "upstream_sha256": upstream_hash,
        "observations_sha256": base._sha(observation_path),
        "source_cases_or_expected_answers_read": False,
    }
    if completed_ocr_checkpoint is not None:
        prior = Path(completed_ocr_checkpoint)
        old_plan = json.loads((prior / "policy_and_selection.json").read_text(encoding="utf-8"))
        for key in (
            "policy",
            "selected",
            "omitted",
            "source_sha256",
            "source_array_sha256",
            "upstream_sha256",
            "observations_sha256",
        ):
            if old_plan.get(key) != plan_record[key]:
                raise ValueError("OCR_CHECKPOINT_FROZEN_INPUT_CHANGED:" + key)
        files = []
        for source in sorted((prior / "local_ocr").iterdir()):
            if not source.is_file():
                continue
            destination = output / "local_ocr" / source.name
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, destination)
            files.append({"file": source.name, "sha256": base._sha(source)})
        base._dump(
            output / "checkpoint_reuse.json",
            {
                "source_directory": str(prior),
                "source_plan_sha256": base._sha(prior / "policy_and_selection.json"),
                "files": files,
                "reuse_only_saved_OCR_not_old_decisions": True,
            },
        )
    base._dump(output / "policy_and_selection.json", plan_record)
    base._dump(
        output / "observation_schema_adapter.json",
        {
            "adaptations": observation_adaptations,
            "changed_text_confidence_or_coordinates": False,
        },
    )
    result = copy.deepcopy(text_data)
    regions = {r["id"]: r for r in result["regions"]}
    # One region may contain observations from several stages. Bind each raw
    # artifact individually; a single inherited region root is insufficient.
    for region in result["regions"]:
        old_root = (
            upstream_path.parent
            / text_data.get("region_evidence_roots", {}).get(region["id"], ".")
        ).resolve()
        for alternative in region.get("completeness_evidence", {}).get(
            "alternatives", []
        ):
            previous_artifact = alternative.get("raw_artifact", {})
            raw = (
                (upstream_path.parent / previous_artifact["path"]).resolve()
                if previous_artifact.get("path")
                else old_root / alternative["raw_tsv"]
            )
            alternative["raw_artifact"] = {
                "path": relative_evidence_path(raw, output),
                "sha256": base._sha(raw) if raw.is_file() else None,
                "status": "SAVED_RAW_TSV"
                if raw.is_file()
                else "UPSTREAM_JSON_ONLY_RAW_EXTERNAL_REFERENCE",
            }
            alternative["raw_tsv"] = relative_evidence_path(raw, output)
    result["region_evidence_roots"] = {r["id"]: "." for r in result["regions"]}
    records, passes = [], []
    for index, plan in enumerate(plans):
        check_cancel("TEXT_BLOCK_CONTEXT:" + plan["group_id"])
        current = []
        for number, p in enumerate(plan["passes"]):
            if len(passes) >= POLICY["maximum_OCR_calls"]:
                raise RuntimeError("BLOCK_CONTEXT_FIXED_CALL_BUDGET_EXCEEDED")
            name = f"B{index + 1:03d}-C{number + 1}-p{p['psm']}"
            words, meta = base._ocr(
                image,
                p["crop_xyxy_px"],
                p["psm"],
                output / "local_ocr",
                name,
                progress_callback,
                padding_px=0,
                dpi=dpi,
            )
            passes.append({"group_id": plan["group_id"], **meta})
            current.append(
                {
                    "context_id": name,
                    "psm": p["psm"],
                    "crop_xyxy_px": p["crop_xyxy_px"],
                    "status": meta["status"],
                    "raw_tsv": "local_ocr/" + name + ".tsv",
                    "external_white_padding_px": 0,
                    "raw_artifact": {
                        "path": "local_ocr/" + name + ".tsv",
                        "sha256": meta["tsv_sha256"],
                        "status": "SAVED_RAW_TSV",
                    },
                    "observation_key": base.raw_observation_key(meta),
                    "observation_provenance": {
                        **base.raw_observation_provenance(meta),
                        "source_sha256": source_sha,
                        "specification": meta["specification"],
                        "raw_tsv_sha256": meta["tsv_sha256"],
                        "recognition_input_sha256": meta["image_sha256"],
                        "engine_command": meta["command"],
                        "engine_version": meta.get("engine_version"),
                    },
                    "evidence_role": "current_candidate",
                    "all_words": words,
                    "source_domain": p["domain"],
                }
            )
        for rid in plan["region_ids"]:
            old = copy.deepcopy(regions[rid])
            if old["complete"]:
                records.append(
                    {
                        "region_id": rid,
                        "not_changed": "ALREADY_COMPLETE_REGION_PRESERVED",
                        "old_digest": _digest(old),
                        "new_digest": _digest(old),
                    }
                )
                continue
            previous = copy.deepcopy(
                old.get("completeness_evidence", {}).get("alternatives", [])
            )
            for alternative in previous:
                alternative["previous_evidence_role"] = alternative.get(
                    "evidence_role", "current_candidate"
                )
                alternative["evidence_role"] = "historical_diagnostic"
            additional = [
                {
                    **alt,
                    "words": base._select_line(alt["all_words"], old["bbox_xyxy_px"]),
                }
                for alt in current
            ]
            alternatives = previous + additional
            seed = {
                "id": rid,
                "bbox_xyxy_px": old["bbox_xyxy_px"],
                "enclosure": old.get("enclosure"),
                "origin": "source_derived_block_context",
                "seed_observation_ids": old.get("discovery_observation_ids", []),
                "discovery_strings": sorted({old.get("text", "")}),
                "glyph_labels": [],
            }
            candidate = base._complete_region(
                seed, alternatives, observations, image, roi, glyphs, labels
            )
            # Historical domains remain diagnostics. Recheck source ink in
            # the actual new OCR contexts, rather than carrying the failure
            # of a previous smaller/graphic-contaminated crop forever.
            old_domain = old.get("line_domain_refinement", {}).get("new_domain")
            boundary = []
            if not old.get("enclosure"):
                source_clean_keys = set()
                source_reasons = set()
                for alternative in additional:
                    crop = list(alternative["crop_xyxy_px"])
                    inspection = domains.inspect_source_domain(labels, roi, crop)
                    # For a paragraph, neighboring rows are not a prefix of
                    # this row. This audit strip does not alter the OCR input.
                    box = candidate["bbox_xyxy_px"]
                    row_domain = {
                        "bbox_xyxy_px": [
                            crop[0],
                            max(crop[1], box[1] - 2),
                            crop[2],
                            min(crop[3], box[3] + 2),
                        ],
                        "bounded_scan_has_no_white_stop": False,
                        "bounded_prefix_scan_has_no_white_stop": False,
                    }
                    unread, reasons = domains._unread_boundary_ink(
                        image, candidate, row_domain
                    )
                    reasons = sorted(set(reasons + inspection["unresolved_reasons"]))
                    if not reasons:
                        source_clean_keys.add(alternative["observation_key"])
                    source_reasons.update(reasons)
                    boundary.append(
                        {
                            "context_id": alternative["context_id"],
                            "actual_OCR_crop_xyxy_px": crop,
                            "source_domain": inspection,
                            "row_audit_strip": row_domain,
                            "unread_source": unread,
                            "unresolved_reasons": reasons,
                            "OCR_pixels_modified": False,
                        }
                    )
                if len(source_clean_keys) < 2:
                    candidate["unresolved_reasons"] = sorted(
                        set(candidate["unresolved_reasons"])
                        | source_reasons
                        | {"BLOCK_CONTEXT_LACKS_TWO_COMPLETE_CURRENT_SOURCE_DOMAINS"}
                    )
                    candidate["complete"] = False
                    candidate["status"] = "UNRESOLVED_TEXT_REGION"
            candidate["block_context_rescue"] = {
                "plan": plan,
                "old_region_digest": _digest(old),
                "raw_strings_never_rewritten": True,
                "current_source_boundary_checks": boundary,
                "historical_domain_diagnostic": old_domain,
                "historical_diagnostic_contexts": [a["context_id"] for a in previous],
                "current_decision_contexts": [a["context_id"] for a in additional],
                "prior_unresolved_reasons_retained": list(
                    old.get("unresolved_reasons", [])
                ),
                "old_unassigned_context": old.get("retained_unassigned_old_context"),
            }
            # The generic source ledger expects this field at the top level.
            # Carry the full old ambiguous mask, not just a prose reference.
            candidate["retained_unassigned_old_context"] = copy.deepcopy(
                old.get("retained_unassigned_old_context")
                or {
                    "bbox_xyxy_px": old.get(
                        "inspection_bbox_xyxy_px", old["bbox_xyxy_px"]
                    ),
                    "compact_source_ink_mask": old["compact_source_ink_mask"],
                    "meaning": "prior source context retained, no source erasure authorized",
                }
            )
            accepted = bool(candidate["complete"])
            if accepted:
                regions[rid].clear()
                regions[rid].update(candidate)
            records.append(
                {
                    "region_id": rid,
                    "old": old,
                    "candidate": candidate,
                    "adopted_into_text_contract": accepted,
                    "failure_preserves_previous_region": not accepted,
                }
            )
            base._dump(output / "region_attempts" / (rid + ".json"), records[-1])
    for group in result["groups"]:
        rows = [regions[rid] for rid in group["region_ids"]]
        group["text"] = "\n".join(r["text"] for r in rows)
        group["lines"] = [
            {
                "region_id": r["id"],
                "text": r["text"],
                "bbox_xyxy_px": r["bbox_xyxy_px"],
                "complete": r["complete"],
                "word_ids": [w["id"] for w in r["words"]],
            }
            for r in rows
        ]
        group["complete"] = all(r["complete"] for r in rows)
        group["bbox_xyxy_px"] = base._box_union([r["bbox_xyxy_px"] for r in rows])
        group["unresolved_reasons"] = sorted(
            {reason for r in rows for reason in r["unresolved_reasons"]}
        )
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
    import numpy as np
    from PIL import Image

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
    if source_hash != base.source_array_sha256(image) or upstream_hash != base._sha(
        upstream_path
    ):
        raise RuntimeError("BLOCK_RESCUE_SOURCE_OR_PRIOR_RESULT_CHANGED")
    dependencies = [
        {"module": m.__name__, "sha256": base._sha(m.__file__)} for m in [base, domains]
    ]
    result["producer"] = {
        "module": __name__,
        "sha256": base._sha(__file__),
        "dependencies": dependencies,
        "source_sha256": source_sha,
        "source_array_sha256": source_hash,
        "upstream_path": str(upstream_path),
        "upstream_sha256": upstream_hash,
        "raw_source_pixels_modified": False,
        "manual_transcription_supplied": False,
    }
    result["status"] = "SOURCE_BLOCK_CONTEXT_COMPLETED_WITH_EXPLICIT_PENDING"
    summary = {
        "policy": POLICY,
        "groups_selected": len(plans),
        "groups_omitted": len(omitted),
        "OCR_contexts_evaluated": len(passes),
        "actual_OCR_calls": sum(not p.get("reused_checkpoint", False) for p in passes),
        "reused_OCR_checkpoints": sum(
            bool(p.get("reused_checkpoint", False)) for p in passes
        ),
        "new_automatic_complete_regions": [
            r["region_id"] for r in records if r.get("adopted_into_text_contract")
        ],
        "new_automatic_texts": [
            r["candidate"]["text"]
            for r in records
            if r.get("adopted_into_text_contract")
        ],
        "unchanged_complete_regions": sum(bool(r.get("not_changed")) for r in records),
        "wall_seconds": time.perf_counter() - start,
        "passes": passes,
        "source_and_old_results_unchanged": True,
        "confidence_or_source_gates_relaxed": False,
    }
    result["block_context_rescue_summary"] = summary
    validate_text_regions(result, image.shape, roi)
    base._dump(output / "completed_text.json", result)
    base._dump(output / "text_regions.json", result)
    base._dump(output / "summary.json", summary)
    base._dump(
        output / "completed_stages.json",
        {
            "source_sha256": source_sha,
            "roi_xyxy_px": roi,
            "source_size_px": result["source_size_px"],
            "source_array_sha256": source_hash,
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
