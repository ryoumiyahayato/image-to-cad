from __future__ import annotations

from app.line_detect import LineSegment
from app.topology import build_topology, validate_topology


def _line(x1: float, y1: float, x2: float, y2: float, source: str) -> LineSegment:
    return LineSegment(
        x1,
        y1,
        x2,
        y2,
        source_ids=(source,),
        history=("test",),
    )


def test_crossing_lines_are_split_into_endpoint_graph() -> None:
    result = build_topology(
        [
            _line(0, 50, 100, 50, "H"),
            _line(50, 0, 50, 100, "V"),
        ],
        intersection_tolerance=0.1,
        endpoint_tolerance=0.1,
        gap_tolerance=2.0,
    )
    assert result.split_report.intersections_found == 1
    assert result.split_report.lines_split == 2
    assert len(result.lines) == 4
    assert result.validation_report.unresolved_interior_intersections == 0
    assert result.validation_report.junction_nodes == 1
    assert result.validation_report.dangling_endpoints == 4


def test_closed_rectangle_is_reported_as_closed_component() -> None:
    lines = [
        _line(0, 0, 100, 0, "TOP"),
        _line(100, 0, 100, 80, "RIGHT"),
        _line(100, 80, 0, 80, "BOTTOM"),
        _line(0, 80, 0, 0, "LEFT"),
    ]
    report = validate_topology(lines, endpoint_tolerance=0.1, gap_tolerance=2.0)
    assert report.closed_components == 1
    assert report.open_components == 0
    assert report.dangling_endpoints == 0


def test_small_gap_between_dangling_endpoints_is_reported() -> None:
    lines = [
        _line(0, 0, 49, 0, "A"),
        _line(52, 0, 100, 0, "B"),
    ]
    report = validate_topology(lines, endpoint_tolerance=0.1, gap_tolerance=5.0)
    assert report.small_gap_pairs == 1
    assert report.open_components == 2


def test_duplicate_lines_are_reported() -> None:
    lines = [
        _line(0, 0, 100, 0, "A"),
        _line(100, 0, 0, 0, "B"),
    ]
    report = validate_topology(lines, endpoint_tolerance=0.1, gap_tolerance=2.0)
    assert report.exact_duplicate_lines == 1
