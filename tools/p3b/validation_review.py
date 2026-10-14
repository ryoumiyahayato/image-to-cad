"""One bounded validation UI and an explicitly invoked, read-only human-label audit.

No scheduler, timer, polling, training, prediction or blind-source access.
"""

import argparse
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from audit_acceptance import audit_state
from common import LABELS, atomic_json, read, read_rows, sha, validate_samples
from label_ui import LabelApp
from pilot_audit import DOCS
from quality import POLICY
from queue_dedup import deduplicate
from validation_v2 import MANIFEST, PLAN, STATE, OUT

PURPOSE = "independent validation labeling; no training authorized"
ASSETS = (
    "gray.png",
    "overlay.png",
    "support.png",
    "context.png",
    "edges.png",
    "centerline.png",
    "protection.png",
    "nodes.png",
)


def verify_batch(manifest=MANIFEST, labels=STATE, patch_root=OUT):
    """Fail closed on identity/ownership/split/leakage or changed source evidence."""
    plan = read(PLAN)
    final_path = DOCS / "FORMAL-SEED-FINAL-STATUS.json"
    final = read(final_path)
    rows = read_rows(manifest)
    if (
        Path(manifest).resolve() != MANIFEST.resolve()
        or Path(labels).resolve() != STATE.resolve()
        or patch_root is None
        or Path(patch_root).resolve() != OUT.resolve()
        or len(rows) != 50
        or plan["sample_count"] != 50
        or plan["manifest_sha256"] != sha(manifest)
        or plan["split_manifest_sha256"] != sha(DOCS / "split-manifest.json")
        or plan["final_train_status_sha256"] != sha(final_path)
        or final["FORMAL_SEED_FINAL_STATUS"] != "PASS"
        or final["DISPUTED_REMAINING"] != 0
        or plan["training_authorized"]
        or final["training_authorized"]
        or plan["quality_policy"] != POLICY
        or plan["visual_curation_status"] != "ALL_50_INSPECTED_READY"
        or plan["blind_sources_accessed"] != 0
        or sha(DOCS / "labels/formal-seed-v2-001.json")
        != final["original_state_sha256"]
        or sha(DOCS / "labels/suspect-review-v2-001.json")
        != final["re_review_state_sha256"]
        or sha(DOCS / "formal-seed-v2-001.jsonl") != final["original_manifest_sha256"]
    ):
        raise ValueError(
            "Validation must match the frozen bounded queue, valid adjudicated seed and separate state"
        )
    assignments = {
        r["source_drawing_id"]: r
        for r in read(DOCS / "split-manifest.json")["drawings"]
    }
    # Metadata inventory read is allowed; only selected validation files are opened.
    sources = {
        r["source_drawing_id"]: r
        for r in read(DOCS / "inventory.json")["sources"]
        if r["split"] == "validation" and r["availability"] == "AVAILABLE"
    }
    checked_sources, images = set(), {}
    for row in rows:
        sid = row["source_drawing_id"]
        source = sources.get(sid)
        assignment = assignments.get(sid, {})
        file = (
            next(
                (f for f in source["files"] if f["sha256"] == row["source_sha256"]),
                None,
            )
            if source
            else None
        )
        if (
            assignment.get("split") != "validation"
            or row["split"] != "validation"
            or assignment.get("source_family_id") != row["source_family_id"]
            or not file
            or Path(file["path"]).resolve() != Path(row["source_path"]).resolve()
            or row["source_page"] not in plan["page_selection"].get(sid, [])
            or row["label"] is not None
            or row["label_provenance"] is not None
            or row.get("nomination_status") is not None
            or row["training_authorized"]
            or row["label_contract"] != "p3b-label-v2"
            or not row["quality"]["HUMAN_QUEUE_ELIGIBLE"]
            or not (row["candidate_geometry"] or row["target_roi"])
            or (
                row["explicit_ownership"] == "SOURCE_NATIVE_TEXT_EXCLUSIVE_INK"
                and row["target_kind"] != "CONTROL"
            )
        ):
            raise ValueError(
                "Invalid validation source, split, fresh label state or nomination"
            )
        if file["path"] not in checked_sources:
            if sha(file["path"]) != file["sha256"]:
                raise ValueError("Validation source changed")
            checked_sources.add(file["path"])
        folder = (OUT / row["patch_dir"]).resolve()
        if OUT.resolve() not in folder.parents:
            raise ValueError("Patch path escapes the designated validation cache")
        for name in ASSETS:
            key = row["patch_dir"] + "/" + name
            if plan["asset_sha256"].get(key) != sha(folder / name):
                raise ValueError("Validation display/channel assets changed")
        with Image.open(folder / "gray.png") as im:
            gray = im.convert("L")
        if (
            gray.size != (256, 256)
            or hashlib.sha256(gray.tobytes()).hexdigest() != row["patch_sha256"]
        ):
            raise ValueError("Validation source crop identity mismatch")
        images[row["sample_id"]] = gray
    train = read_rows(DOCS / "real-candidates.jsonl")
    validate_samples(train + rows)
    if len({r["patch_sha256"] for r in rows}) != 50:
        raise ValueError("Duplicate validation inputs")
    _, duplicates, _ = deduplicate(
        rows, None, lambda r: images[r["sample_id"]], radius=320, hamming=24
    )
    if duplicates:
        raise ValueError("Validation queue contains repeated nominations")
    if STATE.exists():
        history = audit_state(read(STATE), rows, sha(MANIFEST))
        # Missing future presentations are expected while the reviewer is paused.
        errors = [
            e
            for e in history["INTERNAL_ERRORS"]
            if e != "missing durable presentations"
        ]
        if errors:
            raise ValueError(f"Saved validation history is inconsistent: {errors}")
    return rows


def disposition(row, state):
    sid = row["sample_id"]
    status = state["nomination_statuses"].get(sid, {}).get("status")
    label = state["labels"].get(sid, {}).get("label")
    if sid in state["skipped"]:
        return "EXCLUDED_SKIP"
    if status in ("INVALID_NOMINATION", "UNCLEAR_TARGET"):
        return "EXCLUDED_NOMINATION"
    if status == "VALID_TARGET" and label in LABELS:
        if (
            row.get("explicit_ownership") == "SOURCE_NATIVE_TEXT_EXCLUSIVE_INK"
            and label in LABELS[:2]
        ):
            return "EXCLUDED_OWNERSHIP_CONFLICT"
        return "READY"
    return "INCOMPLETE"


def summarize(rows, state):
    statuses = Counter(disposition(r, state) for r in rows)
    ready = [r for r in rows if disposition(r, state) == "READY"]
    classes = Counter(state["labels"][r["sample_id"]]["label"] for r in ready)

    def grouped(key):
        groups = defaultdict(list)
        for row in rows:
            groups[str(key(row))].append(row)
        return {
            group: {
                "total": len(items),
                "ready": sum(disposition(r, state) == "READY" for r in items),
                "excluded": sum(
                    disposition(r, state).startswith("EXCLUDED") for r in items
                ),
                "classes": dict(
                    Counter(
                        state["labels"][r["sample_id"]]["label"]
                        for r in items
                        if disposition(r, state) == "READY"
                    )
                ),
            }
            for group, items in sorted(groups.items())
        }

    return {
        "VALIDATION_REVIEWED": len(rows) - statuses["INCOMPLETE"],
        "VALIDATION_READY": len(ready),
        "VALIDATION_EXCLUDED": sum(
            n for k, n in statuses.items() if k.startswith("EXCLUDED")
        ),
        "SINGLE": classes[LABELS[0]],
        "TRUE_PARALLEL": classes[LABELS[1]],
        "OTHER": classes[LABELS[2]],
        "AMBIGUOUS": classes[LABELS[3]],
        "DRAWINGS": len({r["source_drawing_id"] for r in rows}),
        "SOURCE_FAMILIES": len({r["source_family_id"] for r in rows}),
        "V_X_U": dict(
            Counter(r["status"] for r in state["nomination_statuses"].values())
        ),
        "SKIPPED": len(state["skipped"]),
        "dispositions": dict(statuses),
        "by_drawing": grouped(lambda r: r["source_drawing_id"]),
        "by_source_family": grouped(lambda r: r["source_family_id"]),
        "by_target_kind": grouped(lambda r: r["target_kind"]),
        "DPI_DISTRIBUTION": grouped(
            lambda r: "UNKNOWN_SOURCE_DPI"
            if r["source_dpi"] is None
            else f"{r['source_dpi']:.6f}"
        ),
        "dpi_definition": "PDF effective rasterization DPI; native TIFF physical DPI unknown. No invented scan DPI.",
    }


def audit():
    rows = verify_batch()
    state = read(STATE)
    history = audit_state(state, rows, sha(MANIFEST))
    if not history.get("FINAL_STATE_INTERNALLY_CONSISTENT"):
        raise ValueError(
            f"Validation history inconsistent: {history['INTERNAL_ERRORS']}"
        )
    result = summarize(rows, state)
    if result["VALIDATION_REVIEWED"] != 50 or history["PRESENTATIONS_PERSISTED"] != 50:
        raise ValueError(
            "Validation is incomplete; V alone is not a completed disposition"
        )
    result.update(
        batch="validation-v2-001",
        state_sha256=sha(STATE),
        manifest_sha256=sha(MANIFEST),
        history_audit=history,
        model_trained=False,
        training_authorized=False,
        blind_sources_accessed=0,
        colab_started=False,
        background_tasks_created=False,
        next_action="STOP; training requires a later explicit instruction",
    )
    atomic_json(DOCS / "VALIDATION-V2-001-AUDIT.json", result)
    lines = ["# Independent validation human-label audit", "", "```text"]
    lines += [
        f"{k}: {result[k]}"
        for k in (
            "VALIDATION_REVIEWED",
            "VALIDATION_READY",
            "VALIDATION_EXCLUDED",
            "SINGLE",
            "TRUE_PARALLEL",
            "OTHER",
            "AMBIGUOUS",
            "DRAWINGS",
            "SOURCE_FAMILIES",
            "SKIPPED",
        )
    ]
    lines += [
        "```",
        "",
        "All presentations and saved decisions passed schema, source/manifest binding and history/undo replay.",
        "",
    ]
    for title in (
        "by_drawing",
        "by_source_family",
        "by_target_kind",
        "DPI_DISTRIBUTION",
    ):
        lines += [
            f"## {title}",
            "",
            "| Group | Presented | Ready | Excluded | Classes |",
            "|---|---:|---:|---:|---|",
        ]
        for name, item in result[title].items():
            lines.append(
                f"| {name} | {item['total']} | {item['ready']} | {item['excluded']} | {item['classes']} |"
            )
        lines.append("")
    lines += [
        result["dpi_definition"],
        "",
        "Human answers remain unchanged. No model training, blind-source access, production/DXF/OCR change, cloud session or recurring/background task. STOP.",
        "",
    ]
    path = DOCS / "VALIDATION-V2-001-AUDIT.md"
    temp = path.with_suffix(".md.tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.replace(path)
    print(
        "MANUAL_VALIDATION_AUDIT_COMPLETE "
        + str({k: v for k, v in result.items() if not isinstance(v, dict)}),
        flush=True,
    )
    return result


def launch():
    import tkinter as tk
    from tkinter import messagebox

    verify_batch()
    root = tk.Tk()
    root.protocol("WM_DELETE_WINDOW", root.quit)
    completed = False

    def offer_manual_audit(app):
        nonlocal completed
        if completed:
            return
        completed = True
        app.note.set(
            "All 50 decisions are saved. Click Finish & audit to run one manual audit, then stop. No training starts."
        )

        def finish():
            try:
                audit()
            except ValueError as error:
                messagebox.showerror("Saved-state audit", str(error), parent=root)
                return
            root.quit()

        tk.Button(
            root, text="Finish & audit — one manual saved-state audit", command=finish
        ).pack(pady=8)
        print(
            "VALIDATION_REVIEW_COMPLETE — waiting for human Finish & audit; no timer/monitor",
            flush=True,
        )

    LabelApp(
        root,
        MANIFEST,
        STATE,
        "local-reviewer-validation",
        OUT,
        "validation",
        on_complete=offer_manual_audit,
    )
    root.update_idletasks()
    root.lift()
    root.focus_force()
    print(
        "VALIDATION_UI_OPEN — 50 frozen validation-only samples; 1–4 / X / U; separate atomic resumable state",
        flush=True,
    )
    root.mainloop()
    root.destroy()
    print(
        "VALIDATION_UI_CLOSED — saved decisions preserved; no background task",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--verify", action="store_true")
    actions.add_argument("--launch", action="store_true")
    actions.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(f"VALIDATION_BATCH_INTEGRITY_PASS: {len(verify_batch())}")
    elif args.audit:
        audit()
    elif args.launch:
        launch()
