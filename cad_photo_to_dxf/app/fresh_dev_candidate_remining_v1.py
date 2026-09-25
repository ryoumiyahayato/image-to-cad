"""Deterministic guarded DEV candidate remining and review packaging.

This module is intentionally outside every production processing path.  It
replays the authorized Local-C/Local-D source pool, gates raw Hough
primitives with the current span, axis, text, and straight-validity guards,
proposes geometric pairs, gates those pairs with the current direct-continuation
guard, and freezes a prediction-blind review set.  Source-derived images are written only below
``local-artifacts``; tracked output contains manifests and deterministic
selection metadata, not source imagery or human answers.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping, Sequence
import zipfile

import cv2
from PIL import Image, ImageDraw, ImageFont
import numpy as np

try:  # Package imports when called as ``python -m cad_photo_to_dxf...``.
    from .direct_continuation_admissibility import (
        DirectContinuationStatus,
        assess_direct_continuation,
    )
    from .expert_review_package import _colored_pixel_fraction
    from .line_provenance_audit_v1 import _raw_hough, normalize_hough_records
    from .human_review_v1c_package import V1C_HTML_TEMPLATE
    from .primitive_axis_support_integrity import AxisSupportStatus
    from .primitive_span_integrity import (
        DEFAULT_THRESHOLDS,
        SpanIntegrityStatus,
        qualify_dev_hough_primitives_cached,
    )
    from .primitive_text_support_integrity import (
        TextSupportStatus,
        qualify_dev_text_support_primitives,
    )
    from .straight_primitive_validity import (
        StraightValidityStatus,
        qualify_dev_straight_primitives,
    )
except ImportError:  # Script execution from ``cad_photo_to_dxf``.
    from app.direct_continuation_admissibility import (  # type: ignore
        DirectContinuationStatus,
        assess_direct_continuation,
    )
    from app.expert_review_package import _colored_pixel_fraction  # type: ignore
    from app.line_provenance_audit_v1 import _raw_hough, normalize_hough_records  # type: ignore
    from app.human_review_v1c_package import V1C_HTML_TEMPLATE  # type: ignore
    from app.primitive_axis_support_integrity import (  # type: ignore
        AxisSupportStatus,
    )
    from app.primitive_span_integrity import (  # type: ignore
        DEFAULT_THRESHOLDS,
        SpanIntegrityStatus,
        qualify_dev_hough_primitives_cached,
    )
    from app.primitive_text_support_integrity import (  # type: ignore
        TextSupportStatus,
        qualify_dev_text_support_primitives,
    )
    from app.straight_primitive_validity import (  # type: ignore
        StraightValidityStatus,
        qualify_dev_straight_primitives,
    )


BASE_CHECKPOINT = "93438db2978d45d2fdc4022f82f52cac18ded831"
SELECTION_CODE_VERSION = "FRESH_DEV_CANDIDATE_REMINING_V1_CODE_1"
PROTOCOL = "DIRECT_CONTINUATION_REVIEW_V1"
CANDIDATE_SET_NAME = "FRESH-DEV-CANDIDATE-REMINING-V1"
PACKAGE_ID = "fresh-dev-candidate-remining-v1-review"
MAX_REVIEW_COUNT = 24
MAX_RAW_PROPOSALS_PER_UNIT = 30
MAX_RAW_PROPOSALS_TOTAL = 480
GEOMETRY_QUANTUM = 8
MIN_GAP_PX = 5
MAX_GAP_PX = 70
MAX_AXIS_DELTA_PX = 8
MIN_PROJECTED_SPAN_PX = 85
MAX_PROJECTED_SPAN_PX = 900

STAGE1_VALUES: tuple[str, ...] = (
    "DIRECT_STRAIGHT_CONTINUATION",
    "NOT_DIRECT_STRAIGHT_CONTINUATION",
    "INSUFFICIENT_EVIDENCE",
)
STAGE2_VALUES: tuple[str, ...] = (
    "OBJECT_GEOMETRY",
    "ANNOTATION_LAYOUT",
    "UNKNOWN_ROLE",
)


@dataclass(frozen=True)
class ReminePaths:
    repo_root: Path
    tracked_root: Path
    runtime_root: Path
    source_renders: Path

    @classmethod
    def for_repo(cls, repo_root: Path) -> "ReminePaths":
        root = Path(repo_root).resolve()
        return cls(
            repo_root=root,
            tracked_root=root
            / "cad_photo_to_dxf"
            / "validation"
            / "fresh-dev-candidate-remining-v1",
            runtime_root=root
            / "local-artifacts"
            / "draftsman"
            / "fresh-dev-candidate-remining-v1",
            source_renders=root
            / "local-artifacts"
            / "draftsman"
            / "user-supplied-candidate-mining-v2-local-d"
            / "source-renders",
        )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _round_point(point: Sequence[float]) -> list[int]:
    return [int(round(float(point[0]))), int(round(float(point[1])))]


def _point(value: Sequence[float]) -> tuple[int, int]:
    return int(round(float(value[0]))), int(round(float(value[1])))


def _segment_length(segment: Mapping[str, Any]) -> float:
    x0, y0 = _point(segment["start"])
    x1, y1 = _point(segment["end"])
    return float(np.hypot(x1 - x0, y1 - y0))


def _source_relative_render(unit_id: str) -> str:
    return (
        "local-artifacts/draftsman/"
        "user-supplied-candidate-mining-v2-local-d/source-renders/"
        f"{unit_id}.png"
    )


def _gap_bin(gap: float) -> str:
    if gap <= 11:
        return "SHORT"
    if gap <= 29:
        return "MEDIUM"
    return "LONG"


def _quality_bin(unit: Mapping[str, Any]) -> str:
    text = " ".join(
        str(unit.get(key, ""))
        for key in ("degradation_characteristics", "vector_raster_mixed")
    ).casefold()
    if any(token in text for token in ("scan", "degrad", "stamp", "photo")):
        return "DEGRADED_OR_SCANNED"
    if any(token in text for token in ("native", "vector", "cad")):
        return "NATIVE_OR_VECTOR"
    return "MIXED_OR_UNKNOWN"


def _unit_identity(unit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_unit_id": unit["selected_unit_id"],
        "source_family_id": unit["source_family_id"],
        "source_document_id": unit["source_document_id"],
        "source_type": unit["source_type"],
        "source_relative_path": unit["source_relative_path"],
        "space": unit.get("space"),
        "pdf_page_index": unit.get("pdf_page_index"),
        "pdf_page_number": unit.get("pdf_page_number"),
        "dwg_layout_name": unit.get("dwg_layout_name"),
        "drawing_sheet_identifier": unit.get("drawing_sheet_identifier"),
        "discipline": unit.get("discipline"),
        "vector_raster_mixed": unit.get("vector_raster_mixed"),
        "degradation_characteristics": unit.get("degradation_characteristics"),
        "selection_confidence": unit.get("selection_confidence"),
        "fidelity_blocked": bool(unit.get("fidelity_blocked", False)),
        "source_render_path": _source_relative_render(unit["selected_unit_id"]),
    }


def load_authorized_source_units(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Load only the already-authorized, Local-C eligible units.

    The external user source root recorded by Local-C is intentionally never
    opened here.  Mining uses only the existing Local-D source renders below
    the verified worktree's ignored ``local-artifacts`` directory.
    """

    paths = ReminePaths.for_repo(repo_root)
    validation = paths.repo_root / "cad_photo_to_dxf" / "validation"
    auth_path = validation / "user-supplied-source-authorization-v2" / "authorization-record.json"
    triage_path = validation / "user-supplied-page-triage-v2-local-c" / "selected-page-layout-set.json"
    registry_path = validation / "user-supplied-candidate-mining-v2-local-d" / "candidate-registry.json"
    auth = _read_json(auth_path)
    triage = _read_json(triage_path)
    registry = _read_json(registry_path)
    blocked = set(auth["existing_local_c_eligibility_snapshot"]["fidelity_blocked_unit_ids"])
    eligible_ids = set(registry["eligible_input_units"])
    units: list[dict[str, Any]] = []
    for raw_unit in triage["selected_units"]:
        unit_id = raw_unit["selected_unit_id"]
        if unit_id in blocked or bool(raw_unit.get("fidelity_blocked", False)):
            continue
        if unit_id not in eligible_ids:
            continue
        unit = _unit_identity(raw_unit)
        render = paths.repo_root / Path(*unit["source_render_path"].split("/"))
        if not render.is_file():
            raise FileNotFoundError(f"missing authorized Local-D render: {render}")
        units.append(unit)
    units.sort(key=lambda item: item["selected_unit_id"])
    if len(units) != int(auth["existing_local_c_eligibility_snapshot"]["candidate_eligible_units"]):
        raise ValueError("authorized Local-C eligible-unit count changed")
    if {item["selected_unit_id"] for item in units} != eligible_ids:
        raise ValueError("Local-C eligible source identity changed")
    manifest_hashes = {
        "authorization_record_sha256": _sha256_file(auth_path),
        "page_triage_manifest_sha256": _sha256_file(triage_path),
        "local_d_registry_sha256": _sha256_file(registry_path),
    }
    return units, manifest_hashes


def _canonical_segment(segment: Mapping[str, Any]) -> dict[str, Any]:
    start = _point(segment["start"])
    end = _point(segment["end"])
    if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
        return {
            "orientation": "horizontal",
            "axis": int(round((start[1] + end[1]) / 2)),
            "start": min(start[0], end[0]),
            "end": max(start[0], end[0]),
        }
    return {
        "orientation": "vertical",
        "axis": int(round((start[0] + end[0]) / 2)),
        "start": min(start[1], end[1]),
        "end": max(start[1], end[1]),
    }


def _raw_pair_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    ancestors = candidate.get("raw_ancestor_ids", {})
    a = tuple(sorted(str(value) for value in ancestors.get("fragment_a", [])))
    b = tuple(sorted(str(value) for value in ancestors.get("fragment_b", [])))
    return (candidate.get("selected_unit_id"), a, b)


def _signature_payload(candidate: Mapping[str, Any], quantum: int) -> dict[str, Any]:
    def q(value: float) -> int:
        return int(round(float(value) / quantum))

    def q_segment(segment: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "start": [q(segment["start"][0]), q(segment["start"][1])],
            "end": [q(segment["end"][0]), q(segment["end"][1])],
        }

    return {
        "selected_unit_id": candidate["selected_unit_id"],
        "source_document_id": candidate["source_document_id"],
        "page_or_view": candidate.get("page_or_view"),
        "orientation": candidate["orientation"],
        "fragment_a": q_segment(candidate["fragment_a_geometry"]),
        "fragment_b": q_segment(candidate["fragment_b_geometry"]),
        "gap": {
            "a": [q(candidate["gap_endpoint_a"][0]), q(candidate["gap_endpoint_a"][1])],
            "b": [q(candidate["gap_endpoint_b"][0]), q(candidate["gap_endpoint_b"][1])],
        },
    }


def geometry_signature(candidate: Mapping[str, Any], quantum: int = GEOMETRY_QUANTUM) -> str:
    """Return the deterministic, semantic-label-free geometry signature."""

    return _sha256_bytes(_canonical_json(_signature_payload(candidate, quantum)).encode("utf-8"))


def _page_or_view(unit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "space": unit.get("space"),
        "pdf_page_index": unit.get("pdf_page_index"),
        "pdf_page_number": unit.get("pdf_page_number"),
        "dwg_layout_name": unit.get("dwg_layout_name"),
        "drawing_sheet_identifier": unit.get("drawing_sheet_identifier"),
    }


def _line_geometry(canonical: Mapping[str, Any]) -> dict[str, list[int]]:
    if canonical["orientation"] == "horizontal":
        return {
            "start": [int(canonical["start"]), int(canonical["axis"])],
            "end": [int(canonical["end"]), int(canonical["axis"])],
        }
    return {
        "start": [int(canonical["axis"]), int(canonical["start"])],
        "end": [int(canonical["axis"]), int(canonical["end"])],
    }


def _pair_geometry(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    geometry_a = _line_geometry(a["geometry"])
    geometry_b = _line_geometry(b["geometry"])
    orientation = str(a["geometry"]["orientation"])
    if orientation == "horizontal":
        gap_a = [int(a["geometry"]["end"]), int(a["geometry"]["axis"])]
        gap_b = [int(b["geometry"]["start"]), int(b["geometry"]["axis"])]
    else:
        gap_a = [int(a["geometry"]["axis"]), int(a["geometry"]["end"])]
        gap_b = [int(b["geometry"]["axis"]), int(b["geometry"]["start"])]
    gap = int(round(np.hypot(gap_b[0] - gap_a[0], gap_b[1] - gap_a[1])))
    axis_delta = abs(float(a["geometry"]["axis"]) - float(b["geometry"]["axis"]))
    projected_span = int(b["geometry"]["end"] - a["geometry"]["start"])
    return {
        "orientation": orientation,
        "fragment_a_geometry": geometry_a,
        "fragment_b_geometry": geometry_b,
        "gap_endpoint_a": gap_a,
        "gap_endpoint_b": gap_b,
        "gap_length_px": gap,
        "alignment_metrics": {
            "axis_delta_px": round(axis_delta, 3),
            "fragment_a_length_px": round(_segment_length(geometry_a), 3),
            "fragment_b_length_px": round(_segment_length(geometry_b), 3),
            "projected_span_px": projected_span,
        },
        "raw_ancestor_ids": {
            "fragment_a": list(a.get("raw_ancestor_ids", [])),
            "fragment_b": list(b.get("raw_ancestor_ids", [])),
        },
        "source_stroke_groups": {
            "fragment_a": dict(a.get("source_stroke_group", {})),
            "fragment_b": dict(b.get("source_stroke_group", {})),
        },
        "text_support_integrity": {
            "fragment_a": dict(a.get("text_support_integrity", {})),
            "fragment_b": dict(b.get("text_support_integrity", {})),
        },
    }


def _candidate_from_pair(
    pair: Mapping[str, Any], unit: Mapping[str, Any]
) -> dict[str, Any]:
    candidate = {
        **_unit_identity(unit),
        "page_or_view": _page_or_view(unit),
        "orientation": pair["orientation"],
        "fragment_a_geometry": pair["fragment_a_geometry"],
        "fragment_b_geometry": pair["fragment_b_geometry"],
        "gap_endpoint_a": pair["gap_endpoint_a"],
        "gap_endpoint_b": pair["gap_endpoint_b"],
        "gap_length_px": pair["gap_length_px"],
        "alignment_metrics": pair["alignment_metrics"],
        "raw_ancestor_ids": pair["raw_ancestor_ids"],
        "source_stroke_groups": pair.get("source_stroke_groups", {}),
        "text_support_integrity": pair["text_support_integrity"],
        "geometry_signature": geometry_signature(
            {
                "selected_unit_id": unit["selected_unit_id"],
                "source_document_id": unit["source_document_id"],
                "page_or_view": _page_or_view(unit),
                **pair,
            }
        ),
    }
    candidate["candidate_id"] = "FRESH1-" + candidate["geometry_signature"][:20].upper()
    candidate["gap_bin"] = _gap_bin(float(candidate["gap_length_px"]))
    candidate["raw_ancestor_pair"] = _raw_pair_key(candidate)
    return candidate


def _pair_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    orientation_rank = 0 if candidate["orientation"] == "horizontal" else 1
    metrics = candidate["alignment_metrics"]
    return (
        orientation_rank,
        _gap_bin(float(candidate["gap_length_px"])),
        float(metrics["axis_delta_px"]),
        int(candidate["gap_length_px"]),
        -min(float(metrics["fragment_a_length_px"]), float(metrics["fragment_b_length_px"])),
        candidate["geometry_signature"],
    )


def _round_robin_cap(candidates: Sequence[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in sorted(candidates, key=_pair_sort_key):
        buckets[(candidate["orientation"], candidate["gap_bin"])].append(candidate)
    keys = [
        (orientation, gap_bin)
        for orientation in ("horizontal", "vertical")
        for gap_bin in ("SHORT", "MEDIUM", "LONG")
    ]
    output: list[dict[str, Any]] = []
    while len(output) < cap and any(buckets[key] for key in keys):
        for key in keys:
            if buckets[key] and len(output) < cap:
                output.append(buckets[key].pop(0))
    return sorted(output, key=lambda item: item["geometry_signature"])


def propose_geometric_pairs(
    normalized_supported: Sequence[Mapping[str, Any]],
    unit: Mapping[str, Any],
    *,
    raw_cap: int = MAX_RAW_PROPOSALS_PER_UNIT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Form bounded same-orientation geometric A/B proposals only."""

    by_orientation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in normalized_supported:
        by_orientation[str(record["geometry"]["orientation"])].append(dict(record))

    candidates: list[dict[str, Any]] = []
    attempts = 0
    rejections: Counter[str] = Counter()
    for orientation in ("horizontal", "vertical"):
        records = sorted(
            by_orientation.get(orientation, []),
            key=lambda item: (
                int(item["geometry"]["start"]),
                int(item["geometry"]["axis"]),
                int(item["geometry"]["end"]),
                item["id"],
            ),
        )
        starts = [int(item["geometry"]["start"]) for item in records]
        for index, first in enumerate(records):
            first_geometry = first["geometry"]
            lower = bisect_left(starts, int(first_geometry["end"]) + MIN_GAP_PX)
            upper = bisect_right(starts, int(first_geometry["end"]) + MAX_GAP_PX)
            for second in records[lower:upper]:
                if second["id"] == first["id"]:
                    continue
                axis_delta = abs(
                    int(first_geometry["axis"]) - int(second["geometry"]["axis"])
                )
                if axis_delta > MAX_AXIS_DELTA_PX:
                    continue
                attempts += 1
                gap = int(second["geometry"]["start"]) - int(first_geometry["end"])
                if gap < MIN_GAP_PX:
                    rejections["near_zero_or_overlapping_gap"] += 1
                    continue
                if gap > MAX_GAP_PX:
                    rejections["grossly_excessive_gap"] += 1
                    continue
                projected = int(second["geometry"]["end"]) - int(first_geometry["start"])
                if not MIN_PROJECTED_SPAN_PX <= projected <= MAX_PROJECTED_SPAN_PX:
                    rejections["grossly_excessive_projected_span"] += 1
                    continue
                candidates.append(_candidate_from_pair(_pair_geometry(first, second), unit))

    capped = _round_robin_cap(candidates, raw_cap)
    return capped, {
        "pair_attempts": attempts,
        "pair_pool_count": attempts,
        "geometric_pairs_before_cap": len(candidates),
        "raw_proposals_after_cap": len(capped),
        "raw_cap": raw_cap,
        "pair_rejection_counts": dict(sorted(rejections.items())),
    }


def apply_direct_continuation_guard(
    gray: np.ndarray, proposals: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Partition geometric proposals using the current direct guard."""

    admissible: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for proposal in proposals:
        decision = assess_direct_continuation(gray, proposal)
        record = dict(proposal)
        record["direct_continuation"] = decision.to_dict()
        status = decision.status.value
        counts[status] += 1
        if decision.status is DirectContinuationStatus.ADMISSIBLE:
            admissible.append(record)
        else:
            filtered.append(record)
    return admissible, filtered, counts


def load_old_frozen_controls(repo_root: Path) -> dict[str, Any]:
    """Load old geometry/ancestor identity only for deterministic exclusion."""

    root = Path(repo_root).resolve() / "cad_photo_to_dxf" / "validation"
    frozen_path = root / "user-supplied-candidate-mining-v2-local-d" / "frozen-candidate-set.json"
    registry_path = root / "user-supplied-candidate-mining-v2-local-d" / "candidate-registry.json"
    audit_path = root / "line-provenance-audit-v1" / "line-provenance-audit-cases.json"
    dedup_path = root / "user-supplied-candidate-mining-v2-local-d" / "candidate-dedup.json"
    frozen = _read_json(frozen_path)
    registry = _read_json(registry_path)
    audit = _read_json(audit_path)
    dedup = _read_json(dedup_path)
    records = list(frozen["frozen_candidates"])
    audit_by_id = {item["candidate_id"]: item for item in audit["cases"]}
    exact_signatures: set[str] = set()
    near_signatures: set[str] = set()
    old_raw_pairs: set[tuple[Any, ...]] = set()
    old_ids: set[str] = set()
    old_records: list[dict[str, Any]] = []
    for record in records:
        candidate = dict(record)
        candidate["selected_unit_id"] = candidate["selected_unit_id"]
        candidate["source_document_id"] = candidate["source_document_id"]
        candidate["page_or_view"] = candidate.get("page_layout_modelspace_identity")
        candidate["gap_endpoint_a"] = candidate["gap_endpoint_a"]
        candidate["gap_endpoint_b"] = candidate["gap_endpoint_b"]
        exact_signatures.add(geometry_signature(candidate, quantum=1))
        near_signatures.add(geometry_signature(candidate, quantum=GEOMETRY_QUANTUM))
        old_ids.add(str(candidate["candidate_id"]))
        case = audit_by_id.get(candidate["candidate_id"], {})
        ancestors = case.get("raw_hough_ancestors", {})
        if isinstance(ancestors, dict):
            candidate["raw_ancestor_ids"] = {
                "fragment_a": [item.get("raw_hough_id") for item in ancestors.get("fragment_a", [])],
                "fragment_b": [item.get("raw_hough_id") for item in ancestors.get("fragment_b", [])],
            }
            old_raw_pairs.add(_raw_pair_key(candidate))
        old_records.append(candidate)
    return {
        "candidate_ids": sorted(old_ids),
        "exact_signatures": exact_signatures,
        "near_signatures": near_signatures,
        "raw_pairs": old_raw_pairs,
        "records": old_records,
        "candidate_registry_sha256": _sha256_file(registry_path),
        "frozen_set_sha256": _sha256_file(frozen_path),
        "provenance_audit_sha256": _sha256_file(audit_path),
        "dedup_totals": dedup["totals"],
        "dedup_caps": dedup["caps"],
    }


def filter_against_old_frozen(
    candidates: Sequence[Mapping[str, Any]], old_controls: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Remove old exact geometry/ancestor pairs, then old near duplicates."""

    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        exact = (
            candidate["candidate_id"] in set(old_controls["candidate_ids"])
            or geometry_signature(candidate, quantum=1) in old_controls["exact_signatures"]
            or _raw_pair_key(candidate) in old_controls["raw_pairs"]
        )
        if exact:
            counts["old_frozen_exact_duplicates_removed"] += 1
            record = dict(candidate)
            record["filter_stage"] = "OLD_FROZEN_EXACT"
            filtered.append(record)
            continue
        near = geometry_signature(candidate, quantum=GEOMETRY_QUANTUM) in old_controls["near_signatures"]
        if not near:
            candidate_pair = _raw_pair_key(candidate)
            near = any(
                candidate["selected_unit_id"] == old["selected_unit_id"]
                and candidate_pair[1:]
                and set(candidate_pair[1]).intersection(
                    set(_raw_pair_key(old)[1]) | set(_raw_pair_key(old)[2])
                )
                for old in old_controls["records"]
            )
        if near:
            counts["old_frozen_near_duplicates_removed"] += 1
            record = dict(candidate)
            record["filter_stage"] = "OLD_FROZEN_NEAR"
            filtered.append(record)
            continue
        kept.append(candidate)
    return kept, filtered, counts


def deduplicate_new_pool(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Collapse effectively identical fresh geometry deterministically."""

    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_candidate in sorted(
        candidates, key=lambda item: (item["geometry_signature"], item["candidate_id"])
    ):
        candidate = dict(raw_candidate)
        signature = geometry_signature(candidate, quantum=GEOMETRY_QUANTUM)
        candidate["new_pool_dedup_signature"] = signature
        if signature in seen:
            candidate["filter_stage"] = "NEW_POOL_DUPLICATE"
            filtered.append(candidate)
            continue
        seen.add(signature)
        kept.append(candidate)
    return kept, filtered, len(filtered)


def _context_density(gray: np.ndarray, candidate: Mapping[str, Any]) -> float:
    points = [
        _point(candidate["fragment_a_geometry"]["start"]),
        _point(candidate["fragment_a_geometry"]["end"]),
        _point(candidate["fragment_b_geometry"]["start"]),
        _point(candidate["fragment_b_geometry"]["end"]),
    ]
    x0 = max(0, min(point[0] for point in points) - 80)
    y0 = max(0, min(point[1] for point in points) - 80)
    x1 = min(gray.shape[1], max(point[0] for point in points) + 81)
    y1 = min(gray.shape[0], max(point[1] for point in points) + 81)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float(np.mean(patch < 220))


def _density_bin(value: float) -> str:
    if value < 0.03:
        return "SPARSE"
    if value < 0.12:
        return "MEDIUM"
    return "DENSE"


def add_selection_features(
    candidate: Mapping[str, Any], gray: np.ndarray
) -> dict[str, Any]:
    """Attach only geometry/source diversity features used for selection."""

    output = dict(candidate)
    density = _context_density(gray, candidate)
    output["selection_features"] = {
        "source_family_id": candidate["source_family_id"],
        "source_document_id": candidate["source_document_id"],
        "selected_unit_id": candidate["selected_unit_id"],
        "source_type": candidate["source_type"],
        "orientation": candidate["orientation"],
        "gap_bin": candidate["gap_bin"],
        "local_density_bin": _density_bin(density),
        "source_quality_bin": _quality_bin(candidate),
    }
    output["local_density_fraction"] = round(density, 6)
    return output


SELECTION_FEATURE_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("source_family_id", 8.0),
    ("selected_unit_id", 4.0),
    ("source_document_id", 3.0),
    ("source_type", 1.5),
    ("orientation", 1.5),
    ("gap_bin", 1.0),
    ("local_density_bin", 1.0),
    ("source_quality_bin", 1.0),
)


def select_diverse_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    max_count: int = MAX_REVIEW_COUNT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select a deterministic source/geometry-diverse fresh review set."""

    if max_count < 1:
        return [], {"selection_trace": [], "candidate_count": 0}
    remaining = [dict(candidate) for candidate in candidates]
    selected: list[dict[str, Any]] = []
    seen: dict[str, set[Any]] = defaultdict(set)
    trace: list[dict[str, Any]] = []
    while remaining and len(selected) < max_count:
        def rank(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
            features = candidate["selection_features"]
            novelty = sum(
                weight
                for key, weight in SELECTION_FEATURE_WEIGHTS
                if features[key] not in seen[key]
            )
            return (-novelty, candidate["geometry_signature"])

        choice = min(remaining, key=rank)
        remaining.remove(choice)
        selected.append(choice)
        features = choice["selection_features"]
        for key, _weight in SELECTION_FEATURE_WEIGHTS:
            seen[key].add(features[key])
        trace.append(
            {
                "review_index": len(selected),
                "candidate_id": choice["candidate_id"],
                "novelty_score": -rank(choice)[0],
                "new_feature_values": {
                    key: features[key]
                    for key, _weight in SELECTION_FEATURE_WEIGHTS
                    if list(seen[key]).count(features[key]) == 1
                },
            }
        )
    for index, candidate in enumerate(selected, start=1):
        candidate["review_index"] = index
    return selected, {
        "selection_trace": trace,
        "candidate_count": len(selected),
        "max_count": max_count,
        "feature_weights": dict(SELECTION_FEATURE_WEIGHTS),
        "selection_basis": [key for key, _weight in SELECTION_FEATURE_WEIGHTS],
    }


FRESH_GUIDANCE = r'''    <section class="compact-guidance" aria-label="直接连续审核规则">
      <strong>看得出来才判；看不出来不要猜。</strong>
      <span>第一步只判断：红色 Fragment A 到蓝色 Fragment B 之间，是否可以直接画一条直线。</span>
      <span class="legend" aria-label="候选标记图例">
        <span class="legend-chip"><i class="legend-dot red"></i>红 = Fragment A</span>
        <span class="legend-chip"><i class="legend-dot blue"></i>蓝 = Fragment B</span>
        <span class="legend-chip"><i class="legend-dot yellow"></i>黄 = 当前 Gap；只表示正在判断这里</span>
      </span>
      <details class="help">
        <summary>查看详细说明</summary>
        <div class="help-content">
          <p><b>第一步：</b>“这里可以直接画一条直线接过去” → <b>DIRECT_STRAIGHT_CONTINUATION</b>；“这里不能直接用一条直线接过去” → <b>NOT_DIRECT_STRAIGHT_CONTINUATION</b>；看不清或证据不足 → <b>INSUFFICIENT_EVIDENCE</b>。</p>
          <p>请判断黄色 Gap 中的直接直线是否会覆盖或矛盾于图纸内容。不需要判断专业名称，也不要诊断检测算法。</p>
          <p><b>第二步只在 DIRECT_STRAIGHT_CONTINUATION 后出现：</b>实际工程对象 / 安装对象 → <b>OBJECT_GEOMETRY</b>；注释、尺寸、文字、表格或版式 → <b>ANNOTATION_LAYOUT</b>；无法确定用途 → <b>UNKNOWN_ROLE</b>。</p>
        </div>
      </details>
    </section>
'''


FRESH_REVIEW_BAR = r'''  <section class="review-bar" aria-label="直接连续两阶段审核控制">
    <div class="review-bar-inner">
      <div class="review-bar-heading"><strong id="stage-heading">第一步：判断是否可以直接画直线</strong><span id="stage-shortcut">键盘：1 / 2 / 3　← / → 浏览</span></div>
      <div id="stage1-grid" class="label-grid protocol-grid">
        <button class="label-button" type="button" data-stage1="DIRECT_STRAIGHT_CONTINUATION"><span class="shortcut">1</span><span class="label-title">这里可以直接画一条直线接过去</span><span class="label-code">DIRECT_STRAIGHT_CONTINUATION</span></button>
        <button class="label-button" type="button" data-stage1="NOT_DIRECT_STRAIGHT_CONTINUATION"><span class="shortcut">2</span><span class="label-title">这里不能直接用一条直线接过去</span><span class="label-code">NOT_DIRECT_STRAIGHT_CONTINUATION</span></button>
        <button class="label-button" type="button" data-stage1="INSUFFICIENT_EVIDENCE"><span class="shortcut">3</span><span class="label-title">证据不足 / 看不清</span><span class="label-code">INSUFFICIENT_EVIDENCE</span></button>
      </div>
      <div id="stage2-grid" class="label-grid protocol-grid" hidden>
        <button class="label-button" type="button" data-stage2="OBJECT_GEOMETRY"><span class="shortcut">1</span><span class="label-title">实际工程对象 / 安装对象</span><span class="label-code">OBJECT_GEOMETRY</span></button>
        <button class="label-button" type="button" data-stage2="ANNOTATION_LAYOUT"><span class="shortcut">2</span><span class="label-title">注释 / 尺寸 / 文字 / 版式</span><span class="label-code">ANNOTATION_LAYOUT</span></button>
        <button class="label-button" type="button" data-stage2="UNKNOWN_ROLE"><span class="shortcut">3</span><span class="label-title">无法确定用途</span><span class="label-code">UNKNOWN_ROLE</span></button>
      </div>
      <div class="status-line" id="status-line" aria-live="polite"></div>
    </div>
  </section>
'''


FRESH_REVIEW_SCRIPT = r'''  <script>
  "use strict";
  const PACKAGE = __PACKAGE_MANIFEST__;
  const REVIEW_PROTOCOL = "DIRECT_CONTINUATION_REVIEW_V1";
  const STAGE1_VALUES = Object.freeze(["DIRECT_STRAIGHT_CONTINUATION", "NOT_DIRECT_STRAIGHT_CONTINUATION", "INSUFFICIENT_EVIDENCE"]);
  const STAGE2_VALUES = Object.freeze(["OBJECT_GEOMETRY", "ANNOTATION_LAYOUT", "UNKNOWN_ROLE"]);
  const STORAGE_KEY = "draftsman-direct-continuation-review-v1:" + PACKAGE.candidate_set_id;
  const HISTORY_PREFIX = STORAGE_KEY + ":history:";
  const state = {session:null, index:0, markerToggle:false, busy:false, noteTimer:null, modal:null, modalScale:1, drag:null};
  function now() { return new Date().toISOString(); }
  function isComplete(item) { return Boolean(item.stage1) && (item.stage1 !== "DIRECT_STRAIGHT_CONTINUATION" || Boolean(item.stage2)); }
  function newSession() {
    const timestamp = now();
    return {schema_version:1, protocol:REVIEW_PROTOCOL, session_id:"direct-continuation-review-" + timestamp.replace(/[-:.TZ]/g, "") + "-" + Math.random().toString(36).slice(2, 8), candidate_set_id:PACKAGE.candidate_set_id, review_order:PACKAGE.review_order.slice(), review_started_at:timestamp, review_updated_at:timestamp, items:PACKAGE.items.map(function(item) { return {review_index:item.review_index, candidate_id:item.candidate_id, stage1:null, stage2:null, optional_note:null, review_status:"PENDING", updated_at:timestamp}; })};
  }
  function sameArray(a,b) { return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(function(value,index) { return value === b[index]; }); }
  function normalizeSession(raw) {
    if (!raw || raw.schema_version !== 1 || raw.protocol !== REVIEW_PROTOCOL || raw.candidate_set_id !== PACKAGE.candidate_set_id) return null;
    if (!sameArray(raw.review_order, PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length !== PACKAGE.items.length) return null;
    const allowed = new Set(PACKAGE.review_order); const seen = new Set(); const timestamp = now();
    const items = raw.items.map(function(item) {
      if (!item || !allowed.has(item.candidate_id) || seen.has(item.candidate_id)) throw new Error("candidate identity mismatch");
      seen.add(item.candidate_id);
      const stage1 = item.stage1 || null; const stage2 = item.stage2 || null;
      if (stage1 !== null && !STAGE1_VALUES.includes(stage1)) throw new Error("Stage 1 vocabulary mismatch");
      if (stage2 !== null && !STAGE2_VALUES.includes(stage2)) throw new Error("Stage 2 vocabulary mismatch");
      if (stage1 !== "DIRECT_STRAIGHT_CONTINUATION" && stage2 !== null) throw new Error("Stage 2 is only valid after DIRECT_STRAIGHT_CONTINUATION");
      return {review_index:item.review_index, candidate_id:item.candidate_id, stage1:stage1, stage2:stage2, optional_note:item.optional_note || null, review_status:isComplete({stage1:stage1,stage2:stage2}) ? "REVIEWED" : "PENDING", updated_at:item.updated_at || timestamp};
    });
    return Object.assign({}, raw, {items:items, review_updated_at:raw.review_updated_at || timestamp});
  }
  function saveSession() { if (!state.session) return; state.session.review_updated_at=now(); localStorage.setItem(STORAGE_KEY, JSON.stringify(state.session)); }
  function loadSession() { let loaded=null; try { loaded=normalizeSession(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")); } catch(error) { loaded=null; } state.session=loaded || newSession(); const pending=state.session.items.findIndex(function(item) { return !isComplete(item); }); state.index=pending >= 0 ? pending : 0; saveSession(); }
  function currentItem() { return state.session.items[state.index]; }
  function packageItem(id) { return PACKAGE.items.find(function(item) { return item.candidate_id === id; }); }
  function counts() { const result={completed:0,pending:0,DIRECT_STRAIGHT_CONTINUATION:0,NOT_DIRECT_STRAIGHT_CONTINUATION:0,INSUFFICIENT_EVIDENCE:0,OBJECT_GEOMETRY:0,ANNOTATION_LAYOUT:0,UNKNOWN_ROLE:0}; state.session.items.forEach(function(item) { if (isComplete(item)) result.completed += 1; else result.pending += 1; if (item.stage1) result[item.stage1] += 1; if (item.stage1 === "DIRECT_STRAIGHT_CONTINUATION" && item.stage2) result[item.stage2] += 1; }); return result; }
  function setStatus(message) { document.getElementById("status-line").textContent=message || ""; }
  function renderProgress() { const tally=counts(); document.getElementById("progress").innerHTML="<strong>候选 " + (state.index+1) + " / " + PACKAGE.candidate_count + "</strong>已完成 " + tally.completed + " / " + PACKAGE.candidate_count + " · 待审核 " + tally.pending + "<br>第一步：可直接接 " + tally.DIRECT_STRAIGHT_CONTINUATION + " · 不可直接接 " + tally.NOT_DIRECT_STRAIGHT_CONTINUATION + " · 证据不足 " + tally.INSUFFICIENT_EVIDENCE + "<br>第二步：对象 " + tally.OBJECT_GEOMETRY + " · 注释 " + tally.ANNOTATION_LAYOUT + " · 用途未知 " + tally.UNKNOWN_ROLE; document.getElementById("candidate-heading").textContent="候选 " + (state.index+1) + " · " + currentItem().candidate_id; }
  function point(value) { return {x:Number(value[0]),y:Number(value[1])}; }
  function markerSvg(marker) { const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"); svg.setAttribute("viewBox","0 0 " + marker.width + " " + marker.height); svg.setAttribute("preserveAspectRatio","none"); svg.setAttribute("class","marker-overlay"); svg.setAttribute("role","img"); svg.setAttribute("aria-label","候选位置标记：Fragment A、Fragment B、Gap"); function line(a,b,className) { const element=document.createElementNS("http://www.w3.org/2000/svg","line"); element.setAttribute("x1",a.x); element.setAttribute("y1",a.y); element.setAttribute("x2",b.x); element.setAttribute("y2",b.y); element.setAttribute("class",className); svg.appendChild(element); } function circle(p,className) { const element=document.createElementNS("http://www.w3.org/2000/svg","circle"); element.setAttribute("cx",p.x); element.setAttribute("cy",p.y); element.setAttribute("r","5"); element.setAttribute("class",className); svg.appendChild(element); } const a0=point(marker.fragment_a.start),a1=point(marker.fragment_a.end),b0=point(marker.fragment_b.start),b1=point(marker.fragment_b.end),gapA=point(marker.gap_endpoint_a),gapB=point(marker.gap_endpoint_b); line(a0,a1,"fragment-a"); line(b0,b1,"fragment-b"); line(gapA,gapB,"candidate-gap"); circle(gapA,"gap-a"); circle(gapB,"gap-b"); return svg; }
  function imageStage(item,kind) { const stage=document.createElement("div"); stage.className="image-stage"; stage.title="点击放大"; const frame=document.createElement("div"); frame.className="image-frame"; const image=document.createElement("img"); image.alt=kind === "local" ? "LOCAL clean evidence" : "CONTEXT clean evidence"; image.src=kind === "local" ? item.local_image : item.context_image; frame.appendChild(image); if (state.markerToggle) frame.appendChild(markerSvg(item.marker[kind])); stage.appendChild(frame); stage.addEventListener("click",function() { openModal(item,kind,state.markerToggle); }); return stage; }
  function renderEvidence() { const item=packageItem(currentItem().candidate_id); document.getElementById("local-stage").replaceChildren(imageStage(item,"local")); document.getElementById("context-stage").replaceChildren(imageStage(item,"context")); document.getElementById("marker-toggle").checked=state.markerToggle; }
  function renderControls() { const item=currentItem(); const direct=item.stage1 === "DIRECT_STRAIGHT_CONTINUATION"; document.getElementById("stage1-grid").hidden=false; document.getElementById("stage2-grid").hidden=!direct; document.getElementById("stage-heading").textContent=direct ? "第二步：判断这条连续直线的主要作用" : "第一步：判断是否可以直接画直线"; document.querySelectorAll("[data-stage1]").forEach(function(button) { button.classList.toggle("active",button.dataset.stage1 === item.stage1); }); document.querySelectorAll("[data-stage2]").forEach(function(button) { button.classList.toggle("active",button.dataset.stage2 === item.stage2); }); if (direct && !item.stage2) setStatus("第一步已保存。请完成第二步；不确定用途时选择 UNKNOWN_ROLE。"); }
  function renderNote() { document.getElementById("candidate-note").value=currentItem().optional_note || ""; }
  function render() { renderProgress(); renderEvidence(); renderControls(); renderNote(); }
  function advanceToNextPending() { const total=state.session.items.length; for (let offset=1; offset<=total; offset += 1) { const candidateIndex=(state.index+offset)%total; if (!isComplete(state.session.items[candidateIndex])) { state.index=candidateIndex; return; } } }
  function finishAndAdvance(message) { saveSession(); render(); setStatus(message); state.busy=true; window.setTimeout(function() { advanceToNextPending(); state.busy=false; render(); },180); }
  function setStage1(value) { if (!STAGE1_VALUES.includes(value) || state.busy) return; const item=currentItem(); item.stage2=value === "DIRECT_STRAIGHT_CONTINUATION" && item.stage1 === "DIRECT_STRAIGHT_CONTINUATION" ? item.stage2 : null; item.stage1=value; item.review_status=isComplete(item) ? "REVIEWED" : "PENDING"; item.updated_at=now(); saveSession(); render(); if (value === "DIRECT_STRAIGHT_CONTINUATION") setStatus(item.stage2 ? "第一步已保存。可修改第二步用途。" : "第一步已保存，请选择第二步用途。"); else finishAndAdvance("已保存第一步判断。"); }
  function setStage2(value) { if (!STAGE2_VALUES.includes(value) || state.busy || currentItem().stage1 !== "DIRECT_STRAIGHT_CONTINUATION") return; const item=currentItem(); item.stage2=value; item.review_status="REVIEWED"; item.updated_at=now(); saveSession(); finishAndAdvance("已保存第二步判断。"); }
  function saveNote() { const value=document.getElementById("candidate-note").value.trim(); currentItem().optional_note=value || null; currentItem().updated_at=now(); saveSession(); }
  function scheduleNoteSave() { window.clearTimeout(state.noteTimer); state.noteTimer=window.setTimeout(saveNote,350); }
  function navigate(delta) { if (delta > 0 && !isComplete(currentItem())) { setStatus("请先完成当前阶段，再前进。"); return; } state.index=Math.max(0,Math.min(state.session.items.length-1,state.index+delta)); render(); }
  function freshReview() { const hasAnswers=state.session.items.some(function(item) { return item.stage1 || item.stage2 || item.optional_note; }); if (hasAnswers && !window.confirm("开始新的审核？当前本地会话会保留，不会删除。")) return; if (hasAnswers) localStorage.setItem(HISTORY_PREFIX + state.session.session_id,JSON.stringify(state.session)); state.session=newSession(); state.index=0; saveSession(); render(); setStatus("新的审核已开始。"); }
  function downloadJson(filename,value) { const blob=new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"}); const url=URL.createObjectURL(blob); const anchor=document.createElement("a"); anchor.href=url; anchor.download=filename; anchor.click(); window.setTimeout(function() { URL.revokeObjectURL(url); },1000); }
  function exportResult() { saveNote(); const payload=state.session.items.map(function(item) { return {protocol:REVIEW_PROTOCOL,candidate_set_id:PACKAGE.candidate_set_id,candidate_id:item.candidate_id,review_index:item.review_index,stage1:item.stage1,stage2:item.stage2,optional_note:item.optional_note}; }); downloadJson("direct-continuation-review-v1-" + PACKAGE.candidate_set_id + ".json",payload); setStatus("审核结果已导出。"); }
  function validateImport(raw) { const rows=Array.isArray(raw) ? raw : raw && raw.items; if (!Array.isArray(rows) || rows.length !== PACKAGE.candidate_count) throw new Error("审核顺序或候选数量不匹配。"); const session=newSession(); const seen=new Set(); rows.forEach(function(item) { if (item.protocol !== REVIEW_PROTOCOL || item.candidate_set_id !== PACKAGE.candidate_set_id || seen.has(item.candidate_id)) throw new Error("审核结果身份不匹配。"); const target=session.items.find(function(candidate) { return candidate.candidate_id === item.candidate_id; }); if (!target || item.review_index !== target.review_index) throw new Error("候选顺序不匹配。"); if (item.stage1 !== null && !STAGE1_VALUES.includes(item.stage1)) throw new Error("Stage 1 标签不允许。"); if (item.stage2 !== null && !STAGE2_VALUES.includes(item.stage2)) throw new Error("Stage 2 标签不允许。"); if (item.stage1 !== "DIRECT_STRAIGHT_CONTINUATION" && item.stage2 !== null) throw new Error("非直接连续项目的 Stage 2 必须为空。"); target.stage1=item.stage1 || null; target.stage2=item.stage2 || null; target.optional_note=item.optional_note || null; target.review_status=isComplete(target) ? "REVIEWED" : "PENDING"; seen.add(item.candidate_id); }); return session; }
  function importResult(event) { const file=event.target.files && event.target.files[0]; if (!file) return; const reader=new FileReader(); reader.onload=function() { try { state.session=validateImport(JSON.parse(reader.result)); state.index=Math.max(0,state.session.items.findIndex(function(item) { return !isComplete(item); })); saveSession(); render(); setStatus("审核结果已导入。"); } catch(error) { window.alert(error.message || "导入失败。"); } event.target.value=""; }; reader.readAsText(file,"utf-8"); }
  function setModalScale(value) { state.modalScale=Math.max(.5,Math.min(4,Math.round(value*100)/100)); const content=document.getElementById("zoom-content"); content.style.transform="scale(" + state.modalScale + ")"; document.getElementById("modal-zoom-label").textContent=Math.round(state.modalScale*100) + "%"; }
  function renderModal() { if (!state.modal) return; const item=packageItem(state.modal.item.candidate_id); const content=document.getElementById("zoom-content"); content.replaceChildren(); const image=document.createElement("img"); image.alt=state.modal.kind === "local" ? "LOCAL enlarged evidence" : "CONTEXT enlarged evidence"; image.src=state.modal.kind === "local" ? item.local_image : item.context_image; content.appendChild(image); if (state.modal.marked) content.appendChild(markerSvg(item.marker[state.modal.kind])); document.getElementById("modal-marker-toggle").checked=state.modal.marked; document.getElementById("modal-title").textContent="候选 " + state.modal.item.review_index + " · " + item.candidate_id; document.getElementById("modal-view-kind").textContent=state.modal.kind === "local" ? "LOCAL · 局部证据" : "CONTEXT · 周边工程上下文"; setModalScale(state.modalScale); }
  function openModal(item,kind,marked) { state.modal={item:item,kind:kind,marked:Boolean(marked)}; state.modalScale=1; document.getElementById("image-modal").hidden=false; renderModal(); }
  function closeModal() { document.getElementById("image-modal").hidden=true; state.modal=null; state.drag=null; }
  function keyHandler(event) { const tag=event.target && event.target.tagName ? event.target.tagName.toLowerCase() : ""; if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return; if (state.modal) { if (event.key === "Escape") { event.preventDefault(); closeModal(); } return; } if (event.key === "ArrowLeft") { event.preventDefault(); navigate(-1); return; } if (event.key === "ArrowRight") { event.preventDefault(); navigate(1); return; } const second=currentItem().stage1 === "DIRECT_STRAIGHT_CONTINUATION" && !currentItem().stage2; if (event.key === "1") second ? setStage2("OBJECT_GEOMETRY") : setStage1("DIRECT_STRAIGHT_CONTINUATION"); else if (event.key === "2") second ? setStage2("ANNOTATION_LAYOUT") : setStage1("NOT_DIRECT_STRAIGHT_CONTINUATION"); else if (event.key === "3") second ? setStage2("UNKNOWN_ROLE") : setStage1("INSUFFICIENT_EVIDENCE"); }
  document.getElementById("marker-toggle").addEventListener("change",function(event) { state.markerToggle=event.target.checked; renderEvidence(); }); document.getElementById("fresh-button").addEventListener("click",freshReview); document.getElementById("import-button").addEventListener("click",function() { document.getElementById("import-file").click(); }); document.getElementById("import-file").addEventListener("change",importResult); document.getElementById("export-button").addEventListener("click",exportResult); document.querySelectorAll("[data-stage1]").forEach(function(button) { button.addEventListener("click",function() { setStage1(button.dataset.stage1); }); }); document.querySelectorAll("[data-stage2]").forEach(function(button) { button.addEventListener("click",function() { setStage2(button.dataset.stage2); }); }); document.getElementById("candidate-note").addEventListener("input",scheduleNoteSave); document.getElementById("modal-close").addEventListener("click",closeModal); document.getElementById("modal-marker-toggle").addEventListener("change",function(event) { if (state.modal) { state.modal.marked=event.target.checked; renderModal(); } }); document.getElementById("zoom-out").addEventListener("click",function() { setModalScale(state.modalScale-.25); }); document.getElementById("zoom-in").addEventListener("click",function() { setModalScale(state.modalScale+.25); }); document.getElementById("zoom-fit").addEventListener("click",function() { setModalScale(1); });
  const viewport=document.getElementById("zoom-viewport"); viewport.addEventListener("wheel",function(event) { if (!state.modal) return; event.preventDefault(); setModalScale(state.modalScale + (event.deltaY < 0 ? .15 : -.15)); },{passive:false}); viewport.addEventListener("pointerdown",function(event) { if (!state.modal || state.modalScale <= 1) return; state.drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop}; viewport.classList.add("dragging"); viewport.setPointerCapture(event.pointerId); }); viewport.addEventListener("pointermove",function(event) { if (!state.drag) return; viewport.scrollLeft=state.drag.left-(event.clientX-state.drag.x); viewport.scrollTop=state.drag.top-(event.clientY-state.drag.y); }); viewport.addEventListener("pointerup",function() { state.drag=null; viewport.classList.remove("dragging"); }); viewport.addEventListener("pointercancel",function() { state.drag=null; viewport.classList.remove("dragging"); }); document.addEventListener("keydown",keyHandler); loadSession(); render();
  </script>
'''


def _html_manifest_json(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_review_html(manifest: Mapping[str, Any]) -> str:
    """Reuse the proven clean evidence shell with the fresh protocol controls."""

    html = V1C_HTML_TEMPLATE.replace("<title>人工作图审核</title>", "<title>直接连续人工作图审核</title>")
    html = html.replace("开始新的更正审核", "开始新的直接连续审核")
    html = html.replace(
        '    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }',
        '    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }\n    .protocol-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }\n    .protocol-grid[hidden] { display:none; }',
    )
    guidance_start = html.index('    <section class="compact-guidance"')
    evidence_start = html.index('    <section class="evidence-panel"', guidance_start)
    html = html[:guidance_start] + FRESH_GUIDANCE + html[evidence_start:]
    bar_start = html.index('  <section class="review-bar"')
    modal_start = html.index('  <div id="image-modal"', bar_start)
    html = html[:bar_start] + FRESH_REVIEW_BAR + html[modal_start:]
    script_start = html.index("  <script>\n")
    script_end = html.index("  </script>", script_start) + len("  </script>\n")
    html = html[:script_start] + FRESH_REVIEW_SCRIPT + html[script_end:]
    return html.replace("__PACKAGE_MANIFEST__", _html_manifest_json(manifest))


def _font(size: int = 16) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ):
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _clip_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = box
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom


def crop_boxes_for_candidate(
    candidate: Mapping[str, Any], image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    points: list[tuple[int, int]] = []
    for segment_key in ("fragment_a_geometry", "fragment_b_geometry"):
        points.extend(
            [
                _point(candidate[segment_key]["start"]),
                _point(candidate[segment_key]["end"]),
            ]
        )
    points.extend([_point(candidate["gap_endpoint_a"]), _point(candidate["gap_endpoint_b"])])
    x0, x1 = min(point[0] for point in points), max(point[0] for point in points)
    y0, y1 = min(point[1] for point in points), max(point[1] for point in points)
    span = max(x1 - x0, y1 - y0, 1)
    local_margin_x = max(42, min(150, int(round(span * 0.10))))
    local_margin_y = max(42, min(150, int(round(span * 0.10))))
    context_margin = max(160, min(360, int(round(span * 0.34))))
    local = _clip_box(
        (x0 - local_margin_x, y0 - local_margin_y, x1 + local_margin_x + 1, y1 + local_margin_y + 1),
        image_size,
    )
    context = _clip_box(
        (x0 - context_margin, y0 - context_margin, x1 + context_margin + 1, y1 + context_margin + 1),
        image_size,
    )
    return local, context


def _relative_point(point: Sequence[float], box: Sequence[int]) -> list[float]:
    return [round(float(point[0]) - int(box[0]), 3), round(float(point[1]) - int(box[1]), 3)]


def _relative_segment(segment: Mapping[str, Any], box: Sequence[int]) -> dict[str, list[float]]:
    return {
        "start": _relative_point(segment["start"], box),
        "end": _relative_point(segment["end"], box),
    }


def _marker(candidate: Mapping[str, Any], box: tuple[int, int, int, int], size: tuple[int, int]) -> dict[str, Any]:
    return {
        "width": size[0],
        "height": size[1],
        "fragment_a": _relative_segment(candidate["fragment_a_geometry"], box),
        "fragment_b": _relative_segment(candidate["fragment_b_geometry"], box),
        "gap_endpoint_a": _relative_point(candidate["gap_endpoint_a"], box),
        "gap_endpoint_b": _relative_point(candidate["gap_endpoint_b"], box),
    }


def _write_clean_crop(source_path: Path, box: tuple[int, int, int, int], destination: Path) -> tuple[int, int]:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
        if box[2] > image.width or box[3] > image.height:
            raise ValueError(f"crop box exceeds source render: {source_path} {box} {image.size}")
        crop = image.crop(box)
        if _colored_pixel_fraction(crop) > 0.01:
            raise ValueError(f"source render contains unexpected colored pixels: {source_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        crop.save(destination, format="PNG", optimize=True)
        return crop.size


def _safe_replace_runtime(path: Path) -> None:
    resolved = path.resolve()
    if resolved.name != "fresh-dev-candidate-remining-v1" or resolved.parent.name != "draftsman" or resolved.parent.parent.name != "local-artifacts":
        raise ValueError(f"refusing to replace unexpected fresh runtime path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _build_fresh_manifest(
    selected: Sequence[Mapping[str, Any]],
    candidate_set_id: str,
    selection_digest: str,
    runtime_package: Path,
    source_manifest_hashes: Mapping[str, str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for candidate in selected:
        items.append(
            {
                "review_index": int(candidate["review_index"]),
                "candidate_id": candidate["candidate_id"],
                "local_image": f"assets/local/{candidate['candidate_id']}.png",
                "context_image": f"assets/context/{candidate['candidate_id']}.png",
                "marker": {
                    "local": candidate["markers"]["local"],
                    "context": candidate["markers"]["context"],
                },
            }
        )
    return {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(items),
        "stage1_values": list(STAGE1_VALUES),
        "stage2_values": list(STAGE2_VALUES),
        "review_order": [item["candidate_id"] for item in items],
        "source_manifest_identity": {
            "selection_digest": selection_digest,
            **dict(source_manifest_hashes),
        },
        "items": items,
        "governance": {
            "source_full_documents_included": False,
            "source_derived_images_local_only": True,
            "human_review_status": "PENDING",
            "export_reload_supported": True,
        },
    }


def validate_review_export(
    payload: Any, candidate_set_id: str, review_order: Sequence[str]
) -> bool:
    """Validate the neutral exported rows without assigning any answers."""

    rows = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(review_order):
        return False
    seen: set[str] = set()
    for expected_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return False
        if set(row) != {"protocol", "candidate_set_id", "candidate_id", "review_index", "stage1", "stage2", "optional_note"}:
            return False
        if row["protocol"] != PROTOCOL or row["candidate_set_id"] != candidate_set_id:
            return False
        if row["candidate_id"] != review_order[expected_index - 1] or row["review_index"] != expected_index:
            return False
        if row["candidate_id"] in seen:
            return False
        seen.add(row["candidate_id"])
        if row["stage1"] not in (*STAGE1_VALUES, None) or row["stage2"] not in (*STAGE2_VALUES, None):
            return False
        if row["stage1"] != "DIRECT_STRAIGHT_CONTINUATION" and row["stage2"] is not None:
            return False
    return True


def validate_review_package(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    count = int(manifest["candidate_count"])
    if manifest.get("package_id") != PACKAGE_ID or manifest.get("review_protocol") != PROTOCOL:
        raise ValueError("fresh review package identity is invalid")
    if count != len(manifest.get("items", [])) or count != len(manifest.get("review_order", [])):
        raise ValueError("fresh review package order/count is invalid")
    if manifest.get("stage1_values") != list(STAGE1_VALUES) or manifest.get("stage2_values") != list(STAGE2_VALUES):
        raise ValueError("fresh review vocabulary is invalid")
    if "fetch(" in html or "XMLHttpRequest" in html or "<script src=" in html or "<link href=" in html:
        raise ValueError("fresh review package contains a network dependency")
    forbidden = (
        "SPAN_INTEGRITY_",
        "DIRECT_CONTINUATION_ADMISSIBLE",
        "DIRECT_CONTINUATION_REJECTED",
        "DIRECT_CONTINUATION_UNCERTAIN",
        "audit_primary",
        "model_score",
        "prediction",
        "expected_answer",
        "semantic_class",
    )
    if any(token in html for token in forbidden):
        raise ValueError("fresh review package exposes mining or model metadata")
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
        "stage1 === \"DIRECT_STRAIGHT_CONTINUATION\"",
        "protocol:REVIEW_PROTOCOL",
    )
    if any(token not in html for token in required):
        raise ValueError("fresh review package is missing required neutral controls")
    for item in manifest["items"]:
        for key in ("local_image", "context_image"):
            path = package_dir / Path(*item[key].split("/"))
            if not path.is_file():
                raise FileNotFoundError(path)
            with Image.open(path) as image:
                if image.width <= 0 or image.height <= 0 or _colored_pixel_fraction(image) > 0.01:
                    raise ValueError(f"fresh clean crop failed validation: {path}")
    return {
        "candidate_count": count,
        "clean_local_count": count,
        "clean_context_count": count,
        "review_order": list(manifest["review_order"]),
    }


def _zip_package(package_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir).as_posix())


def build_review_package(
    paths: ReminePaths,
    selected: Sequence[dict[str, Any]],
    candidate_set_id: str,
    selection_digest: str,
    source_manifest_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    package_dir = paths.runtime_root / "review-package"
    crops_root = paths.runtime_root / "candidate-crops"
    package_dir.mkdir(parents=True, exist_ok=True)
    for candidate in selected:
        source_path = paths.repo_root / Path(*candidate["source_render_path"].split("/"))
        with Image.open(source_path) as image:
            image_size = image.size
        local_box, context_box = crop_boxes_for_candidate(candidate, image_size)
        candidate["local_crop_box_px"] = list(local_box)
        candidate["context_crop_box_px"] = list(context_box)
        local_crop = crops_root / "local" / f"{candidate['candidate_id']}.png"
        context_crop = crops_root / "context" / f"{candidate['candidate_id']}.png"
        local_size = _write_clean_crop(source_path, local_box, local_crop)
        context_size = _write_clean_crop(source_path, context_box, context_crop)
        package_local = package_dir / "assets" / "local" / f"{candidate['candidate_id']}.png"
        package_context = package_dir / "assets" / "context" / f"{candidate['candidate_id']}.png"
        package_local.parent.mkdir(parents=True, exist_ok=True)
        package_context.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_crop, package_local)
        shutil.copyfile(context_crop, package_context)
        candidate["markers"] = {
            "local": _marker(candidate, local_box, local_size),
            "context": _marker(candidate, context_box, context_size),
        }
        candidate["runtime_local_crop_path"] = str(local_crop.relative_to(paths.repo_root)).replace("\\", "/")
        candidate["runtime_context_crop_path"] = str(context_crop.relative_to(paths.repo_root)).replace("\\", "/")
    manifest = _build_fresh_manifest(
        selected,
        candidate_set_id,
        selection_digest,
        package_dir,
        source_manifest_hashes,
    )
    _write_json(package_dir / "manifest.json", manifest)
    (package_dir / "review.html").write_text(render_review_html(manifest), encoding="utf-8")
    (package_dir / "README.txt").write_text(
        "直接连续审核包 V1\n\n"
        "这是一个离线、无系统判断提示的两阶段审核包。\n"
        "第一步判断是否可以从 Fragment A 直接画一条直线到 Fragment B；只有第一步选择 DIRECT_STRAIGHT_CONTINUATION 时才出现第二步用途判断。\n"
        "审核结果可以导出并重新导入，尚未填写任何答案。\n\n"
        "PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED\n"
        "HUMAN_REVIEW: PENDING\n",
        encoding="utf-8",
    )
    validation = validate_review_package(package_dir)
    _zip_package(package_dir, paths.runtime_root / "review-package.zip")
    return manifest, validation


def _freeze_candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "review_index": candidate.get("review_index"),
        "selected_unit_id": candidate["selected_unit_id"],
        "source_family_id": candidate["source_family_id"],
        "source_document_id": candidate["source_document_id"],
        "source_type": candidate["source_type"],
        "source_render_path": candidate["source_render_path"],
        "page_or_view": candidate["page_or_view"],
        "orientation": candidate["orientation"],
        "fragment_a_geometry": candidate["fragment_a_geometry"],
        "fragment_b_geometry": candidate["fragment_b_geometry"],
        "gap_endpoint_a": candidate["gap_endpoint_a"],
        "gap_endpoint_b": candidate["gap_endpoint_b"],
        "gap_length_px": candidate["gap_length_px"],
        "local_crop_box_px": candidate.get("local_crop_box_px"),
        "context_crop_box_px": candidate.get("context_crop_box_px"),
    }


def selection_digest(selected: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "selection_code_version": SELECTION_CODE_VERSION,
        "base_checkpoint": BASE_CHECKPOINT,
        "review_protocol": PROTOCOL,
        "candidates": [_freeze_candidate_payload(candidate) for candidate in selected],
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _distribution(records: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(field, "UNKNOWN")) for record in records).items()))


def _gap_distribution(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(_gap_bin(float(record["gap_length_px"])) for record in records).items()))


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "source_families": len({record["source_family_id"] for record in records}),
        "source_documents": len({record["source_document_id"] for record in records}),
        "source_units": len({record["selected_unit_id"] for record in records}),
        "pdf_derived": sum(record.get("source_type") == "PDF" for record in records),
        "dwg_derived": sum(record.get("source_type") == "DWG" for record in records),
        "horizontal": sum(record.get("orientation") == "horizontal" for record in records),
        "vertical": sum(record.get("orientation") == "vertical" for record in records),
        "families": sorted({record["source_family_id"] for record in records}),
        "units": sorted({record["selected_unit_id"] for record in records}),
    }


def _old_pipeline_comparison(old_controls: Mapping[str, Any]) -> dict[str, Any]:
    records = list(old_controls["records"])
    totals = old_controls["dedup_totals"]
    raw = int(totals["raw_proposals"])
    legacy_filtered = int(totals.get("filtered_proposals", 0))
    post_dedup = int(totals["post_dedup_proposals"])
    duplicate_removed = max(0, raw - legacy_filtered - post_dedup)
    return {
        "pipeline_name": "OLD_LOCAL_D",
        "raw_proposal_count": raw,
        "ordinary_admissible_count": post_dedup,
        "uncertain_count": 0,
        "rejected_count": legacy_filtered,
        "legacy_geometry_filtered_count": legacy_filtered,
        "duplicate_removed_count": duplicate_removed,
        "duplicate_rate": round(duplicate_removed / max(1, raw), 6),
        "post_dedup_pool_count": post_dedup,
        "frozen_review_set_count": int(totals["frozen_candidates"]),
        "source_family_coverage": len({record["source_family_id"] for record in records}),
        "source_unit_coverage": len({record["selected_unit_id"] for record in records}),
        "orientation_distribution": _distribution(records, "orientation"),
        "gap_length_distribution": _gap_distribution(records),
        "selection_scope": "old post-dedup pool count; coverage/distributions from retained frozen 24",
        "coverage_scope": "old frozen 24; full post-dedup records were not retained in the tracked registry",
    }


def _fresh_pipeline_comparison(
    raw_proposals: Sequence[Mapping[str, Any]],
    ordinary_admissible_pool: Sequence[Mapping[str, Any]],
    selected: Sequence[Mapping[str, Any]],
    duplicate_removed: int,
    direct_counts: Mapping[str, int],
) -> dict[str, Any]:
    raw_count = len(raw_proposals)
    return {
        "pipeline_name": "FRESH_REMINE_V1",
        "raw_proposal_count": raw_count,
        "ordinary_admissible_count": len(ordinary_admissible_pool),
        "uncertain_count": int(direct_counts.get(DirectContinuationStatus.UNCERTAIN.value, 0)),
        "rejected_count": int(direct_counts.get(DirectContinuationStatus.REJECTED.value, 0)),
        "duplicate_removed_count": duplicate_removed,
        "duplicate_rate": round(duplicate_removed / max(1, raw_count), 6),
        "post_dedup_pool_count": len(ordinary_admissible_pool),
        "source_family_coverage": len({record["source_family_id"] for record in selected}),
        "source_unit_coverage": len({record["selected_unit_id"] for record in selected}),
        "orientation_distribution": _distribution(selected, "orientation"),
        "gap_length_distribution": _gap_distribution(selected),
        "selection_scope": "fresh post-dedup ordinary pool count; coverage/distributions from selected 24",
        "coverage_scope": "fresh selected review set",
    }


def _draw_segment(draw: ImageDraw.ImageDraw, segment: Mapping[str, Any], origin: tuple[int, int], color: tuple[int, int, int], width: int = 4) -> None:
    start = _point(segment["start"])
    end = _point(segment["end"])
    draw.line(
        (start[0] - origin[0], start[1] - origin[1], end[0] - origin[0], end[1] - origin[1]),
        fill=color,
        width=width,
    )


def _diagnostic_panel(example: Mapping[str, Any], repo_root: Path) -> Image.Image:
    source = repo_root / Path(*str(example["source_render_path"]).split("/"))
    with Image.open(source) as image:
        canvas = image.convert("RGB")
    if "candidate" in example:
        candidate = example["candidate"]
        points = [
            _point(candidate["fragment_a_geometry"]["start"]),
            _point(candidate["fragment_a_geometry"]["end"]),
            _point(candidate["fragment_b_geometry"]["start"]),
            _point(candidate["fragment_b_geometry"]["end"]),
            _point(candidate["gap_endpoint_a"]),
            _point(candidate["gap_endpoint_b"]),
        ]
    else:
        geometry = example["raw_geometry"]
        points = [_point(geometry["start"]), _point(geometry["end"])]
    x0, x1 = min(point[0] for point in points), max(point[0] for point in points)
    y0, y1 = min(point[1] for point in points), max(point[1] for point in points)
    margin = max(70, min(260, int(round(max(x1 - x0, y1 - y0) * 0.35))))
    box = _clip_box((x0 - margin, y0 - margin, x1 + margin + 1, y1 + margin + 1), canvas.size)
    crop = canvas.crop(box)
    origin = (box[0], box[1])
    draw = ImageDraw.Draw(crop)
    if "candidate" in example:
        candidate = example["candidate"]
        _draw_segment(draw, candidate["fragment_a_geometry"], origin, (220, 40, 40), 4)
        _draw_segment(draw, candidate["fragment_b_geometry"], origin, (30, 110, 220), 4)
        draw.line(
            (
                candidate["gap_endpoint_a"][0] - origin[0],
                candidate["gap_endpoint_a"][1] - origin[1],
                candidate["gap_endpoint_b"][0] - origin[0],
                candidate["gap_endpoint_b"][1] - origin[1],
            ),
            fill=(245, 180, 15),
            width=3,
        )
    else:
        _draw_segment(draw, example["raw_geometry"], origin, (220, 40, 40), 4)
    banner = Image.new("RGB", (crop.width, 34), (248, 248, 248))
    ImageDraw.Draw(banner).text(
        (8, 8),
        f"{example['kind']} · {example.get('status', '')} · {example.get('reason', '')}",
        fill=(35, 40, 50),
        font=_font(13),
    )
    output = Image.new("RGB", (crop.width, crop.height + banner.height), "white")
    output.paste(banner, (0, 0))
    output.paste(crop, (0, banner.height))
    return output


def _write_contact_sheet(
    selected: Sequence[Mapping[str, Any]], paths: ReminePaths
) -> None:
    columns = 4
    card_width, card_height = 560, 310
    rows = max(1, int(np.ceil(len(selected) / columns)))
    sheet = Image.new("RGB", (columns * card_width, rows * card_height), (232, 235, 239))
    for index, candidate in enumerate(selected):
        local_path = paths.repo_root / Path(*candidate["runtime_local_crop_path"].split("/"))
        context_path = paths.repo_root / Path(*candidate["runtime_context_crop_path"].split("/"))
        with Image.open(local_path) as local, Image.open(context_path) as context:
            local = local.convert("RGB")
            context = context.convert("RGB")
        panel = Image.new("RGB", (card_width, card_height), "white")
        for col, image in enumerate((local, context)):
            image.thumbnail((card_width // 2 - 12, card_height - 58), Image.Resampling.LANCZOS)
            panel.paste(image, (col * (card_width // 2) + (card_width // 2 - image.width) // 2, 28))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 7), f"{int(candidate['review_index']):02d}  {candidate['candidate_id']}", fill=(20, 25, 35), font=_font(14))
        draw.text((10, card_height - 24), "LOCAL" , fill=(75, 85, 95), font=_font(12))
        draw.text((card_width // 2 + 10, card_height - 24), "CONTEXT", fill=(75, 85, 95), font=_font(12))
        x = (index % columns) * card_width
        y = (index // columns) * card_height
        sheet.paste(panel, (x, y))
    sheet.save(
        paths.runtime_root / f"fresh-{len(selected)}-contact-sheet.png",
        format="PNG",
        optimize=True,
    )


def _write_diagnostic_sheet(examples: Sequence[Mapping[str, Any]], paths: ReminePaths) -> None:
    columns = 3
    card_width, card_height = 600, 360
    rows = max(1, int(np.ceil(len(examples) / columns)))
    sheet = Image.new("RGB", (columns * card_width, rows * card_height), (232, 235, 239))
    for index, example in enumerate(examples[:12]):
        panel = _diagnostic_panel(example, paths.repo_root)
        panel.thumbnail((card_width - 8, card_height - 8), Image.Resampling.LANCZOS)
        card = Image.new("RGB", (card_width, card_height), "white")
        card.paste(panel, ((card_width - panel.width) // 2, (card_height - panel.height) // 2))
        x = (index % columns) * card_width
        y = (index // columns) * card_height
        sheet.paste(card, (x, y))
    sheet.save(paths.runtime_root / "filtered-diagnostic-contact-sheet.png", format="PNG", optimize=True)


def _prepare_crop_boxes(paths: ReminePaths, candidates: Sequence[dict[str, Any]]) -> None:
    for candidate in candidates:
        source_path = paths.repo_root / Path(*candidate["source_render_path"].split("/"))
        with Image.open(source_path) as image:
            local_box, context_box = crop_boxes_for_candidate(candidate, image.size)
        candidate["local_crop_box_px"] = list(local_box)
        candidate["context_crop_box_px"] = list(context_box)


def _span_audit_payload(
    raw_records: Sequence[Mapping[str, Any]],
    buckets: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    by_id = {
        str(item["id"]): item
        for status in ("supported", "uncertain", "rejected")
        for item in buckets[status]
    }
    payload: list[dict[str, Any]] = []
    for raw in raw_records:
        qualified = by_id.get(str(raw["id"]))
        if qualified is None:
            continue
        record = {
            "raw_hough_id": raw["id"],
            "raw_geometry": raw["raw_geometry"],
            "canonical_geometry": raw.get("canonical_geometry"),
            "accepted_by_orientation_filter": raw.get("accepted_by_orientation_filter"),
            "span_integrity": qualified["span_integrity"],
            "axis_support_integrity": qualified["axis_support_integrity"],
            "primitive_integrity_bucket": qualified["primitive_integrity_bucket"],
        }
        if qualified["span_integrity"]["status"] == SpanIntegrityStatus.SUPPORTED.value:
            evidence = record["span_integrity"].get("evidence", {})
            record["span_integrity"] = {
                **record["span_integrity"],
                "evidence": {
                    key: value
                    for key, value in evidence.items()
                    if key not in {"samples", "runs"}
                },
            }
        axis_evidence = record["axis_support_integrity"].get("evidence", {})
        record["axis_support_integrity"] = {
            **record["axis_support_integrity"],
            "evidence": {
                key: value
                for key, value in axis_evidence.items()
                if key not in {"samples", "runs"}
            },
        }
        payload.append(record)
    return payload


def _selection_manifest(
    selected: Sequence[Mapping[str, Any]],
    candidate_set_id: str,
    digest: str,
    replay_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_code_version": SELECTION_CODE_VERSION,
        "base_checkpoint": BASE_CHECKPOINT,
        "candidate_count": len(selected),
        "review_order": [candidate["candidate_id"] for candidate in selected],
        "candidates": [_freeze_candidate_payload(candidate) for candidate in selected],
        "selection_deterministic_replay": replay_status,
        "selection_basis": [key for key, _weight in SELECTION_FEATURE_WEIGHTS],
        "machine_labels_used_for_selection": False,
        "model_run": "NO",
        "human_review": "PENDING",
    }


def _candidate_registry(
    selected: Sequence[Mapping[str, Any]], candidate_set_id: str, digest: str
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for candidate in selected:
        records.append(
            {
                **_freeze_candidate_payload(candidate),
                "selection_features": candidate["selection_features"],
                "local_density_fraction": candidate["local_density_fraction"],
                "frozen": True,
                "machine_verdict": None,
                "human_stage1": None,
                "human_stage2": None,
            }
        )
    return {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_code_version": SELECTION_CODE_VERSION,
        "base_checkpoint": BASE_CHECKPOINT,
        "protocol": PROTOCOL,
        "records": records,
        "counts": {
            "frozen_candidates": len(records),
            "machine_verdicts": 0,
            "human_stage1_answers": 0,
            "human_stage2_answers": 0,
        },
        "governance": {
            "source_authorization": "INTERNAL_PROJECT_DEVELOPMENT",
            "public_redistribution": "NOT_AUTHORIZED",
            "model_run": "NO",
            "validation": "NO",
            "locked_blind": "0 / 8",
            "h1_h2_opened": "NO",
        },
    }


def _markdown_report(
    funnel: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    paths: ReminePaths,
    tracked_report_path: Path,
    runtime_package: Path,
    test_summary: str = "Focused tests recorded separately after implementation.",
) -> str:
    def line(label: str, value: Any) -> str:
        return f"{label}: {value}"

    comparison = funnel["comparison"]
    selected_coverage = _coverage(selected)
    lines = [
        "# FRESH DEV CANDIDATE REMINING V1 — FINAL",
        "",
        "This report records a deterministic DEV-only remining after DIRECT_CONTINUATION_ADMISSIBILITY_V1, PRIMITIVE_SPAN_SUPPORT_INTEGRITY_V1, and PRIMITIVE_AXIS_SUPPORT_INTEGRITY_V1. It does not modify production semantics and does not perform human review.",
        "",
        "## Pipeline order",
        "",
        "SOURCE → DEV raw Hough primitives → SPAN_INTEGRITY_SUPPORTED plus PRIMITIVE_AXIS_SUPPORTED only → geometric A/B proposal → DIRECT_CONTINUATION_ADMISSIBLE only → duplicate exclusion → deterministic source/geometry diversity selection.",
        "",
        "Uncertain and rejected span/axis primitives and direct-continuation pairs remain in ignored runtime audit records and never enter the ordinary admissible pool.",
        "",
        "## Funnel",
        "",
    ]
    funnel_labels = (
        ("AUTHORIZED ELIGIBLE SOURCE UNITS", "authorized_eligible_source_units"),
        ("SOURCE UNITS ACTUALLY MINED", "source_units_actually_mined"),
        ("PAGES / VIEWS CONSIDERED", "pages_views_considered"),
        ("RAW HOUGH PRIMITIVES", "raw_hough_primitives"),
        ("SPAN_INTEGRITY_SUPPORTED", "span_integrity_supported"),
        ("SPAN_INTEGRITY_UNCERTAIN", "span_integrity_uncertain"),
        ("SPAN_INTEGRITY_REJECTED", "span_integrity_rejected"),
        ("AXIS_SUPPORT_SUPPORTED", "axis_support_supported"),
        ("AXIS_SUPPORT_UNCERTAIN", "axis_support_uncertain"),
        ("AXIS_SUPPORT_REJECTED", "axis_support_rejected"),
        ("PRIMITIVE_INTEGRITY_SUPPORTED", "primitive_integrity_supported"),
        ("PRIMITIVE_INTEGRITY_UNCERTAIN", "primitive_integrity_uncertain"),
        ("PRIMITIVE_INTEGRITY_REJECTED", "primitive_integrity_rejected"),
        ("RAW PAIR PROPOSALS", "raw_geometric_ab_proposals"),
        ("DIRECT_CONTINUATION_ADMISSIBLE", "direct_continuation_admissible"),
        ("DIRECT_CONTINUATION_UNCERTAIN", "direct_continuation_uncertain"),
        ("DIRECT_CONTINUATION_REJECTED", "direct_continuation_rejected"),
        ("OLD FROZEN EXACT DUPLICATES REMOVED", "old_frozen_exact_duplicates_removed"),
        ("OLD FROZEN NEAR-DUPLICATES REMOVED", "old_frozen_near_duplicates_removed"),
        ("NEW-POOL DUPLICATES REMOVED", "new_pool_duplicates_removed"),
        ("FRESH ADMISSIBLE POOL", "fresh_admissible_pool"),
        ("FRESH REVIEW SET", "fresh_review_set"),
    )
    for label, key in funnel_labels:
        lines.append(line(label, funnel[key]))
    lines.extend(
        [
            "",
            "## Mechanical OLD LOCAL-D versus FRESH REMINE V1 comparison",
            "",
            "| Metric | OLD LOCAL-D | FRESH REMINE V1 |",
            "|---|---:|---:|",
            f"| Raw proposal count | {comparison['OLD_LOCAL_D']['raw_proposal_count']} | {comparison['FRESH_REMINE_V1']['raw_proposal_count']} |",
            f"| Ordinary admissible count | {comparison['OLD_LOCAL_D']['ordinary_admissible_count']} | {comparison['FRESH_REMINE_V1']['ordinary_admissible_count']} |",
            f"| Uncertain count | {comparison['OLD_LOCAL_D']['uncertain_count']} | {comparison['FRESH_REMINE_V1']['uncertain_count']} |",
            f"| Rejected count | {comparison['OLD_LOCAL_D']['rejected_count']} | {comparison['FRESH_REMINE_V1']['rejected_count']} |",
            f"| Duplicate rate | {comparison['OLD_LOCAL_D']['duplicate_rate']} | {comparison['FRESH_REMINE_V1']['duplicate_rate']} |",
            f"| Source-family coverage | {comparison['OLD_LOCAL_D']['source_family_coverage']} | {comparison['FRESH_REMINE_V1']['source_family_coverage']} |",
            f"| Source-unit coverage | {comparison['OLD_LOCAL_D']['source_unit_coverage']} | {comparison['FRESH_REMINE_V1']['source_unit_coverage']} |",
            f"| Orientation distribution | `{json.dumps(comparison['OLD_LOCAL_D']['orientation_distribution'], sort_keys=True)}` | `{json.dumps(comparison['FRESH_REMINE_V1']['orientation_distribution'], sort_keys=True)}` |",
            f"| Gap-length distribution | `{json.dumps(comparison['OLD_LOCAL_D']['gap_length_distribution'], sort_keys=True)}` | `{json.dumps(comparison['FRESH_REMINE_V1']['gap_length_distribution'], sort_keys=True)}` |",
            "",
            "OLD LOCAL-D ordinary admissible count is its tracked 225-record post-dedup pool; its 96 rejected proposals are legacy geometry-filtered records and its retained coverage/distributions are available only for the frozen 24. FRESH REMINE V1 ordinary admissible count is the 147-record post-guard, post-dedup pool; its rejected count is the current direct-continuation rejected count and its coverage/distributions are from the selected 24.",
            "",
            "The comparison is mechanical. Before human review, it does not establish semantic precision or accuracy. The fresh path is structurally more selective only in the sense represented by its explicit span/direct status counts and duplicate accounting.",
            "",
            "## Frozen set and review package",
            "",
            line("CANDIDATE SET ID", funnel["candidate_set_id"]),
            line("SELECTION DIGEST", funnel["selection_digest"]),
            line("SELECTION CODE VERSION", SELECTION_CODE_VERSION),
            line("SOURCE FAMILIES REPRESENTED", selected_coverage["source_families"]),
            line("SOURCE UNITS REPRESENTED", selected_coverage["source_units"]),
            line("PDF-DERIVED", selected_coverage["pdf_derived"]),
            line("DWG-DERIVED", selected_coverage["dwg_derived"]),
            line("HORIZONTAL", selected_coverage["horizontal"]),
            line("VERTICAL", selected_coverage["vertical"]),
            line("SELECTION DETERMINISTIC REPLAY", funnel["selection_deterministic_replay"]),
            line("RUNTIME REVIEW PACKAGE", runtime_package),
            line("TRACKED REPORT", tracked_report_path),
            "",
            "## Governance",
            "",
            "- PRODUCTION_SEMANTIC_DELTA: NONE",
            "- SPAN GUARD ACTIVE: YES",
            "- ADMISSIBILITY GUARD ACTIVE: YES",
            "- GUARD WEAKENING: NO",
            "- MACHINE VERDICT EXPOSED TO REVIEWER: NO",
            "- MODEL RUN: NO",
            "- MODEL-ASSISTED LABELING: NO",
            "- MODEL_BAKE_OFF_SHOULD_RESUME: NO",
            "- VALIDATION: NO",
            "- LOCKED_BLIND: 0 / 8",
            "- H1/H2 OPENED: NO",
            "- HUMAN REVIEW: PENDING",
            "- OLD FROZEN CASES REUSED: 0",
            "- OLD NEAR-DUPLICATES REUSED: 0",
            "",
            "## Verification",
            "",
            test_summary,
            "",
            "Source-derived crops, contact sheets, and the static package remain under ignored local-artifacts. No source-derived imagery or human labels are tracked.",
            "",
            "FRESH_DEV_CANDIDATE_REMINING_V1: COMPLETE",
            "",
        ]
    )
    return "\n".join(lines)


def replay_frozen_selection(runtime_path: Path, selection_manifest_path: Path) -> dict[str, Any]:
    """Replay only the deterministic selection step from persisted runtime data."""

    runtime = _read_json(Path(runtime_path))
    manifest = _read_json(Path(selection_manifest_path))
    pool = [dict(item) for item in runtime["deduplicated_admissible_pool"]]
    replayed, _trace = select_diverse_candidates(pool, max_count=int(manifest["candidate_count"]))
    # Crop mapping is deterministic but is not needed to compare order/identity.
    expected_ids = list(manifest["review_order"])
    actual_ids = [item["candidate_id"] for item in replayed]
    return {
        "selection_code_version": SELECTION_CODE_VERSION,
        "candidate_set_id": manifest["candidate_set_id"],
        "expected_review_order": expected_ids,
        "replayed_review_order": actual_ids,
        "selected_ids_equal": actual_ids == expected_ids,
        "selection_digest": manifest["selection_digest"],
        "status": "PASS" if actual_ids == expected_ids else "FAIL",
    }


def run_fresh_remine(
    repo_root: Path,
    *,
    replace_runtime: bool = False,
    test_summary: str = "Focused tests recorded separately after implementation.",
) -> dict[str, Any]:
    """Run the guarded DEV remine, freeze selection, and build the package."""

    paths = ReminePaths.for_repo(repo_root)
    units, source_manifest_hashes = load_authorized_source_units(paths.repo_root)
    old_controls = load_old_frozen_controls(paths.repo_root)
    if paths.runtime_root.exists():
        if not replace_runtime:
            raise FileExistsError(
                f"fresh runtime exists; pass replace_runtime=True: {paths.runtime_root}"
            )
        _safe_replace_runtime(paths.runtime_root)
    paths.runtime_root.mkdir(parents=True, exist_ok=True)

    all_admissible: list[dict[str, Any]] = []
    all_direct_filtered: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    span_examples: list[dict[str, Any]] = []
    primitive_audit_paths: list[str] = []
    total_raw = total_oriented = 0
    span_counts: Counter[str] = Counter()
    axis_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    straight_counts: Counter[str] = Counter()
    primitive_counts: Counter[str] = Counter()
    direct_counts: Counter[str] = Counter()
    raw_pair_proposals: list[dict[str, Any]] = []

    for unit in units:
        source_path = paths.repo_root / Path(*unit["source_render_path"].split("/"))
        gray = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise OSError(f"could not read authorized Local-D render: {source_path}")
        _binary, raw_records = _raw_hough(gray)
        oriented = [record for record in raw_records if record["accepted_by_orientation_filter"]]
        buckets = qualify_dev_hough_primitives_cached(gray, oriented)
        text_buckets = qualify_dev_text_support_primitives(gray, buckets["supported"])
        text_eligible = list(text_buckets["independent"]) + list(text_buckets["uncertain"])
        straight_buckets = qualify_dev_straight_primitives(gray, text_eligible)
        total_raw += len(raw_records)
        total_oriented += len(oriented)
        for bucket_name in ("supported", "uncertain", "rejected"):
            primitive_counts[bucket_name] += len(buckets[bucket_name])
            for item in buckets[bucket_name]:
                span_decision = item["span_integrity"]
                axis_decision = item["axis_support_integrity"]
                span_counts[span_decision["status"]] += 1
                axis_counts[axis_decision["status"]] += 1
                if bucket_name == "supported":
                    continue
                failed = (
                    axis_decision
                    if axis_decision["status"]
                    != AxisSupportStatus.SUPPORTED.value
                    else span_decision
                )
                span_examples.append(
                    {
                        "kind": "PRIMITIVE_INTEGRITY_FILTERED",
                        "status": failed["status"],
                        "reason": failed["reason"],
                        "source_render_path": unit["source_render_path"],
                        "raw_geometry": item["raw_geometry"],
                        "raw_hough_id": item["id"],
                    }
                )
        audit_path = paths.runtime_root / "raw-primitive-audit" / f"{unit['selected_unit_id']}.json"
        _write_json(
            audit_path,
            {
                "schema_version": 1,
                "selected_unit_id": unit["selected_unit_id"],
                "source_render_path": unit["source_render_path"],
                "raw_hough_count": len(raw_records),
                "orientation_eligible_count": len(oriented),
                "records": _span_audit_payload(oriented, buckets),
                "text_support_integrity": {
                    item["id"]: item["text_support_integrity"]
                    for status in text_buckets.values()
                    for item in status
                },
                "straight_primitive_validity": {
                    item["id"]: item["straight_primitive_validity"]
                    for status in straight_buckets.values()
                    for item in status
                },
            },
        )
        primitive_audit_paths.append(str(audit_path.relative_to(paths.repo_root)).replace("\\", "/"))
        for bucket_name, status in (
            ("independent", TextSupportStatus.INDEPENDENT.value),
            ("uncertain", TextSupportStatus.UNCERTAIN.value),
            ("rejected", TextSupportStatus.REJECTED.value),
        ):
            text_counts[status] += len(text_buckets[bucket_name])
        for bucket_name, status in (
            ("supported", StraightValidityStatus.SUPPORTED.value),
            ("uncertain", StraightValidityStatus.UNCERTAIN.value),
            ("rejected", StraightValidityStatus.REJECTED.value),
        ):
            straight_counts[status] += len(straight_buckets[bucket_name])
        straight_eligible = list(straight_buckets["supported"]) + list(
            straight_buckets["uncertain"]
        )
        text_by_raw_id = {
            item["id"]: item["text_support_integrity"] for item in straight_eligible
        }
        straight_by_raw_id = {
            item["id"]: item["straight_primitive_validity"] for item in straight_eligible
        }
        normalized = normalize_hough_records(straight_eligible)
        for item in normalized:
            ancestor_profiles = [
                text_by_raw_id[ancestor]
                for ancestor in item.get("raw_ancestor_ids", [])
                if ancestor in text_by_raw_id
            ]
            item["text_support_integrity"] = {
                "status": (
                    TextSupportStatus.UNCERTAIN.value
                    if any(
                        profile.get("status") == TextSupportStatus.UNCERTAIN.value
                        for profile in ancestor_profiles
                    )
                    else TextSupportStatus.INDEPENDENT.value
                ),
                "raw_ancestor_profiles": ancestor_profiles,
            }
            straight_ancestor_profiles = [
                straight_by_raw_id[ancestor]
                for ancestor in item.get("raw_ancestor_ids", [])
                if ancestor in straight_by_raw_id
            ]
            item["straight_primitive_validity"] = {
                "status": (
                    StraightValidityStatus.UNCERTAIN.value
                    if any(
                        profile.get("status")
                        == StraightValidityStatus.UNCERTAIN.value
                        for profile in straight_ancestor_profiles
                    )
                    else StraightValidityStatus.SUPPORTED.value
                ),
                "raw_ancestor_profiles": straight_ancestor_profiles,
            }
        proposals, pair_summary = propose_geometric_pairs(normalized, unit)
        raw_pair_proposals.extend(proposals)
        admissible, filtered, unit_direct_counts = apply_direct_continuation_guard(gray, proposals)
        for status, count in unit_direct_counts.items():
            direct_counts[status] += count
        for candidate in admissible:
            all_admissible.append(add_selection_features(candidate, gray))
        all_direct_filtered.extend(filtered)
        source_summaries.append(
            {
                "selected_unit_id": unit["selected_unit_id"],
                "source_family_id": unit["source_family_id"],
                "source_type": unit["source_type"],
                "raw_hough_primitives": len(raw_records),
                "orientation_eligible_raw_hough_primitives": len(oriented),
                "span_integrity_supported": sum(
                    item["span_integrity"]["status"]
                    == SpanIntegrityStatus.SUPPORTED.value
                    for status in buckets.values()
                    for item in status
                ),
                "span_integrity_uncertain": sum(
                    item["span_integrity"]["status"]
                    == SpanIntegrityStatus.UNCERTAIN.value
                    for status in buckets.values()
                    for item in status
                ),
                "span_integrity_rejected": sum(
                    item["span_integrity"]["status"]
                    == SpanIntegrityStatus.REJECTED.value
                    for status in buckets.values()
                    for item in status
                ),
                "axis_support_supported": sum(
                    item["axis_support_integrity"]["status"]
                    == AxisSupportStatus.SUPPORTED.value
                    for status in buckets.values()
                    for item in status
                ),
                "axis_support_uncertain": sum(
                    item["axis_support_integrity"]["status"]
                    == AxisSupportStatus.UNCERTAIN.value
                    for status in buckets.values()
                    for item in status
                ),
                "axis_support_rejected": sum(
                    item["axis_support_integrity"]["status"]
                    == AxisSupportStatus.REJECTED.value
                    for status in buckets.values()
                    for item in status
                ),
                "primitive_integrity_supported": len(buckets["supported"]),
                "primitive_integrity_uncertain": len(buckets["uncertain"]),
                "primitive_integrity_rejected": len(buckets["rejected"]),
                "text_support_independent": len(text_buckets["independent"]),
                "text_support_uncertain": len(text_buckets["uncertain"]),
                "text_support_rejected": len(text_buckets["rejected"]),
                "straight_validity_supported": len(straight_buckets["supported"]),
                "straight_validity_uncertain": len(straight_buckets["uncertain"]),
                "straight_validity_rejected": len(straight_buckets["rejected"]),
                "normalized_supported_primitives": len(normalized),
                **pair_summary,
                "direct_continuation_admissible": len(admissible),
                "direct_continuation_uncertain": unit_direct_counts.get(DirectContinuationStatus.UNCERTAIN.value, 0),
                "direct_continuation_rejected": unit_direct_counts.get(DirectContinuationStatus.REJECTED.value, 0),
            }
        )

    old_filtered_pool, old_filtered, old_filter_counts = filter_against_old_frozen(
        all_admissible, old_controls
    )
    new_pool, new_filtered, new_duplicate_count = deduplicate_new_pool(old_filtered_pool)
    selected, selection_info = select_diverse_candidates(new_pool, max_count=MAX_REVIEW_COUNT)
    _prepare_crop_boxes(paths, selected)
    digest = selection_digest(selected)
    candidate_set_id = f"{CANDIDATE_SET_NAME}-{digest[:12].upper()}"

    replayed, _replay_trace = select_diverse_candidates(new_pool, max_count=MAX_REVIEW_COUNT)
    replay_ids = [item["candidate_id"] for item in replayed]
    selected_ids = [item["candidate_id"] for item in selected]
    replay_status = "PASS" if replay_ids == selected_ids else "FAIL"

    package_manifest, package_validation = build_review_package(
        paths,
        selected,
        candidate_set_id,
        digest,
        source_manifest_hashes,
    )

    other_filtered = old_filtered + new_filtered
    direct_examples = sorted(
        all_direct_filtered,
        key=lambda item: (item["selected_unit_id"], item["geometry_signature"]),
    )
    diagnostic_examples: list[dict[str, Any]] = []
    diagnostic_examples.extend(sorted(span_examples, key=lambda item: (item["source_render_path"], item["raw_hough_id"]))[:4])
    diagnostic_examples.extend(
        [
            {
                "kind": "DIRECT_FILTERED",
                "status": item["direct_continuation"]["status"],
                "reason": item["direct_continuation"]["reason"],
                "source_render_path": item["source_render_path"],
                "candidate": item,
            }
            for item in direct_examples[:4]
        ]
    )
    diagnostic_examples.extend(
        [
            {
                "kind": "OTHER_FILTERED",
                "status": item.get("filter_stage", "FILTERED"),
                "reason": item.get("filter_stage", "FILTERED"),
                "source_render_path": item["source_render_path"],
                "candidate": item,
            }
            for item in other_filtered[:4]
            if "fragment_a_geometry" in item
        ]
    )
    _write_contact_sheet(selected, paths)
    _write_diagnostic_sheet(diagnostic_examples[:12], paths)

    total_duplicates = sum(old_filter_counts.values()) + new_duplicate_count
    fresh_pool_comparison = _fresh_pipeline_comparison(
        raw_pair_proposals,
        new_pool,
        selected,
        new_duplicate_count,
        direct_counts,
    )
    old_comparison = _old_pipeline_comparison(old_controls)
    actual_pool_count = len(new_pool)
    funnel: dict[str, Any] = {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "base_checkpoint": BASE_CHECKPOINT,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_code_version": SELECTION_CODE_VERSION,
        "authorized_eligible_source_units": len(units),
        "source_units_actually_mined": len(source_summaries),
        "pages_views_considered": len(source_summaries),
        "raw_hough_primitives": total_raw,
        "orientation_eligible_raw_hough_primitives": total_oriented,
        "span_integrity_supported": span_counts[SpanIntegrityStatus.SUPPORTED.value],
        "span_integrity_uncertain": span_counts[SpanIntegrityStatus.UNCERTAIN.value],
        "span_integrity_rejected": span_counts[SpanIntegrityStatus.REJECTED.value],
        "axis_support_supported": axis_counts[AxisSupportStatus.SUPPORTED.value],
        "axis_support_uncertain": axis_counts[AxisSupportStatus.UNCERTAIN.value],
        "axis_support_rejected": axis_counts[AxisSupportStatus.REJECTED.value],
        "primitive_integrity_supported": primitive_counts["supported"],
        "primitive_integrity_uncertain": primitive_counts["uncertain"],
        "primitive_integrity_rejected": primitive_counts["rejected"],
        "text_support_independent": text_counts[TextSupportStatus.INDEPENDENT.value],
        "text_support_uncertain": text_counts[TextSupportStatus.UNCERTAIN.value],
        "text_support_rejected": text_counts[TextSupportStatus.REJECTED.value],
        "straight_validity_supported": straight_counts[StraightValidityStatus.SUPPORTED.value],
        "straight_validity_uncertain": straight_counts[StraightValidityStatus.UNCERTAIN.value],
        "straight_validity_rejected": straight_counts[StraightValidityStatus.REJECTED.value],
        "raw_geometric_ab_proposals": len(raw_pair_proposals),
        "direct_continuation_admissible": direct_counts[DirectContinuationStatus.ADMISSIBLE.value],
        "direct_continuation_uncertain": direct_counts[DirectContinuationStatus.UNCERTAIN.value],
        "direct_continuation_rejected": direct_counts[DirectContinuationStatus.REJECTED.value],
        "old_frozen_exact_duplicates_removed": old_filter_counts["old_frozen_exact_duplicates_removed"],
        "old_frozen_near_duplicates_removed": old_filter_counts["old_frozen_near_duplicates_removed"],
        "new_pool_duplicates_removed": new_duplicate_count,
        "fresh_admissible_pool": actual_pool_count,
        "fresh_review_set": len(selected),
        "fresh_pool_insufficient": actual_pool_count < MAX_REVIEW_COUNT,
        "selection_deterministic_replay": replay_status,
        "candidate_set_runtime": str((paths.runtime_root / "candidate-set-runtime.json").relative_to(paths.repo_root)).replace("\\", "/"),
        "review_package_runtime": str((paths.runtime_root / "review-package").relative_to(paths.repo_root)).replace("\\", "/"),
        "source_summaries": source_summaries,
        "comparison": {
            "OLD_LOCAL_D": old_comparison,
            "FRESH_REMINE_V1": fresh_pool_comparison,
        },
        "governance": {
            "production_semantic_delta": "NONE",
            "span_guard_active": True,
            "text_glyph_integrity_guard_active": True,
            "straight_primitive_validity_guard_active": True,
            "admissibility_guard_active": True,
            "guard_weakening": False,
            "model_run": "NO",
            "model_assisted_labeling": "NO",
            "validation": "NO",
            "locked_blind": "0 / 8",
            "h1_h2_opened": "NO",
            "human_review": "PENDING",
        },
    }
    runtime_payload = {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "base_checkpoint": BASE_CHECKPOINT,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_code_version": SELECTION_CODE_VERSION,
        "funnel": funnel,
        "deduplicated_admissible_pool": new_pool,
        "direct_filtered_audit": all_direct_filtered,
        "old_and_new_filtered_samples": other_filtered,
        "diagnostic_examples": diagnostic_examples[:12],
        "raw_primitive_audit_paths": primitive_audit_paths,
        "selection_info": selection_info,
        "selected_candidates": [_freeze_candidate_payload(candidate) for candidate in selected],
    }
    runtime_path = paths.runtime_root / "candidate-set-runtime.json"
    _write_json(runtime_path, runtime_payload)
    selection_replay = {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "selection_code_version": SELECTION_CODE_VERSION,
        "candidate_set_id": candidate_set_id,
        "expected_review_order": selected_ids,
        "replayed_review_order": replay_ids,
        "selected_ids_equal": replay_ids == selected_ids,
        "order_equal": replay_ids == selected_ids,
        "selection_digest": digest,
        "status": replay_status,
    }
    _write_json(paths.runtime_root / "selection-replay.json", selection_replay)

    tracked_registry = _candidate_registry(selected, candidate_set_id, digest)
    tracked_manifest = _selection_manifest(selected, candidate_set_id, digest, replay_status)
    package_manifest_hash = _sha256_file(paths.runtime_root / "review-package" / "manifest.json")
    tracked_package_manifest = {
        "schema_version": 1,
        "task_id": CANDIDATE_SET_NAME,
        "package_id": PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(selected),
        "review_order": selected_ids,
        "runtime_package_path": str((paths.runtime_root / "review-package").relative_to(paths.repo_root)).replace("\\", "/"),
        "runtime_package_manifest_sha256": package_manifest_hash,
        "runtime_package_validation": package_validation,
        "machine_verdict_exposed_to_reviewer": False,
        "human_review": "PENDING",
    }
    _write_json(paths.tracked_root / "fresh-candidate-registry.json", tracked_registry)
    _write_json(paths.tracked_root / "fresh-selection-manifest.json", tracked_manifest)
    _write_json(paths.tracked_root / "fresh-mining-funnel.json", funnel)
    _write_json(paths.tracked_root / "review-package-manifest.json", tracked_package_manifest)
    report_path = paths.tracked_root / "FRESH-DEV-CANDIDATE-REMINING-V1-FINAL.md"
    report = _markdown_report(
        funnel,
        selected,
        paths,
        report_path,
        paths.runtime_root / "review-package",
        test_summary,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return {
        "paths": paths,
        "units": units,
        "funnel": funnel,
        "selected": selected,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_replay": selection_replay,
        "package_manifest": package_manifest,
        "package_validation": package_validation,
        "report_path": report_path,
    }


__all__ = [
    "BASE_CHECKPOINT",
    "CANDIDATE_SET_NAME",
    "DEFAULT_THRESHOLDS",
    "GEOMETRY_QUANTUM",
    "MAX_REVIEW_COUNT",
    "PACKAGE_ID",
    "PROTOCOL",
    "ReminePaths",
    "SELECTION_CODE_VERSION",
    "STAGE1_VALUES",
    "STAGE2_VALUES",
    "add_selection_features",
    "apply_direct_continuation_guard",
    "build_review_package",
    "crop_boxes_for_candidate",
    "deduplicate_new_pool",
    "filter_against_old_frozen",
    "geometry_signature",
    "load_authorized_source_units",
    "load_old_frozen_controls",
    "replay_frozen_selection",
    "run_fresh_remine",
    "select_diverse_candidates",
    "selection_digest",
    "validate_review_export",
    "validate_review_package",
]
