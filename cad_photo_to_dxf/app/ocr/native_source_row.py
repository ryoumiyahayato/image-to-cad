"""Optional complete native row recovery before source ownership.

Row geometry does not certify transcription. Actual PDF paint, not a box or
layer, must independently support every source pixel the new carrier claims.
"""
import ctypes as ct
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from app.ocr.observed_text_display import _basis
from app.geometry.text_residual_retirement import pixel_runs

VERSION = "native-row-before-ownership-v4"


def measure_row(gray, observation):
    """Measure one complete ink band; never count OCR character segments."""
    p, u, v, width, height = _basis(observation.quad)
    w, h, pad = round(width), round(height), 2
    if (w+5)*(h+5) > 65_536:
        raise ValueError("ROW_PIXEL_BUDGET")
    expanded = p + np.asarray((-u-v, u-v, u+v, -u+v))*pad
    if np.any(expanded < 0) or np.any(expanded[:, 0] >= gray.shape[1]) or np.any(expanded[:, 1] >= gray.shape[0]):
        raise ValueError("ROW_PAGE_BOUNDARY")
    target = np.asarray(((0, 0), (w+4, 0), (w+4, h+4), (0, h+4)), np.float32)
    crop = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(expanded.astype(np.float32), target),
                               (w+5, h+5), flags=cv2.INTER_NEAREST)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(crop < 128)*255, connectivity=8)
    body, rules, edge = [], [], []
    thin = max(2, round(h*.15))
    for label in range(1, count):
        x, y, cw, ch, _ = map(int, stats[label])
        if x == 0 or y == 0 or x+cw == crop.shape[1] or y+ch == crop.shape[0]:
            if x == 0 and cw == crop.shape[1] and ch <= thin:
                rules.append(("h", x, y, cw, ch))
            elif y == 0 and ch == crop.shape[0] and cw <= thin:
                rules.append(("v", x, y, cw, ch))
            else:
                edge.append(label)
        elif x <= pad or y <= pad or x+cw >= w+pad or y+ch >= h+pad:
            raise ValueError("ROW_INK_AT_BOUNDARY")
        else:
            body.append(label)
    if len(body) < 2:
        raise ValueError("NO_COMPLETE_ROW_COMPONENTS")
    owned = np.isin(labels, body)
    for label in edge:
        fragment = labels == label
        inner = fragment[pad:pad+h+1, pad:pad+w+1]
        x, y, cw, ch, pixels = map(int, stats[label])
        if np.any(inner) and (np.any(inner[pad:-pad, pad:-pad]) or min(cw, ch) > pad or pixels < .8*cw*ch):
            raise ValueError("ROW_SHARED_OR_INCOMPLETE_COMPONENT")
        if np.any((cv2.dilate(np.uint8(fragment), np.ones((5, 5), np.uint8)) > 0) & owned):
            raise ValueError("ROW_TOUCHES_BOUNDARY_CONTEXT")
    for direction, x, y, cw, ch in rules:
        if ((direction == "v" and np.any(owned[:, :x]) and np.any(owned[:, x+cw:]))
                or (direction == "h" and np.any(owned[:y, :]) and np.any(owned[y+ch:, :]))):
            raise ValueError("ROW_CROSSES_REAL_SEPARATOR")
    # Independent line-band geometry, including punctuation. This does not
    # infer a count of characters or assert that the OCR transcript is right.
    heights = [int(stats[i, cv2.CC_STAT_HEIGHT]) for i in body]
    tallest = max(heights)
    main = [i for i in body if stats[i, cv2.CC_STAT_HEIGHT] >= tallest*.5]
    bottoms = [int(stats[i, cv2.CC_STAT_TOP]+stats[i, cv2.CC_STAT_HEIGHT]) for i in main]
    if len(main) < 2 or max(bottoms)-min(bottoms) > max(2, tallest*.25):
        raise ValueError("NOT_ONE_OBSERVED_LINE_BAND")
    mask = owned[pad:pad+h+1, pad:pad+w+1]
    ys, xs = np.nonzero(mask)
    a, b = max(0, int(xs.min())-1), max(0, int(ys.min())-1)
    c, d = min(w, int(xs.max())+2), min(h, int(ys.max())+2)
    quad = tuple(tuple(map(float, p[0]+u*x+v*y)) for x, y in ((a,b), (c,b), (c,d), (a,d)))
    # Orthogonal reading bases map integer source pixel centers exactly.
    coordinates = p[0] + np.column_stack((xs, ys)) @ np.stack((u, v))
    return quad, np.rint(coordinates).astype(int), dict(complete_components=len(body), transcript_proven=False)


def _normal(text):
    return " ".join(text.split())


def recover_native_source_rows(gray, texts, pdf_geometry, *, threshold, records,
                               protected_source_masks=()):
    """Immutable all-or-nothing source transaction; caller runs ownership next."""
    from app.geometry.content_ownership import _candidate_region_mask
    from app.geometry.pdf_arc_evidence import pdf_geometry_binding
    from app.export.ocr_outline_export import native_text_placement
    from app.export.review_text import glyph_footprint
    from app.ocr.ocr_overlap import collapse_overlapping_candidates
    from app.ocr.text_output_contract import accepted_ocr_texts
    import pypdfium2 as pdfium

    eligible = []
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    for index, text in enumerate(texts):
        o = text.pre_cell_observation
        if o is None or o.cell_clip_bbox is None or o.cell_clip_bbox == o.bbox:
            continue
        if text.bbox == o.bbox and text.display_quad is not None:
            continue
        record = dict(index=index, observation_index=o.candidate_index, text=text.text, policy=VERSION,
                      decision="ABSTAIN", reason="NOT_ELIGIBLE")
        records.append(record)
        try:
            if (id(text) not in accepted or text.reviewed or text.display_quad is not None
                    or text.text != o.text or text.source != o.source
                    or text.bbox != o.cell_clip_bbox or text.quad != o.cell_clip_quad):
                raise ValueError("CHANGED_OR_FIXED_SOURCE")
            if _basis(o.quad)[3] <= _basis(text.quad)[3]+1:
                raise ValueError("NO_READING_LENGTH_LOSS")
            quad, core, evidence = measure_row(gray, o)
            eligible.append((index, text, quad, core, evidence, record))
        except (ValueError, TypeError, IndexError, OverflowError, cv2.error) as exc:
            record["reason"] = str(exc)
    if not eligible or pdf_geometry is None:
        for *_, record in eligible:
            record["reason"] = "NO_NATIVE_PDF_SOURCE"
        return tuple(texts)
    if any(mask.shape != gray.shape for mask in protected_source_masks):
        for *_,record in eligible:
            record["reason"] = "PROTECTED_SOURCE_GRID_MISMATCH"
        return tuple(texts)
    document = page = bitmap = tp = None
    started = perf_counter()
    staged = {}
    staged_pixels = np.zeros(gray.shape, bool)
    try:
        if len(eligible) > 16 or gray.size > 32_000_000:
            raise ValueError("NATIVE_ROW_BUDGET")
        binding = pdf_geometry.binding
        path, dpi = Path(binding["document"]), float(binding["requested_dpi"])
        page_index = int(binding["page_number"])-1
        if path.stat().st_size > 128_000_000:
            raise ValueError("NATIVE_PDF_BYTE_BUDGET")
        if pdf_geometry_binding(path, page_index, dpi) != binding:
            raise ValueError("NATIVE_SOURCE_BINDING_CHANGED")
        snapshot = path.read_bytes()
        document = pdfium.PdfDocument(snapshot)
        page = document[page_index]
        if page.get_rotation():
            raise ValueError("UNSUPPORTED_PAGE_ROTATION")
        bitmap = page.render(scale=dpi/72, grayscale=True)
        original = np.array(bitmap.to_pil().convert("L"))
        if not np.array_equal(original, gray):
            raise ValueError("NATIVE_PARENT_CANVAS_MISMATCH")
        pos = bitmap.get_posconv(page)
        tp = page.get_textpage()
        if tp.count_chars() > 20_000:
            raise ValueError("NATIVE_CHARACTER_BUDGET")
        groups = {}
        raw = pdfium.raw
        for i in range(tp.count_chars()):
            handle = raw.FPDFText_GetTextObject(tp, i)
            address = ct.cast(handle, ct.c_void_p).value
            if address:
                groups.setdefault(address, (handle, []))[1].append(i)
        objects = [(pdfium.PdfTextObj(handle, textpage=tp), indexes) for handle, indexes in groups.values()]
        # Isolate actual top-level paint on the same parent canvas. A textpage
        # handle inside a Form cannot inherit an unverified ancestor transform.
        object_count = raw.FPDFPage_CountObjects(page)
        if not 0 < object_count <= 250_000:
            raise ValueError("NATIVE_TOP_LEVEL_OBJECT_BUDGET")
        top_objects, states, top_indexes = [], [], {}
        for i in range(object_count):
            handle = raw.FPDFPage_GetObject(page,i)
            state = raw.FPDF_BOOL()
            if not handle or not raw.FPDFPageObj_GetIsActive(handle,ct.byref(state)):
                raise ValueError("NATIVE_ACTIVE_STATE_UNAVAILABLE")
            top_indexes[ct.cast(handle,ct.c_void_p).value] = i
            top_objects.append(handle)
            states.append(state.value)

        def restore_states():
            failed = False
            for handle,state in zip(top_objects,states,strict=True):
                try:
                    if not raw.FPDFPageObj_SetIsActive(handle,state):
                        failed = True
                except Exception:
                    failed = True
            if failed:
                raise ValueError("NATIVE_GROUP_RESTORE_FAILED")

        for index, text, quad, core, evidence, record in eligible:
            if perf_counter()-started > 45:
                raise ValueError("NATIVE_ROW_TIME_BUDGET")
            o = text.pre_cell_observation
            matches = []
            for obj, chars in objects:
                if _normal(obj.extract()) != _normal(text.text):
                    continue
                corners = [pos.to_bitmap(x,y) for x,y in ((obj.get_bounds()[0],obj.get_bounds()[1]),(obj.get_bounds()[2],obj.get_bounds()[3]))]
                x0,y0=np.min(corners,axis=0)
                x1,y1=np.max(corners,axis=0)
                x,y,w,h=o.bbox
                if x <= x0 <= x1 <= x+w and y <= y0 <= y1 <= y+h:
                    matches.append((obj,chars))
            if len(matches) != 1:
                record["reason"] = "NO_UNIQUE_NATIVE_ROW"
                continue
            obj, chars = matches[0]
            object_index = top_indexes.get(ct.cast(obj.raw,ct.c_void_p).value)
            clip = raw.FPDFPageObj_GetClipPath(obj)
            if object_index is None:
                record["reason"] = "NATIVE_ROW_NOT_TOP_LEVEL"
                continue
            if not clip or raw.FPDFClipPath_CountPaths(clip) != -1:
                record["reason"] = "UNSUPPORTED_NATIVE_ROW_CLIP"
                continue
            matrix = obj.get_matrix().get()
            start = np.asarray(pos.to_bitmap(matrix[4], matrix[5]),float)
            end = np.asarray(pos.to_bitmap(matrix[4]+matrix[0], matrix[5]+matrix[1]),float)
            direction = end-start
            if np.linalg.norm(direction) < 1 or np.dot(direction/np.linalg.norm(direction),_basis(o.quad)[1]) < .99:
                record["reason"] = "NATIVE_READING_BASIS_MISMATCH"
                continue
            rgba = [ct.c_uint() for _ in range(4)]
            state = raw.FPDF_BOOL()
            if (raw.FPDFTextObj_GetTextRenderMode(obj) != 0 or raw.FPDFPageObj_HasTransparency(obj)
                    or not raw.FPDFPageObj_GetFillColor(obj,*[ct.byref(v) for v in rgba])
                    or tuple(v.value for v in rgba) != (0,0,0,255)
                    or not raw.FPDFPageObj_GetIsActive(obj,ct.byref(state)) or not state.value):
                record["reason"] = "UNSUPPORTED_NATIVE_ROW_PAINT"
                continue
            try:
                if not raw.FPDFPageObj_SetIsActive(obj,0):
                    raise ValueError("NATIVE_DEACTIVATION_FAILED")
                without_bitmap = page.render(scale=dpi/72,grayscale=True)
                try:
                    without = np.array(without_bitmap.to_pil().convert("L"))
                finally:
                    without_bitmap.close()
            finally:
                if not raw.FPDFPageObj_SetIsActive(obj,state.value):
                    raise ValueError("NATIVE_RESTORE_FAILED")
            changed = original != without
            ys,xs=np.nonzero(changed)
            x,y,w,h=o.bbox
            if (not len(xs) or np.any(xs<x) or np.any(xs>=x+w) or np.any(ys<y) or np.any(ys>=y+h)
                    or np.any(without[changed] != 255) or np.any(original[changed] >= 255)
                    or np.any(without[core[:,1],core[:,0]] != 255)):
                record["reason"] = "SHARED_OCCLUDED_OR_FOREIGN_ROW_PAINT"
                continue
            if any(np.any(changed & (mask>0)) for mask in protected_source_masks):
                record["reason"] = "PROTECTED_BACKGROUND_SOURCE"
                continue
            try:
                for i,handle in enumerate(top_objects):
                    if not raw.FPDFPageObj_SetIsActive(handle,states[i] if i==object_index else 0):
                        raise ValueError("NATIVE_GROUP_ACTIVATION_FAILED")
                isolated_bitmap = page.render(scale=dpi/72,grayscale=True)
                try:
                    isolated = np.array(isolated_bitmap.to_pil().convert("L"))
                finally:
                    isolated_bitmap.close()
            finally:
                restore_states()
            if (not np.array_equal(isolated<255,changed)
                    or np.any(isolated[changed]!=original[changed])):
                record["reason"] = "NATIVE_ROW_NOT_COMPLETELY_VISIBLE"
                continue
            boxes=[]
            for char_index in chars:
                if chr(raw.FPDFText_GetUnicode(tp,char_index)).isspace():
                    continue
                l,b,r,t=tp.get_charbox(char_index)
                corners=[pos.to_bitmap(a,c) for a,c in ((l,b),(l,t),(r,b),(r,t))]
                left,top=np.min(corners,axis=0)
                right,bottom=np.max(corners,axis=0)
                boxes.append((int(left),int(top),max(1,int(right-left+1)),max(1,int(bottom-top+1))))
            candidate=replace(text,bbox=o.bbox,quad=o.quad,character_boxes=tuple(boxes),display_quad=quad)
            region=_candidate_region_mask(candidate,gray.shape)>0
            claim=region & (gray<=threshold)
            if np.any(claim & ~changed) or np.any(changed & ~region):
                record["reason"] = "NATIVE_CHARACTER_ENVELOPE_HAS_UNPROVEN_SOURCE"
                continue
            old_claim=(_candidate_region_mask(text,gray.shape)>0) & (gray<=threshold)
            if np.any(old_claim & ~changed):
                record["reason"] = "OLD_CARRIER_CONTAINS_UNPROVEN_MEMBER"
                continue
            transform=lambda x,y:(x,gray.shape[0]-y)
            placement=native_text_placement(candidate,transform=transform)
            before=native_text_placement(text,transform=transform)
            if placement is None or before is None or placement.metrics.fallback_reason:
                record["reason"] = "INVALID_NATIVE_ROW_DISPLAY"
                continue
            added=glyph_footprint(placement).subtracted(glyph_footprint(before))
            neighbors = [native_text_placement(other,transform=transform)
                         for j,other in enumerate(texts) if j!=index and id(other) in accepted]
            if any(p is None or p.metrics.fallback_reason for p in neighbors):
                record["reason"] = "UNMEASURABLE_NEIGHBOR_TEXT"
                continue
            if any(added.intersects(glyph_footprint(p)) for p in neighbors):
                record["reason"] = "NEW_NEIGHBOR_TEXT_CONTACT"
                continue
            if np.any(changed & staged_pixels):
                record["reason"] = "SHARED_PROPOSED_SOURCE_MEMBER"
                continue
            staged[index]=candidate
            staged_pixels |= changed
            record.update(evidence,decision="PROPOSED",reason="EXCLUSIVE_NATIVE_ROW_BEFORE_OWNERSHIP",
                          source_runs=pixel_runs(changed),display_quad=quad,source_bbox=o.bbox,
                          native_text_object_index=object_index,source_binding=dict(binding),
                          complete_native_paint_visible=True,
                          source_role="EXCLUSIVE_VISIBLE_NATIVE_TEXT_OBJECT",backup="EXISTING_SOURCE_TEXT_OUTLINE",
                          original_source=dict(bbox=text.bbox,quad=text.quad,character_boxes=text.character_boxes))
        restored=page.render(scale=dpi/72,grayscale=True)
        try:
            if not np.array_equal(np.array(restored.to_pil().convert("L")),original):
                raise ValueError("NATIVE_RESTORED_CANVAS_MISMATCH")
        finally:
            restored.close()
        for handle,state in zip(top_objects,states,strict=True):
            actual = raw.FPDF_BOOL()
            if not raw.FPDFPageObj_GetIsActive(handle,ct.byref(actual)) or actual.value!=state:
                raise ValueError("NATIVE_GROUP_RESTORED_STATE_MISMATCH")
        if path.read_bytes()!=snapshot or pdf_geometry_binding(path,page_index,dpi)!=binding:
            raise ValueError("NATIVE_SOURCE_CHANGED_DURING_PROOF")
        # Both sides of a new proposal pair must also remain disjoint.
        footprints={i:glyph_footprint(native_text_placement(t,transform=lambda x,y:(x,gray.shape[0]-y))) for i,t in staged.items()}
        blocked={i for i,p in footprints.items() for j,q in footprints.items() if i!=j and p.intersects(q)}
        for i in blocked:
            staged.pop(i)
        proposed = tuple(staged.get(i,t) for i,t in enumerate(texts))
        before_ids = {id(t):i for i,t in enumerate(texts)}
        after_ids = {id(t):i for i,t in enumerate(proposed)}
        if ({before_ids[id(t)] for t in collapse_overlapping_candidates(texts)}
                != {after_ids[id(t)] for t in collapse_overlapping_candidates(proposed)}):
            staged.clear()
            for *_,record in eligible:
                if record["decision"]=="PROPOSED":
                    record.update(decision="ABSTAIN",reason="RESTORED_BOUNDS_CHANGE_DEDUP_WINNERS")
        for *_, record in eligible:
            if record["index"] in staged:
                record["decision"]="ADOPTED"
            elif record["decision"]=="PROPOSED":
                record.update(decision="ABSTAIN",reason="JOINT_NEW_TEXT_CONTACT")
        return tuple(staged.get(i,t) for i,t in enumerate(texts))
    except (ValueError,RuntimeError,OSError,KeyError,IndexError,TypeError,OverflowError,cv2.error) as exc:
        for *_,record in eligible:
            record.update(decision="ABSTAIN",reason=str(exc))
        return tuple(texts)
    finally:
        if tp is not None:
            tp.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()
