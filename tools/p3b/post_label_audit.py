"""Frozen human evidence + independent, class-blind nomination audit. No training."""

import argparse
import hashlib
import math
import shutil
from collections import Counter, defaultdict

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from audit_acceptance import audit_state
from common import atomic_json, read, read_rows, sha, write_rows
from label_ui import diverse_order
from pilot_audit import CACHE, DOCS, TrainSources
from quality import pair_metrics
from target_view import target_overlay

POLICY = {
    "version": "post-label-independent-v1",
    "dark_threshold": 180,
    "sample_step_px": 0.5,
    "support_radius_px": 1.5,
    "strong_min_support": 0.98,
    "strong_max_mean_px": 1.1,
    "strong_max_p95_px": 1.5,
    "strong_min_endpoint_support": 0.95,
    "strong_min_tangent_alignment": 0.95,
    "strong_min_pair_ratio": 0.85,
    "strong_max_pair_separation_range_px": 1.0,
    "poor_min_support": 0.60,
    "poor_max_mean_px": 2.5,
    "poor_max_p95_px": 4.0,
    "poor_min_tangent_alignment": 0.50,
    "poor_min_pair_ratio": 0.40,
    "poor_min_overlap_px": 16.0,
}


def line_metrics(line, gray, tree):
    a, b = np.array(line).reshape(2, 2)
    length = float(np.linalg.norm(b - a))
    tangent = (b - a) / max(length, 1e-9)
    points = np.linspace(a, b, max(9, math.ceil(length / POLICY["sample_step_px"]) + 1))
    valid = (
        (points[:, 0] >= 0)
        & (points[:, 0] < gray.shape[1])
        & (points[:, 1] >= 0)
        & (points[:, 1] < gray.shape[0])
    )
    distances = tree.query(points)[0] if tree else np.full(len(points), 1e6)
    supported = (distances <= POLICY["support_radius_px"]) & valid
    endpoint_span = min(len(points), max(5, math.ceil(3 / POLICY["sample_step_px"])))
    endpoint = min(
        float(supported[:endpoint_span].mean()),
        float(supported[-endpoint_span:].mean()),
    )
    probes = points[:: max(1, len(points) // 96)]
    minus, plus = probes - tangent * 3, probes + tangent * 3
    if tree:
        dm, im = tree.query(minus)
        dp, ip = tree.query(plus)
        observed = tree.data[ip] - tree.data[im]
        norms = np.linalg.norm(observed, axis=1)
        cosine = np.clip(np.abs(observed @ tangent) / np.maximum(norms, 1e-9), 0, 1)
        angles = np.degrees(np.arccos(cosine))
        aligned = (dm <= 1.5) & (dp <= 1.5) & (norms >= 2) & (angles <= 25)
        alignment = float(aligned.mean())
        median_angle = float(np.median(angles))
    else:
        alignment, median_angle = 0.0, 90.0
    return {
        "SOURCE_SUPPORT_RATIO": float(supported.mean()),
        "MEAN_DISTANCE_TO_SOURCE_INK": float(distances.mean()),
        "P95_DISTANCE_TO_SOURCE_INK": float(np.percentile(distances, 95)),
        "ENDPOINT_SUPPORT": endpoint,
        "LOCAL_TANGENT_ALIGNMENT": alignment,
        "MEDIAN_TANGENT_ERROR_DEG": median_angle,
        "SOURCE_IN_BOUNDS_RATIO": float(valid.mean()),
        "LENGTH_PX": length,
        "SAMPLES": len(points),
    }


def correspondence(row, patch):
    """Only source pixels, target geometry and ROI enter quality computation."""
    gray = np.array(patch)
    ink = np.argwhere(gray <= POLICY["dark_threshold"])[:, ::-1]
    tree = cKDTree(ink) if len(ink) else None
    x, y, w, h = row["source_bbox"]
    metrics, borderline, poor = {}, [], []
    geometry = row["candidate_geometry"]
    for i, (_, line, _) in enumerate(geometry):
        prefix = "A" if i == 0 else "B"
        local = np.array(line).reshape(2, 2) - [x, y]
        m = line_metrics(local.ravel(), gray, tree)
        metrics[prefix] = m
        # One mildly imperfect endpoint is a borderline flag, not automatic exclusion.
        if (
            m["SOURCE_IN_BOUNDS_RATIO"] < 0.90
            or m["SOURCE_SUPPORT_RATIO"] < 0.60
            or m["MEAN_DISTANCE_TO_SOURCE_INK"] > 2.5
            or (
                m["P95_DISTANCE_TO_SOURCE_INK"] > 4 and m["SOURCE_SUPPORT_RATIO"] < 0.90
            )
            or m["LOCAL_TANGENT_ALIGNMENT"] < 0.50
        ):
            poor.append(prefix + "_SEVERELY_UNSUPPORTED_OR_MISALIGNED")
        if (
            m["SOURCE_SUPPORT_RATIO"] < 0.98
            or m["MEAN_DISTANCE_TO_SOURCE_INK"] > 1.1
            or m["P95_DISTANCE_TO_SOURCE_INK"] > 1.5
        ):
            borderline.append(prefix + "_IMPERFECT_INK_CORRESPONDENCE")
        if m["ENDPOINT_SUPPORT"] < 0.95:
            borderline.append(prefix + "_ENDPOINT_SUPPORT")
        if m["LOCAL_TANGENT_ALIGNMENT"] < 0.95:
            borderline.append(prefix + "_LOCAL_TANGENT_ALIGNMENT")
        if m["SOURCE_IN_BOUNDS_RATIO"] < 1:
            borderline.append(prefix + "_PARTLY_OUT_OF_BOUNDS")
        m["DISPLAY_ENDPOINTS_IN_BOUNDS"] = bool(
            np.all(local >= [12, 12]) and np.all(local <= [w - 12, h - 12])
        )
        if not m["DISPLAY_ENDPOINTS_IN_BOUNDS"]:
            borderline.append(prefix + "_ENDPOINT_DISPLAY_MARGIN")
    if len(geometry) == 2:
        pair = pair_metrics(geometry[0][1], geometry[1][1])
        metrics["PAIR"] = pair
        if pair["PAIR_LENGTH_RATIO"] < 0.40 or pair["PAIR_OVERLAP_LENGTH"] < 16:
            poor.append("PAIR_NO_DEFENSIBLE_COMMON_EXTENT")
        elif pair["PAIR_LENGTH_RATIO"] < 0.85:
            borderline.append("PAIR_UNEQUAL_EXTENT")
        if pair["PAIR_SEPARATION_STABILITY"]["range_px"] > 1.0:
            borderline.append("PAIR_SEPARATION_VARIATION")
    if not geometry:
        target = row.get("target_roi")
        if target:
            tx, ty, tw, th = target
            lx, ly = tx - x, ty - y
            in_bounds = lx >= 0 and ly >= 0 and lx + tw <= w and ly + th <= h
            roi = gray[max(0, ly) : min(h, ly + th), max(0, lx) : min(w, lx + tw)]
            count = int((roi <= 180).sum())
            metrics["CONTROL"] = {
                "TARGET_INK_PIXELS": count,
                "ROI_IN_BOUNDS": in_bounds,
                "LINE_METRICS": "NOT_APPLICABLE: explicit source-object ROI, no line geometry",
            }
            if count < 4 or not in_bounds:
                poor.append("CONTROL_NO_SUPPORTED_EXPLICIT_ROI")
        else:
            poor.append("CONTROL_MISSING_ROI")
    category = (
        "NOMINATION_POOR"
        if poor
        else "NOMINATION_BORDERLINE"
        if borderline
        else "NOMINATION_STRONG"
    )
    return {
        "nomination_quality": category,
        "reasons": sorted(set(poor + borderline)),
        "independent_metrics": metrics,
        "policy": POLICY["version"],
        "human_class_used_for_quality": False,
    }


def freeze(manifest, labels):
    folder = DOCS / "frozen/formal-seed-v2-001"
    folder.mkdir(parents=True, exist_ok=True)
    for source, name in ((manifest, "manifest.jsonl"), (labels, "label-state.json")):
        target = folder / name
        if target.exists() and sha(target) != sha(source):
            raise ValueError(
                "Completed batch changed after freeze; preserve existing freeze and investigate"
            )
        if not target.exists():
            shutil.copyfile(source, target)
    return folder


def run():
    manifest, labels = (
        DOCS / "formal-seed-v2-001.jsonl",
        DOCS / "labels/formal-seed-v2-001.json",
    )
    before = {p: sha(p) for p in (manifest, labels, DOCS / "split-manifest.json")}
    rows, state = diverse_order(read_rows(manifest)), read(labels)
    history = audit_state(state, read_rows(manifest), sha(manifest))
    if (
        not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or len(state["nomination_statuses"]) != 100
    ):
        raise ValueError(
            "Completed state is internally inconsistent; do not alter answers"
        )
    folder = freeze(manifest, labels)
    freeze_record = {
        "batch": "formal-seed-v2-001",
        "status": "FROZEN_HUMAN_EVIDENCE_NOT_TRAINING_AUTHORIZATION",
        "manifest_sha256": sha(manifest),
        "label_state_sha256": sha(labels),
        "history_count": len(state["review_log"]),
        "revision": state["revision"],
        "remaining_undo_events": len(state["events"]),
        "reviewed_count": 100,
        "status_counts": dict(
            Counter(v["status"] for v in state["nomination_statuses"].values())
        ),
        "class_counts": dict(Counter(v["label"] for v in state["labels"].values())),
        "freeze_directory": str(folder),
        "training_authorized": False,
        "reviewer_feedback": "Intended objects were identifiable, but some overlays had imperfect alignment/coverage; Stage-1 correctness is not guaranteed. Preserve classes and independently flag nomination risks.",
    }
    atomic_json(DOCS / "formal-seed-freeze.json", freeze_record)
    reader, grouped = TrainSources(), defaultdict(list)
    for row in rows:
        grouped[(row["source_drawing_id"], row["source_page"])].append(row)
    patches, audited = {}, {}
    for group in grouped.values():
        source = reader.load(group[0])
        for row in group:
            x, y, w, h = row["source_bbox"]
            patch = Image.new("L", (256, 256), 255)
            patch.paste(Image.fromarray(source[y : y + h, x : x + w]), (0, 0))
            if hashlib.sha256(patch.tobytes()).hexdigest() != row["patch_sha256"]:
                raise ValueError("Re-read source crop differs from frozen manifest")
            with Image.open(
                CACHE / "real-v2-formal-seed-001" / row["patch_dir"] / "gray.png"
            ) as cached:
                if cached.convert("L").tobytes() != patch.tobytes():
                    raise ValueError("Cached source pixels changed")
            # Compute blind to the human record; attach human evidence only afterwards.
            quality = correspondence(row, patch)
            sid = row["sample_id"]
            nomination = state["nomination_statuses"].get(sid, {})
            label = state["labels"].get(sid, {}).get("label")
            status = nomination.get("status")
            disposition = "EXCLUDE_NOMINATION"
            if status == "VALID_TARGET" and label:
                disposition = {
                    "NOMINATION_STRONG": "READY",
                    "NOMINATION_BORDERLINE": "REVIEW_RECOMMENDED",
                    "NOMINATION_POOR": "EXCLUDE_NOMINATION",
                }[quality["nomination_quality"]]
            audited[sid] = {
                "sample_id": sid,
                "queue_rank": rows.index(row) + 1,
                "source_drawing_id": row["source_drawing_id"],
                "source_family_id": row["source_family_id"],
                "source_page": row["source_page"],
                "effective_dpi": row["source_dpi"],
                "target_kind": row["target_kind"],
                **quality,
                "human_nomination_status": status,
                "human_class": label,
                "TRAINING_REVIEW_STATUS": disposition,
                "training_authorized": False,
            }
            patches[sid] = patch
        print(
            "Recomputed train source",
            group[0]["source_drawing_id"],
            group[0]["source_page"],
            flush=True,
        )
    out = CACHE / "formal-seed-post-audit"
    out.mkdir(parents=True, exist_ok=True)
    # Contact sheets contain ranks/types/IDs only: quality visual review is class-blind.
    for start in range(0, 100, 10):
        canvas = Image.new("RGB", (1024, 5 * 284), "white")
        draw = ImageDraw.Draw(canvas)
        for j, row in enumerate(rows[start : start + 10]):
            left, top = (j % 2) * 512, (j // 2) * 284
            draw.text(
                (left + 3, top + 2),
                f"#{start + j + 1} {row['target_kind']} {row['source_drawing_id']}",
                fill="black",
            )
            canvas.paste(patches[row["sample_id"]], (left, top + 25))
            canvas.paste(
                target_overlay(patches[row["sample_id"]], row, 1),
                (left + 256, top + 25),
            )
        canvas.save(
            out / f"blind-quality-{start + 1:03d}-{min(start + 10, 100):03d}.png"
        )
    write_rows(
        DOCS / "formal-seed-correspondence-audit.jsonl",
        [audited[r["sample_id"]] for r in rows],
    )
    valid = [
        v
        for v in audited.values()
        if v["human_nomination_status"] == "VALID_TARGET" and v["human_class"]
    ]
    summary = {
        "freeze": freeze_record,
        "independent_quality_policy": POLICY,
        "quality_counts_labeled_V": dict(
            Counter(v["nomination_quality"] for v in valid)
        ),
        "review_status_counts_all_100": dict(
            Counter(v["TRAINING_REVIEW_STATUS"] for v in audited.values())
        ),
        "quality_by_class_for_reporting_only": {
            c: dict(
                Counter(v["nomination_quality"] for v in valid if v["human_class"] == c)
            )
            for c in Counter(v["human_class"] for v in valid)
        },
        "source_pages_opened": sorted(reader.opened),
        "validation_sources_opened": 0,
        "blind_sources_opened": 0,
        "visual_review_directory": str(out),
        "visual_review_status": "PENDING",
        "training_authorized": False,
    }
    atomic_json(DOCS / "formal-seed-post-audit-summary.json", summary)
    for p, expected in before.items():
        if sha(p) != expected:
            raise ValueError("Frozen evidence changed during read-only audit")
    print(summary)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
