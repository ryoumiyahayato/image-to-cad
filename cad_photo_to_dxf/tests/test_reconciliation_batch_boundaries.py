"""P16-A isolated commit-boundary controls; not design-role inference."""

from dataclasses import replace

import pytest

from tests.test_source_stroke_reconciliation_v1 import _draw, _line, _page, _reconcile


def test_disconnected_collinear_members_keep_their_source_ids():
    page = _page()
    lines = [_line(20, 100, 80, 100, "LEFT"), _line(100, 100, 200, 100, "RIGHT")]
    for line in lines:
        _draw(page, line)
    result = _reconcile(page, main=lines)
    assert len(result.lines) == 2
    assert {(line.x1, line.x2, line.source_ids) for line in result.lines} == {
        (20, 80, ("LEFT",)),
        (100, 200, ("RIGHT",)),
    }
    result.assert_complete(result.lines)


def test_reversed_endpoints_preserve_same_source_coverage():
    page = _page()
    a, b = _line(20, 100, 200, 100, "A"), _line(60, 100, 160, 100, "B")
    _draw(page, a)
    normal = _reconcile(page, main=[a, b])
    reversed_lines = [
        replace(line, x1=line.x2, y1=line.y2, x2=line.x1, y2=line.y1) for line in (a, b)
    ]
    reversed_result = _reconcile(page, main=reversed_lines)

    def members(result):
        return sorted(
            (sorted(((line.x1, line.y1), (line.x2, line.y2))), line.source_ids)
            for line in result.lines
        )

    assert members(normal) == members(reversed_result)


@pytest.mark.parametrize("duplicate", ["first", "second"])
def test_duplicate_candidate_population_cannot_commit(duplicate):
    page = _page()
    a, b = _line(20, 100, 200, 100, "A"), _line(60, 100, 160, 100, "B")
    _draw(page, a)
    _reconcile(page, main=[a, b]).assert_complete()
    with pytest.raises(AssertionError, match="one-to-one"):
        _reconcile(page, main=[a, a] if duplicate == "first" else [a, b, b])


def test_equal_geometry_source_swap_fails_actual_commit_binding():
    page = _page()
    lines = [_line(20, 80, 200, 80, "UPPER"), _line(20, 120, 200, 120, "LOWER")]
    for line in lines:
        _draw(page, line)
    result = _reconcile(page, main=lines)
    result.assert_complete(result.lines)
    a, b = result.lines
    damaged = (replace(a, source_ids=b.source_ids), replace(b, source_ids=a.source_ids))
    assert [(v.x1, v.y1, v.x2, v.y2, v.length) for v in damaged] == [
        (v.x1, v.y1, v.x2, v.y2, v.length) for v in result.lines
    ]
    assert len(damaged) == len(result.lines) == 2
    assert sum(v.length for v in damaged) == 360
    # This detects replacement of the committed tuple. It is not a semantic
    # wrong-connection detector for an arbitrary independently loaded DXF.
    with pytest.raises(AssertionError, match="exact tuple object"):
        result.assert_complete(damaged)
