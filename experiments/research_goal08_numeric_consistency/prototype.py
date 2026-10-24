"""Read-only source-backed numeric review hints. No labels, OCR calls, or DXF writes."""
import os,sys,json,re,ctypes as ct,time,argparse,collections
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode=True
import cv2,numpy as np,pypdfium2 as pdfium
ROOT=Path(__file__).resolve().parents[2]
STABLE=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
PARAMS={'version':'goal08-v2','context_padding_in_OCR_heights':1.0,'max_rotation_degrees':2.,'isolated_core_gray_max':180,'minimum_core_pixels':6,'minimum_visible_core_fraction':.90,'minimum_source_darkening':8,'max_numeric_objects':32,'max_paint_proofs':24,'max_fragments':16}
QUOTES=str.maketrans({'’':"'",'‘':"'",'′':"'",'”':'"','“':'"','″':'"'})
UNITS={'in','inch','inches','ft','feet','foot','mm','cm','m','degrees','degree','gauge','dia','min','max'}
def signature(text):
    # Lexical atoms keep 1 1/4 distinct from 11/4, while spacing before a unit
    # cannot manufacture a discrepancy. Attached specification letters stay.
    s=text.translate(QUOTES)
    atoms=list(re.finditer(r'\d+(?:[.,]\d+)?|[^\W\d_]+|[^\w\s]',s,re.UNICODE))
    keep={i for i,a in enumerate(atoms) if any(c.isnumeric() for c in a.group())}
    pending=list(keep)
    while pending:
        i=pending.pop()
        for j in [i-1,i+1]:
            if j<0 or j>=len(atoms) or j in keep:continue
            a,b=atoms[min(i,j)],atoms[max(i,j)];v=atoms[j].group()
            attached=a.end()==b.start()
            punctuation=not any(c.isalnum() for c in v)
            if punctuation or v.casefold() in UNITS or attached:
                keep.add(j);pending.append(j)
    return [a.group().casefold() for i,a in enumerate(atoms) if i in keep]
def center_in(b,r):
    x,y,w,h=b;return r[0]<=x+w/2<r[2] and r[1]<=y+h/2<r[3]
def contained(b,q):return q[0]<=b[0] and q[1]<=b[1] and b[2]<=q[2] and b[3]<=q[3]
def render(page,scale):
    b=page.render(scale=scale,grayscale=True)
    try:return np.array(b.to_pil().convert('L'))
    finally:b.close()
def existing_pairs(texts,evidence):
    sys.path.insert(0,str(STABLE))
    from app.core.native_text_review import bind_native_suggestions
    from app.geometry.pdf_text_suggestions import SUGGESTION_KEY
    structure=SimpleNamespace(provenance={SUGGESTION_KEY:evidence},source_size_px=evidence['source_size_px'],texts=[SimpleNamespace(**t) for t in texts])
    manifest={'source':{'path':evidence['source_path'],'physical_page':evidence['physical_page'],'cache_identity':{'dpi':evidence['dpi']}},'snapshot_uuid':'DIAGNOSTIC_NOT_A_SAVED_REVIEW_PROJECT','text_bindings':[{'index':i,'text_source_uuid':str(i)} for i in range(len(texts))]}
    return {x['binding']['index']:x['evidence'] for x in bind_native_suggestions(structure,manifest)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--normal-dir',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--roi',type=int,nargs=4,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    normal=json.loads((args.normal_dir/'result.json').read_text('utf8'));info=json.loads((args.normal_dir/'input.json').read_text('utf8'));evidence=json.loads((args.normal_dir/'native-suggestions.json').read_text('utf8'));texts=normal['texts']
    assert str(args.source.resolve())==evidence['source_path'] and info['physical_page']==evidence['physical_page'] and info['dpi']==evidence['dpi']
    source=cv2.imread(str(args.normal_dir/'source-page.png'),cv2.IMREAD_GRAYSCALE);assert source is not None and list(source.shape[::-1])==evidence['source_size_px']
    indices=[i for i,t in enumerate(texts) if center_in(t['bbox'],args.roi) and any(c.isdigit() for c in t['text'])]
    all_indices=[i for i,t in enumerate(texts) if center_in(t['bbox'],args.roi)]
    old=existing_pairs(texts,evidence);rows=evidence.get('rows',[]);requests={};reverse=collections.Counter()
    for i in indices:
        t=texts[i];x,y,w,h=t['bbox'];pad=h*PARAMS['context_padding_in_OCR_heights'];q=[x-pad,y-pad,x+w+pad,y+h+pad]
        matches=[j for j,row in enumerate(rows) if contained(row['bounds'],q)]
        requests[i]=(q,matches)
        if len(matches)==1:reverse[matches[0]]+=1
    d=pdfium.PdfDocument(str(args.source));page=d[info['physical_page']-1];tp=page.get_textpage();objects=list(page.get_objects(max_depth=1,textpage=tp));raw=pdfium.raw
    assert len(objects)==evidence['object_count'] and evidence['object_traversal_complete']
    states=[]
    for obj in objects:
        state=raw.FPDF_BOOL();assert raw.FPDFPageObj_GetIsActive(obj,ct.byref(state));states.append(state.value)
    scale=info['dpi']/72;reference=render(page,scale);assert np.array_equal(reference,source)
    output=[];proofs=0
    def switch(ids,without=False):
        for n,obj in enumerate(objects):
            value=(0 if n in ids else states[n]) if without else (states[n] if n in ids else 0)
            if not raw.FPDFPageObj_SetIsActive(obj,value):raise RuntimeError('Cannot switch PDF paint')
    def restore():
        for obj,state in zip(objects,states):
            if not raw.FPDFPageObj_SetIsActive(obj,state):raise RuntimeError('Cannot restore PDF paint')
    try:
        for ordinal,i in enumerate(indices):
            t=texts[i];q,matches=requests[i];record={'OCR_index':i,'OCR_text':t['text'],'OCR_bbox':t['bbox'],'OCR_signature':signature(t['text']),'OCR_confidence':t['confidence'],'state':'ABSTAIN','original_value_retained':True,'automatic_correction':False,'existing_native_binding':i in old,'existing_native_text':old[i]['text'] if i in old else None,'existing_numeric_conflict':i in old and signature(t['text'])!=signature(old[i]['text']),'context':q,'native_row_candidates':matches}
            reason=None
            if ordinal>=PARAMS['max_numeric_objects']:reason='OBJECT_BUDGET'
            elif abs(t.get('rotation_deg',0))>PARAMS['max_rotation_degrees']:reason='ROTATION_UNSUPPORTED'
            elif len(matches)!=1:reason='NO_UNIQUE_COMPLETE_NATIVE_ROW'
            elif reverse[matches[0]]!=1:reason='NATIVE_ROW_TO_MULTIPLE_OCR'
            else:
                row=rows[matches[0]];fragments=row.get('fragments',[]);ids={f['object'] for f in fragments}
                record.update(native_text_hypothesis=row['text'],native_bounds=row['bounds'],native_object_indices=sorted(ids),native_signature=signature(row['text']),unicode_status='UNVERIFIED_PDF_MAPPING',native_prior_reason=row.get('reason'))
                mapped=[c for f in fragments for c in f.get('chars',[])]
                if not 0<len(fragments)<=PARAMS['max_fragments'] or len(ids)!=len(fragments):reason='FRAGMENT_COUNT_OR_IDENTITY'
                elif not mapped or any(c.get('unicode') in (0,0xfffd) for c in mapped) or any(ord(c)<32 or c=='\ufffd' for c in row['text']):reason='INCOMPLETE_MAPPING'
                elif not all(f.get('no_clip') and objects[f['object']].type==raw.FPDF_PAGEOBJ_TEXT and objects[f['object']].extract()==f['text'] for f in fragments):reason='SOURCE_OBJECT_OR_CLIP_MISMATCH'
                elif not record['native_signature']:reason='NO_NATIVE_NUMERIC_SIGNATURE'
                elif proofs>=PARAMS['max_paint_proofs']:reason='PAINT_BUDGET'
                else:
                    proofs+=1;box=[max(0,int(min(row['bounds'][0],q[0]))-3),max(0,int(min(row['bounds'][1],q[1]))-3),min(source.shape[1],int(max(row['bounds'][2],q[2]))+4),min(source.shape[0],int(max(row['bounds'][3],q[3]))+4)];sl=np.s_[box[1]:box[3],box[0]:box[2]]
                    try:
                        switch(ids);isolated=render(page,scale)[sl].copy();switch(ids,True);without=render(page,scale)[sl].copy()
                    finally:restore()
                    restored=render(page,scale);equal=bool(np.array_equal(restored,reference));assert equal,'Restored source paint differs'
                    original=source[sl];core=isolated<PARAMS['isolated_core_gray_max'];darkening=without.astype(np.int16)-original.astype(np.int16);n=int(core.sum());visible=float(np.mean(darkening[core]>=PARAMS['minimum_source_darkening'])) if n else 0.
                    record['paint_proof']={'box':box,'core_pixels':n,'visible_core_fraction':visible,'restored_full_page_equal':equal,'same_parent_resolution':[source.shape[1],source.shape[0]],'background':'retained; no binarization OR, morphology, or source edit'}
                    prefix='object-'+str(i)
                    for suffix,img in [('source',original),('native-only',isolated),('without-native',without)]:cv2.imwrite(str(args.output/(prefix+'-'+suffix+'.png')),img)
                    if n<PARAMS['minimum_core_pixels'] or visible<PARAMS['minimum_visible_core_fraction']:reason='VISIBLE_SOURCE_SUPPORT_INSUFFICIENT'
                    elif record['OCR_signature']!=record['native_signature']:
                        record.update(state='REVIEW_CANDIDATE',reason='VISIBLE_NATIVE_NUMERIC_CONFLICT',review_authority='PENDING_HUMAN_CONTENT_AND_MAPPING_CONFIRMATION',proposed_automatic_value=None)
                    else:record.update(state='NO_DISAGREEMENT',reason='NUMERIC_SIGNATURE_AGREES_NOT_A_CORRECTNESS_CERTIFICATE')
            if reason:record['reason']=reason
            output.append(record)
    finally:
        restore();tp.close();page.close();d.close()
    result={'parameters':PARAMS,'input_normal_dir':str(args.normal_dir.resolve()),'source':str(args.source.resolve()),'physical_page':info['physical_page'],'dpi':info['dpi'],'ROI':args.roi,'all_ROI_OCR_indices':all_indices,'numeric_OCR_indices':indices,'objects':output,'seconds':time.perf_counter()-start,'paint_proofs':proofs,'labels_read':False,'OCR_or_model_calls':0,'DXF_written':False,'human_reviewed':False,'scope':'LOCAL_EVAL_ONLY; read-only candidate evidence; no live review-project events'}
    (args.output/'candidates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'objects':len(output),'states':dict(collections.Counter(x['state'] for x in output)),'candidates':[(x['OCR_index'],x['OCR_text'],x.get('native_text_hypothesis')) for x in output if x['state']=='REVIEW_CANDIDATE'],'proofs':proofs,'seconds':result['seconds']},ensure_ascii=False))
if __name__=='__main__':main()
