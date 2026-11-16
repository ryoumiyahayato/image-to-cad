"""Confirmed source evidence must not depend on a raster classification heuristic."""
import numpy as np
import pytest

from app.geometry.scan_cleanup import prepare_scan_page


def _sparse_page():
    image = np.full((96, 128), 255, np.uint8)
    image[20:65, 50] = 0  # retained independent thin stroke
    image[8, 8] = 0
    image[80, 110] = 192  # unknown light ink must not be deleted
    mask = np.zeros(image.shape, bool)
    mask[8, 8] = True
    return image, mask


def test_confirmed_sparse_dust_is_removed_even_when_raster_looks_digital():
    image, mask = _sparse_page()
    baseline = prepare_scan_page(image)
    assert baseline.clean_digital
    actual = prepare_scan_page(image, confirmed_noise=mask)
    expected = baseline.binary.copy()
    expected[8, 8] = 255
    assert np.array_equal(actual.binary, expected)
    assert actual.removed_noise_runs == ((8, 8, 9),)
    assert actual.binary[80, 110] == 0
    assert np.array_equal(image, _sparse_page()[0])


def test_mixed_visible_vector_is_protected_before_authorized_mask_application():
    image, mask = _sparse_page()
    vector = np.full_like(image, 255)
    vector[8, 8] = image[8, 8]
    actual = prepare_scan_page(image, pdf_content="mixed",
                               mixed_vector_gray=vector, confirmed_noise=mask)
    assert actual.clean_digital
    assert actual.binary[8, 8] == 0
    assert not actual.removed_noise_runs
    assert mask[8, 8]  # protection must not mutate caller authorization


def test_mixed_hidden_or_different_vector_does_not_claim_visible_ink():
    image, mask = _sparse_page()
    vector = np.full_like(image, 255)
    vector[8, 8] = 128  # not the ink visible in the current canvas
    actual = prepare_scan_page(image, pdf_content="mixed",
                               mixed_vector_gray=vector, confirmed_noise=mask)
    assert actual.binary[8, 8] == 255
    assert actual.removed_noise_runs == ((8, 8, 9),)


@pytest.mark.parametrize("mode", ["no_authorization", "explicit_threshold", "vector_page"])
def test_existing_non_authorized_and_explicit_input_contracts_are_preserved(mode):
    image, mask = _sparse_page()
    kwargs = {"foreground_threshold": 200} if mode == "explicit_threshold" else (
        {"pdf_content": "vector"} if mode == "vector_page" else {})
    baseline = prepare_scan_page(image, **kwargs)
    actual = prepare_scan_page(image, confirmed_noise=None if mode == "no_authorization" else mask,
                               **kwargs)
    assert np.array_equal(actual.binary, baseline.binary)
    assert not actual.removed_noise_runs


@pytest.mark.parametrize("bad", [np.ones((2, 2), bool), np.ones((96, 128), np.uint8)])
def test_invalid_authorization_grid_is_rejected(bad):
    with pytest.raises(ValueError, match="boolean mask in source coordinates"):
        prepare_scan_page(_sparse_page()[0], confirmed_noise=bad)
