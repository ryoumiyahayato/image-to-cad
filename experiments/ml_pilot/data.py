"""Small, synthetic-only Gate 0 package. Never reads production or blind data."""

import argparse
import json
import math
import random
from pathlib import Path

CLASSES = ["SINGLE_PHYSICAL_STROKE", "TRUE_PARALLEL_STRUCTURE", "OTHER"]
FEATURE_NAMES = [
    "separation_256", "angle_delta_180", "overlap_256", "dpi_600", "dpi_known",
    "mean_gray", "std_gray", "dark_fraction", "gradient_x", "gradient_y",
    "width_px_16", "width_known", "stable_fraction", "dark_core_fraction",
    "center_offset_16", "profile_samples_19", "contrast_separated_fraction", "pair_present",
]
ARTIFICIAL_VERSION = "p12a-artificial-env-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def make_artificial():
    """Feature vectors test plumbing, not drawing recognition or CAD recovery."""
    rng = random.Random(314159)
    rows = []
    for split, repetitions in (("train", 4), ("validation", 2)):
        for category, label in enumerate(CLASSES):
            for index in range(repetitions):
                features = [rng.uniform(-0.1, 0.1) for _ in FEATURE_NAMES]
                features[category] += 1.0
                identity = f"artificial-{split}-{category}-{index}"
                rows.append({
                    "sample_id": identity, "split": split, "label": label,
                    "source_family_id": f"artificial-{split}-family-{category}",
                    "source_document_id": f"artificial-{split}-family-{category}",
                    "source_object_id": identity, "features": features,
                })
    return {
        "schema_version": 1, "dataset_version": ARTIFICIAL_VERSION,
        "domain": "ARTIFICIAL_CONTRACT_TEST", "purpose": "ENVIRONMENT_ONLY",
        "license": "PROJECT_AUTHORED_ARTIFICIAL", "classes": CLASSES,
        "feature_names": FEATURE_NAMES, "samples": rows,
    }


def validate(package):
    require(package.get("dataset_version") == ARTIFICIAL_VERSION, "Unknown data version")
    require(package.get("domain") == "ARTIFICIAL_CONTRACT_TEST"
            and package.get("purpose") == "ENVIRONMENT_ONLY", "Real training is disabled")
    require(package.get("license") == "PROJECT_AUTHORED_ARTIFICIAL", "Unapproved data")
    require(package.get("classes") == CLASSES, "Class order changed")
    require(package.get("feature_names") == FEATURE_NAMES, "Feature units/order changed")
    rows = package.get("samples", [])
    require(0 < len(rows) <= 64, "Gate 0 accepts at most 64 artificial records")
    ids = set()
    groups = {field: {} for field in
              ("source_family_id", "source_document_id", "source_object_id")}
    classes = {"train": set(), "validation": set()}
    for row in rows:
        split = row.get("split")
        require(split in classes, "Only train/validation are allowed; blind/reserve prohibited")
        identity = row.get("sample_id")
        require(isinstance(identity, str) and identity.startswith("artificial-")
                and identity not in ids, "Missing, non-artificial or repeated sample")
        ids.add(identity)
        require(row.get("label") in CLASSES, "UNKNOWN/AMBIGUOUS are not hard training labels")
        classes[split].add(row["label"])
        vector = row.get("features", [])
        require(len(vector) == len(FEATURE_NAMES) and all(
            type(v) in (int, float) and math.isfinite(v) for v in vector
        ), "Need 18 finite feature values")
        for field, assignments in groups.items():
            group = row.get(field)
            require(isinstance(group, str) and group.startswith("artificial-"), "Missing source group")
            require(group not in assignments or assignments[group] == split,
                    f"Cross-split source leakage: {field}")
            assignments[group] = split
    require(all(value == set(CLASSES) for value in classes.values()), "Missing artificial class")
    return {"dataset_version": package["dataset_version"], "domain": package["domain"],
            "samples": len(rows), "train": sum(r["split"] == "train" for r in rows),
            "validation": sum(r["split"] == "validation" for r in rows),
            "source_family_overlap": [], "real_samples": 0, "blind_samples": 0}


def load(path):
    path = Path(path)
    require(path.stat().st_size <= 500_000, "Gate 0 package exceeds 500 KB")
    package = json.loads(path.read_text(encoding="utf-8"))
    validate(package)
    return package


def validate_references(rows):
    """Read-only catalogue consistency, not file integrity or training permission."""
    require(0 < len(rows) <= 500, "Reference catalogue outside this pilot's scope")
    ids, families, drawings = set(), {}, {}
    for row in rows:
        require(row.get("split") in ("train", "validation"), "Blind/reserve/unassigned references prohibited")
        require(row.get("sample_id") and row["sample_id"] not in ids, "Duplicate reference")
        ids.add(row["sample_id"])
        allowed = CLASSES if row["split"] == "train" else CLASSES + ["AMBIGUOUS"]
        require(row.get("label") in allowed, "UNKNOWN is not a hard reference label")
        require(row.get("human_review_record_present") is True and row.get("truth_reference")
                and row.get("record_reference"), "Missing human truth provenance")
        for key, groups in (("source_family_id", families), ("source_drawing_id", drawings)):
            value = row.get(key)
            require(value and (value not in groups or groups[value] == row["split"]),
                    "Reference source leakage: " + key)
            groups[value] = row["split"]
    return {"references": len(rows), "families": len(families), "drawings": len(drawings),
            "training_permission": "NOT_GRANTED_BY_THIS_CHECK"}


def write_json(path, document):
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
                          + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(load(args.dataset)), indent=2))
