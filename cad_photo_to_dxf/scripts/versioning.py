from __future__ import annotations

from pathlib import Path
import re


_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int, int, int]:
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise ValueError("Version must use semantic form MAJOR.MINOR.PATCH")
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
        [StringStruct(u'CompanyName', u'CAD Photo to DXF'),
         StringStruct(u'FileDescription', u'CAD Photo to Editable DXF'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'CADPhotoToDXF'),
         StringStruct(u'OriginalFilename', u'CADPhotoToDXF.exe'),
         StringStruct(u'ProductName', u'CAD Photo to DXF'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    output.write_text(content, encoding="utf-8")
    return output
