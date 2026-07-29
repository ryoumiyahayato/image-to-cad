from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "tests" / "real_regression" / "manifest.json"
REQUIRED_ANNOTATION_COLLECTIONS = {
    "text_regions_to_preserve",
    "true_breaks_to_repair",
    "forbidden_connection_regions",
    "logo_regions",
    "signature_regions",
    "key_rois",
}


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_real_document_regression_set_is_nonempty_complete_and_immutable() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    documents = manifest["documents"]

    assert manifest["schema_version"] == 2
    assert len(documents) >= manifest["minimum_documents"] >= 10
    assert (
        len({item["source_document"] for item in documents})
        >= manifest["minimum_source_documents"]
        >= 3
    )
    assert (
        len(
            {
                (item["source_document"], item["page"]["number"])
                for item in documents
            }
        )
        >= manifest["minimum_unique_pages"]
        >= 10
    )
    assert manifest["final_structure_schema_version"] == 2
    covered_categories = {
        category
        for document in documents
        for category in document["coverage_categories"]
    }
    assert set(manifest["required_categories"]) <= covered_categories
    assert set(manifest["required_dpis"]) <= {
        document["page"]["dpi"] for document in documents
    }
    for document in documents:
        source = PROJECT_ROOT / document["source_path"]
        original = PROJECT_ROOT / document["original_path"]
        expected = document["expected"]
        assert document["full_page"] is True
        assert document["cropped"] is False
        assert document["enable_ocr"] is True
        assert not ({"skip", "skipped", "xfail"} & set(document))
        assert document["provenance"]["rights_basis"]
        assert document["usage_authorization"]["scope"]
        assert document["usage_authorization"]["authorization_basis"]
        assert (
            document["usage_authorization"]["redistribution_allowed"] is False
        )
        assert document["human_acceptance_notes"]
        assert REQUIRED_ANNOTATION_COLLECTIONS <= set(document["annotations"])
        assert document["annotations"]["text_regions_to_preserve"]
        assert document["annotations"]["key_rois"]
        assert document["expected_object_types"]
        assert source.is_file()
        assert original.is_file()
        assert _digest(source) == document["sha256"]
        assert _digest(original) == document["original_sha256"]
        assert expected["structure_id"] != "pending"
        assert expected["preview_sha256"] != "pending"
        assert expected["content_audit_sha256"] != "pending"
        assert expected["source_size_px"][0] > 0
        assert expected["source_size_px"][1] > 0


def test_ci_runs_the_mandatory_real_document_regression() -> None:
    workflow = (
        PROJECT_ROOT.parent / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")

    assert "scripts/run_real_document_regression.py" in workflow
    assert "--manifest tests/real_regression/manifest.json" in workflow
    assert "--record-baseline-to" not in workflow
