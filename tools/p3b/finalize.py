"""Validate and retain small records. Prune only obsolete, tool-owned patch folders."""

import argparse
import importlib.metadata
import re
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from common import (
    ROOT,
    atomic_json,
    digest,
    product_snapshot,
    read,
    read_rows,
    sha,
    validate_samples,
)


def finalize(cache, docs, prune=False):
    cache = Path(cache).resolve()
    if cache.name != "image-to-cad-p3b-cache" or cache.is_symlink():
        raise ValueError("Expected designated P3B regenerable cache")
    real = read_rows(cache / "real-v1/samples.jsonl")
    synthetic = read_rows(cache / "synthetic-v1/samples.jsonl")
    validate_samples(real + synthetic)
    for dataset, rows in (("real-v1", real), ("synthetic-v1", synthetic)):
        base = cache / dataset
        current = {Path(r["patch_dir"]).name for r in rows}
        for row in rows:
            folder = (base / row["patch_dir"]).resolve()
            if base not in folder.parents or folder.is_symlink():
                raise ValueError("Patch path outside cache")
            for name in ("gray", "edges", "centerline", "protection", "nodes"):
                with Image.open(folder / (name + ".png")) as image:
                    if image.size != (256, 256):
                        raise ValueError("Wrong patch dimensions")
                    if (
                        name == "gray"
                        and __import__("hashlib")
                        .sha256(image.convert("L").tobytes())
                        .hexdigest()
                        != row["patch_sha256"]
                    ):
                        raise ValueError("Source patch bytes changed")
        if prune:
            patches = (base / "patches").resolve()
            if cache not in patches.parents or patches.is_symlink():
                raise ValueError("Unsafe patch root")
            for folder in patches.iterdir():
                if folder.name in current:
                    continue
                if not re.fullmatch(r"(?:real|synthetic)-[0-9a-f]{24}", folder.name):
                    raise ValueError("Unknown folder: do not prune")
                target = folder.resolve()
                if target.parent != patches or folder.is_symlink():
                    raise ValueError("Unsafe stale folder")
                allowed = {
                    "gray.png",
                    "edges.png",
                    "centerline.png",
                    "protection.png",
                    "nodes.png",
                    "overlay.png",
                    "context.png",
                    "truth.json",
                }
                if any(
                    p.name not in allowed or not p.is_file() or p.is_symlink()
                    for p in folder.iterdir()
                ):
                    raise ValueError("Unknown stale folder contents")
                shutil.rmtree(target)
        shutil.copyfile(
            base / "samples.jsonl",
            docs
            / (
                "real-candidates.jsonl"
                if dataset == "real-v1"
                else "synthetic-manifest.jsonl"
            ),
        )
        shutil.copyfile(base / "summary.json", docs / (dataset + "-summary.json"))
    # Retain representative views from already reviewed P3A evidence and one raw corpus nomination.
    examples = [r for r in real if r.get("evidence_reference")]
    examples += [
        next(
            r
            for r in real
            if r["source_drawing_id"] == "A2-SG-009"
            and r["nomination_kind"] == "paired_edges"
        )
    ]
    canvas = Image.new("RGB", (768, len(examples) * 280), "white")
    draw = ImageDraw.Draw(canvas)
    references = []
    for index, row in enumerate(examples):
        base = cache / "real-v1" / row["patch_dir"]
        for column, filename in enumerate(("gray.png", "overlay.png", "context.png")):
            with Image.open(base / filename) as image:
                image = image.convert("RGB")
                image.thumbnail((256, 256))
                canvas.paste(image, (column * 256, index * 280 + 24))
        draw.text(
            (5, index * 280 + 3),
            row.get("evidence_reference") or "Raw corpus pair; unlabeled",
            fill="black",
        )
        references.append(
            {
                "sample_id": row["sample_id"],
                "drawing": row["source_drawing_id"],
                "source_page": row["source_page"],
                "source_bbox": row["source_bbox"],
                "sha256": row["source_sha256"],
                "label": None,
            }
        )
    canvas.save(docs / "representative-samples.png")
    atomic_json(docs / "representative-samples.json", references)
    before = read(docs / "production-before.json")
    after = product_snapshot()
    changed = sorted(
        k for k in before.keys() | after.keys() if before.get(k) != after.get(k)
    )
    if changed:
        raise ValueError(f"Production or prior tests changed: {changed}")
    packages = (
        "numpy",
        "scipy",
        "opencv-python",
        "Pillow",
        "pypdfium2",
        "ezdxf",
        "PySide6",
    )
    dependencies = {p: importlib.metadata.version(p) for p in packages}
    receipt = {
        "real_manifest_sha256": sha(docs / "real-candidates.jsonl"),
        "synthetic_manifest_sha256": sha(docs / "synthetic-manifest.jsonl"),
        "real_samples": len(real),
        "synthetic_samples": len(synthetic),
        "real_label_count": sum(r["label"] is not None for r in real),
        "source_drawing_count_extracted": len({r["source_drawing_id"] for r in real}),
        "real_by_kind": dict(Counter(r["nomination_kind"] for r in real)),
        "real_deterministic_decisions": dict(
            Counter(r["current_deterministic_decision"] for r in real)
        ),
        "synthetic_by_class": dict(Counter(r["label"] for r in synthetic)),
        "source_family_split_overlap": 0,
        "exact_patch_split_overlap": 0,
        "blind_sources_opened": 0,
        "production_files_hashed": len(before),
        "production_files_changed": changed,
        "production_snapshot_digest": digest(after),
        "dependencies": dependencies,
        "tooling_hashes": {
            p.name: sha(p) for p in sorted((ROOT / "tools/p3b").glob("*.py"))
        },
        "cache_path": str(cache),
        "cache_bytes": sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()),
        "retained_doc_bytes": sum(
            p.stat().st_size for p in docs.rglob("*") if p.is_file()
        ),
    }
    atomic_json(docs / "verification.json", receipt)
    print(receipt)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--docs", type=Path, default=ROOT / "docs/product-fix-p3b")
    ap.add_argument("--prune-stale-patches", action="store_true")
    args = ap.parse_args()
    finalize(args.cache, args.docs, args.prune_stale_patches)
