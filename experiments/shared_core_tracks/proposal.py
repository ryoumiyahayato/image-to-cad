"""Research-only cardinal source bands across retained shared cores.

No production/export contract is registered here.  Complete original bitonal
cross-sections propose a band and its retirement ledger *before* pen validation.
The skeleton is not used to grant source ownership.  Shared/superset sections,
their full-parent guards and all unselected source remain visible residual.
"""
from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.geometry.observed_label_frames import PEN_WIDTHS_HUNDREDTH_MM
from app.geometry.observed_open_strokes import _runs
from app.geometry.compound_straight_parts import (
    pixel_union_distance,
    rasterize_straight_pen,
    source_to_segment_distance,
)

VERSION = "cardinal-shared-core-tracks-research-v1"
CONTRACT = {
    "version": VERSION,
    "source": "registered-complete-bitonal-native-parent",
    "directions": ("horizontal", "vertical"),
    "proposal": "maximal-full-black-band-with-repeated-exact-cross-section",
    "shared": "strict-superset-section-and-source-width-guard-never-retired",
    "exclusive_sections_per_interval_min": 12,
    "exclusive_interval_length_mm_min": 2.0,
    "exclusive_interval_aspect_min": 8.0,
    "exclusive_intervals_min": 2,
    "pen_edge_shift_work_px_max": 0.25,
    "boundary_error_native_px_max": 1.0,
    "native_black_white_center_changes_max": 0,
    "guard_native_px": "max(2*scale,source_width+sqrt(.5)*scale,pen_width+sqrt(.5)*scale)",
    "exclusive_terminal_trim": "source_width/2+guard; strict endpoint inequalities",
    "selection": "source-span-descending-axis-bounds; no post-fit promotion",
    "geometric_contact": "OBSERVED_SOURCE_ONLY",
    "historical_object_identity": "NOT_PROVEN",
    "electrical_semantics": "NOT_INFERRED",
    "full_object_movable": False,
    "production_retirement_authorized": False,
}
CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(CONTRACT, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
MAX_WORK_PIXELS = 100_000
MAX_NATIVE_PIXELS = 1_000_000
MAX_PARENT_WORK_PIXELS = 8192
MAX_SECTION_KEYS = 4096
MAX_PROPOSED_BANDS = 512
MAX_CANDIDATE_KEY_COLUMNS = 2_000_000


def _hash(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _intervals(values: np.ndarray) -> tuple[tuple[int, int], ...]:
    edges = np.diff(np.r_[False, values, False].astype(np.int8))
    return tuple((int(a), int(b)) for a, b in
                 zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _source_mask(shape: tuple[int, int], axis: str, lo: int, hi: int,
                 start: int, stop: int) -> np.ndarray:
    mask = np.zeros(shape, bool)
    if axis == "horizontal":
        mask[lo:hi, start:stop] = True
    else:
        mask[start:stop, lo:hi] = True
    return mask


def _column_mask(parent: np.ndarray, axis: str, stations: np.ndarray) -> np.ndarray:
    return parent & (stations[None, :] if axis == "horizontal" else stations[:, None])


def _pen_samples(path: np.ndarray, width: float) -> np.ndarray:
    a, b = path
    edge = b-a
    length = float(np.linalg.norm(edge))
    tangent = edge/length
    normal = np.array((-tangent[1], tangent[0]))
    centers = np.linspace(a, b, max(3, int(math.ceil(length*4))+1))
    radius = width/2.
    angles = np.linspace(0., 2.*math.pi, max(65, int(math.ceil(width*math.pi*8))+1))
    caps = np.column_stack((np.cos(angles), np.sin(angles)))*radius
    square = np.linspace(-radius, radius, max(3, int(math.ceil(width*8))+1))
    return np.concatenate((
        centers, centers+normal*radius, centers-normal*radius,
        a+caps, b+caps,
        a-tangent*radius+square[:, None]*normal,
        b+tangent*radius+square[:, None]*normal,
    ))


def _propose(parent: np.ndarray, scale: int, dpi: float) -> tuple[list[dict], dict]:
    """Freeze raw bands and complete source ledgers without reading fit results."""
    proposals: list[dict] = []
    key_columns = 0
    stats = {"section_keys": 0, "singleton_section_keys_not_proposed": 0,
             "candidate_key_columns": 0, "raw_bands": 0}
    for axis in ("horizontal", "vertical"):
        source = parent if axis == "horizontal" else parent.T
        length = source.shape[1]
        occurrences: dict[tuple[int, int], list[int]] = {}
        for x in range(length):
            for lo, hi in _intervals(source[:, x]):
                occurrences.setdefault((lo, hi), []).append(x)
        stats["section_keys"] += len(occurrences)
        if stats["section_keys"] > MAX_SECTION_KEYS:
            raise ValueError("SOURCE_SECTION_KEY_BUDGET")
        white_prefix = np.vstack((np.zeros((1, length), np.int32),
                                  np.cumsum(~source, axis=0, dtype=np.int32)))
        for (lo, hi), positions in sorted(occurrences.items()):
            if len(positions) < 2:
                stats["singleton_section_keys_not_proposed"] += 1
                continue
            key_columns += length
            if key_columns > MAX_CANDIDATE_KEY_COLUMNS:
                raise ValueError("SOURCE_KEY_COLUMN_BUDGET")
            fully_black = white_prefix[hi] == white_prefix[lo]
            exact = np.zeros(length, bool)
            exact[positions] = True
            for start, stop in _intervals(fully_black):
                stats["raw_bands"] += 1
                if len(proposals) >= MAX_PROPOSED_BANDS:
                    raise ValueError("SOURCE_BAND_BUDGET")
                in_span = np.zeros(length, bool)
                in_span[start:stop] = True
                exclusive_stations = exact & in_span
                shared_stations = in_span & ~exact
                exclusive = _intervals(exclusive_stations)
                shared = _intervals(shared_stations)
                width = float(hi-lo)
                code = min(PEN_WIDTHS_HUNDREDTH_MM,
                           key=lambda c: (abs(c*dpi*scale/2540.-width), c))
                pen_width = code*dpi*scale/2540.
                collar = max(2.*scale, width+math.sqrt(.5)*scale,
                             pen_width+math.sqrt(.5)*scale)
                guard_steps = int(math.ceil(collar+width/2.))
                guarded_stations = np.zeros(length, bool)
                for a, b in shared:
                    guarded_stations[max(0, a-guard_steps):min(length, b+guard_steps)] = True
                shared_source = _column_mask(parent, axis, shared_stations)
                guard_source = _column_mask(parent, axis, guarded_stations) & ~shared_source
                supporting_band = _source_mask(parent.shape, axis, lo, hi, start, stop)
                retirement = np.zeros(parent.shape, bool)
                exclusive_source = np.zeros(parent.shape, bool)
                interval_records = []
                for a, b in exclusive:
                    section_source = _source_mask(parent.shape, axis, lo, hi, a, b)
                    exclusive_source |= section_source
                    lower = a+width/2.+collar
                    upper = b-1-width/2.-collar
                    first = int(math.floor(lower))+1
                    last_exclusive = int(math.ceil(upper))
                    first = max(a, min(b, first))
                    last_exclusive = max(first, min(b, last_exclusive))
                    interior = _source_mask(parent.shape, axis, lo, hi,
                                            first, last_exclusive)
                    interior &= ~_column_mask(parent, axis, guarded_stations)
                    retained_station_mask = np.any(
                        interior if axis == "horizontal" else interior.T, axis=0)
                    continuous = _intervals(retained_station_mask)
                    actual_n = int(np.count_nonzero(retained_station_mask))
                    effective_px = max(0., float(actual_n-1))
                    length_mm = effective_px*25.4/(dpi*scale)
                    aspect = effective_px/width
                    reason = "SOURCE_INTERVAL_ELIGIBLE"
                    if len(continuous) != 1:
                        reason = "NO_CONTIGUOUS_EXCLUSIVE_INTERIOR"
                    elif actual_n < 12:
                        reason = "FEWER_THAN_12_CONTINUOUS_NATIVE_SECTIONS"
                    elif length_mm < 2.0:
                        reason = "EXCLUSIVE_INTERIOR_SHORTER_THAN_2MM"
                    elif aspect < 8.0:
                        reason = "EXCLUSIVE_INTERIOR_ASPECT_BELOW_8"
                    interval_records.append({
                        "source_station_range": (a, b),
                        "native_source_runs_y_x0_x1": _runs(section_source),
                        "native_retired_source_runs_y_x0_x1": _runs(interior),
                        "native_retained_source_runs_y_x0_x1": _runs(section_source & ~interior),
                        "retired_station_intervals": continuous,
                        "independent_native_cross_sections": actual_n,
                        "effective_length_native_px": effective_px,
                        "effective_length_mm": length_mm,
                        "effective_length_width_ratio": aspect,
                        "reason": reason,
                    })
                    retirement |= interior
                exclusive_collar = exclusive_source & ~retirement
                mandatory_retained = shared_source | guard_source | exclusive_collar
                row = {
                    "band_id": len(proposals)+1, "axis": axis,
                    "normal_interval": (lo, hi), "station_interval": (start, stop),
                    "source_width_native_px": width,
                    "source_span_native_px": stop-start,
                    "exclusive_intervals": interval_records,
                    "shared_station_intervals": shared,
                    "guard_station_intervals": _intervals(guarded_stations),
                    "native_fitting_band_runs_y_x0_x1": _runs(supporting_band),
                    "native_exclusive_source_runs_y_x0_x1": _runs(exclusive_source),
                    "native_shared_core_source_runs_y_x0_x1": _runs(shared_source),
                    "native_guard_source_runs_y_x0_x1": _runs(guard_source),
                    "native_exclusive_collar_source_runs_y_x0_x1": _runs(exclusive_collar),
                    "native_mandatory_retained_source_runs_y_x0_x1": _runs(mandatory_retained),
                    "native_retired_source_runs_y_x0_x1": _runs(retirement),
                    "lineweight_hundredth_mm": int(code),
                    "native_pen_width_px": float(pen_width),
                    "maximum_pen_edge_shift_work_px": abs(pen_width-width)/(2.*scale),
                    "collar_native_px": collar, "guard_steps_native": guard_steps,
                    "source_precheck_reason": "SOURCE_BAND_ELIGIBLE",
                    "source_selected_before_fit": False,
                }
                if not shared:
                    row["source_precheck_reason"] = "NO_SHARED_SUPERSET_CORE"
                elif len(exclusive) < 2:
                    row["source_precheck_reason"] = "FEWER_THAN_TWO_EXCLUSIVE_INTERVALS"
                elif width < .5*scale or width > 4.*dpi*scale/100.:
                    row["source_precheck_reason"] = "SOURCE_WIDTH_OUTSIDE_R13_RANGE"
                elif row["maximum_pen_edge_shift_work_px"] > .25:
                    row["source_precheck_reason"] = "STANDARD_PEN_WIDTH_SHIFT"
                elif any(i["reason"] != "SOURCE_INTERVAL_ELIGIBLE" for i in interval_records):
                    row["source_precheck_reason"] = "INELIGIBLE_EXCLUSIVE_INTERVAL"
                elif np.any(retirement & mandatory_retained):
                    row["source_precheck_reason"] = "SOURCE_LEDGER_OVERLAP"
                proposals.append(row)
    stats["candidate_key_columns"] = key_columns
    # Resolve source promises before pen evaluation; rejected fits do not promote
    # any conflicting alternative later in this fixed selection.
    consumed = np.zeros(parent.shape, bool)
    retained = np.zeros(parent.shape, bool)
    eligible = [r for r in proposals if r["source_precheck_reason"] == "SOURCE_BAND_ELIGIBLE"]
    eligible.sort(key=lambda r: (-r["source_span_native_px"], r["axis"],
                                r["normal_interval"], r["station_interval"]))
    for rank, row in enumerate(eligible, 1):
        retirement = _mask(row["native_retired_source_runs_y_x0_x1"], parent.shape)
        preserve = _mask(row["native_mandatory_retained_source_runs_y_x0_x1"], parent.shape)
        row["source_selection_rank"] = rank
        if np.any(retirement & (consumed | retained)) or np.any(preserve & consumed):
            row["source_precheck_reason"] = "SOURCE_FIXED_CANDIDATE_CONFLICT"
            continue
        row["source_selected_before_fit"] = True
        consumed |= retirement
        retained |= preserve
    return proposals, stats


def _mask(runs: Sequence[Sequence[int]], shape: tuple[int, int]) -> np.ndarray:
    result = np.zeros(shape, bool)
    for y, start, stop in runs:
        result[y, start:stop] = True
    return result


def _validate_pen(row: dict, parent: np.ndarray, foreign: np.ndarray,
                  forbidden: np.ndarray, scale: int, dpi: float) -> tuple[dict | None, str, dict]:
    """One phase-fixed cardinal LINE; the frozen retirement is never edited."""
    lo, hi = row["normal_interval"]
    start, stop = row["station_interval"]
    width = row["source_width_native_px"]
    center = (lo+hi-1)/2.
    a = start+width/2.
    b = stop-1-width/2.
    if a >= b:
        return None, "NO_FINITE_AXIS_LINE", {}
    path = np.array(((a, center), (b, center)) if row["axis"] == "horizontal"
                    else ((center, a), (center, b)), dtype=float)
    pen_width = row["native_pen_width_px"]
    radius = pen_width/2.
    lower = path.min(axis=0)-radius
    upper = path.max(axis=0)+radius
    if np.any(lower <= -.5) or np.any(upper >= np.asarray(parent.shape[::-1])-.5):
        return None, "PEN_REACHES_NATIVE_TILE_BOUNDARY", {}
    retirement = _mask(row["native_retired_source_runs_y_x0_x1"], parent.shape)
    fitting = _mask(row["native_fitting_band_runs_y_x0_x1"], parent.shape)
    source_points = np.column_stack(np.nonzero(fitting)[::-1]).astype(float)
    complete_source = np.column_stack(np.nonzero(parent)[::-1]).astype(float)
    forward = max(0., float(source_to_segment_distance(source_points, *path).max())-radius)
    reverse = pixel_union_distance(_pen_samples(path, pen_width), complete_source)
    audit = {"source_to_pen_error_native_px": forward,
             "pen_to_source_error_native_px": reverse, "caps": []}
    if forward > 1.:
        return None, "SOURCE_TO_PEN_BOUNDARY", audit
    if reverse > 1.:
        return None, "PEN_TO_SOURCE_BOUNDARY", audit
    residual = parent & ~retirement
    for cap, name in ((1, "round"), (2, "butt"), (3, "square")):
        drawn = rasterize_straight_pen(parent.shape, path, pen_width, cap)
        uncovered = int(np.count_nonzero(retirement & ~drawn))
        new_ink = int(np.count_nonzero(drawn & ~parent))
        missing = int(np.count_nonzero(parent & ~(residual | drawn)))
        foreign_count = int(np.count_nonzero(drawn & foreign))
        forbidden_count = int(np.count_nonzero(drawn & forbidden))
        item = {"cap_style": name, "uncovered_own_retired_centers": uncovered,
                "new_ink_center_pixels": new_ink, "missing_ink_center_pixels": missing,
                "foreign_center_contacts": foreign_count,
                "protected_working_cell_center_contacts": forbidden_count}
        audit["caps"].append(item)
        if uncovered:
            return None, "OWN_RETIRED_SOURCE_NOT_COVERED", audit
        if new_ink or missing:
            return None, "NATIVE_BLACK_WHITE_CENTERS_CHANGED", audit
        if foreign_count or forbidden_count:
            return None, "FOREIGN_OR_PROTECTED_CENTER_CONTACT", audit
    work_path = (path+.5)/scale-.5
    candidate = {
        "part_id": row["band_id"], "axis": row["axis"],
        "native_points_px": tuple(map(tuple, path.tolist())),
        "points_px": tuple(map(tuple, work_path.tolist())),
        "native_retired_source_runs_y_x0_x1": row["native_retired_source_runs_y_x0_x1"],
        "native_retired_source_pixels": int(retirement.sum()),
        "native_supporting_source_runs_y_x0_x1": row["native_fitting_band_runs_y_x0_x1"],
        "native_mandatory_retained_source_runs_y_x0_x1":
            row["native_mandatory_retained_source_runs_y_x0_x1"],
        "native_shared_core_source_runs_y_x0_x1": row["native_shared_core_source_runs_y_x0_x1"],
        "native_guard_source_runs_y_x0_x1": row["native_guard_source_runs_y_x0_x1"],
        "native_exclusive_collar_source_runs_y_x0_x1":
            row["native_exclusive_collar_source_runs_y_x0_x1"],
        "exclusive_intervals": row["exclusive_intervals"],
        "native_pen_width_px": pen_width,
        "lineweight_hundredth_mm": row["lineweight_hundredth_mm"],
        "source_width_native_px": width, "width_px": width/scale,
        "length_px": float(np.linalg.norm(path[1]-path[0]))/scale,
        "collar_native_px": row["collar_native_px"],
        "source_to_pen_error_px": forward/scale, "pen_to_source_error_px": reverse/scale,
        "maximum_measured_pen_edge_shift_px": row["maximum_pen_edge_shift_work_px"],
        "source_band_id": row["band_id"], "source_manifest_sha256": None,
        "geometric_contact": "OBSERVED_SOURCE_ONLY",
        "historical_object_identity": "NOT_PROVEN", "electrical_semantics": "NOT_INFERRED",
        "full_object_movable": False, "production_retirement_authorized": False,
        "continuous_geometry_and_joint_contact_status": "NOT_YET_INDEPENDENTLY_VALIDATED",
        "native_pen_audit": audit,
        "join_styles": "NO_INTERNAL_JOIN_IN_TWO_VERTEX_LINE",
    }
    return candidate, "RESEARCH_PEN_AND_CENTER_CHECKS_PASSED", audit


def recover_shared_core_tracks(
    gray: np.ndarray, component: np.ndarray, foreign: np.ndarray | None = None, *,
    native_gray: np.ndarray | None = None, native_scale: int | None = None,
    dpi: float = 100., binary: np.ndarray | None = None,
    visible_binary: np.ndarray | None = None,
    protected_masks: Sequence[np.ndarray | None] = (),
) -> dict:
    """Propose source-frozen cardinal tracks in one complete working parent.

    Required gray/binary/visible arrays use black below 128 (gray evidence <254).
    The native array must be bitonal and match the registered BOX observation.
    All returned runs are native-tile-local.  No input array or DXF is modified.
    Candidates are research proposals, never production retirement authority.
    """
    result: dict[str, Any] = {
        "version": VERSION, "contract_sha256": CONTRACT_SHA256,
        "status": "REJECTED", "reason": None, "candidates": [], "decisions": [],
        "source_proposed_bands": [], "no_mutation": True,
        "source_ledger_status": "NOT_BOUND_INPUT_REJECTED",
        "geometric_contact": "OBSERVED_SOURCE_ONLY",
        "historical_object_identity": "NOT_PROVEN", "electrical_semantics": "NOT_INFERRED",
        "full_object_movable": False, "production_retirement_authorized": False,
        "continuous_geometry_and_joint_contact_status": "NOT_YET_INDEPENDENTLY_VALIDATED",
    }

    def reject(reason: str) -> dict:
        result["reason"] = reason
        return result

    if (not isinstance(gray, np.ndarray) or gray.dtype != np.uint8 or gray.ndim != 2
            or not isinstance(component, np.ndarray) or component.dtype != np.bool_
            or component.shape != gray.shape
            or isinstance(dpi, bool) or not isinstance(dpi, (int, float, np.number))
            or not math.isfinite(float(dpi)) or dpi <= 0):
        return reject("WORKING_INPUT_CONTRACT")
    if gray.size > MAX_WORK_PIXELS or int(component.sum()) > MAX_PARENT_WORK_PIXELS:
        return reject("WORKING_RESOURCE_BUDGET")
    if binary is None or visible_binary is None:
        return reject("SOURCE_STATE_REQUIRED")
    if any(not isinstance(a, np.ndarray) or a.dtype != np.uint8 or a.shape != gray.shape
           for a in (binary, visible_binary)):
        return reject("SOURCE_STATE_CONTRACT")
    if foreign is None:
        foreign = (gray < 254) & ~component
    if not isinstance(foreign, np.ndarray) or foreign.shape != gray.shape:
        return reject("FOREIGN_MASK_CONTRACT")
    if any(p is not None and (not isinstance(p, np.ndarray) or p.shape != gray.shape)
           for p in protected_masks):
        return reject("PROTECTION_MASK_CONTRACT")
    protected = np.asarray(foreign, bool).copy()
    for p in protected_masks:
        if p is not None:
            protected |= p > 0
    if np.any(component & protected):
        return reject("WHOLE_PARENT_PROTECTED_OR_FOREIGN")
    if not component.any() or np.any(component & ~(gray < 254)):
        return reject("PARENT_SOURCE_NOT_OBSERVED")
    if (component[0].any() or component[-1].any()
            or component[:, 0].any() or component[:, -1].any()):
        return reject("PARENT_TOUCHES_WORKING_TILE_BOUNDARY")
    _, labels = cv2.connectedComponents(np.uint8(gray < 254), connectivity=8)
    y, x = np.argwhere(component)[0]
    if not np.array_equal(labels == labels[y, x], component):
        return reject("WORKING_PARENT_NOT_COMPLETE_CONNECTED_COMPONENT")
    if np.any(component & (binary >= 128)):
        return reject("WHOLE_PARENT_SOURCE_NOT_CURRENT")
    if np.any(component & (visible_binary >= 128)):
        return reject("WHOLE_PARENT_ALREADY_CLAIMED")
    if (isinstance(native_scale, bool) or not isinstance(native_scale, (int, np.integer))
            or not 2 <= int(native_scale) <= 16):
        return reject("ISOTROPIC_INTEGER_NATIVE_SCALE_REQUIRED")
    scale = int(native_scale)
    if (not isinstance(native_gray, np.ndarray) or native_gray.ndim != 2
            or native_gray.dtype != np.uint8
            or native_gray.shape != tuple(scale*n for n in gray.shape)):
        return reject("NATIVE_GRID_SHAPE_CONTRACT")
    if native_gray.size > MAX_NATIVE_PIXELS:
        return reject("NATIVE_RESOURCE_BUDGET")
    if not np.isin(native_gray, (0, 255)).all():
        return reject("ORIGINAL_SCAN_NOT_BITONAL")
    down = np.array(Image.fromarray(native_gray).resize(
        (gray.shape[1], gray.shape[0]), Image.Resampling.BOX))
    if (np.max(np.abs(down.astype(np.int16)-gray.astype(np.int16))) > 1
            or not np.array_equal(down < 254, gray < 254)):
        return reject("ORIGINAL_SCAN_REGISTRATION_MISMATCH")
    parent = np.repeat(np.repeat(component, scale, axis=0), scale, axis=1) & (native_gray == 0)
    result["native_source_runs_y_x0_x1"] = _runs(parent)
    result["source_ledger_status"] = "BOUND_COMPLETE_NATIVE_PARENT"
    result["native_residual_runs_y_x0_x1"] = _runs(parent)
    result["native_source_pixels"] = int(parent.sum())
    result["native_residual_pixels"] = int(parent.sum())
    result["native_retired_source_pixels"] = 0
    if (parent[0].any() or parent[-1].any() or parent[:, 0].any() or parent[:, -1].any()):
        return reject("PARENT_TOUCHES_NATIVE_TILE_BOUNDARY")
    _, native_labels = cv2.connectedComponents(np.uint8(native_gray == 0), connectivity=8)
    selected_ids = np.unique(native_labels[parent])
    if 0 in selected_ids or not np.array_equal(np.isin(native_labels, selected_ids), parent):
        return reject("NATIVE_PARENT_COMPONENTS_NOT_COMPLETE")
    native_foreign = (native_gray == 0) & ~parent
    native_forbidden = np.repeat(np.repeat(protected, scale, axis=0), scale, axis=1)
    inputs = (gray, component, np.asarray(foreign), binary, visible_binary, native_gray, *(
        p for p in protected_masks if p is not None))
    before = tuple(_hash(a) for a in inputs)
    result["source_identity"] = {
        "gray_pixels_sha256": _hash(gray), "component_sha256": _hash(component),
        "foreign_sha256": _hash(np.asarray(foreign)),
        "binary_sha256": _hash(binary), "visible_binary_sha256": _hash(visible_binary),
        "native_pixels_sha256": _hash(native_gray),
        "protected_masks_sha256": tuple(_hash(p) for p in protected_masks if p is not None),
        "working_shape": gray.shape, "native_shape": native_gray.shape,
        "working_dpi": float(dpi), "native_scale": scale,
    }
    try:
        bands, budget = _propose(parent, scale, float(dpi))
    except ValueError as exc:
        result["input_arrays_unchanged"] = before == tuple(_hash(a) for a in inputs)
        return reject(str(exc))
    # Freeze the complete source-only proposal and selection before any LINE check.
    manifest = {"contract": CONTRACT, "contract_sha256": CONTRACT_SHA256,
                "source_identity": result["source_identity"], "bands": bands,
                "budget": budget}
    manifest_hash = _canonical_hash(manifest)
    result["proposal_manifest_sha256"] = manifest_hash
    result["source_proposal_manifest"] = manifest
    result["source_proposed_bands"] = bands
    result["source_budget"] = budget
    retired_union = np.zeros(parent.shape, bool)
    for band in bands:
        decision = {"band_id": band["band_id"], "axis": band["axis"],
                    "decision": "RETAINED", "reason": band["source_precheck_reason"]}
        result["decisions"].append(decision)
        if not band["source_selected_before_fit"]:
            continue
        candidate, reason, audit = _validate_pen(
            band, parent, native_foreign, native_forbidden, scale, float(dpi))
        decision["reason"] = reason
        decision["pen_audit"] = audit
        if candidate is None:
            continue
        candidate["source_manifest_sha256"] = manifest_hash
        candidate["version"] = VERSION
        candidate["contract_sha256"] = CONTRACT_SHA256
        result["candidates"].append(candidate)
        retirement = _mask(candidate["native_retired_source_runs_y_x0_x1"], parent.shape)
        retired_union |= retirement
        decision["decision"] = "RESEARCH_CANDIDATE"
        decision["native_retired_source_pixels"] = int(retirement.sum())
    # All candidates individually preserve native centers.  This ledger is still
    # only a research result; continuous/joint-contact auditing is separate.
    residual = parent & ~retired_union
    result["native_residual_runs_y_x0_x1"] = _runs(residual)
    result["native_residual_pixels"] = int(residual.sum())
    result["native_retired_source_pixels"] = int(retired_union.sum())
    result["source_partition_exact"] = bool(
        not np.any(residual & retired_union) and np.array_equal(residual | retired_union, parent))
    result["input_arrays_unchanged"] = before == tuple(_hash(a) for a in inputs)
    if not result["input_arrays_unchanged"]:
        raise AssertionError("Research proposal unexpectedly mutated an input")
    result["status"] = "RESEARCH_CANDIDATES" if result["candidates"] else "NO_SUPPORTED_TRACKS"
    result["reason"] = ("RESEARCH_PEN_AND_CENTER_CHECKS_PASSED" if result["candidates"]
                        else "NO_CARDINAL_SHARED_CORE_TRACK_PASSED")
    return result

