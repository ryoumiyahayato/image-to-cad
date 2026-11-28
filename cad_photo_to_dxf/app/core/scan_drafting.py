"""Resolve scan observations with executable drafting rules and save their origin.

This is the deterministic decision stage. It operates before DXF export, without
changing the independent saved-file quality check or claiming a learned model.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.spatial import cKDTree

from app.core.cancellation import checkpoint
from app.geometry.drafting_rules import PACK_NAME, PACK_VERSION, resolve_geometry
from app.geometry.scan_symbols import assemble_symbols


APPID = "IMAGE_TO_CAD"
REPAIR_LAYER = "SUGGEST_REPAIR"


def resolve_page(candidates, binary, texts, *, dpi, source_binary=None, cancellation_token=None):
    """Keep observations intact while selecting formal geometry and symbol groups."""
    geometry, stats = resolve_geometry(candidates, binary, dpi=dpi, source_binary=source_binary,
                                       cancellation_token=cancellation_token)
    symbols = assemble_symbols(geometry, texts, cancellation_token=cancellation_token)
    return geometry, symbols, {"pack": PACK_NAME, "version": PACK_VERSION,
                               "geometry": stats, "symbol_groups": len(symbols)}


def suggest_repairs(candidates, source_binary, *, cancellation_token=None):
    """Propose local continuations between free ends with observed source wings."""
    ends = []
    for index, record in enumerate(candidates):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        path = record["source_path"]
        width = record["stroke_width"]
        if len(path) < 13 or width > 12:
            continue
        for degree, wing in zip(record["endpoint_degrees"], (path, path[::-1])):
            if degree != 1:
                continue
            tangent = wing[0] - wing[8]
            length = np.linalg.norm(tangent)
            if length >= 6 and np.max(np.linalg.norm(
                wing[:9] - (wing[0] - np.outer(np.linspace(0, 1, 9), tangent)), axis=1
            )) <= 1.5:
                ends.append((index, wing[0], tangent / length, width))
    if len(ends) < 2:
        return []
    pairs = cKDTree([end[1] for end in ends]).query_pairs(12, output_type="ndarray")
    repairs = []
    for pair_index, (i, j) in enumerate(pairs):
        if pair_index % 256 == 0:
            checkpoint(cancellation_token)
        first, start, forward, width = ends[i]
        second, stop, backward, other_width = ends[j]
        if first == second or max(width, other_width) > 1.6 * min(width, other_width):
            continue
        delta = stop - start
        gap = np.linalg.norm(delta)
        limit = min(12, max(6, 2 * min(width, other_width)))
        if not 3 <= gap <= limit:
            continue
        if min(forward @ delta, -backward @ delta) >= 0.94 * gap:
            points = np.asarray((start, stop))
            reason = "broken_stroke"
        else:
            # Nonparallel source wings can meet at a missing corner. Extend
            # each only along its observed direction and within this gap.
            axes = np.column_stack((forward, -backward))
            if abs(np.linalg.det(axes)) < 0.5:
                continue
            reach = np.linalg.solve(axes, delta)
            if min(reach) < 1.5 or reach.sum() > limit:
                continue
            corner = start + reach[0] * forward
            points = np.asarray((start, corner, stop))
            reason = "possible_junction"
        spans = [np.linspace(a, b, int(np.ceil(np.linalg.norm(b-a)))+1)
                 for a, b in zip(points[:-1], points[1:])]
        xs, ys = np.unique(np.rint(np.concatenate(spans)).astype(int), axis=0).T
        if np.any(xs < 0) or np.any(ys < 0) or np.any(xs >= source_binary.shape[1]) or np.any(
            ys >= source_binary.shape[0]
        ):
            continue
        if np.count_nonzero(source_binary[ys, xs]) < max(2, len(xs)-3):
            continue
        repairs.append({"points": points.tolist(), "source_indices": [first, second],
                        "reason": reason})
    return repairs


def _record_json(record, data):
    # XDATA strings are bounded and XDATA has a 16 KiB entity limit. Arbitrarily
    # long source-index lists belong in an XRECORD, not an oversized XDATA blob.
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    record.reset((1, payload[start:start+240]) for start in range(0, len(payload), 240))


def _attach(entity, page_index, role, data):
    entity.set_xdata(APPID, [(1000, PACK_NAME), (1000, PACK_VERSION),
                            (1000, role), (1071, page_index)])
    evidence = entity.new_extension_dict().add_xrecord("SOURCE_EVIDENCE")
    _record_json(evidence, {"page_index": page_index, "role": role, **data})


def _candidate_bounds(record):
    points = record.get("source_path", record.get("points"))
    if points is not None:
        points = np.asarray(points, float)
        return np.array([points.min(axis=0), points.max(axis=0)])
    center = np.asarray(record["center"], float)
    radius = float(record["radius"])
    return np.array([center-radius, center+radius])


def save_drafting_evidence(doc, candidates, geometry, texts, symbols,
                           geometry_entities, text_entities, *, source, page_index,
                           image_size, dpi, drawing_scale, perspective_corrected=False,
                           cancellation_token=None):
    """Write selectable native GROUPs and portable, page-coordinate evidence.

    GROUP members stay in modelspace: TEXT stays directly editable, and the
    saved-file geometry checker sees every real entity. External leaders remain
    separate entities, referenced by DXF handles in the group's source record.
    """
    if APPID not in doc.appids:
        doc.appids.new(APPID)
    page = doc.rootdict.add_new_dict(APPID).add_xrecord("PAGE_SOURCE")
    _record_json(page, {"source": str(source), "page_index": page_index,
                       "image_size_px": list(image_size), "dpi": float(dpi),
                       "drawing_scale": float(drawing_scale), "pack": PACK_NAME,
                       "version": PACK_VERSION, "input_candidates": len(candidates),
                       "coordinate_frame": ("rectified_page_pixels" if perspective_corrected
                                            else "source_page_pixels")})
    bounds = [_candidate_bounds(record) for record in candidates]
    for index, (record, entity) in enumerate(zip(geometry, geometry_entities)):
        if index % 256 == 0:
            checkpoint(cancellation_token)
        origins = record["source_indices"]
        regions = np.asarray([bounds[i] for i in origins])
        region = np.concatenate((regions[:, 0].min(axis=0), regions[:, 1].max(axis=0)))
        _attach(entity, page_index, "geometry", {
            "source_indices": origins, "source_bounds_px": region.tolist(),
            "rules": record["rules"], "stroke_width_px": float(record["stroke_width"])})
    for index, (line, entity) in enumerate(zip(texts, text_entities)):
        checkpoint(cancellation_token)
        _attach(entity, page_index, "text", {"text_index": index, "quad_px": line.quad,
                                             "confidence": float(line.confidence)})
    for index, symbol in enumerate(symbols):
        checkpoint(cancellation_token)
        group = doc.groups.new(name=f"SCAN_SYMBOL_{page_index+1}_{index+1}",
                               description=f"{symbol['kind']} frame with editable text")
        group.set_data([geometry_entities[i] for i in symbol["geometry_indices"]]
                       + [text_entities[i] for i in symbol["text_indices"]])
        _attach(group, page_index, "symbol", {
            "kind": symbol["kind"], "source_bounds_px": symbol["bounds"],
            "rules": ["frame_label_assembly"],
            "leader_handles": [geometry_entities[i].dxf.handle for i in symbol["leader_indices"]]})


def save_repair_evidence(msp, repairs, point, page_index, *, cancellation_token=None):
    for repair in repairs:
        checkpoint(cancellation_token)
        entity = msp.add_lwpolyline([point(p) for p in repair["points"]],
                                   dxfattribs={"layer": REPAIR_LAYER, "lineweight": 0})
        _attach(entity, page_index, "suggest_repair", {
            "source_indices": repair["source_indices"],
            "path_px": repair["points"],
            "reason": repair["reason"],
            "uncertainty": "unconfirmed",
        })


def save_text_repair_evidence(entity, line, page_index):
    _attach(entity, page_index, "suggest_repair", {
        "reason": "low_confidence_text",
        "uncertainty": "unconfirmed",
        "quad_px": line.quad,
        "candidate_text": line.text,
        "confidence": float(line.confidence),
    })
