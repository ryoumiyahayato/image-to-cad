"""Cold-read actual finite DXF geometry and bound, explicitly supplied fonts.

No candidate producer or producer approval is imported.  These records are
inputs to independent source acceptance, never an ownership approval by
themselves.  Coordinates used for new decisions retain exact binary64 values.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from fractions import Fraction
from io import BytesIO
from pathlib import Path

import ezdxf
import fontTools
from ezdxf.fonts.ttfonts import TTFontRenderer
from fontTools.ttLib import TTFont, TTLibError

SCHEMA = "independent-finite-component-saved-reader-v1"
APPID = "I2CAD_NATIVE_V2"
POLICY = {
    "text_model": "HASH_BOUND_RAW_BEZIER_CONTROL_HULL_LEFT_BASELINE_V1",
    "source_transform": "EXACT_RATIONAL_OF_SAVED_BINARY64_AND_EXISTING_MM_SCALE",
    "maximum_block_depth": 16,
    "maximum_members": 100000,
    "maximum_text_characters": 4096,
    "system_font_fallback": False,
    "source_ownership_claimed_by_reader": False,
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _q(value):
    if isinstance(value, Fraction):
        return value
    if not math.isfinite(value):
        raise ValueError("NONFINITE_SAVED_VALUE")
    return Fraction(value)


def _pack(value):
    value = _q(value)
    return [value.numerator, value.denominator]


def _unpack(value):
    return Fraction(int(value[0]), int(value[1]))


def exact_points(row):
    """Return exact source coordinates, not rounded display coordinates."""
    return [tuple(_unpack(v) for v in p) for p in row["points_exact"]]


def _outward(value, upper):
    rounded = float(value)
    if not math.isfinite(rounded):
        raise ValueError("UNREPRESENTABLE_SOURCE_COORDINATE")
    if (_q(rounded) < value) if upper else (_q(rounded) > value):
        rounded = math.nextafter(rounded, math.inf if upper else -math.inf)
    return rounded


def _source_point(point, roi, scale):
    return (_q(point[0]) / scale + roi[0], roi[3] - _q(point[1]) / scale)


def _set_bound(row, bounds, scope):
    row.update(
        bbox_xyxy=[_outward(q, i >= 2) for i, q in enumerate(bounds)],
        bbox_xyxy_exact=[_pack(q) for q in bounds],
        bbox_scope=scope,
        coverage_valid=True,
    )


def _points_bound(points):
    x, y = zip(*points)
    return (min(x), min(y), max(x), max(y))


def _identity(entity):
    if not entity.has_xdata(APPID):
        return None
    chunks = [tag.value for tag in entity.get_xdata(APPID) if tag.code == 1000]
    try:
        identity = json.loads("".join(chunks))
    except (ValueError, TypeError):
        raise ValueError("INVALID_SAVED_NATIVE_IDENTITY") from None
    if not isinstance(identity, dict) or not isinstance(identity.get("id"), str) or not identity["id"]:
        raise ValueError("INVALID_SAVED_NATIVE_IDENTITY")
    # Other fields, including any producer PASS, are deliberately not returned.
    return identity["id"]


def _planar(entity):
    return tuple(entity.dxf.get("extrusion", (0., 0., 1.))) == (0., 0., 1.)


def _text_enclosure(entity, directory, bindings, roi, scale, font_cache):
    """Enclose decoded outlines with exact affine control-point hulls.

    A new byte-backed decoder per font digest avoids sideload_ttf's path-keyed
    shared cache.  Font discovery and substitution are never invoked.
    """
    def fail(reason):
        return {"status": "UNKNOWN_TEXT_EXTENT", "reason": reason}
    if entity.dxftype() != "TEXT":
        return fail("TEXT_SUBSET_EXCLUDES_ATTRIBUTES_AND_MULTILINE")
    if not _planar(entity) or entity.dxf.insert.z != 0. or entity.dxf.get("thickness", 0.) != 0.:
        return fail("NONPLANAR_OR_THICK_TEXT")
    if (entity.dxf.halign != 0 or entity.dxf.valign != 0 or
            entity.dxf.get("rotation", 0.) != 0. or entity.dxf.get("oblique", 0.) != 0. or
            entity.dxf.get("text_generation_flag", 0) != 0):
        return fail("TEXT_LAYOUT_OUTSIDE_FROZEN_SUBSET")
    height, width = _q(entity.dxf.height), _q(entity.dxf.get("width", 1.))
    if height <= 0 or width <= 0:
        return fail("NONPOSITIVE_TEXT_HEIGHT_OR_WIDTH")
    text = entity.dxf.text
    if len(text) > POLICY["maximum_text_characters"]:
        return fail("TEXT_RESOURCE_BOUNDARY")
    if "\\" in text or "%%" in text or any(not ch.isprintable() for ch in text):
        return fail("NON_LITERAL_OR_CONTROL_TEXT")
    try:
        style = entity.doc.styles.get(entity.dxf.style)
    except (KeyError, ezdxf.DXFError):
        return fail("MISSING_SAVED_TEXT_STYLE")
    if style.dxf.get("bigfont", ""):
        return fail("BIGFONT_OUTSIDE_FROZEN_SUBSET")
    if (style.dxf.get("oblique", 0.) != 0. or style.dxf.get("generation_flags", 0) != 0 or
            style.dxf.get("width", 1.) != 1.):
        return fail("STYLE_LAYOUT_OUTSIDE_FROZEN_SUBSET")
    name = style.dxf.get("font", "")
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return fail("FONT_NAME_REQUIRES_EXPLICIT_SIMPLE_BINDING")
    binding = bindings.get(name)
    if binding is None:
        return fail("FONT_BINDING_MISSING")
    if isinstance(binding, str):
        path, expected = directory / name, binding
    elif isinstance(binding, dict):
        path = Path(binding.get("path", directory / name))
        expected = binding.get("sha256")
    else:
        return fail("INVALID_FONT_BINDING")
    if not isinstance(expected, str) or len(expected) != 64:
        return fail("FONT_SHA256_PIN_REQUIRED")
    try:
        data = path.read_bytes()
    except OSError:
        return fail("BOUND_FONT_UNAVAILABLE")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        return fail("FONT_SHA256_MISMATCH")
    try:
        if digest not in font_cache:
            font = TTFont(BytesIO(data), fontNumber=0, lazy=False)
            if "fvar" in font or "COLR" in font or "SVG " in font:
                font.close()
                return fail("VARIABLE_OR_COLOR_FONT_OUTSIDE_FROZEN_SUBSET")
            renderer = TTFontRenderer(font, kerning=False)
            font_cache[digest] = (font, renderer)
        _, renderer = font_cache[digest]
        if any(ord(ch) not in renderer.cmap for ch in text):
            return fail("FONT_CHARACTER_MAP_INCOMPLETE")
        fm = renderer.font_measurements
        cap, baseline = _q(fm.cap_height), _q(fm.baseline)
        if cap <= 0:
            return fail("INVALID_FONT_CAP_HEIGHT")
        xscale, yscale = height * width / cap, height / cap
        insx, insy = _q(entity.dxf.insert.x), _q(entity.dxf.insert.y)
        points, advance, vertex_count = [], Fraction(0), 0
        for char in text:
            controls = renderer.get_glyph_path(char).control_vertices()
            for point in controls:
                mm = (insx + (advance + _q(point.x)) * xscale,
                      insy + (_q(point.y) - baseline) * yscale)
                points.append(_source_point(mm, roi, scale))
            vertex_count += len(controls)
            advance += _q(renderer.get_glyph_width(char))
    except (ValueError, TypeError, KeyError, ArithmeticError, OSError, RuntimeError, TTLibError) as exc:
        return {**fail("FONT_OUTLINE_DECODE_UNRESOLVED"), "error_type": type(exc).__name__}
    proof = {
        "status": "CERTIFIED_CONSERVATIVE_OUTLINE_BOUND",
        "font_name": name, "font_sha256": digest,
        "decoder": {"ezdxf": ezdxf.__version__, "fonttools": fontTools.__version__,
                    "engine": "TTFontRenderer", "kerning": False, "font_fallback": False},
        "model": POLICY["text_model"],
        "layout": "SAVED_LEFT_BASELINE_ROTATION_ZERO_OBLIQUE_ZERO",
        "raw_cap_height_exact": _pack(cap), "raw_baseline_exact": _pack(baseline),
        "raw_advance_exact": _pack(advance), "outline_control_vertex_count": vertex_count,
        "literal_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "empty_outline": not points,
    }
    if points:
        proof["bounds"] = _points_bound(points)
    return proof


def _member_geometry(entity, identity, parent, member_path, roi, scale, directory, bindings, font_cache):
    kind = entity.dxftype()
    row = {"object_id": identity, "parent_object_id": parent, "member_index": list(member_path),
           "kind": kind, "handle": entity.dxf.get("handle"), "closed": False,
           "actual_saved_layer": entity.dxf.get("layer", "0"),
           "actual_saved_geometry": True, "geometry_supported": False,
           "points": [], "points_exact": [], "bulges": [],
           "bbox_scope": "UNAVAILABLE", "coverage_valid": False}
    points = []
    if kind == "LINE":
        points = [_source_point(p, roi, scale) for p in (entity.dxf.start, entity.dxf.end)]
        row["bulges"] = [0., 0.]
        if not _planar(entity) or entity.dxf.start.z != 0. or entity.dxf.end.z != 0.:
            row["unsupported_reason"] = "NONPLANAR_NATIVE_LINE"
        elif entity.dxf.get("thickness", 0.) != 0.:
            row["unsupported_reason"] = "LINE_THICKNESS_REQUIRES_AREA_AUDIT"
    elif kind == "LWPOLYLINE":
        vertices = list(entity.get_points("xyseb"))
        points = [_source_point(v, roi, scale) for v in vertices]
        row.update(bulges=[-float(v[4]) for v in vertices], closed=bool(entity.closed),
                   widths=[[float(v[2]), float(v[3])] for v in vertices],
                   constant_width=float(entity.dxf.get("const_width", 0.)))
        if not _planar(entity) or entity.dxf.elevation != 0.:
            row["unsupported_reason"] = "NONPLANAR_NATIVE_POLYLINE"
        elif any(row["bulges"]):
            row["unsupported_reason"] = "CURVED_SEGMENTS_REQUIRE_EXACT_CURVE_AUDIT"
        elif row["constant_width"] or any(any(w) for w in row["widths"]):
            row["unsupported_reason"] = "FINITE_WIDTH_POLYLINE_REQUIRES_AREA_AUDIT"
        elif row["closed"]:
            row["unsupported_reason"] = "CLOSED_PATH_OUTSIDE_FINITE_OPEN_MODEL"
        elif entity.dxf.get("thickness", 0.) != 0.:
            row["unsupported_reason"] = "POLYLINE_THICKNESS_REQUIRES_AREA_AUDIT"
    elif kind == "TEXT":
        row["unsupported_reason"] = "NON_LINEAR_NATIVE_MEMBER"
        proof = _text_enclosure(entity, directory, bindings, roi, scale, font_cache)
        bounds = proof.pop("bounds", None)
        row["text_bound_proof"] = proof
        if bounds:
            _set_bound(row, bounds, "CONSERVATIVE_HASH_BOUND_TEXT_OUTLINE")
        elif proof.get("empty_outline"):
            row.update(coverage_valid=True, empty_ink_bound=True, bbox_scope="CERTIFIED_EMPTY_TEXT_OUTLINE")
        else:
            row["extent_unknown_reason"] = proof["reason"]
    elif (kind in ("CIRCLE", "ARC") and _planar(entity) and entity.dxf.center.z == 0. and
          entity.dxf.get("thickness", 0.) == 0. and entity.dxf.radius > 0.):
        cx, cy = _q(entity.dxf.center.x), _q(entity.dxf.center.y)
        radius = _q(entity.dxf.radius)
        a, b = _source_point((cx - radius, cy + radius), roi, scale), _source_point((cx + radius, cy - radius), roi, scale)
        _set_bound(row, (*a, *b), "CONSERVATIVE_FULL_CIRCLE_AREA_BOUND")
        row["unsupported_reason"] = "CURVE_REQUIRES_EXACT_CURVE_AUDIT"
    else:
        row["unsupported_reason"] = "UNSUPPORTED_NATIVE_MEMBER"
    if points:
        row.update(points=[[float(v) for v in p] for p in points],
                   points_exact=[[_pack(v) for v in p] for p in points])
        if not row.get("unsupported_reason"):
            if len(points) < 2 or any(a == b for a, b in zip(points, points[1:])):
                row["unsupported_reason"] = "DEGENERATE_NATIVE_SEGMENT"
            else:
                row["geometry_supported"] = True
                _set_bound(row, _points_bound(points), "FINITE_CENTERLINE_ONLY")
        elif row["unsupported_reason"] == "CLOSED_PATH_OUTSIDE_FINITE_OPEN_MODEL":
            # Closing a straight zero-width polygon adds a finite segment
            # inside this same vertex hull.  Its context bound is certifiable
            # even though closed objects are outside the responsibility model.
            _set_bound(row, _points_bound(points), "CONSERVATIVE_CLOSED_STRAIGHT_CENTERLINE_BOUND")
    elif kind in ("LINE", "LWPOLYLINE"):
        row["unsupported_reason"] = "EMPTY_NATIVE_GEOMETRY"
    return row


def context_for_scope(reader, bbox_xyxy, *, exclude_object_ids=()):
    """Classify conservative local relevance without declaring ink conflicts."""
    scope = tuple(_q(v) for v in bbox_xyxy)
    if len(scope) != 4 or scope[0] > scope[2] or scope[1] > scope[3]:
        raise ValueError("INVALID_LOCAL_SCOPE")
    exclude = set(exclude_object_ids)
    rows = []
    for row in reader["geometries"]:
        if row["object_id"] in exclude or row["parent_object_id"] in exclude:
            continue
        if row.get("empty_ink_bound"):
            relation = "PROVED_EMPTY"
        elif row.get("coverage_valid") and row.get("bbox_xyxy_exact"):
            box = tuple(_unpack(v) for v in row["bbox_xyxy_exact"])
            disjoint = box[2] < scope[0] or box[0] > scope[2] or box[3] < scope[1] or box[1] > scope[3]
            relation = "PROVED_DISJOINT" if disjoint else "POSSIBLY_RELATED"
        else:
            relation = "UNKNOWN_EXTENT_RELEVANCE"
        rows.append({"object_id": row["object_id"], "kind": row["kind"], "relation": relation,
                     "bbox_scope": row["bbox_scope"], "actual_conflict_asserted": False})
    return {"scope_bbox_xyxy_exact": [_pack(v) for v in scope], "members": rows,
            "relation_counts": dict(Counter(r["relation"] for r in rows)),
            "actual_conflict_count": 0,
            "claim": "CONSERVATIVE_RELEVANCE_ONLY_NOT_PIXEL_OR_CONTACT_ACCEPTANCE"}


def saved_source_geometries(path, roi, dpi, *, font_bindings=None, expected_dxf_sha256=None,
                            source_path=None, expected_source_sha256=None):
    """Cold-read persisted finite geometry with an external source frame.

    ``font_bindings`` maps a saved font name either to its adjacent file's
    SHA-256, or to ``{"path": explicit_path, "sha256": expected_digest}``.
    It is a byte identity pin, never a producer glyph or source approval.
    """
    path = Path(path)
    if len(roi) != 4:
        raise ValueError("INVALID_SOURCE_FRAME")
    roi_q = tuple(_q(v) for v in roi)
    if (any(v.denominator != 1 for v in roi_q) or roi_q[0] >= roi_q[2] or
            roi_q[1] >= roi_q[3] or _q(dpi) <= 0):
        raise ValueError("INVALID_SOURCE_FRAME")
    scale = _q(25.4 / float(dpi))
    if scale <= 0:
        raise ValueError("INVALID_SOURCE_FRAME")
    before = sha256(path)
    if expected_dxf_sha256 is not None and before != expected_dxf_sha256:
        raise ValueError("ACTUAL_DXF_SHA256_MISMATCH")
    actual_source = sha256(source_path) if source_path is not None else None
    if expected_source_sha256 is not None and actual_source != expected_source_sha256:
        raise ValueError("ACTUAL_SOURCE_SHA256_MISMATCH")
    doc = ezdxf.readfile(path)
    if sha256(path) != before:
        raise ValueError("DXF_CHANGED_DURING_COLD_READ")
    errors, geometries, counts, seen = [], [], Counter(), set()
    if doc.units != 4:
        errors.append({"reason": "ACTUAL_DXF_UNITS_NOT_PAPER_MM"})
    font_cache, exhausted = {}, False

    def unknown(identity, parent, reason, detail=None):
        geometries.append({"object_id": identity + "/unresolved", "parent_object_id": parent,
                           "kind": "UNRESOLVED", "points": [], "points_exact": [], "bulges": [],
                           "closed": False, "geometry_supported": False, "actual_saved_geometry": True,
                           "coverage_valid": False, "bbox_scope": "UNAVAILABLE",
                           "unsupported_reason": reason, "detail": detail})

    def visit(entity, parent, member_path=(), block_stack=()):
        nonlocal exhausted
        identity = parent if not member_path else parent + "/member:" + ".".join(map(str, member_path))
        if exhausted:
            return
        if len(geometries) >= POLICY["maximum_members"]:
            exhausted = True
            unknown(identity, parent, "MEMBER_RESOURCE_BOUNDARY")
            return
        if entity.dxftype() != "INSERT":
            try:
                geometries.append(_member_geometry(entity, identity, parent, member_path, roi_q,
                                  scale, path.parent, font_bindings or {}, font_cache))
            except (ValueError, TypeError, ArithmeticError) as exc:
                unknown(identity, parent, "INVALID_NATIVE_GEOMETRY", str(exc))
            return
        if len(block_stack) >= POLICY["maximum_block_depth"]:
            unknown(identity, parent, "BLOCK_DEPTH_RESOURCE_BOUNDARY")
            return
        if entity.mcount > 1:
            unknown(identity, parent, "MULTIPLE_INSERT_REQUIRES_COMPLETE_INSTANCE_AUDIT")
            return
        if entity.dxf.name in block_stack:
            unknown(identity, parent, "RECURSIVE_BLOCK_REFERENCE")
            return
        if entity.has_extension_dict:
            unknown(identity, parent, "BLOCK_EXTENSION_REQUIRES_CLIPPING_AUDIT")
        skipped = []
        try:
            virtual = list(entity.virtual_entities(skipped_entity_callback=lambda member, reason:
                           skipped.append({"native_type": member.dxftype(), "reason": reason})))
            for index, member in enumerate(virtual):
                visit(member, parent, (*member_path, index), (*block_stack, entity.dxf.name))
            for index, attribute in enumerate(entity.attribs, start=len(virtual)):
                visit(attribute, parent, (*member_path, index), (*block_stack, entity.dxf.name))
            if skipped:
                unknown(identity, parent, "UNTRANSFORMED_BLOCK_MEMBERS", skipped)
        except (ValueError, TypeError, ZeroDivisionError, ezdxf.DXFError) as exc:
            unknown(identity, parent, "BLOCK_TRANSFORM_UNRESOLVED", type(exc).__name__)

    for index, entity in enumerate(doc.modelspace()):
        if entity.dxf.layer == "REVIEW":
            counts["review"] += 1
            continue
        counts["formal"] += 1
        try:
            identity = _identity(entity)
        except ValueError as exc:
            errors.append({"handle": entity.dxf.handle, "reason": str(exc)})
            identity = None
        if identity is None:
            errors.append({"handle": entity.dxf.handle, "reason": "UNIDENTIFIED_FORMAL_ENTITY"})
            identity = "unidentified:" + str(index)
        elif identity in seen:
            errors.append({"object_id": identity, "reason": "DUPLICATE_FORMAL_ID"})
            identity += "/duplicate-instance:" + str(index)
        seen.add(identity)
        visit(entity, identity)
    for font, _ in font_cache.values():
        font.close()
    counts["members"] = len(geometries)
    counts["named_blocks"] = sum(not b.name.startswith(("*Model_Space", "*Paper_Space")) for b in doc.blocks)
    counts["formal_text_members"] = sum(r["kind"] == "TEXT" for r in geometries)
    counts["certified_text_members"] = sum(r.get("text_bound_proof", {}).get("status") ==
                                          "CERTIFIED_CONSERVATIVE_OUTLINE_BOUND" for r in geometries)
    counts["unresolved_members"] = sum(r["kind"] == "UNRESOLVED" for r in geometries)
    return {
        "schema": SCHEMA, "policy": dict(POLICY), "reader_sha256": sha256(__file__),
        "dxf_sha256": before, "source_sha256": actual_source,
        "externally_bound_source_bytes": expected_source_sha256 is not None and actual_source is not None,
        "roi_xyxy": list(roi), "dpi": dpi, "mm_per_source_pixel_exact": _pack(scale),
        "geometry_origin": "ACTUAL_SAVED_DXF_COLD_READ", "geometries": geometries,
        "identity_errors": errors, "counts": dict(counts), "enumeration_complete": not exhausted,
        "curves_replaced_by_chords": False, "producer_approval_consumed": False,
        "source_ownership_verdict": "NOT_ESTABLISHED_BY_SAVED_READER",
    }
