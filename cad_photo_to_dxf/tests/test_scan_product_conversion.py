"""Saved-file behavior of the ordinary scan route; no archived fixture graphs."""
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from PIL import Image
from ezdxf.enums import TextEntityAlignment
from ezdxf.fonts import fonts

from app.core import scan_conversion
from app.core.dxf_preview import resolve_drawing_fonts
from app.geometry.scan_cell_layout import _cell_slots, _fit_text
from app.geometry.scan_geometry import extract_scan_geometry
from app.ocr.line_recognition import RecognizedLine


def test_centerline_basic_shapes_and_real_white_gap():
    image = np.full((350,600),255,np.uint8)
    cv2.line(image,(30,40),(230,40),0,5)
    cv2.line(image,(245,40),(450,40),0,5)
    cv2.circle(image,(110,190),45,0,3)
    cv2.ellipse(image,(320,190),(55,55),0,5,130,0,3)
    shapes,_,warnings = extract_scan_geometry(image)
    assert not warnings
    assert sum(s["type"] == "LINE" for s in shapes) == 2
    assert sum(s["type"] == "CIRCLE" for s in shapes) == 1
    assert sum(s["type"] == "ARC" for s in shapes) == 1
    for shape in shapes:
        if shape["type"] == "LINE":
            xs = [p[0] for p in shape["points"]]
            assert not min(xs) < 235 < max(xs), "Actual source white gap must remain open"


def test_normal_words_and_graphics_survive_actual_save_edit_reopen(tmp_path,monkeypatch):
    image = np.full((480,720,3),255,np.uint8)
    cv2.putText(image,"ROOM A-12",(35,75),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    cv2.line(image,(35,160),(420,160),(0,0,0),4)
    cv2.circle(image,(520,270),45,(0,0,0),4)
    cv2.line(image,(490,240),(555,295),(0,0,0),3)
    source = tmp_path/'input.png'
    Image.fromarray(image[:,:,::-1]).save(source)
    observed = RecognizedLine("配电室 A-12",0.98,((30,42),(220,42),(220,80),(30,80)))
    monkeypatch.setattr(scan_conversion,"recognize_lines",lambda *a,**k:[observed])
    output = tmp_path/'ordinary.dxf'
    result = scan_conversion.convert_scan(source,output,preserve_regions=[(465,215,580,325)])
    document = ezdxf.readfile(output)
    text = list(document.modelspace().query('TEXT'))
    assert len(text) == 1 and text[0].dxf.text == "配电室 A-12"
    assert result['counts']['LINE'] >= 1
    images = list(document.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]'))
    assert len(images) == 1
    asset = output.parent / images[0].image_def.dxf.filename
    rgba = np.asarray(Image.open(asset))
    assert rgba.shape[2] == 4 and np.any(rgba[:,:,3] == 0) and np.any(rgba[:,:,3] > 0)
    before = [(tuple(e.dxf.start),tuple(e.dxf.end)) for e in document.modelspace().query('LINE')]
    text[0].dxf.text = "配电室 B-24"
    document.modelspace().delete_entity(images[0])
    edited = tmp_path/'edited.dxf'
    document.saveas(edited)
    reopened = ezdxf.readfile(edited)
    assert [e.dxf.text for e in reopened.modelspace().query('TEXT')] == ["配电室 B-24"]
    assert not list(reopened.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]'))
    assert before == [(tuple(e.dxf.start),tuple(e.dxf.end)) for e in reopened.modelspace().query('LINE')]
    assert not reopened.audit().errors
    assert Path(result['output']) == output


def test_low_confidence_text_retains_original_ink_in_image(tmp_path,monkeypatch):
    image = np.full((200,400,3),255,np.uint8)
    cv2.putText(image,"UNCLEAR",(30,90),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
    observed = RecognizedLine("UNCLEAR",0.55,((25,55),(190,55),(190,98),(25,98)))
    monkeypatch.setattr(scan_conversion,"recognize_lines",lambda *a,**k:[observed])
    result = scan_conversion.convert_scan('memory.png',tmp_path/'low.dxf',image=image)
    doc = ezdxf.readfile(result['output'])
    assert not list(doc.modelspace().query('TEXT'))
    assert list(doc.modelspace().query('IMAGE[layer=="REVIEW_SOURCE"]'))
    assert result['ocr']['uncertain_lines'][0]['text'] == 'UNCLEAR'


def test_scan_cell_layout_keeps_native_lines_and_grid_on_save(tmp_path, monkeypatch):
    image = np.full((210, 360, 3), 255, np.uint8)
    for x in (40, 165, 310):
        cv2.line(image, (x, 50), (x, 135), (0, 0, 0), 3)
    for y in (50, 135):
        cv2.line(image, (40, y), (310, y), (0, 0, 0), 3)
    lines = [
        RecognizedLine("进线 Feed", 0.99, ((41, 50), (163, 50), (163, 89), (41, 89))),
        RecognizedLine("回路 g24", 0.99, ((41, 94), (163, 94), (163, 134), (41, 134))),
        RecognizedLine("Drawing title", 0.99, ((45, 155), (225, 155), (225, 189), (45, 189))),
    ]
    monkeypatch.setattr(scan_conversion, "recognize_lines", lambda *a, **k: lines)
    # A known model scale ensures the layout compares pen and text in the right units.
    dpi, drawing_scale = 100, 12
    scale = 25.4 / dpi * drawing_scale
    after = tmp_path / "layout.dxf"
    report = scan_conversion.convert_scan(
        "memory.png", after, image=image, dpi=dpi, drawing_scale=drawing_scale,
    )
    monkeypatch.setattr(scan_conversion, "place_cell_text", lambda *a, **k: None)
    before = tmp_path / "unfitted.dxf"
    baseline = scan_conversion.convert_scan(
        "memory.png", before, image=image, dpi=dpi, drawing_scale=drawing_scale,
    )
    doc, old_doc = ezdxf.readfile(after), ezdxf.readfile(before)
    style_font = doc.styles.get("wqy-unicode").dxf.font
    resolve_drawing_fonts(doc, after.parent)
    texts = list(doc.modelspace().query("TEXT"))
    old_texts = list(old_doc.modelspace().query("TEXT"))
    assert [text.dxf.text for text in texts] == [line.text for line in lines]
    grid = [(e.dxf.start, e.dxf.end) for e in doc.modelspace().query("LINE")]
    assert grid and grid == [(e.dxf.start, e.dxf.end) for e in old_doc.modelspace().query("LINE")]
    assert report["quality"]["geometry"] == baseline["quality"]["geometry"]
    assert not report["quality"]["text"]["missing_or_changed"]
    assert texts[2].dxf.all_existing_dxf_attribs() == old_texts[2].dxf.all_existing_dxf_attribs()
    assert all(text.get_align_enum() == TextEntityAlignment.FIT for text in texts[:2])

    def ink_bounds(text):
        font = fonts.make_font(doc.styles.get(text.dxf.style).dxf.font, text.dxf.height, text.dxf.width)
        bounds = font.text_path(text.dxf.text).bbox()
        return bounds.extmin + text.dxf.insert, bounds.extmax + text.dxf.insert

    limits = [ink_bounds(text) for text in texts[:2]]
    for low, high in limits:
        assert 41 * scale < low.x < high.x < 164 * scale
        assert (210 - 134) * scale < low.y < high.y < (210 - 51) * scale
    assert limits[0][0].y > limits[1][1].y
    assert any(ink_bounds(old) != bounds for old, bounds in zip(old_texts, limits))
    assert all(doc.layers.get(name).is_off() for name in ("REVIEW_SOURCE", "SUGGEST_REPAIR"))

    # Reload the untouched style path before doing the saved-file edit.
    doc.styles.get("wqy-unicode").dxf.font = style_font
    texts[0].dxf.text = "出线 Feed"
    first_anchor, last_anchor = texts[0].dxf.insert, texts[0].dxf.align_point
    texts[0].translate(scale, 0, 0)
    doc.save()
    edited = ezdxf.readfile(after)
    assert [e.dxf.text for e in edited.modelspace().query("TEXT")] == ["出线 Feed", "回路 g24", "Drawing title"]
    restored = list(edited.modelspace().query("TEXT"))[0]
    assert restored.dxf.insert == first_anchor + (scale, 0, 0)
    assert restored.dxf.align_point == last_anchor + (scale, 0, 0)
    assert grid == [(e.dxf.start, e.dxf.end) for e in edited.modelspace().query("LINE")]
    assert not edited.audit().errors


def test_cell_layout_ignores_open_grid_isolated_box_and_cross_cell_ocr():
    drawing = np.full((65, 140), 255, np.uint8)
    cv2.rectangle(drawing, (10, 10), (130, 50), 0, 1)
    first = RecognizedLine("Text", 1, ((14, 18), (65, 18), (65, 40), (14, 40)))
    across = RecognizedLine("Text Text", 1, ((35, 18), (110, 18), (110, 40), (35, 40)))
    assert not list(_cell_slots(drawing, [], [first], [], 100))
    cv2.line(drawing, (70, 10), (70, 50), 0, 1)
    [(index, clearance)] = list(_cell_slots(drawing, [], [first, across], [], 300))
    assert index == 0
    heavy_divider = {"type": "LINE", "points": [(70, 10), (70, 50)], "lineweight": 100}
    [(_, adjusted)] = list(_cell_slots(drawing, [heavy_divider], [first], [], 300))
    assert adjusted[2] < clearance[2] - 4
    assert not list(_cell_slots(drawing, [], [first], [{"text_indices": [0]}], 100))
    drawing[11:15, 70] = 255
    assert not list(_cell_slots(drawing, [], [first], [], 100))


def test_vertical_cell_text_resizes_as_one_native_string():
    doc = ezdxf.new()
    label = doc.modelspace().add_text(
        "A-12", dxfattribs={"insert": (20, 10), "rotation": 90, "height": 10, "width": 1.2},
    )
    font = fonts.make_font(fonts.MONOSPACE, label.dxf.height, label.dxf.width)
    available_y = font.text_width(label.dxf.text) * 0.7
    _fit_text(label, np.array([12, 10, 20, 10 + available_y]), fonts.MONOSPACE)
    scaled = fonts.make_font(fonts.MONOSPACE, label.dxf.height, label.dxf.width)
    assert label.dxf.text == "A-12" and label.dxf.rotation == 90
    assert label.get_align_enum() == TextEntityAlignment.FIT
    assert 6.5 <= label.dxf.height < 10 and 0.95 <= label.dxf.width < 1.2
    assert label.dxf.insert.x - label.dxf.height >= 12 - 1e-10
    assert label.dxf.insert.y + scaled.text_width(label.dxf.text) <= 10 + available_y + 1e-10
    assert label.dxf.align_point.y <= 10 + available_y + 1e-10


def test_transparent_png_is_composited_on_white_before_geometry(tmp_path):
    pixels = np.zeros((60,90,4),np.uint8)
    pixels[25:29,10:80,3] = 255
    source = tmp_path/'transparent.png'
    Image.fromarray(pixels).save(source)
    loaded = scan_conversion._load(source,0)
    assert np.all(loaded[0,0] == 255)
    assert np.all(loaded[26,30] == 0)


def test_separate_stamp_ring_and_lettering_form_one_image(tmp_path):
    image = np.full((240, 360, 3), 255, np.uint8)
    cv2.circle(image, (180, 120), 70, (0, 0, 190), 3)
    cv2.putText(image, "OK", (150, 132), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 190), 3)
    result = scan_conversion.convert_scan('memory.png', tmp_path/'stamp.dxf',
                                          image=image, enable_ocr=False)
    document = ezdxf.readfile(result['output'])
    assert result['protected_graphics'] == 1
    assert len(document.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]')) == 1


def test_manual_graphic_on_gray_paper_is_saved_with_transparent_paper(tmp_path):
    image = np.full((240, 360, 3), 220, np.uint8)
    cv2.polylines(image, [np.array([(90, 115), (120, 80), (145, 120), (190, 85)])],
                  False, (50, 50, 50), 2)
    result = scan_conversion.convert_scan('memory.png', tmp_path/'gray-paper.dxf',
        image=image, enable_ocr=False, preserve_regions=[(75, 65, 205, 135)])
    document = ezdxf.readfile(result['output'])
    images = list(document.modelspace().query('IMAGE[layer=="PROTECTED_GRAPHICS"]'))
    assert len(images) == 1 and images[0].dxf.flags & 8
    rgba = np.asarray(Image.open(tmp_path/images[0].image_def.dxf.filename))
    assert rgba.shape[2] == 4
    assert np.count_nonzero(rgba[:, :, 3] == 0) > rgba.shape[0]*rgba.shape[1]*.80
    assert rgba[:, :, 3].max() > 150
