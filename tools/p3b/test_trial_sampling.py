"""Local regressions for target/history identity, line caps and shared measurement."""

import copy
import unittest
from unittest.mock import patch

import numpy as np

from measurement import measure_row, SourceWindow
from preview_selection import history_relation, select_preview
from trial_sampling import same_target, line_groups, regional_nominations


def candidate(identity, kind="SINGLE", x=0, line_group="long-1", region=None):
    geometry = [[x,0,x+80,0]]
    if kind=="PAIR":
        geometry.append([x,8,x+80,8])
    return {"sample_id":identity,"source_drawing_id":"drawing","source_page":7,
            "source_family_id":"design","plan_unit":"TRIAL-01",
            "region_id":region or identity,"target_kind":kind,"preferred_kind":kind,
            "longline_proxy_ids":[line_group],"display_geometry":geometry,
            "display_parent_geometry":geometry,"display_crop_box":[x-20,-20,x+100,100],
            "display_target_box":None,"quality":{"metrics":{}},"scan_context_exception":False}


class TrialSamplingTests(unittest.TestCase):
    def test_new_id_and_shortening_do_not_make_a_new_target(self):
        old = candidate("old")
        new = candidate("new")
        new["display_geometry"]=[[20,0,60,0]]
        self.assertTrue(same_target(new,old))
        old["intentional_review"]=True
        old['human_contact_confirmed']=True
        old["round"]="formal re-review"
        self.assertEqual(history_relation(new,[old])[0],"historical_same_target")

    def test_changed_pair_gap_is_different_target_but_region_is_occupied(self):
        first = candidate("one",kind="PAIR")
        second = candidate("two",kind="PAIR",line_group="other")
        second["display_geometry"][1]=[0,18,80,18]
        self.assertFalse(same_target(first,second))
        rows,_,counts = select_preview([first,second],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["cross_kind_region_occupancy"],1)

    def test_cross_kind_region_occupancy(self):
        first = candidate("one",kind="PAIR")
        second = candidate("two",kind="SINGLE",x=20,line_group="other")
        rows,_,counts = select_preview([first,second],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["cross_kind_region_occupancy"],1)

    def test_disjoint_segments_share_the_long_line_quota(self):
        first = candidate("one",kind="PAIR")
        second = candidate("two",kind="SINGLE",x=500)
        rows,_,counts = select_preview([first,second],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["shared_line_cap"],1)

    def test_detector_gap_does_not_split_an_observation_window_carrier(self):
        lines=[("A",[50,0,50,100],"test"),("B",[50,180,50,260],"test"),
               ("C",[80,0,80,100],"test")]
        frame={"render_size_px":[500,500],"page_size_points":[500,500]}
        cells=[{"region_id":"TRIAL-01-search-1-1-1","display_box":[0,0,250,500]}]
        groups=line_groups(lines,frame,cells)
        self.assertEqual(groups["A"],groups["B"])
        self.assertNotEqual(groups["A"],groups["C"])

    def test_seen_context_requires_an_explicit_retention_reason(self):
        row = candidate("new",x=500)
        old = candidate("old",x=0)
        old['human_contact_confirmed']=True
        old["display_context_box"]=[0,-100,900,200]
        self.assertEqual(history_relation(row,[old])[0],"historical_context_region")
        row["scan_context_exception"]=True
        self.assertEqual(history_relation(row,[old])[0],"historical_context_region")
        row["relation_difference_evidence"]="新增开口节点与旧长线关系不同"
        reason,_,notes = history_relation(row,[old])
        self.assertIsNone(reason)
        self.assertEqual(notes[0]["relation"],"previous_context_overlap_different_target")

    def test_train_validation_share_final_target_measurement_and_missing_reasons(self):
        gray = np.full((256,256),255,dtype=np.uint8)
        gray[63:66,10:200]=0
        row={"candidate_geometry":[["A",[20,64,180,64],"test"]],"source_dpi":110}
        train=measure_row({**copy.deepcopy(row),"split":"train"},gray)
        validation=measure_row({**copy.deepcopy(row),"split":"validation"},gray)
        self.assertEqual(train["current_p3a_measurement"],validation["current_p3a_measurement"])
        self.assertEqual(train["measurement_status"],"measured")
        short=measure_row({"candidate_geometry":[["A",[20,64,24,64],"test"]]},gray)
        self.assertEqual(short["current_p3a_measurement"][0]["missing_reason"],"target_length_below_8px")
        roi=measure_row({"candidate_geometry":[]},gray)
        self.assertEqual(roi["measurement_missing_reason"],"target_has_no_line_geometry")

    def test_train_validation_explicit_plan_dispatch_to_the_same_pool(self):
        from prepare_v2 import build_pool
        from validation_v2 import candidates
        plan,supplement={"rows":[]},{"rows":[]}
        expected=object()
        with patch("trial_sampling.build_trial_pool",return_value=expected) as shared:
            self.assertIs(build_pool(page_plan=plan,supplement=supplement),expected)
            self.assertIs(candidates(page_plan=plan,supplement=supplement),expected)
        self.assertEqual(shared.call_count,2)
        self.assertEqual(shared.call_args_list[0],shared.call_args_list[1])

    def test_shared_base_and_standard_content_are_separate_from_container(self):
        first=candidate("one")
        second=candidate("two",x=500,line_group="other")
        second.update(source_drawing_id="another-file",plan_unit="TRIAL-05",source_page=6)
        for row in (first,second):
            row["content_source"]={"shared_base_group":"floor4","logical_base_region":"grid-B"}
        rows,_,counts=select_preview([first,second],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["shared_base_region"],1)
        second["professional_difference_evidence"]="支管与轴线的新增邻接关系"
        self.assertEqual(len(select_preview([first,second],[],{})[0]),2)
        for row in (first,second):
            row["content_source"]={"content_id":"20S206/page16"}
        second.pop("professional_difference_evidence")
        rows,_,counts=select_preview([first,second],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["shared_standard_content_region"],1)
        first['human_contact_confirmed']=True
        self.assertEqual(history_relation(second,[first])[0],"historical_shared_standard_content_region")
        # Original engineering pages in the two packages are not merged.
        for row in (first,second): row["content_source"]={"kind":"engineering_page"}
        self.assertEqual(len(select_preview([first,second],[],{})[0]),2)

    def test_development_preview_and_unknown_history_do_not_ban_annotation(self):
        from preview_selection import preview_exposure_priority
        row=candidate('new')
        for state in ('development_preview','legacy_unknown','human_view_or_review','formal_human_label'):
            old={**candidate('old'),'contact_state':state}
            reason,_,notes=history_relation(row,[old])
            if state in ('human_view_or_review','formal_human_label'):
                self.assertEqual(reason,'historical_same_target')
            else:
                self.assertIsNone(reason)
                self.assertEqual(notes[0]['contact_state'],state)
            self.assertEqual(preview_exposure_priority(row,[old]),int(state=='development_preview'))
        old={**candidate('old'),'contact_state':'development_preview'}
        # Previewed target remains selectable when it is the available nomination.
        chosen,_,_=select_preview([row],[old],{'max_difficult_page':0})
        self.assertEqual(chosen[0]['sample_id'],'new')

    def test_one_difficult_addition_does_not_bypass_target_identity(self):
        first=candidate("one")
        second=candidate("two",x=500)
        third=candidate("three",x=1000)
        for row in (second,third):
            row["difficulty_difference"]={"kind":"opening","evidence":"同载体另一门洞节点关系"}
        rows,_,counts=select_preview([first,second,third],[],{"max_page":1})
        self.assertEqual(len(rows),2)
        self.assertEqual(counts["selected_difficult_per_page"]["TRIAL-01"],1)
        duplicate=candidate("two")
        duplicate["difficulty_difference"]={"kind":"gap","evidence":"不能凭改ID保留"}
        rows,_,counts=select_preview([first,duplicate],[],{})
        self.assertEqual(len(rows),1)
        self.assertEqual(counts["decision_counts"]["same_target_representative"],1)

    def test_region_pair_budget_reports_unchecked_comparisons(self):
        gray=np.full((128,128),255,np.uint8)
        lines=[(str(i),[10,y,110,y],"test") for i,y in enumerate((10,20,30,40))]
        cells=[{"region_id":"fixed-before-detection","pixel_box":[0,0,128,128]}]
        stats=[]
        proposals=list(regional_nominations(lines,gray,cells,{g[0]:g[0] for g in lines},pair_budget=2,budget_stats=stats))
        self.assertEqual(stats[0]["pair_comparisons"],2)
        self.assertEqual(stats[0]["unchecked_comparisons"],4)
        self.assertFalse(stats[0]["complete"])
        self.assertEqual(sum(p["kind"]=="paired_edges" for p in proposals),2)

    def test_final_pair_measurement_is_invariant_to_member_and_endpoint_order(self):
        from prepare_v2 import measure_trial_targets as train_measure
        from validation_v2 import measure_trial_targets as validation_measure
        gray=np.full((1800,1800),255,np.uint8)
        gray[1099:1102,1000:1250]=0
        gray[1118:1123,1000:1250]=0
        row={"sample_id":"pair","source_dpi":110,
             "candidate_geometry":[["top",[1010,1100,1240,1100],"test"],["bottom",[1010,1120,1240,1120],"test"]]}
        windows={"pair":(gray[950:1462,950:1462],(950,950),(1800,1800))}
        a=train_measure([row],windows)[0]
        b=validation_measure([row],windows)[0]
        self.assertEqual(a["current_p3a_measurement"],b["current_p3a_measurement"])
        full=measure_row(copy.deepcopy(row),gray)
        self.assertEqual(a["current_p3a_measurement"],full["current_p3a_measurement"])
        reversed_row=copy.deepcopy(row)
        reversed_row["candidate_geometry"]=[[g[0],g[1][2:]+g[1][:2],g[2]] for g in reversed(row["candidate_geometry"])]
        c=train_measure([reversed_row],windows)[0]
        canonical=lambda r:[{k:v for k,v in m.items() if k!="display_member"} for m in r["current_p3a_measurement"]]
        self.assertEqual(canonical(a),canonical(c))
        self.assertEqual(a["feature_profile_geometry_id"],c["feature_profile_geometry_id"])
        self.assertTrue(all(m["profile_status"]=="measured" for m in a["current_p3a_measurement"]))

    def test_missing_source_window_is_a_read_error_not_measured_zero(self):
        gray=np.full((100,100),255,np.uint8)
        row=measure_row({"candidate_geometry":[["outside",[1000,1100,1200,1100],"test"]]},
                        SourceWindow(gray,(0,0),(1800,1800)))
        self.assertEqual(row["measurement_status"],"read_or_coordinate_error")
        self.assertIsNone(row["current_p3a_measurement"][0]["profile"])

    def test_protected_association_skips_without_opening_the_file(self):
        from inventory import planned_sources
        plan={"rows":[{"plan_unit":"skip","source_entry_id":"protected","page_or_layout":{"type":"PDF"}}]}
        supplement={"materials_root":"D:/programs/Image-to-CAD/materials/新建文件夹",
                    "rows":[{"entry_id":"protected","role":"原始PDF","p3b_mapping":{"split":"validation"}}]}
        self.assertEqual(planned_sources(plan,supplement),[])
        self.assertIn("unopened",plan["rows"][0]["preview_skip_reason"])


if __name__=="__main__":
    unittest.main()
