"""Inspect the pinned native runtime without downloading or recognizing input.

Run from any directory with the selected native-profile Python interpreter.
The ONNX recognition session is opened only to read its embedded dictionary;
no inference, source drawing, network request or package mutation occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/native/resource_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path, expected: dict) -> dict:
    result = {"path": str(path.resolve()), "exists": path.is_file()}
    if path.is_file():
        result.update(bytes=path.stat().st_size, sha256=sha256(path))
        result["matches_manifest"] = (
            result["sha256"] == expected["sha256"]
            and result["bytes"] == expected["bytes"]
        )
    else:
        result["matches_manifest"] = False
    return result


def inspect_runtime(*, strict_platform_binaries: bool = False) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures, warnings = [], []
    report = {
        "schema": "native-resource-check-v1",
        "manifest_sha256": sha256(MANIFEST),
        "python": {"version": platform.python_version(), "executable": sys.executable,
                   "prefix": sys.prefix, "base_prefix": sys.base_prefix,
                   "system": platform.system(), "machine": platform.machine()},
        "network_calls": 0, "inference_calls": 0,
        "strict_platform_binaries": strict_platform_binaries,
        "packages": {}, "failures": failures, "warnings": warnings,
        "scope": "Deployment identity only; not CAD, content-completeness or engineer acceptance",
    }
    for name, expected in manifest["packages"].items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        report["packages"][name] = {"expected": expected, "actual": actual, "matched": actual == expected}
        if actual != expected:
            failures.append(f"PACKAGE_VERSION_MISMATCH:{name}:{actual}")
    if platform.python_version() != manifest["tested_platform"]["python"]:
        warnings.append("PYTHON_DIFFERS_FROM_TESTED_PATCH_VERSION")
    pyvenv = Path(sys.prefix) / "pyvenv.cfg"
    if pyvenv.is_file():
        config = pyvenv.read_text(encoding="utf-8")
        report["python"]["system_site_packages"] = bool(
            re.search(r"include-system-site-packages\s*=\s*true", config, re.IGNORECASE)
        )
        if report["python"]["system_site_packages"]:
            warnings.append("SYSTEM_SITE_PACKAGES_ENABLED_NOT_A_CLEAN_REPRODUCTION")
    else:
        report["python"]["system_site_packages"] = None
        warnings.append("NOT_A_VIRTUAL_ENVIRONMENT")

    binary = os.environ.get("I2CAD_TESSERACT") or shutil.which("tesseract")
    tess = manifest["tesseract"]
    if not binary:
        failures.append("TESSERACT_NOT_FOUND")
    else:
        binary_path = Path(binary)
        record = file_identity(binary_path, tess["tested_binary"])
        report["tesseract"] = record
        try:
            version = subprocess.run([str(binary_path), "--version"], capture_output=True,
                                     text=True, timeout=20, check=True)
            first_line = (version.stdout or version.stderr).splitlines()[0]
            record["version"] = first_line
            if first_line != tess["version"]:
                failures.append("TESSERACT_VERSION_MISMATCH")
            langs = subprocess.run([str(binary_path), "--list-langs"], capture_output=True,
                                   text=True, timeout=20, check=True)
            language_output = langs.stdout + langs.stderr
            record["language_output"] = language_output
            if "eng" not in [line.strip() for line in language_output.splitlines()]:
                failures.append("TESSERACT_ENG_UNAVAILABLE")
            location = re.search(r'in "([^"]+)"', language_output)
            if location is None:
                failures.append("TESSDATA_LOCATION_UNRESOLVED")
            else:
                data = Path(location.group(1)) / tess["traineddata"]["filename"]
                record["traineddata"] = file_identity(data, tess["traineddata"])
                if not record["traineddata"]["matches_manifest"]:
                    failures.append("ENG_TRAINEDDATA_SHA256_MISMATCH")
            if not record["matches_manifest"]:
                (failures if strict_platform_binaries else warnings).append(
                    "TESSERACT_BINARY_BUILD_DIFFERS_FROM_RECORDED_LINUX_BUILD")
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as error:
            failures.append(f"TESSERACT_INSPECTION_FAILED:{type(error).__name__}:{error}")

    try:
        specification = importlib.util.find_spec("rapidocr")
        if specification is None or specification.origin is None:
            raise ImportError("rapidocr package not installed")
        package = Path(specification.origin).parent
        models = []
        for expected in manifest["rapidocr"]["models"]:
            item = file_identity(package / expected["relative_path"], expected)
            item["role"] = expected["role"]
            models.append(item)
            if not item["matches_manifest"]:
                failures.append("RAPIDOCR_MODEL_SHA256_MISMATCH:" + expected["relative_path"])
        report["rapidocr"] = {"package_directory": str(package), "models": models}
        if all(item["matches_manifest"] for item in models):
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            options.enable_cpu_mem_arena = False
            session = ort.InferenceSession(str(package / "models/PP-OCRv6_rec_small.onnx"),
                                           sess_options=options, providers=["CPUExecutionProvider"])
            expected = manifest["rapidocr"]["embedded_dictionary"]
            raw = session.get_modelmeta().custom_metadata_map[expected["metadata_key"]]
            dictionary = {
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "decoding_character_count_including_CTC_blank_and_space": len(raw.splitlines()) + 2,
            }
            report["rapidocr"]["embedded_dictionary"] = dictionary
            if (dictionary["sha256"] != expected["sha256"]
                    or dictionary["decoding_character_count_including_CTC_blank_and_space"]
                    != expected["decoding_character_count_including_CTC_blank_and_space"]):
                failures.append("RAPIDOCR_CHARACTER_DICTIONARY_MISMATCH")
    except (ImportError, OSError, RuntimeError, ValueError, KeyError) as error:
        failures.append(f"RAPIDOCR_INSPECTION_FAILED:{type(error).__name__}:{error}")

    font = manifest["font"]
    local = ROOT / "cad_photo_to_dxf/resources/fonts"
    choices = [
        (local / font["filename"], local / font["license_filename"]),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/doc/fonts-dejavu-core/copyright")),
    ]
    candidate = next(((f, license_file) for f, license_file in choices
                      if f.is_file() and license_file.is_file()), None)
    if candidate is None:
        failures.append("NATIVE_FONT_OR_LICENSE_MISSING")
    else:
        font_path, license_path = candidate
        record = file_identity(font_path, font)
        record["license"] = file_identity(license_path, font["tested_license"])
        report["font"] = record
        if not record["matches_manifest"]:
            failures.append("NATIVE_FONT_SHA256_MISMATCH")
        if not record["license"]["matches_manifest"]:
            (failures if strict_platform_binaries else warnings).append(
                "FONT_LICENSE_TEXT_DIFFERS_FROM_RECORDED_PACKAGE_COPY_REVIEW_REQUIRED")
    report["passed"] = not failures
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-platform-binaries", action="store_true",
                        help="Also require the recorded Linux Tesseract executable and license-text hashes")
    parser.add_argument("--output", type=Path, help="Optionally save the inspection JSON at a new path")
    args = parser.parse_args()
    report = inspect_runtime(strict_platform_binaries=args.strict_platform_binaries)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
