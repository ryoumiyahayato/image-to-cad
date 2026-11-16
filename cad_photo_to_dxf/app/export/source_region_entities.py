"""Explicit complete native source regions, without stroke fitting or inference.

The adapter binds the record to registered source pixels and current ownership.
This module independently verifies its ledger and exact integer boundaries,
prepares every coordinate before mutation, and emits one HATCH per role.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re

import cv2
import numpy as np

VERSION = "explicit-native-source-region-v1"
CLASSIFICATION = "EXPLICIT_COMPLETE_NATIVE_SOURCE_COMPONENT"
AUTHORITY = "OPERATOR_SELECTED_WHOLE_OBSERVED_SOURCE_COMPONENT"
APPID = "I2C_SOURCE_REGION_V1"
DICTIONARY_KEY = "I2C_SOURCE_REGIONS_V1"
MAX_NATIVE_PIXELS = 1_000_000
MAX_RUNS = 100_000
MAX_VERTICES = 200_000
MAX_BOUNDARY_EDGES = 400_000
MAX_LOOPS = 10_000
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
CONTRACT = {
    "version": VERSION,
    "authority": AUTHORITY,
    "representation": "one solid nonassociative HATCH for each of M,R,P",
    "partition": "P=M disjoint_union R; nonempty proper M; full native8 and native4",
    "coordinates": "frame.edge(origin_work_px+native_cell_edge/native_scale)",
    "source": "registered original bitonal cells; no fitting, bridges or smoothing",
    "limits": {"cells": MAX_NATIVE_PIXELS, "runs": MAX_RUNS,
               "vertices": MAX_VERTICES, "edges": MAX_BOUNDARY_EDGES,
               "loops": MAX_LOOPS, "json_bytes": MAX_PAYLOAD_BYTES},
    "historical_identity": "NOT_PROVEN",
    "electrical_semantics": "NOT_INFERRED",
    "local_CAD_validation": "NOT_RUN",
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _digest(value):
    return sha256(_canonical(value).encode("ascii")).hexdigest()


CONTRACT_SHA256 = _digest(CONTRACT)
_RECORD_FIELDS = frozenset({
    "version", "contract_sha256", "native_source_region_partition", "kind", "classification",
    "selection_authority", "automatic_selection", "complete_native_component", "full_object_movable",
    "creates_connection", "historical_identity", "electrical_semantics", "selection_id",
    "selection_manifest", "manifest_sha256", "source_identity", "dpi", "native_dpi", "native_scale",
    "origin_work_px", "source_shape", "native_shape", "bbox", "source_runs_y_x0_x1",
    "native_source_runs_y_x0_x1", "native_member_runs_y_x0_x1", "native_residual_runs_y_x0_x1",
    "native_foreign_runs_y_x0_x1", "source_pixels", "native_source_pixels", "native_member_pixels",
    "native_residual_pixels", "native_foreign_pixels", "whole_parent_protected_source_pixels",
    "whole_parent_previously_claimed_source_pixels", "whole_parent_noncurrent_source_pixels",
    "whole_parent_foreign_source_pixels", "contour_index", "native_source_compound_strokes",
    "native_source_open_stroke", "native_source_frame", "native_scan", "native_source_region",
})


@dataclass(frozen=True)
class SourceRegionRing:
    vertices: tuple[tuple[int, int], ...]
    coordinates: tuple[tuple[float, float], ...]
    flags: int


@dataclass(frozen=True)
class SourceRegionPlan:
    source_digest: str
    selection_id: str
    record_sha256: str
    record_json: str
    frame_json: str
    frame_sha256: str
    member: tuple[SourceRegionRing, ...]
    residual: tuple[SourceRegionRing, ...]
    backup: tuple[SourceRegionRing, ...]
    counts: tuple[int, int, int]
    bounds: tuple[tuple[float, float], ...]


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _finite(value, name, positive=False):
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{name} must be finite and positive")
    return number


def _pair(value, name, minimum=0):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be a pair")
    return tuple(_integer(n, name, minimum) for n in value)


def _sha(value, name):
    if not isinstance(value, str) or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value


def _bounded_json(value):
    budget = [600_000]

    def visit(item, depth):
        budget[0] -= 1
        if depth > 12 or budget[0] < 0:
            raise ValueError("Source region metadata exceeds its nesting/item budget")
        if isinstance(item, Mapping):
            detached = {}
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 160:
                    raise ValueError("Invalid source region metadata key")
                detached[key] = visit(child, depth + 1)
            return detached
        elif isinstance(item, (list, tuple)):
            return [visit(child, depth + 1) for child in item]
        elif type(item) is str:
            if len(item) > 4096:
                raise ValueError("Source region metadata string too large")
        elif item is not None and type(item) not in (bool, int, float):
            raise ValueError("Source region metadata must contain JSON primitives")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("Nonfinite source region metadata")
        elif type(item) is int and abs(item) > 2**53:
            raise ValueError("Source region metadata integer too large")
        return item

    detached = visit(value, 0)
    encoded = _canonical(detached)
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("Source region metadata byte budget exceeded")
    return encoded


def _runs(value, shape, name, budget, *, empty=False):
    if not isinstance(value, (list, tuple)) or (not value and not empty):
        raise ValueError(f"{name} requires canonical source runs")
    budget[0] -= len(value)
    if budget[0] < 0:
        raise ValueError("Source region run budget exceeded")
    result, previous = [], None
    for run in value:
        if not isinstance(run, (list, tuple)) or len(run) != 3:
            raise ValueError(f"Malformed {name} run")
        y, a, b = (_integer(n, name) for n in run)
        if not (y < shape[0] and a < b <= shape[1]):
            raise ValueError(f"Out of bounds {name} run")
        if previous is not None and (y < previous[0] or (y == previous[0] and a <= previous[2])):
            raise ValueError(f"{name} runs must be sorted, maximal and disjoint")
        previous = (y, a, b)
        result.append(previous)
    return tuple(result)


def _mask(runs, shape):
    value = np.zeros(shape, dtype=bool)
    for y, a, b in runs:
        value[y, a:b] = True
    return value


def _integer_rings(mask, edge_budget, vertex_budget, loop_budget):
    """Trace directed exposed cell edges; internal edges never reach the DXF."""
    padded = np.pad(mask, 1)
    sides = (mask & ~padded[:-2, 1:-1], mask & ~padded[1:-1, 2:],
             mask & ~padded[2:, 1:-1], mask & ~padded[1:-1, :-2])
    count = sum(int(side.sum()) for side in sides)
    edge_budget[0] -= count
    if edge_budget[0] < 0:
        raise ValueError("Source region boundary edge budget exceeded")
    edges = set()
    outgoing = {}
    for direction, side in enumerate(sides):
        for y, x in zip(*np.nonzero(side)):
            x, y = int(x), int(y)
            a, b = (((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)),
                    ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y)))[direction]
            edge = (a, b)
            edges.add(edge)
            outgoing.setdefault(a, []).append((direction, b))
    if not edges:
        raise ValueError("Empty source region boundary")
    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    rings = []
    ordered_edges = iter(sorted(edges))
    while edges:
        first = next(edge for edge in ordered_edges if edge in edges)
        current = first
        points = []
        seen_vertices = set()
        while True:
            a, b = current
            if current not in edges or a in seen_vertices:
                raise ValueError("Source region has an ambiguous or self-touching ring")
            edges.remove(current)
            seen_vertices.add(a)
            points.append(a)
            if b == first[0]:
                break
            direction = directions[(b[0] - a[0], b[1] - a[1])]
            choices = [(d, end) for d, end in outgoing.get(b, ()) if (b, end) in edges]
            if not choices:
                raise ValueError("Open source region boundary")
            # Right-hand cell interior keeps diagonally touching cells in
            # separate simple rings without joining across an observed white gap.
            order = {1: 0, 0: 1, 3: 2, 2: 3}
            _next_direction, end = min(choices, key=lambda item: order[(item[0] - direction) % 4])
            current = (b, end)
        kept = []
        for i, point in enumerate(points):
            a, b = points[i - 1], points[(i + 1) % len(points)]
            if (point[0] - a[0]) * (b[1] - point[1]) != (point[1] - a[1]) * (b[0] - point[0]):
                kept.append(point)
        area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(kept, kept[1:] + kept[:1]))
        if len(kept) < 4 or not area2:
            raise ValueError("Degenerate source region ring")
        start = min(range(len(kept)), key=kept.__getitem__)
        ring = tuple(kept[start:] + kept[:start])
        vertex_budget[0] -= len(ring)
        loop_budget[0] -= 1
        if vertex_budget[0] < 0 or loop_budget[0] < 0:
            raise ValueError("Source region vertex/loop budget exceeded")
        rings.append((ring, 1 if area2 > 0 else 0))
    # Exact signed area is an additional ledger check, not an approximate oracle.
    area2 = sum(sum(a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(ring, ring[1:] + ring[:1])) for ring, _flags in rings)
    if area2 != 2 * int(mask.sum()):
        raise ValueError("Source cell boundary ledger changed")
    crossings = np.zeros((mask.shape[0], mask.shape[1] + 1), dtype=bool)
    for ring, _flags in rings:
        for a, b in zip(ring, ring[1:] + ring[:1]):
            if a[0] == b[0]:
                crossings[min(a[1], b[1]):max(a[1], b[1]), a[0]] ^= True
    if not np.array_equal(np.logical_xor.accumulate(crossings[:, :-1], axis=1), mask):
        raise ValueError("Source region rings changed an original black or white cell")
    return tuple(sorted(rings, key=lambda item: (-item[1], item[0])))


def _coordinate_plan(edge_transform, origin, scale, native_shape, rings_by_role):
    def call(x, y):
        result = edge_transform(x, y)
        if not isinstance(result, (tuple, list, np.ndarray)) or len(result) != 2:
            raise ValueError("Region edge transform must return two coordinates")
        return tuple(_finite(n, "edge coordinate") for n in result)

    owner = getattr(edge_transform, "__self__", None)
    from app.core.scale_calibrator import RasterToCad
    if isinstance(owner, RasterToCad) and getattr(edge_transform, "__name__", "") == "edge":
        zero = (_finite(owner.left, "frame left"), _finite(owner.top, "frame top"))
        sx, sy = _finite(owner.scale_x, "frame scale x", True), -_finite(owner.scale_y, "frame scale y", True)
    else:
        zero, x1, y1 = call(0., 0.), call(1., 0.), call(0., 1.)
        sx, sy = x1[0] - zero[0], y1[1] - zero[1]
        if x1[1] != zero[1] or y1[0] != zero[0] or sx <= 0 or sy >= 0:
            raise ValueError("Source region requires positive x / flipped y axis-aligned affine edges")
    if not math.isfinite(sx) or not math.isfinite(sy) or sx <= 0 or sy >= 0:
        raise ValueError("Invalid source region affine frame")
    frame = {"kind": "axis-aligned-cell-edge-v1", "origin": zero, "basis": (sx, sy)}
    ox, oy = origin
    # Check every grid line, including white gaps, before converting rings.
    xs = tuple(zero[0] + (ox + x / scale) * sx for x in range(native_shape[1] + 1))
    ys = tuple(zero[1] + (oy + y / scale) * sy for y in range(native_shape[0] + 1))
    if (not all(math.isfinite(v) for v in (*xs, *ys))
            or any(a >= b for a, b in zip(xs, xs[1:]))
            or any(a <= b for a, b in zip(ys, ys[1:]))):
        raise ValueError("Source cell grid collapsed in the output coordinate precision")
    converted = []
    for rings in rings_by_role:
        converted_rings = []
        for points, flags in rings:
            coordinates = tuple((xs[x], ys[y]) for x, y in points)
            for (x, y), expected in zip(points, coordinates):
                actual = call(ox + x / scale, oy + y / scale)
                if actual != expected:
                    raise ValueError("Source region edge transform is not the declared affine frame")
            converted_rings.append(SourceRegionRing(points, coordinates, flags))
        converted.append(tuple(converted_rings))
    return tuple(converted), frame


def preflight_source_region(record, *, edge_transform):
    """Return a frozen plan without touching a document or retiring any source."""
    if not isinstance(record, Mapping):
        raise ValueError("Source region record must be a JSON mapping")
    record_json = _bounded_json(record)
    # FinalStructure/cache metadata is recursively frozen MappingProxyType.
    # Detach only after its bounded traversal, never through an unbounded copy.
    record = json.loads(record_json)
    if set(record) - _RECORD_FIELDS:
        raise ValueError("Unregistered source region metadata fields")
    if (record.get("version") != VERSION or record.get("contract_sha256") != CONTRACT_SHA256
            or record.get("native_source_region_partition") is not True
            or record.get("kind") != "explicit_native_source_region"
            or record.get("classification") != CLASSIFICATION
            or record.get("selection_authority") != AUTHORITY
            or record.get("automatic_selection") is not False
            or record.get("complete_native_component") is not True
            or record.get("full_object_movable") is not False
            or record.get("creates_connection") is not False
            or record.get("historical_identity") != "NOT_PROVEN"
            or record.get("electrical_semantics") != "NOT_INFERRED"):
        raise ValueError("Source region requires its registered explicit-selection contract")
    if any(record.get(key) is not None and record.get(key) is not False for key in (
            "native_source_compound_strokes", "native_source_open_stroke",
            "native_source_frame", "native_scan", "native_source_region")):
        raise ValueError("Conflicting source region entity selector")
    for field in ("protected_source", "previously_claimed_source", "noncurrent_source", "foreign_source"):
        if _integer(record.get(f"whole_parent_{field}_pixels"), field) != 0:
            raise ValueError("Source region parent violates current ownership guards")
    shape = _pair(record.get("source_shape"), "working shape", 1)
    native_shape = _pair(record.get("native_shape"), "native shape", 1)
    scale = _integer(record.get("native_scale"), "native scale", 1)
    if scale > 16 or native_shape != tuple(n * scale for n in shape) or math.prod(native_shape) > MAX_NATIVE_PIXELS:
        raise ValueError("Source region native shape/scale budget mismatch")
    origin = _pair(record.get("origin_work_px"), "working origin")
    dpi = _finite(record.get("dpi"), "working dpi", True)
    native_dpi = _finite(record.get("native_dpi"), "native dpi", True)
    # This matches registered-scan metadata tolerance; source geometry and
    # coordinate round-trip comparisons never use this DPI tolerance.
    if not math.isclose(native_dpi, dpi * scale, rel_tol=0., abs_tol=.01):
        raise ValueError("Source region native/working DPI mismatch")
    budget = [MAX_RUNS]
    working_runs = _runs(record.get("source_runs_y_x0_x1"), shape, "working parent", budget)
    source_runs, member_runs, residual_runs, foreign_runs = (
        _runs(record.get(f"native_{role}_runs_y_x0_x1"), native_shape, role, budget, empty=role == "foreign")
        for role in ("source", "member", "residual", "foreign"))
    parent, member, residual, foreign = (_mask(r, native_shape) for r in
                                          (source_runs, member_runs, residual_runs, foreign_runs))
    if np.any(member & ~parent) or np.any(member & residual) or not np.array_equal(parent, member | residual) or np.any(parent & foreign):
        raise ValueError("Source region P/M/R/foreign partition is inconsistent")
    working = _mask(working_runs, shape)
    ys, xs = np.nonzero(working)
    expected_bbox = [origin[0] + int(xs.min()), origin[1] + int(ys.min()),
                     int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1]
    bbox = record.get("bbox")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or any(type(value) is not int for value in bbox) or bbox != expected_bbox):
        raise ValueError("Source region bbox does not match its original source ownership")
    parent_support = np.repeat(np.repeat(working, scale, 0), scale, 1)
    if np.any(parent & ~parent_support) or np.any(foreign & parent_support):
        raise ValueError("Native parent does not match its working ownership")
    if not np.array_equal(parent.reshape(shape[0], scale, shape[1], scale).any(axis=(1, 3)), working):
        raise ValueError("Working parent has no native support")
    for name, mask in (("source_pixels", working), ("native_source_pixels", parent),
                       ("native_member_pixels", member), ("native_residual_pixels", residual),
                       ("native_foreign_pixels", foreign)):
        if _integer(record.get(name), name, 0 if name == "native_foreign_pixels" else 1) != int(mask.sum()):
            raise ValueError("Stale source region pixel accounting")
    if member[0].any() or member[-1].any() or member[:, 0].any() or member[:, -1].any():
        raise ValueError("Selected source region touches the registered tile boundary")
    black = np.uint8(parent | foreign)
    _, labels = cv2.connectedComponents(black, connectivity=8)
    label_ids = np.unique(labels[member])
    if len(label_ids) != 1 or label_ids[0] == 0 or not np.array_equal(member, labels == label_ids[0]):
        raise ValueError("Member is not a complete original native eight-component")
    if cv2.connectedComponents(np.uint8(member), connectivity=4)[0] != 2:
        raise ValueError("Member must be four-connected")
    manifest = record.get("selection_manifest")
    identity = record.get("source_identity")
    if type(manifest) is not dict or type(identity) is not dict or _digest(manifest) != _sha(record.get("manifest_sha256"), "selection manifest"):
        raise ValueError("Source region manifest identity mismatch")
    from app.geometry.source_region_selection import parse_source_region_selection
    normalized_manifest = parse_source_region_selection(manifest)
    if _canonical(manifest) != _canonical(normalized_manifest):
        raise ValueError("Source region requires a canonical selection manifest")
    selection = manifest.get("selection", {})
    prepared = manifest.get("prepared_window", {})
    selection_id = record.get("selection_id")
    if (not isinstance(selection_id, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", selection_id) is None
            or selection.get("id") != selection_id
            or _canonical(selection.get("working_parent_runs_y_x0_x1")) != _canonical(working_runs)
            or _canonical(selection.get("native_member_runs_y_x0_x1")) != _canonical(member_runs)
            or _canonical(prepared.get("origin_work_px")) != _canonical(origin)
            or _canonical(prepared.get("shape_yx")) != _canonical(shape)
            or manifest.get("native_scale") != scale):
        raise ValueError("Source region selection/registration differs from its manifest")
    for field in ("input_pixels_sha256", "original_pixels_sha256",
                  "trace_window_pixels_sha256", "prepared_window_pixels_sha256"):
        _sha(identity.get(field), field)
    if (identity.get("native_scale") != scale or identity.get("working_dpi") != dpi
            or identity.get("original_dpi") != native_dpi
            or identity.get("prepared_window_pixels_sha256") != prepared.get("pixels_sha256")):
        raise ValueError("Source region source identity is inconsistent")
    expected_identity = {
        "input_pixels_sha256": manifest["input"]["pixels_sha256"],
        "input_shape": manifest["input"]["shape_yx"], "input_dtype": "uint8",
        "original_pixels_sha256": manifest["original"]["pixels_sha256"],
        "original_shape": manifest["original"]["shape_yx"], "original_dtype": "uint8",
        "working_dpi": manifest["input"]["dpi"], "original_dpi": manifest["original"]["dpi"],
        "native_scale": scale, "source_crop": manifest["crop_work_px"],
        "trace_window_pixels_sha256": identity["trace_window_pixels_sha256"],
        "prepared_window_pixels_sha256": prepared["pixels_sha256"],
        "mapping": "full_native_edge=(trace_work_edge+crop_origin)*native_scale",
    }
    if _canonical(identity) != _canonical(expected_identity):
        raise ValueError("Source region source identity disagrees with its bound selection manifest")
    edge_budget, vertex_budget, loop_budget = [MAX_BOUNDARY_EDGES], [MAX_VERTICES], [MAX_LOOPS]
    rings = tuple(_integer_rings(mask, edge_budget, vertex_budget, loop_budget)
                  for mask in (member, residual, parent))
    converted, frame = _coordinate_plan(edge_transform, origin, scale, native_shape, rings)
    bounds = tuple(point for ring in converted[2] for point in ring.coordinates)
    source_digest = _digest({"identity": identity, "manifest_sha256": record["manifest_sha256"],
                             "source": source_runs, "member": member_runs, "version": VERSION})
    return SourceRegionPlan(source_digest, selection_id, sha256(record_json.encode("ascii")).hexdigest(),
                            record_json, _canonical(frame), _digest(frame), *converted,
                            (int(member.sum()), int(residual.sum()), int(parent.sum())), bounds)


def _names(plan, namespace):
    if not isinstance(namespace, str) or re.fullmatch(r"[A-Za-z0-9_.-]{0,64}", namespace) is None:
        raise ValueError("Invalid source region export namespace")
    key = _digest({"namespace": namespace, "source_digest": plan.source_digest})
    prefix = "I2CR_" + key[:16]
    return key, {role: prefix + "_" + suffix for role, suffix in
                 (("member", "M"), ("residual", "R"), ("backup", "P"))}


def preflight_source_region_document(doc, plans, *, namespace=""):
    """Reject document collisions/display problems before any page mutation."""
    plans = tuple(plans)
    if len(plans) > 1:
        raise ValueError("The first source region document contract accepts one explicit selection")
    if not plans:
        return
    if int(doc.header.get("$FILLMODE", 1)) != 1 or int(doc.units) not in (0, 4):
        raise ValueError("Source region requires fill display and millimetres/unitless preview")
    if doc.dxfversion < "AC1015":
        raise ValueError("Source region requires a modern DXF HATCH document")
    dictionary = doc.rootdict.get(DICTIONARY_KEY)
    if dictionary is not None and dictionary.dxftype() != "DICTIONARY":
        raise ValueError("Source region metadata dictionary collision")
    for plan in plans:
        if not isinstance(plan, SourceRegionPlan):
            raise ValueError("Source region emission requires a prepared plan")
        key, layers = _names(plan, namespace)
        if dictionary is not None and key in dictionary:
            raise ValueError("Source region selection already exists in this document namespace")
        if any(layer in doc.layers for layer in layers.values()):
            raise ValueError("Source region layer identity collision")
        for entity in doc.modelspace():
            if entity.has_xdata(APPID):
                tags = entity.get_xdata(APPID)
                if len(tags) >= 2 and tags[1].value == plan.source_digest:
                    raise ValueError("Duplicate source region entities in this document")


def emit_source_region_plan(doc, modelspace, plan, *, namespace=""):
    """Emit (M, R, hidden P, bounds); on error roll back newly added DXF objects.

    Callers must discard the output document after an emission exception and
    must never publish it; the outer exporter owns atomic file publication.
    """
    if modelspace.doc is not doc:
        raise ValueError("Source region layout belongs to another document")
    preflight_source_region_document(doc, (plan,), namespace=namespace)
    key, layers = _names(plan, namespace)
    metadata = {"version": VERSION, "contract_sha256": CONTRACT_SHA256,
                "source_digest": plan.source_digest, "record_sha256": plan.record_sha256,
                "record": json.loads(plan.record_json), "frame": json.loads(plan.frame_json),
                "frame_sha256": plan.frame_sha256, "namespace": namespace,
                "record_key": key, "lifecycle": "PARTITIONED",
                "roles": {role: {"layer": layers[role], "source_pixels": count}
                          for role, count in zip(("member", "residual", "backup"), plan.counts)}}
    encoded = _bounded_json(metadata)
    existing_handles = set(doc.entitydb)
    existing_appid = APPID in doc.appids
    existing_dictionary = doc.rootdict.get(DICTIONARY_KEY)
    created_entities = []
    dictionary = None
    try:
        if not existing_appid:
            doc.appids.new(APPID)
        for role, layer_name in layers.items():
            layer = doc.layers.new(layer_name, dxfattribs={"color": 4 if role == "member" else 7,
                                                          "lineweight": 0, "plot": 1})
            if role != "member":
                layer.lock()
            if role == "backup":
                layer.off()
                layer.freeze()
        dictionary = existing_dictionary
        if dictionary is None:
            dictionary = doc.rootdict.add_new_dict(DICTIONARY_KEY, hard_owned=True)
        xrecord = dictionary.add_xrecord(key)
        xrecord.extend((1, encoded[i:i + 220]) for i in range(0, len(encoded), 220))
        for role, rings in (("member", plan.member), ("residual", plan.residual), ("backup", plan.backup)):
            hatch = modelspace.add_hatch(color=256, dxfattribs={"layer": layers[role],
                "hatch_style": 0, "associative": 0, "elevation": (0, 0, 0), "extrusion": (0, 0, 1)})
            created_entities.append(hatch)
            for ring in rings:
                hatch.paths.add_polyline_path(ring.coordinates, is_closed=True, flags=ring.flags)
            hatch.set_xdata(APPID, [(1000, VERSION), (1000, plan.source_digest), (1000, role),
                                   (1000, plan.record_sha256), (1000, plan.frame_sha256)])
        return (*created_entities, list(plan.bounds))
    except BaseException:
        # Restore every created public resource. Handle allocation can advance;
        # that is why the failed working document must additionally be discarded.
        for entity in list(modelspace):
            if entity.dxf.handle not in existing_handles:
                modelspace.delete_entity(entity)
        dictionary = doc.rootdict.get(DICTIONARY_KEY)
        if existing_dictionary is None and dictionary is not None:
            # Delete the hard-owning dictionary before its children; deleting
            # XRECORD first leaves a dead hard-owner reference in ezdxf.
            doc.rootdict.discard(DICTIONARY_KEY)
            doc.objects.delete_entity(dictionary)
        elif dictionary is not None and key in dictionary:
            xrecord = dictionary[key]
            dictionary.discard(key)
            doc.objects.delete_entity(xrecord)
        for layer_name in reversed(tuple(layers.values())):
            if layer_name in doc.layers:
                doc.layers.remove(layer_name)
        if not existing_appid and APPID in doc.appids:
            doc.appids.remove(APPID)
        for handle in set(doc.entitydb) - existing_handles:
            entity = doc.entitydb.get(handle)
            if entity is not None and entity.is_alive:
                if entity.dxftype() in ("DICTIONARY", "XRECORD"):
                    doc.objects.delete_entity(entity)
                else:
                    doc.entitydb.delete_entity(entity)
        raise
