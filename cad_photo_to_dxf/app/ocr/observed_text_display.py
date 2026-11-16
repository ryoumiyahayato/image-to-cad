"""Fit native TEXT to measured source ink without changing source ownership."""
from dataclasses import replace
from math import ceil, floor

import cv2
import numpy as np

from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import (
    ReviewLayoutGuard,
    glyph_footprint,
    polygon,
    visible_corners,
)
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.librecad_lff import librecad_font_available
from app.ocr.ocr_layout import _horizontal_character_boxes
from app.ocr.text_output_contract import accepted_ocr_texts

VERSION = "observed-source-components-display-v2"
RECORD_KEY = "observed_text_display_v1"
PDF_LABEL_DISPLAY_VERSION = "isolated-source-label-display-v1"


def _basis(quad):
    p = np.asarray(quad, dtype=float)
    if p.shape != (4, 2) or not np.isfinite(p).all():
        raise ValueError("INVALID_OBSERVATION_QUAD")
    along, across = p[1]-p[0], p[3]-p[0]
    w, h = float(np.linalg.norm(along)), float(np.linalg.norm(across))
    if w < 2 or h < 2:
        raise ValueError("DEGENERATE_OBSERVATION_QUAD")
    u, v = along/w, across/h
    # Only retain an already observed orthogonal reading basis. No new angle.
    if (min(abs(along)) > .5 or min(abs(across)) > .5
            or abs(float(np.dot(u, v))) > 1e-6
            or float(u[0]*v[1]-u[1]*v[0]) < .99
            or np.linalg.norm(p[2]-(p[0]+along+across)) > .5):
        raise ValueError("NON_ORTHOGONAL_OBSERVATION")
    return p, u, v, w, h


def _source_fit(gray, observation, *, reject_enclosing_components=False):
    p, u, v, width, height = _basis(observation.quad)
    w, h, pad = int(round(width)), int(round(height)), 2
    if (w+5)*(h+5) > 65_536:
        raise ValueError("SOURCE_PIXEL_BUDGET")
    expanded = p + np.asarray((-u-v, u-v, u+v, -u+v))*pad
    if (np.any(expanded < 0) or np.any(expanded[:, 0] >= gray.shape[1])
            or np.any(expanded[:, 1] >= gray.shape[0])):
        raise ValueError("SOURCE_PAGE_BOUNDARY")
    target = np.asarray(((0, 0), (w+4, 0), (w+4, h+4), (0, h+4)), np.float32)
    crop = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(expanded.astype(np.float32), target),
                               (w+5, h+5), flags=cv2.INTER_NEAREST)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(crop < 128)*255, connectivity=8)
    glyphs, rules, boundary_fragments = [], [], []
    thin = max(2, int(round(h*.15)))
    for label in range(1, count):
        x, y, cw, ch, _ = map(int, stats[label])
        boundary = x == 0 or y == 0 or x+cw == crop.shape[1] or y+ch == crop.shape[0]
        if boundary:
            if x == 0 and cw == crop.shape[1] and ch <= thin:
                rules.append(("horizontal", x, y, cw, ch))
            elif y == 0 and ch == crop.shape[0] and cw <= thin:
                rules.append(("vertical", x, y, cw, ch))
            else:
                boundary_fragments.append(label)
        elif x <= pad or y <= pad or x+cw >= w+pad or y+ch >= h+pad:
            raise ValueError("SOURCE_INK_AT_OBSERVATION_BOUNDARY")
        else:
            glyphs.append(label)
    if len(glyphs) < 2:
        raise ValueError("NO_SEPARATED_COMPLETE_GLYPHS")
    owned = np.isin(labels, glyphs)
    if reject_enclosing_components:
        # A complete box containing letters is not itself a character. Leave
        # such compound objects to enclosure recovery, not display fitting.
        _contours, hierarchy = cv2.findContours(
            np.uint8(owned), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE,
        )
        if hierarchy is not None and any(
            parent >= 0 and hierarchy[0][parent][3] >= 0
            for parent in hierarchy[0, :, 3]
        ):
            raise ValueError("ENCLOSURE_CONTAINS_SEPARATE_INK")
    for label in boundary_fragments:
        fragment = labels == label
        inner = fragment[pad:pad+h+1, pad:pad+w+1]
        x, y, cw, ch, pixels = map(int, stats[label])
        if np.any(inner):
            # Only a straight independent fragment whose observed intrusion
            # stays in the existing two-pixel perimeter can be context. The
            # rest must actually extend outside the observation into the pad.
            core = inner[pad:-pad, pad:-pad]
            if (np.any(core) or min(cw, ch) > pad
                    or pixels < .8*cw*ch):
                raise ValueError("INCOMPLETE_OR_SHARED_SOURCE_COMPONENT")
        halo = cv2.dilate(np.uint8(fragment), np.ones((5, 5), np.uint8)) > 0
        if np.any(halo & owned):
            raise ValueError("BOUNDARY_CONTEXT_TOUCHES_GLYPHS")
    for direction, x, y, cw, ch in rules:
        # A real cell separator between two source groups is not a license to
        # merge their display. Lines outside the glyph band stay unchanged.
        if direction == "vertical":
            separates = np.any(owned[:, :x]) and np.any(owned[:, x+cw:])
        else:
            separates = np.any(owned[:y, :]) and np.any(owned[y+ch:, :])
        if separates:
            raise ValueError("SOURCE_RULE_BETWEEN_GLYPHS")
    mask = np.uint8(owned[pad:pad+h+1, pad:pad+w+1])*255
    probe = TextCandidate(observation.text, (0, 0, w+1, h+1), .99, "text_candidate")
    boxes, safe, _ = _horizontal_character_boxes(mask, probe)
    # The legacy .72 coverage decision alone is insufficient. Every non-space
    # segment must contain ink, and every complete component must be covered.
    covered = np.zeros(mask.shape, bool)
    for x, y, bw, bh in boxes:
        if not np.any(mask[y:y+bh, x:x+bw]):
            raise ValueError("INCOMPLETE_CHARACTER_SEGMENT_COVERAGE")
        covered[y:y+bh, x:x+bw] = True
    if not safe or not boxes or np.any((mask > 0) & ~covered):
        raise ValueError("NO_COMPLETE_CHARACTER_COVERAGE")
    ys, xs = np.nonzero(mask)
    a, b = max(0, int(xs.min())-1), max(0, int(ys.min())-1)
    c, d = min(w, int(xs.max())+2), min(h, int(ys.max())+2)
    quad = tuple(tuple(map(float, p[0]+u*x+v*y)) for x, y in ((a, b), (c, b), (c, d), (a, d)))
    _basis(quad)
    return quad, dict(complete_components=len(glyphs), separate_rules=len(rules),
                      measured_border_context_components=len(boundary_fragments),
                      measured_bounds=[a, b, c, d])


def _joint_conflicts(proposals, originals):
    blocked = set()
    indexes = sorted(proposals)
    for n, i in enumerate(indexes):
        for j in indexes[n+1:]:
            left, right = proposals[i][1], proposals[j][1]
            if (left.subtracted(originals[i]).intersects(right)
                    or right.subtracted(originals[j]).intersects(left)):
                blocked.update((i, j))
    return blocked


def refine_unfitted_pdf_labels(gray, texts, *, protected_source_masks):
    """Tighten padded OCR labels in place using complete, separated source ink."""
    if not librecad_font_available():
        return texts
    def transform(x, y):
        return (x, gray.shape[0]-y)
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    placements = {
        i: native_text_placement(t, transform=transform)
        for i, t in enumerate(texts) if id(t) in accepted
    }
    footprints = {
        i: polygon(visible_corners(p)) for i, p in placements.items() if p is not None
    }
    updated = list(texts)
    remaining = 262_144
    for i, old in placements.items():
        text = texts[i]
        observation = text.pre_cell_observation
        if (
            old is None or old.metrics.fallback_reason or text.reviewed
            or text.display_quad is not None or not text.source.startswith("rapidocr-")
            or len("".join(text.text.split())) < 2 or "\n" in text.text
        ):
            continue
        if observation is not None and observation.cell_clip_bbox not in (None, observation.bbox):
            continue
        _, _, width, height = text.bbox
        area = (width+5)*(height+5)
        if area > min(remaining, 65_536):
            continue
        remaining -= area
        try:
            quad, _ = _source_fit(gray, text)
        except (ValueError, TypeError, cv2.error):
            continue
        proposal = replace(text, display_quad=quad)
        new = native_text_placement(proposal, transform=transform)
        if new is None:
            continue
        before, after = old.geometry, new.geometry
        if (abs(before.rotation-after.rotation) > .01
                or after.target_height > before.target_height - max(3, .10*before.target_height)
                or not .5 <= after.width_factor <= 2):
            continue
        corners = visible_corners(new)
        # The source-to-CAD transform is its own inverse at this scale.
        xs, ys = zip(*(transform(x, y) for x, y in corners))
        window = (
            slice(max(0, floor(min(ys))-1), ceil(max(ys))+1),
            slice(max(0, floor(min(xs))-1), ceil(max(xs))+1),
        )
        if any(np.any(mask[window]) for mask in protected_source_masks if mask is not None):
            continue
        footprint = polygon(corners)
        if any(j != i and footprint.intersects(other) for j, other in footprints.items()):
            continue
        updated[i], footprints[i] = proposal, footprint
    return tuple(updated)


def refine_observed_text_displays(gray, structure):
    """Apply only display_quad after all source/retirement consumers finish."""
    if (gray.ndim != 2 or gray.dtype != np.uint8 or gray.shape[::-1] != structure.source_size_px
            or gray.size > 32_000_000 or len(structure.texts) > 512
            or structure.provenance.get("review_snapshot_v1")
            or structure.provenance.get("draftsman_output_v1") or not librecad_font_available()):
        return structure
    texts, records, candidates = structure.texts, {}, {}
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    remaining = 262_144
    for i, text in enumerate(texts):
        observation = text.pre_cell_observation
        if observation is None or observation.cell_clip_bbox is None:
            continue
        # Register every actual cell range change, not just successful fits.
        if observation.cell_clip_bbox == observation.bbox:
            continue
        record = dict(index=i, observation_index=observation.candidate_index,
                      text=text.text, decision="REJECTED", reason="NOT_ELIGIBLE")
        records[i] = record
        try:
            if (id(text) not in accepted or text.reviewed or text.display_quad is not None
                    or text.text != observation.text or text.source != observation.source
                    or not text.source.startswith("rapidocr") or not np.isfinite(text.rotation_deg)
                    or text.rotation_deg != observation.rotation_deg):
                raise ValueError("FIXED_OR_CHANGED_CANDIDATE")
            if text.bbox != observation.cell_clip_bbox or text.quad != observation.cell_clip_quad:
                raise ValueError("SOURCE_FIELDS_CHANGED_AFTER_CELL")
            _, _, _, original_width, _ = _basis(observation.quad)
            _, _, _, current_width, _ = _basis(text.quad)
            if original_width <= current_width+1:
                raise ValueError("NO_READING_LENGTH_LOSS")
            area = (observation.bbox[2]+5)*(observation.bbox[3]+5)
            if area <= 0 or area > remaining:
                raise ValueError("SOURCE_PIXEL_BUDGET")
            remaining -= area
            quad, evidence = _source_fit(gray, observation)
            old = native_text_placement(text, transform=lambda x, y: (x, gray.shape[0]-y))
            new = native_text_placement(replace(text, display_quad=quad),
                                        transform=lambda x, y: (x, gray.shape[0]-y))
            if (old is None or new is None or new.metrics.fallback_reason
                    or new.geometry.target_width <= old.geometry.target_width+1):
                raise ValueError("INVALID_OR_NO_COMPLETE_DISPLAY_GAIN")
            candidates[i] = (quad, glyph_footprint(new), new.geometry.payload())
            record.update(evidence, reason="PENDING_VISIBLE_CONTEXT_CHECK")
        except (ValueError, RuntimeError, TypeError, IndexError, OverflowError, cv2.error) as exc:
            record["reason"] = str(exc)
    proposals = {}
    if candidates:
        try:
            guard = ReviewLayoutGuard(structure)
            if guard.unknown:
                raise ValueError("UNMEASURED_VISIBLE_GEOMETRY: "+", ".join(sorted(guard.unknown)))
            originals = {i: glyph_footprint(native_text_placement(texts[i], transform=guard.transform))
                         for i in sorted(guard.emitted_indices)}
            for i, candidate in candidates.items():
                if i not in originals:
                    records[i]["reason"] = "NOT_ACTUALLY_EMITTED"
                    continue
                added = candidate[1].subtracted(originals[i])
                if any(owner is None and added.boundingRect().intersects(bounds) and added.intersects(path)
                       for owner, path, bounds in guard.obstacles):
                    records[i]["reason"] = "NEW_VISIBLE_GEOMETRY_OR_OLD_OUTLINE_CONTACT"
                elif any(j != i and added.intersects(path) for j, path in originals.items()):
                    records[i]["reason"] = "NEW_NATIVE_TEXT_CONTACT"
                else:
                    proposals[i] = candidate
            for i in _joint_conflicts(proposals, originals):
                records[i]["reason"] = "JOINT_NEW_NATIVE_TEXT_CONTACT"
                del proposals[i]
        except (ValueError, RuntimeError, TypeError, IndexError, OverflowError, OSError) as exc:
            for i in candidates:
                records[i]["reason"] = str(exc)
            proposals.clear()
    for i, (quad, _path, geometry) in proposals.items():
        records[i].update(decision="ADOPTED", reason="COMPLETE_SOURCE_AND_NO_NEW_VISIBLE_CONTACT",
                          display_quad=quad, geometry=geometry)
    if not records:
        return structure
    output = tuple(replace(t, display_quad=proposals[i][0]) if i in proposals else t
                   for i, t in enumerate(texts))
    return replace(structure, texts=output, provenance={
        **structure.provenance, RECORD_KEY: dict(version=VERSION, authority="DISPLAY_ONLY",
            source_deletion_authority=False, decisions=[records[i] for i in sorted(records)])})


def refine_source_supported_scan_displays(gray, structure):
    """Tighten only proved source glyphs; no text/content/ownership edits.

    A detector's padded box is a search observation, not the visible cap body.
    Reuse complete-component and character coverage checks. Unknown, shared,
    enclosed, rotated and protected material is left exactly as it was.
    """
    if (gray.ndim != 2 or gray.dtype != np.uint8
            or gray.shape[::-1] != structure.source_size_px
            or structure.provenance.get("clean_digital")
            or structure.provenance.get("review_snapshot_v1")
            or gray.size > 32_000_000 or len(structure.texts) > 512
            or not librecad_font_available()):
        return structure
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPainterPathStroker
    def transform(x, y):
        return (float(x), float(gray.shape[0]-y))
    texts = structure.texts
    accepted = {id(t) for t in accepted_ocr_texts(texts)}
    originals, placements = {}, {}
    for i, t in enumerate(texts):
        if id(t) in accepted:
            p = native_text_placement(t, transform=transform)
            if p is not None and not p.metrics.fallback_reason:
                placements[i], originals[i] = p, glyph_footprint(p)
    fixed = []
    for line in structure.straight_lines:
        path = QPainterPath(QPointF(*transform(line.x1,line.y1)))
        path.lineTo(QPointF(*transform(line.x2,line.y2)))
        pen = QPainterPathStroker()
        pen.setWidth(max(1.0,float(line.width)))
        stroke = pen.createStroke(path)
        fixed.append((stroke, stroke.boundingRect()))
    for obj in (*structure.logos, *structure.signatures):
        x,y,w,h = obj.bbox
        path = polygon((transform(x,y),transform(x+w,y),transform(x+w,y+h),transform(x,y+h)))
        fixed.append((path,path.boundingRect()))
    proposals, records, skipped = {}, [], []
    remaining = 1_048_576
    for i, old in placements.items():
        text = texts[i]
        if (text.reviewed or text.display_quad is not None
                or not text.source.startswith("rapidocr")
                or not text.text.isascii() or not any(c.isalpha() for c in text.text)
                or len("".join(text.text.split())) < 2
                or "\n" in text.text):
            continue
        _,_,w,h = text.bbox
        area = (w+5)*(h+5)
        if area > min(remaining,65_536):
            continue
        remaining -= area
        try:
            quad, proof = _source_fit(gray,text,reject_enclosing_components=True)
            new = native_text_placement(replace(text,display_quad=quad),transform=transform)
            if new is None or new.metrics.fallback_reason:
                raise ValueError("FONT_METRICS_UNAVAILABLE")
            a,b = old.geometry,new.geometry
            if (abs(a.rotation-b.rotation) > .01
                    or b.target_height > a.target_height-max(2,.10*a.target_height)
                    or not .5 <= b.width_factor <= 2):
                raise ValueError("NO_SUPPORTED_CAP_HEIGHT_REDUCTION")
            legal = polygon(old.geometry.transformed_quad)
            if any(not legal.contains(QPointF(*point)) for point in visible_corners(new)):
                raise ValueError("OUTSIDE_EXISTING_DISPLAY_BOX")
            path = glyph_footprint(new)
            added = path.subtracted(originals[i])
            bounds=added.boundingRect()
            if any(bounds.intersects(box) and added.intersects(obstacle) for obstacle,box in fixed):
                raise ValueError("NEW_FIXED_OBJECT_CONTACT")
            if any(j != i and not originals[i].intersects(other)
                   and (path.intersects(other) or (j in proposals and path.intersects(proposals[j][1])))
                   for j,other in originals.items()):
                raise ValueError("NEW_TEXT_CONTACT")
            proposals[i]=(quad,path)
            records.append(dict(index=i,text=text.text,old_quad=text.quad,display_quad=quad,
                height_before=a.target_height,height_after=b.target_height,proof=proof,
                authority="DISPLAY_ONLY",source_deletion_authority=False))
        except (ValueError,TypeError,cv2.error) as exc:
            skipped.append(dict(index=i,reason=str(exc)))
    blocked=_joint_conflicts(proposals, originals)
    for i in blocked:
        proposals.pop(i,None)
    if not proposals:
        return structure
    records=[r for r in records if r["index"] in proposals]
    result=replace(structure,texts=tuple(replace(t,display_quad=proposals[i][0])
        if i in proposals else t for i,t in enumerate(texts)),provenance={
        **structure.provenance,"source_supported_scan_display":dict(
            version="complete-source-cap-body-v1",records=records,skipped=skipped,
            source_deletion_authority=False)})
    result.assert_valid()
    return result
