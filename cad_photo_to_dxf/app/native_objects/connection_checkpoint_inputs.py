"""Capture bounded connection inputs without OCR or author-directory fallbacks.

The old ledger describes entities to preserve, not an adoption list for newly
discovered paths.  Window identifiers and optional reporting notes are opaque
labels.  All algorithm decisions must still come from the captured source.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import uuid

import ezdxf
import numpy as np

from .contracts import save_json, validate_text_regions
from .execution import file_sha
from .source_import import _decode, inspect_source


SCHEMA = "native-connection-checkpoint-v1"
CAPTURE_SCHEMA = "native-connection-checkpoint-capture-v1"
_ASSETS = ("baseline_dxf", "baseline_ownership", "text_observations")
_OPTIONAL_ASSETS = ("baseline_evidence", "source_observations")
_APPID = "I2CAD_NATIVE_V2"
_KINDS = {
    "LINE": {"LINE"},
    "ARC": {"ARC"},
    "TEXT": {"TEXT"},
    "MTEXT": {"MTEXT"},
    "CONNECTION_PATH": {"LWPOLYLINE", "LINE", "ARC"},
    "ROOM_LABEL": {"INSERT"},
    "WALL_SEGMENT": {"INSERT"},
    "DOOR": {"INSERT"},
}


def _fail(reason):
    raise ValueError("CONNECTION_CHECKPOINT_" + reason)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("SHA256_INVALID")
    return value


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _roi(value, label):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or not all(_integer(v) for v in value)
        or not (0 <= value[0] < value[2] and 0 <= value[1] < value[3])
    ):
        _fail(label + "_INVALID")
    return list(value)


def _inside(inner, outer):
    return (
        outer[0] <= inner[0] < inner[2] <= outer[2]
        and outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def _union_area(rectangles):
    """Exact union area for at most eight source-pixel rectangles."""
    edges = sorted({r[i] for r in rectangles for i in (0, 2)})
    area = 0
    for left, right in zip(edges, edges[1:]):
        spans = sorted((r[1], r[3]) for r in rectangles if r[0] < right and r[2] > left)
        length, end = 0, -1
        for start, stop in spans:
            length += max(0, stop - max(start, end))
            end = max(end, stop)
        area += (right - left) * length
    return area


def _under(path, directory):
    path, directory = Path(path).resolve(), Path(directory).resolve()
    if path == directory or directory not in path.parents:
        _fail("PATH_OUTSIDE_CAPTURE")
    return path


def _asset(value, *, base=None, directory=None):
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        _fail("ASSET_REFERENCE_INVALID")
    name = value["path"]
    if not isinstance(name, str) or not name or "\x00" in name:
        _fail("ASSET_PATH_INVALID")
    path = Path(name).expanduser()
    if not path.is_absolute():
        if base is None:
            _fail("CAPTURED_PATH_NOT_ABSOLUTE")
        path = Path(base) / path
    path = path.resolve()
    if directory is not None:
        path = _under(path, directory)
    if not path.is_file():
        _fail("ASSET_MISSING:" + path.name)
    digest = _sha(value["sha256"])
    if file_sha(path) != digest:
        _fail("ASSET_HASH_MISMATCH:" + path.name)
    return {"path": str(path), "sha256": digest}


def _read_json(asset):
    data = Path(asset["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        _fail("ASSET_CHANGED_DURING_READ")
    try:
        return json.loads(data, parse_constant=lambda _: _fail("JSON_NONFINITE"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CONNECTION_CHECKPOINT_JSON_INVALID") from exc


def _parameters(parameters):
    if not isinstance(parameters, dict):
        _fail("PARAMETERS_MISSING")
    roi = _roi(parameters.get("roi"), "PARAMETER_ROI")
    dpi = parameters.get("dpi")
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not math.isfinite(dpi) or dpi <= 0:
        _fail("DPI_INVALID")
    if parameters.get("orientation") != 0 or isinstance(parameters.get("orientation"), bool):
        _fail("ONLY_UNROTATED_SOURCE_FRAME_SUPPORTED")
    return roi, dpi


def _manifest(manifest, source_sha256, parameters):
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        _fail("MANIFEST_SCHEMA_INVALID")
    expected_keys = {"schema", "source_sha256", "roi_xyxy_px", "dpi", "windows", *_ASSETS}
    if set(manifest) - expected_keys - {"reporting", *_OPTIONAL_ASSETS} or expected_keys - set(manifest):
        _fail("MANIFEST_FIELDS_INVALID")
    roi, dpi = _parameters(parameters)
    if _sha(manifest["source_sha256"]) != _sha(source_sha256):
        _fail("SOURCE_HASH_MISMATCH")
    if _roi(manifest["roi_xyxy_px"], "MANIFEST_ROI") != roi or manifest["dpi"] != dpi:
        _fail("SOURCE_PARAMETERS_MISMATCH")
    windows = manifest["windows"]
    if not isinstance(windows, list) or not 1 <= len(windows) <= 8:
        _fail("BOUNDED_WINDOWS_REQUIRED")
    labels, rectangles = set(), []
    for row in windows:
        if not isinstance(row, dict) or set(row) != {"id", "target_roi", "context_roi"}:
            _fail("WINDOW_FIELDS_INVALID")
        label = row["id"]
        if not isinstance(label, str) or not label or label in labels:
            _fail("WINDOW_ID_MISSING_OR_DUPLICATE")
        labels.add(label)
        target, context = _roi(row["target_roi"], "TARGET_ROI"), _roi(row["context_roi"], "CONTEXT_ROI")
        if not _inside(target, context) or not _inside(context, roi):
            _fail("WINDOW_OUTSIDE_SOURCE_SCOPE")
        rectangles.append(context)
    if _union_area(rectangles) >= (roi[2] - roi[0]) * (roi[3] - roi[1]):
        _fail("FULL_REGION_WINDOWS_FORBIDDEN")
    return roi, dpi


def _source(path, source_sha256, parameters):
    if file_sha(path) != source_sha256:
        _fail("CAPTURED_SOURCE_HASH_MISMATCH")
    info = inspect_source(
        path,
        dpi=parameters["dpi"],
        page_number=parameters.get("page_number"),
        frame_number=parameters.get("frame_number"),
    )
    gray = np.ascontiguousarray(_decode(path, info, parameters["dpi"]))
    if [gray.shape[1], gray.shape[0]] != info["source_size_px"]:
        _fail("DECODED_SOURCE_SIZE_MISMATCH")
    if file_sha(path) != source_sha256:
        _fail("CAPTURED_SOURCE_CHANGED")
    return {
        "path": str(Path(path).resolve()),
        "sha256": source_sha256,
        "source_array_sha256": hashlib.sha256(memoryview(gray).cast("B")).hexdigest(),
        "source_size_px": info["source_size_px"],
        "page_number_1based": info.get("page_number_1based"),
        "frame_number_1based": info.get("frame_number_1based"),
    }


def _rows_by_id(rows, label):
    if not isinstance(rows, list):
        _fail(label + "_LIST_MISSING")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in result:
            _fail(label + "_ID_MISSING_OR_DUPLICATE")
        if row.get("kind") not in _KINDS:
            _fail(label + "_KIND_UNSUPPORTED")
        result[row["id"]] = row
    return result


def _baseline(ownership, dxf_asset, source_sha256, roi, dpi):
    if (
        not isinstance(ownership, dict)
        or ownership.get("source_sha256") != source_sha256
        or ownership.get("dxf_sha256") != dxf_asset["sha256"]
        or ownership.get("roi_xyxy_px") != roi
        or ownership.get("dpi") != dpi
        or ownership.get("unit") != "paper_mm"
    ):
        _fail("BASELINE_SOURCE_BINDING_MISMATCH")
    objects = _rows_by_id(ownership.get("objects"), "BASELINE_OBJECT")
    written = _rows_by_id(ownership.get("written"), "BASELINE_WRITTEN")
    if objects.keys() != written.keys():
        _fail("BASELINE_WRITTEN_IDS_MISMATCH")
    doc = ezdxf.readfile(dxf_asset["path"])
    if file_sha(dxf_asset["path"]) != dxf_asset["sha256"]:
        _fail("BASELINE_DXF_CHANGED_DURING_READ")
    if doc.units != 4:
        _fail("BASELINE_NOT_PAPER_MM")
    actual = {}
    for entity in doc.modelspace():
        try:
            tags = entity.get_xdata(_APPID)
            if len(tags) != 1 or tags[0].code != 1000:
                _fail("BASELINE_XDATA_INVALID")
            identity = json.loads(tags[0].value)
        except (ezdxf.DXFError, ValueError, TypeError) as exc:
            raise ValueError("CONNECTION_CHECKPOINT_BASELINE_XDATA_INVALID") from exc
        if not isinstance(identity, dict) or set(identity) != {"id", "kind"}:
            _fail("BASELINE_XDATA_INVALID")
        if identity["kind"] == "REVIEW" and entity.dxf.layer == "REVIEW":
            continue
        oid = identity["id"]
        if not isinstance(oid, str) or oid not in objects or oid in actual:
            _fail("BASELINE_DXF_IDS_MISMATCH")
        old, record = objects[oid], written[oid]
        if (
            identity["kind"] != old["kind"]
            or record["kind"] != old["kind"]
            or entity.dxftype() not in _KINDS[old["kind"]]
            or record.get("type") != entity.dxftype()
            or record.get("handle") != entity.dxf.handle
            or old.get("layer") != entity.dxf.layer
            or not isinstance(old.get("geometry"), dict)
            or not old["geometry"]
            or not isinstance(old.get("source_evidence"), dict)
            or not old["source_evidence"]
        ):
            _fail("BASELINE_DXF_OBJECT_MISMATCH:" + oid)
        if entity.dxftype() == "INSERT":
            block = doc.blocks.get(entity.dxf.name)
            if block is None or [member.dxftype() for member in block] != record.get("block_members"):
                _fail("BASELINE_BLOCK_MEMBERS_MISMATCH:" + oid)
        actual[oid] = identity["kind"]
    if actual.keys() != objects.keys() or Counter(actual.values()) != Counter(row["kind"] for row in objects.values()):
        _fail("BASELINE_DXF_COUNTS_MISMATCH")


def _payloads(manifest, assets, source, parameters):
    roi, dpi = _manifest(manifest, source["sha256"], parameters)
    ownership, texts = _read_json(assets["baseline_ownership"]), _read_json(assets["text_observations"])
    _baseline(ownership, assets["baseline_dxf"], source["sha256"], roi, dpi)
    size = source["source_size_px"]
    if not _inside(roi, [0, 0, *size]):
        _fail("PARENT_ROI_OUTSIDE_SOURCE")
    if not isinstance(texts, dict) or texts.get("schema") != "native_text_regions_v2":
        _fail("TEXT_SCHEMA_INVALID")
    if _sha(texts.get("source_array_sha256")) != source["source_array_sha256"]:
        _fail("TEXT_SOURCE_ARRAY_MISMATCH")
    validate_text_regions(texts, (size[1], size[0]), roi)
    if "baseline_evidence" in assets:
        from .checkpoint_baseline import verify_baseline_evidence

        verified = verify_baseline_evidence(
            assets["baseline_evidence"], assets["baseline_dxf"]["path"], ownership,
            source["path"], source["sha256"], parameters,
        )
        if verified["manifest"]["baseline_ownership_sha256"] != assets["baseline_ownership"]["sha256"]:
            _fail("BASELINE_EVIDENCE_LEDGER_HASH_MISMATCH")
    if "source_observations" in assets:
        from .checkpoint_text_observations import verify_source_observations

        verify_source_observations(assets["source_observations"], source["path"],
                                   source["sha256"], parameters)
    return ownership, texts


def _copy_verified(asset, destination):
    with Path(asset["path"]).open("rb") as incoming, Path(destination).open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if file_sha(asset["path"]) != asset["sha256"] or file_sha(destination) != asset["sha256"]:
        _fail("INPUT_CHANGED_DURING_CAPTURE")
    return {"path": str(Path(destination).resolve()), "sha256": asset["sha256"]}


def capture_checkpoint(manifest_path, job_directory, source_sha256, parameters):
    """Validate and freeze one request under a fresh task-local directory."""
    job_directory = Path(job_directory).resolve()
    inputs = _under(job_directory / "inputs", job_directory)
    parameters = deepcopy(parameters)
    _parameters(parameters)
    path = Path(manifest_path).expanduser().resolve()
    original = _asset({"path": str(path), "sha256": file_sha(path)})
    manifest = _read_json(original)
    _manifest(manifest, source_sha256, parameters)
    asset_names = (*_ASSETS, *(name for name in _OPTIONAL_ASSETS if name in manifest))
    assets = {name: _asset(manifest[name], base=path.parent) for name in asset_names}
    candidates = [p for p in inputs.glob("source.*") if p.is_file() and p.suffix != ".tmp"]
    if len(candidates) != 1:
        _fail("ONE_CAPTURED_SOURCE_REQUIRED")
    source = _source(_under(candidates[0], inputs), source_sha256, parameters)
    _payloads(manifest, assets, source, parameters)
    base = _under(inputs / "connection_checkpoint", inputs)
    base.mkdir(exist_ok=True)
    capture = base / ("capture-" + uuid.uuid4().hex)
    capture.mkdir()
    originals = _copy_verified(original, capture / "request.original.json")
    copied = {
        name: _copy_verified(asset, capture / (name + (".dxf" if name == "baseline_dxf" else ".json")))
        for name, asset in assets.items() if name in _ASSETS
    }
    if "baseline_evidence" in assets:
        from .checkpoint_baseline import capture_baseline_evidence

        copied["baseline_evidence"] = capture_baseline_evidence(
            assets["baseline_evidence"], capture / "baseline_evidence"
        )
    if "source_observations" in assets:
        from .checkpoint_text_observations import capture_source_observations

        copied["source_observations"] = capture_source_observations(
            assets["source_observations"]["path"], capture / "source_observations",
            source["path"], source["sha256"], parameters,
        )
    rebound = deepcopy(manifest)
    rebound.update(copied)
    rebound_path = capture / "manifest.json"
    save_json(rebound_path, rebound)
    binding = {
        "schema": CAPTURE_SCHEMA,
        "job_directory": str(job_directory),
        "capture_directory": str(capture),
        "source_sha256": source_sha256,
        "source_array_sha256": source["source_array_sha256"],
        "source": source,
        "parameters": parameters,
        "manifest": {"path": str(rebound_path), "sha256": file_sha(rebound_path)},
        "original_manifest": originals,
        **copied,
    }
    verify_captured_checkpoint(binding, job_directory, source_sha256, parameters)
    return binding


def _verified_contents(binding, job_directory, source_sha256, parameters):
    if not isinstance(binding, dict) or binding.get("schema") != CAPTURE_SCHEMA:
        _fail("CAPTURE_BINDING_INVALID")
    job_directory = Path(job_directory).resolve()
    if binding.get("job_directory") != str(job_directory) or binding.get("source_sha256") != source_sha256 or binding.get("parameters") != parameters:
        _fail("CAPTURE_PARAMETERS_MISMATCH")
    _parameters(parameters)
    inputs = _under(job_directory / "inputs", job_directory)
    base = _under(inputs / "connection_checkpoint", inputs)
    capture = _under(binding.get("capture_directory", ""), base)
    if capture.parent != base:
        _fail("CAPTURE_DIRECTORY_INVALID")
    assets = {name: _asset(binding.get(name), directory=capture) for name in ("manifest", "original_manifest")}
    original = _read_json(assets["original_manifest"])
    _manifest(original, source_sha256, parameters)
    asset_names = (*_ASSETS, *(name for name in _OPTIONAL_ASSETS if name in original))
    if {name for name in _OPTIONAL_ASSETS if name in binding} != {name for name in _OPTIONAL_ASSETS if name in original}:
        _fail("OPTIONAL_CAPTURE_ASSET_SET_MISMATCH")
    assets.update({name: _asset(binding.get(name), directory=capture) for name in asset_names})
    if len({row["path"] for row in assets.values()}) != len(assets):
        _fail("CAPTURE_ASSET_PATHS_NOT_DISTINCT")
    manifest = _read_json(assets["manifest"])
    rebound = deepcopy(original)
    for name in asset_names:
        if original[name].get("sha256") != assets[name]["sha256"]:
            _fail("ORIGINAL_CAPTURE_HASH_MISMATCH")
        rebound[name] = assets[name]
    if rebound != manifest:
        _fail("CAPTURED_MANIFEST_REBINDING_MISMATCH")
    source = binding.get("source")
    if not isinstance(source, dict) or source.get("sha256") != source_sha256:
        _fail("CAPTURE_SOURCE_BINDING_MISSING")
    actual_source = _source(_under(source.get("path", ""), inputs), source_sha256, parameters)
    if source != actual_source or binding.get("source_array_sha256") != actual_source["source_array_sha256"]:
        _fail("CAPTURE_SOURCE_BINDING_MISMATCH")
    ownership, texts = _payloads(manifest, assets, actual_source, parameters)
    return manifest, ownership, texts, Path(assets["baseline_dxf"]["path"])


def verify_captured_checkpoint(binding, job_directory, source_sha256, parameters):
    """Fail closed if any captured input, source frame or parameter changed."""
    _verified_contents(binding, job_directory, source_sha256, parameters)
    return binding


def load_captured_checkpoint(binding):
    """Read only the immutable task copy; never resolve historical paths."""
    if not isinstance(binding, dict):
        _fail("CAPTURE_BINDING_INVALID")
    return _verified_contents(
        binding,
        binding.get("job_directory", ""),
        binding.get("source_sha256"),
        binding.get("parameters"),
    )
