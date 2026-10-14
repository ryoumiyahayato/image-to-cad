"""Future baseline B: train-only logistic regression; NOT executed during P3B."""

import argparse
from pathlib import Path

import numpy as np

from common import (
    LABELS,
    atomic_json,
    check_output,
    read,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from benchmark import evaluate, join_labels
from features import FEATURE_NAMES, feature_vector


def run(manifest, label_file, out, patch_root=None):
    labels = read(label_file)
    if labels.get("training_authorized") is not True:
        raise ValueError("Pilot/acceptance labels are not training-authorized")
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import joblib

    rows = read_rows(manifest)
    labels = read(label_file)
    if labels.get("training_authorized") is not True:
        raise ValueError("Pilot/acceptance labels are not training-authorized")
    if labels["manifest_sha256"] != sha(manifest):
        raise ValueError("Dataset/labels mismatch")
    rows = join_labels(rows, labels)
    validate_samples(rows)
    if any(r["split"] == "blind_test" for r in rows):
        raise ValueError("Blind data prohibited during model development")
    train = [r for r in rows if r["split"] == "train" and r["label"] in LABELS]
    validation = [
        r for r in rows if r["split"] == "validation" and r["label"] in LABELS
    ]
    if set(r["label"] for r in train) != set(LABELS) or not validation:
        raise ValueError(
            "Need all four human-labeled training classes and held-out validation drawings"
        )
    base = patch_root or Path(manifest).parent
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=314159),
    )
    model.fit(
        np.stack([feature_vector(r, base / r["patch_dir"]) for r in train]),
        [r["label"] for r in train],
    )
    probs = model.predict_proba(
        np.stack([feature_vector(r, base / r["patch_dir"]) for r in validation])
    )
    predictions = [
        {
            "sample_id": row["sample_id"],
            "probabilities": {
                c: float(p[list(model.classes_).index(c)]) for c in LABELS
            },
        }
        for row, p in zip(validation, probs)
    ]
    out = check_output(out)
    joblib.dump(model, out / "logistic.joblib")
    write_rows(out / "validation-predictions.jsonl", predictions)
    atomic_json(out / "metrics.json", evaluate(validation, predictions))
    atomic_json(
        out / "configuration.json",
        {
            "features": FEATURE_NAMES,
            "dataset_sha256": sha(manifest),
            "labels_sha256": sha(label_file),
            "seed": 314159,
            "calibration": "raw probabilities; not eligible for geometry",
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--patch-root", type=Path)
    args = ap.parse_args()
    run(args.manifest, args.labels, args.out, args.patch_root)
