"""Pinned, offline LibreCAD companions for the existing native DejaVu TEXT.

LibreCAD 2.2.1.6 resolves a TEXT style by its LFF/CXF basename, ignoring the
DXF STYLE's TrueType filename.  This module derives the complete LFF from the
actual, hash-verified TTF beside a result or in the application resource bundle.
It never changes that TTF, a drawing, the source-row font, or CAD settings.

LFF has no per-glyph advance field.  Original outlines are retained and one
whole-font median right-side gap is used.  This is an explicit outline-format
conversion, not a promise of identical TrueType spacing for arbitrary strings.
No selected text, drawing coordinate or recognition answer enters the builder.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
import json
import math
from pathlib import Path
import re
from statistics import median
import tempfile
import unicodedata


DERIVATION = "original-outlines-whole-font-median-right-gap-v1"
LFF_FILENAME = "I2CAD_TEXT.lff"
LICENSE_FILENAME = "I2CAD_TEXT.LICENSE.txt"
RECEIPT_FILENAME = "native-librecad-font.lock.json"
CURVE_FLATTENING = 1 / 4096
LIBRECAD_VERSION = "2.2.1.6"
LIBRECAD_COMMIT = "29179cdc09fbec439a1cb0931d92e67f4c0f6622"
REFERENCE_BUILD_DEPENDENCIES = {"fonttools": "4.68.0", "ezdxf": "1.4.5"}

# The two existing deployments remain separate identities.  No new TTF is
# created, installed in Windows, or substituted for either original.
NATIVE_LIBRECAD_FONTS = {
    "57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e": {
        "profile": "native-dejavu-2.37-linux-57f73e11-lff-v1",
        "font": "DejaVuSans.ttf",
        "bytes": 759720,
        "version": "DejaVu Sans 2.37, frozen Linux distribution build",
        "source_url": "https://dejavu-fonts.github.io/",
        "license": {
            "bytes": 3859,
            "sha256": "63d3ba759d12804c5b31a9d5940d855c1820d1f5999e6b0872eb1c7ff045fbc9",
        },
        "lff": {
            "bytes": 26918293,
            "sha256": "598d0c841448ce0d0b5a566944ac0225d240208591ebdd74193bfd258c81c040",
        },
        "derived_license": {
            "bytes": 5571,
            "sha256": "92b762ac6fcc0ea504f10358115e92e6d9c3ad7f0ab4648a4cca8f8c828072f3",
        },
    },
    "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954": {
        "profile": "native-dejavu-2.37-official-7da195a7-lff-v1",
        "font": "DejaVuSans.ttf",
        "bytes": 757076,
        "version": "DejaVu Sans 2.37, official release",
        "source_url": "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
        "version_2_37/dejavu-sans-ttf-2.37.zip",
        "license": {
            "bytes": 8816,
            "sha256": "7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93",
        },
        "lff": {
            "bytes": 25478769,
            "sha256": "5bb91a4d8328056e787e61f3e2b10e387772342dfce3de015c714884656f5f47",
        },
        "derived_license": {
            "bytes": 10585,
            "sha256": "3c950843cd46ae75efb98871cdca34ac0dc21b191e38a093e9554257b645a00a",
        },
    },
}


def _identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


def _matches(data: bytes, specification: dict) -> bool:
    return len(data) == specification.get("bytes") and sha256(data).hexdigest() == specification.get("sha256")


def _source(source_ttf: Path) -> tuple[bytes, str, dict]:
    path = Path(source_ttf)
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    specification = NATIVE_LIBRECAD_FONTS.get(digest)
    if specification is None or len(data) != specification["bytes"]:
        raise ValueError("NATIVE_LIBRECAD_FONT_UNRECOGNIZED_SOURCE:" + str(path))
    return data, digest, specification


def _license_source(source_ttf: Path, specification: dict, source_license: Path | None) -> bytes:
    candidates = [Path(source_license)] if source_license is not None else [
        Path(source_ttf).parent / name
        for name in ("FONT_LICENSE_DejaVu.txt", "DejaVuSans.LICENSE.txt")
    ]
    for candidate in candidates:
        if candidate.is_file():
            data = candidate.read_bytes()
            if _matches(data, specification["license"]):
                return data
    raise ValueError("NATIVE_LIBRECAD_FONT_MATCHING_LICENSE_REQUIRED")


def _ranges(codepoints: list[int]) -> list[list[int]]:
    answer: list[list[int]] = []
    for codepoint in sorted(set(codepoints)):
        if answer and answer[-1][1] + 1 == codepoint:
            answer[-1][1] = codepoint
        else:
            answer.append([codepoint, codepoint])
    return answer


def _derived_license(original: bytes, source_sha256: str, specification: dict) -> bytes:
    notice = f"""

DERIVED FONT RESOURCE - I2CAD TEXT LIBRECAD COMPANION, VERSION 1.0
Derivation profile: {DERIVATION}
Source profile: {specification['profile']}
Source version: {specification['version']}
Original source: {specification['source_url']}
Original TTF SHA256: {source_sha256}
Original license SHA256: {specification['license']['sha256']}

This LFF is an outline-format conversion of the complete source cmap. It is
not the unmodified original TrueType font. Original outlines and bearings are
retained and scaled to LibreCAD's nine-unit cap-height grid. Curves are flattened
at a fixed 1/4096 cap-height tolerance. No outline is added to encode spacing.
The global letter gap is the median of original advance minus exact outline
maxX over every mapped outlined glyph with a positive advance. Space retains
the original space advance. No selected drawing, label or expected text enters
the conversion. The original TTF remains unchanged.

LibreCAD 2.2.1.6 LFF has only one global letter gap and no per-glyph advance or
kerning field. Consequently variable TrueType advances, complex shaping and
arbitrary Unicode text are not promised to render identically. The generated
resource receipt records the limitation and character coverage. Actual drawing
layout and neighboring objects must be checked separately.

Build implementation: app/cad_font_resources.py
Explicit setup entry: scripts/prepare_native_librecad_font.py
Target LibreCAD source: {LIBRECAD_COMMIT}
The original copyright, trademark and permission notices above are preserved.
"""
    return original + notice.encode("utf-8")


def build_native_librecad_font(source_data: bytes, original_license: bytes) -> tuple[dict[str, bytes], dict]:
    """Convert the complete pinned source, accepting no text or drawing input."""
    from ezdxf.fonts.ttfonts import TTFontRenderer
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    digest = sha256(source_data).hexdigest()
    specification = NATIVE_LIBRECAD_FONTS.get(digest)
    if specification is None or len(source_data) != specification["bytes"]:
        raise ValueError("NATIVE_LIBRECAD_FONT_UNRECOGNIZED_SOURCE")
    if not _matches(original_license, specification["license"]):
        raise ValueError("NATIVE_LIBRECAD_FONT_LICENSE_HASH_MISMATCH")

    native = TTFont(BytesIO(source_data), recalcTimestamp=False)
    try:
        renderer = TTFontRenderer(native)
        cmap, glyph_set = native.getBestCmap(), native.getGlyphSet()
        cap = float(renderer.font_measurements.cap_height)
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError("NATIVE_LIBRECAD_FONT_INVALID_CAP_HEIGHT")
        measurements = {}
        for codepoint, name in sorted(cmap.items()):
            bounds = BoundsPen(glyph_set)
            glyph_set[name].draw(bounds)
            measurements[codepoint] = (bounds.bounds, native["hmtx"][name][0])
        gaps = [advance - bounds[2] for bounds, advance in measurements.values()
                if bounds is not None and advance > 0]
        gap = float(median(gaps))
        if not math.isfinite(gap) or gap <= 0:
            raise ValueError("NATIVE_LIBRECAD_FONT_INVALID_GLOBAL_GAP")
        space = float(measurements[32][1])
        scale = 9 / cap
        lines = [
            "# Format: LibreCAD Font 1",
            "# Creator: Image-to-CAD " + DERIVATION,
            "# Name: I2CAD Text LibreCAD Companion",
            "# Encoding: UTF-8",
            "# LetterSpacing: " + format(gap * scale, ".12f"),
            "# WordSpacing: " + format(space * scale, ".12f"),
            "# LineSpacingFactor: 1",
            "# License: Original DejaVu/Bitstream permission; see " + LICENSE_FILENAME,
            "# SourceProfile: " + specification["profile"],
            "# SourceSHA256: " + digest,
            "",
        ]
        errors, represented, empty = {}, [], []
        for codepoint, (bounds, advance) in measurements.items():
            if bounds is None:
                empty.append(codepoint)
                continue
            glyph = renderer.get_glyph_path(chr(codepoint))
            rows, max_x = [], -math.inf
            for subpath in glyph.sub_paths():
                points = list(subpath.flattening(cap * CURVE_FLATTENING))
                if points and points[-1] != points[0]:
                    points.append(points[0])
                if len(points) < 2:
                    continue
                if any(not math.isfinite(value) for point in points for value in (point.x, point.y)):
                    raise ValueError("NATIVE_LIBRECAD_FONT_NONFINITE_OUTLINE")
                max_x = max(max_x, max(point.x for point in points))
                rows.append(";".join(f"{point.x * scale:.12f},{point.y * scale:.12f}" for point in points))
            if not rows:
                raise ValueError("NATIVE_LIBRECAD_FONT_UNREPRESENTABLE_OUTLINE:" + str(codepoint))
            lines.extend(["[%04X]" % codepoint, *rows, ""])
            represented.append(codepoint)
            errors[codepoint] = max_x + gap - advance

        coverage = {
            "outlined_glyphs": len(represented),
            "codepoint_ranges": _ranges(represented + [32]),
            "empty_source_codepoints": empty,
            "ascii_printable_complete": all(cp == 32 or cp in errors for cp in range(32, 127)),
            "complex_shaping_verified": False,
            "non_bmp_TEXT_verified": False,
        }
        if not coverage["ascii_printable_complete"]:
            raise ValueError("NATIVE_LIBRECAD_FONT_INCOMPLETE_ASCII")
        lff = ("\n".join(lines) + "\n").encode("utf-8")
        license_bytes = _derived_license(original_license, digest, specification)
        outputs = {LFF_FILENAME: lff, LICENSE_FILENAME: license_bytes}
        receipt = {
            "schema": "native-librecad-companion-v1",
            "profile": specification["profile"],
            "derivation": DERIVATION,
            "style": "I2CAD_TEXT",
            "source": {"font": specification["font"], **_identity(source_data),
                       "version": specification["version"], "url": specification["source_url"],
                       "license": dict(specification["license"])},
            "librecad": {"version": LIBRECAD_VERSION, "source_commit": LIBRECAD_COMMIT},
            "resources": {name: {"file": name, **_identity(data)} for name, data in outputs.items()},
            "coverage": coverage,
            "layout": {
                "source_cap_height_units": cap,
                "global_whole_font_median_right_gap_units": gap,
                "source_space_advance_units": space,
                "curve_flattening_cap_height": CURVE_FLATTENING,
                "maximum_absolute_advance_error_units": max(abs(error) for error in errors.values()),
                "ascii_maximum_absolute_advance_error_units": max(abs(error) for cp, error in errors.items()
                                                                  if 33 <= cp <= 126),
                "source_outlines_preserved": True,
                "added_spacing_geometry": False,
                "per_glyph_advance_preserved": False,
                "arbitrary_string_TTF_geometry_equivalent": False,
                "drawing_layout_validation": "REQUIRED_SEPARATELY",
            },
            "source_ttf_modified": False,
            "drawing_or_recognition_inputs": False,
            "reference_build_dependencies": dict(REFERENCE_BUILD_DEPENDENCIES),
            "dependencies": {name: version(name) for name in ("fonttools", "ezdxf")},
        }
        return outputs, receipt
    finally:
        native.close()


def _resource_record(directory: Path, receipt: dict) -> dict:
    return {
        "status": "verified",
        "font": LFF_FILENAME,
        "style": "I2CAD_TEXT",
        "path": str(directory / LFF_FILENAME),
        **receipt["resources"][LFF_FILENAME],
        "source": receipt["source"],
        "profile": receipt["profile"],
        "coverage": receipt["coverage"],
        "license": {"path": str(directory / LICENSE_FILENAME), **receipt["resources"][LICENSE_FILENAME]},
        "layout": receipt["layout"],
        "receipt_path": str(directory / RECEIPT_FILENAME),
        "cad_loaded": False,
    }


def _read_cache(directory: Path, specification: dict, source_sha256: str) -> dict | None:
    members = (LFF_FILENAME, LICENSE_FILENAME, RECEIPT_FILENAME)
    if directory.is_symlink():
        raise FileExistsError("NATIVE_LIBRECAD_FONT_CACHE_DIRECTORY_CONFLICT:" + str(directory))
    if not any((directory / name).exists() or (directory / name).is_symlink() for name in members):
        return None
    if any((directory / name).is_symlink() or not (directory / name).is_file() for name in members):
        raise FileExistsError("NATIVE_LIBRECAD_FONT_CACHE_INCOMPLETE_OR_CONFLICT:" + str(directory))
    try:
        receipt = json.loads((directory / RECEIPT_FILENAME).read_text(encoding="utf-8"))
        if (not isinstance(receipt, dict)
                or receipt.get("profile") != specification["profile"]
                or receipt.get("derivation") != DERIVATION
                or receipt.get("source", {}).get("sha256") != source_sha256):
            raise ValueError("wrong source or derivation")
        for role, name in (("lff", LFF_FILENAME), ("derived_license", LICENSE_FILENAME)):
            contents = (directory / name).read_bytes()
            if not _matches(contents, specification[role]):
                raise ValueError("resource hash mismatch")
            if not _matches(contents, receipt["resources"][name]):
                raise ValueError("receipt resource hash mismatch")
            if role == "lff":
                codepoints = [int(value, 16) for value in re.findall(rb"^\[([0-9A-F]{4,6})\]$", contents, re.M)]
                if (receipt["coverage"]["codepoint_ranges"] != _ranges(codepoints + [32])
                        or receipt["coverage"]["outlined_glyphs"] != len(codepoints)
                        or not receipt["coverage"]["ascii_printable_complete"]
                        or receipt["layout"]["arbitrary_string_TTF_geometry_equivalent"] is not False):
                    raise ValueError("receipt coverage or limitation mismatch")
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
        raise FileExistsError("NATIVE_LIBRECAD_FONT_CACHE_IDENTITY_CONFLICT:" + str(directory)) from exc
    return _resource_record(directory, receipt)


def inspect_librecad_resource(source_ttf: Path, cache_dir: Path) -> dict:
    """Read-only: distinguish a verified cache from missing/incompatible files."""
    _, digest, specification = _source(Path(source_ttf))
    directory = Path(cache_dir) / specification["profile"]
    record = _read_cache(directory, specification, digest)
    return record or {"status": "missing", "style": "I2CAD_TEXT", "profile": specification["profile"],
                      "source": {"sha256": digest, "bytes": specification["bytes"]}, "cad_loaded": False}


def _write_new(path: Path, data: bytes) -> None:
    # Exclusive creation preserves even a concurrently created different file.
    with path.open("xb") as stream:
        stream.write(data)


def ensure_librecad_resource(
    source_ttf: Path,
    cache_dir: Path,
    *,
    source_license: Path | None = None,
) -> dict:
    """Create/reuse a pinned offline companion; never install it into CAD.

    A matching existing cache is reused without changing any file timestamp.
    Different or partial cache contents are an error and are retained. CAD
    directory selection, copies, process detection and restart state belong to
    the application preparation service, which consumes this resource record.
    """
    source_ttf = Path(source_ttf)
    data, digest, specification = _source(source_ttf)
    original_license = _license_source(source_ttf, specification, source_license)
    directory = Path(cache_dir) / specification["profile"]
    record = _read_cache(directory, specification, digest)
    if record is not None:
        return record
    outputs, receipt = build_native_librecad_font(data, original_license)
    for role, name in (("lff", LFF_FILENAME), ("derived_license", LICENSE_FILENAME)):
        if not _matches(outputs[name], specification[role]):
            raise ValueError("NATIVE_LIBRECAD_FONT_DERIVATION_HASH_MISMATCH:" + name)
    # Prepare all bytes before creating the destination. The cache lives under
    # a source-specific key; it never overwrites a result or another profile.
    outputs[RECEIPT_FILENAME] = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-lff-", dir=Path(cache_dir)) as temp:
        staging = Path(temp) / specification["profile"]
        staging.mkdir()
        for name, contents in outputs.items():
            _write_new(staging / name, contents)
        if directory.exists() or directory.is_symlink():
            # Recheck a competing completed write; never replace a directory.
            record = _read_cache(directory, specification, digest)
            if record is not None:
                return record
            raise FileExistsError("NATIVE_LIBRECAD_FONT_CACHE_DIRECTORY_CONFLICT:" + str(directory))
        staging.rename(directory)
    return _resource_record(directory, receipt)


def check_librecad_character_coverage(record: dict, text: str) -> dict:
    """Separate absent glyphs from unsupported shaping; do not modify text."""
    ranges = record.get("coverage", {}).get("codepoint_ranges", [])
    missing, limited = [], []
    for char in dict.fromkeys(text):
        cp = ord(char)
        if not any(start <= cp <= end for start, end in ranges):
            missing.append(f"U+{cp:04X}")
        elif (cp > 126 or unicodedata.category(char) in {"Mn", "Mc", "Me", "Cf"}
              or unicodedata.bidirectional(char) in {"R", "AL", "AN"}):
            # Conversion covers the complete cmap; this delivery verifies
            # printable ASCII editing only, not arbitrary scripts or shaping.
            limited.append(f"U+{cp:04X}")
    return {"complete": not missing and not limited, "missing": missing,
            "shaping_or_non_bmp_unverified": limited}
