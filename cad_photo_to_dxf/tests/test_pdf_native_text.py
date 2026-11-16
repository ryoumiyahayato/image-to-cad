"""Native omissions, actual shared structure, hidden paint and mapping fallback."""
from types import SimpleNamespace
from pathlib import Path
import os

import numpy as np
import pymupdf
import pypdfium2 as pdfium
import pytest
from PySide6.QtGui import QGuiApplication

from app.geometry.pdf_arc_evidence import pdf_geometry_binding
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.pdf_native_text import collect_native_text

APP = QGuiApplication.instance() or QGuiApplication([])


def source(tmp_path, *, rotate=0, hidden=False, line=False, mirror=False, page_rotation=0):
    path = tmp_path / "source.pdf"
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
    if not font_path.is_file():
        pytest.skip("This local PDF fixture needs an installed TrueType test font")
    font = pymupdf.Font(fontfile=str(font_path))
    with pymupdf.open() as doc:
        page = doc.new_page(width=180,height=180)
        page.insert_font(fontname="SourceFont",fontbuffer=font.buffer)
        extra={"morph":(pymupdf.Point(80,95),pymupdf.Matrix(-1,0,0,1,0,0))} if mirror else {}
        page.insert_text((80,95),"P7",fontname="SourceFont",fontsize=16,rotate=rotate,**extra)
        if line:
            page.draw_line((70,90),(120,90),color=(0,0,0),width=1)
        if hidden:
            color=(0,0,0) if hidden in ("black","partial-black") else (1,1,1)
            box=(95,65,125,110) if hidden=="partial-black" else (65,65,125,110)
            page.draw_rect(box,color=None,fill=color,overlay=True)
        page.set_rotation(page_rotation)
        doc.save(path)
    with pdfium.PdfDocument(path) as doc:
        page=doc[0]
        bitmap=page.render(scale=2,grayscale=True)
        gray=np.array(bitmap.to_pil().convert("L"))
        bitmap.close()
        page.close()
    return gray,SimpleNamespace(binding=pdf_geometry_binding(path,0,144)),path


@pytest.mark.parametrize("rotate",[0,90,180,270])
def test_independent_native_entry_does_not_require_an_ocr_carrier(tmp_path,rotate):
    gray,evidence,path=source(tmp_path,rotate=rotate)
    original=path.read_bytes()
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert [t.text for t in plan.texts]==["P7"],plan.records
    assert np.all(plan.background==255)
    assert np.count_nonzero(plan.retired)>0
    assert path.read_bytes()==original


def test_real_intersecting_line_is_revealed_rather_than_erased(tmp_path):
    gray,evidence,_=source(tmp_path,line=True)
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert len(plan.texts)==1,plan.records
    assert np.all(plan.background[180,145:235]<128)
    assert plan.records[0]["shared_structure_pixels"]>0
    assert np.count_nonzero(plan.background<128)<np.count_nonzero(gray<128)


def test_covered_native_object_does_not_reappear(tmp_path):
    gray,evidence,_=source(tmp_path,hidden=True)
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert not plan.texts
    assert np.array_equal(plan.background,gray)
    assert any(r.get("reason")=="NATIVE_PAINT_OCCLUDED_OR_NOT_VISIBLE" for r in plan.records)


@pytest.mark.parametrize("hidden",["black","partial-black"])
def test_dark_area_occlusion_does_not_resurrect_whole_glyphs(tmp_path,hidden):
    gray,evidence,_=source(tmp_path,hidden=hidden)
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert not plan.texts
    assert np.array_equal(plan.background,gray)
    assert any(r.get("reason")=="NATIVE_GLYPH_OVERLAPS_PAINTED_AREA" for r in plan.records)


def test_matched_route_cannot_fix_a_missing_candidate(tmp_path):
    gray,evidence,_=source(tmp_path)
    plan=collect_native_text(gray,evidence,(),mode="matched")
    assert not plan.texts and np.array_equal(plan.background,gray)
    wrong=TextCandidate("Q7",(140,140,110,80),.9,"text")
    plan=collect_native_text(gray,evidence,(wrong,),mode="independent")
    assert [t.text for t in plan.texts]==["P7"]
    # Independent entry never throws away a pre-existing mixed OCR row. The
    # service reads its remaining paint afresh, after native object separation.
    assert plan.suppressed_ocr==[]


def test_missing_font_glyph_proof_preserves_existing_branch(tmp_path,monkeypatch):
    gray,evidence,_=source(tmp_path)
    monkeypatch.setattr("app.ocr.pdf_native_text._mapping_evidence",lambda *_:(180,[]))
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert not plan.texts
    assert np.array_equal(plan.background,gray)
    assert any(r.get("reason")=="EMBEDDED_CMAP_GLYPH_NOT_CONFIRMED" for r in plan.records)


def test_mirrored_source_cannot_become_unmirrored_cad_text(tmp_path):
    gray,evidence,_=source(tmp_path,mirror=True)
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert not plan.texts
    assert np.array_equal(plan.background,gray)
    assert any(r.get("reason")=="NATIVE_REFLECTED_TEXT_UNSUPPORTED" for r in plan.records)


def test_page_rotation_keeps_source_reading_basis(tmp_path):
    gray,evidence,_=source(tmp_path,page_rotation=90)
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert [t.text for t in plan.texts]==["P7"],plan.records
    q=np.asarray(plan.texts[0].quad)
    assert q[1,1]>q[0,1] and abs(q[1,0]-q[0,0])<1e-6


def test_two_parsers_agreeing_on_a_wrong_tounicode_does_not_prove_content(tmp_path):
    gray,_,original=source(tmp_path)
    wrong=tmp_path/"wrong-mapping.pdf"
    with pymupdf.open(original) as doc:
        font=doc[0].get_fonts(full=True)[0][0]
        _,key=doc.xref_get_key(font,"ToUnicode")
        # The printed glyph remains P (gid 51), but both text parsers now
        # report Q. The embedded font's cmap still maps P to that actual glyph.
        doc.update_stream(int(key.split()[0]),b"""/CIDInit /ProcSet findresource begin
12 dict begin begincmap /CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def
/CMapName /Test-UCS def /CMapType 2 def
1 begincodespacerange <0000> <ffff> endcodespacerange
2 beginbfchar <0033> <0051> <001a> <0037> endbfchar
endcmap CMapName currentdict /CMap defineresource pop end end""")
        doc.save(wrong)
    with pymupdf.open(wrong) as doc:
        assert "Q7" in doc[0].get_text()
    with pdfium.PdfDocument(wrong) as doc:
        page=doc[0]
        tp=page.get_textpage()
        assert "Q7" in tp.get_text_range()
        bitmap=page.render(scale=2,grayscale=True)
        assert np.array_equal(gray,np.array(bitmap.to_pil().convert("L")))
        bitmap.close()
        tp.close()
        page.close()
    evidence=SimpleNamespace(binding=pdf_geometry_binding(wrong,0,144))
    plan=collect_native_text(gray,evidence,(),mode="independent")
    assert not plan.texts
    assert any(r.get("reason")=="EMBEDDED_CMAP_GLYPH_NOT_CONFIRMED" for r in plan.records)


@pytest.mark.parametrize("production_omissions", [False, True])
def test_normal_service_cache_and_actual_export_keep_native_text(
    tmp_path, monkeypatch, production_omissions,
):
    import ezdxf
    from app.core.processing import ProductionProcessingService, ProductionProcessingConfig
    from app.core.cache import save_trace_cache, load_trace_cache
    from app.core.scale_calibrator import ScaleCalibration
    from app.export.trace_single_export import export_final_structure_dxf

    gray,evidence,_=source(tmp_path,line=True)
    # Arc/fill consumers expect their own typed evidence. The text source
    # binding comes from the ordinary loader, rather than a test-only carrier.
    from app.core.image_loader import load_image
    geometry=[]
    image=load_image(evidence.binding["document"],page_index=0,pdf_dpi=144,
                     grayscale=True,pdf_geometry_sink=geometry)
    if production_omissions:
        monkeypatch.setattr(
            "app.geometry.optimized_trace.recognize_text_candidates_optimized",
            lambda *args, **kwargs: ((), ()),
        )
        config = ProductionProcessingConfig(source_dpi=144)
    else:
        config = ProductionProcessingConfig(
            source_dpi=144, enable_ocr=False, experimental_pdf_native_text="independent",
        )
    result = ProductionProcessingService.process_page(image, config, pdf_geometry=geometry[0])
    assert [t.text for t in result.final_structure.texts]==["P7"]
    cache=tmp_path/"run.npz"
    save_trace_cache(cache,result)
    restored=load_trace_cache(cache)
    assert restored.final_structure.texts==result.final_structure.texts
    assert restored.final_structure.provenance["pdf_native_text"]["mode"] == (
        "omissions" if production_omissions else "independent"
    )
    assert restored.final_structure.provenance["pdf_native_text"]["records"][0]["decision"]=="ADOPTED"
    dxf=tmp_path/"first.dxf"
    export_final_structure_dxf(restored.final_structure,dxf,
                               ScaleCalibration((0,0),(1,0),25.4/144),allow_empty=True)
    actual=ezdxf.readfile(dxf)
    assert [e.dxf.text for e in actual.modelspace().query("TEXT")]==["P7"]
    assert any(e.dxftype() in {"LINE","LWPOLYLINE"} for e in actual.modelspace())


def test_remaining_path_paint_is_sent_to_ocr_after_native_separation(tmp_path,monkeypatch):
    from app.core.image_loader import load_image
    from app.core.processing import ProductionProcessingConfig,ProductionProcessingService

    _,_,path=source(tmp_path)
    mixed=tmp_path/"mixed.pdf"
    with pymupdf.open(path) as doc:
        doc[0].draw_polyline([(112,82),(124,82),(112,98),(124,98)],color=(0,0,0),width=1)
        doc[0].draw_polyline([(20,20),(35,35),(20,50)],color=(0,0,0),width=1)
        doc.save(mixed)
    geometry=[]
    image=load_image(mixed,page_index=0,pdf_dpi=144,grayscale=True,pdf_geometry_sink=geometry)
    seen=[]

    def read_remaining(gray,**kwargs):
        seen.append(gray.copy())
        if len(seen)==1:
            return (TextCandidate("P7Z",(155,155,105,50),.99,"text_candidate",
                    quad=((155,155),(260,155),(260,205),(155,205)),
                    character_boxes=((160,160,40,40),(220,160,32,40))),),()
        return (
            TextCandidate("Z",(220,160,32,40),.99,"text_candidate",
                quad=((220,160),(252,160),(252,200),(220,200)),character_boxes=((220,160,32,40),)),
            TextCandidate(">",(30,30,50,80),.99,"text_candidate",
                quad=((30,30),(80,30),(80,110),(30,110))),
        ),()

    monkeypatch.setattr("app.geometry.optimized_trace.recognize_text_candidates_optimized",read_remaining)
    result=ProductionProcessingService.process_page(image,ProductionProcessingConfig(
        source_dpi=144,enable_ocr=True,experimental_pdf_native_text="independent"),pdf_geometry=geometry[0])
    assert len(seen)==2
    assert np.any(seen[0][155:200,155:205]<128)
    assert np.all(seen[1][155:200,155:205]==255)  # The native P7 was separated.
    assert np.any(seen[1][160:200,220:252]<128)  # Path lettering is still read.
    assert sorted(t.text for t in result.final_structure.texts)==["P7","Z"]
    assert result.final_structure.provenance["pdf_native_text"]["suppressed_ocr_indices"]==(0,)


def test_unread_mixed_remainder_rolls_back_only_its_native_source_object(tmp_path,monkeypatch):
    from app.core.image_loader import load_image
    from app.core.processing import ProductionProcessingConfig,ProductionProcessingService

    _,_,path=source(tmp_path)
    mixed=tmp_path/"mixed-unread.pdf"
    with pymupdf.open(path) as doc:
        page=doc[0]
        page.draw_polyline([(112,82),(124,82),(112,98),(124,98)],color=(0,0,0),width=1)
        page.insert_font(fontname="SecondFont",fontfile=str(Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts/arial.ttf"))
        page.insert_text((20,140),"R4",fontname="SecondFont",fontsize=16)
        doc.save(mixed)
    geometry=[]
    image=load_image(mixed,page_index=0,pdf_dpi=144,grayscale=True,pdf_geometry_sink=geometry)
    seen=[]
    original=TextCandidate("P7Z",(155,155,105,50),.99,"text_candidate",
        quad=((155,155),(260,155),(260,205),(155,205)),
        character_boxes=((160,160,40,40),(220,160,32,40)))

    def read_remaining(gray,**kwargs):
        seen.append(gray)
        return ((original,) if len(seen)==1 else ()),()

    monkeypatch.setattr("app.geometry.optimized_trace.recognize_text_candidates_optimized",read_remaining)
    result=ProductionProcessingService.process_page(image,ProductionProcessingConfig(
        source_dpi=144,enable_ocr=True,experimental_pdf_native_text="independent"),pdf_geometry=geometry[0])
    assert sorted(t.text for t in result.final_structure.texts)==["P7Z","R4"]
    records=result.final_structure.provenance["pdf_native_text"]["records"]
    assert [r["text"] for r in records if r["decision"]=="ADOPTED"]==[("R4",)]
    assert any(r.get("reason")=="UNRESOLVED_MIXED_SOURCE_CARRIER" for r in records)


def test_legacy_fallback_uses_original_canvas_and_native_fixed_neighbors(tmp_path,monkeypatch):
    from app.core.image_loader import load_image
    from app.core.processing import ProductionProcessingConfig,ProductionProcessingService

    _,_,path=source(tmp_path,line=True)
    geometry=[]
    image=load_image(path,page_index=0,pdf_dpi=144,grayscale=True,pdf_geometry_sink=geometry)
    seen=[]

    def existing_fallback(gray,texts,*args,**kwargs):
        seen.append((gray.copy(),texts))
        return tuple(texts)

    monkeypatch.setattr("app.ocr.native_source_row.recover_native_source_rows",existing_fallback)
    result=ProductionProcessingService.process_page(image,ProductionProcessingConfig(
        source_dpi=144,enable_ocr=False,experimental_pdf_native_text="independent",
        experimental_native_source_row=True),pdf_geometry=geometry[0])
    assert len(seen)==1 and np.array_equal(seen[0][0],image)
    assert [t.text for t in seen[0][1]]==["P7"]
    assert [t.text for t in result.final_structure.texts]==["P7"]
