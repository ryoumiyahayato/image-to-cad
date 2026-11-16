"""Keep residual engineering ink without a transparent page-sized pick target.

Only residuals of a source-proved native recovery are eligible.  We do not infer
noise, delete pixels, quantize alpha, change ownership, or split real logos.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

import numpy as np


def has_native_recovery(bbox, records: Iterable[Mapping[str, object]]) -> bool:
    """Require the actual member-replacement evidence, not spatial proximity."""
    target = tuple(bbox)
    return any(
        tuple(item.get("source_bbox", ())) == target
        and item.get("authority") == "ACCEPTED_NATIVE_MEMBER_SOURCE_ONLY"
        and int(item.get("retired_source_pixels", 0)) > 0
        for record in records
        for item in record.get("engineering_graphic_replacements", ())
    )


def residual_image_tiles(region, *, eligible: bool, max_tiles: int = 128):
    """Return disjoint, fully occupied rectangles of the existing alpha mask.

    An IMAGE may be hit-tested over its whole rectangle, including transparent
    pixels.  A single bounding rectangle for sparse ink can therefore cover an
    otherwise editable TEXT/CIRCLE.  Merge identical horizontal nonzero runs
    across rows; preserve every original alpha value in the resulting images.
    The cap is a representation budget, never an authority to discard ink.
    """
    if not eligible or getattr(region, "visual_kind", "") != "engineering_graphic":
        return (region,)
    x, y, width, height = region.bbox
    mask = region.mask
    if mask.shape != (height, width) or width <= 0 or height <= 0:
        return (region,)
    active = {}
    rectangles = []
    for row_index in range(height + 1):
        if row_index == height:
            runs = set()
        else:
            changes = np.flatnonzero(np.diff(np.r_[False, mask[row_index] > 0, False].astype(np.int8)))
            runs = {(int(a), int(b)) for a, b in zip(changes[::2], changes[1::2], strict=True)}
        for run, top in list(active.items()):
            if run not in runs:
                rectangles.append((run[0], top, run[1], row_index))
                del active[run]
        for run in runs:
            active.setdefault(run, row_index)
        if len(rectangles) + len(active) > max_tiles:
            return (region,)
    if not rectangles:
        return (region,)  # Existing empty-region handling remains authoritative.
    return tuple(
        replace(region, bbox=(x + left, y + top, right-left, bottom-top),
                mask=np.ascontiguousarray(mask[top:bottom, left:right]).copy())
        for left, top, right, bottom in sorted(rectangles, key=lambda r: (r[1], r[0], r[3], r[2]))
    )
