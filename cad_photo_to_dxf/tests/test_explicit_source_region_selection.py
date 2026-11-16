"""Explicit source selection identities, whole-parent guards, and retirement."""
from __future__ import annotations

import copy
import hashlib
import json

import cv2
import numpy as np
import pytest

from app.geometry.observed_source_regions import (
    recover_explicit_native_source_regions,
    source_region_input_identity,
)
from app.geometry.scan_dust import RegisteredOriginalScan
from app.geometry.source_region_selection import (
    MAX_MANIFEST_BYTES,
    VERSION,
    canonical_source_region_selection,
    parse_source_region_selection,
    source_region_selection_digest,
)


def _digest(image):
    return hashlib.sha256(np.ascontiguousarray(image)).hexdigest()


def _runs(mask):
    rows = []
    for y, row in enumerate(mask):
        changes = np.diff(np.r_[False, row, False].astype(np.int8))
        rows.extend([y, int(a), int(b)] for a, b in zip(
            np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))
    return rows


def _fixture(*, crop=False, full_halo_contact=False, corner_member=False):
    if full_halo_contact:
        ratio = 16
        native = np.full((64, 64), 255, np.uint8)
        native[20, 30:33] = 0
        native[28, 20:22] = 0
        origin, shape = [0, 0], [4, 4]
        member_full = np.zeros_like(native, bool)
        member_full[20, 30:32] = True
    else:
        ratio = 2
        native = np.full((48, 48), 255, np.uint8)
        native[20, 14:24] = 0
        native[22, 14:24] = 0
        native[8, 8] = 0  # A separate non-target component outside the window.
        origin, shape = [4, 7], [9, 12]
        member_full = np.zeros_like(native, bool)
        member_full[20, 14:24] = True
        if corner_member:
            native[20, 14:24] = 255
            native[20, 14] = native[21, 15] = 0
            native[22, 14:24] = 255
            native[23, 14:24] = 0
            member_full[:] = False
            member_full[20, 14] = member_full[21, 15] = True
    full = cv2.resize(native, (native.shape[1] // ratio, native.shape[0] // ratio),
                      interpolation=cv2.INTER_AREA)
    crop_bounds = [2, 3, 20, 21] if crop else [0, 0, full.shape[1], full.shape[0]]
    left, top, right, bottom = crop_bounds
    gray = full[top:bottom, left:right].copy()
    origin = [origin[0] - left, origin[1] - top]
    ox, oy = origin
    height, width = shape
    local_gray = gray[oy:oy + height, ox:ox + width]
    parent = local_gray < 254
    full_x, full_y = (left + ox) * ratio, (top + oy) * ratio
    member = member_full[full_y:full_y + height * ratio, full_x:full_x + width * ratio]
    binary = np.where(gray < 254, 0, 255).astype(np.uint8)
    input_identity = source_region_input_identity(full, 100.)
    manifest = {
        "version": VERSION, "input": input_identity,
        "original": {"pixels_sha256": _digest(native), "shape_yx": list(native.shape),
                     "dtype": "uint8", "dpi": float(100 * ratio)},
        "crop_work_px": crop_bounds, "native_scale": ratio,
        "prepared_window": {"origin_work_px": origin, "shape_yx": shape,
                            "pixels_sha256": _digest(local_gray), "dtype": "uint8"},
        "selection": {"id": "explicit-source-toy", "working_parent_runs_y_x0_x1": _runs(parent),
                      "native_member_runs_y_x0_x1": _runs(member)},
    }
    kwargs = dict(selection_manifest=manifest, registered_original_scan=RegisteredOriginalScan(
        native, float(100 * ratio), ratio), dpi=100., source_identity=input_identity,
        source_crop=tuple(crop_bounds) if crop else None)
    return gray, binary, kwargs


def test_manifest_canonical_identity_ignores_json_layout_but_binds_selection():
    _, _, kwargs = _fixture()
    manifest = kwargs["selection_manifest"]
    normalized = parse_source_region_selection(manifest)
    assert normalized == manifest and normalized is not manifest
    encoded = json.dumps(manifest, indent=4)
    assert canonical_source_region_selection(encoded) == canonical_source_region_selection(manifest)
    assert source_region_selection_digest(encoded) == source_region_selection_digest(normalized)
    altered = copy.deepcopy(manifest)
    altered["selection"]["id"] = "different-explicit-selection"
    assert source_region_selection_digest(altered) != source_region_selection_digest(manifest)
    normalized["input"]["shape_yx"][0] = 999
    assert manifest["input"]["shape_yx"][0] == 24


@pytest.mark.parametrize("invalid", ["unknown", "version", "bool_scale", "dtype", "dpi",
                                    "crop", "parent_repeat", "member_adjacent", "run_bool",
                                    "run_oob", "run_empty", "window_budget", "parent_budget"])
def test_manifest_rejects_invalid_or_noncanonical_data_before_raster_allocation(invalid):
    _, _, kwargs = _fixture()
    manifest = copy.deepcopy(kwargs["selection_manifest"])
    if invalid == "unknown":
        manifest["automatic_search"] = True
    elif invalid == "version":
        manifest["version"] = "unknown"
    elif invalid == "bool_scale":
        manifest["native_scale"] = True
    elif invalid == "dtype":
        manifest["input"]["dtype"] = "uint16"
    elif invalid == "dpi":
        manifest["original"]["dpi"] = float("nan")
    elif invalid == "crop":
        manifest["crop_work_px"][2] = 999
    elif invalid == "parent_repeat":
        rows = manifest["selection"]["working_parent_runs_y_x0_x1"]
        rows.insert(1, list(rows[0]))
    elif invalid == "member_adjacent":
        y, a, b = manifest["selection"]["native_member_runs_y_x0_x1"][0]
        manifest["selection"]["native_member_runs_y_x0_x1"] = [[y, a, a + 1], [y, a + 1, b]]
    elif invalid == "run_bool":
        manifest["selection"]["native_member_runs_y_x0_x1"][0][0] = True
    elif invalid == "run_oob":
        manifest["selection"]["native_member_runs_y_x0_x1"][0][2] = 999
    elif invalid == "run_empty":
        manifest["selection"]["native_member_runs_y_x0_x1"] = []
    else:
        manifest["input"]["shape_yx"] = [400, 400]
        manifest["original"]["shape_yx"] = [800, 800]
        manifest["crop_work_px"] = [0, 0, 400, 400]
        manifest["prepared_window"]["origin_work_px"] = [0, 0]
        manifest["prepared_window"]["shape_yx"] = [400, 400] if invalid == "window_budget" else [100, 100]
        if invalid == "parent_budget":
            manifest["selection"]["working_parent_runs_y_x0_x1"] = [[y, 0, 100] for y in range(83)]
    with pytest.raises(ValueError):
        parse_source_region_selection(manifest)


def test_manifest_rejects_duplicate_keys_and_byte_budget():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_source_region_selection('{"version":1,"version":2}')
    with pytest.raises(ValueError, match="byte budget"):
        parse_source_region_selection(" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ValueError, match="Nonfinite"):
        parse_source_region_selection('{"anything":NaN}')


def test_selected_complete_component_retires_whole_parent_only_and_preserves_inputs():
    gray, binary, kwargs = _fixture()
    native = kwargs["registered_original_scan"].pixels
    before = (gray.copy(), binary.copy(), native.copy())
    output, paths, records, review = recover_explicit_native_source_regions(gray, binary, binary, **kwargs)
    assert len(paths) == len(records) == 1
    record = records[0]
    assert record["native_source_region_partition"] is True
    assert record["native_source_pixels"] == 20
    assert record["native_member_pixels"] == record["native_residual_pixels"] == 10
    assert record["source_pixels"] == 10
    assert review["accepted_parents"] == review["accepted_members"] == 1
    assert np.all(output[10:12, 7:12] == 255)
    untouched = np.ones_like(binary, bool)
    untouched[10:12, 7:12] = False
    np.testing.assert_array_equal(output[untouched], binary[untouched])
    for actual, expected in zip((gray, binary, native), before):
        np.testing.assert_array_equal(actual, expected)
    assert record["source_identity"]["source_crop"] == (0, 0, 24, 24)
    assert record["manifest_sha256"] == source_region_selection_digest(kwargs["selection_manifest"])


def test_cropped_selection_keeps_full_input_binding_and_window_local_origin():
    gray, binary, kwargs = _fixture(crop=True)
    _, paths, records, _ = recover_explicit_native_source_regions(gray, binary, binary, **kwargs)
    record = records[0]
    assert record["origin_work_px"] == (2, 4)
    assert record["source_identity"]["source_crop"] == (2, 3, 20, 21)
    assert record["source_identity"]["input_shape"] == (24, 24)
    assert record["bbox"] == (5, 7, 5, 2)
    assert min(x for x, _ in paths[0].points) == 5


@pytest.mark.parametrize("reason", ["protected_residual", "claimed_residual", "noncurrent_residual",
                                   "input_hash", "native_hash", "prepared_hash", "crop", "dpi",
                                   "missing_native", "nonbitonal", "parent_partial", "member_partial",
                                   "member_equals_parent", "parent_edge", "protection_dtype"])
def test_invalid_source_or_whole_parent_guards_raise_without_mutation(reason):
    gray, binary, kwargs = _fixture()
    visible = binary.copy()
    protected = np.zeros_like(binary)
    manifest = kwargs["selection_manifest"]
    kwargs["protected_masks"] = (protected,)
    if reason == "protected_residual":
        protected[11, 8] = 1
    elif reason == "claimed_residual":
        visible[11, 8] = 255
    elif reason == "noncurrent_residual":
        binary[11, 8] = 255
    elif reason == "input_hash":
        kwargs["source_identity"] = {**kwargs["source_identity"], "pixels_sha256": "f" * 64}
    elif reason == "native_hash":
        manifest["original"]["pixels_sha256"] = "f" * 64
    elif reason == "prepared_hash":
        manifest["prepared_window"]["pixels_sha256"] = "f" * 64
    elif reason == "crop":
        kwargs["source_crop"] = (0, 0, 23, 24)
    elif reason == "dpi":
        kwargs["dpi"] = 101.
    elif reason == "missing_native":
        kwargs["registered_original_scan"] = None
    elif reason == "nonbitonal":
        kwargs["registered_original_scan"].pixels[0, 0] = 1
        manifest["original"]["pixels_sha256"] = _digest(kwargs["registered_original_scan"].pixels)
    elif reason == "parent_partial":
        manifest["selection"]["working_parent_runs_y_x0_x1"].pop()
    elif reason == "member_partial":
        manifest["selection"]["native_member_runs_y_x0_x1"][0][2] -= 1
    elif reason == "member_equals_parent":
        manifest["selection"]["native_member_runs_y_x0_x1"].append([8, 6, 16])
    elif reason == "parent_edge":
        manifest["selection"]["working_parent_runs_y_x0_x1"].insert(0, [0, 0, 1])
    elif reason == "protection_dtype":
        kwargs["protected_masks"] = (protected.astype(float),)
    inputs = (gray, binary, visible, protected)
    before = tuple(a.copy() for a in inputs)
    with pytest.raises(ValueError):
        recover_explicit_native_source_regions(gray, binary, visible, **kwargs)
    for actual, expected in zip(inputs, before):
        np.testing.assert_array_equal(actual, expected)


def test_member_complete_in_parent_but_connected_to_full_native_foreign_source_is_rejected():
    gray, binary, kwargs = _fixture(full_halo_contact=True)
    # One foreign native cell reduces to gray 254, outside the declared <254 W.
    assert gray[1, 2] == 254
    with pytest.raises(ValueError, match="incomplete in the full native source"):
        recover_explicit_native_source_regions(gray, binary, binary, **kwargs)


def test_eight_connected_corner_only_member_is_rejected():
    gray, binary, kwargs = _fixture(corner_member=True)
    with pytest.raises(ValueError, match="Corner-only"):
        recover_explicit_native_source_regions(gray, binary, binary, **kwargs)


def test_writer_preflight_failure_cannot_retire_source(monkeypatch):
    from app.export import source_region_entities

    gray, binary, kwargs = _fixture()
    before = binary.copy()

    def reject(*_args, **_kwargs):
        raise ValueError("injected export contract rejection")

    monkeypatch.setattr(source_region_entities, "preflight_source_region", reject)
    with pytest.raises(ValueError, match="injected export"):
        recover_explicit_native_source_regions(gray, binary, binary, **kwargs)
    np.testing.assert_array_equal(binary, before)


@pytest.mark.parametrize("conflict", ["pdf", "compound", "color_input"])
def test_production_entry_rejects_unsupported_modes_before_preparation(monkeypatch, conflict):
    from app.geometry import optimized_trace

    gray, _, kwargs = _fixture()
    contract = {"experimental_native_source_region_manifest": kwargs["selection_manifest"]}
    calls = []
    monkeypatch.setattr(optimized_trace, "prepare_scan_page", lambda *_a, **_k: calls.append(True))
    options = {"processing_contract": contract, "enable_ocr": False, "source_dpi": 100.}
    if conflict == "pdf":
        options["pdf_geometry"] = object()
    elif conflict == "compound":
        contract["experimental_compound_strokes"] = True
    else:
        gray = np.repeat(gray[:, :, None], 3, axis=2)
    with pytest.raises(ValueError):
        optimized_trace.trace_image_optimized(gray, **options)
    assert calls == []
