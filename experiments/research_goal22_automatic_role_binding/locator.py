"""Pixel-only geometry proposals. No files, OCR text, candidates or reference labels."""
import numpy as np
import cv2

VERSION='v2'
PARAMS=dict(threshold=180,min_area=2,scale_component_parent_height=.25,slash_body_height=.80,slash_slope_min=-1.1,
    slash_slope_max=-.30,slash_residual_height=.07,slash_residual_floor=1.2,
    fraction_height_min=.30,fraction_height_max=.85,fraction_center_offset=.10,
    fraction_reach=1.25,line_group_gap=.28,line_center_tolerance=.18,
    whole_to_fraction_height=1.25,mixed_gap=.30,standalone_height=.38,word_gap=.18,
    tall_diagonal_body_height=1.25,tall_diagonal_aspect=1.5,max_center_spread=.26,crop_margin=1)

def bounds(cs):
    return [min(c['box'][0] for c in cs),min(c['box'][1] for c in cs),
            max(c['box'][2] for c in cs),max(c['box'][3] for c in cs)]

def locate(pixels,parent_to_source=(1,0,0,0,1,0),direction='PAGE_AXIS'):
    """Accept only the parent pixels, affine map and existing direction convention."""
    if direction!='PAGE_AXIS':return dict(version=VERSION,regions=[],relations=[],status='UNSUPPORTED_DIRECTION')
    gray=cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY) if pixels.ndim==3 else pixels
    h,w=gray.shape;mask=(gray<PARAMS['threshold']).astype(np.uint8)
    count,labels,stats,centers=cv2.connectedComponentsWithStats(mask,connectivity=8)
    comps=[]
    for i in range(1,count):
        x,y,ww,hh,area=map(int,stats[i])
        if area<PARAMS['min_area']:continue
        yy,xx=np.where(labels==i);slope=float(np.polyfit(yy,xx,1)[0]) if len(set(yy))>1 else 0.
        residual=float(np.std(xx-slope*yy))
        comps.append(dict(id=i,box=[x,y,x+ww,y+hh],area=area,center=centers[i].tolist(),height=hh,
            slope=slope,line_residual=residual,touches_edge=x==0 or y==0 or x+ww==w or y+hh==h))
    body_heights=[c['height'] for c in comps if c['height']>=PARAMS['scale_component_parent_height']*h]
    body_height=float(np.median(body_heights)) if body_heights else float(h)
    for c in comps:
        diagonal=PARAMS['slash_slope_min']<=c['slope']<=PARAMS['slash_slope_max']
        straight=c['line_residual']<=max(PARAMS['slash_residual_floor'],PARAMS['slash_residual_height']*c['height'])
        c['slash_candidate']=bool(c['height']>=PARAMS['slash_body_height']*body_height and diagonal and straight)
        c['uncertain_diagonal']=bool(diagonal and not straight and c['height']>=PARAMS['tall_diagonal_body_height']*body_height
            and c['height']/(c['box'][2]-c['box'][0])>=PARAMS['tall_diagonal_aspect'])
    regions=[];relations=[];used=set();hints=[]
    def mapbox(b):
        a,b0,tx,c,d,ty=parent_to_source
        pts=[(a*x+b0*y+tx,c*x+d*y+ty) for x,y in [(b[0],b[1]),(b[2],b[3])]]
        return [int(round(min(p[0] for p in pts))),int(round(min(p[1] for p in pts))),int(round(max(p[0] for p in pts))),int(round(max(p[1] for p in pts)))]
    def add(cs,role,group,state='USABLE'):
        b=bounds(cs);m=PARAMS['crop_margin'];b=[max(0,b[0]-m),max(0,b[1]-m),min(w,b[2]+m),min(h,b[3]+m)]
        if any(c['touches_edge'] for c in cs):state='AMBIGUOUS_PARENT_EDGE'
        if any(c['uncertain_diagonal'] for c in cs):state='AMBIGUOUS_DIAGONAL_COMPONENT'
        r=dict(id='r'+str(len(regions)),role=role,group_id=group,parent_box=b,source_box=mapbox(b),component_ids=[c['id'] for c in cs],
            state=state,glyph_content='UNCONFIRMED',box_origin='AUTOMATIC_COMPONENT_GEOMETRY',role_binding='GEOMETRIC_PROPOSAL',visibility='PROPOSED_COMPLETE' if state=='USABLE' else 'UNCERTAIN')
        regions.append(r);used.update(r['component_ids']);return r['id']
    def connected_row(candidates,seed,hs):
        selected=[seed];remaining=[c for c in candidates if c['id']!=seed['id']]
        changed=True
        while changed:
            changed=False;b=bounds(selected)
            for c in list(remaining):
                gap=max(c['box'][0]-b[2],b[0]-c['box'][2],0)
                if gap<=PARAMS['line_group_gap']*hs and abs(c['center'][1]-seed['center'][1])<=PARAMS['line_center_tolerance']*hs:
                    selected.append(c);remaining.remove(c);changed=True
        return selected
    for slash in sorted([c for c in comps if c['slash_candidate']],key=lambda c:c['box'][0]):
        if slash['id'] in used:continue
        sx,sy=slash['center'];hs=slash['height'];sbox=slash['box'];group='g'+str(len(relations));role_ids={}
        pool=[c for c in comps if c['id'] not in used and c['id']!=slash['id'] and not c['slash_candidate']
              and PARAMS['fraction_height_min']*hs<=c['height']<=PARAMS['fraction_height_max']*hs]
        for role,side in [('numerator',-1),('denominator',1)]:
            opts=[c for c in pool if side*(c['center'][0]-sx)>0 and side*(c['center'][1]-sy)>=PARAMS['fraction_center_offset']*hs
                  and abs(c['center'][0]-sx)<PARAMS['fraction_reach']*hs and abs(c['center'][1]-sy)<.65*hs]
            if opts:
                seed=min(opts,key=lambda c:abs(c['center'][0]-sx));cs=connected_row(opts,seed,hs)
                role_ids[role]=add(cs,role,group)
        status='PROPOSED_FRACTION' if set(role_ids)=={'numerator','denominator'} else 'AMBIGUOUS_SEPARATOR_BINDING'
        if status=='PROPOSED_FRACTION':
            n=next(r for r in regions if r['id']==role_ids['numerator']);den=next(r for r in regions if r['id']==role_ids['denominator'])
            fraction_height=max(c['height'] for c in comps if c['id'] in n['component_ids']+den['component_ids'])
            opts=[c for c in comps if c['id'] not in used and c['id']!=slash['id'] and not c['slash_candidate']
                  and c['height']>=PARAMS['whole_to_fraction_height']*fraction_height and c['box'][2]<=n['parent_box'][0]+1
                  and n['parent_box'][0]-c['box'][2]<=PARAMS['mixed_gap']*hs
                  and abs(c['box'][3]-den['parent_box'][3])<=.35*hs]
            if opts:
                seed=max(opts,key=lambda c:c['box'][2]);cs=connected_row(opts,seed,hs)
                role_ids['whole']=add(cs,'whole',group);status='PROPOSED_MIXED'
        else:
            for r in regions:
                if r['group_id']==group:r['state']='AMBIGUOUS_SEPARATOR_BINDING';r['visibility']='UNCERTAIN'
        used.add(slash['id'])
        relations.append(dict(id=group,type=status,roles=role_ids,separator_parent_box=sbox,separator_source_box=mapbox(sbox),
            separator_component=slash['id'],separator_kind='SLANTED_CONNECTED_STROKE',slope=slash['slope'],line_residual=slash['line_residual'],
            spatial_rule='upper-left numerator / lower-right denominator; nearby baseline-height whole only',state='USABLE' if status in ('PROPOSED_FRACTION','PROPOSED_MIXED') and not slash['touches_edge'] and all(r['state']=='USABLE' for r in regions if r['group_id']==group) else 'AMBIGUOUS'))
    leftovers=[c for c in comps if c['id'] not in used and c['height']>=PARAMS['standalone_height']*h]
    groups=[]
    for c in sorted(leftovers,key=lambda c:c['box'][0]):
        if groups and c['box'][0]-bounds(groups[-1])[2]<=PARAMS['word_gap']*h:groups[-1].append(c)
        else:groups.append([c])
    for cs in groups:
        spread=max(c['center'][1] for c in cs)-min(c['center'][1] for c in cs)
        state='AMBIGUOUS_VERTICAL_STRUCTURE' if spread>PARAMS['max_center_spread']*h else 'USABLE'
        gid='standalone-'+str(len(regions));rid=add(cs,'whole',gid,state)
        relations.append(dict(id=gid,type='PROPOSED_STANDALONE',roles={'whole':rid},separator_kind=None,state=state,
            spatial_rule='separate horizontal component group; numeric content not yet known'))
    for c in comps:
        if c['id'] not in used:hints.append(dict(parent_box=c['box'],source_box=mapbox(c['box']),component_id=c['id'],type='SMALL_MARK_OR_UNIT_CONTEXT_UNVERIFIED'))
    return dict(version=VERSION,params=PARAMS,parent_shape=[h,w],parent_to_source=list(parent_to_source),regions=regions,relations=relations,
                boundary_hints=hints,components=comps,body_height=body_height,status='PROPOSALS_ONLY',runtime_human_role_boxes=0,candidate_input=False,source_ocr_assistance=False)
