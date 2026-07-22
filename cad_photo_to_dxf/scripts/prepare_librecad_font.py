from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile


def _read_manifest(directory: Path) -> dict[str, object]:
    path = directory / "librecad-font.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing LibreCAD font manifest: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("LibreCAD font manifest must contain a JSON object")
    return payload


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, *, attempts: int = 4) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        temporary: Path | None = None
        try:
            request = Request(
                url,
                headers={"User-Agent": "CADPhotoToDXF-build/1.0"},
            )
            with urlopen(request, timeout=240) as response:
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=f".{destination.name}.",
                    suffix=".download",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    shutil.copyfileobj(response, handle)
            temporary.replace(destination)
            return
        except (OSError, URLError) as exc:
            last_error = exc
            if temporary is not None and temporary.exists():
                temporary.unlink()
            if attempt < attempts:
                time.sleep(float(attempt * 2))
    raise RuntimeError(f"Could not download {url}: {last_error}")


def _is_lff_file(path: Path, minimum_size: int) -> bool:
    if not path.exists() or path.stat().st_size < minimum_size:
        return False
    try:
        with path.open("rb") as handle:
            header = handle.read(256)
    except OSError:
        return False
    return b"LibreCAD Font" in header or b"LetterSpacing" in header


def _extract_direct_lff(archive: Path, destination: Path) -> bool:
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [
                name
                for name in bundle.namelist()
                if name.casefold().endswith(".lff")
            ]
            if not members:
                return False
            member = sorted(members, key=lambda value: len(value))[0]
            with bundle.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            return True
    except (OSError, zipfile.BadZipFile):
        return False


def _extract_nested_7z(archive: Path, destination: Path) -> bool:
    extractor = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
    if extractor is None:
        return False
    with tempfile.TemporaryDirectory(prefix="cadphoto-lff-") as temporary_value:
        temporary = Path(temporary_value)
        try:
            with zipfile.ZipFile(archive) as bundle:
                nested = [
                    name
                    for name in bundle.namelist()
                    if name.casefold().endswith((".7z", ".lff.7z"))
                ]
                if not nested:
                    return False
                bundle.extract(nested[0], temporary)
                nested_path = temporary / nested[0]
        except (OSError, zipfile.BadZipFile):
            return False
        extract_root = temporary / "expanded"
        extract_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [extractor, "x", "-y", f"-o{extract_root}", str(nested_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return False
        candidates = sorted(extract_root.rglob("*.lff"), key=lambda path: path.stat().st_size)
        if not candidates:
            return False
        shutil.copy2(candidates[-1], destination)
        return True


def _extract_lff(archive: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    extracted = _extract_direct_lff(archive, temporary)
    if not extracted:
        extracted = _extract_nested_7z(archive, temporary)
    if not extracted:
        raise RuntimeError(
            "Could not extract wqy-unicode.lff. The SourceForge package did not "
            "contain a direct LFF file and no usable 7z extractor was found."
        )
    temporary.replace(destination)


def prepare_librecad_font(
    directory: str | Path,
    *,
    allow_download: bool = True,
    strict: bool = True,
) -> Path:
    """Prepare LibreCAD's native CJK LFF font used by preview and DXF TEXT."""

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(target)
    filename = Path(str(manifest.get("filename", "wqy-unicode.lff"))).name
    archive_filename = Path(
        str(manifest.get("archive_filename", "wqy-unicode.zip"))
    ).name
    url = str(manifest.get("url", "")).strip()
    license_url = str(manifest.get("license_url", "")).strip()
    minimum_size = int(manifest.get("minimum_size_bytes", 10_000_000))

    font_path = target / filename
    archive_path = target / archive_filename
    if not _is_lff_file(font_path, minimum_size) and allow_download and url:
        print(f"Downloading LibreCAD CJK font archive: {archive_filename}")
        _download(url, archive_path)
        _extract_lff(archive_path, font_path)

    license_path = target / "WQY-LICENSE-Apache-2.0.txt"
    if not license_path.exists() and allow_download and license_url:
        _download(license_url, license_path)

    ready = _is_lff_file(font_path, minimum_size)
    lock = {
        "schema_version": 1,
        "name": manifest.get("name", "LibreCAD CJK font"),
        "family": manifest.get("family", "wqy-unicode"),
        "filename": filename,
        "ready": ready,
        "size_bytes": font_path.stat().st_size if font_path.exists() else 0,
        "sha256": _hash_file(font_path) if ready else None,
        "source": url,
        "license": manifest.get("license"),
    }
    (target / "librecad-font.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if strict and not ready:
        raise RuntimeError(
            "LibreCAD CJK font bundle is incomplete. Run "
            "scripts/prepare_librecad_font.py while connected to the internet."
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare LibreCAD CJK LFF font")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "resources" / "fonts",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    prepare_librecad_font(
        args.directory,
        allow_download=not args.offline,
        strict=not args.allow_missing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
