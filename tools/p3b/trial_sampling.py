"""Explicit PDF page/region nominations for the repair preview, without labels."""

import ctypes
import math
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image

from common import ROOT, read, read_rows
from inventory import build as inventory_build
from measurement import measure_row
from quality import ink_distance, inspect


def device_to_pdf(page, size, point):
    x, y = ctypes.c_double(), ctypes.c_double()
    ok = raw.FPDF_DeviceToPage(page, 0, 0, *size, 0,
                              round(point[0]), round(point[1]),
                              ctypes.byref(x), ctypes.byref(y))
    if not ok:
        raise ValueError("PDF coordinate conversion failed")
    return [x.value, y.value]


def pdf_to_device(page, size, point):
    x, y = ctypes.c_int(), ctypes.c_int()
    ok = raw.FPDF_PageToDevice(page, 0, 0, *size, 0, *point,
                              ctypes.byref(x), ctypes.byref(y))
    if not ok:
        raise ValueError("PDF coordinate conversion failed")
    return [x.value, y.value]


def render_explicit(unit, requested_dpi=110):
    path, number = unit["resolved_path"], unit["page_or_layout"]["page_number"]
    cache = unit.get("source_render_cache")
    if cache:
        saved = read(ROOT/cache["frame"])
        with Image.open(ROOT/cache["image"]) as image:
            gray = np.array(image.convert("L"))
        frame = saved["frame"]
        if (Path(saved["source_path"]).resolve()!=Path(path).resolve()
                or saved["source_page"]!=number
                or [gray.shape[1],gray.shape[0]]!=frame["render_size_px"]):
            raise ValueError("Explicit source cache does not match file/page/frame")
        return gray, frame
    with pdfium.PdfDocument(path) as doc:
        if not 1 <= number <= len(doc):
            raise ValueError(f"Explicit page missing: {path}, page {number}")
        page = doc[number - 1]
        try:
            points = list(page.get_size())
            dpi = min(requested_dpi, 4096 * 72 / max(points))
            bitmap = page.render(scale=dpi / 72, grayscale=True)
            try:
                gray = np.array(bitmap.to_pil().convert("L"))
            finally:
                bitmap.close()
            size = [gray.shape[1], gray.shape[0]]
            # Store the actual PDFium map, including page rotation/cropbox.
            p0 = np.array(device_to_pdf(page, size, [0, 0]))
            px = np.array(device_to_pdf(page, size, [size[0], 0]))
            py = np.array(device_to_pdf(page, size, [0, size[1]]))
            frame = {"page_size_points": points, "render_size_px": size,
                     "effective_dpi": dpi, "page_rotation": page.get_rotation(),
                     "media_box_pdf":list(page.get_mediabox()),"crop_box_pdf":list(page.get_cropbox()),
                     "pdf_origin": p0.tolist(),
                     "pdf_x_per_pixel": ((px-p0)/size[0]).tolist(),
                     "pdf_y_per_pixel": ((py-p0)/size[1]).tolist(),
                     "display_origin": "top-left; page plan display coordinates",
                     "pdf_origin_convention": "PDFium page coordinates; rotation-aware"}
        finally:
            page.close()
    return gray, frame


def to_display(line, frame):
    w, h = frame["render_size_px"]
    pw, ph = frame["page_size_points"]
    return [line[0]*pw/w, line[1]*ph/h, line[2]*pw/w, line[3]*ph/h]


def to_pdf(point, frame):
    return (np.array(frame["pdf_origin"]) + point[0]*np.array(frame["pdf_x_per_pixel"])
            + point[1]*np.array(frame["pdf_y_per_pixel"])).tolist()


def pixel_center_to_pdf(point, frame):
    """LSD/array index centres differ from raster/crop box boundaries by .5."""
    return to_pdf(np.asarray(point)+.5, frame)


def pdf_to_pixel_center(point, frame):
    matrix = np.column_stack((frame["pdf_x_per_pixel"],frame["pdf_y_per_pixel"]))
    return (np.linalg.solve(matrix,np.asarray(point)-frame["pdf_origin"])-.5).tolist()


def intersect(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def line_relation(a, b, tolerance=2.0, gap=8.0):
    """Finite collinear/continuous proxy; does not identify walls or rooms."""
    a, b = np.asarray(a).reshape(2, 2), np.asarray(b).reshape(2, 2)
    da, db = a[1]-a[0], b[1]-b[0]
    la, lb = np.linalg.norm(da), np.linalg.norm(db)
    if min(la, lb) < 1e-6:
        return False
    t = da/la
    if abs(np.dot(t, db/lb)) < math.cos(math.radians(2)):
        return False
    n = np.array([-t[1], t[0]])
    if max(abs((b-a[0]) @ n)) > tolerance:
        return False
    bb = sorted((b-a[0]) @ t)
    return max(0, max(0, bb[0])-min(la, bb[1])) <= gap


def same_target(a, b):
    ga, gb = a.get("display_geometry", []), b.get("display_geometry", [])
    if ga and gb:
        if len(ga) != len(gb):
            return False
        def same_line(x, y):
            if not line_relation(x, y, tolerance=.8, gap=0):
                return False
            x, y = np.asarray(x).reshape(2, 2), np.asarray(y).reshape(2, 2)
            length = np.linalg.norm(x[1]-x[0])
            other_length = np.linalg.norm(y[1]-y[0])
            yy = sorted((y-x[0]) @ ((x[1]-x[0])/length))
            overlap = max(0, min(length, yy[1])-max(0, yy[0]))
            return overlap/min(length, other_length) >= .8
        if len(ga) == 1:
            return same_line(ga[0], gb[0])
        return (same_line(ga[0], gb[0]) and same_line(ga[1], gb[1])) or (
            same_line(ga[0], gb[1]) and same_line(ga[1], gb[0]))
    if not ga and not gb:
        aa, bb = a.get("display_target_box"), b.get("display_target_box")
        if aa is None or bb is None:
            return False
        area = min((aa[2]-aa[0])*(aa[3]-aa[1]), (bb[2]-bb[0])*(bb[3]-bb[1]))
        return bool(area and intersect(aa, bb)/area >= .85)
    return False


def line_groups(lines, frame, cells):
    parents = list(range(len(lines)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    normalized = [to_display(x[1], frame) for x in lines]
    windows = []
    for line in normalized:
        box = [min(line[0],line[2])-1,min(line[1],line[3])-1,
               max(line[0],line[2])+1,max(line[1],line[3])+1]
        windows.append({c["region_id"].rsplit("-",2)[0] for c in cells
                        if intersect(box,c["display_box"])})
    for i, a in enumerate(normalized):
        for j in range(i):
            # Detector splits at symbols/openings must not create fresh quotas.
            # Collinear carriers share a quota within one explicit observation
            # window even across gaps. This is a finite, conservative proxy.
            if windows[i] & windows[j] and line_relation(a, normalized[j], tolerance=1.25, gap=float("inf")):
                parents[find(i)] = find(j)
    return {x[0]: f"line-group-{find(i):05d}" for i, x in enumerate(lines)}


def cells_for(unit, frame):
    """Observation windows constrain search, never supply the output crop."""
    cells = []
    pw, ph = frame["page_size_points"]
    w, h = frame["render_size_px"]
    for i, region in enumerate(unit["regions"]):
        a, b, c, d = region["observation_box_pdf_points_approx"]
        for iy in range(2):
            for ix in range(2):
                box = [a+(c-a)*ix/2, b+(d-b)*iy/2,
                       a+(c-a)*(ix+1)/2, b+(d-b)*(iy+1)/2]
                cells.append({"region_id": f"{unit['plan_unit']}-search-{i+1}-{iy+1}-{ix+1}",
                              "display_box": box,
                              "pixel_box": [box[0]*w/pw, box[1]*h/ph, box[2]*w/pw, box[3]*h/ph],
                              "landmark": region["landmark"],
                              "preferred_kind": ("PAIR", "SINGLE", "CONTROL")[(iy*2+ix)%3]})
    return cells


def spatial_pair_neighbors(lines,distance_px,angle_degrees=None):
    """Finite spatial/angle index only; exact pairing stays inside its budget."""
    from collections import defaultdict
    from extract import PAIR_MAX_ANGLE_DEG
    if angle_degrees is None:angle_degrees=PAIR_MAX_ANGLE_DEG
    bins=defaultdict(set);boxes=[];angles=[]
    angular_count=round(180/angle_degrees)
    def keys(box):
        for y in range(math.floor(box[1]/distance_px),math.floor(box[3]/distance_px)+1):
            for x in range(math.floor(box[0]/distance_px),math.floor(box[2]/distance_px)+1):yield x,y
    for i,g in enumerate(lines):
        x,y,u,v=g[1];box=[min(x,u),min(y,v),max(x,u),max(y,v)]
        angle=math.degrees(math.atan2(v-y,u-x))%180
        boxes.append(box);angles.append(angle);bucket=int(angle//angle_degrees)%angular_count
        for key in keys(box):bins[(bucket,*key)].add(i)
    pairs=set()
    for i,box in enumerate(boxes):
        expanded=[box[0]-distance_px,box[1]-distance_px,box[2]+distance_px,box[3]+distance_px]
        bucket=int(angles[i]//angle_degrees)%angular_count;near=set()
        for offset in (-1,0,1):
            for key in keys(expanded):near.update(bins.get(((bucket+offset)%angular_count,*key),()))
        for j in near:
            if j<=i:continue
            delta=abs((angles[i]-angles[j]+90)%180-90)
            if delta>angle_degrees:continue
            other=boxes[j]
            dx=max(0,box[0]-other[2],other[0]-box[2]);dy=max(0,box[1]-other[3],other[1]-box[3])
            if math.hypot(dx,dy)<=distance_px:pairs.add((i,j))
    return pairs


def regional_nominations(lines, gray, cells, groups, pair_budget=2000, budget_stats=None, *, include_components=True,
                         member_halo_px=0, pair_trace=None, control_context=None):
    """Bound pairing inside predefined regions before shrinking the pool.

    Carriers interleave; no global detector-prefix or full-page all-pairs pool.
    Unchecked comparisons are reported instead of claiming complete coverage.
    An explicit halo retrieves members across cell borders; the nomination
    center still belongs to the unchanged half-open core cell. No geometry
    is extended, joined or averaged. Halo lengths use the input line grid.
    """
    from extract import nominations,PAIR_MAX_SEPARATION_PX
    stats=budget_stats if budget_stats is not None else []
    def canonical(g):
        a,b=sorted((tuple(g[1][:2]),tuple(g[1][2:])))
        return (g[0],list(a+b),g[2])
    # Equivalent endpoints and input permutations must not change pairing.
    lines=sorted((canonical(g) for g in lines),key=lambda g:(tuple(g[1]),g[0]))
    for cell in cells:
        box=cell["pixel_box"]
        retrieval=[box[0]-member_halo_px,box[1]-member_halo_px,
                   box[2]+member_halo_px,box[3]+member_halo_px]
        members=[g for g in lines if intersect(
            [min(g[1][0],g[1][2])-1,min(g[1][1],g[1][3])-1,
             max(g[1][0],g[1][2])+1,max(g[1][1],g[1][3])+1],retrieval)]
        buckets={}
        for g in members: buckets.setdefault(groups[g[0]],[]).append(g)
        group_order=sorted(buckets,key=lambda k:(tuple(buckets[k][0][1]),buckets[k][0][0]))
        ordered=[]
        while any(buckets.values()):
            for key in group_order:
                if buckets[key]: ordered.append(buckets[key].pop(0))
        # Halo mode does not spend the exact-pair budget on remote or
        # incompatible orientations. No support or semantic filters here.
        neighbors=spatial_pair_neighbors(ordered,PAIR_MAX_SEPARATION_PX) if member_halo_px else None
        total=len(neighbors) if neighbors is not None else len(ordered)*(len(ordered)-1)//2
        examined=0
        for offset in range(1,len(ordered)):
            for i in range(len(ordered)-offset):
                if neighbors is not None and (i,i+offset) not in neighbors:continue
                if examined>=pair_budget: break
                examined+=1
                event={'region_id':cell['region_id'],'members':[ordered[i][0],ordered[i+offset][0]],
                       'loose_pair':False,'center_owned':False}
                # Reuse the original loose pair rule on two members. Stop at
                # its single part, before connected-component extraction.
                for proposal in nominations([ordered[i],ordered[i+offset]],gray):
                    if proposal["kind"]!="paired_edges": break
                    cx,cy=proposal["center"]
                    owned=box[0]<=cx<box[2] and box[1]<=cy<box[3]
                    event.update(loose_pair=True,center_owned=owned,center=proposal['center'],features=proposal['features'])
                    if owned: yield proposal
                if pair_trace is not None:pair_trace.append(event)
            if examined>=pair_budget: break
        stats.append({"region_id":cell["region_id"],"pair_comparisons":examined,
                      "unchecked_comparisons":max(0,total-examined),
                      "pair_budget":pair_budget,"complete":examined==total,
                      "member_halo_px":member_halo_px,"member_count":len(members),
                      "raw_member_combinations":len(ordered)*(len(ordered)-1)//2,
                      "spatial_angle_exclusions":len(ordered)*(len(ordered)-1)//2-total,
                      "budget_unit":"exact loose-pair evaluations after spatial/angle index"})
    if include_components:
        yield from (control_context.nominations() if control_context is not None else nominations([],gray))
    for g in lines:
        a=np.asarray(g[1])
        yield {"kind":"single_rule_control","center":((a[:2]+a[2:])/2).tolist(),
               "geometry":[g],"features":{}}


def build_trial_pool(page_plan, supplement):
    if page_plan.get('local_diagnostic_windows'):
        if page_plan.get('purpose')!='development_local_scale_replay':
            raise ValueError('Local redetection is an explicit development diagnostic, not ordinary sampling')
        from local_detection import build_local_trial_pool
        return build_local_trial_pool(page_plan,supplement)
    from extract import lines_from_source, nominations, crop_box
    from prepare_v2 import local_geometry
    from control_targets import ControlContext

    units = inventory_build(page_plan=page_plan, supplement=supplement)
    rows, pages, summaries = [], {}, []
    for unit in units:
        print(f"Reading {unit['plan_unit']} page {unit['page_or_layout']['page_number']}", flush=True)
        gray, frame = render_explicit(unit)
        unit["actual_page_frame"]={"media_box_pdf":frame["media_box_pdf"],"crop_box_pdf":frame["crop_box_pdf"],
                                   "page_rotation_degrees":frame["page_rotation"],
                                   "rotated_display_size_pdf_points":frame["page_size_points"]}
        next(r for r in page_plan["rows"] if r["plan_unit"]==unit["plan_unit"])["actual_page_frame"]=unit["actual_page_frame"]
        cells = cells_for(unit, frame)
        # Detect the full page before any region quota; no detector-prefix cap.
        detected = lines_from_source(gray, limit=None)
        lines = [g for g in detected if any(intersect(
            [min(g[1][0], g[1][2])-1, min(g[1][1], g[1][3])-1,
             max(g[1][0], g[1][2])+1, max(g[1][1], g[1][3])+1], c["pixel_box"])
            for c in cells)]
        groups = line_groups(lines, frame, cells)
        parents = {g[0]: g[1] for g in lines}
        control_context=ControlContext(gray,detected)
        distance = ink_distance(gray)
        counts = Counter()
        nominated_kinds, regional_kinds, passed_kinds = Counter(), Counter(), Counter()
        failed_kinds = {kind: Counter() for kind in ('PAIR', 'SINGLE', 'CONTROL')}
        control_status_counts=Counter()
        quality_examples = []
        region_budget=[]
        references = [{"original_sample_id": r["original_sample_id"],
                       "nominated_before_quality":0,"eligible_after_quality":0,
                       "quality_reasons":Counter()} for r in unit.get("diagnostic_reference_targets", [])]
        for nomination in regional_nominations(lines, gray, cells, groups,
                pair_budget=unit.get("pair_comparison_budget_per_region",2000),budget_stats=region_budget,
                control_context=control_context):
            kind = 'PAIR' if len(nomination['geometry']) == 2 else 'SINGLE' if nomination['geometry'] else 'CONTROL'
            nominated_kinds[kind] += 1
            cx, cy = nomination["center"]
            cell = next((c for c in cells if c["pixel_box"][0] <= cx < c["pixel_box"][2]
                         and c["pixel_box"][1] <= cy < c["pixel_box"][3]), None)
            if cell is None:
                continue
            counts["in_search_cells"] += 1
            regional_kinds[kind] += 1
            geometry = nomination["geometry"]
            geometry = local_geometry(geometry, [cx, cy]) if geometry else []
            roi = nomination.get("ink_bbox") if not geometry else None
            if not geometry and not roi:
                counts["no_defensible_target"] += 1
                continue
            # Crop center follows the finalized target, not the observation window.
            center = np.asarray([g[1] for g in geometry]).reshape(-1, 2).mean(0) if geometry else [roi[0]+roi[2]/2, roi[1]+roi[3]/2]
            bbox = crop_box(gray, center)
            row = {"sample_id": f"proposal-{unit['plan_unit']}-{counts['in_search_cells']:06d}",
                   "plan_unit": unit["plan_unit"], "source_entry_id": unit["source_entry_id"],
                   "source_drawing_id": unit["source_drawing_id"],
                   "source_family_id": unit["source_family_id"], "source_path": unit["resolved_path"],
                   "source_relative_path": unit["relative_path"],
                   "source_page": unit["page_or_layout"]["page_number"],
                   "source_dpi": frame["effective_dpi"], "source_bbox": bbox,
                   "candidate_geometry": geometry, "candidate_geometry_ids": [g[0] for g in geometry],
                   "target_roi": roi, "target_kind": "PAIR" if len(geometry)==2 else "SINGLE" if geometry else "CONTROL",
                   "features": nomination["features"], "label": None, "label_provenance": None,
                   "split": "unassigned_preview", "source_existing_split": unit["source_existing_split"],
                   "container_identity": unit.get("container_identity"),
                   "content_source": unit.get("content_source"),
                   "development_exposure": "repair_preview/dev_accessed; not untouched blind material",
                   "training_authorized": False, "intentional_review": False,
                   "purpose": "repair_preview_only", "region_id": cell["region_id"],
                   "preferred_kind": cell["preferred_kind"], "region_landmark": cell["landmark"],
                   "longline_proxy_ids": sorted({groups[g[0]] for g in geometry}),
                   "longline_proxy_rule": "collinear carrier within one observation window, including disjoint detector segments; not complete physical-structure recognition",
                   "display_geometry": [to_display(g[1], frame) for g in geometry],
                   "display_parent_geometry": [to_display(parents[g[0]], frame) for g in geometry],
                   "display_crop_box": to_display([bbox[0],bbox[1],bbox[0]+bbox[2],bbox[1]+bbox[3]],frame),
                   "display_target_box": to_display([roi[0],roi[1],roi[0]+roi[2],roi[1]+roi[3]],frame) if roi else None,
                   "coordinate_frame": frame,
                   "measurement_status":"not_attempted",
                   "current_p3a_measurement":None,
                   "geometry_semantics":"LSD detected edge-segment proposal; not established centerline/entity truth",
                   "target_extent_basis": nomination.get("target_extent_basis"),
                   "scan_context_exception": unit["plan_unit"] == "TRIAL-06"}
            control_evidence=control_context.assess(roi) if roi else None
            if control_evidence:control_status_counts[control_evidence['status']]+=1
            row["quality"] = inspect(row, gray, distance, require_directional_edge=True,
                                     control_evidence=control_evidence)
            row["proposal_relation"] = ("angle/distance/projected-overlap proposal; source-object relation unconfirmed"
                                       if len(geometry)==2 else "one detected edge, not semantic object truth" if geometry else
                                       "threshold-connected ink extent; may be a fragment or touch adjacent objects")
            # Read-only tracing. These references never choose, move or retain
            # proposals and contain no human labels.
            for reference, status in zip(unit.get("diagnostic_reference_targets", []),references):
                if same_target(row,reference):
                    status["nominated_before_quality"] += 1
                    status["eligible_after_quality"] += int(row["quality"]["HUMAN_QUEUE_ELIGIBLE"])
                    status["quality_reasons"].update(row["quality"]["rejection_reasons"])
            if not row["quality"]["HUMAN_QUEUE_ELIGIBLE"]:
                counts.update(row["quality"]["rejection_reasons"])
                failed_kinds[kind].update(row['quality']['rejection_reasons'])
                if len(quality_examples) < 4:
                    quality_examples.append({'sample_id':row['sample_id'],'target_kind':kind,
                        'candidate_geometry':geometry,'target_roi':roi,'source_bbox':bbox,
                        'reasons':row['quality']['rejection_reasons']})
                continue
            counts["supported_targets"] += 1
            passed_kinds[kind] += 1
            rows.append(row)
        pages[unit["plan_unit"]] = {"gray": gray, "frame": frame, "unit": unit}
        summaries.append({"plan_unit": unit["plan_unit"], "page": unit["page_or_layout"]["page_number"],
                          "full_page_detected_lines": len(detected), "search_intersecting_lines": len(lines),
                          "proposal_counts": dict(counts), "coordinate_frame": frame,
                          "raw_nomination_kind_counts":dict(nominated_kinds),
                          "regional_nomination_kind_counts":dict(regional_kinds),
                          "quality_pass_kind_counts":dict(passed_kinds),
                          "control_validity_counts":dict(control_status_counts),
                          "quality_fail_reasons_by_kind":{k:dict(v) for k,v in failed_kinds.items()},
                          "quality_examples":quality_examples,
                          "region_pair_budget":region_budget,
                          "diagnostic_reference_matches":[{**r,"quality_reasons":dict(r["quality_reasons"])} for r in references],
                          "sampling_regions":cells})
        print(f"  {len(detected)} detected lines; {counts['supported_targets']} supported regional targets", flush=True)
    return rows, pages, summaries


def append_preview_history(history, path, round_name):
    """Read only declared preview metadata, including its retained context frame."""
    if not path.is_file():return
    contexts={};run_path=path.parent/'run.json'
    if run_path.is_file():
        for check in read(run_path).get('preview_checks',{}).get('source_pixel_and_mapping_checks',[]):
            if check.get('context_box_source_px'):contexts[check['proposal']]=check['context_box_source_px']
    for row in read_rows(path):
        if not row.get('display_crop_box'):continue
        old={**row,'round':round_name,'mapping_status':'recorded_source_frame',
             'in_queue':False,'labeled':False,'intentional_review':False,
             'presented':False,'presentation_event_confirmed':False,
             'human_contact_confirmed':False,'formal_label_saved':False,
             'contact_state':'development_preview',
             'contact_basis':'generated preview manifest; no human event inferred',
             'recorded_development_exposure':True}
        box=contexts.get(row['sample_id']);frame=row.get('coordinate_frame')
        if box and frame:
            w,h=frame['render_size_px'];pw,ph=frame['page_size_points']
            old['display_context_box']=[box[0]*pw/w,box[1]*ph/h,box[2]*pw/w,box[3]*ph/h]
            old['context_mapping_basis']='existing preview_checks.context_box_source_px and recorded source frame; no guessed expansion'
        history.append(old)


def load_history(page_plan, sources):
    """Existing presentations/labels/reviews remain separate; do not import labels."""
    aliases = {}
    for unit in sources:
        for sid in unit["existing_source_ids"] + [unit["source_drawing_id"], unit["source_entry_id"]]:
            aliases[sid] = unit["source_drawing_id"]
    frozen = read(ROOT / "docs/product-fix-p3b/FINAL-TRAINING-DATA-FREEZE.json")
    frozen_ids = set(frozen["sample_ids"]["train"])
    history, summary = [], []
    for item in page_plan["history_scope"]:
        manifest = item.get("target_manifest")
        if not manifest or item["round"] == "其他任务Local-D/E2":
            continue
        if not (ROOT/manifest).is_file() or not (ROOT/item["state"]).is_file():
            summary.append({"round":item["round"],"queue_targets":None,
                            "event_uncertainty":"history manifest/state not obtained; not evidence of no previous target"})
            continue
        rows = read_rows(ROOT/manifest)
        state = read(ROOT/item["state"])
        events = state.get("review_log", [])
        presented = {e["sample_id"] for e in events if e.get("action")=="present"}
        saved_labels=state.get('labels',{})
        legacy_answer_events={e['sample_id'] for e in state.get('events',[]) if e.get('new') and e.get('sample_id')}
        formal_round=item['round'] in ('正式','正式复核','验证','验证复核')
        summary.append({"round": item["round"], "queue_targets": len(rows),
                        "presentation_events": sum(e.get("action")=="present" for e in events),
                        "unique_presented_in_events": len(presented), "saved_labels": len(state.get("labels", {})),
                        "intentional_review": "复核" in item["round"],
                        "event_uncertainty": "V1 uses the existing 209 seen-position record; no complete event log" if item["round"]=="V1" else None})
        for outer in rows:
            row = outer.get("original", outer)
            sid = aliases.get(row.get("source_drawing_id"))
            dpi = row.get("source_dpi")
            # Only matched PDF source frames are normalized. Unrelated/blind images are not opened.
            if not sid or not dpi:
                continue
            bbox = row["source_bbox"]
            scale = 72/dpi
            identity=row['sample_id']
            labeled=identity in saved_labels
            formal_label=formal_round and labeled and saved_labels[identity].get('label') in (
                'SINGLE_PHYSICAL_STROKE','TRUE_PARALLEL_STRUCTURE','OTHER','AMBIGUOUS')
            human_contact=identity in presented or identity in legacy_answer_events or labeled
            contact_state=('formal_human_label' if formal_label else 'human_view_or_review'
                           if human_contact else 'legacy_unknown')
            history.append({"source_drawing_id": sid, "source_page": row["source_page"],
                            "sample_id": row.get("original_sample_id", row["sample_id"]),
                            "round": item["round"],
                            "presented": identity in presented,
                            "presentation_event_confirmed":identity in presented,
                            "in_queue": True, "labeled": labeled,
                            "formal_label_saved":formal_label,'human_contact_confirmed':human_contact,
                            "contact_state":contact_state,
                            "contact_basis":('saved formal category' if formal_label else 'recorded present/answer event or saved human answer'
                                             if human_contact else 'legacy queue/seen-position only; no per-target event confirmed'),
                            "annotation_scope":'formal_p3b' if formal_round else 'ui_acceptance' if item['round']=='V2验收' else 'legacy_unverified',
                            "intentional_review": human_contact and "复核" in item["round"],
                            "frozen_training_input": row["sample_id"] in frozen_ids,
                            "mapping_status":"recorded_dpi",
                            "mapping_basis":"existing PDF source alias and recorded raster DPI; no new registration",
                            "display_geometry": [[v*scale for v in g[1]] for g in row.get("candidate_geometry", [])],
                            "display_crop_box": [bbox[0]*scale,bbox[1]*scale,(bbox[0]+bbox[2])*scale,(bbox[1]+bbox[3])*scale],
                            "display_target_box": [v*scale for v in [row["target_roi"][0],row["target_roi"][1],row["target_roi"][0]+row["target_roi"][2],row["target_roi"][1]+row["target_roi"][3]]] if row.get("target_roi") else None})
    for unit in sources:
        for old in unit["history"]["other_task_targets_and_context"]:
            review_path=ROOT/'local-artifacts/draftsman/user-supplied-human-review-v2-local-e2/review-state.json'
            review_item=read(review_path).get('items',{}).get(old['target_id'],{}) if review_path.is_file() else {}
            reviewed=review_item.get('review_status')=='REVIEWED' and bool(review_item.get('updated_at'))
            w,h = old["render_frame_px"]
            pw,ph = unit["page_or_layout"]["page_size_points"]
            frame=unit.get("actual_page_frame",{})
            image_path=ROOT/old["render_path"]
            recorded_size_matches=False
            if image_path.is_file():
                with Image.open(image_path) as im:
                    recorded_size_matches=list(im.size)==[w,h]
            boxes=frame.get("media_box_pdf"),frame.get("crop_box_pdf")
            verified=(recorded_size_matches and boxes[0] and boxes[0]==boxes[1]
                      and boxes[0][:2]==[0.0,0.0]
                      and np.allclose(frame.get("rotated_display_size_pdf_points",[]),[pw,ph])
                      and abs(w/h-pw/ph)<.002)
            def box_from_old(key):
                a,b,c,d=old[key]  # This existing schema is xyxy, not xywh.
                return [a*pw/w,b*ph/h,c*pw/w,d*ph/h]
            geometry = [old["target_geometry"][k] for k in ("a","b")]
            history.append({"source_drawing_id":unit["source_drawing_id"],
                            "source_page":unit["page_or_layout"]["page_number"],
                            "sample_id":old["target_id"], "round":"Local-D/E2", "presented":False,
                            "labeled":False,"other_task_answer_saved":bool(review_item.get('human_label')),
                            "intentional_review":reviewed,'human_contact_confirmed':reviewed,
                            'formal_label_saved':False,'annotation_scope':'other_task',
                            'contact_state':'human_view_or_review' if reviewed else 'legacy_unknown',
                            'contact_basis':'saved E2 review item' if reviewed else 'old review metadata without obtained per-target review evidence',
                            "frozen_training_input":False,
                            "mapping_status":"verified_render_frame_rounding_limited" if verified else "unknown",
                            "mapping_basis":{"old_render_size_px":[w,h],"old_render_header_verified":bool(recorded_size_matches),
                                "current_media_crop_rotation_checked":bool(verified),
                                "legacy_renderer":"retained Local-D run_mining.py: pdftoppm -scale-to 2600, rotated MediaBox, no cropbox flag",
                                "precision_limit":"integer raster rounding; no geometric registration; unverified frames stay unknown"},
                            "display_geometry":[[g["start"][0]*pw/w,g["start"][1]*ph/h,g["end"][0]*pw/w,g["end"][1]*ph/h] for g in geometry],
                            "display_crop_box":box_from_old("local_box_xyxy"),
                            "display_context_box":box_from_old("context_box_xyxy"), "display_target_box":None})
    for entry in page_plan.get('preview_history_manifests',[]):
        count=len(history)
        append_preview_history(history,ROOT/entry['manifest'],entry['round'])
        summary.append({'round':entry['round'],'recorded_preview_positions':len(history)-count,
                        'presentation_events':None,'saved_labels':None,'intentional_review':False,
                        'event_uncertainty':'preview exposure metadata; no user click/answer events inferred'})
    return history, summary
