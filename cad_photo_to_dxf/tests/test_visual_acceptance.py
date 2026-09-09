from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.final_structure import build_final_structure
from app.visual_acceptance import (
    build_visual_acceptance_images,
    write_visual_acceptance_artifacts,
)


def _structure(*, width: int = 120, height: int = 80):
    contour = np.full((height, width), 255, dtype=np.uint8)
    preview = contour.copy()
    preview[20:24, 15:95] = 0
    preview[35:60, 65:69] = 0
    return build_final_structure(
        source_size_px=(width, height),
        contour_binary=contour,
        contours=(),
        preview_binary=preview,
        provenance={"test": "visual_acceptance"},
    )


def test_visual_acceptance_requires_same_page_coordinates() -> None:
    source = np.full((79, 120, 3), 255, dtype=np.uint8)
    with pytest.raises(ValueError, match="identical page coordinates"):
        build_visual_acceptance_images(source, _structure())


def test_visual_acceptance_uses_canonical_preview_without_resizing() -> None:
    source = np.full((80, 120, 3), 255, dtype=np.uint8)
    original, reconstructed, overlay = build_visual_acceptance_images(
        source,
        _structure(),
    )

    assert original.shape == source.shape
    assert reconstructed.shape == source.shape
    assert overlay.shape == source.shape
    assert np.any(reconstructed != 255)
    assert np.any(overlay != original)


def test_visual_acceptance_artifacts_bind_structure_identity(tmp_path: Path) -> None:
    source = np.full((80, 120, 3), 255, dtype=np.uint8)
    structure = _structure()

    artifacts = write_visual_acceptance_artifacts(
        source,
        structure,
        root=tmp_path,
        source_label="DEV sample page 1",
        review={"verdict": "FAIL", "problems": ["missing_content"]},
    )

    for path in (
        artifacts.original_path,
        artifacts.reconstructed_path,
        artifacts.overlay_path,
        artifacts.overview_path,
        artifacts.review_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0

    payload = json.loads(artifacts.review_path.read_text(encoding="utf-8"))
    assert payload["structure_id"] == structure.structure_id
    assert payload["human_review"]["verdict"] == "FAIL"
    assert payload["final_entity_summary"]["warnings"] == 0
