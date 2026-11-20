from __future__ import annotations

from pathlib import Path
import re
from app.version import PRODUCT_NAME, PRODUCT_STATUS, __version__


_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-dev)?$")


def require_product_release_approval(
    version: str = __version__, status: str = PRODUCT_STATUS,
) -> None:
    """Block publishing a development/NO_GO baseline; building remains available.

    This guard does not establish product acceptance. A future GO requires the
    independent CAD and engineer acceptance in the current product baseline.
    """
    if status != "GO" or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError(
            f"Formal release blocked: {version} / {status}. "
            "Complete native objects, target-CAD roundtrip and engineer acceptance "
            "must be verified before product release. Development builds remain available."
        )


def parse_version(version: str) -> tuple[int, int, int, int]:
    """Map the human version's three numeric fields to Windows MAJOR.MINOR.PATCH.0."""
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise ValueError("Version must use MAJOR.MINOR.PATCH with optional -dev suffix")
    major, minor, patch = (int(value) for value in match.groups())
    return major, minor, patch, 0


def write_windows_version_info(path: str | Path, version: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    numeric = parse_version(version)
    numeric_text = ", ".join(str(value) for value in numeric)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric_text}),
    prodvers=({numeric_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'{PRODUCT_NAME}'),
         StringStruct(u'FileDescription', u'{PRODUCT_NAME}'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'CADPhotoToDXF'),
         StringStruct(u'OriginalFilename', u'CADPhotoToDXF.exe'),
         StringStruct(u'ProductName', u'{PRODUCT_NAME}'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    output.write_text(content, encoding="utf-8")
    return output
