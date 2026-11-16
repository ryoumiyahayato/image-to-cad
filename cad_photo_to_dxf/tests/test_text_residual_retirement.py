"""Source-member proof counterexamples; no OCR replacement in production tests."""
from dataclasses import asdict

import cv2
import numpy as np
import pytest

from app.geometry.text_residual_retirement import (
    exclusive_source_members, path_source_members, pixel_runs,
    propose_verified_row_retirement, source_box_inside_cell,
)
from app.ocr.ruled_cell_display import refine_ruled_cell_row_displays


def member_sample():
    only = np.full((18, 26), 255, np.uint8)
    only[5:10, 5:11] = 0
    only[4, 5:11] = 200
    only[10, 5:11] = 254
    rows = np.zeros(only.shape, np.uint8)
    rows[5:10, 5:11] = 1
    return only, rows, np.zeros(only.shape, bool)


@pytest.mark.parametrize('dx,dy', [(0,0),(4,3)])
def test_exact_source_member_and_weak_fringe_survive_translation(dx,dy):
    only,rows,protected=member_sample()
    only=np.pad(only,((dy,0),(dx,0)),constant_values=255)
    rows=np.pad(rows,((dy,0),(dx,0)))
    protected=np.pad(protected,((dy,0),(dx,0)))
    before=only.copy()
    members,reason=path_source_members(only,rows,protected,254)
    assert reason=='PROVEN_PATH_MEMBERS'
    assert np.array_equal(members,only<255)
    assert np.array_equal(only,before)
    restored=np.zeros_like(members)
    for y,x0,x1 in pixel_runs(members):
        restored[y,x0:x1]=True
    assert np.array_equal(restored,members)


@pytest.mark.parametrize('unsafe', ['foreign-strong','shared-strong','weak-only','protected-strong','protected-weak'])
def test_uncertain_path_or_any_protected_source_abstains(unsafe):
    only,rows,protected=member_sample()
    if unsafe=='foreign-strong':
        only[5,10]=0
        rows[5,10]=0
    elif unsafe=='shared-strong':
        rows[5,10]=2
    elif unsafe=='weak-only':
        only[14,20]=200
    elif unsafe=='protected-strong':
        protected[7,8]=True
    else:
        protected[10,8]=True
    members,reason=path_source_members(only,rows,protected,254)
    assert not np.any(members)
    assert reason in {'FOREIGN_OR_SHARED_STRONG_SOURCE','WEAK_ONLY_SOURCE_COMPONENT','PROTECTED_SOURCE_CONTACT'}


def test_attached_unknown_weak_tail_is_retained_not_entire_path_erased():
    only,rows,protected=member_sample()
    only[7,11:22]=200
    members,reason=path_source_members(only,rows,protected,254)
    assert reason=='PARTIAL_WEAK_TAIL_ABSTAIN'
    assert np.all(members[5:10,5:11])
    assert not np.any(members[7,12:22])
    assert np.array_equal(only[7,12:22],np.full(10,200,np.uint8))


def test_shared_prepared_carrier_does_not_imply_shared_source_retirement():
    a,rows,protected=member_sample()
    b=np.full_like(a,255)
    b[12:15,5:11]=0
    source=np.minimum(a,b)
    source[10:13,8]=np.minimum(source[10:13,8],200)
    # Only source A is independently proven. The weak carrier and B retain ink.
    members,_=path_source_members(a,rows,protected,254)
    moved=exclusive_source_members(source,a,b,members,source<255,protected,254)
    assert np.any(moved)
    assert not np.any(moved[11:15])
    assert np.all(source[12:15,5:11]==0)


@pytest.mark.parametrize('unsafe', ['underpaint','source-different','not-visible','protected'])
def test_counterfactual_or_final_ownership_exclusions_are_pixel_exact(unsafe):
    only,rows,protected=member_sample()
    members,_=path_source_members(only,rows,protected,254)
    source=only.copy()
    without=np.full_like(only,255)
    visible=only<255
    pixel=(7,8)
    if unsafe=='underpaint':
        without[pixel]=254
    elif unsafe=='source-different':
        source[pixel]=1
    elif unsafe=='not-visible':
        visible[pixel]=False
    else:
        protected[pixel]=True
    moved=exclusive_source_members(source,only,without,members,visible,protected,254)
    assert not moved[pixel]
    assert np.count_nonzero(moved)==np.count_nonzero(members)-1


def test_no_pdf_or_non_digital_source_never_changes_visible_members():
    gray=np.full((20,30),255,np.uint8)
    moved,records=propose_verified_row_retirement(gray,gray,(),{},visible=gray<128,protected_source_masks=())
    assert not np.any(moved) and records==[]


def test_display_proof_sidechannel_preserves_original_candidates():
    # Existing content-independent row fixture, not a fixed production candidate.
    from app.ocr.auxiliary_recognition import TextCandidate
    gray=np.full((110,150),255,np.uint8)
    for x in (28,83):
        cv2.rectangle(gray,(x,25),(x+14,43),0,1)
        cv2.line(gray,(x,34),(x+14,34),0,1)
    cv2.putText(gray,'Sample',(43,64),cv2.FONT_HERSHEY_SIMPLEX,.4,0,1)
    texts=(TextCandidate('中文',(22,18,85,36),.99,'text_candidate',rotation_deg=2,
                         quad=((22,18),(107,21),(107,54),(22,51)),source='rapidocr-test',replacement_safe=False),
           TextCandidate('Sample',(38,48,60,23),.99,'text_candidate',source='rapidocr-test',replacement_safe=False))
    cells={(10,10,130,90):tuple((t.text,t.bbox) for t in texts)}
    proofs=[]
    expected=refine_ruled_cell_row_displays(gray,texts,cells)
    actual=refine_ruled_cell_row_displays(gray,texts,cells,source_proof_sink=proofs)
    assert actual==expected and len(proofs)==1
    indexes,proof=proofs[0]
    assert indexes==(0,1)
    assert np.all(gray[10:90,10:130][proof.mask>0]<128)
    for before,after in zip(texts,actual[0],strict=True):
        a,b=asdict(before),asdict(after)
        a.pop('display_quad')
        b.pop('display_quad')
        assert a==b


@pytest.mark.parametrize('box', [(12,15,18,15),(12,15,12,19),(12,15,12,15)])
def test_integer_mapped_thin_strokes_are_shortlisted_not_silently_lost(box):
    assert source_box_inside_cell(box,(10,10,30,30))
    assert not source_box_inside_cell((9,15,18,15),(10,10,30,30))
    assert not source_box_inside_cell((12,float('nan'),18,15),(10,10,30,30))


def test_group_unknown_tail_cannot_borrow_another_path_authority():
    a=np.full((14,16),255,np.uint8)
    a[4,3:7]=0
    a[4,7:12]=200
    row_a=np.zeros_like(a)
    row_a[4,3:7]=1
    b=np.full_like(a,255)
    b[4,10]=0
    b[5,10]=0
    row_b=np.zeros_like(a)
    row_b[b<128]=1
    blank=np.zeros(a.shape,bool)
    ma,_=path_source_members(a,row_a,blank,254)
    mb,_=path_source_members(b,row_b,blank,254)
    unknown=((a<=254)&~ma)|((b<=254)&~mb)
    group=np.minimum(a,b)
    moved=exclusive_source_members(group,group,np.full_like(group,255),ma|mb,group<255,unknown,254)
    assert not moved[4,10]
    assert moved[4,3]


def pdf_source_fixture(tmp_path):
    """Real PDF paint + explicit trusted-row fixture; does not simulate OCR."""
    fitz=pytest.importorskip('fitz')
    import pypdfium2 as pdfium
    from app.geometry.pdf_arc_evidence import PdfGeometryEvidence,pdf_geometry_binding
    from app.ocr.auxiliary_recognition import TextCandidate
    from app.ocr.ocr_layout import VerifiedCellTextSource
    path=tmp_path/'source.pdf'
    doc=fitz.open()
    page=doc.new_page(width=100,height=80)
    page.draw_rect(fitz.Rect(20,15,32,30),color=None,fill=(0,0,0))
    page.draw_rect(fitz.Rect(20,45,32,60),color=None,fill=(0,0,0))
    page.draw_rect(fitz.Rect(80,5,84,75),color=None,fill=(0,0,0))
    doc.save(path)
    doc.close()
    pdf=pdfium.PdfDocument(path)
    page=pdf[0]
    bitmap=page.render(scale=1,grayscale=True)
    gray=np.array(bitmap.to_pil().convert('L'))
    bitmap.close()
    page.close()
    pdf.close()
    bounds=(5,5,75,75)
    left,top,right,bottom=bounds
    strong=gray[top:bottom,left:right]<128
    row1=strong.copy()
    row1[30:]=False
    row2=strong.copy()
    row2[:30]=False
    quads=(((15,10),(40,10),(40,35),(15,35)),((15,40),(40,40),(40,65),(15,65)))
    texts=tuple(TextCandidate(name,box,.99,'text_candidate',source='rapidocr-unit',approved=True,quad=quad,display_quad=quad) for name,box,quad in zip(('Alpha','Beta'),((15,10,25,25),(15,40,25,25)),quads))
    proof=VerifiedCellTextSource(bounds,strong.astype(np.uint8)*255,texts,(row1.astype(np.uint8)*255,row2.astype(np.uint8)*255))
    geometry=PdfGeometryEvidence(pdf_geometry_binding(path,0,72),(100,80),())
    binary=np.where(gray<=254,0,255).astype(np.uint8)
    return path,gray,binary,texts,(((0,1),proof),),geometry


def test_real_pdf_member_extraction_is_readonly_and_preserves_foreign_paint(tmp_path):
    path,gray,binary,texts,proofs,geometry=pdf_source_fixture(tmp_path)
    original=path.read_bytes()
    moved,records=propose_verified_row_retirement(binary,gray,texts,proofs,visible=binary<128,protected_source_masks=(),pdf_geometry=geometry,clean_digital=True)
    assert np.any(moved),records
    assert not np.any(moved[:,80:85])
    assert path.read_bytes()==original
    recovered=np.zeros_like(moved)
    for record in records:
        assert record.get('ownership_scope')=='JOINT_VERIFIED_ROW_SOURCE_GROUP'
        for y,x0,x1 in record['retired_runs']:
            assert not np.any(recovered[y,x0:x1])
            recovered[y,x0:x1]=255
    assert np.array_equal(recovered,moved)


@pytest.mark.parametrize('unsafe',['layout','source-gray','prepared-threshold','protected-weak','source-binding','native-fill'])
def test_real_pdf_unsafe_binding_or_source_representation_abstains(tmp_path,unsafe):
    from dataclasses import replace
    from types import SimpleNamespace
    path,gray,binary,texts,proofs,geometry=pdf_source_fixture(tmp_path)
    protected=np.zeros_like(gray)
    if unsafe=='layout':
        texts=(replace(texts[0],display_quad=((0,0),(1,0),(1,1),(0,1))),texts[1])
    elif unsafe=='source-gray':
        gray[0,0]=254
        binary[0,0]=0
    elif unsafe=='prepared-threshold':
        binary[0,0]=0
    elif unsafe=='protected-weak':
        protected[binary<128]=255
    elif unsafe=='source-binding':
        geometry=replace(geometry,source_size_px=(99,80))
    else:
        geometry=replace(geometry,native_fills=tuple(SimpleNamespace(source=SimpleNamespace(object_index=i)) for i in range(3)))
    moved,records=propose_verified_row_retirement(binary,gray,texts,proofs,visible=binary<128,protected_source_masks=(protected,),pdf_geometry=geometry,clean_digital=True)
    assert not np.any(moved),records
    assert any(record['decision']=='ABSTAIN' for record in records)


@pytest.mark.parametrize('failure_call',[2,3,4,5,6])
def test_real_pdf_render_fault_never_publishes_partial_retirement(tmp_path,monkeypatch,failure_call):
    import app.geometry.text_residual_retirement as module
    path,gray,binary,texts,proofs,geometry=pdf_source_fixture(tmp_path)
    original_bytes=path.read_bytes()
    render=module._render
    calls=0
    states=[]
    def fault(page,scale):
        nonlocal calls
        import ctypes as ct
        import pypdfium2 as pdfium
        calls+=1
        state=[]
        for obj in page.get_objects(max_depth=1):
            active=pdfium.raw.FPDF_BOOL()
            assert pdfium.raw.FPDFPageObj_GetIsActive(obj,ct.byref(active))
            state.append(active.value)
        states.append(state)
        if calls==failure_call:
            raise RuntimeError('injected render failure')
        return render(page,scale)
    monkeypatch.setattr(module,'_render',fault)
    moved,records=module.propose_verified_row_retirement(binary,gray,texts,proofs,visible=binary<128,protected_source_masks=(),pdf_geometry=geometry,clean_digital=True)
    assert not np.any(moved)
    assert records and all(row['decision']=='ABSTAIN' for row in records)
    assert states[-1]==states[0]
    assert path.read_bytes()==original_bytes


def test_joint_source_owner_roundtrips_fringe_outside_original_candidate_bbox(tmp_path):
    from types import SimpleNamespace
    from app.core.cache import save_trace_cache,load_trace_cache
    from app.core.structure_build import build_final_structure
    from app.core.structure import metadata_to_jsonable
    from app.ocr.auxiliary_recognition import TextCandidate
    visible=np.full((12,16),255,np.uint8)
    fringe=np.zeros_like(visible)
    fringe[4,4]=255
    text=TextCandidate('Sample',(5,4,5,5),.99,'text_candidate',approved=True,quad=((5,4),(10,5),(9,9),(5,9)))
    record={'ownership_scope':'JOINT_VERIFIED_ROW_SOURCE_GROUP','text_indices':[0],
            'retired_runs':pixel_runs(fringe),'retired_pixels':1,
            'candidate_counter_scope':'original-footprint intersection, not complete joint-group source'}
    structure=build_final_structure(source_size_px=(16,12),contour_binary=visible,contours=(),texts=(text,),
        editable_text_source_mask=fringe,source_text_outline_mask=fringe,
        provenance={'text_residual_retirement':[record]})
    cache=tmp_path/'joint-source.npz'
    save_trace_cache(cache,SimpleNamespace(final_structure=structure))
    loaded=load_trace_cache(cache).final_structure
    records=metadata_to_jsonable(loaded.provenance)['text_residual_retirement']
    assert records==[record]
    reconstructed=np.zeros_like(fringe)
    for y,x0,x1 in records[0]['retired_runs']:
        reconstructed[y,x0:x1]=255
    assert np.array_equal(reconstructed,loaded.source_text_outline_mask)
    assert np.array_equal(reconstructed,loaded.editable_text_source_mask)
    assert loaded.texts[0].bbox[0]>4 and reconstructed[4,4]==255
