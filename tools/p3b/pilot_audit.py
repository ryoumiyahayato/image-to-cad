"""Freeze-aware pilot reconstruction and train-only nomination quality audit."""

import argparse
import hashlib
from collections import Counter, defaultdict

import numpy as np
from PIL import Image, ImageDraw

from common import ROOT, atomic_json, read, read_rows, sha, write_rows
from extract import raster
from label_ui import diverse_order
from quality import POLICY, ink_distance, inspect

DOCS = ROOT / "docs/product-fix-p3b"
CACHE = ROOT.parent.parent / "image-to-cad-p3b-cache"


class TrainSources:
    def __init__(self):
        inventory = read(DOCS / "inventory.json")
        split = read(DOCS / "split-manifest.json")
        self.sources = {
            s["source_drawing_id"]: s
            for s in inventory["sources"]
            if s["split"] == "train" and s["availability"] == "AVAILABLE"
        }
        self.assigned = {s["source_drawing_id"]: s for s in split["drawings"]}
        self.opened = set()

    def load(self, row):
        sid = row["source_drawing_id"]
        if (
            row["split"] != "train"
            or sid not in self.sources
            or self.assigned[sid]["split"] != "train"
        ):
            raise ValueError("Only frozen train drawings can be accessed")
        source = self.sources[sid]
        file = source["files"][0]
        if file["sha256"] != row["source_sha256"]:
            raise ValueError("Source binding changed")
        if sid == "warehouse-electrical" and row["source_page"] == 3:
            with Image.open(
                ROOT / "local-artifacts/product-fix-p3a/W03/source.png"
            ) as image:
                gray = np.array(image.convert("L"))
            if (
                hashlib.sha256(gray.tobytes()).hexdigest()
                != read(ROOT / "docs/product-fix-p3a/W03-STROKE-REPLAY.json")[
                    "source_sha256_verified"
                ]
            ):
                raise ValueError("W03 raster changed")
        else:
            gray, _ = raster(file, row["source_page"], row["source_dpi"] or 110)
        self.opened.add((sid, row["source_page"]))
        return gray


def overlay_available(row):
    folder = CACHE / "real-v1" / row["patch_dir"]
    with Image.open(folder / "overlay.png") as image:
        a = np.array(image.convert("RGB"))
    red = int(((a[:, :, 0] == 230) & (a[:, :, 1] == 40) & (a[:, :, 2] == 40)).sum())
    return {
        "file_present": (folder / "overlay.png").is_file(),
        "visible_overlay_pixels": red,
        "explicit_geometry": bool(row["candidate_geometry_ids"]) and red > 0,
        "control_target_roi": row.get("target_roi"),
    }


def contact_sheets(rows, out):
    out.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), 16):
        selected = rows[start : start + 16]
        canvas = Image.new("RGB", (1024, 4 * 294), "#f5f5f5")
        draw = ImageDraw.Draw(canvas)
        for i, row in enumerate(selected):
            left, top = (i % 2) * 512, (i // 2) * 147
            # Two 128 px views, plus exact queue rank, label and machine quality flags.
            original = row["original"]
            folder = CACHE / "real-v1" / original["patch_dir"]
            for offset, name in ((0, "gray.png"), (128, "overlay.png")):
                with Image.open(folder / name) as image:
                    canvas.paste(
                        image.convert("RGB").resize(
                            (128, 128), Image.Resampling.NEAREST
                        ),
                        (left + offset, top + 19),
                    )
            label = (
                (row["label"] or "UNLABELED")
                .replace("SINGLE_PHYSICAL_STROKE", "SINGLE")
                .replace("TRUE_PARALLEL_STRUCTURE", "PARALLEL")
            )
            draw.text(
                (left + 2, top + 2),
                f"#{row['queue_rank']} {original['source_drawing_id']} {label}",
                fill="black",
            )
            for k, reason in enumerate(row["quality"]["rejection_reasons"][:5]):
                draw.text((left + 263, top + 22 + k * 15), reason, fill="#9d1c21")
            draw.text(
                (left + 263, top + 110), original["nomination_kind"], fill="black"
            )
        canvas.save(out / f"pilot-{start + 1:03d}-{start + len(selected):03d}.png")


def audit(position=209):
    frozen = read(DOCS / "pilot-freeze.json")
    labels_path = DOCS / "labels/local-labels.json"
    if sha(labels_path) != frozen["sha256"]:
        raise ValueError("Pilot labels changed after freeze")
    labels = read(labels_path)
    rows = read_rows(DOCS / "real-candidates.jsonl")
    if sha(DOCS / "real-candidates.jsonl") != labels["manifest_sha256"]:
        raise ValueError("V1 manifest changed")
    order = diverse_order(rows)
    if any(r["split"] != "train" for r in rows):
        raise ValueError("Nontrain source present")
    reader, grouped, results = TrainSources(), defaultdict(list), {}
    for row in rows:
        grouped[(row["source_drawing_id"], row["source_page"])].append(row)
    for group in grouped.values():
        gray = reader.load(group[0])
        distance = ink_distance(gray)
        for row in group:
            x, y, w, h = row["source_bbox"]
            patch = Image.new("L", (256, 256), 255)
            patch.paste(Image.fromarray(gray[y : y + h, x : x + w]), (0, 0))
            if hashlib.sha256(patch.tobytes()).hexdigest() != row["patch_sha256"]:
                raise ValueError(f"Source/crop coordinate mismatch: {row['sample_id']}")
            results[row["sample_id"]] = inspect(row, gray, distance)
        print(
            "Audited",
            group[0]["source_drawing_id"],
            group[0]["source_page"],
            flush=True,
        )
    window = []
    for rank, row in enumerate(order[:position], 1):
        label = labels["labels"].get(row["sample_id"])
        window.append(
            {
                "sample_id": row["sample_id"],
                "queue_rank": rank,
                "drawing": row["source_drawing_id"],
                "page": row["source_page"],
                "nomination_type": row["nomination_kind"],
                "label": label["label"] if label else None,
                "unlabeled_status": "LABELED"
                if label
                else "CURRENT_PRESENTED_UNLABELED"
                if rank == position
                else "SKIPPED_OR_LEFT_UNLABELED_CONFIRMED_SINGLE_SESSION",
                "candidate_geometry": row.get("candidate_geometry", []),
                "source_crop_hash": row["patch_sha256"],
                "overlay_availability": overlay_available(row),
                "quality": results[row["sample_id"]],
                "original": row,
            }
        )
    write_rows(DOCS / "pilot-review-manifest.jsonl", window)
    write_rows(
        DOCS / "v1-quality-audit.jsonl",
        [{"sample_id": r["sample_id"], **results[r["sample_id"]]} for r in rows],
    )
    saved = {r["sample_id"]: r for r in rows if r["sample_id"] in labels["labels"]}
    disposition = []
    for sid, row in saved.items():
        record = labels["labels"][sid]
        unchanged = record["sample_sha256"] == __import__("common").digest(row)
        metrics = results[sid]["metrics"]
        reasons = results[sid]["rejection_reasons"]
        if "NO_EXPLICIT_TARGET_OVERLAY" in reasons:
            status = "PILOT_V1_UNCLEAR_TARGET"
        elif (
            any(
                metrics.get(prefix + "_SOURCE_SUPPORT_RATIO", 1) < 0.7
                or metrics.get(prefix + "_MEAN_DISTANCE_TO_DARK_INK", 0) > 2.5
                for prefix in ("A", "B")
            )
            or metrics.get("PAIR_LENGTH_RATIO", 1) < 0.4
        ):
            status = "PILOT_V1_INVALID_NOMINATION"
        elif unchanged and results[sid]["HUMAN_QUEUE_ELIGIBLE"]:
            status = "PILOT_V1_RETAINABLE_CANDIDATE"
        else:
            status = "PILOT_V1_NEEDS_HUMAN_REVIEW"
        disposition.append(
            {
                "sample_id": sid,
                "status": status,
                "quarantine_status": "PILOT_V1_UNVERIFIED",
                "training_authorized": False,
                "nomination_status": None,
                "triage_basis": "source/geometry quality flags; no human Stage-0 certification",
                "candidate_identity_unchanged": unchanged,
                "human_decision": record,
                "reasons": results[sid]["rejection_reasons"],
                "source_crop_sha256": row["patch_sha256"],
                "original_sample_sha256": record["sample_sha256"],
            }
        )
    atomic_json(DOCS / "pilot-label-disposition.json", disposition)
    counts = Counter(
        reason for r in window for reason in r["quality"]["rejection_reasons"]
    )
    summary = {
        "PILOT_REVIEWED": position,
        "PILOT_SAVED": len(labels["labels"]),
        "PILOT_UNLABELED_OR_SKIPPED": sum(r["label"] is None for r in window),
        "confirmed_prior_skipped_or_unlabeled": sum(
            r["label"] is None for r in window[:-1]
        ),
        "current_position_unlabeled": window[-1]["label"] is None,
        "LABELABLE_RATE_saved_proxy": len(labels["labels"]) / position,
        "LABELABLE_RATE_quality_gate": sum(
            r["quality"]["HUMAN_QUEUE_ELIGIBLE"] for r in window
        )
        / position,
        "unusable_multiple_reason_counts": dict(counts),
        "reason_percent_of_presented": {k: n / position for k, n in counts.items()},
        "gate_eligible_presented": sum(
            r["quality"]["HUMAN_QUEUE_ELIGIBLE"] for r in window
        ),
        "PILOT_LABELS_TOTAL": len(disposition),
        "PILOT_LABELS_RETAINED": 0,
        "PILOT_LABELS_QUARANTINED": len(disposition),
        "V1_TRAINING_AUTHORIZED": 0,
        "V1_STATUS": "PILOT_V1_UNVERIFIED",
        "saved_label_triage": dict(Counter(d["status"] for d in disposition)),
        "policy": POLICY,
        "opened_sources": sorted(reader.opened),
        "validation_opened": 0,
        "blind_opened": 0,
        "reconstruction_provenance": "user confirms Sample 209/769, one continuous session; deterministic V1 round-robin order; labels manifest hash matches",
        "historical_presentation_event_count": "not recorded; repeats due undo cannot be enumerated",
    }
    atomic_json(DOCS / "pilot-audit-summary.json", summary)
    contact_sheets(window, DOCS / "pilot-contact-sheets")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--position", type=int, default=209)
    args = ap.parse_args()
    print(audit(args.position))
