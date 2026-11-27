"""Prepare the three pinned RapidOCR ONNX models before packaging.

Only this build/development command downloads models. The desktop converter
uses the resulting files directly and does not need a network connection.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request

from omegaconf import OmegaConf


RAPIDOCR_VERSION = "3.9.2"
MODEL_KEYS = {
    "det": ("PP-OCRv6", "multi_PP-OCRv6_det_small"),
    "cls": ("PP-OCRv4", "ch_ppocr_mobile_v2.0_cls_mobile"),
    "rec": ("PP-OCRv6", "multi_PP-OCRv6_rec_small"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: Path, expected: str) -> bool:
    return path.is_file() and sha256(path) == expected


def _download(url: str, destination: Path, expected: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ImageToCAD-build"})
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with urllib.request.urlopen(request, timeout=180) as response:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
        if not _matches(temporary, expected):
            raise RuntimeError(f"Downloaded model checksum mismatch: {destination.name}")
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_ocr_models(directory: str | Path, *, allow_download: bool = True) -> Path:
    version = metadata.version("rapidocr")
    if version != RAPIDOCR_VERSION:
        raise RuntimeError(f"Install rapidocr=={RAPIDOCR_VERSION}; found {version}")
    spec = util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        raise RuntimeError("RapidOCR package not found")
    package = Path(spec.origin).parent
    definitions = OmegaConf.load(package / "default_models.yaml")["onnxruntime"]
    output = Path(directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    license_file = Path(__file__).parent / "licenses/RapidOCR-Apache-2.0.txt"
    shutil.copyfile(license_file, output / license_file.name)
    models: dict[str, dict[str, object]] = {}
    for role, (ocr_version, key) in MODEL_KEYS.items():
        definition = definitions[ocr_version][role][key]
        url = str(definition["model_dir"])
        expected = str(definition["SHA256"])
        filename = url.rsplit("/", 1)[-1]
        destination = output / filename
        if not _matches(destination, expected):
            installed = package / "models" / filename
            if _matches(installed, expected):
                shutil.copyfile(installed, destination)
            elif allow_download:
                _download(url, destination, expected)
            else:
                raise RuntimeError(f"Offline OCR model missing or invalid: {destination}")
        models[role] = {
            "filename": filename, "sha256": expected,
            "bytes": destination.stat().st_size, "source": url,
        }
    (output / "models.json").write_text(
        json.dumps({"rapidocr_version": version, "engine": "onnxruntime",
                    "rapidocr_package_license": "Apache-2.0", "models": models},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path,
                        default=Path(__file__).resolve().parents[1] / "resources/ocr/rapidocr")
    parser.add_argument("--offline", action="store_true",
                        help="Use only valid local models; do not download")
    args = parser.parse_args()
    print(prepare_ocr_models(args.directory, allow_download=not args.offline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
