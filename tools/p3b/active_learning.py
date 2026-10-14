"""Future round selector: entropy, predicted class balance, source diversity, dedup."""

import argparse
import math
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from common import atomic_json, read, read_rows, validate_samples
from benchmark import validate_prediction


def perceptual_hash(path):
    gray = np.array(Image.open(path).convert("L").resize((9, 8)))
    bits = (gray[:, 1:] > gray[:, :-1]).ravel()
    return sum(int(b) << i for i, b in enumerate(bits))


def select(rows, scores, count=64, per_drawing=8, already_seen=(), base=None):
    validate_samples(rows)
    if any(r["split"] != "train" for r in rows):
        raise ValueError("Active learning pool must contain train drawings only")
    scored = {s["sample_id"]: s for s in scores}
    candidates = []
    for row in rows:
        if (
            row["sample_id"] in already_seen
            or row["label"] is not None
            or row["sample_id"] not in scored
        ):
            continue
        pred, _ = validate_prediction(scored[row["sample_id"]])
        probs = scored[row["sample_id"]].get("probabilities")
        if not probs:
            continue
        entropy = -sum(p * math.log(max(p, 1e-12)) for p in probs.values()) / math.log(
            4
        )
        phash = (
            perceptual_hash(Path(base) / row["patch_dir"] / "gray.png")
            if base
            else row.get("perceptual_hash")
        )
        candidates.append((row, pred, entropy, phash))
    selected, drawings, classes, hashes, centers, visual = (
        [],
        Counter(),
        Counter(),
        set(),
        {},
        [],
    )
    for row in rows:
        if row["sample_id"] in already_seen or row["label"] is not None:
            hashes.add(row["patch_sha256"])
            x, y, w, h = row["source_bbox"]
            centers.setdefault(
                (row["source_drawing_id"], row["source_page"]), []
            ).append((x + w / 2, y + h / 2))
            if base:
                visual.append(
                    perceptual_hash(Path(base) / row["patch_dir"] / "gray.png")
                )
    while candidates and len(selected) < count:
        candidates.sort(
            key=lambda c: (
                -(
                    c[2]
                    / (
                        1
                        + 0.6 * drawings[c[0]["source_drawing_id"]]
                        + 0.4 * classes[c[1]]
                    )
                ),
                c[0]["sample_id"],
            )
        )
        row, pred, entropy, phash = candidates.pop(0)
        drawing = row["source_drawing_id"]
        key = drawing, row["source_page"]
        x, y, w, h = row["source_bbox"]
        center = (x + w / 2, y + h / 2)
        if drawings[drawing] >= per_drawing or row["patch_sha256"] in hashes:
            continue
        if any(math.dist(center, old) < 128 for old in centers.get(key, [])):
            continue
        if phash is not None and any(
            (int(phash) ^ old).bit_count() <= 4 for old in visual
        ):
            continue
        selected.append(
            {
                "sample_id": row["sample_id"],
                "reason": "uncertainty + class/source diversity",
                "entropy": entropy,
            }
        )
        drawings[drawing] += 1
        classes[pred] += 1
        hashes.add(row["patch_sha256"])
        centers.setdefault(key, []).append(center)
        if phash is not None:
            visual.append(int(phash))
    return selected


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--count", type=int, default=64)
    args = ap.parse_args()
    rows = read_rows(args.manifest)
    seen = read(args.labels).get("labels", {}) if args.labels else {}
    atomic_json(
        args.out,
        select(
            rows,
            read_rows(args.scores),
            args.count,
            already_seen=seen,
            base=args.manifest.parent,
        ),
    )
