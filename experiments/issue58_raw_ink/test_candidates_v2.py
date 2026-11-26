"""Seed-mechanism comparison on source-independent slanted/crossing fixtures."""
import importlib.util
import unittest
from pathlib import Path

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("raw_ink_candidates_v2", Path(__file__).with_name("candidates_v2.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class NonConsumingSeedRiskTests(unittest.TestCase):
    def test_slanted_support_axes_are_proposed_without_consuming_crossing_pixels(self):
        source = np.full((120, 130), 255, np.uint8)
        segments = [((20, 20), (45, 85)), ((50, 15), (75, 80)), ((80, 10), (105, 75))]
        for a, b in segments:
            cv2.line(source, a, b, 0, 3)
        cv2.line(source, (5, 45), (120, 45), 0, 3)
        before = source.copy()
        result = m.discover(source, [0, 0, 130, 120])
        np.testing.assert_array_equal(before, source)
        self.assertFalse(any(result['resources'].values()))
        for a, b in segments:
            axis = np.array(b, float) - a
            expected_angle = np.degrees(np.arctan2(axis[1], axis[0]))
            middle = (np.array(a) + b) / 2
            nearby = []
            for seed in result['seed_axes']:
                theta = np.radians(seed['angle_deg'])
                normal = np.array([-np.sin(theta), np.cos(theta)])
                if abs(seed['angle_deg'] - expected_angle) <= 4 and abs(middle @ normal - seed['normal_offset_px']) <= 3:
                    nearby.append(seed)
            self.assertTrue(nearby)
        self.assertEqual(result['adopted_objects'], [])
        for row in result['candidates']:
            self.assertEqual(len(row['axis_evidence_variants']), len(row['seed_axes']))
            for witness in row['axis_evidence_variants']:
                self.assertEqual(witness['source_path_sha256'], m.base.digest(row['source_path_px']))

    def test_real_gap_still_partitions_source_paths(self):
        source = np.full((80, 130), 255, np.uint8)
        cv2.line(source, (5, 40), (125, 40), 0, 3)
        source[:, 62:66] = 255
        result = m.discover(source, [0, 0, 130, 80])
        self.assertGreater(len(result['candidates']), 1)
        for row in result['candidates']:
            pts = np.asarray(row['source_path_px'])
            self.assertFalse(pts[:, 0].min() < 62 and pts[:, 0].max() >= 66)
            self.assertTrue(np.all(source[pts[:, 1], pts[:, 0]] < 128))

    def test_same_source_and_rules_replay_identically(self):
        source = np.full((80, 100), 255, np.uint8)
        cv2.line(source, (5, 10), (75, 60), 0, 3)
        a = m.discover(source, [0, 0, 100, 80])
        b = m.discover(source, [0, 0, 100, 80])
        a.pop('wall_seconds')
        b.pop('wall_seconds')
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main(verbosity=2)
