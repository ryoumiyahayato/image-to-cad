from __future__ import annotations

import ctypes as ct
from typing import Literal

import numpy as np


PdfPageContent = Literal["raster", "vector", "mixed"]


def _has_ink(get_color, obj) -> bool:
    red, green, blue, alpha = (ct.c_uint() for _ in range(4))
    return bool(
        get_color(obj, red, green, blue, alpha)
        and alpha.value
        and min(red.value, green.value, blue.value) < 255
    )


def _has_vector_ink(obj, raw) -> bool:
    if obj.type == raw.FPDF_PAGEOBJ_PATH:
        fill_mode, stroke_enabled = ct.c_int(), raw.FPDF_BOOL()
        if not raw.FPDFPath_GetDrawMode(obj, fill_mode, stroke_enabled):
            return False
        fill, stroke = bool(fill_mode.value), bool(stroke_enabled.value)
    else:
        mode = raw.FPDFTextObj_GetTextRenderMode(obj)
        fill = mode in (
            raw.FPDF_TEXTRENDERMODE_FILL,
            raw.FPDF_TEXTRENDERMODE_FILL_STROKE,
            raw.FPDF_TEXTRENDERMODE_FILL_CLIP,
            raw.FPDF_TEXTRENDERMODE_FILL_STROKE_CLIP,
        )
        stroke = mode in (
            raw.FPDF_TEXTRENDERMODE_STROKE,
            raw.FPDF_TEXTRENDERMODE_FILL_STROKE,
            raw.FPDF_TEXTRENDERMODE_STROKE_CLIP,
            raw.FPDF_TEXTRENDERMODE_FILL_STROKE_CLIP,
        )
    return (fill and _has_ink(raw.FPDFPageObj_GetFillColor, obj)) or (
        stroke and _has_ink(raw.FPDFPageObj_GetStrokeColor, obj)
    )


def classify_pdf_page_content(page, objects) -> PdfPageContent | None:
    """Use active paint objects from a complete page traversal, without rendering."""
    import pypdfium2 as pdfium

    raw = pdfium.raw
    left, bottom, right, top = page.get_bbox()
    # Union of image bounds, so overlapping images do not double-count coverage.
    grid = (np.arange(32) + 0.5) / 32
    xs, ys = left + grid * (right - left), bottom + grid * (top - bottom)
    raster = np.zeros((grid.size, grid.size), dtype=bool)
    vector_ink = False
    for obj in objects:
        is_image = obj.type == raw.FPDF_PAGEOBJ_IMAGE
        if not is_image and (
            vector_ink or obj.type not in (raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_TEXT)
        ):
            continue
        bounds = obj.get_bounds()
        ancestor = obj
        active = raw.FPDF_BOOL()
        while ancestor is not None:
            if not raw.FPDFPageObj_GetIsActive(ancestor, active):
                return None
            if not active.value:
                break
            ancestor = ancestor.container
            if ancestor is not None:
                bounds = ancestor.get_matrix().on_rect(*bounds)
        if not active.value:
            continue
        x0, y0, x1, y1 = bounds
        if x1 <= left or x0 >= right or y1 <= bottom or y0 >= top:
            continue
        if is_image:
            raster |= ((ys >= y0) & (ys < y1))[:, None] & ((xs >= x0) & (xs < x1))
        else:
            vector_ink = _has_vector_ink(obj, raw)

    raster_fraction = raster.mean()
    if raster_fraction >= 0.8 and not vector_ink:
        return "raster"
    if vector_ink:
        return "vector" if raster_fraction < 0.1 else "mixed"
    return None
