"""Create one ordinary portable ZIP, containing the complete application folder."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def create_portable_zip(source: Path, destination: Path, version: str) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Delivery output must be outside the application folder")
    if not (source / "CADPhotoToDXF.exe").is_file():
        raise FileNotFoundError("The Windows application has not been built")
    if any(character not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for character in version):
        raise ValueError("Invalid version in portable filename")
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"CADPhotoToDXF-{version}-Windows-Portable.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                if path.is_symlink():
                    raise ValueError(f"Unexpected symlink in Windows application: {path}")
                archive.write(path, Path("CADPhotoToDXF") / path.relative_to(source))
    with zipfile.ZipFile(output) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"Portable ZIP CRC error: {corrupt}")
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    output = create_portable_zip(args.source_dir, args.output_dir, args.version)
    print(json.dumps({"portable": str(output), "bytes": output.stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
