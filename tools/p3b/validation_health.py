"""Record the foreground validation-health decision after class-blind visual audit.

No final truth freeze, UI launch, human decision mutation, training or scheduling.
The selection is an auditable review recommendation, never a replacement label.
"""

import argparse
from collections import Counter

from common import atomic_json, product_snapshot, read, read_rows, sha
from pilot_audit import DOCS
from validation_review import MANIFEST, STATE

# Foreground examination of source pixels, exact overlays and expanded context.
# These are review concerns; no expected or replacement class is assigned.
VISUAL_CONCERNS = {
    41: "NARROW_PAIR_SINGLE_VS_PARALLEL_BOUNDARY: 4.886px separation; heterogeneous archival ink/white gap can be interpreted as boundaries or a stroked run. Confirm the intended source objects with context; do not infer truth from gap alone.",
}
ORDER = [16, 41, 30, 6, 17, 33, 13, 36]


def run():
    summary_path = DOCS / "validation-v2-001-post-audit-summary.json"
    summary = read(summary_path)
    for path, expected in summary["protected_input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Protected human audit/state/seed/split changed; stop")
    if product_snapshot() != read(DOCS / "pilot-production-before.json"):
        raise ValueError(
            "Production snapshot changed; investigate before reporting unchanged"
        )
    human = summary["human_result"]
    audited = read_rows(DOCS / "validation-v2-001-correspondence-audit.jsonl")
    by_rank = {r["queue_rank"]: r for r in audited}
    actual_concerns = {
        r["queue_rank"]
        for r in audited
        if r["nomination_quality"] != "NOMINATION_STRONG"
        or r["human_class"] == "AMBIGUOUS"
    } | set(VISUAL_CONCERNS)
    if actual_concerns != set(ORDER) or len(ORDER) > 10:
        raise ValueError(
            "Review recommendation does not match this bounded audited batch"
        )
    train_manifest = read_rows(DOCS / "formal-seed-v2-001.jsonl")
    effective_train = read_rows(DOCS / "formal-seed-adjudicated-decisions.jsonl")
    validation = read_rows(MANIFEST)
    overlap = {
        key: sorted({r[key] for r in train_manifest} & {r[key] for r in validation})
        for key in (
            "sample_id",
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
        )
    }
    if any(overlap.values()):
        raise ValueError("Train/validation leakage; stop without final freeze")
    final_train = read(DOCS / "FORMAL-SEED-FINAL-STATUS.json")
    train_counts = Counter(
        r["current_class"]
        for r in effective_train
        if r["current_review_status"] == "READY"
    )
    if (
        len(effective_train) != 100
        or sum(train_counts.values()) != 94
        or final_train["FORMAL_SEED_FINAL_STATUS"] != "PASS"
    ):
        raise ValueError("Accepted adjudicated train view is inconsistent")
    samples = []
    for rank in ORDER:
        item = by_rank[rank]
        reasons = list(item["reasons"])
        if rank in VISUAL_CONCERNS:
            reasons.append(VISUAL_CONCERNS[rank])
        if item["human_class"] == "AMBIGUOUS":
            reasons.append(
                "HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced"
            )
        samples.append(
            {
                **item,
                "original_stage0": item["human_stage0"],
                "original_stage1": item["human_class"],
                "review_reasons": reasons,
                "review_status": "INDEPENDENT_REVIEW_RECOMMENDED",
                "replacement_class": None,
                "training_authorized": False,
            }
        )
    recommendation = {
        "source_batch": "validation-v2-001",
        "review_count": len(samples),
        "maximum_review_count": 10,
        "manifest_sha256": sha(MANIFEST),
        "state_sha256": sha(STATE),
        "original_audit_sha256": sha(DOCS / "VALIDATION-V2-001-AUDIT.json"),
        "correspondence_audit_sha256": sha(
            DOCS / "validation-v2-001-correspondence-audit.jsonl"
        ),
        "review_rank_order": ORDER,
        "samples": samples,
        "original_answers_immutable": True,
        "original_classes_must_be_hidden_before_re_review": True,
        "new_review_state_required": True,
        "preserve_ambiguous_if_uncertain": True,
        "suspect_ui_prepared": False,
        "suspect_ui_launched": False,
        "blind_sources_accessed": 0,
        "model_trained": False,
        "background_tasks_created": False,
    }
    atomic_json(DOCS / "validation-suspect-review-recommendation.json", recommendation)
    quality = Counter(r["nomination_quality"] for r in audited)
    outside = [r for r in audited if r["queue_rank"] not in actual_concerns]
    outside_classes = Counter(r["human_class"] for r in outside)
    result = {
        "AUDIT_RECOVERED": "YES",
        "EXISTING_HUMAN_AUDIT_RERUN": "NO",
        "TOTAL_REVIEWED": 50,
        "READY": human["VALIDATION_READY"],
        "EXCLUDED": human["VALIDATION_EXCLUDED"],
        "CLASS_DISTRIBUTION": {
            "SINGLE_PHYSICAL_STROKE": human["SINGLE"],
            "TRUE_PARALLEL_STRUCTURE": human["TRUE_PARALLEL"],
            "OTHER": human["OTHER"],
            "AMBIGUOUS": human["AMBIGUOUS"],
        },
        "BAD_NOMINATION_X": human["V_X_U"].get("INVALID_NOMINATION", 0),
        "UNCLEAR_TARGET_U": human["V_X_U"].get("UNCLEAR_TARGET", 0),
        "SKIPPED": human["SKIPPED"],
        **{
            k: quality[k]
            for k in ("NOMINATION_STRONG", "NOMINATION_BORDERLINE", "NOMINATION_POOR")
        },
        "SUSPECT_REVIEW_COUNT": len(samples),
        "VALIDATION_HEALTH": "PASS_WITH_REVIEW_SUBSET",
        "TRAIN_SOURCE_OVERLAP": "NONE",
        "TRAIN_VALIDATION_LEAKAGE": "NONE",
        "leakage_checks": overlap,
        "BLIND_TOUCHED": "NO",
        "TRAINING_DATA_FREEZE": "DEFERRED",
        "READY_FOR_COLAB_TRAINING_PREFLIGHT": "NO",
        "NEXT_ACTION": "Independent re-review of the eight recommended validation samples only; preserve originals and valid AMBIGUOUS labels, then resolve disagreements explicitly before final freeze/pre-flight",
        "BACKGROUND_TASKS_CREATED": "NO",
        "MODEL_TRAINED": "NO",
        "COLAB_STARTED": "NO",
        "PRODUCTION_CODE_CHANGED": "NO",
        "DXF_CHANGED": "NO",
        "OCR_CHANGED": "NO",
        "by_drawing": human["by_drawing"],
        "by_source_family": human["by_source_family"],
        "by_target_kind": human["by_target_kind"],
        "effective_dpi": human["DPI_DISTRIBUTION"],
        "quality_by_class_reporting_only": summary["quality_by_class_reporting_only"],
        "unsuspected_subset": {
            "count": len(outside),
            "classes": dict(outside_classes),
            "nomination_quality": dict(
                Counter(r["nomination_quality"] for r in outside)
            ),
        },
        "train_current_classes": dict(train_counts),
        "train_ambiguity_coverage_limit": "Current adjudicated train seed has zero AMBIGUOUS examples. After review, a separate pre-flight must explicitly address four-class training support or a documented abstention policy; do not silently drop validation class 4.",
        "dpi_coverage_limit": "37 PDF samples at effective render DPI 110, 13 TIFF samples with unknown physical DPI. This supports a small bounded initial comparison, not known multi-DPI robustness.",
        "safety_metric_limit": "18 labeled true parallels are adequate for an initial pilot comparison, not a production false-merge safety estimate. A zero-error run would still leave substantial statistical uncertainty; no model metrics have been measured.",
        "target_coverage_limit": "PAIR has 18 parallels, only two singles and two ambiguous cases; report PAIR-only safety/performance separately to detect target-kind shortcuts and do not claim broad paired-stroke recall from two positives.",
        "original_input_identity": summary["protected_input_hashes"],
        "correspondence_audit_sha256": sha(
            DOCS / "validation-v2-001-correspondence-audit.jsonl"
        ),
        "suspect_recommendation_sha256": sha(
            DOCS / "validation-suspect-review-recommendation.json"
        ),
        "health_reason": "22 singles/18 parallels, four structurally represented independent families plus a fifth control family, 14% OTHER, no poor source correspondence or leakage; 42 samples outside bounded review (19 singles/16 parallels/7 OTHER), so usable validation needs a small review, not full relabeling or a systemic quality-failure designation.",
        "human_uncertainty_policy": "No existing class is declared wrong or changed. STRONG measures target correspondence, not guaranteed semantic truth. AMBIGUOUS is a valid label and may stay AMBIGUOUS after independent review.",
    }
    atomic_json(DOCS / "VALIDATION-FINAL-AUDIT.json", result)
    summary.update(
        visual_review_status="COMPLETED_50_CLASS_UNANNOTATED_CONTACT_VIEWS_AND_9_CONTEXT_DETAILS",
        validation_health=result["VALIDATION_HEALTH"],
        suspect_review_count=len(samples),
        human_answers_changed=False,
        final_truth_freeze_created=False,
    )
    atomic_json(summary_path, summary)
    lines = ["# P3B VALIDATION FINAL AUDIT", "", "```text"]
    for key in (
        "AUDIT_RECOVERED",
        "EXISTING_HUMAN_AUDIT_RERUN",
        "TOTAL_REVIEWED",
        "READY",
        "EXCLUDED",
        "BAD_NOMINATION_X",
        "UNCLEAR_TARGET_U",
        "SKIPPED",
        "NOMINATION_STRONG",
        "NOMINATION_BORDERLINE",
        "NOMINATION_POOR",
        "SUSPECT_REVIEW_COUNT",
        "VALIDATION_HEALTH",
        "TRAIN_SOURCE_OVERLAP",
        "TRAIN_VALIDATION_LEAKAGE",
        "BLIND_TOUCHED",
        "TRAINING_DATA_FREEZE",
        "READY_FOR_COLAB_TRAINING_PREFLIGHT",
        "BACKGROUND_TASKS_CREATED",
        "MODEL_TRAINED",
        "COLAB_STARTED",
        "PRODUCTION_CODE_CHANGED",
        "DXF_CHANGED",
        "OCR_CHANGED",
    ):
        lines.append(f"{key}: {result[key]}")
    lines += ["```", "", "| Human class | Count |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in result["CLASS_DISTRIBUTION"].items()]
    lines += [
        "",
        "The original one-time audit completed successfully and was recovered without rerunning it or relaunching the UI. Its manifest/state hashes, all grouped counts and full history/undo replay match the final saved state: 50 durable presentations, 72 presentation-log entries, 14 undos, one session, no class before prior V, no zero-source-support Stage 1 and no inconsistent X/U overwrite.",
        "",
        "READY=50 describes persisted valid V+class records, not final acceptance of all semantic truth. Final validation acceptance/freeze is deferred pending the bounded subset below. Original answers and audit artifacts remain unchanged.",
        "",
    ]
    for title, key in (
        ("Drawing breakdown", "by_drawing"),
        ("Source-family breakdown", "by_source_family"),
        ("PAIR / SINGLE / CONTROL", "by_target_kind"),
        ("Effective DPI", "effective_dpi"),
    ):
        lines += [
            f"## {title}",
            "",
            "| Group | Reviewed / ready | Excluded | Single | Parallel | Other | Ambiguous |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, group in result[key].items():
            c = group["classes"]
            lines.append(
                f"| {name} | {group['total']} / {group['ready']} | {group['excluded']} | {c.get('SINGLE_PHYSICAL_STROKE', 0)} | {c.get('TRUE_PARALLEL_STRUCTURE', 0)} | {c.get('OTHER', 0)} | {c.get('AMBIGUOUS', 0)} |"
            )
        lines.append("")
    lines += [
        "## Independent nomination audit",
        "",
        "All 50 nomination qualities were computed before attaching human classes, using only source pixels, geometry and explicit ROI. Seven selected source pages were re-rendered/re-read, and every crop matched its frozen SHA256 and cache pixels. The post-label-independent-v1 policy is the same accepted policy used for the formal seed: ink threshold 180, 0.5px probes, 1.5px support radius; support, mean/p95 ink distance, endpoints, local tangent alignment, bounds, overlap, length ratio and pair separation stability. No human class entered quality computation.",
        "",
        "Controls use supported explicit ROI ink/bounds; line metrics are not applicable. Slight endpoint/extent/alignment defects produce BORDERLINE, not POOR, while target/source identity remains defensible. Source geometry and production P3A are untouched. All 50 class-unannotated contact views and nine expanded source/overlay/context detail views were inspected; generated previews live only in the external regenerable validation cache.",
        "",
        "| Human class (reporting only) | Strong | Borderline | Poor |",
        "|---|---:|---:|---:|",
    ]
    for cls, q in result["quality_by_class_reporting_only"].items():
        lines.append(
            f"| {cls} | {q.get('NOMINATION_STRONG', 0)} | {q.get('NOMINATION_BORDERLINE', 0)} | {q.get('NOMINATION_POOR', 0)} |"
        )
    lines += [
        "",
        "## Bounded suspect recommendation",
        "",
        "Review only these eight in the listed priority order. Three class-4 decisions are valid uncertainty, not errors: retain class 4 if context cannot resolve them. No expected class is assigned; original classes must be hidden before independent re-review. Rank 41 is a semantic boundary concern despite strong ink correspondence, not a poor nomination. No suspect UI/state has been prepared or launched in this task.",
        "",
        "| Rank | Sample ID | Saved class (audit only) | Nomination | Review reason |",
        "|---:|---|---|---|---|",
    ]
    for item in samples:
        lines.append(
            f"| {item['queue_rank']} | {item['sample_id']} | {item['human_class']} | {item['nomination_quality']} | {'; '.join(item['review_reasons'])} |"
        )
    lines += [
        "",
        "Recommendation: `validation-suspect-review-recommendation.json`. It preserves original rank/ID/V/class, source identities, metrics and reasons. A future re-review must write a separate state. Do not silently resolve disagreement or train on a disputed decision.",
        "",
        "## Health and next phase",
        "",
        result["health_reason"],
        "",
        result["human_uncertainty_policy"],
        "",
        "All drawing/family/source-file/crop/sample-ID intersections with the train manifest are empty; the existing verification also checks exact leakage against the full train pool. Frozen split assignments are unchanged; blind-source inventory metadata is never used to open a blind file. Original audits and protected state hashes remain unchanged.",
        "",
        result["dpi_coverage_limit"],
        "",
        result["target_coverage_limit"],
        "",
        result["safety_metric_limit"],
        "",
        result["train_ambiguity_coverage_limit"],
        "",
        "The train seed remains accepted at 94 current labels (38 SINGLE, 20 PARALLEL, 36 OTHER) across 13 drawings / 12 families. Final validation truth and a training-data freeze are DEFERRED. No new training-data freeze manifest or copied final validation truth was created. Existing historical evidence freezes are preserved.",
        "",
        "After a separately authorized bounded review and explicit resolution, reassess validation health. Only then consider an exact train/validation data freeze and a separate Colab/training pre-flight. The future pre-flight would verify the requested official Colab MCP source and installation, interactive login, Drive access, checkpoint write/read/resume, staging frozen train/validation only, and a classical Logistic Regression baseline before any CNN decision. None of those actions was performed or scheduled here.",
        "",
        "## Evidence hashes",
        "",
        "| Protected input | SHA256 |",
        "|---|---|",
    ]
    lines += [
        f"| {path} | {value} |"
        for path, value in result["original_input_identity"].items()
    ]
    lines += [
        "",
        "No packages, model training, account connections, Drive mount, Colab session, UI launch, production/DXF/OCR changes, heartbeat, timer, polling, watcher or background job. All 157 production app/test files match the retained snapshot.",
        "",
        "NEXT_ACTION: " + result["NEXT_ACTION"],
        "",
        "STOP.",
        "",
    ]
    path = DOCS / "VALIDATION-FINAL-AUDIT.md"
    temp = path.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(path)
    for path, expected in summary["protected_input_hashes"].items():
        if sha(path) != expected:
            raise ValueError(
                "Protected human evidence changed while writing derived report"
            )
    print(
        {
            k: v
            for k, v in result.items()
            if isinstance(v, (str, int)) or k == "CLASS_DISTRIBUTION"
        },
        flush=True,
    )


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
