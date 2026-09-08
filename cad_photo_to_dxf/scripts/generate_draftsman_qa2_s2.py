from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import FamilyAuditReference  # noqa: E402
from app.draftsman_qa1 import audit_draftsman_qa1  # noqa: E402
from app.draftsman_qa2_s1 import measure_independent_source_coverage  # noqa: E402
from app.draftsman_qa2_s2 import (  # noqa: E402
    QA2S2Result,
    RiskTier,
    triage_source_coverage_risk,
    write_draftsman_qa2_s2_artifacts,
    write_frozen_config,
)
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1  # noqa: E402
from app.draftsman_vs3_u1 import preserve_draftsman_vs3_u1  # noqa: E402


KNOWN_REAL_OMISSION_ID = "ELEC-150-S01-165"


def _overlap(first: tuple[int, ...], second: tuple[int, ...]) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _evaluate_frozen(
    result: QA2S2Result, reference: FamilyAuditReference
) -> tuple[dict[str, object], dict[str, object]]:
    expected = next(
        item
        for item in reference.instances
        if item.reference_instance_id == KNOWN_REAL_OMISSION_ID
    )
    hits = [
        item
        for item in result.clusters
        if _overlap(item.source_region, expected.source_bbox_px)
    ]
    known_tier = "MISSED"
    if hits:
        known_tier = min(
            (item.tier for item in hits),
            key=lambda tier: (RiskTier.A, RiskTier.B, RiskTier.C).index(tier),
        ).name
    tier_counts = Counter(item.tier for item in result.clusters)
    hit_ids = {item.cluster_id for item in hits}
    tier_metrics: dict[str, dict[str, object]] = {}
    for tier in RiskTier:
        true_hits = int(any(item.tier is tier for item in hits))
        false_alerts = sum(
            item.tier is tier and item.cluster_id not in hit_ids for item in result.clusters
        )
        total = tier_counts[tier]
        tier_metrics[tier.name] = {
            "signals": total,
            "true_hits": true_hits,
            "false_alerts": false_alerts,
            "precision_percent": 0.0 if not total else round(100.0 * true_hits / total, 4),
        }
    false_families = Counter(
        item.generic_family.value
        for item in result.clusters
        if item.tier is RiskTier.A and item.cluster_id not in hit_ids
    )
    tier_a_true_hits = int(any(item.tier is RiskTier.A for item in hits))
    tier_a_false_alerts = sum(
        item.tier is RiskTier.A and item.cluster_id not in hit_ids
        for item in result.clusters
    )
    evaluation: dict[str, object] = {
        "schema_version": "draftsman-qa2-s2-reference-evaluation-v1",
        "usage": "ONE_POST_HOC_EVALUATION_AFTER_CONFIG_PERSISTENCE",
        "frozen_config_id": result.config.config_id,
        "known_silent_omission_evaluated": 1,
        "raw_s1_detected": bool(hits),
        "clustered_residual_present": bool(hits),
        "known_omission_tier": known_tier,
        "known_omission_actionable_candidate": any(
            item.tier is RiskTier.A for item in hits
        ),
        "known_omission_independent_of_glyph_frontend": all(
            item.independent_of_glyph_evidence for item in hits
        ),
        "hit_cluster_ids": sorted(hit_ids),
        "tier_a": tier_metrics[RiskTier.A.name],
        "tier_b": tier_metrics[RiskTier.B.name],
        "tier_c": tier_metrics[RiskTier.C.name],
        "tier_a_false_signal_families": dict(false_families.most_common()),
        "golden_reference_runtime_dependency": False,
        "post_evaluation_tuning_performed": False,
    }
    tier_a = tier_metrics[RiskTier.A.name]
    comparison: dict[str, object] = {
        "schema_version": "draftsman-qa2-s2-baseline-comparison-v1",
        "qa0": {
            "signals": 37,
            "true_hits": 1,
            "false_alerts": 36,
            "precision_percent": 2.7027,
            "known_omission_recall_percent": 100.0,
            "alerts_per_page": 37,
        },
        "qa2_s1": {
            "signals": 220,
            "true_hits": 1,
            "false_alerts": 219,
            "precision_percent": 0.4545,
            "known_omission_recall_percent": 100.0,
            "alerts_per_page": 220,
        },
        "qa2_s2_tier_a": {
            **tier_a,
            "known_omission_recall_percent": (
                100.0 if tier_a_true_hits else 0.0
            ),
            "alerts_per_page": tier_a["signals"],
        },
        "materially_improves_review_burden": (
            "YES"
            if tier_a_false_alerts < 36 and tier_a_true_hits == 1
            else (
                "PARTIALLY"
                if tier_counts[RiskTier.A] < 220 and tier_a_true_hits == 1
                else "NO"
            )
        ),
        "evaluation_runs": 1,
        "parameters_changed_after_evaluation": False,
    }
    return evaluation, comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate QA2-S2 blind triage benchmark")
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
        s1 = measure_independent_source_coverage(
            args.source, u1_result=u1, qa1_audit=qa1
        )
        runtime_results.append(
            triage_source_coverage_risk(
                args.source, s1_result=s1, qa1_audit=qa1
            )
        )
    result_ids = tuple(item.result_id for item in runtime_results)
    if len(set(result_ids)) != 1:
        raise SystemExit("QA2-S2 replay is not deterministic")
    result = runtime_results[0]

    # This persistence is deliberately before the only Golden load/evaluation.
    frozen_path = args.output_dir / "qa2-s2-frozen-config.json"
    write_frozen_config(frozen_path, result.config)
    reference = FamilyAuditReference.load(args.reference)
    evaluation, comparison = _evaluate_frozen(result, reference)
    paths = write_draftsman_qa2_s2_artifacts(
        args.output_dir,
        result=result,
        replay_result_ids=result_ids,
        reference_evaluation=evaluation,
        baseline_comparison=comparison,
    )
    print(dict(result.summary))
    print(evaluation["tier_a"])
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
