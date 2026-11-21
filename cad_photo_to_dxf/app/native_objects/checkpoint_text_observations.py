"""Capture and cold-verify a finite set of existing raw text observations.

Only verified TSV, metadata and recognition-input bytes are replayed. This
module never requests OCR, scans an author's evidence directory or imports an
old adoption decision. Its returned verification result is produced in code,
not accepted from a caller's JSON flag.
"""

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

import numpy as np

from .execution import file_sha
from .source_import import _decode, inspect_source
from .source_text_completion import BoundObservations
from .text_regions import raw_observation_provenance


SCHEMA = "native-checkpoint-text-observations-v1"
_FILES = ("tsv", "meta", "png")
_SUFFIXES = {"tsv": ".tsv", "meta": ".json", "png": ".png"}
_TSV_FIELDS = (
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
)


def _fail(reason):
    raise ValueError("CHECKPOINT_TEXT_OBSERVATIONS_" + reason)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("SHA256_INVALID")
    return value


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _roi(value):
    if (not isinstance(value, list) or len(value) != 4
            or not all(_integer(v) for v in value)
            or not (0 <= value[0] < value[2] and 0 <= value[1] < value[3])):
        _fail("ROI_INVALID")
    return value


def _inside(inner, outer):
    return (outer[0] <= inner[0] < inner[2] <= outer[2]
            and outer[1] <= inner[1] < inner[3] <= outer[3])


def _parameters(parameters):
    if not isinstance(parameters, dict):
        _fail("PARAMETERS_MISSING")
    roi = _roi(parameters.get("roi"))
    dpi = parameters.get("dpi")
    if (isinstance(dpi, bool) or not isinstance(dpi, (int, float))
            or not math.isfinite(dpi) or not float(dpi).is_integer() or dpi <= 0):
        _fail("DPI_INVALID")
    if parameters.get("orientation") != 0 or isinstance(parameters.get("orientation"), bool):
        _fail("ONLY_UNROTATED_SOURCE_SUPPORTED")
    return roi, int(dpi)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _json(content):
    try:
        return json.loads(content, object_pairs_hook=_pairs,
                          parse_constant=lambda _: _fail("JSON_NONFINITE"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CHECKPOINT_TEXT_OBSERVATIONS_JSON_INVALID") from exc


def _read(asset, *, root=None):
    if not isinstance(asset, dict) or set(asset) != {"path", "sha256"}:
        _fail("ASSET_REFERENCE_INVALID")
    name = asset["path"]
    if not isinstance(name, str) or not name or "\x00" in name:
        _fail("ASSET_PATH_INVALID")
    if root is None:
        path = Path(name)
        if not path.is_absolute():
            _fail("MANIFEST_PATH_NOT_ABSOLUTE")
        path = path.resolve()
    else:
        portable = PurePosixPath(name)
        if ("\\" in name or ":" in name or portable.is_absolute()
                or any(part in ("", ".", "..") for part in name.split("/"))):
            _fail("ASSET_PATH_NOT_CONTAINED_POSIX")
        root = Path(root).resolve()
        path = (root / Path(*portable.parts)).resolve()
        if root not in path.parents:
            _fail("ASSET_PATH_ESCAPES_MANIFEST")
    if not path.is_file():
        _fail("ASSET_MISSING:" + path.name)
    content = path.read_bytes()
    digest = _sha(asset["sha256"])
    if hashlib.sha256(content).hexdigest() != digest or file_sha(path) != digest:
        _fail("ASSET_HASH_MISMATCH:" + path.name)
    return path, content


def _source(source_path, source_sha256, parameters, gray):
    source_path = Path(source_path).resolve()
    if file_sha(source_path) != _sha(source_sha256):
        _fail("SOURCE_FILE_HASH_MISMATCH")
    info = inspect_source(source_path, dpi=parameters["dpi"],
                          page_number=parameters.get("page_number"),
                          frame_number=parameters.get("frame_number"))
    if gray is None:
        gray = _decode(source_path, info, parameters["dpi"])
    gray = np.asarray(gray)
    if gray.ndim != 2 or gray.dtype != np.uint8 or not gray.size:
        _fail("SOURCE_NOT_ORIGINAL_GRAYSCALE")
    gray = np.ascontiguousarray(gray)
    if [gray.shape[1], gray.shape[0]] != info["source_size_px"]:
        _fail("SOURCE_SIZE_MISMATCH")
    if file_sha(source_path) != source_sha256:
        _fail("SOURCE_FILE_CHANGED")
    return gray


def _validate_tsv(content, specification):
    """A malformed row cannot disappear through the permissive OCR parser."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")), delimiter="\t",
                                quoting=csv.QUOTE_NONE)
        if reader.fieldnames != list(_TSV_FIELDS):
            _fail("TSV_HEADER_INVALID")
        box = specification["crop_xyxy_px"]
        padding = specification["external_white_padding_px"]
        width, height = box[2] - box[0] + 2 * padding, box[3] - box[1] + 2 * padding
        for row in reader:
            if set(row) != set(_TSV_FIELDS) or any(value is None for value in row.values()):
                _fail("TSV_ROW_INVALID")
            level = int(row["level"])
            if level not in (1, 2, 3, 4, 5):
                _fail("TSV_LEVEL_INVALID")
            for key in ("page_num", "block_num", "par_num", "line_num", "word_num"):
                if int(row[key]) < 0:
                    _fail("TSV_INDEX_INVALID")
            x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            confidence = float(row["conf"])
            if (min(x, y, w, h) < 0 or x + w > width or y + h > height
                    or not math.isfinite(confidence) or not -1 <= confidence <= 100):
                _fail("TSV_GEOMETRY_OR_CONFIDENCE_INVALID")
            if level == 5 and row["text"].strip() and (w == 0 or h == 0):
                _fail("TSV_WORD_HAS_EMPTY_GEOMETRY")
    except (UnicodeError, csv.Error, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CHECKPOINT_TEXT_OBSERVATIONS_"):
            raise
        raise ValueError("CHECKPOINT_TEXT_OBSERVATIONS_TSV_INVALID") from exc


def _metadata(content, roi, dpi):
    meta = _json(content)
    if not isinstance(meta, dict) or meta.get("status") != "COMPLETED" or meta.get("return_code", 0) != 0:
        _fail("RAW_METADATA_NOT_COMPLETED")
    spec = meta.get("specification")
    required = {"crop_xyxy_px", "psm", "crop_array_sha256", "pixel_scale", "source_pixels_modified",
                "language", "recognition_dpi", "external_white_padding_px", "padding_replaces_source_pixels"}
    if not isinstance(spec, dict) or set(spec) != required:
        _fail("RAW_SPECIFICATION_FIELDS_INVALID")
    if not _inside(_roi(spec["crop_xyxy_px"]), roi):
        _fail("RAW_CROP_OUTSIDE_TASK_ROI")
    if (not _integer(spec["psm"]) or not 0 <= spec["psm"] <= 13
            or not _integer(spec["external_white_padding_px"]) or spec["external_white_padding_px"] < 0
            or spec["source_pixels_modified"] is not False or spec["padding_replaces_source_pixels"] is not False
            or spec["pixel_scale"] != [1, 1] or spec["language"] != "eng" or spec["recognition_dpi"] != dpi):
        _fail("RAW_CONFIGURATION_NOT_FROZEN")
    for value in (spec["crop_array_sha256"], meta.get("tsv_sha256"), meta.get("image_sha256")):
        _sha(value)
    command = meta.get("command")
    if not isinstance(command, list) or not all(isinstance(word, str) for word in command):
        _fail("ENGINE_COMMAND_INVALID")
    for flag, value in (("--psm", str(spec["psm"])), ("--dpi", str(dpi)), ("-l", "eng"), ("--oem", "1")):
        if command.count(flag) != 1 or command.index(flag) + 1 >= len(command) or command[command.index(flag) + 1] != value:
            _fail("ENGINE_COMMAND_CONFIG_MISMATCH:" + flag)
    if not str(meta.get("engine_version", "")).startswith("tesseract "):
        _fail("ENGINE_VERSION_MISSING")
    return meta


def verify_source_observations(asset, source_path, source_sha256, parameters, *, gray=None):
    """Return source-rechecked BoundObservations records; never run recognition."""
    roi, dpi = _parameters(parameters)
    manifest_path, content = _read(asset)
    manifest = _json(content)
    required = {"schema", "source_sha256", "source_array_sha256", "roi_xyxy_px", "dpi", "observations"}
    if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
            or set(manifest) != required):
        _fail("MANIFEST_FIELDS_INVALID")
    if (_sha(manifest["source_sha256"]) != _sha(source_sha256)
            or _roi(manifest["roi_xyxy_px"]) != roi or manifest["dpi"] != dpi):
        _fail("MANIFEST_SOURCE_BINDING_MISMATCH")
    gray = _source(source_path, source_sha256, parameters, gray)
    array_sha = hashlib.sha256(memoryview(gray).cast("B")).hexdigest()
    if array_sha != _sha(manifest["source_array_sha256"]):
        _fail("SOURCE_ARRAY_HASH_MISMATCH")
    if not _inside(roi, [0, 0, gray.shape[1], gray.shape[0]]):
        _fail("ROI_OUTSIDE_SOURCE")
    entries = manifest["observations"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        _fail("FINITE_OBSERVATIONS_REQUIRED")
    records, aliases, seen = [], [], {}
    # BoundObservations writes scope ledgers while ingesting. Use a temporary
    # verification workspace so verification never mutates captured inputs.
    with tempfile.TemporaryDirectory(prefix="i2cad-verify-text-") as temporary:
        temporary = Path(temporary)
        store = BoundObservations(gray, temporary / "evidence", source_sha256, dpi)
        for index, entry in enumerate(entries):
            if (not isinstance(entry, dict) or set(entry) != {"region_id", *_FILES}
                    or not isinstance(entry["region_id"], str) or not entry["region_id"]):
                _fail("OBSERVATION_ENTRY_INVALID")
            payloads = {kind: _read(entry[kind], root=manifest_path.parent) for kind in _FILES}
            if len({path for path, _ in payloads.values()}) != 3:
                _fail("RAW_ASSET_PATHS_NOT_DISTINCT")
            meta = _metadata(payloads["meta"][1], roi, dpi)
            if meta["tsv_sha256"] != entry["tsv"]["sha256"] or meta["image_sha256"] != entry["png"]["sha256"]:
                _fail("RAW_METADATA_PAYLOAD_HASH_MISMATCH")
            _validate_tsv(payloads["tsv"][1], meta["specification"])
            raw = temporary / f"observation-{index:04d}.tsv"
            for kind, (_, payload) in payloads.items():
                raw.with_suffix(_SUFFIXES[kind]).write_bytes(payload)
            context_key = store.ingest(raw)
            bound = store.rows[context_key]
            provenance = {
                **raw_observation_provenance(meta),
                "source_sha256": source_sha256,
                "metadata_sha256": entry["meta"]["sha256"],
                "original_source_bytes_rechecked": True,
            }
            if provenance.get("historical_model_byte_identity_proven") is None:
                provenance["historical_model_byte_identity_proven"] = False
            provenance["command_executed_for_this_request"] = False
            provenance["captured_raw_bytes_verified"] = True
            words = deepcopy(bound["words"])
            for word in words:
                word["observation_provenance"] = deepcopy(provenance)
            row = {"region_id": entry["region_id"], "key": bound["observation_key"],
                   "observation_key": bound["observation_key"], "context_key": context_key,
                   "words": words, "provenance": provenance, "specification": deepcopy(meta["specification"]),
                   "raw_tsv_sha256": entry["tsv"]["sha256"], "metadata_sha256": entry["meta"]["sha256"],
                   "input_png_sha256": entry["png"]["sha256"],
                   "files": {kind: {"path": str(payloads[kind][0]), "sha256": entry[kind]["sha256"]} for kind in _FILES}}
            key = (row["region_id"], row["key"])
            if key in seen:
                aliases.append({"region_id": row["region_id"], "key": row["key"], "files": row["files"], "extra_vote": False})
            else:
                seen[key] = row
                records.append(row)
            # Check the real assets again after the parser read their copies.
            for kind in _FILES:
                _read(entry[kind], root=manifest_path.parent)
        assert store.new_tesseract_calls == store.new_model_calls == 0
    _read(asset)
    if file_sha(source_path) != source_sha256:
        _fail("SOURCE_CHANGED_DURING_VERIFICATION")
    return {"validated": True, "source_sha256": source_sha256, "source_array_sha256": array_sha,
            "roi_xyxy_px": list(roi), "dpi": dpi, "manifest": deepcopy(asset), "observations": records,
            "aliases": aliases, "same_key_is_one_observation": True, "new_OCR_calls": 0,
            "old_adoption_loaded": False, "source_pixels_modified": False}


def _write_once(path, payload):
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def capture_source_observations(manifest_path, capture_directory, source_path, source_sha256, parameters):
    """Copy verified raw assets into a new, non-overwriting task directory."""
    manifest_path = Path(manifest_path).resolve()
    original = {"path": str(manifest_path), "sha256": file_sha(manifest_path)}
    verify_source_observations(original, source_path, source_sha256, parameters)
    _, content = _read(original)
    manifest = _json(content)
    capture = Path(capture_directory).resolve()
    capture.mkdir(parents=True, exist_ok=False)
    for old in manifest["observations"]:
        for kind in _FILES:
            _, payload = _read(old[kind], root=manifest_path.parent)
            destination = capture / Path(*PurePosixPath(old[kind]["path"]).parts)
            if destination == capture / "manifest.json":
                _fail("ASSET_CAPTURE_MANIFEST_COLLISION")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                _write_once(destination, payload)
            if file_sha(destination) != old[kind]["sha256"]:
                _fail("CAPTURE_COPY_HASH_MISMATCH")
    output = capture / "manifest.json"
    _write_once(output, content)
    result = {"path": str(output), "sha256": file_sha(output)}
    verify_source_observations(result, source_path, source_sha256, parameters)
    _read(original)
    return result


def _current_reference(root, base, name):
    """Resolve one declared current-job relative reference, never a search."""
    if (not isinstance(name, str) or not name or "\x00" in name or "\\" in name
            or ":" in name or PurePosixPath(name).is_absolute()):
        _fail("CURRENT_REFERENCE_NOT_RELATIVE_POSIX")
    path = (base / Path(*PurePosixPath(name).parts)).resolve()
    if path != root and root not in path.parents:
        _fail("CURRENT_REFERENCE_OUTSIDE_JOB")
    return path


def verify_current_job_observations(
    texts, evidence_root, source_path, source_sha256, parameters, *, text_artifact_path, gray=None,
):
    """Bind only declared current-job TSV triples for the ordinary pipeline.

    Missing observations produce a conservative, explicitly unverified result.
    A declared but missing, escaped or corrupt artifact is an integrity error.
    Existing producer-relative references may contain ``..`` only when their
    resolved files stay inside this job. The generated finite manifests use
    normalized POSIX paths and retain every original observation byte.
    """
    roi, dpi = _parameters(parameters)
    result = {"validated": False, "source_sha256": source_sha256,
              "source_array_sha256": texts.get("source_array_sha256") if isinstance(texts, dict) else None,
              "roi_xyxy_px": list(roi), "dpi": dpi, "observations": [], "aliases": [],
              "unverified_regions": [], "manifests": [], "same_key_is_one_observation": True,
              "new_OCR_calls": 0, "old_adoption_loaded": False, "source_pixels_modified": False,
              "adapter": "declared-current-job-raw-observations-v1"}
    regions = texts.get("regions") if isinstance(texts, dict) else None
    if not regions:
        result["reason"] = "NO_CURRENT_TEXT_REGIONS"
        return result
    if not isinstance(regions, list):
        _fail("CURRENT_REGIONS_INVALID")
    references, ids = [], set()
    for region in regions:
        rid = region.get("id") if isinstance(region, dict) else None
        if not isinstance(rid, str) or not rid or rid in ids:
            _fail("CURRENT_REGION_ID_INVALID")
        ids.add(rid)
        alternatives = region.get("completeness_evidence", {}).get("alternatives", [])
        if not isinstance(alternatives, list):
            _fail("CURRENT_ALTERNATIVES_INVALID")
        supplied = 0
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                _fail("CURRENT_ALTERNATIVE_INVALID")
            artifact = alternative.get("raw_artifact") or {}
            if not isinstance(artifact, dict):
                _fail("CURRENT_RAW_ARTIFACT_INVALID")
            name = artifact.get("path") or alternative.get("raw_tsv")
            if not name:
                continue
            references.append((rid, name, artifact))
            supplied += 1
        if not supplied:
            result["unverified_regions"].append({"region_id": rid, "reason": "NO_DECLARED_RAW_OBSERVATIONS"})
    if not references:
        result["reason"] = "NO_DECLARED_RAW_OBSERVATIONS"
        return result
    if len(references) > 4096:
        _fail("CURRENT_OBSERVATION_LIMIT_EXCEEDED")
    root = Path(evidence_root).resolve()
    artifact_path = Path(text_artifact_path)
    if not artifact_path.is_absolute():
        artifact_path = root / artifact_path
    artifact_path = artifact_path.resolve()
    if root not in artifact_path.parents or not artifact_path.is_file():
        _fail("CURRENT_TEXT_ARTIFACT_OUTSIDE_JOB_OR_MISSING")
    text_asset = {"path": str(artifact_path), "sha256": file_sha(artifact_path)}
    if _json(_read(text_asset)[1]) != texts:
        _fail("CURRENT_TEXT_ARTIFACT_CONTENT_MISMATCH")
    result["text_artifact"] = text_asset
    roots = texts.get("region_evidence_roots", {})
    if not isinstance(roots, dict):
        _fail("CURRENT_REGION_ROOTS_INVALID")
    # The initial text producer saves its public stage result at the job root
    # and raw passes under text/. Later producers declare region roots.
    initial = artifact_path.parent == root and not roots
    default_base = root / "text" if initial else artifact_path.parent
    entries = []
    for rid, name, declared in references:
        base = (_current_reference(root, artifact_path.parent, roots[rid])
                if rid in roots else default_base)
        path = _current_reference(root, base, name)
        files = {kind: path.with_suffix(_SUFFIXES[kind]) for kind in _FILES}
        entry = {"region_id": rid}
        for kind, current in files.items():
            current = current.resolve()
            if root not in current.parents or not current.is_file():
                _fail("CURRENT_DECLARED_RAW_MISSING_OR_ESCAPED:" + current.name)
            entry[kind] = {"path": current.relative_to(root).as_posix(), "sha256": file_sha(current)}
        if declared.get("sha256") and _sha(declared["sha256"]) != entry["tsv"]["sha256"]:
            _fail("CURRENT_DECLARED_RAW_HASH_MISMATCH")
        # Existing crops outside the selected task ROI are preserved as raw
        # diagnostics. They do not authorize the new ownership decision.
        meta = _json(_read(entry["meta"], root=root)[1])
        if (not isinstance(meta, dict) or meta.get("tsv_sha256") != entry["tsv"]["sha256"]
                or meta.get("image_sha256") != entry["png"]["sha256"]):
            _fail("CURRENT_RAW_METADATA_PAYLOAD_HASH_MISMATCH")
        specification = meta.get("specification")
        box = specification.get("crop_xyxy_px") if isinstance(specification, dict) else None
        if isinstance(box, list) and len(box) == 4 and all(_integer(v) for v in box) and not _inside(box, roi):
            result["unverified_regions"].append({"region_id": rid, "reason": "RAW_CROP_OUTSIDE_TASK_ROI", "raw_tsv": entry["tsv"]})
            continue
        entries.append(entry)
    if not entries:
        result["reason"] = "NO_IN_SCOPE_RAW_OBSERVATIONS"
        return result
    if gray is None:
        gray = _source(source_path, source_sha256, parameters, None)
    seen = {}
    for offset in range(0, len(entries), 64):
        manifest = {"schema": SCHEMA, "source_sha256": source_sha256,
                    "source_array_sha256": texts.get("source_array_sha256"),
                    "roi_xyxy_px": list(roi), "dpi": dpi, "observations": entries[offset:offset + 64]}
        content = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        digest = hashlib.sha256(content).hexdigest()
        path = root / ("text_graphic_raw_observations_" + digest + ".json")
        if path.exists():
            if path.read_bytes() != content:
                _fail("CURRENT_MANIFEST_CONFLICT")
        else:
            _write_once(path, content)
        asset = {"path": str(path), "sha256": digest}
        verified = verify_source_observations(asset, source_path, source_sha256, parameters, gray=gray)
        result["manifests"].append(asset)
        result["aliases"].extend(verified["aliases"])
        for row in verified["observations"]:
            key = (row["region_id"], row["key"])
            if key in seen:
                if seen[key]["raw_tsv_sha256"] != row["raw_tsv_sha256"]:
                    _fail("CURRENT_SAME_OBSERVATION_DIFFERENT_RAW_RESULT")
                result["aliases"].append({"region_id": row["region_id"], "key": row["key"], "files": row["files"], "extra_vote": False})
            else:
                seen[key] = row
                result["observations"].append(row)
        result["source_array_sha256"] = verified["source_array_sha256"]
    _read(text_asset)
    result["validated"] = bool(result["observations"])
    result["reason"] = "CURRENT_RAW_OBSERVATIONS_VERIFIED"
    return result
