from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any, Mapping

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_LOGO_TERMS = ("DESIGN", "GROUP", "设计", "集团")
OWNER_CODES = {
    "structural_line": 1,
    "text": 2,
    "logo": 3,
    "signature": 4,
    "graphic": 5,
    "residual": 6,
}
REQUIRED_LOGO_EVIDENCE = {
    "bbox",
    "closed_complexity",
    "contour_count",
    "density",
    "evidence_source",
    "hole_count",
    "mask_pixels",
    "reflection_similarity",
    "structural_score",
    "visual_kind",
}
REQUIRED_SIGNATURE_EVIDENCE = {
    "bidirectional_diagonal_support",
    "confidence",
    "continuity",
    "convex_solidity",
    "density",
    "directional_complexity",
    "evidence_source",
    "negative_diagonal_span",
    "perimeter_per_pixel",
    "positive_diagonal_span",
    "source_component_count",
    "source_pixel_count",
}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class _ObservationCollector:
    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        stage_key: str,
        *,
        image: np.ndarray | None = None,
        payload: Mapping[str, Any] | None = None,
        status: str = "captured",
    ) -> None:
        self.records.setdefault(stage_key, []).append(
            {
                "image": (
                    None
                    if image is None
                    else np.ascontiguousarray(image.copy())
                ),
                "payload": dict(payload or {}),
                "status": str(status),
            }
        )

    def with_role(
        self,
        stage_key: str,
        role: str,
    ) -> dict[str, Any] | None:
        for record in self.records.get(stage_key, ()):
            if record["payload"].get("role") == role:
                return record
        return None

    def with_payload_key(
        self,
        stage_key: str,
        key: str,
    ) -> dict[str, Any] | None:
        for record in self.records.get(stage_key, ()):
            if key in record["payload"]:
                return record
        return None


def _require_image(
    record: dict[str, Any] | None,
    *,
    label: str,
    shape: tuple[int, int] | None = None,
) -> np.ndarray:
    if record is None or record["image"] is None:
        raise ValueError(f"Missing observed image: {label}")
    image = np.ascontiguousarray(record["image"])
    if image.ndim != 2:
        raise ValueError(f"{label} must use page pixel coordinates")
    if shape is not None and image.shape != shape:
        raise ValueError(
            f"{label} shape {image.shape} does not match page {shape}"
        )
    return image


def _clipped_bbox(
    bbox: object,
    shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(value, bool) for value in bbox)
    ):
        raise ValueError(f"Invalid annotation bbox: {bbox!r}")
    x, y, width, height = (int(value) for value in bbox)
    left = max(0, x)
    top = max(0, y)
    right = min(shape[1], x + width)
    bottom = min(shape[0], y + height)
    if right <= left or bottom <= top:
        raise ValueError(f"Annotation bbox lies outside page: {bbox!r}")
    return left, top, right, bottom


def _annotation_mask(
    annotations: list[Mapping[str, Any]],
    shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for annotation in annotations:
        left, top, right, bottom = _clipped_bbox(
            annotation["bbox"],
            shape,
        )
        mask[top:bottom, left:right] = 255
    return mask


def _region_record(
    annotation: Mapping[str, Any],
    *,
    target: str,
    source: np.ndarray,
    lineage: np.ndarray,
) -> dict[str, object]:
    left, top, right, bottom = _clipped_bbox(
        annotation["bbox"],
        source.shape,
    )
    source_crop = source[top:bottom, left:right]
    lineage_crop = lineage[top:bottom, left:right]
    owner_pixels = {
        category: int(np.count_nonzero(lineage_crop == owner_code))
        for category, owner_code in OWNER_CODES.items()
    }
    matching = owner_pixels[target]
    fallback = (
        owner_pixels["graphic"]
        + owner_pixels["residual"]
    )
    other_preserved = (
        owner_pixels["structural_line"]
        + owner_pixels["text"]
    )
    source_pixels = int(cv2.countNonZero(source_crop))
    if matching > 0:
        predicted = target
    elif fallback > 0:
        predicted = "fallback_outline"
    elif other_preserved > 0:
        predicted = "other_preserved"
    else:
        predicted = "lost"
    return {
        "id": str(annotation["id"]),
        "target": target,
        "bbox": [left, top, right - left, bottom - top],
        "source_pixels": source_pixels,
        "owner_pixels": owner_pixels,
        "predicted": predicted,
        "matching_semantic_pixels": matching,
        "fallback_outline_pixels": fallback,
        "other_preserved_pixels": other_preserved,
        "review_note": str(annotation.get("review_note", "")),
    }


def _candidate_evidence_errors(
    payload: Mapping[str, Any],
    *,
    category: str,
    allowed_visual_kinds: set[str],
) -> list[str]:
    errors: list[str] = []
    regions = payload.get("regions")
    if not isinstance(regions, list):
        return [f"{category}: missing regions list"]
    for index, raw_region in enumerate(regions):
        if not isinstance(raw_region, Mapping):
            errors.append(f"{category}[{index}]: invalid evidence object")
            continue
        if category == "logo":
            missing = REQUIRED_LOGO_EVIDENCE - set(raw_region)
            if missing:
                errors.append(
                    f"logo[{index}]: missing {sorted(missing)}"
                )
            visual_kind = str(raw_region.get("visual_kind", ""))
            if visual_kind not in allowed_visual_kinds:
                errors.append(
                    f"logo[{index}]: unsupported visual_kind {visual_kind!r}"
                )
            if str(raw_region.get("evidence_source", "")) != (
                "source_geometry_only"
            ):
                errors.append(
                    f"logo[{index}]: non-visual evidence source"
                )
        else:
            evidence = raw_region.get("visual_evidence")
            if not isinstance(evidence, Mapping):
                errors.append(
                    f"signature[{index}]: missing visual evidence"
                )
                continue
            missing = REQUIRED_SIGNATURE_EVIDENCE - set(evidence)
            if missing:
                errors.append(
                    f"signature[{index}]: missing {sorted(missing)}"
                )
    return errors


def _document_record(
    document: Mapping[str, Any],
    *,
    enable_ocr: bool,
) -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.logo_detection import LOGO_VISUAL_KINDS
    from app.optimized_trace import trace_image_optimized

    raster_path = Path(str(document["raster_path"]))
    image = cv2.imread(str(raster_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Could not load validation page: {raster_path}")

    collector = _ObservationCollector()
    started = perf_counter()
    result = trace_image_optimized(
        image,
        enable_ocr=enable_ocr,
        source_dpi=float(document["page"]["dpi"]),
        observation_sink=collector,
    )
    elapsed_seconds = round(perf_counter() - started, 3)

    binary_record = collector.with_payload_key(
        "binary_foreground",
        "foreground_pixels",
    )
    binary = _require_image(binary_record, label="binary_foreground")
    source = np.where(binary < 128, 255, 0).astype(np.uint8)
    lineage = _require_image(
        collector.with_role("residual_mask", "pixel-lineage"),
        label="pixel-lineage",
        shape=source.shape,
    )
    logo_candidate_record = collector.with_role(
        "logo_candidate_mask",
        "candidate",
    )
    signature_candidate_record = collector.with_role(
        "signature_candidate_mask",
        "candidate",
    )
    logo_final_record = collector.with_role(
        "logo_candidate_mask",
        "final-owned",
    )
    signature_final_record = collector.with_role(
        "signature_candidate_mask",
        "final-owned",
    )
    logo_candidate = _require_image(
        logo_candidate_record,
        label="logo-candidate",
        shape=source.shape,
    )
    signature_candidate = _require_image(
        signature_candidate_record,
        label="signature-candidate",
        shape=source.shape,
    )
    logo_final = _require_image(
        logo_final_record,
        label="logo-final",
        shape=source.shape,
    )
    signature_final = _require_image(
        signature_final_record,
        label="signature-final",
        shape=source.shape,
    )

    annotations = dict(document["annotations"])
    logo_annotations = list(annotations["logo_regions"])
    signature_annotations = list(annotations["signature_regions"])
    text_annotations = list(annotations["text_regions_to_preserve"])
    annotated_logo = _annotation_mask(logo_annotations, source.shape)
    annotated_signature = _annotation_mask(
        signature_annotations,
        source.shape,
    )
    annotated_semantic = cv2.max(annotated_logo, annotated_signature)

    semantic_capture_in_normal_text = 0
    for annotation in text_annotations:
        left, top, right, bottom = _clipped_bbox(
            annotation["bbox"],
            source.shape,
        )
        semantic_crop = cv2.max(
            logo_final[top:bottom, left:right],
            signature_final[top:bottom, left:right],
        )
        allowed_crop = annotated_semantic[top:bottom, left:right]
        semantic_capture_in_normal_text += int(
            np.count_nonzero(
                (semantic_crop > 0) & (allowed_crop == 0)
            )
        )

    logo_regions = [
        _region_record(
            annotation,
            target="logo",
            source=source,
            lineage=lineage,
        )
        for annotation in logo_annotations
    ]
    signature_regions = [
        _region_record(
            annotation,
            target="signature",
            source=source,
            lineage=lineage,
        )
        for annotation in signature_annotations
    ]
    evidence_errors = (
        _candidate_evidence_errors(
            (
                {}
                if logo_candidate_record is None
                else logo_candidate_record["payload"]
            ),
            category="logo",
            allowed_visual_kinds=set(LOGO_VISUAL_KINDS),
        )
        + _candidate_evidence_errors(
            (
                {}
                if signature_candidate_record is None
                else signature_candidate_record["payload"]
            ),
            category="signature",
            allowed_visual_kinds=set(LOGO_VISUAL_KINDS),
        )
    )

    return {
        "id": str(document["id"]),
        "page": dict(document["page"]),
        "raster_path": str(raster_path.resolve()),
        "raster_sha256": _file_sha256(raster_path),
        "elapsed_seconds": elapsed_seconds,
        "structure_id": (
            None
            if result.final_structure is None
            else result.final_structure.structure_id
        ),
        "source_pixels": int(cv2.countNonZero(source)),
        "logo_candidate_count": int(
            0
            if logo_candidate_record is None
            else logo_candidate_record["payload"].get("count", 0)
        ),
        "signature_candidate_count": int(
            0
            if signature_candidate_record is None
            else signature_candidate_record["payload"].get("count", 0)
        ),
        "logo_candidate_pixels": int(cv2.countNonZero(logo_candidate)),
        "signature_candidate_pixels": int(
            cv2.countNonZero(signature_candidate)
        ),
        "logo_final_pixels": int(cv2.countNonZero(logo_final)),
        "signature_final_pixels": int(cv2.countNonZero(signature_final)),
        "logo_candidate_background_pixels": int(
            np.count_nonzero((logo_candidate > 0) & (source == 0))
        ),
        "signature_candidate_background_pixels": int(
            np.count_nonzero((signature_candidate > 0) & (source == 0))
        ),
        "logo_final_outside_candidate_pixels": int(
            np.count_nonzero((logo_final > 0) & (logo_candidate == 0))
        ),
        "signature_final_outside_candidate_pixels": int(
            np.count_nonzero(
                (signature_final > 0) & (signature_candidate == 0)
            )
        ),
        "logo_final_outside_annotation_pixels": int(
            np.count_nonzero((logo_final > 0) & (annotated_logo == 0))
        ),
        "signature_final_outside_annotation_pixels": int(
            np.count_nonzero(
                (signature_final > 0) & (annotated_signature == 0)
            )
        ),
        "semantic_capture_in_normal_text_pixels": (
            semantic_capture_in_normal_text
        ),
        "evidence_errors": evidence_errors,
        "logo_regions": logo_regions,
        "signature_regions": signature_regions,
    }


def _run(args: argparse.Namespace) -> int:
    manifest_path = args.input_manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [
        _document_record(document, enable_ocr=bool(args.enable_ocr))
        for document in manifest["documents"]
    ]

    all_regions = [
        region
        for document in documents
        for key in ("logo_regions", "signature_regions")
        for region in document[key]
    ]
    confusion: Counter[tuple[str, str]] = Counter(
        (str(region["target"]), str(region["predicted"]))
        for region in all_regions
    )
    totals: Counter[str] = Counter()
    for document in documents:
        for key, value in document.items():
            if key.endswith("_pixels") or key.endswith("_count"):
                totals[key] += int(value)

    production_sources = (
        PROJECT_ROOT / "app" / "logo_detection.py",
        PROJECT_ROOT / "app" / "signature_overlay.py",
    )
    semantic_term_hits = {
        term: [
            str(path.relative_to(PROJECT_ROOT))
            for path in production_sources
            if term in path.read_text(encoding="utf-8")
        ]
        for term in FORBIDDEN_LOGO_TERMS
    }
    semantic_term_hits = {
        term: paths for term, paths in semantic_term_hits.items() if paths
    }

    acceptance = {
        "minimum_ten_pages": len(documents) >= 10,
        "annotated_logo_regions_present": any(
            document["logo_regions"] for document in documents
        ),
        "annotated_signature_regions_present": any(
            document["signature_regions"] for document in documents
        ),
        "candidate_masks_claim_only_source_pixels": (
            totals["logo_candidate_background_pixels"] == 0
            and totals["signature_candidate_background_pixels"] == 0
        ),
        "final_masks_are_subsets_of_candidate_masks": (
            totals["logo_final_outside_candidate_pixels"] == 0
            and totals["signature_final_outside_candidate_pixels"] == 0
        ),
        "candidate_visual_evidence_complete": all(
            not document["evidence_errors"] for document in documents
        ),
        "semantic_predictions_stay_inside_annotated_regions": (
            totals["logo_final_outside_annotation_pixels"] == 0
            and totals["signature_final_outside_annotation_pixels"] == 0
        ),
        "neighboring_normal_text_not_semantically_captured": (
            totals["semantic_capture_in_normal_text_pixels"] == 0
        ),
        "annotated_source_ink_is_never_lost": all(
            int(region["source_pixels"]) > 0
            and str(region["predicted"]) != "lost"
            for region in all_regions
        ),
        "insufficient_evidence_falls_back_without_forced_classification": all(
            (
                int(region["matching_semantic_pixels"]) > 0
                or int(region["fallback_outline_pixels"]) > 0
                or int(region["other_preserved_pixels"]) > 0
            )
            for region in all_regions
        ),
        "logo_ocr_semantic_terms_absent_from_production_classifiers": (
            not semantic_term_hits
        ),
    }
    payload = {
        "schema_version": 1,
        "git_commit": _git_commit(),
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _file_sha256(manifest_path),
        "enable_ocr": bool(args.enable_ocr),
        "document_count": len(documents),
        "annotated_region_count": len(all_regions),
        "aggregate": {
            **dict(sorted(totals.items())),
            "confusion_matrix": {
                f"{target}->{predicted}": int(count)
                for (target, predicted), count in sorted(confusion.items())
            },
            "semantic_term_hits": semantic_term_hits,
            "document_elapsed_total_seconds": round(
                sum(float(document["elapsed_seconds"]) for document in documents),
                3,
            ),
        },
        "acceptance": acceptance,
        "documents": documents,
    }
    _write_json(args.output.resolve(), payload)
    print(args.output.resolve())
    if args.enforce and not all(acceptance.values()):
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit exact signature and Logo masks, independent visual "
            "evidence, nearby text preservation, and semantic fallbacks."
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(_run(_parser().parse_args()))
