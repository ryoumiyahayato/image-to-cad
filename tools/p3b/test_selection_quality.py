"""Local checks for saved-pool selection losses; no detector or PDF renderer."""

import copy
import json
import unittest
from pathlib import Path

from preview_selection import select_preview, select_preview_mode
from selection_targets import (burden_coverage, choose_representatives,
                              coverage_against_outputs, geometry_key,
                              measured_difference, same_observed_target, shared_line_occupants)

ROOT = Path(__file__).resolve().parents[2]
SAVED = ROOT/'local-artifacts/product-fix-p3b/local-lifecycle-20261011-001'


def target(identity, lines, ids, region='r', groups=None):
    return {'sample_id': identity, 'source_drawing_id': 'source', 'source_page': 1,
            'source_family_id': 'design', 'plan_unit': 'page', 'region_id': region,
            'target_kind': 'PAIR' if len(lines) == 2 else 'SINGLE', 'preferred_kind': 'SINGLE',
            'candidate_geometry_ids': ids, 'display_geometry': lines,
            'display_parent_geometry': lines, 'display_crop_box': [-20, -20, 120, 120],
            'longline_proxy_ids': groups or ['carrier'], 'display_target_box': None,
            'quality': {'metrics': {}}, 'label': None}


class SelectionQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = [json.loads(l) for l in (SAVED/'eligible-pool.jsonl').read_text(encoding='utf-8').splitlines()]
        cls.previous = json.loads((SAVED/'results.json').read_text(encoding='utf-8'))
        cls.config = {**cls.previous['selection']['configuration'], 'max_difficult_page': 1}

    def replay(self, rows=None):
        return select_preview_mode(copy.deepcopy(self.pool if rows is None else rows), [], self.config,
                                   mode='development_replay')

    def test_complete_representative_not_first_id_or_detector_order(self):
        short = target('first', [[20, 0, 60, 0]], ['edge'])
        full = target('last', [[0, 0, 100, 0]], ['edge'])
        for rows in ([short, full], [full, short]):
            chosen, removed = choose_representatives(copy.deepcopy(rows))
            self.assertEqual(chosen[0]['display_geometry'], full['display_geometry'])
            self.assertEqual(removed[0]['reason'], 'same_target_representative')
        alias = copy.deepcopy(full)
        alias.update(sample_id='new-id', candidate_geometry_ids=['renamed-detector-id'])
        self.assertTrue(same_observed_target(full, alias))
        self.assertEqual(coverage_against_outputs(full, [alias])['full_target_coverage_fraction'], 1)
        chosen, _ = choose_representatives([full, alias])
        self.assertEqual(len(chosen), 1)

    def test_shared_member_is_not_full_pair_or_full_interval(self):
        full = target('full', [[0, 0, 100, 0]], ['edge'])
        pair = target('pair', [[0, 0, 38.1, 0], [0, 10, 38.1, 10]], ['edge', 'other'])
        evidence = coverage_against_outputs(full, [pair])
        self.assertAlmostEqual(evidence['members'][0]['covered_fraction'], .381)
        self.assertEqual(evidence['full_target_coverage_fraction'], 0)
        self.assertFalse(same_observed_target(full, pair))

    def test_interval_union_keeps_gap_and_parallel_edge_separate(self):
        full = target('full', [[0, 0, 100, 0]], ['edge'])
        pieces = [target('left', [[0, 0, 20, 0]], ['edge']),
                  target('right', [[100, 0, 80, 0]], ['edge']),
                  target('neighbor', [[0, 10, 100, 10]], ['other'])]
        evidence = coverage_against_outputs(full, pieces)
        self.assertEqual(evidence['members'][0]['covered_intervals_pdf_points'], [[0, 20], [80, 100]])
        self.assertAlmostEqual(evidence['members'][0]['covered_fraction'], .4)
        self.assertAlmostEqual(burden_coverage(full, pieces)['mean_missing_length_pdf_points'], 60)
        self.assertEqual(len(shared_line_occupants(full, pieces)['carrier']), 2)

    def test_same_crop_different_target_is_burden_not_equivalence(self):
        a = target('a', [[0, 0, 100, 0]], ['a'])
        b = target('b', [[0, 12, 100, 12]], ['b'])
        chosen, _, stats = select_preview([a, b], [], {'record_decisions': True, 'max_difficult_page': 0})
        self.assertEqual(len(chosen), 1)
        rejection = next(d for d in stats['decisions'] if d['outcome'] == 'rejected')
        self.assertTrue(rejection['burden_is_not_target_equivalence'])
        self.assertEqual(rejection['coverage_against_final_outputs']['members'][0]['covered_fraction'], 0)

    def test_saved_pool_permutation_and_endpoint_reversal(self):
        chosen, _, _ = self.replay()
        reversed_rows = copy.deepcopy(list(reversed(self.pool)))
        for row in reversed_rows:
            row['display_geometry'] = [g[2:]+g[:2] for g in row['display_geometry']]
        alternate, _, _ = self.replay(reversed_rows)
        self.assertEqual(sorted(geometry_key(r) for r in chosen), sorted(geometry_key(r) for r in alternate))

    def test_real_coverage_and_bounded_extra(self):
        chosen, _, stats = self.replay()
        by_id = {r['sample_id']: r for r in self.pool}
        t10 = by_id['local-proposal-02-00034']
        self.assertGreater(coverage_against_outputs(t10, chosen)['members'][0]['covered_fraction'], .999)
        self.assertEqual(coverage_against_outputs(t10, chosen)['full_target_coverage_fraction'], 0)
        self.assertIn('local-proposal-03-00094', [r['sample_id'] for r in chosen])
        self.assertIn('local-proposal-05-00001', [r['sample_id'] for r in chosen])
        self.assertNotIn('local-proposal-04-00011', [r['sample_id'] for r in chosen])
        self.assertEqual(sum(stats['ordinary_selected_per_page'].values()), 5)
        self.assertEqual(sum(stats['selected_difficult_per_page'].values()), 1)
        self.assertEqual(len(chosen), 6)
        self.assertTrue(all(r.get('label') is None and not r.get('human_answer_inherited') for r in chosen))
        # Selection cannot create the unresolved006 geometry: every output is an unchanged saved proposal.
        for row in chosen:
            self.assertEqual(row['candidate_geometry'], by_id[row['sample_id']]['candidate_geometry'])

    def test_default_history_exclusion_is_not_replay(self):
        old = next(r for r in self.pool if r['sample_id'] == 'local-proposal-05-00001')
        old=copy.deepcopy(old)
        old['human_contact_confirmed']=True
        normal, _, stats = select_preview_mode(copy.deepcopy(self.pool), [old], self.config)
        self.assertNotIn(old['sample_id'], [r['sample_id'] for r in normal])
        self.assertTrue(stats['historical_exclusion_applied'])
        replay, _, stats = self.replay()
        self.assertIn(old['sample_id'], [r['sample_id'] for r in replay])
        self.assertFalse(stats['new_information_claimed'])

    def test_planned_control_opportunity_and_extra_counts_without_decision_log(self):
        line = target('line', [[0, 0, 100, 0]], ['edge'])
        line['preferred_kind'] = 'CONTROL'
        control = target('control', [], [])
        control.update(target_kind='CONTROL', preferred_kind='CONTROL', display_target_box=[30, 30, 50, 50])
        chosen, _, _ = select_preview([line, control], [], {'max_difficult_page': 0})
        self.assertEqual(chosen[0]['target_kind'], 'CONTROL')
        self.assertIsNone(chosen[0]['label'])
        # Explicit existing differences still work without record_decisions=True.
        a = target('first', [[0, 0, 100, 0]], ['a'])
        b = target('next', [[500, 0, 600, 0]], ['b'], region='s')
        b['display_crop_box'] = [480, -20, 620, 120]
        b['difficulty_difference'] = {'kind': 'opening', 'evidence': 'explicit test node difference'}
        chosen, _, stats = select_preview([a, b], [], {'max_page': 1})
        self.assertEqual(len(chosen), 2)
        self.assertEqual(stats['decision_counts']['page_or_design_cap'], 0)

    def test_control_nested_extent_is_not_identical_target(self):
        outer = target('outer', [], [])
        inner = target('inner', [], [])
        outer.update(target_kind='CONTROL', display_target_box=[20, 20, 60, 60])
        inner.update(target_kind='CONTROL', display_target_box=[30, 30, 40, 40])
        self.assertFalse(same_observed_target(outer, inner))
        alias = copy.deepcopy(inner)
        alias['sample_id'] = 'another-id'
        self.assertTrue(same_observed_target(inner, alias))
        chosen, _, stats = select_preview([outer, inner], [], {'max_difficult_page': 0})
        self.assertEqual(len(chosen), 1)
        self.assertNotIn('same_target', stats['decision_counts'])

    def test_new_information_extra_needs_more_than_uncovered_extent(self):
        def supported(identity, y, interval):
            row = target(identity, [[interval[0], y, interval[1], y]], [identity])
            row['source_dpi'] = 110
            row['quality'] = {'HUMAN_QUEUE_ELIGIBLE': True, 'metrics': {
                'A_SOURCE_SUPPORT_RATIO': 1, 'A_ENDPOINT_SUPPORT': 1,
                'A_SUPPORT_RADIUS_PX': 1.25,
                'A_EDGE_ATTACHMENT': {'directional_edge_ratio': 1}}}
            return row
        old = supported('old', 0, [0, 50])
        more = supported('more', 0, [40, 100])
        different = supported('different', 10, [0, 100])
        self.assertIsNone(measured_difference(more, [old], require_new_geometry=True))
        evidence = measured_difference(different, [old], require_new_geometry=True)
        self.assertEqual(evidence['new_geometric_carrier_members'], ['different'])
        self.assertFalse(evidence['semantic_identity_confirmed'])
        control = target('control', [], [])
        control.update(target_kind='CONTROL', display_target_box=[30, 30, 40, 40])
        self.assertIsNone(measured_difference(different, [control], require_new_geometry=True))
        # Diagnostic full-extent replay remains available, with no new-label claim.
        self.assertIsNotNone(measured_difference(more, [old]))

    def test_whole_window_rotation_before_subcell_and_control_opportunity(self):
        rows = []
        for win in (1, 2):
            for cell in (1, 2):
                for kind in ('PAIR', 'SINGLE', 'CONTROL'):
                    pos = win*1000+cell*200
                    lines = [] if kind == 'CONTROL' else [[pos, 0, pos+100, 0]]
                    if kind == 'PAIR': lines.append([pos, 10, pos+100, 10])
                    row = target(f'{win}-{cell}-{kind}', lines,
                                 [f'{win}-{cell}-{kind}-{i}' for i in range(len(lines))],
                                 region=f'page-search-{win}-{cell}-1',
                                 groups=[f'{win}-{cell}-{kind}-carrier'])
                    row.update(target_kind=kind, preferred_kind='PAIR',
                               display_crop_box=[pos-20, -20, pos+120, 120])
                    if kind == 'CONTROL':
                        row['display_target_box'] = [pos+30, 30, pos+50, 50]
                        row['quality']['control_object_evidence']={'queue_eligible':True,'status':'separable_ink_candidate'}
                    rows.append(row)
        chosen, _, stats = select_preview_mode(rows, [], {'max_page': 3, 'max_difficult_page': 0})
        self.assertEqual([r['target_kind'] for r in chosen], ['PAIR', 'SINGLE', 'CONTROL'])
        self.assertEqual(len({r['observation_window_id'] for r in chosen}), 2)
        self.assertTrue(stats['historical_exclusion_applied'])
        self.assertTrue(all(r['label'] is None for r in chosen))


if __name__ == '__main__':
    unittest.main()
