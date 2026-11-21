"""Portable, content-addressed *raw* recognition observations.

Keys contain the actual grayscale samples, recognition configuration and exact
engine/model identities. Coordinates, filenames and prior adoption decisions
are deliberately absent. A hit supplies one prior observation, never another
agreement vote. Corruption is an error, not permission to silently run OCR again.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading

from .execution import current_context, file_sha, utc_now

SCHEMA = "native-raw-observation-cache-v1"
ENVIRONMENT_VARIABLE = "I2CAD_RAW_OBSERVATION_CACHE"
KINDS = frozenset({"tesseract-tsv", "historical-tesseract-tsv", "ppocr-ctc"})
_USAGE: list[dict] = []
_LOCK = threading.Lock()


def canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require_sha(value, label):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("RAW_OBSERVATION_IDENTITY_MISSING:" + label)
    return value


def pixels_identity(pixels):
    import numpy as np

    array = np.ascontiguousarray(pixels, dtype=np.uint8)
    if array.ndim != 2 or not array.size:
        raise ValueError("RAW_OBSERVATION_REQUIRES_NONEMPTY_GRAYSCALE_INPUT")
    return {
        "shape_px": list(array.shape),
        "dtype": "uint8",
        "sha256": hashlib.sha256(memoryview(array)).hexdigest(),
    }


def tesseract_identity(engine):
    """Measure the installed executable and the data path it actually reports."""
    location = re.search(r'in "([^"]+)"', engine.get("list_langs_output", ""))
    if location is None:
        raise ValueError("RAW_OBSERVATION_TESSDATA_LOCATION_UNPROVEN")
    executable = Path(engine["executable"])
    traineddata = Path(location.group(1)) / "eng.traineddata"
    return {
        "name": "tesseract",
        "version": engine["version"],
        "executable_sha256": file_sha(executable),
        "traineddata_sha256": file_sha(traineddata),
        "language": "eng",
        "oem": 1,
        "CPU_threads": 1,
    }


def tesseract_spec(crop, recognition_input, *, padding, psm, dpi, engine):
    identity = {
        key: engine[key]
        for key in (
            "name",
            "version",
            "executable_sha256",
            "traineddata_sha256",
            "language",
            "oem",
            "CPU_threads",
        )
    }
    _require_sha(identity["executable_sha256"], "tesseract executable")
    _require_sha(identity["traineddata_sha256"], "eng.traineddata")
    if (
        identity["name"] != "tesseract"
        or identity["language"] != "eng"
        or identity["oem"] != 1
        or identity["CPU_threads"] != 1
    ):
        raise ValueError("RAW_OBSERVATION_UNSUPPORTED_TESSERACT_CONFIGURATION")
    if (
        isinstance(padding, bool)
        or int(padding) != padding
        or padding < 0
        or isinstance(dpi, bool)
        or int(dpi) != dpi
        or dpi <= 0
        or isinstance(psm, bool)
        or int(psm) != psm
        or not 0 <= psm <= 13
    ):
        raise ValueError("RAW_OBSERVATION_INVALID_RECOGNITION_CONFIGURATION")
    return {
        "schema": SCHEMA,
        "kind": "tesseract-tsv",
        "crop": pixels_identity(crop),
        "recognition_input": pixels_identity(recognition_input),
        "external_white_padding_px": int(padding),
        "psm": int(psm),
        "recognition_dpi": int(dpi),
        "engine": identity,
        "source_pixels_modified": False,
        "pixel_scale": [1, 1],
    }


def model_spec(crop, tensor, identity):
    import numpy as np

    engine = {
        key: copy.deepcopy(identity[key])
        for key in (
            "name",
            "distribution",
            "model_sha256",
            "ONNXRuntime",
            "providers",
            "character_dictionary_sha256",
            "policy",
        )
    }
    _require_sha(engine["model_sha256"], "recognition model")
    _require_sha(engine["character_dictionary_sha256"], "character dictionary")
    sample = np.ascontiguousarray(tensor, dtype=np.float32)
    return {
        "schema": SCHEMA,
        "kind": "ppocr-ctc",
        "crop": pixels_identity(crop),
        "model_tensor": {
            "shape": list(sample.shape),
            "dtype": "float32",
            "sha256": hashlib.sha256(memoryview(sample)).hexdigest(),
        },
        "engine": engine,
        "source_pixels_modified": False,
    }


def historical_tesseract_spec(specification, source_sha256):
    """A separate namespace for explicitly supplied, limited historical proof.

    The original run did not capture executable/model digests. Its verified raw
    TSV may be reviewed again, but must never hit the exact-current-engine key.
    Whole-source identity is required in addition to the actual crop samples.
    """
    _require_sha(source_sha256, "historical source file")
    result = copy.deepcopy(specification)
    result["kind"] = "historical-tesseract-tsv"
    result["source_sha256"] = source_sha256
    result["engine"] = {
        key: specification["engine"][key]
        for key in ("name", "version", "language", "oem", "CPU_threads")
    }
    result["engine"].update(
        historical_executable_sha256=None,
        historical_model_sha256=None,
        historical_model_byte_identity_proven=False,
    )
    return result


def _immutable_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError(
                "RAW_OBSERVATION_IMMUTABLE_FILE_CONFLICT:" + str(path)
            ) from None


class ObservationCache:
    def __init__(self, root, *, create=False, allow_historical_tesseract=False):
        self.root = Path(root).expanduser().resolve()
        manifest = self.root / "manifest.json"
        if create and not manifest.exists():
            _immutable_bytes(
                manifest,
                canonical_bytes(
                    {
                        "schema": SCHEMA,
                        "created_utc": utc_now(),
                        "payloads": sorted(KINDS),
                        "raw_observations_only": True,
                        "adoption_geometry_or_review_imported": False,
                        "same_key_is_one_observation": True,
                        "historical_tesseract_namespace": bool(
                            allow_historical_tesseract
                        ),
                    }
                ),
            )
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            self.manifest.get("schema") != SCHEMA
            or self.manifest.get("raw_observations_only") is not True
            or self.manifest.get("adoption_geometry_or_review_imported") is not False
        ):
            raise ValueError("RAW_OBSERVATION_CACHE_MANIFEST_INVALID")
        self.manifest_sha256 = file_sha(manifest)

    def lookup_tesseract(self, specification):
        exact = self.lookup(specification, note=False)
        if exact is not None:
            _note("hit", specification, self, exact[1])
            return exact
        context = current_context()
        source_sha = (
            context.identity.get("source_sha256") if context is not None else None
        )
        if self.manifest.get("historical_tesseract_namespace") and source_sha:
            historical = historical_tesseract_spec(specification, source_sha)
            previous = self.lookup(historical, note=False)
            if previous is not None:
                _note("hit", historical, self, previous[1])
                return previous
        _note("miss", specification, self, None)
        return None

    def blob(self, payload):
        content = bytes(payload)
        sha = hashlib.sha256(content).hexdigest()
        _immutable_bytes(self.root / "blobs" / sha, content)
        return sha

    def read_blob(self, sha):
        _require_sha(sha, "raw payload")
        content = (self.root / "blobs" / sha).read_bytes()
        if hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("RAW_OBSERVATION_PAYLOAD_HASH_MISMATCH:" + sha)
        return content

    def snapshot(self):
        entries = {
            p.relative_to(self.root).as_posix(): file_sha(p)
            for p in sorted((self.root / "entries").glob("*/*.json"))
        }
        return {
            "enabled": True,
            "root": str(self.root),
            "manifest_sha256": self.manifest_sha256,
            "entries_sha256": digest(entries),
            "entry_count": len(entries),
            "raw_only": True,
            "prior_adoption_loaded": False,
        }

    def _path(self, specification):
        kind = specification.get("kind")
        if kind not in KINDS or specification.get("schema") != SCHEMA:
            raise ValueError("RAW_OBSERVATION_SPECIFICATION_UNSUPPORTED")
        return self.root / "entries" / kind / (digest(specification) + ".json")

    def lookup(self, specification, *, note=True):
        path = self._path(specification)
        if not path.exists():
            if note:
                _note("miss", specification, self, None)
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            record.get("schema") != SCHEMA
            or record.get("key") != digest(specification)
            or record.get("specification") != specification
        ):
            raise ValueError("RAW_OBSERVATION_RECORD_KEY_MISMATCH:" + str(path))
        payload = self.read_blob(record["payload_sha256"])
        if len(payload) != record["payload_bytes"]:
            raise ValueError("RAW_OBSERVATION_PAYLOAD_LENGTH_MISMATCH")
        for sha in record.get("producer", {}).get("evidence_blobs", {}).values():
            self.read_blob(sha)
        receipt = {
            "key": record["key"],
            "kind": specification["kind"],
            "cache_manifest_sha256": self.manifest_sha256,
            "record_sha256": file_sha(path),
            "payload_sha256": record["payload_sha256"],
            "producer": record["producer"],
            "same_observation_no_extra_vote": True,
        }
        if note:
            _note("hit", specification, self, receipt)
        return payload, receipt

    def put(self, specification, payload, producer):
        content = bytes(payload)
        existing = self.lookup(specification, note=False)
        if existing:
            equivalent = existing[0] == content
            if not equivalent and specification["kind"] == "ppocr-ctc":
                # The saved raw CTC outputs remain byte-for-byte preserved in
                # their producer proofs. Elapsed time is not a second reading.
                old, new = json.loads(existing[0]), json.loads(content)
                old.pop("wall_seconds", None)
                new.pop("wall_seconds", None)
                equivalent = old == new
            if not equivalent:
                raise ValueError("RAW_OBSERVATION_SAME_INPUT_DIFFERENT_RAW_RESULT")
            return existing[1]
        record = {
            "schema": SCHEMA,
            "key": digest(specification),
            "specification": specification,
            "payload_sha256": self.blob(content),
            "payload_bytes": len(content),
            "producer": copy.deepcopy(producer),
        }
        _immutable_bytes(self._path(specification), canonical_bytes(record))
        receipt = self.lookup(specification, note=False)[1]
        _note("stored", specification, self, receipt)
        return receipt


def _note(action, specification, cache, receipt):
    row = {
        "action": action,
        "key": digest(specification),
        "kind": specification["kind"],
        "root": str(cache.root),
        "cache_manifest_sha256": cache.manifest_sha256,
    }
    if receipt is not None:
        row["receipt"] = receipt
    with _LOCK:
        _USAGE.append(row)
    context = current_context()
    if context is not None:
        context.event("raw_observation_cache", observation=row)


def configured_cache():
    root = os.environ.get(ENVIRONMENT_VARIABLE)
    return ObservationCache(root) if root else None


def cache_binding(root, *, create=False):
    return ObservationCache(root, create=create).snapshot()


def verify_binding(binding, *, check_inventory=True):
    current = cache_binding(binding["root"])
    keys = ["manifest_sha256"]
    if check_inventory:
        keys += ["entries_sha256", "entry_count"]
    if any(current[key] != binding[key] for key in keys):
        raise ValueError("RAW_OBSERVATION_CACHE_CHANGED_AFTER_BINDING")
    return current


def producer_identity(module_file, *, engine=None, metadata=None):
    context = current_context()
    return {
        "origin": "actual_local_recognition",
        "module": Path(module_file).name,
        "module_sha256": file_sha(module_file),
        "job": copy.deepcopy(context.identity) if context is not None else None,
        "engine": copy.deepcopy(engine),
        "metadata": copy.deepcopy(metadata),
        "raw_text_rewritten": False,
        "old_adoption_loaded": False,
    }


def write_usage_report(path, binding):
    """Include the immutable producer proofs in the published evidence tree."""
    from .execution import atomic_json

    path = Path(path)
    with _LOCK:
        rows = copy.deepcopy(_USAGE)
    counts = {
        kind: {
            action: sum(row["kind"] == kind and row["action"] == action for row in rows)
            for action in ("hit", "miss", "stored")
        }
        for kind in sorted(KINDS)
    }
    copied = {}
    for row in rows:
        receipt = row.get("receipt", {})
        cache = ObservationCache(row["root"])
        for sha in receipt.get("producer", {}).get("evidence_blobs", {}).values():
            if sha not in copied:
                content = cache.read_blob(sha)
                relative = Path("raw_observation_proofs") / sha
                _immutable_bytes(path.parent / relative, content)
                copied[sha] = relative.as_posix()
    report = {
        "schema": "native-raw-observation-usage-v1",
        "startup_binding": binding,
        "counts": counts,
        "observations": rows,
        "copied_producer_proofs": copied,
        "hits_are_not_new_or_independent_recognition": True,
        "historical_measurements_are_not_current_execution_time": True,
        "prior_adoption_or_geometry_loaded": False,
    }
    atomic_json(path, report)
    return {"path": str(path), "sha256": file_sha(path), "counts": counts}
