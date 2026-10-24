"""Page-local PDFium suggestions. Extracted Unicode is NEVER a correction.

Only top-level, horizontal, opaque fill text with unambiguous paint order can
offer a source layout. Two local renders prove visible ink and retained source
representations. Neither this evidence nor ToUnicode authorizes text changes.
"""

from __future__ import annotations

import base64
from collections import defaultdict
import ctypes as ct
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

SUGGESTION_VERSION = "native-pdf-review-suggestions-v1"
SUGGESTION_KEY = "pdf_native_suggestions_v1"
MAX_OBJECTS = 12000
MAX_CHARACTERS = 20000
MAX_PROOFS = 48
MAX_SECONDS = 8.0


def _address(handle):
    return ct.cast(handle, ct.c_void_p).value


def _render_crop(page, box, scale, shape):
    x0, y0, x1, y1 = box
    h, w = shape
    crop = tuple(max(0, v - 1e-5) / scale for v in (x0, h - y1, w - x1, y0))
    bitmap = page.render(scale=scale, grayscale=True, crop=crop)
    try:
        return np.array(bitmap.to_pil().convert("L"))
    finally:
        bitmap.close()


def _render_page(page, scale):
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        return np.array(bitmap.to_pil().convert("L"))
    finally:
        bitmap.close()


def _group_paint_evidence(page, objects, states, rows, gray, scale):
    """Actual joint paint, with exact parent-canvas restoration after each group."""
    import pypdfium2 as pdfium

    raw = pdfium.raw
    complete = []
    for row in rows:
        ids = {f["object"] for f in row["fragments"]}
        if any(ids < {f["object"] for f in other["fragments"]} for other in rows):
            continue
        if any(ids == {f["object"] for f in r["fragments"]} for r in complete):
            continue
        complete.append(row)
    families = defaultdict(list)
    for row in complete:
        f = row["fragments"][0]
        obj = objects[f["object"]]
        key = (
            tuple(round(v, 5) for v in f["matrix"][:4]),
            round(obj.get_font_size(), 3),
            obj.get_font().get_base_name(),
        )
        families[key].append(row)
    groups = []
    for family in families.values():
        chains = []
        for row in sorted(family, key=lambda r: (r["bounds"][1], r["bounds"][0])):
            a, b, c, d = row["bounds"]
            matches = [
                chain
                for chain in chains
                if abs(chain[-1]["bounds"][0] - a)
                <= max(d - b, chain[-1]["bounds"][3] - chain[-1]["bounds"][1])
                and b - chain[-1]["bounds"][3]
                <= 0.25 * max(d - b, chain[-1]["bounds"][3] - chain[-1]["bounds"][1])
                and 0
                <= b - chain[-1]["bounds"][1]
                <= 1.7 * max(d - b, chain[-1]["bounds"][3] - chain[-1]["bounds"][1])
            ]
            if len(matches) == 1:
                matches[0].append(row)
            else:
                chains.append([row])
        groups.extend(chain for chain in chains if 2 <= len(chain) <= 12)
    output = []
    for group in sorted(groups, key=lambda g: (-len(g), g[0]["bounds"][1]))[:2]:
        selected = {f["object"] for r in group for f in r["fragments"]}
        if (
            len(selected) > 1024
            or len(selected) != sum(len(r["fragments"]) for r in group)
            or any(not states[i] for i in selected)
        ):
            continue
        bounds = [
            min(r["bounds"][0] for r in group),
            min(r["bounds"][1] for r in group),
            max(r["bounds"][2] for r in group),
            max(r["bounds"][3] for r in group),
        ]
        box = [
            max(0, bounds[0] - 2),
            max(0, bounds[1] - 2),
            min(gray.shape[1], bounds[2] + 3),
            min(gray.shape[0], bounds[3] + 3),
        ]
        if (box[2] - box[0]) * (box[3] - box[1]) > 600000:
            continue
        all_page = _render_page(page, scale)
        if not np.array_equal(all_page, gray):
            continue
        try:
            for i, obj in enumerate(objects):
                if not raw.FPDFPageObj_SetIsActive(
                    obj, 0 if i in selected else states[i]
                ):
                    raise ValueError("Cannot exclude native text group")
            without = _render_page(page, scale)
            for i, obj in enumerate(objects):
                if not raw.FPDFPageObj_SetIsActive(
                    obj, states[i] if i in selected else 0
                ):
                    raise ValueError("Cannot isolate native text group")
            only = _render_page(page, scale)
        finally:
            restore_errors = []
            for obj, state in zip(objects, states):
                try:
                    if not raw.FPDFPageObj_SetIsActive(obj, state):
                        restore_errors.append("Native text group restoration failed")
                except Exception as exc:
                    restore_errors.append(str(exc))
            try:
                if not np.array_equal(_render_page(page, scale), all_page):
                    restore_errors.append("Native text group restored paint differs")
            except Exception as exc:
                restore_errors.append(str(exc))
            if restore_errors:
                raise ValueError("; ".join(restore_errors))
        if without.shape != gray.shape or only.shape != gray.shape:
            continue
        a, b, c, d = box
        encoded = {}
        for key, image in (("all", all_page), ("without", without), ("only", only)):
            ok, png = cv2.imencode(".png", image[b:d, a:c])
            if not ok:
                raise ValueError("Cannot encode native group paint")
            encoded[key + "_png"] = base64.b64encode(png).decode("ascii")
        output.append(
            dict(
                version="native-text-group-paint-v1",
                box=box,
                rows=[
                    dict(text=r["text"], bounds=r["bounds"], fragments=r["fragments"])
                    for r in group
                ],
                object_indices=sorted(selected),
                restore_equal=True,
                canvas_size_px=[gray.shape[1], gray.shape[0]],
                pixel_contract="PDFIUM_GRAY_SAME_PARENT_CANVAS_INTEGER_PIXEL_CENTERS",
                **encoded,
            )
        )
    return output


def extract_pdf_text_suggestions(
    path, page_index, page, bitmap, gray, scale, dpi, *, include_display_rows=False
):
    """Reuse the current page/render; bounded optional evidence, no file writes."""
    import pypdfium2 as pdfium

    started = perf_counter()
    raw = pdfium.raw
    result = dict(
        version=SUGGESTION_VERSION,
        source_path=str(Path(path).resolve()),
        physical_page=page_index + 1,
        dpi=float(dpi),
        source_size_px=[gray.shape[1], gray.shape[0]],
        rows=[],
        rejected=[],
        unicode_status="UNVERIFIED_PDF_MAPPING",
        object_count=0,
        object_count_scope="VISITED_TOP_LEVEL_OBJECTS",
        object_traversal_complete=False,
    )
    tp = page.get_textpage()
    objects, states = [], []
    try:
        count = tp.count_chars()
        result["character_count"] = count
        if not count:
            result["status"] = "NO_ELIGIBLE_SUGGESTION"
            return result
        if count > MAX_CHARACTERS:
            result["status"] = "CHARACTER_BUDGET_EXCEEDED"
            return result
        # Only top-level objects are admitted. Ancestor Form clips/transforms
        # are deliberately outside this first layout contract.
        for obj in page.get_objects(max_depth=1, textpage=tp):
            objects.append(obj)
            if len(objects) > MAX_OBJECTS or perf_counter() - started > MAX_SECONDS:
                result["status"] = "OBJECT_BUDGET_EXCEEDED"
                return result
        result["object_count"] = len(objects)
        result["object_traversal_complete"] = True
        address_to_index = {_address(o.raw): i for i, o in enumerate(objects)}
        characters = defaultdict(list)
        generated = []
        for i in range(count):
            code = raw.FPDFText_GetUnicode(tp, i)
            item = dict(
                index=i, unicode=code, generated=bool(raw.FPDFText_IsGenerated(tp, i))
            )
            owner = address_to_index.get(_address(raw.FPDFText_GetTextObject(tp, i)))
            if owner is None:
                generated.append(item)
            else:
                characters[owner].append(item)
        pos = bitmap.get_posconv(page)
        groups = defaultdict(list)
        for index, obj in enumerate(objects):
            if obj.type != raw.FPDF_PAGEOBJ_TEXT:
                continue
            matrix = obj.get_matrix().get()
            mode = raw.FPDFTextObj_GetTextRenderMode(obj)
            rgba = [ct.c_uint() for _ in range(4)]
            color_ok = raw.FPDFPageObj_GetFillColor(obj, *[ct.byref(v) for v in rgba])
            clip = raw.FPDFPageObj_GetClipPath(obj)
            clip_count = raw.FPDFClipPath_CountPaths(clip) if clip else None
            text = obj.extract()
            if (
                mode != 0
                or not color_ok
                or tuple(v.value for v in rgba) != (0, 0, 0, 255)
            ):
                result["rejected"].append(
                    dict(object=index, reason="HIDDEN_OR_UNSUPPORTED_PAINT")
                )
                continue
            if (
                abs(matrix[1]) + abs(matrix[2]) > 1e-6
                or matrix[0] <= 0
                or matrix[3] <= 0
                or page.get_rotation()
            ):
                result["rejected"].append(
                    dict(object=index, reason="ROTATED_OR_TRANSFORMED_TEXT")
                )
                continue
            b = obj.get_bounds()
            corners = [pos.to_bitmap(x, y) for x, y in ((b[0], b[1]), (b[2], b[3]))]
            bounds = [
                min(p[0] for p in corners),
                min(p[1] for p in corners),
                max(p[0] for p in corners),
                max(p[1] for p in corners),
            ]
            # A valid object returns a clip container. PDFium CountPaths=-1
            # with this non-null container means no referenced clip state.
            # This is only ONE condition: local source/occlusion proof follows.
            no_clip = bool(clip) and clip_count == -1
            key = (
                tuple(round(v, 5) for v in matrix[:4]),
                round(matrix[5], 3),
                round(obj.get_font_size(), 4),
                obj.get_font().get_base_name(),
            )
            groups[key].append(
                dict(
                    object=index,
                    text=text,
                    bounds=bounds,
                    matrix=list(matrix),
                    no_clip=no_clip,
                    clip_path_count=clip_count,
                    chars=characters[index],
                )
            )
        rows = []
        display_basis = {}
        for key, items in groups.items():
            items.sort(key=lambda item: item["matrix"][4])
            runs = [[]]
            for item in items:
                # Split disconnected columns; never infer words or punctuation.
                if (
                    runs[-1]
                    and item["bounds"][0] - runs[-1][-1]["bounds"][2]
                    > key[2] * scale * 3
                ):
                    runs.append([])
                runs[-1].append(item)
            for run in runs:
                text = "".join(item["text"] for item in run).strip()
                if not text:
                    continue
                x0, y0 = np.min([i["bounds"][:2] for i in run], axis=0)
                x1, y1 = np.max([i["bounds"][2:] for i in run], axis=0)
                indices = [i["object"] for i in run]
                mapped = [c for i in run for c in i["chars"]]
                reason = None
                if indices != sorted(indices) or len(indices) != len(set(indices)):
                    reason = "CHARACTER_PAINT_ORDER_AMBIGUOUS"
                elif any(
                    min(a["bounds"][2], b["bounds"][2])
                    - max(a["bounds"][0], b["bounds"][0])
                    > max(1, key[2] * scale * 0.15)
                    for a, b in zip(run, run[1:])
                ):
                    reason = "OVERLAPPING_NATIVE_FRAGMENTS"
                elif (
                    any(ord(c) < 32 or c in "\ufffd\x00" for c in text)
                    or not mapped
                    or any(c["unicode"] in (0, 0xFFFD) for c in mapped)
                ):
                    reason = "INCOMPLETE_UNICODE_OR_MULTILINE"
                elif len(text.encode("utf-8")) > 250:
                    reason = "NATIVE_LINE_PROVENANCE_BYTE_LIMIT"
                elif not all(i["no_clip"] for i in run):
                    reason = "CLIPPING_NOT_COMPLETE"
                elif (
                    x0 < 0
                    or y0 < 0
                    or x1 > gray.shape[1]
                    or y1 > gray.shape[0]
                    or x1 <= x0
                    or y1 <= y0
                ):
                    reason = "NATIVE_REGION_OUTSIDE_PAGE"
                row = dict(
                    text=text,
                    bounds=[int(x0), int(y0), int(x1), int(y1)],
                    quad=[
                        [int(x0), int(y0)],
                        [int(x1), int(y0)],
                        [int(x1), int(y1)],
                        [int(x0), int(y1)],
                    ],
                    rotation_deg=0.0,
                    fragments=run,
                    generated_characters=[
                        c
                        for c in generated
                        if mapped
                        and mapped[0]["index"] <= c["index"] <= mapped[-1]["index"]
                    ],
                    whitespace_source="PDFIUM_EXTRACT_NO_LANGUAGE_RECONSTRUCTION",
                    unicode_status="UNVERIFIED_PDF_MAPPING",
                    status="NATIVE_VISIBILITY_PARTIAL",
                    layout_eligible=False,
                    reason=reason or "VISIBILITY_NOT_CHECKED",
                )
                rows.append(row)
                display_basis[id(row)] = key
        # Longest rows first, then reading order. Budget has no file/coordinate
        # allowlist. Unchecked rows remain explicitly partial, not confirmable.
        candidates = sorted(
            (r for r in rows if r["reason"] == "VISIBILITY_NOT_CHECKED"),
            key=lambda r: (-len(r["text"]), r["bounds"][1], r["bounds"][0]),
        )
        display_rows = []
        display_parents = {}
        for row in rows if include_display_rows else ():
            key = display_basis[id(row)]
            peers = [
                r
                for r in rows
                if r is not row
                and r["reason"] == "VISIBILITY_NOT_CHECKED"
                and display_basis[id(r)][:2] == key[:2]
                and display_basis[id(r)][3] == key[3]
                and abs(display_basis[id(r)][2] - key[2]) <= 0.001
                and 0
                <= row["bounds"][0] - r["bounds"][2]
                <= max(1, row["bounds"][3] - row["bounds"][1])
            ]
            if (
                len(peers) == 1
                and len(row["fragments"]) + len(peers[0]["fragments"]) <= 512
            ):
                peer = peers[0]
                fragments = sorted(
                    peer["fragments"] + row["fragments"], key=lambda f: f["matrix"][4]
                )
                bounds = [
                    min(peer["bounds"][0], row["bounds"][0]),
                    min(peer["bounds"][1], row["bounds"][1]),
                    max(peer["bounds"][2], row["bounds"][2]),
                    max(peer["bounds"][3], row["bounds"][3]),
                ]
                derived = dict(
                    row,
                    text="".join(f["text"] for f in fragments).strip(),
                    fragments=fragments,
                    bounds=bounds,
                    quad=[
                        [bounds[0], bounds[1]],
                        [bounds[2], bounds[1]],
                        [bounds[2], bounds[3]],
                        [bounds[0], bounds[3]],
                    ],
                )
                display_parents[id(row)] = derived
        for obj in objects:
            state = raw.FPDF_BOOL()
            if not raw.FPDFPageObj_GetIsActive(obj, ct.byref(state)):
                result["status"] = "PAINT_STATE_UNAVAILABLE"
                return result
            states.append(state.value)
        for row in candidates[:MAX_PROOFS]:
            if perf_counter() - started > MAX_SECONDS:
                row["reason"] = "VISIBILITY_TIME_BUDGET"
                break
            x0, y0, x1, y1 = row["bounds"]
            box = [
                max(0, x0 - 4),
                max(0, y0 - 4),
                min(gray.shape[1], x1 + 5),
                min(gray.shape[0], y1 + 5),
            ]
            if (box[2] - box[0]) * (box[3] - box[1]) > 150000:
                row["reason"] = "LOCAL_RENDER_BUDGET"
                continue
            original_box = box
            display_row = display_parents.get(id(row), row)
            if display_row is not row:
                a, b, c, d = display_row["bounds"]
                box = [
                    max(0, a - 4),
                    max(0, b - 4),
                    min(gray.shape[1], c + 5),
                    min(gray.shape[0], d + 5),
                ]
                if (box[2] - box[0]) * (box[3] - box[1]) > 150000:
                    continue
            selected = {f["object"] for f in display_row["fragments"]}
            for i, obj in enumerate(objects):
                if not raw.FPDFPageObj_SetIsActive(
                    obj, states[i] if i in selected else 0
                ):
                    raise ValueError("Cannot isolate PDF paint")
            isolated = _render_crop(page, box, scale, gray.shape)
            for i, obj in enumerate(objects):
                if not raw.FPDFPageObj_SetIsActive(
                    obj, 0 if i in selected else states[i]
                ):
                    raise ValueError("Cannot exclude PDF paint")
            without = _render_crop(page, box, scale, gray.shape)
            normal = gray[box[1] : box[3], box[0] : box[2]]
            if isolated.shape != normal.shape or without.shape != normal.shape:
                row["reason"] = "LOCAL_RENDER_COORDINATE_MISMATCH"
                continue
            display_ink = isolated < 245
            display_normal = normal
            display_without = without
            display_isolated = isolated
            display_box = box
            if display_row is not row:
                a, b, c, d = original_box
                sl = np.s_[b - box[1] : d - box[1], a - box[0] : c - box[0]]
                combined_original = (isolated[sl], without[sl])
                original_selected = {f["object"] for f in row["fragments"]}
                for i, obj in enumerate(objects):
                    if not raw.FPDFPageObj_SetIsActive(
                        obj, states[i] if i in original_selected else 0
                    ):
                        raise ValueError("Cannot isolate original PDF row")
                original_isolated = _render_crop(page, original_box, scale, gray.shape)
                for i, obj in enumerate(objects):
                    if not raw.FPDFPageObj_SetIsActive(
                        obj, 0 if i in original_selected else states[i]
                    ):
                        raise ValueError("Cannot exclude original PDF row")
                original_without = _render_crop(page, original_box, scale, gray.shape)
                # The derived view may share this bounded proof iteration only
                # when both original isolation renders are exactly unchanged.
                if not np.array_equal(
                    combined_original[0], original_isolated
                ) or not np.array_equal(combined_original[1], original_without):
                    display_ink = np.zeros_like(display_ink)
                isolated, without, normal = (
                    original_isolated,
                    original_without,
                    normal[sl],
                )
                box = original_box
            ink = isolated < 245
            if not np.any(ink) or np.any(
                np.abs(normal.astype(int) - isolated)[ink] > 0
            ):
                row["reason"] = "OCCLUDED_OR_NO_VISIBLE_INK"
                continue
            if np.any((without < 250) & ink):
                row["reason"] = "DUPLICATE_OR_OTHER_PAINT_UNDER_GLYPHS"
                continue
            # Preserve each existing source contour, including glyph backups.
            # A later guard may recognize ONLY a whole CAD footprint contained
            # in this source-only ink support. It never deletes those objects.
            kernel = np.ones((5, 5), np.uint8)
            support = cv2.dilate(ink.astype(np.uint8), kernel)
            support[cv2.dilate((without < 250).astype(np.uint8), kernel) != 0] = 0
            ok, png = cv2.imencode(".png", support * 255)
            if not ok:
                raise ValueError("Cannot encode local source support")
            row.update(
                status="NATIVE_TEXT_SUGGESTION",
                layout_eligible=True,
                reason="VISIBLE_INK_UNIQUE_UNCLIPPED_UNICODE_UNVERIFIED",
                proof=dict(
                    clip_state="TOP_LEVEL_NO_REFERENCED_CLIP",
                    visible_ink_pixels=int(ink.sum()),
                    source_difference_on_ink=0,
                    other_ink_under_glyphs=0,
                    support_box=box,
                    source_only_support_png=base64.b64encode(png).decode("ascii"),
                ),
            )
            # This separate view never enters review binding or source deletion.
            if (
                include_display_rows
                and np.any(display_ink)
                and not np.any(
                    np.abs(display_normal.astype(int) - display_isolated)[display_ink]
                )
                and not np.any((display_without < 250) & display_ink)
            ):
                support = cv2.dilate(display_ink.astype(np.uint8), kernel)
                support[
                    cv2.dilate((display_without < 250).astype(np.uint8), kernel) != 0
                ] = 0
                ok, png = cv2.imencode(".png", support * 255)
                if ok:
                    iy, ix = np.where(display_ink)
                    display_rows.append(
                        dict(
                            display_row,
                            status="NATIVE_TEXT_SUGGESTION",
                            layout_eligible=True,
                            proof=dict(
                                row["proof"],
                                support_box=display_box,
                                source_only_support_png=base64.b64encode(png).decode(
                                    "ascii"
                                ),
                                complete_ink_center_bounds=[
                                    float(display_box[0] + ix.min() + 0.5),
                                    float(display_box[1] + iy.min() + 0.5),
                                    float(display_box[0] + ix.max() + 0.5),
                                    float(display_box[1] + iy.max() + 0.5),
                                ],
                            ),
                        )
                    )
        if include_display_rows:
            result["display_rows"] = display_rows
            for obj, state in zip(objects, states):
                if not raw.FPDFPageObj_SetIsActive(obj, state):
                    raise ValueError("Cannot restore paint before group proof")
            result["text_groups"] = _group_paint_evidence(
                page, objects, states, display_rows, gray, scale
            )
        result["rows"] = rows
        result["status"] = (
            "SUGGESTIONS_AVAILABLE"
            if any(r["layout_eligible"] for r in rows)
            else "NO_ELIGIBLE_SUGGESTION"
        )
        return result
    finally:
        restore_errors = []
        if states:
            for obj, state in zip(objects, states):
                try:
                    if not pdfium.raw.FPDFPageObj_SetIsActive(obj, state):
                        restore_errors.append("PDF paint restoration failed")
                except Exception as exc:
                    restore_errors.append(str(exc))
        tp.close()
        result["seconds"] = perf_counter() - started
        if restore_errors:
            raise ValueError("; ".join(restore_errors))
