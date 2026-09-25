"""Freeze the completed direct-continuation review and prepare the next batch.

This module is a validation/data-packaging workflow only.  It reads the
already-frozen fresh remining pool and the user's exported review JSON.  It
does not run Hough, span-integrity, admissibility, production, or model code.
Source-derived images are written only below ``local-artifacts``; tracked
output is metadata and human-review records.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

try:
    from . import fresh_dev_candidate_remining_v1 as fresh
except ImportError:  # pragma: no cover - direct script compatibility
    from app import fresh_dev_candidate_remining_v1 as fresh  # type: ignore


PROTOCOL = "DIRECT_CONTINUATION_REVIEW_V1"
BATCH_SIZE = 24
FRESH_POOL_COUNT = 147
BATCH01_COUNT = 24
REMAINING_POOL_COUNT = 123
FRESH_CANDIDATE_SET_ID = "FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504"
ACCUMULATION_TASK_ID = "DIRECT-CONTINUATION-REVIEW-ACCUMULATION-V1"
BATCH02_PACKAGE_ID = "direct-continuation-human-review-v1-batch-02"
FREEZE_CODE_CHECKPOINT = "88f44c161db11d9cb38c751374bbf5df0a13b074"

STAGE1_VALUES = tuple(fresh.STAGE1_VALUES)
STAGE2_VALUES = tuple(fresh.STAGE2_VALUES)
SELECTION_BASIS = tuple(key for key, _weight in fresh.SELECTION_FEATURE_WEIGHTS)


class AccumulationPaths:
    """Absolute paths for the tracked and ignored parts of this workflow."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.tracked_root = (
            self.repo_root
            / "cad_photo_to_dxf"
            / "validation"
            / "direct-continuation-human-review-v1"
        )
        self.runtime_root = (
            self.repo_root
            / "local-artifacts"
            / "draftsman"
            / "direct-continuation-human-review-v1"
        )
        self.batch01_tracked = self.tracked_root / "batch-01"
        self.batch02_tracked = self.tracked_root / "batch-02"
        self.accumulated_tracked = self.tracked_root / "accumulated"
        self.batch02_runtime = self.runtime_root / "batch-02"
        self.batch02_package = self.batch02_runtime / "review-package"


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _canonical_digest(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _rows_from_export(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("items"), list):
        rows = value["items"]
    elif isinstance(value, dict) and isinstance(value.get("records"), list):
        rows = value["records"]
    else:
        raise ValueError("review export must be a row array or an items/records object")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("review export contains a non-object record")
    return [dict(row) for row in rows]


def _label_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "DIRECT_STRAIGHT_CONTINUATION": 0,
        "NOT_DIRECT_STRAIGHT_CONTINUATION": 0,
        "INSUFFICIENT_EVIDENCE": 0,
        "OBJECT_GEOMETRY": 0,
        "ANNOTATION_LAYOUT": 0,
        "UNKNOWN_ROLE": 0,
    }
    for row in rows:
        stage1 = row.get("stage1")
        if stage1 in counts:
            counts[stage1] += 1
        stage2 = row.get("stage2")
        if stage1 == "DIRECT_STRAIGHT_CONTINUATION" and stage2 in counts:
            counts[stage2] += 1
    return counts


def validate_batch01_export(
    export_path: Path, selection_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the user's export without changing any human decision."""

    export_path = Path(export_path).resolve()
    rows = _rows_from_export(_read_json(export_path))
    expected_order = list(selection_manifest["review_order"])
    expected_set_id = str(selection_manifest["candidate_set_id"])
    expected_keys = {
        "protocol",
        "candidate_set_id",
        "candidate_id",
        "review_index",
        "stage1",
        "stage2",
        "optional_note",
    }
    errors: list[str] = []
    if len(rows) != len(expected_order):
        errors.append(f"record_count={len(rows)}")
    seen_ids: set[str] = set()
    seen_indices: set[int] = set()
    for expected_index, row in enumerate(rows, start=1):
        if set(row) != expected_keys:
            errors.append(f"record_keys_{expected_index}")
        if row.get("protocol") != PROTOCOL:
            errors.append(f"protocol_{expected_index}")
        if row.get("candidate_set_id") != expected_set_id:
            errors.append(f"candidate_set_{expected_index}")
        candidate_id = row.get("candidate_id")
        if candidate_id in seen_ids:
            errors.append(f"duplicate_candidate_{expected_index}")
        seen_ids.add(str(candidate_id))
        if candidate_id != expected_order[expected_index - 1]:
            errors.append(f"candidate_order_{expected_index}")
        review_index = row.get("review_index")
        if review_index in seen_indices:
            errors.append(f"duplicate_review_index_{expected_index}")
        seen_indices.add(review_index)
        if review_index != expected_index:
            errors.append(f"review_index_{expected_index}")
        stage1 = row.get("stage1")
        stage2 = row.get("stage2")
        if stage1 not in STAGE1_VALUES:
            errors.append(f"stage1_{expected_index}")
        if stage1 == "DIRECT_STRAIGHT_CONTINUATION":
            if stage2 not in STAGE2_VALUES:
                errors.append(f"stage2_missing_or_invalid_{expected_index}")
        elif stage2 is not None:
            errors.append(f"stage2_without_direct_{expected_index}")
    if seen_ids != set(expected_order):
        errors.append("candidate_id_set_mismatch")
    if errors:
        raise ValueError("invalid Batch-01 review export: " + "; ".join(errors))
    counts = _label_counts(rows)
    return {
        "rows": rows,
        "counts": counts,
        "review_completion_timestamp": None,
        "export_sha256": _sha256_file(export_path),
    }


def _source_mapping_payload(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "review_index": int(record["review_index"]),
            "candidate_id": record["candidate_id"],
            "selected_unit_id": record["selected_unit_id"],
            "source_family_id": record["source_family_id"],
            "source_document_id": record["source_document_id"],
            "source_type": record["source_type"],
            "source_render_path": record["source_render_path"],
            "page_or_view": record.get("page_or_view"),
        }
        for record in records
    ]


def _geometry_payload(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "review_index": int(record["review_index"]),
            "candidate_id": record["candidate_id"],
            "fragment_a_geometry": record["fragment_a_geometry"],
            "fragment_b_geometry": record["fragment_b_geometry"],
            "gap_endpoint_a": record["gap_endpoint_a"],
            "gap_endpoint_b": record["gap_endpoint_b"],
            "gap_length_px": record["gap_length_px"],
        }
        for record in records
    ]


def source_mapping_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return _canonical_digest(_source_mapping_payload(records))


def ab_geometry_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return _canonical_digest(_geometry_payload(records))


def _exact_geometry_key(candidate: Mapping[str, Any]) -> str:
    return _canonical_json(
        {
            "fragment_a_geometry": candidate["fragment_a_geometry"],
            "fragment_b_geometry": candidate["fragment_b_geometry"],
            "gap_endpoint_a": candidate["gap_endpoint_a"],
            "gap_endpoint_b": candidate["gap_endpoint_b"],
        }
    )


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "source_families": len({record["source_family_id"] for record in records}),
        "source_units": len({record["selected_unit_id"] for record in records}),
        "pdf_derived": sum(record.get("source_type") == "PDF" for record in records),
        "dwg_derived": sum(record.get("source_type") == "DWG" for record in records),
        "horizontal": sum(record.get("orientation") == "horizontal" for record in records),
        "vertical": sum(record.get("orientation") == "vertical" for record in records),
        "gap_bins": dict(sorted(Counter(str(record.get("gap_bin", "UNKNOWN")) for record in records).items())),
        "fragment_length_bins": dict(
            sorted(
                Counter(
                    "SHORT"
                    if max(
                        fresh._segment_length(record["fragment_a_geometry"]),
                        fresh._segment_length(record["fragment_b_geometry"]),
                    )
                    <= 80
                    else "LONG"
                    for record in records
                ).items()
            )
        ),
    }


def _selection_record(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return non-semantic selection metadata, excluding machine decisions."""

    return {
        **fresh._freeze_candidate_payload(candidate),
        "geometry_signature": candidate.get("geometry_signature"),
        "exact_geometry_digest": _sha256_bytes(_exact_geometry_key(candidate).encode("utf-8")),
        "gap_bin": candidate.get("gap_bin"),
        "selection_features": deepcopy(candidate.get("selection_features", {})),
        "local_density_fraction": candidate.get("local_density_fraction"),
    }


def _sanitize_selection_trace(selection_info: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "review_index": item["review_index"],
            "candidate_id": item["candidate_id"],
            "new_feature_values": item.get("new_feature_values", {}),
        }
        for item in selection_info.get("selection_trace", [])
    ]


def freeze_batch01(
    paths: AccumulationPaths,
    export_path: Path,
    *,
    freeze_code_checkpoint: str = FREEZE_CODE_CHECKPOINT,
) -> dict[str, Any]:
    """Create the tracked, human-observation Batch-01 freeze."""

    selection_path = (
        paths.repo_root
        / "cad_photo_to_dxf"
        / "validation"
        / "fresh-dev-candidate-remining-v1"
        / "fresh-selection-manifest.json"
    )
    package_manifest_path = (
        paths.repo_root
        / "local-artifacts"
        / "draftsman"
        / "fresh-dev-candidate-remining-v1"
        / "review-package"
        / "manifest.json"
    )
    selection = _read_json(selection_path)
    if selection.get("candidate_set_id") != FRESH_CANDIDATE_SET_ID:
        raise ValueError("fresh Batch-01 selection identity changed")
    if int(selection.get("candidate_count", 0)) != BATCH01_COUNT:
        raise ValueError("fresh Batch-01 selection count changed")
    export_info = validate_batch01_export(export_path, selection)
    selected = list(selection["candidates"])
    if len(selected) != BATCH01_COUNT:
        raise ValueError("Batch-01 candidate manifest is not 24 records")
    paths.batch01_tracked.mkdir(parents=True, exist_ok=True)
    record_path = paths.batch01_tracked / "batch-01-review-record.json"
    _write_json(record_path, export_info["rows"])
    record_digest = _sha256_file(record_path)
    mapping_digest = source_mapping_digest(selected)
    geometry_digest = ab_geometry_digest(selected)
    package_digest = _sha256_file(package_manifest_path)
    candidate_order = [record["candidate_id"] for record in selected]
    core = {
        "schema_version": 1,
        "task_id": ACCUMULATION_TASK_ID,
        "batch_id": "batch-01",
        "status": "HUMAN_REVIEW_FROZEN",
        "protocol": PROTOCOL,
        "candidate_set_id": selection["candidate_set_id"],
        "source_fresh_remine_checkpoint": selection["base_checkpoint"],
        "review_candidate_count": BATCH01_COUNT,
        "candidate_ids": candidate_order,
        "candidate_order": candidate_order,
        "candidate_set_digest": selection["selection_digest"],
        "review_export_digest": export_info["export_sha256"],
        "review_record_digest": record_digest,
        "source_mapping_digest": mapping_digest,
        "ab_geometry_digest": geometry_digest,
        "review_package_manifest_digest": package_digest,
        "review_completion_timestamp": export_info["review_completion_timestamp"],
        "freeze_code_checkpoint": freeze_code_checkpoint,
        "human_counts": export_info["counts"],
        "labels_modified": "NO",
        "source_export_filename": Path(export_path).name,
        "source_export_format": "flat-array",
    }
    manifest = {**core, "freeze_digest": _canonical_digest(core)}
    _write_json(paths.batch01_tracked / "batch-01-freeze-manifest.json", manifest)
    _write_json(
        paths.batch01_tracked / "batch-01-candidate-index.json",
        {
            "schema_version": 1,
            "batch_id": "batch-01",
            "protocol": PROTOCOL,
            "candidate_set_id": selection["candidate_set_id"],
            "candidate_count": BATCH01_COUNT,
            "review_order": candidate_order,
            "candidate_set_digest": selection["selection_digest"],
            "source_mapping_digest": mapping_digest,
            "ab_geometry_digest": geometry_digest,
            "records": [_selection_record(candidate) for candidate in selected],
        },
    )
    counts = export_info["counts"]
    final_md = f"""# Direct Continuation Review V1 — Batch 01 Final

Status: `HUMAN_REVIEW_FROZEN`

This file records human review observations from the completed
`DIRECT_CONTINUATION_REVIEW_V1` export. They are not perfect ground truth,
production truth, or engineering semantic truth. Human decisions and notes
are preserved in `batch-01-review-record.json` without relabeling.

## Frozen identity

- Candidate set: `{selection['candidate_set_id']}`
- Fresh remining checkpoint: `{selection['base_checkpoint']}`
- Review records: `{BATCH01_COUNT}`
- Candidate-set digest: `{selection['selection_digest']}`
- Original export SHA-256: `{export_info['export_sha256']}`
- Tracked review-record SHA-256: `{record_digest}`
- Source mapping digest: `{mapping_digest}`
- A/B geometry digest: `{geometry_digest}`
- Prior review-package manifest digest: `{package_digest}`
- Freeze code checkpoint: `{freeze_code_checkpoint}`
- Review completion timestamp in source export: not present

## Human counts

| Observation | Count |
| --- | ---: |
| `DIRECT_STRAIGHT_CONTINUATION` | {counts['DIRECT_STRAIGHT_CONTINUATION']} |
| `NOT_DIRECT_STRAIGHT_CONTINUATION` | {counts['NOT_DIRECT_STRAIGHT_CONTINUATION']} |
| `INSUFFICIENT_EVIDENCE` | {counts['INSUFFICIENT_EVIDENCE']} |
| `OBJECT_GEOMETRY` among DIRECT | {counts['OBJECT_GEOMETRY']} |
| `ANNOTATION_LAYOUT` among DIRECT | {counts['ANNOTATION_LAYOUT']} |
| `UNKNOWN_ROLE` among DIRECT | {counts['UNKNOWN_ROLE']} |

The role observations remain useful downstream but difficult borderline cases
are not silently corrected. The direct-continuation judgment is the primary
human signal.

## Downstream set semantics

DIRECT cases are eligible for the separate object-vs-annotation perception
dataset only through Stage 2. NOT_DIRECT cases remain hard-negative regression
examples and are not reinterpreted as annotation labels.

## Governance

- Production semantic delta: `NONE`
- New candidate mining: `NO`
- Model run or model-assisted labeling: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- Labels modified: `NO`
- Public redistribution: `NOT_AUTHORIZED`
"""
    (paths.batch01_tracked / "BATCH-01-FINAL.md").write_text(final_md, encoding="utf-8")
    return {
        "selection": selection,
        "export": export_info,
        "selected": selected,
        "manifest": manifest,
        "record_path": record_path,
    }


def resolve_funnel_bookkeeping(paths: AccumulationPaths) -> dict[str, Any]:
    """Resolve the pre-span raw-Hough accounting using existing telemetry."""

    tracked_funnel_path = (
        paths.repo_root
        / "cad_photo_to_dxf"
        / "validation"
        / "fresh-dev-candidate-remining-v1"
        / "fresh-mining-funnel.json"
    )
    runtime_path = (
        paths.repo_root
        / "local-artifacts"
        / "draftsman"
        / "fresh-dev-candidate-remining-v1"
        / "candidate-set-runtime.json"
    )
    funnel = _read_json(tracked_funnel_path)
    runtime = _read_json(runtime_path)
    raw = int(funnel["raw_hough_primitives"])
    orientation_eligible = int(funnel["orientation_eligible_raw_hough_primitives"])
    span_counts = {
        "supported": int(funnel["span_integrity_supported"]),
        "uncertain": int(funnel["span_integrity_uncertain"]),
        "rejected": int(funnel["span_integrity_rejected"]),
    }
    span_total = sum(span_counts.values())
    not_evaluated = raw - orientation_eligible
    unaccounted = raw - span_total - not_evaluated
    per_unit: list[dict[str, Any]] = []
    audit_paths = list(runtime.get("raw_primitive_audit_paths", []))
    for relative in audit_paths:
        audit_path = paths.repo_root / Path(*str(relative).split("/"))
        audit = _read_json(audit_path)
        raw_unit = int(audit["raw_hough_count"])
        eligible_unit = int(audit["orientation_eligible_count"])
        evaluated_records = len(audit.get("records", []))
        if evaluated_records != eligible_unit:
            raise ValueError(f"raw primitive audit is incomplete: {audit_path}")
        per_unit.append(
            {
                "selected_unit_id": audit["selected_unit_id"],
                "raw_hough_primitives": raw_unit,
                "orientation_eligible": eligible_unit,
                "not_span_evaluated": raw_unit - eligible_unit,
            }
        )
    if sum(item["raw_hough_primitives"] for item in per_unit) != raw:
        raise ValueError("raw primitive audit total does not match tracked funnel")
    if sum(item["orientation_eligible"] for item in per_unit) != orientation_eligible:
        raise ValueError("orientation-eligible audit total does not match tracked funnel")
    if sum(item["not_span_evaluated"] for item in per_unit) != not_evaluated:
        raise ValueError("not-span-evaluated audit total does not match tracked funnel")
    source_code_path = paths.repo_root / "cad_photo_to_dxf" / "app" / "line_provenance_audit_v1.py"
    return {
        "raw_hough_primitives_previous": raw,
        "raw_hough_span_status_total_previous": span_total,
        "raw_hough_not_span_evaluated": not_evaluated,
        "not_span_evaluated_reason_counts": {
            "orientation_filter_rejected_before_span_evaluation": not_evaluated
        },
        "raw_hough_funnel_unaccounted": unaccounted,
        "funnel_bookkeeping_status": "COMPLETE" if unaccounted == 0 else "PARTIAL",
        "orientation_filter_rule": (
            "canonical geometry is retained only when abs(dx) >= 3 * max(1, abs(dy)) "
            "or abs(dy) >= 3 * max(1, abs(dx))"
        ),
        "existing_telemetry_paths": audit_paths,
        "per_unit": sorted(per_unit, key=lambda item: item["selected_unit_id"]),
        "orientation_filter_source_sha256": _sha256_file(source_code_path),
        "hough_rerun": "NO",
    }


def _safe_replace_batch02_runtime(path: Path) -> None:
    path = Path(path).resolve()
    if (
        path.name != "batch-02"
        or path.parent.name != "direct-continuation-human-review-v1"
        or path.parent.parent.name != "draftsman"
        or path.parent.parent.parent.name != "local-artifacts"
    ):
        raise ValueError(f"refusing to replace unexpected runtime path: {path}")
    if path.exists():
        shutil.rmtree(path)


def _write_contact_sheet(selected: Sequence[Mapping[str, Any]], package_dir: Path) -> None:
    columns = 4
    card_width, card_height = 560, 310
    rows = max(1, (len(selected) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * card_width, rows * card_height), (232, 235, 239))
    for index, candidate in enumerate(selected):
        local_path = package_dir / "assets" / "local" / f"{candidate['candidate_id']}.png"
        context_path = package_dir / "assets" / "context" / f"{candidate['candidate_id']}.png"
        with Image.open(local_path) as local_image, Image.open(context_path) as context_image:
            images = [local_image.convert("RGB"), context_image.convert("RGB")]
        panel = Image.new("RGB", (card_width, card_height), "white")
        for column, image in enumerate(images):
            image.thumbnail((card_width // 2 - 12, card_height - 58), Image.Resampling.LANCZOS)
            panel.paste(
                image,
                (
                    column * (card_width // 2) + (card_width // 2 - image.width) // 2,
                    28,
                ),
            )
        draw = ImageDraw.Draw(panel)
        draw.text(
            (8, 7),
            f"{int(candidate['review_index']):02d}  {candidate['candidate_id']}",
            fill=(20, 25, 35),
        )
        draw.text((10, card_height - 24), "LOCAL", fill=(75, 85, 95))
        draw.text((card_width // 2 + 10, card_height - 24), "CONTEXT", fill=(75, 85, 95))
        sheet.paste(panel, ((index % columns) * card_width, (index // columns) * card_height))
    sheet.save(package_dir / "candidate-contact-sheet.png", format="PNG", optimize=True)


def validate_batch02_package(package_dir: Path, expected_order: Sequence[str]) -> dict[str, Any]:
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    if manifest.get("package_id") != BATCH02_PACKAGE_ID:
        raise ValueError("Batch-02 package identity mismatch")
    if manifest.get("review_protocol") != PROTOCOL:
        raise ValueError("Batch-02 package protocol mismatch")
    if manifest.get("candidate_count") != len(expected_order):
        raise ValueError("Batch-02 package candidate count mismatch")
    if manifest.get("review_order") != list(expected_order):
        raise ValueError("Batch-02 package order mismatch")
    if manifest.get("stage1_values") != list(STAGE1_VALUES):
        raise ValueError("Batch-02 Stage-1 vocabulary changed")
    if manifest.get("stage2_values") != list(STAGE2_VALUES):
        raise ValueError("Batch-02 Stage-2 vocabulary changed")
    forbidden = (
        "SPAN_INTEGRITY_",
        "DIRECT_CONTINUATION_ADMISSIBLE",
        "DIRECT_CONTINUATION_REJECTED",
        "DIRECT_CONTINUATION_UNCERTAIN",
        "machine_verdict",
        "human_stage1",
        "human_stage2",
        "model_score",
        "expected_answer",
        "semantic_class",
        "prediction",
    )
    if any(token in html for token in forbidden):
        raise ValueError("Batch-02 review HTML exposes a machine verdict")
    required = (
        "DIRECT_STRAIGHT_CONTINUATION",
        "NOT_DIRECT_STRAIGHT_CONTINUATION",
        "INSUFFICIENT_EVIDENCE",
        "OBJECT_GEOMETRY",
        "ANNOTATION_LAYOUT",
        "UNKNOWN_ROLE",
        "marker-toggle",
        "modal-marker-toggle",
        "zoom-fit",
        'stage1 === "DIRECT_STRAIGHT_CONTINUATION"',
        "protocol:REVIEW_PROTOCOL",
        "downloadJson",
        "validateImport",
    )
    if any(token not in html for token in required):
        raise ValueError("Batch-02 review HTML is missing a required neutral control")
    if "fetch(" in html or "XMLHttpRequest" in html or "<script src=" in html or "<link href=" in html:
        raise ValueError("Batch-02 review HTML has a network dependency")
    for item in manifest["items"]:
        if item["candidate_id"] not in expected_order:
            raise ValueError("unknown candidate in Batch-02 package")
        for key in ("local_image", "context_image"):
            image_path = package_dir / Path(*item[key].split("/"))
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            with Image.open(image_path) as image:
                if image.width <= 0 or image.height <= 0 or fresh._colored_pixel_fraction(image) > 0.01:
                    raise ValueError(f"unclean Batch-02 crop: {image_path}")
    return {
        "candidate_count": len(expected_order),
        "clean_local_count": len(expected_order),
        "clean_context_count": len(expected_order),
        "review_order": list(expected_order),
    }


def _build_batch02_package(
    paths: AccumulationPaths,
    selected: list[dict[str, Any]],
    *,
    candidate_set_id: str,
    selection_digest: str,
    batch01_freeze_digest: str,
    source_pool_runtime_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _safe_replace_batch02_runtime(paths.batch02_runtime)
    paths.batch02_package.mkdir(parents=True, exist_ok=True)
    package_items: list[dict[str, Any]] = []
    remine_paths = fresh.ReminePaths.for_repo(paths.repo_root)
    for candidate in selected:
        source_path = paths.repo_root / Path(*candidate["source_render_path"].split("/"))
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with Image.open(source_path) as image:
            image_size = image.size
        local_box, context_box = fresh.crop_boxes_for_candidate(candidate, image_size)
        candidate["local_crop_box_px"] = list(local_box)
        candidate["context_crop_box_px"] = list(context_box)
        local_path = paths.batch02_package / "assets" / "local" / f"{candidate['candidate_id']}.png"
        context_path = paths.batch02_package / "assets" / "context" / f"{candidate['candidate_id']}.png"
        local_size = fresh._write_clean_crop(source_path, local_box, local_path)
        context_size = fresh._write_clean_crop(source_path, context_box, context_path)
        candidate["markers"] = {
            "local": fresh._marker(candidate, local_box, local_size),
            "context": fresh._marker(candidate, context_box, context_size),
        }
        package_items.append(
            {
                "review_index": int(candidate["review_index"]),
                "candidate_id": candidate["candidate_id"],
                "local_image": f"assets/local/{candidate['candidate_id']}.png",
                "context_image": f"assets/context/{candidate['candidate_id']}.png",
                "marker": candidate["markers"],
            }
        )
    manifest = {
        "schema_version": 1,
        "package_id": BATCH02_PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(package_items),
        "stage1_values": list(STAGE1_VALUES),
        "stage2_values": list(STAGE2_VALUES),
        "review_order": [item["candidate_id"] for item in package_items],
        "source_manifest_identity": {
            "source_fresh_candidate_set_id": FRESH_CANDIDATE_SET_ID,
            "source_frozen_pool_count": FRESH_POOL_COUNT,
            "batch01_freeze_digest": batch01_freeze_digest,
            "batch02_selection_digest": selection_digest,
            "source_pool_runtime_sha256": source_pool_runtime_sha256,
        },
        "items": package_items,
        "governance": {
            "source_full_documents_included": False,
            "source_derived_images_local_only": True,
            "human_review_status": "PENDING",
            "export_reload_supported": True,
        },
    }
    _write_json(paths.batch02_package / "manifest.json", manifest)
    (paths.batch02_package / "review.html").write_text(
        fresh.render_review_html(manifest), encoding="utf-8"
    )
    (paths.batch02_package / "README.txt").write_text(
        "DIRECT_CONTINUATION_REVIEW_V1 — Batch 02\n\n"
        "这是一个离线、预测盲的 24 项两阶段人工作图审核包。\n"
        "第一步只判断：红色 Fragment A 到蓝色 Fragment B 之间，是否可以直接画一条直线。\n"
        "黄色区域只表示正在判断的 Gap，不是建议答案。只有第一步选择 DIRECT_STRAIGHT_CONTINUATION 时才出现第二步用途判断。\n"
        "看不清或无法确定用途时不要猜，分别使用 INSUFFICIENT_EVIDENCE 或 UNKNOWN_ROLE。\n\n"
        "审核结果可以导出并重新导入；本包开始时没有预填答案。\n"
        "PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED\n"
        "HUMAN_REVIEW: PENDING\n",
        encoding="utf-8",
    )
    _write_contact_sheet(selected, paths.batch02_package)
    validation = validate_batch02_package(
        paths.batch02_package, [item["candidate_id"] for item in package_items]
    )
    runtime_registry = {
        "schema_version": 1,
        "package_id": BATCH02_PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(package_items),
        "review_order": [item["candidate_id"] for item in package_items],
        "items": package_items,
        "governance": {
            "human_review_status": "PENDING",
            "machine_verdict_exposed_to_reviewer": False,
        },
    }
    _write_json(paths.batch02_runtime / "runtime-candidate-registry.json", runtime_registry)
    return manifest, validation


def prepare_batch02(paths: AccumulationPaths, batch01: Mapping[str, Any]) -> dict[str, Any]:
    """Select and package Batch-02 from the already-frozen 147 pool."""

    source_runtime_path = (
        paths.repo_root
        / "local-artifacts"
        / "draftsman"
        / "fresh-dev-candidate-remining-v1"
        / "candidate-set-runtime.json"
    )
    source_selection_path = (
        paths.repo_root
        / "cad_photo_to_dxf"
        / "validation"
        / "fresh-dev-candidate-remining-v1"
        / "fresh-selection-manifest.json"
    )
    source_runtime = _read_json(source_runtime_path)
    source_selection = _read_json(source_selection_path)
    pool = [dict(item) for item in source_runtime["deduplicated_admissible_pool"]]
    if len(pool) != FRESH_POOL_COUNT:
        raise ValueError(f"frozen fresh pool changed: {len(pool)} != {FRESH_POOL_COUNT}")
    pool_ids = [item["candidate_id"] for item in pool]
    if len(set(pool_ids)) != FRESH_POOL_COUNT:
        raise ValueError("frozen fresh pool contains duplicate candidate IDs")
    geometry_keys = [_exact_geometry_key(item) for item in pool]
    if len(set(geometry_keys)) != FRESH_POOL_COUNT:
        raise ValueError("frozen fresh pool contains exact geometry duplicates")
    batch01_manifest = dict(batch01["manifest"])
    batch01_ids = list(batch01_manifest["candidate_ids"])
    if len(batch01_ids) != BATCH01_COUNT or len(set(batch01_ids)) != BATCH01_COUNT:
        raise ValueError("Batch-01 freeze identity is not 24 unique candidates")
    if set(batch01_ids) - set(pool_ids):
        raise ValueError("Batch-01 contains an unknown frozen-pool candidate")
    remaining = [item for item in pool if item["candidate_id"] not in set(batch01_ids)]
    if len(remaining) != REMAINING_POOL_COUNT:
        raise ValueError(f"remaining frozen pool changed: {len(remaining)} != {REMAINING_POOL_COUNT}")
    target_count = min(BATCH_SIZE, len(remaining))
    selected, selection_info = fresh.select_diverse_candidates(remaining, max_count=target_count)
    remine_paths = fresh.ReminePaths.for_repo(paths.repo_root)
    fresh._prepare_crop_boxes(remine_paths, selected)
    selected_ids = [item["candidate_id"] for item in selected]
    if set(selected_ids) & set(batch01_ids):
        raise ValueError("Batch-02 reused a Batch-01 candidate")
    selected_geometry = {_exact_geometry_key(item) for item in selected}
    batch01_geometry = {
        _exact_geometry_key(item) for item in batch01["selection"]["candidates"]
    }
    geometry_reuse_count = len(selected_geometry & batch01_geometry)
    if geometry_reuse_count:
        raise ValueError("Batch-02 reused exact Batch-01 geometry")
    selection_digest = fresh.selection_digest(selected)
    replay_input = [deepcopy(item) for item in remaining]
    replayed, replay_info = fresh.select_diverse_candidates(replay_input, max_count=target_count)
    fresh._prepare_crop_boxes(remine_paths, replayed)
    replay_ids = [item["candidate_id"] for item in replayed]
    replay_digest = fresh.selection_digest(replayed)
    source_mapping_equal = source_mapping_digest(selected) == source_mapping_digest(replayed)
    replay_status = "PASS" if replay_ids == selected_ids and replay_digest == selection_digest and source_mapping_equal else "FAIL"
    if replay_status != "PASS":
        raise ValueError("Batch-02 deterministic replay failed")
    batch02_candidate_set_id = f"{FRESH_CANDIDATE_SET_ID}-BATCH-02"
    coverage = _coverage(selected)
    selection_replay = {
        "schema_version": 1,
        "task_id": ACCUMULATION_TASK_ID,
        "batch_id": "batch-02",
        "source_fresh_candidate_set_id": FRESH_CANDIDATE_SET_ID,
        "candidate_set_id": batch02_candidate_set_id,
        "frozen_pool_count": FRESH_POOL_COUNT,
        "excluded_batch01_count": BATCH01_COUNT,
        "remaining_pool_count": len(remaining),
        "target_count": BATCH_SIZE,
        "selected_count": len(selected),
        "expected_review_order": selected_ids,
        "replayed_review_order": replay_ids,
        "selection_digest": selection_digest,
        "replayed_selection_digest": replay_digest,
        "source_mapping_equal": source_mapping_equal,
        "selection_deterministic_replay": replay_status,
        "selection_basis": list(SELECTION_BASIS),
        "selection_trace": _sanitize_selection_trace(selection_info),
        "replay_trace": _sanitize_selection_trace(replay_info),
        "human_labels_used_for_selection": False,
        "audit_root_cause_labels_used_for_selection": False,
        "model_scores_used_for_selection": False,
        "ocr_content_used_for_selection": False,
        "machine_semantic_prediction_used_for_selection": False,
        "semantic_target_balancing_used": False,
        "batch01_candidate_reuse_count": 0,
        "batch01_geometry_reuse_count": geometry_reuse_count,
        "pool_insufficient": len(remaining) < BATCH_SIZE,
    }
    source_pool_digest = _sha256_file(source_runtime_path)
    package_manifest, package_validation = _build_batch02_package(
        paths,
        selected,
        candidate_set_id=batch02_candidate_set_id,
        selection_digest=selection_digest,
        batch01_freeze_digest=batch01_manifest["freeze_digest"],
        source_pool_runtime_sha256=source_pool_digest,
    )
    _write_json(paths.batch02_runtime / "selection-replay.json", selection_replay)
    tracked_records = [_selection_record(candidate) for candidate in selected]
    paths.batch02_tracked.mkdir(parents=True, exist_ok=True)
    _write_json(paths.batch02_tracked / "batch-02-selection-replay.json", selection_replay)
    _write_json(
        paths.batch02_tracked / "batch-02-candidate-registry.json",
        {
            "schema_version": 1,
            "task_id": ACCUMULATION_TASK_ID,
            "batch_id": "batch-02",
            "protocol": PROTOCOL,
            "candidate_set_id": batch02_candidate_set_id,
            "source_fresh_candidate_set_id": FRESH_CANDIDATE_SET_ID,
            "source_pool_runtime_sha256": source_pool_digest,
            "candidate_count": len(selected),
            "review_order": selected_ids,
            "records": tracked_records,
            "counts": {
                "frozen_candidates": len(selected),
                "human_stage1_answers": 0,
                "human_stage2_answers": 0,
            },
            "governance": {
                "human_review_status": "PENDING",
                "machine_verdict_exposed_to_reviewer": False,
                "model_run": "NO",
                "validation": "NO",
                "locked_blind": "0 / 8",
                "h1_h2_opened": "NO",
            },
        },
    )
    _write_json(
        paths.batch02_tracked / "batch-02-selection-manifest.json",
        {
            "schema_version": 1,
            "task_id": ACCUMULATION_TASK_ID,
            "batch_id": "batch-02",
            "protocol": PROTOCOL,
            "candidate_set_id": batch02_candidate_set_id,
            "source_fresh_candidate_set_id": FRESH_CANDIDATE_SET_ID,
            "source_fresh_remine_checkpoint": source_selection["base_checkpoint"],
            "source_frozen_pool_count": FRESH_POOL_COUNT,
            "excluded_batch01_count": BATCH01_COUNT,
            "remaining_unreviewed_count": len(remaining),
            "candidate_count": len(selected),
            "review_order": selected_ids,
            "selection_digest": selection_digest,
            "source_mapping_digest": source_mapping_digest(selected),
            "ab_geometry_digest": ab_geometry_digest(selected),
            "selection_code_version": fresh.SELECTION_CODE_VERSION,
            "selection_basis": list(SELECTION_BASIS),
            "selection_trace": _sanitize_selection_trace(selection_info),
            "selection_deterministic_replay": replay_status,
            "human_labels_used_for_selection": False,
            "model_predictions_used_for_selection": False,
            "semantic_target_balancing_used": False,
            "batch01_candidate_reuse_count": 0,
            "batch01_geometry_reuse_count": geometry_reuse_count,
            "pool_insufficient": len(remaining) < BATCH_SIZE,
            "coverage": coverage,
            "records": tracked_records,
        },
    )
    package_manifest_digest = _sha256_file(paths.batch02_package / "manifest.json")
    _write_json(
        paths.batch02_tracked / "batch-02-review-package-manifest.json",
        {
            "schema_version": 1,
            "task_id": ACCUMULATION_TASK_ID,
            "batch_id": "batch-02",
            "package_id": BATCH02_PACKAGE_ID,
            "review_protocol": PROTOCOL,
            "candidate_set_id": batch02_candidate_set_id,
            "candidate_count": len(selected),
            "review_order": selected_ids,
            "runtime_package_path": str(paths.batch02_package.relative_to(paths.repo_root)).replace("\\", "/"),
            "runtime_package_manifest_sha256": package_manifest_digest,
            "runtime_package_validation": package_validation,
            "machine_verdict_exposed_to_reviewer": False,
            "human_review": "PENDING",
        },
    )
    batch02_md = f"""# Direct Continuation Review V1 — Batch 02 Preparation

Status: `HUMAN_REVIEW: PENDING`

Batch 02 is a fresh, neutral review package selected from the already-frozen
fresh admissible pool. It contains no pre-filled human answers and exposes no
span-integrity result, admissibility reason, model prediction, OCR content, or
old audit label to the reviewer.

## Selection integrity

- Protocol: `{PROTOCOL}`
- Source fresh candidate set: `{FRESH_CANDIDATE_SET_ID}`
- Frozen source pool: `{FRESH_POOL_COUNT}`
- Batch 01 excluded: `{BATCH01_COUNT}`
- Remaining before Batch 02: `{len(remaining)}`
- Selected: `{len(selected)} / {BATCH_SIZE}`
- Pool insufficient: `{'YES' if len(remaining) < BATCH_SIZE else 'NO'}`
- Selection digest: `{selection_digest}`
- Selection replay: `{replay_status}`
- Source mapping digest: `{source_mapping_digest(selected)}`
- A/B geometry digest: `{ab_geometry_digest(selected)}`
- Batch 01 candidate reuse: `0`
- Batch 01 exact geometry reuse: `{geometry_reuse_count}`

Selection uses only deterministic, non-semantic source and geometry diversity
features: source family/unit/document, source type, orientation, gap bucket,
local density bucket, and source-quality metadata already present in the frozen
pool. Human labels, audit labels, OCR, model scores, semantic predictions, and
class-target balancing are not used.

## Coverage

- Source families: `{coverage['source_families']}`
- Source units: `{coverage['source_units']}`
- PDF-derived: `{coverage['pdf_derived']}`
- DWG-derived: `{coverage['dwg_derived']}`
- Horizontal: `{coverage['horizontal']}`
- Vertical: `{coverage['vertical']}`
- Gap bins: `{json.dumps(coverage['gap_bins'], sort_keys=True)}`

The reviewer-facing question remains unchanged: “红色 Fragment A 到蓝色
Fragment B 之间，是否可以直接画一条直线？” The yellow region marks the gap
being judged and is not a suggested answer. Stage 2 appears only after
`DIRECT_STRAIGHT_CONTINUATION`; unclear role uses `UNKNOWN_ROLE`.

## Governance

- Production semantic delta: `NONE`
- New candidate mining: `NO`
- Span guard changed: `NO`
- Admissibility guard changed: `NO`
- Model run: `NO`
- Model-assisted labeling: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- Batch 03: not created
"""
    (paths.batch02_tracked / "BATCH-02-PREP.md").write_text(batch02_md, encoding="utf-8")
    return {
        "selected": selected,
        "remaining": remaining,
        "selection_manifest": _read_json(paths.batch02_tracked / "batch-02-selection-manifest.json"),
        "selection_replay": selection_replay,
        "package_manifest": package_manifest,
        "package_validation": package_validation,
        "coverage": coverage,
    }


def write_accumulated_summary(
    paths: AccumulationPaths,
    batch01: Mapping[str, Any],
    batch02: Mapping[str, Any],
    bookkeeping: Mapping[str, Any],
) -> dict[str, Any]:
    counts = batch01["export"]["counts"]
    summary = {
        "schema_version": 1,
        "task_id": ACCUMULATION_TASK_ID,
        "protocol": PROTOCOL,
        "status": "HUMAN_REVIEW_FROZEN_BATCH01_BATCH02_PENDING",
        "completed_batches": ["batch-01"],
        "batch02_human_review": "PENDING",
        "total_reviewed": BATCH01_COUNT,
        "direct_straight_continuation": counts["DIRECT_STRAIGHT_CONTINUATION"],
        "not_direct_straight_continuation": counts["NOT_DIRECT_STRAIGHT_CONTINUATION"],
        "insufficient_evidence": counts["INSUFFICIENT_EVIDENCE"],
        "object_geometry": counts["OBJECT_GEOMETRY"],
        "annotation_layout": counts["ANNOTATION_LAYOUT"],
        "unknown_role": counts["UNKNOWN_ROLE"],
        "class_floor_plan": {
            "object_geometry_target_floor": 35,
            "annotation_layout_target_floor": 35,
            "object_geometry_remaining_to_floor": 27,
            "annotation_layout_remaining_to_floor": 29,
            "planning_only": True,
            "statistical_guarantee": False,
        },
        "future_stopping_rule": (
            "Continue 24-case batches until OBJECT_GEOMETRY >= 35 and "
            "ANNOTATION_LAYOUT >= 35 using completed human-reviewed DIRECT cases."
        ),
        "fresh_frozen_pool": FRESH_POOL_COUNT,
        "remaining_before_batch02": REMAINING_POOL_COUNT,
        "batch02_selected": len(batch02["selected"]),
        "batch02_pool_insufficient": len(batch02["remaining"]) < BATCH_SIZE,
        "funnel_bookkeeping": dict(bookkeeping),
        "model_bake_off_should_resume": "NO",
        "production_semantic_delta": "NONE",
        "validation": "NO",
        "locked_blind": "0 / 8",
        "h1_h2_opened": "NO",
        "new_candidate_mining": "NO",
    }
    paths.accumulated_tracked.mkdir(parents=True, exist_ok=True)
    _write_json(paths.accumulated_tracked / "accumulated-review-summary.json", summary)
    funnel_status = bookkeeping["funnel_bookkeeping_status"]
    md = f"""# Direct Continuation Review V1 — Accumulated Summary

Status: `HUMAN_REVIEW_FROZEN` for Batch 01; Batch 02 is `PENDING`.

## Completed human observations

| Metric | Count |
| --- | ---: |
| Total reviewed | {BATCH01_COUNT} |
| `DIRECT_STRAIGHT_CONTINUATION` | {counts['DIRECT_STRAIGHT_CONTINUATION']} |
| `NOT_DIRECT_STRAIGHT_CONTINUATION` | {counts['NOT_DIRECT_STRAIGHT_CONTINUATION']} |
| `INSUFFICIENT_EVIDENCE` | {counts['INSUFFICIENT_EVIDENCE']} |
| `OBJECT_GEOMETRY` | {counts['OBJECT_GEOMETRY']} |
| `ANNOTATION_LAYOUT` | {counts['ANNOTATION_LAYOUT']} |
| `UNKNOWN_ROLE` | {counts['UNKNOWN_ROLE']} |

Object and annotation counts are planning floors, not statistically sufficient
guarantees. Continue 24-case batches until both completed DIRECT role counts
reach 35. Do not predict the number of batches required.

## Pool and Batch 02

- Frozen fresh pool: `{FRESH_POOL_COUNT}`
- Remaining after exact Batch-01 exclusion: `{REMAINING_POOL_COUNT}`
- Batch 02 selected: `{len(batch02['selected'])} / {BATCH_SIZE}`
- Batch 02 human review: `PENDING`
- Batch 01 candidates reused: `0`
- Batch 01 exact geometry reused: `0`
- Batch 02 deterministic replay: `{batch02['selection_replay']['selection_deterministic_replay']}`

## Historical funnel bookkeeping

- Raw Hough primitives: `{bookkeeping['raw_hough_primitives_previous']}`
- Span-status total: `{bookkeeping['raw_hough_span_status_total_previous']}`
- Not span-evaluated: `{bookkeeping['raw_hough_not_span_evaluated']}`
- Reason: `orientation_filter_rejected_before_span_evaluation` = `{bookkeeping['not_span_evaluated_reason_counts']['orientation_filter_rejected_before_span_evaluation']}`
- Unaccounted: `{bookkeeping['raw_hough_funnel_unaccounted']}`
- Status: `{funnel_status}`

The 537 records are mechanically explained by the existing telemetry field
`orientation_eligible_raw_hough_primitives` and the existing `_raw_hough`
orientation gate. No Hough mining was rerun and no guard was changed.

## Governance

- Production semantic delta: `NONE`
- Model bake-off should resume: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- New candidate mining: `NO`
"""
    (paths.accumulated_tracked / "ACCUMULATED-REVIEW-SUMMARY.md").write_text(md, encoding="utf-8")
    return summary


def run_workflow(repo_root: Path, export_path: Path) -> dict[str, Any]:
    paths = AccumulationPaths(repo_root)
    batch01 = freeze_batch01(paths, Path(export_path))
    batch02 = prepare_batch02(paths, batch01)
    bookkeeping = resolve_funnel_bookkeeping(paths)
    accumulated = write_accumulated_summary(paths, batch01, batch02, bookkeeping)
    return {
        "paths": paths,
        "batch01": batch01,
        "batch02": batch02,
        "bookkeeping": bookkeeping,
        "accumulated": accumulated,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    args = parser.parse_args()
    result = run_workflow(args.repo_root.resolve(), args.export.resolve())
    print(
        json.dumps(
            {
                "batch01_freeze_digest": result["batch01"]["manifest"]["freeze_digest"],
                "batch02_selection_digest": result["batch02"]["selection_manifest"]["selection_digest"],
                "batch02_selected": len(result["batch02"]["selected"]),
                "remaining_pool": len(result["batch02"]["remaining"]),
                "funnel_bookkeeping_status": result["bookkeeping"]["funnel_bookkeeping_status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "AccumulationPaths",
    "PROTOCOL",
    "STAGE1_VALUES",
    "STAGE2_VALUES",
    "ab_geometry_digest",
    "main",
    "prepare_batch02",
    "resolve_funnel_bookkeeping",
    "run_workflow",
    "source_mapping_digest",
    "validate_batch01_export",
    "validate_batch02_package",
]
