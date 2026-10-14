"""Separate exact target identity from region/long-line annotation burden."""

from collections import Counter, defaultdict, deque

from trial_sampling import intersect, line_relation, same_target
from selection_targets import (burden_coverage, choose_representatives, coverage_against_outputs,
                              evidence_rank, same_observed_target,
                              selection_difference, shared_line_occupants)

DEFAULT = {"max_total": 30, "max_page": 4, "max_design": 8,
           "max_region": 1, "max_shared_line": 1, "max_crop_iou": .25,
           "max_control_page": 1, "scan_page_cap": 1, "max_difficult_page":1,
           "auto_extra_requires_new_geometry":True}


def same_page(a, b):
    return a["source_drawing_id"] == b["source_drawing_id"] and a["source_page"] == b["source_page"]


def iou(a, b):
    shared = intersect(a, b)
    area = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-shared
    return shared/area if area else 0


def contact_state(old):
    if old.get('contact_state'):
        return old['contact_state']
    if old.get('recorded_development_exposure'):
        return 'development_preview'
    if old.get('formal_label_saved'):
        return 'formal_human_label'
    if old.get('human_contact_confirmed') or old.get('presentation_event_confirmed'):
        return 'human_view_or_review'
    return 'legacy_unknown'


def history_spatial_relation(row, old):
    shared=reuse_conflict(row,old)
    if shared:return shared
    if not same_page(row,old):return None
    if old.get('mapping_status')=='unknown':return 'mapping_unknown'
    if same_target(row,old):return 'same_target'
    if any(line_relation(a,b,tolerance=1.25,gap=6)
           for a in row.get('display_parent_geometry',[]) for b in old.get('display_geometry',[])):
        return 'shared_continuous_line'
    crop=row['display_crop_box']
    if iou(crop,old['display_crop_box'])>.25:return 'local_region'
    context=old.get('display_context_box')
    area=(crop[2]-crop[0])*(crop[3]-crop[1])
    if context and area and intersect(crop,context)/area>.5:return 'context_region'
    return None


def preview_exposure_priority(row, history):
    # A generated preview can guide exploration, never bar future annotation.
    return int(any(contact_state(old)=='development_preview' and history_spatial_relation(row,old)
                   for old in history))


def history_relation(row, history):
    """Hard exclusion needs human contact; previews/unknown records are notes."""
    notes = []
    for old in history:
        relation=history_spatial_relation(row,old)
        if not relation:continue
        state=contact_state(old)
        if relation=='mapping_unknown' or state=='legacy_unknown':
            notes.append({"related_target":old["sample_id"],"relation":"history_mapping_unknown",
                          'contact_state':state,
                          "retain_reason":"旧记录接触状态或映射未确认；不推断从未看过，不作硬排除"})
            continue
        if state=='development_preview':
            notes.append({'related_target':old['sample_id'],'relation':'development_preview_'+relation,
                          'contact_state':state,'retain_reason':'开发预览仅降低探索优先级；未确认人工查看或正式类别'})
            continue
        if relation=='context_region' and row.get('relation_difference_evidence'):
            notes.append({'related_target':old['sample_id'],'relation':'previous_context_overlap_different_target',
                          'contact_state':state,'retain_reason':row['relation_difference_evidence']})
            continue
        return 'historical_'+relation,old['sample_id'],notes
    return None, None, notes


def reuse_conflict(row, old):
    """Known content/base relations constrain exposure, not actual geometry."""
    if same_page(row,old): return None
    content=row.get("content_source") or {}
    other=old.get("content_source") or {}
    if content.get("content_id") and content["content_id"]==other.get("content_id"):
        region,other_region=row.get("reuse_region_key"),old.get("reuse_region_key")
        if not region or not other_region or region==other_region:
            return "shared_standard_content_region"
    base=content.get("shared_base_group")
    if base and base==other.get("shared_base_group"):
        if row.get("professional_difference_evidence") or old.get("professional_difference_evidence"):
            return None
        region,other_region=content.get("logical_base_region"),other.get("logical_base_region")
        if not region or not other_region or region==other_region:
            return "shared_base_region"
    return None


def select_preview(rows, history, config=None):
    config = {**DEFAULT, **(config or {})}
    input_rows = rows
    control_holds=[]
    if config.get('require_control_validity'):
        assessed=[]
        for row in rows:
            evidence=row.get('quality',{}).get('control_object_evidence')
            if row['target_kind']=='CONTROL' and (not evidence or not evidence.get('queue_eligible')):
                control_holds.append({'proposal':row['sample_id'],'outcome':'rejected',
                    'reason':'control_'+(evidence['status'] if evidence else 'unassessed'),
                    'deferred':True,'label':None})
            else:assessed.append(row)
        rows=assessed
    rows, representative_decisions = choose_representatives(rows)
    representative_decisions += control_holds
    exposure_priority={r['sample_id']:preview_exposure_priority(r,history) for r in rows}
    def priority(row):return exposure_priority[row['sample_id']]
    buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        buckets[row["source_family_id"]][row["plan_unit"]][row["region_id"]].append(row)
    pages, page_rotation = {}, {}
    for family, units in buckets.items():
        page_rotation[family] = deque(sorted(units))
        for page, regions in units.items():
            pages[page] = deque()
            for region, candidates in sorted(regions.items()):
                # The existing planned kind rotation keeps CONTROL opportunities.
                # Within that slot, evidence replaces detector/sample-ID order.
                candidates.sort(key=lambda r:(priority(r),
                                              r["target_kind"] != r["preferred_kind"], evidence_rank(r)))
                pages[page].append(deque(candidates))
    selected, details, counts = [], [], Counter()
    decisions=list(representative_decisions) if config.get('record_decisions') else None
    page_rejections=defaultdict(Counter)
    difficult_count=Counter()
    page_count, family_count, control_count = Counter(), Counter(), Counter()
    region_count = Counter()
    window_count, last_window = Counter(), {}
    def window(row):
        return row.get('observation_window_id') or row['region_id'].rsplit('-',2)[0]
    pending_differences = []
    for decision in representative_decisions:
        counts[decision['reason']] += 1
        row = next(r for r in input_rows if r['sample_id'] == decision['proposal'])
        page_rejections[row['plan_unit']][decision['reason']] += 1
    active = deque(sorted(page_rotation))
    while active and len(selected)<config["max_total"]:
        family = active.popleft()
        units = page_rotation[family]
        found = False
        for _ in range(len(units)):
            page = units.popleft()
            units.append(page)
            regions = pages[page]
            if config.get('page_window_kind_rotation') and regions:
                wanted = ('PAIR','SINGLE','CONTROL')[page_count[page] % 3]
                # Rotate whole observation windows before their subcells. A first
                # window's four cells must not exhaust the page's three slots.
                regions = deque(sorted(regions, key=lambda q:(
                    min(priority(r) for r in q),
                    window_count[(page,window(q[0]))], window(q[0]) == last_window.get(page),
                    not any(r['target_kind']==wanted for r in q), q[0]['region_id'])))
                regions = deque(deque(sorted(q,key=lambda r:(priority(r),
                                                            r['target_kind']!=wanted,evidence_rank(r)))) for q in regions)
                pages[page] = regions
            while regions:
                candidates = regions.popleft()
                while candidates:
                    row = candidates.popleft()
                    line_occupants = shared_line_occupants(row, selected)
                    cap = config["scan_page_cap"] if row.get("scan_context_exception") else config["max_page"]
                    reason, related = None, None
                    # Target identity is independent of quota rejection order.
                    reason, related, notes = history_relation(row, history)
                    if reason is None:
                        for old in selected:
                            if same_observed_target(row,old):
                                reason,related="same_target",old["sample_id"]
                                break
                    if reason is None and row.get("scan_context_exception") and not row.get("relation_difference_evidence"):
                        reason="scan_relation_difference_missing"
                    if reason is None and (page_count[page]>=cap or family_count[family]>=config["max_design"]):
                        reason = "page_or_design_cap"
                    elif reason is None and region_count[row["region_id"]]>=config["max_region"]:
                        reason = "region_cap"
                    elif reason is None and row["target_kind"]=="CONTROL" and control_count[page]>=config["max_control_page"]:
                        reason = "component_target_page_cap"
                    elif reason is None and any(len(ids)>=config["max_shared_line"] for ids in line_occupants.values()):
                        reason = "shared_line_cap"
                    if reason is None:
                        for old in selected:
                            reused=reuse_conflict(row,old)
                            if reused:
                                reason,related=reused,old["sample_id"]
                                break
                            if not same_page(row, old):
                                continue
                            if same_observed_target(row, old):
                                reason, related = "same_target", old["sample_id"]
                                break
                            if iou(row["display_crop_box"],old["display_crop_box"])>config["max_crop_iou"]:
                                reason, related = "cross_kind_region_occupancy", old["sample_id"]
                                break
                    difficulty=selection_difference(row,selected,config)
                    if (reason in ("region_cap","shared_line_cap","cross_kind_region_occupancy","shared_base_region","page_or_design_cap")
                            and isinstance(difficulty,dict) and difficulty.get("kind") in ("gap","node","opening","object_relation")
                            and difficulty.get("evidence") and difficult_count[page]<config["max_difficult_page"]
                            and not row.get("scan_context_exception")
                            and not any(same_observed_target(row,old) for old in selected)
                            and history_relation(row,history)[0] is None):
                        # Extra opportunities compete after ordinary page/region rotation.
                        # A detector's earlier blocked nomination cannot take the extra slot.
                        pending_differences.append((row, difficulty, notes, reason))
                    if reason:
                        if decisions is not None:
                            blockers=[old['sample_id'] for old in selected if
                                (reason=='shared_line_cap' and any(old['sample_id'] in ids for ids in line_occupants.values())) or
                                (reason=='region_cap' and old['region_id']==row['region_id']) or
                                (reason=='page_or_design_cap' and
                                 (page_count[page]>=cap and old['plan_unit']==page or
                                  family_count[family]>=config['max_design'] and old['source_family_id']==family))]
                            decisions.append({'proposal':row['sample_id'],'reason':reason,
                                'related':related,'quota_occupants':blockers,'outcome':'rejected',
                                'coverage':coverage_against_outputs(row, selected),
                                'carrier_exposure':burden_coverage(row, selected),
                                'burden_is_not_target_equivalence': reason in ('shared_line_cap','cross_kind_region_occupancy','region_cap','page_or_design_cap')})
                            if row.get('selection_uncertainty'):
                                decisions[-1]['information_uncertainty']=row['selection_uncertainty']
                        counts[reason] += 1
                        page_rejections[page][reason]+=1
                        # Count all decisions; retain only a few examples, not a new audit pack.
                        if len(details)<20:
                            details.append({"proposal":row["sample_id"],"reason":reason,"related":related})
                        continue
                    row["historical_relations"] = notes
                    row["retain_reasons"] = [
                        "显式选页；目标在计划观察范围内，裁框由最终目标确定",
                        "源图支持及端点检查合格；来源/页/区域轮转",
                        "同目标、已证实人工接触及当前区域/连续长线名额检查后保留",
                        f"观察位置：{row.get('region_landmark', row['region_id'])}；占用区域 {row['region_id']}",
                    ] + [n["retain_reason"] for n in notes]
                    if row["target_kind"]=="PAIR":
                        metrics=row["quality"]["metrics"]
                        row["retain_reasons"].append(
                            f"保留两提名线的关系差异：间距 {metrics.get('PAIR_SEPARATION_STABILITY',{}).get('mean_px',0):.2f}px、共同投影 {metrics.get('PAIR_OVERLAP_LENGTH',0):.1f}px；不据此赋人工类别")
                    elif row["target_kind"]=="SINGLE":
                        row["retain_reasons"].append("一个有源图支持的线目标；同载体其他局部段共享名额，人工类别未定")
                    else:
                        row["retain_reasons"].append("框出连通墨迹候选；完整字符/符号及对象归属仍未确认")
                    selected.append(row)
                    if config.get('page_window_kind_rotation'):
                        row['observation_window_id'] = window(row)
                        window_count[(page,window(row))] += 1
                        last_window[page] = window(row)
                    if decisions is not None:decisions.append({'proposal':row['sample_id'],'outcome':'selected'})
                    if row.get("difficult_addition"):
                        difficult_count[page]+=1
                    else:
                        page_count[page]+=1
                        family_count[family]+=1
                    region_count[row["region_id"]]+=1
                    if row["target_kind"]=="CONTROL":
                        control_count[page]+=1
                    found=True
                    break
                if found:
                    if candidates:
                        regions.append(candidates)
                    break
            if found:
                break
        if found:
            active.append(family)
    # Re-evaluate marginal coverage against the complete ordinary set. Do not fill gaps.
    while pending_differences:
        best = min(range(len(pending_differences)), key=lambda i:(
            -burden_coverage(pending_differences[i][0], selected)['mean_missing_length_pdf_points'],
            evidence_rank(pending_differences[i][0])))
        row, difficulty, notes, original_reason = pending_differences.pop(best)
        page = row['plan_unit']
        if (len(selected) >= config['max_total'] or difficult_count[page] >= config['max_difficult_page']
                or row['target_kind'] == 'CONTROL' and control_count[page] >= config['max_control_page']
                or any(same_observed_target(row, old) for old in selected)
                or any(reuse_conflict(row, old) == 'shared_standard_content_region' for old in selected)):
            continue
        current=selection_difference(row,selected,config)
        if not current:
            continue
        coverage = coverage_against_outputs(row, selected)
        row['difficult_addition'] = True
        row['difficulty_difference'] = current
        row['selection_coverage_before_addition'] = coverage
        row['historical_relations'] = notes
        row['retain_reasons'] = ['普通名额完成后，按实际未覆盖区间选择有界困难差异', current['evidence']]
        selected.append(row)
        difficult_count[page] += 1
        region_count[row['region_id']] += 1
        if row['target_kind'] == 'CONTROL': control_count[page] += 1
        if decisions is not None:
            decision = next(d for d in decisions if d['proposal'] == row['sample_id'])
            decision.pop('reason')
            decision.update(outcome='selected_difficult', ordinary_rejection=original_reason,
                            coverage_before_addition=coverage)
        counts[original_reason] -= 1
        page_rejections[page][original_reason] -= 1
        details[:] = [d for d in details if d['proposal'] != row['sample_id']]
    unchecked={page:sum(len(candidates) for candidates in regions) for page,regions in pages.items()}
    result=(selected, details, {"decision_counts":dict(counts), "selected_per_page":dict(Counter(r["plan_unit"] for r in selected)),
                               "ordinary_selected_per_page":dict(page_count),
                               "selected_per_design":dict(family_count), "configuration":config,
                               "candidate_kind_counts":dict(Counter(r["target_kind"] for r in selected)),
                               "selected_difficult_per_page":dict(difficult_count),
                               "primary_rejections_per_page":{p:dict(v) for p,v in page_rejections.items()},
                               "unexamined_after_total_cap_per_page":{p:n for p,n in unchecked.items() if n},
                               "rejection_counting":"one first-hit rejection per proposal; nonexclusive quality flags are separate",
                               "labels_assigned":0, "intentional_reviews_in_new_batch":0})
    result[2]['representative_pool_per_page'] = dict(Counter(r['plan_unit'] for r in rows))
    result[2]['representative_rule'] = 'full source-bound unordered member set + source-pixel geometry, or exactly equal source geometry across IDs; completeness then source evidence, no label or sample-ID ranking'
    result[2]['coverage_unit'] = 'PDF display paper points; interval union with gaps retained; not architectural millimetres'
    if decisions is not None:
        visited={d['proposal'] for d in decisions}
        decisions.extend({'proposal':r['sample_id'],'outcome':'unexamined_total_cap'} for r in input_rows if r['sample_id'] not in visited)
        by_id = {r['sample_id']: r for r in input_rows}
        for decision in decisions:
            if decision['outcome'] == 'rejected':
                row = by_id[decision['proposal']]
                decision['coverage_against_final_outputs'] = coverage_against_outputs(row, selected)
                decision['carrier_exposure_against_final_outputs'] = burden_coverage(row, selected)
                if decision.get('burden_is_not_target_equivalence'):
                    decision['difference_not_retained'] = (
                        'total_cap' if len(selected) >= config['max_total'] else
                        'difficult_page_cap' if difficult_count[row['plan_unit']] >= config['max_difficult_page'] else
                        'no_sufficient_difference_evidence')
        result[2]['decisions']=decisions
    return result


def select_preview_mode(rows,history,config=None,*,mode='new_information'):
    """Normal exploration distinguishes human contact from generated previews."""
    if mode not in ('new_information','development_replay'):raise ValueError('Unknown preview exposure mode')
    if mode=='development_replay' and any(r.get('purpose') not in ('development_local_scale_replay','development_candidate_replay') for r in rows):
        raise ValueError('Replay mode requires diagnostic-only proposals')
    config = dict(config or {})
    # Full-extent diagnostics may use geometric differences. Normal selection
    # needs recorded judgment value; development exposure remains a soft hint.
    config.setdefault('auto_extra_requires_new_geometry',mode=='new_information')
    config.setdefault('page_window_kind_rotation',mode=='new_information')
    config.setdefault('require_control_validity',mode=='new_information')
    result=select_preview(rows,history if mode=='new_information' else [],config)
    result[2]['exposure_mode']=mode
    result[2]['historical_exclusion_applied']=mode=='new_information'
    result[2]['history_contact_counts']=dict(Counter(contact_state(old) for old in history))
    result[2]['history_policy']='human contact hard exclusion; development preview soft exploration priority; unknown records noted; no labels imported'
    result[2]['automatic_geometry_only_extra_allowed']=not config['auto_extra_requires_new_geometry']
    result[2]['new_information_claimed']=False if mode=='development_replay' else None
    return result
