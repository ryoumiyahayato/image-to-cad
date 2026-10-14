"""Offline P3B utilities. No DXF writer or production gate is imported here."""

import hashlib
import json
import os
from pathlib import Path

LABELS = ("SINGLE_PHYSICAL_STROKE", "TRUE_PARALLEL_STRUCTURE", "OTHER", "AMBIGUOUS")
VERSION = "p3b-v1"
ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_rows(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def validate_samples(rows):
    """Reject drawing/family/source and exact input leakage, including synthetic truth."""
    seen = {}
    ids = set()
    required = {
        "sample_id",
        "source_drawing_id",
        "source_page",
        "source_bbox",
        "candidate_geometry_ids",
        "source_dpi",
        "current_p3a_measurement",
        "current_deterministic_decision",
        "label",
        "label_provenance",
        "split",
        "source_sha256",
    }
    for row in rows:
        if required - row.keys():
            raise ValueError(f"Missing fields: {required - row.keys()}")
        if row["sample_id"] in ids:
            raise ValueError("Duplicate sample ID")
        ids.add(row["sample_id"])
        if row["label"] is not None and row["label"] not in LABELS:
            raise ValueError("Invalid label")
        if row["split"] not in ("train", "validation", "blind_test"):
            raise ValueError("Invalid split")
        if row.get("domain") == "synthetic" and row["split"] == "blind_test":
            raise ValueError("Synthetic blind test prohibited")
        if (
            row.get("content_role") in ("text", "graphic")
            and row["label"] in LABELS[:2]
        ):
            raise ValueError("Text/graphic cannot be structural training truth")
        for field in (
            "source_drawing_id",
            "source_family_id",
            "source_sha256",
            "patch_sha256",
            "truth_id",
        ):
            if row.get(field):
                key = field, row[field]
                if key in seen and seen[key] != row["split"]:
                    raise ValueError(f"Cross-split leakage: {key}")
                seen[key] = row["split"]


def check_output(path):
    """Generated arrays/crops must live in a designated regenerable cache."""
    path = Path(path).resolve()
    if ROOT in path.parents and "local-artifacts" not in path.parts:
        raise ValueError("Generated data inside checkout requires local-artifacts")
    path.mkdir(parents=True, exist_ok=True)
    return path


def product_snapshot():
    return {
        str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
        for base in ("cad_photo_to_dxf/app", "cad_photo_to_dxf/tests")
        for p in sorted((ROOT / base).rglob("*"))
        if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts
    }
