"""Experimental partial compound strokes with retained native source cells.

All validation and coordinate conversion finish before a DXF object is created.
This emitter does not certify OCR identity or infer an electrical/logical node.
One source parent yields several independently editable *partial* strokes and
visible unresolved HATCH; it is never presented as a complete movable object.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from hashlib import sha256
import json
import math

import cv2
import numpy as np
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from app.geometry.observed_label_frames import PEN_WIDTHS_HUNDREDTH_MM

VERSION = "observed-compound-parts-v1"
CLASSIFICATION = "PARTIAL_COMPOUND_STROKES"
APPID = "OBSERVED_COMPOUND_PART_SOURCE"
VISIBLE_LAYER = "NATIVE_COMPOUND_PART"
RESIDUAL_LAYER = "COMPOUND_SOURCE_RESIDUAL"
BACKUP_LAYER = "SOURCE_COMPOUND_OUTLINE"
MAX_NATIVE_PIXELS = 1_000_000
MAX_RUNS = 100_000
EPSILON = 1.e-9
SHORT_CONTRACT_VERSION = "short-straight-compound-parts-v1"
SHORT_CONTRACT_SHA256 = "b2678b460fcf5bb73d1d26df1a3a281d555db23c5f458a5a5db8c4f6ed10ebfc"
LONG_CONTRACT_VERSION = "native-compound-long-export-v1"
# The original long emitter fixtures had no version. Register their existing
# native export gates explicitly; the earlier working-grid prototype's version
# is a different schema and is deliberately not an accepted alias.
LONG_CONTRACT = {
    "version": LONG_CONTRACT_VERSION,
    "status": "EXPERIMENTAL_EXPORT_CONTRACT_NOT_PRODUCT_ACCEPTANCE",
    "scope": "Explicit registration of the formerly unversioned native long-part emitter; not the old working-grid proposal schema",
    "geometry": {
        "path_types": ["LINE", "OPEN_LWPOLYLINE"], "simple_open": True,
        "minimum_length_mm": 10.0, "minimum_width_work_px": 0.5,
        "maximum_pen_edge_shift_work_px": 0.25,
        "maximum_bidirectional_boundary_error_work_px": 1.0,
        "centerline_white_cell_intrusion": 0,
        "paper_lineweight": "standard_hundredth_mm",
        "cap_styles": ["round", "butt", "square"],
    },
    "source": {
        "native_scale_min": 2, "native_scale_max": 16,
        "native_center_mapping": "native=(work+0.5)*scale-0.5",
        "support_partition": "support=retired disjoint_union retained_interface",
        "parent_partition": "parent=all_retired disjoint_union residual",
        "retained_interface_in_residual": True, "support_members_disjoint": True,
        "foreign_or_forbidden_contact": 0, "non_interface_residual_contact": 0,
        "direct_part_contact": 0,
        "native_ink8_paper4_region_overlap_bijection": True,
        "continuous_ink_paper_region_overlap_bijection": True,
        "remaining_source": "exact native pixel cells",
        "original_backup": "full native cells and original working boundaries",
    },
    "output": {
        "classification": CLASSIFICATION, "full_object_movable": False,
        "creates_connection": False, "electrical_semantics": "NOT_INFERRED",
        "coordinate_contract": "isotropic source-DPI paper millimetres or unitless source preview",
        "input_validation_before_dxf_mutation": True,
    },
}
# SHA-256 of the UTF-8 canonical JSON: sort_keys=True, separators=(",", ":").
LONG_CONTRACT_SHA256 = "854460e1c9fd1f9baad07e9de386c1d453e583a2490e3b5440d52aad7a57b3df"
_EXPORT_CONTRACTS = {
    SHORT_CONTRACT_VERSION: (SHORT_CONTRACT_SHA256, True),
    LONG_CONTRACT_VERSION: (LONG_CONTRACT_SHA256, False),
}


def _short_contract(record):
    """Resolve a registered proof contract; unknown input never selects long."""
    version = record.get("version")
    registered = _EXPORT_CONTRACTS.get(version) if isinstance(version, str) else None
    if registered is None or record.get("contract_sha256") != registered[0]:
        raise ValueError("Unregistered compound export contract version or hash")
    # Both registered contracts describe their legacy inputs, which predate an
    # explicit proposal declaration. A new generator/ownership claim requires
    # separate registration; a known geometry label must not ignore that claim.
    if any(isinstance(key, str) and (key == "proposal" or key.startswith("proposal_"))
           for key in record):
        raise ValueError("Unregistered compound proposal contract")
    return registered[1]


def _integer(value, label, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{label} must be an integer")
    value = int(value)
    if value < minimum:
        raise ValueError(f"{label} is out of bounds")
    return value


def _finite(value, label, *, positive=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} cannot be boolean")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{label} must be finite and positive")
    return value


def _runs(value, label, *, allow_empty=False):
    if not isinstance(value, (tuple, list)) or len(value) > MAX_RUNS:
        raise ValueError(f"{label} must be bounded source runs")
    if not value and not allow_empty:
        raise ValueError(f"{label} cannot be empty")
    result = []
    previous = None
    pixels = 0
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError(f"Malformed {label}")
        y, a, b = (_integer(v, label) for v in item)
        if b <= a or (previous is not None and
                     (y < previous[0] or (y == previous[0] and a <= previous[2]))):
            raise ValueError(f"{label} must be sorted maximal disjoint runs")
        result.append((y, a, b)); previous = (y, a, b)
        pixels += b-a
        if pixels > MAX_NATIVE_PIXELS:
            raise ValueError(f"{label} exceeds the bounded native source budget")
    return tuple(result)


def _cells(runs, scale):
    # Native pixel centers map to working centers as (n+.5)/scale-.5.
    return unary_union([box(a/scale-.5, y/scale-.5,
                            b/scale-.5, (y+1)/scale-.5) for y, a, b in runs])


def _pixel_set(runs):
    return {(y, x) for y, a, b in runs for x in range(a, b)}


def _polygons(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [part for item in shape.geoms for part in _polygons(item)]


def _topology(shape):
    # Reconcile zero-area diagonal pixel contact with the source eight-neighbor
    # convention. This numerical epsilon is far below one native pixel and is
    # never a candidate connection, distance cluster, or white-gap allowance.
    polygons = _polygons(shape.buffer(1.e-8, join_style="mitre"))
    return len(polygons), sum(len(p.interiors) for p in polygons)


def _inside(shape, region):
    return bool(shape.difference(region.buffer(EPSILON)).is_empty)


def _native_mask(runs, shape):
    mask = np.zeros(shape, bool)
    for y, a, b in runs:
        if y >= shape[0] or b > shape[1]:
            raise ValueError("Source run lies outside the original native grid")
        mask[y, a:b] = True
    return mask


def _native_pen_mask(points, radius, scale, shape, cap):
    """Evaluate the planned pen analytically at original native pixel centers.

Round joins are unions of segment rectangles and disks, with independently
selected round/butt/square terminal caps. No interpolation or coarse grid is
used, and a polygon approximation cannot hide a source-center white gap.
    """
    points = (np.asarray(points, dtype=float)+.5)*scale-.5
    radius *= scale
    out = np.zeros(shape, bool)
    x0 = max(0, int(math.floor(points[:, 0].min()-radius))-1)
    x1 = min(shape[1], int(math.ceil(points[:, 0].max()+radius))+2)
    y0 = max(0, int(math.floor(points[:, 1].min()-radius))-1)
    y1 = min(shape[0], int(math.ceil(points[:, 1].max()+radius))+2)
    if x0 >= x1 or y0 >= y1:
        return out
    yy, xx = np.mgrid[y0:y1, x0:x1]
    target = np.zeros(xx.shape, bool)
    for index, (a, b) in enumerate(zip(points, points[1:])):
        edge = b-a
        length = float(np.linalg.norm(edge))
        direction = edge/length
        dx, dy = xx-a[0], yy-a[1]
        along = dx*direction[0]+dy*direction[1]
        normal = -dx*direction[1]+dy*direction[0]
        lo = -radius if cap == "square" and index == 0 else 0.
        hi = length+radius if cap == "square" and index == len(points)-2 else length
        target |= (along >= lo) & (along <= hi) & (normal*normal <= radius*radius)
    disks = points if cap == "round" else points[1:-1]
    for point in disks:
        target |= (xx-point[0])**2+(yy-point[1])**2 <= radius*radius
    out[y0:y1, x0:x1] = target
    return out


def _overlap_bijection(first, first_count, second, second_count):
    if first_count != second_count:
        return False
    common = (first > 0) & (second > 0)
    pairs = np.unique(np.column_stack((first[common], second[common])), axis=0)
    if not len(pairs):
        return first_count == second_count == 1
    a = np.bincount(pairs[:, 0], minlength=first_count)
    b = np.bincount(pairs[:, 1], minlength=second_count)
    return bool(np.all(a[1:] == 1) and np.all(b[1:] == 1))


def _native_raster_relation(source, output):
    """Require ink-8/paper-4 component overlap bijections, not just equal totals."""
    # The one-cell white frame identifies the external paper even if ink meets
    # a tile border. It creates no source pixels and is never retired/exported.
    source = np.pad(source, 1, constant_values=False)
    output = np.pad(output, 1, constant_values=False)
    result = {}
    for name, connection, left, right in (
        ("ink", 8, source, output), ("paper", 4, ~source, ~output)
    ):
        na, a = cv2.connectedComponents(np.ascontiguousarray(left, dtype=np.uint8), connectivity=connection)
        nb, b = cv2.connectedComponents(np.ascontiguousarray(right, dtype=np.uint8), connectivity=connection)
        result[f"source_{name}_components"] = int(na-1)
        result[f"output_{name}_components"] = int(nb-1)
        result[f"{name}_overlap_bijection"] = _overlap_bijection(a, na, b, nb)
        if name == "paper":
            border_a = set(np.r_[a[0], a[-1], a[:, 0], a[:, -1]])-{0}
            border_b = set(np.r_[b[0], b[-1], b[:, 0], b[:, -1]])-{0}
            result["source_holes"] = int(na-1-len(border_a))
            result["output_holes"] = int(nb-1-len(border_b))
    result["new_ink_center_pixels"] = int(np.count_nonzero(output & ~source))
    result["missing_ink_center_pixels"] = int(np.count_nonzero(source & ~output))
    result["passed"] = bool(result["ink_overlap_bijection"] and result["paper_overlap_bijection"])
    return result


def _continuous_overlap_bijection(first, second):
    if len(first) != len(second):
        return False
    if not first:
        return True
    tree = STRtree(second)
    backward = [set() for _ in second]
    for index, region in enumerate(first):
        matches = {int(peer) for peer in tree.query(region, predicate="intersects")
                   if region.intersection(second[int(peer)]).area > EPSILON**2}
        if len(matches) != 1:
            return False
        backward[next(iter(matches))].add(index)
    return all(len(matches) == 1 for matches in backward)


def _continuous_region_relation(source, output, canvas):
    """Preserve each continuous ink and paper region, including outside paper.

An epsilon only resolves zero-area pixel corner contacts: ink admits those
contacts, while paper requires a positive-width passage. It is never an allowed
white gap bridge or a substitute for the exact native-center raster check.
    """
    result = {}
    for name, left, right in (
        ("ink", source.buffer(1.e-8, join_style="mitre"),
         output.buffer(1.e-8, join_style="mitre")),
        ("paper", canvas.difference(source).buffer(-1.e-8, join_style="mitre"),
         canvas.difference(output).buffer(-1.e-8, join_style="mitre")),
    ):
        a, b = _polygons(left), _polygons(right)
        result[f"source_{name}_regions"] = len(a)
        result[f"output_{name}_regions"] = len(b)
        result[f"{name}_overlap_bijection"] = _continuous_overlap_bijection(a, b)
    result["passed"] = bool(result["ink_overlap_bijection"] and result["paper_overlap_bijection"])
    return result


@dataclass(frozen=True)
class _Part:
    identifier: int
    points: tuple[tuple[float, float], ...]
    code: int
    support_pixels: int
    retired_pixels: int
    retained_pixels: int


@dataclass(frozen=True)
class _Plan:
    source_digest: str
    dpi: float
    scale: int
    parts: tuple[_Part, ...]
    residual_polygons: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    backup_polygons: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    original_boundaries: tuple[tuple[tuple[float, float], ...], ...]
    bounds: tuple[tuple[float, float], ...]
    source_pixels: int
    residual_pixels: int
    native_raster_audit: tuple[dict, ...]
    continuous_region_audit: tuple[dict, ...]


@dataclass(frozen=True)
class _UnitContext:
    units: int


def _validate(record, center_transform, doc) -> _Plan:
    if not isinstance(record, Mapping):
        raise ValueError("Compound source record must be a mapping")
    if (record.get("classification") != CLASSIFICATION
            or record.get("native_source_compound_strokes") is not True
            or record.get("full_object_movable") is not False
            or record.get("creates_connection") is not False
            or record.get("electrical_semantics") != "NOT_INFERRED"):
        raise ValueError("Compound output requires an explicit partial-source contract")
    short_contract = _short_contract(record)
    dpi = _finite(record.get("dpi"), "working source DPI", positive=True)
    scale = _integer(record.get("native_scale"), "native scale", 2)
    if scale > 16:
        raise ValueError("Native scale exceeds the bounded experimental contract")
    origin = np.asarray(record.get("origin_work_px", ()), dtype=float)
    if origin.shape != (2,) or not np.isfinite(origin).all():
        raise ValueError("Compound source requires its finite working-grid origin")
    source_runs = _runs(record.get("native_source_runs_y_x0_x1"), "native source")
    residual_runs = _runs(record.get("native_residual_runs_y_x0_x1"), "native residual")
    foreign_runs = _runs(record.get("native_foreign_runs_y_x0_x1"), "native foreign source", allow_empty=True)
    forbidden_runs = _runs(record.get("native_forbidden_runs_y_x0_x1", None if short_contract else ()),
                           "native forbidden band", allow_empty=True)
    source_set = _pixel_set(source_runs)
    residual_set = _pixel_set(residual_runs)
    foreign_set = _pixel_set(foreign_runs)
    forbidden_set = _pixel_set(forbidden_runs)
    if not residual_set <= source_set or source_set & (foreign_set | forbidden_set):
        raise ValueError("Native residual/foreign source membership is invalid")
    for name, actual in (("native_source_pixels", len(source_set)),
                         ("native_residual_pixels", len(residual_set)),
                         ("native_retired_source_pixels", len(source_set)-len(residual_set))):
        if name in record and _integer(record[name], name) != actual:
            raise ValueError("Stale native source accounting")
    if "source_shape" in record or "native_shape" in record:
        shape = record.get("source_shape", ())
        native_shape = record.get("native_shape", ())
        if (len(shape) != 2 or len(native_shape) != 2
                or tuple(_integer(n, "native shape", 1) for n in native_shape)
                != tuple(scale*_integer(n, "working shape", 1) for n in shape)
                or any(y >= native_shape[0] or b > native_shape[1]
                       for y, a, b in (*source_runs, *residual_runs, *foreign_runs, *forbidden_runs))):
            raise ValueError("Native source runs differ from the registered tile dimensions")
        grid_shape = tuple(map(int, native_shape))
    else:
        all_runs = (*source_runs, *residual_runs, *foreign_runs, *forbidden_runs)
        grid_shape = (max(row[0] for row in all_runs)+3, max(row[2] for row in all_runs)+3)
    if grid_shape[0]*grid_shape[1] > MAX_NATIVE_PIXELS:
        raise ValueError("Native raster topology exceeds the bounded tile budget")
    source_shape, residual_shape = _cells(source_runs, scale), _cells(residual_runs, scale)
    foreign_shape = _cells(foreign_runs, scale)
    forbidden_shape = _cells(forbidden_runs, scale)
    if not source_shape.is_valid or not residual_shape.is_valid:
        raise ValueError("Invalid native source cell geometry")
    parts = record.get("parts", ())
    if not isinstance(parts, (list, tuple)) or not 1 <= len(parts) <= 256:
        raise ValueError("Compound parent must carry bounded native parts")
    retired_union, support_union, part_ids = set(), set(), set()
    pens_by_cap = {cap: [] for cap in ("round", "flat", "square")}
    prepared = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise ValueError("Compound part record must be a mapping")
        part_id = _integer(part.get("part_id"), "part identifier", 1)
        if part_id in part_ids:
            raise ValueError("Duplicate compound part identifier")
        part_ids.add(part_id)
        points = np.asarray(part.get("points_px", ()), dtype=float)
        if (points.ndim != 2 or points.shape[1:] != (2,) or not 2 <= len(points) <= 256
                or not np.isfinite(points).all()
                or np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) <= 0)):
            raise ValueError("Native part requires a finite nondegenerate open path")
        line = LineString(points)
        if not line.is_simple or line.is_ring:
            raise ValueError("Native part must remain a simple open path")
        if not short_contract and line.length < 10.*dpi/25.4-EPSILON:
            raise ValueError("Long native part fails the unchanged 10 mm gate")
        code = _integer(part.get("lineweight_hundredth_mm"), "paper lineweight", 1)
        if code not in PEN_WIDTHS_HUNDREDTH_MM:
            raise ValueError("Unsupported paper lineweight")
        width = _finite(part.get("width_px"), "measured width", positive=True)
        shift = abs(code*dpi/2540.-width)/2.
        if (width < .5 or shift > .25+EPSILON
                or not math.isclose(_finite(part.get("maximum_measured_pen_edge_shift_px"), "pen shift"),
                                    shift, rel_tol=0., abs_tol=1.e-9)):
            raise ValueError("Stale or out-of-bounds paper pen proof")
        for key in ("source_to_pen_error_px", "pen_to_source_error_px"):
            if not 0 <= _finite(part.get(key), key) <= 1.:
                raise ValueError("Part exceeds the unchanged source boundary gate")
        if short_contract:
            collar = max(2., code*dpi/2540.+math.sqrt(.5))
            interior = line.length-2.*collar
            cross_sections = _integer(part.get("native_cross_sections"), "native cross sections", 12)
            spacing = _finite(part.get("native_cross_section_spacing_px"), "native section spacing", positive=True)
            if (len(points) != 2 or interior*25.4/dpi < 2.-EPSILON
                    or interior/width < 8.-EPSILON or spacing < 1.-EPSILON
                    or (cross_sections-1)*spacing > interior*scale+1.e-7
                    or not math.isclose(_finite(part.get("interior_length_mm"), "interior length"),
                                        interior*25.4/dpi, rel_tol=0., abs_tol=1.e-8)
                    or not math.isclose(_finite(part.get("interior_length_width_ratio"), "interior aspect"),
                                        interior/width, rel_tol=0., abs_tol=1.e-8)):
                raise ValueError("Short part violates its independent original-source sampling contract")
            native_points = np.asarray(part.get("native_points_px", ()), dtype=float)
            if (native_points.shape != points.shape
                    or not np.isfinite(native_points).all()
                    or not np.allclose(native_points, (points+.5)*scale-.5, rtol=0., atol=1.e-9)
                    or tuple(part.get("artificial_endpoint", ())) != (True, True)
                    or _finite(part.get("terminal_extension_px"), "artificial terminal extension") != 0.
                    or not math.isclose(_finite(part.get("collar_radius_px"), "retained collar"),
                                        collar, rel_tol=0., abs_tol=1.e-9)):
                raise ValueError("Short part source-grid or artificial-terminal proof is stale")
            for native_key, working_key in (("native_source_to_pen_error_px", "source_to_pen_error_px"),
                                            ("native_pen_to_source_error_px", "pen_to_source_error_px")):
                error = _finite(part.get(native_key), native_key)
                if not 0 <= error <= 1. or not math.isclose(error/scale, float(part[working_key]),
                                                          rel_tol=0., abs_tol=1.e-9):
                    raise ValueError("Short part exceeds the one-native-pixel boundary contract")
        if (part.get("creates_connection") is not False
                or part.get("full_object_movable") is not False
                or part.get("electrical_semantics") != "NOT_INFERRED"):
            raise ValueError("Part must retain partial-object and no-new-connection meaning")
        support_runs = _runs(part.get("native_supporting_source_runs_y_x0_x1"), "native fit support")
        retired_runs = _runs(part.get("native_retired_source_runs_y_x0_x1"), "native retired source")
        retained_runs = _runs(part.get("native_retained_interface_runs_y_x0_x1"), "native retained interface")
        support, retired, retained = map(_pixel_set, (support_runs, retired_runs, retained_runs))
        if (not support <= source_set or support_union & support
                or retired & retained or retired | retained != support
                or not retained <= residual_set or retired & residual_set
                or retired_union & retired):
            raise ValueError("Native support/retirement/interface ledger is not disjoint and complete")
        for name, actual in (("native_retired_source_pixels", len(retired)),
                             ("native_retained_interface_pixels", len(retained))):
            if name in part and _integer(part[name], name) != actual:
                raise ValueError("Stale native part accounting")
        if short_contract and _integer(part.get("source_pixels"), "native fit support count", 1) != len(support):
            raise ValueError("Short-part fit support count differs from its original source")
        support_union |= support; retired_union |= retired
        support_shape, interface_shape = _cells(support_runs, scale), _cells(retained_runs, scale)
        if not _inside(line, support_shape):
            raise ValueError("Native centerline enters a source white cell")
        tolerance = 1./scale if short_contract else 1.
        # Forward error is defined on original pixel centers, matching the
        # frozen fit contract; reverse error uses the pixel-cell union.
        from app.geometry.observed_open_strokes import _distances
        centers = (np.asarray([(x, y) for y, x in support], dtype=float)+.5)/scale-.5
        forward = max(0., float(_distances(centers, points).max())-code*dpi/5080.)
        if forward > tolerance+EPSILON:
            raise ValueError("Native source exceeds the declared pen boundary")
        for cap, prior_pens in pens_by_cap.items():
            pen = line.buffer(code*dpi/5080., cap_style=cap, join_style="round", quad_segs=32)
            if (not _inside(pen, support_shape.buffer(tolerance))
                    or (not foreign_shape.is_empty and pen.intersects(foreign_shape))
                    or (not forbidden_shape.is_empty and pen.intersects(forbidden_shape))):
                raise ValueError("Native pen has unsupported geometry or foreign contact")
            if any(pen.intersection(piece).area <= EPSILON**2 for piece in _polygons(interface_shape)):
                raise ValueError("Native pen separates a retained source interface")
            if not _inside(pen.intersection(residual_shape), interface_shape):
                raise ValueError("Native pen contacts residual outside its recorded interface")
            if any(pen.intersects(previous) for previous in prior_pens):
                raise ValueError("Distinct partial pens must not create a direct connection")
            prior_pens.append(pen)
        prepared.append((part_id, points, code, len(support), len(retired), len(retained)))
    if retired_union & residual_set or retired_union | residual_set != source_set:
        raise ValueError("Compound native source has missing or overlapping retirement")
    original_native = _native_mask(source_runs, grid_shape)
    retained_native = _native_mask(residual_runs, grid_shape)
    native_raster_audit, continuous_region_audit = [], []
    canvas = box(-.5-1./scale, -.5-1./scale,
                 (grid_shape[1]+1)/scale-.5, (grid_shape[0]+1)/scale-.5)
    for cap, pen_shapes in pens_by_cap.items():
        rendered_native = retained_native.copy()
        for _identifier, points, code, _support, _retired, _retained in prepared:
            rendered_native |= _native_pen_mask(points, code*dpi/5080., scale, grid_shape, cap)
        raster_relation = _native_raster_relation(original_native, rendered_native)
        if not raster_relation["passed"]:
            raise ValueError("Native-grid ink/paper overlap identity changed: "
                + json.dumps({"cap_style": cap, **raster_relation}, sort_keys=True))
        native_raster_audit.append({"cap_style": cap, **raster_relation})
        result_shape = unary_union([residual_shape, *pen_shapes])
        if not result_shape.is_valid or _topology(result_shape) != _topology(source_shape):
            raise ValueError("Compound output changes native source components or holes")
        continuous_relation = _continuous_region_relation(source_shape, result_shape, canvas)
        if not continuous_relation["passed"]:
            raise ValueError("Continuous ink/paper overlap identity changed: "
                + json.dumps({"cap_style": cap, **continuous_relation}, sort_keys=True))
        continuous_region_audit.append({"cap_style": cap, **continuous_relation})

    # Coordinate conversion can fail. Finish it now, before even adding a layer.
    def transform(point):
        result = np.asarray(center_transform(*(np.asarray(point, dtype=float)+origin)), dtype=float)
        if result.shape != (2,) or not np.isfinite(result).all():
            raise ValueError("Nonfinite transformed compound coordinate")
        return tuple(map(float, result))

    zero = np.asarray(transform((0., 0.)))
    basis = np.column_stack((np.asarray(transform((1., 0.)))-zero,
                             np.asarray(transform((0., 1.)))-zero))
    lengths = np.linalg.norm(basis, axis=0)
    if (min(lengths) <= 0 or not math.isclose(*lengths, rel_tol=1.e-9, abs_tol=1.e-12)
            or abs(np.dot(basis[:, 0], basis[:, 1])) > 1.e-9*lengths.prod()):
        raise ValueError("Compound paper pen requires an isotropic coordinate transform")
    expected = 25.4/dpi if int(doc.units) == 4 else 1.
    if int(doc.units) not in (0, 4) or not math.isclose(lengths[0], expected, rel_tol=1.e-8, abs_tol=1.e-10):
        raise ValueError("Compound paper pen requires source-DPI paper scale or unitless source preview")

    def convert_points(points):
        converted = tuple(transform(p) for p in points)
        for point, mapped in zip(points, converted):
            if not np.allclose(mapped, zero+basis@np.asarray(point), rtol=0., atol=1.e-8):
                raise ValueError("Non-affine compound coordinate transform")
        return converted

    def convert_polygons(shape):
        return tuple((convert_points(list(p.exterior.coords)[:-1]),
                      *(convert_points(list(h.coords)[:-1]) for h in p.interiors))
                     for p in _polygons(shape))

    boundaries = record.get("original_boundary_paths_px", ())
    if not isinstance(boundaries, (list, tuple)) or not boundaries:
        raise ValueError("Compound parent requires original working-source boundary backup")
    original = []
    for points in boundaries:
        points = np.asarray(points, dtype=float)
        if (points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 2
                or not np.isfinite(points).all()):
            raise ValueError("Invalid original compound boundary backup")
        original.append(convert_points(points))
    native = tuple(_Part(identifier, convert_points(points), code, supporting, retired, retained)
                   for identifier, points, code, supporting, retired, retained in prepared)
    residual_polygons, backup_polygons = convert_polygons(residual_shape), convert_polygons(source_shape)
    bounds = tuple(point for polygon in backup_polygons for ring in polygon for point in ring)
    identity = sha256(json.dumps({"native_scale": scale, "dpi": dpi,
        "origin_work_px": origin.tolist(), "source": source_runs},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _Plan(identity, dpi, scale, native, residual_polygons, backup_polygons,
                 tuple(original), bounds, len(source_set), len(residual_set),
                 tuple(native_raster_audit), tuple(continuous_region_audit))


def validate_compound_stroke_record(record, *, center_transform, units=4):
    """Validate before source retirement without creating a DXF document.

All member geometry, source runs and original boundary paths are local working
or native coordinates as named; ``origin_work_px`` maps working coordinates to
the page. Native scale 2..16 is a bounded experimental resource contract. The
default ``units=4`` means millimetres; ``units=0`` is the internal source preview.
    """
    units = _integer(units, "output units")
    plan = _validate(record, center_transform, _UnitContext(units))
    return {"version": VERSION, "source_digest": plan.source_digest,
            "native_parts": len(plan.parts), "native_source_pixels": plan.source_pixels,
            "native_residual_pixels": plan.residual_pixels,
            "native_retired_pixels": plan.source_pixels-plan.residual_pixels,
            "source_partition_exact": True, "native_caps_checked": ("round", "butt", "square"),
            "native_raster_audit": plan.native_raster_audit,
            "continuous_region_audit": plan.continuous_region_audit,
            "full_object_movable": False, "electrical_semantics": "NOT_INFERRED"}


def add_compound_stroke_entities(doc, layout, record, *, center_transform):
    """Return (native entities, residual entities, bounds) after strict validation.

All record/geometry/coordinate failures happen before mutation. The independent
parts are partial members; the visible HATCH retains every unresolved native
source pixel, while the hidden backup retains the full native source as well as
the original working-grid boundaries.
"""
    if layout.doc is not doc:
        raise ValueError("Compound layout must belong to the output document")
    if not doc.header.get("$LWDISPLAY", False) or int(doc.header.get("$FILLMODE", 1)) != 1:
        raise ValueError("Compound pen and residual source require lineweight and fill display enabled")
    for name in (VISIBLE_LAYER, RESIDUAL_LAYER):
        if name in doc.layers and (doc.layers.get(name).is_off() or doc.layers.get(name).is_frozen()):
            raise ValueError("Compound visible output layer is disabled")
    plan = _validate(record, center_transform, doc)
    if APPID not in doc.appids:
        doc.appids.new(APPID)
    for name in (VISIBLE_LAYER, RESIDUAL_LAYER, BACKUP_LAYER):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": 7, "lineweight": 0})
    backup = doc.layers.get(BACKUP_LAYER)
    backup.off(); backup.freeze(); backup.lock()
    common = [(1000, CLASSIFICATION), (1000, plan.source_digest),
              (1071, 0), (1040, plan.dpi), (1000, "PARTIAL_OBJECT_NOT_COMPLETE_MOVABLE_OBJECT"),
              (1000, "ELECTRICAL_SEMANTICS_NOT_INFERRED"), (1000, "EXPERIMENTAL_CANDIDATE")]

    def hatches(polygons, layer, marker):
        result = []
        for polygon in polygons:
            hatch = layout.add_hatch(color=7, dxfattribs={"layer": layer})
            for index, ring in enumerate(polygon):
                hatch.paths.add_polyline_path(ring, is_closed=True, flags=1 if index == 0 else 0)
            hatch.set_xdata(APPID, [*common, (1000, marker)])
            result.append(hatch)
        return result

    hatches(plan.backup_polygons, BACKUP_LAYER, "FULL_NATIVE_SOURCE_BACKUP")
    for boundary in plan.original_boundaries:
        entity = layout.add_lwpolyline(boundary, close=True,
                                      dxfattribs={"layer": BACKUP_LAYER, "lineweight": 0})
        entity.set_xdata(APPID, [*common, (1000, "ORIGINAL_WORKING_SOURCE_BOUNDARY")])
    residual = hatches(plan.residual_polygons, RESIDUAL_LAYER, "UNRESOLVED_NATIVE_SOURCE_CELLS")
    native = []
    for part in plan.parts:
        attrs = {"layer": VISIBLE_LAYER, "lineweight": part.code}
        entity = (layout.add_line(*part.points, dxfattribs=attrs) if len(part.points) == 2
                  else layout.add_lwpolyline(part.points, close=False, dxfattribs=attrs))
        tags = [*common]
        tags[2] = (1071, part.identifier)
        tags.extend([(1071, part.support_pixels), (1071, part.retired_pixels),
                     (1071, part.retained_pixels), (1000, "EXCLUSIVE_NATIVE_PART_WITH_SOURCE_COLLAR")])
        entity.set_xdata(APPID, tags)
        native.append(entity)
    return tuple(native), tuple(residual), list(plan.bounds)
