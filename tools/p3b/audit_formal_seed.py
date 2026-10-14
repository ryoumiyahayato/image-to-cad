"""Audit completed human seed labels only; no training or source access."""

import argparse
from collections import Counter, defaultdict

from audit_acceptance import audit_state
from common import LABELS, atomic_json, read, read_rows, sha
from pilot_audit import DOCS

MANIFEST = DOCS / "formal-seed-v2-001.jsonl"
STATE = DOCS / "labels/formal-seed-v2-001.json"


def completed_ids(state, rows):
    """V alone is not completion; a deliberate skip is an explicit disposition."""
    result = set()
    for row in rows:
        sid = row["sample_id"]
        status = state["nomination_statuses"].get(sid, {}).get("status")
        if (
            sid in state["skipped"]
            or status in ("INVALID_NOMINATION", "UNCLEAR_TARGET")
            or (status == "VALID_TARGET" and sid in state["labels"])
        ):
            result.add(sid)
    return result


def counts(state, rows):
    statuses, classes = Counter(), Counter()
    skipped = valid_unclassified = 0
    for row in rows:
        sid = row["sample_id"]
        status = state["nomination_statuses"].get(sid, {}).get("status")
        label = state["labels"].get(sid, {}).get("label")
        statuses[status] += 1
        if status == "VALID_TARGET" and label:
            classes[label] += 1
        if status == "VALID_TARGET" and not label:
            valid_unclassified += 1
        skipped += sid in state["skipped"]
    return {
        "TOTAL_REVIEWED": len(completed_ids(state, rows)),
        "VALID_TARGET": statuses["VALID_TARGET"],
        "INVALID_NOMINATION": statuses["INVALID_NOMINATION"],
        "UNCLEAR_TARGET": statuses["UNCLEAR_TARGET"],
        **{c: classes[c] for c in LABELS},
        "VALID_BUT_UNCLASSIFIED": valid_unclassified,
        "SKIPPED": skipped,
        "NO_STAGE0_STATUS": statuses[None],
    }


def assess(state, rows, summary, consistent):
    """Transparent seed-distribution diagnostics, never training authorization."""
    reasons, support = [], {}
    reviewed_nomination = sum(
        summary[k] for k in ("VALID_TARGET", "INVALID_NOMINATION", "UNCLEAR_TARGET")
    )
    failure_rate = (summary["INVALID_NOMINATION"] + summary["UNCLEAR_TARGET"]) / max(
        reviewed_nomination, 1
    )
    for label in LABELS[:2]:
        labeled = [
            r
            for r in rows
            if state["labels"].get(r["sample_id"], {}).get("label") == label
            and state["nomination_statuses"].get(r["sample_id"], {}).get("status")
            == "VALID_TARGET"
        ]
        support[label] = {
            "count": len(labeled),
            "drawings": len({r["source_drawing_id"] for r in labeled}),
            "source_families": len({r["source_family_id"] for r in labeled}),
        }
        if (
            len(labeled) < 20
            or support[label]["drawings"] < 3
            or support[label]["source_families"] < 2
        ):
            reasons.append(
                f"{label} needs support: proposed minimum 20 labels across 3 drawings / 2 source families"
            )
    class_count = sum(summary[c] for c in LABELS)
    other_fraction = summary["OTHER"] / max(class_count, 1)
    drawings = Counter(r["source_drawing_id"] for r in rows)
    families = Counter(r["source_family_id"] for r in rows)
    if other_fraction > 0.60:
        reasons.append(
            "OTHER exceeds 60% of classified valid targets; add targeted structural examples"
        )
    if summary["VALID_BUT_UNCLASSIFIED"] > 0:
        reasons.append(
            "Valid targets remain unclassified; complete deliberate deferrals before seed approval"
        )
    if summary["NO_STAGE0_STATUS"] > 0:
        reasons.append(
            "Deliberate skips without Stage 0 remain; obtain nomination decisions before seed approval"
        )
    if max(drawings.values(), default=0) / max(len(rows), 1) > 0.25:
        reasons.append("One drawing exceeds 25% of the seed")
    if max(families.values(), default=0) / max(len(rows), 1) > 0.35:
        reasons.append("One source family exceeds 35% of the seed")
    if not consistent or failure_rate > 0.05:
        health = "NOMINATION_QUALITY_FAIL"
        reasons.insert(
            0,
            "Saved-state inconsistency or X/U rate above 5%; resolve nomination/UI failures first",
        )
    else:
        health = "NEED_TARGETED_MORE_LABELS" if reasons else "PASS"
    return {
        "FORMAL_SEED_HEALTH": health,
        "reasons": reasons,
        "structural_class_support": support,
        "x_u_rate_among_stage0_reviewed": failure_rate,
        "other_fraction_of_classes": other_fraction,
        "independent_validation_batch_preparation_assessment": "Distribution supports proposing an independent validation batch; sources remain unopened and approval is still required"
        if health == "PASS"
        else "Resolve listed seed/nomination gaps before proposing validation labeling",
        "criteria_provenance": "Proposed diagnostic thresholds for this 100-sample seed: V2 nomination quality >=95%, each structural class >=20 across >=3 drawings / >=2 families, OTHER <=60%, no unclassified V or missing Stage 0, drawing <=25%, family <=35%. These are not learned-model safety or training entry criteria.",
    }


def run():
    rows, state = read_rows(MANIFEST), read(STATE)
    plan = read(DOCS / "formal-seed-v2-summary.json")
    if (
        len(rows) != 100
        or sha(MANIFEST) != plan["manifest_sha256"]
        or any(r["split"] != "train" for r in rows)
    ):
        raise ValueError("Prepared train queue identity changed; do not regenerate")
    if len(completed_ids(state, rows)) != 100:
        print({"STATUS": "IN_PROGRESS", **counts(state, rows)})
        return
    audit = audit_state(state, rows, sha(MANIFEST))
    summary = counts(state, rows)
    result = {
        **summary,
        **assess(
            state, rows, summary, audit.get("FINAL_STATE_INTERNALLY_CONSISTENT", False)
        ),
        "state_sha256": sha(STATE),
        "manifest_sha256": sha(MANIFEST),
        "split_manifest_sha256": sha(DOCS / "split-manifest.json"),
        "saved_state_audit": {
            k: v for k, v in audit.items() if k != "TRACEABLE_TARGET_RATE"
        },
        "training_authorized": False,
        "model_trained": False,
        "validation_sources_opened": 0,
        "blind_sources_opened": 0,
        "production_code_changed": False,
        "breakdowns": {},
    }
    for field in ("source_drawing_id", "source_family_id", "target_kind"):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[field]].append(row)
        result["breakdowns"][field] = {
            key: counts(state, group) for key, group in sorted(grouped.items())
        }
    atomic_json(DOCS / "FORMAL-SEED-V2-001-AUDIT.json", result)
    lines = [
        "# P3B formal human seed 001 — completed audit",
        "",
        "Final human decisions only. No training or validation/blind source access.",
        "",
        "```text",
    ]
    lines.extend(f"{key}: {value}" for key, value in summary.items())
    lines.extend(
        [
            f"FORMAL_SEED_HEALTH: {result['FORMAL_SEED_HEALTH']}",
            "TRAINING_AUTHORIZED: NO",
            "```",
            "",
            result["criteria_provenance"],
            "",
            "## Assessment",
            "",
        ]
    )
    lines.extend("- " + reason for reason in result["reasons"])
    if not result["reasons"]:
        lines.append("The proposed seed-distribution checks pass.")
    lines.extend(
        ["", result["independent_validation_batch_preparation_assessment"], ""]
    )
    for field, breakdown in result["breakdowns"].items():
        lines.extend(
            [
                "## " + field,
                "",
                "| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | V unclassified | Skipped |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for key, item in breakdown.items():
            values = [
                item[k]
                for k in (
                    "TOTAL_REVIEWED",
                    "VALID_TARGET",
                    "INVALID_NOMINATION",
                    "UNCLEAR_TARGET",
                    *LABELS,
                    "VALID_BUT_UNCLASSIFIED",
                    "SKIPPED",
                )
            ]
            lines.append("| " + key + " | " + " | ".join(map(str, values)) + " |")
        lines.append("")
    lines.extend(
        [
            "Full history/schema/identity audit: `FORMAL-SEED-V2-001-AUDIT.json`.",
            "",
            "The user's and reviewer's seed-distribution approval is still required before any training. No validation batch was opened or generated. STOP.",
            "",
        ]
    )
    report = DOCS / "FORMAL-SEED-V2-001-AUDIT.md"
    temp = report.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(report)
    print(
        {
            k: v
            for k, v in result.items()
            if k not in ("saved_state_audit", "breakdowns")
        }
    )


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
