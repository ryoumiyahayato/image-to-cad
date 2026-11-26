"""Native-resolution text regions, local OCR, and explicit completeness evidence.

This module never draws CAD, removes source rules, changes a recognised string,
or knows drawing-specific answers or coordinates.  It may use an explicitly
supplied, source-verified OCR cache for discovery; local OCR is still executed.
Rectangular label interiors are discovered from the source, not a room list.

All boxes and masks are in full source pixels (x right, y down), half-open.
An uncertain text region is useful protection evidence, not an adopted TEXT.
The compact-glyph mask is deliberately not an instruction to erase a wall.
"""

from __future__ import annotations

from .performance import profiled
import csv
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
from .execution import run_subprocess, check_cancel, NativeResourceLimit
import time

try:
    import resource
except ImportError:  # Windows has no stdlib resource module.
    resource = None


POLICY = {
    "version": "native-text-regions-v2-local-20261119",
    "source_threshold": 192,
    "local_psms": [7, 13],
    "enclosed_label_psms": [7, 6],
    "enclosed_label_external_padding_px": [8, 12],
    "discovery_psm_without_cache": 11,
    "discovery_tile_size": 1400,
    "discovery_overlap": 240,
    "discovery_context": 80,
    "maximum_local_regions": 256,
    "local_timeout_seconds": 20,
    "total_local_wall_budget_seconds": 300,
    "minimum_word_confidence": 85.0,
    "minimum_numeric_word_confidence": 95.0,
    "minimum_glyph_height": 8,
    "maximum_glyph_height": 70,
    "frame_maximum_width": 320,
    "frame_maximum_height": 130,
    "frame_minimum_edge_support": 0.72,
    "automatic_formal_adoption": False,
    "source_policy": "Original native pixels, no source erasure, rescaling, or guessed characters",
    "mask_policy": "Compact source components only; candidate boxes and connected rule ink are not erasure masks",
    "group_policy": "Geometric line/paragraph proximity is a grouping hypothesis, not engineering semantics",
}


def _dump(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _usage(children=False):
    if resource is None:
        return (None if children else time.process_time()), None
    sample = resource.getrusage(
        resource.RUSAGE_CHILDREN if children else resource.RUSAGE_SELF
    )
    return sample.ru_utime + sample.ru_stime, sample.ru_maxrss


@lru_cache(maxsize=4)
def _resolve_tesseract(configured_path, tessdata_prefix=None):
    binary = configured_path or shutil.which("tesseract")
    if not binary or not Path(binary).is_file():
        raise RuntimeError(
            "Tesseract is unavailable; set I2CAD_TESSERACT or install an executable on PATH"
        )
    languages = run_subprocess(
        [binary, "--list-langs"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    names = [
        line.strip()
        for line in (languages.stdout + "\n" + languages.stderr).splitlines()
    ]
    if languages.returncode != 0 or "eng" not in names:
        raise RuntimeError(
            "The selected Tesseract engine does not report an installed eng model"
        )
    version = run_subprocess(
        [binary, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    first_line = (version.stdout or version.stderr).splitlines()
    return {
        "executable": str(Path(binary).resolve()),
        "language": "eng",
        "version": first_line[0] if first_line else "UNKNOWN",
        "list_langs_output": languages.stdout + languages.stderr,
        "model_source": "selected engine installed language data; no fixed tessdata path",
    }


@profiled("text_regions.source_array_sha256")
def source_array_sha256(image):
    """Public cache fingerprint: SHA256 of contiguous uint8 grey sample bytes."""
    import numpy as np

    # Keep every source integrity check, but avoid a full-page .tobytes copy.
    # This reads the identical C-order uint8 bytes; it never caches the hash.
    contiguous = np.ascontiguousarray(image, dtype=np.uint8)
    return hashlib.sha256(memoryview(contiguous)).hexdigest()


def _box_union(boxes):
    return [
        int(min(b[0] for b in boxes)),
        int(min(b[1] for b in boxes)),
        int(max(b[2] for b in boxes)),
        int(max(b[3] for b in boxes)),
    ]


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _overlap(a, b):
    return _intersection(a, b) / max(1, min(_area(a), _area(b)))


def _inside(a, b):
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def _clip(box, shape):
    h, w = shape
    return [
        max(0, min(w, int(box[0]))),
        max(0, min(h, int(box[1]))),
        max(0, min(w, int(box[2]))),
        max(0, min(h, int(box[3]))),
    ]


def _starts(lo, hi, size, overlap):
    values = [lo]
    while values[-1] + size < hi:
        nxt = min(values[-1] + size - overlap, hi - size)
        if nxt <= values[-1]:
            break
        values.append(nxt)
    return values


def _rle(mask, origin):
    import numpy as np

    ox, oy = origin
    runs = []
    for y in np.flatnonzero(mask.any(axis=1)):
        row = np.pad(mask[y].astype(np.int8), (1, 1))
        changes = np.diff(row)
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        runs.extend(
            [[int(y + oy), int(a + ox), int(b + ox)] for a, b in zip(starts, ends)]
        )
    return runs


def _parse_tsv(raw, crop_box, context_id, psm):
    result = []
    for row in csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        try:
            x, y, w, h = [int(row[k]) for k in ("left", "top", "width", "height")]
            conf = float(row["conf"])
        except (KeyError, ValueError):
            continue
        if w <= 0 or h <= 0 or not math.isfinite(conf):
            continue
        text = row["text"].strip()
        result.append(
            {
                "text": text,
                "confidence": conf,
                "bbox_xyxy_px": [
                    crop_box[0] + x,
                    crop_box[1] + y,
                    crop_box[0] + x + w,
                    crop_box[1] + y + h,
                ],
                "context_id": context_id,
                "psm": int(psm),
                "line_key": ":".join(
                    [
                        context_id,
                        row.get("block_num", ""),
                        row.get("par_num", ""),
                        row.get("line_num", ""),
                    ]
                ),
                "word_num": int(row.get("word_num") or 0),
                "raw_text_unchanged": True,
            }
        )
    return result


def _observation_context_key(specification, engine_identity=None):
    """Identify an actual recognition input/configuration, never its display ID.

    Source coordinates and unpadded crop bytes are part of the identity.  The
    same OCR renamed by another producer cannot provide another agreement vote.
    A non-Tesseract producer must provide its model/configuration identity.
    """
    keys = (
        "crop_xyxy_px",
        "crop_array_sha256",
        "psm",
        "pixel_scale",
        "source_pixels_modified",
        "language",
        "recognition_dpi",
        "external_white_padding_px",
        "padding_replaces_source_pixels",
    )
    canonical = {key: specification.get(key) for key in keys}
    canonical["engine_identity"] = engine_identity or {
        "engine": "tesseract",
        "oem": 1,
        "language": "eng",
    }
    return hashlib.sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def raw_observation_key(meta):
    """One actual recognition input supplies one vote, whatever its filename."""
    receipt = meta.get("raw_observation_cache")
    return (
        receipt["key"] if receipt else _observation_context_key(meta["specification"])
    )


def raw_observation_provenance(meta):
    engine = meta.get("engine_identity") or {
        "engine": "tesseract",
        "oem": 1,
        "language": "eng",
    }
    receipt = meta.get("raw_observation_cache")
    proven = engine.get("historical_model_byte_identity_proven")
    if (
        proven is None
        and engine.get("executable_sha256")
        and engine.get("traineddata_sha256")
    ):
        proven = True
    return {
        "specification": dict(meta["specification"]),
        "engine_identity": engine,
        "raw_tsv_sha256": meta.get("tsv_sha256"),
        "recognition_input_sha256": meta.get("image_sha256"),
        "engine_command": meta.get("command"),
        "engine_version": meta.get("engine_version"),
        "raw_text_unchanged": True,
        "raw_observation_cache": receipt,
        "raw_observation_kind": receipt.get("kind") if receipt else None,
        "raw_observation_key": raw_observation_key(meta),
        "command_executed_for_this_request": meta.get(
            "command_executed_for_this_request"
        ),
        "historical_model_byte_identity_proven": proven,
        "consumer_installed_engine_identity": meta.get(
            "consumer_installed_engine_identity"
        ),
    }


def _bind_ocr_words(words, specification, meta):
    key = raw_observation_key(meta)
    for word in words:
        word["observation_key"] = key
        word["observation_provenance"] = raw_observation_provenance(meta)
    return words


def _check_reused_tsv_encoding(raw, metadata):
    """Do not silently reuse earlier Windows locale-decoded non-ASCII OCR.

    The preserved text may already be mojibake even though its saved container
    is valid UTF-8. Without the producer's decoding receipt it cannot be repaired
    from the saved string. ASCII and prior Linux observations keep their normal
    source/engine/hash checks; this guard does not rewrite any raw observation.
    """
    command = metadata.get("command") or []
    executable = str(command[0]) if isinstance(command, list) and command else ""
    windows = executable.lower().endswith(".exe") or bool(
        PureWindowsPath(executable).drive
    )
    if (
        windows
        and not raw.isascii()
        and metadata.get("recognition_output_encoding") != "utf-8"
    ):
        raise ValueError("LEGACY_WINDOWS_NONASCII_OCR_ENCODING_UNVERIFIED")


@profiled("text_regions._ocr")
def _ocr(image, box, psm, directory, name, progress_callback, padding_px=0, *, dpi=200,
         record_engine_identity=False):
    from PIL import Image
    import numpy as np
    from .observation_cache import (
        configured_cache,
        producer_identity,
        tesseract_identity,
        tesseract_spec,
    )

    check_cancel("OCR:" + str(name))
    if isinstance(dpi, bool) or not float(dpi).is_integer() or dpi <= 0:
        raise ValueError("OCR requires the explicit positive integer task DPI")
    directory.mkdir(parents=True, exist_ok=True)
    image_path = directory / f"{name}.png"
    tsv_path = directory / f"{name}.tsv"
    meta_path = directory / f"{name}.json"
    x0, y0, x1, y1 = box
    crop = image[y0:y1, x0:x1]
    crop_hash = source_array_sha256(crop)
    specification = {
        "crop_xyxy_px": list(box),
        "psm": psm,
        "crop_array_sha256": crop_hash,
        "pixel_scale": [1, 1],
        "source_pixels_modified": False,
        "language": "eng",
        "recognition_dpi": int(dpi),
        "external_white_padding_px": int(padding_px),
        "padding_replaces_source_pixels": False,
    }
    origin_box = [
        box[0] - padding_px,
        box[1] - padding_px,
        box[2] + padding_px,
        box[3] + padding_px,
    ]
    if meta_path.exists() and tsv_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("specification") != specification:
            raise ValueError(
                f"OCR checkpoint source/specification mismatch: {meta_path}"
            )
        if meta.get("status") == "COMPLETED" and meta.get("tsv_sha256") == _sha(
            tsv_path
        ):
            raw = tsv_path.read_text(encoding="utf-8")
            _check_reused_tsv_encoding(raw, meta)
            reused = {
                **meta,
                "reused_checkpoint": True,
                "command_executed_for_this_request": False,
            }
            return _bind_ocr_words(
                _parse_tsv(raw, origin_box, name, psm),
                specification,
                reused,
            ), reused
        raise RuntimeError(
            f"Prior failed OCR requires a new evidence directory: {meta_path}"
        )
    recognition_input = (
        np.pad(crop, int(padding_px), mode="constant", constant_values=255)
        if padding_px
        else crop
    )
    Image.fromarray(recognition_input).save(image_path)
    engine = _resolve_tesseract(
        os.environ.get("I2CAD_TESSERACT", ""), os.environ.get("TESSDATA_PREFIX")
    )
    command = [
        engine["executable"],
        str(image_path),
        "stdout",
        "-l",
        "eng",
        "--oem",
        "1",
        "--psm",
        str(psm),
        "--dpi",
        str(int(dpi)),
        "tsv",
    ]
    cache_lookup_started = time.perf_counter()
    cache = configured_cache()
    # Some fixed multi-view contracts require exact byte identity even in a
    # normal run without a raw cache. Measure before this new call; never
    # attribute today's installed bytes to an older identity-free checkpoint.
    engine_bytes = tesseract_identity(engine) if cache is not None or record_engine_identity else None
    cache_spec = (
        tesseract_spec(
            crop,
            recognition_input,
            padding=padding_px,
            psm=psm,
            dpi=dpi,
            engine=engine_bytes,
        )
        if cache is not None
        else None
    )
    cached = cache.lookup_tesseract(cache_spec) if cache is not None else None
    if cached is not None:
        payload, receipt = cached
        raw = payload.decode("utf-8")
        producer_metadata = receipt["producer"].get("metadata") or {}
        _check_reused_tsv_encoding(raw, producer_metadata)
        tsv_path.write_bytes(payload)
        meta = {
            "status": "COMPLETED",
            "specification": specification,
            "command": producer_metadata.get("command", command),
            "command_executed_for_this_request": False,
            "engine_version": engine["version"],
            "engine_identity": receipt["producer"].get("engine"),
            "consumer_installed_engine_identity": engine_bytes,
            "recognition_output_encoding": producer_metadata.get(
                "recognition_output_encoding"
            ),
            "wall_seconds": time.perf_counter() - cache_lookup_started,
            "child_cpu_seconds": 0.0,
            "child_peak_rss_kib": None,
            "return_code": 0,
            "tsv_sha256": _sha(tsv_path),
            "image_sha256": _sha(image_path),
            "reused_checkpoint": False,
            "reused_raw_observation": True,
            "raw_observation_cache": receipt,
            "resource_scope": "No recognition child launched; cache IO is charged to this worker",
        }
        _dump(meta_path, meta)
        if progress_callback:
            progress_callback(
                {
                    "stage": "local_ocr_raw_observation_reused",
                    "context_id": name,
                    "bbox_xyxy_px": list(box),
                    "psm": psm,
                    "observation_key": receipt["key"],
                }
            )
        return _bind_ocr_words(
            _parse_tsv(raw, origin_box, name, psm), specification, meta
        ), meta
    environment = dict(os.environ)
    environment.update(
        OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"
    )
    start = time.perf_counter()
    before_cpu, _ = _usage(children=True)
    if progress_callback:
        progress_callback(
            {
                "stage": "local_ocr_start",
                "context_id": name,
                "bbox_xyxy_px": list(box),
                "psm": psm,
            }
        )
    try:
        completed = run_subprocess(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=POLICY["local_timeout_seconds"],
        )
        raw, stderr, code = completed.stdout, completed.stderr, completed.returncode
        status = "COMPLETED" if code == 0 else "FAILED"
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        stderr = exc.stderr or ""
        raw = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        stderr = (
            stderr.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes)
            else stderr
        )
        code, status = None, "TIMEOUT"
    after_cpu, after_rss = _usage(children=True)
    tsv_path.write_text(raw, encoding="utf-8")
    (directory / f"{name}.stderr.txt").write_text(stderr, encoding="utf-8")
    meta = {
        "status": status,
        "specification": specification,
        "command": command,
        "engine_version": engine["version"],
        "engine_identity": engine_bytes,
        "recognition_output_encoding": "utf-8",
        "command_executed_for_this_request": True,
        "wall_seconds": time.perf_counter() - start,
        "child_cpu_seconds": after_cpu - before_cpu if before_cpu is not None else None,
        "child_peak_rss_kib": after_rss,
        "return_code": code,
        "tsv_sha256": _sha(tsv_path),
        "image_sha256": _sha(image_path),
        "reused_checkpoint": False,
    }
    _dump(meta_path, meta)
    if status == "TIMEOUT":
        raise NativeResourceLimit("OCR_SUBPROCESS_TIMEOUT:" + name)
    if status != "COMPLETED":
        raise RuntimeError("OCR_SUBPROCESS_FAILED:" + name + ":returncode=" + str(code))
    if cache is not None:
        meta["raw_observation_cache"] = cache.put(
            cache_spec,
            tsv_path.read_bytes(),
            producer_identity(__file__, engine=engine_bytes, metadata=meta),
        )
        _dump(meta_path, meta)
    return (
        _bind_ocr_words(_parse_tsv(raw, origin_box, name, psm), specification, meta)
        if status == "COMPLETED"
        else []
    ), meta


def _cached_observations(cache_dir, image, roi):
    if cache_dir is None:
        return None, {"enabled": False}
    directory = Path(cache_dir)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "source_array_sha256": source_array_sha256(image),
        "source_size_px": [int(image.shape[1]), int(image.shape[0])],
        "roi_xyxy_px": list(roi),
        "coordinate_system": "source_pixels_top_left",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Explicit OCR cache {key} mismatch")
    observation_path = directory / manifest.get(
        "observations_file", "observations.json"
    )
    if manifest.get("observations_sha256") != _sha(observation_path):
        raise ValueError("Explicit OCR cache observations hash mismatch")
    data = json.loads(observation_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("Cached OCR observations must be a list")
    cleaned = []
    for i, old in enumerate(data):
        box = old.get("bbox_xyxy_px")
        if not box or len(box) != 4 or _area(box) <= 0:
            raise ValueError("Malformed cached source box")
        if not _inside(box, [0, 0, image.shape[1], image.shape[0]]):
            raise ValueError("Cached word lies outside source")
        if not _intersection(box, roi):
            continue
        conf = float(old.get("confidence", -1))
        if not math.isfinite(conf):
            raise ValueError("Nonfinite cached confidence")
        cleaned.append(
            {
                "id": f"seed-{i:05d}",
                "text": str(old.get("text", "")),
                "confidence": conf,
                "bbox_xyxy_px": list(map(int, box)),
                "psm": int(old.get("psm", 11)),
                "context_id": str(old.get("tile_id", old.get("context_id", "cache"))),
                "line_key": str(old.get("line_key", i)),
                "word_num": int(old.get("word_num", 0)),
                "origin": "verified_cache",
            }
        )
    return cleaned, {
        "enabled": True,
        "directory": str(directory),
        "manifest_sha256": _sha(manifest_path),
        "manifest": manifest,
        "discovery_only": True,
        "local_re_OCR_required": True,
    }


@profiled("text_regions._discover_without_cache")
def _discover_without_cache(image, roi, output, progress_callback, *, dpi=200):
    margin = POLICY["discovery_context"]
    box = _clip(
        [roi[0] - margin, roi[1] - margin, roi[2] + margin, roi[3] + margin],
        image.shape,
    )
    words, passes = [], []
    size, overlap = POLICY["discovery_tile_size"], POLICY["discovery_overlap"]
    for y in _starts(box[1], box[3], size, overlap):
        for x in _starts(box[0], box[2], size, overlap):
            tile = [x, y, min(x + size, box[2]), min(y + size, box[3])]
            name = f"discovery-{len(passes):03d}"
            found, meta = _ocr(
                image,
                tile,
                POLICY["discovery_psm_without_cache"],
                output / "discovery_ocr",
                name,
                progress_callback,
                dpi=dpi,
            )
            for w in found:
                if _intersection(w["bbox_xyxy_px"], roi):
                    words.append(
                        {
                            **w,
                            "id": f"seed-{len(words):05d}",
                            "origin": "native_discovery_ocr",
                        }
                    )
            passes.append(meta)
    return words, passes


def _component_evidence(image, roi):
    import cv2
    import numpy as np

    x0, y0, x1, y1 = roi
    ink = np.ascontiguousarray(
        (image[y0:y1, x0:x1] < POLICY["source_threshold"]).astype(np.uint8)
    )
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    glyphs = []
    for lab, (x, y, w, h, area) in enumerate(stats[1:], 1):
        # A proposal heuristic only.  Every rejected/large component remains in
        # the original image; it is not labelled dust or removed from geometry.
        if (
            POLICY["minimum_glyph_height"] <= h <= POLICY["maximum_glyph_height"]
            and 2 <= w <= 120
            and area >= 8
            and 0.035 <= area / (w * h) <= 0.88
            and 0.04 <= w / h <= 5.0
        ):
            glyphs.append(
                {
                    "label": int(lab),
                    "bbox_xyxy_px": [
                        int(x + x0),
                        int(y + y0),
                        int(x + x0 + w),
                        int(y + y0 + h),
                    ],
                    "source_area_px": int(area),
                }
            )
    return ink, labels, glyphs


def _frames(ink, roi):
    import cv2
    import numpy as np

    # A one/two-cell scan break makes an otherwise rectangular outline return
    # a backtracking nonconvex contour.  A fixed 3x3 discovery-only closing adds
    # those hypotheses.  Edge evidence and every OCR crop still use raw ink;
    # this is not a claim that the source frame is continuously closed.
    contour_records = []
    for discovery_map, method in [
        (ink, "native_contour"),
        (
            cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)),
            "3x3_close_for_discovery_only",
        ),
    ]:
        contours, hierarchy = cv2.findContours(
            discovery_map, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        for ci, contour in enumerate(contours):
            row = (
                hierarchy[0, ci].astype(int).tolist() if hierarchy is not None else None
            )
            contour_records.append((contour, row, method))
    result = []
    for ci, (contour, hierarchy_row, discovery_method) in enumerate(contour_records):
        x, y, w, h = cv2.boundingRect(contour)
        if not (
            28 <= w <= POLICY["frame_maximum_width"]
            and 18 <= h <= POLICY["frame_maximum_height"]
            and 0.45 <= w / h <= 8
        ):
            continue
        perimeter = cv2.arcLength(contour, True)
        poly = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(poly) != 4 or not cv2.isContourConvex(poly):
            continue
        pts = poly[:, 0, :]
        if any(
            min(abs(int(b[0] - a[0])), abs(int(b[1] - a[1]))) > 3
            for a, b in zip(pts, np.roll(pts, -1, axis=0))
        ):
            continue
        band = 3
        support = [
            float(
                ink[max(0, y - band) : min(ink.shape[0], y + band + 1), x : x + w]
                .any(axis=0)
                .mean()
            ),
            float(
                ink[
                    max(0, y + h - 1 - band) : min(ink.shape[0], y + h + band),
                    x : x + w,
                ]
                .any(axis=0)
                .mean()
            ),
            float(
                ink[y : y + h, max(0, x - band) : min(ink.shape[1], x + band + 1)]
                .any(axis=1)
                .mean()
            ),
            float(
                ink[
                    y : y + h,
                    max(0, x + w - 1 - band) : min(ink.shape[1], x + w + band),
                ]
                .any(axis=1)
                .mean()
            ),
        ]
        if min(support) < POLICY["frame_minimum_edge_support"]:
            continue
        # Crop off only the measured enclosing border; no pixels inside this
        # native source crop are whitened.  The original border is retained.
        inset = max(3, min(6, int(round(min(w, h) * 0.07))))
        inner = [x + inset, y + inset, x + w - inset, y + h - inset]
        if inner[2] <= inner[0] or inner[3] <= inner[1]:
            continue
        internal = ink[inner[1] : inner[3], inner[0] : inner[2]]
        if int(internal.sum()) < 12 or internal.mean() > 0.65:
            continue
        source_box = [x + roi[0], y + roi[1], x + w + roi[0], y + h + roi[1]]
        if any(
            _overlap(source_box, old["enclosure_bbox_xyxy_px"]) > 0.92 for old in result
        ):
            continue
        result.append(
            {
                "bbox_xyxy_px": [
                    inner[0] + roi[0],
                    inner[1] + roi[1],
                    inner[2] + roi[0],
                    inner[3] + roi[1],
                ],
                "enclosure_bbox_xyxy_px": source_box,
                "edge_support": support,
                "contour_index": ci,
                "contour_points_xy_px": (pts + np.array(roi[:2])).astype(int).tolist(),
                "hierarchy": hierarchy_row,
                "contour_discovery_method": discovery_method,
                "discovery": "source_rectangle_contour_with_internal_ink",
                "source_rule_not_removed": True,
                "source_frame_continuity_proven": False,
                "geometry_must_verify_original_four_sides": True,
            }
        )
    return result


def _make_seeds(words, glyphs, frames):
    proposals = []
    for frame in frames:
        proposals.append(
            {
                "bbox_xyxy_px": frame["bbox_xyxy_px"],
                "origin": "enclosed_label",
                "priority": 0,
                "enclosure": frame,
                "seed_observation_ids": [],
                "glyph_labels": [],
                "discovery_strings": [],
            }
        )
    # Recover nearby words from a cached line only when their measured geometry
    # supports one printed line.  A PSM paragraph is not accepted wholesale.
    lines = {}
    for word in words:
        b = word["bbox_xyxy_px"]
        if (
            word["confidence"] >= 20
            and any(c.isalnum() for c in word["text"])
            and 7 <= b[3] - b[1] <= 90
            and 2 <= b[2] - b[0] <= 650
        ):
            lines.setdefault(word["line_key"], []).append(word)
    for members in lines.values():
        members.sort(key=lambda v: v["bbox_xyxy_px"][0])
        groups, current = [], []
        for word in members:
            if current:
                a, b = current[-1]["bbox_xyxy_px"], word["bbox_xyxy_px"]
                h = max(a[3] - a[1], b[3] - b[1])
                if b[0] - a[2] > 1.25 * h or abs(b[3] - a[3]) > 0.45 * h:
                    groups.append(current)
                    current = []
            current.append(word)
        if current:
            groups.append(current)
        for group in groups:
            box = _box_union([w["bbox_xyxy_px"] for w in group])
            if box[2] - box[0] <= 650:
                proposals.append(
                    {
                        "bbox_xyxy_px": box,
                        "origin": "ocr_line_geometry",
                        "priority": 1,
                        "seed_observation_ids": [w["id"] for w in group],
                        "glyph_labels": [],
                        "discovery_strings": [" ".join(w["text"] for w in group)],
                    }
                )
    # Connected compact glyph rows supply candidates missing from all OCR seeds.
    ordered = sorted(glyphs, key=lambda g: (g["bbox_xyxy_px"][1], g["bbox_xyxy_px"][0]))
    rows = []
    for glyph in ordered:
        box = glyph["bbox_xyxy_px"]
        h = box[3] - box[1]
        compatible = []
        for row in rows:
            b = row["bbox"]
            rh = row["height"]
            if 0.45 <= h / max(1, rh) <= 2.2 and abs(
                (box[1] + box[3] - b[1] - b[3]) / 2
            ) <= 0.35 * max(h, rh):
                gap = max(box[0] - b[2], b[0] - box[2], 0)
                if (
                    gap <= 1.25 * max(h, rh)
                    and max(box[2], b[2]) - min(box[0], b[0]) <= 650
                ):
                    compatible.append((gap, row))
        if compatible:
            row = min(compatible, key=lambda p: p[0])[1]
            row["items"].append(glyph)
            row["bbox"] = _box_union([row["bbox"], box])
            row["height"] = sorted(
                g["bbox_xyxy_px"][3] - g["bbox_xyxy_px"][1] for g in row["items"]
            )[len(row["items"]) // 2]
        else:
            rows.append({"items": [glyph], "bbox": box, "height": h})
    for row in rows:
        if len(row["items"]) >= 2:
            proposals.append(
                {
                    "bbox_xyxy_px": row["bbox"],
                    "origin": "compact_source_glyph_chain",
                    "priority": 2,
                    "seed_observation_ids": [],
                    "glyph_labels": [g["label"] for g in row["items"]],
                    "discovery_strings": [],
                }
            )
    # Prefer measured enclosures, then combine overlapping line observations.
    dedup = []
    for proposal in sorted(
        proposals,
        key=lambda p: (p["priority"], p["bbox_xyxy_px"][1], p["bbox_xyxy_px"][0]),
    ):
        b = proposal["bbox_xyxy_px"]
        same = None
        for existing in dedup:
            a = existing["bbox_xyxy_px"]
            if _overlap(a, b) < 0.72:
                continue
            # Avoid folding two separate printed rows into a tall false word.
            if abs((a[1] + a[3] - b[1] - b[3]) / 2) > 0.45 * max(
                a[3] - a[1], b[3] - b[1]
            ):
                continue
            same = existing
            break
        if same is None:
            dedup.append(dict(proposal))
        else:
            same["seed_observation_ids"] = sorted(
                set(same["seed_observation_ids"] + proposal["seed_observation_ids"])
            )
            same["glyph_labels"] = sorted(
                set(same["glyph_labels"] + proposal["glyph_labels"])
            )
            same["discovery_strings"] = sorted(
                set(same["discovery_strings"] + proposal["discovery_strings"])
            )
            if "enclosure" not in same:
                combined = _box_union([a, b])
                if combined[2] - combined[0] <= 650:
                    same["bbox_xyxy_px"] = combined
    for i, proposal in enumerate(dedup):
        proposal["id"] = f"TR-{i + 1:04d}"
    return dedup


def _local_boxes(seed, image_shape, glyphs):
    b = list(seed["bbox_xyxy_px"])
    if seed.get("enclosure"):
        # Both fixed local segmentation modes use the complete set of actual
        # compact components inside the measured frame.  This avoids passing a
        # residual frame edge as an extra bracket glyph.  It crops, rather than
        # whitens, the source; the original complete interior remains evidence.
        internal = [g["bbox_xyxy_px"] for g in glyphs if _inside(g["bbox_xyxy_px"], b)]
        if internal:
            core = _box_union(internal)
            core = [
                max(b[0], core[0] - 2),
                max(b[1], core[1] - 2),
                min(b[2], core[2] + 2),
                min(b[3], core[3] + 2),
            ]
        else:
            core = b
        seed["enclosure"]["OCR_glyph_domain_xyxy_px"] = list(core)
        seed["enclosure"]["OCR_domain_method"] = (
            "union_of_all_compact_source_components_inside_measured_frame_plus_2px_margin"
        )
        seed["enclosure"]["original_complete_interior_retained_xyxy_px"] = list(b)
        return [core, core]
    h = b[3] - b[1]
    # Extend to compact neighbour glyphs at the same baseline, including small
    # detached suffixes.  Connected wall/arc ink is not removed to make OCR easy.
    neighbors = []
    for glyph in glyphs:
        g = glyph["bbox_xyxy_px"]
        gh = g[3] - g[1]
        if (
            0.35 * h <= gh <= 1.7 * h
            and abs(g[3] - b[3]) <= 0.40 * h
            and max(g[0] - b[2], b[0] - g[2], 0) <= 1.5 * h
        ):
            neighbors.append(g)
    if neighbors:
        expanded = _box_union([b] + neighbors)
        if expanded[2] - expanded[0] <= 750:
            b = expanded
    return [
        _clip(
            [
                b[0] - max(3, int(0.25 * h)),
                b[1] - 2,
                b[2] + max(8, int(1.8 * h)),
                b[3] + 2,
            ],
            image_shape,
        ),
        _clip(
            [
                b[0] - max(6, int(0.55 * h)),
                b[1] - 4,
                b[2] + max(12, int(2.2 * h)),
                b[3] + 4,
            ],
            image_shape,
        ),
    ]


def _pass_plan(seed, image_shape, glyphs):
    boxes = _local_boxes(seed, image_shape, glyphs)
    if seed.get("enclosure"):
        psms = POLICY["enclosed_label_psms"]
        padding = POLICY["enclosed_label_external_padding_px"]
    else:
        psms, padding = POLICY["local_psms"], [0, 0]
    return [
        {"psm": psm, "crop_xyxy_px": box, "padding_px": pad}
        for psm, box, pad in zip(psms, boxes, padding)
    ]


def _select_line(words, focus):
    """Return raw OCR words on the focus baseline; no character repair."""
    h = max(1, focus[3] - focus[1])
    relevant = []
    for word in words:
        b = word["bbox_xyxy_px"]
        overlap_y = max(0, min(b[3], focus[3]) - max(b[1], focus[1]))
        if overlap_y / max(1, min(h, b[3] - b[1])) >= 0.45:
            relevant.append(word)
    anchors = [w for w in relevant if any(c.isalnum() for c in w["text"])]
    if not anchors:
        return []
    span = _box_union([w["bbox_xyxy_px"] for w in anchors])
    # Tesseract can tokenize a real engineering hyphen or punctuation mark
    # separately.  Preserve those original tokens between/adjacent to words;
    # filtering them as non-alphanumeric would silently change a source tag.
    relevant = [
        w
        for w in relevant
        if any(c.isalnum() for c in w["text"])
        or (
            w["bbox_xyxy_px"][2] >= span[0] - 0.5 * h
            and w["bbox_xyxy_px"][0] <= span[2] + 0.5 * h
        )
    ]
    return sorted(relevant, key=lambda w: w["bbox_xyxy_px"][0])


def _alternative_context_key(alternative, image):
    if alternative.get("observation_key"):
        return alternative["observation_key"]
    keys = {
        w.get("observation_key")
        for w in alternative.get("all_words", alternative.get("words", []))
        if w.get("observation_key")
    }
    if len(keys) == 1:
        return next(iter(keys))
    provenance = alternative.get("observation_provenance", {})
    specification = dict(provenance.get("specification", {}))
    box = list(alternative["crop_xyxy_px"])
    x0, y0, x1, y1 = _clip(box, image.shape)
    if not specification:
        # Legacy snapshots did not carry DPI/configuration in the alternative.
        # Retain that absence rather than manufacture a model/engine identity.
        specification = {
            "crop_xyxy_px": box,
            "crop_array_sha256": source_array_sha256(image[y0:y1, x0:x1]),
            "psm": alternative.get("psm"),
            "pixel_scale": [1, 1],
            "source_pixels_modified": False,
            "language": "eng",
            "recognition_dpi": alternative.get("recognition_dpi"),
            "external_white_padding_px": alternative.get(
                "external_white_padding_px", 0
            ),
            "padding_replaces_source_pixels": False,
        }
    return _observation_context_key(specification, provenance.get("engine_identity"))


def _source_label_contacts(labels, roi, rectangle, component_ids):
    """Actual source pixels of word-support components on a domain boundary.

    This operates on the unchanged source component labels, not OCR boxes or
    padded OCR images. Large/connected source components are not discarded.
    """
    import numpy as np

    if not component_ids:
        return []
    x0, y0, x1, y1 = map(int, rectangle)
    rx0, ry0, rx1, ry1 = map(int, roi)
    xa, xb, ya, yb = max(x0, rx0), min(x1, rx1), max(y0, ry0), min(y1, ry1)
    if xa >= xb or ya >= yb:
        return []
    contacts = []
    candidates = []
    if rx0 <= x0 < rx1:
        candidates.append(("left", labels[ya - ry0 : yb - ry0, x0 - rx0]))
    if rx0 < x1 <= rx1:
        candidates.append(("right", labels[ya - ry0 : yb - ry0, x1 - 1 - rx0]))
    if ry0 <= y0 < ry1:
        candidates.append(("top", labels[y0 - ry0, xa - rx0 : xb - rx0]))
    if ry0 < y1 <= ry1:
        candidates.append(("bottom", labels[y1 - 1 - ry0, xa - rx0 : xb - rx0]))
    for edge, values in candidates:
        # This evidence is part of the saved text contract. Keep its in-memory
        # form identical to its JSON form so later strict source checks compare
        # the same contract, including when the current run has not resumed.
        counts = [
            [int(lab), int((values == lab).sum())]
            for lab in np.unique(values)
            if int(lab) in component_ids
        ]
        if counts:
            contacts.append(
                {
                    "edge": edge,
                    "component_pixel_counts": counts,
                    "rectangle_xyxy_px": [x0, y0, x1, y1],
                }
            )
    return contacts


def _current_boundary_assessment(
    alternatives, chosen_words, image, roi, labels, context_keys
):
    """Keep all historic diagnostics, require two clean current full witnesses.

    A bounding-box contact alone is an OCR diagnostic. It may be superseded
    only by two independent current full-line observations with unchanged
    confidence gates, real source support, and no input/crop boundary contact.
    Actual source component contact at the effective input/ROI remains a veto,
    even when OCR invents a plausible complete word inside the clipped image.
    """
    import numpy as np

    supported, no_source = set(), []
    for index, word in enumerate(chosen_words):
        b = word["bbox_xyxy_px"]
        x0, y0, x1, y1 = (
            max(roi[0], b[0]),
            max(roi[1], b[1]),
            min(roi[2], b[2]),
            min(roi[3], b[3]),
        )
        local = labels[
            max(0, y0 - roi[1]) : max(0, y1 - roi[1]),
            max(0, x0 - roi[0]) : max(0, x1 - roi[0]),
        ]
        ids = {int(v) for v in np.unique(local) if v}
        if not ids:
            no_source.append(index)
        supported.update(ids)
    input_contacts = _source_label_contacts(labels, roi, roi, supported)
    records, clean_keys, touched = [], set(), []
    chosen_texts = [w["text"] for w in chosen_words]
    for index, alternative in enumerate(alternatives):
        crop = list(alternative["crop_xyxy_px"])
        words = alternative["words"]
        word_box = _box_union([w["bbox_xyxy_px"] for w in words]) if words else None
        box_touch = bool(
            word_box
            and min(
                word_box[0] - crop[0],
                word_box[1] - crop[1],
                crop[2] - word_box[2],
                crop[3] - word_box[3],
            )
            <= 0
        )
        if box_touch:
            touched.append(alternative["context_id"])
        applies = (
            bool(chosen_words)
            and [w["text"] for w in words] == chosen_texts
            and all(
                _overlap(w["bbox_xyxy_px"], c["bbox_xyxy_px"]) >= 0.6
                for w, c in zip(words, chosen_words)
            )
        )
        thresholds = [
            (
                POLICY["minimum_numeric_word_confidence"]
                if all(ch.isdigit() for ch in w["text"])
                else POLICY["minimum_word_confidence"]
            )
            for w in words
        ]
        confident = bool(words) and all(
            w["confidence"] >= limit for w, limit in zip(words, thresholds)
        )
        source_contacts = (
            _source_label_contacts(labels, roi, crop, supported) if applies else []
        )
        role = alternative.get("evidence_role", "current_candidate")
        clean = (
            role == "current_candidate"
            and alternative.get("status") == "COMPLETED"
            and applies
            and confident
            and not box_touch
            and not source_contacts
            and not input_contacts
            and not no_source
            and all(_inside(w["bbox_xyxy_px"], crop) for w in words)
        )
        if clean:
            clean_keys.add(context_keys[index])
        provenance = alternative.get("observation_provenance")
        if not provenance and words:
            provenance = words[0].get("observation_provenance")
        records.append(
            {
                "context_id": alternative["context_id"],
                "observation_key": context_keys[index],
                "evidence_role": role,
                "crop_xyxy_px": crop,
                "psm": alternative.get("psm"),
                "raw_artifact": alternative.get(
                    "raw_artifact", {"path": alternative.get("raw_tsv")}
                ),
                "observation_provenance": provenance,
                "applicable_raw_word_texts": [w["text"] for w in words],
                "matches_current_whole_line": applies,
                "unchanged_confidence_gates_pass": confident,
                "OCR_box_contacts_crop": box_touch,
                "actual_source_component_contacts_crop": source_contacts,
                "clean_current_full_line_witness": clean,
            }
        )
    return {
        "policy": "two_independent_current_full_line_source_witnesses_supersede_box_only_history_v1",
        "historical_failures_preserved": True,
        "all_crop_boundary_contexts": touched,
        "observations": records,
        "independent_clean_current_context_keys": sorted(clean_keys),
        "clean_current_full_line_witness_count": len(clean_keys),
        "actual_source_component_contacts_effective_input": input_contacts,
        "chosen_word_indices_without_source_ink": no_source,
        "support_component_ids": sorted(supported),
        "historical_crop_veto_superseded": bool(
            touched and len(clean_keys) >= 2 and not input_contacts and not no_source
        ),
        "source_pixels_modified": False,
        "confidence_thresholds_changed": False,
    }


def _complete_region(seed, alternatives, original_words, image, roi, glyphs, labels):
    import numpy as np

    context_keys = [_alternative_context_key(a, image) for a in alternatives]
    context_by_id = {a["context_id"]: key for a, key in zip(alternatives, context_keys)}

    def vote_key(word):
        return context_by_id.get(word.get("context_id")) or word.get("observation_key")

    by_string = {}
    for alternative, key in zip(alternatives, context_keys):
        words = alternative["words"]
        text = " ".join(w["text"] for w in words)
        if not text:
            continue
        score = sum(w["confidence"] for w in words) / len(words)
        entry = by_string.setdefault(
            text,
            {
                "text": text,
                "alternatives": [],
                "maximum_confidence": score,
                "independent_context_keys": set(),
            },
        )
        entry["alternatives"].append(alternative)
        entry["independent_context_keys"].add(key)
        entry["maximum_confidence"] = max(entry["maximum_confidence"], score)
    ranked = sorted(
        by_string.values(),
        key=lambda a: (
            -len(a["independent_context_keys"]),
            -a["maximum_confidence"],
            a["text"],
        ),
    )
    chosen = ranked[0] if ranked else None
    selected = (
        max(
            chosen["alternatives"],
            key=lambda a: sum(w["confidence"] for w in a["words"]) / len(a["words"]),
        )
        if chosen
        else {"words": [], "context_id": None}
    )
    words = selected["words"]
    box = (
        _box_union([w["bbox_xyxy_px"] for w in words])
        if words
        else list(seed["bbox_xyxy_px"])
    )
    reasons = []
    if not words:
        reasons.append("no_local_text_recognition")
    word_evidence = []
    for i, word in enumerate(words):
        numeric = all(c.isdigit() for c in word["text"])
        threshold = (
            POLICY["minimum_numeric_word_confidence"]
            if numeric
            else POLICY["minimum_word_confidence"]
        )
        local = [
            w
            for a in alternatives
            for w in a["words"]
            if w["text"] == word["text"]
            and w["confidence"] >= threshold
            and _overlap(w["bbox_xyxy_px"], word["bbox_xyxy_px"]) >= 0.6
        ]
        cached = [
            w
            for w in original_words
            if w["text"] == word["text"]
            and w["confidence"] >= threshold
            and _overlap(w["bbox_xyxy_px"], word["bbox_xyxy_px"]) >= 0.6
        ]
        local_contexts = sorted(set(w["context_id"] for w in local))
        contexts = local_contexts + sorted(
            set("seed:" + w["context_id"] + ":" + str(w["psm"]) for w in cached)
        )
        local_votes = {vote_key(w) for w in local if vote_key(w)}
        all_votes = local_votes | {vote_key(w) for w in cached if vote_key(w)}
        ok = (
            len(local_votes) >= 1
            and len(all_votes) >= 2
            and word["confidence"] >= threshold
        )
        if not ok:
            reasons.append("word_missing_two_confident_contexts_with_current_local_OCR")
        if len("".join(c for c in word["text"] if c.isalnum())) == 1 and not seed.get(
            "enclosure"
        ):
            reasons.append("single_character_may_be_graphic_symbol")
        wb = word["bbox_xyxy_px"]
        contradictory = []
        for cached_word in original_words:
            cb = cached_word["bbox_xyxy_px"]
            union = _area(cb) + _area(wb) - _intersection(cb, wb)
            if (
                cached_word["text"] != word["text"]
                and cached_word["confidence"] >= threshold
                and _intersection(cb, wb) / max(1, union) >= 0.65
                and min(cb[2] - cb[0], wb[2] - wb[0])
                / max(1, max(cb[2] - cb[0], wb[2] - wb[0]))
                >= 0.75
            ):
                contradictory.append(
                    {
                        "text": cached_word["text"],
                        "confidence": cached_word["confidence"],
                        "bbox_xyxy_px": cb,
                        "observation_id": cached_word["id"],
                    }
                )
        if contradictory:
            reasons.append(
                "high_confidence_seed_transcription_conflict_at_same_full_word_box"
            )
        word_evidence.append(
            {
                **word,
                "id": f"{seed['id']}-W{i + 1:02d}",
                "exact_agreement_contexts": contexts,
                "agreement_pass": ok,
                "independent_agreement_observation_keys": sorted(all_votes),
                "same_observation_not_double_counted_as_seed_and_local": True,
                "conflicting_seed_observations": contradictory,
                "required_confidence": threshold,
            }
        )
    distinct_high = [
        a
        for a in ranked
        if a["maximum_confidence"] >= POLICY["minimum_word_confidence"]
    ]
    if len(distinct_high) > 1:
        reasons.append("local_transcriptions_conflict")
    if not _inside(box, roi):
        reasons.append("crosses_requested_roi")
    chosen_text = chosen["text"] if chosen else ""
    # Direct prefix evidence is not discarded just because the short prefix has
    # a high confidence.  It remains incomplete until the full string agrees.
    prefix_pairs = []
    texts = sorted(set([a["text"] for a in ranked] + seed["discovery_strings"]))
    for short in texts:
        for long in texts:
            if (
                short
                and short != long
                and long.startswith(short)
                and len(long) > len(short)
            ):
                prefix_pairs.append({"short": short, "long": long})
    if any(p["short"] == chosen_text for p in prefix_pairs):
        reasons.append("selected_string_is_observed_prefix_of_longer_alternative")
    edge_glyphs, mask_labels = [], []
    bh = max(1, box[3] - box[1])
    inspection = (
        _box_union([a["crop_xyxy_px"] for a in alternatives])
        if alternatives
        else seed["bbox_xyxy_px"]
    )
    for glyph in glyphs:
        g = glyph["bbox_xyxy_px"]
        if _inside(g, inspection) and _overlap(g, box) >= 0.75:
            mask_labels.append(glyph["label"])
        baseline_close = abs(g[3] - box[3]) <= 0.35 * max(bh, g[3] - g[1])
        right_gap, left_gap = g[0] - box[2], box[0] - g[2]
        if (
            words
            and baseline_close
            and ((0 <= right_gap <= 1.1 * bh) or (0 <= left_gap <= 0.65 * bh))
        ):
            if not any(_overlap(g, w["bbox_xyxy_px"]) >= 0.5 for w in words):
                edge_glyphs.append({"bbox_xyxy_px": g, "label": glyph["label"]})
    if edge_glyphs and not seed.get("enclosure"):
        reasons.append("unread_source_components_adjacent_to_line_ends")
    unread_enclosed = []
    if seed.get("enclosure"):
        inner = seed["enclosure"]["bbox_xyxy_px"]
        unread_enclosed = [
            g
            for g in glyphs
            if _inside(g["bbox_xyxy_px"], inner)
            and not any(
                _overlap(g["bbox_xyxy_px"], w["bbox_xyxy_px"]) >= 0.5 for w in words
            )
        ]
        if unread_enclosed:
            reasons.append("unread_compact_source_components_inside_label_frame")
    boundary_assessment = _current_boundary_assessment(
        alternatives, words, image, roi, labels, context_keys
    )
    crop_touches = boundary_assessment["all_crop_boundary_contexts"]
    if crop_touches and not boundary_assessment["historical_crop_veto_superseded"]:
        reasons.append("OCR_ink_touches_local_crop_boundary")
    if boundary_assessment["actual_source_component_contacts_effective_input"]:
        reasons.append("source_text_support_touches_effective_input_boundary")
    if (
        any(
            r["evidence_role"] == "current_candidate"
            and r["actual_source_component_contacts_crop"]
            for r in boundary_assessment["observations"]
        )
        and boundary_assessment["clean_current_full_line_witness_count"] < 2
    ):
        reasons.append("source_text_support_crosses_current_crop_boundary")
    if boundary_assessment["chosen_word_indices_without_source_ink"]:
        reasons.append("recognised_word_has_no_actual_source_ink_support")
    x0, y0, x1, y1 = _clip(inspection, image.shape)
    mask_box = [max(roi[0], x0), max(roi[1], y0), min(roi[2], x1), min(roi[3], y1)]
    rx0, ry0, rx1, ry1 = mask_box
    local_labels = labels[ry0 - roi[1] : ry1 - roi[1], rx0 - roi[0] : rx1 - roi[0]]
    if not mask_labels:
        mask_labels = [
            g["label"]
            for g in glyphs
            if _inside(g["bbox_xyxy_px"], seed["bbox_xyxy_px"])
        ]
    compact_mask = (
        np.isin(local_labels, mask_labels)
        if local_labels.size
        else np.zeros((0, 0), dtype=bool)
    )
    source = image[box[1] : box[3], box[0] : box[2]]
    return {
        "id": seed["id"],
        "bbox_xyxy_px": box,
        "discovery_bbox_xyxy_px": seed["bbox_xyxy_px"],
        "inspection_bbox_xyxy_px": inspection,
        "words": word_evidence,
        "text": chosen_text,
        "token_join_policy": "one_space_between_raw_TSV_tokens; no character replacement or punctuation deletion",
        "status": "TEXT_PROPOSAL_PENDING_SOURCE_REVIEW"
        if words and not reasons
        else "UNRESOLVED_TEXT_REGION",
        "complete": bool(words and not reasons),
        "complete_claim_scope": "finite_local_OCR_and_source_end_checks_not_semantic_proof",
        "source_review_required": True,
        "unresolved_reasons": sorted(set(reasons)),
        "accepted": False,
        "enclosure": seed.get("enclosure"),
        "discovery_origin": seed["origin"],
        "discovery_observation_ids": seed["seed_observation_ids"],
        "completeness_evidence": {
            "alternatives": alternatives,
            "prefix_alternatives": prefix_pairs,
            "adjacent_unread_components": edge_glyphs,
            "unread_compact_components_inside_frame": unread_enclosed,
            "crop_boundary_contexts": crop_touches,
            "current_boundary_assessment": boundary_assessment,
            "crop_boundary_contexts_are_diagnostics_not_unconditional_veto": True,
            "source_ink_pixels_in_text_box": int(
                (source < POLICY["source_threshold"]).sum()
            ),
            "source_rules_not_removed": True,
        },
        "compact_source_ink_mask": {
            "runs_y_x0_x1": _rle(compact_mask, mask_box[:2]),
            "component_labels": sorted(set(mask_labels)),
            "meaning": "candidate compact glyph ink; not every pixel inside a text bbox",
            "source_erasure_authorized": False,
        },
    }


def _groups(regions):
    # One region is one line or enclosed label.  Multiline groups require
    # comparable character height, close vertical spacing and a shared margin.
    used, result = set(), []
    ordered = sorted(
        regions, key=lambda r: (r["bbox_xyxy_px"][1], r["bbox_xyxy_px"][0])
    )
    for region in ordered:
        if region["id"] in used:
            continue
        chain = [region]
        if not region.get("enclosure") and region["words"]:
            current = region
            for _ in range(5):
                a = current["bbox_xyxy_px"]
                h = a[3] - a[1]
                possible = []
                for nxt in ordered:
                    if (
                        nxt["id"] in used
                        or nxt in chain
                        or nxt.get("enclosure")
                        or not nxt["words"]
                    ):
                        continue
                    b = nxt["bbox_xyxy_px"]
                    nh = b[3] - b[1]
                    gap = b[1] - a[3]
                    aligned = abs(b[0] - a[0]) <= 0.75 * max(h, nh) or abs(
                        (b[0] + b[2] - a[0] - a[2]) / 2
                    ) <= 0.65 * max(h, nh)
                    if (
                        0 <= gap <= 1.25 * max(h, nh)
                        and 0.6 <= nh / max(1, h) <= 1.7
                        and aligned
                    ):
                        possible.append((gap, nxt))
                if not possible:
                    break
                current = min(possible, key=lambda p: p[0])[1]
                chain.append(current)
        used.update(r["id"] for r in chain)
        lines = [
            {
                "region_id": r["id"],
                "text": r["text"],
                "bbox_xyxy_px": r["bbox_xyxy_px"],
                "complete": r["complete"],
                "word_ids": [w["id"] for w in r["words"]],
            }
            for r in chain
        ]
        text = "\n".join(r["text"] for r in chain)
        complete = all(r["complete"] for r in chain)
        result.append(
            {
                "id": f"TG-{len(result) + 1:04d}",
                "geometry_type": "MTEXT" if len(chain) > 1 else "TEXT",
                "kind": "multiline_geometric_group"
                if len(chain) > 1
                else ("enclosed_label" if region.get("enclosure") else "single_line"),
                "bbox_xyxy_px": _box_union([r["bbox_xyxy_px"] for r in chain]),
                "region_ids": [r["id"] for r in chain],
                "lines": lines,
                "text": text,
                "complete": complete,
                "source_review_required": True,
                "unresolved_reasons": sorted(
                    set(reason for r in chain for reason in r["unresolved_reasons"])
                ),
                "enclosure": region.get("enclosure"),
                "numeric_label": len(chain) == 1 and bool(text) and text.isdigit(),
                "grouping_is_semantic_proof": False,
                "automatic_formal_adoption": False,
            }
        )
    return result


def _overlay(image, roi, regions, output):
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = roi
    picture = Image.fromarray(image[y0:y1, x0:x1]).convert("RGB")
    draw = ImageDraw.Draw(picture)
    for region in regions:
        b = region["bbox_xyxy_px"]
        color = (0, 150, 70) if region["complete"] else (225, 110, 0)
        draw.rectangle(
            [b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0], outline=color, width=2
        )
        draw.text((b[0] - x0, max(0, b[1] - y0 - 11)), region["id"], fill=color)
        if region.get("enclosure"):
            e = region["enclosure"]["enclosure_bbox_xyxy_px"]
            draw.rectangle(
                [e[0] - x0, e[1] - y0, e[2] - x0, e[3] - y0],
                outline=(0, 110, 220),
                width=1,
            )
    path = output / "text_regions_bbox_overlay.png"
    picture.save(path)
    return path.name


@profiled("text_regions.extract_text_regions")
def extract_text_regions(
    image_gray_native,
    roi_xyxy,
    output_dir,
    *,
    progress_callback=None,
    cache_dir=None,
    dpi=200,
):
    """Return the source-pixel region contract and save complete OCR evidence.

    Optional cache_dir contains manifest.json + observations.json and must match
    source_array_sha256, source_size_px and roi_xyxy_px exactly.  It is discovery
    input only.  A missing cache runs native tiled sparse OCR before local passes.
    The caller owns formal review, CAD export, and any geometry decisions.
    """
    import numpy as np

    start = time.perf_counter()
    image = np.asarray(image_gray_native)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise TypeError("image_gray_native must be a full-page 2D uint8 array")
    roi = list(map(int, roi_xyxy))
    if (
        len(roi) != 4
        or _area(roi) <= 0
        or not _inside(roi, [0, 0, image.shape[1], image.shape[0]])
    ):
        raise ValueError("roi_xyxy must be a positive half-open full-source box")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    engine = _resolve_tesseract(os.environ.get("I2CAD_TESSERACT", ""))
    source_hash = source_array_sha256(image)
    policy = {
        "policy": POLICY,
        "code_sha256": _sha(Path(__file__)),
        "coordinate_system": "source_pixels_top_left",
        "source_array_sha256": source_hash,
        "source_size_px": [int(image.shape[1]), int(image.shape[0])],
        "roi_xyxy_px": roi,
        "engine": engine,
        "recognition_dpi": int(dpi),
    }
    policy_path = output / "policy_frozen_before_recognition.json"
    if policy_path.exists() and json.loads(policy_path.read_text(encoding="utf-8")) != policy:
        raise ValueError(
            "Changed source/code/policy requires a fresh evidence output directory"
        )
    _dump(policy_path, policy)
    observations, cache_evidence = _cached_observations(cache_dir, image, roi)
    discovery_passes = []
    if observations is None:
        observations, discovery_passes = _discover_without_cache(
            image, roi, output, progress_callback, dpi=dpi
        )
    _dump(output / "discovery_observations.json", observations)
    ink, labels, glyphs = _component_evidence(image, roi)
    frames = _frames(ink, roi)
    seeds = _make_seeds(observations, glyphs, frames)
    _dump(output / "source_frame_discovery.json", frames)
    _dump(output / "source_component_proposals.json", glyphs)
    _dump(output / "region_seeds.json", seeds)
    if progress_callback:
        progress_callback(
            {
                "stage": "text_region_discovery_complete",
                "regions": len(seeds),
                "source_frames": len(frames),
                "cached_discovery": cache_dir is not None,
            }
        )
    regions, passes = [], []
    local_start = time.perf_counter()
    stopped = False
    for index, seed in enumerate(seeds):
        check_cancel("TEXT_REGION:" + seed["id"])
        alternatives = []
        reason = None
        if index >= POLICY["maximum_local_regions"]:
            reason = "local_region_budget_unprocessed"
        elif (
            time.perf_counter() - local_start
            >= POLICY["total_local_wall_budget_seconds"]
        ):
            stopped, reason = True, "local_wall_budget_unprocessed"
        if reason is None:
            for plan in _pass_plan(seed, image.shape, glyphs):
                psm, box, padding = (
                    plan["psm"],
                    plan["crop_xyxy_px"],
                    plan["padding_px"],
                )
                name = f"{seed['id']}-p{psm}"
                found, meta = _ocr(
                    image,
                    box,
                    psm,
                    output / "local_ocr",
                    name,
                    progress_callback,
                    padding,
                    dpi=dpi,
                )
                passes.append({"region_id": seed["id"], **meta})
                alternatives.append(
                    {
                        "context_id": name,
                        "psm": psm,
                        "crop_xyxy_px": box,
                        "status": meta["status"],
                        "raw_tsv": f"local_ocr/{name}.tsv",
                        "external_white_padding_px": padding,
                        "all_words": found,
                        "words": _select_line(found, seed["bbox_xyxy_px"]),
                    }
                )
        region = _complete_region(
            seed, alternatives, observations, image, roi, glyphs, labels
        )
        if reason:
            region["unresolved_reasons"] = sorted(
                set(region["unresolved_reasons"] + [reason])
            )
            region["complete"] = False
        regions.append(region)
        _dump(output / "region_checkpoints" / f"{seed['id']}.json", region)
        if progress_callback:
            progress_callback(
                {
                    "stage": "text_region_complete",
                    "region_id": seed["id"],
                    "text": region["text"],
                    "complete": region["complete"],
                    "completed": len(regions),
                    "total": len(seeds),
                }
            )
    groups = _groups(regions)
    combined_mask = np.zeros_like(ink, dtype=np.uint8)
    for region in regions:
        for y, a, b in region["compact_source_ink_mask"]["runs_y_x0_x1"]:
            combined_mask[y - roi[1], a - roi[0] : b - roi[0]] = 255
    from PIL import Image

    Image.fromarray(combined_mask).save(output / "compact_glyph_candidate_mask.png")
    overlay = _overlay(image, roi, regions, output)
    if source_array_sha256(image) != source_hash:
        raise RuntimeError("Caller source image changed during text extraction")
    own_cpu, own_rss = _usage()
    report = {
        "schema": "native_text_regions_v2",
        "schema_version": 2,
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": policy["source_size_px"],
        "roi_xyxy_px": roi,
        "source_array_sha256": source_hash,
        "regions": regions,
        "groups": groups,
        "uncertainties": [
            {
                "region_id": r["id"],
                "bbox_xyxy_px": r["bbox_xyxy_px"],
                "text": r["text"],
                "reasons": r["unresolved_reasons"],
            }
            for r in regions
            if not r["complete"]
        ],
        "bbox_overlay": overlay,
        "text_candidate_mask": {
            "path": "compact_glyph_candidate_mask.png",
            "origin_xy_px": roi[:2],
            "size_px": [roi[2] - roi[0], roi[3] - roi[1]],
            "coordinate_system": "source_pixels_top_left",
            "source_erasure_authorized": False,
            "policy": POLICY["mask_policy"],
        },
        "cache": cache_evidence,
        "policy": POLICY,
        "engine": engine,
        "status": "RESOURCE_STOP_PARTIAL"
        if stopped
        else "COMPLETED_PENDING_SOURCE_REVIEW",
        "discovery_coverage_complete": False,
        "automatic_formal_adoption": False,
        "source_pixels_modified": False,
        "resources": {
            "wall_seconds": time.perf_counter() - start,
            "process_cpu_seconds": own_cpu,
            "peak_rss_kib": own_rss,
            "discovery_ocr_calls": len(discovery_passes),
            "local_ocr_calls": len(passes),
            "new_local_ocr_calls": sum(not p["reused_checkpoint"] for p in passes),
            "local_child_cpu_seconds": (
                sum(
                    p["child_cpu_seconds"] for p in passes if not p["reused_checkpoint"]
                )
                if all(
                    p["child_cpu_seconds"] is not None
                    for p in passes
                    if not p["reused_checkpoint"]
                )
                else None
            ),
            "local_passes": passes,
            "discovery_passes": discovery_passes,
        },
    }
    _dump(output / "text_regions.json", report)
    _dump(
        output / "group_summary.json",
        [
            {
                k: g[k]
                for k in (
                    "id",
                    "geometry_type",
                    "kind",
                    "text",
                    "bbox_xyxy_px",
                    "complete",
                    "unresolved_reasons",
                    "numeric_label",
                )
            }
            for g in groups
        ],
    )
    return report
