"""Compare an actual portable EXE with its source revision on a generated input.

Run this helper from a copy outside the source checkout. It executes the source
CLI first, then temporarily hides the application's original source directory
and executes a detached copy of the shipped bundle with a clean environment.
All recognition/adoption is the ordinary manager/worker pipeline. The known
fixture content is checked only after saving; it is never an OCR hint.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import sys
import time
import uuid


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_fixture(path: Path, font_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 560, 400), outline=0, width=3)
    draw.line((100, 280, 400, 280), fill=0, width=3)
    # Same permitted generated fixture as maintenance/native_cli_smoke.py;
    # an explicit shipped font makes generation independent of host fonts.
    font = ImageFont.truetype(str(font_path), 24)
    draw.text((120, 130), "ROOM 17", font=font, fill=0)
    image.save(path, dpi=(200, 200))


def create_circular_fixture(path: Path, font_path: Path) -> None:
    """A separate permitted image; these characters are never recognizer hints."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 32)
    for center, character in (((150, 150), "F"), ((400, 150), "K")):
        cx, cy = center
        draw.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), outline=0, width=3)
        bbox = draw.textbbox((0, 0), character, font=font)
        draw.text((cx - (bbox[0] + bbox[2]) / 2, cy - (bbox[1] + bbox[3]) / 2), character, font=font, fill=0)
        draw.line((cx + 26, cy, cx + 130, cy), fill=0, width=3)
    # Empty attached border: a partial CIRCLE, never a complete marker.
    draw.ellipse((374, 304, 426, 356), outline=0, width=3)
    draw.line((426, 330, 530, 330), fill=0, width=3)
    # Two truly white source columns (372/373) separate this independent
    # left-hand line from the empty circle. It must never be snapped to it.
    draw.line((290, 330, 371, 330), fill=0, width=3)
    # Ordinary round glyphs must not become CIRCLEs or marker INSERTs.
    draw.text((110, 310), "O 0", font=font, fill=0)
    image.save(path, dpi=(200, 200))


def create_curve_end_boundary_fixture(path: Path, font_path: Path) -> None:
    """Generated variable-width circular ink with separate contact/gap lines.

    The circular pen centre is specified only by this external test drawing.
    Ordinary production receives a PNG, without positions or character hints.
    The two established character markers remain independent controls.
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    create_circular_fixture(path, font_path)
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L")).copy()
    gray[280:380, 280:560] = 255
    yy, xx = np.indices(gray.shape)
    angle = np.arctan2(yy - 330, xx - 400)
    half_width = 2.5 + 1.2 * np.sin(3 * angle + 0.3)
    ring = np.abs(np.hypot(xx - 400, yy - 330) - 22) <= half_width
    gray[ring] = 0
    # An unconfirmed inner stroke is retained in source evidence. Its content
    # is deliberately not an acceptance answer or a required adopted TEXT.
    cv2.line(gray, (395, 322), (395, 338), 0, 2)
    cv2.line(gray, (395, 322), (405, 322), 0, 2)
    # Keep the same local contact direction, with a complete lead longer
    # than the ordinary pipeline's general path-candidate minimum.
    cv2.line(gray, (422, 330), (536, 300), 0, 2)
    image = Image.fromarray(gray)
    ImageDraw.Draw(image).line((290, 330, 373, 330), fill=0, width=3)
    image.save(path, dpi=(200, 200))


def create_circle_character_completion_fixture(path: Path, font_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new('L', (640, 480), 255)
    draw = ImageDraw.Draw(image)
    for center, letter, size in (
        ((150, 130), 'E', 30), ((430, 130), 'E', 31),
        ((150, 340), 'E', 29), ((430, 340), 'F', 32),
    ):
        cx, cy = center
        font = ImageFont.truetype(str(font_path), size)
        bbox = draw.textbbox((0, 0), letter, font=font)
        draw.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), outline=0, width=3)
        draw.text((cx - (bbox[0] + bbox[2]) / 2, cy - (bbox[1] + bbox[3]) / 2), letter, font=font, fill=0)
        draw.line((cx + 26, cy, cx + 130, cy), fill=0, width=3)
    # Three genuinely blank source columns (121..123) before the lower-left ring.
    draw.line((40, 340, 120, 340), fill=0, width=3)
    image.save(path, dpi=(200, 200))



def create_terminal_core_fixture(path: Path, font_path: Path) -> None:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    gray = np.full((480, 640), 255, np.uint8)
    curve = [(round(230 + 0.55 * (y - 188) + 0.0015 * (y - 188) ** 2), y)
             for y in range(90, 330)]
    cv2.polylines(gray, [np.asarray(curve[:215], np.int32)], False, 0, 2)
    cv2.polylines(gray, [np.asarray(curve[214:], np.int32)], False, 0, 5)
    cv2.circle(gray, (355, 330), 18, 0, 2)
    cv2.line(gray, (305, 329), (338, 329), 0, 5)
    cv2.putText(gray, "F", (349, 336), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1)
    cv2.circle(gray, (160, 350), 18, 0, 2)
    cv2.line(gray, (80, 350), (141, 350), 0, 2)
    cv2.line(gray, (183, 350), (260, 350), 0, 2)
    cv2.putText(gray, "F", (154, 356), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1)
    image = Image.fromarray(gray)
    draw = ImageDraw.Draw(image)
    source_font = ImageFont.truetype(str(font_path), 32, layout_engine=ImageFont.Layout.BASIC)
    control_font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    draw.text((110, 170), "STORAGE42", font=source_font, fill=0)
    draw.text((460, 64), "STORE", font=control_font, fill=0)
    draw.text((460, 120), "AX7", font=control_font, fill=0)
    image.save(path, dpi=(200, 200))



SINGLE_LINE_LABEL_FIXTURE = (
    ("AHU-27B, Z4", (80, 64)),
    ("PANEL-08A", (80, 176)),
    ("CIRCUIT-315, B2", (80, 288)),
)
SINGLE_LINE_NEIGHBOR_FIXTURE = (
    ((50, 112), (405, 112)),
    ((50, 202), (405, 202)),
    ((310, 275), (310, 338)),
    ((460, 308), (480, 308)),
)
SINGLE_LINE_TESSERACT_VIEWS = (
    {"scale": 2, "padding": 16, "psm": 7},
    {"scale": 2, "padding": 16, "psm": 13},
)
SINGLE_LINE_PP_OCR_VIEWS = (
    {"scale": 1, "padding": 4},
    {"scale": 1, "padding": 0},
)


def create_single_line_fixture(path: Path, font_path: Path) -> None:
    """Fixed generated source, with answers confined to this post-save harness.

    The middle label's bottom ink touches the independent horizontal line.
    Neither component overwrites the other. The last short stroke is a real
    independent source line, not a punctuation character to erase or absorb.
    The existing circular fixture remains a separate, unchanged protection case.
    """
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    for content, point in SINGLE_LINE_LABEL_FIXTURE:
        draw.text(point, content, font=font, fill=0)
    draw.text((460, 64), "STORE", font=font, fill=0)
    for start, end in SINGLE_LINE_NEIGHBOR_FIXTURE:
        draw.line((start, end), fill=0, width=3)
    image.save(path, dpi=(200, 200))


CONTACT_LABEL_FIXTURE = (("STORAGE42", (110, 170)),)
CONTACT_NEIGHBOR_FIXTURE = (
    ((100, 260), (230, 260)),
    ((480, 300), (500, 300)),
)


def _contact_curve_points():
    """Generated source geometry, used only by this external smoke harness."""
    return [(round(230 + 0.55 * (y - 188) + 0.0015 * (y - 188) ** 2), y)
            for y in range(90, 311)]


def create_contact_fixture(path: Path, font_path: Path) -> None:
    """One whole alphanumeric label with a curve crossing the middle glyphs.

    Both real curve endpoints, a separate underline, a short stroke, and a
    correct ordinary text control are present. No expected string or location
    is provided to the ordinary source/EXE command, which receives only PNG.
    The previous three fixture creators and their pixels remain unchanged.
    """
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 32, layout_engine=ImageFont.Layout.BASIC)
    for content, point in CONTACT_LABEL_FIXTURE:
        draw.text(point, content, font=font, fill=0)
    draw.line(_contact_curve_points(), fill=0, width=3)
    for start, end in CONTACT_NEIGHBOR_FIXTURE:
        draw.line((start, end), fill=0, width=3)
    control_font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    draw.text((460, 64), "STORE", font=control_font, fill=0)
    image.save(path, dpi=(200, 200))


SHORT_CODE_LABEL_FIXTURE = (("PX-17,29", (100, 195)),)
SHORT_CODE_CIRCLE_FIXTURE = ((153, 179), 19)
SHORT_CODE_NEIGHBOR_FIXTURE = (
    ((85, 236), (250, 236)),
    ((500, 330), (520, 330)),
)
SHORT_CODE_CONTACT_FIXTURE = ((172, 179), (297, 279))


def create_short_code_fixture(path: Path, font_path: Path, source_font_path: Path) -> None:
    """A separate complete code with source-separated ring and crossing lead.

    Literal text and fixed positions belong only to this public image generator
    and the post-save inspector. The ordinary CLI receives only this PNG; no
    text, glyph box, layout or code-specific hint is supplied to recognition.
    The four previous inputs remain unchanged.
    """
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    source_font = ImageFont.truetype(str(source_font_path), 36, layout_engine=ImageFont.Layout.BASIC)
    for content, point in SHORT_CODE_LABEL_FIXTURE:
        draw.text(point, content, font=source_font, fill=0)
    (cx, cy), radius = SHORT_CODE_CIRCLE_FIXTURE
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=0, width=3)
    for start, end in (*SHORT_CODE_NEIGHBOR_FIXTURE, SHORT_CODE_CONTACT_FIXTURE):
        draw.line((start, end), fill=0, width=3)
    control_font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    draw.text((460, 64), "STORE", font=control_font, fill=0)
    image.save(path, dpi=(200, 200))


def read_source_row_font_spec(app_root: Path) -> dict:
    """Read the one verified packaged registry, without importing app runtime.

    run() checks every bundled source against the build manifest first. This
    tiny pure-data module also works while the original checkout is hidden.
    No font identity is duplicated in the fixture or acceptance code.
    """
    registry = app_root / "app/native_objects/source_row_font_registry.py"
    spec = runpy.run_path(str(registry))["FONT_SPEC"]
    if not isinstance(spec, dict) or not all(isinstance(spec.get(key), str) for key in (
        "font", "sha256", "style", "source_license", "bundled_license", "license_sha256",
        "librecad_font", "librecad_sha256",
    )):
        raise AssertionError("Packaged source-row font registry is incomplete")
    for name, checksum, size in ((spec["font"], spec["sha256"], spec["bytes"]),
                                 (spec["source_license"], spec["license_sha256"], spec["license_bytes"]),
                                 (spec["librecad_font"], spec["librecad_sha256"], spec["librecad_bytes"])):
        path = app_root / "resources/fonts" / name
        if path.name != name or not path.is_file() or path.stat().st_size != size or digest(path) != checksum:
            raise AssertionError("Packaged source-row font/license differs from its fixed registry")
    return spec


def read_source_row_fixture_font(app_root: Path) -> Path:
    """Keep the fifth original input fixed when the output font is derived."""
    registry = runpy.run_path(str(app_root / "app/native_objects/source_row_font_registry.py"))["SOURCE_ROW_FONT"]
    for role in ("font", "license"):
        specification = registry[role]
        path = app_root / "resources/fonts" / specification["file"]
        if (path.name != specification["file"] or not path.is_file()
                or path.stat().st_size != specification["bytes"] or digest(path) != specification["sha256"]):
            raise AssertionError("Fifth fixture's fixed upstream font/license differs from the source registry")
    return app_root / "resources/fonts" / registry["font"]["file"]


def native_identity(entity) -> dict:
    """Read the saved public XDATA format without importing hidden app code."""
    try:
        return json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)
    except (ValueError, IndexError, AttributeError) as exc:
        raise AssertionError("Saved formal entity has no readable native identity") from exc


def _pixel_point(point) -> tuple[float, float]:
    return float(point[0]) * 200 / 25.4, 480 - float(point[1]) * 200 / 25.4


def _near_point(actual, expected, tolerance=2.0) -> bool:
    return math.dist(actual, expected) <= tolerance


def _line_points(entity) -> list[tuple[float, float]]:
    if entity.dxftype() == "LINE":
        return [_pixel_point(entity.dxf.start), _pixel_point(entity.dxf.end)]
    if entity.dxftype() == "LWPOLYLINE" and not entity.closed:
        points = list(entity.get_points("xyb"))
        if all(float(point[2]) == 0.0 for point in points):
            return [_pixel_point(point) for point in points]
    return []


def _finite_circle_intersections(points, center, radius):
    intersections = []
    for start, end in zip(points, points[1:]):
        direction = (end[0] - start[0], end[1] - start[1])
        offset = (start[0] - center[0], start[1] - center[1])
        a = sum(value * value for value in direction)
        if a == 0:
            continue
        b = 2 * sum(x * y for x, y in zip(offset, direction))
        c = sum(value * value for value in offset) - radius * radius
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            continue
        tolerance = 1e-6 / math.sqrt(a)
        for parameter in ((-b - math.sqrt(discriminant)) / (2 * a), (-b + math.sqrt(discriminant)) / (2 * a)):
            if -tolerance <= parameter <= 1 + tolerance:
                parameter = min(1.0, max(0.0, parameter))
                point = [start[i] + parameter * direction[i] for i in (0, 1)]
                if abs(math.dist(point, center) - radius) <= 1e-6:
                    intersections.append(point)
    return intersections


def _segment_enters_box(start, end, box):
    low, high = 0.0, 1.0
    for axis in (0, 1):
        delta = end[axis] - start[axis]
        if delta == 0:
            if not box[axis] <= start[axis] <= box[axis + 2]:
                return False
            continue
        left, right = sorted(((box[axis] - start[axis]) / delta, (box[axis + 2] - start[axis]) / delta))
        low, high = max(low, left), min(high, right)
        if low > high:
            return False
    return True


def _saved_line_source_check(cold, oid):
    support = [row for row in cold.get("source_checks", []) if row.get("id") == oid and row.get("type") in ("LINE", "LWPOLYLINE")]
    if len(support) != 1 or support[0].get("pass") is not True or support[0].get("source_fraction") != 1.0 or support[0].get("maximum_gap_px") != 0.0 or support[0].get("max_distance_px", math.inf) > 2.5:
        raise AssertionError("Independent complete lead lacks actual saved source support")
    return support[0]


def inspect_circular_fixture_source_gap(source_path):
    """Read the original generated fixture; never supply recognition answers."""
    from PIL import Image

    with Image.open(source_path) as source:
        image = source.convert("L")
    if image.size != (640, 480) or any(image.getpixel((x, y)) != 255 for x in (372, 373) for y in (329, 330, 331)):
        raise AssertionError("Controlled circle fixture lost its actual white source gap")
    if image.getpixel((371, 330)) != 0 or image.getpixel((374, 330)) != 0:
        raise AssertionError("White gap is not bounded by the intended independent line and circle ink")
    return {"source_sha256": digest(source_path), "original_white_columns": [372, 373], "white_gap_pixels_read": 6, "source_gap_width_px": 2, "source_pixels_modified": False}


def inspect_curve_end_fixture_source_gap(source_path):
    """Verify the sixth input's two white columns before comparing CAD gaps."""
    from PIL import Image

    with Image.open(source_path) as source:
        image = source.convert("L")
    if image.size != (640, 480) or any(image.getpixel((x, y)) != 255 for x in (374, 375) for y in (329, 330, 331)):
        raise AssertionError("Variable-width circle fixture lost its actual white source gap")
    if image.getpixel((373, 330)) != 0 or image.getpixel((376, 330)) != 0:
        raise AssertionError("White gap is not bounded by the independent line and variable-width circle ink")
    return {"source_sha256": digest(source_path), "original_white_columns": [374, 375], "white_gap_pixels_read": 6, "source_gap_width_px": 2, "source_pixels_modified": False}


def inspect_circular_members(document, objects: dict, cold: dict, *, curve_end_boundaries: bool = False) -> dict:
    """Inspect actual saved members and executed source checks, not candidates.

    Expected positions and strings belong only to this generated-input checker.
    They are not passed to the CLI, detector, character recognizer or exporter.
    Raw character payload validation is additionally required by inspect_result.
    """
    formal = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    rows = {row["id"]: row for row in objects["objects"]}
    if len(rows) != len(objects["objects"]):
        raise AssertionError("Circular fixture ledger has duplicate object identities")
    circular = [(entity, native_identity(entity)) for entity in formal if entity.dxftype() in ("CIRCLE", "INSERT")]
    markers = [(entity, identity) for entity, identity in circular if identity["kind"] == "CIRCULAR_MARKER"]
    partial = [(entity, identity) for entity, identity in circular if identity["kind"] == "CIRCLE"]
    if len(markers) != 2 or len(partial) != 1 or len(circular) != 3:
        raise AssertionError("Circular input requires two complete markers and one partial border; ordinary O/0 must not become circles")
    names = [entity.dxf.name for entity, _ in markers]
    if len(set(names)) != 2 or any(sum(entity.dxftype() == "INSERT" and entity.dxf.name == name for entity in formal) != 1 for name in names):
        raise AssertionError("Circular markers share a block definition")
    source_checks = cold.get("circular_marker_source_checks", [])
    if len(source_checks) != 3 or len({row["id"] for row in source_checks}) != 3:
        raise AssertionError("Actual circle-specific source audit was not executed for every saved border")
    by_id = {row["id"]: row for row in source_checks}
    sampling = cold.get("circular_member_source_sampling", {})
    if sampling.get("closed_circle_sweep_deg") != 360.0 or not 0 < sampling.get("maximum_sample_spacing_px", 0) <= 0.05 or sampling.get("circle_and_character_evidence_replayed") is not True or sampling.get("missing_or_unreadable_evidence_passes") is not False:
        raise AssertionError("Actual circular source evidence was not replayed")
    expected = {"F": (150, 150), "K": (400, 150)}
    actual_characters = []
    reports = []
    circle_geometry = {}
    for entity, identity in markers + partial:
        oid, kind = identity["id"], identity["kind"]
        obj = rows.get(oid, {})
        complete = kind == "CIRCULAR_MARKER"
        if obj.get("kind") != kind or obj.get("source_evidence", {}).get("components_complete") is not complete:
            raise AssertionError("Saved circle composition is not explicitly complete or partial")
        if complete:
            relation = obj.get("source_evidence", {}).get("external_endpoint_contact_review", {})
            if relation.get("status") != "NO_UNRESOLVED_OBSERVED_EXTERNAL_ENDPOINT" or relation.get("pending_contacts") != []:
                raise AssertionError("Circle plus text with a pending external relation is not a complete marker")
            members = list(document.blocks.get(entity.dxf.name))
            if Counter(member.dxftype() for member in members) != {"CIRCLE": 1, "TEXT": 1} or entity.attribs:
                raise AssertionError("Complete marker must contain exactly one real CIRCLE and one real TEXT")
            if any(float(entity.dxf.get(key, 1.0)) != 1.0 for key in ("xscale", "yscale", "zscale")):
                raise AssertionError("Marker INSERT has a non-unit or singular transform")
            expanded = list(entity.virtual_entities())
            circle = next(member for member in expanded if member.dxftype() == "CIRCLE")
            character = next(member.dxf.text for member in expanded if member.dxftype() == "TEXT")
            if character not in expected or obj.get("geometry", {}).get("text_geometry", {}).get("text") != character:
                raise AssertionError("Actual editable marker character differs from the observed fixture content")
            center = expected[character]
            actual_characters.append(character)
        else:
            if entity.dxftype() != "CIRCLE":
                raise AssertionError("An unconfirmed empty border is not a complete marker INSERT")
            circle, character, center = entity, None, (400, 330)
        variable_boundary = curve_end_boundaries and not complete
        expected_radius = 22 if variable_boundary else 25
        geometry_tolerance = 0.5 if variable_boundary else 2.0
        if not _near_point(_pixel_point(circle.dxf.center), center, geometry_tolerance) or abs(float(circle.dxf.radius) * 200 / 25.4 - expected_radius) > geometry_tolerance:
            raise AssertionError("Saved circle location or radius differs from its source border")
        if variable_boundary:
            radial = obj.get("source_evidence", {}).get("radial_fit", {})
            ring_width = obj.get("source_evidence", {}).get("ring_geometry", {}).get("stroke_width_px", math.inf)
            if (radial.get("measurement") != "PAIRED_ORIGINAL_INK_STROKE_EDGES_V1"
                    or radial.get("radial_error_measured_on") != "PAIRED_STROKE_CENTERLINE"
                    or radial.get("source_pixels_modified") is not False
                    or radial.get("full_circle_source_fraction") != 1.0
                    or radial.get("minimum_center_ink") != 1.0
                    or radial.get("clean_outer_rays", 0) < 64
                    or radial.get("p95_radial_error_px", math.inf) > 0.85
                    or radial.get("max_radial_error_px", math.inf) > 1.35
                    or not 2.0 <= ring_width <= 8.0):
                raise AssertionError("Saved variable-width boundary did not actually use the paired original stroke-edge fallback")
        circle_geometry[center] = {"center": _pixel_point(circle.dxf.center), "radius": float(circle.dxf.radius) * 200 / 25.4, "object": obj}
        check = by_id.get(oid, {})
        contracts = check.get("saved_candidate_checks", {})
        if check.get("pass") is not True or not contracts or not all(value is True for value in contracts.values()) or check.get("ring_source", {}).get("pass") is not True:
            raise AssertionError("Saved marker lacks passing actual circle/structure source checks")
        if complete and check.get("character_source", {}).get("pass") is not True:
            raise AssertionError("Complete marker lacks passing raw character source evidence")
        sweeps = [row for row in cold.get("source_checks", []) if row.get("id") == oid and row.get("type") == "CIRCLE"]
        minimum_samples = math.ceil(2 * math.pi * float(circle.dxf.radius) * 200 / 25.4 / 0.05)
        if len(sweeps) != 1 or sweeps[0].get("pass") is not True or sweeps[0].get("sampled_sweep_deg") != 360.0 or sweeps[0].get("samples", 0) < minimum_samples or not 0 < sweeps[0].get("tolerance_px", 0) <= 2.5 or sweeps[0].get("max_distance_px", math.inf) > sweeps[0]["tolerance_px"]:
            raise AssertionError("Actual saved CIRCLE did not receive a full-sweep source audit")
        reports.append({"id": oid, "kind": kind, "character": character, "block_name": entity.dxf.name if complete else None, "circle_source_check": check, "saved_circle_full_sweep": sweeps[0]})
    if sorted(actual_characters) != ["F", "K"]:
        raise AssertionError("The two independent markers did not preserve their distinct characters")
    lead_ids = []
    lead_reports = []
    for center in ((150, 150), (400, 150), (400, 330)):
        # Use the source band to locate an independent lead, not to forgive a
        # positive CAD gap. Existing supported overlap remains explicitly
        # distinct from an endpoint lying exactly on the saved circle.
        actual_center = circle_geometry[center]["center"]
        radius = circle_geometry[center]["radius"]
        variable_boundary = curve_end_boundaries and center == (400, 330)
        ring_width = circle_geometry[center]["object"].get("source_evidence", {}).get("ring_geometry", {}).get("stroke_width_px", 3.0) if variable_boundary else 3.0
        contact_tolerance = max(3.0, ring_width) / 2 + 2.5
        contact, end = (center[0] + radius, center[1]), (536, 300) if variable_boundary else (center[0] + 130, center[1])
        matching = []
        for entity in formal:
            points = _line_points(entity)
            if len(points) < 2:
                continue
            near_endpoint_number = int(points[0][0] > points[-1][0])
            if near_endpoint_number:
                points.reverse()
            direction_preserved = (all(abs((point[0] - 422) * -30 - (point[1] - 330) * 114) / math.hypot(114, 30) <= 2.5 for point in points)
                                   if variable_boundary else all(abs(point[1] - center[1]) <= 2 for point in points))
            if _near_point(points[0], contact, contact_tolerance) and _near_point(points[-1], end, 2.5 if variable_boundary else 2.0) and direction_preserved and all(right[0] > left[0] for left, right in zip(points, points[1:])):
                oid = native_identity(entity)["id"]
                support = _saved_line_source_check(cold, oid)
                signed_gap = math.dist(points[0], actual_center) - radius
                intersections = _finite_circle_intersections(points, actual_center, radius)
                if signed_gap > 1e-6 or signed_gap < -contact_tolerance or not intersections:
                    raise AssertionError("Saved finite lead does not contact its circle or exceeds the supported overlap band")
                certificate = rows.get(oid, {}).get("source_evidence", {}).get("circle_endpoint_contacts")
                new_contacts = []
                if certificate is not None:
                    if certificate.get("schema") != "native-direct-circle-end-contact-v2-observed-terminal-core" or not isinstance(certificate.get("ends"), list):
                        raise AssertionError("Saved lead has an unreadable circle endpoint contact certificate")
                    new_contacts = [end for end in certificate["ends"] if end.get("circle_id") == circle_geometry[center]["object"]["id"]]
                    if len(new_contacts) > 1:
                        raise AssertionError("Saved lead repeats its new circle endpoint certificate")
                    for restored in new_contacts:
                        certified_circle = restored.get("circle_geometry", {})
                        if abs(signed_gap) > 1e-6 or restored.get("endpoint_number") != near_endpoint_number or not _near_point(restored.get("restored_endpoint_px", (math.inf, math.inf)), points[0], 1e-6) or not _near_point(certified_circle.get("center", (math.inf, math.inf)), actual_center, 1e-6) or abs(certified_circle.get("radius_px", math.inf) - radius) > 1e-6:
                            raise AssertionError("A newly certified endpoint is not exactly on its actual saved circle")
                glyph = circle_geometry[center]["object"].get("geometry", {}).get("text_geometry")
                if glyph is not None:
                    box = [glyph["x"], glyph["y"] - glyph["height_px"], glyph["x"] + glyph["width_px"], glyph["y"]]
                    if any(_segment_enters_box(left, right, box) for left, right in zip(points, points[1:])):
                        raise AssertionError("An external lead enters the marker's actual character source box")
                matching.append(oid)
                lead_reports.append({"id": oid, "actual_circle_center_px": list(actual_center), "circle_radius_px": radius, "source_stroke_width_px": 3.0, "circle_source_stroke_width_px": ring_width, "saved_source_budget_px": 2.5, "shared_contact_half_band_px": contact_tolerance, "actual_start_px": list(points[0]), "actual_end_px": list(points[-1]), "signed_endpoint_gap_px": signed_gap, "finite_geometry_intersections_px": intersections, "contact_kind": "existing_supported_ring_overlap" if signed_gap < -1e-6 else "endpoint_on_circle", "new_certified_endpoint_checked": bool(new_contacts), "positive_CAD_gap_tolerance_px": 1e-6, "character_source_box_preserved": True, "saved_source_check": support})
        if len(matching) != 1:
            raise AssertionError("Attached line is missing, duplicated, fragmented or absorbed into a marker")
        lead_ids += matching
    protected_gaps = []
    for entity in formal:
        points = _line_points(entity)
        if len(points) < 2:
            continue
        if points[0][0] > points[-1][0]:
            points.reverse()
        gap_endpoint = (373, 330) if curve_end_boundaries else (371, 330)
        if not (_near_point(points[0], (290, 330)) and _near_point(points[-1], gap_endpoint) and all(abs(point[1] - 330) <= 2 for point in points) and all(right[0] > left[0] for left, right in zip(points, points[1:]))):
            continue
        oid = native_identity(entity)["id"]
        support = _saved_line_source_check(cold, oid)
        actual_circle = circle_geometry[(400, 330)]
        minimum_gap = math.inf
        for left, right in zip(points, points[1:]):
            dx, dy = right[0] - left[0], right[1] - left[1]
            cx, cy = actual_circle["center"]
            parameter = min(1.0, max(0.0, ((cx - left[0]) * dx + (cy - left[1]) * dy) / (dx * dx + dy * dy)))
            nearest = (left[0] + parameter * dx, left[1] + parameter * dy)
            minimum_gap = min(minimum_gap, math.dist(nearest, actual_circle["center"]) - actual_circle["radius"])
        if minimum_gap < 2.0 or _finite_circle_intersections(points, actual_circle["center"], actual_circle["radius"]):
            raise AssertionError("The independent line's real source gap was bridged or reduced below its white-gap width")
        protected_gaps.append({"id": oid, "actual_start_px": list(points[0]), "actual_end_px": list(points[-1]), "minimum_saved_geometry_gap_px": minimum_gap, "source_white_gap_width_px": 2, "finite_geometry_intersects_circle": False, "saved_source_check": support})
    if len(protected_gaps) != 1:
        raise AssertionError("The independent real-gap line is missing, duplicated, fragmented or snapped to the circle")
    lead_ids += [row["id"] for row in protected_gaps]
    allowed_geometry_ids = {identity["id"] for _, identity in circular} | set(lead_ids)
    ordinary_texts = []
    for entity in formal:
        if entity.dxftype() in ("TEXT", "MTEXT"):
            px, py = _pixel_point(entity.dxf.insert)
            if not (105 <= px <= 185 and 305 <= py <= 355):
                raise AssertionError("A marker character was duplicated outside its unique block")
            ordinary_texts.append(entity.dxf.text if entity.dxftype() == "TEXT" else entity.plain_text())
        elif native_identity(entity)["id"] not in allowed_geometry_ids:
            raise AssertionError("Fixture gained a glyph outline, duplicate or unexplained fragment")
    result = {
        "complete_marker_count": 2, "partial_circle_boundary_count": 1,
        "unique_block_definitions": names, "complete_marker_characters": sorted(actual_characters),
        "independent_external_line_ids": lead_ids, "ordinary_O_and_zero_not_circles": True,
        "independent_line_shared_contact_checks": lead_reports,
        "protected_real_gap_line_checks": protected_gaps,
        "existing_supported_overlap_line_ids": [row["id"] for row in lead_reports if row["contact_kind"] == "existing_supported_ring_overlap"],
        "all_attached_finite_geometry_contacts_circle": True,
        "all_attached_endpoints_exactly_on_circle": all(row["contact_kind"] == "endpoint_on_circle" for row in lead_reports),
        "ordinary_round_glyph_texts_if_adopted": ordinary_texts,
        "ordinary_O_and_zero_transcription_accuracy_claimed": False,
        "actual_saved_circle_and_character_audit": reports,
        "fixture_expectations_sent_to_recognizer": False,
    }
    if curve_end_boundaries:
        boundary = circle_geometry[(400, 330)]
        result.update(
            paired_edge_boundary_id=boundary["object"]["id"],
            paired_edge_boundary_center_px=list(boundary["center"]),
            paired_edge_boundary_radius_px=boundary["radius"],
            paired_edge_boundary_source_receipt=boundary["object"]["source_evidence"]["radial_fit"],
            paired_original_stroke_edge_fallback_executed=True,
            uncertain_inner_character_not_counted_as_complete=True,
            independent_boundary_contact_path_id=lead_reports[2]["id"],
            independent_marker_for_edit_id=next(identity["id"] for _, identity in markers),
        )
    return result


def _checked_record(root: Path, record: dict) -> tuple[Path, bytes]:
    name = record.get("path")
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise AssertionError("Raw circle observation path is not a relative evidence reference")
    relative = PurePosixPath(name)
    root = root.resolve()
    path = root.joinpath(*relative.parts)
    if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or root not in path.resolve().parents or not path.is_file():
        raise AssertionError("Raw circle observation is missing or outside the managed evidence")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != record.get("sha256"):
        raise AssertionError("Raw circle observation bytes differ from their source record")
    return path, data


def inspect_circular_character_payloads(
    objects, cold, evidence_root: Path, source_path: Path, pipeline_report,
    *, expected_markers=2, expected_partial=1, require_source_reference_resolution=False,
) -> dict:
    """Read v2 source payloads without importing app code or running either OCR."""
    from io import BytesIO

    import numpy as np
    from PIL import Image

    stage_path = evidence_root / "circular_markers/circular_markers.json"
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    summary = stage["summary"]
    if pipeline_report.get("circular_marker_completion") != summary or stage.get("source_sha256") != digest(source_path):
        raise AssertionError("Circle call summary is not the current ordinary pipeline report")
    payloads = [_checked_record(evidence_root, row) for row in stage["raw_evidence_files"]]
    if not payloads:
        raise AssertionError("Circle stage saved no raw payload manifest")
    result_rows = [json.loads(data) for path, data in payloads if path.name == "character_result.json"]
    actual_tesseract = sum(row["new_Tesseract_calls"] for row in result_rows)
    actual_model = sum(row["new_model_calls"] for row in result_rows)
    if summary["new_Tesseract_calls"] != actual_tesseract or summary["new_model_calls"] != actual_model or actual_tesseract <= 0 or actual_model <= 0:
        raise AssertionError("Circle stage did not record real new Tesseract and model calls")
    complete = summary.get("new_complete_markers", 0)
    pending_contacts = summary.get("circle_text_compositions_with_external_contacts_pending", 0)
    if (summary.get("circle_text_compositions") != expected_markers
            or complete + pending_contacts != expected_markers
            or (not require_source_reference_resolution and pending_contacts != 0)
            or summary.get("new_partial_boundaries") != expected_partial
            or summary.get("partial_compositions") != expected_partial):
        raise AssertionError("Ordinary pipeline summary does not separate adopted circle/TEXT compositions from partial borders and pending external contacts")
    with Image.open(source_path) as image:
        original = np.asarray(image.convert("L"))
    checks = {row["id"]: row for row in cold["circular_marker_source_checks"]}
    verified, reference_resolutions = [], []
    for obj in objects["objects"]:
        if obj["kind"] != "CIRCULAR_MARKER":
            continue
        evidence = obj["source_evidence"]["character_evidence"]
        character = checks[obj["id"]]["character_source"]
        if evidence.get("schema") != "native-circle-character-evidence-v2" or evidence.get("expected_answers_provided") is not False or evidence.get("raw_transcription_rewritten") is not False or evidence.get("source_pixels_modified") is not False:
            raise AssertionError("Complete marker lacks unchanged original v2 character evidence")
        if character.get("all_raw_artifacts_read_and_hashed") is not True or character.get("original_glyph_pixels_and_model_tensors_rechecked") is not True or character.get("new_OCR_calls") != 0 or character.get("new_model_calls") != 0:
            raise AssertionError("Actual character cold audit did not replay raw evidence without recognition")
        box = evidence["source_bbox_xyxy_px"]
        if len(box) != 4 or not all(isinstance(value, int) and not isinstance(value, bool) for value in box) or not (0 <= box[0] < box[2] <= original.shape[1] and 0 <= box[1] < box[3] <= original.shape[0]):
            raise AssertionError("Character crop is not a complete original image region")
        crop = np.ascontiguousarray(original[box[1]:box[3], box[0]:box[2]])
        adopted_geometry = evidence["text_geometry"]
        resolution = evidence.get("source_reference_resolution")
        if resolution is not None:
            reference_resolutions.append(inspect_source_reference_adoption(evidence_root, obj, character))
            adopted_geometry = resolution["text_geometry"]
        elif evidence["decision"].get("accepted") is not True:
            raise AssertionError("Saved marker has neither a strict raw decision nor a replayed source reference resolution")
        if hashlib.sha256(crop.tobytes()).hexdigest() != evidence["source_crop_array_sha256"] or adopted_geometry != obj["geometry"]["text_geometry"]:
            raise AssertionError("Saved marker character lost its original glyph/content binding")
        t_views, p_views = evidence["tesseract_views"], evidence["ppocr_views"]
        if not 1 <= len(t_views) <= 2 or len(t_views) != len(p_views) or character["Tesseract_views_replayed"] != len(t_views) or character["PP_OCR_views_replayed"] != len(p_views):
            raise AssertionError("Character source views exceed or omit the frozen finite observations")
        _, identity_raw = _checked_record(evidence_root, evidence["model_identity"])
        if json.loads(identity_raw).get("providers") != ["CPUExecutionProvider"]:
            raise AssertionError("Circle character did not use the actual CPU model")
        t_calls = p_calls = 0
        for view in t_views:
            _, raw = _checked_record(evidence_root, view["raw_tsv"])
            _, metadata = _checked_record(evidence_root, view["metadata"])
            _, png = _checked_record(evidence_root, view["recognition_image"])
            metadata = json.loads(metadata)
            norm = view["normalization"]
            scale = norm["pixel_scale"]
            pad = norm["external_white_padding_px"]
            if scale not in ([1, 1], [2, 2]) or not isinstance(pad, int) or not 0 <= pad <= 32 or norm["source_bbox_xyxy_px"] != box or norm["original_source_modified"] is not False:
                raise AssertionError("Tesseract normalization is not an original-glyph finite view")
            actual = np.pad(np.repeat(np.repeat(crop, scale[0], axis=0), scale[1], axis=1), pad, constant_values=255)
            with Image.open(BytesIO(png)) as image:
                unchanged = np.array_equal(actual, np.asarray(image.convert("L")))
            if not unchanged or hashlib.sha256(actual.tobytes()).hexdigest() != norm["recognition_input_array_sha256"] or metadata["status"] != "COMPLETED" or metadata["return_code"] != 0 or metadata["tsv_sha256"] != hashlib.sha256(raw).hexdigest() or metadata["image_sha256"] != hashlib.sha256(png).hexdigest():
                raise AssertionError("Actual Tesseract payload differs from its original glyph normalization")
            called = view["command_executed_for_this_request"]
            if not isinstance(called, bool) or called is not metadata["command_executed_for_this_request"]:
                raise AssertionError("Circle Tesseract call count includes an unexecuted/cache observation")
            t_calls += called
        for view in p_views:
            _, raw = _checked_record(evidence_root, view["prediction_file"])
            prediction = json.loads(raw)
            norm = view["normalization"]
            pad = norm["external_white_padding_px"]
            if not isinstance(pad, int) or not 0 <= pad <= 32 or norm["source_bbox_xyxy_px"] != box or norm["original_source_modified"] is not False:
                raise AssertionError("PP-OCR normalization is not an original-glyph finite view")
            actual = np.pad(crop, pad, constant_values=255)
            raw_sha = hashlib.sha256(actual.tobytes()).hexdigest()
            if prediction != view["prediction"] or prediction.get("input_array_sha256") != raw_sha or norm["recognition_input_array_sha256"] != raw_sha or prediction.get("raw_transcription_rewritten") is not False or prediction.get("source_geometry_modified") is not False:
                raise AssertionError("Actual PP-OCR payload differs from the original glyph")
            called = view["model_inference_executed_for_this_request"]
            if not isinstance(called, bool) or called is not view["observation_receipt"]["model_inference_executed_for_this_request"]:
                raise AssertionError("Circle model call count includes an unexecuted/cache observation")
            p_calls += called
        if evidence["new_Tesseract_calls"] != t_calls or evidence["new_model_calls"] != p_calls:
            raise AssertionError("Character call counters disagree with actual producer receipts")
        verified.append({"id": obj["id"], "text": adopted_geometry["text"], "adoption_basis": character.get("adoption_basis"), "new_Tesseract_calls": t_calls, "new_model_calls": p_calls, "Tesseract_views": len(t_views), "PP_OCR_views": len(p_views)})
    if len(verified) != expected_markers:
        raise AssertionError("Not every complete marker has verified original character payloads")
    if require_source_reference_resolution and not reference_resolutions:
        raise AssertionError("Actual ordinary conversion did not exercise same-source circle character resolution")
    return {"verified_complete_characters": verified, "source_reference_resolutions": reference_resolutions, "raw_stage_files_read_and_hashed": len(payloads), "new_Tesseract_calls": actual_tesseract, "new_model_calls": actual_model, "global_cross_engine_calls_required": False, "inspection_executed_recognition": False}


def inspect_source_reference_adoption(evidence_root, obj, character):
    """Bind the new adoption route to its actual frozen source witnesses."""
    evidence = obj["source_evidence"]["character_evidence"]
    resolution = evidence["source_reference_resolution"]
    decision = resolution["decision"]
    replay = character.get("source_reference_verification", {})
    if (evidence["decision"].get("accepted") is not False
            or resolution.get("schema") != "native-circle-source-reference-resolution-v1"
            or resolution.get("adoption_basis") != "SAME_SOURCE_FROZEN_GLYPH_REFERENCES"
            or resolution.get("original_raw_decision_and_conflicts_retained") is not True
            or resolution.get("new_OCR_calls") != 0 or resolution.get("new_model_calls") != 0
            or decision.get("accepted") is not True
            or decision.get("raw_observations_rewritten") is not False
            or decision.get("confidence_thresholds_changed") is not False
            or decision.get("missing_raw_competing_reference_classes") != []
            or decision.get("unexcluded_competing_reference_classes") != []
            or character.get("adoption_basis") != "SAME_SOURCE_FROZEN_GLYPH_REFERENCES"
            or character.get("source_reference_resolution_recomputed") is not True
            or replay.get("pass") is not True
            or replay.get("reference_raw_sources_and_original_pixels_replayed") is not True
            or replay.get("comparison_and_adoption_recomputed") is not True):
        raise AssertionError("Actual circle character source resolution or original failed raw decision was not replayed")
    _, raw_pool = _checked_record(evidence_root, resolution["reference_pool"])
    pool = json.loads(raw_pool)
    if (pool.get("frozen_before_any_resolution") is not True
            or pool.get("upgraded_characters_used_as_references") is not False
            or pool.get("source_sha256") != obj["source_evidence"].get("source_sha256")):
        raise AssertionError("Circle reference pool is not a frozen original-source pool")
    refs = {row["reference_key"]: row for row in pool["references"]}
    keys = decision["positive_reference_keys_by_character"][decision["text"]]
    if len(keys) < 2 or len(set(keys)) != len(keys) or keys != replay.get("verified_positive_reference_keys"):
        raise AssertionError("Resolved circle character lacks two independently replayed source positions")
    boxes = [evidence["source_bbox_xyxy_px"]]
    for key in keys:
        ref = refs[key]
        box = ref["source_component"]["bbox_xyxy_px"]
        if ref["character"] != decision["text"] or any(
            max(box[0], old[0]) < min(box[2], old[2]) and max(box[1], old[1]) < min(box[3], old[3])
            for old in boxes
        ):
            raise AssertionError("Character reference reused the target or another reference source domain")
        boxes.append(box)
    if len(decision["all_available_reference_classes"]) < 2:
        raise AssertionError("Generated source reference input did not exercise a competing character class")
    return {"id": obj["id"], "text": decision["text"], "original_raw_decision_retained": True,
            "positive_original_reference_keys": keys,
            "competing_classes_checked": [x for x in decision["all_available_reference_classes"] if x != decision["text"]],
            "frozen_pool_sha256": resolution["reference_pool"]["sha256"], "actual_source_replay_checked": True}


def inspect_circle_completion_members(document, objects, cold, source_path) -> dict:
    """Check the saved four-circle public fixture, independently of recognition.

    Fixture positions/content below are assertions only. Production receives
    the PNG through its ordinary entry point and receives no expected labels.
    The caller separately replays every raw character and reference-bank file.
    Existing smoke helpers are intentionally used without importing app code.
    """
    from collections import Counter
    import hashlib
    import math
    from pathlib import Path

    import numpy as np
    from PIL import Image

    source_path = Path(source_path)
    with Image.open(source_path) as source:
        gray = np.asarray(source.convert("L"))
    if gray.shape != (480, 640):
        raise AssertionError("Circle completion fixture has changed source dimensions")
    if any(int(gray[y, x]) != 255 for x in (121, 122, 123) for y in (339, 340, 341)):
        raise AssertionError("The generated circle completion source lost its three-column real white gap")
    if int(gray[340, 120]) != 0 or int(gray[340, 124]) != 0:
        raise AssertionError("The real gap is not bounded by the intended independent line and original ring ink")

    formal = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    rows = {obj["id"]: obj for obj in objects["objects"]}
    if len(rows) != len(objects["objects"]):
        raise AssertionError("Circle completion ledger repeats an object identity")
    identities = [(entity, native_identity(entity)) for entity in formal]
    if len({identity["id"] for _, identity in identities}) != len(identities):
        raise AssertionError("Saved circle completion drawing repeats a formal object")
    markers = [(entity, identity) for entity, identity in identities if identity["kind"] == "CIRCULAR_MARKER"]
    if len(markers) != 4 or any(entity.dxftype() != "INSERT" for entity, _ in markers):
        raise AssertionError("Circle completion requires four actual editable circle/text INSERTs")
    if any(entity.dxftype() == "CIRCLE" or identity["kind"] == "CIRCLE" for entity, identity in identities):
        raise AssertionError("A boundary-only circle or a duplicate circle remains beside an upgraded marker")
    names = [entity.dxf.name for entity, _ in markers]
    if len(set(names)) != 4 or any(sum(entity.dxftype() == "INSERT" and entity.dxf.name == name for entity in formal) != 1 for name in names):
        raise AssertionError("Circle completion instances share a block definition")
    checks = cold.get("circular_marker_source_checks", [])
    if len(checks) != 4 or len({row["id"] for row in checks}) != 4:
        raise AssertionError("The saved audit did not individually check all four circle/text objects")
    by_id = {row["id"]: row for row in checks}
    sampling = cold.get("circular_member_source_sampling", {})
    if (sampling.get("closed_circle_sweep_deg") != 360.0
            or not 0 < sampling.get("maximum_sample_spacing_px", 0) <= 0.05
            or sampling.get("circle_and_character_evidence_replayed") is not True
            or sampling.get("missing_or_unreadable_evidence_passes") is not False):
        raise AssertionError("Saved circle source sampling or evidence replay was not performed")

    expected = {(150, 130): "E", (430, 130): "E", (150, 340): "E", (430, 340): "F"}
    circles, marker_reports = {}, []
    target_marker_id = None
    for entity, identity in markers:
        oid = identity["id"]
        obj = rows.get(oid, {})
        if obj.get("kind") != "CIRCULAR_MARKER" or obj.get("source_evidence", {}).get("components_complete") is not True:
            raise AssertionError("A saved circle/text INSERT is not explicitly a complete composition")
        members = list(document.blocks.get(entity.dxf.name))
        if Counter(member.dxftype() for member in members) != {"CIRCLE": 1, "TEXT": 1} or entity.attribs:
            raise AssertionError("A circle/text block must contain exactly one genuine CIRCLE and one editable TEXT")
        if any(float(entity.dxf.get(axis, 1.0)) != 1.0 for axis in ("xscale", "yscale", "zscale")):
            raise AssertionError("Circle/text INSERT has a singular or non-unit transform")
        if abs(float(entity.dxf.get("rotation", 0))) > 1e-8:
            raise AssertionError("The saved fixture marker has an unexpected block rotation")
        expanded = list(entity.virtual_entities())
        circle = next(member for member in expanded if member.dxftype() == "CIRCLE")
        text = next(member for member in expanded if member.dxftype() == "TEXT")
        center = _pixel_point(circle.dxf.center)
        radius = float(circle.dxf.radius) * 200 / 25.4
        matches = [point for point in expected if _near_point(center, point, 0.5)]
        if len(matches) != 1 or matches[0] in circles or abs(radius - 25.0) > 0.5:
            raise AssertionError("A final circle is missing, duplicated, displaced or incorrectly sized")
        position = matches[0]
        letter = expected[position]
        if text.dxf.text != letter or obj.get("geometry", {}).get("text_geometry", {}).get("text") != letter:
            raise AssertionError("A saved editable inner character differs from its generated source")
        if abs(float(text.dxf.get("rotation", 0.0))) > 1e-8:
            raise AssertionError("An inner character has an unexpected rotation")

        # Read the actual interior ink of this small generated source. The
        # 20px disk is wholly inside its 23px inner ring and does not alter OCR.
        cx, cy = position
        yy, xx = np.indices(gray.shape)
        interior = (np.hypot(xx - cx, yy - cy) < 20) & (gray < 128)
        sy, sx = np.nonzero(interior)
        if not len(sx):
            raise AssertionError("A generated inner character has no original ink")
        source_box = [int(sx.min()), int(sy.min()), int(sx.max()) + 1, int(sy.max()) + 1]
        glyph = obj["geometry"]["text_geometry"]
        expected_geometry = {"text": letter, "x": source_box[0], "y": source_box[3],
                             "width_px": source_box[2] - source_box[0],
                             "height_px": source_box[3] - source_box[1], "rotation_deg_image": 0.0}
        if glyph != expected_geometry:
            raise AssertionError("The saved glyph's source location or dimensions differ from the complete original interior")
        actual_height_px = float(text.dxf.height) * 200 / 25.4
        actual_baseline = _pixel_point(text.dxf.insert)
        if abs(actual_height_px - glyph["height_px"]) > 1e-7 or abs(actual_baseline[1] - glyph["y"]) > 1e-7:
            raise AssertionError("Actual TEXT height or baseline differs from its original glyph")
        if not 0 < float(text.dxf.get("width", 1.0)) < 3:
            raise AssertionError("Actual TEXT has an invalid width transform")
        corners = [(source_box[x], source_box[y]) for x in (0, 2) for y in (1, 3)]
        glyph_circle_gap = radius - max(math.dist(point, center) for point in corners)
        if glyph_circle_gap < 5:
            raise AssertionError("The newly editable character touches or overlaps its circle boundary")
        check = by_id.get(oid, {})
        contracts = check.get("saved_candidate_checks", {})
        character_check = check.get("character_source", {})
        if (check.get("pass") is not True or not contracts or not all(value is True for value in contracts.values())
                or check.get("ring_source", {}).get("pass") is not True or character_check.get("pass") is not True):
            raise AssertionError("Actual saved circle/text source geometry or character evidence failed its cold check")
        sweeps = [row for row in cold.get("source_checks", []) if row.get("id") == oid and row.get("type") == "CIRCLE"]
        if (len(sweeps) != 1 or sweeps[0].get("pass") is not True or sweeps[0].get("sampled_sweep_deg") != 360.0
                or sweeps[0].get("samples", 0) < math.ceil(2 * math.pi * radius / 0.05)):
            raise AssertionError("The saved circle was not audited over its complete finite circumference")
        original = obj["source_evidence"]["character_evidence"]
        if position == (150, 340):
            resolved = original.get("source_reference_resolution", {})
            verified = character_check.get("source_reference_verification", {})
            if (original.get("decision", {}).get("accepted") is not False
                    or resolved.get("schema") != "native-circle-source-reference-resolution-v1"
                    or resolved.get("adoption_basis") != "SAME_SOURCE_FROZEN_GLYPH_REFERENCES"
                    or resolved.get("decision", {}).get("accepted") is not True
                    or resolved.get("decision", {}).get("text") != letter
                    or resolved.get("original_raw_decision_and_conflicts_retained") is not True
                    or character_check.get("adoption_basis") != "SAME_SOURCE_FROZEN_GLYPH_REFERENCES"
                    or character_check.get("source_reference_resolution_recomputed") is not True
                    or verified.get("pass") is not True
                    or len(set(verified.get("verified_positive_reference_keys", []))) < 2
                    or set(verified.get("compared_reference_classes", [])) != {"E", "F"}
                    or verified.get("comparison_and_adoption_recomputed") is not True):
                raise AssertionError("The actual target did not trigger and cold-replay the new source-reference character route")
            target_marker_id = oid
        elif original.get("decision", {}).get("accepted") is not True or original.get("source_reference_resolution") is not None:
            raise AssertionError("The two donor characters and competing F must retain their original strict recognition route")
        circles[position] = {"id": oid, "center": center, "radius": radius, "glyph_box": source_box}
        marker_reports.append({"id": oid, "block_name": entity.dxf.name, "character": letter,
                               "actual_circle_center_px": list(center), "actual_radius_px": radius,
                               "source_glyph_bbox_xyxy_px": source_box,
                               "actual_TEXT_height_px": actual_height_px,
                               "glyph_box_minimum_circle_gap_px": glyph_circle_gap,
                               "adoption_basis": character_check.get("adoption_basis"),
                               "actual_saved_structure_and_character_source_pass": True})
    if set(circles) != set(expected) or target_marker_id is None:
        raise AssertionError("The final drawing did not contain the complete four-position fixture")

    leads, lead_ids = [], []
    for position, circle in circles.items():
        cx, cy = position
        near = (cx + circle["radius"], cy)
        endpoint = (cx + 130, cy)
        matching = []
        for entity, identity in identities:
            points = _line_points(entity)
            if len(points) < 2:
                continue
            if points[0][0] > points[-1][0]:
                points.reverse()
            if not (_near_point(points[0], near, 4.0) and _near_point(points[-1], endpoint, 2.0)
                    and all(abs(point[1] - cy) <= 2.0 for point in points)
                    and all(right[0] > left[0] for left, right in zip(points, points[1:]))):
                continue
            oid = identity["id"]
            support = _saved_line_source_check(cold, oid)
            intersections = _finite_circle_intersections(points, circle["center"], circle["radius"])
            signed_gap = math.dist(points[0], circle["center"]) - circle["radius"]
            if signed_gap > 1e-6 or signed_gap < -4.0 or not intersections:
                raise AssertionError("A saved right-hand independent line no longer meets its circle")
            # Monotone rightward geometry cannot enter a glyph box wholly left
            # of its first point; reject any deeper interior path explicitly.
            if points[0][0] <= circle["glyph_box"][2]:
                raise AssertionError("A separately editable external line enters the inner character")
            matching.append(oid)
            leads.append({"id": oid, "circle_id": circle["id"], "circle_position_px": list(position),
                          "actual_start_px": list(points[0]), "actual_end_px": list(points[-1]),
                          "signed_endpoint_gap_px": signed_gap, "finite_circle_intersections_px": intersections,
                          "contact_kind": "existing_supported_ring_overlap" if signed_gap < -1e-6 else "endpoint_on_circle",
                          "saved_source_check": support})
        if len(matching) != 1:
            raise AssertionError("A complete right-hand path is missing, fragmented, duplicated or absorbed into its block")
        lead_ids += matching
    if len(set(lead_ids)) != 4:
        raise AssertionError("Four external paths are not independently represented")

    gap_lines = []
    target_circle = circles[(150, 340)]
    for entity, identity in identities:
        points = _line_points(entity)
        if len(points) < 2:
            continue
        if points[0][0] > points[-1][0]:
            points.reverse()
        if not (_near_point(points[0], (40, 340), 2.0) and _near_point(points[-1], (120, 340), 1.0)
                and all(abs(point[1] - 340) <= 2.0 for point in points)
                and all(right[0] > left[0] for left, right in zip(points, points[1:]))):
            continue
        oid = identity["id"]
        support = _saved_line_source_check(cold, oid)
        minimum_gap = math.inf
        for left, right in zip(points, points[1:]):
            dx, dy = right[0] - left[0], right[1] - left[1]
            cx, cy = target_circle["center"]
            t = min(1.0, max(0.0, ((cx - left[0]) * dx + (cy - left[1]) * dy) / (dx * dx + dy * dy)))
            nearest = (left[0] + t * dx, left[1] + t * dy)
            minimum_gap = min(minimum_gap, math.dist(nearest, target_circle["center"]) - target_circle["radius"])
        if minimum_gap < 3.0 or _finite_circle_intersections(points, target_circle["center"], target_circle["radius"]):
            raise AssertionError("The real three-column white gap was bridged by a saved native path")
        gap_check = [row for row in cold.get("circle_white_gap_protection_checks", []) if row.get("id") == oid]
        if len(gap_check) != 1 or gap_check[0].get("pass") is not True or gap_check[0].get("actual_saved_line_checked") is not True:
            raise AssertionError("The actual saved gap line did not receive its source white-gap check")
        gap_lines.append({"id": oid, "actual_start_px": list(points[0]), "actual_end_px": list(points[-1]),
                          "minimum_saved_geometry_gap_px": minimum_gap,
                          "original_white_columns": [121, 122, 123], "source_white_gap_width_px": 3,
                          "finite_geometry_intersects_circle": False, "saved_source_check": support,
                          "saved_white_gap_check": gap_check[0]})
    if len(gap_lines) != 1:
        raise AssertionError("The independent real-gap line is missing, fragmented or duplicated")
    permitted_ids = {circle["id"] for circle in circles.values()} | set(lead_ids) | {gap_lines[0]["id"]}
    if len(formal) != 9 or {identity["id"] for _, identity in identities} != permitted_ids or set(rows) != permitted_ids:
        raise AssertionError("Circle completion gained a duplicate glyph, stray circle, fragment or unexplained formal object")
    if cold.get("exact_duplicate_segments"):
        raise AssertionError("The final circle completion drawing contains duplicate native segments")
    path_id = next(row["id"] for row in leads if row["circle_position_px"] == [150, 340])
    return {"complete_marker_count": 4, "partial_circle_boundary_count": 0,
            "unique_block_definitions": names, "complete_marker_characters": ["E", "E", "E", "F"],
            "target_marker_id": target_marker_id, "independent_path_id": path_id,
            "path_id": path_id, "independent_marker_for_edit_id": target_marker_id,
            "independent_boundary_contact_path_id": path_id,
            "independent_external_line_ids": lead_ids + [gap_lines[0]["id"]],
            "actual_marker_geometry_and_TEXT_checks": marker_reports,
            "independent_line_shared_contact_checks": leads,
            "protected_real_gap_line_checks": gap_lines,
            "original_source_gap": {"source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                                    "original_white_columns": [121, 122, 123], "source_gap_width_px": 3,
                                    "source_pixels_modified": False},
            "actual_new_source_reference_route_triggered_and_replayed": True,
            "original_target_two_engine_rejection_retained": True,
            "all_right_paths_independent_and_touching_circle": True,
            "fixture_expectations_sent_to_recognizer": False}


"""Standalone Windows smoke member check; paste into windows_native_smoke.py.

The function uses that script's existing public-format helpers. It imports no
application code and inspects the real saved DXF, its bound cold audit, and PNG.
The target of the new contact may remain a partial bare circle; the separate
complete F control is then the explicit block-edit target.
"""


def inspect_terminal_core_members(document, objects, cold, source_path) -> dict:
    import numpy as np
    from PIL import Image

    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    rows = objects.get("objects", [])
    ledger = {row["id"]: row for row in rows}
    identities = [native_identity(entity) for entity in entities]
    saved = {identity["id"]: entity for identity, entity in zip(identities, entities)}
    texts = [entity for entity in entities if entity.dxftype() == "TEXT"]
    circles = [entity for entity in entities if entity.dxftype() in ("CIRCLE", "INSERT")]
    lines = [entity for entity in entities if entity.dxftype() == "LINE"]
    paths = [entity for entity in entities if entity.dxftype() == "LWPOLYLINE"]
    if (len(entities) != 7 or len(texts) != 3 or len(circles) != 2 or len(lines) != 1 or len(paths) != 1
            or Counter(entity.dxf.text for entity in texts) != Counter(["STORAGE42", "STORE", "AX7"])
            or len(ledger) != len(rows) or len(saved) != len(entities) or set(saved) != set(ledger)):
        raise AssertionError("Terminal-core input did not save three complete TEXTs, two circles, one whole path and one gap LINE")
    if (cold.get("source_gate_pass") is not True or cold.get("ezdxf_errors") != []
            or cold.get("ezdxf_in_memory_fixes") != [] or cold.get("exact_duplicate_segments")):
        raise AssertionError("Actual saved terminal-core input failed its cold source/duplicate gate")
    if digest(Path(source_path)) != objects.get("source_sha256"):
        raise AssertionError("Terminal-core fixture source identity changed")
    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    if source.shape != (480, 640):
        raise AssertionError("Terminal-core source coordinate contract changed")
    text_checks = {row.get("id"): row for row in cold.get("native_text_candidate_checks", [])}
    for entity in texts:
        oid = native_identity(entity)["id"]
        if (ledger[oid].get("kind") != "TEXT" or ledger[oid].get("geometry", {}).get("text") != entity.dxf.text
                or text_checks.get(oid, {}).get("pass") is not True
                or entity.dxf.style != "I2CAD_TEXT"
                or document.styles.get(entity.dxf.style).dxf.font != "DejaVuSans.ttf"):
            raise AssertionError("A complete fixture TEXT changed content, style or saved source binding")
    marker_checks = {row.get("id"): row for row in cold.get("circular_marker_source_checks", [])}
    round_members, complete_markers = {}, []
    for entity in circles:
        oid = native_identity(entity)["id"]
        row = ledger[oid]
        complete = row.get("kind") == "CIRCULAR_MARKER"
        if row.get("kind") not in ("CIRCLE", "CIRCULAR_MARKER") or row.get("source_evidence", {}).get("components_complete") is not complete:
            raise AssertionError("Terminal-core fixture circle components are not explicitly complete or pending")
        if complete:
            if entity.dxftype() != "INSERT" or entity.attribs:
                raise AssertionError("Complete circle control lost its independent editable block")
            if (Counter(member.dxftype() for member in document.blocks.get(entity.dxf.name)) != {"CIRCLE": 1, "TEXT": 1}
                    or any(float(entity.dxf.get(key, 1)) != 1 for key in ("xscale", "yscale", "zscale"))):
                raise AssertionError("Circle block has duplicate members, nested paths or a singular transform")
            expanded = list(entity.virtual_entities())
            circle = next(member for member in expanded if member.dxftype() == "CIRCLE")
            character = next(member.dxf.text for member in expanded if member.dxftype() == "TEXT")
            if character != "F" or row.get("geometry", {}).get("text_geometry", {}).get("text") != character:
                raise AssertionError("Saved editable circle control has the wrong complete character")
            complete_markers.append(oid)
        else:
            if entity.dxftype() != "CIRCLE":
                raise AssertionError("An uncertain target character was presented as a completed circle block")
            circle, character = entity, None
        center, radius = _pixel_point(circle.dxf.center), float(circle.dxf.radius) * 200 / 25.4
        check = marker_checks.get(oid, {})
        if (check.get("pass") is not True or check.get("ring_source", {}).get("pass") is not True
                or not check.get("saved_candidate_checks") or any(value is not True for value in check["saved_candidate_checks"].values())
                or (complete and check.get("character_source", {}).get("pass") is not True)):
            raise AssertionError("Saved circle geometry or actual editable character failed its raw-source audit")
        round_members[oid] = {"center": center, "radius": radius, "complete": complete, "text": character}
    path = paths[0]
    path_id = native_identity(path)["id"]
    path_row = ledger[path_id]
    evidence = path_row.get("source_evidence", {})
    proof = evidence.get("text_contact_path", {})
    certificate = evidence.get("circle_endpoint_contacts", {})
    ends = certificate.get("ends", [])
    if (path_row.get("kind") != "CONNECTION_PATH" or proof.get("schema") != "source-text-contact-native-path-v1"
            or len(ends) != 1 or ends[0].get("endpoint_extension_shape") != "REPLAYED_ORIGINAL_TERMINAL_CORE_TO_OPPOSITE_RING_BRANCHES"):
        raise AssertionError("Ordinary input did not actually adopt one whole path using the new original-terminal-core rule")
    end = ends[0]
    circle_id = end.get("circle_id")
    target_circle = round_members.get(circle_id)
    if (target_circle is None or not _near_point(target_circle["center"], (355, 330), 0.5)
            or abs(target_circle["radius"] - 18) > 0.5):
        raise AssertionError("Completed source core touches the wrong actual saved circle")
    planned = proof.get("path", {}).get("representation", {})
    geometry_check = inspect_contact_path_vertices(document, objects, cold, path, path_row, planned, source_path)
    if (geometry_check.get("added_terminal_segments") != 1
            or geometry_check.get("endpoint_certificate_replayed") is not True
            or geometry_check.get("original_vertices_continuously_preserved") != len(planned.get("points", []))
            or sum(math.dist(a, b) for a, b in zip(_line_points(path), _line_points(path)[1:])) < 200):
        raise AssertionError("New terminal span replaced the old body or became a separate fragment")
    endpoint_checks = [row for row in cold.get("circle_endpoint_contact_checks", []) if row.get("id") == path_id]
    if (len(endpoint_checks) != 1 or endpoint_checks[0].get("pass") is not True
            or endpoint_checks[0].get("actual_saved_geometry_checked") is not True
            or endpoint_checks[0].get("external_entity_is_independent") is not True):
        raise AssertionError("Actual saved whole-path endpoint was not independently cold checked")
    contact = cold.get("text_contact_source_checks", {})
    checked = {row.get("id"): row for row in contact.get("checks", [])}
    selected = checked.get(path_id, {})
    if (contact.get("pass") is not True or contact.get("target_ids") != [path_id]
            or selected.get("pass") is not True
            or selected.get("original_source_plan_replay", {}).get("pass") is not True
            or selected.get("checks", {}).get("original_source_plan_replayed") is not True
            or selected.get("checks", {}).get("actual_vertices") is not True
            or checked.get("TEXT_CONTACT_DUPLICATES", {}).get("conflicts") != []):
        raise AssertionError("Saved original terminal core was not replayed from the actual source graph and path plan")
    protected = checked.get("TEXT_CONTACT_NEIGHBORS", {})
    if (protected.get("pass") is not True or protected.get("protected_count") != len(entities) - 1
            or {row.get("id") for row in protected.get("objects", [])} != set(ledger) - {path_id}
            or any(row.get("pass") is not True for row in protected.get("objects", []))):
        raise AssertionError("Whole-path completion changed an unrelated saved neighbor")
    control_id = next(oid for oid, geometry in round_members.items() if oid != circle_id)
    control = round_members[control_id]
    if not _near_point(control["center"], (160, 350), 0.5) or abs(control["radius"] - 18) > 0.5 or control_id not in complete_markers:
        raise AssertionError("Independent complete circle control was lost")
    line = lines[0]
    line_id = native_identity(line)["id"]
    line_row = ledger[line_id]
    actual_line = _line_points(line)
    planned_line = [line_row.get("geometry", {}).get(key) for key in ("start", "end")]
    if (line_row.get("kind") != "LINE" or len(actual_line) != 2
            or any(not _near_point(a, b, 1e-6) for a, b in zip(actual_line, planned_line))
            or not _near_point(actual_line[0], (182, 350), 1.0)
            or not _near_point(actual_line[1], (262, 350), 1.0)):
        raise AssertionError("Independent finite white-gap LINE was changed or merged into a marker")
    start, finish = map(np.asarray, actual_line)
    axis = finish - start
    t = float(np.clip((np.asarray(control["center"]) - start) @ axis / (axis @ axis), 0, 1))
    distance = float(np.linalg.norm(start + t * axis - control["center"])) - control["radius"]
    gap_proof = line_row.get("source_evidence", {}).get("circle_white_gap_protection", {})
    gaps = gap_proof.get("ends", [])
    cold_gaps = [row for row in cold.get("circle_white_gap_protection_checks", []) if row.get("id") == line_id]
    if (not 2.5 < distance < 5 or not np.all(source[346:355, 180:182] >= 128)
            or len(gaps) != 1 or gaps[0].get("circle_id") != control_id
            or gaps[0].get("status") != "PROTECTED_SOURCE_WHITE_GAP_NO_CONNECTION_REQUIRED"
            or gaps[0].get("exterior_and_ring_are_different_local_eight_connected_components") is not True
            or gaps[0].get("complete_white_strip_width_px", 0) < 1.9
            or len(cold_gaps) != 1 or cold_gaps[0].get("pass") is not True
            or cold_gaps[0].get("actual_saved_line_checked") is not True):
        raise AssertionError("Original two-column white gap was bridged by the finite saved LINE")
    # The source-core target is currently partial. Never describe this as a
    # completed circle+text; edit the independently proved control instance.
    edit_marker = circle_id if target_circle["complete"] else control_id
    return {
        "schema": "windows-saved-original-terminal-core-v1",
        "complete_TEXTs": sorted(entity.dxf.text for entity in texts),
        "formal_object_count": len(entities),
        "complete_circle_text_objects": len(complete_markers),
        "partial_circle_boundary_objects": len(circles) - len(complete_markers),
        "target_marker_id": edit_marker,
        "independent_path_id": path_id,
        "contact_target_circle_id": circle_id,
        "contact_target_circle_text_complete": target_circle["complete"],
        "edit_marker_is_separate_complete_control": edit_marker != circle_id,
        "core_completion_shape": end["endpoint_extension_shape"],
        "core_extension_length_px": end["extension_length_px"],
        "saved_whole_path_geometry": geometry_check,
        "new_rule_actual_saved_endpoint_check": endpoint_checks[0],
        "gap_line_id": line_id,
        "gap_control_circle_id": control_id,
        "actual_finite_line_circle_gap_px": distance,
        "original_white_columns": [180, 181],
        "actual_saved_white_gap_check": cold_gaps[0],
        "all_formal_objects_accounted_for": True,
        "all_original_neighbor_paths_claimed_complete": False,
        "GUI_operations_claimed": False,
    }


def inspect_single_line_members(document, objects: dict, cold: dict, font_path: Path) -> dict:
    """Original strict contract: every one of the three full labels is required."""
    return _inspect_single_line_members_for_labels(
        document, objects, cold, font_path, SINGLE_LINE_LABEL_FIXTURE
    )


def _inspect_single_line_members_for_labels(
    document, objects: dict, cold: dict, font_path: Path, required_labels, *,
    fixture_labels=SINGLE_LINE_LABEL_FIXTURE,
    neighbor_fixture=SINGLE_LINE_NEIGHBOR_FIXTURE,
    label_font_size=26, additional_path_count=0,
) -> dict:
    """Check actual saved whole labels, source bindings, and independent neighbors.

    This is a post-save assertion for the fixed generated fixture. It cannot
    supply transcription, coordinates, or acceptance hints to the worker.
    """
    from ezdxf.fonts import fonts
    from PIL import Image, ImageDraw, ImageFont

    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    expected_strings = [item[0] for item in required_labels] + ["STORE"]
    texts = [entity for entity in entities if entity.dxftype() == "TEXT"]
    paths = [entity for entity in entities if entity.dxftype() in ("LINE", "LWPOLYLINE")]
    if (len(entities) != len(texts) + len(paths)
            or Counter(entity.dxf.text for entity in texts) != Counter(expected_strings)):
        raise AssertionError("Single-line fixture did not save one complete literal TEXT per label/control")
    if len(paths) != len(neighbor_fixture) + additional_path_count:
        raise AssertionError("Single-line fixture lost, duplicated, or fragmented an independent source line")
    rows = objects.get("objects", [])
    ledger = {row["id"]: row for row in rows}
    if len(ledger) != len(rows):
        raise AssertionError("Single-line fixture ledger has duplicate object identities")
    candidate_checks = cold.get("native_text_candidate_checks", [])
    candidate_checked_ids = [row.get("id") for row in candidate_checks]
    if (len(set(candidate_checked_ids)) != len(candidate_checked_ids)
            or set(candidate_checked_ids) != {native_identity(entity)["id"] for entity in texts}
            or any(row.get("pass") is not True or row.get("type") != "NATIVE_TEXT_CANDIDATE_BINDING" for row in candidate_checks)):
        raise AssertionError("Actual single-line TEXT lacks complete saved candidate/layout bindings")
    checks = cold.get("single_line_text_source_checks", [])
    checked_ids = [row.get("id") for row in checks]
    if len(set(checked_ids)) != len(checked_ids):
        raise AssertionError("Single-line source checks have duplicate identities")
    saved_checks = {row.get("id"): row for row in checks}
    mm = 25.4 / 200
    positions = dict(fixture_labels)
    positions["STORE"] = (460, 64)
    text_results = []
    recovered_ids = []
    for entity in texts:
        oid = native_identity(entity)["id"]
        row = ledger.get(oid, {})
        geometry = row.get("geometry", {})
        content = entity.dxf.text
        font = ImageFont.truetype(str(font_path), 26 if content == "STORE" else label_font_size, layout_engine=ImageFont.Layout.BASIC)
        if row.get("kind") != "TEXT" or geometry.get("text") != content:
            raise AssertionError("Actual single-line TEXT content/identity differs from its bound candidate")
        recovery = row.get("source_evidence", {}).get("single_line_recovery")
        x, y = _pixel_point(entity.dxf.insert)
        measured = fonts.sideload_ttf(font_path, entity.dxf.height)
        width_px = measured.text_width(content) * entity.dxf.get("width", 1.0) / mm
        expected = (float(geometry["x"]), float(geometry["y"]), float(geometry["height_px"]), float(geometry["width_px"]), -float(geometry.get("rotation_deg_image", 0)))
        actual = (x, y, entity.dxf.height / mm, width_px, float(entity.dxf.get("rotation", 0)))
        if (not all(math.isfinite(value) for value in (*actual, *expected))
                or any(value <= 0 for value in (*actual[2:4], *expected[2:4]))
                or (recovery is None and any(abs(a - b) > 1e-6 for a, b in zip(actual, expected)))):
            raise AssertionError("Actual saved single-line TEXT position/height/width/direction differs from its candidate")
        if (entity.dxf.get("halign", 0) != 0 or entity.dxf.get("valign", 0) != 0
                or entity.dxf.get("text_generation_flag", 0) != 0
                or abs(entity.dxf.get("oblique", 0)) > 1e-8
                or abs(actual[4]) > 1e-8 or abs(expected[4]) > 1e-8
                or tuple(entity.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1)
                or document.styles.get(entity.dxf.style).dxf.font != "DejaVuSans.ttf"):
            raise AssertionError("Single-line TEXT has an unexpected alignment or transform")
        original = Image.new("L", (640, 480), 0)
        ImageDraw.Draw(original).text(positions[content], content, font=font, fill=255)
        source_box = original.getbbox()
        candidate_box = (x, y - actual[2], x + width_px, y)
        if recovery is not None:
            # New labels fit complete portable-font ink, including descenders.
            # Their exact candidate binding is checked by the saved production
            # audit above; this independently measures the actual TEXT outline
            # bounds to catch misplaced/truncated complete-label presentation.
            lower, upper = measured.text_path(content).bbox()
            factor = entity.dxf.get("width", 1.0)
            candidate_box = (x + lower.x * factor / mm, y - upper.y / mm,
                             x + upper.x * factor / mm, y - lower.y / mm)
            bound_box = (expected[0], expected[1] - expected[2], expected[0] + expected[3], expected[1])
            if any(abs(a - b) > 1e-6 for a, b in zip(candidate_box, bound_box)):
                raise AssertionError("Actual complete single-line font ink bounds differ from the bound source geometry")
        edge_error = max(abs(a - b) for a, b in zip(candidate_box, source_box))
        if edge_error > 2.0:
            raise AssertionError("Single-line TEXT layout does not follow the complete source label bounds")
        if recovery is not None:
            check = saved_checks.get(oid, {})
            if (not isinstance(recovery, dict)
                    or recovery.get("schema") != "native-single-line-label-evidence-v1"
                    or check.get("type") != "SINGLE_LINE_TEXT_SOURCE_BINDING"
                    or check.get("pass") is not True):
                raise AssertionError("Recovered single-line TEXT lacks its passing saved source replay")
            recovered_ids.append(oid)
        text_results.append({"id": oid, "text": content, "source_bbox_xyxy_px": list(source_box), "saved_layout_bbox_xyxy_px": list(candidate_box), "maximum_layout_edge_error_px": edge_error, "actual_saved_candidate_binding": True, "new_source_recovery_replayed": recovery is not None})
    target_ids = {row["id"] for row in text_results if row["text"] != "STORE"}
    if not target_ids.intersection(recovered_ids):
        raise AssertionError("Single-line fixture did not exercise the new recovery capability")
    if set(saved_checks) != set(recovered_ids):
        raise AssertionError("Single-line source check inventory differs from the recovered actual TEXT objects")
    line_results = []
    used = set()
    for start, end in neighbor_fixture:
        candidates = []
        for entity in paths:
            points = _line_points(entity)
            if not points:
                continue
            a, b = points[0], points[-1]
            forward = math.dist(a, start) <= 2.5 and math.dist(b, end) <= 2.5
            reverse = math.dist(b, start) <= 2.5 and math.dist(a, end) <= 2.5
            if forward or reverse:
                candidates.append((entity, points))
        if len(candidates) != 1:
            raise AssertionError("Independent neighbor line/short stroke has no unique saved whole object")
        entity, points = candidates[0]
        oid = native_identity(entity)["id"]
        if oid in used or ledger.get(oid, {}).get("kind") not in ("LINE", "LWPOLYLINE"):
            raise AssertionError("Independent neighbor line identity or ownership changed")
        used.add(oid)
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if any(abs((point[0] - start[0]) * dy - (point[1] - start[1]) * dx) / length > 2.5 for point in points):
            raise AssertionError("Independent neighbor line contains a text-glyph branch")
        support = _saved_line_source_check(cold, oid)
        line_results.append({"id": oid, "source_start_px": list(start), "source_end_px": list(end), "saved_points_px": points, "saved_source_check": support})
    return {
        "complete_label_count": len(required_labels),
        "complete_label_strings": [item[0] for item in required_labels],
        "ordinary_text_control": "STORE",
        "ordinary_text_control_preserved": True,
        "all_labels_are_single_top_level_TEXT": True,
        "all_actual_TEXT_content_and_layout_bound_to_candidates": True,
        "normal_font_shape_difference_not_pixel_equality": True,
        "TEXT_checks": text_results,
        "new_recovery_label_ids": sorted(target_ids.intersection(recovered_ids)),
        "new_recovery_TEXT_ids": sorted(recovered_ids),
        "all_new_recovery_TEXT_saved_source_replay_passed": True,
        "independent_neighbor_line_checks": line_results,
        "independent_short_stroke_preserved": True,
        "fixture_expectations_sent_to_recognizer": False,
    }


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _distance_to_path(point, points):
    distances = []
    for start, end in zip(points, points[1:]):
        delta = (end[0] - start[0], end[1] - start[1])
        length2 = sum(value * value for value in delta)
        parameter = sum((point[i] - start[i]) * delta[i] for i in (0, 1)) / length2 if length2 else 0
        parameter = max(0.0, min(1.0, parameter))
        distances.append(math.dist(point, [start[i] + parameter * delta[i] for i in (0, 1)]))
    return min(distances, default=math.inf)


def inspect_contact_members(document, objects: dict, cold: dict, font_path: Path) -> dict:
    """Require a saved complete TEXT and a separate whole original-contact path.

    An empty contact audit or an unrelated ordinary LINE cannot satisfy this
    capability gate. All formal entities are accounted for, so text fragments,
    duplicate curves, missing underlines and short strokes fail the check.
    """
    result = _inspect_single_line_members_for_labels(
        document, objects, cold, font_path, CONTACT_LABEL_FIXTURE,
        fixture_labels=CONTACT_LABEL_FIXTURE, neighbor_fixture=CONTACT_NEIGHBOR_FIXTURE,
        label_font_size=32, additional_path_count=1,
    )
    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    identities = [native_identity(entity) for entity in entities]
    ledger = {row["id"]: row for row in objects["objects"]}
    if len(identities) != len({row["id"] for row in identities}) or set(ledger) != {row["id"] for row in identities}:
        raise AssertionError("Contact fixture has missing, duplicate, or unwritten formal identities")
    target = next(entity for entity in entities if entity.dxftype() == "TEXT" and entity.dxf.text == CONTACT_LABEL_FIXTURE[0][0])
    text_id = native_identity(target)["id"]
    recovery = ledger[text_id].get("source_evidence", {}).get("single_line_recovery", {})
    separation = recovery.get("source_partition", {}).get("text_contact_separation", {})
    plan = separation.get("geometry_plan", {})
    if (separation.get("schema") != "complete-original-contact-row-separation-v1"
            or separation.get("source_erasure_authorized") is not False
            or separation.get("source_pixels_added") != 0
            or separation.get("real_source_white_gaps_filled") is not False
            or separation.get("independent_graphics_require_separate_adoption") is not True
            or not separation.get("shared_original_contact_runs")
            or not separation.get("recognition_excluded_source_runs")
            or plan.get("original_source_pixels_modified") is not False
            or plan.get("transcription_supplied") is not False
            or len(plan.get("paths", [])) != 1):
        raise AssertionError("Whole TEXT did not exercise original-source contact separation")
    contact_entities = [entity for entity in entities if native_identity(entity).get("text_contact_path") is True]
    if len(contact_entities) != 1:
        raise AssertionError("Contact fixture lacks one actual independently flagged complete path")
    path_entity = contact_entities[0]
    path_id = native_identity(path_entity)["id"]
    path_row = ledger[path_id]
    proof = path_row.get("source_evidence", {}).get("text_contact_path", {})
    selected = plan["paths"][0]
    if (path_row.get("kind") != "CONNECTION_PATH"
            or proof.get("schema") != "source-text-contact-native-path-v1"
            or proof.get("source_sha256") != objects.get("source_sha256")
            or proof.get("plan_sha256") != _json_digest(plan)
            or proof.get("path_index") != 0 or proof.get("path") != selected
            or proof.get("path_sha256") != _json_digest(selected)
            or not selected.get("contact_continuations")
            or not selected.get("shared_contact_runs")
            or selected.get("line_and_text_may_share_source_pixels") is not True):
        raise AssertionError("Saved independent path is not bound to the TEXT's actual original-source plan")
    points = _line_points(path_entity)
    expected = _contact_curve_points()
    if not points or len(points) < 3:
        raise AssertionError("Contact curve is not a whole editable native polyline")
    endpoint_error = min(max(math.dist(points[0], expected[0]), math.dist(points[-1], expected[-1])),
                         max(math.dist(points[0], expected[-1]), math.dist(points[-1], expected[0])))
    curve_error = max(max(_distance_to_path(point, expected) for point in points),
                      max(_distance_to_path(point, points) for point in expected))
    if endpoint_error > 2.5 or curve_error > 2.5:
        raise AssertionError("Saved contact curve lost a real endpoint, includes a glyph branch, or does not follow the whole source")
    geometry = path_row.get("geometry", {})
    if (geometry != selected.get("representation")
            or len(geometry.get("points", [])) != len(points)
            or any(math.dist(a, b) > 1e-6 for a, b in zip(geometry["points"], points))
            or geometry.get("closed") is not False
            or geometry.get("bulges") != [0.0] * len(points)):
        raise AssertionError("Actual contact curve differs from its source-bound saved candidate")
    contact_cold = cold.get("text_contact_source_checks", {})
    checks = contact_cold.get("checks", [])
    by_id = {row.get("id"): row for row in checks}
    required_types = {
        "TEXT_CONTACT_MANIFEST": "TEXT_CONTACT_MANIFEST_BINDING",
        path_id: "SAVED_TEXT_CONTACT_PATH_SOURCE",
        "TEXT_CONTACT_RETIREMENT": "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT",
        "TEXT_CONTACT_NEIGHBORS": "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION",
        "TEXT_CONTACT_DUPLICATES": "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES",
    }
    if (contact_cold.get("schema") != "saved-text-contact-source-audit-v1"
            or contact_cold.get("pass") is not True
            or contact_cold.get("target_ids") != [path_id]
            or contact_cold.get("duplicate_conflicts") != []
            or contact_cold.get("source_or_DXF_geometry_modified") is not False
            or len(by_id) != len(checks) or set(by_id) != set(required_types)
            or any(by_id[key].get("type") != kind or by_id[key].get("pass") is not True for key, kind in required_types.items())):
        raise AssertionError("Actual contact saved-source checker was empty, incomplete, or failed")
    for key in ("TEXT_CONTACT_MANIFEST", path_id, "TEXT_CONTACT_RETIREMENT"):
        if not by_id[key].get("checks") or any(value is not True for value in by_id[key]["checks"].values()):
            raise AssertionError("Actual contact binding/geometry/retirement checks did not all pass")
    path_check = by_id[path_id]
    if any(path_check["checks"].get(key) is not True for key in (
        "three_way_object_binding", "actual_identity_and_flag", "actual_vertices",
        "original_source_plan_replayed", "original_source_geometry_supported",
        "whole_native_representation_from_source_plan",
    )):
        raise AssertionError("Saved path audit omitted an actual source/geometry binding")
    for key in ("original_source_plan_replay", "actual_source_geometry"):
        value = path_check.get(key, {})
        if value.get("pass") is not True or not value.get("checks") or any(v is not True for v in value["checks"].values()):
            raise AssertionError("Actual saved contact source geometry was not independently replayed")
    neighbor_check = by_id["TEXT_CONTACT_NEIGHBORS"]
    protected = neighbor_check.get("objects", [])
    if (neighbor_check.get("protected_count") != len(entities) - 1
            or {row.get("id") for row in protected} != set(ledger) - {path_id}
            or len(protected) != len(entities) - 1
            or any(row.get("pass") is not True or not row.get("checks") or any(v is not True for v in row["checks"].values()) for row in protected)
            or by_id["TEXT_CONTACT_DUPLICATES"].get("conflicts") != []):
        raise AssertionError("Saved contact completion did not protect every other actual object")
    covered = {row["id"] for row in result["independent_neighbor_line_checks"]} | {path_id, text_id}
    covered |= {native_identity(entity)["id"] for entity in entities if entity.dxftype() == "TEXT"}
    if covered != set(ledger):
        raise AssertionError("Saved contact fixture contains an unaccounted fragment or duplicate")
    result.update(
        schema="windows-saved-text-contact-check-v1", complete_location_count=1,
        new_complete_TEXT_count=1, new_complete_independent_path_count=1,
        text_id=text_id, independent_contact_path_id=path_id,
        contact_path_source_audit=path_check, contact_path_saved_points_px=points,
        maximum_contact_curve_error_px=curve_error,
        maximum_contact_endpoint_error_px=endpoint_error,
        new_contact_separation_required=True, empty_contact_audit_can_pass=False,
        original_contact_shared_evidence_preserved=True,
        no_text_only_glyph_fragments_or_duplicate_lines=True,
        graphic_inside_original_text_rectangle_is_allowed=True,
    )
    return result


def inspect_contact_payloads(objects, cold, evidence_root, source_path, font_path, pipeline_report):
    """Reopen actual source and adoption records, in addition to raw OCR proof."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    glyph_mask = Image.new("L", (640, 480), 0)
    glyph_draw = ImageDraw.Draw(glyph_mask)
    font = ImageFont.truetype(str(font_path), 32, layout_engine=ImageFont.Layout.BASIC)
    for text, point in CONTACT_LABEL_FIXTURE:
        glyph_draw.text(point, text, font=font, fill=255)
    curve_mask = Image.new("L", (640, 480), 0)
    ImageDraw.Draw(curve_mask).line(_contact_curve_points(), fill=255, width=3)
    overlap = (np.asarray(glyph_mask) >= 64) & (np.asarray(curve_mask) > 0)
    if source.shape != (480, 640) or not overlap.any() or not np.all(source[overlap] < 192):
        raise AssertionError("Original controlled input has no actual shared glyph/curve ink")
    target = next(row for row in objects["objects"] if row.get("source_evidence", {}).get("text_contact_path"))
    proof = target["source_evidence"]["text_contact_path"]
    manifest_path = evidence_root / "text_contact/adoption.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != "source-text-contact-adoption-v1"
            or manifest.get("source_sha256") != digest(source_path)
            or manifest.get("source_pixels_modified") is not False
            or manifest.get("partial_old_entity_retirement_permitted") is not False
            or manifest.get("objects") != [target]
            or manifest.get("geometry_plans", {}).get(proof["plan_sha256"]) is None
            or _json_digest(manifest["geometry_plans"][proof["plan_sha256"]]) != proof["plan_sha256"]):
        raise AssertionError("Saved contact manifest does not bind actual source, path, and original geometry plan")
    report = pipeline_report.get("text_contact_completion", {})
    adopted = [row.get("id") for row in report.get("decisions", []) if row.get("adopted") is True]
    if (report.get("new_complete_graphics") != 1 or adopted != [target["id"]]
            or report.get("actual_saved_source_checks") != cold.get("text_contact_source_checks")
            or report.get("text_and_graphic_objects_counted_separately") is not True):
        raise AssertionError("Ordinary pipeline did not publish the checked contact completion")
    raw = inspect_single_line_character_payloads(objects, cold, evidence_root, pipeline_report)
    if raw.get("accepted_label_new_model_calls", 0) <= 0 or raw.get("accepted_label_new_Tesseract_calls", 0) <= 0:
        raise AssertionError("Contact fixture did not actually recognize its new whole label")
    return {"source_sha256": digest(source_path), "original_shared_ink_pixels": int(overlap.sum()),
            "adoption_manifest_sha256": digest(manifest_path), "actual_label_payloads": raw,
            "fixture_expectations_sent_to_recognizer": False, "inspection_executed_recognition": False}


def _passing_checks(value, description):
    checks = value.get("checks", {})
    if value.get("pass") is not True or not isinstance(checks, dict) or not checks or any(v is not True for v in checks.values()):
        raise AssertionError(description)


def _closed_source_segment_cells(start, end):
    """Enumerate closed source pixel cells touched by a finite terminal segment."""
    cells = []
    delta = [end[axis] - start[axis] for axis in (0, 1)]
    low = [math.ceil(min(start[axis], end[axis]) - 0.5) for axis in (0, 1)]
    high = [math.floor(max(start[axis], end[axis]) + 0.5) for axis in (0, 1)]
    for y in range(low[1], high[1] + 1):
        for x in range(low[0], high[0] + 1):
            enter, leave = 0.0, 1.0
            for axis, coordinate in enumerate((x, y)):
                if abs(delta[axis]) <= 1e-14:
                    if not coordinate - 0.5 <= start[axis] <= coordinate + 0.5:
                        leave = -1.0
                        break
                else:
                    first, last = sorted(((coordinate - 0.5 - start[axis]) / delta[axis],
                                          (coordinate + 0.5 - start[axis]) / delta[axis]))
                    enter, leave = max(enter, first), min(leave, last)
            if enter <= leave + 1e-12:
                cells.append([x, y])
    return cells


def _inspect_observed_terminal_core(gray, endpoint, center, radius, width, end, original_evidence):
    """Replay bounded source-core geometry independently of application imports.

    The actual saved-source audit additionally rebuilds the original graph.
    Here its saved plan, every source pixel, both opposite ring prefixes and
    both finite core routes must account for the new direction and bound.
    """
    import numpy as np

    shape = "REPLAYED_ORIGINAL_TERMINAL_CORE_TO_OPPOSITE_RING_BRANCHES"
    path = original_evidence["text_contact_path"]["path"]
    core = path["endpoint_source_cores"][end["endpoint_number"]]
    if (end.get("endpoint_extension_shape") != shape
            or end.get("terminal_core_source_evidence") != core
            or end.get("raw_source_graph_rebuilt") is not True
            or end.get("unselected_external_branches_retained") is not True
            or core.get("schema") != "observed-round-terminal-source-core-v1"
            or core.get("source_pixels_modified") is not False
            or core.get("semantic_connection_inferred") is not False
            or core.get("original_branches_retained") is not True
            or end.get("terminal_core_source_crop_sha256") != original_evidence.get("original_source_crop_array_sha256")):
        raise AssertionError("Observed terminal core differs from the original whole-path source plan")
    points = core["source_core_points_px"]
    if (not 1 <= len(points) <= 48 or len({tuple(p) for p in points}) != len(points)
            or any(len(p) != 2 or any(type(v) is not int for v in p) for p in points)
            or np.max(np.ptp(np.asarray(points), axis=0)) > 16
            or list(endpoint) not in points):
        raise AssertionError("Terminal core is not the original bounded integer source junction")
    prefixes = core["all_adjacent_source_prefixes"]
    ports = [row["source_graph_port"] for row in prefixes]
    incoming = core["incoming_source_graph_port"]
    if len({tuple(p) for p in ports}) != len(ports) or incoming not in ports:
        raise AssertionError("Terminal core repeats or omits an original graph port")
    all_pixels = points + [p for row in prefixes for p in row["original_source_prefix_px"]]
    if any(not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0] and gray[y, x] < 128) for x, y in all_pixels):
        raise AssertionError("Terminal core or an observed adjacent prefix differs from original black source pixels")
    allowance = width / 2 + 0.85
    ring = []
    for row in prefixes:
        if row["source_graph_port"] == incoming:
            continue
        prefix = row["original_source_prefix_px"]
        if len(prefix) < 3:
            continue
        radial = [prefix[0][axis] - center[axis] for axis in (0, 1)]
        delta = [prefix[-1][axis] - prefix[0][axis] for axis in (0, 1)]
        denominator = math.hypot(*radial) * math.hypot(*delta)
        sine = (radial[0] * delta[1] - radial[1] * delta[0]) / denominator if denominator else 0
        span = sum(math.dist(a, b) for a, b in zip(prefix, prefix[1:]))
        if (span >= min(radius / 2, width * 2)
                and max(abs(math.dist(p, center) - radius) for p in prefix) <= allowance
                and abs(sine) >= 0.5):
            ring.append((row, sine))
    if len(ring) != 2 or ring[0][1] * ring[1][1] >= 0:
        raise AssertionError("Terminal core lacks one unique opposite pair of original circle branches")
    anchors = [row["original_source_prefix_px"][0] for row, _ in ring]
    anchor = [(anchors[0][axis] + anchors[1][axis]) / 2 for axis in (0, 1)]
    if (math.dist(*anchors) > width + 1.7
            or end.get("ring_source_graph_ports") != [row["source_graph_port"] for row, _ in ring]
            or end.get("ring_branch_core_anchors_px") != anchors
            or end.get("original_core_connector_anchor_px") != anchor):
        raise AssertionError("Terminal direction is not bound to its two source ring-branch endpoints")
    routes = end.get("original_core_routes_to_ring_branches_px", [])
    if len(routes) != 2:
        raise AssertionError("Observed terminal core lacks both finite original routes")
    for route, finish in zip(routes, anchors):
        if (not route or route[0] != list(endpoint) or route[-1] != finish
                or any(p not in points for p in route)
                or any(not 0 < math.dist(a, b) <= math.sqrt(2) for a, b in zip(route, route[1:]))):
            raise AssertionError("Terminal route leaves the original observed core")
    magnitude = math.dist(anchor, endpoint)
    if magnitude <= 1e-6:
        raise AssertionError("Observed terminal core has no missing arrival span")
    direction = [(anchor[axis] - endpoint[axis]) / magnitude for axis in (0, 1)]
    bound = math.hypot(*(max(p[axis] for p in points) - min(p[axis] for p in points) for axis in (0, 1))) + allowance
    if not _near_point(end.get("core_completion_direction", (math.inf, math.inf)), direction, 1e-7):
        raise AssertionError("Terminal core direction differs from the original source anchors")
    return direction, bound, points, allowance


def inspect_contact_path_vertices(document, objects, cold, entity, path_row, planned, source_path=None):
    """Replay short straight end proofs while retaining the entire old path.

    This standalone checker imports no hidden application code. Its original
    1e-6 CAD precision is unchanged; other geometry mismatches still fail.
    """
    from copy import deepcopy

    actual_points = _line_points(entity)
    original_points = planned.get("points", [])
    if (path_row.get("kind") != "CONNECTION_PATH" or entity.dxftype() != "LWPOLYLINE"
            or planned.get("closed") is not False or len(original_points) < 2
            or planned.get("bulges") != [0.0] * len(original_points)
            or not actual_points or any(not all(math.isfinite(v) for v in point) for point in original_points + actual_points)):
        raise AssertionError("Saved whole contact lead has no finite open source-plan representation")
    evidence = path_row.get("source_evidence", {})
    certificate = evidence.get("circle_endpoint_contacts")
    expected = deepcopy(planned)
    identity = native_identity(entity)
    reports = []
    if certificate is not None:
        import numpy as np
        from PIL import Image

        policy = {
            "version": "native-direct-circle-end-contact-v2-observed-terminal-core", "source_threshold": 128,
            "maximum_extension_stroke_widths": 1.0, "existing_native_fit_allowance_px": 0.85,
            "absolute_extension_limit_px": 6.0, "candidate_search_stroke_widths": 2.0,
            "existing_terminal_witness_length_px": 3.0, "endpoint_precision_px": 1e-6,
            "core_ring_prefix_minimum_span_stroke_widths": 2.0,
            "core_ring_prefix_minimum_tangential_sine": 0.5,
            "core_completion": "REPLAY_ORIGINAL_TERMINAL_CORE_AND_TWO_OPPOSITE_RING_BRANCHES",
            "source_contact_test": "EVERY_CLOSED_PIXEL_CELL_INTERSECTED_BY_THE_STRAIGHT_EXTENSION_IS_ORIGINAL_INK",
            "source_morphology": "NONE", "existing_interior_overlap": "RETAIN_UNCHANGED",
            "external_connection_owned_by_marker": False,
        }
        original_evidence = {key: value for key, value in evidence.items() if key != "circle_endpoint_contacts"}
        if (not isinstance(certificate, dict) or certificate.get("schema") != policy["version"]
                or certificate.get("policy") != policy or identity.get("circle_endpoint_contacts") is not True
                or certificate.get("original_geometry") != planned
                or certificate.get("original_geometry_sha256") != _json_digest(planned)
                or certificate.get("original_source_evidence_sha256") != _json_digest(original_evidence)
                or certificate.get("original_source_path_points_sha256") != _json_digest(original_evidence.get("source_path_points"))
                or certificate.get("same_independent_object_id_retained") is not True
                or certificate.get("polyline_old_vertices_and_bulges_retained") is not True
                or certificate.get("existing_geometry_removed") is not False
                or certificate.get("original_source_records_modified") is not False):
            raise AssertionError("Contact endpoint certificate changed its policy or original geometry/source records")
        if source_path is None or digest(Path(source_path)) != objects.get("source_sha256"):
            raise AssertionError("Contact endpoint replay requires the exact original source PNG")
        with Image.open(source_path) as image:
            gray = np.asarray(image.convert("L"))

        def crop_digest(box):
            if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
                    or not (0 <= box[0] < box[2] <= gray.shape[1] and 0 <= box[1] < box[3] <= gray.shape[0])):
                raise AssertionError("Contact endpoint crop is outside the original source")
            return hashlib.sha256(np.ascontiguousarray(gray[box[1]:box[3], box[0]:box[2]]).tobytes()).hexdigest()

        ends = certificate.get("ends", [])
        if (not 1 <= len(ends) <= 2 or any(row.get("endpoint_number") not in (0, 1) for row in ends)
                or len({row["endpoint_number"] for row in ends}) != len(ends)):
            raise AssertionError("Contact endpoint proof has an invalid or repeated terminal")
        ledger = {row["id"]: row for row in objects["objects"]}
        saved = {native_identity(value)["id"]: value for value in document.modelspace() if value.dxf.layer != "REVIEW"}
        checks = [row for row in cold.get("circle_endpoint_contact_checks", []) if row.get("id") == path_row["id"]]
        if (len(checks) != 1 or checks[0].get("type") != "CIRCLE_ENDPOINT_CONTACT"
                or checks[0].get("restored_endpoints") != len(ends)
                or any(checks[0].get(key) is not True for key in ("pass", "actual_saved_geometry_checked", "original_source_records_preserved", "external_entity_is_independent"))):
            raise AssertionError("Contact endpoint lacks its actual independent saved-source cold check")
        for end in sorted(ends, key=lambda row: row["endpoint_number"]):
            number = end["endpoint_number"]
            points = original_points if number == 0 else list(reversed(original_points))
            endpoint, neighbor = points[:2]
            span = math.dist(endpoint, neighbor)
            if span <= 0:
                raise AssertionError("Contact endpoint has no original outward direction")
            direction = [(endpoint[axis] - neighbor[axis]) / span for axis in (0, 1)]
            marker = ledger.get(end.get("circle_id"), {})
            saved_marker = saved.get(end.get("circle_id"))
            if marker.get("kind") not in ("CIRCLE", "CIRCULAR_MARKER") or saved_marker is None:
                raise AssertionError("Contact endpoint is not bound to a separately saved circle")
            geometry = marker["geometry"] if marker["kind"] == "CIRCLE" else marker["geometry"]["circle_geometry"]
            members = [saved_marker] if saved_marker.dxftype() == "CIRCLE" else list(saved_marker.virtual_entities())
            circles = [member for member in members if member.dxftype() == "CIRCLE"]
            if len(circles) != 1:
                raise AssertionError("Contact endpoint target lost its actual single CIRCLE")
            center, radius = geometry["center"], float(geometry["radius_px"])
            source = marker["source_evidence"]
            if (not _near_point(_pixel_point(circles[0].dxf.center), center, 1e-6)
                    or abs(float(circles[0].dxf.radius) * 200 / 25.4 - radius) > 1e-6
                    or end.get("circle_geometry") != geometry
                    or end.get("circle_source_crop_sha256") != source.get("crop_sha256")
                    or crop_digest(source.get("crop_bbox_xyxy_px")) != source.get("crop_sha256")):
                raise AssertionError("Contact endpoint target differs from its actual circle or original source crop")
            width = float(source["ring_geometry"]["stroke_width_px"])
            bound = min(6.0, width + 0.85)
            actual_direction = direction
            shape = end.get("endpoint_extension_shape")
            core_limits = None
            if shape == "REPLAYED_ORIGINAL_TERMINAL_CORE_TO_OPPOSITE_RING_BRANCHES":
                if math.dist(endpoint, center) - radius <= bound:
                    raise AssertionError("Observed core route must not bypass the unchanged ordinary short-tail gate")
                actual_direction, bound, core_points, allowance = _inspect_observed_terminal_core(
                    gray, endpoint, center, radius, width, end, original_evidence
                )
                core_limits = (core_points, allowance)
            elif shape is not None:
                raise AssertionError("This generated whole-path case contains an unexamined endpoint extension shape")
            radial = [endpoint[axis] - center[axis] for axis in (0, 1)]
            projection = sum(a * b for a, b in zip(radial, actual_direction))
            discriminant = projection ** 2 - (sum(value * value for value in radial) - radius ** 2)
            if projection >= 0 or discriminant <= 0:
                raise AssertionError("Contact endpoint straight terminal does not enter the actual circle")
            length = -projection - math.sqrt(discriminant)
            target = [endpoint[axis] + length * actual_direction[axis] for axis in (0, 1)]
            if core_limits is not None:
                core_points, allowance = core_limits
                if any(not min(p[axis] for p in core_points) - allowance <= target[axis]
                       <= max(p[axis] for p in core_points) + allowance for axis in (0, 1)):
                    raise AssertionError("Restored core endpoint leaves its bounded original source junction")
            if (not 0 < length <= bound or math.dist(endpoint, center) - radius <= 1e-6
                    or end.get("object_id") != path_row["id"] or end.get("accepted") is not True
                    or end.get("reason") != "DIRECT_ORIGINAL_INK_CONTACT_TO_MEASURED_CIRCLE"
                    or not _near_point(end.get("original_endpoint_px", (math.inf, math.inf)), endpoint, 1e-7)
                    or not _near_point(end.get("endpoint_direction", (math.inf, math.inf)), direction, 1e-7)
                    or not _near_point(end.get("restored_endpoint_px", (math.inf, math.inf)), target, 1e-7)
                    or abs(end.get("extension_length_px", math.inf) - length) > 1e-7
                    or abs(end.get("maximum_extension_px", math.inf) - bound) > 1e-7
                    or abs(end.get("original_radial_gap_px", math.inf) - (math.dist(endpoint, center) - radius)) > 1e-7
                    or any(end.get(key) is not False for key in ("source_pixels_modified", "source_path_points_modified", "external_connection_in_marker_block"))
                    or end.get("every_intersected_source_pixel_is_black") is not True):
                raise AssertionError("Contact endpoint's short measured-circle extension does not replay")
            direct = _closed_source_segment_cells(endpoint, end["restored_endpoint_px"])
            witness, remaining = set(), 3.0
            for start, finish in zip(points, points[1:]):
                distance = math.dist(start, finish)
                if distance == 0:
                    continue
                stop = [start[axis] + (finish[axis] - start[axis]) * min(1.0, remaining / distance) for axis in (0, 1)]
                witness.update(map(tuple, _closed_source_segment_cells(start, stop)))
                remaining -= min(remaining, distance)
                if remaining <= 0:
                    break
            witness = [list(point) for point in sorted(witness, key=lambda point: (point[1], point[0]))]
            cells = direct + witness
            if (not direct or not witness or end.get("direct_segment_cells_xy") != direct
                    or end.get("existing_terminal_witness_cells_xy") != witness
                    or any(not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0] and gray[y, x] < 128) for x, y in cells)):
                raise AssertionError("Contact endpoint crosses an original white cell or changed its finite pixel proof")
            box = [min(point[0] for point in cells), min(point[1] for point in cells),
                   max(point[0] for point in cells) + 1, max(point[1] for point in cells) + 1]
            if end.get("source_crop_xyxy_px") != box or end.get("source_crop_sha256") != crop_digest(box):
                raise AssertionError("Contact endpoint source pixels do not match their bound original crop")
            dense = []
            for start, finish in zip(points, points[1:]):
                dense.extend(np.linspace(start, finish, max(2, math.ceil(math.dist(start, finish) / 0.25) + 1))[:-1].tolist())
            dense.append(points[-1])
            dense = np.asarray(dense)
            travelled = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
            pixels = np.unique(np.rint(dense[travelled <= max(3.0, 2 * width + 2)]).astype(int), axis=0)
            ports = [index for index, port in enumerate(source["contact_ports"])
                     if sum(any(y == row and left <= x < right for row, left, right in port["source_runs_y_x0_x1"]) for x, y in pixels) >= 2]
            if ports != [end.get("observed_port_index")]:
                raise AssertionError("Contact endpoint does not replay exactly one originally observed circle port")
            if number == 0:
                expected["points"].insert(0, end["restored_endpoint_px"])
                expected["bulges"].insert(0, 0.0)
            else:
                expected["points"].append(end["restored_endpoint_px"])
                expected["bulges"].append(0.0)
            saved_end = actual_points[0 if number == 0 else -1]
            if abs(math.dist(saved_end, _pixel_point(circles[0].dxf.center)) - float(circles[0].dxf.radius) * 200 / 25.4) > 1e-6:
                raise AssertionError("Actual saved contact endpoint does not touch its actual independent CIRCLE")
            reports.append({"endpoint_number": number, "circle_id": end["circle_id"],
                            "extension_length_px": length, "original_black_cells_replayed": len(set(map(tuple, cells))),
                            "actual_saved_circle_contact_checked": True})
        if certificate.get("restored_geometry_sha256") != _json_digest(expected):
            raise AssertionError("Contact endpoint certificate changed the restored whole-path geometry")
    elif identity.get("circle_endpoint_contacts"):
        raise AssertionError("Actual contact endpoint flag has no replayable certificate")
    if (path_row.get("geometry") != expected or len(expected["points"]) != len(actual_points)
            or any(math.dist(a, b) > 1e-6 for a, b in zip(expected["points"], actual_points))):
        raise AssertionError("Saved whole short-code lead differs from its source-bound actual vertices")
    return {"original_vertices_continuously_preserved": len(original_points),
            "original_bulges_unchanged": True, "added_terminal_segments": len(reports),
            "endpoint_certificate_replayed": bool(reports), "source_pixels_modified": False,
            "saved_vertex_tolerance_px": 1e-6, "terminal_checks": reports}


def inspect_short_code_members(document, objects, cold, font_spec, companion: Path, *, source_path=None) -> dict:
    """Require a complete saved code and actual source-constrained font layout.

    This is a post-save checker, not an adoption path. A candidate, a bundled
    font, an empty ring audit, or a passing old whole-ink fit cannot satisfy it.
    Every formal object is accounted for; original line contact is permitted.
    """
    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    texts = [entity for entity in entities if entity.dxftype() == "TEXT"]
    circles = [entity for entity in entities if entity.dxftype() == "CIRCLE"]
    paths = [entity for entity in entities if entity.dxftype() in ("LINE", "LWPOLYLINE")]
    expected_text = SHORT_CODE_LABEL_FIXTURE[0][0]
    if (len(entities) != 6 or len(paths) != 3 or len(circles) != 1
            or Counter(entity.dxf.text for entity in texts) != Counter([expected_text, "STORE"])):
        raise AssertionError("Short-code input did not save one complete TEXT, control, circle, and three whole independent lines")
    rows = objects.get("objects", [])
    ledger = {row["id"]: row for row in rows}
    actual_ids = [native_identity(entity)["id"] for entity in entities]
    if len(ledger) != len(rows) or len(set(actual_ids)) != len(actual_ids) or set(ledger) != set(actual_ids):
        raise AssertionError("Short-code input has a duplicate, unwritten object, or glyph fragment")
    target = next(entity for entity in texts if entity.dxf.text == expected_text)
    text_id = native_identity(target)["id"]
    target_row = ledger[text_id]
    recovery = target_row.get("source_evidence", {}).get("single_line_recovery", {})
    partition = recovery.get("source_partition", {})
    adoption = recovery.get("layout_adoption", {})
    selected = adoption.get("selected_layout", {})
    default = adoption.get("default_layout_rejection", {})
    if (target_row.get("kind") != "TEXT" or target_row.get("geometry", {}).get("text") != expected_text
            or recovery.get("schema") != "native-single-line-label-evidence-v1"
            or recovery.get("decision", {}).get("accepted") is not True
            or recovery["decision"].get("text") != expected_text
            or len(partition.get("components", [])) != len(expected_text)
            or adoption.get("pass") is not True
            or adoption.get("font") != font_spec
            or adoption.get("layout_selection") != "one_pinned_source_component_fit_after_default_white_gap_failure"
            or selected.get("basis") != "proved-source-components-one-TEXT-affine-v1"
            or selected.get("font_sha256") != font_spec["sha256"]
            or selected.get("font_is_recognition_evidence") is not False
            or selected.get("scan_pixel_equality_required") is not False
            or default.get("pass") is not False
            or default.get("reason") != "NATIVE_TEXT_CLOSES_PROVED_SOURCE_ROUND_WHITE_GAP"
            or not any(row.get("original_white_gap_proved") is True and row.get("pass") is False for row in default.get("relations", []))):
        raise AssertionError("Complete short code did not actually replace a rejected default with the source-component layout")
    exported_fonts = [row for row in objects.get("fonts", []) if row.get("font") == font_spec["font"]]
    if len(exported_fonts) != 1 or any(exported_fonts[0].get(key) != value for key, value in font_spec.items()):
        raise AssertionError("Saved short code did not export the uniquely pinned source-row font and full license")
    for name, checksum, size in ((font_spec["font"], font_spec["sha256"], font_spec["bytes"]),
                                 (font_spec["bundled_license"], font_spec["license_sha256"], font_spec["license_bytes"]),
                                 (font_spec["librecad_font"], font_spec["librecad_sha256"], font_spec["librecad_bytes"])):
        path = companion / name
        if path.name != name or not path.is_file() or path.stat().st_size != size or digest(path) != checksum:
            raise AssertionError("Saved short-code font/license bytes differ from the packaged registry")
    if (target.dxf.style != font_spec["style"]
            or document.styles.get(target.dxf.style).dxf.font != font_spec["font"]):
        raise AssertionError("Actual saved short code did not use its selected portable font style")
    attributes = {"text": target.dxf.text, "insert": [float(v) for v in target.dxf.insert],
                  "height": float(target.dxf.height), "width": float(target.dxf.get("width", 1.0)),
                  "rotation": float(target.dxf.get("rotation", 0.0))}
    for key in ("insert", "height", "width", "rotation"):
        actual, expected = attributes[key], selected.get(key)
        if canonical_value(actual) != canonical_value(expected):
            raise AssertionError("Saved complete short-code transform differs from its selected source layout")
    if (any(target.dxf.get(key, 0) != 0 for key in ("halign", "valign", "oblique", "text_generation_flag"))
            or tuple(target.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1)
            or min(attributes["height"], attributes["width"]) <= 0
            or any(not math.isfinite(v) for v in (*attributes["insert"], attributes["height"], attributes["width"], attributes["rotation"]))):
        raise AssertionError("Saved short code has an unsupported or invalid TEXT transform")
    candidates = cold.get("native_text_candidate_checks", [])
    if ({row.get("id") for row in candidates} != {native_identity(entity)["id"] for entity in texts}
            or len(candidates) != len(texts)
            or any(row.get("type") != "NATIVE_TEXT_CANDIDATE_BINDING" or row.get("pass") is not True for row in candidates)):
        raise AssertionError("Saved short-code/control candidate checks are incomplete")
    checked = [row for row in cold.get("single_line_text_source_checks", []) if row.get("id") == text_id]
    if len(checked) != 1 or checked[0].get("type") != "SINGLE_LINE_TEXT_SOURCE_BINDING" or checked[0].get("pass") is not True:
        raise AssertionError("Saved complete short code lacks actual source replay")
    source_check = checked[0]
    replay = source_check.get("source_replay", {})
    if (replay.get("pass") is not True or replay.get("text") != expected_text
            or replay.get("new_OCR_calls") != 0 or replay.get("new_model_calls") != 0
            or replay.get("layout_adoption") != adoption
            or replay.get("all_raw_artifacts_read_and_hashed") is not True):
        raise AssertionError("Short-code source replay did not recompute the actual complete adoption without OCR")
    component = source_check.get("actual_saved_source_component_layout", {})
    if (component.get("pass") is not True or component.get("actual_attributes_used") is not True
            or component.get("font_sha256") != font_spec["sha256"]
            or component.get("source_partition_sha256") != _json_digest(partition)):
        raise AssertionError("Saved source-component layout checker was not actually executed")
    companion_check = component.get("actual_saved_LFF_literal_equivalence", {})
    if (companion_check.get("pass") is not True
            or companion_check.get("font_sha256") != font_spec["sha256"]
            or companion_check.get("librecad_sha256") != font_spec["librecad_sha256"]
            or companion_check.get("actual_LFF_file_read") is not True
            or companion_check.get("all_literal_outlines_and_advances_checked") is not True
            or companion_check.get("unverified_glyphs_are_not_exempted") is not True
            or not 0 < companion_check.get("serialization_tolerance_unit_capheight", 0) <= 1e-9
            or any(not 0 <= companion_check.get(key, math.inf) <= companion_check["serialization_tolerance_unit_capheight"] for key in (
                "maximum_outline_difference_unit_capheight", "maximum_accumulated_advance_difference_unit_capheight",
            ))):
        raise AssertionError("Actual saved short-code TTF/LFF outlines and accumulated advance were not equivalently checked")
    fit = component.get("source_fit", {})
    _passing_checks(fit, "Saved whole-label glyph position, height, baseline or source bounds failed")
    if (fit.get("one_transform_for_all_characters") is not True
            or len(fit.get("component_center_errors_px", [])) != len(expected_text)
            or any(fit["checks"].get(key) is not True for key in (
                "positive_whole_TEXT_scales", "component_positions_match_source",
                "full_glyph_height_and_baseline_match_source", "whole_ink_bounds_match_source",
            ))):
        raise AssertionError("Saved label fit did not check every original character with one TEXT transform")
    neighbors = component.get("source_neighbor_clearance", {})
    if (neighbors.get("pass") is not True or neighbors.get("all_original_neighbors_preserved") is not True
            or neighbors.get("source_pixels_modified") is not False or not neighbors.get("checks")
            or any(row.get("pass") is not True or row.get("whole_graphic_component_exempted") is True for row in neighbors["checks"])):
        raise AssertionError("Saved source layout did not preserve original line/ring/underline relations")
    circle = circles[0]
    circle_id = native_identity(circle)["id"]
    center, outer_radius = SHORT_CODE_CIRCLE_FIXTURE
    radius = float(circle.dxf.radius) * 200 / 25.4
    if not _near_point(_pixel_point(circle.dxf.center), center) or abs(radius - (outer_radius - 1)) > 2:
        raise AssertionError("Saved independent short-code circle lost its source center/radius")
    rounds = source_check.get("actual_saved_text_round_clearance", {})
    relations = rounds.get("relations", [])
    if (rounds.get("pass") is not True or rounds.get("font_sha256") != font_spec["sha256"]
            or rounds.get("actual_text_attributes_sha256") != _json_digest(attributes)
            or rounds.get("source_partition_sha256") != _json_digest(partition)
            or rounds.get("source_pixels_modified") is not False or len(relations) != 1):
        raise AssertionError("Actual saved short-code ring-white-gap check is missing or empty")
    relation = relations[0]
    if (relation.get("circle_id") != circle_id or relation.get("pass") is not True
            or relation.get("original_white_gap_proved") is not True
            or relation.get("original_glyph_and_ring_touch") is not False
            or relation.get("actual_font_touches_native_circle") is not False
            or relation.get("actual_font_touches_original_ring_ink") is not False
            or relation.get("native_circle_outline_clearance_px", 0.0) <= 0.02
            or not _near_point(relation.get("circle_geometry", {}).get("center", (math.inf, math.inf)), _pixel_point(circle.dxf.center), 1e-6)
            or abs(relation.get("circle_geometry", {}).get("radius_px", math.inf) - radius) > 1e-6):
        raise AssertionError("Actual short-code font closes the proved gap to its independently saved circle")
    sweeps = [row for row in cold.get("source_checks", []) if row.get("id") == circle_id and row.get("type") == "CIRCLE"]
    circle_checks = [row for row in cold.get("circular_marker_source_checks", []) if row.get("id") == circle_id]
    if (len(sweeps) != 1 or sweeps[0].get("pass") is not True or sweeps[0].get("sampled_sweep_deg") != 360.0
            or sweeps[0].get("samples", 0) < math.ceil(2 * math.pi * radius / 0.05)
            or len(circle_checks) != 1 or circle_checks[0].get("pass") is not True
            or circle_checks[0].get("ring_source", {}).get("pass") is not True):
        raise AssertionError("Independent saved circle did not receive its full actual source audit")
    line_results, used = [], set()
    for start, end in (*SHORT_CODE_NEIGHBOR_FIXTURE, SHORT_CODE_CONTACT_FIXTURE):
        matching = []
        for entity in paths:
            points = _line_points(entity)
            if points and min(max(math.dist(points[0], start), math.dist(points[-1], end)),
                              max(math.dist(points[0], end), math.dist(points[-1], start))) <= 2.5:
                matching.append((entity, points))
        if len(matching) != 1:
            raise AssertionError("Short-code neighbor/lead is missing, duplicated, or delivered as fragments")
        entity, points = matching[0]
        oid = native_identity(entity)["id"]
        if oid in used or any(_distance_to_path(point, [start, end]) > 2.5 for point in points):
            raise AssertionError("Short-code line absorbed a glyph branch or another independent neighbor")
        used.add(oid)
        if (start, end) != SHORT_CODE_CONTACT_FIXTURE:
            _saved_line_source_check(cold, oid)
        line_results.append({"id": oid, "source_endpoints_px": [start, end], "saved_points_px": points})
    path_id = line_results[-1]["id"]
    path_row = ledger[path_id]
    proof = path_row.get("source_evidence", {}).get("text_contact_path", {})
    separation = partition.get("text_contact_separation", {})
    plan = separation.get("geometry_plan", {})
    path_plan = plan.get("paths", [])
    if (len(path_plan) != 1 or proof.get("schema") != "source-text-contact-native-path-v1"
            or proof.get("source_sha256") != objects.get("source_sha256")
            or proof.get("plan_sha256") != _json_digest(plan) or proof.get("path_index") != 0
            or proof.get("path") != path_plan[0] or proof.get("path_sha256") != _json_digest(path_plan[0])
            or not separation.get("shared_original_contact_runs")
            or separation.get("source_erasure_authorized") is not False
            or separation.get("real_source_white_gaps_filled") is not False
            or native_identity(next(entity for entity in paths if native_identity(entity)["id"] == path_id)).get("text_contact_path") is not True):
        raise AssertionError("Saved independent lead lacks the complete original-contact source plan")
    contact = cold.get("text_contact_source_checks", {})
    contact_checks = {row.get("id"): row for row in contact.get("checks", [])}
    path_check = contact_checks.get(path_id, {})
    required_types = {
        "TEXT_CONTACT_MANIFEST": "TEXT_CONTACT_MANIFEST_BINDING",
        path_id: "SAVED_TEXT_CONTACT_PATH_SOURCE",
        "TEXT_CONTACT_RETIREMENT": "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT",
        "TEXT_CONTACT_NEIGHBORS": "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION",
        "TEXT_CONTACT_DUPLICATES": "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES",
    }
    if (contact.get("schema") != "saved-text-contact-source-audit-v1"
            or contact.get("pass") is not True or contact.get("target_ids") != [path_id]
            or contact.get("duplicate_conflicts") != []
            or contact.get("source_or_DXF_geometry_modified") is not False
            or len(contact_checks) != len(contact.get("checks", [])) or set(contact_checks) != set(required_types)
            or any(contact_checks[key].get("type") != kind or contact_checks[key].get("pass") is not True for key, kind in required_types.items())):
        raise AssertionError("Saved independent lead's actual contact source audit was missing or failed")
    _passing_checks(path_check, "Saved short-code lead binding/source representation failed")
    if any(path_check["checks"].get(key) is not True for key in (
        "three_way_object_binding", "actual_identity_and_flag", "actual_vertices", "original_source_plan_replayed",
        "original_source_geometry_supported", "whole_native_representation_from_source_plan",
    )):
        raise AssertionError("Saved short-code lead audit omitted an actual source/geometry binding")
    planned = path_plan[0].get("representation", {})
    path_geometry_check = inspect_contact_path_vertices(
        document, objects, cold, next(entity for entity in paths if native_identity(entity)["id"] == path_id),
        path_row, planned, source_path,
    )
    for key in ("TEXT_CONTACT_MANIFEST", "TEXT_CONTACT_RETIREMENT"):
        _passing_checks(contact_checks[key], "Saved short-code contact binding or whole-retirement check was omitted")
    _passing_checks(path_check.get("original_source_plan_replay", {}), "Saved short-code contact plan was not replayed")
    _passing_checks(path_check.get("actual_source_geometry", {}), "Saved short-code lead source geometry was not inspected")
    protected = contact_checks.get("TEXT_CONTACT_NEIGHBORS", {}).get("objects", [])
    if (len(protected) != len(entities) - 1 or {row.get("id") for row in protected} != set(ledger) - {path_id}
            or contact_checks["TEXT_CONTACT_NEIGHBORS"].get("protected_count") != len(protected)
            or contact_checks["TEXT_CONTACT_DUPLICATES"].get("conflicts") != []
            or any(row.get("pass") is not True or not row.get("checks") or any(v is not True for v in row["checks"].values()) for row in protected)):
        raise AssertionError("Independent lead adoption did not protect every other saved object")
    control = next(entity for entity in texts if entity.dxf.text == "STORE")
    if (control.dxf.style != "I2CAD_TEXT" or document.styles.get(control.dxf.style).dxf.font != "DejaVuSans.ttf"
            or not _near_point(_pixel_point(control.dxf.insert), (462, 89), 3.0)):
        raise AssertionError("Existing correct ordinary text changed font style or position")
    return {"schema": "windows-saved-source-row-short-code-v1", "complete_label_count": 1,
            "text_id": text_id, "text": expected_text, "circle_id": circle_id,
            "independent_contact_path_id": path_id, "independent_line_checks": line_results,
            "whole_path_and_terminal_source_check": path_geometry_check,
            "default_layout_was_actually_rejected": True, "new_source_component_layout_required": True,
            "actual_source_component_layout": component, "actual_round_white_gap": rounds,
            "export_font": exported_fonts[0], "font_shape_pixel_equality_required": False,
            "all_formal_objects_accounted_for": True, "GUI_operations_claimed": False}


def inspect_short_code_payloads(objects, cold, evidence_root, source_path, source_font_path, pipeline_report, *, document=None):
    """Check original overlap/gap plus actual raw recognition, never infer text."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    glyph, ring, lead = (Image.new("L", (640, 480), 0) for _ in range(3))
    font = ImageFont.truetype(str(source_font_path), 36, layout_engine=ImageFont.Layout.BASIC)
    for text, point in SHORT_CODE_LABEL_FIXTURE:
        ImageDraw.Draw(glyph).text(point, text, font=font, fill=255)
    (cx, cy), radius = SHORT_CODE_CIRCLE_FIXTURE
    ImageDraw.Draw(ring).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=255, width=3)
    ImageDraw.Draw(lead).line(SHORT_CODE_CONTACT_FIXTURE, fill=255, width=3)
    glyph_ink, ring_ink, lead_ink = np.asarray(glyph) >= 64, np.asarray(ring) > 0, np.asarray(lead) > 0
    shared = glyph_ink & lead_ink
    if (source.shape != (480, 640) or not shared.any() or not np.all(source[shared] < 192)
            or np.any(glyph_ink & cv2.dilate(np.uint8(ring_ink), np.ones((3, 3), np.uint8)))
            or not np.all(source[ring_ink] < 192)):
        raise AssertionError("Fifth original input lost its real line contact or proved ring white gap")
    target = next(row for row in objects["objects"] if row.get("source_evidence", {}).get("text_contact_path"))
    proof = target["source_evidence"]["text_contact_path"]
    original_target = target
    if "circle_endpoint_contacts" in target["source_evidence"]:
        from copy import deepcopy

        if document is None:
            raise AssertionError("Original contact manifest binding requires the actual saved terminal geometry")
        entity = next(value for value in document.modelspace() if value.dxf.layer != "REVIEW" and native_identity(value)["id"] == target["id"])
        inspect_contact_path_vertices(document, objects, cold, entity, target, proof["path"]["representation"], source_path)
        original_target = deepcopy(target)
        certificate = original_target["source_evidence"].pop("circle_endpoint_contacts")
        original_target["geometry"] = certificate["original_geometry"]
    manifest_path = evidence_root / "text_contact/adoption.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("source_sha256") != digest(source_path) or manifest.get("source_pixels_modified") is not False
            or manifest.get("objects") != [original_target]
            or _json_digest(manifest.get("geometry_plans", {}).get(proof["plan_sha256"])) != proof["plan_sha256"]):
        raise AssertionError("Short-code lead's actual adoption file is not bound to the original PNG")
    report = pipeline_report.get("text_contact_completion", {})
    if (report.get("new_complete_graphics") != 1
            or report.get("actual_saved_source_checks") != cold.get("text_contact_source_checks")):
        raise AssertionError("Ordinary pipeline did not publish the saved short-code lead source checks")
    raw = inspect_single_line_character_payloads(objects, cold, evidence_root, pipeline_report)
    return {"source_sha256": digest(source_path), "original_shared_line_glyph_pixels": int(shared.sum()),
            "original_glyph_ring_8_adjacent": False, "actual_label_payloads": raw,
            "fixture_expectations_sent_to_recognizer": False, "inspection_executed_recognition": False}


def inspect_contact_edit_isolation(saved_path: Path, output: Path, text_id: str, path_id: str) -> dict:
    """Actual scripted save/reopen edits; this deliberately makes no GUI claim."""
    import ezdxf

    def inventory(document):
        return {native_identity(entity)["id"]: entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"}

    def edit_geometry(entity, document):
        value = entity_geometry(entity, document)
        if entity.dxftype() == "LWPOLYLINE":
            # translate() materializes default plane attributes which the DXF
            # writer is allowed to omit. Compare their actual values as well.
            value["attributes"].update(elevation=float(entity.dxf.get("elevation", 0)),
                                       extrusion=canonical_value(entity.dxf.get("extrusion", (0, 0, 1))))
        return value

    original_sha = digest(saved_path)
    baseline = ezdxf.readfile(saved_path)
    before = {key: edit_geometry(entity, baseline) for key, entity in inventory(baseline).items()}
    output.mkdir(exist_ok=True)
    results = []
    for action, target_id in (("change-text", text_id), ("move-text", text_id), ("delete-text", text_id), ("move-path", path_id), ("delete-path", path_id)):
        document = ezdxf.readfile(saved_path)
        target = inventory(document)[target_id]
        if action == "change-text":
            target.dxf.text = "EDITED59"
        elif action.startswith("move"):
            target.translate(7, 3, 0)
        else:
            document.modelspace().delete_entity(target)
        expected = None if action.startswith("delete") else edit_geometry(target, document)
        edited_path = output / (action + ".dxf")
        document.saveas(edited_path)
        reopened = ezdxf.readfile(edited_path)
        audit = reopened.audit()
        actual = {key: edit_geometry(entity, reopened) for key, entity in inventory(reopened).items()}
        expected_ids = set(before) - ({target_id} if expected is None else set())
        if (audit.errors or audit.fixes or set(actual) != expected_ids
                or any(actual[key] != value for key, value in before.items() if key != target_id)
                or (expected is not None and (actual[target_id] != expected or actual[target_id] == before[target_id]))):
            raise AssertionError("Contact text/line edit did not survive cold save with every neighbor unchanged")
        results.append({"action": action, "changed_id": target_id, "saved_dxf_sha256": digest(edited_path),
                        "unchanged_other_formal_objects": len(before) - 1, "pass": True})
    if digest(saved_path) != original_sha:
        raise AssertionError("Scripted editing changed the published native fixture result")
    result = {"schema": "windows-contact-scripted-edit-isolation-v1", "pass": True,
              "scope": "ezdxf ordinary save and cold reopen, not LibreCAD GUI",
              "GUI_operations_claimed": False, "source_DXF_unchanged": True, "checks": results}
    write_json(output / "edit-isolation.json", result)
    return result


def inspect_circle_path_edit_isolation(saved_path: Path, output: Path, marker_id: str, path_id: str) -> dict:
    """Move/delete a unique circle+TEXT block and delete a separate whole path.

    Every action starts from the published file and is saved then cold-read.
    These file operations are deliberately not reported as LibreCAD GUI work.
    """
    import ezdxf

    def inventory(document):
        return {native_identity(entity)["id"]: entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"}

    original_sha = digest(saved_path)
    baseline = ezdxf.readfile(saved_path)
    entities = inventory(baseline)
    marker, path = entities[marker_id], entities[path_id]
    if (marker.dxftype() != "INSERT" or native_identity(marker)["kind"] != "CIRCULAR_MARKER"
            or Counter(entity.dxftype() for entity in marker.virtual_entities()) != {"CIRCLE": 1, "TEXT": 1}
            or len([entity for entity in entities.values() if entity.dxftype() == "INSERT" and entity.dxf.name == marker.dxf.name]) != 1
            or len(_line_points(path)) < 2):
        raise AssertionError("Edit isolation requires a unique circle/TEXT block and a distinct whole native path")
    before = {key: entity_geometry(entity, baseline) for key, entity in entities.items()}
    original_members = list(marker.virtual_entities())
    original_circle = next(entity for entity in original_members if entity.dxftype() == "CIRCLE")
    original_text = next(entity for entity in original_members if entity.dxftype() == "TEXT")
    output.mkdir(exist_ok=True)
    results = []
    for action, target_id in (("move-marker", marker_id), ("delete-marker", marker_id),
                              ("change-marker-text", marker_id), ("delete-path", path_id)):
        document = ezdxf.readfile(saved_path)
        target = inventory(document)[target_id]
        if action == "move-marker":
            target.translate(7, 3, 0)
        elif action == "change-marker-text":
            next(entity for entity in document.blocks[target.dxf.name] if entity.dxftype() == "TEXT").dxf.text = "Q7"
        else:
            document.modelspace().delete_entity(target)
        expected = None if action.startswith("delete") else entity_geometry(target, document)
        edited_path = output / (action + ".dxf")
        document.saveas(edited_path)
        reopened = ezdxf.readfile(edited_path)
        audit = reopened.audit()
        actual_entities = inventory(reopened)
        actual = {key: entity_geometry(entity, reopened) for key, entity in actual_entities.items()}
        expected_ids = set(before) - ({target_id} if expected is None else set())
        if (audit.errors or audit.fixes or set(actual) != expected_ids
                or any(actual[key] != value for key, value in before.items() if key != target_id)
                or (expected is not None and (actual[target_id] != expected or actual[target_id] == before[target_id]))):
            raise AssertionError("Circle/block/path edit failed cold save/reopen or changed an independent neighbor")
        if action in ("move-marker", "change-marker-text"):
            members = list(actual_entities[marker_id].virtual_entities())
            if Counter(entity.dxftype() for entity in members) != {"CIRCLE": 1, "TEXT": 1}:
                raise AssertionError("Edited marker lost its actual CIRCLE/TEXT composition")
            circle = next(entity for entity in members if entity.dxftype() == "CIRCLE")
            text = next(entity for entity in members if entity.dxftype() == "TEXT")
            if action == "move-marker":
                if (not _near_point(circle.dxf.center, original_circle.dxf.center + (7, 3, 0), 1e-8)
                        or not _near_point(text.dxf.insert, original_text.dxf.insert + (7, 3, 0), 1e-8)
                        or text.dxf.text != original_text.dxf.text
                        or float(circle.dxf.radius) != float(original_circle.dxf.radius)):
                    raise AssertionError("Circle and adopted TEXT did not move together after reopening")
            elif (text.dxf.text != "Q7" or entity_geometry(circle, reopened) != entity_geometry(original_circle, baseline)):
                raise AssertionError("Direct block TEXT editing changed its independent circle")
        results.append({"action": action, "changed_id": target_id, "saved_dxf_sha256": digest(edited_path),
                        "unchanged_other_formal_objects": len(before) - 1,
                        "circle_and_text_move_or_delete_together": action in ("move-marker", "delete-marker"),
                        "pass": True})
    if digest(saved_path) != original_sha:
        raise AssertionError("Scripted editing changed the published native fixture result")
    result = {"schema": "windows-circle-path-scripted-edit-isolation-v1", "pass": True,
              "scope": "ezdxf ordinary save and cold reopen, not LibreCAD GUI",
              "GUI_operations_claimed": False, "source_DXF_unchanged": True, "checks": results}
    write_json(output / "edit-isolation.json", result)
    return result


def _inspect_single_line_preexisting_raw_inventory(evidence, read_record):
    """Bind every already available finite-plan raw view to its consumed bytes."""
    reference = evidence.get("preexisting_raw_view_inventory")
    if not isinstance(reference, dict):
        raise AssertionError("Single-line evidence omitted its pre-recognition raw-view inventory")
    _, raw = read_record(reference)
    inventory = json.loads(raw)
    source_hash = evidence.get("source_array_sha256")
    if (inventory.get("schema") != "single-line-preexisting-raw-view-inventory-v1"
            or not isinstance(source_hash, str) or len(source_hash) != 64
            or inventory.get("source_array_sha256") != source_hash
            or inventory.get("source_bbox_xyxy_px") != evidence.get("source_bbox_xyxy_px")
            or inventory.get("recorded_before_any_recognition_or_adoption") is not True
            or inventory.get("missing_views_do_not_request_recognition") is not True):
        raise AssertionError("Single-line preexisting raw inventory lost its original source or timing binding")
    saved = {"Tesseract": {view["view_index"]: view for view in evidence["tesseract_views"]},
             "PP-OCR": {view["view_index"]: view for view in evidence["ppocr_views"]}}
    rows = inventory.get("views", [])
    keys = [(row.get("engine"), row.get("view_index")) for row in rows]
    required_keys = [(family, index) for index in range(2) for family in ("Tesseract", "PP-OCR")]
    if keys != required_keys or any(type(row.get("view_index")) is not int for row in rows):
        raise AssertionError("Single-line preexisting raw inventory is incomplete, duplicated or reordered")
    known = []
    for slot in rows:
        family, index = slot["engine"], slot["view_index"]
        spec = (SINGLE_LINE_TESSERACT_VIEWS if family == "Tesseract" else SINGLE_LINE_PP_OCR_VIEWS)[index]
        view = saved[family].get(index)
        input_hash = slot.get("input_array_sha256")
        if (slot.get("normalization") != spec or not isinstance(input_hash, str) or len(input_hash) != 64
                or (view is not None and input_hash != view.get("normalization", {}).get("input_array_sha256"))):
            raise AssertionError("Known raw view changed its frozen configuration or actual input samples")
        availability = slot.get("availability")
        if availability == "ABSENT":
            if slot.get("raw_observation_cache") is not None or any(key in slot for key in ("raw_payload", "cache_record", "checkpoint_metadata")):
                raise AssertionError("An absent preexisting view contains an unaccounted raw record")
            continue
        if availability not in ("RAW_CACHE", "OUTPUT_CHECKPOINT") or view is None:
            raise AssertionError("A known finite-plan raw view was omitted from the saved observations")
        if not isinstance(slot.get("raw_payload"), dict):
            raise AssertionError("Known raw view omitted its preserved original payload")
        _, payload = read_record(slot["raw_payload"])
        payload_sha = hashlib.sha256(payload).hexdigest()
        if family == "Tesseract":
            _, consumed = read_record(view["raw_tsv"])
            _, metadata_raw = read_record(view["metadata"])
            metadata = json.loads(metadata_raw)
            if payload != consumed or view.get("command_executed_for_this_request") is not False:
                raise AssertionError("Known Tesseract bytes changed or were counted as a fresh recognition call")
            actual_receipt = metadata.get("raw_observation_cache")
        else:
            if json.loads(payload) != view.get("prediction") or view.get("model_inference_executed_for_this_request") is not False:
                raise AssertionError("Known model output changed or was counted as a fresh inference")
            actual_receipt = view.get("observation_receipt", {}).get("raw_observation_cache")
        if availability == "RAW_CACHE":
            if not isinstance(slot.get("cache_record"), dict) or not isinstance(slot.get("raw_observation_cache"), dict):
                raise AssertionError("Known raw cache view omitted its cache record or receipt")
            _, record_bytes = read_record(slot["cache_record"])
            record = json.loads(record_bytes)
            specification, receipt = record.get("specification", {}), slot["raw_observation_cache"]
            request_key = hashlib.sha256(json.dumps(specification, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            expected_kinds = ("tesseract-tsv", "historical-tesseract-tsv") if family == "Tesseract" else ("ppocr-ctc",)
            if (record.get("schema") != "native-raw-observation-cache-v1"
                    or specification.get("schema") != "native-raw-observation-cache-v1"
                    or specification.get("kind") not in expected_kinds or specification.get("source_pixels_modified") is not False
                    or not isinstance(specification.get("engine"), dict) or not specification["engine"]
                    or record.get("key") != request_key or receipt.get("key") != request_key
                    or receipt.get("kind") != specification.get("kind") or receipt.get("producer") != record.get("producer")
                    or actual_receipt != receipt or receipt.get("record_sha256") != slot["cache_record"]["sha256"]
                    or receipt.get("payload_sha256") != payload_sha or record.get("payload_sha256") != payload_sha
                    or record.get("payload_bytes") != len(payload)):
                raise AssertionError("Known raw cache record, producer receipt or payload binding changed")
            if family == "Tesseract":
                if (specification.get("recognition_input", {}).get("sha256") != input_hash
                        or specification.get("external_white_padding_px") != spec["padding"]
                        or specification.get("psm") != spec["psm"]
                        or specification.get("recognition_dpi") != evidence.get("recognition_dpi", 0) * spec["scale"]
                        or any(metadata.get("consumer_installed_engine_identity", {}).get(key) != value for key, value in specification.get("engine", {}).items())):
                    raise AssertionError("Known Tesseract cache configuration differs from the current original-source view")
            else:
                _, identity_bytes = read_record(evidence["model_identity"])
                identity = json.loads(identity_bytes)
                if (specification.get("crop", {}).get("sha256") != input_hash
                        or specification.get("model_tensor", {}).get("sha256") != view["prediction"].get("model_tensor_sha256")
                        or any(identity.get(key) != value for key, value in specification.get("engine", {}).items())):
                    raise AssertionError("Known model cache configuration differs from the current original-source view")
        elif family == "Tesseract":
            if not isinstance(slot.get("checkpoint_metadata"), dict):
                raise AssertionError("Known Tesseract checkpoint omitted its original metadata")
            _, metadata_bytes = read_record(slot["checkpoint_metadata"])
            original = json.loads(metadata_bytes)
            if original.get("status") != "COMPLETED" or original.get("return_code") != 0 or original.get("tsv_sha256") != payload_sha:
                raise AssertionError("Known Tesseract checkpoint no longer identifies its preserved raw bytes")
        known.append({"engine": family, "view_index": index, "availability": availability, "raw_payload_sha256": payload_sha})
    return {"inventory_sha256": reference["sha256"], "all_preexisting_views_replayed": True,
            "known_view_count": len(known), "known_views": known, "new_recognition_requested_for_absent_views": False}


def _inspect_single_line_raw_view_payloads(evidence, read_record):
    """Read actual accepted or pending producer payloads; this never adopts text."""
    from io import BytesIO

    import numpy as np
    from PIL import Image

    def array_digest(data):
        with Image.open(BytesIO(data)) as image:
            array = np.ascontiguousarray(image.convert("L"))
        return hashlib.sha256(array.tobytes()).hexdigest()

    policy = evidence.get("policy", {})
    if (policy.get("Tesseract_views") != list(SINGLE_LINE_TESSERACT_VIEWS)
            or policy.get("PP_OCR_views") != list(SINGLE_LINE_PP_OCR_VIEWS)
            or policy.get("maximum_views_per_engine") != 2):
        raise AssertionError("Single-line recognition view policy differs from its frozen bounded configuration")
    read_record(evidence["original_source"])
    _, identity_raw = read_record(evidence["model_identity"])
    if json.loads(identity_raw).get("providers") != ["CPUExecutionProvider"]:
        raise AssertionError("Single-line recovery did not use its recorded CPU model")
    t_views, p_views = evidence["tesseract_views"], evidence["ppocr_views"]
    for views in (t_views, p_views):
        indices = [view.get("view_index") for view in views]
        if (not 1 <= len(views) <= 2 or any(type(index) is not int or index not in (0, 1) for index in indices)
                or indices != sorted(set(indices))):
            raise AssertionError("Single-line engine views are not unique, ordered members of its frozen finite plan")
    t_calls = p_calls = 0
    for view in t_views:
        index = view["view_index"]
        _, raw = read_record(view["raw_tsv"])
        _, metadata_raw = read_record(view["metadata"])
        _, image_raw = read_record(view["recognition_image"])
        metadata = json.loads(metadata_raw)
        norm = view.get("normalization", {})
        if (view.get("view_index") != index
                or any(norm.get(key) != value for key, value in SINGLE_LINE_TESSERACT_VIEWS[index].items())
                or norm.get("source_bbox_xyxy_px") != evidence.get("source_bbox_xyxy_px")
                or norm.get("input_array_sha256") != array_digest(image_raw)
                or norm.get("original_source_pixels_modified") is not False):
            raise AssertionError("Single-line Tesseract input differs from its fixed source-derived view")
        if (metadata.get("status") != "COMPLETED" or metadata.get("return_code") != 0
                or metadata.get("tsv_sha256") != hashlib.sha256(raw).hexdigest()
                or metadata.get("image_sha256") != hashlib.sha256(image_raw).hexdigest()):
            raise AssertionError("Single-line Tesseract raw/image bytes differ from the actual producer receipt")
        called = view["command_executed_for_this_request"]
        if not isinstance(called, bool) or called is not metadata.get("command_executed_for_this_request"):
            raise AssertionError("Single-line Tesseract call count includes an unexecuted observation")
        t_calls += called
    for view in p_views:
        index = view["view_index"]
        _, prediction_raw = read_record(view["prediction_file"])
        _, image_raw = read_record(view["recognition_image"])
        prediction = json.loads(prediction_raw)
        norm = view.get("normalization", {})
        if (view.get("view_index") != index
                or any(norm.get(key) != value for key, value in SINGLE_LINE_PP_OCR_VIEWS[index].items())
                or norm.get("source_bbox_xyxy_px") != evidence.get("source_bbox_xyxy_px")
                or norm.get("input_array_sha256") != array_digest(image_raw)
                or norm.get("original_source_pixels_modified") is not False):
            raise AssertionError("Single-line model input differs from its fixed source-derived view")
        if (prediction != view["prediction"]
                or prediction.get("input_array_sha256") != array_digest(image_raw)
                or prediction.get("raw_transcription_rewritten") is not False
                or prediction.get("source_geometry_modified") is not False):
            raise AssertionError("Single-line model raw payload differs from its actual recognition input")
        called = view["model_inference_executed_for_this_request"]
        if not isinstance(called, bool) or called is not view["observation_receipt"].get("model_inference_executed_for_this_request"):
            raise AssertionError("Single-line model call count includes an unexecuted observation")
        p_calls += called
    if evidence.get("new_Tesseract_calls") != t_calls or evidence.get("new_model_calls") != p_calls:
        raise AssertionError("Single-line call counters disagree with the saved producer receipts")
    inventory = _inspect_single_line_preexisting_raw_inventory(evidence, read_record)
    return {"Tesseract_views": len(t_views), "PP_OCR_views": len(p_views), "new_Tesseract_calls": t_calls,
            "new_model_calls": p_calls, "preexisting_raw_view_inventory": inventory}


def inspect_single_line_character_payloads(objects, cold, evidence_root: Path, pipeline_report) -> dict:
    """Re-read raw accepted-label files and actual call receipts without OCR.

    The ordinary saved audit separately replays source ownership and the finite
    source-to-derived transforms. This inspection does not replace that gate.
    """
    summary_path = evidence_root / "single_line_labels/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if pipeline_report.get("single_line_label_recovery") != summary:
        raise AssertionError("Single-line call summary is not the current ordinary pipeline report")
    for key in ("new_Tesseract_calls", "new_model_calls"):
        if not isinstance(summary.get(key), int) or isinstance(summary[key], bool) or summary[key] <= 0:
            raise AssertionError("Single-line stage did not record real new Tesseract and model calls")
    checks = {row["id"]: row for row in cold.get("single_line_text_source_checks", [])}
    payloads = {}

    def read_record(record):
        path, data = _checked_record(evidence_root, record)
        prior = payloads.get(record["path"])
        if prior is not None and prior != record["sha256"]:
            raise AssertionError("Single-line raw file has conflicting evidence hashes")
        payloads[record["path"]] = record["sha256"]
        return path, data

    verified = []
    for obj in objects["objects"]:
        evidence = obj.get("source_evidence", {}).get("single_line_recovery")
        if evidence is None:
            continue
        check = checks.get(obj["id"], {})
        replay = check.get("source_replay", {})
        if (obj.get("kind") != "TEXT"
                or evidence.get("schema") != "native-single-line-label-evidence-v1"
                or check.get("type") != "SINGLE_LINE_TEXT_SOURCE_BINDING"
                or check.get("pass") is not True or replay.get("pass") is not True
                or replay.get("new_OCR_calls") != 0 or replay.get("new_model_calls") != 0):
            raise AssertionError("Actual single-line TEXT lacks a passing complete source replay")
        decision = evidence.get("decision", {})
        if decision.get("accepted") is not True or decision.get("text") != obj["geometry"]["text"]:
            raise AssertionError("Saved single-line content differs from its complete observed decision")
        normalization = decision.get("source_text_normalization")
        if (not isinstance(normalization, dict) or normalization.get("text") != decision["text"]
                or normalization.get("reasons") != []
                or not isinstance(normalization.get("normalizations"), list)
                or not isinstance(normalization.get("word_spaces"), list)
                or replay.get("source_text_normalization") != normalization
                or replay.get("Tesseract_canonical_word_texts") != decision.get("Tesseract_canonical_word_texts")):
            raise AssertionError("Single-line source character/space normalization was not replayed unchanged")
        raw_report = _inspect_single_line_raw_view_payloads(evidence, read_record)
        verified.append({"id": obj["id"], "text": decision["text"], **raw_report, "source_text_normalization": normalization, "raw_transcription_compared_before_source_supported_canonicalization": True})
    actual_tesseract = sum(row["new_Tesseract_calls"] for row in verified)
    actual_model = sum(row["new_model_calls"] for row in verified)
    if (not verified or actual_tesseract <= 0 or actual_model <= 0
            or actual_tesseract > summary["new_Tesseract_calls"]
            or actual_model > summary["new_model_calls"]):
        raise AssertionError("Single-line fixture did not execute new recognition for its actual recovered TEXT")
    return {
        "verified_saved_recovery_TEXT": verified,
        "accepted_label_raw_files_read_and_hashed": len(payloads),
        "accepted_label_new_Tesseract_calls": actual_tesseract,
        "accepted_label_new_model_calls": actual_model,
        "new_Tesseract_calls": summary["new_Tesseract_calls"],
        "new_model_calls": summary["new_model_calls"],
        "stage_counts_include_pending_attempts": True,
        "source_partition_and_derived_views_replayed_by_saved_audit": True,
        "inspection_executed_recognition": False,
    }


def inspect_single_line_pending_label(objects, evidence_root: Path, source_path: Path, font_path: Path, pipeline_report) -> dict:
    """Keep the unresolved first fixture label fully source-bound and visible.

    The expected fixture string locates a post-save check only. It is never
    supplied to recognition, substituted for raw observations, or adopted here.
    """
    from io import BytesIO

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    expected_text, point = SINGLE_LINE_LABEL_FIXTURE[0]
    summary = json.loads((evidence_root / "single_line_labels/summary.json").read_text(encoding="utf-8"))
    if pipeline_report.get("single_line_label_recovery") != summary or summary.get("source_sha256") != digest(source_path):
        raise AssertionError("Pending label is not bound to the ordinary source stage")
    with Image.open(source_path) as image:
        source = np.ascontiguousarray(image.convert("L"))
    if summary.get("source_array_sha256") != hashlib.sha256(source.tobytes()).hexdigest():
        raise AssertionError("Pending label lost the original source array")
    font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    rendered = Image.new("L", (640, 480), 0)
    ImageDraw.Draw(rendered).text(point, expected_text, font=font, fill=255)
    expected_box = rendered.getbbox()

    def full_box(box):
        return (isinstance(box, (list, tuple)) and len(box) == 4
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                and max(abs(a - b) for a, b in zip(box, expected_box)) <= 2)

    attempts = [row for row in summary.get("attempts", []) if full_box(row.get("bbox_xyxy_px"))]
    if (len(attempts) != 1 or attempts[0].get("accepted") is not False
            or attempts[0].get("text") is not None or not attempts[0].get("reasons")
            or summary.get("pending_labels", 0) < 1):
        raise AssertionError("Unwritten label has no explicit complete pending attempt")
    attempt = attempts[0]
    payloads = {}

    def read_record(record):
        path, raw = _checked_record(evidence_root, record)
        if record["path"] in payloads and payloads[record["path"]][0] != record["sha256"]:
            raise AssertionError("Pending label raw manifest has conflicting hashes")
        payloads[record["path"]] = (record["sha256"], raw)
        return path, raw

    for record in summary.get("raw_evidence_files", []):
        read_record(record)
    result_name = f"single_line_labels/labels/{attempt['id']}/label_result.json"
    if result_name not in payloads:
        raise AssertionError("Pending label has no hashed original result payload")
    result = json.loads(payloads[result_name][1])
    evidence = result.get("evidence", {})
    decision = evidence.get("decision", {})
    if (result.get("accepted") is not False or result.get("text") is not None
            or result.get("geometry") is not None or not result.get("reasons")
            or decision.get("accepted") is not False or decision.get("text") is not None
            or decision.get("reasons") != result["reasons"]
            or result["reasons"] != attempt["reasons"]
            or evidence.get("schema") != "native-single-line-label-evidence-v1"
            or evidence.get("expected_answers_provided") is not False
            or evidence.get("original_source_pixels_modified") is not False
            or evidence.get("raw_transcription_rewritten") is not False):
        raise AssertionError("Pending label was rewritten, partially adopted, or lost its reason")
    box = evidence.get("source_bbox_xyxy_px")
    if not full_box(box) or box != result.get("bbox_xyxy_px") or box != attempt["bbox_xyxy_px"] or not all(isinstance(v, int) for v in box):
        raise AssertionError("Pending label source record covers only a fragment")
    x0, y0, x1, y1 = box
    ey, ex = np.nonzero(source[expected_box[1]:expected_box[3], expected_box[0]:expected_box[2]] < 192)
    if (not len(ex) or x0 > int(ex.min()) + expected_box[0] or x1 <= int(ex.max()) + expected_box[0]
            or y0 > int(ey.min()) + expected_box[1] or y1 <= int(ey.max()) + expected_box[1]):
        raise AssertionError("Pending label crop excludes real original character ink")
    _, original_bytes = read_record(evidence["original_source"])
    with Image.open(BytesIO(original_bytes)) as image:
        original = np.asarray(image.convert("L"))
    if not np.array_equal(original, source[y0:y1, x0:x1]):
        raise AssertionError("Pending original label pixels were changed or truncated")
    partition = evidence.get("source_partition", {})
    if (partition.get("bbox_xyxy_px") != box or partition.get("all_label_ink_assigned") is not True
            or partition.get("original_source_pixels_modified") is not False
            or partition.get("recognition_excluded_graphic_runs_y_x0_x1") != []):
        raise AssertionError("Pending first-label source partition omits original ink")
    source_mask = np.zeros(original.shape, dtype=bool)
    for y, lo, hi in partition.get("source_support_runs_y_x0_x1", []):
        if not (y0 <= y < y1 and x0 <= lo < hi <= x1):
            raise AssertionError("Pending source support exceeds the complete original label")
        source_mask[y - y0, lo - x0:hi - x0] = True
    if not np.array_equal(source_mask, original < 192):
        raise AssertionError("Pending label source support lost a character or punctuation")
    raw_report = _inspect_single_line_raw_view_payloads(evidence, read_record)
    for key in ("new_Tesseract_calls", "new_model_calls"):
        if raw_report[key] <= 0 or evidence.get(key) != raw_report[key] or result.get(key) != raw_report[key] or attempt.get(key) != raw_report[key]:
            raise AssertionError("Pending label has no matching actual recognition receipts")
    for family in ("tesseract_views", "ppocr_views"):
        for view in evidence[family]:
            _, raw = read_record(view["recognition_image"])
            norm = view["normalization"]
            derived = np.pad(np.repeat(np.repeat(original, norm["scale"], axis=0), norm["scale"], axis=1), norm["padding"], constant_values=255)
            with Image.open(BytesIO(raw)) as image:
                if not np.array_equal(np.asarray(image.convert("L")), derived):
                    raise AssertionError("Pending raw recognition input no longer preserves its complete source")
    completed = json.loads((evidence_root / "single_line_labels/completed_text.json").read_text(encoding="utf-8"))
    if completed.get("source_array_sha256") != summary["source_array_sha256"]:
        raise AssertionError("Pending text checkpoint is stale for this source")
    region_ids = attempt.get("region_ids", [])
    regions = [r for r in completed.get("regions", []) if r.get("id") in region_ids]
    groups = [g for g in completed.get("groups", []) if g.get("region_ids") == region_ids]
    if (not region_ids or len(regions) != len(region_ids) or len(groups) != 1
            or groups[0].get("complete") is not False or not groups[0].get("unresolved_reasons")
            or not full_box(groups[0].get("bbox_xyxy_px"))
            or any(r.get("complete") is not False or not r.get("unresolved_reasons") for r in regions)):
        raise AssertionError("Unwritten label silently disappeared from the complete pending group ledger")
    uncertainties = json.loads((evidence_root / "quality_uncertainties.json").read_text(encoding="utf-8"))
    indices = [i for i, row in enumerate(uncertainties) if row.get("id") == groups[0]["id"] and full_box(row.get("bbox_xyxy_px")) and row.get("reason")]
    issues = json.loads((evidence_root / "quality_issues.json").read_text(encoding="utf-8"))
    matching = []
    for issue in issues.get("issues", []):
        binding = issue.get("binding", {})
        support = issue.get("source_support", {})
        if (support.get("uncertainty_record_index") in indices
                and support.get("details_file") == "quality_uncertainties.json"
                and issue.get("status") == "PENDING_SOURCE_REPAIR" and full_box(issue.get("bbox_xyxy_px"))
                and binding.get("source_file_sha256") == digest(source_path)
                and binding.get("saved_DXF_sha256") == objects.get("dxf_sha256")):
            matching.append(issue["id"])
    if len(indices) != 1 or len(matching) != 1:
        raise AssertionError("Unwritten label lacks a full localized repair issue bound to the actual DXF")
    return {
        "fixture_validation_label": expected_text, "status": "PENDING_SOURCE_REPAIR",
        "counted_as_complete": False, "pending_attempt_id": attempt["id"],
        "source_bbox_xyxy_px": box, "reasons": result["reasons"],
        "pending_group_id": groups[0]["id"], "actual_quality_issue_id": matching[0],
        "raw_pending_candidate_text_not_adopted": groups[0].get("text"),
        "original_source_and_all_label_ink_preserved": True,
        "raw_files_read_and_hashed": len(payloads), "actual_producer_receipts": raw_report,
        "source_derived_inputs_recomputed_without_recognition": True,
        "inspection_executed_recognition": False,
    }


def inspect_bounded_single_line_members(document, objects, cold, font_path, evidence_root, source_path, pipeline_report):
    """Actual capability gate alongside the unchanged strict-three-label goal."""
    saved = [e.dxf.text for e in document.modelspace() if e.dxf.layer != "REVIEW" and e.dxftype() == "TEXT"]
    first = SINGLE_LINE_LABEL_FIXTURE[0][0]
    first_complete = first in saved
    required = SINGLE_LINE_LABEL_FIXTURE if first_complete else SINGLE_LINE_LABEL_FIXTURE[1:]
    result = _inspect_single_line_members_for_labels(document, objects, cold, font_path, required)
    checks = {r["text"]: r for r in result["TEXT_checks"]}
    if not checks[SINGLE_LINE_LABEL_FIXTURE[1][0]]["new_source_recovery_replayed"]:
        raise AssertionError("Bounded capability did not save the touching alphanumeric label through new recovery")
    if first_complete and not checks[first]["new_source_recovery_replayed"]:
        raise AssertionError("Formally recovered difficult label lacks its complete source replay")
    pending = [] if first_complete else [inspect_single_line_pending_label(objects, evidence_root, source_path, font_path, pipeline_report)]
    strict_failure = None
    try:
        inspect_single_line_members(document, objects, cold, font_path)
    except AssertionError as exc:
        if first_complete or str(exc) != "Single-line fixture did not save one complete literal TEXT per label/control":
            raise
        strict_failure = str(exc)
    result.update({
        "contract": "editable_alphanumeric_capability_with_explicit_pending_source_v1",
        "strict_three_complete_status": "PASS" if first_complete else "FAIL",
        "strict_three_complete_goal_met": first_complete,
        "strict_three_complete_failure_preserved": not first_complete,
        "strict_three_complete_inspector_executed": True,
        "strict_three_complete_failure": strict_failure,
        "complete_count": len(required), "pending_count": len(pending),
        "new_recovery_count": len(result["new_recovery_label_ids"]),
        "supported_capability_pass": True, "pending_labels": pending,
        "all_labels_are_single_top_level_TEXT": first_complete,
        "all_complete_labels_are_single_top_level_TEXT": True,
        "pending_label_not_counted_as_complete": True,
        "strict_inspector_remains_available_and_requires_all_three_labels": True,
    })
    return result


def canonical_value(value):
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): canonical_value(v) for k, v in sorted(value.items())}
    try:
        return [canonical_value(item) for item in value]
    except TypeError:
        return str(value)


def entity_geometry(entity, document) -> dict:
    attributes = dict(entity.dxf.all_existing_dxf_attribs())
    for key in ("handle", "owner", "paperspace", "material_handle", "plotstyle_handle"):
        attributes.pop(key, None)
    result = {"type": entity.dxftype(), "attributes": canonical_value(attributes)}
    if entity.dxftype() == "LWPOLYLINE":
        result["points"] = canonical_value(list(entity.get_points("xyseb")))
    if entity.dxftype() == "POLYLINE":
        result["points"] = canonical_value([vertex.dxf.location for vertex in entity.vertices])
    if entity.dxftype() == "INSERT":
        result["members"] = [entity_geometry(member, document) for member in document.blocks[entity.dxf.name]]
    return result


def inspect_result(work: Path, source_sha: str, *, frozen: bool, fixture_kind: str = "room17", single_line_contract: str = "strict-three", source_row_font_spec: dict | None = None, source_row_fixture_font: Path | None = None) -> dict:
    import ezdxf

    target = work / "native.dxf"
    document = ezdxf.readfile(target)
    audit = document.audit()
    if audit.errors or audit.fixes or document.units != 4:
        raise AssertionError("Actual saved DXF failed cold audit/paper-mm units")
    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    types = Counter(entity.dxftype() for entity in entities)
    if fixture_kind not in ("room17", "circular-markers", "single-line-labels", "text-line-contact", "short-codes", "curve-end-boundaries", "circle-character-completion", "observed-terminal-core"):
        raise ValueError("Unknown permitted native smoke fixture")
    if any(types[kind] for kind in ("HATCH", "IMAGE")) or (fixture_kind == "room17" and types["LINE"] != 5):
        raise AssertionError("Controlled input lost expected real native line geometry")
    texts = []
    for entity in entities:
        members = list(entity.virtual_entities()) if entity.dxftype() == "INSERT" else [entity]
        texts += [member.dxf.text for member in members if member.dxftype() == "TEXT"]
        texts += [member.plain_text() for member in members if member.dxftype() == "MTEXT"]
    if fixture_kind == "room17" and "ROOM 17" not in texts:
        raise AssertionError("Controlled input did not save its complete editable native text")
    companion = target.with_suffix(".native")
    objects = json.loads((companion / "result.objects.json").read_text(encoding="utf-8"))
    if objects.get("dxf_sha256") != digest(target) or objects.get("source_sha256") != source_sha:
        raise AssertionError("Object ledger is not bound to the actual saved DXF and generated input")
    font = objects["font"]
    if digest(companion / font["font"]) != font["sha256"] or not (companion / font["bundled_license"]).is_file():
        raise AssertionError("Saved native text has missing or changed bundled font/license")
    cold = json.loads((companion / "evidence/cold_audit.json").read_text(encoding="utf-8"))
    if not cold["source_gate_pass"] or not cold["dxf_unchanged"] or cold.get("dxf_sha256") != digest(target):
        raise AssertionError("Actual published native result failed its saved source audit")
    pipeline_report = json.loads((companion / "result.report.json").read_text(encoding="utf-8"))
    circle_result = inspect_circular_members(document, objects, cold) if fixture_kind == "circular-markers" else None
    if circle_result is not None:
        circle_result["original_real_gap_evidence"] = inspect_circular_fixture_source_gap(work.parent / "controlled-source.png")
    curve_end_result = None
    if fixture_kind == "curve-end-boundaries":
        curve_end_result = inspect_circular_members(document, objects, cold, curve_end_boundaries=True)
        curve_end_result["original_real_gap_evidence"] = inspect_curve_end_fixture_source_gap(work.parent / "controlled-source.png")
        curve_end_result["scripted_edit_isolation"] = inspect_circle_path_edit_isolation(
            target, work / "edit-isolation", curve_end_result["independent_marker_for_edit_id"],
            curve_end_result["independent_boundary_contact_path_id"],
        )
    completion_result = None
    if fixture_kind == "circle-character-completion":
        completion_result = inspect_circle_completion_members(document, objects, cold, work.parent / "controlled-source.png")
        completion_result["scripted_edit_isolation"] = inspect_circle_path_edit_isolation(
            target, work / "edit-isolation", completion_result["target_marker_id"], completion_result["independent_path_id"]
        )
    terminal_core_result = None
    if fixture_kind == "observed-terminal-core":
        terminal_core_result = inspect_terminal_core_members(document, objects, cold, work.parent / "controlled-source.png")
        terminal_core_result["scripted_edit_isolation"] = inspect_circle_path_edit_isolation(
            target, work / "edit-isolation", terminal_core_result["target_marker_id"], terminal_core_result["independent_path_id"]
        )
    if single_line_contract not in ("strict-three", "bounded-capability"):
        raise ValueError("Unknown single-line saved-output contract")
    single_line_result = None
    if fixture_kind == "single-line-labels":
        if single_line_contract == "strict-three":
            single_line_result = inspect_single_line_members(document, objects, cold, companion / font["font"])
        else:
            single_line_result = inspect_bounded_single_line_members(document, objects, cold, companion / font["font"], companion / "evidence", work.parent / "controlled-source.png", pipeline_report)
    contact_result = None
    if fixture_kind == "text-line-contact":
        contact_result = inspect_contact_members(document, objects, cold, companion / font["font"])
        contact_result["actual_contact_payloads"] = inspect_contact_payloads(
            objects, cold, companion / "evidence", work.parent / "controlled-source.png",
            companion / font["font"], pipeline_report,
        )
        contact_result["scripted_edit_isolation"] = inspect_contact_edit_isolation(
            target, work / "edit-isolation", contact_result["text_id"], contact_result["independent_contact_path_id"],
        )
    short_code_result = None
    if fixture_kind == "short-codes":
        if source_row_font_spec is None or source_row_fixture_font is None:
            raise AssertionError("Short-code saved check requires its verified packaged registry and original fixture font")
        short_code_result = inspect_short_code_members(
            document, objects, cold, source_row_font_spec, companion, source_path=work.parent / "controlled-source.png",
        )
        short_code_result["actual_source_payloads"] = inspect_short_code_payloads(
            objects, cold, companion / "evidence", work.parent / "controlled-source.png", source_row_fixture_font, pipeline_report, document=document,
        )
        short_code_result["scripted_edit_isolation"] = inspect_contact_edit_isolation(
            target, work / "edit-isolation", short_code_result["text_id"], short_code_result["independent_contact_path_id"],
        )
    entry = json.loads((companion / "result.entry_trace.json").read_text(encoding="utf-8"))
    if entry["mode"] != "native-objects" or entry["legacy_processing_called"] or entry["legacy_export_called"] or entry["source_sha256"] != source_sha:
        raise AssertionError("EXE did not enter the source-bound native pipeline")
    states = list((work / "jobs").glob("*/state.json"))
    if len(states) != 1:
        raise AssertionError("Smoke did not create exactly one real managed task")
    state = json.loads(states[0].read_text(encoding="utf-8"))
    if state["status"] != "COMPLETED_WITH_ISSUES" or state.get("connection_checkpoint") or state.get("checkpoint_import"):
        raise AssertionError("Smoke did not complete ordinary native recognition")
    if state["raw_observation_cache"]["entry_count"] != 0:
        raise AssertionError("Smoke inherited an old recognition cache")
    command = state["attempts"][0]["command"]
    if "--native-worker" not in command or (frozen and (len(command) != 3 or not command[0].lower().endswith(".exe"))):
        raise AssertionError("Native conversion bypassed the actual packaged worker")
    if frozen and "frozen_application_executable" not in state["algorithm"]["files"]:
        raise AssertionError("Packaged native result was not bound to the EXE")
    policies = list((companion / "evidence").rglob("policy_frozen_before_recognition.json"))
    policies = [json.loads(path.read_text(encoding="utf-8")) for path in policies]
    engines = [row["engine"] for row in policies if "engine" in row]
    if not engines:
        raise AssertionError("No actual Tesseract producer evidence was saved")
    if not list((companion / "evidence").rglob("*.tsv")):
        raise AssertionError("No actual raw OCR observation was saved")
    models = [json.loads(path.read_text(encoding="utf-8")) for path in (companion / "evidence").rglob("model_identity.json")]
    if not models or not all(row.get("providers") == ["CPUExecutionProvider"] for row in models):
        raise AssertionError("Native flow did not initialize its bundled independent model")
    global_summary_path = companion / "evidence/cross_engine_text/summary.json"
    global_calls = json.loads(global_summary_path.read_text(encoding="utf-8"))["actual_model_calls"] if global_summary_path.is_file() else 0
    circle_calls = 0
    single_line_calls = pipeline_report.get("single_line_label_recovery", {}).get("new_model_calls", 0)
    if circle_result is not None or curve_end_result is not None:
        payloads = inspect_circular_character_payloads(objects, cold, companion / "evidence", work.parent / "controlled-source.png", pipeline_report)
        (circle_result if circle_result is not None else curve_end_result)["actual_character_payloads"] = payloads
        circle_calls = payloads["new_model_calls"]
    if completion_result is not None or terminal_core_result is not None:
        payloads = inspect_circular_character_payloads(
            objects, cold, companion / "evidence", work.parent / "controlled-source.png", pipeline_report,
            expected_markers=4 if completion_result is not None else 1,
            expected_partial=0 if completion_result is not None else 1,
            require_source_reference_resolution=completion_result is not None,
        )
        (completion_result if completion_result is not None else terminal_core_result)["actual_character_payloads"] = payloads
        circle_calls = payloads["new_model_calls"]
    if single_line_result is not None:
        payloads = inspect_single_line_character_payloads(objects, cold, companion / "evidence", pipeline_report)
        single_line_result["actual_label_payloads"] = payloads
        single_line_calls = payloads["new_model_calls"]
    if (fixture_kind == "room17" and global_calls <= 0) or (fixture_kind in ("circular-markers", "curve-end-boundaries", "circle-character-completion", "observed-terminal-core") and circle_calls <= 0):
        raise AssertionError("Native flow did not execute its independent recognizer")
    snapshot = sorted([entity_geometry(entity, document) for entity in entities], key=lambda row: json.dumps(row, sort_keys=True))
    write_json(work / "geometry.json", {"entities": snapshot})
    result = {
        "dxf_sha256": digest(target),
        "formal_entity_count": len(entities),
        "formal_types": dict(sorted(types.items())),
        "editable_texts": texts,
        "geometry_sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
        "geometry": snapshot,
        "entry_trace": entry,
        "worker_command": command,
        "task_status": state["status"],
        "algorithm": state["algorithm"],
        "tesseract_engines": engines,
        "independent_models": models,
        "actual_independent_model_calls": global_calls + circle_calls + single_line_calls,
        "global_cross_engine_model_calls": global_calls,
        "circle_character_model_calls": circle_calls,
        "single_line_label_model_calls": single_line_calls,
        "initial_raw_observation_count": 0,
        "actual_source_ocr_saved": True,
        "export_font": font,
        "export_fonts": objects.get("fonts", [font]),
        "cold_audit_errors": 0,
        "cold_audit_fixes": 0,
    }
    if circle_result is not None:
        result["circular_markers"] = circle_result
    if single_line_result is not None:
        result["single_line_labels"] = single_line_result
    if contact_result is not None:
        result["text_line_contact"] = contact_result
    if short_code_result is not None:
        result["short_codes"] = short_code_result
    if curve_end_result is not None:
        result["curve_end_boundaries"] = curve_end_result
    if completion_result is not None:
        result["circle_character_completion"] = completion_result
    if terminal_core_result is not None:
        result["observed_terminal_core"] = terminal_core_result
    return result


def run_cli(command: list[str], source: Path, work: Path, environment: dict) -> None:
    work.mkdir()
    arguments = command + [
        "--headless", "--mode", "native-objects", "--input", str(source),
        "--roi", "0", "0", "640", "480", "--dpi", "200", "--orientation", "0",
        "--output", str(work / "native.dxf"), "--jobs-dir", str(work / "jobs"),
        "--cpu-seconds", "300", "--wall-seconds", "360", "--verbose",
    ]
    write_json(work / "command.json", {"arguments": arguments, "started_unix": time.time()})
    with (work / "stdout.txt").open("w", encoding="utf-8") as out, (work / "stderr.txt").open("w", encoding="utf-8") as err:
        process = subprocess.run(arguments, cwd=work, env=environment, stdout=out, stderr=err, timeout=400, check=False)
    write_json(work / "process.json", {"exit_code": process.returncode, "finished_unix": time.time()})
    if process.returncode:
        raise RuntimeError(f"Actual native CLI failed: {process.returncode}; evidence retained in {work}")


def clean_environment() -> dict:
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "I2CAD_RAW_OBSERVATION_CACHE", "I2CAD_TESSERACT", "TESSDATA_PREFIX", "I2CAD_JOBS_ROOT"):
        environment.pop(key, None)
    environment.update(OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONNOUSERSITE="1")
    return environment


def _verify_bundle_resources(result: dict, bundle: Path) -> None:
    for engine in result["tesseract_engines"]:
        if not Path(engine["executable"]).resolve().is_relative_to(bundle):
            raise AssertionError("EXE used an external Tesseract installation")
    for model in result["independent_models"]:
        if not Path(model["model_path"]).resolve().is_relative_to(bundle):
            raise AssertionError("EXE used a model outside its bundle")
    for font in result.get("export_fonts", [result["export_font"]]):
        if not Path(font["source"]).resolve().is_relative_to(bundle):
            raise AssertionError("EXE used an export font outside its bundle")


def run(executable: Path, source_main: Path, work: Path, expected_version: str) -> dict:
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    progress = {"schema": "windows-native-smoke-progress-v1", "completed": [], "active_case": None, "active_stage": "prepare-package"}

    def stage(case, name, *, complete=False):
        progress.update(active_case=case, active_stage=name)
        if complete:
            progress["completed"].append({"case": case, "stage": name})
        write_json(work / "native-smoke-progress.json", progress)

    stage(None, "prepare-package")
    app_root = source_main.resolve().parent
    original_executable = executable.resolve()
    package = work / "detached-package"
    shutil.copytree(original_executable.parent, package)
    executable = package / original_executable.name
    bundle = package / "_internal"
    # Keep the actual built metadata beside the small smoke evidence so it can
    # be cold-read without downloading the much larger application package.
    metadata_files = (
        "resources/native-build.json",
        "resources/ocr/tesseract/native-ocr.lock.json",
        "resources/fonts/source-row-font.lock.json",
        "docs/product/product_status.generated.json",
    )
    for relative in metadata_files:
        shutil.copyfile(bundle / relative, work / Path(relative).name)
    manifest = json.loads((bundle / "resources/native-build.json").read_text(encoding="utf-8"))
    product = json.loads((bundle / "docs/product/product_status.generated.json").read_text(encoding="utf-8"))
    if manifest["application_version"] != expected_version or product["status"] != "LOCAL_NO_GO" or product["running_pipeline"] != "native-objects":
        raise AssertionError("Packaged product metadata has wrong version")
    for relative, expected in manifest["application_sources"].items():
        if digest(app_root / relative) != expected or digest(bundle / relative) != expected:
            raise AssertionError("Packaged code evidence differs from same-version source: " + relative)
    source_row_font_spec = read_source_row_font_spec(bundle)
    source_row_fixture_font = read_source_row_fixture_font(bundle)
    circular_work = work / "circular-markers"
    circular_work.mkdir()
    single_line_work = work / "single-line-labels"
    single_line_work.mkdir()
    contact_work = work / "text-line-contact"
    contact_work.mkdir()
    short_code_work = work / "short-codes"
    short_code_work.mkdir()
    curve_end_work = work / "curve-end-boundaries"
    curve_end_work.mkdir()
    completion_work = work / "circle-character-completion"
    completion_work.mkdir()
    terminal_core_work = work / "observed-terminal-core"
    terminal_core_work.mkdir()
    cases = [
        {"name": "room17", "directory": work, "create": create_fixture},
        {"name": "circular-markers", "directory": circular_work, "create": create_circular_fixture},
        {"name": "single-line-labels", "directory": single_line_work, "create": create_single_line_fixture},
        {"name": "text-line-contact", "directory": contact_work, "create": create_contact_fixture},
        {"name": "short-codes", "directory": short_code_work, "create": create_short_code_fixture},
        {"name": "curve-end-boundaries", "directory": curve_end_work, "create": create_curve_end_boundary_fixture},
        {"name": "circle-character-completion", "directory": completion_work, "create": create_circle_character_completion_fixture},
        {"name": "observed-terminal-core", "directory": terminal_core_work, "create": create_terminal_core_fixture},
    ]
    environment = clean_environment()
    for case in cases:
        fixture = case["directory"] / "controlled-source.png"
        if case["name"] == "short-codes":
            case["create"](fixture, bundle / "resources/fonts/DejaVuSans.ttf", source_row_fixture_font)
        else:
            case["create"](fixture, bundle / "resources/fonts/DejaVuSans.ttf")
        case.update(fixture=fixture, source_sha256=digest(fixture))
        stage(case["name"], "source-recognition")
        run_cli([sys.executable, str(source_main.resolve())], fixture, case["directory"] / "source-run", environment)
        stage(case["name"], "source-saved-audit")
        case["source_result"] = inspect_result(case["directory"] / "source-run", case["source_sha256"], frozen=False, fixture_kind=case["name"], single_line_contract="bounded-capability" if case["name"] == "single-line-labels" else "strict-three", source_row_font_spec=source_row_font_spec, source_row_fixture_font=source_row_fixture_font)
        stage(case["name"], "source-saved-audit", complete=True)
    # Only this controlled CI checkout is hidden, and always restored. The
    # helper, fixture and detached bundle are outside it before this point.
    if app_root in work.parents or Path(__file__).resolve().is_relative_to(app_root):
        raise ValueError("Run the smoke helper and evidence outside the source directory")
    hidden = app_root.with_name(app_root.name + ".native-smoke-hidden-" + uuid.uuid4().hex)
    app_root.rename(hidden)
    try:
        if app_root.exists():
            raise AssertionError("Original application source is still available")
        for case in cases:
            profile = case["directory"] / "clean-user-profile"
            profile.mkdir()
            exe_environment = dict(environment)
            exe_environment.update(
                PATH=str(Path(os.environ["SystemRoot"]) / "System32") + os.pathsep + os.environ["SystemRoot"],
                USERPROFILE=str(profile), APPDATA=str(profile / "AppData/Roaming"),
                LOCALAPPDATA=str(profile / "AppData/Local"),
            )
            exe_environment.pop("HOME", None)
            for key in ("APPDATA", "LOCALAPPDATA"):
                Path(exe_environment[key]).mkdir(parents=True)
            stage(case["name"], "packaged-exe-recognition")
            run_cli([str(executable)], case["fixture"], case["directory"] / "exe-run", exe_environment)
            stage(case["name"], "packaged-exe-saved-audit")
            case["exe_result"] = inspect_result(case["directory"] / "exe-run", case["source_sha256"], frozen=True, fixture_kind=case["name"], single_line_contract="bounded-capability" if case["name"] == "single-line-labels" else "strict-three", source_row_font_spec=source_row_font_spec, source_row_fixture_font=source_row_fixture_font)
            stage(case["name"], "packaged-exe-saved-audit", complete=True)
    finally:
        hidden.rename(app_root)
    for case in cases:
        stage(case["name"], "source-exe-comparison")
        if case["source_result"]["geometry"] != case["exe_result"]["geometry"]:
            raise AssertionError("Packaged native geometry/text differs from same-version source; both actual DXFs retained")
        if digest(case["fixture"]) != case["source_sha256"]:
            raise AssertionError("Native conversion changed the generated input")
        _verify_bundle_resources(case["exe_result"], bundle)
        for result in (case["source_result"], case["exe_result"]):
            result.pop("geometry")
        stage(case["name"], "source-exe-comparison", complete=True)
    room, circles, single_lines, contact, short_codes, curve_ends, circle_completion, terminal_core = cases
    circle_report = {
        "status": "PASS", "schema": "windows-native-circular-markers-smoke-v2",
        "source_commit": manifest["source_commit"], "source_sha256": circles["source_sha256"],
        "source_result": circles["source_result"], "exe_result": circles["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "independent_complete_marker_definitions": True,
        "partial_border_not_counted_as_complete_marker": True,
        "ordinary_round_glyphs_not_exported_as_circles": True,
        "actual_finite_lead_circle_contacts_checked": True,
        "independent_real_source_gap_preserved": True,
        "expected_text_sent_to_recognizer": False,
        "product_GO": False,
    }
    write_json(circular_work / "native-smoke.json", circle_report)
    single_line_report = {
        "status": "PASS", "schema": "windows-native-single-line-labels-smoke-v2",
        "status_scope": "SUPPORTED_CAPABILITY_WITH_EXPLICIT_COMPLETE_AND_PENDING_LABEL_COUNTS",
        "source_commit": manifest["source_commit"], "source_sha256": single_lines["source_sha256"],
        "source_result": single_lines["source_result"], "exe_result": single_lines["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "strict_three_complete_status": single_lines["exe_result"]["single_line_labels"]["strict_three_complete_status"],
        "complete_count": single_lines["exe_result"]["single_line_labels"]["complete_count"],
        "pending_count": single_lines["exe_result"]["single_line_labels"]["pending_count"],
        "new_recovery_count": single_lines["exe_result"]["single_line_labels"]["new_recovery_count"],
        "supported_capability_pass": True,
        "complete_output_strings_each_one_editable_TEXT": True,
        "pending_labels_not_counted_as_complete": True,
        "actual_saved_content_and_layout_checked": True,
        "new_recovery_source_evidence_replayed": True,
        "independent_neighbor_lines_short_stroke_and_ordinary_text_preserved": True,
        "unchanged_circular_case_also_required": True,
        "expected_text_sent_to_recognizer": False,
        "generated_fixture_not_real_drawing_quality_acceptance": True,
        "product_GO": False,
    }
    write_json(single_line_work / "native-smoke.json", single_line_report)
    contact_report = {
        "status": "PASS", "schema": "windows-native-text-line-contact-smoke-v1",
        "source_commit": manifest["source_commit"], "source_sha256": contact["source_sha256"],
        "source_result": contact["source_result"], "exe_result": contact["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "complete_locations": 1, "new_complete_TEXT_objects": 1,
        "new_complete_independent_graphic_objects": 1,
        "actual_new_contact_partition_and_saved_path_source_audit_required": True,
        "independent_underline_short_stroke_and_correct_text_preserved": True,
        "actual_scripted_edit_save_reopen_isolation_checked": True,
        "GUI_operations_claimed": False,
        "expected_text_sent_to_recognizer": False,
        "generated_fixture_not_real_drawing_quality_acceptance": True,
        "original_strict_three_label_goal_status": single_line_report["strict_three_complete_status"],
        "product_GO": False,
    }
    write_json(contact_work / "native-smoke.json", contact_report)
    short_code_report = {
        "status": "PASS", "schema": "windows-native-source-row-short-code-smoke-v1",
        "source_commit": manifest["source_commit"], "source_sha256": short_codes["source_sha256"],
        "fixed_original_fixture_font_sha256": digest(source_row_fixture_font),
        "source_result": short_codes["source_result"], "exe_result": short_codes["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "complete_labels": 1, "complete_independent_contact_paths": 1,
        "actual_default_white_gap_failure_and_source_component_fallback_required": True,
        "actual_saved_nonempty_round_and_source_component_checks_required": True,
        "new_TTF_LFF_and_full_license_match_packaged_registry": True,
        "actual_saved_literal_LFF_outline_and_advance_check_required": True,
        "existing_control_font_style_kept": True,
        "actual_scripted_edit_save_reopen_isolation_checked": True,
        "GUI_operations_claimed": False, "expected_text_sent_to_recognizer": False,
        "original_strict_three_label_goal_status": single_line_report["strict_three_complete_status"],
        "generated_fixture_not_real_drawing_quality_acceptance": True, "product_GO": False,
    }
    write_json(short_code_work / "native-smoke.json", short_code_report)
    curve_end_report = {
        "status": "PASS", "schema": "windows-native-curve-end-boundaries-smoke-v1",
        "source_commit": manifest["source_commit"], "source_sha256": curve_ends["source_sha256"],
        "source_result": curve_ends["source_result"], "exe_result": curve_ends["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "paired_original_stroke_edge_fallback_required_in_saved_circle": True,
        "uncertain_inner_character_not_counted_as_complete": True,
        "independent_complete_contact_path_and_true_white_gap_required": True,
        "actual_saved_circle_full_sweep_and_finite_contact_checked": True,
        "actual_scripted_block_move_delete_text_edit_and_path_delete_checked": True,
        "all_independent_neighbors_unchanged_after_save_reopen": True,
        "previous_five_inputs_preserved": True,
        "GUI_operations_claimed": False, "expected_text_sent_to_recognizer": False,
        "generated_fixture_not_real_drawing_quality_acceptance": True, "product_GO": False,
    }
    write_json(curve_end_work / "native-smoke.json", curve_end_report)
    completion_report = {
        "status": "PASS", "schema": "windows-native-circle-character-completion-smoke-v1",
        "source_commit": manifest["source_commit"], "source_sha256": circle_completion["source_sha256"],
        "source_result": circle_completion["source_result"], "exe_result": circle_completion["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "original_failed_two_engine_decision_and_raw_readings_retained": True,
        "two_independent_original_glyph_references_and_competing_class_checked": True,
        "actual_saved_source_reference_resolution_required": True,
        "each_circle_and_TEXT_one_unique_editable_block": True,
        "independent_paths_and_original_white_gap_preserved": True,
        "scripted_block_text_edit_move_delete_and_path_delete_checked": True,
        "GUI_operations_claimed": False, "expected_text_sent_to_recognizer": False,
        "generated_fixture_not_real_drawing_quality_acceptance": True, "product_GO": False,
    }
    write_json(completion_work / "native-smoke.json", completion_report)
    terminal_core_report = {
        "status": "PASS", "schema": "windows-native-observed-terminal-core-smoke-v1",
        "source_commit": manifest["source_commit"], "source_sha256": terminal_core["source_sha256"],
        "source_result": terminal_core["source_result"], "exe_result": terminal_core["exe_result"],
        "same_source_saved_geometry_and_text_equal": True,
        "new_observed_core_transfer_required_in_actual_saved_path": True,
        "original_whole_path_vertices_retained": True,
        "complete_main_connection_and_other_pending_branches_separately_reported": True,
        "whole_path_delete_leaves_no_added_terminal_fragment": True,
        "original_white_gap_and_independent_neighbors_preserved": True,
        "GUI_operations_claimed": False, "expected_text_sent_to_recognizer": False,
        "generated_fixture_not_real_drawing_quality_acceptance": True, "product_GO": False,
    }
    write_json(terminal_core_work / "native-smoke.json", terminal_core_report)
    report = {
        "status": "PASS", "schema": "windows-native-exe-smoke-v1",
        "coverage_revision": 9,
        "status_scope": "REQUIRED_NATIVE_CAPABILITY_GATES; STRICT_THREE_LABEL_GOAL_REPORTED_SEPARATELY",
        "application_version": expected_version, "source_commit": manifest["source_commit"],
        "packaged_metadata_sha256": {Path(name).name: digest(work / Path(name).name) for name in metadata_files},
        "source_sha256": room["source_sha256"], "executable_sha256": digest(executable),
        "same_source_saved_geometry_and_text_equal": True,
        "source_result": room["source_result"], "exe_result": room["exe_result"],
        "additional_fixtures": {"circular_markers": circle_report, "single_line_labels": single_line_report, "text_line_contact": contact_report, "short_codes": short_code_report, "curve_end_boundaries": curve_end_report, "circle_character_completion": completion_report, "observed_terminal_core": terminal_core_report},
        "original_application_source_hidden_during_EXE_execution": True,
        "source_directory_restored": app_root.is_dir(),
        "EXE_PATH_contains_only_windows_system_directories": True,
        "EXE_clean_user_profile": True,
        "bundled_source_audit_resources_match_checkout": True,
        "explicit_cache_or_adoption_whitelist": False,
        "expected_text_sent_to_recognizer": False,
        "generated_controlled_input_only_not_real_drawing_quality_acceptance": True,
        "product_GO": False,
    }
    write_json(work / "native-smoke.json", report)
    stage(None, "all-required-capability-gates-passed", complete=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--source-main", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    try:
        report = run(args.executable, args.source_main, args.work_dir, args.expected_version)
    except BaseException as exc:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        progress_path = args.work_dir / "native-smoke-progress.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.is_file() else None
        write_json(args.work_dir / "native-smoke-failure.json", {"status": "FAILED", "type": type(exc).__name__, "message": str(exc), "progress": progress, "product_GO": False})
        raise
    print(json.dumps({key: report[key] for key in ("status", "source_commit", "source_sha256", "same_source_saved_geometry_and_text_equal")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
