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


def inspect_circular_members(document, objects: dict, cold: dict) -> dict:
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
        if not _near_point(_pixel_point(circle.dxf.center), center) or abs(float(circle.dxf.radius) * 200 / 25.4 - 25) > 2:
            raise AssertionError("Saved circle location or radius differs from its source border")
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
        contact_tolerance = 3.0 / 2 + 2.5
        contact, end = (center[0] + radius, center[1]), (center[0] + 130, center[1])
        matching = []
        for entity in formal:
            points = _line_points(entity)
            if len(points) < 2:
                continue
            near_endpoint_number = int(points[0][0] > points[-1][0])
            if near_endpoint_number:
                points.reverse()
            if _near_point(points[0], contact, contact_tolerance) and _near_point(points[-1], end) and all(abs(point[1] - center[1]) <= 2 for point in points) and all(right[0] > left[0] for left, right in zip(points, points[1:])):
                oid = native_identity(entity)["id"]
                support = _saved_line_source_check(cold, oid)
                signed_gap = math.dist(points[0], actual_center) - radius
                intersections = _finite_circle_intersections(points, actual_center, radius)
                if signed_gap > 1e-6 or signed_gap < -contact_tolerance or not intersections:
                    raise AssertionError("Saved finite lead does not contact its circle or exceeds the supported overlap band")
                certificate = rows.get(oid, {}).get("source_evidence", {}).get("circle_endpoint_contacts")
                new_contacts = []
                if certificate is not None:
                    if certificate.get("schema") != "native-direct-circle-end-contact-v1" or not isinstance(certificate.get("ends"), list):
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
                lead_reports.append({"id": oid, "actual_circle_center_px": list(actual_center), "circle_radius_px": radius, "source_stroke_width_px": 3.0, "saved_source_budget_px": 2.5, "shared_contact_half_band_px": contact_tolerance, "actual_start_px": list(points[0]), "actual_end_px": list(points[-1]), "signed_endpoint_gap_px": signed_gap, "finite_geometry_intersections_px": intersections, "contact_kind": "existing_supported_ring_overlap" if signed_gap < -1e-6 else "endpoint_on_circle", "new_certified_endpoint_checked": bool(new_contacts), "positive_CAD_gap_tolerance_px": 1e-6, "character_source_box_preserved": True, "saved_source_check": support})
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
        if not (_near_point(points[0], (290, 330)) and _near_point(points[-1], (371, 330)) and all(abs(point[1] - 330) <= 2 for point in points) and all(right[0] > left[0] for left, right in zip(points, points[1:]))):
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
    return {
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


def inspect_circular_character_payloads(objects, cold, evidence_root: Path, source_path: Path, pipeline_report) -> dict:
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
    if (summary.get("new_complete_markers") != 2 or summary.get("circle_text_compositions") != 2
            or summary.get("circle_text_compositions_with_external_contacts_pending") != 0
            or summary.get("new_partial_boundaries") != 1 or summary.get("partial_compositions") != 1):
        raise AssertionError("Ordinary pipeline summary does not separate two complete markers from the partial border")
    with Image.open(source_path) as image:
        original = np.asarray(image.convert("L"))
    checks = {row["id"]: row for row in cold["circular_marker_source_checks"]}
    verified = []
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
        if hashlib.sha256(crop.tobytes()).hexdigest() != evidence["source_crop_array_sha256"] or evidence["text_geometry"] != obj["geometry"]["text_geometry"] or evidence["decision"].get("accepted") is not True:
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
        verified.append({"id": obj["id"], "text": evidence["decision"]["text"], "new_Tesseract_calls": t_calls, "new_model_calls": p_calls, "Tesseract_views": len(t_views), "PP_OCR_views": len(p_views)})
    if len(verified) != 2:
        raise AssertionError("Not every complete marker has verified original character payloads")
    return {"verified_complete_characters": verified, "raw_stage_files_read_and_hashed": len(payloads), "new_Tesseract_calls": actual_tesseract, "new_model_calls": actual_model, "global_cross_engine_calls_required": False, "inspection_executed_recognition": False}


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


def inspect_result(work: Path, source_sha: str, *, frozen: bool, fixture_kind: str = "room17") -> dict:
    import ezdxf

    target = work / "native.dxf"
    document = ezdxf.readfile(target)
    audit = document.audit()
    if audit.errors or audit.fixes or document.units != 4:
        raise AssertionError("Actual saved DXF failed cold audit/paper-mm units")
    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    types = Counter(entity.dxftype() for entity in entities)
    if fixture_kind not in ("room17", "circular-markers"):
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
    circle_result = inspect_circular_members(document, objects, cold) if fixture_kind == "circular-markers" else None
    if circle_result is not None:
        circle_result["original_real_gap_evidence"] = inspect_circular_fixture_source_gap(work.parent / "controlled-source.png")
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
    if circle_result is not None:
        pipeline_report = json.loads((companion / "result.report.json").read_text(encoding="utf-8"))
        payloads = inspect_circular_character_payloads(objects, cold, companion / "evidence", work.parent / "controlled-source.png", pipeline_report)
        circle_result["actual_character_payloads"] = payloads
        circle_calls = payloads["new_model_calls"]
    if (fixture_kind == "room17" and global_calls <= 0) or (fixture_kind == "circular-markers" and circle_calls <= 0):
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
        "actual_independent_model_calls": global_calls + circle_calls,
        "global_cross_engine_model_calls": global_calls,
        "circle_character_model_calls": circle_calls,
        "initial_raw_observation_count": 0,
        "actual_source_ocr_saved": True,
        "export_font": font,
        "cold_audit_errors": 0,
        "cold_audit_fixes": 0,
    }
    if circle_result is not None:
        result["circular_markers"] = circle_result
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
    if not Path(result["export_font"]["source"]).resolve().is_relative_to(bundle):
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
    circular_work = work / "circular-markers"
    circular_work.mkdir()
    cases = [
        {"name": "room17", "directory": work, "create": create_fixture},
        {"name": "circular-markers", "directory": circular_work, "create": create_circular_fixture},
    ]
    environment = clean_environment()
    for case in cases:
        fixture = case["directory"] / "controlled-source.png"
        case["create"](fixture, bundle / "resources/fonts/DejaVuSans.ttf")
        case.update(fixture=fixture, source_sha256=digest(fixture))
        stage(case["name"], "source-recognition")
        run_cli([sys.executable, str(source_main.resolve())], fixture, case["directory"] / "source-run", environment)
        stage(case["name"], "source-saved-audit")
        case["source_result"] = inspect_result(case["directory"] / "source-run", case["source_sha256"], frozen=False, fixture_kind=case["name"])
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
            case["exe_result"] = inspect_result(case["directory"] / "exe-run", case["source_sha256"], frozen=True, fixture_kind=case["name"])
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
    room, circles = cases
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
    report = {
        "status": "PASS", "schema": "windows-native-exe-smoke-v1",
        "coverage_revision": 3,
        "application_version": expected_version, "source_commit": manifest["source_commit"],
        "packaged_metadata_sha256": {Path(name).name: digest(work / Path(name).name) for name in metadata_files},
        "source_sha256": room["source_sha256"], "executable_sha256": digest(executable),
        "same_source_saved_geometry_and_text_equal": True,
        "source_result": room["source_result"], "exe_result": room["exe_result"],
        "additional_fixtures": {"circular_markers": circle_report},
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
    stage(None, "all-fixtures-passed", complete=True)
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
