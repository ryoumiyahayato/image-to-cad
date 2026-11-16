"""Package a DXF, its live IMAGE resources and a font dependency note.

CLI: python -m app.export.portable_dxf INPUT.dxf --output DELIVERY.zip
Optional --trusted-map JSON maps exact IMAGEDEF filenames to generated files.
"""

from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory, NamedTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED
import ezdxf
from ezdxf.audit import AuditError


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


def _layer_state(layer):
    return {"off": layer.is_off(), "frozen": layer.is_frozen(), "locked": layer.is_locked()}


def _layer_states(doc):
    return {layer.dxf.name: _layer_state(layer) for layer in doc.layers}


def _apply_layer_states(doc, reference):
    changes = []
    for layer in doc.layers:
        name = layer.dxf.name
        if name not in reference.layers:
            continue
        original = reference.layers.get(name)
        before, after = _layer_state(layer), _layer_state(original)
        if before == after:
            continue
        change = {"layer": name, "before": before, "after": after}
        # DXF encodes OFF as a negative layer ACI. LibreCAD can save 256
        # (BYLAYER), whose negative form is invalid, so use the source ACI.
        if after["off"] and not 1 <= layer.color <= 255:
            change["aci_before"] = layer.color
            layer.color = original.color
            change["aci_after"] = layer.color
        (layer.off if after["off"] else layer.on)()
        (layer.freeze if after["frozen"] else layer.thaw)()
        (layer.lock if after["locked"] else layer.unlock)()
        if _layer_state(layer) != after:
            raise PortableDxfError(f"Cannot restore layer state: {name}")
        changes.append(change)
    return changes


def _font_dependencies(doc):
    styles = {
        entity.dxf.style for entity in doc.entitydb.values()
        if entity.is_alive and entity.dxftype() in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
    }
    return [
        {"style": name, "font": style.dxf.font, "bigfont": style.dxf.bigfont}
        for name in sorted(styles, key=str.casefold)
        if (style := doc.styles.get(name)) is not None
    ]


def _write_font_note(stage, fonts):
    lines = [
        "字体依赖（DXF 文字样式）",
        "字体文件需在接收端 CAD 中可用。请保持 DXF 与 images 目录的相对位置。",
    ]
    for entry in fonts:
        font = entry["font"]
        lines.append(f'{entry["style"]}: {font or "(CAD 默认字体)"}')
        if entry["bigfont"]:
            lines.append(f'  Big Font: {entry["bigfont"]}')
    if any(entry["font"].casefold() in {"wqy-unicode", "wqy-unicode.lff"} for entry in fonts):
        lines.append("LibreCAD 请安装 wqy-unicode.lff 到其字体目录，再重启并检查中文文字。")
    if not fonts:
        lines.append("未发现 TEXT、MTEXT 或块属性引用的文字样式。")
    (stage / "FONTS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _audit_delivery_copy(doc):
    audit = doc.audit()
    # LibreCAD saves can leave these object owners invalid. Let ezdxf repair
    # them on the copy, and reject any other audit fix or error.
    allowed = re.compile(
        r"Fixed invalid owner handle of IMAGEDEF\(#[0-9A-F]+\)\."
        r"|Deleted PLOTSETTINGS\(#[0-9A-F]+\) entity without owner handle\."
    )
    if audit.errors or any(
        fix.code != AuditError.INVALID_OWNER_HANDLE or not allowed.fullmatch(fix.message)
        for fix in audit.fixes
    ):
        raise PortableDxfError(
            f"DXF audit: {len(audit.errors)} errors, {len(audit.fixes)} fixes"
        )
    return [fix.message for fix in audit.fixes]


def validate_directory(dxf_path, *, expected_layers=None):
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
    if expected_layers is not None and _layer_states(doc) != expected_layers:
        raise PortableDxfError("Layer state changed during DXF serialization")
    return rows


def package_dxf(input_path, output_path, *, trusted_map=None, layer_reference=None, source_record=None):
    """Build a ZIP. An optional source record is generated against the staged DXF."""
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
    layer_changes = _apply_layer_states(doc, layer_reference) if layer_reference is not None else []
    layers = _layer_states(doc)
    repairs = _audit_delivery_copy(doc)
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
            rows = validate_directory(target, expected_layers=layers)
            fonts = _font_dependencies(doc)
            _write_font_note(stage, fonts)
            info = {
                "version": 1,
                "dxf": source.name,
                "images": manifest,
                "image_entities": len(rows),
                "scope": "DXF, live IMAGE assets and font dependency note",
                "fonts": fonts,
                "font_note": "FONTS.txt",
                "layer_states": layers,
                "layer_state_changes": layer_changes,
                "compatibility_repairs": repairs,
            }
            if source_record is not None:
                name = f"{target.stem}.source.json"
                record = source_record(target)
                (stage / name).write_text(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                info["source_record"] = name
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
