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
CORE_SOURCE_FILES = (
    "app/content_ownership.py",
    "app/connectivity_safety.py",
    "app/observability.py",
    "app/optimized_trace.py",
    "app/straight_line_reconstruction.py",
    "app/structural_roi.py",
)
REQUIRED_PROTECTION_CATEGORIES = {
    "high_confidence_text",
    "logo",
    "signature",
    "engineering_symbol",
    "arrow",
    "dimension_number",
    "leader_annotation",
}
REQUIRED_ROI_FIELDS = {
    "confidence",
    "endpoint_corridors",
    "expansion_distance",
    "line_width_evidence",
    "orientation_evidence",
    "roi_id",
    "source_types",
}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


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

    def records_for(self, stage_key: str) -> list[dict[str, Any]]:
        return list(self.records.get(stage_key, ()))


def _record_with_payload_key(
    collector: _ObservationCollector,
    stage_key: str,
    key: str,
) -> dict[str, Any] | None:
    for record in collector.records_for(stage_key):
        if key in record["payload"]:
            return record
    return None


def _record_with_role(
    collector: _ObservationCollector,
    stage_key: str,
    role: str,
) -> dict[str, Any] | None:
    for record in collector.records_for(stage_key):
        if record["payload"].get("role") == role:
            return record
    return None


def _connection_mask(
    connection: Mapping[str, Any],
    shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    start = connection["start"]
    end = connection["end"]
    cv2.line(
        mask,
        (int(round(float(start[0]))), int(round(float(start[1])))),
        (int(round(float(end[0]))), int(round(float(end[1])))),
        255,
        max(1, int(connection.get("bridge_thickness", 1))),
        cv2.LINE_8,
    )
    return mask


def _point_in_bbox(
    point: list[float],
    bbox: list[int],
) -> bool:
    x, y, width, height = (int(value) for value in bbox)
    return bool(
        x <= float(point[0]) < x + width
        and y <= float(point[1]) < y + height
    )


def _document_record(
    document: Mapping[str, Any],
    *,
    enable_ocr: bool,
) -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.optimized_trace import trace_image_optimized

    raster_path = Path(str(document["raster_path"]))
    image = cv2.imread(str(raster_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Could not load ROI validation page: {raster_path}")
    collector = _ObservationCollector()
    started = perf_counter()
    result = trace_image_optimized(
        image,
        enable_ocr=enable_ocr,
        observation_sink=collector,
    )
    elapsed_seconds = round(perf_counter() - started, 3)

    roi_record = _record_with_payload_key(
        collector,
        "structural_roi",
        "rois",
    )
    rois = [] if roi_record is None else list(roi_record["payload"]["rois"])
    roi_mask = (
        None
        if roi_record is None
        else roi_record["image"]
    )
    protection_record = _record_with_role(
        collector,
        "conflict_mask",
        "connection-protection",
    )
    protection_mask = (
        None
        if protection_record is None
        else protection_record["image"]
    )
    roi_protection_records = {
        str(record["payload"].get("roi_id", "")): record
        for record in collector.records_for("conflict_mask")
        if record["payload"].get("role") == "connection-protection-roi"
    }
    protected_categories = set(
        ()
        if protection_record is None
        else protection_record["payload"].get(
            "protected_categories",
            (),
        )
    )
    endpoint_record = _record_with_payload_key(
        collector,
        "candidate_endpoints",
        "endpoints",
    )
    candidate_endpoints = (
        []
        if endpoint_record is None
        else list(endpoint_record["payload"]["endpoints"])
    )
    approved_record = _record_with_payload_key(
        collector,
        "approved_connections",
        "connections",
    )
    rejected_record = _record_with_payload_key(
        collector,
        "rejected_connections",
        "connections",
    )
    approved = (
        []
        if approved_record is None
        else list(approved_record["payload"]["connections"])
    )
    rejected = (
        []
        if rejected_record is None
        else list(rejected_record["payload"]["connections"])
    )
    rois_by_id = {str(roi["roi_id"]): roi for roi in rois}

    approved_outside_roi_mask = 0
    approved_outside_roi_bbox = 0
    approved_through_protection = 0
    approved_without_roi_protection = 0
    approved_records: list[dict[str, Any]] = []
    for connection in approved:
        bridge = _connection_mask(connection, image.shape[:2])
        outside_pixels = (
            int(cv2.countNonZero(bridge))
            if roi_mask is None
            else int(
                np.count_nonzero(
                    (bridge > 0) & (roi_mask == 0)
                )
            )
        )
        roi_id = str(connection.get("roi_id", ""))
        roi_protection = roi_protection_records.get(roi_id)
        if roi_protection is None or roi_protection["image"] is None:
            protected_pixels = -1
        else:
            origin = roi_protection["payload"].get("origin", (0, 0))
            left, top = (int(value) for value in origin)
            local_protection = roi_protection["image"]
            bottom = top + local_protection.shape[0]
            right = left + local_protection.shape[1]
            protected_pixels = int(
                np.count_nonzero(
                    (bridge[top:bottom, left:right] > 0)
                    & (local_protection > 0)
                )
            )
        roi = rois_by_id.get(str(connection.get("roi_id", "")))
        endpoints_inside_bbox = bool(
            roi is not None
            and _point_in_bbox(connection["start"], roi["bbox"])
            and _point_in_bbox(connection["end"], roi["bbox"])
        )
        approved_outside_roi_mask += int(outside_pixels > 0)
        approved_outside_roi_bbox += int(not endpoints_inside_bbox)
        approved_through_protection += int(protected_pixels > 0)
        approved_without_roi_protection += int(protected_pixels < 0)
        approved_records.append(
            {
                "attempt_id": int(connection.get("attempt_id", 0)),
                "roi_id": roi_id,
                "bridge_thickness": int(
                    connection.get("bridge_thickness", 1)
                ),
                "outside_roi_mask_pixels": outside_pixels,
                "protected_mask_pixels": protected_pixels,
                "endpoints_inside_roi_bbox": endpoints_inside_bbox,
            }
        )

    rejection_reasons = Counter(
        str(connection.get("reason_code", "unknown"))
        for connection in rejected
    )
    missing_roi_metadata = [
        {
            "roi_id": str(roi.get("roi_id", "")),
            "missing_fields": sorted(REQUIRED_ROI_FIELDS - set(roi)),
        }
        for roi in rois
        if REQUIRED_ROI_FIELDS - set(roi)
    ]
    source_types = Counter(
        str(source_type)
        for roi in rois
        for source_type in roi.get("source_types", ())
    )
    structure = result.final_structure
    return {
        "id": str(document["id"]),
        "page": dict(document["page"]),
        "raster_path": str(raster_path.resolve()),
        "raster_sha256": _file_sha256(raster_path),
        "elapsed_seconds": elapsed_seconds,
        "structure_id": (
            None if structure is None else structure.structure_id
        ),
        "preview_binary_sha256": _array_sha256(result.preview_binary),
        "roi_count": len(rois),
        "roi_mask_observed": roi_mask is not None,
        "roi_mask_pixels": (
            0 if roi_mask is None else int(cv2.countNonZero(roi_mask))
        ),
        "roi_purposes": dict(Counter(str(roi["purpose"]) for roi in rois)),
        "roi_source_types": dict(source_types),
        "roi_confidences": [
            float(roi.get("confidence", 0.0)) for roi in rois
        ],
        "missing_roi_metadata": missing_roi_metadata,
        "candidate_endpoint_count": len(candidate_endpoints),
        "roi_inside_endpoint_count": sum(
            len(roi.get("endpoint_corridors", ())) for roi in rois
        ),
        "approved_connection_count": len(approved),
        "approved_outside_roi_mask_count": approved_outside_roi_mask,
        "approved_outside_roi_bbox_count": approved_outside_roi_bbox,
        "approved_through_protection_count": approved_through_protection,
        "approved_without_roi_protection_count": (
            approved_without_roi_protection
        ),
        "approved_connections": approved_records,
        "rejected_connection_count": len(rejected),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "outside_roi_rejection_count": int(
            rejection_reasons["outside_structural_roi"]
        ),
        "protection_mask_observed": protection_mask is not None,
        "protection_mask_pixels": (
            0
            if protection_mask is None
            else int(cv2.countNonZero(protection_mask))
        ),
        "roi_protection_mask_count": len(roi_protection_records),
        "protected_categories": sorted(protected_categories),
        "missing_protected_categories": sorted(
            REQUIRED_PROTECTION_CATEGORIES - protected_categories
        ),
    }


def _run(args: argparse.Namespace) -> int:
    manifest_path = args.input_manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [
        _document_record(document, enable_ocr=bool(args.enable_ocr))
        for document in manifest["documents"]
    ]
    missing_metadata_count = sum(
        len(document["missing_roi_metadata"]) for document in documents
    )
    total_approved = sum(
        int(document["approved_connection_count"]) for document in documents
    )
    total_rejected = sum(
        int(document["rejected_connection_count"]) for document in documents
    )
    total_outside_rejections = sum(
        int(document["outside_roi_rejection_count"]) for document in documents
    )
    total_outside_mask = sum(
        int(document["approved_outside_roi_mask_count"])
        for document in documents
    )
    total_outside_bbox = sum(
        int(document["approved_outside_roi_bbox_count"])
        for document in documents
    )
    total_protected_crossings = sum(
        int(document["approved_through_protection_count"])
        for document in documents
    )
    total_missing_roi_protection = sum(
        int(document["approved_without_roi_protection_count"])
        for document in documents
    )
    all_protection_observed = all(
        bool(document["protection_mask_observed"]) for document in documents
    )
    all_protection_categories = all(
        not document["missing_protected_categories"]
        for document in documents
    )
    acceptance = {
        "minimum_ten_pages": len(documents) >= 10,
        "roi_mask_observed_on_every_page": all(
            bool(document["roi_mask_observed"]) for document in documents
        ),
        "roi_metadata_complete": missing_metadata_count == 0,
        "roi_inside_endpoints_observable": all(
            int(document["roi_count"]) == 0
            or int(document["roi_inside_endpoint_count"]) > 0
            for document in documents
        ),
        "outside_roi_rejections_observable": total_outside_rejections > 0,
        "all_approved_connections_inside_roi_mask": total_outside_mask == 0,
        "all_approved_connection_endpoints_inside_roi_bbox": (
            total_outside_bbox == 0
        ),
        "connection_protection_mask_observed_on_every_page": (
            all_protection_observed
        ),
        "required_protection_categories_declared": (
            all_protection_categories
        ),
        "no_approved_connection_crosses_protection_mask": (
            all_protection_observed
            and total_missing_roi_protection == 0
            and total_protected_crossings == 0
        ),
    }
    payload = {
        "schema_version": 1,
        "git_commit": _git_commit(),
        "core_source_sha256": {
            relative: _file_sha256(PROJECT_ROOT / relative)
            for relative in CORE_SOURCE_FILES
        },
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _file_sha256(manifest_path),
        "enable_ocr": bool(args.enable_ocr),
        "document_count": len(documents),
        "aggregate": {
            "roi_count": sum(
                int(document["roi_count"]) for document in documents
            ),
            "roi_mask_pixels": sum(
                int(document["roi_mask_pixels"]) for document in documents
            ),
            "candidate_endpoint_count": sum(
                int(document["candidate_endpoint_count"])
                for document in documents
            ),
            "roi_inside_endpoint_count": sum(
                int(document["roi_inside_endpoint_count"])
                for document in documents
            ),
            "approved_connection_count": total_approved,
            "approved_outside_roi_mask_count": total_outside_mask,
            "approved_outside_roi_bbox_count": total_outside_bbox,
            "approved_through_protection_count": (
                total_protected_crossings
            ),
            "approved_without_roi_protection_count": (
                total_missing_roi_protection
            ),
            "rejected_connection_count": total_rejected,
            "outside_roi_rejection_count": total_outside_rejections,
            "missing_roi_metadata_count": missing_metadata_count,
            "document_elapsed_total_seconds": round(
                sum(
                    float(document["elapsed_seconds"])
                    for document in documents
                ),
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
            "Validate StructuralRoi evidence, repair boundaries, endpoint "
            "observability, and connection protection on real pages."
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    return parser


def main() -> int:
    return _run(_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
