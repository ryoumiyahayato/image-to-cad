"""Layout binds actual raw cache identities without counting renamed views."""

from copy import deepcopy
import hashlib

import numpy as np
import pytest

from app.native_objects import observation_cache as cache
from app.native_objects import source_text_layout as layout
from app.native_objects import text_regions as base


ENGINE = {
    "name": "tesseract",
    "version": "tesseract test-source-record",
    "executable_sha256": "a" * 64,
    "traineddata_sha256": "b" * 64,
    "language": "eng",
    "oem": 1,
    "CPU_threads": 1,
}
TIGHT = [20, 20, 80, 43]
CURRENT = [18, 18, 83, 46]


@pytest.fixture
def source_contract(tmp_path, monkeypatch):
    # These are synthetic source pixels and immutable observation receipts,
    # not claims that OCR was executed by this layout-only test.
    monkeypatch.setattr(cache, "_USAGE", [])
    image = np.full((64, 100), 255, np.uint8)
    image[20:39, 20:43] = 0
    image[20:39, 60:80] = 0
    image[37:43, 49:52] = 0  # Descending punctuation must remain in the bbox.
    alternatives, boundaries = [], []
    storage = cache.ObservationCache(tmp_path / "raw-cache", create=True)
    for index, psm in enumerate((7, 6)):
        crop_box = [10, 10, 90, 55]
        x0, y0, x1, y1 = crop_box
        crop = image[y0:y1, x0:x1]
        spec = {
            "crop_xyxy_px": crop_box,
            "crop_array_sha256": base.source_array_sha256(crop),
            "psm": psm,
            "pixel_scale": [1, 1],
            "source_pixels_modified": False,
            "language": "eng",
            "recognition_dpi": 200,
            "external_white_padding_px": 0,
            "padding_replaces_source_pixels": False,
        }
        words = [
            {"text": "AB-27,", "confidence": 93.5, "bbox_xyxy_px": [20, 20, 52, 43]},
            {"text": "C3", "confidence": 94.5, "bbox_xyxy_px": [60, 20, 80, 39]},
        ]
        raw = ("test-only immutable raw payload psm=" + str(psm)).encode()
        raw_hash = hashlib.sha256(raw).hexdigest()
        metadata = {
            "status": "COMPLETED",
            "return_code": 0,
            "specification": deepcopy(spec),
            "tsv_sha256": raw_hash,
            "engine_identity": deepcopy(ENGINE),
        }
        request = cache.tesseract_spec(
            crop, crop, padding=0, psm=psm, dpi=200, engine=ENGINE
        )
        receipt = storage.put(
            request,
            raw,
            {
                "origin": "test_only_immutable_receipt_no_OCR",
                "engine": deepcopy(ENGINE),
                "metadata": deepcopy(metadata),
                "raw_text_rewritten": False,
            },
        )
        provenance = base.raw_observation_provenance(
            {**metadata, "raw_observation_cache": receipt}
        )
        key = receipt["key"]
        assert key != base._observation_context_key(spec)
        alternatives.append(
            {
                "context_id": "view-" + str(index),
                "status": "COMPLETED",
                "observation_key": key,
                "words": words,
                "observation_provenance": provenance,
                "raw_artifact": {"sha256": raw_hash},
            }
        )
        boundaries.append(
            {
                "observation_key": key,
                "clean_current_full_line_witness": True,
                "actual_source_component_contacts_crop": [],
                "matches_current_whole_line": True,
            }
        )
    region = {
        "bbox_xyxy_px": CURRENT[:],
        "text": "AB-27, C3",
        "complete": True,
        "words": deepcopy(alternatives[0]["words"]),
        "enclosure": None,
        "completeness_evidence": {
            "alternatives": alternatives,
            "current_boundary_assessment": {
                "observations": boundaries,
                "actual_source_component_contacts_effective_input": [],
                "chosen_word_indices_without_source_ink": [],
            },
        },
    }
    return region, image


def test_cached_observation_identity_preserves_exact_two_context_source_gate(
    source_contract,
):
    region, image = source_contract
    before, pixels = deepcopy(region), image.copy()
    result = layout.choose_source_text_layout(region, image)
    assert result["bbox_xyxy_px"] == TIGHT and result["changed"]
    assert result["status"] == "LAYOUT_SOURCE_BOUND_BBOX_INFLATION_CORRECTED"
    assert len(result["clean_bbox_modes"][0]["independent_observation_keys"]) == 2
    assert all(
        r["eligible"] and r["source_configuration_key"] != r["observation_key"]
        for r in result["observations"]
    )
    assert result["actual_source_ink_check"][
        "contains_all_ink_inside_original_word_union"
    ]
    assert region == before and np.array_equal(image, pixels)


def test_legacy_noncache_identity_retains_same_geometry(source_contract):
    region, image = source_contract
    evidence = region["completeness_evidence"]
    for alternative, boundary in zip(
        evidence["alternatives"],
        evidence["current_boundary_assessment"]["observations"],
    ):
        provenance = alternative["observation_provenance"]
        for key in (
            "raw_observation_cache",
            "raw_observation_key",
            "raw_observation_kind",
        ):
            provenance.pop(key)
        key = base._observation_context_key(provenance["specification"])
        alternative["observation_key"] = boundary["observation_key"] = key
    assert layout.choose_source_text_layout(region, image)["bbox_xyxy_px"] == TIGHT


def test_renamed_same_input_does_not_supply_second_context(source_contract):
    region, image = source_contract
    evidence = region["completeness_evidence"]
    evidence["alternatives"][1] = deepcopy(evidence["alternatives"][0])
    evidence["alternatives"][1]["context_id"] = "renamed-view"
    evidence["current_boundary_assessment"]["observations"][1] = deepcopy(
        evidence["current_boundary_assessment"]["observations"][0]
    )
    result = layout.choose_source_text_layout(region, image)
    assert not result["changed"]
    assert (
        result["observations"][1]["reason"]
        == "DUPLICATE_SOURCE_AND_CONFIGURATION_NO_EXTRA_VOTE"
    )


def test_different_valid_raw_receipt_for_same_source_configuration_is_not_second_context(
    source_contract, tmp_path
):
    region, image = source_contract
    evidence = region["completeness_evidence"]
    second = deepcopy(evidence["alternatives"][0])
    second["context_id"] = "same-crop-and-psm-other-engine"
    provenance = second["observation_provenance"]
    producer = deepcopy(provenance["raw_observation_cache"]["producer"])
    engine = {
        **ENGINE,
        "version": "tesseract other exact engine",
        "executable_sha256": "c" * 64,
    }
    producer["engine"] = producer["metadata"]["engine_identity"] = deepcopy(engine)
    crop = image[10:55, 10:90]
    request = cache.tesseract_spec(crop, crop, padding=0, psm=7, dpi=200, engine=engine)
    storage = cache.ObservationCache(tmp_path / "second-engine-cache", create=True)
    receipt = storage.put(request, b"test-only immutable raw payload psm=7", producer)
    provenance.update(
        engine_identity=engine,
        raw_observation_cache=receipt,
        raw_observation_key=receipt["key"],
    )
    second["observation_key"] = receipt["key"]
    assert second["observation_key"] != evidence["alternatives"][0]["observation_key"]
    evidence["alternatives"][1] = second
    evidence["current_boundary_assessment"]["observations"][1]["observation_key"] = (
        receipt["key"]
    )
    result = layout.choose_source_text_layout(region, image)
    assert not result["changed"]
    assert (
        result["observations"][1]["reason"]
        == "DUPLICATE_SOURCE_AND_CONFIGURATION_NO_EXTRA_VOTE"
    )


@pytest.mark.parametrize(
    "change",
    [
        "alternative_key",
        "provenance_key",
        "receipt_key",
        "receipt_payload",
        "receipt_engine",
        "receipt_config",
        "receipt_status",
        "receipt_absent",
        "crop_pixels",
        "crop_hash",
        "raw_hash",
        "raw_artifact_hash",
    ],
)
def test_wrong_raw_identity_receipt_or_source_cannot_borrow_clean_witness(
    source_contract, change
):
    region, image = source_contract
    evidence = region["completeness_evidence"]
    alternative = evidence["alternatives"][1]
    provenance = alternative["observation_provenance"]
    receipt = provenance["raw_observation_cache"]
    if change == "alternative_key":
        alternative["observation_key"] = "f" * 64
    elif change == "provenance_key":
        provenance["raw_observation_key"] = "f" * 64
    elif change == "receipt_key":
        receipt["key"] = "f" * 64
    elif change == "receipt_payload":
        receipt["payload_sha256"] = "f" * 64
    elif change == "receipt_engine":
        receipt["producer"]["engine"]["traineddata_sha256"] = "f" * 64
    elif change == "receipt_config":
        receipt["producer"]["metadata"]["specification"]["psm"] = 13
    elif change == "receipt_status":
        receipt["producer"]["metadata"]["return_code"] = 1
    elif change == "receipt_absent":
        provenance["raw_observation_cache"] = None
    elif change == "crop_pixels":
        image[11, 11] = 0
    elif change == "crop_hash":
        provenance["specification"]["crop_array_sha256"] = "f" * 64
    elif change == "raw_hash":
        provenance["raw_tsv_sha256"] = "f" * 64
    else:
        alternative["raw_artifact"]["sha256"] = "f" * 64
    result = layout.choose_source_text_layout(region, image)
    assert result["bbox_xyxy_px"] == CURRENT and not result["changed"]
    assert not result["observations"][1]["eligible"]


@pytest.mark.parametrize(
    "change", ["coarse_box", "clipped_comma", "low_confidence", "extra_ink"]
)
def test_layout_still_rejects_coarse_or_clipped_low_confidence_and_extra_source(
    source_contract, change
):
    region, image = source_contract
    evidence = region["completeness_evidence"]
    if change == "extra_ink":
        # Give the changed source correctly rebound receipts so the exact-ink
        # gate, not a stale image hash, has to protect the real extra mark.
        image[44, 81] = 0
        for alternative in evidence["alternatives"]:
            provenance = alternative["observation_provenance"]
            provenance["raw_observation_cache"] = None
            provenance["raw_observation_kind"] = None
            spec = provenance["specification"]
            spec["crop_array_sha256"] = base.source_array_sha256(image[10:55, 10:90])
            key = base._observation_context_key(spec)
            old = alternative["observation_key"]
            alternative["observation_key"] = provenance["raw_observation_key"] = key
            next(
                b
                for b in evidence["current_boundary_assessment"]["observations"]
                if b["observation_key"] == old
            )["observation_key"] = key
    for alternative in evidence["alternatives"]:
        if change == "coarse_box":
            alternative["words"][0]["bbox_xyxy_px"] = [18, 18, 52, 46]
        elif change == "clipped_comma":
            alternative["words"][0]["bbox_xyxy_px"][3] = 42
        elif change == "low_confidence":
            alternative["words"][0]["confidence"] = 84.99
    result = layout.choose_source_text_layout(region, image)
    assert not result["changed"] and result["bbox_xyxy_px"] == CURRENT
    if change in ("coarse_box", "clipped_comma", "extra_ink"):
        assert result["status"] == "LAYOUT_ACTUAL_SOURCE_INK_DISAGREES_WITH_CONSENSUS"
