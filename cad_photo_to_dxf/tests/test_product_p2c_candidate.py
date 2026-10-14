"""P2C preflight checks; these do not certify an Autodesk engine render."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import ezdxf
import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "product-fix-p2c"
CANDIDATE = json.loads((DOCS / "font-candidate.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    # Real official binaries stay in ignored runtime artifacts until target
    # acceptance. Never download or change Windows font state from a test.
    cached = ROOT / "local-artifacts/product-fix-p2c/comparison/drawing.fonts"
    if not (cached / CANDIDATE["filename"]).exists():
        pytest.skip("P2C official candidate runtime resource not prepared")
    pytest.importorskip("fontTools.ttLib", reason="P2C candidate inspection needs fontTools")
    output = tmp_path_factory.mktemp("p2c-candidate")
    fonts = output / "comparison/drawing.fonts"
    fonts.mkdir(parents=True)
    for name in (CANDIDATE["filename"], "OFL.txt"):
        shutil.copyfile(cached / name, fonts / name)
    spec = importlib.util.spec_from_file_location("p2c_prepare", DOCS / "prepare_candidate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.prepare(output)
    return output, result


def test_official_font_bytes_license_and_actual_chinese_coverage(prepared):
    from fontTools.ttLib import TTFont
    output, result = prepared
    fonts = output / "comparison/drawing.fonts"
    assert sha256((fonts / CANDIDATE["filename"]).read_bytes()).hexdigest() == CANDIDATE["sha256"]
    assert sha256((fonts / "OFL.txt").read_bytes()).hexdigest() == CANDIDATE["license_sha256"]
    assert "SIL OPEN FONT LICENSE Version 1.1" in (fonts / "OFL.txt").read_text()
    with TTFont(fonts / CANDIDATE["filename"]) as font:
        assert "glyf" in font and "CFF " not in font and "CFF2" not in font
        assert all(ord(c) in font.getBestCmap() for c in CANDIDATE["required_characters"])
        assert font["name"].getDebugName(16) == "Noto Sans SC"
    assert result["font"]["font_modified"] is False


@pytest.mark.parametrize("mode", ["comparison", "deployment-A", "deployment-B"])
def test_native_text_roundtrip_style_and_no_outline_conversion(prepared, mode):
    output, _ = prepared
    doc = ezdxf.readfile(output / mode / "drawing.dxf")
    assert not doc.audit().errors
    entities = list(doc.modelspace())
    assert len(entities) == 10
    assert [e.dxf.text for e in entities] == CANDIDATE["comparison_texts"]
    assert all(e.dxftype() == "TEXT" for e in entities)
    style = doc.styles.get("P2C_NOTO_SC_CANDIDATE")
    assert style.dxf.font == CANDIDATE["filename"]
    assert style.get_extended_font_data()[0] == "Noto Sans SC"
    assert all(e.dxf.width == 1.0 for e in entities)


def test_deployment_layout_does_not_claim_engine_loading(prepared):
    output, result = prepared
    assert (output / "deployment-B" / CANDIDATE["filename"]).exists()
    assert not (output / "deployment-A" / CANDIDATE["filename"]).exists()
    assert (output / "comparison/drawing.fonts/OFL.txt").exists()
    assert all(d["actual_font_loading"] == "NOT_RUN" for d in result["dxf"])
    assert result["font"]["target_render"] == "NOT_RUN"
    assert result["status"] == "CANDIDATE_NOT_TARGET_VALIDATED"
    assert result["production_default_changed"] is False
    assert result["system_fonts_changed"] is False
    # The upstream variable's Thin default cannot be described as verified
    # Regular simply because a named Regular instance is present.
    assert result["font"]["default_weight_is_regular"] is False
    assert any(i["coordinates"] == {"wght": 400.0} for i in result["font"]["named_instances"])


def test_legacy_web_handoff_keeps_exact_inputs_without_font_acceptance(prepared):
    output, result = prepared
    web = output / "autocad-web"
    assert (web / "comparison.dxf").read_bytes() == (output / "comparison/drawing.dxf").read_bytes()
    assert sha256((web / CANDIDATE["filename"]).read_bytes()).hexdigest() == CANDIDATE["sha256"]
    manifest = json.loads((web / "package-manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        assert sha256((web / item["filename"]).read_bytes()).hexdigest() == item["sha256"]
    template = json.loads((web / "user-result-template.json").read_text(encoding="utf-8"))
    assert template["PRIMARY_TARGET"] == "AutoCAD Desktop"
    assert template["PRIMARY_LOCAL_DEVELOPMENT_VALIDATOR"] == "Bentley View"
    assert template["TRUEVIEW_STATUS"] == "ABANDONED_INSTALLATION_BLOCKER"
    assert template["AUTOCAD_DESKTOP_RC_ACCEPTANCE"] == "NOT_RUN"
    assert template["AUTODESK_VIEWER_FONT_LOADED"] == "FAIL"
    assert template["AUTODESK_VIEWER_FONT_SUBSTITUTION"] == "YES"
    assert template["AUTODESK_VIEWER_FONT_FIDELITY"] == "NOT_VALIDATED"
    assert template["DESKTOP_AUTOCAD_RC_MANDATORY"] is True
    assert [r["text"] for r in template["comparison_rows"]] == CANDIDATE["comparison_texts"]
    assert all(r["entity_type"] == "TEXT" and r["AUTOCAD_WEB_RENDER_BBOX"] is None
               for r in template["comparison_rows"])
    assert result["web_handoff"]["actual_render"] == "SUPERSEDED_MANUAL_WEB_HANDOFF"
    with ZipFile(output / "autocad-web-user-test.zip") as archive:
        assert set(archive.namelist()) == {i["filename"] for i in manifest["files"]} | {"package-manifest.json"}
        assert archive.read(CANDIDATE["filename"]) == (web / CANDIDATE["filename"]).read_bytes()


@pytest.fixture(scope="module")
def bentley_prepared(prepared):
    output, _ = prepared
    # The complete closed-P2B runtime packages are optional on another host.
    if not all((ROOT / "local-artifacts/product-fix-p2b" / uid / "drawing.dxf").exists()
               for uid in ("W03", "E01", "W01")):
        pytest.skip("Closed P2B real packages unavailable on this host")
    spec = importlib.util.spec_from_file_location("p2c_bentley_prepare", DOCS / "prepare_bentley_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return output, module.prepare(output)


def test_static_400_is_renamed_license_preserved_complete_native_ttf(bentley_prepared):
    from fontTools.ttLib import TTFont
    output, matrix = bentley_prepared
    folder = output / "bentley-view/fonts"
    with TTFont(folder / CANDIDATE["static_derivative"]["filename"]) as static, TTFont(
            folder / CANDIDATE["filename"]) as original:
        assert "fvar" not in static and "gvar" not in static and "glyf" in static
        assert static["OS/2"].usWeightClass == 400
        assert static["name"].getDebugName(1) == "ITC CAD SC"
        assert static["name"].getDebugName(2) == "Regular"
        assert static["name"].getDebugName(6) == "ITCCADSC-Regular"
        assert static.getBestCmap() == original.getBestCmap()
        for name_id in (0, 13, 14):
            assert {n.toUnicode() for n in static["name"].names if n.nameID == name_id} == {
                n.toUnicode() for n in original["name"].names if n.nameID == name_id}
        for n in static["name"].names:
            if n.nameID in (1, 2, 3, 4, 6, 16, 17, 18, 21, 22):
                assert "Source" not in n.toUnicode() and "Noto" not in n.toUnicode()
    assert sha256((folder / "OFL.txt").read_bytes()).hexdigest() == CANDIDATE["license_sha256"]
    for label in ("A", "B"):
        doc = ezdxf.readfile(output / "bentley-view" / f"comparison-{label}.dxf")
        assert all(e.dxftype() == "TEXT" for e in doc.modelspace())
        assert len(doc.modelspace()) == 10 and not doc.audit().errors
    assert all(r["FONT_FOUND"] == "NOT_TESTED" for r in matrix["FONT_MATRIX"])


def test_bentley_real_packages_retain_exact_dxf_and_all_image_bytes(bentley_prepared):
    output, matrix = bentley_prepared
    for row in matrix["REAL_DRAWING_LOAD"]:
        uid = row["drawing"]
        source = ROOT / "local-artifacts/product-fix-p2b" / uid
        copied = output / "bentley-view" / uid
        assert (source / "drawing.dxf").read_bytes() == (copied / "drawing.dxf").read_bytes()
        for asset in row["IMAGE_ASSETS"]:
            assert (source / asset).read_bytes() == (copied / asset).read_bytes()
        assert row["OPEN_TIME"] is None and row["CRASH_OR_HANG"] == "NOT_TESTED"
    assert matrix["PRODUCTION_FONT_STRATEGY_CHANGED"] is False
