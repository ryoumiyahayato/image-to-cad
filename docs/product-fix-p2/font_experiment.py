"""Reproducible A1 experiment; uses installed resources and native LibreCAD only.

Run from cad_photo_to_dxf with the existing project Python environment.
No production code or source fixtures are modified.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

import ezdxf
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))
from app.ocr.librecad_lff import LffFont

OUT = ROOT / "local-artifacts/product-fix-p2/font-experiment"
OUT.mkdir(parents=True, exist_ok=True)
LC = Path("C:/Users/agcrf/Desktop/LibreCAD/LibreCAD.exe")
FONT_DIR = LC.parent / "resources/fonts"
SAMPLES = ["电施", "图纸目录", "项目编号", "Project Name", "Design Institute",
           "1", "7", "01", "2024.8.15", "®"]
CHARACTERS = list(dict.fromkeys("".join(SAMPLES).replace(" ", "")))
CANDIDATES = [
    ("wqy-unicode", "wqy-unicode.lff", FONT_DIR / "wqy-unicode.lff", None),
    ("unicode", "unicode.lff", FONT_DIR / "unicode.lff", None),
    ("kst32b", "kst32b.lff", FONT_DIR / "kst32b.lff", None),
    ("iso3098", "iso3098.lff", FONT_DIR / "iso3098.lff", None),
    ("simhei", "simhei.ttf", Path("C:/Windows/Fonts/simhei.ttf"), "SimHei"),
    ("simhei.ttf", "simhei.ttf", Path("C:/Windows/Fonts/simhei.ttf"), "SimHei"),
    ("arial", "arial.ttf", Path("C:/Windows/Fonts/arial.ttf"), "Arial"),
    ("NotoSansSC-VF", "NotoSansSC-VF.ttf", Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"), "Noto Sans SC"),
    ("standard", "standard.lff", FONT_DIR / "standard.lff", None),
    ("p2_missing_font", "p2_missing_font.ttf", None, None),
]

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

inventory = []
for path in sorted(FONT_DIR.glob("*.lff")):
    font = LffFont(path)
    inventory.append(dict(font=path.name,
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          missing="".join(c for c in CHARACTERS if font.glyph(c) is None)))
dump(OUT / "installed-lff-inventory.json", inventory)

matrix = []
for name, filename, source_path, family in CANDIDATES:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    style = doc.styles.get(name) if name in doc.styles else doc.styles.new(name)
    style.dxf.font = filename
    if family:
        style.set_extended_font_data(family=family, italic=False, bold=False)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (120, 0), (120, 140), (0, 140)], close=True)
    msp.add_text(name, dxfattribs=dict(style="standard", height=3, insert=(5, 132)))
    for index, sample in enumerate(SAMPLES):
        msp.add_text(sample, dxfattribs=dict(style=name, height=5, width=1,
                                           insert=(8, 120 - index * 11)))
    for ent in msp:
        ent.dxf.true_color = 0
        ent.dxf.lineweight = 13
    dxf = OUT / f"{name}.dxf"
    doc.saveas(dxf)
    audit = ezdxf.readfile(dxf).audit()
    edited = ezdxf.readfile(dxf)
    ent = list(edited.modelspace().query("TEXT"))[1]
    handle = ent.dxf.handle
    ent.dxf.text = "电施7"
    ent.dxf.insert = (9, 121, 0)
    edited_path = OUT / f"{name}.edit-save-reopen.dxf"
    edited.saveas(edited_path)
    reopened = ezdxf.readfile(edited_path)
    assert reopened.entitydb[handle].dxf.text == "电施7"
    assert tuple(reopened.entitydb[handle].dxf.insert) == (9, 121, 0)
    row = dict(style=name, filename=filename, source_path=str(source_path),
               resource_available=source_path is not None and source_path.exists(),
               native_text_count=len(msp.query("TEXT")) - 1,
               audit_errors=len(audit.errors), audit_fixes=len(audit.fixes),
               native_edit_save_reopen="PASS (ezdxf; not GUI)")
    if source_path is not None and source_path.suffix == ".lff":
        font = LffFont(source_path)
        row["missing_glyphs"] = "".join(c for c in CHARACTERS if font.glyph(c) is None)
        row["sample_glyphs"] = {
            c: dict(strokes=len(g.strokes), closed=sum(s[0] == s[-1] for s in g.strokes))
            for c in "电施M17®" if (g := font.glyph(c)) is not None
        }
    elif source_path is not None:
        font = TTFont(source_path)
        cmap = font.getBestCmap()
        row["missing_glyphs"] = "".join(c for c in CHARACTERS if ord(c) not in cmap)
        font.close()
    cmd = [str(LC), "dxf2pdf", "-p", "130x150", "-s", "1", "-c", "-m",
           "-o", str(OUT / f"{name}.pdf"), str(dxf)]
    completed = subprocess.run(cmd, capture_output=True, timeout=60)
    (OUT / f"{name}.render.log").write_bytes(completed.stdout + completed.stderr)
    row["render_command"] = cmd
    row["render_exit_code"] = completed.returncode
    row["pdf_exists"] = (OUT / f"{name}.pdf").exists()
    matrix.append(row)
    print(name, "render", completed.returncode, "pdf", row["pdf_exists"], flush=True)
    png = OUT / f"{name}.png"
    render = subprocess.run(["pdftoppm", "-r", "180", "-singlefile", "-png",
                             str(OUT / f"{name}.pdf"), str(png.with_suffix(""))],
                            capture_output=True, timeout=60)
    (OUT / f"{name}.poppler.log").write_bytes(render.stderr)
    assert render.returncode == 0
    from PIL import Image
    import numpy as np
    gray = np.array(Image.open(png).convert("L"))
    ys, xs = np.where(gray < 180)
    x1, y1, x2, y2 = xs.min(), ys.min(), xs.max(), ys.max()
    # Label-independent same source-coordinate crop; no image enhancement.
    body = gray[int(y1 + (y2-y1)*0.1):int(y1 + (y2-y1)*0.95),
                int(x1 + (x2-x1)*0.035):int(x1 + (x2-x1)*0.97)]
    Image.fromarray(body).save(OUT / f"{name}.body.png")
    row["native_render_body_shape"] = list(body.shape)
    row["native_render_body_sha256"] = hashlib.sha256(body.tobytes()).hexdigest()
    row["native_render_black_pixels"] = int(np.count_nonzero(body < 128))
dump(OUT / "matrix-measurements.json", matrix)
from PIL import ImageDraw
sheet = Image.new("RGB", (2000, 1400), "#ddd")
for index, row in enumerate(matrix):
    tile = Image.open(OUT / f"{row['style']}.body.png").convert("RGB")
    tile.thumbnail((395, 660))
    x, y = (index % 5) * 400, (index // 5) * 700
    ImageDraw.Draw(sheet).text((x + 5, y + 8), row["style"], fill="black")
    sheet.paste(tile, (x + 2, y + 30))
sheet.save(OUT / "comparison.png")
manifest = ROOT / "cad_photo_to_dxf/resources/fonts/manifest.json"
bundled = json.loads(manifest.read_text(encoding="utf-8"))
dump(OUT / "project-font-manifest-availability.json", [
    dict(filename=f["filename"], declared_license=bundled["license"],
         exists=(manifest.parent / f["filename"]).exists()) for f in bundled["fonts"]])
print("DONE", OUT, flush=True)
