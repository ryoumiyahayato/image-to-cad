"""Prepare the pinned official DejaVu font and license for native export tests.

This is an explicit resource-setup command, never an import-time download.
The official release differs from the frozen Linux distribution build recorded
in docs/native/resource_manifest.json; that deployment identity stays unchanged.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
import zipfile


ARCHIVE_URL = (
    "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
    "version_2_37/dejavu-sans-ttf-2.37.zip"
)
ARCHIVE_BYTES = 417746
ARCHIVE_SHA256 = "5c6e497a2f36552cb5ffb112c413a6af39c0f3c47653662b90b4fa6499822fd7"
RESOURCES = {
    "DejaVuSans.ttf": {
        "member": "dejavu-sans-ttf-2.37/ttf/DejaVuSans.ttf",
        "bytes": 757076,
        "sha256": "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
    },
    "DejaVuSans.LICENSE.txt": {
        "member": "dejavu-sans-ttf-2.37/LICENSE",
        "bytes": 8816,
        "sha256": "7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93",
    },
}


def _matches(data: bytes, spec: dict) -> bool:
    return len(data) == spec["bytes"] and sha256(data).hexdigest() == spec["sha256"]


def prepare_native_font(
    directory: str | Path,
    *,
    archive: str | Path | None = None,
    allow_download: bool = True,
) -> dict:
    """Verify both original members before installing; preserve other resources."""
    target = Path(directory)
    missing = []
    for name, spec in RESOURCES.items():
        path = target / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise FileExistsError(f"NATIVE_FONT_RESOURCE_CONFLICT:{path}")
        if not path.exists():
            missing.append(name)
        elif not _matches(path.read_bytes(), spec):
            # A different legitimate deployment font must not be overwritten.
            raise FileExistsError(f"NATIVE_FONT_RESOURCE_CONFLICT:{path}")

    if missing:
        if archive is not None:
            payload = Path(archive).read_bytes()
        elif allow_download:
            request = Request(ARCHIVE_URL, headers={"User-Agent": "Image-to-CAD-resource-setup"})
            with urlopen(request, timeout=30) as response:
                payload = response.read(ARCHIVE_BYTES + 1)
        else:
            raise FileNotFoundError("NATIVE_FONT_OFFLINE_RESOURCES_MISSING")
        if len(payload) != ARCHIVE_BYTES or sha256(payload).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("NATIVE_FONT_ARCHIVE_HASH_MISMATCH")

        # Read only the two pinned members; never extract arbitrary ZIP paths.
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            contents = {name: bundle.read(spec["member"]) for name, spec in RESOURCES.items()}
        for name, data in contents.items():
            if not _matches(data, RESOURCES[name]):
                raise ValueError(f"NATIVE_FONT_MEMBER_HASH_MISMATCH:{name}")

        target.mkdir(parents=True, exist_ok=True)
        for name in missing:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target, prefix=".native-font-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(contents[name])
                temporary.replace(target / name)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    receipt = {
        "schema": "native-official-font-resources-v1",
        "profile": "official-dejavu-sans-2.37",
        "source": ARCHIVE_URL,
        "archive_sha256": ARCHIVE_SHA256,
        "font_and_license_verified": True,
        "resources": RESOURCES,
        "scope": "Explicit official-release setup; not the frozen Linux distribution identity or CAD acceptance.",
    }
    (target / "native-dejavu.lock.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "resources/fonts")
    parser.add_argument("--archive", type=Path, help="Use the pinned local ZIP; no download is needed.")
    parser.add_argument("--offline", action="store_true", help="Require verified installed resources or --archive.")
    args = parser.parse_args()
    receipt = prepare_native_font(args.directory, archive=args.archive, allow_download=not args.offline)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
