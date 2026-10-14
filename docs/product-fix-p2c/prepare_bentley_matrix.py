"""Build license-reviewed A/B DXFs and preserve complete real CAD packages.

Preparation is not renderer acceptance. No production exporter, font installer,
OCR, IMAGE mask, or structural geometry is changed.
"""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import shutil

import ezdxf
import fontTools
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def prepare(output: Path) -> dict:
    candidate = json.loads((HERE / "font-candidate.json").read_text(encoding="utf-8"))
    derivative = candidate["static_derivative"]
    review = HERE / derivative["license_review"]
    assert review.is_file(), "Record OFL naming review before creating B"
    source = output / "comparison/drawing.fonts" / candidate["filename"]
    license_file = output / "comparison/drawing.fonts/OFL.txt"
    assert sha256(source.read_bytes()).hexdigest() == candidate["sha256"]
    assert sha256(license_file.read_bytes()).hexdigest() == candidate["license_sha256"]
    assert "Reserved Font Name 'Source'" in license_file.read_text()
    destination = output / "bentley-view"
    fonts = destination / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, fonts / source.name)
    shutil.copyfile(license_file, fonts / "OFL.txt")
    shutil.copyfile(review, fonts / review.name)
    with TTFont(source, recalcTimestamp=False) as original:
        copyrights = {n.toUnicode() for n in original["name"].names if n.nameID == 0}
        licenses = {n.toUnicode() for n in original["name"].names if n.nameID in (13, 14)}
        static = instantiateVariableFont(original, derivative["axes"], inplace=False, updateFontNames=True)
        family, style = derivative["family"], derivative["style"]
        rename = {1: family, 2: style, 3: "ITCCADSC-Regular-P2C-400", 4: f"{family} {style}",
                  6: derivative["postscript_name"], 16: family, 17: style,
                  18: f"{family} {style}", 21: family, 22: style}
        for record in static["name"].names:
            if record.nameID in rename:
                record.string = rename[record.nameID].encode(record.getEncoding())
        static["name"].names = [n for n in static["name"].names if n.nameID != 25]
        for name_id, value in rename.items():
            static["name"].setName(value, name_id, 3, 1, 0x409)
        static["name"].setName(
            "Modified static weight 400 derivative of official Noto Sans SC; see accompanying FONTLOG.json and OFL.txt.",
            10, 3, 1, 0x409)
        assert "fvar" not in static and "gvar" not in static
        assert static["OS/2"].usWeightClass == 400
        assert copyrights == {n.toUnicode() for n in static["name"].names if n.nameID == 0}
        assert licenses == {n.toUnicode() for n in static["name"].names if n.nameID in (13,14)}
        assert all(ord(c) in static.getBestCmap() for c in candidate["required_characters"])
        static_path = fonts / derivative["filename"]
        static.save(static_path)
    fontlog = {"source_sha256": candidate["sha256"], "source_url": candidate["source_url"],
               "license": candidate["license"], "reserved_font_names": ["Source"],
               "license_review": derivative["license_review"], "fontTools_version": fontTools.__version__,
               "modified_version": True, "coordinates": derivative["axes"], "name_changes": rename,
               "output_sha256": sha256(static_path.read_bytes()).hexdigest(),
               "production_bundling": derivative["production_bundling"]}
    (fonts / "FONTLOG.json").write_text(json.dumps(fontlog, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    rows = []
    for label, path, family in (("A", fonts / source.name, "Noto Sans SC"),
                                ("B", static_path, derivative["family"])):
        with TTFont(path) as font:
            rows.append({"CANDIDATE": label, "FONT_FILE": path.name, "FONT_FAMILY": family,
                "INTERNAL_LEGACY_FAMILY": font["name"].getDebugName(1),
                "FONT_WEIGHT": {"requested": "Regular 400", "metadata": font["OS/2"].usWeightClass,
                                "renderer_observed": None},
                "VARIABLE_OR_STATIC": "VARIABLE" if "fvar" in font else "STATIC",
                "FONT_FOUND": "NOT_TESTED", "FONT_SUBSTITUTION": "NOT_TESTED",
                "CHINESE": "NOT_TESTED", "LATIN": "NOT_TESTED", "DIGITS": "NOT_TESTED",
                "REGISTERED_SYMBOL": "NOT_TESTED", "FILLED_APPEARANCE": "NOT_TESTED",
                "TEXT_WIDTH": None, "TEXT_HEIGHT": None, "DXF_NATIVE_TEXT_PRESERVED": True,
                "font_sha256": sha256(path.read_bytes()).hexdigest()})
        doc = ezdxf.new("R2010", setup=True)
        doc.units = ezdxf.units.MM
        style = doc.styles.new(f"P2C_{label}_CANDIDATE", dxfattribs={"font": path.name})
        style.set_extended_font_data(family, italic=False, bold=False)
        for i, content in enumerate(candidate["comparison_texts"]):
            doc.modelspace().add_text(content, dxfattribs={"style": style.dxf.name, "height": 5,
                "width": 1, "insert": (10, 110-i*10)})
        audit = doc.audit()
        assert not audit.errors and not audit.fixes
        doc.saveas(destination / f"comparison-{label}.dxf")
    drawings = []
    for uid in ("W03", "E01", "W01"):
        # Untouched complete closed-P2B package. No candidate font substitution
        # in this first load-test baseline, and no re-export or reconstruction.
        src = ROOT / "local-artifacts/product-fix-p2b" / uid
        target = destination / uid
        target.mkdir(exist_ok=True)
        shutil.copyfile(src / "drawing.dxf", target / "drawing.dxf")
        doc = ezdxf.readfile(target / "drawing.dxf")
        assets = []
        for entity in doc.modelspace().query("IMAGE"):
            filename = entity.image_def.dxf.filename
            assert not Path(filename).is_absolute() and ":" not in filename
            shutil.copyfile(src / filename, target / filename)
            assets.append(filename)
        audit = doc.audit()
        assert not audit.errors
        drawings.append({"drawing": uid, "FILE_SIZE": (target / "drawing.dxf").stat().st_size,
            "ENTITY_COUNT": len(doc.modelspace()), "IMAGE_ASSETS": assets,
            "SOURCE_DXF_SHA256": sha256((src / "drawing.dxf").read_bytes()).hexdigest(),
            "COPIED_DXF_SHA256": sha256((target / "drawing.dxf").read_bytes()).hexdigest(),
            "OPEN_TIME": None, "PEAK_MEMORY_IF_AVAILABLE": None,
            "PAN_ZOOM_RESPONSIVENESS": "NOT_TESTED", "TEXT_VISIBLE": "NOT_TESTED",
            "IMAGE_ASSETS_VISIBLE": "NOT_TESTED", "STRUCTURAL_GEOMETRY_VISIBLE": "NOT_TESTED",
            "MISSING_REFERENCES": "NOT_TESTED", "FONT_SUBSTITUTION": "NOT_TESTED",
            "CRASH_OR_HANG": "NOT_TESTED", "existing_LFF_style": True,
            "test_order": "after comparison passes; stop after W03 if suitability is established"})
    result = {"PRIMARY_TARGET": "AutoCAD Desktop", "PRIMARY_LOCAL_DEVELOPMENT_VALIDATOR": "Bentley View",
              "BENTLEY_VIEW_RENDER": "NOT_RUN", "FONT_MATRIX": rows, "REAL_DRAWING_LOAD": drawings,
              "AUTOCAD_DESKTOP_RC_ACCEPTANCE": "MANDATORY_NOT_RUN", "PRODUCTION_FONT_STRATEGY_CHANGED": False}
    (destination / "matrix-and-load-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().output), ensure_ascii=False, indent=2))
