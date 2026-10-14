"""Bounded local pairing regressions; no labels, models or source edits."""

import copy
import unittest

import numpy as np
from PIL import Image

from common import ROOT,read
from extract import lines_from_source,PAIR_MAX_SEPARATION_PX
from local_detection import partition_native_fragments
from prepare_v2 import local_geometry
from quality import inspect
from queue_dedup import deduplicate
from test_trial_sampling import candidate
from trial_sampling import regional_nominations,line_groups


def paired(lines,gray,cells,groups,halo):
    return [p for p in regional_nominations(lines,gray,cells,groups,
        include_components=False,member_halo_px=halo) if p['kind']=='paired_edges']


class LocalLifecycleTests(unittest.TestCase):
    def fixture(self):
        gray=np.full((200,240),255,np.uint8)
        gray[60:63,10:230]=0;gray[85:88,10:230]=0
        gray[20:63,70:73]=0;gray[20:63,150:153]=0
        lines=[('upper',[10,60,230,60],'test'),('lower',[10,85,230,85],'test')]
        cells=[{'region_id':'top','pixel_box':[0,0,240,72]},
               {'region_id':'bottom','pixel_box':[0,72,240,200]}]
        return gray,lines,cells,{'upper':'u','lower':'l'}

    def test_real_local_long_members_are_missing_only_without_cell_halo(self):
        prior=ROOT/'local-artifacts/product-fix-p3b/local-scale-20261011-001'
        m=read(prior/'preview-007/window.json');p=read(prior/'local-plan.json')
        w=p['local_diagnostic_windows'][4]
        ref=read(ROOT/'local-artifacts/product-fix-p3b/feedback-fix-20261010-001/trial-05/frame.json')['frame']
        gray=np.array(Image.open(prior/'preview-007/native.png').convert('L'))
        parents,trace=partition_native_fragments(lines_from_source(gray,limit=None,min_length_px=0),
            np.array(m['origin_px']),m['coordinate_frame'],ref,[gray.shape[1],gray.shape[0]],'local-05-')
        b=w['search_box_reference_xyxy'];cells=[]
        for y in range(2):
            for x in range(2):
                box=[b[0]+(b[2]-b[0])*x/2,b[1]+(b[3]-b[1])*y/2,
                     b[0]+(b[2]-b[0])*(x+1)/2,b[1]+(b[3]-b[1])*(y+1)/2]
                cells.append({'region_id':f'local-search-{y}-{x}','pixel_box':box,
                              'display_box':box})
        groups=line_groups(parents,{'page_size_points':ref['render_size_px'],'render_size_px':ref['render_size_px']},cells)
        wanted={'local-05-P3B-LSD-000128','local-05-P3B-LSD-000188'}
        old=paired(parents,gray,cells,groups,0);new=paired(parents,gray,cells,groups,PAIR_MAX_SEPARATION_PX)
        self.assertFalse(any({g[0] for g in p['geometry']}==wanted for p in old))
        self.assertEqual(sum({g[0] for g in p['geometry']}==wanted for p in new),1)
        self.assertTrue(all(t['queue_parent'] for t in trace if t['fragment_id'] in wanted))

    def test_short_raw_evidence_does_not_enter_final_parent_pool(self):
        frame={'effective_dpi':100,'render_size_px':[240,200],
               'pdf_origin':[0,0],'pdf_x_per_pixel':[1,0],'pdf_y_per_pixel':[0,1]}
        parents,trace=partition_native_fragments([('short',[20,60,40,60],'test'),
            ('usable',[20,85,220,85],'test')],np.array([0,0]),frame,frame,[240,200],'')
        self.assertEqual([g[0] for g in parents],['usable'])
        self.assertEqual(trace[0]['stop_before_pairing'],'parent_length_below_40_reference_px')

    def test_spatial_index_preserves_existing_real_pair_within_original_budget(self):
        from trial_sampling import spatial_pair_neighbors
        from local_detection import map_line
        prior=ROOT/'local-artifacts/product-fix-p3b/local-scale-20261011-001'
        m=read(prior/'preview-001/window.json');p=read(prior/'local-plan.json')
        ref=read(ROOT/'local-artifacts/product-fix-p3b/feedback-fix-20261010-001/trial-02/frame.json')['frame']
        gray=np.array(Image.open(prior/'preview-001/native.png').convert('L'))
        parents,_=partition_native_fragments(lines_from_source(gray,limit=None,min_length_px=0),
            np.array(m['origin_px']),m['coordinate_frame'],ref,[gray.shape[1],gray.shape[0]],'local-04-')
        b=p['local_diagnostic_windows'][3]['search_box_reference_xyxy'];cells=[]
        for y in range(2):
            for x in range(2):
                box=[b[0]+(b[2]-b[0])*x/2,b[1]+(b[3]-b[1])*y/2,b[0]+(b[2]-b[0])*(x+1)/2,b[1]+(b[3]-b[1])*(y+1)/2]
                cells.append({'region_id':f'region-{y}-{x}','pixel_box':box,'display_box':box})
        groups=line_groups(parents,{'page_size_points':ref['render_size_px'],'render_size_px':ref['render_size_px']},cells)
        stats=[];wanted={'local-04-P3B-LSD-000257','local-04-P3B-LSD-000686'}
        proposals=list(regional_nominations(parents,gray,cells,groups,pair_budget=250,
            budget_stats=stats,include_components=False,member_halo_px=PAIR_MAX_SEPARATION_PX))
        self.assertEqual(sum({g[0] for g in r['geometry']}==wanted for r in proposals),1)
        self.assertTrue(all(s['complete'] and s['pair_comparisons']<=250 for s in stats))

    def test_intersections_keep_source_continuity_and_two_distinct_members(self):
        gray,lines,cells,groups=self.fixture();before=gray.copy()
        proposals=paired(lines,gray,cells,groups,PAIR_MAX_SEPARATION_PX)
        self.assertEqual(len(proposals),1)
        geometry=local_geometry(proposals[0]['geometry'],proposals[0]['center'])
        self.assertEqual({g[0] for g in geometry},{'upper','lower'})
        result=inspect({'candidate_geometry':geometry,'source_bbox':[0,0,240,200]},gray,require_directional_edge=True)
        self.assertTrue(result['HUMAN_QUEUE_ELIGIBLE'])
        self.assertEqual(result['metrics']['A_MAX_UNSUPPORTED_RUN_PX'],0)
        np.testing.assert_array_equal(gray,before)

    def test_true_source_gap_is_rejected_without_filling_pixels(self):
        gray,lines,cells,groups=self.fixture();gray[59:64,90:120]=255;before=gray.copy()
        prop=paired(lines,gray,cells,groups,PAIR_MAX_SEPARATION_PX)[0]
        geometry=local_geometry(prop['geometry'],prop['center'])
        quality=inspect({'candidate_geometry':geometry,'source_bbox':[0,0,240,200]},gray,require_directional_edge=True)
        self.assertFalse(quality['HUMAN_QUEUE_ELIGIBLE'])
        self.assertGreater(quality['metrics']['A_MAX_UNSUPPORTED_RUN_PX'],8)
        np.testing.assert_array_equal(gray,before)

    def test_fragment_order_and_endpoint_reversal_preserve_final_geometry(self):
        gray,lines,cells,groups=self.fixture()
        def geometry(items):
            p=paired(items,gray,cells,groups,PAIR_MAX_SEPARATION_PX)
            return [local_geometry(r['geometry'],r['center']) for r in p]
        reversed_lines=[(g[0],g[1][2:]+g[1][:2],g[2]) for g in reversed(lines)]
        self.assertEqual(geometry(lines),geometry(reversed_lines))

    def test_normal_history_exclusion_and_opt_in_replay_remain_separate(self):
        old=candidate('old');new=candidate('new');new['purpose']='development_local_scale_replay'
        selected,_,result=deduplicate([copy.deepcopy(new)],None,preview_policy={'record_decisions':True},history=[old])
        self.assertEqual(selected,[]);self.assertTrue(result['historical_exclusion_applied'])
        self.assertEqual(result['decisions'][0]['reason'],'historical_same_target')
        selected,_,result=deduplicate([copy.deepcopy(new)],None,preview_policy={'record_decisions':True},history=[old],preview_mode='development_replay')
        self.assertEqual(len(selected),1);self.assertFalse(result['historical_exclusion_applied'])


if __name__=='__main__':unittest.main()
