"""Verified native PDF text before raster ownership, with a rendered fallback.

Content is checked against the embedded font's Unicode-to-glyph mapping.
Paint authority comes from activating actual PDF objects on the same canvas;
neither a character rectangle nor a Unicode string authorizes raster removal.
"""
from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass
from io import BytesIO
from math import ceil, floor
from pathlib import Path
import re

import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.pdf_text_suggestions import _address, _render_page

VERSION = "embedded-cmap-visible-native-text-v7-stable-cell-source"


@dataclass
class NativeTextPlan:
    background: np.ndarray
    texts: tuple
    retired: np.ndarray
    records: list
    suppressed_ocr: list
    native_ink: np.ndarray | None = None


def residual_ocr_partition(gray, plan, original, fresh=(), *, source_carriers=None):
    """Keep unaffected reads; re-read only actual remaining mixed source ink.

    Spatial intersection schedules a re-read. It never deletes a mixed row or
    proves its remaining characters. A failed remainder cancels its native
    source transaction in the caller.
    """
    from app.geometry.content_ownership import _candidate_region_mask

    ink=plan.native_ink
    if ink is None:
        return tuple(original),(),(),np.zeros(gray.shape,bool)
    kept, affected, needs = [], [], {}
    for i,text in enumerate(original):
        carrier=source_carriers[i] if source_carriers is not None else text
        region=_candidate_region_mask(carrier,gray.shape)>0
        if not np.any(region & ink):
            kept.append(text)
            continue
        affected.append(i)
        body=np.zeros(gray.shape,bool)
        if carrier.character_boxes:
            for x,y,w,h in carrier.character_boxes:
                body[max(0,y):y+h,max(0,x):x+w]=True
        else:
            body=region
        foreign=body & (gray<250) & ~ink
        parts=[]
        for native in plan.texts:
            x,y,w,h=native.bbox
            if np.any(region[max(0,y):y+h,max(0,x):x+w] & ink[max(0,y):y+h,max(0,x):x+w]):
                parts.append(native)
        axis=1 if text.bbox[3]>text.bbox[2] and all(len(t.text)==1 for t in parts) else 0
        parts.sort(key=lambda t:t.bbox[axis])
        def normal(s):
            return "".join(s.split())
        if parts and normal(text.text)==normal("".join(t.text for t in parts)):
            # Same complete source transcript: foreign padding is retained
            # structure, rather than a missing OCR suffix to invent.
            foreign[:]=False
        if np.any(foreign):
            needs[i]=foreign
    required=np.zeros(gray.shape,bool)
    for mask in needs.values():
        required |= mask
    covered=np.zeros(gray.shape,bool)
    for text in fresh:
        claim=(_candidate_region_mask(text,gray.shape)>0) & (plan.background<255)
        if np.any(claim & required) and not np.any(claim & ~required):
            kept.append(text)
            covered |= claim
    failed=tuple(i for i,mask in needs.items() if np.any(mask & ~covered))
    return tuple(kept),failed,tuple(affected),required


def mixed_source_rollback_objects(plan, original, failed):
    """Atomic source-object/old-carrier closure, local to unresolved rows."""
    rows={i for i in failed}
    objects=set()

    def intersects(a,b):
        x,y,w,h=a
        u,v,s,t=b
        return max(x,u)<min(x+w,u+s) and max(y,v)<min(y+h,v+t)

    def carrier_hits(text,boxes):
        return any(intersects(a,b) for a in (text.bbox,*text.character_boxes) for b in boxes)

    changed=True
    while changed:
        previous=(len(rows),len(objects))
        for record in plan.records:
            if record["decision"]!="ADOPTED":
                continue
            if record["object_index"] in objects or any(carrier_hits(original[i],record["bboxes"]) for i in rows):
                objects.add(record["object_index"])
                rows.update(i for i,text in enumerate(original) if carrier_hits(text,record["bboxes"]))
        changed=previous!=(len(rows),len(objects))
    return objects


def _font_name(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^[A-Z]{6}\+", "", name).lower())


def _mapping_evidence(path, page_index):
    """Independent embedded cmap and painted glyph IDs, not parser consensus."""
    import pymupdf
    from fontTools.ttLib import TTFont

    with pymupdf.open(path) as document:
        page = document[page_index]
        if page.cropbox != page.mediabox:
            raise ValueError("NATIVE_PAGE_TRANSFORM")
        # Optional layers and annotation appearances keep their renderer
        # defaults. Per-object actual-paint tests below establish visibility;
        # their mere presence is not a reason to discard visible source text.
        cmaps = {}
        for xref, _, _, name, *_ in page.get_fonts(full=True):
            data = document.extract_font(xref)[3]
            if not data:
                continue
            try:
                with TTFont(BytesIO(data)) as font:
                    cmap = font.getBestCmap() or {}
                    mapping = {u: font.getGlyphID(glyph) for u, glyph in cmap.items()}
                    for alias in {name, font["name"].getDebugName(6) or name}:
                        cmaps.setdefault(_font_name(alias), []).append(mapping)
            except Exception:
                continue  # This font stays on the existing raster/OCR branch.
        chars = []
        for row in page.get_texttrace():
            if row["type"] != 0 or row.get("opacity", 1) != 1:
                continue
            maps = cmaps.get(_font_name(row["font"]), ())
            for code, glyph, origin, _ in row["chars"]:
                # A reused font name is not an actual font reference. Admit
                # this character only when every embedded map under that name
                # agrees on its painted glyph ID; ambiguous subsets fall back.
                if maps and all(cmap.get(code) == glyph and glyph != 0 for cmap in maps):
                    chars.append((int(code), float(origin[0]), float(origin[1])))
        return page.mediabox.height, chars


def _frame(obj, pos):
    a,b,c,d,e,f = obj.get_matrix().get()
    origin = np.asarray(pos.to_bitmap(e,f),float)
    u = np.asarray(pos.to_bitmap(e+1000*a,f+1000*b),float)-origin
    v = origin-np.asarray(pos.to_bitmap(e+1000*c,f+1000*d),float)
    if min(np.linalg.norm(u),np.linalg.norm(v)) <= 1e-9:
        raise ValueError("DEGENERATE_NATIVE_BASIS")
    u,v = u/np.linalg.norm(u),v/np.linalg.norm(v)
    if u[0]*v[1]-u[1]*v[0] <= 0:
        raise ValueError("NATIVE_REFLECTED_TEXT_UNSUPPORTED")
    if abs(u@v)>1e-6 or min(abs(u[0]),abs(u[1]))>1e-6:
        raise ValueError("NATIVE_NON_ORTHOGONAL_BASIS")
    return origin,u,v


def _segments(obj, indexes, tp, pos, raw):
    """Split discontinuous source placements, not guessed words or strings."""
    _,u,v = _frame(obj,pos)
    groups, group, previous = [], [], None
    for index in indexes:
        char=chr(raw.FPDFText_GetUnicode(tp,index) or 0xfffd)
        if char.isspace():
            group.append(index)
            continue
        x,y=ct.c_double(),ct.c_double()
        if not raw.FPDFText_GetCharOrigin(tp,index,ct.byref(x),ct.byref(y)):
            raise ValueError("NO_NATIVE_CHARACTER_ORIGIN")
        p=np.asarray(pos.to_bitmap(x.value,y.value),float)
        left_coord,b,r,t=tp.get_charbox(index)
        corners=np.asarray([pos.to_bitmap(a,z) for a,z in ((left_coord,b),(left_coord,t),(r,b),(r,t))])
        height=max(1,float(np.ptp(corners@v)))
        if previous is not None:
            old,old_height=previous
            delta=p-old
            scale=max(height,old_height)
            if delta@u < -.25*scale or delta@u > 1.7*scale or abs(delta@v) > .3*scale:
                if group:
                    groups.append(group)
                group=[]
        group.append(index)
        previous=(p,height)
    if group:
        groups.append(group)
    return groups


def _candidate(obj, indexes, tp, pos, raw, shape, mapping):
    """Orthogonal source reading basis; each PDF text object remains independent."""
    origin,u,v = _frame(obj,pos)
    points, content, character_boxes, origins = [], [], [], []
    for index in indexes:
        code = int(raw.FPDFText_GetUnicode(tp, index))
        if code <= 0 or code == 0xfffd:
            raise ValueError("INVALID_NATIVE_UNICODE")
        char = chr(code)
        if char.isspace():
            content.append(" ")
            continue
        x, y = ct.c_double(), ct.c_double()
        if not raw.FPDFText_GetCharOrigin(tp, index, ct.byref(x), ct.byref(y)):
            raise ValueError("NO_NATIVE_CHARACTER_ORIGIN")
        # Both parsers must refer to this actual painted character, and the
        # embedded font cmap must map its Unicode to its actual glyph ID.
        origins.append((code, x.value, y.value))
        left_coord, b, r, t = tp.get_charbox(index)
        corners = np.asarray([pos.to_bitmap(a, z) for a, z in ((left_coord,b),(left_coord,t),(r,b),(r,t))], float)
        points.extend(corners)
        lo, hi = corners.min(axis=0), corners.max(axis=0)
        character_boxes.append((floor(lo[0]), floor(lo[1]), max(1, ceil(hi[0])-floor(lo[0])), max(1, ceil(hi[1])-floor(lo[1]))))
        content.append(char)
    text = " ".join("".join(content).split())
    if not text or not points:
        raise ValueError("EMPTY_NATIVE_TEXT")
    # Mapping positions are in unrotated, top-left PDF points.
    page_height = mapping[0]
    for code, x, y in origins:
        if not any(c == code and abs(a-x) < .02 and abs(b-(page_height-y)) < .02 for c, a, b in mapping[1]):
            raise ValueError("EMBEDDED_CMAP_GLYPH_NOT_CONFIRMED")
    p = np.asarray(points)-origin
    along, across = p@u, p@v
    a, b, c, d = along.min(), across.min(), along.max(), across.max()
    quad = tuple(tuple(map(float, origin+x*u+y*v)) for x,y in ((a,b),(c,b),(c,d),(a,d)))
    lo, hi = np.asarray(quad).min(axis=0), np.asarray(quad).max(axis=0)
    if np.any(lo < 0) or hi[0] > shape[1] or hi[1] > shape[0] or min(c-a,d-b) <= .1:
        raise ValueError("NATIVE_GEOMETRY_OUTSIDE_PAGE")
    bbox = (floor(lo[0]),floor(lo[1]),ceil(hi[0])-floor(lo[0]),ceil(hi[1])-floor(lo[1]))
    return TextCandidate(text, bbox, 1.0, "text_candidate", quad=quad,
                         source="pdf_native_visible_cmap", character_boxes=tuple(character_boxes))


def collect_native_text(
    image, evidence, ocr_texts, *, mode, protected_masks=(),
    excluded_object_indices=(), protected_retirement_masks=(),
):
    """Return original fallback on unsupported sources; never modify the PDF."""
    import pypdfium2 as pdfium
    from app.export.ocr_outline_export import native_text_placement
    from app.geometry.pdf_arc_evidence import pdf_geometry_binding
    from app.geometry.text_residual_retirement import pixel_runs

    records = []
    empty = NativeTextPlan(image, (), np.zeros(image.shape, np.uint8), records, [])
    if evidence is None:
        return empty
    document = page = bitmap = tp = None
    try:
        binding = evidence.binding
        path = Path(binding["document"])
        page_index, dpi = int(binding["page_number"])-1, float(binding["requested_dpi"])
        if image.ndim != 2 or image.size > 32_000_000 or path.stat().st_size > 512_000_000:
            raise ValueError("NATIVE_INPUT_BUDGET")
        if pdf_geometry_binding(path,page_index,dpi) != binding:
            raise ValueError("NATIVE_BINDING_CHANGED")
        snapshot = path.read_bytes()
        mapping = _mapping_evidence(path, page_index)
        document = pdfium.PdfDocument(snapshot)
        page = document[page_index]
        bitmap = page.render(scale=dpi/72, grayscale=True)
        original = np.array(bitmap.to_pil().convert("L"))
        if not np.array_equal(image, original):
            raise ValueError("NATIVE_PARENT_CANVAS_MISMATCH")
        pos = bitmap.get_posconv(page)
        tp = page.get_textpage()
        if not tp.count_chars():
            return empty
        objects = list(page.get_objects(max_depth=1,textpage=tp))
        if len(objects) > 32768 or tp.count_chars() > 20000:
            raise ValueError("NATIVE_OBJECT_BUDGET")
        raw = pdfium.raw
        states = []
        by_address = {_address(o.raw):i for i,o in enumerate(objects)}
        groups = {}
        for j in range(tp.count_chars()):
            if not raw.FPDFText_IsGenerated(tp,j):
                i = by_address.get(_address(raw.FPDFText_GetTextObject(tp,j)))
                if i is not None:
                    groups.setdefault(i,[]).append(j)
        for obj in objects:
            state = raw.FPDF_BOOL()
            if not raw.FPDFPageObj_GetIsActive(obj,ct.byref(state)):
                raise ValueError("NATIVE_ACTIVE_STATE_UNAVAILABLE")
            states.append(state.value)

        def activate(selected):
            for j, obj in enumerate(objects):
                state = states[j] if selected(j) else 0
                if not raw.FPDFPageObj_SetIsActive(obj,state):
                    raise ValueError("NATIVE_ACTIVE_STATE_FAILED")

        selected, candidates = [], []
        native_ink = np.zeros(image.shape,bool)
        try:
            area_objects = set()
            for i,obj in enumerate(objects):
                if obj.type == raw.FPDF_PAGEOBJ_PATH:
                    fill,stroke = ct.c_int(),raw.FPDF_BOOL()
                    if not raw.FPDFPath_GetDrawMode(obj,ct.byref(fill),ct.byref(stroke)):
                        raise ValueError("NATIVE_AREA_PAINT_UNAVAILABLE")
                    if fill.value:
                        area_objects.add(i)
                elif obj.type not in (raw.FPDF_PAGEOBJ_TEXT,):
                    area_objects.add(i)
            activate(lambda j:j in area_objects)
            area_paint = _render_page(page,dpi/72)
            activate(lambda j:True)
            for i,indexes in groups.items():
                obj = objects[i]
                if obj.type != raw.FPDF_PAGEOBJ_TEXT:
                    continue
                rec = dict(object_index=i, decision="FALLBACK")
                records.append(rec)
                try:
                    rec["observed_pdf_text"] = obj.extract()
                    if i in excluded_object_indices:
                        raise ValueError("UNRESOLVED_MIXED_SOURCE_CARRIER")
                    clip = raw.FPDFPageObj_GetClipPath(obj)
                    rgba = [ct.c_uint() for _ in range(4)]
                    if (not states[i] or not clip or raw.FPDFClipPath_CountPaths(clip) != -1
                            or raw.FPDFTextObj_GetTextRenderMode(obj) != 0
                            or raw.FPDFPageObj_HasTransparency(obj)
                            or not raw.FPDFPageObj_GetFillColor(obj,*[ct.byref(v) for v in rgba])
                            or tuple(v.value for v in rgba) != (0,0,0,255)):
                        raise ValueError("UNSUPPORTED_NATIVE_PAINT_OR_CLIP")
                    parts = []
                    for segment in _segments(obj,indexes,tp,pos,raw):
                        candidate = _candidate(obj,segment,tp,pos,raw,image.shape,mapping)
                        placement = native_text_placement(candidate,transform=lambda x,y:(x,image.shape[0]-y))
                        if placement is None or placement.metrics.fallback_reason:
                            raise ValueError("NATIVE_TARGET_FONT_UNAVAILABLE")
                        x,y,w,h = candidate.bbox
                        overlaps = [t for t in ocr_texts if max(x,t.bbox[0]) < min(x+w,t.bbox[0]+t.bbox[2])
                                    and max(y,t.bbox[1]) < min(y+h,t.bbox[1]+t.bbox[3])]
                        if mode == "omissions" and overlaps:
                            raise ValueError("EXISTING_OCR_CARRIER_OVERLAPS")
                        if mode == "matched" and not any(" ".join(t.text.split()) == candidate.text for t in overlaps):
                            raise ValueError("MATCHED_ROUTE_REQUIRES_EXISTING_TRANSCRIPT")
                        parts.append(candidate)
                    rec.update(text=[t.text for t in parts], bboxes=[t.bbox for t in parts], quads=[t.quad for t in parts])
                    activate(lambda j:j==i)
                    only = _render_page(page,dpi/72)
                    ink = only < 250
                    if not np.any(ink) or np.any(image[ink].astype(int) > only[ink].astype(int)+2):
                        raise ValueError("NATIVE_PAINT_OCCLUDED_OR_NOT_VISIBLE")
                    # A dark painted area can hide glyphs without making the
                    # all-object rendering lighter. Do not resurrect those
                    # glyphs as colored editable TEXT. Open source strokes may
                    # still intersect text; they stay on the structural canvas.
                    if np.any(ink & (area_paint<250)):
                        raise ValueError("NATIVE_GLYPH_OVERLAPS_PAINTED_AREA")
                    if any(np.any(ink & (m>0)) for m in protected_masks):
                        raise ValueError("PROTECTED_GRAPHIC_OR_SIGNATURE")
                    if mode == "omissions" and any(
                        np.any(ink[y:y+h, x:x+w]) for x, y, w, h in (t.bbox for t in ocr_texts)
                    ):
                        raise ValueError("EXISTING_OCR_CARRIER_OVERLAPS_PAINT")
                    if mode == "matched":
                        from app.geometry.content_ownership import _candidate_region_mask

                        for old in ocr_texts:
                            claim = (_candidate_region_mask(old,image.shape)>0) & (image<255)
                            if np.any(claim & (only<255)) and np.any(claim & (only==255)):
                                raise ValueError("MATCHED_CARRIER_HAS_UNREPLACED_SOURCE")
                    activate(lambda j:j!=i)
                    without = _render_page(page,dpi/72)
                    changed = image != without
                    if not np.any(changed):
                        raise ValueError("NATIVE_OBJECT_HAS_NO_VISIBLE_CONTRIBUTION")
                    # Excluding this text may reveal actual structure. It must
                    # never darken unrelated pixels outside its actual paint.
                    if np.any(changed & (only==255)):
                        raise ValueError("NATIVE_PAINT_HAS_EXTERNAL_EFFECT")
                    if mode == "omissions":
                        exclusive = changed & (without == 255)
                        if not np.any(exclusive & (image < 128)):
                            raise ValueError("NO_EXCLUSIVE_NATIVE_GLYPH_INK")
                        if np.any(ink & native_ink) or any(
                            np.any(exclusive & (mask > 0)) for mask in protected_retirement_masks
                        ):
                            raise ValueError("NATIVE_RETIREMENT_OWNERSHIP_CONFLICT")
                    selected.append(i)
                    candidates.extend(parts)
                    native_ink |= only<255
                    rec.update(decision="ADOPTED", reason="VISIBLE_NATIVE_OBJECT_EMBEDDED_CMAP",
                               mapping="EMBEDDED_CMAP_EQUALS_PAINTED_GLYPH_ID_AND_ORIGIN",
                               source_runs=pixel_runs(changed), shared_structure_pixels=int(np.count_nonzero(ink & (without<250))))
                except (ValueError,TypeError,IndexError,OverflowError) as exc:
                    rec["reason"] = str(exc)
                finally:
                    activate(lambda j:True)
            if not selected:
                return empty
            ids = set(selected)
            activate(lambda j:j not in ids)
            background = _render_page(page,dpi/72)
        finally:
            activate(lambda j:True)
            if not np.array_equal(_render_page(page,dpi/72),image):
                raise ValueError("NATIVE_RESTORED_PAINT_CHANGED")
        if path.read_bytes() != snapshot:
            raise ValueError("NATIVE_SOURCE_CHANGED")
        if np.any((image != background) & ~native_ink):
            raise ValueError("NATIVE_JOINT_PAINT_HAS_EXTERNAL_EFFECT")
        retired = np.uint8((image != background) & (image<255))*255
        if mode == "omissions":
            retired[background != 255] = 0
        suppressed = []
        if mode == "matched":
            from app.geometry.content_ownership import _candidate_region_mask

            for index,t in enumerate(ocr_texts):
                claim = (_candidate_region_mask(t,image.shape)>0) & (image<255)
                if np.any(claim & native_ink):
                    if np.any(claim & ~native_ink):
                        raise ValueError("MATCHED_TRANSACTION_HAS_PARTIAL_OCR_CARRIER")
                    suppressed.append(index)
        return NativeTextPlan(background,tuple(candidates),retired,records,suppressed,native_ink)
    except Exception as exc:
        for row in records:
            if row["decision"] == "ADOPTED":
                row.update(decision="FALLBACK",reason="NATIVE_TRANSACTION_ROLLED_BACK")
        records.append(dict(decision="FALLBACK",reason=f"{type(exc).__name__}: {exc}"))
        return empty
    finally:
        for obj in (tp,bitmap,page,document):
            if obj is not None:
                obj.close()
