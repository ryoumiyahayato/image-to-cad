"""Independent continuous LINE/source audit; never imports the proposal.

Coordinates are original native pixel centres. Pixel (x,y) is the CLOSED unit
cell [x-.5,x+.5] x [y-.5,y+.5]. Ink is closed, paper regions are the connected
open complement (polygon interiors). Joins do not exist inside a two-point LINE.

Round pens have analytic contact predicates and nested inscribed/circumscribed
polygon bounds. No arc approximation is used to relax a threshold. A round
case passes only when both bounds give the same relevant topology and a convex
cover/Helly certificate excludes a topology change inside the uncertainty band.
The sole 1e-8 tolerance is anchored to an OBSERVED old zero-area ink contact,
for equivalence with old 8-neighbour connectivity; it never dilates a shape.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point, Polygon, box
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

VERSION = "independent-continuous-shared-core-tracks-v2"
CAPS = ("butt", "round", "square")
JOINS = ("round", "mitre", "bevel")
ARC_SIDES = 512
OLD_ZERO_AREA_CONTACT_EPSILON = 1e-8
MAX_CAP_COMBINATIONS = 729
MAX_NERVE_CHECKS = 250_000
BOUNDARY_LIMIT_NATIVE = 1.0
PEN_EDGE_LIMIT_WORK = .25
KEYS = {
    "retired": "native_retired_source_runs_y_x0_x1",
    "support": "native_supporting_source_runs_y_x0_x1",
    "mandatory": "native_mandatory_retained_source_runs_y_x0_x1",
    "core": "native_shared_core_source_runs_y_x0_x1",
    "guard": "native_guard_source_runs_y_x0_x1",
    "collar": "native_exclusive_collar_source_runs_y_x0_x1",
}


def _hash(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _runs(mask):
    answer = []
    for y, row in enumerate(mask):
        d = np.diff(np.r_[False, row, False].astype(np.int8))
        answer.extend((y, int(a), int(b)) for a, b in
                      zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
    return answer


def _mask(runs, shape):
    if not isinstance(runs, (list, tuple)):
        raise ValueError("source runs must be an explicit sequence")
    answer = np.zeros(shape, bool)
    for row in runs:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError("source run must have y,x0,x1")
        if any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in row):
            raise ValueError("source run coordinates must be integers")
        y, a, b = map(int, row)
        if not (0 <= y < shape[0] and 0 <= a < b <= shape[1]):
            raise ValueError("source run is outside the native tile")
        if answer[y, a:b].any():
            raise ValueError("overlapping runs within one source ledger")
        answer[y, a:b] = True
    return answer


def _rectangles(mask):
    """Merge identical adjacent row runs into exact axis-aligned cell boxes."""
    active = {}
    bounds = []
    for y in range(mask.shape[0] + 1):
        keys = []
        if y < mask.shape[0]:
            d = np.diff(np.r_[False, mask[y], False].astype(np.int8))
            keys = [(int(a), int(b)) for a, b in
                    zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))]
        next_active = {}
        for key in keys:
            next_active[key] = active.pop(key, y)
        for (a, b), first_y in active.items():
            bounds.append((a-.5, first_y-.5, b-.5, y-.5))
        active = next_active
    return [box(*b) for b in bounds]


def _union(items):
    return unary_union(items) if items else GeometryCollection()


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > 0 else []
    if hasattr(geometry, "geoms"):
        return [p for g in geometry.geoms for p in _polygons(g)]
    return []


def _evidence(geometry):
    return {"empty": bool(geometry.is_empty), "type": geometry.geom_type,
            "area_native_px2": float(geometry.area), "length_native_px": float(geometry.length),
            "bounds": list(geometry.bounds) if not geometry.is_empty else [],
            "wkt_excerpt": geometry.wkt[:1400] if not geometry.is_empty else "GEOMETRYCOLLECTION EMPTY"}


def _fail(failures, code, **context):
    failures.append({"code": code, **context})


def _line_bounds(points, width, cap):
    """Return convex inner/outer bounds containing exactly the LINE cap domain."""
    a, b = points
    v = b-a
    tangent = v / np.linalg.norm(v)
    normal = np.array([-tangent[1], tangent[0]])
    r = width/2.
    if cap in ("butt", "square"):
        extension = 0. if cap == "butt" else r
        first, last = a-extension*tangent, b+extension*tangent
        geom = Polygon([first+r*normal, last+r*normal, last-r*normal, first-r*normal])
        return geom, geom, 0.
    # A circumscribed regular polygon has apothem r. Its edges are tangent to
    # the circle. Convex hull of its two translations encloses the capsule.
    theta = np.arange(ARC_SIDES, dtype=float)*(2.*math.pi/ARC_SIDES)
    unit_inner = np.cos(theta)[:, None]*tangent + np.sin(theta)[:, None]*normal
    outer_theta = theta + math.pi/ARC_SIDES
    unit_outer = np.cos(outer_theta)[:, None]*tangent + np.sin(outer_theta)[:, None]*normal
    factor = 1./math.cos(math.pi/ARC_SIDES)
    inner = MultiPoint(np.vstack((a+r*unit_inner, b+r*unit_inner))).convex_hull
    outer = MultiPoint(np.vstack((a+r*factor*unit_outer, b+r*factor*unit_outer))).convex_hull
    return inner, outer, r*(factor-1.)


def _point_pen_distance(points, ends, width, cap):
    a, b = ends
    v = b-a
    length = float(np.linalg.norm(v))
    tangent = v/length
    normal = np.array([-tangent[1], tangent[0]])
    p = np.asarray(points, float)-a
    along, across = p @ tangent, np.abs(p @ normal)
    radius = width/2.
    if cap == "round":
        beyond = np.maximum(np.maximum(-along, along-length), 0.)
        return np.maximum(np.hypot(across, beyond)-radius, 0.)
    extension = radius if cap == "square" else 0.
    beyond = np.maximum(np.maximum(-extension-along, along-length-extension), 0.)
    return np.hypot(np.maximum(across-radius, 0.), beyond)


def _cell_corner_distance(rectangles, ends, width, cap):
    # Distance to a convex pen is convex; its maximum over each source cell
    # rectangle occurs at a vertex. This checks all source area, not centres.
    points = [p for rect in rectangles for p in list(rect.exterior.coords)[:-1]]
    return float(_point_pen_distance(points, ends, width, cap).max()) if points else 0.


def _round_contact(line, width, geometry):
    if geometry.is_empty:
        return False, None
    distance = float(line.distance(geometry))
    return distance <= width/2., distance


def _source_margin_check(pen_inner, pen_outer, source):
    """Conservative continuous pen -> original source distance <= exactly 1."""
    inside_offset = source.buffer(BOUNDARY_LIMIT_NATIVE, quad_segs=ARC_SIDES//4)
    # The inscribed round offset is a subset of the true Euclidean offset.
    proved = bool(inside_offset.covers(pen_outer))
    return {"all_points_within_one_native_px_proved": proved,
            "method": "circumscribed_pen_covered_by_inscribed_source_1px_offset",
            "unproved_region": _evidence(pen_outer.difference(inside_offset)),
            "threshold_native_px": BOUNDARY_LIMIT_NATIVE,
            "no_threshold_relaxation": True}


def _old_zero_contacts(geometry):
    parts = _polygons(geometry)
    if not parts:
        return GeometryCollection()
    tree = STRtree(parts)
    contacts = []
    for i, part in enumerate(parts):
        for j in tree.query(part):
            j = int(j)
            if j <= i:
                continue
            contact = part.intersection(parts[j])
            if not contact.is_empty and contact.area == 0:
                contacts.append(contact)
    return _union(contacts)


def _ink_regions(geometry, old_contacts):
    parts = _polygons(geometry)
    roots = list(range(len(parts)))
    def root(i):
        while roots[i] != i:
            roots[i] = roots[roots[i]]
            i = roots[i]
        return i
    uses = []
    if parts:
        tree = STRtree(parts)
        eps = OLD_ZERO_AREA_CONTACT_EPSILON
        for i, part in enumerate(parts):
            lo, bot, hi, top = part.bounds
            for j in tree.query(box(lo-eps, bot-eps, hi+eps, top+eps)):
                j = int(j)
                if j <= i or root(i) == root(j):
                    continue
                joined = part.intersects(parts[j])
                if not joined and not old_contacts.is_empty:
                    distance = float(part.distance(parts[j]))
                    if 0. < distance <= eps:
                        a, b = nearest_points(part, parts[j])
                        if a.distance(old_contacts) <= eps and b.distance(old_contacts) <= eps:
                            joined = True
                            uses.append({"part_indices": [i,j], "gap_native_px": distance,
                                         "old_contact_witness": _evidence(old_contacts.intersection(box(
                                             a.x-eps, a.y-eps, a.x+eps, a.y+eps)))})
                if joined:
                    roots[root(j)] = root(i)
    groups = {}
    for i, part in enumerate(parts):
        groups.setdefault(root(i), []).append(part)
    return [_union(g) for g in groups.values()], uses


def _bijection(old, new):
    links = []
    by_old = [[] for _ in old]
    by_new = [[] for _ in new]
    tree = STRtree(new) if new else None
    for i, a in enumerate(old):
        for j in ([] if tree is None else tree.query(a)):
            j = int(j)
            area = float(a.intersection(new[j]).area)
            if area > 0.:
                by_old[i].append(j)
                by_new[j].append(i)
                links.append({"before": i, "after": j, "positive_overlap_native_px2": area})
    passed = (len(old) == len(new) and all(len(v) == 1 for v in by_old)
              and all(len(v) == 1 for v in by_new))
    return {"passed": bool(passed), "before_regions": len(old), "after_regions": len(new),
            "before_to_after": by_old, "after_to_before": by_new,
            "positive_area_overlap_links": links}


def _topology(before, after, tile, old_contacts):
    old_ink, _ = _ink_regions(before, old_contacts)
    new_ink, epsilon_uses = _ink_regions(after, old_contacts)
    # Paper is open: polygon components that meet only on an ink boundary are
    # not joined. Do not apply ink's 8-neighbour equivalence to white regions.
    old_paper = _polygons(tile.difference(before))
    new_paper = _polygons(tile.difference(after))
    ink = _bijection(old_ink, new_ink)
    paper = _bijection(old_paper, new_paper)
    return {"passed": bool(ink["passed"] and paper["passed"]), "ink": ink, "paper": paper,
            "old_zero_area_contact_epsilon_uses": epsilon_uses}


def _nerve_certificate(fixed, pen_bounds):
    """Stable convex-cover nerve via pair/triple intersections (Helly R2).

    Every primitive is convex: merged source-cell boxes and convex LINE pens.
    Exact pens are nested between their bounds. Unchanged emptiness of all
    pair/triple intersections proves the whole nerve unchanged, excluding a
    hidden component/hole in the round-arc approximation band.
    """
    count = 0
    uncertain = []
    tree = STRtree(fixed) if fixed else None
    def check(inner, outer, members):
        nonlocal count
        count += 1
        if count > MAX_NERVE_CHECKS:
            raise ValueError("CONVEX_COVER_CERTIFICATE_BUDGET")
        if bool(inner.is_empty) != bool(outer.is_empty):
            uncertain.append({"members": members, "inner_empty": bool(inner.is_empty),
                              "outer_empty": bool(outer.is_empty), "outer_intersection": _evidence(outer)})
    # Fixed pair intersections are reusable in one-pen/two-fixed triples.
    fixed_pair_cache = {}
    for i, (inner, outer) in enumerate(pen_bounds):
        if inner.equals(outer):
            continue
        near = [int(j) for j in ([] if tree is None else tree.query(outer))]
        for j in near:
            check(inner.intersection(fixed[j]), outer.intersection(fixed[j]), [f"pen:{i}",f"source:{j}"])
        for j in near:
            for k in ([] if tree is None else tree.query(fixed[j])):
                k = int(k)
                if k <= j or k not in near:
                    continue
                key = (j,k)
                fixed_intersection = fixed_pair_cache.setdefault(key, fixed[j].intersection(fixed[k]))
                if not fixed_intersection.is_empty:
                    check(inner.intersection(fixed_intersection), outer.intersection(fixed_intersection),
                          [f"pen:{i}",f"source:{j}",f"source:{k}"])
    for i, j in itertools.combinations(range(len(pen_bounds)), 2):
        ai, ao = pen_bounds[i]
        bi, bo = pen_bounds[j]
        if ai.equals(ao) and bi.equals(bo):
            continue
        low, high = ai.intersection(bi), ao.intersection(bo)
        check(low, high, [f"pen:{i}",f"pen:{j}"])
        for k in ([] if tree is None else tree.query(high)):
            k = int(k)
            check(low.intersection(fixed[k]), high.intersection(fixed[k]),
                  [f"pen:{i}",f"pen:{j}",f"source:{k}"])
    for indices in itertools.combinations(range(len(pen_bounds)), 3):
        low = pen_bounds[indices[0]][0]
        high = pen_bounds[indices[0]][1]
        variable = False
        for i in indices:
            variable |= not pen_bounds[i][0].equals(pen_bounds[i][1])
        if not variable:
            continue
        for i in indices[1:]:
            low = low.intersection(pen_bounds[i][0])
            high = high.intersection(pen_bounds[i][1])
        check(low, high, [f"pen:{i}" for i in indices])
    return {"passed": not uncertain, "pair_and_triple_checks": count,
            "uncertain_intersections": uncertain,
            "proof": "NESTED_CONVEX_PRIMITIVES; STABLE_PAIRS_AND_TRIPLES; HELLY_R2; CLOSED_CONVEX_NERVE"}


def audit_continuous(result, parent, native_foreign, native_forbidden, scale, dpi):
    """Audit explicit returned geometry/ledgers; ignore all producer verdicts.

    parent, native_foreign, native_forbidden: native-resolution bool arrays.
    scale: integer native/working grid ratio. dpi: working-grid DPI.
    The supplied masks are authority; result.status/reason/pass/audits are not.
    """
    start = time.monotonic()
    report = {"schema_version":1, "auditor":VERSION, "all_passed":False,
              "producer_verdicts_used":False, "source_pixel_cell_extent":"center +/- 0.5 native pixel",
              "input_contract":{}, "ledger_checks":{}, "candidate_checks":[],
              "pair_contacts":[], "topology":[], "failures":[],
              "own_source_center_coverage":"NOT_REPEATED; SEPARATE_INDEPENDENT_ORACLE",
              "join_geometry_note":"Two-vertex LINE has no internal join. Three join labels repeat one cap geometry.",
              "production_authorization":False}
    failures = report["failures"]
    try:
        arrays = [parent,native_foreign,native_forbidden]
        if any(not isinstance(a,np.ndarray) or a.dtype != np.bool_ or a.ndim != 2 for a in arrays):
            raise ValueError("all source inputs must be native two-dimensional bool arrays")
        if any(a.shape != parent.shape for a in arrays):
            raise ValueError("native input shapes differ")
        if isinstance(scale,bool) or not isinstance(scale,(int,np.integer)) or scale <= 0:
            raise ValueError("positive integer native scale required")
        if isinstance(dpi,bool) or not isinstance(dpi,(int,float,np.number)) or not math.isfinite(float(dpi)) or dpi <= 0:
            raise ValueError("finite positive working dpi required")
        if not isinstance(result,dict) or not isinstance(result.get("candidates"), (list,tuple)):
            raise ValueError("explicit candidate list required")
        parts = list(result["candidates"])
        report["input_contract"] = {"passed":True,"shape":list(parent.shape),"scale":int(scale),"dpi":float(dpi),
            "parent_sha256":_hash(parent),"foreign_sha256":_hash(native_foreign),
            "forbidden_sha256":_hash(native_forbidden),"candidate_count":len(parts)}
        before_hashes = tuple(_hash(a) for a in arrays)
        if np.any(parent & native_foreign):
            _fail(failures,"PARENT_FOREIGN_SOURCE_OVERLAP")
        parent_rects = _rectangles(parent)
        parent_geom = _union(parent_rects)
        foreign_geom = _union(_rectangles(native_foreign))
        forbidden_geom = _union(_rectangles(native_forbidden))
        tile = box(-.5,-.5,parent.shape[1]-.5,parent.shape[0]-.5)
        declared_source = _mask(result["native_source_runs_y_x0_x1"],parent.shape)
        residual = _mask(result["native_residual_runs_y_x0_x1"],parent.shape)
        if not np.array_equal(declared_source,parent):
            _fail(failures,"DECLARED_PARENT_DIFFERS_FROM_ACTUAL_SOURCE")
        retired_union = np.zeros(parent.shape,bool)
        prepared = []
        for index, part in enumerate(parts):
            masks = {name:_mask(part[key],parent.shape) for name,key in KEYS.items()}
            check = {"candidate_index":index,"part_id":part.get("part_id"),"failures":[],"cap_join_checks":[]}
            cf = check["failures"]
            for name, mask in masks.items():
                outside = int(np.count_nonzero(mask & ~parent))
                if outside:
                    _fail(cf,"SOURCE_RUNS_CLAIM_NONPARENT",ledger=name,pixels=outside)
            if not masks['retired'].any():
                _fail(cf,"EMPTY_RETIRED_SOURCE")
            duplicate = int(np.count_nonzero(retired_union & masks['retired']))
            if duplicate:
                _fail(cf,"DUPLICATE_RETIRED_SOURCE",pixels=duplicate)
            retired_union |= masks['retired']
            mandatory_union = masks['core'] | masks['guard'] | masks['collar']
            if not np.array_equal(mandatory_union,masks['mandatory']):
                _fail(cf,"MANDATORY_RUNS_DIFFER_FROM_CORE_GUARD_COLLAR_UNION")
            # These are retained-role annotations, not exclusive ownership
            # partitions. In particular a guard may also be an exclusive
            # terminal collar. Their exact UNION is the mandatory source.
            check['retained_role_overlap_pixels'] = {
                f'{a}_and_{b}':int(np.count_nonzero(masks[a] & masks[b]))
                for a,b in itertools.combinations(('core','guard','collar'),2)}
            if np.any(masks['retired'] & masks['mandatory']):
                _fail(cf,"OWN_RETIRED_SOURCE_TOUCHES_MANDATORY_RETAINED_CELLS")
            if np.any(masks['retired'] & ~masks['support']):
                _fail(cf,"RETIREMENT_OUTSIDE_DECLARED_SUPPORTING_BAND")
            work_points = np.asarray(part['points_px'],float)
            native_points = np.asarray(part['native_points_px'],float)
            if work_points.shape != (2,2) or native_points.shape != (2,2) or not np.isfinite(work_points).all() or not np.isfinite(native_points).all():
                raise ValueError("only finite two-vertex LINE is in this auditor's scope")
            points = (work_points+.5)*scale-.5
            if not np.array_equal(points,native_points):
                _fail(cf,"WORKING_NATIVE_COORDINATE_BINDING_DIFFERS",max_abs_delta=float(np.max(np.abs(points-native_points))))
            vector = points[1]-points[0]
            if np.linalg.norm(vector) <= 0:
                raise ValueError("zero-length LINE")
            if not (vector[0] == 0 or vector[1] == 0):
                _fail(cf,"NONCARDINAL_LINE_OUTSIDE_DECLARED_SOURCE_BAND_SCOPE")
            axis = 'horizontal' if vector[1] == 0 else 'vertical'
            if part.get('axis') != axis:
                _fail(cf,"DECLARED_AXIS_DIFFERS_FROM_GEOMETRY")
            code = part['lineweight_hundredth_mm']
            if isinstance(code,bool) or not isinstance(code,(int,np.integer)) or code <= 0:
                raise ValueError("positive integer lineweight required")
            width = float(code)*float(dpi)*int(scale)/2540.
            if float(part['native_pen_width_px']) != width:
                _fail(cf,"DECLARED_PEN_WIDTH_DIFFERS_FROM_ACTUAL_LINEWEIGHT")
            support_rects = _rectangles(masks['support'])
            support_geom = _union(support_rects)
            if support_geom.is_empty:
                raise ValueError("empty source supporting band")
            bounds = support_geom.bounds
            rectangular = support_geom.equals(box(*bounds))
            if not rectangular:
                _fail(cf,"SUPPORTING_BAND_IS_NOT_COMPLETE_CELL_RECTANGLE")
            normal_lo,normal_hi = (bounds[1],bounds[3]) if axis == 'horizontal' else (bounds[0],bounds[2])
            normal_position = points[0,1] if axis == 'horizontal' else points[0,0]
            observed_width = normal_hi-normal_lo
            edge_shift = max(abs(normal_position-width/2.-normal_lo),abs(normal_position+width/2.-normal_hi))/scale
            if float(part['source_width_native_px']) != observed_width:
                _fail(cf,"DECLARED_SOURCE_WIDTH_DIFFERS_FROM_SUPPORT_CELLS")
            if edge_shift > PEN_EDGE_LIMIT_WORK:
                _fail(cf,"PEN_EDGE_SHIFT_EXCEEDS_QUARTER_WORK_PIXEL",measured=edge_shift,limit=PEN_EDGE_LIMIT_WORK)
            line = LineString(points)
            center_inside = bool(parent_geom.covers(line))
            if not center_inside:
                _fail(cf,"CONTINUOUS_CENTERLINE_LEAVES_ORIGINAL_PARENT",outside=_evidence(line.difference(parent_geom)))
            check.update(actual_native_points=points.tolist(),actual_pen_width_native_px=width,
                         source_width_from_cells_native_px=observed_width,maximum_pen_edge_shift_work_px=edge_shift,
                         full_centerline_inside_actual_parent=center_inside,retired_source_pixels=int(masks['retired'].sum()))
            geoms = {key:_union(_rectangles(mask)) for key,mask in masks.items()}
            prepared.append({'part':part,'masks':masks,'geoms':geoms,'points':points,'line':line,'width':width,
                             'retired_rects':_rectangles(masks['retired']),'caps':{},'check':check})
            report['candidate_checks'].append(check)
        expected_residual = parent & ~retired_union
        ledger_exact = np.array_equal(residual,expected_residual)
        if not ledger_exact:
            _fail(failures,"FULL_RESULT_RESIDUAL_DIFFERS_FROM_SOURCE_MINUS_UNION_RETIREMENT",
                  differing_cells=int(np.count_nonzero(residual ^ expected_residual)))
        for index,item in enumerate(prepared):
            missing = int(np.count_nonzero(item['masks']['mandatory'] & ~residual))
            if missing:
                _fail(item['check']['failures'],"ANOTHER_CANDIDATE_RETIRES_MANDATORY_SOURCE",pixels=missing)
        report['ledger_checks']={'exact_source_minus_retirement':bool(ledger_exact),
            'source_cells':int(parent.sum()),'retired_union_cells':int(retired_union.sum()),
            'residual_cells':int(residual.sum()),'pixel_cell_geometry_area':float(parent_geom.area),
            'source_rectangles':len(parent_rects)}
        residual_rects = _rectangles(residual)
        residual_geom = _union(residual_rects)
        for index,item in enumerate(prepared):
            for cap in CAPS:
                inner,outer,arc_error = _line_bounds(item['points'],item['width'],cap)
                item['caps'][cap]=(inner,outer)
                forward = _cell_corner_distance(item['retired_rects'],item['points'],item['width'],cap)
                row={'cap':cap,'join_styles':list(JOINS),'independent_geometries_for_three_joins':1,
                     'join_note':'NO_INTERNAL_JOIN_IN_TWO_VERTEX_LINE',
                     'round_outer_radial_error_bound_native_px':arc_error,
                     'retired_full_cell_to_pen_error_native_px':forward,
                     'retired_support_error_limit_native_px':BOUNDARY_LIMIT_NATIVE,'failures':[]}
                rf=row['failures']
                if forward > BOUNDARY_LIMIT_NATIVE:
                    _fail(rf,"FULL_RETIRED_SOURCE_SUPPORT_ERROR_EXCEEDS_ONE_NATIVE_PIXEL",measured=forward)
                reverse = _source_margin_check(inner,outer,parent_geom)
                row['pen_to_parent_source']=reverse
                if not reverse['all_points_within_one_native_px_proved']:
                    _fail(rf,"CONTINUOUS_PEN_TO_PARENT_ERROR_NOT_PROVED_WITHIN_ONE_NATIVE_PIXEL")
                if not tile.covers(outer):
                    _fail(rf,"CONTINUOUS_PEN_LEAVES_BOUND_NATIVE_TILE")
                for label,geom in (('foreign',foreign_geom),('forbidden',forbidden_geom)):
                    if cap=='round':
                        contact,distance=_round_contact(item['line'],item['width'],geom)
                        method='ANALYTIC_SEGMENT_DISTANCE_LE_RADIUS'
                    else:
                        contact=bool(inner.intersects(geom))
                        distance=float(inner.distance(geom)) if not geom.is_empty else None
                        method='EXACT_POLYGON_INTERSECTION'
                    row[f'{label}_contact']={'contact':contact,'distance_native_px':distance,'method':method}
                    if contact:
                        _fail(rf,f'CONTINUOUS_PEN_CONTACTS_{label.upper()}',contact=_evidence(outer.intersection(geom)))
                upper_contact=outer.intersection(residual_geom)
                lower_contact=inner.intersection(residual_geom)
                illegal_upper=upper_contact.difference(item['geoms']['mandatory'])
                illegal_lower=lower_contact.difference(item['geoms']['mandatory'])
                row['residual_contact']={'all_contacts_within_declared_mandatory_source':bool(illegal_upper.is_empty),
                    'outside_mandatory_lower':_evidence(illegal_lower),'outside_mandatory_upper':_evidence(illegal_upper),
                    'mandatory_roles':['shared_core','guard','exclusive_collar']}
                if not illegal_upper.is_empty:
                    _fail(rf,'PEN_RESIDUAL_CONTACT_OUTSIDE_EXPLICIT_MANDATORY_SOURCE' if not illegal_lower.is_empty
                          else 'ROUND_CONTACT_CONTAINMENT_UNPROVED')
                row['passed']=not rf
                item['check']['cap_join_checks'].append(row)
            item['check']['passed']=not item['check']['failures'] and all(x['passed'] for x in item['check']['cap_join_checks'])
        for i,j in itertools.combinations(range(len(prepared)),2):
            a,b=prepared[i],prepared[j]
            declared_common=a['geoms']['core'].intersection(b['geoms']['core'])
            supported_common=declared_common.intersection(parent_geom).intersection(residual_geom)
            for ca,cb in itertools.product(CAPS,repeat=2):
                ai,ao=a['caps'][ca];bi,bo=b['caps'][cb]
                low=ai.intersection(bi);high=ao.intersection(bo)
                illegal_low=low.difference(supported_common)
                illegal_high=high.difference(supported_common)
                passed=bool(illegal_high.is_empty)
                pair={'candidate_indices':[i,j],'caps':[ca,cb],'passed':passed,
                      'all_join_pairs_same_geometry':True,'shared_core_intersection_source':_evidence(supported_common),
                      'contact_lower':_evidence(low),'contact_upper':_evidence(high),
                      'outside_shared_source_lower':_evidence(illegal_low),'outside_shared_source_upper':_evidence(illegal_high)}
                if not passed:
                    pair['failure']='CANDIDATE_CONTACT_OUTSIDE_BOTH_DECLARED_SHARED_CORES' if not illegal_low.is_empty else 'ROUND_PAIR_CONTACT_CONTAINMENT_UNPROVED'
                report['pair_contacts'].append(pair)
        before_ink=parent_geom.union(foreign_geom)
        old_contacts=_old_zero_contacts(before_ink)
        fixed_rects=_rectangles(residual | native_foreign)
        fixed_geom=_union(fixed_rects)
        combinations=3**len(prepared)
        if combinations>MAX_CAP_COMBINATIONS:
            _fail(failures,'CAP_COMBINATION_AUDIT_BUDGET',required=combinations,limit=MAX_CAP_COMBINATIONS)
        else:
            for caps in itertools.product(CAPS,repeat=len(prepared)):
                bounds=[item['caps'][cap] for item,cap in zip(prepared,caps)]
                low=_union([fixed_geom]+[p[0] for p in bounds])
                high=_union([fixed_geom]+[p[1] for p in bounds])
                low_topology=_topology(before_ink,low,tile,old_contacts)
                high_topology=_topology(before_ink,high,tile,old_contacts)
                certificate=_nerve_certificate(fixed_rects,bounds)
                passed=bool(low_topology['passed'] and high_topology['passed'] and certificate['passed'])
                report['topology'].append({'caps':list(caps),'passed':passed,
                    'before_vs_inner':low_topology,'before_vs_outer':high_topology,
                    'round_uncertainty_topology_certificate':certificate,
                    'old_zero_area_contact_epsilon_native_px':OLD_ZERO_AREA_CONTACT_EPSILON,
                    'epsilon_policy':'ONLY_AT_OBSERVED_OLD_ZERO_AREA_CONTACT; NO_DILATION; NO_WHITE_GAP_BRIDGING'})
        report['input_arrays_unchanged']=before_hashes==tuple(_hash(a) for a in arrays)
        if not report['input_arrays_unchanged']:
            _fail(failures,'AUDITOR_MUTATED_INPUT')
        for i,c in enumerate(report['candidate_checks']):
            if not c['passed']:
                _fail(failures,'CANDIDATE_CONTINUOUS_CHECK_FAILED',candidate_index=i)
        for p in report['pair_contacts']:
            if not p['passed']:
                _fail(failures,p['failure'],candidate_indices=p['candidate_indices'],caps=p['caps'])
        for row in report['topology']:
            if not row['passed']:
                _fail(failures,'CONTINUOUS_INK_PAPER_TOPOLOGY_OR_CERTIFICATE_FAILED',caps=row['caps'])
        report['all_passed']=not failures
    except Exception as error:
        _fail(failures,'AUDITOR_CANNOT_CERTIFY',exception_type=type(error).__name__,message=str(error))
        report['all_passed']=False
    report['wall_seconds']=time.monotonic()-start
    return report


def _toy_candidate(parent, support, retired, core, guard, points, scale, dpi, code=40, part_id=1):
    collar=support & ~retired & ~core & ~guard
    mandatory=core|guard|collar
    bounds=_union(_rectangles(support)).bounds
    axis='horizontal' if points[0][1]==points[1][1] else 'vertical'
    source_width=(bounds[3]-bounds[1]) if axis=='horizontal' else (bounds[2]-bounds[0])
    return {'part_id':part_id,'axis':axis,'points_px':((np.asarray(points)+.5)/scale-.5).tolist(),
            'native_points_px':np.asarray(points).tolist(),'lineweight_hundredth_mm':code,
            'native_pen_width_px':code*dpi*scale/2540.,'source_width_native_px':source_width,
            **{KEYS[k]:_runs(v) for k,v in {'retired':retired,'support':support,'core':core,
                                          'guard':guard,'collar':collar,'mandatory':mandatory}.items()}}


def _toy_result(parent, candidates):
    retired=np.zeros(parent.shape,bool)
    for c in candidates:
        retired|=_mask(c[KEYS['retired']],parent.shape)
    return {'candidates':candidates,'native_source_runs_y_x0_x1':_runs(parent),
            'native_residual_runs_y_x0_x1':_runs(parent & ~retired),
            'status':'PRODUCER_STATUS_DELIBERATELY_IGNORED'}


def self_checks():
    shape=(80,160);scale=2;dpi=127.
    source=np.zeros(shape,bool);source[38:42,10:150]=True;source[15:38,78:82]=True
    support=np.zeros(shape,bool);support[38:42,10:150]=True
    retired=np.zeros(shape,bool);retired[38:42,25:65]=True;retired[38:42,95:135]=True
    core=source.copy();core[:,:78]=False;core[:,82:]=False
    guard=source.copy();guard[:,:72]=False;guard[:,88:]=False;guard&=~core
    c=_toy_candidate(source,support,retired,core,guard,[[12.,39.5],[147.,39.5]],scale,dpi)
    result=_toy_result(source,[c]);blank=np.zeros(shape,bool)
    cases=[]
    def add(name,res,parent=source,foreign=blank,forbidden=blank,expected=True,required=None,scale_value=scale):
        audit=audit_continuous(res,parent,foreign,forbidden,scale_value,dpi)
        text=json.dumps(audit,sort_keys=True)
        passed=(audit['all_passed']==expected and (required is None or required in text))
        cases.append({'name':name,'expected_all_passed':expected,'self_check_passed':passed,'required_evidence':required,'audit':audit})
    add('exact_width_T_positive',result)
    # The producer verdict must neither grant nor deny certification.
    contradictory=deepcopy(result);contradictory['status']='REJECTED';contradictory['reason']='UNTRUSTED_LABEL'
    add('producer_rejected_label_is_ignored',contradictory)
    overlapping_roles=deepcopy(result)
    overlapping_roles['candidates'][0][KEYS['collar']]=_runs(
        _mask(c[KEYS['collar']],shape) | (_mask(c[KEYS['guard']],shape)&support))
    add('retained_guard_collar_roles_may_overlap',overlapping_roles)
    # Full centreline crosses actual source absence. Rebind ledgers to that source
    # so the error is independently visible beyond a declared parent mismatch.
    gap=source.copy();gap[38:42,45]=False
    bad=deepcopy(result);bad['native_source_runs_y_x0_x1']=_runs(gap)
    add('white_gap_under_continuous_centerline',bad,parent=gap,expected=False,required='CONTINUOUS_CENTERLINE_LEAVES_ORIGINAL_PARENT')
    outside=deepcopy(result)
    for key in ('mandatory','collar'):
        m=_mask(outside['candidates'][0][KEYS[key]],shape);m[38:42,24]=False
        outside['candidates'][0][KEYS[key]]=_runs(m)
    add('unlisted_residual_contact',outside,expected=False,required='PEN_RESIDUAL_CONTACT_OUTSIDE_EXPLICIT_MANDATORY_SOURCE')
    foreign=blank.copy();foreign[43,50:60]=True
    wide=deepcopy(result);w=wide['candidates'][0];w['lineweight_hundredth_mm']=60;w['native_pen_width_px']=6.
    add('continuous_foreign_tangent_is_contact',wide,foreign=foreign,expected=False,required='CONTINUOUS_PEN_CONTACTS_FOREIGN')
    add('continuous_protected_tangent_is_contact',wide,forbidden=foreign,expected=False,required='CONTINUOUS_PEN_CONTACTS_FORBIDDEN')
    narrow=deepcopy(result);w=narrow['candidates'][0];w['lineweight_hundredth_mm']=10;w['native_pen_width_px']=1.
    add('complete_retired_cells_not_only_centres',narrow,expected=False,required='FULL_RETIRED_SOURCE_SUPPORT_ERROR_EXCEEDS_ONE_NATIVE_PIXEL')
    # Orthogonal LINE pair: explicit shared cores are the sole authority for
    # mutual contact. Both spans retain their core and end collars.
    cross=np.zeros((160,160),bool);cross[78:82,10:150]=True;cross[10:150,78:82]=True
    candidates=[]
    for index,axis in enumerate(('horizontal','vertical')):
        band=np.zeros_like(cross);ret=np.zeros_like(cross)
        if axis=='horizontal':
            band[78:82,10:150]=True;ret[78:82,25:65]=True;ret[78:82,95:135]=True
            corex=cross.copy();corex[:,:78]=False;corex[:,82:]=False
            guardx=cross.copy();guardx[:,:72]=False;guardx[:,88:]=False
            points=[[12.,79.5],[147.,79.5]]
        else:
            band[10:150,78:82]=True;ret[25:65,78:82]=True;ret[95:135,78:82]=True
            corex=cross.copy();corex[:78]=False;corex[82:]=False
            guardx=cross.copy();guardx[:72]=False;guardx[88:]=False
            points=[[79.5,12.],[79.5,147.]]
        candidates.append(_toy_candidate(cross,band,ret,corex,guardx&~corex,points,scale,dpi,part_id=index+1))
    cross_blank=np.zeros_like(cross)
    conflicting_pair_result=_toy_result(cross,deepcopy(candidates))
    add('other_candidate_retires_declared_mandatory_arm',conflicting_pair_result,parent=cross,
        foreign=cross_blank,forbidden=cross_blank,expected=False,
        required='ANOTHER_CANDIDATE_RETIRES_MANDATORY_SOURCE')
    # The preceding full-column/full-row cores deliberately promise to retain
    # the other candidate's entire arm. For a separate geometric positive the
    # explicit common core is only the true central source square; end collars
    # and guards belong to each candidate's own band. This tests the audit API,
    # not the producer's more restrictive full-parent-column selection policy.
    middle=np.zeros_like(cross);middle[78:82,78:82]=True
    for candidate in candidates:
        band=_mask(candidate[KEYS['support']],cross.shape)
        ret=_mask(candidate[KEYS['retired']],cross.shape)
        old_guard=_mask(candidate[KEYS['guard']],cross.shape)
        limited_guard=old_guard & band & ~middle
        collar=band & ~ret & ~middle & ~limited_guard
        for key,mask in {'core':middle,'guard':limited_guard,'collar':collar,
                         'mandatory':middle|limited_guard|collar}.items():
            candidate[KEYS[key]]=_runs(mask)
    pair_result=_toy_result(cross,candidates)
    add('two_pens_true_common_shared_source',pair_result,parent=cross,foreign=cross_blank,forbidden=cross_blank)
    pair_bad=deepcopy(pair_result)
    moved=_mask(pair_bad['candidates'][1][KEYS['core']],cross.shape)
    oldguard=_mask(pair_bad['candidates'][1][KEYS['guard']],cross.shape)
    pair_bad['candidates'][1][KEYS['core']]=[]
    pair_bad['candidates'][1][KEYS['guard']]=_runs(oldguard|moved)
    add('pair_contact_cannot_use_guard_as_shared_core',pair_bad,parent=cross,foreign=cross_blank,forbidden=cross_blank,
        expected=False,required='CANDIDATE_CONTACT_OUTSIDE_BOTH_DECLARED_SHARED_CORES')
    # Independent geometry primitives and topology oracle controls.
    unit=np.zeros((3,3),bool);unit[1,1]=True
    cell=_union(_rectangles(unit))
    cell_ok=list(cell.bounds)==[.5,.5,1.5,1.5] and cell.area==1.
    diag=np.zeros((4,4),bool);diag[1,1]=diag[2,2]=True
    diaggeom=_union(_rectangles(diag));anchors=_old_zero_contacts(diaggeom)
    diagregions,_=_ink_regions(diaggeom,anchors)
    separated=_union([box(.5,.5,1.5-1e-9,1.5),box(1.5,1.5,2.5,2.5)])
    tolerated,uses=_ink_regions(separated,anchors)
    unanchored,_=_ink_regions(separated,GeometryCollection())
    topology_before=box(0,0,20,20).difference(box(2,2,5,5))
    topology_after=box(0,0,20,20).difference(box(12,12,15,15))
    shifted=_topology(topology_before,topology_after,box(-1,-1,21,21),GeometryCollection())
    primitive_checks={'half_cell_corner_convention':cell_ok,'old_diagonal_ink_is_one_closed_component':len(diagregions)==1,
        'epsilon_only_at_observed_zero_contact':len(tolerated)==1 and bool(uses),
        'unobserved_sub_epsilon_gap_is_not_bridged':len(unanchored)==2,
        'same_region_counts_wrong_paper_overlap_rejected':not shifted['passed'] and not shifted['paper']['passed']}
    return {'auditor':VERSION,'all_passed':all(c['self_check_passed'] for c in cases) and all(primitive_checks.values()),
            'constructed_geometry_cases':cases,'primitive_checks':primitive_checks,
            'same_count_wrong_overlap_evidence':shifted,'real_sources_run':0}


def audit_saved_controls(input_dir, output_dir):
    """Read saved inputs/results without importing or executing their producer."""
    import cv2
    output_dir.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();usage=resource.getrusage(resource.RUSAGE_SELF)
    rows=[]
    for path in sorted(input_dir.glob('*.parent_*.result.json')):
        result=json.loads(path.read_text())
        if not result.get('candidates'):
            continue
        name,label_text=path.name.split('.parent_',1)
        label=int(label_text.split('.',1)[0])
        inputs=input_dir/f'{name}.inputs.npz'
        with np.load(inputs,allow_pickle=False) as z:
            gray=z['gray'];native_gray=z['native_gray'];protected=z['protected']
        if native_gray.shape[0] % gray.shape[0] or native_gray.shape[1] % gray.shape[1]:
            raise ValueError('native dimensions are not integer multiples of working inputs')
        scale=native_gray.shape[0]//gray.shape[0]
        if scale!=native_gray.shape[1]//gray.shape[1]:
            raise ValueError('native/work scale is anisotropic')
        frozen=json.loads((Path(__file__).parent/'controls_frozen.json').read_text())
        dpi_by_name={row['name']:float(row['dpi']) for row in frozen['controls']}
        # NativeFixture's independent dataclass default and two direct-native
        # constructions use 100 working DPI; this is not a producer field.
        dpi_by_name.update(one_native_black_spur=100.,one_native_white_notch=100.)
        dpi=dpi_by_name[name]
        identity=result['source_identity']
        if scale!=identity['native_scale'] or dpi!=identity['working_dpi']:
            raise ValueError('producer source identity differs from independent fixture scale/dpi')
        _,labels=cv2.connectedComponents(np.uint8(gray<254),connectivity=8)
        component=labels==label
        native_source=native_gray==0
        parent=native_source & np.repeat(np.repeat(component,scale,0),scale,1)
        native_foreign=native_source & ~parent
        work_forbidden=((gray<254)&~component)|protected
        native_forbidden=np.repeat(np.repeat(work_forbidden,scale,0),scale,1)
        audit=audit_continuous(result,parent,native_foreign,native_forbidden,scale,dpi)
        target=output_dir/f'{name}.parent_{label}.continuous.json'
        target.write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        rows.append({'name':name,'parent':label,'candidate_count':len(result['candidates']),
                     'all_passed':audit['all_passed'],'failures':audit['failures'],
                     'input_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),
                     'result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'audit_file':str(target.resolve()),'wall_seconds':audit['wall_seconds']})
        print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    after=resource.getrusage(resource.RUSAGE_SELF)
    report={'auditor':VERSION,'all_passed':bool(rows) and all(r['all_passed'] for r in rows),
            'nonempty_parent_results':len(rows),'candidate_count':sum(r['candidate_count'] for r in rows),
            'producer_executed':False,'real_sources_run':0,'production_adoptions':0,'cases':rows,
            'wall_seconds':time.monotonic()-started,'user_cpu_seconds':after.ru_utime-usage.ru_utime,
            'system_cpu_seconds':after.ru_stime-usage.ru_stime,'process_peak_rss_kib':after.ru_maxrss,
            'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check',type=Path)
    parser.add_argument('--controls',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.self_check:
        if args.self_check.exists():
            raise FileExistsError('preserve the earlier auditor self-check')
        report=self_checks()
        args.self_check.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'self_checks_all_passed':report['all_passed'],
                          'case_outcomes':[(c['name'],c['self_check_passed'],c['audit']['all_passed']) for c in report['constructed_geometry_cases']],
                          'primitive_checks':report['primitive_checks']},ensure_ascii=False),flush=True)
        if not report['all_passed']:
            raise SystemExit(1)
    if args.controls:
        if args.output is None:
            parser.error('--controls requires --output')
        report=audit_saved_controls(args.controls,args.output)
        print(json.dumps({'all_passed':report['all_passed'],'candidate_count':report['candidate_count'],
                          'nonempty_parent_results':report['nonempty_parent_results']},ensure_ascii=False),flush=True)
        if not report['all_passed']:
            raise SystemExit(1)


if __name__=='__main__':
    main()
