"""Reproducible label-blind nomination. Reads sources and CAD; never writes CAD.

Default development extraction reads train sources only, one corpus page each,
plus the six retained UAT pages. Page lists can be supplied with --pages JSON.
"""

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pypdfium2 as pdfium

from common import (
    ROOT,
    VERSION,
    atomic_json,
    check_output,
    digest,
    read,
    sha,
    validate_samples,
    write_rows,
)
from measurement import measure_row


def raster(file, page, dpi):
    path = Path(file["path"])
    if sha(path) != file["sha256"]:
        raise ValueError(f"Source changed: {path}")
    if path.suffix.lower() != ".pdf":
        with Image.open(path) as im:
            im.seek(page - 1)
            return np.array(
                im.convert("L")
            ), None  # physical DPI unknown, do not invent it
    with pdfium.PdfDocument(str(path)) as doc:
        source = doc[page - 1]
        try:
            w, h = source.get_size()
            effective_dpi = min(dpi, 4096 * 72 / max(w, h))
            # W03 retained source is used below, preserving its 110-DPI frame.
            bitmap = source.render(scale=effective_dpi / 72, grayscale=True)
            try:
                gray = np.array(bitmap.to_pil().convert("L"))
            finally:
                bitmap.close()
        finally:
            source.close()
    return gray, effective_dpi


def lines_from_source(gray, limit=6000, *, min_length_px=40):
    found = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    lines = [] if found is None else [list(map(float, x[0])) for x in found]
    result = [
        (f"P3B-LSD-{i:06d}", line, "PROPOSAL_ONLY")
        for i, line in enumerate(lines)
        if math.hypot(line[2] - line[0], line[3] - line[1]) >= min_length_px
    ]
    return result if limit is None else result[:limit]


def native_w03(root, height):
    import ezdxf

    doc = ezdxf.readfile(root / "local-artifacts/product-fix-p3a/W03/source-unit.dxf")
    output = []
    for entity in doc.modelspace():
        if entity.dxf.layer not in (
            "TRACE_STRAIGHT",
            "TRACE_CURVE",
            "ENGINEERING_SYMBOL",
        ):
            continue
        if entity.dxftype() == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            output.append(
                (
                    f"DXF:{entity.dxf.handle}",
                    [a.x, height - a.y, b.x, height - b.y],
                    "NATIVE_LINE",
                )
            )
        elif entity.dxftype() == "LWPOLYLINE":
            points = list(entity.get_points("xy"))
            if entity.closed and points:
                points.append(points[0])
            for i, (a, b) in enumerate(zip(points, points[1:])):
                if math.dist(a, b) >= 40:
                    output.append(
                        (
                            f"DXF:{entity.dxf.handle}:edge:{i}",
                            [a[0], height - a[1], b[0], height - b[1]],
                            "NATIVE_CONTOUR_EDGE",
                        )
                    )
    return output[:6000]


PAIR_MAX_SEPARATION_PX = 60
PAIR_MAX_ANGLE_DEG = 3


def nominations(lines, gray):
    """Loose geometry proposals, NOT merge rules or class evidence."""
    if lines:
        coords = np.array([entry[1] for entry in lines])
        starts, ends = coords[:, :2], coords[:, 2:]
        lengths = np.linalg.norm(ends - starts, axis=1)
        angles = np.arctan2(ends[:, 1] - starts[:, 1], ends[:, 0] - starts[:, 0])
        for i, (gid, line, origin) in enumerate(lines):
            tangent = (ends[i] - starts[i]) / max(lengths[i], 1e-9)
            normal = np.array([-tangent[1], tangent[0]])
            delta = np.abs((angles - angles[i] + np.pi / 2) % np.pi - np.pi / 2)
            along_a, along_b = (
                (starts - starts[i]) @ tangent,
                (ends - starts[i]) @ tangent,
            )
            lo, hi = np.minimum(along_a, along_b), np.maximum(along_a, along_b)
            overlap_lo, overlap_hi = np.maximum(lo, 0), np.minimum(hi, lengths[i])
            separation = np.abs((starts - starts[i]) @ normal)
            eligible = (
                (np.arange(len(lines)) > i)
                & (delta <= np.deg2rad(PAIR_MAX_ANGLE_DEG))
                & (separation >= 0.5)
                & (separation <= PAIR_MAX_SEPARATION_PX)
                & (overlap_hi - overlap_lo >= 40)
            )
            for j in np.flatnonzero(eligible):
                center = starts[i] + tangent * ((overlap_lo[j] + overlap_hi[j]) / 2)
                center += normal * (((starts[j] - starts[i]) @ normal) / 2)
                yield {
                    "kind": "paired_edges",
                    "center": center.tolist(),
                    "geometry": [lines[i], lines[j]],
                    "features": {
                        "distance_px": float(separation[j]),
                        "angle_delta_deg": float(np.rad2deg(delta[j])),
                        "overlap_px": float(overlap_hi[j] - overlap_lo[j]),
                    },
                }
        for line in lines:
            a = np.array(line[1])
            yield {
                "kind": "single_rule_control",
                "center": ((a[:2] + a[2:]) / 2).tolist(),
                "geometry": [line],
                "features": {},
            }
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        (gray < 160).astype(np.uint8), 8
    )
    for i in range(1, count):
        x, y, w, h, area = map(int, stats[i])
        if 6 <= max(w, h) <= 180 and area >= 6:
            yield {
                "kind": "untyped_ink_control",
                "center": [x + w / 2, y + h / 2],
                "geometry": [],
                "features": {},
                "ink_bbox": [x, y, w, h],
                "target_extent_basis": "8-connected pixels below 160; not an exclusive glyph/entity boundary",
            }


def point_distance(line, point):
    start, end = np.array(line[:2]), np.array(line[2:])
    t = np.clip(
        np.dot(np.array(point) - start, end - start)
        / max(np.sum((end - start) ** 2), 1e-9),
        0,
        1,
    )
    return float(np.linalg.norm(np.array(point) - (start + t * (end - start))))


def w03_graphic_boxes(height):
    import ezdxf

    doc = ezdxf.readfile(ROOT / "local-artifacts/product-fix-p3a/W03/source-unit.dxf")
    boxes = []
    for entity in doc.modelspace().query("IMAGE"):
        insert, u, v, size = (
            entity.dxf.insert,
            entity.dxf.u_pixel,
            entity.dxf.v_pixel,
            entity.dxf.image_size,
        )
        corners = [insert + u * x + v * y for x in (0, size.x) for y in (0, size.y)]
        xs, ys = [p.x for p in corners], [height - p.y for p in corners]
        boxes.append([min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)])
    return boxes


def crop_box(gray, center, side=256):
    h, w = gray.shape
    left = min(max(0, int(center[0] - side / 2)), max(0, w - side))
    top = min(max(0, int(center[1] - side / 2)), max(0, h - side))
    return [left, top, min(side, w - left), min(side, h - top)]


def render_channels(gray, bbox, geometry, protection_boxes=(), nodes=()):
    x, y, w, h = bbox
    source = Image.new("L", (256, 256), 255)
    source.paste(Image.fromarray(gray[y : y + h, x : x + w]), (0, 0))
    edges, center, protection, junction = [Image.new("L", (256, 256)) for _ in range(4)]
    edge_draw = ImageDraw.Draw(edges)
    for _, line, _ in geometry:
        edge_draw.line(
            (line[0] - x, line[1] - y, line[2] - x, line[3] - y), fill=255, width=1
        )
    if len(geometry) == 2:
        a, b = np.array(geometry[0][1]), np.array(geometry[1][1])
        if np.dot(a[2:] - a[:2], b[2:] - b[:2]) < 0:
            b = np.r_[b[2:], b[:2]]
        c = (a + b) / 2
        ImageDraw.Draw(center).line(
            (c[0] - x, c[1] - y, c[2] - x, c[3] - y), fill=255, width=1
        )
    pd = ImageDraw.Draw(protection)
    for a, b, c, d in protection_boxes:
        pd.rectangle((a - x, b - y, a + c - x, b + d - y), fill=255)
    jd = ImageDraw.Draw(junction)
    for a, b in nodes:
        jd.ellipse((a - x - 2, b - y - 2, a - x + 2, b - y + 2), fill=255)
    return [source, edges, center, protection, junction]


def run(inventory, splits, output, page_override=None, per_kind=24, *, page_plan=None, supplement=None):
    if page_plan is not None:
        from trial_sampling import build_trial_pool
        return build_trial_pool(page_plan, supplement)
    sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))
    from app.geometry.line_detect import LineSegment

    output = check_output(output)
    rows, hashes, visual_hashes = [], {}, set()
    split_map = {d["source_drawing_id"]: d for d in splits["drawings"]}
    pages = {
        "warehouse-electrical": [[1, 240], [2, 110], [3, 110]],
        "environment-building": [[1, 110], [3, 110], [4, 110]],
    }
    pages.update(page_override or {})
    for source in inventory["sources"]:
        sid = source["source_drawing_id"]
        if source["split"] != "train" or source["availability"] != "AVAILABLE":
            continue
        if split_map[sid]["split"] != source["split"]:
            raise ValueError("Inventory/split mismatch")
        file = source["files"][0]
        for page, requested_dpi in pages.get(sid, [[1, 110]]):
            if sid == "warehouse-electrical" and page == 3:
                retained = ROOT / "local-artifacts/product-fix-p3a/W03/source.png"
                if sha(Path(file["path"])) != file["sha256"]:
                    raise ValueError("W03 source PDF changed")
                gray = np.array(Image.open(retained).convert("L"))
                dpi = 110
                proof = read(ROOT / "docs/product-fix-p3a/W03-STROKE-REPLAY.json")
                if (
                    __import__("hashlib").sha256(gray.tobytes()).hexdigest()
                    != proof["source_sha256_verified"]
                ):
                    raise ValueError("W03 retained source raster changed")
                lines = native_w03(ROOT, gray.shape[0])
            else:
                gray, dpi = raster(file, page, requested_dpi)
                lines = lines_from_source(gray)
            protection_boxes, context_provenance = [], "NOT_AVAILABLE"
            uat = ("W" if sid == "warehouse-electrical" else "E") + f"{page:02d}"
            if sid in ("warehouse-electrical", "environment-building"):
                for ref in inventory["retained_label_context_refs"]:
                    if f"verified\\{uat}\\texts.json" in ref["retained_path"]:
                        path = Path(ref["retained_path"])
                        if path.is_file() and sha(path) == ref["sha256"]:
                            observations = read(path)
                            # Retained production observations are coordinates at the original UAT DPI.
                            frozen = read(
                                ROOT
                                / "cad_photo_to_dxf/tests/fixtures/product-p2b-ocr-observations.json"
                            )
                            original_dpi = (
                                frozen.get(uat, {}).get("input", {}).get("DPI")
                            )
                            if original_dpi and dpi:
                                scale = dpi / original_dpi
                                protection_boxes = [
                                    [v * scale for v in t["bbox"]] for t in observations
                                ]
                                context_provenance = "retained text boxes; partial protection, not full production mask"
                            break
            text_boxes = list(protection_boxes)
            graphic_boxes = []
            if sid == "warehouse-electrical" and page == 3:
                acceptance = read(ROOT / "docs/product-fix-p3a/W03-ACCEPTANCE.json")
                graphic_boxes = w03_graphic_boxes(gray.shape[0])
                protection_boxes += graphic_boxes
            endpoint_counts = Counter(
                tuple(entry[1][k : k + 2]) for entry in lines for k in (0, 2)
            )
            nodes = [p for p, n in endpoint_counts.items() if n > 1]
            used_centers, quota = [], Counter()
            # Human-only controls from retained text/graphic context; these are not structural truth.
            controls = [
                {
                    "kind": "text_control",
                    "center": [b[0] + b[2] / 2, b[1] + b[3] / 2],
                    "geometry": [],
                    "features": {},
                    "content_role": "text",
                }
                for b in text_boxes
            ]
            controls = [
                {
                    "kind": "graphic_control",
                    "center": [b[0] + b[2] / 2, b[1] + b[3] / 2],
                    "geometry": [],
                    "features": {},
                    "content_role": "graphic",
                }
                for b in graphic_boxes
            ] + controls
            proposals = list(nominations(lines, gray))
            # Fixed spatial ordering avoids privileging P3A accept/reject outcomes.
            proposals.sort(key=lambda n: (n["kind"], digest(n)))
            if sid == "warehouse-electrical" and page == 3:
                pairs = [p for p in proposals if p["kind"] == "paired_edges"]
                for name in ("thick-rule", "thin-table-rule", "true-double-wall"):
                    roi = acceptance["evidence"][name]["roi_source_px"]
                    center = [roi[0] + roi[2] / 2, roi[1] + roi[3] / 2]
                    nearby = min(
                        pairs,
                        key=lambda p: math.dist(center, p["center"]),
                        default=None,
                    )
                    selected_geometry = (
                        nearby["geometry"]
                        if nearby and math.dist(center, nearby["center"]) < 128
                        else []
                    )
                    if not selected_geometry and lines:
                        nearest = min(
                            lines, key=lambda entry: point_distance(entry[1], center)
                        )
                        if point_distance(nearest[1], center) < 128:
                            selected_geometry = [nearest]
                    controls.insert(
                        0,
                        {
                            "kind": "retained_source_roi",
                            "center": center,
                            "geometry": selected_geometry,
                            "features": nearby["features"]
                            if nearby and math.dist(center, nearby["center"]) < 128
                            else {},
                            "evidence_reference": name,
                        },
                    )
            for nomination in controls + proposals:
                kind, center = nomination["kind"], nomination["center"]
                if quota[kind] >= per_kind or any(
                    math.dist(center, old) < 80 for old in used_centers
                ):
                    continue
                bbox = crop_box(gray, center)
                geometry = nomination["geometry"]
                channels = render_channels(
                    gray, bbox, geometry, protection_boxes, nodes
                )
                patch_hash = (
                    __import__("hashlib").sha256(channels[0].tobytes()).hexdigest()
                )
                if patch_hash in visual_hashes:
                    continue
                visual_hashes.add(patch_hash)
                input_hash = (
                    __import__("hashlib")
                    .sha256(b"".join(c.tobytes() for c in channels))
                    .hexdigest()
                )
                if input_hash in hashes:
                    continue
                identity = {
                    "source": file["sha256"],
                    "page": page,
                    "dpi": dpi,
                    "bbox": bbox,
                    "geometry_ids": [g[0] for g in geometry],
                    "version": VERSION,
                }
                sample_id = "real-" + digest(identity)[:24]
                folder = output / "patches" / sample_id
                folder.mkdir(parents=True, exist_ok=True)
                for name, channel in zip(
                    ("gray", "edges", "centerline", "protection", "nodes"), channels
                ):
                    channel.save(folder / f"{name}.png")
                overlay = Image.merge("RGB", [channels[0]] * 3)
                overlay.paste((230, 40, 40), mask=channels[1])
                overlay.save(folder / "overlay.png")
                x, y, w, h = crop_box(gray, center, 512)
                Image.fromarray(gray[y : y + h, x : x + w]).save(folder / "context.png")
                measurements = measure_row(
                    {"candidate_geometry": geometry, "source_dpi": dpi}, gray
                )["current_p3a_measurement"]
                captured = (
                    sid == "warehouse-electrical"
                    and page == 3
                    and len(geometry) == 2
                    and all(g[2] == "NATIVE_LINE" for g in geometry)
                )
                row = {
                    **identity,
                    "sample_id": sample_id,
                    "source_drawing_id": sid,
                    "source_family_id": source["source_family_id"],
                    "source_page": page,
                    "source_bbox": bbox,
                    "source_dpi": dpi,
                    "requested_render_dpi": requested_dpi,
                    "candidate_geometry_ids": [g[0] for g in geometry],
                    "candidate_geometry": geometry,
                    "current_p3a_measurement": measurements,
                    "current_deterministic_decision": "PRESERVE_CAPTURED_W03"
                    if captured
                    else "NOT_CAPTURED",
                    "deterministic_provenance": "W03 closed zero-merge replay; final native entities"
                    if captured
                    else "no production decision captured for this offline nomination",
                    "label": None,
                    "label_provenance": None,
                    "split": "train",
                    "source_sha256": file["sha256"],
                    "source_path": file["path"],
                    "patch_sha256": patch_hash,
                    "input_sha256": input_hash,
                    "patch_dir": str(folder.relative_to(output)),
                    "domain": "real",
                    "nomination_kind": kind,
                    "features": nomination["features"],
                    "protection_provenance": context_provenance,
                    "full_protection_available": False,
                    "nodes_provenance": "exact endpoints in available nomination geometry; incomplete topology",
                    "label_scope": "classify highlighted candidate; controls classify central ink",
                    "evidence_reference": nomination.get("evidence_reference"),
                    "content_role": nomination.get("content_role", "unqualified"),
                    "split_manifest_sha256": digest(splits),
                }
                rows.append(row)
                hashes[input_hash] = sample_id
                quota[kind] += 1
                used_centers.append(center)
            print(sid, page, "nominations", dict(quota), flush=True)
    validate_samples(rows)
    write_rows(output / "samples.jsonl", rows)
    summary = {
        "dataset_version": digest(rows),
        "split_version": digest(splits),
        "samples": len(rows),
        "by_drawing": dict(Counter(r["source_drawing_id"] for r in rows)),
        "by_kind": dict(Counter(r["nomination_kind"] for r in rows)),
        "label_counts": {"UNLABELED": len(rows)},
        "blind_sources_opened": 0,
        "positive_patches": "UNQUALIFIED_PENDING_HUMAN",
        "negative_patches": "UNQUALIFIED_PENDING_HUMAN",
    }
    atomic_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--inventory", type=Path, default=ROOT / "docs/product-fix-p3b/inventory.json"
    )
    ap.add_argument(
        "--splits", type=Path, default=ROOT / "docs/product-fix-p3b/split-manifest.json"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--pages", type=Path, help="JSON: drawing_id -> [[one-based page, DPI], ...]"
    )
    ap.add_argument("--per-kind", type=int, default=24)
    args = ap.parse_args()
    print(
        run(
            read(args.inventory),
            read(args.splits),
            args.out,
            read(args.pages) if args.pages else None,
            args.per_kind,
        )
    )
