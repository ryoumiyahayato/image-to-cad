"""Bind isolated PDF stroke glyphs to an existing editable text observation."""

import cv2
import numpy as np

from app.export.ocr_outline_export import native_text_placement
from app.geometry.native_pdf_paths import _local_render, render_without_active_objects
from app.ocr.pdf_path_callouts import _recognize
from app.ocr.text_output_contract import accepted_ocr_texts


def _complete_glyphs(ink, text):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.uint8(ink < 128), connectivity=8
    )
    if count != len(text.text) + 1:
        return False
    left, top, _, _ = text.bbox
    order = sorted(range(1, count), key=lambda label: stats[label, cv2.CC_STAT_LEFT])
    for label, (x, y, w, h) in zip(order, text.character_boxes):
        if x < left or y < top or x + w > left + ink.shape[1] or y + h > top + ink.shape[0]:
            return False
        region = labels[y-top:y-top+h, x-left:x-left+w]
        if (np.count_nonzero(region == label) != stats[label, cv2.CC_STAT_AREA]
                or np.any((region != 0) & (region != label))):
            return False
    return True


def _independent_strokes(fact):
    style = fact["style"]
    return (
        style["stroke"] and not style["fill"]
        and tuple(style["colors"]["stroke"]) == (0, 0, 0, 255)
        and all(
            edge["kind"] == "L" and not edge.get("shared_with")
            and not edge.get("aliases") and edge.get("existing_line") is None
            for path in fact["subpaths"] for edge in path["edges"]
        )
    )


def bind_isolated_path_text(page, size, active_objects, facts, path_bounds, texts):
    """Commit whole path objects only after positive and negative render checks."""
    accepted = {id(text) for text in accepted_ocr_texts(texts)}
    records = []
    retries = 0
    for index, text in enumerate(texts):
        observation = text.pre_cell_observation
        if (
            id(text) not in accepted or text.reviewed or not text.replacement_safe
            or not text.source.startswith("rapidocr-") or text.confidence < .90
            or text.rotation_deg != 0 or not text.text.isascii() or not text.text.isalnum()
            or not 2 <= len(text.text) <= 8 or len(text.character_boxes) != len(text.text)
            or (observation is not None and observation.cell_clip_bbox not in (None, observation.bbox))
        ):
            continue
        x, y, width, height = text.bbox
        right, bottom = x + width, y + height
        if not (0 <= x < right <= size[0] and 0 <= y < bottom <= size[1]
                and width * height <= 16_384):
            continue
        if any(
            j != index and id(other) in accepted
            and x < ox + ow and ox < right and y < oy + oh and oy < bottom
            for j, other in enumerate(texts) for ox, oy, ow, oh in (other.bbox,)
        ):
            continue
        candidates = []
        for fact in facts:
            left_coord, t, r, b = path_bounds[fact["object_index"]]
            if x <= left_coord and y <= t and r <= right and b <= bottom:
                candidates.append(fact)
        if not 1 <= len(candidates) <= 32 or any(not _independent_strokes(f) for f in candidates):
            continue
        placement = native_text_placement(text, transform=lambda px, py: (px, size[1]-py))
        if placement is None or placement.metrics.fallback_reason:
            continue
        indices = {f["object_index"] for f in candidates}
        box = (x, y, right, bottom)
        isolated = render_without_active_objects(
            page, box, size, (obj for i, obj in active_objects.items() if i not in indices)
        )
        if not _complete_glyphs(isolated, text) or not np.array_equal(isolated, _local_render(page, box, size)):
            continue
        foreign = render_without_active_objects(page, box, size, (active_objects[i] for i in sorted(indices)))
        if np.any(foreign < 255):
            continue
        if retries == 16:
            break
        retries += 1
        if _recognize(isolated) != text.text:
            continue
        for fact in candidates:
            fact["editable_text_owner"] = index
        records.append({
            "text_index": index,
            "text": text.text,
            "bbox": list(box),
            "pdf_objects": sorted(indices),
            "foreground_pixels": int(np.count_nonzero(isolated < 128)),
            "proof": "COMPLETE_ISOLATED_STROKE_GLYPHS_AND_AGREEING_OCR",
        })
    return records
