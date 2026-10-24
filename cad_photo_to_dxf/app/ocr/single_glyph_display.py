"""Bounded display-only fitting of an isolated glyph in a source-ruled cell."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping, Sequence

import cv2
import numpy as np

from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.librecad_lff import librecad_font_available, librecad_text_metrics
from app.ocr.text_output_contract import accepted_ocr_texts


def refine_single_glyph_displays(
    gray: np.ndarray,
    texts: Sequence[TextCandidate],
    cells: Mapping[tuple[str, tuple[int, int, int, int]], tuple[int, int, int, int]],
    *,
    protected_source_masks: Sequence[np.ndarray] = (),
) -> tuple[tuple[TextCandidate, ...], tuple[dict, ...]]:
    """Change only display quads, after all source/contour decisions are final.

    A cell is an existing four-rule observation, not source-deletion authority.
    Three locally derived gray cuts must find one complete, separated glyph.
    Nothing is cut out of a connected source carrier. Character boxes, bbox,
    replacement eligibility and source masks remain exactly as received.
    """
    if not cells or not librecad_font_available():
        return tuple(texts), ()
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Single glyph display requires the prepared source gray")
    if any(mask.shape != gray.shape for mask in protected_source_masks):
        raise ValueError("Glyph protection must share source coordinates")
    remaining_pixels = 65_536
    output, proofs = list(texts), []
    page_h, page_w = gray.shape
    for index, text in enumerate(texts):
        # Numeric/dimension direction, manual placement and multi-letter fits
        # retain their existing contracts. No particular letter is selected.
        if (
            len(text.text) != 1
            or not text.text.isascii()
            or not text.text.isalpha()
            or text.kind != "text_candidate"
            or text.reviewed
            or not text.source.startswith("rapidocr")
            or abs(text.rotation_deg) > 0.5
            or len(text.character_boxes) != 1
            or not accepted_ocr_texts((text,))
        ):
            continue
        cell = cells.get((text.text, text.bbox))
        if cell is None:
            continue
        x, y, w, h = text.bbox
        if not (
            0 < w
            and 0 < h
            and cell[0] <= x < x + w <= cell[2]
            and cell[1] <= y < y + h <= cell[3]
        ):
            continue
        original_quad = (
            (float(x), float(y)),
            (float(x + w), float(y)),
            (float(x + w), float(y + h)),
            (float(x), float(y + h)),
        )
        if text.quad is not None and text.quad != original_quad:
            continue  # preserve prior fitted/rotated placements; idempotent
        margin = max(6, h // 2)
        left, top, right, bottom = (
            x - margin,
            y - margin,
            x + w + margin,
            y + h + margin,
        )
        area = (right - left) * (bottom - top)
        if (
            min(left, top) < 0
            or right > page_w
            or bottom > page_h
            or area > 4096
            or area > remaining_pixels
        ):
            continue
        remaining_pixels -= area
        crop = gray[top:bottom, left:right]
        threshold, base_mask = cv2.threshold(
            crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
        )
        if not np.any(base_mask) or not np.any(base_mask == 0):
            continue
        dark = float(np.median(crop[base_mask > 0]))
        paper = float(np.median(crop[base_mask == 0]))
        if paper - dark < 40:
            continue
        levels = (
            int(round((dark + threshold) / 2)),
            int(threshold),
            int(round((threshold + paper) / 2)),
        )
        if not levels[0] < levels[1] < levels[2]:
            continue
        box = (x - left, y - top, x + w - left, y + h - top)
        components = []
        for level in levels:
            count, labels, stats, _ = cv2.connectedComponentsWithStats(
                np.uint8(crop <= level) * 255, connectivity=8
            )
            candidates = []
            for label in range(1, count):
                a, b, cw, ch, pixels = map(int, stats[label])
                # A full component, with paper margin inside the OCR box.
                # Boundary-crossing pieces and small noise cannot set a fit.
                if (
                    box[0] < a
                    and box[1] < b
                    and a + cw < box[2]
                    and b + ch < box[3]
                    and pixels >= 8
                    and cw >= max(3, w * 0.30)
                    and ch >= max(5, h * 0.50)
                ):
                    candidates.append((label, (a, b, a + cw, b + ch)))
            if len(candidates) != 1:
                break
            label, bounds = candidates[0]
            glyph = labels == label
            others_valid = True
            for other in np.unique(labels[box[1] : box[3], box[0] : box[2]]):
                if other in (0, label):
                    continue
                oa, ob, ow, oh, _ = map(int, stats[other])
                # A separate full-width/height thin source rule may intersect
                # the padded detection box. It is not part of this glyph. Any
                # other enclosed fragment (including a dot) is undetermined.
                horizontal = (
                    oa == 0
                    and ow == crop.shape[1]
                    and oh <= max(2, h // 5)
                    and (ob + oh <= bounds[1] - 2 or ob >= bounds[3] + 2)
                )
                vertical = (
                    ob == 0
                    and oh == crop.shape[0]
                    and ow <= max(2, w // 5)
                    and (oa + ow <= bounds[0] - 2 or oa >= bounds[2] + 2)
                )
                if not (horizontal or vertical):
                    others_valid = False
                    break
            if not others_valid:
                break
            # Two source-paper pixels must separate every other component.
            # Other ink is left owned/represented exactly as before, not noise.
            halo = cv2.dilate(np.uint8(glyph), np.ones((5, 5), np.uint8)) > 0
            if np.any(halo & (labels != 0) & ~glyph):
                break
            if components and not np.all(glyph[components[-1][0]]):
                break
            components.append((glyph, bounds, int(np.count_nonzero(glyph))))
        if len(components) != 3:
            continue
        core, base, weak = components
        # The full boundary must stop growing before the weaker paper cut.
        # A strong core may differ by one antialiasing pixel, not a missing arm.
        if base[1] != weak[1] or max(abs(a - b) for a, b in zip(core[1], base[1])) > 1:
            continue
        a, b, c, d = weak[1]
        char_x, char_y, char_w, char_h = text.character_boxes[0]
        if not (
            char_x <= left + a
            and char_y <= top + b
            and left + c <= char_x + char_w
            and top + d <= char_y + char_h
        ):
            continue
        if any(
            np.any(mask[top:bottom, left:right][weak[0]] > 0)
            for mask in protected_source_masks
        ):
            continue
        metrics = librecad_text_metrics(text.text)
        if (
            metrics.fallback_glyph_count
            or metrics.width <= 0
            or metrics.height <= 0
            or metrics.em_height <= 0
        ):
            continue
        bounds = (left + a, top + b, left + c, top + d)
        new_quad = (
            (float(bounds[0]), float(bounds[1])),
            (float(bounds[2]), float(bounds[1])),
            (float(bounds[2]), float(bounds[3])),
            (float(bounds[0]), float(bounds[3])),
        )
        output[index] = replace(text, quad=new_quad)
        proofs.append(
            {
                "text": text.text,
                "bbox": text.bbox,
                "cell": cell,
                "original_quad": original_quad,
                "display_quad": new_quad,
                "source_bounds": bounds,
                "context_bounds": (left, top, right, bottom),
                "gray_levels": levels,
                "source_pixels": tuple(c[2] for c in components),
                "source_replacement_safe": bool(text.replacement_safe),
                "source_fields_unchanged": True,
                "authority": "display geometry only; no source suppression or member replacement",
            }
        )
    return tuple(output), tuple(proofs)
