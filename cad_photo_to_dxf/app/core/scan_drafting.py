"""Resolve scan observations with executable drafting rules and save their origin.

This is the deterministic decision stage. It operates before DXF export, without
changing the independent saved-file quality check or claiming a learned model.
"""
from __future__ import annotations

import json

import numpy as np

from app.core.cancellation import checkpoint
from app.geometry.drafting_rules import PACK_NAME, PACK_VERSION, resolve_geometry
from app.geometry.scan_symbols import assemble_symbols


APPID = "IMAGE_TO_CAD"


def resolve_page(candidates, binary, texts, *, dpi, source_binary=None, cancellation_token=None):
    """Keep observations intact while selecting formal geometry and symbol groups."""
    geometry, stats = resolve_geometry(candidates, binary, dpi=dpi, source_binary=source_binary,
                                       cancellation_token=cancellation_token)
    symbols = assemble_symbols(geometry, texts, cancellation_token=cancellation_token)
    return geometry, symbols, {"pack": PACK_NAME, "version": PACK_VERSION,
                               "geometry": stats, "symbol_groups": len(symbols)}


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
