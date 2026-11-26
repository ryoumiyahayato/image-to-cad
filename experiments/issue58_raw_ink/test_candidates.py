"""Adversarial discovery tests. No synthetic case is counted as real recovery."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("raw_ink_candidates", Path(__file__).with_name("candidates.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CandidateRiskTests(unittest.TestCase):
    def image(self):
        return np.full((100, 110), 255, np.uint8)

    def run_model(self, source, roi=None):
        before = source.copy()
        result = m.discover(source, roi or [0, 0, source.shape[1], source.shape[0]])
        np.testing.assert_array_equal(source, before)
        self.assertEqual(result["complete_recovered_objects"], 0)
        self.assertEqual(result["adopted_objects"], [])
        self.assertFalse(result["old_source_graph_used"])
        for row in result["candidates"]:
            xy = np.asarray(row["source_path_px"])
            self.assertTrue(np.all(source[xy[:, 1], xy[:, 0]] < 128))
            self.assertLessEqual(np.max(abs(np.diff(xy, axis=0))), 1)
        return result

    def test_real_white_gap_cannot_be_bridged(self):
        source = self.image()
        cv2.line(source, (10, 50), (95, 50), 0, 5)
        source[:, 48:51] = 255
        result = self.run_model(source)
        self.assertGreaterEqual(len(result["candidates"]), 2)
        for row in result["candidates"]:
            xs = np.asarray(row["source_path_px"])[:, 0]
            self.assertFalse(xs.min() < 48 and xs.max() >= 51)

    def test_crop_edge_is_not_a_true_endpoint(self):
        source = self.image()
        cv2.line(source, (0, 50), (95, 50), 0, 5)
        result = self.run_model(source)
        self.assertTrue(any(e["crop_censored"] for row in result["candidates"]
                            for e in row["endpoint_evidence"]))

    def test_wrong_attachment_has_unassigned_source(self):
        source = self.image()
        cv2.line(source, (10, 55), (95, 55), 0, 5)
        cv2.line(source, (50, 55), (50, 10), 0, 5)
        result = self.run_model(source)
        self.assertTrue(any(row["unassigned_adjacent_source_pixels_px"]
                            for row in result["candidates"]))
        self.assertTrue(all("INDEPENDENT_SOURCE_OWNERSHIP_NOT_PROVED" in row["rejection_reasons"]
                            for row in result["candidates"]))

    def test_competing_fork_sequences_are_recorded(self):
        source = self.image()
        cv2.line(source, (10, 50), (50, 50), 0, 3)
        cv2.line(source, (50, 50), (95, 20), 0, 3)
        cv2.line(source, (50, 50), (95, 80), 0, 3)
        result = self.run_model(source)
        self.assertTrue(any(a["section_splits"] for a in result["axis_branch_reports"]))
        self.assertTrue(any(a["maximal_section_sequences"] > 1 for a in result["axis_branch_reports"]))

    def test_local_loop_is_not_silently_filled(self):
        source = self.image()
        cv2.line(source, (5, 50), (100, 50), 0, 3)
        cv2.rectangle(source, (40, 40), (60, 60), 0, 3)
        result = self.run_model(source)
        self.assertGreater(len(result["original_white_holes"]), 0)
        self.assertTrue(any(row["original_white_holes_touching_band"] for row in result["candidates"]))
        self.assertTrue(all(source[y, x] >= 128 for h in result["original_white_holes"]
                            for x, y in h["white_pixels_px"]))

    def test_nonstraight_ink_gets_polyline_candidates(self):
        source = self.image()
        cv2.polylines(source, [np.array([(10, 70), (40, 55), (75, 50), (100, 52)], np.int32)], False, 0, 5)
        result = self.run_model(source)
        def deviation(row):
            pts = np.asarray(row["source_path_px"], float)
            axis = pts[-1] - pts[0]
            axis /= np.linalg.norm(axis)
            return np.max(abs((pts - pts[0]) @ np.array([-axis[1], axis[0]])))
        self.assertTrue(any(deviation(row) > 1.5 for row in result["candidates"]))

    def test_branch_resource_stop_withholds_candidates(self):
        source = self.image()
        cv2.line(source, (10, 50), (50, 50), 0, 3)
        cv2.line(source, (50, 50), (95, 20), 0, 3)
        cv2.line(source, (50, 50), (95, 80), 0, 3)
        policy = deepcopy(m.POLICY)
        try:
            m.POLICY["maximum_section_paths_per_axis"] = 0
            result = self.run_model(source)
            self.assertGreater(result["resources"]["axis_branch_overflows"], 0)
            self.assertEqual(result["candidates"], [])
        finally:
            m.POLICY.clear()
            m.POLICY.update(policy)

    def test_replay_is_deterministic(self):
        source = self.image()
        cv2.line(source, (10, 70), (95, 25), 0, 5)
        first, second = self.run_model(source), self.run_model(source)
        first.pop("wall_seconds")
        second.pop("wall_seconds")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
