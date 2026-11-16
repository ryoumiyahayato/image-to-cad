"""Explicit complete native source component handoff, with no automatic search.

All checks finish before a copied residual mask is retired. A rejected explicit
request raises instead of silently exporting an unchanged drawing as success.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math

import cv2
import numpy as np
from scipy import ndimage

from app.core.cancellation import checkpoint
from app.core.trace_types import TracePath
from app.geometry.raster_trace import trace_binary
from app.geometry.source_region_selection import (
    MAX_RUNS,
    parse_source_region_selection,
    source_region_selection_digest,
)

VERSION = "explicit-native-source-region-v1"


def _pixels_sha256(image):
    return hashlib.sha256(np.ascontiguousarray(image)).hexdigest()


def _valid_dpi(value):
    return (not isinstance(value, (bool, np.bool_))
            and isinstance(value, (int, float, np.integer, np.floating))
            and math.isfinite(value) and value > 0)


def source_region_input_identity(image: np.ndarray, dpi: float) -> dict:
    """Measure the actual full input once, before preparation or crop slicing."""
    if (not isinstance(image, np.ndarray) or image.ndim != 2
            or image.dtype != np.uint8 or not image.size):
        raise ValueError("Explicit source regions require a two-dimensional uint8 input")
    if not _valid_dpi(dpi):
        raise ValueError("Explicit source regions require a positive finite input DPI")
    return {"pixels_sha256": _pixels_sha256(image),
            "shape_yx": list(map(int, image.shape)), "dtype": "uint8", "dpi": float(dpi)}


def _mask(runs, shape):
    result = np.zeros(shape, dtype=bool)
    for y, start, end in runs:
        result[y, start:end] = True
    return result


def _runs(mask):
    result = []
    for y, row in enumerate(mask):
        transitions = np.diff(np.r_[False, row, False].astype(np.int8))
        result.extend([y, int(start), int(end)] for start, end in zip(
            np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1)))
        if len(result) > MAX_RUNS:
            raise ValueError("Explicit source region generated run budget exceeded")
    return result


def _one_component(mask, connectivity):
    structure = ndimage.generate_binary_structure(2, 2 if connectivity == 8 else 1)
    return ndimage.label(mask, structure=structure)[1] == 1


def _interior(mask):
    return not (mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())


def recover_explicit_native_source_regions(
    gray: np.ndarray, binary: np.ndarray, visible_binary: np.ndarray, *,
    selection_manifest: str | Mapping,
    protected_masks: Sequence[np.ndarray | None] = (), dpi: float = 100.,
    registered_original_scan=None, source_crop=None,
    source_identity: Mapping[str, object] | None = None, cancellation_token=None,
) -> tuple[np.ndarray, tuple[TracePath, ...], tuple[dict, ...], dict]:
    """Validate one explicit selection and transfer its complete working parent.

    ``source_identity`` is measured from the full input by the production entry,
    before crop and preparation. It is compared with the supplied manifest; live
    prepared/current/protected masks and original bytes are checked independently.
    """
    checkpoint(cancellation_token)
    manifest = parse_source_region_selection(selection_manifest)
    if (not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.dtype != np.uint8
            or not gray.size or not isinstance(binary, np.ndarray)
            or not isinstance(visible_binary, np.ndarray)
            or binary.dtype != np.uint8 or visible_binary.dtype != np.uint8
            or binary.shape != gray.shape or visible_binary.shape != gray.shape):
        raise ValueError("Explicit source region working mask contract is invalid")
    if (not _valid_dpi(dpi)
            or float(dpi) != manifest["input"]["dpi"]):
        raise ValueError("Explicit source region working DPI changed")
    if (not isinstance(source_identity, Mapping)
            or dict(source_identity) != manifest["input"]):
        raise ValueError("Explicit source region complete input identity changed")
    for protected in protected_masks:
        if (protected is not None and (not isinstance(protected, np.ndarray)
                or protected.shape != gray.shape
                or protected.dtype not in (np.dtype(np.uint8), np.dtype(np.bool_)))):
            raise ValueError("Explicit source region protection mask contract is invalid")
    scan = registered_original_scan
    if scan is None:
        raise ValueError("Explicit source region requires a verified original scan")
    native_full = getattr(scan, "pixels", None)
    scan_ratio = getattr(scan, "ratio", None)
    scan_dpi = getattr(scan, "dpi", None)
    ratio = manifest["native_scale"]
    if (isinstance(scan_ratio, (bool, np.bool_))
            or not isinstance(scan_ratio, (int, np.integer)) or int(scan_ratio) != ratio
            or not isinstance(native_full, np.ndarray) or native_full.ndim != 2
            or native_full.dtype != np.uint8
            or list(native_full.shape) != manifest["original"]["shape_yx"]
            or not _valid_dpi(scan_dpi)
            or float(scan_dpi) != manifest["original"]["dpi"]
            or not math.isclose(float(scan_dpi), float(dpi) * ratio,
                                rel_tol=0.0, abs_tol=0.01)):
        raise ValueError("Explicit source region original grid contract changed")
    if _pixels_sha256(native_full) != manifest["original"]["pixels_sha256"]:
        raise ValueError("Explicit source region complete original identity changed")
    # Keep full-source bitonal verification bounded in temporary memory.
    block_rows = max(1, 1_000_000 // native_full.shape[1])
    for start in range(0, native_full.shape[0], block_rows):
        checkpoint(cancellation_token)
        block = native_full[start:start + block_rows]
        if np.any((block != 0) & (block != 255)):
            raise ValueError("Explicit source region original is not bitonal")
    input_h, input_w = manifest["input"]["shape_yx"]
    actual_crop = (0, 0, input_w, input_h) if source_crop is None else source_crop
    if (not isinstance(actual_crop, (tuple, list)) or len(actual_crop) != 4
            or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer))
                   for v in actual_crop)
            or list(actual_crop) != manifest["crop_work_px"]):
        raise ValueError("Explicit source region working crop changed")
    left, top, right, bottom = map(int, actual_crop)
    if gray.shape != (bottom - top, right - left):
        raise ValueError("Explicit source region prepared crop shape changed")
    window = manifest["prepared_window"]
    ox, oy = window["origin_work_px"]
    height, width = window["shape_yx"]
    sl = np.s_[oy:oy + height, ox:ox + width]
    local_gray = gray[sl]
    if _pixels_sha256(local_gray) != window["pixels_sha256"]:
        raise ValueError("Explicit source region prepared window identity changed")
    selection = manifest["selection"]
    parent_work = _mask(selection["working_parent_runs_y_x0_x1"], (height, width))
    if not _interior(parent_work) or not _one_component(parent_work, 8):
        raise ValueError("Working parent must be one complete interior eight-connected component")
    if np.any(parent_work & (local_gray >= 254)):
        raise ValueError("Working parent contains non-source cells")
    parent_halo = ndimage.binary_dilation(parent_work, structure=np.ones((3, 3), bool))
    if np.any(parent_halo & (local_gray < 254) & ~parent_work):
        raise ValueError("Working parent omits connected prepared source")
    if np.any(parent_work & (binary[sl] >= 128)):
        raise ValueError("Whole parent contains noncurrent source")
    if np.any(parent_work & (visible_binary[sl] >= 128)):
        raise ValueError("Whole parent contains previously claimed source")
    if any(protected is not None and np.any(parent_work & (protected[sl] > 0))
           for protected in protected_masks):
        raise ValueError("Whole parent contains protected source")

    full_x, full_y = (left + ox) * ratio, (top + oy) * ratio
    native = native_full[full_y:full_y + height * ratio,
                         full_x:full_x + width * ratio]
    reduced = cv2.resize(native, (width, height), interpolation=cv2.INTER_AREA)
    if (not np.array_equal(reduced < 254, local_gray < 254)
            or np.max(np.abs(reduced.astype(np.int16) - local_gray.astype(np.int16))) > 1):
        raise ValueError("Prepared window is not registered to the original source")
    parent = np.repeat(np.repeat(parent_work, ratio, axis=0), ratio, axis=1) & (native == 0)
    member = _mask(selection["native_member_runs_y_x0_x1"], native.shape)
    if not parent.any() or np.any(member & ~parent) or np.array_equal(member, parent):
        raise ValueError("Selected native member must be a nonempty proper parent subset")
    if not _interior(member) or not _one_component(member, 8):
        raise ValueError("Selected native member must be one interior eight-connected component")
    if not _one_component(member, 4):
        raise ValueError("Corner-only native member is outside the first source region contract")
    # Use full original coordinates for the complete one-cell native halo.
    yy, xx = np.nonzero(member)
    x0, y0, x1, y1 = int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1
    absolute_x0, absolute_y0 = full_x + x0, full_y + y0
    absolute_x1, absolute_y1 = full_x + x1, full_y + y1
    if (absolute_x0 <= 0 or absolute_y0 <= 0
            or absolute_x1 >= native_full.shape[1] or absolute_y1 >= native_full.shape[0]):
        raise ValueError("Native component touches the complete source boundary")
    halo_source = native_full[absolute_y0 - 1:absolute_y1 + 1,
                              absolute_x0 - 1:absolute_x1 + 1] == 0
    halo_member = np.pad(member[y0:y1, x0:x1], 1)
    if np.any(ndimage.binary_dilation(halo_member, structure=np.ones((3, 3), bool))
              & halo_source & ~halo_member):
        raise ValueError("Selected member is incomplete in the full native source")
    residual = parent & ~member
    foreign = (native == 0) & ~parent
    checkpoint(cancellation_token)
    from app.export.source_region_entities import CONTRACT_SHA256, preflight_source_region

    source_identity_record = {
        "input_pixels_sha256": manifest["input"]["pixels_sha256"],
        "input_shape": tuple(manifest["input"]["shape_yx"]), "input_dtype": "uint8",
        "original_pixels_sha256": manifest["original"]["pixels_sha256"],
        "original_shape": tuple(native_full.shape), "original_dtype": "uint8",
        "working_dpi": float(dpi), "original_dpi": float(scan.dpi), "native_scale": ratio,
        "source_crop": tuple(map(int, actual_crop)),
        "trace_window_pixels_sha256": _pixels_sha256(gray),
        "prepared_window_pixels_sha256": window["pixels_sha256"],
        "mapping": "full_native_edge=(trace_work_edge+crop_origin)*native_scale",
    }
    wy, wx = np.nonzero(parent_work)
    bbox = (ox + int(wx.min()), oy + int(wy.min()),
            int(wx.max() - wx.min()) + 1, int(wy.max() - wy.min()) + 1)
    record = {
        "version": VERSION, "contract_sha256": CONTRACT_SHA256,
        "kind": "explicit_native_source_region",
        "classification": "EXPLICIT_COMPLETE_NATIVE_SOURCE_COMPONENT",
        "native_source_region_partition": True,
        "selection_id": selection["id"], "selection_manifest": manifest,
        "manifest_sha256": source_region_selection_digest(manifest),
        "source_identity": source_identity_record,
        "dpi": float(dpi), "native_dpi": float(scan.dpi), "native_scale": ratio,
        "origin_work_px": (ox, oy), "source_shape": (height, width),
        "native_shape": tuple(native.shape), "bbox": bbox,
        "source_runs_y_x0_x1": selection["working_parent_runs_y_x0_x1"],
        "native_source_runs_y_x0_x1": _runs(parent),
        "native_member_runs_y_x0_x1": selection["native_member_runs_y_x0_x1"],
        "native_residual_runs_y_x0_x1": _runs(residual),
        "native_foreign_runs_y_x0_x1": _runs(foreign),
        "source_pixels": int(parent_work.sum()), "native_source_pixels": int(parent.sum()),
        "native_member_pixels": int(member.sum()), "native_residual_pixels": int(residual.sum()),
        "native_foreign_pixels": int(foreign.sum()),
        "whole_parent_protected_source_pixels": 0,
        "whole_parent_previously_claimed_source_pixels": 0,
        "whole_parent_noncurrent_source_pixels": 0, "whole_parent_foreign_source_pixels": 0,
        "complete_native_component": True, "full_object_movable": False,
        "historical_identity": "NOT_PROVEN", "electrical_semantics": "NOT_INFERRED",
        "creates_connection": False, "automatic_selection": False,
        "selection_authority": "OPERATOR_SELECTED_WHOLE_OBSERVED_SOURCE_COMPONENT",
    }
    # The same writer preflight validates the complete exact-cell ledger before
    # handing off a single source pixel. Actual export uses its official frame.
    preflight_source_region(record, edge_transform=lambda x, y: (x, -y))
    old_paths = trace_binary(np.where(parent_work, 0, 255).astype(np.uint8))
    if not old_paths:
        raise ValueError("Explicit source parent has no retained boundary placeholder")
    placeholder = TracePath(tuple((x + ox, y + oy) for x, y in old_paths[0].points),
                            None, 0, 0)
    checkpoint(cancellation_token)
    output = visible_binary.copy()
    output[sl][parent_work] = 255
    review = {"version": VERSION, "status": "ACCEPTED_EXPLICIT_NATIVE_SOURCE_COMPONENT",
              "accepted_parents": 1, "accepted_members": 1,
              "manifest_sha256": record["manifest_sha256"],
              "selection_id": selection["id"], "source_identity": source_identity_record,
              "working_source_pixels": record["source_pixels"],
              "native_source_pixels": record["native_source_pixels"],
              "native_member_pixels": record["native_member_pixels"],
              "native_residual_pixels": record["native_residual_pixels"],
              "historical_identity": "NOT_PROVEN", "electrical_semantics": "NOT_INFERRED",
              "full_object_movable": False, "automatic_selection": False}
    return output, (placeholder,), (record,), review
