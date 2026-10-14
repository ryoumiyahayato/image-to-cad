"""Frozen-policy independent validation nominations; no models or blind access."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from common import (
    atomic_json,
    digest,
    read,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from extract import crop_box, lines_from_source, nominations, raster
from label_ui import diverse_order
from pilot_audit import CACHE, DOCS
from prepare_v2 import component_target, local_geometry, make_row, write_patches
from quality import POLICY, ink_distance, inspect
from queue_dedup import deduplicate

PAGES = {
    "A2-SG-008": [1],
    "G0R2-22E85E2DB7746A00": [9, 21, 30],
    "G0R2-4DC97797ABE2CB18": [19],
    "G0R2-99D5B85436EBB965": [1],
    "G0R2-F519B357241CAC3A": [49, 55],
}
MANIFEST = DOCS / "validation-v2-001.jsonl"
PLAN = DOCS / "validation-v2-001-plan.json"
STATE = DOCS / "labels/validation-v2-001.json"
OUT = CACHE / "validation-v2-001"


def measure_trial_targets(rows, source_windows):
    from measurement import measure_trial_targets as shared_measure
    return shared_measure(rows, source_windows)


def explicit_text_mask(file, page_number, effective_dpi, expected_gray):
    """Exclusive glyph ink from source-native TEXT operators, never box proximity.

    Remove native text only in a temporary in-memory PDF page; source is never saved.
    Pixels still dark without text (e.g. structural strokes crossing a text box) are
    explicitly NOT owned. Invisible OCR text with no ink contribution owns no pixels.
    """
    if Path(file["path"]).suffix.lower() != ".pdf":
        return np.zeros_like(expected_gray, bool), {
            "available": False,
            "reason": "No source-native PDF text operators",
        }
    with pdfium.PdfDocument(file["path"]) as document:
        page = document[page_number - 1]
        objects = list(page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_TEXT]))
        for obj in objects:
            page.remove_obj(obj)
            obj.close()
        bitmap = page.render(scale=effective_dpi / 72, grayscale=True)
        no_text = np.array(bitmap.to_pil().convert("L"))
        bitmap.close()
        page.close()
    if no_text.shape != expected_gray.shape:
        raise ValueError("Ownership render frame differs from candidate source")
    mask = (expected_gray <= 180) & (no_text > 180)
    return mask, {
        "available": bool(mask.any()),
        "native_text_objects": len(objects),
        "exclusive_owned_ink_pixels": int(mask.sum()),
        "provenance": "source-native TEXT operator ablation render; exclusive ink contribution",
        "source_modified_on_disk": False,
        "bbox_proximity_used": False,
    }


def owned_by_text(row, source, mask):
    """All members must be exclusively supported by native text-owned source ink."""
    x, y, w, h = row["source_bbox"]
    owned = np.argwhere(mask[y : y + h, x : x + w])[:, ::-1]
    if not len(owned):
        return False
    if not row["candidate_geometry"]:
        tx, ty, tw, th = row["target_roi"]
        dark = source[ty : ty + th, tx : tx + tw] <= 180
        return bool(
            dark.any() and mask[ty : ty + th, tx : tx + tw][dark].mean() >= 0.98
        )
    unowned = np.argwhere(
        (source[y : y + h, x : x + w] <= 180) & ~mask[y : y + h, x : x + w]
    )[:, ::-1]
    own_tree = cKDTree(owned)
    other_tree = cKDTree(unowned) if len(unowned) else None
    for _, line, _ in row["candidate_geometry"]:
        a, b = np.array(line).reshape(2, 2) - [x, y]
        points = np.linspace(a, b, max(9, int(np.linalg.norm(b - a)) + 1))
        distances = own_tree.query(points)[0]
        other = other_tree.query(points)[0] if other_tree else np.full(len(points), 1e6)
        if ((distances <= 1.5) & (other > 1.5)).mean() < 0.98:
            return False
    return True


def candidates(*, page_plan=None, supplement=None):
    if page_plan is not None:
        from extract import run
        return run(None, None, None, page_plan=page_plan, supplement=supplement)
    if (
        read(DOCS / "FORMAL-SEED-FINAL-STATUS.json")["FORMAL_SEED_FINAL_STATUS"]
        != "PASS"
    ):
        raise ValueError("Train-seed PASS required before any validation source access")
    inventory = read(DOCS / "inventory.json")
    split = read(DOCS / "split-manifest.json")
    permitted = {
        s["source_drawing_id"]: s
        for s in inventory["sources"]
        if s["split"] == "validation" and s["availability"] == "AVAILABLE"
    }
    assigned = {s["source_drawing_id"]: s for s in split["drawings"]}
    rows, images, contexts, rejected, ownership = [], {}, {}, Counter(), []
    for sid, pages in PAGES.items():
        s = permitted[sid]
        if (
            assigned[sid]["split"] != "validation"
            or assigned[sid]["source_family_id"] != s["source_family_id"]
        ):
            raise ValueError("Frozen validation boundary mismatch")
        file = s["files"][0]
        for page in pages:
            gray, dpi = raster(file, page, 110)
            mask, owner_proof = explicit_text_mask(file, page, dpi, gray)
            ownership.append(
                {
                    "source_drawing_id": sid,
                    "source_page": page,
                    "source_sha256": file["sha256"],
                    **owner_proof,
                }
            )
            distance = ink_distance(gray)
            stats = cv2.connectedComponentsWithStats((gray < 180).astype(np.uint8), 8)[
                2
            ]
            proposals = list(nominations(lines_from_source(gray), gray))
            proposals.sort(key=lambda n: (n["kind"], digest(n)))
            quotas, used = Counter(), []
            for proposal in proposals:
                kind, center = proposal["kind"], proposal["center"]
                if quotas[kind] >= 24 or any(
                    np.linalg.norm(np.array(center) - c) < 80 for c in used
                ):
                    continue
                bbox = crop_box(gray, center)
                geometry = proposal["geometry"]
                identity = {
                    "source": file["sha256"],
                    "page": page,
                    "dpi": dpi,
                    "bbox": bbox,
                    "geometry": geometry,
                    "nomination_policy": "existing_extract.nominations+V2_quality",
                }
                old = {
                    "sample_id": "val-base-" + digest(identity)[:24],
                    "source_drawing_id": sid,
                    "source_family_id": s["source_family_id"],
                    "source_page": page,
                    "source_bbox": bbox,
                    "source_dpi": dpi,
                    "requested_render_dpi": 110,
                    "source_sha256": file["sha256"],
                    "source_path": file["path"],
                    "split": "validation",
                    "domain": "real",
                    "candidate_geometry": geometry,
                    "candidate_geometry_ids": [g[0] for g in geometry],
                    "features": proposal["features"],
                    "current_p3a_measurement": None,
                    "current_deterministic_decision": "NOT_CAPTURED",
                    "label": None,
                    "label_provenance": None,
                    "content_role": "unqualified",
                }
                original_quality = inspect(old, gray, distance)
                if geometry and original_quality["HUMAN_QUEUE_ELIGIBLE"]:
                    row, patch = make_row(old, geometry, None, gray, True)
                elif geometry:
                    m = original_quality["metrics"]
                    if any(
                        m.get(p + "_SOURCE_SUPPORT_RATIO", 0) < 0.9
                        or m.get(p + "_MEAN_DISTANCE_TO_DARK_INK", 1e6) > 1
                        or m.get(p + "_LOCAL_INK_ALIGNMENT", 0) < 0.75
                        for p in ("A", "B")[: len(geometry)]
                    ):
                        rejected["UNSUPPORTED_OR_MISALIGNED_GEOMETRY"] += 1
                        continue
                    local = local_geometry(geometry, center)
                    if not local:
                        continue
                    row, patch = make_row(old, local, None, gray, False)
                else:
                    target = component_target(gray, np.array(center), stats)
                    if not target:
                        continue
                    row, patch = make_row(old, [], target, gray, False)
                q = inspect(row, gray, distance)
                if not q["HUMAN_QUEUE_ELIGIBLE"]:
                    rejected.update(q["rejection_reasons"])
                    continue
                row.update(
                    quality=q,
                    pool_version="validation-v2-001",
                    label_scope="exact nominated object; glyph/symbol/graphic internal strokes are non-target",
                    training_authorized=False,
                    nomination_status=None,
                    split_manifest_sha256=sha(DOCS / "split-manifest.json"),
                )
                row["nomination_parent_id"] = row.pop("parent_v1_sample_id")
                row["sample_id"] = (
                    "val-v2-"
                    + digest(
                        {
                            "identity": identity,
                            "bbox": row["source_bbox"],
                            "geometry": row["candidate_geometry"],
                            "target": row["target_roi"],
                            "quality_policy": POLICY,
                        }
                    )[:24]
                )
                row["patch_dir"] = "patches/" + row["sample_id"]
                is_text = owned_by_text(row, gray, mask)
                row["explicit_ownership"] = (
                    "SOURCE_NATIVE_TEXT_EXCLUSIVE_INK" if is_text else "NOT_ESTABLISHED"
                )
                row["ownership_provenance"] = owner_proof
                if is_text and row["target_kind"] != "CONTROL":
                    rejected["EXPLICIT_TEXT_GLYPH_OWNERSHIP_PREFILTER"] += 1
                    continue
                if is_text:
                    row["content_role"] = "text"
                quotas[kind] += 1
                used.append(np.array(center))
                rows.append(row)
                images[row["sample_id"]] = patch
                cx, cy, cw, ch = crop_box(
                    gray, np.array(row["source_bbox"][:2]) + 128, 512
                )
                contexts[row["sample_id"]] = Image.fromarray(
                    gray[cy : cy + ch, cx : cx + cw]
                )
            print("Validation extraction", sid, page, dict(quotas), flush=True)
    unique, duplicates, dedup_counts = deduplicate(
        rows, None, lambda r: images[r["sample_id"]], radius=320, hamming=24
    )
    return (
        unique,
        images,
        contexts,
        {
            "ownership": ownership,
            "rejections": dict(rejected),
            "dedup_counts": dedup_counts,
            "dedup_details": duplicates,
        },
    )


def propose(rows):
    # Small five-source CONTROL set; target-type coverage is not human class balancing.
    controls, targets = defaultdict(list), defaultdict(list)
    for row in rows:
        (controls if row["target_kind"] == "CONTROL" else targets)[
            row["source_drawing_id"]
        ].append(row)
    selected = []
    for sid in sorted(PAGES):
        if controls[sid]:
            selected.append(
                min(
                    controls[sid],
                    key=lambda r: (
                        r["explicit_ownership"] != "SOURCE_NATIVE_TEXT_EXCLUSIVE_INK",
                        r["sample_id"],
                    ),
                )
            )
    while len(selected) < 50:
        changed = False
        for sid in sorted(PAGES):
            if len(selected) >= 50:
                break
            if sid == "G0R2-99D5B85436EBB965":
                continue  # archive inventory page: curated non-target only, no pretend structural evidence
            pool = targets[sid]
            if not pool:
                continue
            counts = Counter(
                r["target_kind"] for r in selected if r["source_drawing_id"] == sid
            )
            pool.sort(
                key=lambda r: (
                    counts[r["target_kind"]],
                    r["source_page"],
                    r["sample_id"],
                )
            )
            selected.append(pool.pop(0))
            changed = True
        if not changed:
            raise ValueError(
                f"Only {len(selected)} gated validation targets; do not bypass quality"
            )
    return diverse_order(selected)


def prepare():
    if STATE.exists():
        raise ValueError("Validation review has begun; do not rewrite manifest/assets")
    rows, images, contexts, diagnostics = candidates()
    chosen = propose(rows)
    validate_samples(read_rows(DOCS / "formal-seed-v2-001.jsonl") + chosen)
    # Global exact source-input leak checks in addition to whole-drawing/family checks.
    train_hashes = {
        r["patch_sha256"] for r in read_rows(DOCS / "real-candidates.jsonl")
    }
    if any(r["patch_sha256"] in train_hashes for r in chosen):
        raise ValueError("Exact train/validation patch leak")
    OUT.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists() and digest(read_rows(MANIFEST)) != digest(chosen):
        raise ValueError("Existing validation manifest differs")
    write_patches(OUT, chosen, images, contexts)
    write_rows(MANIFEST, chosen)
    write_rows(OUT / "samples.jsonl", chosen)
    plan = {
        "batch": "validation-v2-001",
        "sample_count": len(chosen),
        "manifest_sha256": sha(MANIFEST),
        "labels_path": str(STATE),
        "patch_root": str(OUT),
        "split_manifest_sha256": sha(DOCS / "split-manifest.json"),
        "final_train_status_sha256": sha(DOCS / "FORMAL-SEED-FINAL-STATUS.json"),
        "validation_drawings": sorted({r["source_drawing_id"] for r in chosen}),
        "by_drawing": dict(Counter(r["source_drawing_id"] for r in chosen)),
        "by_type": dict(Counter(r["target_kind"] for r in chosen)),
        "page_selection": PAGES,
        "page_selection_provenance": "foreground source-page overview for drawing-context coverage; no labels/models/errors",
        "quality_policy": POLICY,
        "ownership_policy": "exclusive source-native TEXT ink only; never spatial text-box proximity; unknown remains unfiltered",
        "FUTURE_OTHER_PREFILTER": "READY",
        "curated_OTHER_control_limit": 5,
        "training_authorized": False,
        "model_trained": False,
        "blind_sources_accessed": 0,
        "integrity_verified": True,
        "visual_curation_status": "PENDING",
        **diagnostics,
    }
    atomic_json(PLAN, plan)
    for start in range(0, 50, 10):
        canvas = Image.new("RGB", (1024, 1420), "white")
        draw = ImageDraw.Draw(canvas)
        for j, row in enumerate(chosen[start : start + 10]):
            left, top = (j % 2) * 512, (j // 2) * 284
            draw.text(
                (left + 3, top + 3),
                f"#{start + j + 1} {row['target_kind']} {row['source_drawing_id']}",
                fill="black",
            )
            canvas.paste(images[row["sample_id"]], (left, top + 25))
            with Image.open(OUT / row["patch_dir"] / "overlay.png") as overlay:
                canvas.paste(overlay.resize((256, 256)), (left + 256, top + 25))
        canvas.save(OUT / f"candidate-review-{start + 1:03d}-{start + 10:03d}.png")
    print(
        {
            "prepared": 50,
            "by_drawing": plan["by_drawing"],
            "by_type": plan["by_type"],
            "rejections": plan["rejections"],
        },
        flush=True,
    )


def seal_reviewed():
    """Explicit foreground seal after inspecting all 50 contact-sheet targets."""
    if STATE.exists():
        raise ValueError("Validation labeling has started; do not reseal its inputs")
    plan, rows = read(PLAN), read_rows(MANIFEST)
    if len(rows) != 50 or sha(MANIFEST) != plan["manifest_sha256"]:
        raise ValueError("Prepared validation identity changed")
    names = (
        "gray.png",
        "overlay.png",
        "support.png",
        "context.png",
        "edges.png",
        "centerline.png",
        "protection.png",
        "nodes.png",
    )
    plan.update(
        final_train_status_sha256=sha(DOCS / "FORMAL-SEED-FINAL-STATUS.json"),
        visual_curation_status="ALL_50_INSPECTED_READY",
        visual_curation_provenance="All five 10-target source/overlay sheets inspected in this foreground task; no physical classes assigned",
        overview_pages_exposed_for_nomination=146,
        nomination_extraction_pages=8,
        context_coverage="Walls/shafts/enclosures, doors/openings, junctions, annotation/frame/table rules, and five source-diverse non-target controls",
        by_source_family=dict(Counter(r["source_family_id"] for r in rows)),
        by_effective_dpi=dict(
            Counter(
                "UNKNOWN_SOURCE_DPI"
                if r["source_dpi"] is None
                else f"{r['source_dpi']:.6f}"
                for r in rows
            )
        ),
        ownership_limit="Explicit text ownership is available on only three selected native-PDF pages; scanned sources remain unknown. No ownership is inferred from proximity or image-object membership.",
        asset_sha256={
            r["patch_dir"] + "/" + name: sha(OUT / r["patch_dir"] / name)
            for r in rows
            for name in names
        },
        preview_sha256={
            f.name: sha(f) for f in sorted(OUT.glob("candidate-review-*.png"))
        },
        queue_frozen=True,
    )
    atomic_json(PLAN, plan)
    print(
        {
            "sealed": 50,
            "by_family": plan["by_source_family"],
            "dpi": plan["by_effective_dpi"],
        },
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-reviewed", action="store_true")
    args = parser.parse_args()
    if args.seal_reviewed:
        seal_reviewed()
    else:
        prepare()
