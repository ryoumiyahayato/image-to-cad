from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


_MIN_FONT_BYTES = 1_000_000
_FONT_SIGNATURES = (b"OTTO", b"\x00\x01\x00\x00", b"ttcf")
_LICENSE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/"
    "Sans2.004/Sans/LICENSE"
)


def _read_manifest(directory: Path) -> dict[str, object]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing font manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _is_font_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < _MIN_FONT_BYTES:
        return False
    with path.open("rb") as handle:
        return handle.read(4) in _FONT_SIGNATURES


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
            with urlopen(request, timeout=180) as response:
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


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_font_bundle(
    directory: str | Path,
    *,
    allow_download: bool = True,
    strict: bool = True,
) -> Path:
    """Prepare the redistributable OFL font bundle used by preview and CAD export."""

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(target)
    raw_fonts = manifest.get("fonts", [])
    if not isinstance(raw_fonts, list):
        raise ValueError("Font manifest field 'fonts' must be a list")

    records: list[dict[str, object]] = []
    missing: list[str] = []
    for raw in raw_fonts:
        if not isinstance(raw, dict):
            continue
        filename = str(raw.get("filename", "")).strip()
        url = str(raw.get("url", "")).strip()
        if not filename:
            continue
        path = target / Path(filename).name
        if not _is_font_file(path) and allow_download and url:
            print(f"Downloading CAD font: {filename}")
            _download(url, path)
        if not _is_font_file(path):
            missing.append(filename)
            continue
        records.append(
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _hash_file(path),
                "source": url,
            }
        )

    license_path = target / "OFL-1.1.txt"
    if not license_path.exists() and allow_download:
        _download(_LICENSE_URL, license_path)

    lock = {
        "schema_version": 1,
        "bundle_name": manifest.get("bundle_name", "CAD font bundle"),
        "font_count": len(records),
        "fonts": records,
    }
    (target / "bundle.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if missing and strict:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Portable CAD font bundle is incomplete: {joined}. "
            "Run scripts/prepare_cad_fonts.py while connected to the internet."
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare portable CAD fonts")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "resources" / "fonts",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    prepare_font_bundle(
        args.directory,
        allow_download=not args.offline,
        strict=not args.allow_missing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
