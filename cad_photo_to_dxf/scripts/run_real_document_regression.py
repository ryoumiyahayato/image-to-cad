from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import cv2
import ezdxf
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.optimized_trace import trace_image_optimized  # noqa: E402
from app.final_structure import FINAL_STRUCTURE_SCHEMA_VERSION  # noqa: E402
from app.image_loader import load_image  # noqa: E402
from app.preview_renderer import render_final_structure_preview  # noqa: E402
from app.trace_single_export import export_final_structure_dxf  # noqa: E402


EXPECTED_METRICS = {
    "structure_id",
    "source_size_px",
    "contour_count",
    "straight_line_count",
    "text_count",
    "logo_count",
    "signature_count",
    "foreground_pixels",
    "contour_vertex_count",
    "preview_sha256",
    "dxf_entity_count",
    "dxf_line_count",
    "dxf_text_count",
    "dxf_trace_path_count",
    "dxf_trace_vertex_count",
    "content_audit_sha256",
}
REQUIRED_PROVENANCE = {
    "source",
    "usage",
    "rights_basis",
    "review_status",
}
REQUIRED_USAGE_AUTHORIZATION = {
    "scope",
    "authorization_basis",
    "redistribution_allowed",
    "public_release_status",
}
REQUIRED_ANNOTATION_COLLECTIONS = {
    "text_regions_to_preserve",
    "true_breaks_to_repair",
    "forbidden_connection_regions",
    "logo_regions",
    "signature_regions",
    "key_rois",
}
AUDITED_REGION_COLLECTIONS = tuple(sorted(REQUIRED_ANNOTATION_COLLECTIONS))
OBJECT_MASK_TYPES = {
    "outline",
    "preserved_foreground",
    "structural_line",
    "text",
    "logo",
    "signature",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete trace, preview and DXF-export pipeline against "
            "the mandatory full-page real-document regression set."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/real_regression/manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/real-document-regression.json"),
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("output/real-document-regression"),
    )
    parser.add_argument(
        "--record-baseline-to",
        type=Path,
        help=(
            "Explicit local-only bootstrap mode: write observed metrics to a "
            "different manifest path. CI never uses this option."
        ),
    )
    return parser


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Regression manifest must contain a JSON object")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _content_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _require_nonempty_strings(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{label} must be a non-empty list of strings")
    return [item.strip() for item in value]


def _validate_region_definition(
    document_id: str,
    collection: str,
    region: object,
) -> None:
    if not isinstance(region, dict):
        raise ValueError(f"{document_id}: {collection} entries must be objects")
    region_id = str(region.get("id", "")).strip()
    bbox = region.get("bbox")
    expected_types = region.get("expected_object_types")
    review_note = str(region.get("review_note", "")).strip()
    if not region_id:
        raise ValueError(f"{document_id}: {collection} region id is required")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(not isinstance(value, int) for value in bbox)
        or bbox[0] < 0
        or bbox[1] < 0
        or bbox[2] <= 0
        or bbox[3] <= 0
    ):
        raise ValueError(
            f"{document_id}: {collection}/{region_id} bbox must be "
            "[x, y, width, height] with positive integer dimensions"
        )
    if not isinstance(expected_types, dict):
        raise ValueError(
            f"{document_id}: {collection}/{region_id} "
            "expected_object_types must be an object"
        )
    for object_type, minimum_pixels in expected_types.items():
        if object_type not in OBJECT_MASK_TYPES:
            raise ValueError(
                f"{document_id}: {collection}/{region_id} uses unknown "
                f"object type {object_type!r}"
            )
        if not isinstance(minimum_pixels, int) or minimum_pixels < 0:
            raise ValueError(
                f"{document_id}: {collection}/{region_id} object minima "
                "must be non-negative integers"
            )
    if not review_note:
        raise ValueError(
            f"{document_id}: {collection}/{region_id} review_note is required"
        )
    if collection == "true_breaks_to_repair":
        if region.get("desired_state") != "repaired":
            raise ValueError(
                f"{document_id}: {collection}/{region_id} must declare "
                "desired_state='repaired'"
            )
    if collection == "forbidden_connection_regions":
        maximum = region.get("maximum_added_foreground_pixels")
        if not isinstance(maximum, int) or maximum < 0:
            raise ValueError(
                f"{document_id}: {collection}/{region_id} requires a "
                "non-negative maximum_added_foreground_pixels"
            )


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    require_expected_metrics: bool = True,
) -> list[dict[str, Any]]:
    baseline_schema = int(manifest.get("final_structure_schema_version", 0))
    if baseline_schema != FINAL_STRUCTURE_SCHEMA_VERSION:
        raise ValueError(
            "Regression baseline schema does not match FinalStructure: "
            f"{baseline_schema} != {FINAL_STRUCTURE_SCHEMA_VERSION}"
        )
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Real-document regression set must not be empty")
    minimum_documents = int(manifest.get("minimum_documents", 10))
    if len(documents) < minimum_documents:
        raise ValueError(
            f"Expected at least {minimum_documents} real documents, "
            f"found {len(documents)}"
        )

    ids: set[str] = set()
    source_documents: set[str] = set()
    source_pages: set[tuple[str, int]] = set()
    covered_categories: set[str] = set()
    observed_dpis: set[int] = set()
    annotation_totals = {
        collection: 0 for collection in REQUIRED_ANNOTATION_COLLECTIONS
    }
    validated: list[dict[str, Any]] = []
    for index, raw_document in enumerate(documents):
        if not isinstance(raw_document, dict):
            raise ValueError(f"Document {index + 1} must be a JSON object")
        document_id = str(raw_document.get("id", "")).strip()
        source_document = str(raw_document.get("source_document", "")).strip()
        source_path = str(raw_document.get("source_path", "")).strip()
        expected_hash = str(raw_document.get("sha256", "")).strip().lower()
        original_path = str(raw_document.get("original_path", "")).strip()
        original_hash = str(
            raw_document.get("original_sha256", "")
        ).strip().lower()
        provenance = raw_document.get("provenance")
        authorization = raw_document.get("usage_authorization")
        page = raw_document.get("page")
        categories = raw_document.get("coverage_categories")
        annotations = raw_document.get("annotations")
        expected_object_types = raw_document.get("expected_object_types")
        acceptance_notes = raw_document.get("human_acceptance_notes")
        expected = raw_document.get("expected")
        if not document_id or document_id in ids:
            raise ValueError(f"Document {index + 1} has a missing or duplicate id")
        if not source_document:
            raise ValueError(f"{document_id}: source_document is required")
        if not source_path:
            raise ValueError(f"{document_id}: source_path is required")
        if not original_path:
            raise ValueError(f"{document_id}: original_path is required")
        if len(expected_hash) != 64:
            raise ValueError(f"{document_id}: sha256 must be a full digest")
        if len(original_hash) != 64:
            raise ValueError(
                f"{document_id}: original_sha256 must be a full digest"
            )
        if raw_document.get("full_page") is not True:
            raise ValueError(f"{document_id}: only complete pages are allowed")
        if raw_document.get("cropped") is not False:
            raise ValueError(f"{document_id}: cropped fixtures are forbidden")
        if raw_document.get("enable_ocr") is not True:
            raise ValueError(f"{document_id}: OCR must be enabled")
        if any(key in raw_document for key in ("skip", "skipped", "xfail")):
            raise ValueError(f"{document_id}: skip/xfail controls are forbidden")
        if (
            not isinstance(provenance, dict)
            or not REQUIRED_PROVENANCE.issubset(provenance)
            or any(not str(provenance[key]).strip() for key in REQUIRED_PROVENANCE)
        ):
            raise ValueError(f"{document_id}: provenance metadata is incomplete")
        if (
            not isinstance(authorization, dict)
            or not REQUIRED_USAGE_AUTHORIZATION.issubset(authorization)
            or any(
                authorization[key] in (None, "")
                for key in REQUIRED_USAGE_AUTHORIZATION
            )
            or not isinstance(authorization["redistribution_allowed"], bool)
        ):
            raise ValueError(
                f"{document_id}: usage authorization metadata is incomplete"
            )
        if not isinstance(page, dict):
            raise ValueError(f"{document_id}: page metadata is required")
        page_number = page.get("number")
        dpi = page.get("dpi")
        if not isinstance(page_number, int) or page_number <= 0:
            raise ValueError(f"{document_id}: page number must be positive")
        if not isinstance(dpi, int) or not 72 <= dpi <= 1200:
            raise ValueError(f"{document_id}: DPI must be between 72 and 1200")
        if page.get("orientation") not in {"portrait", "landscape"}:
            raise ValueError(
                f"{document_id}: page orientation must be explicit"
            )
        if page.get("source_kind") not in {
            "pdf_render",
            "raster_photo",
        }:
            raise ValueError(f"{document_id}: source_kind is invalid")
        document_categories = _require_nonempty_strings(
            categories,
            label=f"{document_id}: coverage_categories",
        )
        if not isinstance(annotations, dict):
            raise ValueError(f"{document_id}: annotations are required")
        missing_annotation_groups = (
            REQUIRED_ANNOTATION_COLLECTIONS - set(annotations)
        )
        if missing_annotation_groups:
            raise ValueError(
                f"{document_id}: annotations missing "
                f"{', '.join(sorted(missing_annotation_groups))}"
            )
        for collection in REQUIRED_ANNOTATION_COLLECTIONS:
            regions = annotations[collection]
            if not isinstance(regions, list):
                raise ValueError(
                    f"{document_id}: annotations/{collection} must be a list"
                )
            annotation_totals[collection] += len(regions)
            for region in regions:
                _validate_region_definition(document_id, collection, region)
        if (
            not isinstance(expected_object_types, dict)
            or not expected_object_types
        ):
            raise ValueError(
                f"{document_id}: expected_object_types must be non-empty"
            )
        for object_type, minimum_count in expected_object_types.items():
            if object_type not in OBJECT_MASK_TYPES - {"preserved_foreground"}:
                raise ValueError(
                    f"{document_id}: unknown expected object type {object_type!r}"
                )
            if not isinstance(minimum_count, int) or minimum_count < 0:
                raise ValueError(
                    f"{document_id}: expected object counts must be "
                    "non-negative integers"
                )
        _require_nonempty_strings(
            acceptance_notes,
            label=f"{document_id}: human_acceptance_notes",
        )
        if not isinstance(expected, dict):
            raise ValueError(f"{document_id}: expected metrics are required")
        missing_metrics = EXPECTED_METRICS - set(expected)
        if missing_metrics and require_expected_metrics:
            raise ValueError(
                f"{document_id}: expected metrics missing "
                f"{', '.join(sorted(missing_metrics))}"
            )
        ids.add(document_id)
        source_documents.add(source_document)
        source_pages.add((source_document, page_number))
        covered_categories.update(document_categories)
        observed_dpis.add(dpi)
        validated.append(raw_document)

    minimum_sources = int(manifest.get("minimum_source_documents", 3))
    if len(source_documents) < minimum_sources:
        raise ValueError(
            f"Expected at least {minimum_sources} independent source documents, "
            f"found {len(source_documents)}"
        )
    minimum_pages = int(manifest.get("minimum_unique_pages", 10))
    if len(source_pages) < minimum_pages:
        raise ValueError(
            f"Expected at least {minimum_pages} unique source pages, "
            f"found {len(source_pages)}"
        )
    required_categories = set(
        _require_nonempty_strings(
            manifest.get("required_categories"),
            label="required_categories",
        )
    )
    missing_categories = required_categories - covered_categories
    if missing_categories:
        raise ValueError(
            "Real-document regression coverage missing "
            + ", ".join(sorted(missing_categories))
        )
    required_dpis = manifest.get("required_dpis")
    if (
        not isinstance(required_dpis, list)
        or not required_dpis
        or any(not isinstance(value, int) for value in required_dpis)
    ):
        raise ValueError("required_dpis must be a non-empty integer list")
    missing_dpis = set(required_dpis) - observed_dpis
    if missing_dpis:
        raise ValueError(
            "Real-document regression DPI coverage missing "
            + ", ".join(str(value) for value in sorted(missing_dpis))
        )
    for collection in (
        "true_breaks_to_repair",
        "forbidden_connection_regions",
        "logo_regions",
        "signature_regions",
    ):
        if annotation_totals[collection] <= 0:
            raise ValueError(
                f"Regression set must contain at least one {collection} annotation"
            )
    return validated


def _resolve_source(source_path: str) -> Path:
    resolved = (PROJECT_ROOT / source_path).resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError("Regression source must remain inside the project")
    return resolved


def _load_document_image(
    document: dict[str, Any],
    source_path: Path,
) -> np.ndarray:
    page = document["page"]
    page_index = (
        int(page["number"]) - 1
        if source_path.suffix.lower() == ".pdf"
        else 0
    )
    return load_image(
        source_path,
        page_index=page_index,
        pdf_dpi=int(page["dpi"]),
    )


def _source_foreground(image: np.ndarray) -> np.ndarray:
    gray = (
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.ndim == 3
        else np.ascontiguousarray(image)
    )
    _threshold, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    return binary > 0


def _structure_object_masks(
    structure: Any,
    preview: np.ndarray,
) -> dict[str, np.ndarray]:
    height, width = structure.contour_binary.shape
    masks = {
        "outline": structure.contour_binary == 0,
        "preserved_foreground": preview < 128,
        "structural_line": np.zeros((height, width), dtype=np.uint8),
        "text": np.zeros((height, width), dtype=np.uint8),
        "logo": np.zeros((height, width), dtype=np.uint8),
        "signature": np.zeros((height, width), dtype=np.uint8),
    }
    for line in structure.straight_lines:
        cv2.line(
            masks["structural_line"],
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            max(1, int(round(line.width))),
            cv2.LINE_8,
        )
    for text in structure.texts:
        x, y, box_width, box_height = (int(value) for value in text.bbox)
        masks["text"][y : y + box_height, x : x + box_width] = 255
    for object_type, items in (
        ("logo", structure.logos),
        ("signature", structure.signatures),
    ):
        target = masks[object_type]
        for item in items:
            x, y, box_width, box_height = (int(value) for value in item.bbox)
            target[y : y + box_height, x : x + box_width] = cv2.max(
                target[y : y + box_height, x : x + box_width],
                np.where(item.mask > 0, 255, 0).astype(np.uint8),
            )
    return {
        key: value if value.dtype == np.bool_ else value > 0
        for key, value in masks.items()
    }


def _object_counts(structure: Any) -> dict[str, int]:
    return {
        "outline": len(structure.contours),
        "structural_line": len(structure.straight_lines),
        "text": len(structure.texts),
        "logo": len(structure.logos),
        "signature": len(structure.signatures),
    }


def _audit_content(
    document: dict[str, Any],
    *,
    source_image: np.ndarray,
    structure: Any,
    preview: np.ndarray,
) -> tuple[dict[str, Any], list[str]]:
    document_id = str(document["id"])
    height, width = preview.shape[:2]
    source_foreground = _source_foreground(source_image)
    masks = _structure_object_masks(structure, preview)
    errors: list[str] = []
    object_counts = _object_counts(structure)
    for object_type, minimum_count in document["expected_object_types"].items():
        observed = object_counts[object_type]
        if observed < minimum_count:
            errors.append(
                f"content audit object {object_type} count below minimum: "
                f"{observed} < {minimum_count}"
            )

    audited_regions: dict[str, list[dict[str, Any]]] = {}
    for collection in AUDITED_REGION_COLLECTIONS:
        results: list[dict[str, Any]] = []
        for region in document["annotations"][collection]:
            x, y, box_width, box_height = (
                int(value) for value in region["bbox"]
            )
            if x + box_width > width or y + box_height > height:
                errors.append(
                    f"{collection}/{region['id']} lies outside "
                    f"{width}x{height}"
                )
                continue
            slices = np.s_[y : y + box_height, x : x + box_width]
            source_roi = source_foreground[slices]
            final_roi = masks["preserved_foreground"][slices]
            type_pixels = {
                object_type: int(np.count_nonzero(mask[slices]))
                for object_type, mask in masks.items()
            }
            added_pixels = int(np.count_nonzero(final_roi & ~source_roi))
            missing_types: list[str] = []
            for object_type, minimum_pixels in region[
                "expected_object_types"
            ].items():
                if type_pixels[object_type] < minimum_pixels:
                    missing_types.append(object_type)
                    errors.append(
                        f"{collection}/{region['id']} {object_type} pixels "
                        f"below minimum: {type_pixels[object_type]} "
                        f"< {minimum_pixels}"
                    )
            maximum_added = region.get("maximum_added_foreground_pixels")
            if (
                isinstance(maximum_added, int)
                and added_pixels > maximum_added
            ):
                errors.append(
                    f"{collection}/{region['id']} added foreground exceeds "
                    f"limit: {added_pixels} > {maximum_added}"
                )
            results.append(
                {
                    "id": region["id"],
                    "bbox": [x, y, box_width, box_height],
                    "source_foreground_pixels": int(
                        np.count_nonzero(source_roi)
                    ),
                    "final_foreground_pixels": int(
                        np.count_nonzero(final_roi)
                    ),
                    "added_foreground_pixels": added_pixels,
                    "object_type_pixels": type_pixels,
                    "missing_expected_object_types": missing_types,
                }
            )
        audited_regions[collection] = results
    audit = {
        "object_counts": object_counts,
        "regions": audited_regions,
    }
    audit["sha256"] = _content_sha256(audit)
    if not audited_regions["text_regions_to_preserve"]:
        errors.append(f"{document_id}: no text preservation region was audited")
    if not audited_regions["key_rois"]:
        errors.append(f"{document_id}: no key ROI was audited")
    return audit, errors


def _measure_document(
    document: dict[str, Any],
    *,
    artifacts: Path,
    compare_expected: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    document_id = str(document["id"])
    source_path = _resolve_source(str(document["source_path"]))
    original_path = _resolve_source(str(document["original_path"]))
    errors: list[str] = []
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing regression page: {source_path}")
    observed_hash = _file_sha256(source_path)
    if observed_hash != str(document["sha256"]).lower():
        errors.append(
            f"source sha256 mismatch: expected {document['sha256']}, "
            f"observed {observed_hash}"
        )
    if not original_path.is_file():
        raise FileNotFoundError(f"Missing original fixture file: {original_path}")
    observed_original_hash = _file_sha256(original_path)
    if observed_original_hash != str(document["original_sha256"]).lower():
        errors.append(
            "original sha256 mismatch: "
            f"expected {document['original_sha256']}, "
            f"observed {observed_original_hash}"
        )

    image = _load_document_image(document, source_path)
    if image is None or image.size == 0:
        raise ValueError(f"Could not load {source_path}")
    started = perf_counter()
    trace_result = trace_image_optimized(
        image,
        enable_ocr=bool(document.get("enable_ocr", True)),
        source_dpi=float(document["page"]["dpi"]),
    )
    structure = trace_result.final_structure
    if structure is None:
        raise AssertionError("Trace pipeline did not produce FinalStructure")
    structure.assert_valid()

    preview = render_final_structure_preview(structure)
    if preview.shape != structure.contour_binary.shape:
        errors.append("preview shape differs from FinalStructure coordinates")

    artifacts.mkdir(parents=True, exist_ok=True)
    dxf_path = artifacts / f"{document_id}.dxf"
    export_result = export_final_structure_dxf(structure, dxf_path)
    if export_result.structure_id != structure.structure_id:
        errors.append("preview and DXF export did not consume the same structure")

    dxf_document = ezdxf.readfile(dxf_path)
    audit = dxf_document.audit()
    if audit.errors:
        errors.append(f"DXF audit reported {len(audit.errors)} errors")
    modelspace = dxf_document.modelspace()
    content_audit, content_errors = _audit_content(
        document,
        source_image=image,
        structure=structure,
        preview=preview,
    )
    errors.extend(content_errors)
    metrics: dict[str, Any] = {
        "structure_id": structure.structure_id,
        "source_size_px": list(structure.source_size_px),
        "contour_count": len(structure.contours),
        "straight_line_count": len(structure.straight_lines),
        "text_count": len(structure.texts),
        "logo_count": len(structure.logos),
        "signature_count": len(structure.signatures),
        "foreground_pixels": int(
            np.count_nonzero(structure.contour_binary == 0)
        ),
        "contour_vertex_count": sum(
            len(path.points) for path in structure.contours
        ),
        "preview_sha256": _array_sha256(preview),
        "dxf_entity_count": len(modelspace),
        "dxf_line_count": int(export_result.line_count),
        "dxf_text_count": int(export_result.text_count),
        "dxf_trace_path_count": int(export_result.trace_path_count),
        "dxf_trace_vertex_count": int(export_result.trace_vertex_count),
        "content_audit_sha256": content_audit["sha256"],
    }
    if compare_expected:
        expected = document["expected"]
        for key in sorted(EXPECTED_METRICS):
            if metrics[key] != expected[key]:
                errors.append(
                    f"{key} mismatch: expected {expected[key]!r}, "
                    f"observed {metrics[key]!r}"
                )
    result = {
        "id": document_id,
        "source_path": str(source_path.relative_to(PROJECT_ROOT).as_posix()),
        "source_sha256": observed_hash,
        "original_path": str(original_path.relative_to(PROJECT_ROOT).as_posix()),
        "original_sha256": observed_original_hash,
        "page": dict(document["page"]),
        "coverage_categories": list(document["coverage_categories"]),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "metrics": metrics,
        "content_audit": content_audit,
        "pipeline_stages": {
            "ocr": True,
            "structure_analysis": True,
            "preview": True,
            "dxf_export": True,
            "content_audit": True,
        },
        "dxf_path": str(dxf_path.resolve()),
        "errors": errors,
        "passed": not errors,
    }
    return result, errors


def main() -> int:
    args = _parser().parse_args()
    manifest_path = args.manifest.resolve()
    output_path = args.output.resolve()
    artifacts = args.artifacts.resolve()
    report: dict[str, Any] = {
        "manifest": str(manifest_path),
        "passed": False,
        "documents": [],
        "errors": [],
    }
    record_path = (
        None
        if args.record_baseline_to is None
        else args.record_baseline_to.resolve()
    )
    try:
        manifest = _load_manifest(manifest_path)
        if record_path == manifest_path:
            raise ValueError(
                "--record-baseline-to must not overwrite the input manifest"
            )
        documents = _validate_manifest(
            manifest,
            require_expected_metrics=record_path is None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"].append(str(exc))
        documents = []

    for document in documents:
        try:
            result, errors = _measure_document(
                document,
                artifacts=artifacts,
                compare_expected=record_path is None,
            )
            report["documents"].append(result)
            report["errors"].extend(
                f"{document['id']}: {message}" for message in errors
            )
        except Exception as exc:  # keep the full set observable after one failure
            message = f"{document['id']}: {type(exc).__name__}: {exc}"
            report["documents"].append(
                {
                    "id": document["id"],
                    "passed": False,
                    "errors": [message],
                }
            )
            report["errors"].append(message)

    report["document_count"] = len(report["documents"])
    report["unique_page_count"] = len(
        {
            (str(document["source_document"]), int(document["page"]["number"]))
            for document in documents
        }
    )
    report["coverage_categories"] = sorted(
        {
            category
            for document in documents
            for category in document["coverage_categories"]
        }
    )
    report["passed"] = (
        bool(documents)
        and len(report["documents"]) == len(documents)
        and not report["errors"]
    )
    if record_path is not None and report["passed"]:
        observed_by_id = {
            str(item["id"]): item["metrics"]
            for item in report["documents"]
        }
        recorded_manifest = json.loads(json.dumps(manifest))
        for document in recorded_manifest["documents"]:
            document["expected"] = observed_by_id[str(document["id"])]
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                recorded_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            + "\n",
            encoding="utf-8",
        )
        report["recorded_manifest"] = str(record_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
