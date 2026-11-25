"""Actual pinned outlines, safe offline reuse and honest LibreCAD limitations."""

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil

import pytest

from app import cad_font_resources as resource


@pytest.fixture(scope="module")
def actual_source():
    candidate = os.environ.get("I2CAD_NATIVE_FONT_TEST_SOURCE")
    path = Path(candidate) if candidate else Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    if not path.is_file():
        pytest.skip("Prepare the pinned DejaVu resource; Windows workflow does so before tests")
    data, digest, specification = resource._source(path)
    license_bytes = resource._license_source(path, specification, None)
    return path, data, digest, specification, license_bytes


@pytest.fixture(scope="module")
def actual_build(actual_source):
    return resource.build_native_librecad_font(actual_source[1], actual_source[4])


def test_actual_entire_cmap_build_is_pinned_and_keeps_original_permission(actual_source, actual_build):
    _, source, digest, specification, original_license = actual_source
    outputs, receipt = actual_build
    for role, name in (("lff", resource.LFF_FILENAME), ("derived_license", resource.LICENSE_FILENAME)):
        assert len(outputs[name]) == specification[role]["bytes"]
        assert sha256(outputs[name]).hexdigest() == specification[role]["sha256"]
    assert outputs[resource.LICENSE_FILENAME].startswith(original_license)
    assert digest.encode() in outputs[resource.LICENSE_FILENAME]
    assert b"DERIVED FONT RESOURCE" in outputs[resource.LICENSE_FILENAME]
    assert receipt["coverage"]["outlined_glyphs"] == 5857
    assert receipt["coverage"]["ascii_printable_complete"] is True
    assert receipt["layout"]["source_outlines_preserved"] is True
    assert receipt["layout"]["added_spacing_geometry"] is False
    assert receipt["layout"]["arbitrary_string_TTF_geometry_equivalent"] is False
    assert receipt["drawing_or_recognition_inputs"] is False
    assert receipt["source_ttf_modified"] is False
    assert sha256(source).hexdigest() == digest


def test_ascii_outlines_are_direct_source_paths_without_spacing_markers(actual_source, actual_build):
    from ezdxf.fonts import lff
    from ezdxf.fonts.ttfonts import TTFontRenderer
    from fontTools.ttLib import TTFont

    native = TTFont(BytesIO(actual_source[1]), recalcTimestamp=False)
    try:
        renderer = TTFontRenderer(native)
        cap = renderer.font_measurements.cap_height
        converted = lff.loads(actual_build[0][resource.LFF_FILENAME].decode("utf-8"))
        for cp in range(33, 127):
            expected = []
            for contour in renderer.get_glyph_path(chr(cp)).sub_paths():
                points = list(contour.flattening(cap * resource.CURVE_FLATTENING))
                if points and points[-1] != points[0]:
                    points.append(points[0])
                if len(points) >= 2:
                    expected.append(points)
            actual = converted[cp].polylines
            assert len(actual) == len(expected)
            for polyline, original in zip(actual, expected):
                assert len(polyline) == len(original)
                for result, point in zip(polyline, original):
                    assert result[0] == pytest.approx(point.x * 9 / cap, abs=1e-11)
                    assert result[1] == pytest.approx(point.y * 9 / cap, abs=1e-11)
    finally:
        native.close()


def test_readonly_inspection_and_second_prepare_preserve_all_bytes_and_mtimes(actual_source, tmp_path):
    source_path = actual_source[0]
    original = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in source_path.parent.iterdir() if path.is_file() and path.name in
                {"DejaVuSans.ttf", "DejaVuSans.LICENSE.txt", "FONT_LICENSE_DejaVu.txt"}}
    cache = tmp_path / "cache"
    assert resource.inspect_librecad_resource(source_path, cache)["status"] == "missing"
    assert not cache.exists()
    first = resource.ensure_librecad_resource(source_path, cache)
    assert first["status"] == "verified" and first["cad_loaded"] is False
    directory = Path(first["path"]).parent
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
    assert resource.ensure_librecad_resource(source_path, cache) == first
    assert resource.inspect_librecad_resource(source_path, cache) == first
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
    assert original == {name: ((source_path.parent / name).read_bytes(),
                              (source_path.parent / name).stat().st_mtime_ns) for name in original}


@pytest.mark.parametrize("member", [resource.LFF_FILENAME, resource.LICENSE_FILENAME, resource.RECEIPT_FILENAME])
def test_different_or_partial_cache_is_preserved_not_replaced(actual_source, actual_build, tmp_path, member):
    cache = tmp_path / "cache"
    directory = cache / actual_source[3]["profile"]
    directory.mkdir(parents=True)
    contents = dict(actual_build[0])
    contents[resource.RECEIPT_FILENAME] = (json.dumps(actual_build[1]) + "\n").encode()
    for name, data in contents.items():
        (directory / name).write_bytes(data)
    (directory / member).write_bytes(b"different user's content; preserve")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(FileExistsError, match="CACHE_(IDENTITY|INCOMPLETE)"):
        resource.ensure_librecad_resource(actual_source[0], cache)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def test_unknown_ttf_and_mismatched_license_fail_before_cache_writes(actual_source, tmp_path):
    source = tmp_path / "unknown.ttf"
    source.write_bytes(b"not a known font")
    with pytest.raises(ValueError, match="UNRECOGNIZED_SOURCE"):
        resource.ensure_librecad_resource(source, tmp_path / "cache")
    wrong_license = tmp_path / "wrong-license.txt"
    wrong_license.write_bytes(b"not permission")
    with pytest.raises(ValueError, match="MATCHING_LICENSE_REQUIRED"):
        resource.ensure_librecad_resource(actual_source[0], tmp_path / "cache", source_license=wrong_license)
    assert not (tmp_path / "cache").exists()


def test_receipt_cannot_claim_nonexistent_glyphs_or_exact_arbitrary_spacing(actual_source, actual_build, tmp_path):
    cache = tmp_path / "cache"
    directory = cache / actual_source[3]["profile"]
    directory.mkdir(parents=True)
    for name, data in actual_build[0].items():
        (directory / name).write_bytes(data)
    receipt = json.loads(json.dumps(actual_build[1]))
    receipt["coverage"]["codepoint_ranges"].append([0x10FFFF, 0x10FFFF])
    (directory / resource.RECEIPT_FILENAME).write_text(json.dumps(receipt))
    with pytest.raises(FileExistsError, match="CACHE_IDENTITY_CONFLICT"):
        resource.inspect_librecad_resource(actual_source[0], cache)


def test_character_coverage_covers_edits_and_distinguishes_shaping(actual_build):
    record = {"coverage": actual_build[1]["coverage"]}
    assert resource.check_librecad_character_coverage(record, "RX-C9,04 / z=8.2") == {
        "complete": True, "missing": [], "shaping_or_non_bmp_unverified": []}
    unknown = resource.check_librecad_character_coverage(record, "\U0010ffff")
    assert unknown["complete"] is False and unknown["missing"] == ["U+10FFFF"]
    combining = resource.check_librecad_character_coverage(record, "a\u0301")
    assert combining["complete"] is False and combining["shaping_or_non_bmp_unverified"] == ["U+0301"]


def test_source_specific_cache_does_not_overwrite_other_font_or_user_files(actual_source, tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    source = folder / "DejaVuSans.ttf"
    shutil.copyfile(actual_source[0], source)
    (folder / "FONT_LICENSE_DejaVu.txt").write_bytes(actual_source[4])
    (folder / "I2CAD_TEXT.lff").write_bytes(b"user's unrelated same-name font")
    record = resource.ensure_librecad_resource(source, tmp_path / "cache")
    assert Path(record["path"]).parent.name == actual_source[3]["profile"]
    assert (folder / "I2CAD_TEXT.lff").read_bytes() == b"user's unrelated same-name font"
