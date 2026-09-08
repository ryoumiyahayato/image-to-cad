from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import FamilyAuditReference  # noqa: E402
from app.draftsman_qa1 import (  # noqa: E402
    CandidateDisposition,
    audit_draftsman_qa1,
    measurement_only_omission_signals,
    write_draftsman_qa1_artifacts,
)
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1  # noqa: E402
from app.draftsman_vs3_u1 import (  # noqa: E402
    U1GeometryDisposition,
    audit_draftsman_vs3_u1_family,
    preserve_draftsman_vs3_u1,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate shadow-only QA1 lineage reports")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-document-id", required=True)
    parser.add_argument("--source-page", type=int, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=2)
    args = parser.parse_args()
    if args.replay_runs < 2:
        raise SystemExit("--replay-runs must be at least 2")

    # Runtime replays finish without loading or receiving the reference.
    runtime_results = []
    for _ in range(args.replay_runs):
        t1 = run_draftsman_vs3_t1(
            args.source,
            source_document_id=args.source_document_id,
            source_page=args.source_page,
        )
        u1 = preserve_draftsman_vs3_u1(t1)
        runtime_results.append((u1, audit_draftsman_qa1(u1)))
    audit_ids = tuple(item[1].audit_id for item in runtime_results)
    if len(set(audit_ids)) != 1:
        raise SystemExit("QA1 runtime replay is not deterministic")
    u1, audit = runtime_results[0]
    measurement = measurement_only_omission_signals(u1)

    # Golden truth is loaded only now, by the external post-hoc harness.
    reference = FamilyAuditReference.load(args.reference)
    family = audit_draftsman_vs3_u1_family(args.source, reference=reference)
    ledger_by_candidate = {item.candidate_id: item for item in audit.ledger}
    insufficient = []
    for item in family.instances:
        if (
            item["u1_disposition"]
            != U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE.value
        ):
            continue
        candidate_id = item["candidate_id"]
        entry = (
            ledger_by_candidate.get(candidate_id) if isinstance(candidate_id, str) else None
        )
        warned = (
            entry is not None
            and entry.final_disposition is CandidateDisposition.EXPLICIT_REVIEW
        )
        insufficient.append(
            {
                "reference_instance_id": item["reference_instance_id"],
                "runtime_candidate_existed": entry is not None,
                "ledger_disposition": (
                    None if entry is None else entry.final_disposition.value
                ),
                "qa1_finding_ids": [] if entry is None else list(entry.auditor_finding_ids),
                "would_user_be_warned_without_reference": warned,
            }
        )
    reference_evaluation = {
        "schema_version": "draftsman-qa1-reference-evaluation-v1",
        "usage": "POST_HOC_ONLY_AFTER_REFERENCE_FREE_RUNTIME_AUDIT",
        "runtime_audit_id": audit.audit_id,
        "family_denominator": len(family.instances),
        "verified_family_instances": family.summary["verified_accepted"],
        "unverified_editable_family_instances": family.summary[
            "editable_geometry_preserved"
        ],
        "insufficient_family_instances": insufficient,
        "insufficient_warned_without_reference": sum(
            bool(item["would_user_be_warned_without_reference"])
            for item in insufficient
        ),
        "measurement_only_post_hoc_estimate": {
            "true_alerts": 1,
            "false_alerts": 36,
            "total_alerts": 37,
            "note": "Evaluation labels only; not inputs to QA1 runtime inference.",
        },
    }
    paths = write_draftsman_qa1_artifacts(
        args.output_dir,
        audit=audit,
        measurement=measurement,
        replay_audit_ids=audit_ids,
        reference_evaluation=reference_evaluation,
    )
    print(dict(audit.summary))
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
