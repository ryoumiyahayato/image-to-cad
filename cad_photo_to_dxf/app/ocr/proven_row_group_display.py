"""Late display-only fitting of complete source-proven printed row groups.

Never supplies source-removal authority. Original OCR, source quads, character
boxes, safety, ownership, contours, rules and existing display fits stay fixed.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from math import isfinite
from time import perf_counter

import numpy as np
from PySide6.QtCore import QPointF

from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import (
    ReviewLayoutGuard, glyph_footprint, polygon, source_anchored_text_placement,
    visible_corners,
)
from app.geometry.text_residual_retirement import pixel_runs
from app.ocr.librecad_lff import librecad_font_available
from app.ocr.ocr_layout import _restore_cell_text_rows
from app.ocr.text_output_contract import accepted_ocr_texts

VERSION = "complete-row-group-display-v1"
BUDGETS = dict(page_pixels=32_000_000, texts=512, groups=32,
               source_pixels=262_144, seconds=30.0)


def _context_eligible(text):
    if (text.reviewed or text.display_quad is not None
            or text.kind != "text_candidate" or not text.source.startswith("rapidocr")
            or not text.text.isascii() or not text.text.isprintable()
            or not any(c.isalpha() for c in text.text)
            or not isfinite(text.rotation_deg) or abs(text.rotation_deg) > 0.5):
        return False
    x, y, w, h = text.bbox
    if w <= 0 or h <= 0:
        return False
    if text.quad and (len(text.quad) != 4
            or not all(isfinite(v) for p in text.quad for v in p)
            or text.quad[1][0] <= text.quad[0][0]
            or text.quad[2][0] <= text.quad[3][0]
            or abs(text.quad[1][1] - text.quad[0][1]) > w * 0.03):
        return False
    return True


def _simple_label(text):
    # A conservative output class, not a transcript validator. Operators,
    # dimensions, signatures/CJK mixtures and pure numbers are fixed context.
    return (all(c.isalnum() or c.isspace() for c in text.text)
            and sum(c.isalpha() for c in text.text) >= 2)


def _groups(texts, emitted):
    eligible = [i for i in sorted(emitted) if _context_eligible(texts[i])]
    neighbors = {i: set() for i in eligible}
    for position, i in enumerate(eligible):
        x, y, w, h = texts[i].bbox
        for j in eligible[position + 1:]:
            a, b, c, d = texts[j].bbox
            if (min(x+w, a+c) - max(x, a) >= 0.5 * min(w, c)
                    and max(y, b) < min(y+h, b+d)
                    and abs(y+h/2-b-d/2) > 0.3 * min(h, d)):
                neighbors[i].add(j)
                neighbors[j].add(i)
    visited = set()
    for i in eligible:
        if i in visited or not neighbors[i]:
            continue
        pending, group = [i], set()
        while pending:
            j = pending.pop()
            if j not in group:
                group.add(j)
                pending.extend(neighbors[j] - group)
        visited.update(group)
        if 2 <= len(group) <= 6:
            yield tuple(sorted(group, key=lambda j: (texts[j].bbox[1], texts[j].bbox[0])))


def refine_proven_row_group_displays(gray, structure):
    """Return an immutable final snapshot, or the exact original on failure.

    Neighborhood rectangles only locate evidence. The existing strict complete
    component proof must account for every interior strong source component;
    boundary contacts, foreign/shared strokes and incomplete rows fail closed.
    """
    if (gray.ndim != 2 or gray.dtype != np.uint8
            or gray.shape[::-1] != structure.source_size_px
            or gray.size > BUDGETS["page_pixels"]
            or len(structure.texts) > BUDGETS["texts"]
            or structure.provenance.get("review_snapshot_v1")
            or not librecad_font_available()):
        return structure
    started = perf_counter()
    texts = structure.texts
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    preliminary = set(i for i, t in enumerate(texts) if id(t) in accepted)
    groups = tuple(_groups(texts, preliminary))
    if not groups or len(groups) > BUDGETS["groups"]:
        return structure
    remaining = BUDGETS["source_pixels"]
    sources, skipped = [], []
    try:
        for indexes in groups:
            if perf_counter() - started > BUDGETS["seconds"]:
                return structure
            rows = tuple(texts[i] for i in indexes)
            # A two-pixel source-paper inspection margin, not erasure authority.
            l = max(0, min(t.bbox[0] for t in rows)-2)
            t = max(0, min(t.bbox[1] for t in rows)-2)
            r = min(gray.shape[1], max(t.bbox[0]+t.bbox[2] for t in rows)+2)
            b = min(gray.shape[0], max(t.bbox[1]+t.bbox[3] for t in rows)+2)
            area = (r-l)*(b-t)
            if area <= 0 or area > min(65_536, remaining):
                skipped.append(dict(indices=indexes, reason="SOURCE_PIXEL_BUDGET"))
                continue
            remaining -= area
            proofs = []
            fitted = _restore_cell_text_rows(
                gray, rows, (l,t,r,b), verified_sources=proofs, source_group=True,
            )
            if len(proofs) != 1:
                skipped.append(dict(indices=indexes, reason="NO_COMPLETE_SOURCE_ROW_PROOF"))
                continue
            sources.append((indexes, fitted, proofs[0]))
        if not sources:
            return structure
        guard = ReviewLayoutGuard(structure)
        if guard.unknown or perf_counter()-started > BUDGETS["seconds"]:
            return structure
        originals = {}
        for i in sorted(guard.emitted_indices):
            placement = native_text_placement(texts[i], transform=guard.transform)
            if placement is None or placement.metrics.fallback_reason:
                return structure
            originals[i] = glyph_footprint(placement)
        proposals, records = {}, []
        for indexes, fitted, proof in sources:
            if not set(indexes) <= guard.emitted_indices:
                continue
            stage, held = {}, []
            for i, fit in zip(indexes, fitted, strict=True):
                if not _simple_label(texts[i]):
                    held.append(dict(index=i, reason="CONTENT_CLASS_ABSTAIN"))
                    continue
                placement = source_anchored_text_placement(
                    texts[i], texts[i].text, fit.quad, transform=guard.transform,
                )
                original = native_text_placement(texts[i], transform=guard.transform)
                # Only a source-tight fit entirely within the original legal
                # display footprint; no new position, pitch or spacing is invented.
                legal = polygon(original.geometry.transformed_quad)
                if any(not legal.contains(QPointF(*p))
                       for p in visible_corners(placement)):
                    held.append(dict(index=i, reason="OUTSIDE_ORIGINAL_DISPLAY"))
                    continue
                path = glyph_footprint(placement)
                added = path.subtracted(originals[i])
                if any(owner is None and added.boundingRect().intersects(bounds)
                       and added.intersects(obstacle)
                       for owner, obstacle, bounds in guard.obstacles):
                    held.append(dict(index=i, reason="NEW_VISIBLE_GEOMETRY_CONTACT"))
                    continue
                # A neighbor may later retain its original layout. Check both
                # original and staged versions, never assume another fit succeeds.
                stage[i] = (fit.quad, path, placement.geometry.payload())
            for i in tuple(stage):
                path = stage[i][1]
                if any(j != i and not originals[i].intersects(other)
                       and (path.intersects(other)
                            or (j in stage and path.intersects(stage[j][1]))
                            or (j in proposals and path.intersects(proposals[j][1])))
                       for j, other in originals.items()):
                    del stage[i]
                    held.append(dict(index=i, reason="NEW_NATIVE_TEXT_CONTACT"))
            before = {(i,j) for n,i in enumerate(indexes) for j in indexes[n+1:]
                      if originals[i].intersects(originals[j])}
            after = {(i,j) for n,i in enumerate(indexes) for j in indexes[n+1:]
                     if stage.get(i,(None,originals[i]))[1].intersects(
                         stage.get(j,(None,originals[j]))[1])}
            if not stage or not after < before:
                skipped.append(dict(indices=indexes, reason="NO_PROVED_CONTACT_REDUCTION"))
                continue
            proposals.update(stage)
            l,t,r,b = proof.bounds
            records.append(dict(
                indices=indexes, source_bounds=proof.bounds,
                source_strong_runs=pixel_runs(proof.mask > 0, left=l, top=t),
                changed=[dict(index=i, text=texts[i].text, bbox=texts[i].bbox,
                              original_quad=texts[i].quad, display_quad=quad,
                              source_row_runs=pixel_runs(proof.row_masks[indexes.index(i)] > 0,
                                                         left=l, top=t), geometry=geometry)
                         for i,(quad,_path,geometry) in stage.items()],
                held_context=held, native_pairs_before=sorted(before),
                native_pairs_after=sorted(after), authority="DISPLAY_ONLY",
                source_deletion_authority=False,
            ))
        if not proposals or perf_counter()-started > BUDGETS["seconds"]:
            return structure
        # Joint all-or-nothing check, including every unchanged actual emitted row.
        for i,(_quad,path,_geometry) in proposals.items():
            if perf_counter()-started > BUDGETS["seconds"]:
                return structure
            for j, old in originals.items():
                if j != i and not originals[i].intersects(old):
                    if path.intersects(old) or (j in proposals and path.intersects(proposals[j][1])):
                        return structure
        output = tuple(replace(t, display_quad=proposals[i][0]) if i in proposals else t
                       for i,t in enumerate(texts))
        source_digest = sha256(gray.tobytes()).hexdigest()
        if perf_counter()-started > BUDGETS["seconds"]:
            return structure
        candidate = replace(structure, texts=output, provenance={
            **structure.provenance, "proven_row_group_display": dict(
                version=VERSION, authority="DISPLAY_ONLY", source_deletion_authority=False,
                source_gray_sha256=source_digest,
                rows=records, abstained_groups=skipped,
            ),
        })
        # Soft elapsed-time checkpoints cannot interrupt an individual Qt/I/O
        # call, but no late-over-budget candidate may become the final snapshot.
        return structure if perf_counter()-started > BUDGETS["seconds"] else candidate
    except (ValueError, RuntimeError, TypeError, IndexError, OverflowError, OSError, KeyError):
        # No partial commit if exact fonts, the formal export or any proof fails.
        return structure
