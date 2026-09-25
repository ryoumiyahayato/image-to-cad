"""Deterministically repair the frozen SOURCE_GAP_REVIEW_V1 package.

This module consumes only the existing v1 selection, the unchanged frozen
147-candidate runtime pool, the already-written text/glyph reevaluation, and a
completed v1 human export when one is available.  It does not mine, rerun a
guard, call a model, or change production behavior.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import primitive_integrity_review_v1 as primitive
from . import targeted_source_gap_review_v1 as source_gap


TASK_ID = "TARGETED_SOURCE_GAP_REVIEW_V1_1_REPAIR"
PROTOCOL = source_gap.PROTOCOL
PACKAGE_REVISION = "SOURCE_GAP_REVIEW_V1_1"
PACKAGE_ID = "targeted-source-gap-review-v1-1"
REPAIR_SELECTION_CODE_VERSION = "SOURCE_GAP_REVIEW_V1_REPAIR_CODE_1"
FRESH_POOL_COUNT = source_gap.FRESH_POOL_COUNT
TARGET_REVIEW_SIZE = source_gap.TARGET_REVIEW_SIZE
RUNTIME_RELATIVE = "local-artifacts/draftsman/targeted-source-gap-review-v1-1"
TRACKED_RELATIVE = "cad_photo_to_dxf/validation/targeted-source-gap-review-v1-1"
OLD_TRACKED_RELATIVE = source_gap.TRACKED_RELATIVE
OLD_SELECTION_RELATIVE = f"{OLD_TRACKED_RELATIVE}/source-gap-selection-manifest.json"
TEXT_REEVALUATION_RELATIVE = (
    "local-artifacts/draftsman/text-glyph-primitive-contamination-v1/"
    "frozen147-reevaluation.json"
)
TEXT_SUMMARY_RELATIVE = (
    "cad_photo_to_dxf/validation/text-glyph-primitive-contamination-v1/"
    "frozen147-text-reevaluation-summary.json"
)
FRESH_RUNTIME_RELATIVE = primitive.FRESH_RUNTIME_RELATIVE
FRESH_SELECTION_RELATIVE = primitive.FRESH_SELECTION_RELATIVE


@dataclass(frozen=True)
class RepairBuildResult:
    runtime_root: Path
    package_dir: Path
    package_zip: Path
    tracked_root: Path
    old_candidate_set_id: str
    new_candidate_set_id: str
    old_selection_digest: str
    new_selection_digest: str
    removed_count: int
    retained_count: int
    replacement_count: int
    migrated_answer_count: int
    human_state_migration: str
    selection_replay_status: str
    package_validation: dict[str, Any]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(repo_root: Path, relative: str) -> Path:
    return primitive._repo_path(repo_root, relative)


def _safe_replace_runtime(path: Path) -> None:
    resolved = path.resolve()
    if (
        resolved.name != PACKAGE_ID
        or resolved.parent.name != "draftsman"
        or resolved.parent.parent.name != "local-artifacts"
    ):
        raise ValueError(f"refusing to replace unexpected runtime path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _load_old_selection(repo_root: Path) -> dict[str, Any]:
    manifest = _read_json(_repo_path(repo_root, OLD_SELECTION_RELATIVE))
    records = list(manifest.get("records", []))
    order = list(manifest.get("review_order", []))
    if (
        manifest.get("protocol") != PROTOCOL
        or len(records) != TARGET_REVIEW_SIZE
        or len(order) != TARGET_REVIEW_SIZE
        or order != [str(record.get("candidate_id")) for record in records]
        or len(set(order)) != len(order)
    ):
        raise ValueError("historical source-gap v1 selection is not a valid 16-case package")
    if not manifest.get("candidate_set_id") or not manifest.get("selection_digest"):
        raise ValueError("historical source-gap v1 selection lacks identity")
    return manifest


def _load_text_reevaluation(
    repo_root: Path, pool_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload = _read_json(_repo_path(repo_root, TEXT_REEVALUATION_RELATIVE))
    records = list(payload.get("records", []))
    if len(records) != FRESH_POOL_COUNT:
        raise ValueError(f"text reevaluation changed: {len(records)} != {FRESH_POOL_COUNT}")
    statuses = {str(record["candidate_id"]): record for record in records}
    if set(statuses) != pool_ids:
        raise ValueError("text reevaluation does not cover exactly the frozen 147 pool")
    summary = payload.get("summary", {})
    summary_path = _repo_path(repo_root, TEXT_SUMMARY_RELATIVE)
    summary_file = _read_json(summary_path)
    if summary_file.get("invalid_primitives_in_source_gap_16") != 1:
        raise ValueError("authoritative text summary does not confirm one invalid source-gap primitive")
    rejected_ids = set(summary_file.get("newly_ineligible_candidate_ids", []))
    computed_rejected_ids = {
        candidate_id
        for candidate_id, record in statuses.items()
        if record.get("eligibility_after_guard") != "ELIGIBLE_UNCHANGED"
    }
    if computed_rejected_ids != rejected_ids:
        raise ValueError("text reevaluation rejection set differs from its authoritative summary")
    if int(summary.get("frozen147_text_rejected", -1)) != len(rejected_ids):
        raise ValueError("text reevaluation record count differs from its summary")
    for candidate_id in rejected_ids:
        record = statuses[candidate_id]
        if record.get("text_support_status") != "TEXT_REJECTED":
            raise ValueError(f"non-rejected text status in rejected set: {candidate_id}")
    return statuses, summary_file


def _load_human_export(
    repo_root: Path,
    old_candidate_set_id: str,
    old_order: Sequence[str],
    explicit_path: Path | None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    paths: list[Path] = []
    if explicit_path is not None:
        paths.append(explicit_path.resolve())
    else:
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            paths.extend(sorted(downloads.glob("source-gap-review-v1-*.json")))
        runtime_root = _repo_path(repo_root, source_gap.RUNTIME_RELATIVE)
        if runtime_root.is_dir():
            paths.extend(sorted(runtime_root.rglob("*.json")))
    seen_paths: set[Path] = set()
    errors: list[str] = []
    for path in paths:
        if path in seen_paths or not path.is_file():
            continue
        seen_paths.add(path)
        try:
            payload = _read_json(path)
            rows = source_gap.validate_review_export(payload, old_candidate_set_id, old_order)
            if any(row["primary_class"] is None for row in rows):
                errors.append(f"incomplete human export: {path.name}")
                continue
            return rows, {
                "status": "PASS",
                "source_file_name": path.name,
                "source_file_sha256": _sha256_file(path),
                "source_candidate_set_id": old_candidate_set_id,
                "source_row_count": len(rows),
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return None, {
        "status": "UNAVAILABLE",
        "source_file_name": None,
        "source_file_sha256": None,
        "source_candidate_set_id": old_candidate_set_id,
        "source_row_count": 0,
        "search_scope": ["Downloads/source-gap-review-v1-*.json", f"{source_gap.RUNTIME_RELATIVE}/**/*.json"],
        "search_errors": errors,
    }


def _blank_answer(candidate_id: str, review_index: int) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "review_index": review_index,
        "primary_class": None,
        "secondary_flags": [],
        "optional_note": "",
    }


def _guard_statuses(candidate: Mapping[str, Any]) -> dict[str, str]:
    direct_status = str(candidate.get("direct_continuation", {}).get("status"))
    if direct_status != "DIRECT_CONTINUATION_ADMISSIBLE":
        raise ValueError(f"replacement candidate is not admissible: {candidate.get('candidate_id')}")
    return {
        "span_status": "SPAN_INTEGRITY_SUPPORTED",
        "axis_status": "AXIS_SUPPORT_SUPPORTED",
        "admissibility_status": direct_status,
    }


def _stratum_candidates(
    candidates: Sequence[Mapping[str, Any]],
    stratum: str,
    measurements: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if stratum == "PATTERNED_VISIBLE_SEGMENTS":
        return [
            candidate
            for candidate in candidates
            if float(measurements[str(candidate["candidate_id"])] ["local_density_fraction"]) < 0.15
            and float(measurements[str(candidate["candidate_id"])] ["gap_length_px"]) >= 20.0
            and int(measurements[str(candidate["candidate_id"])] ["supported_run_count"]) >= 2
        ]
    if stratum == "DEGRADATION_LIKE_GAP":
        return [
            candidate
            for candidate in candidates
            if measurements[str(candidate["candidate_id"])] ["source_quality_bin"] == "DEGRADED_OR_SCANNED"
            and float(measurements[str(candidate["candidate_id"])] ["local_density_fraction"]) < 0.20
            and float(measurements[str(candidate["candidate_id"])] ["gap_length_px"]) >= 12.0
            and int(measurements[str(candidate["candidate_id"])] ["direct_transverse_crossing_columns"]) <= 2
        ]
    if stratum == "IRREGULAR_SEPARATE_SEGMENTS":
        return [
            candidate
            for candidate in candidates
            if float(measurements[str(candidate["candidate_id"])] ["local_density_fraction"]) < 0.20
            and int(measurements[str(candidate["candidate_id"])] ["supported_run_count"]) >= 2
        ]
    return list(candidates)


def _select_replacements(
    repo_root: Path,
    frozen: Mapping[str, Any],
    old_selection: Mapping[str, Any],
    text_statuses: Mapping[str, Mapping[str, Any]],
    removed_records: Sequence[Mapping[str, Any]],
    retained_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pool = list(frozen["pool"])
    pool_ids = {str(candidate["candidate_id"]) for candidate in pool}
    prior_ids, _ = source_gap._load_prior_reviewed_ids(repo_root, pool_ids)
    diagnostics = source_gap.primitive._load_diagnostics(repo_root, pool_ids)
    measurements = {
        str(candidate["candidate_id"]): source_gap._selection_measurements(
            repo_root, candidate, diagnostics.get(str(candidate["candidate_id"]))
        )
        for candidate in pool
    }
    retained_ids = {str(record["candidate_id"]) for record in retained_records}
    rejected_ids = {
        candidate_id
        for candidate_id, status in text_statuses.items()
        if status.get("eligibility_after_guard") != "ELIGIBLE_UNCHANGED"
    }
    used_primitive_keys = {
        source_gap.primitive._exact_primitive_key(record) for record in retained_records
    }
    available = [
        candidate
        for candidate in pool
        if str(candidate["candidate_id"]) not in prior_ids
        and str(candidate["candidate_id"]) not in retained_ids
        and str(candidate["candidate_id"]) not in rejected_ids
        and text_statuses[str(candidate["candidate_id"])] ["eligibility_after_guard"] == "ELIGIBLE_UNCHANGED"
        and float(candidate.get("gap_length_px", 0.0)) > 0.0
    ]
    replacements: list[dict[str, Any]] = []
    replacement_provenance: list[dict[str, Any]] = []
    used_families = {str(record["source_family"]) for record in retained_records}
    used_units = {str(record["source_unit"]) for record in retained_records}
    for removed in sorted(removed_records, key=lambda record: int(record["review_index"])):
        stratum = str(removed["selection_stratum"])
        candidates = [
            candidate
            for candidate in available
            if str(candidate["candidate_id"]) not in {str(item["candidate_id"]) for item in replacements}
            and source_gap.primitive._exact_primitive_key(candidate) not in used_primitive_keys
        ]
        candidates = _stratum_candidates(candidates, stratum, measurements)
        if not candidates:
            raise ValueError(f"replacement stratum is undersupplied: {stratum}")
        ranked: list[tuple[float, str, float, float, Mapping[str, Any]]] = []
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            base_score = float(source_gap._score(measurements[candidate_id], stratum))
            diversity_bonus = (
                0.22 * (str(candidate["source_family_id"]) not in used_families)
                + 0.12 * (str(candidate["selected_unit_id"]) not in used_units)
            )
            ranked.append(
                (
                    base_score + diversity_bonus,
                    candidate_id,
                    base_score,
                    diversity_bonus,
                    candidate,
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        combined_score, candidate_id, base_score, diversity_bonus, chosen = ranked[0]
        rank = next(index for index, item in enumerate(ranked, start=1) if item[1] == candidate_id)
        selected_candidate = dict(chosen)
        selected_candidate["selection_stratum"] = stratum
        selected_candidate["selection_measurements"] = dict(measurements[candidate_id])
        selected_candidate["prior_reviewed_control"] = False
        replacement_record = source_gap.primitive._attach_source_mapping(
            repo_root, [selected_candidate]
        )[0]
        replacement_record["review_index"] = int(removed["review_index"])
        replacement_record["new_or_prior_reviewed"] = "NEW_UNREVIEWED"
        replacements.append(replacement_record)
        used_primitive_keys.add(source_gap.primitive._exact_primitive_key(replacement_record))
        used_families.add(str(chosen["source_family_id"]))
        used_units.add(str(chosen["selected_unit_id"]))
        guard_status = _guard_statuses(chosen)
        replacement_provenance.append(
            {
                "candidate_id": candidate_id,
                "source_family": str(chosen["source_family_id"]),
                "source_unit": str(chosen["selected_unit_id"]),
                "orientation": str(chosen["orientation"]),
                "diagnostic_stratum": stratum,
                "selection_score": {
                    "base_score": round(base_score, 6),
                    "diversity_bonus": round(diversity_bonus, 6),
                    "combined_score": round(combined_score, 6),
                    "eligible_rank": rank,
                    "eligible_count": len(ranked),
                },
                "prior_review_status": "PREVIOUSLY_UNREVIEWED",
                "text_glyph_status": str(text_statuses[candidate_id]["text_support_status"]),
                "text_eligibility": str(text_statuses[candidate_id]["eligibility_after_guard"]),
                **guard_status,
                "visible_gap_length_px": float(chosen["gap_length_px"]),
                "reason_selected": (
                    "Matched the removed candidate's AMBIGUOUS_EDGE_CASES stratum using "
                    "the original SOURCE_GAP_REVIEW_V1 deterministic rank after excluding "
                    "text-rejected, retained, prior-reviewed, and exact-duplicate candidates."
                ),
            }
        )
    return replacements, replacement_provenance


def _prepare_repair(repo_root: Path) -> dict[str, Any]:
    old_selection = _load_old_selection(repo_root)
    frozen = primitive._load_frozen_inputs(repo_root)
    pool_ids = {str(candidate["candidate_id"]) for candidate in frozen["pool"]}
    if len(pool_ids) != FRESH_POOL_COUNT:
        raise ValueError("frozen pool identity changed")
    text_statuses, text_summary = _load_text_reevaluation(repo_root, pool_ids)
    old_records = list(old_selection["records"])
    removed_records = [
        record
        for record in old_records
        if text_statuses[str(record["candidate_id"])] ["eligibility_after_guard"] != "ELIGIBLE_UNCHANGED"
    ]
    retained_records = [
        record
        for record in old_records
        if text_statuses[str(record["candidate_id"])] ["eligibility_after_guard"] == "ELIGIBLE_UNCHANGED"
    ]
    for removed in removed_records:
        status = text_statuses[str(removed["candidate_id"])]
        if status.get("text_support_status") != "TEXT_REJECTED":
            raise ValueError(f"current source-gap removal is not text-rejected: {removed['candidate_id']}")
    replacements, replacement_provenance = _select_replacements(
        repo_root,
        frozen,
        old_selection,
        text_statuses,
        removed_records,
        retained_records,
    )
    replacements_by_index = {
        int(record["review_index"]): record for record in replacements
    }
    final_records: list[dict[str, Any]] = []
    for old_record in old_records:
        review_index = int(old_record["review_index"])
        final_records.append(
            dict(replacements_by_index.get(review_index, old_record))
        )
    final_ids = [str(record["candidate_id"]) for record in final_records]
    if len(final_records) != TARGET_REVIEW_SIZE or len(set(final_ids)) != TARGET_REVIEW_SIZE:
        raise ValueError("repaired source-gap selection does not contain exactly 16 unique candidates")
    if [record["review_index"] for record in final_records] != list(range(1, TARGET_REVIEW_SIZE + 1)):
        raise ValueError("repaired review indexes are not contiguous")
    if any(
        source_gap.primitive._exact_primitive_key(left)
        == source_gap.primitive._exact_primitive_key(right)
        for index, left in enumerate(final_records)
        for right in final_records[index + 1 :]
    ):
        raise ValueError("repaired selection contains duplicate primitives")
    return {
        "old_selection": old_selection,
        "frozen": frozen,
        "text_statuses": text_statuses,
        "text_summary": text_summary,
        "old_records": old_records,
        "removed_records": removed_records,
        "retained_records": retained_records,
        "replacements": replacements,
        "replacement_provenance": replacement_provenance,
        "final_records": final_records,
    }


def _repair_selection_digest(prepared: Mapping[str, Any]) -> str:
    old_selection = prepared["old_selection"]
    records = prepared["final_records"]
    payload = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "package_revision": PACKAGE_REVISION,
        "repair_selection_code_version": REPAIR_SELECTION_CODE_VERSION,
        "protocol": PROTOCOL,
        "source_fresh_candidate_set_id": old_selection["source_fresh_candidate_set_id"],
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "old_selection_digest": old_selection["selection_digest"],
        "retained_candidate_ids": [record["candidate_id"] for record in prepared["retained_records"]],
        "removed_candidate_ids": [record["candidate_id"] for record in prepared["removed_records"]],
        "replacement_candidate_ids": [record["candidate_id"] for record in prepared["replacements"]],
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
            }
            for record in records
        ],
        "replacement_provenance": prepared["replacement_provenance"],
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _candidate_set_id(old_candidate_set_id: str, digest: str) -> str:
    return f"{old_candidate_set_id}-REPAIRED-{digest[:12].upper()}"


def _human_migration(
    old_selection: Mapping[str, Any],
    final_records: Sequence[Mapping[str, Any]],
    removed_records: Sequence[Mapping[str, Any]],
    replacements: Sequence[Mapping[str, Any]],
    human_rows: Sequence[Mapping[str, Any]] | None,
    human_metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    answers = {str(row["candidate_id"]): dict(row) for row in human_rows or []}
    old_index = {
        str(candidate_id): index
        for index, candidate_id in enumerate(old_selection["review_order"], start=1)
    }
    initial_state: list[dict[str, Any]] = []
    migrated: list[dict[str, Any]] = []
    removed_history: list[dict[str, Any]] = []
    replacement_ids = {str(record["candidate_id"]) for record in replacements}
    for record in final_records:
        candidate_id = str(record["candidate_id"])
        if candidate_id in answers:
            answer = answers[candidate_id]
            state = {
                "candidate_id": candidate_id,
                "review_index": int(record["review_index"]),
                "primary_class": answer["primary_class"],
                "secondary_flags": list(answer["secondary_flags"]),
                "optional_note": answer["optional_note"],
            }
            migrated.append(
                {
                    **state,
                    "source_review_index": old_index[candidate_id],
                    "migration": "RETAINED_UNCHANGED",
                }
            )
        else:
            state = _blank_answer(candidate_id, int(record["review_index"]))
        initial_state.append(state)
    for record in removed_records:
        candidate_id = str(record["candidate_id"])
        if candidate_id in answers:
            removed_history.append(
                {
                    "old_review_index": old_index[candidate_id],
                    "candidate_id": candidate_id,
                    "prior_human_answer": {
                        "primary_class": answers[candidate_id]["primary_class"],
                        "secondary_flags": list(answers[candidate_id]["secondary_flags"]),
                        "optional_note": answers[candidate_id]["optional_note"],
                    },
                }
            )
    status = str(human_metadata.get("status", "UNAVAILABLE"))
    if status == "PASS" and len(migrated) != len(final_records) - len(replacements):
        status = "PARTIAL"
    payload = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_revision": PACKAGE_REVISION,
        "status": status,
        "source": dict(human_metadata),
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "new_candidate_set_id": None,
        "migrated_human_answers": migrated,
        "migrated_answer_count": len(migrated),
        "removed_human_answers_retained_as_history": removed_history,
        "removed_human_answer_history_count": len(removed_history),
        "replacement_candidate_ids": sorted(replacement_ids),
        "replacement_answers_prefilled": "NO",
        "initial_review_state": initial_state,
    }
    return payload, initial_state


def replay_repaired_selection(repo_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    prepared = _prepare_repair(repo_root)
    digest = _repair_selection_digest(prepared)
    replayed_order = [record["candidate_id"] for record in prepared["final_records"]]
    expected_order = list(manifest["final_review_order"])
    expected_mappings = list(manifest["source_mappings"])
    replayed_mappings = [
        {
            "candidate_id": record["candidate_id"],
            "source_crop_mapping": record["source_crop_mapping"],
        }
        for record in prepared["final_records"]
    ]
    status = "PASS" if (
        expected_order == replayed_order
        and manifest["new_selection_digest"] == digest
        and expected_mappings == replayed_mappings
        and manifest["new_candidate_set_id"] == _candidate_set_id(
            str(prepared["old_selection"]["candidate_set_id"]), digest
        )
    ) else "FAIL"
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_revision": PACKAGE_REVISION,
        "old_candidate_set_id": prepared["old_selection"]["candidate_set_id"],
        "new_candidate_set_id": manifest["new_candidate_set_id"],
        "expected_order": expected_order,
        "replayed_order": replayed_order,
        "expected_selection_digest": manifest["new_selection_digest"],
        "replayed_selection_digest": digest,
        "source_mapping_equal": expected_mappings == replayed_mappings,
        "selection_deterministic_replay": status,
        "status": status,
        "new_candidate_mining": "NO",
    }


def _prep_report(
    prepared: Mapping[str, Any],
    new_candidate_set_id: str,
    new_digest: str,
    migration: Mapping[str, Any],
    package_validation: Mapping[str, Any],
    runtime_path: str,
    tracked_path: str,
) -> str:
    old_selection = prepared["old_selection"]
    removed = prepared["removed_records"]
    retained = prepared["retained_records"]
    replacements = prepared["replacements"]
    return f"""# Targeted Source Gap Review V1.1 Preparation

Status: `HUMAN_REVIEW: PENDING_REPLACEMENT_ONLY`

This is a deterministic package repair of the existing SOURCE_GAP_REVIEW_V1
selection. It consumes the unchanged frozen 147 pool and the completed
text/glyph reevaluation. It does not remine, rerun guards, run a model, or
modify production behavior.

## Repair result

- Old candidate-set ID: `{old_selection['candidate_set_id']}`
- New candidate-set ID: `{new_candidate_set_id}`
- Old selection digest: `{old_selection['selection_digest']}`
- New selection digest: `{new_digest}`
- Frozen fresh pool: `{FRESH_POOL_COUNT}`
- Old review size: `{len(old_selection['review_order'])}`
- Removed invalid candidates: `{len(removed)}`
- Retained candidates: `{len(retained)}`
- Deterministic replacements: `{len(replacements)}`
- Final review size: `{len(prepared['final_records'])}`
- Retained order preserved: `YES`
- Selection deterministic replay: `PASS`

The removed candidate is replaced at its old review index. The replacement was
selected from the same frozen pool by matching the removed
`{removed[0]['selection_stratum'] if removed else 'N/A'}` stratum and applying the original deterministic ranking after the text/glyph eligibility filter. Human answers were not used for selection.

## Human-state migration

- Migration status: `{migration['status']}`
- Migrated retained answers: `{migration['migrated_answer_count']}`
- Removed answers retained as history: `{migration['removed_human_answer_history_count']}`
- Replacement answers prefilled: `NO`

## Reviewer UI

The human-facing title remains `原图断开位置检查` and the protocol remains
`{PROTOCOL}`. The six existing primary choices are unchanged. The seventh
fail-closed option is `候选本身无效`; it is not preselected and machine
verdicts are not exposed.

## Governance

- Production semantic delta: `NONE`
- New candidate mining: `NO`
- Span / axis / text-glyph / admissibility guards changed: `NO / NO / NO / NO`
- Source-continuity / endpoint guards implemented: `NO / NO`
- Model run / model-assisted labeling: `NO / NO`
- Validation: `NO`
- Locked blind: `0 / 8`; H1/H2 opened: `NO`; Batch-03 created: `NO`
- Runtime package: `{runtime_path}`
- Static package QA: `{package_validation.get('four_view_assets') == 'PASS' and 'PASS' or 'FAIL'}`

Next: `HUMAN_REVIEW_REPLACEMENT_CASES_ONLY`.
"""


def build_repaired_source_gap_review(
    repo_root: Path,
    *,
    human_export: Path | None = None,
    replace_runtime: bool = False,
) -> RepairBuildResult:
    repo_root = repo_root.resolve()
    prepared = _prepare_repair(repo_root)
    old_selection = prepared["old_selection"]
    new_digest = _repair_selection_digest(prepared)
    new_candidate_set_id = _candidate_set_id(str(old_selection["candidate_set_id"]), new_digest)
    human_rows, human_metadata = _load_human_export(
        repo_root,
        str(old_selection["candidate_set_id"]),
        old_selection["review_order"],
        human_export,
    )
    migration, initial_state = _human_migration(
        old_selection,
        prepared["final_records"],
        prepared["removed_records"],
        prepared["replacements"],
        human_rows,
        human_metadata,
    )
    migration["new_candidate_set_id"] = new_candidate_set_id
    legacy_import = {
        "protocol": PROTOCOL,
        "candidate_set_id": old_selection["candidate_set_id"],
        "review_order": list(old_selection["review_order"]),
        "review_index_by_candidate_id": {
            str(candidate_id): index
            for index, candidate_id in enumerate(old_selection["review_order"], start=1)
        },
        "retained_candidate_ids": [record["candidate_id"] for record in prepared["retained_records"]],
        "removed_candidate_ids": [record["candidate_id"] for record in prepared["removed_records"]],
        "replacement_candidate_ids": [record["candidate_id"] for record in prepared["replacements"]],
        "id_map": {
            record["candidate_id"]: record["candidate_id"]
            for record in prepared["retained_records"]
        },
    }
    source_identity = {
        "source_fresh_candidate_set_id": old_selection["source_fresh_candidate_set_id"],
        "source_frozen_pool_count": FRESH_POOL_COUNT,
        "source_pool_runtime_sha256": prepared["frozen"]["runtime_sha256"],
        "source_fresh_selection_manifest_sha256": prepared["frozen"]["selection_sha256"],
        "source_checkpoint": old_selection.get("source_checkpoint"),
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "old_selection_digest": old_selection["selection_digest"],
        "selection_digest": new_digest,
        "package_revision": PACKAGE_REVISION,
    }
    runtime_root = _repo_path(repo_root, RUNTIME_RELATIVE)
    if runtime_root.exists():
        if not replace_runtime:
            raise FileExistsError(runtime_root)
        _safe_replace_runtime(runtime_root)
    runtime_root.mkdir(parents=True)
    tracked_root = _repo_path(repo_root, TRACKED_RELATIVE)
    tracked_root.mkdir(parents=True, exist_ok=True)
    package_dir = runtime_root / "review-package"
    package_zip = runtime_root / "review-package.zip"
    package_manifest, package_validation = source_gap.build_review_package(
        repo_root,
        prepared["final_records"],
        new_candidate_set_id,
        source_identity,
        output_dir=package_dir,
        zip_path=package_zip,
        replace=True,
        package_id=PACKAGE_ID,
        package_revision=PACKAGE_REVISION,
        initial_review_state=initial_state,
        legacy_import=legacy_import,
        human_review_status="PENDING_REPLACEMENT_ONLY",
        readme_text=(
            "SOURCE_GAP_REVIEW_V1\n\n"
            "原图中这根线在这些断开位置，最接近哪种情况？\n"
            "红色表示检测到的整体线范围；黄色标记表示本次重点查看的断开位置。\n"
            "保留案例的历史审核答案已迁移；新增替换案例答案为空。\n\n"
            "HUMAN_REVIEW: PENDING_REPLACEMENT_ONLY\n"
            "PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED\n"
        ),
    )
    selection_manifest = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_revision": PACKAGE_REVISION,
        "source_fresh_candidate_set_id": old_selection["source_fresh_candidate_set_id"],
        "source_frozen_pool_count": FRESH_POOL_COUNT,
        "source_pool_runtime_sha256": prepared["frozen"]["runtime_sha256"],
        "source_fresh_selection_manifest_sha256": prepared["frozen"]["selection_sha256"],
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "new_candidate_set_id": new_candidate_set_id,
        "old_selection_digest": old_selection["selection_digest"],
        "new_selection_digest": new_digest,
        "retained_candidate_ids": [record["candidate_id"] for record in prepared["retained_records"]],
        "removed_candidate_ids": [record["candidate_id"] for record in prepared["removed_records"]],
        "replacement_candidate_ids": [record["candidate_id"] for record in prepared["replacements"]],
        "final_review_order": [record["candidate_id"] for record in prepared["final_records"]],
        "retained_order_preserved": True,
        "selection_rule": (
            "Match each removed candidate's original diagnostic stratum where possible; "
            "rank only the unchanged frozen pool after span, axis, text/glyph, and "
            "direct-continuation/admissibility eligibility, excluding prior-reviewed, "
            "retained, rejected, and exact-duplicate candidates."
        ),
        "human_answers_used_for_selection": False,
        "model_assisted_selection": False,
        "records": prepared["final_records"],
        "source_mappings": [
            {
                "candidate_id": record["candidate_id"],
                "source_crop_mapping": record["source_crop_mapping"],
            }
            for record in prepared["final_records"]
        ],
        "replacement_provenance": prepared["replacement_provenance"],
        "governance": {
            "new_candidate_mining": "NO",
            "span_guard_changed": "NO",
            "axis_guard_changed": "NO",
            "text_glyph_guard_changed": "NO",
            "admissibility_guard_changed": "NO",
            "source_continuity_guard_implemented": "NO",
            "endpoint_guard_implemented": "NO",
            "model_run": "NO",
            "model_assisted_labeling": "NO",
            "validation": "NO",
            "locked_blind": "0 / 8",
            "h1_h2_opened": "NO",
            "production_semantic_delta": "NONE",
        },
    }
    selection_replay = replay_repaired_selection(repo_root, selection_manifest)
    if selection_replay["status"] != "PASS":
        raise ValueError("repaired source-gap selection deterministic replay failed")
    removed_payload = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_revision": PACKAGE_REVISION,
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "removed_candidates": [
            {
                "old_review_index": record["review_index"],
                "candidate_id": record["candidate_id"],
                "text_glyph_status": prepared["text_statuses"][record["candidate_id"]]["text_support_status"],
                "eligibility_reason": prepared["text_statuses"][record["candidate_id"]]["eligibility_after_guard"],
                "prior_human_answer": next(
                    (
                        item["prior_human_answer"]
                        for item in migration["removed_human_answers_retained_as_history"]
                        if item["candidate_id"] == record["candidate_id"]
                    ),
                    None,
                ),
                "reason_removed_from_repaired_package": "Text/glyph guard marks glyph-only support; the source-gap taxonomy requires a valid primitive.",
            }
            for record in prepared["removed_records"]
        ],
    }
    replacement_payload = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_revision": PACKAGE_REVISION,
        "new_candidate_set_id": new_candidate_set_id,
        "replacement_candidates": prepared["replacement_provenance"],
    }
    repair_manifest = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "protocol": PROTOCOL,
        "package_id": PACKAGE_ID,
        "package_revision": PACKAGE_REVISION,
        "old_candidate_set_id": old_selection["candidate_set_id"],
        "new_candidate_set_id": new_candidate_set_id,
        "old_selection_digest": old_selection["selection_digest"],
        "new_selection_digest": new_digest,
        "frozen_fresh_pool": FRESH_POOL_COUNT,
        "old_review_size": len(old_selection["review_order"]),
        "invalid_current_candidates_removed": len(prepared["removed_records"]),
        "retained_current_candidates": len(prepared["retained_records"]),
        "replacement_candidates": len(prepared["replacements"]),
        "final_review_size": len(prepared["final_records"]),
        "text_rejected_in_final_review": sum(
            prepared["text_statuses"][record["candidate_id"]]["text_support_status"] == "TEXT_REJECTED"
            for record in prepared["final_records"]
        ),
        "text_uncertain_in_final_review": sum(
            prepared["text_statuses"][record["candidate_id"]]["text_support_status"] == "TEXT_UNCERTAIN"
            for record in prepared["final_records"]
        ),
        "previously_unreviewed_replacements": sum(
            item["prior_review_status"] == "PREVIOUSLY_UNREVIEWED"
            for item in prepared["replacement_provenance"]
        ),
        "retained_order_preserved": True,
        "selection_deterministic_replay": selection_replay["status"],
        "selection_rule": selection_manifest["selection_rule"],
        "removed_candidates": removed_payload["removed_candidates"],
        "replacement_candidates_provenance": replacement_payload["replacement_candidates"],
        "human_state_migration": migration["status"],
        "migrated_human_answers": migration["migrated_answer_count"],
        "removed_human_answers_retained_as_history": migration["removed_human_answer_history_count"],
        "replacement_answers_prefilled": "NO",
        "invalid_primitive_fail_closed_option": True,
        "visible_primary_options": 7,
        "machine_verdict_exposed": False,
        "guard_changes": {
            "span": "NO",
            "axis": "NO",
            "text_glyph": "NO",
            "admissibility": "NO",
        },
        "governance": selection_manifest["governance"],
        "runtime_package_path": f"{RUNTIME_RELATIVE}/review-package",
        "runtime_package_manifest_sha256": _sha256_file(package_dir / "manifest.json"),
        "package_validation": package_validation,
    }
    migration["new_candidate_set_id"] = new_candidate_set_id
    for path, payload in (
        (runtime_root / "selection-repair.json", selection_manifest),
        (runtime_root / "selection-replay.json", selection_replay),
        (runtime_root / "human-state-migration.json", migration),
        (runtime_root / "removed-candidates.json", removed_payload),
        (runtime_root / "replacement-candidates.json", replacement_payload),
        (runtime_root / "repair-manifest.json", repair_manifest),
    ):
        _write_json(path, payload)
    for filename, payload in (
        ("source-gap-v1-1-selection-manifest.json", selection_manifest),
        ("source-gap-v1-1-repair-manifest.json", repair_manifest),
        ("source-gap-v1-1-selection-replay.json", selection_replay),
        ("source-gap-v1-1-human-state-migration.json", migration),
        ("source-gap-v1-1-removed-candidates.json", removed_payload),
        ("source-gap-v1-1-replacement-candidates.json", replacement_payload),
    ):
        _write_json(tracked_root / filename, payload)
    _write_json(
        tracked_root / "source-gap-v1-1-review-package-manifest.json",
        {
            "schema_version": 1,
            "task_id": TASK_ID,
            "package_id": PACKAGE_ID,
            "package_revision": PACKAGE_REVISION,
            "review_protocol": PROTOCOL,
            "candidate_set_id": new_candidate_set_id,
            "candidate_count": TARGET_REVIEW_SIZE,
            "review_order": selection_manifest["final_review_order"],
            "runtime_package_path": f"{RUNTIME_RELATIVE}/review-package",
            "runtime_package_manifest_sha256": repair_manifest["runtime_package_manifest_sha256"],
            "package_validation": package_validation,
            "human_review": "PENDING_REPLACEMENT_ONLY",
            "machine_verdict_exposed_to_reviewer": False,
        },
    )
    tracked_prep = _repo_path(repo_root, f"{TRACKED_RELATIVE}/TARGETED-SOURCE-GAP-REVIEW-V1-1-PREP.md")
    tracked_prep.write_text(
        _prep_report(
            prepared,
            new_candidate_set_id,
            new_digest,
            migration,
            package_validation,
            f"{RUNTIME_RELATIVE}/review-package",
            f"{TRACKED_RELATIVE}/source-gap-v1-1-repair-manifest.json",
        ),
        encoding="utf-8",
    )
    return RepairBuildResult(
        runtime_root=runtime_root,
        package_dir=package_dir,
        package_zip=package_zip,
        tracked_root=tracked_root,
        old_candidate_set_id=str(old_selection["candidate_set_id"]),
        new_candidate_set_id=new_candidate_set_id,
        old_selection_digest=str(old_selection["selection_digest"]),
        new_selection_digest=new_digest,
        removed_count=len(prepared["removed_records"]),
        retained_count=len(prepared["retained_records"]),
        replacement_count=len(prepared["replacements"]),
        migrated_answer_count=int(migration["migrated_answer_count"]),
        human_state_migration=str(migration["status"]),
        selection_replay_status=str(selection_replay["status"]),
        package_validation=package_validation,
    )


__all__ = [
    "FRESH_POOL_COUNT",
    "PACKAGE_ID",
    "PACKAGE_REVISION",
    "PROTOCOL",
    "RUNTIME_RELATIVE",
    "RepairBuildResult",
    "build_repaired_source_gap_review",
    "replay_repaired_selection",
]
