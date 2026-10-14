"""Whole residual-member replacement. Does not merge or edit accepted LINEs."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil

import cv2
import numpy as np

from app.core.arc_types import ArcSegment
from app.core.structure import FinalStructure, metadata_to_jsonable
from app.geometry.pdf_arc_evidence import NativeArcCandidate, PdfGeometryEvidence


def _box(path):
    p = np.asarray(path.points)
    return (float(p[:, 0].min()), float(p[:, 1].min()),
            float(p[:, 0].max()), float(p[:, 1].max()))


class _ContourIndex:
    def __init__(self, paths):
        self.cells, self.large = {}, []
        for i, path in enumerate(paths):
            if not path.points:
                continue
            x0, y0, x1, y1 = _box(path)
            cells = (range(int(x0)//128, int(x1)//128+1), range(int(y0)//128, int(y1)//128+1))
            if len(cells[0])*len(cells[1]) > 64:
                self.large.append(i)
                continue
            for x in cells[0]:
                for y in cells[1]:
                    self.cells.setdefault((x, y), []).append(i)

    def query(self, box):
        x0, y0, x1, y1 = box
        result = set(self.large)
        for x in range(x0//128, x1//128+1):
            for y in range(y0//128, y1//128+1):
                result.update(self.cells.get((x, y), ()))
        if len(result) > 128:
            raise ValueError('LOCAL_MEMBER_BUDGET')
        return sorted(result)


def _path_mask(path, box):
    x0, y0, x1, y1 = box
    mask = np.zeros((y1-y0, x1-x0), np.uint8)
    points = np.rint(np.asarray(path.points)-[x0, y0]).astype(np.int32)
    cv2.fillPoly(mask, [points], 1)
    return mask.astype(bool)


def _edge_samples(path):
    p = np.asarray(path.points, dtype=float)
    lengths = np.linalg.norm(np.roll(p, -1, axis=0)-p, axis=1)
    if np.ceil(lengths/.5).sum() > 8192:
        raise ValueError('MEMBER_SAMPLE_BUDGET')
    return np.concatenate([a+(b-a)*np.linspace(0, 1, max(2, ceil(length/.5)+1))[:, None]
                           for a, b, length in zip(p, np.roll(p, -1, axis=0), lengths)])


def _near_locus(points, candidate, tolerance):
    params = candidate.parameters
    center, radius = np.asarray(params['center']), params['radius']
    start, sweep = params['start_angle_deg'], params['sweep_angle_deg']
    v = np.asarray(points)-center
    angle = np.degrees(np.arctan2(-v[:, 1], v[:, 0])) % 360
    distance = ((angle-start) if sweep > 0 else (start-angle)) % 360
    radial = np.abs(np.linalg.norm(v, axis=1)-radius)
    end = start+sweep
    ends = np.array([center+[radius*np.cos(np.radians(a)), -radius*np.sin(np.radians(a))]
                     for a in (start, end)])
    end_distance = np.linalg.norm(np.asarray(points)[:, None, :]-ends, axis=2).min(axis=1)
    return ((distance <= abs(sweep)+1e-8) & (radial <= tolerance)) | (end_distance <= tolerance)


def _protection(structure, candidate):
    x0, y0, x1, y1 = candidate.box
    footprint = candidate.native_gray < 255
    for mask in (structure.editable_text_source_mask, structure.source_text_outline_mask,
                 structure.uncertain_text_outline_mask):
        if mask is not None and np.any(footprint & (mask[y0:y1, x0:x1] > 0)):
            raise ValueError('TEXT_SOURCE_PROTECTION')
    for text in structure.texts:
        x, y, w, h = text.bbox
        a, b, c, d = max(x, x0), max(y, y0), min(x+w, x1), min(y+h, y1)
        if a < c and b < d and np.any(footprint[b-y0:d-y0, a-x0:c-x0]):
            raise ValueError('TEXT_REGION_PROTECTION')
    for item in (*structure.logos, *structure.signatures):
        x, y, w, h = item.bbox
        a, b, c, d = max(x, x0), max(y, y0), min(x+w, x1), min(y+h, y1)
        if a < c and b < d and np.any(footprint[b-y0:d-y0, a-x0:c-x0] & (item.mask[b-y:d-y, a-x:c-x] > 0)):
            raise ValueError('GRAPHIC_SOURCE_PROTECTION')


@dataclass(frozen=True)
class ArcReplacementPlan:
    base: FinalStructure
    candidate: NativeArcCandidate
    arc: ArcSegment
    indices: tuple[int, ...]
    box: tuple[int, int, int, int]
    owned_ink: np.ndarray
    proof: dict


def plan_arc_replacement(structure, candidate, index=None):
    if 'draftsman_output_v1' in structure.provenance:
        raise ValueError('FROZEN_COMPOSITE_BINDING')
    _protection(structure, candidate)
    x0, y0, x1, y1 = candidate.box
    residual = structure.contour_binary[y0:y1, x0:x1] < 128
    native = candidate.native_gray < 255
    if residual.shape != native.shape:
        raise ValueError('SOURCE_MAPPING_CHANGED')
    index = index or _ContourIndex(structure.contours)
    selected, masks = [], []
    child_parents = {p.parent for p in structure.contours if p.parent is not None}
    enclosure_indices = {int(r['contour_index']) for r in structure.provenance.get('engineering_enclosures', ())}
    tolerance = candidate.stroke_width_px/2 + 2**.5  # contour edge raster quantization
    for i in index.query(candidate.box):
        path = structure.contours[i]
        if path.depth % 2 or len(path.points) < 3:
            continue
        mask = _path_mask(path, candidate.box)
        ink = mask & residual
        if not np.any(ink & native):
            continue
        bounds = _box(path)
        if not (x0 <= bounds[0] <= bounds[2] < x1 and y0 <= bounds[1] <= bounds[3] < y1):
            raise ValueError('MIXED_MEMBER_EXTENT')
        if path.parent is not None or i in child_parents or i in enclosure_indices:
            raise ValueError('NESTED_OR_SYMBOL_MEMBER')
        if np.any(ink & ~native):
            raise ValueError('FOREIGN_MEMBER_INK')
        if not np.all(_near_locus(_edge_samples(path), candidate, tolerance)):
            raise ValueError('INDEPENDENT_MEMBER_GEOMETRY')
        selected.append(i)
        masks.append(ink)
    if not selected:
        raise ValueError('NO_COMPLETE_RESIDUAL_MEMBER')
    owned = np.logical_or.reduce(masks)
    if np.any(native & residual & ~owned):
        raise ValueError('UNASSIGNED_NATIVE_RESIDUE')
    # Interior source range must still belong to residual members. A LINE that
    # independently observes a curved tail is not silently suppressed or aliased.
    arc = candidate.accepted_member([f'contour:{i}' for i in selected],
        'complete visible PDF stroke; exclusive residual members; retained endpoint participants')
    yy, xx = np.indices(native.shape)
    pts = np.stack((xx+x0, yy+y0), axis=-1)
    ends = np.array([arc.point_at(0), arc.point_at(1)])
    cap_distance = np.linalg.norm(pts[:, :, None, :]-ends, axis=-1).min(axis=2)
    cap_reach = max(3., candidate.stroke_width_px*2)
    interior = native & (cap_distance > cap_reach)
    # Only foreground admitted by the existing source preparation can have
    # been claimed upstream. Faint antialias samples excluded by that threshold are
    # still native stroke evidence, but are not missing residual ownership.
    source_foreground = (
        structure.preview_binary[y0:y1, x0:x1] < 128
        if structure.preview_binary is not None
        else candidate.source_gray <= structure.threshold
    )
    if np.any(interior & source_foreground & ~residual):
        raise ValueError('INTERIOR_STROKE_ALREADY_CLAIMED')
    round_caps = candidate.cap_neighborhood() if candidate.stroke_cap == 'round' else None
    if round_caps is not None:
        candidate.check_round_caps()
        if np.any(round_caps & native & source_foreground & ~owned):
            raise ValueError('ROUND_CAP_SOURCE_NOT_OWNED')
    endpoint_lines = []
    vertices = np.concatenate([np.asarray(structure.contours[i].points) for i in selected])
    shared_nodes = []
    for i, line in enumerate(structure.straight_lines):
        if max(line.x1, line.x2) < x0 or min(line.x1, line.x2) > x1 or max(line.y1, line.y2) < y0 or min(line.y1, line.y2) > y1:
            continue
        for endpoint in ((line.x1, line.y1), (line.x2, line.y2)):
            if np.any(np.linalg.norm(vertices-np.asarray(endpoint), axis=1) <= 1e-7):
                if np.linalg.norm(ends-np.asarray(endpoint), axis=1).min() > 1e-7:
                    raise ValueError('EXACT_CAD_NODE_WOULD_CHANGE')
                shared_nodes.append(dict(line_index=i, point=list(endpoint), preserved=True))
        claim = np.zeros(native.shape, np.uint8)
        cv2.line(claim, (round(line.x1-x0), round(line.y1-y0)),
                 (round(line.x2-x0), round(line.y2-y0)), 1, max(1, ceil(line.width)), cv2.LINE_8)
        if np.any(interior & (claim > 0)):
            raise ValueError('INTERIOR_SHARED_LINE_CLAIM')
        contacts = native & (claim > 0)
        if round_caps is not None and np.any(round_caps & (claim > 0)):
            raise ValueError('ROUND_CAP_SHARED_LINE_CLAIM')
        if np.any(contacts):
            endpoint_lines.append(dict(index=i, source_ids=list(line.source_ids),
                geometry=[line.x1, line.y1, line.x2, line.y2], unchanged=True,
                contact_pixels=int(contacts.sum())))
    owned.setflags(write=False)
    for i in index.query(candidate.box):
        if i in selected:
            continue
        if round_caps is not None and np.any(round_caps & _path_mask(structure.contours[i], candidate.box) & residual):
            raise ValueError('ROUND_CAP_SHARED_CONTOUR_CLAIM')
        for point in structure.contours[i].points:
            if np.any(np.linalg.norm(vertices-np.asarray(point), axis=1) <= 1e-7) and np.linalg.norm(ends-np.asarray(point), axis=1).min() > 1e-7:
                raise ValueError('SHARED_CONTOUR_NODE_WOULD_CHANGE')
    return ArcReplacementPlan(structure, candidate, arc, tuple(selected), candidate.box, owned,
        dict(native_reference=arc.payload()['source'], numeric=candidate.numeric_evidence,
             visible_stroke_pixels=int(native.sum()), owned_residual_pixels=int(owned.sum()),
             replaced_contours=[dict(index=i, points=list(structure.contours[i].points)) for i in selected],
             endpoint_lines=endpoint_lines, exact_shared_nodes=shared_nodes,
             round_caps=candidate.numeric_evidence.get('round_caps'),
             endpoints_source_px=list(ends.tolist()),
             policy='no line movement, extension, deletion or new connection; complete contour members only'))


def commit_arc_replacement(structure, plan):
    """One immutable commit, including residual suppression and index rebinding."""
    existing = next((a for a in structure.arcs if a.object_id == plan.arc.object_id), None)
    records = structure.provenance.get('native_arc_replacements', ())
    if existing is not None:
        if existing == plan.arc and any(r.get('object_id') == existing.object_id for r in records):
            return structure
        raise ValueError('ARC_ID_ALREADY_OCCUPIED')
    if any(i >= len(structure.contours) or structure.contours[i] != plan.base.contours[i] for i in plan.indices):
        raise ValueError('REPLACEMENT_MEMBER_MISSING_OR_CHANGED')
    if structure is not plan.base:
        raise ValueError('STALE_REPLACEMENT_PLAN')
    verified = plan_arc_replacement(structure, plan.candidate)
    if verified.arc != plan.arc or verified.indices != plan.indices or not np.array_equal(verified.owned_ink, plan.owned_ink):
        raise ValueError('REPLACEMENT_PROOF_CHANGED')
    plan = verified
    # Parameter validation precedes suppression, even for externally built plans.
    arc = ArcSegment.from_payload(plan.arc.payload())
    removed = set(plan.indices)
    remap = {old: new for new, old in enumerate(i for i in range(len(structure.contours)) if i not in removed)}
    paths = []
    for i, path in enumerate(structure.contours):
        if i in removed:
            continue
        if path.parent in removed or path.root in removed:
            raise ValueError('REPLACEMENT_HAS_DEPENDENT_MEMBER')
        paths.append(replace(path, parent=remap[path.parent] if path.parent is not None else None,
                             root=remap[path.root]))
    binary = structure.contour_binary.copy()
    x0, y0, x1, y1 = plan.box
    binary[y0:y1, x0:x1][plan.owned_ink] = 255
    provenance = metadata_to_jsonable(structure.provenance)
    presentation = provenance.get('stroke_presentation')
    if presentation is not None:
        presentation['fill_records'] = {str(remap[int(k)]): v for k, v in presentation.get('fill_records', {}).items() if int(k) in remap}
    if provenance.get('engineering_enclosures'):
        provenance['engineering_enclosures'] = [dict(r, contour_index=remap[int(r['contour_index'])]) for r in provenance['engineering_enclosures']]
    provenance['native_arc_replacements'] = [*provenance.get('native_arc_replacements', ()),
        dict(object_id=arc.object_id, replaced_members=list(arc.replaced_members), **plan.proof)]
    return replace(structure, contours=tuple(paths), contour_binary=binary,
                   arcs=tuple(sorted((*structure.arcs, arc), key=lambda a: a.object_id)), provenance=provenance)


def apply_pdf_arc_evidence(structure: FinalStructure, image, evidence: PdfGeometryEvidence):
    if not evidence.candidates and not evidence.rejections:
        return structure
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    decisions = list(evidence.rejections)
    if evidence.source_size_px != structure.source_size_px or gray.shape[::-1] != evidence.source_size_px:
        decisions.append({'reason': 'SOURCE_MAPPING_CHANGED', 'decision': 'REJECTED',
                          'stage': 'binding', 'category': 'unavailable'})
        candidates = ()
    else:
        candidates = evidence.candidates
    for candidate in sorted(candidates, key=lambda c: c.object_id):
        x0, y0, x1, y1 = candidate.box
        try:
            if not np.array_equal(gray[y0:y1, x0:x1], candidate.source_gray):
                raise ValueError('STALE_RENDER_EVIDENCE')
            existing = next((a for a in structure.arcs if a.object_id == candidate.object_id), None)
            if existing is not None:
                records = structure.provenance.get('native_arc_replacements', ())
                committed = any(r.get('object_id') == existing.object_id and
                                tuple(r.get('replaced_members', ())) == existing.replaced_members
                                for r in records)
                if not committed or existing != candidate.accepted_member(existing.replaced_members, existing.acceptance_reason):
                    raise ValueError('ARC_ID_ALREADY_OCCUPIED')
                decisions.append(dict(object_id=candidate.object_id, decision='ACCEPTED',
                                      stage='replacement', category='accepted',
                                      replaced_members=list(existing.replaced_members)))
                continue
            plan = plan_arc_replacement(structure, candidate, _ContourIndex(structure.contours))
            structure = commit_arc_replacement(structure, plan)
            decisions.append(dict(object_id=candidate.object_id, decision='ACCEPTED',
                                  stage='replacement', category='accepted',
                                  replaced_members=list(plan.arc.replaced_members)))
        except (ValueError, KeyError) as exc:
            reason = str(exc)
            decisions.append(dict(object_id=candidate.object_id, decision='REJECTED', reason=reason,
                stage='binding' if reason == 'STALE_RENDER_EVIDENCE' else 'replacement',
                category='unavailable' if reason == 'STALE_RENDER_EVIDENCE' else 'membership'))
    observation = dict(event='native_pdf_arcs', binding=evidence.binding,
                       page_to_pixel=list(evidence.page_to_pixel), decisions=decisions)
    if evidence.analysis:
        observation['analysis'] = evidence.analysis
    if any(metadata_to_jsonable(o) == observation for o in structure.observations if o.get('event') == 'native_pdf_arcs'):
        return structure
    previous = tuple(o for o in structure.observations if o.get('event') != 'native_pdf_arcs')
    return replace(structure, observations=(*previous, observation))
