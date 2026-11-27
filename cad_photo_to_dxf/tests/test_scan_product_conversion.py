"""Saved-file behavior of the ordinary scan route; no archived fixture graphs."""
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from PIL import Image

from app.core import scan_conversion
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
