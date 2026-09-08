from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
MANIFEST_PATH = (
    PROJECT_ROOT / "tests" / "real_regression" / "draftsman_golden_manifest.json"
)
CURRENT_STATE_PATH = REPOSITORY_ROOT / "docs" / "draftsman" / "CURRENT_STATE.md"
REPLAY_MATRIX_PATH = REPOSITORY_ROOT / "docs" / "draftsman" / "REPLAY_MATRIX.md"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_draftsman_golden_manifest_resolves_tracked_source_hashes() -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "draftsman-golden-manifest-v1"
    sources = payload["golden_sources"]
    assert {item["canonical_id"] for item in sources} == {
        "environment-plan-page-003-150dpi",
        "warehouse-index-page-001-600dpi",
    }

    for item in sources:
        source = REPOSITORY_ROOT / item["tracked_source_path"]
        assert source.is_file()
        assert _sha256(source) == item["sha256"]
        assert item["related_replay_slices"]
        assert item["role"]

    original = REPOSITORY_ROOT / sources[0]["original_document"][
        "tracked_source_path"
    ]
    assert original.is_file()
    assert _sha256(original) == sources[0]["original_document"]["sha256"]


def test_canonical_state_and_replay_matrix_cover_fresh_clone_contract() -> None:
    current = CURRENT_STATE_PATH.read_text(encoding="utf-8")
    replay = REPLAY_MATRIX_PATH.read_text(encoding="utf-8")

    for required in (
        "SOURCE IS TRUTH",
        "Detection Fragment != Logical Entity != Final CAD Entity",
        "SEMANTIC_IDENTITY_UNVERIFIED",
        "STILL_TOO_NOISY",
        "Production semantic delta",
        "local-artifacts",
        "B1",
    ):
        assert required in current

    for required in (
        "VS1",
        "VS2",
        "VS3",
        "family audit",
        "E1",
        "T1",
        "U1",
        "QA1",
        "QA2-S1",
        "QA2-S2",
    ):
        assert required in replay

    assert "`local-artifacts` is an optional disposable output location" in replay
    assert "local-artifacts/review" not in replay
