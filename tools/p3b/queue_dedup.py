"""Drawing-preserving human-queue dedup. Different pair gaps/topology are protected."""

import math
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def descriptor(row, gray):
    small = np.array(gray.resize((17, 16), Image.Resampling.BOX))
    bits = (small[:, 1:] > small[:, :-1]).ravel()
    phash = sum(int(b) << i for i, b in enumerate(bits))
    geometry = row.get("candidate_geometry", [])
    if geometry:
        line = geometry[0][1]
        angle = math.degrees(math.atan2(line[3] - line[1], line[2] - line[0])) % 180
        gap = (
            row.get("quality", {})
            .get("metrics", {})
            .get("PAIR_SEPARATION_STABILITY", {})
            .get("mean_px", row.get("features", {}).get("distance_px", 0))
        )
    else:
        angle, gap = 0.0, 0.0
    # Local raster crossings/component complexity protects visually distinct structure.
    ink = np.array(gray) < 180
    edges = int(
        np.count_nonzero(ink[:, 1:] != ink[:, :-1])
        + np.count_nonzero(ink[1:, :] != ink[:-1, :])
    )
    return {"phash": phash, "angle": angle, "gap": gap, "complexity": edges}


def deduplicate(rows, base, load_gray=None, radius=192, hamming=20, *, preview_policy=None, history=(), preview_mode='new_information'):
    if preview_policy is not None:
        from preview_selection import select_preview_mode
        return select_preview_mode(rows, history, preview_policy,mode=preview_mode)
    retained, details = [], []
    counts = Counter()
    for row in rows:
        gray = (
            load_gray(row)
            if load_gray
            else Image.open(Path(base) / row["patch_dir"] / "gray.png").convert("L")
        )
        desc = descriptor(row, gray)
        x, y, w, h = row["source_bbox"]
        center = (x + w / 2, y + h / 2)
        kind = row.get("target_kind") or (
            "PAIR"
            if len(row.get("candidate_geometry", [])) == 2
            else "SINGLE"
            if row.get("candidate_geometry")
            else "CONTROL"
        )
        duplicate, category = None, None
        for old, od, oc, okind in retained:
            if (
                row["source_drawing_id"] != old["source_drawing_id"]
                or row["source_page"] != old["source_page"]
                or kind != okind
            ):
                continue
            if row["patch_sha256"] == old["patch_sha256"]:
                duplicate, category = old, "DUPLICATE_EXACT"
                break
            distance = math.dist(center, oc)
            angle = abs((desc["angle"] - od["angle"] + 90) % 180 - 90)
            topology_similar = (
                abs(desc["complexity"] - od["complexity"])
                / max(desc["complexity"], od["complexity"], 1)
                <= 0.20
            )
            geometry_similar = angle <= 5 and abs(desc["gap"] - od["gap"]) <= 1.5
            shared = set(row["candidate_geometry_ids"]) & set(
                old["candidate_geometry_ids"]
            )
            if shared and distance <= radius and geometry_similar and topology_similar:
                duplicate, category = old, "SAME_STRUCTURE_REPETITION"
                break
            if (
                distance <= radius
                and (desc["phash"] ^ od["phash"]).bit_count() <= hamming
                and geometry_similar
                and topology_similar
            ):
                duplicate, category = old, "DUPLICATE_NEAR"
                break
        if duplicate:
            counts[category] += 1
            details.append(
                {
                    "sample_id": row["sample_id"],
                    "duplicate_of": duplicate["sample_id"],
                    "reason": category,
                }
            )
        else:
            retained.append((row, desc, center, kind))
    return (
        [r for r, _, _, _ in retained],
        details,
        {
            "EXACT_DUPLICATES_REMOVED": counts["DUPLICATE_EXACT"],
            "NEAR_DUPLICATES_REMOVED": counts["DUPLICATE_NEAR"],
            "SAME_STRUCTURE_REPETITIONS_REMOVED": counts["SAME_STRUCTURE_REPETITION"],
            "UNIQUE_CANDIDATES_REMAINING": len(retained),
        },
    )
