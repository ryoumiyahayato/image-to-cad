"""A single foreground 13-sample re-review; completion is a UI event, not a watcher."""

import argparse
import copy
import hashlib
from collections import Counter
from pathlib import Path

from PIL import Image

from audit_acceptance import audit_state
from common import LABELS, atomic_json, digest, read, read_rows, sha, write_rows
from label_ui import LabelApp, diverse_order
from pilot_audit import CACHE, DOCS

MANIFEST = DOCS / "suspect-review-v2-001.jsonl"
LABEL_STATE = DOCS / "labels/suspect-review-v2-001.json"
ORIGINALS = DOCS / "suspect-review-v2-001-original-evidence.json"
PLAN = DOCS / "suspect-review-v2-001-plan.json"
ORDER = [1, 40, 65, 4, 46, 66, 68, 72, 75, 81, 84, 93, 100]


def save_identical_or_new(path, value, rows=False):
    if path.exists():
        existing = read_rows(path) if rows else read(path)
        if digest(existing) != digest(value):
            raise ValueError(
                f"Existing review artifact differs: {path}; do not overwrite"
            )
    elif rows:
        write_rows(path, value)
    else:
        atomic_json(path, value)


def prepare():
    recommendation = read(DOCS / "formal-seed-suspect-review-recommendation.json")
    frozen = read(DOCS / "formal-seed-freeze.json")
    original_state_path = DOCS / "labels/formal-seed-v2-001.json"
    original_manifest_path = DOCS / "formal-seed-v2-001.jsonl"
    if (
        sha(original_state_path) != frozen["label_state_sha256"]
        or sha(original_manifest_path) != frozen["manifest_sha256"]
    ):
        raise ValueError("Original human evidence changed after freeze")
    if (
        recommendation["state_sha256"] != frozen["label_state_sha256"]
        or recommendation["manifest_sha256"] != frozen["manifest_sha256"]
    ):
        raise ValueError("Recommendations belong to another original state")
    originals = read(original_state_path)
    source_rows = diverse_order(read_rows(original_manifest_path))
    selected = recommendation["samples"]
    if len(selected) != 13 or [r["queue_rank"] for r in selected] != ORDER:
        raise ValueError(
            "Only the exact 13 recommendations in the requested order may enter"
        )
    rows, evidence = [], []
    for item in selected:
        row = copy.deepcopy(source_rows[item["queue_rank"] - 1])
        sid = row["sample_id"]
        if sid != item["sample_id"] or row["split"] != "train":
            raise ValueError("Original identity/rank or train boundary mismatch")
        evidence.append(
            {
                "sample_id": sid,
                "original_rank": item["queue_rank"],
                "original_stage0": originals["nomination_statuses"][sid],
                "original_stage1": originals["labels"][sid],
                "original_correspondence_audit_reasons": item["reasons"],
            }
        )
        # No original answer or audit reason enters the displayed review manifest.
        row.update(
            original_sample_id=sid,
            original_rank=item["queue_rank"],
            pool_version="suspect-review-v2-001",
            label=None,
            label_provenance=None,
            nomination_status=None,
            queue_purpose="13-sample independent suspect re-review; no training authorized",
            training_authorized=False,
        )
        folder = CACHE / "real-v2-formal-seed-001" / row["patch_dir"]
        with Image.open(folder / "gray.png") as image:
            if (
                hashlib.sha256(image.convert("L").tobytes()).hexdigest()
                != row["patch_sha256"]
            ):
                raise ValueError("Original target pixels changed")
        for name in ("context.png", "support.png"):
            if not (folder / name).is_file():
                raise ValueError("Accepted V2 context/diagnostic missing")
        rows.append(row)
    save_identical_or_new(
        ORIGINALS,
        {
            "original_manifest_sha256": frozen["manifest_sha256"],
            "original_state_sha256": frozen["label_state_sha256"],
            "samples": evidence,
            "purpose": "Immutable historical evidence; never displayed before re-review answers",
        },
    )
    save_identical_or_new(MANIFEST, rows, rows=True)
    plan = {
        "batch": "suspect-review-v2-001",
        "sample_count": 13,
        "original_rank_order": ORDER,
        "manifest_sha256": sha(MANIFEST),
        "original_evidence_sha256": sha(ORIGINALS),
        "original_manifest_sha256": frozen["manifest_sha256"],
        "original_state_sha256": frozen["label_state_sha256"],
        "labels_path": str(LABEL_STATE),
        "patch_root": str(CACHE / "real-v2-formal-seed-001"),
        "original_answers_shown_before_new_decision": False,
        "training_authorized": False,
        "background_monitor": False,
    }
    save_identical_or_new(PLAN, plan)
    print(
        {
            "prepared_samples": 13,
            "original_rank_order": ORDER,
            "labels_path": str(LABEL_STATE),
        },
        flush=True,
    )


def compare(rows, originals, new_state, base_audit):
    """Both answers survive; disagreement is never resolved by preferring a class."""
    originals_by_id = {r["sample_id"]: r for r in originals["samples"]}
    result = {
        "TOTAL_REVIEWED": len(rows),
        "EXACT_AGREEMENT": 0,
        "STAGE0_DISAGREEMENT": 0,
        "STAGE1_DISAGREEMENT": 0,
        "CONFIRMED_TRUE_PARALLEL": 0,
        "CONFIRMED_OTHER": 0,
        "REVISED_TO_SINGLE": 0,
        "REVISED_TO_PARALLEL": 0,
        "REVISED_TO_OTHER": 0,
        "REVISED_TO_AMBIGUOUS": 0,
        "REVISED_TO_X_OR_U": 0,
        "disagreements": [],
        "sample_comparisons": [],
    }
    confirmed = Counter()
    revised_keys = dict(
        zip(
            LABELS,
            (
                "REVISED_TO_SINGLE",
                "REVISED_TO_PARALLEL",
                "REVISED_TO_OTHER",
                "REVISED_TO_AMBIGUOUS",
            ),
        )
    )
    for row in rows:
        sid = row["sample_id"]
        old = originals_by_id[sid]
        old_status = old["original_stage0"]["status"]
        old_class = old["original_stage1"]["label"]
        new_status = new_state["nomination_statuses"].get(sid, {}).get("status")
        new_class = new_state["labels"].get(sid, {}).get("label")
        if new_status not in ("INVALID_NOMINATION", "UNCLEAR_TARGET") and not (
            new_status == "VALID_TARGET" and new_class in LABELS
        ):
            raise ValueError(
                "Re-review is incomplete; do not produce a 13-sample result"
            )
        stage0_diff = new_status != old_status
        stage1_diff = (
            old_status == new_status == "VALID_TARGET" and old_class != new_class
        )
        agreement = not stage0_diff and not stage1_diff
        item = {
            "sample_id": sid,
            "original_rank": old["original_rank"],
            "original_stage0": old_status,
            "new_stage0": new_status,
            "original_class": old_class,
            "new_class": new_class,
            "audit_reason": old["original_correspondence_audit_reasons"],
            "review_result": "CONFIRMED" if agreement else "ADJUDICATION_REQUIRED",
            "training_authorized": False,
        }
        result["sample_comparisons"].append(item)
        result["STAGE0_DISAGREEMENT"] += stage0_diff
        result["STAGE1_DISAGREEMENT"] += stage1_diff
        if agreement:
            result["EXACT_AGREEMENT"] += 1
            confirmed[old_class] += 1
        else:
            result["disagreements"].append(item)
            if new_status in ("INVALID_NOMINATION", "UNCLEAR_TARGET"):
                result["REVISED_TO_X_OR_U"] += 1
            else:
                result[revised_keys[new_class]] += 1
    result["CONFIRMED_TRUE_PARALLEL"] = confirmed["TRUE_PARALLEL_STRUCTURE"]
    result["CONFIRMED_OTHER"] = confirmed["OTHER"]
    accepted = Counter(
        r["human_class"] for r in base_audit if r["TRAINING_REVIEW_STATUS"] == "READY"
    )
    accepted.update(confirmed)
    disputed = len(result["disagreements"])
    result["SEED_RESULT"] = {
        "TRAINING_READY_LABELS": sum(accepted.values()),
        "CONFIRMED_SINGLE": accepted["SINGLE_PHYSICAL_STROKE"],
        "CONFIRMED_TRUE_PARALLEL": accepted["TRUE_PARALLEL_STRUCTURE"],
        "CONFIRMED_OTHER": accepted["OTHER"],
        "EXCLUDED": sum(
            r["TRAINING_REVIEW_STATUS"] == "EXCLUDE_NOMINATION" for r in base_audit
        ),
        "ADJUDICATION_REQUIRED": disputed,
        "CONFIRMED_AMBIGUOUS": accepted["AMBIGUOUS"],
    }
    result["FORMAL_SEED_FINAL_STATUS"] = "NEEDS_ADJUDICATION" if disputed else "PASS"
    result["RECOMMENDED_NEXT_ACTION"] = (
        "ADJUDICATE DISPUTED SAMPLES ONLY"
        if disputed
        else "PREPARE INDEPENDENT VALIDATION LABELING"
    )
    result["training_authorized"] = False
    return result


def finish(app):
    plan = read(PLAN)
    if (
        sha(DOCS / "labels/formal-seed-v2-001.json") != plan["original_state_sha256"]
        or sha(DOCS / "formal-seed-v2-001.jsonl") != plan["original_manifest_sha256"]
    ):
        raise ValueError("Original evidence changed; stop without choosing an answer")
    rows = read_rows(MANIFEST)
    history = audit_state(app.store.state, rows, sha(MANIFEST), presentation_order=rows)
    if not history.get("FINAL_STATE_INTERNALLY_CONSISTENT"):
        raise ValueError(
            f"Re-review history/schema inconsistent: {history['INTERNAL_ERRORS']}"
        )
    result = compare(
        rows,
        read(ORIGINALS),
        app.store.state,
        read_rows(DOCS / "formal-seed-correspondence-audit.jsonl"),
    )
    result.update(
        original_state_sha256=plan["original_state_sha256"],
        re_review_state_sha256=sha(LABEL_STATE),
        re_review_manifest_sha256=sha(MANIFEST),
        saved_history_audit=history,
        background_tasks_created=False,
        next_action_started=False,
        stage1_disagreement_definition="Compared only when both Stage-0 decisions are V; X/U changes are Stage-0 disagreements",
        seed_count_definition="Accepted original 82 READY labels plus exact re-review agreements; no disputed old or new class is included. CONFIRMED seed counts do not claim independent re-review of the original 82.",
    )
    atomic_json(DOCS / "SUSPECT-REVIEW-V2-001-RESULT.json", result)
    lines = ["# P3B 13-sample suspect re-review result", "", "```text"]
    lines.extend(
        f"{k}: {v}"
        for k, v in result.items()
        if isinstance(v, (int, str))
        and k
        not in (
            "original_state_sha256",
            "re_review_state_sha256",
            "re_review_manifest_sha256",
            "stage1_disagreement_definition",
            "seed_count_definition",
        )
    )
    lines.extend(["```", "", "## Seed result", "", "```text"])
    lines.extend(f"{k}: {v}" for k, v in result["SEED_RESULT"].items())
    lines.extend(
        [
            "```",
            "",
            result["seed_count_definition"],
            "",
            result["stage1_disagreement_definition"],
            "",
            "Five original exclusions stay excluded. A new X/U that conflicts with original V remains an adjudication case, not a silently resolved exclusion.",
            "",
            "## Disputed samples only",
            "",
            "| Sample ID | Original rank | Original class | New stage/class | Audit reason |",
            "|---|---:|---|---|---|",
        ]
    )
    for item in result["disagreements"]:
        lines.append(
            f"| {item['sample_id']} | {item['original_rank']} | {item['original_class']} | {item['new_stage0']} / {item['new_class']} | {', '.join(item['audit_reason'])} |"
        )
    if not result["disagreements"]:
        lines.append(
            "No disputed samples. All 13 independently re-reviewed answers agree."
        )
    lines.extend(
        [
            "",
            "Both original and new records remain preserved. No disputed label is training-eligible. No model, validation data, production geometry, DXF, OCR, Colab, Drive, recurring job or background monitor was used. No next action was started. Training still requires user/reviewer approval. STOP.",
            "",
        ]
    )
    report = DOCS / "SUSPECT-REVIEW-V2-001-RESULT.md"
    temp = report.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(report)
    print(
        "RE_REVIEW_COMPLETE "
        + str(
            {
                k: v
                for k, v in result.items()
                if k not in ("sample_comparisons", "saved_history_audit")
            }
        ),
        flush=True,
    )
    # This runs once in the foreground UI's final decision callback. No polling/timer.
    app.window.quit()


def launch():
    import tkinter as tk

    plan = read(PLAN)
    root = tk.Tk()
    app = LabelApp(
        root,
        MANIFEST,
        LABEL_STATE,
        "local-reviewer-re-review",
        Path(plan["patch_root"]),
        "suspect-review",
        on_complete=finish,
    )
    print(
        "RE_REVIEW_UI_OPEN — 13 samples; separate empty/resumable state; original classes hidden",
        flush=True,
    )
    if app.index < len(app.rows):
        root.mainloop()
    root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    if args.launch:
        launch()
