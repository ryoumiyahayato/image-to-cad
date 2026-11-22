"""Two-way review of the actual saved DXF against this job's source pixels.

Runtime capability is local OCR evidence plus deterministic geometry, identity,
structure and raster checks. It is not a deployed general vision model or the
chat assistant's visual judgement. Unknown source is retained as whole original
connected-ink groups, including one-pixel components; a navigation grid is never
used as the repair inventory. No source pixel or CAD entity is changed here.
"""

from __future__ import annotations

from .performance import profiled
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import time

import ezdxf
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

from . import cad_io
from .contracts import TOLERANCES, save_json, validate_text_regions
from .review_binding import (
    build_review_binding,
    canonical_sha256,
    file_sha256,
    reviewer_code_identity,
    verify_saved_review,
)


SCHEMA = "native-quality-review-v4"
POLICY = {
    "review_version": "actual-dxf-bidirectional-local-rules-v4.1",
    "source_ink_threshold": 128,
    "independent_render_threshold": 128,
    "source_connected_group_connectivity": 8,
    "minimum_source_component_area": None,
    "line_support_distance_px": TOLERANCES["line_perpendicular_px"],
    "arc_support_distance_px": TOLERANCES["arc_radial_px"],
    "reverse_geometry_sample_step_px": 0.25,
    "geometric_proximity_is_source_ownership": False,
    "thresholds_changed_to_pass": False,
    "engineering_semantic_classifier": None,
    "deployed_general_vision_model": None,
    "online_service_calls": 0,
    "online_service_wait_seconds": 0.0,
}


def _numeric_equal(a, b):
    left, right = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if (
        left.shape != right.shape
        or not np.isfinite(left).all()
        or not np.isfinite(right).all()
    ):
        return False
    scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), 1.0)
    return bool(np.all(np.abs(left - right) <= 64 * np.spacing(scale)))


def _box(value):
    """Derive locations from supplied evidence, never from fixed case IDs."""
    if not isinstance(value, dict):
        return None
    for key in ("bbox_xyxy_px", "component_bbox_xyxy_px", "source_bbox_xyxy_px"):
        candidate = value.get(key)
        if isinstance(candidate, (list, tuple)) and len(candidate) == 4:
            a = np.asarray(candidate, dtype=float)
            if np.isfinite(a).all() and a[2] >= a[0] and a[3] >= a[1]:
                return a.tolist()
    points = []
    for key in ("start", "end", "hinge", "center"):
        p = value.get(key)
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            points.append(p[:2])
    for key in ("points", "frame_points", "source_path_points"):
        sequence = value.get(key)
        if isinstance(sequence, (list, tuple)):
            points += [
                p[:2] for p in sequence if isinstance(p, (list, tuple)) and len(p) >= 2
            ]
    if all(key in value for key in ("x", "y", "width_px", "height_px")):
        x, y, w, h = (float(value[k]) for k in ("x", "y", "width_px", "height_px"))
        points += [[x, y - h], [x + w, y]]
    nested = []
    for key in (
        "geometry",
        "source_evidence",
        "object",
        "text_geometry",
        "circle_geometry",
    ):
        candidate = _box(value.get(key))
        if candidate is not None:
            nested += [candidate[:2], candidate[2:]]
    for key in ("leaves", "members", "native_members", "frame_source_remainders"):
        for member in value.get(key, []) or []:
            candidate = _box(member)
            if candidate is not None:
                nested += [candidate[:2], candidate[2:]]
    points += nested
    if not points:
        return None
    array = np.asarray(points, dtype=float)
    if not np.isfinite(array).all():
        return None
    lo, hi = array.min(axis=0), array.max(axis=0)
    # A centre alone is not a usable arc bounds estimate.
    if value.get("radius_px") is not None and value.get("center") is not None:
        centre, radius = np.asarray(value["center"], float), float(value["radius_px"])
        lo, hi = np.minimum(lo, centre - radius), np.maximum(hi, centre + radius)
    return [*lo.tolist(), *hi.tolist()]


def _intersects(a, b):
    return (
        a is not None
        and b is not None
        and max(a[0], b[0]) <= min(a[2], b[2])
        and max(a[1], b[1]) <= min(a[3], b[3])
    )


def _issue(
    reason,
    bbox=None,
    *,
    status="PENDING_SOURCE_REPAIR",
    object_ids=(),
    member_refs=(),
    source_group_ids=(),
    support=None,
    severity="review",
    discriminator=None,
):
    payload = {
        "reason": str(reason),
        "bbox_xyxy_px": bbox,
        "object_ids": sorted(set(object_ids)),
        "member_refs": list(member_refs),
        "source_group_ids": list(source_group_ids),
        "discriminator": discriminator,
    }
    return {
        "id": "ISSUE-" + canonical_sha256(payload)[:16],
        "bbox_xyxy_px": bbox,
        "coordinate_system": "job_working_pixels_top_left",
        "unlocalized": bbox is None,
        "reason": str(reason),
        "reasons": [str(reason)],
        "status": status,
        "severity": severity,
        "object_ids": payload["object_ids"],
        "member_refs": list(member_refs),
        "source_group_ids": list(source_group_ids),
        "source_support": support or {},
    }


def _expanded(entity, depth=0):
    if depth > 16:
        raise ValueError("NESTED_BLOCK_DEPTH_OR_CYCLE_EXCEEDS_REVIEW_BOUND")
    if entity.dxftype() == "INSERT":
        result = []
        for child in entity.virtual_entities():
            result.extend(_expanded(child, depth + 1))
        return result
    return [entity]


def _path_points(entity, pixel_from_cad, mm):
    """Samples of cold-read CAD geometry; never clipped to source ink."""
    typ = entity.dxftype()
    step = POLICY["reverse_geometry_sample_step_px"]
    if typ == "LINE":
        start, end = pixel_from_cad(entity.dxf.start), pixel_from_cad(entity.dxf.end)
        count = max(2, int(math.ceil(float(np.linalg.norm(end - start)) / step)) + 1)
        return [(np.linspace(start, end, count), "LINE")]
    if typ in ("ARC", "CIRCLE"):
        centre, radius = (
            pixel_from_cad(entity.dxf.center),
            float(entity.dxf.radius) / mm,
        )
        start = float(entity.dxf.start_angle) if typ == "ARC" else 0.0
        sweep = (float(entity.dxf.end_angle) - start) % 360 if typ == "ARC" else 360.0
        count = max(3, int(math.ceil(radius * math.radians(sweep) / step)) + 1)
        angle = np.deg2rad(np.linspace(start, start + sweep, count))
        return [
            (centre + radius * np.column_stack((np.cos(angle), -np.sin(angle))), "ARC")
        ]
    if typ == "LWPOLYLINE":
        result = []
        # virtual_entities preserves true bulge arcs; do not join endpoints
        # across an intended gap or silently render bulges as straight chords.
        for segment in entity.virtual_entities():
            result.extend(_path_points(segment, pixel_from_cad, mm))
        return result
    return []


def _member_definition(obj):
    g, kind = obj["geometry"], obj["kind"]
    if kind == "WALL_SEGMENT":
        return g["members"]
    if kind == "DOOR":
        if g.get("native_members") is not None:
            return g["native_members"]
        result = []
        for leaf in g.get("leaves", [g]):
            centre = np.asarray(leaf["hinge"], float)
            radius = float(leaf["radius_px"])
            theta = math.radians(float(leaf["leaf_angle_deg_image"]))
            result += [
                {
                    "kind": "LINE",
                    "geometry": {
                        "start": centre.tolist(),
                        "end": (
                            centre
                            + radius * np.array([math.cos(theta), math.sin(theta)])
                        ).tolist(),
                    },
                },
                {
                    "kind": "ARC",
                    "geometry": {
                        "center": centre.tolist(),
                        "radius_px": radius,
                        "start_deg_image": leaf["start_deg_image"],
                        "end_deg_image": leaf["end_deg_image"],
                        "sweep_deg_image": leaf.get(
                            "sweep_deg_image",
                            leaf["end_deg_image"] - leaf["start_deg_image"],
                        ),
                    },
                },
            ]
        return result
    return []


def _matches_member(member, expected, pixel_from_cad, mm):
    kind, g = expected["kind"], expected["geometry"]
    if member.dxftype() != kind:
        return False
    if kind == "LINE":
        return _numeric_equal(
            pixel_from_cad(member.dxf.start), g["start"]
        ) and _numeric_equal(pixel_from_cad(member.dxf.end), g["end"])
    if kind == "CIRCLE":
        return (
            _numeric_equal(pixel_from_cad(member.dxf.center), g["center"])
            and _numeric_equal(float(member.dxf.radius) / mm, g["radius_px"])
            and float(g["radius_px"]) > 0
        )
    if kind == "ARC":
        if not _numeric_equal(
            pixel_from_cad(member.dxf.center), g["center"]
        ) or not _numeric_equal(float(member.dxf.radius) / mm, g["radius_px"]):
            return False
        expected_ends = [
            np.asarray(g["center"], float)
            + float(g["radius_px"])
            * np.array(
                [
                    math.cos(math.radians(float(g[key]))),
                    math.sin(math.radians(float(g[key]))),
                ]
            )
            for key in ("start_deg_image", "end_deg_image")
        ]
        centre = pixel_from_cad(member.dxf.center)
        actual_ends = [
            centre
            + float(member.dxf.radius)
            / mm
            * np.array(
                [
                    math.cos(math.radians(float(member.dxf.get(key)))),
                    -math.sin(math.radians(float(member.dxf.get(key)))),
                ]
            )
            for key in ("start_angle", "end_angle")
        ]
        matched = (
            _numeric_equal(actual_ends[0], expected_ends[0])
            and _numeric_equal(actual_ends[1], expected_ends[1])
        ) or (
            _numeric_equal(actual_ends[0], expected_ends[1])
            and _numeric_equal(actual_ends[1], expected_ends[0])
        )
        sweep = (float(member.dxf.end_angle) - float(member.dxf.start_angle)) % 360
        return matched and _numeric_equal(
            sweep,
            abs(
                float(
                    g.get("sweep_deg_image", g["end_deg_image"] - g["start_deg_image"])
                )
            ),
        )
    return False


def _candidate_geometry_checks(entity, obj, members, pixel_from_cad, mm):
    """Exact exported parameters with 64-ULP serialization allowance only."""
    kind, g = obj["kind"], obj["geometry"]
    expected_type = {
        "LINE": "LINE",
        "ARC": "ARC",
        "CIRCLE": "CIRCLE",
        "CIRCULAR_MARKER": "INSERT",
        "CONNECTION_PATH": "LWPOLYLINE",
        "TEXT": "TEXT",
        "MTEXT": "MTEXT",
        "ROOM_LABEL": "INSERT",
        "WALL_SEGMENT": "INSERT",
        "DOOR": "INSERT",
    }.get(kind)
    checks = {
        "native_entity_type": entity.dxftype() == expected_type,
        "candidate_layer": entity.dxf.layer == obj["layer"],
        "all_members_have_finite_parameters": True,
        "entities_not_explicitly_invisible": all(
            not bool(m.dxf.get("invisible", 0)) for m in [entity] + members
        ),
    }
    try:
        for member in [entity] + members:
            for value in member.dxf.all_existing_dxf_attribs().values():
                if hasattr(value, "x") and not all(
                    math.isfinite(float(x)) for x in value
                ):
                    checks["all_members_have_finite_parameters"] = False
                elif isinstance(value, float) and not math.isfinite(value):
                    checks["all_members_have_finite_parameters"] = False
        if not checks["native_entity_type"]:
            return checks
        if kind == "LINE":
            checks["endpoints_match_candidate"] = _matches_member(
                entity, {"kind": "LINE", "geometry": g}, pixel_from_cad, mm
            )
            checks["nonzero_length"] = not _numeric_equal(g["start"], g["end"])
        elif kind == "ARC":
            checks["observed_arc_parameters_match_candidate"] = _matches_member(
                entity, {"kind": "ARC", "geometry": g}, pixel_from_cad, mm
            )
            checks["observed_sweep_is_open"] = (
                0
                < abs(
                    float(
                        g.get(
                            "sweep_deg_image", g["end_deg_image"] - g["start_deg_image"]
                        )
                    )
                )
                < 360
            )
        elif kind in ("CIRCLE", "CIRCULAR_MARKER"):
            checks.update(
                cad_io.circular_candidate_contract(entity, obj, pixel_from_cad, mm)
            )
        elif kind == "CONNECTION_PATH":
            vertices = list(entity.get_points("xyseb"))
            checks["whole_open_chain"] = (
                len(vertices) == len(g["points"]) >= 2 and not entity.closed
            )
            checks["vertices_match_candidate"] = len(vertices) == len(
                g["points"]
            ) and all(
                _numeric_equal(pixel_from_cad(p), q)
                for p, q in zip(vertices, g["points"])
            )
            checks["bulges_match_source_reflection"] = _numeric_equal(
                [v[4] for v in vertices],
                [-float(v) for v in g.get("bulges", [0.0] * len(g["points"]))],
            )
            checks["no_invented_width"] = (
                all(v[2] == 0 and v[3] == 0 for v in vertices)
                and float(entity.dxf.get("const_width", 0.0)) == 0.0
            )
        elif kind in ("WALL_SEGMENT", "DOOR"):
            expected = _member_definition(obj)
            checks["whole_native_member_set"] = len(members) == len(expected) and all(
                _matches_member(m, e, pixel_from_cad, mm)
                for m, e in zip(members, expected)
            )
        elif kind == "ROOM_LABEL":
            frames = [m for m in members if m.dxftype() == "LWPOLYLINE"]
            strings = [m for m in members if m.dxftype() == "TEXT"]
            tails = [m for m in members if m.dxftype() == "LINE"]
            checks["complete_closed_frame"] = (
                len(frames) == 1
                and frames[0].closed
                and len(frames[0]) == len(g["frame_points"])
            )
            checks["frame_vertices_match_candidate"] = len(
                frames
            ) == 1 and _numeric_equal(
                [pixel_from_cad(v).tolist() for v in frames[0].get_points("xy")],
                g["frame_points"],
            )
            checks["true_editable_number_TEXT"] = (
                len(strings) == 1 and strings[0].dxf.text == g["text_geometry"]["text"]
            )
            if len(strings) == 1:
                text_checks = _candidate_geometry_checks(
                    strings[0],
                    {
                        "kind": "TEXT",
                        "geometry": g["text_geometry"],
                        "layer": strings[0].dxf.layer,
                    },
                    [strings[0]],
                    pixel_from_cad,
                    mm,
                )
                checks.update(
                    {"room_text_" + key: value for key, value in text_checks.items()}
                )
            checks["all_source_remainder_members_explicit"] = len(tails) == len(
                g.get("frame_source_remainders", [])
            ) and all(
                _matches_member(m, e, pixel_from_cad, mm)
                for m, e in zip(tails, g.get("frame_source_remainders", []))
            )
            checks["no_unexpected_members"] = len(members) == 2 + len(tails)
        elif kind == "TEXT":
            checks["literal_content_matches_candidate"] = entity.dxf.text == g["text"]
            checks["height_matches_candidate"] = _numeric_equal(
                float(entity.dxf.height) / mm, g["height_px"]
            )
            checks["insertion_matches_candidate"] = _numeric_equal(
                pixel_from_cad(entity.dxf.insert), [g["x"], g["y"]]
            )
            checks["rotation_matches_candidate"] = _numeric_equal(
                (
                    float(entity.dxf.get("rotation", 0.0))
                    + float(g.get("rotation_deg_image", 0.0))
                )
                % 360,
                0.0,
            )
            checks["positive_width_factor"] = (
                math.isfinite(float(entity.dxf.get("width", 1.0)))
                and float(entity.dxf.get("width", 1.0)) > 0
            )
            checks["source_baseline_alignment"] = (
                int(entity.dxf.get("halign", 0)) == 0
                and int(entity.dxf.get("valign", 0)) == 0
            )
        elif kind == "MTEXT":
            checks["all_literal_lines_match_candidate"] = (
                entity.plain_text().splitlines() == g["lines"]
            )
            checks["height_matches_candidate"] = _numeric_equal(
                float(entity.dxf.char_height) / mm, g["height_px"]
            )
            checks["insertion_matches_candidate"] = _numeric_equal(
                pixel_from_cad(entity.dxf.insert), [g["x"], g["y"]]
            )
            checks["ordered_source_line_layout_available"] = len(
                g.get("source_line_geometries", [])
            ) == len(g["lines"])
            checks["source_text_block_top_left_attachment"] = (
                int(entity.dxf.attachment_point) == 1
            )
            checks["declared_text_box_width"] = _numeric_equal(
                float(entity.dxf.width) / mm, float(g["width_px"]) * 1.03
            )
            checks["declared_line_pitch"] = _numeric_equal(
                float(entity.dxf.line_spacing_factor),
                float(
                    np.clip(
                        g.get("line_pitch_px", g["height_px"] * 1.5)
                        / (g["height_px"] * (5 / 3)),
                        0.25,
                        4,
                    )
                ),
            )
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        checks["candidate_geometry_contract_readable"] = False
        checks["contract_error"] = type(exc).__name__ + ": " + str(exc)
    return checks


def _font_dependencies(doc, dxf_path):
    """Read actual style references and portable font bytes; never install fonts."""
    directory, rows, assets = Path(dxf_path).parent, [], []
    style_names = {
        entity.dxf.get("style", "Standard")
        for entity in doc.modelspace()
        if entity.dxftype() in ("TEXT", "MTEXT")
    }
    for block in doc.blocks:
        style_names.update(
            entity.dxf.get("style", "Standard")
            for entity in block
            if entity.dxftype() in ("TEXT", "MTEXT")
        )
    for name in sorted(style_names):
        row = {"style": name, "style_exists": name in doc.styles}
        if row["style_exists"]:
            style = doc.styles.get(name)
            filename = str(style.dxf.get("font", ""))
            # Native output is portable only when the referenced font is a
            # basename beside the DXF. System-font fallback is not proof.
            row.update(
                {
                    "font_reference": filename,
                    "font_reference_is_portable_basename": bool(filename)
                    and Path(filename).name == filename
                    and "\\" not in filename,
                }
            )
            font = directory / filename
            row["bundled_font_available"] = (
                row["font_reference_is_portable_basename"] and font.is_file()
            )
            if row["bundled_font_available"]:
                row["font_sha256"] = file_sha256(font)
                assets.append(font)
            row["font_style_width_factor"] = float(style.dxf.get("width", 1.0))
            row["font_style_oblique_degrees"] = float(style.dxf.get("oblique", 0.0))
        row["pass"] = bool(row["style_exists"] and row.get("bundled_font_available"))
        rows.append(row)
    if any(row.get("font_reference") == "DejaVuSans.ttf" for row in rows):
        license_path = directory / "FONT_LICENSE_DejaVu.txt"
        rows.append(
            {
                "dependency": "font_license",
                "filename": license_path.name,
                "pass": license_path.is_file(),
            }
        )
        if license_path.is_file():
            assets.append(license_path)
    return rows, assets


def _connection_checkpoint_scope(import_manifest, roi):
    """Validate an explicit local review scope without changing source pixels."""
    if "connection_checkpoint" not in import_manifest:
        return None, None
    checkpoint = import_manifest["connection_checkpoint"]
    required = {"manifest_sha256", "baseline_dxf_sha256", "context_rois"}
    if not isinstance(checkpoint, dict) or set(checkpoint) != required:
        raise ValueError("REVIEW_CONNECTION_CHECKPOINT_FIELDS_INVALID")
    for key in ("manifest_sha256", "baseline_dxf_sha256"):
        digest = checkpoint[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("REVIEW_CONNECTION_CHECKPOINT_HASH_INVALID:" + key)
    contexts = checkpoint["context_rois"]
    if not isinstance(contexts, (list, tuple)) or not 1 <= len(contexts) <= 8:
        raise ValueError("REVIEW_CONNECTION_CHECKPOINT_REQUIRES_1_TO_8_CONTEXTS")
    x0, y0, x1, y1 = roi
    normalized = []
    for context in contexts:
        if (
            not isinstance(context, (list, tuple))
            or len(context) != 4
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in context)
        ):
            raise ValueError("REVIEW_CONNECTION_CONTEXT_INTEGER_ROI_REQUIRED")
        a, b, c, d = context
        if not (x0 <= a < c <= x1 and y0 <= b < d <= y1):
            raise ValueError("REVIEW_CONNECTION_CONTEXT_OUTSIDE_PARENT_ROI")
        normalized.append(list(context))
    mask = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    for a, b, c, d in normalized:
        mask[b - y0 : d - y0, a - x0 : c - x0] = True
    scope = {
        "mode": "CONNECTION_CHECKPOINT_CONTEXT_UNION",
        "parent_roi_xyxy_px": list(roi),
        "context_rois": normalized,
        "context_union_pixel_count": int(np.count_nonzero(mask)),
        "parent_roi_pixel_count": int(mask.size),
        "manifest_sha256": checkpoint["manifest_sha256"],
        "baseline_dxf_sha256": checkpoint["baseline_dxf_sha256"],
        "connection_checkpoint_sha256": canonical_sha256(checkpoint),
        "source_to_output_scope": "ONLY_ORIGINAL_PIXELS_WITHIN_CONTEXT_UNION",
        "output_to_source_scope": "ALL_SAVED_FORMAL_ENTITIES_INCLUDING_PRESERVED_NEIGHBORS",
        "source_pixels_changed": False,
        "full_parent_region_review_performed": False,
        "limitation": (
            "This local source review does not establish completeness or acceptance "
            "of the parent region. Context-boundary groups have unverified full "
            "extent. Every saved formal entity still receives structure and "
            "cold source checks, including geometry outside the contexts."
        ),
    }
    return scope, mask


def _topology(mask, scope_mask=None):
    result = {}
    for connectivity, structure in (
        (4, ndimage.generate_binary_structure(2, 1)),
        (8, np.ones((3, 3), bool)),
    ):
        _, ink_count = ndimage.label(mask, structure)
        paper = ~mask if scope_mask is None else scope_mask & ~mask
        paper_labels, paper_count = ndimage.label(paper, structure)
        if scope_mask is None:
            edge_labels = set(
                np.concatenate(
                    (
                        paper_labels[0],
                        paper_labels[-1],
                        paper_labels[:, 0],
                        paper_labels[:, -1],
                    )
                ).tolist()
            )
        else:
            frame = scope_mask & ~ndimage.binary_erosion(
                scope_mask, structure=structure, border_value=0
            )
            edge_labels = set(paper_labels[frame].tolist())
        edge_labels.discard(0)
        result[str(connectivity)] = {
            "ink_components": int(ink_count),
            "paper_components": int(paper_count),
            (
                "paper_components_not_touching_ROI_frame"
                if scope_mask is None
                else "paper_components_not_touching_context_union_frame"
            ): int(paper_count - len(edge_labels)),
        }
    return result


def _runs(mask, x_origin, y_origin):
    runs = []
    for row_index, row in enumerate(mask):
        changes = np.diff(np.r_[False, row, False].astype(np.int8))
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        runs.extend(
            [int(y_origin + row_index), int(x_origin + start), int(x_origin + end)]
            for start, end in zip(starts, ends)
        )
    return runs


def _source_groups(
    source_mask,
    render_mask,
    line_samples,
    arc_samples,
    object_bounds,
    text_boxes,
    roi,
    identity_hash,
    *,
    scope_mask=None,
):
    """Retain every in-scope source pixel; mark any context-clipped fragment."""
    x0, y0, _, _ = roi
    labels, count = ndimage.label(source_mask, np.ones((3, 3), bool))
    slices = ndimage.find_objects(labels)
    scope_frame = (
        None
        if scope_mask is None
        else scope_mask
        & ~ndimage.binary_erosion(
            scope_mask, structure=np.ones((3, 3), bool), border_value=0
        )
    )
    yy, xx = np.nonzero(source_mask)
    points = np.column_stack((xx + x0, yy + y0)).astype(float)
    near = np.zeros(len(points), bool)
    for samples, tolerance in (
        (line_samples, POLICY["line_support_distance_px"]),
        (arc_samples, POLICY["arc_support_distance_px"]),
    ):
        if samples and len(points):
            array = np.concatenate(samples, axis=0)
            if len(array):
                # Dense samples are a conservative geometric proximity witness;
                # no dilation, source smoothing or owner identity is inferred.
                distance, _ = cKDTree(array).query(
                    points, k=1, distance_upper_bound=tolerance
                )
                near |= np.isfinite(distance)
    near_mask = np.zeros_like(source_mask)
    near_mask[yy, xx] = near
    exact = source_mask & render_mask
    possible_text = np.zeros_like(source_mask)
    for box in text_boxes:
        a, b, c, d = box
        left, top = max(0, int(math.floor(a - x0))), max(0, int(math.floor(b - y0)))
        right, bottom = (
            min(source_mask.shape[1], int(math.ceil(c - x0))),
            min(source_mask.shape[0], int(math.ceil(d - y0))),
        )
        if right > left and bottom > top:
            possible_text[top:bottom, left:right] |= source_mask[top:bottom, left:right]
    unrepresented = source_mask & ~exact & ~near_mask
    groups, issues = [], []
    for index, window in enumerate(slices, start=1):
        if window is None:
            raise ValueError("SOURCE_COMPONENT_LABEL_GAP")
        sy, sx = window
        local = labels[window] == index
        area = int(np.count_nonzero(local))
        bounds = [sx.start + x0, sy.start + y0, sx.stop + x0, sy.stop + y0]
        exact_count = int(np.count_nonzero(exact[window] & local))
        proximity_count = int(np.count_nonzero(near_mask[window] & local))
        missing_count = int(np.count_nonzero(unrepresented[window] & local))
        text_count = int(np.count_nonzero(possible_text[window] & local))
        touches_frame = (
            sx.start == 0
            or sy.start == 0
            or sx.stop == source_mask.shape[1]
            or sy.stop == source_mask.shape[0]
        )
        touches_scope_frame = bool(
            scope_frame is not None and np.any(scope_frame[window] & local)
        )
        group_id = "SRC-" + canonical_sha256([identity_hash, bounds, index, area])[:16]
        linked = sorted(
            oid for oid, box in object_bounds.items() if _intersects(bounds, box)
        )
        if missing_count:
            reason, status = (
                "UNEXPLAINED_OR_PARTLY_RECONSTRUCTED_SOURCE_GROUP",
                "PENDING_SOURCE_REPAIR",
            )
        elif text_count:
            reason, status = (
                "TEXT_OR_SHARED_INK_GROUP_REQUIRES_CONTENT_AND_OWNERSHIP_REVIEW",
                "REVIEW_TEXT_OR_SHARED_SOURCE",
            )
        elif touches_scope_frame:
            reason, status = (
                "SOURCE_GROUP_EXTENT_UNVERIFIED_AT_CONTEXT_SCOPE_BOUNDARY",
                "REVIEW_OBJECT_EXTENT",
            )
        elif touches_frame:
            reason, status = (
                "SOURCE_GROUP_CLIPPED_BY_SELECTED_REGION",
                "REVIEW_OBJECT_EXTENT",
            )
        elif exact_count < area:
            reason, status = (
                "TOLERANCE_SUPPORT_WITHOUT_FULL_RASTER_SOURCE_REPLACEMENT",
                "REVIEW_SOURCE_SHAPE",
            )
        else:
            reason, status = None, "SOURCE_PIXELS_REPRESENTED_NOT_SEMANTIC_PROOF"
        support = {
            "source_pixel_count": area,
            "exact_source_render_ink_intersection": exact_count,
            "within_existing_native_geometry_distance": proximity_count,
            "neither_rendered_nor_near_verified_geometry": missing_count,
            "inside_current_text_localization": text_count,
            "bbox_contact_is_not_ownership": True,
            "touches_ROI_frame": touches_frame,
        }
        if scope_mask is not None:
            support.update(
                {
                    "touches_context_union_frame": touches_scope_frame,
                    "complete_source_component_extent_in_scope": not touches_scope_frame,
                    "outside_context_source_not_analyzed": True,
                }
            )
        group = {
            "id": group_id,
            "bbox_xyxy_px": bounds,
            "status": status,
            "support": support,
            "coordinate_system": "job_working_pixels_top_left",
            "connectivity": 8,
            "grouping_meaning": "original connected ink; may include several crossing/shared engineering objects",
            "source_runs_y_x0_x1": _runs(local, sx.start + x0, sy.start + y0),
            "possible_object_ids_by_bbox_contact": linked,
            "unique_engineering_owner_proven": False,
            "minimum_area_filter_applied": False,
        }
        groups.append(group)
        if scope_mask is not None:
            group["grouping_meaning"] = (
                "original connected ink within context union; boundary fragments "
                "are not complete original components or editable objects"
            )
        if reason:
            issues.append(
                _issue(
                    reason,
                    bounds,
                    status=status,
                    object_ids=linked,
                    source_group_ids=[group_id],
                    support=support,
                )
            )
        if touches_scope_frame and status != "REVIEW_OBJECT_EXTENT":
            # Missing pixels and text contact must remain accurately reported;
            # neither cancels the additional, independent extent limitation.
            issues.append(
                _issue(
                    "SOURCE_GROUP_EXTENT_UNVERIFIED_AT_CONTEXT_SCOPE_BOUNDARY",
                    bounds,
                    status="REVIEW_OBJECT_EXTENT",
                    object_ids=linked,
                    source_group_ids=[group_id],
                    support=support,
                )
            )
    counts = {
        "source_ink_pixels": int(source_mask.sum()),
        "rendered_ink_pixels": int(render_mask.sum()),
        "exact_source_render_overlap_pixels": int(exact.sum()),
        "rendered_black_on_source_white_pixels": int(
            np.count_nonzero(render_mask & ~source_mask)
        ),
        "source_not_black_in_render_pixels": int(
            np.count_nonzero(source_mask & ~render_mask)
        ),
        "source_near_actual_native_geometry_pixels": int(near_mask.sum()),
        "source_neither_rendered_nor_near_verified_geometry_pixels": int(
            unrepresented.sum()
        ),
        "source_group_count": int(count),
        "all_source_pixels_in_group_ledger": sum(
            g["support"]["source_pixel_count"] for g in groups
        )
        == int(source_mask.sum()),
        "all_source_group_pixel_runs_accounted": sum(
            sum(end - start for _, start, end in g["source_runs_y_x0_x1"])
            for g in groups
        )
        == int(source_mask.sum()),
        "one_pixel_groups_preserved": sum(
            g["support"]["source_pixel_count"] == 1 for g in groups
        ),
        "geometry_distance_is_not_full_coverage": True,
        "mask_thresholds": [128, 128],
    }
    return groups, issues, counts, unrepresented


def _circular_composition_summary(circular_rows, candidate_by_id):
    """A circle and TEXT can be intact while an external relation remains open."""
    pending = {
        oid for oid, obj in candidate_by_id.items()
        if obj.get("source_evidence", {}).get("external_endpoint_contact_review", {}).get("status")
        == "NEARBY_EXTERNAL_ENDPOINT_RELATION_PENDING"
    }
    valid = [row for row in circular_rows
             if row["candidate_structure_matches"] and row["source_geometry_gate_pass"]]
    compositions = [row for row in valid if row["kind"] == "CIRCULAR_MARKER"]
    pending_count = sum(row["id"] in pending for row in compositions)
    boundaries = sum(row["kind"] == "CIRCLE" for row in valid)
    return {
        "complete_marker_objects": len(compositions) - pending_count,
        "circle_text_compositions": len(compositions),
        "circle_text_compositions_with_external_contacts_pending": pending_count,
        "partial_circle_boundary_objects": boundaries,
        "partial_compositions": boundaries + pending_count,
        "circle_plus_text_is_one_marker_not_two": True,
        "GUI_and_engineer_validation_not_inferred": True,
    }


@profiled("quality_review.run_quality_review")
def run_quality_review(
    dxf_path,
    gray,
    roi,
    dpi,
    objects,
    texts,
    uncertainties,
    import_manifest,
    out_dir,
    *,
    cold_audit=None,
    render=None,
):
    """Review this candidate after save/cold-read/render; no chat allow-list.

    Pass already-generated ``cold_audit`` and ``render`` to avoid repeating
    their expensive stages. The caller must obtain both for this job; this
    function verifies the saved DXF SHA and image dimensions. Source/group
    analysis and candidate structure are recomputed from the current pixels.
    """
    started = time.perf_counter()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "quality_review.json"
    if report_path.exists():
        raise FileExistsError(
            "REVIEW_ALREADY_EXISTS_USE_NEW_ATTEMPT_OR_EXPLICIT_BINDING_VALIDATION"
        )
    binding = build_review_binding(dxf_path, objects, import_manifest, gray=gray)
    roi = tuple(map(int, roi))
    if (
        list(roi) != import_manifest["coordinates"]["working_ROI_xyxy_px"]
        or int(dpi) != import_manifest["job"]["recognition_dpi"]
    ):
        raise ValueError("REVIEW_COORDINATES_OR_DPI_MISMATCH")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0]):
        raise ValueError("REVIEW_ROI_OUTSIDE_WORKING_PIXELS")
    review_scope, scope_mask = _connection_checkpoint_scope(import_manifest, roi)
    validate_text_regions(texts, gray.shape, roi)
    if (
        texts.get("source_array_sha256")
        != binding["source_identity"]["working_array_sha256"]
    ):
        raise ValueError("REVIEW_TEXT_EVIDENCE_NOT_FOR_CURRENT_WORKING_PIXELS")
    original_sha = binding["saved_DXF_sha256"]
    if cold_audit is None:
        cold_audit = cad_io.cold_audit(
            dxf_path, gray, roi, dpi, out / "quality_independent_cold_audit.json"
        )
    if cold_audit.get("dxf_sha256") != original_sha or not cold_audit.get(
        "dxf_unchanged"
    ):
        raise ValueError("REVIEW_COLD_AUDIT_NOT_FOR_CURRENT_SAVED_DXF")
    if render is None:
        render = cad_io.render_saved(dxf_path, out / "quality_DXF_render.png", roi, dpi)
    if (
        render.get("renderer") != "official_ezdxf_to_MuPDF"
        or render.get("DXF_sha256") != original_sha
    ):
        raise ValueError("REVIEW_INDEPENDENT_RENDER_NOT_FOR_CURRENT_SAVED_DXF")
    rendered_path = Path(render["png_path"])
    with Image.open(rendered_path) as image:
        if image.size != (x1 - x0, y1 - y0):
            raise ValueError("REVIEW_RENDER_PIXEL_GRID_MISMATCH")
        render_mask = (
            np.asarray(image.convert("L")) < POLICY["independent_render_threshold"]
        )
    source_mask = gray[y0:y1, x0:x1] < POLICY["source_ink_threshold"]
    if scope_mask is not None:
        # These are analysis masks only. The immutable gray array, saved source
        # image and complete cold audit below retain all original pixels.
        source_mask = source_mask & scope_mask
        render_mask = render_mask & scope_mask
    mm = 25.4 / float(dpi)

    def pixel_from_cad(point):
        return np.array([float(point[0]) / mm + x0, y1 - float(point[1]) / mm])

    # Fresh load after the prior audit: its in-memory repairs are never used as
    # the reviewed original entity geometry.
    doc = ezdxf.readfile(dxf_path)
    candidate_by_id = {obj["id"]: obj for obj in objects}
    issues, formal, seen_ids, object_bounds = [], [], set(), {}
    checks_by_id = defaultdict(list)
    for row in cold_audit.get("source_checks", []):
        checks_by_id[row["id"]].append(row)
    line_samples, arc_samples = [], []
    units_ok = (
        int(doc.header.get("$INSUNITS", 0)) == 4
        and int(doc.header.get("$MEASUREMENT", 0)) == 1
    )
    if not units_ok:
        issues.append(
            _issue(
                "DXF_UNITS_DO_NOT_MATCH_EXPLICIT_PAPER_MM",
                severity="error",
                status="REJECT_STRUCTURE",
            )
        )
    review_layer = doc.layers.get("REVIEW") if "REVIEW" in doc.layers else None
    navigation_layer_ok = (
        review_layer is not None
        and not review_layer.is_on()
        and review_layer.is_locked()
        and not bool(review_layer.dxf.get("plot", 1))
    )
    if not navigation_layer_ok:
        issues.append(
            _issue(
                "NAVIGATION_REVIEW_LAYER_MUST_BE_OFF_LOCKED_NONPLOTTING",
                severity="error",
                status="REJECT_STRUCTURE",
            )
        )
    font_checks, font_assets = _font_dependencies(doc, dxf_path)
    if any(not row["pass"] for row in font_checks):
        issues.append(
            _issue(
                "TEXT_STYLE_OR_PORTABLE_FONT_DEPENDENCY_MISSING",
                severity="error",
                status="REJECT_STRUCTURE",
                support={"checks": font_checks},
            )
        )
    for entity in doc.modelspace():
        if entity.dxf.layer == "REVIEW":
            continue
        try:
            identity = cad_io.identity(entity)
            oid, kind = identity["id"], identity["kind"]
        except (KeyError, ValueError, AttributeError, ezdxf.DXFError) as exc:
            issues.append(
                _issue(
                    "SAVED_FORMAL_ENTITY_WITHOUT_CANDIDATE_IDENTITY",
                    severity="error",
                    status="REJECT_STRUCTURE",
                    member_refs=[
                        {"handle": entity.dxf.handle, "type": entity.dxftype()}
                    ],
                    support={"error": str(exc)},
                )
            )
            continue
        if oid in seen_ids or oid not in candidate_by_id:
            issues.append(
                _issue(
                    "SAVED_ENTITY_DUPLICATE_OR_UNKNOWN_CANDIDATE_ID",
                    severity="error",
                    status="REJECT_STRUCTURE",
                    object_ids=[oid],
                )
            )
            continue
        seen_ids.add(oid)
        obj = candidate_by_id[oid]
        bbox = _box(obj)
        object_bounds[oid] = bbox
        members = _expanded(entity)
        checks = _candidate_geometry_checks(entity, obj, members, pixel_from_cad, mm)
        checks["identity_kind_matches_candidate"] = kind == obj["kind"]
        layer = doc.layers.get(entity.dxf.layer)
        checks["formal_layer_visible_and_plotted"] = (
            layer.is_on() and not layer.is_frozen() and bool(layer.dxf.get("plot", 1))
        )
        if entity.dxftype() == "INSERT":
            references = [
                e
                for e in doc.modelspace().query("INSERT")
                if e.dxf.name == entity.dxf.name
            ]
            checks["instance_definition_independent"] = len(references) == 1
            checks["no_unexpected_attribute_members"] = len(entity.attribs) == 0
            for member in doc.blocks.get(entity.dxf.name):
                checks.setdefault("all_block_members_inherited_or_declared_layer", True)
                checks["all_block_members_inherited_or_declared_layer"] &= (
                    member.dxf.layer in ("0", entity.dxf.layer)
                )
        matches = all(
            value is True for key, value in checks.items() if key != "contract_error"
        )
        geometry_checks = checks_by_id.get(oid, [])
        expected_geometry = any(
            member.dxftype() not in ("TEXT", "MTEXT") for member in members
        )
        geometry_source_ok = (
            bool(geometry_checks)
            and all(row.get("pass") is True for row in geometry_checks)
            if expected_geometry
            else None
        )
        if not matches:
            issues.append(
                _issue(
                    "SAVED_NATIVE_ENTITY_DIFFERS_FROM_CURRENT_CANDIDATE_OR_STRUCTURE",
                    bbox,
                    object_ids=[oid],
                    severity="error",
                    status="REJECT_STRUCTURE",
                    support=checks,
                )
            )
        if expected_geometry and not geometry_source_ok:
            issues.append(
                _issue(
                    "SAVED_OBJECT_FAILS_OR_LACKS_SOURCE_GEOMETRY_CHECK",
                    bbox,
                    object_ids=[oid],
                    severity="error",
                    status="REJECT_SOURCE",
                    support={"checks": geometry_checks},
                )
            )
        texts_actual = [
            m.dxf.text if m.dxftype() == "TEXT" else m.plain_text()
            for m in members
            if m.dxftype() in ("TEXT", "MTEXT")
        ]
        if texts_actual:
            issues.append(
                _issue(
                    "LOCAL_OCR_AND_LITERAL_DXF_AGREE_BUT_CONTENT_AND_LAYOUT_REQUIRE_REVIEW",
                    bbox,
                    status="REVIEW_TEXT_CONTENT_AND_LAYOUT",
                    object_ids=[oid],
                    support={
                        "saved_strings": texts_actual,
                        "local_OCR_evidence_in_candidate": bool(
                            obj.get("source_evidence")
                        ),
                        "deployed_visual_semantic_verifier": None,
                        "ordinary_text_is_not_outline": True,
                    },
                )
            )
        source_ev = obj.get("source_evidence", {})
        if source_ev.get("boundary_clipped"):
            issues.append(
                _issue(
                    "OBSERVED_OBJECT_EXTENT_CLIPPED_BY_SELECTION",
                    bbox,
                    status="REVIEW_OBJECT_EXTENT",
                    object_ids=[oid],
                )
            )
        if kind in (
            "DOOR",
            "ROOM_LABEL",
            "WALL_SEGMENT",
            "CONNECTION_PATH",
            "CIRCULAR_MARKER",
        ):
            issues.append(
                _issue(
                    "COMPOSITE_GEOMETRY_CHECKED_ENGINEERING_CLASS_OR_EDIT_SCOPE_NOT_HUMAN_VERIFIED",
                    bbox,
                    status="REVIEW_OBJECT_CLASS_AND_EDIT_SCOPE",
                    object_ids=[oid],
                    support={
                        "geometric_structure_matches_current_candidate": matches,
                        "whole_engineering_object_identity_proven": False,
                    },
                )
            )
        if matches and geometry_source_ok:
            for member in members:
                for points, family in _path_points(member, pixel_from_cad, mm):
                    (arc_samples if family == "ARC" else line_samples).append(points)
        parameter_count = 0
        for member in members:
            if member.dxftype() == "LINE":
                parameter_count += 4
            elif member.dxftype() == "ARC":
                parameter_count += 5
            elif member.dxftype() == "CIRCLE":
                parameter_count += 3
            elif member.dxftype() == "LWPOLYLINE":
                parameter_count += 2 * len(member) + (
                    len(member) if member.closed else max(0, len(member) - 1)
                )
        formal.append(
            {
                "id": oid,
                "kind": kind,
                "bbox_xyxy_px": bbox,
                "actual_native_type": entity.dxftype(),
                "handle": entity.dxf.handle,
                "layer": entity.dxf.layer,
                "member_types": dict(Counter(m.dxftype() for m in members)),
                "member_refs": [
                    {"index": i, "type": m.dxftype()} for i, m in enumerate(members)
                ],
                "saved_candidate_structure_checks": checks,
                "candidate_structure_matches": matches,
                "source_geometry_gate_pass": geometry_source_ok,
                "native_geometric_parameters_excluding_text_layout": parameter_count,
                "saved_literal_text": texts_actual,
                "engineering_identity_proven": False,
                "complete_source_object_recovery_proven": False,
                "runtime_review": "LOCAL_DETERMINISTIC_RULES_NOT_CHAT_VISION",
            }
        )
    for oid in sorted(set(candidate_by_id) - seen_ids):
        issues.append(
            _issue(
                "CURRENT_CANDIDATE_MISSING_FROM_SAVED_DXF",
                _box(candidate_by_id[oid]),
                object_ids=[oid],
                severity="error",
                status="REJECT_STRUCTURE",
            )
        )
    for duplicate in cold_audit.get("exact_duplicate_segments", []):
        issues.append(
            _issue(
                "EXACT_DUPLICATE_SAVED_NATIVE_GEOMETRY",
                object_ids=duplicate.get("objects", []),
                severity="error",
                status="REJECT_STRUCTURE",
                support=duplicate,
            )
        )
    for reason, values in (
        ("DXF_AUDITOR_ERRORS", cold_audit.get("ezdxf_errors", [])),
        (
            "DXF_AUDITOR_IN_MEMORY_FIXES_ARE_NOT_ORIGINAL_VALIDITY",
            cold_audit.get("ezdxf_in_memory_fixes", []),
        ),
    ):
        if values:
            issues.append(
                _issue(
                    reason,
                    severity="error",
                    status="REJECT_STRUCTURE",
                    support={"records": values},
                )
            )
    text_boxes = [
        row["bbox_xyxy_px"]
        for row in (texts or {}).get("regions", [])
        if row.get("bbox_xyxy_px")
    ]
    groups, source_issues, counts, missing_mask = _source_groups(
        source_mask,
        render_mask,
        line_samples,
        arc_samples,
        object_bounds,
        text_boxes,
        roi,
        binding["source_identity"]["working_array_sha256"],
        scope_mask=scope_mask,
    )
    issues += source_issues
    represented_groups = {
        obj.get("source_evidence", {}).get("text_group_id", obj["id"])
        for obj in objects
        if obj["kind"] in ("TEXT", "MTEXT", "ROOM_LABEL")
    }
    for group in (texts or {}).get("groups", []):
        if group.get("id") not in represented_groups:
            group_box = _box(group)
            if review_scope is not None and not any(
                _intersects(group_box, context)
                for context in review_scope["context_rois"]
            ):
                continue
            issues.append(
                _issue(
                    "CURRENT_TEXT_GROUP_NOT_EXPORTED_COMPLETE",
                    group_box,
                    status="PENDING_TEXT_GROUP",
                    support={
                        "text_group_id": group.get("id"),
                        "candidate_text": group.get("text"),
                        "complete_by_OCR_rules": bool(group.get("complete")),
                        "unresolved_reasons": group.get("unresolved_reasons", []),
                    },
                    discriminator=group.get("id"),
                )
            )
    for index, uncertainty in enumerate(uncertainties or []):
        reason = (
            uncertainty.get("reason", "UNRESOLVED_CURRENT_CANDIDATE")
            if isinstance(uncertainty, dict)
            else "UNRESOLVED_CURRENT_CANDIDATE"
        )
        issues.append(
            _issue(
                "CANDIDATE_UNCERTAINTY:" + str(reason),
                _box(uncertainty),
                support={
                    "uncertainty_record_index": index,
                    "details_file": "quality_uncertainties.json",
                },
                discriminator=index,
            )
        )
    unique_issues = {issue["id"]: issue for issue in issues}
    issues = sorted(
        unique_issues.values(),
        key=lambda row: (
            row["severity"] != "error",
            row["bbox_xyxy_px"] is None,
            (row["bbox_xyxy_px"] or [0, 0])[1],
            (row["bbox_xyxy_px"] or [0, 0])[0],
            row["id"],
        ),
    )
    for issue in issues:
        issue["review_revision"] = POLICY["review_version"]
        issue["binding"] = {
            "binding_sha256": binding["binding_sha256"],
            "source_file_sha256": binding["source_identity"]["source_file_sha256"],
            "working_array_sha256": binding["source_identity"]["working_array_sha256"],
            "candidate_sha256": binding["candidate_sha256"],
            "saved_DXF_sha256": binding["saved_DXF_sha256"],
            "review_code_sha256": binding["review_code_sha256"],
        }
        issue["on_binding_change"] = "STALE_REVIEW_PENDING"
    source_path = out / "quality_source_roi.png"
    Image.fromarray(gray[y0:y1, x0:x1]).save(source_path)
    Image.fromarray((~missing_mask).astype(np.uint8) * 255).save(
        out / "quality_unexplained_source.png"
    )
    save_json(
        out / "quality_source_groups.json",
        {
            "schema": "original-source-ink-group-ledger-v4",
            "coordinate_system": "job_working_pixels_top_left",
            "roi_xyxy_px": list(roi),
            "source_identity": binding["source_identity"],
            **({"review_scope": review_scope} if review_scope is not None else {}),
            "groups": groups,
            "counts": counts,
        },
    )
    save_json(
        out / "quality_issues.json",
        {
            "schema": "native-quality-issues-v4",
            "coordinate_system": "job_working_pixels_top_left",
            "roi_xyxy_px": list(roi),
            "binding_sha256": binding["binding_sha256"],
            **({"review_scope": review_scope} if review_scope is not None else {}),
            "issues": issues,
        },
    )
    save_json(out / "quality_uncertainties.json", uncertainties or [])
    save_json(out / "quality_text_evidence.json", texts)
    save_json(out / "quality_saved_cold_audit.json", cold_audit)
    source_topology, render_topology = (
        _topology(source_mask, scope_mask),
        _topology(render_mask, scope_mask),
    )
    safe_structure = not any(
        row["severity"] == "error" and row["status"] == "REJECT_STRUCTURE"
        for row in issues
    )
    source_gate = bool(cold_audit.get("source_gate_pass")) and not any(
        row["status"] == "REJECT_SOURCE" for row in issues
    )
    summary = {
        "safe_artifact_structure": safe_structure,
        "source_geometry_gate_pass": source_gate,
        "requires_manual_review": bool(issues),
        "issue_count": len(issues),
        "localized_issue_count": sum(not r["unlocalized"] for r in issues),
        "unlocalized_issue_count": sum(r["unlocalized"] for r in issues),
        "source_group_count": len(groups),
        "source_groups_with_pending_work": len(
            {gid for issue in source_issues for gid in issue["source_group_ids"]}
        ),
        "formal_object_count": len(formal),
        "formal_object_kind_counts": dict(Counter(row["kind"] for row in formal)),
        "native_modelspace_type_counts": dict(
            Counter(row["actual_native_type"] for row in formal)
        ),
        "not_all_ink_explained": bool(
            counts["source_not_black_in_render_pixels"] or source_issues
        ),
        "all_original_source_pixels_in_group_ledger": counts[
            "all_source_pixels_in_group_ledger"
        ]
        and counts["all_source_group_pixel_runs_accounted"],
        "important_engineering_object_inventory_known": False,
        "full_source_reconstruction_proven": False,
        "product_GO": False,
        "chat_assistant_visual_approval_used": False,
        "previous_OCR_DXF_or_review_list_required": False,
        "current_text_discovery_cache_supplied": bool(
            texts.get("cache", {}).get("enabled")
        ),
        "current_OCR_status": texts.get("status", "UNKNOWN"),
        "network_service_calls": 0,
        "network_service_wait_seconds": 0.0,
        "review_status": "REJECT_SAVED_ARTIFACT"
        if not safe_structure or not source_gate
        else "RULES_REVIEW_COMPLETE_WITH_PENDING_ITEMS"
        if issues
        else "RULES_REVIEW_COMPLETE_NO_REPORTED_ISSUES",
    }
    circular_rows = [
        row for row in formal if row["kind"] in ("CIRCLE", "CIRCULAR_MARKER")
    ]
    if circular_rows:
        summary["circular_marker_composition"] = _circular_composition_summary(
            circular_rows, candidate_by_id
        )
    if review_scope is not None:
        summary["source_to_output_scope"] = review_scope["mode"]
        summary["full_parent_region_review_performed"] = False
        summary["all_in_scope_original_source_pixels_in_group_ledger"] = summary.pop(
            "all_original_source_pixels_in_group_ledger"
        )
    assets = [
        source_path,
        out / "quality_unexplained_source.png",
        out / "quality_source_groups.json",
        out / "quality_issues.json",
        out / "quality_uncertainties.json",
        out / "quality_text_evidence.json",
        out / "quality_saved_cold_audit.json",
        rendered_path,
    ] + font_assets
    report = {
        "schema": SCHEMA,
        "coordinate_system": "job_working_pixels_top_left",
        "roi_xyxy_px": list(roi),
        "source_identity": binding["source_identity"],
        **({"review_scope": review_scope} if review_scope is not None else {}),
        "binding": binding,
        "policy": POLICY,
        "summary": summary,
        "issues": issues,
        "output_to_source": formal,
        "runtime_review_capability": {
            "local_OCR_engine": texts.get("engine"),
            "local_OCR_status": texts.get("status"),
            "discovery_coverage_complete": texts.get(
                "discovery_coverage_complete", False
            ),
            "review_engine": "LOCAL_DETERMINISTIC_SOURCE_AND_SAVED_DXF_RULES",
            "independent_raster_consumer": "official_ezdxf_to_MuPDF",
            "deployed_visual_semantic_verifier": None,
            "chat_assistant_decisions_used": False,
            "online_service_calls": 0,
            "online_service_wait_seconds": 0.0,
            "ordinary_text_correctness": "PENDING_CONTENT_AND_LAYOUT_REVIEW",
            "review_binding_source": "CURRENT_SOURCE_BYTES_WORKING_PIXELS_CANDIDATES_DXF_CODE_AND_EVIDENCE",
        },
        "text_style_and_font_dependencies": font_checks,
        "source_to_output": {
            "counts": counts,
            "ledger_file": "quality_source_groups.json",
            **({"review_scope": review_scope} if review_scope is not None else {}),
            "source_grouping_is_engineering_classification": False,
            "grid_role": "NAVIGATION_ONLY_NOT_REPAIR_INVENTORY",
            "all_small_components_retained": True,
            "unknown_ink_classified_as_dust": False,
        },
        "pixel_topology": {
            "source": source_topology,
            "independent_render": render_topology,
            "same_4_and_8_connected_pixel_counts": source_topology == render_topology,
            "scope": (
                "context union raster only; excluded pixels are not paper; "
                "boundary fragments have unverified full extent"
                if review_scope is not None
                else "selected ROI raster only; boundary-clipped groups are marked"
            ),
            "continuous_ink_paper_topology": "NOT_PROVEN_BY_RASTER_COUNTS_OR_ZERO_HATCH",
        },
        "independent_render": {
            "renderer": render["renderer"],
            "saved_DXF_sha256": original_sha,
            "raster_sha256": file_sha256(rendered_path),
            "CAD_GUI": "NOT_RUN_BY_RULE_REVIEW",
        },
        "reviewer_code": reviewer_code_identity(),
        "evidence_assets": [
            {"relative_path": os.path.relpath(path, out), "sha256": file_sha256(path)}
            for path in assets
        ],
        "resources": {
            "wall_seconds": time.perf_counter() - started,
            "source_field_scope": (
                "source-to-output context union only; cold audit covers all saved entities"
                if review_scope is not None
                else "ROI only; no full-page floating distance field"
            ),
        },
        "old_failure_records_modified": False,
        "actual_saved_DXF_unchanged": file_sha256(dxf_path) == original_sha,
    }
    # Source, candidate and version must still match at the end of the review.
    if build_review_binding(dxf_path, objects, import_manifest, gray=gray) != binding:
        raise ValueError("REVIEW_INPUT_OR_VERSION_CHANGED_DURING_CHECK")
    save_json(report_path, report)
    validation = verify_saved_review(report_path, dxf_path, objects, import_manifest)
    if not validation["valid"]:
        raise ValueError(
            "NEW_REVIEW_BINDING_FAILED:"
            + json.dumps(validation["mismatches"], ensure_ascii=False)
        )
    return report
