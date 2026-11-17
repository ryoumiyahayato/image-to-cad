"""Two direct-native controls for source-first segmentation.

The single-cell feature is constructed in the original 200-DPI grid, then the
working grayscale is derived by BOX. These are synthetic counterexamples,
never independent acquisitions of a real drawing or added real evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from independent_fixtures import Fixture, fixtures, native_version


@dataclass(frozen=True)
class NativeFixture:
    name: str
    working_gray: np.ndarray
    native: Fixture
    scale: int = 2
    dpi: float = 100.0


def direct_native_fixtures():
    base = next(f for f in fixtures() if f.name == "T_long_arms")
    native_base = native_version(base)
    for kind in ("one_native_black_spur", "one_native_white_notch"):
        gray = native_base.gray.copy()
        retain = native_base.must_retain.copy()
        fence = np.zeros(gray.shape, bool)
        if kind == "one_native_black_spur":
            # The T's main bar occupies native rows 190..195. This deliberately
            # constructed member is one cell above it, away from the T center.
            gray[189, 180] = 0
            retain[189, 180] = True
            note = "One-cell short branch is its own observed member even if thinning omits a branch node."
        else:
            # An exterior notch: deleting this source cell does not create a
            # new hole or paper component, so count-only topology can miss it.
            gray[190, 180] = 255
            fence[190, 180] = True
            note = "One-cell open white notch must not be covered, even when component/hole counts agree."
        working = np.asarray(Image.fromarray(gray).resize(
            (base.gray.shape[1], base.gray.shape[0]), Image.Resampling.BOX)).copy()
        native = Fixture(kind, "native_single_cell_source_member", gray,
                         np.zeros(gray.shape, bool), retain & (gray < 254), fence,
                         np.where(gray < 254, 0, 255).astype(np.uint8),
                         "partial_candidate_permitted", note, 200.0)
        yield NativeFixture(kind, working, native)
