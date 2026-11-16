"""Source-paint permission, shifted PDF grids and safe upstream recovery."""
import ctypes as ct
from dataclasses import replace
from math import cos, sin, radians
from types import SimpleNamespace

import numpy as np
import pypdfium2 as pdfium
import pytest
from PySide6.QtGui import QGuiApplication

from app.core.processing import ProductionProcessingConfig
from app.geometry.content_ownership import _candidate_region_mask
from app.geometry.pdf_arc_evidence import pdf_geometry_binding
from app.ocr.auxiliary_recognition import TextCandidate, TextObservation
from app.ocr.native_source_row import measure_row, recover_native_source_rows

APP = QGuiApplication.instance() or QGuiApplication([])


def sample(tmp_path, *, angle=0, shifted=False, extra=None, page_rotation=0):
    raw = pdfium.raw
    path = tmp_path / "source.pdf"
    with pdfium.PdfDocument.new() as doc:
        page = doc.new_page(300, 300)
        if shifted:
            page.set_mediabox(-20, -30, 280, 270)
            page.set_cropbox(-10, -20, 270, 260)

        def text(x=120, y=130):
            obj = raw.FPDFPageObj_NewTextObj(doc, b"Helvetica", 16)
            data = "SAMPLE TEXT".encode("utf-16-le") + b"\0\0"
            buffer = (ct.c_ushort * (len(data)//2)).from_buffer_copy(data)
            assert raw.FPDFText_SetText(obj, buffer)
            assert raw.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            a = radians(angle)
            raw.FPDFPageObj_Transform(obj, cos(a), sin(a), -sin(a), cos(a), x, y)
            raw.FPDFPage_InsertObject(page, obj)

        text()
        assert raw.FPDFPage_GenerateContent(page)
        bitmap = page.render(scale=2, grayscale=True)
        try:
            baseline = np.array(bitmap.to_pil().convert("L"))
        finally:
            bitmap.close()
        if extra == "duplicate":
            text()
        elif extra == "same-neighbor":
            text(y=165)
        elif extra == "separator":
            # A real rule through the gap in the observed row, not four corners.
            shape = raw.FPDFPageObj_CreateNewPath(184, 120)
            assert raw.FPDFPath_LineTo(shape, 184, 160)
            assert raw.FPDFPageObj_SetStrokeColor(shape, 0, 0, 0, 255)
            assert raw.FPDFPageObj_SetStrokeWidth(shape, 1)
            assert raw.FPDFPath_SetDrawMode(shape, 0, 1)
            raw.FPDFPage_InsertObject(page, shape)
        elif extra == "weak-foreign":
            shape = raw.FPDFPageObj_CreateNewRect(135, 137, 1, 1)
            assert raw.FPDFPageObj_SetFillColor(shape, 220, 220, 220, 255)
            assert raw.FPDFPath_SetDrawMode(shape, raw.FPDF_FILLMODE_WINDING, 0)
            raw.FPDFPage_InsertObject(page, shape)
        elif extra == "white-occlusion":
            tp = page.get_textpage()
            try:
                l,b,r,t = tp.get_charbox(2)
            finally:
                tp.close()
            shape = raw.FPDFPageObj_CreateNewRect(l-1,b-1,r-l+2,t-b+2)
            assert raw.FPDFPageObj_SetFillColor(shape, 255, 255, 255, 255)
            assert raw.FPDFPath_SetDrawMode(shape, raw.FPDF_FILLMODE_WINDING, 0)
            raw.FPDFPage_InsertObject(page, shape)
        elif extra == "native-clip":
            clip = raw.FPDF_CreateClipPath(110, 120, 180, 150)
            raw.FPDFPage_InsertClipPath(page, clip)
            raw.FPDF_DestroyClipPath(clip)
        assert raw.FPDFPage_GenerateContent(page)
        page.set_rotation(page_rotation)
        doc.save(path)
        page.close()
    with pdfium.PdfDocument(path) as doc:
        page = doc[0]
        bitmap = page.render(scale=2, grayscale=True)
        try:
            gray = np.array(bitmap.to_pil().convert("L"))
        finally:
            bitmap.close()
        page.close()
    ys, xs = np.nonzero(baseline < 255)
    l,t,r,b = int(xs.min())-5,int(ys.min())-5,int(xs.max())+6,int(ys.max())+6
    corners = ((l,t),(r,t),(r,b),(l,b))
    start = {0:0,90:3,180:2,270:1}[angle]
    quad = tuple(tuple(map(float,corners[(start+i)%4])) for i in range(4))
    original = TextCandidate("SAMPLE TEXT", (l,t,r-l,b-t), .99, "text_candidate",
                             quad=quad, source="rapidocr-test", replacement_safe=False)
    if angle in (0,180):
        clip = (l,t,(r-l)//2,b-t)
    else:
        clip = (l,t,r-l,(b-t)//2)
    x,y,w,h=clip
    clipped_quad=tuple((float(x if px<(l+r)/2 else x+w),float(y if py<(t+b)/2 else y+h)) for px,py in quad)
    obs = replace(TextObservation.capture(original,0),cell_clip_bbox=clip,cell_clip_quad=clipped_quad)
    clipped=replace(original,bbox=clip,quad=clipped_quad,pre_cell_observation=obs)
    evidence=SimpleNamespace(binding=pdf_geometry_binding(path,0,144))
    return gray,clipped,evidence,path


@pytest.mark.parametrize("angle", [0,90,180,270])
@pytest.mark.parametrize("shifted", [False,True])
def test_complete_native_source_is_recovered_in_observed_direction(tmp_path,angle,shifted):
    gray,text,evidence,path=sample(tmp_path,angle=angle,shifted=shifted)
    before=path.read_bytes()
    records=[]
    output=recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records)
    assert records[0]["decision"]=="ADOPTED",records
    new=output[0]
    assert new.text==text.text and new.pre_cell_observation==text.pre_cell_observation
    assert new.bbox==text.pre_cell_observation.bbox
    assert new.quad==text.pre_cell_observation.quad
    assert new.display_quad is not None and new.replacement_safe==text.replacement_safe
    assert records[0]["transcript_proven"] is False
    assert path.read_bytes()==before
    claim=(_candidate_region_mask(new,gray.shape)>0)&(gray<=254)
    proved=np.zeros(gray.shape,bool)
    for y,l,r in records[0]["source_runs"]: proved[y,l:r]=True
    assert np.array_equal(claim,proved)
    repeated=[]
    assert recover_native_source_rows(gray,output,evidence,threshold=254,records=repeated)==output
    assert repeated==[]


@pytest.mark.parametrize("extra", ["duplicate","separator","weak-foreign","native-clip"])
def test_shared_paint_and_true_separator_are_not_claimed(tmp_path,extra):
    gray,text,evidence,_=sample(tmp_path,extra=extra)
    records=[]
    assert recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records)==(text,)
    assert records[0]["decision"]=="ABSTAIN"


def test_same_transcript_neighbor_is_not_selected_by_nearness(tmp_path):
    gray,text,evidence,_=sample(tmp_path,extra="same-neighbor")
    records=[]
    output=recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records)
    assert records[0]["decision"]=="ADOPTED",records
    assert output[0].text==text.text
    assert max(y for y,_,_ in records[0]["source_runs"])<text.pre_cell_observation.bbox[1]+text.pre_cell_observation.bbox[3]


def test_a_white_occluder_cannot_certify_a_complete_native_row(tmp_path):
    gray,text,evidence,_=sample(tmp_path,extra="white-occlusion")
    records=[]
    assert recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records)==(text,)
    assert records[0]["decision"]=="ABSTAIN"


def test_native_font_paint_does_not_override_a_protected_background_role(tmp_path):
    gray,text,evidence,_=sample(tmp_path)
    protected=np.uint8(gray<255)*255
    records=[]
    assert recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records,
                                      protected_source_masks=(protected,))==(text,)
    assert records[0]["reason"]=="PROTECTED_BACKGROUND_SOURCE"


def test_wrong_canvas_missing_source_and_user_layout_keep_baseline(tmp_path):
    gray,text,evidence,_=sample(tmp_path)
    altered=gray.copy()
    altered[0,0]=0
    records=[]
    assert recover_native_source_rows(altered,(text,),evidence,threshold=254,records=records)==(text,)
    assert records[0]["reason"]=="NATIVE_PARENT_CANVAS_MISMATCH"
    records=[]
    assert recover_native_source_rows(gray,(text,),None,threshold=254,records=records)==(text,)
    assert records[0]["reason"]=="NO_NATIVE_PDF_SOURCE"
    reviewed=replace(text,reviewed=True)
    assert recover_native_source_rows(gray,(reviewed,),evidence,threshold=254,records=[])==(reviewed,)


def test_degenerate_neighbor_does_not_crash_or_authorize_a_proposal(tmp_path):
    gray,text,evidence,_=sample(tmp_path)
    neighbor=TextCandidate("X",(10,10,20,10),.99,"text_candidate",
                           display_quad=((0.,0.),)*4,source="rapidocr-test")
    records=[]
    assert recover_native_source_rows(gray,(text,neighbor),evidence,threshold=254,records=records)==(text,neighbor)
    assert records[0]["reason"]=="UNMEASURABLE_NEIGHBOR_TEXT"


def test_old_unproved_carrier_is_held_instead_of_releasing_foreign_ink(tmp_path):
    gray,text,evidence,_=sample(tmp_path,extra="same-neighbor")
    x,y,w,h=text.pre_cell_observation.bbox
    outside=gray<128
    outside[y:y+h,x:x+w]=False
    ys,xs=np.nonzero(outside)
    foreign=(int(xs.min()),int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1))
    text=replace(text,character_boxes=(foreign,))
    records=[]
    assert recover_native_source_rows(gray,(text,),evidence,threshold=254,records=records)==(text,)
    assert records[0]["reason"]=="OLD_CARRIER_CONTAINS_UNPROVEN_MEMBER"


def test_restored_bounds_cannot_silently_drop_a_neighbor_in_dedup(tmp_path):
    gray,text,evidence,_=sample(tmp_path)
    x,y,w,h=text.bbox
    neighbor=TextCandidate("LABEL",(x+w+5,y,30,h),.8,"text_candidate",
                           display_quad=((10.,10.),(40.,10.),(40.,25.),(10.,25.)),source="rapidocr-test")
    records=[]
    assert recover_native_source_rows(gray,(text,neighbor),evidence,threshold=254,records=records)==(text,neighbor)
    assert records[0]["reason"]=="RESTORED_BOUNDS_CHANGE_DEDUP_WINNERS"


def test_three_rectangles_are_geometry_not_four_verified_characters():
    gray=np.full((50,80),255,np.uint8)
    for left,right in ((3,8),(14,19),(33,38)):
        gray[15:25,10+left:10+right]=0
    candidate=TextCandidate("ABCD",(10,10,42,20),.99,"text_candidate",
                            quad=((10.,10.),(52.,10.),(52.,30.),(10.,30.)))
    quad,_,facts=measure_row(gray,TextObservation.capture(candidate,0))
    assert len(quad)==4 and facts["complete_components"]==3
    assert facts["transcript_proven"] is False


def test_config_is_opt_in_and_separate_from_frozen_g35():
    assert "experimental_native_source_row" not in ProductionProcessingConfig().payload()
    assert ProductionProcessingConfig(experimental_native_source_row=True).payload()["native_source_row_version"]
    with pytest.raises(ValueError):
        ProductionProcessingConfig(experimental_native_source_row=True,experimental_observed_text_display=True)
