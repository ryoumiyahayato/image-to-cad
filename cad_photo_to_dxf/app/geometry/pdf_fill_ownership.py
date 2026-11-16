"""Conservative native-area presentation eligibility; never source-deletion authority."""
from dataclasses import replace
from collections.abc import Mapping

import numpy as np

POLICY = "pdf-fill-protected-envelope-v1"


def _envelope(points):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 2 or not np.isfinite(p).all():
        raise ValueError("FILL_PROTECTED_GEOMETRY_UNREADABLE")
    lo, hi = p.min(axis=0) - 2, p.max(axis=0) + 2
    return (*lo, *hi)


def _region_box(region):
    box = np.asarray(region.bbox, dtype=float)
    if box.shape != (4,) or not np.isfinite(box).all() or np.any(box[2:] <= 0):
        raise ValueError("FILL_PROTECTED_BBOX_UNREADABLE")
    x, y, w, h = box
    return _envelope(((x, y), (x + w, y + h)))


def _touches(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def qualify_pdf_fill_ownership(evidence, *, texts, protected_masks,
                               protected_regions=(), occupied_boxes=(),
                               stage="pre-retirement"):
    """Veto whole areas that meet any old text/background/source presentation.

    Envelopes deliberately overapproximate concave paint. Bounding boxes provide
    rejection authority only, never pixel deletion/ownership transfer. All OCR
    candidates, including rejected/low-score ones, must be supplied by caller.
    """
    if evidence is None or not getattr(evidence, "native_fills", ()):
        return evidence
    fills = evidence.native_fills
    decisions = []

    def result(accepted, reason=None):
        records = decisions if reason is None else [
            {"object_id": f.object_id, "reason": reason} for f in fills
        ]
        analysis = evidence.fill_analysis if isinstance(evidence.fill_analysis, Mapping) else {}
        previous = analysis.get("ownership_qualification", {})
        if not isinstance(previous, Mapping):
            previous = {}
        return replace(evidence, native_fills=tuple(accepted), fill_analysis={
            **analysis,
            "ownership_qualification": {**previous, stage: {
                "policy": POLICY, "source_deletion_authority": False,
                "accepted": [f.object_id for f in accepted], "abstained": records,
            }},
        })

    try:
        width, height = evidence.source_size_px
        if not (0 < width * height <= 32_000_000) or len(fills) > 32:
            raise ValueError("FILL_OWNERSHIP_RESOURCE_BUDGET")
        texts, regions, masks = tuple(texts), tuple(protected_regions), tuple(protected_masks)
        if len(texts) + len(regions) > 8192 or not masks:
            raise ValueError("FILL_OWNERSHIP_CONTEXT_UNREADABLE")
        for mask in masks:
            if (not isinstance(mask, np.ndarray) or mask.shape != (height, width)
                    or mask.dtype not in (np.dtype("uint8"), np.dtype("bool"))):
                raise ValueError("FILL_OWNERSHIP_MASK_UNREADABLE")
        protected = [_region_box(region) for region in (*texts, *regions)]
        for text in texts:
            for name in ("quad", "display_quad"):
                quad = getattr(text, name, None)
                if quad is not None:
                    if np.asarray(quad).shape != (4, 2):
                        raise ValueError("FILL_PROTECTED_QUAD_UNREADABLE")
                    protected.append(_envelope(quad))
        occupied = []
        for box in occupied_boxes:
            b = np.asarray(box, dtype=float)
            if b.shape != (4,) or not np.isfinite(b).all() or np.any(b[2:] <= b[:2]):
                raise ValueError("FILL_EXISTING_PRESENTATION_UNREADABLE")
            occupied.append(tuple(b))
        # Largest independently proven area first. Later overlapping candidates
        # ABSTAIN rather than adding redundant paint or claiming containment.
        def area(fill):
            p = np.asarray(fill.points)
            return abs(np.sum(p[:, 0] * np.roll(p[:, 1], -1)
                              - p[:, 1] * np.roll(p[:, 0], -1)))
        accepted, accepted_boxes = [], []
        for fill in sorted(fills, key=area, reverse=True):
            if (fill.page_to_pixel != tuple(evidence.page_to_pixel)
                    or fill.source.document != evidence.binding["document"]
                    or fill.source.page_number != evidence.binding["page_number"]):
                raise ValueError("FILL_OWNERSHIP_SOURCE_BINDING_MISMATCH")
            box = _envelope(fill.points)
            p = np.asarray(fill.points)
            if np.any(p < 0) or np.any(p[:, 0] > width) or np.any(p[:, 1] > height):
                reason = "FILL_OWNERSHIP_OUTSIDE_FRAME"
            elif any(_touches(box, b) for b in protected):
                reason = "FILL_PROTECTED_TEXT_OR_BACKGROUND"
            elif any(_touches(box, b) for b in occupied):
                reason = "FILL_EXISTING_PRESENTATION_OVERLAP"
            else:
                x0, y0 = np.maximum(0, np.floor(box[:2])).astype(int)
                x1, y1 = np.minimum((width, height), np.ceil(box[2:])).astype(int)
                if any(np.any(mask[y0:y1, x0:x1]) for mask in masks):
                    reason = "FILL_PROTECTED_SOURCE_MASK"
                elif any(_touches(box, b) for b in accepted_boxes):
                    reason = "FILL_OVERLAPPING_NATIVE_AREA"
                else:
                    accepted.append(fill)
                    accepted_boxes.append(box)
                    continue
            decisions.append({"object_id": fill.object_id, "reason": reason})
        return result(accepted)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        return result((), str(exc))
