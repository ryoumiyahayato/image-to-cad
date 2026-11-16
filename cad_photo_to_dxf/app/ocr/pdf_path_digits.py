"""Retry a dropped digit only in a complete, isolated PDF stroke label."""

import ctypes as ct
from dataclasses import replace
from math import ceil

import cv2
import numpy as np

from app.geometry.text_residual_retirement import pixel_runs
from app.ocr.ocr_recognition import _as_sequence, _get_rapidocr_engine
from app.ocr.text_output_contract import accepted_ocr_texts


def _digit_bands(gray, candidate):
    if (candidate.reviewed or not candidate.source.startswith("rapidocr-")
            or candidate.display_quad is not None or abs(candidate.rotation_deg) > 10
            or not candidate.text.isascii() or not candidate.text.isdecimal()
            or not 2 <= len(candidate.text) <= 5):
        return ()
    x, y, width, height = candidate.bbox
    if not (8 <= width <= 96 and 12 <= height <= 96
            and 0 <= x <= gray.shape[1] - width and 0 <= y <= gray.shape[0] - height):
        return ()
    ink = gray[y:y+height, x:x+width] < 128
    bounds = np.flatnonzero(np.diff(ink.any(axis=1), prepend=False, append=False))
    if len(bounds) != 2 * (len(candidate.text) + 1):
        return ()
    bands = []
    for top, bottom in zip(bounds[::2], bounds[1::2]):
        columns = np.flatnonzero(ink[top:bottom].any(axis=0))
        left, right = int(columns[0]), int(columns[-1]) + 1
        if right - left < max(8, 1.3 * (bottom - top)):
            return ()
        bands.append((x + left, y + int(top), x + right, y + int(bottom)))
    if min(np.ptp(np.asarray(bands)[:, (0, 2)], axis=0)) > 3:
        return ()
    return bands


def _read_portrait_digits(gray, bands):
    left, top = min(b[0] for b in bands), bands[0][1]
    right, bottom = max(b[2] for b in bands), bands[-1][3]
    crop = cv2.cvtColor(gray[max(0, top-1):bottom+1, max(0, left-1):right+1],
                        cv2.COLOR_GRAY2BGR)
    rotations = [cv2.rotate(crop, code) for code in (
        cv2.ROTATE_90_COUNTERCLOCKWISE, cv2.ROTATE_90_CLOCKWISE,
    )]
    crops = [variant for rotated in rotations for variant in (
        rotated, cv2.copyMakeBorder(rotated, 4, 4, 4, 4, cv2.BORDER_CONSTANT,
                                   value=(255, 255, 255)),
    )]
    try:
        engine = _get_rapidocr_engine()
        labels = _as_sequence(getattr(engine.text_cls(rotations[:1]), "cls_res", None))
        result = engine.recognize_txt(crops)
        readings = _as_sequence(getattr(result, "txts", None))
        scores = _as_sequence(getattr(result, "scores", None))
        if len(labels) != 1 or len(readings) != 4 or len(scores) != 4:
            return None
        direction, confidence = labels[0]
        if str(direction) not in {"0", "180"} or not .95 <= float(confidence) <= 1:
            return None
        selected = 0 if str(direction) == "0" else 2
        reading = str(readings[selected]).strip()
        if (not reading.isascii() or not reading.isdecimal() or len(reading) != len(bands)
                or str(readings[selected + 1]).strip() != reading
                or not all(.90 <= float(s) <= 1 for s in scores[selected:selected + 2])):
            return None
        return reading, selected == 2
    except Exception:
        # A failed optional retry must preserve the original OCR observation.
        return None


def _stroke_boxes(page, raw, size):
    coordinate = [ct.c_int() for _ in range(4)]
    active, mode, stroke = raw.FPDF_BOOL(), ct.c_int(), raw.FPDF_BOOL()
    for index, obj in enumerate(page.get_objects(max_depth=1)):
        if (obj.type != raw.FPDF_PAGEOBJ_PATH
                or not raw.FPDFPageObj_GetIsActive(obj, ct.byref(active)) or not active.value
                or not raw.FPDFPath_GetDrawMode(obj, ct.byref(mode), ct.byref(stroke))
                or mode.value or not stroke.value):
            continue
        x0, y0, x1, y1 = obj.get_bounds()
        left, top, right, bottom = coordinate
        if (raw.FPDF_PageToDevice(page, 0, 0, *size, 0, x0, y0, ct.byref(left), ct.byref(top))
                and raw.FPDF_PageToDevice(page, 0, 0, *size, 0, x1, y1, ct.byref(right), ct.byref(bottom))):
            xs, ys = (left.value, right.value), (top.value, bottom.value)
            yield index, obj, (min(xs), min(ys), max(xs), max(ys))


def _exclusive_label_ink(page, raw, render, size, box, crop, objects, bands):
    ink = crop < 128
    source = render(page, box, size)
    if not np.array_equal(source < 128, ink):
        return None
    exclusive = np.zeros_like(ink)
    matching_paint = (source == crop) & (source < 255)
    for obj, (_, top, _, bottom) in zip(objects, bands):
        if not raw.FPDFPageObj_SetIsActive(obj, 0):
            return None
        try:
            without = render(page, box, size)
        finally:
            if not raw.FPDFPageObj_SetIsActive(obj, 1):
                raise ValueError("PDF stroke visibility could not be restored")
        rows = slice(top - box[1], bottom - box[1])
        expected = ink.copy()
        expected[rows] = False
        if not np.array_equal(without < 128, expected):
            return None
        # Gray fringe is attributable only where the actual crop agrees and
        # no other source paint remains after removing this one object.
        exclusive |= matching_paint & (without == 255)
    return exclusive


def _proven_omission(old, reading, objects, raw):
    missing = [i for i in range(len(reading)) if reading[:i] + reading[i+1:] == old]
    if len(missing) == 1:
        return 0 < missing[0] < len(reading) - 1
    if len(missing) != 2 or missing[1] != missing[0] + 1:
        return False
    # Exact translated copies let us keep both repeated glyphs without
    # asserting which instance the recognizer collapsed.
    from app.geometry.native_pdf_paths import _segments

    first, second = (objects[i] for i in missing)
    widths = ct.c_float(), ct.c_float()
    if (not all(raw.FPDFPageObj_GetStrokeWidth(obj, ct.byref(width))
                for obj, width in zip((first, second), widths))
            or widths[0].value != widths[1].value
            or first.get_matrix().get()[:4] != second.get_matrix().get()[:4]):
        return False
    a, b = _segments(first), _segments(second)
    if [s[::2] for s in a] != [s[::2] for s in b]:
        return False
    coords_a, coords_b = (np.asarray([s[1] for s in segments]) for segments in (a, b))
    return np.array_equal(coords_a - coords_a[0], coords_b - coords_b[0])


def review_pdf_path_digits(gray, texts, binding):
    """Preserve the OCR carrier and retry at most four complete digit labels."""
    candidates = []
    for index, text in enumerate(texts):
        bands = _digit_bands(gray, text)
        if bands:
            left, right = min(b[0] for b in bands), max(b[2] for b in bands)
            top, bottom = bands[0][1], bands[-1][3]
            overlaps = any(
                other_index != index and x < right and left < x + w
                and y < bottom and top < y + h
                for other_index, (x, y, w, h) in enumerate(t.bbox for t in texts)
            )
            if not overlaps:
                candidates.append((index, text, bands))
        if len(candidates) == 4:
            break
    if not candidates:
        return texts, []

    import pypdfium2 as pdf
    from app.geometry.native_pdf_paths import _local_render

    updated, records = list(texts), []
    size = (gray.shape[1], gray.shape[0])
    raw = pdf.raw
    try:
        with pdf.PdfDocument(binding["document"]) as document:
            page = document[int(binding["page_number"]) - 1]
            scale = float(binding["requested_dpi"]) / 72
            if (tuple(ceil(d * scale) for d in page.get_size()) != size
                    or raw.FPDFPage_CountObjects(page) > 8192):
                return texts, []
            strokes = list(_stroke_boxes(page, raw, size))
            for index, text, bands in candidates:
                x, y, width, height = text.bbox
                contained = [(i, obj, bounds) for i, obj, bounds in strokes
                             if x <= bounds[0] and bounds[2] <= x + width
                             and y <= bounds[1] and bounds[3] <= y + height]
                matches = [[(i, obj) for i, obj, bounds in contained
                            if bounds[0] < band[2] and band[0] < bounds[2]
                            and max(abs(bounds[k]-band[k]) for k in (1, 3)) <= 2]
                           for band in bands]
                if any(len(group) != 1 for group in matches):
                    continue
                indices, objects = zip(*(group[0] for group in matches))
                if len(set(indices)) != len(bands):
                    continue
                crop = gray[y:y+height, x:x+width]
                exclusive = _exclusive_label_ink(
                    page, raw, _local_render, size, (x, y, x+width, y+height), crop, objects, bands,
                )
                if exclusive is None:
                    continue
                read = _read_portrait_digits(gray, bands)
                if read is None:
                    continue
                reading, bottom_up = read
                if not _proven_omission(text.text, reading, objects[::-1] if bottom_up else objects, raw):
                    continue

                def vertical_quad(left, top, right, bottom):
                    if bottom_up:
                        return ((left, bottom), (left, top), (right, top), (right, bottom))
                    return ((right, top), (right, bottom), (left, bottom), (left, top))

                ordered = bands[::-1] if bottom_up else bands
                updated[index] = replace(
                    text, text=reading, source="rapidocr-pdf-path-digits",
                    quad=vertical_quad(x, y, x+width, y+height),
                    rotation_deg=-90.0 if bottom_up else 90.0,
                    display_quad=vertical_quad(min(b[0] for b in bands), bands[0][1],
                                               max(b[2] for b in bands), bands[-1][3]),
                    character_boxes=tuple((l, t, r-l, b-t) for l, t, r, b in ordered),
                )
                records.append(dict(before=text.text, text=reading, bbox=list(text.bbox),
                                    objects=list(indices[::-1] if bottom_up else indices),
                                    source_runs=pixel_runs(exclusive, x, y)))
    except (IndexError, KeyError, OSError, ValueError, pdf.PdfiumError):
        return texts, []
    return tuple(updated), records


def mark_pdf_digit_retirement(retired, records, texts, contour_binary, protected_masks):
    """Route only exclusive ink of a surviving editable digit label to backup."""
    if not records:
        return
    emitted = [(t.bbox, t.text) for t in accepted_ocr_texts(texts)
               if t.source == "rapidocr-pdf-path-digits"]
    for record in records:
        if emitted.count((tuple(record["bbox"]), record["text"])) != 1:
            continue
        for y, left, right in record["source_runs"]:
            window = np.s_[y, left:right]
            visible = contour_binary[window] < 128
            for mask in protected_masks:
                visible &= mask[window] == 0
            retired[window][visible] = 255
