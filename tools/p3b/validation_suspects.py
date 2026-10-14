"""Exact eight-sample foreground re-review with explicit human completion.

Original answers are immutable, absent from the displayed review manifest.
Completion compares both histories, applies the current user's adjudication
rule in a separate derived view, and freezes train/validation only. No models,
package installations, blind access, polling, scheduling or background monitor.
"""

import argparse
import copy
import hashlib
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from audit_acceptance import audit_state
from common import (
    LABELS,
    atomic_json,
    digest,
    product_snapshot,
    read,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from label_ui import LabelApp, diverse_order
from pilot_audit import DOCS
from review_suspects import save_identical_or_new
from validation_review import (
    ASSETS,
    MANIFEST as ORIGINAL_MANIFEST,
    OUT,
    STATE as ORIGINAL_STATE,
)

MANIFEST = DOCS / "validation-suspect-v2-001.jsonl"
STATE = DOCS / "labels/validation-suspect-v2-001.json"
ORIGINALS = DOCS / "validation-suspect-v2-001-original-evidence.json"
PLAN = DOCS / "validation-suspect-v2-001-plan.json"
ADJUDICATED = DOCS / "validation-adjudicated-decisions.jsonl"
RESULT = DOCS / "VALIDATION-SUSPECT-REVIEW-FINAL.json"
FREEZE = DOCS / "TRAINING-DATA-FREEZE.json"
ORDER = [16, 41, 30, 6, 17, 33, 13, 36]
PURPOSE = "8-sample independent validation suspect re-review; no training authorized"
POLICY = {
    "recommended_route": "A",
    "recommendation": "Three-class SINGLE / TRUE_PARALLEL / OTHER classifier plus separately evaluated abstention/confidence policy",
    "reason": "The 94 accepted train labels contain no AMBIGUOUS examples. Ambiguity here reflects unresolved source interpretation rather than a consistently observed fourth physical structure. An initial three-class baseline avoids an unsupported learned fourth class; four-class learning requires genuine train ambiguity evidence (route B), never fabricated balance.",
    "retention": "Every human AMBIGUOUS label remains in frozen validation truth. Evaluate these separately as ambiguity/abstention cases alongside unambiguous classification, with all-sample coverage and failure reporting; never remap class 4 to another class or silently remove it.",
    "limits": "Low confidence is not guaranteed to detect human ambiguity or wrong high-confidence predictions. Evaluate abstention on the independent ambiguous subset; report its small size. Threshold selection must avoid fitting to these eight review answers. This recommendation requires later explicit training authorization and leaves production safety vetoes intact.",
    "fourth_probability": "Do not fabricate a learned/calibrated AMBIGUOUS probability from a three-class model; any later API abstention mapping must be explicitly documented.",
    "training_authorized": False,
}


def prepare():
    recommendation = read(DOCS / "validation-suspect-review-recommendation.json")
    rows, state = diverse_order(read_rows(ORIGINAL_MANIFEST)), read(ORIGINAL_STATE)
    audit = read(DOCS / "VALIDATION-V2-001-AUDIT.json")
    if (
        recommendation["review_rank_order"] != ORDER
        or recommendation["review_count"] != 8
        or sha(ORIGINAL_MANIFEST) != recommendation["manifest_sha256"]
        or sha(ORIGINAL_STATE) != recommendation["state_sha256"]
        or sha(DOCS / "VALIDATION-V2-001-AUDIT.json")
        != recommendation["original_audit_sha256"]
        or sha(DOCS / "validation-v2-001-correspondence-audit.jsonl")
        != recommendation["correspondence_audit_sha256"]
    ):
        raise ValueError("Accepted recommendation/original validation identity changed")
    history = audit_state(state, rows, sha(ORIGINAL_MANIFEST))
    if (
        not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or history != audit["history_audit"]
    ):
        raise ValueError("Original saved validation history is inconsistent")
    selected, evidence = [], []
    for rank, item in zip(ORDER, recommendation["samples"], strict=True):
        original = rows[rank - 1]
        sid = original["sample_id"]
        if (
            item["queue_rank"] != rank
            or item["sample_id"] != sid
            or original["split"] != "validation"
        ):
            raise ValueError("Only the eight accepted suspects may enter")
        if (
            state["labels"][sid]["label"] != item["original_stage1"]
            or state["nomination_statuses"][sid]["status"] != item["original_stage0"]
        ):
            raise ValueError("Recommended original decision mismatch")
        evidence.append(
            {
                "sample_id": sid,
                "original_rank": rank,
                "original_stage0": state["nomination_statuses"][sid],
                "original_stage1": state["labels"][sid],
                "nomination_quality": item["nomination_quality"],
                "independent_metrics": item["independent_metrics"],
                "review_reasons": item["review_reasons"],
                "original_sample_sha256": digest(original),
            }
        )
        row = copy.deepcopy(original)
        row.update(
            original_rank=rank,
            original_sample_id=sid,
            pool_version="validation-suspect-v2-001",
            label=None,
            label_provenance=None,
            nomination_status=None,
            training_authorized=False,
            queue_purpose=PURPOSE,
        )
        selected.append(row)
    save_identical_or_new(MANIFEST, selected, rows=True)
    save_identical_or_new(
        ORIGINALS,
        {
            "manifest_sha256": sha(ORIGINAL_MANIFEST),
            "state_sha256": sha(ORIGINAL_STATE),
            "samples": evidence,
        },
    )
    protected_names = [
        "validation-v2-001.jsonl",
        "labels/validation-v2-001.json",
        "VALIDATION-V2-001-AUDIT.json",
        "VALIDATION-V2-001-AUDIT.md",
        "validation-suspect-review-recommendation.json",
        "validation-v2-001-correspondence-audit.jsonl",
        "VALIDATION-FINAL-AUDIT.json",
        "validation-v2-001-plan.json",
        "formal-seed-v2-001.jsonl",
        "labels/formal-seed-v2-001.json",
        "labels/suspect-review-v2-001.json",
        "formal-seed-adjudicated-decisions.jsonl",
        "FORMAL-SEED-FINAL-STATUS.json",
        "split-manifest.json",
    ]
    save_identical_or_new(
        PLAN,
        {
            "batch": "validation-suspect-v2-001",
            "count": 8,
            "original_rank_order": ORDER,
            "manifest_sha256": sha(MANIFEST),
            "original_evidence_sha256": sha(ORIGINALS),
            "labels_path": str(STATE),
            "patch_root": str(OUT),
            "protected_input_hashes": {
                str(DOCS / name): sha(DOCS / name) for name in protected_names
            },
            "original_classes_shown": False,
            "training_authorized": False,
            "background_tasks_created": False,
        },
    )
    verify()
    print(
        "VALIDATION_SUSPECT_QUEUE_PREPARED: exact eight; original classes hidden; independent state",
        flush=True,
    )


def verify(manifest=MANIFEST, labels=STATE, patch_root=OUT):
    plan = read(PLAN)
    if (
        Path(manifest).resolve() != MANIFEST.resolve()
        or Path(labels).resolve() != STATE.resolve()
        or patch_root is None
        or Path(patch_root).resolve() != OUT.resolve()
    ):
        raise ValueError(
            "Wrong re-review manifest/state/cache; originals cannot be overwritten"
        )
    for path, expected in plan["protected_input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Immutable original evidence/accepted seed changed")
    rows = read_rows(MANIFEST)
    originals = diverse_order(read_rows(ORIGINAL_MANIFEST))
    if (
        sha(MANIFEST) != plan["manifest_sha256"]
        or sha(ORIGINALS) != plan["original_evidence_sha256"]
        or len(rows) != 8
        or [r["original_rank"] for r in rows] != ORDER
    ):
        raise ValueError("The exact eight-sample queue/evidence changed")
    source_paths = set()
    parent_plan = read(DOCS / "validation-v2-001-plan.json")
    assignments = {
        r["source_drawing_id"]: r
        for r in read(DOCS / "split-manifest.json")["drawings"]
    }
    for rank, row in zip(ORDER, rows, strict=True):
        expected = copy.deepcopy(originals[rank - 1])
        expected.update(
            original_rank=rank,
            original_sample_id=expected["sample_id"],
            pool_version="validation-suspect-v2-001",
            label=None,
            label_provenance=None,
            nomination_status=None,
            training_authorized=False,
            queue_purpose=PURPOSE,
        )
        if (
            row != expected
            or row["split"] != "validation"
            or assignments[row["source_drawing_id"]]["split"] != "validation"
        ):
            raise ValueError(
                "Re-review includes altered source/geometry/labels or a wrong split"
            )
        if row["source_path"] not in source_paths:
            if sha(row["source_path"]) != row["source_sha256"]:
                raise ValueError("Selected validation source changed")
            source_paths.add(row["source_path"])
        folder = (OUT / row["patch_dir"]).resolve()
        if OUT.resolve() not in folder.parents:
            raise ValueError("Patch cache escape")
        for name in ASSETS:
            if (
                sha(folder / name)
                != parent_plan["asset_sha256"][row["patch_dir"] + "/" + name]
            ):
                raise ValueError("Accepted display assets changed")
        with Image.open(folder / "gray.png") as im:
            if (
                hashlib.sha256(im.convert("L").tobytes()).hexdigest()
                != row["patch_sha256"]
            ):
                raise ValueError("Re-review source pixels changed")
    validate_samples(rows)
    if STATE.exists():
        history = audit_state(read(STATE), rows, sha(MANIFEST), presentation_order=rows)
        errors = [
            e
            for e in history["INTERNAL_ERRORS"]
            if e != "missing durable presentations"
        ]
        if errors:
            raise ValueError(f"Re-review state history inconsistent: {errors}")
    return rows


def compare(rows, originals, state):
    old_by_id = {r["sample_id"]: r for r in originals["samples"]}
    result = {
        "TOTAL_REVIEWED": len(rows),
        "EXACT_AGREEMENT": 0,
        "STAGE0_DISAGREEMENT": 0,
        "STAGE1_DISAGREEMENT": 0,
        "DISAGREEMENTS": [],
        "sample_comparisons": [],
    }
    for suffix in ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS"):
        result["CONFIRMED_" + suffix] = 0
        result["REVISED_TO_" + suffix] = 0
    result["REVISED_TO_X_OR_U"] = 0
    suffixes = dict(
        zip(LABELS, ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS"), strict=True)
    )
    for row in rows:
        sid = row["sample_id"]
        old = old_by_id[sid]
        new0 = state["nomination_statuses"].get(sid, {}).get("status")
        new1 = state["labels"].get(sid, {}).get("label")
        old0, old1 = old["original_stage0"]["status"], old["original_stage1"]["label"]
        if sid in state["skipped"] or not (
            new0 in ("INVALID_NOMINATION", "UNCLEAR_TARGET")
            or (new0 == "VALID_TARGET" and new1 in LABELS)
        ):
            raise ValueError(
                "All eight require complete independent decisions; no skip or V alone"
            )
        diff0 = old0 != new0
        diff1 = old0 == new0 == "VALID_TARGET" and old1 != new1
        item = {
            "sample_id": sid,
            "original_rank": old["original_rank"],
            "original_stage0": old0,
            "original_class": old1,
            "new_stage0": new0,
            "new_class": new1,
            "review_reasons": old["review_reasons"],
            "exact_agreement": not (diff0 or diff1),
            "current_resolution": "CONFIRMED"
            if not (diff0 or diff1)
            else "USER_AUTHORIZED_ADJUDICATED_RE_REVIEW",
            "training_authorized": False,
        }
        result["STAGE0_DISAGREEMENT"] += int(diff0)
        result["STAGE1_DISAGREEMENT"] += int(diff1)
        result["sample_comparisons"].append(item)
        if not (diff0 or diff1):
            result["EXACT_AGREEMENT"] += 1
            result["CONFIRMED_" + suffixes[new1]] += 1
        else:
            result["DISAGREEMENTS"].append(item)
            key = (
                "REVISED_TO_X_OR_U"
                if new0 in ("INVALID_NOMINATION", "UNCLEAR_TARGET")
                else "REVISED_TO_" + suffixes[new1]
            )
            result[key] += 1
    return result


def adjudicate(parent_rows, original_state, review_rows, new_state):
    reviewed = {r["sample_id"]: r for r in review_rows}
    effective = []
    for rank, row in enumerate(diverse_order(parent_rows), 1):
        sid = row["sample_id"]
        state = new_state if sid in reviewed else original_state
        stage0 = state["nomination_statuses"][sid]
        stage1 = state["labels"].get(sid)
        ready = stage0["status"] == "VALID_TARGET" and stage1 is not None
        effective.append(
            {
                "sample_id": sid,
                "original_rank": rank,
                "source_drawing_id": row["source_drawing_id"],
                "source_family_id": row["source_family_id"],
                "source_sha256": row["source_sha256"],
                "manifest_sample_sha256": digest(row),
                "original_stage0": original_state["nomination_statuses"][sid],
                "original_stage1": original_state["labels"].get(sid),
                "re_review_stage0": new_state["nomination_statuses"].get(sid),
                "re_review_stage1": new_state["labels"].get(sid),
                "current_stage0": stage0["status"],
                "current_class": stage1["label"] if stage1 else None,
                "current_decision_provenance": "user_authorized_complete_valid_independent_re_review"
                if sid in reviewed
                else "accepted_original_validation_human_review",
                "current_review_status": "READY" if ready else "EXCLUDED",
                "training_authorized": False,
            }
        )
    return effective


def describe_split(rows, truth):
    by_id = {r["sample_id"]: r for r in rows}
    ready, excluded = [], []
    groups = defaultdict(list)
    dpi = Counter()
    classes = Counter()
    for item in truth:
        row = by_id[item["sample_id"]]
        groups[(row["source_drawing_id"], row["source_family_id"])].append(
            row["sample_id"]
        )
        if item["current_review_status"] == "READY":
            ready.append(item["sample_id"])
            classes[item["current_class"]] += 1
            dpi[
                "UNKNOWN_SOURCE_DPI"
                if row["source_dpi"] is None
                else f"{row['source_dpi']:.6f}"
            ] += 1
        else:
            excluded.append(
                {
                    "sample_id": item["sample_id"],
                    "status": item["current_stage0"],
                    "class": item["current_class"],
                }
            )
    return {
        "included_sample_ids": sorted(ready),
        "excluded_samples": excluded,
        "class_distribution": {label: classes[label] for label in LABELS},
        "included_count": len(ready),
        "excluded_count": len(excluded),
        "source_identities": [
            {"drawing": d, "family": f, "sample_ids": sorted(ids)}
            for (d, f), ids in sorted(groups.items())
        ],
        "effective_dpi_distribution_included": dict(dpi),
        "ambiguous_sample_ids": sorted(
            i["sample_id"] for i in truth if i["current_class"] == "AMBIGUOUS"
        ),
    }


def freeze_data(validation_truth):
    train_rows, val_rows = (
        read_rows(DOCS / "formal-seed-v2-001.jsonl"),
        read_rows(ORIGINAL_MANIFEST),
    )
    train_truth = read_rows(DOCS / "formal-seed-adjudicated-decisions.jsonl")
    final_train = read(DOCS / "FORMAL-SEED-FINAL-STATUS.json")
    if (
        final_train["FORMAL_SEED_FINAL_STATUS"] != "PASS"
        or final_train["DISPUTED_REMAINING"]
    ):
        raise ValueError("Train seed is not accepted")
    validate_samples(train_rows + val_rows)
    leakage = {
        key: sorted({r[key] for r in train_rows} & {r[key] for r in val_rows})
        for key in (
            "sample_id",
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
        )
    }
    if any(leakage.values()):
        raise ValueError("Train/validation leakage; no freeze")
    assignments = {
        r["source_drawing_id"]: r
        for r in read(DOCS / "split-manifest.json")["drawings"]
    }
    for expected_split, rows in (("train", train_rows), ("validation", val_rows)):
        for row in rows:
            a = assignments[row["source_drawing_id"]]
            if (
                row["split"] != expected_split
                or a["split"] != expected_split
                or a["source_family_id"] != row["source_family_id"]
            ):
                raise ValueError("Frozen source-family split changed")
    folder = DOCS / "frozen/training-data-v2-001"
    folder.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for source, name in (
        (
            DOCS / "formal-seed-adjudicated-decisions.jsonl",
            "train-adjudicated-truth.jsonl",
        ),
        (ADJUDICATED, "validation-adjudicated-truth.jsonl"),
    ):
        target = folder / name
        if target.exists() and sha(target) != sha(source):
            raise ValueError("Existing frozen truth differs; do not overwrite history")
        if not target.exists():
            shutil.copyfile(source, target)
        snapshots[name] = {"path": str(target), "sha256": sha(target)}
    train = describe_split(train_rows, train_truth)
    validation = describe_split(val_rows, validation_truth)
    if train["included_count"] != 94:
        raise ValueError("Adjudicated train truth differs from accepted 94")
    train.update(
        manifest_sha256=sha(DOCS / "formal-seed-v2-001.jsonl"),
        original_label_state_sha256=sha(DOCS / "labels/formal-seed-v2-001.json"),
        re_review_state_sha256=sha(DOCS / "labels/suspect-review-v2-001.json"),
        adjudication_sha256=sha(DOCS / "formal-seed-adjudicated-decisions.jsonl"),
    )
    validation.update(
        manifest_sha256=sha(ORIGINAL_MANIFEST),
        original_label_state_sha256=sha(ORIGINAL_STATE),
        re_review_manifest_sha256=sha(MANIFEST),
        re_review_state_sha256=sha(STATE),
        adjudication_sha256=sha(ADJUDICATED),
    )
    frozen = {
        "dataset_version": "p3b-train-validation-freeze-v2-001",
        "TRAINING_DATA_FREEZE": "READY",
        "train": train,
        "validation": validation,
        "snapshots": snapshots,
        "split_manifest_sha256": sha(DOCS / "split-manifest.json"),
        "source_family_splits": {
            "train": sorted({r["source_family_id"] for r in train_rows}),
            "validation": sorted({r["source_family_id"] for r in val_rows}),
        },
        "leakage_checks": leakage,
        "TRAIN_VALIDATION_LEAKAGE": "NONE",
        "BLIND_TOUCHED": "NO",
        "AMBIGUOUS_POLICY": POLICY,
        "training_authorized": False,
        "model_trained": False,
        "colab_started": False,
        "background_tasks_created": False,
        "scope": "Exact current adjudicated truth; excludes V1/acceptance labels and every blind source. Ambiguous human truth retained, not class-balanced or fabricated.",
    }
    save_identical_or_new(FREEZE, frozen)
    return frozen


def finish():
    rows = verify()
    state = read(STATE)
    before = sha(STATE)
    history = audit_state(state, rows, sha(MANIFEST), presentation_order=rows)
    if (
        not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or history["PRESENTATIONS_PERSISTED"] != 8
    ):
        raise ValueError(
            "Eight-sample saved state is incomplete/inconsistent; no adjudication/freeze"
        )
    result = compare(rows, read(ORIGINALS), state)
    effective = adjudicate(
        read_rows(ORIGINAL_MANIFEST), read(ORIGINAL_STATE), rows, state
    )
    result.update(
        DISPUTED_REMAINING=0,
        VALIDATION_FINAL_STATUS="PASS",
        FINAL_VALIDATION_EXCLUDED=sum(
            r["current_review_status"] == "EXCLUDED" for r in effective
        ),
    )
    counts = Counter(
        r["current_class"] for r in effective if r["current_review_status"] == "READY"
    )
    for label, suffix in zip(
        LABELS, ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS"), strict=True
    ):
        result["FINAL_VALIDATION_" + suffix] = counts[label]
    if product_snapshot() != read(DOCS / "pilot-production-before.json"):
        raise ValueError("Production snapshot changed; stop without freeze")
    write_rows(ADJUDICATED, effective)
    frozen = freeze_data(effective)
    if sha(STATE) != before:
        raise ValueError("Re-review changed during finalization")
    result.update(
        TRAINING_DATA_FREEZE="READY",
        AMBIGUOUS_TRAINING_POLICY=POLICY,
        READY_FOR_COLAB_TRAINING_PREFLIGHT="YES",
        BLIND_TOUCHED="NO",
        BACKGROUND_TASKS_CREATED="NO",
        MODEL_TRAINED="NO",
        COLAB_STARTED="NO",
        training_authorized=False,
        adjudication_authority="Current user explicitly authorized completed internally valid re-review as current truth. Every disagreement remains reported alongside both preserved historical answers.",
        history_audit=history,
        re_review_state_sha256=before,
        original_state_sha256=sha(ORIGINAL_STATE),
        original_manifest_sha256=sha(ORIGINAL_MANIFEST),
        re_review_manifest_sha256=sha(MANIFEST),
        adjudication_sha256=sha(ADJUDICATED),
        training_data_freeze_sha256=sha(FREEZE),
        TRAIN_VALIDATION_LEAKAGE="NONE",
        NEXT_ACTION="Separate explicitly authorized Colab/training pre-flight; no training now",
    )
    atomic_json(RESULT, result)
    lines = ["# P3B VALIDATION SUSPECT REVIEW FINAL", "", "```text"]
    keys = [
        "TOTAL_REVIEWED",
        "EXACT_AGREEMENT",
        "STAGE0_DISAGREEMENT",
        "STAGE1_DISAGREEMENT",
    ]
    keys += [
        "CONFIRMED_" + s for s in ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS")
    ]
    keys += [
        "REVISED_TO_" + s
        for s in ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS", "X_OR_U")
    ]
    keys += ["VALIDATION_FINAL_STATUS", "DISPUTED_REMAINING"] + [
        "FINAL_VALIDATION_" + s
        for s in ("SINGLE", "TRUE_PARALLEL", "OTHER", "AMBIGUOUS", "EXCLUDED")
    ]
    keys += [
        "TRAINING_DATA_FREEZE",
        "READY_FOR_COLAB_TRAINING_PREFLIGHT",
        "TRAIN_VALIDATION_LEAKAGE",
        "BLIND_TOUCHED",
        "MODEL_TRAINED",
        "COLAB_STARTED",
        "BACKGROUND_TASKS_CREATED",
    ]
    lines += [f"{k}: {result[k]}" for k in keys]
    lines += [
        "```",
        "",
        "Stage-1 disagreement is compared only when both Stage-0 answers are V. X/U changes are Stage-0 disagreement. Every new complete decision is current under the user's explicit rule; no disagreement has been silently discarded.",
        "",
        "## Disagreements",
        "",
        "| Rank | Sample ID | Original decision | New/current decision | Review reason |",
        "|---:|---|---|---|---|",
    ]
    for item in result["DISAGREEMENTS"]:
        lines.append(
            f"| {item['original_rank']} | {item['sample_id']} | {item['original_stage0']} / {item['original_class']} | {item['new_stage0']} / {item['new_class']} | {'; '.join(item['review_reasons'])} |"
        )
    if not result["DISAGREEMENTS"]:
        lines += [
            "No disagreements. All eight independent decisions agree with the originals."
        ]
    lines += [
        "",
        "Both historical records remain unchanged. Current adjudication: `validation-adjudicated-decisions.jsonl`. Exact freeze: `TRAINING-DATA-FREEZE.json`, with immutable current-truth snapshots, original/re-review state and manifest hashes, sample IDs, distributions, source-family splits, effective DPI, exclusions and ambiguity policy. No blind files were opened.",
        "",
        "## AMBIGUOUS training policy",
        "",
        "Technically preferable initial route: **A — three-class baseline plus abstention policy**.",
        "",
        POLICY["reason"],
        "",
        POLICY["retention"],
        "",
        POLICY["limits"],
        "",
        POLICY["fourth_probability"],
        "",
        f"Accepted train labels: {frozen['train']['included_count']}; excluded train: {frozen['train']['excluded_count']}. Final included validation: {frozen['validation']['included_count']}; excluded validation: {frozen['validation']['excluded_count']}.",
        "",
        "READY_FOR_COLAB_TRAINING_PREFLIGHT means the data are frozen and ready for a separate authorized infrastructure/policy/checkpoint-resume check, not authorization to install/connect/train. Later authorization is still required. No production/DXF/OCR code or outputs changed; all 157 production app/test files match the retained snapshot.",
        "",
        "NEXT_ACTION: " + result["NEXT_ACTION"],
        "",
        "STOP.",
        "",
    ]
    path = DOCS / "VALIDATION-SUSPECT-REVIEW-FINAL.md"
    temp = path.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(path)
    print(
        "VALIDATION_SUSPECT_FINALIZED "
        + str({k: v for k, v in result.items() if isinstance(v, (str, int))}),
        flush=True,
    )
    return result


def launch():
    import tkinter as tk
    from tkinter import messagebox

    verify()
    root = tk.Tk()
    root.protocol("WM_DELETE_WINDOW", root.quit)
    offered = False

    def offer_finish(app):
        nonlocal offered
        if offered:
            return
        offered = True
        app.note.set(
            "All eight answers are saved. Finish & finalize compares both histories and freezes current truth if valid. No training starts."
        )

        def complete():
            try:
                result = finish()
            except (ValueError, KeyError) as error:
                messagebox.showerror(
                    "Saved-state finalization", str(error), parent=root
                )
                return
            messagebox.showinfo(
                "Validation review finalized",
                f"{result['VALIDATION_FINAL_STATUS']} — {result['EXACT_AGREEMENT']}/8 exact agreements; {len(result['DISAGREEMENTS'])} reported changes.\nCurrent truth frozen. No training started.\nReport: VALIDATION-SUSPECT-REVIEW-FINAL.md",
                parent=root,
            )
            root.quit()

        tk.Button(
            root,
            text="Finish & finalize — compare, adjudicate and freeze only",
            command=complete,
        ).pack(pady=8)
        print(
            "ALL_EIGHT_SAVED — waiting for human Finish & finalize; no polling/monitor",
            flush=True,
        )

    LabelApp(
        root,
        MANIFEST,
        STATE,
        "local-reviewer-validation-re-review",
        OUT,
        "validation-suspect",
        on_complete=offer_finish,
    )
    root.update_idletasks()
    root.lift()
    root.focus_force()
    print(
        "VALIDATION_SUSPECT_UI_OPEN — eight only; exact requested order; original classes hidden; independent atomic state",
        flush=True,
    )
    root.mainloop()
    root.destroy()
    print(
        "VALIDATION_SUSPECT_UI_CLOSED — answers preserved; no background task",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--launch", action="store_true")
    actions.add_argument("--finish", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.launch:
        launch()
    elif args.finish:
        finish()
