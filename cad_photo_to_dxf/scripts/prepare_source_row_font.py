"""Explicitly install the pinned source-row font with its complete license.

The resource registry is shared with layout, export and saved-source audit.
This command never changes the existing DejaVu font, license or TEXT style.
The licensed font binary is fetched only by this explicit setup command;
ordinary application imports and conversions must not download resources.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import Request, urlopen


APP_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(APP_ROOT))

from app.native_objects.source_row_font_registry import SOURCE_ROW_DERIVATIVE, SOURCE_ROW_FONT  # noqa: E402
from scripts.build_source_row_font import build_source_row_font  # noqa: E402


LICENSE_SOURCE_DIRECTORY = APP_ROOT / "resources/fonts"
LOCK_NAME = "source-row-font.lock.json"


def _matches(data: bytes, specification: dict) -> bool:
    return len(data) == specification["bytes"] and sha256(data).hexdigest() == specification["sha256"]


def _atomic_write(target: Path, data: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".source-row-font-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_source_row_font(
    directory: str | Path,
    *,
    font: str | Path | None = None,
    allow_download: bool = True,
) -> dict:
    """Verify all source and derived identities before writing missing members.

    A different existing font or license is a conflict, never an instruction
    to replace an installation. The complete tracked license is copied with
    its exact LF bytes. The whole-font builder creates the matching TTF/LFF
    and full derivative license; each result must equal the fixed registry.
    """
    target = Path(directory)
    specifications = {
        "font": SOURCE_ROW_FONT["font"], "license": SOURCE_ROW_FONT["license"],
        "derived_font": SOURCE_ROW_DERIVATIVE["font"], "derived_lff": SOURCE_ROW_DERIVATIVE["lff"],
        "derived_license": SOURCE_ROW_DERIVATIVE["license"],
    }
    missing = []
    for role, specification in specifications.items():
        path = target / specification["file"]
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise FileExistsError(f"SOURCE_ROW_FONT_RESOURCE_CONFLICT:{path}")
        if not path.exists():
            missing.append(role)
        elif not _matches(path.read_bytes(), specification):
            raise FileExistsError(f"SOURCE_ROW_FONT_RESOURCE_CONFLICT:{path}")

    contents = {}
    if "license" in missing:
        source = LICENSE_SOURCE_DIRECTORY / SOURCE_ROW_FONT["license"]["file"]
        if not source.is_file():
            raise FileNotFoundError(f"SOURCE_ROW_FONT_COMPLETE_LICENSE_MISSING:{source}")
        data = source.read_bytes()
        if not _matches(data, SOURCE_ROW_FONT["license"]):
            raise ValueError("SOURCE_ROW_FONT_LICENSE_HASH_MISMATCH")
        contents["license"] = data
    if "font" in missing:
        if font is not None:
            data = Path(font).read_bytes()
        elif allow_download:
            request = Request(SOURCE_ROW_FONT["source_url"], headers={"User-Agent": "Image-to-CAD-resource-setup"})
            with urlopen(request, timeout=30) as response:
                data = response.read(SOURCE_ROW_FONT["font"]["bytes"] + 1)
        else:
            raise FileNotFoundError("SOURCE_ROW_FONT_OFFLINE_RESOURCE_MISSING")
        if not _matches(data, SOURCE_ROW_FONT["font"]):
            raise ValueError("SOURCE_ROW_FONT_BINARY_HASH_MISMATCH")
        contents["font"] = data

    generated = None
    if any(role.startswith("derived_") for role in missing):
        originals = {role: contents[role] if role in contents else (target / SOURCE_ROW_FONT[role]["file"]).read_bytes()
                     for role in ("font", "license")}
        output, generated = build_source_row_font(originals["font"], originals["license"])
        if generated.get("derivation") != SOURCE_ROW_DERIVATIVE["derivation"]:
            raise ValueError("SOURCE_ROW_FONT_DERIVATION_PROFILE_MISMATCH")
        for role in ("derived_font", "derived_lff", "derived_license"):
            specification = specifications[role]
            data = output.get(specification["file"], b"")
            if not _matches(data, specification):
                raise ValueError("SOURCE_ROW_FONT_DERIVED_RESOURCE_HASH_MISMATCH:" + specification["file"])
            if role in missing:
                contents[role] = data
    target.mkdir(parents=True, exist_ok=True)
    for role in missing:
        _atomic_write(target / specifications[role]["file"], contents[role])
    receipt = {
        "schema": "native-source-row-font-resources-v2",
        "profile": SOURCE_ROW_DERIVATIVE["profile"],
        "source_profile": SOURCE_ROW_FONT["profile"],
        "upstream_commit": SOURCE_ROW_FONT["upstream_commit"],
        "source_url": SOURCE_ROW_FONT["source_url"],
        "font_and_license_verified": True,
        "derived_TTF_LFF_and_full_license_verified": True,
        "generation_executed_this_request": generated is not None,
        "derivation_receipt": generated,
        "resources": {specification["file"]: dict(specification) for specification in specifications.values()},
        "scope": "Explicit source-row resource setup; existing native font and styles unchanged.",
    }
    _atomic_write(target / LOCK_NAME, (json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=APP_ROOT / "resources/fonts")
    parser.add_argument("--font", type=Path, help="Use this unmodified, pinned local font binary.")
    parser.add_argument("--offline", action="store_true", help="Require installed resources or --font; do not download.")
    args = parser.parse_args()
    receipt = prepare_source_row_font(args.directory, font=args.font, allow_download=not args.offline)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
