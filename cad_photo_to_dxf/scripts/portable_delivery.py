"""Make the exact, verified Windows ZIP and optional byte-identical split delivery.

The scripts accompanying this ZIP are also the scripts exercised on Windows.
Only program files belong in this bundle; private drawings are separate results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile


SCHEMA = "cadphoto-portable-recovery-v2"
CHUNK = 1024 * 1024
DEFAULT_PART_BYTES = 140 * CHUNK
SCRIPT_DIRECTORY = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str) -> str:
    """Reject names whose meaning changes when extracted by Windows."""
    path = PurePosixPath(value)
    if (
        not value
        or value != path.as_posix()
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(re.search(r'[<>:"|?*\x00-\x1f]', part) for part in path.parts)
        or any(part.endswith((" ", ".")) for part in path.parts)
        or any(
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0])
            for part in path.parts
        )
    ):
        raise ValueError(f"Unsafe Windows archive path: {value!r}")
    return value


def _exclusive_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _inventory_archive(archive: Path) -> list[dict[str, object]]:
    entries = []
    names: set[str] = set()
    with zipfile.ZipFile(archive) as zipped:
        for info in sorted(zipped.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            name = safe_relative_path(info.filename)
            if name.casefold() in names:
                raise ValueError(f"Duplicate Windows archive path: {name}")
            names.add(name.casefold())
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symbolic links are not portable files: {name}")
            digest = hashlib.sha256()
            size = 0
            with zipped.open(info) as stream:
                for block in iter(lambda: stream.read(CHUNK), b""):
                    digest.update(block)
                    size += len(block)
            if size != info.file_size:
                raise ValueError(f"Archive member size mismatch: {name}")
            entries.append({"path": name, "bytes": size, "sha256": digest.hexdigest()})
    if "cadphototodxf.exe" not in names:
        raise ValueError("The archive root must contain CADPhotoToDXF.exe")
    return entries


def make_delivery(
    *,
    destination: Path,
    source_commit: str,
    version: str,
    package: Path | None = None,
    archive: Path | None = None,
    part_bytes: int = DEFAULT_PART_BYTES,
) -> dict[str, object]:
    """Build a new destination exclusively; never merge or overwrite user files."""
    if bool(package) == bool(archive):
        raise ValueError("Choose exactly one package directory or existing archive")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be the exact lowercase 40-character Git commit")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,70}", version):
        raise ValueError("Unsafe application version")
    if part_bytes <= 0:
        raise ValueError("Part size must be positive")
    destination.mkdir(parents=True, exist_ok=False)
    stem = f"CADPhotoToDXF-{version}-{source_commit[:12]}-Windows-portable"
    archive_path = destination / f"{stem}.zip"
    if package is not None:
        package = package.resolve(strict=True)
        if not (package / "CADPhotoToDXF.exe").is_file():
            raise ValueError("The package must contain CADPhotoToDXF.exe")
        if destination.resolve().is_relative_to(package):
            raise ValueError("Delivery destination must be outside the program directory")
        names: set[str] = set()
        with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for path in sorted(package.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"Symbolic links are not portable files: {path}")
                if not path.is_file():
                    continue
                relative = safe_relative_path(path.relative_to(package).as_posix())
                if relative.casefold() in names:
                    raise ValueError(f"Duplicate Windows archive path: {relative}")
                names.add(relative.casefold())
                before = path.stat()
                info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source, zipped.open(info, "w", force_zip64=True) as target:
                    shutil.copyfileobj(source, target, CHUNK)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError(f"Program file changed while packaging: {relative}")
    else:
        assert archive is not None
        with archive.open("rb") as source, archive_path.open("xb") as target:
            shutil.copyfileobj(source, target, CHUNK)

    inventory = _inventory_archive(archive_path)
    archive_hash = sha256_file(archive_path)
    parts = []
    joined_digest = hashlib.sha256()
    with archive_path.open("rb") as source:
        index = 1
        while True:
            first = source.read(min(CHUNK, part_bytes))
            if not first:
                break
            part = destination / f"{archive_path.name}.part{index:02d}"
            digest = hashlib.sha256()
            size = 0
            with part.open("xb") as target:
                block = first
                while block:
                    target.write(block)
                    digest.update(block)
                    joined_digest.update(block)
                    size += len(block)
                    block = source.read(min(CHUNK, part_bytes - size)) if size < part_bytes else b""
            parts.append({"file": part.name, "bytes": size, "sha256": digest.hexdigest()})
            index += 1
    if joined_digest.hexdigest() != archive_hash:
        raise ValueError("Split stream differs from original ZIP")
    manifest = {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "application_version": version,
        "original_file": archive_path.name,
        "original_bytes": archive_path.stat().st_size,
        "original_sha256": archive_hash,
        "extract_directory": stem,
        "executable_relative_path": "CADPhotoToDXF.exe",
        "parts": parts,
        "files": inventory,
        "privacy": "Program files only. Private drawings are delivered separately.",
    }
    _exclusive_json(destination / "PORTABLE_RESTORE_MANIFEST.json", manifest)
    for source_name, target_name in (
        ("restore_windows_portable.cmd", "Restore-Windows-portable.cmd"),
        ("restore_windows_portable.ps1", "Restore-Windows-portable.ps1"),
    ):
        shutil.copyfile(SCRIPT_DIRECTORY / source_name, destination / target_name)
    (destination / "README_RESTORE.txt").write_text(
        "Windows 便携程序：准备与打开\n\n"
        "1. 将完整 ZIP（或全部 .partXX 分卷）、PORTABLE_RESTORE_MANIFEST.json、\n"
        "   Restore-Windows-portable.cmd 和 Restore-Windows-portable.ps1 放在同一文件夹。\n"
        "2. 双击 Restore-Windows-portable.cmd。程序会验证、恢复、解压并打开应用。\n"
        "   不需要手工拼接命令，不会永久更改 PowerShell 执行策略。\n"
        "3. 在应用中选择真实 DXF，使用“准备 CAD 字体”及“在 CAD 中打开”。\n"
        "   如提示需要重新打开 CAD，请退出所有 LibreCAD 窗口后再打开。\n\n"
        "如果提示缺卷或损坏，请重新取得提示的文件后再双击。\n"
        "已有不同 ZIP 或解压目录不会被覆盖。请保留原文件，在新文件夹恢复。\n"
        "也可直接解压完整 ZIP，运行其中的 CADPhotoToDXF.exe。\n"
        "恢复日志保存在本目录。字体、识别及 CAD 保存限制见配套使用说明。\n",
        encoding="utf-8-sig",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--package", type=Path)
    inputs.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--part-bytes", type=int, default=DEFAULT_PART_BYTES)
    args = parser.parse_args()
    manifest = make_delivery(
        destination=args.destination,
        package=args.package,
        archive=args.archive,
        source_commit=args.source_commit,
        version=args.version,
        part_bytes=args.part_bytes,
    )
    print(json.dumps({key: manifest[key] for key in (
        "source_commit", "original_file", "original_bytes", "original_sha256", "parts"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
