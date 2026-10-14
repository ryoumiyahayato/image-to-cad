"""Assemble the manual recovery report from bound foreground audit evidence."""

from collections import Counter, defaultdict

from audit_formal_seed import counts
from common import LABELS, atomic_json, read, read_rows, sha, write_rows
from label_ui import diverse_order
from pilot_audit import DOCS

# Manual visual object ownership, not OCR output or a replacement physical label.
OWNERSHIP_EXCEPTIONS = {
    10: (
        "COMPOUND_SYMBOL",
        "Two boundaries of a boxed code inside a circular legend symbol",
    ),
    49: (
        "GRAPHIC_OBJECT",
        "Frame of an annotation stamp; nominated frame, not its lettering",
    ),
    81: (
        "COMPOUND_SYMBOL",
        "Boxed stylized mark near branding; exact semantic identity is not asserted",
    ),
}
OWNERSHIP_CATEGORIES = (
    "TEXT_OR_DIGIT",
    "COMPOUND_SYMBOL",
    "GRAPHIC_OBJECT",
    "FILL_OR_HATCH",
    "ARTIFACT_OR_NOISE",
    "OTHER_OTHER",
)


def table(groups, state, quality_by_id):
    lines = [
        "| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | Skip | V unclassified | Ready | Review | Exclude |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, rows in sorted(groups.items(), key=lambda x: str(x[0])):
        c = counts(state, rows)
        review = Counter(
            quality_by_id[r["sample_id"]]["TRAINING_REVIEW_STATUS"] for r in rows
        )
        values = [
            c[k]
            for k in (
                "TOTAL_REVIEWED",
                "VALID_TARGET",
                "INVALID_NOMINATION",
                "UNCLEAR_TARGET",
                *LABELS,
                "SKIPPED",
                "VALID_BUT_UNCLASSIFIED",
            )
        ]
        values.extend(
            review[k] for k in ("READY", "REVIEW_RECOMMENDED", "EXCLUDE_NOMINATION")
        )
        lines.append("| " + str(key) + " | " + " | ".join(map(str, values)) + " |")
    return lines


def assemble():
    manifest = DOCS / "formal-seed-v2-001.jsonl"
    label_file = DOCS / "labels/formal-seed-v2-001.json"
    state, rows = read(label_file), diverse_order(read_rows(manifest))
    frozen = read(DOCS / "formal-seed-freeze.json")
    nominal = read(DOCS / "FORMAL-SEED-V2-001-AUDIT.json")
    independent = read(DOCS / "formal-seed-post-audit-summary.json")
    evidence = read_rows(DOCS / "formal-seed-correspondence-audit.jsonl")
    if (
        sha(manifest) != frozen["manifest_sha256"]
        or sha(label_file) != frozen["label_state_sha256"]
        or nominal["state_sha256"] != sha(label_file)
    ):
        raise ValueError(
            "Evidence identity mismatch; stop without changing human answers"
        )
    if (
        independent["freeze"] != frozen
        or not nominal["saved_state_audit"]["FINAL_STATE_INTERNALLY_CONSISTENT"]
    ):
        raise ValueError("Independent audit binding or human history inconsistent")
    by_id = {r["sample_id"]: r for r in evidence}
    ownership = []
    for row in rows:
        audit = by_id[row["sample_id"]]
        if audit["human_nomination_status"] != state["nomination_statuses"][
            row["sample_id"]
        ]["status"] or audit["human_class"] != state["labels"].get(
            row["sample_id"], {}
        ).get("label"):
            raise ValueError("Derived evidence no longer matches human state")
        if audit["human_class"] == "OTHER":
            category, note = OWNERSHIP_EXCEPTIONS.get(
                audit["queue_rank"],
                (
                    "TEXT_OR_DIGIT",
                    "Nominated source ink lies in visible alphabetic/numeric/CJK glyphs or text tokens; no transcription asserted",
                ),
            )
            ownership.append(
                {
                    "sample_id": row["sample_id"],
                    "queue_rank": audit["queue_rank"],
                    "OTHER_CATEGORY": category,
                    "evidence_note": note,
                    "provenance": "manual_source_crop_and_exact_overlay_visual_review",
                    "human_class_unchanged": "OTHER",
                    "training_authorized": False,
                }
            )
    write_rows(DOCS / "formal-seed-other-ownership.jsonl", ownership)
    other_counts = Counter(r["OTHER_CATEGORY"] for r in ownership)
    recommendations = sorted(
        [r for r in evidence if r["TRAINING_REVIEW_STATUS"] == "REVIEW_RECOMMENDED"],
        key=lambda r: (r["human_class"] != "TRUE_PARALLEL_STRUCTURE", r["queue_rank"]),
    )
    if len(recommendations) > 20:
        raise ValueError("A bounded review recommendation may not exceed 20")
    recommended_set = [
        {
            "sample_id": r["sample_id"],
            "queue_rank": r["queue_rank"],
            "source_drawing_id": r["source_drawing_id"],
            "human_class": r["human_class"],
            "reasons": r["reasons"],
        }
        for r in recommendations
    ]
    # A recommendation only: no queue regeneration, patch extraction, or review UI launch.
    atomic_json(
        DOCS / "formal-seed-suspect-review-recommendation.json",
        {
            "state_sha256": sha(label_file),
            "manifest_sha256": sha(manifest),
            "recommended_sample_count": len(recommended_set),
            "samples": recommended_set,
            "queue_prepared_or_launched": False,
            "human_answers_modified": False,
            "purpose": "For a future explicitly requested bounded review; not training authorization",
        },
    )
    summary = counts(state, rows)
    valid = [
        r
        for r in evidence
        if r["human_nomination_status"] == "VALID_TARGET" and r["human_class"]
    ]
    quality_counts = Counter(r["nomination_quality"] for r in valid)
    training_counts = Counter(r["TRAINING_REVIEW_STATUS"] for r in evidence)
    quality_by_class = {
        c: dict(
            Counter(r["TRAINING_REVIEW_STATUS"] for r in valid if r["human_class"] == c)
        )
        for c in LABELS
    }
    family_counts = Counter(r["source_family_id"] for r in rows)
    decision = {
        "report": "FORMAL-SEED-V2-001 FINAL REPORT",
        "date": "2026-10-07 Asia/Taipei",
        "HEARTBEAT_STATUS": "NOT_PRESENT",
        **summary,
        "NOMINATION_STRONG": quality_counts["NOMINATION_STRONG"],
        "NOMINATION_BORDERLINE": quality_counts["NOMINATION_BORDERLINE"],
        "NOMINATION_POOR": quality_counts["NOMINATION_POOR"],
        "TRAINING_READY_LABELS": training_counts["READY"],
        "REVIEW_RECOMMENDED": training_counts["REVIEW_RECOMMENDED"],
        "EXCLUDED": training_counts["EXCLUDE_NOMINATION"],
        "OTHER_BREAKDOWN": {c: other_counts[c] for c in OWNERSHIP_CATEGORIES},
        "PAIR_CLASS_COUNTS": {
            c: sum(r["target_kind"] == "PAIR" and r["human_class"] == c for r in valid)
            for c in LABELS
        },
        "QUALITY_BY_CLASS": quality_by_class,
        "SOURCE_DIVERSITY": {
            "drawings": len({r["source_drawing_id"] for r in rows}),
            "source_families": len(family_counts),
            "largest_drawing_count": max(
                Counter(r["source_drawing_id"] for r in rows).values()
            ),
            "largest_family_count": max(family_counts.values()),
        },
        "FORMAL_SEED_HEALTH": "PASS_WITH_REVIEW_SUBSET",
        "RECOMMENDED_NEXT_ACTION": "B. REVIEW SMALL SUSPECT SUBSET",
        "WHY": "82 source-supported labels remain nominally ready (38 SINGLE, 18 TRUE_PARALLEL, 26 OTHER). Thirteen bounded PAIR nominations have imperfect endpoint/tangent support or unequal extents, including three TRUE_PARALLEL decisions. Recheck that subset before training; do not redo the 100 or treat slight overlay defects as human class errors.",
        "SIMPLIFIED_FUTURE_UI_JUSTIFIED": "YES",
        "SUSPECT_REVIEW_QUEUE": len(recommended_set),
        "suspect_review_is_recommendation_only": True,
        "training_authorized": False,
        "BACKGROUND_TASKS_CREATED": "NO",
        "manifest_sha256": sha(manifest),
        "label_state_sha256": sha(label_file),
        "audit_formal_seed_manual_runs_this_task": 1,
        "independent_correspondence_recomputed_in_foreground": True,
        "visual_quality_review": {
            "contact_sheets": 10,
            "presentations_inspected": 100,
            "class_predictions_displayed": False,
            "human_answers_changed": False,
        },
        "source_pages_opened": independent["source_pages_opened"],
        "validation_sources_opened": 0,
        "blind_sources_opened": 0,
        "next_action_started": False,
    }
    atomic_json(DOCS / "FORMAL-SEED-AUDIT.json", decision)
    independent["visual_review_status"] = (
        "COMPLETED_100_CLASS_UNANNOTATED_CONTACT_VIEWS"
    )
    independent["final_manual_report"] = "FORMAL-SEED-AUDIT.md"
    atomic_json(DOCS / "formal-seed-post-audit-summary.json", independent)
    lines = [
        "# FORMAL-SEED-V2-001 FINAL REPORT",
        "",
        "2026-10-07, Asia/Taipei. One manual foreground recovery task. The cancelled heartbeat remains absent.",
        "",
        "**FORMAL_SEED_HEALTH: PASS_WITH_REVIEW_SUBSET.** Recommend **B. REVIEW SMALL SUSPECT SUBSET**: 13 nominations, prioritizing three true-parallel decisions. This recommendation is not launched or prepared as another labeling run. No training is authorized.",
        "",
        "```text",
    ]
    lines.extend(
        f"{k}: {v}"
        for k, v in decision.items()
        if k
        in (
            "HEARTBEAT_STATUS",
            *summary.keys(),
            "NOMINATION_STRONG",
            "NOMINATION_BORDERLINE",
            "NOMINATION_POOR",
            "TRAINING_READY_LABELS",
            "REVIEW_RECOMMENDED",
            "EXCLUDED",
            "FORMAL_SEED_HEALTH",
            "SIMPLIFIED_FUTURE_UI_JUSTIFIED",
            "SUSPECT_REVIEW_QUEUE",
            "RECOMMENDED_NEXT_ACTION",
            "BACKGROUND_TASKS_CREATED",
        )
    )
    lines.extend(
        [
            "TRAINING_AUTHORIZED: NO",
            "NEXT_ACTION_STARTED: NO",
            "STOP",
            "```",
            "",
            "## Frozen human evidence",
            "",
            f"Manifest SHA256: `{sha(manifest)}`.",
            "",
            f"Label-state SHA256: `{sha(label_file)}`.",
            "",
            "All 100 reviewed; 385 durable history records and revision 385, with 24 undo actions and 201 remaining undo events. Full schema/history/manifest/sample-digest checks pass, with zero class-before-V or inconsistent X/U overwrite. The saved human answers and frozen copies remain byte-identical.",
            "",
            "No acceptance sample IDs overlap the formal queue. All final classes have fresh formal human source-review provenance after Stage 0; replay starts from empty state and reproduces every final record. Some underlying nomination IDs also exist in V1, which is source identity reuse, not class import. No V1 or acceptance decisions were copied.",
            "",
            "[formal-seed-freeze.json](formal-seed-freeze.json) records preserved identities; the frozen manifest/state are in `frozen/formal-seed-v2-001`. `audit_formal_seed.py` was run manually exactly once in this task. Its distribution-only PASS is refined here using the independent correspondence findings and the reviewer's reliability feedback.",
            "",
            "## Independent nomination quality",
            "",
            "Source crops were recomputed from 17 pages of the 13 frozen TRAIN drawings and verified against source/crop hashes and cached pixels. Candidate/source correspondence was recomputed before attaching human answers. No class is used as a quality input. Ten class-unannotated source/overlay contact sheets were visually inspected; no intended target was shifted or redrawn.",
            "",
            "Unlike the queue gate's interpolated distance lookup, this audit samples every 0.5 source pixel and uses exact Euclidean nearest-dark-pixel distances (threshold 180) plus tangent probes ±3 pixels. Edge coordinates may lie slightly outside a filled stroke; 1.5-pixel support tolerance avoids treating ordinary edge sampling as a bad nomination. These are pixel distances, not physical-width ground truth.",
            "",
            "Strong line correspondence requires support ≥98%, mean distance ≤1.1px, p95 ≤1.5px, endpoint and tangent alignment ≥95%, in-bounds displayed extents, pair length ratio ≥0.85, and separation range ≤1px. Borderline retains identifiable source objects with weaker alignment/support or unequal extents. Poor requires substantial unsupported/misaligned geometry, e.g. support <60%, mean >2.5px, tangent alignment <50%, severely missing bounds, or no defensible common pair extent. Slightly imperfect endpoints alone do not cause exclusion.",
            "",
            "Per-sample metrics include source support, mean/p95 distance, endpoint support, tangent agreement, bounds, pair overlap, length ratio and separation range/std/mean in [formal-seed-correspondence-audit.jsonl](formal-seed-correspondence-audit.jsonl). CONTROL has no line geometry: line metrics are explicitly not applicable, and its ROI bounds/source ink are evaluated instead. Bounded local candidates are not required to cover the entire page-wide rule; unequal partner extents are a review flag, not proof the human class is wrong.",
            "",
            "Among the 95 labeled V samples: **82 strong / 13 borderline / 0 poor**. All 13 borderline samples are PAIRs. The five human X/U nominations are excluded regardless of what pixel support measures, and are not included in that 95-sample quality denominator. READY is a derived source-correspondence eligibility flag, not a claim of perfect physical-class accuracy or permission to train.",
            "",
            "| Human class | READY | REVIEW_RECOMMENDED |",
            "|---|---:|---:|",
            "| SINGLE_PHYSICAL_STROKE | 38 | 0 |",
            "| TRUE_PARALLEL_STRUCTURE | 18 | 3 |",
            "| OTHER | 26 | 10 |",
            "| AMBIGUOUS | 0 | 0 |",
            "",
            "Original human V/X/U and classes are untouched. Any future AMBIGUOUS evidence stays ambiguous and is never a positive SINGLE/TRUE_PARALLEL example.",
            "",
            "## Human distribution and source/DPI breakdown",
            "",
            "PAIR_SINGLE_COUNT: 22; PAIR_TRUE_PARALLEL_COUNT: 21; PAIR_OTHER_COUNT: 16; PAIR_AMBIGUOUS_COUNT: 0. The remaining PAIR has human X.",
            "",
        ]
    )
    for field in ("target_kind", "source_drawing_id", "source_family_id", "source_dpi"):
        groups = defaultdict(list)
        for row in rows:
            key = (
                row[field]
                if row[field] is not None
                else "UNKNOWN — original raster physical DPI not available"
            )
            groups[key].append(row)
        lines.extend(["### " + field, "", *table(groups, state, by_id), ""])
    lines.extend(
        [
            "PDF/source-derived rasters retain their effective 110 or 240 DPI. The 15 unknown-DPI samples are original raster sources; requested rendering DPI is not substituted for unknown physical DPI.",
            "",
            "## OTHER ownership and future workflow",
            "",
            "| Category | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| {category} | {other_counts[category]} |"
        for category in OWNERSHIP_CATEGORIES
    )
    lines.extend(
        [
            "",
            "Manual taxonomy examines the nominated object, not every object visible in the crop. The two compound symbols are #10 (boxed code within circular legend) and #81 (boxed stylized mark near branding); the graphic object is #49 (annotation stamp frame). The remaining 33 are visible text/digit/glyph targets. No OCR recognition or semantic accuracy work was performed. Per-sample evidence is in [formal-seed-other-ownership.jsonl](formal-seed-other-ownership.jsonl); these categories do not replace the saved OTHER classes.",
            "",
            "The queue imposed substantial avoidable interaction: 33% of all presentations were obvious text/digit targets requiring V → OTHER, and 36% were outside the two structural classes. Actual category-specific time was not measured; some OTHER examples remain useful hard negatives, so these counts do not mean every such decision was wasted.",
            "",
            "**SIMPLIFIED_FUTURE_UI_JUSTIFIED: YES, with safeguards.** A future 1=one line, 2=two structural lines, 3=non-target, 4=source-class ambiguity, X=bad nomination workflow can reduce unnecessary two-stage interaction. Geometry quality must remain separately checked and recorded. X must never stand in for source ambiguity, and insufficient visualization must retain a distinct unclear-target disposition (U or equivalent). Only trusted, explicit source ownership may pre-filter text/graphics; do not blanket-filter by proximity to text boxes or exclude table/frame rules and mixed boundaries. Keep a small diverse curated OTHER set for safety evaluation. No simplified UI or ownership filter was implemented.",
            "",
            "## Seed health and one recommended next action",
            "",
            decision["WHY"],
            "",
            "The human seed has 38 SINGLE and 21 TRUE_PARALLEL labels across 10/9 drawings and 9/8 families respectively. The 82 READY labels include 18 source-supported true parallels, sufficient for a small exploratory baseline after acceptance, rather than a validated model or precise safety estimate. OTHER is 37.9% of labeled V samples; no catastrophic class imbalance is evident. Thirteen drawings and twelve source families are represented, with maximum drawing/family shares 10%/18%. X/U is 5%, at the previous nomination-quality threshold. No new systemic floating/missing-geometry family was found.",
            "",
            "Three borderline true-parallel labels are not automatically invalid: both rails are visible, but their extents differ. Confirming them could restore the full 21-class support. Zero AMBIGUOUS labels and the concentration of 12/21 true parallels in two A2 archives remain coverage limitations; do not invent ambiguous examples or expand training in this task.",
            "",
            "**B. REVIEW SMALL SUSPECT SUBSET** is the only recommended next action. Confirm the three structural decisions first, then the ten source-supported OTHER nominations with imperfect endpoint/tangent support or unequal extents. Do not repeat all 100. The nominal READY/REVIEW flags are approximate source-correspondence assessments; they do not accuse the reviewer of errors. Independent validation labeling is deferred until that bounded review is accepted. No next-action UI, dataset or validation batch was started.",
            "",
            "### Recommended 13 samples (not a launched review queue)",
            "",
            "| Original rank | Sample ID | Drawing | Saved class | Review reason |",
            "|---:|---|---|---|---|",
        ]
    )
    for row in recommended_set:
        lines.append(
            f"| {row['queue_rank']} | {row['sample_id']} | {row['source_drawing_id']} | {row['human_class']} | {', '.join(row['reasons'])} |"
        )
    lines.extend(
        [
            "",
            "[formal-seed-suspect-review-recommendation.json](formal-seed-suspect-review-recommendation.json) binds this recommendation to the frozen state. It contains no new geometry or human answers.",
            "",
            "No heartbeat, timer, watcher, scheduler, polling loop or background task was created. No training, ML installation, Colab/Drive access, validation/blind source access, production code, DXF or OCR changes occurred. Training remains forbidden until this audit and seed distribution are accepted by the user/reviewer. STOP.",
            "",
        ]
    )
    path = DOCS / "FORMAL-SEED-AUDIT.md"
    temp = path.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(path)
    if (
        sha(manifest) != frozen["manifest_sha256"]
        or sha(label_file) != frozen["label_state_sha256"]
    ):
        raise ValueError("Human evidence changed during report assembly")
    print(
        {
            k: decision[k]
            for k in (
                "TOTAL_REVIEWED",
                "NOMINATION_STRONG",
                "NOMINATION_BORDERLINE",
                "NOMINATION_POOR",
                "TRAINING_READY_LABELS",
                "REVIEW_RECOMMENDED",
                "EXCLUDED",
                "OTHER_BREAKDOWN",
                "FORMAL_SEED_HEALTH",
                "RECOMMENDED_NEXT_ACTION",
            )
        }
    )


if __name__ == "__main__":
    assemble()
