"""Whole-font resource integrity; no recognition or drawing fixture is used."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
import pytest

from app.native_objects.source_row_font_registry import SOURCE_ROW_DERIVATIVE, SOURCE_ROW_FONT
from scripts.build_source_row_font import build_source_row_font


@pytest.fixture(scope="module")
def original_resources():
    folder = Path(__file__).resolve().parents[1] / "resources/fonts"
    font = folder / SOURCE_ROW_FONT["font"]["file"]
    if not font.is_file():
        pytest.skip("Prepare the pinned font; Windows workflow does so before tests")
    return font.read_bytes(), (folder / SOURCE_ROW_FONT["license"]["file"]).read_bytes()


@pytest.fixture(scope="module")
def actual_build(original_resources):
    return build_source_row_font(*original_resources)


def test_actual_whole_font_build_matches_every_fixed_resource(actual_build):
    outputs, receipt = actual_build
    assert receipt["derivation"] == SOURCE_ROW_DERIVATIVE["derivation"]
    assert set(outputs) == {SOURCE_ROW_DERIVATIVE[role]["file"] for role in ("font", "lff", "license")}
    for role in ("font", "lff", "license"):
        specification = SOURCE_ROW_DERIVATIVE[role]
        assert len(outputs[specification["file"]]) == specification["bytes"]
        assert sha256(outputs[specification["file"]]).hexdigest() == specification["sha256"]
    assert receipt["drawing_or_recognition_inputs"] is False
    assert receipt["LFF_metrics"]["every_possible_unicode_string_is_equivalent"] is False


def test_second_actual_generation_is_byte_identical_without_a_clock_input(original_resources, actual_build):
    second, receipt = build_source_row_font(*original_resources)
    assert second == actual_build[0]
    assert receipt == actual_build[1]


def test_font_origin_copyright_and_source_timestamps_are_preserved(original_resources, actual_build):
    original = TTFont(BytesIO(original_resources[0]), recalcTimestamp=False)
    derived = TTFont(BytesIO(actual_build[0][SOURCE_ROW_DERIVATIVE["font"]["file"]]), recalcTimestamp=False)

    def original_copyright(font):
        return [(row.platformID, row.platEncID, row.langID, row.toUnicode()) for row in font["name"].names if row.nameID == 0]

    assert original_copyright(original) == original_copyright(derived)
    assert original["head"].created == derived["head"].created
    assert original["head"].modified == derived["head"].modified
    assert original.getGlyphOrder() == derived.getGlyphOrder()
    assert original.getBestCmap() == derived.getBestCmap()
    assert all(tag not in derived for tag in ("kern", "GPOS", "GSUB"))
    versions = [row.toUnicode() for row in derived["name"].names if row.nameID == 5]
    assert versions and all(SOURCE_ROW_DERIVATIVE["derivation"] in row and "private" not in row.lower() for row in versions)
    original.close()
    derived.close()


def test_full_original_permission_and_modified_resource_notice_are_both_delivered(original_resources, actual_build):
    outputs = actual_build[0]
    license_bytes = outputs[SOURCE_ROW_DERIVATIVE["license"]["file"]]
    assert license_bytes.startswith(original_resources[1])
    assert b"MODIFIED FONT RESOURCE" in license_bytes
    assert b"scripts/build_source_row_font.py" in license_bytes
    assert b"GNU LESSER GENERAL PUBLIC LICENSE" in license_bytes
    assert b"As a special exception" in license_bytes
    assert b"\r" not in license_bytes and b"\r" not in outputs[SOURCE_ROW_DERIVATIVE["lff"]["file"]]


@pytest.mark.parametrize("index", [0, 1])
def test_no_other_font_or_reduced_permission_text_is_accepted(original_resources, index):
    inputs = list(original_resources)
    inputs[index] = inputs[index][:-1] + b"!"
    with pytest.raises(ValueError, match="SOURCE_ROW_DERIVATION_ORIGINAL_(FONT|LICENSE)_MISMATCH"):
        build_source_row_font(*inputs)
