"""Inventory allowlisted evidence; blind source contents are never accessed."""

import argparse
import csv
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from common import ROOT, atomic_json, read, sha, product_snapshot


def planned_sources(page_plan, supplement, root=ROOT):
    """Resolve only explicit nonblind PDF plan entries; no historical rewrites."""
    registry = {r["entry_id"]: r for r in supplement["rows"]}
    materials = Path(supplement["materials_root"]).resolve()
    sources = []
    for unit in page_plan["rows"]:
        if unit["page_or_layout"]["type"] != "PDF":
            continue
        original = registry[unit["source_entry_id"]]
        if original["role"] != "原始PDF":
            raise ValueError("Planned PDF must refer to an original PDF")
        partition = str(original["p3b_mapping"].get("split") or "").lower()
        if "blind" in partition or "validation" in partition or unit.get("protected_source_conflict"):
            unit["preview_skip_reason"] = "Known protected validation/blind association; metadata only, contents unopened"
            continue
        path = (materials / unit["relative_path"]).resolve()
        if materials not in path.parents or not path.is_file():
            raise ValueError(f"Explicit source missing/outside materials: {path}")
        sources.append({
            **unit,
            "resolved_path": str(path),
            "source_drawing_id": original["p3b_mapping"].get("source_drawing_id")
            or next(iter(original["existing_source_ids"]), original["entry_id"]),
            "source_family_id": (unit.get("content_source") or {}).get("family_id", unit["design_family"]["plan_id"]),
            "content_source": unit.get("content_source"),
            "container_identity": unit.get("container_identity"),
            "split": "unassigned_preview",
            "source_existing_split": original["p3b_mapping"].get("split"),
        })
    return sources


def build(root=ROOT, *, page_plan=None, supplement=None):
    if page_plan is not None:
        if supplement is None:
            raise ValueError("Explicit plan requires the source supplement")
        return planned_sources(page_plan, supplement, root)
    outer = root.parent
    registry = root / "docs/draftsman/corpus"
    split = read(registry / "g0_corpus_v1_split.json")
    acquisition = read(registry / "g0_corpus_v1_acquisition_manifest.json")
    metadata = {
        x["source_group_id"]: x for rows in split["splits"].values() for x in rows
    }
    sources = []
    for group in acquisition["source_groups"]:
        partition = {
            "DEV": "train",
            "VALIDATION": "validation",
            "LOCKED_BLIND": "blind_test",
        }[group["split"]]
        sid = group["source_group_id"]
        entry = {
            "source_drawing_id": sid,
            "source_family_id": metadata[sid]["source_family_id"],
            "split": partition,
            "origin": "corpus-v1",
            "source_kind": metadata[sid]["vector_raster_status"],
            "availability": "NOT_MATERIALIZED",
            "files": [],
            "pages": None,
            "content_accessed": False,
            "vector_ground_truth": "NOT_QUALIFIED",
            "rights": group["governance_state"],
        }
        for f in group["files"]:
            relative = f["local_relative_path"]
            # Blind: use only the frozen acquisition metadata, no stat/open/hash/render.
            if partition == "blind_test":
                entry["files"].append(
                    {
                        "path": relative,
                        "sha256": f["sha256"],
                        "format": f["detected_format"],
                        "pages": f.get("page_count", 1),
                        "availability": "RECORDED_ONLY",
                    }
                )
                entry["availability"] = "RECORDED_ONLY"
                continue
            path = next(
                (p for p in (root / relative, outer / relative) if p.is_file()), None
            )
            if path is None:
                continue
            count = f.get("page_count", 1)
            if partition == "train":
                if path.suffix.lower() == ".pdf":
                    with pdfium.PdfDocument(str(path)) as doc:
                        count = len(doc)
                else:
                    with Image.open(path) as im:
                        count = getattr(im, "n_frames", 1)
                actual_hash = sha(path)
                if actual_hash != f["sha256"]:
                    raise ValueError(f"Source hash differs: {path}")
            else:
                actual_hash = f[
                    "sha256"
                ]  # validation source contents stay unopened too
            entry["files"].append(
                {
                    "path": str(path),
                    "sha256": actual_hash,
                    "format": f["detected_format"],
                    "pages": count,
                }
            )
            entry["availability"] = "AVAILABLE"
        entry["pages"] = sum(f["pages"] for f in entry["files"]) or None
        sources.append(entry)
    assets = root / "cad_photo_to_dxf/tests/real_regression/assets"
    for sid, filename, pages, kind in (
        (
            "warehouse-electrical",
            "sources/warehouse-electrical-vector.pdf",
            7,
            "VECTOR_PDF",
        ),
        (
            "environment-building",
            "sources/environment-building-scan.pdf",
            14,
            "RASTER_PDF",
        ),
        ("sample-plan-photo", "test.jpg", 1, "PHOTO"),
    ):
        path = assets / filename
        sources.append(
            {
                "source_drawing_id": sid,
                "source_family_id": "user-project-haiyang"
                if sid != "sample-plan-photo"
                else sid,
                "split": "train",
                "origin": "P1/P2B/P3A/real-UAT"
                if sid != "sample-plan-photo"
                else "retained-regression-photo",
                "source_kind": kind,
                "availability": "AVAILABLE" if path.is_file() else "MISSING",
                "content_accessed": False,
                "pages": pages,
                "vector_ground_truth": "SOURCE_VECTOR_PATHS_NOT_ENTITY_TRUTH"
                if kind == "VECTOR_PDF"
                else "NONE",
                "files": [
                    {
                        "path": str(path),
                        "sha256": sha(path),
                        "format": path.suffix[1:].upper(),
                        "pages": pages,
                    }
                ],
                "rights": "INTERNAL_TASK_ONLY; no public redistribution",
            }
        )
    # Related original CAD packages: retained conversion audit is provenance, not source-aligned truth.
    audit = read(
        root / "local-artifacts/draftsman/user-supplied-ingest/conversion-audit.json"
    )
    vector_refs = [
        {
            "path": s["output_path"],
            "exists": Path(s["output_path"]).is_file(),
            "sha256_recorded": s["output_sha256"],
            "source_sha256_recorded": s["source_sha256"],
            "qualification": "NATIVE_CAD_AVAILABLE; raster/entity correspondence not qualified",
            "family": "user-project-haiyang",
            "split": "train",
        }
        for s in audit["samples"]
        if s.get("conversion_success")
    ]
    rasters = []
    for base in (
        outer / "product-uat-20261005",
        root / "local-artifacts/product-fix-p1/verified",
        root / "local-artifacts/product-fix-p2b",
        root / "local-artifacts/product-fix-p3a",
    ):
        for path in sorted(base.glob("*/source.png")):
            rasters.append(
                {
                    "path": str(path),
                    "sha256": sha(path),
                    "role": "source_raster; derived, not independent drawing",
                }
            )
    history_refs = []
    with (outer / "storage-cleanup-20261006/retained-manifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        for row in csv.DictReader(stream):
            if row["source"].endswith("texts.json") and any(
                t in row["source"] for t in ("product-fix-p1", "product-uat-20261005")
            ):
                history_refs.append(
                    {
                        "source": row["source"],
                        "retained_path": row["retained_path"],
                        "sha256": row["sha256"],
                    }
                )
    plan = {
        "version": "p3b-split-v1",
        "authority_sha256": sha(registry / "g0_corpus_v1_split.json"),
        "policy": "whole source group plus source family; keep established validation and blind allocations",
        "drawings": [
            {
                k: s[k]
                for k in (
                    "source_drawing_id",
                    "source_family_id",
                    "split",
                    "availability",
                )
            }
            for s in sources
        ],
        "blind_access": "PROHIBITED_IN_DEVELOPMENT",
        "related_user_CAD": "train only",
    }
    family_splits = {}
    hash_splits = {}
    for d in plan["drawings"]:
        family = d["source_family_id"]
        if family in family_splits and family_splits[family] != d["split"]:
            raise ValueError(f"Family split conflict: {family}")
        family_splits[family] = d["split"]
    for s in sources:
        for f in s["files"]:
            if f["sha256"] in hash_splits and hash_splits[f["sha256"]] != s["split"]:
                raise ValueError("Exact source duplicate across splits")
            hash_splits[f["sha256"]] = s["split"]
    available = [s for s in sources if s["availability"] == "AVAILABLE"]
    unique_rasters = {r["sha256"] for r in rasters}
    result = {
        "version": "p3b-inventory-v1",
        "sources": sources,
        "raster_aliases": rasters,
        "retained_label_context_refs": history_refs,
        "native_CAD_refs": vector_refs,
        "counts": {
            "DRAWINGS_AVAILABLE": len(available),
            "DRAWINGS_REGISTERED": len(sources),
            "PAGE_COUNT_AVAILABLE_NONBLIND": sum(s["pages"] for s in available),
            "PAGE_COUNT_BLIND_RECORDED_ONLY": sum(
                s["pages"] or 0 for s in sources if s["split"] == "blind_test"
            ),
            "RASTER_COUNT_SOURCE_ALIASES": len(rasters),
            "RASTER_COUNT_UNIQUE_SOURCE_ALIASES": len(unique_rasters),
            "SOURCE_FORMATS": dict(
                Counter(f["format"] for s in available for f in s["files"])
            ),
            "VECTOR_GROUND_TRUTH_AVAILABLE": "native CAD and vector PDF exist; no aligned real stroke truth qualified",
        },
    }
    return result, plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs/product-fix-p3b")
    args = ap.parse_args()
    inventory, plan = build()
    atomic_json(args.out / "inventory.json", inventory)
    atomic_json(args.out / "split-manifest.json", plan)
    snapshot = args.out / "production-before.json"
    if not snapshot.exists():
        atomic_json(snapshot, product_snapshot())
    print(inventory["counts"])
