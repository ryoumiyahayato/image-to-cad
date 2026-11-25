"""Delivery integrity is independent of CAD/source recognition acceptance."""

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.portable_delivery import make_delivery, safe_relative_path


COMMIT = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def tiny_program(tmp_path: Path) -> Path:
    package = tmp_path / "program"
    (package / "_internal" / "resources").mkdir(parents=True)
    (package / "CADPhotoToDXF.exe").write_bytes(b"MZ-test-fixture-only-not-an-executable")
    (package / "_internal" / "resources" / "license.txt").write_bytes(b"font license\n")
    (package / "_internal" / "payload.bin").write_bytes(bytes(range(256)) * 13)
    return package


def test_exact_archive_roundtrip_and_inventory(tiny_program: Path, tmp_path: Path) -> None:
    destination = tmp_path / "delivery"
    manifest = make_delivery(
        package=tiny_program, destination=destination, source_commit=COMMIT,
        version="0.3.0-dev", part_bytes=127,
    )
    archive = destination / manifest["original_file"]
    original = archive.read_bytes()
    assert len(manifest["parts"]) > 1
    rejoined = b"".join((destination / part["file"]).read_bytes() for part in manifest["parts"])
    assert rejoined == original
    assert len(original) == manifest["original_bytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["original_sha256"]
    with zipfile.ZipFile(archive) as zipped:
        assert len(zipped.infolist()) == len(manifest["files"]) == 3
        for member in manifest["files"]:
            expected = (tiny_program / member["path"]).read_bytes()
            actual = zipped.read(member["path"])
            assert actual == expected
            assert len(actual) == member["bytes"]
            assert hashlib.sha256(actual).hexdigest() == member["sha256"]
    assert (destination / "Restore-Windows-portable.cmd").is_file()
    assert (destination / "Restore-Windows-portable.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads((destination / "PORTABLE_RESTORE_MANIFEST.json").read_text()) == manifest


def test_existing_output_preserved(tiny_program: Path, tmp_path: Path) -> None:
    destination = tmp_path / "delivery"
    destination.mkdir()
    sentinel = destination / "important.zip"
    sentinel.write_bytes(b"existing private data")
    with pytest.raises(FileExistsError):
        make_delivery(
            package=tiny_program, destination=destination, source_commit=COMMIT,
            version="0.3.0-dev",
        )
    assert sentinel.read_bytes() == b"existing private data"
    assert list(destination.iterdir()) == [sentinel]


def test_resplit_keeps_tested_archive_identical(tiny_program: Path, tmp_path: Path) -> None:
    first_directory = tmp_path / "first"
    first = make_delivery(
        package=tiny_program, destination=first_directory, source_commit=COMMIT,
        version="0.3.0-dev", part_bytes=151,
    )
    second_directory = tmp_path / "second"
    second = make_delivery(
        archive=first_directory / first["original_file"], destination=second_directory,
        source_commit=COMMIT, version="0.3.0-dev", part_bytes=151,
    )
    assert first == second


@pytest.mark.parametrize("name", [
    "../outside.exe", "/absolute.exe", "a/../outside", "a\\b", "a//b", "a/./b",
    "C:/drive.exe", "a:stream", "CON.txt", "a/LPT1", "a/trailing.", "a/trailing ",
])
def test_windows_unsafe_paths_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="Unsafe Windows archive path"):
        safe_relative_path(name)


def test_existing_zip_windows_aliases_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("CADPhotoToDXF.exe", b"not an executable")
        zipped.writestr("_internal/file", b"one")
        zipped.writestr("_internal/FILE", b"two")
    with pytest.raises(ValueError, match="Duplicate Windows archive path"):
        make_delivery(
            archive=archive, destination=tmp_path / "delivery", source_commit=COMMIT,
            version="0.3.0-dev",
        )


def test_source_symlink_is_not_followed(tiny_program: Path, tmp_path: Path) -> None:
    private = tmp_path / "private.txt"
    private.write_text("private material", encoding="utf-8")
    link = tiny_program / "linked.txt"
    try:
        link.symlink_to(private)
    except (OSError, NotImplementedError):
        pytest.skip("Creating a symlink is unavailable to this test account")
    with pytest.raises(ValueError, match="Symbolic links"):
        make_delivery(
            package=tiny_program, destination=tmp_path / "delivery", source_commit=COMMIT,
            version="0.3.0-dev",
        )
    assert private.read_text(encoding="utf-8") == "private material"
