from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any

import cv2
import numpy as np


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE_FILES = (
    "app/optimized_trace.py",
    "app/scan_cleanup.py",
    "app/straight_line_reconstruction.py",
    "app/structural_roi.py",
    "app/connectivity_safety.py",
    "app/pipeline_service.py",
    "app/line_detect.py",
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_commit(project_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _prepare_inputs(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))
    from app.image_loader import load_image, save_image

    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Topology input directory is not empty: {output_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    unique_pages: set[tuple[str, int]] = set()
    for document in manifest["documents"]:
        page_key = (
            str(document["source_document"]),
            int(document["page"]["number"]),
        )
        if page_key in unique_pages:
            continue
        unique_pages.add(page_key)
        selected.append(document)
        if len(selected) == int(args.minimum_pages):
            break
    if len(selected) < int(args.minimum_pages):
        raise ValueError(
            f"Expected {args.minimum_pages} unique pages, found {len(selected)}"
        )

    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for document in selected:
        source_path = (SCRIPT_PROJECT_ROOT / document["source_path"]).resolve()
        page = document["page"]
        image = load_image(
            source_path,
            page_index=(
                int(page["number"]) - 1
                if source_path.suffix.lower() == ".pdf"
                else 0
            ),
            pdf_dpi=int(page["dpi"]),
        )
        target = pages_dir / f"{document['id']}.png"
        save_image(target, image)
        records.append(
            {
                "id": document["id"],
                "source_document": document["source_document"],
                "page": dict(page),
                "source_path": str(source_path),
                "source_sha256": _file_sha256(source_path),
                "raster_path": str(target.resolve()),
                "raster_sha256": _file_sha256(target),
                "shape": [int(value) for value in image.shape],
                "annotations": document["annotations"],
            }
        )
    payload = {
        "schema_version": 4,
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": _file_sha256(manifest_path),
        "unique_page_count": len(records),
        "documents": records,
    }
    target_manifest = output_dir / "input-manifest.json"
    _write_json(target_manifest, payload)
    print(target_manifest)
    return 0


def _component_count(mask: np.ndarray) -> int:
    count, _labels = cv2.connectedComponents(
        np.ascontiguousarray(mask, dtype=np.uint8),
        connectivity=8,
    )
    return max(0, int(count) - 1)


def _merged_source_components(
    source: np.ndarray,
    after: np.ndarray,
) -> int:
    source_count, source_labels = cv2.connectedComponents(
        np.ascontiguousarray(source, dtype=np.uint8),
        connectivity=8,
    )
    after_count, after_labels = cv2.connectedComponents(
        np.ascontiguousarray(after, dtype=np.uint8),
        connectivity=8,
    )
    if source_count <= 1 or after_count <= 1:
        return 0
    overlap_counts = _source_overlap_counts(
        source_labels,
        after_labels,
        source_count=source_count,
        after_count=after_count,
    )
    return int(np.maximum(overlap_counts - 1, 0).sum())


def _source_overlap_counts(
    source_labels: np.ndarray,
    after_labels: np.ndarray,
    *,
    source_count: int,
    after_count: int,
) -> np.ndarray:
    valid = (source_labels > 0) & (after_labels > 0)
    if not np.any(valid):
        return np.zeros(after_count, dtype=np.int64)
    encoded_pairs = (
        after_labels[valid].astype(np.int64) * int(source_count)
        + source_labels[valid].astype(np.int64)
    )
    unique_pairs = np.unique(encoded_pairs)
    after_values = unique_pairs // int(source_count)
    return np.bincount(after_values, minlength=after_count)


def _region_connection_changes(
    source: np.ndarray,
    after: np.ndarray,
    added: np.ndarray,
    regions: list[dict[str, Any]],
) -> tuple[int, int, list[dict[str, Any]]]:
    source_count, source_labels = cv2.connectedComponents(
        np.ascontiguousarray(source, dtype=np.uint8),
        connectivity=8,
    )
    after_count, after_labels = cv2.connectedComponents(
        np.ascontiguousarray(after, dtype=np.uint8),
        connectivity=8,
    )
    overlap_counts = _source_overlap_counts(
        source_labels,
        after_labels,
        source_count=source_count,
        after_count=after_count,
    )
    total = 0
    affected_regions = 0
    records: list[dict[str, Any]] = []
    height, width = added.shape
    for region in regions:
        x, y, box_width, box_height = (
            int(value) for value in region["bbox"]
        )
        if x + box_width > width or y + box_height > height:
            raise ValueError(
                f"{region['id']} lies outside comparison raster {width}x{height}"
            )
        added_crop = added[y : y + box_height, x : x + box_width]
        after_crop = after_labels[y : y + box_height, x : x + box_width]
        candidate_labels = np.unique(after_crop[added_crop > 0])
        connection_count = 0
        for label_value in candidate_labels:
            if int(label_value) <= 0:
                continue
            overlapping = int(overlap_counts[int(label_value)])
            connection_count += max(0, overlapping - 1)
        total += connection_count
        affected_regions += int(connection_count > 0)
        records.append(
            {
                "id": region["id"],
                "connection_count": connection_count,
            }
        )
    return total, affected_regions, records


def _line_mask(lines: object, shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for line in lines:
        cv2.line(
            mask,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            max(1, int(round(float(getattr(line, "width", 1.0))))),
            cv2.LINE_8,
        )
    return mask


def _region_added_pixels(
    added: np.ndarray,
    regions: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    total = 0
    records: list[dict[str, Any]] = []
    height, width = added.shape
    for region in regions:
        x, y, box_width, box_height = (
            int(value) for value in region["bbox"]
        )
        if x + box_width > width or y + box_height > height:
            raise ValueError(
                f"{region['id']} lies outside comparison raster {width}x{height}"
            )
        count = int(
            np.count_nonzero(
                added[y : y + box_height, x : x + box_width]
            )
        )
        total += count
        records.append({"id": region["id"], "added_pixels": count})
    return total, records


def _text_payload(texts: object) -> list[dict[str, Any]]:
    return [
        {
            "text": str(getattr(item, "text", "")),
            "bbox": [int(value) for value in getattr(item, "bbox", ())],
            "kind": str(getattr(item, "kind", "")),
            "approved": bool(getattr(item, "approved", False)),
            "replacement_safe": bool(
                getattr(item, "replacement_safe", False)
            ),
        }
        for item in texts
    ]


def _object_payload(result: object) -> dict[str, Any]:
    return {
        "texts": _text_payload(getattr(result, "texts", ())),
        "logos": [
            [int(value) for value in item.bbox]
            for item in getattr(result, "logos", ())
        ],
        "signatures": [
            [int(value) for value in item.bbox]
            for item in getattr(result, "signatures", ())
        ],
        "straight_lines": [
            [
                round(float(line.x1), 6),
                round(float(line.y1), 6),
                round(float(line.x2), 6),
                round(float(line.y2), 6),
            ]
            for line in getattr(result, "straight_lines", ())
        ],
        "contour_count": len(getattr(result, "paths", ())),
    }


def _measure_variant(args: argparse.Namespace) -> int:
    app_root = args.app_root.resolve()
    input_manifest_path = args.input_manifest.resolve()
    output_path = args.output.resolve()
    sys.path.insert(0, str(app_root))
    from app.optimized_trace import trace_image_optimized
    from app import straight_line_reconstruction

    if args.disable_roi_repair:
        def retain_without_roi_repair(lines, **_kwargs):
            return [line.copy() for line in lines]

        straight_line_reconstruction.extend_lines_to_first_intersection = (
            retain_without_roi_repair
        )

    manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    original_cwd = Path.cwd()
    os.chdir(app_root)
    try:
        for document in manifest["documents"]:
            raster_path = Path(document["raster_path"])
            image = cv2.imread(str(raster_path), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                raise ValueError(f"Could not load comparison page: {raster_path}")
            started = perf_counter()
            result = trace_image_optimized(image, enable_ocr=True)
            source_binary = getattr(result, "preview_binary", None)
            if source_binary is None:
                source_binary = result.binary
            prepared = np.where(source_binary < 128, 255, 0).astype(np.uint8)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _threshold, reference = cv2.threshold(
                gray,
                0,
                255,
                cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
            )
            if reference.shape != prepared.shape:
                reference = cv2.resize(
                    reference,
                    (prepared.shape[1], prepared.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
            lines = tuple(getattr(result, "straight_lines", ()))
            structural = _line_mask(lines, prepared.shape)
            prepared_added = np.where(
                (prepared > 0) & (reference == 0),
                255,
                0,
            ).astype(np.uint8)
            structural_added = np.where(
                (structural > 0) & (prepared == 0),
                255,
                0,
            ).astype(np.uint8)
            after = cv2.max(prepared, structural)
            added = np.where(
                (after > 0) & (reference == 0),
                255,
                0,
            ).astype(
                np.uint8,
            )
            annotations = document["annotations"]
            text_added, text_regions = _region_added_pixels(
                added,
                annotations["text_regions_to_preserve"],
            )
            structural_text_added, structural_text_regions = (
                _region_added_pixels(
                    structural_added,
                    annotations["text_regions_to_preserve"],
                )
            )
            forbidden_added, forbidden_regions = _region_added_pixels(
                added,
                annotations["forbidden_connection_regions"],
            )
            structural_forbidden_added, structural_forbidden_regions = (
                _region_added_pixels(
                    structural_added,
                    annotations["forbidden_connection_regions"],
                )
            )
            repair_added, repair_regions = _region_added_pixels(
                added,
                annotations["true_breaks_to_repair"],
            )
            structural_repair_added, structural_repair_regions = (
                _region_added_pixels(
                    structural_added,
                    annotations["true_breaks_to_repair"],
                )
            )
            (
                text_adhesion_count,
                text_adhesion_region_count,
                text_connection_regions,
            ) = _region_connection_changes(
                prepared,
                after,
                structural_added,
                annotations["text_regions_to_preserve"],
            )
            (
                incorrect_bridge_count,
                incorrect_bridge_region_count,
                forbidden_connection_regions,
            ) = _region_connection_changes(
                prepared,
                after,
                structural_added,
                annotations["forbidden_connection_regions"],
            )
            (
                correct_repair_count,
                correct_repair_region_count,
                repair_connection_regions,
            ) = _region_connection_changes(
                prepared,
                after,
                structural_added,
                annotations["true_breaks_to_repair"],
            )
            object_payload = _object_payload(result)
            structure = getattr(result, "final_structure", None)
            records.append(
                {
                    "id": document["id"],
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "source_component_count": _component_count(reference),
                    "final_component_count": _component_count(after),
                    "added_pixel_count": int(np.count_nonzero(added)),
                    "prepared_added_pixel_count": int(
                        np.count_nonzero(prepared_added)
                    ),
                    "structural_added_pixel_count": int(
                        np.count_nonzero(structural_added)
                    ),
                    "merged_source_component_count": _merged_source_components(
                        reference,
                        after,
                    ),
                    "structural_merged_component_count": (
                        _merged_source_components(prepared, after)
                    ),
                    "text_region_added_pixels": text_added,
                    "structural_text_region_added_pixels": (
                        structural_text_added
                    ),
                    "text_adhesion_count": text_adhesion_count,
                    "text_adhesion_region_count": (
                        text_adhesion_region_count
                    ),
                    "forbidden_region_added_pixels": forbidden_added,
                    "structural_forbidden_region_added_pixels": (
                        structural_forbidden_added
                    ),
                    "forbidden_region_with_added_pixels_count": sum(
                        item["added_pixels"] > 0 for item in forbidden_regions
                    ),
                    "forbidden_region_with_structural_pixels_count": sum(
                        item["added_pixels"] > 0
                        for item in structural_forbidden_regions
                    ),
                    "incorrect_bridge_count": incorrect_bridge_count,
                    "incorrect_bridge_region_count": (
                        incorrect_bridge_region_count
                    ),
                    "correct_repair_count": correct_repair_count,
                    "correct_repair_region_count": (
                        correct_repair_region_count
                    ),
                    "true_break_added_pixels": repair_added,
                    "structural_true_break_added_pixels": (
                        structural_repair_added
                    ),
                    "text_regions": text_regions,
                    "structural_text_regions": structural_text_regions,
                    "text_connection_regions": text_connection_regions,
                    "forbidden_regions": forbidden_regions,
                    "structural_forbidden_regions": (
                        structural_forbidden_regions
                    ),
                    "forbidden_connection_regions": (
                        forbidden_connection_regions
                    ),
                    "repair_regions": repair_regions,
                    "structural_repair_regions": structural_repair_regions,
                    "repair_connection_regions": repair_connection_regions,
                    "ocr_count": len(getattr(result, "texts", ())),
                    "ocr_sha256": _json_sha256(object_payload["texts"]),
                    "object_counts": {
                        "contours": len(getattr(result, "paths", ())),
                        "straight_lines": len(lines),
                        "texts": len(getattr(result, "texts", ())),
                        "logos": len(getattr(result, "logos", ())),
                        "signatures": len(
                            getattr(result, "signatures", ())
                        ),
                    },
                    "object_type_sha256": _json_sha256(object_payload),
                    "structure_id": (
                        None
                        if structure is None
                        else structure.structure_id
                    ),
                }
            )
    finally:
        os.chdir(original_cwd)

    payload = {
        "schema_version": 4,
        "variant": args.label,
        "git_commit": _git_commit(app_root),
        "core_source_sha256": {
            relative: (
                _file_sha256(app_root / relative)
                if (app_root / relative).is_file()
                else None
            )
            for relative in CORE_SOURCE_FILES
        },
        "app_root": str(app_root),
        "measurement_options": {
            "disable_roi_repair": bool(args.disable_roi_repair),
            "enable_ocr": True,
        },
        "input_manifest": str(input_manifest_path),
        "input_manifest_sha256": _file_sha256(input_manifest_path),
        "document_count": len(records),
        "documents": records,
    }
    _write_json(output_path, payload)
    print(output_path)
    return 0


def _variant_argument(value: str) -> tuple[str, Path]:
    label, separator, path = value.partition("=")
    if not separator or not label or not path:
        raise argparse.ArgumentTypeError("variant must use LABEL=PATH")
    return label, Path(path)


def _compare_variants(args: argparse.Namespace) -> int:
    variants = {
        label: json.loads(path.resolve().read_text(encoding="utf-8"))
        for label, path in args.variant
    }
    required = {
        "old_algorithm",
        "whole_page_disabled",
        "current_structural_roi",
    }
    missing = required - set(variants)
    if missing:
        raise ValueError(
            "Comparison variants missing " + ", ".join(sorted(missing))
        )
    ids = [
        item["id"] for item in variants["old_algorithm"]["documents"]
    ]
    by_variant = {
        label: {item["id"]: item for item in payload["documents"]}
        for label, payload in variants.items()
    }
    for label, records in by_variant.items():
        if set(records) != set(ids):
            raise ValueError(f"{label} measured a different page set")

    metrics = (
        "source_component_count",
        "final_component_count",
        "added_pixel_count",
        "prepared_added_pixel_count",
        "structural_added_pixel_count",
        "merged_source_component_count",
        "structural_merged_component_count",
        "text_region_added_pixels",
        "structural_text_region_added_pixels",
        "text_adhesion_count",
        "text_adhesion_region_count",
        "forbidden_region_added_pixels",
        "structural_forbidden_region_added_pixels",
        "forbidden_region_with_added_pixels_count",
        "forbidden_region_with_structural_pixels_count",
        "incorrect_bridge_count",
        "incorrect_bridge_region_count",
        "correct_repair_count",
        "correct_repair_region_count",
        "true_break_added_pixels",
        "structural_true_break_added_pixels",
    )
    aggregate: dict[str, dict[str, Any]] = {}
    for label, records in by_variant.items():
        aggregate[label] = {
            metric: sum(int(records[item_id][metric]) for item_id in ids)
            for metric in metrics
        }
        aggregate[label]["ocr_changed_pages_vs_old"] = sum(
            records[item_id]["ocr_sha256"]
            != by_variant["old_algorithm"][item_id]["ocr_sha256"]
            for item_id in ids
        )
        aggregate[label]["object_type_changed_pages_vs_old"] = sum(
            records[item_id]["object_type_sha256"]
            != by_variant["old_algorithm"][item_id][
                "object_type_sha256"
            ]
            for item_id in ids
        )

    documents: list[dict[str, Any]] = []
    for item_id in ids:
        values = {
            label: records[item_id]
            for label, records in by_variant.items()
        }
        documents.append({"id": item_id, "variants": values})

    disabled = aggregate["whole_page_disabled"]
    current = aggregate["current_structural_roi"]
    unsafe = aggregate.get("historical_d9")
    payload = {
        "schema_version": 4,
        "document_count": len(ids),
        "variants": {
            label: {
                "git_commit": variants[label]["git_commit"],
                "core_source_sha256": variants[label][
                    "core_source_sha256"
                ],
                "measurement_options": variants[label].get(
                    "measurement_options",
                    {
                        "disable_roi_repair": False,
                        "enable_ocr": True,
                    },
                ),
                "result_sha256": _file_sha256(path.resolve()),
            }
            for label, path in args.variant
        },
        "aggregate": aggregate,
        "acceptance": {
            "minimum_ten_pages": len(ids) >= 10,
            "disabled_and_current_roi_share_source": (
                variants["whole_page_disabled"]["core_source_sha256"]
                == variants["current_structural_roi"]["core_source_sha256"]
            ),
            "unsafe_reference_available": unsafe is not None,
            "text_region_additions_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["text_region_added_pixels"]
                < unsafe["text_region_added_pixels"]
            ),
            "forbidden_region_additions_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["forbidden_region_added_pixels"]
                < unsafe["forbidden_region_added_pixels"]
            ),
            "incorrect_bridge_regions_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["incorrect_bridge_region_count"]
                < unsafe["incorrect_bridge_region_count"]
            ),
            "incorrect_bridges_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["incorrect_bridge_count"]
                < unsafe["incorrect_bridge_count"]
            ),
            "text_adhesions_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["text_adhesion_count"]
                < unsafe["text_adhesion_count"]
            ),
            "merged_components_reduced_vs_unsafe": (
                None
                if unsafe is None
                else current["merged_source_component_count"]
                < unsafe["merged_source_component_count"]
            ),
            "correct_repairs_preserved_vs_unsafe": (
                None
                if unsafe is None
                else current["correct_repair_region_count"]
                >= unsafe["correct_repair_region_count"]
            ),
            "roi_does_not_increase_incorrect_bridges": (
                current["incorrect_bridge_count"]
                <= disabled["incorrect_bridge_count"]
            ),
            "roi_does_not_increase_text_adhesions": (
                current["text_adhesion_count"]
                <= disabled["text_adhesion_count"]
            ),
            "roi_preserves_correct_repair_regions": (
                current["correct_repair_region_count"]
                >= disabled["correct_repair_region_count"]
            ),
        },
        "documents": documents,
    }
    _write_json(args.output.resolve(), payload)
    print(args.output.resolve())
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, measure and compare whole-page topology variants."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--minimum-pages", type=int, default=10)
    prepare.set_defaults(handler=_prepare_inputs)

    measure = subparsers.add_parser("measure")
    measure.add_argument("--app-root", type=Path, required=True)
    measure.add_argument("--input-manifest", type=Path, required=True)
    measure.add_argument("--label", required=True)
    measure.add_argument("--output", type=Path, required=True)
    measure.add_argument("--disable-roi-repair", action="store_true")
    measure.set_defaults(handler=_measure_variant)

    compare = subparsers.add_parser("compare")
    compare.add_argument(
        "--variant",
        action="append",
        type=_variant_argument,
        required=True,
    )
    compare.add_argument("--output", type=Path, required=True)
    compare.set_defaults(handler=_compare_variants)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
