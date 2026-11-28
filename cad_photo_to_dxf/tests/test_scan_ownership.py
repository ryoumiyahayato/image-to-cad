"""Ordinary entry, saved-file mutations and the default offscreen preview."""
from types import SimpleNamespace

import cv2
import ezdxf
import numpy as np
import pytest
from PIL import Image

from app.core import scan_conversion
from app.core.conversion import convert_document
from app.core.dxf_preview import render_dxf
from app.core.scan_quality import check_saved_scan, source_reference
from app.geometry.scan_ownership import _continuous_rules
from app.ocr.line_recognition import RecognizedLine
from app.ocr import line_recognition


def _convert(tmp_path, image, name="scan", **kwargs):
    source = tmp_path / f"{name}.png"
    Image.fromarray(image[:, :, ::-1]).save(source)
    page = convert_document(source, tmp_path / f"{name}.dxf", **kwargs)["outputs"][0]
    return page, ezdxf.readfile(page["output"])


def _recognition(monkeypatch, lines):
    monkeypatch.setattr(scan_conversion, "recognize_lines", lambda *_args, **_kw: lines)


@pytest.mark.parametrize("slope", [0, 0.28])
def test_crossing_and_adjacent_lines_survive_native_text_edit(tmp_path, monkeypatch, slope):
    image = np.full((160, 360, 3), 255, np.uint8)
    cv2.putText(image, "A12", (90, 85), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    y = round(72 - 85*slope)
    cv2.line(image, (20, y), (340, y+round(320*slope)), (0, 0, 0), 1)
    # Keep the second line outside the oblique leader's extent for the inclined case.
    if not slope:
        cv2.line(image, (20, 90), (340, 90), (0, 0, 0), 1)
    line = RecognizedLine("A12", .98, ((84, 57), (160, 57), (160, 91), (84, 91)))
    _recognition(monkeypatch, [line])
    page, doc = _convert(tmp_path, image)
    text, = doc.modelspace().query("TEXT")
    assert text.dxf.text == "A12"
    text.dxf.text = "B43"
    edited = tmp_path / "edited.dxf"
    doc.saveas(edited)
    msp = ezdxf.readfile(edited).modelspace()
    assert msp.query("TEXT")[0].dxf.text == "B43"
    geometry = msp.query('*[layer=="GEOMETRY"]')
    assert len(geometry) == (1 if slope else 2)
    for entity in geometry:
        assert entity.dxftype() == "LINE"
        xs = sorted(p.x * 300/25.4 for p in (entity.dxf.start, entity.dxf.end))
        assert xs == pytest.approx([20, 340], abs=1)
    assert page["quality"]["text"]["outside_box"] == []
    assert page["quality"]["geometry"]["missing_pixels"] == 0


def test_readback_detects_cut_inside_ocr_box_and_spurious_line(tmp_path, monkeypatch):
    image = np.full((140, 280, 3), 255, np.uint8)
    cv2.putText(image, "125", (82, 76), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.line(image, (10, 66), (270, 66), (0, 0, 0), 1)
    observed = RecognizedLine("125", .98, ((75, 47), (150, 47), (150, 82), (75, 82)))
    _recognition(monkeypatch, [observed])
    page, doc = _convert(tmp_path, image, drawing_scale=100)
    assert page["quality"]["geometry"]["extra_pixels"] == 0
    msp = doc.modelspace()
    line, = msp.query("LINE")
    scale = 25.4/300*100
    def at(x, y):
        return x*scale, (140-y)*scale
    msp.delete_entity(line)
    attrs = {"layer": "GEOMETRY", "lineweight": 13}
    msp.add_line(at(10, 66), at(96, 66), dxfattribs=attrs)
    msp.add_line(at(131, 66), at(270, 66), dxfattribs=attrs)
    msp.add_line(at(95, 51), at(130, 51), dxfattribs=attrs)
    msp.query("TEXT")[0].dxf.insert = at(180, 50)
    doc.saveas(page["output"])
    ref = source_reference(image, np.zeros(image.shape[:2], np.uint8), [observed], [])
    checks, residual = check_saved_scan(page["output"], ref, [observed], dpi=300, drawing_scale=100)
    assert np.all(residual[66, 102:125])
    assert checks["geometry"]["missing_pixels"] >= 30
    assert checks["geometry"]["extra_pixels"] >= 30
    assert checks["text"]["outside_box"] == [0]
    msp.query("TEXT")[0].dxf.text = "12"
    doc.saveas(page["output"])
    checks, _ = check_saved_scan(page["output"], ref, [observed], dpi=300, drawing_scale=100)
    assert checks["text"]["missing_or_changed"] == [0]


def test_red_text_and_separate_graphics_reach_default_preview(tmp_path, monkeypatch):
    image = np.full((240, 480, 3), 255, np.uint8)
    cv2.putText(image, "12", (25, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 210), 2)
    cv2.circle(image, (230, 90), 42, (0, 0, 200), 3)
    cv2.putText(image, "OK", (212, 99), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 200), 2)
    cv2.line(image, (340, 120), (375, 77), (0, 0, 0), 3)
    cv2.fillPoly(image, [np.int32([(90, 170), (116, 170), (101, 148)])], (180, 40, 0))
    cv2.putText(image, "BLUR", (290, 215), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    def observe(view, **kwargs):
        assert np.count_nonzero(view[40:80, 20:80, 0] < 80) > 150
        assert view[45:135, 185:275].min() == 255
        assert view[70:130, 330:390].min() == 255
        return [RecognizedLine("12", .98, ((20, 43), (76, 43), (76, 80), (20, 80))),
                RecognizedLine("BLUR", .55, ((285, 182), (395, 182), (395, 220), (285, 220)))]
    monkeypatch.setattr(scan_conversion, "recognize_lines", observe)
    page, doc = _convert(tmp_path, image, preserve_regions=[(330, 70, 390, 130)])
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["12"]
    assert len(doc.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]')) == 3
    assert doc.layers.get("REVIEW_SOURCE").is_off()
    review, = doc.modelspace().query('IMAGE[layer=="REVIEW_SOURCE"]')
    assert review.image_def.dxf.filename.endswith("unresolved-ink.png")
    preview = np.asarray(Image.open(page["preview"]).convert("RGB"))
    assert np.count_nonzero(preview[:, :, 0].astype(int) - preview[:, :, 2] > 80) > 20
    # Force the diagnostic layer on, then remove it. Both default renders must match.
    doc.layers.get("REVIEW_SOURCE").on()
    doc.saveas(page["output"])
    render_dxf(page["output"], tmp_path / "layer-on.png")
    doc.modelspace().delete_entity(review)
    doc.saveas(page["output"])
    render_dxf(page["output"], tmp_path / "no-review.png")
    for name in ("layer-on.png", "no-review.png"):
        assert np.array_equal(preview, np.asarray(Image.open(tmp_path / name).convert("RGB")))


@pytest.mark.parametrize("scale", [1, 100])
def test_paper_weights_short_dash_and_short_junction_link(tmp_path, scale):
    image = np.full((160, 220, 3), 255, np.uint8)
    for y, thickness in ((30, 1), (60, 5)):
        cv2.line(image, (10, y), (150, y), (0, 0, 0), thickness)
    cv2.line(image, (160, 90), (165, 90), (0, 0, 0), 1)
    cv2.line(image, (20, 100), (20, 130), (0, 0, 0), 1)
    cv2.line(image, (25, 100), (25, 130), (0, 0, 0), 1)
    cv2.line(image, (20, 115), (25, 115), (0, 0, 0), 1)
    image[145, 200] = 0
    _, doc = _convert(tmp_path, image, enable_ocr=False, dpi=300, drawing_scale=scale)
    units = scale * 25.4/300
    lines = doc.modelspace().query("LINE")
    by_y = {round(160-e.dxf.start.y/units): e for e in lines if abs(e.dxf.start.y-e.dxf.end.y) < 0.01}
    assert (by_y[30].dxf.lineweight, by_y[60].dxf.lineweight) == (13, 50)
    for y in (90, 115):
        edge = by_y[y]
        assert abs(edge.dxf.start.x-edge.dxf.end.x) / units == pytest.approx(5)
    assert not any(e.dxf.start.x/units > 190 for e in lines)


@pytest.mark.parametrize("symbol", ["circle", "box"])
def test_touching_symbol_frame_and_enclosed_character(tmp_path, monkeypatch, symbol):
    image = np.full((160, 220, 3), 255, np.uint8)
    if symbol == "circle":
        cv2.circle(image, (100, 80), 30, (0, 0, 0), 3)
    else:
        cv2.rectangle(image, (70, 50), (130, 110), (0, 0, 0), 3)
    cv2.putText(image, "R", (70, 98), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 2)
    _recognition(monkeypatch, [RecognizedLine("R", .98, ((66,47),(134,47),(134,114),(66,114)))])
    _, doc = _convert(tmp_path, image)
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["R"]
    frame, = doc.modelspace().query('*[layer=="GEOMETRY"]')
    if symbol == "circle":
        assert frame.dxftype() == "CIRCLE" and frame.dxf.radius == pytest.approx(30*25.4/300, abs=.12)
    else:
        assert frame.dxftype() == "LWPOLYLINE" and frame.closed


def test_boxed_printed_glyphs_do_not_leave_frames(tmp_path, monkeypatch):
    image = np.full((100, 180, 3), 255, np.uint8)
    red = (0, 0, 200)
    for x in (35, 80):
        cv2.rectangle(image, (x, 35), (x+32, 67), red, 2)
        cv2.rectangle(image, (x+10, 45), (x+22, 57), red, 2)
    def observe(view, **kwargs):
        assert np.count_nonzero(view[:, :, 0] == 0) > 300
        return [RecognizedLine("回回", .98, ((30,30),(118,30),(118,72),(30,72)))]
    monkeypatch.setattr(scan_conversion, "recognize_lines", observe)
    _, doc = _convert(tmp_path, image)
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["回回"]
    assert not doc.modelspace().query('*[layer=="GEOMETRY"]')
    assert not doc.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]')


def test_rule_crosses_stamp_and_manually_protected_area(tmp_path):
    image = np.full((180, 420, 3), 255, np.uint8)
    cv2.line(image, (10, 85), (405, 85), (0, 0, 0), 3)
    cv2.circle(image, (110, 85), 35, (0, 0, 180), 3)
    cv2.putText(image, "OK", (94, 94), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 180), 2)
    cv2.line(image, (255, 103), (298, 68), (0, 0, 0), 2)
    _, doc = _convert(tmp_path, image, enable_ocr=False, preserve_regions=[(242, 57, 310, 115)])
    assert len(doc.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]')) == 2
    rule, = doc.modelspace().query('*[layer=="GEOMETRY"]')
    assert rule.dxftype() == "LINE"
    xs = sorted(p.x * 300/25.4 for p in (rule.dxf.start, rule.dxf.end))
    assert xs == pytest.approx([10, 405], abs=3)


def test_missing_output_cannot_be_hidden_by_fitter_coverage(tmp_path, monkeypatch):
    image = np.full((100, 260, 3), 255, np.uint8)
    cv2.putText(image, "B2", (71, 63), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.line(image, (10, 53), (249, 53), (0, 0, 0), 1)
    _recognition(monkeypatch, [RecognizedLine("B2", .99, ((63,35),(131,35),(131,70),(63,70)))])
    monkeypatch.setattr(scan_conversion, "extract_scan_geometry",
                        lambda binary, **kwargs: ([], np.full_like(binary, 255), []))
    page, _ = _convert(tmp_path, image)
    assert page["status"] == "COMPLETED_WITH_REVIEW"
    assert page["quality"]["geometry"]["missing_pixels"] == page["unresolved_ink_pixels"] == 240


def test_review_only_page_has_a_blank_default_preview(tmp_path, monkeypatch):
    image = np.full((100, 240, 3), 255, np.uint8)
    cv2.putText(image, "LOW", (60, 64), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    _recognition(monkeypatch, [RecognizedLine("LOW", .55, ((52,36),(148,36),(148,73),(52,73)))])
    page, doc = _convert(tmp_path, image)
    assert page["unresolved_ink_pixels"] > 0
    assert len(doc.modelspace().query('IMAGE[layer=="REVIEW_SOURCE"]')) == 1
    assert np.all(np.asarray(Image.open(page["preview"]).convert("RGB")) == 255)


def test_ocr_last_tile_is_anchored_at_page_edge(monkeypatch):
    sizes = []

    def engine(tile, **kwargs):
        sizes.append(tile.shape[:2])

    monkeypatch.setattr(line_recognition, "_engine", lambda: engine)
    page = np.zeros((230, 3600, 3), np.uint8)
    assert line_recognition.recognize_lines(page) == []
    assert sizes == [(230, 3600), (230, 2048), (230, 2048)]


def test_ocr_recovers_native_small_ink_across_tiles_without_duplicate_text(monkeypatch):
    image = np.full((260, 3000), 249, np.uint8)
    for x, y in ((1475, 115), (2745, 183)):
        cv2.putText(image, "SMALL NOTE", (x, y), cv2.FONT_HERSHEY_SIMPLEX, .45, 75, 1)
    expected = ((1472, 100), (1566, 100), (1566, 120), (1472, 120))
    calls = 0

    def engine(tile, *, use_det, **kwargs):
        nonlocal calls
        if not use_det:
            assert tile.shape[0] < 32
            return SimpleNamespace(txts=["SMALL NOTE"], scores=np.array([.94]))
        calls += 1
        if calls == 1:
            return SimpleNamespace(boxes=[expected], txts=["EXISTING NOTE"], scores=[.92])
        return None

    monkeypatch.setattr(line_recognition, "_engine", lambda: engine)
    ink = np.uint8(image < 200) * 255
    existing, recovered = line_recognition.recognize_lines(image, recovery=(image, ink))
    assert existing.text == "EXISTING NOTE"
    assert recovered.text == "SMALL NOTE"
    assert recovered.confidence == .94
    assert 2740 <= recovered.bbox[0] <= 2750
    assert 182 <= recovered.bbox[3] <= 189


def test_axis_aligned_rule_profile_does_not_lose_ink_or_fill_gap_at_text():
    ink = np.zeros((90, 225), np.uint8)
    ink[40, 20:113] = 255
    ink[40, 114:210] = 255
    cv2.putText(ink, "L", (91, 40), cv2.FONT_HERSHEY_SIMPLEX, .8, 255, 1)
    quad = np.zeros_like(ink)
    quad[23:66, 80:145] = 255
    rules = _continuous_rules(ink, quad, 116, crossing_only=True)
    assert np.array_equal(rules[40], ink[40])
    assert not np.any(rules[:40])
    assert rules[40, 113] == 0

    quad[23:66, :80] = 255
    assert not _continuous_rules(ink, quad, 116, crossing_only=True).any()
