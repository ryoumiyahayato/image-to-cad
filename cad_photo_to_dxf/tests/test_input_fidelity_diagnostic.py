from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.input_fidelity_diagnostic import (
    FidelityCase,
    build_case_trace,
    build_overview,
)


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def _fixture_case(tmp_path: Path, *, split: str = "dev") -> FidelityCase:
    bundle = tmp_path / "bundle"
    vqa = tmp_path / "vqa"
    bundle.mkdir()
    vqa.mkdir()
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 10), (20, 70), (0, 0, 0), 3)
    mask = np.zeros((80, 120), dtype=np.uint8)
    cv2.line(mask, (20, 10), (20, 70), 255, 3)
    stages: dict[str, list[tuple[str, np.ndarray]]] = {
        "original_page": [("", image)],
        "original_gray": [("", cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))],
        "normalized_background": [("", cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))],
        "binary_foreground": [("", cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))],
        "raw_line_candidates": [
            ("prepared", mask),
            ("edge-proposals-before-recenter", mask),
        ],
        "line_candidates_text_filtered": [
            ("before-text-filter", mask),
            ("after-text-filter", mask),
        ],
        "text_candidate_mask": [("line-filter-protection", mask)],
        "structural_line_candidate_mask": [("post-filter-candidates", mask)],
    }
    manifest_stages = []
    for stage_key, artifacts in stages.items():
        artifact_payload = []
        for index, (role, stage_image) in enumerate(artifacts):
            image_path = bundle / f"{stage_key}-{index}.png"
            metadata_path = bundle / f"{stage_key}-{index}.json"
            _write_image(image_path, stage_image)
            metadata_path.write_text(
                json.dumps({"observation": {"role": role}}),
                encoding="utf-8",
            )
            artifact_payload.append(
                {
                    "path": image_path.name,
                    "metadata_path": metadata_path.name,
                    "role": role,
                }
            )
        manifest_stages.append({"stage_key": stage_key, "artifacts": artifact_payload})
    for filename in ("reconstructed.png", "overlay.png"):
        _write_image(vqa / filename, image)
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "input": {
                    "path": f"C:/corpus-v1/{split}/example.png",
                    "source_size_px": [120, 80],
                    "sha256": "source-hash",
                },
                "structure_id": "structure-id",
                "stages": manifest_stages,
            }
        ),
        encoding="utf-8",
    )
    return FidelityCase(
        "case_1",
        "DEV-SG-001",
        "line",
        bundle,
        vqa,
        (10, 10, 80, 50),
        (20, 15, 20, 55),
        "synthetic continuous line",
        "NONE OBSERVED",
        "NO DEFECT",
        "The target stays continuous.",
    )


def test_trace_uses_fixed_source_coordinates_and_generates_artifact(
    tmp_path: Path,
) -> None:
    case = _fixture_case(tmp_path)
    output = tmp_path / "trace.png"

    report = build_case_trace(case, output)

    rendered = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert rendered is not None
    assert rendered.shape == (838, 2100, 3)
    assert report["roi"] == [10, 10, 80, 50]
    assert report["target"] == [20, 15, 20, 55]
    assert report["structure_id"] == "structure-id"


def test_overview_contains_three_fixed_roi_traces(tmp_path: Path) -> None:
    case = _fixture_case(tmp_path)
    trace = tmp_path / "trace.png"
    build_case_trace(case, trace)
    output = tmp_path / "overview.png"

    build_overview([(case, trace), (case, trace), (case, trace)], output)

    rendered = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert rendered is not None
    assert rendered.shape == (1256, 2100, 3)


def test_protected_split_fails_closed_before_artifact_generation(
    tmp_path: Path,
) -> None:
    case = _fixture_case(tmp_path, split="locked_blind")
    output = tmp_path / "forbidden.png"

    with pytest.raises(ValueError, match="not DEV|protected split"):
        build_case_trace(case, output)

    assert not output.exists()
