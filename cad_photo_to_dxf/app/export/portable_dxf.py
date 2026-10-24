"""Package an existing DXF and its live IMAGE resources without source scans.

CLI: python -m app.export.portable_dxf INPUT.dxf --output DELIVERY.zip
Optional --trusted-map JSON maps exact IMAGEDEF filenames to generated files.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory, NamedTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED
import ezdxf


class PortableDxfError(ValueError):
    pass


def live_images(doc):
    """IMAGEs reachable from model/paper layouts through INSERT blocks."""
    images, visited_blocks, visited_images = [], set(), set()

    def walk(layout):
        for entity in layout:
            if not entity.is_alive:
                continue
            if entity.dxftype() == "IMAGE":
                key = entity.dxf.handle
                if key not in visited_images:
                    visited_images.add(key)
                    images.append(entity)
            elif entity.dxftype() == "INSERT":
                name = entity.dxf.name
                key = name.casefold()
                if key in visited_blocks:
                    continue
                visited_blocks.add(key)
                try:
                    block = doc.blocks.get(name)
                except KeyError:
                    raise PortableDxfError(
                        f"INSERT references missing block: {name}"
                    ) from None
                walk(block)

    for layout in doc.layouts:
        walk(layout)
    return tuple(images)


def _resolve(filename, directory, trusted):
    if filename in trusted:
        supplied = str(trusted[filename])
        if supplied.startswith(("\\\\", "//")) or "://" in supplied:
            raise PortableDxfError(f"Untrusted mapped IMAGE network path: {filename}")
        path = Path(supplied).resolve(strict=True)
        if not path.is_file():
            raise PortableDxfError(f"IMAGE dependency is not a file: {filename}")
        return path
    win = PureWindowsPath(filename)
    if (
        not filename
        or win.is_absolute()
        or win.drive
        or filename.startswith(("\\\\", "//"))
        or "://" in filename
    ):
        raise PortableDxfError(f"Untrusted IMAGE path: {filename}")
    path = (directory / Path(filename.replace("\\", "/"))).resolve()
    if not path.is_relative_to(directory):
        raise PortableDxfError(f"IMAGE path escapes DXF directory: {filename}")
    if not path.is_file():
        raise PortableDxfError(f"Missing IMAGE dependency: {filename}")
    return path


def validate_directory(dxf_path):
    path = Path(dxf_path).resolve()
    doc = ezdxf.readfile(path)
    rows = []
    for image in live_images(doc):
        definition = image.image_def
        if definition is None:
            raise PortableDxfError(f"IMAGE {image.dxf.handle} has no IMAGEDEF")
        filename = definition.dxf.filename
        resource = _resolve(filename, path.parent, {})
        rows.append(
            {
                "image": image.dxf.handle,
                "imagedef": definition.dxf.handle,
                "file": filename,
                "bytes": resource.stat().st_size,
            }
        )
    audit = doc.audit()
    if audit.errors or audit.fixes:
        raise PortableDxfError(
            f"DXF audit: {len(audit.errors)} errors, {len(audit.fixes)} fixes"
        )
    return rows


def package_dxf(input_path, output_path, *, trusted_map=None):
    source = Path(input_path).resolve(strict=True)
    output = Path(output_path).resolve()
    if output.suffix.lower() != ".zip" or output == source:
        raise PortableDxfError("Output must be an explicit ZIP path")
    doc = ezdxf.readfile(source)
    unsupported = []
    for block in doc.blocks:
        if block.block.dxf.flags & 12:
            unsupported.append(f"XREF:{block.name}")
    for e in doc.entitydb.values():
        if e.is_alive and e.dxftype() in (
            "PDFUNDERLAY",
            "DWFUNDERLAY",
            "DGNUNDERLAY",
            "OLE2FRAME",
        ):
            unsupported.append(e.dxftype())
    if unsupported:
        raise PortableDxfError(
            "Unsupported external dependencies: " + ", ".join(sorted(set(unsupported)))
        )
    trusted = dict(trusted_map or {})
    dependencies = {}
    for image in live_images(doc):
        definition = image.image_def
        if definition is None:
            raise PortableDxfError(f"IMAGE {image.dxf.handle} has no IMAGEDEF")
        name = definition.dxf.filename
        try:
            actual = _resolve(name, source.parent, trusted)
        except (OSError, PortableDxfError) as exc:
            raise PortableDxfError(
                f"IMAGEDEF {definition.dxf.handle}, required {name}: {exc}"
            ) from exc
        dependencies[definition.dxf.handle] = (definition, actual, name)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_zip = None
    try:
        with TemporaryDirectory(prefix="portable-dxf-", dir=output.parent) as folder:
            stage = Path(folder)
            resources = []
            manifest = []
            for handle, (definition, actual, original) in dependencies.items():
                data = actual.read_bytes()
                # Direct bytes comparison avoids introducing a hash ledger.
                same = next(
                    (name for _, content, name in resources if content == data), None
                )
                if same is None:
                    suffix = actual.suffix.lower()
                    if suffix not in (
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".bmp",
                        ".tif",
                        ".tiff",
                        ".gif",
                    ):
                        raise PortableDxfError(f"Unsupported IMAGE format: {original}")
                    same = f"images/image-{len(resources) + 1:03d}{suffix}"
                    (stage / "images").mkdir(exist_ok=True)
                    (stage / same).write_bytes(data)
                    resources.append((actual, data, same))
                definition.dxf.filename = same
                manifest.append(
                    {
                        "imagedef": handle,
                        "original": original,
                        "file": same,
                        "bytes": len(data),
                    }
                )
            target = stage / source.name
            doc.saveas(target)
            rows = validate_directory(target)
            info = {
                "version": 1,
                "dxf": source.name,
                "images": manifest,
                "image_entities": len(rows),
                "scope": "DXF and live IMAGE assets; fonts and source/review projects excluded",
            }
            (stage / "dependencies.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with NamedTemporaryFile(
                suffix=".zip", dir=output.parent, delete=False
            ) as temp:
                temporary_zip = Path(temp.name)
            with ZipFile(temporary_zip, "w", ZIP_DEFLATED) as archive:
                for file in sorted(stage.rglob("*")):
                    if file.is_file():
                        archive.write(file, file.relative_to(stage).as_posix())
            with ZipFile(temporary_zip) as archive:
                if archive.testzip() is not None:
                    raise PortableDxfError("ZIP validation failed")
            os.replace(temporary_zip, output)
            temporary_zip = None
            return info
    finally:
        if temporary_zip is not None:
            temporary_zip.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trusted-map", type=Path)
    args = parser.parse_args()
    try:
        mapping = (
            json.loads(args.trusted_map.read_text(encoding="utf-8"))
            if args.trusted_map
            else None
        )
        print(
            json.dumps(
                package_dxf(args.input, args.output, trusted_map=mapping),
                ensure_ascii=False,
                indent=2,
            )
        )
    except (OSError, ValueError, ezdxf.DXFError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
