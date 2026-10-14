"""Known CONTROL errors and compound-region burden only; no PDF redetection."""

import copy
import gzip
import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from control_targets import ControlContext
from quality import inspect
from selection_targets import compound_carrier_burden, same_observed_target, selection_difference

ROOT=Path(__file__).resolve().parents[2]
SAVED=ROOT/'local-artifacts/product-fix-p3b/new-page-trial-20261011-001'


class ControlTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=[json.loads(l) for l in (SAVED/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        with gzip.open(SAVED/'eligible-pool.jsonl.gz','rt',encoding='utf-8') as f:
            pool=list(map(json.loads,f))
        cls.contexts={}
        for unit in ('NEW-01','NEW-02','NEW-03','NEW-04'):
            gray=np.array(Image.open(SAVED/'sources'/unit/'source.png').convert('L'))
            cls.contexts[unit]=ControlContext.from_saved_rows(gray,[r for r in pool if r['plan_unit']==unit])

    def test_known_dash_and_wall_fragments_deferred_letters_not_recognized_or_labeled(self):
        for index,reason in ((8,'repeated_collinear_dash_sequence'),(11,'ink_on_detected_long_line_carrier')):
            row=self.rows[index];context=self.contexts[row['plan_unit']]
            evidence=context.assess(row['target_roi'])
            self.assertEqual(evidence['status'],'line_fragment')
            self.assertEqual(evidence['reason'],reason)
            self.assertFalse(inspect(row,context.gray,require_directional_edge=True,
                                     control_evidence=evidence)['HUMAN_QUEUE_ELIGIBLE'])
        for index in (9,10):
            row=self.rows[index];context=self.contexts[row['plan_unit']]
            evidence=context.assess(row['target_roi'])
            self.assertEqual(evidence['status'],'separable_ink_candidate')
            self.assertTrue(inspect(row,context.gray,require_directional_edge=True,
                                    control_evidence=evidence)['HUMAN_QUEUE_ELIGIBLE'])
            self.assertFalse(evidence['glyph_identity_confirmed'])
            self.assertNotIn('ocr_text',evidence)
            self.assertIsNone(row['label'])

    def test_isolated_flat_print_is_uncertain_not_automatically_structure_fragment(self):
        gray=np.full((32,40),255,np.uint8);gray[15,12:23]=0
        evidence=ControlContext(gray,[]).assess([12,15,11,1])
        self.assertEqual(evidence['status'],'uncertain_extent')
        self.assertEqual(evidence['reason'],'linear_print_or_line_fragment_unresolved')

    def test_saved_bent_dash_is_fragment_without_rejecting_letters(self):
        directory=ROOT/'local-artifacts/product-fix-p3b/normal-entry-closeout-20261011-001'
        with gzip.open(directory/'four-page-quality-pool.jsonl.gz','rt',encoding='utf-8') as f:
            row=next(r for r in map(json.loads,f) if r['sample_id']=='proposal-NEW-01-000416')
        evidence=self.contexts['NEW-01'].assess(row['target_roi'])
        self.assertEqual(evidence['reason'],'bent_fragment_on_repeated_dash_carrier')
        self.assertEqual(evidence['series_phase_members'],4)
        self.assertFalse(evidence['queue_eligible'])
        gray=np.full((40,40),255,np.uint8)
        gray[10:19,10:12]=0;gray[17:19,10:16]=0
        self.assertEqual(ControlContext(gray,[]).assess([10,10,6,9])['status'],'separable_ink_candidate')

    def test_saved_geometry_only_extras_deferred_without_merging_edges(self):
        directory=ROOT/'local-artifacts/product-fix-p3b/normal-entry-closeout-20261011-001'
        rows={r['sample_id']:r for r in map(json.loads,(directory/'manifest.jsonl').read_text(encoding='utf-8').splitlines())}
        config={'auto_extra_requires_new_geometry':True,'max_crop_iou':.25}
        for first,second in (('proposal-NEW-04-000856','proposal-NEW-04-000857'),
                             ('proposal-NEW-01-001439','proposal-NEW-01-001440'),
                             ('proposal-OBS-05-000579','proposal-OBS-05-000589')):
            old,row=rows[first],copy.deepcopy(rows[second])
            original=copy.deepcopy(row['candidate_geometry'])
            self.assertFalse(same_observed_target(row,old))
            self.assertIsNone(selection_difference(row,[old],config))
            self.assertEqual(row['selection_uncertainty']['reason'],'single_member_relation_unconfirmed')
            self.assertEqual(row['candidate_geometry'],original)
        # A PAIR nomination alone also cannot establish another object relation.
        row=copy.deepcopy(rows['proposal-NEW-02-000202'])
        self.assertIsNone(selection_difference(row,[rows['proposal-NEW-02-000799']],config))
        row['difficulty_difference']={'kind':'opening','evidence':'recorded source opening relation'}
        self.assertIsNotNone(selection_difference(row,[rows['proposal-NEW-02-000799']],config))

    def test_real_third_ink_edge_not_merged_but_extra_information_unconfirmed(self):
        pair,third=self.rows[3],copy.deepcopy(self.rows[13])
        before=copy.deepcopy(third['candidate_geometry'])
        evidence=compound_carrier_burden(third,[pair])
        self.assertFalse(same_observed_target(third,pair))
        self.assertAlmostEqual(evidence['crop_iou'],.7653745656)
        self.assertTrue(evidence['target_entirely_in_shown_crop'])
        self.assertFalse(evidence['same_target_claimed'])
        gray=self.contexts['NEW-03'].gray
        self.assertLess(gray[690,860],160)  # Observed separate lower ink, no created pixels.
        self.assertTrue(np.all(gray[686:690,860]>180))  # Real intervening light interval.
        self.assertIsNone(selection_difference(third,[pair],{'max_crop_iou':.25,
                                        'auto_extra_requires_new_geometry':True}))
        self.assertEqual(third['candidate_geometry'],before)
        # An existing nonparallel relation is not blocked by this band proxy.
        self.assertIsNone(compound_carrier_burden(self.rows[12],[self.rows[0]]))


if __name__=='__main__':unittest.main()
