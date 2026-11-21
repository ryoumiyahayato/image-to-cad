"""Resource-integrity unit tests; synthetic bytes are never used to render text."""

from hashlib import sha256
import io
from pathlib import Path
import zipfile

import pytest

from scripts import prepare_native_font as fonts


@pytest.fixture
def archive_case(monkeypatch, tmp_path):
    contents = {
        "DejaVuSans.ttf": b"synthetic transport fixture, not a renderable font",
        "DejaVuSans.LICENSE.txt": b"synthetic transport fixture license",
    }
    specs = {
        name: {"member": "fixture/" + name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
        for name, data in contents.items()
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        for name, data in contents.items():
            bundle.writestr(specs[name]["member"], data)
        bundle.writestr("../must-not-be-extracted", b"unrelated member")
    raw = payload.getvalue()
    monkeypatch.setattr(fonts, "RESOURCES", specs)
    monkeypatch.setattr(fonts, "ARCHIVE_BYTES", len(raw))
    monkeypatch.setattr(fonts, "ARCHIVE_SHA256", sha256(raw).hexdigest())

    def unexpected_network(*_args, **_kwargs):
        pytest.fail("local or offline resource preparation must not use the network")

    monkeypatch.setattr(fonts, "urlopen", unexpected_network)
    archive = tmp_path / "fixture.zip"
    archive.write_bytes(raw)
    return archive, contents


def test_verified_members_install_and_offline_reuse_without_network(archive_case, tmp_path):
    archive, contents = archive_case
    output = tmp_path / "resources"
    receipt = fonts.prepare_native_font(output, archive=archive, allow_download=False)
    assert receipt["font_and_license_verified"] is True
    assert {name: (output / name).read_bytes() for name in contents} == contents
    assert not (tmp_path / "must-not-be-extracted").exists()
    before = {name: (output / name).stat().st_mtime_ns for name in contents}
    fonts.prepare_native_font(output, allow_download=False)
    assert {name: (output / name).stat().st_mtime_ns for name in contents} == before


def test_corrupt_archive_is_rejected_before_resource_writes(archive_case, tmp_path):
    archive, _ = archive_case
    archive.write_bytes(archive.read_bytes() + b"changed")
    output = tmp_path / "resources"
    with pytest.raises(ValueError, match="NATIVE_FONT_ARCHIVE_HASH_MISMATCH"):
        fonts.prepare_native_font(output, archive=archive)
    assert not output.exists()


@pytest.mark.parametrize("name", ["DejaVuSans.ttf", "DejaVuSans.LICENSE.txt"])
def test_changed_member_is_rejected_before_any_write(archive_case, monkeypatch, tmp_path, name):
    archive, _ = archive_case
    # Even when transport identity is accepted, each required resource has its
    # own pin. This exercises the license check as well as the font check.
    specs = {key: dict(value) for key, value in fonts.RESOURCES.items()}
    specs[name]["sha256"] = "0" * 64
    monkeypatch.setattr(fonts, "RESOURCES", specs)
    output = tmp_path / "resources"
    with pytest.raises(ValueError, match="NATIVE_FONT_MEMBER_HASH_MISMATCH"):
        fonts.prepare_native_font(output, archive=archive)
    assert not output.exists()


def test_existing_different_deployment_font_is_not_overwritten(archive_case, tmp_path):
    archive, _ = archive_case
    output = tmp_path / "resources"
    output.mkdir()
    existing = output / "DejaVuSans.ttf"
    existing.write_bytes(b"different deployment font")
    with pytest.raises(FileExistsError, match="NATIVE_FONT_RESOURCE_CONFLICT"):
        fonts.prepare_native_font(output, archive=archive)
    assert existing.read_bytes() == b"different deployment font"
    assert not (output / "DejaVuSans.LICENSE.txt").exists()


def test_offline_mode_requires_the_license_too(archive_case, tmp_path):
    _, contents = archive_case
    output = tmp_path / "resources"
    output.mkdir()
    (output / "DejaVuSans.ttf").write_bytes(contents["DejaVuSans.ttf"])
    with pytest.raises(FileNotFoundError, match="NATIVE_FONT_OFFLINE_RESOURCES_MISSING"):
        fonts.prepare_native_font(output, allow_download=False)
    assert not (output / "native-dejavu.lock.json").exists()


def test_windows_workflow_prepares_real_resources_before_pytest():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/windows-build.yml"
    text = workflow.read_text(encoding="utf-8")
    assert text.index("python scripts/prepare_native_font.py") < text.index("python -m pytest -q")
