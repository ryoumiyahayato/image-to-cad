"""Real strict source proof + packaged LFF; no OCR simulation in production."""
from dataclasses import asdict, replace

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QGuiApplication

from app.core.structure import FinalStructure
from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import glyph_footprint
from app.geometry.line_detect import LineSegment
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr import proven_row_group_display as module


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def sample(offset=(0, 0), scale=1):
    image = np.full((95, 150), 255, np.uint8)
    cv2.putText(image, "ALPHA", (25, 39), cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 1)
    cv2.putText(image, "BRAVO", (25, 64), cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 1)
    rows = tuple(TextCandidate(text, (16, y, 112, 37), .99, "text_candidate",
                              source="rapidocr-test", replacement_safe=False)
                 for text, y in (("ALPHA", 10), ("BRAVO", 35)))
    dx, dy = offset
    gray = np.full((95*scale+dy+5, 150*scale+dx+5), 255, np.uint8)
    gray[dy:dy+95*scale, dx:dx+150*scale] = cv2.resize(
        image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST,
    )
    rows = tuple(replace(t, bbox=(t.bbox[0]*scale+dx,t.bbox[1]*scale+dy,
                                 t.bbox[2]*scale,t.bbox[3]*scale)) for t in rows)
    source = np.where(gray < 128, 255, 0).astype(np.uint8)
    structure = FinalStructure(gray.shape[::-1], np.full_like(gray,255), (),
                               texts=rows, source_text_outline_mask=source,
                               provenance={"text_residual_retirement": {"frozen": [1,2,3]}})
    return gray, structure


def paths(structure):
    return [glyph_footprint(native_text_placement(t, transform=lambda x,y:
            (x,structure.source_size_px[1]-y))) for t in structure.texts]


def pairs(structure):
    items = paths(structure)
    return {(i,j) for i,p in enumerate(items) for j,q in enumerate(items) if i<j and p.intersects(q)}


@pytest.mark.parametrize("offset,scale", [((0,0),1),((39,27),1),((15,13),2)])
def test_source_proven_fit_changes_only_display_with_translation_scale(offset, scale):
    gray, before = sample(offset,scale)
    old_gray = gray.copy()
    after = module.refine_proven_row_group_displays(gray,before)
    assert after is not before
    assert pairs(before) and not pairs(after)
    assert after.source_structure_id == before.source_structure_id
    assert after.provenance["text_residual_retirement"] == before.provenance["text_residual_retirement"]
    assert np.array_equal(gray,old_gray)
    for old,new in zip(before.texts,after.texts,strict=True):
        a,b=asdict(old),asdict(new)
        assert b.pop("display_quad") is not None
        a.pop("display_quad")
        assert a==b
    for field in ("contour_binary","preview_binary","editable_text_source_mask",
                  "source_text_outline_mask","uncertain_text_outline_mask"):
        assert np.array_equal(getattr(before,field),getattr(after,field))
    assert module.refine_proven_row_group_displays(gray,after) is after
    proof=after.provenance["proven_row_group_display"]
    assert proof["authority"]=="DISPLAY_ONLY" and proof["source_deletion_authority"] is False
    assert proof["rows"][0]["source_strong_runs"]


@pytest.mark.parametrize("unsafe", ["joined","boundary","manual","rotation","existing-display",
                                     "operators","pure-numeric","unapproved","wrong-kind",
                                     "non-rapidocr","source-shape","source-dtype","review-snapshot"])
def test_unsafe_or_out_of_scope_input_keeps_exact_original(unsafe):
    gray,before=sample()
    rows=before.texts
    if unsafe=="joined":
        cv2.line(gray,(55,30),(55,60),0,2)
    elif unsafe=="boundary":
        cv2.line(gray,(14,9),(14,70),0,1)
    elif unsafe in {"manual","rotation","existing-display","unapproved","wrong-kind","non-rapidocr"}:
        updates={"manual":dict(reviewed=True),"rotation":dict(rotation_deg=90),
                 "existing-display":dict(display_quad=((16,10),(128,10),(128,47),(16,47))),
                 "unapproved":dict(approved=False),"wrong-kind":dict(kind="symbol"),
                 "non-rapidocr":dict(source="manual")}
        rows=(replace(rows[0],**updates[unsafe]),rows[1])
        before=replace(before,texts=rows)
    elif unsafe=="operators":
        before=replace(before,texts=tuple(replace(t,text=t.text+"#") for t in rows))
    elif unsafe=="pure-numeric":
        before=replace(before,texts=tuple(replace(t,text="12345") for t in rows))
    elif unsafe=="source-shape":
        gray=gray[:-1]
    elif unsafe=="source-dtype":
        gray=gray.astype(np.float32)
    elif unsafe=="review-snapshot":
        before=replace(before,provenance={"review_snapshot_v1": {"id":"saved"}})
    assert module.refine_proven_row_group_displays(gray,before) is before


@pytest.mark.parametrize("error", [ValueError,RuntimeError,OSError,KeyError])
def test_controlled_export_or_font_failure_commits_no_partial_layout(monkeypatch,error):
    gray,before=sample()
    def fail(*args,**kwargs):
        raise error("controlled fixture failure")
    monkeypatch.setattr(module,"ReviewLayoutGuard",fail)
    assert module.refine_proven_row_group_displays(gray,before) is before


@pytest.mark.parametrize("budget,value", [("texts",1),("page_pixels",100),("groups",0),
                                          ("source_pixels",1),("seconds",0)])
def test_budgets_abstain_without_mutation(monkeypatch,budget,value):
    gray,before=sample()
    monkeypatch.setitem(module.BUDGETS,budget,value)
    assert module.refine_proven_row_group_displays(gray,before) is before


def added_paper_point(gray,before,after,index=0):
    added=paths(after)[index].subtracted(paths(before)[index])
    height=gray.shape[0]
    return next((x,y) for y in range(gray.shape[0]) for x in range(gray.shape[1])
                if gray[y,x]==255 and added.contains(QPointF(x+.5,height-y-.5)))


def test_actual_emitted_line_blocks_new_glyph_contact_without_changing_line():
    gray,before=sample()
    proposal=module.refine_proven_row_group_displays(gray,before)
    x,y=added_paper_point(gray,before,proposal)
    line=LineSegment(x+.3,y+.5,x+.7,y+.5,width=.1)
    protected=replace(before,straight_lines=(line,))
    after=module.refine_proven_row_group_displays(gray,protected)
    assert after.texts[0]==protected.texts[0]
    assert after.straight_lines==protected.straight_lines
    assert after.source_structure_id==protected.source_structure_id
    assert pairs(after)<=pairs(protected)


@pytest.mark.parametrize("late_phase", ["hash", "final-snapshot"])
def test_late_elapsed_budget_discards_all_prepared_layouts(monkeypatch,late_phase):
    gray,before=sample()
    clock={"value":0.0}
    monkeypatch.setattr(module,"perf_counter",lambda:clock["value"])
    if late_phase=="hash":
        real=module.sha256
        def late_hash(data):
            result=real(data);clock["value"]=31.0
            return result
        monkeypatch.setattr(module,"sha256",late_hash)
    else:
        real=module.replace
        def late_replace(obj,**changes):
            result=real(obj,**changes)
            if isinstance(obj,FinalStructure) and "proven_row_group_display" in changes.get("provenance",{}):
                clock["value"]=31.0
            return result
        monkeypatch.setattr(module,"replace",late_replace)
    assert module.refine_proven_row_group_displays(gray,before) is before


def test_missing_exact_font_does_not_outline_or_change_text(monkeypatch):
    gray,before=sample()
    monkeypatch.setattr(module,"librecad_font_available",lambda:False)
    assert module.refine_proven_row_group_displays(gray,before) is before


def test_unknown_formal_geometry_abstains(monkeypatch):
    gray,before=sample()
    real=module.ReviewLayoutGuard
    def unknown(structure):
        guard=real(structure);guard.unknown.add("unsupported fixture entity")
        return guard
    monkeypatch.setattr(module,"ReviewLayoutGuard",unknown)
    assert module.refine_proven_row_group_displays(gray,before) is before


def test_cache_and_actual_dxf_keep_native_strings_source_and_layout(tmp_path):
    from app.core.cache import save_trace_cache,load_trace_cache
    from app.geometry.raster_trace import RasterTraceResult
    from app.export.trace_single_export import export_final_structure_dxf
    import ezdxf
    gray,before=sample();after=module.refine_proven_row_group_displays(gray,before)
    result=RasterTraceResult(binary=after.contour_binary,stages={},paths=(),threshold=128,
                             foreground_pixels=0,vertex_count=0,texts=after.texts,final_structure=after)
    save_trace_cache(tmp_path/"cache.npz",result)
    restored=load_trace_cache(tmp_path/"cache.npz").final_structure
    assert restored.texts==after.texts
    assert restored.source_structure_id==before.source_structure_id
    assert restored.provenance["proven_row_group_display"]==after.provenance["proven_row_group_display"]
    export_final_structure_dxf(restored,tmp_path/"native.dxf",allow_empty=True)
    doc=ezdxf.readfile(tmp_path/"native.dxf")
    assert [e.dxf.text for e in doc.modelspace().query("TEXT")]==["ALPHA","BRAVO"]
    assert doc.audit().has_errors is False
