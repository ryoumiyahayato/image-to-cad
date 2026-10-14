"""Offline scoring contract. Unlabeled or absent populations report null, never zero risk."""

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import beta

from common import LABELS, atomic_json, read, read_rows, validate_samples


def join_labels(rows, labels):
    if labels.get("schema_version") != "p3b-label-v2":
        raise ValueError(
            "PILOT_V1_UNVERIFIED: V1 is not trusted benchmark/training truth"
        )
    statuses = labels.get("nomination_statuses", {})
    labels = labels.get("labels", {})
    for sid, label in labels.items():
        if (
            statuses.get(sid, {}).get("status") != "VALID_TARGET"
            or label.get("nomination_status") != "VALID_TARGET"
        ):
            raise ValueError("Physical class requires human VALID_TARGET")
    return [
        {
            **r,
            "label": labels.get(r["sample_id"], {}).get("label", r["label"]),
            "label_provenance": labels.get(r["sample_id"], r["label_provenance"]),
        }
        for r in rows
    ]


def validate_prediction(pred):
    probs = pred.get("probabilities")
    if probs is None:
        if pred.get("deterministic") is True and pred.get("prediction") in LABELS:
            return pred["prediction"], 0.0  # no invented probability/confidence
        if pred.get("prediction") != "ABSTAIN":
            raise ValueError("Prediction requires probabilities or explicit ABSTAIN")
        return "ABSTAIN", 0.0
    if set(probs) != set(LABELS):
        raise ValueError("Prediction needs all four classes")
    values = np.array([probs[k] for k in LABELS], dtype=float)
    if (
        not np.all(np.isfinite(values))
        or np.any(values < 0)
        or np.any(values > 1)
        or abs(values.sum() - 1) > 1e-5
    ):
        raise ValueError("Invalid probability distribution")
    i = int(values.argmax())
    return LABELS[i], float(values[i])


def score(rows, predictions):
    pred_map = {p["sample_id"]: p for p in predictions}
    if len(pred_map) != len(predictions):
        raise ValueError("Duplicate prediction IDs")
    extras = set(pred_map) - {r["sample_id"] for r in rows}
    if extras:
        raise ValueError("Prediction IDs outside this manifest")
    labeled = [r for r in rows if r["label"] in LABELS]
    confusion = {c: {p: 0 for p in (*LABELS, "ABSTAIN")} for c in LABELS}
    cases = []
    for row in labeled:
        pred, confidence = validate_prediction(
            pred_map.get(row["sample_id"], {"prediction": "ABSTAIN"})
        )
        confusion[row["label"]][pred] += 1
        cases.append((row, pred, confidence))
    per_class = {}
    for c in LABELS:
        tp = confusion[c][c]
        positive = sum(confusion[x][c] for x in LABELS)
        support = sum(confusion[c].values())
        per_class[c] = {
            "precision": tp / positive if positive else None,
            "recall": tp / support if support else None,
            "support": support,
        }
    negatives = per_class["TRUE_PARALLEL_STRUCTURE"]["support"]
    errors = confusion["TRUE_PARALLEL_STRUCTURE"]["SINGLE_PHYSICAL_STROKE"]
    upper = (
        float(beta.ppf(0.95, errors + 1, negatives - errors))
        if negatives and errors < negatives
        else 1.0
        if negatives
        else None
    )
    thresholds = []
    for threshold in (0.5, 0.8, 0.9, 0.95, 0.99, 0.995):
        accepted = [
            (r, p)
            for r, p, c in cases
            if c >= threshold and p not in ("AMBIGUOUS", "ABSTAIN")
        ]
        structural = [
            (r, p) for r, p in accepted if r["label"] == "TRUE_PARALLEL_STRUCTURE"
        ]
        thresholds.append(
            {
                "threshold": threshold,
                "accepted": len(accepted),
                "coverage": len(accepted) / len(cases) if cases else None,
                "selective_accuracy": sum(r["label"] == p for r, p in accepted)
                / len(accepted)
                if accepted
                else None,
                "FALSE_MERGE_RATE_all_parallel_denominator": sum(
                    p == "SINGLE_PHYSICAL_STROKE" for _, p in structural
                )
                / negatives
                if negatives
                else None,
                "accepted_parallel_support": len(structural),
                "FALSE_MERGE_RATE_accepted_parallel_denominator": sum(
                    p == "SINGLE_PHYSICAL_STROKE" for _, p in structural
                )
                / len(structural)
                if structural
                else None,
            }
        )
    return {
        "labeled_samples": len(cases),
        "unlabeled_samples": len(rows) - len(cases),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "FALSE_MERGE_RATE": errors / negatives if negatives else None,
        "false_merges": errors,
        "parallel_support": negatives,
        "FMR_one_sided_95pct_upper_iid": upper,
        "confidence_bound_warning": "IID bound only; correlated patches require structure grouping and drawing-cluster audit",
        "AMBIGUOUS_truth_coverage": per_class["AMBIGUOUS"]["support"] / len(cases)
        if cases
        else None,
        "AMBIGUOUS_prediction_coverage": sum(p == "AMBIGUOUS" for _, p, _ in cases)
        / len(cases)
        if cases
        else None,
        "abstention_coverage": sum(p == "ABSTAIN" for _, p, _ in cases) / len(cases)
        if cases
        else None,
        "selective": thresholds,
    }


def evaluate(rows, predictions):
    validate_samples(rows)
    result = {"overall": score(rows, predictions)}
    for field in ("source_drawing_id", "source_family_id", "source_dpi", "domain"):
        groups = defaultdict(list)
        for row in rows:
            groups[str(row.get(field))].append(row)
        result["by_" + field] = {
            k: score(
                group,
                [
                    p
                    for p in predictions
                    if p["sample_id"] in {r["sample_id"] for r in group}
                ],
            )
            for k, group in groups.items()
        }
    return result


def p3a_predictions(rows):
    """Nonmerge is abstention; it is NOT ground truth for two real structures."""
    return [
        {
            "sample_id": r["sample_id"],
            "prediction": "SINGLE_PHYSICAL_STROKE"
            if r["current_deterministic_decision"] == "MERGE_PROPOSED_OFFLINE"
            else "ABSTAIN",
            "probabilities": None,
            "deterministic": True,
            "baseline": "P3A",
            "decision": r["current_deterministic_decision"],
            "decision_available": r["current_deterministic_decision"] != "NOT_CAPTURED",
        }
        for r in rows
    ]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--predictions", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    rows = read_rows(args.manifest)
    if any(r["split"] == "blind_test" for r in rows):
        raise ValueError("Blind benchmark is outside P3B preparation")
    if args.labels:
        from common import sha

        labels = read(args.labels)
        if labels["manifest_sha256"] != sha(args.manifest):
            raise ValueError("Label manifest mismatch")
        rows = join_labels(rows, labels)
    predictions = (
        read_rows(args.predictions) if args.predictions else p3a_predictions(rows)
    )
    atomic_json(args.out, evaluate(rows, predictions))
