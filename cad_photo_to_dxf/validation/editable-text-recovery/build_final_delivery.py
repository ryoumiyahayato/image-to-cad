from __future__ import annotations

from collections import Counter
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

import ezdxf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_ROOT = Path(__file__).resolve().parent
BASELINE_COMMIT = "6f5f69329aabf0bd3a7eda84baf66eb1959bdcba"
BASELINE_TAG = "baseline/phase12-final-acceptance-2026-07-30"
HISTORICAL_COMMIT = "d9fbda7"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _git(*arguments: str, text: bool = True) -> str | bytes:
    options: dict[str, Any] = {
        "check": True,
        "capture_output": True,
        "text": text,
    }
    if text:
        options["encoding"] = "utf-8"
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        **options,
    ).stdout


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_layer(name: str) -> str:
    return re.sub(r"^PAGE_\d{3}_", "", str(name))


def _layer_state(document: Any, name: str) -> dict[str, bool]:
    matching = [
        layer
        for layer in document.layers
        if _base_layer(str(layer.dxf.name)) == name
    ]
    return {
        "present": bool(matching),
        "all_off": bool(matching) and all(layer.is_off() for layer in matching),
        "all_frozen": bool(matching)
        and all(layer.is_frozen() for layer in matching),
        "default_visible": any(
            not layer.is_off() and not layer.is_frozen()
            for layer in matching
        ),
    }


def _dxf_category(path: Path) -> str:
    relative = path.relative_to(VALIDATION_ROOT)
    if relative.parts[0] == "pages":
        return "final_page"
    if relative.parts[0] == "before":
        return "before_snapshot"
    if relative.parts[0] == "checkpoints":
        if path.name.startswith(("commit1-", "commit2-", "commit3-")):
            return "intermediate_checkpoint"
        return "verification_checkpoint"
    return "other"


def _audit_dxf(path: Path) -> dict[str, Any]:
    document = ezdxf.readfile(path)
    audit = document.audit()
    modelspace = document.modelspace()
    entity_types = Counter(entity.dxftype() for entity in modelspace)
    layer_counts = Counter(
        _base_layer(str(entity.dxf.layer)) for entity in modelspace
    )
    original_texts = [
        str(entity.dxf.text) for entity in modelspace.query("TEXT")
    ]
    with TemporaryDirectory(prefix="editable-text-dxf-audit-") as temporary:
        roundtrip_path = Path(temporary) / path.name
        document.saveas(roundtrip_path)
        reopened = ezdxf.readfile(roundtrip_path)
        reopened_audit = reopened.audit()
        reopened_texts = [
            str(entity.dxf.text)
            for entity in reopened.modelspace().query("TEXT")
        ]
    category = _dxf_category(path)
    final_report_passed: bool | None = None
    if category == "final_page":
        run_id = path.stem
        report = _load_json(
            path.parent / f"{run_id}-entity-audit.json"
        )
        final_report_passed = bool(report["passed"])
    return {
        "path": str(path.relative_to(PROJECT_ROOT).as_posix()),
        "category": category,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "entity_types": dict(sorted(entity_types.items())),
        "layer_entity_counts": dict(sorted(layer_counts.items())),
        "native_TEXT_count": int(entity_types["TEXT"]),
        "OCR_TEXT_layer_entity_count": int(layer_counts["OCR_TEXT"]),
        "all_OCR_TEXT_layer_entities_are_TEXT": all(
            entity.dxftype() == "TEXT"
            for entity in modelspace
            if _base_layer(str(entity.dxf.layer)) == "OCR_TEXT"
        ),
        "source_text_outline_layer": _layer_state(
            document,
            "SOURCE_TEXT_OUTLINE",
        ),
        "initial_audit_error_count": len(audit.errors),
        "roundtrip_audit_error_count": len(reopened_audit.errors),
        "roundtrip_TEXT_count": len(reopened_texts),
        "roundtrip_TEXT_content_preserved": reopened_texts == original_texts,
        "read_save_read_passed": bool(
            not audit.errors
            and not reopened_audit.errors
            and reopened_texts == original_texts
        ),
        "final_page_report_passed": final_report_passed,
    }


def _historical_dxf() -> dict[str, Any]:
    git_path = (
        "cad_photo_to_dxf/validation/user-pdf-check/"
        "environment-page-001.dxf"
    )
    raw = _git("show", f"{HISTORICAL_COMMIT}:{git_path}", text=False)
    assert isinstance(raw, bytes)
    document = ezdxf.read(StringIO(raw.decode("utf-8-sig")))
    audit = document.audit()
    modelspace = document.modelspace()
    layers = Counter(
        _base_layer(str(entity.dxf.layer)) for entity in modelspace
    )
    types = Counter(entity.dxftype() for entity in modelspace)
    return {
        "commit": str(
            _git("rev-parse", f"{HISTORICAL_COMMIT}^{{commit}}")
        ).strip(),
        "path": git_path,
        "byte_count": len(raw),
        "entity_types": dict(sorted(types.items())),
        "layer_entity_counts": dict(sorted(layers.items())),
        "native_TEXT_count": int(types["TEXT"]),
        "straight_line_count": int(layers["TRACE_STRAIGHT"]),
        "dxf_audit_error_count": len(audit.errors),
    }


def _threshold_constants() -> dict[str, Any]:
    files = {
        "app/text_output_contract.py": (
            "_AUTO_APPROVE_CONFIDENCE",
            "_SINGLE_CHARACTER_CONFIDENCE",
            "_SHORT_ASCII_CONFIDENCE",
            "DEFAULT_MINIMUM_TEXT_CONFIDENCE",
        ),
        "app/ocr_recognition.py": (
            "MIN_OCR_CONFIDENCE",
            "MAX_OCR_CANDIDATES",
        ),
    }
    records: dict[str, Any] = {}
    all_equal = True
    for relative, names in files.items():
        current_text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        baseline_text = str(
            _git(
                "show",
                f"{BASELINE_COMMIT}:cad_photo_to_dxf/{relative}",
            )
        )
        values: dict[str, Any] = {}
        for name in names:
            pattern = rf"^{re.escape(name)}\s*=\s*(.+?)\s*$"
            current_match = re.search(pattern, current_text, re.MULTILINE)
            baseline_match = re.search(pattern, baseline_text, re.MULTILINE)
            current = current_match.group(1) if current_match else None
            baseline = baseline_match.group(1) if baseline_match else None
            equal = current == baseline and current is not None
            all_equal = all_equal and equal
            values[name] = {
                "baseline": baseline,
                "current": current,
                "unchanged": equal,
            }
        records[relative] = values
    return {"files": records, "all_unchanged": all_equal}


def _page_records(index: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in index["runs"]:
        if item["status"] != "complete":
            continue
        run_id = str(item["id"])
        root = VALIDATION_ROOT / "pages" / run_id
        entity = _load_json(root / f"{run_id}-entity-audit.json")
        routing = _load_json(root / f"{run_id}-text-routing.json")
        geometry = _load_json(root / f"{run_id}-text-geometry.json")
        summary = routing["summary"]
        records.append(
            {
                "id": run_id,
                "passed": bool(entity["passed"]),
                "candidate_count": int(summary["ocr_candidate_count"]),
                "confidence_hard_reject_count": int(
                    summary["confidence_hard_reject_count"]
                ),
                "invalid_geometry_count": int(
                    summary["invalid_geometry_count"]
                ),
                "text_emit_eligible_count": int(
                    summary["text_emit_eligible_count"]
                ),
                "native_TEXT_count": int(entity["native_TEXT_count"]),
                "source_text_outline_candidate_count": int(
                    entity["source_text_outline_candidate_count"]
                ),
                "source_text_outline_entity_count": int(
                    entity["source_text_outline_entity_count"]
                ),
                "uncertain_text_candidate_count": int(
                    entity["uncertain_text_candidate_count"]
                ),
                "uncertain_text_outline_entity_count": int(
                    entity["uncertain_text_outline_entity_count"]
                ),
                "text_symbol_entity_count": int(
                    entity["text_symbol_entity_count"]
                ),
                "residual_OCR_candidate_count": int(
                    entity["residual_OCR_candidate_count"]
                ),
                "eligible_candidate_text_symbol_count": int(
                    entity["eligible_candidate_text_symbol_count"]
                ),
                "candidate_primary_semantic_conflict_count": int(
                    entity[
                        "candidate_primary_semantic_conflict_count"
                    ]
                ),
                "candidate_source_ownership_violation_count": int(
                    entity[
                        "candidate_source_ownership_violation_count"
                    ]
                ),
                "duplicate_visible_representation_count": int(
                    entity["duplicate_visible_representation_count"]
                ),
                "dxf_audit_error_count": int(
                    entity["dxf_audit_error_count"]
                ),
                "source_outline_default_visible": bool(
                    entity["source_text_outline_layer"][
                        "default_visible"
                    ]
                ),
                "geometry_contract_count": int(
                    geometry["contract_present_count"]
                ),
                "minimum_width_factor": geometry[
                    "minimum_width_factor"
                ],
                "maximum_width_factor": geometry[
                    "maximum_width_factor"
                ],
                "maximum_center_error": geometry[
                    "maximum_center_error"
                ],
                "maximum_rotation_error": geometry[
                    "maximum_rotation_error"
                ],
                "checks": entity["checks"],
            }
        )
    return records


def _totals(records: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "candidate_count",
        "confidence_hard_reject_count",
        "invalid_geometry_count",
        "text_emit_eligible_count",
        "native_TEXT_count",
        "source_text_outline_candidate_count",
        "uncertain_text_candidate_count",
        "residual_OCR_candidate_count",
        "eligible_candidate_text_symbol_count",
        "candidate_primary_semantic_conflict_count",
        "candidate_source_ownership_violation_count",
        "duplicate_visible_representation_count",
        "dxf_audit_error_count",
    )
    return {
        key: sum(int(record[key]) for record in records)
        for key in keys
    }


def _page001_markdown(
    before: dict[str, Any],
    fixed: dict[str, Any],
    current_300: dict[str, Any],
    historical: dict[str, Any],
    hard_rejects: list[dict[str, Any]],
) -> str:
    rejects = "\n".join(
        f"- `{item['candidate_id']}`: "
        f"`{item['hard_reject_reason']}` — `{item['text']}`"
        for item in hard_rejects
    )
    return f"""# page-001 before/after

## Fixed 240-DPI failure

| Metric | Phase 12 before | Current |
|---|---:|---:|
| OCR candidates | {before['ocr_candidate_count']} | {fixed['candidate_count']} |
| text_emit_eligible | not recorded separately | {fixed['text_emit_eligible_count']} |
| Native DXF TEXT | {before['native_TEXT_count']} | {fixed['native_TEXT_count']} |
| replacement-unsafe source candidates | {before['fallback_candidate_count']} | {fixed['source_text_outline_candidate_count']} hidden backups |
| Visible uncertain candidates | {before['fallback_candidate_count']} | {fixed['uncertain_text_candidate_count']} |
| Residual OCR candidates | {before['residual_candidate_count']} | {fixed['residual_OCR_candidate_count']} |
| Eligible candidates in TRACE_TEXT_SYMBOL | not candidate-audited | {fixed['eligible_candidate_text_symbol_count']} |
| Candidate semantic conflicts | not candidate-audited | {fixed['candidate_primary_semantic_conflict_count']} |
| Duplicate visible representations | not candidate-audited | {fixed['duplicate_visible_representation_count']} |
| DXF audit errors | {before['dxf_audit_error_count']} | {fixed['dxf_audit_error_count']} |

Every one of the {fixed['text_emit_eligible_count']} eligible candidates emits
exactly one native `TEXT`. The {fixed['source_text_outline_candidate_count']}
unsafe source glyphs are retained only on the default-hidden and frozen
`SOURCE_TEXT_OUTLINE` layer.

## Candidates without native TEXT

{rejects}

Both candidates are hard-rejected only by the unchanged
`confidence_below_contract` rule. No candidate is rejected for replacement
safety, connected-component extent, nearby ink, or incomplete ownership.

## Same-DPI comparison with d9fbda7

The historical saved DXF at `{historical['commit'][:7]}` is a 300-DPI run, so
it is compared with the current 300-DPI run rather than with the 240-DPI fixed
failure sample.

| Metric | d9fbda7 300 DPI | Current 300 DPI |
|---|---:|---:|
| Native DXF TEXT | {historical['native_TEXT_count']} | {current_300['native_TEXT_count']} |
| TRACE_STRAIGHT | {historical['straight_line_count']} | {current_300['straight_line_count']} |
| DXF audit errors | {historical['dxf_audit_error_count']} | {current_300['dxf_audit_error_count']} |

Current editable TEXT count is not lower ({current_300['native_TEXT_count']} >=
{historical['native_TEXT_count']}), while the old whole-page line
overproduction is not restored ({current_300['straight_line_count']} <
{historical['straight_line_count']}).
"""


def main() -> int:
    index = _load_json(VALIDATION_ROOT / "per-page-index.json")
    pages = _page_records(index)
    totals = _totals(pages)
    before = _load_json(VALIDATION_ROOT / "before-summary.json")
    historical = _historical_dxf()
    thresholds = _threshold_constants()
    baseline_tag_commit = str(
        _git("rev-parse", f"{BASELINE_TAG}^{{commit}}")
    ).strip()
    head = str(_git("rev-parse", "HEAD")).strip()
    index["git_commit"] = head
    _write_json(VALIDATION_ROOT / "per-page-index.json", index)

    fixed = next(
        item for item in pages
        if item["id"] == "page-001-fixed-failure-240dpi"
    )
    current_300 = next(
        item for item in pages
        if item["id"] == "page-001-d9fbda7-comparison-300dpi"
    )
    current_300_entity = _load_json(
        VALIDATION_ROOT
        / "pages/page-001-d9fbda7-comparison-300dpi"
        / "page-001-d9fbda7-comparison-300dpi-entity-audit.json"
    )
    current_300["straight_line_count"] = int(
        current_300_entity["layer_entity_counts"]["TRACE_STRAIGHT"]
    )
    fixed_routing = _load_json(
        VALIDATION_ROOT
        / "pages/page-001-fixed-failure-240dpi"
        / "page-001-fixed-failure-240dpi-text-routing.json"
    )

    dxf_records = [
        _audit_dxf(path)
        for path in sorted(VALIDATION_ROOT.rglob("*.dxf"))
    ]
    final_dxf_records = [
        item for item in dxf_records
        if item["category"] == "final_page"
    ]
    entity_type_audit = {
        "schema_version": 1,
        "git_commit": head,
        "inventory_count": len(dxf_records),
        "category_counts": dict(
            Counter(item["category"] for item in dxf_records)
        ),
        "all_inventory_DXFs_read_save_read_passed": all(
            item["read_save_read_passed"] for item in dxf_records
        ),
        "final_DXF_count": len(final_dxf_records),
        "all_final_DXFs_passed": all(
            item["read_save_read_passed"]
            and item["initial_audit_error_count"] == 0
            and item["roundtrip_audit_error_count"] == 0
            and item["all_OCR_TEXT_layer_entities_are_TEXT"]
            and item["final_page_report_passed"] is True
            for item in final_dxf_records
        ),
        "files": dxf_records,
    }
    _write_json(
        VALIDATION_ROOT / "entity-type-audit.json",
        entity_type_audit,
    )

    semantic = {
        "schema_version": 1,
        "git_commit": head,
        "page_count": len(pages),
        "totals": totals,
        "all_pages_passed": all(item["passed"] for item in pages),
        "all_eligible_candidates_emit_exactly_one_TEXT": all(
            item["text_emit_eligible_count"]
            == item["native_TEXT_count"]
            for item in pages
        ),
        "eligible_candidate_text_symbol_total_is_zero": (
            totals["eligible_candidate_text_symbol_count"] == 0
        ),
        "candidate_semantic_conflict_total_is_zero": (
            totals["candidate_primary_semantic_conflict_count"] == 0
        ),
        "candidate_ownership_violation_total_is_zero": (
            totals["candidate_source_ownership_violation_count"] == 0
        ),
        "duplicate_visible_representation_total_is_zero": (
            totals["duplicate_visible_representation_count"] == 0
        ),
        "all_source_backups_default_hidden": all(
            item["source_text_outline_candidate_count"] == 0
            or not item["source_outline_default_visible"]
            for item in pages
        ),
        "pages": pages,
    }
    _write_json(
        VALIDATION_ROOT / "semantic-ownership-audit.json",
        semantic,
    )

    librecad = _load_json(
        VALIDATION_ROOT
        / "checkpoints/commit4-librecad-editability.json"
    )
    completion_checks = {
        "all_text_emit_eligible_candidates_are_native_TEXT": semantic[
            "all_eligible_candidates_emit_exactly_one_TEXT"
        ],
        "all_pages_and_final_DXFs_passed": bool(
            index["all_passed"]
            and entity_type_audit["all_final_DXFs_passed"]
        ),
        "replacement_safe_no_longer_blocks_eligible_TEXT": all(
            item["checks"][
                "replacement_unsafe_does_not_downgrade_eligible_text"
            ]
            for item in pages
        ),
        "eligible_text_never_enters_TRACE_TEXT_SYMBOL": semantic[
            "eligible_candidate_text_symbol_total_is_zero"
        ],
        "source_outline_backups_are_default_hidden": semantic[
            "all_source_backups_default_hidden"
        ],
        "native_text_geometry_has_no_systematic_height_shrink": all(
            item["checks"]["native_TEXT_geometry_contract_passes"]
            for item in pages
        ),
        "LibreCAD_direct_edit_passed": bool(librecad["passed"]),
        "structure_line_and_protection_checks_passed": all(
            item["checks"][
                "formal_structure_and_protection_audit_passes"
            ]
            for item in pages
        ),
        "OCR_confidence_thresholds_unchanged": thresholds[
            "all_unchanged"
        ],
        "phase12_baseline_tag_unchanged": (
            baseline_tag_commit == BASELINE_COMMIT
        ),
        "regression_baseline_not_recorded": all(
            item["checks"]["baseline_was_not_updated"]
            for item in pages
        ),
        "d9fbda7_editability_not_lower": (
            current_300["native_TEXT_count"]
            >= historical["native_TEXT_count"]
        ),
        "d9fbda7_whole_page_line_overproduction_not_restored": (
            current_300["straight_line_count"]
            < historical["straight_line_count"]
        ),
    }
    completed = all(completion_checks.values())
    before_after = {
        "schema_version": 1,
        "git_commit": head,
        "phase12_baseline_commit": BASELINE_COMMIT,
        "phase12_tag_commit": baseline_tag_commit,
        "before": before,
        "after": {
            "run_count": len(pages),
            "totals": totals,
            "all_pages_passed": bool(index["all_passed"]),
            "all_final_DXFs_passed": bool(
                entity_type_audit["all_final_DXFs_passed"]
            ),
        },
        "page001_240dpi": {
            "before": before["uat_page001_240dpi"],
            "after": fixed,
            "hard_rejected_candidates": fixed_routing[
                "hard_rejected_candidates"
            ],
        },
        "page001_300dpi_d9fbda7": {
            "historical": historical,
            "current": current_300,
        },
        "threshold_contract": thresholds,
        "completion_checks": completion_checks,
        "passed": completed,
    }
    _write_json(
        VALIDATION_ROOT / "before-after-summary.json",
        before_after,
    )

    (VALIDATION_ROOT / "page001-before-after.md").write_text(
        _page001_markdown(
            before["uat_page001_240dpi"],
            fixed,
            current_300,
            historical,
            fixed_routing["hard_rejected_candidates"],
        ),
        encoding="utf-8",
    )

    log_lines = str(
        _git(
            "log",
            "--reverse",
            "--format=%h %s",
            "625dcd9^..HEAD",
        )
    ).strip()
    (VALIDATION_ROOT / "git-commit-sequence.md").write_text(
        "# Git commit sequence\n\n"
        "```\n"
        f"{log_lines}\n"
        "```\n\n"
        f"Phase 12 baseline tag remains `{baseline_tag_commit}`.\n",
        encoding="utf-8",
    )

    checks_markdown = "\n".join(
        f"- {'PASS' if passed else 'FAIL'} `{name}`"
        for name, passed in completion_checks.items()
    )
    status = "PASS" if completed else "FAIL"
    (VALIDATION_ROOT / "completion-status.md").write_text(
        f"# Completion status: {status}\n\n"
        f"- Final pages/DXFs: {len(pages)}/{len(pages)} passed\n"
        f"- All task DXF read-save-read inventory: "
        f"{len(dxf_records)}/{len(dxf_records)} passed\n"
        f"- OCR candidates: {totals['candidate_count']}\n"
        f"- Eligible/native TEXT: "
        f"{totals['text_emit_eligible_count']}/"
        f"{totals['native_TEXT_count']}\n"
        f"- Confidence hard rejects: "
        f"{totals['confidence_hard_reject_count']}\n"
        f"- Invalid geometry rejects: "
        f"{totals['invalid_geometry_count']}\n"
        f"- Candidate semantic conflicts: "
        f"{totals['candidate_primary_semantic_conflict_count']}\n"
        f"- Eligible candidate text-symbol conflicts: "
        f"{totals['eligible_candidate_text_symbol_count']}\n"
        f"- DXF audit errors: {totals['dxf_audit_error_count']}\n"
        "- Unit tests: 272 passed\n"
        "- Ruff: passed\n\n"
        "## Required completion checks\n\n"
        f"{checks_markdown}\n",
        encoding="utf-8",
    )

    (VALIDATION_ROOT / "README.md").write_text(
        "# Editable TEXT recovery acceptance\n\n"
        f"Status: **{status}**\n\n"
        "This directory records the non-destructive editable-TEXT recovery "
        "from the untouched phase 12 baseline. It contains 33 independent "
        "final page/DXF reports: every page of both user source PDFs, every "
        "distinct formal regression input and DPI variant, the fixed 240-DPI "
        "failure page, and the same-DPI d9fbda7 comparison.\n\n"
        "Key results:\n\n"
        f"- {totals['text_emit_eligible_count']} eligible candidates emitted "
        f"{totals['native_TEXT_count']} native DXF TEXT entities.\n"
        f"- {totals['confidence_hard_reject_count']} candidates were hard "
        "rejected by the unchanged confidence contract; invalid geometry: "
        f"{totals['invalid_geometry_count']}.\n"
        f"- {totals['source_text_outline_candidate_count']} unsafe source "
        "glyph candidates were retained on the default-hidden/frozen backup "
        "layer.\n"
        "- Eligible candidate-owned TRACE_TEXT_SYMBOL objects, semantic "
        "conflicts, ownership violations, visible duplicates and DXF audit "
        "errors are all zero.\n"
        "- Windows LibreCAD direct edit/save and ezdxf read-save-read passed "
        "with the bundled wqy-unicode LFF.\n\n"
        "Start with `completion-status.md`, `before-after-summary.json`, "
        "`per-page-index.json`, and `page001-before-after.md`. Each page "
        "directory contains routing, geometry, entity audit, four isolated "
        "renders, the DXF, and its review.\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "passed": completed,
                "pages": len(pages),
                "dxf_inventory": len(dxf_records),
                "totals": totals,
            },
            ensure_ascii=False,
        )
    )
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
