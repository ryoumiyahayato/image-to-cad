"""Separate a demonstrably merged dimension chain without inventing measurements.

The ruling is observation/segmentation evidence, never a command to erase or
recreate geometry. Only independent source components can be read as labels.
Confirmed labels enter the normal text/ownership pipeline; undecidable labels
keep their source. No CAD length, expected number, coordinate or dictionary is
used to choose text. This initial contract is for horizontal printed chains.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from math import isfinite
import re
from typing import Callable, Sequence
import cv2
import numpy as np
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.source_token_review import _read_pairs

MAX_AREA = 65536
MAX_CHAINS = 12
DIGIT_SCORE = 0.90

@dataclass(frozen=True)
class ChainObservation:
    bounds: tuple[int, int, int, int]
    baseline: int
    witnesses: tuple[tuple[int, int, int, int], ...]
    labels: tuple[tuple[int, int, int, int], ...]
    components: tuple[tuple[tuple[int, int, int, int], ...], ...]


def _eligible(t: TextCandidate) -> bool:
    x, y, w, h = t.bbox
    return (t.approved and not t.reviewed and t.source.startswith('rapidocr-')
            and isfinite(t.confidence) and 0.5 <= t.confidence < .85
            and isfinite(t.rotation_deg) and abs(t.rotation_deg) <= 3
            and t.text.isascii() and len(re.findall(r'[0-9]', t.text)) >= 2
            and not re.search(r'[A-Za-z]{3}', t.text)
            and 16 <= h <= 96 and w >= 3*h and w*h <= MAX_AREA)


def observe_chain(gray: np.ndarray, t: TextCandidate) -> ChainObservation | None:
    """Require a baseline crossed by >=4 independently observed short witnesses."""
    if not _eligible(t):
        return None
    x,y,w,h = map(int,t.bbox); ih,iw=gray.shape
    pad=max(3,h//3)
    a,b=max(0,x-pad),max(0,y-pad);u,v=min(iw,x+w+pad),min(ih,y+h+pad)
    if min(x,y)<0 or x+w>iw or y+h>ih or (u-a)*(v-b)>MAX_AREA:
        return None
    crop=gray[b:v,a:u];ink=np.uint8(crop<160)
    horizontal=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(25,round(w*.45))),np.uint8))
    _,_,hs,_=cv2.connectedComponentsWithStats(horizontal,connectivity=8)
    seeds=[s for s in hs[1:] if s[2]>=w*.40 and s[3]<=max(3,h*.1)
           and y+.45*h<=b+s[1]<=y+h]
    if len(seeds)!=1:
        return None
    seed=seeds[0];base=int(b+seed[1]+(seed[3]-1)/2)
    vertical=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(12,round(h*.45)),1),np.uint8))
    _,_,vs,_=cv2.connectedComponentsWithStats(vertical,connectivity=8)
    witnesses=[]
    for sx,sy,sw,sh,area in vs[1:]:
        gx,gy=int(a+sx),int(b+sy)
        if (sw<=max(3,h*.12) and .45*h<=sh<=1.2*h
                and y-h*.1<=gy<=y+.5*h and gy<base-5
                and base+1<=gy+sh<=base+h*.4
                and x-pad*.2<=gx<=x+w+pad*.2):
            witnesses.append((gx,gy,int(sw),int(sh)))
    witnesses.sort()
    if not 4<=len(witnesses)<=16 or witnesses[-1][0]-witnesses[0][0]<w*.60:
        return None
    if any(q[0]-(p[0]+p[2])<3 for p,q in zip(witnesses,witnesses[1:])):
        return None
    heights=[r[3] for r in witnesses]; tops=[r[1] for r in witnesses]
    if max(tops)-min(tops)>max(3,h*.15):
        return None
    left,right=witnesses[0][0],witnesses[-1][0]+witnesses[-1][2]
    band=gray[max(0,base-2):min(ih,base+3),left:right]
    if np.mean(np.any(band<160,axis=0))<.90:
        return None
    # Observe disconnected label ink in the strip ABOVE the dimension baseline.
    # Rule-connected arrows/ticks are excluded because their components extend
    # through the baseline, not because of their apparent text or area.
    top=int(np.median(tops))-1;bottom=base-2
    count,lab,stats,_=cv2.connectedComponentsWithStats(ink,connectivity=8)
    parts=[]
    for k in range(1,count):
        sx,sy,sw,sh,area=map(int,stats[k]);gx,gy=a+sx,b+sy
        if (gx>=x-2 and gx+sw<=x+w+2 and gy>=top and gy+sh<=bottom
                and sh<=.75*np.median(heights) and area>=1):
            parts.append((gx,gy,sw,sh,k))
    cuts=[x-2]+[q[0]+q[2]/2 for q in witnesses]+[x+w+2]
    groups=[]
    for lo,hi in zip(cuts,cuts[1:]):
        comp=sorted([p for p in parts if p[0]>lo+1 and p[0]+p[2]<hi-1])
        if not comp:
            continue
        body_h=max(p[3] for p in comp)
        # Only split on observed horizontal whitespace; no character-count hint.
        group=[comp[0]]
        for p in comp[1:]:
            if p[0]-(group[-1][0]+group[-1][2])>max(3,body_h*.85):
                groups.append(group);group=[]
            group.append(p)
        groups.append(group)
    # A shared bounding rectangle is not shared source ink. Only a component
    # actually connected to the independently observed ruler may intrude into
    # the whitespace between separated character components. It must not enter
    # the per-character source regions (including their one-pixel padding).
    base_local = lab[max(0,base-b-1):min(lab.shape[0],base-b+2),
                     max(0,left-a):min(lab.shape[1],right-a)]
    ruler_ids = set(map(int,np.unique(base_local))) - {0}
    boxes=[];members=[]
    for group in groups:
        if len(group)<2 or max(p[3] for p in group)<5:
            continue
        gx=min(p[0] for p in group);gy=min(p[1] for p in group)
        gu=max(p[0]+p[2] for p in group);gv=max(p[1]+p[3] for p in group)
        if gu-gx>5*(gv-gy) or gv-gy<5:
            continue
        # The bounding crop must not also contain unowned arrow/line pixels.
        local=lab[gy-b:gv-b,gx-a:gu-a]
        members_set = {p[4] for p in group}
        foreign = set(map(int,np.unique(local))) - {0, *members_set}
        if foreign and not foreign.issubset(ruler_ids):
            continue
        if foreign:
            clean = True
            for px,py,pw,ph,pid in group:
                a0=max(0,px-a-1); b0=max(0,py-b-1)
                a1=min(lab.shape[1],px-a+pw+1); b1=min(lab.shape[0],py-b+ph+1)
                if set(map(int,np.unique(lab[b0:b1,a0:a1]))) - {0,*members_set}:
                    clean = False; break
            if not clean:
                continue
        boxes.append((gx-1,gy-1,gu-gx+2,gv-gy+2))
        members.append(tuple(p[:4] for p in group))
    if len(boxes)<2:
        return None
    return ChainObservation((x,y,w,h),base,tuple(witnesses),tuple(boxes),tuple(members))


def _raised_marks(gray, boxes, body_top, body_h):
    """Recognize detached unit strokes from position and gray-level lobes.

    Returns only 1 or 2 observed strokes. A small horizontal blob does not
    become a double quote unless its upper source profile has two ink lobes.
    """
    if not boxes or len(boxes)>2:
        return None
    strokes=0
    for x,y,w,h in boxes:
        if (y>body_top+body_h*.30 or y+h>body_top+body_h*.65
                or h>body_h*.65 or h<2 or w>body_h*.55):
            return None
        if w<=max(2,h*.70):
            strokes+=1
        elif len(boxes)==1 and w>=3 and h<=body_h*.40:
            patch=gray[y:y+h,x:x+w]
            profile=np.any(patch[:max(1,(h+1)//2)]<128,axis=0)
            runs=np.count_nonzero(np.diff(np.pad(profile.astype(np.int8),(1,1)))==1)
            if runs!=2:
                return None
            strokes+=2
        else:
            return None
    return strokes if strokes in (1,2) else None


def _isolated_label_view(gray, box, components):
    """Return source-valued component windows for OCR, never a source mask.

    A rectangular token crop can contain a separate ruler in its whitespace.
    Keep every original gray value inside each observed component's one-pixel
    halo. Pixels outside those halos are absent from this *observation only*.
    The caller has already rejected unknown foreign components and connected
    engineering ink; no operation is performed on the production image.
    """
    x,y,w,h=map(int,box)
    crop=gray[y:y+h,x:x+w]
    keep=np.zeros(crop.shape,dtype=bool)
    for px,py,pw,ph in components:
        a=max(x,px-1);b=max(y,py-1)
        u=min(x+w,px+pw+1);v=min(y+h,py+ph+1)
        if u>a and v>b:keep[b-y:v-y,a-x:u-x]=True
    return np.where(keep,crop,255).astype(np.uint8),int(np.count_nonzero((crop<160)&~keep))


def preserve_disjoint_dimension_members(gray, observed, prepared):
    """Do not let generic character boxing reclaim a separate source carrier.

    This only narrows the generic region back to independently observed boxes
    when the generic layout has admitted another connected component. It never
    turns replacement_safe on, never widens the old glyph region and never
    rewrites geometry. Fresh grayscale components verify the supplied boxes;
    missing/stale/clipped/connected members provide no override authority.
    """
    if (gray is None or gray.ndim!=2 or gray.dtype!=np.uint8):
        return prepared
    if (observed.source!='rapidocr-dimension-source-island'
            or not observed.approved or not observed.character_boxes
            or prepared.source!=observed.source or prepared.bbox!=observed.bbox
            or prepared.text!=observed.text or observed.reviewed):
        return prepared
    x,y,w,h=map(int,observed.bbox)
    if (min(x,y)<0 or min(w,h)<1 or x+w>gray.shape[1] or y+h>gray.shape[0]
            or w*h>MAX_AREA or len(observed.character_boxes)>32):
        return prepared
    left=max(0,x-3);top=max(0,y-3)
    right=min(gray.shape[1],x+w+3);bottom=min(gray.shape[0],y+h+3)
    patch=gray[top:bottom,left:right]
    _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(patch<160),connectivity=8)
    members=set();source_region=np.zeros(patch.shape,dtype=bool)
    for px,py,pw,ph in observed.character_boxes:
        a=px-left;b=py-top
        if a<=0 or b<=0 or a+pw>=patch.shape[1] or b+ph>=patch.shape[0]:
            return prepared
        ids=set(map(int,np.unique(labels[b:b+ph,a:a+pw])))-{0}
        if len(ids)!=1:return prepared
        k=next(iter(ids));sx,sy,sw,sh,_=map(int,stats[k])
        if (sx,sy,sw,sh)!=(a,b,pw,ph):return prepared
        members.add(k)
        pad=max(1,int(round(ph*.05)))
        source_region[max(0,b-pad):min(patch.shape[0],b+ph+pad),
                      max(0,a-pad):min(patch.shape[1],a+pw+pad)]=True
    foreign=(labels>0)&~np.isin(labels,list(members))
    if np.any(source_region&foreign):return prepared
    proposed=np.zeros_like(source_region)
    for px,py,pw,ph in prepared.character_boxes:
        pad=max(1,int(round(ph*.05)))
        a=max(0,px-left-pad);b=max(0,py-top-pad)
        u=min(patch.shape[1],px-left+pw+pad);v=min(patch.shape[0],py-top+ph+pad)
        if u>a and v>b:proposed[b:v,a:u]=True
    intrusion=proposed&foreign
    if not np.any(intrusion):return prepared
    # The safe source footprint must already be contained in generic layout.
    if np.any(source_region & ~proposed & (labels>0)):return prepared
    note={'stage':'dimension-disjoint-member-layout-v1',
          'source_note':observed.review_note,
          'generic_layout_note':prepared.review_note,
          'excluded_neighbor_core_pixels':int(np.count_nonzero(intrusion)),
          'source_deletion_authority':'normal_pipeline_only'}
    return replace(prepared,character_boxes=observed.character_boxes,
                   replacement_safe=False,review_note=json.dumps(note,ensure_ascii=False))


def read_label(gray, box, components, recognize):
    """Read independent numeral bodies; punctuation requires separate geometry."""
    heights=[p[3] for p in components]; H=max(heights)
    bodies=[p for p in components if p[3]>=H*.70]
    if not bodies or len(bodies)>8:
        return None,{'reason':'no_independent_digit_bodies'}
    body_top=float(np.median([p[1] for p in bodies]));body_bottom=float(np.median([p[1]+p[3] for p in bodies]))
    if max(abs(p[1]+p[3]-body_bottom) for p in bodies)>max(2,H*.25):
        return None,{'reason':'multiple_baselines'}
    images=[]
    for x,y,w,h in bodies:
        patch=gray[y-1:y+h+1,x-1:x+w+1]
        for pad in (2,4):
            images.append(cv2.cvtColor(np.pad(patch,pad,constant_values=255),cv2.COLOR_GRAY2BGR))
    reads=_read_pairs(recognize,images)
    if reads is None:
        return None,{'reason':'recognizer_unavailable'}
    digits={};scores=[]
    for i,p in enumerate(bodies):
        (t1,s1),(t2,s2)=reads[2*i:2*i+2]
        if t1!=t2 or not re.fullmatch('[0-9]',t1) or min(s1,s2)<DIGIT_SCORE:
            return None,{'reason':'digit_conflict','readings':reads}
        # Numeric grammar does not prove 0/O or 1/I/l identity. The real-model
        # counterexamples include O" and 3'-O" misread with high scores.
        # Reject the entire value, not merely its unit or one character.
        if t1 in {'0', '1'}:
            return None,{'reason':'identity_like_digit','readings':reads}
        digits[p]=t1;scores.extend((s1,s2))
    parts=sorted(components);symbols=[];i=0
    while i<len(parts):
        p=parts[i]
        if p in digits:
            symbols.append(digits[p]);i+=1;continue
        x,y,w,h=p
        # A dash must be detached, at the middle height, between digit groups.
        if (w>=2*h and h<=H*.30 and body_top+H*.30<=y<=body_top+H*.70
                and symbols and i+1<len(parts) and parts[i+1] in digits):
            symbols.append('-');i+=1;continue
        marks=[p]
        if i+1<len(parts) and parts[i+1] not in digits:
            q=parts[i+1]
            if q[0]-(x+w)<=max(2,H*.30) and abs(q[1]-y)<=2:
                marks.append(q)
        count=_raised_marks(gray,marks,body_top,H)
        if count is None or not symbols or not symbols[-1].isdigit():
            return None,{'reason':'unproven_unit_mark','readings':reads}
        symbols.append("'" if count==1 else '"');i+=len(marks)
    text=''.join(symbols)
    if not re.fullmatch(r'(?:[0-9]{1,4}\'\-[0-9]{1,3}\"|[0-9]{1,4}[\'\"])',text):
        return None,{'reason':'unsupported_notation','readings':reads,'observed_symbols':text}
    # A confident contradictory whole-token observation vetoes adoption. Low
    # whole-token scores confer no authority and do not decide punctuation.
    # Numerals above were read independently; units were measured, not guessed
    # from a language model or from the lengths of the dimension intervals.
    x,y,w,h=box;patch=gray[y:y+h,x:x+w]
    views=[cv2.cvtColor(np.pad(patch,pad,constant_values=255),cv2.COLOR_GRAY2BGR) for pad in (2,4)]
    whole=_read_pairs(recognize,views)
    if whole is None:
        return None,{'reason':'token_observation_unavailable'}
    def normal_units(value):
        return ''.join(value.split()).translate(str.maketrans({'′':"'",'’':"'",'″':'"','“':'"','”':'"'}))
    if any(score>=.90 and normal_units(value)!=text for value,score in whole):
        return None,{'reason':'conflicting_whole_token','readings':reads,'whole':whole}
    isolated, excluded=_isolated_label_view(gray,box,components)
    isolated_reads=None
    if excluded:
        views=[cv2.cvtColor(np.pad(isolated,pad,constant_values=255),cv2.COLOR_GRAY2BGR) for pad in (2,4)]
        isolated_reads=_read_pairs(recognize,views)
        if (isolated_reads is None or any(score<DIGIT_SCORE or normal_units(value)!=text
                                         for value,score in isolated_reads)):
            return None,{'reason':'isolated_token_conflict','readings':reads,
                         'whole':whole,'isolated':isolated_reads}
    evidence={'reason':'independent_glyphs_and_unit_marks' ,'text':text,'readings':reads,
              'character_components':[list(p) for p in parts], 'confidence':min(scores), 'whole':whole, 'isolated':isolated_reads,
              'observation_excluded_neighbor_core_pixels':excluded}
    return (text,min(scores)),evidence


def review_dimension_chains(gray: np.ndarray, candidates: Sequence[TextCandidate], *, recognize=None, checkpoint: Callable[[],None]|None=None):
    original=list(candidates)
    if gray is None or gray.ndim!=2 or gray.dtype!=np.uint8:
        return original,[]
    jobs=[]
    for i,t in enumerate(original):
        if checkpoint:checkpoint()
        obs=observe_chain(gray,t)
        if obs is not None and len(jobs)<MAX_CHAINS:
            # Do not supersede another independent accepted text region.
            x,y,w,h=t.bbox
            if any(j!=i and q.approved and q.reviewed and not(q.bbox[0]>=x+w or q.bbox[0]+q.bbox[2]<=x or q.bbox[1]>=y+h or q.bbox[1]+q.bbox[3]<=y) for j,q in enumerate(original)):
                continue
            jobs.append((i,obs))
    if not jobs:return original,[]
    if recognize is None:
        try:
            from app.ocr.ocr_recognition import _get_rapidocr_engine
            recognize=_get_rapidocr_engine().recognize_txt
        except (ImportError,RuntimeError,AttributeError,ValueError):return original,[]
    replacements={};records=[]
    for i,obs in jobs:
        if checkpoint:checkpoint()
        parent=original[i];labels=[];record={'stage':'dimension-chain-source-islands-v1','before':parent.text,
             'parent_bbox':list(parent.bbox),'baseline_y':obs.baseline,'witnesses':[list(x) for x in obs.witnesses],'labels':[]}
        for box,comps in zip(obs.labels,obs.components):
            result,evidence=read_label(gray,box,comps,recognize)
            record['labels'].append({'bbox':list(box),**evidence})
            if result is None:continue
            text,confidence=result;x,y,w,h=box
            labels.append(TextCandidate(text,box,confidence,'dimension_text_candidate',rotation_deg=0.,
                quad=((x,y),(x+w,y),(x+w,y+h),(x,y+h)),source='rapidocr-dimension-source-island',
                approved=True,reviewed=False,character_boxes=tuple(comps),replacement_safe=False,
                review_note=json.dumps({'stage':'dimension-chain-source-islands-v1','parent_text':parent.text,**evidence},ensure_ascii=False)))
        # Until independently read children exist, leave old output untouched.
        if not labels:continue
        # No broad parent mask is retained: its geometry includes engineering
        # strokes. Unrecognized islands remain raw visible ink in the normal
        # trace. Evidence, including parent reading, is retained in child notes.
        record['accepted_count']=len(labels);record['unresolved_count']=len(obs.labels)-len(labels)
        replacements[i]=[replace(label, review_note=json.dumps({
            'stage':'dimension-chain-source-islands-v1', 'chain_observation':record,
            'label_observation':json.loads(label.review_note),
            'source_deletion_authority':'normal_pipeline_only',
        },ensure_ascii=False)) for label in labels]
        records.append(record)
    output=[]
    for i,t in enumerate(original):output.extend(replacements.get(i,[t]))
    return output,records
