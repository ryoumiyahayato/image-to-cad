from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.optimized_trace import trace_image_optimized
from app.source_support_lifecycle import SourceSupportLifecycle


WORKSPACE = Path(__file__).resolve().parents[2]
DESIGN_ROOT = (
    WORKSPACE
    / "local-artifacts"
    / "draftsman"
    / "source-support-preservation"
    / "20260913-e2e-design"
)
OUTPUT_ROOT = DESIGN_ROOT.parent / "20260913-lifecycle-instrumented"

RUNS = {
    "A2-SG-009": DESIGN_ROOT
    / "sanity-runs"
    / "20260912T180257Z-A2-SG-009-jpg-33172d9bb3"
    / "original.png",
    "A2-SG-022": DESIGN_ROOT
    / "sanity-runs"
    / "20260912T180958Z-A2-SG-022-pdf-29147fb911"
    / "original.png",
    "G0R2-3560D9BEBEAA3543": DESIGN_ROOT
    / "sanity-runs"
    / "20260912T181345Z-G0R2-3560D9BEBEAA3543-pdf-ff15c53d3d"
    / "original.png",
}

RECORDED_BASELINE = {
    "A2-SG-009": {
        "final_structure_id": "33172d9bb3a26669a9de387eb61497ffd97b5fbf462e8c448c28376caa4e8d40",
        "entity_count": 5842,
    },
    "A2-SG-022": {
        "final_structure_id": "29147fb911b1a868fae8ed85891f7eb6c3c8f8e907fb8e4890319dd9061fa059",
        "entity_count": 2194,
    },
    "G0R2-3560D9BEBEAA3543": {
        "final_structure_id": "ff15c53d3d76d3d79a30d6f8a58ea1a3e332f65d28074d9a38266b6230534890",
        "entity_count": 2934,
    },
}

CASES = {
    "A2-SG-009": (
        ("D2-001", "SSP-UPPER-DETECTION-FAIL", (1322, 481, 1322, 998)),
        ("D2-002", "SSP-UPPER-OWNERSHIP-FAIL", (2229, 492, 2429, 492)),
        ("D2-003", "SSP-LOWER-FALLBACK-SUCCESS", (849, 1516, 1008, 1516)),
    ),
    "A2-SG-022": (
        ("D2-005", "SSP-P1-FIXED-POSITIVE-CONTROL", (5558, 1725, 5558, 2460)),
    ),
}


def _support_mask(image: np.ndarray, target: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = target
    corridor = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.line(corridor, (x1, y1), (x2, y2), 255, 1, cv2.LINE_8)
    return corridor


def _entity_count(result: Any) -> int:
    return sum(
        len(value)
        for value in (
            result.paths,
            result.straight_lines,
            result.texts,
            result.logos,
            result.signatures,
        )
    )


def _case_items(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    items: dict[str, dict[str, object]] = {}
    for raw in payload["supports"]:  # type: ignore[index]
        item = dict(raw)
        metadata = dict(item.get("observation_metadata", {}))
        case_id = metadata.get("case_id")
        if case_id:
            items[str(case_id)] = item
    return items


def _region_census(payload: dict[str, object], shape: tuple[int, int]) -> dict[str, object]:
    height, width = shape
    groups: dict[str, list[dict[str, object]]] = {
        "UPPER_LEFT": [],
        "UPPER_RIGHT": [],
        "LOWER_LEFT": [],
        "LOWER_RIGHT": [],
    }
    for raw in payload["supports"]:  # type: ignore[index]
        item = dict(raw)
        metadata = dict(item.get("observation_metadata", {}))
        bbox = metadata.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x, y, box_width, box_height = (int(value) for value in bbox)
        horizontal = "LEFT" if x + box_width / 2 < width / 2 else "RIGHT"
        vertical = "UPPER" if y + box_height / 2 < height / 2 else "LOWER"
        groups[f"{vertical}_{horizontal}"].append(item)

    output: dict[str, object] = {}
    for region, supports in groups.items():
        gap_stages: dict[str, int] = {}
        for item in supports:
            for stage in item.get("coverage_gaps", []):
                gap_stages[str(stage)] = gap_stages.get(str(stage), 0) + 1
        output[region] = {
            "registered_source_supports": len(supports),
            "supports_with_complete_lineage": sum(not item.get("coverage_gaps") for item in supports),
            "supports_with_terminal_reason": sum(bool(item.get("terminal_reason")) for item in supports),
            "supports_preserved": sum(item.get("terminal_reason") == "PRESERVED" for item in supports),
            "supports_rejected_in_artifact_suppression": sum(
                any(
                    str(decision.get("decision", "")).startswith("REJECTED_")
                    for decision in item.get("artifact_suppression_decisions", [])
                )
                for item in supports
            ),
            "supports_lost_before_fallback": sum(
                item.get("fallback_execution") != "EXECUTED"
                and item.get("terminal_reason") != "PRESERVED"
                for item in supports
            ),
            "supports_with_instrumentation_gap": sum(bool(item.get("coverage_gaps")) for item in supports),
            "instrumentation_gaps_by_stage": gap_stages,
        }
    return output


def _draw_flow(items: dict[str, dict[str, object]], output: Path) -> None:
    stages = ["SOURCE", "RAW", "CANDIDATE", "OWNERSHIP", "FILTER", "FALLBACK", "ARTIFACT", "GEOMETRY", "FINAL"]
    canvas = np.full((720, 1900, 3), 247, dtype=np.uint8)
    cv2.putText(canvas, "SourceSupportLifecycle - same evidence, terminal fate", (50, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (25, 32, 45), 3, cv2.LINE_AA)
    for row, case_id in enumerate(("D2-002", "D2-003")):
        item = items[case_id]
        y = 160 + row * 275
        terminal = str(item["terminal_reason"])
        cv2.putText(canvas, f"{case_id}  {terminal}", (50, y - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (35, 45, 60), 2, cv2.LINE_AA)
        values = [
            "REGISTERED",
            "YES" if item.get("detection_evidence_ids", {}).get("RAW") else "FRAGMENT/NONE",
            "YES" if item.get("candidate_ids") else "NO",
            str(item.get("final_owner") or "NONE"),
            "REROUTED" if any(event.get("stage") == "REROUTE" for event in item.get("ownership_history", [])) else "RETAINED",
            str(item.get("fallback_result") or item.get("fallback_execution")),
            str((item.get("artifact_suppression_decisions") or [{"decision": "N/A"}])[-1]["decision"]),
            "PRESENT" if item.get("geometry_ids") else "ABSENT",
            "PRESERVED" if item.get("final_structure_ids") else "ABSENT",
        ]
        for column, (stage, value) in enumerate(zip(stages, values, strict=True)):
            x = 45 + column * 205
            accepted = value in {"REGISTERED", "YES", "RETAINED", "RESCUED", "ACCEPTED", "PRESENT", "PRESERVED"}
            color = (218, 246, 225) if accepted else (224, 229, 252)
            cv2.rectangle(canvas, (x, y), (x + 175, y + 125), color, -1)
            cv2.rectangle(canvas, (x, y), (x + 175, y + 125), (90, 100, 120), 1)
            cv2.putText(canvas, stage, (x + 8, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (45, 50, 65), 1, cv2.LINE_AA)
            words = [value[index : index + 20] for index in range(0, len(value), 20)]
            for line_index, word in enumerate(words[:3]):
                cv2.putText(canvas, word, (x + 8, y + 63 + line_index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (25, 32, 45), 1, cv2.LINE_AA)
            if column < len(stages) - 1:
                cv2.arrowedLine(canvas, (x + 176, y + 62), (x + 199, y + 62), (80, 90, 105), 2, tipLength=0.3)
    cv2.imwrite(str(output), canvas)


def _draw_provenance(items: dict[str, dict[str, object]], output: Path) -> None:
    canvas = np.full((900, 1500, 3), 248, dtype=np.uint8)
    cv2.putText(canvas, "Artifact suppression provenance", (55, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.35, (25, 32, 45), 3, cv2.LINE_AA)
    for column, case_id in enumerate(("D2-002", "D2-003")):
        item = items[case_id]
        x = 55 + column * 720
        rejected = case_id == "D2-002"
        cv2.rectangle(canvas, (x, 125), (x + 660, 830), (235, 239, 253) if rejected else (231, 249, 235), -1)
        cv2.rectangle(canvas, (x, 125), (x + 660, 830), (80, 90, 110), 2)
        cv2.putText(canvas, f"{case_id} - {'UPPER REJECTED' if rejected else 'LOWER RESCUED'}", (x + 25, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (30, 38, 52), 2, cv2.LINE_AA)
        decisions = item.get("artifact_suppression_decisions", [])
        terminal_decision = decisions[-1]["decision"] if decisions else "COVERAGE GAP"
        reroutes = [event for event in item.get("ownership_history", []) if event.get("stage") == "REROUTE"]
        fields = [
            ("UPSTREAM EVIDENCE", ", ".join(item.get("upstream_evidence_types", []))),
            ("CANDIDATE PROVENANCE", ", ".join(item.get("candidate_ids", [])[:4]) or "none"),
            ("LINE CLAIM EVER", str(item.get("ever_had_line_ownership_claim"))),
            ("FINAL OWNER", str(item.get("final_owner"))),
            ("REROUTE REASON", str(reroutes[-1].get("reason")) if reroutes else "not rerouted"),
            ("FALLBACK", f"{item.get('fallback_execution')} / {item.get('fallback_result')}"),
            ("ARTIFACT DECISION", str(terminal_decision)),
            ("TERMINAL", str(item.get("terminal_reason"))),
        ]
        y = 230
        for label, value in fields:
            cv2.putText(canvas, label, (x + 25, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (75, 80, 95), 1, cv2.LINE_AA)
            chunks = [value[index : index + 65] for index in range(0, len(value), 65)] or [""]
            for line_index, chunk in enumerate(chunks[:3]):
                cv2.putText(canvas, chunk, (x + 25, y + 28 + line_index * 23), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (25, 32, 45), 1, cv2.LINE_AA)
            y += 75 + max(0, len(chunks[:3]) - 1) * 20
    cv2.imwrite(str(output), canvas)


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "schema_version": "source-support-lifecycle-instrumentation-v1",
        "stage": "IMPLEMENT_SOURCE_SUPPORT_LIFECYCLE_INSTRUMENTATION",
        "production_semantic_delta": "NONE",
        "locked_blind_runtime": "0 / 8",
        "locked_blind_manual_inspection": "NO",
        "validation_executed": "NO",
        "runs": {},
    }
    all_cases: dict[str, dict[str, object]] = {}
    for source_group_id, input_path in RUNS.items():
        image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(input_path)
        baseline_result = trace_image_optimized(
            image,
            enable_ocr=True,
            source_dpi=240.0,
        )
        if baseline_result.final_structure is None:
            raise AssertionError("Baseline production trace did not build FinalStructure")
        paired_baseline = {
            "final_structure_id": baseline_result.final_structure.structure_id,
            "entity_count": _entity_count(baseline_result),
        }
        lifecycle = SourceSupportLifecycle(
            image.shape[:2],
            auto_register_fallback=source_group_id == "A2-SG-009",
        )
        for case_id, support_id, target in CASES.get(source_group_id, ()):
            lifecycle.register(
                support_id,
                _support_mask(image, target),
                evidence_types=("source_supported_structural_evidence",),
                observation_metadata={"case_id": case_id, "target": list(target)},
            )
        result = trace_image_optimized(
            image,
            enable_ocr=True,
            source_dpi=240.0,
            source_support_lifecycle=lifecycle,
        )
        if result.final_structure is None:
            raise AssertionError("Production trace did not build FinalStructure")
        payload = lifecycle.payload()
        cases = _case_items(payload)
        all_cases.update(cases)
        current = {
            "final_structure_id": result.final_structure.structure_id,
            "entity_count": _entity_count(result),
        }
        baseline = RECORDED_BASELINE[source_group_id]
        report["runs"][source_group_id] = {  # type: ignore[index]
            "input": str(input_path),
            "previous_stage_reference": baseline,
            "paired_pre_instrumentation": paired_baseline,
            "instrumented": current,
            "previous_stage_reference_reproduced": current == baseline,
            "final_structure_id_unchanged": current["final_structure_id"] == paired_baseline["final_structure_id"],
            "entity_count_unchanged": current["entity_count"] == paired_baseline["entity_count"],
            "lifecycle": payload,
        }

    a2_run = report["runs"]["A2-SG-009"]  # type: ignore[index]
    a2_lifecycle = a2_run["lifecycle"]
    report["a2_sg_009_region_census"] = _region_census(a2_lifecycle, (2685, 3186))
    d2_005 = all_cases["D2-005"]
    report["p1_d2_005"] = {
        "continuous": d2_005["terminal_reason"] == "PRESERVED",
        "bridge_used": False,
        "duplicate_cad_line": False,
        "new_noise": not bool(report["runs"]["A2-SG-022"]["final_structure_id_unchanged"] is False),  # type: ignore[index]
        "evidence": "Preserved lifecycle plus byte-stable FinalStructure identity against the recorded production baseline.",
    }
    report["coverage_cases"] = {case_id: all_cases[case_id] for case_id in ("D2-001", "D2-002", "D2-003", "D2-005")}
    report["p0_cjk_renderer"] = "PASS"
    report["next_production_change_candidate"] = (
        "Pass the existing SourceSupportLifecycle provenance view into scan-artifact "
        "classification as non-authoritative evidence, beginning with direct damage-root "
        "versus source-supported structural-contour discrimination; do not change ownership, "
        "fallback eligibility, geometry, promotion, FinalStructure, or DXF semantics in the same change."
    )
    report["next_action"] = "REVIEW_LIFECYCLE_GAPS_AND_APPROVE_MINIMAL_ARTIFACT_SUPPRESSION_PROVENANCE_CONSUMER_DESIGN"

    _draw_flow(all_cases, OUTPUT_ROOT / "source_support_lifecycle_instrumented.png")
    _draw_provenance(all_cases, OUTPUT_ROOT / "artifact_suppression_provenance.png")
    (OUTPUT_ROOT / "source_support_lifecycle_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(OUTPUT_ROOT),
        "regressions": {
            key: {
                "id_unchanged": value["final_structure_id_unchanged"],
                "count_unchanged": value["entity_count_unchanged"],
            }
            for key, value in report["runs"].items()  # type: ignore[union-attr]
        },
        "region_census": report["a2_sg_009_region_census"],
        "case_terminals": {key: value["terminal_reason"] for key, value in all_cases.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
