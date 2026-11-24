"""Separate observed graphics from a source row without inventing glyph ink.

The geometry planner owns complete source paths.  This module only prepares a
bounded recognition view and records which original samples were shared at a
contact.  It never uses a transcript, a page identifier or evaluation boxes.
"""

from __future__ import annotations

import copy
import json
import math

import cv2
import numpy as np

from . import text_contact_geometry as graphics
from . import text_regions as base


POLICY = {
    "version": "complete-source-contact-row-v1",
    "minimum_intact_row_anchors": 3,
    "round_diameter_glyph_height_minimum": 1.15,
    "round_source_outer_margin_px": 5.0,
    "fragment_white_gap_px": 2,
    "fragment_column_overlap_fraction": 0.25,
    "foot_height_glyph_fraction_maximum": 0.16,
    "foot_width_glyph_fraction_maximum": 0.60,
    "foot_baseline_tolerance_px": 2,
    "source_gaps_filled": False,
    "derived_samples_are_original_character_proof": False,
    "shared_contact_samples_may_belong_to_both_objects": True,
}

_GRAPH_CACHE = None


def _source_graph(gray, roi):
    """Cache only the unmodified graph, keyed by actual current source bytes."""
    global _GRAPH_CACHE
    key = (
        base.source_array_sha256(gray),
        tuple(roi),
        json.dumps(graphics.POLICY, sort_keys=True),
    )
    if _GRAPH_CACHE is None or _GRAPH_CACHE[0] != key:
        _GRAPH_CACHE = (key, graphics.build_text_contact_source_graph(gray, roi))
    return _GRAPH_CACHE[1]


def _mark(mask, runs, origin):
    ox, oy = origin
    for y, a, b in runs:
        if oy <= y < oy + mask.shape[0]:
            mask[y - oy, max(0, a - ox) : min(mask.shape[1], b - ox)] = True


def _join_fragments(components, height, baseline):
    """Associate fragmented source strokes; do not paint across their gaps.

    A foot must lie at the bottom of a narrow full-height stem.  This does not
    consume middle dashes, adjacent commas, quotes or a neighboring short line.
    Vertical fragments may be associated before they have full glyph height.
    """
    rows = copy.deepcopy(components)
    joins = []
    for _ in range(64):
        rows.sort(key=lambda r: (r["bbox"][0], r["bbox"][1]))
        changed = False
        for i, a in enumerate(rows):
            if a["height"] > 1.45 * height or a["width"] > 1.7 * height:
                continue
            for j in range(i + 1, len(rows)):
                b = rows[j]
                if b["bbox"][0] > a["bbox"][2] + POLICY["fragment_white_gap_px"]:
                    break
                if b["height"] > 1.45 * height or b["width"] > 1.7 * height:
                    continue
                ab, bb = a["bbox"], b["bbox"]
                union = base._box_union([ab, bb])
                if (
                    union[2] - union[0] > 1.7 * height
                    or union[3] - union[1] > 1.45 * height
                    or union[1] < baseline - 1.45 * height
                    or union[3] > baseline + 0.28 * height
                ):
                    continue
                xo = max(0, min(ab[2], bb[2]) - max(ab[0], bb[0]))
                yg = max(ab[1] - bb[3], bb[1] - ab[3], 0)
                xg = max(ab[0] - bb[2], bb[0] - ab[2], 0)
                vertical = (
                    xo
                    >= POLICY["fragment_column_overlap_fraction"]
                    * min(a["width"], b["width"])
                    and yg <= POLICY["fragment_white_gap_px"]
                    and not (
                        a["height"] >= 0.6 * height and b["height"] >= 0.6 * height
                    )
                    and (
                        max(a["height"], b["height"]) >= 0.60 * height
                        or union[3] - union[1] >= 0.75 * height
                    )
                    and union[1] >= baseline - height - 2
                    and union[3] <= baseline + 2
                )
                foot = False
                for stem, small in ((a, b), (b, a)):
                    foot |= (
                        stem["height"] >= 0.80 * height
                        and stem["width"] <= 0.4 * height
                        and small["height"]
                        <= POLICY["foot_height_glyph_fraction_maximum"] * height
                        and small["height"] * 2.5
                        <= small["width"]
                        <= POLICY["foot_width_glyph_fraction_maximum"] * height
                        and abs(small["bbox"][3] - baseline)
                        <= POLICY["foot_baseline_tolerance_px"]
                        and abs(stem["bbox"][3] - small["bbox"][3]) <= 2
                        and xg <= 1
                    )
                if not (vertical or foot):
                    continue
                rows[i] = {
                    "label": min(a["labels"] + b["labels"]),
                    "labels": sorted(a["labels"] + b["labels"]),
                    "bbox": union,
                    "width": union[2] - union[0],
                    "height": union[3] - union[1],
                    "area": a["area"] + b["area"],
                }
                joins.append(
                    {
                        "component_bboxes": [ab, bb],
                        "union_bbox": union,
                        "rule": "BOTTOM_STEM_FOOT"
                        if foot
                        else "VERTICAL_FRAGMENT_COLUMN",
                        "actual_white_gap_px": xg if foot else yg,
                        "source_samples_added": 0,
                    }
                )
                del rows[j]
                changed = True
                break
            if changed:
                break
        if not changed:
            break
    return rows, joins


def _associate_contact_fragments(
    components,
    height,
    baseline,
    original_labels,
    derived_labels,
    roi,
    gray,
    erased,
    origin,
):
    """Retain a small upper branch split by the certified graphic corridor.

    Unlike a detached quote or punctuation mark, both pieces must still be
    connected by original black samples inside their finite joint glyph box.
    The separating samples must belong to the recorded graphic corridor.
    """
    from . import single_line_labels as rows

    result = copy.deepcopy(components)
    associations = []
    for small in list(result):
        if not (
            small["area"] <= 0.12 * height * height
            and small["height"] < 0.35 * height
            and small["bbox"][3] < baseline - 0.55 * height
        ):
            continue
        alternatives = []
        for body in result:
            if (
                body is small
                or not rows._glyph(body, height, baseline)
                or body["height"] < 0.8 * height
            ):
                continue
            box = base._box_union([small["bbox"], body["bbox"]])
            gap = max(
                small["bbox"][0] - body["bbox"][2],
                body["bbox"][0] - small["bbox"][2],
                0,
            )
            if box[2] - box[0] > height or gap > 0.3 * height:
                continue
            a, b, c, d = box
            part = gray[b:d, a:c] < rows.POLICY["source_threshold"]
            _, local_labels = cv2.connectedComponents(
                part.astype(np.uint8), connectivity=8
            )
            dl = derived_labels[b - roi[1] : d - roi[1], a - roi[0] : c - roi[0]]
            sb = np.isin(dl, small["labels"])
            bb = np.isin(dl, body["labels"])
            shared_ids = set(np.unique(local_labels[sb])) & set(
                np.unique(local_labels[bb])
            ) - {0}
            if not shared_ids:
                continue
            cut = np.zeros_like(part)
            for y in range(b, d):
                if origin[1] <= y < origin[1] + erased.shape[0]:
                    lo, hi = max(a, origin[0]), min(c, origin[0] + erased.shape[1])
                    if lo < hi:
                        cut[y - b, lo - a : hi - a] = erased[
                            y - origin[1], lo - origin[0] : hi - origin[0]
                        ]
            if not np.any(cut & np.isin(local_labels, list(shared_ids))):
                continue
            alternatives.append((body, box))
        if len(alternatives) != 1:
            continue
        body, box = alternatives[0]
        merged = {
            "label": min(body["labels"] + small["labels"]),
            "labels": sorted(body["labels"] + small["labels"]),
            "bbox": box,
            "width": box[2] - box[0],
            "height": box[3] - box[1],
            "area": body["area"] + small["area"],
        }
        result.remove(body)
        result.remove(small)
        result.append(merged)
        associations.append(
            {
                "component_bboxes": [body["bbox"], small["bbox"]],
                "union_bbox": box,
                "rule": "ORIGINAL_CONNECTED_UPPER_BRANCH_ACROSS_CERTIFIED_GRAPHIC",
                "original_local_connection_proven": True,
                "source_samples_added": 0,
            }
        )
    return result, associations


def partition_text_contact_row(gray, roi, seed, *, catalog=None, context=None):
    """Return a replayable source partition and independent complete graphics."""
    from . import single_line_labels as rows

    roi, seed = rows._box_tuple(roi), rows._box_tuple(seed)
    if not base._inside(seed, roi) or not 7 <= seed[3] - seed[1] <= 90:
        return None, "CONTACT_SEED_OUTSIDE_SOURCE_ROW_SCOPE", None
    labels, original_components = (
        catalog if catalog is not None else rows._catalog(gray, roi)
    )
    initial_h = seed[3] - seed[1]
    anchors = [
        c
        for c in original_components
        if rows._glyph(c, initial_h, seed[3])
        and base._intersection(c["bbox"], seed) / max(1, base._area(c["bbox"])) >= 0.5
    ]
    if len(anchors) < POLICY["minimum_intact_row_anchors"]:
        return None, "CONTACT_ROW_LACKS_INTACT_SOURCE_BASELINE_ANCHORS", None
    graph = (context or {}).get("source_graph")
    if graph is None:
        graph = _source_graph(gray, roi)
        if context is not None:
            context["source_graph"] = graph
    plan = graphics.plan_text_contact_geometry(gray, roi, seed, source_graph=graph)
    if not plan["paths"]:
        return None, "NO_COMPLETE_INDEPENDENT_CONTACT_PATH", plan
    height = float(np.median([c["height"] for c in anchors]))
    baseline = float(np.median([c["bbox"][3] for c in anchors]))
    # A complete geometric round with a diameter greater than a row glyph is
    # an independently observed neighbor. Its interior is not a word prefix.
    rounds = [
        r
        for r in graph.rounds
        if 2 * r["inner_boundary_radius_px"]
        >= POLICY["round_diameter_glyph_height_minimum"] * height
    ]
    anchors = [
        c
        for c in anchors
        if not any(
            np.linalg.norm(
                (np.asarray(c["bbox"][:2]) + c["bbox"][2:]) / 2 - r["center"]
            )
            < r["inner_boundary_radius_px"]
            for r in rounds
        )
    ]
    if len(anchors) < POLICY["minimum_intact_row_anchors"]:
        return None, "CONTACT_ROW_ANCHORS_ARE_INDEPENDENT_ROUND_CONTENT", plan
    height = float(np.median([c["height"] for c in anchors]))
    baseline = float(np.median([c["bbox"][3] for c in anchors]))
    pad = int(math.ceil(2 * height))
    context_box = [
        max(roi[0], seed[0] - pad),
        max(roi[1], seed[1] - pad),
        min(roi[2], seed[2] + pad),
        min(roi[3], seed[3] + pad),
    ]
    x0, y0, x1, y1 = context_box
    original = gray[y0:y1, x0:x1]
    erase = np.zeros(original.shape, bool)
    shared = np.zeros_like(erase)
    for path in plan["paths"]:
        _mark(erase, path["line_runs"], [x0, y0])
        _mark(shared, path["shared_contact_runs"], [x0, y0])
    erase &= ~shared
    excluded_rounds = []
    yy, xx = np.mgrid[y0:y1, x0:x1]
    for circle in rounds:
        cx, cy = circle["center"]
        radius = (
            circle["inner_boundary_radius_px"] + POLICY["round_source_outer_margin_px"]
        )
        disk = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
        if (disk & (original < rows.POLICY["source_threshold"])).any():
            erase |= disk
            excluded_rounds.append(circle)
    # Independently bounded original glyph anchors cannot be removed merely
    # because their bounding box is close to a fitted round perimeter.
    local_labels = labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]]
    erase &= ~np.isin(local_labels, [c["label"] for c in anchors])
    erase &= original < rows.POLICY["source_threshold"]
    row_band = [
        max(x0, seed[0]),
        max(y0, int(baseline - height)),
        min(x1, seed[2]),
        min(y1, int(baseline) + 2),
    ]
    if not erase[
        row_band[1] - y0 : row_band[3] - y0, row_band[0] - x0 : row_band[2] - x0
    ].any():
        return None, "NO_SHARED_GRAPHIC_IN_SOURCE_ROW", plan
    if context is not None:
        context.setdefault("plans", {})[tuple(seed)] = plan
    separated = gray.copy()
    separated[y0:y1, x0:x1][erase] = 255
    derived_labels, components = rows._catalog(separated, roi)
    components, joins = _join_fragments(components, height, baseline)
    components, contact_joins = _associate_contact_fragments(
        components, height, baseline, labels, derived_labels, roi, gray, erase, [x0, y0]
    )
    joins.extend(contact_joins)
    source_seed = [
        seed[0],
        int(math.floor(baseline - height)),
        seed[2],
        int(math.ceil(baseline)),
    ]
    body, reason = rows._partition_original_row(
        separated, roi, source_seed, catalog=(derived_labels, components)
    )
    if body is None:
        return None, reason, plan
    body["seed_bbox_xyxy_px"] = seed
    for component in body["components"]:
        original_ids = set()
        for y, a, b in component["source_runs_y_x0_x1"]:
            original_ids.update(
                int(v)
                for v in np.unique(labels[y - roi[1], a - roi[0] : b - roi[0]])
                if v
            )
        component["derived_partition_component_labels"] = component[
            "source_component_labels"
        ]
        component["source_component_labels"] = sorted(original_ids)
    box = body["bbox_xyxy_px"]
    actual = gray[box[1] : box[3], box[0] : box[2]]
    support = np.zeros(actual.shape, bool)
    _mark(support, body["source_support_runs_y_x0_x1"], box[:2])
    excluded = (actual < rows.POLICY["source_threshold"]) & ~support
    body["recognition_excluded_graphic_runs_y_x0_x1"] = base._rle(excluded, box[:2])
    body["recognition_excluded_graphic_pixels"] = int(excluded.sum())
    body["source_crop_array_sha256"] = base.source_array_sha256(actual)
    cb = body["context_bbox_xyxy_px"]
    body["context_array_sha256"] = base.source_array_sha256(
        gray[cb[1] : cb[3], cb[0] : cb[2]]
    )
    body["source_components_cut"] = True
    body["source_component_catalog_basis"] = (
        "original_graph_with_recorded_contact_subcomponents"
    )
    body["text_contact_separation"] = {
        "schema": "complete-original-contact-row-separation-v1",
        "policy": POLICY,
        "geometry_plan": plan,
        "intact_baseline_anchor_bboxes": [c["bbox"] for c in anchors],
        "source_baseline_px": baseline,
        "source_glyph_height_px": height,
        "derived_partition_seed_bbox_xyxy_px": source_seed,
        "recognition_context_bbox_xyxy_px": context_box,
        "recognition_context_array_sha256": base.source_array_sha256(original),
        "recognition_excluded_source_runs": base._rle(erase, [x0, y0]),
        "shared_original_contact_runs": base._rle(shared, [x0, y0]),
        "independent_round_observations": excluded_rounds,
        "source_fragment_associations": joins,
        "source_erasure_authorized": False,
        "source_pixels_added": 0,
        "real_source_white_gaps_filled": False,
        "independent_graphics_require_separate_adoption": True,
    }
    return body, None, plan
