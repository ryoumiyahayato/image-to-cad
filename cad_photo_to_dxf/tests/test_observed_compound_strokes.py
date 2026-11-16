"""Source permission, crop phase, and opt-in isolation of compound recovery."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from app.core.processing import ProductionProcessingConfig
from app.geometry.observed_compound_strokes import recover_observed_compound_strokes
from app.geometry.scan_dust import RegisteredOriginalScan


def source_cross():
    gray = np.full((181, 181), 255, np.uint8)
    gray[90, 10:171] = 0
    gray[10:171, 90] = 0
    native = np.repeat(np.repeat(gray, 2, axis=0), 2, axis=1)
    return gray, RegisteredOriginalScan(native, 200., 2)


def test_native_ledger_covers_retired_parent_and_inputs_stay_immutable():
    gray, scan = source_cross()
    originals = (gray.copy(), scan.pixels.copy())
    visible, paths, records, review = recover_observed_compound_strokes(
        gray, gray, gray, dpi=100., registered_original_scan=scan)
    assert review['accepted_parents'] == 1
    assert review['accepted_parts'] == 4
    assert len(paths) == len(records) == 1
    assert np.all(visible == 255)
    assert np.array_equal(gray, originals[0]) and np.array_equal(scan.pixels, originals[1])
    record = records[0]
    assert record['native_source_pixels'] == (gray == 0).sum()*4
    assert record['native_retired_source_pixels'] + record['native_residual_pixels'] == record['native_source_pixels']
    assert record['pre_retirement_export_validation']
    assert record['experimental_retirement_authorized'] is True
    assert record['full_object_movable'] is False
    assert record['electrical_semantics'] == 'NOT_INFERRED'


@pytest.mark.parametrize('reason', ['protected', 'claimed', 'current_foreground', 'missing_native',
                                    'native_mismatch', 'nonbitonal', 'clip'])
def test_whole_parent_permissions_and_original_evidence_fail_closed(reason):
    gray, scan = source_cross()
    binary, visible = gray.copy(), gray.copy()
    protected = np.zeros_like(gray)
    if reason == 'protected':
        protected[90, 15] = 1
    elif reason == 'claimed':
        visible[90, 15] = 255
    elif reason == 'current_foreground':
        binary[90, 15] = 255
    elif reason == 'missing_native':
        scan = None
    elif reason == 'native_mismatch':
        scan.pixels[180:182, 30:32] = 255
    elif reason == 'nonbitonal':
        scan.pixels[180, 30] = 1
    else:
        gray = np.roll(gray, -9, axis=1)
        binary = gray.copy(); visible = gray.copy()
        scan = RegisteredOriginalScan(np.repeat(np.repeat(gray, 2, 0), 2, 1), 200., 2)
    expected = visible.copy()
    output, paths, records, review = recover_observed_compound_strokes(
        gray, binary, visible, protected_masks=(protected,), dpi=100., registered_original_scan=scan)
    assert np.array_equal(output, expected)
    assert not paths and not records
    assert review['accepted_parents'] == review['accepted_parts'] == 0


def test_crop_mapping_uses_full_native_grid_and_local_output_origin():
    gray, scan = source_cross()
    full = np.full((442, 462), 255, np.uint8)
    full[40:402, 60:422] = scan.pixels
    crop_scan = RegisteredOriginalScan(full, 200., 2)
    result = recover_observed_compound_strokes(
        gray, gray, gray, dpi=100., registered_original_scan=crop_scan,
        source_crop=(30, 20, 211, 201))
    plain = recover_observed_compound_strokes(gray, gray, gray, dpi=100., registered_original_scan=scan)
    assert result[3]['accepted_parts'] == plain[3]['accepted_parts'] == 4
    for a, b in zip(result[2][0]['parts'], plain[2][0]['parts']):
        assert a['points_px'] == b['points_px']
        assert a['native_retired_source_runs_y_x0_x1'] == b['native_retired_source_runs_y_x0_x1']
    assert result[2][0]['source_identity']['source_crop'] == (30, 20, 211, 201)


def test_isolated_line_is_not_reclassified_by_compound_contract():
    gray, _ = source_cross()
    gray[10:90, 90] = 255
    gray[91:171, 90] = 255
    scan = RegisteredOriginalScan(np.repeat(np.repeat(gray, 2, 0), 2, 1), 200., 2)
    output, paths, records, review = recover_observed_compound_strokes(
        gray, gray, gray, dpi=100., registered_original_scan=scan)
    assert output is gray and not paths and not records
    assert review['decisions'][0]['reason'] == 'NO_COMPOUND_JUNCTION'


def test_feature_is_opt_in_and_changes_processing_contract_identity():
    default = ProductionProcessingConfig().payload()
    explicit_off = ProductionProcessingConfig(experimental_compound_strokes=False).payload()
    enabled = ProductionProcessingConfig(experimental_compound_strokes=True).payload()
    assert default == explicit_off
    assert 'experimental_compound_strokes' not in default
    assert enabled['experimental_compound_strokes'] is True
    assert enabled['compound_stroke_version'] == 'registered-native-compound-parts-v1'
    restored = copy.deepcopy(enabled)
    del restored['experimental_compound_strokes'], restored['compound_stroke_version']
    assert restored == default
    with pytest.raises(ValueError):
        ProductionProcessingConfig(experimental_compound_strokes=1)
