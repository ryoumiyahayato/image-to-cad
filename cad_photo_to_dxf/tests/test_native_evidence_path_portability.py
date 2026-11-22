"""Windows-produced references survive the strict current-source verifier."""

import ntpath
import posixpath
from pathlib import PureWindowsPath, PurePosixPath

import pytest

from app.native_objects import evidence_paths
from tests.test_native_checkpoint_text_observations import _current_job, _current_verify, _write


@pytest.mark.parametrize("host", [ntpath, posixpath], ids=["windows", "posix"])
@pytest.mark.parametrize("derived", [False, True], ids=["initial", "derived"])
def test_native_relative_paths_verify_actual_raw_observations_on_both_hosts(tmp_path, monkeypatch, host, derived):
    fixture, root, path, texts = _current_job(tmp_path, derived=derived)
    monkeypatch.setattr(evidence_paths, "_host_relative_path", host.relpath)
    # Simulate the producer's host paths, independent of the test runner's
    # actual filesystem. posixpath cannot interpret a WindowsPath drive, and
    # ntpath must receive an explicit same-drive Windows hierarchy.
    simulated_root = (
        PureWindowsPath("C:/native-job/evidence")
        if host is ntpath else PurePosixPath("/native-job/evidence")
    )
    raw = simulated_root / "text/local_ocr/sample.tsv"
    base = simulated_root / "text"
    region = texts["regions"][0]
    region["completeness_evidence"]["alternatives"][0]["raw_tsv"] = (
        evidence_paths.relative_evidence_path(raw, base)
    )
    if derived:
        texts["region_evidence_roots"] = {
            region["id"]: evidence_paths.relative_evidence_path(
                base, simulated_root / "derived"
            ),
        }
    _write(path, texts)
    verified = _current_verify(fixture, root, path, texts)
    assert verified["validated"] and len(verified["observations"]) == 1
    assert verified["observations"][0]["words"][0]["text"] == "AB"
    assert verified["new_OCR_calls"] == 0
    assert region["completeness_evidence"]["alternatives"][0]["raw_tsv"] == "local_ocr/sample.tsv"
    if derived:
        assert texts["region_evidence_roots"][region["id"]] == "../text"


def test_backslash_in_external_reference_is_still_rejected(tmp_path):
    fixture, root, path, texts = _current_job(tmp_path)
    texts["regions"][0]["completeness_evidence"]["alternatives"][0]["raw_tsv"] = "local_ocr\\sample.tsv"
    _write(path, texts)
    with pytest.raises(ValueError, match="CURRENT_REFERENCE_NOT_RELATIVE_POSIX"):
        _current_verify(fixture, root, path, texts)
