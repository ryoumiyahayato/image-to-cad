from __future__ import annotations

import unittest

from app.line_detect import LineSegment
from app.topology import TopologyParams, split_lines_at_intersections


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    source: str,
) -> LineSegment:
    return LineSegment(
        x1,
        y1,
        x2,
        y2,
        source_ids=(source,),
        history=("test-input",),
    )


class TopologyTests(unittest.TestCase):
    def test_crossing_lines_are_split_into_four_segments(self) -> None:
        result = split_lines_at_intersections(
            [
                line(0, 5, 10, 5, "H"),
                line(5, 0, 5, 10, "V"),
            ]
        )

        self.assertEqual(len(result.lines), 4)
        self.assertEqual(result.report.split_line_count, 2)
        self.assertEqual(result.report.generated_segment_count, 2)
        shared = sum(
            int(abs(item.x1 - 5) < 1e-9 and abs(item.y1 - 5) < 1e-9)
            + int(abs(item.x2 - 5) < 1e-9 and abs(item.y2 - 5) < 1e-9)
            for item in result.lines
        )
        self.assertEqual(shared, 4)
        self.assertTrue(
            all("split_intersection" in item.history for item in result.lines)
        )

    def test_t_junction_splits_only_the_interior_line(self) -> None:
        result = split_lines_at_intersections(
            [
                line(0, 5, 10, 5, "H"),
                line(5, 0, 5, 5, "V"),
            ]
        )

        self.assertEqual(len(result.lines), 3)
        self.assertEqual(result.report.split_line_count, 1)
        horizontal = [item for item in result.lines if "H" in item.source_ids]
        vertical = [item for item in result.lines if "V" in item.source_ids]
        self.assertEqual(len(horizontal), 2)
        self.assertEqual(len(vertical), 1)

    def test_parallel_lines_are_not_split(self) -> None:
        result = split_lines_at_intersections(
            [
                line(0, 0, 10, 0, "A"),
                line(0, 1, 10, 1, "B"),
            ]
        )
        self.assertEqual(len(result.lines), 2)
        self.assertEqual(result.report.split_line_count, 0)

    def test_pair_limit_is_reported_without_hiding_output(self) -> None:
        result = split_lines_at_intersections(
            [
                line(0, 0, 10, 10, "A"),
                line(0, 10, 10, 0, "B"),
            ],
            TopologyParams(max_pair_checks=0),
        )
        self.assertTrue(result.report.pair_limit_reached)
        self.assertEqual(result.report.pair_checks, 0)
        self.assertEqual(len(result.lines), 2)


if __name__ == "__main__":
    unittest.main()
