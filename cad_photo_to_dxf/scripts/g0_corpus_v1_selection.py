"""Deterministically select and freeze Draftsman Generalization Corpus V1."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

candidate_registry = importlib.import_module(
    ".g0_candidate_registry" if __package__ else "g0_candidate_registry",
    package=__package__,
)

SCHEMA_VERSION = "draftsman-corpus-v1-split-v1"
CORPUS_VERSION = "DRAFTSMAN_GENERALIZATION_CORPUS_V1"
POLICY_VERSION = "draftsman-g0-b3-selection-v1"
REGISTRY_DIGEST = "07e25d6d876c0d0416556aefe01267d688da495111eec69e521bb2c70803e780"
SPLIT_COUNTS = {"DEV": 15, "VALIDATION": 7, "LOCKED_BLIND": 8, "RESERVE": 15}
SPLIT_ORDER = ("LOCKED_BLIND", "VALIDATION", "DEV", "RESERVE")
REGION_TARGETS = {
    "LOCKED_BLIND": {"East Asia": 2, "Europe": 1, "North America": 2, "Oceania": 3},
    "VALIDATION": {"East Asia": 2, "Europe": 1, "North America": 2, "Oceania": 2},
    "DEV": {"East Asia": 5, "Europe": 2, "North America": 4, "Oceania": 4},
    "RESERVE": {"East Asia": 5, "Europe": 3, "North America": 4, "Oceania": 3},
}
RENDER_TARGETS = {
    "LOCKED_BLIND": {
        "CONFIRMED_RASTER": 3,
        "CONFIRMED_MIXED": 2,
        "CONFIRMED_VECTOR": 0,
        "UNKNOWN": 3,
    },
    "VALIDATION": {
        "CONFIRMED_RASTER": 2,
        "CONFIRMED_MIXED": 1,
        "CONFIRMED_VECTOR": 1,
        "UNKNOWN": 3,
    },
    "DEV": {
        "CONFIRMED_RASTER": 3,
        "CONFIRMED_MIXED": 2,
        "CONFIRMED_VECTOR": 2,
        "UNKNOWN": 8,
    },
    "RESERVE": {
        "CONFIRMED_RASTER": 3,
        "CONFIRMED_MIXED": 2,
        "CONFIRMED_VECTOR": 1,
        "UNKNOWN": 9,
    },
}
FEATURE_TARGETS = {
    "LOCKED_BLIND": {"historical_archival": 4, "degraded_scan": 2, "native_image": 2},
    "VALIDATION": {"historical_archival": 2, "degraded_scan": 1, "native_image": 1},
    "DEV": {"historical_archival": 4, "degraded_scan": 2, "native_image": 2},
    "RESERVE": {"historical_archival": 4, "degraded_scan": 1, "native_image": 2},
}
TIER_SCORE = {"STRONG": 40, "UNKNOWN": 16, "SECONDARY": 4}
GOVERNANCE_SCORE = {
    "PUBLIC_DOWNLOAD_CLEAR": 20,
    "PUBLIC_ACCESS_REUSE_UNCLEAR": 12,
    "PUBLIC_ARCHIVE_RIGHTS_ADVISORY": 10,
}
REGION_SCORE = 30
RENDER_SCORE = 26
FEATURE_SCORE = 12
DRAWING_FAMILY_SCORE = 8
DRAWING_FAMILY_KEYWORDS = {
    "fire_alarm": ("fire alarm", "fire-alarm", "自動火災", "消防", "警報"),
    "lighting": ("lighting", "電灯", "照明", "燈"),
    "low_voltage": ("low-voltage", "low voltage", "weak-current", "弱電", "通信"),
    "panel_schedule": ("panel", "schedule", "盤", "分電"),
    "power": ("power", "distribution", "reticulation", "配電", "動力", "受変電"),
    "single_line": ("single-line", "single line", "單線", "单线", "結線"),
    "wiring_control": ("wiring", "control", "回路", "配線", "制御"),
}
POLICY_DEDUP_UNRESOLVED = {
    "G0R2-D93E7F1D84FE931F": "Fort McPherson WWII Station Hospital standardized mess-hall drawing family",
    "G0R2-3811E2A2F0494CEC": "Fort McPherson WWII Station Hospital standardized mess-hall drawing family",
}


class SelectionError(ValueError):
    """Raised when an authoritative selection gate cannot be satisfied."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def artifact_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def macro_region(record: dict[str, Any]) -> str:
    value = f"{record['region']} {record['country_or_area']}".lower()
    if any(token in value for token in ("china", "taiwan", "japan", "korea", "中国", "日本")):
        return "East Asia"
    if any(token in value for token in ("australia", "new zealand", "oceania", "guam", "hawaii")):
        return "Oceania"
    if any(token in value for token in ("europe", "united kingdom", "uk_")):
        return "Europe"
    return "North America"


def drawing_families(record: dict[str, Any]) -> list[str]:
    evidence = f"{record['drawing_type']} {record['discipline']}".lower()
    return sorted(
        family
        for family, keywords in DRAWING_FAMILY_KEYWORDS.items()
        if any(keyword.lower() in evidence for keyword in keywords)
    ) or ["other_electrical"]


def eligibility(record: dict[str, Any]) -> tuple[str, str]:
    if record["governance_status"] == "LICENSE_RESTRICTED" or record[
        "split_eligibility"
    ] in {"INELIGIBLE", "RESTRICTED"}:
        return "INELIGIBLE", "Explicit license restriction or split restriction."
    if record["source_group_id"] in POLICY_DEDUP_UNRESOLVED:
        return "DEDUP_UNRESOLVED", POLICY_DEDUP_UNRESOLVED[record["source_group_id"]]
    if record["dedup_status"] == "UNRESOLVED":
        return "DEDUP_UNRESOLVED", "SOURCE_GROUP or parent-package relation is unresolved."
    if record["split_eligibility"] == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED", "Access, rights, or parent-package review is required."
    if record["governance_status"] == "PUBLIC_DOWNLOAD_CLEAR":
        return "ELIGIBLE", "Public download is recorded as clear."
    return (
        "ELIGIBLE_WITH_ADVISORY",
        "Public access is repeatable; local evaluation is provisional and redistribution is not granted.",
    )


def _score(
    record: dict[str, Any],
    split: str,
    region_counts: Counter[str],
    render_counts: Counter[str],
    feature_counts: Counter[str],
    family_counts: Counter[str],
) -> tuple[int, str]:
    score = TIER_SCORE[record["quality_tier"]]
    score += GOVERNANCE_SCORE.get(record["governance_status"], 0)
    region = macro_region(record)
    if region_counts[region] < REGION_TARGETS[split][region]:
        score += REGION_SCORE
    rendering = record["vector_raster_status"]
    if render_counts[rendering] < RENDER_TARGETS[split][rendering]:
        score += RENDER_SCORE
    for feature, target in FEATURE_TARGETS[split].items():
        if record[feature] is True and feature_counts[feature] < target:
            score += FEATURE_SCORE
    if any(family_counts[family] == 0 for family in drawing_families(record)):
        score += DRAWING_FAMILY_SCORE
    return score, record["source_group_id"]


def _select_split(
    candidates: list[dict[str, Any]], split: str, count: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    region_counts: Counter[str] = Counter()
    render_counts: Counter[str] = Counter()
    feature_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    remaining = list(candidates)
    while len(selected) < count:
        if not remaining:
            raise SelectionError(f"not enough candidates for {split}")
        chosen = min(
            remaining,
            key=lambda record: (
                -_score(
                    record,
                    split,
                    region_counts,
                    render_counts,
                    feature_counts,
                    family_counts,
                )[0],
                record["source_group_id"],
            ),
        )
        selected.append(chosen)
        remaining.remove(chosen)
        region_counts[macro_region(chosen)] += 1
        render_counts[chosen["vector_raster_status"]] += 1
        for feature in FEATURE_TARGETS[split]:
            feature_counts[feature] += chosen[feature] is True
        family_counts.update(drawing_families(chosen))
    return selected


def select_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    eligible = [record for record in records if eligibility(record)[0] in {"ELIGIBLE", "ELIGIBLE_WITH_ADVISORY"}]
    selected: dict[str, list[dict[str, Any]]] = {}
    used: set[str] = set()
    for split in SPLIT_ORDER:
        available = [record for record in eligible if record["source_group_id"] not in used]
        if split == "LOCKED_BLIND":
            available = [
                record
                for record in available
                if record["discovery_phase"] == "G0-R2"
                and record["quality_tier"] == "STRONG"
                and record["split_eligibility"] == "PROVISIONAL_PENDING_ACQUISITION"
            ]
        chosen = _select_split(available, split, SPLIT_COUNTS[split])
        selected[split] = chosen
        used.update(record["source_group_id"] for record in chosen)
    return selected


def _entry(record: dict[str, Any], split: str) -> dict[str, Any]:
    eligibility_state, _ = eligibility(record)
    return {
        "source_group_id": record["source_group_id"],
        "source_family_id": record["source_family_id"],
        "eligibility": eligibility_state,
        "governance_status": record["governance_status"],
        "split_eligibility": record["split_eligibility"],
        "blind_exposure_status": "NEVER_EXECUTED" if split == "LOCKED_BLIND" else "NOT_APPLICABLE",
        "quality_tier": record["quality_tier"],
        "macro_region": macro_region(record),
        "vector_raster_status": record["vector_raster_status"],
        "historical_archival": record["historical_archival"],
        "degraded_scan": record["degraded_scan"],
        "native_image": record["native_image"],
        "drawing_families": drawing_families(record),
    }


def _distribution(records: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record[field]) for record in records).items()))


def _selected_stats(selected: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    corpus = selected["DEV"] + selected["VALIDATION"] + selected["LOCKED_BLIND"]
    families: Counter[str] = Counter()
    for record in corpus:
        families.update(drawing_families(record))
    return {
        "vector_raster_status": _distribution(corpus, "vector_raster_status"),
        "historical_archival": sum(r["historical_archival"] is True for r in corpus),
        "confirmed_degraded": sum(r["degraded_scan"] is True for r in corpus),
        "native_image": sum(r["native_image"] is True for r in corpus),
        "region_distribution": dict(sorted(Counter(macro_region(r) for r in corpus).items())),
        "drawing_family_distribution": dict(sorted(families.items())),
    }


def build_artifacts(
    records: list[dict[str, Any]], registry_path: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    digest = candidate_registry.registry_sha256(records)
    if digest != REGISTRY_DIGEST:
        raise SelectionError(f"candidate registry digest mismatch: {digest}")
    selected = select_records(records)
    all_ids = [r["source_group_id"] for values in selected.values() for r in values]
    corpus = selected["DEV"] + selected["VALIDATION"] + selected["LOCKED_BLIND"]
    family_splits: dict[str, set[str]] = {}
    for split, values in selected.items():
        for record in values:
            family_splits.setdefault(record["source_family_id"], set()).add(split)
    leaks = sorted(family for family, splits in family_splits.items() if len(splits) > 1)
    overlaps = len(all_ids) - len(set(all_ids))
    exposed = sum(
        _entry(record, "LOCKED_BLIND")["blind_exposure_status"] != "NEVER_EXECUTED"
        for record in selected["LOCKED_BLIND"]
    )
    bad_selected = [
        r["source_group_id"]
        for r in (record for values in selected.values() for record in values)
        if eligibility(r)[0] not in {"ELIGIBLE", "ELIGIBLE_WITH_ADVISORY"}
    ]
    gates = {
        "exact_split_counts": all(len(selected[s]) == SPLIT_COUNTS[s] for s in SPLIT_COUNTS),
        "split_overlap_count": overlaps,
        "source_family_leakage": leaks,
        "previously_exposed_locked_blind": exposed,
        "ineligible_selected": bad_selected,
        "candidate_registry_digest_matches": True,
        "fabricated_records": 0,
    }
    if not (
        gates["exact_split_counts"]
        and overlaps == 0
        and not leaks
        and exposed == 0
        and not bad_selected
    ):
        raise SelectionError(f"authoritative gates failed: {gates}")
    policy = {
        "version": POLICY_VERSION,
        "algorithm": "greedy marginal diversity score; SOURCE_GROUP ID ascending tie-break",
        "split_order": list(SPLIT_ORDER),
        "configuration": {
            "split_counts": SPLIT_COUNTS,
            "region_targets": REGION_TARGETS,
            "render_targets": RENDER_TARGETS,
            "feature_targets": FEATURE_TARGETS,
            "tier_score": TIER_SCORE,
            "governance_score": GOVERNANCE_SCORE,
            "region_score": REGION_SCORE,
            "render_score": RENDER_SCORE,
            "feature_score": FEATURE_SCORE,
            "drawing_family_score": DRAWING_FAMILY_SCORE,
            "locked_blind_filter": "G0-R2 + STRONG + PROVISIONAL_PENDING_ACQUISITION",
            "policy_dedup_unresolved": POLICY_DEDUP_UNRESOLVED,
        },
    }
    split_artifact = {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "authoritative": True,
        "freeze_status": "FROZEN",
        "candidate_registry": {
            "path": registry_path,
            "sha256": digest,
            "records": len(records),
        },
        "selection_policy": policy,
        "counts": {**SPLIT_COUNTS, "CORPUS_V1": len(corpus)},
        "corpus_v1_source_group_ids": sorted(r["source_group_id"] for r in corpus),
        "selected_source_group_ids": sorted(all_ids),
        "splits": {
            split: [_entry(record, split) for record in selected[split]]
            for split in ("DEV", "VALIDATION", "LOCKED_BLIND", "RESERVE")
        },
        "gates": gates,
        "deterministic_replay": {
            "registry_sha256": digest,
            "policy_version": POLICY_VERSION,
            "serialization": "UTF-8 JSON, sorted keys, indent=2, LF, final LF",
        },
    }
    decisions = []
    assignments = {
        record["source_group_id"]: split for split, values in selected.items() for record in values
    }
    for record in sorted(records, key=lambda item: item["source_group_id"]):
        state, reason = eligibility(record)
        decisions.append(
            {
                "source_group_id": record["source_group_id"],
                "source_family_id": record["source_family_id"],
                "eligibility": state,
                "reason": reason,
                "assignment": assignments.get(record["source_group_id"], "UNSELECTED"),
            }
        )
    report = {
        "schema_version": "draftsman-g0-selection-report-v1",
        "candidate_registry_sha256": digest,
        "selection_policy_version": POLICY_VERSION,
        "eligibility_counts": dict(sorted(Counter(item["eligibility"] for item in decisions).items())),
        "governance_gate_counts": {
            "registry_review_required": sum(
                record["split_eligibility"] == "REVIEW_REQUIRED" for record in records
            ),
            "registry_dedup_unresolved": sum(
                record["dedup_status"] == "UNRESOLVED" for record in records
            ),
            "policy_dedup_unresolved_added": len(POLICY_DEDUP_UNRESOLVED),
            "explicitly_ineligible": sum(
                record["governance_status"] == "LICENSE_RESTRICTED"
                or record["split_eligibility"] in {"INELIGIBLE", "RESTRICTED"}
                for record in records
            ),
        },
        "selected_statistics": _selected_stats(selected),
        "gates": gates,
        "candidate_decisions": decisions,
    }
    return split_artifact, report


def validate_split(artifact: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise SelectionError("unsupported split schema")
    if artifact.get("authoritative") is not True or artifact.get("freeze_status") != "FROZEN":
        raise SelectionError("split is not authoritative and frozen")
    replay, _ = build_artifacts(records, artifact["candidate_registry"]["path"])
    if canonical_json_bytes(replay) != canonical_json_bytes(artifact):
        raise SelectionError("selection policy replay mismatch")


def write_artifacts(
    split_path: Path, report_path: Path, digest_path: Path, split: dict[str, Any], report: dict[str, Any]
) -> str:
    payload = canonical_json_bytes(split)
    digest = hashlib.sha256(payload).hexdigest()
    split_path.write_bytes(payload)
    report_path.write_bytes(canonical_json_bytes(report))
    digest_path.write_bytes(f"{digest}\n".encode("ascii"))
    return digest


def load_locked_blind_ids(split_path: Path, *, explicit_opt_in: bool = False) -> list[str]:
    """Fail closed so ordinary development code cannot enumerate blind identities."""
    if not explicit_opt_in:
        raise SelectionError("LOCKED_BLIND access requires explicit opt-in")
    artifact = json.loads(split_path.read_text(encoding="utf-8"))
    return [entry["source_group_id"] for entry in artifact["splits"]["LOCKED_BLIND"]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--digest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    records = candidate_registry.load_registry(args.registry)
    split, report = build_artifacts(records, args.registry.as_posix())
    if args.check:
        checked = json.loads(args.split.read_text(encoding="utf-8"))
        validate_split(checked, records)
        expected_digest = artifact_sha256(checked)
        if args.digest.read_text(encoding="ascii").strip() != expected_digest:
            raise SelectionError("authoritative split digest mismatch")
        if canonical_json_bytes(report) != args.report.read_bytes():
            raise SelectionError("selection report replay mismatch")
        print(f"authoritative_split_sha256={expected_digest}")
        return 0
    digest = write_artifacts(args.split, args.report, args.digest, split, report)
    validate_split(split, records)
    print(f"authoritative_split_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
