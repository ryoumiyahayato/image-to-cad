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
REQUIRED_CANDIDATE_CATEGORIES = {
    "graphic",
    "logo",
    "signature",
    "structural_line",
    "text",
}
REQUIRED_CONFLICT_FIELDS = {
    "arbitration_rule",
    "bbox",
    "candidate_categories",
    "candidate_confidences",
    "conflict_id",
    "conflict_reason",
    "downgrade_reason",
    "final_category",
    "overlap_pixels",
    "residual_pixels",
}
REQUIRED_DOWNGRADE_FIELDS = {
    "arbitration_rule",
    "candidate_category",
    "candidate_index",
    "conflict_reason",
    "downgrade_reason",
    "final_category",
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

    def records_for(self, stage_key: str) -> list[dict[str, Any]]:
        return list(self.records.get(stage_key, ()))


def _record_with_role(
    collector: _ObservationCollector,
    stage_key: str,
    role: str,
) -> dict[str, Any] | None:
    for record in collector.records_for(stage_key):
        if record["payload"].get("role") == role:
            return record
    return None


def _record_with_payload_key(
    collector: _ObservationCollector,
    stage_key: str,
    key: str,
) -> dict[str, Any] | None:
    for record in collector.records_for(stage_key):
        if key in record["payload"]:
            return record
    return None


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
        raise ValueError(f"Could not load ownership validation page: {raster_path}")

    collector = _ObservationCollector()
    started = perf_counter()
    result = trace_image_optimized(
        image,
        enable_ocr=enable_ocr,
        source_dpi=float(document["page"]["dpi"]),
        observation_sink=collector,
    )
    elapsed_seconds = round(perf_counter() - started, 3)

    binary_record = _record_with_payload_key(
        collector,
        "binary_foreground",
        "foreground_pixels",
    )
    source_pixels = (
        0
        if binary_record is None
        else int(binary_record["payload"]["foreground_pixels"])
    )
    arbitration_record = _record_with_role(
        collector,
        "conflict_mask",
        "ownership-arbitration",
    )
    arbitration = (
        {}
        if arbitration_record is None
        else dict(arbitration_record["payload"])
    )
    legacy_conflict_record = _record_with_payload_key(
        collector,
        "conflict_mask",
        "ambiguous_pixels",
    )
    conflict_pixels = int(
        arbitration.get(
            "conflict_pixels",
            (
                0
                if legacy_conflict_record is None
                else legacy_conflict_record["payload"].get(
                    "ambiguous_pixels",
                    0,
                )
            ),
        )
    )
    residual_record = _record_with_role(
        collector,
        "residual_mask",
        "residual",
    )
    residual_pixels = (
        0
        if residual_record is None
        else int(residual_record["payload"].get("residual_pixels", 0))
    )
    lineage_record = _record_with_role(
        collector,
        "residual_mask",
        "pixel-lineage",
    )
    lineage = (
        None if lineage_record is None else lineage_record["image"]
    )
    owned_pixels = (
        0 if lineage is None else int(np.count_nonzero(lineage > 0))
    )
    background_owned_pixels = (
        0
        if lineage is None or binary_record is None
        else int(
            np.count_nonzero(
                (lineage > 0) & (binary_record["image"] >= 128)
            )
        )
    )
    unowned_source_pixels = (
        source_pixels - owned_pixels
        if lineage is not None
        else source_pixels
    )

    candidates = list(arbitration.get("candidate_classes", ()))
    candidate_categories = {
        str(candidate.get("category", "")) for candidate in candidates
    }
    invalid_candidate_confidence_count = sum(
        int(
            not isinstance(candidate.get("confidence"), Mapping)
            or any(
                key not in candidate["confidence"]
                for key in ("maximum", "mean", "minimum")
            )
        )
        for candidate in candidates
    )
    conflicts = list(arbitration.get("conflicts", ()))
    incomplete_conflict_count = sum(
        int(
            not isinstance(conflict, Mapping)
            or bool(REQUIRED_CONFLICT_FIELDS - set(conflict))
        )
        for conflict in conflicts
    )
    conflict_residual_pixels = int(
        arbitration.get("unresolved_conflict_pixels", -1)
    )
    graphic_fallback_pixels = int(
        arbitration.get("graphic_fallback_pixels", -1)
    )
    final_owner_pixels = dict(arbitration.get("final_owner_pixels", {}))
    final_owner_total = sum(
        int(value) for value in final_owner_pixels.values()
    )
    downgrades = list(arbitration.get("downgrades", ()))
    incomplete_downgrade_count = sum(
        int(
            not isinstance(downgrade, Mapping)
            or bool(REQUIRED_DOWNGRADE_FIELDS - set(downgrade))
        )
        for downgrade in downgrades
    )
    downgrade_categories = Counter(
        str(downgrade.get("candidate_category", "unknown"))
        for downgrade in downgrades
        if isinstance(downgrade, Mapping)
    )
    conflict_final_categories = Counter(
        str(conflict.get("final_category", "unknown"))
        for conflict in conflicts
        if isinstance(conflict, Mapping)
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
        "source_pixels": source_pixels,
        "owned_pixels": owned_pixels,
        "background_owned_pixels": background_owned_pixels,
        "unowned_source_pixels": unowned_source_pixels,
        "lineage_observed": lineage is not None,
        "arbitration_observed": arbitration_record is not None,
        "candidate_categories": sorted(candidate_categories),
        "missing_candidate_categories": sorted(
            REQUIRED_CANDIDATE_CATEGORIES - candidate_categories
        ),
        "invalid_candidate_confidence_count": (
            invalid_candidate_confidence_count
        ),
        "conflict_pixels": conflict_pixels,
        "conflict_object_count": len(conflicts),
        "incomplete_conflict_count": incomplete_conflict_count,
        "downgrade_count": len(downgrades),
        "incomplete_downgrade_count": incomplete_downgrade_count,
        "downgrade_categories": dict(sorted(downgrade_categories.items())),
        "conflict_final_categories": dict(
            sorted(conflict_final_categories.items())
        ),
        "residual_pixels": residual_pixels,
        "unresolved_conflict_pixels": conflict_residual_pixels,
        "graphic_fallback_pixels": graphic_fallback_pixels,
        "final_owner_pixels": final_owner_pixels,
        "final_owner_total": final_owner_total,
        "conflicts": conflicts,
        "downgrades": downgrades,
    }


def _run(args: argparse.Namespace) -> int:
    manifest_path = args.input_manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [
        _document_record(
            document,
            enable_ocr=bool(args.enable_ocr),
        )
        for document in manifest["documents"]
    ]
    totals = Counter()
    aggregate_downgrade_categories: Counter[str] = Counter()
    aggregate_conflict_final_categories: Counter[str] = Counter()
    for document in documents:
        for key in (
            "background_owned_pixels",
            "conflict_object_count",
            "conflict_pixels",
            "downgrade_count",
            "graphic_fallback_pixels",
            "incomplete_conflict_count",
            "incomplete_downgrade_count",
            "invalid_candidate_confidence_count",
            "owned_pixels",
            "residual_pixels",
            "source_pixels",
            "unowned_source_pixels",
            "unresolved_conflict_pixels",
        ):
            value = int(document[key])
            if value >= 0:
                totals[key] += value
        aggregate_downgrade_categories.update(
            {
                str(category): int(count)
                for category, count in document[
                    "downgrade_categories"
                ].items()
            }
        )
        aggregate_conflict_final_categories.update(
            {
                str(category): int(count)
                for category, count in document[
                    "conflict_final_categories"
                ].items()
            }
        )

    acceptance = {
        "minimum_ten_pages": len(documents) >= 10,
        "pixel_lineage_observed_on_every_page": all(
            bool(document["lineage_observed"]) for document in documents
        ),
        "source_pixels_have_exactly_one_owner": all(
            int(document["unowned_source_pixels"]) == 0
            and int(document["background_owned_pixels"]) == 0
            for document in documents
        ),
        "unified_arbitration_observed_on_every_page": all(
            bool(document["arbitration_observed"]) for document in documents
        ),
        "candidate_categories_complete": all(
            not document["missing_candidate_categories"]
            for document in documents
        ),
        "candidate_confidences_complete": (
            totals["invalid_candidate_confidence_count"] == 0
        ),
        "conflict_explanations_complete": all(
            int(document["incomplete_conflict_count"]) == 0
            and (
                int(document["conflict_pixels"]) == 0
                or int(document["conflict_object_count"]) > 0
            )
            for document in documents
        ),
        "downgrade_explanations_complete": (
            totals["incomplete_downgrade_count"] == 0
        ),
        "residual_is_only_unresolved_conflict": all(
            int(document["unresolved_conflict_pixels"]) >= 0
            and int(document["residual_pixels"])
            == int(document["unresolved_conflict_pixels"])
            for document in documents
        ),
        "graphic_fallback_is_explicit": all(
            int(document["graphic_fallback_pixels"]) >= 0
            for document in documents
        ),
    }
    payload = {
        "schema_version": 1,
        "git_commit": _git_commit(),
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _file_sha256(manifest_path),
        "enable_ocr": bool(args.enable_ocr),
        "document_count": len(documents),
        "aggregate": {
            **dict(sorted(totals.items())),
            "downgrade_categories": dict(
                sorted(aggregate_downgrade_categories.items())
            ),
            "conflict_final_categories": dict(
                sorted(aggregate_conflict_final_categories.items())
            ),
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
            "Audit unified object ownership, conflict explanations, residual "
            "scope, and source-pixel lineage on real pages."
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(_run(_parser().parse_args()))
