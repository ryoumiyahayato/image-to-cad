"""Prepare exactly 30 quality-gated train candidates for UI acceptance, no labels."""

import argparse
import hashlib
from collections import Counter, defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw

from common import (
    atomic_json,
    digest,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from extract import crop_box, render_channels
from pilot_audit import DOCS, CACHE, TrainSources
from quality import POLICY, ink_distance, inspect, pair_metrics
from queue_dedup import deduplicate
from target_view import target_overlay, source_support_view
from measurement import measure_row


def measure_trial_targets(rows, source_windows):
    from measurement import measure_trial_targets as shared_measure
    return shared_measure(rows, source_windows)


def local_geometry(geometry, center):
    """Change only OFFLINE nomination extents; never CAD/source pixels or V1 identity."""
    if len(geometry) == 1:
        gid, line, origin = geometry[0]
        a, b = np.array(line).reshape(2, 2)
        length = np.linalg.norm(b - a)
        tangent = (b - a) / max(length, 1e-9)
        t = np.clip(np.dot(np.array(center) - a, tangent), 0, length)
        span = min(180.0, length - 8.0)
        if span < 32:
            return []
        lo = float(np.clip(t - span / 2, 4, length - span - 4))
        return [
            (gid, np.r_[a + tangent * lo, a + tangent * (lo + span)].tolist(), origin)
        ]
    if len(geometry) != 2:
        return []
    a, b = (
        np.array(geometry[0][1]).reshape(2, 2),
        np.array(geometry[1][1]).reshape(2, 2),
    )
    tangent = (a[1] - a[0]) / max(np.linalg.norm(a[1] - a[0]), 1e-9)
    aa, bb = (a - a[0]) @ tangent, (b - a[0]) @ tangent
    lo, hi = (
        max(float(aa.min()), float(bb.min())) + 4,
        min(float(aa.max()), float(bb.max())) - 4,
    )
    span = min(180.0, hi - lo)
    if span < 32 or abs(bb[1] - bb[0]) < 1e-6:
        return []
    t = np.dot(np.array(center) - a[0], tangent)
    low = float(np.clip(t - span / 2, lo, hi - span))
    high = low + span
    result = []
    for original, points, projection in zip(geometry, (a, b), (aa, bb)):
        endpoints = points[0] + (
            (np.array([low, high]) - projection[0]) / (projection[1] - projection[0])
        )[:, None] * (points[1] - points[0])
        result.append((original[0], endpoints.ravel().tolist(), original[2]))
    return result


def component_target(gray, center, stats):
    candidates = []
    for x, y, w, h, area in stats[1:]:
        if 5 <= max(w, h) <= 180 and area >= 4:
            dist = np.linalg.norm(np.array([x + w / 2, y + h / 2]) - center)
            if dist <= 80:
                candidates.append((float(dist), [int(x), int(y), int(w), int(h)]))
    return min(candidates, key=lambda x: x[0])[1] if candidates else None


def make_row(old, geometry, target, gray, unchanged):
    if geometry:
        center = np.array([g[1] for g in geometry]).reshape(-1, 2).mean(0)
    else:
        tx, ty, tw, th = target
        center = [tx + tw / 2, ty + th / 2]
    bbox = old["source_bbox"] if unchanged else crop_box(gray, center)
    patch = Image.new("L", (256, 256), 255)
    x, y, w, h = bbox
    patch.paste(Image.fromarray(gray[y : y + h, x : x + w]), (0, 0))
    crop_hash = hashlib.sha256(patch.tobytes()).hexdigest()
    row = {
        **old,
        "label": None,
        "label_provenance": None,
        "candidate_geometry": geometry,
        "candidate_geometry_ids": [g[0] for g in geometry],
        "source_bbox": bbox,
        "patch_sha256": crop_hash,
        "parent_v1_sample_id": old["sample_id"],
        "original_identity_unchanged": unchanged,
        "target_kind": "PAIR"
        if len(geometry) == 2
        else "SINGLE"
        if geometry
        else "CONTROL",
        "target_roi": target,
        "nomination_status": None,
        "label_contract": "p3b-label-v2",
        "training_authorized": False,
        "pool_version": "real-v2-ui-acceptance-only",
        "content_role": old.get("content_role", "unqualified")
        if unchanged
        else "unqualified",
    }
    if not unchanged:
        row["sample_id"] = (
            "real-v2-"
            + digest(
                {
                    "source": old["source_sha256"],
                    "page": old["source_page"],
                    "bbox": bbox,
                    "geometry": geometry,
                    "target": target,
                    "policy": POLICY,
                }
            )[:24]
        )
        row["current_deterministic_decision"] = "NOT_CAPTURED"
        row["deterministic_provenance"] = (
            "New offline target; no production decision claimed"
        )
        row["input_sha256"] = None
    if len(geometry) == 2:
        pair = pair_metrics(geometry[0][1], geometry[1][1])
        row["features"] = {
            "distance_px": pair["PAIR_SEPARATION_STABILITY"]["mean_px"],
            "overlap_px": pair["PAIR_OVERLAP_LENGTH"],
            "angle_delta_deg": old.get("features", {}).get("angle_delta_deg", 0),
        }
    measure_row(row, gray)
    row["patch_dir"] = "patches/" + row["sample_id"]
    return row, patch


def build_pool(*, page_plan=None, supplement=None):
    """Transient train-only nominations; callers materialize only a bounded batch."""
    if page_plan is not None:
        from extract import run
        return run(None, None, None, page_plan=page_plan, supplement=supplement)
    old_rows = read_rows(DOCS / "real-candidates.jsonl")
    reader = TrainSources()
    groups = defaultdict(list)
    for row in old_rows:
        groups[(row["source_drawing_id"], row["source_page"])].append(row)
    candidates, images, contexts, rejections = [], {}, {}, Counter()
    for group in groups.values():
        gray = reader.load(group[0])
        distance = ink_distance(gray)
        stats = cv2.connectedComponentsWithStats((gray < 180).astype(np.uint8), 8)[2]
        for old in group:
            geometry = old.get("candidate_geometry", [])
            original_quality = inspect(old, gray, distance)
            x, y, w, h = old["source_bbox"]
            center = np.array([x + w / 2, y + h / 2])
            if geometry and original_quality["HUMAN_QUEUE_ELIGIBLE"]:
                row, patch = make_row(old, geometry, None, gray, True)
            elif geometry:
                # Obvious unsupported members are rejected, never shifted onto unrelated ink.
                m = original_quality["metrics"]
                if any(
                    m.get(prefix + "_SOURCE_SUPPORT_RATIO", 0) < 0.9
                    or m.get(prefix + "_MEAN_DISTANCE_TO_DARK_INK", 1e6) > 1.0
                    or m.get(prefix + "_LOCAL_INK_ALIGNMENT", 0) < 0.75
                    for prefix in ("A", "B")[: len(geometry)]
                ):
                    rejections["UNSUPPORTED_OR_MISALIGNED_GEOMETRY"] += 1
                    continue
                new_geometry = local_geometry(geometry, center)
                if not new_geometry:
                    rejections["NO_DEFENSIBLE_LOCAL_EXTENT"] += 1
                    continue
                row, patch = make_row(old, new_geometry, None, gray, False)
            else:
                target = component_target(gray, center, stats)
                if target is None:
                    rejections["NO_EXPLICIT_COMPONENT"] += 1
                    continue
                row, patch = make_row(old, [], target, gray, False)
            quality = inspect(row, gray, distance)
            if not quality["HUMAN_QUEUE_ELIGIBLE"]:
                rejections.update(quality["rejection_reasons"])
                continue
            row["quality"] = quality
            candidates.append(row)
            images[row["sample_id"]] = patch
            cx, cy, cw, ch = crop_box(gray, np.array(row["source_bbox"][:2]) + 128, 512)
            contexts[row["sample_id"]] = Image.fromarray(
                gray[cy : cy + ch, cx : cx + cw]
            )
    # Better supported targets rank first; no old human class participates in selection.
    candidates.sort(
        key=lambda r: (
            r["source_drawing_id"],
            r["target_kind"],
            -min(
                r["quality"]["metrics"].get("A_SOURCE_SUPPORT_RATIO", 1),
                r["quality"]["metrics"].get("B_SOURCE_SUPPORT_RATIO", 1),
            ),
            r["sample_id"],
        )
    )
    return reader, candidates, images, contexts, rejections


def write_patches(out, chosen, images, contexts):
    for row in chosen:
        folder = out / row["patch_dir"]
        folder.mkdir(parents=True, exist_ok=True)
        patch = images[row["sample_id"]]
        channels = render_channels(
            np.array(patch),
            [0, 0, 256, 256],
            [
                (
                    gid,
                    [
                        xy[0] - row["source_bbox"][0],
                        xy[1] - row["source_bbox"][1],
                        xy[2] - row["source_bbox"][0],
                        xy[3] - row["source_bbox"][1],
                    ],
                    origin,
                )
                for gid, xy, origin in row["candidate_geometry"]
            ],
        )
        for name, image in zip(
            ("gray", "edges", "centerline", "protection", "nodes"), channels
        ):
            image.save(folder / (name + ".png"))
        target_overlay(patch, row).save(folder / "overlay.png")
        source_support_view(patch, row).save(folder / "support.png")
        contexts[row["sample_id"]].save(folder / "context.png")


def prepare(refresh_unreviewed=False):
    reader, candidates, images, contexts, rejections = build_pool()
    unique, duplicates, dedup_counts = deduplicate(
        candidates, None, load_gray=lambda r: images[r["sample_id"]]
    )
    per_source = defaultdict(list)
    for row in unique:
        per_source[row["source_drawing_id"]].append(row)
    chosen, source_counts, kinds = [], Counter(), Counter()
    # Round robin, prefer one of each target type per source, max 3 per drawing.
    while len(chosen) < 30:
        changed = False
        for sid in sorted(per_source):
            if len(chosen) >= 30:
                break
            if source_counts[sid] >= 3 or not per_source[sid]:
                continue
            per_source[sid].sort(
                key=lambda r: (
                    kinds[(sid, r["target_kind"])],
                    r["target_kind"],
                    r["sample_id"],
                )
            )
            row = per_source[sid].pop(0)
            chosen.append(row)
            source_counts[sid] += 1
            kinds[(sid, row["target_kind"])] += 1
            changed = True
        if not changed:
            break
    if len(chosen) != 30:
        raise ValueError(
            f"Only {len(chosen)} usable diverse candidates; do not bypass gate"
        )
    validate_samples(chosen)
    out = CACHE / "real-v2"
    if out.name == "real-v1":
        raise ValueError("V1 immutable")
    out.mkdir(parents=True, exist_ok=True)
    # Do not overwrite a separately reviewed V2 manifest or patches.
    if (out / "samples.jsonl").exists():
        if digest(read_rows(out / "samples.jsonl")) != digest(chosen):
            if (
                not refresh_unreviewed
                or (DOCS / "labels/v2-ui-acceptance.json").exists()
            ):
                raise ValueError(
                    "V2 differs; only an explicitly unreviewed draft can be refreshed"
                )
    write_patches(out, chosen, images, contexts)
    write_rows(out / "samples.jsonl", chosen)
    write_rows(DOCS / "real-v2-acceptance.jsonl", chosen)
    atomic_json(
        DOCS / "v2-duplicate-audit.json",
        {"counts": dedup_counts, "details": duplicates},
    )
    summary = {
        "REAL_V2_CANDIDATES": 30,
        "internal_quality_passed_nomination_count": len(candidates),
        **dedup_counts,
        "generated_or_queued": 30,
        "by_drawing": dict(source_counts),
        "by_type": dict(Counter(r["target_kind"] for r in chosen)),
        "rejection_counts": dict(rejections),
        "manifest_sha256": sha(out / "samples.jsonl"),
        "quality_policy": POLICY,
        "source_pages_accessed": sorted(reader.opened),
        "validation_sources_accessed": 0,
        "blind_sources_accessed": 0,
        "V1_TRAINING_AUTHORIZED": 0,
        "V2_TRAINING_AUTHORIZED": 0,
        "acceptance_target": ">=29/30 explicitly identifiable; human review pending",
    }
    atomic_json(DOCS / "real-v2-summary.json", summary)
    preview = Image.new("RGB", (1024, 10 * 286), "white")
    draw = ImageDraw.Draw(preview)
    for i, row in enumerate(chosen[:20]):
        left, top = (i % 2) * 512, (i // 2) * 286
        draw.text(
            (left + 4, top + 2),
            f"{i + 1}. {row['target_kind']} {row['source_drawing_id']}",
            fill="black",
        )
        preview.paste(images[row["sample_id"]], (left, top + 25))
        preview.paste(
            target_overlay(images[row["sample_id"]], row, scale=1).resize((256, 256)),
            (left + 256, top + 25),
        )
    preview.save(DOCS / "v2-target-preview.png")
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-unreviewed", action="store_true")
    args = parser.parse_args()
    prepare(args.refresh_unreviewed)
