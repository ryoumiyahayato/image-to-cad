"""Source-bound target representatives and interval evidence for selection only."""

import math
from collections import defaultdict

from trial_sampling import intersect, line_relation, same_target


def length(line):
    return math.hypot(line[2]-line[0], line[3]-line[1])


def line_key(g):
    a, b = tuple(g[:2]), tuple(g[2:])
    return tuple(round(v, 8) for p in sorted((a, b)) for v in p)


def geometry_key(row):
    members = [line_key(g) for g in row.get('display_geometry', [])]
    return tuple(sorted(members)), tuple(row.get('display_target_box') or ())


def member_map(row):
    ids, lines = row.get('candidate_geometry_ids', []), row.get('display_geometry', [])
    return dict(zip(ids, lines)) if ids and len(ids) == len(lines) else {}


def same_source(a, b):
    return (a['source_drawing_id'], a['source_page']) == (b['source_drawing_id'], b['source_page'])


def same_observed_target(a, b):
    """Full member set plus geometry; a shared member is not a shared PAIR."""
    if not same_source(a, b):
        return False
    ma, mb = member_map(a), member_map(b)
    if ma or mb:
        # Different detector IDs do not make exactly identical source geometry new.
        if ma and mb and geometry_key(a) == geometry_key(b):
            return True
        tolerance = min((72/r['source_dpi'] for r in (a, b) if r.get('source_dpi')), default=.8)
        return (bool(ma) and ma.keys() == mb.keys()
                and all(line_relation(g, mb[k], tolerance=tolerance, gap=0) for k, g in ma.items())
                and same_target(a, b))
    if a.get('target_kind') == 'CONTROL' and b.get('target_kind') == 'CONTROL':
        # A contained bounding box can belong to a separate component/fragment.
        # Overlap is display burden, not proof of the identical region target.
        aa, bb = a.get('display_target_box'), b.get('display_target_box')
        return bool(aa and bb and tuple(aa) == tuple(bb))
    # Existing non-native records have no detector lineage. Keep their old rule.
    return same_target(a, b)


def union_intervals(intervals):
    """Union only actual intervals. Separate gaps remain separate."""
    result = []
    for lo, hi in sorted(intervals):
        if hi <= lo:
            continue
        if result and lo <= result[-1][1]:
            result[-1][1] = max(result[-1][1], hi)
        else:
            result.append([lo, hi])
    return result


def covered_intervals(target, others):
    extent = length(target)
    if not extent:
        return []
    tx, ty = (target[2]-target[0])/extent, (target[3]-target[1])/extent
    intervals = []
    for g in others:
        if not line_relation(target, g, tolerance=.8, gap=0):
            continue
        projected = sorted((g[i]-target[0])*tx+(g[i+1]-target[1])*ty for i in (0, 2))
        intervals.append([max(0, projected[0]), min(extent, projected[1])])
    return union_intervals(intervals)


def coverage_against_outputs(row, outputs):
    """Per-member coverage and full-relation coverage are separate facts."""
    members, full = member_map(row), []
    for old in outputs:
        if same_source(row, old) and members and (member_map(old).keys() == members.keys() or same_observed_target(row, old)):
            full.append(old)
    def match(gid, target, old):
        mapped = member_map(old)
        return mapped.get(gid) or next((g for g in mapped.values() if line_key(g) == line_key(target)), None)
    evidence = []
    for gid, target in members.items():
        related = [(old, g) for old in outputs
                   if same_source(row, old) and (g := match(gid, target, old)) is not None]
        intervals = covered_intervals(target, [g for _, g in related])
        joint = covered_intervals(target, [g for old in full if (g := match(gid, target, old)) is not None])
        extent = length(target)
        total = sum(hi-lo for lo, hi in intervals)
        evidence.append({'member_id': gid, 'length_pdf_points': extent,
                         'covered_intervals_pdf_points': intervals,
                         'covered_fraction': total/extent if extent else 0,
                         'missing_length_pdf_points': max(0, extent-total),
                         'outputs': [old['sample_id'] for old, _ in related],
                         'full_relation_covered_fraction': sum(hi-lo for lo, hi in joint)/extent if extent else 0})
    return {'members': evidence,
            'complete_member_relation_outputs': [old['sample_id'] for old in full],
            'full_target_coverage_fraction': min((e['full_relation_covered_fraction'] for e in evidence), default=0),
            'mean_missing_length_pdf_points': sum(e['missing_length_pdf_points'] for e in evidence)/len(evidence) if evidence else 0}


def burden_coverage(row, outputs):
    """Near-collinear quota carriers measure exposure, NOT target equivalence."""
    evidence = []
    groups = set(row.get('longline_proxy_ids', []))
    for target in row.get('display_geometry', []):
        nearby = [g for old in outputs if same_source(row, old)
                  and groups & set(old.get('longline_proxy_ids', []))
                  for g in old.get('display_geometry', [])
                  if line_relation(target, g, tolerance=1.25, gap=0)]
        # The existing quota's 1.25 paper-point carrier tolerance is deliberately
        # separate from source-member identity. Project only actual intervals.
        extent = length(target)
        tx, ty = (target[2]-target[0])/extent, (target[3]-target[1])/extent
        intervals = []
        for g in nearby:
            p = sorted((g[i]-target[0])*tx+(g[i+1]-target[1])*ty for i in (0, 2))
            intervals.append([max(0, p[0]), min(extent, p[1])])
        union = union_intervals(intervals)
        covered = sum(hi-lo for lo, hi in union)
        evidence.append({'covered_intervals_pdf_points': union,
                         'covered_fraction': covered/extent,
                         'missing_length_pdf_points': max(0, extent-covered)})
    return {'members': evidence,
            'mean_missing_length_pdf_points': sum(e['missing_length_pdf_points'] for e in evidence)/len(evidence) if evidence else 0,
            'limit': 'shared carrier exposure proxy only; different faces/relations stay different targets'}


def shared_line_occupants(row, outputs):
    result = defaultdict(list)
    for old in outputs:
        if not same_source(row, old):
            continue
        common = set(row.get('longline_proxy_ids', [])) & set(old.get('longline_proxy_ids', []))
        if common and any(line_relation(g, h, tolerance=1.25, gap=math.inf)
                          for g in row.get('display_geometry', []) for h in old.get('display_geometry', [])):
            for proxy in common:
                result[proxy].append(old['sample_id'])
    return dict(result)


def evidence_rank(row):
    """No sample IDs, human labels or nomination kinds in the evidence rank."""
    metrics = row.get('quality', {}).get('metrics', {})
    prefixes = ['A', 'B'][:len(row.get('display_geometry', []))]
    scale = row.get('quality', {}).get('actual_source_pixels_per_reference_pixel', 1)
    lengths = [metrics.get(s+'_LENGTH_PX', length(g)) / scale
               for s, g in zip(prefixes, row.get('display_geometry', []))]
    support = [metrics.get(s+'_SOURCE_SUPPORT_RATIO', 1) for s in prefixes]
    endpoints = [metrics.get(s+'_ENDPOINT_SUPPORT', 1) for s in prefixes]
    direction = [metrics.get(s+'_EDGE_ATTACHMENT', {}).get('directional_edge_ratio', 1) for s in prefixes]
    fit = [metrics.get(s+'_MEAN_DISTANCE_TO_DARK_INK', 0)/max(metrics.get(s+'_SUPPORT_RADIUS_PX', 1), 1e-9) for s in prefixes]
    # One reference-pixel bin prevents subpixel clipping jitter deciding a tie.
    return (-min(support, default=1), -round(min(lengths, default=0)),
            -min(endpoints, default=1), -round(min(direction, default=1), 2),
            sum(fit)/len(fit) if fit else 0, geometry_key(row))


def choose_representatives(rows):
    """Complete-link groups avoid joining targets through a transitive bridge."""
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: (-min((length(g) for g in r.get('display_geometry', [])), default=0), geometry_key(r))):
        key = (row['source_drawing_id'], row['source_page'], len(row.get('display_geometry', [])))
        for group in groups[key]:
            if all(same_observed_target(row, other) for other in group):
                group.append(row)
                break
        else:
            groups[key].append([row])
    representatives, rejected = [], []
    for page_groups in groups.values():
        for group in page_groups:
            # Coverage first within the SAME target; no new geometry is assembled.
            def rank(row):
                evidence = coverage_against_outputs(row, group)['members']
                span = min((e['length_pdf_points'] for e in evidence), default=0)
                return -span, evidence_rank(row)
            best = min(group, key=rank)
            best['target_representative_members'] = [r['sample_id'] for r in group]
            representatives.append(best)
            rejected.extend({'proposal': r['sample_id'], 'outcome': 'rejected',
                             'reason': 'same_target_representative', 'related': best['sample_id'],
                             'coverage': coverage_against_outputs(r, [best])}
                            for r in group if r is not best)
    return representatives, rejected


def compound_carrier_burden(row, outputs, max_crop_iou=.25):
    """An already shown parallel band is burden, not identical target identity.

    Only a finite same-context proxy. Separate ink edges remain separate; an
    automatic third carrier supplies no confirmed node/opening/semantic value.
    """
    if not row.get('display_geometry'):return None
    for old in outputs:
        if not same_source(row,old) or len(old.get('display_geometry',[]))!=2:continue
        if not old.get('source_dpi'):continue  # No pixel-to-paper scale, no band-width evidence.
        a,b=row['display_crop_box'],old['display_crop_box']
        shared=intersect(a,b);area=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-shared
        overlap=shared/area if area else 0
        if overlap<=max_crop_iou:continue
        first,second=old['display_geometry']
        if not line_relation(first,second,tolerance=math.inf,gap=0):continue
        extent=length(first);tx,ty=(first[2]-first[0])/extent,(first[3]-first[1])/extent
        nx,ny=-ty,tx
        def offset(g):return ((g[0]+g[2])/2-first[0])*nx+((g[1]+g[3])/2-first[1])*ny
        band=abs(offset(second))
        radii=[old.get('quality',{}).get('metrics',{}).get(s+'_SUPPORT_RADIUS_PX',1.25)*72/old['source_dpi'] for s in 'AB']
        covered=True;projections=[]
        for g in row['display_geometry']:
            if not line_relation(g,first,tolerance=math.inf,gap=0):covered=False;break
            if not all(b[0]<=g[i]<=b[2] and b[1]<=g[i+1]<=b[3] for i in (0,2)):covered=False;break
            if min(abs(offset(g)),abs(offset(g)-offset(second)))>band+max(radii):covered=False;break
            p=sorted((g[i]-first[0])*tx+(g[i+1]-first[1])*ty for i in (0,2))
            projections.append(max(0,min(extent,p[1])-max(0,p[0]))/max(length(g),1e-9))
        if covered:
            return {'reason':'compound_carrier_incremental_information_unconfirmed',
                    'compared_output':old['sample_id'],'crop_iou':overlap,
                    'parallel_band_pdf_points':band,'common_projection_fractions':projections,
                    'target_entirely_in_shown_crop':True,'same_target_claimed':False,
                    'independent_edge_not_removed':True,'semantic_identity_confirmed':False}
    return None


def selection_difference(row, outputs, config):
    """Revalidate automatic differences; saved proxy evidence cannot bypass burden."""
    supplied=row.get('difficulty_difference')
    if config.get('auto_extra_requires_new_geometry'):
        burden=compound_carrier_burden(row,outputs,config['max_crop_iou'])
        explicit_detail=isinstance(supplied,dict) and supplied.get('kind') in ('gap','node','opening') and supplied.get('evidence')
        if explicit_detail:
            return supplied
        # Geometry/support establishes a nomination, not another object relation.
        # This applies to SINGLE as well as PAIR; automatic carrier IDs and newly
        # exposed hatch/parallel faces cannot manufacture a difficult opportunity.
        row['selection_uncertainty']=burden or {
            'reason':'single_member_relation_unconfirmed' if len(member_map(row))==1
                     else 'source_object_relation_unconfirmed',
            'coverage':coverage_against_outputs(row,outputs),
            'carrier_exposure':burden_coverage(row,outputs),
            'same_target_claimed':False,'independent_edge_not_removed':True,
            'limit':'new source-supported geometry alone has no recorded gap/node/opening judgment value'}
        return None
    return supplied or measured_difference(row,outputs,config['max_crop_iou'],
                            require_new_geometry=config.get('auto_extra_requires_new_geometry',False))


def measured_difference(row, outputs, max_crop_iou=.25, *, require_new_geometry=False):
    """Bounded geometric relation/coverage differences, never semantic labels."""
    metrics = row.get('quality', {}).get('metrics', {})
    members = member_map(row)
    if not members or not row.get('quality', {}).get('HUMAN_QUEUE_ELIGIBLE'):
        return None
    for s in ['A', 'B'][:len(members)]:
        if (metrics.get(s+'_SOURCE_SUPPORT_RATIO', 0) < .9 or
                metrics.get(s+'_EDGE_ATTACHMENT', {}).get('directional_edge_ratio', 0) < .75 or
                metrics.get(s+'_ENDPOINT_SUPPORT', 0) < .9):
            return None
    def overlapping(old):
        a, b = row['display_crop_box'], old['display_crop_box']
        shared = intersect(a, b)
        area = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-shared
        return area > 0 and shared/area > max_crop_iou
    neighbors = [old for old in outputs if same_source(row, old) and
                 (shared_line_occupants(row, [old]) or overlapping(old))]
    if not neighbors or any(same_observed_target(row, old) for old in outputs):
        return None
    new_carriers = []
    if require_new_geometry:
        line_neighbors = [old for old in neighbors if old.get('display_geometry')]
        if not line_neighbors:
            return None  # CONTROL ink alone does not establish another line relation.
        for i, (gid, target) in enumerate(members.items()):
            radius = metrics['AB'[i]+'_SUPPORT_RADIUS_PX'] * 72 / row['source_dpi']
            matches = []
            for old in line_neighbors:
                other_metrics = old.get('quality',{}).get('metrics',{})
                for j, old_line in enumerate(old['display_geometry']):
                    other_radius = other_metrics.get('AB'[j]+'_SUPPORT_RADIUS_PX',1.25) * 72 / old['source_dpi']
                    if line_relation(target, old_line, tolerance=radius+other_radius, gap=math.inf):
                        matches.append(old['sample_id'])
            if not matches:
                new_carriers.append(gid)
        if not new_carriers:
            return None  # More extent on the same carriers is not a new relationship.
    coverage = coverage_against_outputs(row, outputs)
    if coverage['full_target_coverage_fraction'] >= .98:
        return None
    # Only meaningful uncovered measured extent or an unrepresented member relation.
    # Parent/proxy IDs alone neither prove object identity nor complete coverage.
    source_support = min(metrics[s+'_SOURCE_SUPPORT_RATIO'] for s in ['A','B'][:len(members)])
    directional = min(metrics[s+'_EDGE_ATTACHMENT']['directional_edge_ratio'] for s in ['A','B'][:len(members)])
    differences = [f"{old['sample_id']}共有{len(set(members) & set(member_map(old)))}／{len(members)}成员"
                   for old in neighbors]
    observed_relation = (f"两成员间距{metrics.get('PAIR_SEPARATION_STABILITY',{}).get('mean_px',0):.2f}源px、"
                         f"共同投影{metrics.get('PAIR_OVERLAP_LENGTH',0):.1f}源px" if len(members)==2 else
                         '单成员完整范围，与已选成员关系分别记录')
    return {'kind': 'object_relation', 'evidence':
            f"源支持{source_support:.3f}、方向支持{directional:.3f}；{observed_relation}；"
            + '；'.join(differences) +
            f"；成员平均未覆盖{coverage['mean_missing_length_pdf_points']:.2f}纸面点。"
            '仅几何/呈现差异，未确认工程语义，不赋人工类别',
            'coverage': coverage, 'compared_outputs': [old['sample_id'] for old in neighbors],
            'burden_coverage': burden_coverage(row, outputs),
            'difference_basis': 'source_supported_geometrically_distinct_carrier' if require_new_geometry else 'development_full_target_extent_or_member_relation',
            'new_geometric_carrier_members': new_carriers,
            'geometric_carrier_limit': 'non-overlapping normal support bands and direction/collinearity proxy; not building-object recognition',
            'semantic_identity_confirmed': False}
