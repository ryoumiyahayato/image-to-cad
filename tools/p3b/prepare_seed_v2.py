"""Prepare, but never launch, the first formal V2 human seed queue."""

import argparse
from collections import Counter, defaultdict

from PIL import Image

from audit_acceptance import audit_state
from common import (
    atomic_json,
    digest,
    read,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from label_ui import diverse_order
from pilot_audit import CACHE, DOCS
from prepare_v2 import build_pool, write_patches
from quality import POLICY
from queue_dedup import deduplicate

QUOTAS = {"PAIR": 60, "SINGLE": 20, "CONTROL": 20}
SEED_POLICY = {
    "version": "formal-seed-v2-1",
    "radius_px": 320,
    "hamming_bits": 24,
    "max_per_drawing": 10,
    "exclude_acceptance_parent_candidates": True,
}


def select_batch(rows, quotas=None, max_per_drawing=10):
    quotas = quotas or QUOTAS
    per_source = defaultdict(list)
    for row in rows:
        per_source[row["source_drawing_id"]].append(row)
    selected, kinds, sources, local_kinds = [], Counter(), Counter(), Counter()
    while len(selected) < sum(quotas.values()):
        changed = False
        for sid in sorted(per_source):
            eligible = [
                r
                for r in per_source[sid]
                if kinds[r["target_kind"]] < quotas[r["target_kind"]]
            ]
            if sources[sid] >= max_per_drawing or not eligible:
                continue
            # Target-type balance is not a guessed physical class.
            row = min(
                eligible,
                key=lambda r: (
                    local_kinds[(sid, r["target_kind"])],
                    kinds[r["target_kind"]] / quotas[r["target_kind"]],
                    -quotas[r["target_kind"]],
                    r["sample_id"],
                ),
            )
            per_source[sid].remove(row)
            selected.append(row)
            kinds[row["target_kind"]] += 1
            local_kinds[(sid, row["target_kind"])] += 1
            sources[sid] += 1
            changed = True
        if not changed:
            raise ValueError(
                f"Insufficient diverse gated nominations: {dict(kinds)}; do not relax gates"
            )
    return diverse_order(selected)


def prepare():
    acceptance_manifest = DOCS / "real-v2-acceptance.jsonl"
    acceptance_state = DOCS / "labels/v2-ui-acceptance.json"
    acceptance = read_rows(acceptance_manifest)
    state = read(acceptance_state)
    audit = read(DOCS / "v2-acceptance-audit.json")
    live = audit_state(state, acceptance, sha(acceptance_manifest))
    if (
        audit["V2_UI_ACCEPTANCE"] != "PASS"
        or audit["state_sha256"] != sha(acceptance_state)
        or not live["FINAL_STATE_INTERNALLY_CONSISTENT"]
        or live["VALID_TARGET"] < 29
    ):
        raise ValueError("A current, internally consistent V2 PASS is required")
    preserved = {
        p: sha(p)
        for p in (
            acceptance_state,
            acceptance_manifest,
            DOCS / "split-manifest.json",
            DOCS / "labels/local-labels.json",
            DOCS / "real-candidates.jsonl",
        )
    }
    reader, candidates, images, contexts, rejections = build_pool()
    parents = {r["parent_v1_sample_id"] for r in acceptance}
    candidates = [r for r in candidates if r["parent_v1_sample_id"] not in parents]
    # Suppress repetitions against all 30 previous targets, including the U target.
    anchors = {}
    for row in acceptance:
        with Image.open(CACHE / "real-v2" / row["patch_dir"] / "gray.png") as image:
            anchors[row["sample_id"]] = image.convert("L")
    acceptance_ids = {r["sample_id"] for r in acceptance}
    unique, duplicates, counts = deduplicate(
        acceptance + candidates,
        None,
        lambda r: anchors[r["sample_id"]]
        if r["sample_id"] in acceptance_ids
        else images[r["sample_id"]],
        radius=SEED_POLICY["radius_px"],
        hamming=SEED_POLICY["hamming_bits"],
    )
    unique = [r for r in unique if r["sample_id"] not in acceptance_ids]
    # Exact raster repeats anywhere in the queue are suppressed before selection.
    hashes = {r["patch_sha256"] for r in acceptance}
    distinct, cross_source_exact = [], []
    for row in unique:
        if row["patch_sha256"] in hashes:
            cross_source_exact.append(row["sample_id"])
            continue
        hashes.add(row["patch_sha256"])
        distinct.append(row)
    chosen = select_batch(distinct)
    for row in chosen:
        row["pool_version"] = "real-v2-formal-seed-001"
        row["queue_purpose"] = "formal human seed labeling; no training authorized"
        row["nomination_status"] = row["label"] = row["label_provenance"] = None
        row["training_authorized"] = False
    validate_samples(chosen)
    if any(r["split"] != "train" for r in chosen):
        raise ValueError("Frozen train-only boundary violated")
    manifest = DOCS / "formal-seed-v2-001.jsonl"
    out = CACHE / "real-v2-formal-seed-001"
    # Reviewed states are immutable here; regeneration may only reproduce the same queue.
    if manifest.exists() and digest(read_rows(manifest)) != digest(chosen):
        raise ValueError("Existing formal manifest differs; create a new batch/version")
    if (DOCS / "labels/formal-seed-v2-001.json").exists():
        raise ValueError(
            "Formal labeling has begun; preparation must not rewrite assets"
        )
    out.mkdir(parents=True, exist_ok=True)
    write_patches(out, chosen, images, contexts)
    write_rows(manifest, chosen)
    write_rows(out / "samples.jsonl", chosen)
    summary = {
        "queue_version": "real-v2-formal-seed-001",
        "purpose": chosen[0]["queue_purpose"],
        "proposed_first_batch_size": len(chosen),
        "ready": True,
        "launched": False,
        "training_authorized": False,
        "acceptance_state_sha256": sha(acceptance_state),
        "acceptance_manifest_sha256": sha(acceptance_manifest),
        "split_manifest_sha256": sha(DOCS / "split-manifest.json"),
        "manifest_sha256": sha(manifest),
        "cache": str(out),
        "labels_path": str(DOCS / "labels/formal-seed-v2-001.json"),
        "by_drawing": dict(Counter(r["source_drawing_id"] for r in chosen)),
        "by_target_type": dict(Counter(r["target_kind"] for r in chosen)),
        "available_before_selection": dict(Counter(r["target_kind"] for r in distinct)),
        "quality_policy": POLICY,
        "dedup_policy": SEED_POLICY,
        "excluded_acceptance_parent_candidates": len(parents),
        "dedup_against_acceptance_and_pool": counts,
        "cross_source_or_type_exact_raster_repeats_removed": len(cross_source_exact),
        "selection_uses_human_classes_or_predictions": False,
        "stage_0_required": True,
        "stage_1_requires_human_v": True,
        "fresh_status_and_class_records": True,
        "source_pages_accessed": sorted(reader.opened),
        "validation_sources_accessed": 0,
        "blind_sources_accessed": 0,
        "rejection_counts": dict(rejections),
        "cache_lifecycle": "Only 100 selected patches retained; transient pool freed on exit. Regenerate with this script; retain until review completes, then archive with labels/manifest or remove only after preserving human evidence.",
    }
    atomic_json(DOCS / "formal-seed-v2-summary.json", summary)
    atomic_json(
        DOCS / "formal-seed-v2-dedup.json",
        {
            "details": duplicates,
            "exact_raster_suppressed": cross_source_exact,
            "scope": "Train-only transient pool + acceptance anchors; no class-based selection",
        },
    )
    for path, before in preserved.items():
        if sha(path) != before:
            raise ValueError(f"Frozen evidence changed: {path}")
    print(summary)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()
