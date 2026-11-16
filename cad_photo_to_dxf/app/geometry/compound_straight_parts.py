"""Frozen-contract straight parts, supported by registered bitonal original scan.

Separate research representation; never changes r13 isolated-stroke limits.
All geometry and runs are local to the supplied tile. Source permissions remain
whole-parent permissions. Exact source pixel cells carry all unresolved content.
"""
from __future__ import annotations
import hashlib
import math
import cv2
import numpy as np
from PIL import Image
from shapely.geometry import LineString,box
from shapely.ops import unary_union
from app.geometry.observed_open_strokes import _thin, _runs
from app.geometry.observed_label_frames import PEN_WIDTHS_HUNDREDTH_MM
NEIGHBOURS=((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1))

def chains_from_source(mask):
    skel=_thin(mask);nodes=set(zip(*np.nonzero(skel)))
    adj={}
    for y,x in nodes:
        peers=[]
        for dy,dx in NEIGHBOURS:
            q=(y+dy,x+dx)
            if q not in nodes:continue
            if dx and dy and ((y,x+dx) in nodes or (y+dy,x) in nodes):continue
            peers.append(q)
        adj[y,x]=sorted(peers)
    visited=set();chains=[]
    def edge(a,b):return tuple(sorted((a,b)))
    for start in sorted(p for p,v in adj.items() if len(v)!=2):
        for peer in adj[start]:
            if edge(start,peer) in visited:continue
            seq=[start,peer];visited.add(edge(start,peer))
            while len(adj[seq[-1]])==2:
                p=seq[-1];nb=next(q for q in adj[p] if q!=seq[-2])
                if edge(p,nb) in visited:break
                seq.append(nb);visited.add(edge(p,nb))
            chains.append(seq)
    # Closed cycles stay unresolved; don't cut them into an invented open stroke.
    total=sum(len(v) for v in adj.values())//2
    return skel,adj,chains,len(visited),total

def _minimum_distances(points,seeds):
    if not len(seeds):return np.full(len(points),np.inf)
    seeds=np.asarray(seeds,float)
    out=[]
    for start in range(0,len(points),256):
        delta=points[start:start+256,None,:]-seeds[None,:,:]
        out.append(np.sqrt(np.square(delta).sum(2).min(1)))
    return np.concatenate(out) if out else np.empty(0)

def partition_component(component):
    """Disjoint source-member proposals; 0 is conserved unresolved source.

    A pixel square is only assigned when the distance gap to another skeleton
    chain/junction exceeds its full diagonal. This is a conservative ownership
    filter, not a correctness proof or a junction clustering radius.
    """
    skel,adj,chains,covered,total=chains_from_source(component)
    source=np.column_stack(np.nonzero(component))
    if not len(source):return np.zeros(component.shape,np.int32),[],{},skel
    junctions=sorted(p for p,v in adj.items() if len(v)>=3)
    distances=[_minimum_distances(source,junctions)]
    usable=[]
    for seq in chains:
        seeds=[p for p in seq if len(adj[p])<3]
        if not seeds:continue
        usable.append(seq);distances.append(_minimum_distances(source,seeds))
    ds=np.asarray(distances)
    if len(ds)<2:
        return np.zeros(component.shape,np.int32),usable,dict(skeleton_edges=total,accounted_edges=covered),skel
    nearest=np.argsort(ds,axis=0,kind='stable')[:2]
    ids=nearest[0]
    first=ds[ids,np.arange(len(source))]
    second=ds[nearest[1],np.arange(len(source))]
    assign=(ids>0)&((second-first)>math.sqrt(2.))
    owner=np.zeros(component.shape,np.int32)
    owner[tuple(source[assign].T)]=ids[assign]
    meta=dict(skeleton_edges=total,accounted_edges=covered,
              unresolved_cycle_edges=total-covered,chain_count=len(usable),
              junction_pixels=len(junctions),ownership_margin_px=math.sqrt(2.),
              junctions_merged=False,branches_pruned=False)
    return owner,usable,meta,skel

# Frozen before A2 fitting; source: docs/research/short_straight_contract.json
CONTRACT_SHA256='b2678b460fcf5bb73d1d26df1a3a281d555db23c5f458a5a5db8c4f6ed10ebfc'
VERSION='short-straight-compound-parts-v1'


def mask_geometry(mask):
    return unary_union([box(a-.5,y-.5,b-.5,y+.5) for y,a,b in _runs(mask)])


def topology(geom):
    # Floating epsilon only reconciles zero-area point contact in pixel cells,
    # the 8-neighbor source convention. It cannot bridge a native-pixel white gap.
    g=geom.buffer(1e-8,join_style=2)
    ps=[]
    if g.geom_type=='Polygon':ps=[g]
    elif hasattr(g,'geoms'):ps=[x for x in g.geoms if x.geom_type=='Polygon']
    return len(ps),sum(len(x.interiors) for x in ps)


def pixel_union_distance(points,source):
    if not len(source):return float('inf')
    maximum=0.
    for start in range(0,len(points),64):
        delta=np.maximum(np.abs(points[start:start+64,None,:]-source[None,:,:])-.5,0.)
        maximum=max(maximum,float(np.sqrt(np.square(delta).sum(2).min(1)).max()))
    return maximum


def source_to_segment_distance(points,a,b):
    edge=b-a;den=float(edge@edge)
    if den<=0:return np.full(len(points),np.inf)
    t=np.clip((points-a)@edge/den,0.,1.)
    return np.linalg.norm(points-(a+t[:,None]*edge),axis=1)


def _native_line_fit(native_gray,support,*,scale,dpi):
    yy,xx=np.nonzero(support);source=np.column_stack((xx,yy)).astype(float)
    if len(source)<12:return None,'FEWER_THAN_12_SOURCE_PIXELS'
    centroid=source.mean(0)
    _,vec=np.linalg.eigh((source-centroid).T@(source-centroid))
    tangent=vec[:,-1]
    if tangent[0]<0 or (abs(tangent[0])<1e-12 and tangent[1]<0):tangent=-tangent
    normal=np.array([-tangent[1],tangent[0]])
    projection=(source-centroid)@tangent
    extent=float(projection.max()-projection.min())
    if extent<=0:return None,'ZERO_LENGTH'
    rough_width=len(source)/(extent+1.)
    # Artificial endpoints move inward within their observed source support.
    # They are never restored/extended toward another branch or white gap.
    lo=float(projection.min()+rough_width/2.)
    hi=float(projection.max()-rough_width/2.)
    if hi<=lo:return None,'NO_STRAIGHT_INTERIOR'
    a=centroid+lo*tangent;b=centroid+hi*tangent
    rough_collar=max(2.*scale,rough_width+math.sqrt(.5)*scale)
    interior_length=hi-lo-2*rough_collar
    minimum_native_mm=2.0*(dpi*scale)/25.4
    if interior_length<minimum_native_mm:return None,'INTERIOR_SHORTER_THAN_2MM'
    n=int(math.floor(interior_length))+1
    if n<12:return None,'FEWER_THAN_12_NATIVE_CROSS_SECTIONS'
    stations=np.linspace(lo+rough_collar,hi-rough_collar,n)
    centers=centroid+stations[:,None]*tangent
    radius=max(4.*scale,2.*rough_width+scale)
    offsets=np.arange(-radius,radius+.0625,.125)
    points=centers[:,None,:]+offsets[None,:,None]*normal
    ink=support.astype(np.float32)
    profiles=cv2.remap(ink,points[:,:,0].astype(np.float32),points[:,:,1].astype(np.float32),
                      cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    widths=profiles.sum(1)*.125
    width=float(np.median(widths))
    if widths.min()<.5*scale:return None,'WIDTH_BELOW_R13_MINIMUM'
    if float(np.ptp(widths))>1.5*scale:return None,'WIDTH_VARIATION'
    code=min(PEN_WIDTHS_HUNDREDTH_MM,key=lambda c:(abs(c*dpi*scale/2540.-width),c))
    pen_width=code*dpi*scale/2540.
    edge_shift=abs(pen_width-width)/2.
    if edge_shift>.25*scale:return None,'PEN_WIDTH_SHIFT'
    collar=max(2.*scale,pen_width+math.sqrt(.5)*scale)
    interior_length=hi-lo-2*collar
    n=int(math.floor(interior_length))+1
    if interior_length<minimum_native_mm:return None,'INTERIOR_SHORTER_THAN_2MM'
    if n<12:return None,'FEWER_THAN_12_NATIVE_CROSS_SECTIONS'
    interior_stations=(stations>=lo+collar-1e-9)&(stations<=hi-collar+1e-9)
    actual_stations=stations[interior_stations]
    actual_widths=widths[interior_stations]
    if len(actual_stations)<12:return None,'FEWER_THAN_12_NATIVE_CROSS_SECTIONS'
    measured_width=float(np.median(actual_widths))
    measured_code=min(PEN_WIDTHS_HUNDREDTH_MM,key=lambda c:(abs(c*dpi*scale/2540.-measured_width),c))
    if measured_code!=code:return None,'PEN_WIDTH_UNSTABLE_AFTER_COLLAR'
    width=measured_width
    edge_shift=abs(pen_width-width)/2.
    if edge_shift>.25*scale:return None,'PEN_WIDTH_SHIFT'
    if interior_length/width<8:return None,'INTERIOR_ASPECT_BELOW_8'
    # The original-source pixel centers must all remain within the pen's
    # unchanged boundary tolerance; no discarded off-line source fragments.
    forward=max(0.,float(source_to_segment_distance(source,a,b).max())-pen_width/2.)
    if forward>min(1.,scale):return None,'NATIVE_SOURCE_TO_PEN'
    centers=np.linspace(a,b,max(2,int(math.ceil(np.linalg.norm(b-a)*4))+1))
    center_error=pixel_union_distance(centers,source)
    if center_error>1e-9:return None,'NATIVE_CENTERLINE_WHITE_GAP_OR_UNSUPPORTED'
    # All standard cap styles are measured. Exact topology is tested separately.
    samples=[centers,centers+normal*pen_width/2.,centers-normal*pen_width/2.]
    angles=np.linspace(0,2*math.pi,max(33,int(math.ceil(pen_width*math.pi*8))))
    caps=np.column_stack((np.cos(angles),np.sin(angles)))*pen_width/2.
    samples.extend([a+caps,b+caps])
    for p,sgn in [(a,-1),(b,1)]:
        samples.append(p+sgn*tangent*pen_width/2.+np.linspace(-1,1,max(3,int(math.ceil(pen_width*8))))[:,None]*normal*pen_width/2.)
    reverse=pixel_union_distance(np.concatenate(samples),source)
    if reverse>min(1.,scale):return None,'NATIVE_PEN_TO_SOURCE'
    # Fit support is not identical to consumption. Source collar remains under
    # the artificial endpoints, and only the measured interior is retired.
    end_distance=np.minimum(np.linalg.norm(source-a,axis=1),np.linalg.norm(source-b,axis=1))
    retired=support.copy();retired[yy[end_distance<=collar],xx[end_distance<=collar]]=False
    if not retired.any():return None,'NO_INTERIOR_RETIREMENT'
    retained=support&~retired
    path_native=np.array([a,b]);path_work=(path_native+.5)/scale-.5
    return dict(points_px=path_work.tolist(),native_points_px=path_native.tolist(),
                lineweight_hundredth_mm=int(code),width_px=width/scale,
                native_measured_width_px=width,native_pen_width_px=pen_width,
                length_px=float(hi-lo)/scale,interior_length_mm=float(interior_length)*25.4/(dpi*scale),
                interior_length_width_ratio=float(interior_length/width),
                native_cross_sections=len(actual_stations),native_cross_section_spacing_px=float(np.diff(actual_stations).min()),
                source_to_pen_error_px=forward/scale,pen_to_source_error_px=reverse/scale,
                native_source_to_pen_error_px=forward,native_pen_to_source_error_px=reverse,
                native_centerline_to_source_error_px=center_error,
                maximum_measured_pen_edge_shift_px=edge_shift/scale,
                measured_width_range_px=(float(widths.min())/scale,float(widths.max())/scale),
                source_pixels=int(support.sum()),native_retired_source_pixels=int(retired.sum()),
                native_retained_interface_pixels=int(retained.sum()),
                native_supporting_source_runs_y_x0_x1=_runs(support),
                native_retired_source_runs_y_x0_x1=_runs(retired),
                native_retained_interface_runs_y_x0_x1=_runs(retained),
                artificial_endpoint=(True,True),terminal_extension_px=0.,
                collar_radius_px=collar/scale,classification='OBSERVED_PARTIAL_COMPOUND_STRAIGHT_STROKE',
                electrical_semantics='NOT_INFERRED',full_object_movable=False,
                _retired=retired,_interface=retained,_native_path=path_native), 'FIT_SUPPORTED'


def rasterize_straight_pen(shape,path,width,cap_style):
    """Sample the saved LINE pen at exact original pixel centers, no epsilon."""
    yy,xx=np.indices(shape,dtype=float)
    a,b=np.asarray(path,dtype=float)
    vector=b-a;length=float(np.linalg.norm(vector));tangent=vector/length
    along=(xx-a[0])*tangent[0]+(yy-a[1])*tangent[1]
    across=np.abs((xx-a[0])*(-tangent[1])+(yy-a[1])*tangent[0])
    radius=width/2.
    if cap_style==1:
        beyond=np.maximum(np.maximum(-along,along-length),0.)
        return np.hypot(beyond,across)<=radius
    if cap_style==2:
        return (along>=0.)&(along<=length)&(across<=radius)
    if cap_style==3:
        return (along>=-radius)&(along<=length+radius)&(across<=radius)
    raise ValueError('unknown pen cap')


def native_component_labels(mask):
    # Native ink uses 8-neighbor connectivity; paper uses 4, including one
    # explicit exterior-paper border. Both overlap maps must remain bijective.
    ink_count,ink=cv2.connectedComponents(mask.astype(np.uint8),connectivity=8)
    paper_mask=np.pad(~mask,1,constant_values=True)
    paper_count,paper=cv2.connectedComponents(paper_mask.astype(np.uint8),connectivity=4)
    return ink_count-1,ink,paper_count-2,paper


def _overlap_bijective(before,after):
    before_ids=np.unique(before);before_ids=before_ids[before_ids>0]
    after_ids=np.unique(after);after_ids=after_ids[after_ids>0]
    if len(before_ids)!=len(after_ids):return False
    common=(before>0)&(after>0)
    stride=int(after.max())+1
    pairs=np.unique(before[common].astype(np.int64)*stride+after[common])
    by_before=np.bincount(pairs//stride,minlength=int(before.max())+1)
    by_after=np.bincount(pairs%stride,minlength=stride)
    return bool(np.all(by_before[before_ids]==1) and np.all(by_after[after_ids]==1))


def native_raster_correspondence(before_labels,after_mask):
    after_labels=native_component_labels(after_mask)
    counts=before_labels[0]==after_labels[0] and before_labels[2]==after_labels[2]
    bijective=counts and _overlap_bijective(before_labels[1],after_labels[1]) and _overlap_bijective(before_labels[3],after_labels[3])
    return bool(bijective),dict(source_components=before_labels[0],source_holes=before_labels[2],
                                output_components=after_labels[0],output_holes=after_labels[2],
                                component_overlap_bijective=bool(bijective),
                                native_grid_ink_connectivity=8,native_grid_paper_connectivity=4)


def recover_short_straight_parts(gray,component,foreign=None,*,dpi=100.,native_gray=None,native_scale=None):
    if not isinstance(gray,np.ndarray) or gray.ndim!=2 or gray.dtype!=np.uint8:
        raise ValueError('working gray contract')
    if not math.isfinite(dpi) or dpi<=0:
        raise ValueError('positive finite working DPI required')
    component=np.asarray(component,bool)
    if component.shape!=gray.shape:raise ValueError('component shape')
    if foreign is None:foreign=(gray<254)&~component
    foreign=np.asarray(foreign,bool)
    if foreign.shape!=gray.shape:raise ValueError('foreign shape')
    result=dict(version=VERSION,contract_sha256=CONTRACT_SHA256,candidates=[],decisions=[],
                status='REJECTED',classification='PARTIAL_COMPOUND_STROKES',
                full_object_movable=False,electrical_semantics='NOT_INFERRED',
                production_retirement_authorized=False)
    before=[hashlib.sha256(x.tobytes()).hexdigest() for x in (gray,component,foreign)]
    if np.any(component&foreign):result['reason']='WHOLE_PARENT_PROTECTED_OR_CLAIMED';return result
    if native_gray is None or native_scale is None:result['reason']='ORIGINAL_SCAN_REQUIRED';return result
    if isinstance(native_scale,(tuple,list)):
        if len(native_scale)!=2 or native_scale[0]!=native_scale[1]:result['reason']='ISOTROPIC_INTEGER_REGISTRATION_REQUIRED';return result
        scale=float(native_scale[0])
    else:scale=float(native_scale)
    if not math.isfinite(scale) or scale<2 or scale!=int(scale):result['reason']='INTEGER_ORIGINAL_SCALE_AT_LEAST_TWO';return result
    scale=int(scale)
    if native_gray.dtype!=np.uint8 or native_gray.ndim!=2 or native_gray.shape!=tuple(scale*n for n in gray.shape):
        result['reason']='ORIGINAL_SCAN_SHAPE';return result
    if not np.isin(native_gray,[0,255]).all():result['reason']='ORIGINAL_SCAN_NOT_BITONAL';return result
    down=np.array(Image.fromarray(native_gray).resize((gray.shape[1],gray.shape[0]),Image.Resampling.BOX))
    difference=np.abs(down.astype(np.int16)-gray.astype(np.int16))
    if difference.max()>1 or not np.array_equal(down<254,gray<254):
        result['reason']='ORIGINAL_SCAN_REGISTRATION_MISMATCH';return result
    native_before=hashlib.sha256(native_gray.tobytes()).hexdigest()
    parent=np.repeat(np.repeat(component,scale,0),scale,1)&(native_gray==0)
    native_foreign=(native_gray==0)&~parent
    native_forbidden=np.repeat(np.repeat(foreign,scale,0),scale,1)
    native_owner=np.zeros(native_gray.shape,np.int32)
    owner,chains,meta,_=partition_component(component)
    if not meta.get('junction_pixels',0):
        result.update(status='NO_SUPPORTED_PARTS',reason='NO_COMPOUND_JUNCTION',metadata=meta)
        return result
    proposals=[]
    for part_id,chain in enumerate(chains,1):
        region=owner==part_id
        support=np.repeat(np.repeat(region,scale,0),scale,1)&(native_gray==0)
        row=dict(part_id=part_id,working_support_pixels=int(region.sum()),native_support_pixels=int(support.sum()),decision='RETAINED')
        result['decisions'].append(row)
        fit,reason=_native_line_fit(native_gray,support,scale=scale,dpi=dpi)
        row['reason']=reason
        if fit is None:continue
        fit['part_id']=part_id
        fit['working_supporting_source_runs_y_x0_x1']=_runs(region)
        proposals.append((fit,row))
    # Native exact cell representation closes all consumption seams. Each part
    # must satisfy every standard cap style, with no new residual/foreign contact.
    # Greedy processing is deterministic; failed candidates retain all their source.
    adopted=[]
    if proposals:
        parent_geom=mask_geometry(parent);foreign_geom=mask_geometry(native_foreign)
        original_topology=topology(parent_geom)
        original_raster_labels=native_component_labels(parent)
        forbidden_geom=mask_geometry(native_forbidden)
    for fit,row in proposals:
        retired=fit['_retired'];interface=fit['_interface'];path=fit['_native_path']
        if np.any((native_owner>0)&retired):row['reason']='SOURCE_CONSUMPTION_CONFLICT';continue
        proposed_owner=native_owner.copy();proposed_owner[retired]=fit['part_id']
        residual=parent&(proposed_owner==0)
        residual_geom=mask_geometry(residual);interface_geom=mask_geometry(interface)
        cap_reports=[];raster_reports=[];failure=None
        for cap_style,name in [(1,'round'),(2,'butt'),(3,'square')]:
            pen=LineString(path).buffer(fit['native_pen_width_px']/2.,cap_style=cap_style,join_style=2,quad_segs=32)
            if any(pen.intersects(LineString(previous['_native_path']).buffer(previous['native_pen_width_px']/2.,cap_style=cap_style,join_style=2,quad_segs=32)) for previous in adopted):
                failure='NEW_NATIVE_PART_CONTACT';break
            if not forbidden_geom.is_empty and pen.intersects(forbidden_geom):
                failure='PROTECTED_OR_FOREIGN_WORKING_CELL_CONTACT';break
            if not foreign_geom.is_empty and pen.intersects(foreign_geom):
                failure='NEW_FOREIGN_SOURCE_CONTACT';break
            contact=pen.intersection(residual_geom)
            if not contact.difference(interface_geom).is_empty:
                failure='NEW_NON_INTERFACE_SOURCE_CONTACT';break
            # Every artificial endpoint must touch its own retained source collar.
            for p in path:
                # Only use original retained interface members near this endpoint.
                yy,xx=np.nonzero(interface);coords=np.column_stack((xx,yy))
                keep=np.linalg.norm(coords-p,axis=1)<=fit['collar_radius_px']*scale+1e-8
                local=np.zeros(interface.shape,bool);local[yy[keep],xx[keep]]=True
                if not pen.intersects(mask_geometry(local)):
                    failure='ARTIFICIAL_SEAM_DISCONNECTED';break
            if failure:break
            pieces=[residual_geom,pen]
            for previous in adopted:
                pieces.append(LineString(previous['_native_path']).buffer(previous['native_pen_width_px']/2.,cap_style=cap_style,join_style=2,quad_segs=32))
            after=topology(unary_union(pieces))
            if after!=original_topology:failure='NATIVE_COMPONENT_OR_HOLE_CHANGE';break
            output_raster=residual.copy()
            output_raster|=rasterize_straight_pen(parent.shape,path,fit['native_pen_width_px'],cap_style)
            for previous in adopted:
                output_raster|=rasterize_straight_pen(parent.shape,previous['_native_path'],previous['native_pen_width_px'],cap_style)
            raster_preserved,raster_report=native_raster_correspondence(original_raster_labels,output_raster)
            raster_report['cap_style']=name
            raster_reports.append(raster_report)
            if not raster_preserved:
                failure='NATIVE_PIXEL_COMPONENT_OR_HOLE_IDENTITY_CHANGE';break
            cap_reports.append(dict(cap_style=name,source_components=original_topology[0],source_holes=original_topology[1],output_components=after[0],output_holes=after[1],non_interface_contacts=0,foreign_contacts=0))
        if failure:
            row['reason']=failure
            if raster_reports:row['native_raster_cap_audit']=raster_reports
            continue
        native_owner=proposed_owner
        fit['native_topology_cap_audit']=cap_reports
        fit['native_raster_cap_audit']=raster_reports
        fit['creates_connection']=False;fit['native_retirement_verified']=True
        adopted.append(fit);row.update(decision='CANDIDATE',reason='ORIGINAL_SUPPORTED_STRAIGHT_PART_WITH_PRESERVED_INTERFACES')
    residual=parent&(native_owner==0)
    assert np.array_equal((native_owner>0)|residual,parent)
    assert not np.any((native_owner>0)&residual)
    assert all(hashlib.sha256(x.tobytes()).hexdigest()==h for x,h in zip((gray,component,foreign),before))
    assert hashlib.sha256(native_gray.tobytes()).hexdigest()==native_before
    result.update(status='CANDIDATES' if adopted else 'NO_SUPPORTED_PARTS',reason='COMPLETE',
                  candidates=[{k:v for k,v in p.items() if not k.startswith('_')} for p in adopted],
                  native_scale=scale,native_pixel_to_work='(native+0.5)/scale-0.5',
                  native_source_runs_y_x0_x1=_runs(parent),native_residual_runs_y_x0_x1=_runs(residual),
                  native_foreign_runs_y_x0_x1=_runs(native_foreign),native_forbidden_runs_y_x0_x1=_runs(native_forbidden),
                  source_shape=gray.shape,native_shape=native_gray.shape,
                  native_source_pixels=int(parent.sum()),native_retired_source_pixels=int((native_owner>0).sum()),
                  native_residual_pixels=int(residual.sum()),native_partition_owner=native_owner,
                  native_preserved_residual=residual,source_partition_exact=True,source_overlap_pixels=0,
                  source_unaccounted_pixels=0,input_unchanged=True,registration_max_gray_difference=int(difference.max()),
                  registration_working_sha256=before[0],registration_native_sha256=native_before,metadata=meta)
    return result
