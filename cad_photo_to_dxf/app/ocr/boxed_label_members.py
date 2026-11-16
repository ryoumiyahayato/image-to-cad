"""Bind short horizontal labels to independent ink inside observed closed frames.

No OCR, spelling correction, inferred frame completion or deletion authority is
introduced. A rectangle is a search/ownership witness, not new CAD geometry.
"""
from dataclasses import replace
import cv2
import numpy as np
from app.ocr.auxiliary_recognition import TextObservation
from app.ocr.text_output_contract import text_output_decisions

VERSION = "observed-boxed-label-members-v1"


def observe_boxed_members(gray, candidate):
    """Return measured character boxes only for a unique, complete source frame."""
    text = candidate.text
    if (not text.isascii() or not text.isalnum() or not 2 <= len(text) <= 8
            or candidate.reviewed or candidate.display_quad is not None
            or not candidate.source.startswith("rapidocr")
            or abs(candidate.rotation_deg) > 0.01
            or not text_output_decisions((candidate,))[0].text_emit_eligible):
        return None
    x, y, w, h = candidate.bbox
    if min(w, h) < 6 or w*h > 16384 or not candidate.quad:
        return None
    q = np.asarray(candidate.quad, dtype=float)
    if q.shape != (4, 2) or not np.isfinite(q).all():
        return None
    if not (np.max(np.abs(q - np.asarray(((x,y),(x+w,y),(x+w,y+h),(x,y+h))))) <= 1.0):
        return None
    pad = max(3, int(round(h*0.35)))
    left, top = max(0,x-pad), max(0,y-pad)
    right, bottom = min(gray.shape[1],x+w+pad), min(gray.shape[0],y+h+pad)
    crop = gray[top:bottom, left:right]
    if crop.size > 65536 or not crop.size:
        return None
    # Non-white pixels provide a closed-boundary witness; no thresholded raster
    # replaces the production input. Strong ink separately verifies each glyph.
    ink = np.uint8(crop < 254)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return None
    choices = []
    for ci, contour in enumerate(contours):
        parent = int(hierarchy[0, ci, 3])
        if parent < 0:
            continue
        # Inner contour: it must enclose independent source components, not a
        # character's empty counter. Both axes are bounded by the observation.
        fx,fy,fw,fh = map(int,cv2.boundingRect(contour))
        if not (fw >= 10 and fh >= 8 and .55*w <= fw <= 1.3*w
                and .45*h <= fh <= 1.2*h and 1.2 <= fw/fh <= 8):
            continue
        if not (fx < x-left+w*.5 < fx+fw and fy < y-top+h*.5 < fy+fh):
            continue
        area=float(cv2.contourArea(contour));perim=float(cv2.arcLength(contour,True))
        corners=cv2.approxPolyDP(contour, .025*perim, True).reshape(-1,2)
        if len(corners)!=4 or area < .85*(fw-1)*(fh-1):
            continue
        edges=np.roll(corners,-1,axis=0)-corners
        if any(min(abs(dx),abs(dy))>max(1.,.08*max(abs(dx),abs(dy))) for dx,dy in edges):
            continue
        interior=np.zeros(ink.shape,np.uint8)
        cv2.drawContours(interior,[contour],0,1,-1)
        boundary_labels=set(int(v) for v in np.unique(labels[contour[:,0,1],contour[:,0,0]]) if v)
        if len(boundary_labels)!=1:
            continue
        # A rectangular hole in a connected fixture is not an independent
        # label frame. Reassigning its text can change distant source tracing.
        # Require the COMPLETE boundary component within the observation and
        # a bounded ring around the hole; do not clip away attached branches.
        boundary_label = next(iter(boundary_labels))
        rx, ry, rw, rh, _ = map(int, stats[boundary_label])
        if (rx <= 0 or ry <= 0 or rx + rw >= crop.shape[1]
                or ry + rh >= crop.shape[0]
                or rx < fx - 2 or ry < fy - 2
                or rx + rw > fx + fw + 2 or ry + rh > fy + fh + 2):
            continue
        # Full connected components must be contained; no breaking a touching
        # arrow/frame, dropping a dot, or silently clipping a partial glyph.
        found=[];bad=False
        for lab in np.unique(labels[(interior>0)&(ink>0)]):
            lab=int(lab)
            if lab==0 or lab in boundary_labels:continue
            gx,gy,gw,gh,pixels=map(int,stats[lab])
            if (gx<=fx or gy<=fy or gx+gw>=fx+fw or gy+gh>=fy+fh
                    or np.any((labels==lab)&(interior==0))
                    or not np.any((labels==lab)&(crop<128))):
                bad=True;break
            found.append((lab,gx,gy,gw,gh,pixels))
        if bad or len(found)!=len(text):continue
        found.sort(key=lambda z:z[1]);heights=[z[4] for z in found]
        if min(heights)<max(4,fh*.35) or max(heights)>1.5*min(heights):continue
        if any(a[1]+a[3]>=b[1] for a,b in zip(found,found[1:])):continue
        boxes=tuple((left+gx,top+gy,gw,gh) for _,gx,gy,gw,gh,_ in found)
        bx=min(b[0] for b in boxes);by=min(b[1] for b in boxes)
        ex=max(b[0]+b[2] for b in boxes);ey=max(b[1]+b[3] for b in boxes)
        # This correction may shrink an observed window, never find extra text
        # outside it. Border inflation, not content identity, is being corrected.
        if bx<x or by<y or ex>x+w or ey>y+h or ey-by>h-2:continue
        owned=np.isin(labels,[z[0] for z in found])
        # One blank-pixel separation keeps the tightened placement off the frame.
        if np.any((cv2.dilate(np.uint8(owned),np.ones((3,3),np.uint8))>0)
                  & np.isin(labels,list(boundary_labels))):continue
        choices.append(dict(frame_bbox=[left+fx,top+fy,fw,fh],
                            bbox=(bx,by,ex-bx,ey-by),character_boxes=boxes,
                            member_pixels=int(np.count_nonzero(owned)),
                            frame_component_bbox=[left+rx,top+ry,rw,rh],
                            frame_component_pixels=int(sum(stats[k,4] for k in boundary_labels))))
    # Duplicate contour approximations of the same inner ring do not grant
    # selection among genuinely different/nested enclosures.
    unique={tuple(c['frame_bbox']):c for c in choices}
    if len(unique)!=1:return None
    return next(iter(unique.values()))


def refine_boxed_label_members(gray, texts, *, protected_masks=(), verified_sources=None):
    if (gray.ndim != 2 or gray.dtype != np.uint8 or gray.size>32_000_000
            or len(texts)>512):
        return tuple(texts), ()
    output=list(texts);records=[];budget=1_048_576
    for i,t in enumerate(texts):
        x,y,w,h=t.bbox;budget-=(w+h+8)*(h*2+8)
        if budget<0:break
        proof=observe_boxed_members(gray,t)
        if proof is None:continue
        fx,fy,fw,fh=proof['frame_bbox']
        if any(m is not None and np.any(m[fy:fy+fh,fx:fx+fw]) for m in protected_masks):continue
        # A unique candidate is required inside the observed frame.
        if any(j!=i and fx<o.bbox[0]+o.bbox[2]/2<fx+fw
               and fy<o.bbox[1]+o.bbox[3]/2<fy+fh for j,o in enumerate(texts)):continue
        bx,by,bw,bh=proof['bbox'];quad=((float(bx),float(by)),(float(bx+bw),float(by)),
                                     (float(bx+bw),float(by+bh)),(float(bx),float(by+bh)))
        # Reuse the normal source-safety contract on an exact isolated-member
        # observation. The frame is not erased from the production raster.
        from app.ocr.ocr_fast import prepare_safe_candidate
        from app.ocr.ocr_layout import VerifiedCellTextSource, offset_candidate
        margin=3; lx=max(0,fx-margin); ly=max(0,fy-margin)
        rx=min(gray.shape[1],fx+fw+margin); ry=min(gray.shape[0],fy+fh+margin)
        crop=gray[ly:ry,lx:rx]; core=np.zeros(crop.shape,np.uint8)
        for cx,cy,cw,ch in proof['character_boxes']:
            win=np.s_[cy-ly:cy-ly+ch,cx-lx:cx-lx+cw]
            core[win]=np.uint8(crop[win]<254)*255
        isolated=np.where(core>0,crop,255).astype(np.uint8)
        local=replace(t,bbox=(bx-lx,by-ly,bw,bh),
                      quad=tuple((a-lx,b-ly) for a,b in quad),character_boxes=())
        checked=offset_candidate(prepare_safe_candidate(isolated,local),offset_x=lx,offset_y=ly)
        if not checked.replacement_safe:
            continue
        # Complete membership, not a string format or score, supplies this proof.
        output[i]=replace(t,bbox=proof['bbox'],quad=quad,character_boxes=proof['character_boxes'],
                          replacement_safe=checked.replacement_safe,
                          review_note=t.review_note+'; observed separate frame and complete inner members',
                          pre_cell_observation=t.pre_cell_observation or TextObservation.capture(t,i))
        if verified_sources is not None:
            verified_sources.append(VerifiedCellTextSource((lx,ly,rx,ry),core,
                                    (output[i],),(core.copy(),)))
        records.append(dict(index=i,text=t.text,original_bbox=t.bbox,original_quad=t.quad,
                            original_character_boxes=t.character_boxes,**proof,
                            text_content_changed=False,source_deletion_authority=False,
                            rectangle_geometry_created=False))
    return tuple(output),tuple(records)
