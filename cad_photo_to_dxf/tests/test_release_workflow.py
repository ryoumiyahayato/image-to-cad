from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_preserves_qualification_and_least_privilege() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "FREECAD_APT_VERSION: 0.19.2+dfsg1-3ubuntu1" in source
    assert "scripts/validate_fixtures.py" in source
    assert "scripts/run_fixture_benchmarks.py" in source
    assert "--minimum 1" in source
    assert "nonempty_shape_count" in source
    assert "environment: production-release" in source
    assert "needs:\n      - qualify\n      - build" in source
    assert "build:\n    needs: qualify" in source
    assert source.count("contents: write") == 1
    assert source.count("contents: read") >= 1


def test_release_workflow_does_not_restore_destructive_publishing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").casefold()
    forbidden = (
        "gh release delete",
        "git push --force",
        "git push -f",
        "git tag -d",
        "git push origin :refs/tags",
        "base64 --decode",
        "build-v1.2.0",
    )
    for fragment in forbidden:
        assert fragment not in source


def test_release_workflow_builds_and_publishes_exact_tag_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert source.count("ref: ${{ github.sha }}") >= 3
    assert "--verify-tag" in source
    assert "--target \"$GITHUB_SHA\"" in source
    assert "Refuse to overwrite an existing release" in source
