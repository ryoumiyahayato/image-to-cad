"""Opt-in source partitioning for native-supported straight compound members.

An entire parent must remain unclaimed and unprotected.  Its working contour is
retired only after the exporter validates an exact native source ledger: native
LINE members, retained cut interfaces, and unresolved source-cell HATCH.  Nothing
here asserts an electrical connection or a complete movable engineering object.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any

import cv2
import numpy as np

from app.core.cancellation import checkpoint
from app.core.trace_types import TracePath
from app.geometry.observed_open_strokes import _runs
from app.geometry.raster_trace import trace_binary

VERSION = "registered-native-compound-parts-v1"
MAX_COMPONENT_PIXELS = 8192
MAX_LOCAL_PIXELS = 100000
MAX_NATIVE_LOCAL_PIXELS = 1000000
MAX_CHECKS = 512
MAX_TOTAL_LOCAL_PIXELS = 4000000


def _serial(value):
    """Keep the auditable scalar/run proof; full-size arrays stay ephemeral."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _serial(v) for k, v in value.items() if not isinstance(v, np.ndarray)}
    if isinstance(value, (list, tuple)):
        return tuple(_serial(v) for v in value)
    return value


def recover_observed_compound_strokes(
    gray: np.ndarray, binary: np.ndarray, visible_binary: np.ndarray, *,
    protected_masks: Sequence[np.ndarray | None] = (), dpi: float = 100.,
    registered_original_scan=None, source_crop=None,
    source_identity: Mapping[str, object] | None = None, cancellation_token=None,
) -> tuple[np.ndarray, tuple[TracePath, ...], tuple[dict, ...], dict]:
    review: dict[str, Any] = dict(
        version=VERSION, status="EXPERIMENTAL", accepted_parents=0, accepted_parts=0,
        working_source_pixels=0, native_source_pixels=0, native_retired_source_pixels=0,
        native_residual_pixels=0, decisions=[], creates_connection=False,
        electrical_semantics="NOT_INFERRED", full_object_movable=False,
        resource_limits=dict(max_component_pixels=MAX_COMPONENT_PIXELS,
            max_local_pixels=MAX_LOCAL_PIXELS, max_native_local_pixels=MAX_NATIVE_LOCAL_PIXELS,
            max_checks=MAX_CHECKS, max_total_local_pixels=MAX_TOTAL_LOCAL_PIXELS),
    )
    unchanged = lambda: (visible_binary, (), (), review)
    if (not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.dtype != np.uint8
            or not isinstance(binary, np.ndarray) or binary.shape != gray.shape
            or not isinstance(visible_binary, np.ndarray) or visible_binary.shape != gray.shape
            or binary.dtype != np.uint8 or visible_binary.dtype != np.uint8
            or not math.isfinite(dpi) or dpi <= 0
            or any(p is not None and p.shape != gray.shape for p in protected_masks)):
        review["status"] = "SKIPPED_INPUT_CONTRACT"
        return unchanged()
    if registered_original_scan is None:
        review["status"] = "SKIPPED_ORIGINAL_SCAN_REQUIRED"
        return unchanged()
    scan = registered_original_scan
    ratio = scan.ratio
    if (isinstance(ratio, bool) or not isinstance(ratio, (int, np.integer))
            or not 2 <= ratio <= 16 or scan.pixels.dtype != np.uint8
            or scan.pixels.ndim != 2 or not math.isfinite(scan.dpi)
            or abs(float(scan.dpi)-float(dpi)*ratio) > .01):
        review["status"] = "SKIPPED_NATIVE_GRID_CONTRACT"
        return unchanged()
    ratio = int(ratio)
    full_h, full_w = scan.pixels.shape
    crop = source_crop or (0, 0, full_w//ratio, full_h//ratio)
    if (len(crop) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in crop)
            or not 0 <= crop[0] < crop[2] <= full_w//ratio
            or not 0 <= crop[1] < crop[3] <= full_h//ratio
            or (crop[3]-crop[1], crop[2]-crop[0]) != gray.shape):
        review["status"] = "SKIPPED_NATIVE_CROP_CONTRACT"
        return unchanged()
    left, top, _right, _bottom = map(int, crop)
    identity = dict(source_identity or {})
    identity.update(
        trace_window_pixels_sha256=hashlib.sha256(gray.tobytes()).hexdigest(),
        original_pixels_sha256=hashlib.sha256(scan.pixels.tobytes()).hexdigest(),
        original_shape=tuple(map(int, scan.pixels.shape)), original_dpi=float(scan.dpi),
        working_dpi=float(dpi), source_crop=tuple(map(int, crop)), native_scale=ratio,
        mapping="full_native=(local_work+crop_origin+0.5)*native_scale-0.5",
    )
    review["source_identity"] = identity
    from app.export.compound_stroke_entities import validate_compound_stroke_record
    from app.geometry.compound_straight_parts import recover_short_straight_parts
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(gray < 254), connectivity=8)
    paths, records = [], []
    accepted_pen_envelopes = []
    output = visible_binary
    budget = MAX_TOTAL_LOCAL_PIXELS
    pad = max(6, int(math.ceil(4*dpi/100.))+1)
    # This is a parent resource filter, not the short member's geometry gate.
    minimum_parent_span = 10.*dpi/25.4*.9
    for label in range(1, count):
        checkpoint(cancellation_token)
        x, y, w, h, area = map(int, stats[label])
        if max(w, h) < minimum_parent_span or area < minimum_parent_span:
            continue
        size = (w+2*pad)*(h+2*pad)
        if (area > MAX_COMPONENT_PIXELS or size > MAX_LOCAL_PIXELS
                or size*ratio**2 > MAX_NATIVE_LOCAL_PIXELS):
            continue
        item = dict(component_id=label, bbox=(x, y, w, h), source_pixels=area,
                    decision="RETAINED")
        review["decisions"].append(item)
        if len(review["decisions"]) > MAX_CHECKS or budget < size:
            item["reason"] = "RESOURCE_BUDGET"
            break
        budget -= size
        if x < pad or y < pad or x+w+pad > gray.shape[1] or y+h+pad > gray.shape[0]:
            item["reason"] = "PAGE_OR_CROP_EDGE_COMPONENT"
            continue
        sl = np.s_[y-pad:y+h+pad, x-pad:x+w+pad]
        component = labels[sl] == label
        protected = np.zeros(component.shape, bool)
        for mask in protected_masks:
            if mask is not None:
                protected |= mask[sl] > 0
        if np.any(component & protected):
            item["reason"] = "WHOLE_PARENT_PROTECTED_OR_SHARED"
            continue
        if np.any(component & (binary[sl] >= 128)):
            item["reason"] = "WHOLE_PARENT_SOURCE_NOT_CURRENT"
            continue
        if np.any(component & (visible_binary[sl] >= 128)):
            item["reason"] = "WHOLE_PARENT_ALREADY_CLAIMED"
            continue
        native = scan.pixels[
            (top+y-pad)*ratio:(top+y+h+pad)*ratio,
            (left+x-pad)*ratio:(left+x+w+pad)*ratio,
        ]
        foreign = ((gray[sl] < 254) & ~component) | protected
        result = recover_short_straight_parts(
            gray[sl], component, foreign, dpi=float(dpi), native_gray=native, native_scale=ratio,
        )
        item["reason"] = result["reason"]
        item["part_decisions"] = _serial(result["decisions"])
        candidates = result["candidates"]
        if not candidates:
            continue
        old_paths = trace_binary(np.where(component, 0, 255).astype(np.uint8))
        if not old_paths:
            item["reason"] = "NO_SOURCE_BOUNDARY"
            continue
        record = _serial(result)
        record.pop("candidates", None)
        record.update(
            kind="partial_compound_strokes", classification="PARTIAL_COMPOUND_STROKES",
            native_source_compound_strokes=True, native_scan=False, dpi=float(dpi),
            origin_work_px=(x-pad, y-pad), bbox=(x, y, w, h), parts=_serial(candidates),
            source_runs_y_x0_x1=_runs(component), source_pixels=area,
            original_boundary_paths_px=tuple(tuple(p.points) for p in old_paths),
            source_identity=identity, full_object_movable=False, creates_connection=False,
            electrical_semantics="NOT_INFERRED", historical_identity="NOT_PROVEN",
            width_space="paper_mm", whole_parent_protected_source_pixels=0,
            whole_parent_previously_claimed_source_pixels=0,
        )
        unit = 25.4/float(dpi)
        try:
            proof = validate_compound_stroke_record(
                record, center_transform=lambda px, py: (px*unit, -py*unit), units=4,
            )
        except ValueError as exc:
            item.update(reason="EXPORT_CONTRACT_REJECTED", detail=str(exc))
            continue
        # Independent parents must also remain disjoint after *both* fits.
        # The square-cap envelope contains butt and round caps of these LINEs.
        # Checking only each pen against the other parent's old ink is weaker.
        origin = np.asarray(record["origin_work_px"], dtype=float)
        envelope = unary_union([
            LineString(np.asarray(part["points_px"], dtype=float)+origin).buffer(
                part["lineweight_hundredth_mm"]*float(dpi)/5080.,
                cap_style="square", join_style="round")
            for part in candidates
        ])
        if any(envelope.intersects(previous) for previous in accepted_pen_envelopes):
            item["reason"] = "NEW_CONTACT_BETWEEN_ADOPTED_PARENTS"
            continue
        accepted_pen_envelopes.append(envelope)
        record["pre_retirement_export_validation"] = proof
        record["prior_adopted_parent_pen_contacts"] = 0
        record["experimental_retirement_authorized"] = True
        record["retirement_authority"] = "EXPLICIT_EXPERIMENTAL_FLAG_AND_VALIDATED_NATIVE_PARTITION"
        # One parent record occupies one enclosure slot. Its full representation
        # is emitted by the compound exporter, never by the ordinary contour loop.
        path = tuple((px+x-pad, py+y-pad) for px, py in old_paths[0].points)
        paths.append(TracePath(path, None, 0, len(paths)))
        records.append(record)
        if output is visible_binary:
            output = visible_binary.copy()
        output[sl][component] = 255
        item.update(decision="ACCEPTED_PARTIAL_PARENT", parts=len(candidates),
                    native_source_pixels=result["native_source_pixels"],
                    native_retired_source_pixels=result["native_retired_source_pixels"],
                    native_residual_pixels=result["native_residual_pixels"])
        review["accepted_parents"] += 1
        review["accepted_parts"] += len(candidates)
        review["working_source_pixels"] += area
        for key in ("native_source_pixels", "native_retired_source_pixels", "native_residual_pixels"):
            review[key] += result[key]
    review["checked_parents"] = len(review["decisions"])
    return output, tuple(paths), tuple(records), review
