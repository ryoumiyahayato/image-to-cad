"""Prepare an unmodified official TTF and native TEXT comparison, not acceptance.

Run with the existing project Python. No application font registration, Windows
installation, production exporter changes, or substitute renderer is performed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED

import ezdxf
from fontTools.ttLib import TTFont


HERE = Path(__file__).resolve().parent


def prepare_web_handoff(output: Path, candidate: dict) -> dict:
    """Package exact prepared inputs; only the human runs Autodesk Web."""
    folder = output / "autocad-web"
    folder.mkdir(exist_ok=True)
    plan = json.loads((HERE / "validation-plan.json").read_text(encoding="utf-8"))
    fonts = output / "comparison/drawing.fonts"
    for source, name in ((output / "comparison/drawing.dxf", "comparison.dxf"),
                         (fonts / candidate["filename"], candidate["filename"]),
                         (fonts / "OFL.txt", "OFL.txt"),
                         (HERE / "AUTOCAD-WEB-USER-TEST.md", "AUTOCAD-WEB-USER-TEST.md")):
        shutil.copyfile(source, folder / name)
    doc = ezdxf.readfile(folder / "comparison.dxf")
    rows = [{"text": e.dxf.text, "entity_type": e.dxftype(), "style": e.dxf.style,
             "TEXT_INSERT": list(e.dxf.insert), "TEXT_HEIGHT": e.dxf.height,
             "WIDTH_FACTOR": e.dxf.width, "AUTOCAD_WEB_RENDER_BBOX": None,
             "appearance": "PENDING_USER_TEST", "notes": ""}
            for e in doc.modelspace()]
    result = {**plan, "font_filename": candidate["filename"],
              "font_sha256": candidate["sha256"], "font_family_observed": None,
              "font_style_observed": None, "font_weight_observed": None,
              "font_substitution_observed": None, "screenshots": [],
              "comparison_rows": rows, "user_notes": ""}
    (folder / "user-result-template.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    names = ("comparison.dxf", candidate["filename"], "OFL.txt",
             "AUTOCAD-WEB-USER-TEST.md", "user-result-template.json")
    manifest = {"validation": plan, "files": [
        {"filename": name, "bytes": (folder / name).stat().st_size,
         "sha256": sha256((folder / name).read_bytes()).hexdigest()} for name in names]}
    (folder / "package-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with ZipFile(output / "autocad-web-user-test.zip", "w", ZIP_DEFLATED) as archive:
        for name in (*names, "package-manifest.json"):
            archive.write(folder / name, name)
    return {"path": "autocad-web", "zip": "autocad-web-user-test.zip",
            "validation": plan, "font_sha256": candidate["sha256"],
            "native_text_count": len(rows), "actual_render": "SUPERSEDED_MANUAL_WEB_HANDOFF"}


def checked_download(url: str, path: Path, expected_hash: str) -> None:
    if not path.exists():
        with urlopen(Request(url, headers={"User-Agent": "ImageToCAD-P2C"}), timeout=60) as response:
            data = response.read()
        if sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"Official resource checksum mismatch: {path.name}")
        path.write_bytes(data)
    if sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(f"Resource checksum mismatch: {path.name}")


def prepare(output: Path) -> dict:
    candidate = json.loads((HERE / "font-candidate.json").read_text(encoding="utf-8"))
    fonts = output / "comparison" / "drawing.fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    font_path = fonts / candidate["filename"]
    checked_download(candidate["source_url"], font_path, candidate["sha256"])
    checked_download(candidate["license_url"], fonts / "OFL.txt", candidate["license_sha256"])
    with TTFont(font_path) as font:
        cmap = font.getBestCmap()
        missing = [c for c in candidate["required_characters"] if ord(c) not in cmap]
        if missing or "glyf" not in font or "CFF " in font or "CFF2" in font:
            raise ValueError(f"Required TrueType outlines/coverage failed: {missing}")
        names = {str(n): font["name"].getDebugName(n) for n in (1, 2, 4, 6, 16, 17)}
        axes = [{"tag": a.axisTag, "min": a.minValue, "default": a.defaultValue,
                 "max": a.maxValue} for a in font["fvar"].axes] if "fvar" in font else []
        instances = [{"name": font["name"].getDebugName(i.subfamilyNameID),
                      "coordinates": i.coordinates} for i in font["fvar"].instances] if axes else []
        font_result = {"filename": candidate["filename"], "sha256": candidate["sha256"],
                       "source_url": candidate["source_url"], "license": candidate["license"],
                       "format": "TTF", "outlines": "glyf", "variant": "VARIABLE" if axes else "STATIC",
                       "internal_names": names, "axes": axes, "named_instances": instances,
                       "required_characters": candidate["required_characters"], "missing_glyphs": missing,
                       "cmap_size": len(cmap), "font_modified": False,
                       "target_render": "NOT_RUN", "default_weight_is_regular": all(
                           a["default"] == 400 for a in axes if a["tag"] == "wght")}
    outputs = []
    for mode in ("comparison", "deployment-A", "deployment-B"):
        folder = output / mode
        folder.mkdir(exist_ok=True)
        doc = ezdxf.new("R2010", setup=True)
        doc.units = ezdxf.units.MM
        style = doc.styles.new("P2C_NOTO_SC_CANDIDATE", dxfattribs={"font": candidate["filename"]})
        style.set_extended_font_data("Noto Sans SC", italic=False, bold=False)
        msp = doc.modelspace()
        for index, content in enumerate(candidate["comparison_texts"]):
            msp.add_text(content, dxfattribs={"style": style.dxf.name, "height": 5.0,
                                            "width": 1.0, "insert": (10, 110 - index * 10)})
        audit = doc.audit()
        if audit.errors or audit.fixes:
            raise ValueError("Comparison DXF audit failed")
        path = folder / "drawing.dxf"
        doc.saveas(path)
        reread = ezdxf.readfile(path)
        assert [e.dxf.text for e in reread.modelspace()] == candidate["comparison_texts"]
        assert all(e.dxftype() == "TEXT" for e in reread.modelspace())
        if mode == "deployment-B":
            shutil.copyfile(font_path, folder / candidate["filename"])
            shutil.copyfile(fonts / "OFL.txt", folder / "OFL.txt")
        outputs.append({"mode": mode, "path": str(path.relative_to(output)), "native_text_count": 10,
                        "audit_errors": 0, "audit_fixes": 0, "outline_entities": 0,
                        "actual_font_loading": "NOT_RUN"})
    note = (
        "UNVALIDATED P2C COMPARISON PACKAGE\n"
        "Native TEXT uses Noto Sans SC candidate; no target render has passed.\n"
        "deployment-A requires the exact TTF installed in Windows.\n"
        "deployment-B includes that TTF beside the DXF to test file lookup.\n"
        "comparison/drawing.fonts is a portability/reference candidate only.\n"
        "Font presence alone does not establish Autodesk engine loading.\n"
        "Primary local development visual validation now uses Bentley View.\n"
        "Variable default weight and named Regular instance remain unverified.\n"
    )
    (output / "FONT-REQUIREMENT.txt").write_text(note, encoding="utf-8")
    result = {"status": "CANDIDATE_NOT_TARGET_VALIDATED", "font": font_result, "dxf": outputs,
              "production_default_changed": False, "system_fonts_changed": False,
              "web_handoff": prepare_web_handoff(output, candidate)}
    (output / "candidate-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), ensure_ascii=False, indent=2))
