"""Advisory three-class metrics; no prediction can authorize a CAD action."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from data import CLASSES, require, validate_references, write_json


def metrics(rows, probabilities, threshold=0.9):
    require(0 <= threshold <= 1, "Invalid abstention threshold")
    require(len(rows) == len(probabilities) and len(rows) > 0, "Prediction count mismatch")
    matrix = {c: {p: 0 for p in CLASSES + ["ABSTAIN"]} for c in CLASSES + ["AMBIGUOUS"]}
    brier, nll, bins = [], [], [[] for _ in range(5)]
    for row, probability in zip(rows, probabilities):
        truth = row["label"]
        require(truth in matrix, "Unknown truth must not be forced into a known class")
        require(len(probability) == 3 and all(math.isfinite(p) and 0 <= p <= 1 for p in probability)
                and abs(sum(probability) - 1) <= 1e-5, "Invalid probabilities")
        index = max(range(3), key=lambda i: probability[i])
        confidence = probability[index]
        prediction = CLASSES[index] if confidence >= threshold else "ABSTAIN"
        matrix[truth][prediction] += 1
        if truth in CLASSES:
            correct = CLASSES[index] == truth
            bins[min(4, int(confidence * 5))].append((confidence, correct))
            target = CLASSES.index(truth)
            brier.append(sum((p - int(i == target)) ** 2 for i, p in enumerate(probability)))
            nll.append(-math.log(max(probability[target], 1e-12)))
    support = {c: sum(matrix[c].values()) for c in CLASSES}
    known = sum(support.values())
    accepted = sum(sum(matrix[c][p] for p in CLASSES) for c in CLASSES)
    correct = sum(matrix[c][c] for c in CLASSES)
    parallel = support[CLASSES[1]]
    precision = {
        c: matrix[c][c] / sum(matrix[truth][c] for truth in CLASSES)
        if sum(matrix[truth][c] for truth in CLASSES) else None for c in CLASSES
    }
    recall = {c: matrix[c][c] / support[c] if support[c] else None for c in CLASSES}
    calibration = [
        {"bin": i, "count": len(b),
         "mean_confidence": sum(v for v, _ in b) / len(b) if b else None,
         "accuracy": sum(ok for _, ok in b) / len(b) if b else None}
        for i, b in enumerate(bins)
    ]
    return {
        "threshold": threshold, "confusion_matrix": matrix, "known_support": known,
        "per_class_recall": recall, "per_class_precision": precision,
        "macro_recall": sum(recall[c] for c in CLASSES) / 3
        if all(recall[c] is not None for c in CLASSES) else None,
        "coverage": accepted / known if known else None,
        "abstention_rate": 1 - accepted / known if known else None,
        "selective_accuracy": correct / accepted if accepted else None,
        "parallel_mislabeled_single": matrix[CLASSES[1]][CLASSES[0]],
        "parallel_mislabeled_single_rate": matrix[CLASSES[1]][CLASSES[0]] / parallel if parallel else None,
        "ambiguous_support": sum(matrix["AMBIGUOUS"].values()),
        "ambiguous_abstained": matrix["AMBIGUOUS"]["ABSTAIN"],
        "brier_score": sum(brier) / known if known else None,
        "negative_log_likelihood": sum(nll) / known if known else None,
        "calibration_bins": calibration,
        "expected_calibration_error": sum(
            b["count"] * abs(b["mean_confidence"] - b["accuracy"])
            for b in calibration if b["count"]
        ) / known if known else None,
        "cad_actions_authorized": 0,
        "priority_check_recall": "NOT_EVALUABLE_WITHOUT_CHECK_WORTHINESS_LABELS",
        "actual_source_suppression_rate": "NOT_APPLICABLE_NO_CAD_ACTIONS",
    }


def baseline(train, validation):
    """No learner fit: uniform abstention plus a train-only class-frequency control."""
    counts = Counter(row["label"] for row in train)
    require(set(counts) == set(CLASSES), "Training classes differ from the frozen three classes")
    prior = [counts[c] / len(train) for c in CLASSES]
    result = {"kind": "DETERMINISTIC_CONTROL_NOT_LEARNED", "train_counts": dict(counts),
              "train_prior": prior, "by_source_family": {}}
    result["uniform_abstain_at_0.9"] = metrics(validation, [[1 / 3] * 3] * len(validation), 0.9)
    result["class_prior_at_0.0"] = metrics(validation, [prior] * len(validation), 0.0)
    result["class_prior_at_0.9"] = metrics(validation, [prior] * len(validation), 0.9)
    for family in sorted({r["source_family_id"] for r in validation}):
        group = [r for r in validation if r["source_family_id"] == family]
        result["by_source_family"][family] = metrics(group, [prior] * len(group), 0.0)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.reference.read_text(encoding="utf-8").splitlines() if line]
    validate_references(rows)
    train = [r for r in rows if r["split"] == "train"]
    validation = [r for r in rows if r["split"] == "validation"]
    write_json(args.out, baseline(train, validation))
