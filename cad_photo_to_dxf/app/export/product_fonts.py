"""Portable Unicode text styles shared by the scan and native PDF routes."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import shutil
import sys

from fontTools.ttLib import TTFont


def _font_roots(font_directory=None):
    roots = []
    if font_directory:
        roots.append(Path(font_directory))
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS) / "resources" / "fonts")
    roots.append(Path(__file__).resolve().parents[2] / "resources" / "fonts")
    return roots


@lru_cache(maxsize=16)
def _metrics(filename):
    with TTFont(filename, lazy=True) as font:
        cmap = font.getBestCmap() or {}
        units = float(font["head"].unitsPerEm)
        cap = float(getattr(font.get("OS/2"), "sCapHeight", 0) or units * 0.72)
        advances = {cp: float(font["hmtx"][name][0]) for cp, name in cmap.items()}
    return advances, cap, units


def cap_height_ratio(font_path):
    if not font_path:
        return 0.72
    _, cap, units = _metrics(str(font_path))
    return cap / units


def text_width_factor(text, font_path, height, target_width):
    """Map an entire word/line to its observed width; never split it into glyphs."""
    if not font_path or height <= 0 or target_width <= 0:
        return 1.0
    advances, cap, _ = _metrics(str(font_path))
    advance = sum(advances.get(ord(c), advances.get(32, cap * 0.5)) for c in text)
    natural = advance / cap * height
    return max(0.01, min(100.0, target_width / natural)) if natural else 1.0


def install_text_style(doc, output_path, texts=(), *, font_directory=None):
    """Use a complete redistributable font, and keep the license beside the DXF."""
    output = Path(output_path)
    strings = tuple(texts)
    required = {ord(c) for text in strings for c in text if not c.isspace()}
    roots = _font_roots(font_directory)
    source = next((root / name for root in roots for name in (
        "NotoSansCJKsc-Regular.otf", "NotoSansSC-Regular.otf", "NotoSansCJKsc-Medium.otf",
    ) if (root / name).is_file()), None)
    collection = None
    if source is None:
        system = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
        if system.is_file():
            collection = system
        else:
            candidates = [root / "DejaVuSans.ttf" for root in roots]
            candidates.append(Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
            source = next((p for p in candidates if p.is_file()), None)
    warnings, resources = [], []
    style, actual = "wqy-unicode", None
    if source is not None or collection is not None:
        directory = output.parent / "fonts"
        directory.mkdir(parents=True, exist_ok=True)
        actual = directory / (source.name if source else "NotoSansCJKsc-Regular.otf")
        if collection is not None:
            # The installed Noto collection uses SC at index 2. Save the complete
            # original face, retaining all glyphs and glyph IDs (no subsetting).
            if not actual.exists():
                with TTFont(collection, fontNumber=2) as font:
                    font.save(actual)
        elif source.resolve() != actual.resolve():
            if not actual.exists() or actual.read_bytes() != source.read_bytes():
                shutil.copyfile(source, actual)
        resources.append(str(actual))
        license_candidates = [root / n for root in roots for n in (
            "OFL-1.1.txt", "LICENSE", "LICENSE.txt", "DejaVuSans.LICENSE.txt",
        )]
        if collection:
            license_candidates.insert(0, Path("/usr/share/doc/fonts-noto-cjk/copyright"))
        elif source and "DejaVu" in source.name:
            license_candidates.insert(0, Path("/usr/share/doc/fonts-dejavu-core/copyright"))
        license_source = next((p for p in license_candidates if p.is_file()), None)
        if license_source:
            license_path = directory / (actual.stem + ".LICENSE.txt")
            if license_path.resolve() != license_source.resolve():
                shutil.copyfile(license_source, license_path)
            resources.append(str(license_path))
        else:
            warnings.append("FONT_LICENSE_NOT_FOUND: keep the font's original license when distributing")
        missing = required - set(_metrics(str(actual))[0])
        if missing:
            warnings.append("FONT_MISSING_CHARACTERS: " + " ".join(f"U+{c:04X}" for c in sorted(missing)))
        font_name = actual.relative_to(output.parent).as_posix()
    else:
        font_name = "txt"
        warnings.append("PORTABLE_FONT_MISSING: Unicode remains editable; install the bundled Noto CJK font for display")
    if style not in doc.styles:
        doc.styles.new(style, dxfattribs={"font": font_name})
    else:
        doc.styles.get(style).dxf.font = font_name
    return {"style": style, "font_path": str(actual) if actual else None,
            "resources": resources, "warnings": warnings}
