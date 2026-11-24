"""Fit one literal TEXT to proved source components without changing its ink source.

This optional layout is used only after the ordinary portable-font layout has
failed a source-neighbor relation. It is not OCR, a font search, or per-character
positioning: every character receives the same four-parameter affine transform.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import cv2
from ezdxf.fonts import fonts
import numpy as np

from .source_row_font_registry import FONT_SPEC

POLICY = {
    "version": "proved-source-components-one-TEXT-affine-v1",
    "maximum_component_center_error_heights": 0.20,
    "maximum_full_height_edge_error_heights": 0.12,
    "maximum_whole_ink_edge_error_heights": 0.20,
    "source_quantization_search_px": 1.0,
    "search_step_px": 0.25,
    "minimum_retained_source_white_gap_px": 0.5,
    "maximum_required_source_white_gap_px": 1.0,
    "font_unit_curve_flattening": 1.0 / 4096,
    "literal_companion_equivalence_unit_capheight": 1e-9,
    "source_contact_is_permitted": True,
    "characters_individually_transformed": False,
    "source_pixels_changed": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_row_font_path():
    """Resolve only the one packaged font and exact accompanying permission file."""
    root = Path(__file__).resolve().parents[2] / "resources/fonts"
    font, license_path = root / FONT_SPEC["font"], root / FONT_SPEC["source_license"]
    for path, size, digest in (
        (font, FONT_SPEC["bytes"], FONT_SPEC["sha256"]),
        (license_path, FONT_SPEC["license_bytes"], FONT_SPEC["license_sha256"]),
        (root / FONT_SPEC["librecad_font"], FONT_SPEC["librecad_bytes"],
         FONT_SPEC["librecad_sha256"]),
    ):
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != size
                or _file_sha(path) != digest):
            raise ValueError("SOURCE_ROW_PACKAGED_FONT_OR_LICENSE_IDENTITY_MISMATCH")
    return font.resolve()


def _companion_path(font_path):
    path = Path(font_path).with_name(FONT_SPEC["librecad_font"])
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_size != FONT_SPEC["librecad_bytes"]
            or _file_sha(path) != FONT_SPEC["librecad_sha256"]):
        raise ValueError("SOURCE_ROW_ACTUAL_LFF_COMPANION_IDENTITY_CHANGED")
    return path.resolve()


@lru_cache(maxsize=8)
def _lff_glyphs(filename, digest):
    """Read the actual fixed companion; unsupported LFF constructs fail closed."""
    if digest != FONT_SPEC["librecad_sha256"]:
        raise ValueError("SOURCE_ROW_LFF_NOT_IN_FIXED_REGISTRY")
    glyphs, headers, current = {}, {}, None
    for raw in Path(filename).read_text(encoding="utf-8").splitlines():
        row = raw.strip()
        if not row:
            continue
        if row.startswith("#"):
            key, sep, value = row[1:].partition(":")
            if sep:
                headers[key.strip()] = value.strip()
            continue
        if row.startswith("[") and row.endswith("]"):
            current = int(row[1:-1], 16)
            if current in glyphs or not 0 <= current <= 0x10FFFF:
                raise ValueError("SOURCE_ROW_LFF_GLYPH_IDENTITY_INVALID")
            glyphs[current] = []
            continue
        if current is None:
            raise ValueError("SOURCE_ROW_LFF_GLYPH_HEADER_MISSING")
        points = np.asarray([list(map(float, item.split(",")))
                             for item in row.split(";")], dtype=float)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 4
                or not np.isfinite(points).all()
                or not np.allclose(points[0], points[-1], atol=1e-12, rtol=0)):
            raise ValueError("SOURCE_ROW_LFF_CLOSED_OUTLINE_INVALID")
        glyphs[current].append(points / 9.0)
    if headers.get("Format") != "LibreCAD Font 1" or not glyphs:
        raise ValueError("SOURCE_ROW_LFF_FORMAT_OR_GLYPHS_INVALID")
    spacing = float(headers["LetterSpacing"]) / 9.0
    word_spacing = float(headers["WordSpacing"]) / 9.0
    if not (math.isfinite(spacing) and math.isfinite(word_spacing)
            and spacing > 0 and word_spacing > 0):
        raise ValueError("SOURCE_ROW_LFF_SPACING_INVALID")
    return glyphs, spacing, word_spacing


@lru_cache(maxsize=128)
def _literal_companion_equivalence(font_filename, font_digest, lff_filename, lff_digest, text):
    """Prove this literal's outlines and advance, without assuming full-font equality.

    LibreCAD uses each LFF glyph's max-x plus a global spacing. Merely deriving
    LFF from the same TTF does not preserve TrueType advance. All selected glyphs
    and accumulated positions must agree at numerical serialization tolerance.
    """
    _, native_contours = _font_geometry(font_filename, font_digest, text)
    glyphs, spacing, word_spacing = _lff_glyphs(lff_filename, lff_digest)
    font = fonts.sideload_ttf(Path(font_filename), 1.0)
    contours, advances, position = [], [], 0.0
    for index, character in enumerate(text):
        if character == " ":
            position += word_spacing
        else:
            paths = glyphs.get(ord(character))
            if not paths:
                raise ValueError("SOURCE_ROW_LFF_LITERAL_GLYPH_MISSING")
            contours.extend(points + [position, 0.0] for points in paths)
            position += max(float(points[:, 0].max()) for points in paths) + spacing
        advances.append(abs(position - float(font.text_width(text[:index + 1]))))
    if len(contours) != len(native_contours) or any(
        a.shape != b.shape for a, b in zip(contours, native_contours)
    ):
        raise ValueError("SOURCE_ROW_LFF_LITERAL_OUTLINE_TOPOLOGY_CHANGED")
    outline_error = max(float(np.max(np.abs(a - b)))
                        for a, b in zip(contours, native_contours))
    advance_error = max(advances)
    tolerance = POLICY["literal_companion_equivalence_unit_capheight"]
    return {
        "pass": outline_error <= tolerance and advance_error <= tolerance,
        "scope": "this complete literal only; no whole-font equivalence claimed",
        "font_sha256": font_digest, "librecad_sha256": lff_digest,
        "actual_LFF_file_read": True, "all_literal_outlines_and_advances_checked": True,
        "maximum_outline_difference_unit_capheight": outline_error,
        "maximum_accumulated_advance_difference_unit_capheight": advance_error,
        "serialization_tolerance_unit_capheight": tolerance,
        "unverified_glyphs_are_not_exempted": True,
    }


def _check_companion(font_path, digest, text):
    companion = _companion_path(font_path)
    return _literal_companion_equivalence(
        str(Path(font_path).resolve()), digest, str(companion),
        FONT_SPEC["librecad_sha256"], text,
    )


@lru_cache(maxsize=128)
def _font_geometry(filename, digest, text):
    if digest != FONT_SPEC["sha256"] or Path(filename).name != FONT_SPEC["font"]:
        raise ValueError("SOURCE_ROW_FONT_NOT_IN_FIXED_REGISTRY")
    font = fonts.sideload_ttf(Path(filename), 1.0)
    glyphs = font.text_glyph_paths(text, 1.0)
    if len(glyphs) != len([c for c in text if not c.isspace()]):
        raise ValueError("SOURCE_ROW_FONT_LITERAL_GLYPH_CARDINALITY_MISMATCH")
    bounds, contours = [], []
    for glyph in glyphs:
        bbox = glyph.bbox()
        if not bbox.has_data:
            raise ValueError("SOURCE_ROW_FONT_GLYPH_HAS_NO_INK")
        bounds.append([bbox.extmin.x, bbox.extmin.y, bbox.extmax.x, bbox.extmax.y])
        for subpath in glyph.sub_paths():
            points = np.asarray([list(p) for p in subpath.flattening(
                POLICY["font_unit_curve_flattening"])], dtype=float)
            if len(points) < 3:
                raise ValueError("SOURCE_ROW_FONT_CONTOUR_INVALID")
            if not np.array_equal(points[0], points[-1]):
                points = np.vstack((points, points[0]))
            contours.append(points)
    return np.asarray(bounds, float), tuple(contours)


def _mask(runs, box):
    mask = np.zeros((box[3] - box[1], box[2] - box[0]), np.uint8)
    for row in runs:
        if (len(row) != 3 or any(isinstance(x, bool) or int(x) != x for x in row)
                or row[2] <= row[1]):
            raise ValueError("SOURCE_ROW_ORIGINAL_RUN_INVALID")
        y, a, b = map(int, row)
        if box[1] <= y < box[3]:
            a, b = max(a, box[0]), min(b, box[2])
            if b > a:
                mask[y - box[1], a - box[0]:b - box[0]] = 1
    return mask


def _rectangles(mask, origin):
    rows = []
    for y in np.flatnonzero(np.any(mask, axis=1)):
        edges = np.diff(np.pad(mask[y].astype(np.int8), (1, 1)))
        rows.extend([[float(x0 + origin[0]), float(y + origin[1]),
                      float(x1 + origin[0]), float(y + origin[1] + 1)]
                     for x0, x1 in zip(np.flatnonzero(edges == 1),
                                       np.flatnonzero(edges == -1))])
    return rows


def _source_data(geometry, partition, gray):
    text = geometry["text"]
    if not isinstance(text, str) or not text or any(c in text for c in "\n\r\t"):
        raise ValueError("SOURCE_ROW_REQUIRES_ONE_LITERAL_LINE")
    components = partition["components"]
    if not 3 <= len(components) <= 64 or len(components) != len(text.replace(" ", "")):
        raise ValueError("SOURCE_ROW_COMPONENT_LITERAL_CARDINALITY_MISMATCH")
    box = list(map(int, partition["context_bbox_xyxy_px"]))
    if (len(box) != 4 or min(box[0], box[1]) < 0 or not 0 < box[2] - box[0] <= 1100
            or not 0 < box[3] - box[1] <= 500):
        raise ValueError("SOURCE_ROW_CONTEXT_NOT_BOUNDED")
    angle = math.radians(float(geometry.get("rotation_deg_image", 0.0)))
    if not math.isfinite(angle):
        raise ValueError("SOURCE_ROW_DIRECTION_INVALID")
    u, v = np.array([math.cos(angle), math.sin(angle)]), np.array([-math.sin(angle), math.cos(angle)])
    source_boxes, full_indices = [], []
    glyph = _mask(partition["source_support_runs_y_x0_x1"], box)
    union = np.zeros_like(glyph)
    for i, component in enumerate(components):
        current = _mask(component["source_runs_y_x0_x1"], box)
        if not np.any(current):
            raise ValueError("SOURCE_ROW_COMPONENT_HAS_NO_ORIGINAL_INK")
        union |= current
        yy, xx = np.nonzero(current)
        corners = np.column_stack([xx + box[0], yy + box[1]])
        corners = np.vstack([corners + delta for delta in ([0, 0], [1, 0], [0, 1], [1, 1])])
        projected = np.column_stack((corners @ u, corners @ v))
        source_boxes.append([*projected.min(axis=0), *projected.max(axis=0)])
        if component["source_role"] == "FULL_HEIGHT_GLYPH":
            full_indices.append(i)
    if not np.array_equal(glyph, union) or len(full_indices) < 3:
        raise ValueError("SOURCE_ROW_COMPLETE_COMPONENT_RESPONSIBILITY_MISSING")
    source_boxes = np.asarray(source_boxes)
    if np.any(np.diff((source_boxes[:, 0] + source_boxes[:, 2]) / 2) <= 0):
        raise ValueError("SOURCE_ROW_COMPONENT_ORDER_DISAGREES_WITH_DIRECTION")
    separation = partition.get("text_contact_separation", {})
    runs = list(partition.get("recognition_excluded_graphic_runs_y_x0_x1", []))
    runs += separation.get("recognition_excluded_source_runs", [])
    for path in separation.get("geometry_plan", {}).get("paths", []):
        runs += path.get("line_runs", [])
    graphic = _mask(runs, box)
    if gray is not None:
        crop = gray[box[1]:box[3], box[0]:box[2]]
        if crop.shape != glyph.shape or np.any((glyph | graphic) & (crop >= 192)):
            raise ValueError("SOURCE_ROW_SUPPORT_IS_NOT_ORIGINAL_INK")
    near = cv2.dilate(glyph, np.ones((3, 3), np.uint8))
    near_two = cv2.dilate(glyph, np.ones((5, 5), np.uint8))
    source_height = float(np.median(source_boxes[full_indices, 3] - source_boxes[full_indices, 1]))
    contact = graphic & near
    locality = int(math.ceil(source_height * 0.20))
    allowed = np.zeros_like(graphic)
    graphic_count, graphic_labels = cv2.connectedComponents(graphic, connectivity=8)
    contact_kernel = np.ones((2 * locality + 1, 2 * locality + 1), np.uint8)
    for label in range(1, graphic_count):
        current = graphic_labels == label
        own_contact = (contact & current).astype(np.uint8)
        if np.any(own_contact):
            allowed |= cv2.dilate(own_contact, contact_kernel) & current
    # A contact at one end of a long graphic does not waive white gaps elsewhere.
    # Only the same source graphic's bounded original contact may share ink;
    # a nearby disconnected line retains its own proved white gap.
    protected_graphic = graphic & (allowed == 0)
    count, labels = cv2.connectedComponents(protected_graphic, connectivity=8)
    neighbors = []
    if np.any(contact):
        neighbors.append({"source_contact": True, "rectangles": [], "required_gap_px": 0.0,
                          "contact_locality_px": locality,
                          "original_contact_sha256": _digest(_rectangles(contact, box[:2]))})
    for label in range(1, count):
        current = labels == label
        required = 0.5 if np.any(current & near_two) else 1.0
        rectangles = _rectangles(current, box[:2])
        neighbors.append({"source_contact": False, "rectangles": rectangles,
                          "source_runs_sha256": _digest(rectangles),
                          "required_gap_px": required})
    return source_boxes, full_indices, u, v, neighbors


def _linear_fit(a, b):
    am, bm = math.fsum(map(float, a)) / len(a), math.fsum(map(float, b)) / len(b)
    denominator = math.fsum((float(x) - am) ** 2 for x in a)
    if denominator <= 1e-12:
        raise ValueError("SOURCE_ROW_LAYOUT_ANCHORS_DEGENERATE")
    scale = math.fsum((float(x) - am) * (float(y) - bm) for x, y in zip(a, b)) / denominator
    return scale, bm - scale * am


def _fit_metrics(parameters, font_boxes, source_boxes, full_indices):
    sx, sy, ox, oy = parameters
    actual = font_boxes * [sx, -sy, sx, -sy] + [ox, oy, ox, oy]
    actual[:, [1, 3]] = actual[:, [3, 1]]
    height = float(np.median(source_boxes[full_indices, 3] - source_boxes[full_indices, 1]))
    centers = (actual[:, :2] + actual[:, 2:] - source_boxes[:, :2] - source_boxes[:, 2:]) / 2
    vertical = actual[full_indices][:, [1, 3]] - source_boxes[full_indices][:, [1, 3]]
    actual_box = [*actual[:, :2].min(axis=0), *actual[:, 2:].max(axis=0)]
    source_box = [*source_boxes[:, :2].min(axis=0), *source_boxes[:, 2:].max(axis=0)]
    box_error = np.asarray(actual_box) - source_box
    checks = {
        "positive_whole_TEXT_scales": bool(sx > 0 and sy > 0 and 0.5 <= sx / sy <= 2),
        "component_positions_match_source": bool(np.max(np.abs(centers)) <= height * 0.20 + 1e-9),
        "full_glyph_height_and_baseline_match_source": bool(np.max(np.abs(vertical)) <= max(2.0, height * 0.12) + 1e-9),
        "whole_ink_bounds_match_source": bool(np.max(np.abs(box_error)) <= height * 0.20 + 1e-9),
    }
    score = float(np.mean(centers ** 2) + np.mean(vertical ** 2))
    return {"pass": all(checks.values()), "checks": checks, "score": score,
            "observed_glyph_height_px": height, "component_center_errors_px": centers.tolist(),
            "full_height_edge_errors_px": vertical.tolist(),
            "actual_whole_ink_box_in_source_axes": actual_box,
            "source_whole_ink_box_in_source_axes": source_box,
            "one_transform_for_all_characters": True}


def _inside_many(points, starts, ends):
    x, y = points[:, 0, None], points[:, 1, None]
    eligible = (starts[None, :, 1] > y) != (ends[None, :, 1] > y)
    den = ends[:, 1] - starts[:, 1]
    den = np.where(den == 0, 1.0, den)
    hits = x < starts[None, :, 0] + ((ends[:, 0] - starts[:, 0])[None, :]
                                  * (y - starts[None, :, 1]) / den[None, :])
    return np.count_nonzero(eligible & hits, axis=1) % 2 == 1


def _neighbor_check(parameters, contours, u, v, neighbors):
    sx, sy, ox, oy = parameters
    paths = [(points * [sx, -sy] + [ox, oy]) @ np.column_stack((u, v)).T for points in contours]
    starts, ends = np.vstack([p[:-1] for p in paths]), np.vstack([p[1:] for p in paths])
    delta = ends - starts
    checked = []
    for neighbor in neighbors:
        if neighbor["source_contact"]:
            checked.append({"pass": True, "relation": "BOUNDED_ORIGINAL_SOURCE_CONTACT_ALLOWED",
                            "contact_locality_px": neighbor["contact_locality_px"],
                            "original_contact_sha256": neighbor["original_contact_sha256"],
                            "whole_graphic_component_exempted": False})
            continue
        margin = neighbor["required_gap_px"]
        rectangles = np.asarray(neighbor["rectangles"], float)
        lo, hi = rectangles[:, :2] - margin, rectangles[:, 2:] + margin
        # Closed font boundary against the original pixel rectangles, conservatively
        # expanded by a half/one source pixel. Counters use even-odd fill below.
        a = starts[:, None, :]
        d = delta[:, None, :]
        moving = np.abs(d) > 1e-15
        safe_d = np.where(moving, d, 1.0)
        first, last = (lo[None, :, :] - a) / safe_d, (hi[None, :, :] - a) / safe_d
        low = np.where(moving, np.minimum(first, last), -np.inf).max(axis=2)
        high = np.where(moving, np.maximum(first, last), np.inf).min(axis=2)
        parallel = np.all(moving | ((a >= lo) & (a <= hi)), axis=2)
        intersects = bool(np.any(parallel & (np.maximum(low, 0) <= np.minimum(high, 1))))
        contained = bool(np.any(_inside_many((lo + hi) / 2, starts, ends)))
        checked.append({"pass": not intersects and not contained,
                        "source_runs_sha256": neighbor["source_runs_sha256"],
                        "required_original_ink_clearance_px": margin,
                        "checks_actual_font_boundary_and_filled_interior": True})
        if not checked[-1]["pass"]:
            return {"pass": False, "checks": checked}
    return {"pass": True, "checks": checked,
            "all_original_neighbors_preserved": True,
            "source_pixels_modified": False}


def _layout(parameters, geometry, roi, dpi, u, v):
    sx, sy, ox, oy = parameters
    mm = 25.4 / float(dpi)
    baseline = np.array([ox, oy]) @ np.column_stack((u, v)).T
    return {"insert": [round(float((baseline[0] - roi[0]) * mm), 12),
                       round(float((roi[3] - baseline[1]) * mm), 12), 0.0],
            "height": round(float(sy * mm), 12), "width": round(float(sx / sy), 12),
            "rotation": -float(geometry.get("rotation_deg_image", 0.0)),
            "basis": POLICY["version"], "font_sha256": FONT_SPEC["sha256"],
            "source_ink_bbox_xyxy_px": [geometry["x"], geometry["y"] - geometry["height_px"],
                                       geometry["x"] + geometry["width_px"], geometry["y"]],
            "font_is_recognition_evidence": False, "scan_pixel_equality_required": False}


def _actual_parameters(attributes, geometry, roi, dpi, u, v):
    mm = 25.4 / float(dpi)
    insert = np.asarray(attributes["insert"], float)
    if (insert.shape != (3,) or not np.isfinite(insert).all()
            or not math.isfinite(mm) or mm <= 0 or attributes["text"] != geometry["text"]
            or abs(float(attributes["rotation"]) + float(geometry.get("rotation_deg_image", 0))) > 1e-9
            or any(attributes.get(k, 0) != 0 for k in ("halign", "valign", "oblique", "text_generation_flag"))
            or attributes.get("extrusion", [0, 0, 1]) != [0, 0, 1]):
        raise ValueError("SOURCE_ROW_ACTUAL_TEXT_TRANSFORM_OR_CONTENT_CHANGED")
    image = [roi[0] + insert[0] / mm, roi[3] - insert[1] / mm]
    sy = float(attributes["height"]) / mm
    return [sy * float(attributes["width"]), sy, float(np.dot(image, u)), float(np.dot(image, v))]


def verify_source_glyph_layout(geometry, partition, roi, dpi, font_path, actual_attributes, *, gray=None):
    """Recheck source placement and white gaps using the actual saved TEXT attrs."""
    source_boxes, full, u, v, neighbors = _source_data(geometry, partition, gray)
    digest = _file_sha(font_path)
    boxes, contours = _font_geometry(str(Path(font_path).resolve()), digest, geometry["text"])
    companion = _check_companion(font_path, digest, geometry["text"])
    parameters = _actual_parameters(actual_attributes, geometry, roi, dpi, u, v)
    if not np.isfinite(parameters).all():
        raise ValueError("SOURCE_ROW_ACTUAL_TEXT_NONFINITE")
    fit = _fit_metrics(parameters, boxes, source_boxes, full)
    clearance = _neighbor_check(parameters, contours, u, v, neighbors) if fit["pass"] else {"pass": False, "reason": "SOURCE_COMPONENT_FIT_FAILED"}
    return {"pass": fit["pass"] and clearance["pass"] and companion["pass"], "source_fit": fit,
            "source_neighbor_clearance": clearance, "actual_attributes_used": True,
            "actual_saved_LFF_literal_equivalence": companion,
            "font_sha256": digest, "source_partition_sha256": _digest(partition)}


def fit_source_glyph_layout(geometry, partition, roi, dpi, font_path, *, gray=None):
    """Deterministically select one complete source-constrained affine TEXT layout."""
    result = {"schema": POLICY["version"], "policy": dict(POLICY), "pass": False,
              "reason": "NO_SINGLE_TEXT_LAYOUT_PRESERVES_SOURCE_COMPONENTS_AND_GAPS",
              "font": dict(FONT_SPEC), "source_partition_sha256": _digest(partition)}
    try:
        source_boxes, full, u, v, neighbors = _source_data(geometry, partition, gray)
        digest = _file_sha(font_path)
        boxes, contours = _font_geometry(str(Path(font_path).resolve()), digest, geometry["text"])
        companion = _check_companion(font_path, digest, geometry["text"])
        result["librecad_literal_equivalence"] = companion
        if not companion["pass"]:
            result["reason"] = "SOURCE_ROW_LFF_LITERAL_OUTLINE_OR_ADVANCE_DIFFERS"
            return result
        sx, ox = _linear_fit((boxes[:, 0] + boxes[:, 2]) / 2,
                             (source_boxes[:, 0] + source_boxes[:, 2]) / 2)
        neg_sy, oy = _linear_fit(np.r_[boxes[full, 1], boxes[full, 3]],
                                 np.r_[source_boxes[full, 3], source_boxes[full, 1]])
        sy = -neg_sy
        unit_width = float(boxes[:, 2].max() - boxes[:, 0].min())
        candidates = []
        # One-pixel source sampling uncertainty; no character-specific displacement.
        for width_delta in (-1.0, 0.0, 1.0):
            for height_delta in (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0):
                for dx in (-0.5, 0.0, 0.5):
                    for dy in (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0):
                        params = tuple(round(float(q), 12) for q in
                                       (sx + width_delta / unit_width, sy + height_delta, ox + dx, oy + dy))
                        fit = _fit_metrics(params, boxes, source_boxes, full)
                        if fit["pass"]:
                            candidates.append((fit["score"], params))
        for _, parameters in sorted(candidates):
            selected = _layout(parameters, geometry, roi, dpi, u, v)
            actual = {"text": geometry["text"], **selected}
            # Check the final rounded CAD attributes, not unrounded fit parameters.
            rounded = _actual_parameters(actual, geometry, roi, dpi, u, v)
            checked_fit = _fit_metrics(rounded, boxes, source_boxes, full)
            clearance = _neighbor_check(rounded, contours, u, v, neighbors)
            if checked_fit["pass"] and clearance["pass"]:
                result.update({"pass": True, "reason": None, "selected_layout": selected,
                               "source_fit": checked_fit,
                               "source_neighbor_clearance": clearance})
                break
        result["finite_source_bounded_candidates"] = len(candidates)
    except (ValueError, TypeError, KeyError, OSError, IndexError) as exc:
        result["reason"] = type(exc).__name__ + ": " + str(exc)
    return result


def selected_layout_for_export(geometry, partition, roi, dpi, font_path):
    result = fit_source_glyph_layout(geometry, partition, roi, dpi, font_path)
    if not result["pass"]:
        raise ValueError(result["reason"])
    return result["selected_layout"]
