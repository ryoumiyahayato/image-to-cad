"""User-requested original counterexamples; not training data or real transfer evidence."""
import sys,random,copy,json,itertools
sys.dont_write_bytecode=True
from pathlib import Path
import numpy as np,cv2,pypdfium2 as pdfium,pypdfium2.raw as raw,ezdxf
from ownership import select,key,delta,shape_error,clean,save,POLICY
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'local-artifacts/research-goal04-candidate-ownership-20261022/mechanism-examples'
if len(sys.argv)>1:OUT=Path(sys.argv[1]).resolve()

def make_row(folder,index,pts,width=1,closed=False):
    pdf=pdfium.PdfDocument.new();page=pdf.new_page(128,128);path=raw.FPDFPageObj_CreateNewPath(pts[0][0],128-pts[0][1])
    for x,y in pts[1:]:raw.FPDFPath_LineTo(path,x,128-y)
    if closed:raw.FPDFPath_Close(path)
    raw.FPDFPageObj_SetStrokeColor(path,0,0,0,255);raw.FPDFPageObj_SetStrokeWidth(path,width);raw.FPDFPageObj_SetLineCap(path,0);raw.FPDFPageObj_SetLineJoin(path,0);raw.FPDFPath_SetDrawMode(path,0,1);raw.FPDFPage_InsertObject(page,path)
    bm=page.render(scale=1);im=np.array(bm.to_pil().convert('RGB'));bm.close();page.close();pdf.close()
    cv2.imwrite(str(folder/f'path-{index}-only.png'),cv2.cvtColor(im,cv2.COLOR_RGB2BGR))
    return {'source_object':index,'points':pts,'closed':closed,'width_px':width,'rgb':[0,0,0],'source_file':str(folder/'ORIGINAL_IN_MEMORY_SOURCE'),'page':1,'dpi':72.,
      'source_path':{'line_cap':0,'line_join':0,'dash_count':0,'transparent':False},'visibility':{'grid':'parent','box':[0,0,128,128]},'_witness_dir':str(folder)}
def comparable(result):
    return {'owners':[{'points':o['representative']['points'],'closed':o['representative']['closed'],'width':o['representative']['width_px'],'sources':o['source_objects'],'existing':o['existing_handle']} for o in result['owners']],
      'pending':sorted((p['source_object'],p['reason'],p['original_candidate']['points'],p['unique_intervals']) for p in result['pending'])}
def main():
    OUT.mkdir(exist_ok=False)
    definitions=[
      ('same_direction',[([[20,20],[80,20]],1),([[20,20],[80,20]],1)],1,0),
      ('reverse_direction',[([[20,20],[80,20]],1),([[80,20],[20,20]],1)],1,0),
      ('numerical_micro_difference',[([[20,20],[80,20]],1),([[20,20.002],[80,20.002]],1)],1,0),
      ('reverse_micro_difference',[([[20,20],[80,20]],1),([[80,20.002],[20,20]],1)],1,0),
      ('independent_close_double',[([[20,20],[80,20]],.05),([[20,20.25],[80,20.25]],.05)],2,0),
      ('independent_parallel_below_scoring_tolerance',[([[20,20],[80,20]],1),([[20,20.03],[80,20.03]],1)],2,0),
      ('shared_endpoint',[([[20,20],[60,20]],1),([[60,20],[90,35]],1)],2,0),
      ('crossing',[([[20,50],[100,50]],1),([[60,20],[60,100]],1)],2,0),
      ('T_junction',[([[20,50],[100,50]],1),([[60,50],[60,100]],1)],2,0),
      ('partial_each_unique',[([[20,20],[60,20]],1),([[40,20],[80,20]],1)],0,2),
      ('real_tiny_collinear_gap',[([[20,20],[50,20]],1),([[50.002,20],[90,20]],1)],2,0),
      ('different_width_same_geometry',[([[20,20],[80,20]],1),([[20,20],[80,20]],1.1)],0,2),
      ('nontransitive_micro_chain',[([[20,20],[80,20]],1),([[20,20.003],[80,20.003]],1),([[20,20.006],[80,20.006]],1)],0,3),
      ('polyline_unique_turn',[([[20,20],[60,20],[60,60]],1),([[40,20],[90,20]],1)],0,2),
    ]
    summary=[]
    for name,defs,count,pending_count in definitions:
        folder=OUT/name;folder.mkdir();rows=[make_row(folder,10+i,p,w) for i,(p,w) in enumerate(defs)];result=select(rows,[])
        assert len(result['owners'])==count and len(result['pending'])==pending_count,(name,len(result['owners']),len(result['pending']))
        variants=[rows[::-1],random.Random(20261022).sample(rows,len(rows))];stable=all(comparable(select(v,[]))==comparable(result) for v in variants)
        assert stable,name
        all_sources=[s for o in result['owners'] for s in o['source_objects']]+[r['source_object'] for r in result['pending']]
        assert sorted(all_sources)==sorted(r['source_object'] for r in rows)
        if name in ['partial_each_unique','polyline_unique_turn']:
            assert all(sum(v['length_px'] for v in r['unique_intervals'])>0 for r in result['pending'])
            assert all(len(r['original_candidate']['points'])==len(next(q for q in rows if q['source_object']==r['source_object'])['points']) for r in result['pending'])
        save(folder/'original-fixture.json',{'data_kind':'ORIGINAL_MECHANISM_FIXTURE_NOT_REAL_EVALUATION','rows':[clean(r) for r in rows]});save(folder/'selection.json',result)
        summary.append({'case':name,'automatic_owners':count,'pending_original_candidates':pending_count,'input_order_stable':stable,'status':'EXPECTED_BEHAVIOR','automatic_restoration_claim':False})
    # A known same-style baseline owner is reused; unknown width is deferred, never deleted or falsely adopted.
    folder=OUT/'baseline_relationships';folder.mkdir();row=make_row(folder,10,[[20,20],[80,20]])
    known={**clean(row),'source_object':None,'_existing':True,'_handle':'OLD','source_file':None,'page':None,'dpi':None}
    res=select([row],[known]);assert len(res['owners'])==1 and res['owners'][0]['existing_handle']=='OLD'
    unknown={**known,'_width_unknown':True};res2=select([row],[unknown]);assert len(res2['pending'])==1 and not res2['owners']
    partial={**known,'points':[[40,20],[100,20]]};res3=select([row],[partial]);assert len(res3['pending'])==1 and res3['pending'][0]['unique_intervals']
    save(folder/'results.json',{'same_style_full':res,'unknown_style':res2,'partial_old_owner':res3})
    summary.append({'case':'baseline_relationships','full_reused':True,'unknown_width_deferred':True,'partial_unique_preserved_pending':True,'status':'EXPECTED_BEHAVIOR'})
    save(OUT/'results.json',{'data_kind':'ORIGINAL_COUNTEREXAMPLES_ONLY','policy':POLICY,'cases':summary,'count':len(summary),'all_expected':True,'not_real_transfer_evidence':True});print(json.dumps({'cases':len(summary),'all_expected':True}))
if __name__=='__main__':main()
