import numpy as np
from independent_native_pen import line_ink


def test_flat_horizontal_cell_centers_exact():
    expected = np.zeros((12, 12), bool)
    expected[3:6, 3:9] = True
    assert np.array_equal(line_ink((12, 12), ((3, 4), (8, 4)), 2, "flat"), expected)


def test_square_cap_extends_both_ends():
    expected = np.zeros((12, 12), bool)
    expected[3:6, 2:10] = True
    assert np.array_equal(line_ink((12, 12), ((3, 4), (8, 4)), 2, "square"), expected)


def test_round_terminal_curves_not_square_corners():
    flat = line_ink((12, 12), ((3, 4), (8, 4)), 2, "flat")
    expected = flat.copy()
    expected[4, 2] = expected[4, 9] = True
    assert np.array_equal(line_ink((12, 12), ((3, 4), (8, 4)), 2, "round"), expected)


def test_diagonal_reversal_and_offgrid_extent_are_symmetric():
    for cap in ("round", "flat", "square"):
        start, end = (-2.0, 2.0), (7.0, 11.0)
        forward = line_ink((12, 12), (start, end), 5, cap)
        reverse = line_ink((12, 12), (end, start), 5, cap)
        assert np.array_equal(forward, reverse), cap
