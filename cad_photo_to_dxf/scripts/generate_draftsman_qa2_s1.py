from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import FamilyAuditReference  # noqa: E402
from app.draftsman_qa1 import audit_draftsman_qa1  # noqa: E402
from app.draftsman_qa2_s1 import (  # noqa: E402
    QA2SourceCoverageResult,
    measure_independent_source_coverage,
    write_draftsman_qa2_s1_artifacts,
)
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1  # noqa: E402
from app.draftsman_vs3_u1 import (  # noqa: E402
    U1GeometryDisposition,
    audit_draftsman_vs3_u1_family,
    preserve_draftsman_vs3_u1,
)


KNOWN_REAL_OMISSION_ID = "ELEC-150-S01-165"


def _overlap(first: tuple[int, ...], second: tuple[int, ...]) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _post_hoc_evaluation(
    result: QA2SourceCoverageResult,
    *,
    source: Path,
    reference: FamilyAuditReference,
) -> tuple[dict[str, object], dict[str, object]]:
    family = audit_draftsman_vs3_u1_family(source, reference=reference)
    insufficient_ids = {
        str(item["reference_instance_id"])
        for item in family.instances
        if item["u1_disposition"]
        == U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE.value
    }
    reference_by_id = {
        item.reference_instance_id: item for item in reference.instances
    }
    evaluated = []
    hit_region_ids: set[str] = set()
    for reference_id in sorted(insufficient_ids):
        expected = reference_by_id[reference_id]
        hits = tuple(
            sorted(
                item.region_id
                for item in result.residual_regions
                if _overlap(item.source_region, expected.source_bbox_px)
            )
        )
        hit_region_ids.update(hits)
        evaluated.append(
            {
                "reference_instance_id": reference_id,
                "evaluation_role": (
                    "KNOWN_REAL_SILENT_OMISSION"
                    if reference_id == KNOWN_REAL_OMISSION_ID
                    else "OTHER_INSUFFICIENT_INSTANCE"
                ),
                "residual_region_hits": list(hits),
                "hit": bool(hits),
            }
        )
    known_hit = sum(
        bool(item["hit"])
        for item in evaluated
        if item["evaluation_role"] == "KNOWN_REAL_SILENT_OMISSION"
    )
    other_hit = sum(
        bool(item["hit"])
        for item in evaluated
        if item["evaluation_role"] == "OTHER_INSUFFICIENT_INSTANCE"
    )
    false_alerts = len(result.residual_regions) - len(hit_region_ids)
    precision = (
        0.0
        if not result.residual_regions
        else round(100.0 * known_hit / len(result.residual_regions), 4)
    )
    evaluation: dict[str, object] = {
        "schema_version": "draftsman-qa2-s1-reference-evaluation-v1",
        "usage": "POST_HOC_ONLY_AFTER_FROZEN_REFERENCE_FREE_RUNTIME",
        "runtime_result_id": result.result_id,
        "known_real_silent_omissions_evaluated": 1,
        "known_omission_hits": known_hit,
        "other_insufficient_instances_evaluated": 1,
        "other_insufficient_hits": other_hit,
        "instances": evaluated,
        "reference_loaded_at_runtime": False,
    }
    comparison: dict[str, object] = {
        "schema_version": "draftsman-qa2-s1-baseline-comparison-v1",
        "qa0": {
            "signals": 37,
            "true_omission_hits": 1,
            "false_alerts": 36,
            "precision_percent": 2.7027,
            "known_omission_recall_percent": 100.0,
            "alerts_per_page": 37,
        },
        "qa2": {
            "signals": len(result.residual_regions),
            "true_omission_hits": known_hit,
            "false_alerts": false_alerts,
            "precision_percent": precision,
            "known_omission_recall_percent": 100.0 if known_hit else 0.0,
            "alerts_per_page": len(result.residual_regions),
        },
        "material_improvement": "NO",
        "frozen_evaluation_count": 1,
        "parameters_changed_after_reference_evaluation": False,
        "signal_family_gap": (
            "Compact line-incident residuals detect the omission but cannot distinguish it "
            "from page-wide text, symbols, annotations, and drafting structure."
        ),
    }
    return evaluation, comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate QA2-S1 source benchmark")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-document-id", required=True)
    parser.add_argument("--source-page", type=int, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=2)
    args = parser.parse_args()
    if args.replay_runs < 2:
        raise SystemExit("--replay-runs must be at least 2")

    runtime_results = []
    for _ in range(args.replay_runs):
        t1 = run_draftsman_vs3_t1(
            args.source,
            source_document_id=args.source_document_id,
            source_page=args.source_page,
        )
        u1 = preserve_draftsman_vs3_u1(t1)
        qa1 = audit_draftsman_qa1(u1)
        runtime_results.append(
            measure_independent_source_coverage(
                args.source, u1_result=u1, qa1_audit=qa1
            )
        )
    result_ids = tuple(item.result_id for item in runtime_results)
    if len(set(result_ids)) != 1:
        raise SystemExit("QA2-S1 runtime replay is not deterministic")

    # Reference is deliberately loaded only after all runtime regions are frozen.
    reference = FamilyAuditReference.load(args.reference)
    evaluation, comparison = _post_hoc_evaluation(
        runtime_results[0], source=args.source, reference=reference
    )
    paths = write_draftsman_qa2_s1_artifacts(
        args.output_dir,
        result=runtime_results[0],
        replay_result_ids=result_ids,
        reference_evaluation=evaluation,
        baseline_comparison=comparison,
    )
    print(dict(runtime_results[0].summary))
    print(comparison["qa2"])
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
