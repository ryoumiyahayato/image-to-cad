"""Source-member retirement, never OCR-box or connected-carrier erasure.

A strict observed row proof supplies strong glyph cores, not permission to hide
an entire weak carrier. Independent, same-parent-canvas PDF PATH isolation and
counterfactual paint establish source members. Unknown paint remains visible.
"""
from __future__ import annotations

import ctypes as ct
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

POLICY = "verified-row-source-members-v1"
BUDGETS = dict(page_pixels=32_000_000, pdf_bytes=128_000_000,
               objects=250_000, local_paths=384, cells=12,
               cell_pixels=65_536, renders=512, seconds=45.0)


def pixel_runs(mask, left=0, top=0):
    """Lossless half-open horizontal source-pixel intervals [y,x0,x1]."""
    runs = []
    for y in np.flatnonzero(np.any(mask, axis=1)):
        columns = np.flatnonzero(mask[y])
        for part in np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1):
            runs.append([int(y + top), int(part[0] + left), int(part[-1] + left + 1)])
    return runs


def path_source_members(only, row_map, protected, threshold):
    """Validate a complete isolated drawing; return ONLY proven local members.

    One-pixel AA fringe is an additional conservative rejection bound, not an
    ownership proof. A weak tail beyond it is explicitly retained/ABSTAIN.
    Foreign strong or weak-only components reject the entire source member.
    """
    support = only <= threshold
    strong = only < 128
    if not np.any(strong):
        return np.zeros_like(support), "NO_PROVEN_STRONG_MEMBER"
    owners = np.unique(row_map[strong])
    if len(owners) != 1 or owners[0] == 0:
        return np.zeros_like(support), "FOREIGN_OR_SHARED_STRONG_SOURCE"
    count, labels = cv2.connectedComponents(support.astype(np.uint8), connectivity=8)
    if any(not np.any(strong & (labels == i)) for i in range(1, count)):
        return np.zeros_like(support), "WEAK_ONLY_SOURCE_COMPONENT"
    if np.any(support & protected):
        return np.zeros_like(support), "PROTECTED_SOURCE_CONTACT"
    fringe = cv2.dilate(strong.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    members = support & fringe
    return members, "PARTIAL_WEAK_TAIL_ABSTAIN" if np.any(support & ~fringe) else "PROVEN_PATH_MEMBERS"


def exclusive_source_members(source, only, without, members, visible, protected, threshold):
    """Intersect actual source members, never synthesize or transfer other owners."""
    return (members & (source <= threshold) & (only == source)
            & (without == 255) & visible & ~protected)


def source_box_inside_cell(box, cell):
    """Bounds only shortlist; integer mapping can collapse a thin glyph stroke.

    Empty-looking mapped bounds are not missing paint: full-canvas isolation
    below still has to prove every actual source pixel, including AA support.
    """
    left, top, right, bottom = cell
    return bool(np.isfinite(box).all()
                and left <= box[0] <= box[2] <= right
                and top <= box[1] <= box[3] <= bottom)


def _closed_opaque_path(obj, raw):
    """Closed black glyph paint only; retain the original clip in every render.

    Clipping is not reconstructed or assumed absent. Both fill-only and
    fill+stroke glyphs are legal; exact raster evidence is still mandatory.
    """
    fill, stroke = ct.c_int(), raw.FPDF_BOOL()
    if (not raw.FPDFPath_GetDrawMode(obj, ct.byref(fill), ct.byref(stroke))
            or not fill.value or raw.FPDFPageObj_HasTransparency(obj)):
        return False
    for getter in ([raw.FPDFPageObj_GetFillColor, raw.FPDFPageObj_GetStrokeColor]
                   if stroke.value else [raw.FPDFPageObj_GetFillColor]):
        rgba = [ct.c_uint() for _ in range(4)]
        if not getter(obj, *[ct.byref(v) for v in rgba]):
            return False
        if tuple(v.value for v in rgba) != (0, 0, 0, 255):
            return False
    count = raw.FPDFPath_CountSegments(obj)
    if not 2 <= count <= 512:
        return False
    previous_closed = True
    for index in range(count):
        segment = raw.FPDFPath_GetPathSegment(obj, index)
        kind = raw.FPDFPathSegment_GetType(segment)
        if kind == raw.FPDF_SEGMENT_UNKNOWN:
            return False
        if kind == raw.FPDF_SEGMENT_MOVETO and not previous_closed:
            return False
        previous_closed = bool(raw.FPDFPathSegment_GetClose(segment))
    return previous_closed


def _render(page, scale):
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        return np.array(bitmap.to_pil().convert("L"))
    finally:
        bitmap.close()


def propose_verified_row_retirement(
    binary, gray, texts, row_proofs, *, visible, protected_source_masks,
    pdf_geometry=None, clean_digital=False, threshold=254,
):
    """Return a recoverable pixel proposal plus ACCEPT/ABSTAIN evidence.

    This does not change text, source files, ownership, contours or DXF layers.
    Every production invocation obtains fresh source evidence, never a cached
    diagnostic path list, string, page, filename or coordinate selector.
    """
    accepted = np.zeros(binary.shape, np.uint8)
    records = []
    if not clean_digital or pdf_geometry is None or not row_proofs:
        return accepted, records
    from app.ocr.text_output_contract import accepted_ocr_texts
    from app.geometry.pdf_arc_evidence import pdf_geometry_binding
    import pypdfium2 as pdfium

    def abstain(reason, **details):
        records.append(dict(decision="ABSTAIN", reason=reason, policy=POLICY, **details))

    if (gray.shape != binary.shape or gray.dtype != np.uint8
            or visible.shape != gray.shape
            or any(m.shape != gray.shape for m in protected_source_masks)):
        raise ValueError("Retirement evidence must share the complete source grid")
    if gray.size > BUDGETS["page_pixels"]:
        abstain("PAGE_PIXEL_BUDGET")
        return accepted, records
    if not np.array_equal(binary < 128, gray <= threshold):
        abstain("PREPARED_SOURCE_NOT_EXACT_THRESHOLD")
        return accepted, records
    proofs = tuple(row_proofs)
    if len(proofs) > BUDGETS["cells"]:
        abstain("CELL_BUDGET")
        return accepted, records
    emitted = accepted_ocr_texts(texts)
    protected = np.zeros(gray.shape, bool)
    for mask in protected_source_masks:
        protected |= mask > 0
    binding = pdf_geometry.binding
    document = None
    page = None
    started = perf_counter()
    renders = 0
    try:
        path = Path(binding["document"])
        page_index = binding["page_number"] - 1
        dpi = float(binding["requested_dpi"])
        if path.stat().st_size > BUDGETS["pdf_bytes"]:
            raise ValueError("PDF_BYTE_BUDGET")
        if (pdf_geometry_binding(path, page_index, dpi) != binding
                or tuple(pdf_geometry.source_size_px) != (gray.shape[1], gray.shape[0])):
            raise ValueError("SOURCE_BINDING_CHANGED")
        snapshot = path.read_bytes()
        snapshot_digest = sha256(snapshot).hexdigest()
        document = pdfium.PdfDocument(snapshot)
        page = document[page_index]
        scale = dpi / 72.0
        original = _render(page, scale)
        renders += 1
        if not np.array_equal(original, gray):
            raise ValueError("PARENT_CANVAS_SOURCE_MISMATCH")
        raw = pdfium.raw
        # These sources are independently emitted later as visible native fill.
        # Do not claim raster-only retirement could remove that representation.
        native_fill_sources = {fill.source.object_index
                               for fill in getattr(pdf_geometry, "native_fills", ())}
        objects, states, bounds = [], [], []
        bitmap = page.render(scale=scale, grayscale=True)
        try:
            pos = bitmap.get_posconv(page)
            for obj in page.get_objects(max_depth=1):
                if len(objects) >= BUDGETS["objects"]:
                    raise ValueError("OBJECT_BUDGET")
                if perf_counter() - started > BUDGETS["seconds"]:
                    raise ValueError("TIME_BUDGET")
                state = raw.FPDF_BOOL()
                if not raw.FPDFPageObj_GetIsActive(obj, ct.byref(state)):
                    raise ValueError("SOURCE_ACTIVE_STATE_UNAVAILABLE")
                objects.append(obj)
                states.append(state.value)
                x0, y0, x1, y1 = obj.get_bounds()
                points = [pos.to_bitmap(x, y) for x, y in
                          ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
                xs, ys = zip(*points)
                bounds.append((min(xs), min(ys), max(xs), max(ys)))
        finally:
            bitmap.close()

        def activate(index, value):
            if not raw.FPDFPageObj_SetIsActive(objects[index], value):
                raise ValueError("SOURCE_ACTIVATION_FAILED")

        def render():
            nonlocal renders
            if (renders >= BUDGETS["renders"]
                    or perf_counter() - started > BUDGETS["seconds"]):
                raise ValueError("RENDER_OR_TIME_BUDGET")
            renders += 1
            return _render(page, scale)

        staged = np.zeros_like(accepted)
        staged_records = []
        try:
            for indexes, proof in proofs:
                left, top, right, bottom = proof.bounds
                if ((right-left)*(bottom-top) > BUDGETS["cell_pixels"]
                        or any(texts[i] not in emitted for i in indexes)
                        or any(sum(t.text == texts[i].text and t.bbox == texts[i].bbox
                                   for t in texts) != 1 for i in indexes)
                        or len(indexes) != len(proof.texts)
                        or any(texts[i].text != row.text or texts[i].bbox != row.bbox
                               or texts[i].source != row.source
                               or texts[i].display_quad != row.quad
                               for i, row in zip(indexes, proof.texts, strict=True))):
                    abstain("FINAL_TEXT_OR_CELL_PROOF_CHANGED", bounds=list(proof.bounds))
                    continue
                row_map = np.zeros(proof.mask.shape, np.uint8)
                for row_index, mask in enumerate(proof.row_masks, 1):
                    if np.any((row_map > 0) & (mask > 0)):
                        raise ValueError("ROW_PROOF_SHARED_STRONG")
                    row_map[mask > 0] = row_index
                # Exact complete strong source, not cropped per-character boxes.
                if np.any((row_map > 0) & (gray[top:bottom,left:right] >= 128)):
                    raise ValueError("ROW_PROOF_NOT_SOURCE_STRONG")
                candidates = [i for i, box in enumerate(bounds)
                              if states[i] and objects[i].type == raw.FPDF_PAGEOBJ_PATH
                              and source_box_inside_cell(box, proof.bounds)]
                if len(candidates) > BUDGETS["local_paths"]:
                    abstain("LOCAL_PATH_BUDGET", bounds=list(proof.bounds))
                    continue
                if not np.any(visible[top:bottom,left:right] & (gray[top:bottom,left:right] <= threshold)):
                    continue
                for i in range(len(objects)):
                    activate(i, 0)
                selected = []
                previous = None
                local_members = np.zeros(row_map.shape, bool)
                unknown_support = np.zeros(row_map.shape, bool)
                member_records = []
                local_protected = protected[top:bottom,left:right]
                for index in candidates:
                    obj = objects[index]
                    if index in native_fill_sources:
                        member_records.append(dict(object_index=index, decision="ABSTAIN", reason="INDEPENDENT_VISIBLE_NATIVE_FILL"))
                        continue
                    if not _closed_opaque_path(obj, raw):
                        member_records.append(dict(object_index=index, decision="ABSTAIN", reason="NOT_CLOSED_OPAQUE_GLYPH_PAINT"))
                        continue
                    if previous is not None:
                        activate(previous, 0)
                    activate(index, states[index])
                    previous = index
                    isolated = render()
                    local = isolated[top:bottom,left:right]
                    if np.count_nonzero(isolated <= threshold) != np.count_nonzero(local <= threshold):
                        member_records.append(dict(object_index=index, decision="ABSTAIN", reason="SOURCE_PAINT_OUTSIDE_PROOF"))
                        continue
                    members, reason = path_source_members(local, row_map, local_protected, threshold)
                    member_records.append(dict(object_index=index, decision="PROPOSE" if np.any(members) else "ABSTAIN", reason=reason,
                                               source_runs=pixel_runs(local <= threshold,left,top),
                                               proposed_runs=pixel_runs(members,left,top),
                                               retained_runs=pixel_runs((local <= threshold) & ~members,left,top)))
                    if np.any(members):
                        selected.append(index)
                        local_members |= members
                        # A selected object's unproved tail is still foreign
                        # even though group isolation disables the whole object.
                        unknown_support |= (local <= threshold) & ~members
                if previous is not None:
                    activate(previous, 0)
                for index in selected:
                    activate(index, states[index])
                only = render()[top:bottom,left:right]
                selected_set = set(selected)
                for i, state in enumerate(states):
                    activate(i, 0 if i in selected_set else state)
                without = render()[top:bottom,left:right]
                source = gray[top:bottom,left:right]
                moved = exclusive_source_members(source, only, without, local_members,
                                                 visible[top:bottom,left:right],
                                                 local_protected | unknown_support | (staged[top:bottom,left:right] > 0), threshold)
                staged[top:bottom,left:right][moved] = 255
                before = visible[top:bottom,left:right] & (source <= threshold)
                staged_records.append(dict(policy=POLICY, decision="ACCEPT" if np.any(moved) else "ABSTAIN",
                    reason="EXCLUSIVE_SOURCE_MEMBER_TRANSFER" if np.any(moved) else "NO_EXCLUSIVE_VISIBLE_MEMBER",
                    bounds=list(proof.bounds), text_indices=list(indexes),
                    text_members=[dict(text=texts[i].text,bbox=list(texts[i].bbox),source=texts[i].source,
                                       display_quad=texts[i].display_quad) for i in indexes],
                    source_binding=dict(binding), source_snapshot_sha256=snapshot_digest,
                    ownership_scope="JOINT_VERIFIED_ROW_SOURCE_GROUP",
                    candidate_counter_scope="original-footprint intersections; joint retired_runs own the complete source fringe",
                    object_members=member_records,
                    visible_before_runs=pixel_runs(before,left,top), retired_runs=pixel_runs(moved,left,top),
                    retained_runs=pixel_runs(before & ~moved,left,top),
                    retired_pixels=int(moved.sum()),
                    retained_pixels=int(np.count_nonzero(before & ~moved)),
                    already_nonvisible_member_pixels=int(np.count_nonzero(local_members & ~visible[top:bottom,left:right])),
                    abstain_visible_member_pixels=int(np.count_nonzero(local_members & visible[top:bottom,left:right] & ~moved)),
                    pixel_contract="PDFIUM_GRAY_SAME_PARENT_CANVAS_INTEGER_PIXEL_CENTERS"))
                for i, state in enumerate(states):
                    activate(i, state)
        finally:
            # Restoration is mandatory even on budgets/errors. No partially
            # evaluated proposal escapes if restoration/source equality fails.
            for i, state in enumerate(states):
                activate(i, state)
            for i, state in enumerate(states):
                actual = raw.FPDF_BOOL()
                if (not raw.FPDFPageObj_GetIsActive(objects[i], ct.byref(actual))
                        or actual.value != state):
                    raise ValueError("RESTORED_ACTIVE_STATE_MISMATCH")
            if not np.array_equal(_render(page, scale), original):
                raise ValueError("RESTORED_SOURCE_MISMATCH")
        if pdf_geometry_binding(path, page_index, dpi) != binding or path.read_bytes() != snapshot:
            raise ValueError("SOURCE_CHANGED_DURING_PROOF")
        recorded = np.zeros_like(staged)
        for record in staged_records:
            for y, x0, x1 in record["retired_runs"]:
                if np.any(recorded[y,x0:x1]):
                    raise ValueError("DUPLICATE_JOINT_SOURCE_OWNER")
                recorded[y,x0:x1] = 255
        if not np.array_equal(recorded, staged):
            raise ValueError("UNRECORDED_RETIRED_SOURCE_MEMBER")
        accepted = staged
        records.extend(staged_records)
    except (ValueError, RuntimeError, OSError, KeyError, IndexError, TypeError, cv2.error) as exc:
        accepted[:] = 0
        abstain(str(exc))
    finally:
        if page is not None:
            page.close()
        if document is not None:
            document.close()
    return accepted, records
