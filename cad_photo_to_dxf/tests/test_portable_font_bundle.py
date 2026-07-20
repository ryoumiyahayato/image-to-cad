from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_ROOT = PROJECT_ROOT / "resources" / "fonts"


def test_portable_font_manifest_uses_pinned_official_noto_sources() -> None:
    payload = json.loads((FONT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    fonts = payload["fonts"]

    assert payload["license"] == "SIL Open Font License 1.1"
    assert payload["source_repository"] == "notofonts/noto-cjk"
    assert len(fonts) >= 4
    filenames = [item["filename"] for item in fonts]
    assert len(filenames) == len(set(filenames))
    assert "NotoSansCJKsc-Regular.otf" in filenames
    assert "NotoSansMonoCJKsc-Regular.otf" in filenames
    assert "NotoSerifCJKsc-Regular.otf" in filenames
    assert all(item["url"].startswith("https://raw.githubusercontent.com/notofonts/noto-cjk/") for item in fonts)
    assert all("/main/" not in item["url"] for item in fonts)
    assert {item["category"] for item in fonts} >= {"sans", "mono", "serif"}


def test_build_prepares_and_packages_font_bundle() -> None:
    script = (PROJECT_ROOT / "scripts" / "prepare_cad_fonts.py").read_text(
        encoding="utf-8"
    )
    spec = (PROJECT_ROOT / "cad_photo_to_dxf.spec").read_text(encoding="utf-8")

    assert "def prepare_font_bundle" in script
    assert "bundle.lock.json" in script
    assert "sha256" in script
    assert "strict=True" in spec
    assert "resources/fonts" in spec
    assert "prepare_font_bundle" in spec
