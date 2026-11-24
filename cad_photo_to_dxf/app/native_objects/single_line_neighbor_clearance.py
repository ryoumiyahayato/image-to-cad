"""Keep a proved source white gap between complete TEXT and an independent ring.

This is a conservative layout veto, never recognition or a font optimizer.
The caller must replay the complete source partition. Saved checks supply the
actual TEXT attributes, not attributes reconstructed by the layout writer.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from ezdxf.fonts import fonts

from .circular_markers import _mask_from_runs, _observe_seed
from .contracts import plain

POLICY = {
    "version": "source-separated-round-native-text-clearance-v1",
    "source_white_gap": "no_shared_or_8_adjacent_original_glyph_and_ring_pixels",
    "font_curve_flattening_tolerance_px": 0.02,
    "original_ring_ink_must_remain_separate": True,
    "native_circle_centerline_must_remain_separate": True,
    "source_contact_is_permitted": True,
    "changes_text_font_or_geometry": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=plain).encode()).hexdigest()


def native_font_path():
    """Use the same two existing font/permission resources as the DXF writer."""
    root = Path(__file__).resolve().parents[2] / "resources/fonts"
    for font, licence in (
        (root / "DejaVuSans.ttf", root / "DejaVuSans.LICENSE.txt"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/doc/fonts-dejavu-core/copyright")),
    ):
        if font.is_file() and licence.is_file():
            return font.resolve()
    raise FileNotFoundError("NATIVE_EXPORT_FONT_OR_LICENSE_MISSING")


def _source_rounds(gray, roi, partition):
    seeds = partition.get("text_contact_separation", {}).get("independent_round_observations", [])
    if not seeds:
        return []
    rows = []
    for seed in seeds:
        center = np.asarray(seed["center"], float)
        radius = float(seed["inner_boundary_radius_px"])
        if (center.shape != (2,) or not np.isfinite(center).all()
                or not math.isfinite(radius) or not 8 <= radius <= 32
                or not (roi[0] <= center[0] < roi[2] and roi[1] <= center[1] < roi[3])):
            raise ValueError("TEXT_ROUND_CLEARANCE_SOURCE_SEED_INVALID")
        # Reuse the existing bounded measurement, not whole-ROI discovery.
        # Only the original partition's independently observed rounds enter.
        rows.append(_observe_seed(gray, roi, seed, ()))
    result = []
    for row in rows:
        if not row.get("geometry_accepted"):
            continue
        evidence = row["source_evidence"]
        a = partition["bbox_xyxy_px"]
        b = evidence["crop_bbox_xyxy_px"]
        box = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        glyph = _mask_from_runs(partition["source_support_runs_y_x0_x1"], box)
        ring = _mask_from_runs(evidence["ring_support_runs_y_x0_x1"], box)
        crop = gray[box[1]:box[3], box[0]:box[2]]
        if not glyph.any() or np.any(glyph & (crop >= 192)):
            raise ValueError("TEXT_ROUND_CLEARANCE_GLYPH_SOURCE_NOT_ORIGINAL_INK")
        touches = bool(np.any(glyph & cv2.dilate(np.uint8(ring), np.ones((3, 3), np.uint8))))
        result.append({
            "circle_id": row["id"], "circle_geometry": row["geometry"],
            "circle_source_crop_sha256": evidence["crop_sha256"],
            "ring_source_runs_sha256": _digest(evidence["ring_support_runs_y_x0_x1"]),
            "original_glyph_and_ring_touch": touches,
            "original_white_gap_proved": not touches,
            "ring_runs": evidence["ring_support_runs_y_x0_x1"],
        })
    return result


def _font_contours(attributes, font_path, roi, dpi):
    mm = 25.4 / float(dpi)
    text = attributes["text"]
    height, width = float(attributes["height"]), float(attributes["width"])
    angle = math.radians(float(attributes["rotation"]))
    insert = np.asarray(attributes["insert"], float)
    if (not isinstance(text, str) or not text or insert.shape != (3,)
            or not np.isfinite(insert).all()
            or not all(math.isfinite(v) for v in (mm, height, width, angle))
            or min(mm, height, width) <= 0):
        raise ValueError("TEXT_ROUND_CLEARANCE_ACTUAL_TEXT_ATTRIBUTES_INVALID")
    for key, expected in (("halign", 0), ("valign", 0), ("oblique", 0),
                          ("text_generation_flag", 0)):
        if attributes.get(key, expected) != expected:
            raise ValueError("TEXT_ROUND_CLEARANCE_UNSUPPORTED_ACTUAL_TEXT_TRANSFORM")
    if attributes.get("extrusion", [0, 0, 1]) != [0, 0, 1]:
        raise ValueError("TEXT_ROUND_CLEARANCE_UNSUPPORTED_ACTUAL_TEXT_EXTRUSION")
    font = fonts.sideload_ttf(Path(font_path).resolve(), 1.0)
    flat = POLICY["font_curve_flattening_tolerance_px"] * mm / max(height, height * width)
    c, s = math.cos(angle), math.sin(angle)
    transform = np.array([[c * height * width, -s * height],
                          [s * height * width, c * height]])
    contours = []
    for subpath in font.text_path(text).sub_paths():
        unit = np.asarray([list(point) for point in subpath.flattening(flat)], float)
        points = unit @ transform.T + insert[:2]
        points[:, 0] = points[:, 0] / mm + roi[0]
        points[:, 1] = roi[3] - points[:, 1] / mm
        if len(points) < 3 or not np.isfinite(points).all():
            raise ValueError("TEXT_ROUND_CLEARANCE_FONT_OUTLINE_INVALID")
        if not np.array_equal(points[0], points[-1]):
            points = np.vstack([points, points[0]])
        contours.append(points)
    if not contours:
        raise ValueError("TEXT_ROUND_CLEARANCE_FONT_HAS_NO_INK")
    return contours


def _inside(point, contours):
    """Even-odd contour fill includes counters without filling their white holes."""
    px, py = point
    crossings = 0
    for points in contours:
        a, b = points[:-1], points[1:]
        eligible = (a[:, 1] > py) != (b[:, 1] > py)
        a, b = a[eligible], b[eligible]
        crossings += int(np.count_nonzero(px < a[:, 0] + (b[:, 0] - a[:, 0])
                                         * (py - a[:, 1]) / (b[:, 1] - a[:, 1])))
    return bool(crossings % 2)


def _relations(contours, circle, ring_runs):
    a = np.vstack([p[:-1] for p in contours])
    b = np.vstack([p[1:] for p in contours])
    d = b - a
    lengths = np.sum(d * d, axis=1)
    valid = lengths > 1e-24
    a, b, d, lengths = a[valid], b[valid], d[valid], lengths[valid]
    center, radius = np.asarray(circle["center"], float), float(circle["radius_px"])
    t = np.clip(-np.sum((a - center) * d, axis=1) / lengths, 0, 1)
    minimum = np.linalg.norm(a + t[:, None] * d - center, axis=1)
    maximum = np.maximum(np.linalg.norm(a - center, axis=1), np.linalg.norm(b - center, axis=1))
    separation = np.maximum(np.maximum(minimum - radius, radius - maximum), 0)
    tolerance = POLICY["font_curve_flattening_tolerance_px"]
    circle_inside = _inside(center + [radius, 0], contours)
    native_contact = bool(circle_inside or float(separation.min()) <= tolerance)
    ring_contact = False
    for y, left, right in ring_runs:
        lo, hi = np.array([left, y], float) - tolerance, np.array([right, y + 1], float) + tolerance
        possible = np.all(np.maximum(a, b) >= lo, axis=1) & np.all(np.minimum(a, b) <= hi, axis=1)
        aa, dd = a[possible], d[possible]
        if len(aa):
            low, high = np.zeros(len(aa)), np.ones(len(aa))
            feasible = np.ones(len(aa), bool)
            for axis in (0, 1):
                moving = np.abs(dd[:, axis]) > 1e-15
                feasible &= moving | ((aa[:, axis] >= lo[axis]) & (aa[:, axis] <= hi[axis]))
                first = np.full(len(aa), -np.inf)
                last = np.full(len(aa), np.inf)
                first[moving] = (lo[axis] - aa[moving, axis]) / dd[moving, axis]
                last[moving] = (hi[axis] - aa[moving, axis]) / dd[moving, axis]
                low = np.maximum(low, np.minimum(first, last))
                high = np.minimum(high, np.maximum(first, last))
            ring_contact = bool(np.any(feasible & (low <= high)))
        if ring_contact or _inside([(left + right) / 2, y + 0.5], contours):
            ring_contact = True
            break
    return {
        "actual_font_touches_native_circle": native_contact,
        "actual_font_touches_original_ring_ink": ring_contact,
        "native_circle_outline_clearance_px": 0.0 if circle_inside else float(separation.min()),
        "pass": not native_contact and not ring_contact,
    }


def check_text_round_white_gaps(gray, roi, partition, attributes, font_path, dpi):
    """Inspect actual font ink against source-proved, independent round ink."""
    rows = _source_rounds(gray, roi, partition)
    protected = [row for row in rows if row["original_white_gap_proved"]]
    contours = _font_contours(attributes, font_path, roi, dpi) if protected else None
    checked = []
    for row in rows:
        runs = row.pop("ring_runs")
        if row["original_white_gap_proved"]:
            row.update(_relations(contours, row["circle_geometry"], runs))
        else:
            row.update({"pass": True, "relation": "ORIGINAL_SOURCE_CONTACT_OR_OWN_GLYPH_ALLOWED"})
        checked.append(row)
    passed = all(row["pass"] for row in checked)
    return {
        "schema": POLICY["version"], "policy": dict(POLICY), "pass": passed,
        "reason": None if passed else "NATIVE_TEXT_CLOSES_PROVED_SOURCE_ROUND_WHITE_GAP",
        "source_partition_sha256": _digest(partition),
        "actual_text_attributes_sha256": _digest({key: attributes[key] for key in ("text", "insert", "height", "width", "rotation")}),
        "font_sha256": hashlib.sha256(Path(font_path).read_bytes()).hexdigest(),
        "relations": checked, "source_pixels_modified": False,
        "font_or_text_geometry_modified": False,
    }


def proposed_text_round_white_gaps(gray, roi, partition, geometry, dpi):
    from .single_line_text_audit import source_ink_text_layout

    font = native_font_path()
    layout = source_ink_text_layout(geometry, roi, dpi, font)
    attributes = {"text": geometry["text"], **{key: layout[key] for key in ("insert", "height", "width", "rotation")}}
    return check_text_round_white_gaps(gray, roi, partition, attributes, font, dpi)
