"""Bounded explicit selection of one complete native raster component.

This manifest selects data; it never authorizes bypassing the live source guards.
Working parent runs are local to ``prepared_window``. Native member runs use the
same window at ``native_scale``. All intervals and the full working crop are
half-open, and all coordinates denote source cells, not CAD coordinates.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re

VERSION = "explicit-native-source-region-selection-v1"
MAX_MANIFEST_BYTES = 1_048_576
MAX_WORKING_WINDOW_PIXELS = 100_000
MAX_NATIVE_WINDOW_PIXELS = 1_000_000
MAX_WORKING_PARENT_PIXELS = 8_192
MAX_RUNS = 100_000
MAX_NATIVE_SCALE = 16


def _object(value, keys, label):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} fields")
    return value


def _integer(value, label, *, minimum=0):
    if type(value) is not int or not minimum <= value <= 2_147_483_647:
        raise ValueError(f"Invalid {label} integer")
    return value


def _vector(value, length, label, *, minimum=0):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"Invalid {label} dimensions")
    return [_integer(v, label, minimum=minimum) for v in value]


def _sha256(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"Invalid {label} SHA256")
    return value.lower()


def _positive_number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"Invalid {label}")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"Invalid {label}")
    return number


def _image_identity(value, label):
    value = _object(value, ("pixels_sha256", "shape_yx", "dtype", "dpi"), label)
    if value["dtype"] != "uint8":
        raise ValueError(f"{label} must use uint8 source pixels")
    return {
        "pixels_sha256": _sha256(value["pixels_sha256"], label),
        "shape_yx": _vector(value["shape_yx"], 2, label, minimum=1),
        "dtype": "uint8",
        "dpi": _positive_number(value["dpi"], label + " DPI"),
    }


def _runs(value, shape, label, *, max_pixels):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_RUNS:
        raise ValueError(f"Invalid or over-budget {label} source runs")
    result = []
    previous = (-1, -1, -1)
    pixels = 0
    for item in value:
        y, start, end = _vector(item, 3, label)
        if not (y < shape[0] and start < end <= shape[1]):
            raise ValueError(f"Out-of-bounds {label} source run")
        current = (y, start, end)
        if current <= previous or (y == previous[0] and start <= previous[2]):
            raise ValueError(f"Noncanonical {label} source runs")
        pixels += end - start
        if pixels > max_pixels:
            raise ValueError(f"{label} source pixel budget exceeded")
        result.append([y, start, end])
        previous = current
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate source region manifest key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Nonfinite source region manifest value")


def parse_source_region_selection(value: str | Mapping) -> dict:
    """Return normalized JSON data; reject unknown fields and excessive source.

    This performs no raster allocation and proves no permission to retire source.
    Both a decoded mapping and a JSON string are accepted; the returned data is a
    new bounded tree, so callers may hold its canonical JSON as immutable config.
    """
    if isinstance(value, str):
        try:
            if len(value.encode("utf-8")) > MAX_MANIFEST_BYTES:
                raise ValueError("Source region manifest byte budget exceeded")
            value = json.loads(value, object_pairs_hook=_unique_object,
                               parse_constant=_invalid_constant)
        except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
            raise ValueError("Invalid source region manifest JSON") from exc
    value = _object(value, ("version", "input", "original", "crop_work_px",
                           "native_scale", "prepared_window", "selection"), "manifest")
    if value["version"] != VERSION:
        raise ValueError("Unsupported source region selection version")
    input_identity = _image_identity(value["input"], "working input")
    original_identity = _image_identity(value["original"], "native original")
    ratio = _integer(value["native_scale"], "native scale", minimum=2)
    if ratio > MAX_NATIVE_SCALE:
        raise ValueError("Native scale budget exceeded")
    if original_identity["shape_yx"] != [n * ratio for n in input_identity["shape_yx"]]:
        raise ValueError("Working and original image dimensions do not register")
    if not math.isclose(original_identity["dpi"], input_identity["dpi"] * ratio,
                        rel_tol=0.0, abs_tol=0.01):
        raise ValueError("Working and original DPI do not register")
    left, top, right, bottom = _vector(value["crop_work_px"], 4, "working crop")
    height, width = input_identity["shape_yx"]
    if not (left < right <= width and top < bottom <= height):
        raise ValueError("Working crop lies outside the complete input")
    window = _object(value["prepared_window"],
                     ("origin_work_px", "shape_yx", "pixels_sha256", "dtype"),
                     "prepared window")
    origin = _vector(window["origin_work_px"], 2, "prepared origin")
    shape = _vector(window["shape_yx"], 2, "prepared shape", minimum=1)
    if window["dtype"] != "uint8":
        raise ValueError("Prepared window must use uint8 pixels")
    if (origin[0] + shape[1] > right - left or origin[1] + shape[0] > bottom - top):
        raise ValueError("Prepared window lies outside the trace crop")
    if shape[0] * shape[1] > MAX_WORKING_WINDOW_PIXELS:
        raise ValueError("Working source window budget exceeded")
    native_shape = [n * ratio for n in shape]
    if native_shape[0] * native_shape[1] > MAX_NATIVE_WINDOW_PIXELS:
        raise ValueError("Native source window budget exceeded")
    selection = _object(value["selection"],
                        ("id", "working_parent_runs_y_x0_x1", "native_member_runs_y_x0_x1"),
                        "selection")
    identifier = selection["id"]
    if (not isinstance(identifier, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", identifier) is None):
        raise ValueError("Invalid source region selection ID")
    normalized = {
        "version": VERSION,
        "input": input_identity,
        "original": original_identity,
        "crop_work_px": [left, top, right, bottom],
        "native_scale": ratio,
        "prepared_window": {
            "origin_work_px": origin, "shape_yx": shape, "dtype": "uint8",
            "pixels_sha256": _sha256(window["pixels_sha256"], "prepared window"),
        },
        "selection": {
            "id": identifier,
            "working_parent_runs_y_x0_x1": _runs(
                selection["working_parent_runs_y_x0_x1"], shape, "working parent",
                max_pixels=MAX_WORKING_PARENT_PIXELS),
            "native_member_runs_y_x0_x1": _runs(
                selection["native_member_runs_y_x0_x1"], native_shape, "native member",
                max_pixels=MAX_NATIVE_WINDOW_PIXELS),
        },
    }
    if len(_canonical(normalized).encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ValueError("Source region manifest byte budget exceeded")
    return normalized


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def canonical_source_region_selection(value: str | Mapping) -> str:
    return _canonical(parse_source_region_selection(value))


def source_region_selection_digest(value: str | Mapping) -> str:
    return hashlib.sha256(canonical_source_region_selection(value).encode("utf-8")).hexdigest()
