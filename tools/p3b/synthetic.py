"""Synthetic physical CAD primitives with truth independent of raster appearance."""

import argparse
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from common import atomic_json, check_output, digest, sha, validate_samples, write_rows
from extract import crop_box, render_channels
from p3a_baseline import measure

WIDTHS = (0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00)
SCENES = (
    "isolated",
    "parallel",
    "T_junction",
    "cross_junction",
    "corner",
    "door_opening",
    "table_intersection",
    "frame_edge",
    "shaft_enclosure",
    "fill",
    "hatch",
    "text",
    "graphic",
    "noise",
)


def truth(scene, width, seed):
    rng = np.random.default_rng(seed)
    two = scene in ("parallel", "door_opening", "shaft_enclosure") or (
        scene
        in (
            "T_junction",
            "cross_junction",
            "corner",
            "table_intersection",
            "frame_edge",
        )
        and seed % 2 == 0
    )
    spacing = float(rng.uniform(0.3, 5.0)) + width
    label = "TRUE_PARALLEL_STRUCTURE" if two else "SINGLE_PHYSICAL_STROKE"
    if scene in ("fill", "hatch", "text", "graphic", "noise"):
        label = "OTHER"
    primitives = []

    def line(coords, identifier, w=width):
        primitives.append(
            {"id": identifier, "type": "LINE", "xy_mm": coords, "width_mm": w}
        )

    if label != "OTHER":
        for i, y in enumerate(([12 - spacing / 2, 12 + spacing / 2] if two else [12])):
            if scene == "door_opening":
                line([2, y, 10, y], f"rail-{i}-left")
                line([14, y, 22, y], f"rail-{i}-right")
            else:
                line([2, y, 22, y], f"rail-{i}")
        if scene in ("T_junction", "cross_junction", "table_intersection"):
            line([12, 2, 12, 22 if scene != "T_junction" else 12], "junction")
        if scene in ("corner", "frame_edge", "shaft_enclosure"):
            line([2, 12, 2, 2], "left-corner")
        if scene in ("frame_edge", "shaft_enclosure"):
            line([22, 12, 22, 2], "right-corner")
            line([2, 2, 22, 2], "top-frame")
        if scene == "shaft_enclosure":
            for x in (2 + spacing, 22 - spacing):
                line([x, 12 - spacing / 2, x, 3 + spacing], f"inner-{x:.4f}")
    elif scene == "fill":
        primitives.append({"id": "fill", "type": "SOLID", "bbox_mm": [5, 7, 14, 10]})
    elif scene == "hatch":
        for i in range(3, 20):
            line([i, 5, i + 3, 19], f"hatch-{i}", 0.18)
    elif scene == "text":
        primitives.append(
            {"id": "glyph", "type": "TEXT", "text": "H11", "point_mm": [8, 10]}
        )
    elif scene == "graphic":
        primitives.append(
            {"id": "graphic", "type": "GRAPHIC", "bbox_mm": [7, 7, 10, 10]}
        )
    else:
        for i in range(60):
            x, y = rng.uniform(3, 21, 2)
            line(
                [float(x), float(y), float(x + 0.1), float(y + 0.1)],
                f"artifact-{i}",
                0.13,
            )
    return {
        "scene": scene,
        "class": label,
        "units": "mm",
        "canvas_mm": [24, 24],
        "width_mm": width,
        "spacing_mm": spacing if two else None,
        "primitives": primitives,
        "role": "text"
        if scene == "text"
        else "other"
        if label == "OTHER"
        else "structural",
    }


def generate(out, variants=2, seed=314159):
    out = check_output(out)
    rows = []
    for scene_idx, scene in enumerate(SCENES):
        for width_idx, width in enumerate(WIDTHS):
            # CAD truth identity is split before creating degradation variants.
            design_seed = seed + scene_idx * 100 + width_idx
            cad = truth(scene, width, design_seed)
            truth_id = digest(cad)
            split = "validation" if width_idx in (1, 5) else "train"
            for variant in range(variants):
                rng = np.random.default_rng(design_seed * 100 + variant)
                dpi = int(rng.choice([72, 96, 110, 150, 240, 300, 600]))
                scale = dpi / 25.4
                size = int(np.ceil(24 * scale))
                ss = 4
                paper = int(rng.integers(205, 256))
                ink = int(rng.integers(0, 90))
                large = Image.new("L", (size * ss, size * ss), paper)
                draw = ImageDraw.Draw(large)
                for p in cad["primitives"]:
                    if p["type"] == "LINE":
                        draw.line(
                            [v * scale * ss for v in p["xy_mm"]],
                            fill=ink,
                            width=max(1, round(p["width_mm"] * scale * ss)),
                        )
                    elif p["type"] in ("SOLID", "GRAPHIC"):
                        x, y, w, h = [v * scale * ss for v in p["bbox_mm"]]
                        (draw.rectangle if p["type"] == "SOLID" else draw.ellipse)(
                            (x, y, x + w, y + h), fill=ink
                        )
                    elif p["type"] == "TEXT":
                        glyph = Image.new("L", (30, 14), paper)
                        ImageDraw.Draw(glyph).text((0, 0), p["text"], fill=ink)
                        glyph = glyph.resize((int(8 * scale * ss), int(4 * scale * ss)))
                        large.paste(
                            glyph, tuple(round(v * scale * ss) for v in p["point_mm"])
                        )
                aa = "LANCZOS" if variant % 2 else "BOX"
                gray = np.array(
                    large.resize((size, size), getattr(Image.Resampling, aa))
                )
                # Rotate/skew the source and all candidate coordinates by the SAME transform.
                rotation = float(rng.uniform(-25, 25))
                skew = float(rng.uniform(-0.025, 0.025))
                matrix = cv2.getRotationMatrix2D((size / 2, size / 2), rotation, 1.0)
                matrix[0, 1] += skew
                gray = cv2.warpAffine(gray, matrix, (size, size), borderValue=paper)
                sigma = float(rng.uniform(0, 1.25))
                if sigma > 0.05:
                    gray = cv2.GaussianBlur(gray, (0, 0), sigma)
                broken = float(rng.uniform(0, 0.008))
                gray[rng.random(gray.shape) < broken] = paper
                exposure = float(rng.uniform(0.70, 1.30))
                contrast = float(rng.uniform(0.70, 1.25))
                noise = float(rng.uniform(0, 6))
                gray = np.clip(
                    ((gray.astype(float) - 128) * contrast + 128) * exposure
                    + rng.normal(0, noise, gray.shape),
                    0,
                    255,
                ).astype(np.uint8)
                jpeg = int(rng.integers(35, 96))
                buffer = io.BytesIO()
                Image.fromarray(gray).save(buffer, format="JPEG", quality=jpeg)
                buffer.seek(0)
                gray = np.array(Image.open(buffer).convert("L"))
                geometry = []
                if cad["class"] == "SINGLE_PHYSICAL_STROKE":
                    # Nominate two boundaries of ONE physical stroke, not two truth entities.
                    for i, offset in enumerate((-width / 2, width / 2)):
                        geometry.append(
                            (
                                f"edge-of:rail-0:{i}",
                                [2, 12 + offset, 22, 12 + offset],
                                "SYNTHETIC_CANDIDATE",
                            )
                        )
                elif cad["class"] == "TRUE_PARALLEL_STRUCTURE":
                    for i, offset in enumerate(
                        (-cad["spacing_mm"] / 2, cad["spacing_mm"] / 2)
                    ):
                        geometry.append(
                            (
                                f"rail-{i}",
                                [2, 12 + offset, 22, 12 + offset],
                                "SYNTHETIC_CANDIDATE",
                            )
                        )
                transformed = []
                for gid, xy, origin in geometry:
                    coords = np.array(xy).reshape(2, 2) * scale
                    coords = np.c_[coords, np.ones(2)] @ matrix.T
                    transformed.append((gid, coords.ravel().tolist(), origin))
                measurements, decision, gate_decisions = measure(
                    gray, transformed, cad, scale, matrix, dpi
                )
                bbox = crop_box(gray, [size / 2, size / 2])
                channels = render_channels(gray, bbox, transformed)
                patch_sha = (
                    __import__("hashlib").sha256(channels[0].tobytes()).hexdigest()
                )
                metadata = {
                    "cad_truth": cad,
                    "dpi": dpi,
                    "rotation": rotation,
                    "skew": skew,
                    "blur_sigma_px": sigma,
                    "antialias": aa,
                    "jpeg_quality": jpeg,
                    "paper": paper,
                    "ink": ink,
                    "contrast": contrast,
                    "noise_sigma": noise,
                    "broken_ink_fraction": broken,
                    "exposure": exposure,
                    "affine_source_px_to_degraded_px": matrix.tolist(),
                    "mm_to_pixels_scale": scale,
                    "seed": design_seed * 100 + variant,
                }
                sid = "synthetic-" + digest(metadata)[:24]
                folder = out / "patches" / sid
                folder.mkdir(parents=True, exist_ok=True)
                for name, channel in zip(
                    ("gray", "edges", "centerline", "protection", "nodes"), channels
                ):
                    channel.save(folder / f"{name}.png")
                overlay = Image.merge("RGB", [channels[0]] * 3)
                overlay.paste((230, 40, 40), mask=channels[1])
                overlay.save(folder / "overlay.png")
                Image.fromarray(gray).save(folder / "context.png")
                atomic_json(folder / "truth.json", metadata)
                rows.append(
                    {
                        "sample_id": sid,
                        "source_drawing_id": truth_id,
                        "source_family_id": truth_id,
                        "source_page": 1,
                        "source_bbox": bbox,
                        "candidate_geometry_ids": [g[0] for g in transformed],
                        "candidate_geometry": transformed,
                        "source_dpi": dpi,
                        "current_p3a_measurement": measurements,
                        "current_deterministic_decision": decision,
                        "deterministic_provenance": "read-only P3A replay on full synthetic raster; CAD context protection; outputs discarded",
                        "offline_gate_decisions": gate_decisions,
                        "label": cad["class"],
                        "label_provenance": {
                            "kind": "generation_truth",
                            "truth_id": truth_id,
                        },
                        "split": split,
                        "source_sha256": sha(folder / "context.png"),
                        "source_path": str((folder / "context.png").relative_to(out)),
                        "patch_sha256": patch_sha,
                        "truth_id": truth_id,
                        "domain": "synthetic",
                        "content_role": cad["role"],
                        "patch_dir": str(folder.relative_to(out)),
                        "features": {
                            "distance_px": width * scale
                            if cad["class"] == "SINGLE_PHYSICAL_STROKE"
                            else (cad["spacing_mm"] or 0) * scale,
                            "angle_delta_deg": 0,
                            "overlap_px": 20 * scale,
                        },
                        "metadata": metadata,
                        "full_protection_available": False,
                        "protection_provenance": "NOT_RENDERED; masks cannot imply eligibility",
                    }
                )
    validate_samples(rows)
    write_rows(out / "samples.jsonl", rows)
    atomic_json(
        out / "summary.json",
        {
            "samples": len(rows),
            "version": digest(rows),
            "truth_designs": len(SCENES) * len(WIDTHS),
            "synthetic_blind_samples": 0,
            "AMBIGUOUS": "real human uncertainty only",
        },
    )
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--variants", type=int, default=2)
    ap.add_argument("--seed", type=int, default=314159)
    args = ap.parse_args()
    print("Generated", len(generate(args.out, args.variants, args.seed)))
