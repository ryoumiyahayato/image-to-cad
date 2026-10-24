"""Source-certified interval candidates. No labels or design-specific rules."""
import sys
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
SNAP=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
sys.path.insert(0,str(SNAP))
from app.geometry.line_detect import LineSegment,_normalize_endpoint_order

CONFIG=dict(version='v1',detector='OpenCV LSD_REFINE_STD; same detector branch as line_detect',
    min_proposal_length=8.,normal_radius=12.,normal_step=.5,recenter_radius=6.,
    contrast_min=20.,half_height_fraction=.5,width_min=.5,width_max=10.,min_interval_samples=8,
    model_threshold=.6,source_sample_step=1.,max_proposals_per_route=4000,
    route_order=['stable','source','model'],gap_filling=False,endpoint_extension=False,
    label_access=False,model_downvote=False)

def true_runs(a):
    d=np.diff(np.r_[False,a,False].astype(np.int8));return list(zip(np.flatnonzero(d==1),np.flatnonzero(d==-1)))
def proposals(image):
    lines=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(image)[0];result=[]
    for k,v in enumerate([] if lines is None else lines[:,0,:]):
        seg=_normalize_endpoint_order(LineSegment(*map(float,v),source_ids=(f'LSD-{k}',)))
        if seg.length>=CONFIG['min_proposal_length']:result.append(seg)
    return sorted(result,key=lambda x:-x.length)[:CONFIG['max_proposals_per_route']]
def cross_profiles(strength,points,normal):
    offsets=np.arange(-CONFIG['normal_radius'],CONFIG['normal_radius']+.01,CONFIG['normal_step'])
    q=points[:,None,:]+offsets[None,:,None]*normal[None,None,:]
    profile=cv2.remap(strength,q[:,:,0].astype(np.float32),q[:,:,1].astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    return offsets,profile
def cross_component(profile,offsets):
    # Each side must contain a lower-intensity flank. A flat field is not a stroke.
    left=profile[:,offsets<=-2].min(axis=1);right=profile[:,offsets>=2].min(axis=1);background=np.maximum(left,right)
    near=np.abs(offsets)<=CONFIG['recenter_radius'];peak=profile[:,near].max(axis=1)
    threshold=background+CONFIG['half_height_fraction']*(peak-background)
    return background,peak,threshold
def certify(gray,seg,polarity):
    strength=(gray if polarity=='light_ink' else 255-gray).astype(np.float32)
    a,b=seg.p1,seg.p2;vector=b-a;normal=np.array([-vector[1],vector[0]])/seg.length
    n=max(2,int(seg.length)+1);points=np.linspace(a,b,n);offsets,profiles=cross_profiles(strength,points,normal)
    median=np.median(profiles,axis=0)[None,:];bg,peak,threshold=cross_component(median,offsets)
    if peak[0]-bg[0]<CONFIG['contrast_min']:return None,'insufficient_two_sided_source_contrast'
    components=true_runs(median[0]>=threshold[0])
    components=[(s,e) for s,e in components if min(abs(offsets[s]),abs(offsets[e-1]))<=CONFIG['recenter_radius']]
    if not components:return None,'no_local_source_ridge'
    # Choose nearest ridge, not the brightest adjacent parallel stroke.
    s,e=min(components,key=lambda z:(0 if offsets[z[0]]<=0<=offsets[z[1]-1] else min(abs(offsets[z[0]]),abs(offsets[z[1]-1]))))
    shift=float((offsets[s]+offsets[e-1])/2);width=(e-s)*CONFIG['normal_step']
    if not CONFIG['width_min']<=width<=CONFIG['width_max']:return None,'wide_field_or_unresolved_stroke'
    points=points+normal*shift;offsets,profiles=cross_profiles(strength,points,normal);bg,peak,threshold=cross_component(profiles,offsets)
    good=np.zeros(n,bool);widths=np.zeros(n,float);footprints=[]
    for i,row in enumerate(profiles):
        if peak[i]-bg[i]<CONFIG['contrast_min']:footprints.append(np.empty((0,2),int));continue
        components=true_runs(row>=threshold[i]);near=[]
        for s,e in components:
            center=(offsets[s]+offsets[e-1])/2
            if abs(center)<=1.5:near.append((s,e,center))
        if not near:footprints.append(np.empty((0,2),int));continue
        s,e,center=min(near,key=lambda z:abs(z[2]));w=(e-s)*CONFIG['normal_step'];widths[i]=w
        if w>CONFIG['width_max'] or w<CONFIG['width_min']:footprints.append(np.empty((0,2),int));continue
        pix=np.unique(np.rint(points[i]+offsets[s:e,None]*normal).astype(int),axis=0)
        inside=(pix[:,0]>=0)&(pix[:,0]<gray.shape[1])&(pix[:,1]>=0)&(pix[:,1]<gray.shape[0]);pix=pix[inside]
        if not len(pix):footprints.append(pix);continue
        # Direct source pixels only; no binary interpolation or morphological repair.
        pix=pix[strength[pix[:,1],pix[:,0]]>=threshold[i]]
        centerpix=np.rint(points[i]).astype(int);centerinside=0<=centerpix[0]<gray.shape[1] and 0<=centerpix[1]<gray.shape[0]
        good[i]=bool(len(pix) and centerinside and strength[centerpix[1],centerpix[0]]>=threshold[i])
        footprints.append(pix)
    return dict(points=points,normal=normal,good=good,widths=widths,footprints=footprints,
        contrast=peak-bg,shift=shift,uniform_step=float(seg.length/(n-1))),None
def field_evidence(gray):
    f=gray.astype(np.float32);m=cv2.GaussianBlur(f,(0,0),2);var=np.maximum(0,cv2.GaussianBlur(f*f,(0,0),2)-m*m)
    field=(gray>24)&(gray<232)&(var<16)
    count,labels,stats,_=cv2.connectedComponentsWithStats(field.astype(np.uint8),8);rows=[];keep=np.zeros(gray.shape,bool)
    for i in range(1,count):
        x,y,w,h,n=map(int,stats[i])
        if n>=64:
            keep[labels==i]=True;rows.append(dict(box=[x,y,x+w,y+h],pixels=n,median_gray=float(np.median(gray[labels==i])),kind='flat_midtone_field; background/fill evidence only, not stroke'))
    return keep,rows
def generate(rgb,stable,scores=None):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);polarity='light_ink' if np.median(gray)<128 else 'dark_ink'
    detector_source=255-gray if polarity=='light_ink' else gray
    routes=[('stable',np.where(stable,0,255).astype(np.uint8)),('source',detector_source)]
    if scores is not None:routes.append(('model',np.where(scores>=CONFIG['model_threshold'],0,255).astype(np.uint8)))
    owner=np.zeros(gray.shape,np.int32);records=[];adopted=[];duplicates=[];proposal_count={}
    for route,img in routes:
        raw=proposals(img);proposal_count[route]=len(raw)
        for index,seg in enumerate(raw):
            parent=f'{route}-{index:05d}';cert,reason=certify(gray,seg,polarity)
            record=dict(proposal_id=parent,route=route,proposed_points=[seg.p1.tolist(),seg.p2.tolist()],proposal_length=seg.length)
            if cert is None:records.append(dict(**record,decision='REJECT',reason=reason));continue
            points=cert['points'];ps=np.rint(points).astype(int);inside=(ps[:,0]>=0)&(ps[:,0]<gray.shape[1])&(ps[:,1]>=0)&(ps[:,1]<gray.shape[0])
            represented=np.zeros(len(ps),bool);represented[inside]=owner[ps[inside,1],ps[inside,0]]>0
            source_good=cert['good'];new=source_good&~represented
            prior=np.unique(owner[ps[inside,1],ps[inside,0]]);prior=prior[prior>0].tolist()
            children=[]
            for start,end in true_runs(new):
                if end-start<CONFIG['min_interval_samples']:continue
                fp=np.unique(np.concatenate(cert['footprints'][start:end]),axis=0)
                if not len(fp):continue
                # Shared source intersection pixels may be owned already; no extra collinear interval is created there.
                ident=len(adopted)+1;oldowners=np.unique(owner[fp[:,1],fp[:,0]]);junctions=oldowners[oldowners>0].tolist()
                owner[fp[:,1],fp[:,0]]=np.where(owner[fp[:,1],fp[:,0]]==0,ident,owner[fp[:,1],fp[:,0]])
                ww=cert['widths'][start:end];p=points[start:end]
                row=dict(candidate_id=ident,parent_proposal=parent,route=route,points=[p[0].tolist(),p[-1].tolist()],
                    width_median=float(np.median(ww)),width_min=float(ww.min()),width_max=float(ww.max()),source_sample_count=end-start,
                    source_uniform_step_px=cert['uniform_step'],source_contrast_median=float(np.median(cert['contrast'][start:end])),
                    source_recenter_offset_px=cert['shift'],source_footprint_pixels=len(fp),source_footprint_xy=fp.tolist(),
                    stable_pixel_fraction=float(stable[fp[:,1],fp[:,0]].mean()),related_prior_ids=prior,source_junction_owner_ids=junctions,
                    relation='novel source interval; represented same-ridge centers omitted; source junction pixels shared',
                    decision='ADOPT',reason='continuous narrow source ridge; no low-model-score veto',endpoint_extension=False)
                if scores is not None:
                    row['model_score_median']=float(np.median(scores[fp[:,1],fp[:,0]]));row['model_supported_fraction']=float((scores[fp[:,1],fp[:,0]]>=CONFIG['model_threshold']).mean())
                adopted.append(row);children.append(ident)
            if represented.any():duplicates.append(dict(proposal_id=parent,prior_candidate_ids=prior,represented_samples=int((source_good&represented).sum()),operation='omit represented source-center intervals; no global near-line merge'))
            records.append(dict(**record,decision='ADOPT_INTERVALS' if children else 'REJECT_OR_REVIEW',candidate_ids=children,
                reason='new source-certified intervals' if children else 'all represented, source evidence broken, or intervals shorter than 8 samples',
                source_recenter_offset_px=cert['shift'],source_supported_samples=int(source_good.sum()),represented_source_samples=int((source_good&represented).sum())))
    fields,fields_meta=field_evidence(gray)
    return dict(adopted=adopted,proposals=records,relations=duplicates,owner=owner,mask=owner>0,field=fields,field_records=fields_meta,
        summary=dict(polarity=polarity,proposal_counts=proposal_count,adopted_count=len(adopted),represented_relation_count=len(duplicates),
            source_support_pixels=int((owner>0).sum()),model_used=scores is not None,config=CONFIG))
