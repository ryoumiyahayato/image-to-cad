"""Closed preparation scaffold. No real input reads or fit without admission.

No production CAD imports. This file's enabled training branch has not been
executed in P12-C. Notebook runs it only after separate real-data authorization.
"""

import argparse
from collections import Counter
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys
import time
import warnings

from data import CLASSES, FEATURE_NAMES


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def admitted(config, context):
    """Explicit local/cloud admission must precede even reading real inputs."""
    require(context in ("local", "colab"), "Unknown execution context")
    checks = config.get("admission", {})
    allowed = (
        config.get("enabled") is True
        and checks.get("gate_1a") == "GO"
        and checks.get("label_review_resolved") is True
        and checks.get("numeric_only_missing_originals_accepted") is True
        and checks.get("all_17_local_rights_confirmed") is True
        and checks.get("specific_real_fit_authorized") is True
        and bool(checks.get("authorization_reference"))
    )
    if context == "colab":
        allowed = (
            allowed
            and checks.get("gate_1b") == "GO"
            and checks.get("all_17_cloud_rights_confirmed") is True
            and checks.get("specific_upload_authorized") is True
        )
    if not allowed:
        raise PermissionError("NOT_AUTHORIZED: P12-C real data/fit admission is closed")


def validate_rows(rows, split):
    ids = set()
    for row in rows:
        require(row.get("split") == split, "Split changed; blind/reserve prohibited")
        sid = row.get("sample_id")
        require(isinstance(sid, str) and sid and sid not in ids, "Missing/duplicate ID")
        ids.add(sid)
        allowed = CLASSES if split == "train" else CLASSES + ["AMBIGUOUS"]
        require(row.get("label") in allowed, "Unknown/ambiguous hard training class")
        vector = row.get("features", [])
        require(len(vector) == 18 and all(
            type(v) in (int, float) and math.isfinite(v) for v in vector
        ), "Expected 18 finite frozen values")
        mask = row.get("missing_features", [])
        require(len(mask) == 18 and all(type(v) is bool for v in mask), "Missing mask")
        require(type(row.get("profile_present")) is bool, "Missing profile identity")
        require(all(vector[i] in (0, 1) for i in (4, 11, 17)), "Invalid known/pair flag")
        require(bool(vector[11]) == row["profile_present"], "Profile flag changed")
        for key in ("source_family_id", "source_drawing_id", "target_kind"):
            require(bool(row.get(key)), "Missing source/target: " + key)
    return ids


def validate_separation(train, validation):
    for key in ("sample_id", "source_family_id", "source_drawing_id"):
        require(not ({r[key] for r in train} & {r[key] for r in validation}),
                "Cross-split source identity: " + key)


def read_inputs(folder, config):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("dataset_version") == config["dataset_version"], "Data version")
    require(manifest.get("feature_names") == FEATURE_NAMES, "Feature order/units")
    result = {}
    for split in ("train", "validation"):
        path = folder / (split + ".jsonl")
        require(path.stat().st_size <= 500_000, "Input exceeds this small pilot scope")
        rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]
        ids = validate_rows(rows, split)
        expected = manifest["sample_ids"][split]
        require(len(expected) == len(set(expected)) and ids == set(expected), "Frozen ID list")
        require(len(rows) == (94 if split == "train" else 50), "94/50 required")
        counts = ([38, 20, 36] if split == "train" else [22, 20, 7])
        require(Counter(r["label"] for r in rows) == Counter({
            **dict(zip(CLASSES, counts)), **({"AMBIGUOUS": 1} if split == "validation" else {})
        }), "Frozen classes changed; obtain versioned review approval first")
        require(len({r["source_family_id"] for r in rows}) == (12 if split == "train" else 5),
                "Frozen source-family population changed")
        result[split] = sorted(rows, key=lambda r: r["sample_id"])
    validate_separation(result["train"], result["validation"])
    return result, manifest


def execute(folder, output, config, *, requested=False, context="colab"):
    if not requested:
        return {"status": "NOT_RUN", "reason": "Real training switch is off"}
    admitted(config, context)  # Never read real data under the current closed config.
    require(config["model"] == {
        "C": 1, "class_weight": "balanced", "max_iter": 1000,
        "random_state": 314159, "solver": "lbfgs",
    }, "Fixed model changed")
    require(config["thresholds"] == [0.5, 0.8, 0.9, 0.95, 0.99, 0.995], "Reporting points changed")
    output = Path(output)
    require(not output.exists(), "Use a new output directory; do not overwrite a model")
    rows, manifest = read_inputs(folder, config)
    # Heavy dependencies are deliberately deferred until authorized input checks pass.
    import joblib
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    from evaluate import baseline, metrics

    train, validation = rows["train"], rows["validation"]
    x = np.asarray([r["features"] for r in train], dtype=np.float32)
    xv = np.asarray([r["features"] for r in validation], dtype=np.float32)
    # Preserve frozen zeros/known flags. No validation fit, new imputer or feature selection.
    model = make_pipeline(StandardScaler(), LogisticRegression(**config["model"]))
    output.mkdir(parents=True)
    env = {"python": sys.version, "platform": platform.platform(), "device": "CPU",
           "libraries": {p: importlib.metadata.version(p) for p in
                         ("numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl")}}
    write_json(output / "environment.json", env)
    write_json(output / "config.json", config)
    write_json(output / "manifest.json", manifest)
    started = time.perf_counter()
    cpu_started = time.process_time()
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(x, [r["label"] for r in train])  # Single fixed fit, only after admission.
    fit_seconds = time.perf_counter() - started
    fit_cpu_seconds = time.process_time() - cpu_started
    # sklearn uses sorted classes; explicitly restore the fixed project order.
    columns = [list(model.classes_).index(c) for c in CLASSES]
    probabilities = model.predict_proba(xv)[:, columns].tolist()  # Single fixed validation.
    try:
        import resource  # Linux/Colab; Windows has no standard-library equivalent.
        peak_memory = {"peak_process_RSS_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                       (1 if sys.platform == "darwin" else 1024), "scope": "whole child process"}
    except ImportError:
        peak_memory = {"peak_process_RSS_bytes": None, "scope": "NOT_MEASURED on this platform"}
    report = {
        "experiment": config["experiment"], "fit_count": 1, "fit_seconds": fit_seconds,
        "fit_cpu_seconds": fit_cpu_seconds,
        "input_counts": {k: len(v) for k, v in rows.items()}, "classes": CLASSES,
        "unabstained_argmax": metrics(validation, probabilities, 0.0),
        "threshold_reports": {str(t): metrics(validation, probabilities, t)
                              for t in config["thresholds"]},
        "baseline": baseline(train, validation), "by_stratum": {},
        "optimizer_checkpoint": "NOT_APPLICABLE_SKLEARN_LBFGS",
        "resume": "No iterative continuation; completed fitted model only",
        "production_permission": "NONE; advisory numerical feasibility only",
        "formal_rule_comparison": "NOT_CAPTURED; not compared with production decisions",
        "memory_observation": peak_memory,
    }
    for field in ("source_family_id", "target_kind", "profile_present", "source_dpi"):
        report["by_stratum"][field] = {}
        for value in sorted({r[field] for r in validation}, key=str):
            indices = [i for i, r in enumerate(validation) if r[field] == value]
            report["by_stratum"][field][str(value)] = {
                str(t): metrics([validation[i] for i in indices],
                                [probabilities[i] for i in indices], t)
                for t in config["thresholds"]
            }
    # Load only the model just produced by this process, never a supplied arbitrary pickle.
    joblib.dump(model, output / "pipeline.joblib")
    loaded = joblib.load(output / "pipeline.joblib")
    require(np.array_equal(model.predict_proba(xv), loaded.predict_proba(xv)), "Model readback")
    scaler, classifier = model.steps[0][1], model.steps[1][1]
    require(all(np.isfinite(v).all() for v in
                (scaler.mean_, scaler.scale_, scaler.var_, classifier.coef_, classifier.intercept_)),
            "Non-finite fitted parameters")
    np.savez(output / "model-parameters.npz", mean=scaler.mean_, scale=scaler.scale_,
             variance=scaler.var_, coef=classifier.coef_, intercept=classifier.intercept_,
             classes=classifier.classes_, iterations=classifier.n_iter_)
    write_json(output / "metrics.json", report)
    (output / "predictions.jsonl").write_text("".join(json.dumps({
        "sample_id": row["sample_id"], "truth": row["label"], "probabilities": prob,
        "source_family_id": row["source_family_id"], "target_kind": row["target_kind"],
        "profile_present": row["profile_present"], "source_dpi": row["source_dpi"],
    }, ensure_ascii=False, allow_nan=False) + "\n" for row, prob in zip(validation, probabilities)),
        encoding="utf-8")
    return {"status": "COMPLETED_NUMERIC_ONLY", "fit_seconds": fit_seconds,
            "model_readback": "PASS", "output": str(output), "production_ML": "NO_GO"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--context", choices=("local", "colab"), default="colab")
    parser.add_argument("--execute-real", action="store_true")
    args = parser.parse_args()
    result = execute(args.input, args.out, json.loads(args.config.read_text(encoding="utf-8")),
                     requested=args.execute_real, context=args.context)
    print(json.dumps(result, ensure_ascii=False, indent=2))
