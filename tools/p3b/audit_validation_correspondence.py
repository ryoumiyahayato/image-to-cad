"""Foreground validation recovery and class-blind source-correspondence audit.

Does not rerun an already valid human-label audit, launch a UI, change answers,
train, access blind sources or create monitors. Human classes are attached only
after all nomination metrics have been computed from re-read source pixels.
"""

import argparse
import copy
import hashlib
from collections import Counter, defaultdict

from PIL import Image, ImageDraw

from audit_acceptance import audit_state
from common import atomic_json, read, sha, write_rows
from extract import raster
from label_ui import diverse_order
from pilot_audit import DOCS
from post_label_audit import POLICY, correspondence
from target_view import target_overlay
from validation_review import MANIFEST, OUT, STATE, summarize, verify_batch


def recover(rows):
    """Read-only verification of the existing audit; never call audit()."""
    state = read(STATE)
    existing = read(DOCS / "VALIDATION-V2-001-AUDIT.json")
    text = (DOCS / "VALIDATION-V2-001-AUDIT.md").read_text(encoding="utf-8")
    history = audit_state(state, rows, sha(MANIFEST))
    summary = summarize(rows, state)
    if (
        existing["manifest_sha256"] != sha(MANIFEST)
        or existing["state_sha256"] != sha(STATE)
        or existing["history_audit"] != history
        or not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or history["PRESENTATIONS_PERSISTED"] != 50
        or summary["VALIDATION_REVIEWED"] != 50
        or any(existing.get(k) != v for k, v in summary.items())
        or any(
            f"{key}: {existing[key]}" not in text
            for key in (
                "VALIDATION_REVIEWED",
                "VALIDATION_READY",
                "VALIDATION_EXCLUDED",
                "SINGLE",
                "TRUE_PARALLEL",
                "OTHER",
                "AMBIGUOUS",
                "SKIPPED",
            )
        )
    ):
        raise ValueError(
            "Existing audit is invalid; stop for one explicitly bounded manual audit recovery"
        )
    return state, existing


def measure(rows):
    """Only frozen validation source/geometry/ROI inputs, no human decisions."""
    grouped = defaultdict(list)
    for row in rows:
        if row["split"] != "validation":
            raise ValueError("Validation-only source audit")
        grouped[(row["source_drawing_id"], row["source_page"])].append(row)
    patches, quality = {}, {}
    for group in grouped.values():
        first = group[0]
        source, dpi = raster(
            {"path": first["source_path"], "sha256": first["source_sha256"]},
            first["source_page"],
            first["requested_render_dpi"],
        )
        if dpi != first["source_dpi"]:
            raise ValueError("Source render frame differs from the frozen nomination")
        for row in group:
            x, y, w, h = row["source_bbox"]
            patch = Image.new("L", (256, 256), 255)
            patch.paste(Image.fromarray(source[y : y + h, x : x + w]), (0, 0))
            if hashlib.sha256(patch.tobytes()).hexdigest() != row["patch_sha256"]:
                raise ValueError("Re-read validation source differs from frozen crop")
            with Image.open(OUT / row["patch_dir"] / "gray.png") as cached:
                if cached.convert("L").tobytes() != patch.tobytes():
                    raise ValueError("Cached validation pixels changed")
            # Explicitly remove class-related metadata before computing metrics.
            blind = {
                k: copy.deepcopy(row[k])
                for k in ("source_bbox", "candidate_geometry", "target_roi")
            }
            quality[row["sample_id"]] = correspondence(blind, patch)
            patches[row["sample_id"]] = patch
        print(
            f"SOURCE_CORRESPONDENCE {first['source_drawing_id']} page {first['source_page']}",
            flush=True,
        )
    return patches, quality


def run():
    rows = diverse_order(verify_batch())
    protected = (
        MANIFEST,
        STATE,
        DOCS / "VALIDATION-V2-001-AUDIT.json",
        DOCS / "VALIDATION-V2-001-AUDIT.md",
        DOCS / "labels/formal-seed-v2-001.json",
        DOCS / "labels/suspect-review-v2-001.json",
        DOCS / "formal-seed-adjudicated-decisions.jsonl",
        DOCS / "split-manifest.json",
    )
    before = {str(p): sha(p) for p in protected}
    state, recovered = recover(rows)
    patches, qualities = measure(rows)
    audited, counts, by_class = [], Counter(), defaultdict(Counter)
    for rank, row in enumerate(rows, 1):
        sid = row["sample_id"]
        label = state["labels"].get(sid, {}).get("label")
        q = qualities[sid]
        if label:
            counts[q["nomination_quality"]] += 1
            by_class[label][q["nomination_quality"]] += 1
        audited.append(
            {
                "sample_id": sid,
                "queue_rank": rank,
                "source_drawing_id": row["source_drawing_id"],
                "source_family_id": row["source_family_id"],
                "source_page": row["source_page"],
                "source_sha256": row["source_sha256"],
                "source_bbox": row["source_bbox"],
                "source_dpi": row["source_dpi"],
                "target_kind": row["target_kind"],
                "human_stage0": state["nomination_statuses"].get(sid, {}).get("status"),
                "human_class": label,
                "human_class_used_for_quality": False,
                **q,
            }
        )
    directory = OUT / "post-label-correspondence"
    directory.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), 10):
        canvas = Image.new("RGB", (1024, 1420), "white")
        draw = ImageDraw.Draw(canvas)
        for j, row in enumerate(rows[start : start + 10]):
            left, top = (j % 2) * 512, (j // 2) * 284
            draw.text(
                (left + 3, top + 3),
                f"#{start + j + 1} {row['target_kind']} {row['source_drawing_id']}",
                fill="black",
            )
            canvas.paste(patches[row["sample_id"]], (left, top + 25))
            canvas.paste(
                target_overlay(patches[row["sample_id"]], row, 1),
                (left + 256, top + 25),
            )
        canvas.save(
            directory / f"class-unannotated-{start + 1:03d}-{start + 10:03d}.png"
        )
    write_rows(DOCS / "validation-v2-001-correspondence-audit.jsonl", audited)
    summary = {
        "AUDIT_RECOVERED": True,
        "existing_human_audit_rerun": False,
        "existing_audit_sha256": before[str(DOCS / "VALIDATION-V2-001-AUDIT.json")],
        "manifest_sha256": before[str(MANIFEST)],
        "state_sha256": before[str(STATE)],
        "quality_counts_labeled_V": dict(counts),
        "quality_by_class_reporting_only": {k: dict(v) for k, v in by_class.items()},
        "independent_quality_policy": POLICY,
        "source_pages_re_read": [
            list(key)
            for key in sorted(
                {(r["source_drawing_id"], r["source_page"]) for r in rows}
            )
        ],
        "human_class_used_for_quality": False,
        "visual_contact_directory": str(directory),
        "visual_review_status": "PENDING",
        "human_result": recovered,
        "protected_input_hashes": before,
        "training_authorized": False,
        "model_trained": False,
        "blind_sources_accessed": 0,
        "background_tasks_created": False,
    }
    if any(sha(p) != before[str(p)] for p in protected):
        raise ValueError("Protected human evidence changed during audit; stop")
    atomic_json(DOCS / "validation-v2-001-post-audit-summary.json", summary)
    print(
        {
            "quality": dict(counts),
            "by_class": summary["quality_by_class_reporting_only"],
        },
        flush=True,
    )
    for item in audited:
        if (
            item["nomination_quality"] != "NOMINATION_STRONG"
            or item["human_class"] == "AMBIGUOUS"
        ):
            print(
                {
                    k: item[k]
                    for k in (
                        "queue_rank",
                        "sample_id",
                        "human_class",
                        "nomination_quality",
                        "reasons",
                    )
                },
                flush=True,
            )


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
