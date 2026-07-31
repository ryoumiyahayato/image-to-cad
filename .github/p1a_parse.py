from __future__ import annotations
import json, math, re, csv
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class DxfEntity:
    type: str
    tags: list[tuple[int,str]]
    xdata: dict[str,list[tuple[int,str]]]

    def first(self, code:int, default=None):
        for c,v in self.tags:
            if c==code: return v
        return default
    def floats(self, code:int):
        return [float(v) for c,v in self.tags if c==code]


def read_pairs(path:Path):
    lines=path.read_text(encoding='utf-8', errors='replace').splitlines()
    out=[]
    for i in range(0,len(lines)-1,2):
        try: c=int(lines[i].strip())
        except: continue
        out.append((c,lines[i+1].rstrip('\r')))
    return out


def parse_dxf(path:Path):
    pairs=read_pairs(path)
    entities=[]; styles={}; layers={}; header={}
    section=None; table=None; i=0
    while i<len(pairs):
        c,v=pairs[i]
        if c==0 and v=='SECTION':
            if i+1<len(pairs) and pairs[i+1][0]==2:
                section=pairs[i+1][1]; i+=2; continue
        if c==0 and v=='ENDSEC': section=None; table=None; i+=1; continue
        if section=='HEADER' and c==9:
            name=v; vals=[]; i+=1
            while i<len(pairs) and pairs[i][0]!=9 and not (pairs[i][0]==0 and pairs[i][1]=='ENDSEC'):
                vals.append(pairs[i]); i+=1
            header[name]=vals; continue
        if section=='TABLES':
            if c==0 and v=='TABLE':
                if i+1<len(pairs) and pairs[i+1][0]==2: table=pairs[i+1][1]
                i+=2; continue
            if c==0 and v=='ENDTAB': table=None; i+=1; continue
            if c==0 and table in {'STYLE','LAYER'} and v in {'STYLE','LAYER'}:
                typ=v; tags=[]; i+=1
                while i<len(pairs) and pairs[i][0]!=0:
                    tags.append(pairs[i]); i+=1
                d={code:val for code,val in tags}
                if typ=='STYLE': styles[d.get(2,'')]=d
                else: layers[d.get(2,'')]=d
                continue
        if section=='ENTITIES' and c==0 and v not in {'ENDSEC'}:
            typ=v; tags=[]; xdata={}; current_app=None; i+=1
            while i<len(pairs) and pairs[i][0]!=0:
                cc,vv=pairs[i]
                if cc==1001:
                    current_app=vv; xdata.setdefault(vv,[])
                elif current_app is not None and cc>=1000:
                    xdata[current_app].append((cc,vv))
                else:
                    tags.append((cc,vv))
                i+=1
            entities.append(DxfEntity(typ,tags,xdata)); continue
        i+=1
    return header,styles,layers,entities

class LffFont:
    def __init__(self,path:Path):
        self.path=path; self.letter_spacing=1.0; self.word_spacing=5.0; self.glyphs={}
        self._parse()
    def _parse(self):
        current=None; strokes=[]
        def finish():
            nonlocal current,strokes
            if current is None: return
            pts=[]
            for s in strokes:
                for token in s.split(';'):
                    p=token.strip().split(',')
                    if len(p)>=2:
                        try: pts.append((float(p[0]),float(p[1])))
                        except: pass
            if pts:
                xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                maxx=max(xs)
                self.glyphs[current]=(min(xs),min(ys),maxx,max(ys),max(maxx,0.0)+self.letter_spacing)
            current=None; strokes=[]
        with self.path.open('r',encoding='utf-8',errors='ignore') as f:
            for line in f:
                s=line.strip()
                if s.startswith('# LetterSpacing:'):
                    try:self.letter_spacing=float(s.split(':',1)[1])
                    except:pass
                elif s.startswith('# WordSpacing:'):
                    try:self.word_spacing=float(s.split(':',1)[1])
                    except:pass
                elif re.match(r'^\[[0-9A-Fa-f]+\]$',s):
                    finish(); current=int(s[1:-1],16)
                elif current is not None and s and not s.startswith('#'):
                    strokes.append(s)
        finish()
    def metrics(self,text:str):
        cursor=0.; minx=float('inf'); miny=float('inf'); maxx=float('-inf'); maxy=float('-inf'); count=0; fallback=0
        replacement=self.glyphs.get(0xFFFD)
        for ch in text:
            if ch.isspace(): cursor+=max(self.word_spacing,3.0); continue
            g=self.glyphs.get(ord(ch))
            if g is None: g=replacement; fallback+=1
            if g is None: g=(0.,0.,7.,9.,7.+self.letter_spacing)
            gx0,gy0,gx1,gy1,adv=g
            minx=min(minx,cursor+gx0); miny=min(miny,gy0); maxx=max(maxx,cursor+gx1); maxy=max(maxy,gy1)
            cursor+=max(adv,1.); count+=1
        if not count: return dict(min_x=0.,min_y=0.,max_x=max(cursor,1.),max_y=9.,advance=cursor,em_height=9.,fallback=fallback)
        return dict(min_x=minx,min_y=miny,max_x=maxx,max_y=maxy,advance=cursor,em_height=9.,fallback=fallback)

def xdata_decode(e:DxfEntity):
    out={}
    for app,tags in e.xdata.items():
        vals=[]
        for c,v in tags:
            if c in (1040,1041,1042):
                try: vals.append(float(v))
                except: vals.append(v)
            elif c in (1070,1071):
                try: vals.append(int(v))
                except: vals.append(v)
            else: vals.append(v)
        out[app]=vals
    return out

def style_font(styles,name):
    d=styles.get(name,{})
    return d.get(3) or d.get(4) or ''

def rotate_point(x,y,ang_deg,origin=(0,0)):
    a=math.radians(ang_deg); ca=math.cos(a); sa=math.sin(a)
    ox,oy=origin
    return (ox+x*ca-y*sa, oy+x*sa+y*ca)

def oriented_rect(center,w,h,rot):
    pts=[]
    for x,y in [(-w/2,h/2),(w/2,h/2),(w/2,-h/2),(-w/2,-h/2)]:
        rx,ry=rotate_point(x,y,rot,center); pts.append((rx,ry))
    return pts

def aabb(points):
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    return (min(xs),min(ys),max(xs),max(ys))

def segment_intersect(p1,p2,q1,q2):
    def orient(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    o1,o2,o3,o4=orient(p1,p2,q1),orient(p1,p2,q2),orient(q1,q2,p1),orient(q1,q2,p2)
    return (o1==0 or o2==0 or o1*o2<=0) and (o3==0 or o4==0 or o3*o4<=0)

def poly_edges(poly):
    return list(zip(poly,poly[1:]+poly[:1]))

def classify_rotation(deg):
    d=deg%360
    nearest=min([0,90,180,270], key=lambda x: min(abs(d-x),360-abs(d-x)))
    delta=min(abs(d-nearest),360-abs(d-nearest))
    return str(nearest) if delta<=3 else 'arbitrary'

def get_header_extents(header):
    def vec(name):
        d={c:float(v) for c,v in header.get(name,[]) if c in (10,20,30)}
        return (d.get(10,0),d.get(20,0),d.get(30,0))
    return vec('$EXTMIN'),vec('$EXTMAX')

def process_page(dxf:Path, page_meta:dict, font:LffFont):
    header,styles,layers,entities=parse_dxf(dxf)
    texts=[e for e in entities if e.type=='TEXT' and (e.first(8,'')=='OCR_TEXT' or str(e.first(8,'')).endswith('_OCR_TEXT'))]
    lines=[]
    for e in entities:
        if e.type=='LINE' and ('TRACE_STRAIGHT' in str(e.first(8,''))):
            try: lines.append(((float(e.first(10)),float(e.first(20))), (float(e.first(11)),float(e.first(21)))))
            except: pass
    source_w,source_h=page_meta['source_size_px']
    extmin,extmax=get_header_extents(header)
    cad_w=max(float(source_w),extmax[0]-extmin[0]); cad_h=max(float(source_h),extmax[1]-extmin[1])
    sx=cad_w/source_w if source_w else 1; sy=cad_h/source_h if source_h else 1
    recs=[]
    for idx,e in enumerate(texts,1):
        xd=xdata_decode(e); geom=xd.get('OCR_TEXT_GEOMETRY',[]); line=xd.get('OCR_TEXT_LINE',[])
        text=e.first(1,''); style=e.first(7,'STANDARD'); h=float(e.first(40,0)); wf=float(e.first(41,1)); rot=float(e.first(50,0)); ins=(float(e.first(10,0)),float(e.first(20,0)))
        align=(float(e.first(11,ins[0])),float(e.first(21,ins[1]))) if e.first(11) is not None else None
        metric_source='unknown'; metric_fallback='unknown'; target_center=(None,None); tw=th=rw=rh=ce=raw_wf=None; clamped=None
        if geom:
            if len(geom)>=2: metric_source=str(geom[1]).split('=',1)[-1]
            if len(geom)>=3: metric_fallback=str(geom[2]).split('=',1)[-1]
            nums=[v for v in geom[3:] if isinstance(v,(int,float))]
            if len(nums)>=11:
                target_center=(float(nums[0]),float(nums[1])); tw=float(nums[2]);th=float(nums[3]);rw=float(nums[4]);rh=float(nums[5]);ce=float(nums[6]);raw_wf=float(nums[7]);clamped=bool(nums[10])
        conf=float(line[2]) if len(line)>=3 and isinstance(line[2],(int,float)) else None
        font_file=style_font(styles,style)
        m=font.metrics(text)
        local=[(m['min_x']/9*h*wf,m['max_y']/9*h),(m['max_x']/9*h*wf,m['max_y']/9*h),(m['max_x']/9*h*wf,m['min_y']/9*h),(m['min_x']/9*h*wf,m['min_y']/9*h)]
        pred=[rotate_point(x,y,rot,ins) for x,y in local]; pred_aabb=aabb(pred)
        if tw is None:
            tw=max(1e-9,pred_aabb[2]-pred_aabb[0]);th=max(1e-9,pred_aabb[3]-pred_aabb[1]); target_center=((pred_aabb[0]+pred_aabb[2])/2,(pred_aabb[1]+pred_aabb[3])/2); rw=tw;rh=th;raw_wf=wf;clamped=False
        target=oriented_rect(target_center,tw,th,rot)
        src_quad=[(x/sx, source_h-y/sy) for x,y in target]
        xs=[p[0] for p in src_quad]; ys=[p[1] for p in src_quad]
        bbox=(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys))
        crosses=False; nearby=0; pa=pred_aabb; margin=max(th,tw*0.03,5)
        for l1,l2 in lines:
            la=(min(l1[0],l2[0]),min(l1[1],l2[1]),max(l1[0],l2[0]),max(l1[1],l2[1]))
            if la[2]<pa[0]-margin or la[0]>pa[2]+margin or la[3]<pa[1]-margin or la[1]>pa[3]+margin: continue
            nearby+=1
            if any(segment_intersect(a,b,l1,l2) for a,b in poly_edges(pred)) and not any(segment_intersect(a,b,l1,l2) for a,b in poly_edges(target)):
                crosses=True; break
        orientation=classify_rotation(rot)
        recs.append({'page_id':page_meta['id'],'structure_id':page_meta['structure_id'],'candidate_id':f"ocr-{idx:03d}",'ocr_text':text,'ocr_confidence':conf,'ocr_bbox':[round(v,6) for v in bbox],'ocr_quad':[[round(x,6),round(y,6)] for x,y in src_quad],'ocr_orientation_degrees':rot,'ocr_direction':orientation,'source_image_width':source_w,'source_image_height':source_h,'cad_page_width':cad_w,'cad_page_height':cad_h,'x_scale':sx,'y_scale':sy,'selected_text_style':style,'font_family_identifier':'wqy-unicode' if 'wqy' in font_file.lower() or style=='wqy-unicode' else style,'font_file_identifier':font_file,'computed_text_height':h,'width_factor':wf,'insertion_point':[ins[0],ins[1]],'alignment_mode':f"h={e.first(72,'0')},v={e.first(73,'0')}",'alignment_point':list(align) if align else None,'baseline_lift':0.0,'rotation':rot,'predicted_dxf_text_bbox':[[round(x,6),round(y,6)] for x,y in pred], 'target_ocr_bbox_cad':[[round(x,6),round(y,6)] for x,y in target],'predicted_width_over_target':float(rw/tw) if tw else None,'predicted_height_over_target':float(rh/th) if th else None,'center_offset_x':((pred_aabb[0]+pred_aabb[2])/2-target_center[0]),'center_offset_y':((pred_aabb[1]+pred_aabb[3])/2-target_center[1]),'crosses_nearby_table_cell_boundary':crosses,'nearby_structural_line_count':nearby,'rotation_class':orientation,'source_text_outline_participated':False,'metric_source':metric_source,'metric_fallback':metric_fallback,'raw_width_factor':raw_wf,'width_factor_clamped':clamped})
    return dict(records=recs,lines=lines,styles=styles,layers=layers,extmin=extmin,extmax=extmax)
