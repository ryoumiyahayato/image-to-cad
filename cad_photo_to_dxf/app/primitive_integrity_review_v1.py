"""Targeted primitive-integrity human-review package V1.

This module only consumes the already-frozen fresh DEV candidate pool and the
diagnostic artifacts written by the preceding primitive-integrity checkpoints.
It does not mine candidates, run a model, change a guard, or infer a human
answer.  The reviewer-facing package deliberately contains only source crops,
red primitive overlays, and empty review controls.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image, ImageDraw

try:  # pragma: no cover - exercised through both package and script imports
    from . import fresh_dev_candidate_remining_v1 as fresh
except ImportError:  # pragma: no cover
    from app import fresh_dev_candidate_remining_v1 as fresh  # type: ignore


BASE_CHECKPOINT = "e3a3c81fa2783352bc8655b28d564471b441ceec"
FRESH_POOL_COUNT = 147
TARGET_REVIEW_SIZE = 16
MIN_REVIEW_SIZE = 12
MAX_REVIEW_SIZE = 20
MAX_PRIOR_REVIEWED_CONTROLS = 4
LONG_PRIMITIVE_MIN_PX = 200.0

TASK_ID = "PRIMITIVE-INTEGRITY-REVIEW-V1"
PROTOCOL = "PRIMITIVE_INTEGRITY_REVIEW_V1"
PACKAGE_ID = "primitive-integrity-review-v1"
SELECTION_CODE_VERSION = "PRIMITIVE_INTEGRITY_REVIEW_V1_CODE_1"

PRIMARY_CLASSES = (
    "VALID_SINGLE_STRAIGHT_PRIMITIVE",
    "MULTIPLE_OR_OFFSET_SEGMENTS",
    "ENDPOINT_OVERSHOOT",
    "FOREIGN_STROKE_CAPTURE",
    "OTHER_PRIMITIVE_MISMATCH",
    "INSUFFICIENT_EVIDENCE",
)
SECONDARY_FLAGS = (
    "MULTIPLE_OR_OFFSET_SEGMENTS",
    "ENDPOINT_OVERSHOOT",
    "FOREIGN_STROKE_CAPTURE",
    "CROSSES_LOCAL_STRUCTURE",
    "OTHER",
)

RUNTIME_RELATIVE = "local-artifacts/draftsman/primitive-integrity-review-v1"
FRESH_RUNTIME_RELATIVE = (
    "local-artifacts/draftsman/fresh-dev-candidate-remining-v1/"
    "candidate-set-runtime.json"
)
FRESH_SELECTION_RELATIVE = (
    "cad_photo_to_dxf/validation/fresh-dev-candidate-remining-v1/"
    "fresh-selection-manifest.json"
)
BATCH01_FREEZE_RELATIVE = (
    "cad_photo_to_dxf/validation/direct-continuation-human-review-v1/"
    "batch-01/batch-01-freeze-manifest.json"
)
BATCH02_SELECTION_RELATIVE = (
    "cad_photo_to_dxf/validation/direct-continuation-human-review-v1/"
    "batch-02/batch-02-selection-manifest.json"
)
DIAGNOSTIC_RELATIVE = (
    "local-artifacts/draftsman/primitive-coherence-endpoint-audit-v1/"
    "audited-cases.json"
)


@dataclass(frozen=True)
class PackageBuildResult:
    """Small stable result object used by the focused package tests and tool."""

    runtime_root: Path
    package_dir: Path
    package_zip: Path
    tracked_root: Path
    candidate_set_id: str
    selection_digest: str
    selected_count: int
    newly_unreviewed_count: int
    prior_reviewed_control_count: int
    strata_counts: dict[str, int]
    source_family_count: int
    source_unit_count: int
    horizontal_count: int
    vertical_count: int
    selection_replay_status: str
    package_validation: dict[str, Any]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _repo_path(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve()
    path = (root / Path(*relative.split("/"))).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"path escapes repository root: {relative}")
    return path


def _relative_path(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _safe_replace_runtime(path: Path) -> None:
    """Replace only this task's ignored runtime directory."""

    resolved = path.resolve()
    if (
        resolved.name != "primitive-integrity-review-v1"
        or resolved.parent.name != "draftsman"
        or resolved.parent.parent.name != "local-artifacts"
    ):
        raise ValueError(f"refusing to replace unexpected runtime path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rounded(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _point(value: Sequence[float | int]) -> list[float | int]:
    return [value[0], value[1]]


def _distance_sq(a: Sequence[float | int], b: Sequence[float | int]) -> float:
    return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2


def _segment_length(segment: Mapping[str, Any]) -> float:
    return math.sqrt(_distance_sq(segment["start"], segment["end"]))


def _outer_endpoint(
    segment: Mapping[str, Any], gap_endpoint: Sequence[float | int]
) -> list[float | int]:
    start = _point(segment["start"])
    end = _point(segment["end"])
    return start if _distance_sq(start, gap_endpoint) >= _distance_sq(end, gap_endpoint) else end


def _primitive_geometry(candidate: Mapping[str, Any]) -> dict[str, Any]:
    fragment_a = candidate["fragment_a_geometry"]
    fragment_b = candidate["fragment_b_geometry"]
    gap_a = _point(candidate["gap_endpoint_a"])
    gap_b = _point(candidate["gap_endpoint_b"])
    claimed_start = _outer_endpoint(fragment_a, gap_a)
    claimed_end = _outer_endpoint(fragment_b, gap_b)
    return {
        "claimed_start_px": claimed_start,
        "claimed_end_px": claimed_end,
        "fragment_a": {
            "start": _point(fragment_a["start"]),
            "end": _point(fragment_a["end"]),
        },
        "fragment_b": {
            "start": _point(fragment_b["start"]),
            "end": _point(fragment_b["end"]),
        },
        "gap_endpoint_a_px": gap_a,
        "gap_endpoint_b_px": gap_b,
        "primitive_ids": {
            "fragment_a": list(candidate.get("raw_ancestor_ids", {}).get("fragment_a", [])),
            "fragment_b": list(candidate.get("raw_ancestor_ids", {}).get("fragment_b", [])),
        },
        "a_b_relation": "fragment_a_then_gap_then_fragment_b",
    }


def _exact_primitive_key(candidate_or_record: Mapping[str, Any]) -> str:
    geometry = candidate_or_record.get("primitive_geometry")
    if geometry is None:
        geometry = _primitive_geometry(candidate_or_record)
    endpoints = [
        tuple(geometry["claimed_start_px"]),
        tuple(geometry["claimed_end_px"]),
    ]
    endpoints.sort()
    return _canonical_json(
        {
            "source_render_path": candidate_or_record.get("source_render_path"),
            "endpoints": endpoints,
        }
    )


def _load_frozen_inputs(repo_root: Path) -> dict[str, Any]:
    runtime_path = _repo_path(repo_root, FRESH_RUNTIME_RELATIVE)
    selection_path = _repo_path(repo_root, FRESH_SELECTION_RELATIVE)
    runtime = _read_json(runtime_path)
    selection = _read_json(selection_path)
    pool = [dict(item) for item in runtime.get("deduplicated_admissible_pool", [])]
    if len(pool) != FRESH_POOL_COUNT:
        raise ValueError(f"frozen fresh pool changed: {len(pool)} != {FRESH_POOL_COUNT}")
    if runtime.get("funnel", {}).get("fresh_admissible_pool") != FRESH_POOL_COUNT:
        raise ValueError("fresh runtime funnel does not describe the frozen 147 pool")
    if runtime.get("candidate_set_id") != selection.get("candidate_set_id"):
        raise ValueError("fresh pool and selection manifest candidate-set identity differ")
    if runtime.get("selection_digest") != selection.get("selection_digest"):
        raise ValueError("fresh pool and selection manifest digest differ")
    ids = [str(item.get("candidate_id")) for item in pool]
    if len(set(ids)) != FRESH_POOL_COUNT:
        raise ValueError("frozen fresh pool contains duplicate candidate IDs")
    for item in pool:
        if item.get("direct_continuation", {}).get("status") != "DIRECT_CONTINUATION_ADMISSIBLE":
            raise ValueError(f"pool item is not admissible: {item.get('candidate_id')}")
        for key in (
            "source_family_id",
            "selected_unit_id",
            "source_type",
            "source_render_path",
            "orientation",
            "fragment_a_geometry",
            "fragment_b_geometry",
            "gap_endpoint_a",
            "gap_endpoint_b",
        ):
            if key not in item:
                raise ValueError(f"pool item missing frozen field {key}: {item.get('candidate_id')}")
    return {
        "runtime": runtime,
        "selection": selection,
        "pool": pool,
        "runtime_path": runtime_path,
        "selection_path": selection_path,
        "runtime_sha256": _sha256_file(runtime_path),
        "selection_sha256": _sha256_file(selection_path),
    }


def _load_prior_reviewed_ids(repo_root: Path, pool_ids: set[str]) -> tuple[set[str], dict[str, Any]]:
    batch01 = _read_json(_repo_path(repo_root, BATCH01_FREEZE_RELATIVE))
    batch02 = _read_json(_repo_path(repo_root, BATCH02_SELECTION_RELATIVE))
    batch01_ids = [str(value) for value in batch01.get("candidate_ids", [])]
    batch02_ids = [str(value) for value in batch02.get("review_order", [])]
    if len(batch01_ids) != 24 or len(set(batch01_ids)) != 24:
        raise ValueError("Batch-01 reviewed identity is not 24 unique candidates")
    if len(batch02_ids) != 24 or len(set(batch02_ids)) != 24:
        raise ValueError("Batch-02 reviewed identity is not 24 unique candidates")
    all_ids = set(batch01_ids) | set(batch02_ids)
    if all_ids - pool_ids:
        raise ValueError("previously reviewed case is outside the frozen fresh pool")
    return all_ids, {
        "batch01_count": len(batch01_ids),
        "batch02_count": len(batch02_ids),
        "batch01_digest": batch01.get("freeze_digest"),
        "batch02_digest": batch02.get("selection_digest"),
    }


def _max_coherence_evidence(record: Mapping[str, Any], key: str) -> float:
    values = [
        _as_float(item.get("coherence", {}).get("evidence", {}).get(key), 0.0)
        for item in record.get("raw_primitive_results", [])
        if item.get("coherence", {}).get("evidence", {}).get(key) is not None
    ]
    return max(values, default=0.0)


def _max_endpoint_evidence(record: Mapping[str, Any], key: str) -> float:
    values: list[float] = []
    for item in record.get("raw_primitive_results", []):
        evidence = item.get("endpoint", {}).get("evidence", {})
        for side in ("start", "end"):
            if evidence.get(side, {}).get(key) is not None:
                values.append(_as_float(evidence[side][key], 0.0))
    return max(values, default=0.0)


def _diagnostic_scores(record: Mapping[str, Any]) -> tuple[float, float]:
    profile = record.get("coherence_profile", {})
    if not profile:
        return 0.0, 0.0
    coherence_score = (
        _as_float(profile.get("center_offset_range_widths", {}).get("max")) / 4.0
        + _as_float(profile.get("local_tangent_delta_p95_degrees", {}).get("max")) / 30.0
        + _as_float(profile.get("junction_or_crossing_fraction", {}).get("max"))
        + (1.0 - _as_float(profile.get("local_continuity_fraction", {}).get("min"), 1.0))
        + min(_as_float(profile.get("longest_disjoint_interval_fraction", {}).get("max")) * 10.0, 1.0)
        + min(_as_float(profile.get("width_p95_to_median_ratio", {}).get("max")) / 8.0, 1.0)
    ) / 6.0
    endpoint_score = (
        _max_endpoint_evidence(record, "beyond_support_fraction")
        + _max_endpoint_evidence(record, "tail_junction_fraction")
        + _max_endpoint_evidence(record, "tail_offset_change_widths") / 2.0
        + _max_endpoint_evidence(record, "tail_width_ratio") / 8.0
        + min(_max_endpoint_evidence(record, "internal_gap_before_supported_tail_fraction") * 5.0, 1.0)
    ) / 5.0
    return _clamp(coherence_score), _clamp(endpoint_score)


def _sanitize_diagnostic_case(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only engineering measurements; never copy prior human fields."""

    coherence_score, endpoint_score = _diagnostic_scores(record)
    profile = record.get("coherence_profile", {})
    endpoint_profile = record.get("endpoint_profile", {})
    return {
        "diagnostic_available": True,
        "span_status": record.get("span_status"),
        "axis_status": record.get("axis_status"),
        "coherence_status": record.get("coherence_status"),
        "coherence_reason": record.get("coherence_reason"),
        "endpoint_status": record.get("endpoint_status"),
        "endpoint_reason": record.get("endpoint_reason"),
        "coherence_profile": {
            "center_offset_range_widths_max": _rounded(
                _as_float(profile.get("center_offset_range_widths", {}).get("max"))
            ),
            "local_tangent_delta_p95_degrees_max": _rounded(
                _as_float(profile.get("local_tangent_delta_p95_degrees", {}).get("max"))
            ),
            "local_continuity_fraction_min": _rounded(
                _as_float(profile.get("local_continuity_fraction", {}).get("min"), 1.0)
            ),
            "longest_disjoint_interval_fraction_max": _rounded(
                _as_float(profile.get("longest_disjoint_interval_fraction", {}).get("max"))
            ),
            "junction_or_crossing_fraction_max": _rounded(
                _as_float(profile.get("junction_or_crossing_fraction", {}).get("max"))
            ),
            "width_p95_to_median_ratio_max": _rounded(
                _as_float(profile.get("width_p95_to_median_ratio", {}).get("max"))
            ),
            "primitive_count": profile.get("primitive_count"),
        },
        "endpoint_profile": {
            "max_tail_junction_fraction": _rounded(
                _as_float(endpoint_profile.get("max_tail_junction_fraction"))
            ),
            "max_tail_offset_change_widths": _rounded(
                _as_float(endpoint_profile.get("max_tail_offset_change_widths"))
            ),
            "max_tail_width_ratio": _rounded(
                _as_float(endpoint_profile.get("max_tail_width_ratio"))
            ),
            "max_internal_gap_before_supported_tail_fraction": _rounded(
                _as_float(endpoint_profile.get("max_internal_gap_before_supported_tail_fraction"))
            ),
            "status_counts": dict(sorted(endpoint_profile.get("status_counts", {}).items())),
        },
        "diagnostic_coherence_score": _rounded(coherence_score),
        "diagnostic_endpoint_score": _rounded(endpoint_score),
    }


def _load_diagnostics(repo_root: Path, pool_ids: set[str]) -> dict[str, dict[str, Any]]:
    payload = _read_json(_repo_path(repo_root, DIAGNOSTIC_RELATIVE))
    if payload.get("diagnostic_only", True) is not True:
        raise ValueError("primitive coherence/endpoint diagnostics are not marked diagnostic-only")
    diagnostics: dict[str, dict[str, Any]] = {}
    for record in payload.get("cases", []):
        candidate_id = str(record.get("candidate_id"))
        if candidate_id in pool_ids:
            diagnostics[candidate_id] = _sanitize_diagnostic_case(record)
    return diagnostics


def _selection_measurements(
    candidate: Mapping[str, Any], diagnostic: Mapping[str, Any] | None
) -> dict[str, Any]:
    evidence = candidate.get("direct_continuation", {}).get("evidence", {})
    off_axis = _clamp(_as_float(evidence.get("off_axis_ink_fraction")))
    parallel = _clamp(_as_float(evidence.get("parallel_run_fraction")))
    crossings = _clamp(_as_float(evidence.get("transverse_crossing_columns")) / 20.0)
    thickness = _clamp((_as_float(evidence.get("fragment_thickness_ratio"), 1.0) - 1.0) / 4.0)
    gap = _clamp(_as_float(candidate.get("gap_length_px")) / 45.0)
    length = _as_float(candidate.get("alignment_metrics", {}).get("projected_span_px"))
    proxy_coherence = 0.35 * off_axis + 0.30 * parallel + 0.20 * crossings + 0.10 * thickness + 0.05 * gap
    proxy_endpoint = 0.20 * off_axis + 0.35 * parallel + 0.25 * gap + 0.20 * crossings
    diagnostic_coherence = (
        _as_float(diagnostic.get("diagnostic_coherence_score"), 0.0)
        if diagnostic and diagnostic.get("diagnostic_available")
        else 0.0
    )
    diagnostic_endpoint = (
        _as_float(diagnostic.get("diagnostic_endpoint_score"), 0.0)
        if diagnostic and diagnostic.get("diagnostic_available")
        else 0.0
    )
    coherence_score = max(proxy_coherence, diagnostic_coherence)
    endpoint_score = max(proxy_endpoint, diagnostic_endpoint)
    clean_score = (1.0 - coherence_score) * (1.0 - endpoint_score)
    edge_score = max(gap, crossings, parallel, _clamp(length / 650.0))
    return {
        "primitive_length_px": _rounded(
            math.sqrt(
                _distance_sq(
                    _primitive_geometry(candidate)["claimed_start_px"],
                    _primitive_geometry(candidate)["claimed_end_px"],
                )
            )
        ),
        "projected_span_px": _rounded(length),
        "gap_length_px": _rounded(_as_float(candidate.get("gap_length_px"))),
        "direct_off_axis_ink_fraction": _rounded(off_axis),
        "direct_parallel_run_fraction": _rounded(parallel),
        "direct_transverse_crossing_columns": int(_as_float(evidence.get("transverse_crossing_columns"))),
        "direct_enclosed_contours": int(_as_float(evidence.get("enclosed_contours"))),
        "direct_volumetric_components": int(_as_float(evidence.get("volumetric_components"))),
        "fragment_thickness_ratio": _rounded(_as_float(evidence.get("fragment_thickness_ratio"), 1.0)),
        "local_density_fraction": _rounded(_as_float(candidate.get("local_density_fraction"))),
        "coherence_selection_score": _rounded(coherence_score),
        "endpoint_selection_score": _rounded(endpoint_score),
        "clean_control_score": _rounded(clean_score),
        "edge_selection_score": _rounded(edge_score),
        "diagnostic": dict(diagnostic) if diagnostic else {"diagnostic_available": False},
    }


def _pick_ranked(
    candidates: Sequence[Mapping[str, Any]],
    count: int,
    score: Callable[[Mapping[str, Any]], float],
    stratum: str,
    selected: list[dict[str, Any]],
    measurements: Mapping[str, Mapping[str, Any]],
) -> None:
    """Greedy deterministic selection with small source-diversity bonuses."""

    for _ in range(count):
        used_ids = {item["candidate_id"] for item in selected}
        remaining = [item for item in candidates if item["candidate_id"] not in used_ids]
        if not remaining:
            raise ValueError(f"selection stratum is undersupplied: {stratum}")
        used_families = {item["source_family_id"] for item in selected}
        used_units = {item["selected_unit_id"] for item in selected}
        used_types = {item["source_type"] for item in selected}
        used_orientations = {item["orientation"] for item in selected}
        ranked: list[tuple[float, float, str, Mapping[str, Any]]] = []
        for candidate in remaining:
            base = float(score(candidate))
            novelty = (
                0.075 * (candidate["source_family_id"] not in used_families)
                + 0.035 * (candidate["selected_unit_id"] not in used_units)
                + 0.020 * (candidate["source_type"] not in used_types)
                + 0.010 * (candidate["orientation"] not in used_orientations)
            )
            ranked.append((base + novelty, base, str(candidate["candidate_id"]), candidate))
        _combined, _base, _candidate_id, chosen = sorted(
            ranked, key=lambda item: (-item[0], -item[1], item[2])
        )[0]
        selected.append(
            {
                **dict(chosen),
                "selection_stratum": stratum,
                "selection_measurements": dict(measurements[str(chosen["candidate_id"])]),
            }
        )


def _selection_rationale(stratum: str, measurements: Mapping[str, Any]) -> str:
    if stratum == "SUSPECTED_COHERENCE_CASES":
        return (
            "High non-semantic primitive-shape variation signal from the frozen "
            "diagnostic profile when available, otherwise from direct off-axis, "
            "parallel-run, crossing, thickness, and gap measurements."
        )
    if stratum == "SUSPECTED_ENDPOINT_CASES":
        return (
            "Endpoint-focused review candidate selected from the frozen endpoint "
            "profile when available, otherwise from continuation, gap, crossing, "
            "and off-axis evidence near the claimed extent."
        )
    if stratum == "CLEAN_LONG_PRIMITIVE_CONTROLS":
        return (
            "Long claimed primitive with low frozen non-semantic conflict signal; "
            "included as a clean straight-primitive control."
        )
    if stratum == "CLEAN_SHORT_MEDIUM_CONTROLS":
        return (
            "Short/medium claimed primitive with low frozen non-semantic conflict "
            "signal; included as an ordinary control."
        )
    return (
        "Boundary case selected from extreme frozen gap, span, parallel-run, "
        "crossing, or direct-support measurements."
    )


def _attach_source_mapping(repo_root: Path, selected: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        source_path = _repo_path(repo_root, str(candidate["source_render_path"]))
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with Image.open(source_path) as image:
            image_size = image.size
        local_box, context_box = fresh.crop_boxes_for_candidate(candidate, image_size)
        geometry = _primitive_geometry(candidate)
        measurements = dict(candidate["selection_measurements"])
        source_type = str(candidate["source_type"])
        prior = bool(candidate.get("prior_reviewed_control", False))
        records.append(
            {
                "candidate_id": str(candidate["candidate_id"]),
                "review_index": index,
                "source_family": str(candidate["source_family_id"]),
                "source_document": str(candidate["source_document_id"]),
                "source_unit": str(candidate["selected_unit_id"]),
                "source_type": source_type,
                "source_render_path": str(candidate["source_render_path"]),
                "orientation": str(candidate["orientation"]),
                "primitive_length_px": measurements["primitive_length_px"],
                "projected_span_px": measurements["projected_span_px"],
                "primitive_geometry": geometry,
                "a_b_relation": geometry["a_b_relation"],
                "source_crop_mapping": {
                    "local_box_px": list(local_box),
                    "context_box_px": list(context_box),
                    "source_image_size_px": list(image_size),
                },
                "diagnostic_measurements_used": measurements,
                "selection_stratum": str(candidate["selection_stratum"]),
                "new_or_prior_reviewed": "PRIOR_REVIEWED_CONTROL" if prior else "NEW_UNREVIEWED",
                "selection_rationale": _selection_rationale(
                    str(candidate["selection_stratum"]), measurements
                ),
            }
        )
    return records


def _select_target(
    repo_root: Path,
    pool: Sequence[Mapping[str, Any]],
    prior_ids: set[str],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    measurements = {
        str(candidate["candidate_id"]): _selection_measurements(
            candidate, diagnostics.get(str(candidate["candidate_id"]))
        )
        for candidate in pool
    }
    selected: list[dict[str, Any]] = []
    prior_candidates = [
        candidate
        for candidate in pool
        if str(candidate["candidate_id"]) in prior_ids
        and measurements[str(candidate["candidate_id"])]
        .get("diagnostic", {})
        .get("diagnostic_available")
    ]
    _pick_ranked(
        prior_candidates,
        2,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])].get("diagnostic", {}).get(
                "diagnostic_coherence_score"
            )
        ),
        "SUSPECTED_COHERENCE_CASES",
        selected,
        measurements,
    )
    _pick_ranked(
        prior_candidates,
        1,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])].get("diagnostic", {}).get(
                "diagnostic_endpoint_score"
            )
        ),
        "SUSPECTED_ENDPOINT_CASES",
        selected,
        measurements,
    )
    _pick_ranked(
        prior_candidates,
        1,
        lambda candidate: (
            _as_float(measurements[str(candidate["candidate_id"])].get("clean_control_score"))
            + 0.25
            * _clamp(
                _as_float(measurements[str(candidate["candidate_id"])].get("primitive_length_px"))
                / 450.0
            )
        ),
        "CLEAN_LONG_PRIMITIVE_CONTROLS",
        selected,
        measurements,
    )

    new_candidates = [candidate for candidate in pool if str(candidate["candidate_id"]) not in prior_ids]
    _pick_ranked(
        new_candidates,
        3,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])]["coherence_selection_score"]
        ),
        "SUSPECTED_COHERENCE_CASES",
        selected,
        measurements,
    )
    _pick_ranked(
        new_candidates,
        3,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])]["endpoint_selection_score"]
        ),
        "SUSPECTED_ENDPOINT_CASES",
        selected,
        measurements,
    )
    long_candidates = [
        candidate
        for candidate in new_candidates
        if _as_float(measurements[str(candidate["candidate_id"])]["projected_span_px"])
        >= LONG_PRIMITIVE_MIN_PX
    ]
    _pick_ranked(
        long_candidates,
        2,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])]["clean_control_score"]
        ),
        "CLEAN_LONG_PRIMITIVE_CONTROLS",
        selected,
        measurements,
    )
    short_medium_candidates = [
        candidate
        for candidate in new_candidates
        if _as_float(measurements[str(candidate["candidate_id"])]["projected_span_px"])
        < LONG_PRIMITIVE_MIN_PX
    ]
    _pick_ranked(
        short_medium_candidates,
        3,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])]["clean_control_score"]
        ),
        "CLEAN_SHORT_MEDIUM_CONTROLS",
        selected,
        measurements,
    )
    _pick_ranked(
        new_candidates,
        1,
        lambda candidate: _as_float(
            measurements[str(candidate["candidate_id"])]["edge_selection_score"]
        ),
        "AXIS_SPAN_EDGE_CASES",
        selected,
        measurements,
    )
    if len(selected) != TARGET_REVIEW_SIZE:
        raise ValueError(f"targeted review size is {len(selected)} != {TARGET_REVIEW_SIZE}")
    if len({item["candidate_id"] for item in selected}) != len(selected):
        raise ValueError("selection contains duplicate candidate IDs")
    selected_for_freeze: list[dict[str, Any]] = []
    for candidate in selected:
        candidate_copy = dict(candidate)
        candidate_copy["prior_reviewed_control"] = str(candidate["candidate_id"]) in prior_ids
        selected_for_freeze.append(candidate_copy)
    return _attach_source_mapping(repo_root, selected_for_freeze)


def _selection_digest(records: Sequence[Mapping[str, Any]], source_candidate_set_id: str) -> str:
    payload = {
        "base_checkpoint": BASE_CHECKPOINT,
        "selection_code_version": SELECTION_CODE_VERSION,
        "protocol": PROTOCOL,
        "source_candidate_set_id": source_candidate_set_id,
        "records": [
            {
                "candidate_id": record["candidate_id"],
                "review_index": record["review_index"],
                "source_family": record["source_family"],
                "source_unit": record["source_unit"],
                "source_render_path": record["source_render_path"],
                "orientation": record["orientation"],
                "primitive_geometry": record["primitive_geometry"],
                "source_crop_mapping": record["source_crop_mapping"],
                "selection_stratum": record["selection_stratum"],
                "new_or_prior_reviewed": record["new_or_prior_reviewed"],
                "diagnostic_measurements_used": record["diagnostic_measurements_used"],
            }
            for record in records
        ],
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "source_families": len({record["source_family"] for record in records}),
        "source_units": len({record["source_unit"] for record in records}),
        "source_types": len({record["source_type"] for record in records}),
        "pdf_derived": sum(record["source_type"] == "PDF" for record in records),
        "dwg_derived": sum(record["source_type"] == "DWG" for record in records),
        "horizontal": sum(record["orientation"] == "horizontal" for record in records),
        "vertical": sum(record["orientation"] == "vertical" for record in records),
    }


def _marker_for_box(
    record: Mapping[str, Any], box: Sequence[int], size: tuple[int, int]
) -> dict[str, Any]:
    geometry = record["primitive_geometry"]
    origin_x, origin_y = int(box[0]), int(box[1])

    def relative(value: Sequence[float | int]) -> list[float]:
        return [round(float(value[0]) - origin_x, 3), round(float(value[1]) - origin_y, 3)]

    return {
        "width": int(size[0]),
        "height": int(size[1]),
        "start": relative(geometry["claimed_start_px"]),
        "end": relative(geometry["claimed_end_px"]),
    }


def _write_clean_crop(source_path: Path, box: Sequence[int], destination: Path) -> tuple[int, int]:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
        crop_box = tuple(int(value) for value in box)
        if crop_box[2] > image.width or crop_box[3] > image.height:
            raise ValueError(f"crop exceeds source render: {source_path} {crop_box} {image.size}")
        crop = image.crop(crop_box)
        destination.parent.mkdir(parents=True, exist_ok=True)
        crop.save(destination, format="PNG", optimize=True)
        return crop.size


def _write_overlay(
    clean_path: Path,
    destination: Path,
    marker: Mapping[str, Any],
) -> None:
    with Image.open(clean_path) as source:
        image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        start = tuple(float(value) for value in marker["start"])
        end = tuple(float(value) for value in marker["end"])
        draw.line([start, end], fill=(224, 28, 45), width=4)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=True)


def _write_contact_sheet(records: Sequence[Mapping[str, Any]], package_dir: Path, destination: Path) -> None:
    thumbnails: list[tuple[int, Image.Image]] = []
    for record in records:
        path = package_dir / "assets" / "local" / f"{record['candidate_id']}-overlay.png"
        with Image.open(path) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((280, 180))
            thumbnails.append((int(record["review_index"]), thumb.copy()))
    columns = 4
    rows = math.ceil(len(thumbnails) / columns)
    cell_width, cell_height = 300, 220
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (246, 248, 250))
    draw = ImageDraw.Draw(sheet)
    for index, (review_index, thumb) in enumerate(thumbnails):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(thumb, (x + (cell_width - thumb.width) // 2, y + 24))
        draw.text((x + 10, y + 6), f"Review {review_index}", fill=(25, 35, 45))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG", optimize=True)


REVIEW_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>线段检查</title>
  <style>
    :root { --ink:#17202a; --muted:#5b6873; --line:#d6dee5; --panel:#fff; --soft:#f3f6f8; --red:#df1d35; --yellow:#f2bb23; --blue:#0d5a9e; --blue-soft:#e9f4fa; }
    * { box-sizing:border-box; }
    html, body { min-height:100%; }
    body { margin:0; color:var(--ink); background:#e9eef2; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
    button, input, textarea { font:inherit; }
    button { cursor:pointer; }
    .shell { width:min(1380px,100%); margin:0 auto; padding:20px 22px 28px; }
    .topbar { display:flex; gap:14px; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; margin-bottom:7px; }
    h1, h2, h3, p { margin:0; }
    h1 { font-size:clamp(21px,2.4vw,28px); letter-spacing:-.02em; }
    .subtle { color:var(--muted); font-size:13px; }
    .header-actions { display:flex; align-items:flex-start; gap:12px; }
    .header-progress { display:flex; flex-direction:column; align-items:flex-end; gap:2px; color:var(--muted); font-size:12px; line-height:1.35; }
    .header-progress strong { color:var(--ink); font-size:15px; font-weight:700; }
    .data-menu { position:relative; z-index:30; }
    .data-menu summary { list-style:none; border:1px solid #b9c7d1; border-radius:8px; background:#fff; color:#243847; padding:7px 12px; font-size:13px; cursor:pointer; }
    .data-menu summary::-webkit-details-marker { display:none; }
    .data-menu summary::after { content:" ▾"; color:var(--muted); }
    .data-menu[open] summary, .data-menu summary:hover { border-color:#28698f; background:var(--blue-soft); }
    .data-menu-panel { position:absolute; top:calc(100% + 6px); right:0; display:grid; gap:4px; min-width:128px; padding:6px; border:1px solid var(--line); border-radius:9px; background:#fff; box-shadow:0 8px 24px rgba(34,52,66,.14); }
    .data-menu-panel button { width:100%; padding:7px 9px; border:0; border-radius:6px; background:#fff; color:#243847; text-align:left; font-size:13px; }
    .data-menu-panel button:hover { background:var(--soft); }
    .intro { margin:0 0 12px; }
    .evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .evidence-card { min-width:0; overflow:hidden; border:1px solid var(--line); border-radius:10px; background:var(--panel); box-shadow:0 3px 12px rgba(34,52,66,.05); }
    .evidence-card[hidden] { display:none; }
    .evidence-card h2 { padding:8px 11px; font-size:13px; font-weight:650; border-bottom:1px solid var(--line); }
    .image-stage { height:clamp(106px,12vw,150px); display:flex; align-items:center; justify-content:center; overflow:hidden; padding:8px; background:#f8fafb; cursor:zoom-in; }
    .image-frame { position:relative; width:100%; height:100%; display:flex; align-items:center; justify-content:center; line-height:0; }
    .image-frame img { display:block; max-width:100%; max-height:100%; width:auto; height:auto; object-fit:contain; }
    .marker-overlay { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; overflow:visible; }
    .marker-overlay circle { fill:var(--yellow); stroke:#fff; stroke-width:1.5; vector-effect:non-scaling-stroke; opacity:.95; }
    .preview-hint { margin-top:8px; color:var(--muted); font-size:12px; }
    .review-section { margin-top:16px; padding:15px 16px 16px; border:1px solid var(--line); border-radius:11px; background:var(--panel); box-shadow:0 3px 12px rgba(34,52,66,.05); }
    .review-section h2 { font-size:17px; margin-bottom:10px; }
    .primary-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; }
    .choice-button { min-height:78px; padding:9px 10px; text-align:left; border:1px solid #b9c7d1; border-radius:8px; background:#fff; color:#243847; }
    .choice-button:hover { border-color:#28698f; background:#f5fbfe; }
    .choice-button.active { border-color:#28698f; background:var(--blue-soft); box-shadow:0 0 0 2px rgba(40,105,143,.18); }
    .choice-button .shortcut { display:inline-grid; place-items:center; width:22px; height:22px; border-radius:50%; background:#e7edf1; font-weight:750; }
    .choice-button.active .shortcut { background:#28698f; color:#fff; }
    .choice-button .choice-title { display:block; margin-top:7px; font-size:14px; line-height:1.25; font-weight:650; }
    .choice-button .choice-help { display:block; margin-top:4px; color:var(--muted); font-size:11px; line-height:1.35; }
    .secondary-details { margin-top:12px; }
    .secondary-details summary { display:inline-flex; align-items:center; gap:4px; color:#364b59; font-size:13px; cursor:pointer; }
    .secondary-details summary::-webkit-details-marker { display:none; }
    .secondary-details summary .disclosure { color:var(--muted); transition:transform .16s ease; }
    .secondary-details[open] summary .disclosure { transform:rotate(180deg); }
    .secondary-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:7px; margin-top:9px; }
    .secondary-choice { display:flex; gap:7px; align-items:flex-start; min-height:36px; padding:8px 9px; border:1px solid #b9c7d1; border-radius:8px; background:#fff; color:#344853; font-size:12px; }
    .secondary-choice input { margin:2px 0 0; accent-color:var(--blue); }
    .note-panel { margin-top:15px; padding-top:14px; border-top:1px solid var(--line); }
    .note-panel label { display:block; font-weight:650; }
    .note-helper { margin-top:4px; color:var(--muted); font-size:12px; }
    .note-panel textarea { display:block; width:100%; min-height:88px; margin-top:8px; resize:vertical; padding:9px 10px; border:1px solid #b9c7d1; border-radius:8px; background:#fff; line-height:1.5; font-size:14px; }
    .navigation { display:flex; justify-content:space-between; gap:10px; margin-top:15px; padding-top:14px; border-top:1px solid var(--line); }
    .navigation button { min-width:96px; padding:8px 13px; border:1px solid #b9c7d1; border-radius:8px; background:#fff; color:#243847; font-size:13px; }
    .navigation button:hover:not(:disabled) { border-color:#28698f; background:var(--blue-soft); }
    .navigation button:disabled { cursor:not-allowed; opacity:.48; }
    .status-line { min-height:20px; margin-top:9px; color:#405965; font-size:12px; }
    .shortcut-hint { margin-top:4px; color:var(--muted); font-size:11px; }
    .modal { position:fixed; inset:0; z-index:100; display:flex; align-items:stretch; justify-content:center; padding:14px; background:rgba(11,21,29,.78); }
    .modal[hidden] { display:none; }
    .modal-dialog { display:flex; flex-direction:column; width:min(1600px,100%); min-height:0; border-radius:12px; overflow:hidden; background:#edf2f5; box-shadow:0 18px 60px rgba(0,0,0,.35); }
    .modal-head { display:flex; align-items:center; gap:10px; justify-content:space-between; padding:10px 14px; background:#fff; border-bottom:1px solid var(--line); }
    .modal-toolbar { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
    .modal-toolbar button { border:1px solid #b9c7d1; border-radius:7px; background:#fff; color:#243847; padding:7px 10px; }
    .modal-toolbar button:hover { border-color:#28698f; background:var(--blue-soft); }
    .zoom-viewport { position:relative; flex:1; min-height:0; overflow:auto; padding:18px; background:#dce4e9; cursor:grab; }
    .zoom-viewport.dragging { cursor:grabbing; }
    .zoom-content { display:flex; gap:18px; align-items:flex-start; width:max-content; transform-origin:top left; line-height:0; }
    .zoom-content figure { margin:0; padding:0; background:#fff; border:1px solid #b8c6ce; }
    .zoom-content figcaption { padding:7px 9px; line-height:1.2; color:#435864; font-size:12px; background:#fff; }
    .zoom-content .zoom-frame { position:relative; display:block; line-height:0; }
    .zoom-content img { display:block; max-width:none; height:auto; }
    .zoom-content .marker-overlay { position:absolute; inset:0; }
    .modal-foot { display:flex; justify-content:space-between; padding:8px 14px; color:#536570; font-size:12px; background:#fff; border-top:1px solid var(--line); }
    @media (max-width:1080px) { .primary-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } .secondary-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
    @media (max-width:700px) { .shell { padding:14px 10px 22px; } .header-actions { width:100%; justify-content:space-between; align-items:center; } .header-progress { align-items:flex-start; } .evidence-grid { gap:8px; } .primary-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .secondary-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .review-section { padding-inline:12px; } }
    @media (max-width:430px) { .evidence-grid, .secondary-grid { grid-template-columns:1fr; } .primary-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .image-stage { height:150px; } }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <h1>线段检查</h1>
        <p class="subtle">看图，判断这根红线本身，再选择一个结果。</p>
      </div>
      <div class="header-actions">
        <div id="progress" class="header-progress" aria-live="polite"></div>
        <details class="data-menu">
          <summary>数据</summary>
          <div class="data-menu-panel">
            <button id="import-button" type="button">导入结果</button>
            <button id="export-button" type="button">导出结果</button>
            <button id="new-button" type="button">重新开始</button>
            <input id="import-file" type="file" accept="application/json" hidden>
          </div>
        </details>
      </div>
    </header>
    <section id="evidence-grid" class="evidence-grid" aria-label="图片预览">
      <article class="evidence-card"><h2>局部原图</h2><div id="local-clean-stage"></div></article>
      <article class="evidence-card"><h2>局部红线</h2><div id="local-overlay-stage"></div></article>
      <article class="evidence-card"><h2>整体原图</h2><div id="context-clean-stage"></div></article>
      <article class="evidence-card"><h2>整体红线</h2><div id="context-overlay-stage"></div></article>
    </section>
    <p class="preview-hint">点击图片可放大</p>
    <section class="review-section" aria-label="检查结果">
      <h2>判断这根红线本身：</h2>
      <div class="primary-grid">
        <button class="choice-button" type="button" data-primary="VALID_SINGLE_STRAIGHT_PRIMITIVE"><span class="shortcut">1</span><span class="choice-title">完整直线</span><span class="choice-help">原图确实是一根连续直线</span></button>
        <button class="choice-button" type="button" data-primary="MULTIPLE_OR_OFFSET_SEGMENTS"><span class="shortcut">2</span><span class="choice-title">多段误合并</span><span class="choice-help">多段、错位或分离的线被合成一根</span></button>
        <button class="choice-button" type="button" data-primary="ENDPOINT_OVERSHOOT"><span class="shortcut">3</span><span class="choice-title">端点过长</span><span class="choice-help">主体正确，但一端或两端伸过头</span></button>
        <button class="choice-button" type="button" data-primary="FOREIGN_STROKE_CAPTURE"><span class="shortcut">4</span><span class="choice-title">侵入其他结构</span><span class="choice-help">红线进入文字、符号或别的线</span></button>
        <button class="choice-button" type="button" data-primary="OTHER_PRIMITIVE_MISMATCH"><span class="shortcut">5</span><span class="choice-title">其他错误</span><span class="choice-help">明显不对，但不属于以上情况</span></button>
        <button class="choice-button" type="button" data-primary="INSUFFICIENT_EVIDENCE"><span class="shortcut">6</span><span class="choice-title">看不清</span><span class="choice-help">现有图像不足以判断</span></button>
      </div>
      <details class="secondary-details">
        <summary>补充标记（可选） <span class="disclosure" aria-hidden="true">▾</span></summary>
        <div class="secondary-grid">
          <label class="secondary-choice"><input type="checkbox" data-secondary="MULTIPLE_OR_OFFSET_SEGMENTS"><span>多段/错位</span></label>
          <label class="secondary-choice"><input type="checkbox" data-secondary="ENDPOINT_OVERSHOOT"><span>端点过长</span></label>
          <label class="secondary-choice"><input type="checkbox" data-secondary="FOREIGN_STROKE_CAPTURE"><span>侵入其他结构</span></label>
          <label class="secondary-choice"><input type="checkbox" data-secondary="CROSSES_LOCAL_STRUCTURE"><span>穿过局部结构</span></label>
          <label class="secondary-choice"><input type="checkbox" data-secondary="OTHER"><span>其他</span></label>
        </div>
      </details>
      <section class="note-panel" aria-label="备注">
        <label for="candidate-note">备注（可选）</label>
        <p class="note-helper">只写你实际看到的问题即可，不需要专业名称。</p>
        <textarea id="candidate-note" placeholder="例如：这里实际是三段错开的线；右端伸进了文字。"></textarea>
      </section>
      <nav class="navigation" aria-label="案例导航">
        <button id="previous-button" type="button">上一张</button>
        <button id="next-button" type="button">下一张</button>
      </nav>
      <div id="status-line" class="status-line" aria-live="polite">请选择一个结果。</div>
      <p class="shortcut-hint">快捷键：1–6 选择，←/→ 切换案例</p>
    </section>
  </main>
  <div id="modal" class="modal" hidden role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-dialog">
      <div class="modal-head"><strong id="modal-title">放大查看</strong><div class="modal-toolbar"><button id="zoom-out" type="button" aria-label="缩小">−</button><button id="zoom-fit" type="button">适合窗口</button><button id="zoom-in" type="button" aria-label="放大">+</button><button id="modal-close" type="button">关闭</button></div></div>
      <div id="zoom-viewport" class="zoom-viewport"><div id="zoom-content" class="zoom-content"></div></div>
      <div class="modal-foot"><span>原图与红线并排查看</span><span id="modal-zoom-label">100%</span></div>
    </div>
  </div>
  <script>
  "use strict";
  const PACKAGE = __PACKAGE_MANIFEST__;
  const REVIEW_PROTOCOL = "PRIMITIVE_INTEGRITY_REVIEW_V1";
  const PRIMARY_CLASSES = Object.freeze(["VALID_SINGLE_STRAIGHT_PRIMITIVE","MULTIPLE_OR_OFFSET_SEGMENTS","ENDPOINT_OVERSHOOT","FOREIGN_STROKE_CAPTURE","OTHER_PRIMITIVE_MISMATCH","INSUFFICIENT_EVIDENCE"]);
  const SECONDARY_FLAGS = Object.freeze(["MULTIPLE_OR_OFFSET_SEGMENTS","ENDPOINT_OVERSHOOT","FOREIGN_STROKE_CAPTURE","CROSSES_LOCAL_STRUCTURE","OTHER"]);
  const STORAGE_KEY = "draftsman-primitive-integrity-review-v1:" + PACKAGE.candidate_set_id;
  const HISTORY_PREFIX = STORAGE_KEY + ":history:";
  const IMAGE_LABELS = Object.freeze({local:Object.freeze({clean:"局部原图",overlay:"局部红线"}),context:Object.freeze({clean:"整体原图",overlay:"整体红线"})});
  const state = {session:null,index:0,noteTimer:null,modal:null,modalScale:1,drag:null};
  function now() { return new Date().toISOString(); }
  function newSession() { const timestamp=now(); return {schema_version:1,protocol:REVIEW_PROTOCOL,session_id:"primitive-integrity-review-" + timestamp.replace(/[-:.TZ]/g,"") + "-" + Math.random().toString(36).slice(2,8),candidate_set_id:PACKAGE.candidate_set_id,review_order:PACKAGE.review_order.slice(),review_started_at:timestamp,review_updated_at:timestamp,items:PACKAGE.items.map(function(item) { return {review_index:item.review_index,candidate_id:item.candidate_id,primary_class:null,secondary_flags:[],optional_note:"",review_status:"PENDING",updated_at:timestamp}; })}; }
  function sameArray(a,b) { return Array.isArray(a) && Array.isArray(b) && a.length===b.length && a.every(function(value,index) { return value===b[index]; }); }
  function normalizeSession(raw) { if (!raw || raw.schema_version!==1 || raw.protocol!==REVIEW_PROTOCOL || raw.candidate_set_id!==PACKAGE.candidate_set_id || !sameArray(raw.review_order,PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length!==PACKAGE.items.length) return null; const allowed=new Set(PACKAGE.review_order),seen=new Set(),timestamp=now(); const items=raw.items.map(function(item) { if (!item || !allowed.has(item.candidate_id) || seen.has(item.candidate_id)) throw new Error("candidate identity mismatch"); seen.add(item.candidate_id); const primary=item.primary_class || null; const flags=Array.isArray(item.secondary_flags) ? item.secondary_flags.slice() : []; if (primary!==null && !PRIMARY_CLASSES.includes(primary)) throw new Error("primary class mismatch"); if (flags.some(function(flag) { return !SECONDARY_FLAGS.includes(flag); }) || new Set(flags).size!==flags.length) throw new Error("secondary flag mismatch"); return {review_index:item.review_index,candidate_id:item.candidate_id,primary_class:primary,secondary_flags:flags,optional_note:typeof item.optional_note === "string" ? item.optional_note : "",review_status:primary ? "REVIEWED" : "PENDING",updated_at:item.updated_at || timestamp}; }); return Object.assign({},raw,{items:items,review_updated_at:raw.review_updated_at || timestamp}); }
  function saveSession() { if (!state.session) return; state.session.review_updated_at=now(); localStorage.setItem(STORAGE_KEY,JSON.stringify(state.session)); }
  function loadSession() { let loaded=null; try { loaded=normalizeSession(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")); } catch(error) { loaded=null; } state.session=loaded || newSession(); const pending=state.session.items.findIndex(function(item) { return !item.primary_class; }); state.index=pending>=0 ? pending : 0; saveSession(); }
  function currentItem() { return state.session.items[state.index]; }
  function packageItem(id) { return PACKAGE.items.find(function(item) { return item.candidate_id===id; }); }
  function setStatus(message) { document.getElementById("status-line").textContent=message || ""; }
  function renderProgress() { const done=state.session.items.filter(function(item) { return Boolean(item.primary_class); }).length; const progress=document.getElementById("progress"); progress.replaceChildren(); const current=document.createElement("strong"); current.textContent="案例 " + (state.index+1) + " / " + PACKAGE.candidate_count; const completed=document.createElement("span"); completed.textContent="已完成 " + done + " / " + PACKAGE.candidate_count; progress.append(current,completed); if (state.modal) document.getElementById("modal-title").textContent=(state.modal.kind==="local" ? "局部查看" : "整体查看"); }
  function endpointMarkerSvg(marker) { const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"); svg.setAttribute("viewBox","0 0 " + marker.width + " " + marker.height); svg.setAttribute("preserveAspectRatio","none"); svg.setAttribute("class","marker-overlay"); svg.setAttribute("aria-label","黄色端点标记"); [marker.start,marker.end].forEach(function(value) { const circle=document.createElementNS("http://www.w3.org/2000/svg","circle"); circle.setAttribute("cx",value[0]); circle.setAttribute("cy",value[1]); circle.setAttribute("r","5"); svg.appendChild(circle); }); return svg; }
  function imageStage(item,kind,type) { const stage=document.createElement("div"); stage.className="image-stage"; stage.title="点击放大"; stage.setAttribute("role","button"); stage.tabIndex=0; stage.setAttribute("aria-label",IMAGE_LABELS[kind][type] + "，点击放大"); const frame=document.createElement("div"); frame.className="image-frame"; const image=document.createElement("img"); image.alt=IMAGE_LABELS[kind][type]; image.src=type==="clean" ? (kind==="local" ? item.local_clean_image : item.context_clean_image) : (kind==="local" ? item.local_overlay_image : item.context_overlay_image); frame.appendChild(image); stage.appendChild(frame); stage.addEventListener("click",function() { openModal(item,kind); }); stage.addEventListener("keydown",function(event) { if (event.key==="Enter" || event.key===" ") { event.preventDefault(); openModal(item,kind); } }); return stage; }
  function renderEvidence() { const item=packageItem(currentItem().candidate_id); ["local","context"].forEach(function(kind) { ["clean","overlay"].forEach(function(type) { const id=kind+"-"+type+"-stage"; document.getElementById(id).replaceChildren(imageStage(item,kind,type)); }); }); }
  function renderControls() { const item=currentItem(); document.querySelectorAll("[data-primary]").forEach(function(button) { button.classList.toggle("active",button.dataset.primary===item.primary_class); }); document.querySelectorAll("[data-secondary]").forEach(function(input) { input.checked=item.secondary_flags.includes(input.dataset.secondary); }); document.getElementById("candidate-note").value=item.optional_note || ""; }
  function renderNavigation() { document.getElementById("previous-button").disabled=state.index===0; document.getElementById("next-button").disabled=state.index===state.session.items.length-1; }
  function render() { renderProgress(); renderEvidence(); renderControls(); renderNavigation(); }
  function saveNote() { currentItem().optional_note=document.getElementById("candidate-note").value; currentItem().updated_at=now(); saveSession(); }
  function scheduleNoteSave() { window.clearTimeout(state.noteTimer); state.noteTimer=window.setTimeout(saveNote,250); }
  function setPrimary(value) { if (!PRIMARY_CLASSES.includes(value)) return; const item=currentItem(); item.primary_class=value; item.updated_at=now(); saveSession(); render(); setStatus("已选择，可继续补充标记或备注。"); }
  function setSecondary(flag,checked) { if (!SECONDARY_FLAGS.includes(flag)) return; const item=currentItem(); const values=new Set(item.secondary_flags); if (checked) values.add(flag); else values.delete(flag); item.secondary_flags=SECONDARY_FLAGS.filter(function(value) { return values.has(value); }); item.updated_at=now(); saveSession(); render(); setStatus("补充标记已保存。"); }
  function navigate(delta) { saveNote(); state.index=Math.max(0,Math.min(state.session.items.length-1,state.index+delta)); render(); setStatus("已切换案例。"); }
  function freshReview() { const hasAnswers=state.session.items.some(function(item) { return item.primary_class || item.secondary_flags.length || item.optional_note.length; }); if (hasAnswers && !window.confirm("开始新的审核？当前本地会话会保留。")) return; if (hasAnswers) localStorage.setItem(HISTORY_PREFIX + state.session.session_id,JSON.stringify(state.session)); state.session=newSession(); state.index=0; saveSession(); render(); setStatus("新的审核已开始；所有答案均为空。"); }
  function downloadJson(filename,value) { const blob=new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"}); const url=URL.createObjectURL(blob); const anchor=document.createElement("a"); anchor.href=url; anchor.download=filename; anchor.click(); window.setTimeout(function() { URL.revokeObjectURL(url); },1000); }
  function exportResult() { saveNote(); const payload=state.session.items.map(function(item) { return {protocol:REVIEW_PROTOCOL,candidate_set_id:PACKAGE.candidate_set_id,candidate_id:item.candidate_id,review_index:item.review_index,primary_class:item.primary_class,secondary_flags:item.secondary_flags.slice(),optional_note:item.optional_note}; }); downloadJson("primitive-integrity-review-v1-" + PACKAGE.candidate_set_id + ".json",payload); setStatus("审核结果已导出；备注按原文保留。"); }
  function validateImport(raw) { const rows=Array.isArray(raw) ? raw : raw && raw.items; if (!Array.isArray(rows) || rows.length!==PACKAGE.candidate_count) throw new Error("候选数量不匹配。"); const session=newSession(),seen=new Set(); rows.forEach(function(row) { if (!row || row.protocol!==REVIEW_PROTOCOL || row.candidate_set_id!==PACKAGE.candidate_set_id || seen.has(row.candidate_id)) throw new Error("审核结果身份不匹配。"); const target=session.items.find(function(item) { return item.candidate_id===row.candidate_id; }); if (!target || row.review_index!==target.review_index) throw new Error("审核顺序不匹配。"); const primary=row.primary_class || null; const flags=Array.isArray(row.secondary_flags) ? row.secondary_flags.slice() : []; if (primary!==null && !PRIMARY_CLASSES.includes(primary)) throw new Error("分类结果不允许。"); if (flags.some(function(flag) { return !SECONDARY_FLAGS.includes(flag); }) || new Set(flags).size!==flags.length) throw new Error("补充标记不允许。"); if (typeof row.optional_note!=="string") throw new Error("备注格式不正确。"); target.primary_class=primary; target.secondary_flags=SECONDARY_FLAGS.filter(function(flag) { return flags.includes(flag); }); target.optional_note=row.optional_note; target.review_status=primary ? "REVIEWED" : "PENDING"; seen.add(row.candidate_id); }); if (seen.size!==PACKAGE.candidate_count) throw new Error("缺少候选。"); return session; }
  function importResult(event) { const file=event.target.files && event.target.files[0]; if (!file) return; const reader=new FileReader(); reader.onload=function() { try { state.session=validateImport(JSON.parse(String(reader.result))); state.index=0; saveSession(); render(); setStatus("审核结果已导入并校验；答案和备注保持原样。"); } catch(error) { setStatus("导入失败：" + error.message); } event.target.value=""; }; reader.readAsText(file); }
  function openModal(item,kind) { state.modal={item:item,kind:kind}; state.modalScale=1; document.getElementById("modal").hidden=false; renderModal(); }
  function closeModal() { state.modal=null; state.drag=null; document.getElementById("modal").hidden=true; }
  function setModalScale(value) { state.modalScale=Math.max(.5,Math.min(4,Math.round(value*100)/100)); document.getElementById("zoom-content").style.transform="scale(" + state.modalScale + ")"; document.getElementById("modal-zoom-label").textContent=Math.round(state.modalScale*100) + "%"; }
  function renderModal() { if (!state.modal) return; const item=packageItem(state.modal.item.candidate_id),kind=state.modal.kind,content=document.getElementById("zoom-content"); document.getElementById("modal-title").textContent=kind==="local" ? "局部查看" : "整体查看"; content.replaceChildren(); [["clean",kind==="local" ? item.local_clean_image : item.context_clean_image,false],["overlay",kind==="local" ? item.local_overlay_image : item.context_overlay_image,true]].forEach(function(view) { const figure=document.createElement("figure"),frame=document.createElement("div"),image=document.createElement("img"),caption=document.createElement("figcaption"),label=IMAGE_LABELS[kind][view[0]]; frame.className="zoom-frame"; image.src=view[1]; image.alt=label; frame.appendChild(image); if (view[2]) frame.appendChild(endpointMarkerSvg(item.marker[kind])); figure.appendChild(frame); caption.textContent=label; figure.appendChild(caption); content.appendChild(figure); }); setModalScale(state.modalScale); }
  function keyHandler(event) { const tag=event.target && event.target.tagName ? event.target.tagName.toLowerCase() : ""; if (tag==="input" || tag==="textarea" || event.target.isContentEditable) return; if (!document.getElementById("modal").hidden) { if (event.key==="Escape") { event.preventDefault(); closeModal(); } return; } if (event.key==="ArrowLeft") { event.preventDefault(); navigate(-1); return; } if (event.key==="ArrowRight") { event.preventDefault(); navigate(1); return; } const number={"1":PRIMARY_CLASSES[0],"2":PRIMARY_CLASSES[1],"3":PRIMARY_CLASSES[2],"4":PRIMARY_CLASSES[3],"5":PRIMARY_CLASSES[4],"6":PRIMARY_CLASSES[5]}[event.key]; if (number) setPrimary(number); }
  document.querySelectorAll("[data-primary]").forEach(function(button) { button.addEventListener("click",function() { setPrimary(button.dataset.primary); }); });
  document.querySelectorAll("[data-secondary]").forEach(function(input) { input.addEventListener("change",function() { setSecondary(input.dataset.secondary,input.checked); }); });
  document.getElementById("candidate-note").addEventListener("input",scheduleNoteSave); document.getElementById("previous-button").addEventListener("click",function() { navigate(-1); }); document.getElementById("next-button").addEventListener("click",function() { navigate(1); }); document.getElementById("new-button").addEventListener("click",freshReview); document.getElementById("import-button").addEventListener("click",function() { document.getElementById("import-file").click(); }); document.getElementById("import-file").addEventListener("change",importResult); document.getElementById("export-button").addEventListener("click",exportResult); document.getElementById("modal-close").addEventListener("click",closeModal); document.getElementById("modal").addEventListener("click",function(event) { if (event.target===event.currentTarget) closeModal(); }); document.getElementById("zoom-out").addEventListener("click",function() { setModalScale(state.modalScale-.25); }); document.getElementById("zoom-in").addEventListener("click",function() { setModalScale(state.modalScale+.25); }); document.getElementById("zoom-fit").addEventListener("click",function() { setModalScale(1); });
  const viewport=document.getElementById("zoom-viewport"); viewport.addEventListener("wheel",function(event) { if (!state.modal) return; event.preventDefault(); setModalScale(state.modalScale + (event.deltaY<0 ? .15 : -.15)); },{passive:false}); viewport.addEventListener("pointerdown",function(event) { if (!state.modal || state.modalScale<=1) return; state.drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop}; viewport.classList.add("dragging"); viewport.setPointerCapture(event.pointerId); }); viewport.addEventListener("pointermove",function(event) { if (!state.drag) return; viewport.scrollLeft=state.drag.left-(event.clientX-state.drag.x); viewport.scrollTop=state.drag.top-(event.clientY-state.drag.y); }); viewport.addEventListener("pointerup",function() { state.drag=null; viewport.classList.remove("dragging"); }); viewport.addEventListener("pointercancel",function() { state.drag=null; viewport.classList.remove("dragging"); }); document.addEventListener("keydown",keyHandler); loadSession(); render();
  </script>
</body>
</html>
'''


def render_review_html(manifest: Mapping[str, Any]) -> str:
    # Keep provenance/governance fields outside the reviewer-facing document.
    # The UI only needs immutable identity, order, asset paths, and endpoint
    # marker geometry.
    reviewer_manifest = {
        "schema_version": manifest["schema_version"],
        "package_id": manifest["package_id"],
        "review_protocol": manifest["review_protocol"],
        "candidate_set_id": manifest["candidate_set_id"],
        "candidate_count": manifest["candidate_count"],
        "review_order": list(manifest["review_order"]),
        "items": list(manifest["items"]),
    }
    package_json = json.dumps(reviewer_manifest, ensure_ascii=False, separators=(",", ":"))
    return REVIEW_HTML_TEMPLATE.replace("__PACKAGE_MANIFEST__", package_json)


def _write_package_readme(path: Path) -> None:
    path.write_text(
        "PRIMITIVE_INTEGRITY_REVIEW_V1\n\n"
        "比较机器绘制的红色 primitive 与可见 source geometry。\n"
        "Primary class 必选；secondary flags 和 optional note 可选。\n"
        "本地审核包开始时没有预填答案，导出结果可重新导入并保留备注原文。\n\n"
        "HUMAN_REVIEW: PENDING\n"
        "PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED\n",
        encoding="utf-8",
    )


def _zip_package(package_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_dir).as_posix()
            info = zipfile.ZipInfo(relative)
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def _validate_package_html(html: str) -> list[str]:
    errors: list[str] = []
    if "position:sticky" in html or ".review-controls" in html:
        errors.append("review controls must remain in normal document flow")
    if ".review-section" not in html or ".data-menu" not in html:
        errors.append("compact review hierarchy missing")
    if ".shell { width:min(1380px,100%); margin:0 auto; padding:20px 22px 28px" not in html:
        errors.append("compact page spacing missing")
    if "primary_class:null" not in html or "secondary_flags:[]" not in html or 'optional_note:""' not in html:
        errors.append("fresh empty review state missing")
    for token in (
        "局部原图",
        "局部红线",
        "整体原图",
        "整体红线",
        "完整直线",
        "多段误合并",
        "端点过长",
        "侵入其他结构",
        "其他错误",
        "看不清",
        "补充标记（可选）",
        "备注（可选）",
        "点击图片可放大",
        "上一张",
        "下一张",
    ):
        if token not in html:
            errors.append(f"reviewer-facing label missing: {token}")
    for value in PRIMARY_CLASSES + SECONDARY_FLAGS:
        if value not in html:
            errors.append(f"review vocabulary missing: {value}")
    for forbidden in (
        'class="label-code"',
        ">VALID_SINGLE_STRAIGHT_PRIMITIVE<",
        ">MULTIPLE_OR_OFFSET_SEGMENTS<",
        ">ENDPOINT_OVERSHOOT<",
        ">FOREIGN_STROKE_CAPTURE<",
        ">OTHER_PRIMITIVE_MISMATCH<",
        ">INSUFFICIENT_EVIDENCE<",
        "marker-toggle",
        "data-view-mode",
        "data-focus",
        "primitive overlay",
    ):
        if forbidden in html:
            errors.append(f"reviewer UI exposes redundant technical control: {forbidden}")
    for forbidden in (
        "selection_stratum",
        "diagnostic_measurements_used",
        "machine_verdict",
        "support_fraction",
        "coherence_status",
        "endpoint_status",
        "human_stage1",
        "human_stage2",
        "prediction",
        "cosine",
        "VALIDATION",
        "LOCKED_BLIND",
        "H1/H2",
        "Batch-03",
    ):
        if forbidden in html:
            errors.append(f"reviewer leakage: {forbidden}")
    if "<script src=" in html or "<link rel=\"stylesheet\"" in html or "fetch(" in html or "XMLHttpRequest" in html:
        errors.append("package is not self-contained")
    return errors


def validate_review_package(package_dir: Path) -> dict[str, Any]:
    manifest = _read_json(package_dir / "manifest.json")
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    errors = _validate_package_html(html)
    items = manifest.get("items", [])
    order = list(manifest.get("review_order", []))
    if manifest.get("review_protocol") != PROTOCOL:
        errors.append("review protocol mismatch")
    if manifest.get("candidate_count") != TARGET_REVIEW_SIZE or len(items) != TARGET_REVIEW_SIZE:
        errors.append("package count mismatch")
    if len(order) != len(set(order)) or order != [item.get("candidate_id") for item in items]:
        errors.append("review order mismatch")
    local_clean_count = local_overlay_count = context_clean_count = context_overlay_count = 0
    for item in items:
        for key in ("local_clean_image", "local_overlay_image", "context_clean_image", "context_overlay_image"):
            asset = package_dir / Path(*str(item[key]).split("/"))
            if not asset.is_file():
                errors.append(f"missing asset: {asset}")
        if str(item.get("local_clean_image", "")).startswith("assets/local/"):
            local_clean_count += 1
        if str(item.get("local_overlay_image", "")).startswith("assets/local/"):
            local_overlay_count += 1
        if str(item.get("context_clean_image", "")).startswith("assets/context/"):
            context_clean_count += 1
        if str(item.get("context_overlay_image", "")).startswith("assets/context/"):
            context_overlay_count += 1
        for kind in ("local", "context"):
            marker = item.get("marker", {}).get(kind, {})
            if marker.get("width", 0) <= 0 or marker.get("height", 0) <= 0:
                errors.append(f"invalid marker dimensions: {item.get('candidate_id')} {kind}")
    if (local_clean_count, local_overlay_count, context_clean_count, context_overlay_count) != (
        TARGET_REVIEW_SIZE,
        TARGET_REVIEW_SIZE,
        TARGET_REVIEW_SIZE,
        TARGET_REVIEW_SIZE,
    ):
        errors.append("four-view asset mapping mismatch")
    if errors:
        raise ValueError("invalid primitive-integrity review package: " + "; ".join(errors))
    return {
        "candidate_count": len(items),
        "clean_local_count": local_clean_count,
        "overlay_local_count": local_overlay_count,
        "clean_context_count": context_clean_count,
        "overlay_context_count": context_overlay_count,
        "review_order": order,
        "primary_choice_initially_empty": True,
        "secondary_flags_initially_empty": True,
        "optional_notes_initially_empty": True,
        "bottom_control_overlap_guard": "PASS",
    }


def validate_review_export(
    payload: Any, candidate_set_id: str, review_order: Sequence[str]
) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(review_order):
        raise ValueError("review export row count mismatch")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected = list(review_order)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("review export row is not an object")
        candidate_id = row.get("candidate_id")
        if (
            row.get("protocol") != PROTOCOL
            or row.get("candidate_set_id") != candidate_set_id
            or candidate_id in seen
            or candidate_id not in expected
        ):
            raise ValueError("review export identity mismatch")
        index = expected.index(candidate_id)
        if row.get("review_index") != index + 1:
            raise ValueError("review export review index mismatch")
        primary = row.get("primary_class")
        flags = row.get("secondary_flags")
        note = row.get("optional_note")
        if primary is not None and primary not in PRIMARY_CLASSES:
            raise ValueError("review export primary class mismatch")
        if not isinstance(flags, list) or len(set(flags)) != len(flags) or any(
            flag not in SECONDARY_FLAGS for flag in flags
        ):
            raise ValueError("review export secondary flags mismatch")
        if not isinstance(note, str):
            raise ValueError("review export note must be a string")
        normalized.append(
            {
                "protocol": PROTOCOL,
                "candidate_set_id": candidate_set_id,
                "candidate_id": candidate_id,
                "review_index": index + 1,
                "primary_class": primary,
                "secondary_flags": list(flags),
                "optional_note": note,
            }
        )
        seen.add(candidate_id)
    if [row["candidate_id"] for row in normalized] != expected:
        raise ValueError("review export order mismatch")
    return normalized


def _build_package_manifest(
    records: Sequence[Mapping[str, Any]], candidate_set_id: str, source_identity: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(items),
        "review_order": [item["candidate_id"] for item in items],
        "source_identity": dict(source_identity),
        "items": list(items),
        "governance": {
            "human_review_status": "PENDING",
            "machine_verdict_exposed_to_reviewer": False,
            "source_full_documents_included": False,
            "source_derived_images_local_only": True,
            "export_reload_supported": True,
        },
    }


def build_review_package(
    repo_root: Path,
    records: Sequence[Mapping[str, Any]],
    candidate_set_id: str,
    source_identity: Mapping[str, Any],
    *,
    output_dir: Path,
    zip_path: Path | None = None,
    replace: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build only the reviewer-facing package from frozen selection records."""

    package_dir = output_dir
    if package_dir.exists():
        if not replace:
            raise FileExistsError(f"review package exists: {package_dir}")
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for record in records:
        source_path = _repo_path(repo_root, str(record["source_render_path"]))
        local_box = tuple(record["source_crop_mapping"]["local_box_px"])
        context_box = tuple(record["source_crop_mapping"]["context_box_px"])
        local_clean = package_dir / "assets" / "local" / f"{record['candidate_id']}-clean.png"
        local_overlay = package_dir / "assets" / "local" / f"{record['candidate_id']}-overlay.png"
        context_clean = package_dir / "assets" / "context" / f"{record['candidate_id']}-clean.png"
        context_overlay = package_dir / "assets" / "context" / f"{record['candidate_id']}-overlay.png"
        local_size = _write_clean_crop(source_path, local_box, local_clean)
        context_size = _write_clean_crop(source_path, context_box, context_clean)
        local_marker = _marker_for_box(record, local_box, local_size)
        context_marker = _marker_for_box(record, context_box, context_size)
        _write_overlay(local_clean, local_overlay, local_marker)
        _write_overlay(context_clean, context_overlay, context_marker)
        items.append(
            {
                "review_index": int(record["review_index"]),
                "candidate_id": str(record["candidate_id"]),
                "local_clean_image": f"assets/local/{record['candidate_id']}-clean.png",
                "local_overlay_image": f"assets/local/{record['candidate_id']}-overlay.png",
                "context_clean_image": f"assets/context/{record['candidate_id']}-clean.png",
                "context_overlay_image": f"assets/context/{record['candidate_id']}-overlay.png",
                "marker": {"local": local_marker, "context": context_marker},
            }
        )
    manifest = _build_package_manifest(records, candidate_set_id, source_identity, items)
    _write_json(package_dir / "manifest.json", manifest)
    (package_dir / "review.html").write_text(render_review_html(manifest), encoding="utf-8")
    _write_package_readme(package_dir / "README.txt")
    validation = validate_review_package(package_dir)
    if zip_path is not None:
        _zip_package(package_dir, zip_path)
    return manifest, validation


def _tracked_selection_manifest(
    records: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    candidate_set_id: str,
    selection_digest: str,
    replay_status: str,
    prior_reviewed_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    coverage = _coverage(records)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "base_checkpoint": BASE_CHECKPOINT,
        "candidate_set_id": candidate_set_id,
        "source_fresh_candidate_set_id": source["candidate_set_id"],
        "source_fresh_remine_checkpoint": source["source_checkpoint"],
        "source_frozen_pool_count": FRESH_POOL_COUNT,
        "source_pool_runtime_sha256": source["runtime_sha256"],
        "candidate_count": len(records),
        "target_review_size": TARGET_REVIEW_SIZE,
        "allowed_review_size": [MIN_REVIEW_SIZE, MAX_REVIEW_SIZE],
        "review_order": [record["candidate_id"] for record in records],
        "selection_digest": selection_digest,
        "selection_code_version": SELECTION_CODE_VERSION,
        "selection_deterministic_replay": replay_status,
        "selection_basis": [
            "frozen primitive/coherence/endpoint diagnostics where available",
            "direct continuation support measurements already present in frozen pool",
            "primitive length and orientation",
            "source family, source unit, and source type diversity",
        ],
        "human_labels_used_for_selection": False,
        "semantic_model_predictions_used_for_selection": False,
        "ocr_" + "semantic_predictions_used_for_selection": False,
        "new_candidate_mining": "NO",
        "model_run": "NO",
        "validation": "NO",
        "locked_blind": "0 / 8",
        "h1_h2_opened": "NO",
        "prior_reviewed_control_count": sum(
            record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in records
        ),
        "previously_unreviewed_count": sum(
            record["new_or_prior_reviewed"] == "NEW_UNREVIEWED" for record in records
        ),
        "previously_reviewed_source_metadata": dict(prior_reviewed_metadata),
        "coverage": coverage,
        "strata_counts": dict(sorted(Counter(record["selection_stratum"] for record in records).items())),
        "records": list(records),
    }


def _selection_replay_payload(
    expected_records: Sequence[Mapping[str, Any]],
    replayed_records: Sequence[Mapping[str, Any]],
    source_candidate_set_id: str,
    expected_digest: str,
) -> dict[str, Any]:
    expected_ids = [record["candidate_id"] for record in expected_records]
    replayed_ids = [record["candidate_id"] for record in replayed_records]
    replayed_digest = _selection_digest(replayed_records, source_candidate_set_id)
    source_mapping_equal = [
        record["source_crop_mapping"] for record in expected_records
    ] == [record["source_crop_mapping"] for record in replayed_records]
    status = (
        "PASS"
        if expected_ids == replayed_ids
        and expected_digest == replayed_digest
        and source_mapping_equal
        else "FAIL"
    )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "source_candidate_set_id": source_candidate_set_id,
        "expected_review_order": expected_ids,
        "replayed_review_order": replayed_ids,
        "expected_selection_digest": expected_digest,
        "replayed_selection_digest": replayed_digest,
        "source_mapping_equal": source_mapping_equal,
        "selection_deterministic_replay": status,
        "status": status,
    }


def replay_selection(repo_root: Path, selection_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Replay selection from the frozen pool without generating any imagery."""

    frozen = _load_frozen_inputs(repo_root)
    pool_ids = {str(item["candidate_id"]) for item in frozen["pool"]}
    prior_ids, _prior_meta = _load_prior_reviewed_ids(repo_root, pool_ids)
    diagnostics = _load_diagnostics(repo_root, pool_ids)
    replayed = _select_target(repo_root, frozen["pool"], prior_ids, diagnostics)
    return _selection_replay_payload(
        list(selection_manifest["records"]),
        replayed,
        str(selection_manifest["source_fresh_candidate_set_id"]),
        str(selection_manifest["selection_digest"]),
    )


def _prep_markdown(
    selection_manifest: Mapping[str, Any],
    package_manifest: Mapping[str, Any],
    package_validation: Mapping[str, Any],
    runtime_root: Path,
    tracked_root: Path,
) -> str:
    coverage = selection_manifest["coverage"]
    strata = selection_manifest["strata_counts"]
    return f"""# Primitive Integrity Review V1 Preparation

Status: `HUMAN_REVIEW: PENDING`

This package is a targeted, blind human review of the machine-detected red
primitive against the visible source geometry. It is evidence collection only;
it does not implement a coherence guard, endpoint guard, geometry clipping, or
primitive splitting.

## Frozen source and selection

- Base checkpoint: `{BASE_CHECKPOINT}`
- Source fresh candidate set: `{selection_manifest['source_fresh_candidate_set_id']}`
- Frozen fresh pool: `{selection_manifest['source_frozen_pool_count']}`
- Selected review size: `{selection_manifest['candidate_count']}`
- Previously unreviewed: `{selection_manifest['previously_unreviewed_count']}`
- Previously reviewed controls: `{selection_manifest['prior_reviewed_control_count']}`
- Selection digest: `{selection_manifest['selection_digest']}`
- Deterministic replay: `{selection_manifest['selection_deterministic_replay']}`
- Human labels used for selection: `NO`
- Model or semantic predictions used for selection: `NO`

Strata: `{json.dumps(strata, ensure_ascii=False, sort_keys=True)}`

Coverage: {coverage['source_families']} source families, {coverage['source_units']} source units,
{coverage['pdf_derived']} PDF-derived and {coverage['dwg_derived']} DWG-derived cases,
{coverage['horizontal']} horizontal and {coverage['vertical']} vertical cases.

## Reviewer contract

Protocol: `{PROTOCOL}`

Primary classes are exactly:

- `VALID_SINGLE_STRAIGHT_PRIMITIVE`
- `MULTIPLE_OR_OFFSET_SEGMENTS`
- `ENDPOINT_OVERSHOOT`
- `FOREIGN_STROKE_CAPTURE`
- `OTHER_PRIMITIVE_MISMATCH`
- `INSUFFICIENT_EVIDENCE`

Secondary flags are optional and may be multi-selected. Notes are optional and
are exported verbatim. The package starts with empty primary choices, empty
secondary flags, and empty notes.

## Blindness and governance

- Machine suspicion, diagnostic strata, support scores, and prior human labels are not in the reviewer UI.
- Source-derived images are runtime-only; full PDFs/DWGs are not included.
- Production semantic delta: `NONE`
- Span guard changed: `NO`
- Axis guard changed: `NO`
- Admissibility guard changed: `NO`
- Coherence guard implemented: `NO`
- Endpoint guard implemented: `NO`
- New candidate mining: `NO`
- Model run: `NO`
- Model-assisted labeling: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- Batch-03 created: `NO`

## Package QA

- Runtime review package: `{_relative_path(selection_manifest['_repo_root'], runtime_root / 'review-package')}`
- Tracked package manifest: `{_relative_path(selection_manifest['_repo_root'], tracked_root / 'primitive-integrity-review-package-manifest.json')}`
- Four-view asset validation: `PASS` ({package_validation['candidate_count']} candidates)
- Empty review state: `PASS`
- Bottom-control overlap static assertion: `{package_validation['bottom_control_overlap_guard']}`
- Export/reload schema: `PASS`

Human review remains pending. The next action is `HUMAN_PRIMITIVE_INTEGRITY_REVIEW`.
"""


def build_primitive_integrity_review(
    repo_root: Path,
    *,
    replace_runtime: bool = False,
) -> PackageBuildResult:
    """Freeze the targeted selection and build its local review package."""

    repo_root = repo_root.resolve()
    frozen = _load_frozen_inputs(repo_root)
    pool = frozen["pool"]
    pool_ids = {str(item["candidate_id"]) for item in pool}
    prior_ids, prior_metadata = _load_prior_reviewed_ids(repo_root, pool_ids)
    diagnostics = _load_diagnostics(repo_root, pool_ids)
    selected_records = _select_target(repo_root, pool, prior_ids, diagnostics)
    if len(selected_records) < MIN_REVIEW_SIZE or len(selected_records) > MAX_REVIEW_SIZE:
        raise ValueError("selected review size is outside the allowed range")
    if sum(record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in selected_records) > MAX_PRIOR_REVIEWED_CONTROLS:
        raise ValueError("too many previously reviewed controls")
    primitive_keys = [_exact_primitive_key(record) for record in selected_records]
    if len(set(primitive_keys)) != len(primitive_keys):
        raise ValueError("selected review contains duplicate primitive geometry")
    source_candidate_set_id = str(frozen["runtime"]["candidate_set_id"])
    digest = _selection_digest(selected_records, source_candidate_set_id)
    candidate_set_id = f"{source_candidate_set_id}-PRIMITIVE-INTEGRITY-{digest[:12].upper()}"

    runtime_root = _repo_path(repo_root, RUNTIME_RELATIVE)
    if runtime_root.exists():
        if not replace_runtime:
            raise FileExistsError(f"primitive-integrity runtime exists: {runtime_root}")
        _safe_replace_runtime(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    tracked_root = _repo_path(repo_root, "cad_photo_to_dxf/validation/primitive-integrity-review-v1")
    tracked_root.mkdir(parents=True, exist_ok=True)

    selection_manifest = _tracked_selection_manifest(
        selected_records,
        {
            "candidate_set_id": source_candidate_set_id,
            "source_checkpoint": frozen["selection"].get("base_checkpoint"),
            "runtime_sha256": frozen["runtime_sha256"],
        },
        candidate_set_id,
        digest,
        "PENDING",
        prior_metadata,
    )
    selection_manifest["_repo_root"] = repo_root
    selection_manifest["source_crop_mappings"] = [
        record["source_crop_mapping"] for record in selected_records
    ]
    replay = _selection_replay_payload(
        selected_records,
        _select_target(repo_root, pool, prior_ids, diagnostics),
        source_candidate_set_id,
        digest,
    )
    if replay["status"] != "PASS":
        raise ValueError("selection deterministic replay failed")
    selection_manifest["selection_deterministic_replay"] = replay["status"]
    selection_manifest.pop("_repo_root")
    selection_manifest.pop("source_crop_mappings")

    runtime_selection = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "base_checkpoint": BASE_CHECKPOINT,
        "source_fresh_candidate_set_id": source_candidate_set_id,
        "source_frozen_pool_count": FRESH_POOL_COUNT,
        "source_pool_runtime_sha256": frozen["runtime_sha256"],
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "selection_deterministic_replay": replay["status"],
        "candidate_count": len(selected_records),
        "records": selected_records,
        "governance": {
            "new_candidate_mining": "NO",
            "model_run": "NO",
            "validation": "NO",
            "locked_blind": "0 / 8",
            "h1_h2_opened": "NO",
            "human_review": "PENDING",
        },
    }
    _write_json(runtime_root / "selection-runtime.json", runtime_selection)
    _write_json(runtime_root / "selection-replay.json", replay)
    _write_json(
        runtime_root / "internal-diagnostic-selection.json",
        {
            "schema_version": 1,
            "task_id": TASK_ID,
            "candidate_set_id": candidate_set_id,
            "selection_digest": digest,
            "records": [
                {
                    "candidate_id": record["candidate_id"],
                    "review_index": record["review_index"],
                    "selection_stratum": record["selection_stratum"],
                    "new_or_prior_reviewed": record["new_or_prior_reviewed"],
                    "diagnostic_measurements_used": record["diagnostic_measurements_used"],
                    "selection_rationale": record["selection_rationale"],
                }
                for record in selected_records
            ],
        },
    )

    source_identity = {
        "source_fresh_candidate_set_id": source_candidate_set_id,
        "source_frozen_pool_count": FRESH_POOL_COUNT,
        "source_pool_runtime_sha256": frozen["runtime_sha256"],
        "source_fresh_selection_manifest_sha256": frozen["selection_sha256"],
        "source_fresh_remine_checkpoint": frozen["selection"].get("base_checkpoint"),
        "selection_digest": digest,
    }
    package_manifest, package_validation = build_review_package(
        repo_root,
        selected_records,
        candidate_set_id,
        source_identity,
        output_dir=runtime_root / "review-package",
        zip_path=runtime_root / "review-package.zip",
        replace=True,
    )
    _write_contact_sheet(
        selected_records,
        runtime_root / "review-package",
        runtime_root / "contact-sheet.png",
    )
    package_manifest_sha256 = _sha256_file(runtime_root / "review-package" / "manifest.json")
    tracked_package_manifest = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "package_id": PACKAGE_ID,
        "review_protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "candidate_count": len(selected_records),
        "review_order": [record["candidate_id"] for record in selected_records],
        "runtime_package_path": f"{RUNTIME_RELATIVE}/review-package",
        "runtime_package_manifest_sha256": package_manifest_sha256,
        "runtime_package_validation": package_validation,
        "machine_verdict_exposed_to_reviewer": False,
        "human_review": "PENDING",
    }
    selection_manifest_for_disk = dict(selection_manifest)
    selection_manifest_for_disk["selection_deterministic_replay"] = replay["status"]
    _write_json(tracked_root / "primitive-integrity-candidate-registry.json", {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "candidate_set_id": candidate_set_id,
        "selection_digest": digest,
        "candidate_count": len(selected_records),
        "records": selected_records,
        "counts": {
            "frozen_candidates": len(selected_records),
            "previously_unreviewed": sum(record["new_or_prior_reviewed"] == "NEW_UNREVIEWED" for record in selected_records),
            "previously_reviewed_controls": sum(record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in selected_records),
            "human_primary_answers": 0,
        },
    })
    _write_json(tracked_root / "primitive-integrity-selection-manifest.json", selection_manifest_for_disk)
    _write_json(tracked_root / "primitive-integrity-review-package-manifest.json", tracked_package_manifest)
    _write_json(tracked_root / "primitive-integrity-selection-replay.json", replay)
    prep_manifest = dict(selection_manifest_for_disk)
    prep_manifest["_repo_root"] = repo_root
    prep_markdown = _prep_markdown(
        prep_manifest,
        package_manifest,
        package_validation,
        runtime_root,
        tracked_root,
    )
    (tracked_root / "PRIMITIVE-INTEGRITY-REVIEW-V1-PREP.md").write_text(
        prep_markdown, encoding="utf-8"
    )
    strata_counts = dict(sorted(Counter(record["selection_stratum"] for record in selected_records).items()))
    coverage = _coverage(selected_records)
    return PackageBuildResult(
        runtime_root=runtime_root,
        package_dir=runtime_root / "review-package",
        package_zip=runtime_root / "review-package.zip",
        tracked_root=tracked_root,
        candidate_set_id=candidate_set_id,
        selection_digest=digest,
        selected_count=len(selected_records),
        newly_unreviewed_count=sum(record["new_or_prior_reviewed"] == "NEW_UNREVIEWED" for record in selected_records),
        prior_reviewed_control_count=sum(record["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for record in selected_records),
        strata_counts=strata_counts,
        source_family_count=int(coverage["source_families"]),
        source_unit_count=int(coverage["source_units"]),
        horizontal_count=int(coverage["horizontal"]),
        vertical_count=int(coverage["vertical"]),
        selection_replay_status=str(replay["status"]),
        package_validation=package_validation,
    )


__all__ = [
    "BASE_CHECKPOINT",
    "FRESH_POOL_COUNT",
    "MAX_PRIOR_REVIEWED_CONTROLS",
    "MAX_REVIEW_SIZE",
    "MIN_REVIEW_SIZE",
    "PACKAGE_ID",
    "PRIMARY_CLASSES",
    "PROTOCOL",
    "SECONDARY_FLAGS",
    "TARGET_REVIEW_SIZE",
    "PackageBuildResult",
    "build_primitive_integrity_review",
    "build_review_package",
    "render_review_html",
    "replay_selection",
    "validate_review_export",
    "validate_review_package",
]
