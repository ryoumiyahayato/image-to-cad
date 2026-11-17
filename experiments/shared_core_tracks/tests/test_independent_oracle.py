"""Negative controls prove the new source oracle detects the intended failures."""
import numpy as np

from independent_fixtures import fixtures, native_version
from independent_oracle import Observation, inspect


FIXTURES = {f.name: f for f in fixtures()}


def test_complete_retention_passes_every_constructed_source():
    for fixture in FIXTURES.values():
        result = inspect(fixture, Observation(fixture.source.copy(), [], fixture.source.copy(), []))
        assert result["pass"], (fixture.name, result)


def test_deleted_short_branch_detected_even_if_ledger_claims_it():
    fixture = FIXTURES["comb_short_teeth"]
    owned = np.zeros(fixture.gray.shape, bool)
    owned[88, 55] = True
    retained = fixture.source & ~owned
    result = inspect(fixture, Observation(retained, [owned], retained.copy(), [retained.copy()]))
    assert "owner_0_claims_required_retained" in result["failures"]
    assert "observed_black_centers_missing" in result["failures"]
    assert "rendered_part_0_does_not_cover_own_source" in result["failures"]


def test_white_gap_bridge_detected_without_source_retirement():
    fixture = FIXTURES["end_gap_1px"]
    rendered = fixture.source.copy()
    rendered[96, 126] = True
    result = inspect(fixture, Observation(fixture.source.copy(), [], rendered, []))
    assert "observed_white_fence_bridged" in result["failures"]
    assert "observed_white_centers_covered" in result["failures"]


def test_small_protected_touch_prohibits_other_parts_of_same_source():
    fixture = FIXTURES["text_touching_line_protected"]
    owned = np.zeros(fixture.gray.shape, bool)
    owned[96, 24:48] = True
    result = inspect(fixture, Observation(fixture.source & ~owned, [owned]))
    assert "source_that_must_reject_has_owner" in result["failures"]


def test_duplicate_ownership_and_inferred_connectivity_rejected():
    fixture = FIXTURES["isolated_long_control"]
    owned = fixture.source.copy()
    result = inspect(fixture, Observation(np.zeros_like(owned), [owned, owned],
                                         object_identity="ONE_SYMBOL", electrical_connectivity="CONNECTED"))
    assert "duplicate_source_ownership" in result["failures"]
    assert "object_identity_inferred_from_synthetic_pixels" in result["failures"]
    assert "electrical_connectivity_inferred_from_synthetic_pixels" in result["failures"]


def test_native_construction_retains_exact_cell_state():
    for fixture in FIXTURES.values():
        native = native_version(fixture)
        assert native.source.sum() == 4 * fixture.source.sum()
        assert native.dpi == 2 * fixture.dpi
        assert inspect(native, Observation(native.source.copy(), [], native.source.copy(), []))["pass"]
