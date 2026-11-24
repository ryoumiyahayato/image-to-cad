"""Transport/identity checks; synthetic font bytes are never render inputs."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from scripts import prepare_source_row_font as fonts


@pytest.fixture
def resources(monkeypatch, tmp_path):
    profile = deepcopy(fonts.SOURCE_ROW_FONT)
    data = {"font": b"synthetic transport fixture, not a real font", "license": b"synthetic complete license fixture\n"}
    for role, payload in data.items():
        profile[role].update(bytes=len(payload), sha256=sha256(payload).hexdigest())
    monkeypatch.setattr(fonts, "SOURCE_ROW_FONT", profile)
    derivative = deepcopy(fonts.SOURCE_ROW_DERIVATIVE)
    generated = {"font": b"synthetic derived TTF, never a render input",
                 "lff": b"synthetic derived LFF, never a render input\n",
                 "license": data["license"] + b"synthetic derivative notice\n"}
    for role, payload in generated.items():
        derivative[role].update(bytes=len(payload), sha256=sha256(payload).hexdigest())
    monkeypatch.setattr(fonts, "SOURCE_ROW_DERIVATIVE", derivative)

    def fake_builder(font_data, license_data):
        assert font_data == data["font"] and license_data == data["license"]
        return {derivative[role]["file"]: payload for role, payload in generated.items()}, {
            "derivation": derivative["derivation"], "checker_test_only": True,
        }

    monkeypatch.setattr(fonts, "build_source_row_font", fake_builder)
    source = tmp_path / "source"
    source.mkdir()
    font = source / profile["font"]["file"]
    font.write_bytes(data["font"])
    (source / profile["license"]["file"]).write_bytes(data["license"])
    monkeypatch.setattr(fonts, "LICENSE_SOURCE_DIRECTORY", source)

    def unexpected_network(*_args, **_kwargs):
        pytest.fail("offline/local setup must not call the network")

    monkeypatch.setattr(fonts, "urlopen", unexpected_network)
    return profile, data, source, font


def test_local_setup_and_offline_reuse_preserve_existing_native_font(resources, tmp_path):
    profile, data, _, font = resources
    target = tmp_path / "target"
    target.mkdir()
    old = target / "DejaVuSans.ttf"
    old.write_bytes(b"existing native deployment font")
    receipt = fonts.prepare_source_row_font(target, font=font, allow_download=False)
    assert receipt["font_and_license_verified"] is True
    assert receipt["derived_TTF_LFF_and_full_license_verified"] is True
    assert receipt["generation_executed_this_request"] is True
    assert receipt["upstream_commit"] == profile["upstream_commit"]
    assert {role: (target / profile[role]["file"]).read_bytes() for role in data} == data
    stamps = {role: (target / profile[role]["file"]).stat().st_mtime_ns for role in data}
    reused = fonts.prepare_source_row_font(target, allow_download=False)
    assert reused["generation_executed_this_request"] is False
    assert stamps == {role: (target / profile[role]["file"]).stat().st_mtime_ns for role in data}
    assert old.read_bytes() == b"existing native deployment font"


@pytest.mark.parametrize("role", ["font", "license"])
def test_corrupt_input_rejected_before_resource_writes(resources, tmp_path, role):
    profile, _, source, font = resources
    (source / profile[role]["file"]).write_bytes(b"wrong resource bytes")
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="SOURCE_ROW_FONT_(BINARY|LICENSE)_HASH_MISMATCH"):
        fonts.prepare_source_row_font(target, font=font, allow_download=False)
    assert not target.exists()


@pytest.mark.parametrize("role", ["font", "license"])
def test_existing_different_resource_is_never_overwritten(resources, tmp_path, role):
    profile, _, _, font = resources
    target = tmp_path / "target"
    target.mkdir()
    path = target / profile[role]["file"]
    path.write_bytes(b"another legitimate installation")
    with pytest.raises(FileExistsError, match="SOURCE_ROW_FONT_RESOURCE_CONFLICT"):
        fonts.prepare_source_row_font(target, font=font, allow_download=False)
    assert path.read_bytes() == b"another legitimate installation"
    assert not (target / fonts.LOCK_NAME).exists()


def test_missing_complete_license_does_not_download_or_write(resources, tmp_path):
    profile, _, source, _ = resources
    (source / profile["license"]["file"]).unlink()
    target = tmp_path / "target"
    with pytest.raises(FileNotFoundError, match="SOURCE_ROW_FONT_COMPLETE_LICENSE_MISSING"):
        fonts.prepare_source_row_font(target)
    assert not target.exists()


def test_offline_missing_font_leaves_no_partial_license(resources, tmp_path):
    target = tmp_path / "target"
    with pytest.raises(FileNotFoundError, match="SOURCE_ROW_FONT_OFFLINE_RESOURCE_MISSING"):
        fonts.prepare_source_row_font(target, allow_download=False)
    assert not target.exists()


def test_explicit_download_uses_fixed_source_and_verifies_bytes(resources, monkeypatch, tmp_path):
    profile, data, _, _ = resources
    seen = []

    def download(request, timeout):
        seen.append((request.full_url, timeout))
        return BytesIO(data["font"])

    monkeypatch.setattr(fonts, "urlopen", download)
    target = tmp_path / "target"
    fonts.prepare_source_row_font(target)
    assert seen == [(profile["source_url"], 30)]
    assert (target / profile["font"]["file"]).read_bytes() == data["font"]


def test_downloaded_wrong_bytes_are_rejected(resources, monkeypatch, tmp_path):
    monkeypatch.setattr(fonts, "urlopen", lambda *_args, **_kwargs: BytesIO(b"wrong remote content"))
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="SOURCE_ROW_FONT_BINARY_HASH_MISMATCH"):
        fonts.prepare_source_row_font(target)
    assert not target.exists()


@pytest.mark.parametrize("role", ["font", "lff", "license"])
def test_generated_bytes_must_match_registry_before_any_resource_write(resources, monkeypatch, tmp_path, role):
    _, _, _, font = resources
    build = fonts.build_source_row_font

    def changed(*args):
        output, receipt = build(*args)
        output[fonts.SOURCE_ROW_DERIVATIVE[role]["file"]] += b"changed"
        return output, receipt

    monkeypatch.setattr(fonts, "build_source_row_font", changed)
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="SOURCE_ROW_FONT_DERIVED_RESOURCE_HASH_MISMATCH"):
        fonts.prepare_source_row_font(target, font=font, allow_download=False)
    assert not target.exists()


@pytest.mark.parametrize("role", ["font", "lff", "license"])
def test_existing_different_derived_resource_is_never_overwritten(resources, tmp_path, role):
    _, _, _, font = resources
    target = tmp_path / "target"
    target.mkdir()
    path = target / fonts.SOURCE_ROW_DERIVATIVE[role]["file"]
    path.write_bytes(b"an existing different derived resource")
    with pytest.raises(FileExistsError, match="SOURCE_ROW_FONT_RESOURCE_CONFLICT"):
        fonts.prepare_source_row_font(target, font=font, allow_download=False)
    assert path.read_bytes() == b"an existing different derived resource"
    assert not (target / fonts.LOCK_NAME).exists()


def test_default_profile_binds_full_tracked_license_and_immutable_source():
    profile = fonts.SOURCE_ROW_FONT
    license_path = fonts.LICENSE_SOURCE_DIRECTORY / profile["license"]["file"]
    assert fonts._matches(license_path.read_bytes(), profile["license"])
    assert profile["upstream_commit"] in profile["source_url"]
    assert "/master/" not in profile["source_url"] and "/main/" not in profile["source_url"]
    assert profile["font"]["file"] != "DejaVuSans.ttf"
    assert b"GNU LESSER GENERAL PUBLIC LICENSE" in license_path.read_bytes()
    assert b"GNU GENERAL PUBLIC LICENSE" in license_path.read_bytes()
    assert b"As a special exception" in license_path.read_bytes()


def test_windows_prepares_new_resource_before_tests_without_replacing_old_setup():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/windows-build.yml").read_text()
    assert workflow.index("python scripts/prepare_native_font.py") < workflow.index("python -m pytest -q")
    assert workflow.index("python scripts/prepare_source_row_font.py") < workflow.index("python -m pytest -q")
    assert workflow.index("python scripts/prepare_source_row_font.py") < workflow.index("pyinstaller --noconfirm --clean")
    assert workflow.index("fonttools==4.68.0 ezdxf==1.4.5") < workflow.index("python scripts/prepare_source_row_font.py")
