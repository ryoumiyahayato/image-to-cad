from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "real_regression" / "manifest.json"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_real_document_regression_set_is_nonempty_complete_and_immutable() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    documents = manifest["documents"]

    assert len(documents) >= manifest["minimum_documents"] >= 3
    assert (
        len({item["source_document"] for item in documents})
        >= manifest["minimum_source_documents"]
        >= 2
    )
    assert manifest["final_structure_schema_version"] == 2
    for document in documents:
        source = PROJECT_ROOT / document["source_path"]
        expected = document["expected"]
        assert document["full_page"] is True
        assert document["cropped"] is False
        assert document["provenance"]["rights_basis"]
        assert source.is_file()
        assert _digest(source) == document["sha256"]
        assert expected["structure_id"] != "pending"
        assert expected["preview_sha256"] != "pending"
        assert expected["source_size_px"][0] > 0
        assert expected["source_size_px"][1] > 0


def test_ci_runs_the_mandatory_real_document_regression() -> None:
    workflow = (
        PROJECT_ROOT.parent / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")

    assert "scripts/run_real_document_regression.py" in workflow
    assert "--manifest tests/real_regression/manifest.json" in workflow
