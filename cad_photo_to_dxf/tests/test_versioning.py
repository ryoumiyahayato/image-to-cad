from __future__ import annotations

from pathlib import Path

import pytest

from scripts.versioning import parse_version, write_windows_version_info


def test_parse_version_accepts_prerelease_suffix() -> None:
    assert parse_version("1.3.0-preview.1") == (1, 3, 0, 0)
    assert parse_version("1.3.0+build.7") == (1, 3, 0, 0)


def test_parse_version_rejects_incomplete_version() -> None:
    with pytest.raises(ValueError):
        parse_version("1.3")


def test_windows_version_info_keeps_display_version(tmp_path: Path) -> None:
    output = write_windows_version_info(
        tmp_path / "version-info.txt",
        "1.3.0-preview.1",
    )
    content = output.read_text(encoding="utf-8")
    assert "filevers=(1, 3, 0, 0)" in content
    assert "ProductVersion', u'1.3.0-preview.1'" in content
