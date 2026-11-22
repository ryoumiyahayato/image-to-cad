"""Stage pinned Windows native OCR resources without installing on the host.

The upstream release's NSIS archive is verified before 7-Zip extraction. Its
runtime DLLs and documentation remain together; eng.traineddata is pinned
separately. This explicit build step is the only download route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen


BASE = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/"
INSTALLER = {
    "url": BASE + "tesseract-ocr-w64-setup-5.5.0.20241111.exe",
    "bytes": 21381872,
    "sha256": "f3fc4236425b690c8be756f35793f77394ee004be0a6460a440c754d892f68bc",
}
ASSETS = {
    "tessdata/eng.traineddata": {
        "url": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata",
        "bytes": 4113088,
        "sha256": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    },
    "LICENSE-Tesseract.txt": {
        "url": "https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.5.0/LICENSE",
        "bytes": 11358,
        "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    },
    "LICENSE-tessdata.txt": {
        "url": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/LICENSE",
        "bytes": 11358,
        "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    },
}


def verified_bytes(spec: dict, local: Path | None = None) -> bytes:
    if local is None:
        request = Request(spec["url"], headers={"User-Agent": "Image-to-CAD-resource-setup"})
        with urlopen(request, timeout=60) as response:
            data = response.read(spec["bytes"] + 1)
    else:
        data = Path(local).read_bytes()
    if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("WINDOWS_OCR_DOWNLOAD_IDENTITY_MISMATCH:" + spec["url"])
    return data


def prepare(directory: Path, *, installer: Path | None = None, seven_zip: str = "7z") -> dict:
    target = Path(directory).resolve()
    if target.exists():
        raise FileExistsError("Use a new OCR staging directory: " + str(target))
    payload = verified_bytes(INSTALLER, installer)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-windows-ocr-", dir=target.parent) as temporary:
        work = Path(temporary)
        archive = work / "verified-installer.exe"
        archive.write_bytes(payload)
        extracted = work / "extracted"
        result = subprocess.run(
            [seven_zip, "x", "-y", str(archive), "-o" + str(extracted)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode:
            raise RuntimeError("WINDOWS_OCR_ARCHIVE_EXTRACTION_FAILED:" + result.stderr[-2000:])
        matches = list(extracted.rglob("tesseract.exe"))
        if len(matches) != 1:
            raise ValueError("WINDOWS_OCR_ARCHIVE_LAYOUT_UNRECOGNIZED")
        staged = work / "runtime"
        shutil.copytree(matches[0].parent, staged)
        # NSIS helper code is not part of the deployed OCR runtime.
        for name in ("$PLUGINSDIR", "$TEMP"):
            shutil.rmtree(staged / name, ignore_errors=True)
        for name, spec in ASSETS.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(verified_bytes(spec))
        if not list(staged.glob("*.dll")):
            raise ValueError("WINDOWS_OCR_RUNTIME_DLLS_MISSING")
        files = {
            path.relative_to(staged).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(staged.rglob("*")) if path.is_file()
        }
        receipt = {
            "schema": "native-windows-ocr-resources-v1",
            "profile": "tesseract-5.5.0.20241111-x64-eng-fast-4.1.0",
            "installer": INSTALLER,
            "separate_assets": ASSETS,
            "files": files,
            "original_runtime_and_license_documents_retained": True,
            "runtime_downloads": False,
        }
        (staged / "native-ocr.lock.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        staged.replace(target)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "resources/ocr/tesseract")
    parser.add_argument("--installer", type=Path, help="Previously downloaded pinned NSIS archive")
    parser.add_argument("--seven-zip", default="7z")
    args = parser.parse_args()
    result = prepare(args.directory, installer=args.installer, seven_zip=args.seven_zip)
    print(json.dumps({"profile": result["profile"], "files": len(result["files"]), "directory": str(args.directory)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
