"""Portable Colab helpers. Importing this module never trains or connects to cloud."""

import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import random
import stat
import sys
import tempfile
import warnings
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import numpy as np

CLASSES = ["SINGLE_PHYSICAL_STROKE", "TRUE_PARALLEL_STRUCTURE", "OTHER"]
PINS = {"numpy": "2.2.6", "scipy": "1.15.3", "scikit-learn": "1.7.2",
        "joblib": "1.5.2", "threadpoolctl": "3.6.0"}
MEMBERS = {"train-features.jsonl", "validation-features.jsonl", "dataset-manifest.json",
           "class-map.json", "feature-schema.json", "freeze-provenance.json",
           "training-config.json", "checksums.sha256"}
ROOT_NAME = "p3b-colab-inputs"
MARKER = "EXPLORATORY_BASELINE_ONLY"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with Path(path).open("rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False) + "\n", encoding="utf-8")


def environment(require_ml=True):
    result = {"python": sys.version, "platform": platform.platform(), "packages": {}}
    if require_ml:
        require((3, 10) <= sys.version_info[:2] <= (3, 13),
                "Python must be 3.10–3.13 for this pinned CPU environment; stop on incompatibility")
        require(not Path("/proc/driver/nvidia/version").exists()
                and not os.environ.get("COLAB_TPU_ADDR") and not os.environ.get("TPU_NAME"),
                "Select CPU / hardware accelerator None, then rerun setup")
    for name, version in PINS.items():
        try:
            result["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["packages"][name] = "NOT_INSTALLED"
        if require_ml:
            require(result["packages"][name] == version,
                    f"Dependency FAIL: {name}; run A0 install, restart session, then A1")
    if require_ml:
        # Import checks also catch ABI / binary compatibility failures before training.
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        import sklearn, scipy, joblib, threadpoolctl
        loaded = {"numpy": np.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__,
                  "joblib": joblib.__version__, "threadpoolctl": threadpoolctl.__version__}
        require(loaded == PINS, "Loaded dependency versions differ; restart the Colab session after A0")
    return result


def archive_payload(zip_path, anchors):
    require(sha(zip_path) == anchors["zip_sha256"], "Input ZIP SHA256 mismatch")
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        expected = {ROOT_NAME + "/" + n for n in MEMBERS}
        require(len(infos) == len(expected) and {i.filename for i in infos} == expected,
                "Unexpected, missing or duplicate ZIP members; Blind/extra inputs prohibited")
        require(sum(i.file_size for i in infos) < 5_000_000, "Input archive too large")
        for item in infos:
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename
                    and not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16),
                    "Unsafe ZIP member")
        payload = {PurePosixPath(i.filename).name: archive.read(i) for i in infos}
    sums = payload["checksums.sha256"]
    require(hash_bytes(sums) == anchors["checksums_sha256"], "Checksum list identity mismatch")
    listed = {}
    for line in sums.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        require(name not in listed and name in MEMBERS - {"checksums.sha256"}, "Invalid checksum list")
        listed[name] = digest
    require(set(listed) == MEMBERS - {"checksums.sha256"}, "Incomplete checksum coverage")
    for name, digest in listed.items():
        require(hash_bytes(payload[name]) == digest, "Member checksum mismatch: " + name)
    return payload


def validate_payload(payload, anchors):
    documents = {n: json.loads(payload[n]) for n in MEMBERS if n.endswith(".json")}
    manifest, schema, config, provenance = [documents[n] for n in
        ("dataset-manifest.json", "feature-schema.json", "training-config.json", "freeze-provenance.json")]
    require(manifest == anchors["manifest"], "Frozen manifest identity / sample IDs changed")
    require(config == anchors["config"], "Frozen training / threshold configuration changed")
    require(schema["feature_order"] == anchors["feature_order"] and schema["feature_count"] == 18
            and schema["dtype"] == "float32", "18-feature schema/order mismatch")
    require(documents["class-map.json"] == {"classes": CLASSES, "class_to_index":
            {c: i for i, c in enumerate(CLASSES)}, "AMBIGUOUS": "ABSTENTION_EVALUATION_ONLY"},
            "Three-class mapping mismatch")
    require(provenance["final_manifest_sha256"] == manifest["frozen_manifest_sha256"]
            and provenance["DATA_INTEGRITY"] == "PASS" and provenance["LABEL_PROVENANCE"] == "VERIFIED"
            and provenance["human_labels_infallible"] is False, "Freeze/provenance binding failed")
    require(config["dataset_version"] == manifest["dataset_version"]
            and config["seed"] == 314159 and config["classes"] == CLASSES
            and config["C"] == 1.0 and config["max_iter"] == 1000
            and config["class_weight"] == "balanced" and config["solver"] == "lbfgs"
            and config["thresholds_for_reporting"] == [0.5, 0.8, 0.9, 0.95, 0.99, 0.995],
            "Frozen baseline contract mismatch")
    rows = {}
    matrices = {}
    for split in ("train", "validation"):
        rows[split] = [json.loads(line) for line in payload[split + "-features.jsonl"].decode().splitlines()]
        ids = [r["sample_id"] for r in rows[split]]
        require(ids == manifest[split]["sample_ids"] and len(ids) == len(set(ids))
                and len(ids) == manifest[split]["count"], "Sample count/ordered ID mismatch: " + split)
        require(dict(Counter(r["label"] for r in rows[split])) == manifest[split]["class_counts"],
                "Class counts mismatch: " + split)
        for row in rows[split]:
            require(row["split"] == split and row["domain"] == "real" and row["stage0"] == "VALID_TARGET",
                    "Blind, synthetic or X/U sample cannot enter input")
            require(row["label"] in CLASSES if split == "train" else row["label"] in CLASSES + ["AMBIGUOUS"],
                    "Invalid supervised / validation class")
            role = "SUPERVISED_TRAIN" if split == "train" else (
                "ABSTENTION_EVALUATION" if row["label"] == "AMBIGUOUS" else "CLASSIFICATION_EVALUATION")
            require(row["role"] == role and row["target_kind"] in ("PAIR", "SINGLE", "CONTROL"),
                    "Sample evaluation role / target-kind mismatch")
            x = np.asarray(row["features"], dtype=np.float32)
            require(x.shape == (18,) and np.isfinite(x).all(), "Nonfinite / missing / malformed feature vector")
            require(hash_bytes(x.astype("<f4").tobytes()) == row["feature_sha256"], "Feature vector hash mismatch")
            missing = row["missing_features"]
            require(len(missing) == 18 and all(type(v) is bool for v in missing), "Missing indicators malformed")
            require(np.all(x[np.array(missing)] == 0), "Frozen zero default mismatch")
            require(float(x[4]) == float(row["source_dpi"] is not None)
                    and float(x[11]) == float(row["profile_present"])
                    and float(x[17]) == float(row["target_kind"] == "PAIR"), "Availability / pair indicators mismatch")
            require(float(x[3]) == float(np.float32((row["source_dpi"] or 0) / 600)), "DPI feature mismatch")
            require(missing[3] == (row["source_dpi"] is None), "Missing DPI flag mismatch")
            if not row["profile_present"]:
                require(all(missing[i] for i in (10, 12, 13, 14, 15, 16)), "Missing profile flags mismatch")
            require(all(row.get(k) for k in ("source_drawing_id", "source_family_id", "source_sha256",
                    "patch_sha256", "record_reference", "truth_reference", "record_sha256", "truth_record_sha256")),
                    "Missing per-sample provenance")
        matrices[split] = np.asarray([r["features"] for r in rows[split]], dtype=np.float32)
    train, validation = rows["train"], rows["validation"]
    require(set(r["label"] for r in train) == set(CLASSES), "Training needs exactly three classes")
    for field in ("sample_id", "source_drawing_id", "source_family_id", "source_sha256", "patch_sha256"):
        require(not ({r[field] for r in train} & {r[field] for r in validation}), "Cross-split leakage: " + field)
    excluded = {r["sample_id"] for r in manifest["excluded"]}
    require(not excluded & {r["sample_id"] for split in rows.values() for r in split}, "Excluded X/U sample included")
    require([r["sample_id"] for r in validation if r["label"] == "AMBIGUOUS"] == manifest["ambiguous_sample_ids"],
            "AMBIGUOUS identity lost / remapped")
    x = matrices["train"].astype(np.float64)
    norm = schema["training_normalization"]
    require(norm["fit_sample_ids"] == sorted(r["sample_id"] for r in train)
            and norm["validation_stats_used"] is False, "Scaler fit population mismatch")
    for values, name in ((x.mean(0), "mean"), (x.var(0), "variance")):
        require(np.allclose(values, norm[name], rtol=1e-12, atol=1e-14), "Frozen train statistics mismatch: " + name)
    scale = np.sqrt(x.var(0)); scale[scale == 0] = 1
    require(np.allclose(scale, norm["scale"], rtol=1e-12, atol=1e-14), "Frozen scaler scale mismatch")
    identity = {"zip_sha256": anchors["zip_sha256"], "files": {n: hash_bytes(b) for n, b in sorted(payload.items())},
                "frozen_manifest_sha256": manifest["frozen_manifest_sha256"],
                "dataset_version": manifest["dataset_version"], "config_sha256": hash_bytes(canonical(config))}
    return rows, matrices, documents, identity


@dataclass(frozen=True)
class PreflightReceipt:
    zip_path: str
    root: str
    identity_digest: str
    environment_digest: str
    ml_checked: bool


def preflight(zip_path, anchors, require_ml=True):
    try:
        env = environment(require_ml)
        payload = archive_payload(zip_path, anchors)
        rows, matrices, documents, identity = validate_payload(payload, anchors)
        root = Path(tempfile.mkdtemp(prefix="p3b-colab-")) / ROOT_NAME
        root.mkdir()
        for name, data in payload.items():
            (root / name).write_bytes(data)
        report = {"status": "PASS", "train": len(rows["train"]), "validation": len(rows["validation"]),
                  "features": 18, "classes": CLASSES, "AMBIGUOUS": documents["dataset-manifest.json"]["ambiguous_sample_ids"],
                  "leakage": "NONE", "Blind_inputs": 0, "SHA256": "PASS", "environment": env,
                  "ML_DEPENDENCY_CHECK": "PASS" if require_ml else "NOT_RUN_LOCAL_DATA_ONLY"}
        print("PRE-FLIGHT PASS\n" + json.dumps(report, ensure_ascii=False, indent=2))
        return PreflightReceipt(str(Path(zip_path).resolve()), str(root), hash_bytes(canonical(identity)),
                                hash_bytes(canonical(env)), require_ml)
    except Exception as error:
        print("PRE-FLIGHT FAIL — TRAIN BLOCKED: " + str(error))
        raise


def guarded_inputs(receipt, anchors, require_ml=True):
    require(isinstance(receipt, PreflightReceipt), "Run PRE-FLIGHT A1 successfully first")
    require(not require_ml or receipt.ml_checked, "ML dependencies were not preflighted")
    payload = archive_payload(receipt.zip_path, anchors)
    for name, data in payload.items():
        require((Path(receipt.root) / name).is_file() and sha(Path(receipt.root) / name) == hash_bytes(data),
                "Extracted input changed after PRE-FLIGHT: " + name)
    rows, matrices, docs, identity = validate_payload(payload, anchors)
    require(hash_bytes(canonical(identity)) == receipt.identity_digest, "Input/config receipt identity changed")
    require(hash_bytes(canonical(environment(require_ml))) == receipt.environment_digest,
            "Environment changed; restart setup / PRE-FLIGHT")
    return rows, matrices, docs, identity


def model_bytes(model):
    import joblib
    buffer = io.BytesIO()
    joblib.dump(model, buffer, compress=0)
    return buffer.getvalue()


def train_manual(receipt, anchors):
    rows, matrices, docs, identity = guarded_inputs(receipt, anchors)
    config = docs["training-config.json"]
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    require(input("只在 PRE-FLIGHT PASS 后输入 TRAIN 并回车，手动开始一次训练：") == "TRAIN", "Training not started")
    started_at_utc = datetime.now(timezone.utc).isoformat()
    random.seed(config["seed"]); np.random.seed(config["seed"])
    model = Pipeline([("scaler", StandardScaler()), ("classifier", LogisticRegression(
        C=config["C"], max_iter=config["max_iter"], class_weight=config["class_weight"],
        random_state=config["seed"], solver=config["solver"], tol=config["tol"]))])
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(matrices["train"], [r["label"] for r in rows["train"]])
    norm = docs["feature-schema.json"]["training_normalization"]
    scaler = model.named_steps["scaler"]
    require(int(scaler.n_samples_seen_) == len(rows["train"]), "Scaler saw nontraining samples")
    for field, values in (("mean_", norm["mean"]), ("var_", norm["variance"]), ("scale_", norm["scale"])):
        require(np.allclose(getattr(scaler, field), values, rtol=1e-12, atol=1e-14), "Fitted scaler changed: " + field)
    require(set(model.classes_) == set(CLASSES), "Model class mismatch")
    print("TRAIN COMPLETE — user-started CPU LogisticRegression; no validation fit")
    return {"model": model, "model_sha256": hash_bytes(model_bytes(model)), "identity": identity,
            "config": config, "environment": environment(), "validation": None,
            "started_at_utc": started_at_utc,
            "rng_state": {"python": repr(random.getstate()), "numpy": repr(np.random.get_state())}}


def guarded_run(receipt, anchors, run):
    require(isinstance(run, dict) and "model" in run, "TRAIN has not completed")
    data = guarded_inputs(receipt, anchors)
    require(data[3] == run["identity"] and data[2]["training-config.json"] == run["config"], "Training/input identity mismatch")
    require(hash_bytes(model_bytes(run["model"])) == run["model_sha256"], "Trained model modified")
    require(environment() == run["environment"], "Model runtime environment changed")
    return data


def ratio(numerator, denominator):
    return {"numerator": int(numerator), "denominator": int(denominator),
            "rate": float(numerator / denominator) if denominator else None}


def summary(rows, predicted, max_scores, thresholds):
    ordinary = np.array([r["label"] in CLASSES for r in rows], dtype=bool)
    truth = np.array([r["label"] for r in rows]); predicted = np.asarray(predicted)
    n = len(rows); n_labeled = int(ordinary.sum())
    matrix = [[int(np.sum(ordinary & (truth == c) & (predicted == p))) for p in CLASSES] for c in CLASSES]
    per_class, f1s, recalls = {}, [], []
    for i, c in enumerate(CLASSES):
        tp = matrix[i][i]; support = sum(matrix[i]); positives = sum(row[i] for row in matrix)
        precision = tp / positives if positives else 0.0
        recall = tp / support if support else None
        f1 = 2 * tp / (support + positives) if support + positives else 0.0
        per_class[c] = {"precision": precision, "recall": recall, "support": support,
                        "predicted_support": positives, "f1": f1}
        f1s.append(f1)
        if support:
            recalls.append(recall)
    parallel = truth == "TRUE_PARALLEL_STRUCTURE"; single = predicted == "SINGLE_PHYSICAL_STROKE"
    selective = []
    for t in thresholds:
        accepted = max_scores >= t
        kept_labeled = accepted & ordinary
        selective.append({"threshold": t, "scope": "EXPLORATORY_REPORT_ONLY_UNCALIBRATED",
            "all_validation_coverage": ratio(accepted.sum(), n),
            "all_validation_abstention": ratio((~accepted).sum(), n),
            "classification_coverage": ratio(kept_labeled.sum(), n_labeled),
            "selective_accuracy": ratio(np.sum(kept_labeled & (truth == predicted)), kept_labeled.sum()),
            "FALSE_MERGE_RATE": ratio(np.sum(accepted & parallel & single), parallel.sum()),
            "SINGLE_action_coverage": ratio(np.sum(accepted & single), n),
            "SINGLE_truth_action_recall": ratio(np.sum(accepted & single & (truth == CLASSES[0])), np.sum(truth == CLASSES[0])),
            "ambiguous_rejected": ratio(np.sum((~accepted) & (~ordinary)), np.sum(~ordinary))})
    return {"all_samples": n, "classification_samples": n_labeled, "ambiguous_samples": n - n_labeled,
        "confusion_matrix": matrix, "class_order": CLASSES, "per_class": per_class,
        "macro_F1": float(np.mean(f1s)) if n_labeled else None,
        "balanced_accuracy": float(np.mean(recalls)) if recalls else None,
        "overall_accuracy_auxiliary": ratio(np.sum(ordinary & (truth == predicted)), n_labeled),
        "FALSE_MERGE_RATE": ratio(np.sum(parallel & single), parallel.sum()),
        "SINGLE_action_coverage": ratio(single.sum(), n), "abstention_coverage": selective,
        "group_metric_note": "Macro F1 uses fixed three classes (undefined precision/F1=0); balanced accuracy averages classes with support. Empty denominators are null."}


def validate_manual(receipt, anchors, run):
    rows, matrices, docs, identity = guarded_run(receipt, anchors, run)
    require(run["validation"] is None, "Validation already completed; reuse exported results without tuning")
    require(input("输入 VALIDATE 并回车，执行一次冻结验证：") == "VALIDATE", "Validation not started")
    validation = rows["validation"]; model = run["model"]
    probabilities = model.predict_proba(matrices["validation"])
    probabilities = probabilities[:, [list(model.classes_).index(c) for c in CLASSES]]
    require(np.isfinite(probabilities).all() and np.allclose(probabilities.sum(1), 1), "Invalid model scores")
    predicted = np.array(CLASSES)[probabilities.argmax(1)]; scores = probabilities.max(1)
    thresholds = run["config"]["thresholds_for_reporting"]
    metrics = {"status": MARKER, "probability_note": "Uncalibrated predict_proba scores, not reliable true confidence probabilities",
               "overall": summary(validation, predicted, scores, thresholds)}
    for field in ("source_family_id", "source_drawing_id", "source_dpi", "target_kind"):
        groups = defaultdict(list)
        for i, r in enumerate(validation):
            key = "UNKNOWN_DPI" if field == "source_dpi" and r[field] is None else str(r[field])
            groups[key].append(i)
        if field == "target_kind":
            for kind in ("PAIR", "SINGLE", "CONTROL"):
                groups.setdefault(kind, [])
        metrics["by_" + field] = {k: summary([validation[i] for i in ix], predicted[ix], scores[ix], thresholds)
                                      for k, ix in sorted(groups.items())}
    predictions = []
    for i, r in enumerate(validation):
        predictions.append({k: r[k] for k in ("sample_id", "split", "label", "role", "source_family_id",
                            "source_drawing_id", "source_dpi", "target_kind", "record_reference", "truth_reference")}
                           | {"prediction": str(predicted[i]), "max_uncalibrated_score": float(scores[i])}
                           | {"score_" + c: float(probabilities[i, j]) for j, c in enumerate(CLASSES)}
                           | {"abstain_at_" + str(t): bool(scores[i] < t) for t in thresholds})
    ambiguous = [r for r in predictions if r["label"] == "AMBIGUOUS"]
    evaluation = {"status": MARKER, "thresholds": thresholds, "policy": "Frozen exploratory thresholds; none selected as best",
                  "coverage_table": metrics["overall"]["abstention_coverage"], "ambiguous_cases": ambiguous,
                  "limitation": "One human AMBIGUOUS case cannot establish reliable abstention; no production safety claim"}
    run["validation"] = {"metrics": metrics, "predictions": predictions, "abstention": evaluation}
    run["validation_sha256"] = hash_bytes(canonical(run["validation"]))
    print(MARKER + "\n" + json.dumps(metrics["overall"], ensure_ascii=False, indent=2))
    print("\nConfusion matrix — rows=truth, columns=prediction")
    print("truth," + ",".join(CLASSES))
    for i, c in enumerate(CLASSES):
        print(c + "," + ",".join(str(v) for v in metrics["overall"]["confusion_matrix"][i]))
    print("\nAbstention / coverage table — all 50 validation samples; raw scores uncalibrated")
    print("threshold,accepted,total,abstained,single_actions,false_merges,all_true_parallel,selective_accuracy")
    for item in evaluation["coverage_table"]:
        print(",".join(str(v) for v in (item["threshold"], item["all_validation_coverage"]["numerator"],
            item["all_validation_coverage"]["denominator"], item["all_validation_abstention"]["numerator"],
            item["SINGLE_action_coverage"]["numerator"], item["FALSE_MERGE_RATE"]["numerator"],
            item["FALSE_MERGE_RATE"]["denominator"], item["selective_accuracy"]["rate"])))
    for field in ("source_family_id", "source_drawing_id", "source_dpi", "target_kind"):
        print("\nGrouped results: " + field)
        print("group,all_samples,classification_samples,macro_F1,balanced_accuracy,false_merges,all_true_parallel")
        for group, values in metrics["by_" + field].items():
            print(",".join(str(v) for v in (group, values["all_samples"], values["classification_samples"],
                values["macro_F1"], values["balanced_accuracy"], values["FALSE_MERGE_RATE"]["numerator"],
                values["FALSE_MERGE_RATE"]["denominator"])))
    print("Complete grouped metrics and all threshold reports will be included in the exported metrics.json.")
    print("AMBIGUOUS — separate observed case(s):\n" + json.dumps(ambiguous, ensure_ascii=False, indent=2))
    return metrics


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def export_manual(receipt, anchors, run):
    guarded_run(receipt, anchors, run)
    require(run["validation"] is not None, "VALIDATE must complete before EXPORT")
    require(hash_bytes(canonical(run["validation"])) == run["validation_sha256"], "Evaluation results changed")
    require(input("输入 EXPORT 并回车，导出并下载研究结果：") == "EXPORT", "Export not started")
    root = Path(tempfile.mkdtemp(prefix="p3b-results-")) / "p3b-baseline-results"; root.mkdir()
    validation = run["validation"]
    for name, value in (("metrics.json", validation["metrics"]), ("abstention-evaluation.json", validation["abstention"]),
                        ("environment.json", run["environment"]), ("training-config.json", run["config"]),
                        ("data-identity.json", run["identity"]), ("rng-state.json", run["rng_state"])):
        write_json(root / name, value)
    predictions = validation["predictions"]
    write_csv(root / "predictions.csv", predictions, list(predictions[0]))
    matrix = validation["metrics"]["overall"]["confusion_matrix"]
    write_csv(root / "confusion-matrix.csv", [{"truth": c, **dict(zip(CLASSES, matrix[i]))}
                                             for i, c in enumerate(CLASSES)], ["truth"] + CLASSES)
    (root / "logistic-pipeline.joblib").write_bytes(model_bytes(run["model"]))
    write_json(root / "run-metadata.json", {"status": MARKER, "started_at_utc": run["started_at_utc"],
               "model_sha256": run["model_sha256"], "validation_sha256": run["validation_sha256"]})
    (root / "README.txt").write_text(
        "EXPLORATORY_BASELINE_ONLY\nOffline research only. No production geometry / DXF / OCR integration.\n"
        "94 train, 49 classification validation + 1 separate human AMBIGUOUS.\n"
        "Raw LogisticRegression scores are not calibrated confidence. All six thresholds are reporting only.\n"
        "FALSE_MERGE_RATE always uses ALL true-parallel cases in the denominator, even after abstention.\n"
        "SINGLE action coverage = predicted/accepted SINGLE / all 50 validation samples (includes ambiguity).\n"
        "joblib uses pickle: ONLY load trusted model files; unknown files can execute code.\n"
        "Use the SAME Python major/minor and exact numpy/scipy/scikit-learn/joblib/threadpoolctl versions\n"
        "recorded in environment.json. Cross-version loading is unsupported.\n"
        "Colab temporary files may disappear. Download this ZIP and return it for offline analysis.\n", encoding="utf-8")
    files = sorted(p for p in root.iterdir() if p.is_file())
    (root / "checksums.sha256").write_text("".join(sha(p) + "  " + p.name + "\n" for p in files), encoding="utf-8")
    out = root.parent / "p3b-baseline-results.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(root.iterdir()):
            archive.write(p, root.name + "/" + p.name)
    print("EXPORT PASS:", out, "SHA256:", sha(out))
    from google.colab import files
    files.download(str(out))
    return str(out)
