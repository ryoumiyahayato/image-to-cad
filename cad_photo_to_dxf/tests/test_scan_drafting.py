"""Drafting rules through the public entry and the actual saved CAD objects."""
from __future__ import annotations

import json

import cv2
import ezdxf
import numpy as np
import pytest
from PIL import Image

from app.core import scan_conversion
from app.core.conversion import convert_document
from app.core.scan_quality import check_saved_scan, source_reference
from app.ocr.line_recognition import RecognizedLine


def _record_data(record):
    return json.loads("".join(tag.value for tag in record.tags if tag.code == 1))


def _evidence(entity):
    return _record_data(entity.get_extension_dict()["SOURCE_EVIDENCE"])


def _convert(tmp_path, image, *, scale=1, ocr=False):
    source = tmp_path / "drawing.png"
    Image.fromarray(image[:, :, ::-1]).save(source)
    report = convert_document(source, tmp_path / "drawing.dxf", enable_ocr=ocr,
                              dpi=300, drawing_scale=scale)
    page = report["outputs"][0]
    doc = ezdxf.readfile(page["output"])
    origin = _record_data(doc.rootdict["IMAGE_TO_CAD"]["PAGE_SOURCE"])
    assert origin["source"] == str(source)
    assert origin["page_index"] == 0
    assert origin["image_size_px"] == [image.shape[1], image.shape[0]]
    assert origin["dpi"] == 300 and origin["drawing_scale"] == scale
    assert origin["coordinate_frame"] == "source_page_pixels"
    assert origin["pack"] == page["drafting"]["pack"]
    assert origin["version"] == page["drafting"]["version"]
    for entity in doc.modelspace():
        if entity.dxf.layer not in {"GEOMETRY", "TEXT"}:
            continue
        evidence = _evidence(entity)
        role = entity.dxf.layer.lower()
        assert [(tag.code, tag.value) for tag in entity.get_xdata("IMAGE_TO_CAD")] == [
            (1000, origin["pack"]), (1000, origin["version"]), (1000, role), (1071, 0)]
        assert evidence["page_index"] == 0 and evidence["role"] == role
        if role == "geometry":
            assert evidence["source_indices"]
            assert all(0 <= index < origin["input_candidates"] for index in evidence["source_indices"])
            x0, y0, x1, y1 = evidence["source_bounds_px"]
            assert 0 <= x0 <= x1 < image.shape[1] and 0 <= y0 <= y1 < image.shape[0]
            assert isinstance(evidence["rules"], list) and evidence["stroke_width_px"] > 0
        else:
            assert np.asarray(evidence["quad_px"]).shape == (4, 2)
            assert .7 <= evidence["confidence"] <= 1
    return page, doc


def _pixel_ends(entity, height, scale=1):
    factor = scale * 25.4 / 300
    return np.array([(p.x / factor, height - p.y / factor)
                     for p in (entity.dxf.start, entity.dxf.end)])


def _has_line(lines, first, last, *, tolerance=1.5):
    expected = np.array([first, last], float)
    return any(min(np.max(np.linalg.norm(points - expected, axis=1)),
                   np.max(np.linalg.norm(points[::-1] - expected, axis=1))) <= tolerance
               for points in lines)


@pytest.mark.parametrize("junction", ["elbow", "tee", "cross", "diagonal"])
@pytest.mark.parametrize("scale", [1, 100])
def test_public_entry_resolves_junctions_into_continuous_native_lines(tmp_path, junction, scale):
    image = np.full((260, 420, 3), 255, np.uint8)
    if junction == "diagonal":
        expected = [((70, 30), (270, 230)), ((70, 230), (270, 30))]
    elif junction == "elbow":
        expected = [((30, 130), (210, 130)), ((210, 30), (210, 130))]
    else:
        expected = [((30, 130), (390, 130)),
                    ((210, 30), (210, 130 if junction == "tee" else 230))]
    for start, end in expected:
        cv2.line(image, start, end, (0, 0, 0), 1)
    page, doc = _convert(tmp_path, image, scale=scale)
    lines = [_pixel_ends(entity, image.shape[0], scale)
             for entity in doc.modelspace().query("LINE")]
    assert all(_has_line(lines, start, end) for start, end in expected)
    assert len(lines) == len(expected), "A source line must not remain fragmented at its crossing"
    assert page["drafting"]
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    if junction == "diagonal":
        # The minimum standard pen is wider than a 1px diagonal at 300dpi.
        # Compare with independently authored ideal CAD, without relaxing QA.
        ideal = ezdxf.new("R2013")
        ideal.layers.new("GEOMETRY")
        factor = scale * 25.4 / 300
        for start, end in expected:
            ideal.modelspace().add_line((start[0]*factor, (image.shape[0]-start[1])*factor),
                                        (end[0]*factor, (image.shape[0]-end[1])*factor),
                                        dxfattribs={"layer": "GEOMETRY", "lineweight": 13})
        ideal_file = tmp_path / "ideal.dxf"
        ideal.saveas(ideal_file)
        reference = source_reference(image, np.zeros(image.shape[:2], np.uint8), [], [])
        ideal_quality, _ = check_saved_scan(ideal_file, reference, [], dpi=300, drawing_scale=scale)
        assert page["quality"]["geometry"]["extra_pixels"] == ideal_quality["geometry"]["extra_pixels"]
    else:
        assert page["quality"]["geometry"]["extra_pixels"] == 0
    assert not doc.modelspace().query('*[layer=="SUGGEST_REPAIR"]'), "Ordinary junctions are formal geometry"
    assert not doc.audit().errors


@pytest.mark.parametrize("origin,spacing", [((35, 25), (125, 75)), ((80, 55), (90, 60))])
def test_table_rules_span_the_grid_and_keep_exact_intersections(tmp_path, origin, spacing):
    image = np.full((360, 560, 3), 255, np.uint8)
    x0, y0 = origin
    dx, dy = spacing
    xs = [x0 + i*dx for i in range(4)]
    ys = [y0 + i*dy for i in range(4)]
    expected = [((x, ys[0]), (x, ys[-1])) for x in xs]
    expected += [((xs[0], y), (xs[-1], y)) for y in ys]
    for start, end in expected:
        cv2.line(image, start, end, (0, 0, 0), 1)
    page, doc = _convert(tmp_path, image)
    lines = [_pixel_ends(e, image.shape[0]) for e in doc.modelspace().query("LINE")]
    assert len(lines) == len(expected)
    assert all(_has_line(lines, start, end, tolerance=.1) for start, end in expected)
    assert any(len(_evidence(e)["source_indices"]) > 1 for e in doc.modelspace().query("LINE"))
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    assert page["quality"]["geometry"]["extra_pixels"] == 0
    assert len(doc.groups) == 0, "A whole table is not an equipment symbol"


def test_wide_source_rule_round_trips_with_native_width(tmp_path):
    image = np.full((260, 500, 3), 255, np.uint8)
    image[70:110, 60:440] = 0
    page, doc = _convert(tmp_path, image, scale=5)
    wide = doc.modelspace().query('LWPOLYLINE[layer=="GEOMETRY"]')
    assert wide and all(entity.dxf.const_width > 30 * 25.4 / 300 * 5 for entity in wide)
    assert all(_evidence(entity)["source_indices"] for entity in wide)
    checks = page["quality"]["geometry"]
    assert checks["missing_pixels"] < 1600
    assert checks["extra_pixels"] == checks["outside_page_entities"] == 0
    assert checks["tolerance_px"] == 1


def test_repair_alternatives_are_hidden_and_excluded_from_saved_quality(tmp_path):
    image = np.full((150, 180, 3), 255, np.uint8)
    for first, last in (((20, 76), (76, 76)), ((81, 76), (150, 76)), ((79, 25), (79, 73))):
        cv2.line(image, first, last, (0, 0, 0), 1)
    page, doc = _convert(tmp_path, image)
    layer = doc.layers.get("SUGGEST_REPAIR")
    assert layer.is_frozen()
    assert doc.layers.get("REVIEW_SOURCE").is_frozen()
    formal = [_pixel_ends(line, 150) for line in doc.modelspace().query('LINE[layer=="GEOMETRY"]')]
    assert len(formal) == 3
    assert _has_line(formal, (20, 76), (76, 76))
    assert _has_line(formal, (81, 76), (150, 76))
    proposals = doc.modelspace().query('LWPOLYLINE[layer=="SUGGEST_REPAIR"]')
    evidence = [_evidence(proposal) for proposal in proposals]
    assert page["drafting"]["repair_suggestions"] == len(proposals) == 3
    assert [record["reason"] for record in evidence].count("possible_junction") == 2
    assert [record["reason"] for record in evidence].count("broken_stroke") == 1
    for entity, record in zip(proposals, evidence):
        assert entity.get_xdata("IMAGE_TO_CAD")[2].value == "suggest_repair"
        assert record["uncertainty"] == "unconfirmed"
        assert len(record["source_indices"]) == 2
    reference = source_reference(image, np.zeros(image.shape[:2], np.uint8), [], [])
    layer.thaw()
    doc.saveas(page["output"])
    checks, _ = check_saved_scan(page["output"], reference, [], dpi=300)
    assert checks == page["quality"]


@pytest.mark.parametrize("length,rise", [(60, 2), (100, 8)])
@pytest.mark.parametrize("major,sign", [(0, 1), (0, -1), (1, 1), (1, -1)])
def test_shallow_drawn_incline_keeps_its_direction(tmp_path, length, rise, major, sign):
    image = np.full((220, 220, 3), 255, np.uint8)
    start = np.array([60, 60])
    displacement = np.zeros(2, dtype=int)
    displacement[major] = length
    displacement[1-major] = sign * rise
    end = start + displacement
    cv2.line(image, tuple(start), tuple(end), (0, 0, 0), 3)
    _, doc = _convert(tmp_path, image)
    entity, = doc.modelspace().query("LINE")
    points = _pixel_ends(entity, image.shape[0])
    points = points[np.argsort(points[:, major])]
    # Thick rounded raster caps can shorten the fitted centreline slightly;
    # they cannot erase the independently drawn change in its other axis.
    assert np.max(abs(points - np.array([start, end]))) <= 3
    assert points[1, major] - points[0, major] >= length - 6
    assert sign * (points[1, 1-major] - points[0, 1-major]) >= rise * .5


def test_orthogonal_grid_remains_regular_despite_raster_corner_steps(tmp_path):
    image = np.full((220, 220, 3), 255, np.uint8)
    xs = [40, 70, 100, 130, 160]
    ys = [30, 60, 90, 120, 150]
    expected = [((x, ys[0]), (x, ys[-1])) for x in xs]
    expected += [((xs[0], y), (xs[-1], y)) for y in ys]
    # Rounded thick-line intersections create short off-axis skeleton steps,
    # while the engineering rules themselves are exactly horizontal/vertical.
    for start, end in expected:
        cv2.line(image, start, end, (0, 0, 0), 3)
    page, doc = _convert(tmp_path, image)
    entities = list(doc.modelspace().query("LINE"))
    lines = [_pixel_ends(e, image.shape[0]) for e in entities]
    assert len(lines) == len(expected)
    assert all(_has_line(lines, start, end, tolerance=.1) for start, end in expected)
    assert {e.dxf.lineweight for e in entities} == {50}
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    ideal = ezdxf.new("R2013")
    ideal.layers.new("GEOMETRY")
    factor = 25.4 / 300
    for start, end in expected:
        ideal.modelspace().add_line((start[0]*factor, (image.shape[0]-start[1])*factor),
                                    (end[0]*factor, (image.shape[0]-end[1])*factor),
                                    dxfattribs={"layer": "GEOMETRY", "lineweight": 50})
    ideal_file = tmp_path / "ideal-grid.dxf"
    ideal.saveas(ideal_file)
    reference = source_reference(image, np.zeros(image.shape[:2], np.uint8), [], [])
    ideal_quality, _ = check_saved_scan(ideal_file, reference, [], dpi=300)
    # A proven corner uses the same physical standard pen as ideal native CAD;
    # third-layer QA still reports that pen's unavoidable raster corner cost.
    assert page["quality"]["geometry"]["extra_pixels"] == ideal_quality["geometry"]["extra_pixels"]


def test_shallow_l_edge_is_not_granted_an_orthogonal_corner_exception(tmp_path):
    image = np.full((170, 160, 3), 255, np.uint8)
    cv2.polylines(image, [np.array([[40, 40], [100, 42], [100, 120]], np.int32)],
                  False, (0, 0, 0), 3)
    page, doc = _convert(tmp_path, image)
    segments = []
    for entity in doc.modelspace().query('*[layer=="GEOMETRY"]'):
        if entity.dxftype() == "LINE":
            points = _pixel_ends(entity, image.shape[0])
        else:
            assert entity.dxftype() == "LWPOLYLINE"
            points = np.array(entity.get_points("xy")) * 300/25.4
            points[:, 1] = image.shape[0] - points[:, 1]
        segments.extend(np.diff(points, axis=0))
    shallow_edges = [delta for delta in segments if abs(delta[0]) >= 50]
    assert shallow_edges and all(abs(delta[1]) >= 1 for delta in shallow_edges)
    assert page["drafting"]["geometry"]["corner_pen_normalizations"] == 0


@pytest.mark.parametrize("pens,measured_widths", [((25, 50), (4.3, 4.6)),
                                                ((50, 100), (8.7, 9.1))])
def test_collinear_segments_keep_their_distinct_standard_pens(
        tmp_path, monkeypatch, pens, measured_widths):
    image = np.full((160, 280, 3), 255, np.uint8)
    endpoints = [((30, 80), (110, 80)), ((110, 80), (230, 80))]
    candidates = []
    for points, pen, measured_width in zip(endpoints, pens, measured_widths):
        cv2.line(image, points[0], points[1], (0, 0, 0), round(pen*300/2540))
        candidates.append({"type": "LINE", "points": points,
                           "stroke_width": measured_width, "source_path": np.array(points),
                           "endpoint_degrees": (1, 1)})
    # Isolate the rule stage from noisy first-stage pen measurements while
    # exercising the actual exporter and saved-file evidence/quality checks.
    monkeypatch.setattr(scan_conversion, "extract_scan_geometry",
                        lambda binary, **_kw: (candidates, np.full_like(binary, 255), []))
    page, doc = _convert(tmp_path, image)
    saved = list(doc.modelspace().query("LINE"))
    assert len(saved) == 2
    for points, pen in zip(endpoints, pens):
        matching = [e for e in saved if _has_line([_pixel_ends(e, image.shape[0])], *points,
                                                 tolerance=.1)]
        assert len(matching) == 1 and matching[0].dxf.lineweight == pen
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    assert page["quality"]["geometry"]["extra_pixels"] == 0


@pytest.mark.parametrize("mirror,offset", [(False, (20, 15)), (True, (80, 30))])
def test_subpixel_junction_snap_cannot_extend_a_thick_cap_into_blank_paper(
        tmp_path, monkeypatch, mirror, offset):
    image = np.full((240, 340, 3), 255, np.uint8)
    paths = [np.array([[30., 80.], [100., 80.]]),
             np.array([[100.75, 80.75], [100.75, 140.]])]
    for points in paths:
        if mirror:
            points[:, 0] = 180 - points[:, 0]
        points += offset
    candidates = []
    for points, source_thickness, measured_width in zip(paths, (9, 2), (10.5, 2.)):
        cv2.polylines(image, [np.rint(points*16).astype(np.int32)], False,
                      (0, 0, 0), source_thickness, shift=4)
        candidates.append({"type": "LINE", "points": points.tolist(),
                           "stroke_width": measured_width, "source_path": points.copy(),
                           "endpoint_degrees": (1, 1)})
    monkeypatch.setattr(scan_conversion, "extract_scan_geometry",
                        lambda binary, **_kw: (candidates, np.full_like(binary, 255), []))
    page, doc = _convert(tmp_path, image)
    assert sorted(e.dxf.lineweight for e in doc.modelspace().query("LINE")) == [13, 100]
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    assert page["quality"]["geometry"]["extra_pixels"] == 0

    # The centreline intersection is close and lies on ink, but moving both
    # endpoints there pushes the thick native round cap onto unsupported paper.
    intersection = np.array([paths[1][0, 0], paths[0][0, 1]])
    snapped = [(paths[0][0], intersection), (intersection, paths[1][1])]
    unsafe = ezdxf.new("R2013")
    unsafe.layers.new("GEOMETRY")
    factor = 25.4 / 300
    for points, pen in zip(snapped, (100, 13)):
        model = [(x*factor, (image.shape[0]-y)*factor) for x, y in points]
        unsafe.modelspace().add_line(*model, dxfattribs={"layer": "GEOMETRY", "lineweight": pen})
    unsafe_file = tmp_path / "unsupported-snap.dxf"
    unsafe.saveas(unsafe_file)
    reference = source_reference(image, np.zeros(image.shape[:2], np.uint8), [], [])
    unsafe_quality, _ = check_saved_scan(unsafe_file, reference, [], dpi=300)
    assert unsafe_quality["geometry"]["extra_pixels"] > 0


def test_neighbouring_parallel_lines_true_white_gap_and_short_stroke_remain_distinct(tmp_path):
    image = np.full((240, 400, 3), 255, np.uint8)
    expected = [((25, 45), (190, 45)), ((192, 45), (375, 45)),
                ((25, 85), (375, 85)), ((25, 87), (375, 87)),
                ((40, 170), (45, 170))]
    for start, end in expected:
        cv2.line(image, start, end, (0, 0, 0), 1)
    page, doc = _convert(tmp_path, image)
    lines = [_pixel_ends(e, image.shape[0]) for e in doc.modelspace().query("LINE")]
    assert len(lines) == len(expected)
    assert all(_has_line(lines, start, end, tolerance=.1) for start, end in expected)
    assert not any(min(points[:, 0]) < 191 < max(points[:, 0])
                   and np.allclose(points[:, 1], 45, atol=1) for points in lines)
    assert page["quality"]["geometry"]["missing_pixels"] == 0
    assert page["quality"]["geometry"]["extra_pixels"] == 0


def test_multi_cell_table_text_is_not_assembled_as_equipment_symbols(tmp_path, monkeypatch):
    image = np.full((290, 440, 3), 255, np.uint8)
    for x in (40, 210, 380):
        cv2.line(image, (x, 30), (x, 250), (0, 0, 0), 1)
    for y in (30, 140, 250):
        cv2.line(image, (40, y), (380, y), (0, 0, 0), 1)
    observed = []
    for value, (x, y) in zip(("R", "S", "1", "2"), ((115, 95), (285, 95), (115, 205), (285, 205))):
        cv2.putText(image, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
        observed.append(RecognizedLine(value, .98, ((x-4, y-23), (x+21, y-23),
                                                       (x+21, y+5), (x-4, y+5))))
    monkeypatch.setattr(scan_conversion, "recognize_lines", lambda *_args, **_kw: observed)
    page, doc = _convert(tmp_path, image, ocr=True)
    assert len(doc.groups) == 0
    assert sorted(e.dxf.text for e in doc.modelspace().query("TEXT")) == ["1", "2", "R", "S"]
    assert page["quality"]["text"]["missing_or_changed"] == []
    assert page["quality"]["geometry"]["missing_pixels"] == 0


def test_low_confidence_observation_does_not_offset_symbol_text_members(tmp_path, monkeypatch):
    image = np.full((220, 440, 3), 255, np.uint8)
    cv2.circle(image, (140, 110), 35, (0, 0, 0), 2)
    cv2.putText(image, "R", (130, 120), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    cv2.putText(image, "Q", (300, 120), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    observed = [RecognizedLine("Q", .3, ((296, 98), (326, 98), (326, 126), (296, 126))),
                RecognizedLine("R", .98, ((126, 98), (151, 98), (151, 125), (126, 125)))]
    monkeypatch.setattr(scan_conversion, "recognize_lines", lambda *_args, **_kw: observed)
    page, doc = _convert(tmp_path, image, ocr=True)
    assert len(doc.groups) == 1
    _, group = next(iter(doc.groups))
    assert [e.dxf.text for e in group if e.dxftype() == "TEXT"] == ["R"]
    formal_text, = doc.modelspace().query('TEXT[layer=="TEXT"]')
    candidate, = doc.modelspace().query('TEXT[layer=="SUGGEST_REPAIR"]')
    assert formal_text.dxf.text == "R"
    assert candidate.dxf.text == "Q"
    assert _evidence(formal_text)["text_index"] == 0
    assert _evidence(formal_text)["quad_px"] == [list(point) for point in observed[1].quad]
    assert page["quality"]["text"]["missing_or_changed"] == []


@pytest.mark.parametrize("frame,leader", [("circle", False), ("rectangle", False),
                                         ("circle", True), ("rectangle", True)])
@pytest.mark.parametrize("scale", [1, 100])
def test_symbol_group_survives_text_edit_and_move_without_changing_unrelated_geometry(
        tmp_path, monkeypatch, frame, leader, scale):
    image = np.full((300, 480, 3), 255, np.uint8)
    if frame == "circle":
        cv2.circle(image, (140, 110), 35, (0, 0, 0), 2)
    else:
        cv2.rectangle(image, (105, 75), (175, 145), (0, 0, 0), 2)
    cv2.putText(image, "R", (130, 120), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    if leader:
        cv2.line(image, (175, 110), (245, 110), (0, 0, 0), 1)
    cv2.line(image, (30, 235), (445, 235), (0, 0, 0), 1)
    observed = RecognizedLine("R", .98, ((126, 98), (151, 98), (151, 125), (126, 125)))
    monkeypatch.setattr(scan_conversion, "recognize_lines", lambda *_args, **_kw: [observed])
    page, doc = _convert(tmp_path, image, scale=scale, ocr=True)
    assert len(doc.groups) == 1
    name, group = next(iter(doc.groups))
    members = list(group)
    group_evidence = _evidence(group)
    assert group_evidence["kind"] == frame
    assert group_evidence["role"] == "symbol" and group_evidence["page_index"] == 0
    texts = [e for e in members if e.dxftype() in {"TEXT", "MTEXT"}]
    geometry = [e for e in members if e.dxf.layer == "GEOMETRY"]
    assert len(texts) == 1 and texts[0].dxf.text == "R"
    assert _evidence(texts[0])["quad_px"] == [list(point) for point in observed.quad]
    assert geometry, "The native outer frame must be part of the same selectable symbol"
    assert all(e.dxf.owner == doc.modelspace().layout_key for e in members)
    assert page["quality"]["text"]["missing_or_changed"] == []
    assert page["quality"]["text"]["outside_box"] == []
    independent = [e for e in doc.modelspace().query("LINE") if e not in members]
    assert len(independent) == 1 + int(leader)
    leader_handles = group_evidence["leader_handles"]
    assert len(leader_handles) == int(leader)
    assert set(leader_handles).issubset({e.dxf.handle for e in independent})
    if leader:
        assert _has_line([_pixel_ends(doc.entitydb[leader_handles[0]], image.shape[0], scale)],
                         (175, 110), (245, 110))
    independent_before = {e.dxf.handle: (tuple(e.dxf.start), tuple(e.dxf.end)) for e in independent}
    originals = {e.dxf.handle: tuple(e.dxf.insert) for e in texts}
    texts[0].dxf.text = "K"
    movement = (7*scale, 11*scale, 0)
    for entity in members:
        entity.translate(*movement)
    edited = tmp_path / "edited.dxf"
    doc.saveas(edited)
    reopened = ezdxf.readfile(edited)
    saved_group = reopened.groups.get(name)
    assert len(saved_group) == len(members)
    assert _evidence(saved_group) == group_evidence
    moved_text, = [e for e in saved_group if e.dxftype() == "TEXT"]
    assert moved_text.dxf.text == "K"
    assert tuple(moved_text.dxf.insert) == pytest.approx(
        tuple(a+b for a, b in zip(originals[moved_text.dxf.handle], movement)))
    for handle, original_ends in independent_before.items():
        untouched = reopened.entitydb[handle]
        assert (tuple(untouched.dxf.start), tuple(untouched.dxf.end)) == original_ends
    assert not reopened.audit().errors

    # QA reads group members as real modelspace entities, so actual modifications
    # remain visible rather than disappearing behind a GROUP/INSERT wrapper.
    reference = source_reference(image, np.zeros(image.shape[:2], np.uint8), [observed], [])
    quality, _ = check_saved_scan(edited, reference, [observed], dpi=300, drawing_scale=scale)
    assert quality["text"]["missing_or_changed"] == [0]
    assert quality["geometry"]["missing_pixels"] > 0
    assert quality["geometry"]["extra_pixels"] > 0
