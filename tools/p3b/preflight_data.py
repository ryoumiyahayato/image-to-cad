"""Verify accepted human truth and freeze the existing v1 input contract.

Only cached approved train/validation crops and metadata are read. Historical
answers/freezes stay immutable. No learner, source renderer, blind loader or
cloud connection is imported or run.
"""

import argparse
from collections import Counter

import numpy as np
from PIL import Image

from audit_acceptance import audit_state
from common import (
    LABELS,
    digest,
    product_snapshot,
    read,
    read_rows,
    sha,
    validate_samples,
    write_rows,
)
from features import FEATURE_NAMES, feature_vector, image_tensor
from pilot_audit import CACHE, DOCS
from review_suspects import save_identical_or_new
from validation_suspects import (
    MANIFEST as REVIEW_MANIFEST,
    STATE as REVIEW_STATE,
    ORIGINAL_MANIFEST,
    ORIGINAL_STATE,
    adjudicate,
    compare,
    ORIGINALS,
)

CLASSES = LABELS[:3]
FINAL = DOCS / "FINAL-TRAINING-DATA-FREEZE.json"
CONTRACT = DOCS / "model-input-v1-frozen.json"
PROVENANCE = DOCS / "final-human-reliability-provenance.jsonl"
CONFIG = DOCS / "first-baseline-configuration.json"


def run():
    legacy_path = DOCS / "TRAINING-DATA-FREEZE.json"
    accepted = read(legacy_path)
    result_path = DOCS / "VALIDATION-SUSPECT-REVIEW-FINAL.json"
    result = read(result_path)
    train_path = DOCS / "formal-seed-v2-001.jsonl"
    train_truth_path = DOCS / "formal-seed-adjudicated-decisions.jsonl"
    val_truth_path = DOCS / "validation-adjudicated-decisions.jsonl"
    bindings = {
        "train_manifest": train_path,
        "train_original_labels": DOCS / "labels/formal-seed-v2-001.json",
        "train_re_review_manifest": DOCS / "suspect-review-v2-001.jsonl",
        "train_re_review_labels": DOCS / "labels/suspect-review-v2-001.json",
        "train_adjudication": train_truth_path,
        "validation_manifest": ORIGINAL_MANIFEST,
        "validation_original_labels": ORIGINAL_STATE,
        "validation_re_review_manifest": REVIEW_MANIFEST,
        "validation_re_review_labels": REVIEW_STATE,
        "validation_adjudication": val_truth_path,
        "split_manifest": DOCS / "split-manifest.json",
        "accepted_freeze": legacy_path,
        "accepted_validation_result": result_path,
    }
    before = {name: sha(path) for name, path in bindings.items()}
    for split, names in (
        (
            "train",
            (
                "train_manifest",
                "train_original_labels",
                "train_re_review_labels",
                "train_adjudication",
            ),
        ),
        (
            "validation",
            (
                "validation_manifest",
                "validation_original_labels",
                "validation_re_review_labels",
                "validation_adjudication",
            ),
        ),
    ):
        for name, key in zip(
            names,
            (
                "manifest_sha256",
                "original_label_state_sha256",
                "re_review_state_sha256",
                "adjudication_sha256",
            ),
            strict=True,
        ):
            if before[name] != accepted[split][key]:
                raise ValueError("Accepted freeze identity mismatch: " + name)
    if (
        before["accepted_freeze"] != result["training_data_freeze_sha256"]
        or before["validation_re_review_labels"] != result["re_review_state_sha256"]
        or before["validation_re_review_manifest"]
        != result["re_review_manifest_sha256"]
        or before["split_manifest"] != accepted["split_manifest_sha256"]
    ):
        raise ValueError("Final adjudication/freeze binding changed")
    for snapshot in accepted["snapshots"].values():
        if sha(snapshot["path"]) != snapshot["sha256"]:
            raise ValueError("Immutable current-truth snapshot changed")
    review_rows, review_state = read_rows(REVIEW_MANIFEST), read(REVIEW_STATE)
    history = audit_state(
        review_state, review_rows, sha(REVIEW_MANIFEST), presentation_order=review_rows
    )
    if (
        not history.get("FINAL_STATE_INTERNALLY_CONSISTENT")
        or history != result["history_audit"]
    ):
        raise ValueError("Re-review result/history differs from final saved answers")
    comparison = compare(review_rows, read(ORIGINALS), review_state)
    for key, value in comparison.items():
        if result.get(key) != value:
            raise ValueError("Recovered comparison mismatch: " + key)
    val_rows, val_truth = read_rows(ORIGINAL_MANIFEST), read_rows(val_truth_path)
    if val_truth != adjudicate(
        val_rows, read(ORIGINAL_STATE), review_rows, review_state
    ):
        raise ValueError(
            "Derived validation view differs from current adjudicated answers"
        )
    train_rows, train_truth = read_rows(train_path), read_rows(train_truth_path)
    validate_samples(train_rows + val_rows)
    assignments = {
        r["source_drawing_id"]: r for r in read(bindings["split_manifest"])["drawings"]
    }
    by_id = {r["sample_id"]: r for r in train_rows + val_rows}
    leakage = {
        key: sorted({r[key] for r in train_rows} & {r[key] for r in val_rows})
        for key in (
            "sample_id",
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
        )
    }
    if any(leakage.values()):
        raise ValueError("Cross-split leakage")
    provenance, selected, features = (
        [],
        {"train": [], "validation": [], "abstention_evaluation": []},
        [],
    )
    asset_hashes = {}
    counts = {}
    for split, rows, truth, root in (
        ("train", train_rows, train_truth, CACHE / "real-v2-formal-seed-001"),
        ("validation", val_rows, val_truth, CACHE / "validation-v2-001"),
    ):
        if len(truth) != len(rows) or {i["sample_id"] for i in truth} != {
            r["sample_id"] for r in rows
        }:
            raise ValueError("Truth/manifest population mismatch")
        classes, dpi = Counter(), Counter()
        excluded = []
        for item in truth:
            row = by_id[item["sample_id"]]
            a = assignments[row["source_drawing_id"]]
            if (
                row["split"] != split
                or a["split"] != split
                or a["source_family_id"] != row["source_family_id"]
            ):
                raise ValueError("Drawing/source family split identity mismatch")
            old0, old1 = (
                item["original_stage0"]["status"],
                (item.get("original_stage1") or {}).get("label"),
            )
            new0, new1 = (
                (item.get("re_review_stage0") or {}).get("status"),
                (item.get("re_review_stage1") or {}).get("label"),
            )
            tags = (
                ["DIRECT_HUMAN"]
                if new0 is None
                else ["CONFIRMED_BY_REREVIEW"]
                if (old0, old1) == (new0, new1)
                else ["ADJUDICATED_CHANGED"]
            )
            label, status = item["current_class"], item["current_stage0"]
            if label == "AMBIGUOUS":
                tags.append("HUMAN_AMBIGUOUS")
            if status == "INVALID_NOMINATION":
                tags.append("EXCLUDED_BAD_NOMINATION")
            ready = item["current_review_status"] == "READY"
            if ready and (status != "VALID_TARGET" or label not in LABELS):
                raise ValueError("Invalid supervised truth disposition")
            role = (
                "EXCLUDED"
                if not ready
                else "ABSTENTION_EVALUATION"
                if label == "AMBIGUOUS"
                else "SUPERVISED_TRAIN"
                if split == "train"
                else "CLASSIFICATION_EVALUATION"
            )
            provenance.append(
                {
                    "sample_id": item["sample_id"],
                    "split": split,
                    "current_human_class": label,
                    "current_stage0": status,
                    "human_reliability_provenance": tags,
                    "evaluation_role": role,
                    "exclusion_reason": status if not ready else None,
                    "human_correctness_probability": None,
                    "numeric_human_probability_invented": False,
                }
            )
            if not ready:
                excluded.append({"sample_id": row["sample_id"], "stage0": status})
                continue
            classes[label] += 1
            dpi[
                "UNKNOWN_SOURCE_DPI"
                if row["source_dpi"] is None
                else f"{row['source_dpi']:.6f}"
            ] += 1
            selected["abstention_evaluation" if label == "AMBIGUOUS" else split].append(
                row["sample_id"]
            )
            folder = root / row["patch_dir"]
            with Image.open(folder / "gray.png") as im:
                import hashlib

                if (
                    hashlib.sha256(im.convert("L").tobytes()).hexdigest()
                    != row["patch_sha256"]
                ):
                    raise ValueError("Frozen source pixels changed")
            image, feature = image_tensor(row, folder), feature_vector(row, folder)
            if (
                image.shape != (3, 256, 256)
                or image.dtype != np.float32
                or not np.isfinite(image).all()
                or image.min() < 0
                or image.max() > 1
                or feature.shape != (18,)
                or not np.isfinite(feature).all()
            ):
                raise ValueError("Concrete v1 input integrity defect")
            asset_hashes[row["sample_id"]] = {
                name: sha(folder / (name + ".png"))
                for name in ("gray", "edges", "centerline")
            }
            if split == "train" and label in CLASSES:
                features.append(feature)
        if dict(classes) != {
            k: v for k, v in accepted[split]["class_distribution"].items() if v
        } or sorted(excluded, key=lambda x: x["sample_id"]) != sorted(
            [
                {"sample_id": x["sample_id"], "stage0": x["status"]}
                for x in accepted[split]["excluded_samples"]
            ],
            key=lambda x: x["sample_id"],
        ):
            raise ValueError("Counts/exclusions differ from accepted truth")
        counts[split] = {
            "included_count": sum(classes.values()),
            "supervised_or_accuracy_count": sum(classes[c] for c in CLASSES),
            "class_distribution": {k: classes[k] for k in LABELS},
            "excluded": excluded,
            "drawings": len({r["source_drawing_id"] for r in rows}),
            "source_families": len({r["source_family_id"] for r in rows}),
            "known_dpi_distribution": {
                k: v for k, v in dpi.items() if k != "UNKNOWN_SOURCE_DPI"
            },
            "unknown_dpi_count": dpi["UNKNOWN_SOURCE_DPI"],
        }
    x = np.stack(features).astype(np.float64)
    mean, variance = x.mean(0), x.var(0)
    scale = np.sqrt(variance)
    scale[scale == 0] = 1
    contract = {
        "version": "p3b-model-input-v1-frozen",
        "image_shape": [3, 256, 256],
        "image_dtype": "float32",
        "image_channels": [
            "1-gray/255",
            "candidate_edges/255",
            "nominal_candidate_centerline/255",
        ],
        "image_transform": "Native source pixels; white padding only; no resize, deskew, autocontrast, whole-page context or extra masks",
        "feature_shape": [18],
        "feature_dtype": "float32",
        "feature_order": list(FEATURE_NAMES),
        "feature_implementation_sha256": sha(
            DOCS.parent.parent / "tools/p3b/features.py"
        ),
        "numerical_normalization": {
            "type": "StandardScaler train-only population statistics (ddof=0)",
            "mean": mean.tolist(),
            "variance": variance.tolist(),
            "scale": scale.tolist(),
            "constant_feature_scale": 1,
            "fit_sample_ids": sorted(selected["train"]),
            "validation_stats_used": False,
        },
        "missing_values": "Existing v1 zero defaults and dpi_known/width_known availability indicators retained. Missing/zero protection masks do not mean merge-safe.",
        "random_seed_policy": {
            "base_seed": 314159,
            "split_policy": "Frozen whole drawing/source family assignments; never random patch splits",
            "rng_states_required": ["python", "numpy", "framework if used"],
        },
        "first_model_classes": list(CLASSES),
        "AMBIGUOUS_hard_label_training_count": 0,
        "AMBIGUOUS_validation_role": "ABSTENTION_EVALUATION",
        "human_labels_infallible": False,
        "input_asset_sha256": asset_hashes,
        "known_limit": "v1 geometric/profile features may be missing or constant; retained without inventing measurements. target-kind shortcuts and source/DPI effects require explicit validation reporting.",
    }
    save_identical_or_new(CONTRACT, contract)
    if PROVENANCE.exists() and digest(read_rows(PROVENANCE)) != digest(provenance):
        raise ValueError("Derived provenance differs; preserve the existing version")
    if not PROVENANCE.exists():
        write_rows(PROVENANCE, provenance)
    config = {
        "dataset_version": "p3b-final-three-class-abstention-v1",
        "model": "18-feature standardized LogisticRegression",
        "classes": list(CLASSES),
        "seed": 314159,
        "max_iter": 1000,
        "class_weight": "balanced",
        "C": 1.0,
        "scaling": "training-only StandardScaler",
        "thresholds_for_reporting": [0.5, 0.8, 0.9, 0.95, 0.99, 0.995],
        "selection": "No model selection or confidence threshold tuning on blind data; avoid tuning on these reviewed validation answers",
        "metrics": [
            "per_class_precision",
            "per_class_recall",
            "confusion_matrix",
            "balanced_accuracy",
            "macro_F1",
            "FALSE_MERGE_RATE",
            "SINGLE_action_coverage",
            "abstention_coverage",
            "selective_accuracy",
        ],
        "FALSE_MERGE_RATE": "truth TRUE_PARALLEL predicted SINGLE / all truth TRUE_PARALLEL; denominator retained under abstention",
        "ambiguous_evaluation": "Separate abstention group, never remapped into supervised accuracy truth",
        "CNN_gate": "No CNN unless a later decision after the classical benchmark justifies it",
        "CNN_future_architecture": "Conv16/32/64, global pooling, 18-feature fusion, 64-unit head, 3 logits",
        "training_authorized": False,
        "model_trained": False,
        "input_contract_sha256": sha(CONTRACT),
        "checkpoint_retention": ["latest", "best", "at most 2 explicit milestones"],
        "hot_storage": "/content/p3b",
        "durable_workspace": "MyDrive/Image-to-CAD-ML/{manifests,labels,checkpoints,metrics,runs,active-learning}",
        "checkpoint_required_fields": [
            "model_state",
            "optimizer_state",
            "completed_epoch",
            "dataset_version",
            "label_version",
            "split_manifest",
            "configuration",
            "feature_normalization",
            "random_seed",
            "RNG_state",
            "metric_history",
        ],
    }
    save_identical_or_new(CONFIG, config)
    final = {
        "dataset_version": config["dataset_version"],
        "TRAINING_DATA_FREEZE": "PASS",
        "source_freeze_sha256": sha(legacy_path),
        "human_input_bindings": {
            name: {"path": str(bindings[name]), "sha256": value}
            for name, value in before.items()
        },
        "train": counts["train"],
        "validation": counts["validation"],
        "sample_ids": {k: sorted(v) for k, v in selected.items()},
        "source_family_splits": accepted["source_family_splits"],
        "drawing_source_family_identities": {
            split: accepted[split]["source_identities"]
            for split in ("train", "validation")
        },
        "current_truth_snapshots": accepted["snapshots"],
        "input_contract_sha256": sha(CONTRACT),
        "baseline_configuration_sha256": sha(CONFIG),
        "human_provenance_sha256": sha(PROVENANCE),
        "FIRST_MODEL_CLASS_POLICY": "3_CLASS_PLUS_ABSTENTION",
        "AMBIGUOUS_TRAIN_SAMPLES_USED_AS_HARD_LABELS": 0,
        "AMBIGUOUS_VALIDATION_ROLE": "ABSTENTION_EVALUATION",
        "unresolved_disputes": 0,
        "human_labels_infallible": False,
        "TRAIN_VALIDATION_LEAKAGE": "NONE",
        "leakage_checks": leakage,
        "BLIND_TOUCHED": "NO",
        "MODEL_TRAINED": "NO",
        "training_authorized": False,
        "BACKGROUND_TASKS_CREATED": "NO",
    }
    if product_snapshot() != read(DOCS / "pilot-production-before.json") or any(
        sha(bindings[name]) != value for name, value in before.items()
    ):
        raise ValueError("Historical evidence/production changed during preflight")
    save_identical_or_new(FINAL, final)
    print(
        {
            "freeze": "PASS",
            "train": counts["train"],
            "validation": counts["validation"],
            "re_review_agreement": result["EXACT_AGREEMENT"],
            "changes": result["DISAGREEMENTS"],
            "image_and_feature_inputs_checked": sum(
                c["included_count"] for c in counts.values()
            ),
            "normalization_fitted_train_only": len(features),
            "final_manifest_sha256": sha(FINAL),
        },
        flush=True,
    )
    return final


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
