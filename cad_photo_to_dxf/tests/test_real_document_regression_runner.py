from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from scripts import run_real_document_regression as runner


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "real_regression" / "manifest.json"


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_validator_rejects_missing_category() -> None:
    manifest = _manifest()
    documents = manifest["documents"]
    assert isinstance(documents, list)
    for document in documents:
        document["coverage_categories"] = [
            category
            for category in document["coverage_categories"]
            if category != "mobile_perspective_photo"
        ]

    with pytest.raises(ValueError, match="mobile_perspective_photo"):
        runner._validate_manifest(manifest)


def test_missing_fixture_file_is_a_hard_failure(tmp_path: Path) -> None:
    document = deepcopy(_manifest()["documents"][0])
    document["source_path"] = "tests/real_regression/assets/missing-page.png"

    with pytest.raises(FileNotFoundError, match="Missing regression page"):
        runner._measure_document(document, artifacts=tmp_path)


def test_caught_document_failures_cannot_make_the_run_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "report.json"

    def fail_document(
        document: dict[str, object],
        *,
        artifacts: Path,
        compare_expected: bool = True,
    ) -> tuple[dict[str, object], list[str]]:
        del artifacts, compare_expected
        raise RuntimeError(f"fixture load failed: {document['id']}")

    monkeypatch.setattr(runner, "_measure_document", fail_document)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_real_document_regression.py",
            "--manifest",
            str(MANIFEST_PATH),
            "--output",
            str(output_path),
            "--artifacts",
            str(tmp_path / "artifacts"),
        ],
    )

    assert runner.main() == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["document_count"] == len(_manifest()["documents"])
    assert len(report["errors"]) == len(_manifest()["documents"])
