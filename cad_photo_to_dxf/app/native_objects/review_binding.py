"""Content bindings for reviews of a *saved* native CAD candidate.

A review is evidence for exact input samples, candidate data, saved DXF and
review implementation. It is not an ID allow-list. Paths and task output
directories are deliberately excluded so an atomic directory rename does not
invalidate identical bytes. Changed bytes or code always make a review stale.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

import numpy as np


BINDING_SCHEMA = "native-review-binding-v4.1"


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_value(value):
    """Preserve all values; no rounding, snapping, NaN-to-zero or key fallback."""
    if isinstance(value, np.ndarray):
        return canonical_value(value.tolist())
    if isinstance(value, np.generic):
        return canonical_value(value.item())
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("REVIEW_MAPPING_KEYS_MUST_BE_STRINGS")
        return {key: canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("REVIEW_NONFINITE_VALUE")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError("REVIEW_UNSUPPORTED_VALUE:" + type(value).__name__)


def canonical_sha256(value):
    encoded = json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_payload(objects):
    if not isinstance(objects, (list, tuple)):
        raise TypeError("REVIEW_CANDIDATE_LIST_REQUIRED")
    rows, identifiers = [], set()
    for obj in objects:
        if not isinstance(obj, Mapping) or not all(
            key in obj for key in ("id", "kind", "geometry", "layer")
        ):
            raise ValueError("REVIEW_CANDIDATE_CONTRACT_MISSING")
        oid = obj["id"]
        if not isinstance(oid, str) or not oid or oid in identifiers:
            raise ValueError("REVIEW_CANDIDATE_ID_MISSING_OR_DUPLICATE")
        identifiers.add(oid)
        # Only old exporter diagnostics are not intrinsic candidate data. The
        # complete geometry, source evidence and acceptance mode remain bound.
        rows.append(
            canonical_value(
                {
                    key: value
                    for key, value in obj.items()
                    if key not in ("handle_at_write", "export")
                }
            )
        )
    return sorted(rows, key=lambda row: row["id"])


def reviewer_code_identity():
    app_root = Path(__file__).resolve().parents[2]
    files = list((app_root / "app/native_objects").glob("*.py"))
    files += [app_root / "main.py"]
    for relative in (
        "app/core/native_objects_entry.py",
        "app/core/processing.py",
        "app/core/native_worker.py",
        "app/core/native_job_manager.py",
    ):
        path = app_root / relative
        if path.is_file():
            files.append(path)
    rows = {
        str(path.relative_to(app_root)): file_sha256(path)
        for path in sorted(set(files))
        if path.is_file()
    }
    versions = {"python": ".".join(map(str, sys.version_info[:3]))}
    for name in ("numpy", "scipy", "ezdxf", "PyMuPDF", "Pillow"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "UNAVAILABLE"
    return {
        "files": rows,
        "code_sha256": canonical_sha256(rows),
        "runtime_versions": versions,
        "runtime_sha256": canonical_sha256(versions),
    }


def source_identity(import_manifest):
    if not isinstance(import_manifest, Mapping):
        raise ValueError("REVIEW_IMPORT_MANIFEST_REQUIRED")
    for key in (
        "source_sha256",
        "working_array_sha256",
        "selection",
        "coordinates",
        "job",
    ):
        if key not in import_manifest:
            raise ValueError("REVIEW_IMPORT_MANIFEST_FIELD_MISSING:" + key)
    job = import_manifest["job"]
    # Exclude paths/job id, retain every input interpretation and scale field.
    selection = {
        key: job.get(key)
        for key in (
            "page_number_1based",
            "frame_number_1based",
            "roi_source_xyxy_px",
            "recognition_dpi",
            "orientation_clockwise_degrees",
            "mode",
            "unit",
            "scale_evidence",
            "paper_mm_per_recognition_pixel",
        )
    }
    identity = {
        "source_file_sha256": import_manifest["source_sha256"],
        "working_array_sha256": import_manifest["working_array_sha256"],
        "selection_sha256": canonical_sha256(
            {
                "job_selection": selection,
                "decoded_selection": import_manifest["selection"],
            }
        ),
        "coordinates_sha256": canonical_sha256(import_manifest["coordinates"]),
        "job_input_interpretation": selection,
    }
    if "connection_checkpoint" in import_manifest:
        # Scope and preserved baseline are part of the source interpretation,
        # not an old approval list.  Do not add a default key: ordinary jobs
        # retain their existing source identity shape and digest inputs.
        identity["connection_checkpoint_sha256"] = canonical_sha256(
            import_manifest["connection_checkpoint"]
        )
    return identity


def build_review_binding(
    dxf_path, objects, import_manifest, *, gray=None, source_path=None
):
    identity = source_identity(import_manifest)
    source = Path(source_path or import_manifest.get("source_path", ""))
    if not source.is_file():
        raise FileNotFoundError("REVIEW_SOURCE_BYTES_UNAVAILABLE:" + str(source))
    if file_sha256(source) != identity["source_file_sha256"]:
        raise ValueError("REVIEW_SOURCE_BYTES_CHANGED")
    if gray is not None:
        if not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.dtype != np.uint8:
            raise ValueError("REVIEW_EXPECTS_UNCHANGED_UINT8_WORKING_GRAY")
        # Buffer hashing avoids an additional full-page byte copy.
        actual = hashlib.sha256(
            memoryview(np.ascontiguousarray(gray)).cast("B")
        ).hexdigest()
        if actual != identity["working_array_sha256"]:
            raise ValueError("REVIEW_WORKING_PIXELS_CHANGED")
    payload = candidate_payload(objects)
    code = reviewer_code_identity()
    binding = {
        "schema": BINDING_SCHEMA,
        "source_identity": identity,
        "candidate_sha256": canonical_sha256(payload),
        "candidate_count": len(payload),
        "saved_DXF_sha256": file_sha256(dxf_path),
        "review_code_sha256": code["code_sha256"],
        "runtime_sha256": code["runtime_sha256"],
    }
    binding["binding_sha256"] = canonical_sha256(binding)
    return binding


def verify_saved_review(
    review_path, dxf_path, objects, import_manifest, *, source_path=None
):
    """Read-only validation, suitable immediately before atomic publication.

    Missing/changed evidence never inherits the old approval. Expected stale
    conditions are structured results; malformed JSON is also explicit. There
    is no geometry repair, OCR, rendering or old review allow-list lookup.
    """
    review_path = Path(review_path)
    try:
        saved = json.loads(review_path.read_text(encoding="utf-8"))
        if saved.get("schema") != "native-quality-review-v4":
            raise ValueError("REVIEW_SCHEMA_MISMATCH")
        current = build_review_binding(
            dxf_path, objects, import_manifest, source_path=source_path
        )
        previous = saved.get("binding", {})
        mismatches = [
            {"field": key, "reviewed": previous.get(key), "current": current.get(key)}
            for key in sorted(set(previous) | set(current))
            if previous.get(key) != current.get(key)
        ]
        for row in saved.get("evidence_assets", []):
            path = review_path.parent / row["relative_path"]
            if not path.is_file():
                mismatches.append(
                    {
                        "field": "evidence_asset",
                        "path": row["relative_path"],
                        "reason": "MISSING",
                    }
                )
            elif file_sha256(path) != row["sha256"]:
                mismatches.append(
                    {
                        "field": "evidence_asset",
                        "path": row["relative_path"],
                        "reason": "CHANGED_BYTES",
                    }
                )
        return {
            "valid": not mismatches,
            "status": "BOUND_REVIEW_CURRENT"
            if not mismatches
            else "STALE_REVIEW_PENDING",
            "mismatches": mismatches,
            "current_binding": current,
            "review_reused_as_old_ID_allowlist": False,
            "new_render_or_OCR_calls": 0,
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {
            "valid": False,
            "status": "STALE_REVIEW_PENDING",
            "mismatches": [
                {
                    "field": "review_binding",
                    "reason": type(exc).__name__,
                    "detail": str(exc),
                }
            ],
            "current_binding": None,
            "review_reused_as_old_ID_allowlist": False,
            "new_render_or_OCR_calls": 0,
        }
